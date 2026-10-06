# -*- coding: utf-8 -*-
"""
utilidades/medir_clima_nfl.py - baja el clima historico de cada partido de NFL al aire libre (Open-Meteo archive, gratis)
y mide su efecto en los puntos totales, fuera de muestra.

Paso 1 (baja): una consulta por estadio para todo el rango; guarda datos/equipos/nfl_clima.csv (fecha, estadio,
temperatura media, viento maximo, rafaga maxima, lluvia del dia). Incremental: solo baja lo que falta.
Paso 2 (mide): base = promedio de puntos de la liga con lo anterior; regresion de clima ajustada con temporadas
anteriores y evaluada en la siguiente. Protocolo: z >= 2 y mejora en las dos mitades. Escribe modelos/clima_nfl.json.

Domos y techos retractiles se marcan como techados (sin clima). Sede neutral (Londres, Alemania, Mexico) se omite.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\medir_clima_nfl.py            (baja lo que falte y mide)
    python utilidades\\medir_clima_nfl.py --solo-medir
"""
import argparse, csv, json, math, os, sys, time, urllib.request, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io

ARCHIVO = "https://archive-api.open-meteo.com/v1/archive?latitude=%.3f&longitude=%.3f&start_date=%s&end_date=%s&daily=temperature_2m_mean,wind_speed_10m_max,wind_gusts_10m_max,precipitation_sum&timezone=auto&wind_speed_unit=mph&temperature_unit=fahrenheit"
# equipo local -> (lat, lon, techado)
ESTADIOS = {"ARI": (33.528, -112.263, True), "ATL": (33.755, -84.401, True), "BAL": (39.278, -76.623, False),
            "BUF": (42.774, -78.787, False), "CAR": (35.226, -80.853, False), "CHI": (41.862, -87.617, False),
            "CIN": (39.095, -84.516, False), "CLE": (41.506, -81.700, False), "DAL": (32.748, -97.093, True),
            "DEN": (39.744, -105.020, False), "DET": (42.340, -83.046, True), "GB": (44.501, -88.062, False),
            "HOU": (29.685, -95.411, True), "IND": (39.760, -86.164, True), "JAX": (30.324, -81.637, False),
            "KC": (39.049, -94.484, False), "LV": (36.091, -115.184, True), "LA": (33.953, -118.339, True),
            "LAC": (33.953, -118.339, True), "MIA": (25.958, -80.239, False), "MIN": (44.974, -93.258, True),
            "NE": (42.091, -71.264, False), "NO": (29.951, -90.081, True), "NYG": (40.814, -74.074, False),
            "NYJ": (40.814, -74.074, False), "PHI": (39.901, -75.168, False), "PIT": (40.447, -80.016, False),
            "SF": (37.403, -121.970, False), "SEA": (47.595, -122.332, False), "TB": (27.976, -82.503, False),
            "TEN": (36.166, -86.771, False), "WAS": (38.908, -76.864, False)}
SALIDA = os.path.join(io.BASE, "datos", "equipos", "nfl_clima.csv")


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def juegos():
    out = {}
    with open(os.path.join(io.BASE, "datos", "americano.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("league") or "").upper() != "NFL" or str(r.get("is_home")).replace(".0", "") != "1":
                continue
            a, b = _f(r.get("points")), _f(r.get("points_opp"))
            if a is None or b is None:
                continue
            out[str(r.get("gamePk"))] = {"f": (r.get("game_date") or "")[:10], "home": r.get("team"), "tot": a + b,
                                         "neutral": str(r.get("neutral") or r.get("neutral_site") or "").lower() in ("1", "true")}
    return sorted(out.values(), key=lambda x: x["f"])


def bajar(G):
    ya = {}
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                ya[(r["fecha"], r["estadio"])] = r
    falta = {}
    for g in G:
        e = ESTADIOS.get(g["home"])
        if e and not e[2] and (g["f"], g["home"]) not in ya:
            falta.setdefault(g["home"], []).append(g["f"])
    for eq, fs in sorted(falta.items()):
        la, lo, _ = ESTADIOS[eq]
        try:
            req = urllib.request.Request(ARCHIVO % (la, lo, min(fs), max(fs)), headers={"User-Agent": "Edgeline"})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("  %s: %s" % (eq, str(e)[:80])); continue
        dd = d.get("daily") or {}
        pos = {t: i for i, t in enumerate(dd.get("time") or [])}
        for f in fs:
            i = pos.get(f)
            if i is None:
                continue
            ya[(f, eq)] = {"fecha": f, "estadio": eq, "temp_f": dd["temperature_2m_mean"][i], "viento_mph": dd["wind_speed_10m_max"][i],
                           "rafaga_mph": dd["wind_gusts_10m_max"][i], "lluvia_mm": dd["precipitation_sum"][i]}
        print("  %s: %d partidos" % (eq, len(fs))); time.sleep(0.5)
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["fecha", "estadio", "temp_f", "viento_mph", "rafaga_mph", "lluvia_mm"])
        w.writeheader(); w.writerows(sorted(ya.values(), key=lambda r: (r["fecha"], r["estadio"])))
    return ya


def ols(X, y, l2=1e-3):
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


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--solo-medir", action="store_true"); a = ap.parse_args()
    G = juegos()
    clima = bajar(G) if not a.solo_medir else {}
    if a.solo_medir and os.path.exists(SALIDA):
        with open(SALIDA, encoding="utf-8-sig", newline="") as f:
            clima = {(r["fecha"], r["estadio"]): r for r in csv.DictReader(f)}
    s = n = 0.0
    for g in G:
        g["base"] = s / n if n else 44.0; s += g["tot"]; n += 1
        e = ESTADIOS.get(g["home"]); c = clima.get((g["f"], g["home"]))
        if e and e[2]:
            g["x"] = [0.0, 0.0, 0.0, 1.0]
        elif c and not g["neutral"]:
            g["x"] = [(_f(c["temp_f"]) or 60) - 60.0, max((_f(c["viento_mph"]) or 0) - 10.0, 0.0), _f(c["lluvia_mm"]) or 0.0, 0.0]
        else:
            g["x"] = None
    G = [g for g in G if g["x"]]
    temps = sorted({g["f"][:4] for g in G}); ev = []; coefs = {}
    for t in temps[1:]:
        tr = [g for g in G if g["f"][:4] < t]; te = [g for g in G if g["f"][:4] == t]
        if len(tr) < 200:
            continue
        b = ols([g["x"] for g in tr], [g["tot"] - g["base"] for g in tr]); coefs[t] = [round(v, 3) for v in b]
        for g in te:
            g["aj"] = sum(bi * xi for bi, xi in zip(b, g["x"])); ev.append(g)
    if not ev:
        print("Sin datos suficientes."); return 1
    d = [(g["tot"] - g["base"]) ** 2 - (g["tot"] - g["base"] - g["aj"]) ** 2 for g in ev]
    da = [abs(g["tot"] - g["base"]) - abs(g["tot"] - g["base"] - g["aj"]) for g in ev]
    N = len(d); h = N // 2
    def z(x):
        m = sum(x) / N; sd = math.sqrt(sum((v - m) ** 2 for v in x) / (N - 1)) or 1e-9; return m, m / (sd / math.sqrt(N))
    mm, zm = z(d); ma, za = z(da)
    mit = [sum(da[:h]) / h, sum(da[h:]) / (N - h)]
    ok = N >= 300 and za >= 2.0 and min(mit) > 0
    ult = coefs[max(coefs)]
    print("NFL clima: n=%d  MAE %+.3f puntos (z %.2f)  MSE %+.2f (z %.2f)  mitades %s -> %s" % (
        N, ma, za, mm, zm, [round(x, 3) for x in mit], "APLICAR" if ok else "sin mejora demostrada"))
    print("Coeficientes: %+.3f puntos por grado F (vs 60), %+.3f por mph de viento arriba de 10, %+.3f por mm de lluvia, %+.2f techado" % tuple(ult))
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "clima_nfl.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": dt.datetime.now().isoformat(timespec="seconds"), "n": N, "mejora_mae": round(ma, 4), "z_mae": round(za, 2),
                   "mejora_mse": round(mm, 3), "z_mse": round(zm, 2), "mitades_mae": mit, "veredicto": "APLICAR" if ok else "sin mejora demostrada",
                   "variables": ["temp_F_menos_60", "viento_mph_arriba_10", "lluvia_mm", "techado"],
                   "coef_vigentes": dict(zip(["temp_F_menos_60", "viento_mph_arriba_10", "lluvia_mm", "techado"], ult)),
                   "coeficientes_por_temporada": coefs}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
