# -*- coding: utf-8 -*-
"""
RECOLECTAR JUGADORES - una fila por JUGADOR y PARTIDO, para medir record, evolucion e influencia.

Los modelos NO usan estos datos (estan congelados). Sirven para fichas de jugador,
para el "indicador de influencia, no aplicado" (abridor / portero / QB) y para validarlo.

Fuentes (todas gratis, sin key):
  mlb | npb | kbo | invierno   MLB Stats API   -> lanzadores y bateadores por juego
  nhl                          api-web.nhle.com -> porteros y patinadores por juego
  nfl                          nflverse (GitHub) -> todos los jugadores por semana
  espn                         ESPN summary     -> NBA, NCAA basket, NCAA futbol americano,
                                                   futbol (5 ligas, Liga MX, MLS, Champions),
                                                   y cualquier otra liga de ESPN

Salida (incremental, se FUSIONA con lo que ya tengas; respaldo en datos\\_respaldo\\jugadores):
  datos\\jugadores\\mlb_lanzadores.csv, mlb_bateadores.csv     (columna liga: MLB/NPB/KBO/LIDOM/...)
  datos\\jugadores\\nhl_porteros.csv, nhl_patinadores.csv
  datos\\jugadores\\nfl_jugadores.csv
  datos\\jugadores\\espn_<liga>_jugadores.csv   y   data_maestra\\espn_<liga>_juegos.csv (resultados)

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python colectores\\recolectar_jugadores.py estado
    python colectores\\recolectar_jugadores.py mlb --desde 2022-04-01
    python colectores\\recolectar_jugadores.py invierno --desde 2025-10-01
    python colectores\\recolectar_jugadores.py nhl --desde 2023-10-01
    python colectores\\recolectar_jugadores.py nfl --desde-season 2021
    python colectores\\recolectar_jugadores.py espn --liga nba --desde 20221018
    python colectores\\recolectar_jugadores.py espn --liga ncaamb --desde 20231106
Sin --desde: modo diario (continua desde el ultimo dia guardado, menos 3 dias de solape).
Pretemporada / spring training se excluye siempre.
"""
import argparse, csv, datetime as dt, gzip, io, json, os, shutil, subprocess, sys, time
import urllib.error, urllib.parse, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(BASE, "datos", "jugadores")
EQ = os.path.join(BASE, "datos", "equipos")
RESP = os.path.join(BASE, "datos", "_respaldo", "jugadores")
RAW = os.path.join(BASE, "data_maestra", "raw")
MAESTRA = os.path.join(BASE, "data_maestra")
UA = "Mozilla/5.0 (Edgeline)"


# ------------------------------------------------------------------ utilidades
def get_json(url, reintentos=3, pausa=1.5):
    """GET JSON. Si urllib recibe 403/bloqueo (ESPN a veces), reintenta con curl."""
    ult = None
    for i in range(reintentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception as e:
            ult = e
            try:
                exe = "curl.exe" if os.name == "nt" else "curl"
                out = subprocess.run([exe, "-sL", "--max-time", "40", "-A", UA, url],
                                     capture_output=True, timeout=60)
                if out.returncode == 0 and out.stdout:
                    return json.loads(out.stdout.decode("utf-8", "replace"))
            except Exception as e2:
                ult = e2
            time.sleep(pausa * (i + 1))
    raise RuntimeError("fallo %s: %s" % (url, ult))


def get_texto(url, reintentos=3):
    ult = None
    for i in range(reintentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            ult = e; time.sleep(2 * (i + 1))
    raise RuntimeError("fallo %s: %s" % (url, ult))


def cargar(fuente, liga, anio, gid, url, raw=True):
    """JSON de un partido. Si ya esta en data_maestra\\raw\\ (cache comprimido) NO se vuelve a pedir a internet.
    Devuelve (datos, vino_de_internet)."""
    p = os.path.join(RAW, fuente, str(liga).lower(), str(anio), "%s.json.gz" % gid)
    if raw and os.path.exists(p):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh), False
        except Exception:
            pass                                   # archivo danado: se vuelve a bajar
    d = get_json(url)
    if raw:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(d, fh, separators=(",", ":"))
        os.replace(tmp, p)
    return d, True


def num(x):
    if x is None or x == "" or x == "--":
        return ""
    try:
        f = float(x)
        return int(f) if f == int(f) and "." not in str(x) else f
    except (TypeError, ValueError):
        return x


def ip_a_outs(ip):
    """'5.2' (5 entradas y 2 outs) -> 17 outs."""
    try:
        s = str(ip); ent, _, fr = s.partition(".")
        return int(ent) * 3 + int(fr or 0)
    except Exception:
        return ""


def mmss(t):
    """'19:42' -> 19.7 minutos."""
    try:
        m, s = str(t).split(":"); return round(int(m) + int(s) / 60.0, 2)
    except Exception:
        return ""


ESTADO_DESC = os.path.join(MAESTRA, "estado_descargas.json")


def get_texto_cond(url, enc="utf-8"):
    """Descarga solo si el archivo cambio (ETag / Last-Modified guardados). Devuelve None si no cambio."""
    try:
        with open(ESTADO_DESC, encoding="utf-8") as fh:
            est = json.load(fh)
    except Exception:
        est = {}
    h = {"User-Agent": UA}
    e = est.get(url) or {}
    if e.get("etag"): h["If-None-Match"] = e["etag"]
    if e.get("lm"): h["If-Modified-Since"] = e["lm"]
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode(enc, "replace")
            est[url] = {"etag": r.headers.get("ETag", ""), "lm": r.headers.get("Last-Modified", "")}
    except urllib.error.HTTPError as ex:
        if ex.code == 304:
            return None
        raise
    os.makedirs(MAESTRA, exist_ok=True)
    with open(ESTADO_DESC, "w", encoding="utf-8") as fh:
        json.dump(est, fh, indent=1)
    return txt


csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))


def leer_csv(ruta):
    """Lee el CSV. Si una fila viene rota (dos procesos escribieron a la vez, corte de luz), la descarta y avisa:
    el resto del archivo se conserva."""
    if not os.path.exists(ruta):
        return [], []
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames or []
        filas, rotas = [], 0
        while True:
            try:
                r = next(rd)
            except StopIteration:
                break
            except csv.Error:
                rotas += 1; continue
            if r.get(None) is not None or (len(cols) > 3 and sum(1 for v in r.values() if v is None) > len(cols) // 2):
                rotas += 1; continue        # mas campos que columnas, o fila a medias
            filas.append(r)
        if rotas:
            print("  AVISO %s: %d fila(s) rota(s) descartada(s)" % (os.path.basename(ruta), rotas))
        return cols, filas


def fusionar(nombre, filas, llave, fijas, carpeta=None):
    """Mezcla 'filas' con el archivo existente (llave unica), respalda y guarda. Devuelve (nuevas, total)."""
    carpeta = carpeta or DIR
    ruta = os.path.join(carpeta, nombre)
    cols0, previas = leer_csv(ruta)
    d = {llave(r): r for r in previas}
    antes = len(d)
    for r in filas:
        d[llave(r)] = {k: ("" if v is None else v) for k, v in r.items()}
    presentes = set(cols0)
    for r in d.values():
        presentes |= set(r)
    cols = [c for c in fijas if c in presentes] + sorted(presentes - set(fijas))
    if os.path.exists(ruta):
        os.makedirs(RESP, exist_ok=True); shutil.copy2(ruta, os.path.join(RESP, nombre))
    os.makedirs(carpeta, exist_ok=True)
    salida = sorted(d.values(), key=lambda r: (str(r.get("game_date", "")), str(r.get("game_id", ""))))
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(salida)
    return len(d) - antes, len(d)


def ultima_fecha(nombre, col="game_date"):
    _, filas = leer_csv(os.path.join(DIR, nombre))
    fs = sorted(r[col] for r in filas if r.get(col))
    return fs[-1] if fs else None


def desde_modo_diario(nombre, por_defecto, col="game_date", solape=3):
    u = ultima_fecha(nombre, col)
    if not u:
        return por_defecto
    d = dt.date.fromisoformat(u[:10]) - dt.timedelta(days=solape)
    return d.isoformat()


def ids_guardados(nombre, col="game_id"):
    _, filas = leer_csv(os.path.join(DIR, nombre))
    return {str(r.get(col)) for r in filas}


# ------------------------------------------------------------------ BEISBOL (MLB Stats API)
API_MLB = "https://statsapi.mlb.com/api/v1"
LIGAS_BB = {"mlb": (1, None, "MLB"), "npb": (31, None, "NPB"), "kbo": (32, None, "KBO"),
            "lmp": (17, 132, "LMP"), "lvbp": (17, 135, "LVBP"), "lidom": (17, 131, "LIDOM"), "abl": (17, 595, "ABL")}
GRUPOS_BB = {"invierno": ["lmp", "lvbp", "lidom", "abl"], "todas": ["mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl"]}
FIJAS_BB = ["game_id", "game_date", "liga", "season", "team", "opp", "is_home", "player_id", "jugador", "posicion"]


def mlb_get(path, **p):
    url = API_MLB + path + "?" + urllib.parse.urlencode({k: v for k, v in p.items() if v is not None})
    return get_json(url)


def mlb_calendario(sport_id, d1, d2, league_id):
    d = mlb_get("/schedule", sportId=sport_id, startDate=d1, endDate=d2, leagueId=league_id,
                gameType="R,F,D,L,W,C,P")            # sin S (spring training) ni E (exhibicion)
    out = []
    for dia in d.get("dates", []):
        for g in dia.get("games", []):
            if (g.get("status") or {}).get("abstractGameState") != "Final":
                continue
            out.append({"pk": g["gamePk"], "fecha": g.get("officialDate") or (g.get("gameDate") or "")[:10],
                        "season": g.get("season")})
    return out


def mlb_filas(box, meta, liga):
    """box = /game/{pk}/boxscore -> (lanzadores, bateadores)."""
    lan, bat = [], []
    teams = box.get("teams") or {}
    for lado in ("away", "home"):
        t = teams.get(lado) or {}
        otro = teams.get("home" if lado == "away" else "away") or {}
        nom = (t.get("team") or {}).get("name", ""); opp = (otro.get("team") or {}).get("name", "")
        pit_orden = t.get("pitchers") or []
        bat_orden = t.get("battingOrder") or []
        for pid, p in (t.get("players") or {}).items():
            per = p.get("person") or {}
            base = {"game_id": meta["pk"], "game_date": meta["fecha"], "liga": liga, "season": meta["season"],
                    "team": nom, "opp": opp, "is_home": 1 if lado == "home" else 0,
                    "player_id": per.get("id"), "jugador": per.get("fullName"),
                    "posicion": (p.get("position") or {}).get("abbreviation", "")}
            st = p.get("stats") or {}
            pit = st.get("pitching") or {}
            if pit and (pit.get("inningsPitched") not in (None, "") or pit.get("battersFaced")):
                r = dict(base)
                r["abridor"] = 1 if (pit.get("gamesStarted") == 1 or (pit_orden and per.get("id") == pit_orden[0])) else 0
                r["orden_salida"] = (pit_orden.index(per.get("id")) + 1) if per.get("id") in pit_orden else ""
                r["ip"] = pit.get("inningsPitched"); r["outs"] = ip_a_outs(pit.get("inningsPitched"))
                for k_out, k_in in (("h", "hits"), ("r", "runs"), ("er", "earnedRuns"), ("bb", "baseOnBalls"),
                                    ("k", "strikeOuts"), ("hr", "homeRuns"), ("bf", "battersFaced"),
                                    ("pitches", "numberOfPitches"), ("strikes", "strikes"), ("balls", "balls"),
                                    ("hbp", "hitByPitch"), ("ganado", "wins"), ("perdido", "losses"),
                                    ("salvado", "saves"), ("hold", "holds"), ("blown_save", "blownSaves"),
                                    ("inherited", "inheritedRunners"), ("inherited_scored", "inheritedRunnersScored")):
                    r[k_out] = num(pit.get(k_in))
                for k_in, v in pit.items():                      # TODAS las metricas que trae la API
                    if not isinstance(v, (dict, list)) and k_in not in ("note", "summary"):
                        r["pit_" + k_in] = num(v)
                for k_in, v in (st.get("fielding") or {}).items():
                    if not isinstance(v, (dict, list)):
                        r["fld_" + k_in] = num(v)
                lan.append(r)
            bt = st.get("batting") or {}
            if bt and (bt.get("atBats") not in (None, "") or bt.get("plateAppearances")):
                r = dict(base)
                bo = p.get("battingOrder")
                r["orden_bate"] = int(str(bo)[:1]) if bo else ""
                r["titular"] = 1 if (bo and str(bo).endswith("00")) else 0
                for k_out, k_in in (("pa", "plateAppearances"), ("ab", "atBats"), ("r", "runs"), ("h", "hits"),
                                    ("d2", "doubles"), ("d3", "triples"), ("hr", "homeRuns"), ("rbi", "rbi"),
                                    ("bb", "baseOnBalls"), ("k", "strikeOuts"), ("sb", "stolenBases"),
                                    ("cs", "caughtStealing"), ("hbp", "hitByPitch"), ("sf", "sacFlies"),
                                    ("lob", "leftOnBase"), ("tb", "totalBases")):
                    r[k_out] = num(bt.get(k_in))
                for k_in, v in bt.items():
                    if not isinstance(v, (dict, list)) and k_in not in ("note", "summary"):
                        r["bat_" + k_in] = num(v)
                for k_in, v in (st.get("fielding") or {}).items():
                    if not isinstance(v, (dict, list)):
                        r["fld_" + k_in] = num(v)
                bat.append(r)
    return lan, bat


# ------------------------------------------------------------------ NPB (Nippon Baseball Data Repository: por jugador y partido)
REL_NPB = "https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/download"


def _csv_url(url):
    try:
        txt = get_texto(url)
    except Exception as e:                      # el mes en curso suele no existir todavia (404): no es error
        if "404" in str(e):
            return []
        raise
    if not txt or txt.strip() == "Not Found":
        return []
    return list(csv.DictReader(io.StringIO(txt)))


def cmd_npb_repo(a):
    """NPB no tiene box scores en la MLB Stats API. El repositorio publico de armstjc trae stats por jugador y partido
    (bateo y pitcheo, incl. orden de salida del lanzador): se convierten al MISMO esquema que mlb_lanzadores.csv y
    mlb_bateadores.csv con liga = NPB. Pretemporada (game_kind_id != 1) se excluye.
    Uso: python colectores\\recolectar_jugadores.py npb --desde 2024-03-01   (sin --desde: desde el ultimo dia guardado - 3)"""
    f_lan, f_bat = "mlb_lanzadores.csv", "mlb_bateadores.csv"
    d1 = a.desde or desde_modo_diario(f_lan, "2024-03-01")
    d2 = a.hasta or dt.date.today().isoformat()
    y1, y2 = int(d1[:4]), int(d2[:4])
    print("NPB (repositorio): %s -> %s" % (d1, d2))
    tl = tb = 0
    for season in range(y1, y2 + 1):
        sched = _csv_url("%s/schedule/%d_npb_schedule.csv" % (REL_NPB, season))
        juegos = {}
        for g in sched:
            if str(g.get("game_kind_id")) != "1" or g.get("home_score") in (None, "", "NA"):
                continue                       # solo temporada regular y juegos terminados
            fecha = (g.get("game_date") or "")[:10]
            if not (d1 <= fecha <= d2):
                continue
            juegos[str(g.get("game_id"))] = {"fecha": fecha, "season": season,
                                             str(g.get("home_team_id")): (g.get("home_team_name_en"), g.get("away_team_name_en"), 1),
                                             str(g.get("away_team_id")): (g.get("away_team_name_en"), g.get("home_team_name_en"), 0)}
        if not juegos:
            print("  %d: sin juegos en el rango" % season); continue
        meses = sorted({j["fecha"][5:7] for j in juegos.values()})
        lan, bat = [], []
        for mm in meses:
            rows = _csv_url("%s/player_game_stats/%d-%s_game_stats.csv" % (REL_NPB, season, mm))
            for r in rows:
                gid = str(r.get("game_id")); j = juegos.get(gid)
                if not j or str(r.get("team_id")) not in j:
                    continue
                team, opp, is_home = j[str(r.get("team_id"))]
                nombre = r.get("player_name") or r.get("player_name_jap") or ""
                base = {"game_id": gid, "game_date": j["fecha"], "liga": "NPB", "season": season, "team": team, "opp": opp,
                        "is_home": is_home, "player_id": r.get("player_id"), "jugador": nombre.strip(),
                        "jugador_jp": (r.get("player_name_jap") or "").strip(), "posicion": r.get("position") or ""}
                if r.get("pitching_IP") not in (None, "", "NA"):
                    x = dict(base)
                    orden = r.get("pitcher_order_number") or ""
                    x["abridor"] = 1 if str(orden) == "1" or str(r.get("pitching_GS")) in ("1", "1.0") else 0
                    x["orden_salida"] = orden
                    x["ip"] = r.get("pitching_IP"); x["outs"] = ip_a_outs(r.get("pitching_IP_str") or r.get("pitching_IP"))
                    for k_out, k_in in (("h", "pitching_H"), ("r", "pitching_R"), ("er", "pitching_ER"), ("bb", "pitching_BB"),
                                        ("k", "pitching_SO"), ("hr", "pitching_HR"), ("bf", "pitching_BF"), ("pitches", "pitching_PI"),
                                        ("hbp", "pitching_HBP"), ("ganado", "pitching_W"), ("perdido", "pitching_L"), ("salvado", "pitching_SV")):
                        x[k_out] = num(r.get(k_in))
                    lan.append(x)
                if r.get("batting_PA") not in (None, "", "NA", "0") or num(r.get("batting_AB")):
                    x = dict(base)
                    x["titular"] = 1 if str(r.get("batting_GS")) in ("1", "1.0") else 0
                    for k_out, k_in in (("pa", "batting_PA"), ("ab", "batting_AB"), ("r", "batting_R"), ("h", "batting_H"),
                                        ("d2", "batting_2B"), ("d3", "batting_3B"), ("hr", "batting_HR"), ("rbi", "batting_RBI"),
                                        ("bb", "batting_BB"), ("k", "batting_SO"), ("sb", "batting_SB"), ("cs", "batting_CS"),
                                        ("hbp", "batting_HBP"), ("sf", "batting_SF")):
                        x[k_out] = num(r.get(k_in))
                    bat.append(x)
        n1, _ = fusionar(f_lan, lan, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_BB)
        n2, _ = fusionar(f_bat, bat, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_BB)
        tl += n1; tb += n2
        print("  %d: %d juegos, %d lanzador-juego, %d bateador-juego (%d y %d nuevos)" % (season, len(juegos), len(lan), len(bat), n1, n2))
    print("Listo NPB: +%d lanzador-juego, +%d bateador-juego." % (tl, tb))


# ------------------------------------------------------------------ KBO (koreabaseball.com: abridores por juego)
def cmd_kbo_lista(a):
    """KBO no tiene box score publico por jugador. GetKboGameList trae por juego el abridor de cada equipo (id y nombre),
    el ganador, el perdedor y el salvador. Se guardan los dos abridores por juego en mlb_lanzadores.csv (liga KBO):
    sirve para rotacion, descanso y para emparejar al probable del dia. IP/ER quedan vacios.
    Uso: python colectores\\recolectar_jugadores.py kbo --desde 2026-03-20"""
    sys.path.insert(0, os.path.join(BASE, "colectores"))
    import recolectar_kbo as K
    f_lan = "mlb_lanzadores.csv"
    d1 = a.desde or desde_modo_diario(f_lan, "2026-03-20")
    d2 = a.hasta or dt.date.today().isoformat()
    print("KBO (abridores por juego): %s -> %s" % (d1, d2))
    cur, fin = dt.date.fromisoformat(d1), dt.date.fromisoformat(d2)
    filas, dias = [], 0
    while cur <= fin:
        if cur.month < 3 or cur.month > 11:
            cur += dt.timedelta(days=1); continue
        try:
            juegos = K.lista_juegos(cur.year, cur.strftime("%Y%m%d"))
        except Exception as e:
            print("  %s: %s" % (cur, str(e)[:60])); juegos = []
        for g in juegos:
            if str(g.get("GAME_STATE_SC")) != "3" or str(g.get("CANCEL_SC_ID", "0")) != "0":
                continue
            gid = g.get("G_ID"); aw, hm = g.get("AWAY_ID"), g.get("HOME_ID")
            na, nh = K.EQUIPOS.get(aw, aw), K.EQUIPOS.get(hm, hm)
            ra, rh = num(g.get("T_SCORE_CN")), num(g.get("B_SCORE_CN"))
            for lado, pid, nom, team, opp, r_contra in (("away", g.get("T_PIT_P_ID"), g.get("T_PIT_P_NM"), na, nh, rh),
                                                      ("home", g.get("B_PIT_P_ID"), g.get("B_PIT_P_NM"), nh, na, ra)):
                if not pid:
                    continue
                filas.append({"game_id": gid, "game_date": cur.isoformat(), "liga": "KBO", "season": cur.year,
                              "team": team, "opp": opp, "is_home": 1 if lado == "home" else 0,
                              "player_id": pid, "jugador": (nom or "").strip(), "posicion": "P", "abridor": 1, "orden_salida": 1,
                              "ganado": 1 if g.get("W_PIT_P_ID") == pid else 0, "perdido": 1 if g.get("L_PIT_P_ID") == pid else 0,
                              "r_equipo_permite": r_contra})
        dias += 1
        time.sleep(0.3)
        cur += dt.timedelta(days=1)
    n, tot = fusionar(f_lan, filas, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_BB)
    print("Listo KBO: %d dias, %d abridor-juego (%d nuevos; archivo con %d filas)." % (dias, len(filas), n, tot))


def cmd_beisbol(nombre, a):
    ligas = GRUPOS_BB.get(nombre) or [nombre]
    f_lan, f_bat = "mlb_lanzadores.csv", "mlb_bateadores.csv"
    defecto = {"mlb": "2022-04-01"}.get(nombre, "2022-04-01")
    d1 = a.desde or desde_modo_diario(f_lan, defecto)
    d2 = a.hasta or dt.date.today().isoformat()
    print("Beisbol %s: %s -> %s" % (nombre, d1, d2))
    tl, tb = 0, 0
    for lg in ligas:
        sid, lid, etiqueta = LIGAS_BB[lg]
        # ventanas mensuales para no pedir calendarios enormes
        ini = dt.date.fromisoformat(d1); fin = dt.date.fromisoformat(d2)
        ya = ids_guardados(f_lan)
        cur = ini
        while cur <= fin:
            nxt = min(cur + dt.timedelta(days=30), fin)
            try:
                juegos = mlb_calendario(sid, cur.isoformat(), nxt.isoformat(), lid)
            except Exception as e:
                print("  %s %s: calendario fallo (%s)" % (etiqueta, cur, e)); cur = nxt + dt.timedelta(days=1); continue
            nuevos_l, nuevos_b = [], []
            for g in juegos:
                if a.solo_nuevos and not a.raw and str(g["pk"]) in ya:
                    continue
                try:
                    box, web = cargar("mlb", etiqueta, g["fecha"][:4], g["pk"], API_MLB + "/game/%s/boxscore" % g["pk"], a.raw)
                except Exception as e:
                    print("   juego %s fallo: %s" % (g["pk"], e)); continue
                l, b = mlb_filas(box, g, etiqueta)
                nuevos_l += l; nuevos_b += b
                if web:
                    time.sleep(0.2)
            if nuevos_l:
                n1, _ = fusionar(f_lan, nuevos_l, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_BB)
                n2, _ = fusionar(f_bat, nuevos_b, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_BB)
                tl += n1; tb += n2
            print("  %s %s -> %s: %d juegos, %d lanzadores, %d bateadores (filas nuevas)" %
                  (etiqueta, cur, nxt, len(juegos), len(nuevos_l), len(nuevos_b)))
            cur = nxt + dt.timedelta(days=1)
    print("Listo beisbol: +%d lanzador-juego, +%d bateador-juego. Archivos en %s" % (tl, tb, DIR))


# ------------------------------------------------------------------ NHL (api-web.nhle.com)
API_NHL = "https://api-web.nhle.com/v1"
FIJAS_NHL = ["game_id", "game_date", "season", "tipo", "team", "opp", "is_home", "player_id", "jugador", "posicion"]


def nhl_calendario(d1, d2):
    juegos, vistos = [], set()
    cur = dt.date.fromisoformat(d1); fin = dt.date.fromisoformat(d2)
    while cur <= fin:
        try:
            d = get_json("%s/schedule/%s" % (API_NHL, cur.isoformat()))
        except Exception as e:
            print("  calendario %s fallo: %s" % (cur, e)); cur += dt.timedelta(days=7); continue
        for dia in d.get("gameWeek", []):
            for g in dia.get("games", []):
                gid = g.get("id")
                if gid in vistos:
                    continue
                vistos.add(gid)
                if g.get("gameType") not in (2, 3):          # 1 = pretemporada, 4 = all-star/otros
                    continue
                if str(g.get("gameState", "")).upper() not in ("FINAL", "OFF"):
                    continue
                f = dia.get("date") or (g.get("startTimeUTC") or "")[:10]
                if d1 <= f <= d2:
                    juegos.append({"id": gid, "fecha": f, "tipo": "POST" if g.get("gameType") == 3 else "REG",
                                   "season": g.get("season")})
        cur += dt.timedelta(days=7)
    return juegos


def _nom(x):
    n = x.get("name")
    return n.get("default") if isinstance(n, dict) else (n or "")


def _frac(s):
    """'25/27' -> (25, 27)."""
    try:
        a, b = str(s).split("/"); return int(a), int(b)
    except Exception:
        return "", ""


def nhl_filas(box, meta):
    port, pat = [], []
    ph = box.get("playerByGameStats") or {}
    for lado in ("awayTeam", "homeTeam"):
        otro = "homeTeam" if lado == "awayTeam" else "awayTeam"
        eq = ph.get(lado) or {}
        base_c = {"game_id": meta["id"], "game_date": meta["fecha"], "season": meta["season"], "tipo": meta["tipo"],
                  "team": (box.get(lado) or {}).get("abbrev", ""), "opp": (box.get(otro) or {}).get("abbrev", ""),
                  "is_home": 1 if lado == "homeTeam" else 0}
        for g in eq.get("goalies") or []:
            r = dict(base_c); r.update({"player_id": g.get("playerId"), "jugador": _nom(g), "posicion": "G"})
            sv, sa = _frac(g.get("saveShotsAgainst"))
            if sa == "":
                sa = g.get("shotsAgainst", ""); sv = g.get("saves", "")
            r.update({"toi_min": mmss(g.get("toi")), "tiros_contra": sa, "paradas": sv,
                      "goles_contra": g.get("goalsAgainst", ""),
                      "sv_pct": round(sv / sa, 4) if isinstance(sv, int) and isinstance(sa, int) and sa else "",
                      "abridor": 1 if g.get("starter") else 0, "decision": g.get("decision", ""),
                      "pim": g.get("pim", g.get("penaltyMinutes", ""))})
            for k_out, k_in in (("es_tiros_contra", "evenStrengthShotsAgainst"), ("pp_tiros_contra", "powerPlayShotsAgainst"),
                                ("sh_tiros_contra", "shorthandedShotsAgainst")):
                v = g.get(k_in)
                if v not in (None, ""):
                    r[k_out] = v
            for k_out, k_in in (("es_goles_contra", "evenStrengthGoalsAgainst"), ("pp_goles_contra", "powerPlayGoalsAgainst"),
                                ("sh_goles_contra", "shorthandedGoalsAgainst")):
                if g.get(k_in) is not None:
                    r[k_out] = g.get(k_in)
            for k_in, v in g.items():                          # todo lo demas que mande la API
                if not isinstance(v, (dict, list)) and k_in not in ("playerId", "sweaterNumber", "headshot", "position", "toi"):
                    r.setdefault("x_" + k_in, v)
            port.append(r)
        for grupo in ("forwards", "defense"):
            for s in eq.get(grupo) or []:
                r = dict(base_c); r.update({"player_id": s.get("playerId"), "jugador": _nom(s), "posicion": s.get("position", "")})
                for k_out, k_in in (("goles", "goals"), ("asist", "assists"), ("puntos", "points"), ("mas_menos", "plusMinus"),
                                    ("pim", "pim"), ("hits", "hits"), ("pp_goles", "powerPlayGoals"), ("tiros", "sog"),
                                    ("bloqueos", "blockedShots"), ("shifts", "shifts"), ("giveaways", "giveaways"),
                                    ("takeaways", "takeaways"), ("faceoff_pct", "faceoffWinningPctg")):
                    r[k_out] = s.get(k_in, "")
                r["toi_min"] = mmss(s.get("toi"))
                for k_in, v in s.items():
                    if not isinstance(v, (dict, list)) and k_in not in ("playerId", "sweaterNumber", "headshot", "position", "toi"):
                        r.setdefault("x_" + k_in, v)
                pat.append(r)
    return port, pat


def nhl_equipos(box, meta, port, pat):
    """Una fila por equipo y partido: suma de sus jugadores + datos del partido (goles, tiros, como termino)."""
    out = []
    for lado in ("awayTeam", "homeTeam"):
        otro = "homeTeam" if lado == "awayTeam" else "awayTeam"
        ab = (box.get(lado) or {}).get("abbrev", "")
        ps = [r for r in pat if r["team"] == ab]; gs = [r for r in port if r["team"] == ab]

        def suma(rows, k):
            return sum(float(r.get(k) or 0) for r in rows)
        r = {"game_id": meta["id"], "game_date": meta["fecha"], "season": meta["season"], "tipo": meta["tipo"],
             "team": ab, "opp": (box.get(otro) or {}).get("abbrev", ""), "is_home": 1 if lado == "homeTeam" else 0,
             "goles": (box.get(lado) or {}).get("score", ""), "goles_opp": (box.get(otro) or {}).get("score", ""),
             "tiros": (box.get(lado) or {}).get("sog", suma(ps, "tiros")),
             "tiros_opp": (box.get(otro) or {}).get("sog", ""),
             "hits": suma(ps, "hits"), "pim": suma(ps, "pim"), "bloqueos": suma(ps, "bloqueos"),
             "giveaways": suma(ps, "giveaways"), "takeaways": suma(ps, "takeaways"), "pp_goles": suma(ps, "pp_goles"),
             "porteros_usados": len(gs), "portero_abridor": next((x["jugador"] for x in gs if x.get("abridor") == 1), ""),
             "fin_en": (box.get("gameOutcome") or {}).get("lastPeriodType", "")}
        out.append(r)
    return out


def cmd_nhl(a):
    f_p, f_s = "nhl_porteros.csv", "nhl_patinadores.csv"
    d1 = a.desde or desde_modo_diario(f_p, "2023-10-10")
    d2 = a.hasta or dt.date.today().isoformat()
    print("NHL: %s -> %s" % (d1, d2))
    juegos = nhl_calendario(d1, d2)
    ya = ids_guardados(f_p) if (a.solo_nuevos and not a.raw) else set()
    juegos = [g for g in juegos if str(g["id"]) not in ya]
    print("  %d juegos por bajar (temporada regular y playoffs)" % len(juegos))
    lote_p, lote_s, lote_e, total_p, total_s = [], [], [], 0, 0
    for i, g in enumerate(juegos, 1):
        try:
            box, web = cargar("nhl", "nhl", str(g["fecha"])[:4], g["id"], "%s/gamecenter/%s/boxscore" % (API_NHL, g["id"]), a.raw)
        except Exception as e:
            print("   juego %s fallo: %s" % (g["id"], e)); continue
        p, s = nhl_filas(box, g); lote_p += p; lote_s += s
        lote_e += nhl_equipos(box, g, p, s)
        if web:
            time.sleep(0.2)
        if i % 300 == 0 or i == len(juegos):
            n1, _ = fusionar(f_p, lote_p, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_NHL)
            n2, _ = fusionar(f_s, lote_s, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_NHL)
            fusionar("nhl_equipos.csv", lote_e, lambda r: "%s|%s" % (r["game_id"], r["team"]), FIJAS_NHL[:7], carpeta=EQ)
            total_p += n1; total_s += n2; lote_p, lote_s, lote_e = [], [], []
            print("  %d/%d juegos | +%d porteros, +%d patinadores" % (i, len(juegos), total_p, total_s))
    print("Listo NHL. Archivos en %s" % DIR)


# ------------------------------------------------------------------ NFL (nflverse en GitHub)
NFL_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_%d.csv"
NFL_EQ_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_%d.csv"
NFL_GAMES = ["https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv",
             "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"]
QUITAR_NFL = {"headshot_url", "fg_made_list", "fg_missed_list", "fg_blocked_list", "fg_made_distance",
              "fg_missed_distance", "fg_blocked_distance", "gwfg_distance", "player_name"}


def cmd_nfl(a):
    hoy = dt.date.today()
    s0 = a.desde_season or (hoy.year - 1 if hoy.month < 9 else hoy.year)
    if not a.desde_season and os.path.exists(os.path.join(DIR, "nfl_jugadores.csv")):
        s0 = hoy.year - 1 if hoy.month < 9 else hoy.year       # diario: solo la temporada en curso
    fechas = {}
    for url in NFL_GAMES:
        try:
            for r in csv.DictReader(io.StringIO(get_texto(url, reintentos=2))):
                fechas[r.get("game_id")] = r.get("gameday")
            break
        except Exception as e:
            print("  (calendario de fechas no disponible en %s: %s)" % (url, e))
    tot = 0
    for season in range(s0, hoy.year + 1):
        try:
            txt = get_texto_cond(NFL_URL % season) if a.solo_nuevos else get_texto(NFL_URL % season)
        except Exception as e:
            print("  temporada %d no disponible (%s)" % (season, e)); continue
        try:
            txt_eq = get_texto_cond(NFL_EQ_URL % season) if a.solo_nuevos else get_texto(NFL_EQ_URL % season)
        except Exception:
            txt_eq = None
        if txt_eq:
            eq_filas = []
            for r in csv.DictReader(io.StringIO(txt_eq)):
                if r.get("season_type") not in ("REG", "POST"):
                    continue
                o = dict(r); o["game_date"] = fechas.get(r.get("game_id"), ""); o["opp"] = r.get("opponent_team")
                eq_filas.append(o)
            ne, te = fusionar("nfl_equipos.csv", eq_filas, lambda r: "%s|%s" % (r["game_id"], r["team"]),
                              ["game_id", "game_date", "season", "week", "season_type", "team", "opp"], carpeta=EQ)
            print("  temporada %d equipos (EPA, yardas, turnovers...): +%d nuevas (total %d)" % (season, ne, te))
        if txt is None:
            print("  temporada %d jugadores: sin cambios en nflverse, no se baja" % season); continue
        filas = []
        for r in csv.DictReader(io.StringIO(txt)):
            if r.get("season_type") not in ("REG", "POST"):
                continue
            o = {k: v for k, v in r.items() if k not in QUITAR_NFL and v not in (None,)}
            o["game_date"] = fechas.get(r.get("game_id"), "")
            o["jugador"] = r.get("player_display_name") or r.get("player_name")
            o["posicion"] = r.get("position")
            o["team"] = r.get("team"); o["opp"] = r.get("opponent_team")
            filas.append(o)
        n, total = fusionar("nfl_jugadores.csv", filas, lambda r: "%s|%s" % (r["game_id"], r["player_id"]),
                            ["game_id", "game_date", "season", "week", "season_type", "team", "opp",
                             "player_id", "jugador", "posicion"])
        tot += n
        print("  temporada %d: %d filas bajadas, +%d nuevas (total %d)" % (season, len(filas), n, total))
    print("Listo NFL. Archivo: %s" % os.path.join(DIR, "nfl_jugadores.csv"))


# ------------------------------------------------------------------ ESPN (todo lo demas)
SITE = "https://site.api.espn.com/apis/site/v2/sports"
LIGAS_ESPN = {
    "nba": ("basketball", "nba", None), "wnba": ("basketball", "wnba", None),
    "ncaamb": ("basketball", "mens-college-basketball", "50"),       # groups=50: toda la D1
    "ncaawb": ("basketball", "womens-college-basketball", "50"),
    "nfl": ("football", "nfl", None), "ncaafb": ("football", "college-football", "80"),   # 80 = FBS
    "nhl": ("hockey", "nhl", None), "mlb": ("baseball", "mlb", None),
    "premier": ("soccer", "eng.1", None), "laliga": ("soccer", "esp.1", None), "seriea": ("soccer", "ita.1", None),
    "bundesliga": ("soccer", "ger.1", None), "ligue1": ("soccer", "fra.1", None), "ligamx": ("soccer", "mex.1", None),
    "champions": ("soccer", "uefa.champions", None), "mls": ("soccer", "usa.1", None),
}
DEFECTO_ESPN = {"nba": "20221018", "ncaamb": "20231106", "ncaafb": "20230826", "nfl": "20230907", "nhl": "20231010",
                "mlb": "20230330", "champions": "20230912"}
FIJAS_ESPN = ["game_id", "game_date", "liga", "season", "tipo", "team", "opp", "is_home", "player_id", "jugador",
              "posicion", "titular"]
FIJAS_JUEGOS = ["game_id", "game_date", "liga", "season", "tipo", "home", "away", "score_home", "score_away",
                "neutral", "conf_game", "estado"]


def _clave_stat(k):
    return str(k).replace(" ", "_").replace("/", "_").replace("-", "_")


def _parte(keys, vals):
    """Aplana una lista de stats; 'a-b' / 'a/b' con valor 'x-y' / 'x/y' se separa en dos columnas."""
    out = {}
    for k, v in zip(keys, vals):
        k = str(k)
        sep = "-" if "-" in k and isinstance(v, str) and "-" in v and k.count("-") == v.count("-") else \
              ("/" if "/" in k and isinstance(v, str) and "/" in v and k.count("/") == v.count("/") else None)
        if sep and isinstance(v, str):
            for kk, vv in zip(k.split(sep), v.split(sep)):
                out[_clave_stat(kk)] = num(vv)
        else:
            out[_clave_stat(k)] = num(v)
    return out


def espn_filas(summary, liga, meta):
    """Jugadores de un summary de ESPN. Devuelve lista de filas (una por jugador y partido)."""
    hdr = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    lado = {}
    for c in hdr.get("competitors", []):
        lado[str((c.get("team") or {}).get("id"))] = c.get("homeAway")
    nombres = {str((c.get("team") or {}).get("id")): (c.get("team") or {}).get("displayName") for c in hdr.get("competitors", [])}
    filas = []
    for eq in (summary.get("boxscore") or {}).get("players") or []:
        tid = str((eq.get("team") or {}).get("id"))
        me = nombres.get(tid, (eq.get("team") or {}).get("displayName", ""))
        rival = next((n for i, n in nombres.items() if i != tid), "")
        porjug = {}
        for cat in eq.get("statistics") or []:
            prefijo = cat.get("name") or ""
            claves = cat.get("keys") or cat.get("names") or []
            for at in cat.get("athletes") or []:
                a = at.get("athlete") or {}
                pid = a.get("id")
                if pid is None:
                    continue
                r = porjug.setdefault(pid, {
                    "game_id": meta["id"], "game_date": meta["fecha"], "liga": liga, "season": meta.get("season", ""),
                    "tipo": meta.get("tipo", ""), "team": me, "opp": rival,
                    "is_home": 1 if lado.get(tid) == "home" else 0, "player_id": pid,
                    "jugador": a.get("displayName"), "posicion": (a.get("position") or {}).get("abbreviation", ""),
                    "titular": 1 if at.get("starter") else 0})
                for k, v in _parte(claves, at.get("stats") or []).items():
                    r[("%s_%s" % (prefijo, k)) if prefijo else k] = v
        filas += list(porjug.values())
    if not filas:                                   # futbol: rosters con stats por jugador
        for ro in summary.get("rosters") or []:
            tid = str((ro.get("team") or {}).get("id"))
            me = nombres.get(tid, (ro.get("team") or {}).get("displayName", ""))
            rival = next((n for i, n in nombres.items() if i != tid), "")
            for p in ro.get("roster") or []:
                a = p.get("athlete") or {}
                if a.get("id") is None:
                    continue
                r = {"game_id": meta["id"], "game_date": meta["fecha"], "liga": liga, "season": meta.get("season", ""),
                     "tipo": meta.get("tipo", ""), "team": me, "opp": rival,
                     "is_home": 1 if (ro.get("homeAway") or lado.get(tid)) == "home" else 0,
                     "player_id": a.get("id"), "jugador": a.get("displayName"),
                     "posicion": (p.get("position") or {}).get("abbreviation", ""),
                     "titular": 1 if p.get("starter") else 0, "dorsal": p.get("jersey", "")}
                for s in p.get("stats") or []:
                    if s.get("name") is not None:
                        r[_clave_stat(s["name"])] = num(s.get("value", s.get("displayValue")))
                filas.append(r)
    return filas


def espn_equipos(summary, liga, meta):
    """Estadisticas de EQUIPO del box score de ESPN (tiros, posesion, rebotes, yardas, turnovers...)."""
    hdr = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    lado = {}; nombres = {}; marc = {}
    for c in hdr.get("competitors", []):
        tid = str((c.get("team") or {}).get("id"))
        lado[tid] = c.get("homeAway"); nombres[tid] = (c.get("team") or {}).get("displayName"); marc[tid] = c.get("score")
    out = []
    for t in (summary.get("boxscore") or {}).get("teams") or []:
        tid = str((t.get("team") or {}).get("id"))
        r = {"game_id": meta["id"], "game_date": meta["fecha"], "liga": liga, "season": meta.get("season", ""),
             "tipo": meta.get("tipo", ""), "team": nombres.get(tid, (t.get("team") or {}).get("displayName", "")),
             "opp": next((n for i, n in nombres.items() if i != tid), ""),
             "is_home": 1 if (t.get("homeAway") or lado.get(tid)) == "home" else 0, "marcador": num(marc.get(tid))}
        sts = t.get("statistics") or []
        r.update(_parte([x.get("name") for x in sts], [x.get("displayValue", x.get("value")) for x in sts]))
        out.append(r)
    return out


def espn_eventos(deporte, liga_espn, grupos, fecha):
    url = "%s/%s/%s/scoreboard?dates=%s&limit=500" % (SITE, deporte, liga_espn, fecha)
    if grupos:
        url += "&groups=%s" % grupos
    d = get_json(url)
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        est = ((comp.get("status") or e.get("status") or {}).get("type") or {})
        if not est.get("completed"):
            continue
        stype = (e.get("season") or {}).get("type")
        if stype == 1:                                # pretemporada
            continue
        cps = comp.get("competitors") or []
        h = next((c for c in cps if c.get("homeAway") == "home"), {}); v = next((c for c in cps if c.get("homeAway") == "away"), {})
        out.append({"id": e.get("id"), "fecha": fecha[:4] + "-" + fecha[4:6] + "-" + fecha[6:8],
                    "season": (e.get("season") or {}).get("year", ""),
                    "tipo": {2: "REG", 3: "POST", 4: "OFF"}.get(stype, str(stype or "")),
                    "home": (h.get("team") or {}).get("displayName", ""), "away": (v.get("team") or {}).get("displayName", ""),
                    "score_home": num(h.get("score")), "score_away": num(v.get("score")),
                    "neutral": 1 if comp.get("neutralSite") else 0, "conf_game": 1 if comp.get("conferenceCompetition") else 0,
                    "estado": est.get("name", "")})
    return out


def cmd_espn(a):
    if a.liga not in LIGAS_ESPN:
        print("Liga desconocida. Opciones: " + ", ".join(sorted(LIGAS_ESPN))); return
    dep, le, grp = LIGAS_ESPN[a.liga]
    f_j = "espn_%s_jugadores.csv" % a.liga
    f_g = "espn_%s_juegos.csv" % a.liga
    desde = (a.desde or "").replace("-", "")
    if not desde:
        u = ultima_fecha(f_j)
        if u:
            desde = (dt.date.fromisoformat(u[:10]) - dt.timedelta(days=3)).strftime("%Y%m%d")
        else:
            desde = DEFECTO_ESPN.get(a.liga, "20230801")
    hasta = (a.hasta or dt.date.today().isoformat()).replace("-", "")
    print("ESPN %s: %s -> %s" % (a.liga, desde, hasta))
    ya = ids_guardados(f_j) if (a.solo_nuevos and not a.raw) else set()
    d0 = dt.datetime.strptime(desde, "%Y%m%d").date(); d1 = dt.datetime.strptime(hasta, "%Y%m%d").date()
    lote_j, lote_g, lote_e, bajados = [], [], [], 0
    cur = d0
    while cur <= d1:
        f = cur.strftime("%Y%m%d")
        try:
            evs = espn_eventos(dep, le, grp, f)
        except Exception as e:
            print("  %s scoreboard fallo: %s" % (f, e)); cur += dt.timedelta(days=1); continue
        for ev in evs:
            lote_g.append({"game_id": ev["id"], "game_date": ev["fecha"], "liga": a.liga, "season": ev["season"],
                           "tipo": ev["tipo"], "home": ev["home"], "away": ev["away"], "score_home": ev["score_home"],
                           "score_away": ev["score_away"], "neutral": ev["neutral"], "conf_game": ev["conf_game"],
                           "estado": ev["estado"]})
            if str(ev["id"]) in ya:
                continue
            try:
                sm, web = cargar("espn", a.liga, ev["fecha"][:4], ev["id"],
                                 "%s/%s/%s/summary?event=%s" % (SITE, dep, le, ev["id"]), a.raw)
            except Exception as e:
                print("   %s fallo: %s" % (ev["id"], e)); continue
            lote_j += espn_filas(sm, a.liga, ev); lote_e += espn_equipos(sm, a.liga, ev); bajados += 1
            if web:
                time.sleep(0.15)
        if (cur.day == 1 or cur == d1 or len(lote_j) > 4000) and (lote_j or lote_g):
            _guardar_espn(f_j, f_g, lote_j, lote_g, lote_e, a.liga); lote_j, lote_g, lote_e = [], [], []
            print("  hasta %s: %d partidos con jugadores bajados" % (f, bajados))
        cur += dt.timedelta(days=1)
    if lote_j or lote_g:
        _guardar_espn(f_j, f_g, lote_j, lote_g, lote_e, a.liga)
    print("Listo ESPN %s: %d partidos nuevos. Jugadores: %s | Resultados: %s" %
          (a.liga, bajados, os.path.join(DIR, f_j), os.path.join(MAESTRA, f_g)))


def _guardar_espn(f_j, f_g, lote_j, lote_g, lote_e, liga):
    if lote_e:
        fusionar("espn_%s_equipos.csv" % liga, lote_e, lambda r: "%s|%s" % (r["game_id"], r["team"]), FIJAS_ESPN[:8], carpeta=EQ)
    if lote_j:
        fusionar(f_j, lote_j, lambda r: "%s|%s" % (r["game_id"], r["player_id"]), FIJAS_ESPN)
    if lote_g:
        fusionar(f_g, lote_g, lambda r: str(r["game_id"]), FIJAS_JUEGOS, carpeta=MAESTRA)


# ------------------------------------------------------------------ estado
def cmd_estado():
    for titulo, carpeta in (("Jugadores", DIR), ("Equipos (estadisticas de equipo por partido)", EQ)):
        print("%s en %s\n" % (titulo, carpeta))
        if not os.path.isdir(carpeta):
            print("  (carpeta vacia: aun no se ha bajado nada)\n"); continue
        for n in sorted(os.listdir(carpeta)):
            if not n.endswith(".csv"):
                continue
            cols, filas = leer_csv(os.path.join(carpeta, n))
            fs = sorted(r["game_date"] for r in filas if r.get("game_date"))
            ent = len({r.get("player_id") or r.get("team") for r in filas})
            print("  %-30s %8d filas  %6d %s  %3d columnas  %s -> %s" % (
                n, len(filas), ent, "jugadores" if carpeta == DIR else "equipos", len(cols), fs[0] if fs else "?", fs[-1] if fs else "?"))
        print()
    n_raw = sum(1 for _, _, fs in os.walk(RAW) for f in fs if f.endswith(".json.gz")) if os.path.isdir(RAW) else 0
    print("Copias crudas comprimidas en %s: %d partidos" % (RAW, n_raw))


def main():
    ap = argparse.ArgumentParser(description="Datos de jugadores por partido")
    ap.add_argument("que", choices=["estado", "mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl", "invierno", "todas",
                                    "nhl", "nfl", "espn"])
    ap.add_argument("--desde"); ap.add_argument("--hasta"); ap.add_argument("--liga")
    ap.add_argument("--desde-season", dest="desde_season", type=int)
    ap.add_argument("--todo", dest="solo_nuevos", action="store_false",
                    help="vuelve a bajar partidos que ya tienes (por defecto solo los nuevos)")
    ap.add_argument("--sin-raw", dest="raw", action="store_false",
                    help="no guardar la copia cruda comprimida de cada partido (por defecto se guarda en data_maestra\\raw)")
    ap.set_defaults(solo_nuevos=True, raw=True)
    a = ap.parse_args()
    if a.que == "estado": cmd_estado()
    elif a.que == "npb": cmd_npb_repo(a)
    elif a.que == "kbo": cmd_kbo_lista(a)
    elif a.que == "nhl": cmd_nhl(a)
    elif a.que == "nfl": cmd_nfl(a)
    elif a.que == "espn": cmd_espn(a)
    else: cmd_beisbol(a.que, a)


if __name__ == "__main__":
    main()
