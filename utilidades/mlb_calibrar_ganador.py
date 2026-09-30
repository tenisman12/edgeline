# -*- coding: utf-8 -*-
"""
MLB - calibrar el ganador (p_combo) y revisar que sea estable.

Toma tu mejor senal de MLB (p_combo del modelo con abridor+statcast), revisa la
accuracy POR TEMPORADA (para detectar fuga: si una temporada esta rarisimo alta,
huele a in-sample), y calibra con Platt en split temporal (entrena en las viejas,
valida en la mas nueva). Guarda los parametros para que el modelo unificado los use.

Lee:  mlb_statcast_model_v1_predictions.csv  (game_id, season, y, p_home..p_combo)
Escribe:  nucleo/_calib/beisbol_mlb.json   (a, b del Platt)

Uso:
    python mlb_calibrar_ganador.py
    python mlb_calibrar_ganador.py --col p_combo
"""
import argparse, csv, io, os, json, math, glob

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")


def num(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None

def _logit(p): p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))
def _sig(z): return 0.0 if z < -35 else (1.0 if z > 35 else 1 / (1 + math.exp(-z)))

def platt(P, iters=800, lr=0.05):
    X = [_logit(d["p"]) for d in P]; Y = [d["y"] for d in P]; n = len(X)
    a, b = 1.0, 0.0
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(X, Y):
            e = _sig(a * x + b) - y; ga += e * x; gb += e
        a -= lr * ga / n; b -= lr * gb / n
    return a, b

def brier(P): return sum((d["p"] - d["y"]) ** 2 for d in P) / len(P)
def acc(P): return sum(1 for d in P if (d["p"] >= .5) == (d["y"] == 1)) / len(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--col", default="p_combo", help="columna de probabilidad a calibrar")
    ap.add_argument("--archivo", default=None)
    args = ap.parse_args()

    path = args.archivo or (glob.glob(os.path.join(BASE, "*statcast_model*predictions*.csv")) + [None])[0]
    if not path or not os.path.exists(path):
        print("No encontre mlb_statcast_model_v1_predictions.csv. Pasalo con --archivo."); return
    rows = list(csv.DictReader(io.open(path, encoding="utf-8-sig", errors="replace")))
    P = [{"season": r.get("season"), "p": num(r.get(args.col)), "y": num(r.get("y"))}
         for r in rows if num(r.get(args.col)) is not None and num(r.get("y")) is not None]
    print("Archivo: %s   col=%s   n=%d" % (os.path.basename(path), args.col, len(P)))

    # accuracy por temporada (chequeo de fuga)
    porseason = {}
    for d in P:
        porseason.setdefault(d["season"], []).append(d)
    print("\nAccuracy por temporada (si alguna esta >0.60, sospecha in-sample/fuga):")
    for s in sorted(porseason):
        Q = porseason[s]
        print("  %s  n=%5d  acc=%.4f  brier=%.4f" % (s, len(Q), acc(Q), brier(Q)))

    # split temporal: entrena Platt en viejas, valida en la ultima
    seasons = sorted(porseason)
    if len(seasons) >= 2:
        test_s = seasons[-1]
        tr = [d for d in P if d["season"] != test_s]
        te = [d for d in P if d["season"] == test_s]
        a, b = platt(tr)
        te_cal = [{**d, "p": _sig(a * _logit(d["p"]) + b)} for d in te]
        print("\nSplit temporal (test = %s):" % test_s)
        print("  sin calibrar : acc=%.4f  brier=%.4f" % (acc(te), brier(te)))
        print("  calibrado    : acc=%.4f  brier=%.4f  (Platt a=%.3f b=%.3f)" %
              (acc(te_cal), brier(te_cal), a, b))
    # Platt final con todo, para produccion
    a, b = platt(P)
    outdir = os.path.join(BASE, "nucleo", "_calib")
    os.makedirs(outdir, exist_ok=True)
    with io.open(os.path.join(outdir, "beisbol_mlb.json"), "w", encoding="utf-8") as f:
        json.dump({"a": a, "b": b, "col": args.col}, f)
    print("\nGuardado Platt de MLB (a=%.3f, b=%.3f) en nucleo/_calib/beisbol_mlb.json" % (a, b))
    print("Tabla de calibracion (todo, ya calibrado):")
    Pc = [{**d, "p": _sig(a * _logit(d["p"]) + b)} for d in P]
    tr = {}
    for d in Pc:
        k = min(int(d["p"] * 10), 9); t = tr.setdefault(k, [0, 0.0, 0])
        t[0] += 1; t[1] += d["p"]; t[2] += d["y"]
    for k in sorted(tr):
        n, sp, sy = tr[k]
        print("  pred %5.1f%%  real %5.1f%%  (n=%4d)" % (100 * sp / n, 100 * sy / n, n))


if __name__ == "__main__":
    main()
