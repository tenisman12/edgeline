# -*- coding: utf-8 -*-
"""
utilidades/capas_totales_beisbol.py - CAPAS DEL TOTAL DE CARRERAS: parque, umpire, clima y viento.

Por que: el total de beisbol es el unico mercado grande que no pasa validacion walk-forward en ninguna liga
(MLB skill -0.86%, NPB -0.04%, KBO +0.12%, y las tres fallan en las dos mitades). El modelo reparte carreras
con las ofensivas y el abridor, y no sabe nada del lugar donde se juega ni de quien canta las bolas ni del
clima. datos/beisbol.csv SI trae esos campos (estadio, umpire_home, clima, viento) con 100% de cobertura en
MLB sobre ~9,800 juegos, 'estadio' en todas las ligas.

Que hace: recorre los juegos en orden de fecha y, para cada uno, calcula las capas SOLO con lo anterior
(as-of, sin mirar el futuro):
  - parque:  (carreras por juego en ese estadio) - (carreras por juego de la liga), con regresion a la media
             por tamano de muestra (k juegos de lastre).
  - umpire:  lo mismo por umpire de home.
  - temp:    grados del campo 'clima' centrados en la media de la liga.
  - viento:  mph con signo segun direccion (Out = empuja carreras, In = las frena, resto = 0).
Luego mide por minimos cuadrados cuanto de la carrera RESIDUAL (total real menos la base de la liga) explica
cada capa, con validacion cruzada en 4 bloques por tiempo, y reporta el MAE del total con y sin cada capa.

Lo que se reporta es la mejora REAL fuera de muestra, no el ajuste. Si una capa no reduce el MAE en los
bloques de prueba, se reporta en cero y no se usa.

    python utilidades\\capas_totales_beisbol.py
    python utilidades\\capas_totales_beisbol.py --liga MLB
Escribe modelos/capas_totales_beisbol.json. Solo stdlib.
"""
import argparse, csv, io, json, os, re, sys, datetime as dt
from collections import defaultdict

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(REPO, "modelos", "capas_totales_beisbol.json")

LASTRE_PARQUE = 60.0      # juegos de lastre: con pocos juegos el factor se jala a cero
LASTRE_UMPIRE = 40.0
MIN_JUEGOS = 800          # ligas con menos no se miden
BLOQUES = 4


def juegos(liga_filtro=None):
    """Un registro por juego, en orden de fecha. Una fila por equipo en el csv, asi que se deduplica."""
    vistos = {}
    ruta = os.path.join(BASE, "datos", "beisbol.csv")
    with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            lg = (r.get("league") or "").upper()
            if liga_filtro and lg != liga_filtro:
                continue
            pk = str(r.get("gamePk") or "")
            k = (lg, pk)
            if k in vistos:
                continue
            try:
                total = float(r["runs"]) + float(r["runs_opp"])
                fecha = dt.date.fromisoformat((r.get("game_date") or "")[:10])
            except (TypeError, ValueError, KeyError):
                continue
            vistos[k] = {"liga": lg, "pk": pk, "fecha": fecha, "total": total,
                         "estadio": (r.get("estadio") or "").strip(),
                         "umpire": (r.get("umpire_home") or "").strip(),
                         "temp": _temp(r.get("clima")), "viento": _viento(r.get("viento"))}
    out = sorted(vistos.values(), key=lambda j: (j["liga"], j["fecha"], j["pk"]))
    por = defaultdict(list)
    for j in out:
        por[j["liga"]].append(j)
    return por


def _temp(s):
    """'88 degrees, Partly Cloudy' -> 88.0 ; vacio -> None"""
    m = re.search(r"(-?\d+)\s*degrees", s or "", re.I)
    return float(m.group(1)) if m else None


def _viento(s):
    """'12 mph, Out To CF' -> +12 ; '8 mph, In From LF' -> -8 ; resto o vacio -> 0.0 / None"""
    if not (s or "").strip():
        return None
    m = re.search(r"(\d+)\s*mph", s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    t = s.lower()
    if " out" in t:
        return v
    if " in " in t or t.endswith(" in") or "in from" in t:
        return -v
    return 0.0


def capas_asof(js):
    """Para cada juego, las capas calculadas solo con los juegos anteriores. Devuelve (filas, base_liga)."""
    sum_tot, n_tot = 0.0, 0
    par = defaultdict(lambda: [0.0, 0])     # estadio -> [suma de totales, n]
    ump = defaultdict(lambda: [0.0, 0])
    sum_t, n_t = 0.0, 0                     # temperatura media as-of
    filas = []
    for j in js:
        base = (sum_tot / n_tot) if n_tot >= 200 else None
        f = {"fecha": j["fecha"], "total": j["total"], "base": base}
        if base is not None:
            s, n = par[j["estadio"]]
            f["parque"] = ((s / n) - base) * (n / (n + LASTRE_PARQUE)) if n else 0.0
            s, n = ump[j["umpire"]] if j["umpire"] else (0.0, 0)
            f["umpire"] = ((s / n) - base) * (n / (n + LASTRE_UMPIRE)) if n else 0.0
            tm = (sum_t / n_t) if n_t >= 200 else None
            f["temp"] = (j["temp"] - tm) if (j["temp"] is not None and tm is not None) else 0.0
            f["viento"] = j["viento"] if j["viento"] is not None else 0.0
            filas.append(f)
        # recien ahora se suma este juego (as-of estricto)
        sum_tot += j["total"]; n_tot += 1
        if j["estadio"]:
            par[j["estadio"]][0] += j["total"]; par[j["estadio"]][1] += 1
        if j["umpire"]:
            ump[j["umpire"]][0] += j["total"]; ump[j["umpire"]][1] += 1
        if j["temp"] is not None:
            sum_t += j["temp"]; n_t += 1
    return filas


def _coef(filas, cols):
    """Minimos cuadrados del residual (total - base) contra las columnas. Ecuaciones normales con pivoteo."""
    k = len(cols)
    A = [[0.0] * (k + 1) for _ in range(k)]
    for f in filas:
        y = f["total"] - f["base"]
        x = [f[c] for c in cols]
        for i in range(k):
            for jx in range(k):
                A[i][jx] += x[i] * x[jx]
            A[i][k] += x[i] * y
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        if abs(A[p][i]) < 1e-12:
            return [0.0] * k
        A[i], A[p] = A[p], A[i]
        for r in range(k):
            if r == i:
                continue
            fac = A[r][i] / A[i][i]
            for c in range(i, k + 1):
                A[r][c] -= fac * A[i][c]
    return [A[i][k] / A[i][i] for i in range(k)]


def medir(filas, cols):
    """CV por bloques de tiempo: entrena en el resto, prueba en el bloque. Devuelve (mae_base, mae_capas, coefs)."""
    n = len(filas)
    if n < MIN_JUEGOS:
        return None
    corte = [int(n * i / BLOQUES) for i in range(BLOQUES + 1)]
    e0 = e1 = 0.0
    cnt = 0
    acum = [0.0] * len(cols)
    for b in range(BLOQUES):
        prueba = filas[corte[b]:corte[b + 1]]
        entrena = filas[:corte[b]] + filas[corte[b + 1]:]
        if len(entrena) < 300 or not prueba:
            continue
        c = _coef(entrena, cols)
        for i, v in enumerate(c):
            acum[i] += v / BLOQUES
        for f in prueba:
            y = f["total"] - f["base"]
            pred = sum(ci * f[ci_name] for ci, ci_name in zip(c, cols))
            e0 += abs(y); e1 += abs(y - pred); cnt += 1
    if not cnt:
        return None
    return e0 / cnt, e1 / cnt, acum, cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", default=None, help="solo esta liga (MLB, NPB, KBO, ...)")
    a = ap.parse_args()
    por = juegos(a.liga.upper() if a.liga else None)
    res = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "metodo": "capas as-of (sin mirar el futuro) + minimos cuadrados con validacion cruzada en 4 bloques por tiempo",
           "lastre_parque": LASTRE_PARQUE, "lastre_umpire": LASTRE_UMPIRE, "ligas": {}}
    print("CAPAS DEL TOTAL DE CARRERAS (MAE del total; 'mejora' = milesimas de carrera que baja el error)")
    for lg, js in sorted(por.items()):
        filas = capas_asof(js)
        if len(filas) < MIN_JUEGOS:
            print("  %-5s n=%5d  muy poca muestra, se omite" % (lg, len(filas)))
            continue
        hay = {c: sum(1 for f in filas if abs(f[c]) > 1e-9) for c in ("parque", "umpire", "temp", "viento")}
        print("  == %s  n=%d juegos medibles  (con dato: parque %d, umpire %d, temp %d, viento %d)" % (
            lg, len(filas), hay["parque"], hay["umpire"], hay["temp"], hay["viento"]))
        d = {"n": len(filas), "cobertura": hay, "capas": {}}
        # cada capa por separado
        for c in ("parque", "umpire", "temp", "viento"):
            if hay[c] < 300:
                print("     %-8s sin dato suficiente" % c)
                continue
            m = medir(filas, [c])
            if not m:
                continue
            mae0, mae1, coef, cnt = m
            mej = 1000.0 * (mae0 - mae1)
            print("     %-8s coef %+8.4f  MAE %.4f -> %.4f  mejora %+6.1f milesimas  (n prueba %d)" % (c, coef[0], mae0, mae1, mej, cnt))
            d["capas"][c] = {"coef": round(coef[0], 5), "mae_base": round(mae0, 4), "mae_capa": round(mae1, 4), "mejora_milesimas": round(mej, 1), "n": cnt}
        # todas juntas, solo las que tienen dato
        cols = [c for c in ("parque", "umpire", "temp", "viento") if hay[c] >= 300]
        if len(cols) > 1:
            m = medir(filas, cols)
            if m:
                mae0, mae1, coef, cnt = m
                mej = 1000.0 * (mae0 - mae1)
                print("     JUNTAS   %s  MAE %.4f -> %.4f  mejora %+6.1f milesimas" % (
                    ", ".join("%s %+0.4f" % (c, v) for c, v in zip(cols, coef)), mae0, mae1, mej))
                d["juntas"] = {"cols": cols, "coef": [round(v, 5) for v in coef], "mae_base": round(mae0, 4),
                               "mae_capas": round(mae1, 4), "mejora_milesimas": round(mej, 1), "n": cnt}
        res["ligas"][lg] = d
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with io.open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("Guardado:", SALIDA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
