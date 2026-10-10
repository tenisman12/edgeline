# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_tanda7.py - tanda 7 (hipotesis: trabajo/minar/2026-10-10_tanda7.md): suerte contra rendimiento.
Pitagoras, juegos cerrados, dominio de tiros/yardas, conversion neta (PDO, BABIP, triples, perdidas) y, en totales,
conversion y volumen en los juegos de los dos equipos. Mismas filas as-of y evaluadores de las tandas 4 y 5.
No toca modelos/ ni nucleo/.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_tanda7.py --cache trabajo/minar/tanda7_cache.pkl
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, bisect, csv, datetime as dt, io as _io, json, math, os, pickle, sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_angulos_tanda5 as T5  # noqa: E402

DEPS = ("NHL", "NBA", "NCAAMB", "NFL", "NCAAFB", "BEISBOL", "FUTBOL")
EXP = {"BEISBOL": 1.83, "NHL": 2.0, "NBA": 14.0, "NCAAMB": 11.5, "NFL": 2.37, "NCAAFB": 2.37, "FUTBOL": 1.3}
MIN = {"BEISBOL": 15, "NHL": 10, "NBA": 10, "NCAAMB": 10, "NFL": 4, "NCAAFB": 4, "FUTBOL": 8}
CORTO = {"BEISBOL": 1, "NHL": 1, "NBA": 3, "NCAAMB": 3, "NFL": 7, "NCAAFB": 7, "FUTBOL": 1}

NOMBRES = {"L1": ("Pitagoras (suerte en el record)", -1), "L2": ("record en juegos cerrados", -1),
           "L3": ("dominio de tiros o yardas", +1), "L4": ("conversion neta (PDO, BABIP, triples, perdidas)", -1)}
TOT = {"TL1": ("NHL: conversion en sus juegos", -1, ("NHL",)), "TL2": ("triples en sus juegos vs temporada", -1, ("NBA", "NCAAMB")),
       "TL3": ("BABIP en sus juegos", -1, ("BEISBOL",)), "TL4": ("futbol: goles por tiro a puerta", -1, ("FUTBOL",)),
       "TL5": ("NHL: volumen de tiros", +1, ("NHL",)), "TL6": ("futbol: volumen de tiros a puerta", +1, ("FUTBOL",)),
       "TL7": ("posesiones en sus juegos", +1, ("NBA", "NCAAMB"))}


def _n(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _leer(nombre):
    with _io.open(os.path.join(M.BASE, "datos", nombre), encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------ estadisticas por (juego, equipo)
def estadisticas():
    """S[dep][(gp, clave_equipo)] = dict con lo que usa cada angulo; G[dep_liga] = [(fecha, num, den)] por juego."""
    S = defaultdict(dict)
    for x in _leer("hockey.csv"):
        if x["league"] != "NHL": continue
        s, so, g, go = _n(x["shots"]), _n(x["shots_opp"]), _n(x["goals"]), _n(x["goals_opp"])
        if None in (s, so, g, go) or s <= 0 or so <= 0: continue
        S["NHL"][(str(x["gamePk"]), x["team"])] = dict(f=x["game_date"][:10], s=s, so=so, g=g, go=go, loc=x["is_home"])
    for x in _leer("nba.csv"):
        d = {k: _n(x.get("nba_" + k)) for k in ("fg3m", "fg3a", "fg3m_opp", "fg3a_opp", "fga", "fga_opp", "fta", "fta_opp",
                                                "tov", "tov_opp", "oreb", "oreb_opp")}
        if any(v is None for v in d.values()) or not d["fg3a"] or not d["fg3a_opp"]: continue
        d["pos"] = d["fga"] + 0.44 * d["fta"] + d["tov"] - d["oreb"] + d["fga_opp"] + 0.44 * d["fta_opp"] + d["tov_opp"] - d["oreb_opp"]
        d["f"] = x["game_date"][:10]; d["loc"] = x["is_home"]
        S[x["league"]][(str(x["gamePk"]), x["team"])] = d
    for x in _leer("americano.csv"):
        y, yo, t, to = _n(x["yards_total"]), _n(x["yards_total_opp"]), _n(x["turnovers"]), _n(x["turnovers_opp"])
        if None in (y, yo) or y + yo <= 0: continue
        S[x["league"]][(str(x["gamePk"]), x["team"])] = dict(f=x["game_date"][:10], y=y, yo=yo, t=t, to=to, loc=x["is_home"])
    for x in _leer("futbol.csv"):
        s, so, g, go = _n(x["shots_target"]), _n(x["shots_target_opp"]), _n(x["goals"]), _n(x["goals_opp"])
        if None in (s, so, g, go): continue
        S["FUTBOL"][(str(x["gamePk"]), x["team"])] = dict(f=x["game_date"][:10], s=s, so=so, g=g, go=go, loc=x["is_home"], liga=x["league"])
    for x in _leer("beisbol.csv"):
        b = [_n(x.get("bat_" + k)) for k in ("hits", "homeRuns", "atBats", "strikeOuts", "sacFlies")]
        p = [_n(x.get("pit_" + k)) for k in ("hits", "homeRuns", "atBats", "strikeOuts", "sacFlies")]
        if any(v is None for v in b + p): continue
        bn, bd = b[0] - b[1], b[2] - b[3] - b[1] + b[4]
        pn, pd = p[0] - p[1], p[2] - p[3] - p[1] + p[4]
        if bd <= 0 or pd <= 0: continue
        S["BEISBOL"][(str(x["gamePk"]), (x["league"], x["team"]))] = dict(f=x["game_date"][:10], bn=bn, bd=bd, pn=pn, pd=pd,
                                                                           loc=x["is_home"], liga=x["league"])
    return S


class Tasa:
    """tasa de la liga hasta el dia anterior: suma(num)/suma(den) de los juegos (contados una vez, fila local)."""

    def __init__(self):
        self.L = defaultdict(list); self.A = {}

    def add(self, lg, f, num, den): self.L[lg].append((f, num, den))

    def cerrar(self):
        for lg, L in self.L.items():
            L.sort(); fs = [f for f, _, _ in L]; cn, cd = [], []; sn = sd = 0.0
            for _, a, b in L: sn += a; sd += b; cn.append(sn); cd.append(sd)
            self.A[lg] = (fs, cn, cd)

    def __call__(self, lg, f):
        fs, cn, cd = self.A.get(lg, ([], [], []))
        k = bisect.bisect_left(fs, f)
        if k < 50 or cd[k - 1] <= 0: return None
        return cn[k - 1] / cd[k - 1]


def tasas(S):
    T = Tasa()
    es_local = lambda d: str(d.get("loc")) in ("1", "1.0", "True", "true")
    for (gp, e), d in S["NHL"].items():
        if es_local(d):
            T.add("NHL_conv", d["f"], d["g"] + d["go"], d["s"] + d["so"]); T.add("NHL_vol", d["f"], d["s"] + d["so"], 1.0)
    for lg in ("NBA", "NCAAMB"):
        for (gp, e), d in S[lg].items():
            if es_local(d): T.add(lg + "_pos", d["f"], d["pos"], 1.0)
    for (gp, e), d in S["FUTBOL"].items():
        if es_local(d):
            T.add(d["liga"] + "_conv", d["f"], d["g"] + d["go"], d["s"] + d["so"]); T.add(d["liga"] + "_vol", d["f"], d["s"] + d["so"], 1.0)
    for (gp, e), d in S["BEISBOL"].items():
        if es_local(d): T.add(d["liga"] + "_babip", d["f"], d["bn"] + d["pn"], d["bd"] + d["pd"])
    T.cerrar()
    return T


# ------------------------------------------------------------------ valores por equipo
def valores(dep, e, P, SD, T, fecha, liga):
    """P: juegos previos de la misma temporada, del mas reciente al mas viejo. Devuelve dict con L1..L4 y piezas de totales."""
    v = {}
    n = len(P)
    if n >= MIN[dep]:
        gf = sum(g["gf"] for g in P); ga = sum(g["ga"] for g in P)
        w = sum(1.0 if g["gf"] > g["ga"] else (0.5 if g["gf"] == g["ga"] else 0.0) for g in P) / n
        k = EXP[dep]
        if gf + ga > 0:
            v["L1"] = w - gf ** k / (gf ** k + ga ** k)
        c = CORTO[dep]
        cw = sum(1 for g in P if 0 < g["gf"] - g["ga"] <= c); cl = sum(1 for g in P if 0 < g["ga"] - g["gf"] <= c)
        v["L2"] = (cw - cl) / n
    st = lambda g: SD.get((g["gp"], e))
    if dep == "NHL":
        U = [d for d in (st(g) for g in P[:10]) if d]
        if len(U) >= 5:
            s, so, g_, go = (sum(d[k] for d in U) for k in ("s", "so", "g", "go"))
            v["L3"] = s / (s + so) - 0.5
            v["L4"] = g_ / s + 1 - go / so - 1
            lc, lv = T("NHL_conv", fecha), T("NHL_vol", fecha)
            if lc: v["TL1"] = (g_ + go) / (s + so) - lc
            if lv: v["TL5"] = (s + so) / len(U) / lv - 1
    elif dep in ("NBA", "NCAAMB"):
        U5 = [d for d in (st(g) for g in P[:5]) if d]; UA = [d for d in (st(g) for g in P) if d]
        if len(U5) >= 4 and len(UA) >= 10:
            def net(U): return sum(d["fg3m"] for d in U) / sum(d["fg3a"] for d in U) - sum(d["fg3m_opp"] for d in U) / sum(d["fg3a_opp"] for d in U)
            def tot(U): return (sum(d["fg3m"] + d["fg3m_opp"] for d in U)) / sum(d["fg3a"] + d["fg3a_opp"] for d in U)
            v["L4"] = net(U5) - net(UA)
            v["TL2"] = tot(U5) - tot(UA)
            lp = T(dep + "_pos", fecha)
            if lp: v["TL7"] = sum(d["pos"] for d in U5) / len(U5) / lp - 1
    elif dep in ("NFL", "NCAAFB"):
        U4 = [d for d in (st(g) for g in P[:4]) if d]
        if len(U4) >= 2:
            y, yo = sum(d["y"] for d in U4), sum(d["yo"] for d in U4)
            v["L3"] = y / (y + yo) - 0.5
        UA = [d for d in (st(g) for g in P) if d and d["t"] is not None and d["to"] is not None]
        if len(UA) >= 3:
            v["L4"] = sum(d["to"] - d["t"] for d in UA) / len(UA)
    elif dep == "FUTBOL":
        U = [d for d in (st(g) for g in P[:5]) if d]
        if len(U) >= 3:
            s, so, g_, go = (sum(d[k] for d in U) for k in ("s", "so", "g", "go"))
            if s + so > 0:
                v["L3"] = s / (s + so) - 0.5
            if s > 0 and so > 0:
                v["L4"] = g_ / s - go / so
            lc, lv = T(liga + "_conv", fecha), T(liga + "_vol", fecha)
            if lc and s + so > 0: v["TL4"] = (g_ + go) / (s + so) - lc
            if lv: v["TL6"] = (s + so) / len(U) / lv - 1
    elif dep == "BEISBOL":
        U = [d for d in (st(g) for g in P[:10]) if d]
        if len(U) >= 6:
            bn, bd, pn, pd = (sum(d[k] for d in U) for k in ("bn", "bd", "pn", "pd"))
            v["L4"] = bn / bd - pn / pd
            lb = T(liga + "_babip", fecha)
            if lb: v["TL3"] = (bn + pn) / (bd + pd) - lb
    return v


def construir(dep, filas, C, S, T, liga_fut):
    gap = T5.PARAM[dep]["gap"]; SD = S[dep] if dep not in ("NBA", "NCAAMB", "NFL", "NCAAFB") else S[dep]
    out = []
    for r in filas:
        h, a = r["home"], r["away"]
        Ph, Pa = T5.previos(C, h, r["gp"], gap), T5.previos(C, a, r["gp"], gap)
        if Ph is None or Pa is None: continue
        g0 = C.actual(h, r["gp"])
        fecha = g0["fecha"].isoformat() if g0 else str(r["fecha"])[:10]
        liga = (h[0] if isinstance(h, tuple) else (liga_fut.get(h) if dep == "FUTBOL" else dep))
        vh = valores(dep, h, Ph, SD, T, fecha, liga); va = valores(dep, a, Pa, SD, T, fecha, liga)
        x = dict(fecha=r["fecha"], gp=r["gp"], p=r["p"], y=r["y"], home=h, away=a, liga=r.get("liga") or dep, corte=r.get("corte"))
        for c in NOMBRES:
            x[c] = (vh[c] - va[c]) if (c in vh and c in va) else None
        for c in TOT:
            x[c] = (vh[c] + va[c]) if (c in vh and c in va) else None
        out.append(x)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    if a.cache and os.path.exists(a.cache):
        ULT = pickle.load(open(a.cache, "rb"))
    else:
        M.evaluar = lambda *x, **k: {"veredicto": "capturado"}
        M.correr_hockey(); M.correr_basquet("NBA"); M.correr_basquet("NCAAMB"); M.correr_americano("NFL"); M.correr_americano("NCAAFB")
        M.correr_beisbol(["MLB", "NPB", "KBO", "LMP", "LVBP", "LIDOM", "ABL"]); M.correr_futbol()
        M.evaluar = T4.EV_REAL
        ULT = dict(M.ULTIMO)
        if a.cache: pickle.dump(ULT, open(a.cache, "wb"))
    S = estadisticas(); T = tasas(S)
    liga_fut = {}
    for (gp, e), d in S["FUTBOL"].items(): liga_fut[e] = d["liga"]
    FILAS = {}
    for dep in DEPS:
        if dep not in ULT: continue
        filas, C = ULT[dep]
        FILAS[dep] = construir(dep, filas, C, S, T, liga_fut)
        cob = {c: sum(1 for r in FILAS[dep] if r.get(c) is not None) for c in list(NOMBRES) + list(TOT)}
        print("%s: %d partidos; con dato %s" % (dep, len(FILAS[dep]), {k: v for k, v in cob.items() if v}))
    R = {"ganador": [], "agrupado": [], "totales": [], "estimacion": []}
    print("\n" + "=" * 100 + "\nGANADOR POR DEPORTE")
    for cod, (nom, s) in NOMBRES.items():
        fuentes = []
        for dep, F in FILAS.items():
            rows = [dict(r, x=r[cod]) for r in F if r.get(cod) is not None]
            if len(rows) < 200: continue
            o = T4.evaluar_agrupado([rows], cod, nom, dep, s)
            if o: R["ganador"].append(o)
            R["estimacion"].append(dict(T5.describir(rows, dep), codigo=cod, angulo=nom))
            if dep == "BEISBOL":
                lmp = [r for r in rows if r["liga"] == "LMP"]
                if lmp: R["estimacion"].append(dict(T5.describir(lmp, "LMP"), codigo=cod, angulo=nom))
            fuentes.append(rows)
        if len(fuentes) > 1:
            # x en unidades distintas por deporte: se estandariza por deporte antes de juntar
            Z = []
            for rows in fuentes:
                sd = math.sqrt(sum(r["x"] ** 2 for r in rows) / len(rows)) or 1.0
                Z.append([dict(r, x=r["x"] / sd) for r in rows])
            o = T4.evaluar_agrupado(Z, cod, nom, "todos", s)
            if o: R["agrupado"].append(o)
            R["estimacion"].append(dict(T5.describir([r for f in Z for r in f], "todos (x en desv.)"), codigo=cod, angulo=nom))
    print("\n" + "=" * 100 + "\nTOTALES")
    for dep, F in FILAS.items():
        filas, C = ULT[dep]
        if dep == "BEISBOL":
            ld = lambda e: e[0] if isinstance(e, tuple) else "?"
        elif dep == "FUTBOL":
            ld = lambda e, le=liga_fut: le.get(e, "FUT")
        else:
            ld = lambda e, d=dep: d
        ET = T4.esperado_total(C, filas, ld)
        for cod, (nom, s, deps) in TOT.items():
            if dep not in deps: continue
            rows = []
            for r in F:
                et = ET.get(str(r["gp"]))
                if et and r.get(cod) is not None:
                    rows.append(dict(fecha=r["fecha"], gp=r["gp"], E=et[0], T=et[1], x=r[cod]))
            R["totales"].append(T4.evaluar_total(rows, cod, nom, dep, s))
            if dep == "BEISBOL":
                lmp = [dict(fecha=r["fecha"], gp=r["gp"], E=ET[str(r["gp"])][0], T=ET[str(r["gp"])][1], x=r[cod]) for r in F
                       if r["liga"] == "LMP" and str(r["gp"]) in ET and r.get(cod) is not None]
                if lmp: R["totales"].append(dict(T4.evaluar_total(lmp, cod, nom, "LMP", s), descriptivo=True))
    nuevas = [r for r in R["ganador"] + R["agrupado"] + R["totales"] if r and "z" in r and not r.get("descriptivo")]
    pasan = [r for r in nuevas if r.get("veredicto") == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d | falsos 'pasa' esperados ~ %.1f | pasan: %d" % (len(nuevas), 0.023 * len(nuevas), len(pasan)))
    for r in pasan:
        print("  PASA %s %s %s z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["z"]))
    print("\nESTIMACION (toda la muestra, pp para un partido de 50 % con x tipico; encogido)")
    for e in R["estimacion"]:
        if "pp_50" in e:
            print("  %-3s %-40s %-18s n %6d act %5d  %+5.1f pp [%+5.1f, %+5.1f]  encogido %+5.1f" % (
                e["codigo"], e["angulo"][:40], e["liga"][:18], e["n"], e["n_activos"], e["pp_50"], e["ic95_50"][0], e["ic95_50"][1],
                e["pp_50_encogido"]))
    out = dict(generado=dt.datetime.now().isoformat(timespec="seconds"), hipotesis="trabajo/minar/2026-10-10_tanda7.md",
               k=len(nuevas), falsos_esperados=round(0.023 * len(nuevas), 1), **R)
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_tanda7_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
