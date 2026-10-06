# -*- coding: utf-8 -*-
"""
utilidades/medir_porteros_nhl.py - mide si la calidad del portero titular (GSAx as-of) mejora al modelo de NHL.

GSAx (goles salvados sobre lo esperado) por partido del portero que abrio = xG en contra de su equipo (MoneyPuck, 'all')
menos los goles que recibio el equipo. Como las tasas del modelo ya usan 75 % xG, la defensa del equipo casi no ve al
portero: esta capa agrega lo que el portero ataja por encima (o por debajo) de lo esperado.

Rating as-of del portero = suma de GSAx de sus ultimas N aperturas / (aperturas + K)  (encogido hacia 0 = promedio).
Ajuste: goles esperados del rival -= BETA * rating.

Walk-forward igual que utilidades/validar_mercados.py (bloques de 30 dias, el modelo se entrena solo con lo anterior;
el titular real se usa como si fuera el anunciado, que es lo que da Daily Faceoff antes del juego). Compara contra el
modelo sin portero en: Ganador (log-loss), Total esperado (MAE) y Over/Under en la linea ~promedio (log-loss),
total y por mitades. Imprime la mejor combinacion y escribe modelos/porteros_nhl.json con el veredicto.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\medir_porteros_nhl.py
"""
import csv, json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io
from modelos import hockey as H

BETAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25)
KS = (10, 20, 40)
N_ULT = 40


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def gsax_por_partido():
    """[(fecha, gamePk, equipo, portero, gsax)] en orden: xGA del equipo - goles recibidos, atribuido al abridor."""
    X = H._xg_partidos()
    out = []
    with open(os.path.join(io.BASE, "datos", "hockey.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            g = (r.get("starter_goalie") or "").strip()
            gp = str(r.get("gamePk") or "").split(".")[0]
            x = X.get((gp, r.get("team")))
            ga = _f(r.get("goals_opp"))
            if not g or not x or ga is None:
                continue
            ga_ = ga - (1 if (r.get("ended_in") or "") == "SO" and ga > _f(r.get("goals") or 0) else 0)   # gol de shootout
            out.append(((r.get("game_date") or "")[:10], gp, r.get("team"), g, x[1] - ga_))
    out.sort()
    return out


class Rating:
    def __init__(s):
        s.h = {}

    def add(s, g, v):
        s.h.setdefault(g, []).append(v)

    def get(s, g, K):
        v = s.h.get(g) or []
        v = v[-N_ULT:]
        return sum(v) / (len(v) + K) if v else 0.0


def _pois(m, k):
    return math.exp(-m) * m ** k / math.factorial(k)


def _p_over(mu, L):
    return 1 - sum(_pois(mu, k) for k in range(int(math.floor(L)) + 1))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def main():
    juegos = H._juegos(None)
    G = [(f, gp, h, a) for f, gp, h, a in juegos if _f(h.get("goals")) is not None and _f(h.get("goals_opp")) is not None]
    ultimo = dt.date.fromisoformat(G[-1][0]); ini = ultimo - dt.timedelta(days=int(24 * 30.4))
    gs = gsax_por_partido()
    idx_g = {(gp, t): g for _, gp, t, g, _ in gs}
    filas = []          # por partido: base y lo necesario para recalcular con cada (beta, K)
    orig = io.cargar_juegos
    d0 = ini
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=30)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        if blk and len(prev) >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = H.entrenar(None)
            finally:
                io.cargar_juegos = orig
            tot_prev = [_f(g[2]["goals"]) + _f(g[2]["goals_opp"]) for g in prev]
            L = math.floor(sum(tot_prev) / len(tot_prev)) + 0.5
            fr_over = sum(1 for t in tot_prev if t > L) / len(tot_prev)
            for f, gp, h, a in blk:
                th, ta = h.get("team"), a.get("team")
                xh, xa = H._xg(est, th, ta)
                if xh is None:
                    continue
                gh, ga = _f(h["goals"]), _f(h["goals_opp"])
                filas.append({"f": f, "gp": gp, "xh": xh, "xa": xa, "gh": gh, "ga": ga, "L": L, "fr": fr_over,
                              "pl": est["platt"], "lg": est["lg"], "gh_": idx_g.get((gp, th)), "ga_": idx_g.get((gp, ta))})
        d0 = d1
    print("Partidos en la ventana: %d (con portero de ambos: %d)" % (len(filas), sum(1 for r in filas if r["gh_"] and r["ga_"])))
    # ratings as-of: se recorren los partidos en orden y el rating se toma ANTES de sumar el partido
    by_date = {}
    for fch, gp, t, g, v in gs:
        by_date.setdefault(fch, []).append((g, v))
    res = {}
    for K in KS:
        R = Rating(); fechas = sorted(by_date); j = 0
        rat = {}
        filas_s = sorted(filas, key=lambda r: r["f"])
        for r in filas_s:
            while j < len(fechas) and fechas[j] < r["f"]:
                for g, v in by_date[fechas[j]]:
                    R.add(g, v)
                j += 1
            rat[r["gp"]] = (R.get(r["gh_"], K) if r["gh_"] else 0.0, R.get(r["ga_"], K) if r["ga_"] else 0.0)
        for B in BETAS:
            m = {"gan": [], "tot": [], "ou": []}
            for r in filas_s:
                rh, ra = rat[r["gp"]]
                xh = max(r["xh"] - B * ra, 0.3); xa = max(r["xa"] - B * rh, 0.3)
                a, b = r["pl"]
                p = H._sig(a * math.log(H._prob_home(xh, xa) / (1 - H._prob_home(xh, xa))) + b)
                mu = xh + xa; lg2 = 2 * r["lg"]; mu = lg2 + H.TOT_K * (mu - lg2)
                tot = r["gh"] + r["ga"]
                m["gan"].append(_ll(p, 1 if r["gh"] > r["ga"] else 0))
                m["tot"].append(abs(mu - tot))
                m["ou"].append(_ll(_p_over(mu, r["L"]), 1 if tot > r["L"] else 0))
            res[(K, B)] = m
    base = res[(KS[0], 0.0)]
    n = len(base["gan"]); h = n // 2
    def resumen(m):
        out = {}
        for k in ("gan", "tot", "ou"):
            d = [b - x for b, x in zip(base[k], m[k])]          # positivo = mejora
            mu = sum(d) / n; sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) or 1e-9
            out[k] = {"mejora": round(mu * 1000, 3), "z": round(mu / (sd / math.sqrt(n)), 2),
                      "mitades": [round(1000 * sum(d[:h]) / h, 3), round(1000 * sum(d[h:]) / (n - h), 3)]}
        return out
    print("\nMejora contra el modelo sin portero (milesimas; Ganador y O/U en log-loss, Total en MAE de goles):")
    tabla = {}
    for K in KS:
        for B in BETAS[1:]:
            s = resumen(res[(K, B)]); tabla["K%d_B%.2f" % (K, B)] = s
            print("  K=%-3d beta=%.2f  ganador %+.2f (z %.2f)  total %+.2f (z %.2f)  O/U %+.2f (z %.2f)" % (
                K, B, s["gan"]["mejora"], s["gan"]["z"], s["tot"]["mejora"], s["tot"]["z"], s["ou"]["mejora"], s["ou"]["z"]))
    def ok(s, k):
        return s[k]["z"] >= 2.0 and min(s[k]["mitades"]) > 0 and n >= 300
    mejor = {}
    for k in ("gan", "tot", "ou"):
        cands = [(v[k]["mejora"], c) for c, v in tabla.items() if ok(v, k)]
        mejor[k] = max(cands)[1] if cands else None
    print("\nVeredicto (z >= 2 y mejora en las dos mitades):")
    for k, nom in (("gan", "Ganador"), ("tot", "Total esperado"), ("ou", "Over/Under")):
        print("  %-15s %s" % (nom, ("APLICAR " + mejor[k]) if mejor[k] else "sin mejora demostrada"))
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "porteros_nhl.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": dt.datetime.now().isoformat(timespec="seconds"), "n": n, "n_ultimas": N_ULT,
                   "tabla": tabla, "mejor": mejor}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
