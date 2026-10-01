# -*- coding: utf-8 -*-
"""
utilidades/jugadores_recientes.py - JUGADORES RECIENTES PARA GITHUB (pequenos, se actualizan solos).

El historial completo de jugadores (datos/jugadores/, cientos de MB) se queda en tu PC. A GitHub sube
solo una version compacta de los ultimos dias (datos/jugadores_recientes/) con las columnas que usa la
pagina (forma de abridores, bullpen, porteros, QB, jugadores clave). Con ella Actions puede seguir
actualizando los jugadores dia con dia sin bajar historia.

Comandos (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\jugadores_recientes.py recortar [--dias 60]
        datos\\jugadores\\*.csv  ->  datos\\jugadores_recientes\\*.csv   (ultimos N dias de cada archivo,
        columnas compactas en beisbol/hockey/NFL; todas las columnas en los demas)
    python utilidades\\jugadores_recientes.py sembrar
        copia datos\\jugadores_recientes\\ a datos\\jugadores\\ SOLO donde falte el archivo (lo usa Actions)
    python utilidades\\jugadores_recientes.py diario [--dias-max 30]
        baja solo lo nuevo de cada fuente (desde el ultimo dia guardado menos 3, con tope de N dias hacia
        atras) y vuelve a recortar. Cada fuente es independiente: si una falla, las demas siguen.
    python utilidades\\jugadores_recientes.py estado

Solo stdlib.
"""
import argparse, csv, datetime as dt, os, shutil, subprocess, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(BASE, "datos", "jugadores")
REC = os.path.join(BASE, "datos", "jugadores_recientes")
COLECTOR = os.path.join(BASE, "colectores", "recolectar_jugadores.py")

FIJAS_BB = ["game_id", "game_date", "liga", "season", "team", "opp", "is_home", "player_id", "jugador", "posicion"]
FIJAS_ESPN = ["game_id", "game_date", "liga", "season", "tipo", "team", "opp", "is_home", "player_id", "jugador",
              "posicion", "titular"]
FIJAS_NHL = ["game_id", "game_date", "season", "tipo", "team", "opp", "is_home", "player_id", "jugador", "posicion"]
NFL_FIJAS = ["game_id", "game_date", "season", "week", "season_type", "team", "opp", "player_id", "jugador", "posicion"]
NFL_STATS = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "interceptions",
             "sacks_suffered", "sacks", "carries", "rushing_yards", "rushing_tds", "receptions", "targets",
             "receiving_yards", "receiving_tds", "fantasy_points", "fantasy_points_ppr"]
# columnas que se conservan; los archivos que no aparecen aqui se guardan completos
CORE = {
    "mlb_lanzadores.csv": FIJAS_BB + ["abridor", "orden_salida", "ip", "outs", "h", "r", "er", "bb", "k", "hr", "bf",
                                      "pitches", "strikes", "balls", "hbp", "ganado", "perdido", "salvado", "hold",
                                      "blown_save", "inherited", "inherited_scored"],
    "mlb_bateadores.csv": FIJAS_BB + ["orden_bate", "titular", "pa", "ab", "r", "h", "d2", "d3", "hr", "rbi", "bb", "k",
                                      "sb", "cs", "hbp", "sf", "lob", "tb"],
    "nhl_patinadores.csv": FIJAS_NHL + ["toi_min", "goles", "asist", "puntos", "mas_menos", "pim", "hits", "pp_goles",
                                        "tiros", "bloqueos", "shifts", "giveaways", "takeaways", "faceoff_pct"],
    "nfl_jugadores.csv": NFL_FIJAS + NFL_STATS,
}
ESPN_LIGAS = ["nba", "ncaamb", "ncaafb", "premier", "laliga", "seriea", "bundesliga", "ligue1", "ligamx", "mls",
              "champions"]


def _leer(ruta):
    if not os.path.exists(ruta):
        return [], []
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rd = csv.DictReader(fh)
        return rd.fieldnames or [], list(rd)


def _escribir(ruta, cols, filas):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def ultima_fecha(ruta):
    _, filas = _leer(ruta)
    fs = sorted((r.get("game_date") or "")[:10] for r in filas if r.get("game_date"))
    return fs[-1] if fs else None


def recortar(dias=60):
    if not os.path.isdir(DIR):
        print("No existe %s: nada que recortar." % DIR); return 1
    total = 0
    for n in sorted(os.listdir(DIR)):
        if not n.endswith(".csv"):
            continue
        cols0, filas = _leer(os.path.join(DIR, n))
        if not filas:
            continue
        fmax = max((r.get("game_date") or "")[:10] for r in filas)
        if not fmax:
            continue
        lim = (dt.date.fromisoformat(fmax) - dt.timedelta(days=dias)).isoformat()
        rec = [r for r in filas if (r.get("game_date") or "")[:10] >= lim]
        cols = [c for c in CORE[n] if c in cols0] if n in CORE else cols0
        _escribir(os.path.join(REC, n), cols, rec)
        kb = os.path.getsize(os.path.join(REC, n)) / 1024
        total += kb
        print("  %-34s %7d filas (de %d) %6.0f KB  %s -> %s" % (n, len(rec), len(filas), kb, lim, fmax))
    print("Listo: %.1f MB en %s" % (total / 1024, REC))
    return 0


def sembrar():
    if not os.path.isdir(REC):
        print("No hay %s: Actions arrancara sin jugadores previos." % REC); return 0
    os.makedirs(DIR, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(REC)):
        if f.endswith(".csv") and not os.path.exists(os.path.join(DIR, f)):
            shutil.copy2(os.path.join(REC, f), os.path.join(DIR, f)); n += 1
    print("Sembrados %d archivos de jugadores en %s" % (n, DIR))
    return 0


def _desde(ruta, dias_max, hoy):
    u = ultima_fecha(ruta)
    piso = hoy - dt.timedelta(days=dias_max if u else 10)
    if not u:
        return piso
    return max(dt.date.fromisoformat(u) - dt.timedelta(days=3), piso)


def _correr(args):
    cmd = [sys.executable, COLECTOR] + args
    print("\n>>> " + " ".join(args))
    try:
        r = subprocess.run(cmd, timeout=3 * 3600)
        if r.returncode != 0:
            print("    (termino con codigo %d; se sigue con las demas fuentes)" % r.returncode)
    except Exception as ex:
        print("    (fallo: %s; se sigue con las demas fuentes)" % ex)


def diario(dias_max=30):
    hoy = dt.date.today()
    d = _desde(os.path.join(DIR, "mlb_lanzadores.csv"), dias_max, hoy)
    _correr(["todas", "--desde", d.isoformat(), "--sin-raw"])
    d = _desde(os.path.join(DIR, "nhl_porteros.csv"), dias_max, hoy)
    _correr(["nhl", "--desde", d.isoformat(), "--sin-raw"])
    _correr(["nfl", "--sin-raw"])
    for lg in ESPN_LIGAS:
        d = _desde(os.path.join(DIR, "espn_%s_jugadores.csv" % lg), dias_max, hoy)
        _correr(["espn", "--liga", lg, "--desde", d.strftime("%Y%m%d"), "--sin-raw"])
    print("\nRecortando jugadores recientes ...")
    return recortar(60)


def estado():
    for carpeta, titulo in ((DIR, "COMPLETO (tu PC)"), (REC, "RECIENTES (GitHub)")):
        print("\n%s  %s" % (titulo, carpeta))
        if not os.path.isdir(carpeta):
            print("  (no existe)"); continue
        for n in sorted(os.listdir(carpeta)):
            if n.endswith(".csv"):
                p = os.path.join(carpeta, n)
                _, filas = _leer(p)
                print("  %-34s %8d filas %7.0f KB  ultimo %s" % (n, len(filas), os.path.getsize(p) / 1024, ultima_fecha(p)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("que", choices=["recortar", "sembrar", "diario", "estado"])
    ap.add_argument("--dias", type=int, default=60)
    ap.add_argument("--dias-max", type=int, default=30, dest="dias_max")
    a = ap.parse_args()
    if a.que == "recortar":
        return recortar(a.dias)
    if a.que == "sembrar":
        return sembrar()
    if a.que == "diario":
        return diario(a.dias_max)
    return estado()


if __name__ == "__main__":
    sys.exit(main())
