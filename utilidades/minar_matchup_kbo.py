# -*- coding: utf-8 -*-
"""
utilidades/minar_matchup_kbo.py - mineria: interaccion log5 abridor x lineup rival (HR y K) en el total de KBO.
Hipotesis registrada en trabajo/minar/2026-10-06_matchup_kbo.md.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\minar_matchup_kbo.py
"""
import csv, json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, features as F, abridores as AB
from modelos import beisbol as B

K_AB, K_LIN = 150.0, 400.0


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def senales():
    """{(game_id, equipo_que_batea): (hr_int, k_int, bf_esperados)} as-of."""
    rows = list(csv.DictReader(open(os.path.join(io.BASE, "datos", "jugadores", "kbo_lanzadores.csv"), encoding="utf-8-sig")))
    rows.sort(key=lambda r: (r["game_date"], r["game_id"]))
    lg = {"bf": 0.0, "hr": 0.0, "k": 0.0}
    ab = {}                 # abridor -> [(temp, bf, hr, k, outs)]
    lin = {}                # (equipo, temp) -> [bf, hr, k]  (lo que bateo el equipo)
    por_dia = {}
    for r in rows:
        por_dia.setdefault(r["game_date"], []).append(r)
    out = {}
    for f in sorted(por_dia):
        dia = por_dia[f]; temp = int(f[:4])
        lhr = lg["hr"] / lg["bf"] if lg["bf"] > 2000 else 0.022
        lk = lg["k"] / lg["bf"] if lg["bf"] > 2000 else 0.19
        for r in dia:
            if str(r.get("abridor")) != "1":
                continue
            h = [x for x in ab.get(r["jugador"].strip(), []) if x[0] >= temp - 1]
            bf = sum(x[1] for x in h)
            phr = (sum(x[2] for x in h) + K_AB * lhr) / (bf + K_AB)
            pk = (sum(x[3] for x in h) + K_AB * lk) / (bf + K_AB)
            outs = sum(x[4] for x in h)
            bf_esp = ((outs / 3.0) / len(h) if h else 5.0) * 4.3
            l_ = lin.get((r["opp"], temp), [0.0, 0.0, 0.0])
            bhr = (l_[1] + K_LIN * lhr) / (l_[0] + K_LIN)
            bk = (l_[2] + K_LIN * lk) / (l_[0] + K_LIN)
            hr_int = (phr * bhr / lhr - (phr + bhr - lhr)) * bf_esp
            k_int = (pk * bk / lk - (pk + bk - lk)) * bf_esp
            out[(r["game_id"], r["opp"])] = (hr_int, k_int, bf_esp)
        for r in dia:
            bf, hr, k, o = (_f(r.get(c)) or 0.0 for c in ("bf", "hr", "k", "outs"))
            lg["bf"] += bf; lg["hr"] += hr; lg["k"] += k
            l_ = lin.setdefault((r["opp"], temp), [0.0, 0.0, 0.0]); l_[0] += bf; l_[1] += hr; l_[2] += k
            if str(r.get("abridor")) == "1":
                ab.setdefault(r["jugador"].strip(), []).append((temp, bf, hr, k, o))
    return out


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _over(mu, L):
    return 1 - sum(B._nb_pmf(k, mu) for k in range(int(math.floor(L)) + 1))


def ols(X, y, l2=1e-2):
    k = len(X[0]); A = [[0.0] * (k + 1) for _ in range(k)]
    for xi, yi in zip(X, y):
        for i in range(k):
            A[i][k] += xi[i] * yi
            for j in range(k): A[i][j] += xi[i] * xi[j]
    for i in range(k): A[i][i] += l2
    for i in range(k):
        p = A[i][i] or 1e-9
        for j in range(i, k + 1): A[i][j] /= p
        for r in range(k):
            if r != i:
                fc = A[r][i]
                for j in range(i, k + 1): A[r][j] -= fc * A[i][j]
    return [A[i][k] for i in range(k)]


def main():
    S = senales(); VAB = AB.historicos(io.BASE)
    feats, _ = F.construir("beisbol", "KBO", 5)
    G = sorted([r for r in feats if r["league"] == "kbo" and r.get("total") is not None], key=lambda r: r["game_date"])
    filas = []
    d0 = dt.date.fromisoformat(G[0]["game_date"][:10]); ultimo = dt.date.fromisoformat(G[-1]["game_date"][:10])
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=30)
        blk = [r for r in G if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in G if r["game_date"][:10] < d0.isoformat()]
        if blk and len(prev) >= 500:
            mod = B.entrenar_logistica(prev)
            if mod:
                tp = [r["total"] for r in prev]; base_t = sum(tp) / len(tp); L = math.floor(base_t) + 0.5
                fr = sum(1 for t in tp if t > L) / len(tp)
                for r in blk:
                    p = B.prob(mod, r); xh, xa = B.carreras_esperadas(r)
                    if xh is None: continue
                    if B.COHERENTE: xh, xa = B.ajustar_carreras(xh, xa, p)
                    vh, va = VAB.get((r["gamePk"], r["home"])), VAB.get((r["gamePk"], r["away"]))
                    sh_ = S.get((r["gamePk"], r["home"])); sa_ = S.get((r["gamePk"], r["away"]))   # equipo que batea
                    if not (vh and va and sh_ and sa_): continue
                    sh, sa = AB.carreras_salvadas(r.get("df_home"), vh), AB.carreras_salvadas(r.get("df_away"), va)
                    mu = max(xh - AB.ESCALA_TOTAL * sa, 0.5) + max(xa - AB.ESCALA_TOTAL * sh, 0.5)
                    filas.append({"f": r["game_date"][:10], "mu": mu, "tot": r["total"], "L": L, "fr": fr,
                                  "hr": sh_[0] + sa_[0], "k": sh_[1] + sa_[1]})
        d0 = d1
    c = int(len(filas) * 0.7); E, T = filas[:c], filas[c:]
    n = len(T); h = n // 2
    print("KBO: %d juegos (ajuste %d hasta %s, prueba %d desde %s)" % (len(filas), len(E), E[-1]["f"], n, T[0]["f"]))
    res = {"hipotesis": "trabajo/minar/2026-10-06_matchup_kbo.md", "k_variantes": 3, "n_prueba": n, "variantes": {}}
    def st(d, m=1.0):
        mu = sum(d) / len(d); sd = math.sqrt(sum((v - mu) ** 2 for v in d) / (len(d) - 1)) or 1e-9; hh = len(d) // 2
        return round(m * mu, 4), round(mu / (sd / math.sqrt(len(d))), 2), [round(m * sum(d[:hh]) / hh, 4), round(m * sum(d[hh:]) / (len(d) - hh), 4)]
    for nom, cols in (("HR", ["hr"]), ("K", ["k"]), ("HR+K", ["hr", "k"])):
        b = ols([[x[cc] for cc in cols] for x in E], [x["tot"] - x["mu"] for x in E])
        q = [max(x["mu"] + sum(bi * x[cc] for bi, cc in zip(b, cols)), 1.0) for x in T]
        mae = st([abs(x["tot"] - x["mu"]) - abs(x["tot"] - qq) for qq, x in zip(q, T)])
        mse = st([(x["tot"] - x["mu"]) ** 2 - (x["tot"] - qq) ** 2 for qq, x in zip(q, T)])
        ou = st([_ll(_over(x["mu"], x["L"]), 1 if x["tot"] > x["L"] else 0) - _ll(_over(qq, x["L"]), 1 if x["tot"] > x["L"] else 0) for qq, x in zip(q, T)], 1000)
        ok = n >= 300 and ((mae[1] >= 2 and min(mae[2]) > 0) or (mse[1] >= 2 and min(mse[2]) > 0)) and ou[1] >= 2 and min(ou[2]) > 0
        res["variantes"][nom] = {"coef": [round(v, 3) for v in b], "mae": mae, "mse": mse, "ou_milesimas": ou, "veredicto": "pasa" if ok else "no pasa"}
        print("  %-5s coef %s | MAE %+.4f (z %.2f, %s) | MSE %+.3f (z %.2f) | O/U %+.2f (z %.2f, %s) -> %s" % (
            nom, res["variantes"][nom]["coef"], mae[0], mae[1], mae[2], mse[0], mse[1], ou[0], ou[1], ou[2], res["variantes"][nom]["veredicto"]))
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trabajo", "minar", "matchup_kbo.json")
    json.dump(res, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
