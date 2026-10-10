# -*- coding: utf-8 -*-
"""
utilidades/minar_tanda8_produccion.py - tanda 8, parte A (trabajo/minar/2026-10-10_tanda8.md): los candidatos de la
tanda 7 en basquet sobre produccion.
  A1 TL7 posesiones sobre la capa de totales (nucleo/capa_totales: OLS 1, T_modelo, M, E + nivel; O/U con residuos)
  A2 L1 Pitagoras sobre la p_home del modelo reentrenado por bloques
Walk-forward por bloques de 30 dias (modelo reentrenado solo con lo anterior, como validar_mercados). No toca modelos/.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_tanda8_produccion.py --cache trabajo/minar/tanda7_cache.pkl
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, math, os, pickle, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
from nucleo import io  # noqa: E402
from nucleo import capa_totales as CT  # noqa: E402
import minar_angulos_tanda7 as T7  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402

BLOQUE = 30
MIN_PREV = 300


def _sig(x): return 1 / (1 + math.exp(-x))
def _lg(p): p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))
def _ll(p, y): p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))
def medio(x): return math.floor(x) + 0.5


def _ols(X, Y):
    k = len(X[0]); A = [[0.0] * k for _ in range(k)]; b = [0.0] * k
    for v, y in zip(X, Y):
        for i in range(k):
            b[i] += v[i] * y
            for j in range(k): A[i][j] += v[i] * v[j]
    for i in range(k): A[i][i] += 1e-6
    import minar_situacionales as M
    return M._resolver(A, b)


def resumen(d, nombre, extra=None):
    n = len(d)
    if n < 30:
        return {"prueba": nombre, "n": n, "veredicto": "muestra insuficiente"}
    m = sum(d) / n; sd = math.sqrt(sum((v - m) ** 2 for v in d) / (n - 1)) or 1e-12
    h = n // 2
    out = {"prueba": nombre, "n": n, "mejora_media": round(m, 5), "z": round(m / (sd / math.sqrt(n)), 2),
           "mitades": [round(sum(d[:h]) / h, 5), round(sum(d[h:]) / (n - h), 5)]}
    if extra: out.update(extra)
    return out


def predicciones(dep):
    from modelos import nba as N
    todos = N._juegos(dep)
    G = []
    for f, gp, h, a in todos:
        gh, ga = T7._n(h.get("points")), T7._n(h.get("points_opp"))
        if gh is not None and ga is not None:
            G.append((str(f)[:10], str(gp), h.get("team"), a.get("team"), gh, ga))
    G.sort()
    orig = io.cargar_juegos
    d0 = dt.date.fromisoformat(G[0][0]); fin = dt.date.fromisoformat(G[-1][0])
    P = []; b = 0
    while d0 <= fin:
        d1 = d0 + dt.timedelta(days=BLOQUE)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        if blk and len(prev) >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = N.entrenar(dep)
            finally:
                io.cargar_juegos = orig
            L = medio(sum(g[4] + g[5] for g in prev) / len(prev))
            for f, gp, th, ta, gh, ga in blk:
                r = N.predecir(est, th, ta, linea_total=L, linea_spread=0.0)
                if not r: continue
                P.append(dict(f=f, gp=gp, h=th, a=ta, gh=gh, ga=ga, p=r["p_home"], T=r["total_esperado"], L=L, b=b))
            b += 1
            print("  %s bloque %s: %d juegos" % (dep, corte, len(blk)), flush=True)
        d0 = d1
    return G, P


def correr(dep, ULT, S, TS):
    G, P = predicciones(dep)
    filas, C = ULT[dep]
    gap = T7.T5.PARAM[dep]["gap"]
    rit = CT.Ritmo([(g[0], g[2], g[3], g[4] + g[5]) for g in G])
    for r in P:
        st = rit.estado(r["f"], r["h"], r["a"])
        r["M"], r["E"] = st if st else (None, None)
        Ph, Pa = T7.T5.previos(C, r["h"], r["gp"], gap), T7.T5.previos(C, r["a"], r["gp"], gap)
        r["TL7"] = r["L1"] = None
        if Ph is None or Pa is None: continue
        vh = T7.valores(dep, r["h"], Ph, S[dep], TS, r["f"], dep); va = T7.valores(dep, r["a"], Pa, S[dep], TS, r["f"], dep)
        if "TL7" in vh and "TL7" in va: r["TL7"] = vh["TL7"] + va["TL7"]
        if "L1" in vh and "L1" in va: r["L1"] = vh["L1"] - va["L1"]
    print("%s: %d predicciones; con TL7 %d, con L1 %d" % (dep, len(P), sum(1 for r in P if r["TL7"] is not None),
                                                        sum(1 for r in P if r["L1"] is not None)))
    nb = max(r["b"] for r in P) + 1
    # ---- A1: capa contra capa + TL7 (mismas filas: las que tienen x y M)
    Q = [r for r in P if r["TL7"] is not None and r["M"] is not None]
    dT, dB, sesgo, cal0, cal1, coefs = [], [], [], [], [], []
    for b in range(nb):
        prev = [r for r in Q if r["b"] < b]; cur = [r for r in Q if r["b"] == b]
        if len(prev) < MIN_PREV or not cur: continue
        Y = [r["gh"] + r["ga"] for r in prev]
        X0 = [(1.0, r["T"], r["M"], r["E"]) for r in prev]; X1 = [x + (r["TL7"],) for x, r in zip(X0, prev)]
        q0, q1 = _ols(X0, Y), _ols(X1, Y)
        if q0 is None or q1 is None: continue
        coefs.append(q1[-1])
        e0 = [y - sum(c * v for c, v in zip(q0, x)) for x, y in zip(X0, Y)]
        e1 = [y - sum(c * v for c, v in zip(q1, x)) for x, y in zip(X1, Y)]
        n0, n1 = sum(e0[-300:]) / 300, sum(e1[-300:]) / 300
        lim = (dt.date.fromisoformat(prev[-1]["f"]) - dt.timedelta(days=365)).isoformat()
        r0 = [e - n0 for e, r in zip(e0, prev) if r["f"] >= lim]; r1 = [e - n1 for e, r in zip(e1, prev) if r["f"] >= lim]
        if len(r0) < 300: r0 = [e - n0 for e in e0[-300:]]; r1 = [e - n1 for e in e1[-300:]]
        for r in cur:
            y = r["gh"] + r["ga"]
            t0 = sum(c * v for c, v in zip(q0, (1.0, r["T"], r["M"], r["E"]))) + n0
            t1 = sum(c * v for c, v in zip(q1, (1.0, r["T"], r["M"], r["E"], r["TL7"]))) + n1
            dT.append((y - t0) ** 2 - (y - t1) ** 2); sesgo.append(y - t1)
            o = 1 if y > r["L"] else 0
            p0 = sum(1 for e in r0 if t0 + e > r["L"]) / len(r0); p1 = sum(1 for e in r1 if t1 + e > r["L"]) / len(r1)
            dB.append((p0 - o) ** 2 - (p1 - o) ** 2); cal0.append((p0, o)); cal1.append((p1, o))
    sdT = math.sqrt(sum((v - sum(sesgo) / len(sesgo)) ** 2 for v in sesgo) / max(len(sesgo) - 1, 1)) if sesgo else 1
    a1t = resumen(dT, "A1 total esperado: capa + TL7 contra capa", {
        "sesgo_desv": round(sum(sesgo) / max(len(sesgo), 1) / (sdT or 1), 3), "coef_tl7_ultimo": round(coefs[-1], 2) if coefs else None})
    a1o = resumen(dB, "A1 over/under: capa + TL7 contra capa", {
        "calibracion_capa": round(sum(p for p, o in cal0) / max(len(cal0), 1) - sum(o for p, o in cal0) / max(len(cal0), 1), 4),
        "calibracion_con_tl7": round(sum(p for p, o in cal1) / max(len(cal1), 1) - sum(o for p, o in cal1) / max(len(cal1), 1), 4)})
    # ---- A2: L1 sobre p_home
    R = [r for r in P if r["L1"] is not None]
    dL, betas, pp, yy = [], [], [], []
    for b in range(nb):
        prev = [dict(p=r["p"], x=r["L1"], y=1 if r["gh"] > r["ga"] else 0) for r in R if r["b"] < b]
        cur = [r for r in R if r["b"] == b]
        if len(prev) < MIN_PREV or not cur: continue
        beta, _ = T4.offset_beta(prev)
        if beta is None: continue
        betas.append(beta)
        for r in cur:
            y = 1 if r["gh"] > r["ga"] else 0; p1 = _sig(_lg(r["p"]) + beta * r["L1"])
            dL.append(_ll(r["p"], y) - _ll(p1, y)); pp.append(p1); yy.append(y)
    a2 = resumen(dL, "A2 ganador: p_home + L1 contra p_home (log loss)", {
        "beta_ultimo": round(betas[-1], 3) if betas else None,
        "calibracion": round(sum(pp) / max(len(pp), 1) - sum(yy) / max(len(yy), 1), 4) if pp else None})
    for x in (a1t, a1o, a2):
        x["liga"] = dep
        print("  ", x)
    return [a1t, a1o, a2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl"))
    ap.add_argument("--deportes", default="NCAAMB,NBA")
    a = ap.parse_args()
    ULT = pickle.load(open(a.cache, "rb"))
    S = T7.estadisticas(); TS = T7.tasas(S)
    out = []
    for dep in a.deportes.split(","):
        out += correr(dep, ULT, S, TS)
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_tanda8_produccion.json")
    json.dump({"generado": dt.datetime.now().isoformat(timespec="seconds"), "hipotesis": "trabajo/minar/2026-10-10_tanda8.md",
               "resultados": out}, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
