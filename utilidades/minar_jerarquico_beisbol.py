# -*- coding: utf-8 -*-
"""
utilidades/minar_jerarquico_beisbol.py - MODELO JERARQUICO con encogimiento parcial entre ligas (ganador de beisbol).

Hipotesis (escrita antes de ver resultados):
  Problema. El ganador de beisbol se predice con una logistica de 13 features de diferencia entrenada POR LIGA
  (modelos/beisbol.entrenar_logistica). MLB entrena con ~9,800 juegos, NPB con ~4,300 y KBO con 689. Las dos ligas
  chicas son justo donde el modelo apenas pasa validacion (NPB skill +2.1% z 2.65, KBO +3.1% z 3.42, MLB +1.3% z 2.82)
  y donde cada capa nueva falla por muestra.
  Senal. Los coeficientes de esas 13 features no tienen por que ser distintos entre ligas: el beisbol es el mismo
  juego. Un modelo multinivel que comparta los coeficientes entre MLB, NPB y KBO, dejando intercepto propio por liga
  (ventaja local distinta) y encogiendo las desviaciones de cada liga hacia el coeficiente comun, deberia estimar
  mejor en las ligas chicas sin perder en la grande. Ademas, la fuerza de cada equipo como EFECTO ALEATORIO
  (dummies de equipo con prior normal, es decir ridge) encoge a los equipos con pocos juegos hacia la media de su
  liga, en vez de confiar en su ELO crudo.
  Variantes (k = 3):
    B  coeficientes comunes a las tres ligas + intercepto por liga.
    C  B + desviacion por liga encogida (coef_liga = comun + delta_liga, con L2 fuerte sobre delta).
    D  C + efectos aleatorios de equipo (ridge sobre dummies de local y visita).
  Direccion esperada. Mejora en KBO y NPB; en MLB, empate o mejora chica. Si solo mejora MLB, la hipotesis es falsa.
  Contra que. El mismo walk-forward por bloques del validador de la casa, con la logistica actual por liga como
  rival, y la frecuencia historica de victoria local como linea base.
  Metrica. Log-loss por juego; error pareado contra el modelo actual y contra la base.
  Criterio de la casa. n >= 300 en prueba, z >= 2.0, mejora en las dos mitades, |p media - tasa| <= 0.04.

Se mira UNA vez. Escribe trabajo/minar/<fecha>_jerarquico_beisbol.md y modelos/jerarquico_beisbol.json.

    python utilidades\\minar_jerarquico_beisbol.py
    python utilidades\\minar_jerarquico_beisbol.py --bloque 30 --meses 18
Usa numpy (solo este script de medicion; nada del pipeline lo importa). Si falta: pip install numpy
"""
import argparse, io as _io, json, math, os, sys, datetime as dt
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import features as F, io as nio
from modelos import beisbol as B

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Las siete ligas de beisbol con datos. El encogimiento se hace entre TODAS: KBO (664 juegos) toma prestado
# de MLB (9,492) y de las invernales. Solo se reportan las tres que se apuestan.
LIGAS = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")
REPORTAR = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")   # TODAS las ligas, las invernales incluidas
FEATS = B.FEATS
L2_COMUN = 1.0        # mismo L2 que el modelo actual, para que la comparacion sea limpia
L2_DELTA = 20.0       # desviacion por liga: prior fuerte (encogimiento hacia el coeficiente comun)
L2_EQUIPO = 8.0       # efecto aleatorio de equipo: prior medio
ITERS, LR = 400, 0.3


def _sig(z):
    if z < -35: return 0.0
    if z > 35: return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _estandarizar(filas):
    mu, sd = {}, {}
    for f in FEATS:
        v = [r[f] for r in filas if r.get(f) is not None]
        m = sum(v) / len(v) if v else 0.0
        var = sum((x - m) ** 2 for x in v) / len(v) if v else 1.0
        mu[f] = m; sd[f] = math.sqrt(var) or 1.0
    return mu, sd


def _vec(r, mu, sd):
    return [((r[f] - mu[f]) / sd[f]) if r.get(f) is not None else 0.0 for f in FEATS]


def _diseno(filas, variante, ligas_idx, equipos_idx, mu, sd):
    """Matriz de diseno por bloques y el vector de penalizacion de cada columna.
       [ X (13) | intercepto por liga (nl) | X x liga (13*nl, solo C/D) | equipo local-visita (ne, solo D) ]
    La penalizacion distinta por bloque ES el encogimiento parcial: los coeficientes comunes llevan L2 suave,
    las desviaciones por liga L2 fuerte (se van a cero si la liga no aporta), y los equipos L2 medio."""
    n = len(filas); d = len(FEATS); nl = len(ligas_idx)
    X = np.array([_vec(r, mu, sd) for r in filas], dtype=float)
    L = np.array([ligas_idx[r["league"]] for r in filas], dtype=int)
    bloques = [X]
    pen = [np.full(d, L2_COMUN)]
    OH = np.zeros((n, nl)); OH[np.arange(n), L] = 1.0
    bloques.append(OH); pen.append(np.zeros(nl))          # intercepto de liga sin penalizar
    if variante in ("C", "D"):
        XL = np.zeros((n, d * nl))
        for k in range(nl):
            m = (L == k)
            XL[np.ix_(m, range(k * d, (k + 1) * d))] = X[m]
        bloques.append(XL); pen.append(np.full(d * nl, L2_DELTA))
    if variante == "D":
        ne = len(equipos_idx)
        E = np.zeros((n, ne))
        for i, r in enumerate(filas):
            h = equipos_idx.get((r["league"], r["home"]), -1)
            a = equipos_idx.get((r["league"], r["away"]), -1)
            if h >= 0: E[i, h] += 1.0
            if a >= 0: E[i, a] -= 1.0
        bloques.append(E); pen.append(np.full(ne, L2_EQUIPO))
    return np.hstack(bloques), np.concatenate(pen)


def entrenar(filas, variante, ligas_idx, equipos_idx, iters=8):
    """Logistica penalizada por IRLS (Newton con ridge por bloque). Converge en ~8 pasos."""
    if len(filas) < 60:
        return None
    mu, sd = _estandarizar(filas)
    Z, pen = _diseno(filas, variante, ligas_idx, equipos_idx, mu, sd)
    y = np.array([r["y_home"] for r in filas], dtype=float)
    n, k = Z.shape
    beta = np.zeros(k)
    Lam = np.diag(pen)
    for _ in range(iters):
        eta = Z @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -35, 35)))
        W = np.clip(p * (1 - p), 1e-6, None)
        # paso de Newton: (Z'WZ + Lam) db = Z'(y-p) - Lam beta
        A = Z.T @ (Z * W[:, None]) + Lam
        g = Z.T @ (y - p) - Lam @ beta
        try:
            db = np.linalg.solve(A, g)
        except np.linalg.LinAlgError:
            db = np.linalg.lstsq(A, g, rcond=None)[0]
        beta = beta + db
        if np.max(np.abs(db)) < 1e-7:
            break
    return {"beta": beta, "mu": mu, "sd": sd, "li": ligas_idx, "ei": equipos_idx, "variante": variante}


def predecir_lote(m, filas):
    """Probabilidades de un bloque entero. Devuelve None para las filas de ligas que el modelo no vio."""
    ok = [r for r in filas if r["league"] in m["li"]]
    if not ok:
        return {}
    Z, _ = _diseno(ok, m["variante"], m["li"], m["ei"], m["mu"], m["sd"])
    p = 1.0 / (1.0 + np.exp(-np.clip(Z @ m["beta"], -35, 35)))
    return {id(r): float(pi) for r, pi in zip(ok, p)}


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _z(dif):
    """z del error pareado: media / error estandar."""
    n = len(dif)
    if n < 2:
        return 0.0
    m = sum(dif) / n
    var = sum((x - m) ** 2 for x in dif) / (n - 1)
    return (m / math.sqrt(var / n)) if var > 0 else 0.0


def cargar():
    """Filas as-of de todas las ligas de beisbol, en una sola pasada (construir() recorre el csv completo).
    Mismo constructor que usa el validador de la casa, para que la comparacion sea limpia."""
    feats, _ = F.construir("beisbol", None, 5)
    G = defaultdict(list)
    for r in feats:
        if r.get("y_home") is None:
            continue
        lg = r.get("league")
        if lg in {nio.norm(l) for l in LIGAS}:
            G[lg].append(r)
    for lg in G:
        G[lg].sort(key=lambda r: r["game_date"])
        print("  %-5s %5d juegos%s" % (lg.upper(), len(G[lg]), "   (se reporta)" if lg in REPORTAR else ""))
    return G


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bloque", type=int, default=30, help="dias por bloque de walk-forward")
    ap.add_argument("--meses", type=float, default=18.0, help="ventana de prueba hacia atras")
    a = ap.parse_args()
    print("MODELO JERARQUICO DE BEISBOL (encogimiento parcial entre ligas) - se mira una vez")
    G = cargar()
    todos = sorted([r for xs in G.values() for r in xs], key=lambda r: r["game_date"])
    if len(todos) < 2000:
        print("Muestra insuficiente."); return 1
    ultimo = dt.date.fromisoformat(todos[-1]["game_date"][:10])
    ini = ultimo - dt.timedelta(days=int(a.meses * 30.4))
    d0 = max(ini, dt.date.fromisoformat(todos[0]["game_date"][:10]) + dt.timedelta(days=200))
    ligas_idx = {lg: i for i, lg in enumerate(sorted(G))}
    # resultados: por variante y liga, lista de (ll_modelo_actual, ll_variante, ll_base, p, y)
    R = defaultdict(lambda: defaultdict(list))
    nbl = 0
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=a.bloque)
        blk = [r for r in todos if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in todos if r["game_date"][:10] < d0.isoformat()]
        if blk and len(prev) >= 600:
            # rival: el modelo actual, una logistica POR LIGA con lo anterior de esa liga
            actual = {}
            base = {}
            for lg in REPORTAR:   # el rival solo hace falta en las ligas que se reportan (ahorra entrenar 4 logisticas)
                pl = [r for r in prev if r["league"] == lg]
                if len(pl) >= 300:
                    actual[lg] = B.entrenar_logistica(pl)
                    base[lg] = sum(r["y_home"] for r in pl) / len(pl)
            equipos_idx = {}
            for r in prev:
                for lado in ("home", "away"):
                    k = (r["league"], r[lado])
                    if k not in equipos_idx:
                        equipos_idx[k] = len(equipos_idx)
            jer = {v: entrenar(prev, v, ligas_idx, equipos_idx) for v in ("B", "C", "D")}
            if any(jer.values()) and actual:
                nbl += 1
                pred = {v: (predecir_lote(m, blk) if m else {}) for v, m in jer.items()}
                for r in blk:
                    lg = r["league"]
                    if lg not in actual or not actual[lg]:
                        continue
                    p0 = B.prob_local(actual[lg], r)
                    y = r["y_home"]; bb = base[lg]
                    for v in ("B", "C", "D"):
                        pv = pred[v].get(id(r))
                        if pv is None:
                            continue
                        R[v][lg].append((_ll(p0, y), _ll(pv, y), _ll(bb, y), pv, y, p0))
        d0 = d1
    print("  bloques de walk-forward: %d" % nbl)
    out = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "bloque_dias": a.bloque,
           "meses": a.meses, "l2": {"comun": L2_COMUN, "delta_liga": L2_DELTA, "equipo": L2_EQUIPO},
           "variantes": {"B": "coeficientes comunes + intercepto por liga",
                         "C": "B + desviacion por liga encogida",
                         "D": "C + efectos aleatorios de equipo"}, "resultados": {}}
    print("\n(mejora en MILESIMAS de log-loss; positivo = la variante gana. 'vs actual' es el pareado contra la logistica por liga)")
    print("%-3s %-5s %6s  %18s  %18s  %s" % ("var", "liga", "n", "vs modelo actual", "vs linea base", "calibracion"))
    for v in ("B", "C", "D"):
        for lg in sorted(R[v]):
            if lg not in REPORTAR:
                continue
            xs = R[v][lg]
            n = len(xs)
            if n < 100:
                continue
            d_act = [(x[0] - x[1]) for x in xs]
            d_bas = [(x[2] - x[1]) for x in xs]
            m_act = 1000 * sum(d_act) / n; z_act = _z(d_act)
            m_bas = 1000 * sum(d_bas) / n; z_bas = _z(d_bas)
            h = n // 2
            m1 = 1000 * sum(d_act[:h]) / h; m2 = 1000 * sum(d_act[h:]) / (n - h)
            pm = sum(x[3] for x in xs) / n; ta = sum(x[4] for x in xs) / n
            pasa = (n >= 300 and z_act >= 2.0 and m1 > 0 and m2 > 0 and abs(pm - ta) <= 0.04)
            out["resultados"].setdefault(v, {})[lg] = {
                "n": n, "vs_actual_milesimas": round(m_act, 2), "z_vs_actual": round(z_act, 2),
                "vs_base_milesimas": round(m_bas, 2), "z_vs_base": round(z_bas, 2),
                "mitades": [round(m1, 2), round(m2, 2)], "p_media": round(pm, 3), "tasa_real": round(ta, 3),
                "pasa": bool(pasa)}
            print("%-3s %-5s %6d  %+8.2f (z %+5.2f)  %+8.2f (z %+5.2f)  p %.3f vs %.3f  mitades %+6.2f/%+6.2f  %s" % (
                v, lg.upper(), n, m_act, z_act, m_bas, z_bas, pm, ta, m1, m2, "PASA" if pasa else "no pasa"))
    # Impacto practico. No hay cuotas historicas de beisbol, asi que NO se puede simular el EV real.
    # Lo que si se puede medir sin inventar precios: con que frecuencia los dos modelos caen a lados
    # OPUESTOS del umbral de decision. Para una cuota decimal D, el pick entra si p >= 1.01/D. Si un modelo
    # queda arriba del umbral y el otro abajo, la decision cambia. Se reporta en tres precios tipicos.
    # (Un intento anterior derivaba la cuota de la probabilidad del modelo actual; eso le fijaba EV -4.5%
    #  por construccion y hacia que todos los cambios fueran en una sola direccion. Estaba mal.)
    UMBRALES = ((1.70, 1.01 / 1.70), (2.00, 1.01 / 2.00), (2.40, 1.01 / 2.40))
    print("\nIMPACTO PRACTICO (variante B): cuanto mueve la probabilidad y con que frecuencia cruza el umbral de decision")
    out["impacto"] = {}
    for lg in sorted(R["B"]):
        if lg not in REPORTAR: continue
        xs = R["B"][lg]
        if len(xs) < 100: continue
        dps = sorted(abs(x[3] - x[5]) for x in xs)
        n = len(dps)
        prom = sum(dps) / n; med = dps[n // 2]; p90 = dps[int(0.90 * n)]
        d = {"n": n, "dp_promedio_pp": round(100 * prom, 2), "dp_mediana_pp": round(100 * med, 2),
             "dp_p90_pp": round(100 * p90, 2), "dp_max_pp": round(100 * dps[-1], 2), "cruces": {}}
        tramos = []
        for D, u in UMBRALES:
            cr = ac = 0
            for ll0, llv, llb, pv, y, p0 in xs:
                for q0, qv in ((p0, pv), (1 - p0, 1 - pv)):
                    if (q0 >= u) != (qv >= u):
                        cr += 1
                        # acierto del lado nuevo cuando la decision cambia a favor de B
                        if qv >= u:
                            ac += 1
            d["cruces"]["cuota_%.2f" % D] = {"umbral_p": round(u, 3), "cruces": cr, "de_lados": 2 * n,
                                             "pct": round(100.0 * cr / (2 * n), 2)}
            tramos.append("cuota %.2f (p>=%.1f%%): %d de %d lados (%.1f%%)" % (D, 100 * u, cr, 2 * n, 100.0 * cr / (2 * n)))
        out["impacto"][lg] = d
        print("  %-5s n=%5d  |cambio de p|: promedio %.2f pp, mediana %.2f pp, p90 %.2f pp, max %.2f pp" % (
            lg.upper(), n, 100 * prom, 100 * med, 100 * p90, 100 * dps[-1]))
        for t in tramos:
            print("          cruza el umbral en %s" % t)

    # veredicto
    pasan = [(v, lg) for v in out["resultados"] for lg, d in out["resultados"][v].items() if d["pasa"]]
    out["veredicto"] = ("PASA en: " + ", ".join("%s/%s" % (v, lg.upper()) for v, lg in pasan)) if pasan else \
                       "NO PASA en ninguna liga con ninguna variante (k = 3)"
    print("\nVEREDICTO:", out["veredicto"])
    os.makedirs(os.path.join(REPO, "modelos"), exist_ok=True)
    with _io.open(os.path.join(REPO, "modelos", "jerarquico_beisbol.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Guardado: modelos/jerarquico_beisbol.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
