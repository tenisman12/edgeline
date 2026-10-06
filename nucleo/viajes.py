# -*- coding: utf-8 -*-
"""
nucleo/viajes.py - arenas de NHL y NBA (coordenadas y huso horario estandar) y el viaje de cada equipo entre partidos.

viaje(historial, equipo, fecha, sede) -> {"km": km desde la sede del partido anterior, "husos": cambio de huso (+ = hacia
el este), "dias": dias desde el partido anterior}. La sede de un partido es la arena del local. Partidos en sede neutral
(Global Series, etc.) se toman como si fueran en la arena del local: error chico y raro.
"""
import math

# (lat, lon, huso estandar UTC)
NHL = {"ANA": (33.808, -117.877, -8), "ARI": (33.532, -112.261, -7), "BOS": (42.366, -71.062, -5), "BUF": (42.875, -78.876, -5),
       "CAR": (35.803, -78.722, -5), "CBJ": (39.969, -83.006, -5), "CGY": (51.037, -114.052, -7), "CHI": (41.881, -87.674, -6),
       "COL": (39.749, -105.008, -7), "DAL": (32.790, -96.810, -6), "DET": (42.341, -83.055, -5), "EDM": (53.547, -113.498, -7),
       "FLA": (26.158, -80.326, -5), "LAK": (34.043, -118.267, -8), "MIN": (44.945, -93.101, -6), "MTL": (45.496, -73.569, -5),
       "NJD": (40.734, -74.171, -5), "NSH": (36.159, -86.778, -6), "NYI": (40.723, -73.590, -5), "NYR": (40.750, -73.993, -5),
       "OTT": (45.297, -75.927, -5), "PHI": (39.901, -75.172, -5), "PIT": (40.439, -79.989, -5), "SEA": (47.622, -122.354, -8),
       "SJS": (37.333, -121.901, -8), "STL": (38.627, -90.203, -6), "TBL": (27.943, -82.452, -5), "TOR": (43.643, -79.379, -5),
       "UTA": (40.768, -111.901, -7), "VAN": (49.278, -123.109, -8), "VGK": (36.103, -115.178, -8), "WPG": (49.893, -97.144, -6),
       "WSH": (38.898, -77.021, -5)}
NBA = {"ATL": (33.757, -84.396, -5), "BKN": (40.683, -73.976, -5), "BOS": (42.366, -71.062, -5), "CHA": (35.225, -80.839, -5),
       "CHI": (41.881, -87.674, -6), "CLE": (41.497, -81.688, -5), "DAL": (32.790, -96.810, -6), "DEN": (39.749, -105.008, -7),
       "DET": (42.341, -83.055, -5), "GSW": (37.768, -122.388, -8), "HOU": (29.751, -95.362, -6), "IND": (39.764, -86.155, -5),
       "LAC": (33.945, -118.343, -8), "LAL": (34.043, -118.267, -8), "MEM": (35.138, -90.051, -6), "MIA": (25.781, -80.188, -5),
       "MIL": (43.045, -87.917, -6), "MIN": (44.979, -93.276, -6), "NOP": (29.949, -90.082, -6), "NYK": (40.750, -73.993, -5),
       "OKC": (35.463, -97.515, -6), "ORL": (28.539, -81.384, -5), "PHI": (39.901, -75.172, -5), "PHX": (33.446, -112.071, -7),
       "POR": (45.532, -122.667, -8), "SAC": (38.580, -121.500, -8), "SAS": (29.427, -98.437, -6), "TOR": (43.643, -79.379, -5),
       "UTA": (40.768, -111.901, -7), "WAS": (38.898, -77.021, -5)}
ARENAS = {"nhl": NHL, "nba": NBA}


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


class Historial:
    """Recorre los partidos en orden; por equipo guarda (fecha, sede) del ultimo partido."""
    def __init__(self, liga):
        self.A = ARENAS[liga]; self.ult = {}

    def antes(self, equipo, fecha, sede_local):
        """viaje del equipo hasta un partido en la arena de sede_local (abreviatura del local)."""
        import datetime as dt
        u = self.ult.get(equipo)
        s = self.A.get(sede_local)
        if not u or not s or u[1] not in self.A:
            return None
        p = self.A[u[1]]
        try:
            dias = (dt.date.fromisoformat(fecha[:10]) - dt.date.fromisoformat(u[0][:10])).days
        except ValueError:
            return None
        return {"km": km(p, s), "husos": s[2] - p[2], "dias": dias}

    def jugar(self, equipo, fecha, sede_local):
        self.ult[equipo] = (fecha, sede_local)
