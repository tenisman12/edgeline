# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_bayes_hockey.py - TODOS los angulos de ganador de hockey a la vez, en un modelo bayesiano jerarquico.

Hipotesis (registrada antes de correr, 10-oct-2026): los angulos situacionales, medidos uno por uno, no pasan en ninguna liga de
hockey. Juntos, con efectos compartidos entre ligas (encogimiento jerarquico), mejoran la prediccion as-of del modelo de hockey
fuera de muestra (log loss), con z >= 2.0, las dos mitades a favor y calibrado |p media - tasa real| <= 0.04.

Modelo (logistica con offset, MAP con priors normales = bayes empirico):
    logit P(gana local) = a_liga + b_liga * logit(p_modelo) + sum_k (mu_k + d_liga,k) * x_k / sd_k
    mu_k ~ N(0, tau^2)       efecto comun del angulo k en hockey
    d_liga,k ~ N(0, sig^2)   desviacion de cada liga (sig chico = todas las ligas comparten el efecto)
La base es el MISMO modelo sin angulos (a_liga + b_liga * logit p): la mejora no viene de recalibrar.
tau y sig se eligen dentro del entrenamiento (ultimo 20 % como validacion), sin ver la prueba.

Walk-forward: se ordena todo por fecha; desde el 40 % de los partidos, cada mes se reentrena con todo lo anterior y se predice
ese mes. Veredicto con el protocolo de siempre (n >= 300, z >= 2.0, mitades, calibracion). Tambien por liga.

Angulos (mismas definiciones que el minado, x > 0 favorece al local): H1-H8, H13-H18, H21-H23 (tanda 1 y 3), Q1-Q7
(cualitativos), S1-S4, S7, S8 (tanda 5). Sin porteros (H19, H20: las ligas europeas y la AHL no traen el titular).

Contra el mercado (prueba B): no hay cuotas historicas de hockey en el repo (cuotas_sharp_2026.csv empieza el 1-oct-2026),
asi que esa prueba se hace en vivo con salida/historial_angulos.csv.

Uso:
    python utilidades/minar_angulos_bayes_hockey.py            # arma las filas (lento la primera vez) y evalua
    python utilidades/minar_angulos_bayes_hockey.py --cache    # reusa trabajo/minar/bayes_hockey_filas.pkl
    python utilidades/minar_angulos_bayes_hockey.py --cache --ml   # ademas boosting y red neuronal con el mismo walk-forward
Escribe trabajo/minar/2026-10-10_bayes_hockey_resultados.json
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, contextlib, datetime as dt, io, json, math, os, pickle, sys
from collections import defaultdict

import numpy as np
from scipy.optimize import minimize

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)

LIGAS = ["NHL", "SHL", "LIIGA", "AHL", "DEL"]
H = ["H1", "H2", "H4", "H6", "H7", "H8", "H13", "H14", "H15", "H16", "H17", "H18", "H21", "H22", "H23"]
QS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6a", "Q6b", "Q7"]
SS = ["S1", "S2", "S3", "S4", "S7", "S8"]
ANG = H + QS + SS
RUTA_CACHE = os.path.join(CODIGO, "trabajo", "minar", "bayes_hockey_filas.pkl")
RUTA_OUT = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_bayes_hockey_resultados.json")
GRID_TAU = [0.01, 0.03, 0.06, 0.10, 0.20]
GRID_SIG = [0.005, 0.03, 0.08]


# ------------------------------------------------------------------ filas: prediccion as-of + todos los angulos
def armar():
    import minar_situacionales as M
    import minar_cualitativos as Q
    import minar_angulos_tanda5 as T5
    filas = []
    for L in LIGAS:
        with contextlib.redirect_stdout(io.StringIO()):
            M.correr_hockey(L)
        F, C = M.ULTIMO[L]
        T = Q.Tabla(C)
        F5 = {str(r["gp"]): r for r in T5.construir("NHL", F, C)}
        n0 = len(filas)
        for r in F:
            x = {k: r.get(k) for k in H if k != "H23"}
            x["H23"] = M._ind((C.en_ventana(r["away"], r["gp"], 5) or 0) >= 3) - M._ind((C.en_ventana(r["home"], r["gp"], 5) or 0) >= 3)
            s = Q.situaciones(r, C, T)
            for c in QS:
                lado = s.get(c)
                x[c] = 1 if lado == "H" else (-1 if lado == "A" else 0)       # AMBOS o sin dato = 0
            s5 = F5.get(str(r["gp"])) or {}
            for c in SS:
                x[c] = s5.get(c)
            filas.append(dict(liga=L, fecha=str(r["fecha"])[:10], gp=str(r["gp"]), p=float(r["p"]), y=int(r["y"]),
                              home=r["home"], away=r["away"], x={k: (0.0 if v is None else float(v)) for k, v in x.items()}))
        print("  %-6s %6d partidos con prediccion as-of y angulos" % (L, len(filas) - n0))
    filas.sort(key=lambda r: (r["fecha"], r["liga"], r["gp"]))
    return filas


# ------------------------------------------------------------------ modelo jerarquico (MAP)
def _lgt(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class Jerarquico:
    def __init__(self, nl, nk, tau, sig, con_angulos=True):
        self.nl, self.nk, self.tau, self.sig, self.ang = nl, nk, tau, sig, con_angulos

    def _partes(self, w):
        nl, nk = self.nl, self.nk
        a = w[:nl]; b = w[nl:2 * nl]
        if not self.ang:
            return a, b, None, None
        mu = w[2 * nl:2 * nl + nk]; d = w[2 * nl + nk:].reshape(nl, nk)
        return a, b, mu, d

    def _eta(self, w, li, off, X):
        a, b, mu, d = self._partes(w)
        eta = a[li] + b[li] * off
        if self.ang:
            eta = eta + np.einsum("ij,ij->i", X, mu[None, :] + d[li])
        return eta

    def ajustar(self, li, off, X, y):
        nl, nk = self.nl, self.nk
        npar = 2 * nl + (nk + nl * nk if self.ang else 0)
        w0 = np.zeros(npar); w0[nl:2 * nl] = 1.0
        oh = np.zeros((len(y), nl)); oh[np.arange(len(y)), li] = 1.0

        def f(w):
            a, b, mu, d = self._partes(w)
            eta = self._eta(w, li, off, X)
            p = 1 / (1 + np.exp(-eta))
            ll = np.sum(np.logaddexp(0, eta) - y * eta)
            r = p - y
            ga = oh.T @ r; gb = oh.T @ (r * off)
            pen = 0.5 * np.sum(a ** 2) / 1.0 + 0.5 * np.sum((b - 1) ** 2) / 1.0
            ga = ga + a; gb = gb + (b - 1)
            g = [ga, gb]
            if self.ang:
                gmu = X.T @ r + mu / self.tau ** 2
                gd = np.zeros((nl, nk))
                np.add.at(gd, li, X * r[:, None])
                gd = gd + d / self.sig ** 2
                pen += 0.5 * np.sum(mu ** 2) / self.tau ** 2 + 0.5 * np.sum(d ** 2) / self.sig ** 2
                g += [gmu, gd.ravel()]
            return ll + pen, np.concatenate(g)
        res = minimize(f, w0, jac=True, method="L-BFGS-B", options={"maxiter": 2000})
        self.w = res.x
        return self

    def predecir(self, li, off, X):
        return 1 / (1 + np.exp(-self._eta(self.w, li, off, X)))


def _ll(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def matrices(F, sd=None):
    li = np.array([LIGAS.index(r["liga"]) for r in F])
    off = _lgt(np.array([r["p"] for r in F]))
    X = np.array([[r["x"][k] for k in ANG] for r in F], float)
    y = np.array([r["y"] for r in F], float)
    if sd is None:
        sd = X.std(axis=0); sd[sd < 1e-9] = 1.0
    return li, off, X / sd, y, sd


def elegir(Ftr):
    """tau y sig con el ultimo 20 % del entrenamiento como validacion."""
    cut = int(len(Ftr) * 0.8)
    a, b = Ftr[:cut], Ftr[cut:]
    li, off, X, y, sd = matrices(a)
    li2, off2, X2, y2, _ = matrices(b, sd)
    mejor = None
    for t in GRID_TAU:
        for s in GRID_SIG:
            m = Jerarquico(len(LIGAS), len(ANG), t, s).ajustar(li, off, X, y)
            v = float(np.mean(_ll(m.predecir(li2, off2, X2), y2)))
            if mejor is None or v < mejor[0]:
                mejor = (v, t, s)
    return mejor[1], mejor[2]


def _mes(f):
    return f[:7]


def walk_forward(F, inicio_frac=0.4):
    i0 = int(len(F) * inicio_frac)
    meses = sorted({_mes(r["fecha"]) for r in F[i0:]})
    preds = []
    hip = None
    for k, m in enumerate(meses):
        tr = [r for r in F if _mes(r["fecha"]) < m]
        te = [r for r in F if _mes(r["fecha"]) == m]
        if len(tr) < 2000 or not te:
            continue
        if hip is None or k % 6 == 0:                  # hiperparametros cada 6 meses
            hip = elegir(tr)
        li, off, X, y, sd = matrices(tr)
        lt, ot, Xt, yt, _ = matrices(te, sd)
        mb = Jerarquico(len(LIGAS), len(ANG), 1, 1, con_angulos=False).ajustar(li, off, X, y)
        ma = Jerarquico(len(LIGAS), len(ANG), hip[0], hip[1]).ajustar(li, off, X, y)
        q0, q1 = mb.predecir(lt, ot, Xt), ma.predecir(lt, ot, Xt)
        for r, a, b_, xx in zip(te, q0, q1, Xt):
            preds.append(dict(liga=r["liga"], fecha=r["fecha"], y=r["y"], q0=float(a), q1=float(b_),
                              activo=bool(np.any(xx != 0)), tau=hip[0], sig=hip[1]))
        print("  %s  entrena %6d  prueba %4d  tau %.2f sig %.3f  mejora %+.3f milesimas" % (
            m, len(tr), len(te), hip[0], hip[1], 1000 * float(np.mean(_ll(q0, yt) - _ll(q1, yt)))))
    return preds


def veredicto(P, etiqueta):
    if not P:
        return {"grupo": etiqueta, "n": 0, "veredicto": "muestra insuficiente"}
    y = np.array([p["y"] for p in P], float); q0 = np.array([p["q0"] for p in P]); q1 = np.array([p["q1"] for p in P])
    d = _ll(q0, y) - _ll(q1, y)
    n = len(d); m = float(d.mean()); sd = float(d.std(ddof=1)) or 1e-12
    z = m / (sd / math.sqrt(n)); h = n // 2
    m1, m2 = float(d[:h].mean()), float(d[h:].mean())
    cal = float(q1.mean() - y.mean())
    b0, b1 = float(np.mean((q0 - y) ** 2)), float(np.mean((q1 - y) ** 2))
    dec = []
    orden = np.argsort(q1)
    for g in np.array_split(orden, 10):
        dec.append([round(float(q1[g].mean()), 3), round(float(y[g].mean()), 3)])
    cal_max = max(abs(a - b) for a, b in dec)
    mov = float(np.mean(np.abs(q1 - q0)))
    ver = "muestra insuficiente" if n < 300 else (
        "pasa" if (z >= 2.0 and m1 > 0 and m2 > 0 and abs(cal) <= 0.04) else "no pasa")
    return {"grupo": etiqueta, "n": n, "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2),
            "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)], "brier_base": round(b0, 5), "brier_angulos": round(b1, 5),
            "brier_mejora_pct": round(100 * (b0 - b1) / b0, 2), "calibracion": round(cal, 4), "deciles": dec,
            "cal_peor_decil": round(cal_max, 3), "mueve_pp_medio": round(100 * mov, 2), "veredicto": ver,
            "desde": P[0]["fecha"], "hasta": P[-1]["fecha"]}


def efectos_finales(F):
    """modelo con todo el historial: efecto comun de cada angulo (pp en un partido de 50 % con x tipico)."""
    t, s = elegir(F)
    li, off, X, y, sd = matrices(F)
    m = Jerarquico(len(LIGAS), len(ANG), t, s).ajustar(li, off, X, y)
    a, b, mu, d = m._partes(m.w)
    Xr = np.array([[r["x"][k] for k in ANG] for r in F], float)
    out = []
    for j, k in enumerate(ANG):
        act = np.abs(Xr[:, j])[Xr[:, j] != 0]
        xt = float(np.median(act)) if len(act) else 1.0
        e = mu[j] * xt / sd[j]
        por = {L: round(100 * (1 / (1 + math.exp(-(mu[j] + d[i, j]) * xt / sd[j])) - 0.5), 2) for i, L in enumerate(LIGAS)}
        out.append({"codigo": k, "activos": int(len(act)), "x_tipico": xt, "comun_pp": round(100 * (1 / (1 + math.exp(-e)) - 0.5), 2),
                    "por_liga_pp": por})
    out.sort(key=lambda r: -abs(r["comun_pp"]))
    return {"tau": t, "sig": s, "angulos": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", action="store_true")
    a = ap.parse_args()
    if a.cache and os.path.exists(RUTA_CACHE):
        F = pickle.load(open(RUTA_CACHE, "rb"))
    else:
        print("armando filas (prediccion as-of por liga y angulos)...")
        F = armar()
        os.makedirs(os.path.dirname(RUTA_CACHE), exist_ok=True)
        pickle.dump(F, open(RUTA_CACHE, "wb"))
    print("%d partidos, %d angulos; desde %s hasta %s" % (len(F), len(ANG), F[0]["fecha"], F[-1]["fecha"]))
    for L in LIGAS:
        G = [r for r in F if r["liga"] == L]
        if G:
            print("  %-6s %6d  %s a %s" % (L, len(G), G[0]["fecha"], G[-1]["fecha"]))
    print("\nwalk-forward mensual")
    P = walk_forward(F)
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "angulos": ANG,
           "hipotesis": "todos los angulos de ganador juntos, jerarquico entre ligas, mejoran al modelo de hockey fuera de muestra",
           "total": veredicto(P, "HOCKEY"),
           "por_liga": [veredicto([p for p in P if p["liga"] == L], L) for L in LIGAS],
           "solo_activos": veredicto([p for p in P if p["activo"]], "HOCKEY con algun angulo activo")}
    print("\nRESULTADO")
    for v in [res["total"], res["solo_activos"]] + res["por_liga"]:
        if v.get("n"):
            print("  %-34s n %6d  mejora %+.3f mil  z %+5.2f  mitades %+.3f/%+.3f  Brier %+.2f%%  cal %+.4f (peor decil %.3f)  "
                  "mueve %.2f pp  -> %s" % (v["grupo"], v["n"], v["mejora_milesimas"], v["z"], v["mitades"][0], v["mitades"][1],
                                         v["brier_mejora_pct"], v["calibracion"], v["cal_peor_decil"], v["mueve_pp_medio"],
                                         v["veredicto"].upper()))
    print("\nefectos con todo el historial")
    ef = efectos_finales(F)
    res["efectos"] = ef
    print("  tau %.2f  sig %.3f" % (ef["tau"], ef["sig"]))
    for e in ef["angulos"]:
        print("  %-4s activos %6d  comun %+5.2f pp  %s" % (e["codigo"], e["activos"], e["comun_pp"],
                                                       " ".join("%s %+.2f" % (k, v) for k, v in e["por_liga_pp"].items())))
    with open(RUTA_OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nresultados en", RUTA_OUT)



# ------------------------------------------------------------------ comparacion: boosting y red neuronal (mismo walk-forward)
def walk_forward_ml(F, inicio_frac=0.4, cada=3):
    """HistGradientBoosting y un MLP chico con logit(p), liga y los angulos; reentrena cada `cada` meses (costo)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.neural_network import MLPClassifier
    i0 = int(len(F) * inicio_frac)
    meses = sorted({_mes(r["fecha"]) for r in F[i0:]})
    out = []
    mods = None
    for k, m in enumerate(meses):
        tr = [r for r in F if _mes(r["fecha"]) < m]
        te = [r for r in F if _mes(r["fecha"]) == m]
        if len(tr) < 2000 or not te:
            continue
        li, off, X, y, sd = matrices(tr)
        lt, ot, Xt, yt, _ = matrices(te, sd)
        oh = lambda l: np.eye(len(LIGAS))[l]
        Z, Zt = np.column_stack([off, oh(li), X]), np.column_stack([ot, oh(lt), Xt])
        if mods is None or k % cada == 0:
            mb = Jerarquico(len(LIGAS), len(ANG), 1, 1, con_angulos=False).ajustar(li, off, X, y)
            gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.03, max_iter=300, l2_regularization=1.0,
                                                min_samples_leaf=100, random_state=0).fit(Z, y)
            nn = MLPClassifier(hidden_layer_sizes=(16,), alpha=1e-2, max_iter=500, early_stopping=True, random_state=0).fit(Z, y)
            mods = (mb, gb, nn)
        mb, gb, nn = mods
        q0 = mb.predecir(lt, ot, Xt); qg = gb.predict_proba(Zt)[:, 1]; qn = nn.predict_proba(Zt)[:, 1]
        for r, a, g, n_ in zip(te, q0, qg, qn):
            out.append(dict(liga=r["liga"], fecha=r["fecha"], y=r["y"], q0=float(a), qg=float(g), qn=float(n_)))
    return out


def comparar_ml(F):
    P = walk_forward_ml(F)
    res = {}
    for clave, nombre in (("qg", "boosting (HistGradientBoosting)"), ("qn", "red neuronal (MLP 16)")):
        res[nombre] = veredicto([dict(p, q1=p[clave]) for p in P], nombre)
    return res



if __name__ == "__main__":
    main()
    if "--ml" in sys.argv:
        R = comparar_ml(pickle.load(open(RUTA_CACHE, "rb")))
        for k, v in R.items():
            print("  %-34s n %6d  mejora %+.3f mil  z %+5.2f  mitades %+.3f/%+.3f  Brier %+.2f%%  -> %s" % (
                k, v["n"], v["mejora_milesimas"], v["z"], v["mitades"][0], v["mitades"][1], v["brier_mejora_pct"], v["veredicto"].upper()))
        r = json.load(open(RUTA_OUT, encoding="utf-8")); r["comparacion_ml"] = R
        with open(RUTA_OUT, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
