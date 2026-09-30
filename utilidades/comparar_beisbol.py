# -*- coding: utf-8 -*-
"""Compara datos\\beisbol.csv (repo) con otra copia: filas por liga y temporada en cada una, y cuantas filas
de la copia estan en el repo segun dos llaves (gamePk o fecha+equipo). Solo lee.
Uso:  python utilidades\\comparar_beisbol.py C:\\Edgeline\\datos\\beisbol.csv"""
import csv, os, sys, collections
BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")

def leer(p):
    with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
        return list(csv.DictReader(f))

def gp(r):
    g = str(r.get("gamePk") or "")
    return (g[:-2] if g.endswith(".0") else g, str(r.get("is_home")).replace(".0", ""))

def fe(r):
    eq = r.get("team") or r.get("team_name") or ""
    return (r.get("league"), (r.get("game_date") or "")[:10], "".join(c for c in eq.lower() if c.isalnum()), str(r.get("is_home")).replace(".0", ""))

def temporada(r):
    f = (r.get("game_date") or "")[:10]
    return f[:4] if f[5:7] not in ("10", "11", "12") else str(int(f[:4]) + 1)     # invierno: temporada por año de cierre

def tabla(rows, titulo):
    c = collections.Counter((r.get("league"), temporada(r)) for r in rows)
    print("\n" + titulo)
    for lg in sorted({k[0] for k in c}):
        print("  %-6s %s" % (lg, "  ".join("%s:%d" % (y, c[(lg, y)]) for y in sorted(y for l, y in c if l == lg))))

a = leer(os.path.join(BASE, "datos", "beisbol.csv")); b = leer(sys.argv[1])
tabla(a, "REPO (%d filas)  formato liga  año:filas" % len(a)); tabla(b, "COPIA (%d filas)" % len(b))
ka = {gp(r) for r in a}; kf = {fe(r) for r in a}
print("\nFilas de la copia presentes en el repo:")
for lg in sorted({r.get("league") for r in b}):
    rr = [r for r in b if r.get("league") == lg]
    print("  %-6s %5d filas | por gamePk: %5d | por fecha+equipo: %5d" % (
        lg, len(rr), sum(1 for r in rr if gp(r) in ka), sum(1 for r in rr if fe(r) in kf)))
print("\nEjemplos de gamePk  REPO:", [gp(r)[0] for r in a[:3] + a[-3:]])
print("Ejemplos de gamePk  COPIA:", [gp(r)[0] for r in b[:3] + b[-3:]])
