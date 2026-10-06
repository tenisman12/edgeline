# -*- coding: utf-8 -*-
"""
utilidades/medir_clima_mlb.py - mide el efecto del clima (temperatura, viento hacia/desde el jardin, lluvia, techo) y del
umpire del plato en las carreras totales de MLB, fuera de muestra.

Datos: datos/beisbol.csv (MLB Stats API): clima "61 degrees, Clear", viento "13 mph, Out To CF" (la direccion ya viene
relativa al campo, no hace falta la orientacion del estadio), estadio y umpire_home.

Base: promedio de carreras del estadio (encogido hacia la liga) con lo anterior. Clima: regresion lineal sobre la base,
ajustada solo con temporadas anteriores y evaluada en la siguiente (2023, 2024, 2025, 2026). Umpire: residuo medio de
sus juegos anteriores, encogido. Mejora de MAE y RMSE contra la base, z y por mitades (protocolo: z >= 2 y las dos
mitades). Escribe modelos/clima_mlb.json con coeficientes (carreras por grado, por mph) y veredicto.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\medir_clima_mlb.py
"""
import csv, json, math, os, re, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io

K_PARQUE, K_UMP = 150, 60       # encogimiento: juegos equivalentes al promedio de la liga


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def clima(txt, viento):
    """(techado, temp F, mph hacia afuera, mph hacia adentro, mph cruzado, lluvia)"""
    t = (txt or ""); v = (viento or "")
    techo = any(k in t for k in ("Roof Closed", "Dome"))
    m = re.search(r"(-?\d+)\s*degrees", t); temp = float(m.group(1)) if m else None
    m = re.search(r"(\d+)\s*mph", v); mph = float(m.group(1)) if m else 0.0
    d = v.split(", ", 1)[1] if ", " in v else ""
    fuera = mph if d.startswith("Out") else 0.0
    dentro = mph if d.startswith("In") else 0.0
    cruz = mph if d in ("L To R", "R To L") else 0.0
    lluvia = 1.0 if any(k in t for k in ("Rain", "Drizzle")) else 0.0
    if techo:
        fuera = dentro = cruz = 0.0
    return techo, temp, fuera, dentro, cruz, lluvia


def juegos():
    out = {}
    with open(os.path.join(io.BASE, "datos", "beisbol.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("league") or "").upper() != "MLB" or str(r.get("is_home")).replace(".0", "") != "1":
                continue
            a, b = _f(r.get("runs")), _f(r.get("runs_opp"))
            if a is None or b is None:
                continue
            tipo = (r.get("tipo") or r.get("game_type") or "R")
            out[str(r.get("gamePk"))] = {"f": (r.get("game_date") or "")[:10], "tot": a + b, "park": r.get("estadio") or r.get("team"),
                                         "ump": r.get("umpire_home") or "", "c": clima(r.get("clima"), r.get("viento"))}
    return sorted(out.values(), key=lambda x: x["f"])


def _x(g):
    techo, temp, fu, de, cr, ll = g["c"]
    t = 0.0 if (techo or temp is None) else (temp - 72.0)
    return [t, fu, de, cr, ll, 1.0 if techo else 0.0]


def ols(X, y, l2=1e-3):
    k = len(X[0]); A = [[0.0] * (k + 1) for _ in range(k)]
    for xi, yi in zip(X, y):
        for i in range(k):
            A[i][k] += xi[i] * yi
            for j in range(k):
                A[i][j] += xi[i] * xi[j]
    for i in range(k): A[i][i] += l2
    for i in range(k):
        p = A[i][i] or 1e-9
        for j in range(i, k + 1): A[i][j] /= p
        for r in range(k):
            if r != i:
                fct = A[r][i]
                for j in range(i, k + 1): A[r][j] -= fct * A[i][j]
    return [A[i][k] for i in range(k)]


def main():
    G = juegos()
    print("Juegos MLB con clima: %d (%s a %s)" % (len(G), G[0]["f"], G[-1]["f"]))
    # base as-of: estadio encogido hacia la liga, con todo lo anterior
    lg_s = lg_n = 0.0; park = {}; ump = {}
    for g in G:
        lgm = lg_s / lg_n if lg_n else 8.8
        s, n = park.get(g["park"], (0.0, 0))
        g["base"] = (s + K_PARQUE * lgm) / (n + K_PARQUE)
        g["lg"] = lgm
        lg_s += g["tot"]; lg_n += 1; park[g["park"]] = (s + g["tot"], n + 1)
    temporadas = sorted({g["f"][:4] for g in G})
    coefs = {}; ev = []
    for t in temporadas[1:]:
        tr = [g for g in G if g["f"][:4] < t]; te = [g for g in G if g["f"][:4] == t]
        b = ols([_x(g) for g in tr], [g["tot"] - g["base"] for g in tr])
        coefs[t] = [round(v, 4) for v in b]
        for g in te:
            g["clima_aj"] = sum(bi * xi for bi, xi in zip(b, _x(g))); ev.append(g)
    # umpire as-of (residuo contra base + clima)
    for g in G:
        s, n = ump.get(g["ump"], (0.0, 0))
        g["ump_aj"] = s / (n + K_UMP) if g["ump"] else 0.0
        if g["ump"]:
            ump[g["ump"]] = (s + (g["tot"] - g["base"] - g.get("clima_aj", 0.0)), n + 1)
    def prueba(nombre, pred):
        d_abs = [abs(g["tot"] - g["base"]) - abs(g["tot"] - pred(g)) for g in ev]
        d_sq = [(g["tot"] - g["base"]) ** 2 - (g["tot"] - pred(g)) ** 2 for g in ev]
        n = len(d_abs); h = n // 2
        def z(d):
            m = sum(d) / n; sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) or 1e-9; return m, m / (sd / math.sqrt(n))
        ma, za = z(d_abs); ms, zs = z(d_sq)
        mit = [sum(d_abs[:h]) / h, sum(d_abs[h:]) / (n - h)]
        ok = n >= 300 and za >= 2.0 and min(mit) > 0
        r = {"n": n, "mejora_mae": round(ma, 4), "z_mae": round(za, 2), "mejora_mse": round(ms, 4), "z_mse": round(zs, 2),
             "mitades_mae": [round(x, 4) for x in mit], "veredicto": "APLICAR" if ok else "sin mejora demostrada"}
        print("  %-16s n=%d  MAE %+.4f carreras (z %.2f)  MSE %+.4f (z %.2f)  mitades %s -> %s" % (
            nombre, n, ma, za, ms, zs, r["mitades_mae"], r["veredicto"]))
        return r
    print("\nMejora contra la base (estadio encogido), evaluando cada temporada con lo aprendido antes:")
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"),
           "variables": ["temp_F_menos_72", "mph_hacia_afuera", "mph_hacia_adentro", "mph_cruzado", "lluvia", "techado"],
           "coeficientes_por_temporada": coefs,
           "clima": prueba("clima", lambda g: g["base"] + g["clima_aj"]),
           "umpire": prueba("umpire", lambda g: g["base"] + g["ump_aj"]),
           "clima+umpire": prueba("clima+umpire", lambda g: g["base"] + g["clima_aj"] + g["ump_aj"])}
    ult = coefs[temporadas[-1]]
    print("\nCoeficientes (ultima temporada): %+.3f carreras por grado F, %+.3f por mph hacia afuera, %+.3f por mph hacia adentro, "
          "%+.3f por mph cruzado, %+.2f con lluvia, %+.2f techado" % tuple(ult))
    res["coef_vigentes"] = dict(zip(res["variables"], ult))
    res["umpires"] = {u: round(s / (n + K_UMP), 3) for u, (s, n) in ump.items() if n >= 30}
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "clima_mlb.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
