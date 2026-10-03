# -*- coding: utf-8 -*-
"""
RECOLECTAR PROXIMOS - los partidos de los siguientes dias, de todas tus ligas, desde ESPN.

Por cada partido por jugar trae:
  - equipos, hora, record, abridor/portero probable (si ESPN lo publica),
  - cuotas de DraftKings: moneyline (apertura y cierre), total, spread/run line,
  - contexto (opcional, una llamada extra por partido): lesiones, record ATS, H2H,
    ultimos 5 partidos y el "predictor" pregame de ESPN.

Tenis: ESPN lista torneos; aqui se aplanan a partidos individuales por jugar.

Uso (en C:\\Edgeline):
    python recolectar_proximos.py                      (3 dias, todas las ligas)
    python recolectar_proximos.py --dias 5 --ligas mlb,nfl,premier
    python recolectar_proximos.py --sin-contexto       (mas rapido)

Escribe contexto\\proximos_espn.json (lo lee plataforma.py).
"""
import argparse, io, os, sys, json, time, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recolectar_espn as E

BASE = E.BASE
DEFAULT = ["mlb", "nfl", "ncaafb", "nhl", "nba", "ncaamb", "premier", "laliga", "seriea",
           "bundesliga", "ligue1", "ligamx", "champions", "mls", "atp", "wta"]
SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")
TZ_MX = -6      # Ciudad de Mexico (sin horario de verano)


# ------------------------------------------------------------------ utilidades
def _am(x):
    """'-110' | '+150' | 'EVEN' | 150 -> float (cuota americana) o None."""
    if x is None:
        return None
    s = str(x).strip().upper().replace("+", "")
    if s in ("EVEN", "EV", "PK"):
        return 100.0
    try:
        return float(s)
    except ValueError:
        return None


def _linea(x):
    """'o7' | 'u7.5' | '+1.5' | '-3' -> float."""
    s = str(x if x is not None else "").strip().lower()
    if s[:1] in ("o", "u"):
        s = s[1:]
    try:
        return float(s)
    except ValueError:
        return None


def _dic(x):
    return x if isinstance(x, dict) else {}


def _cierre(bloque, lado, k="close", campo="odds"):
    return _dic(_dic(_dic(bloque).get(lado)).get(k)).get(campo)


def _cuotas(comp):
    # ESPN a veces manda la lista de cuotas con elementos nulos (2-oct-2026: tumbo la corrida completa)
    ods = [o for o in (comp.get("odds") or []) if isinstance(o, dict)]
    if not ods:
        return {}
    od = ods[0]
    prov = _dic(od.get("provider"))
    ml, tot, ps = _dic(od.get("moneyline")), _dic(od.get("total")), _dic(od.get("pointSpread"))
    q = {"casa": prov.get("displayName") or prov.get("name") or "",
         "ml_home": _am(_cierre(ml, "home")), "ml_away": _am(_cierre(ml, "away")),
         "ml_draw": _am(_cierre(ml, "draw")),
         "ml_home_open": _am(_cierre(ml, "home", "open")), "ml_away_open": _am(_cierre(ml, "away", "open")),
         "ml_draw_open": _am(_cierre(ml, "draw", "open")),
         "total": _linea(_cierre(tot, "over", "close", "line")),
         "total_open": _linea(_cierre(tot, "over", "open", "line")),
         "over_odds": _am(_cierre(tot, "over")), "under_odds": _am(_cierre(tot, "under")),
         "spread_home": _linea(_cierre(ps, "home", "close", "line")),
         "spread_home_open": _linea(_cierre(ps, "home", "open", "line")),
         "spread_home_odds": _am(_cierre(ps, "home")), "spread_away_odds": _am(_cierre(ps, "away"))}
    # formato viejo (respaldo)
    if q["ml_home"] is None:
        q["ml_home"] = _am(_dic(od.get("homeTeamOdds")).get("moneyLine"))
    if q["ml_away"] is None:
        q["ml_away"] = _am(_dic(od.get("awayTeamOdds")).get("moneyLine"))
    if q["ml_draw"] is None:
        q["ml_draw"] = _am(_dic(od.get("drawOdds")).get("moneyLine"))
    if q["total"] is None:
        q["total"] = _linea(od.get("overUnder"))
    if q["over_odds"] is None:
        q["over_odds"] = _am(od.get("overOdds"))
    if q["under_odds"] is None:
        q["under_odds"] = _am(od.get("underOdds"))
    return {k: v for k, v in q.items() if v not in (None, "")}


def _equipo(cp):
    t = cp.get("team") or {}
    rec = next((r.get("summary") for r in (cp.get("records") or [])
                if r.get("type") == "total" or r.get("name") == "overall"), None) or cp.get("record")
    probable = rol = None
    for p in cp.get("probables") or []:
        ath = p.get("athlete") or {}
        probable = ath.get("displayName") or ath.get("fullName")
        rol = p.get("abbreviation") or p.get("shortDisplayName")
        if probable:
            break
    rk = cp.get("curatedRank")
    return {"nombre": t.get("displayName") or (cp.get("athlete") or {}).get("displayName"),
            "corto": t.get("shortDisplayName") or t.get("name"), "abrev": t.get("abbreviation"),
            "loc": t.get("location"), "logo": t.get("logo"), "record": rec,
            "probable": probable, "probable_rol": rol,
            "ranking": rk.get("current") if isinstance(rk, dict) else None}


def _evento(ev, liga):
    comp = (ev.get("competitions") or [{}])[0]
    est = ((comp.get("status") or {}).get("type") or {})
    if est.get("state") != "pre":
        return None
    cps = comp.get("competitors") or []
    home = next((c for c in cps if c.get("homeAway") == "home"), None)
    away = next((c for c in cps if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    nota = ((comp.get("notes") or [{}])[0]).get("headline")
    return {"id": str(ev.get("id")), "liga": liga, "tipo": "equipos",
            "fecha_utc": ev.get("date") or comp.get("date"), "estado": est.get("shortDetail"),
            "home": _equipo(home), "away": _equipo(away), "cuotas": _cuotas(comp),
            "nota": nota, "serie": (comp.get("series") or {}).get("summary") or None,
            "pretemporada": ((ev.get("season") or {}).get("type") == 1),
            "neutral": bool(comp.get("neutralSite")), "estadio": (comp.get("venue") or {}).get("fullName")}


def _superficie(torneo, fecha):
    t = (torneo or "").lower()
    if any(k in t for k in ("roland", "french", "clay", "madrid", "rome", "italian", "monte")):
        return "Clay"
    if "wimbledon" in t or "queen" in t or "halle" in t:
        return "Grass"
    m = int(fecha[5:7]) if fecha else 1
    if 4 <= m <= 6:
        return "Clay"
    if m == 7 and not ("us open" in t or "cincinnati" in t or "toronto" in t or "montreal" in t):
        return "Clay"
    return "Hard"


def _tenis_pre(ev, liga):
    out, torneo = [], ev.get("name")
    for g in ev.get("groupings") or []:
        gname = ((g.get("grouping") or {}).get("displayName") or "")
        if "Singles" not in gname:
            continue
        # en torneos combinados ESPN devuelve los dos cuadros en el mismo endpoint: el cuadro manda, no el endpoint
        liga_g = "wta" if "women" in gname.lower() else ("atp" if "men" in gname.lower() else liga)
        for c in g.get("competitions") or []:
            if (((c.get("status") or {}).get("type") or {}).get("state")) != "pre":
                continue
            cps = c.get("competitors") or []
            h = next((x for x in cps if x.get("homeAway") == "home"), None)
            a = next((x for x in cps if x.get("homeAway") == "away"), None)
            if not h or not a:
                continue
            fecha = (c.get("date") or "")[:10]
            slam = any(s in (torneo or "").lower() for s in SLAMS)
            out.append({"id": str(c.get("id")), "liga": liga_g, "tipo": "tenis",
                        "fecha_utc": c.get("date"),
                        "estado": ((c.get("status") or {}).get("type") or {}).get("shortDetail"),
                        "home": _equipo(h), "away": _equipo(a), "cuotas": {},
                        "nota": "%s - %s" % (torneo, (c.get("round") or {}).get("displayName") or ""),
                        "torneo": torneo, "ronda": (c.get("round") or {}).get("displayName"),
                        "cancha": (c.get("venue") or {}).get("court"),
                        "superficie": _superficie(torneo, fecha),
                        "best_of": 5 if (slam and liga_g == "atp") else 3, "superficie_estimada": True})
    return out


# ------------------------------------------------------------------ contexto por partido
def _estado_lesion(it):
    return it.get("status") if isinstance(it.get("status"), str) else \
        ((it.get("type") or {}).get("description") or (it.get("status") or {}).get("name") or "")


def contexto(sport, league, gid, home_ab, away_ab):
    sm = E.summary(sport, league, gid)
    if not sm:
        return {}
    ctx = {}
    inj = {}
    for blk in sm.get("injuries") or []:
        ab = (blk.get("team") or {}).get("abbreviation")
        lado = "home" if ab == home_ab else ("away" if ab == away_ab else None)
        if not lado:
            continue
        lst = []
        for it in blk.get("injuries") or []:
            ath = it.get("athlete") or {}
            pos = ath.get("position")
            lst.append({"jugador": ath.get("displayName") or ath.get("fullName"),
                        "pos": pos.get("abbreviation") if isinstance(pos, dict) else pos,
                        "estado": _estado_lesion(it)})
        inj[lado] = lst[:12]
    if inj:
        ctx["lesiones"] = inj
    ats = {}
    for blk in sm.get("againstTheSpread") or []:
        ab = (blk.get("team") or {}).get("abbreviation")
        lado = "home" if ab == home_ab else ("away" if ab == away_ab else None)
        recs = [(r.get("displayName") or r.get("type") or r.get("name") or "",
                 r.get("displayValue") or r.get("summary") or "") for r in (blk.get("records") or [])]
        recs = [x for x in recs if x[1]]
        if lado and recs:
            ats[lado] = recs[:3]
    if ats:
        ctx["ats"] = ats
    ss = (sm.get("seasonseries") or [None])[0]
    if ss:
        ult = []
        for e in ss.get("events") or []:
            cs = e.get("competitors") or []
            ult.append({"fecha": (e.get("date") or "")[:10],
                        "marcador": " - ".join("%s %s" % ((c.get("team") or {}).get("abbreviation"), c.get("score"))
                                               for c in cs)})
        ctx["h2h"] = {"resumen": ss.get("summary"), "titulo": ss.get("title"), "ultimos": ult[:5]}
    l5 = {}
    for blk in sm.get("lastFiveGames") or []:
        ab = (blk.get("team") or {}).get("abbreviation")
        lado = "home" if ab == home_ab else ("away" if ab == away_ab else None)
        if lado:
            l5[lado] = [{"res": e.get("gameResult"), "score": e.get("score"), "vs": e.get("atVs"),
                         "rival": (e.get("opponent") or {}).get("displayName")} for e in (blk.get("events") or [])][:5]
    if l5:
        ctx["ultimos5"] = l5
    pred = sm.get("predictor") or {}
    try:
        ph = float((pred.get("homeTeam") or {}).get("gameProjection")) / 100.0
        ctx["espn_pred_home"] = round(ph, 4)
    except (TypeError, ValueError):
        pass
    return ctx


# ------------------------------------------------------------------ recoleccion
def recolectar(ligas, dias, con_contexto=True, hoy=None, verbose=True):
    hoy = hoy or dt.date.today()
    fechas = [(hoy + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(dias)]
    juegos, vistos = [], set()
    for lg in ligas:
        if lg not in E.LIGAS:
            if verbose: print("  (salto %s: liga no mapeada)" % lg)
            continue
        sport, league = E.LIGAS[lg]
        n = 0
        for fecha in fechas:
            try:
                d = E.get("%s/%s/%s/scoreboard?dates=%s&limit=500" % (E.SITE, sport, league, fecha))
            except Exception as e:
                if verbose: print("  %s %s: %s" % (lg, fecha, str(e)[:60]))
                continue
            for ev in d.get("events", []):
                try:
                    filas = _tenis_pre(ev, lg) if ev.get("groupings") else [x for x in [_evento(ev, lg)] if x]
                except Exception as e:           # un evento raro de ESPN no debe tumbar toda la corrida
                    print("  %s: evento %s omitido (%s: %s)" % (lg, ev.get("id"), type(e).__name__, str(e)[:80]))
                    continue
                for g in filas:
                    if (g["liga"], g["id"]) in vistos:
                        continue
                    if lg in ("atp", "wta") and g["liga"] != lg:
                        continue                 # ese cuadro se cuenta cuando se recorre su propio endpoint
                    vistos.add((g["liga"], g["id"])); juegos.append(g); n += 1
            time.sleep(0.15)
        if verbose: print("  %-10s %3d partidos por jugar" % (lg, n))
    if con_contexto:
        equipos = [g for g in juegos if g["tipo"] == "equipos"]
        if verbose: print("  contexto (lesiones, ATS, H2H, ultimos 5) de %d partidos ..." % len(equipos))
        for i, g in enumerate(equipos, 1):
            sport, league = E.LIGAS[g["liga"]]
            g["contexto"] = contexto(sport, league, g["id"], g["home"]["abrev"], g["away"]["abrev"])
            time.sleep(0.15)
            if verbose and i % 20 == 0: print("     ... %d/%d" % (i, len(equipos)))
    return juegos


def guardar(juegos, ruta=None):
    ruta = ruta or os.path.join(BASE, "contexto", "proximos_espn.json")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with io.open(ruta, "w", encoding="utf-8") as f:
        json.dump({"generado": dt.datetime.now().isoformat(timespec="seconds"), "partidos": juegos},
                  f, ensure_ascii=False)
    return ruta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=3)
    ap.add_argument("--ligas", help="lista separada por comas (default: todas)")
    ap.add_argument("--sin-contexto", action="store_true")
    a = ap.parse_args()
    ligas = [x.strip() for x in a.ligas.split(",")] if a.ligas else DEFAULT
    print("Partidos por jugar, proximos %d dia(s):" % a.dias)
    juegos = recolectar(ligas, a.dias, not a.sin_contexto)
    print("\n%d partidos. Guardado en: %s" % (len(juegos), guardar(juegos)))


if __name__ == "__main__":
    main()
