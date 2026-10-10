# -*- coding: utf-8 -*-
"""
utilidades/motor_carreras.py - MOTOR DE CARRERAS por equipo para beisbol (10-oct-2026, Alejandro: "empieza con todo lo
de baseball, porque mi principal mercado que es LMP empieza pronto").

Idea: un solo modelo del marcador. Cada equipo tiene ATAQUE y DEFENSA que cambian partido a partido (filtro de Kalman
extendido sobre el log de las carreras, con su incertidumbre). De las carreras esperadas de cada equipo salen, con la
misma distribucion (binomial negativa), el GANADOR, el TOTAL, los TOTALES POR EQUIPO y la RUN LINE: todo cuadra.

    log lambda_local  = log(nivel local de la liga) + ataque_local  - defensa_visita + abridor_visita + parque
    log lambda_visita = log(nivel visita de la liga) + ataque_visita - defensa_local + abridor_local  + parque
    carreras ~ NB(lambda, r)          empate en 9 -> extras: el local gana el 52 % (como modelos/beisbol.py)

  - nivel de la liga: promedio con olvido de las carreras de local y de visita (se ajusta solo a cambios de reglas).
  - ataque/defensa: EKF con ruido de proceso q por partido; al cambiar de temporada se encogen (rho) y se abre la
    incertidumbre. Se recentran cada dia (promedio 0).
  - abridor (LMP y NPB, nucleo/abridores.py): carreras que permite su abridor respecto al promedio de los abridores de
    ese equipo (kappa).
  - parque y clima (nucleo/parques.py, donde aplica): delta del total en el log de las dos lambdas.
Hiperparametros por liga (q, rho, P0, kappa, parque, r) con el 40 % mas viejo de cada liga; nada del periodo de prueba.

Comparacion (protocolo de siempre, n >= 300, z >= 2.0, las dos mitades, calibrado) contra PRODUCCION reproducida
partido a partido como en utilidades/validar_mercados.validar_beisbol: logistica media3 reentrenada cada 30 dias,
abridores, parque y clima, y la capa de totales (24 meses de precalentamiento).

Mercados: Ganador, Ganador mezcla (logit: w motor + 1-w produccion, w elegido en el 40 % viejo), Total esperado (MAE),
Over/Under a la linea ~promedio, Run line local -1.5, Carreras local / visita esperadas (MAE), Total por equipo O/U.

Uso:
    python utilidades/motor_carreras.py                 # todas las ligas
    python utilidades/motor_carreras.py --ligas LMP
Escribe trabajo/minar/2026-10-10_motor_carreras_resultados.json
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, itertools, json, math, os, sys
from collections import defaultdict

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
from nucleo import io  # noqa: E402

LIGAS = ["LMP", "MLB", "NPB", "KBO", "LVBP", "LIDOM", "ABL"]
RUTA_OUT = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_motor_carreras_resultados.json")
EXTRA_LOCAL = 0.52
KMAX = 26


def _sig(z):
    return 1 / (1 + math.exp(-max(min(z, 35), -35)))


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def medio(x):
    return math.floor(x) + 0.5


# ------------------------------------------------------------------ binomial negativa
def nb_pmf_vec(mu, r, kmax=KMAX):
    k = np.arange(kmax)
    p = r / (r + mu)
    lg = np.array([math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1) for i in k])
    v = np.exp(lg + r * math.log(p) + k * math.log(1 - p))
    v[-1] += max(0.0, 1 - v.sum())                    # cola en el ultimo
    return v


def mercados(lh, la, r, lineas, linea_eq):
    """probabilidades de todos los mercados desde las dos lambdas."""
    ph, pa = nb_pmf_vec(lh, r), nb_pmf_vec(la, r)
    M = np.outer(ph, pa)                               # M[i, j] = P(local i, visita j)
    i, j = np.indices(M.shape)
    gana = M[i > j].sum(); emp = M[i == j].sum()
    tot = i + j
    out = {"p_home": float(gana + EXTRA_LOCAL * emp), "lh": lh, "la": la,
           "rl_home": float(M[i - j >= 2].sum()),
           "over": {L: float(M[tot > L].sum()) for L in lineas},
           "eq_h": float(ph[np.arange(len(ph)) > linea_eq[0]].sum()),
           "eq_a": float(pa[np.arange(len(pa)) > linea_eq[1]].sum())}
    return out


def nb_ll(k, mu, r):
    p = r / (r + mu)
    return math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p)


# ------------------------------------------------------------------ juegos de una liga
def juegos(liga):
    from nucleo import features as F
    feats, _ = F.construir("beisbol", liga, 0)
    lg = io.norm(liga)
    G = []
    for r in feats:
        if r["league"] != lg or r.get("total") is None or r.get("marg_home") is None:
            continue
        rh = (r["total"] + r["marg_home"]) / 2.0; ra = r["total"] - rh
        G.append(dict(gp=str(r["gamePk"]), f=r["game_date"][:10], season=str(r.get("season")), h=r["home"], a=r["away"],
                      rh=int(round(rh)), ra=int(round(ra))))
    G.sort(key=lambda g: (g["f"], g["gp"]))
    return G


def abridores_rel(liga, G):
    """{(gp, equipo): carreras extra que permite su abridor vs. el promedio de los abridores de ese equipo (as-of)}."""
    from nucleo import abridores as AB
    lg = io.norm(liga)
    if lg not in ("lmp", "npb"):
        return {}
    V = AB.historicos(io.BASE, lg)
    if not V:
        return {}
    out, prom = {}, {}
    for g in G:
        for e in (g["h"], g["a"]):
            v = V.get((g["gp"], e))
            if not v:
                continue
            runs = (v[0] - v[3]) * v[1] / 9.0          # carreras sobre la liga que permite en su salida
            m, n = prom.get(e, (0.0, 0.0))
            if n >= 3:
                out[(g["gp"], e)] = runs - m / n
            prom[e] = (0.97 * m + runs, 0.97 * n + 1)
    return out


def parques_delta(liga, G):
    from nucleo import parques as PQ
    lg = io.norm(liga)
    if not PQ.aplica(lg):
        return {}
    V = PQ.historicos(io.BASE, lg)
    out = {}
    for g in G:
        v = V.get((g["gp"], g["h"]))
        if v:
            out[g["gp"]] = PQ.delta(lg, v[0], v[1], v[2])
    return out


# ------------------------------------------------------------------ motor (EKF)
def correr_motor(G, prm, ABR, PQD, r_nb):
    q, rho, p0, kap, usa_pq = prm["q"], prm["rho"], prm["p0"], prm["kappa"], prm["parque"]
    a = defaultdict(float); d = defaultdict(float)
    Pa = defaultdict(lambda: p0); Pd = defaultdict(lambda: p0)
    ult = {}
    nivel = [4.5, 4.3]; LAM = 0.5 ** (1 / 600.0)
    num = [0.0, 0.0]; den = 0.0
    pred = {}
    por_dia = defaultdict(list)
    for g in G:
        por_dia[g["f"]].append(g)
    for f in sorted(por_dia):
        fd = dt.date.fromisoformat(f)
        dia = por_dia[f]
        # temporada nueva por equipo (hueco > 60 dias): encoger y abrir incertidumbre
        for g in dia:
            for e in (g["h"], g["a"]):
                if e in ult and (fd - ult[e]).days > 60:
                    a[e] *= rho; d[e] *= rho; Pa[e] += p0; Pd[e] += p0
                Pa[e] += q; Pd[e] += q
        nh, na = (num[0] / den, num[1] / den) if den > 50 else nivel
        upd = []
        for g in dia:
            pk = PQD.get(g["gp"], 0.0) if usa_pq else 0.0
            tot0 = nh + na
            fpq = math.log(max(tot0 + pk, 0.5 * tot0) / tot0) if pk else 0.0
            sh = kap * ABR.get((g["gp"], g["a"]), 0.0) / na if kap else 0.0      # abridor visita -> carreras del local
            sa = kap * ABR.get((g["gp"], g["h"]), 0.0) / nh if kap else 0.0
            eh = math.log(nh) + a[g["h"]] - d[g["a"]] + fpq + sh
            ea = math.log(na) + a[g["a"]] - d[g["h"]] + fpq + sa
            lh, la = math.exp(eh), math.exp(ea)
            pred[g["gp"]] = (lh, la, math.sqrt(Pa[g["h"]] + Pd[g["a"]]), math.sqrt(Pa[g["a"]] + Pd[g["h"]]))
            upd.append((g, lh, la))
        for g, lh, la in upd:
            for k, lam, at, df in ((g["rh"], lh, g["h"], g["a"]), (g["ra"], la, g["a"], g["h"])):
                info = lam * r_nb / (r_nb + lam)
                score = (k - lam) * r_nb / (r_nb + lam)
                S = Pa[at] + Pd[df] + 1.0 / info
                z = score / info
                ka, kd = Pa[at] / S, Pd[df] / S
                a[at] += ka * z; d[df] -= kd * z
                Pa[at] -= ka * Pa[at]; Pd[df] -= kd * Pd[df]
            num[0] = LAM * num[0] + g["rh"]; num[1] = LAM * num[1] + g["ra"]; den = LAM * den + 1
            ult[g["h"]] = fd; ult[g["a"]] = fd
        # recentrar (promedio 0 entre los equipos vistos)
        if a:
            ma = sum(a.values()) / len(a); md = sum(d.values()) / len(d)
            for e in list(a):
                a[e] -= ma
            for e in list(d):
                d[e] -= md
    return pred


def ll_runs(G, pred, r_nb, desde, hasta):
    s = n = 0
    for g in G:
        if not (desde <= g["f"] < hasta) or g["gp"] not in pred:
            continue
        lh, la = pred[g["gp"]][:2]
        s += nb_ll(g["rh"], lh, r_nb) + nb_ll(g["ra"], la, r_nb); n += 1
    return s / max(n, 1)


def estimar_r(G, pred, desde, hasta):
    mejor = None
    for r in (2, 3, 4, 5, 6, 8, 10, 14, 20, 30):
        v = ll_runs(G, pred, r, desde, hasta)
        if mejor is None or v > mejor[0]:
            mejor = (v, r)
    return mejor[1]


def afinar(G, ABR, PQD, corte):
    """rejilla de hiperparametros con los juegos anteriores a 'corte' (despues de la primera temporada)."""
    inicio = G[0]["f"]
    calent = (dt.date.fromisoformat(inicio) + dt.timedelta(days=200)).isoformat()
    base = dict(q=0.001, rho=0.6, p0=0.02, kappa=0.0, parque=0)
    r_nb = estimar_r(G, correr_motor(G, base, ABR, PQD, 6.0), calent, corte)
    grid = dict(q=[0.00003, 0.0001, 0.0003, 0.001], rho=[0.0, 0.15, 0.3, 0.6], p0=[0.001, 0.0025, 0.005, 0.02],
                kappa=[0.0, 0.5, 1.0] if ABR else [0.0], parque=[0, 1] if PQD else [0])
    mejor = None
    for vals in itertools.product(*grid.values()):
        prm = dict(zip(grid.keys(), vals))
        v = ll_runs(G, correr_motor(G, prm, ABR, PQD, r_nb), r_nb, calent, corte)
        if mejor is None or v > mejor[0]:
            mejor = (v, prm)
    prm = mejor[1]
    r_nb = estimar_r(G, correr_motor(G, prm, ABR, PQD, r_nb), calent, corte)
    return prm, r_nb


# ------------------------------------------------------------------ produccion reproducida (validar_beisbol)
def _logistica_np(prev):
    from modelos import beisbol as B
    mu, sd = B._estandarizar(prev)
    X = np.array([B._vec(r, mu, sd) for r in prev]); y = np.array([r["y_home"] for r in prev], float)
    n, k = X.shape
    w = np.zeros(k); b = 0.0
    for _ in range(400):
        p = 1 / (1 + np.exp(-np.clip(X @ w + b, -35, 35)))
        e = p - y
        gw = X.T @ e; gb = e.sum()
        w = w - 0.3 * (gw / n + 1.0 * w / n); b = b - 0.3 * (gb / n)
    return {"w": list(w), "b": float(b), "mu": mu, "sd": sd, "cs_home": B._prom(prev, "cs_home"), "ca_home": B._prom(prev, "ca_home")}


def produccion(liga, bloque=30, precal_meses=24):
    from nucleo import features as F
    from nucleo import abridores as AB
    from nucleo import parques as PQ
    from nucleo import capa_totales as CT
    from modelos import beisbol as B
    feats, _ = F.construir("beisbol", liga, 5)
    lg = io.norm(liga)
    G = [r for r in feats if r["league"] == lg and r.get("y_home") is not None and r.get("total") is not None]
    G.sort(key=lambda r: r["game_date"])
    VAB = AB.historicos(io.BASE, lg) if AB.aplica(lg) else {}
    K_AB, ESC_AB = AB.coeficientes(lg)
    VPQ = PQ.historicos(io.BASE, lg) if PQ.aplica(lg) else {}
    ritmo = CT.Ritmo([(r["game_date"], r["home"], r["away"], r["total"]) for r in G])
    out = {}
    capa = []
    d0 = dt.date.fromisoformat(G[0]["game_date"][:10]); ultimo = dt.date.fromisoformat(G[-1]["game_date"][:10])
    nb = 0
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=bloque)
        blk = [r for r in G if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in G if r["game_date"][:10] < d0.isoformat()]
        if blk and len(prev) >= 300:
            modelo = _logistica_np(prev); nb += 1
            for r in blk:
                p = B.prob(modelo, r)
                xh, xa = B.carreras_esperadas(r)
                if xh is None:
                    continue
                if B.COHERENTE:
                    xh, xa = B.ajustar_carreras(xh, xa, p)
                if VAB:
                    vh, va = VAB.get((r["gamePk"], r["home"])), VAB.get((r["gamePk"], r["away"]))
                    if vh and va:
                        sh, sa = AB.carreras_salvadas(r.get("df_home"), vh), AB.carreras_salvadas(r.get("df_away"), va)
                        p = _sig(_lg(p) + K_AB * (sh - sa))
                        xh, xa = max(xh - ESC_AB * sa, 0.5), max(xa - ESC_AB * sh, 0.5)
                if VPQ:
                    v = VPQ.get((r["gamePk"], r["home"]))
                    if v:
                        xh, xa = PQ.ajustar(xh, xa, lg, v[0], v[1], v[2])
                gp = str(r["gamePk"])
                out[gp] = dict(p=p, xh=xh, xa=xa, b=nb)
                st = ritmo.estado(r["game_date"][:10], r["home"], r["away"])
                if st:
                    capa.append(dict(gp=gp, b=nb, pred=xh + xa, real=r["total"], M=st[0], E=st[1], f=r["game_date"][:10]))
        d0 = d1
    # capa de totales: cada bloque se ajusta con los bloques anteriores
    bloques = sorted({x["b"] for x in capa})
    for bq in bloques:
        prev = [x for x in capa if x["b"] < bq]
        if len(prev) < CT.MIN_PREV:
            continue
        coef, res = CT.entrenar([(x["pred"], x["real"], x["M"], x["E"], x["f"]) for x in prev])
        for x in capa:
            if x["b"] == bq:
                out[x["gp"]]["t_capa"] = CT.total(coef, x["pred"], x["M"], x["E"])
                out[x["gp"]]["res_capa"] = res
    return out


def nb_over(mu, L, r=4.0):
    from modelos import beisbol as B
    return 1 - sum(B._nb_pmf(k, mu, r) for k in range(int(math.floor(L)) + 1))


# ------------------------------------------------------------------ evaluacion
def _ll(p, y):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def comparar_prob(filas, nombre):
    """filas: (fecha, y, q_produccion, q_motor). Mejora = log loss produccion - motor."""
    if len(filas) < 50:
        return {"mercado": nombre, "n": len(filas), "veredicto": "muestra insuficiente"}
    filas.sort()
    d = np.array([_ll(q0, y) - _ll(q1, y) for _, y, q0, q1 in filas])
    y = np.array([f[1] for f in filas]); q0 = np.array([f[2] for f in filas]); q1 = np.array([f[3] for f in filas])
    n = len(d); m = d.mean(); sd = d.std(ddof=1) or 1e-12; z = m / (sd / math.sqrt(n)); h = n // 2
    cal = float(q1.mean() - y.mean())
    ver = "muestra insuficiente" if n < 300 else ("pasa" if (z >= 2 and d[:h].mean() > 0 and d[h:].mean() > 0 and abs(cal) <= 0.04) else "no pasa")
    b0, b1 = float(np.mean((q0 - y) ** 2)), float(np.mean((q1 - y) ** 2))
    return {"mercado": nombre, "n": n, "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2),
            "mitades": [round(1000 * d[:h].mean(), 3), round(1000 * d[h:].mean(), 3)],
            "brier_prod": round(b0, 5), "brier_motor": round(b1, 5), "brier_mejora_pct": round(100 * (b0 - b1) / b0, 2),
            "cal_motor": round(cal, 4), "cal_prod": round(float(q0.mean() - y.mean()), 4), "veredicto": ver}


def comparar_val(filas, nombre):
    """filas: (fecha, real, pred_produccion, pred_motor). Mejora = |error| produccion - |error| motor (carreras)."""
    if len(filas) < 50:
        return {"mercado": nombre, "n": len(filas), "veredicto": "muestra insuficiente"}
    filas.sort()
    d = np.array([abs(r - a) - abs(r - b) for _, r, a, b in filas])
    n = len(d); m = d.mean(); sd = d.std(ddof=1) or 1e-12; z = m / (sd / math.sqrt(n)); h = n // 2
    sesgo = float(np.mean([b - r for _, r, a, b in filas]))
    ver = "muestra insuficiente" if n < 300 else ("pasa" if (z >= 2 and d[:h].mean() > 0 and d[h:].mean() > 0) else "no pasa")
    return {"mercado": nombre, "n": n, "mae_prod": round(float(np.mean([abs(r - a) for _, r, a, b in filas])), 3),
            "mae_motor": round(float(np.mean([abs(r - b) for _, r, a, b in filas])), 3),
            "mejora_milesimas": round(1000 * m, 2), "z": round(z, 2), "mitades": [round(1000 * d[:h].mean(), 2), round(1000 * d[h:].mean(), 2)],
            "sesgo_motor": round(sesgo, 3), "veredicto": ver}


def apilar(filas, minimo=300):
    """apilado walk-forward: cada mes, logistica sobre [logit q_produccion, logit q_motor] con TODO lo anterior (meses
    previos de la prueba). Devuelve filas (fecha, y, q_produccion, q_apilado) desde que hay 'minimo' previos."""
    from sklearn.linear_model import LogisticRegression
    filas = sorted(filas)
    out = []
    meses = sorted({f[0][:7] for f in filas})
    for m in meses:
        prev = [f for f in filas if f[0][:7] < m]
        cur = [f for f in filas if f[0][:7] == m]
        if len(prev) < minimo:
            continue
        X = np.array([[_lg(f[2]), _lg(f[3])] for f in prev]); y = np.array([f[1] for f in prev])
        lr = LogisticRegression(C=1.0).fit(X, y)
        q = lr.predict_proba(np.array([[_lg(f[2]), _lg(f[3])] for f in cur]))[:, 1]
        out += [(f[0], f[1], f[2], float(qq)) for f, qq in zip(cur, q)]
    return out


def evaluar_liga(liga):
    print("\n" + "=" * 100 + "\n%s" % liga)
    G = juegos(liga)
    if len(G) < 800:
        print("  muestra insuficiente (%d juegos)" % len(G)); return None
    ABR = abridores_rel(liga, G); PQD = parques_delta(liga, G)
    corte = G[int(len(G) * 0.4)]["f"]
    prm, r_nb = afinar(G, ABR, PQD, corte)
    print("  %d juegos (%s a %s); afinado con lo anterior a %s: %s, r %.0f; abridores %d, parque %d" % (
        len(G), G[0]["f"], G[-1]["f"], corte, prm, r_nb, len(ABR), len(PQD)))
    pred = correr_motor(G, prm, ABR, PQD, r_nb)
    P = produccion(liga)
    print("  produccion reproducida: %d juegos (%d con capa de totales)" % (len(P), sum(1 for v in P.values() if "t_capa" in v)))
    # lineas como el validador: alrededor del promedio de los juegos anteriores; total por equipo: promedio por lado
    acum = [0.0, 0.0, 0.0, 0]
    # mezcla: w elegido en el periodo de afinado (con produccion disponible)
    filas = []
    for g in G:
        tot = g["rh"] + g["ra"]
        if acum[3] >= 300 and g["gp"] in pred and g["gp"] in P:
            base_tot = acum[0] / acum[3]; Lm = medio(base_tot)
            leq = (medio(acum[1] / acum[3]), medio(acum[2] / acum[3]))
            lh, la = pred[g["gp"]][:2]
            mk = mercados(lh, la, r_nb, [Lm], leq)
            filas.append((g, mk, P[g["gp"]], Lm, leq))
        acum[0] += tot; acum[1] += g["rh"]; acum[2] += g["ra"]; acum[3] += 1
    afin = [x for x in filas if x[0]["f"] < corte]
    mejor_w = (None, 0.0)
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        ll = sum(_ll(_sig(w * _lg(mk["p_home"]) + (1 - w) * _lg(pp["p"])), 1 if g["rh"] > g["ra"] else 0) for g, mk, pp, _, _ in afin)
        if mejor_w[0] is None or ll < mejor_w[0]:
            mejor_w = (ll, w)
    w = mejor_w[1]
    prueba = [x for x in filas if x[0]["f"] >= corte]
    print("  prueba: %d juegos desde %s; peso del motor en la mezcla (afinado): %.2f" % (len(prueba), corte, w))
    R = {"liga": liga, "parametros": prm, "r_nb": r_nb, "w_mezcla": w, "corte": corte, "n_prueba": len(prueba), "mercados": []}
    gan, mez, ou, ouc, rl, eqh, eqa, tv, tvc, xh_, xa_, eqhc, eqac = ([] for _ in range(13))
    for g, mk, pp, Lm, leq in prueba:
        y = 1 if g["rh"] > g["ra"] else 0; tot = g["rh"] + g["ra"]
        gan.append((g["f"], y, pp["p"], mk["p_home"]))
        mez.append((g["f"], y, pp["p"], _sig(w * _lg(mk["p_home"]) + (1 - w) * _lg(pp["p"]))))
        if tot != Lm:
            ou.append((g["f"], 1 if tot > Lm else 0, nb_over(pp["xh"] + pp["xa"], Lm), mk["over"][Lm]))
            if "t_capa" in pp:
                res = pp["res_capa"]
                pc = sum(1 for e in res if pp["t_capa"] + e > Lm) / len(res)
                ouc.append((g["f"], 1 if tot > Lm else 0, min(max(pc, 0.01), 0.99), mk["over"][Lm]))
        from modelos import beisbol as B
        rlp, _ = B.prob_run_line({}, 1.5, xh=pp["xh"], xa=pp["xa"])
        rl.append((g["f"], 1 if g["rh"] - g["ra"] >= 2 else 0, rlp, mk["rl_home"]))
        eqh.append((g["f"], 1 if g["rh"] > leq[0] else 0, nb_over(pp["xh"], leq[0]), mk["eq_h"]))
        if "t_capa" in pp:                                   # como plataforma: marcadores escalados al total de la capa
            esc = pp["t_capa"] / (pp["xh"] + pp["xa"])
            eqhc.append((g["f"], 1 if g["rh"] > leq[0] else 0, nb_over(pp["xh"] * esc, leq[0]), mk["eq_h"]))
            eqac.append((g["f"], 1 if g["ra"] > leq[1] else 0, nb_over(pp["xa"] * esc, leq[1]), mk["eq_a"]))
        eqa.append((g["f"], 1 if g["ra"] > leq[1] else 0, nb_over(pp["xa"], leq[1]), mk["eq_a"]))
        tv.append((g["f"], tot, pp["xh"] + pp["xa"], mk["lh"] + mk["la"]))
        if "t_capa" in pp:
            tvc.append((g["f"], tot, pp["t_capa"], mk["lh"] + mk["la"]))
        xh_.append((g["f"], g["rh"], pp["xh"], mk["lh"])); xa_.append((g["f"], g["ra"], pp["xa"], mk["la"]))
    # el apilado aprende tambien con los juegos del periodo de afinado (anteriores al corte) y se califica solo en la prueba
    gan_t, ouc_t = [], []
    for g, mk, pp, Lm, leq in filas:
        if g["f"] >= corte:
            continue
        tot = g["rh"] + g["ra"]
        gan_t.append((g["f"], 1 if g["rh"] > g["ra"] else 0, pp["p"], mk["p_home"]))
        if "t_capa" in pp and tot != Lm:
            pc = sum(1 for e in pp["res_capa"] if pp["t_capa"] + e > Lm) / len(pp["res_capa"])
            ouc_t.append((g["f"], 1 if tot > Lm else 0, min(max(pc, 0.01), 0.99), mk["over"][Lm]))
    gst = [f for f in apilar(gan_t + gan) if f[0] >= corte]
    ost = [f for f in apilar(ouc_t + ouc) if f[0] >= corte]
    for out in (comparar_prob(gan, "Ganador (motor vs produccion)"),
                comparar_prob(gst, "Ganador (apilado vs produccion)"),
                comparar_prob(ost, "Over/Under (apilado vs capa de totales)"),
                comparar_prob(mez, "Ganador (mezcla vs produccion)"),
                comparar_prob(ou, "Over/Under linea ~promedio (vs modelo)"),
                comparar_prob(ouc, "Over/Under linea ~promedio (vs capa de totales)"),
                comparar_prob(rl, "Run line local -1.5"),
                comparar_prob(eqh, "Total local O/U"),
                comparar_prob(eqa, "Total visita O/U"),
                comparar_prob(eqhc, "Total local O/U (vs escalado a la capa)"),
                comparar_prob(eqac, "Total visita O/U (vs escalado a la capa)"),
                comparar_val(tv, "Total esperado (vs modelo)"),
                comparar_val(tvc, "Total esperado (vs capa de totales)"),
                comparar_val(xh_, "Carreras local esperadas"),
                comparar_val(xa_, "Carreras visita esperadas")):
        R["mercados"].append(out)
        if out.get("z") is None:
            print("  %-48s n %5d  %s" % (out["mercado"], out["n"], out["veredicto"].upper())); continue
        extra = ("Brier %+.2f%%  cal motor %+.3f (prod %+.3f)" % (out["brier_mejora_pct"], out["cal_motor"], out["cal_prod"])) \
            if "brier_mejora_pct" in out else ("MAE %.3f -> %.3f  sesgo motor %+.2f" % (out["mae_prod"], out["mae_motor"], out["sesgo_motor"]))
        print("  %-48s n %5d  mejora %+8.3f  z %+6.2f  mitades %+.3f/%+.3f  %s  -> %s" % (
            out["mercado"], out["n"], out["mejora_milesimas"], out["z"], out["mitades"][0], out["mitades"][1], extra, out["veredicto"].upper()))
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default=",".join(LIGAS))
    a = ap.parse_args()
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "ligas": []}
    if os.path.exists(RUTA_OUT):
        try:
            viejo = json.load(open(RUTA_OUT, encoding="utf-8"))
            res["ligas"] = [x for x in viejo.get("ligas", []) if x["liga"] not in a.ligas.upper().split(",")]
        except Exception:
            pass
    for L in [x.strip().upper() for x in a.ligas.split(",") if x.strip()]:
        R = evaluar_liga(L)
        if R:
            res["ligas"].append(R)
            with open(RUTA_OUT, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nresultados en", RUTA_OUT)


if __name__ == "__main__":
    main()
