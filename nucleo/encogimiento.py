"""Priors de anotación por liga, con candidatos aislados de producción.

Un k equivale a pseudopartidos del promedio de liga. 'referencia' permite
comparar la tasa cruda y el candidato dentro del modelo completo; no cambia
los picks ni las probabilidades publicadas. Solo MLB está habilitada.
"""

BASE = {"beisbol": 6.0, "hockey": 12.0, "americano": 6.0,
        "nba": 8.0, "futbol": 6.0}

# Candidatos exploratorios. No todos se compararon con k=0 ni con el motor
# publicado; por ello solo se habilitan despues de la prueba del motor entero.
CANDIDATOS = {
    "beisbol": {"mlb": 100.0, "kbo": 200.0, "npb": 150.0, "lmp": 100.0},
    "hockey": {"nhl": 20.0, "ahl": 30.0, "del": 15.0, "liiga": 30.0},
    "americano": {"nfl": 5.0, "ncaafb": 0.0},
    "nba": {"nba": 8.0},
    "futbol": {"ligamx": 10.0, "mls": 20.0,
               "ligue1": 8.0, "bundesliga": 10.0, "laliga": 8.0,
               "premier": 8.0, "seriea": 5.0},
}

# Solo hubo evidencia directa favorable en el ensamble publicado para MLB.
HABILITADOS = {("beisbol", "mlb")}


def k(deporte, liga, referencia=False):
    """Devuelve k de producción o, si se solicita, el candidato de investigación.

    None indica que no se probó una regla equivalente (por ejemplo, tenis).
    """
    deporte = str(deporte or "").lower()
    liga = str(liga or "").lower()
    base = BASE.get(deporte)
    if base is None:
        return None
    candidato = CANDIDATOS.get(deporte, {}).get(liga, base)
    if referencia or (deporte, liga) in HABILITADOS:
        return candidato
    return base


def estado(deporte, liga):
    """Motivo legible para mostrar junto a la proyección auxiliar."""
    llave = (str(deporte or "").lower(), str(liga or "").lower())
    if llave in HABILITADOS:
        return "habilitado"
    if llave[1] in CANDIDATOS.get(llave[0], {}):
        return "solo_referencia"
    return "sin_prueba"


def ficha(deporte, liga):
    """Metadatos auditables para una proyeccion auxiliar por liga."""
    d = str(deporte or "").lower()
    l = str(liga or "").lower()
    return {"deporte": d, "liga": l, "k_base": BASE.get(d),
            "k_candidato": CANDIDATOS.get(d, {}).get(l),
            "k_publicado": k(d, l), "estado": estado(d, l)}
