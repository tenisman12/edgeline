# -*- coding: utf-8 -*-
"""
nucleo/metamodelo.py - metamodelo apilado (como razona un tipster): una sola probabilidad por lado a partir de

    1. el mercado sharp (Pinnacle sin vig en el momento de decidir)       -> lm = logit(p_mercado)
    2. el desacuerdo del modelo con ese mercado                           -> dm = logit(p_modelo) - lm
    3. los angulos situacionales (firmados hacia el lado, encogidos)      -> a_1 ... a_k
    4. el publico y el movimiento (boletos, dinero - boletos, movimiento) -> u_1 ... u_m

    logit(q) = b0 + b1*lm + b2*dm + sum(c_i*a_i) + sum(d_j*u_j) [+ e*es_empate]

Se ajusta con regresion logistica con penalizacion L2 por grupo (el mercado y el modelo casi sin castigo; angulos y
publico con castigo fuerte, o sea encogidos hacia 0 hasta que los datos los sostengan). Si el publico no tiene historia,
su peso queda en ~0 sin romper nada.

Todo lo que se predice se ajusta SOLO con partidos anteriores (walk-forward por bloques). En deportes de 3 vias (futbol)
las tres probabilidades del partido se normalizan para que sumen 1.

No toca modelos ni picks: lo usan utilidades/metamodelo.py (evaluacion) y, si pasa, decidir.py.
"""
import math
from collections import defaultdict

EPS = 1e-6


def logit(p):
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def sig(x):
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    z = math.exp(x)
    return z / (1 + z)


def _resolver(A, b):
    n = len(b); M = [A[i][:] + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            continue
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def ajustar(X, Y, castigo, prior=None, iters=25):
    """Logistica con L2 por coeficiente hacia `prior` (IRLS). castigo[i] = lambda del coeficiente i (0 = libre)."""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        Xa = np.asarray(X, float); Ya = np.asarray(Y, float); L = np.diag(np.asarray(castigo, float))
        pr = np.asarray(prior if prior else [0.0] * len(castigo), float); b = pr.copy()
        for _ in range(iters):
            z = Xa @ b; p = 1 / (1 + np.exp(-np.clip(z, -30, 30))); w = np.maximum(p * (1 - p), 1e-9)
            g = Xa.T @ (Ya - p) - L @ (b - pr); H = (Xa * w[:, None]).T @ Xa + L
            d = np.linalg.solve(H, g); b = b + d
            if np.max(np.abs(d)) < 1e-7:
                break
        return [float(v) for v in b]
    k = len(castigo); b = list(prior) if prior else [0.0] * k
    pr = list(prior) if prior else [0.0] * k
    for _ in range(iters):
        H = [[0.0] * k for _ in range(k)]; g = [0.0] * k
        for x, y in zip(X, Y):
            z = sum(bi * xi for bi, xi in zip(b, x)); p = sig(z); w = max(p * (1 - p), 1e-9); r = y - p
            for i in range(k):
                if x[i] == 0: continue
                g[i] += r * x[i]; wi = w * x[i]
                for j in range(i, k):
                    if x[j]: H[i][j] += wi * x[j]
        for i in range(k):
            for j in range(i):
                H[i][j] = H[j][i]
            H[i][i] += castigo[i]; g[i] -= castigo[i] * (b[i] - pr[i])
        d = _resolver(H, g)
        b = [bi + di for bi, di in zip(b, d)]
        if max(abs(x) for x in d) < 1e-7:
            break
    return b


class Metamodelo:
    """Columnas: ['b0','lm','dm', angulos..., publico..., extras...]. castigos por grupo."""

    def __init__(self, angulos=(), publico=(), extras=(), l_ang=200.0, l_pub=400.0, l_base=1.0, usar_modelo=True):
        self.angulos = list(angulos); self.publico = list(publico); self.extras = list(extras)
        self.usar_modelo = usar_modelo
        self.cols = ["b0", "lm", "dm"] + self.angulos + self.publico + self.extras
        # usar_modelo=False: el coeficiente del modelo queda clavado en 0 (castigo enorme) -> mercado recalibrado
        self.castigo = [l_base, l_base, l_base if usar_modelo else 1e9] + [l_ang] * len(self.angulos) + \
            [l_pub] * len(self.publico) + [l_base] * len(self.extras)
        # prior: mercado con peso 1, sin intercepto, modelo 0 (lo tiene que ganar), angulos y publico 0
        self.prior = [0.0, 1.0, 0.0] + [0.0] * (len(self.angulos) + len(self.publico) + len(self.extras))
        self.b = list(self.prior)

    def fila(self, s):
        lm = logit(s["p_mkt"]); dm = (logit(s["p_mod"]) - lm) if s.get("p_mod") is not None else 0.0
        x = [1.0, lm, dm]
        x += [float(s.get("ang", {}).get(a) or 0.0) for a in self.angulos]
        x += [float(s.get("pub", {}).get(u) or 0.0) for u in self.publico]
        x += [float(s.get(e) or 0.0) for e in self.extras]
        return x

    def ajustar(self, lados):
        X = [self.fila(s) for s in lados]; Y = [s["y"] for s in lados]
        self.b = ajustar(X, Y, self.castigo, self.prior)
        return self

    def q(self, s):
        return sig(sum(bi * xi for bi, xi in zip(self.b, self.fila(s))))

    def coef(self):
        return dict(zip(self.cols, [round(v, 4) for v in self.b]))


def normalizar(lados, clave="q"):
    """En cada partido (s['juego']) las probabilidades de sus lados suman 1."""
    por = defaultdict(list)
    for s in lados:
        por[s["juego"]].append(s)
    for L in por.values():
        t = sum(s[clave] for s in L)
        if t > 0:
            for s in L:
                s[clave] = s[clave] / t


def walk_forward(lados, mm_factory, dias_bloque=30, min_entreno=2000, normalizar_juego=True):
    """Predice cada bloque de `dias_bloque` dias con un metamodelo ajustado solo con lo anterior. Escribe s['q']."""
    import datetime as dt
    lados = sorted(lados, key=lambda s: s["fecha"])
    if not lados:
        return [], []
    d0 = dt.date.fromisoformat(lados[0]["fecha"][:10]); fin = dt.date.fromisoformat(lados[-1]["fecha"][:10])
    pred = []; hist = []; i_tr = 0
    while d0 <= fin:
        d1 = d0 + dt.timedelta(days=dias_bloque)
        c0, c1 = d0.isoformat(), d1.isoformat()
        while i_tr < len(lados) and lados[i_tr]["fecha"][:10] < c0:
            i_tr += 1
        blk = [s for s in lados[i_tr:] if s["fecha"][:10] < c1]
        juegos_tr = len({s["juego"] for s in lados[:i_tr]})
        if blk and juegos_tr >= min_entreno:
            mm = mm_factory().ajustar(lados[:i_tr])
            for s in blk:
                s["q"] = mm.q(s)
            if normalizar_juego:
                normalizar(blk, "q")
            pred += blk; hist.append((c0, mm.coef()))
        d0 = d1
    return pred, hist
