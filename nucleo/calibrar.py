# -*- coding: utf-8 -*-
"""
PASO 5b - nucleo/calibrar.py

UN Platt scaling para cualquier modelo. Reemplaza kbo_calibrar.py y demas.
Toma predicciones out-of-sample (las que produce nucleo/evaluar en walk-forward)
y ajusta (a, b) tal que:

    p_calibrada = sigmoid( a * logit(p_modelo) + b )

minimice el logloss. Corrige el exceso/falta de confianza del modelo (p. ej. cuando
predice 70% pero en realidad gana 60%). Guarda/lee los parametros por deporte.

Uso normal: lo llama nucleo/evaluar.correr(). Directo:
    from nucleo import calibrar
    a, b = calibrar.ajustar(preds)          # preds = [{"p":..,"y":..}, ...]
    p2 = calibrar.aplicar(p, a, b)
    calibrar.guardar("beisbol", a, b); a,b = calibrar.cargar("beisbol")
"""
import io as _io, os, json, math

try:
    from nucleo import io as EIO
    BASE = EIO.BASE
except Exception:
    BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")

DIR = os.path.join(BASE, "nucleo", "_calib")


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))

def _sig(z):
    if z < -35: return 0.0
    if z > 35:  return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def ajustar(preds, iters=800, lr=0.05):
    """Ajusta (a, b) por descenso de gradiente sobre logloss. a~1,b~0 = sin cambio."""
    X = [_logit(d["p"]) for d in preds]
    Y = [d["y"] for d in preds]
    n = len(X)
    if n < 50:
        return 1.0, 0.0
    a, b = 1.0, 0.0
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(X, Y):
            p = _sig(a * x + b)
            e = p - y
            ga += e * x; gb += e
        a -= lr * ga / n; b -= lr * gb / n
    return a, b


def aplicar(p, a, b):
    return _sig(a * _logit(p) + b)


def guardar(deporte, a, b, liga=None):
    os.makedirs(DIR, exist_ok=True)
    nombre = "%s%s.json" % (deporte, ("_" + liga) if liga else "")
    with _io.open(os.path.join(DIR, nombre), "w", encoding="utf-8") as f:
        json.dump({"a": a, "b": b}, f)
    return os.path.join(DIR, nombre)


def cargar(deporte, liga=None):
    nombre = "%s%s.json" % (deporte, ("_" + liga) if liga else "")
    ruta = os.path.join(DIR, nombre)
    if not os.path.exists(ruta):
        return 1.0, 0.0
    with _io.open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("a", 1.0), d.get("b", 0.0)


# --- peso del ensamble (logistica vs carreras) por liga ---
def guardar_w(deporte, liga, w):
    os.makedirs(DIR, exist_ok=True)
    with _io.open(os.path.join(DIR, "w_%s_%s.json" % (deporte, liga)), "w", encoding="utf-8") as f:
        json.dump({"w": w}, f)

def cargar_w(deporte, liga, default=0.5):
    ruta = os.path.join(DIR, "w_%s_%s.json" % (deporte, liga))
    if not os.path.exists(ruta):
        return default
    try:
        with _io.open(ruta, encoding="utf-8") as f:
            return json.load(f).get("w", default)
    except Exception:
        return default
