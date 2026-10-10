# -*- coding: utf-8 -*-
"""
utilidades/evaluar_lmp_cuotas.py - que tan preciso es el modelo de LMP en temporadas completas, y contra las cuotas.

1. Modelo por temporada (sin ver el futuro): para cada temporada se entrena la logistica de ganador (modelos/beisbol.py)
   solo con los juegos ANTERIORES a su primer juego, y se le suma la capa frio contra caliente (S4, beta de
   modelos/capas_ausencias_minutos.json), como en produccion. Total esperado con modelos/beisbol.predecir.
   Metricas: acierto del favorito del modelo, log-loss y Brier contra la tasa de local, calibracion por rangos, mitades.
2. Contra el mercado (si hay cuotas): semillas/lmp_cuotas_sgo.csv (colectores/sgo_historico.py) o --cuotas <csv> con
   columnas fecha, home, away, ml_home, ml_away [, total, over, under, casa]; momios americanos o decimales.
   Casa preferida: pinnacle, si no consenso, si no la primera. Mide:
     - log-loss del mercado sin vig, del modelo y de la mezcla de produccion (decidir.py: 75 % mercado + 25 % modelo en logit)
     - apuestas a 1 u, cuota >= 1.80, por EV del modelo y de la mezcla (umbral 2/4/6 %): acierto, unidades, ROI, mitades
     - totales: over/under del modelo contra la linea (acierto y unidades a 1 u con el momio de la casa)

Uso (PowerShell):
    cd C:\\Edgeline_repo
    git pull
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/evaluar_lmp_cuotas.py                       # temporadas 2024-25 y 2025-26
    python utilidades/evaluar_lmp_cuotas.py --cuotas C:\\ruta\\mis_cuotas_lmp.csv
Escribe salida/evaluacion_lmp.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io as _io, json, math, os, sys, unicodedata
from collections import defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO)
from nucleo import io  # noqa: E402

CUOTA_MIN = 1.80
APODOS = ["aguilas", "algodoneros", "caneros", "charros", "jaguares", "mayos", "naranjeros", "tomateros", "venados", "yaquis",
          "tucson"]


def _apodo(nombre):
    s = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode().lower()
    for a in APODOS:
        if a in s:
            return "mayos" if a == "tucson" else a
    for k, a in (("mexicali", "aguilas"), ("guasave", "algodoneros"), ("mochis", "caneros"), ("jalisco", "charros"),
                 ("nayarit", "jaguares"), ("navojoa", "mayos"), ("hermosillo", "naranjeros"), ("culiacan", "tomateros"),
                 ("mazatlan", "venados"), ("obregon", "yaquis")):
        if k in s:
            return a
    return s.strip()


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _dec(x):
    try:
        v = float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    if 1.0 < v < 30 and "." in str(x):          # ya es decimal
        return v
    return 1 + (v / 100 if v > 0 else 100 / -v)


def _season_start(G):
    """primer juego de cada temporada (columna season)."""
    ini = {}
    for r in G:
        s = str(r.get("season") or r["game_date"][:4])
        ini[s] = min(ini.get(s, "9999"), r["game_date"][:10])
    return ini


def predicciones(temporadas):
    from nucleo import features as Fz
    from modelos import beisbol as B
    try:
        beta_s4 = json.load(_io.open(os.path.join(CODIGO, "modelos", "capas_ausencias_minutos.json"), encoding="utf-8"))["beisbol_S4"]["beta"]
    except Exception:
        beta_s4 = 0.0
    feats, _ = Fz.construir("beisbol", "LMP", 5)
    lg = io.norm("LMP")
    G = sorted([r for r in feats if r["league"] == lg and r.get("y_home") is not None], key=lambda r: r["game_date"])
    # racha por equipo (para S4) desde el orden de los juegos
    hist = defaultdict(list)          # equipo -> [(fecha, gano)]
    racha = {}
    for r in G:
        f = r["game_date"][:10]
        for eq in (r["home"], r["away"]):
            L = [x for x in hist[eq] if (dt.date.fromisoformat(f) - dt.date.fromisoformat(x[0])).days <= 200]
            ult = L[-3:]
            ok = len(ult) == 3 and all((dt.date.fromisoformat(ult[i + 1][0]) - dt.date.fromisoformat(ult[i][0])).days <= 20
                                       for i in range(2)) and (dt.date.fromisoformat(f) - dt.date.fromisoformat(ult[-1][0])).days <= 20
            racha[(r["gamePk"], eq)] = ("frio" if ok and not any(x[1] for x in ult) else ("cal" if ok and all(x[1] for x in ult) else None))
        yh = r["y_home"]
        hist[r["home"]].append((f, yh == 1)); hist[r["away"]].append((f, yh == 0))
    ini = _season_start(G)
    out = []
    for s in temporadas:
        s = str(s)
        if s not in ini:
            print("  temporada %s: sin juegos en los datos" % s); continue
        d0 = ini[s]
        tr = [r for r in G if r["game_date"][:10] < d0]
        te = [r for r in G if str(r.get("season") or r["game_date"][:4]) == s]
        if len(tr) < 600 or not te:
            print("  temporada %s: poca historia" % s); continue
        mod = B.entrenar_logistica(tr)
        tasa_local = sum(r["y_home"] for r in tr) / len(tr)
        for r in te:
            p0 = B.prob(mod, r)
            rh, ra = racha.get((r["gamePk"], r["home"])), racha.get((r["gamePk"], r["away"]))
            x = 1 if (rh == "frio" and ra == "cal") else (-1 if (ra == "frio" and rh == "cal") else 0)
            p = _sig(_lg(p0) + beta_s4 * x)
            try:
                pr = B.predecir(mod, r) or {}
            except Exception:
                pr = {}
            tot = pr.get("total")
            out.append(dict(temporada=s, fecha=r["game_date"][:10], gp=str(r["gamePk"]), home=r["home"], away=r["away"],
                            p=p, p_base=p0, s4=x, y=r["y_home"], tasa_local=tasa_local, total_modelo=tot,
                            runs_total=r.get("total")))
    return out


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _z(d):
    n = len(d)
    if n < 30:
        return None
    m = sum(d) / n; sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
    return round(m / sd * n ** 0.5, 2) if sd > 0 else None


def metricas_modelo(P):
    out = {}
    for s in sorted({x["temporada"] for x in P}) + ["todas"]:
        L = [x for x in P if s == "todas" or x["temporada"] == s]
        if not L:
            continue
        L.sort(key=lambda x: x["fecha"]); h = len(L) // 2
        acierto = sum((x["p"] >= 0.5) == (x["y"] == 1) for x in L) / len(L)
        ll_m = [_ll(x["p"], x["y"]) for x in L]; ll_b = [_ll(x["tasa_local"], x["y"]) for x in L]
        d = [b - m for b, m in zip(ll_b, ll_m)]
        cal = defaultdict(lambda: [0, 0.0, 0])
        for x in L:
            pf = max(x["p"], 1 - x["p"]); yf = x["y"] if x["p"] >= 0.5 else 1 - x["y"]
            k = "50-55" if pf < .55 else ("55-60" if pf < .60 else ("60-65" if pf < .65 else "65+"))
            cal[k][0] += 1; cal[k][1] += pf; cal[k][2] += yf
        out[s] = {"n": len(L), "acierto_favorito_modelo_pct": round(100 * acierto, 1),
                  "local_gana_pct": round(100 * sum(x["y"] for x in L) / len(L), 1),
                  "logloss_modelo": round(sum(ll_m) / len(L), 4), "logloss_tasa_local": round(sum(ll_b) / len(L), 4),
                  "mejora_milesimas": round(1000 * sum(d) / len(d), 2), "z": _z(d),
                  "mitades_milesimas": [round(1000 * sum(d[:h]) / max(h, 1), 2), round(1000 * sum(d[h:]) / max(len(d) - h, 1), 2)],
                  "brier": round(sum((x["p"] - x["y"]) ** 2 for x in L) / len(L), 4),
                  "calibracion_favorito": {k: {"n": v[0], "p_media": round(100 * v[1] / v[0], 1), "real": round(100 * v[2] / v[0], 1)}
                                           for k, v in sorted(cal.items())}}
    return out


def cargar_cuotas(ruta):
    if not ruta or not os.path.exists(ruta):
        return {}
    por = defaultdict(dict)
    with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for x in csv.DictReader(f):
            k = (x["fecha"][:10], _apodo(x["home"]), _apodo(x["away"]))
            por[k][(x.get("casa") or "casa").lower()] = x
    out = {}
    for k, casas in por.items():
        for pref in ("pinnacle", "consenso"):
            if pref in casas and casas[pref].get("ml_home"):
                out[k] = dict(casas[pref], _casa=pref); break
        else:
            c, x = next(iter(casas.items())); out[k] = dict(x, _casa=c)
    return out


def emparejar(P, Q):
    n = 0
    for x in P:
        f = dt.date.fromisoformat(x["fecha"]); h, a = _apodo(x["home"]), _apodo(x["away"])
        for dd in (0, -1, 1):
            q = Q.get(((f + dt.timedelta(days=dd)).isoformat(), h, a))
            if q:
                x["q"] = q; n += 1; break
    return n


def apuestas(L, clave, umbral):
    ap = []
    for x in L:
        dh, da = _dec(x["q"].get("ml_home")), _dec(x["q"].get("ml_away"))
        if not dh or not da:
            continue
        p = x[clave]
        mejor = None
        for lado, pp, c, gano in (("home", p, dh, x["y"] == 1), ("away", 1 - p, da, x["y"] == 0)):
            ev = pp * c - 1
            if c >= CUOTA_MIN and ev >= umbral and (mejor is None or ev > mejor[0]):
                mejor = (ev, c, gano, x["fecha"])
        if mejor:
            ap.append(mejor)
    return ap


def resumen(ap):
    if not ap:
        return {"n": 0}
    ap.sort(key=lambda t: t[3]); u = [(c - 1) if g else -1.0 for ev, c, g, f in ap]; n = len(u); h = n // 2
    return {"n": n, "ganadas": sum(1 for t in ap if t[2]), "acierto_pct": round(100 * sum(1 for t in ap if t[2]) / n, 1),
            "cuota_media": round(sum(t[1] for t in ap) / n, 2), "unidades": round(sum(u), 2), "roi_pct": round(100 * sum(u) / n, 2),
            "z": _z(u), "mitades_unidades": [round(sum(u[:h]), 2), round(sum(u[h:]), 2)]}


def contra_mercado(P):
    L = [x for x in P if x.get("q")]
    for x in L:
        dh, da = _dec(x["q"].get("ml_home")), _dec(x["q"].get("ml_away"))
        if dh and da:
            s = 1 / dh + 1 / da; x["pm"] = (1 / dh) / s
            x["mezcla"] = _sig(0.75 * _lg(x["pm"]) + 0.25 * _lg(x["p"]))
    L = [x for x in L if x.get("pm") is not None]
    if not L:
        return None
    L.sort(key=lambda x: x["fecha"])
    out = {"n": len(L), "casas": sorted({x["q"]["_casa"] for x in L})}
    base = [_ll(x["pm"], x["y"]) for x in L]
    for nombre, k in (("mercado", "pm"), ("modelo", "p"), ("mezcla_75_25", "mezcla")):
        v = [_ll(x[k], x["y"]) for x in L]
        d = [b - m for b, m in zip(base, v)]
        out["logloss_" + nombre] = {"logloss": round(sum(v) / len(v), 4), "vs_mercado_milesimas": round(1000 * sum(d) / len(d), 2), "z": _z(d),
                                    "acierto_favorito_pct": round(100 * sum((x[k] >= .5) == (x["y"] == 1) for x in L) / len(L), 1)}
    for clave in ("p", "mezcla"):
        for u in (0.02, 0.04, 0.06):
            out["apuestas_%s_ev%d" % ("modelo" if clave == "p" else "mezcla", round(u * 100))] = resumen(apuestas(L, clave, u))
    # totales: lado del modelo contra la linea, con el momio de la casa
    tot = []
    for x in L:
        ln, ov, un = x["q"].get("total"), _dec(x["q"].get("over")), _dec(x["q"].get("under"))
        try:
            ln = float(ln)
        except (TypeError, ValueError):
            continue
        if x.get("total_modelo") is None or x.get("runs_total") is None or not ov or not un or x["runs_total"] == ln:
            continue
        over = x["total_modelo"] > ln
        gano = (x["runs_total"] > ln) == over
        c = ov if over else un
        tot.append((abs(x["total_modelo"] - ln), c, gano, x["fecha"]))
    if tot:
        out["totales_lado_modelo"] = resumen(list(tot))
        out["totales_brecha_1_carrera"] = resumen([t for t in tot if t[0] >= 1.0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temporadas", default="2024,2025")
    ap.add_argument("--cuotas", default=os.path.join(CODIGO, "semillas", "lmp_cuotas_sgo.csv"))
    a = ap.parse_args()
    P = predicciones([t.strip() for t in a.temporadas.split(",") if t.strip()])
    res = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "modelo": metricas_modelo(P)}
    print("\nLMP - modelo de ganador por temporada (entrenado solo con temporadas anteriores, + frio/caliente)")
    for s, m in res["modelo"].items():
        print("  %-6s n %4d  acierta el favorito del modelo %5.1f%%  (local gana %5.1f%%)  log-loss %.4f vs tasa local %.4f "
              "-> %+6.2f milesimas (z %s, mitades %s)  Brier %.4f"
              % (s, m["n"], m["acierto_favorito_modelo_pct"], m["local_gana_pct"], m["logloss_modelo"], m["logloss_tasa_local"],
                 m["mejora_milesimas"], m["z"], m["mitades_milesimas"], m["brier"]))
        print("         calibracion (favorito):", m["calibracion_favorito"])
    Q = cargar_cuotas(a.cuotas)
    if Q:
        n = emparejar(P, Q)
        print("\nCuotas: %d partidos en %s, %d emparejados con el modelo" % (len(Q), a.cuotas, n))
        res["contra_mercado"] = contra_mercado(P)
        for k, v in (res["contra_mercado"] or {}).items():
            print("  %-26s %s" % (k, v))
    else:
        print("\nSin archivo de cuotas (%s): solo se midio el modelo." % a.cuotas)
    os.makedirs(os.path.join(CODIGO, "salida"), exist_ok=True)
    json.dump(res, _io.open(os.path.join(CODIGO, "salida", "evaluacion_lmp.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresumen en salida/evaluacion_lmp.json")


if __name__ == "__main__":
    main()
