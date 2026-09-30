# -*- coding: utf-8 -*-
"""
ORGANIZAR - acomoda los archivos del refactor en su carpeta correcta.

Busca cada archivo entregado (io.py, features.py, evaluar.py, calibrar.py,
beisbol.py, ...) en las carpetas tipicas (C:\\Edgeline, Descargas, Escritorio,
carpeta actual) y lo MUEVE a donde va:

    nucleo\\   -> io.py, features.py, evaluar.py, calibrar.py
    modelos\\  -> beisbol.py, americano.py, hockey.py, futbol.py

Crea las carpetas y los __init__.py que falten. No borra nada (mueve).
Si un archivo esta en varios lados, usa el mas reciente.

Uso (en C:\\Edgeline):
    python organizar.py
    python organizar.py --ver     (solo muestra donde esta cada archivo, no mueve)
"""
import argparse, os, shutil, glob

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
HOME = os.path.expanduser("~")

DESTINO = {
    "io.py": "nucleo", "features.py": "nucleo", "evaluar.py": "nucleo", "calibrar.py": "nucleo",
    "mercado.py": "nucleo", "indicadores.py": "nucleo",
    "beisbol.py": "modelos", "americano.py": "modelos", "hockey.py": "modelos",
    "futbol.py": "modelos", "tenis.py": "modelos", "nba.py": "modelos",
}

# donde buscar (no recursivo salvo Edgeline)
CARPETAS_PLANAS = [BASE, os.path.join(HOME, "Downloads"), os.path.join(HOME, "Desktop"),
                   os.path.join(HOME, "Descargas"), os.getcwd()]


def candidatos(nombre):
    """Todas las copias de un archivo, incluyendo las que el navegador renombro a
    'evaluar(1).py' o 'evaluar (1).py'. Devuelve mas reciente primero."""
    stem = nombre[:-3]   # sin .py
    patrones = [nombre, stem + "(*).py", stem + " (*).py"]
    vistos, rutas = set(), []
    for c in CARPETAS_PLANAS + [os.path.join(BASE, "**")]:
        rec = c.endswith("**")
        for pat in patrones:
            for p in glob.glob(os.path.join(c, pat), recursive=rec):
                ap = os.path.abspath(p)
                if ap not in vistos and os.path.isfile(p):
                    vistos.add(ap); rutas.append(p)
    rutas.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return rutas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", action="store_true", help="solo muestra, no mueve")
    args = ap.parse_args()

    # crear carpetas destino + __init__.py
    for sub in ("nucleo", "modelos"):
        d = os.path.join(BASE, sub)
        os.makedirs(d, exist_ok=True)
        ini = os.path.join(d, "__init__.py")
        if not os.path.exists(ini) and not args.ver:
            open(ini, "w").close()

    print("Base: %s\n" % BASE)
    for nombre, sub in DESTINO.items():
        destino = os.path.join(BASE, sub, nombre)
        cands = candidatos(nombre)
        cands_fuera = [p for p in cands if os.path.abspath(p) != os.path.abspath(destino)]
        # elegir la copia mas reciente que exista fuera del destino
        origen = cands_fuera[0] if cands_fuera else None
        if origen is None:
            if os.path.exists(destino):
                print("  [ya en %s] %s" % (sub, nombre))
            else:
                print("  [FALTA]     %s  (no lo encontre; descargalo del chat)" % nombre)
            continue
        # si el destino ya existe y es igual o mas nuevo, no lo pises
        if os.path.exists(destino) and os.path.getmtime(destino) >= os.path.getmtime(origen):
            print("  [ya en %s] %s  (el de nucleo es igual o mas nuevo)" % (sub, nombre)); continue
        nuevo = " (reemplaza mas viejo)" if os.path.exists(destino) else ""
        if args.ver:
            print("  [mover]     %s  <-  %s%s" % (os.path.join(sub, nombre), origen, nuevo)); continue
        if os.path.exists(destino):
            os.remove(destino)
        shutil.move(origen, destino)
        print("  [movido]    %s  <-  %s%s" % (os.path.join(sub, nombre), origen, nuevo))

    if not args.ver:
        print("\nListo. Prueba:")
        print('  python -c "import sys; sys.path.insert(0,\'.\'); from nucleo import io; io.diagnostico()"')


if __name__ == "__main__":
    main()
