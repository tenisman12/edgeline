# -*- coding: utf-8 -*-
"""
utilidades/minar_platt_pool.py - compartir la CALIBRACION entre ligas del mismo deporte (americano y basket).

Hipotesis (escrita antes de ver resultados):
  Problema. modelos/americano.py y modelos/nba.py convierten la probabilidad cruda del ensamble en la final con
  una Platt de dos parametros ajustada POR LIGA. NFL tiene 1,473 partidos y NCAAF 4,200; NBA 4,910 y NCAA
  basquet 18,835. En cada deporte una liga tiene bastante menos muestra que la otra.
  Senal. El juego es el mismo: la relacion entre la probabilidad cruda y la real no tiene por que diferir entre
  NFL y NCAAF. Ajustar la Platt con los pares de las DOS ligas deberia estimar mejor (a, b) en la liga chica sin
  perder en la grande. Es la misma idea del modelo jerarquico de beisbol, aplicada donde SI hay asimetria de
  muestra (en beisbol las siete ligas eran grandes y por eso no paso).
  Variante (k = 1): B la Platt se ajusta con los pares de las dos ligas; todo lo demas (acumuladores de equipo,
  media de liga, sesgos del margen y del total) se queda por liga.
  Direccion esperada. Mejora en la liga con menos muestra; empate en la grande.
  PREVISION ESCRITA ANTES DE MEDIR: con 1,473 pares, dos parametros ya quedan bien determinados, asi que lo mas
  probable es que NO pase. Se mide porque es barato y porque la alternativa es suponerlo.
  Contra que. Walk-forward por bloques con el mismo mecanismo de la casa (se parcha io.cargar_juegos con un
  corte de fecha, igual que validar_mercados.validar_equipos). Rival: la Platt de su propia liga, entrenada con
  lo mismo. Base: frecuencia historica de victoria local.
  Metrica. Log-loss del ganador, error pareado. Criterio: n >= 300, z >= 2.0, mejora en las dos mitades,
  |p media - tasa| <= 0.04.

Se mira UNA vez. Escribe trabajo/minar/<fecha>_platt_pool.md. Solo stdlib.

    python utilidades\\minar_platt_pool.py
    python utilidades\\minar_platt_pool.py --deporte americano --bloque 45
"""
import argparse, io as _io, math, os, sys, datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io as nio

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPORTES = {"americano": ("nfl", "ncaafb"), "basket": ("nba", "ncaamb")}
MODULO = {"americano": "americano", "basket": "nba"}


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _z(d):
    n = len(d)
    if n < 2:
        return 0.0
    m = sum(d) / n
    v = sum((x - m) ** 2 for x in d) / (n - 1)
    return (m / math.sqrt(v / n)) if v > 0 else 0.0


def _entrenar_asof(mod, liga, corte):
    """entrenar(liga) viendo solo juegos anteriores a 'corte'. Mismo truco que validar_equipos."""
    orig = nio.cargar_juegos
    nio.cargar_juegos = lambda x, lg=None, _o=orig, _c=corte: [
        r for r in _o(x, lg) if (r.get("game_date") or "")[:10] < _c]
    try:
        return mod.entrenar(liga)
    finally:
        nio.cargar_juegos = orig


def _pares(est, cal):
    """(prob cruda del ensamble, resultado) con el peso w de ese estado, que es lo que come _platt."""
    w = est.get("w", 1.0)
    return [(w * pe + (1 - w) * psc, y) for pe, psc, y in cal]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", default="todos", choices=["todos"] + list(DEPORTES))
    ap.add_argument("--bloque", type=int, default=45)
    ap.add_argument("--meses", type=float, default=30.0)
    a = ap.parse_args()
    out = ["# Hipotesis (escrita antes de ver resultados) - %s" % dt.date.today().isoformat(), "",
           "Compartir la Platt de dos parametros entre las ligas del mismo deporte (americano: NFL + NCAAF;",
           "basket: NBA + NCAA). Todo lo demas se queda por liga. Es la idea del modelo jerarquico de beisbol",
           "aplicada donde SI hay asimetria de muestra.", "",
           "Direccion esperada: mejora en la liga chica, empate en la grande.",
           "Prevision escrita antes de medir: con 1,473 pares de NFL dos parametros ya quedan determinados, asi",
           "que lo mas probable es que NO pase.", "",
           "Criterio de la casa: n>=300, z>=2.0, mejora en las dos mitades, |p media - tasa| <= 0.04.", ""]
    for dep in (list(DEPORTES) if a.deporte == "todos" else [a.deporte]):
        mod = __import__("modelos.%s" % MODULO[dep], fromlist=["x"])
        ligas = DEPORTES[dep]
        print("=== %s: %s" % (dep.upper(), " + ".join(l.upper() for l in ligas)))
        J = {}
        for lg in ligas:
            J[lg] = mod._juegos(lg)
            print("   %-7s %6d partidos" % (lg.upper(), len(J[lg])))
        fechas = sorted({x[0] for lg in ligas for x in J[lg]})
        if not fechas:
            out.append("## %s: sin partidos." % dep); continue
        ultimo = dt.date.fromisoformat(fechas[-1])
        d0 = max(dt.date.fromisoformat(fechas[0]) + dt.timedelta(days=200),
                 ultimo - dt.timedelta(days=int(a.meses * 30.4)))
        R = defaultdict(list); nbl = 0
        while d0 <= ultimo:
            d1 = d0 + dt.timedelta(days=a.bloque)
            corte = d0.isoformat()
            est, pares = {}, []
            for lg in ligas:
                prev = [x for x in J[lg] if x[0] < corte]
                if len(prev) < 300:
                    continue
                e = _entrenar_asof(mod, lg, corte)
                if not e:
                    continue
                est[lg] = e
                pares += _pares(e, e.get("cal") or [])
            if len(est) == len(ligas) and len(pares) >= 240:
                platt_pool = mod._platt(pares)
                nbl += 1
                for lg in ligas:
                    e = est[lg]
                    blk = [x for x in J[lg] if corte <= x[0] < d1.isoformat()]
                    prev = [x for x in J[lg] if x[0] < corte]
                    if not blk:
                        continue
                    def pts(r):
                        return mod._f(r.get("points")) if mod._f(r.get("points")) is not None else mod._f(r.get("runs"))
                    gan = [1 for x in prev if (pts(x[2]) or 0) > (pts(x[3]) or 0)]
                    hw = len(gan) / len(prev)
                    e2 = dict(e); e2["platt"] = platt_pool
                    for f, gp, h, aw in blk:
                        ph, pa_ = pts(h), pts(aw)
                        if ph is None or pa_ is None:
                            continue
                        r0 = mod.predecir(e, h.get("team"), aw.get("team"))
                        r1 = mod.predecir(e2, h.get("team"), aw.get("team"))
                        if not r0 or not r1:
                            continue
                        y = 1 if ph > pa_ else 0
                        R[lg].append((_ll(r0["p_home"], y), _ll(r1["p_home"], y), _ll(hw, y), r1["p_home"], y))
            d0 = d1
        print("   bloques de walk-forward: %d" % nbl)
        out.append("## %s (bloques de %d dias, %d bloques; mirado una vez)" % (dep, a.bloque, nbl))
        for lg in ligas:
            xs = R[lg]
            if len(xs) < 100:
                print("   %-7s n=%d: insuficiente" % (lg.upper(), len(xs)))
                out.append("- %s: n=%d, insuficiente." % (lg.upper(), len(xs))); continue
            n = len(xs)
            d = [x[0] - x[1] for x in xs]
            m = 1000 * sum(d) / n; z = _z(d)
            h2 = n // 2
            m1 = 1000 * sum(d[:h2]) / h2; m2 = 1000 * sum(d[h2:]) / (n - h2)
            pm = sum(x[3] for x in xs) / n; ta = sum(x[4] for x in xs) / n
            vb = 1000 * sum(x[2] - x[1] for x in xs) / n
            pasa = n >= 300 and z >= 2.0 and m1 > 0 and m2 > 0 and abs(pm - ta) <= 0.04
            print("   %-7s n=%5d  vs su Platt %+7.2f milesimas (z %+5.2f)  vs base %+7.2f  mitades %+6.2f/%+6.2f  p %.3f vs %.3f  %s" % (
                lg.upper(), n, m, z, vb, m1, m2, pm, ta, "PASA" if pasa else "no pasa"))
            out.append("- **%s** n=%d: %+.2f milesimas de log-loss contra su propia Platt (z %.2f); contra la base %+.2f; "
                       "mitades %+.2f/%+.2f; p media %.3f vs tasa %.3f. %s" % (
                           lg.upper(), n, m, z, vb, m1, m2, pm, ta, "**PASA**" if pasa else "No pasa."))
        out.append("")
    os.makedirs(os.path.join(REPO, "trabajo", "minar"), exist_ok=True)
    ruta = os.path.join(REPO, "trabajo", "minar", "%s_platt_pool.md" % dt.date.today().isoformat())
    with _io.open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\nEscrito:", ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
