# -*- coding: utf-8 -*-
"""
RECOLECTAR TENIS - desde los repos de Jeff Sackmann (GitHub, gratis).

Baja los partidos ATP y WTA (superficie, best-of, marcador, y stats profundas de
saque/resto: aces, dobles faltas, puntos de saque, 1er/2do saque ganados, games de
saque, break points salvados/enfrentados) y los deja en un esquema unico.

Fuente y cita:
    Sackmann, Jeff. tennis_atp / tennis_wta. https://github.com/JeffSackmann

Uso (en tu compu, que si alcanza GitHub):
    python recolectar_tenis.py --desde 2020 --hasta 2026
Escribe:  data_maestra/tennis_matches.csv  (una fila por partido)
"""
import argparse, csv, io, os, urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "tennis_matches.csv")
REPOS = {"ATP": "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/%s/atp_matches_%d.csv",
         "WTA": "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/%s/wta_matches_%d.csv"}
RAMAS = ("master", "main")

# columnas de Sackmann que conservamos (contexto + saque/resto de ganador w_ y perdedor l_)
BASE_COLS = ["tourney_date", "tourney_name", "surface", "tourney_level", "best_of", "round",
             "winner_name", "loser_name", "score", "minutes", "winner_rank", "loser_rank",
             "winner_id", "loser_id", "winner_hand", "loser_hand"]
STAT = ["ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced"]


def bajar(patron, year):
    """Prueba la rama master y luego main. Devuelve (filas|None, detalle_del_error)."""
    err = ""
    for rama in RAMAS:
        url = patron % (rama, year)
        req = urllib.request.Request(url, headers={"User-Agent": "Edgeline/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode("utf-8", "replace")
            return list(csv.DictReader(io.StringIO(txt))), ""
        except Exception as e:
            err = "%s -> %s" % (url, str(e)[:60])
    return None, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2020)
    ap.add_argument("--hasta", type=int, default=2026)
    args = ap.parse_args()

    cols = ["tour"] + BASE_COLS + ["w_" + s for s in STAT] + ["l_" + s for s in STAT]
    filas = []
    for tour, patron in REPOS.items():
        n = 0
        for year in range(args.desde, args.hasta + 1):
            rows, err = bajar(patron, year)
            if not rows:
                print("  %s %d: sin archivo (%s)" % (tour, year, err))
                continue
            for r in rows:
                fila = {"tour": tour}
                for c in BASE_COLS:
                    fila[c] = r.get(c, "")
                for s in STAT:
                    fila["w_" + s] = r.get("w_" + s, "")
                    fila["l_" + s] = r.get("l_" + s, "")
                filas.append(fila)
                n += 1
            print("  %s %d: %d partidos" % (tour, year, len(rows)))
        print("%s total: %d" % (tour, n))

    if not filas:
        print("Sin datos. ¿Rango de años sin archivos aun?"); return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("\nEscritos %d partidos en:\n  %s" % (len(filas), OUT))
    print("Fuente: Jeff Sackmann tennis_atp / tennis_wta (github.com/JeffSackmann)")


if __name__ == "__main__":
    main()
