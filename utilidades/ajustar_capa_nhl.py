# -*- coding: utf-8 -*-
"""
utilidades/ajustar_capa_nhl.py - grupo nhl_ganador de la capa bayesiana de angulos (27-nov-2026).

Los 29 angulos de hockey (H, Q, S; mismas definiciones que minar_angulos_bayes_hockey.py, x > 0 favorece al local) contra el
precio de mercado de ESPN (mediana sin vig de las casas, 2021-10 a hoy), con offset = mezcla de produccion
(logit p_mercado + 0.35 * (logit p_modelo - logit p_mercado)) y prior N(0, TAU) sobre cada angulo estandarizado.
Guarda los beta en escala de x en salida/capa_angulos.json -> grupos.nhl_ganador con "sombra": true (se calcula y se
registra en cada pick, NO mueve la probabilidad hasta que Alejandro lo apruebe).

Medicion (proyecto claude/capa-bayesiana-nhl-2026-11-27.md): walk-forward por temporada, mejora de log-loss positiva en todas
las temporadas (z +0.7 a +2.1); 30 % mas reciente contra la linea anticipada z +2.4, contra el cierre z +1.0.

    EDGELINE_BASE=. python utilidades/ajustar_capa_nhl.py
Necesita numpy, scipy y pandas.
"""
import io, json, os, sys
import numpy as np
import pandas as pd
from scipy.optimize import minimize

AQUI = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(AQUI)
sys.path.insert(0, REPO); sys.path.insert(0, AQUI)
os.environ.setdefault("EDGELINE_BASE", REPO)
TAU = 0.10
W_MODELO = 0.35
SALIDA = os.path.join(REPO, "salida", "capa_angulos.json")


def _lg(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _imp(a):
    a = np.asarray(a, float)
    return np.where(a < 0, -a / (-a + 100), 100 / (a + 100))


def mercado():
    c = pd.read_csv(os.path.join(REPO, "datos", "mercado", "espn_cuotas.csv"), low_memory=False)
    c = c[(c.liga == "nhl") & (c.estado == "ok") & (~c.casa.astype(str).str.contains("Live"))].dropna(subset=["ml_home", "ml_away"])
    c = c[(c.ml_home != 0) & (c.ml_away != 0)]
    c["pn"] = _imp(c.ml_home) / (_imp(c.ml_home) + _imp(c.ml_away))
    g = c.groupby("game_id").pn.median().rename("p_mkt").reset_index()
    e = pd.read_csv(os.path.join(REPO, "datos", "equipos", "espn_nhl_juegos.csv"))
    g = g.merge(e, on="game_id"); g["f"] = pd.to_datetime(g.game_date)
    return g


def main():
    import contextlib
    import minar_angulos_bayes_hockey as B
    B.LIGAS = ["NHL"]
    with contextlib.redirect_stdout(io.StringIO()):
        F = B.armar()
    ang = list(F[0]["x"].keys())
    df = pd.DataFrame([{**{k: v for k, v in r.items() if k != "x"}, **r["x"]} for r in F]); df["f"] = pd.to_datetime(df.fecha)
    g = mercado()
    from collections import Counter
    cnt = Counter()
    for d in (0, 1, -1):
        t = g.copy(); t["f"] = t.f + pd.Timedelta(days=d)
        m = df.merge(t, on="f")
        cnt.update(zip(m.home, m.local))
    M = {}
    for (a, b), _ in cnt.most_common():
        if a not in M and b not in M.values():
            M[a] = b
    df["local"] = df.home.map(M); df["visita"] = df.away.map(M)
    out = []
    for d in (0, 1, -1):
        t = g.copy(); t["f"] = t.f + pd.Timedelta(days=d)
        out.append(df.merge(t[["f", "local", "visita", "p_mkt", "game_id"]], on=["f", "local", "visita"]))
    J = pd.concat(out).drop_duplicates("gp").drop_duplicates("game_id").sort_values("f")
    y = J.y.values.astype(float)
    off = _lg(J.p_mkt.values) + W_MODELO * (_lg(J.p.values) - _lg(J.p_mkt.values))
    X = J[ang].values.astype(float); sd = X.std(0); sd[sd == 0] = 1; Xs = X / sd

    def fit(Xm, yy, oo):
        def f(b):
            eta = oo + Xm @ b; p = 1 / (1 + np.exp(-eta))
            return np.sum(np.logaddexp(0, eta) - yy * eta) + 0.5 * np.sum(b ** 2) / TAU ** 2, Xm.T @ (p - yy) + b / TAU ** 2
        return minimize(f, np.zeros(Xm.shape[1]), jac=True, method="L-BFGS-B").x

    def ll(yy, eta):
        return -(yy * eta - np.logaddexp(0, eta))
    n = len(y); c1 = int(n * 0.7)
    b = fit(Xs[:c1], y[:c1], off[:c1]); dlt = ll(y[c1:], off[c1:] + Xs[c1:] @ b) - ll(y[c1:], off[c1:])
    z = float(dlt.mean() / dlt.std() * np.sqrt(len(dlt)))
    bt = fit(Xs, y, off)
    grupo = {"liga": "nhl", "mercado": "Ganador", "favorece": "home", "n": int(n), "desde": str(J.f.iloc[0].date()), "hasta": str(J.f.iloc[-1].date()),
             "prueba": {"n": int(len(dlt)), "mejora_logloss_media": round(float(dlt.mean()), 6), "z": round(z, 2), "corte": str(J.f.iloc[c1].date())},
             "activo": False, "sombra": True, "x_desde": "salida/historial_angulos.csv", "base": "mezcla 35 % modelo / 65 % mercado",
             "angulos": [{"codigo": a, "descripcion": a, "prior_sd": round(TAU / s, 4), "beta": round(float(v / s), 4), "sd_post": None,
                          "pp_aprox_50": round(100 * (1 / (1 + np.exp(-v / s)) - 0.5), 2), "n_activo": int((J[a] != 0).sum())}
                         for a, v, s in zip(ang, bt, sd)]}
    try:
        with io.open(SALIDA, encoding="utf-8") as fh:
            res = json.load(fh)
    except Exception:
        res = {"grupos": {}}
    res.setdefault("grupos", {})["nhl_ganador"] = grupo
    with io.open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print("nhl_ganador: n %d, prueba n %d z %+.2f (sombra)" % (n, len(dlt), z))
    for a in sorted(grupo["angulos"], key=lambda t: -abs(t["beta"]))[:10]:
        print("   %-4s beta %+.3f  ~%+.1f pp  n %d" % (a["codigo"], a["beta"], a["pp_aprox_50"], a["n_activo"]))


if __name__ == "__main__":
    main()
