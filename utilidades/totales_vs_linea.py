# -*- coding: utf-8 -*-
"""
utilidades/totales_vs_linea.py - TOTALES: el modelo contra la LINEA DE CIERRE de Pinnacle, no contra la media de liga.

La pregunta que importa en totales es si el modelo le gana a la linea que pone el mercado. Con las fotos de cuotas
(salida/cuotas_sharp_*.csv: por evento, mercado totals, linea y p_sharp en cada hora) se toma la ULTIMA foto antes del
inicio (cierre) y se cruza con las predicciones del modelo ya calificadas (salida/historial_predicciones_calificado.csv:
mercado Total, lado, p_modelo, valor_modelo = total esperado, linea usada, real).

Reporta por liga:
  - n, MAE de la linea de cierre vs total real (el rival a vencer) y MAE del total esperado del modelo (si se registro).
  - Acierto del lado del modelo contra la linea de cierre (over si total esperado > cierre), con el umbral 52.4% que
    paga a -110, por tamano de brecha (|modelo - cierre| en unidades de la liga).
  - Calibracion de Pinnacle: p_sharp del over vs frecuencia real de over.
Se acumula solo: entre mas dias de fotos, mas n. Hoy (4-oct) las fotos empiezan el 1-oct: la muestra es chica y
el reporte es orientativo hasta tener ~300 partidos por liga.

    python utilidades\\totales_vs_linea.py
Escribe salida/totales_vs_linea.json. Solo stdlib.
"""
import csv, glob, io, json, math, os, sys, datetime as dt
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io as nio

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAL = os.path.join(REPO, "salida") if os.path.exists(os.path.join(REPO, "salida", "proximos.json")) else nio.ruta("salida")
LIGA_DE = {"baseball_mlb": "mlb", "baseball_npb": "npb", "baseball_kbo": "kbo", "icehockey_nhl": "nhl", "americanfootball_nfl": "nfl",
           "americanfootball_ncaaf": "ncaafb", "basketball_nba": "nba", "basketball_ncaab": "ncaamb"}
UNIDAD = {"nhl": 0.5, "mlb": 0.5, "npb": 0.5, "kbo": 0.5, "nfl": 1.0, "ncaafb": 1.0, "nba": 1.0, "ncaamb": 1.0, "atp": 1.0, "wta": 1.0}


def _liga(sport):
    if sport in LIGA_DE:
        return LIGA_DE[sport]
    if sport.startswith("tennis_atp"):
        return "atp"
    if sport.startswith("tennis_wta"):
        return "wta"
    return None


def _norm(s):
    return nio.norm(s or "")


def cierres():
    """{(liga, fecha_utc[:10], home_norm, away_norm): {linea, p_over, ts}} ultima foto antes del inicio."""
    out = {}
    for ruta in sorted(glob.glob(os.path.join(SAL, "cuotas_sharp_*.csv"))):
        with io.open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("mercado") != "totals" or r.get("lado") != "over":
                    continue
                lg = _liga(r.get("sport") or "")
                if not lg:
                    continue
                try:
                    L = float(r.get("linea")); p = float(r.get("p_sharp")); ts = r.get("ts_utc") or ""; ini = r.get("commence_time") or ""
                except (TypeError, ValueError):
                    continue
                if ts > ini:
                    continue                          # foto posterior al inicio: no es cierre
                k = (lg, ini[:10], _norm(r.get("home")), _norm(r.get("away")))
                if k not in out or ts > out[k]["ts"]:
                    out[k] = {"linea": L, "p_over": p, "ts": ts, "fuente": r.get("fuente")}
    return out


def _mismo(a, b):
    A, B = set(a.split()), set(b.split())
    return bool(A and B) and len(A & B) / min(len(A), len(B)) >= 0.5


def main():
    ruta = os.path.join(SAL, "historial_predicciones_calificado.csv")
    if not os.path.exists(ruta):
        print("No existe", ruta); return 1
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        pred = [r for r in csv.DictReader(f) if (r.get("mercado") or "").split()[:1] in (["Total"], ["Games"]) and r.get("estado") in ("calificado", "push")]
    cz = cierres()
    por_liga = defaultdict(list)
    sin = 0
    for r in pred:
        lg = r["liga"]; f = r["fecha"]
        cands = [(k, v) for k, v in cz.items() if k[0] == lg and abs((dt.date.fromisoformat(k[1]) - dt.date.fromisoformat(f)).days) <= 1
                 and _mismo(k[2], _norm(r["home"])) and _mismo(k[3], _norm(r["away"]))]
        if not cands:
            sin += 1; continue
        c = cands[0][1]
        try:
            real = float(r["real"])
        except (TypeError, ValueError):
            continue
        vm = None
        try:
            vm = float(r["valor_modelo"]) if r.get("valor_modelo") not in (None, "") else None
        except ValueError:
            vm = None
        p_mod = None
        try:
            p_mod = float(r["p_modelo"])
        except (TypeError, ValueError):
            pass
        # lado del modelo contra el CIERRE: por total esperado si existe; si no, por el lado registrado (vs su linea)
        if vm is not None:
            lado = "over" if vm > c["linea"] else ("under" if vm < c["linea"] else None); brecha = abs(vm - c["linea"])
        else:
            lado = r["lado"]; brecha = None
        acierto = None
        if lado and real != c["linea"]:
            acierto = 1 if ((real > c["linea"]) == (lado == "over")) else 0
        por_liga[lg].append({"fecha": f, "home": r["home"], "away": r["away"], "cierre": c["linea"], "p_over_cierre": c["p_over"], "real": real,
                             "modelo_total": vm, "lado_modelo": lado, "brecha": brecha, "acierto": acierto, "push": real == c["linea"]})
    res = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "predicciones_total": len(pred), "sin_cierre": sin, "ligas": {}}
    print("TOTALES vs LINEA DE CIERRE (Pinnacle): %d predicciones de total calificadas, %d sin foto de cierre" % (len(pred), sin))
    for lg, xs in sorted(por_liga.items()):
        n = len(xs)
        mae_c = sum(abs(x["cierre"] - x["real"]) for x in xs) / n
        con_vm = [x for x in xs if x["modelo_total"] is not None]
        mae_m = (sum(abs(x["modelo_total"] - x["real"]) for x in con_vm) / len(con_vm)) if con_vm else None
        ac = [x for x in xs if x["acierto"] is not None]
        pct = (100.0 * sum(x["acierto"] for x in ac) / len(ac)) if ac else None
        # por brecha
        u = UNIDAD.get(lg, 1.0); bandas = {}
        for lo, hi, nom in ((0, u, "<%g" % u), (u, 2 * u, "%g-%g" % (u, 2 * u)), (2 * u, 99, ">=%g" % (2 * u))):
            b = [x for x in ac if x["brecha"] is not None and lo <= x["brecha"] < hi]
            if b:
                bandas[nom] = {"n": len(b), "acierto_pct": round(100.0 * sum(x["acierto"] for x in b) / len(b), 1)}
        # calibracion de Pinnacle: over real vs p_over
        ov = [x for x in xs if not x["push"]]
        real_over = (100.0 * sum(1 for x in ov if x["real"] > x["cierre"]) / len(ov)) if ov else None
        p_med = (100.0 * sum(x["p_over_cierre"] for x in ov) / len(ov)) if ov else None
        res["ligas"][lg] = {"n": n, "mae_cierre": round(mae_c, 3), "mae_modelo": None if mae_m is None else round(mae_m, 3), "n_modelo_total": len(con_vm),
                            "acierto_lado_modelo_pct": None if pct is None else round(pct, 1), "n_acierto": len(ac), "por_brecha": bandas,
                            "pinnacle_p_over_media_pct": None if p_med is None else round(p_med, 1), "over_real_pct": None if real_over is None else round(real_over, 1)}
        print("  %-7s n=%3d | MAE cierre %.3f | MAE modelo %s (n=%d) | lado del modelo vs cierre %s%% (n=%d; paga desde 52.4%%) | bandas %s | Pinnacle p_over %s%% vs over real %s%%" % (
            lg, n, mae_c, ("%.3f" % mae_m) if mae_m is not None else "-", len(con_vm), ("%.1f" % pct) if pct is not None else "-", len(ac),
            ", ".join("%s: %d/%s%%" % (k, v["n"], v["acierto_pct"]) for k, v in bandas.items()) or "-",
            ("%.1f" % p_med) if p_med is not None else "-", ("%.1f" % real_over) if real_over is not None else "-"))
    with io.open(os.path.join(SAL, "totales_vs_linea.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("Escrito salida/totales_vs_linea.json. Nota: valor_modelo (total esperado) se registra desde el 4-oct; antes solo hay lado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
