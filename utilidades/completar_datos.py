# -*- coding: utf-8 -*-
"""
utilidades/completar_datos.py - llena los huecos de datos\\<deporte>.csv con lo que ya esta en datos\\equipos\\.

Los archivos base (los que leen los modelos) traen poco en algunos deportes y los archivos de equipos traen mucho.
Este script cruza los dos y deja el mismo esquema para todas las ligas de un deporte. NUNCA pisa un dato que ya
existe: solo llena celdas vacias y agrega columnas nuevas. Lo que la fuente no tiene queda vacio (sin dato).

  hockey.csv     + tiros, hits, bloqueos, PIM, goles PP, giveaways, takeaways, como termino, portero abridor
                   (nhl_equipos.csv, cruce por gamePk + equipo)
  americano.csv  + yardas (total, pase neto, carrera), intentos, completos, primeros downs, perdidas, castigos,
                   sacks; NFL con EPA de pase y carrera (nfl_equipos.csv); NCAAF con 3a y 4a oportunidad y
                   tiempo de posesion (espn_ncaafb_equipos.csv)
  nba.csv        + box completo de NCAAMB (espn_ncaamb_equipos.csv); + juegos de PLAY-IN y PLAYOFFS de la NBA
                   que stats.nba no trae (espn_nba_equipos.csv); + puntos en la pintura, contraataque, tras
                   perdida y ventaja maxima en NBA y NCAAMB; columna tipo (REG / PLAYIN / POST)
  beisbol.csv    NPB y KBO: lo que batea un equipo = lo que permite el rival (23 parejas, 100 % en MLB);
                   totales de bases, outs, carreras y HR por 9, y AVG/OBP/SLG/OPS/ERA/WHIP acumulados de la temporada
                   (asi los guarda MLB). MLB y las ligas de invierno ya estan completas: no se toca nada.
  futbol.csv     + tiros, tiros a puerta, corners, faltas y tarjetas de Liga MX y MLS (ESPN, desde ago-2023);
                   + posesion, pases, centros, balones largos, fueras de lugar, atajadas, tiros bloqueados,
                   tacleadas, intercepciones, despejes y penales en las 7 ligas (ESPN, desde ago-2023)

Los nombres de equipo entre fuentes se emparejan con los mismos partidos: misma fecha (+-1 dia) y mismo
marcador; cada nombre se queda con el que mas veces coincide. No hay tabla escrita a mano.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\completar_datos.py              (solo muestra que haria y la cobertura)
    python utilidades\\completar_datos.py --aplicar    (escribe; respaldo en datos\\_respaldo\\)
    python utilidades\\completar_datos.py --cobertura  (solo la tabla de cobertura por liga y columna)

Escribe salida\\cobertura_datos.json (por archivo, liga y columna: % de filas con dato, primera y ultima fecha).
Solo stdlib. Idempotente: correrlo dos veces da lo mismo.
"""
import argparse, collections, csv, datetime as dt, json, os, re, shutil, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAT = os.path.join(BASE, "datos")
EQ = os.path.join(DAT, "equipos")
csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))


# ------------------------------------------------------------------ utilidades
def leer(ruta):
    if not os.path.exists(ruta):
        return [], []
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), list(rd)


def escribir(ruta, cols, filas):
    os.makedirs(os.path.join(DAT, "_respaldo"), exist_ok=True)
    if os.path.exists(ruta):
        shutil.copy2(ruta, os.path.join(DAT, "_respaldo", os.path.basename(ruta)))
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
        w.writeheader(); w.writerows(filas)
    os.replace(tmp, ruta)


def vacio(v):
    return v is None or str(v).strip() == ""


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fmt(x):
    if x is None:
        return ""
    return str(int(x)) if float(x).is_integer() else ("%.4f" % x).rstrip("0").rstrip(".")


def par(v, sep):
    """'25/41' -> (25, 41); '4-22' -> (4, 22)."""
    m = re.match(r"^\s*(\d+)\s*%s\s*(\d+)\s*$" % re.escape(sep), str(v or ""))
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def minutos(v):
    m = re.match(r"^\s*(\d+):(\d+)\s*$", str(v or ""))
    return round(int(m.group(1)) + int(m.group(2)) / 60.0, 2) if m else None


def gp(v):
    s = str(v or "")
    return s[:-2] if s.endswith(".0") else s


def dia(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def por_juego(filas, k_id="game_id"):
    """{game_id: {'1': fila_local, '0': fila_visita}}"""
    g = {}
    for r in filas:
        lado = str(r.get("is_home") or "").replace(".0", "")
        if lado in ("0", "1"):
            g.setdefault(gp(r.get(k_id)), {})[lado] = r
    return {k: v for k, v in g.items() if "0" in v and "1" in v}


def poner(fila, col, valor, cont):
    """Llena solo si la celda esta vacia. cont cuenta celdas llenadas."""
    if valor is None or valor == "":
        return
    if vacio(fila.get(col)):
        fila[col] = fmt(valor) if isinstance(valor, float) else valor
        cont[col] += 1


def agregar_cols(cols, nuevas):
    for c in nuevas:
        if c not in cols:
            cols.append(c)


def con_opp(base):
    out = []
    for c in base:
        out += [c, c + "_opp"]
    return out


# ------------------------------------------------------------------ emparejar nombres por partidos comunes
def mapa_nombres(base_juegos, otros_juegos, tol=1):
    """base_juegos / otros_juegos: lista de (fecha, local, visita, goles_local, goles_visita).
    Devuelve {nombre_otro: nombre_base} por mayoria de partidos con misma fecha (+-tol) y mismo marcador."""
    idx = collections.defaultdict(list)
    for f, h, a, gh, ga in base_juegos:
        idx[(f, gh, ga)].append((h, a))
    votos = collections.defaultdict(collections.Counter)
    for f, h, a, gh, ga in otros_juegos:
        for o in [0] + [d for k in range(1, tol + 1) for d in (-k, k)]:
            c = idx.get((f + dt.timedelta(days=o), gh, ga))
            if c and len(c) == 1:
                votos[h][c[0][0]] += 1; votos[a][c[0][1]] += 1
                break
    out = {}
    for n, c in votos.items():
        (top, k), = c.most_common(1)
        if k >= 3 and k >= 0.6 * sum(c.values()):
            out[n] = top
    return out


def juegos_base(filas, liga_col, liga, kp="points", kpo="points_opp"):
    out = []
    for r in filas:
        if r.get(liga_col) != liga or str(r.get("is_home")).replace(".0", "") != "1":
            continue
        f, a, b = dia(r.get("game_date")), num(r.get(kp)), num(r.get(kpo))
        if f and a is not None and b is not None:
            out.append((f, r["team"], r["opp"], int(a), int(b)))
    return out


def juegos_espn(g):
    out = []
    for gid, d in g.items():
        h, a = d["1"], d["0"]
        f, x, y = dia(h.get("game_date")), num(h.get("marcador")), num(a.get("marcador"))
        if f and x is not None and y is not None:
            out.append((f, h["team"], a["team"], int(x), int(y)))
    return out


def indice_espn(g, mapa, tol=1):
    """{(fecha, local_base, visita_base): {'1':..., '0':...}} con +-tol dias."""
    idx = {}
    for gid, d in g.items():
        h, a = mapa.get(d["1"]["team"]), mapa.get(d["0"]["team"])
        f = dia(d["1"].get("game_date"))
        if not (h and a and f):
            continue
        for o in range(-tol, tol + 1):
            idx.setdefault((f + dt.timedelta(days=o), h, a), (abs(o), gid, d))
            k = (f + dt.timedelta(days=o), h, a)
            if abs(o) < idx[k][0]:
                idx[k] = (abs(o), gid, d)
    return idx


# ------------------------------------------------------------------ HOCKEY
NHL_MAP = [("tiros", "shots"), ("hits", "hits"), ("bloqueos", "blocked"), ("pim", "pim"), ("pp_goles", "pp_goals"),
           ("giveaways", "giveaways"), ("takeaways", "takeaways"), ("portero_abridor", "starter_goalie")]
# porteros_usados no se copia: en nhl_equipos.csv siempre vale 2 (dato roto de la fuente)
NHL_COLS = con_opp([d for _, d in NHL_MAP]) + ["ended_in", "tipo"]


def hockey(log):
    ruta = os.path.join(DAT, "hockey.csv")
    cols, filas = leer(ruta)
    _, eq = leer(os.path.join(EQ, "nhl_equipos.csv"))
    if not filas or not eq:
        log.append("hockey: falta hockey.csv o nhl_equipos.csv"); return None
    g = por_juego(eq)
    cont = collections.Counter(); hit = 0
    for r in filas:
        d = g.get(gp(r.get("gamePk")))
        if not d:
            continue
        lado = str(r.get("is_home")).replace(".0", "")
        yo, el = d.get(lado), d.get("0" if lado == "1" else "1")
        if not yo or not el:
            continue
        hit += 1
        for s, t in NHL_MAP:
            v = yo.get(s)
            poner(r, t, v if s == "portero_abridor" else num(v), cont)
            poner(r, t + "_opp", el.get(s) if s in ("portero_abridor",) else num(el.get(s)), cont)
        poner(r, "ended_in", yo.get("fin_en"), cont)
        poner(r, "tipo", yo.get("tipo"), cont)
    agregar_cols(cols, NHL_COLS)
    log.append("hockey: %d de %d filas cruzadas con nhl_equipos; %d celdas llenadas" % (hit, len(filas), sum(cont.values())))
    return ruta, cols, filas


# ------------------------------------------------------------------ AMERICANO
AM_COLS = con_opp(["yards_total", "yards_pass", "yards_rush", "pass_att", "pass_cmp", "rush_att", "first_downs",
                   "turnovers", "int_thrown", "fumbles_lost", "sacks_taken", "penalties", "penalty_yards",
                   "third_conv", "third_att", "fourth_conv", "fourth_att", "redzone_conv", "redzone_att",
                   "possession_min", "epa_pass", "epa_rush"]) + ["tipo"]


def _nfl_stats(r):
    py, sy, ry = num(r.get("passing_yards")), num(r.get("sack_yards_lost")), num(r.get("rushing_yards"))
    neto = None if py is None else py - abs(sy or 0.0)
    fd = [num(r.get(k)) for k in ("passing_first_downs", "rushing_first_downs")]
    it, fl = num(r.get("passing_interceptions")), num(r.get("fumbles_lost_total"))
    return {"yards_total": None if neto is None or ry is None else neto + ry, "yards_pass": neto, "yards_rush": ry,
            "pass_att": num(r.get("attempts")), "pass_cmp": num(r.get("completions")), "rush_att": num(r.get("carries")),
            "first_downs": None if None in fd else sum(fd), "turnovers": None if it is None or fl is None else it + fl,
            "int_thrown": it, "fumbles_lost": fl, "sacks_taken": num(r.get("sacks_suffered")),
            "penalties": num(r.get("penalties")), "penalty_yards": num(r.get("penalty_yards")),
            "epa_pass": num(r.get("passing_epa")), "epa_rush": num(r.get("rushing_epa"))}


def _ncaaf_stats(r):
    c, a = par(r.get("completionAttempts"), "/")
    pe, py = par(r.get("totalPenaltiesYards"), "-")
    t3, a3 = par(r.get("thirdDownEff"), "-")
    t4, a4 = par(r.get("fourthDownEff"), "-")
    rz, ra = par(r.get("redZoneAttempts"), "-")
    sk, _ = par(r.get("sacksYardsLost"), "-")
    return {"redzone_conv": rz, "redzone_att": ra, "sacks_taken": sk,"yards_total": num(r.get("totalYards")), "yards_pass": num(r.get("netPassingYards")),
            "yards_rush": num(r.get("rushingYards")), "pass_att": a, "pass_cmp": c, "rush_att": num(r.get("rushingAttempts")),
            "first_downs": num(r.get("firstDowns")), "turnovers": num(r.get("turnovers")),
            "int_thrown": num(r.get("interceptions")), "fumbles_lost": num(r.get("fumblesLost")),
            "penalties": pe, "penalty_yards": py, "third_conv": t3, "third_att": a3, "fourth_conv": t4, "fourth_att": a4,
            "possession_min": minutos(r.get("possessionTime"))}


def americano(log):
    ruta = os.path.join(DAT, "americano.csv")
    cols, filas = leer(ruta)
    _, nfl = leer(os.path.join(EQ, "nfl_equipos.csv"))
    _, ncf = leer(os.path.join(EQ, "espn_ncaafb_equipos.csv"))
    if not filas:
        log.append("americano: falta americano.csv"); return None
    # NFL: nflverse no trae is_home; se usa el equipo
    nfl_i = {(gp(r.get("game_id")), r.get("team")): r for r in nfl}
    ncf_g = por_juego(ncf)
    # NFL desde ESPN (si ya se bajo): 3a y 4a oportunidad, zona roja y posesion, que nflverse no trae
    _, nfe = leer(os.path.join(EQ, "espn_nfl_equipos.csv"))
    nfe_g = por_juego(nfe)
    nfe_idx = indice_espn(nfe_g, mapa_nombres(juegos_base(filas, "league", "NFL"), juegos_espn(nfe_g), tol=1), tol=1) if nfe_g else {}
    cont = collections.Counter(); h_nfl = h_ncf = h_nfe = 0
    for r in filas:
        lg = r.get("league")
        if lg == "NFL":
            yo, el = nfl_i.get((gp(r["gamePk"]), r["team"])), nfl_i.get((gp(r["gamePk"]), r["opp"]))
            if not yo or not el:
                continue
            h_nfl += 1; sy, so = _nfl_stats(yo), _nfl_stats(el)
            poner(r, "tipo", {"REG": "REG", "POST": "POST"}.get(yo.get("season_type"), yo.get("season_type")), cont)
            lado = str(r.get("is_home")).replace(".0", "")
            hh, aa = (r["team"], r["opp"]) if lado == "1" else (r["opp"], r["team"])
            x = nfe_idx.get((dia(r.get("game_date")), hh, aa))
            if x and num(x[2][lado].get("marcador")) == num(r.get("points")):
                h_nfe += 1
                ey, eo = _ncaaf_stats(x[2][lado]), _ncaaf_stats(x[2]["0" if lado == "1" else "1"])
                for k, v in ey.items():          # nflverse manda; ESPN solo llena lo que nflverse no trae
                    if sy.get(k) is None:
                        sy[k] = v
                for k, v in eo.items():
                    if so.get(k) is None:
                        so[k] = v
        elif lg == "NCAAFB":
            d = ncf_g.get(gp(r["gamePk"]).replace("espn_", ""))
            if not d:
                continue
            lado = str(r.get("is_home")).replace(".0", "")
            yo, el = d.get(lado), d.get("0" if lado == "1" else "1")
            if not yo or not el or yo.get("team") != r.get("team"):
                continue
            h_ncf += 1; sy, so = _ncaaf_stats(yo), _ncaaf_stats(el)
            poner(r, "tipo", yo.get("tipo"), cont)
        else:
            continue
        for k, v in sy.items():
            poner(r, k, v, cont)
        for k, v in so.items():
            poner(r, k + "_opp", v, cont)
    agregar_cols(cols, AM_COLS)
    n_nfl = sum(1 for r in filas if r.get("league") == "NFL"); n_ncf = sum(1 for r in filas if r.get("league") == "NCAAFB")
    log.append("americano: NFL %d de %d filas (con ESPN %d), NCAAF %d de %d; %d celdas llenadas" % (
        h_nfl, n_nfl, h_nfe, h_ncf, n_ncf, sum(cont.values())))
    return ruta, cols, filas


# ------------------------------------------------------------------ NBA / NCAAMB
BOX = [("fieldGoalsMade", "nba_fgm"), ("fieldGoalsAttempted", "nba_fga"), ("threePointFieldGoalsMade", "nba_fg3m"),
       ("threePointFieldGoalsAttempted", "nba_fg3a"), ("freeThrowsMade", "nba_ftm"), ("freeThrowsAttempted", "nba_fta"),
       ("offensiveRebounds", "nba_oreb"), ("defensiveRebounds", "nba_dreb"), ("totalRebounds", "nba_reb"),
       ("assists", "nba_ast"), ("steals", "nba_stl"), ("blocks", "nba_blk"), ("totalTurnovers", "nba_tov"),
       ("fouls", "nba_pf")]
PCT = [("fieldGoalPct", "nba_fg_pct"), ("threePointFieldGoalPct", "nba_fg3_pct"), ("freeThrowPct", "nba_ft_pct")]
EXTRA_NBA = [("pointsInPaint", "nba_paint_pts"), ("fastBreakPoints", "nba_fastbreak_pts"),
             ("turnoverPoints", "nba_pts_off_tov"), ("largestLead", "nba_largest_lead")]
NBA_NUEVAS = con_opp([d for _, d in EXTRA_NBA]) + ["tipo"]
TIPO_NBA = {"REG": "REG", "POST": "POST", "5": "PLAYIN"}


def _box(r):
    out = {d: num(r.get(s)) for s, d in BOX}
    for s, d in PCT:
        k = {"nba_fg_pct": ("nba_fgm", "nba_fga"), "nba_fg3_pct": ("nba_fg3m", "nba_fg3a"), "nba_ft_pct": ("nba_ftm", "nba_fta")}[d]
        m, a = out[k[0]], out[k[1]]
        out[d] = round(m / a, 3) if m is not None and a else None
    for s, d in EXTRA_NBA:
        out[d] = num(r.get(s))
    return out


def _llenar_box(r, yo, el, cont):
    by, bo = _box(yo), _box(el)
    pts, ptso = num(yo.get("marcador")), num(el.get("marcador"))
    for k, v in by.items():
        poner(r, k, v, cont)
    for k, v in bo.items():
        poner(r, k + "_opp", v, cont)
    if pts is not None and ptso is not None:
        poner(r, "nba_plus_minus", pts - ptso, cont); poner(r, "nba_plus_minus_opp", ptso - pts, cont)


def _temporada_nba(f):
    y = f.year if f.month >= 8 else f.year - 1
    return "%d-%02d" % (y, (y + 1) % 100)


def nba(log):
    ruta = os.path.join(DAT, "nba.csv")
    cols, filas = leer(ruta)
    if not filas:
        log.append("nba: falta nba.csv"); return None
    cont = collections.Counter()
    # --- NCAAMB: box desde ESPN (gamePk espn_<id>)
    _, ncb = leer(os.path.join(EQ, "espn_ncaamb_equipos.csv"))
    g = por_juego(ncb); h_ncb = 0
    for r in filas:
        if r.get("league") != "NCAAMB":
            continue
        d = g.get(gp(r["gamePk"]).replace("espn_", ""))
        if not d:
            continue
        lado = str(r.get("is_home")).replace(".0", "")
        yo, el = d.get(lado), d.get("0" if lado == "1" else "1")
        if not yo or not el or yo.get("team") != r.get("team"):
            continue
        h_ncb += 1; _llenar_box(r, yo, el, cont); poner(r, "tipo", TIPO_NBA.get(yo.get("tipo"), yo.get("tipo")), cont)
    # --- NBA: extras ESPN en temporada regular + juegos de play-in y playoffs que faltan
    _, nbe = leer(os.path.join(EQ, "espn_nba_equipos.csv"))
    g = por_juego(nbe)
    mapa = mapa_nombres(juegos_base(filas, "league", "NBA"), juegos_espn(g), tol=1)
    idx = indice_espn(g, mapa, tol=1)
    usados = set(); h_reg = 0
    for r in filas:
        if r.get("league") != "NBA":
            continue
        f = dia(r.get("game_date")); lado = str(r.get("is_home")).replace(".0", "")
        h, a = (r["team"], r["opp"]) if lado == "1" else (r["opp"], r["team"])
        x = idx.get((f, h, a))
        if not x:
            poner(r, "tipo", "REG", cont); continue
        _, gid, d = x
        pts, ptso = num(r.get("points")), num(r.get("points_opp"))
        yo, el = d[lado], d["0" if lado == "1" else "1"]
        if pts is None or num(yo.get("marcador")) != pts or num(el.get("marcador")) != ptso:
            poner(r, "tipo", "REG", cont); continue           # mismo cruce pero otro marcador: no se toca
        usados.add(gid); h_reg += 1
        for s, dcol in EXTRA_NBA:
            poner(r, dcol, num(yo.get(s)), cont); poner(r, dcol + "_opp", num(el.get(s)), cont)
        poner(r, "tipo", TIPO_NBA.get(yo.get("tipo"), "REG"), cont)
    # juegos ESPN que no estan en nba.csv: solo play-in y playoffs (la temporada regular la trae stats.nba)
    existentes = {(dia(r["game_date"]), r["team"], r["opp"]) for r in filas if r.get("league") == "NBA"}
    nuevas = []; faltan_nombre = set()
    for gid, d in g.items():
        if gid in usados:
            continue
        tipo = TIPO_NBA.get(d["1"].get("tipo"), d["1"].get("tipo"))
        if tipo not in ("PLAYIN", "POST"):
            continue
        h, a = mapa.get(d["1"]["team"]), mapa.get(d["0"]["team"])
        if not h or not a:
            faltan_nombre.update(x for x in (d["1"]["team"], d["0"]["team"]) if x not in mapa); continue
        f = dia(d["1"]["game_date"])
        if any((f + dt.timedelta(days=o), h, a) in existentes for o in (-1, 0, 1)):
            continue
        for lado, yo, el, t, o in (("1", d["1"], d["0"], h, a), ("0", d["0"], d["1"], a, h)):
            r = {"gamePk": "espn_" + gid, "league": "NBA", "season": _temporada_nba(f), "game_date": f.isoformat(),
                 "team": t, "opp": o, "is_home": lado, "points": fmt(num(yo.get("marcador"))),
                 "points_opp": fmt(num(el.get("marcador"))), "tipo": tipo}
            _llenar_box(r, yo, el, cont)
            nuevas.append(r)
    filas += nuevas
    filas.sort(key=lambda r: ((r.get("game_date") or "")[:10], str(r.get("gamePk") or ""), str(r.get("is_home"))))
    agregar_cols(cols, NBA_NUEVAS)
    n_ncb = sum(1 for r in filas if r.get("league") == "NCAAMB")
    log.append("nba: NCAAMB box %d de %d filas; NBA extras ESPN en %d filas; +%d filas de play-in/playoffs NBA "
               "(%d partidos); %d celdas llenadas%s" % (
                   h_ncb, n_ncb, h_reg, len(nuevas), len(nuevas) // 2, sum(cont.values()),
                   ("; sin nombre: " + ", ".join(sorted(faltan_nombre))) if faltan_nombre else ""))
    return ruta, cols, filas


# ------------------------------------------------------------------ FUTBOL
LIGAS_FUT = {"Premier": "premier", "LaLiga": "laliga", "SerieA": "seriea", "Bundesliga": "bundesliga",
             "Ligue1": "ligue1", "LigaMX": "ligamx", "MLS": "mls"}
# columnas que football-data ya trae en Europa y que en Liga MX / MLS se llenan desde ESPN
FUT_BASE = [("totalShots", "shots"), ("shotsOnTarget", "shots_target"), ("wonCorners", "corners"),
            ("foulsCommitted", "fouls"), ("yellowCards", "yellow"), ("redCards", "red")]
# columnas nuevas para las 7 ligas (solo ESPN)
FUT_EXTRA = [("possessionPct", "possession"), ("totalPasses", "passes"), ("accuratePasses", "passes_acc"),
             ("totalCrosses", "crosses"), ("accurateCrosses", "crosses_acc"), ("totalLongBalls", "longballs"),
             ("accurateLongBalls", "longballs_acc"), ("offsides", "offsides"), ("saves", "saves"),
             ("blockedShots", "shots_blocked"), ("totalTackles", "tackles"), ("effectiveTackles", "tackles_won"),
             ("interceptions", "interceptions"), ("totalClearance", "clearances"), ("penaltyKickGoals", "pk_goals"),
             ("penaltyKickShots", "pk_shots")]
FUT_NUEVAS = con_opp([d for _, d in FUT_EXTRA])


def futbol(log):
    ruta = os.path.join(DAT, "futbol.csv")
    cols, filas = leer(ruta)
    if not filas:
        log.append("futbol: falta futbol.csv"); return None
    cont = collections.Counter(); partes = []
    for liga, le in LIGAS_FUT.items():
        _, eq = leer(os.path.join(EQ, "espn_%s_equipos.csv" % le))
        if not eq:
            partes.append("%s sin archivo ESPN" % liga); continue
        g = por_juego(eq)
        mapa = mapa_nombres(juegos_base(filas, "league", liga, "goals", "goals_opp"), juegos_espn(g), tol=1)
        idx = indice_espn(g, mapa, tol=1)
        hit = n = 0
        for r in filas:
            if r.get("league") != liga:
                continue
            n += 1
            f = dia(r.get("game_date")); lado = str(r.get("is_home")).replace(".0", "")
            h, a = (r["team"], r["opp"]) if lado == "1" else (r["opp"], r["team"])
            x = idx.get((f, h, a))
            if not x:
                continue
            _, gid, d = x
            yo, el = d[lado], d["0" if lado == "1" else "1"]
            if num(yo.get("marcador")) != num(r.get("goals")) or num(el.get("marcador")) != num(r.get("goals_opp")):
                continue
            hit += 1
            for s, dcol in FUT_BASE + FUT_EXTRA:
                poner(r, dcol, num(yo.get(s)), cont); poner(r, dcol + "_opp", num(el.get(s)), cont)
        sin = sorted({x for d in g.values() for x in (d["1"]["team"], d["0"]["team"]) if x not in mapa})
        partes.append("%s %d/%d%s" % (liga, hit, n, (" (sin nombre: %d)" % len(sin)) if sin else ""))
    agregar_cols(cols, FUT_NUEVAS)
    log.append("futbol: filas cruzadas con ESPN -> " + ", ".join(partes) + "; %d celdas llenadas" % sum(cont.values()))
    return ruta, cols, filas


# ------------------------------------------------------------------ BEISBOL
# Lo que batea un equipo es lo que permite el pitcheo del rival. Comprobado en 19,690 juegos de MLB: las 23 parejas
# coinciden en el 100 % (pickoffs 99 %: no se usa).
ESPEJO = [("bat_hits", "pit_hits"), ("bat_doubles", "pit_doubles"), ("bat_triples", "pit_triples"),
          ("bat_homeRuns", "pit_homeRuns"), ("bat_baseOnBalls", "pit_baseOnBalls"),
          ("bat_intentionalWalks", "pit_intentionalWalks"), ("bat_hitByPitch", "pit_hitByPitch"),
          ("bat_strikeOuts", "pit_strikeOuts"), ("bat_atBats", "pit_atBats"), ("bat_runs", "pit_runs"),
          ("bat_rbi", "pit_rbi"), ("bat_stolenBases", "pit_stolenBases"), ("bat_caughtStealing", "pit_caughtStealing"),
          ("bat_sacBunts", "pit_sacBunts"), ("bat_sacFlies", "pit_sacFlies"), ("bat_plateAppearances", "pit_battersFaced"),
          ("bat_groundOuts", "pit_groundOuts"), ("bat_airOuts", "pit_airOuts"), ("bat_flyOuts", "pit_flyOuts"),
          ("bat_lineOuts", "pit_lineOuts"), ("bat_popOuts", "pit_popOuts"),
          ("bat_catchersInterference", "pit_catchersInterference")]


def _outs(ip):
    s = str(ip or "").strip()
    if not s:
        return None
    try:
        a, b = (s.split(".") + ["0"])[:2]
        return int(float(a)) * 3 + int((b or "0")[:1])
    except ValueError:
        return None


def beisbol(log):
    ruta = os.path.join(DAT, "beisbol.csv")
    cols, filas = leer(ruta)
    if not filas:
        log.append("beisbol: falta beisbol.csv"); return None
    cont = collections.Counter()
    g = {}
    for r in filas:
        lado = str(r.get("is_home") or "").replace(".0", "")
        g.setdefault((r.get("league"), gp(r.get("gamePk"))), {})[lado] = r
    # 1) espejo bateo <-> pitcheo del rival, y carreras propias / del rival
    for d in g.values():
        if "0" not in d or "1" not in d:
            continue
        for yo, el in ((d["0"], d["1"]), (d["1"], d["0"])):
            for b, p in ESPEJO:
                poner(yo, b, num(el.get(p)), cont)
                poner(yo, p, num(el.get(b)), cont)
            poner(yo, "bat_runs", num(yo.get("runs")), cont)
            poner(yo, "pit_runs", num(yo.get("runs_opp")), cont)
    # 2) derivados exactos por juego (formulas comprobadas en MLB)
    for r in filas:
        h, d2, d3, hr, ab = (num(r.get(k)) for k in ("bat_hits", "bat_doubles", "bat_triples", "bat_homeRuns", "bat_atBats"))
        if None not in (h, d2, d3, hr):
            poner(r, "bat_totalBases", h + d2 + 2 * d3 + 3 * hr, cont)
        if ab is not None and hr is not None and vacio(r.get("bat_atBatsPerHomeRun")):
            r["bat_atBatsPerHomeRun"] = fmt(round(ab / hr, 2)) if hr else "-.--"; cont["bat_atBatsPerHomeRun"] += 1
        o = _outs(r.get("pit_inningsPitched"))
        if o:
            poner(r, "pit_outs", float(o), cont)
            for src, dst in (("pit_runs", "pit_runsScoredPer9"), ("pit_homeRuns", "pit_homeRunsPer9")):
                v = num(r.get(src))
                if v is not None:
                    poner(r, dst, round(27.0 * v / o, 2), cont)
    # 3) tasas acumuladas de la temporada hasta ese juego (como las guarda MLB): AVG, OBP, SLG, OPS, ERA, WHIP
    orden = sorted(range(len(filas)), key=lambda i: ((filas[i].get("game_date") or "")[:10], gp(filas[i].get("gamePk"))))
    acc = collections.defaultdict(collections.Counter)
    for i in orden:
        r = filas[i]
        a = acc[(r.get("league"), str(r.get("season")).replace(".0", ""), r.get("team"))]
        for k in ("bat_hits", "bat_atBats", "bat_baseOnBalls", "bat_hitByPitch", "bat_sacFlies", "bat_totalBases",
                  "pit_earnedRuns", "pit_hits", "pit_baseOnBalls"):
            v = num(r.get(k))
            if v is not None:
                a[k] += v; a["n_" + k] += 1
        o = _outs(r.get("pit_inningsPitched"))
        if o:
            a["outs"] += o
        if a["bat_atBats"] and r.get("bat_atBats"):
            poner(r, "bat_avg", round(a["bat_hits"] / a["bat_atBats"], 3), cont)
            pa = a["bat_atBats"] + a["bat_baseOnBalls"] + a["bat_hitByPitch"] + a["bat_sacFlies"]
            obp = (a["bat_hits"] + a["bat_baseOnBalls"] + a["bat_hitByPitch"]) / pa if pa else None
            slg = a["bat_totalBases"] / a["bat_atBats"] if a["n_bat_totalBases"] else None
            if obp is not None:
                poner(r, "bat_obp", round(obp, 3), cont)
            if slg is not None:
                poner(r, "bat_slg", round(slg, 3), cont)
            if obp is not None and slg is not None:
                poner(r, "bat_ops", round(obp + slg, 3), cont)
        if a["outs"] and o:
            if a["n_pit_earnedRuns"]:
                poner(r, "pit_era", round(27.0 * a["pit_earnedRuns"] / a["outs"], 2), cont)
            if a["n_pit_hits"] and a["n_pit_baseOnBalls"]:
                poner(r, "pit_whip", round(3.0 * (a["pit_hits"] + a["pit_baseOnBalls"]) / a["outs"], 2), cont)
    log.append("beisbol: %d celdas llenadas (espejo bateo/pitcheo, totales de bases, outs, por 9, tasas de temporada)"
               % sum(cont.values()))
    return ruta, cols, filas


# ------------------------------------------------------------------ cobertura
ARCHIVOS = {"beisbol.csv": "league", "futbol.csv": "league", "americano.csv": "league", "hockey.csv": "league",
            "nba.csv": "league", "tenis.csv": "tour"}
FIJAS = {"gamePk", "league", "season", "game_date", "team", "opp", "is_home", "tour", "tourney_id", "tourney_date"}


def cobertura(datos_mem=None):
    out = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "archivos": {}}
    for nombre, lc in ARCHIVOS.items():
        if datos_mem and nombre in datos_mem:
            cols, filas = datos_mem[nombre]
        else:
            cols, filas = leer(os.path.join(DAT, nombre))
        if not filas:
            continue
        fc = "game_date" if "game_date" in cols else "tourney_date"
        por = collections.defaultdict(list)
        for r in filas:
            por[r.get(lc) or "?"].append(r)
        info = {}
        for lg, rs in sorted(por.items()):
            fs = sorted((r.get(fc) or "")[:10] for r in rs if r.get(fc))
            llenas = {c: round(100.0 * sum(1 for r in rs if not vacio(r.get(c))) / len(rs), 1) for c in cols if c not in FIJAS}
            info[lg] = {"filas": len(rs), "desde": fs[0] if fs else "", "hasta": fs[-1] if fs else "",
                        "columnas_con_dato": sum(1 for v in llenas.values() if v > 0), "columnas": len(llenas),
                        "vacias": sorted(c for c, v in llenas.items() if v == 0), "pct": llenas}
        out["archivos"][nombre] = info
    return out


def imprimir_cobertura(cob):
    for nombre, ligas in cob["archivos"].items():
        print("\n%s" % nombre)
        for lg, i in ligas.items():
            parc = sorted((c for c, v in i["pct"].items() if 0 < v < 50), key=lambda c: i["pct"][c])
            print("  %-8s %7d filas  %s -> %s  columnas con dato %d/%d" % (lg, i["filas"], i["desde"], i["hasta"],
                                                                         i["columnas_con_dato"], i["columnas"]))
            if i["vacias"]:
                print("           sin dato: %s" % ", ".join(i["vacias"][:14]) + (" ... (+%d)" % (len(i["vacias"]) - 14) if len(i["vacias"]) > 14 else ""))
            if parc:
                print("           parcial (<50%%): %s" % ", ".join("%s %.0f%%" % (c, i["pct"][c]) for c in parc[:8]))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--cobertura", action="store_true")
    ap.add_argument("--solo", help="beisbol,hockey,americano,nba,futbol")
    a = ap.parse_args()
    if a.cobertura:
        cob = cobertura(); imprimir_cobertura(cob); _guardar_cob(cob); return 0
    pasos = {"beisbol": beisbol, "hockey": hockey, "americano": americano, "nba": nba, "futbol": futbol}
    elegidos = [x.strip() for x in a.solo.split(",")] if a.solo else list(pasos)
    log, mem = [], {}
    for p in elegidos:
        try:
            res = pasos[p](log)
        except Exception as e:
            log.append("%s: ERROR %s (archivo intacto)" % (p, e)); continue
        if res:
            ruta, cols, filas = res
            mem[os.path.basename(ruta)] = (cols, filas)
            if a.aplicar:
                escribir(ruta, cols, filas)
    print("COMPLETAR DATOS (%s)" % ("aplicado" if a.aplicar else "solo vista; para escribir: --aplicar"))
    for x in log:
        print("  " + x)
    cob = cobertura(mem)
    imprimir_cobertura(cob)
    if a.aplicar:
        _guardar_cob(cob)
    return 0


def _guardar_cob(cob):
    os.makedirs(os.path.join(BASE, "salida"), exist_ok=True)
    with open(os.path.join(BASE, "salida", "cobertura_datos.json"), "w", encoding="utf-8") as f:
        json.dump(cob, f, ensure_ascii=False, indent=1)
    print("\nCobertura en salida\\cobertura_datos.json")


if __name__ == "__main__":
    sys.exit(main())
