# -*- coding: utf-8 -*-
"""
utilidades/minar_ganador_cuota.py - elegir al ganador a cuota decente (trabajo/minar/2026-10-10_ganador_cuota.md).

Apuesta 1 u al lado que elige el modelo (as-of) cuando la cuota es >= 1.70, con 6 reglas (E1-E6), y mide unidades, ROI,
z, mitades, acierto contra el de equilibrio, CLV (futbol) y rango de cuota. Futbol 7 ligas y NFL con cuotas historicas;
2026 en vivo para los demas deportes (descriptivo).

    python utilidades/minar_ganador_cuota.py [--solo futbol,nfl,vivo]
Escribe trabajo/minar/2026-10-10_ganador_cuota_resultados.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, io as _io, json, math, os, sys
from collections import defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
import metamodelo as MT  # noqa: E402  (filas en cache y utilidades)

CUOTA_MIN = 1.70
RANGOS = ((1.70, 2.10), (2.10, 3.00), (3.00, 99.0))
SALIDA = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_ganador_cuota_resultados.json")


def _n(x):
    return MT._n(x)


# ------------------------------------------------------------------ candidatos por partido
def partidos_futbol(filas, fuente):
    """[{fecha, liga, lados:[{lado, p, cuota, y, p_mkt, p_close, ang}]}]; solo local y visita (el empate pierde)."""
    out = []
    for r in filas:
        c = r.get("cu") or {}
        pc = MT._novig(c.get("PSCH"), c.get("PSCD"), c.get("PSCA"))
        pe = MT._novig(c.get("PSH"), c.get("PSD"), c.get("PSA")) or MT._novig(c.get("AvgH"), c.get("AvgD"), c.get("AvgA"))
        lados = []
        for i, (lado, p, k, sg) in enumerate((("H", r["p_h"], "H", 1), ("A", r["p_a"], "A", -1))):
            cu = c.get(("Max" if fuente == "mejor" else "B365") + k)
            if cu is None or p is None:
                continue
            y = int((r["gh"] > r["ga"]) if lado == "H" else (r["ga"] > r["gh"]))
            ang = sum(sg * (r.get(a) or 0) for a in ("F1", "F13", "S1", "S4", "S7"))
            lados.append(dict(lado=lado, p=p, cuota=cu, y=y, p_mkt=(pe[0 if lado == "H" else 2] if pe else None),
                              p_close=(pc[0 if lado == "H" else 2] if pc else None), ang=ang))
        if lados:
            out.append(dict(fecha=str(r["fecha"]), liga=r["liga"], lados=lados))
    return out


def partidos_ou_futbol(filas, fuente):
    """Over/Under 2.5 como 'ganador' de dos lados (over y under)."""
    out = []
    for r in filas:
        c = r.get("cu") or {}
        if r.get("p_over") is None:
            continue
        pre = "Max_" if fuente == "mejor" else "B365_"
        pe = MT._novig(c.get("P_mas2.5"), c.get("P_menos2.5")); pc = MT._novig(c.get("PC_mas2.5"), c.get("PC_menos2.5"))
        tot = r["gh"] + r["ga"]; lados = []
        for i, (lado, p, k) in enumerate((("over", r["p_over"], "mas2.5"), ("under", 1 - r["p_over"], "menos2.5"))):
            cu = c.get(pre + k)
            if cu is None:
                continue
            lados.append(dict(lado=lado, p=p, cuota=cu, y=int((tot > 2.5) == (lado == "over")), p_mkt=(pe[i] if pe else None),
                              p_close=(pc[i] if pc else None), ang=0))
        if lados:
            out.append(dict(fecha=str(r["fecha"]), liga=r["liga"], lados=lados))
    return out


def partidos_nfl(filas):
    out = []
    for r in filas:
        dh, da = MT._dec_ml(r.get("ml_h")), MT._dec_ml(r.get("ml_a"))
        p = MT._novig(dh, da)
        if not p or r.get("p") is None:
            continue
        lados = []
        for i, (lado, pm, cu, sg) in enumerate((("home", r["p"], dh, 1), ("away", 1 - r["p"], da, -1))):
            ang = sum(sg * (r.get(a) or 0) for a in ("S1", "S4", "S7"))
            lados.append(dict(lado=lado, p=pm, cuota=cu, y=int((r["y"] == 1) == (lado == "home")), p_mkt=p[i], p_close=p[i], ang=ang))
        out.append(dict(fecha=str(r["fecha"])[:10], liga="NFL", lados=lados))
    return out


def partidos_vivo():
    rp = os.path.join(CODIGO, "salida", "historial_predicciones_calificado.csv")
    por = defaultdict(list)
    for r in csv.DictReader(_io.open(rp, encoding="utf-8-sig")):
        if r["mercado"] != "Ganador" or r["estado"] != "calificado":
            continue
        pm, c = _n(r["p_modelo"]), MT._dec_ml(r["cuota"])
        if pm is None or c is None:
            continue
        por[(r["liga"], r["id"], r["fecha"])].append(dict(lado=r["lado"], p=pm, cuota=c, y=int(r["acierto"] == "1"),
                                                          p_mkt=_n(r["p_mercado"]), p_close=None, ang=0))
    return [dict(fecha=k[2], liga=k[0], lados=v) for k, v in por.items()]


# ------------------------------------------------------------------ reglas
def elegir(partido, regla):
    L = [s for s in partido["lados"] if s["cuota"] is not None]
    if not L:
        return None
    ev = lambda s: s["p"] * s["cuota"] - 1
    if regla == "E4":
        cand = [s for s in L if s["cuota"] >= CUOTA_MIN and ev(s) >= 0.05]
        return max(cand, key=ev) if cand else None
    fav = max(L, key=lambda s: s["p"])
    if fav["cuota"] < CUOTA_MIN:
        return None
    if regla == "E1":
        return fav
    if regla == "E2":
        return fav if ev(fav) >= 0 else None
    if regla == "E3":
        return fav if ev(fav) >= 0.05 else None
    if regla == "E5":
        return fav if (ev(fav) >= 0 and fav["ang"] >= 1) else None
    if regla == "E6":
        return fav if (ev(fav) >= 0.05 and fav["p_mkt"] is not None and fav["p"] - fav["p_mkt"] <= 0.10) else None
    return None


REGLAS = ("E1", "E2", "E3", "E4", "E5", "E6")


def resumen(ap):
    if not ap:
        return {"n": 0}
    ap = sorted(ap, key=lambda a: a["fecha"]); n = len(ap)
    u = [(a["cuota"] - 1) if a["y"] else -1.0 for a in ap]
    m = sum(u) / n; sd = (sum((x - m) ** 2 for x in u) / max(n - 1, 1)) ** 0.5
    h = n // 2
    cm = sum(a["cuota"] for a in ap) / n
    out = {"n": n, "acierto_pct": round(100 * sum(a["y"] for a in ap) / n, 1),
           "equilibrio_pct": round(100 * sum(1 / a["cuota"] for a in ap) / n, 1),
           "p_modelo_pct": round(100 * sum(a["p"] for a in ap) / n, 1),
           "cuota_media": round(cm, 2), "unidades": round(sum(u), 1), "roi_pct": round(100 * m, 2),
           "z": round(m / sd * n ** 0.5, 2) if sd > 0 else None,
           "mitades_u": [round(sum(u[:h]), 1), round(sum(u[h:]), 1)], "desde": ap[0]["fecha"][:10], "hasta": ap[-1]["fecha"][:10]}
    cl = [a["cuota"] * a["p_close"] - 1 for a in ap if a.get("p_close")]
    if len(cl) >= 30:
        mc = sum(cl) / len(cl); sdc = (sum((x - mc) ** 2 for x in cl) / (len(cl) - 1)) ** 0.5
        out["clv_pct"] = round(100 * mc, 2); out["z_clv"] = round(mc / sdc * len(cl) ** 0.5, 2) if sdc > 0 else None
    out["veredicto"] = "pasa" if (n >= 300 and out["z"] is not None and out["z"] >= 2.0 and min(out["mitades_u"]) > 0) else (
        "muestra corta" if n < 300 else "no pasa")
    return out


def evaluar(nombre, partidos):
    res = {"partidos": len(partidos), "reglas": {}}
    ligas = sorted({p["liga"] for p in partidos})
    print("\n" + "=" * 110 + "\n%s: %d partidos con cuota (%s)" % (nombre, len(partidos), ", ".join(ligas)))
    for rg in REGLAS:
        ap = []
        for p in partidos:
            s = elegir(p, rg)
            if s:
                ap.append(dict(s, fecha=p["fecha"], liga=p["liga"]))
        o = {"junto": resumen(ap), "ligas": {}, "rangos": {}}
        if len(ligas) > 1:
            for lg in ligas:
                o["ligas"][lg] = resumen([a for a in ap if a["liga"] == lg])
        for a0, a1 in RANGOS:
            o["rangos"]["%.2f-%.2f" % (a0, a1)] = resumen([a for a in ap if a0 <= a["cuota"] < a1])
        res["reglas"][rg] = o
        j = o["junto"]
        if j["n"]:
            print("  %s junto  n %5d  acierto %5.1f%% (equilibrio %5.1f%%, modelo %5.1f%%)  cuota %.2f  u %+7.1f  ROI %+6.2f%%  z %5s  mitades %s  %s%s"
                  % (rg, j["n"], j["acierto_pct"], j["equilibrio_pct"], j["p_modelo_pct"], j["cuota_media"], j["unidades"], j["roi_pct"],
                     j["z"], j["mitades_u"], j["veredicto"], ("  CLV %+.2f%% (z %s)" % (j["clv_pct"], j["z_clv"])) if "clv_pct" in j else ""))
            for lg, x in o["ligas"].items():
                if x["n"]:
                    print("      %-12s n %5d  acierto %5.1f%% (eq %5.1f%%)  u %+7.1f  ROI %+6.2f%%  z %5s  mitades %s  %s"
                          % (lg, x["n"], x["acierto_pct"], x["equilibrio_pct"], x["unidades"], x["roi_pct"], x["z"], x["mitades_u"], x["veredicto"]))
            for rgo, x in o["rangos"].items():
                if x["n"]:
                    print("      cuota %-10s n %5d  acierto %5.1f%% (eq %5.1f%%)  u %+7.1f  ROI %+6.2f%%  z %5s"
                          % (rgo, x["n"], x["acierto_pct"], x["equilibrio_pct"], x["unidades"], x["roi_pct"], x["z"]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="futbol,nfl,vivo")
    ap.add_argument("--cache", default=os.path.join(MT.BASE, "datos", "cache"))
    a = ap.parse_args()
    solo = {x.strip() for x in a.solo.split(",")}
    out = {"cuota_min": CUOTA_MIN, "resultados": {}}
    if "futbol" in solo:
        F = MT._filas("futbol", a.cache)
        for fuente in ("bet365", "mejor"):
            out["resultados"]["futbol_" + fuente] = evaluar("FUTBOL ganador, cuota %s temprana" % fuente, partidos_futbol(F, fuente))
            out["resultados"]["futbol_ou_" + fuente] = evaluar("FUTBOL Over/Under 2.5, cuota %s temprana" % fuente, partidos_ou_futbol(F, fuente))
    if "nfl" in solo:
        out["resultados"]["nfl_cierre"] = evaluar("NFL ganador, moneyline de cierre", partidos_nfl(MT._filas("nfl", a.cache)))
    if "vivo" in solo:
        out["resultados"]["vivo_2026"] = evaluar("2026 EN VIVO (todas las ligas, cuota al registrar)", partidos_vivo())
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    k = sum(len(r["reglas"]) * (1 + len([1 for x in next(iter(r["reglas"].values()))["ligas"]])) for r in out["resultados"].values())
    out["k"] = k
    json.dump(out, _io.open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nk = %d pruebas (falsos 'pasa' esperados ~ %.1f). Escrito %s" % (k, k * 0.023, SALIDA))


if __name__ == "__main__":
    main()
