# -*- coding: utf-8 -*-
"""
utilidades/minar_cuotas_altas.py - capa de decision para apostar a cuota de 1.80 a 3.00 (futbol y NFL), con cuotas reales.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_cuotas_altas.md
Reglas fijas sobre la probabilidad as-of del modelo; ROI a 1 u al mejor precio (futbol) o al cierre (NFL);
IC por bootstrap y P(ROI > 0) con bootstrap bayesiano. La brecha contra Pinnacle se reporta, no filtra.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_cuotas_altas.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402

LO, HI = 1.80, 3.00
RNG = np.random.default_rng(7)


def _dec(ml):
    if ml is None or ml == 0: return None
    return 1 + ml / 100.0 if ml > 0 else 1 + 100.0 / -ml


def apuestas_futbol(filas):
    out = []
    for r in filas:
        c = r.get("cuotas")
        if not c or not c.get("res"): continue
        mx, ps = c["max"], c["pin"]
        probs = {"H": r["p"], "D": r.get("pdraw"), "A": r.get("paway")}
        if any(v is None for v in probs.values()): continue
        fav = max(probs, key=probs.get)
        pin_nv = None
        if ps and all(ps):
            s = sum(1 / o for o in ps); pin_nv = {k: (1 / o) / s for k, o in zip("HDA", ps)}
        for i, lado in enumerate("HDA"):
            o = mx[i] if mx else None
            if not o: continue
            descanso = r.get("F1") or 0.0
            ang = (descanso >= 1 / 3 - 1e-9) if lado == "H" else ((descanso <= -1 / 3 + 1e-9) if lado == "A" else False)
            out.append(dict(fecha=r["fecha"], cuota=o, p=probs[lado], gana=(c["res"] == lado), fav=(lado == fav), ang=ang,
                            brecha=(pin_nv[lado] * o - 1) if pin_nv else None, liga=r.get("liga")))
    return out


def apuestas_nfl(filas):
    out = []
    for r in filas:
        mh, ma = _dec(r.get("ml_h")), _dec(r.get("ml_a"))
        if not mh or not ma: continue
        for lado, o, p, gana in (("H", mh, r["p"], r["y"] == 1), ("A", ma, 1 - r["p"], r["y"] == 0)):
            out.append(dict(fecha=r["fecha"], cuota=o, p=p, gana=gana, fav=(p >= 0.5), ang=(lado == "H"), brecha=None, liga="NFL"))
    return out


def reglas():
    en = lambda a: LO <= a["cuota"] <= HI
    return [("R0 todo 1.80-3.00", lambda a: en(a)),
            ("R1 modelo > lo que pide la cuota", lambda a: en(a) and a["p"] > 1 / a["cuota"]),
            ("R2 modelo con 3 pp de margen", lambda a: en(a) and a["p"] - 1 / a["cuota"] >= 0.03),
            ("R3 favorito del modelo", lambda a: en(a) and a["fav"]),
            ("R4 R2 + angulo a favor", lambda a: en(a) and a["p"] - 1 / a["cuota"] >= 0.03 and a["ang"])]


def medir(A):
    if not A: return None
    g = np.array([a["cuota"] - 1 if a["gana"] else -1.0 for a in A]); o = np.array([a["cuota"] for a in A])
    w = np.array([1.0 if a["gana"] else 0.0 for a in A]); n = len(A)
    boot = np.array([g[RNG.integers(0, n, n)].mean() for _ in range(2000)])
    bayes = RNG.dirichlet(np.ones(n), 2000) @ g
    br = [a["brecha"] for a in A if a["brecha"] is not None]
    anios = max(1.0, (np.datetime64(A[-1]["fecha"][:10]) - np.datetime64(A[0]["fecha"][:10])).astype(int) / 365.25)
    return {"n": n, "por_anio": round(n / anios, 1), "acierto": round(100 * w.mean(), 1), "cuota_media": round(float(o.mean()), 2),
            "equilibrio": round(100 * n / o.sum(), 1), "roi": round(100 * g.mean(), 2),
            "ic95": [round(100 * float(np.percentile(boot, 2.5)), 2), round(100 * float(np.percentile(boot, 97.5)), 2)],
            "p_roi_pos": round(float((bayes > 0).mean()), 3), "brecha_media": round(100 * float(np.mean(br)), 2) if br else None}


def correr(nombre, A):
    A.sort(key=lambda a: a["fecha"])
    fechas = sorted({a["fecha"] for a in A}); corte = fechas[int(len(fechas) * 0.7)]
    print("\n%s | %d lados con cuota | prueba desde %s" % (nombre, len(A), corte))
    res = {}
    for nom, f in reglas():
        S = [a for a in A if f(a)]
        ex, te = medir([a for a in S if a["fecha"] < corte]), medir([a for a in S if a["fecha"] >= corte])
        if not te or not ex:
            print("  %-34s sin apuestas" % nom); continue
        ver = "pasa" if (te["n"] >= 300 and te["roi"] > 0 and te["p_roi_pos"] >= 0.90 and ex["roi"] > 0) else (
            "muestra insuficiente" if te["n"] < 300 else "no pasa")
        res[nom] = {"explorar": ex, "prueba": te, "veredicto": ver}
        print("  %-34s 70%%: n %5d ROI %+6.2f%% | 30%%: n %5d (%5.1f/año) acierto %5.1f%% cuota %.2f equil %5.1f%% ROI %+6.2f%% IC [%+.1f, %+.1f] P(ROI>0) %.2f%s -> %s" % (
            nom, ex["n"], ex["roi"], te["n"], te["por_anio"], te["acierto"], te["cuota_media"], te["equilibrio"], te["roi"],
            te["ic95"][0], te["ic95"][1], te["p_roi_pos"], ("  brecha %+.1f%%" % te["brecha_media"]) if te["brecha_media"] is not None else "",
            ver.upper()))
    return res


def main():
    M.evaluar = lambda *a, **k: None
    M.correr_futbol(); M.correr_americano("NFL")
    out = {"futbol": correr("FUTBOL (mejor precio)", apuestas_futbol(M.ULTIMO["FUTBOL"][0])),
           "nfl": correr("NFL (cierre)", apuestas_nfl(M.ULTIMO["NFL"][0]))}
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_cuotas_altas_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresultados en", ruta)


if __name__ == "__main__":
    main()
