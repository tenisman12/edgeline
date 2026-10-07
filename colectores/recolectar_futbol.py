# -*- coding: utf-8 -*-
"""
RECOLECTAR FUTBOL (ENRIQUECIDO) - football-data.co.uk, toda la data por partido.

Captura goles (final y medio tiempo), TIROS, tiros a puerta, CORNERS, faltas y
TARJETAS por equipo-juego. Con esto el modelo puede usar xG proxy (tiros a puerta),
corners y tarjetas, no solo goles.

NOTA: Liga MX y Champions no estan aqui (necesitan fuente con key).

Uso:
    python recolectar_futbol.py --desde 2021
Escribe:  data_maestra/futbol_games.csv   (copia a datos/futbol.csv)
"""
import argparse, csv, io, os, datetime as dt
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "futbol_games.csv")
DIVS = {"E0": "Premier", "SP1": "LaLiga", "I1": "SerieA", "D1": "Bundesliga", "F1": "Ligue1"}
URL = "https://www.football-data.co.uk/mmz4281/%s/%s.csv"
# (col football-data del LOCAL, col del VISITANTE, nombre en nuestro esquema)
MAP = [("FTHG","FTAG","goals"), ("HTHG","HTAG","goals_ht"), ("HS","AS","shots"),
       ("HST","AST","shots_target"), ("HC","AC","corners"), ("HF","AF","fouls"),
       ("HY","AY","yellow"), ("HR","AR","red")]


def temporadas(desde):
    hoy = dt.date.today(); fin = hoy.year if hoy.month >= 7 else hoy.year - 1
    return ["%02d%02d" % (y % 100, (y + 1) % 100) for y in range(desde, fin + 1)]

FALLOS = []        # (div, temp, motivo): se traga nada, se reporta todo


def bajar(div, temp):
    """Baja una liga-temporada. Antes se tragaba cualquier excepcion y devolvia None, y el colector seguia
    como si nada: el 6-oct-2026 las cinco ligas europeas llevaban 16 dias sin resultados y nada lo reporto.
    Ahora cada fallo se registra en FALLOS y main() los imprime y sale con codigo 1."""
    req = urllib.request.Request(URL % (temp, div), headers={"User-Agent": "Edgeline/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            cuerpo = r.read().decode("latin-1", "replace")
        filas = list(csv.DictReader(io.StringIO(cuerpo)))
        if not filas:
            FALLOS.append((div, temp, "la respuesta vino vacia (%d bytes)" % len(cuerpo)))
        return filas
    except Exception as e:
        FALLOS.append((div, temp, "%s: %s" % (type(e).__name__, str(e)[:90])))
        return None

def _fecha(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except (ValueError, TypeError):
            pass
    return ""

def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2021)
    args = ap.parse_args()
    filas = []
    for temp in temporadas(args.desde):
        for div, liga in DIVS.items():
            rows = bajar(div, temp)
            if not rows:
                continue
            n = 0
            for g in rows:
                h, a = g.get("HomeTeam"), g.get("AwayTeam")
                if not h or not a or g.get("FTHG") in (None, "") or g.get("FTAG") in (None, ""):
                    continue
                fecha = _fecha(g.get("Date"))
                gid = "%s_%s_%s_%s" % (liga, temp, h.replace(" ", ""), a.replace(" ", ""))
                for lado, rival in (("home", "away"), ("away", "home")):
                    fila = {"gamePk": gid, "league": liga, "season": temp, "game_date": fecha,
                            "team": h if lado == "home" else a, "opp": a if lado == "home" else h,
                            "is_home": 1 if lado == "home" else 0}
                    for ch, ca, nom in MAP:
                        propio = ch if lado == "home" else ca
                        rivalc = ca if lado == "home" else ch
                        fila[nom] = num(g.get(propio))
                        fila[nom + "_opp"] = num(g.get(rivalc))
                    # alias para el modelo (usa goals/goals_opp)
                    filas.append(fila)
                n += 1
            if n:
                print("  %-10s %s: %d partidos" % (liga, temp, n))
    if not filas:
        print("Sin datos.")
        _reportar(None)
        return 1
    fijas = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home"]
    extras = sorted({k for f in filas for k in f if k not in fijas})
    cols = fijas + extras
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("\nEscritos %d equipo-juego, %d columnas, en:\n  %s" % (len(filas), len(cols), OUT))
    print("Ahora trae tiros/corners/tarjetas por partido. Copia a datos\\futbol.csv")
    return _reportar(filas)


def _reportar(filas):
    """Imprime los fallos y la frescura por liga. Devuelve 1 si algo esta mal, 0 si todo bien.
    'Mal' es: alguna liga-temporada no se pudo bajar, o la temporada en curso trae su ultimo partido
    con mas de ATRASO_MAX dias. Asi el paso del workflow se pone en rojo en lugar de pasar callado."""
    ATRASO_MAX = 9
    malo = 0
    if FALLOS:
        malo = 1
        print("\nFALLOS AL BAJAR (%d):" % len(FALLOS))
        for div, temp, motivo in FALLOS:
            print("  %s %s (%s): %s" % (DIVS.get(div, div), div, temp, motivo))
    if filas:
        hoy = dt.date.today()
        print("\nFrescura por liga:")
        for liga in sorted(DIVS.values()):
            fs = [f["game_date"] for f in filas if f.get("league") == liga and f.get("game_date")]
            if not fs:
                print("  %-10s sin partidos" % liga); malo = 1; continue
            u = max(fs)
            try:
                dias = (hoy - dt.date.fromisoformat(u)).days
            except ValueError:
                print("  %-10s ultima fecha ilegible (%r)" % (liga, u)); malo = 1; continue
            marca = ""
            if dias > ATRASO_MAX:
                marca = "  <-- ATRASADA"; malo = 1
            print("  %-10s ultimo %s (%d dias)%s" % (liga, u, dias, marca))
    if malo:
        print("\n::error::El colector de futbol no quedo al dia. Revisa los fallos de arriba: "
              "football-data.co.uk pudo cambiar de formato, bloquear al agente o estar caido.")
    return malo


if __name__ == "__main__":
    import sys as _s
    _s.exit(main() or 0)
