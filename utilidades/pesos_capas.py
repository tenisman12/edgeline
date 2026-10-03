# -*- coding: utf-8 -*-
"""
utilidades/pesos_capas.py - PESOS ESTIMADOS DE LAS CAPAS (beisbol): que predice de verdad el ganador y el margen.

Toma datos/beisbol.csv (MLB, NPB, KBO), reconstruye las capas AS-OF (solo con juegos anteriores a cada partido):
ELO descriptivo (mismo K/HFA/regresion que nucleo/forma.py), diferencial de carreras de la temporada, % de victorias,
L10, L5, local/visita, H2H y descanso, y mide, mes a mes y siempre con el pasado, cuanto aporta cada capa por encima
de ELO + diferencial. Ajusta la regresion logistica del ganador y la lineal del margen con lo que si aporta, y guarda
los coeficientes en modelos/decidir_beisbol.json (los usa utilidades/decidir.py).

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\pesos_capas.py                 # MLB+NPB+KBO, 2022 en adelante
    python utilidades\\pesos_capas.py --ligas mlb      # una liga
    python utilidades\\pesos_capas.py --desde 2018

Solo stdlib. Validacion walk-forward: cada mes se predice con coeficientes ajustados con TODOS los meses anteriores
(primeros 12 meses solo para arrancar). Brier contra la base (tasa de victoria del local por liga, tambien as-of).
"""
import argparse, csv, datetime as dt, io, json, math, os, sys
from collections import defaultdict

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))
K_ELO, HFA, REGRESION = 6.0, 24.0, 0.70          # igual que nucleo/forma.py (beisbol)
LIGAS = {"mlb": "MLB", "npb": "NPB", "kbo": "KBO"}
SALIDA = os.path.join(BASE, "modelos", "decidir_beisbol.json")


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x)) if x > -500 else 0.0


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


# ------------------------------------------------------------------ datos
def juegos(ligas, desde):
    """[{liga, season, fecha, gp, home, away, rh, ra}] ordenados por fecha; un registro por juego."""
    ruta = os.path.join(BASE, "datos", "beisbol.csv")
    por = {}
    with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            lg = (r.get("league") or "").upper()
            if lg not in ligas or (r.get("game_date") or "") < desde:
                continue
            try:
                runs, ro = float(r["runs"]), float(r["runs_opp"])
            except (TypeError, ValueError):
                continue
            gp = str(r.get("gamePk") or "").replace(".0", "")
            k = (lg, gp)
            d = por.setdefault(k, {"liga": lg, "season": str(r.get("season") or "")[:4], "fecha": r["game_date"][:10], "gp": gp})
            if str(r.get("is_home")).replace(".0", "") == "1":
                d.update(home=r["team"], rh=runs, ra=ro)
            else:
                d.update(away=r["team"])
                d.setdefault("rh", ro); d.setdefault("ra", runs)
    out = [d for d in por.values() if d.get("home") and d.get("away") and d["rh"] != d["ra"]]
    out.sort(key=lambda d: (d["fecha"], d["gp"]))
    return out


# ------------------------------------------------------------------ capas as-of
def capas(js):
    """Recorre los juegos en orden y, ANTES de cada uno, calcula las capas de los dos equipos con lo jugado hasta entonces."""
    elo, ult_se = {}, {}
    temp = defaultdict(lambda: {"n": 0, "w": 0, "gf": 0.0, "ga": 0.0})     # por (equipo, season)
    hist = defaultdict(list)                                                # equipo -> [(fecha, gf, ga, home)]
    h2h = defaultdict(lambda: [0, 0])                                       # (a, b) -> [gana a, n]
    base = defaultdict(lambda: [0, 0])                                      # liga -> [local gana, n]
    filas = []
    for j in js:
        h, a, se, lg = j["home"], j["away"], j["season"], j["liga"]
        for t in (h, a):
            elo.setdefault(t, 1500.0)
            if ult_se.get(t) not in (None, se):
                elo[t] = 1500.0 + (elo[t] - 1500.0) * REGRESION
            ult_se[t] = se
        th, ta = temp[(h, se)], temp[(a, se)]
        def ventana(t, n):
            u = hist[t][-n:]
            if not u:
                return None
            return sum(1.0 for (_, gf, ga, _) in u if gf > ga) / len(u)
        def split(t, home):
            u = [x for x in hist[t] if x[3] == home][-20:]
            return (sum(1.0 for (_, gf, ga, _) in u if gf > ga) / len(u)) if u else None
        def descanso(t):
            return (dt.date.fromisoformat(j["fecha"]) - dt.date.fromisoformat(hist[t][-1][0])).days if hist[t] else None
        hh = h2h[(h, a)]
        fila = {"liga": lg, "fecha": j["fecha"], "season": se, "y": 1.0 if j["rh"] > j["ra"] else 0.0, "margen": j["rh"] - j["ra"],
                "elo": (elo[h] + HFA - elo[a]) / 200.0,
                "dif": ((th["gf"] - th["ga"]) / th["n"] if th["n"] else 0.0) - ((ta["gf"] - ta["ga"]) / ta["n"] if ta["n"] else 0.0),
                "pct": ((th["w"] / th["n"]) if th["n"] else 0.5) - ((ta["w"] / ta["n"]) if ta["n"] else 0.5),
                "l10": (ventana(h, 10) or 0.5) - (ventana(a, 10) or 0.5),
                "l5": (ventana(h, 5) or 0.5) - (ventana(a, 5) or 0.5),
                "split": (split(h, True) or 0.5) - (split(a, False) or 0.5),
                "h2h": (hh[0] / hh[1] - 0.5) if hh[1] >= 3 else 0.0,
                "descanso": min(3, descanso(h) or 1) - min(3, descanso(a) or 1),
                "n_temp": min(th["n"], ta["n"]),
                "base": (base[lg][0] / base[lg][1]) if base[lg][1] >= 50 else 0.54}
        filas.append(fila)
        # actualizar con el resultado
        esp = _sig((elo[h] + HFA - elo[a]) / (400.0 / math.log(10)))
        res = 1.0 if j["rh"] > j["ra"] else 0.0
        d = K_ELO * max(math.log(abs(j["rh"] - j["ra"]) + 1), 0.7) * (res - esp)
        elo[h] += d; elo[a] -= d
        th["n"] += 1; th["w"] += res; th["gf"] += j["rh"]; th["ga"] += j["ra"]
        ta["n"] += 1; ta["w"] += 1 - res; ta["gf"] += j["ra"]; ta["ga"] += j["rh"]
        hist[h].append((j["fecha"], j["rh"], j["ra"], True)); hist[a].append((j["fecha"], j["ra"], j["rh"], False))
        hh[1] += 1; hh[0] += res
        rb = h2h[(a, h)]; rb[1] += 1; rb[0] += 1 - res
        base[lg][0] += res; base[lg][1] += 1
    return filas


# ------------------------------------------------------------------ ajuste (stdlib)
def _solve(A, b):
    n = len(b); M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            M[c][c] = 1e-12
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def logistica(filas, vars_, iters=25, l2=1e-3):
    """Regresion logistica por Newton con regularizacion ligera. Devuelve [b0, b1, ...]."""
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


def lineal(filas, vars_, objetivo="margen", l2=1e-3):
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
    beta = _solve(A, b)
    res = [yi - sum(bb * x for bb, x in zip(beta, xi)) for xi, yi in zip(X, y)]
    sd = math.sqrt(sum(r * r for r in res) / max(1, len(res) - p))
    return beta, sd


def _pred(beta, f, vars_):
    return _sig(beta[0] + sum(b * f[v] for b, v in zip(beta[1:], vars_)))


def walk_forward(filas, vars_, min_meses=12):
    """Cada mes se predice con lo ajustado en los meses anteriores. Devuelve (logloss, brier, brier_base, n, por_liga)."""
    meses = sorted({f["fecha"][:7] for f in filas})
    ll = br = bb = 0.0; n = 0
    por = defaultdict(lambda: [0.0, 0.0, 0])
    for i, m in enumerate(meses):
        if i < min_meses:
            continue
        train = [f for f in filas if f["fecha"][:7] < m and f["n_temp"] >= 5]
        test = [f for f in filas if f["fecha"][:7] == m and f["n_temp"] >= 5]
        if len(train) < 300 or not test:
            continue
        beta = logistica(train, vars_)
        for f in test:
            p = min(max(_pred(beta, f, vars_), 1e-4), 1 - 1e-4)
            ll += -(f["y"] * math.log(p) + (1 - f["y"]) * math.log(1 - p))
            br += (p - f["y"]) ** 2; bb += (f["base"] - f["y"]) ** 2; n += 1
            q = por[f["liga"]]; q[0] += (p - f["y"]) ** 2; q[1] += (f["base"] - f["y"]) ** 2; q[2] += 1
    return (ll / n if n else None, br / n if n else None, bb / n if n else None, n, por)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default="mlb,npb,kbo")
    ap.add_argument("--desde", default="2022-01-01")
    a = ap.parse_args()
    ligas = {LIGAS[x.strip()] for x in a.ligas.split(",") if x.strip() in LIGAS}
    js = juegos(ligas, a.desde)
    print("Juegos: %d (%s) desde %s" % (len(js), ", ".join(sorted(ligas)), a.desde))
    filas = capas(js)
    print("Con capas as-of y al menos 5 juegos de temporada por equipo: %d" % sum(1 for f in filas if f["n_temp"] >= 5))

    nucleo = ["elo", "dif"]
    ll0, br0, bb0, n0, por0 = walk_forward(filas, nucleo)
    print("\nGANADOR, walk-forward mes a mes (ELO + diferencial de temporada):")
    print("  n=%d  Brier %.4f  base %.4f  skill %+.2f%%" % (n0, br0, bb0, 100 * (bb0 - br0) / bb0))
    for lg, (b, bbase, n) in sorted(por0.items()):
        print("  %-4s n=%5d  Brier %.4f  base %.4f  skill %+.2f%%" % (lg, n, b / n, bbase / n, 100 * (bbase - b) / bbase))
    print("\nQue aporta cada capa por encima de ELO + diferencial (log-loss, milesimas; positivo = mejora):")
    for extra in ("pct", "l10", "l5", "split", "h2h", "descanso"):
        ll, br, _, n, _ = walk_forward(filas, nucleo + [extra])
        print("  %-9s %+.2f" % (extra, 1000 * (ll0 - ll)))
    beta = logistica([f for f in filas if f["n_temp"] >= 5], nucleo)
    bm, sd = lineal([f for f in filas if f["n_temp"] >= 5], nucleo)
    # pendiente logit por carrera de margen esperado: para traducir el aporte del abridor (carreras) a probabilidad
    for f in filas:
        f["m_esp"] = bm[0] + bm[1] * f["elo"] + bm[2] * f["dif"]
    bk = logistica([f for f in filas if f["n_temp"] >= 5], ["m_esp"])
    # RUN LINE: mapa calibrado de logit(p_gana) -> logit(p_cubre), por liga (el margen normal sobreestima la cobertura)
    for f in filas:
        f["lp"] = _logit(_pred(beta, f, nucleo))
    por_liga = {}
    for lg in sorted(ligas) + ["TODAS"]:
        sub = [f for f in filas if (lg == "TODAS" or f["liga"] == lg) and f["n_temp"] >= 5]
        if len(sub) < 300:
            continue
        m15 = logistica([dict(f, y=1.0 if f["margen"] >= 2 else 0.0) for f in sub], ["lp"])      # local cubre -1.5
        p15 = logistica([dict(f, y=1.0 if f["margen"] >= -1 else 0.0) for f in sub], ["lp"])     # local cubre +1.5
        por_liga[lg] = {"n": len(sub), "local_gana": round(sum(f["y"] for f in sub) / len(sub), 4),
                        "cubre_-1.5_real": round(sum(1 for f in sub if f["margen"] >= 2) / len(sub), 4),
                        "cubre_+1.5_real": round(sum(1 for f in sub if f["margen"] >= -1) / len(sub), 4),
                        "mapa_-1.5": [round(x, 4) for x in m15], "mapa_+1.5": [round(x, 4) for x in p15],
                        "nota": "logit(p_cubre) = a + b*logit(p_gana_local)"}
    out = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "juegos": len(js), "desde": a.desde, "ligas": sorted(ligas),
           "ganador": {"vars": nucleo, "beta": [round(x, 5) for x in beta], "nota": "logit(p_home) = b0 + b1*(elo_home+HFA-elo_away)/200 + b2*(dif_home-dif_away)"},
           "margen": {"vars": nucleo, "beta": [round(x, 5) for x in bm], "sd": round(sd, 4), "nota": "margen esperado del local; residuos ~ normal(sd)"},
           "logit_por_carrera": round(bk[1], 5),
           "walk_forward": {"n": n0, "brier": round(br0, 4), "brier_base": round(bb0, 4), "skill_pct": round(100 * (bb0 - br0) / bb0, 2)},
           "run_line": por_liga}
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with io.open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nGanador: logit = %.3f %+.3f*elo %+.3f*dif | margen = %.2f %+.2f*elo %+.2f*dif, sd %.2f | logit por carrera %.3f" % (
        beta[0], beta[1], beta[2], bm[0], bm[1], bm[2], sd, bk[1]))
    for lg, d in por_liga.items():
        print("  run line %-5s n=%5d  local cubre -1.5: %.3f  +1.5: %.3f  | mapa -1.5 %s  +1.5 %s" % (
            lg, d["n"], d["cubre_-1.5_real"], d["cubre_+1.5_real"], d["mapa_-1.5"], d["mapa_+1.5"]))
    print("Guardado:", SALIDA)


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


if __name__ == "__main__":
    main()
