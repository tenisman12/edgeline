# -*- coding: utf-8 -*-
"""
nucleo/motor_puntos.py - MOTOR DE PUNTOS por equipo para la NFL (10-oct-2026). Mismo enfoque que los motores de carreras
(beisbol) y goles (hockey), con lo que la literatura marca como lo mas preciso en NFL (nfelo, ELWAY de Silver, Lopez &
Bliss 2024; resumen en trabajo/minar/2026-10-10_motor_puntos.md):

  puntos_local  = nivel local  + ataque_local  + QB_local  - defensa_visita + descanso + clima
  puntos_visita = nivel visita + ataque_visita + QB_visita - defensa_local  + descanso + clima
  - ataque, defensa y QUARTERBACK TITULAR (nfl_lineas: home_qb_name / away_qb_name) con filtro de Kalman lineal; un QB que
    no se ha visto entra con un valor previo (qb0) y mucha incertidumbre.
  - EPA por partido (epa_pass + epa_rush) entra como segunda observacion del ataque y la defensa (peso we).
  - ventaja de local: los niveles local y visita son promedios con olvido (sigue el cambio de la ventaja de local; en
    juegos divisionales se resta div).
  - descanso: bye (10+ dias) y semana corta (5 o menos), en puntos.
  - viento: el total baja `viento` puntos por mph arriba de 10 (en exteriores).
  - margen ~ Normal(m, sd_m) y total ~ Normal(T, sd_t): ganador, spread y totales con la misma distribucion.
Solo stdlib.
"""
import csv, datetime as dt, json, math, os
from collections import defaultdict

from nucleo import io

RUTA_JSON = ("modelos", "motor_puntos.json")
_CACHE = {}


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def lineas_nfl(base=None):
    ruta = os.path.join(base or io.BASE, "datos", "mercado", "nfl_lineas.csv")
    out = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8-sig") as fh:
            for x in csv.DictReader(fh):
                out[x["game_id"]] = x
    return out


def juegos(liga="NFL", base=None):
    """partidos jugados de americano.csv con lo que trae nfl_lineas (QB, descanso, viento, techo, divisional, lineas)."""
    filas = io.cargar_juegos("americano", liga)
    par = defaultdict(list)
    for r in filas:
        par[str(r.get("gamePk"))].append(r)
    L = lineas_nfl(base) if liga.upper() == "NFL" else {}
    G = []
    for gp, rs in par.items():
        if len(rs) != 2:
            continue
        h = next((x for x in rs if str(x.get("is_home")) in ("1", "1.0", "True")), None)
        a = next((x for x in rs if x is not h), None)
        if not h or not a:
            continue
        ph, pa = _f(h.get("points")), _f(a.get("points"))
        if ph is None or pa is None:
            continue
        x = L.get(gp) or {}
        eh = (_f(h.get("epa_pass")) or 0.0) + (_f(h.get("epa_rush")) or 0.0) if h.get("epa_pass") not in (None, "") else None
        ea = (_f(a.get("epa_pass")) or 0.0) + (_f(a.get("epa_rush")) or 0.0) if a.get("epa_pass") not in (None, "") else None
        G.append(dict(gp=gp, f=(h.get("game_date") or "")[:10], h=h.get("team"), a=a.get("team"), ph=int(ph), pa=int(pa),
                      tipo=h.get("tipo") or x.get("game_type") or "", eh=eh, ea=ea, **extras(x)))
    G.sort(key=lambda g: (g["f"], g["gp"]))
    return G


def extras(x):
    """lo que aporta una fila de nfl_lineas (vale tambien para un partido por jugar)."""
    techo = (x.get("roof") or "").lower()
    return dict(qh=(x.get("home_qb_name") or "").strip() or None, qa=(x.get("away_qb_name") or "").strip() or None,
                rh=_f(x.get("home_rest")), ra=_f(x.get("away_rest")), div=x.get("div_game") == "1",
                viento=(0.0 if techo in ("dome", "closed") else _f(x.get("wind"))),
                neutral=(x.get("location") == "Neutral"),
                spread=_f(x.get("spread_line")), total_l=_f(x.get("total_line")),
                ml_h=_f(x.get("home_moneyline")), ml_a=_f(x.get("away_moneyline")),
                sp_oh=_f(x.get("home_spread_odds")), sp_oa=_f(x.get("away_spread_odds")),
                ov_o=_f(x.get("over_odds")), un_o=_f(x.get("under_odds")))


def _desc(rest, prm):
    if rest is None:
        return 0.0
    if rest >= 10:
        return prm["bye"]
    if rest <= 5:
        return prm["corta"]
    return 0.0


def _medias(nh, na, o, d, q, g, prm, qh_val, qa_val):
    hfa_adj = 0.0
    if g.get("neutral"):
        hfa_adj = -(nh - na) / 2.0
    elif g.get("div"):
        hfa_adj = -prm["div"] / 2.0
    mh = nh + hfa_adj + o[g["h"]] + qh_val - d[g["a"]] + _desc(g.get("rh"), prm)
    ma = na - hfa_adj + o[g["a"]] + qa_val - d[g["h"]] + _desc(g.get("ra"), prm)
    v = g.get("viento")
    if v is not None and v > 10 and prm["viento"]:
        red = prm["viento"] * (v - 10) / 2.0
        mh -= red; ma -= red
    return mh, ma


def correr(G, prm, estado_final=False):
    """filtro de Kalman lineal (puntos). pred[gp] = (puntos local, puntos visita) ANTES de cada juego."""
    q, rho, p0, we, sd, qb0, pq0 = prm["q"], prm["rho"], prm["p0"], prm["we"], prm["sd"], prm["qb0"], prm["pq0"]
    o = defaultdict(float); d = defaultdict(float); Q = {}
    Po = defaultdict(lambda: p0); Pd = defaultdict(lambda: p0); PQ = {}
    ult = {}
    LAM = 0.5 ** (1 / 400.0)
    num = [0.0, 0.0]; den = 0.0
    pred = {}
    for g in G:
        fd = dt.date.fromisoformat(g["f"])
        for e in (g["h"], g["a"]):
            if e in ult and (fd - ult[e]).days > 120:            # temporada nueva
                o[e] *= rho; d[e] *= rho; Po[e] += p0; Pd[e] += p0
            elif e in ult:
                Po[e] += q; Pd[e] += q
        for k in (g.get("qh"), g.get("qa")):
            if k and k not in Q:
                Q[k] = qb0; PQ[k] = pq0
            elif k:
                PQ[k] += q * 0.5
        nh, na = (num[0] / den, num[1] / den) if den > 30 else (23.0, 21.0)
        qhv = Q[g["qh"]] if g.get("qh") else 0.0
        qav = Q[g["qa"]] if g.get("qa") else 0.0
        mh, ma = _medias(nh, na, o, d, Q, g, prm, qhv, qav)
        pred[g["gp"]] = (mh, ma, nh, na)
        obs = [(g["ph"], mh, g["h"], g["a"], g.get("qh"), sd), (g["pa"], ma, g["a"], g["h"], g.get("qa"), sd)]
        if we > 0 and g.get("eh") is not None and g.get("ea") is not None:
            # EPA de la ofensiva: puntos 'que merecio' ~ nivel de la liga + EPA del partido; ruido mayor -> peso menor
            obs += [(nh + g["eh"], mh, g["h"], g["a"], g.get("qh"), sd / math.sqrt(we)),
                    (na + g["ea"], ma, g["a"], g["h"], g.get("qa"), sd / math.sqrt(we))]
        for y, m, at, df, kq, s in obs:
            Pq = PQ[kq] if kq else 0.0
            S = Po[at] + Pd[df] + Pq + s * s
            e = y - m
            ko, kd, kq_ = Po[at] / S, Pd[df] / S, Pq / S
            o[at] += ko * e; d[df] -= kd * e
            Po[at] -= ko * Po[at]; Pd[df] -= kd * Pd[df]
            if kq:
                Q[kq] += kq_ * e; PQ[kq] -= kq_ * PQ[kq]
        if not g.get("neutral"):
            num[0] = LAM * num[0] + g["ph"]; num[1] = LAM * num[1] + g["pa"]; den = LAM * den + 1
        ult[g["h"]] = fd; ult[g["a"]] = fd
        mo = sum(o.values()) / len(o); md = sum(d.values()) / len(d)
        for e in o: o[e] -= mo
        for e in d: d[e] -= md
    if not estado_final:
        return pred
    nh, na = (num[0] / den, num[1] / den) if den > 30 else (23.0, 21.0)
    return pred, {"o": dict(o), "d": dict(d), "Q": dict(Q), "Po": dict(Po), "Pd": dict(Pd), "PQ": dict(PQ),
                  "ult": {k: v.isoformat() for k, v in ult.items()}, "nivel": (nh, na)}


def probs(mh, ma, sd_m, sd_t, spread=None, total=None):
    m, t = mh - ma, mh + ma
    out = {"p_home": _cdf(m / sd_m), "margen": m, "total": t}
    if spread is not None:
        out["p_cubre_home"] = 1 - _cdf((spread - m) / sd_m)        # local cubre si margen > spread_line (linea en margen local)
    if total is not None:
        out["p_over"] = 1 - _cdf((total - t) / sd_t)
    return out


# ------------------------------------------------------------------ produccion
def config(base=None):
    ruta = os.path.join(base or io.BASE, *RUTA_JSON)
    if ruta not in _CACHE:
        try:
            _CACHE[ruta] = json.load(open(ruta, encoding="utf-8"))
        except Exception:
            _CACHE[ruta] = {}
    return _CACHE[ruta]


def cfg_liga(liga="nfl", base=None):
    return (config(base).get("ligas") or {}).get((liga or "nfl").lower())


def estado(liga="nfl", base=None):
    lg = (liga or "nfl").lower()
    k = ("estado", base or io.BASE, lg)
    if k not in _CACHE:
        c = cfg_liga(lg, base)
        G = juegos(lg.upper(), base) if c else []
        _CACHE[k] = None if (not c or len(G) < 300) else dict(correr(G, c["parametros"], estado_final=True)[1], ultimo=G[-1]["f"])
    return _CACHE[k]


def fila_lineas(home, away, fecha, base=None):
    """fila de nfl_lineas para un partido por jugar (QB titular proyectado, descanso, viento, techo, divisional)."""
    for x in lineas_nfl(base).values():
        if x.get("home_team") == home and x.get("away_team") == away and abs(
                (dt.date.fromisoformat(x["gameday"][:10]) - dt.date.fromisoformat(str(fecha)[:10])).days) <= 1:
            return x
    return None


def predecir(home, away, fecha, liga="nfl", qb_home=None, qb_away=None, spread=None, total=None, base=None):
    c = cfg_liga(liga, base); st = estado(liga, base)
    if not c or not st:
        return None
    prm = c["parametros"]
    x = fila_lineas(home, away, fecha, base) or {}
    g = dict(h=home, a=away, **extras(x))
    if qb_home: g["qh"] = qb_home
    if qb_away: g["qa"] = qb_away
    fd = dt.date.fromisoformat(str(fecha)[:10])
    o = defaultdict(float, st["o"]); d = defaultdict(float, st["d"])
    for e in (home, away):
        u = st["ult"].get(e)
        if u and (fd - dt.date.fromisoformat(u)).days > 120:
            o[e] *= prm["rho"]; d[e] *= prm["rho"]
    qv = lambda k: st["Q"].get(k, prm["qb0"]) if k else 0.0
    nh, na = st["nivel"]
    mh, ma = _medias(nh, na, o, d, st["Q"], g, prm, qv(g.get("qh")), qv(g.get("qa")))
    r = probs(mh, ma, c["sd_m"], c["sd_t"], spread, total)
    r.update({"pts_home": round(mh, 1), "pts_away": round(ma, 1), "qb_home": g.get("qh"), "qb_away": g.get("qa"),
              "qb_valor": {"home": round(qv(g.get("qh")), 2), "away": round(qv(g.get("qa")), 2)},
              "aplicar": c.get("aplicar") or {}, "datos_hasta": st["ultimo"], "viento": g.get("viento"),
              "descanso": {"home": g.get("rh"), "away": g.get("ra")}})
    return r


def apilar(liga, clave, p_mercado, z_motor, base=None):
    """apilado con el mercado: logistica sobre [logit p del mercado, (media del motor - linea) / sd]."""
    c = cfg_liga(liga, base)
    w = ((c or {}).get("apilado") or {}).get(clave)
    if not w or p_mercado is None or z_motor is None:
        return None
    lg_ = math.log(min(max(p_mercado, 1e-6), 1 - 1e-6) / (1 - min(max(p_mercado, 1e-6), 1 - 1e-6)))
    return 1 / (1 + math.exp(-(w[0] + w[1] * lg_ + w[2] * z_motor)))
