# -*- coding: utf-8 -*-
"""
utilidades/minar_velocidad_tenis.py - mineria: velocidad del torneo y saque por superficie en breaks y games de tenis.
Hipotesis registrada en trabajo/minar/2026-10-06_velocidad_tenis.md.

Recorre datos/tenis.csv en orden (as-of partido a partido, igual que validar_tenis), guarda por partido la prediccion
actual del modelo (games y breaks con su ajuste de sesgo) y dos senales as-of:
  V1 velocidad del torneo (residuo de % al saque en ediciones/rondas anteriores del mismo torneo),
  V2 saque en superficie (% al saque del jugador en la superficie menos su % de carrera, sumado).
Ajusta el residuo con V1/V2 en el 70 % antiguo y prueba en el 30 % reciente. Escribe trabajo/minar/velocidad_tenis.json.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\minar_velocidad_tenis.py
"""
import csv, io as _io, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io
from modelos import tenis as T
from utilidades.validar_mercados import _games_sets, _f

MIN_J = 10
K_TORNEO, K_SUP = 300.0, 400.0      # puntos de saque para encoger las senales hacia 0


def recorrer():
    with _io.open(os.path.join(io.BASE, "datos", "tenis.csv"), encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows.sort(key=lambda r: (r.get("tourney_date", ""), r.get("winner_name", "")))
    J, tsp, TOR, RES, RESB, HB = {}, {}, {}, {}, {}, {}
    out = []
    def g(n): return J.setdefault(n, {"sp": 0., "spw": 0., "rp": 0., "rpw": 0., "elo": {}, "sup": {}})
    for r in rows:
        w, l = r.get("winner_name"), r.get("loser_name")
        sup = (r.get("surface") or "Hard").strip() or "Hard"
        bo = 5 if str(r.get("best_of")).split(".")[0] == "5" else 3
        try:
            wsv = float(r["w_svpt"]); wsw = float(r["w_1stWon"]) + float(r["w_2ndWon"])
            lsv = float(r["l_svpt"]); lsw = float(r["l_1stWon"]) + float(r["l_2ndWon"])
        except (KeyError, ValueError, TypeError):
            continue
        if not w or not l or wsv <= 0 or lsv <= 0:
            continue
        tour = (r.get("tour") or "TOUR").upper()
        tt = tsp.setdefault(tour, [0.0, 0.0]); tour_spw = (tt[1] / tt[0]) if tt[0] else 0.635
        jw, jl = g(w), g(l)
        games, nsets, ok = _games_sets(r.get("score"))
        brk = None
        if None not in (_f(r.get("w_bpFaced")), _f(r.get("l_bpFaced")), _f(r.get("w_bpSaved")), _f(r.get("l_bpSaved"))):
            brk = (_f(r["w_bpFaced"]) - _f(r["w_bpSaved"])) + (_f(r["l_bpFaced"]) - _f(r["l_bpSaved"]))
        tk = (tour, (r.get("tourney_name") or "").strip().lower())
        tor = TOR.setdefault(tk, [0.0, 0.0])        # suma de (real - esperado) en puntos, puntos
        esp_w = jw["spw"] / jw["sp"] if jw["sp"] else tour_spw
        esp_l = jl["spw"] / jl["sp"] if jl["sp"] else tour_spw
        if jw["sp"] >= MIN_J * 50 and jl["sp"] >= MIN_J * 50:
            p1n, p2n = (w, l) if w < l else (l, w)
            j1, j2 = g(p1n), g(p2n)
            d1 = {"spw": j1["spw"] / j1["sp"], "rpw": j1["rpw"] / max(j1["rp"], 1)}
            d2 = {"spw": j2["spw"] / j2["sp"], "rpw": j2["rpw"] / max(j2["rp"], 1)}
            e1 = j1["elo"].get(sup, 1500.0); e2 = j2["elo"].get(sup, 1500.0)
            lineas = (20.5, 22.5, 24.5) if bo == 3 else (34.5, 38.5, 42.5)
            Rg = RES.setdefault((tour, bo), [])
            aj = (sum(Rg[-400:]) / len(Rg[-400:])) if len(Rg) >= 150 else 0.0
            pr = T.predecir(d1, d2, sup, bo, tour_spw, lineas[1], e1, e2, aj)
            Rb = RESB.setdefault((tour, bo), [])
            ajb = (sum(Rb[-400:]) / len(Rb[-400:])) if len(Rb) >= 150 else 0.0
            v1 = tor[0] / (tor[1] + K_TORNEO)
            def dsup(j):
                s = j["sup"].get(sup)
                if not s or not j["sp"]:
                    return 0.0
                return (s[1] - s[0] * (j["spw"] / j["sp"])) / (s[0] + K_SUP)
            v2 = dsup(j1) + dsup(j2)
            hb = HB.setdefault((tour, bo), [])
            out.append({"f": r.get("tourney_date", ""), "tour": tour, "bo": bo,
                        "games": games if (ok and games) else None, "g_pred": pr["games_esperados"],
                        "brk": brk, "b_pred": max(0.1, pr["breaks_esperados"] + ajb), "v1": v1, "v2": v2,
                        "b_base": (sum(hb) / len(hb)) if len(hb) > 200 else None})
            if ok and games: Rg.append(games - pr["games_sin_ajuste"])
            if brk is not None: Rb.append(brk - pr["breaks_esperados"])
        if brk is not None:
            HB.setdefault((tour, bo), []).append(brk)
        # actualizar senales DESPUES de predecir
        tor[0] += (wsw - wsv * esp_w) + (lsw - lsv * esp_l); tor[1] += wsv + lsv
        for j, sv, sw in ((jw, wsv, wsw), (jl, lsv, lsw)):
            s = j["sup"].setdefault(sup, [0.0, 0.0]); s[0] += sv; s[1] += sw
        jw["sp"] += wsv; jw["spw"] += wsw; jw["rp"] += lsv; jw["rpw"] += (lsv - lsw)
        jl["sp"] += lsv; jl["spw"] += lsw; jl["rp"] += wsv; jl["rpw"] += (wsv - wsw)
        ew = jw["elo"].get(sup, 1500.0); el = jl["elo"].get(sup, 1500.0)
        exp = 1 / (1 + 10 ** (-(ew - el) / 400)); jw["elo"][sup] = ew + 24 * (1 - exp); jl["elo"][sup] = el - 24 * (1 - exp)
        tt[0] += wsv + lsv; tt[1] += wsw + lsw
    return out


def ols(X, y, l2=1e-2):
    k = len(X[0]); A = [[0.0] * (k + 1) for _ in range(k)]
    for xi, yi in zip(X, y):
        for i in range(k):
            A[i][k] += xi[i] * yi
            for j in range(k): A[i][j] += xi[i] * xi[j]
    for i in range(k): A[i][i] += l2
    for i in range(k):
        p = A[i][i] or 1e-9
        for j in range(i, k + 1): A[i][j] /= p
        for r in range(k):
            if r != i:
                fc = A[r][i]
                for j in range(i, k + 1): A[r][j] -= fc * A[i][j]
    return [A[i][k] for i in range(k)]


def _pois_over(mu, L):
    return 1 - sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(int(L) + 1))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def probar(F, campo, pred, nombre_grupo):
    F = [x for x in F if x[campo] is not None]
    if len(F) < 1000:
        return None
    c = int(len(F) * 0.7); E, Tt = F[:c], F[c:]
    n = len(Tt); h = n // 2
    res = {"n_ajuste": len(E), "n_prueba": n, "desde": Tt[0]["f"]}
    for nom, cols in (("V1_torneo", ["v1"]), ("V2_superficie", ["v2"]), ("V1+V2", ["v1", "v2"])):
        b = ols([[x[cc] for cc in cols] for x in E], [x[campo] - x[pred] for x in E])
        p1 = [x[pred] + sum(bi * x[cc] for bi, cc in zip(b, cols)) for x in Tt]
        dm = [abs(x[campo] - x[pred]) - abs(x[campo] - q) for q, x in zip(p1, Tt)]
        ds = [(x[campo] - x[pred]) ** 2 - (x[campo] - q) ** 2 for q, x in zip(p1, Tt)]
        def st(d):
            mu = sum(d) / n; sd = math.sqrt(sum((v - mu) ** 2 for v in d) / (n - 1)) or 1e-9
            return round(mu, 4), round(mu / (sd / math.sqrt(n)), 2), [round(sum(d[:h]) / h, 4), round(sum(d[h:]) / (n - h), 4)]
        mae, zmae, mit = st(dm); mse, zmse, mits = st(ds)
        r_ = {"coef": [round(v, 3) for v in b], "mejora_mae": mae, "z_mae": zmae, "mitades_mae": mit, "mejora_mse": mse, "z_mse": zmse,
              "mitades_mse": mits}
        if campo == "brk":           # O/U de breaks en la linea ~promedio, distribucion de Poisson como el modelo
            do = []
            for q, x in zip(p1, Tt):
                if x["b_base"] is None: continue
                L = math.floor(x["b_base"]) + 0.5; y = 1 if x["brk"] > L else 0
                do.append(_ll(_pois_over(x[pred], L), y) - _ll(_pois_over(max(q, 0.1), L), y))
            if do:
                m_ = len(do); mu = sum(do) / m_; sd = math.sqrt(sum((v - mu) ** 2 for v in do) / (m_ - 1)) or 1e-9
                r_["ou"] = {"n": m_, "mejora_milesimas": round(1000 * mu, 3), "z": round(mu / (sd / math.sqrt(m_)), 2),
                            "mitades": [round(1000 * sum(do[:m_ // 2]) / (m_ // 2), 3), round(1000 * sum(do[m_ // 2:]) / (m_ - m_ // 2), 3)]}
        ok = n >= 300 and ((zmae >= 2.0 and min(mit) > 0) or (zmse >= 2.0 and min(mits) > 0))
        if "ou" in r_:
            ok = ok and r_["ou"]["z"] >= 2.0 and min(r_["ou"]["mitades"]) > 0
        r_["veredicto"] = "pasa" if ok else "no pasa"
        res[nom] = r_
        print("  %-10s %-6s %-13s n=%d  MAE %+.4f (z %.2f, %s)  MSE %+.3f (z %.2f)%s  coef %s -> %s" % (
            nombre_grupo, campo, nom, n, mae, zmae, mit, mse, zmse,
            ("  O/U %+.2f (z %.2f, %s)" % (r_["ou"]["mejora_milesimas"], r_["ou"]["z"], r_["ou"]["mitades"])) if "ou" in r_ else "",
            r_["coef"], r_["veredicto"]))
    return res


def main():
    F = recorrer()
    print("Partidos con prediccion: %d" % len(F))
    res = {"hipotesis": "trabajo/minar/2026-10-06_velocidad_tenis.md", "k_variantes": 3, "grupos": {}}
    for tour in ("ATP", "WTA"):
        for bo in (3, 5):
            G = [x for x in F if x["tour"] == tour and x["bo"] == bo]
            nombre = "%s bo%d" % (tour, bo)
            for campo, pred in (("brk", "b_pred"), ("games", "g_pred")):
                r = probar(G, campo, pred, nombre)
                if r: res["grupos"]["%s_%s" % (nombre, campo)] = r
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trabajo", "minar", "velocidad_tenis.json")
    json.dump(res, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
