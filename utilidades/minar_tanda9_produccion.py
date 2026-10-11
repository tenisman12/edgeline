# -*- coding: utf-8 -*-
"""
utilidades/minar_tanda9_produccion.py - tanda 9: TAUR (ausencias del rival -> puntos del equipo, NBA) sobre los puntos que
predice el modelo de produccion (modelos/nba.py reentrenado por bloques de 30 dias, como validar_mercados).
Por bloque: puntos reales ~ a + b * puntos del modelo (+ c * x) ajustado con los bloques anteriores (minimo 300 filas);
error cuadratico pareado, z, mitades y sesgo. Se prueba tambien x propia (TAUP) y las dos juntas.

    python utilidades/minar_tanda9_produccion.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import datetime as dt, json, math, os, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
from nucleo import io  # noqa: E402
import minar_tanda9 as T9  # noqa: E402
import minar_tanda8_produccion as P8  # noqa: E402
import minar_angulos_tanda7 as T7  # noqa: E402

BLOQUE = 30


def predicciones():
    from modelos import nba as N
    todos = N._juegos("NBA")
    G = []
    for f, gp, h, a in todos:
        gh, ga = T7._n(h.get("points")), T7._n(h.get("points_opp"))
        if gh is not None and ga is not None:
            G.append((str(f)[:10], str(gp), h.get("team"), a.get("team"), gh, ga))
    G.sort()
    orig = io.cargar_juegos
    d0 = dt.date.fromisoformat(G[0][0]); fin = dt.date.fromisoformat(G[-1][0]); b = 0; P = []
    while d0 <= fin:
        d1 = d0 + dt.timedelta(days=BLOQUE)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        if blk and len(prev) >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = N.entrenar("NBA")
            finally:
                io.cargar_juegos = orig
            for f, gp, th, ta, gh, ga in blk:
                r = N.predecir(est, th, ta, linea_total=220.5, linea_spread=0.0)
                if r:
                    P.append(dict(f=f, h=th, a=ta, gh=gh, ga=ga, ph=r["pts_home"], pa=r["pts_away"], b=b))
            b += 1
        d0 = d1
    return P


def prueba(F, cols, nombre):
    nb = max(r["b"] for r in F) + 1
    d, res = [], []
    for b in range(nb):
        prev = [r for r in F if r["b"] < b]; cur = [r for r in F if r["b"] == b]
        if len(prev) < 300 or not cur: continue
        Y = [r["T"] for r in prev]
        q0 = P8._ols([(1.0, r["pred"]) for r in prev], Y)
        q1 = P8._ols([(1.0, r["pred"]) + tuple(r[c] for c in cols) for r in prev], Y)
        for r in cur:
            t0 = q0[0] + q0[1] * r["pred"]
            t1 = sum(c * v for c, v in zip(q1, (1.0, r["pred"]) + tuple(r[c] for c in cols)))
            d.append((r["T"] - t0) ** 2 - (r["T"] - t1) ** 2); res.append(r["T"] - t1)
    sd_t = math.sqrt(sum((v - sum(res) / len(res)) ** 2 for v in res) / (len(res) - 1))
    out = P8.resumen(d, nombre, {"sesgo_desv": round(sum(res) / len(res) / sd_t, 3), "coef_ultimo": [round(x, 3) for x in q1]})
    print("  ", out)
    return out


def main():
    aus = T9.ausencias_nba()
    P = predicciones()
    F = []
    for r in P:
        mh, ma = aus.get((r["f"], r["h"], r["a"], True)), aus.get((r["f"], r["h"], r["a"], False))
        if mh is None or ma is None: continue
        F.append(dict(b=r["b"], T=r["gh"], pred=r["ph"], propia=mh / 48.0, rival=ma / 48.0))
        F.append(dict(b=r["b"], T=r["ga"], pred=r["pa"], propia=ma / 48.0, rival=mh / 48.0))
    print("NBA: %d predicciones, %d filas por equipo con ausencias" % (len(P), len(F)))
    out = [prueba(F, ("rival",), "TAUR sobre los puntos del modelo"), prueba(F, ("propia",), "TAUP sobre los puntos del modelo"),
           prueba(F, ("propia", "rival"), "TAUP + TAUR sobre los puntos del modelo")]
    json.dump({"generado": dt.datetime.now().isoformat(timespec="seconds"), "resultados": out},
              open(os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_tanda9_produccion.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
