# -*- coding: utf-8 -*-
"""
utilidades/pesos_capas_v2.py - PESOS MEDIDOS DE LAS CAPAS NUEVAS (hockey, NFL, beisbol): ganador y total.

Igual que pesos_capas.py (beisbol), pero para las capas que se agregaron despues y para hockey y NFL:
reconstruye cada capa AS-OF (solo con lo jugado antes de cada partido) y mide, mes a mes y siempre con el pasado,
cuanto aporta cada una por encima del nucleo (ELO + diferencial de temporada). Lo que mide ~0 no entra al decisor.

Capas medidas
  comunes: pct, l10, l5, split local/visita, descanso, b2b, racha (3+ derrotas / 3+ victorias), pitagorico (residuo),
           tecnicos: rsi10 del margen, macd_hist del margen (EMA5-EMA20, senal EMA9), roc_elo10, volatilidad10
  hockey:  portero (sv% as-of de ESE portero: ventana 10 y ventana 60 encogida a la liga; y si es el titular del equipo,
           es decir el mas usado; de nhl_equipos.csv),
           sv% del equipo L10, tiros a favor/contra L10 (proxy de Corsi), PDO L10 (suerte), tiros del partido
  nfl:     (los comunes; con 17 juegos por temporada el ELO y el pitagorico son lo que hay)
  beisbol: abridor as-of (FIP de sus aperturas previas en el archivo, mezclado con prior de liga) -> diferencia home-away;
           solo 2026 (mlb_lanzadores.csv empieza en agosto), asi que la muestra es chica y se reporta aparte.

Tambien el TOTAL: regresion lineal del total de goles/puntos/carreras con las capas que lo mueven (ritmo L10 de ambos,
portero, b2b, abridores) y su MAE walk-forward contra la media de liga as-of.

Uso (en C:\\Edgeline_repo con $env:EDGELINE_BASE = "C:\\Edgeline"):
    python utilidades\\pesos_capas_v2.py                       # hockey + nfl + mlb
    python utilidades\\pesos_capas_v2.py --deporte hockey
Escribe modelos/pesos_capas_v2.json con el aporte medido (milesimas de log-loss y Brier) y los coeficientes finales.
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, math, os, sys
from collections import defaultdict

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))
# NCAAMB (ajustado el 6-oct-2026 por rejilla sobre log-loss del nucleo ELO, 18,835 partidos): K=30, HFA=95.
# Muy distintos de NBA (K=5, HFA=70) y por eso NO se copiaron: en NCAA los planteles rotan cada temporada, asi
# que el ELO tiene que moverse mucho mas rapido, y el local gana 66.8% con +8.11 puntos de margen medio.
K_ELO = {"beisbol": 6.0, "hockey": 8.0, "americano": 8.0, "nba": 5.0, "ncaamb": 30.0}
HFA = {"beisbol": 24.0, "hockey": 30.0, "americano": 55.0, "nba": 70.0, "ncaamb": 95.0}
REGRESION = 0.70
PIT = {"hockey": 1.93, "americano": 2.37, "nba": 14.0, "ncaamb": 8.5}   # NCAAMB ajustado sobre 1,141 equipos-temporada
SALIDA = os.path.join(REPO, "modelos", "pesos_capas_v2.json")
IP_PRIOR, FIP_C = 30.0, 3.10


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x)) if x > -500 else 0.0


def _f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# ------------------------------------------------------------------ juegos por deporte
def _pares(ruta, liga_col, ligas, score, extra=()):
    por = {}
    with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            lg = (r.get(liga_col) or "").upper()
            if ligas and lg not in ligas:
                continue
            gf, ga = _f(r.get(score[0])), _f(r.get(score[1]))
            if gf is None or ga is None:
                continue
            gp = str(r.get("gamePk") or r.get("game_id") or "").replace(".0", "")
            d = por.setdefault((lg, gp), {"liga": lg, "season": str(r.get("season") or "")[:4], "fecha": (r.get("game_date") or "")[:10], "gp": gp})
            home = str(r.get("is_home")).replace(".0", "") == "1"
            lado = "h" if home else "a"
            d[lado] = r["team"]; d["gf_" + lado] = gf
            for e in extra:
                d[e + "_" + lado] = r.get(e)
    out = []
    for d in por.values():
        if d.get("h") and d.get("a") and d.get("gf_h") is not None and d.get("gf_a") is not None and d["gf_h"] != d["gf_a"]:
            d.update(home=d["h"], away=d["a"], rh=d["gf_h"], ra=d["gf_a"]); out.append(d)
    out.sort(key=lambda d: (d["fecha"], d["gp"]))
    return out


def juegos_hockey():
    js = _pares(os.path.join(BASE, "datos", "hockey.csv"), "league", {"NHL"}, ("goals", "goals_opp"), extra=("goalie_sv",))
    # porteros abridores y tiros por juego (nhl_equipos.csv), por (gp, team)
    eq = {}
    ruta = os.path.join(BASE, "datos", "equipos", "nhl_equipos.csv")
    if os.path.exists(ruta):
        with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                eq[(str(r.get("game_id")).replace(".0", ""), r.get("team"))] = r
    for j in js:
        for lado, t in (("h", j["home"]), ("a", j["away"])):
            r = eq.get((j["gp"], t)) or {}
            j["portero_" + lado] = (r.get("portero_abridor") or "").strip() or None
            j["tiros_" + lado] = _f(r.get("tiros")); j["tiros_opp_" + lado] = _f(r.get("tiros_opp"))
            j["sv_" + lado] = _f(j.get("goalie_sv_" + lado))
    return js


def juegos_nfl():
    js = _pares(os.path.join(BASE, "datos", "americano.csv"), "league", {"NFL"}, ("points", "points_opp"))
    st = {}
    ruta = os.path.join(BASE, "datos", "equipos", "nfl_equipos.csv")
    if os.path.exists(ruta):
        with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                jug = (_f(r.get("attempts"), 0) + _f(r.get("carries"), 0) + _f(r.get("sacks_suffered"), 0)) or None
                st[(str(r.get("game_id")), r.get("team"))] = {
                    "jugadas": jug,
                    "epa": (_f(r.get("passing_epa"), 0) + _f(r.get("rushing_epa"), 0)),
                    "yardas": _f(r.get("passing_yards"), 0) + _f(r.get("rushing_yards"), 0),
                    "pierde": _f(r.get("passing_interceptions"), 0) + _f(r.get("fumbles_lost_total"), 0),
                    "cpoe": _f(r.get("passing_cpoe")), "att": _f(r.get("attempts"), 0),
                    "sacks_suf": _f(r.get("sacks_suffered"), 0), "pass_epa": _f(r.get("passing_epa"), 0), "rush_epa": _f(r.get("rushing_epa"), 0),
                    "carries": _f(r.get("carries"), 0)}
    for j in js:
        j["st_h"] = st.get((j["gp"], j["home"])); j["st_a"] = st.get((j["gp"], j["away"]))
    return js


CAMPOS_BASKET = ("nba_fga", "nba_fta", "nba_oreb", "nba_dreb", "nba_tov", "nba_fgm", "nba_fg3m", "nba_ftm")


def _juegos_basket(liga):
    """datos/nba.csv: puntos y box score por equipo -> cuatro factores as-of. liga = 'NBA' o 'NCAAMB'.
    NCAA basquet tiene el box completo en 37,636 de 37,670 filas, igual que NBA."""
    js = _pares(os.path.join(BASE, "datos", "nba.csv"), "league", {liga}, ("points", "points_opp"), extra=CAMPOS_BASKET)
    for j in js:
        for lado in ("h", "a"):
            st = {c[4:]: _f(j.get(c + "_" + lado)) for c in CAMPOS_BASKET}
            j["st_" + lado] = st if all(v is not None for v in st.values()) else None
    return js


def juegos_nba():
    return _juegos_basket("NBA")


def juegos_ncaamb():
    """NCAA basquet: 18,835 partidos. Valido el 6-oct-2026 (ganador +14.8% de skill con z 20.3, total +5.1%,
    over/under +6.4% con z 31.3) y sin ninguna capa medida, al contrario de NHL, NFL, NBA y MLB."""
    return _juegos_basket("NCAAMB")


def juegos_mlb():
    js = _pares(os.path.join(BASE, "datos", "beisbol.csv"), "league", {"MLB"}, ("runs", "runs_opp"))
    # abridores por (game_id, team) con su linea
    ab = {}; rel = {}
    ruta = os.path.join(BASE, "datos", "jugadores_recientes", "mlb_lanzadores.csv")
    if os.path.exists(ruta):
        with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                k = (str(r.get("game_id")).replace(".0", ""), r.get("team"))
                if str(r.get("abridor")) in ("1", "1.0", "True"):
                    ab[k] = r
                else:
                    rel.setdefault(k, []).append(r)
    for j in js:
        for lado, t in (("h", j["home"]), ("a", j["away"])):
            j["abridor_" + lado] = ab.get((j["gp"], t))
            j["relevo_" + lado] = rel.get((j["gp"], t)) or []
    return js


# ------------------------------------------------------------------ utilidades de series
def _ema(xs, n):
    if not xs:
        return None
    k = 2.0 / (n + 1); e = xs[0]
    for x in xs[1:]:
        e = x * k + e * (1 - k)
    return e


def _rsi(xs, n=10):
    xs = xs[-(n + 1):]
    if len(xs) < 3:
        return 50.0
    g = [max(0.0, b - a) for a, b in zip(xs, xs[1:])]; l = [max(0.0, a - b) for a, b in zip(xs, xs[1:])]
    ag, al = sum(g) / len(g), sum(l) / len(l)
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _macd_hist(xs):
    if len(xs) < 6:
        return 0.0
    macd = [(_ema(xs[:i + 1], 5) - _ema(xs[:i + 1], 20)) for i in range(max(0, len(xs) - 12), len(xs))]
    return macd[-1] - _ema(macd, 9)


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _fip(ip, hr, bb, hbp, k):
    return FIP_C + (13 * hr + 3 * (bb + hbp) - 2 * k) / ip if ip > 0 else None


def _ip(s):
    v = _f(s)
    if v is None:
        return 0.0
    ent = int(v); dec = round((v - ent) * 10)
    return ent + dec / 3.0


# ------------------------------------------------------------------ capas as-of
def capas(js, deporte):
    k_elo, hfa = K_ELO[deporte], HFA[deporte]
    elo, ult_se = {}, {}
    temp = defaultdict(lambda: {"n": 0, "w": 0, "gf": 0.0, "ga": 0.0})
    hist = defaultdict(list)                   # equipo -> [(fecha, gf, ga, home, sv, tiros, tiros_opp)]
    elos = defaultdict(list)                   # equipo -> elo tras cada juego
    porteros = defaultdict(list)               # portero -> [sv de cada apertura]
    usos = defaultdict(lambda: defaultdict(int))   # equipo -> portero -> aperturas (quien es el titular)
    abridores = defaultdict(list)              # lanzador -> [(ip, hr, bb, hbp, k)]
    bullpen = defaultdict(list)                # equipo -> [(fecha, ip, hr, bb, hbp, k)] por juego (relevistas)
    nfl_st = defaultdict(list)                 # equipo -> [(season, propio, rival)] stats por juego (NFL)
    nba_st = defaultdict(list)                 # equipo -> [(season, propio, rival, pts propios, pts rival)] (NBA)
    base = defaultdict(lambda: [0, 0, 0.0])    # liga -> [local gana, n, total acumulado]
    lig_sv = [0.0, 0]                           # sv% medio de liga as-of
    filas = []
    for j in js:
        h, a, se, lg = j["home"], j["away"], j["season"], j["liga"]
        for t in (h, a):
            elo.setdefault(t, 1500.0)
            if ult_se.get(t) not in (None, se):
                elo[t] = 1500.0 + (elo[t] - 1500.0) * REGRESION
            ult_se[t] = se
        th, ta = temp[(h, se)], temp[(a, se)]

        def ult(t, n):
            return hist[t][-n:]

        def pct_v(u):
            return sum(1.0 for x in u if x[1] > x[2]) / len(u) if u else 0.5

        def split(t, home):
            u = [x for x in hist[t] if x[3] == home][-20:]
            return pct_v(u) if u else 0.5

        def desc(t):
            return (dt.date.fromisoformat(j["fecha"]) - dt.date.fromisoformat(hist[t][-1][0])).days if hist[t] else 3

        def racha(t):
            u = hist[t]
            if len(u) < 3:
                return 0.0
            s = [1 if x[1] > x[2] else 0 for x in u[-3:]]
            return -1.0 if sum(s) == 3 else (1.0 if sum(s) == 0 else 0.0)   # +1 = viene de 3+ derrotas (rebote medido)

        def pit_res(t, tt):
            if tt["n"] < 5 or tt["gf"] + tt["ga"] == 0:
                return 0.0
            e = PIT.get(deporte) or ((tt["gf"] + tt["ga"]) / tt["n"]) ** 0.287
            pw = tt["gf"] ** e / (tt["gf"] ** e + tt["ga"] ** e)
            return (tt["w"] / tt["n"]) - pw

        def margenes(t, n=20):
            return [x[1] - x[2] for x in hist[t][-n:]]

        def roc_elo(t):
            e = elos[t]
            return (e[-1] - e[-11]) / 100.0 if len(e) >= 11 else 0.0

        def ritmo(t, n=10):
            u = ult(t, n)
            return (sum(x[1] + x[2] for x in u) / len(u)) if u else None

        def sv_equipo(t, n=10):
            u = [x[4] for x in ult(t, n) if x[4] is not None]
            return sum(u) / len(u) if u else None

        def tiros(t, n=10):
            u = [(x[5], x[6]) for x in ult(t, n) if x[5] is not None and x[6] is not None]
            if not u:
                return None, None
            return sum(x[0] for x in u) / len(u), sum(x[1] for x in u) / len(u)

        def pdo(t, n=10):
            u = [x for x in ult(t, n) if x[5] and x[6] and x[4] is not None]
            if not u:
                return 0.0
            sh = sum(x[1] for x in u) / sum(x[5] for x in u)
            return (sh + sum(x[4] for x in u) / len(u)) - 1.0

        if deporte == "americano":
            d_h, d_a = min(desc(h), 14), min(desc(a), 14)
        else:
            d_h, d_a = min(desc(h), 3), min(desc(a), 3)
        mh, ma = margenes(h), margenes(a)
        lsv = lig_sv[0] / lig_sv[1] if lig_sv[1] else 0.905
        f = {"liga": lg, "fecha": j["fecha"], "season": se, "y": 1.0 if j["rh"] > j["ra"] else 0.0,
             "margen": j["rh"] - j["ra"], "total": j["rh"] + j["ra"],
             "elo": (elo[h] + hfa - elo[a]) / 200.0,
             "dif": ((th["gf"] - th["ga"]) / th["n"] if th["n"] else 0.0) - ((ta["gf"] - ta["ga"]) / ta["n"] if ta["n"] else 0.0),
             "pct": ((th["w"] / th["n"]) if th["n"] else 0.5) - ((ta["w"] / ta["n"]) if ta["n"] else 0.5),
             "l10": pct_v(ult(h, 10)) - pct_v(ult(a, 10)), "l5": pct_v(ult(h, 5)) - pct_v(ult(a, 5)),
             "split": split(h, True) - split(a, False),
             "descanso": d_h - d_a,
             "b2b": ((1.0 if d_h <= 5 else 0.0) - (1.0 if d_a <= 5 else 0.0)) if deporte == "americano" else ((1.0 if d_h == 1 else 0.0) - (1.0 if d_a == 1 else 0.0)),
             "bye": ((1.0 if d_h >= 13 else 0.0) - (1.0 if d_a >= 13 else 0.0)) if deporte == "americano" else 0.0,
             "racha": racha(h) - racha(a),
             "pit_res": pit_res(h, th) - pit_res(a, ta),
             "rsi10": (_rsi(mh) - _rsi(ma)) / 50.0,
             "macd": _macd_hist(mh) - _macd_hist(ma),
             "roc_elo": roc_elo(h) - roc_elo(a),
             "vol10": _std(mh[-10:]) - _std(ma[-10:]),
             "n_temp": min(th["n"], ta["n"]),
             "base": (base[lg][0] / base[lg][1]) if base[lg][1] >= 50 else 0.54,
             "base_total": (base[lg][2] / base[lg][1]) if base[lg][1] >= 50 else None,
             "ritmo": ((ritmo(h) or 0) + (ritmo(a) or 0)) / 2.0 if ritmo(h) and ritmo(a) else None}
        if deporte == "hockey":
            def sv_portero(nombre):
                u = porteros.get(nombre) or []
                if len(u) < 3:
                    return None
                u = u[-10:]
                return sum(u) / len(u)
            sph, spa = sv_portero(j.get("portero_h")), sv_portero(j.get("portero_a"))
            f["portero"] = ((sph if sph is not None else lsv) - (spa if spa is not None else lsv)) * 100.0     # puntos de sv%
            f["portero_ok"] = 1 if (sph is not None and spa is not None) else 0
            f["portero_suma"] = (((sph if sph is not None else lsv) + (spa if spa is not None else lsv)) / 2.0 - lsv) * 100.0
            def sv60(nombre):
                u = porteros.get(nombre) or []
                if len(u) < 5:
                    return None
                u = u[-60:]
                return (sum(u) + 15 * lsv) / (len(u) + 15)          # encogido hacia la liga (prior 15 aperturas)
            s6h, s6a = sv60(j.get("portero_h")), sv60(j.get("portero_a"))
            f["portero60"] = ((s6h if s6h is not None else lsv) - (s6a if s6a is not None else lsv)) * 100.0
            def titular(team, nombre):
                u = usos[team]
                return (1.0 if nombre == max(u, key=u.get) else 0.0) if u else 0.5
            f["titular"] = titular(h, j.get("portero_h")) - titular(a, j.get("portero_a"))
            seh, sea = sv_equipo(h), sv_equipo(a)
            f["sv_eq"] = ((seh if seh is not None else lsv) - (sea if sea is not None else lsv)) * 100.0
            tf_h, ta_h = tiros(h); tf_a, ta_a = tiros(a)
            f["tiros"] = ((tf_h - ta_h) if tf_h is not None else 0.0) - ((tf_a - ta_a) if tf_a is not None else 0.0)
            f["pdo"] = (pdo(h) - pdo(a)) * 10.0
            f["tiros_suma"] = (((tf_h + ta_h) if tf_h is not None else 60.0) + ((tf_a + ta_a) if tf_a is not None else 60.0)) / 2.0 - 60.0
        if deporte == "americano":
            def agg(t, n=None, se_only=False):
                u = nfl_st.get(t) or []
                if se_only:
                    u = [x for x in u if x[0] == se]
                if n:
                    u = u[-n:]
                if len(u) < 3:
                    return None
                jp = sum(x[1]["jugadas"] or 0 for x in u); jr = sum(x[2]["jugadas"] or 0 for x in u)
                if not jp or not jr:
                    return None
                return {"epa_of": sum(x[1]["epa"] for x in u) / jp, "epa_df": sum(x[2]["epa"] for x in u) / jr,
                        "ypj_of": sum(x[1]["yardas"] for x in u) / jp, "ypj_df": sum(x[2]["yardas"] for x in u) / jr,
                        "to": (sum(x[2]["pierde"] for x in u) - sum(x[1]["pierde"] for x in u)) / len(u),
                        "cpoe": sum((x[1]["cpoe"] or 0) for x in u) / len(u),
                        "sack_of": sum(x[1]["sacks_suf"] for x in u) / max(1, sum(x[1]["att"] + x[1]["sacks_suf"] for x in u)),
                        "sack_df": sum(x[2]["sacks_suf"] for x in u) / max(1, sum(x[2]["att"] + x[2]["sacks_suf"] for x in u)),
                        "pass_epa": sum(x[1]["pass_epa"] for x in u) / max(1, sum(x[1]["att"] + x[1]["sacks_suf"] for x in u)),
                        "rush_epa": sum(x[1]["rush_epa"] for x in u) / max(1, sum(x[1]["carries"] for x in u))}
            def d(k, ah, aa, esc=1.0):
                if not ah or not aa:
                    return 0.0
                return (ah[k] - aa[k]) * esc
            a10h, a10a = agg(h, 10), agg(a, 10)
            a5h, a5a = agg(h, 5), agg(a, 5)
            ash, asa = agg(h, se_only=True), agg(a, se_only=True)
            f["epa_net10"] = d("epa_of", a10h, a10a, 10) - d("epa_df", a10h, a10a, 10)      # EPA/jugada neto L10, x10
            f["epa_net5"] = d("epa_of", a5h, a5a, 10) - d("epa_df", a5h, a5a, 10)
            f["epa_temp"] = (d("epa_of", ash, asa, 10) - d("epa_df", ash, asa, 10)) if (ash and asa and th["n"] >= 4 and ta["n"] >= 4) else 0.0
            f["epa_of10"] = d("epa_of", a10h, a10a, 10)
            f["epa_df10"] = -d("epa_df", a10h, a10a, 10)
            f["ypj_net10"] = d("ypj_of", a10h, a10a) - d("ypj_df", a10h, a10a)
            f["to10"] = d("to", a10h, a10a)
            f["cpoe10"] = d("cpoe", a10h, a10a)
            f["sack10"] = -d("sack_of", a10h, a10a, 10) + d("sack_df", a10h, a10a, 10)
            f["pass_epa10"] = d("pass_epa", a10h, a10a, 10)
            f["rush_epa10"] = d("rush_epa", a10h, a10a, 10)
            f["nfl_ok"] = 1 if (a10h and a10a) else 0
        if deporte in ("nba", "ncaamb"):
            def agg_nba(t, n=None, se_only=False):
                u = nba_st.get(t) or []
                if se_only:
                    u = [x for x in u if x[0] == se]
                if n:
                    u = u[-n:]
                if len(u) < 3:
                    return None
                S = lambda k, i: sum(x[i][k] for x in u)
                pos_p = S("fga", 1) + 0.44 * S("fta", 1) - S("oreb", 1) + S("tov", 1)
                pos_r = S("fga", 2) + 0.44 * S("fta", 2) - S("oreb", 2) + S("tov", 2)
                if pos_p <= 0 or pos_r <= 0 or S("fga", 1) <= 0 or S("fga", 2) <= 0:
                    return None
                return {"ort": 100.0 * sum(x[3] for x in u) / pos_p, "drt": 100.0 * sum(x[4] for x in u) / pos_r,
                        "efg": (S("fgm", 1) + 0.5 * S("fg3m", 1)) / S("fga", 1), "efg_d": (S("fgm", 2) + 0.5 * S("fg3m", 2)) / S("fga", 2),
                        "tov": S("tov", 1) / pos_p, "tov_d": S("tov", 2) / pos_r,
                        "orb": S("oreb", 1) / (S("oreb", 1) + S("dreb", 2)), "orb_d": S("oreb", 2) / (S("oreb", 2) + S("dreb", 1)),
                        "ftr": S("ftm", 1) / S("fga", 1), "ftr_d": S("ftm", 2) / S("fga", 2),
                        "pace": (pos_p + pos_r) / (2.0 * len(u))}
            def dn(k, ah, aa, esc=1.0):
                return ((ah[k] - aa[k]) * esc) if (ah and aa) else 0.0
            n10h, n10a = agg_nba(h, 10), agg_nba(a, 10)
            nsh, nsa = agg_nba(h, se_only=True), agg_nba(a, se_only=True)
            f["net10"] = (dn("ort", n10h, n10a) - dn("drt", n10h, n10a)) / 10.0        # net rating L10 diff, por 10 pts/100 pos
            f["net_temp"] = ((dn("ort", nsh, nsa) - dn("drt", nsh, nsa)) / 10.0) if (nsh and nsa and th["n"] >= 5 and ta["n"] >= 5) else 0.0
            f["efg10"] = (dn("efg", n10h, n10a) - dn("efg_d", n10h, n10a)) * 10.0
            f["tov10"] = -(dn("tov", n10h, n10a) - dn("tov_d", n10h, n10a)) * 10.0
            f["orb10"] = (dn("orb", n10h, n10a) - dn("orb_d", n10h, n10a)) * 10.0
            f["ftr10"] = (dn("ftr", n10h, n10a) - dn("ftr_d", n10h, n10a)) * 10.0
            f["pace_suma"] = (((n10h["pace"] if n10h else 100.0) + (n10a["pace"] if n10a else 100.0)) / 2.0) - 100.0
            f["nba_ok"] = 1 if (n10h and n10a) else 0
        if deporte == "beisbol":
            def fip_asof(r):
                if not r:
                    return None, 0
                u = abridores.get(r.get("jugador")) or []
                ip = sum(x[0] for x in u);
                if ip <= 0:
                    return None, 0
                fipv = _fip(ip, sum(x[1] for x in u), sum(x[2] for x in u), sum(x[3] for x in u), sum(x[4] for x in u))
                # mezcla con prior de liga (4.20) segun innings
                return (ip * fipv + IP_PRIOR * 4.20) / (ip + IP_PRIOR), len(u)
            def bp_asof(t):
                u = [x for x in bullpen.get(t) or [] if x[0] >= (dt.date.fromisoformat(j["fecha"]) - dt.timedelta(days=30)).isoformat()]
                ip = sum(x[1] for x in u)
                if ip < 20:
                    return None, 0.0
                fipb = _fip(ip, sum(x[2] for x in u), sum(x[3] for x in u), sum(x[4] for x in u), sum(x[5] for x in u))
                carga = sum(x[1] for x in bullpen.get(t) or [] if x[0] >= (dt.date.fromisoformat(j["fecha"]) - dt.timedelta(days=3)).isoformat())
                return (ip * fipb + IP_PRIOR * 4.20) / (ip + IP_PRIOR), carga
            bh, ch_ = bp_asof(h); ba, ca_ = bp_asof(a)
            f["bullpen_ok"] = 1 if (bh is not None and ba is not None) else 0
            f["fip_bp"] = ((ba if ba is not None else 4.20) - (bh if bh is not None else 4.20))
            f["carga_bp"] = (ca_ - ch_)                       # + = bullpen local mas cansado (IP ultimos 3 dias)
            f["fip_bp_suma"] = (((bh if bh is not None else 4.20) + (ba if ba is not None else 4.20)) / 2.0) - 4.20
            fh, nh = fip_asof(j.get("abridor_h")); fa, na = fip_asof(j.get("abridor_a"))
            f["abridor_ok"] = 1 if (nh >= 3 and na >= 3) else 0
            f["fip"] = ((fa if fa is not None else 4.20) - (fh if fh is not None else 4.20))      # + = abridor local mejor
            f["fip_suma"] = (((fh if fh is not None else 4.20) + (fa if fa is not None else 4.20)) / 2.0) - 4.20
        filas.append(f)
        # ----- actualizar con el resultado
        esp = _sig((elo[h] + hfa - elo[a]) / (400.0 / math.log(10)))
        res = 1.0 if j["rh"] > j["ra"] else 0.0
        d = k_elo * max(math.log(abs(j["rh"] - j["ra"]) + 1), 0.7) * (res - esp)
        elo[h] += d; elo[a] -= d
        elos[h].append(elo[h]); elos[a].append(elo[a])
        th["n"] += 1; th["w"] += res; th["gf"] += j["rh"]; th["ga"] += j["ra"]
        ta["n"] += 1; ta["w"] += 1 - res; ta["gf"] += j["ra"]; ta["ga"] += j["rh"]
        hist[h].append((j["fecha"], j["rh"], j["ra"], True, j.get("sv_h"), j.get("tiros_h"), j.get("tiros_opp_h")))
        hist[a].append((j["fecha"], j["ra"], j["rh"], False, j.get("sv_a"), j.get("tiros_a"), j.get("tiros_opp_a")))
        base[lg][0] += res; base[lg][1] += 1; base[lg][2] += j["rh"] + j["ra"]
        if deporte == "hockey":
            for lado in ("h", "a"):
                sv = j.get("sv_" + lado)
                if sv is not None:
                    lig_sv[0] += sv; lig_sv[1] += 1
                    if j.get("portero_" + lado):
                        porteros[j["portero_" + lado]].append(sv)
                        usos[j["home"] if lado == "h" else j["away"]][j["portero_" + lado]] += 1
        if deporte == "americano" and j.get("st_h") and j.get("st_a"):
            nfl_st[h].append((se, j["st_h"], j["st_a"])); nfl_st[a].append((se, j["st_a"], j["st_h"]))
        if deporte in ("nba", "ncaamb") and j.get("st_h") and j.get("st_a"):
            nba_st[h].append((se, j["st_h"], j["st_a"], j["rh"], j["ra"])); nba_st[a].append((se, j["st_a"], j["st_h"], j["ra"], j["rh"]))
        if deporte == "beisbol":
            for lado in ("h", "a"):
                r = j.get("abridor_" + lado)
                if r:
                    abridores[r.get("jugador")].append((_ip(r.get("ip")), _f(r.get("hr"), 0), _f(r.get("bb"), 0), _f(r.get("hbp"), 0), _f(r.get("k"), 0)))
                rl = j.get("relevo_" + lado) or []
                if rl:
                    t = j["home"] if lado == "h" else j["away"]
                    bullpen[t].append((j["fecha"], sum(_ip(x.get("ip")) for x in rl), sum(_f(x.get("hr"), 0) for x in rl), sum(_f(x.get("bb"), 0) for x in rl),
                                       sum(_f(x.get("hbp"), 0) for x in rl), sum(_f(x.get("k"), 0) for x in rl)))
    return filas


# ------------------------------------------------------------------ ajuste
def _solve(A, b):
    n = len(b); M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            M[c][c] = 1e-12
        for r in range(n):
            if r != c:
                fct = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= fct * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def logistica(filas, vars_, iters=25, l2=1e-3):
    p = len(vars_) + 1
    beta = [0.0] * p
    X = [[1.0] + [f[v] for v in vars_] for f in filas]
    y = [f["y"] for f in filas]
    for _ in range(iters):
        g = [0.0] * p; H = [[0.0] * p for _ in range(p)]
        for xi, yi in zip(X, y):
            mu = _sig(sum(b * x for b, x in zip(beta, xi)))
            w = mu * (1 - mu)
            for i in range(p):
                g[i] += (yi - mu) * xi[i]
                for k in range(p):
                    H[i][k] += w * xi[i] * xi[k]
        for i in range(1, p):
            g[i] -= l2 * beta[i]; H[i][i] += l2
        paso = _solve(H, g)
        beta = [b + s for b, s in zip(beta, paso)]
        if max(abs(s) for s in paso) < 1e-6:
            break
    return beta


def lineal(filas, vars_, objetivo, l2=1e-3):
    p = len(vars_) + 1
    X = [[1.0] + [f[v] for v in vars_] for f in filas]
    y = [f[objetivo] for f in filas]
    A = [[0.0] * p for _ in range(p)]; b = [0.0] * p
    for xi, yi in zip(X, y):
        for i in range(p):
            b[i] += xi[i] * yi
            for k in range(p):
                A[i][k] += xi[i] * xi[k]
    for i in range(1, p):
        A[i][i] += l2
    return _solve(A, b)


def _pred(beta, f, vars_):
    return _sig(beta[0] + sum(b * f[v] for b, v in zip(beta[1:], vars_)))


def walk_forward(filas, vars_, min_meses=6, filtro=None):
    meses = sorted({f["fecha"][:7] for f in filas})
    ll = br = bb = 0.0; n = 0
    for i, m in enumerate(meses):
        if i < min_meses:
            continue
        train = [f for f in filas if f["fecha"][:7] < m and f["n_temp"] >= 5 and (filtro is None or filtro(f))]
        test = [f for f in filas if f["fecha"][:7] == m and f["n_temp"] >= 5 and (filtro is None or filtro(f))]
        if len(train) < 200 or not test:
            continue
        beta = logistica(train, vars_)
        for f in test:
            p = min(max(_pred(beta, f, vars_), 1e-4), 1 - 1e-4)
            ll += -(f["y"] * math.log(p) + (1 - f["y"]) * math.log(1 - p))
            br += (p - f["y"]) ** 2; bb += (f["base"] - f["y"]) ** 2; n += 1
    return (ll / n if n else None, br / n if n else None, bb / n if n else None, n)


def walk_forward_total(filas, vars_, min_meses=6, filtro=None):
    """MAE del total walk-forward vs media de liga as-of."""
    meses = sorted({f["fecha"][:7] for f in filas})
    ea = eb = 0.0; n = 0
    for i, m in enumerate(meses):
        if i < min_meses:
            continue
        train = [f for f in filas if f["fecha"][:7] < m and f["n_temp"] >= 5 and f["ritmo"] is not None and (filtro is None or filtro(f))]
        test = [f for f in filas if f["fecha"][:7] == m and f["n_temp"] >= 5 and f["ritmo"] is not None and f["base_total"] is not None and (filtro is None or filtro(f))]
        if len(train) < 200 or not test:
            continue
        beta = lineal(train, vars_, "total")
        for f in test:
            p = beta[0] + sum(b * f[v] for b, v in zip(beta[1:], vars_))
            ea += abs(p - f["total"]); eb += abs(f["base_total"] - f["total"]); n += 1
    return (ea / n if n else None, eb / n if n else None, n)


# ------------------------------------------------------------------ informe
def medir(deporte, js):
    filas = capas(js, deporte)
    print("\n==== %s: %d juegos, %d con capas (>=5 juegos de temporada)" % (deporte.upper(), len(js), sum(1 for f in filas if f["n_temp"] >= 5)))
    nucleo = ["elo", "dif"]
    comunes = ["pct", "l10", "l5", "split", "descanso", "b2b", "racha", "pit_res", "rsi10", "macd", "roc_elo", "vol10"]
    propias = {"hockey": ["portero", "portero60", "titular", "sv_eq", "tiros", "pdo"], "beisbol": ["fip"], "nba": ["net10", "net_temp", "efg10", "tov10", "orb10", "ftr10"],
                "ncaamb": ["net10", "net_temp", "efg10", "tov10", "orb10", "ftr10"], "americano": ["bye", "epa_net10", "epa_net5", "epa_temp", "epa_of10", "epa_df10", "ypj_net10", "to10", "cpoe10", "sack10", "pass_epa10", "rush_epa10"]}[deporte]
    out = {"juegos": len(js), "ganador": {}, "total": {}}
    filtro = None
    if deporte == "beisbol":
        return medir_beisbol(filas, out)
    ll0, br0, bb0, n0 = walk_forward(filas, nucleo, filtro=filtro)
    if n0 == 0:
        print("  sin muestra suficiente para walk-forward"); return out
    print("GANADOR walk-forward (nucleo ELO + diferencial): n=%d  logloss %.4f  Brier %.4f  base %.4f  skill %+.2f%%" % (n0, ll0, br0, bb0, 100 * (bb0 - br0) / bb0))
    out["ganador"]["nucleo"] = {"n": n0, "logloss": round(ll0, 4), "brier": round(br0, 4), "brier_base": round(bb0, 4)}
    print("Aporte de cada capa sobre el nucleo (milesimas de log-loss; + = mejora; ~0 = no predice):")
    aportes = {}
    for extra in comunes + propias:
        ll, br, _, n = walk_forward(filas, nucleo + [extra], filtro=filtro)
        if ll is None:
            continue
        beta = logistica([f for f in filas if f["n_temp"] >= 5 and (filtro is None or filtro(f))], nucleo + [extra])
        aportes[extra] = {"d_logloss_milesimas": round(1000 * (ll0 - ll), 2), "d_brier_milesimas": round(1000 * (br0 - br), 2), "coef": round(beta[-1], 4), "n": n}
        print("  %-9s %+6.2f  (Brier %+6.2f)  coef %+.3f" % (extra, 1000 * (ll0 - ll), 1000 * (br0 - br), beta[-1]))
    out["ganador"]["capas"] = aportes
    utiles = [k for k, v in aportes.items() if v["d_logloss_milesimas"] >= 0.5]
    llu, bru, _, nu = walk_forward(filas, nucleo + utiles, filtro=filtro)
    beta_u = logistica([f for f in filas if f["n_temp"] >= 5 and (filtro is None or filtro(f))], nucleo + utiles)
    print("Nucleo + capas utiles %s: logloss %.4f (%+.2f milesimas), Brier %.4f" % (utiles, llu, 1000 * (ll0 - llu), bru))
    out["ganador"]["final"] = {"vars": nucleo + utiles, "beta": [round(b, 5) for b in beta_u], "logloss": round(llu, 4), "brier": round(bru, 4), "n": nu}
    # ---- total
    vt = ["ritmo"]
    cand_t = {"hockey": ["portero_suma", "tiros_suma", "b2b_suma", "pdo_suma"], "beisbol": ["fip_suma"], "americano": ["vol_suma"], "nba": ["pace_suma", "b2b_suma"],
              "ncaamb": ["pace_suma", "b2b_suma"]}[deporte]
    for f in filas:
        f["b2b_suma"] = abs(f["b2b"]) if f["b2b"] else 0.0
        f["pdo_suma"] = 0.0
        f["vol_suma"] = 0.0
    e0, eb, nt = walk_forward_total(filas, vt, filtro=filtro)
    if e0 is not None:
        print("TOTAL walk-forward (ritmo L10 de ambos): n=%d  MAE %.3f  base (media liga) %.3f" % (nt, e0, eb))
        out["total"]["ritmo"] = {"n": nt, "mae": round(e0, 3), "mae_base": round(eb, 3)}
        for extra in cand_t:
            if extra not in filas[0]:
                continue
            e, _, n = walk_forward_total(filas, vt + [extra], filtro=filtro)
            if e is None:
                continue
            bt = lineal([f for f in filas if f["n_temp"] >= 5 and f["ritmo"] is not None and (filtro is None or filtro(f))], vt + [extra], "total")
            print("  %-12s MAE %.3f (%+.3f)  coef %+.3f" % (extra, e, e0 - e, bt[-1]))
            out["total"][extra] = {"mae": round(e, 3), "d_mae": round(e0 - e, 3), "coef": round(bt[-1], 4), "n": n}
    return out


def medir_beisbol(filas, out):
    """Abridores solo desde agosto 2026: el nucleo (ELO+dif) se ajusta con todo lo anterior y, sobre los juegos con los dos
    abridores conocidos (>=3 aperturas previas cada uno), se mide si el FIP as-of aporta, con validacion por bloques de fecha."""
    nucleo = ["elo", "dif"]
    ok = sorted([f for f in filas if f["n_temp"] >= 5 and f.get("abridor_ok") == 1], key=lambda f: f["fecha"])
    if len(ok) < 200:
        print("  beisbol: solo %d juegos con ambos abridores conocidos; sin medicion" % len(ok)); return out
    primera = ok[0]["fecha"]
    train0 = [f for f in filas if f["n_temp"] >= 5 and f["fecha"] < primera]
    b0 = logistica(train0, nucleo)
    for f in ok:
        f["lp0"] = math.log(max(_pred(b0, f, nucleo), 1e-6) / max(1 - _pred(b0, f, nucleo), 1e-6))
    print("BEISBOL (MLB): nucleo ajustado con %d juegos previos; %d juegos con ambos abridores (%s a %s)" % (len(train0), len(ok), primera, ok[-1]["fecha"]))
    def cv(vars_, k=4):
        ll = 0.0; br = 0.0; n = 0
        bloques = [ok[i::k] for i in range(k)]
        for i in range(k):
            test = bloques[i]; train = [f for b in range(k) if b != i for f in bloques[b]]
            beta = logistica(train, vars_, l2=1e-2)
            for f in test:
                p = min(max(_pred(beta, f, vars_), 1e-4), 1 - 1e-4)
                ll += -(f["y"] * math.log(p) + (1 - f["y"]) * math.log(1 - p)); br += (p - f["y"]) ** 2; n += 1
        return ll / n, br / n, n
    ll0, br0, n = cv(["lp0"])
    base = sum(f["y"] for f in ok) / len(ok); bb = sum((base - f["y"]) ** 2 for f in ok) / len(ok)
    print("GANADOR cv-4 bloques (nucleo): n=%d logloss %.4f Brier %.4f base %.4f" % (n, ll0, br0, bb))
    out["ganador"]["nucleo"] = {"n": n, "logloss": round(ll0, 4), "brier": round(br0, 4), "brier_base": round(bb, 4)}
    aportes = {}
    for extra in ("fip", "fip_bp", "carga_bp", "pct", "l10", "l5", "racha", "pit_res", "rsi10", "macd", "roc_elo"):
        ll, br, _ = cv(["lp0", extra])
        beta = logistica(ok, ["lp0", extra], l2=1e-2)
        aportes[extra] = {"d_logloss_milesimas": round(1000 * (ll0 - ll), 2), "d_brier_milesimas": round(1000 * (br0 - br), 2), "coef": round(beta[-1], 4), "n": n}
        print("  %-9s %+6.2f  (Brier %+6.2f)  coef %+.3f" % (extra, 1000 * (ll0 - ll), 1000 * (br0 - br), beta[-1]))
    out["ganador"]["capas"] = aportes
    # total: ritmo + fip_suma
    okt = [f for f in ok if f["ritmo"] is not None and f["base_total"] is not None]
    def cvt(vars_, k=4):
        ea = 0.0; n = 0
        bloques = [okt[i::k] for i in range(k)]
        for i in range(k):
            test = bloques[i]; train = [f for b in range(k) if b != i for f in bloques[b]]
            beta = lineal(train, vars_, "total")
            for f in test:
                ea += abs(beta[0] + sum(b * f[v] for b, v in zip(beta[1:], vars_)) - f["total"]); n += 1
        return ea / n, n
    e_base = sum(abs(f["base_total"] - f["total"]) for f in okt) / len(okt)
    e0, n = cvt(["ritmo"]); e1, _ = cvt(["ritmo", "fip_suma"]); e2, _ = cvt(["ritmo", "fip_suma", "fip_bp_suma"])
    bt = lineal(okt, ["ritmo", "fip_suma", "fip_bp_suma"], "total")
    print("TOTAL cv-4: n=%d  MAE media liga %.3f | ritmo %.3f | + FIP abridores %.3f | + FIP bullpen %.3f (coef abridores %+.3f, bullpen %+.3f)" % (n, e_base, e0, e1, e2, bt[-2], bt[-1]))
    out["total"] = {"n": n, "mae_base": round(e_base, 3), "mae_ritmo": round(e0, 3), "mae_ritmo_fip": round(e1, 3), "mae_ritmo_fip_bullpen": round(e2, 3), "coef_fip_suma": round(bt[-2], 4), "coef_fip_bp_suma": round(bt[-1], 4)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", default="hockey,americano,nba,ncaamb,beisbol")
    a = ap.parse_args()
    res = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "nota": "aporte en milesimas de log-loss walk-forward sobre ELO+diferencial; coef = coeficiente logit de la capa en el ajuste completo"}
    for d in a.deporte.split(","):
        d = d.strip()
        js = {"hockey": juegos_hockey, "americano": juegos_nfl, "beisbol": juegos_mlb,
              "nba": juegos_nba, "ncaamb": juegos_ncaamb}[d]()
        res[d] = medir(d, js)
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with io.open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nGuardado:", SALIDA)


if __name__ == "__main__":
    main()
