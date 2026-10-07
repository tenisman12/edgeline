# -*- coding: utf-8 -*-
"""
nucleo/parques.py - capa de PARQUE y CLIMA para el total de carreras de beisbol.

Por que: el total de beisbol no pasa validacion walk-forward en ninguna liga (MLB skill -0.86%, NPB -0.04%,
KBO +0.12%). El modelo reparte carreras con las ofensivas y el abridor y no sabe donde se juega. Medido el
6-oct-2026 (utilidades/capas_totales_beisbol.py -> modelos/capas_totales_beisbol.json), as-of walk-forward con
validacion cruzada en 4 bloques, el factor de parque por EQUIPO LOCAL baja el MAE del total:
  MLB +26.9 milesimas de carrera (coef 1.072), NPB +28.0 (1.073), KBO +8.3 (0.873), LMP +95.6 (1.616).
  Con temperatura y viento donde hay dato: MLB +33.6 milesimas, LMP +110.0.
  LVBP sale negativo en todo: no se aplica.
El umpire quedo en cero (coef 0.111, mejora -0.2 milesimas) y se descarto; coincide con modelos/clima_mlb.json,
que lo midio por otro camino y dio -0.0075 de MAE con z -2.25.

Como funciona: el factor de un parque es (carreras por juego en ese parque) - (carreras por juego de la liga),
calculado SOLO con juegos anteriores, y encogido hacia cero por tamano de muestra con 60 juegos de lastre. Se
usa el equipo local como llave (cada equipo tiene un parque y la fila del modelo trae 'home', no 'estadio').

    from nucleo import parques
    H = parques.historicos(BASE, "mlb")              # {(gamePk, equipo_local): (factor, temp, viento)}
    f = parques.actual(BASE, "mlb", "Los Angeles Dodgers", "2026-10-07")
    xh, xa = parques.ajustar(xh, xa, "mlb", factor=f[0], temp=f[1], viento=f[2])

Solo stdlib.
"""
import csv, json, os, re

LASTRE = 60.0           # juegos de lastre del encogimiento (el mismo de la medicion)
MIN_LIGA = 200          # juegos de la liga antes de empezar a dar factor
RUTA = ("datos", "beisbol.csv")
_CACHE = {}
_COEF = None


def _coeficientes():
    """{liga: {parque, temp, viento}} desde modelos/capas_totales_beisbol.json. Solo las que mejoran el MAE."""
    global _COEF
    if _COEF is None:
        _COEF = {}
        try:
            ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "modelos", "capas_totales_beisbol.json")
            with open(ruta, encoding="utf-8") as f:
                d = json.load(f)
            for lg, o in (d.get("ligas") or {}).items():
                c = {}
                j = o.get("juntas") or {}
                # se prefiere la combinacion medida junta; si no mejora, se cae a la capa de parque sola
                if (j.get("mejora_milesimas") or 0) > 0 and j.get("cols"):
                    for nom, v in zip(j["cols"], j["coef"]):
                        c[nom.replace("parque_local", "parque")] = float(v)
                else:
                    p = (o.get("capas") or {}).get("parque_local") or (o.get("capas") or {}).get("parque") or {}
                    if (p.get("mejora_milesimas") or 0) > 0:
                        c["parque"] = float(p.get("coef") or 0.0)
                if c:
                    _COEF[lg.lower()] = c
        except Exception:
            _COEF = {}
    return _COEF


def aplica(liga):
    return (liga or "").lower() in _coeficientes()


def _temp(s):
    m = re.search(r"(-?\d+)\s*degrees", s or "", re.I)
    return float(m.group(1)) if m else None


def _viento(s):
    """'12 mph, Out To CF' -> +12 (empuja carreras); 'In From LF' -> -12; cruzado o sin dato -> 0 / None."""
    if not (s or "").strip():
        return None
    m = re.search(r"(\d+)\s*mph", s, re.I)
    if not m:
        return None
    v = float(m.group(1)); t = s.lower()
    if " out" in t:
        return v
    if " in " in t or t.endswith(" in") or "in from" in t:
        return -v
    return 0.0


def _juegos(base, liga):
    """Un registro por juego de la liga, en orden de fecha: (fecha, gamePk, local, total, temp, viento)."""
    lg = (liga or "").upper()
    vistos = {}
    ruta = os.path.join(base, *RUTA)
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("league") or "").upper() != lg:
                continue
            pk = str(r.get("gamePk") or "")
            if pk in vistos:
                continue
            try:
                total = float(r["runs"]) + float(r["runs_opp"])
            except (TypeError, ValueError, KeyError):
                continue
            local = (r.get("team") if str(r.get("is_home")).lower() in ("true", "1") else r.get("opp")) or ""
            vistos[pk] = ((r.get("game_date") or "")[:10], pk, local, total, _temp(r.get("clima")), _viento(r.get("viento")))
    return sorted(vistos.values())


def _recorrer(base, liga, hasta=None):
    """Devuelve (as_of por (gamePk, local), estado final por equipo, media de temperatura de la liga).
    as-of estricto: el factor de un juego usa solo juegos ANTERIORES."""
    suma = 0.0; n = 0
    st = {}                     # equipo -> [suma, n]
    s_t = 0.0; n_t = 0
    out = {}
    for fch, pk, local, total, temp, vto in _juegos(base, liga):
        if hasta and fch >= hasta:
            break
        base_lg = (suma / n) if n >= MIN_LIGA else None
        if base_lg is not None and local in st:
            s, k = st[local]
            fac = ((s / k) - base_lg) * (k / (k + LASTRE)) if k else 0.0
            tm = (s_t / n_t) if n_t >= MIN_LIGA else None
            out[(pk, local)] = (fac, (temp - tm) if (temp is not None and tm is not None) else 0.0,
                                vto if vto is not None else 0.0)
        suma += total; n += 1
        if local:
            a = st.setdefault(local, [0.0, 0]); a[0] += total; a[1] += 1
        if temp is not None:
            s_t += temp; n_t += 1
    return out, st, ((suma / n) if n else None), ((s_t / n_t) if n_t >= MIN_LIGA else None)


def historicos(base, liga):
    """{(gamePk, equipo_local): (factor, temp_centrada, viento)} as-of, para la validacion walk-forward."""
    k = ("hist", base, (liga or "").lower())
    if k not in _CACHE:
        _CACHE[k] = _recorrer(base, liga)[0]
    return _CACHE[k]


def actual(base, liga, equipo_local, hasta=None, temp=None, viento=None):
    """(factor, temp_centrada, viento) del parque de ese equipo con todo lo anterior a 'hasta'.
    temp y viento se pasan del partido por jugar (los trae el clima de plataforma); si faltan, van en 0."""
    k = ("act", base, (liga or "").lower(), hasta or "")
    if k not in _CACHE:
        _, st, base_lg, tm = _recorrer(base, liga, hasta=hasta)
        _CACHE[k] = (st, base_lg, tm)
    st, base_lg, tm = _CACHE[k]
    if base_lg is None or equipo_local not in st:
        return 0.0, 0.0, 0.0
    s, n = st[equipo_local]
    fac = ((s / n) - base_lg) * (n / (n + LASTRE)) if n else 0.0
    t = (temp - tm) if (temp is not None and tm is not None) else 0.0
    return fac, t, (viento if viento is not None else 0.0)


def delta(liga, factor=0.0, temp=0.0, viento=0.0):
    """Carreras que la capa suma al TOTAL esperado (puede ser negativa). 0 si la liga no tiene coeficiente."""
    c = _coeficientes().get((liga or "").lower())
    if not c:
        return 0.0
    return (c.get("parque", 0.0) * factor + c.get("temp", 0.0) * temp + c.get("viento", 0.0) * viento)


def ajustar(xh, xa, liga, factor=0.0, temp=0.0, viento=0.0):
    """Reparte el delta entre local y visita en proporcion a lo que ya anotan. No baja de 0.3 por lado."""
    d = delta(liga, factor, temp, viento)
    if not d or xh is None or xa is None:
        return xh, xa
    tot = xh + xa
    if tot <= 0:
        return xh, xa
    return max(xh + d * (xh / tot), 0.3), max(xa + d * (xa / tot), 0.3)
