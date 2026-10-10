# -*- coding: utf-8 -*-
"""
utilidades/motor_goles.py - valida el MOTOR DE GOLES de hockey (nucleo/motor_goles.py) contra PRODUCCION, igual que
utilidades/motor_carreras.py en beisbol (10-oct-2026).

Hipotesis (registrada antes de correr): el motor (ataque, defensa y portero titular con Kalman, xG como segunda
observacion, segunda noche, prorroga) le gana a produccion fuera de muestra en ganador, total, puck line, empate a 60 min o
totales por equipo, con el protocolo de siempre (n >= 300, z >= 2.0, las dos mitades, calibrado).

Produccion reproducida como plataforma.py: modelos/hockey.entrenar con lo anterior a cada bloque de 30 dias,
hockey.predecir con fecha, segunda noche (jugo ayer) y GSAx del portero titular (rating_portero as-of), y la capa de
totales (bloques anteriores). Hiperparametros del motor con el 40 % mas viejo de cada liga.

Uso:
    python utilidades/motor_goles.py [--ligas NHL,LIIGA] [--guardar]
Escribe trabajo/minar/2026-10-10_motor_goles_resultados.json; --guardar escribe modelos/motor_goles.json (lo que usa plataforma).
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, itertools, json, math, os, sys
from collections import defaultdict

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
from nucleo import io  # noqa: E402
from nucleo import motor_goles as MG  # noqa: E402
import motor_carreras as U  # noqa: E402  (comparar_prob, comparar_val, apilar)

LIGAS = ["NHL", "LIIGA", "AHL", "DEL", "SHL"]
RUTA_OUT = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_motor_goles_resultados.json")


def _sig(z):
    return 1 / (1 + math.exp(-max(min(z, 35), -35)))


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def ll_goles(G, pred, r, desde, hasta):
    s = n = 0
    for g in G:
        if desde <= g["f"] < hasta and g["gp"] in pred:
            lh, la, _ = pred[g["gp"]]
            s += MG.nb_ll(g["rh"], lh, r) + MG.nb_ll(g["ra"], la, r); n += 1
    return s / max(n, 1)


def afinar(G, corte):
    inicio = G[0]["f"]
    calent = (dt.date.fromisoformat(inicio) + dt.timedelta(days=200)).isoformat()
    hay_xg = sum(1 for g in G if g["xh"] is not None) > 100
    hay_port = sum(1 for g in G if g["ph"]) > 300
    base = dict(q=0.0003, rho=0.6, p0=0.01, wx=0.0, portero=0, b2b_of=0.0, b2b_df=0.0)

    def r_mejor(prm):
        best = None
        for r in (10, 30, 100, 1000):
            v = ll_goles(G, MG.correr(G, prm, r), r, calent, corte)
            if best is None or v > best[0]:
                best = (v, r)
        return best[1]
    r = r_mejor(base)
    grid = dict(q=[0.0001, 0.0003, 0.001], rho=[0.3, 0.6, 0.9], p0=[0.003, 0.01],
                wx=[0.0, 0.5, 1.0] if hay_xg else [0.0], portero=[0, 1] if hay_port else [0],
                b2b=[(0.0, 0.0), (-0.04, 0.04), (-0.08, 0.08)])
    mejor = None
    for vals in itertools.product(*grid.values()):
        prm = dict(zip(grid.keys(), vals))
        prm["b2b_of"], prm["b2b_df"] = prm.pop("b2b")
        v = ll_goles(G, MG.correr(G, prm, r), r, calent, corte)
        if mejor is None or v > mejor[0]:
            mejor = (v, prm)
    prm = mejor[1]
    return prm, r_mejor(prm)


def produccion(liga, G, bloque=30):
    from modelos import hockey as H
    from nucleo import capa_totales as CT
    orig = io.cargar_juegos
    out, capa = {}, []
    ritmo = CT.Ritmo([(g["f"], g["h"], g["a"], g["gh"] + g["ga"]) for g in G])
    ult = {}
    b2b = {}
    for g in G:                                                  # segunda noche desde el calendario real
        for e in (g["h"], g["a"]):
            b2b[(g["gp"], e)] = e in ult and (dt.date.fromisoformat(g["f"]) - ult[e]).days == 1
            ult[e] = dt.date.fromisoformat(g["f"])
    d0 = dt.date.fromisoformat(G[0]["f"]); ultimo = dt.date.fromisoformat(G[-1]["f"]); nb = 0
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=bloque)
        blk = [g for g in G if d0.isoformat() <= g["f"] < d1.isoformat()]
        nprev = sum(1 for g in G if g["f"] < d0.isoformat())
        if blk and nprev >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = H.entrenar(liga)
            finally:
                io.cargar_juegos = orig
            nb += 1
            for g in blk:
                gx_h = H.rating_portero(g["ph"], g["f"])[0] if (g["ph"] and liga == "NHL") else None
                gx_a = H.rating_portero(g["pa"], g["f"])[0] if (g["pa"] and liga == "NHL") else None
                r = H.predecir(est, g["h"], g["a"], linea_total=6.5, fecha=g["f"],
                               jugo_ayer=(b2b[(g["gp"], g["h"])], b2b[(g["gp"], g["a"])]), gsax_home=gx_h, gsax_away=gx_a)
                if not r:
                    continue
                out[g["gp"]] = dict(p=r["p_home"], xh=r["xg_home"], xa=r["xg_away"], t=r["total"], p60=r["p_60"]["empate"],
                                    pl=r["p_pl_home"], b=nb)
                st = ritmo.estado(g["f"], g["h"], g["a"])
                if st:
                    capa.append(dict(gp=g["gp"], b=nb, pred=r["total"], real=g["gh"] + g["ga"], M=st[0], E=st[1], f=g["f"]))
        d0 = d1
    for bq in sorted({x["b"] for x in capa}):
        prev = [x for x in capa if x["b"] < bq]
        if len(prev) < CT.MIN_PREV:
            continue
        coef, res = CT.entrenar([(x["pred"], x["real"], x["M"], x["E"], x["f"]) for x in prev])
        for x in capa:
            if x["b"] == bq:
                out[x["gp"]]["t_capa"] = CT.total(coef, x["pred"], x["M"], x["E"]); out[x["gp"]]["res_capa"] = res
    return out


def pois_over(mu, L):
    return 1 - sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(int(math.floor(L)) + 1))


def evaluar_liga(liga):
    print("\n" + "=" * 100 + "\n%s" % liga)
    G = MG.juegos(liga)
    if len(G) < 800:
        print("  muestra insuficiente (%d juegos)" % len(G)); return None
    corte = G[int(len(G) * 0.4)]["f"]
    prm, r_nb = afinar(G, corte)
    print("  %d juegos (%s a %s); afinado con lo anterior a %s: %s, r %s" % (len(G), G[0]["f"], G[-1]["f"], corte, prm, r_nb))
    pred = MG.correr(G, prm, r_nb)
    P = produccion(liga, G)
    print("  produccion reproducida: %d juegos (%d con capa)" % (len(P), sum(1 for v in P.values() if "t_capa" in v)))
    acum = [0.0, 0.0, 0.0, 0]
    filas = []
    for g in G:
        if acum[3] >= 300 and g["gp"] in pred and g["gp"] in P:
            Lm = MG.medio(acum[0] / acum[3]); leq = (MG.medio(acum[1] / acum[3]), MG.medio(acum[2] / acum[3]))
            lh, la, ot = pred[g["gp"]]
            filas.append((g, MG.mercados(lh, la, r_nb, ot, [Lm], leq), P[g["gp"]], Lm, leq))
        acum[0] += g["gh"] + g["ga"]; acum[1] += g["gh"]; acum[2] += g["ga"]; acum[3] += 1
    L_ = defaultdict(list)                       # todas las filas (afinado + prueba) por mercado; se califica la prueba
    for g, mk, pp, Lm, leq in filas:
        y = 1 if g["gh"] > g["ga"] else 0; tot = g["gh"] + g["ga"]
        L_["gan"].append((g["f"], y, pp["p"], mk["p_home"]))
        if tot != Lm:
            L_["ou"].append((g["f"], 1 if tot > Lm else 0, pois_over(pp["t"], Lm), mk["over"][Lm]))
            if "t_capa" in pp:
                pc = sum(1 for e in pp["res_capa"] if pp["t_capa"] + e > Lm) / len(pp["res_capa"])
                L_["ouc"].append((g["f"], 1 if tot > Lm else 0, min(max(pc, 0.01), 0.99), mk["over"][Lm]))
        L_["pl"].append((g["f"], 1 if g["rh"] - g["ra"] >= 2 else 0, pp["pl"], mk["pl_home"]))
        if g["fin"] in ("REG", "OT", "SO"):
            L_["emp"].append((g["f"], 1 if g["fin"] in ("OT", "SO") else 0, pp["p60"], mk["p_empate60"]))
        L_["eqh"].append((g["f"], 1 if g["gh"] > leq[0] else 0, pois_over(pp["xh"], leq[0]), mk["eq_h"]))
        L_["eqa"].append((g["f"], 1 if g["ga"] > leq[1] else 0, pois_over(pp["xa"], leq[1]), mk["eq_a"]))
        L_["tv"].append((g["f"], tot, pp["t"], mk["total"]))
        if "t_capa" in pp:
            L_["tvc"].append((g["f"], tot, pp["t_capa"], mk["total"]))
        L_["xh"].append((g["f"], g["gh"], pp["xh"], mk["lh"])); L_["xa"].append((g["f"], g["ga"], pp["xa"], mk["la"]))
    prueba = lambda k: [f for f in L_[k] if f[0] >= corte]
    gst = [f for f in U.apilar(L_["gan"]) if f[0] >= corte]
    ost = [f for f in U.apilar(L_["ou"]) if f[0] >= corte]
    print("  prueba: %d juegos desde %s" % (len(prueba("gan")), corte))
    R = {"liga": liga, "parametros": prm, "r_nb": r_nb, "corte": corte, "n_prueba": len(prueba("gan")), "mercados": []}
    for out in (U.comparar_prob(prueba("gan"), "Ganador (motor vs produccion)"),
                U.comparar_prob(gst, "Ganador (apilado vs produccion)"),
                U.comparar_prob(prueba("ou"), "Over/Under linea ~promedio (vs produccion)"),
                U.comparar_prob(ost, "Over/Under (apilado vs produccion)"),
                U.comparar_prob(prueba("ouc"), "Over/Under (vs capa de totales)"),
                U.comparar_prob(prueba("pl"), "Puck line local -1.5"),
                U.comparar_prob(prueba("emp"), "Empate a 60 min"),
                U.comparar_prob(prueba("eqh"), "Goles local O/U"),
                U.comparar_prob(prueba("eqa"), "Goles visita O/U"),
                U.comparar_val(prueba("tv"), "Total esperado (vs produccion)"),
                U.comparar_val(prueba("tvc"), "Total esperado (vs capa de totales)"),
                U.comparar_val(prueba("xh"), "Goles local esperados"),
                U.comparar_val(prueba("xa"), "Goles visita esperados")):
        R["mercados"].append(out)
        if out.get("z") is None:
            print("  %-46s n %5d  %s" % (out["mercado"], out["n"], out["veredicto"].upper())); continue
        extra = ("Brier %+.2f%%  cal motor %+.3f (prod %+.3f)" % (out["brier_mejora_pct"], out["cal_motor"], out["cal_prod"])) \
            if "brier_mejora_pct" in out else ("MAE %.3f -> %.3f  sesgo motor %+.2f" % (out["mae_prod"], out["mae_motor"], out["sesgo_motor"]))
        print("  %-46s n %5d  mejora %+8.3f  z %+6.2f  mitades %+.3f/%+.3f  %s  -> %s" % (
            out["mercado"], out["n"], out["mejora_milesimas"], out["z"], out["mitades"][0], out["mitades"][1], extra, out["veredicto"].upper()))
    ver = {o["mercado"]: o.get("veredicto") for o in R["mercados"]}
    R["aplicar"] = {"ganador_apilado": ver.get("Ganador (apilado vs produccion)") == "pasa",
                    "ganador_motor": ver.get("Ganador (motor vs produccion)") == "pasa",
                    "ou_apilado": ver.get("Over/Under (apilado vs produccion)") == "pasa",
                    "ou_motor": ver.get("Over/Under linea ~promedio (vs produccion)") == "pasa",
                    "puck_line": ver.get("Puck line local -1.5") == "pasa",
                    "empate60": ver.get("Empate a 60 min") == "pasa",
                    "equipo_local": ver.get("Goles local O/U") == "pasa",
                    "equipo_visita": ver.get("Goles visita O/U") == "pasa",
                    "total_motor": ver.get("Total esperado (vs produccion)") == "pasa"}
    from sklearn.linear_model import LogisticRegression
    R["apilado"] = {}
    for clave, k in (("ganador", "gan"), ("ou", "ou")):
        F = L_[k]
        if len(F) >= 300:
            lr = LogisticRegression(C=1.0).fit(np.array([[_lg(f[2]), _lg(f[3])] for f in F]), np.array([f[1] for f in F]))
            R["apilado"][clave] = [round(float(lr.intercept_[0]), 5), round(float(lr.coef_[0][0]), 5), round(float(lr.coef_[0][1]), 5)]
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default=",".join(LIGAS))
    ap.add_argument("--guardar", action="store_true")
    a = ap.parse_args()
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "ligas": []}
    pedidas = [x.strip().upper() for x in a.ligas.split(",") if x.strip()]
    if os.path.exists(RUTA_OUT):
        try:
            res["ligas"] = [x for x in json.load(open(RUTA_OUT, encoding="utf-8")).get("ligas", []) if x["liga"] not in pedidas]
        except Exception:
            pass
    for L in pedidas:
        R = evaluar_liga(L)
        if R:
            res["ligas"].append(R)
            with open(RUTA_OUT, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nresultados en", RUTA_OUT)
    if a.guardar:
        cfg = {"generado": res["generado"], "fuente": "utilidades/motor_goles.py --guardar (trabajo/minar/2026-10-10_motor_goles.md)",
               "como_leer": "parametros del filtro por liga; aplicar = mercados que pasaron contra produccion; apilado = [a, b produccion, "
                            "c motor] en logit. Aprobado por Alejandro el 10-oct-2026.", "ligas": {}}
        for R in res["ligas"]:
            cfg["ligas"][R["liga"].lower()] = {k: R.get(k) for k in ("parametros", "r_nb", "aplicar", "apilado", "corte", "n_prueba")}
            cfg["ligas"][R["liga"].lower()]["z"] = {o["mercado"]: o.get("z") for o in R["mercados"] if o.get("z") is not None}
        with open(os.path.join(CODIGO, "modelos", "motor_goles.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        print("configuracion de produccion en modelos/motor_goles.json")


if __name__ == "__main__":
    main()
