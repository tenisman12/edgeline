# -*- coding: utf-8 -*-
"""
nucleo/mercado.py - la capa de mercado (sirve para TODOS los deportes).

Convierte una probabilidad del modelo + la cuota del book en una decision de apuesta:
  - pasa cuotas americanas/decimales a probabilidad,
  - quita el vig (margen del book) para tener la probabilidad JUSTA del mercado,
  - calcula el EDGE = prob_modelo - prob_justa,
  - calcula el stake KELLY (fraccional) para cada value bet.

Con esto no apuestas por accuracy, apuestas por VALOR: solo cuando tu probabilidad
supera a la del mercado por encima del vig.

Uso:
  from nucleo import mercado
  mercado.edge(0.58, -110)                 # edge de un pick vs una cuota
  mercado.value_bets(predicciones, cuotas) # marca los value bets del dia
"""
import math


# ---------------- conversiones ----------------
def american_a_decimal(o):
    o = float(o)
    return 1 + (o / 100.0 if o > 0 else 100.0 / -o)

def decimal_a_prob(dec):
    return 1.0 / float(dec) if dec else None

def prob_implicita(cuota_americana):
    """Probabilidad implicita CON vig de una cuota americana."""
    return decimal_a_prob(american_a_decimal(cuota_americana))


# ---------------- quitar el vig ----------------
def sin_vig(probs):
    """Normaliza una lista de probs implicitas (que suman >1 por el vig) para que
    sumen 1: da la probabilidad JUSTA que el mercado le asigna a cada lado.
    Sirve para 2 vias (ML beisbol/hockey, over/under) y 3 vias (1X2 futbol)."""
    s = sum(p for p in probs if p)
    if not s:
        return probs
    return [(p / s if p else None) for p in probs]

def prob_justa_2(cuota_a, cuota_b):
    """Prob justa del lado A en un mercado de 2 vias (A vs B)."""
    pa, pb = prob_implicita(cuota_a), prob_implicita(cuota_b)
    return sin_vig([pa, pb])[0]


# ---------------- edge y kelly ----------------
def edge(prob_modelo, cuota_americana, cuota_rival=None):
    """
    Edge = prob_modelo - prob_justa_del_mercado.
    Si das la cuota del rival, se quita el vig con ambas (mas exacto). Si no, se usa
    la implicita con vig (edge un poco subestimado, conservador).
    """
    if cuota_rival is not None:
        pj = prob_justa_2(cuota_americana, cuota_rival)
    else:
        pj = prob_implicita(cuota_americana)
    return None if pj is None else prob_modelo - pj

def kelly(prob_modelo, cuota_americana, fraccion=0.25, tope=0.05):
    """
    Fraccion del bankroll a apostar (Kelly fraccional, con tope de seguridad).
    b = ganancia decimal-1; f* = (b*p - (1-p)) / b. Multiplicado por 'fraccion'.
    Devuelve 0 si no hay valor.
    """
    dec = american_a_decimal(cuota_americana)
    b = dec - 1
    p = prob_modelo
    f = (b * p - (1 - p)) / b if b > 0 else 0.0
    return max(0.0, min(f * fraccion, tope))


# ---------------- aplicar a las predicciones del dia ----------------
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def value_bets(predicciones, umbral_edge=0.03, fraccion_kelly=0.25):
    """
    predicciones: lista de dicts con AL MENOS:
        league, away, home, p_home   (prob del local, ya calibrada)
      opcionalmente para totales:
        p_over, total_line
      y las cuotas (de hoy.csv):
        ml_home, ml_away, over, under
    Devuelve la misma lista, anotando por pick:
        edge_ml_home / edge_ml_away / edge_over / edge_under, su kelly, y 'apuestas'
        = lista de value bets (edge >= umbral) ordenables.
    """
    salida = []
    for r in predicciones:
        o = dict(r)
        apuestas = []
        ph = _num(r.get("p_home"))
        mlh, mla = r.get("ml_home"), r.get("ml_away")
        # --- moneyline ---
        if ph is not None and _num(mlh) is not None and _num(mla) is not None:
            e_h = edge(ph, mlh, mla)
            e_a = edge(1 - ph, mla, mlh)
            o["edge_ml_home"], o["edge_ml_away"] = e_h, e_a
            if e_h is not None and e_h >= umbral_edge:
                apuestas.append({"mercado": "ML", "sel": r.get("home"), "cuota": mlh,
                                 "edge": round(e_h, 4), "kelly": round(kelly(ph, mlh, fraccion_kelly), 4)})
            if e_a is not None and e_a >= umbral_edge:
                apuestas.append({"mercado": "ML", "sel": r.get("away"), "cuota": mla,
                                 "edge": round(e_a, 4), "kelly": round(kelly(1 - ph, mla, fraccion_kelly), 4)})
        # --- total (over/under) ---
        po = _num(r.get("p_over"))
        ov, un = r.get("over"), r.get("under")
        if po is not None and _num(ov) is not None and _num(un) is not None:
            e_o = edge(po, ov, un)
            e_u = edge(1 - po, un, ov)
            o["edge_over"], o["edge_under"] = e_o, e_u
            lin = r.get("total_line")
            if e_o is not None and e_o >= umbral_edge:
                apuestas.append({"mercado": "OVER %s" % lin, "sel": "Over", "cuota": ov,
                                 "edge": round(e_o, 4), "kelly": round(kelly(po, ov, fraccion_kelly), 4)})
            if e_u is not None and e_u >= umbral_edge:
                apuestas.append({"mercado": "UNDER %s" % lin, "sel": "Under", "cuota": un,
                                 "edge": round(e_u, 4), "kelly": round(kelly(1 - po, un, fraccion_kelly), 4)})
        o["apuestas"] = apuestas
        salida.append(o)
    return salida


def imprimir(predicciones, umbral_edge=0.03):
    vb = value_bets(predicciones, umbral_edge)
    todos = []
    for r in vb:
        for a in r.get("apuestas", []):
            todos.append((r.get("league"), r.get("away"), r.get("home"), a))
    todos.sort(key=lambda t: -t[3]["edge"])
    if not todos:
        print("Sin value bets sobre el umbral (%.0f%%) hoy." % (100 * umbral_edge)); return
    print("VALUE BETS (edge >= %.0f%%)  -- ordenados por edge" % (100 * umbral_edge))
    print("-" * 74)
    print("%-7s %-26s %-14s %7s %6s %6s" % ("LIGA", "PARTIDO", "APUESTA", "CUOTA", "EDGE", "KELLY"))
    print("-" * 74)
    for lg, a, h, ap in todos:
        print("%-7s %-26s %-14s %7s %5.1f%% %5.1f%%" %
              (lg, "%s @ %s" % (a, h), "%s %s" % (ap["mercado"], ap["sel"]),
               ap["cuota"], 100 * ap["edge"], 100 * ap["kelly"]))
    print("-" * 74)
    print("EDGE = tu prob menos la del mercado sin vig. KELLY = %% del bankroll sugerido.")


if __name__ == "__main__":
    # demo con numeros de ejemplo
    demo = [{"league": "MLB", "away": "Red Sox", "home": "Yankees", "p_home": 0.60,
             "ml_home": -130, "ml_away": +110, "p_over": 0.56, "total_line": 8.5,
             "over": -105, "under": -115}]
    imprimir(demo, umbral_edge=0.02)
