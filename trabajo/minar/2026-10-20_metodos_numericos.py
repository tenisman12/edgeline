# -*- coding: utf-8 -*-
"""
trabajo/minar/2026-10-20_metodos_numericos.py  (minado 20-oct-2026; NO toca produccion)

Banco de pruebas de seis metodos numericos/vectoriales para beisbol, medidos walk-forward as-of
contra el modelo actual (MEDIA3 = ELO + logistica + carreras) con el criterio de la casa:
n >= 300, mejora a la base, z >= 2.0 (error pareado por juego), mejora en las dos mitades, |p media - tasa| <= 0.04.

  M1 vectores   : cada equipo es un vector (ataque, defensa) en un modelo log-lineal de carreras, actualizado juego a juego
  M2 kalman     : fuerza por equipo como estado oculto con incertidumbre; prior = temporada pasada encogida
  M3 vecinos    : k vecinos mas cercanos en el vector de features (juegos parecidos)
  M4 markov     : cadena de Markov de 24 estados (bases x outs) con el vector de tasas por turno (BB, 1B, 2B, 3B, HR, out)
                  de bateo propio contra pitcheo rival (log5 multinomial); distribucion exacta por programacion dinamica
  M5 boosting   : gradient boosting sobre el vector completo de features
  M6 pesos      : apilado logistico de todas las vistas (pesos optimizados con lo anterior en lugar del promedio simple)

Temporadas de prueba: cada temporada con al menos dos anteriores en la liga. Cada metodo solo ve lo anterior:
  - M1, M2, M4 son secuenciales (prediccion antes de actualizar con el juego).
  - Logistica, M3, M5 se entrenan con las temporadas previas; hiperparametros elegidos con la ultima temporada previa.
  - M6 se entrena con las predicciones fuera de muestra de temporadas de prueba anteriores.
Totales: misma capa de produccion (T* = a + b*T + c*M + d*E + nivel), ajustada con lo anterior, cambiando T por la vista nueva.

Uso:
    python trabajo/minar/2026-10-20_metodos_numericos.py            # todas las ligas
    python trabajo/minar/2026-10-20_metodos_numericos.py lmp lvbp   # solo esas
Salida: trabajo/minar/2026-10-20_metodos_numericos_resultados.json y tabla en consola.
"""
import json, math, os, sys, time
from collections import defaultdict

import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
os.environ.setdefault("EDGELINE_BASE", RAIZ)
from nucleo import features, capa_totales as CT          # noqa: E402
from modelos import beisbol as B                          # noqa: E402

FEATS = B.FEATS
EPS = 1e-6
ARRANQUE = 10      # juegos de temporada de cada equipo para la muestra de arranque


def sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def ll(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ============================================================ datos
def cargar():
    feats, _ = features.construir("beisbol", None)
    crudo = pd.read_csv(os.path.join(RAIZ, "datos", "beisbol.csv"), low_memory=False)
    crudo["gamePk"] = crudo["gamePk"].astype(str)
    return feats, crudo


CONT_B = ["bat_plateAppearances", "bat_baseOnBalls", "bat_hitByPitch", "bat_hits", "bat_doubles", "bat_triples",
          "bat_homeRuns", "bat_strikeOuts"]
CONT_P = ["pit_battersFaced", "pit_baseOnBalls", "pit_hitByPitch", "pit_hits", "pit_doubles", "pit_triples",
          "pit_homeRuns", "pit_strikeOuts"]


def vector_turno(pa, bb, hbp, h, d2, d3, hr, k):
    """Conteos -> vector de eventos por turno [BB+HBP, 1B, 2B, 3B, HR, OUT]."""
    s1 = max(h - d2 - d3 - hr, 0)
    out = max(pa - bb - hbp - h, 0)
    return np.array([bb + hbp, s1, d2, d3, hr, out], float)


def conteos_por_juego(crudo):
    """gamePk -> {'home': (vec_bat, vec_pit), 'away': ...} con los conteos del juego."""
    c = crudo.copy()
    for col in CONT_B + CONT_P:
        c[col] = pd.to_numeric(c[col], errors="coerce").fillna(0)
    out = {}
    for r in c.itertuples(index=False):
        d = r._asdict()
        vb = vector_turno(*[d[x] for x in CONT_B])
        vp = vector_turno(*[d[x] for x in CONT_P])
        lado = "home" if int(d["is_home"]) == 1 else "away"
        out.setdefault(d["gamePk"], {})[lado] = (vb, vp)
    return out


# ============================================================ base: MEDIA3 (logistica vectorizada, mismo algoritmo)
def entrenar_log(X, y, iters=400, lr=0.3, l2=1.0):
    mu = np.nanmean(X, 0); sd = np.nanstd(X, 0); sd[sd == 0] = 1
    Z = np.nan_to_num((X - mu) / sd)
    n, d = Z.shape
    w = np.zeros(d); b = 0.0
    for _ in range(iters):
        p = sig(Z @ w + b); e = p - y
        w -= lr * ((Z.T @ e) / n + l2 * w / n)
        b -= lr * e.mean()
    return w, b, mu, sd


def aplicar_log(m, X):
    w, b, mu, sd = m
    return sig(np.nan_to_num((X - mu) / sd) @ w + b)


def matriz(rows, cols=FEATS):
    return np.array([[np.nan if r.get(f) is None else r[f] for f in cols] for r in rows], float)


# ============================================================ M2 Kalman
def kalman(rows, rho, q_frac, p0_frac, sigma2, hfa):
    """rows en orden. Devuelve z (fuerza ajustada por incertidumbre) y diferencia de medias por juego."""
    m, P, temp = {}, {}, {}
    z, dif, pp = [], [], []
    q, p0 = q_frac * sigma2, p0_frac * sigma2
    for r in rows:
        s = r["season"]
        for e in (r["home"], r["away"]):
            if e not in m:
                m[e], P[e], temp[e] = 0.0, p0, s
            elif temp[e] != s:
                m[e] *= rho; P[e] = P[e] * rho ** 2 + p0; temp[e] = s
            P[e] += q
        h, a = r["home"], r["away"]
        mu = m[h] - m[a] + hfa
        S = sigma2 + P[h] + P[a]
        z.append(mu / math.sqrt(S)); dif.append(mu); pp.append(P[h] + P[a])
        y = r["marg_home"]
        if y is None:
            continue
        inn = y - mu
        kh, ka = P[h] / S, P[a] / S
        m[h] += kh * inn; m[a] -= ka * inn
        P[h] *= (1 - kh); P[a] *= (1 - ka)
    return np.array(z), np.array(dif), np.array(pp)


# ============================================================ M1 vectores ataque/defensa (log-lineal online)
def vectores(rows, carreras, eta, rho, eta_mu=0.002):
    """log lambda_local = mu + h + a_local + d_visita ; lambda_visita = mu + a_visita + d_local.
    a = ataque, d = debilidad defensiva. Gradiente de Poisson en escala log (y - lambda)/lambda * eta."""
    a, d, temp = {}, {}, {}
    mu, h = math.log(4.5), 0.03
    xh, xa = [], []
    for r in rows:
        s = r["season"]
        for e in (r["home"], r["away"]):
            if e not in a:
                a[e], d[e], temp[e] = 0.0, 0.0, s
            elif temp[e] != s:
                a[e] *= rho; d[e] *= rho; temp[e] = s
        H, A = r["home"], r["away"]
        lh = math.exp(mu + h + a[H] + d[A]); la = math.exp(mu + a[A] + d[H])
        xh.append(lh); xa.append(la)
        c = carreras.get(r["gamePk"])
        if c is None:
            continue
        yh, ya = c
        gh = (yh - lh) / max(lh, 0.5); ga = (ya - la) / max(la, 0.5)
        a[H] += eta * gh; d[A] += eta * gh
        a[A] += eta * ga; d[H] += eta * ga
        mu += eta_mu * (gh + ga); h += eta_mu * 0.5 * (gh - ga)
    return np.array(xh), np.array(xa)


# ============================================================ M4 Markov (24 estados) por programacion dinamica
RMAX = 15


def _transiciones():
    """Para cada evento (0 BB, 1 1B, 2 2B, 3 3B, 4 HR) y bases (bitmask 1=1a,2=2a,4=3a): (bases nuevas, carreras)."""
    T = {}
    for b in range(8):
        r1, r2, r3 = b & 1, (b >> 1) & 1, (b >> 2) & 1
        # BB forzado
        if r1 and r2 and r3:
            T[(0, b)] = (7, 1)
        elif r1 and r2:
            T[(0, b)] = (7, 0)
        elif r1:
            T[(0, b)] = (b | 2 | 1, 0)
        else:
            T[(0, b)] = (b | 1, 0)
        # sencillo: corredor de 1a a 2a; de 2a y 3a anotan
        T[(1, b)] = (1 | (2 if r1 else 0), r2 + r3)
        # doble: de 1a a 3a; de 2a y 3a anotan
        T[(2, b)] = (2 | (4 if r1 else 0), r2 + r3)
        T[(3, b)] = (4, r1 + r2 + r3)
        T[(4, b)] = (0, 1 + r1 + r2 + r3)
    return T


TRANS = _transiciones()


def _correr(v, rr):
    """Desplaza la distribucion de carreras rr lugares; lo que pasa de RMAX se acumula en el ultimo."""
    if rr == 0:
        return v
    w = np.zeros_like(v)
    w[rr:] = v[:-rr]
    w[-1] += v[-rr:].sum()
    return w


def dist_entrada(p):
    """p = vector [BB, 1B, 2B, 3B, HR, OUT] -> distribucion de carreras en media entrada (0..RMAX).
    Programacion dinamica sobre los 24 estados (outs 0-2 x 8 combinaciones de bases)."""
    cur = {(0, 0): np.eye(RMAX + 1)[0]}
    fin = np.zeros(RMAX + 1)
    for _ in range(60):
        nxt = {}
        for (o, b), v in cur.items():
            if o == 2:
                fin += v * p[5]
            else:
                k = (o + 1, b); nxt[k] = nxt.get(k, 0) + v * p[5]
            for ev in range(5):
                nb, rr = TRANS[(ev, b)]
                k = (o, nb); nxt[k] = nxt.get(k, 0) + _correr(v * p[ev], rr)
        cur = {k: v for k, v in nxt.items() if v.sum() > 1e-9}
        if not cur:
            break
    for v in cur.values():
        fin += v
    return fin / fin.sum()


def conv_n(d, n):
    out = np.zeros(1); out[0] = 1.0
    for _ in range(n):
        out = np.convolve(out, d)
    return out


def markov_juego(ph, pa):
    """ph: tasas del local al bat; pa: de la visita. -> (p_local, total esperado, dist total)."""
    dh, da = dist_entrada(ph), dist_entrada(pa)
    Rh, Ra = conv_n(dh, 9), conv_n(da, 9)
    n = max(len(Rh), len(Ra)); Rh = np.pad(Rh, (0, n - len(Rh))); Ra = np.pad(Ra, (0, n - len(Ra)))
    cRa = np.cumsum(Ra)
    p_gana = float((Rh[1:] * cRa[:-1]).sum())
    p_emp = float((Rh * Ra).sum())
    # extra innings: comparacion de una entrada
    m = max(len(dh), len(da)); dh2 = np.pad(dh, (0, m - len(dh))); da2 = np.pad(da, (0, m - len(da)))
    gh = float((dh2[1:] * np.cumsum(da2)[:-1]).sum()); ga = float((da2[1:] * np.cumsum(dh2)[:-1]).sum())
    px = gh / (gh + ga) if gh + ga > 0 else 0.5
    p = p_gana + p_emp * px
    tot = float((np.arange(n) * Rh).sum() + (np.arange(n) * Ra).sum())
    return p, tot


def log5(bat, pit, liga):
    r = bat * pit / np.maximum(liga, 1e-9)
    return r / r.sum()


def markov(rows, cont, kprior=300.0):
    """Tasas as-of por equipo (bateo y pitcheo permitido), encogidas a un prior (mitad temporada pasada, mitad liga)."""
    tabs = {"b": {}, "p": {}}; prev = {"b": {}, "p": {}}; temp = {"b": {}, "p": {}}
    liga_s, liga_prev, cur_season = {}, None, None
    cache = {}
    out_p, out_t = [], []
    for r in rows:
        s = r["season"]
        if s != cur_season:
            if cur_season is not None:
                liga_prev = liga_s[cur_season]
            cur_season = s; liga_s[s] = np.zeros(6)
        base_prev = liga_prev / liga_prev.sum() if liga_prev is not None and liga_prev.sum() > 0 \
            else np.array([9, 15, 4.5, .5, 2.5, 68.5]) / 100
        Lg = liga_s[s] + base_prev * 2000
        lr = Lg / Lg.sum()

        def tasa(e, t):
            if temp[t].get(e) != s:
                if e in tabs[t] and tabs[t][e].sum() > 0:
                    prev[t][e] = tabs[t][e] / tabs[t][e].sum()
                tabs[t][e] = np.zeros(6); temp[t][e] = s
            pr = 0.5 * prev[t][e] + 0.5 * lr if e in prev[t] else lr
            v = tabs[t][e] + kprior * pr
            return v / v.sum()

        H, A = r["home"], r["away"]
        bh, ph_, ba, pa_ = tasa(H, "b"), tasa(H, "p"), tasa(A, "b"), tasa(A, "p")
        vh, va = log5(bh, pa_, lr), log5(ba, ph_, lr)
        key = (tuple(np.round(vh, 3)), tuple(np.round(va, 3)))
        if key not in cache:
            cache[key] = markov_juego(np.array(key[0]) / sum(key[0]), np.array(key[1]) / sum(key[1]))
        p, t = cache[key]
        out_p.append(p); out_t.append(t)
        c = cont.get(r["gamePk"])
        if c and "home" in c and "away" in c:
            tabs["b"][H] += c["home"][0]; tabs["p"][H] += c["home"][1]
            tabs["b"][A] += c["away"][0]; tabs["p"][A] += c["away"][1]
            liga_s[s] += c["home"][0] + c["away"][0]
    return np.array(out_p), np.array(out_t)


# ============================================================ metricas
def comparar(p_new, p_base, y, mask=None):
    if mask is not None:
        p_new, p_base, y = p_new[mask], p_base[mask], y[mask]
    n = len(y)
    if n < 30:
        return {"n": int(n)}
    d = ll(p_base, y) - ll(p_new, y)            # positivo = el metodo mejora
    z = d.mean() / (d.std(ddof=1) / math.sqrt(n)) if d.std() > 0 else 0.0
    h = n // 2
    return {"n": int(n), "logloss": round(float(ll(p_new, y).mean()), 4),
            "logloss_base": round(float(ll(p_base, y).mean()), 4),
            "mejora_milesimas": round(1000 * float(d.mean()), 2), "z": round(float(z), 2),
            "mitades": [round(1000 * float(d[:h].mean()), 2), round(1000 * float(d[h:].mean()), 2)],
            "brier": round(float(((p_new - y) ** 2).mean()), 4),
            "calibracion": round(float(abs(p_new.mean() - y.mean())), 3),
            "acierto_pct": round(100 * float(((p_new >= .5) == (y == 1)).mean()), 1)}


def veredicto(c):
    if c.get("n", 0) < 300 or "z" not in c:
        return "muestra chica"
    ok = c["mejora_milesimas"] > 0 and c["z"] >= 2.0 and min(c["mitades"]) > 0 and c["calibracion"] <= 0.04
    return "PASA" if ok else "no pasa"


def comparar_total(t_new, t_base, real, mask=None):
    if mask is not None:
        t_new, t_base, real = t_new[mask], t_base[mask], real[mask]
    n = len(real)
    if n < 30:
        return {"n": int(n)}
    d = np.abs(t_base - real) - np.abs(t_new - real)
    z = d.mean() / (d.std(ddof=1) / math.sqrt(n)) if d.std() > 0 else 0.0
    h = n // 2
    return {"n": int(n), "mae": round(float(np.abs(t_new - real).mean()), 3),
            "mae_base": round(float(np.abs(t_base - real).mean()), 3),
            "mejora_mae": round(float(d.mean()), 3), "z": round(float(z), 2),
            "mitades": [round(float(d[:h].mean()), 3), round(float(d[h:].mean()), 3)],
            "sesgo": round(float((t_new - real).mean()), 3)}


def veredicto_total(c):
    if c.get("n", 0) < 300 or "z" not in c:
        return "muestra chica"
    return "PASA" if c["mejora_mae"] > 0 and c["z"] >= 2.0 and min(c["mitades"]) > 0 else "no pasa"


# ============================================================ capa de totales (igual a produccion, walk-forward)
def capa_total(T, M, E, real, temporada, temporadas_prueba):
    """T* = a + b*T + c*M + d*E + nivel; coeficientes con temporadas anteriores; nivel = media ultimos 300 residuos.
    Tambien p(over) a la linea ~promedio (floor(M) + 0.5) con la distribucion empirica de los ultimos 300 residuos."""
    out = np.full(len(T), np.nan); po = np.full(len(T), np.nan)
    for S in temporadas_prueba:
        tr = temporada < S; te = temporada == S
        if tr.sum() < 200:
            continue
        X = np.c_[np.ones(tr.sum()), T[tr], M[tr], E[tr]]
        coef, *_ = np.linalg.lstsq(X, real[tr], rcond=None)
        pred = np.c_[np.ones(len(T)), T, M, E] @ coef
        res = list(real[tr] - pred[tr])[-300:]
        for i in np.where(te)[0]:
            r_ = np.array(res); niv = r_.mean()
            out[i] = pred[i] + niv
            linea = math.floor(M[i]) + 0.5
            po[i] = ((out[i] + (r_ - niv)) > linea).mean()
            res.append(real[i] - pred[i]); res = res[-300:]
    return out, po


def capa_sobre_base(p_m, base, y, temporada, prueba):
    """logit p' = logit base + c + b*(logit p_m - logit base); b y c con temporadas de prueba anteriores."""
    from scipy.optimize import minimize
    out = np.full(len(y), np.nan); betas = {}
    lb, x = logit(base), logit(p_m) - logit(base)
    for S in prueba[1:]:
        tr = (temporada < S) & (temporada >= prueba[0]) & ~np.isnan(x) & ~np.isnan(lb); te = temporada == S
        if tr.sum() < 300:
            continue
        f = lambda w: ll(sig(lb[tr] + w[0] + w[1] * x[tr]), y[tr]).mean() + 1e-3 * (w ** 2).sum()
        w = minimize(f, np.zeros(2), method="BFGS").x
        out[te] = sig(lb[te] + w[0] + w[1] * np.nan_to_num(x[te])); betas[int(S)] = round(float(w[1]), 3)
    return out, betas


def comparar_ou(po_new, po_base, real, M, mask):
    yv = (real > np.floor(M) + 0.5).astype(float)
    c = comparar(np.clip(po_new, 0.02, 0.98), np.clip(po_base, 0.02, 0.98), yv, mask)
    return c


# ============================================================ por liga
def correr_liga(liga, rows, cont):
    t0 = time.time()
    rows = sorted(rows, key=lambda r: (r["game_date"], r["gamePk"]))
    rows = [r for r in rows if r.get("y_home") is not None and r.get("total") is not None]
    temporada = np.array([int(r["season"]) for r in rows])
    temps = sorted(set(temporada))
    prueba = temps[2:]
    if not prueba:
        return None
    y = np.array([r["y_home"] for r in rows], float)
    real = np.array([r["total"] for r in rows], float)
    n = len(rows)

    # juegos de temporada jugados por cada equipo antes del juego (para la muestra de arranque)
    jj, cnt = [], defaultdict(int)
    for r in rows:
        jj.append(max(cnt[(r["season"], r["home"])], cnt[(r["season"], r["away"])]))
        cnt[(r["season"], r["home"])] += 1; cnt[(r["season"], r["away"])] += 1
    jj = np.array(jj)

    # carreras por lado (para M1)
    carreras = {}
    for r in rows:
        tot, mg = r["total"], r["marg_home"]
        carreras[r["gamePk"]] = ((tot + mg) / 2.0, (tot - mg) / 2.0)

    # ---------------- base MEDIA3 y logistica walk-forward
    X = matriz(rows)
    pe = sig(np.array([(r.get("elo_dif") or 0) / 173.0 for r in rows]))
    pc = np.array([B.prob_por_carreras(r) if B.prob_por_carreras(r) is not None else np.nan for r in rows])
    pl = np.full(n, np.nan)
    for S in prueba:
        tr, te = temporada < S, temporada == S
        m = entrenar_log(X[tr], y[tr])
        pl[te] = aplicar_log(m, X[te])
    base = np.where(np.isnan(pc), (pe + pl) / 2, (pe + pl + np.nan_to_num(pc)) / 3)

    # ---------------- M2 Kalman (hiperparametros con las temporadas antes de la primera de prueba)
    pre = temporada < prueba[0]
    sigma2 = float(np.var([r["marg_home"] for r, k in zip(rows, pre) if k]))
    hfa = float(np.mean([r["marg_home"] for r, k in zip(rows, pre) if k]))
    mejor = None
    for rho in (0.3, 0.5, 0.7):
        for q in (0.0005, 0.002, 0.006):
            for p0 in (0.02, 0.06):
                zk, _, _ = kalman(rows, rho, q, p0, sigma2, hfa)
                # Platt en la primera mitad de lo previo, calificado en la segunda (no toca prueba)
                idx = np.where(pre)[0]; a_, b_ = idx[: len(idx) // 2], idx[len(idx) // 2:]
                if len(a_) < 100:
                    continue
                mk = entrenar_log(zk[a_, None], y[a_], iters=300)
                sc = ll(aplicar_log(mk, zk[b_, None]), y[b_]).mean()
                if mejor is None or sc < mejor[0]:
                    mejor = (sc, rho, q, p0)
    _, rho_k, q_k, p0_k = mejor
    zk, difk, Pk = kalman(rows, rho_k, q_k, p0_k, sigma2, hfa)
    p_kal = np.full(n, np.nan)
    for S in prueba:
        tr, te = temporada < S, temporada == S
        mk = entrenar_log(zk[tr, None], y[tr], iters=300)
        p_kal[te] = aplicar_log(mk, zk[te, None])

    # ---------------- M1 vectores
    mejor = None
    for eta in (0.01, 0.02, 0.04):
        for rho in (0.3, 0.6):
            xh, xa = vectores(rows, carreras, eta, rho)
            idx = np.where(pre)[0][len(np.where(pre)[0]) // 2:]
            sc = (np.abs(xh[idx] + xa[idx] - real[idx])).mean()
            if mejor is None or sc < mejor[0]:
                mejor = (sc, eta, rho)
    _, eta_v, rho_v = mejor
    vxh, vxa = vectores(rows, carreras, eta_v, rho_v)
    pv_raw = np.array([B.p_gana_carreras(a, b) for a, b in zip(vxh, vxa)])
    p_vec = np.full(n, np.nan)
    for S in prueba:
        tr, te = temporada < S, temporada == S
        mv = entrenar_log(logit(pv_raw)[tr, None], y[tr], iters=300)
        p_vec[te] = aplicar_log(mv, logit(pv_raw)[te, None])

    # ---------------- M4 Markov

    pm_raw, tm_raw = markov(rows, cont)
    p_mar = np.full(n, np.nan)
    for S in prueba:
        tr, te = temporada < S, temporada == S
        mm = entrenar_log(logit(pm_raw)[tr, None], y[tr], iters=300)
        p_mar[te] = aplicar_log(mm, logit(pm_raw)[te, None])

    # ---------------- M3 vecinos y M5 boosting (vector completo de features)
    from sklearn.neighbors import NearestNeighbors
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    Xv = np.c_[X, np.array([[r.get("of_home") or np.nan, r.get("of_away") or np.nan, r.get("df_home") or np.nan,
                              r.get("df_away") or np.nan, r.get("lg_rs") or np.nan] for r in rows]), jj]
    p_knn = np.full(n, np.nan); t_knn = np.full(n, np.nan)
    p_gbm = np.full(n, np.nan); t_gbm = np.full(n, np.nan)
    k_elegidos = {}
    for S in prueba:
        tr, te = temporada < S, temporada == S
        mu = np.nanmean(X[tr], 0); sd = np.nanstd(X[tr], 0); sd[sd == 0] = 1
        Z = np.nan_to_num((X - mu) / sd)
        # K con la ultima temporada previa como validacion
        ultima = max(t for t in temps if t < S)
        a_, b_ = temporada < ultima, temporada == ultima
        mejorK = None
        if a_.sum() > 200:
            nnv = NearestNeighbors().fit(Z[a_])
            for K in (50, 100, 200, 400):
                if K > a_.sum():
                    continue
                _, ind = nnv.kneighbors(Z[b_], n_neighbors=K)
                pk = (y[a_][ind].sum(1) + 10 * y[a_].mean()) / (K + 10)
                sc = ll(pk, y[b_]).mean()
                if mejorK is None or sc < mejorK[0]:
                    mejorK = (sc, K)
        K = mejorK[1] if mejorK else min(100, int(tr.sum()))
        k_elegidos[int(S)] = K
        nn = NearestNeighbors().fit(Z[tr])
        _, ind = nn.kneighbors(Z[te], n_neighbors=min(K, int(tr.sum())))
        p_knn[te] = (y[tr][ind].sum(1) + 10 * y[tr].mean()) / (ind.shape[1] + 10)
        lg_tr = np.array([r.get("lg_rs") or np.nan for r in rows])
        esc = np.nan_to_num(lg_tr[te] / np.nanmean(lg_tr[tr][ind], 1), nan=1.0)
        t_knn[te] = real[tr][ind].mean(1) * esc
        gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.04, max_iter=250, l2_regularization=1.0,
                                            min_samples_leaf=40, random_state=0)
        gb.fit(Xv[tr], y[tr]); p_gbm[te] = gb.predict_proba(Xv[te])[:, 1]
        gr = HistGradientBoostingRegressor(loss="poisson", max_depth=3, learning_rate=0.04, max_iter=250,
                                           min_samples_leaf=40, random_state=0)
        gr.fit(Xv[tr], real[tr]); t_gbm[te] = gr.predict(Xv[te])

    # ---------------- M6 apilado (pesos optimizados) con predicciones fuera de muestra de temporadas de prueba previas
    vistas = {"elo": pe, "logistica": pl, "carreras": np.where(np.isnan(pc), base, pc), "kalman": p_kal,
              "vectores": p_vec, "markov": p_mar, "vecinos": p_knn, "boosting": p_gbm}
    L = np.c_[[logit(v) for v in vistas.values()]].T
    p_stk = np.full(n, np.nan); pesos = {}
    p_stk3 = np.full(n, np.nan)            # solo las tres vistas de produccion con pesos optimizados
    for S in prueba[1:]:
        tr = (temporada < S) & (temporada >= prueba[0]); te = temporada == S
        ok = tr & ~np.isnan(L).any(1)
        if ok.sum() < 300:
            continue
        ms = entrenar_log(L[ok], y[ok], iters=500, l2=5.0)
        p_stk[te] = aplicar_log(ms, np.nan_to_num(L[te]))
        pesos[int(S)] = dict(zip(vistas, [round(float(w / s), 3) for w, s in zip(ms[0], ms[3])]))
        m3 = entrenar_log(L[ok][:, :3], y[ok], iters=500, l2=5.0)
        p_stk3[te] = aplicar_log(m3, np.nan_to_num(L[te][:, :3]))

    # ---------------- ganador: comparaciones
    enprueba = np.isin(temporada, prueba) & ~np.isnan(base)
    arr = enprueba & (jj < ARRANQUE)
    res = {"liga": liga, "juegos": int(n), "temporadas_prueba": [int(s) for s in prueba],
           "hiper": {"kalman": {"rho": rho_k, "q": q_k, "p0": p0_k}, "vectores": {"eta": eta_v, "rho": rho_v},
                     "vecinos_K": k_elegidos},
           "base": {"todo": comparar(base, base, y, enprueba), "arranque": comparar(base, base, y, arr)},
           "ganador": {}, "totales": {}}
    nuevos = {"M1 vectores": p_vec, "M2 kalman": p_kal, "M3 vecinos": p_knn, "M4 markov": p_mar,
              "M5 boosting": p_gbm, "M6 pesos (todas)": p_stk, "M6 pesos (3 de produccion)": p_stk3}
    for nom, p in nuevos.items():
        msk = enprueba & ~np.isnan(p)
        todo = comparar(p, base, y, msk)
        ar = comparar(p, base, y, msk & (jj < ARRANQUE))
        res["ganador"][nom] = {"todo": todo, "veredicto": veredicto(todo), "arranque": ar,
                               "veredicto_arranque": veredicto(ar)}
        if not nom.startswith("M6"):
            pc_, betas = capa_sobre_base(p, base, y, temporada, prueba)
            m2 = enprueba & ~np.isnan(pc_)
            t2 = comparar(pc_, base, y, m2); a2 = comparar(pc_, base, y, m2 & (jj < ARRANQUE))
            res["ganador"][nom + " (capa sobre base)"] = {"todo": t2, "veredicto": veredicto(t2), "arranque": a2,
                                                          "veredicto_arranque": veredicto(a2), "beta": betas}
    res["pesos_apilado"] = pesos

    # ---------------- totales con la capa de produccion
    juegos = [(r["game_date"], r["home"], r["away"], r["total"]) for r in rows]
    rit = CT.Ritmo(juegos)
    ME = np.array([rit.estado(r["game_date"], r["home"], r["away"]) or (np.nan, np.nan) for r in rows], float)
    ME[:, 0] = np.where(np.isnan(ME[:, 0]), np.nanmean(real[:50]), ME[:, 0]); ME[:, 1] = np.where(np.isnan(ME[:, 1]), ME[:, 0], ME[:, 1])
    M, E = ME[:, 0], ME[:, 1]
    t_mod = np.array([sum(B.carreras_esperadas(r)) if B.carreras_esperadas(r)[0] is not None else np.nan for r in rows])
    t_mod = np.where(np.isnan(t_mod), M, t_mod)
    t_base, po_base = capa_total(t_mod, M, E, real, temporada, prueba)
    vistas_t = {"M1 vectores": vxh + vxa, "M3 vecinos": np.where(np.isnan(t_knn), M, t_knn),
                "M4 markov": tm_raw, "M5 boosting": np.where(np.isnan(t_gbm), M, t_gbm)}
    okb = enprueba & ~np.isnan(t_base)
    res["totales"]["base_capa"] = {"todo": comparar_total(t_base, t_base, real, okb),
                                   "ou": comparar_ou(po_base, po_base, real, M, okb)}
    for nom, T in vistas_t.items():
        tc, po = capa_total(T, M, E, real, temporada, prueba)
        msk = okb & ~np.isnan(tc)
        todo = comparar_total(tc, t_base, real, msk)
        ar = comparar_total(tc, t_base, real, msk & (jj < ARRANQUE))
        ou = comparar_ou(po, po_base, real, M, msk)
        res["totales"][nom] = {"todo": todo, "veredicto": veredicto_total(todo), "arranque": ar,
                               "veredicto_arranque": veredicto_total(ar), "ou": ou, "veredicto_ou": veredicto(ou)}
    # promedio de las vistas de total (ensamble simple) dentro de la capa
    Tens = np.nanmean(np.c_[t_mod, vxh + vxa, tm_raw, np.where(np.isnan(t_gbm), M, t_gbm)], 1)
    tc, po = capa_total(Tens, M, E, real, temporada, prueba)
    msk = okb & ~np.isnan(tc)
    todo = comparar_total(tc, t_base, real, msk)
    ou = comparar_ou(po, po_base, real, M, msk)
    res["totales"]["M6 promedio de vistas"] = {"todo": todo, "veredicto": veredicto_total(todo),
                                               "arranque": comparar_total(tc, t_base, real, msk & (jj < ARRANQUE)),
                                               "ou": ou, "veredicto_ou": veredicto(ou)}
    res["segundos"] = round(time.time() - t0, 1)
    if os.environ.get("MN_GUARDAR"):
        np.savez(os.path.join(os.environ["MN_GUARDAR"], "mn_%s.npz" % liga), y=y, temporada=temporada, jj=jj,
                 base=base, pe=pe, pl=pl, pc=pc, real=real, t_base=t_base, po_base=po_base, M=M,
                 enprueba=enprueba, **{k.split()[0] + "_" + k.split()[1]: v for k, v in nuevos.items() if "(" not in k})
    return res


def main(ligas=None):
    feats, crudo = cargar()
    cont = conteos_por_juego(crudo)
    por = defaultdict(list)
    for r in feats:
        por[r["league"]].append(r)
    salida = {"generado": time.strftime("%Y-%m-%d %H:%M"), "arranque_juegos": ARRANQUE, "ligas": {}}
    for lg in sorted(por):
        if ligas and lg not in ligas:
            continue
        print("==", lg, len(por[lg]), "juegos", flush=True)
        r = correr_liga(lg, por[lg], cont)
        if r is None:
            print("   sin temporadas suficientes"); continue
        salida["ligas"][lg] = r
        b = r["base"]["todo"]
        print("   base MEDIA3: n %s logloss %s | arranque n %s" % (b["n"], b.get("logloss"), r["base"]["arranque"]["n"]))
        for nom, v in r["ganador"].items():
            t, a = v["todo"], v["arranque"]
            print("   %-28s %+6s mil z %5s mitades %s cal %s -> %s | arranque %+6s z %5s -> %s" % (
                nom, t.get("mejora_milesimas"), t.get("z"), t.get("mitades"), t.get("calibracion"), v["veredicto"],
                a.get("mejora_milesimas"), a.get("z"), v["veredicto_arranque"]))
        print("   totales base capa MAE", r["totales"]["base_capa"]["todo"].get("mae"))
        for nom, v in r["totales"].items():
            if nom == "base_capa":
                continue
            t = v["todo"]
            o = v.get("ou", {})
            print("   %-28s MAE %s (%+s) z %s mitades %s -> %s | O/U %+s mil z %s -> %s" % (
                nom, t.get("mae"), t.get("mejora_mae"), t.get("z"), t.get("mitades"), v["veredicto"],
                o.get("mejora_milesimas"), o.get("z"), v.get("veredicto_ou")))
        print("   (%.0f s)" % r["segundos"], flush=True)
    ruta = os.path.join(RAIZ, "trabajo", "minar", "2026-10-20_metodos_numericos_resultados.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print("escrito", ruta)


if __name__ == "__main__":
    main(set(a.lower() for a in sys.argv[1:]) or None)
