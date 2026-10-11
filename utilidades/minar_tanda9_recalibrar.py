# -*- coding: utf-8 -*-
"""
utilidades/minar_tanda9_recalibrar.py - tanda 9, addendum: recalibracion (Platt) del ganador combinado con ESPN, por liga.
70 % mas viejo para ajustar beta de ESPN y la recalibracion; 30 % final para calificar (b) contra (a).

    python utilidades/minar_tanda9_recalibrar.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import datetime as dt, json, math, os, pickle, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_tanda9 as T9  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_situacionales as M  # noqa: E402


def _lg(p): p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))
def _sig(x): return 1 / (1 + math.exp(-x))
def _ll(p, y): p = min(max(p, 1e-9), 1 - 1e-9); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def platt(xs, ys):
    """logit q = a + b x por Newton."""
    a, b = 0.0, 1.0
    for _ in range(50):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            q = _sig(a + b * x); w = q * (1 - q)
            ga += q - y; gb += (q - y) * x; haa += w; hab += w * x; hbb += w * x * x
        det = haa * hbb - hab * hab
        if det <= 0: break
        da = (hbb * ga - hab * gb) / det; db = (haa * gb - hab * ga) / det
        a -= da; b -= db
        if abs(da) + abs(db) < 1e-10: break
    return a, b


def main():
    ULT = pickle.load(open(os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl"), "rb"))
    cap = {}
    orig = T4.evaluar_agrupado
    T4.evaluar_agrupado = lambda f, cod, nom, liga, s, base="modelo": cap.__setitem__((liga, base), f[0])
    T9.parte_e(ULT, {"ganador": [], "mercado": [], "fuga": [], "totales": [], "estimacion": []})
    T4.evaluar_agrupado = orig
    out = []
    for liga in ("NBA", "NCAAMB", "NCAAFB"):
        R = sorted(cap[(liga, "modelo")], key=lambda r: (str(r["fecha"]), str(r["gp"])))
        i70 = int(len(R) * 0.7); tr, te = R[:i70], R[i70:]
        beta, _ = T4.offset_beta(tr)
        comb = lambda r: _sig(_lg(r["p"]) + beta * (_lg(r["q"]) - _lg(r["p"])))
        a, b = platt([_lg(comb(r)) for r in tr], [r["y"] for r in tr])
        d, P0, P1 = [], [], []
        for r in te:
            p0 = comb(r); p1 = _sig(a + b * _lg(p0))
            d.append(_ll(p0, r["y"]) - _ll(p1, r["y"])); P0.append(p0); P1.append(p1)
        n = len(d); m = sum(d) / n; sd = math.sqrt(sum((v - m) ** 2 for v in d) / (n - 1)); h = n // 2
        z = m / (sd / math.sqrt(n)); m1, m2 = sum(d[:h]) / h, sum(d[h:]) / (n - h)
        Y = [r["y"] for r in te]
        cal0 = sum(P0) / n - sum(Y) / n; cal1 = sum(P1) / n - sum(Y) / n
        tramos = []
        for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)):
            S = [(p0, p1, y) for p0, p1, y in zip(P0, P1, Y) if lo <= max(p0, 1 - p0) < hi]
            if len(S) < 40: continue
            f = lambda p, p0: p if p0 >= 0.5 else 1 - p
            yy = [y if p0 >= 0.5 else 1 - y for p0, p1, y in S]
            tramos.append({"tramo": [lo, hi], "n": len(S), "combinado": round(sum(f(p0, p0) for p0, _, _ in S) / len(S), 3),
                           "recalibrado": round(sum(f(p1, p0) for p0, p1, _ in S) / len(S), 3), "real": round(sum(yy) / len(S), 3)})
        ver = "pasa" if (z >= 2 and m1 > 0 and m2 > 0 and abs(cal1) <= 0.04) else "no pasa"
        o = {"liga": liga, "n_prueba": n, "beta_espn_70": round(beta, 3), "platt_a": round(a, 4), "platt_b": round(b, 4),
             "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2), "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)],
             "calibracion_combinado": round(cal0, 4), "calibracion_recalibrado": round(cal1, 4),
             "logloss_combinado": round(sum(_ll(p, y) for p, y in zip(P0, Y)) / n, 4),
             "logloss_modelo_solo": round(sum(_ll(r["p"], r["y"]) for r in te) / n, 4), "tramos": tramos, "veredicto": ver}
        out.append(o)
        print("%-7s n %5d  beta %.3f  Platt a %+.3f b %.3f  mejora %+.3f mil  z %+.2f  mitades %+.3f/%+.3f  cal %+.4f -> %+.4f  %s" % (
            liga, n, beta, a, b, 1000 * m, z, 1000 * m1, 1000 * m2, cal0, cal1, ver.upper()))
        print("        log loss: modelo solo %.4f | combinado %.4f" % (o["logloss_modelo_solo"], o["logloss_combinado"]))
        for t in tramos:
            print("        favorito %.1f-%.1f  n %5d  combinado %.3f  recalibrado %.3f  real %.3f" % (t["tramo"][0], t["tramo"][1], t["n"], t["combinado"], t["recalibrado"], t["real"]))
    json.dump({"generado": dt.datetime.now().isoformat(timespec="seconds"), "resultados": out},
              open(os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_tanda9_recalibrar.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
