# -*- coding: utf-8 -*-
"""
colectores/sonda_lmp.py - revisa que hay de la LMP antes del arranque (corre en Actions: workflow "lmp").

1) MLB Stats API: juegos Final por temporada (oct-feb) para ver que temporadas existen en la fuente.
2) Calendario 2026-27: juegos programados desde el 1 de octubre, con abridor probable cuando lo hay.
3) The Odds API (si hay EDGELINE_ODDS_KEY): deportes de beisbol disponibles (la lista NO gasta creditos).
4) Lo que ya tiene datos/beisbol.csv por temporada.
Escribe salida/sonda_lmp.json.
"""
import csv, json, os, sys, datetime as dt, urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = "https://statsapi.mlb.com/api/v1"


def get(path, **q):
    url = API + path + "?" + urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "edgeline"}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    out = {"generado": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", "fuente": {}, "repo": {}}
    hoy = dt.date.today()
    for y in range(2014, hoy.year + 1):
        try:
            d = get("/schedule", sportId=17, leagueId=132, startDate="%d-10-01" % y, endDate="%d-02-20" % (y + 1),
                    gameType="R,F,D,L,W,C,P")
            fin = sum(1 for x in d.get("dates", []) for g in x.get("games", [])
                      if (g.get("status") or {}).get("abstractGameState") == "Final")
            tot = sum(len(x.get("games", [])) for x in d.get("dates", []))
            out["fuente"][str(y)] = {"final": fin, "programados": tot}
            print("MLB Stats API LMP %d-%d: %d juegos Final (%d en calendario)" % (y, y + 1, fin, tot))
        except Exception as e:
            out["fuente"][str(y)] = {"error": str(e)}
            print("LMP %d: error %s" % (y, e))
    # calendario de la temporada que arranca
    try:
        d = get("/schedule", sportId=17, leagueId=132, startDate="%d-10-01" % hoy.year, endDate="%d-10-25" % hoy.year,
                hydrate="probablePitcher,venue")
        prox = []
        for x in d.get("dates", []):
            for g in x.get("games", []):
                t = g.get("teams") or {}
                prox.append({"fecha": x.get("date"), "gamePk": g.get("gamePk"),
                             "visita": ((t.get("away") or {}).get("team") or {}).get("name"),
                             "local": ((t.get("home") or {}).get("team") or {}).get("name"),
                             "abridor_visita": ((t.get("away") or {}).get("probablePitcher") or {}).get("fullName"),
                             "abridor_local": ((t.get("home") or {}).get("probablePitcher") or {}).get("fullName"),
                             "estadio": (g.get("venue") or {}).get("name")})
        out["calendario_arranque"] = prox
        print("\nCalendario %d (1-25 oct): %d juegos" % (hoy.year, len(prox)))
        for p in prox[:12]:
            print("  %s %s @ %s | %s vs %s" % (p["fecha"], p["visita"], p["local"], p["abridor_visita"], p["abridor_local"]))
    except Exception as e:
        out["calendario_arranque"] = {"error": str(e)}
        print("calendario: error", e)
    # The Odds API: lista de deportes (gratis)
    key = os.environ.get("EDGELINE_ODDS_KEY")
    if key:
        try:
            with urllib.request.urlopen("https://api.the-odds-api.com/v4/sports/?all=true&apiKey=%s" % key, timeout=60) as r:
                sp = json.loads(r.read().decode("utf-8"))
            bb = [{"key": s.get("key"), "titulo": s.get("title"), "activo": s.get("active")} for s in sp
                  if "baseball" in (s.get("key") or "")]
            out["odds_api_beisbol"] = bb
            print("\nThe Odds API, beisbol:", ", ".join("%s (%s)" % (b["key"], "activo" if b["activo"] else "inactivo") for b in bb))
        except Exception as e:
            out["odds_api_beisbol"] = {"error": str(e)}
    else:
        out["odds_api_beisbol"] = "sin llave en este paso"
    # lo que hay en el repo
    ruta = os.path.join(BASE, "datos", "beisbol.csv")
    if os.path.exists(ruta):
        c = {}
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("league") == "LMP":
                    c[r.get("season")] = c.get(r.get("season"), 0) + 1
        out["repo"] = {k: v // 2 for k, v in sorted(c.items())}
        print("\nRepo datos/beisbol.csv LMP por temporada (juegos):", out["repo"])
    os.makedirs(os.path.join(BASE, "salida"), exist_ok=True)
    json.dump(out, open(os.path.join(BASE, "salida", "sonda_lmp.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
