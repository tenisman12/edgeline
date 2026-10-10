# -*- coding: utf-8 -*-
"""
colectores/recolectar_cuotas_sgo.py - cuotas de LMP (y, si se pide, LVBP y LIDOM) desde SportsGameOdds
(https://sportsgameodds.com/docs). The Odds API no cubre esas ligas (salida/sonda_lmp.json, 9-oct-2026).

Pide /v2/events?leagueID=LMP&oddsAvailable=true&includeOpenCloseOdds=true (solo partidos que empiezan en las proximas
--horas), convierte cada evento al MISMO formato de The Odds API (sport "baseball_lmp", bookmakers -> markets h2h /
totals / spreads) y lo MEZCLA en salida/cuotas_casas.json (reemplaza solo los eventos que vinieron de SportsGameOdds).
Tambien agrega las filas sharp a salida/cuotas_sharp_<anio>.csv (CLV, movimiento). Asi todo lo de abajo (nucleo/sharp,
decidir.py, decidir_v2.py, picks_del_dia.py) trata a la LMP igual que a MLB.

Llave: variable de entorno EDGELINE_SGO_KEY (secreto SGO_KEY en GitHub). Sin llave no hace nada.
Presupuesto: cada evento devuelto cuenta como 1 objeto; el plan gratis da 2,500 al mes. Lleva la cuenta del mes en
salida/sgo_creditos.json y no pide si se pasaria de EDGELINE_SGO_PRESUPUESTO (2400 por defecto). Con una foto cada
3 horas (--min-horas 3) y la LMP (unos 5 juegos al dia, ventana de 36 h) son cerca de 64 objetos al dia.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    $env:EDGELINE_SGO_KEY = "<tu llave>"
    python colectores/recolectar_cuotas_sgo.py --ver
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, io, json, os, sys, urllib.parse, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
API = "https://api.sportsgameodds.com/v2/events"
SPORT = {"LMP": "baseball_lmp", "LVBP": "baseball_lvbp", "LIDOM": "baseball_lidom"}
SALIDA = os.path.join(BASE, "salida", "cuotas_casas.json")
CREDITOS = os.path.join(BASE, "salida", "sgo_creditos.json")
# nombres de casa de SportsGameOdds -> los de The Odds API (para que nucleo/sharp reconozca a Pinnacle y las bolsas)
CASA = {"pinnacle": "pinnacle", "draftkings": "draftkings", "fanduel": "fanduel", "betmgm": "betmgm", "caesars": "williamhill_us",
        "bet365": "bet365", "betonline": "betonlineag", "bovada": "bovada", "betrivers": "betrivers", "espnbet": "espnbet",
        "fanatics": "fanatics", "betfair_exchange": "betfair_ex_eu", "unibet": "unibet_eu", "williamhill": "williamhill",
        "lowvig": "lowvig", "mybookie": "mybookieag", "betus": "betus", "circa": "circasports", "hardrockbet": "hardrockbet"}


def _get(params, key):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "User-Agent": "edgeline"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _am(x):
    try:
        return int(round(float(str(x).replace("+", ""))))
    except (TypeError, ValueError):
        return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def convertir(ev, sport):
    """evento de SportsGameOdds -> evento con el formato de The Odds API."""
    th = ((ev.get("teams") or {}).get("home") or {}).get("names") or {}
    ta = ((ev.get("teams") or {}).get("away") or {}).get("names") or {}
    home, away = th.get("long") or th.get("medium"), ta.get("long") or ta.get("medium")
    inicio = (ev.get("status") or {}).get("startsAt")
    if not home or not away or not inicio:
        return None
    casas = {}

    def poner(casa, mk, nombre, precio, punto, desc=None):
        if precio is None:
            return
        c = casas.setdefault(CASA.get(casa, casa), {})
        o = {"name": nombre, "price": precio, "point": punto}
        if desc:
            o["description"] = desc
        c.setdefault(mk, []).append(o)

    for oid, o in (ev.get("odds") or {}).items():
        if o.get("periodID") != "game" or o.get("statID") not in ("points", "runs"):
            continue
        bt, lado, ent = o.get("betTypeID"), o.get("sideID"), o.get("statEntityID")
        for casa, b in (o.get("byBookmaker") or {}).items():
            if b.get("available") is False:
                continue
            precio = _am(b.get("odds"))
            if bt == "ml" and lado in ("home", "away") and ent == lado:
                poner(casa, "h2h", home if lado == "home" else away, precio, None)
            elif bt == "ou" and lado in ("over", "under") and ent == "all":
                poner(casa, "totals", "Over" if lado == "over" else "Under", precio, _num(b.get("overUnder") or o.get("bookOverUnder")))
            elif bt == "ou" and lado in ("over", "under") and ent in ("home", "away"):
                # total por equipo (10-oct-2026, motor de carreras): formato 'team_totals' de The Odds API
                poner(casa, "team_totals", "Over" if lado == "over" else "Under", precio,
                      _num(b.get("overUnder") or o.get("bookOverUnder")), home if ent == "home" else away)
            elif bt == "sp" and lado in ("home", "away") and ent == lado:
                poner(casa, "spreads", home if lado == "home" else away, precio, _num(b.get("spread") or o.get("bookSpread")))
    bks = []
    for casa, mks in casas.items():
        markets = [{"key": k, "outcomes": v} for k, v in mks.items()
                   if (k == "team_totals" and len(v) >= 2) or (k != "team_totals" and len(v) == 2)]
        if markets:
            bks.append({"key": casa, "markets": markets})
    if not bks:
        return None
    t = inicio.replace(".000Z", "Z")
    return {"sport": sport, "id": "sgo_" + str(ev.get("eventID")), "commence_time": t, "home_team": home, "away_team": away,
            "bookmakers": bks, "fuente_api": "sgo"}


def _creditos():
    mes = dt.datetime.utcnow().strftime("%Y-%m")
    try:
        d = json.load(open(CREDITOS, encoding="utf-8"))
    except Exception:
        d = {}
    return d if d.get("mes") == mes else {"mes": mes, "usados": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default=os.environ.get("EDGELINE_SGO_LIGAS", "LMP"))
    ap.add_argument("--horas", type=float, default=36.0, help="solo partidos que empiezan en las proximas N horas")
    ap.add_argument("--ver", action="store_true", help="imprime lo convertido")
    ap.add_argument("--min-horas", type=float, default=3.0, help="no pedir si la ultima foto de SportsGameOdds tiene menos de N horas")
    a = ap.parse_args()
    try:
        g = json.load(open(SALIDA, encoding="utf-8")).get("generado_sgo")
        edad = (dt.datetime.utcnow() - dt.datetime.fromisoformat(g.rstrip("Z"))).total_seconds() / 3600 if g else None
    except Exception:
        edad = None
    if edad is not None and edad < a.min_horas:
        print("Foto de SportsGameOdds de hace %.1f h (< %.1f h): no se piden objetos." % (edad, a.min_horas))
        return 0
    key = os.environ.get("EDGELINE_SGO_KEY")
    if not key:
        print("Sin EDGELINE_SGO_KEY: no se piden cuotas de %s (crea la cuenta en sportsgameodds.com y guarda la llave en el secreto SGO_KEY)." % a.ligas)
        return 0
    tope = int(os.environ.get("EDGELINE_SGO_PRESUPUESTO", "2400"))
    cr = _creditos()
    ahora = dt.datetime.utcnow().replace(microsecond=0)
    hasta = ahora + dt.timedelta(hours=a.horas)
    nuevos = []
    for lg in [x.strip().upper() for x in a.ligas.split(",") if x.strip()]:
        if lg not in SPORT:
            print("liga desconocida para SportsGameOdds:", lg); continue
        cursor = None
        while True:
            if cr["usados"] >= tope:
                print("Presupuesto del mes agotado (%d de %d objetos): no se pide mas." % (cr["usados"], tope)); break
            p = {"leagueID": lg, "oddsAvailable": "true", "includeOpenCloseOdds": "true", "limit": 25,
                 "startsAfter": ahora.isoformat() + "Z", "startsBefore": hasta.isoformat() + "Z"}
            if cursor:
                p["cursor"] = cursor
            try:
                d = _get(p, key)
            except Exception as e:
                print("SportsGameOdds %s: error %s" % (lg, e)); break
            data = d.get("data") or []
            cr["usados"] += len(data)
            for ev in data:
                x = convertir(ev, SPORT[lg])
                if x:
                    nuevos.append(x)
            cursor = d.get("nextCursor")
            if not cursor or not data:
                break
        print("%s: %d eventos con cuotas (objetos usados este mes: %d)" % (lg, sum(1 for x in nuevos if x["sport"] == SPORT[lg]), cr["usados"]))
    os.makedirs(os.path.dirname(CREDITOS), exist_ok=True)
    json.dump(cr, open(CREDITOS, "w", encoding="utf-8"))
    if a.ver:
        for x in nuevos:
            print(json.dumps(x, ensure_ascii=False)[:600])
    if not nuevos:
        return 0
    # mezcla: se quitan los eventos viejos de SportsGameOdds y se ponen los nuevos; lo de The Odds API queda igual
    try:
        prev = json.load(open(SALIDA, encoding="utf-8"))
    except Exception:
        prev = {"generado": None, "eventos": []}
    resto = [e for e in prev.get("eventos") or [] if e.get("fuente_api") != "sgo"]
    ts = ahora.isoformat() + "Z"
    with io.open(SALIDA, "w", encoding="utf-8") as f:
        json.dump({"generado": prev.get("generado") or ts, "generado_sgo": ts, "eventos": resto + nuevos}, f, ensure_ascii=False)
    import recolectar_cuotas as RC
    RC.hist_sharp(nuevos, ts)
    print("cuotas_casas.json: %d eventos de SportsGameOdds mezclados" % len(nuevos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
