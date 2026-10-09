# -*- coding: utf-8 -*-
"""
utilidades/minar_b2b_factor_nhl.py - prueba reescalar el factor de segunda noche (back-to-back) del modelo de hockey.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_b2b_factor_nhl.md
Eleva los factores as-of de modelos/hockey.py a la potencia k; elige k en el 70 % mas antiguo y prueba una vez en el 30 %.
No modifica modelos/: el cambio se aplica a mano solo si pasa.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_b2b_factor_nhl.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402
from modelos import hockey as H  # noqa: E402

REJILLA = [1.0, 1.5, 2.0, 2.5, 3.0]


def cal_con_k(k):
    orig = H._aplicar_b2b
    flags = []

    def w(xh, xa, bh, ba, fac):
        flags.append(bool(bh) or bool(ba))
        f_of, f_df = fac
        return orig(xh, xa, bh, ba, (f_of ** k, f_df ** k))
    H._aplicar_b2b = w
    try:
        est = H.entrenar(None)
    finally:
        H._aplicar_b2b = orig
    return [p for p, y in est["cal"]], [y for p, y in est["cal"]], flags, est["b2b"]


def main():
    res = {}
    for k in REJILLA:
        P, Y, F, b = cal_con_k(k); res[k] = P
        print("  k %.1f listo (factores base of %.4f df %.4f, n b2b %d)" % (k, b["factor_of"], b["factor_df"], b["n"]))
    n = len(Y); i70 = int(n * 0.7)
    print("\nFACTOR DE SEGUNDA NOCHE NHL | %d predicciones as-of | explorar %d | prueba %d" % (n, i70, n - i70))

    def recal(P):
        return M._logistica([[1.0, M._lg(p)] for p in P[:i70]], Y[:i70])

    def ll_seg(P, w, a, b):
        return [M._ll(M._sig(w[0] + w[1] * M._lg(P[i])), Y[i]) for i in range(a, b)]
    exp = {}
    for k in REJILLA:
        w = recal(res[k]); exp[k] = (w, sum(ll_seg(res[k], w, 0, i70)) / i70)
        print("  k %.1f  log-loss en el 70 %%: %.6f" % (k, exp[k][1]))
    kb = min(REJILLA, key=lambda k: exp[k][1])
    print("  k elegido en el 70 %%: %.1f" % kb)
    l1 = ll_seg(res[1.0], exp[1.0][0], i70, n); lk = ll_seg(res[kb], exp[kb][0], i70, n)
    d = [a - b for a, b in zip(l1, lk)]; m = sum(d) / len(d)
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / (len(d) - 1)) or 1e-12; z = m / (sd / math.sqrt(len(d)))
    h = len(d) // 2; m1 = sum(d[:h]) / h; m2 = sum(d[h:]) / (len(d) - h)
    act = [i for i in range(i70, n) if F[i]]
    wk = exp[kb][0]
    cal = sum(M._sig(wk[0] + wk[1] * M._lg(res[kb][i])) for i in act) / len(act) - sum(Y[i] for i in act) / len(act)
    ver = "pasa" if (kb != 1.0 and z >= 2 and m1 > 0 and m2 > 0 and abs(cal) <= 0.04) else "no pasa"
    print("\nPRUEBA: k %.1f contra k 1.0 | mejora %+.3f milesimas  z %+.2f  mitades %+.3f / %+.3f | activos %d calibracion %+.4f | %s" % (
        kb, 1000 * m, z, 1000 * m1, 1000 * m2, len(act), cal, ver.upper()))
    out = {"k_elegido": kb, "logloss_explorar": {str(k): round(v[1], 6) for k, v in exp.items()},
           "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2), "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)],
           "activos": len(act), "calibracion_activos": round(cal, 4), "veredicto": ver}
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_b2b_factor_nhl_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
