# -*- coding: utf-8 -*-
"""
RECOLECTAR HOCKEY LIGAS - SHL, Liiga, AHL y DEL.

Mismo esquema que recolectar_hockey.py (NHL): una fila por equipo-juego, con columna league.
Todas las ligas llevan las mismas columnas; lo que una fuente no trae queda vacio (raya en la plataforma).

Fuentes (solo stdlib):
  SHL   stats.swehockey.se  (federacion sueca): calendario, marcador por periodo, tiros, atajadas
  Liiga liiga.fi/api/v2     (oficial): marcador por periodo, expectedGoals, power play
  AHL   lscluster.hockeytech.com (oficial de la liga): calendario, OT/SO, boxscore con tiros
  DEL   penny-del.org (oficial): pagina de cada juego con marcador por periodo, tiros y power play

Columnas con los mismos nombres que datos/hockey.csv de NHL (shots, goalie_sv, ended_in, tipo) y ademas:
  goals_reg      goles al minuto 60 (para el 1X2 de tiempo regular)
  xg             expected goals (solo Liiga)
  pp_pct         % de power play del partido
Los equipos van con nombre completo (los codigos de la AHL chocan con los de la NHL).

Sin data_maestra\\hockey_ligas.csv (GitHub Actions) toma los juegos ya guardados de datos\\hockey.csv para no
volver a pedir su pagina. actualizar_todo.py lo corre con --solo-actual y mezcla el resultado en datos\\hockey.csv.

Uso:
  python colectores\\recolectar_hockey_ligas.py                 (temporada actual + 2 anteriores)
  python colectores\\recolectar_hockey_ligas.py --solo-actual   (rapido: solo 2026-27)
  python colectores\\recolectar_hockey_ligas.py --ligas SHL,AHL
Escribe: <EDGELINE_BASE>\\data_maestra\\hockey_ligas.csv
         <EDGELINE_BASE>\\salida\\cobertura_hockey_ligas.txt  (que columnas trajo cada liga)
"""
import argparse, csv, html as htmlmod, io, json, os, re, time
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "hockey_ligas.csv")
COB = os.path.join(BASE, "salida", "cobertura_hockey_ligas.txt")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "en,de;q=0.8"}
HT = "https://lscluster.hockeytech.com/feed/?key=50c2cd9b5e18e390&client_code=ahl&"
SHL_ACTUAL = "20961"                       # SHL 2026-27 en swehockey
# ids conocidos de la fase regular de la SHL en swehockey (el selector de temporadas de la pagina no trae ids para todas;
# 2024-25 = 15977, confirmado el 10-oct-2026 desde la pagina del SM-slutspel 2024-25, id 17557)
SHL_IDS = {"2024-25": "15977"}
SIN_FASE_REGULAR = set()   # (liga, temporada) cuyo calendario no es la fase regular: sus filas se quitan
VISTOS = set()          # juegos vistos en los calendarios de esta corrida (incluye los ya guardados que no se piden)
FIJAS = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "goals", "goals_opp",
         "goals_reg", "goals_reg_opp", "final_tipo"]
EXTRAS = ["h_sog", "h_sog_opp", "h_xg", "h_xg_opp", "h_powerPlayPctg", "h_powerPlayPctg_opp",
          "goalie_sv", "goalie_sv_opp"]
# nombre interno -> columna del archivo (la misma que usa datos/hockey.csv de NHL)
SALIDA_COL = {"final_tipo": "ended_in", "h_sog": "shots", "h_sog_opp": "shots_opp", "h_xg": "xg", "h_xg_opp": "xg_opp",
              "h_powerPlayPctg": "pp_pct", "h_powerPlayPctg_opp": "pp_pct_opp"}
COLS_ARCHIVO = [SALIDA_COL.get(c, c) for c in FIJAS] + ["tipo"] + [SALIDA_COL.get(c, c) for c in EXTRAS]
LIGAS_AQUI = ("SHL", "LIIGA", "AHL", "DEL")


def a_interno(r):
    """fila del archivo (nombres nuevos o los de la primera version) -> nombres internos."""
    r = dict(r)
    for interno, col in SALIDA_COL.items():
        if r.get(interno) in (None, "") and r.get(col) not in (None, ""):
            r[interno] = r[col]
    return r


def a_archivo(r):
    out = {SALIDA_COL.get(k, k): v for k, v in r.items() if k in FIJAS or k in EXTRAS}
    out["tipo"] = "REG"
    return out


def get_txt(url, intentos=3):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(2 * (i + 1))


def get_json(url):
    return json.loads(get_txt(url))


def num(x):
    try:
        return float(str(x).replace(",", ".").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def limpio(s):
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def tipo_y_regulacion(hs, as_, tipo, per_h=None, per_a=None):
    """goles al minuto 60. Con periodos los suma; sin periodos: en OT/SO el marcador del 60 es el del perdedor."""
    if per_h is not None and len(per_h) >= 3:
        return tipo, sum(per_h[:3]), sum(per_a[:3])
    if tipo == "REG":
        return tipo, hs, as_
    m = min(hs, as_)
    return tipo, m, m


def filas_de(juego):
    """juego -> 2 filas equipo-juego (local y visita), con *_opp espejo."""
    out = []
    for lado, rival in (("h", "a"), ("a", "h")):
        f = {"gamePk": juego["id"], "league": juego["liga"], "season": juego["season"], "game_date": juego["fecha"],
             "team": juego["eq_" + lado], "opp": juego["eq_" + rival], "is_home": 1 if lado == "h" else 0,
             "goals": juego["g_" + lado], "goals_opp": juego["g_" + rival],
             "goals_reg": juego["r_" + lado], "goals_reg_opp": juego["r_" + rival], "final_tipo": juego["tipo"]}
        for k in ("h_sog", "h_xg", "h_powerPlayPctg", "goalie_sv"):
            v, vo = juego.get(k + "_" + lado), juego.get(k + "_" + rival)
            f[k] = "" if v is None else v
            f[k + "_opp"] = "" if vo is None else vo
        out.append(f)
    return out


# ------------------------------------------------------------------ LIIGA
def liiga(temporadas):
    juegos = []
    for s in temporadas:
        try:
            d = get_json("https://liiga.fi/api/v2/games?tournament=runkosarja&season=%d" % s)
        except Exception as e:
            print("  Liiga %d: falla %s" % (s, e)); continue
        for g in d:
            if not g.get("ended"):
                continue
            h, a = g.get("homeTeam") or {}, g.get("awayTeam") or {}
            if h.get("goals") is None or a.get("goals") is None:
                continue
            per = sorted(g.get("periods") or [], key=lambda p: p.get("index", 0))
            normales = [p for p in per if p.get("category") == "NORMAL"]
            ft = str(g.get("finishedType") or "")
            tipo = "SO" if "WINNING_SHOT" in ft else ("OT" if "EXTENDED" in ft else "REG")
            hs, as_ = float(h["goals"]), float(a["goals"])
            if normales:
                tipo, rh, ra = tipo_y_regulacion(hs, as_, tipo, [p.get("homeTeamGoals", 0) for p in normales],
                                                 [p.get("awayTeamGoals", 0) for p in normales])
            else:
                tipo, rh, ra = tipo_y_regulacion(hs, as_, tipo)

            def pp(t):
                n, gl = num(t.get("powerplayInstances")), num(t.get("powerplayGoals"))
                return round(100.0 * gl / n, 1) if n else None

            juegos.append({"id": "LIIGA-%d-%s" % (s, g.get("id")), "liga": "LIIGA", "season": "%d%d" % (s - 1, s),
                           "fecha": (h.get("gameStartDateTime") or g.get("start") or "")[:10],
                           "eq_h": h.get("teamName"), "eq_a": a.get("teamName"),
                           "g_h": hs, "g_a": as_, "r_h": rh, "r_a": ra, "tipo": tipo,
                           "h_xg_h": num(h.get("expectedGoals")), "h_xg_a": num(a.get("expectedGoals")),
                           "h_powerPlayPctg_h": pp(h), "h_powerPlayPctg_a": pp(a)})
        print("  Liiga %d: %d juegos terminados" % (s, sum(1 for j in juegos if j["season"].endswith(str(s)))))
    return juegos


# ------------------------------------------------------------------ AHL
def ahl_temporadas(n_atras):
    d = get_json(HT + "feed=modulekit&view=seasons")
    regs = []
    for s in (d.get("SiteKit") or {}).get("Seasons") or []:
        nombre = str(s.get("season_name") or "")
        m = re.match(r"(\d{4})", nombre)
        if "Regular Season" in nombre and m:
            regs.append((int(m.group(1)), str(s.get("season_id")), nombre))
    regs.sort(reverse=True)
    return regs[:n_atras + 1]


def buscar(d, claves):
    """primer valor cuya llave (minusculas) este en claves, buscando en todo el JSON."""
    if isinstance(d, dict):
        for k, v in d.items():
            if str(k).lower() in claves:
                return v
        for v in d.values():
            r = buscar(v, claves)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = buscar(v, claves)
            if r is not None:
                return r
    return None


def lado_val(v, lado):
    """{'home':x,'visitor':y} -> x / y"""
    if isinstance(v, dict):
        for k in ((lado,) + (("visitor", "visiting", "away") if lado == "visitor" else ("home",))):
            if k in v:
                return num(v[k])
    return None


def nombre_ahl(g, lado):
    """nombre completo del equipo (Cleveland Monsters): los codigos de la AHL chocan con los de la NHL (CHI, SJ...)."""
    n = g.get("%s_team_name" % lado)
    if not n and g.get("%s_team_city" % lado):
        n = ("%s %s" % (g.get("%s_team_city" % lado), g.get("%s_team_nickname" % lado) or "")).strip()
    return n or g.get("%s_team_code" % lado) or g.get("%s_team" % lado)


def ahl(n_atras, conocidos):
    juegos = []
    for anio, sid, nombre in ahl_temporadas(n_atras):
        try:
            d = get_json(HT + "feed=modulekit&view=schedule&season_id=%s" % sid)
        except Exception as e:
            print("  AHL %s: falla %s" % (nombre, e)); continue
        cal = (d.get("SiteKit") or {}).get("Schedule") or []
        n0 = len(juegos)
        for g in cal:
            if str(g.get("final")) != "1":
                continue
            gid = str(g.get("game_id") or g.get("id"))
            hs, as_ = num(g.get("home_goal_count")), num(g.get("visiting_goal_count"))
            if hs is None or as_ is None:
                continue
            st = str(g.get("game_status") or "")
            tipo = "SO" if (str(g.get("shootout")) == "1" or "SO" in st) else (
                "OT" if (str(g.get("overtime")) not in ("0", "", "None") or "OT" in st) else "REG")
            tipo, rh, ra = tipo_y_regulacion(hs, as_, tipo)
            j = {"id": "AHL-%s" % gid, "liga": "AHL", "season": "%d%d" % (anio, anio + 1),
                 "fecha": str(g.get("date_played") or g.get("GameDateISO8601") or "")[:10],
                 "eq_h": nombre_ahl(g, "home"), "eq_a": nombre_ahl(g, "visiting"),
                 "g_h": hs, "g_a": as_, "r_h": rh, "r_a": ra, "tipo": tipo}
            if j["id"] not in conocidos:
                try:
                    s = get_json(HT + "feed=gc&tab=gamesummary&game_id=%s&fmt=json" % gid)
                    tiros = buscar(s, {"totalshots", "total_shots", "shots"})
                    j["h_sog_h"], j["h_sog_a"] = lado_val(tiros, "home"), lado_val(tiros, "visitor")
                    ppg = buscar(s, {"powerplaygoals", "power_play_goals"})
                    ppc = buscar(s, {"powerplaycount", "power_play_count", "powerplayopportunities"})
                    for lado, suf in (("home", "h"), ("visitor", "a")):
                        g_, c_ = lado_val(ppg, lado), lado_val(ppc, lado)
                        j["h_powerPlayPctg_" + suf] = round(100.0 * g_ / c_, 1) if (g_ is not None and c_) else None
                    time.sleep(0.15)
                except Exception:
                    pass
            juegos.append(j)
        print("  AHL %s: %d juegos terminados" % (nombre, len(juegos) - n0))
    return juegos


# ------------------------------------------------------------------ SHL
def shl_candidatos(sid):
    """{temporada: [ids]} del selector de temporadas en la pagina de una temporada de swehockey."""
    try:
        h = get_txt("https://stats.swehockey.se/ScheduleAndResults/Overview/%s" % sid)
    except Exception as e:
        print("  SHL: no abre la pagina de temporadas %s (%s)" % (sid, e)); return {}, ""
    patrones = [
        r'<option[^>]*value="[^"]*?(\d{4,6})"[^>]*>\s*(\d{4}-\d{2})\s*<',
        r'(?:Overview|Schedule|Standings)/(\d{4,6})[^>]*>\s*(?:<[^>]+>\s*)*(\d{4}-\d{2})\s*<',
        r'(?:value|data-[\w-]+|href)="[^"]*?(\d{4,6})[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*(\d{4}-\d{2})\s*<',
    ]
    cand = {}
    for pat in patrones:
        for val, txt in re.findall(pat, h):
            if val != str(sid):
                cand.setdefault(txt, [])
                if val not in cand[txt]:
                    cand[txt].append(val)
    return cand, h


def shl_temporadas(n_atras):
    """ids de swehockey de la SHL. Se camina hacia atras: la pagina de cada temporada trae bien el id de la
    anterior, asi que se lee el selector desde la temporada ya encontrada."""
    salida = [("2026-27", [SHL_ACTUAL])]
    actual, anio = SHL_ACTUAL, 2026
    for _ in range(n_atras):
        anio -= 1
        txt = "%d-%02d" % (anio, (anio + 1) % 100)
        cand, h = shl_candidatos(actual)
        vals = cand.get(txt, []) or ([SHL_IDS[txt]] if txt in SHL_IDS else [])
        if not vals:
            if h:
                os.makedirs(os.path.dirname(COB), exist_ok=True)
                io.open(os.path.join(os.path.dirname(COB), "shl_overview.html"), "w", encoding="utf-8").write(h)
            print("  SHL: sin id para %s (pagina guardada en salida\\shl_overview.html)" % txt)
            break
        salida.append((txt, vals))
        _, n, mejor = shl_calendario(vals, devolver_id=True)
        if not mejor:
            break
        actual = mejor
    return salida


def shl_calendario(vals, devolver_id=False):
    """de varios ids con la misma temporada, el calendario con mas juegos (la fase regular; no la kvalserie)."""
    mejor, n_mejor, id_mejor = None, -1, None
    for v in vals[:6]:
        try:
            h = get_txt("https://stats.swehockey.se/ScheduleAndResults/Schedule/%s" % v)
        except Exception:
            continue
        n = len(set(re.findall(r"/Game/Events/(\d+)", h)))
        if n > n_mejor:
            mejor, n_mejor, id_mejor = h, n, v
    if devolver_id:
        return mejor, n_mejor, id_mejor
    return mejor, n_mejor


def shl(n_atras, conocidos):
    juegos = []
    for temp, vals in shl_temporadas(n_atras):
        h, n_cal = shl_calendario(vals)
        if not h or (temp != "2026-27" and n_cal < 200):
            print("  SHL %s: sin calendario de fase regular (mejor candidato %d juegos)" % (temp, max(n_cal, 0)))
            SIN_FASE_REGULAR.add(("SHL", "%s%d" % (temp[:4], int(temp[:4]) + 1))); continue
        anio = int(temp[:4])
        fecha = ""
        n0 = len(juegos)
        for fila in re.split(r"<tr[\s>]", h)[1:]:
            mfecha = re.search(r"(\d{4}-\d{2}-\d{2})", fila)
            if mfecha:
                fecha = mfecha.group(1)
            mid = re.search(r"/Game/Events/(\d+)", fila)
            if not mid:
                continue
            celdas = [limpio(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
            equipos = res = per = None
            for c in celdas:
                if res is None and re.fullmatch(r"\d+\s*-\s*\d+", c):
                    res = c
                elif per is None and re.fullmatch(r"\(\s*\d+\s*-\s*\d+(\s*,\s*\d+\s*-\s*\d+)*\s*\)", c):
                    per = c
                elif equipos is None and " - " in c and re.search(r"[A-Za-zÅÄÖåäö]{3}", c) and not re.search(r"\d{2}:\d{2}", c):
                    equipos = c
            if not (equipos and res):
                continue
            eh, ea = [x.strip() for x in equipos.split(" - ", 1)]
            hs, as_ = [float(x) for x in re.findall(r"\d+", res)[:2]]
            ph = pa = None
            tipo = "REG"
            if per:
                pares = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*-\s*(\d+)", per)]
                ph, pa = [p[0] for p in pares], [p[1] for p in pares]
                tipo = "SO" if len(pares) >= 5 else ("OT" if len(pares) == 4 else "REG")
            tipo, rh, ra = tipo_y_regulacion(hs, as_, tipo, ph, pa)
            gid = mid.group(1)
            j = {"id": "SHL-%s" % gid, "liga": "SHL", "season": "%d%d" % (anio, anio + 1), "fecha": fecha,
                 "eq_h": eh, "eq_a": ea, "g_h": hs, "g_a": as_, "r_h": rh, "r_a": ra, "tipo": tipo}
            if j["id"] not in conocidos:
                try:
                    gpag = get_txt("https://stats.swehockey.se/Game/Events/%s" % gid)
                    tiros = re.findall(r"Shots[^()]{0,200}\(([\d:]+)\)", gpag)
                    if len(tiros) >= 2:
                        sh = sum(int(x) for x in tiros[0].split(":"))
                        sa = sum(int(x) for x in tiros[1].split(":"))
                        j["h_sog_h"], j["h_sog_a"] = sh, sa
                        # atajadas del equipo / tiros recibidos (sin goles a porteria vacia, sin tanda)
                        j["goalie_sv_h"] = round(1.0 - ra / sa, 3) if sa and tipo == "REG" else (
                            round(1.0 - (as_ - (1 if (tipo == "SO" and as_ > hs) else 0)) / sa, 3) if sa else None)
                        j["goalie_sv_a"] = round(1.0 - rh / sh, 3) if sh and tipo == "REG" else (
                            round(1.0 - (hs - (1 if (tipo == "SO" and hs > as_) else 0)) / sh, 3) if sh else None)
                    time.sleep(0.2)
                except Exception:
                    pass
            juegos.append(j)
        print("  SHL %s: %d juegos terminados" % (temp, len(juegos) - n0))
    return juegos


# ------------------------------------------------------------------ DEL
DEL_WEB = "https://www.penny-del.org"
EXTRA_SO = {"P", "PS", "SO", "PEN", "S", "N.P.", "NP"}


def del_leer_juego(h, gid):
    """pagina de spieldetails -> juego (o None si no termino / no se entiende)."""
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    t = limpio(t.group(1)) if t else ""
    ms = re.search(r"Saison (\d{4})/(\d{4})", t)
    mf = re.search(r"am (\d{2})\.(\d{2})\.(\d{4})", t)
    sb = re.search(r"<table[^>]*scoreboard-table.*?</table>", h, re.S)
    if not (ms and mf and sb):
        return None
    cab = [limpio(x).upper() for x in re.findall(r"<th[^>]*>(.*?)</th>", sb.group(0), re.S)]
    filas = re.findall(r"<tr[^>]*>(.*?)</tr>", sb.group(0).split("<tbody", 1)[-1], re.S)
    eq = []
    for f in filas:
        celdas = [limpio(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", f, re.S)]
        if len(celdas) >= 5:
            eq.append(celdas)
    if len(eq) < 2:
        return None
    try:
        hs, as_ = float(eq[0][-1]), float(eq[1][-1])
        ph = [int(x) for x in eq[0][1:4]]; pa = [int(x) for x in eq[1][1:4]]
    except ValueError:
        return None
    extras = cab[4:-1] if len(cab) > 5 else []
    tipo = "REG"
    if extras or sum(ph) != hs or sum(pa) != as_:
        tipo = "SO" if (len(extras) >= 2 or (extras and extras[-1] in EXTRA_SO)) else "OT"
    tipo, rh, ra = tipo_y_regulacion(hs, as_, tipo, ph, pa)
    stats = {lab.strip(): (a, b) for lab, a, b in re.findall(
        r'progress-labels__title">([^<]+)</div>\s*</div>\s*<div class="progress-wrapper">\s*'
        r'<div class="progress-labels__value">([^<]*)</div>\s*<div class="progress-labels__value">([^<]*)</div>', h)}
    j = {"id": "DEL-%s" % gid, "liga": "DEL", "season": ms.group(1) + ms.group(2),
         "fecha": "%s-%s-%s" % (mf.group(3), mf.group(2), mf.group(1)),
         "eq_h": eq[0][0], "eq_a": eq[1][0], "g_h": hs, "g_a": as_, "r_h": rh, "r_a": ra, "tipo": tipo}
    sog = stats.get("Schüsse auf Tor")
    if sog:
        sh, sa = num(sog[0]), num(sog[1])
        j["h_sog_h"], j["h_sog_a"] = sh, sa
        if sa:
            j["goalie_sv_h"] = round(1.0 - (as_ - (1 if (tipo == "SO" and as_ > hs) else 0)) / sa, 3)
        if sh:
            j["goalie_sv_a"] = round(1.0 - (hs - (1 if (tipo == "SO" and hs > as_) else 0)) / sh, 3)
    ppq = stats.get("Powerplayquote")
    if ppq:
        j["h_powerPlayPctg_h"], j["h_powerPlayPctg_a"] = num(ppq[0]), num(ppq[1])
    return j


def del_juegos(n_atras, conocidos):
    """los juegos ya guardados se saltan: sus filas se conservan del CSV anterior."""
    juegos = []
    # temporada actual: lista completa de juegos
    links = set()
    for url in ("/spiele/team", "/spiele"):
        try:
            links |= set(re.findall(r"/statistik/spieldetails/[\w\-]+_\d+", get_txt(DEL_WEB + url)))
        except Exception as e:
            print("  DEL %s: falla %s" % (url, e))
        if links:
            break
    hoy = time.strftime("%d%m%Y")
    ids = {}
    for l in links:
        m = re.search(r"/(\d{2})(\d{2})(\d{4})_[\w\-]+_(\d+)$", l)
        if m and (m.group(3) + m.group(2) + m.group(1)) < (hoy[4:] + hoy[2:4] + hoy[:2]):
            ids[int(m.group(4))] = l
    for gid, l in sorted(ids.items()):
        if "DEL-%d" % gid in conocidos:
            VISTOS.add("DEL-%d" % gid); continue
        try:
            j = del_leer_juego(get_txt(DEL_WEB + l), gid)
            if j:
                juegos.append(j)
            time.sleep(0.2)
        except Exception:
            pass
    print("  DEL temporada actual: %d juegos nuevos leidos (de %d terminados en el calendario)" % (len(juegos), len(ids)))
    if not n_atras or not ids:
        return juegos
    # temporadas anteriores: /statistik/saison-AAAA-AA/hauptrunde/spielplan muestra un mes; sus filtros
    # (mes y equipo) son <select> con las direcciones de cada vista: se recorren todas y se juntan los juegos
    n0 = len(juegos)
    anio0 = int(time.strftime("%Y")) if int(time.strftime("%m")) >= 8 else int(time.strftime("%Y")) - 1
    for k in range(1, n_atras + 1):
        a = anio0 - k
        base = "/statistik/saison-%d-%02d/hauptrunde/spielplan" % (a, (a + 1) % 100)
        try:
            h0 = get_txt(DEL_WEB + base)
        except Exception as e:
            print("  DEL %d-%02d: falla %s" % (a, (a + 1) % 100, e)); continue
        vistas = {base}
        for sel in re.findall(r"<select[^>]*>(.*?)</select>", h0, re.S):
            for v in re.findall(r'<option[^>]*value="([^"]+)"', sel):
                if v.startswith("/") and "spielplan" in v:
                    vistas.add(v)
        links = set(re.findall(r"/statistik/spieldetails/[\w\-]+_\d+", h0))
        for v in sorted(vistas - {base}):
            try:
                links |= set(re.findall(r"/statistik/spieldetails/[\w\-]+_\d+", get_txt(DEL_WEB + v)))
            except Exception:
                pass
            time.sleep(0.2)
        ids_t = {}
        for l in links:
            m = re.search(r"/(\d{2})(\d{2})(\d{4})_[\w\-]+_(\d+)$", l)
            if m and int(m.group(3)) in (a, a + 1) and not (int(m.group(3)) == a + 1 and int(m.group(2)) >= 8):
                ids_t[int(m.group(4))] = l
        n_t = 0
        for gid, l in sorted(ids_t.items()):
            if "DEL-%d" % gid in conocidos:
                VISTOS.add("DEL-%d" % gid); continue
            try:
                j = del_leer_juego(get_txt(DEL_WEB + l), gid)
                if j:
                    juegos.append(j); n_t += 1
                time.sleep(0.2)
            except Exception:
                pass
        print("  DEL %d-%02d: %d vistas del calendario, %d juegos en ligas, %d nuevos leidos" % (a, (a + 1) % 100, len(vistas), len(ids_t), n_t))
    print("  DEL temporadas anteriores: %d juegos nuevos" % (len(juegos) - n0))
    return juegos


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default="SHL,LIIGA,AHL,DEL")
    ap.add_argument("--solo-actual", action="store_true")
    args = ap.parse_args()
    ligas = [x.strip().upper() for x in args.ligas.split(",") if x.strip()]
    n_atras = 0 if args.solo_actual else 2

    # juegos ya bajados con detalle: no se vuelve a pedir su pagina
    previos, conocidos = [], set()
    origen = OUT if os.path.exists(OUT) else os.path.join(BASE, "datos", "hockey.csv")
    if os.path.exists(origen):
        with io.open(origen, encoding="utf-8-sig", newline="") as fh:
            previos = [a_interno(r) for r in csv.DictReader(fh) if (r.get("league") or "") in LIGAS_AQUI]
        conocidos = {r["gamePk"] for r in previos if r.get("h_sog") or r.get("league") == "LIIGA"}
        print("Juegos ya guardados (%s): %d" % (os.path.relpath(origen, BASE), len(previos) // 2))

    juegos = []
    if "LIIGA" in ligas:
        print("Liiga ..."); juegos += liiga([2027 - i for i in range(n_atras + 1)])
    if "AHL" in ligas:
        print("AHL ..."); juegos += ahl(n_atras, conocidos)
    if "SHL" in ligas:
        # la historia de la SHL 2024-25 faltaba (swehockey no daba su id): si no esta en los datos, se baja una vez
        n_shl = n_atras
        if n_atras == 0 and not any(r.get("league") == "SHL" and str(r.get("season") or "").startswith("2024") for r in previos):
            n_shl = 2
            print("SHL: falta la temporada 2024-25 en los datos; se baja la historia esta vez")
        print("SHL ..."); juegos += shl(n_shl, conocidos)
    if "DEL" in ligas:
        print("DEL ..."); juegos += del_juegos(n_atras, conocidos)

    nuevas = [f for j in juegos for f in filas_de(j)]
    # se conservan los detalles ya bajados de juegos conocidos
    llave = lambda r: (r["gamePk"], str(r["is_home"]).replace(".0", ""))
    por_llave = {llave(r): r for r in previos}
    for f in nuevas:
        viejo = por_llave.get(llave(f))
        if viejo:
            for k in EXTRAS:
                if f.get(k) in ("", None) and viejo.get(k) not in ("", None):
                    f[k] = viejo[k]
        por_llave[llave(f)] = f
    vistos = VISTOS | {j["id"] for j in juegos}
    # solo se limpian las temporadas que se leyeron en esta corrida (con --solo-actual no se toca la historia)
    leidas = {(j["liga"], str(j["season"])) for j in juegos} | {(r["league"], str(r["season"])) for r in previos if r["gamePk"] in VISTOS}
    quitadas = [k for k, r in por_llave.items() if ((r["league"], str(r["season"])) in leidas and r["gamePk"] not in vistos)
                or (r["league"], str(r["season"])) in SIN_FASE_REGULAR]
    for k in quitadas:
        del por_llave[k]
    if quitadas:
        print("  %d filas viejas quitadas (ids anteriores o fuera de la fase regular)" % len(quitadas))
    filas = sorted(por_llave.values(), key=lambda r: (r["league"], r["game_date"], str(r["gamePk"]), str(r["is_home"])))
    if not filas:
        print("Sin juegos."); return
    # % de salvadas del equipo cuando la fuente trae tiros pero no porteros (AHL y juegos ya guardados):
    # 1 - goles recibidos / tiros recibidos (sin el gol de la tanda de penales)
    for r in filas:
        tiros_rec = num(r.get("h_sog_opp"))
        if r.get("goalie_sv") in ("", None) and tiros_rec:
            g_rec, g_pro = num(r.get("goals_opp")) or 0, num(r.get("goals")) or 0
            g_rec -= 1 if (r.get("final_tipo") == "SO" and g_rec > g_pro) else 0
            r["goalie_sv"] = round(1.0 - g_rec / tiros_rec, 3)
    for r in filas:
        tiros_pro = num(r.get("h_sog"))
        if r.get("goalie_sv_opp") in ("", None) and tiros_pro:
            g_pro, g_rec = num(r.get("goals")) or 0, num(r.get("goals_opp")) or 0
            g_pro -= 1 if (r.get("final_tipo") == "SO" and g_pro > g_rec) else 0
            r["goalie_sv_opp"] = round(1.0 - g_pro / tiros_pro, 3)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS_ARCHIVO, extrasaction="ignore")
        w.writeheader(); w.writerows([a_archivo(r) for r in filas])

    # cobertura: que tanto trae cada liga en cada columna
    lineas = ["Cobertura hockey ligas (%% de filas con dato)  -  %s" % OUT]
    for lg in sorted({r["league"] for r in filas}):
        rs = [r for r in filas if r["league"] == lg]
        tipos = {t: sum(1 for r in rs if r["final_tipo"] == t and r["is_home"] in (1, "1")) for t in ("REG", "OT", "SO")}
        partes = ["%s %d%%" % (k, round(100.0 * sum(1 for r in rs if r.get(k) not in ("", None)) / len(rs)))
                  for k in ("h_sog", "h_xg", "h_powerPlayPctg", "goalie_sv")]
        lineas.append("%-6s %5d juegos | REG %d  OT %d  SO %d | %s" % (lg, len(rs) // 2, tipos["REG"], tipos["OT"],
                                                                       tipos["SO"], " | ".join(partes)))
    os.makedirs(os.path.dirname(COB), exist_ok=True)
    io.open(COB, "w", encoding="utf-8").write("\n".join(lineas) + "\n")
    print("\n" + "\n".join(lineas))


if __name__ == "__main__":
    main()
