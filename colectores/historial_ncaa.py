# -*- coding: utf-8 -*-
"""
colectores/historial_ncaa.py - resultados de NCAA futbol americano (FBS) y NCAA basquet (D-I) desde ESPN.

Escribe en datos\\americano.csv (liga NCAAFB) y datos\\nba.csv (liga NCAAMB) el MISMO esquema de dos filas por
juego que usan los modelos de NFL y NBA, para que esas ligas tengan prediccion. Solo baja lo nuevo: arranca
2 dias antes del ultimo juego que ya tengas de esa liga; la primera vez baja desde el inicio de 2023.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python colectores\\historial_ncaa.py                      # lo nuevo de las dos ligas
    python colectores\\historial_ncaa.py --solo ncaafb        # una liga
    python colectores\\historial_ncaa.py --desde 20250901 --hasta 20250930
Corre en tu maquina o en GitHub Actions (ESPN esta bloqueada en el entorno de Claude).
"""
import os, sys, csv, io, time, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recolectar_espn as RE

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
CFG = {
    "ncaafb": {"sport": "football", "league": "college-football", "grupo": "80", "archivo": "americano.csv",
               "liga": "NCAAFB", "inicio": "20230826"},
    "ncaamb": {"sport": "basketball", "league": "mens-college-basketball", "grupo": "50", "archivo": "nba.csv",
               "liga": "NCAAMB", "inicio": "20231106"},
}


def temporada(clave, f):
    return f.year if (f.month >= 7 if clave == "ncaafb" else f.month < 8) else (f.year - 1 if clave == "ncaafb" else f.year + 1)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def dia(clave, f):
    """juegos terminados de una fecha -> lista de filas (2 por juego)"""
    c = CFG[clave]
    url = "%s/%s/%s/scoreboard?dates=%s&groups=%s&limit=500" % (RE.SITE, c["sport"], c["league"], f.strftime("%Y%m%d"), c["grupo"])
    d = RE.get(url)
    filas = []
    for ev in d.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if not (((comp.get("status") or {}).get("type") or {}).get("completed")):
            continue
        cs = comp.get("competitors") or []
        h = next((x for x in cs if x.get("homeAway") == "home"), None)
        a = next((x for x in cs if x.get("homeAway") == "away"), None)
        if not h or not a: continue
        ph, pa = num(h.get("score")), num(a.get("score"))
        nh, na = (h.get("team") or {}).get("displayName"), (a.get("team") or {}).get("displayName")
        if None in (ph, pa) or not nh or not na: continue
        gp = "espn_%s" % ev.get("id")
        base = {"gamePk": gp, "league": c["liga"], "season": temporada(clave, f), "game_date": f.isoformat()}
        filas.append(dict(base, team=nh, opp=na, is_home=1, points=int(ph), points_opp=int(pa)))
        filas.append(dict(base, team=na, opp=nh, is_home=0, points=int(pa), points_opp=int(ph)))
    return filas


def ultimo(clave):
    ruta = os.path.join(BASE, "datos", CFG[clave]["archivo"])
    if not os.path.exists(ruta): return None
    mx = None
    with io.open(ruta, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("league") == CFG[clave]["liga"] and r.get("game_date"):
                mx = max(mx or "", r["game_date"])
    return mx


def guardar(clave, nuevas):
    ruta = os.path.join(BASE, "datos", CFG[clave]["archivo"])
    if not nuevas: return 0
    cols, existentes = None, set()
    if os.path.exists(ruta):
        with io.open(ruta, encoding="utf-8-sig", newline="") as fh:
            rd = csv.DictReader(fh); cols = rd.fieldnames
            for r in rd: existentes.add((r["gamePk"], r["team"]))
    nuevas = [r for r in nuevas if (r["gamePk"], r["team"]) not in existentes]
    if not nuevas: return 0
    nuevo = not os.path.exists(ruta) or not cols
    cols = cols or ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "points", "points_opp"]
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with io.open(ruta, "a", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if nuevo: w.writeheader()
        w.writerows(nuevas)
    return len(nuevas)


def correr(clave, desde=None, hasta=None):
    ult = ultimo(clave)
    if desde:
        d0 = dt.datetime.strptime(desde, "%Y%m%d").date()
    elif ult:
        d0 = dt.date.fromisoformat(ult) - dt.timedelta(days=2)
    else:
        d0 = dt.datetime.strptime(CFG[clave]["inicio"], "%Y%m%d").date()
    d1 = dt.datetime.strptime(hasta, "%Y%m%d").date() if hasta else dt.date.today()
    print("%s: desde %s hasta %s (ultimo en tus datos: %s)" % (clave.upper(), d0, d1, ult or "ninguno"))
    acum, n_dias, fallos = [], 0, 0
    f = d0
    while f <= d1:
        try:
            acum += dia(clave, f)
        except Exception as e:
            fallos += 1
            if fallos <= 3: print("   %s: %s" % (f, str(e)[:100]))
        n_dias += 1
        if n_dias % 60 == 0:
            print("   ... %s, %d filas" % (f, len(acum)))
        f += dt.timedelta(days=1); time.sleep(0.12)
    n = guardar(clave, acum)
    print("  %s: %d filas nuevas en datos\\%s%s" % (clave.upper(), n, CFG[clave]["archivo"],
                                                   ("  (%d dias con error de ESPN)" % fallos) if fallos else ""))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="ncaafb,ncaamb")
    ap.add_argument("--desde"); ap.add_argument("--hasta")
    a = ap.parse_args()
    for c in [x.strip() for x in a.solo.split(",") if x.strip()]:
        if c in CFG: correr(c, a.desde, a.hasta)
        else: print("liga desconocida:", c)


if __name__ == "__main__":
    main()
