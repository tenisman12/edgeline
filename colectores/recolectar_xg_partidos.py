# -*- coding: utf-8 -*-
"""
colectores/recolectar_xg_partidos.py - xG, Corsi y tiros POR PARTIDO de cada equipo NHL (MoneyPuck, game by game).

Para que el modelo de NHL use goles esperados en lugar de goles reales (lo que hoy le falta para pasar la validacion).
Escribe datos/equipos/nhl_xg_partidos.csv: una fila por equipo, partido y situacion ('all' y '5on5').

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python colectores\\recolectar_xg_partidos.py --debug          (baja 1 equipo e imprime columnas; para revisar)
    python colectores\\recolectar_xg_partidos.py                  (las 32 franquicias, temporada regular y playoffs, desde 2023)
    python colectores\\recolectar_xg_partidos.py --desde 2018     (mas historia)

Fuente: https://moneypuck.com/moneypuck/playerData/careers/gameByGame/<regular|playoffs>/teams/<EQUIPO>.csv
Solo stdlib. Es incremental: fusiona por (game_id, team, situation).
"""
import argparse, csv, io, os, sys, time, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SALIDA = os.path.join(BASE, "datos", "equipos", "nhl_xg_partidos.csv")
URL = "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/%s/teams/%s.csv"
EQUIPOS_MP = ["ANA", "ARI", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET", "EDM", "FLA", "LAK", "MIN",
              "MTL", "NJD", "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "UTA", "VAN",
              "VGK", "WPG", "WSH"]
ALTERNOS = {"LAK": "L.A", "NJD": "N.J", "SJS": "S.J", "TBL": "T.B"}     # MoneyPuck ha usado los dos nombres de archivo
A_NUESTRO = {"L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL"}
CAMPOS = [("xGoalsFor", "xgf"), ("xGoalsAgainst", "xga"), ("xGoalsPercentage", "xg_pct"),
          ("corsiPercentage", "corsi_pct"), ("fenwickPercentage", "fenwick_pct"),
          ("shotsOnGoalFor", "sog_f"), ("shotsOnGoalAgainst", "sog_a"), ("goalsFor", "gf"), ("goalsAgainst", "ga"),
          ("highDangerxGoalsFor", "hdxgf"), ("highDangerxGoalsAgainst", "hdxga"),
          ("shotAttemptsFor", "corsi_f"), ("shotAttemptsAgainst", "corsi_a"), ("iceTime", "toi_seg")]
FIJAS = ["game_id", "game_date", "season", "tipo", "team", "opp", "is_home", "situation"]
SITUACIONES = ("all", "5on5")


def bajar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Edgeline)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8", "replace"))))


def eq(x):
    x = (x or "").strip()
    return A_NUESTRO.get(x, x)


def leer(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2023, help="temporada (ano de inicio) desde la que se guarda")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if a.debug:
        rows = bajar(URL % ("regular", "TOR"))
        print("Filas: %d" % len(rows)); print("Columnas:", ", ".join(rows[0].keys()) if rows else "-")
        print(rows[-1] if rows else "")
        return 0
    nuevas, fallos = [], []
    for tipo, carpeta in (("REG", "regular"), ("POST", "playoffs")):
        for t in EQUIPOS_MP:
            rows = None
            for nombre in (t, ALTERNOS.get(t)):
                if not nombre:
                    continue
                try:
                    rows = bajar(URL % (carpeta, nombre)); break
                except Exception as e:
                    err = str(e)[:60]
            if rows is None:
                fallos.append("%s %s: %s" % (carpeta, t, err)); continue
            n = 0
            for r in rows:
                try:
                    season = int(float(r.get("season") or 0))
                except ValueError:
                    continue
                if season < a.desde or (r.get("situation") or "") not in SITUACIONES:
                    continue
                f = str(r.get("gameDate") or "")
                fila = {"game_id": str(r.get("gameId") or "").split(".")[0],
                        "game_date": "%s-%s-%s" % (f[:4], f[4:6], f[6:8]) if len(f) >= 8 else f,
                        "season": "%d%d" % (season, season + 1), "tipo": tipo,
                        "team": eq(r.get("playerTeam") or r.get("team")), "opp": eq(r.get("opposingTeam")),
                        "is_home": "1" if (r.get("home_or_away") or "").upper() == "HOME" else "0",
                        "situation": r.get("situation")}
                for s, d in CAMPOS:
                    fila[d] = r.get(s, "")
                nuevas.append(fila); n += 1
            time.sleep(0.4)
        print("  %s: %d filas" % (carpeta, len(nuevas)))
    if not nuevas:
        print("No se bajo nada. Corre con --debug y pega la salida."); return 1
    viejas = leer(SALIDA)
    idx = {(r["game_id"], r["team"], r["situation"]): r for r in viejas}
    antes = len(idx)
    for r in nuevas:
        idx[(r["game_id"], r["team"], r["situation"])] = r
    cols = FIJAS + [d for _, d in CAMPOS]
    filas = sorted(idx.values(), key=lambda r: (r["game_date"], r["game_id"], r["team"], r["situation"]))
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(filas)
    print("Listo: %d filas (%d nuevas) en %s" % (len(filas), len(filas) - antes, SALIDA))
    eqs = sorted({r["team"] for r in filas})
    print("Equipos (%d): %s" % (len(eqs), " ".join(eqs)))
    if fallos:
        print("Fallaron %d descargas (equipos que no existen en esa carpeta es normal, p.ej. ARI/UTA):" % len(fallos))
        for x in fallos[:10]:
            print("   " + x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
