# -*- coding: utf-8 -*-
"""
nucleo/linea.py - MOVIMIENTO DE LINEA de un partido (igual para todos los deportes).

Dos fuentes:
  1. apertura -> actual de ESPN/DraftKings (viene dentro de las cuotas del partido)
  2. historial propio: salida/odds_snapshots_<AAAA>.csv (lo llena colectores/snapshot_cuotas.py cada
     3 horas en GitHub Actions). La ultima foto antes del inicio es la linea de cierre.

Que devuelve movimiento(cuotas, serie):
  ml       prob. sin margen del local: apertura, actual, desplazamiento en puntos y hacia quien
  total    linea de apertura, actual y cambio
  spread   linea local de apertura, actual y cambio
  serie    fotos del historial propio (ts, ml_home, ml_away, total, spread_home), mas antigua primero
  fotos    numero de fotos; cierre = True si hay una foto cercana al inicio (menos de 3 horas antes)

La cuota sola no distingue dinero del publico de dinero profesional: para eso hace falta % de tickets
vs handle (feed de pago). Aqui se muestra el movimiento tal cual, sin interpretarlo.
"""
import csv, glob, os, datetime as dt

try:
    from nucleo import io, mercado
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io, mercado

_SNAP = {}


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _nv(a, b):
    x, y = mercado.prob_implicita(a), mercado.prob_implicita(b)
    return x / (x + y)


def _snapshots(directorio=None):
    d = directorio or os.path.join(io.BASE, "salida")
    if d in _SNAP:
        return _SNAP[d]
    por = {}
    for ruta in sorted(glob.glob(os.path.join(d, "odds_snapshots_*.csv"))):
        with open(ruta, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                por.setdefault((r.get("liga"), str(r.get("game_id"))), []).append(r)
    for lst in por.values():
        lst.sort(key=lambda r: r.get("ts_utc") or "")
    _SNAP[d] = por
    return por


def limpiar_cache():
    _SNAP.clear()


def serie(liga, game_id, fecha_utc=None, directorio=None):
    lst = _snapshots(directorio).get((liga, str(game_id))) or []
    out = [{"ts": r.get("ts_utc"), "ml_home": _f(r.get("ml_home")), "ml_away": _f(r.get("ml_away")),
            "total": _f(r.get("total")), "spread_home": _f(r.get("spread_home"))} for r in lst]
    cierre = False
    if out and fecha_utc:
        try:
            ini = dt.datetime.strptime(fecha_utc[:16], "%Y-%m-%dT%H:%M")
            ult = dt.datetime.strptime(out[-1]["ts"][:16], "%Y-%m-%dT%H:%M")
            cierre = 0 <= (ini - ult).total_seconds() <= 3 * 3600
        except (ValueError, TypeError):
            pass
    return out, cierre


def movimiento(c, liga=None, game_id=None, fecha_utc=None, directorio=None):
    """c = cuotas del partido (dict de recolectar_proximos). Siempre devuelve el mismo esquema."""
    c = c or {}
    out = {"ml": None, "total": None, "spread": None, "serie": [], "fotos": 0, "cierre": False,
           "casa": c.get("casa") or ""}
    mh, ma, oh, oa = (_f(c.get(k)) for k in ("ml_home", "ml_away", "ml_home_open", "ml_away_open"))
    if None not in (mh, ma, oh, oa):
        a, b = _nv(oh, oa), _nv(mh, ma)
        d = 100.0 * (b - a)
        out["ml"] = {"home_abre": oh, "away_abre": oa, "home_actual": mh, "away_actual": ma,
                     "p_home_abre": round(a, 4), "p_home_actual": round(b, 4), "desplaza_pts": round(d, 2),
                     "hacia": ("home" if d > 0 else "away") if abs(d) >= 0.05 else "sin_cambio"}
    t0, t1 = _f(c.get("total_open")), _f(c.get("total"))
    if t1 is not None:
        out["total"] = {"abre": t0, "actual": t1, "cambio": None if t0 is None else round(t1 - t0, 2),
                        "over_odds": _f(c.get("over_odds")), "under_odds": _f(c.get("under_odds"))}
    s0, s1 = _f(c.get("spread_home_open")), _f(c.get("spread_home"))
    if s1 is not None:
        out["spread"] = {"abre": s0, "actual": s1, "cambio": None if s0 is None else round(s1 - s0, 2),
                         "home_odds": _f(c.get("spread_home_odds")), "away_odds": _f(c.get("spread_away_odds"))}
    if liga is not None and game_id is not None:
        s, cierre = serie(liga, game_id, fecha_utc, directorio)
        out["serie"], out["fotos"], out["cierre"] = s, len(s), cierre
    return out
