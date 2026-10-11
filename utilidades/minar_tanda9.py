# -*- coding: utf-8 -*-
"""
utilidades/minar_tanda9.py - tanda 9 (hipotesis: trabajo/minar/2026-10-10_tanda9.md): refinar ganador, totales y totales
por equipo. A) NHL equipos especiales, B) umpire de home en beisbol (LMP y el resto), C) NBA ausencias en totales,
E) predictor de ESPN (con --espn, cuando exista datos/equipos/espn_predictor.csv), F) estado de los pesos de totales.
Mismas filas as-of y evaluadores de las tandas 4, 5 y 7. No toca modelos/ ni nucleo/.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_tanda9.py --cache trabajo/minar/tanda7_cache.pkl [--espn]
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, bisect, csv, datetime as dt, io as _io, json, math, os, pickle, sys
from collections import Counter, defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_angulos_tanda5 as T5  # noqa: E402
import minar_angulos_tanda7 as T7  # noqa: E402

_n = T7._n
K_ARB = 20.0


def _lg(p): p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def esperado_equipo(C, filas, liga_de):
    """gp -> (E_local, E_visita, real_local, real_visita): como T4.esperado_total, por equipo."""
    hist = defaultdict(list)
    for e, L in C.t.items():
        for g in L:
            if g["local"] and g["gf"] is not None and g["ga"] is not None:
                hist[liga_de(e)].append((g["fecha"], g["gf"] + g["ga"]))
    acum = {}
    for lg, L in hist.items():
        L.sort(); fs = [f for f, _ in L]; cs = []; s = 0.0
        for _, t in L: s += t; cs.append(s)
        acum[lg] = (fs, cs)
    out = {}
    for r in filas:
        h, a, gp = r["home"], r["away"], r["gp"]
        gh = C.actual(h, gp)
        if not gh or gh["gf"] is None: continue
        fs, cs = acum.get(liga_de(h), ([], []))
        k = bisect.bisect_left(fs, gh["fecha"])
        if k < 50: continue
        m = cs[k - 1] / k / 2
        ih, ia = C.i(h, gp), C.i(a, gp)
        Lh = [g for g in C.t[h][:ih] if g["gf"] is not None]; La = [g for g in C.t[a][:ia] if g["gf"] is not None]
        if len(Lh) < 5 or len(La) < 5: continue
        out[str(gp)] = ((T4._ew(Lh, "gf", m) + T4._ew(La, "ga", m)) / 2, (T4._ew(La, "gf", m) + T4._ew(Lh, "ga", m)) / 2, gh["gf"], gh["ga"])
    return out


# ------------------------------------------------------------------ A. NHL equipos especiales
def parte_a(ULT, R):
    filas, C = ULT["NHL"]
    S = {}; tasa = T7.Tasa()
    for x in T7._leer("hockey.csv"):
        if x["league"] != "NHL": continue
        v = [_n(x.get(k)) for k in ("pp_goals", "pp_goals_opp", "pim", "pim_opp")]
        if any(q is None for q in v): continue
        S[(str(x["gamePk"]), x["team"])] = v
        if str(x.get("is_home")) in ("1", "1.0", "True"):
            tasa.add("pp", x["game_date"][:10], v[0] + v[1], 2.0)
    tasa.cerrar()
    EE = esperado_equipo(C, filas, lambda e: "NHL")
    ET = T4.esperado_total(C, filas, lambda e: "NHL")
    G, TT, TL, TV = [], [], [], []
    for r in filas:
        P = {}
        for lado in ("home", "away"):
            Pl = T5.previos(C, r[lado], r["gp"], 20)
            if Pl is None: P = None; break
            U = [S[(g["gp"], r[lado])] for g in Pl[:20] if (g["gp"], r[lado]) in S]
            if len(U) < 8: P = None; break
            ppg, ppa, pim, pimo = (sum(u[i] for u in U) for i in range(4))
            if pim <= 0 or pimo <= 0: P = None; break
            P[lado] = dict(pp=ppg / (pimo / 2), pk=ppa / (pim / 2), prov=pimo / 2 / len(U), com=pim / 2 / len(U))
        if not P: continue
        h, a = P["home"], P["away"]
        sth = (h["prov"] + a["com"]) / 2 * (h["pp"] + a["pk"]) / 2
        sta = (a["prov"] + h["com"]) / 2 * (a["pp"] + h["pk"]) / 2
        g0 = C.actual(r["home"], r["gp"])
        lg = tasa("pp", g0["fecha"].isoformat()) if g0 else None
        G.append(dict(fecha=r["fecha"], gp=r["gp"], p=r["p"], y=r["y"], x=sth - sta))
        gp = str(r["gp"])
        if lg and gp in ET:
            TT.append(dict(fecha=r["fecha"], gp=gp, E=ET[gp][0], T=ET[gp][1], x=sth + sta - 2 * lg))
        if lg and gp in EE:
            e = EE[gp]
            TL.append(dict(fecha=r["fecha"], gp=gp, E=e[0], T=e[2], x=sth - lg))
            TV.append(dict(fecha=r["fecha"], gp=gp, E=e[1], T=e[3], x=sta - lg))
    print("NHL equipos especiales: ganador %d, total %d, por equipo %d" % (len(G), len(TT), len(TL)))
    o = T4.evaluar_agrupado([G], "ST1", "equipos especiales (ganador)", "NHL", +1)
    if o: R["ganador"].append(o)
    R["estimacion"].append(dict(T5.describir(G, "NHL"), codigo="ST1", angulo="equipos especiales (ganador)"))
    R["totales"].append(T4.evaluar_total(TT, "TST", "equipos especiales (total)", "NHL", +1))
    R["totales"].append(T4.evaluar_total(TL, "TSTL", "equipos especiales (goles del local)", "NHL", +1))
    R["totales"].append(T4.evaluar_total(TV, "TSTV", "equipos especiales (goles de la visita)", "NHL", +1))


# ------------------------------------------------------------------ B. umpire
def parte_b(ULT, R):
    filas, C = ULT["BEISBOL"]
    ET = T4.esperado_total(C, filas, lambda e: e[0] if isinstance(e, tuple) else "?")
    ump = {}
    for x in T7._leer("beisbol.csv"):
        u = (x.get("umpire_home") or "").strip()
        if u and str(x.get("is_home")) in ("1", "1.0", "True"):
            ump[str(x["gamePk"])] = u
    F = sorted(filas, key=lambda r: (str(r["fecha"]), str(r["gp"])))
    hist = defaultdict(list); rows = defaultdict(list)
    for r in F:
        gp = str(r["gp"]); u = ump.get(gp); et = ET.get(gp)
        if not u or not et: continue
        lg = r["liga"]; L = hist[(lg, u)]
        x = (len(L) / (len(L) + K_ARB)) * (sum(L) / len(L)) if L else 0.0
        rows["LMP" if lg == "LMP" else "MLB+LVBP+LIDOM+ABL"].append(dict(fecha=r["fecha"], gp=gp, E=et[0], T=et[1], x=x))
        L.append(et[1] - et[0])
    for g, rr in rows.items():
        print("umpire %s: %d juegos" % (g, len(rr)))
        R["totales"].append(T4.evaluar_total(rr, "TU1", "umpire de home (total)", g, +1))


# ------------------------------------------------------------------ C. NBA ausencias en totales
def ausencias_nba():
    ruta = os.path.join(M.BASE, "datos", "equipos", "nba_ausencias.csv")
    loc_abr = defaultdict(set)
    for x in T7._leer("nba.csv"):
        if x.get("league") == "NBA" and str(x.get("is_home")) in ("1", "1.0", "True"):
            loc_abr[x["game_date"][:10]].add(x["team"])
    A = list(csv.DictReader(_io.open(ruta, encoding="utf-8-sig")))
    par = defaultdict(Counter)
    for x in A:
        if str(x.get("is_home")) in ("1", "1.0", "True"):
            for ab in loc_abr.get(x["game_date"][:10], ()): par[x["team"]][ab] += 1
    nombre = {full: c.most_common(1)[0][0] for full, c in par.items() if c}
    out = {}
    for x in A:
        ab, abo = nombre.get(x["team"]), nombre.get(x.get("opp"))
        if ab and abo:
            local = str(x.get("is_home")) in ("1", "1.0", "True")
            h, a = (ab, abo) if local else (abo, ab)
            out[(x["game_date"][:10], h, a, local)] = _n(x.get("min_ausentes"))
    return out


def parte_c(ULT, R):
    filas, C = ULT["NBA"]
    aus = ausencias_nba()
    ET = T4.esperado_total(C, filas, lambda e: "NBA")
    EE = esperado_equipo(C, filas, lambda e: "NBA")
    TT, TP, TR = [], [], []
    for r in filas:
        k = (str(r["fecha"])[:10], r["home"], r["away"])
        mh, ma = aus.get(k + (True,)), aus.get(k + (False,))
        if mh is None or ma is None: continue
        gp = str(r["gp"])
        if gp in ET:
            TT.append(dict(fecha=r["fecha"], gp=gp, E=ET[gp][0], T=ET[gp][1], x=(mh + ma) / 48.0))
        if gp in EE:
            e = EE[gp]
            for E_, T_, propia, rival in ((e[0], e[2], mh, ma), (e[1], e[3], ma, mh)):
                TP.append(dict(fecha=r["fecha"], gp=gp, E=E_, T=T_, x=propia / 48.0))
                TR.append(dict(fecha=r["fecha"], gp=gp, E=E_, T=T_, x=rival / 48.0))
    print("NBA ausencias: total %d, por equipo %d" % (len(TT), len(TP)))
    R["totales"].append(T4.evaluar_total(TT, "TAU", "ausencias de los dos (total)", "NBA", -1))
    R["totales"].append(T4.evaluar_total(TP, "TAUP", "ausencias propias (puntos del equipo)", "NBA", -1))
    R["totales"].append(T4.evaluar_total(TR, "TAUR", "ausencias del rival (puntos del equipo)", "NBA", +1))


# ------------------------------------------------------------------ E. predictor de ESPN
def parte_e(ULT, R):
    ruta = os.path.join(M.BASE, "datos", "equipos", "espn_predictor.csv")
    if not os.path.exists(ruta):
        print("E: sin datos/equipos/espn_predictor.csv"); R["espn"] = "sin dato"; return
    P = [x for x in csv.DictReader(_io.open(ruta, encoding="utf-8-sig")) if x.get("estado") == "ok"]
    pe = {}
    for x in P:
        ph, pa = _n(x.get("p_local")), _n(x.get("p_visita"))
        if ph is None and pa is None: continue
        if ph is None: ph = 100 - pa
        pe[(x["liga"], x["game_id"])] = min(max(ph / 100.0, 0.005), 0.995)
    print("E: %d proyecciones de ESPN" % len(pe))
    # ESPN id -> (fecha, local) desde datos/equipos/espn_<liga>_equipos.csv
    for liga, dep in (("nfl", "NFL"), ("ncaafb", "NCAAFB"), ("nba", "NBA"), ("ncaamb", "NCAAMB")):
        if dep not in ULT: continue
        filas, C = ULT[dep]
        # nombres de ESPN (completos) contra los del modelo (abreviaturas en NBA/NFL): el par que mas coincide como local
        loc_mod = defaultdict(set)
        for r in filas:
            loc_mod[str(r["fecha"])[:10]].add(r["home"])
        esp = [x for x in T7._leer(os.path.join("equipos", "espn_%s_equipos.csv" % liga)) if str(x.get("is_home")) in ("1", "1.0", "True")]
        par = defaultdict(Counter)
        for x in esp:
            for d in (0, -1, 1):
                f = (dt.date.fromisoformat(x["game_date"][:10]) + dt.timedelta(days=d)).isoformat()
                for t in loc_mod.get(f, ()):
                    par[x["team"]][t] += 3 if d == 0 else 1
        nombre = {k: c.most_common(1)[0][0] for k, c in par.items() if c}
        loc = {}
        for x in esp:
            t = nombre.get(x["team"])
            if t is None: continue
            for d in (0, -1, 1):          # la fecha de ESPN puede ir un dia adelante (hora UTC)
                f = (dt.date.fromisoformat(x["game_date"][:10]) + dt.timedelta(days=d)).isoformat()
                loc.setdefault((f, t), str(x["game_id"]))
        rows, rows_m = [], []
        for r in filas:
            gid = loc.get((str(r["fecha"])[:10], r["home"]))
            q = pe.get((liga, gid)) if gid else None
            if q is None: continue
            rows.append(dict(fecha=r["fecha"], gp=r["gp"], p=r["p"], y=r["y"], x=_lg(q) - _lg(r["p"]), q=q))
            if r.get("pm") is not None and 0 < r["pm"] < 1:
                rows_m.append(dict(fecha=r["fecha"], gp=r["gp"], p=r["pm"], y=r["y"], x=_lg(q) - _lg(r["pm"]), q=q))
        print("E %s: %d juegos casados con el modelo, %d con mercado" % (dep, len(rows), len(rows_m)))
        if len(rows) >= 300:
            o = T4.evaluar_agrupado([rows], "E2", "predictor ESPN sobre el modelo", dep, +1)
            if o: R["ganador"].append(o)
        if len(rows_m) >= 300:
            o = T4.evaluar_agrupado([rows_m], "E1", "predictor ESPN sobre el mercado", dep, +1, base="mercado")
            if o: R["mercado"].append(o)
            # E0: ESPN sola contra el mercado (fuga)
            d = [(-(r["y"] * math.log(r["q"]) + (1 - r["y"]) * math.log(1 - r["q"]))) -
                 (-(r["y"] * math.log(r["p"]) + (1 - r["y"]) * math.log(1 - r["p"]))) for r in rows_m]
            m = sum(d) / len(d); sd = math.sqrt(sum((v - m) ** 2 for v in d) / (len(d) - 1))
            z = -m / (sd / math.sqrt(len(d)))
            R["fuga"].append({"liga": dep, "n": len(d), "logloss_espn_menos_mercado_mil": round(1000 * m, 2), "z_espn_mejor": round(z, 2),
                              "sospecha_de_fuga": z >= 3})
            print("E0 %s: ESPN sola contra el mercado, log loss %+.2f milesimas (z ESPN mejor %+.2f)" % (dep, 1000 * m, z))


def parte_f(R):
    try:
        d = json.load(open(os.path.join(M.BASE, "salida", "pesos_dinamicos.json"), encoding="utf-8"))
        R["pesos_totales"] = {k: v for k, v in (d.get("pesos") or {}).items() if k.endswith("|Total")}
        for k, v in R["pesos_totales"].items():
            print("F %s: n %d, w_vivo %.2f, z %+.2f, w usado %s" % (k, v["n"], v["w_vivo"], v["z"], v.get("w_usado")))
    except Exception as e:
        R["pesos_totales"] = "sin dato (%s)" % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl"))
    ap.add_argument("--espn", action="store_true")
    a = ap.parse_args()
    ULT = pickle.load(open(a.cache, "rb"))
    R = {"ganador": [], "totales": [], "mercado": [], "estimacion": [], "fuga": []}
    if a.espn:
        print("=" * 100 + "\nE"); parte_e(ULT, R)
    else:
        print("=" * 100 + "\nA"); parte_a(ULT, R)
        print("=" * 100 + "\nB"); parte_b(ULT, R)
        print("=" * 100 + "\nC"); parte_c(ULT, R)
    print("=" * 100 + "\nF"); parte_f(R)
    nuevas = [r for r in R["ganador"] + R["totales"] + R["mercado"] if r and "z" in r]
    pasan = [r for r in nuevas if r.get("veredicto") == "pasa"]
    print("\nk = %d | falsos 'pasa' esperados ~ %.1f | pasan: %d" % (len(nuevas), 0.023 * len(nuevas), len(pasan)))
    for r in pasan:
        print("  PASA %s %s %s z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["z"]))
    out = dict(generado=dt.datetime.now().isoformat(timespec="seconds"), hipotesis="trabajo/minar/2026-10-10_tanda9.md",
               k=len(nuevas), falsos_esperados=round(0.023 * len(nuevas), 1), **R)
    nombre = "2026-10-10_tanda9_espn_resultados.json" if a.espn else "2026-10-10_tanda9_resultados.json"
    json.dump(out, open(os.path.join(CODIGO, "trabajo", "minar", nombre), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("resultados en trabajo/minar/" + nombre)


if __name__ == "__main__":
    main()
