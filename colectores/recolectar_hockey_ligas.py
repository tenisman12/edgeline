# -*- coding: utf-8 -*-
"""
RECOLECTAR HOCKEY LIGAS - SHL, Liiga y AHL (DEL: por ahora solo guarda paginas para revisar su formato).

Mismo esquema que recolectar_hockey.py (NHL): una fila por equipo-juego, con columna league.
Todas las ligas llevan las mismas columnas; lo que una fuente no trae queda vacio (raya en la plataforma).

Fuentes (solo stdlib):
  SHL   stats.swehockey.se  (federacion sueca): calendario, marcador por periodo, tiros, atajadas
  Liiga liiga.fi/api/v2     (oficial): marcador por periodo, expectedGoals, power play
  AHL   lscluster.hockeytech.com (oficial de la liga): calendario, OT/SO, boxscore con tiros

Columnas extra frente a NHL:
  final_tipo     REG / OT / SO  (como termino el partido)
  goals_reg      goles al minuto 60 (para el 1X2 de tiempo regular)
  h_xg           expected goals (solo Liiga)

Uso:
  python colectores\\recolectar_hockey_ligas.py                 (temporada actual + 2 anteriores)
  python colectores\\recolectar_hockey_ligas.py --solo-actual   (rapido: solo 2026-27)
  python colectores\\recolectar_hockey_ligas.py --ligas SHL,AHL
Escribe: <EDGELINE_BASE>\\data_maestra\\hockey_ligas.csv
         <EDGELINE_BASE>\\salida\\cobertura_hockey_ligas.txt  (que columnas trajo cada liga)
         <EDGELINE_BASE>\\salida\\del_muestra\\*.html         (paginas de la DEL para armar su lector)
"""
import argparse, csv, html as htmlmod, io, json, os, re, time
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "hockey_ligas.csv")
COB = os.path.join(BASE, "salida", "cobertura_hockey_ligas.txt")
DEL_DIR = os.path.join(BASE, "salida", "del_muestra")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "en,de;q=0.8"}
HT = "https://lscluster.hockeytech.com/feed/?key=50c2cd9b5e18e390&client_code=ahl&"
SHL_ACTUAL = "20961"                       # SHL 2026-27 en swehockey
FIJAS = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "goals", "goals_opp",
         "goals_reg", "goals_reg_opp", "final_tipo"]
EXTRAS = ["h_sog", "h_sog_opp", "h_xg", "h_xg_opp", "h_powerPlayPctg", "h_powerPlayPctg_opp",
          "goalie_sv", "goalie_sv_opp"]


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

            juegos.append({"id": "LIIGA-%s" % g.get("id"), "liga": "LIIGA", "season": "%d%d" % (s - 1, s),
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
                 "eq_h": g.get("home_team_code") or g.get("home_team_name") or g.get("home_team"),
                 "eq_a": g.get("visiting_team_code") or g.get("visiting_team_name") or g.get("visiting_team"),
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
def shl_temporadas(n_atras):
    """ids de swehockey de la SHL: el actual y los anteriores que salgan en el selector de temporadas."""
    ids = [("2026-27", SHL_ACTUAL)]
    try:
        h = get_txt("https://stats.swehockey.se/ScheduleAndResults/Overview/%s" % SHL_ACTUAL)
        for val, txt in re.findall(r'<option[^>]*value="(\d+)"[^>]*>\s*(\d{4}-\d{2})\s*<', h):
            if val != SHL_ACTUAL and (txt, val) not in ids:
                ids.append((txt, val))
    except Exception:
        pass
    ids.sort(reverse=True)
    return ids[:n_atras + 1]


def shl(n_atras, conocidos):
    juegos = []
    for temp, sid in shl_temporadas(n_atras):
        try:
            h = get_txt("https://stats.swehockey.se/ScheduleAndResults/Schedule/%s" % sid)
        except Exception as e:
            print("  SHL %s: falla %s" % (temp, e)); continue
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


# ------------------------------------------------------------------ DEL (muestra)
def del_muestra():
    """guarda la pagina de juegos y un juego terminado para armar el lector con su formato real."""
    os.makedirs(DEL_DIR, exist_ok=True)
    try:
        h = get_txt("https://www.penny-del.org/spiele")
        io.open(os.path.join(DEL_DIR, "spiele.html"), "w", encoding="utf-8").write(h)
        links = sorted(set(re.findall(r"/statistik/spieldetails/[\w\-]+_\d+", h)))
        print("  DEL: pagina de juegos guardada, %d ligas a juegos" % len(links))
        if links:
            g = get_txt("https://www.penny-del.org" + links[0])
            io.open(os.path.join(DEL_DIR, "juego.html"), "w", encoding="utf-8").write(g)
            print("  DEL: juego de muestra guardado (%s)" % links[0])
    except Exception as e:
        print("  DEL: falla %s" % e)


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
    if os.path.exists(OUT):
        with io.open(OUT, encoding="utf-8-sig", newline="") as fh:
            previos = list(csv.DictReader(fh))
        conocidos = {r["gamePk"] for r in previos if r.get("h_sog") or r.get("league") == "LIIGA"}

    juegos = []
    if "LIIGA" in ligas:
        print("Liiga ..."); juegos += liiga([2027 - i for i in range(n_atras + 1)])
    if "AHL" in ligas:
        print("AHL ..."); juegos += ahl(n_atras, conocidos)
    if "SHL" in ligas:
        print("SHL ..."); juegos += shl(n_atras, conocidos)
    if "DEL" in ligas:
        print("DEL (muestra) ..."); del_muestra()

    nuevas = [f for j in juegos for f in filas_de(j)]
    # se conservan los detalles ya bajados de juegos conocidos
    por_llave = {(r["gamePk"], r["team"]): r for r in previos}
    for f in nuevas:
        viejo = por_llave.get((f["gamePk"], f["team"]))
        if viejo:
            for k in EXTRAS:
                if f.get(k) in ("", None) and viejo.get(k) not in ("", None):
                    f[k] = viejo[k]
        por_llave[(f["gamePk"], f["team"])] = f
    filas = sorted(por_llave.values(), key=lambda r: (r["league"], r["game_date"], str(r["gamePk"]), str(r["is_home"])))
    if not filas:
        print("Sin juegos."); return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIJAS + EXTRAS, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)

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
