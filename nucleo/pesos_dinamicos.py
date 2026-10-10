# -*- coding: utf-8 -*-
"""
nucleo/pesos_dinamicos.py - PESO DEL MODELO frente a Pinnacle decidido por los datos, por liga y mercado (10-oct-2026,
Alejandro: "tampoco me gusta darle tanto peso a Pinnacle... armalo").

    p_final = sig((1 - w) * logit(p_pinnacle) + w * logit(p_modelo))

w sale de utilidades/pesos_dinamicos.py (salida/pesos_dinamicos.json), que cada hora junta las predicciones del modelo con
la foto de Pinnacle que habia AL REGISTRARLAS (salida/clv_detalle.csv) y el resultado real, y busca el w que mejor predice.
Ese w se mezcla con el peso previo (el que tenia cada liga, respaldado por las pruebas historicas) en proporcion a la
muestra en vivo:  w = (n * w_vivo + N0 * w_previo) / (n + N0), N0 = 300. Con poca muestra manda el previo; con mucha, el
vivo. Asi el modelo gana peso solo donde acierta mas que Pinnacle y lo pierde donde no.
Solo stdlib.
"""
import json, os

from nucleo import io

N0 = 300
_CACHE = {}


def tabla(base=None):
    ruta = os.path.join(base or io.BASE, "salida", "pesos_dinamicos.json")
    if ruta not in _CACHE:
        try:
            _CACHE[ruta] = json.load(open(ruta, encoding="utf-8")).get("pesos") or {}
        except Exception:
            _CACHE[ruta] = {}
    return _CACHE[ruta]


def peso(liga, tipo, previo, base=None):
    """peso del modelo para (liga, Ganador|Total). previo = el peso fijo que tenia esa liga."""
    x = tabla(base).get("%s|%s" % ((liga or "").lower(), tipo))
    if not x or not x.get("n"):
        return previo
    n = x["n"]
    return (n * x["w_vivo"] + N0 * previo) / (n + N0)


def detalle(liga, tipo, previo, base=None):
    x = tabla(base).get("%s|%s" % ((liga or "").lower(), tipo)) or {}
    return {"peso": round(peso(liga, tipo, previo, base), 3), "previo": previo, "w_vivo": x.get("w_vivo"), "n_vivo": x.get("n", 0),
            "z_vivo": x.get("z")}
