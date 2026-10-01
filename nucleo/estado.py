# -*- coding: utf-8 -*-
"""
nucleo/estado.py - deja a los modelos de BEISBOL y TENIS listos para partidos FUTUROS.

Los modelos de hockey, americano, nba y futbol ya exponen entrenar() + predecir().
Beisbol y tenis se validan hacia atras (walk-forward) y no guardaban su estado final,
asi que aqui se reconstruye reusando los mismos helpers (no se toca nada validado):

    est = estado.beisbol("mlb")                 # modelo + acumuladores al dia de hoy
    fila = estado.fila_proximo(est, "Atlanta Braves", "Philadelphia Phillies", "2026-09-30")
    pred = beisbol.predecir(est["modelo"], fila, linea_total=7.0)

    est = estado.tenis()
    estado.tenis_predecir(est, "Carlos Alcaraz", "Jannik Sinner", "Hard", 3)

Todo as-of: solo usa juegos anteriores a la fecha del partido futuro.
"""
import csv, io as _io, os, sys, datetime as _dt

try:
    from nucleo import io, features as F
    from modelos import beisbol as B, tenis as T
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io, features as F
    from modelos import beisbol as B, tenis as T

MIN_ENTRENO = 200


# ================================================================== BEISBOL
def beisbol(liga, min_juegos=5):
    """Entrena la logistica de la liga y deja los acumuladores as-of al ultimo juego."""
    lg = io.norm(liga)
    feats, _ = F.construir("beisbol", liga, min_juegos)     # fija tambien los parametros ELO
    filas = [r for r in feats if r["league"] == lg]
    if len(filas) < MIN_ENTRENO:
        return None
    modelo = B.entrenar_logistica(filas)
    if not modelo:
        return None

    juegos = F._emparejar(io.cargar_juegos("beisbol", liga))
    lg_stats = F._medias_liga_temporada(juegos)
    acum, nombres = {}, {}
    for f, gp, h, a in juegos:
        lgn = io.norm(h.get("league") or h.get("liga"))
        if lgn != lg:
            continue
        season = str(h.get("season") or f.year)
        th = F._clave(acum, lgn, season, h.get("team"))
        ta = F._clave(acum, lgn, season, a.get("team"))
        csh, cah = F._f(h.get("runs")), F._f(h.get("runs_opp"))
        csa, caa = F._f(a.get("runs")), F._f(a.get("runs_opp"))
        if None in (csh, csa):
            continue
        F._actualiza_elo(th, ta, csh, csa)
        th.ult_fecha = f; ta.ult_fecha = f
        th.sumar(h, csh, cah if cah is not None else csa)
        ta.sumar(a, csa, caa if caa is not None else csh)
        nombres[h.get("team")] = 1; nombres[a.get("team")] = 1
    ultimo = juegos[-1][0] if juegos else None
    return {"liga": lg, "modelo": modelo, "acum": acum, "lg_stats": lg_stats,
            "nombres": list(nombres), "n_entreno": len(filas), "ultimo_juego": ultimo}


def fila_proximo(est, home, away, fecha_iso):
    """Arma la fila de features de un partido futuro (mismo calculo que features.construir)."""
    f = F._fecha(fecha_iso)
    if not f:
        return None
    lg, season, acum = est["liga"], str(f.year), est["acum"]
    th = F._clave(acum, lg, season, home)
    ta = F._clave(acum, lg, season, away)
    pre_h, pre_a = th.tasas(), ta.tasas()
    if not (pre_h and pre_a) or th.j < 5 or ta.j < 5:
        return None                      # inicio de temporada: aun sin muestra
    med = est["lg_stats"].get((lg, season)) or {}
    fila = {"league": lg, "season": season, "game_date": f.isoformat(), "home": home, "away": away,
            "elo_home": round(th.elo, 1), "elo_away": round(ta.elo, 1),
            "elo_dif": round(th.elo + F._HFA - ta.elo, 1),
            "descanso_dif": F._descanso(th, f) - F._descanso(ta, f)}
    for s in F.STATS:
        vh = F._encoge(pre_h.get(s), med.get(s), th.j)
        va = F._encoge(pre_a.get(s), med.get(s), ta.j)
        fila[s + "_dif"] = round(vh - va, 4) if (vh is not None and va is not None) else None
    fila["of_home"] = round(F._encoge(pre_h.get("cs"), med.get("cs"), th.j), 3)
    fila["of_away"] = round(F._encoge(pre_a.get("cs"), med.get("cs"), ta.j), 3)
    fila["df_home"] = round(F._encoge(pre_h.get("ca"), med.get("ca"), th.j), 3)
    fila["df_away"] = round(F._encoge(pre_a.get("ca"), med.get("ca"), ta.j), 3)
    fila["lg_rs"] = round(med.get("cs") or 4.5, 3)
    return fila


# ================================================================== TENIS
def tenis(min_j=10):
    """Repite el recorrido de tenis.validar() pero sin predecir: deja saque/resto y ELO por
    superficie de cada jugador al dia de hoy. Lee datos/tenis.csv."""
    ruta = os.path.join(io.BASE, "datos", "tenis.csv")
    if not os.path.exists(ruta):
        return None
    with _io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows.sort(key=lambda r: (r.get("tourney_date", ""), r.get("winner_name", "")))
    J = {}

    def g(n):
        return J.setdefault(n, {"sp": 0., "spw": 0., "rp": 0., "rpw": 0., "elo": {}})
    tot_sp = tot_spw = 0.0
    por_tour = {}                      # circuito -> [puntos al saque, ganados]
    n = 0
    for r in rows:
        w, l = r.get("winner_name"), r.get("loser_name")
        sup = (r.get("surface") or "Hard").strip() or "Hard"
        if not w or not l:
            continue
        try:
            wsv = float(r["w_svpt"]); wsw = float(r["w_1stWon"]) + float(r["w_2ndWon"])
            lsv = float(r["l_svpt"]); lsw = float(r["l_1stWon"]) + float(r["l_2ndWon"])
            hay_saque = wsv > 0 and lsv > 0
        except (KeyError, ValueError, TypeError):
            hay_saque = False
        if not hay_saque:
            # Partido sin estadisticas de saque (p. ej. resultados de ESPN): solo mueve el ELO.
            jw, jl = g(w), g(l)
            ew = jw["elo"].get(sup, 1500.0); el = jl["elo"].get(sup, 1500.0)
            exp = 1 / (1 + 10 ** (-(ew - el) / 400))
            jw["elo"][sup] = ew + 24 * (1 - exp); jl["elo"][sup] = el - 24 * (1 - exp)
            continue
        jw, jl = g(w), g(l)
        ew = jw["elo"].get(sup, 1500.0); el = jl["elo"].get(sup, 1500.0)
        jw["sp"] += wsv; jw["spw"] += wsw; jw["rp"] += lsv; jw["rpw"] += (lsv - lsw)
        jl["sp"] += lsv; jl["spw"] += lsw; jl["rp"] += wsv; jl["rpw"] += (wsv - wsw)
        exp = 1 / (1 + 10 ** (-(ew - el) / 400))
        jw["elo"][sup] = ew + 24 * (1 - exp); jl["elo"][sup] = el - 24 * (1 - exp)
        tot_sp += wsv + lsv; tot_spw += wsw + lsw
        tt = por_tour.setdefault((r.get("tour") or "").upper(), [0.0, 0.0])
        tt[0] += wsv + lsv; tt[1] += wsw + lsw
        n += 1
    if n < 200:
        return None
    tspw = {k: v[1] / v[0] for k, v in por_tour.items() if k and v[0] > 0}
    return {"J": J, "tour_spw": (tot_spw / tot_sp) if tot_sp else 0.635, "tour_spw_por_tour": tspw, "min_j": min_j,
            "nombres": list(J), "n_partidos": n}


def tenis_predecir(est, n1, n2, superficie="Hard", best_of=3, linea_games=22.5, tour=None, ajuste_games=0.0):
    j1, j2 = est["J"].get(n1), est["J"].get(n2)
    minimo = est["min_j"] * 50
    if not j1 or not j2 or j1["sp"] < minimo or j2["sp"] < minimo:
        return None
    d1 = {"spw": j1["spw"] / j1["sp"], "rpw": j1["rpw"] / max(j1["rp"], 1)}
    d2 = {"spw": j2["spw"] / j2["sp"], "rpw": j2["rpw"] / max(j2["rp"], 1)}
    e1 = j1["elo"].get(superficie, 1500.0); e2 = j2["elo"].get(superficie, 1500.0)
    tsp = (est.get("tour_spw_por_tour") or {}).get((tour or "").upper(), est["tour_spw"])
    return T.predecir(d1, d2, superficie, best_of, tsp, linea_games, e1, e2, ajuste_games)
