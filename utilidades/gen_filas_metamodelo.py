# -*- coding: utf-8 -*-
"""utilidades/gen_filas_metamodelo.py - filas as-of por partido para el metamodelo (lo llama utilidades/metamodelo.py).

Futbol: modelo reentrenado por bloques de 30 dias solo con lo anterior (como minar_situacionales), con 1X2 y p_over 2.5,
cuotas tempranas y de cierre (Pinnacle, mejor del mercado, Bet365) y angulos F1, F13, S1, S4, S7.
NFL: prediccion as-of de minar_situacionales.correr_americano + angulos S1, S4, S7.
"""
import os, sys, time, csv, io as _io, datetime as dt
CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
import minar_situacionales as M
from nucleo import io
W = io.BASE

num = M._num


def rachas(C, e, gp, n_racha, ventana):
    """ultimos partidos con marcador, encadenados con <= ventana dias; devuelve lista [(gf,ga)] del mas reciente atras."""
    out = []; i = C.i(e, gp)
    if i is None: return out
    f = C.t[e][i]["fecha"]; j = i - 1
    while j >= 0 and len(out) < n_racha:
        g = C.t[e][j]
        if (f - g["fecha"]).days > ventana: break
        if g["gf"] is not None and g["ga"] is not None:
            out.append((g["gf"], g["ga"])); f = g["fecha"]
        j -= 1
    return out


def angulos_S(C, th, ta, gp, fc_n, mucho, sequia_max, ventana):
    h = rachas(C, th, gp, max(fc_n, 2), ventana); a = rachas(C, ta, gp, max(fc_n, 2), ventana)
    def frio(L): return len(L) >= fc_n and all(x[0] < x[1] for x in L[:fc_n])
    def cal(L): return len(L) >= fc_n and all(x[0] > x[1] for x in L[:fc_n])
    def paliza(L): return bool(L) and L[0][0] - L[0][1] >= mucho
    def seq(L): return len(L) >= 2 and all(x[0] <= sequia_max for x in L[:2])
    S4 = 1 if (frio(h) and cal(a)) else (-1 if (frio(a) and cal(h)) else 0)
    return dict(S1=int(paliza(h)) - int(paliza(a)), S4=S4, S7=int(seq(h)) - int(seq(a)))


def futbol(bloque=30):
    from modelos import futbol as FU
    C = M.Calendario()
    crudo = list(csv.DictReader(_io.open(os.path.join(W, "datos", "futbol.csv"), encoding="utf-8-sig")))
    for x in crudo:
        gf, gc = num(x.get("goals")), num(x.get("goals_opp"))
        if gf is None or gc is None: continue
        C.agregar(x["team"], x["game_date"], x["gamePk"], str(x.get("is_home")) in ("1", "1.0", "True"), gf, gc, x["opp"])
    eqs = {x["team"] for x in crudo}
    rc = os.path.join(W, "datos", "equipos", "espn_champions_equipos.csv")
    if os.path.exists(rc):
        for x in csv.DictReader(_io.open(rc, encoding="utf-8-sig")):
            if x["team"] in eqs:
                C.agregar(x["team"], x["game_date"], "ch" + str(x["game_id"]), str(x.get("is_home")) in ("1", "1.0"), None, None, x["opp"])
    C.cerrar()
    K = ["PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA", "MaxH", "MaxD", "MaxA", "MaxCH", "MaxCD", "MaxCA", "B365H", "B365D", "B365A",
         "P_mas2.5", "P_menos2.5", "PC_mas2.5", "PC_menos2.5", "Max_mas2.5", "Max_menos2.5", "MaxC_mas2.5", "MaxC_menos2.5",
         "B365_mas2.5", "B365_menos2.5", "AvgH", "AvgD", "AvgA"]
    CU = {}
    for x in csv.DictReader(_io.open(os.path.join(W, "datos", "mercado", "futbol_cuotas.csv"), encoding="utf-8-sig")):
        CU[str(x["gamePk"])] = {k: num(x.get("fd_" + k)) for k in K}
    filas = []; orig = io.cargar_juegos
    for liga in M.LIGAS_FUT:
        G = [(f, gp, h, a) for f, gp, h, a in FU._juegos(liga) if num(h.get("goals")) is not None and num(h.get("goals_opp")) is not None]
        if len(G) < 600: continue
        d0 = M._d(G[300][0]); ultimo = M._d(G[-1][0]); n0 = len(filas)
        while d0 <= ultimo:
            d1 = d0 + dt.timedelta(days=bloque)
            blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
            if blk:
                corte = d0.isoformat()
                io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
                try:
                    est = FU.entrenar(liga)
                finally:
                    io.cargar_juegos = orig
                for f, gp, h, a in blk:
                    th, ta = h.get("team"), a.get("team")
                    rr = FU.predecir(est, th, ta, linea_total=2.5, handicap=0.0)
                    if not rr: continue
                    gh, ga = num(h.get("goals")), num(h.get("goals_opp"))
                    rh, ra = C.descanso(th, gp), C.descanso(ta, gp)
                    ph, pa = C.prev(th, gp), C.prev(ta, gp)
                    def perdio3(g): return bool(g and g["gf"] is not None and g["ga"] - g["gf"] >= 3)
                    r = dict(fecha=f, gp=str(gp), liga=liga, home=th, away=ta, gh=gh, ga=ga,
                             p_h=rr["p_home"], p_d=rr["p_draw"], p_a=rr["p_away"], p_over=rr["p_over"],
                             F1=(max(-3, min(3, rh - ra)) / 3.0) if (rh is not None and ra is not None and rh <= 30 and ra <= 30) else 0.0,
                             F13=int(perdio3(ph)) - int(perdio3(pa)), cu=CU.get(str(gp)))
                    r.update(angulos_S(C, th, ta, gp, 2, 3, 0, 30))
                    filas.append(r)
            d0 = d1
        print("  %s: %d" % (liga, len(filas) - n0), flush=True)
    return filas


def nfl():
    M.correr_americano("NFL")
    filas, C = M.ULTIMO["NFL"]
    out = []
    for r in filas:
        r = dict(r); r.update(angulos_S(C, r["home"], r["away"], r["gp"], 2, 20, 13, 21)); out.append(r)
    return out

