# -*- coding: utf-8 -*-
"""
NHL AHORA - prediccion express de hockey para hoy (sin correr toda la plataforma).

Jala de la API publica oficial de la NHL (api-web.nhle.com): gratis, sin key,
sin navegador. Baja el historial reciente, arma ELO (basado en goles, con ventaja
local, MOV y regresion por temporada) + tasas de goles a favor/en contra, y predice
los juegos de HOY:

    ganador, probabilidad del local, goles esperados por equipo, total, y over/under
    a la linea estandar (5.5).

Uso (en C:\\Edgeline, tu Python normal - solo usa urllib):
    python nhl_ahora.py                 -> juegos de hoy
    python nhl_ahora.py --fecha 2026-10-01
    python nhl_ahora.py --total 5.5     -> cambia la linea de over/under

No modifica nada de tu plataforma; imprime la tabla en pantalla.
"""
import argparse, json, math, sys, time, datetime as dt
import urllib.request

API = "https://api-web.nhle.com/v1"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# 32 equipos actuales (abreviaturas NHL)
EQUIPOS = ["ANA","BOS","BUF","CGY","CAR","CHI","COL","CBJ","DAL","DET","EDM","FLA",
           "LAK","MIN","MTL","NSH","NJD","NYI","NYR","OTT","PHI","PIT","SJS","SEA",
           "STL","TBL","TOR","VAN","VGK","WSH","WPG","UTA"]

# ELO
BASE_ELO = 1500.0
K = 6.0
HFA = 35.0          # ventaja local en ELO (~0.20-0.25 de prob)
REGR = 0.75         # se conserva 75% al cambiar de temporada
ESCALA = 400.0
LIGA_GF = 3.05      # goles por equipo por juego (se recalibra con los datos)


def get(path):
    req = urllib.request.Request(API + path, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def temporadas_relevantes(hoy):
    """(temporada actual y anterior en formato 20252026)."""
    y = hoy.year
    # la temporada NHL arranca en oct; si estamos antes de agosto, la 'actual' es y-1/y
    ini = y if hoy.month >= 8 else y - 1
    s_act = int("%d%d" % (ini, ini + 1))
    s_prev = int("%d%d" % (ini - 1, ini))
    return [s_prev, s_act]


def bajar_historial(seasons):
    """Juegos finalizados (dedup por id) de las temporadas dadas, via club-schedule-season."""
    juegos = {}
    for season in seasons:
        for eq in EQUIPOS:
            try:
                d = get("/club-schedule-season/%s/%d" % (eq, season))
            except Exception:
                continue
            for g in d.get("games", []):
                estado = g.get("gameState")
                if estado not in ("OFF", "FINAL"):   # solo terminados
                    continue
                gid = g.get("id")
                h = g.get("homeTeam") or {}; a = g.get("awayTeam") or {}
                hs, as_ = h.get("score"), a.get("score")
                if hs is None or as_ is None:
                    continue
                juegos[gid] = {"id": gid, "season": season,
                               "fecha": g.get("gameDate") or (g.get("startTimeUTC") or "")[:10],
                               "home": h.get("abbrev"), "away": a.get("abbrev"),
                               "hs": float(hs), "as": float(as_),
                               "tipo": g.get("gameType")}
            time.sleep(0.05)
    return sorted(juegos.values(), key=lambda x: (x["fecha"], x["id"]))


def entrenar(juegos):
    elo = {e: BASE_ELO for e in EQUIPOS}
    gf = {e: [] for e in EQUIPOS}   # goles a favor recientes
    ga = {e: [] for e in EQUIPOS}
    season_prev = None
    tot_g, n_g = 0.0, 0
    for j in juegos:
        h, a = j["home"], j["away"]
        if h not in elo or a not in elo:
            continue
        if season_prev is not None and j["season"] != season_prev:
            for e in elo:   # regresion a la media entre temporadas
                elo[e] = BASE_ELO + (elo[e] - BASE_ELO) * REGR
        season_prev = j["season"]
        # ELO update (MOV)
        esp_h = 1.0 / (1.0 + 10 ** (-(elo[h] + HFA - elo[a]) / ESCALA))
        res_h = 1.0 if j["hs"] > j["as"] else (0.0 if j["hs"] < j["as"] else 0.5)
        mov = math.log(abs(j["hs"] - j["as"]) + 1)
        delta = K * mov * (res_h - esp_h)
        elo[h] += delta; elo[a] -= delta
        gf[h].append(j["hs"]); ga[h].append(j["as"])
        gf[a].append(j["as"]); ga[a].append(j["hs"])
        tot_g += j["hs"] + j["as"]; n_g += 2
    liga = tot_g / n_g if n_g else LIGA_GF
    return {"elo": elo, "gf": gf, "ga": ga, "liga": liga}


def _tasa(lst, liga, k=12):
    """promedio reciente encogido a la media de liga (Marcel)."""
    if not lst:
        return liga
    v = sum(lst[-40:]) / len(lst[-40:])
    n = len(lst[-40:])
    return (n * v + k * liga) / (n + k)


def _pois(lmbda, kk):
    return math.exp(-lmbda) * lmbda ** kk / math.factorial(kk)


def predecir(M, home, away, linea):
    elo, gf, ga, liga = M["elo"], M["gf"], M["ga"], M["liga"]
    if home not in elo or away not in elo:
        return None
    p_home = 1.0 / (1.0 + 10 ** (-(elo[home] + HFA - elo[away]) / ESCALA))
    # goles esperados: ataque propio x defensa rival, relativo a la liga (Log5 de goles)
    of_h, df_a = _tasa(gf[home], liga), _tasa(ga[away], liga)
    of_a, df_h = _tasa(gf[away], liga), _tasa(ga[home], liga)
    xg_h = (of_h * df_a / liga) * (1 + 0.04)   # +4% local
    xg_a = (of_a * df_h / liga) * (1 - 0.04)
    # total over/under via Poisson (suma de dos Poisson ~ Poisson(xg_h+xg_a))
    lt = xg_h + xg_a
    piso = int(math.floor(linea))
    p_under = sum(_pois(lt, k) for k in range(0, piso + 1))
    p_over = 1 - p_under
    margen = abs(p_home - 0.5)
    conf = "alta" if margen > 0.18 else ("media" if margen > 0.09 else "baja")
    return {"p_home": p_home, "xg_home": xg_h, "xg_away": xg_a, "total": lt,
            "p_over": p_over, "conf": conf}


def juegos_de(fecha):
    d = get("/schedule/%s" % fecha)
    out = []
    for sem in d.get("gameWeek", []):
        if sem.get("date") != fecha:
            continue
        for g in sem.get("games", []):
            h = (g.get("homeTeam") or {}).get("abbrev")
            a = (g.get("awayTeam") or {}).get("abbrev")
            if h and a:
                out.append((a, h, g.get("gameState")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="YYYY-MM-DD (default hoy)")
    ap.add_argument("--total", type=float, default=5.5, help="linea de over/under")
    args = ap.parse_args()
    hoy = dt.date.fromisoformat(args.fecha) if args.fecha else dt.date.today()

    print("Bajando historial NHL (2 temporadas)...")
    seasons = temporadas_relevantes(hoy)
    juegos = bajar_historial(seasons)
    if not juegos:
        print("No baje historial. Revisa tu conexion o el rango de temporadas."); return
    M = entrenar(juegos)
    print("Entrenado con %d juegos. Goles/juego liga: %.2f\n" % (len(juegos), M["liga"]))

    hoy_juegos = juegos_de(hoy.isoformat())
    if not hoy_juegos:
        print("No hay juegos NHL el %s." % hoy.isoformat()); return

    print("NHL - %s   (linea total %.1f)" % (hoy.isoformat(), args.total))
    print("-" * 78)
    print("%-22s %7s %6s %6s %6s %6s  %s" %
          ("PARTIDO (V @ L)", "P(local)", "xGL", "xGV", "TOTAL", "P(over)", "PICK"))
    print("-" * 78)
    for away, home, estado in hoy_juegos:
        p = predecir(M, home, away, args.total)
        if not p:
            print("%-22s  (equipo sin historial: %s/%s)" % (away + " @ " + home, away, home)); continue
        pick = home if p["p_home"] >= 0.5 else away
        ou = "OVER" if p["p_over"] >= 0.5 else "UNDER"
        print("%-22s %6.1f%% %6.2f %6.2f %6.2f %6.1f%%  %s / %s (%s)" %
              (away + " @ " + home, 100 * p["p_home"], p["xg_home"], p["xg_away"],
               p["total"], 100 * p["p_over"], pick, ou, p["conf"]))
    print("-" * 78)
    print("xGL/xGV = goles esperados local/visitante. Conf = margen del favorito.")
    print("Hockey es MUY parejo: acc de ganador ~0.55-0.58; el valor esta en el total y el edge vs cuota.")


if __name__ == "__main__":
    main()
