# -*- coding: utf-8 -*-
"""
PROBAR SHL Y DEL (segunda prueba). Solo stdlib, no gasta creditos.

SHL: stats.swehockey.se (oficial de la federacion sueca). SHL 2026-27 = id 20961.
     Calendario con resultados + pagina de cada juego con tiros, atajadas y porteros.
DEL: busca en las paginas de penny-del.org las direcciones de datos (api/json) que usa el sitio.
Odds: lista las claves de hockey activas en The Odds API (endpoint gratis).

Uso:  python utilidades\\probar_shl_del.py
Escribe: <EDGELINE_BASE>\\salida\\prueba_shl_del.txt
"""
import json, os, re, urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
KEY = os.environ.get("EDGELINE_ODDS_KEY", "")
OUT = os.path.join(BASE, "salida", "prueba_shl_del.txt")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "en,de;q=0.8"}
lineas = []


def log(t):
    print(t)
    lineas.append(t)


def get_txt(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ---------- SHL ----------
try:
    html = get_txt("https://stats.swehockey.se/ScheduleAndResults/Schedule/20961")
    ids = re.findall(r"/Game/Events/(\d+)", html)
    res = re.findall(r">\s*(\d+)\s*-\s*(\d+)\s*<", html)
    log("[OK]    SHL calendario -> %d juegos con liga, %d marcadores leidos" % (len(set(ids)), len(res)))
    if ids:
        g = get_txt("https://stats.swehockey.se/Game/Events/%s" % ids[0])
        tiros = re.findall(r"Shots[^()]{0,200}\(([\d:]+)\)", g)
        porteros = re.findall(r"(\d+\.\s*[^<]{3,40}?)\s*</[^>]+>\s*(?:<[^>]+>\s*)*(\d{1,3},\d{2})\s*%", g)
        log("[OK]    SHL juego %s -> tiros por periodo: %s | porteros: %s" % (ids[0], tiros[:2], porteros[:2]))
except Exception as e:
    log("[FALLA] SHL swehockey -> %s" % e)

# ---------- DEL ----------
encontradas = set()
for url in ("https://www.penny-del.org/", "https://www.penny-del.org/statistik/spielplan",
            "https://www.penny-del.org/spielplan"):
    try:
        html = get_txt(url)
        for u in re.findall(r"""["'](https?://[^"'\s]+|/[^"'\s]+)["']""", html):
            if re.search(r"api|json|feed|hydra|sportradar|hockeydata|/data/", u, re.I) and not re.search(r"\.(png|jpg|svg|css|woff)", u, re.I):
                encontradas.add(u)
        log("[OK]    DEL pagina %s -> %d bytes" % (url, len(html)))
    except Exception as e:
        log("[FALLA] DEL pagina %s -> %s" % (url, e))
log("        DEL direcciones de datos encontradas (%d):" % len(encontradas))
for u in sorted(encontradas)[:40]:
    log("          " + u)

# ---------- Odds ----------
if KEY:
    try:
        d = json.loads(get_txt("https://api.the-odds-api.com/v4/sports/?apiKey=%s" % KEY))
        log("[OK]    Odds hockey -> " + ", ".join(x["key"] + ("" if x.get("active") else " (inactiva)")
                                             for x in d if x["key"].startswith("icehockey")))
    except Exception as e:
        log("[FALLA] Odds -> %s" % e)
else:
    log("[AVISO] Sin EDGELINE_ODDS_KEY en esta ventana")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lineas) + "\n")
print("\nGuardado en", OUT)
