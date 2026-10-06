# -*- coding: utf-8 -*-
"""
utilidades/medir_viajes.py - mide si el viaje (km y husos horarios desde el partido anterior) agrega al modelo en NHL y NBA.

Walk-forward igual que la validacion (bloques de 30 dias, modelo entrenado solo con lo anterior, ultimos 24 meses).
Por partido: diferencia visita - local de km recorridos (miles), de husos cruzados (valor absoluto) y back-to-back.
Se ajusta una logistica con el logit del modelo como offset en una mitad y se evalua en la otra (y al reves):
mejora de log-loss contra el modelo solo, z y por mitades. Protocolo: n >= 300, z >= 2.0, mejora en las dos mitades.
Escribe modelos/viajes.json con coeficientes y veredicto.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\medir_viajes.py
"""
import json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, viajes as V
from modelos import hockey, nba

CFG = {"nhl": (hockey, None, ("goals", "goals_opp")), "nba": (nba, "NBA", ("points", "points_opp"))}


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def _lo(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def ajustar(X, off, y, iters=25, l2=1.0):
    """logistica con offset por Newton (sin intercepto: el modelo ya esta calibrado)."""
    k = len(X[0]); b = [0.0] * k
    for _ in range(iters):
        g = [l2 * bi for bi in b]; Hm = [[l2 if i == j else 0.0 for j in range(k)] for i in range(k)]
        for xi, oi, yi in zip(X, off, y):
            p = _sig(oi + sum(bj * xj for bj, xj in zip(b, xi))); w = p * (1 - p)
            for i in range(k):
                g[i] += (p - yi) * xi[i]
                for j in range(k):
                    Hm[i][j] += w * xi[i] * xi[j]
        # resolver Hm * d = g (Gauss)
        A = [row[:] + [gi] for row, gi in zip(Hm, g)]
        for i in range(k):
            piv = A[i][i] or 1e-9
            for j in range(i, k + 1): A[i][j] /= piv
            for r in range(k):
                if r != i:
                    fct = A[r][i]
                    for j in range(i, k + 1): A[r][j] -= fct * A[i][j]
        b = [bi - A[i][k] for i, bi in enumerate(b)]
    return b


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def medir(liga):
    mod, lg_mod, (cg, cgo) = CFG[liga]
    juegos = mod._juegos(lg_mod)
    G = [(f, gp, h, a) for f, gp, h, a in juegos if _f(h.get(cg)) is not None and _f(h.get(cgo)) is not None]
    hist = V.Historial(liga); feat = {}
    for f, gp, h, a in G:
        th, ta = h.get("team"), a.get("team")
        vh, va = hist.antes(th, f, th), hist.antes(ta, f, th)
        if vh and va:
            feat[(f, gp)] = [(va["km"] - vh["km"]) / 1000.0, abs(va["husos"]) - abs(vh["husos"]),
                             (1.0 if va["dias"] == 1 else 0.0) - (1.0 if vh["dias"] == 1 else 0.0)]
        hist.jugar(th, f, th); hist.jugar(ta, f, th)
    ultimo = dt.date.fromisoformat(G[-1][0]); d0 = ultimo - dt.timedelta(days=int(24 * 30.4))
    filas = []; orig = io.cargar_juegos
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=30)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        if blk and len(prev) >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = mod.entrenar(lg_mod)
            finally:
                io.cargar_juegos = orig
            for f, gp, h, a in blk:
                x = feat.get((f, gp))
                if not x:
                    continue
                r = mod.predecir(est, h.get("team"), a.get("team"), linea_total=6.5) if liga == "nhl" else \
                    mod.predecir(est, h.get("team"), a.get("team"), linea_total=None, linea_spread=0.0)
                if not r:
                    continue
                filas.append((x, _lo(r["p_home"]), 1 if _f(h[cg]) > _f(h[cgo]) else 0))
        d0 = d1
    n = len(filas); h_ = n // 2
    A, B = filas[:h_], filas[h_:]
    out = {"n": n}
    for nombre, cols in (("km", [0]), ("husos", [1]), ("km+husos", [0, 1]), ("km+husos+b2b", [0, 1, 2]), ("b2b", [2])):
        def sub(F): return [[r[0][c] for c in cols] for r in F]
        bA = ajustar(sub(A), [r[1] for r in A], [r[2] for r in A])
        bB = ajustar(sub(B), [r[1] for r in B], [r[2] for r in B])
        d = []
        for F, b in ((B, bA), (A, bB)):            # cada mitad se evalua con lo ajustado en la otra
            for x, o, y in F:
                xs = [x[c] for c in cols]
                d.append(_ll(_sig(o), y) - _ll(_sig(o + sum(bi * xi for bi, xi in zip(b, xs))), y))
        mu = sum(d) / len(d); sd = math.sqrt(sum((v - mu) ** 2 for v in d) / (len(d) - 1)) or 1e-9
        mA = sum(d[len(B):]) / max(1, len(A)); mB = sum(d[:len(B)]) / max(1, len(B))
        z = mu / (sd / math.sqrt(len(d)))
        ok = n >= 300 and z >= 2.0 and mA > 0 and mB > 0
        bt = ajustar(sub(filas), [r[1] for r in filas], [r[2] for r in filas])
        out[nombre] = {"mejora_milesimas": round(1000 * mu, 3), "z": round(z, 2), "mitades": [round(1000 * mA, 3), round(1000 * mB, 3)],
                       "coef_todo": [round(b, 4) for b in bt], "veredicto": "APLICAR" if ok else "sin mejora demostrada"}
        print("  %-4s %-13s n=%d  mejora %+.3f milesimas  z %.2f  mitades %s  coef %s -> %s" % (
            liga.upper(), nombre, n, 1000 * mu, z, out[nombre]["mitades"], out[nombre]["coef_todo"], out[nombre]["veredicto"]))
    return out


def main():
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"),
           "variables": "diferencias visita - local: km/1000 desde el partido anterior, |husos| cruzados, back-to-back"}
    for liga in ("nhl", "nba"):
        try:
            res[liga] = medir(liga)
        except Exception as e:
            print("  %s: %s" % (liga, e)); res[liga] = {"error": str(e)}
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "viajes.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
