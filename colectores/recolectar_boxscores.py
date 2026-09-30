# -*- coding: utf-8 -*-
"""
RECOLECTAR BOX SCORES - MLB Stats API (gratis, sin key)

Baja el BOX SCORE COMPLETO por juego (R, H, 2B, 3B, HR, RBI, BB, SO, SB, CS, LOB,
AB, TB, HBP + linea de pitcheo IP/ER/ERA + errores) para tus ligas, desde la
MLB Stats API. Una sola fuente cubre casi todo:

    sportId  1  = MLB
    sportId 31  = NPB (Japon)
    sportId 32  = KBO (Corea)
    sportId 17  = Ligas de Invierno  -> LIDOM, LMP, LVBP (y quiza ABL) por leagueId
    sportId 51  = Internacional

Uso (en C:\\Edgeline):
    python recolectar_boxscores.py --listar
        -> imprime los sports y las ligas de invierno (id + nombre) para mapear
           LIDOM/LMP/LVBP/ABL exacto.

    python recolectar_boxscores.py --liga mlb --desde 2026-04-01 --hasta 2026-09-28
    python recolectar_boxscores.py --liga npb --desde 2026-03-01
    python recolectar_boxscores.py --liga kbo
    python recolectar_boxscores.py --liga invierno --desde 2025-10-01 --hasta 2026-02-01
        -> invierno baja TODAS las ligas bajo sportId 17, etiquetando cada juego
           con su liga (LIDOM/LMP/LVBP/...).

Escribe/actualiza:  data_maestra/baseball_boxscores.csv  (una fila por equipo-juego)
No pisa tu baseball_game_results; es un archivo nuevo, mas rico.

Nota: no requiere API key ni el paquete MLB-StatsAPI (usa la API directo). Si quieres
usar el wrapper, `pip install MLB-StatsAPI`, pero este script no lo necesita.
"""
import argparse, csv, io, json, os, sys, time, datetime as dt
import urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "baseball_boxscores.csv")
API = "https://statsapi.mlb.com/api/v1"
PAUSA = 0.25

# nombre -> (sportId, leagueId, etiqueta). leagueId None = todo el sport.
LIGAS = {
    "mlb":   (1, None, "MLB"),
    "npb":   (31, None, "NPB"),
    "kbo":   (32, None, "KBO"),
    "lmp":   (17, 132, "LMP"),      # Liga Mexicana del Pacifico
    "lvbp":  (17, 135, "LVBP"),     # Liga Venezuela
    "lidom": (17, 131, "LIDOM"),    # Liga Dominicana
    "abl":   (17, 595, "ABL"),      # Australian Baseball League
    "pr":    (17, 133, "LBPRC"),    # Puerto Rico (Roberto Clemente)
}
# grupos utiles
GRUPOS = {
    "invierno": ["lmp", "lvbp", "lidom", "abl"],           # tus ligas de invierno
    "todas":    ["mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl"],
}

# Ya NO se recorta: se extrae TODO lo que la API mande en teamStats
# (bateo/pitcheo/fildeo), con prefijo bat_/pit_/fld_, mas el contexto del juego.


def get(path, **params):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"User-Agent": "Edgeline/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def listar():
    print("SPORTS relevantes:")
    try:
        d = get("/sports")
        for s in d.get("sports", []):
            if s.get("id") in (1, 17, 31, 32, 51):
                print("  sportId=%-3s %-6s %s" % (s.get("id"), s.get("abbreviation", ""), s.get("name")))
    except Exception as e:
        print("  error /sports:", e)
    for sid, nom in ((17, "INVIERNO"), (51, "INTERNACIONAL")):
        print("\nLigas bajo sportId=%d (%s):" % (sid, nom))
        try:
            d = get("/league", sportId=sid)
            for lg in d.get("leagues", []):
                print("  leagueId=%-5s %s" % (lg.get("id"), lg.get("name")))
        except Exception as e:
            print("  error /league:", e)


def ligas_de_invierno():
    """(leagueId, nombre) de todas las ligas bajo sportId 17."""
    try:
        d = get("/league", sportId=17)
        return [(lg.get("id"), lg.get("name")) for lg in d.get("leagues", [])]
    except Exception:
        return []


def schedule(sport_id, d1, d2, league_id=None):
    """gamePks Finales en el rango, con nombre de liga si aplica."""
    juegos = []
    d = get("/schedule", sportId=sport_id, startDate=d1, endDate=d2, leagueId=league_id,
            gameType="R,F,D,L,W,C,P")  # temporada regular + playoffs
    for dia in d.get("dates", []):
        for g in dia.get("games", []):
            estado = (g.get("status") or {}).get("abstractGameState")
            if estado != "Final":
                continue
            juegos.append({
                "gamePk": g.get("gamePk"),
                "fecha": (g.get("officialDate") or (g.get("gameDate") or "")[:10]),
                "season": g.get("season"),
                "home": ((g.get("teams") or {}).get("home") or {}).get("team", {}).get("name"),
                "away": ((g.get("teams") or {}).get("away") or {}).get("team", {}).get("name"),
            })
    return juegos


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return x if x is not None else ""


def parse_info(info):
    """La seccion 'info' del box score trae etiquetas de contexto (clima, viento,
    asistencia, primer pitcheo, duracion, estadio) como pares label/value."""
    ctx = {}
    mapa = {"weather": "clima", "wind": "viento", "att": "asistencia",
            "first pitch": "primer_pitcheo", "t": "duracion", "venue": "estadio"}
    for it in (info or []):
        lab = (it.get("label") or "").strip().lower().rstrip(".")
        val = (it.get("value") or "").strip().rstrip(".")
        if lab in mapa:
            ctx[mapa[lab]] = val
    return ctx


def box(gamePk):
    """Extrae TODO: cada campo de teamStats (bateo/pitcheo/fildeo) + contexto."""
    d = get("/game/%s/boxscore" % gamePk)
    teams = d.get("teams") or {}
    # contexto comun del juego
    ctx = parse_info(d.get("info"))
    ofis = d.get("officials") or []
    hp = next((o.get("official", {}).get("fullName") for o in ofis
               if (o.get("officialType") or "") == "Home Plate"), "")
    ctx["umpire_home"] = hp
    out = {"_ctx": ctx}
    for lado in ("home", "away"):
        t = teams.get(lado) or {}
        st = t.get("teamStats") or {}
        row = {"team": (t.get("team") or {}).get("name")}
        for seccion, pref in (("batting", "bat_"), ("pitching", "pit_"), ("fielding", "fld_")):
            for k, v in (st.get(seccion) or {}).items():
                row[pref + k] = num(v)
        out[lado] = row
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", help="mlb | npb | kbo | invierno | internacional")
    ap.add_argument("--desde", help="YYYY-MM-DD (default: inicio del anio en curso)")
    ap.add_argument("--hasta", help="YYYY-MM-DD (default: hoy)")
    ap.add_argument("--listar", action="store_true", help="lista sports y ligas de invierno")
    args = ap.parse_args()

    if args.listar:
        listar(); return
    liga = (args.liga or "").lower()
    if liga in GRUPOS:
        nombres = GRUPOS[liga]
    elif liga in LIGAS:
        nombres = [liga]
    else:
        print("Falta --liga. Opciones: %s" % ", ".join(list(LIGAS) + list(GRUPOS)))
        print("Ej: --liga mlb  |  --liga lmp  |  --liga invierno  |  --liga todas")
        return

    hoy = dt.date.today()
    d1 = args.desde or ("%d-01-01" % hoy.year)
    d2 = args.hasta or hoy.isoformat()
    objetivos = [LIGAS[n] for n in nombres]   # [(sportId, leagueId, etiqueta), ...]

    filas = []
    for sport_id, league_id, nombre in objetivos:
        try:
            juegos = schedule(sport_id, d1, d2, league_id)
        except Exception as e:
            print("  fallo schedule %s: %s" % (nombre, e)); continue
        print("%-14s %d juegos (%s a %s)" % (nombre, len(juegos), d1, d2))
        for i, g in enumerate(juegos):
            try:
                b = box(g["gamePk"])
            except Exception as e:
                continue
            ctx = b.get("_ctx") or {}
            for lado, rival in (("home", "away"), ("away", "home")):
                r = b[lado]; opp = b[rival]
                fila = {"gamePk": g["gamePk"], "league": nombre, "season": g["season"],
                        "game_date": g["fecha"], "team": r.get("team"), "opp": opp.get("team"),
                        "is_home": 1 if lado == "home" else 0,
                        "runs": r.get("bat_runs"), "runs_opp": opp.get("bat_runs")}
                fila.update(ctx)                 # contexto del juego (clima, viento, etc.)
                fila.update(r)                   # TODOS los campos bat_/pit_/fld_ del equipo
                # ademas: carreras permitidas ya vienen en pit_runs; runs_opp lo confirma
                filas.append(fila)
            if (i + 1) % 50 == 0:
                print("   ... %d/%d" % (i + 1, len(juegos)))
            time.sleep(PAUSA)

    if not filas:
        print("Sin juegos. Revisa el rango de fechas o corre --listar."); return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # union de TODAS las columnas vistas (los campos varian por liga/temporada)
    fijas = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "runs", "runs_opp",
             "clima", "viento", "asistencia", "primer_pitcheo", "duracion", "estadio", "umpire_home"]
    extras = sorted({k for f in filas for k in f if k not in fijas})
    cols = fijas + extras
    # si el archivo ya existe con OTRO conjunto de columnas, se reescribe unificando
    prev = []
    if os.path.exists(OUT):
        with io.open(OUT, encoding="utf-8-sig", errors="replace") as f:
            prev = list(csv.DictReader(f))
        cols = fijas + sorted({k for r in (prev + filas) for k in r if k not in fijas})
    vistos = {(str(r.get("gamePk")), r.get("team")) for r in prev}
    nuevos = [f for f in filas if (str(f["gamePk"]), f.get("team")) not in vistos]
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(prev); w.writerows(nuevos)
    print("\nColumnas por registro: %d" % len(cols))
    print("Escritos %d nuevos (total %d registros equipo-juego) en:\n  %s"
          % (len(nuevos), len(prev) + len(nuevos), OUT))


if __name__ == "__main__":
    main()
