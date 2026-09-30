# -*- coding: utf-8 -*-
"""
RECOLECTAR ESPN - una API para TODOS los deportes, TODO lo disponible por partido.

API publica no oficial de ESPN (mismo patron para todos los deportes). Modos:

  scoreboard : partidos + marcador + cuotas inline (rapido, para resultados/CLV).
  juegos     : SUMMARY COMPLETO de cada partido -> guarda el JSON CRUDO (todo lo que
               ESPN tiene: box score, win probability, predictor, cuotas, clima,
               asistencia, lesiones, leaders) EN JSONL, mas una tabla plana de box
               score por equipo. Este es el "todo lo posible por partido".
  lesiones   : reporte de lesiones (el "status" que mueve la linea).
  powerindex : BPI / power index por equipo (para power rank).
  standings  : posiciones.

Cubre lo que faltaba: Liga MX (mex.1), Champions (uefa.champions). Corre en tu maquina
(ESPN esta bloqueada en el entorno de Claude).

Uso:
    python recolectar_espn.py juegos     --liga nba --desde 20241001 --hasta 20250115
    python recolectar_espn.py scoreboard --liga nfl --desde 20240905 --hasta 20250210
    python recolectar_espn.py lesiones   --liga nba
    python recolectar_espn.py powerindex --liga nfl --season 2025
    python recolectar_espn.py standings  --liga premier

Escribe en data_maestra/:
    espn_<liga>_scoreboard.csv
    espn_<liga>_summary.jsonl        (CRUDO, todo por partido)
    espn_<liga>_boxscore.csv         (plano, por equipo-juego)
    espn_<liga>_injuries.csv / _powerindex.csv / _standings.csv
"""
import argparse, csv, io, os, json, time, datetime as dt
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"

LIGAS = {
    "mlb": ("baseball","mlb"), "beisbol": ("baseball","mlb"),
    "nba": ("basketball","nba"), "wnba": ("basketball","wnba"),
    "ncaamb": ("basketball","mens-college-basketball"),
    "nfl": ("football","nfl"), "ncaafb": ("football","college-football"),
    "nhl": ("hockey","nhl"),
    "premier": ("soccer","eng.1"), "laliga": ("soccer","esp.1"),
    "seriea": ("soccer","ita.1"), "bundesliga": ("soccer","ger.1"),
    "ligue1": ("soccer","fra.1"), "ligamx": ("soccer","mex.1"),
    "champions": ("soccer","uefa.champions"), "mls": ("soccer","usa.1"),
    "atp": ("tennis","atp"), "wta": ("tennis","wta"),
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.load(r)

def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return ""

def rango(desde, hasta):
    d0 = dt.datetime.strptime(desde, "%Y%m%d").date()
    d1 = dt.datetime.strptime(hasta, "%Y%m%d").date()
    while d0 <= d1:
        yield d0.strftime("%Y%m%d"); d0 += dt.timedelta(days=1)

def guardar_csv(filas, nombre, fijas):
    if not filas:
        print("  (sin filas para %s)" % nombre); return
    OUT = os.path.join(BASE, "data_maestra", nombre)
    extras = sorted({k for f in filas for k in f if k not in fijas})
    cols = fijas + extras
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("  escritos %d (%d cols) en %s" % (len(filas), len(cols), nombre))


# ---------------- tenis: torneo -> partidos individuales ----------------
def _tenis_partidos(ev, league):
    """aplana los partidos de SINGLES de un torneo (dobles se omiten)."""
    out = []
    torneo = ev.get("name")
    for g in ev.get("groupings") or []:
        tipo = (g.get("grouping") or {}).get("displayName") or ""
        if "Singles" not in tipo:
            continue
        for c in g.get("competitions") or []:
            cps = c.get("competitors") or []
            home = next((x for x in cps if x.get("homeAway") == "home"), None)
            away = next((x for x in cps if x.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            est = ((c.get("status") or {}).get("type") or {})

            def info(x):
                ls = x.get("linescores") or []
                rk = x.get("curatedRank")
                if isinstance(rk, dict):
                    rk = rk.get("current", "")
                return {"nombre": (x.get("athlete") or {}).get("displayName"),
                        "sets": sum(1 for s in ls if s.get("winner")),
                        "games": int(sum(s.get("value") or 0 for s in ls)),
                        "linea": ["%d%s" % (s.get("value") or 0,
                                            ("(%s)" % s["tiebreak"]) if s.get("tiebreak") is not None else "")
                                  for s in ls],
                        "rank": rk}
            h, a = info(home), info(away)
            out.append({"game_id": c.get("id"), "game_date": (c.get("date") or "")[:10],
                        "league": league, "estado": est.get("state"),
                        "torneo": torneo, "ronda": (c.get("round") or {}).get("displayName"),
                        "cancha": (c.get("venue") or {}).get("court"),
                        "home": h["nombre"], "away": a["nombre"],
                        "home_score": h["sets"], "away_score": a["sets"],
                        "home_games": h["games"], "away_games": a["games"],
                        "home_rank": h["rank"], "away_rank": a["rank"],
                        "n_sets": len(home.get("linescores") or []),
                        "marcador_home": " ".join(h["linea"]), "marcador_away": " ".join(a["linea"]),
                        "ganador": h["nombre"] if home.get("winner") else (a["nombre"] if away.get("winner") else "")})
    return out


# ---------------- scoreboard (ligero) ----------------
def scoreboard_dia(sport, league, fecha):
    try:
        d = get("%s/%s/%s/scoreboard?dates=%s&limit=500" % (SITE, sport, league, fecha))
    except Exception:
        return [], []
    filas, ids = [], []
    for ev in d.get("events", []):
        if ev.get("groupings"):                 # tenis: torneo -> categoria -> partidos
            filas += _tenis_partidos(ev, league)
            continue                            # sin ids: no hay summary por partido en tenis
        comp = (ev.get("competitions") or [{}])[0]; ids.append(ev.get("id"))
        cs = comp.get("competitors") or []
        home = next((c for c in cs if c.get("homeAway")=="home"), {})
        away = next((c for c in cs if c.get("homeAway")=="away"), {})
        est = ((comp.get("status") or {}).get("type") or {})
        fila = {"game_id": ev.get("id"), "game_date": (ev.get("date") or "")[:10], "league": league,
                "estado": est.get("state"),
                "home": (home.get("team") or {}).get("abbreviation"),
                "away": (away.get("team") or {}).get("abbreviation"),
                "home_score": _num(home.get("score")), "away_score": _num(away.get("score"))}
        od = (comp.get("odds") or [{}])[0]
        if od:
            fila.update({"spread": od.get("spread",""), "over_under": od.get("overUnder",""),
                         "ml_home": (od.get("homeTeamOdds") or {}).get("moneyLine",""),
                         "ml_away": (od.get("awayTeamOdds") or {}).get("moneyLine",""),
                         "odds_detalle": od.get("details","")})
        filas.append(fila)
    return filas, ids


# ---------------- summary completo (TODO por partido) ----------------
def summary(sport, league, gid):
    try:
        return get("%s/%s/%s/summary?event=%s" % (SITE, sport, league, gid))
    except Exception:
        return None

def _flat_boxscore(sm, gid, fecha, league):
    """aplana boxscore.teams[].statistics a filas por equipo-juego."""
    out = []
    bx = (sm.get("boxscore") or {})
    teams = bx.get("teams") or []
    # marcador desde header
    header = sm.get("header") or {}
    comp = ((header.get("competitions") or [{}])[0])
    score = {}
    for c in comp.get("competitors", []):
        score[(c.get("team") or {}).get("id")] = {"ha": c.get("homeAway"),
                                                  "sc": _num(c.get("score")),
                                                  "ab": (c.get("team") or {}).get("abbreviation")}
    for t in teams:
        tid = (t.get("team") or {}).get("id")
        s = score.get(tid, {})
        fila = {"game_id": gid, "game_date": fecha, "league": league,
                "team": (t.get("team") or {}).get("abbreviation"),
                "is_home": 1 if s.get("ha")=="home" else 0, "score": s.get("sc","")}
        for st in t.get("statistics") or []:
            nom = (st.get("name") or st.get("label") or "").strip()
            if nom:
                fila["st_"+nom] = st.get("displayValue")
        out.append(fila)
    return out

def _winprob_final(sm):
    wp = sm.get("winprobability") or []
    if wp:
        last = wp[-1]
        return last.get("homeWinPercentage")
    pred = sm.get("predictor") or {}
    return (pred.get("homeTeam") or {}).get("gameProjection")


# ---------------- lesiones / powerindex / standings ----------------
def lesiones(sport, league):
    try:
        d = get("%s/%s/%s/injuries" % (SITE, sport, league))
    except Exception as e:
        print("  error:", str(e)[:70]); return []
    filas = []
    for b in d.get("injuries", []):
        team = (b.get("team") or {}).get("abbreviation") or b.get("displayName") or ""
        lst = b.get("injuries") if isinstance(b.get("injuries"), list) else [b]
        for it in lst:
            ath = it.get("athlete") or {}; det = it.get("details") or {}
            pos = ath.get("position")
            filas.append({"league": league, "team": team,
                          "jugador": ath.get("displayName") or ath.get("fullName") or "",
                          "posicion": pos.get("abbreviation","") if isinstance(pos,dict) else "",
                          "estatus": it.get("status") or "", "tipo": det.get("type") or it.get("shortComment") or "",
                          "fecha": (it.get("date") or "")[:10]})
    return filas

def standings(sport, league):
    for u in ("https://site.api.espn.com/apis/v2/sports/%s/%s/standings" % (sport, league),
              "%s/%s/%s/standings" % (SITE, sport, league)):
        try:
            d = get(u)
        except Exception:
            continue
        filas = []
        def walk(node):
            for e in (node.get("entries") or []):
                t = e.get("team") or {}
                row = {"league": league, "team": t.get("abbreviation") or t.get("displayName")}
                for s in e.get("stats") or []:
                    row["st_"+(s.get("name") or s.get("type") or "")] = s.get("displayValue") or s.get("value")
                filas.append(row)
            for c in (node.get("children") or []):
                walk(c.get("standings") or c)
        walk((d.get("standings") or d))
        if filas: return filas
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("que", choices=["scoreboard","juegos","lesiones","powerindex","standings"])
    ap.add_argument("--liga", required=True)
    ap.add_argument("--desde"); ap.add_argument("--hasta"); ap.add_argument("--season")
    args = ap.parse_args()
    if args.liga not in LIGAS:
        print("Liga no mapeada. Opciones:", ", ".join(LIGAS)); return
    sport, league = LIGAS[args.liga]

    if args.que == "lesiones":
        guardar_csv(lesiones(sport, league), "espn_%s_injuries.csv" % args.liga, ["league","team","jugador"]); return
    if args.que == "standings":
        guardar_csv(standings(sport, league), "espn_%s_standings.csv" % args.liga, ["league","team"]); return
    if args.que == "powerindex":
        season = args.season or str(dt.date.today().year)
        try:
            d = get("%s/%s/leagues/%s/seasons/%s/powerindex" % (CORE, sport, league, season))
            filas=[{"league":league,"season":season,"item":json.dumps(x,ensure_ascii=False)[:300]} for x in (d.get("items") or [])]
        except Exception as e:
            print("  powerindex no disponible:", str(e)[:70]); filas=[]
        guardar_csv(filas, "espn_%s_powerindex.csv" % args.liga, ["league","season"]); return

    # scoreboard / juegos por rango
    if not (args.desde and args.hasta):
        hoy = dt.date.today().strftime("%Y%m%d"); args.desde = args.desde or hoy; args.hasta = args.hasta or hoy
    sb, box = [], []
    jsonl_path = os.path.join(BASE, "data_maestra", "espn_%s_summary.jsonl" % args.liga)
    if args.que == "juegos":
        os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
        jf = io.open(jsonl_path, "w", encoding="utf-8")
    n_g = 0
    for fecha in rango(args.desde, args.hasta):
        filas, ids = scoreboard_dia(sport, league, fecha)
        sb += filas
        if args.que == "juegos":
            for gid in ids:
                sm = summary(sport, league, gid)
                if not sm: continue
                jf.write(json.dumps({"game_id": gid, "date": fecha, "summary": sm}, ensure_ascii=False)+"\n")  # CRUDO: todo
                box += _flat_boxscore(sm, gid, fecha, league)
                n_g += 1
                if n_g % 50 == 0: print("   ... %d partidos (summary)" % n_g)
                time.sleep(0.15)
        time.sleep(0.15)
    # ESPN repite el mismo torneo en cada fecha del rango: quita duplicados por partido
    vistos = set(); unicos = []
    for f in sb:
        k = (f.get("game_id"), f.get("game_date"))
        if k in vistos:
            continue
        vistos.add(k); unicos.append(f)
    sb = unicos
    guardar_csv(sb, "espn_%s_scoreboard.csv" % args.liga,
                ["game_id","game_date","league","home","away","home_score","away_score","estado"])
    if args.que == "juegos":
        jf.close()
        print("  CRUDO (todo) en espn_%s_summary.jsonl" % args.liga)
        guardar_csv(box, "espn_%s_boxscore.csv" % args.liga,
                    ["game_id","game_date","league","team","is_home","score"])


if __name__ == "__main__":
    main()
