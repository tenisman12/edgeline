# -*- coding: utf-8 -*-
"""
utilidades/limpiar_historial.py - quita de salida\\historial_picks.csv los picks de PRETEMPORADA que se colaron.
Guarda una copia en salida\\historial_picks.respaldo.csv antes de cambiar nada.

    python utilidades\\limpiar_historial.py            (solo muestra que quitaria)
    python utilidades\\limpiar_historial.py --aplicar  (quita y guarda)
"""
import argparse, csv, os, shutil, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRE_INICIO = {"nhl": "2026-10-07"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    ruta = os.path.join(BASE, "salida", "historial_picks.csv")
    if not os.path.exists(ruta):
        print("No existe %s" % ruta); return 1
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh); cols = rd.fieldnames; filas = list(rd)
    quitar = [r for r in filas if PRE_INICIO.get(r["liga"]) and r["fecha"] < PRE_INICIO[r["liga"]]]
    quedan = [r for r in filas if r not in quitar]
    print("Picks en el historial: %d | de pretemporada: %d | quedarian: %d" % (len(filas), len(quitar), len(quedan)))
    for r in quitar:
        print("  quitar: %s %s %s @ %s (%s)" % (r["liga"], r["fecha"], r["away"], r["home"], r["pick"]))
    if a.aplicar and quitar:
        shutil.copy2(ruta, os.path.join(BASE, "salida", "historial_picks.respaldo.csv"))
        with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(quedan)
        print("Listo. Copia anterior en salida\\historial_picks.respaldo.csv")
    elif quitar:
        print("Para aplicar: python utilidades\\limpiar_historial.py --aplicar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
