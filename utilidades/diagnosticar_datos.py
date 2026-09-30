# -*- coding: utf-8 -*-
"""C:\Edgeline\diagnosticar_datos.py - resume cada CSV de datos\ : filas, ligas, rango de fechas, ultimo juego."""
import csv, glob, os, collections
BASE = os.path.dirname(os.path.abspath(__file__))
for ruta in sorted(glob.glob(os.path.join(BASE, "datos", "*.csv"))):
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f); cols = rd.fieldnames or []; rows = list(rd)
    print("\n== %s  filas=%d" % (os.path.basename(ruta), len(rows)))
    print("   columnas:", ", ".join(cols[:14]), "..." if len(cols) > 14 else "")
    fc = next((c for c in cols if c in ("game_date", "date", "Date", "fecha", "tourney_date")), None)
    lc = next((c for c in cols if c.lower() in ("league", "liga", "div")), None)
    if fc:
        fs = sorted(r[fc] for r in rows if r.get(fc))
        if fs: print("   fechas: %s  ->  %s" % (fs[0], fs[-1]))
    if lc:
        by = collections.defaultdict(list)
        for r in rows:
            by[r[lc]].append(r.get(fc, "") if fc else "")
        for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
            v = sorted(x for x in v if x)
            print("   %-14s %6d  %s -> %s" % (k, len(v) or len(by[k]), v[0] if v else "", v[-1] if v else ""))
print("\n== raiz de C:\\Edgeline (archivos .py):")
for p in sorted(glob.glob(os.path.join(BASE, "*.py"))):
    print("   ", os.path.basename(p))
