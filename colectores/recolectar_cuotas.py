# -*- coding: utf-8 -*-
"""
RECOLECTAR CUOTAS - snapshots para línea de cierre y movimiento.

Captura las cuotas de The Odds API en este instante y las AÑADE a un historial con
la hora de captura. Corriendo esto varias veces al día tienes, para cada juego:
  - la APERTURA (primer snapshot),
  - el CIERRE (último antes del partido),
  - todo el MOVIMIENTO intermedio,
que es lo que hace falta para medir CLV (¿le ganaste a la línea de cierre?) y para
mostrar cómo se movió la cuota.

No borra: cada corrida agrega filas nuevas. Una fila por (juego, mercado, selección, libro, hora).

Requisitos: tu llave de The Odds API en la variable de entorno EDGELINE_ODDS_KEY.
  Windows:  set EDGELINE_ODDS_KEY=tu_llave
  Actions:  secret ODDS_KEY

Uso (en tu compu):
  python recolectar_cuotas.py
  python recolectar_cuotas.py --deportes baseball_mlb,icehockey_nhl

Ideal: correrlo cada 2-3 horas (tarea programada / Action en cron) durante el día.
Escribe/actualiza:  data_maestra/market_odds_history.csv
"""
import argparse, csv, io, os, sys, json, datetime as dt
import urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "market_odds_history.csv")
KEY = os.environ.get("EDGELINE_ODDS_KEY", "")
API = "https://api.the-odds-api.com/v4/sports/%s/odds/"

# sport keys de The Odds API para tus deportes
DEPORTES = ["baseball_mlb", "baseball_npb", "baseball_kbo", "icehockey_nhl",
            "americanfootball_nfl", "americanfootball_ncaaf",
            "soccer_mexico_ligamx", "soccer_epl", "soccer_spain_la_liga", "soccer_uefa_champs_league"]

COLS = ["fetched_at_utc", "sport", "commence_time_utc", "home_team", "away_team",
        "bookmaker", "market", "selection", "point", "price_american"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Edgeline/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def snapshot(sportkey, ahora):
    url = API % sportkey + "?" + urllib.parse.urlencode(
        {"apiKey": KEY, "regions": "us,eu", "markets": "h2h,spreads,totals",
         "oddsFormat": "american", "dateFormat": "iso"})
    try:
        data = get(url)
    except Exception as e:
        print("  %-26s error: %s" % (sportkey, str(e)[:70])); return []
    filas = []
    for ev in data:
        home, away = ev.get("home_team"), ev.get("away_team")
        ct = ev.get("commence_time")
        for bk in ev.get("bookmakers", []):
            bname = bk.get("key")
            for m in bk.get("markets", []):
                mk = m.get("key")
                for o in m.get("outcomes", []):
                    filas.append({"fetched_at_utc": ahora, "sport": sportkey,
                                  "commence_time_utc": ct, "home_team": home, "away_team": away,
                                  "bookmaker": bname, "market": mk,
                                  "selection": o.get("name"), "point": o.get("point", ""),
                                  "price_american": o.get("price")})
    print("  %-26s %d juegos, %d filas" % (sportkey, len(data), len(filas)))
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deportes", help="lista separada por comas (default: todos)")
    args = ap.parse_args()
    if not KEY:
        print("Falta la llave. Configura EDGELINE_ODDS_KEY (set EDGELINE_ODDS_KEY=tu_llave)."); return
    deportes = args.deportes.split(",") if args.deportes else DEPORTES
    ahora = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    print("Snapshot de cuotas %s" % ahora)
    filas = []
    for sk in deportes:
        filas += snapshot(sk, ahora)
    if not filas:
        print("Sin cuotas (¿deportes fuera de temporada o llave sin crédito?)."); return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    existe = os.path.exists(OUT)
    with io.open(OUT, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if not existe:
            w.writeheader()
        w.writerows(filas)
    print("\nAgregadas %d filas a:\n  %s" % (len(filas), OUT))
    print("Corre esto cada 2-3 h para tener apertura->cierre y el movimiento.")


if __name__ == "__main__":
    main()
