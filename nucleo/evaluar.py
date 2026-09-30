# -*- coding: utf-8 -*-
"""
PASO 5a - nucleo/evaluar.py

UN backtest walk-forward para cualquier deporte/modelo, sin fuga de informacion.
Reemplaza kbo_evaluar.py, nfl_evaluar.py, etc. Cada liga se ordena por fecha, se
entrena solo con lo anterior y se predice hacia adelante, reentrenando cada N juegos.

Reporta accuracy, Brier, logloss y una tabla de calibracion (prob predicha vs tasa
real por tramo), contra dos baselines: 'siempre local' y 'solo ELO'.

Interfaz que espera del modelo (modulo del deporte, p. ej. modelos/beisbol):
    entrenar(filas)  -> M          (o entrenar_logistica)
    prob(M, fila)    -> p_home     (o prob_local)

Uso (en C:\\Edgeline):
    python -c "import sys; sys.path.insert(0,'.'); from nucleo import evaluar; from modelos import beisbol; evaluar.correr('beisbol', beisbol)"
"""
import math, sys, os

try:
    from nucleo import io, features
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io, features


def _entrenar_fn(mod):
    return getattr(mod, "entrenar", None) or getattr(mod, "entrenar_logistica")

def _prob_fn(mod):
    return getattr(mod, "prob", None) or getattr(mod, "prob_local")


def _min_train_liga(n, tope):
    """Escala el minimo de entrenamiento al tamano de la liga (para que las chicas
    tambien se evaluen). Nunca menos de 60, nunca mas que 'tope'."""
    return min(tope, max(60, int(n * 0.4)))

def walk_forward(feats, entrenar, prob, min_train=200, refit=100):
    """Devuelve lista de dicts {liga, fecha, p, y, elo_dif} out-of-sample."""
    porliga = {}
    for r in feats:
        porliga.setdefault(r["league"], []).append(r)
    preds = []
    for lg, rows in porliga.items():
        rows.sort(key=lambda r: (r["game_date"], r["gamePk"]))
        mt = _min_train_liga(len(rows), min_train)
        if len(rows) < mt + 15:
            continue
        modelo = entrenar(rows[:mt])
        for j in range(mt, len(rows)):
            if (j - mt) % refit == 0 and j > mt:
                modelo = entrenar(rows[:j])
            if not modelo:
                continue
            r = rows[j]
            preds.append({"liga": lg, "fecha": r["game_date"], "y": r["y_home"],
                          "p": prob(modelo, r), "elo_dif": r.get("elo_dif") or 0.0})
    return preds


def brier(P): return sum((d["p"] - d["y"]) ** 2 for d in P) / len(P)
def logloss(P):
    s = 0.0
    for d in P:
        p = min(max(d["p"], 1e-6), 1 - 1e-6)
        s += -(d["y"] * math.log(p) + (1 - d["y"]) * math.log(1 - p))
    return s / len(P)
def acc(P): return sum(1 for d in P if (d["p"] >= .5) == (d["y"] == 1)) / len(P)


def tabla_calibracion(P, bins=10):
    tramos = {}
    for d in P:
        b = min(int(d["p"] * bins), bins - 1)
        t = tramos.setdefault(b, {"n": 0, "sp": 0.0, "sy": 0})
        t["n"] += 1; t["sp"] += d["p"]; t["sy"] += d["y"]
    filas = []
    for b in sorted(tramos):
        t = tramos[b]
        filas.append((100 * t["sp"] / t["n"], 100 * t["sy"] / t["n"], t["n"]))
    return filas


def correr(deporte, modelo_mod, liga=None, min_train=200, refit=100, calibrar=True):
    feats, _ = features.construir(deporte, liga)
    if not feats:
        print("Sin features. Falta datos/%s.csv." % deporte); return
    entrenar, prob = _entrenar_fn(modelo_mod), _prob_fn(modelo_mod)
    P = walk_forward(feats, entrenar, prob, min_train, refit)
    if not P:
        print("Muestra insuficiente para walk-forward (min_train=%d)." % min_train); return

    print("BACKTEST walk-forward - %s   (n out-of-sample = %d)" % (deporte, len(P)))
    print("-" * 66)
    # por liga
    porliga = {}
    for d in P:
        porliga.setdefault(d["liga"], []).append(d)
    print("%-8s %7s %8s %8s %8s %10s" % ("LIGA", "N", "ACC", "BRIER", "LOGLOSS", "vs LOCAL"))
    print("-" * 66)
    for lg in sorted(porliga):
        Q = porliga[lg]
        base = sum(d["y"] for d in Q) / len(Q)
        br_loc = sum((base - d["y"]) ** 2 for d in Q) / len(Q)
        print("%-8s %7d %8.3f %8.3f %8.3f %10s" %
              (lg, len(Q), acc(Q), brier(Q), logloss(Q),
               "%+.3f" % (br_loc - brier(Q))))
    print("-" * 66)
    print("GLOBAL   %7d %8.3f %8.3f %8.3f" % (len(P), acc(P), brier(P), logloss(P)))
    print("  (vs LOCAL = cuanto mejora el Brier contra 'siempre local'; + es mejor)")

    # calibracion
    print("\nCALIBRACION (prob predicha -> tasa real):")
    for pp, tr, n in tabla_calibracion(P):
        flag = "  ok" if abs(pp - tr) <= 5 else ("  ALTO" if pp > tr else "  bajo")
        print("  pred %5.1f%%  real %5.1f%%  (n=%4d)%s" % (pp, tr, n, flag))

    if calibrar:
        from nucleo import calibrar as C
        print("\n--- Platt POR LIGA (cada liga se calibra sola y se guarda) ---")
        print("%-8s %10s %18s" % ("LIGA", "a / b", "Brier  sin -> cal"))
        print("-" * 42)
        params_liga = {}
        for lg in sorted(porliga):
            Q = porliga[lg]
            if len(Q) < 100:
                print("%-8s  muestra chica, sin calibrar" % lg); continue
            a, b = C.ajustar(Q)
            Qc = [{**d, "p": C.aplicar(d["p"], a, b)} for d in Q]
            C.guardar(deporte, a, b, liga=lg)
            params_liga[lg] = (a, b)
            print("%-8s %5.2f/%5.2f    %.3f -> %.3f" % (lg, a, b, brier(Q), brier(Qc)))
        print("-" * 42)
        print("Guardados en nucleo/_calib/%s_<liga>.json" % deporte)
        return P, params_liga
    return P, None


def perspectivas(deporte, modelo_mod, liga=None, min_train=300, refit=150, guardar=True, min_n=150):
    """
    Compara, por liga y sin fuga, las tres visiones del GANADOR:
      LOGISTICA  -> el modelo de features (ELO + box)
      CARRERAS   -> prob derivada de las carreras esperadas (ritmo ofensivo/defensivo)
      ENSAMBLE   -> combinacion de las dos (mejor de ambas)
    Busca el peso w del ensamble que da mejor Brier por liga y, si guardar=True y la
    liga tiene >= min_n juegos de test, lo guarda para que el modelo lo use.
    """
    feats, _ = features.construir(deporte, liga)
    if not feats:
        print("Sin features. Falta datos/%s.csv." % deporte); return
    plocal = getattr(modelo_mod, "prob_local")
    pcarr = getattr(modelo_mod, "prob_por_carreras")
    entren = getattr(modelo_mod, "entrenar", None) or getattr(modelo_mod, "entrenar_logistica")

    porliga = {}
    for r in feats:
        porliga.setdefault(r["league"], []).append(r)

    def a(P, key): return sum(1 for d in P if (d[key] >= .5) == (d["y"] == 1)) / len(P)
    def b(P, key): return sum((d[key] - d["y"]) ** 2 for d in P) / len(P)

    print("EVALUACION DE PERSPECTIVAS (ganador) - %s" % deporte)
    print("-" * 90)
    print("%-8s %6s | %-14s | %-14s | %-14s | %s" %
          ("LIGA", "N", "LOGISTICA", "CARRERAS", "ENSAMBLE .5", "MEJOR w (acc/brier)"))
    print("-" * 90)
    for lg in sorted(porliga):
        rows = porliga[lg]; rows.sort(key=lambda r: (r["game_date"], r["gamePk"]))
        mt = _min_train_liga(len(rows), min_train)
        if len(rows) < mt + 15:
            print("%-8s %6d | sin datos suficientes" % (lg, len(rows))); continue
        P = []
        modelo = entren(rows[:mt])
        for j in range(mt, len(rows)):
            if (j - mt) % refit == 0 and j > mt:
                modelo = entren(rows[:j])
            r = rows[j]; pc = pcarr(r)
            if pc is None:
                continue
            P.append({"y": r["y_home"], "pl": plocal(modelo, r), "pc": pc})
        if not P:
            continue
        ruido = " (ruido, n bajo)" if len(P) < 150 else ""
        for d in P:
            d["pe"] = 0.5 * d["pl"] + 0.5 * d["pc"]
        # mejor w por Brier
        mejor = min((round(w, 1) for w in [i / 10 for i in range(0, 11)]),
                    key=lambda w: sum((w * d["pl"] + (1 - w) * d["pc"] - d["y"]) ** 2 for d in P))
        for d in P:
            d["pm"] = mejor * d["pl"] + (1 - mejor) * d["pc"]
        guardado = ""
        if guardar and len(P) >= min_n:
            from nucleo import calibrar as C
            C.guardar_w(deporte, lg, mejor)
            guardado = " *"
        print("%-8s %6d | acc%.3f br%.3f | acc%.3f br%.3f | acc%.3f br%.3f | w=%.1f acc%.3f br%.3f%s%s" %
              (lg, len(P), a(P, "pl"), b(P, "pl"), a(P, "pc"), b(P, "pc"),
               a(P, "pe"), b(P, "pe"), mejor, a(P, "pm"), b(P, "pm"), guardado, ruido))
    print("-" * 90)
    print("Lee: si CARRERAS o ENSAMBLE le ganan a LOGISTICA, esa liga sube al combinar.")
    print("'MEJOR w' es el peso de la logistica que minimiza Brier. '*' = guardado (n>=%d)." % min_n)


def correr_runline(deporte, modelo_mod, liga=None):
    """
    Backtest del RUN LINE (-1.5): compara la prob de que el local cubra -1.5 (as-of,
    sin entrenamiento) contra si de verdad cubrio (gano por 2+). Reporta acierto del
    pick de run line y calibracion (prob predicha vs tasa real de cubrir).
    """
    feats, _ = features.construir(deporte, liga)
    if not feats:
        print("Sin features. Falta datos/%s.csv." % deporte); return
    prl = getattr(modelo_mod, "prob_run_line")
    porliga = {}
    for r in feats:
        porliga.setdefault(r["league"], []).append(r)

    print("BACKTEST RUN LINE (-1.5) - %s" % deporte)
    print("-" * 70)
    print("%-8s %7s %9s %12s %s" % ("LIGA", "N", "ACC pick", "cubre real", "calibracion"))
    print("-" * 70)
    for lg in sorted(porliga):
        Q = porliga[lg]
        P = []
        for r in Q:
            ph, _ = prl(r, 1.5)
            marg = r.get("marg_home")
            if marg is None:
                # el margen se deduce de total y y_home no basta; usamos runs si estan
                pass
            if ph is None:
                continue
            # cubierto real: el local gano por 2+  -> necesitamos el marcador
            cubierto = r.get("cubierto_rl")
            P.append({"ph": ph, "cub": cubierto})
        P = [d for d in P if d["cub"] is not None]
        if len(P) < 40:
            print("%-8s %7d  (sin marcador para run line)" % (lg, len(P))); continue
        acc = sum(1 for d in P if (d["ph"] >= .5) == (d["cub"] == 1)) / len(P)
        real = sum(d["cub"] for d in P) / len(P)
        pred = sum(d["ph"] for d in P) / len(P)
        print("%-8s %7d %8.3f %11.1f%%   pred %.1f%% vs real %.1f%%" %
              (lg, len(P), acc, 100 * real, 100 * pred, 100 * real))
    print("-" * 70)
    print("Si 'pred' ~ 'real', la prob de run line esta bien calibrada.")


def correr_totales(deporte, modelo_mod, liga=None):
    """
    Backtest de CARRERAS/TOTALES (no ganador). El total esperado es as-of (no necesita
    entrenamiento), asi que se evalua directo sobre cada juego con >= muestra.
    Reporta: MAE del total (que tan lejos cae la prediccion), y acierto de over/under
    en la linea MEDIA de cada liga, contra el baseline 'predecir el promedio de liga'.
    """
    feats, _ = features.construir(deporte, liga)
    if not feats:
        print("Sin features. Falta datos/%s.csv." % deporte); return
    cet = getattr(modelo_mod, "carreras_esperadas")
    porliga = {}
    for r in feats:
        porliga.setdefault(r["league"], []).append(r)

    print("BACKTEST de TOTALES - %s" % deporte)
    print("-" * 74)
    print("%-8s %7s %9s %9s %9s %10s" %
          ("LIGA", "N", "MAE_mod", "MAE_base", "linea", "O/U acc"))
    print("-" * 74)
    for lg in sorted(porliga):
        Q = porliga[lg]
        reales = [r["total"] for r in Q if r.get("total") is not None]
        if len(reales) < 30:
            continue
        prom = sum(reales) / len(reales)              # promedio de liga (baseline)
        linea = round(prom * 2) / 2                    # linea tipica ~ al promedio
        ae_mod, ae_base, ou_ok, ou_n = 0.0, 0.0, 0, 0
        for r in Q:
            real = r.get("total")
            xh, xa = cet(r)
            if real is None or xh is None:
                continue
            pred = xh + xa
            ae_mod += abs(pred - real); ae_base += abs(prom - real)
            if real != linea:                          # over/under vs linea de liga
                pred_over = pred > linea
                real_over = real > linea
                ou_ok += (pred_over == real_over); ou_n += 1
        n = sum(1 for r in Q if r.get("total") is not None and cet(r)[0] is not None)
        if n == 0:
            continue
        print("%-8s %7d %9.3f %9.3f %9.1f %9.1f%%" %
              (lg, n, ae_mod / n, ae_base / n, linea, 100 * ou_ok / max(ou_n, 1)))
    print("-" * 74)
    print("MAE_mod < MAE_base = el modelo predice el total mejor que el promedio de liga.")
    print("O/U acc > 52.4%% = superarias el vig estandar (-110) en over/under.")


if __name__ == "__main__":
    dep = sys.argv[1] if len(sys.argv) > 1 else "beisbol"
    mod = __import__("modelos.%s" % dep, fromlist=[dep])
    correr(dep, mod)
