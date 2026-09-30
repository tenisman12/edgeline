# -*- coding: utf-8 -*-
"""
EXPLORAR ESPN - dime que informacion hay disponible para un deporte.

Lee data_maestra/espn_<liga>_summary.jsonl y reporta, para ESE deporte, que trae ESPN:
que secciones vienen con datos, las categorias y stats del box score, si hay win
probability / cuotas / lesiones, etc. Asi sabes que se puede integrar por deporte.

Uso (en C:\\Edgeline):
    python explorar_espn.py               (TODOS los deportes que tengas bajados)
    python explorar_espn.py --liga nba    (solo uno)
"""
import argparse, io, os, json, glob

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")

SECCIONES = {
    "boxscore": "box score (equipo + jugadores)",
    "winprobability": "win probability de ESPN (benchmark)",
    "odds": "cuotas (solo proximos, no historico)",
    "pickcenter": "picks/consenso ESPN",
    "againstTheSpread": "records ATS",
    "injuries": "lesiones (status)",
    "leaders": "lideres del juego",
    "plays": "play-by-play",
    "gameInfo": "estadio / asistencia / arbitros",
    "standings": "posiciones",
    "seasonseries": "serie de temporada (H2H)",
    "predictor": "predictor de ESPN",
}


def explorar(liga):
    JL = os.path.join(BASE, "data_maestra", "espn_%s_summary.jsonl" % liga)
    if not os.path.exists(JL):
        print("No existe %s. Corre: python recolectar_espn.py juegos --liga %s ..." % (JL, liga)); return

    # agrega sobre todos los juegos: cuantos tienen cada seccion con datos
    n = 0; con = {k: 0 for k in SECCIONES}
    cats = {}   # categoria de box score -> set de labels
    for line in io.open(JL, encoding="utf-8"):
        try:
            sm = json.loads(line)["summary"]
        except Exception:
            continue
        n += 1
        for k in SECCIONES:
            v = sm.get(k)
            if v:
                con[k] += 1
        for tb in (sm.get("boxscore") or {}).get("players") or []:
            for st in tb.get("statistics") or []:
                cat = st.get("name") or "general"
                cats.setdefault(cat, set()).update(st.get("labels") or [])

    print("=" * 70)
    print("  DISPONIBLE EN %s   (revisados %d juegos)" % (liga.upper(), n))
    print("=" * 70)
    print("\nSECCIONES (en cuantos juegos viene con datos):")
    for k, desc in SECCIONES.items():
        c = con[k]
        marca = "OK " if c else "-- "
        print("  [%s] %-16s %3d/%d  %s" % (marca, k, c, n, desc))

    print("\nBOX SCORE POR JUGADOR - categorias y stats disponibles:")
    if not cats:
        print("  (sin box score de jugadores en este deporte)")
    for cat in sorted(cats):
        labs = sorted(cats[cat])
        print("  %-14s -> %s" % (cat, ", ".join(labs)))

    print("\nLECTURA:")
    print("  Lo marcado OK se puede integrar. El box score por categoria alimenta")
    print("  paneles de jugador y props. winprobability = benchmark. injuries = status.")


def descubrir():
    """todas las ligas con summary.jsonl en data_maestra."""
    patron = os.path.join(BASE, "data_maestra", "espn_*_summary.jsonl")
    ligas = []
    for p in sorted(glob.glob(patron)):
        nombre = os.path.basename(p)
        ligas.append(nombre[len("espn_"):-len("_summary.jsonl")])
    return ligas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", help="una liga; sin esto, revisa TODAS las bajadas")
    liga = ap.parse_args().liga
    if liga:
        explorar(liga); return
    ligas = descubrir()
    if not ligas:
        print("No hay espn_*_summary.jsonl en data_maestra. Corre bajar_espn_todo.py primero."); return
    print("Deportes con data bajada: %s\n" % ", ".join(ligas))
    for lg in ligas:
        explorar(lg)
        print("")


if __name__ == "__main__":
    main()
