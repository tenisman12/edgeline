# -*- coding: utf-8 -*-
"""
utilidades/motor_puntos.py - valida el MOTOR DE PUNTOS de la NFL (nucleo/motor_puntos.py) contra PRODUCCION y contra el
CIERRE del mercado (nfl_lineas.csv: moneyline, spread y total de cierre con sus precios). 10-oct-2026.

Hipotesis (registrada antes de correr): el motor (ataque, defensa y QB titular con Kalman, EPA como segunda observacion,
ventaja de local que se mueve, descanso, juego divisional, viento) (a) le gana a produccion (modelos/americano.py) en
ganador, spread y totales, y (b) solo o apilado con el cierre le gana al cierre (log loss) en moneyline, spread o total.
Protocolo de siempre: n >= 300, z >= 2.0, las dos mitades, calibrado.

Afinado por coordenadas con lo anterior a --corte (2023-08-01: temporadas 2015-2022, con EPA desde 2021 y QB desde 2018)
por error cuadratico de los puntos de cada equipo; la prueba es 2023-2026. Primera corrida (corte al 40 %, 2019-11) en el md.
Produccion reproducida como validar_mercados: americano.entrenar con lo anterior a cada bloque de 30 dias.

Uso:
    python utilidades/motor_puntos.py [--guardar]
Escribe trabajo/minar/2026-10-10_motor_puntos_resultados.json; --guardar escribe modelos/motor_puntos.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, math, os, sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
from nucleo import io, mercado  # noqa: E402
from nucleo import motor_puntos as MP  # noqa: E402
import motor_carreras as U  # noqa: E402

RUTA_OUT = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_motor_puntos_resultados.json")
BASE_PRM = dict(q=1.0, rho=0.6, p0=9.0, we=0.0, sd=10.0, qb0=-1.5, pq0=9.0, bye=0.0, corta=0.0, div=0.0, viento=0.0)
REJILLA = dict(q=[0.25, 0.5, 1.0, 2.0, 4.0], rho=[0.3, 0.45, 0.6, 0.75, 0.9], p0=[2.0, 4.0, 9.0, 16.0],
               we=[0.0, 0.25, 0.5, 1.0, 2.0], sd=[8.0, 10.0, 12.0], qb0=[0.0, -1.5, -3.0, -4.5], pq0=[2.0, 4.0, 9.0, 16.0],
               bye=[0.0, 0.5, 1.0, 1.5], corta=[0.0, -0.5, -1.0], div=[0.0, 1.0, 2.0], viento=[0.0, 0.2, 0.4, 0.6])


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sse(G, pred, desde, hasta):
    s = n = 0
    for g in G:
        if desde <= g["f"] < hasta and g["gp"] in pred:
            mh, ma = pred[g["gp"]][:2]
            s += (g["ph"] - mh) ** 2 + (g["pa"] - ma) ** 2; n += 1
    return s / max(n, 1)


def afinar(G, corte):
    calent = (dt.date.fromisoformat(G[0]["f"]) + dt.timedelta(days=365)).isoformat()
    prm = dict(BASE_PRM)
    mejor = sse(G, MP.correr(G, prm), calent, corte)
    for vuelta in range(2):
        for k, vals in REJILLA.items():
            for v in vals:
                t = dict(prm, **{k: v})
                e = sse(G, MP.correr(G, t), calent, corte)
                if e < mejor - 1e-9:
                    mejor, prm = e, t
        print("  vuelta %d: error cuadratico %.3f  %s" % (vuelta + 1, mejor, prm))
    return prm


def produccion(G, bloque=30):
    from modelos import americano as A
    orig = io.cargar_juegos
    out = {}
    d0 = dt.date.fromisoformat(G[0]["f"]); ultimo = dt.date.fromisoformat(G[-1]["f"])
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=bloque)
        blk = [g for g in G if d0.isoformat() <= g["f"] < d1.isoformat()]
        if blk and sum(1 for g in G if g["f"] < d0.isoformat()) >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = A.entrenar("NFL")
            finally:
                io.cargar_juegos = orig
            for g in blk:
                r = A.predecir(est, g["h"], g["a"], linea_total=g.get("total_l"), linea_spread=g.get("spread"))
                if r:
                    out[g["gp"]] = r
        d0 = d1
    return out


def novig(a, b):
    if a is None or b is None:
        return None
    pa, pb = mercado.prob_implicita(a), mercado.prob_implicita(b)
    return pa / (pa + pb)


def apilar_z(filas, minimo=300):
    """filas (fecha, y, p_mercado, z_motor): cada mes, logistica sobre [logit p_mercado, z_motor] con lo anterior."""
    from sklearn.linear_model import LogisticRegression
    filas = sorted(filas); out = []
    for m in sorted({f[0][:7] for f in filas}):
        prev = [f for f in filas if f[0][:7] < m]; cur = [f for f in filas if f[0][:7] == m]
        if len(prev) < minimo or len({f[1] for f in prev}) < 2:
            continue
        lr = LogisticRegression(C=1.0).fit(np.array([[_lg(f[2]), f[3]] for f in prev]), np.array([f[1] for f in prev]))
        q = lr.predict_proba(np.array([[_lg(f[2]), f[3]] for f in cur]))[:, 1]
        out += [(f[0], f[1], f[2], float(x)) for f, x in zip(cur, q)]
    return out


def ajustar_apilado(filas):
    from sklearn.linear_model import LogisticRegression
    if len(filas) < 300:
        return None
    lr = LogisticRegression(C=1.0).fit(np.array([[_lg(f[2]), f[3]] for f in filas]), np.array([f[1] for f in filas]))
    return [round(float(lr.intercept_[0]), 5), round(float(lr.coef_[0][0]), 5), round(float(lr.coef_[0][1]), 5)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guardar", action="store_true")
    ap.add_argument("--corte", default="2023-08-01",
                    help="fin del afinado. 2023-08-01: el EPA empieza en 2021 y el QB en 2018 (nfl_lineas); con el 40 %% el "
                         "afinado no tenia EPA y casi no tenia QB")
    a = ap.parse_args()
    G = MP.juegos("NFL")
    corte = a.corte
    print("NFL: %d juegos (%s a %s); afinado con lo anterior a %s" % (len(G), G[0]["f"], G[-1]["f"], corte))
    prm = afinar(G, corte)
    pred = MP.correr(G, prm)
    calent = (dt.date.fromisoformat(G[0]["f"]) + dt.timedelta(days=365)).isoformat()
    res_m = [(g["ph"] - g["pa"]) - (pred[g["gp"]][0] - pred[g["gp"]][1]) for g in G if calent <= g["f"] < corte]
    res_t = [(g["ph"] + g["pa"]) - (pred[g["gp"]][0] + pred[g["gp"]][1]) for g in G if calent <= g["f"] < corte]
    sd_m = float(np.std(res_m)); sd_t = float(np.std(res_t))
    print("  sd margen %.2f, sd total %.2f (afinado)" % (sd_m, sd_t))
    P = produccion(G)
    print("  produccion reproducida: %d juegos" % len(P))
    F = {k: [] for k in ("gan_p", "gan_m", "ats", "ou", "ou_p", "mar", "mar_m", "tot", "tot_m", "gan_mz", "ats_z", "ou_z")}
    for g in G:
        if g["gp"] not in pred:
            continue
        mh, ma = pred[g["gp"]][:2]
        r = MP.probs(mh, ma, sd_m, sd_t, g.get("spread"), g.get("total_l"))
        mar, tot = g["ph"] - g["pa"], g["ph"] + g["pa"]
        f = g["f"]
        pp = P.get(g["gp"])
        if mar != 0 and pp:
            F["gan_p"].append((f, 1 if mar > 0 else 0, pp["p_home"], r["p_home"]))
        pml = novig(g.get("ml_h"), g.get("ml_a"))
        if mar != 0 and pml is not None:
            F["gan_m"].append((f, 1 if mar > 0 else 0, pml, r["p_home"]))
            F["gan_mz"].append((f, 1 if mar > 0 else 0, pml, r["margen"] / sd_m))
        if g.get("spread") is not None and mar != g["spread"]:
            pc = novig(g.get("sp_oh"), g.get("sp_oa")) or 0.5
            F["ats"].append((f, 1 if mar > g["spread"] else 0, pc, r["p_cubre_home"]))
            F["ats_z"].append((f, 1 if mar > g["spread"] else 0, pc, (r["margen"] - g["spread"]) / sd_m))
            F["mar_m"].append((f, mar, g["spread"], r["margen"]))
            if pp:
                F["mar"].append((f, mar, pp["margen_esperado"], r["margen"]))
        if g.get("total_l") is not None and tot != g["total_l"]:
            po = novig(g.get("ov_o"), g.get("un_o")) or 0.5
            F["ou"].append((f, 1 if tot > g["total_l"] else 0, po, r["p_over"]))
            F["ou_z"].append((f, 1 if tot > g["total_l"] else 0, po, (r["total"] - g["total_l"]) / sd_t))
            F["tot_m"].append((f, tot, g["total_l"], r["total"]))
            if pp and pp.get("p_over") is not None:
                F["ou_p"].append((f, 1 if tot > g["total_l"] else 0, pp["p_over"], r["p_over"]))
            if pp:
                F["tot"].append((f, tot, pp["total_esperado"], r["total"]))
    prueba = lambda k: [x for x in F[k] if x[0] >= corte]
    gst = [x for x in apilar_z(F["gan_mz"]) if x[0] >= corte]
    ast = [x for x in apilar_z(F["ats_z"]) if x[0] >= corte]
    ost = [x for x in apilar_z(F["ou_z"]) if x[0] >= corte]
    R = {"liga": "NFL", "parametros": prm, "sd_m": round(sd_m, 3), "sd_t": round(sd_t, 3), "corte": corte, "mercados": []}
    print("\nprueba desde %s" % corte)
    for out in (U.comparar_prob(prueba("gan_p"), "Ganador (motor vs produccion)"),
                U.comparar_val(prueba("mar"), "Margen esperado (motor vs produccion)"),
                U.comparar_val(prueba("tot"), "Total esperado (motor vs produccion)"),
                U.comparar_prob(prueba("ou_p"), "Over/Under (motor vs produccion)"),
                U.comparar_prob(prueba("gan_m"), "Moneyline (motor vs cierre)"),
                U.comparar_prob(gst, "Moneyline (apilado vs cierre)"),
                U.comparar_prob(prueba("ats"), "Spread (motor vs cierre)"),
                U.comparar_prob(ast, "Spread (apilado vs cierre)"),
                U.comparar_prob(prueba("ou"), "Total (motor vs cierre)"),
                U.comparar_prob(ost, "Total (apilado vs cierre)"),
                U.comparar_val(prueba("mar_m"), "Margen (motor vs linea de cierre)"),
                U.comparar_val(prueba("tot_m"), "Total (motor vs linea de cierre)")):
        R["mercados"].append(out)
        if out.get("z") is None:
            print("  %-42s n %5d  %s" % (out["mercado"], out["n"], out["veredicto"].upper())); continue
        extra = ("Brier %+.2f%%  cal motor %+.3f (base %+.3f)" % (out["brier_mejora_pct"], out["cal_motor"], out["cal_prod"])) \
            if "brier_mejora_pct" in out else ("MAE %.3f -> %.3f  sesgo motor %+.2f" % (out["mae_prod"], out["mae_motor"], out["sesgo_motor"]))
        print("  %-42s n %5d  mejora %+8.3f  z %+6.2f  mitades %+.3f/%+.3f  %s  -> %s" % (
            out["mercado"], out["n"], out["mejora_milesimas"], out["z"], out["mitades"][0], out["mitades"][1], extra, out["veredicto"].upper()))
    ver = {o["mercado"]: o.get("veredicto") for o in R["mercados"]}
    R["aplicar"] = {"ganador_motor": ver.get("Ganador (motor vs produccion)") == "pasa",
                    "total_motor": ver.get("Over/Under (motor vs produccion)") == "pasa",
                    "ml_apilado": ver.get("Moneyline (apilado vs cierre)") == "pasa",
                    "spread_apilado": ver.get("Spread (apilado vs cierre)") == "pasa",
                    "total_apilado": ver.get("Total (apilado vs cierre)") == "pasa"}
    R["apilado"] = {"ml": ajustar_apilado(F["gan_mz"]), "spread": ajustar_apilado(F["ats_z"]), "total": ajustar_apilado(F["ou_z"])}
    with open(RUTA_OUT, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1)
    print("\nresultados en", RUTA_OUT)
    if a.guardar:
        cfg = {"generado": dt.datetime.now().isoformat(timespec="seconds"),
               "fuente": "utilidades/motor_puntos.py --guardar (trabajo/minar/2026-10-10_motor_puntos.md)",
               "ligas": {"nfl": {k: R[k] for k in ("parametros", "sd_m", "sd_t", "aplicar", "apilado", "corte")}}}
        with open(os.path.join(CODIGO, "modelos", "motor_puntos.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        print("configuracion de produccion en modelos/motor_puntos.json")


if __name__ == "__main__":
    main()
