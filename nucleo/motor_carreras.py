# -*- coding: utf-8 -*-
"""
nucleo/motor_carreras.py - MOTOR DE CARRERAS por equipo (beisbol). Aprobado por Alejandro el 10-oct-2026 ("aplica ya todo
lo relevante, todo lo que abone a una mejor decision") despues de utilidades/motor_carreras.py
(trabajo/minar/2026-10-10_motor_carreras.md).

Cada equipo tiene ATAQUE y DEFENSA que se actualizan partido a partido (filtro de Kalman extendido sobre la binomial
negativa). Con el abridor (LMP, NPB) y el parque/clima salen las carreras esperadas de cada lado; de ahi, con la misma
distribucion, el total, los totales por equipo, la run line y el ganador.

Que se usa en produccion (modelos/motor_carreras.json -> "aplicar", decidido por la validacion contra produccion):
  total_motor    el total esperado y las carreras por equipo salen del motor (LMP: MAE z 2.49 contra la capa).
                 El over/under del total sigue con la capa de totales (el motor no paso ahi en LMP).
  ou_apilado     el p_over del total = logistica sobre [logit p capa, logit p motor] (MLB: z 2.11 contra la capa).
  equipo_local / equipo_visita
                 mercado "Carreras local/visita X.5" con el motor (LMP local z 3.19, MLB local 2.84 y visita 2.78,
                 NPB local 3.42 contra lo que mostraba produccion). Donde no paso se muestra igual (contexto, sin_validar).
El ganador NO cambia: el motor no le gano a la logistica media3.

Solo stdlib (corre en GitHub Actions sin numpy).
"""
import datetime as dt, json, math, os
from collections import defaultdict

from nucleo import io

EXTRA_LOCAL = 0.52
KMAX = 26
RUTA_JSON = ("modelos", "motor_carreras.json")
_CACHE = {}


# ------------------------------------------------------------------ binomial negativa y mercados
def nb_pmf_vec(mu, r, kmax=KMAX):
    p = r / (r + mu)
    v = [math.exp(math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1) + r * math.log(p) + i * math.log(1 - p))
         for i in range(kmax)]
    v[-1] += max(0.0, 1 - sum(v))
    return v


def nb_ll(k, mu, r):
    p = r / (r + mu)
    return math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p)


def mercados(lh, la, r, lineas, linea_eq):
    """probabilidades desde las dos lambdas: ganador, run line, over de cada linea, over de cada total por equipo."""
    ph, pa = nb_pmf_vec(lh, r), nb_pmf_vec(la, r)
    gana = emp = rl = 0.0
    over = {L: 0.0 for L in lineas}
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            pij = x * y
            if i > j:
                gana += pij
                if i - j >= 2:
                    rl += pij
            elif i == j:
                emp += pij
            for L in lineas:
                if i + j > L:
                    over[L] += pij
    return {"p_home": gana + EXTRA_LOCAL * emp, "lh": lh, "la": la, "rl_home": rl, "over": over,
            "eq_h": sum(x for i, x in enumerate(ph) if i > linea_eq[0]),
            "eq_a": sum(y for j, y in enumerate(pa) if j > linea_eq[1])}


def medio(x):
    return math.floor(x) + 0.5


# ------------------------------------------------------------------ juegos y capas de entrada
def juegos(liga):
    from nucleo import features as F
    feats, _ = F.construir("beisbol", liga, 0)
    lg = io.norm(liga)
    G = []
    for r in feats:
        if r["league"] != lg or r.get("total") is None or r.get("marg_home") is None:
            continue
        rh = (r["total"] + r["marg_home"]) / 2.0; ra = r["total"] - rh
        G.append(dict(gp=str(r["gamePk"]), f=r["game_date"][:10], season=str(r.get("season")), h=r["home"], a=r["away"],
                      rh=int(round(rh)), ra=int(round(ra))))
    G.sort(key=lambda g: (g["f"], g["gp"]))
    return G


def carreras_abridor(v):
    """carreras sobre el promedio de la liga que permite un abridor en su salida (FIP encogido x IP esperadas)."""
    return (v[0] - v[3]) * v[1] / 9.0


def abridores_rel(liga, G):
    """({(gp, equipo): carreras de su abridor - promedio de los abridores de ese equipo (as-of)}, promedios finales)."""
    from nucleo import abridores as AB
    lg = io.norm(liga)
    if lg not in ("lmp", "npb"):
        return {}, {}
    V = AB.historicos(io.BASE, lg)
    if not V:
        return {}, {}
    out, prom = {}, {}
    for g in G:
        for e in (g["h"], g["a"]):
            v = V.get((g["gp"], e))
            if not v:
                continue
            runs = carreras_abridor(v)
            m, n = prom.get(e, (0.0, 0.0))
            if n >= 3:
                out[(g["gp"], e)] = runs - m / n
            prom[e] = (0.97 * m + runs, 0.97 * n + 1)
    return out, prom


def parques_delta(liga, G):
    from nucleo import parques as PQ
    lg = io.norm(liga)
    if not PQ.aplica(lg):
        return {}
    V = PQ.historicos(io.BASE, lg)
    out = {}
    for g in G:
        v = V.get((g["gp"], g["h"]))
        if v:
            out[g["gp"]] = PQ.delta(lg, v[0], v[1], v[2])
    return out


# ------------------------------------------------------------------ filtro
def _lambdas(nh, na, ah, dh, aa, da, pk, sh, sa, kap, usa_pq):
    tot0 = nh + na
    fpq = math.log(max(tot0 + pk, 0.5 * tot0) / tot0) if (pk and usa_pq) else 0.0
    eh = math.log(nh) + ah - da + fpq + (kap * sh / na if kap else 0.0)
    ea = math.log(na) + aa - dh + fpq + (kap * sa / nh if kap else 0.0)
    return math.exp(eh), math.exp(ea)


def correr(G, prm, ABR, PQD, r_nb, estado_final=False):
    """recorre los juegos en orden; pred[gp] = (lambda local, lambda visita, sd local, sd visita) ANTES de cada juego.
    estado_final=True devuelve tambien el estado despues del ultimo juego (para predecir los que vienen)."""
    q, rho, p0, kap, usa_pq = prm["q"], prm["rho"], prm["p0"], prm["kappa"], prm["parque"]
    a = defaultdict(float); d = defaultdict(float)
    Pa = defaultdict(lambda: p0); Pd = defaultdict(lambda: p0)
    ult = {}
    LAM = 0.5 ** (1 / 600.0)
    num = [0.0, 0.0]; den = 0.0
    pred = {}
    por_dia = defaultdict(list)
    for g in G:
        por_dia[g["f"]].append(g)
    for f in sorted(por_dia):
        fd = dt.date.fromisoformat(f)
        dia = por_dia[f]
        for g in dia:
            for e in (g["h"], g["a"]):
                if e in ult and (fd - ult[e]).days > 60:
                    a[e] *= rho; d[e] *= rho; Pa[e] += p0; Pd[e] += p0
                Pa[e] += q; Pd[e] += q
        nh, na = (num[0] / den, num[1] / den) if den > 50 else (4.5, 4.3)
        upd = []
        for g in dia:
            lh, la = _lambdas(nh, na, a[g["h"]], d[g["h"]], a[g["a"]], d[g["a"]], PQD.get(g["gp"], 0.0),
                              ABR.get((g["gp"], g["a"]), 0.0), ABR.get((g["gp"], g["h"]), 0.0), kap, usa_pq)
            pred[g["gp"]] = (lh, la, math.sqrt(Pa[g["h"]] + Pd[g["a"]]), math.sqrt(Pa[g["a"]] + Pd[g["h"]]))
            upd.append((g, lh, la))
        for g, lh, la in upd:
            for k, lam, at, df in ((g["rh"], lh, g["h"], g["a"]), (g["ra"], la, g["a"], g["h"])):
                info = lam * r_nb / (r_nb + lam)
                score = (k - lam) * r_nb / (r_nb + lam)
                S = Pa[at] + Pd[df] + 1.0 / info
                z = score / info
                ka, kd = Pa[at] / S, Pd[df] / S
                a[at] += ka * z; d[df] -= kd * z
                Pa[at] -= ka * Pa[at]; Pd[df] -= kd * Pd[df]
            num[0] = LAM * num[0] + g["rh"]; num[1] = LAM * num[1] + g["ra"]; den = LAM * den + 1
            ult[g["h"]] = fd; ult[g["a"]] = fd
        if a:
            ma = sum(a.values()) / len(a); md = sum(d.values()) / len(d)
            for e in list(a):
                a[e] -= ma
            for e in list(d):
                d[e] -= md
    if not estado_final:
        return pred
    nh, na = (num[0] / den, num[1] / den) if den > 50 else (4.5, 4.3)
    return pred, {"a": dict(a), "d": dict(d), "Pa": dict(Pa), "Pd": dict(Pd), "ult": dict(ult), "nivel": (nh, na)}


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
    return (config(base).get("ligas") or {}).get(io.norm(liga))


def estado(liga, base=None):
    """estado del motor despues del ultimo juego en datos/beisbol.csv (cache por corrida)."""
    lg = io.norm(liga)
    k = ("estado", base or io.BASE, lg)
    if k in _CACHE:
        return _CACHE[k]
    c = cfg_liga(lg, base)
    if not c:
        _CACHE[k] = None
        return None
    G = juegos(lg)
    if len(G) < 300:
        _CACHE[k] = None
        return None
    ABR, prom = abridores_rel(lg, G)
    PQD = parques_delta(lg, G)
    _, st = correr(G, c["parametros"], ABR, PQD, c["r_nb"], estado_final=True)
    eq_h = [g["rh"] for g in G[-1500:]]; eq_a = [g["ra"] for g in G[-1500:]]
    st.update(prom=prom, n_juegos=len(G), ultimo=G[-1]["f"],
              linea_eq=(medio(sum(eq_h) / len(eq_h)), medio(sum(eq_a) / len(eq_a))))
    _CACHE[k] = st
    return st


def predecir(liga, home, away, fecha, abridor_home=None, abridor_away=None, dpq=0.0, linea_total=None,
             lineas_equipo=None, base=None):
    """carreras esperadas y mercados del motor para un juego por jugar.
    abridor_*: (fip_encogido, ip_esperadas, aperturas, fip_liga) de nucleo.abridores.actual (o None).
    dpq: delta de carreras del parque/clima (nucleo.parques.delta). lineas_equipo: (linea local, linea visita) del
    mercado si hay; si no, la linea ~promedio de cada lado en la liga."""
    lg = io.norm(liga)
    c = cfg_liga(lg, base); st = estado(lg, base)
    if not c or not st:
        return None
    prm = c["parametros"]; r_nb = c["r_nb"]
    fd = dt.date.fromisoformat(str(fecha)[:10])
    vals = {}
    for e in (home, away):
        av, dv = st["a"].get(e, 0.0), st["d"].get(e, 0.0)
        Pa, Pd = st["Pa"].get(e, prm["p0"]), st["Pd"].get(e, prm["p0"])
        u = st["ult"].get(e)
        if u is not None and (fd - u).days > 60:                 # temporada nueva: como en el filtro
            av *= prm["rho"]; dv *= prm["rho"]; Pa += prm["p0"]; Pd += prm["p0"]
        vals[e] = (av, dv, Pa + prm["q"], Pd + prm["q"], u is not None)
    nh, na = st["nivel"]

    def rel(v, e):
        if not v or not prm.get("kappa"):
            return 0.0
        m, n = st["prom"].get(e, (0.0, 0.0))
        return carreras_abridor(v) - m / n if n >= 3 else 0.0
    sh, sa = rel(abridor_away, away), rel(abridor_home, home)
    ah, dh = vals[home][:2]; aa, da = vals[away][:2]
    lh, la = _lambdas(nh, na, ah, dh, aa, da, dpq or 0.0, sh, sa, prm["kappa"], prm["parque"])
    leq = tuple(lineas_equipo) if lineas_equipo else st["linea_eq"]
    lineas = [linea_total] if linea_total is not None else []
    mk = mercados(lh, la, r_nb, lineas, leq)
    return {"x_home": round(lh, 2), "x_away": round(la, 2), "total": round(lh + la, 2), "p_home": round(mk["p_home"], 4),
            "p_rl_home": round(mk["rl_home"], 4), "p_over": round(mk["over"][linea_total], 4) if linea_total is not None else None,
            "linea_home": leq[0], "linea_away": leq[1], "p_over_home": round(mk["eq_h"], 4), "p_over_away": round(mk["eq_a"], 4),
            "sd_home": round(math.sqrt(vals[home][2] + vals[away][3]), 3), "sd_away": round(math.sqrt(vals[away][2] + vals[home][3]), 3),
            "abridor_rel": {"home": round(sa, 2), "away": round(sh, 2)},
            "equipos_con_historial": vals[home][4] and vals[away][4], "aplicar": c.get("aplicar") or {},
            "datos_hasta": st["ultimo"]}


def apilar_over(liga, p_capa, p_motor, base=None):
    """O/U apilado (logistica sobre los logit de la capa y del motor). None si la liga no lo trae."""
    c = cfg_liga(liga, base)
    w = (c or {}).get("apilado_ou")
    if not w or p_capa is None or p_motor is None:
        return None
    lg_ = lambda p: math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6)))
    z = w[0] + w[1] * lg_(p_capa) + w[2] * lg_(p_motor)
    return 1 / (1 + math.exp(-z))


def cuotas_equipo(ev, home):
    """mejor cuota de los totales por equipo de un evento con el formato de The Odds API (mercado 'team_totals', outcomes con
    'description' = equipo). -> {"home": {"linea", "over", "under"}, "away": {...}} con la linea mas repetida de cada lado."""
    if not ev:
        return {}
    por = {"home": defaultdict(lambda: {"over": None, "under": None, "n": 0}), "away": defaultdict(lambda: {"over": None, "under": None, "n": 0})}
    for bk in ev.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            if m.get("key") != "team_totals":
                continue
            for o in m.get("outcomes") or []:
                lado = "home" if (o.get("description") or "") == (ev.get("home_team") or home) else "away"
                pt, pr, nm = o.get("point"), o.get("price"), (o.get("name") or "").lower()
                if pt is None or pr is None or nm not in ("over", "under"):
                    continue
                d = por[lado][float(pt)]
                d["n"] += 1
                if d[nm] is None or _dec(pr) > _dec(d[nm]):
                    d[nm] = pr
    out = {}
    for lado, lineas in por.items():
        ok = [(v["n"], L, v) for L, v in lineas.items() if v["over"] is not None and v["under"] is not None]
        if ok:
            n, L, v = max(ok)
            out[lado] = {"linea": L, "over": v["over"], "under": v["under"]}
    return out


def _dec(am):
    am = float(am)
    return 1 + (am / 100.0 if am > 0 else 100.0 / -am)
