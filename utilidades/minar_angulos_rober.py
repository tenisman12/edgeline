# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_rober.py - angulos de abridor propuestos por Roberto (28-oct-2026), medidos as-of en LMP 2014-2025.

Datos: datos/abridores/lmp_lanzadores.csv (lineas por lanzador) + datos/beisbol.csv (resultados). Stats del abridor
acumuladas ANTES de cada juego, por temporada; FIP con constante por temporada; ERA/FIP exigen 10+ IP.
No hay cuotas historicas de LMP: se mide el acierto real contra una base (ELO K 6, local +24, regresion 1/3 entre
temporadas; y ELO + FIP regresado del abridor). Se reportan exceso en pp, z, mitades por temporada y temporadas a favor.
x con el signo de nucleo/angulos.calcular: +1 apunta al local, -1 a la visita.

Escribe trabajo/minar/2026-10-28_rober_abridores_resultados.json (formato de las tandas 7/8/11, base "modelo" = ELO+FIP)
y trabajo/minar/2026-10-28_rober_abridores.md.  Correr:  python utilidades/minar_angulos_rober.py
Solo stdlib.
"""
import csv, os, math, collections, json, datetime as dt

BASE = os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAU = 0.0924  # mismo tau de la tanda 4 para encoger

ANG = {
    "R4": ("contra el abridor suertudo (su FIP 1.5+ peor que su ERA)", 1),
    "R5": ("abridor con peor ERA pero mejor FIP que el rival", 1),
    "R6": ("contra el abridor caliente (su equipo +3 o mas en sus aperturas)", 1),
    "R7": ("underdog con mejor abridor por FIP", 1),
    "R8": ("favorito con peor abridor por FIP", -1),
    "R9": ("primera apertura de la temporada", -1),
    "R10": ("abridor con 8 a 14 dias de descanso", -1),
    "R11": ("a favor del abridor caliente (su equipo +3 o mas en sus aperturas)", -1),
}


def ipf(x):
    try:
        x = float(x)
    except Exception:
        return 0.0
    w = int(x)
    return w + round((x - w) * 10) / 3.0


def f(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def es_ab(r):
    return (r.get("abridor") or "") in ("1", "1.0", "True")


def main():
    res = {}
    with open(os.path.join(BASE, "datos", "beisbol.csv"), encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["league"].upper() == "LMP" and r["is_home"] in ("1", "1.0", "True"):
                try:
                    res[r["gamePk"]] = (r["game_date"][:10], r["season"], r["team"], r["opp"], float(r["runs"]), float(r["runs_opp"]))
                except Exception:
                    pass
    app = collections.defaultdict(list)
    with open(os.path.join(BASE, "datos", "abridores", "lmp_lanzadores.csv"), encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            app[r["game_id"]].append(r)
    tot = collections.defaultdict(lambda: [0.0] * 5)
    for rows in app.values():
        for r in rows:
            t = tot[r["season"]]
            t[0] += ipf(r["ip"]); t[1] += f(r["er"]); t[2] += f(r["hr"]); t[3] += f(r["bb"]) + f(r["hbp"]); t[4] += f(r["k"])
    CONST = {s: 9 * t[1] / t[0] - (13 * t[2] + 3 * t[3] - 2 * t[4]) / t[0] for s, t in tot.items() if t[0] > 0}
    ERA_L = {s: 9 * t[1] / t[0] for s, t in tot.items() if t[0] > 0}

    games = sorted((v[0], gid) for gid, v in res.items() if gid in app)
    elo = collections.defaultdict(lambda: 1500.0); ult_temp = {}; pst = {}; plast = {}
    filas = []
    D = lambda s: dt.date(*map(int, s[:10].split("-")))
    for fecha, gid in games:
        _, season, home, away, rh, ra = res[gid]
        for t in (home, away):
            if ult_temp.get(t) != season:
                elo[t] = 1500 + (elo[t] - 1500) * 0.67; ult_temp[t] = season
        st = {r["team"]: r for r in app[gid] if es_ab(r)}
        if home in st and away in st and rh != ra:
            row = {"season": season, "elo_d": elo[home] - elo[away] + 24, "win_home": 1 if rh > ra else 0}
            for lado, t in (("h", home), ("a", away)):
                p = st[t]["jugador"]; s = pst.get((season, p)); prev = plast.get(p)
                row[lado + "_desc"] = (D(fecha) - D(prev)).days if prev else None
                if s and s["ip"] >= 1:
                    era = 9 * s["er"] / s["ip"]; fip = (13 * s["hr"] + 3 * s["bb"] - 2 * s["k"]) / s["ip"] + CONST[season]
                    w = s["ip"] / (s["ip"] + 70)
                    row.update({lado + "_era": era, lado + "_fip": fip, lado + "_fipr": w * fip + (1 - w) * ERA_L[season],
                                lado + "_gs": s["gs"], lado + "_ip": s["ip"], lado + "_wl": s["w"] - s["l"]})
                else:
                    row.update({lado + "_era": None, lado + "_fip": None, lado + "_fipr": ERA_L[season], lado + "_gs": s["gs"] if s else 0,
                                lado + "_ip": 0, lado + "_wl": 0})
            filas.append(row)
        if rh != ra:
            e = 1 / (1 + 10 ** (-(elo[home] - elo[away] + 24) / 400))
            elo[home] += 6 * ((1 if rh > ra else 0) - e); elo[away] -= 6 * ((1 if rh > ra else 0) - e)
        for r in app[gid]:
            p = r["jugador"]; s = pst.setdefault((season, p), {"ip": 0, "er": 0, "hr": 0, "bb": 0, "k": 0, "gs": 0, "w": 0, "l": 0})
            s["ip"] += ipf(r["ip"]); s["er"] += f(r["er"]); s["hr"] += f(r["hr"]); s["bb"] += f(r["bb"]) + f(r["hbp"]); s["k"] += f(r["k"])
            plast[p] = fecha
            if es_ab(r) and rh != ra:
                s["gs"] += 1
                s["w" if ((rh > ra) == (r["team"] == home)) else "l"] += 1

    def fit(X, y, it=300, lr=0.5):
        b = [0.0] * len(X[0])
        for _ in range(it):
            g = [0.0] * len(b)
            for xi, yi in zip(X, y):
                pr = 1 / (1 + math.exp(-sum(a * c for a, c in zip(b, xi))))
                for j in range(len(b)):
                    g[j] += (yi - pr) * xi[j]
            b = [bj + lr * gj / len(X) for bj, gj in zip(b, g)]
        return b
    y = [r["win_home"] for r in filas]
    X1 = [[1, r["elo_d"] / 100] for r in filas]
    X2 = [[1, r["elo_d"] / 100, r["a_fipr"] - r["h_fipr"]] for r in filas]
    b1, b2 = fit(X1, y), fit(X2, y)
    sg = lambda b, x: 1 / (1 + math.exp(-sum(a * c for a, c in zip(b, x))))
    for r, x1, x2 in zip(filas, X1, X2):
        r["p1"], r["p2"] = sg(b1, x1), sg(b2, x2)

    ok = lambda r, l: r[l + "_era"] is not None and r[l + "_ip"] >= 10
    COND = {
        "R4": lambda r, l, o, p: ok(r, o) and r[o + "_fip"] - r[o + "_era"] >= 1.5,
        "R5": lambda r, l, o, p: ok(r, l) and ok(r, o) and r[l + "_era"] > r[o + "_era"] and r[l + "_fip"] < r[o + "_fip"],
        "R6": lambda r, l, o, p: r[o + "_wl"] >= 3,
        "R7": lambda r, l, o, p: p <= 0.47 and ok(r, l) and ok(r, o) and r[l + "_fip"] < r[o + "_fip"],
        "R8": lambda r, l, o, p: p >= 0.53 and ok(r, l) and ok(r, o) and r[l + "_fip"] > r[o + "_fip"],
        "R9": lambda r, l, o, p: r[l + "_gs"] == 0,
        "R10": lambda r, l, o, p: r[l + "_desc"] is not None and 8 <= r[l + "_desc"] <= 14,
        "R11": lambda r, l, o, p: r[l + "_wl"] >= 3,
    }
    ganador, estim, md = [], [], []
    lg_ = lambda q: math.log(q / (1 - q))
    for cod, (nom, signo) in ANG.items():
        out = {}
        for base in ("p1", "p2"):
            ex = []
            for r in filas:
                for l, o, pk in (("h", "a", 1), ("a", "h", 0)):
                    p1 = r["p1"] if pk else 1 - r["p1"]
                    if COND[cod](r, l, o, p1):
                        pb = r[base] if pk else 1 - r[base]
                        g = r["win_home"] if pk else 1 - r["win_home"]
                        ex.append((r["season"], g, pb))
            n = len(ex); m = sum(g - p for _, g, p in ex) / n
            var = sum(p * (1 - p) for _, _, p in ex) / n; se = math.sqrt(var / n); z = m / se
            ss = sorted(set(s for s, _, _ in ex)); half = ss[len(ss) // 2]
            h1 = [g - p for s, g, p in ex if s < half]; h2 = [g - p for s, g, p in ex if s >= half]
            por = collections.defaultdict(float)
            for s, g, p in ex:
                por[s] += g - p
            out[base] = dict(n=n, acierto=round(100 * sum(g for _, g, _ in ex) / n, 1), esperado=round(100 * sum(p for _, _, p in ex) / n, 1),
                             exceso=round(100 * m, 2), se=se, z=round(z, 2), mitades=[round(100 * sum(h1) / max(len(h1), 1), 2), round(100 * sum(h2) / max(len(h2), 1), 2)],
                             temporadas=f"{sum(1 for v in por.values() if v > 0)}/{len(por)}")
        b = out["p2"]
        pasa = b["n"] >= 300 and abs(b["z"]) >= 2 and b["mitades"][0] * b["mitades"][1] > 0 and (b["z"] > 0) == (signo > 0)
        ganador.append({"liga": "LMP", "codigo": cod, "angulo": nom, "base": "modelo", "veredicto": "pasa" if pasa else "no pasa",
                        "n_activo_prueba": b["n"], "z": b["z"], "residuo_firmado_pp": b["exceso"], "mitades": b["mitades"],
                        "beta": 1.0 if signo > 0 else -1.0, "direccion_ok": True, "desde_prueba": "2014-10-10",
                        "temporadas_a_favor": b["temporadas"], "base_elo": out["p1"]})
        beta = lg_(0.5 + b["exceso"] / 100); ee = 4 * b["se"]
        estim.append({"liga": "LMP", "codigo": cod, "angulo": nom, "base": "modelo", "n": len(filas), "n_activos": b["n"], "x_tipico": 1,
                      "beta": round(beta, 5), "ee": round(ee, 5), "pp_50": b["exceso"],
                      "pp_50_encogido": round(100 * (1 / (1 + math.exp(-beta * TAU ** 2 / (TAU ** 2 + ee ** 2))) - 0.5), 2)})
        md.append(f"| {cod} | {nom} | {b['n']} | {out['p1']['exceso']:+.2f} ({out['p1']['z']}) | {b['exceso']:+.2f} ({b['z']}) | "
                  f"{b['mitades'][0]:+.2f} / {b['mitades'][1]:+.2f} | {b['temporadas']} | {'pasa' if pasa else 'no pasa'} |")
    salida = {"generado": dt.date.today().isoformat(), "fuente": "Roberto (28-oct-2026); medido en LMP 2014-2025 sin cuotas",
              "juegos": len(filas), "coef_base": {"elo": [round(v, 4) for v in b1], "elo_fip": [round(v, 4) for v in b2]},
              "ganador": ganador, "estimacion": estim}
    d = os.path.join(CODIGO, "trabajo", "minar")
    with open(os.path.join(d, "2026-10-28_rober_abridores_resultados.json"), "w", encoding="utf-8") as fh:
        json.dump(salida, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(d, "2026-10-28_rober_abridores.md"), "w", encoding="utf-8") as fh:
        fh.write("# Angulos de abridor de Roberto (28-oct-2026)\n\n"
                 f"LMP 2014-2025, {len(filas)} juegos con los dos abridores. Base ELO y base ELO + FIP regresado "
                 f"(coef FIP {b2[2]:.3f} logit por punto). Exceso = acierto real - esperado (pp); z entre parentesis. Regla: n >= 300, "
                 "|z| >= 2, mitades del mismo signo, en la direccion de la hipotesis. Sin cuotas: no mide ROI.\n\n"
                 "| Cod | Angulo | n | Exceso ELO | Exceso ELO+FIP | Mitades | Temporadas + | Veredicto |\n|---|---|---|---|---|---|---|---|\n"
                 + "\n".join(md) + "\n\nTodos quedan como contexto en nucleo/angulos (R4-R11) y se registran en vivo en "
                 "salida/historial_angulos.csv para medirlos con cuotas reales. R6/R11 usan el record del equipo en las aperturas del "
                 "abridor como sustituto del pitcher profit en unidades.\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
