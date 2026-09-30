# -*- coding: utf-8 -*-
"""
RECOLECTAR FUTBOL EXTRA - Liga MX y MLS desde football-data.co.uk (archivos /new/MEX.csv y /new/USA.csv).
Un archivo por pais con todas las temporadas: una sola peticion por liga, sin llave.
Escribe data_maestra/futbol_extra.csv con el esquema de datos/futbol.csv (una fila por equipo y partido).
actualizar_todo.py lo mezcla (upsert) en datos/futbol.csv sin tocar el historial.

Uso:
    python colectores\\recolectar_futbol_extra.py --desde 2021
"""
import argparse, csv, io, os, datetime as dt
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")
OUT = os.path.join(BASE, "data_maestra", "futbol_extra.csv")
# archivo -> nombre de liga en datos/futbol.csv (io.norm: "LigaMX" coincide con la clave ligamx)
FUENTES = {"MEX": "LigaMX", "USA": "MLS"}
URL = "https://football-data.co.uk/new/%s.csv"      # sin www: evita la redireccion 302


def bajar(codigo):
    req = urllib.request.Request(URL % codigo, headers={"User-Agent": "Edgeline/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:       # urllib sigue redirecciones
        return list(csv.DictReader(io.StringIO(r.read().decode("latin-1", "replace"))))


def _fecha(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except (ValueError, TypeError):
            pass
    return ""


def _gol(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def filas_de(rows, liga, desde):
    out = []
    for g in rows:
        h, a = (g.get("Home") or "").strip(), (g.get("Away") or "").strip()
        gh, ga = _gol(g.get("HG")), _gol(g.get("AG"))
        fecha = _fecha(g.get("Date"))
        if not h or not a or gh is None or ga is None or not fecha:
            continue                                        # partido sin jugar o fila rota
        if int(fecha[:4]) < desde:
            continue
        season = str(g.get("Season") or "").replace("/", "-")
        gid = "%s_%s_%s_%s_%s" % (liga, fecha, h.replace(" ", ""), a.replace(" ", ""), season)
        for lado in ("home", "away"):
            es_h = lado == "home"
            out.append({"gamePk": gid, "league": liga, "season": season, "game_date": fecha,
                        "team": h if es_h else a, "opp": a if es_h else h, "is_home": 1 if es_h else 0,
                        "goals": gh if es_h else ga, "goals_opp": ga if es_h else gh})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2021)
    args = ap.parse_args()
    filas = []
    for cod, liga in FUENTES.items():
        try:
            rows = bajar(cod)
        except Exception as ex:
            print("  %s: no se pudo bajar (%s)" % (liga, str(ex)[:80])); continue
        f = filas_de(rows, liga, args.desde)
        fs = sorted(x["game_date"] for x in f)
        print("  %-8s %5d equipo-juego  %s a %s" % (liga, len(f), fs[0] if fs else "?", fs[-1] if fs else "?"))
        filas += f
    if not filas:
        print("Sin datos nuevos; no se escribe nada."); return
    cols = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "goals", "goals_opp"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(filas)
    print("Escritos %d filas en %s" % (len(filas), OUT))


if __name__ == "__main__":
    main()
