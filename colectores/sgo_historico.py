# -*- coding: utf-8 -*-
"""
colectores/sgo_historico.py - cuotas HISTORICAS (partidos ya jugados) de LMP desde SportsGameOdds, para medir el modelo
contra el mercado de la temporada pasada.

SportsGameOdds guarda historia desde feb-2024 (temporadas LMP 2024-25 y 2025-26) y cuotas de apertura y cierre por casa
desde ene-2026. Segun su FAQ y su pagina de precios, la historia es del plan Pro (tiene prueba gratis); con la llave
gratis el script lo intenta y, si la API no devuelve partidos viejos, lo dice y no rompe nada.

Pide /v2/events?leagueID=LMP&finalized=true&startsAfter=...&startsBefore=...&includeOpenCloseOdds=true por paginas de 50
y escribe una fila por partido y casa (pinnacle, consenso y las demas que vengan) en semillas/lmp_cuotas_sgo.csv:
    fecha, inicio_utc, home, away, casa, ml_home, ml_away, ml_home_open, ml_away_open, total, over, under, total_open, event_id
Momios americanos. Lo ya guardado no se vuelve a pedir (se salta por event_id). Cada evento cuenta como 1 objeto.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    $env:EDGELINE_SGO_KEY = "<llave>"
    python colectores/sgo_historico.py --desde 2024-10-01 --hasta 2026-02-15
En GitHub: Actions -> "lmp cuotas historicas" -> Run workflow (usa el secreto SGO_KEY_HIST o, si no existe, SGO_KEY).
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io, json, os, sys, urllib.error, urllib.parse, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.sportsgameodds.com/v2/events"
SALIDA = os.path.join(REPO, "semillas", "lmp_cuotas_sgo.csv")
COLS = ["fecha", "inicio_utc", "home", "away", "casa", "ml_home", "ml_away", "ml_home_open", "ml_away_open",
        "total", "over", "under", "total_open", "event_id", "liga"]


def _get(params, key):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "User-Agent": "edgeline"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def _am(x):
    try:
        v = int(round(float(str(x).replace("+", ""))))
        return v if v != 0 else None
    except (TypeError, ValueError):
        return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def filas_evento(ev, liga):
    th = ((ev.get("teams") or {}).get("home") or {}).get("names") or {}
    ta = ((ev.get("teams") or {}).get("away") or {}).get("names") or {}
    home, away = th.get("long") or th.get("medium"), ta.get("long") or ta.get("medium")
    inicio = (ev.get("status") or {}).get("startsAt")
    if not home or not away or not inicio:
        return []
    # fecha local de Mexico (UTC-7 en Sinaloa/Sonora; con -7 los juegos nocturnos caen en su dia)
    t = dt.datetime.fromisoformat(inicio.replace("Z", "+00:00"))
    fecha = (t - dt.timedelta(hours=7)).date().isoformat()
    casas = {}

    def poner(casa, campo, v):
        if v is None:
            return
        casas.setdefault(casa, {})[campo] = v

    for o in (ev.get("odds") or {}).values():
        if o.get("periodID") != "game" or o.get("statID") not in ("points", "runs"):
            continue
        bt, lado, ent = o.get("betTypeID"), o.get("sideID"), o.get("statEntityID")
        es_ml = bt == "ml" and lado in ("home", "away") and ent == lado
        es_ou = bt == "ou" and lado in ("over", "under") and ent == "all"
        if not (es_ml or es_ou):
            continue
        # consenso de SportsGameOdds a nivel de la apuesta
        if es_ml:
            poner("consenso", "ml_" + lado, _am(o.get("bookOdds")))
        else:
            poner("consenso", lado, _am(o.get("bookOdds")))
            poner("consenso", "total", _num(o.get("bookOverUnder")))
        for casa, b in (o.get("byBookmaker") or {}).items():
            cierre = b.get("closeOdds") if b.get("closeOdds") is not None else b.get("odds")
            if es_ml:
                poner(casa, "ml_" + lado, _am(cierre))
                poner(casa, "ml_%s_open" % lado, _am(b.get("openOdds")))
            else:
                poner(casa, lado, _am(cierre))
                ln = b.get("closeOverUnder") if b.get("closeOverUnder") is not None else (b.get("overUnder") or o.get("bookOverUnder"))
                poner(casa, "total", _num(ln))
                if lado == "over":
                    poner(casa, "total_open", _num(b.get("openOverUnder")))
    out = []
    for casa, v in casas.items():
        if not (v.get("ml_home") and v.get("ml_away")) and not (v.get("over") and v.get("under")):
            continue
        r = {c: "" for c in COLS}
        r.update({k: v.get(k, "") for k in COLS if k in v})
        r.update(fecha=fecha, inicio_utc=inicio, home=home, away=away, casa=casa, event_id=str(ev.get("eventID")), liga=liga)
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", default="LMP")
    ap.add_argument("--desde", default="2024-10-01")
    ap.add_argument("--hasta", default=dt.date.today().isoformat())
    ap.add_argument("--max-objetos", type=int, default=int(os.environ.get("EDGELINE_SGO_MAX_HIST", "1200")))
    a = ap.parse_args()
    key = os.environ.get("EDGELINE_SGO_KEY")
    if not key:
        print("Sin EDGELINE_SGO_KEY: no se pide nada."); return 0
    previas, vistos = [], set()
    if os.path.exists(SALIDA):
        with io.open(SALIDA, encoding="utf-8-sig", newline="") as f:
            previas = list(csv.DictReader(f))
        vistos = {r["event_id"] for r in previas}
    nuevas, cursor, usados, eventos, viejos = [], None, 0, 0, 0
    while usados < a.max_objetos:
        p = {"leagueID": a.liga, "finalized": "true", "includeOpenCloseOdds": "true", "limit": 50,
             "startsAfter": a.desde + "T00:00:00Z", "startsBefore": a.hasta + "T23:59:59Z"}
        if cursor:
            p["cursor"] = cursor
        try:
            d = _get(p, key)
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode("utf-8", "replace")[:400]
            print("SportsGameOdds respondio %s: %s" % (e.code, cuerpo))
            print("Si dice que el plan no incluye historia: hace falta el plan Pro (prueba gratis) en el secreto SGO_KEY_HIST.")
            break
        except Exception as e:
            print("error:", e); break
        data = d.get("data") or []
        usados += len(data)
        for ev in data:
            eventos += 1
            if str(ev.get("eventID")) in vistos:
                viejos += 1; continue
            nuevas += filas_evento(ev, a.liga)
        cursor = d.get("nextCursor")
        print("  pagina: %d eventos (acumulado %d, objetos usados %d)" % (len(data), eventos, usados), flush=True)
        if not cursor or not data:
            break
    todas = previas + nuevas
    todas.sort(key=lambda r: (r["fecha"], r["home"], r["casa"]))
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with io.open(SALIDA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(todas)
    casas = {}
    for r in nuevas:
        casas[r["casa"]] = casas.get(r["casa"], 0) + 1
    print("%s %s -> %s: %d eventos devueltos (%d ya estaban), %d filas nuevas; casas: %s" % (
        a.liga, a.desde, a.hasta, eventos, viejos, len(nuevas), dict(sorted(casas.items(), key=lambda x: -x[1]))))
    if eventos == 0:
        print("La API no devolvio partidos terminados en ese rango (con el plan gratis es lo esperado).")
    print("archivo:", SALIDA, "(%d filas)" % len(todas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
