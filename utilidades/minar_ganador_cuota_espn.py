# -*- coding: utf-8 -*-
"""
utilidades/minar_ganador_cuota_espn.py - la misma medicion de minar_ganador_cuota.py (E1-E6, 1 u, cuota >= 1.70) en NBA,
NCAAMB y NCAAFB con las cuotas historicas de ESPN (datos/mercado/espn_cuotas.csv, colectores/recolectar_cuotas_espn.py).

p del modelo as-of: trabajo/minar/tanda7_cache.pkl (la misma de las tandas 7-9). Variante "modelo + capa ESPN": la p de
produccion desde el 10-oct (logit p + beta (logit p_ESPN - logit p), beta de modelos/capa_espn.json; p_ESPN de
datos/equipos/espn_predictor.csv). Ojo: beta se ajusto con toda la muestra (tanda 9), asi que esa variante tiene una
ventaja dentro de muestra.

Cuotas: por casa real (se excluyen 'Live' y accuscore, que es una proyeccion). Fuentes: 'mejor' = la mejor moneyline
por lado entre casas al cierre; 'draftkings' y 'espn bet' sueltas; 'mejor_apertura' = la mejor de apertura.
Referencia del mercado (p_mkt) = consenso sin vig de cierre (promedio de casas).

    python utilidades/minar_ganador_cuota_espn.py
Escribe trabajo/minar/2026-10-11_ganador_cuota_espn_resultados.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, datetime as dt, io as _io, json, math, os, pickle, sys
from collections import Counter, defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
import minar_ganador_cuota as G  # noqa: E402
import metamodelo as MT  # noqa: E402
from nucleo import io  # noqa: E402

LIGAS = (("nba", "NBA"), ("ncaamb", "NCAAMB"), ("ncaafb", "NCAAFB"), ("nfl", "NFL"), ("nhl", "NHL"), ("mlb", "MLB"))
SALIDA = os.path.join(CODIGO, "trabajo", "minar", "2026-10-11_ganador_cuota_espn_resultados%s.json" % (("_" + sys.argv[1].replace(",", "_")) if len(sys.argv) > 1 else ""))


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def leer(rel):
    with _io.open(io.ruta("datos", *rel), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def mapa_ids(liga, filas):
    """(fecha, local del modelo) -> game_id de ESPN. Los nombres se casan por coincidencia de fechas; despues el juego se
    acepta solo si LOCAL Y VISITA coinciden y la fecha de ESPN (UTC) es la del modelo o un dia despues. (La version
    anterior aceptaba +-1 dia solo con el local y podia tomar el juego de otro dia del mismo local: en NHL eso pegaba
    las cuotas de otro partido.)"""
    loc_mod = defaultdict(set); vis_mod = defaultdict(set)
    for r in filas:
        loc_mod[str(r["fecha"])[:10]].add(r["home"]); vis_mod[str(r["fecha"])[:10]].add(r["away"])
    if liga in ("nhl", "mlb"):
        esp = [dict(team=x["local"], opp=x["visita"], game_date=x["game_date"], game_id=x["game_id"])
               for x in leer(("equipos", "espn_%s_juegos.csv" % liga))]
    else:
        esp = [x for x in leer(("equipos", "espn_%s_equipos.csv" % liga)) if str(x.get("is_home")) in ("1", "1.0", "True")]
    par = defaultdict(Counter)
    for x in esp:
        for d in (0, -1):
            f = (dt.date.fromisoformat(x["game_date"][:10]) + dt.timedelta(days=d)).isoformat()
            for t in loc_mod.get(f, ()):
                par[x["team"]][t] += 3 if d == 0 else 2
            for t in vis_mod.get(f, ()):
                if x.get("opp"):
                    par[x["opp"]][t] += 3 if d == 0 else 2
    nombre = {k: c.most_common(1)[0][0] for k, c in par.items() if c}
    loc = {}
    for x in esp:
        th, ta = nombre.get(x["team"]), nombre.get(x.get("opp") or "")
        if th is None:
            continue
        for d in (0, -1):
            f = (dt.date.fromisoformat(x["game_date"][:10]) + dt.timedelta(days=d)).isoformat()
            loc.setdefault((f, th, ta), str(x["game_id"]))
    return loc


def cuotas_por_juego():
    C = defaultdict(list)
    for x in leer(("mercado", "espn_cuotas.csv")):
        if x.get("estado") != "ok":
            continue
        casa = (x.get("casa") or "").strip()
        if not casa or any(k in casa.lower() for k in ("live", "accuscore", "teamrankings", "numberfire")):
            continue
        C[(x["liga"], x["game_id"])].append(x)
    return C


def lados_de(rows, p_home, y_home, ang=0):
    """Construye lados con varias fuentes de cuota. y_home = 1 si gano el local."""
    dec = lambda v: MT._dec_ml(v)
    por = {"mejor": [None, None], "mejor_apertura": [None, None], "draftkings": [None, None], "espn bet": [None, None]}
    nov = []
    for x in rows:
        h, a = dec(x.get("ml_home_close") or x.get("ml_home")), dec(x.get("ml_away_close") or x.get("ml_away"))
        ho, ao = dec(x.get("ml_home_open")), dec(x.get("ml_away_open"))
        # NHL: varias casas (DraftKings, Unibet, Bet365...) publican en ESPN la moneyline a 3 vias de tiempo regular
        # (1/h + 1/a < 1). Solo se usan precios a 2 vias (con margen positivo).
        if h and a and 1 / h + 1 / a < 1.0:
            h = a = None
        if ho and ao and 1 / ho + 1 / ao < 1.0:
            ho = ao = None
        if h and a:
            nv = MT._novig(h, a)
            if nv:
                nov.append(nv[0])
            por["mejor"][0] = max(por["mejor"][0] or 0, h); por["mejor"][1] = max(por["mejor"][1] or 0, a)
            c = x["casa"].lower()
            for k in ("draftkings", "espn bet"):
                if c == k:
                    por[k] = [h, a]
        if ho and ao:
            por["mejor_apertura"][0] = max(por["mejor_apertura"][0] or 0, ho); por["mejor_apertura"][1] = max(por["mejor_apertura"][1] or 0, ao)
    if not nov:
        return None
    pm = sum(nov) / len(nov)
    out = {}
    for f, (h, a) in por.items():
        if not h or not a:
            continue
        out[f] = [dict(lado="home", p=p_home, cuota=h, y=y_home, p_mkt=pm, p_close=pm, ang=ang),
                  dict(lado="away", p=1 - p_home, cuota=a, y=1 - y_home, p_mkt=1 - pm, p_close=1 - pm, ang=-ang)]
    return out


def main():
    U = pickle.load(open(os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl"), "rb"))
    CU = cuotas_por_juego()
    PE = {}
    for x in leer(("equipos", "espn_predictor.csv")):
        if x.get("estado") != "ok":
            continue
        ph, pa = G._n(x.get("p_local")), G._n(x.get("p_visita"))
        if ph is None and pa is None:
            continue
        PE[(x["liga"], x["game_id"])] = min(max((ph if ph is not None else 100 - pa) / 100.0, 0.005), 0.995)
    beta = (json.load(open(os.path.join(CODIGO, "modelos", "capa_espn.json"), encoding="utf-8")).get("ligas") or {})
    res = {"resultados": {}}
    solo = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None
    for liga, dep in LIGAS:
        if solo and liga not in solo:
            continue
        if dep == "MLB":
            filas = [dict(r, home=r["home"][1] if isinstance(r["home"], tuple) else r["home"], away=r["away"][1] if isinstance(r["away"], tuple) else r["away"]) for r in U["BEISBOL"][0] if r.get("liga") == "MLB"]
        else:
            filas = U[dep][0]
        loc = mapa_ids(liga, filas)
        partidos = defaultdict(list)          # fuente -> partidos (modelo base)
        partidos_c = defaultdict(list)        # fuente -> partidos (modelo + capa ESPN)
        n_cas = 0
        for r in filas:
            gid = loc.get((str(r["fecha"])[:10], r["home"], r.get("away"))) or loc.get((str(r["fecha"])[:10], r["home"], None))
            rows = CU.get((liga, gid)) if gid else None
            if not rows:
                continue
            L = lados_de(rows, r["p"], int(r["y"] == 1))
            if not L:
                continue
            n_cas += 1
            for f, lados in L.items():
                partidos[f].append(dict(fecha=str(r["fecha"])[:10], liga=dep, lados=lados))
            q = PE.get((liga, gid)); b = (beta.get(liga) or {}).get("beta")
            if q is not None and b is not None:
                pc = _sig(_lg(r["p"]) + b * (_lg(q) - _lg(r["p"])))
                Lc = lados_de(rows, pc, int(r["y"] == 1))
                for f, lados in (Lc or {}).items():
                    partidos_c[f].append(dict(fecha=str(r["fecha"])[:10], liga=dep, lados=lados))
        print("\n%s: %d juegos del modelo casados con cuotas de ESPN" % (dep, n_cas))
        for f in ("mejor", "mejor_apertura", "draftkings", "espn bet"):
            if partidos.get(f):
                res["resultados"]["%s|modelo|%s" % (dep, f)] = G.evaluar("%s ganador, MODELO, cuota %s" % (dep, f), partidos[f])
            if partidos_c.get(f):
                res["resultados"]["%s|modelo+espn|%s" % (dep, f)] = G.evaluar("%s ganador, MODELO + CAPA ESPN, cuota %s" % (dep, f), partidos_c[f])
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    json.dump(res, _io.open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nescrito", SALIDA)


if __name__ == "__main__":
    main()
