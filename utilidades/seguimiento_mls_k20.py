"""Congela predicciones MLS k=6 y k=20 antes del inicio y resuelve después.

EDGELINE_BASE=$PWD python utilidades/seguimiento_mls_k20.py registrar
EDGELINE_BASE=$PWD python utilidades/seguimiento_mls_k20.py resolver

Solo referencia: no cambia probabilidades, mercados ni picks publicados.
"""
import datetime as dt
import json
import math
import os
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modelos import futbol
from nucleo import equipos

BASE = os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(BASE, "modelos", "seguimiento_mls_k20.json")
FUENTE = os.path.join(BASE, "salida", "resumen", "mls.json")
TZ = ZoneInfo("America/Mexico_City")
K = (6, 20)


def _leer():
    try:
        with open(RUTA, encoding="utf8") as f:
            x = json.load(f)
    except FileNotFoundError:
        x = {"liga": "mls", "k_publicado": 6, "k_candidato": 20,
             "regla": "Registrar solo antes del inicio; no reescribir predicciones; evaluar Brier 1X2, logloss, MAE por equipo y total.",
             "partidos": []}
    if (x["k_publicado"], x["k_candidato"]) != K:
        raise ValueError("El parametro congelado del registro no coincide")
    return x


def _guardar(x):
    with open(RUTA, "w", encoding="utf8") as f:
        json.dump(x, f, ensure_ascii=False, indent=2)


def _predecir(fecha, home, away, k):
    previos = [j for j in futbol._juegos("mls") if j[0] < fecha]
    with patch.object(futbol, "_juegos", return_value=previos), patch.object(futbol, "SHRINK", k):
        st = futbol.entrenar("mls")
        emp = equipos.Emparejador(list(st["eq"]))
        # Solo el monitor conoce este alias: no modifica los picks publicados.
        nombre_h = "Los Angeles FC" if home["nombre"] == "LAFC" else home["nombre"]
        nombre_a = "Los Angeles FC" if away["nombre"] == "LAFC" else away["nombre"]
        h,_ = emp.buscar([nombre_h], home.get("abrev"))
        a,_ = emp.buscar([nombre_a], away.get("abrev"))
        if not h or not a:
            return None
        p = futbol.predecir(st, h, a)
    return {"home_resuelto": h, "away_resuelto": a,
            "p_home": p["p_home"], "p_draw": p["p_draw"], "p_away": p["p_away"],
            "x_home": p["xg_home"], "x_away": p["xg_away"], "total": p["total_esperado"]}


def registrar():
    now = dt.datetime.now(TZ)
    x = _leer(); ids = {str(p["id"]) for p in x["partidos"]}
    with open(FUENTE, encoding="utf8") as f:
        fuente = json.load(f)
    nuevos = 0
    for p in fuente["partidos_lista"]:
        kickoff = dt.datetime.fromisoformat(p["fecha"]+"T"+p["hora"]).replace(tzinfo=TZ)
        if str(p["id"]) in ids or kickoff <= now or p.get("estado") != "Scheduled":
            continue
        base = _predecir(p["fecha"], p["home"], p["away"], K[0])
        cand = _predecir(p["fecha"], p["home"], p["away"], K[1])
        if not base or not cand or (base["home_resuelto"], base["away_resuelto"]) != (cand["home_resuelto"], cand["away_resuelto"]):
            continue
        x["partidos"].append({"id": p["id"], "fecha": p["fecha"], "hora": p["hora"],
                             "inicio_local": kickoff.isoformat(), "registrado_local": now.isoformat(),
                             "fuente_generada": fuente.get("generado"), "home": p["home"]["nombre"],
                             "away": p["away"]["nombre"], "publicado": base, "candidato": cand,
                             "resultado": None})
        ids.add(str(p["id"])); nuevos += 1
    if nuevos:
        _guardar(x)
    print("Nuevas predicciones previas al inicio:", nuevos, "| total registradas:", len(x["partidos"]))


def resolver():
    x = _leer()
    now = dt.datetime.now(TZ)
    juegos = {(f,h["team"],a["team"]): (futbol._f(h.get("goals")), futbol._f(h.get("goals_opp")))
              for f,_,h,a in futbol._juegos("mls")}
    nuevos = 0
    for p in x["partidos"]:
        if p["resultado"] is not None:
            continue
        if now < dt.datetime.fromisoformat(p["inicio_local"]) + dt.timedelta(hours=3):
            continue  # no leer un marcador parcial como resultado final
        b=p["publicado"]
        scores=juegos.get((p["fecha"],b["home_resuelto"],b["away_resuelto"]))
        if scores and None not in scores:
            p["resultado"] = {"home": scores[0], "away": scores[1]}; nuevos += 1
    if nuevos:
        _guardar(x)
    res=[p for p in x["partidos"] if p["resultado"] is not None]
    def metricas(modo):
        if not res:
            return None
        probs = lambda p: [p[modo]["p_home"],p[modo]["p_draw"],p[modo]["p_away"]]
        y = lambda p: 0 if p["resultado"]["home"]>p["resultado"]["away"] else 2 if p["resultado"]["home"]<p["resultado"]["away"] else 1
        n=len(res)
        return {"brier_1x2":sum(sum((q-(i==y(p)))**2 for i,q in enumerate(probs(p)))/3 for p in res)/n,
                "logloss":sum(-math.log(max(probs(p)[y(p)],1e-6)) for p in res)/n,
                "mae_equipo":sum((abs(p[modo]["x_home"]-p["resultado"]["home"])+abs(p[modo]["x_away"]-p["resultado"]["away"]))/2 for p in res)/n,
                "mae_total":sum(abs(p[modo]["total"]-p["resultado"]["home"]-p["resultado"]["away"]) for p in res)/n}
    print(json.dumps({"registrados":len(x["partidos"]),"resueltos":len(res),"nuevos_resueltos":nuevos,
                      "publicado":metricas("publicado"),"candidato":metricas("candidato")},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("registrar","resolver"):
        raise SystemExit("Uso: seguimiento_mls_k20.py registrar|resolver")
    (registrar if sys.argv[1] == "registrar" else resolver)()
