# -*- coding: utf-8 -*-
"""
BAJAR ESPN TODO - baja ESPN de todos tus deportes de un jalon.

Corre recolectar_espn.py (modo 'juegos' = todo por partido) + extraer_espn.py para
cada liga, en secuencia. Un solo comando y tienes ESPN completo.

OJO: el modo 'juegos' pide el summary de CADA partido, asi que bajar todo tarda
bastante (horas si son temporadas completas). Opciones:
    python bajar_espn_todo.py                 -> todas las ligas, rangos por defecto
    python bajar_espn_todo.py --scoreboard    -> rapido: solo marcador + cuotas (sin summary)
    python bajar_espn_todo.py --solo nfl,nhl  -> solo esas ligas
    python bajar_espn_todo.py --dias 30        -> solo los ultimos 30 dias (rapido para probar)

Corre en tu maquina (ESPN esta bloqueada en el entorno de Claude).
"""
import argparse, os, sys, subprocess, datetime as dt

AQUI = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# liga -> (desde, hasta) rango por defecto (temporada reciente aprox)
LIGAS = {
    "nfl":       ("20240905", "20250210"),
    "nba":       ("20241022", "20250420"),
    "nhl":       ("20241004", "20250420"),
    "mlb":       ("20250327", "20251101"),
    "premier":   ("20240816", "20250525"),
    "laliga":    ("20240815", "20250525"),
    "seriea":    ("20240817", "20250525"),
    "bundesliga":("20240823", "20250517"),
    "ligue1":    ("20240816", "20250517"),
    "ligamx":    ("20250110", "20250601"),
    "champions": ("20240917", "20250601"),
    "mls":       ("20250222", "20251109"),
    # americano y basket universitario (ya soportados por el colector)
    "ncaafb":    ("20240824", "20250120"),
    "ncaamb":    ("20241104", "20250407"),
    # tenis: eventos por dia; usa --dias para acotar (el rango completo es enorme)
    "atp":       ("20250101", "20251231"),
    "wta":       ("20250101", "20251231"),
}


def correr(cmd):
    print("\n>>> " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print("   fallo:", str(e)[:80])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", help="ligas separadas por coma (default: todas)")
    ap.add_argument("--scoreboard", action="store_true", help="rapido: solo marcador+cuotas")
    ap.add_argument("--dias", type=int, help="solo los ultimos N dias (para probar rapido)")
    args = ap.parse_args()

    ligas = args.solo.split(",") if args.solo else list(LIGAS)
    modo = "scoreboard" if args.scoreboard else "juegos"

    for liga in ligas:
        liga = liga.strip()
        if liga not in LIGAS:
            print("  (salto %s: no mapeada)" % liga); continue
        d0, d1 = LIGAS[liga]
        if args.dias:
            hoy = dt.date.today()
            d0 = (hoy - dt.timedelta(days=args.dias)).strftime("%Y%m%d"); d1 = hoy.strftime("%Y%m%d")
        print("\n" + "=" * 60); print("LIGA: %s   (%s a %s)" % (liga.upper(), d0, d1)); print("=" * 60)
        correr([PY, os.path.join(AQUI, "recolectar_espn.py"), modo, "--liga", liga, "--desde", d0, "--hasta", d1])
        if modo == "juegos":
            correr([PY, os.path.join(AQUI, "extraer_espn.py"), "--liga", liga])
        # lesiones y standings (rapidos, siempre)
        correr([PY, os.path.join(AQUI, "recolectar_espn.py"), "lesiones", "--liga", liga])

    print("\n" + "=" * 60)
    print("LISTO. Revisa data_maestra/espn_*_*.csv y espn_*_summary.jsonl")
    print("=" * 60)


if __name__ == "__main__":
    main()
