# -*- coding: utf-8 -*-
"""
colectores/recolectar_cuotas_espn.py - cuotas HISTORICAS por partido desde ESPN (core API, endpoint /odds), para medir si
elegir al ganador a cuota decente deja dinero (trabajo/minar/2026-10-10_ganador_cuota.md) en los deportes que no tienen
otra fuente de cuotas viejas.

Para cada juego de datos/equipos/espn_<liga>_equipos.csv (nfl, ncaafb, nba, ncaamb) pide
  https://sports.core.api.espn.com/v2/sports/<deporte>/leagues/<liga>/events/<id>/competitions/<id>/odds
y guarda, por casa que traiga moneyline (DraftKings, ESPN BET, consenso...): moneyline local/visita (la que muestra ESPN al
final = cierre), apertura y cierre si vienen, spread, total y sus precios. Salida datos/mercado/espn_cuotas.csv.
Lo ya guardado no se vuelve a pedir (liga + game_id).

    python colectores/recolectar_cuotas_espn.py --ligas nba,ncaamb,ncaafb,nfl [--hilos 16] [--max 0]
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, io as _io, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io  # noqa: E402

DEP = {"nfl": "football", "ncaafb": "football", "nba": "basketball", "ncaamb": "basketball", "nhl": "hockey", "mlb": "baseball"}
LIGA_ESPN = {"nfl": "nfl", "ncaafb": "college-football", "nba": "nba", "ncaamb": "mens-college-basketball", "nhl": "nhl", "mlb": "mlb"}
# NHL y MLB no tienen datos/equipos/espn_<liga>_equipos.csv: los juegos salen del scoreboard de ESPN dia por dia y se guardan
# en datos/equipos/espn_<liga>_juegos.csv (game_id, game_date, local, visita) para casarlos con el modelo.
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/%s/%s/scoreboard?dates=%s"
MESES = {"nhl": (10, 11, 12, 1, 2, 3, 4, 5, 6), "mlb": (3, 4, 5, 6, 7, 8, 9, 10, 11)}
URL = "https://sports.core.api.espn.com/v2/sports/%s/leagues/%s/events/%s/competitions/%s/odds"
COLS = ["liga", "game_id", "game_date", "casa", "ml_home", "ml_away", "ml_home_open", "ml_away_open", "ml_home_close",
        "ml_away_close", "spread_home", "total", "over", "under", "total_open", "estado"]
RUTA = ("datos", "mercado", "espn_cuotas.csv")


def _am(x):
    """'+150' / '-170' / 150 / {'american': '+150'} -> int americano o None."""
    if isinstance(x, dict):
        x = x.get("american", x.get("value"))
    if x in (None, "", "EVEN", "even"):
        return 100 if x in ("EVEN", "even") else None
    try:
        v = int(round(float(str(x).replace("+", ""))))
        return v if abs(v) >= 100 else None
    except ValueError:
        return None


def _fila(it):
    h, a = it.get("homeTeamOdds") or {}, it.get("awayTeamOdds") or {}
    mh, ma = _am(h.get("moneyLine")), _am(a.get("moneyLine"))
    oh, oa = _am(((h.get("open") or {}).get("moneyLine"))), _am(((a.get("open") or {}).get("moneyLine")))
    ch, ca = _am(((h.get("close") or {}).get("moneyLine"))), _am(((a.get("close") or {}).get("moneyLine")))
    if mh is None and ch is None and oh is None:
        return None
    to = (it.get("open") or {}).get("total") or {}
    tov = to.get("alternateDisplayValue") or to.get("american") if isinstance(to, dict) else None
    try:
        tov = float(str(tov).lstrip("ou")) if tov not in (None, "") else None
    except ValueError:
        tov = None
    return {"casa": ((it.get("provider") or {}).get("name") or "").strip(), "ml_home": mh, "ml_away": ma, "ml_home_open": oh,
            "ml_away_open": oa, "ml_home_close": ch, "ml_away_close": ca, "spread_home": it.get("spread"),
            "total": it.get("overUnder"), "over": it.get("overOdds"), "under": it.get("underOdds"), "total_open": tov}


def pedir(liga, gid):
    url = URL % (DEP[liga], LIGA_ESPN[liga], gid, gid)
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode("utf-8"))
            filas = [f for f in (_fila(it) for it in (d.get("items") or [])) if f]
            return filas or [{"estado": "sin_cuotas"}]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return [{"estado": "404"}]
            time.sleep(1 + intento)
        except Exception:
            time.sleep(1 + intento)
    return None


def juegos_scoreboard(liga, desde):
    """{game_id: fecha} desde el scoreboard de ESPN; guarda datos/equipos/espn_<liga>_juegos.csv (incremental)."""
    import datetime as dt
    ruta = io.ruta("datos", "equipos", "espn_%s_juegos.csv" % liga)
    hay = {}
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                hay[r["game_id"]] = r
    fechas_hechas = {r["consultado"] for r in hay.values()}
    d0 = dt.date.fromisoformat(desde); hoy = dt.date.today()
    dias = []
    while d0 <= hoy:
        if d0.month in MESES[liga] and (d0.isoformat() not in fechas_hechas or (hoy - d0).days < 3):
            dias.append(d0)
        d0 += dt.timedelta(days=1)
    def uno(d):
        url = SCOREBOARD % (DEP[liga], liga, d.strftime("%Y%m%d"))
        for intento in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    return d, json.loads(r.read().decode("utf-8"))
            except Exception:
                time.sleep(1 + intento)
        return d, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        for d, js in ex.map(uno, dias):
            for ev in (js or {}).get("events") or []:
                comp = (ev.get("competitions") or [{}])[0]
                eq = {c.get("homeAway"): ((c.get("team") or {}).get("displayName") or "") for c in comp.get("competitors") or []}
                hay[str(ev.get("id"))] = {"game_id": str(ev.get("id")), "game_date": (ev.get("date") or "")[:10], "local": eq.get("home", ""),
                                          "visita": eq.get("away", ""), "consultado": d.isoformat()}
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with _io.open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["game_id", "game_date", "local", "visita", "consultado"])
        w.writeheader()
        for k in sorted(hay):
            w.writerow(hay[k])
    print("%s: %d juegos en el scoreboard (%d dias consultados)" % (liga, len(hay), len(dias)), flush=True)
    return {k: v["game_date"] for k, v in hay.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default="nba,ncaamb,ncaafb,nfl")
    ap.add_argument("--hilos", type=int, default=16)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--desde", default="2021-10-01", help="NHL/MLB: primer dia del scoreboard")
    a = ap.parse_args()
    ruta = io.ruta(*RUTA)
    hay = {}
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                hay.setdefault((r["liga"], r["game_id"]), []).append(r)
    for liga in [x.strip() for x in a.ligas.split(",") if x.strip()]:
        if liga in MESES:
            juegos = juegos_scoreboard(liga, a.desde)
        else:
            fuente = io.ruta("datos", "equipos", "espn_%s_equipos.csv" % liga)
            if not os.path.exists(fuente):
                print("%s: sin %s" % (liga, fuente)); continue
            juegos = {}
            with _io.open(fuente, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    juegos[str(r["game_id"])] = (r.get("game_date") or "")[:10]
        falta = [g for g in sorted(juegos) if (liga, g) not in hay]
        if a.max:
            falta = falta[-a.max:]
        print("%s: %d juegos, faltan %d" % (liga, len(juegos), len(falta)), flush=True)
        t0 = time.time(); n = 0
        with ThreadPoolExecutor(max_workers=a.hilos) as ex:
            for gid, res in zip(falta, ex.map(lambda g: pedir(liga, g), falta)):
                n += 1
                if res is None:
                    continue
                hay[(liga, gid)] = [dict(x, liga=liga, game_id=gid, game_date=juegos[gid], estado=x.get("estado", "ok")) for x in res]
                if n % 2000 == 0:
                    print("  %d / %d (%.0f s)" % (n, len(falta), time.time() - t0), flush=True)
        ok = sum(1 for k, v in hay.items() if k[0] == liga and any(x.get("estado") == "ok" for x in v))
        print("  %s: con cuotas %d" % (liga, ok), flush=True)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with _io.open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for k in sorted(hay):
            for x in hay[k]:
                w.writerow(x)
    print("escrito", ruta)


if __name__ == "__main__":
    main()
