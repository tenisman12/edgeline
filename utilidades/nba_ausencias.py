# -*- coding: utf-8 -*-
"""
utilidades/nba_ausencias.py - ausencias de jugadores importantes por partido de NBA, as-of, desde el box por jugador de ESPN
(datos/jugadores/espn_nba_jugadores.csv o datos/jugadores_recientes/espn_nba_jugadores.csv).

Por equipo y partido: jugadores que en los 5 partidos anteriores del equipo jugaron al menos 3, con 20+ minutos de promedio,
y que en este partido no aparecen o jugaron 0 minutos. Se suman sus minutos y puntos promedio (lo que el equipo pierde).
Solo usa partidos anteriores (as-of): sirve para medir el efecto antes de usarlo.

Escribe datos/equipos/nba_ausencias.csv:
  game_id, game_date, team, opp, is_home, n_ausentes, min_ausentes, pts_ausentes, ausentes

    python utilidades/nba_ausencias.py
"""
import csv, os, sys
from collections import defaultdict, deque

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VENTANA, MIN_JUEGOS, MIN_MINUTOS = 5, 3, 20.0


def _f(x):
    try:
        v = float(str(x).split(":")[0]) if ":" in str(x) else float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def leer():
    filas = {}
    for sub in ("jugadores", "jugadores_recientes"):
        ruta = os.path.join(BASE, "datos", sub, "espn_nba_jugadores.csv")
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("liga") or "nba").lower() != "nba":
                    continue
                filas[(r.get("game_id"), r.get("player_id"))] = r
    return list(filas.values())


def main():
    rows = leer()
    if not rows:
        print("Sin box por jugador de NBA."); return 1
    por_juego = defaultdict(list)
    meta = {}
    for r in rows:
        k = (r["game_id"], r["team"])
        por_juego[k].append(r)
        meta[k] = (r.get("game_date") or "", r.get("opp"), r.get("is_home"))
    juegos_eq = defaultdict(list)
    for (gid, team), (fch, _, _) in meta.items():
        juegos_eq[team].append((fch, gid))
    out = []
    for team, lista in juegos_eq.items():
        lista.sort()
        hist = deque(maxlen=VENTANA)              # por partido anterior: {player: (nombre, min, pts)}
        for fch, gid in lista:
            hoy = {}
            for r in por_juego[(gid, team)]:
                m = _f(r.get("minutes")) or 0.0
                hoy[r["player_id"]] = (r.get("jugador"), m, _f(r.get("points")) or 0.0)
            if len(hist) >= MIN_JUEGOS:
                acum = defaultdict(lambda: [None, 0, 0.0, 0.0])
                for g in hist:
                    for pid, (nom, m, p) in g.items():
                        if m > 0:
                            a = acum[pid]; a[0] = nom; a[1] += 1; a[2] += m; a[3] += p
                aus = []
                for pid, (nom, n, mt, pt) in acum.items():
                    if n >= MIN_JUEGOS and mt / n >= MIN_MINUTOS and (pid not in hoy or hoy[pid][1] <= 0):
                        aus.append((nom, mt / n, pt / n))
                _, opp, is_home = meta[(gid, team)]
                out.append({"game_id": gid, "game_date": fch, "team": team, "opp": opp, "is_home": is_home,
                            "n_ausentes": len(aus), "min_ausentes": round(sum(a[1] for a in aus), 1),
                            "pts_ausentes": round(sum(a[2] for a in aus), 1),
                            "ausentes": "; ".join("%s (%.0f min)" % (a[0], a[1]) for a in sorted(aus, key=lambda a: -a[1]))})
            hist.append(hoy)
    ruta = os.path.join(BASE, "datos", "equipos", "nba_ausencias.csv")
    # mezcla con lo ya calculado: en Actions solo hay box reciente; los partidos viejos se conservan
    if os.path.exists(ruta):
        nuevos = {(r["game_id"], r["team"]) for r in out}
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            out += [r for r in csv.DictReader(f) if (r.get("game_id"), r.get("team")) not in nuevos]
    out.sort(key=lambda r: (r["game_date"], r["game_id"]))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["game_id"]); w.writeheader(); w.writerows(out)
    con = sum(1 for r in out if r["n_ausentes"])
    print("nba_ausencias.csv: %d equipo-partido (%d con alguna ausencia), %s -> %s" % (
        len(out), con, out[0]["game_date"] if out else "?", out[-1]["game_date"] if out else "?"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
