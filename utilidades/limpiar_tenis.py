# -*- coding: utf-8 -*-
"""
utilidades/limpiar_tenis.py - quita de datos\\tenis.csv los partidos REPETIDOS (misma llave torneo + ronda + ganador +
perdedor + marcador). TML repite algunos partidos de torneos por equipos (United Cup, Davis Cup) con otra fecha de
torneo. Se queda con la primera aparicion. Guarda copia en datos\\tenis.respaldo.csv.

    python utilidades\\limpiar_tenis.py            (solo cuenta)
    python utilidades\\limpiar_tenis.py --aplicar
"""
import argparse, csv, os, shutil, sys

csv.field_size_limit(10 ** 8)
BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    ruta = os.path.join(BASE, "datos", "tenis.csv")
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh); cols = rd.fieldnames; filas = list(rd)
    vistos, quedan, quitadas = set(), [], []
    for r in filas:
        k = (r.get("tourney_id"), r.get("round"), r.get("winner_name"), r.get("loser_name"))
        if all(k) and k in vistos:
            quitadas.append(r); continue
        vistos.add(k); quedan.append(r)
    print("Filas: %d | repetidas: %d | quedarian: %d" % (len(filas), len(quitadas), len(quedan)))
    por = {}
    for r in quitadas:
        por[r.get("tourney_name")] = por.get(r.get("tourney_name"), 0) + 1
    for n, c in sorted(por.items(), key=lambda z: -z[1])[:10]:
        print("  %-45s %d" % (n, c))
    if a.aplicar and quitadas:
        shutil.copy2(ruta, os.path.join(BASE, "datos", "tenis.respaldo.csv"))
        with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(quedan)
        print("Listo. Copia anterior en datos\\tenis.respaldo.csv (borrala cuando verifiques; no la subas a GitHub)")
    elif quitadas:
        print("Para aplicar: python utilidades\\limpiar_tenis.py --aplicar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
