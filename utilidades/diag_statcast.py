# -*- coding: utf-8 -*-
"""
DIAGNOSTICO del modelo MLB con abridor (statcast) que YA tienes.

Lee tus predicciones existentes y mide la accuracy y el Brier de CADA columna de
probabilidad (p_home, p_elo, p_starter_v3, p_statcast, p_combo, etc.) contra el
resultado real. Asi vemos si el modelo con pitcher YA llega a ~57% en ganador,
antes de reconstruir nada.

Busca estos archivos en C:\\Edgeline (ajusta si tienen otro nombre):
    mlb_statcast_model_v1_predictions.csv
    mlb_statcast_model_v1_results.csv   (opcional, para el resultado real)

Uso:
    python diag_statcast.py
    python diag_statcast.py archivo_predicciones.csv
No modifica nada.
"""
import csv, io, os, sys, glob

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")


def leer(path):
    with io.open(path, encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def buscar(nombre_parcial):
    for p in glob.glob(os.path.join(BASE, "*.csv")):
        if nombre_parcial in os.path.basename(p).lower():
            return p
    return None


def resultado_real(r):
    """Intenta deducir si gano el local (1/0) de las columnas disponibles."""
    for k in ("y_home", "home_win", "result", "gano_local", "y"):
        v = r.get(k)
        if v not in (None, ""):
            try:
                return int(float(v))
            except ValueError:
                pass
    hs, as_ = num(r.get("home_score") or r.get("runs_home") or r.get("home_runs")), \
              num(r.get("away_score") or r.get("runs_away") or r.get("away_runs"))
    if hs is not None and as_ is not None:
        return 1 if hs > as_ else 0
    return None


def main():
    pred_path = sys.argv[1] if len(sys.argv) > 1 else (
        buscar("statcast_model") or buscar("statcast") or buscar("predictions"))
    if not pred_path or not os.path.exists(pred_path):
        print("No encontre el archivo de predicciones. Pasalo como argumento:")
        print("  python diag_statcast.py <ruta al csv de predicciones>")
        print("\nCSV en C:\\Edgeline que podrian servir:")
        for p in glob.glob(os.path.join(BASE, "*.csv")):
            b = os.path.basename(p).lower()
            if any(k in b for k in ("statcast", "predic", "mlb", "model")):
                print("  ", os.path.basename(p))
        return

    rows = leer(pred_path)
    print("Archivo: %s   (%d filas)" % (os.path.basename(pred_path), len(rows)))
    cols = list(rows[0].keys()) if rows else []
    prob_cols = [c for c in cols if c.lower().startswith("p_") or c.lower() in ("prob", "p")]
    print("Columnas de probabilidad detectadas: %s" % (", ".join(prob_cols) or "ninguna"))
    print("Otras columnas: %s" % ", ".join(c for c in cols if c not in prob_cols)[:200])

    # resultado real por fila
    ys = [resultado_real(r) for r in rows]
    n_con_y = sum(1 for y in ys if y is not None)
    print("\nFilas con resultado real: %d de %d" % (n_con_y, len(rows)))
    if n_con_y < 30:
        print("No hay suficientes resultados reales en el archivo.")
        print("Si el resultado esta en mlb_statcast_model_v1_results.csv, dime y lo cruzo.")
        return

    print("\n%-16s %8s %8s %8s" % ("MODELO (col)", "N", "ACC", "BRIER"))
    print("-" * 44)
    for c in prob_cols:
        acc = br = 0.0; n = 0
        for r, y in zip(rows, ys):
            p = num(r.get(c))
            if p is None or y is None:
                continue
            if p > 1:  # viene en %
                p = p / 100.0
            acc += ((p >= 0.5) == (y == 1)); br += (p - y) ** 2; n += 1
        if n:
            print("%-16s %8d %8.4f %8.4f" % (c, n, acc / n, br / n))
    print("-" * 44)
    print("Si p_combo o p_statcast >= 0.565, el modelo con abridor YA te da tu 57%.")
    print("Ahi el paso es integrar esa columna al modelo unificado para MLB.")


if __name__ == "__main__":
    main()
