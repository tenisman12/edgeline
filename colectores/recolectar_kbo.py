# -*- coding: utf-8 -*-
"""
RECOLECTAR KBO - sin navegador (jala siempre).

Usa los endpoints JSON internos del sitio oficial de KBO via HTTP plano (urllib,
stdlib). NADA de Selenium, NADA de chromedriver: no se rompe cuando Chrome se
actualiza. Basado en la logica de kbo-data-portal/collector.

Nivel de datos por juego (por equipo): carreras (R), hits (H), errores (E),
bases por bolas + golpes (B). Es lo mismo que KBO publica sin JavaScript y lo
mismo que ya tenias. El box score COMPLETO de KBO (AB/HR/K/IP) solo existe en la
pagina con JS y requeriria navegador; aqui no se usa a proposito.

Deja los datos en el MISMO esquema que las otras ligas:
    data_maestra/baseball_boxscores.csv  (league=KBO, runs/bat_hits/bat_baseOnBalls/fld_errors)

Endpoints:
    GetKboGameList     -> juegos del dia (ids, temporada, resultado)
    GetScoreBoardScroll-> R/H/E/B por equipo de cada juego

Uso (en C:\\Edgeline, con tu Python normal - no necesita el venv de scrapers):
    python recolectar_kbo.py --desde 2024 --hasta 2026
    python recolectar_kbo.py --debug 20260927   (imprime el JSON crudo de ese dia)

Si algun campo no mapea (KBO a veces cambia nombres), corre --debug y pegame la
salida: se ajusta el mapeo en un solo paso.
"""
import argparse, csv, io, json, os, sys, time, datetime as dt
import urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "baseball_boxscores.csv")
U_LIST = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
U_SCORE = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScoreBoardScroll"
PAUSA = 0.4

# codigos de equipo en el G_ID (YYYYMMDD + AWAY + HOME + seq) -> nombre canonico
EQUIPOS = {
    "HT": "Kia Tigers", "LG": "LG Twins", "OB": "Doosan Bears", "SS": "Samsung Lions",
    "LT": "Lotte Giants", "NC": "NC Dinos", "KT": "KT Wiz", "WO": "Kiwoom Heroes",
    "SK": "SSG Landers", "SSG": "SSG Landers", "HH": "Hanwha Eagles",
}


def post_json(url, payload):
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.koreabaseball.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("utf-8", "replace")
    # el sitio a veces envuelve el JSON como texto
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        try:
            return json.loads(json.loads(txt))
        except Exception:
            return None


def num(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return 0.0


def equipos_de_gid(gid):
    """G_ID = YYYYMMDD + AWAY(2) + HOME(2) + seq -> (away_code, home_code)."""
    core = gid[8:]
    return core[:2], core[2:4]


def lista_juegos(season, date_str):
    resp = post_json(U_LIST, {"leId": "1", "srId": "0,3,4,5,7", "date": date_str})
    if not resp:
        return []
    return resp.get("game", []) if isinstance(resp, dict) else []


def _heb_del_scoreboard(resp):
    """H/E/B por lado desde table3 del scoreboard. rows[0]=visitante, rows[1]=local,
    celdas = [R, H, E, B]. Devuelve {'away':{...},'home':{...}} o {} si no parsea.
    Extras del scoreboard: asistencia (CROWD_CN) y duracion (USE_TM)."""
    try:
        t3 = json.loads(resp.get("table3", "{}"))
        filas = t3.get("rows", [])
        cel_a = [c["Text"] for c in filas[0]["row"]]   # visitante: [R,H,E,B]
        cel_h = [c["Text"] for c in filas[1]["row"]]   # local
    except (KeyError, IndexError, json.JSONDecodeError, AttributeError):
        return {}
    def heb(c):
        # c = [R, H, E, B]; tomamos H, E, B (R ya viene del marcador)
        return {"bat_hits": num(c[1]), "fld_errors": num(c[2]), "bat_baseOnBalls": num(c[3])} if len(c) >= 4 else {}
    a, h = heb(cel_a), heb(cel_h)
    return {"away": a, "home": h} if (a and h) else {}


def scoreboard(sr_id, season_id, game_id):
    """Devuelve el JSON del scoreboard (para H/E/B y extras), o None."""
    try:
        resp = post_json(U_SCORE, {"leId": "1", "srId": sr_id, "seasonId": season_id, "gameId": game_id})
    except Exception:
        return None
    return resp if isinstance(resp, dict) else None


def recolectar(desde, hasta):
    filas = []
    hoy = dt.date.today()
    for season in range(desde, hasta + 1):
        d = dt.date(season, 3, 1)
        fin = min(dt.date(season, 11, 30), hoy)
        n = 0
        while d <= fin:
            ds = d.strftime("%Y%m%d")
            try:
                juegos = lista_juegos(season, ds)
            except Exception:
                juegos = []
            for g in juegos:
                gid = g.get("G_ID")
                if not gid:
                    continue
                # solo juegos terminados y normales (no cancelados/suspendidos)
                if str(g.get("GAME_STATE_SC")) != "3" or str(g.get("CANCEL_SC_ID", "0")) != "0":
                    continue
                # carreras directo de la lista: T=visitante(top), B=local(bottom)
                runs = {"away": num(g.get("T_SCORE_CN")), "home": num(g.get("B_SCORE_CN"))}
                ac = g.get("AWAY_ID") or equipos_de_gid(gid)[0]
                hc = g.get("HOME_ID") or equipos_de_gid(gid)[1]
                nombres = {"away": EQUIPOS.get(ac, ac), "home": EQUIPOS.get(hc, hc)}
                # H/E/B y extras del scoreboard (defensivo: si no parsea, quedan solo carreras)
                heb, extras = {}, {}
                sb = scoreboard(str(g.get("SR_ID", "0")), str(g.get("SEASON_ID", season)), gid)
                if sb:
                    heb = _heb_del_scoreboard(sb)
                    extras = {"asistencia": (sb.get("CROWD_CN") or "").replace(",", ""),
                              "duracion": sb.get("USE_TM") or "", "estadio": sb.get("FULL_HOME_NM") or g.get("S_NM") or ""}
                for lado, rival in (("home", "away"), ("away", "home")):
                    fila = {"gamePk": gid, "league": "KBO", "season": season,
                            "game_date": d.isoformat(),
                            "team": nombres[lado], "opp": nombres[rival],
                            "is_home": 1 if lado == "home" else 0,
                            "runs": runs[lado], "runs_opp": runs[rival]}
                    if heb:
                        fila.update(heb[lado])
                    fila.update(extras)
                    filas.append(fila)
                n += 1
                time.sleep(PAUSA)
            d += dt.timedelta(days=1)
        print("  %d: %d juegos" % (season, n))
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2024)
    ap.add_argument("--hasta", type=int, default=2026)
    ap.add_argument("--debug", metavar="YYYYMMDD", help="imprime el JSON crudo de ese dia y sale")
    args = ap.parse_args()

    if args.debug:
        season = int(args.debug[:4])
        print("Lista de juegos de %s:" % args.debug)
        juegos = lista_juegos(season, args.debug)
        print(json.dumps(juegos[:2], ensure_ascii=False, indent=2)[:2000])
        if juegos:
            g = juegos[0]
            gid = g.get("G_ID") or g.get("GAME_ID")
            print("\nScoreboard crudo de %s:" % gid)
            resp = post_json(U_SCORE, {"leId": "1", "srId": str(g.get("SR_ID", "0")),
                                       "seasonId": str(g.get("SEASON_ID", season)), "gameId": gid})
            print(json.dumps(resp, ensure_ascii=False, indent=2)[:2500])
        return

    print("Bajando KBO %d-%d (sin navegador)..." % (args.desde, args.hasta))
    filas = recolectar(args.desde, args.hasta)
    if not filas:
        print("Sin datos. Corre --debug 20260927 y pega la salida para ajustar el mapeo."); return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fijas = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home",
             "runs", "runs_opp", "clima", "viento", "asistencia", "primer_pitcheo",
             "duracion", "estadio", "umpire_home"]
    prev = []
    if os.path.exists(OUT):
        with io.open(OUT, encoding="utf-8-sig", errors="replace") as f:
            prev = list(csv.DictReader(f))
    cols = fijas + sorted({k for r in (prev + filas) for k in r if k not in fijas})
    vistos = {(str(r.get("gamePk")), r.get("team")) for r in prev}
    nuevos = [f for f in filas if (str(f["gamePk"]), f.get("team")) not in vistos]
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(prev); w.writerows(nuevos)
    print("\nEscritos %d nuevos KBO (total archivo %d filas) en:\n  %s"
          % (len(nuevos), len(prev) + len(nuevos), OUT))


if __name__ == "__main__":
    main()
