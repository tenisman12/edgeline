# -*- coding: utf-8 -*-
"""
RECUPERAR HISTORIAL - agrega a un CSV de datos\\ las filas que le faltan desde otro CSV (por ejemplo una
copia vieja), sin reemplazar ninguna fila existente. Sirve para recuperar temporadas antiguas.
Llave de juego: (gamePk, is_home) y, para tenis, (tourney_date, winner_name, loser_name, round).
Guarda respaldo en datos\\_respaldo\\ antes de escribir.

Uso:
    python utilidades\\recuperar_historial.py --origen C:\\Edgeline\\datos\\beisbol.csv --destino datos\\beisbol.csv
    (agrega --aplicar para escribir; sin eso solo muestra lo que recuperaria)
"""
import argparse, csv, os, shutil

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")


def leer(ruta):
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), list(rd)


def llave(r):
    gp = r.get("gamePk")
    if gp not in (None, ""):
        gp = str(gp)
        if gp.endswith(".0"): gp = gp[:-2]
        lado = str(r.get("is_home")).replace(".0", "") if r.get("is_home") not in (None, "") else str(r.get("team"))
        return (gp, lado)
    return (str(r.get("tourney_date")), str(r.get("winner_name")), str(r.get("loser_name")), str(r.get("round")))


def llave_fe(r):
    """Llave alternativa: liga + fecha + equipo + lado. Sirve cuando dos copias usan gamePk distinto."""
    eq = r.get("team") or r.get("team_name") or r.get("equipo") or ""
    lado = str(r.get("is_home")).replace(".0", "")
    return (str(r.get("league") or ""), (r.get("game_date") or "")[:10], "".join(ch for ch in eq.lower() if ch.isalnum()), lado)


def fecha(r):
    return r.get("game_date") or r.get("tourney_date") or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origen", required=True)
    ap.add_argument("--destino", required=True)
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--llave", choices=["gamepk", "fecha"], default="gamepk",
                    help="gamepk: (gamePk,is_home). fecha: (liga,fecha,equipo,lado), para copias con ids distintos")
    ap.add_argument("--ligas", help="solo recuperar estas ligas (ej. LMP,LVBP,LIDOM,ABL)")
    ap.add_argument("--hasta", help="solo recuperar filas con fecha anterior o igual a AAAA-MM-DD")
    a = ap.parse_args()
    dst = a.destino if os.path.isabs(a.destino) else os.path.join(BASE, a.destino)
    co, filas = leer(dst); cs, otras = leer(a.origen)
    K = llave if a.llave == "gamepk" else llave_fe
    vistas = {K(r) for r in filas}
    if a.ligas:
        L = {x.strip().upper() for x in a.ligas.split(",")}
        otras = [r for r in otras if (r.get("league") or "").upper() in L]
    if a.hasta:
        otras = [r for r in otras if fecha(r)[:10] <= a.hasta]
    faltan = [r for r in otras if K(r) not in vistas]
    dup = len(faltan) - len({K(r) for r in faltan})
    if dup: print("Aviso: %d filas repetidas dentro de lo que se recuperaria; se conserva una por llave." % dup)
    unico = {}
    for r in faltan: unico.setdefault(K(r), r)
    faltan = list(unico.values())
    fs = sorted(fecha(r)[:10] for r in faltan if fecha(r))
    print("Destino: %d filas | Origen: %d filas | faltan en destino: %d %s" % (
        len(filas), len(otras), len(faltan), ("(%s a %s)" % (fs[0], fs[-1])) if fs else ""))
    if not faltan:
        print("Nada que recuperar."); return
    if not a.aplicar:
        print("Vista previa. Agrega --aplicar para escribir."); return
    cols = list(co) + [c for c in cs if c not in co]
    todas = filas + faltan
    campo = "game_date" if "game_date" in cols else ("tourney_date" if "tourney_date" in cols else None)
    if campo: todas.sort(key=lambda r: (r.get(campo) or "", str(r.get("gamePk") or "")))
    os.makedirs(os.path.join(BASE, "datos", "_respaldo"), exist_ok=True)
    shutil.copy2(dst, os.path.join(BASE, "datos", "_respaldo", "antes_recuperar_" + os.path.basename(dst)))
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval=""); w.writeheader(); w.writerows(todas)
    print("Listo: %s ahora tiene %d filas." % (dst, len(todas)))


if __name__ == "__main__":
    main()
