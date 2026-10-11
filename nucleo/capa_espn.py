# -*- coding: utf-8 -*-
"""
nucleo/capa_espn.py - capa del predictor de ESPN (BPI / FPI) sobre el ganador del modelo (tanda 9, 10-oct-2026, aprobada por
Alejandro: "aplicalo").

    logit p = logit p_modelo + beta_liga * (logit p_ESPN - logit p_modelo)

beta por liga en modelos/capa_espn.json (NCAAMB 0.838, NCAAF 0.886, NBA 0.651; offset logistico en toda la muestra contra la
p as-of del modelo; prueba 70/30: NCAAMB z 9.10, NCAAF 4.66, NBA 3.87). p_ESPN = proyeccion de ESPN guardada ANTES del juego
por colectores/recolectar_predictor_espn.py --vivo (salida/espn_predictor_vivo.csv). Sin proyeccion, p = p_modelo.
NFL no: contra el mercado va al reves y en NFL p final = Pinnacle. Solo stdlib.
"""
import csv, io as _io, json, math, os

from nucleo import io

_CFG = None
_VIVO = None


def _cfg():
    global _CFG
    if _CFG is None:
        try:
            _CFG = json.load(open(io.ruta("modelos", "capa_espn.json"), encoding="utf-8")).get("ligas") or {}
        except Exception:
            _CFG = {}
    return _CFG


def _vivo():
    global _VIVO
    if _VIVO is None:
        _VIVO = {}
        ruta = io.ruta("salida", "espn_predictor_vivo.csv")
        if os.path.exists(ruta):
            with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        ph = float(r["p_local"]) if r.get("p_local") not in (None, "") else None
                        pa = float(r["p_visita"]) if r.get("p_visita") not in (None, "") else None
                    except ValueError:
                        continue
                    if ph is None and pa is None:
                        continue
                    _VIVO[(r["liga"], str(r["game_id"]))] = dict(p=(ph if ph is not None else 100 - pa) / 100.0,
                                                                 registrado=r.get("registrado"))
    return _VIVO


def aplicar(p_home, liga, game_id):
    """-> (p, detalle)."""
    lg = (liga or "").lower()
    c = _cfg().get(lg)
    if not c:
        return p_home, None
    v = _vivo().get((lg, str(game_id)))
    if not v:
        return p_home, {"aplicado": False, "motivo": "sin proyeccion de ESPN antes del juego"}
    lgt = lambda q: math.log(min(max(q, 1e-4), 1 - 1e-4) / (1 - min(max(q, 1e-4), 1 - 1e-4)))
    p0, pe = p_home, v["p"]
    p1 = 1 / (1 + math.exp(-(lgt(p0) + c["beta"] * (lgt(pe) - lgt(p0)))))
    return p1, {"aplicado": True, "p_espn": round(pe, 4), "p_sin_capa": round(p0, 4), "beta": c["beta"],
                "ajuste_pp": round(100 * (p1 - p0), 1), "foto_espn": v.get("registrado"),
                "fuente": "modelos/capa_espn.json (tanda 9, aprobada 10-oct-2026)"}
