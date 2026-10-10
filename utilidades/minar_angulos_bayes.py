# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_bayes.py - el modelo bayesiano jerarquico de minar_angulos_bayes_hockey.py en basquet y beisbol.

Hipotesis (registrada antes de correr, 10-oct-2026): los angulos de ganador que NO tienen peso, juntos y con efectos
compartidos entre ligas, mejoran la prediccion as-of DE PRODUCCION fuera de muestra (z >= 2.0, las dos mitades, calibrado).
La base ya trae las capas aprobadas, con el mismo beta que plataforma.py:
    NBA      K14 ausencias (beta 0.308 por 48 min de ausentes)
    beisbol  S4 frio contra caliente (beta 0.161)
asi que la prueba mide si lo DEMAS agrega algo.

Basquet (NBA y NCAAMB): K1-K4, K8a, K8b, K10, K11 (solo NBA), K12, K13 (altitud), Q1-Q7, S1-S3, S7, S8.
Beisbol (MLB, NPB, KBO, LMP, LVBP, LIDOM, ABL): B1, B2, B5, B10-B15, B18, B19 (LMP/NPB), B21, B25 (Coors), Q1-Q7,
S1-S3, S7, S8. En beisbol la prediccion as-of es la del minado (logistica con el 35 % / 70 % mas antiguo de cada liga).

Uso:
    python utilidades/minar_angulos_bayes.py --deporte nba
    python utilidades/minar_angulos_bayes.py --deporte beisbol [--cache] [--ml]
Escribe trabajo/minar/2026-10-10_bayes_<deporte>_resultados.json
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, contextlib, datetime as dt, io, json, math, os, pickle, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_angulos_bayes_hockey as B  # noqa: E402

QS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6a", "Q6b", "Q7"]
SS = ["S1", "S2", "S3", "S7", "S8"]
CFG = {
    "nba": dict(ligas=["NBA", "NCAAMB"], ang=["K1", "K2", "K3", "K4", "K8a", "K8b", "K10", "K11", "K12", "K13"] + QS + SS,
                capa=("K14", 0.308), t5="NBA"),
    "beisbol": dict(ligas=["MLB", "NPB", "KBO", "LMP", "LVBP", "LIDOM", "ABL"],
                    ang=["B1", "B2", "B5", "B10", "B11", "B12", "B13", "B14", "B15", "B18", "B19", "B21", "B25"] + QS + SS,
                    capa=("S4", 0.161), t5="BEISBOL"),
}


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def armar(dep):
    import minar_situacionales as M
    import minar_cualitativos as Q
    import minar_angulos_tanda5 as T5
    import minar_angulos_tanda3 as T3
    cfg = CFG[dep]
    grupos = []
    if dep == "nba":
        with contextlib.redirect_stdout(io.StringIO()):
            T3.basquet()                              # NBA con K12, K13 y K14 (corre correr_basquet("NBA"))
        grupos.append(("NBA",) + M.ULTIMO["NBA"])
        with contextlib.redirect_stdout(io.StringIO()):
            M.correr_basquet("NCAAMB")
        F, C = M.ULTIMO["NCAAMB"]
        for r in F:
            r["K12"] = M._ind((C.en_ventana(r["away"], r["gp"], 5) or 0) >= 3) - M._ind((C.en_ventana(r["home"], r["gp"], 5) or 0) >= 3)
            r["K13"] = 0; r["K14"] = None
        grupos.append(("NCAAMB", F, C))
    else:
        with contextlib.redirect_stdout(io.StringIO()):
            T3.beisbol()                              # todas las ligas con B25 en MLB
        F, C = M.ULTIMO["BEISBOL"]
        grupos.append((None, F, C))
    filas = []
    for liga_fija, F, C in grupos:
        T = Q.Tabla(C)
        F5 = {(str(r["gp"]), str(r["home"])): r for r in T5.construir(cfg["t5"], F, C)}
        for r in F:
            liga = liga_fija or r["liga"]
            x = {k: r.get(k) for k in cfg["ang"] if not (k in QS or k in SS)}
            s = Q.situaciones(r, C, T)
            for c in QS:
                lado = s.get(c)
                x[c] = 1 if lado == "H" else (-1 if lado == "A" else 0)
            s5 = F5.get((str(r["gp"]), str(r["home"]))) or {}
            for c in SS:
                x[c] = s5.get(c)
            capa, beta = cfg["capa"]
            v = r.get(capa) if capa != "S4" else s5.get("S4")
            p = r["p"] if not v else _sig(_lg(r["p"]) + beta * v)        # la capa aprobada va en la base, como en produccion
            filas.append(dict(liga=liga, fecha=str(r["fecha"])[:10], gp=str(r["gp"]), p=float(p), y=int(r["y"]),
                              home=str(r["home"]), away=str(r["away"]),
                              x={k: (0.0 if x.get(k) is None else float(x[k])) for k in cfg["ang"]}))
    filas.sort(key=lambda r: (r["fecha"], r["liga"], r["gp"]))
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", required=True, choices=sorted(CFG))
    ap.add_argument("--cache", action="store_true")
    ap.add_argument("--ml", action="store_true")
    a = ap.parse_args()
    cfg = CFG[a.deporte]
    B.LIGAS = cfg["ligas"]; B.ANG = cfg["ang"]
    cache = os.path.join(CODIGO, "trabajo", "minar", "bayes_%s_filas.pkl" % a.deporte)
    out_ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_bayes_%s_resultados.json" % a.deporte)
    if a.cache and os.path.exists(cache):
        F = pickle.load(open(cache, "rb"))
    else:
        print("armando filas de %s..." % a.deporte)
        F = armar(a.deporte)
        pickle.dump(F, open(cache, "wb"))
    F = [r for r in F if r["liga"] in B.LIGAS]
    print("%d partidos, %d angulos; desde %s hasta %s" % (len(F), len(B.ANG), F[0]["fecha"], F[-1]["fecha"]))
    for L in B.LIGAS:
        G = [r for r in F if r["liga"] == L]
        if G:
            print("  %-7s %6d  %s a %s" % (L, len(G), G[0]["fecha"], G[-1]["fecha"]))
    print("\nwalk-forward mensual")
    P = B.walk_forward(F)
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "deporte": a.deporte, "angulos": B.ANG,
           "capa_en_base": cfg["capa"], "total": B.veredicto(P, {"nba": "BASQUET", "beisbol": "BEISBOL"}[a.deporte]),
           "por_liga": [B.veredicto([p for p in P if p["liga"] == L], L) for L in B.LIGAS]}
    print("\nRESULTADO")
    for v in [res["total"]] + res["por_liga"]:
        if v.get("n"):
            print("  %-10s n %6d  mejora %+.3f mil  z %+5.2f  mitades %+.3f/%+.3f  Brier %+.2f%%  cal %+.4f (peor decil %.3f)  "
                  "mueve %.2f pp  -> %s" % (v["grupo"], v["n"], v["mejora_milesimas"], v["z"], v["mitades"][0], v["mitades"][1],
                                         v["brier_mejora_pct"], v["calibracion"], v["cal_peor_decil"], v["mueve_pp_medio"],
                                         v["veredicto"].upper()))
    ef = B.efectos_finales(F)
    res["efectos"] = ef
    print("\nefectos con todo el historial (tau %.2f, sig %.3f)" % (ef["tau"], ef["sig"]))
    for e in ef["angulos"][:15]:
        print("  %-4s activos %7d  comun %+5.2f pp  %s" % (e["codigo"], e["activos"], e["comun_pp"],
                                                       " ".join("%s %+.2f" % (k, v) for k, v in e["por_liga_pp"].items())))
    if a.ml:
        R = B.comparar_ml(F)
        res["comparacion_ml"] = R
        for k, v in R.items():
            print("  %-34s n %6d  mejora %+.3f mil  z %+5.2f  mitades %+.3f/%+.3f  Brier %+.2f%%  -> %s" % (
                k, v["n"], v["mejora_milesimas"], v["z"], v["mitades"][0], v["mitades"][1], v["brier_mejora_pct"], v["veredicto"].upper()))
    with open(out_ruta, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nresultados en", out_ruta)


if __name__ == "__main__":
    main()
