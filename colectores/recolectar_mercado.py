# -*- coding: utf-8 -*-
"""
RECOLECTAR MERCADO - cuotas y lineas HISTORICAS gratis, para medir el modelo contra el mercado (CLV) y
para construir modelos que incluyan la vision del mercado.

  futbol : football-data.co.uk -> TODAS las cuotas que publica (apertura y cierre: Pinnacle, Bet365, maximo y
           promedio de mercado; 1X2, Over/Under 2.5, handicap asiatico). 5 ligas europeas + Liga MX + MLS.
           Hasta hoy los colectores de futbol descartaban estas columnas.
  nfl    : nflverse games.csv -> spread, total, moneyline, cuotas over/under, techo, cesped, temperatura, viento,
           mariscales, entrenadores, arbitro, dias de descanso.

Salida:  datos\\mercado\\futbol_cuotas.csv  (llave gamePk = la de datos\\futbol.csv, une con el historial)
         datos\\mercado\\nfl_lineas.csv     (llave game_id = la de datos\\jugadores\\nfl_jugadores.csv)

Incremental: los archivos ya descargados de temporadas cerradas no se piden otra vez; la temporada en curso y
nflverse usan descarga condicional (ETag): si no cambio, no se baja.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python colectores\\recolectar_mercado.py futbol --desde 2017
    python colectores\\recolectar_mercado.py nfl --desde 2018
    python colectores\\recolectar_mercado.py estado
"""
import argparse, csv, datetime as dt, io, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recolectar_jugadores as R

BASE = R.BASE
MERC = os.path.join(BASE, "datos", "mercado")
DIVS = {"E0": "Premier", "SP1": "LaLiga", "I1": "SerieA", "D1": "Bundesliga", "F1": "Ligue1"}
URL_EU = "https://www.football-data.co.uk/mmz4281/%s/%s.csv"
URL_NEW = "https://football-data.co.uk/new/%s.csv"
NEW = {"MEX": "LigaMX", "USA": "MLS"}
ID_FD = {"Div", "Date", "Time", "HomeTeam", "AwayTeam"}
NFL_LINEAS = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"


def _fecha(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except (ValueError, TypeError):
            pass
    return ""


def temporadas(desde):
    hoy = dt.date.today(); fin = hoy.year if hoy.month >= 7 else hoy.year - 1
    return ["%02d%02d" % (y % 100, (y + 1) % 100) for y in range(desde, fin + 1)], "%02d%02d" % (fin % 100, (fin + 1) % 100)


def filas_eu(rows, liga, temp):
    out = []
    for g in rows:
        h, a = (g.get("HomeTeam") or "").strip(), (g.get("AwayTeam") or "").strip()
        if not h or not a or g.get("FTHG") in (None, ""):
            continue
        r = {"gamePk": "%s_%s_%s_%s" % (liga, temp, h.replace(" ", ""), a.replace(" ", "")), "league": liga, "season": temp,
             "game_date": _fecha(g.get("Date")), "home": h, "away": a, "hora": g.get("Time", "")}
        for k, v in g.items():
            if k and k not in ID_FD and v not in (None, ""):
                r["fd_" + k.replace(">", "_mas").replace("<", "_menos")] = v
        out.append(r)
    return out


def filas_new(rows, liga, desde):
    out = []
    for g in rows:
        h, a = (g.get("Home") or "").strip(), (g.get("Away") or "").strip()
        f = _fecha(g.get("Date"))
        if not h or not a or not f or g.get("HG") in (None, "") or int(f[:4]) < desde:
            continue
        season = str(g.get("Season") or "").replace("/", "-")
        r = {"gamePk": "%s_%s_%s_%s_%s" % (liga, f, h.replace(" ", ""), a.replace(" ", ""), season), "league": liga,
             "season": season, "game_date": f, "home": h, "away": a, "hora": g.get("Time", "")}
        for k, v in g.items():
            if k and k not in ("Date", "Time", "Home", "Away", "Country", "League", "Season") and v not in (None, ""):
                r["fd_" + k.replace(">", "_mas").replace("<", "_menos")] = v
        out.append(r)
    return out


def cmd_futbol(desde):
    temps, actual = temporadas(desde)
    cache = os.path.join(R.MAESTRA, "raw", "football-data")
    os.makedirs(cache, exist_ok=True)
    todas = []
    for t in temps:
        for div, liga in DIVS.items():
            ruta = os.path.join(cache, "%s_%s.csv" % (t, div))
            existe = os.path.exists(ruta)
            try:
                if existe and t != actual:
                    txt = open(ruta, encoding="latin-1").read()           # temporada cerrada: no se vuelve a pedir
                elif existe:
                    nuevo = R.get_texto_cond(URL_EU % (t, div), enc="latin-1")   # en curso: solo si cambio
                    txt = nuevo if nuevo is not None else open(ruta, encoding="latin-1").read()
                    if nuevo is not None:
                        open(ruta, "w", encoding="latin-1", errors="replace").write(txt)
                else:
                    txt = R.get_texto(URL_EU % (t, div))
                    open(ruta, "w", encoding="latin-1", errors="replace").write(txt)
            except Exception as e:
                print("  %s %s: no disponible (%s)" % (liga, t, str(e)[:60])); continue
            f = filas_eu(list(csv.DictReader(io.StringIO(txt))), liga, t)
            todas += f
            print("  %-10s %s: %d partidos con cuotas" % (liga, t, len(f)))
    for cod, liga in NEW.items():
        try:
            txt = R.get_texto(URL_NEW % cod)
        except Exception as e:
            print("  %s: no disponible (%s)" % (liga, str(e)[:60])); continue
        f = filas_new(list(csv.DictReader(io.StringIO(txt))), liga, desde)
        todas += f
        print("  %-10s %d partidos con cuotas" % (liga, len(f)))
    if todas:
        n, tot = R.fusionar("futbol_cuotas.csv", todas, lambda r: r["gamePk"],
                            ["gamePk", "league", "season", "game_date", "home", "away", "hora"], carpeta=MERC)
        print("Listo futbol: +%d nuevos (total %d) en %s" % (n, tot, os.path.join(MERC, "futbol_cuotas.csv")))


def cmd_nfl(desde):
    try:
        txt = R.get_texto_cond(NFL_LINEAS)
    except Exception as e:
        print("  nflverse no disponible: %s" % e); return
    if txt is None:
        print("NFL: sin cambios en nflverse, no se baja."); return
    filas = [r for r in csv.DictReader(io.StringIO(txt)) if int(r.get("season") or 0) >= desde]
    for r in filas:
        r["game_date"] = r.get("gameday", "")
    n, tot = R.fusionar("nfl_lineas.csv", filas, lambda r: r["game_id"],
                        ["game_id", "game_date", "season", "week", "game_type", "away_team", "home_team", "away_score", "home_score"],
                        carpeta=MERC)
    print("Listo NFL: +%d nuevos (total %d) en %s" % (n, tot, os.path.join(MERC, "nfl_lineas.csv")))


def cmd_estado():
    print("Mercado en %s\n" % MERC)
    if not os.path.isdir(MERC):
        print("  (vacio)"); return
    for n in sorted(os.listdir(MERC)):
        if n.endswith(".csv"):
            cols, filas = R.leer_csv(os.path.join(MERC, n))
            fs = sorted(r["game_date"] for r in filas if r.get("game_date"))
            print("  %-22s %7d partidos  %3d columnas  %s -> %s" % (n, len(filas), len(cols), fs[0] if fs else "?", fs[-1] if fs else "?"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("que", choices=["futbol", "nfl", "estado", "todo"])
    ap.add_argument("--desde", type=int, default=None)
    a = ap.parse_args()
    if a.que == "estado": cmd_estado()
    if a.que in ("futbol", "todo"): cmd_futbol(a.desde or 2017)
    if a.que in ("nfl", "todo"): cmd_nfl(a.desde or 2018)


if __name__ == "__main__":
    main()
