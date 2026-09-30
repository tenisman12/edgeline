# -*- coding: utf-8 -*-
"""Imprime la forma de un scoreboard de tenis de ESPN y un partido terminado, para escribir el colector.
Uso:  python utilidades\\inspeccionar_espn_tenis.py data_maestra\\espn_tenis_atp.json"""
import json, sys

def forma(x, nivel=0, tope=3, clave=""):
    pad = "  " * nivel
    if isinstance(x, dict):
        print("%s%s{dict %d claves}" % (pad, clave + ": " if clave else "", len(x)))
        if nivel < tope:
            for k, v in list(x.items())[:40]:
                if isinstance(v, (dict, list)): forma(v, nivel + 1, tope, k)
                else: print("%s  %s: %s" % (pad, k, repr(v)[:70]))
    elif isinstance(x, list):
        print("%s%s[lista %d]" % (pad, clave + ": " if clave else "", len(x)))
        if x and nivel < tope: forma(x[0], nivel + 1, tope, "[0]")

d = json.load(open(sys.argv[1], encoding="utf-8"))
print("CLAVES RAIZ:", list(d.keys()))
evs = d.get("events") or []
print("eventos (torneos):", len(evs))
if evs:
    e = evs[0]
    print("torneo:", e.get("name"), "| claves:", list(e.keys()))
    grupos = e.get("groupings") or []
    print("groupings:", [(g.get("grouping", {}).get("displayName"), len(g.get("competitions") or [])) for g in grupos])
    hecho = None
    for g in grupos:
        for c in g.get("competitions") or []:
            if (c.get("status", {}).get("type", {}).get("completed")):
                hecho = c; break
        if hecho: break
    if hecho:
        print("\n--- PARTIDO TERMINADO (estructura) ---")
        forma(hecho, 0, 4)
    else:
        print("sin partidos terminados en el primer torneo")
