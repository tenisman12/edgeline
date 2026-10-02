# -*- coding: utf-8 -*-
"""
utilidades/volcar_partidos.py - vuelca TODOS los bloques de cada partido de salida/proximos.json a texto legible,
un archivo por liga, para que Claude (o una persona) lea la ficha completa sin perder nada.

No filtra campos ni resume: cada clave del partido se imprime completa. Solo cambia el formato (JSON indentado).

Uso:
    python utilidades/volcar_partidos.py                      # hoy (CDMX), todas las ligas
    python utilidades/volcar_partidos.py --fecha 2026-10-03 --dias 2 --ligas nhl,mlb
    python utilidades/volcar_partidos.py --indice             # solo el indice (que hay y en que liga)

Salida: trabajo/volcado/<fecha>_<liga>.txt  (carpeta fuera de git) y un indice en pantalla.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, collections, datetime as dt, io, json, os

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TZ = -6
ORDEN = ["liga", "id", "fecha", "hora", "estado", "nota", "serie", "estadio", "torneo", "ronda", "superficie", "best_of",
         "home", "away", "contexto", "modelo", "validacion", "alerta", "cuotas", "mercados", "valor", "movimiento",
         "consenso", "forma", "h2h_datos", "estadisticas_equipo", "jugadores_clave", "pick", "ganador", "picks",
         "pick_top", "bloques"]


def _edad_horas(iso):
    try:
        t = dt.datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="AAAA-MM-DD (por defecto hoy en CDMX)")
    ap.add_argument("--dias", type=int, default=1)
    ap.add_argument("--ligas", help="coma: nhl,mlb,atp,...")
    ap.add_argument("--indice", action="store_true", help="solo imprimir el indice")
    ap.add_argument("--salida", default=os.path.join(BASE, "trabajo", "volcado"))
    a = ap.parse_args()

    with io.open(os.path.join(BASE, "salida", "proximos.json"), encoding="utf-8") as f:
        D = json.load(f)
    hoy = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()
    ini = dt.date.fromisoformat(a.fecha) if a.fecha else hoy
    fin = ini + dt.timedelta(days=a.dias - 1)
    ligas = {x.strip() for x in a.ligas.split(",")} if a.ligas else None
    sel = [p for p in D["partidos"] if ini.isoformat() <= p.get("fecha", "") <= fin.isoformat()
           and (ligas is None or p.get("liga") in ligas)]

    edad = _edad_horas(D.get("generado", ""))
    print("proximos.json generado %s UTC (%s) | ficha %s | umbral_edge %s" % (
        D.get("generado"), ("hace %.1f h" % edad) if edad is not None else "edad desconocida",
        D.get("ficha"), D.get("umbral_edge")))
    if edad is not None and edad > 12:
        print("AVISO: proximos.json tiene mas de 12 horas.")
    if D.get("avisos"):
        print("Avisos del pipeline:", json.dumps(D["avisos"], ensure_ascii=False))
    sm = D.get("sin_modelo") or []
    print("Partidos sin modelo (todo el archivo, sin fecha): %d" % len(sm))
    for x in sm:
        if ligas is None or any(str(x).lower().startswith(l.lower() + ":") for l in ligas):
            print("  sin modelo:", x)

    grupos = collections.OrderedDict()
    for p in sorted(sel, key=lambda p: (p.get("fecha", ""), p.get("liga", ""), p.get("hora") or "")):
        grupos.setdefault((p["fecha"], p["liga"]), []).append(p)
    print("\nINDICE %s a %s: %d partidos" % (ini, fin, len(sel)))
    for (fe, lg), ps in grupos.items():
        con_cuota = sum(1 for p in ps if (p.get("cuotas") or {}).get("ml_home") is not None)
        print("  %s %-7s %3d partidos | %3d con cuota ML" % (fe, lg, len(ps), con_cuota))
    if a.indice or not sel:
        return

    os.makedirs(a.salida, exist_ok=True)
    for (fe, lg), ps in grupos.items():
        ruta = os.path.join(a.salida, "%s_%s.txt" % (fe, lg))
        with io.open(ruta, "w", encoding="utf-8") as f:
            for p in ps:
                h, w = (p.get("home") or {}).get("nombre"), (p.get("away") or {}).get("nombre")
                f.write("=" * 100 + "\n%s | %s %s | %s @ %s | id %s\n" % (lg.upper(), fe, p.get("hora"), w, h, p.get("id")))
                f.write("=" * 100 + "\n")
                claves = [k for k in ORDEN if k in p] + [k for k in p if k not in ORDEN]
                for k in claves:
                    f.write("\n## %s\n%s\n" % (k, json.dumps(p[k], ensure_ascii=False, indent=1)))
                f.write("\n")
        print("  -> %s (%d KB)" % (os.path.relpath(ruta, BASE), os.path.getsize(ruta) // 1024))


if __name__ == "__main__":
    main()
