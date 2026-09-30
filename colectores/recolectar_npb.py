# -*- coding: utf-8 -*-
"""
RECOLECTAR NPB - desde el Nippon Baseball Data Repository (GitHub, gratis).

NPB no viene en la MLB Stats API. Este colector baja los datos publicos de
armstjc/Nippon-Baseball-Data-Repository (fuente: SPAIA) y los deja en el MISMO
esquema que recolectar_boxscores.py (una fila por equipo-juego, columnas bat_/pit_),
para que NPB viva junto a MLB y las ligas de invierno en el mismo archivo.

No necesita API key, ni Selenium, ni chromedriver: son CSV en releases de GitHub.
Solo stdlib.

Fuente y cita (el repo lo pide):
    This uses data sourced from the Nippon Baseball Data Repository:
    https://github.com/armstjc/Nippon-Baseball-Data-Repository

Uso (en C:\\Edgeline):
    python recolectar_npb.py --desde 2024 --hasta 2026
Escribe/actualiza:  data_maestra/baseball_boxscores.csv  (mismo archivo que MLB)
"""
import argparse, csv, io, os, sys, urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "baseball_boxscores.csv")
REL = "https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/download"

# mapa: columna NPB -> columna esquema Edgeline (las mismas llaves que la MLB Stats API)
BAT = {
    "batting_AB": "bat_atBats", "batting_R": "bat_runs", "batting_H": "bat_hits",
    "batting_2B": "bat_doubles", "batting_3B": "bat_triples", "batting_HR": "bat_homeRuns",
    "batting_RBI": "bat_rbi", "batting_SB": "bat_stolenBases", "batting_CS": "bat_caughtStealing",
    "batting_BB": "bat_baseOnBalls", "batting_SO": "bat_strikeOuts", "batting_HBP": "bat_hitByPitch",
    "batting_SH": "bat_sacBunts", "batting_SF": "bat_sacFlies", "batting_PA": "bat_plateAppearances",
}
PIT = {
    "pitching_IP": "pit_inningsPitched", "pitching_H": "pit_hits", "pitching_R": "pit_runs",
    "pitching_ER": "pit_earnedRuns", "pitching_HR": "pit_homeRuns", "pitching_BB": "pit_baseOnBalls",
    "pitching_IBB": "pit_intentionalWalks", "pitching_SO": "pit_strikeOuts",
    "pitching_HBP": "pit_hitByPitch", "pitching_BK": "pit_balks", "pitching_BF": "pit_battersFaced",
}


def bajar_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Edgeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return None
    if data.strip() == "Not Found" or not data.strip():
        return None
    return list(csv.DictReader(io.StringIO(data)))


def _num(x):
    try:
        v = float(x); return v
    except (TypeError, ValueError):
        return 0.0


def _ip(x):
    """IP NPB (ej 6.2 = 6 y 2/3) -> innings decimales."""
    v = _num(x)
    ent = int(v); dec = round(v - ent, 1); outs = int(round(dec * 10))
    return ent + (outs / 3.0 if outs in (1, 2) else 0.0)


def recolectar(desde, hasta):
    filas = []
    for season in range(desde, hasta + 1):
        sched = bajar_csv("%s/schedule/%d_npb_schedule.csv" % (REL, season))
        if not sched:
            print("  %d: sin calendario" % season); continue
        # juegos finalizados: {game_id: info}
        juegos = {}
        for g in sched:
            hs, as_ = g.get("home_score"), g.get("away_score")
            if hs in (None, "", "NA") or as_ in (None, "", "NA"):
                continue
            gid = str(g.get("game_id"))
            juegos[gid] = {
                "fecha": (g.get("game_date") or "")[:10],
                "home_id": str(g.get("home_team_id")), "away_id": str(g.get("away_team_id")),
                "home": g.get("home_team_name_en") or g.get("home_team_short_name"),
                "away": g.get("away_team_name_en") or g.get("away_team_short_name"),
                "home_score": _num(hs), "away_score": _num(as_),
                "estadio": g.get("stadium_name_short") or g.get("stadium_name_jpn"),
            }
        # stats por jugador, agregadas a (game_id, team_id)
        agg = {}   # (gid, team_id) -> dict acumulado
        for mes in range(2, 12):
            rows = bajar_csv("%s/player_game_stats/%d-%02d_game_stats.csv" % (REL, season, mes))
            if not rows:
                continue
            for r in rows:
                gid = str(r.get("game_id")); tid = str(r.get("team_id"))
                if gid not in juegos:
                    continue
                a = agg.setdefault((gid, tid), {v: 0.0 for v in list(BAT.values()) + list(PIT.values())})
                for src, dst in BAT.items():
                    a[dst] += _num(r.get(src))
                a["pit_inningsPitched"] += _ip(r.get("pitching_IP"))
                for src, dst in PIT.items():
                    if dst == "pit_inningsPitched":
                        continue
                    a[dst] += _num(r.get(src))
        print("  %d: %d juegos finalizados, %d equipo-juego con stats" %
              (season, len(juegos), len(agg)))
        # emitir 2 filas por juego
        for gid, info in juegos.items():
            for lado in ("home", "away"):
                tid = info["%s_id" % lado]
                st = agg.get((gid, tid), {})
                runs = info["%s_score" % lado]
                runs_opp = info["away_score" if lado == "home" else "home_score"]
                fila = {"gamePk": gid, "league": "NPB", "season": season,
                        "game_date": info["fecha"],
                        "team": info[lado], "opp": info["away" if lado == "home" else "home"],
                        "is_home": 1 if lado == "home" else 0,
                        "runs": runs, "runs_opp": runs_opp, "estadio": info["estadio"]}
                fila.update(st)
                filas.append(fila)
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2024)
    ap.add_argument("--hasta", type=int, default=2026)
    args = ap.parse_args()

    print("Bajando NPB %d-%d desde GitHub..." % (args.desde, args.hasta))
    filas = recolectar(args.desde, args.hasta)
    if not filas:
        print("Sin datos NPB."); return

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
    print("\nEscritos %d nuevos NPB (total archivo %d filas) en:\n  %s"
          % (len(nuevos), len(prev) + len(nuevos), OUT))
    print("Fuente: Nippon Baseball Data Repository (github.com/armstjc/Nippon-Baseball-Data-Repository)")


if __name__ == "__main__":
    main()
