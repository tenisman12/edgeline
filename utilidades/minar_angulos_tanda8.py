# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_tanda8.py - tanda 8, parte B (hipotesis: trabajo/minar/2026-10-10_tanda8.md): ponches contra
ponches (beisbol), bullpen y pitcheos del abridor (LMP/NPB), triples y choque de ritmos (NBA/NCAAMB), arbitro en goles y
tarjetas, movimiento de Pinnacle (futbol), numero clave y arbitro en totales (NFL). Mismas filas as-of y evaluadores de
las tandas 4, 5 y 7. No toca modelos/ ni nucleo/.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_tanda8.py --cache trabajo/minar/tanda7_cache.pkl
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io as _io, json, math, os, pickle, sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_angulos_tanda5 as T5  # noqa: E402
import minar_angulos_tanda7 as T7  # noqa: E402

_n = T7._n
K_ARB = 20.0


def _d(s): return dt.date.fromisoformat(str(s)[:10])
def _lg(p): p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _amer(o):
    o = _n(o)
    if o is None or o == 0: return None
    return 1 + (o / 100 if o > 0 else 100 / -o)


# ------------------------------------------------------------------ beisbol: ponches
def ponches():
    S = {}; T = T7.Tasa()
    for x in T7._leer("beisbol.csv"):
        bk, bpa, pk, pbf = (_n(x.get(k)) for k in ("bat_strikeOuts", "bat_plateAppearances", "pit_strikeOuts", "pit_battersFaced"))
        if None in (bk, bpa, pk, pbf) or bpa <= 0 or pbf <= 0: continue
        S[(str(x["gamePk"]), (x["league"], x["team"]))] = (bk, bpa, pk, pbf)
        T.add(x["league"] + "_k", x["game_date"][:10], bk, bpa)
    T.cerrar()
    return S, T


def bullpen():
    """LMP/NPB: outs de relevo por (liga, equipo, fecha) y pitcheos del abridor por (game_id, equipo) con su salida anterior."""
    relevo = defaultdict(float); abridor = {}; salidas = []
    for lg, nombre in (("LMP", "lmp_lanzadores.csv"), ("NPB", "npb_lanzadores.csv")):
        ruta = os.path.join(M.BASE, "datos", "abridores", nombre)
        if not os.path.exists(ruta): continue
        with _io.open(ruta, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                orden = _n(r.get("orden_salida")); outs = _n(r.get("outs"))
                if orden is None: continue
                f = r["game_date"][:10]
                if orden == 1:
                    pit = _n(r.get("pitches")) or _n(r.get("pit_numberOfPitches"))
                    abridor[(str(r["game_id"]), r["team"])] = r.get("player_id") or r.get("jugador")
                    salidas.append((r.get("player_id") or r.get("jugador"), f, str(r["game_id"]), r["team"], pit))
                elif outs is not None:
                    relevo[(lg, r["team"], f)] += outs
    salidas.sort(key=lambda s: (str(s[0]), s[1]))
    previa = {}; ult = {}
    for jug, f, gid, team, pit in salidas:
        u = ult.get(jug)
        if u is not None and (_d(f) - _d(u[0])).days <= 20 and u[1] is not None:
            previa[(gid, team)] = 1 if u[1] >= 105 else 0
        ult[jug] = (f, pit)
    return relevo, previa


def construir_beisbol(filas, C, SK, TK, relevo, previa):
    gap = T5.PARAM["BEISBOL"]["gap"]; out = []
    for r in filas:
        h, a = r["home"], r["away"]
        Ph, Pa = T5.previos(C, h, r["gp"], gap), T5.previos(C, a, r["gp"], gap)
        if Ph is None or Pa is None: continue
        g0 = C.actual(h, r["gp"]); f = g0["fecha"] if g0 else _d(r["fecha"])
        x = dict(fecha=r["fecha"], gp=r["gp"], p=r["p"], y=r["y"], home=h, away=a, liga=r.get("liga"), corte=r.get("corte"))
        v = {}
        for lado, e, P in (("h", h, Ph), ("a", a, Pa)):
            U = [SK.get((g["gp"], e)) for g in P[:15]]; U = [u for u in U if u]
            if len(U) >= 8:
                bk, bpa, pk, pbf = (sum(u[i] for u in U) for i in range(4))
                v[lado] = (bk / bpa, pk / pbf)
        x["R1"] = (v["h"][1] - v["h"][0]) - (v["a"][1] - v["a"][0]) if len(v) == 2 else None
        lk = TK(h[0] + "_k", f.isoformat())
        x["TR1"] = ((v["h"][0] + v["a"][1]) / 2 + (v["a"][0] + v["h"][1]) / 2 - 2 * lk) if (len(v) == 2 and lk) else None
        x["R2"] = x["TR2"] = x["R3"] = None
        if h[0] in ("LMP", "NPB"):
            def rel(e):
                return sum(relevo.get((e[0], e[1], (f - dt.timedelta(days=k)).isoformat()), 0.0) for k in (1, 2, 3))
            hay = any((h[0], h[1], (f - dt.timedelta(days=k)).isoformat()) in relevo for k in range(1, 30)) and \
                any((a[0], a[1], (f - dt.timedelta(days=k)).isoformat()) in relevo for k in range(1, 30))
            if hay:
                rh, ra = rel(h), rel(a)
                x["R2"] = (rh - ra) / 3.0      # en entradas
                x["TR2"] = (rh + ra) / 3.0
            ph, pa = previa.get((str(r["gp"]), h[1])), previa.get((str(r["gp"]), a[1]))
            if ph is not None and pa is not None: x["R3"] = ph - pa
        out.append(x)
    return out


# ------------------------------------------------------------------ basquet: triples y ritmos
def construir_basquet(dep, filas, C, S):
    TS = T7.Tasa()
    for (gp, e), d in S[dep].items():
        if str(d.get("loc")) in ("1", "1.0", "True", "true"):
            TS.add("3r", d["f"], d["fg3a"] + d["fg3a_opp"], d["fga"] + d["fga_opp"]); TS.add("pos", d["f"], d["pos"], 1.0)
    TS.cerrar()
    gap = T5.PARAM[dep]["gap"]; out = []
    for r in filas:
        h, a = r["home"], r["away"]
        Ph, Pa = T5.previos(C, h, r["gp"], gap), T5.previos(C, a, r["gp"], gap)
        if Ph is None or Pa is None: continue
        g0 = C.actual(h, r["gp"]); f = (g0["fecha"].isoformat() if g0 else str(r["fecha"])[:10])
        x = dict(fecha=r["fecha"], gp=r["gp"], TR3=None, TR4=None)
        U = {}
        for lado, e, P in (("h", h, Ph), ("a", a, Pa)):
            U[lado] = ([d for d in (S[dep].get((g["gp"], e)) for g in P[:10]) if d],
                       [d for d in (S[dep].get((g["gp"], e)) for g in P[:5]) if d])
        l3, lp = TS("3r", f), TS("pos", f)
        if l3 and len(U["h"][0]) >= 5 and len(U["a"][0]) >= 5:
            tasa = lambda L: sum(d["fg3a"] + d["fg3a_opp"] for d in L) / sum(d["fga"] + d["fga_opp"] for d in L)
            x["TR3"] = tasa(U["h"][0]) + tasa(U["a"][0]) - 2 * l3
        if lp and len(U["h"][1]) >= 4 and len(U["a"][1]) >= 4:
            pos = lambda L: sum(d["pos"] for d in L) / len(L)
            x["TR4"] = abs(pos(U["h"][1]) - pos(U["a"][1])) / lp
        out.append(x)
    return out


# ------------------------------------------------------------------ futbol: arbitro y movimiento
def futbol_mercado():
    Q = {}
    for x in T7._leer(os.path.join("mercado", "futbol_cuotas.csv")):
        Q[str(x["gamePk"])] = x
    return Q


def _tres(h, d, a):
    o = [_n(h), _n(d), _n(a)]
    if any(v is None or v <= 1 for v in o): return None
    s = sum(1 / v for v in o)
    return [(1 / v) / s for v in o]


def _dos(o, u):
    o, u = _n(o), _n(u)
    if not o or not u or o <= 1 or u <= 1: return None
    return (1 / o) / (1 / o + 1 / u)


def construir_futbol(filas, C, Q, ET, liga_fut):
    # tarjetas por equipo (calendario propio desde futbol.csv)
    tarj = {}; cal_t = defaultdict(list); por_liga = defaultdict(list)
    for x in T7._leer("futbol.csv"):
        y, yo, rr, ro = (_n(x.get(k)) for k in ("yellow", "yellow_opp", "red", "red_opp"))
        if None in (y, yo): continue
        cf = y + (rr or 0); ca = yo + (ro or 0)
        cal_t[x["team"]].append(dict(fecha=x["game_date"][:10], gp=str(x["gamePk"]), gf=cf, ga=ca))
        if str(x.get("is_home")) in ("1", "1.0", "True"):
            tarj[str(x["gamePk"])] = cf + ca; por_liga[x["league"]].append((x["game_date"][:10], cf + ca))
    for e in cal_t: cal_t[e].sort(key=lambda g: (g["fecha"], g["gp"]))
    pos_t = {(e, g["gp"]): i for e, L in cal_t.items() for i, g in enumerate(L)}
    for lg in por_liga: por_liga[lg].sort()
    # orden por fecha para el historial de arbitros
    F = sorted(filas, key=lambda r: (str(r["fecha"]), str(r["gp"])))
    hist_g = defaultdict(list); hist_t = defaultdict(list)
    out = []
    for r in F:
        gp = str(r["gp"]); q = Q.get(gp)
        x = dict(fecha=r["fecha"], gp=r["gp"], p=r.get("pm"), y=r["y"], liga=r.get("liga"), home=r["home"], away=r["away"])
        arb = (q.get("fd_Referee") or "").strip() if q else ""
        et = ET.get(gp)
        # TA1 goles
        x["TR5"] = None
        if arb and et:
            L = hist_g[arb]
            x["TR5"] = (len(L) / (len(L) + K_ARB)) * (sum(L) / len(L)) if L else 0.0
        # TA2 tarjetas: base con olvido de las tarjetas de los dos equipos
        x["TR6"] = None; x["E_t"] = None; x["T_t"] = tarj.get(gp)
        ih, ia = pos_t.get((r["home"], gp)), pos_t.get((r["away"], gp))
        if ih is not None and ia is not None and x["T_t"] is not None:
            Lh, La = cal_t[r["home"]][:ih], cal_t[r["away"]][:ia]
            f = cal_t[r["home"]][ih]["fecha"]
            prev = [t for fl, t in por_liga[liga_fut.get(r["home"], "")] if fl < f]
            if len(Lh) >= 5 and len(La) >= 5 and len(prev) >= 50:
                m = sum(prev[-400:]) / len(prev[-400:]) / 2
                x["E_t"] = (T4._ew(Lh, "gf", m) + T4._ew(La, "ga", m)) / 2 + (T4._ew(La, "gf", m) + T4._ew(Lh, "ga", m)) / 2
                if arb:
                    L = hist_t[arb]
                    x["TR6"] = (len(L) / (len(L) + K_ARB)) * (sum(L) / len(L)) if L else 0.0
        if arb and et: hist_g[arb].append(et[1] - et[0])
        if arb and x["E_t"] is not None: hist_t[arb].append(x["T_t"] - x["E_t"])
        # movimiento
        x["ML1"] = x["ML2"] = x["MLT"] = None; x["p_cierre"] = None; x["p_over"] = None; x["y_over"] = None
        if q:
            ab, ci = _tres(q.get("fd_PSH"), q.get("fd_PSD"), q.get("fd_PSA")), _tres(q.get("fd_PSCH"), q.get("fd_PSCD"), q.get("fd_PSCA"))
            av, avc = _tres(q.get("fd_AvgH"), q.get("fd_AvgD"), q.get("fd_AvgA")), _tres(q.get("fd_AvgCH"), q.get("fd_AvgCD"), q.get("fd_AvgCA"))
            if ab and ci:
                x["p_cierre"] = ci[0]; x["ML1"] = _lg(ci[0]) - _lg(ab[0])
                if av and avc: x["ML2"] = x["ML1"] - (_lg(avc[0]) - _lg(av[0]))
            oa, oc = _dos(q.get("fd_P_mas2.5"), q.get("fd_P_menos2.5")), _dos(q.get("fd_PC_mas2.5"), q.get("fd_PC_menos2.5"))
            if oa and oc and et:
                x["MLT"] = _lg(oc) - _lg(oa); x["p_over"] = oc; x["y_over"] = 1 if et[1] > 2.5 else 0
        out.append(x)
    return out


# ------------------------------------------------------------------ NFL
def nfl():
    R = [x for x in T7._leer(os.path.join("mercado", "nfl_lineas.csv")) if x.get("game_type") in ("REG", "WC", "DIV", "CON", "SB")]
    R.sort(key=lambda x: (x["gameday"], x["game_id"]))
    hist = defaultdict(list); KN, RN = [], []
    for x in R:
        hs, as_ = _n(x["home_score"]), _n(x["away_score"])
        if hs is None or as_ is None: continue
        sl, tl = _n(x["spread_line"]), _n(x["total_line"])
        res = hs - as_; tot = hs + as_
        # KN1
        oh, oa = _amer(x.get("home_spread_odds")), _amer(x.get("away_spread_odds"))
        if sl is not None and oh and oa and res != sl:
            p = (1 / oh) / (1 / oh + 1 / oa)
            k = 1 if sl in (-3.0, -7.0) else (-1 if sl in (3.0, 7.0) else 0)
            KN.append(dict(fecha=x["gameday"], gp=x["game_id"], p=p, y=1 if res > sl else 0, x=k))
        # RN1
        arb = (x.get("referee") or "").strip()
        oo, ou = _amer(x.get("over_odds")), _amer(x.get("under_odds"))
        if arb and tl is not None:
            L = hist[arb]
            xv = (len(L) / (len(L) + K_ARB)) * (sum(L) / len(L)) if L else 0.0
            if oo and ou and tot != tl:
                RN.append(dict(fecha=x["gameday"], gp=x["game_id"], p=(1 / oo) / (1 / oo + 1 / ou), y=1 if tot > tl else 0, x=xv))
            hist[arb].append(tot - tl)
    return KN, RN


# ------------------------------------------------------------------ main
GAN = {"R1": ("ventaja de ponches (pitcheo - bateo)", +1), "R2": ("bullpen cargado, outs de relevo 3 dias (entradas)", -1),
       "R3": ("abridor con 105+ pitcheos en su salida anterior", -1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl"))
    a = ap.parse_args()
    ULT = pickle.load(open(a.cache, "rb"))
    R = {"ganador": [], "totales": [], "mercado": [], "estimacion": []}

    def gan(rows, cod, nom, liga, s, base="modelo"):
        rows = [r for r in rows if r.get("x") is not None and r.get("p") is not None]
        if len(rows) < 200:
            print("  %s %s %s: muestra insuficiente (%d)" % (cod, nom, liga, len(rows))); return
        o = T4.evaluar_agrupado([rows], cod, nom, liga, s, base=base)
        if o: (R["mercado"] if base != "modelo" else R["ganador"]).append(o)
        R["estimacion"].append(dict(T5.describir(rows, liga), codigo=cod, angulo=nom, base=base))

    def tot(rows, cod, nom, liga, s):
        o = T4.evaluar_total(rows, cod, nom, liga, s)
        R["totales"].append(o)

    print("=" * 100 + "\nBEISBOL")
    filas, C = ULT["BEISBOL"]
    SK, TK = ponches(); relevo, previa = bullpen()
    FB = construir_beisbol(filas, C, SK, TK, relevo, previa)
    print("  filas %d; R1 %d, TR1 %d, R2 %d, R3 %d (activos %d)" % (len(FB), *(sum(1 for r in FB if r.get(c) is not None) for c in ("R1", "TR1", "R2", "R3")),
                                                                   sum(1 for r in FB if r.get("R3"))))
    for cod in ("R1", "R2", "R3"):
        nom, s = GAN[cod]
        rows = [dict(r, x=r[cod]) for r in FB if r.get(cod) is not None]
        gan(rows, cod, nom, "BEISBOL" if cod == "R1" else "LMP+NPB", s)
        lmp = [r for r in rows if r["liga"] == "LMP"]
        if lmp: R["estimacion"].append(dict(T5.describir(lmp, "LMP"), codigo=cod, angulo=nom))
    ld = lambda e: e[0] if isinstance(e, tuple) else "?"
    ET = T4.esperado_total(C, filas, ld)
    for cod, nom, s, filtro in (("TR1", "ponches esperados del juego", -1, None), ("TR2", "bullpen de los dos (entradas, 3 dias)", +1, None)):
        rows = [dict(fecha=r["fecha"], gp=r["gp"], E=ET[str(r["gp"])][0], T=ET[str(r["gp"])][1], x=r[cod], liga=r["liga"])
                for r in FB if r.get(cod) is not None and str(r["gp"]) in ET]
        tot(rows, cod, nom, "BEISBOL" if cod == "TR1" else "LMP+NPB", s)
        lmp = [r for r in rows if r["liga"] == "LMP"]
        if lmp: R["totales"].append(dict(T4.evaluar_total(lmp, cod, nom, "LMP", s), descriptivo=True))

    print("=" * 100 + "\nBASQUET")
    S = T7.estadisticas()
    for dep in ("NBA", "NCAAMB"):
        filas, C = ULT[dep]
        FK = construir_basquet(dep, filas, C, S)
        ET = T4.esperado_total(C, filas, lambda e, d=dep: d)
        for cod, nom, s in (("TR3", "tasa de triples de los dos", +1), ("TR4", "choque de ritmos", -1)):
            rows = [dict(fecha=r["fecha"], gp=r["gp"], E=ET[str(r["gp"])][0], T=ET[str(r["gp"])][1], x=r[cod])
                    for r in FK if r.get(cod) is not None and str(r["gp"]) in ET]
            tot(rows, cod, nom, dep, s)

    print("=" * 100 + "\nFUTBOL")
    filas, C = ULT["FUTBOL"]
    liga_fut = {}
    for r in filas: liga_fut[r["home"]] = r["liga"]; liga_fut[r["away"]] = r["liga"]
    ET = T4.esperado_total(C, filas, lambda e, le=liga_fut: le.get(e, "FUT"))
    FF = construir_futbol(filas, C, futbol_mercado(), ET, liga_fut)
    print("  filas %d; TR5 %d, TR6 %d, ML1 %d, ML2 %d, MLT %d" % (len(FF), *(sum(1 for r in FF if r.get(c) is not None) for c in ("TR5", "TR6", "ML1", "ML2", "MLT"))))
    tot([dict(fecha=r["fecha"], gp=r["gp"], E=ET[str(r["gp"])][0], T=ET[str(r["gp"])][1], x=r["TR5"]) for r in FF if r["TR5"] is not None],
        "TR5", "arbitro: goles", "FUTBOL", +1)
    tot([dict(fecha=r["fecha"], gp=r["gp"], E=r["E_t"], T=r["T_t"], x=r["TR6"]) for r in FF if r["TR6"] is not None],
        "TR6", "arbitro: tarjetas", "FUTBOL", +1)
    gan([dict(fecha=r["fecha"], gp=r["gp"], p=r["p_cierre"], y=r["y"], x=r["ML1"]) for r in FF if r["ML1"] is not None],
        "ML1", "movimiento de Pinnacle (1X2 local)", "FUTBOL", +1, base="cierre")
    gan([dict(fecha=r["fecha"], gp=r["gp"], p=r["p_cierre"], y=r["y"], x=r["ML2"]) for r in FF if r["ML2"] is not None],
        "ML2", "Pinnacle contra el promedio de casas", "FUTBOL", +1, base="cierre")
    gan([dict(fecha=r["fecha"], gp=r["gp"], p=r["p_over"], y=r["y_over"], x=r["MLT"]) for r in FF if r["MLT"] is not None],
        "MLT", "movimiento de Pinnacle (over 2.5)", "FUTBOL", +1, base="cierre")

    print("=" * 100 + "\nNFL")
    KN, RN = nfl()
    print("  KN1 %d (activos %d), RN1 %d" % (len(KN), sum(1 for r in KN if r["x"]), len(RN)))
    gan(KN, "KN1", "numero clave 3/7 con el perro", "NFL", +1, base="spread")
    gan(RN, "RN1", "arbitro en totales", "NFL", +1, base="total")

    nuevas = [r for r in R["ganador"] + R["totales"] + R["mercado"] if r and "z" in r and not r.get("descriptivo")]
    pasan = [r for r in nuevas if r.get("veredicto") == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d | falsos 'pasa' esperados ~ %.1f | pasan: %d" % (len(nuevas), 0.023 * len(nuevas), len(pasan)))
    for r in pasan:
        print("  PASA %s %s %s z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["z"]))
    print("\nESTIMACION (toda la muestra)")
    for e in R["estimacion"]:
        if "pp_50" in e:
            print("  %-4s %-45s %-8s n %6d act %5d  %+5.1f pp [%+5.1f, %+5.1f]  encogido %+5.1f" % (
                e["codigo"], e["angulo"][:45], e["liga"][:8], e["n"], e["n_activos"], e["pp_50"], e["ic95_50"][0], e["ic95_50"][1], e["pp_50_encogido"]))
    out = dict(generado=dt.datetime.now().isoformat(timespec="seconds"), hipotesis="trabajo/minar/2026-10-10_tanda8.md",
               k=len(nuevas), falsos_esperados=round(0.023 * len(nuevas), 1), **R)
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_tanda8_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
