# -*- coding: utf-8 -*-
"""
colectores/recolectar_cuotas_pinnacle.py - cuotas de Pinnacle para LMP y LMB desde su endpoint publico de invitado
(guest.api.arcadia.pinnacle.com, el mismo que usa la pagina de Pinnacle). The Odds API no cubre esas ligas y el plan
gratis de SportsGameOdds tampoco (verificado 12-nov-2026: /v2/leagues solo devolvio MLB).

Ligas (id de Pinnacle, verificados por Alejandro el 12-nov-2026 con /sports/3/leagues?all=true):
    245 Mexican Pacific League -> sport "baseball_lmp" (liga lmp de Edgeline)
    244 Mexican League         -> sport "baseball_lmb" (se guarda; Edgeline todavia no modela LMB)

Que hace en cada corrida:
  1. Pide /leagues/<id>/matchups y /leagues/<id>/markets/straight y los une por matchupId.
  2. Se queda con los partidos que NO han empezado (inicio > ahora) y con las lineas principales del juego completo
     (period 0, sin alternas): ML, run line, total y total por equipo.
  3. Convierte cada partido al MISMO formato de The Odds API (bookmaker "pinnacle", markets h2h / spreads / totals /
     team_totals) y lo MEZCLA en salida/cuotas_casas.json (reemplaza solo los eventos con fuente_api "pinnacle").
     nucleo/sharp reconoce "pinnacle" como la casa sharp: decidir.py, decidir_v2.py, plataforma.py y picks_del_dia.py
     usan la LMP igual que MLB (p_sharp, mezcla con el modelo, EV, CLV, movimiento).
  4. Agrega las filas sharp a salida/cuotas_sharp_<anio>.csv (CLV y apertura/cierre) y TODAS las lineas capturadas,
     con el limite de apuesta, a salida/pinnacle_beisbol_<anio>.csv. La primera captura de un partido es su apertura
     y la ultima antes del inicio es su cierre.

No gasta creditos: se puede correr cada hora. Si Pinnacle bloquea la IP (403/429), deja un aviso y no rompe nada.

Llave: EDGELINE_PINNACLE_KEY (secreto PINNACLE_KEY en GitHub). Es la llave de invitado publica de la pagina de
Pinnacle; va en variable de entorno por la regla 7 de CLAUDE.md.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    $env:EDGELINE_PINNACLE_KEY = "<llave de invitado>"
    python colectores/recolectar_cuotas_pinnacle.py --ver            # captura, guarda y muestra la tabla
    python colectores/recolectar_cuotas_pinnacle.py --ver --no-guardar   # solo muestra
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io, json, os, sys, urllib.error, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
API = "https://guest.api.arcadia.pinnacle.com/0.1"
LIGAS = {"LMP": (245, "baseball_lmp"), "LMB": (244, "baseball_lmb")}
SALIDA = os.path.join(BASE, "salida", "cuotas_casas.json")
LINEAS = os.path.join(BASE, "salida", "pinnacle_beisbol_%s.csv")
COLS = ["ts_utc", "liga", "matchup_id", "inicio_utc", "local", "visita", "mercado", "lado", "equipo", "linea", "momio", "limite"]
TZ = -6   # CDMX


def _get(ruta, key):
    req = urllib.request.Request(API + ruta, headers={
        "X-API-Key": key, "Referer": "https://www.pinnacle.com/", "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) edgeline"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def _iso(s):
    """'2026-11-12T03:30:00Z' (o con +00:00) -> datetime UTC sin tz."""
    s = (s or "").replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    return d.replace(tzinfo=None) - (d.utcoffset() or dt.timedelta(0))


def _limite(m):
    lims = [x.get("amount") for x in (m.get("limits") or []) if isinstance(x, dict) and x.get("amount") is not None]
    return max(lims) if lims else None


def _lado_equipo(m):
    """total por equipo: 'home'/'away' desde el campo side o desde la key (s;0;tt;home)."""
    s = (m.get("side") or "").lower()
    if s in ("home", "away"):
        return s
    k = (m.get("key") or "").lower()
    return "home" if k.endswith("home") else ("away" if k.endswith("away") else None)


def capturar(liga, key, ahora, horas):
    """-> (eventos con formato The Odds API, filas para pinnacle_beisbol_<anio>.csv)"""
    lid, sport = LIGAS[liga]
    juegos = _get("/leagues/%d/matchups" % lid, key)
    lineas = _get("/leagues/%d/markets/straight" % lid, key)
    por_juego = {}
    for m in lineas or []:
        if m.get("period") != 0 or m.get("isAlternate") or (m.get("status") not in (None, "open")):
            continue
        por_juego.setdefault(m.get("matchupId"), []).append(m)
    hasta = ahora + dt.timedelta(hours=horas)
    eventos, filas = [], []
    ts = ahora.isoformat() + "Z"
    for g in juegos or []:
        if g.get("parentId") or g.get("isLive") or g.get("type") not in (None, "matchup"):
            continue
        try:
            ini = _iso(g.get("startTime"))
        except Exception:
            continue
        if ini <= ahora or ini > hasta:
            continue          # ya empezo (linea en vivo) o fuera de la ventana
        eq = {p.get("alignment"): p.get("name") for p in g.get("participants") or []}
        home, away = eq.get("home"), eq.get("away")
        if not home or not away:
            continue
        mks = {}
        for m in por_juego.get(g.get("id"), []):
            tipo, pr, lim = m.get("type"), m.get("prices") or [], _limite(m)
            for p in pr:
                d, precio, pt = p.get("designation"), p.get("price"), p.get("points")
                if precio is None:
                    continue
                equipo = None
                if tipo == "moneyline" and d in ("home", "away"):
                    mks.setdefault("h2h", []).append({"name": home if d == "home" else away, "price": precio, "point": None})
                elif tipo == "spread" and d in ("home", "away"):
                    mks.setdefault("spreads", []).append({"name": home if d == "home" else away, "price": precio, "point": pt})
                elif tipo == "total" and d in ("over", "under"):
                    mks.setdefault("totals", []).append({"name": d.capitalize(), "price": precio, "point": pt})
                elif tipo == "team_total" and d in ("over", "under") and _lado_equipo(m):
                    equipo = home if _lado_equipo(m) == "home" else away
                    mks.setdefault("team_totals", []).append({"name": d.capitalize(), "price": precio, "point": pt,
                                                              "description": equipo})
                else:
                    continue
                filas.append({"ts_utc": ts, "liga": liga.lower(), "matchup_id": g.get("id"), "inicio_utc": ini.isoformat() + "Z",
                              "local": home, "visita": away, "mercado": tipo, "lado": d, "equipo": equipo or "",
                              "linea": "" if pt is None else pt, "momio": precio, "limite": "" if lim is None else lim})
        markets = [{"key": k, "outcomes": v} for k, v in mks.items() if (k == "team_totals" and len(v) >= 2) or len(v) == 2]
        if not markets:
            continue
        eventos.append({"sport": sport, "id": "pin_%s" % g.get("id"), "commence_time": ini.isoformat() + "Z",
                        "home_team": home, "away_team": away, "fuente_api": "pinnacle",
                        "bookmakers": [{"key": "pinnacle", "markets": markets}]})
    return eventos, filas


def mezclar(nuevos, ts):
    """cuotas_casas.json: quita los eventos viejos de Pinnacle y pone los nuevos; lo demas (The Odds API, SGO) queda igual."""
    try:
        prev = json.load(io.open(SALIDA, encoding="utf-8"))
    except Exception:
        prev = {"generado": None, "eventos": []}
    resto = [e for e in prev.get("eventos") or [] if e.get("fuente_api") != "pinnacle"]
    prev["eventos"] = resto + nuevos
    prev["generado"] = prev.get("generado") or ts      # 'generado' es de The Odds API (--min-horas): no se toca
    prev["generado_pinnacle"] = ts
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with io.open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(prev, f, ensure_ascii=False)


def guardar_lineas(filas, ts):
    if not filas:
        return
    ruta = LINEAS % ts[:4]
    existe = os.path.exists(ruta)
    with io.open(ruta, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not existe:
            w.writeheader()
        w.writerows(filas)
    print("%s: +%d lineas" % (ruta, len(filas)))


def ver(eventos):
    def mk(ev, k):
        return next((m["outcomes"] for b in ev["bookmakers"] for m in b["markets"] if m["key"] == k), [])
    print("%-11s %-5s %-50s %6s %6s %-12s %-16s" % ("Hora CDMX", "Liga", "Partido", "ML_vis", "ML_loc", "RL local", "Total O/U"))
    for ev in sorted(eventos, key=lambda e: e["commence_time"]):
        h = (_iso(ev["commence_time"]) + dt.timedelta(hours=TZ)).strftime("%d-%m %H:%M")
        ml = {o["name"]: o["price"] for o in mk(ev, "h2h")}
        sp = {o["name"]: (o["point"], o["price"]) for o in mk(ev, "spreads")}
        to = {o["name"]: (o["point"], o["price"]) for o in mk(ev, "totals")}
        rl = sp.get(ev["home_team"])
        print("%-11s %-5s %-50s %6s %6s %-12s %-16s" % (
            h, ev["sport"].split("_")[-1].upper(), (ev["away_team"] + " @ " + ev["home_team"])[:50],
            ml.get(ev["away_team"], ""), ml.get(ev["home_team"], ""),
            "%s (%s)" % rl if rl else "", "%s %s/%s" % (to["Over"][0], to["Over"][1], to["Under"][1]) if "Over" in to and "Under" in to else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default=os.environ.get("EDGELINE_PINNACLE_LIGAS", "LMP,LMB"))
    ap.add_argument("--horas", type=float, default=48.0, help="solo partidos que empiezan en las proximas N horas")
    ap.add_argument("--ver", action="store_true", help="imprime la tabla de lineas")
    ap.add_argument("--no-guardar", action="store_true", help="no escribe nada (prueba)")
    a = ap.parse_args()
    key = os.environ.get("EDGELINE_PINNACLE_KEY")
    if not key:
        print("::warning::Sin EDGELINE_PINNACLE_KEY: no se piden cuotas de Pinnacle (guardar la llave de invitado en el secreto PINNACLE_KEY).")
        return 0
    ahora = dt.datetime.utcnow().replace(microsecond=0)
    ts = ahora.isoformat() + "Z"
    nuevos, filas = [], []
    for lg in [x.strip().upper() for x in a.ligas.split(",") if x.strip()]:
        if lg not in LIGAS:
            print("liga desconocida para Pinnacle:", lg); continue
        try:
            ev, fl = capturar(lg, key, ahora, a.horas)
        except urllib.error.HTTPError as e:
            print("::warning::Pinnacle %s: HTTP %s (403/429 = bloqueo de la IP; correr desde la PC)" % (lg, e.code)); continue
        except Exception as e:
            print("::warning::Pinnacle %s: error %s" % (lg, e)); continue
        nuevos += ev; filas += fl
        print("%s: %d partidos por empezar con lineas (%d lineas)" % (lg, len(ev), len(fl)))
    if a.ver:
        ver(nuevos)
    if a.no_guardar or not nuevos:
        return 0
    mezclar(nuevos, ts)
    guardar_lineas(filas, ts)
    import recolectar_cuotas as RC
    RC.hist_sharp(nuevos, ts)
    print("cuotas_casas.json: %d eventos de Pinnacle mezclados" % len(nuevos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
