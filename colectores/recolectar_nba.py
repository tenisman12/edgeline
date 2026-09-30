# -*- coding: utf-8 -*-
"""
RECOLECTAR NBA (ENRIQUECIDO) - toda la data por partido desde stats.nba.com.

Captura TODAS las columnas del leaguegamelog por equipo-juego: puntos, tiros de campo
(FGM/FGA/FG%), triples, libres, rebotes ofensivos/defensivos, asistencias, robos,
tapones, perdidas, faltas y +/-. Con esto el modelo puede calcular Four Factors
(eFG%, TOV%, OREB%, FT rate) y ritmo, no solo el marcador.

Corre en tu maquina (stats.nba.com pide headers, aqui incluidos).

Uso:
    python recolectar_nba.py --desde 2022
Escribe:  data_maestra/nba_games.csv   (copia a datos/nba.csv)
"""
import argparse, csv, io, os, json, time
import urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "nba_games.csv")
URL = "https://stats.nba.com/stats/leaguegamelog"
HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/",
       "Accept": "application/json, text/plain, */*",
       "x-nba-stats-origin": "stats", "x-nba-stats-token": "true", "Connection": "keep-alive"}
# columnas de stats que capturamos (ademas de puntos)
STATS = ["MIN","FGM","FGA","FG_PCT","FG3M","FG3A","FG3_PCT","FTM","FTA","FT_PCT",
         "OREB","DREB","REB","AST","STL","BLK","TOV","PF","PLUS_MINUS"]


def get(season):
    q = urllib.parse.urlencode({"Counter": 1000, "Direction": "DESC", "LeagueID": "00",
                                "PlayerOrTeam": "T", "Season": season,
                                "SeasonType": "Regular Season", "Sorter": "DATE"})
    req = urllib.request.Request(URL + "?" + q, headers=HDR)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return x if x is not None else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2022)
    ap.add_argument("--hasta", type=int, default=2026)
    args = ap.parse_args()

    juegos = {}
    for y in range(args.desde, args.hasta + 1):
        season = "%d-%02d" % (y, (y + 1) % 100)
        try:
            d = get(season)
        except Exception as e:
            print("  %s: %s" % (season, str(e)[:70])); continue
        rs = d.get("resultSets", [{}])[0]
        cols = rs.get("headers", []); rows = rs.get("rowSet", [])
        ix = {c: i for i, c in enumerate(cols)}
        n = 0
        for row in rows:
            gid = row[ix["GAME_ID"]]; matchup = row[ix["MATCHUP"]]
            team = row[ix["TEAM_ABBREVIATION"]]; fecha = row[ix["GAME_DATE"]]
            es_local = "vs." in matchup; rival = matchup.split()[-1]
            stats = {"nba_" + s.lower(): num(row[ix[s]]) for s in STATS if s in ix}
            g = juegos.setdefault(gid, {"season": season, "fecha": fecha})
            lado = "home" if es_local else "away"
            g[lado] = team; g["%s_pts" % lado] = num(row[ix["PTS"]]); g["%s_stats" % lado] = stats
            n += 1
        print("  %s: %d filas" % (season, n))
        time.sleep(0.6)

    filas = []
    for gid, g in juegos.items():
        if "home" not in g or "away" not in g:
            continue
        for lado, rival in (("home", "away"), ("away", "home")):
            fila = {"gamePk": gid, "league": "NBA", "season": g["season"], "game_date": g["fecha"],
                    "team": g[lado], "opp": g[rival], "is_home": 1 if lado == "home" else 0,
                    "points": g.get("%s_pts" % lado), "points_opp": g.get("%s_pts" % rival)}
            fila.update(g.get("%s_stats" % lado, {}))
            # stats del rival con sufijo _opp (para defensa)
            for k, v in (g.get("%s_stats" % rival, {}) or {}).items():
                fila[k + "_opp"] = v
            filas.append(fila)
    if not filas:
        print("Sin juegos."); return
    fijas = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "points", "points_opp"]
    extras = sorted({k for f in filas for k in f if k not in fijas})
    cols = fijas + extras
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("\nEscritos %d equipo-juego, %d columnas, en:\n  %s" % (len(filas), len(cols), OUT))
    print("Ahora cada partido trae FG/rebotes/asist/TOV -> Four Factors. Copia a datos\\nba.csv")


if __name__ == "__main__":
    main()
