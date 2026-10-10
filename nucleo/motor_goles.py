# -*- coding: utf-8 -*-
"""
nucleo/motor_goles.py - MOTOR DE GOLES por equipo para hockey (NHL, SHL, Liiga, AHL, DEL). 10-oct-2026, mismo enfoque que
nucleo/motor_carreras.py (beisbol).

Goles de TIEMPO REGULAR de cada equipo ~ binomial negativa (r grande = Poisson) con
    log lambda_local  = log(nivel local de la liga) + ataque_local  - defensa_visita - portero_visita + b2b
    log lambda_visita = log(nivel visita de la liga) + ataque_visita - defensa_local - portero_local + b2b
  - ataque, defensa y PORTERO TITULAR (NHL: starter_goalie) con filtro de Kalman extendido; el xG por partido (MoneyPuck en
    NHL, liiga.fi en Liiga) entra como una segunda observacion con peso wx.
  - empate al minuto 60 -> prorroga/shootout: gana el local con la tasa ot_local de la liga.
De esa distribucion salen: ganador, 1X2 a 60 min, total final (con el gol de la prorroga/shootout), totales por equipo,
puck line. Solo stdlib.
"""
import datetime as dt, json, math, os
from collections import defaultdict

from nucleo import io

KMAX = 13
RUTA_JSON = ("modelos", "motor_goles.json")
_CACHE = {}


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def nb_pmf(mu, r, kmax=KMAX):
    if r >= 500:
        v = [math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1)) for k in range(kmax)]
    else:
        p = r / (r + mu)
        v = [math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))
             for k in range(kmax)]
    v[-1] += max(0.0, 1 - sum(v))
    return v


def nb_ll(k, mu, r):
    if r >= 500:
        return -mu + k * math.log(mu) - math.lgamma(k + 1)
    p = r / (r + mu)
    return math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p)


def mercados(lh, la, r, ot, lineas, linea_eq):
    """lh, la: goles esperados en tiempo regular. ot: P(gana el local en prorroga/SO)."""
    ph, pa = nb_pmf(lh, r), nb_pmf(la, r)
    gana = emp = pl = 0.0
    over = {L: 0.0 for L in lineas}
    eqh = eqa = 0.0
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            p = x * y
            if i > j:
                gana += p
                if i - j >= 2:
                    pl += p
            elif i == j:
                emp += p
            extra = 1 if i == j else 0
            for L in lineas:
                if i + j + extra > L:
                    over[L] += p
            if i == j:
                eqh += p * (ot * (i + 1 > linea_eq[0]) + (1 - ot) * (i > linea_eq[0]))
                eqa += p * ((1 - ot) * (j + 1 > linea_eq[1]) + ot * (j > linea_eq[1]))
            else:
                eqh += p * (i > linea_eq[0]); eqa += p * (j > linea_eq[1])
    return {"p_home": gana + ot * emp, "p_reg_home": gana, "p_empate60": emp, "pl_home": pl, "over": over,
            "eq_h": eqh, "eq_a": eqa, "lh": lh, "la": la, "total": lh + la + emp}


def medio(x):
    return math.floor(x) + 0.5


# ------------------------------------------------------------------ juegos
def juegos(liga):
    from modelos import hockey as H
    J = H._juegos(liga)
    X = H._xg_partidos() if (liga or "NHL").upper() == "NHL" else {}
    G = []
    for f, gp, h, a in J:
        gh, ga = _f(h.get("goals")), _f(h.get("goals_opp"))
        if gh is None or ga is None:
            continue
        fin = (h.get("ended_in") or "").strip().upper()
        rh, ra = int(round(gh)), int(round(ga))
        if fin in ("OT", "SO") and rh != ra:            # quitar el gol de la prorroga/shootout: marcador al minuto 60
            if rh > ra: rh -= 1
            else: ra -= 1
        xh = X.get((str(gp), h.get("team"))) or H._xg_fila(h)
        xa = X.get((str(gp), a.get("team"))) or H._xg_fila(a)
        G.append(dict(gp=str(gp), f=f, h=h.get("team"), a=a.get("team"), gh=int(round(gh)), ga=int(round(ga)), rh=rh, ra=ra,
                      fin=fin or None, ph=(h.get("starter_goalie") or "").strip() or None,
                      pa=(a.get("starter_goalie") or "").strip() or None,
                      xh=xh[0] if xh else None, xa=xa[0] if xa else None))
    return G


# ------------------------------------------------------------------ filtro
def correr(G, prm, r_nb, estado_final=False):
    q, rho, p0, wx, port, bo, bd = prm["q"], prm["rho"], prm["p0"], prm["wx"], prm["portero"], prm["b2b_of"], prm["b2b_df"]
    a = defaultdict(float); d = defaultdict(float); gk = defaultdict(float)
    Pa = defaultdict(lambda: p0); Pd = defaultdict(lambda: p0); Pg = defaultdict(lambda: p0)
    ult, ultg = {}, {}
    LAM = 0.5 ** (1 / 800.0)
    num = [0.0, 0.0]; den = 0.0
    otn = [0.0, 0.0]
    pred = {}
    por_dia = defaultdict(list)
    for g in G:
        por_dia[g["f"]].append(g)
    for f in sorted(por_dia):
        fd = dt.date.fromisoformat(f)
        dia = por_dia[f]
        b2b = {}
        for g in dia:
            for e in (g["h"], g["a"]):
                b2b[e] = e in ult and (fd - ult[e]).days == 1
                if e in ult and (fd - ult[e]).days > 60:
                    a[e] *= rho; d[e] *= rho; Pa[e] += p0; Pd[e] += p0
                Pa[e] += q; Pd[e] += q
            if port:
                for k in (g["ph"], g["pa"]):
                    if k:
                        if k in ultg and (fd - ultg[k]).days > 60:
                            gk[k] *= rho; Pg[k] += p0
                        Pg[k] += q
        nh, na = (num[0] / den, num[1] / den) if den > 50 else (3.0, 2.8)
        ot = (otn[0] + 5) / (otn[1] + 10)
        upd = []
        for g in dia:
            gkh = gk[g["ph"]] if (port and g["ph"]) else 0.0
            gka = gk[g["pa"]] if (port and g["pa"]) else 0.0
            eh = math.log(nh) + a[g["h"]] - d[g["a"]] - gka + (bo if b2b[g["h"]] else 0.0) + (bd if b2b[g["a"]] else 0.0)
            ea = math.log(na) + a[g["a"]] - d[g["h"]] - gkh + (bo if b2b[g["a"]] else 0.0) + (bd if b2b[g["h"]] else 0.0)
            lh, la = math.exp(eh), math.exp(ea)
            pred[g["gp"]] = (lh, la, ot)
            upd.append((g, lh, la))
        for g, lh, la in upd:
            for k, lam, at, df, kp, xg in ((g["rh"], lh, g["h"], g["a"], g["pa"] if port else None, g["xh"]),
                                           (g["ra"], la, g["a"], g["h"], g["ph"] if port else None, g["xa"])):
                obs = [(k, 1.0)]
                if wx > 0 and xg is not None:
                    obs.append((xg, wx))
                for val, w in obs:
                    info = w * lam * r_nb / (r_nb + lam)
                    score = w * (val - lam) * r_nb / (r_nb + lam)
                    Pk = Pg[kp] if kp else 0.0
                    S = Pa[at] + Pd[df] + Pk + 1.0 / info
                    z = score / info
                    ka, kd, kg = Pa[at] / S, Pd[df] / S, Pk / S
                    a[at] += ka * z; d[df] -= kd * z
                    Pa[at] -= ka * Pa[at]; Pd[df] -= kd * Pd[df]
                    if kp:
                        gk[kp] -= kg * z; Pg[kp] -= kg * Pg[kp]
            num[0] = LAM * num[0] + g["rh"]; num[1] = LAM * num[1] + g["ra"]; den = LAM * den + 1
            if g["fin"] in ("OT", "SO"):
                otn[0] = 0.995 * otn[0] + (1 if g["gh"] > g["ga"] else 0); otn[1] = 0.995 * otn[1] + 1
            elif g["fin"] == "REG" or (g["fin"] is None and abs(g["gh"] - g["ga"]) != 1):
                pass
            ult[g["h"]] = fd; ult[g["a"]] = fd
            for kp in (g["ph"], g["pa"]):
                if kp:
                    ultg[kp] = fd
        if a:
            ma = sum(a.values()) / len(a); md = sum(d.values()) / len(d)
            for e in list(a): a[e] -= ma
            for e in list(d): d[e] -= md
            if gk:
                mg = sum(gk.values()) / len(gk)
                for e in list(gk): gk[e] -= mg
    if not estado_final:
        return pred
    nh, na = (num[0] / den, num[1] / den) if den > 50 else (3.0, 2.8)
    return pred, {"a": dict(a), "d": dict(d), "gk": dict(gk), "Pa": dict(Pa), "Pd": dict(Pd), "Pg": dict(Pg),
                  "ult": dict(ult), "ultg": dict(ultg), "nivel": (nh, na), "ot": (otn[0] + 5) / (otn[1] + 10)}


# ------------------------------------------------------------------ produccion
def config(base=None):
    ruta = os.path.join(base or io.BASE, *RUTA_JSON)
    if ruta not in _CACHE:
        try:
            _CACHE[ruta] = json.load(open(ruta, encoding="utf-8"))
        except Exception:
            _CACHE[ruta] = {}
    return _CACHE[ruta]


def cfg_liga(liga, base=None):
    return (config(base).get("ligas") or {}).get((liga or "nhl").lower())


def estado(liga, base=None):
    lg = (liga or "nhl").lower()
    k = ("estado", base or io.BASE, lg)
    if k in _CACHE:
        return _CACHE[k]
    c = cfg_liga(lg, base)
    G = juegos(lg.upper()) if c else []
    if not c or len(G) < 300:
        _CACHE[k] = None
        return None
    _, st = correr(G, c["parametros"], c["r_nb"], estado_final=True)
    eh = [g["gh"] for g in G[-1500:]]; ea = [g["ga"] for g in G[-1500:]]
    st.update(ultimo=G[-1]["f"], linea_eq=(medio(sum(eh) / len(eh)), medio(sum(ea) / len(ea))))
    _CACHE[k] = st
    return st


def predecir(liga, home, away, fecha, portero_home=None, portero_away=None, b2b_home=False, b2b_away=False,
             linea_total=None, lineas_equipo=None, base=None):
    lg = (liga or "nhl").lower()
    c = cfg_liga(lg, base); st = estado(lg, base)
    if not c or not st:
        return None
    prm = c["parametros"]; r_nb = c["r_nb"]
    fd = dt.date.fromisoformat(str(fecha)[:10])

    def eq(e):
        av, dv = st["a"].get(e, 0.0), st["d"].get(e, 0.0)
        u = st["ult"].get(e)
        if u is not None and (fd - u).days > 60:
            av *= prm["rho"]; dv *= prm["rho"]
        return av, dv, u is not None

    def gkv(k):
        if not prm["portero"] or not k:
            return 0.0, None
        if k not in st["gk"]:
            return 0.0, False
        v = st["gk"][k]; u = st["ultg"].get(k)
        if u is not None and (fd - u).days > 60:
            v *= prm["rho"]
        return v, True
    ah, dh, okh = eq(home); aa, da, oka = eq(away)
    gh, gh_ok = gkv(portero_home); ga, ga_ok = gkv(portero_away)
    nh, na = st["nivel"]
    eh = math.log(nh) + ah - da - ga + (prm["b2b_of"] if b2b_home else 0.0) + (prm["b2b_df"] if b2b_away else 0.0)
    ea = math.log(na) + aa - dh - gh + (prm["b2b_of"] if b2b_away else 0.0) + (prm["b2b_df"] if b2b_home else 0.0)
    lh, la = math.exp(eh), math.exp(ea)
    leq = tuple(lineas_equipo) if lineas_equipo else st["linea_eq"]
    lineas = [linea_total] if linea_total is not None else []
    mk = mercados(lh, la, r_nb, st["ot"], lineas, leq)
    return {"x_home": round(lh, 2), "x_away": round(la, 2), "total": round(mk["total"], 2), "p_home": round(mk["p_home"], 4),
            "p_60": {"home": round(mk["p_reg_home"], 4), "empate": round(mk["p_empate60"], 4),
                     "away": round(1 - mk["p_reg_home"] - mk["p_empate60"], 4)},
            "p_pl_home": round(mk["pl_home"], 4), "p_over": round(mk["over"][linea_total], 4) if linea_total is not None else None,
            "linea_home": leq[0], "linea_away": leq[1], "p_over_home": round(mk["eq_h"], 4), "p_over_away": round(mk["eq_a"], 4),
            "portero": {"home": {"nombre": portero_home, "valor": round(gh, 3), "con_historial": gh_ok},
                        "away": {"nombre": portero_away, "valor": round(ga, 3), "con_historial": ga_ok}},
            "equipos_con_historial": okh and oka, "aplicar": c.get("aplicar") or {}, "datos_hasta": st["ultimo"]}


def tasa_empate60(liga, n=1500):
    """proporcion de juegos que terminan en prorroga o shootout (empate al minuto 60) en los ultimos n con dato.
    10-oct-2026: ni el modelo de produccion ni el motor le ganan a esta tasa para el empate a 60 min (el modelo dice ~16 %,
    pasa ~22 %; con el motor y un ajuste por liga: Liiga z 0.05, AHL z 0.29 contra la tasa, NHL peor)."""
    lg = (liga or "nhl").lower()
    k = ("empate60", io.BASE, lg)
    if k not in _CACHE:
        G = [g for g in juegos(lg.upper()) if g["fin"] in ("REG", "OT", "SO")][-n:]
        _CACHE[k] = (sum(1 for g in G if g["fin"] in ("OT", "SO")) / len(G), len(G)) if len(G) >= 200 else (None, len(G))
    return _CACHE[k]


def lineas_equipo(liga, n=1500):
    """linea ~promedio de goles de local y de visita en la liga (ultimos n juegos), como en la validacion."""
    lg = (liga or "nhl").lower()
    k = ("lineas_eq", io.BASE, lg)
    if k not in _CACHE:
        G = juegos(lg.upper())[-n:]
        _CACHE[k] = (medio(sum(g["gh"] for g in G) / len(G)), medio(sum(g["ga"] for g in G) / len(G))) if len(G) >= 100 else None
    return _CACHE[k]


def apilar(liga, clave, p_prod, p_motor, base=None):
    c = cfg_liga(liga, base)
    w = ((c or {}).get("apilado") or {}).get(clave)
    if not w or p_prod is None or p_motor is None:
        return None
    lg_ = lambda p: math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6)))
    z = w[0] + w[1] * lg_(p_prod) + w[2] * lg_(p_motor)
    return 1 / (1 + math.exp(-z))


def cuotas_equipo(ev, home):
    """mismo formato que nucleo.motor_carreras.cuotas_equipo (mercado team_totals)."""
    from nucleo import motor_carreras as MC
    return MC.cuotas_equipo(ev, home)
