# -*- coding: utf-8 -*-
"""
RECOLECTAR HOCKEY (ENRIQUECIDO) - NHL, api-web.nhle.com, toda la data por partido.

Baja goles + TIROS (sog), power play, faltas (pim), hits, bloqueos, % de faceoffs, y
el SAVE% del portero titular por equipo. Con esto el modelo puede usar tiros (proxy de
xG) y el ajuste real por portero, no solo goles.

Es mas lento que la version simple porque pide el boxscore de CADA juego. Solo stdlib.

Uso (en tu compu):
    python recolectar_hockey.py --desde 20242025 --hasta 20262027
    python recolectar_hockey.py --simple      (solo goles, rapido, como antes)
Escribe:  data_maestra/hockey_games.csv   (copia a datos/hockey.csv)
"""
import argparse, csv, io, os, json, time
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "hockey_games.csv")
API = "https://api-web.nhle.com/v1"
EQUIPOS = ["ANA","BOS","BUF","CGY","CAR","CHI","COL","CBJ","DAL","DET","EDM","FLA",
           "LAK","MIN","MTL","NSH","NJD","NYI","NYR","OTT","PHI","PIT","SJS","SEA",
           "STL","TBL","TOR","VAN","VGK","WSH","WPG","UTA"]


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def bajar_juegos(seasons):
    juegos = {}
    for season in seasons:
        for eq in EQUIPOS:
            try:
                d = get("/club-schedule-season/%s/%s" % (eq, season))
            except Exception:
                continue
            for g in d.get("games", []):
                if g.get("gameState") not in ("OFF", "FINAL"):
                    continue
                if g.get("gameType") == 1:      # pretemporada: no cuenta para el ELO ni para la plataforma
                    continue
                gid = g.get("id")
                h = g.get("homeTeam") or {}; a = g.get("awayTeam") or {}
                if h.get("score") is None or a.get("score") is None:
                    continue
                juegos[gid] = {"id": gid, "season": season,
                               "fecha": g.get("gameDate") or (g.get("startTimeUTC") or "")[:10],
                               "home": h.get("abbrev"), "away": a.get("abbrev"),
                               "hs": float(h["score"]), "as": float(a["score"])}
            time.sleep(0.05)
    return sorted(juegos.values(), key=lambda x: (x["fecha"], x["id"]))


def _n(x):
    try:
        return float(str(x).replace("%", ""))
    except (TypeError, ValueError):
        return ""


def enriquecer(gid):
    """team stats + save% del portero titular, por lado. {} si falla."""
    try:
        d = get("/gamecenter/%s/boxscore" % gid)
    except Exception:
        return {}
    out = {"home": {}, "away": {}}
    # team stats
    for t in d.get("teamGameStats", []) or []:
        cat = t.get("category"); hv, av = t.get("homeValue"), t.get("awayValue")
        if cat in ("sog", "pim", "hits", "blockedShots", "faceoffWinningPctg", "powerPlayPctg"):
            out["home"]["h_" + cat] = _n(hv); out["away"]["h_" + cat] = _n(av)
    # portero titular (el de mas minutos / mas tiros enfrentados)
    pbg = d.get("playerByGameStats") or {}
    for lado, key in (("home", "homeTeam"), ("away", "awayTeam")):
        gks = (pbg.get(key) or {}).get("goalies") or []
        if gks:
            g0 = max(gks, key=lambda g: _n(g.get("shotsAgainst") or 0) or 0)
            sp = g0.get("savePctg")
            out[lado]["goalie_sv"] = _n(sp) if sp not in (None, "") else ""
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="20242025"); ap.add_argument("--hasta", default="20262027")
    ap.add_argument("--simple", action="store_true", help="solo goles (rapido)")
    ap.add_argument("--conocidos", help="CSV de datos\\ con juegos ya bajados: no los vuelve a pedir (modo diario)")
    args = ap.parse_args()
    y0 = int(args.desde[:4]); y1 = int(args.hasta[:4])
    seasons = ["%d%d" % (y, y + 1) for y in range(y0, y1 + 1)]

    print("Bajando NHL %s ..." % ", ".join(seasons))
    juegos = bajar_juegos(seasons)
    if not juegos:
        print("Sin juegos."); return
    if args.conocidos and os.path.exists(args.conocidos):
        with io.open(args.conocidos, encoding="utf-8-sig", newline="") as fh:
            ya = {str(r.get("gamePk")) for r in csv.DictReader(fh)}
        antes = len(juegos)
        juegos = [g for g in juegos if str(g["id"]) not in ya]
        print("  %d juegos en calendario, %d ya estaban en datos, %d nuevos" % (antes, antes - len(juegos), len(juegos)))
        if not juegos:
            print("Nada nuevo que bajar."); return

    filas = []
    for i, g in enumerate(juegos):
        rich = {} if args.simple else enriquecer(g["id"])
        if not args.simple:
            time.sleep(0.08)
            if (i + 1) % 200 == 0:
                print("   ... %d/%d" % (i + 1, len(juegos)))
        for lado, rival in (("home", "away"), ("away", "home")):
            fila = {"gamePk": g["id"], "league": "NHL", "season": g["season"], "game_date": g["fecha"],
                    "team": g[lado], "opp": g[rival], "is_home": 1 if lado == "home" else 0,
                    "goals": g["hs"] if lado == "home" else g["as"],
                    "goals_opp": g["as"] if lado == "home" else g["hs"]}
            fila.update(rich.get(lado, {}))
            for k, v in (rich.get(rival, {}) or {}).items():
                fila[k + "_opp"] = v
            filas.append(fila)

    fijas = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "goals", "goals_opp"]
    extras = sorted({k for f in filas for k in f if k not in fijas})
    cols = fijas + extras
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("\nEscritos %d equipo-juego, %d columnas, en:\n  %s" % (len(filas), len(cols), OUT))
    if not args.simple:
        print("Ahora trae tiros, PP, hits, faceoffs y save%% del portero. Copia a datos\\hockey.csv")


if __name__ == "__main__":
    main()
