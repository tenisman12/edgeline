# -*- coding: utf-8 -*-
"""
modelos/futbol_mercados.py - TODOS los mercados de futbol derivados del mismo modelo.

Del modelo de marcador (matriz P de Dixon-Coles, ya ensamblado con ELO en el 1X2)
salen, sin modelos nuevos ni datos extra:
  1X2, doble oportunidad (1X, X2, 12), Ambos Anotan (AA/BTTS), Over/Under 1.5-2.5-3.5,
  ganar por 2+ (hándicap -1.5 / +1.5), marcador exacto (top).
Con tasas por equipo salen ademas: primer tiempo (1X2 1T, over 0.5/1.5 1T),
corners (over/under) y tarjetas (over/under).

Cada mercado se valida en utilidades/validar_futbol_mercados.py (as-of vs linea base)
y queda 'publicable' o 'sin_validar'. Aqui solo estan las formulas. Solo stdlib.
"""
import math


def _pois(mu, k):
    return math.exp(-mu) * mu ** k / math.factorial(k)


def desde_matriz(P, ph, pd, pa):
    """P[i][j] = prob. local i goles, visita j goles. ph/pd/pa: 1X2 final (ensamblado)."""
    k = len(P)
    tot = {}
    for i in range(k):
        for j in range(k):
            tot[i + j] = tot.get(i + j, 0.0) + P[i][j]
    aa = sum(P[i][j] for i in range(1, k) for j in range(1, k))
    def over(l):
        return 1 - sum(v for t, v in tot.items() if t <= l)
    m2h = sum(P[i][j] for i in range(k) for j in range(k) if i - j >= 2)
    m2a = sum(P[i][j] for i in range(k) for j in range(k) if j - i >= 2)
    marc = sorted(((P[i][j], i, j) for i in range(k) for j in range(k)), reverse=True)[:5]
    return {
        "1": ph, "X": pd, "2": pa,
        "1X": ph + pd, "X2": pd + pa, "12": ph + pa,
        "aa_si": aa, "aa_no": 1 - aa,
        "over_1.5": over(1), "over_2.5": over(2), "over_3.5": over(3),
        "under_1.5": 1 - over(1), "under_2.5": 1 - over(2), "under_3.5": 1 - over(3),
        "local_gana_por_2": m2h, "visita_gana_por_2": m2a,
        "marcadores_top": [{"marcador": "%d-%d" % (i, j), "p": round(p, 4)} for p, i, j in marc],
    }


def primer_tiempo(xh, xa, f):
    """f = fraccion de goles que cae en el 1T (de los datos de la liga). Poisson independiente."""
    a, b = xh * f, xa * f
    k = 7
    ph = pd = pa = 0.0
    for i in range(k):
        for j in range(k):
            p = _pois(a, i) * _pois(b, j)
            if i > j: ph += p
            elif i == j: pd += p
            else: pa += p
    s = ph + pd + pa
    t = a + b
    return {"1T_1": ph / s, "1T_X": pd / s, "1T_2": pa / s,
            "1T_over_0.5": 1 - math.exp(-t), "1T_over_1.5": 1 - math.exp(-t) * (1 + t)}


def conteo(mu, lineas):
    """Over/Under de un conteo (corners, tarjetas) con Poisson de media mu."""
    out = {}
    for l in lineas:
        piso = int(math.floor(l))
        c = sum(_pois(mu, k) for k in range(piso + 1))
        out["over_%s" % l] = 1 - c
        out["under_%s" % l] = c
    return out
