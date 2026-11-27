# -*- coding: utf-8 -*-
"""
utilidades/registrar_capa_sombra.py - registro en vivo de la capa de angulos en sombra (27-nov-2026).

Por cada partido por jugar con grupo en sombra (hoy: NHL ganador) guarda la p del sistema (mezcla) y la p con la capa en
salida/historial_capa_sombra.csv (una fila por partido: se reescribe hasta que empieza). Con el resultado (datos/hockey.csv)
se mide en vivo si la capa mejora la log-loss: regla de activacion = 300+ juegos, z >= 2 y las dos mitades a favor.

    python utilidades/registrar_capa_sombra.py            (registra)
    python utilidades/registrar_capa_sombra.py --medir    (califica y mide)
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, math, os, sys
AQUI = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(AQUI)
sys.path.insert(0, REPO); sys.path.insert(0, AQUI)
import decidir_v2 as V  # noqa: E402
RUTA = os.path.join(REPO, "salida", "historial_capa_sombra.csv")
ESPN_A_NHL = {"NJ": "NJD", "LA": "LAK", "SJ": "SJS", "TB": "TBL"}    # abreviaturas de ESPN -> datos/hockey.csv
COLS = ["registrado", "liga", "id", "fecha", "hora", "home", "away", "home_abrev", "away_abrev", "p_home_sistema", "p_home_capa", "p_sharp_home"]


def _leer():
    if not os.path.exists(RUTA):
        return []
    with io.open(RUTA, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def registrar():
    with io.open(os.path.join(REPO, "salida", "proximos.json"), encoding="utf-8") as fh:
        D = json.load(fh)
    filas = {(r["liga"], r["id"]): r for r in _leer()}
    ahora = dt.datetime.now(dt.timezone.utc)
    n = 0
    for p in D["partidos"]:
        if p.get("liga") != "nhl" or not p.get("modelo"):
            continue
        try:
            d = V.decidir_mercado(p, "Ganador")
        except Exception:
            continue
        e = next((x for x in (d or {}).get("lados") or [] if x["lado"] == "home"), None)
        if not e or e.get("p_capa_sombra") is None:
            continue
        clave = (p["liga"], str(p["id"]))
        try:
            ini = dt.datetime.fromisoformat("%sT%s:00-06:00" % (p["fecha"], p.get("hora") or "00:00"))
        except Exception:
            ini = None
        if clave in filas and ini is not None and ahora >= ini:
            continue            # ya empezo: se queda el ultimo registro previo
        filas[clave] = {"registrado": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"), "liga": p["liga"], "id": str(p["id"]), "fecha": p["fecha"],
                        "hora": p.get("hora"), "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                        "home_abrev": p["home"].get("abrev"), "away_abrev": p["away"].get("abrev"),
                        "p_home_sistema": e["p_final"], "p_home_capa": e["p_capa_sombra"], "p_sharp_home": e.get("p_sharp")}
        n += 1
    with io.open(RUTA, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader()
        for r in sorted(filas.values(), key=lambda r: (r["fecha"], r["id"])):
            w.writerow({k: r.get(k) for k in COLS})
    print("capa en sombra: %d partidos registrados/actualizados (%d en el historial)" % (n, len(filas)))


def medir():
    res = {}
    with io.open(os.path.join(REPO, "datos", "hockey.csv"), encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("league") == "NHL" and r.get("is_home") == "1" and r.get("goals") not in (None, ""):
                res[(r["game_date"], r["team"], r["opp"])] = 1 if float(r["goals"]) > float(r["goals_opp"]) else 0
    d = []
    for r in _leer():
        y = None
        for k in (0, -1, 1):
            f = (dt.date.fromisoformat(r["fecha"]) + dt.timedelta(days=k)).isoformat()
            y = res.get((f, ESPN_A_NHL.get(r["home_abrev"], r["home_abrev"]), ESPN_A_NHL.get(r["away_abrev"], r["away_abrev"])))
            if y is not None:
                break
        if y is None:
            continue
        ll = lambda p: -(y * math.log(p) + (1 - y) * math.log(1 - p))
        d.append(ll(float(r["p_home_sistema"])) - ll(float(r["p_home_capa"])))
    if len(d) < 2:
        print("capa en sombra: %d juegos calificados" % len(d)); return
    m = sum(d) / len(d); sd = (sum((x - m) ** 2 for x in d) / (len(d) - 1)) ** 0.5
    k = len(d) // 2
    z = m / sd * len(d) ** 0.5 if sd else 0
    m1, m2 = sum(d[:k]) / max(k, 1), sum(d[k:]) / max(len(d) - k, 1)
    ok = len(d) >= 300 and z >= 2 and m1 > 0 and m2 > 0
    print("capa en sombra NHL: n %d, mejora log-loss %+.4f, z %+.2f, mitades %+.4f / %+.4f -> %s" % (
        len(d), m, z, m1, m2, "ACTIVAR (cumple la regla)" if ok else "sigue en sombra"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--medir", action="store_true")
    a = ap.parse_args()
    medir() if a.medir else registrar()
