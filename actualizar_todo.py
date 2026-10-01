# -*- coding: utf-8 -*-
"""
actualizar_todo.py - deja datos\\ al dia SIN bajar todo otra vez.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python actualizar_todo.py --estado                 (solo muestra que hay en datos\\, no baja nada)
    python actualizar_todo.py                          (DIARIO: solo lo reciente, tarda pocos minutos)
    python actualizar_todo.py --completo               (una vez o para reconstruir: historial largo)
    python actualizar_todo.py --solo hockey,nba        (solo algunos)
    python actualizar_todo.py --solo-jugadores         (solo datos de jugadores, incremental; ver recolectar_jugadores.py)
    python actualizar_todo.py --jugadores              (todo lo de arriba y ademas jugadores)
    python actualizar_todo.py --proximos               (al final baja los partidos por jugar de ESPN)

Modo diario: cada colector pide solo la temporada en curso (beisbol: los ultimos 45 dias; hockey:
ademas se salta los juegos que ya estan en datos\\hockey.csv). Lo nuevo se FUSIONA con lo que ya
tienes (llave gamePk + team): las filas nuevas reemplazan a las viejas del mismo juego y el resto
del historial se conserva. Antes de cada fusion se guarda una copia en datos\\_respaldo\\.
"""
import argparse, csv, datetime as dt, glob, os, shutil, subprocess, sys, time

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.abspath(__file__)))
COL = os.path.join(BASE, "colectores")
PY = sys.executable
HOY = dt.date.today()


def _sin_pretemporada_nhl(fila):
    """gameId de la NHL = AAAA TT NNNN ; TT=01 pretemporada."""
    g = str(fila.get("gamePk") or "")
    return not (len(g) == 10 and g[4:6] == "01")


def _dias_mlb():
    """dias a pedir de MLB en modo diario: desde el ultimo juego guardado menos 3 de solape (minimo 4, maximo 45)."""
    try:
        ult = ""
        with open(os.path.join(BASE, "datos", "beisbol.csv"), encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("league") == "MLB" and (r.get("game_date") or "") > ult:
                    ult = r["game_date"]
        if ult:
            d = (HOY - dt.date.fromisoformat(ult[:10])).days + 3
            return max(4, min(45, d))
    except Exception:
        pass
    return 45


def pasos(completo):
    m = HOY.month
    y_nhl = HOY.year if m >= 9 else HOY.year - 1          # temporada NHL en curso (arranca en octubre)
    y_nba = HOY.year if m >= 10 else HOY.year - 1
    y_nfl = HOY.year if m >= 8 else HOY.year - 1
    y_fut = HOY.year if m >= 7 else HOY.year - 1
    ventana = (HOY - dt.timedelta(days=45)).isoformat()
    if completo:
        bb_inv, bb_mlb, y_bb = "2018-10-01", "2022-04-01", 2022
        # Para ampliar el historial de hockey sin repetir lo ya bajado:
        #   $env:EDGELINE_NHL_DESDE="20182019"; $env:EDGELINE_NHL_HASTA="20222023"
        nhl = ["--desde", os.environ.get("EDGELINE_NHL_DESDE", "20232024"),
               "--hasta", os.environ.get("EDGELINE_NHL_HASTA", "%d%d" % (y_nhl, y_nhl + 1))]
        nba, nfl, fut = "2022", "2021", "2021"
    else:
        bb_inv, y_bb = ventana, HOY.year
        bb_mlb = (HOY - dt.timedelta(days=_dias_mlb())).isoformat()       # solo lo nuevo (antes: siempre 45 dias, ~20 min)
        nhl = ["--desde", "%d%d" % (y_nhl - 1, y_nhl), "--hasta", "%d%d" % (y_nhl, y_nhl + 1),
               "--conocidos", os.path.join(BASE, "datos", "hockey.csv")]
        nba, nfl, fut = str(y_nba), str(y_nfl), str(y_fut)
    return {
        "beisbol": {"cmds": [["recolectar_boxscores.py", "--liga", "invierno", "--desde", bb_inv],
                             ["recolectar_boxscores.py", "--liga", "mlb", "--desde", bb_mlb],
                             ["recolectar_npb.py", "--desde", str(y_bb), "--hasta", str(HOY.year)],
                             ["recolectar_kbo.py", "--desde", str(y_bb), "--hasta", str(HOY.year)]],
                    "copia": ("baseball_boxscores.csv", "beisbol.csv"), "filtro": None},
        "futbol": {"cmds": [["recolectar_futbol.py", "--desde", fut]],
                   "copia": ("futbol_games.csv", "futbol.csv"), "filtro": None},
        # Liga MX y MLS (football-data.co.uk /new/MEX.csv y USA.csv): una peticion por liga, mezcla por upsert.
        "futbol_extra": {"cmds": [["recolectar_futbol_extra.py", "--desde", fut]],
                         "copia": ("futbol_extra.csv", "futbol.csv"), "filtro": None},
        "hockey": {"cmds": [["recolectar_hockey.py"] + nhl],
                   "copia": ("hockey_games.csv", "hockey.csv"), "filtro": _sin_pretemporada_nhl},
        "nba": {"cmds": [["recolectar_nba.py", "--desde", nba, "--hasta", str(y_nba)]],
                "copia": ("nba_games.csv", "nba.csv"), "filtro": None},
        "americano": {"cmds": [["recolectar_americano.py", "--desde", nfl]],
                      "copia": ("americano_games.csv", "americano.csv"), "filtro": None},
        # La fuente de tenis (Sackmann en GitHub) da 404 hoy; el colector no reemplaza nada si no trae filas.
        "tenis": {"cmds": [["recolectar_tenis.py", "--desde", "2024" if not completo else "2020",
                            "--hasta", str(HOY.year)]],
                  "copia": ("tennis_matches.csv", "tenis.csv"), "filtro": None},
        # TennisMyLife: ATP y WTA con saque, al dia (reemplaza a Sackmann, que ya no existe). Va ANTES que ESPN.
        "tenis_tml": {"cmds": [["recolectar_tenis_tml.py"]],
                      "copia": ("tennis_tml.csv", "tenis.csv"), "filtro": None},
        # Resultados recientes de ESPN (sin saque/resto): cierran el hueco que deja Sackmann. Mueven el ELO.
        "tenis_espn": {"cmds": [["recolectar_tenis_espn.py"]],
                       "copia": ("tennis_espn.csv", "tenis.csv"), "filtro": None},
    }


def leer(ruta):
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), list(rd)


def escribir(ruta, cols, filas):
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
        w.writeheader(); w.writerows(filas)


def _llave(r):
    """Un juego = una fila local + una visita. Se usa is_home (no el nombre del equipo) para que un
    cambio de nombre entre descargas reemplace la fila en vez de duplicar el juego."""
    gp = r.get("gamePk")
    if gp not in (None, ""):
        gp = str(gp)
        if gp.endswith(".0"): gp = gp[:-2]
        lado = str(r.get("is_home")).replace(".0", "") if r.get("is_home") not in (None, "") else str(r.get("team"))
        return (gp, lado)
    if r.get("tourney_id"):
        # tenis: TML fecha el partido con el inicio del torneo y ESPN con el dia real; sin la fecha en la llave no se duplica
        return ("tenis", str(r.get("tourney_id")), str(r.get("round")), str(r.get("winner_name")), str(r.get("loser_name")))
    return (str(r.get("tourney_date")), str(r.get("winner_name")), str(r.get("loser_name")), str(r.get("round")))


def publicar(origen, destino, filtro):
    """Fusiona data_maestra\\<origen> dentro de datos\\<destino> (upsert) sin perder historial."""
    src = os.path.join(BASE, "data_maestra", origen)
    dst = os.path.join(BASE, "datos", destino)
    if not os.path.exists(src):
        return "sin archivo nuevo (%s)" % origen
    cn, nuevas = leer(src)
    if not nuevas:
        return "el colector no trajo filas: datos\\%s intacto" % destino
    if os.path.exists(dst):
        co, viejas = leer(dst)
    else:
        co, viejas = [], []
    es_tenis = destino == "tenis.csv"
    idx = {}
    for r in viejas:
        k = _llave(r)
        if es_tenis and k in idx:
            continue                         # tenis: un partido repetido se queda con la primera fila (la de TML, con mas columnas)
        idx[k] = r
    agregadas = reemplazadas = 0
    for r in nuevas:
        k = _llave(r)
        if k in idx:
            if es_tenis:
                continue                     # partido ya registrado: no se pisa con la version de otra fuente
            reemplazadas += 1
        else: agregadas += 1
        idx[k] = r
    filas = list(idx.values())
    extra = ""
    if filtro:
        antes = len(filas); filas = [r for r in filas if filtro(r)]
        if antes != len(filas): extra = " (quite %d de pretemporada)" % (antes - len(filas))
    cols = list(co) + [c for c in cn if c not in co]
    campo = "game_date" if "game_date" in cols else ("tourney_date" if "tourney_date" in cols else None)
    if campo:
        filas.sort(key=lambda r: (r.get(campo) or "", str(r.get("gamePk") or "")))
    if os.path.exists(dst):
        os.makedirs(os.path.join(BASE, "datos", "_respaldo"), exist_ok=True)
        shutil.copy2(dst, os.path.join(BASE, "datos", "_respaldo", destino))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    escribir(dst, cols, filas)
    return "datos\\%s: %d filas (antes %d): +%d nuevas, %d actualizadas%s" % (
        destino, len(filas), len(viejas), agregadas, reemplazadas, extra)


def estado():
    print("Estado de datos\\ en %s\n" % BASE)
    for ruta in sorted(glob.glob(os.path.join(BASE, "datos", "*.csv"))):
        cols, filas = leer(ruta)
        fc = next((c for c in cols if c in ("game_date", "tourney_date", "fecha")), None)
        fs = sorted(r[fc] for r in filas if r.get(fc)) if fc else []
        print("  %-14s %7d filas   %s -> %s" % (os.path.basename(ruta), len(filas),
                                                 fs[0] if fs else "?", fs[-1] if fs else "?"))
    for n in ("beisbol", "futbol", "hockey", "nba", "americano", "tenis"):
        if not os.path.exists(os.path.join(BASE, "datos", n + ".csv")):
            print("  %-14s FALTA" % (n + ".csv"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", help="deportes separados por coma: " + ",".join(pasos(False)))
    ap.add_argument("--completo", action="store_true")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--proximos", action="store_true")
    ap.add_argument("--solo-publicar", action="store_true", dest="solo_publicar",
                    help="no descarga nada: solo mezcla data_maestra\\ en datos\\ (despues de correr un colector a mano)")
    ap.add_argument("--jugadores", action="store_true", help="ademas baja datos de jugadores (incremental)")
    ap.add_argument("--solo-jugadores", action="store_true", dest="solo_jugadores",
                    help="solo datos de jugadores: lanzadores, bateadores, porteros, NFL, NBA, NCAA, futbol")
    a = ap.parse_args()
    if a.estado:
        estado(); return
    env = dict(os.environ, EDGELINE_BASE=BASE, PYTHONIOENCODING="utf-8")
    P = pasos(a.completo)
    elegidos = [x.strip() for x in a.solo.split(",")] if a.solo else list(P)
    if a.solo_jugadores:
        elegidos = []; a.jugadores = True
    print("Modo: %s" % ("COMPLETO (historial largo)" if a.completo else "DIARIO (solo lo reciente)"))
    resumen = []
    for dep in elegidos:
        if dep == "ncaa": continue          # se corre aparte, mas abajo
        if dep not in P:
            resumen.append((dep, "deporte desconocido")); continue
        print("\n=== %s ===" % dep.upper()); t0 = time.time(); ok = True
        for cmd in ([] if a.solo_publicar else P[dep]["cmds"]):
            ruta = os.path.join(COL, cmd[0])
            if not os.path.exists(ruta):
                print("  falta %s" % ruta); ok = False; continue
            r = subprocess.run([PY, ruta] + cmd[1:], env=env)
            if r.returncode != 0:
                print("  (termino con error %d: %s)" % (r.returncode, cmd[0])); ok = False
        origen, destino = P[dep]["copia"]
        msg = publicar(origen, destino, P[dep]["filtro"])
        resumen.append((dep, ("" if ok else "CON AVISOS - ") + msg + "  [%ds]" % (time.time() - t0)))
    if not a.solo_publicar and not a.solo_jugadores and (not a.solo or "ncaa" in elegidos):
        print("\n=== NCAA (futbol americano y basquet, resultados ESPN; solo lo nuevo) ===")
        t0 = time.time()
        r = subprocess.run([PY, os.path.join(COL, "historial_ncaa.py")], env=env)
        resumen.append(("ncaa", ("ok" if r.returncode == 0 else "CON AVISOS (error %d)" % r.returncode) + "  [%ds]" % (time.time() - t0)))
    if a.proximos:
        print("\n=== PROXIMOS (ESPN) ===")
        subprocess.run([PY, os.path.join(COL, "recolectar_proximos.py"), "--dias", "3"], env=env)
    if a.jugadores:
        print("\n=== JUGADORES (incremental) ===")
        rj = os.path.join(COL, "recolectar_jugadores.py"); rm = os.path.join(COL, "recolectar_mercado.py")
        trabajos = [(rj, ["mlb"]), (rj, ["invierno"]), (rj, ["nhl"]), (rj, ["nfl"])] + \
                   [(rj, ["espn", "--liga", l]) for l in ("nba", "ncaamb", "ncaafb", "premier", "laliga", "seriea",
                                                        "bundesliga", "ligue1", "ligamx", "mls", "champions")] + \
                   [(rm, ["todo"])]
        for script, t in trabajos:
            t0 = time.time()
            r = subprocess.run([PY, script] + t, env=env)
            resumen.append(("jug:" + (t[2] if len(t) > 2 else t[0]),
                            ("ok" if r.returncode == 0 else "CON AVISOS (error %d)" % r.returncode) + "  [%ds]" % (time.time() - t0)))
    print("\n================ RESUMEN ================")
    for d, m in resumen:
        print("  %-10s %s" % (d, m))
    print()
    estado()


if __name__ == "__main__":
    main()
