# -*- coding: utf-8 -*-
"""
utilidades/minar_osciladores.py - mineria: los osciladores (forma, ataque, defensa, RSI, MACD, estocastico, impulso del
ELO, residuo pitagorico) explican lo que el modelo de ganador falla? NHL, MLB, KBO y NBA.
Hipotesis registrada en trabajo/minar/2026-10-06_osciladores.md.

Osciladores as-of por equipo (solo partidos anteriores, base de 40 juegos cruzando temporadas, como en produccion).
Walk-forward del modelo actual (bloques de 30 dias). Logistica regularizada con el logit del modelo como offset,
ajustada en el 70 % antiguo, probada en el 30 % reciente una vez. Escribe trabajo/minar/osciladores.json.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\minar_osciladores.py
"""
import json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, features as F, abridores as AB
from modelos import hockey, nba, beisbol as B

BASE_N = 40
PIT_EXP = {"nhl": 2.0, "mlb": 1.83, "kbo": 1.83, "nba": 14.0}
BASICOS = ["forma", "ataque", "defensa", "dif5"]
TECNICOS = ["rsi10", "macd_hist", "estoc", "elo_mom10", "res_pit"]


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def _lo(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-max(min(x, 35), -35)))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _ema(xs, n):
    k = 2 / (n + 1); e = xs[0]; out = []
    for x in xs:
        e = x * k + e * (1 - k); out.append(e)
    return out


def _rsi(d, n):
    w = d[-n:]; up = sum(x for x in w if x > 0); dn = -sum(x for x in w if x < 0)
    return 50.0 if up + dn == 0 else 100.0 * up / (up + dn)


def osciladores(js, elo_h, expo):
    """js: lista de (gf, ga) del equipo, mas viejo primero (solo partidos anteriores)."""
    if len(js) < 10:
        return None
    base = js[-BASE_N:]
    def v(L):
        n = len(L); w = sum(1 for a, b in L if a > b) / n
        return w, sum(a for a, _ in L) / n, sum(b for _, b in L) / n, sum(a - b for a, b in L) / n
    bw, bgf, bga, bdif = v(base); w10, gf10, ga10, _ = v(js[-10:]); _, _, _, d5 = v(js[-5:])
    difs = [a - b for a, b in base]
    macd = [a - b for a, b in zip(_ema(difs, 5), _ema(difs, 20))]; senal = _ema(macd, 9)
    h = elo_h[-14:]
    estoc = 100.0 * (h[-1] - min(h)) / (max(h) - min(h)) if len(h) >= 5 and max(h) > min(h) else 50.0
    mom = (elo_h[-1] - elo_h[-11]) if len(elo_h) >= 11 else 0.0
    gf, ga = sum(a for a, _ in base), sum(b for _, b in base)
    pit = gf ** expo / (gf ** expo + ga ** expo) if gf > 0 and ga > 0 else 0.5
    return {"forma": w10 - bw, "ataque": gf10 / bgf - 1 if bgf else 0.0, "defensa": ga10 / bga - 1 if bga else 0.0,
            "dif5": d5 - bdif, "rsi10": (_rsi(difs, 10) - 50) / 50, "macd_hist": macd[-1] - senal[-1],
            "estoc": (estoc - 50) / 50, "elo_mom10": mom / 25.0, "res_pit": bw - pit}


def construir_osc(G, expo):
    """G: lista ordenada de (fecha, id, home, away, gh, ga). Devuelve {id: dict de diferencias local - visita}."""
    hist, elo, eh, out = {}, {}, {}, {}
    for f, gid, th, ta, gh, ga in G:
        oh = osciladores(hist.get(th, []), eh.get(th, [1500.0]), expo)
        oa = osciladores(hist.get(ta, []), eh.get(ta, [1500.0]), expo)
        if oh and oa:
            out[gid] = {k: oh[k] - oa[k] for k in oh}
        eh_ = elo.get(th, 1500.0); ea_ = elo.get(ta, 1500.0)
        exp = 1 / (1 + 10 ** (-(eh_ + 30 - ea_) / 400)); res = 1.0 if gh > ga else 0.0
        elo[th] = eh_ + 8 * (res - exp); elo[ta] = ea_ - 8 * (res - exp)
        hist.setdefault(th, []).append((gh, ga)); hist.setdefault(ta, []).append((ga, gh))
        eh.setdefault(th, [1500.0]).append(elo[th]); eh.setdefault(ta, [1500.0]).append(elo[ta])
    return out


def filas_equipos(liga):
    """walk-forward del modelo de NHL (con GSAx) o NBA."""
    mod, lg_mod, cg, cgo = (hockey, None, "goals", "goals_opp") if liga == "nhl" else (nba, "NBA", "points", "points_opp")
    juegos = mod._juegos(lg_mod)
    G = [(f, gp, h, a) for f, gp, h, a in juegos if _f(h.get(cg)) is not None and _f(h.get(cgo)) is not None]
    osc = construir_osc([(f, str(gp), h["team"], a["team"], _f(h[cg]), _f(h[cgo])) for f, gp, h, a in G], PIT_EXP[liga])
    d0 = dt.date.fromisoformat(G[0][0]); ult = dt.date.fromisoformat(G[-1][0]); out = []; orig = io.cargar_juegos
    while d0 <= ult:
        d1 = d0 + dt.timedelta(days=30)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        if blk and len(prev) >= 600:
            c = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=c: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = mod.entrenar(lg_mod)
            finally:
                io.cargar_juegos = orig
            for f, gp, h, a in blk:
                o = osc.get(str(gp))
                if not o:
                    continue
                if liga == "nhl":
                    gh_, _ = hockey.rating_portero(h.get("starter_goalie"), f) if h.get("starter_goalie") else (None, 0)
                    ga_, _ = hockey.rating_portero(a.get("starter_goalie"), f) if a.get("starter_goalie") else (None, 0)
                    r = hockey.predecir(est, h["team"], a["team"], linea_total=6.5, gsax_home=gh_, gsax_away=ga_)
                else:
                    r = nba.predecir(est, h["team"], a["team"], linea_total=None, linea_spread=0.0)
                if r:
                    out.append({"f": f, "p": r["p_home"], "y": 1 if _f(h[cg]) > _f(h[cgo]) else 0, **o})
        d0 = d1
    return out


def filas_beisbol(liga):
    feats, _ = F.construir("beisbol", liga, 5)
    lg = io.norm(liga)
    G = sorted([r for r in feats if r["league"] == lg and r.get("y_home") is not None and r.get("marg_home") is not None],
               key=lambda r: r["game_date"])
    tot = lambda r: r["total"]
    osc = construir_osc([(r["game_date"][:10], r["gamePk"], r["home"], r["away"], (tot(r) + r["marg_home"]) / 2, (tot(r) - r["marg_home"]) / 2)
                         for r in G if r.get("total") is not None], PIT_EXP[lg])
    VAB = AB.historicos(io.BASE) if lg == "kbo" else {}
    d0 = dt.date.fromisoformat(G[0]["game_date"][:10]); ult = dt.date.fromisoformat(G[-1]["game_date"][:10]); out = []
    while d0 <= ult:
        d1 = d0 + dt.timedelta(days=30)
        blk = [r for r in G if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in G if r["game_date"][:10] < d0.isoformat()]
        if blk and len(prev) >= 500:
            m = B.entrenar_logistica(prev)
            if m:
                for r in blk:
                    o = osc.get(r["gamePk"])
                    if not o:
                        continue
                    p = B.prob(m, r)
                    if VAB:
                        vh, va = VAB.get((r["gamePk"], r["home"])), VAB.get((r["gamePk"], r["away"]))
                        if vh and va:
                            p = _sig(_lo(p) + AB.K_GANADOR * (AB.carreras_salvadas(r.get("df_home"), vh) - AB.carreras_salvadas(r.get("df_away"), va)))
                    out.append({"f": r["game_date"][:10], "p": p, "y": r["y_home"], **o})
        d0 = d1
    return out


def ajustar(E, cols, l2=5.0, iters=25):
    k = len(cols); b = [0.0] * k
    mu = [sum(x[c] for x in E) / len(E) for c in cols]
    sd = [math.sqrt(sum((x[c] - m) ** 2 for x in E) / len(E)) or 1.0 for c, m in zip(cols, mu)]
    X = [[(x[c] - m) / s for c, m, s in zip(cols, mu, sd)] for x in E]
    for _ in range(iters):
        g = [l2 * v for v in b]; H = [[l2 if i == j else 0.0 for j in range(k)] for i in range(k)]
        for xi, x in zip(X, E):
            p = _sig(_lo(x["p"]) + sum(bj * xj for bj, xj in zip(b, xi))); w = p * (1 - p)
            for i in range(k):
                g[i] += (p - x["y"]) * xi[i]
                for j in range(k): H[i][j] += w * xi[i] * xi[j]
        A = [row[:] + [gi] for row, gi in zip(H, g)]
        for i in range(k):
            pv = A[i][i] or 1e-9
            for j in range(i, k + 1): A[i][j] /= pv
            for r in range(k):
                if r != i:
                    fc = A[r][i]
                    for j in range(i, k + 1): A[r][j] -= fc * A[i][j]
        b = [bi - A[i][k] for i, bi in enumerate(b)]
    return b, mu, sd


def main():
    res = {"hipotesis": "trabajo/minar/2026-10-06_osciladores.md", "k_variantes": 3, "ligas": {}}
    for liga, fn in (("nhl", lambda: filas_equipos("nhl")), ("nba", lambda: filas_equipos("nba")),
                     ("mlb", lambda: filas_beisbol("MLB")), ("kbo", lambda: filas_beisbol("KBO"))):
        try:
            Fl = sorted(fn(), key=lambda x: x["f"])
        except Exception as e:
            print("%s: %s" % (liga, e)); continue
        c = int(len(Fl) * 0.7); E, T = Fl[:c], Fl[c:]; n = len(T); h = n // 2
        print("\n%s: %d partidos (ajuste hasta %s, prueba %d desde %s)" % (liga.upper(), len(Fl), E[-1]["f"], n, T[0]["f"]))
        out = {}
        for nom, cols in (("basicos", BASICOS), ("tecnicos", TECNICOS), ("todos", BASICOS + TECNICOS)):
            b, mu, sd = ajustar(E, cols)
            pm = [_sig(_lo(x["p"]) + sum(bi * (x[cc] - m) / s for bi, cc, m, s in zip(b, cols, mu, sd))) for x in T]
            d = [_ll(x["p"], x["y"]) - _ll(q, x["y"]) for q, x in zip(pm, T)]
            m_ = sum(d) / n; s_ = math.sqrt(sum((v - m_) ** 2 for v in d) / (n - 1)) or 1e-9
            z = m_ / (s_ / math.sqrt(n)); mit = [1000 * sum(d[:h]) / h, 1000 * sum(d[h:]) / (n - h)]
            cal = (sum(pm) / n, sum(x["y"] for x in T) / n)
            ok = n >= 300 and z >= 2.0 and min(mit) > 0 and abs(cal[0] - cal[1]) <= 0.04
            out[nom] = {"coef": {cc: round(bi, 4) for cc, bi in zip(cols, b)}, "mejora_milesimas": round(1000 * m_, 3), "z": round(z, 2),
                        "mitades": [round(v, 3) for v in mit], "calibracion": [round(cal[0], 4), round(cal[1], 4)], "veredicto": "pasa" if ok else "no pasa"}
            print("  %-9s mejora %+.2f milesimas (z %.2f, mitades %s) p %.3f real %.3f -> %s | coef %s" % (
                nom, 1000 * m_, z, [round(v, 2) for v in mit], cal[0], cal[1], out[nom]["veredicto"], out[nom]["coef"]))
        res["ligas"][liga] = out
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trabajo", "minar", "osciladores.json")
    json.dump(res, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
