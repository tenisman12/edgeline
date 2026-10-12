# -*- coding: utf-8 -*-
"""
utilidades/minar_portero_confirmado.py - cuanto vale saber el portero titular confirmado en NHL
(hipotesis en trabajo/minar/2026-10-11_portero_confirmado.md).

Walk-forward como utilidades/medir_porteros_nhl.py. Por partido, tres versiones del modelo de NHL:
  A sin portero | B portero supuesto (el que mas abrio en los ultimos 10 juegos del equipo) | C portero real.
Valor de confirmar = C contra B (todos los partidos y los 'sorpresa', donde el real no es el supuesto).
Contra el mercado (ESPN, 2 vias): logit p_mercado + b (logit p_C - logit p_B), apertura y cierre, b en el 70 %.

    python utilidades/minar_portero_confirmado.py
Escribe trabajo/minar/2026-10-11_portero_confirmado_resultados.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, datetime as dt, json, math, os, sys
from collections import Counter, defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
from nucleo import io  # noqa: E402
from modelos import hockey as H  # noqa: E402
import medir_porteros_nhl as MP  # noqa: E402

K, N_ULT = H.GSAX_K, H.GSAX_N
BETAS = (H.GSAX_BETA, 0.5, 1.0)
SALIDA = os.path.join(CODIGO, "trabajo", "minar", "2026-10-11_portero_confirmado_resultados.json")


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def resumen(d):
    n = len(d)
    if n < 2:
        return {"n": n}
    h = n // 2; mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) or 1e-9
    z = mu / (sd / math.sqrt(n))
    mit = [sum(d[:h]), sum(d[h:])]
    return {"n": n, "mejora_mil": round(1000 * mu, 3), "z": round(z, 2), "mitades": [round(x, 2) for x in mit],
            "veredicto": "pasa" if (n >= 300 and z >= 2 and min(mit) > 0) else ("muestra insuficiente" if n < 300 else "no pasa")}


def supuestos():
    """{(gamePk, equipo): portero supuesto} = el que mas abrio en los 10 juegos anteriores del equipo (empate: el mas reciente)."""
    filas = []
    with open(os.path.join(io.BASE, "datos", "hockey.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("league") or "NHL") != "NHL":
                continue
            g = (r.get("starter_goalie") or "").strip()
            filas.append(((r.get("game_date") or "")[:10], str(r.get("gamePk") or "").split(".")[0], r.get("team"), g))
    filas.sort()
    hist = defaultdict(list); out = {}
    for f, gp, t, g in filas:
        prev = [x for x in hist[t][-10:] if x]
        if prev:
            c = Counter(prev); top = max(c.values())
            out[(gp, t)] = next(x for x in reversed(prev) if c[x] == top)
        if g:
            hist[t].append(g)
    return out


def main():
    juegos = H._juegos(None)
    G = [(f, gp, h, a) for f, gp, h, a in juegos if MP._f(h.get("goals")) is not None and MP._f(h.get("goals_opp")) is not None]
    ultimo = dt.date.fromisoformat(G[-1][0]); ini = ultimo - dt.timedelta(days=int(24 * 30.4))
    gs = MP.gsax_por_partido()
    real = {(gp, t): g for _, gp, t, g, _ in gs}
    sup = supuestos()
    filas = []; orig = io.cargar_juegos; d0 = ini
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
            tot_prev = [MP._f(g[2]["goals"]) + MP._f(g[2]["goals_opp"]) for g in prev]
            L = math.floor(sum(tot_prev) / len(tot_prev)) + 0.5
            for f, gp, h, a in blk:
                th, ta = h.get("team"), a.get("team")
                xh, xa = H._xg(est, th, ta)
                if xh is None:
                    continue
                rh, ra = real.get((gp, th)), real.get((gp, ta))
                sh, sa = sup.get((gp, th)), sup.get((gp, ta))
                if not (rh and ra and sh and sa):
                    continue
                filas.append({"f": f, "gp": gp, "home": th, "away": ta, "xh": xh, "xa": xa, "gh": MP._f(h["goals"]),
                              "ga": MP._f(h["goals_opp"]), "L": L, "pl": est["platt"], "lg": est["lg"],
                              "rh": rh, "ra": ra, "sh": sh, "sa": sa})
        d0 = d1
    filas.sort(key=lambda r: r["f"])
    print("Partidos con portero real y supuesto de los dos lados: %d (%s a %s)" % (len(filas), filas[0]["f"], filas[-1]["f"]))
    # ratings GSAx as-of (antes del partido)
    by_date = defaultdict(list)
    for fch, gp, t, g, v in gs:
        by_date[fch].append((g, v))
    R = MP.Rating(); fechas = sorted(by_date); j = 0
    for r in filas:
        while j < len(fechas) and fechas[j] < r["f"]:
            for g, v in by_date[fechas[j]]:
                R.add(g, v)
            j += 1
        for k in ("rh", "ra", "sh", "sa"):
            r["g_" + k] = R.get(r[k], K)
    sorpresa = [r for r in filas if r["rh"] != r["sh"] or r["ra"] != r["sa"]]
    print("Partidos sorpresa (al menos un titular distinto al supuesto): %d (%.1f %%)" % (len(sorpresa), 100 * len(sorpresa) / len(filas)))
    dif = [abs((r["g_rh"] - r["g_sh"])) + abs(r["g_ra"] - r["g_sa"]) for r in sorpresa]
    print("  diferencia media de GSAx por juego entre real y supuesto en esos partidos: %.3f goles" % (sum(dif) / len(dif)))

    def pred(r, B, ver):
        if ver == "A":
            gh = ga = 0.0
        elif ver == "B":
            gh, ga = r["g_sh"], r["g_sa"]
        else:
            gh, ga = r["g_rh"], r["g_ra"]
        xh = max(r["xh"] - B * ga, 0.3); xa = max(r["xa"] - B * gh, 0.3)
        a, b = r["pl"]; ph = H._prob_home(xh, xa)
        p = H._sig(a * _lg(ph) + b)
        mu = xh + xa; lg2 = 2 * r["lg"]; mu = lg2 + H.TOT_K * (mu - lg2)
        return p, mu

    res = {"n": len(filas), "n_sorpresa": len(sorpresa), "comparaciones": {}}
    for B in BETAS:
        for nom, sub in (("todos", filas), ("sorpresa", sorpresa)):
            for c1, c2 in (("C", "B"), ("C", "A"), ("B", "A")):
                dg, dt_, do = [], [], []
                for r in sub:
                    y = 1 if r["gh"] > r["ga"] else 0; tot = r["gh"] + r["ga"]
                    p1, m1 = pred(r, B, c1); p2, m2 = pred(r, B, c2)
                    dg.append(MP._ll(p2, y) - MP._ll(p1, y))
                    dt_.append(abs(m2 - tot) - abs(m1 - tot))
                    do.append(MP._ll(MP._p_over(m2, r["L"]), 1 if tot > r["L"] else 0) - MP._ll(MP._p_over(m1, r["L"]), 1 if tot > r["L"] else 0))
                clave = "beta%.2f|%s|%s_vs_%s" % (B, nom, c1, c2)
                res["comparaciones"][clave] = {"ganador": resumen(dg), "total_mae": resumen(dt_), "over_under": resumen(do)}
                s = res["comparaciones"][clave]
                print("  %-34s ganador %+.3f mil (z %5.2f)  total %+.3f (z %5.2f)  O/U %+.3f (z %5.2f)  n %d" % (
                    clave, s["ganador"]["mejora_mil"], s["ganador"]["z"], s["total_mae"]["mejora_mil"], s["total_mae"]["z"],
                    s["over_under"]["mejora_mil"], s["over_under"]["z"], s["ganador"]["n"]))
    # ---- contra el mercado: cuotas de ESPN a 2 vias
    try:
        import minar_ganador_cuota_espn as GE
        import metamodelo as MT
        CU = GE.cuotas_por_juego()
        loc = GE.mapa_ids("nhl", [{"fecha": r["f"], "home": r["home"], "away": r["away"]} for r in filas])
        mk = []
        for r in filas:
            gid = loc.get((r["f"], r["home"], r["away"])) or loc.get((r["f"], r["home"], None))
            rows = CU.get(("nhl", gid)) if gid else None
            if not rows:
                continue
            no, nc = [], []
            for x in rows:
                h_, a_ = MT._dec_ml(x.get("ml_home_close") or x.get("ml_home")), MT._dec_ml(x.get("ml_away_close") or x.get("ml_away"))
                ho, ao = MT._dec_ml(x.get("ml_home_open")), MT._dec_ml(x.get("ml_away_open"))
                if h_ and a_ and 1 / h_ + 1 / a_ >= 1.0:
                    nc.append(MT._novig(h_, a_)[0])
                if ho and ao and 1 / ho + 1 / ao >= 1.0:
                    no.append(MT._novig(ho, ao)[0])
            if not no or not nc:
                continue
            pB, _ = pred(r, BETAS[0], "B"); pC, _ = pred(r, BETAS[0], "C")
            mk.append({"f": r["f"], "y": 1 if r["gh"] > r["ga"] else 0, "open": sum(no) / len(no), "close": sum(nc) / len(nc),
                       "x": _lg(pC) - _lg(pB), "sorpresa": r["rh"] != r["sh"] or r["ra"] != r["sa"]})
        print("\nContra el mercado (ESPN, 2 vias): %d partidos con apertura y cierre" % len(mk))
        res["mercado"] = {"n": len(mk)}
        # el mercado se mueve hacia el portero real? (cierre - apertura contra C - B)
        s = [m for m in mk if m["sorpresa"]]
        if s:
            mov = [_lg(m["close"]) - _lg(m["open"]) for m in s]; xx = [m["x"] for m in s]
            mx, my = sum(xx) / len(xx), sum(mov) / len(mov)
            cov = sum((a - mx) * (b - my) for a, b in zip(xx, mov)); vx = sum((a - mx) ** 2 for a in xx); vy = sum((b - my) ** 2 for b in mov)
            corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0
            res["mercado"]["corr_movimiento_vs_portero_sorpresa"] = round(corr, 3)
            res["mercado"]["pendiente_movimiento"] = round(cov / vx, 3) if vx > 0 else None
            print("  en sorpresa (n %d): correlacion entre (C - B) y el movimiento apertura->cierre: %.3f; pendiente %.3f" % (
                len(s), corr, cov / vx if vx else float("nan")))
        c = int(len(mk) * 0.7)
        for ref in ("open", "close"):
            for nom, filt in (("todos", lambda m: True), ("sorpresa", lambda m: m["sorpresa"])):
                E = [m for m in mk[:c] if filt(m)]; T = [m for m in mk[c:] if filt(m)]
                if len(E) < 50 or len(T) < 30:
                    continue
                b = 0.0
                for _ in range(30):
                    gsum = sum(m["x"] * (m["y"] - _sig(_lg(m[ref]) + b * m["x"])) for m in E)
                    hs = sum(m["x"] ** 2 * _sig(_lg(m[ref]) + b * m["x"]) * (1 - _sig(_lg(m[ref]) + b * m["x"])) for m in E)
                    if hs <= 0:
                        break
                    b += gsum / hs
                d = [MP._ll(m[ref], m["y"]) - MP._ll(_sig(_lg(m[ref]) + b * m["x"]), m["y"]) for m in T]
                s2 = resumen(d); s2["b"] = round(b, 3)
                res["mercado"]["%s|%s" % (ref, nom)] = s2
                print("  contra %-5s %-8s b %+.2f  prueba n %d  mejora %+.3f mil  z %.2f  mitades %s -> %s" % (
                    "apertura" if ref == "open" else "cierre", nom, b, s2["n"], s2["mejora_mil"], s2["z"], s2["mitades"], s2["veredicto"]))
    except Exception as e:
        print("mercado: no se pudo (%s)" % e)
    json.dump(res, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nescrito", SALIDA)


if __name__ == "__main__":
    main()
