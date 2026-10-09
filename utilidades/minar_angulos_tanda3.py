# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_tanda3.py - angulos situacionales que no se habian probado (tanda 3), todos los deportes.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_tanda3.md
Mismo evaluador que la tanda 1 (minar_situacionales.evaluar: 70/30, log-loss pareado, z >= 2.0, dos mitades,
calibracion <= 0.04, n activo >= 300) y TMLE descriptivo para los indicadores (como minar_cualitativos).
No toca modelos/ ni nucleo/.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_tanda3.py --deporte hockey,nba,nfl,ncaafb,beisbol,futbol,tenis
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io as _io, json, math, os, sys, zlib
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402

BASE = M.BASE
_ev_original = M.evaluar


def _silenciar():
    M.evaluar = lambda *a, **k: None


def _activar():
    M.evaluar = _ev_original


def _tmle_rows(rows):
    """TMLE del equipo en la situacion (x en -1/0/+1), igual que minar_cualitativos."""
    try:
        import minar_cualitativos as Q
    except Exception:
        return None
    ys, As, Ws = [], [], []
    for r in rows:
        x = r.get("x")
        if x is None or x not in (-1, 0, 1):
            return None
        if x == 0:
            lado = "H" if zlib.crc32(str(r["gp"]).encode()) % 2 == 0 else "A"; a = 0
        else:
            lado = "H" if x > 0 else "A"; a = 1
        gano = (r["y"] == 1) if lado == "H" else ((r.get("res") == "A") if "res" in r else (r["y"] == 0))
        p = r["p"] if lado == "H" else (r.get("paway") if r.get("paway") is not None else 1 - r["p"])
        p = min(max(p, 1e-4), 1 - 1e-4)
        ys.append(1.0 if gano else 0.0); As.append(a); Ws.append([math.log(p / (1 - p)), 1.0 if lado == "H" else 0.0])
    na = int(sum(As))
    if na < 50 or len(As) - na < 50:
        return None
    psi, se = Q.tmle(ys, As, Ws)
    return round(100 * psi, 2), [round(100 * (psi - 1.96 * se), 2), round(100 * (psi + 1.96 * se), 2)], na


def evaluar(filas, cod, nom, liga, signo, corte_por_liga=False, base_nombre="modelo", tmle=True):
    rows = [r for r in filas if r.get("x") is not None and r.get("p") is not None and r.get("y") is not None]
    if corte_por_liga:
        for r in rows: r["_te"] = r["fecha"] >= r["corte"]
        G = [dict(r, fecha=("1" if r["_te"] else "0") + r["fecha"]) for r in rows]
        out = M.evaluar(G, cod, nom, liga, signo, corte="1", base_nombre=base_nombre)
        if out and out.get("desde_prueba"): out["desde_prueba"] = out["desde_prueba"][1:]
    else:
        out = M.evaluar(rows, cod, nom, liga, signo, base_nombre=base_nombre)
    if tmle and out is not None and base_nombre == "modelo":
        t = _tmle_rows(rows)
        if t:
            out["tmle_pp"], out["tmle_ic95"], out["tmle_expuestos"] = t
            print("        TMLE %-4s %+5.1f pp  IC [%+5.1f, %+5.1f]  (expuestos %d)" % (cod, t[0], t[1][0], t[1][1], t[2]))
    return out


# ------------------------------------------------------------------ playoffs: estado de la serie
def series(ruta, liga, es_playoff):
    """gp -> (victorias_local_previas, victorias_visita_previas, local_perdio_el_anterior) en playoffs."""
    juegos = {}
    with _io.open(ruta, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if (r.get("league") or "").upper() != liga or str(r.get("is_home")) not in ("1", "1.0", "True"):
                continue
            if not es_playoff(r):
                continue
            pf = M._num(r.get("goals") if r.get("goals") not in (None, "") else r.get("points"))
            pa = M._num(r.get("goals_opp") if r.get("goals_opp") not in (None, "") else r.get("points_opp"))
            if pf is None or pa is None:
                continue
            juegos[str(r["gamePk"])] = (r["game_date"][:10], str(r.get("season")), r["team"], r["opp"], pf > pa)
    por = defaultdict(list)
    for gp, (f, s, h, a, gh) in juegos.items():
        por[(s, frozenset((h, a)))].append((f, gp, h, a, gh))
    out = {}
    for k, L in por.items():
        L.sort(); w = defaultdict(int); prev = None
        for f, gp, h, a, gh in L:
            out[gp] = (w[h], w[a], None if prev is None else (prev != h))   # prev = ganador del juego anterior
            ganador = h if gh else a
            w[ganador] += 1; prev = ganador
    return out


def playoffs(filas, S, liga):
    act = 0
    for r in filas:
        s = S.get(str(r["gp"]))
        r["P1"] = r["P2"] = r["P3"] = None
        if not s:
            continue
        act += 1
        wh, wa, home_perdio = s
        r["P1"] = 0 if home_perdio is None else (1 if home_perdio else -1)
        r["P3"] = 1 if (wh == 3 and wa == 3) else 0
        r["P2"] = 0 if r["P3"] else (1 if (wa == 3 and wh < 3) else (-1 if (wh == 3 and wa < 3) else 0))
    print("  partidos de playoffs con prediccion: %d" % act)
    for cod, nom, s in (("P1", "rebote en playoffs (perdio el anterior)", +1), ("P2", "al borde de la eliminacion", +1),
                        ("P3", "juego 7", +1)):
        evaluar([dict(r, x=r[cod]) for r in filas if r[cod] is not None], cod, nom, liga, s)


# ------------------------------------------------------------------ deportes
def hockey():
    _silenciar(); M.correr_hockey(); _activar()
    filas, C = M.ULTIMO["NHL"]
    for r in filas:
        r["H23"] = M._ind((C.en_ventana(r["away"], r["gp"], 5) or 0) >= 3) - M._ind((C.en_ventana(r["home"], r["gp"], 5) or 0) >= 3)
        alt = {"COL", "UTA"}
        r["H24"] = 1 if (r["home"] in alt and r["away"] not in alt) else 0
    print("\nNHL tanda 3")
    evaluar([dict(r, x=r["H23"]) for r in filas], "H23", "cuarto juego en 6 noches", "NHL", +1)
    evaluar([dict(r, x=r["H24"]) for r in filas], "H24", "altitud (Colorado, Utah)", "NHL", +1)
    S = series(os.path.join(BASE, "datos", "hockey.csv"), "NHL",
               lambda r: (r.get("tipo") == "POST") or (len(str(r.get("gamePk"))) == 10 and str(r["gamePk"])[4:6] == "03"))
    playoffs(filas, S, "NHL")


def basquet():
    _silenciar(); M.correr_basquet("NBA"); _activar()
    filas, C = M.ULTIMO["NBA"]
    aus = {}
    ruta = os.path.join(BASE, "datos", "equipos", "nba_ausencias.csv")
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig") as fh:
            for x in csv.DictReader(fh):
                aus[(str(x["game_id"]), x.get("team"))] = M._num(x.get("min_ausentes"))
    # nba_ausencias usa id de ESPN y nombre completo; el calendario usa otro id y abreviatura. Se casa por
    # (fecha, local): el nombre completo se traduce a abreviatura con el par que mas se repite como local en la misma fecha.
    aus_sede = {}
    if aus:
        from collections import Counter as _C
        loc_abr = defaultdict(set)
        with _io.open(os.path.join(BASE, "datos", "nba.csv"), encoding="utf-8-sig") as fh:
            for x in csv.DictReader(fh):
                if x.get("league") == "NBA" and str(x.get("is_home")) in ("1", "1.0", "True"):
                    loc_abr[x["game_date"][:10]].add(x["team"])
        filas_a = list(csv.DictReader(_io.open(ruta, encoding="utf-8-sig")))
        par = defaultdict(_C)
        for x in filas_a:
            if str(x.get("is_home")) in ("1", "1.0", "True"):
                for ab in loc_abr.get(x["game_date"][:10], ()):
                    par[x["team"]][ab] += 1
        nombre = {full: c.most_common(1)[0][0] for full, c in par.items() if c}
        for x in filas_a:
            ab = nombre.get(x["team"]); ab_o = nombre.get(x.get("opp"))
            if ab and ab_o:
                local = str(x.get("is_home")) in ("1", "1.0", "True")
                h, a = (ab, ab_o) if local else (ab_o, ab)
                aus_sede[(x["game_date"][:10], h, a, local)] = M._num(x.get("min_ausentes"))
    n_aus = 0
    for r in filas:
        r["K12"] = M._ind((C.en_ventana(r["away"], r["gp"], 5) or 0) >= 3) - M._ind((C.en_ventana(r["home"], r["gp"], 5) or 0) >= 3)
        alt = {"DEN", "UTA"}
        r["K13"] = 1 if (r["home"] in alt and r["away"] not in alt) else 0
        k_ = (r["fecha"][:10], r["home"], r["away"])
        mh, ma = aus_sede.get(k_ + (True,)), aus_sede.get(k_ + (False,))
        r["K14"] = None if (mh is None or ma is None) else (ma - mh) / 48.0
        n_aus += r["K14"] is not None
    print("\nNBA tanda 3 (partidos con ausencias: %d)" % n_aus)
    evaluar([dict(r, x=r["K12"]) for r in filas], "K12", "cuarto juego en 6 noches", "NBA", +1)
    evaluar([dict(r, x=r["K13"]) for r in filas], "K13", "altitud (Denver, Utah)", "NBA", +1)
    evaluar([dict(r, x=r["K14"]) for r in filas if r["K14"] is not None], "K14", "ausencias (minutos de los que faltan)", "NBA", +1, tmle=False)
    S = series(os.path.join(BASE, "datos", "nba.csv"), "NBA", lambda r: r.get("tipo") == "POST")
    playoffs(filas, S, "NBA")


PAC = {"SEA", "SF", "LA", "LAC", "LV"}
ESTE = {"ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND", "JAX", "MIA", "NE", "NYG", "NYJ", "PHI", "PIT", "TB", "WAS"}


def americano(liga):
    _silenciar(); M.correr_americano(liga); _activar()
    filas, C = M.ULTIMO[liga]
    lin = {}
    if liga == "NFL":
        with _io.open(os.path.join(BASE, "datos", "mercado", "nfl_lineas.csv"), encoding="utf-8-sig") as fh:
            for x in csv.DictReader(fh):
                lin[(x["gameday"][:10], M._ALIAS_NFL.get(x["home_team"], x["home_team"]), M._ALIAS_NFL.get(x["away_team"], x["away_team"]))] = x
    n_l = 0
    for r in filas:
        if liga == "NFL":
            x = lin.get((r["fecha"][:10], M._ALIAS_NFL.get(r["home"], r["home"]), M._ALIAS_NFL.get(r["away"], r["away"])))
            if not x:
                r["N14"] = r["N15"] = r["N16"] = r["N17"] = None; continue
            n_l += 1
            r["N14"] = 1 if x.get("weekday") == "Thursday" else 0
            h, a = M._ALIAS_NFL.get(r["home"], r["home"]), M._ALIAS_NFL.get(r["away"], r["away"])
            r["N15"] = 1 if (a in PAC and h in ESTE and (x.get("gametime") or "99:99") < "14:00" and x.get("location") != "Neutral") else 0
            r["N16"] = 1 if x.get("location") == "Neutral" else 0
            r["N17"] = (1 if r["p"] < 0.5 else -1) if x.get("div_game") == "1" else 0
        else:
            r["N14"] = 1 if M._d(r["fecha"]).weekday() == 3 else 0
    print("\n%s tanda 3 (con linea: %d)" % (liga, n_l))
    evaluar([dict(r, x=r.get("N14")) for r in filas], "N14", "jueves por la noche", liga, +1)
    if liga == "NFL":
        evaluar([dict(r, x=r.get("N15")) for r in filas], "N15", "costa oeste a la 1 pm en el este", liga, +1)
        evaluar([dict(r, x=r.get("N16")) for r in filas], "N16", "sede neutral", liga, -1)
        evaluar([dict(r, x=r.get("N17")) for r in filas], "N17", "perro divisional", liga, +1)
        con_m = [r for r in filas if r.get("pm") is not None]
        for cod, nom, s in (("N14", "jueves por la noche", +1), ("N15", "costa oeste a la 1 pm en el este", +1),
                            ("N16", "sede neutral", -1), ("N17", "perro divisional", +1)):
            evaluar([dict(r, x=r.get(cod), p=r["pm"]) for r in con_m], cod, nom, liga, s, base_nombre="cierre", tmle=False)


def beisbol():
    _silenciar(); M.correr_beisbol(["MLB", "NPB", "KBO", "LMP", "LVBP", "LIDOM", "ABL"]); _activar()
    filas, C = M.ULTIMO["BEISBOL"]
    mlb = [r for r in filas if r["liga"] == "MLB"]
    for r in mlb:
        r["B25"] = 1 if r["home"][1] == "Colorado Rockies" else 0
    print("\nBEISBOL tanda 3")
    evaluar([dict(r, x=r["B25"]) for r in mlb], "B25", "altitud (Coors Field)", "MLB", +1, corte_por_liga=True)


ALT_MX = {"Toluca", "Club America", "Cruz Azul", "UNAM Pumas", "Pachuca", "Puebla"}
DESCENSO = {"Premier", "LaLiga", "SerieA", "Bundesliga", "Ligue1"}


def _tabla_futbol():
    """(liga, temporada) -> {equipo: [(fecha, puntos_acumulados_despues, juegos)]} y numero de equipos."""
    juegos = defaultdict(list)
    with _io.open(os.path.join(BASE, "datos", "futbol.csv"), encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            gf, gc = M._num(x.get("goals")), M._num(x.get("goals_opp"))
            if gf is None or gc is None: continue
            juegos[(x["league"], str(x.get("season")), x["team"])].append((x["game_date"][:10], 3 if gf > gc else (1 if gf == gc else 0)))
    T = defaultdict(dict)
    for (lg, s, e), L in juegos.items():
        L.sort(); acc = 0; seq = []
        for i, (f, pts) in enumerate(L):
            acc += pts; seq.append((f, acc, i + 1))
        T[(lg, s)][e] = seq
    return T


def _pts_antes(seq, fecha):
    pts = 0; n = 0
    for f, acc, k in seq:
        if f < fecha: pts, n = acc, k
        else: break
    return pts, n


def futbol():
    _silenciar(); M.correr_futbol(); _activar()
    filas, C = M.ULTIMO["FUTBOL"]
    temporada = {}
    with _io.open(os.path.join(BASE, "datos", "futbol.csv"), encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            temporada[str(x["gamePk"])] = str(x.get("season"))
    T = _tabla_futbol()
    for r in filas:
        th, ta, gp = r["home"], r["away"], r["gp"]
        def ultimo_liga(e):
            i = C.i(e, gp)
            if i is None: return None
            for g in reversed(C.t[e][:i]):
                if g["gf"] is not None: return g
            return None
        def champions_reciente(e):
            i = C.i(e, gp)
            if i is None: return False
            f = C.t[e][i]["fecha"]
            return any(str(g["gp"]).startswith("ch") and 0 < (f - g["fecha"]).days <= 4 for g in C.t[e][max(0, i - 3):i])
        r["F14"] = (1 if (th in ALT_MX and ta not in ALT_MX) else 0) if r["liga"] == "LigaMX" else None
        uh, ua = ultimo_liga(th), ultimo_liga(ta)
        f0 = M._d(r["fecha"])
        if uh and ua:
            rh, ra = (f0 - uh["fecha"]).days, (f0 - ua["fecha"]).days
            fav = 1 if r["p"] >= (r.get("paway") or 0) else -1
            r["F15"] = fav if (rh >= 12 and ra >= 12 and rh <= 30 and ra <= 30) else 0
        else:
            r["F15"] = None
        r["F16"] = M._ind(champions_reciente(ta)) - M._ind(champions_reciente(th))
        r["F17"] = None
        if r["liga"] in DESCENSO:
            s = temporada.get(str(gp)); tab = T.get((r["liga"], s)) or {}
            n = len(tab)
            if n >= 16 and th in tab and ta in tab:
                tot = 2 * (n - 1)
                pts = {e: _pts_antes(seq, r["fecha"][:10]) for e, seq in tab.items()}
                orden = sorted(pts.values(), key=lambda v: -v[0])
                linea = orden[n - 4][0]                     # ultimo lugar fuera del descenso
                cuarto = orden[3][0]
                def amenazado(e): return pts[e][1] >= tot - 10 and pts[e][0] <= linea + 3
                def tranquilo(e): return pts[e][0] > linea + 8 and pts[e][0] < cuarto - 8
                r["F17"] = 1 if (amenazado(th) and tranquilo(ta)) else (-1 if (amenazado(ta) and tranquilo(th)) else 0)
    print("\nFUTBOL tanda 3")
    evaluar([dict(r, x=r["F14"]) for r in filas if r["F14"] is not None], "F14", "altitud en Liga MX", "LigaMX", +1)
    evaluar([dict(r, x=r["F15"]) for r in filas if r["F15"] is not None], "F15", "favorito tras fecha FIFA", "7 ligas", -1)
    evaluar([dict(r, x=r["F16"]) for r in filas], "F16", "Champions entre semana", "7 ligas", +1)
    evaluar([dict(r, x=r["F17"]) for r in filas if r["F17"] is not None], "F17", "pelea por no descender", "5 ligas", +1)
    con_m = [r for r in filas if r.get("pm")]
    for cod, nom, s, lg in (("F14", "altitud en Liga MX", +1, "LigaMX"), ("F15", "favorito tras fecha FIFA", -1, "7 ligas"),
                            ("F16", "Champions entre semana", +1, "7 ligas"), ("F17", "pelea por no descender", +1, "5 ligas")):
        evaluar([dict(r, x=r[cod], p=r["pm"]) for r in con_m if r[cod] is not None], cod, nom, lg, s, base_nombre="cierre", tmle=False)


RONDA = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "ER": 3.5, "R128": 4, "R64": 5, "R32": 6, "RR": 6.5, "R16": 7, "QF": 8, "SF": 9, "BR": 9.5, "F": 10}


def _sets(score):
    return sum(1 for t in str(score or "").split() if "-" in t and t[0].isdigit())


def tenis(min_j=10):
    from modelos import tenis as TE
    rows = list(csv.DictReader(_io.open(os.path.join(BASE, "datos", "tenis.csv"), encoding="utf-8-sig", errors="replace")))
    rows.sort(key=lambda r: (r.get("tourney_date", ""), r.get("tourney_id", ""), RONDA.get(r.get("round"), 5), int(M._num(r.get("match_num")) or 0)))
    J = {}
    def g(n): return J.setdefault(n, {"sp": 0., "spw": 0., "rp": 0., "rpw": 0., "elo": {}, "hist": []})
    tot_sp = tot_spw = 0.0; filas = []
    for r in rows:
        w, l = r.get("winner_name"), r.get("loser_name")
        sup = (r.get("surface") or "Hard").strip() or "Hard"
        bo = 5 if str(r.get("best_of")) == "5" else 3
        try:
            wsv = float(r["w_svpt"]); wsw = float(r["w_1stWon"]) + float(r["w_2ndWon"])
            lsv = float(r["l_svpt"]); lsw = float(r["l_1stWon"]) + float(r["l_2ndWon"])
        except (KeyError, ValueError, TypeError):
            continue
        if not w or not l or wsv <= 0 or lsv <= 0: continue
        td = r.get("tourney_date") or ""
        try:
            f = dt.date(int(td[:4]), int(td[4:6]), int(td[6:8]))
        except ValueError:
            continue
        jw, jl = g(w), g(l)
        ew = jw["elo"].get(sup, 1500.0); el = jl["elo"].get(sup, 1500.0)
        tour_spw = (tot_spw / tot_sp) if tot_sp else 0.635
        if jw["sp"] >= min_j * 50 and jl["sp"] >= min_j * 50:
            p1n, p2n = (w, l) if w < l else (l, w)
            j1, j2 = g(p1n), g(p2n)
            d1 = {"spw": j1["spw"] / j1["sp"], "rpw": j1["rpw"] / max(j1["rp"], 1)}
            d2 = {"spw": j2["spw"] / j2["sp"], "rpw": j2["rpw"] / max(j2["rp"], 1)}
            pr = TE.predecir(d1, d2, sup, bo, tour_spw, 22.5, j1["elo"].get(sup, 1500.0), j2["elo"].get(sup, 1500.0))
            fila = dict(fecha=f.isoformat(), gp=r["tourney_id"] + "-" + str(r.get("match_num")), p=pr["p1"], y=1 if p1n == w else 0,
                        liga=r.get("tour") or "ATP")
            def info(j):
                H = j["hist"]
                prev_t = next((m for m in reversed(H) if m["tid"] == r["tourney_id"]), None)
                load = sum(1 for m in H if m["tid"] == r["tourney_id"] or 0 < (f - m["fecha"]).days <= 14)
                prev = H[-1] if H else None
                cambio = None if prev is None or (f - prev["fecha"]).days > 60 else (prev["sup"] != sup and prev["tid"] != r["tourney_id"])
                gs = r.get("tourney_level") != "G" and any(m["nivel"] == "G" and 0 < (f - m["fecha"]).days <= 28 for m in H[-12:])
                return prev_t, load, cambio, gs
            a1, a2 = info(j1), info(j2)
            mins = lambda m: M._num(m["min"]) if m else None
            m1, m2 = mins(a1[0]), mins(a2[0])
            fila["T1"] = (m2 - m1) / 60.0 if (m1 and m2) else None
            fila["T2"] = (M._ind(a2[0]["distancia"]) - M._ind(a1[0]["distancia"])) if (a1[0] and a2[0]) else None
            fila["T3"] = (a2[1] - a1[1]) / 5.0
            fila["T4"] = (M._ind(a2[2]) - M._ind(a1[2])) if (a1[2] is not None and a2[2] is not None) else None
            fila["T5"] = M._ind(a2[3]) - M._ind(a1[3])
            filas.append(fila)
        jw["sp"] += wsv; jw["spw"] += wsw; jw["rp"] += lsv; jw["rpw"] += (lsv - lsw)
        jl["sp"] += lsv; jl["spw"] += lsw; jl["rp"] += wsv; jl["rpw"] += (wsv - wsw)
        exp = 1 / (1 + 10 ** (-(ew - el) / 400)); jw["elo"][sup] = ew + 24 * (1 - exp); jl["elo"][sup] = el - 24 * (1 - exp)
        tot_sp += wsv + lsv; tot_spw += wsw + lsw
        dist = _sets(r.get("score")) >= bo and "RET" not in str(r.get("score")) and "W/O" not in str(r.get("score"))
        for j in (jw, jl):
            j["hist"].append({"tid": r["tourney_id"], "fecha": f, "sup": sup, "min": r.get("minutes"), "distancia": dist,
                              "nivel": r.get("tourney_level")})
            if len(j["hist"]) > 40: j["hist"] = j["hist"][-40:]
    print("\nTENIS tanda 3: %d partidos con prediccion as-of" % len(filas))
    for tour in ("ATP", "WTA"):
        F = [x for x in filas if x["liga"] == tour]
        print("  %s: %d" % (tour, len(F)))
        evaluar([dict(x, x=x["T1"]) for x in F if x["T1"] is not None], "T1", "minutos del partido anterior", tour, +1, tmle=False)
        evaluar([dict(x, x=x["T2"]) for x in F if x["T2"] is not None], "T2", "partido anterior a la distancia", tour, +1)
        evaluar([dict(x, x=x["T3"]) for x in F], "T3", "carga de 14 dias", tour, +1, tmle=False)
        evaluar([dict(x, x=x["T4"]) for x in F if x["T4"] is not None], "T4", "cambio de superficie", tour, +1)
        evaluar([dict(x, x=x["T5"]) for x in F], "T5", "primer torneo tras un Grand Slam", tour, +1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", default="hockey,nba,nfl,ncaafb,beisbol,futbol,tenis")
    a = ap.parse_args()
    for d in [x.strip() for x in a.deporte.split(",") if x.strip()]:
        {"hockey": hockey, "nba": basquet, "nfl": lambda: americano("NFL"), "ncaafb": lambda: americano("NCAAFB"),
         "beisbol": beisbol, "futbol": futbol, "tenis": tenis}[d]()
    R = M.RESULTADOS
    k = sum(1 for r in R if "z" in r)
    pasan = [r for r in R if r["veredicto"] == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d pruebas con resultado | falsos 'pasa' esperados por azar ~ %.1f | pasan: %d" % (k, 0.023 * k, len(pasan)))
    for r in pasan:
        print("  PASA %-4s %-40s %-8s %-7s efecto %+.1f pp/u  z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["base"], r["efecto_pp_por_unidad"], r["z"]))
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_tanda3_resultados%s.json" % ("" if a.deporte.count(",") >= 6 else "_" + a.deporte.replace(",", "_")))
    json.dump(R, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
