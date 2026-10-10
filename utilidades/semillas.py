# -*- coding: utf-8 -*-
"""
utilidades/semillas.py - lleva a GitHub lo que solo se puede bajar en tu PC, sin publicar tu carpeta datos.

Tu PC baja historia (KBO 2021-2025, xG por partido de MoneyPuck...) y la "exporta" a semillas/ (dentro de main).
Actions, en cada actualizacion, "mezcla" semillas/ con datos/: solo AGREGA filas que no existen (nunca pisa).

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\semillas.py exportar kbo      (data_maestra\\baseball_boxscores.csv y datos\\beisbol.csv -> semillas\\kbo_historial.csv)
    python utilidades\\semillas.py exportar kbo_box  (data_maestra\\kbo_box.csv y kbo_lanzadores -> semillas\\)
    python utilidades\\semillas.py exportar xg       (datos\\equipos\\nhl_xg_partidos.csv -> semillas\\nhl_xg_partidos.csv)
    python utilidades\\semillas.py exportar hockey_ligas  (data_maestra\\hockey_ligas.csv -> semillas\\hockey_ligas.csv: SHL, Liiga, AHL, DEL)
    python utilidades\\semillas.py mezclar           (semillas\\ -> datos\\ ; lo corre actualizar_todo.py solo)
    python utilidades\\semillas.py estado
"""
import csv, os, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEM = os.path.join(BASE, "semillas")
csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))

# semilla -> (destino en datos, llave). LLENAR: semillas que no agregan filas sino que llenan celdas vacias de filas existentes
LLENAR = {"kbo_box.csv"}
DESTINOS = {
    "kbo_historial.csv": (os.path.join("datos", "beisbol.csv"), lambda r: (str(r.get("gamePk")).replace(".0", ""), str(r.get("is_home")).replace(".0", ""))),
    "kbo_box.csv": (os.path.join("datos", "beisbol.csv"), lambda r: (str(r.get("gamePk")).replace(".0", ""), str(r.get("is_home")).replace(".0", ""))),
    "kbo_lanzadores.csv": (os.path.join("datos", "jugadores", "kbo_lanzadores.csv"), lambda r: (str(r.get("game_id")), r.get("team"), r.get("jugador"))),
    "nhl_xg_partidos.csv": (os.path.join("datos", "equipos", "nhl_xg_partidos.csv"), lambda r: (str(r.get("game_id")), r.get("team"), r.get("situation"))),
    # LMP (workflow "lmp"): temporadas rellenadas desde la MLB Stats API y lanzadores por juego para la capa de abridores
    "lmp_historial.csv": (os.path.join("datos", "beisbol.csv"), lambda r: (str(r.get("gamePk")).replace(".0", ""), str(r.get("is_home")).replace(".0", ""))),
    "lmp_lanzadores.csv": (os.path.join("datos", "abridores", "lmp_lanzadores.csv"), lambda r: (str(r.get("game_id")), r.get("team"), r.get("jugador"))),
    # SHL, Liiga, AHL y DEL (colectores/recolectar_hockey_ligas.py): historia de 2024-25 en adelante bajada en la PC
    "hockey_ligas.csv": (os.path.join("datos", "hockey.csv"), lambda r: (str(r.get("gamePk")).replace(".0", ""), str(r.get("is_home")).replace(".0", ""))),
    # NPB: lanzadores por juego 2022-2026 del Nippon Baseball Data Repository (capa de abridores medida el 6-oct)
    "npb_lanzadores.csv": (os.path.join("datos", "abridores", "npb_lanzadores.csv"), lambda r: (str(r.get("game_id")), r.get("team"), r.get("player_id"))),
}


def leer(ruta):
    if not os.path.exists(ruta):
        return [], []
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd.fieldnames or []), list(rd)


def escribir(ruta, cols, filas):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval=""); w.writeheader(); w.writerows(filas)


def exportar(que):
    if que == "kbo":
        filas, cols = [], []
        vistos = set()
        for ruta in (os.path.join(BASE, "data_maestra", "baseball_boxscores.csv"), os.path.join(BASE, "datos", "beisbol.csv")):
            c, rs = leer(ruta)
            for r in rs:
                if (r.get("league") or "").upper() != "KBO":
                    continue
                k = DESTINOS["kbo_historial.csv"][1](r)
                if k in vistos:
                    continue
                vistos.add(k); filas.append(r)
                cols += [x for x in c if x not in cols]
        filas.sort(key=lambda r: (r.get("game_date") or "", str(r.get("gamePk"))))
        ruta = os.path.join(SEM, "kbo_historial.csv"); escribir(ruta, cols, filas)
        temps = sorted({(r.get("game_date") or "")[:4] for r in filas})
        print("KBO: %d filas (%d juegos), temporadas %s -> %s" % (len(filas), len(filas) // 2, ", ".join(temps), ruta))
    elif que == "kbo_box":
        for nombre, origen in (("kbo_box.csv", os.path.join(BASE, "data_maestra", "kbo_box.csv")),
                               ("kbo_lanzadores.csv", os.path.join(BASE, "datos", "jugadores", "kbo_lanzadores.csv"))):
            c, rs = leer(origen)
            if not rs:
                print("No existe %s: corre antes colectores\\recolectar_kbo_box.py" % origen); return 1
            escribir(os.path.join(SEM, nombre), c, rs)
            print("%s: %d filas" % (nombre, len(rs)))
    elif que == "xg":
        c, rs = leer(os.path.join(BASE, "datos", "equipos", "nhl_xg_partidos.csv"))
        if not rs:
            print("No existe datos\\equipos\\nhl_xg_partidos.csv: corre antes colectores\\recolectar_xg_partidos.py"); return 1
        ruta = os.path.join(SEM, "nhl_xg_partidos.csv"); escribir(ruta, c, rs)
        print("xG NHL: %d filas, %s -> %s, en %s" % (len(rs), min(r["game_date"] for r in rs), max(r["game_date"] for r in rs), ruta))
    elif que == "hockey_ligas":
        sys.path.insert(0, os.path.join(BASE, "colectores"))
        import recolectar_hockey_ligas as RH
        c, rs = leer(os.path.join(BASE, "data_maestra", "hockey_ligas.csv"))
        if not rs:
            print("No existe data_maestra\\hockey_ligas.csv: corre antes colectores\\recolectar_hockey_ligas.py"); return 1
        filas = [RH.a_archivo(RH.a_interno(r)) for r in rs]
        cortos = sorted({r["team"] for r in filas if r.get("league") == "AHL" and len(r.get("team") or "") <= 4})
        if cortos:
            print("La AHL todavia tiene codigos en vez de nombres (%s): corre colectores\\recolectar_hockey_ligas.py --ligas AHL" % ", ".join(cortos[:8]))
            return 1
        ruta = os.path.join(SEM, "hockey_ligas.csv"); escribir(ruta, RH.COLS_ARCHIVO, filas)
        import collections
        cnt = collections.Counter((r["league"], r["season"]) for r in filas if str(r.get("is_home")) in ("1", "1.0"))
        print("hockey_ligas: %d filas -> %s" % (len(filas), ruta))
        for k, v in sorted(cnt.items()):
            print("  %-6s %s %5d juegos" % (k[0], k[1], v))
    else:
        print("exportar kbo | exportar kbo_box | exportar xg | exportar hockey_ligas"); return 1
    print("Sube con: git add semillas && git commit -m \"semillas %s\" && git push origin main" % que)
    return 0


def mezclar():
    if not os.path.isdir(SEM):
        print("Sin semillas."); return 0
    for nombre, (dest, llave) in DESTINOS.items():
        cs, sem = leer(os.path.join(SEM, nombre))
        if not sem:
            continue
        ruta = os.path.join(BASE, dest)
        cd, dat = leer(ruta)
        if nombre in LLENAR:
            idx = {llave(r): r for r in dat}
            celdas = 0
            for r in sem:
                d = idx.get(llave(r))
                if not d:
                    continue
                for c, v in r.items():
                    if (c.startswith("bat_") or c.startswith("pit_")) and v not in (None, "") and (d.get(c) in (None, "")):
                        d[c] = v; celdas += 1
            if celdas:
                cols = cd + [c for c in cs if (c.startswith("bat_") or c.startswith("pit_")) and c not in cd]
                escribir(ruta, cols, dat)
            print("  %-22s %d celdas llenadas -> %s" % (nombre, celdas, dest)); continue
        ya = {llave(r) for r in dat}
        nuevas = [r for r in sem if llave(r) not in ya]
        if not nuevas:
            print("  %-22s sin filas nuevas (%d ya estan)" % (nombre, len(sem))); continue
        cols = cd + [c for c in cs if c not in cd]
        dat += nuevas
        campo = "game_date" if "game_date" in cols else None
        if campo:
            dat.sort(key=lambda r: ((r.get(campo) or "")[:10], str(r.get("gamePk") or r.get("game_id") or "")))
        escribir(ruta, cols, dat)
        print("  %-22s +%d filas -> %s" % (nombre, len(nuevas), dest))
    return 0


def estado():
    for nombre in sorted(os.listdir(SEM)) if os.path.isdir(SEM) else []:
        _, rs = leer(os.path.join(SEM, nombre))
        fs = sorted((r.get("game_date") or "")[:10] for r in rs if r.get("game_date"))
        print("  %-24s %7d filas  %s -> %s" % (nombre, len(rs), fs[0] if fs else "?", fs[-1] if fs else "?"))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:] or ["estado"]
    sys.exit(exportar(a[1] if len(a) > 1 else "") if a[0] == "exportar" else mezclar() if a[0] == "mezclar" else estado())
