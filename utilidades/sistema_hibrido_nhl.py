# -*- coding: utf-8 -*-
"""
utilidades/sistema_hibrido_nhl.py - sistema hibrido NHL: Super Learner (prediccion) + TMLE (efecto de angulos).

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_hibrido_nhl.md
- Super Learner: 6 aprendices sobre la prediccion as-of del modelo y variables calculadas solo con el pasado;
  pesos por validacion cruzada hacia adelante en el 70 % mas antiguo; prueba una vez en el 30 % mas reciente.
- TMLE: efecto causal de cada angulo sobre la probabilidad de que gane el local, ajustado por fuerza.
No toca modelos/ ni nucleo/. Requiere numpy, scipy y scikit-learn (pip install numpy scipy scikit-learn).

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/sistema_hibrido_nhl.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json, math, os, sys, warnings
import numpy as np
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingClassifier

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402
from modelos import hockey as H  # noqa: E402


# ------------------------------------------------------------------ datos as-of
def construir():
    orig_j = H._juegos; todos = orig_j(None)
    CUR = [None]; tmp = {}; recs = []

    class _It(list):
        def __iter__(self):
            for it in list.__iter__(self):
                CUR[0] = it
                yield it
    o_base, o_b2b = H._xg_base, H._aplicar_b2b

    def w_base(th, ta, lg):
        tmp["elo"] = (th.elo, ta.elo); return o_base(th, ta, lg)

    def w_b2b(xh, xa, bh, ba, fac):
        recs.append((CUR[0], tmp.get("elo"), xh, xa)); return o_b2b(xh, xa, bh, ba, fac)
    H._juegos = lambda l=None: _It(orig_j(l)); H._xg_base = w_base; H._aplicar_b2b = w_b2b
    try:
        est = H.entrenar(None)
    finally:
        H._juegos = orig_j; H._xg_base = o_base; H._aplicar_b2b = o_b2b
    cal = est["cal"]; assert len(cal) == len(recs)
    C = M.Calendario()
    for f, gp, h, a in todos:
        gh, ga = M._num(h.get("goals")), M._num(h.get("goals_opp"))
        if gh is None or ga is None: continue
        fin = (h.get("ended_in") or "").strip()
        ot = (fin in ("OT", "SO")) if fin else None      # None = sin dato de como termino
        for row, loc, gf, gc, riv in ((h, True, gh, ga, a.get("team")), (a, False, ga, gh, h.get("team"))):
            C.agregar(row.get("team"), f, gp, loc, gf, gc, riv, ot=ot, sh=M._num(row.get("shots")), sha=M._num(row.get("shots_opp")))
    C.cerrar()

    def l10(e, gp):
        i = C.i(e, gp); prev = C.t[e][max(0, i - 10):i]
        if len(prev) < 5: return None, None, None
        gd = sum(g["gf"] - g["ga"] for g in prev) / len(prev)
        s = [g for g in prev if g["sh"] and g["sha"]]
        if len(s) < 5: return gd, None, None
        sd = sum(g["sh"] - g["sha"] for g in s) / len(s)
        pdo = sum(g["gf"] for g in s) / sum(g["sh"] for g in s) + 1 - sum(g["ga"] for g in s) / sum(g["sha"] for g in s)
        return gd, sd, pdo
    filas = []
    for (p, y), ((f, gp, h, a), elo, xh0, xa0) in zip(cal, recs):
        th, ta = h.get("team"), a.get("team")
        rh, ra = C.descanso(th, gp), C.descanso(ta, gp)
        if rh is None or ra is None: continue
        gdh, sdh, pdoh = l10(th, gp); gda, sda, pdoa = l10(ta, gp)
        if gdh is None or gda is None: continue
        bh, ba = rh == 1, ra == 1
        pa = C.prev(ta, gp); ph = C.prev(th, gp)
        has = sdh is not None and sda is not None
        r = dict(fecha=f, gp=gp, y=y, p=p, p0=H._prob_home(xh0, xa0), elo_d=(elo[0] - elo[1]) if elo else 0.0,
                 gd10=gdh - gda, sh10=(sdh - sda) if has else 0.0, pdo10=(pdoh - pdoa) if has else 0.0, has_sh=1.0 if has else 0.0,
                 H1=float(ba and not bh), H2=float(bh and not ba), H4=float((1 if rh - ra == 1 else -1) if abs(rh - ra) == 1 else 0),
                 H6=float(((C.en_ventana(ta, gp, 3) or 0) >= 2)) - float(((C.en_ventana(th, gp, 3) or 0) >= 2)),
                 H7=float((C.en_ventana(ta, gp, 7) or 0) - (C.en_ventana(th, gp, 7) or 0)),
                 bh=bh, ba=ba, a3en4=(C.en_ventana(ta, gp, 3) or 0) >= 2,
                 a_ot=(pa["ot"] if pa else None), h_goleado=bool(ph and ph["ga"] - ph["gf"] >= 4),
                 c7=(C.en_ventana(ta, gp, 7) or 0) - (C.en_ventana(th, gp, 7) or 0))
        filas.append(r)
    filas.sort(key=lambda r: (r["fecha"], r["gp"]))
    return filas


def lg(p): p = np.clip(p, 1e-6, 1 - 1e-6); return np.log(p / (1 - p))


# ------------------------------------------------------------------ Super Learner
FAT = ["H1", "H2", "H4", "H6", "H7"]
FORMA = ["gd10", "sh10", "pdo10", "has_sh"]


def matriz(F, cols):
    return np.array([[r[c] for c in cols] for r in F], dtype=float)


def aprendices():
    def X_modelo(F): return lg(np.array([r["p"] for r in F]))[:, None]
    def X_elo(F): return np.array([[r["elo_d"]] for r in F])
    def X_fat(F): return np.hstack([X_modelo(F), matriz(F, FAT)])
    def X_forma(F): return np.hstack([X_modelo(F), matriz(F, FORMA)])
    def X_todo(F): return np.hstack([X_modelo(F), lg(np.array([r["p0"] for r in F]))[:, None], X_elo(F), matriz(F, FAT + FORMA)])
    lr = lambda C: make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000))
    return [("modelo", X_modelo, lambda: LogisticRegression(C=1e6, max_iter=2000)),
            ("elo", X_elo, lambda: lr(1e6)),
            ("modelo+fatiga", X_fat, lambda: lr(0.05)),
            ("modelo+tiros/PDO", X_forma, lambda: lr(0.05)),
            ("todo (ridge)", X_todo, lambda: lr(0.05)),
            ("gradient boosting", X_todo, lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                                                 l2_regularization=1.0, early_stopping=False, random_state=0))]


def ll(q, y): q = np.clip(q, 1e-9, 1 - 1e-9); return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def super_learner(tr, te):
    L = aprendices(); ytr = np.array([r["y"] for r in tr]); yte = np.array([r["y"] for r in te])
    k = 6; cortes = [int(len(tr) * i / k) for i in range(k + 1)]
    oof = np.full((len(tr), len(L)), np.nan)
    for j in range(1, k):
        a, b = cortes[j], cortes[j + 1]
        for m, (nom, fx, mk) in enumerate(L):
            mod = mk(); mod.fit(fx(tr[:a]), ytr[:a]); oof[a:b, m] = mod.predict_proba(fx(tr[a:b]))[:, 1]
    ok = ~np.isnan(oof).any(axis=1); P = oof[ok]; Y = ytr[ok]

    def obj(z):
        w = np.exp(z) / np.exp(z).sum(); return ll(P @ w, Y).mean()
    res = minimize(obj, np.zeros(len(L)), method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-9})
    w = np.exp(res.x) / np.exp(res.x).sum()
    oof_ll = {L[m][0]: float(ll(P[:, m], Y).mean()) for m in range(len(L))}
    Pte = np.zeros((len(te), len(L)))
    for m, (nom, fx, mk) in enumerate(L):
        mod = mk(); mod.fit(fx(tr), ytr); Pte[:, m] = mod.predict_proba(fx(te))[:, 1]
    return [n for n, _, _ in L], w, oof_ll, Pte, yte


def acierto(q, y, etiqueta):
    fav = np.where(q >= 0.5, 1, 0); conf = np.maximum(q, 1 - q); gano = (fav == y).astype(float)
    print("  %s: acierto del favorito %.1f%% (n %d)" % (etiqueta, 100 * gano.mean(), len(y)))
    out = []
    for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
        s = (conf >= lo) & (conf < hi)
        if s.sum():
            out.append({"tramo": "%d-%d%%" % (100 * lo, min(100, 100 * hi)), "n": int(s.sum()),
                        "prometido": round(100 * conf[s].mean(), 1), "real": round(100 * gano[s].mean(), 1)})
            print("     confianza %-8s n %5d  prometido %5.1f%%  real %5.1f%%" % (out[-1]["tramo"], out[-1]["n"], out[-1]["prometido"], out[-1]["real"]))
    return {"acierto": round(100 * gano.mean(), 2), "tramos": out}


# ------------------------------------------------------------------ TMLE
def tmle(F, A):
    Y = np.array([r["y"] for r in F], float); A = np.array(A, float)
    W = np.column_stack([lg(np.array([r["p0"] for r in F])), [r["elo_d"] / 100 for r in F], [r["gd10"] for r in F],
                         [r["sh10"] / 10 for r in F], [r["has_sh"] for r in F]])
    XQ = np.column_stack([A, W, A * W[:, 0]])
    q = LogisticRegression(C=1e6, max_iter=3000).fit(XQ, Y)
    def QA(a):
        Xa = np.column_stack([np.full(len(Y), a), W, a * W[:, 0]]); return q.predict_proba(Xa)[:, 1]
    Q1, Q0 = QA(1.0), QA(0.0); Qa = np.where(A == 1, Q1, Q0)
    g = LogisticRegression(C=1e6, max_iter=3000).fit(W, A).predict_proba(W)[:, 1]
    g = np.clip(g, 0.025, 0.975)
    Hc = A / g - (1 - A) / (1 - g); H1, H0 = 1 / g, -1 / (1 - g)
    off = lg(Qa); eps = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-(off + eps * Hc))); gr = np.sum(Hc * (Y - p)); hs = np.sum(Hc ** 2 * p * (1 - p))
        paso = gr / hs; eps += paso
        if abs(paso) < 1e-10: break
    Q1s = 1 / (1 + np.exp(-(lg(Q1) + eps * H1))); Q0s = 1 / (1 + np.exp(-(lg(Q0) + eps * H0)))
    Qas = np.where(A == 1, Q1s, Q0s)
    psi = float(np.mean(Q1s - Q0s))
    IC = Hc * (Y - Qas) + (Q1s - Q0s) - psi
    se = float(np.std(IC, ddof=1) / math.sqrt(len(Y)))
    crudo = float(Y[A == 1].mean() - Y[A == 0].mean())
    return psi, se, crudo, int(A.sum()), int(len(A) - A.sum())


# ------------------------------------------------------------------ main
def main():
    filas = construir()
    i70 = int(len(filas) * 0.7); tr, te = filas[:i70], filas[i70:]
    print("\nSISTEMA HIBRIDO NHL | %d partidos | explorar %d | prueba %d desde %s" % (len(filas), len(tr), len(te), te[0]["fecha"]))
    nombres, w, oof_ll, Pte, yte = super_learner(tr, te)
    print("\nSUPER LEARNER: pesos aprendidos (validacion hacia adelante en el 70 %)")
    for n, wi in zip(nombres, w):
        print("  %-20s peso %.3f   log-loss fuera de pliegue %.5f" % (n, wi, oof_ll[n]))
    qsl = Pte @ w; qm = Pte[:, 0]
    d = ll(qm, yte) - ll(qsl, yte); n = len(d); m = d.mean(); z = m / (d.std(ddof=1) / math.sqrt(n))
    h = n // 2; m1, m2 = d[:h].mean(), d[h:].mean(); cal = qsl.mean() - yte.mean()
    brier_m, brier_s = float(((qm - yte) ** 2).mean()), float(((qsl - yte) ** 2).mean())
    ver = "pasa" if (z >= 2 and m1 > 0 and m2 > 0 and abs(cal) <= 0.04) else "no pasa"
    print("\nPRUEBA (30 %%): log-loss modelo %.5f -> super learner %.5f | mejora %+.3f milesimas  z %+.2f  mitades %+.3f / %+.3f" % (
        ll(qm, yte).mean(), ll(qsl, yte).mean(), 1000 * m, z, 1000 * m1, 1000 * m2))
    print("  Brier modelo %.5f -> %.5f | calibracion %+.4f | VEREDICTO: %s" % (brier_m, brier_s, cal, ver.upper()))
    print("\nPROBABILIDAD DE ACIERTO EN LA PRUEBA (lado favorito, 2024-03 en adelante)")
    am = acierto(qm, yte, "modelo actual")
    asl = acierto(qsl, yte, "super learner")
    print("\nTMLE: efecto causal sobre la probabilidad de que gane el local (pp, IC 95 %), toda la muestra")
    exps = {
        "E1 visita en segunda noche (local descansado) vs nadie": (lambda r: (r["ba"] and not r["bh"]), lambda r: (not r["ba"] and not r["bh"])),
        "E2 local en segunda noche (visita descansada) vs nadie": (lambda r: (r["bh"] and not r["ba"]), lambda r: (not r["ba"] and not r["bh"])),
        "E3 visita en tercer juego en 4 noches": (lambda r: r["a3en4"], lambda r: not r["a3en4"]),
        "E4 visita viene de prorroga o shootout": (lambda r: r["a_ot"] is True, lambda r: r["a_ot"] is False),
        "E5 local perdio su ultimo juego por 4+": (lambda r: r["h_goleado"], lambda r: not r["h_goleado"]),
        "E6 visita con 2+ juegos mas en 7 dias": (lambda r: r["c7"] >= 2, lambda r: r["c7"] == 0),
    }
    tm = {}
    for nom, (fa, f0) in exps.items():
        S = [r for r in filas if fa(r) or f0(r)]; A = [1 if fa(r) else 0 for r in S]
        psi, se, crudo, n1, n0 = tmle(S, A)
        tm[nom] = {"efecto_pp": round(100 * psi, 2), "ic95": [round(100 * (psi - 1.96 * se), 2), round(100 * (psi + 1.96 * se), 2)],
                   "crudo_pp": round(100 * crudo, 2), "n_expuestos": n1, "n_control": n0}
        print("  %-56s %+5.1f pp  IC [%+5.1f, %+5.1f]  (crudo %+5.1f; expuestos %d)" % (
            nom, 100 * psi, 100 * (psi - 1.96 * se), 100 * (psi + 1.96 * se), 100 * crudo, n1))
    out = {"n": len(filas), "prueba_desde": te[0]["fecha"], "pesos": dict(zip(nombres, [round(float(x), 4) for x in w])),
           "oof_logloss": oof_ll, "prueba": {"mejora_milesimas": round(1000 * m, 3), "z": round(float(z), 2),
           "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)], "brier_modelo": round(brier_m, 5), "brier_sl": round(brier_s, 5),
           "calibracion": round(float(cal), 4), "veredicto": ver}, "acierto_modelo": am, "acierto_super_learner": asl, "tmle": tm}
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_hibrido_nhl_resultados.json")
    os.makedirs(M.SALIDA_MD, exist_ok=True)
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresultados en", ruta)


if __name__ == "__main__":
    main()
