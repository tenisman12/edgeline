# -*- coding: utf-8 -*-
"""
utilidades/pesos_dinamicos.py - estima, con lo que va pasando en vivo, cuanto debe pesar el modelo frente a Pinnacle en
cada liga y mercado (nucleo/pesos_dinamicos.py lo aplica en decidir_v2 y decidir.py).

Datos: cada prediccion del modelo (salida/clv_detalle.csv, lista 'modelo': p_modelo y p_registro = Pinnacle sin vig en la
foto vigente al registrar) con su resultado (salida/historial_predicciones_calificado.csv). Para cada (liga, mercado):
  w_vivo = el w en [0, 1] (pasos de 0.05) que maximiza la verosimilitud de p = sig((1-w) logit p_pinnacle + w logit p_modelo)
  z      = mejora de log loss de w_vivo contra w = 0 (solo Pinnacle), con su z; mitades.
El peso que se usa mezcla w_vivo con el previo de la liga segun la muestra (N0 = 300). Corre cada hora (cuotas.yml).
Escribe salida/pesos_dinamicos.json.

    cd C:\\Edgeline_repo
    python utilidades\\pesos_dinamicos.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, datetime as dt, json, math, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io  # noqa: E402
from nucleo import pesos_dinamicos as PD  # noqa: E402


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _leer(nombre):
    ruta = io.ruta("salida", nombre)
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def datos():
    res = {}
    for r in _leer("historial_predicciones_calificado.csv"):
        if r.get("estado") == "calificado" and r.get("acierto") in ("0", "1"):
            res[(r["liga"], r["fecha"], r["home"], r["away"], (r["mercado"] or "").split()[0], r["lado"], r["mercado"])] = int(r["acierto"])
    out = []
    for r in _leer("clv_detalle.csv"):
        if r.get("lista") != "modelo":
            continue
        pm, pp = _f(r.get("p_modelo")), _f(r.get("p_registro"))
        if pm is None or pp is None:
            continue
        k = (r["liga"], r["fecha"], r["home"], r["away"], (r["mercado"] or "").split()[0], r["lado"], r["mercado"])
        y = res.get(k)
        if y is None:
            continue
        out.append(dict(liga=r["liga"], tipo=k[4], fecha=r["fecha"], registrado=r.get("registrado"), pm=pm, pp=pp, y=y))
    out.sort(key=lambda x: (x["fecha"], x["registrado"] or ""))
    return out


def estimar(F):
    mejor = None
    for i in range(21):
        w = i / 20.0
        s = sum(_ll(1 / (1 + math.exp(-((1 - w) * _lg(x["pp"]) + w * _lg(x["pm"])))), x["y"]) for x in F)
        if mejor is None or s < mejor[0]:
            mejor = (s, w)
    w = mejor[1]
    d = [_ll(x["pp"], x["y"]) - _ll(1 / (1 + math.exp(-((1 - w) * _lg(x["pp"]) + w * _lg(x["pm"])))), x["y"]) for x in F]
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / max(n - 1, 1)) or 1e-12
    h = n // 2
    return {"w_vivo": w, "n": n, "mejora_milesimas": round(1000 * m, 3), "z": round(m / (sd / math.sqrt(n)), 2),
            "mitades": [round(1000 * sum(d[:h]) / max(h, 1), 3), round(1000 * sum(d[h:]) / max(n - h, 1), 3)],
            "brier_pinnacle": round(sum((x["pp"] - x["y"]) ** 2 for x in F) / n, 4),
            "brier_modelo": round(sum((x["pm"] - x["y"]) ** 2 for x in F) / n, 4)}


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "utilidades"))
    try:
        import decidir_v2 as V2
        previos = dict(V2.PESO_MODELO); defecto = V2.PESO_DEFAULT
    except Exception:
        previos, defecto = {}, 0.25
    F = datos()
    grupos = defaultdict(list)
    for x in F:
        grupos[(x["liga"], x["tipo"])].append(x)
    pesos = {}
    print("PESO DEL MODELO FRENTE A PINNACLE, en vivo (%d predicciones con foto de Pinnacle y resultado)" % len(F))
    print("%-8s %-8s %5s %7s %8s %7s %9s %9s %8s" % ("liga", "mercado", "n", "w_vivo", "mejora", "z", "previo", "w usado", "Brier P/M"))
    for (lg, tipo), G in sorted(grupos.items(), key=lambda t: -len(t[1])):
        if len(G) < 20:
            continue
        e = estimar(G)
        pesos["%s|%s" % (lg, tipo)] = e
        previo = 0.25 if lg in ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl") and tipo == "Ganador" else previos.get(lg, defecto)
        e["previo"] = previo
        e["w_usado"] = round((e["n"] * e["w_vivo"] + PD.N0 * previo) / (e["n"] + PD.N0), 3)
        print("%-8s %-8s %5d %7.2f %+8.3f %+7.2f %9.2f %9.3f %.3f/%.3f" % (lg, tipo, e["n"], e["w_vivo"], e["mejora_milesimas"], e["z"],
                                                                         previo, e["w_usado"], e["brier_pinnacle"], e["brier_modelo"]))
    out = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "n0": PD.N0,
           "como_leer": "w_vivo = peso del modelo que mejor predice en vivo (0 = solo Pinnacle, 1 = solo modelo); el peso que se usa = "
                        "(n * w_vivo + n0 * previo) / (n + n0). z = mejora de log loss de w_vivo contra Pinnacle solo.",
           "pesos": pesos}
    with open(io.ruta("salida", "pesos_dinamicos.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("escrito salida/pesos_dinamicos.json")


if __name__ == "__main__":
    main()
