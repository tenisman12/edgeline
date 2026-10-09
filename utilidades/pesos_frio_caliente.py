# -*- coding: utf-8 -*-
"""
utilidades/pesos_frio_caliente.py - coeficiente de produccion de S4 frio contra caliente en beisbol (tanda 5, z 2.02;
aprobado por Alejandro el 9-oct-2026: "se aplica todo a beisbol").
x = +1 si el local viene de 3 derrotas seguidas y la visita de 3 victorias seguidas, -1 al reves, 0 si no (misma temporada).
Ajuste con offset en toda la muestra de las 7 ligas: logit(q) = logit(p_modelo) + beta * x. Escribe la clave "beisbol_S4"
en modelos/capas_ausencias_minutos.json (la lee nucleo/angulos.aplicar_capa).

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/pesos_frio_caliente.py --cache trabajo/minar/tanda4_cache.pkl
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, os, pickle, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI); sys.path.insert(0, os.path.dirname(AQUI))
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_angulos_tanda5 as T5  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    if a.cache and os.path.exists(a.cache):
        D = pickle.load(open(a.cache, "rb"))
    else:
        D = T4.capturar()
        if a.cache: pickle.dump(D, open(a.cache, "wb"))
    filas, C = D["ultimo"]["BEISBOL"]
    F = T5.construir("BEISBOL", filas, C)
    R = [dict(r, x=r["S4"]) for r in F]
    b, se = T4.offset_beta(R)
    na = sum(1 for r in R if r["x"] != 0)
    print("S4 beisbol: beta %+.4f (EE %.4f), n %d, activos %d -> %+.2f pp en un partido de 50 %%" % (b, se, len(R), na, 100 * (T4._sig(b) - 0.5)))
    ruta = os.path.join(os.path.dirname(AQUI), "modelos", "capas_ausencias_minutos.json")
    d = json.load(open(ruta, encoding="utf-8"))
    d["beisbol_S4"] = {"beta": round(b, 4), "ee": round(se, 4), "n": len(R), "activos": na,
                       "desde": min(r["fecha"] for r in R), "hasta": max(r["fecha"] for r in R),
                       "x": "+1 si el local viene de 3 derrotas seguidas y la visita de 3 victorias seguidas (misma temporada, juegos "
                            "a 20 dias o menos), -1 al reves, 0 si no",
                       "fuente": "trabajo/minar/2026-10-09_tanda5.md (z 2.02 fuera de muestra); aprobado 9-oct-2026",
                       "generado": dt.date.today().isoformat()}
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("escrito", ruta)


if __name__ == "__main__":
    main()
