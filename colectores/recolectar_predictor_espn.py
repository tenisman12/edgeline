# -*- coding: utf-8 -*-
"""
colectores/recolectar_predictor_espn.py - probabilidad de ESPN (BPI / FPI, "predictor") por partido.

Para cada juego de datos/equipos/espn_<liga>_equipos.csv (nfl, ncaafb, nba, ncaamb) pide
  https://sports.core.api.espn.com/v2/sports/<deporte>/leagues/<liga>/events/<id>/competitions/<id>/predictor
y guarda en datos/equipos/espn_predictor.csv: liga, game_id, game_date, local/visita (nombres de ESPN), p_local y p_visita
(gameProjection, %), margen proyectado del local si viene (teamPredPtDiff), matchupquality y lastModified.
Lo ya guardado no se vuelve a pedir (fusion por liga + game_id). Sirve para medir si el BPI/FPI agrega algo al modelo
(tanda 9, trabajo/minar/2026-10-10_tanda9.md). Es contexto: no cambia probabilidades.

    python colectores/recolectar_predictor_espn.py --ligas nfl,ncaafb,nba,ncaamb [--hilos 16] [--max 0]
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, io as _io, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io  # noqa: E402

DEP = {"nfl": "football", "ncaafb": "football", "nba": "basketball", "ncaamb": "basketball"}
LIGA_ESPN = {"nfl": "nfl", "ncaafb": "college-football", "nba": "nba", "ncaamb": "mens-college-basketball"}
URL = "https://sports.core.api.espn.com/v2/sports/%s/leagues/%s/events/%s/competitions/%s/predictor"
COLS = ["liga", "game_id", "game_date", "local", "visita", "p_local", "p_visita", "margen_local", "matchupquality",
        "ultima_modificacion", "estado"]
RUTA = ("datos", "equipos", "espn_predictor.csv")


def _stat(lado, nombre):
    for s in (lado or {}).get("statistics") or []:
        if s.get("name") == nombre:
            return s.get("value")
    return None


def pedir(liga, gid):
    url = URL % (DEP[liga], LIGA_ESPN[liga], gid, gid)
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode("utf-8"))
            h, a = d.get("homeTeam") or {}, d.get("awayTeam") or {}
            ph, pa = _stat(h, "gameProjection"), _stat(a, "gameProjection")
            nombre = d.get("name") or ""
            vis, loc = (nombre.split(" at ") + [""])[:2] if " at " in nombre else ("", "")
            return {"p_local": ph, "p_visita": pa, "margen_local": _stat(h, "teamPredPtDiff"),
                    "matchupquality": _stat(h, "matchupquality") or _stat(a, "matchupquality"),
                    "ultima_modificacion": d.get("lastModified"), "local": loc, "visita": vis,
                    "estado": "ok" if (ph is not None or pa is not None) else "sin_proyeccion"}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"estado": "404"}
            time.sleep(1 + intento)
        except Exception:
            time.sleep(1 + intento)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default="nfl,ncaafb,nba,ncaamb")
    ap.add_argument("--hilos", type=int, default=16)
    ap.add_argument("--max", type=int, default=0, help="maximo de pedidos por liga (0 = todos)")
    a = ap.parse_args()
    ruta = io.ruta(*RUTA)
    hay = {}
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                hay[(r["liga"], r["game_id"])] = r
    for liga in [x.strip() for x in a.ligas.split(",") if x.strip()]:
        fuente = io.ruta("datos", "equipos", "espn_%s_equipos.csv" % liga)
        if not os.path.exists(fuente):
            print("%s: sin %s" % (liga, fuente)); continue
        juegos = {}
        with _io.open(fuente, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                juegos[str(r["game_id"])] = (r.get("game_date") or "")[:10]
        falta = [g for g in sorted(juegos) if (liga, g) not in hay or hay[(liga, g)].get("estado") not in ("ok", "sin_proyeccion", "404")]
        if a.max:
            falta = falta[-a.max:]
        print("%s: %d juegos, faltan %d" % (liga, len(juegos), len(falta)), flush=True)
        t0 = time.time(); n = 0
        with ThreadPoolExecutor(max_workers=a.hilos) as ex:
            for gid, res in zip(falta, ex.map(lambda g: pedir(liga, g), falta)):
                n += 1
                if res is None:
                    continue
                hay[(liga, gid)] = dict(res, liga=liga, game_id=gid, game_date=juegos[gid])
                if n % 2000 == 0:
                    print("  %d / %d (%.0f s)" % (n, len(falta), time.time() - t0), flush=True)
        ok = sum(1 for k, v in hay.items() if k[0] == liga and v.get("estado") == "ok")
        print("  %s: con proyeccion %d" % (liga, ok), flush=True)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with _io.open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for k in sorted(hay):
            w.writerow(hay[k])
    print("escrito", ruta)


if __name__ == "__main__":
    main()
