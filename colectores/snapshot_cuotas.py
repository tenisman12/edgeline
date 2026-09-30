# -*- coding: utf-8 -*-
"""
SNAPSHOT DE CUOTAS - guarda la historia de las lineas (DraftKings via ESPN) para medir movimiento y CLV.

Lee contexto\\proximos_espn.json (lo deja recolectar_proximos.py) y agrega una fila a
salida\\odds_snapshots_<AAAA>.csv SOLO cuando las cuotas de un partido cambiaron desde la ultima foto.
Solo guarda partidos que aun no empiezan: la ultima foto antes del inicio es la linea de cierre.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python colectores\\recolectar_proximos.py --dias 3
    python colectores\\snapshot_cuotas.py
"""
import csv, datetime as dt, io, json, os, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENTRADA = os.path.join(BASE, "contexto", "proximos_espn.json")
CAMPOS = ["ml_home", "ml_away", "ml_home_open", "ml_away_open", "total", "total_open", "over_odds", "under_odds",
          "spread_home", "spread_home_open", "spread_home_odds", "spread_away_odds"]
CAMBIO = ["ml_home", "ml_away", "total", "over_odds", "under_odds", "spread_home", "spread_home_odds", "spread_away_odds"]
COLS = ["ts_utc", "liga", "game_id", "fecha_utc", "home", "away", "casa"] + CAMPOS


def main(ahora=None):
    if not os.path.exists(ENTRADA):
        print("No existe %s (corre recolectar_proximos.py primero)." % ENTRADA); return 1
    with open(ENTRADA, encoding="utf-8") as fh:
        d = json.load(fh)
    ahora = ahora or dt.datetime.utcnow().replace(microsecond=0)
    ruta = os.path.join(BASE, "salida", "odds_snapshots_%d.csv" % ahora.year)
    ultimo = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                ultimo[(r["liga"], r["game_id"])] = r
    nuevas, vistos, empezados, sin_cuotas = [], 0, 0, 0
    for g in d.get("partidos", []):
        vistos += 1
        q = g.get("cuotas") or {}
        if not any(q.get(k) is not None for k in CAMBIO):
            sin_cuotas += 1; continue
        try:
            ini = dt.datetime.strptime((g.get("fecha_utc") or "")[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            continue
        if ini <= ahora:
            empezados += 1; continue                      # ya empezo: las lineas en vivo no son de cierre
        clave = (g["liga"], str(g["id"]))
        fila = {"ts_utc": ahora.isoformat() + "Z", "liga": g["liga"], "game_id": g["id"], "fecha_utc": g.get("fecha_utc"),
                "home": (g.get("home") or {}).get("nombre"), "away": (g.get("away") or {}).get("nombre"),
                "casa": q.get("casa", "")}
        for k in CAMPOS:
            fila[k] = "" if q.get(k) is None else q.get(k)
        prev = ultimo.get(clave)
        if prev and all(str(prev.get(k, "")) == str(fila[k]) for k in CAMBIO):
            continue                                        # sin cambios: no se guarda
        nuevas.append(fila); ultimo[clave] = {k: str(v) for k, v in fila.items()}
    if nuevas:
        nuevo = not os.path.exists(ruta)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            if nuevo:
                w.writeheader()
            w.writerows(nuevas)
    print("Snapshot %sZ: %d partidos leidos, %d sin cuotas, %d ya empezados, +%d filas nuevas en %s" % (
        ahora.isoformat(), vistos, sin_cuotas, empezados, len(nuevas), ruta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
