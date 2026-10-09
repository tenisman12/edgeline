# -*- coding: utf-8 -*-
"""
PROBAR LIGAS HOCKEY - SHL, Liiga, AHL y DEL.
Prueba desde tu compu que las fuentes de datos y de cuotas respondan, sin gastar creditos
de The Odds API (solo usa /sports, que es gratis). Solo stdlib.

Uso:  python probar_ligas_hockey.py
Escribe: C:\\Edgeline\\salida\\prueba_ligas_hockey.txt
"""
import json, os, urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
KEY = os.environ.get("EDGELINE_ODDS_KEY", "")
OUT = os.path.join(BASE, "salida", "prueba_ligas_hockey.txt")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
lineas = []


def log(t):
    print(t)
    lineas.append(t)


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def probar(nombre, url, resumen):
    try:
        d = get(url)
        log("[OK]    %s -> %s" % (nombre, resumen(d)))
        return d
    except Exception as e:
        log("[FALLA] %s -> %s" % (nombre, e))
        return None


# 1) LIIGA: API oficial (trae goles, periodos, power play y expectedGoals por equipo)
probar("Liiga juegos 2026-27", "https://liiga.fi/api/v2/games?tournament=runkosarja&season=2027",
       lambda d: "%d juegos; campos equipo: %s" % (len(d), ", ".join(sorted((d[0].get("homeTeam") or {}).keys()))[:200]))

# 2) AHL: HockeyTech (mismo sistema que OHL/WHL/QMJHL). Temporada regular 2026-27 = 94
ahl = probar("AHL calendario 2026-27",
             "https://lscluster.hockeytech.com/feed/?feed=modulekit&view=schedule&key=50c2cd9b5e18e390&client_code=ahl&season_id=94",
             lambda d: "%d juegos" % len(((d.get("SiteKit") or {}).get("Schedule")) or []))
if ahl:
    juegos = (ahl.get("SiteKit") or {}).get("Schedule") or []
    jugado = next((g for g in juegos if str(g.get("final")) == "1"), None)
    if jugado:
        gid = jugado.get("game_id") or jugado.get("id")
        probar("AHL boxscore (tiros/porteros) juego %s" % gid,
               "https://lscluster.hockeytech.com/feed/?feed=gc&tab=gamesummary&game_id=%s&key=50c2cd9b5e18e390&client_code=ahl&fmt=json" % gid,
               lambda d: "claves: %s" % ", ".join(list((d.get("GC") or {}).get("Gamesummary", {}).keys())[:25]))

# 3) SHL y DEL: Sofascore (cubre ambas con tiros, porteros y alineaciones)
for nombre, q in (("SHL", "SHL"), ("DEL", "DEL")):
    probar("Sofascore busqueda %s" % nombre,
           "https://api.sofascore.com/api/v1/search/unique-tournaments?q=" + urllib.parse.quote(q),
           lambda d: "; ".join("%s id=%s (%s)" % (r.get("entity", r).get("name"), r.get("entity", r).get("id"),
                                                   (r.get("entity", r).get("category") or {}).get("name"))
                               for r in (d.get("results") or [])[:5]))

# 4) The Odds API: claves activas de hockey (gratis, no gasta creditos)
if KEY:
    probar("The Odds API hockey activas", "https://api.the-odds-api.com/v4/sports/?apiKey=%s" % KEY,
           lambda d: ", ".join(x["key"] + ("" if x.get("active") else " (inactiva)")
                               for x in d if x["key"].startswith("icehockey")))
else:
    log("[AVISO] Sin EDGELINE_ODDS_KEY en esta ventana: no se probo The Odds API")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lineas) + "\n")
print("\nGuardado en", OUT)
