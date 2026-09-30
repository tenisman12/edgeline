# -*- coding: utf-8 -*-
"""
RECOLECTAR AMERICANO - NFL desde nflverse (GitHub, gratis).

Baja games.csv de nflverse (resultados historicos de la NFL) y lo deja en el esquema
comun (una fila por equipo-juego con puntos). Corre en tu maquina.

Fuente: nflverse/nfldata  (github.com/nflverse/nfldata)

Uso:
    python recolectar_americano.py --desde 2021
Escribe:  data_maestra/americano_games.csv   (copia a datos/americano.csv)

NCAA: usa otra fuente (por construir); este cubre NFL.
"""
import argparse, csv, io, os, urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "americano_games.csv")
URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2021)
    args = ap.parse_args()

    print("Bajando nflverse games.csv ...")
    req = urllib.request.Request(URL, headers={"User-Agent": "Edgeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = list(csv.DictReader(io.StringIO(r.read().decode("utf-8", "replace"))))
    except Exception as e:
        print("Error:", str(e)[:100]); return

    filas = []
    for g in rows:
        try:
            season = int(g.get("season") or 0)
        except ValueError:
            continue
        if season < args.desde:
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs in (None, "", "NA") or as_ in (None, "", "NA"):
            continue
        gid = g.get("game_id"); fecha = g.get("gameday") or ""
        h, a = g.get("home_team"), g.get("away_team")
        for lado, rival in (("home", "away"), ("away", "home")):
            filas.append({"gamePk": gid, "league": "NFL", "season": season,
                          "game_date": fecha, "week": g.get("week", ""),
                          "team": h if lado == "home" else a, "opp": a if lado == "home" else h,
                          "is_home": 1 if lado == "home" else 0,
                          "points": hs if lado == "home" else as_,
                          "points_opp": as_ if lado == "home" else hs})
    if not filas:
        print("Sin juegos."); return
    cols = ["gamePk", "league", "season", "game_date", "week", "team", "opp", "is_home", "points", "points_opp"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("Escritos %d equipo-juego en:\n  %s" % (len(filas), OUT))
    print("Copia a datos\\americano.csv para el modelo.")


if __name__ == "__main__":
    main()
