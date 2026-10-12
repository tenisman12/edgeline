# -*- coding: utf-8 -*-
"""
utilidades/minar_tanda10_barrido.py - tanda 10: barrido de TODAS las columnas numericas del box score contra el residuo
del modelo, en todos los deportes (hipotesis en trabajo/minar/2026-10-11_tanda10_barrido.md).

Base: p del modelo as-of de trabajo/minar/tanda7_cache.pkl. Senales: por equipo, media de los ultimos 5 y 10 partidos,
de la temporada en curso (minimo 3) y tendencia (L5 - temporada) de cada columna, solo con partidos ANTERIORES; senal del
juego = local - visita. Criba en el 70 % mas viejo (z de score, mismo signo en las dos mitades, Benjamini-Hochberg q<0.10,
hasta 8 por deporte sin redundancia > 0.8); prueba UNA vez en el 30 % final (log-loss pareado, z>=2, mitades,
calibracion). Ademas, logistica L2 con todas las senales juntas.

    python utilidades/minar_tanda10_barrido.py [--deportes NHL,NBA,...]
Escribe trabajo/minar/2026-10-11_tanda10_resultados.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, json, math, os, pickle, sys
import numpy as np
import pandas as pd

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
BASE = os.environ.get("EDGELINE_BASE", CODIGO)
CACHE = os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl")
SALIDA = os.path.join(CODIGO, "trabajo", "minar", "2026-10-11_tanda10_resultados.json")

ARCHIVO = {"NHL": ("hockey", ["NHL"]), "NBA": ("nba", ["NBA"]), "NCAAMB": ("nba", ["NCAAMB"]),
           "NFL": ("americano", ["NFL"]), "NCAAFB": ("americano", ["NCAAFB"]),
           "BEISBOL": ("beisbol", ["MLB", "KBO", "NPB", "LMP", "LVBP", "LIDOM", "ABL"]),
           "FUTBOL": ("futbol", ["Premier", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "LigaMX", "MLS"])}
NO_SENAL = {"gamePk", "season", "week", "is_home", "tipo", "ended_in", "asistencia", "primer_pitcheo", "duracion"}
VENTANAS = ("L5", "L10", "T", "tend")


def _ruta_datos(nombre):
    for b in (BASE, os.path.join(CODIGO, "trabajo", "datos")):
        r = os.path.join(b, "datos", nombre + ".csv")
        if os.path.exists(r):
            return r
    raise FileNotFoundError(nombre)


def senales_equipo(dep):
    """DataFrame por (gamePk, team) con las senales as-of de cada columna y ventana."""
    nombre, ligas = ARCHIVO[dep]
    df = pd.read_csv(_ruta_datos(nombre), encoding="utf-8-sig", low_memory=False, dtype={"gamePk": str})
    df = df[df["league"].isin(ligas)].copy()
    df["team"] = df["team"].astype(str)
    cols = []
    for c in df.columns:
        if c in NO_SENAL or c in ("league", "game_date", "team", "opp"):
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        if v.notna().mean() >= 0.2 and v.nunique() > 2:
            df[c] = v; cols.append(c)
    df = df.sort_values(["league", "team", "game_date", "gamePk"]).reset_index(drop=True)
    g = df.groupby(["league", "team"], sort=False)
    out = {"gamePk": df["gamePk"].values, "team": df["team"].values}
    for c in cols:
        prev = g[c].shift(1)                                   # solo partidos anteriores
        key = [df["league"], df["team"]]
        l5 = prev.groupby(key).rolling(5, min_periods=3).mean().reset_index(level=[0, 1], drop=True)
        l10 = prev.groupby(key).rolling(10, min_periods=5).mean().reset_index(level=[0, 1], drop=True)
        # temporada en curso: media expandida dentro de (liga, equipo, temporada), con el partido actual fuera
        prev_t = df.groupby(["league", "team", "season"], sort=False)[c].shift(1)
        tm = prev_t.groupby([df["league"], df["team"], df["season"]]).expanding(min_periods=3).mean().reset_index(level=[0, 1, 2], drop=True)
        out[c + "|L5"] = l5.sort_index().values
        out[c + "|L10"] = l10.sort_index().values
        out[c + "|T"] = tm.sort_index().values
        out[c + "|tend"] = (l5.sort_index() - tm.sort_index()).values
    S = pd.DataFrame(out)
    return S, cols


def base_espn(dep, rows):
    """p de produccion desde el 10-oct en NBA, NCAAMB y NCAAF: modelo + capa ESPN (beta de modelos/capa_espn.json).
    Devuelve {gp: p} solo para juegos con proyeccion de ESPN guardada."""
    import minar_ganador_cuota_espn as GE
    liga = {"NBA": "nba", "NCAAMB": "ncaamb", "NCAAFB": "ncaafb"}[dep]
    beta = ((json.load(open(os.path.join(CODIGO, "modelos", "capa_espn.json"), encoding="utf-8")).get("ligas") or {}).get(liga) or {}).get("beta")
    PE = {}
    for x in GE.leer(("equipos", "espn_predictor.csv")):
        if x.get("estado") != "ok" or x.get("liga") != liga:
            continue
        try:
            ph = float(x["p_local"]) if x.get("p_local") not in (None, "") else 100 - float(x["p_visita"])
        except (TypeError, ValueError):
            continue
        PE[x["game_id"]] = min(max(ph / 100.0, 0.005), 0.995)
    loc = GE.mapa_ids(liga, rows)
    out = {}
    for r in rows:
        gid = loc.get((str(r["fecha"])[:10], r["home"], r.get("away"))) or loc.get((str(r["fecha"])[:10], r["home"], None))
        q = PE.get(gid) if gid else None
        if q is None or beta is None:
            continue
        p = min(max(float(r["p"]), 1e-4), 1 - 1e-4)
        z = math.log(p / (1 - p)); zq = math.log(q / (1 - q))
        out[str(r["gp"])] = 1 / (1 + math.exp(-(z + beta * (zq - z))))
    return out


def filas_juego(dep, U, base="modelo"):
    rows = U[dep][0]
    PB = base_espn(dep, rows) if base == "espn" else None
    S, cols = senales_equipo(dep)
    S = S.drop_duplicates(["gamePk", "team"]).set_index(["gamePk", "team"])
    nombres = [c for c in S.columns]
    X, P, Y, F, PM, LG = [], [], [], [], [], []
    for r in rows:
        h = r["home"][1] if isinstance(r["home"], tuple) else r["home"]
        a = r["away"][1] if isinstance(r["away"], tuple) else r["away"]
        gp = str(r["gp"])
        try:
            xh = S.loc[(gp, str(h))].values; xa = S.loc[(gp, str(a))].values
        except KeyError:
            continue
        if r.get("p") is None or r.get("y") is None:
            continue
        if PB is not None and gp not in PB:
            continue
        pb = PB[gp] if PB is not None else float(r["p"])
        X.append(xh - xa); P.append(min(max(pb, 1e-4), 1 - 1e-4)); Y.append(int(r["y"]))
        F.append(str(r["fecha"])[:10]); PM.append(r.get("pm")); LG.append(r.get("liga") or dep)
    o = np.argsort(np.array(F), kind="stable")
    X = np.array(X, dtype=float)[o]; P = np.array(P)[o]; Y = np.array(Y)[o]
    F = np.array(F)[o]; PM = np.array([np.nan if v is None else float(v) for v in PM])[o]; LG = np.array(LG)[o]
    return X, P, Y, F, PM, LG, nombres


def lg(p):
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def ajustar_b(x, off, y, it=25):
    b = 0.0
    for _ in range(it):
        p = sig(off + b * x)
        I = np.sum(x * x * p * (1 - p))
        if I <= 0:
            break
        d = np.sum(x * (y - p)) / I
        b += d
        if abs(d) < 1e-8:
            break
    return b


def ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def prueba(y, p0, p1):
    d = ll(y, p0) - ll(y, p1); n = len(d); h = n // 2
    sd = d.std(ddof=1)
    br0 = np.mean((y - p0) ** 2); br1 = np.mean((y - p1) ** 2)
    z = float(d.mean() / sd * math.sqrt(n)) if sd > 0 else 0.0
    cal = abs(float(p1.mean() - y.mean()))
    return {"n": n, "z": round(z, 2), "mitades": [round(float(d[:h].sum()), 2), round(float(d[h:].sum()), 2)],
            "logloss_mejora_milesimas": round(1000 * float(d.mean()), 3), "brier_mejora_pct": round(100 * (br0 - br1) / br0, 2),
            "calibracion": round(cal, 3),
            "veredicto": "pasa" if (n >= 300 and z >= 2 and min(float(d[:h].sum()), float(d[h:].sum())) > 0 and cal <= 0.04) else
            ("muestra insuficiente" if n < 300 else "no pasa")}


def bh(pvals, q=0.10):
    m = len(pvals); o = np.argsort(pvals); ok = np.zeros(m, bool); lim = 0
    for i, j in enumerate(o):
        if pvals[j] <= q * (i + 1) / m:
            lim = i + 1
    ok[o[:lim]] = True
    return ok


def ridge_offset(X, off, y, lam, it=30):
    w = np.zeros(X.shape[1])
    for _ in range(it):
        p = sig(off + X @ w)
        g = X.T @ (y - p) - lam * w
        H = (X * (p * (1 - p))[:, None]).T @ X + lam * np.eye(X.shape[1])
        d = np.linalg.solve(H, g); w += d
        if np.max(np.abs(d)) < 1e-7:
            break
    return w


def norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def correr(dep, U, base="modelo"):
    X, P, Y, F, PM, LG, nombres = filas_juego(dep, U, base)
    n = len(Y); c = int(n * 0.7)
    mu = np.nanmean(X[:c], axis=0); sd = np.nanstd(X[:c], axis=0); sd[sd == 0] = 1
    Z = np.nan_to_num((X - mu) / sd)
    Z = np.clip(Z, -5, 5)
    off = lg(P)
    E, T = slice(0, c), slice(c, n)
    h = c // 2
    print("\n%s: %d juegos (%s a %s), %d senales; explorar %d, probar %d" % (dep, n, F[0], F[-1], len(nombres), c, n - c), flush=True)
    # ---- criba en explorar
    res = []
    for j, nm in enumerate(nombres):
        x = Z[E, j]; p = P[E]; yy = Y[E]
        if np.count_nonzero(x) < 300:
            continue
        U_ = np.sum(x * (yy - p)); I = np.sum(x * x * p * (1 - p))
        if I <= 0:
            continue
        z = U_ / math.sqrt(I)
        u1 = np.sum(x[:h] * (yy[:h] - p[:h])); u2 = np.sum(x[h:] * (yy[h:] - p[h:]))
        res.append({"senal": nm, "j": j, "z_explorar": round(float(z), 2), "estable": bool(np.sign(u1) == np.sign(u2) == np.sign(U_)),
                    "pval": 2 * (1 - norm_cdf(abs(z)))})
    pv = np.array([r["pval"] for r in res]); okbh = bh(pv) if len(pv) else []
    for r, o in zip(res, okbh):
        r["bh"] = bool(o)
    cand = sorted([r for r in res if r["bh"] and r["estable"]], key=lambda r: -abs(r["z_explorar"]))
    elegidas = []
    for r in cand:
        if len(elegidas) >= 8:
            break
        if any(abs(np.corrcoef(Z[E, r["j"]], Z[E, e["j"]])[0, 1]) > 0.8 for e in elegidas):
            continue
        elegidas.append(r)
    print("  criba: %d senales probadas en explorar, %d sobreviven BH q<0.10, %d ademas estables, %d llevadas a prueba" % (
        len(res), int(sum(okbh)) if len(pv) else 0, len(cand), len(elegidas)), flush=True)
    top = sorted(res, key=lambda r: -abs(r["z_explorar"]))[:15]
    for r in top:
        print("    explorar %-34s z %6.2f %s%s" % (r["senal"], r["z_explorar"], "estable" if r["estable"] else "inestable", " BH" if r["bh"] else ""))
    # ---- prueba (una vez)
    pruebas = []
    for r in elegidas:
        j = r["j"]
        b = ajustar_b(Z[E, j], off[E], Y[E])
        p1 = sig(off[T] + b * Z[T, j])
        t = prueba(Y[T], P[T], p1)
        t.update({"senal": r["senal"], "b": round(float(b), 4), "z_explorar": r["z_explorar"],
                  "pp_por_desv": round(100 * float(sig(b) - 0.5), 2)})
        mk = ~np.isnan(PM[T])
        if dep in ("FUTBOL", "NFL") and mk.sum() >= 300:
            pmE = np.clip(PM[E], 1e-4, 1 - 1e-4); okE = ~np.isnan(PM[E])
            bm = ajustar_b(Z[E, j][okE], lg(pmE[okE]), Y[E][okE])
            pmT = np.clip(PM[T][mk], 1e-4, 1 - 1e-4)
            t["contra_mercado"] = prueba(Y[T][mk], pmT, sig(lg(pmT) + bm * Z[T, j][mk]))
        if dep == "BEISBOL":
            t["por_liga"] = {}
            for L in sorted(set(LG[T])):
                m = LG[T] == L
                if m.sum() >= 150:
                    t["por_liga"][L] = prueba(Y[T][m], P[T][m], p1[m])
        pruebas.append(t)
        print("  PRUEBA %-34s n %5d  z %5.2f  mitades %s  logloss %+.3f mil  brier %+.2f%%  cal %.3f  b %+.3f  -> %s%s" % (
            t["senal"], t["n"], t["z"], t["mitades"], t["logloss_mejora_milesimas"], t["brier_mejora_pct"], t["calibracion"],
            b, t["veredicto"], ("  | mercado z %.2f" % t["contra_mercado"]["z"]) if "contra_mercado" in t else ""), flush=True)
    # ---- todas juntas (L2), lambda en un corte interno del 70 %
    c2 = int(c * 0.7)
    mejor = None
    for lam in (3e4, 1e4, 3e3, 1e3, 3e2, 1e2):
        w = ridge_offset(Z[:c2], off[:c2], Y[:c2], lam)
        v = float(np.mean(ll(Y[c2:c], P[c2:c]) - ll(Y[c2:c], sig(off[c2:c] + Z[c2:c] @ w))))
        if mejor is None or v > mejor[1]:
            mejor = (lam, v)
    w = ridge_offset(Z[E], off[E], Y[E], mejor[0])
    pj = sig(off[T] + Z[T] @ w)
    junta = prueba(Y[T], P[T], pj); junta["lambda"] = mejor[0]; junta["validacion_interna_mil"] = round(1000 * mejor[1], 3)
    pesos = sorted(zip(nombres, w), key=lambda t: -abs(t[1]))[:12]
    junta["pesos_mayores"] = [[a, round(float(b), 4)] for a, b in pesos]
    print("  TODAS JUNTAS (L2, lambda %g): n %d  z %.2f  mitades %s  logloss %+.3f mil  cal %.3f -> %s" % (
        mejor[0], junta["n"], junta["z"], junta["mitades"], junta["logloss_mejora_milesimas"], junta["calibracion"], junta["veredicto"]), flush=True)
    return {"n": n, "desde": F[0], "hasta": F[-1], "senales": len(nombres), "corte_prueba": F[c],
            "criba": {"probadas": len(res), "bh": int(sum(okbh)) if len(pv) else 0, "estables_bh": len(cand),
                      "top15": [{k: v for k, v in r.items() if k not in ("j", "pval")} for r in top]},
            "k_prueba": len(elegidas), "pruebas": pruebas, "todas_juntas": junta}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deportes", default="NHL,NBA,NCAAMB,NFL,NCAAFB,BEISBOL,FUTBOL")
    ap.add_argument("--base", default="modelo", help="modelo | espn (produccion con capa ESPN: NBA, NCAAMB, NCAAFB)")
    a = ap.parse_args()
    U = pickle.load(open(CACHE, "rb"))
    res = {}
    if os.path.exists(SALIDA):
        try:
            res = json.load(open(SALIDA, encoding="utf-8"))
        except Exception:
            res = {}
    for dep in a.deportes.split(","):
        res[dep + ("" if a.base == "modelo" else "|base_" + a.base)] = correr(dep, U, a.base)
        json.dump(res, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    k = sum(r["k_prueba"] for r in res.values()) + len(res)
    print("\nk total llevado a prueba: %d (falsos 'pasa' esperados ~%.1f)" % (k, k * 0.023))
    print("escrito", SALIDA)


if __name__ == "__main__":
    main()
