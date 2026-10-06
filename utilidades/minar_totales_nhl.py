# -*- coding: utf-8 -*-
"""
utilidades/minar_totales_nhl.py - mineria: la DISTRIBUCION del total de goles de NHL (no el promedio) mejora el O/U?
Hipotesis registrada en trabajo/minar/2026-10-06_totales_nhl.md (escrita antes de correr).

Walk-forward (bloques de 30 dias, el modelo se entrena solo con lo anterior, con GSAx del portero titular como en
produccion). Por partido y linea (5.5 y 6.5): mu esperado y si fue over. Variantes contra Poisson(mu) (modelo actual):
  B binomial negativa (dispersion ajustada en exploracion), C recalibracion logistica, D logistica sobre (mu - L).
70 % mas antiguo para ajustar, 30 % mas reciente para probar una sola vez. Escribe trabajo/minar/totales_nhl.json.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\minar_totales_nhl.py
"""
import json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io
from modelos import hockey as H

LINEAS = (5.5, 6.5)


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def _lo(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def pois_over(mu, L):
    return 1 - sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(int(math.floor(L)) + 1))


def nb_over(mu, L, r):
    p = r / (r + mu); s = 0.0
    for k in range(int(math.floor(L)) + 1):
        s += math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))
    return 1 - s


def logistica(X, y, iters=40, l2=1e-3):
    k = len(X[0]); b = [0.0] * k
    for _ in range(iters):
        g = [l2 * v for v in b]; Hm = [[l2 if i == j else 0.0 for j in range(k)] for i in range(k)]
        for xi, yi in zip(X, y):
            p = _sig(sum(bj * xj for bj, xj in zip(b, xi))); w = p * (1 - p)
            for i in range(k):
                g[i] += (p - yi) * xi[i]
                for j in range(k): Hm[i][j] += w * xi[i] * xi[j]
        A = [row[:] + [gi] for row, gi in zip(Hm, g)]
        for i in range(k):
            pv = A[i][i] or 1e-9
            for j in range(i, k + 1): A[i][j] /= pv
            for r in range(k):
                if r != i:
                    fc = A[r][i]
                    for j in range(i, k + 1): A[r][j] -= fc * A[i][j]
        b = [bi - A[i][k] for i, bi in enumerate(b)]
    return b


def filas_walk_forward():
    juegos = H._juegos(None)
    G = [(f, gp, h, a) for f, gp, h, a in juegos if _f(h.get("goals")) is not None and _f(h.get("goals_opp")) is not None]
    d0 = dt.date.fromisoformat(G[0][0]); ultimo = dt.date.fromisoformat(G[-1][0])
    out = []; orig = io.cargar_juegos
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=30)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        if blk and len(prev) >= 600:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = H.entrenar(None)
            finally:
                io.cargar_juegos = orig
            tot_prev = [_f(g[2]["goals"]) + _f(g[2]["goals_opp"]) for g in prev]
            base = {L: sum(1 for t in tot_prev if t > L) / len(tot_prev) for L in LINEAS}
            for f, gp, h, a in blk:
                gh_, _ = H.rating_portero(h.get("starter_goalie"), f) if h.get("starter_goalie") else (None, 0)
                ga_, _ = H.rating_portero(a.get("starter_goalie"), f) if a.get("starter_goalie") else (None, 0)
                xh, xa = H._xg(est, h.get("team"), a.get("team"), gsax_home=gh_, gsax_away=ga_)
                if xh is None:
                    continue
                mu = xh + xa; lg2 = 2 * est["lg"]; mu = lg2 + H.TOT_K * (mu - lg2)
                tot = _f(h["goals"]) + _f(h["goals_opp"])
                for L in LINEAS:
                    out.append({"f": f, "mu": mu, "L": L, "y": 1 if tot > L else 0, "base": base[L], "tot": tot})
        d0 = d1
    out.sort(key=lambda r: r["f"])
    return out


def main():
    F = filas_walk_forward()
    corte = int(len(F) * 0.7)
    E, T = F[:corte], F[corte:]
    print("Partido-linea: %d (exploracion %d hasta %s, prueba %d desde %s)" % (len(F), len(E), E[-1]["f"], len(T), T[0]["f"]))
    # B: dispersion de la NB que minimiza log-loss en exploracion
    mejor_r = min((5, 8, 12, 20, 35, 60, 100, 200), key=lambda r: sum(_ll(nb_over(x["mu"], x["L"], r), x["y"]) for x in E))
    # C: recalibracion logistica de Poisson
    XC = lambda x: [1.0, _lo(pois_over(x["mu"], x["L"])), 1.0 if x["L"] == 6.5 else 0.0]
    bC = logistica([XC(x) for x in E], [x["y"] for x in E])
    # D: logistica directa
    XD = lambda x: [1.0, x["mu"] - x["L"], 1.0 if x["L"] == 6.5 else 0.0]
    bD = logistica([XD(x) for x in E], [x["y"] for x in E])
    var = {"A_poisson": lambda x: pois_over(x["mu"], x["L"]),
           "B_binomial_negativa": lambda x: nb_over(x["mu"], x["L"], mejor_r),
           "C_recalibrada": lambda x: _sig(sum(b * v for b, v in zip(bC, XC(x)))),
           "D_logistica_mu": lambda x: _sig(sum(b * v for b, v in zip(bD, XD(x))))}
    print("Ajustes en exploracion: NB r=%s | C %s | D %s" % (mejor_r, [round(b, 3) for b in bC], [round(b, 3) for b in bD]))
    res = {"hipotesis": "trabajo/minar/2026-10-06_totales_nhl.md", "n_prueba": len(T), "k_variantes": 3,
           "ajustes": {"nb_r": mejor_r, "C": bC, "D": bD}, "variantes": {}}
    n = len(T); h = n // 2
    for nom, fn in var.items():
        ps = [fn(x) for x in T]
        ll_m = [_ll(p, x["y"]) for p, x in zip(ps, T)]
        ll_A = [_ll(pois_over(x["mu"], x["L"]), x["y"]) for x in T]
        ll_b = [_ll(x["base"], x["y"]) for x in T]
        def cmp(ref):
            d = [r - m for r, m in zip(ref, ll_m)]; mu = sum(d) / n
            sd = math.sqrt(sum((v - mu) ** 2 for v in d) / (n - 1)) or 1e-9
            return {"mejora_milesimas": round(1000 * mu, 3), "z": round(mu / (sd / math.sqrt(n)), 2),
                    "mitades": [round(1000 * sum(d[:h]) / h, 3), round(1000 * sum(d[h:]) / (n - h), 3)]}
        vb, va = cmp(ll_b), cmp(ll_A)
        cal = {"p_media": round(sum(ps) / n, 4), "tasa_real": round(sum(x["y"] for x in T) / n, 4)}
        por_linea = {}
        for L in LINEAS:
            idx = [i for i, x in enumerate(T) if x["L"] == L]
            por_linea[str(L)] = {"p_media": round(sum(ps[i] for i in idx) / len(idx), 4), "tasa_real": round(sum(T[i]["y"] for i in idx) / len(idx), 4),
                                 "ll": round(sum(ll_m[i] for i in idx) / len(idx), 4), "ll_base": round(sum(ll_b[i] for i in idx) / len(idx), 4)}
        ok = n >= 300 and vb["z"] >= 2.0 and min(vb["mitades"]) > 0 and abs(cal["p_media"] - cal["tasa_real"]) <= 0.04
        res["variantes"][nom] = {"contra_base": vb, "contra_modelo_actual": va, "calibracion": cal, "por_linea": por_linea,
                                 "veredicto": "pasa" if ok else "no pasa"}
        print("  %-20s vs base %+.2f (z %.2f, mitades %s) | vs Poisson %+.2f (z %.2f) | p media %.3f real %.3f -> %s" % (
            nom, vb["mejora_milesimas"], vb["z"], vb["mitades"], va["mejora_milesimas"], va["z"], cal["p_media"], cal["tasa_real"],
            res["variantes"][nom]["veredicto"]))
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trabajo", "minar"), exist_ok=True)
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trabajo", "minar", "totales_nhl.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
