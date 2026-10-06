# -*- coding: utf-8 -*-
"""
utilidades/minar_kalman_beisbol.py - mineria: fuerza dinamica con filtro de Kalman (MLB y KBO, ganador).
Hipotesis registrada en trabajo/minar/2026-10-06_kalman_beisbol.md.

Walk-forward igual que la validacion (bloques de 30 dias, logistica entrenada con lo anterior; KBO con la capa de
abridores). Senal Kalman as-of. 70 % antiguo para ajustar beta, 30 % reciente para probar una vez.
Escribe trabajo/minar/kalman_beisbol.json.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\minar_kalman_beisbol.py
"""
import json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, features as F, abridores as AB
from modelos import beisbol as B

QS = {"q_baja": 0.002, "q_alta": 0.01}


def _lo(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def kalman(G, q_rel):
    """senal as-of por gamePk: (m_h - m_a) / sqrt(s2 + P_h + P_a)."""
    m, P, temp = {}, {}, {}
    margenes = [r["marg_home"] for r in G[:300]]
    mu0 = sum(margenes) / len(margenes)
    s2 = sum((x - mu0) ** 2 for x in margenes) / len(margenes)
    h = mu0; n_h = 300
    q = q_rel * s2; P0 = 0.15 * s2
    ult = {}; out = {}
    for r in G:
        f = r["game_date"][:10]; s = r["season"]
        for t in (r["home"], r["away"]):
            if t not in m:
                m[t], P[t], temp[t] = 0.0, P0, s
            if temp[t] != s:                      # cambio de temporada: regresa 1/3 y se infla la incertidumbre
                m[t] *= 2 / 3; P[t] = P[t] + P0 * 0.5; temp[t] = s
            if t in ult:
                dias = max(1, (dt.date.fromisoformat(f) - dt.date.fromisoformat(ult[t])).days)
                P[t] += q * min(dias, 10)
        th, ta = r["home"], r["away"]
        S = s2 + P[th] + P[ta]
        out[r["gamePk"]] = (m[th] - m[ta] + h) / math.sqrt(S)
        e = r["marg_home"] - (m[th] - m[ta] + h)
        kh, ka = P[th] / S, P[ta] / S
        m[th] += kh * e; m[ta] -= ka * e
        P[th] *= (1 - kh); P[ta] *= (1 - ka)
        h = (h * n_h + r["marg_home"]) / (n_h + 1); n_h = min(n_h + 1, 3000)
        ult[th] = ult[ta] = f
    return out


def filas(liga):
    feats, _ = F.construir("beisbol", liga, 5)
    lg = io.norm(liga)
    G = [r for r in feats if r["league"] == lg and r.get("y_home") is not None and r.get("marg_home") is not None]
    G.sort(key=lambda r: r["game_date"])
    VAB = AB.historicos(io.BASE) if lg == "kbo" else {}
    senales = {k: kalman(G, q) for k, q in QS.items()}
    d0 = dt.date.fromisoformat(G[0]["game_date"][:10]); ultimo = dt.date.fromisoformat(G[-1]["game_date"][:10])
    out = []
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=30)
        blk = [r for r in G if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in G if r["game_date"][:10] < d0.isoformat()]
        if blk and len(prev) >= 500:
            mod = B.entrenar_logistica(prev)
            if mod:
                hw = sum(r["y_home"] for r in prev) / len(prev)
                for r in blk:
                    p = B.prob(mod, r)
                    if VAB:
                        vh, va = VAB.get((r["gamePk"], r["home"])), VAB.get((r["gamePk"], r["away"]))
                        if vh and va:
                            sh, sa = AB.carreras_salvadas(r.get("df_home"), vh), AB.carreras_salvadas(r.get("df_away"), va)
                            p = _sig(_lo(p) + AB.K_GANADOR * (sh - sa))
                    out.append({"f": r["game_date"][:10], "p": p, "y": r["y_home"], "base": hw,
                                **{k: senales[k].get(r["gamePk"], 0.0) for k in QS}})
        d0 = d1
    return out


def ajustar_beta(E, k):
    b = 0.0
    for _ in range(30):
        g = h = 0.0
        for x in E:
            p = _sig(_lo(x["p"]) + b * x[k]); g += (p - x["y"]) * x[k]; h += p * (1 - p) * x[k] ** 2
        b -= g / (h + 1e-6)
    return b


def main():
    res = {"hipotesis": "trabajo/minar/2026-10-06_kalman_beisbol.md", "k_variantes": len(QS), "ligas": {}}
    for liga in ("MLB", "KBO"):
        Fl = filas(liga)
        c = int(len(Fl) * 0.7); E, T = Fl[:c], Fl[c:]
        n = len(T); h = n // 2
        print("\n%s: %d partidos (ajuste %d hasta %s, prueba %d desde %s)" % (liga, len(Fl), len(E), E[-1]["f"], n, T[0]["f"]))
        out = {}
        for k in QS:
            b = ajustar_beta(E, k)
            pm = [_sig(_lo(x["p"]) + b * x[k]) for x in T]
            dm = [_ll(x["p"], x["y"]) - _ll(p, x["y"]) for p, x in zip(pm, T)]
            db = [_ll(x["base"], x["y"]) - _ll(p, x["y"]) for p, x in zip(pm, T)]
            d0 = [_ll(x["base"], x["y"]) - _ll(x["p"], x["y"]) for x in T]
            def st(d):
                mu = sum(d) / n; sd = math.sqrt(sum((v - mu) ** 2 for v in d) / (n - 1)) or 1e-9
                return {"mejora_milesimas": round(1000 * mu, 3), "z": round(mu / (sd / math.sqrt(n)), 2),
                        "mitades": [round(1000 * sum(d[:h]) / h, 3), round(1000 * sum(d[h:]) / (n - h), 3)]}
            sm, sb, s0 = st(dm), st(db), st(d0)
            cal = {"p_media": round(sum(pm) / n, 4), "tasa_real": round(sum(x["y"] for x in T) / n, 4)}
            ok = n >= 300 and sm["z"] >= 2.0 and min(sm["mitades"]) > 0 and abs(cal["p_media"] - cal["tasa_real"]) <= 0.04
            out[k] = {"beta": round(b, 4), "contra_modelo_actual": sm, "contra_base": sb, "modelo_actual_contra_base": s0,
                      "calibracion": cal, "veredicto": "pasa" if ok else "no pasa"}
            print("  %-7s beta %+.3f | vs modelo %+.2f (z %.2f, mitades %s) | vs base %+.2f (z %.2f) [modelo solo %+.2f, z %.2f] | p %.3f real %.3f -> %s" % (
                k, b, sm["mejora_milesimas"], sm["z"], sm["mitades"], sb["mejora_milesimas"], sb["z"], s0["mejora_milesimas"], s0["z"],
                cal["p_media"], cal["tasa_real"], out[k]["veredicto"]))
        res["ligas"][liga] = out
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trabajo", "minar", "kalman_beisbol.json")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(res, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
