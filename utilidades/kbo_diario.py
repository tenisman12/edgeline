# -*- coding: utf-8 -*-
"""
utilidades/kbo_diario.py - KBO DESDE TU PC (el runner de GitHub no alcanza koreabaseball.com).

Baja los resultados nuevos de KBO y los abridores por juego en tu PC, y los mete en la rama "datos" de GitHub
SIN pisar lo que el bot ya tiene ahi (toma la version actual de la rama, le agrega solo KBO y la sube).
En la siguiente corrida el bot ya los ve: forma, osciladores, H2H, probable y lecturas de KBO quedan al dia.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\kbo_diario.py            # baja lo nuevo y lo sube a la rama datos
    python utilidades\\kbo_diario.py --sin-subir # solo baja (deja todo en tu PC)

Pasos:
  1. colectores\\recolectar_kbo.py            -> data_maestra\\baseball_boxscores.csv (solo lo nuevo)
  2. colectores\\recolectar_jugadores.py kbo  -> datos\\jugadores\\mlb_lanzadores.csv (abridores, solo lo nuevo)
  3. git fetch origin datos  +  worktree temporal _pub_datos
  4. upsert de las filas KBO en _pub_datos\\datos\\beisbol.csv y en _pub_datos\\datos\\jugadores_recientes\\mlb_lanzadores.csv
  5. commit + push a la rama datos; se borra el worktree
Solo stdlib.
"""
import argparse, csv, datetime as dt, os, shutil, subprocess, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUB = os.path.join(BASE, "_pub_datos")
csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))


def _run(args, cwd=BASE, check=True):
    print(">>> " + " ".join(args))
    r = subprocess.run(args, cwd=cwd)
    if check and r.returncode != 0:
        raise SystemExit("fallo: %s (codigo %d)" % (" ".join(args), r.returncode))
    return r.returncode


def _leer(ruta):
    if not os.path.exists(ruta):
        return [], []
    filas = []
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rd = csv.DictReader(fh)
        cols = rd.fieldnames or []
        while True:
            try:
                r = next(rd)
            except StopIteration:
                break
            except csv.Error:
                continue
            if r.get(None) is None:
                filas.append(r)
    return cols, filas


def _escribir(ruta, cols, filas):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", restval="")
        w.writeheader(); w.writerows(filas)


def _upsert(destino, nuevas, llave, cols_nuevas):
    co, viejas = _leer(destino)
    idx = {llave(r): r for r in viejas}
    agregadas = reemplazadas = 0
    for r in nuevas:
        k = llave(r)
        if k in idx:
            reemplazadas += 1
        else:
            agregadas += 1
        idx[k] = r
    cols = list(co) + [c for c in cols_nuevas if c not in co]
    filas = list(idx.values())
    filas.sort(key=lambda r: (r.get("game_date") or "", str(r.get("gamePk") or r.get("game_id") or "")))
    _escribir(destino, cols, filas)
    return "%s: %d filas (antes %d): +%d nuevas, %d actualizadas" % (os.path.relpath(destino, PUB), len(filas), len(viejas), agregadas, reemplazadas)


def _llave_juego(r):
    gp = str(r.get("gamePk") or "")
    if gp.endswith(".0"):
        gp = gp[:-2]
    lado = str(r.get("is_home")).replace(".0", "") if r.get("is_home") not in (None, "") else str(r.get("team"))
    return (gp, lado)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-subir", dest="subir", action="store_false")
    ap.add_argument("--dias", type=int, default=60, help="abridores: ventana que viaja a GitHub (jugadores_recientes)")
    a = ap.parse_args()
    hoy = dt.date.today()
    py = sys.executable
    print("1/5 Resultados KBO (solo lo nuevo)")
    _run([py, os.path.join(BASE, "colectores", "recolectar_kbo.py"), "--desde", str(hoy.year), "--hasta", str(hoy.year)], check=False)
    print("2/5 Abridores KBO (solo lo nuevo)")
    _run([py, os.path.join(BASE, "colectores", "recolectar_jugadores.py"), "kbo", "--sin-raw"], check=False)

    _, box = _leer(os.path.join(BASE, "data_maestra", "baseball_boxscores.csv"))
    kbo = [r for r in box if (r.get("league") or "").upper() == "KBO"]
    cl, lan = _leer(os.path.join(BASE, "datos", "jugadores", "mlb_lanzadores.csv"))
    lim = (hoy - dt.timedelta(days=a.dias)).isoformat()
    abridores = [r for r in lan if r.get("liga") == "KBO" and (r.get("game_date") or "") >= lim]
    print("   KBO en tu PC: %d filas de juego (ultima %s), %d abridor-juego en %d dias" % (
        len(kbo), max((r.get("game_date") or "" for r in kbo), default="-"), len(abridores), a.dias))
    if not kbo:
        print("Sin filas KBO: nada que subir."); return 1
    if not a.subir:
        print("Listo (sin subir)."); return 0

    print("3/5 Tomando la rama datos actual")
    _run(["git", "fetch", "origin", "datos"])
    if os.path.isdir(PUB):
        _run(["git", "worktree", "remove", "--force", PUB], check=False)
        shutil.rmtree(PUB, ignore_errors=True)
    _run(["git", "worktree", "add", "--detach", PUB, "origin/datos"])

    print("4/5 Mezclando KBO en la copia de la rama")
    cb = ["gamePk", "league", "season", "game_date", "team", "opp", "is_home", "runs", "runs_opp"]
    cb += [c for c in (kbo[0].keys() if kbo else []) if c not in cb]
    print("   " + _upsert(os.path.join(PUB, "datos", "beisbol.csv"), kbo, _llave_juego, cb))
    if abridores:
        from utilidades import jugadores_recientes as JR
        cols = [c for c in JR.CORE["mlb_lanzadores.csv"] if c in cl]
        print("   " + _upsert(os.path.join(PUB, "datos", "jugadores_recientes", "mlb_lanzadores.csv"), abridores,
                              lambda r: "%s|%s" % (r.get("game_id"), r.get("player_id")), cols))

    print("5/5 Subiendo a la rama datos")
    _run(["git", "-C", PUB, "add", "-A"])
    if subprocess.run(["git", "-C", PUB, "diff", "--cached", "--quiet"]).returncode == 0:
        print("   Sin cambios respecto a la rama: nada que subir.")
    else:
        _run(["git", "-C", PUB, "commit", "-q", "-m", "KBO desde PC %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M")])
        rc = _run(["git", "-C", PUB, "push", "origin", "HEAD:datos"], check=False)
        if rc != 0:
            print("   El push fue rechazado (el bot publico en medio). Vuelve a correr: python utilidades\\kbo_diario.py")
    _run(["git", "worktree", "remove", "--force", PUB], check=False)
    shutil.rmtree(PUB, ignore_errors=True)
    print("Listo.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, BASE)
    sys.exit(main())
