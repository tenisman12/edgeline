# -*- coding: utf-8 -*-
"""
utilidades/minar_fatiga_nhl.py - indice de fatiga en NHL con encogimiento bayesiano, contra el modelo.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_fatiga_nhl.md
Reusa la prediccion as-of y los angulos de utilidades/minar_situacionales.py (H1, H2, H4, H6, H7).
Ajuste conjunto en el 70 % mas antiguo con prior normal(0, tau) en cada componente (ridge 1/tau^2);
evaluacion una sola vez en el 30 % mas reciente con log-loss pareado. No toca modelos/ ni nucleo/.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_fatiga_nhl.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402

COMP = ["H1", "H2", "H4", "H6", "H7"]
TAU = 0.10


def _map(X, Y, l2, iters=40):
    d = len(X[0]); w = [0.0] * d; w[1] = 1.0
    for _ in range(iters):
        g = [l2[i] * w[i] for i in range(d)]; H = [[(l2[i] if i == j else 0.0) for j in range(d)] for i in range(d)]
        for x, y in zip(X, Y):
            p = M._sig(sum(a * b for a, b in zip(w, x))); r = p - y; s = p * (1 - p)
            for i in range(d):
                g[i] += r * x[i]
                for j in range(d): H[i][j] += s * x[i] * x[j]
        paso = M._resolver(H, g)
        if paso is None: break
        w = [a - b for a, b in zip(w, paso)]
        if max(abs(s) for s in paso) < 1e-9: break
    return w


def main():
    CAP = {}
    M.evaluar = lambda filas, codigo, *a, **k: CAP.setdefault(codigo, filas)
    M.correr_hockey()
    F = [r for r in CAP["H1"] if all(r.get(c) is not None for c in COMP)]
    F.sort(key=lambda r: (r["fecha"], r.get("gp", "")))
    i70 = int(len(F) * 0.7); tr, te = F[:i70], F[i70:]
    vec = lambda r: [1.0, M._lg(r["p"])] + [float(r[c]) for c in COMP]
    Ytr = [r["y"] for r in tr]
    w0 = _map([[1.0, M._lg(r["p"])] for r in tr], Ytr, [1e-6, 1e-6])
    w1 = _map([vec(r) for r in tr], Ytr, [1e-6, 1e-6] + [1.0 / TAU ** 2] * len(COMP))
    print("\nINDICE DE FATIGA NHL (tau %.2f) | explorar %d, prueba %d desde %s" % (TAU, len(tr), len(te), te[0]["fecha"]))
    for c, b in zip(COMP, w1[2:]):
        print("  %-3s beta %+.3f  (%+.1f pp por unidad en p=0.5)" % (c, b, 25 * b))
    d = []; act = []
    for r in te:
        L = M._lg(r["p"])
        q0 = M._sig(w0[0] + w0[1] * L)
        idx = sum(b * float(r[c]) for c, b in zip(COMP, w1[2:]))
        q1 = M._sig(w1[0] + w1[1] * L + idx)
        d.append(M._ll(q0, r["y"]) - M._ll(q1, r["y"]))
        if abs(idx) > 1e-9: act.append((q0, q1, r["y"], idx))
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / (n - 1)); z = m / (sd / math.sqrt(n))
    h = n // 2; m1 = sum(d[:h]) / h; m2 = sum(d[h:]) / (n - h)
    na = len(act)
    cal = sum(a[1] for a in act) / na - sum(a[2] for a in act) / na
    # el indice favorece al descansado: residuo del modelo en la direccion del indice
    sres = sum((a[2] - a[0]) * (1 if a[3] > 0 else -1) for a in act) / na
    grandes = [a for a in act if abs(a[3]) >= 0.08]
    sres_g = (sum((a[2] - a[0]) * (1 if a[3] > 0 else -1) for a in grandes) / len(grandes)) if grandes else None
    ver = "muestra insuficiente" if na < 300 else ("pasa" if (z >= 2.0 and m1 > 0 and m2 > 0 and abs(cal) <= 0.04 and sres > 0) else "no pasa")
    out = {"n_prueba": n, "n_activo": na, "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2),
           "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)], "calibracion_activos": round(cal, 4),
           "residuo_firmado_pp": round(100 * sres, 2), "n_indice_grande": len(grandes),
           "residuo_firmado_grande_pp": None if sres_g is None else round(100 * sres_g, 2),
           "betas": {c: round(b, 4) for c, b in zip(COMP, w1[2:])}, "tau": TAU, "veredicto": ver}
    print("  prueba: mejora %+.3f milesimas  z %+.2f  mitades %+.3f / %+.3f  activos %d  calibracion %+.3f" % (
        1000 * m, z, 1000 * m1, 1000 * m2, na, cal))
    print("  lo que el modelo falla en la direccion del indice: %+.2f pp (todos) | %s pp con |indice| >= 0.08 (n %d)" % (
        100 * sres, "%+.2f" % (100 * sres_g) if sres_g is not None else "s/d", len(grandes)))
    print("  VEREDICTO:", ver.upper())
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_fatiga_nhl_resultados.json")
    os.makedirs(M.SALIDA_MD, exist_ok=True)
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  resultados en", ruta)


if __name__ == "__main__":
    main()
