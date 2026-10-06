# -*- coding: utf-8 -*-
"""
nucleo/abridores.py - capa de abridores de KBO (box oficial de koreabaseball.com: datos/jugadores/kbo_lanzadores.csv).

Medido el 5-oct-2026 con utilidades/medir_abridores_kbo.py (walk-forward 24 meses, n=1383):
  Ganador: logit(p) + K x (carreras que salva el abridor local - las del visitante), K = 0.45.
           Skill contra la tasa base sube de +7.8 (z 1.58) a +16.3 milesimas (z 3.57, las dos mitades).
  Total esperado: cada abridor quita 0.25 x su valor a las carreras del rival (MAE z 5.4). O/U sin mejora.
Valor del abridor = (carreras permitidas por juego de su equipo - FIP del abridor encogido) x IP esperadas / 9.
"""
import csv, os

K_GANADOR = 0.45
ESCALA_TOTAL = 0.25
IP_PRIOR = 30.0

_CACHE = {}


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def _ruta(base):
    return os.path.join(base, "datos", "jugadores", "kbo_lanzadores.csv")


def _filas(base):
    ruta = _ruta(base)
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (r.get("game_date") or "", r.get("game_id") or ""))
    return rows


def _recorrer(rows, hasta=None):
    """Recorre los dias en orden. Devuelve (valores por (game_id, equipo) as-of, estado final: hist por jugador y liga)."""
    hist, out, por_fecha = {}, {}, {}
    liga = {"er": 0.0, "outs": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0}
    for r in rows:
        if hasta and (r.get("game_date") or "") >= hasta:
            continue
        por_fecha.setdefault(r["game_date"], []).append(r)
    for fch in sorted(por_fecha):
        dia = por_fecha[fch]
        for r in dia:
            if str(r.get("abridor")) == "1":
                out[(r["game_id"], r["team"])] = _valor(hist, liga, (r.get("jugador") or "").strip(), int(fch[:4]))
        for r in dia:
            nom = (r.get("jugador") or "").strip()
            o, k, bb, hr, er = (_f(r.get(c)) or 0.0 for c in ("outs", "k", "bb_hbp", "hr", "er"))
            liga["outs"] += o; liga["k"] += k; liga["bb"] += bb; liga["hr"] += hr; liga["er"] += er
            if str(r.get("abridor")) == "1":
                hist.setdefault(nom, []).append((int(fch[:4]), o, k, bb, hr))
    return out, hist, liga


def _valor(hist, liga, nom, temp):
    ip_l = liga["outs"] / 3.0
    cf = (9 * liga["er"] / ip_l - (13 * liga["hr"] + 3 * liga["bb"] - 2 * liga["k"]) / ip_l) if ip_l > 300 else 3.2
    lg_fip = (13 * liga["hr"] + 3 * liga["bb"] - 2 * liga["k"]) / ip_l + cf if ip_l > 300 else 4.6
    h = [x for x in hist.get(nom, []) if x[0] >= temp - 1]
    ip = sum(x[1] for x in h) / 3.0
    fip = ((13 * sum(x[4] for x in h) + 3 * sum(x[3] for x in h) - 2 * sum(x[2] for x in h)) / ip + cf) if ip > 0 else lg_fip
    fip_s = (ip * fip + IP_PRIOR * lg_fip) / (ip + IP_PRIOR)
    ip_esp = (ip + 5.0 * 5) / (len(h) + 5) if h else 5.0
    return (fip_s, ip_esp, len(h), lg_fip)


def historicos(base):
    """{(game_id, equipo): (fip_encogido, ip_esperadas, aperturas, fip_liga)} as-of, para la validacion."""
    k = ("hist", base)
    if k not in _CACHE:
        _CACHE[k] = _recorrer(_filas(base))[0]
    return _CACHE[k]


def actual(base, nombre, fecha):
    """(fip_encogido, ip_esperadas, aperturas, fip_liga) del abridor anunciado, con todo lo anterior a 'fecha'."""
    k = ("act", base, fecha)
    if k not in _CACHE:
        _, hist, liga = _recorrer(_filas(base), hasta=fecha)
        _CACHE[k] = (hist, liga)
    hist, liga = _CACHE[k]
    nom = (nombre or "").strip()
    if not nom or nom not in hist:
        return None
    return _valor(hist, liga, nom, int(fecha[:4]))


def carreras_salvadas(ra_equipo, v):
    """carreras que el abridor salva (+) o cuesta (-) contra el pitcheo de su equipo."""
    if v is None or ra_equipo is None:
        return 0.0
    return (ra_equipo - v[0]) * v[1] / 9.0
