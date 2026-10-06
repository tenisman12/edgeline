# -*- coding: utf-8 -*-
"""
nucleo/velocidad_tenis.py - capa de velocidad del torneo y saque por superficie para los BREAKS de tenis.

Medido el 6-oct-2026 (utilidades/minar_velocidad_tenis.py, hipotesis en trabajo/minar/2026-10-06_velocidad_tenis.md;
30 % final mirado una vez), O/U de breaks en la linea ~promedio contra el modelo anterior:
  ATP bo3 +5.8 milesimas (z 7.1), ATP bo5 +14.7 (z 4.9), WTA bo3 +3.9 (z 5.1), las dos mitades. Games: mixto, no se usa.
Senales as-of:
  V1 velocidad del torneo = suma, en ediciones/rondas anteriores del mismo torneo, de (puntos ganados al saque reales -
     esperados por la carrera de cada jugador) / (puntos de saque + 300).
  V2 saque en superficie = por jugador, (puntos ganados al saque en la superficie - esperados por su carrera) /
     (puntos de saque en la superficie + 400), sumado para los dos.
Breaks esperados += C1 * V1 + C2 * V2 (coeficientes ajustados con el 70 % antiguo).
"""
import csv, io as _io, os, re, unicodedata, datetime as dt

COEF = {("ATP", 3): (-15.295, -2.809), ("ATP", 5): (-38.873, -3.613), ("WTA", 3): (-18.009, -4.093)}
K_TORNEO, K_SUP = 300.0, 400.0


def _n(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


class Senales:
    """Se alimenta partido a partido en orden (actualizar despues de predecir) y responde V1/V2 as-of."""
    def __init__(self):
        self.tor = {}        # (tour, torneo) -> [suma residuo puntos, puntos]
        self.car = {}        # jugador -> [puntos saque, ganados]
        self.sup = {}        # (jugador, superficie) -> [puntos, ganados]
        self.ult = {}        # jugador -> (fecha, torneo)

    def v1(self, tour, torneo):
        t = self.tor.get((tour, _n(torneo)))
        return t[0] / (t[1] + K_TORNEO) if t else 0.0

    def _dsup(self, j, sup):
        s, c = self.sup.get((j, sup)), self.car.get(j)
        if not s or not c or not c[0]:
            return 0.0
        return (s[1] - s[0] * (c[1] / c[0])) / (s[0] + K_SUP)

    def v2(self, j1, j2, sup):
        return self._dsup(j1, sup) + self._dsup(j2, sup)

    def actualizar(self, tour, torneo, sup, fecha, w, l, wsv, wsw, lsv, lsw, tour_spw=0.635):
        cw, cl = self.car.get(w), self.car.get(l)
        esp_w = cw[1] / cw[0] if cw and cw[0] else tour_spw
        esp_l = cl[1] / cl[0] if cl and cl[0] else tour_spw
        t = self.tor.setdefault((tour, _n(torneo)), [0.0, 0.0])
        t[0] += (wsw - wsv * esp_w) + (lsw - lsv * esp_l); t[1] += wsv + lsv
        for j, sv, sw in ((w, wsv, wsw), (l, lsv, lsw)):
            s = self.sup.setdefault((j, sup), [0.0, 0.0]); s[0] += sv; s[1] += sw
            c = self.car.setdefault(j, [0.0, 0.0]); c[0] += sv; c[1] += sw
            self.ult[j] = (fecha, _n(torneo))


def ajuste(S, tour, best_of, torneo, j1, j2, sup):
    """breaks a sumar al esperado del modelo (0 si el grupo no tiene coeficiente medido)."""
    c = COEF.get(((tour or "").upper(), int(best_of)))
    if not c or S is None:
        return 0.0, 0.0, 0.0
    v1, v2 = S.v1((tour or "").upper(), torneo), S.v2(j1, j2, sup)
    return c[0] * v1 + c[1] * v2, v1, v2


_PROD = None


def produccion(base):
    """Senales con toda la historia de datos/tenis.csv (para predecir partidos por jugar)."""
    global _PROD
    if _PROD is not None:
        return _PROD
    ruta = os.path.join(base, "datos", "tenis.csv")
    S = Senales()
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
            rows = list(csv.DictReader(fh))
        rows.sort(key=lambda r: (r.get("tourney_date", ""), r.get("winner_name", "")))
        for r in rows:
            try:
                wsv = float(r["w_svpt"]); wsw = float(r["w_1stWon"]) + float(r["w_2ndWon"])
                lsv = float(r["l_svpt"]); lsw = float(r["l_1stWon"]) + float(r["l_2ndWon"])
            except (KeyError, ValueError, TypeError):
                continue
            if wsv <= 0 or lsv <= 0 or not r.get("winner_name") or not r.get("loser_name"):
                continue
            S.actualizar((r.get("tour") or "TOUR").upper(), r.get("tourney_name") or "", (r.get("surface") or "Hard").strip() or "Hard",
                         r.get("tourney_date", ""), r["winner_name"], r["loser_name"], wsv, wsw, lsv, lsw)
    _PROD = S
    return S


ALIAS = {"china open": "beijing", "rolex shanghai masters": "shanghai masters", "shanghai": "shanghai masters",
         "wuhan open": "wuhan", "japan open": "tokyo", "toray pan pacific open": "tokyo", "kinoshita group japan open": "tokyo",
         "erste bank open": "vienna", "swiss indoors basel": "basel", "rolex paris masters": "paris masters",
         "national bank open": "montreal", "cincinnati open": "cincinnati masters", "western southern open": "cincinnati masters",
         "bnp paribas open": "indian wells masters", "miami open": "miami masters", "mutua madrid open": "madrid masters",
         "internazionali bnl d italia": "rome masters", "monte carlo rolex masters": "monte carlo masters"}


def torneo_tml(S, torneo_espn, tour, j1, j2):
    """Nombre del torneo como lo guarda TML. 1) el torneo del ultimo partido de los dos jugadores (si coincide y es
    reciente, es el torneo en curso); 2) alias conocidos; 3) mejor coincidencia de palabras."""
    u1, u2 = S.ult.get(j1), S.ult.get(j2)
    hoy = dt.date.today().strftime("%Y%m%d")
    if u1 and u2 and u1[1] == u2[1]:
        try:
            d = (dt.datetime.strptime(hoy, "%Y%m%d") - dt.datetime.strptime(str(u1[0])[:8], "%Y%m%d")).days
            if d <= 21:
                return u1[1]
        except ValueError:
            pass
    e = _n(torneo_espn)
    if e in ALIAS:
        return ALIAS[e]
    tour = (tour or "").upper()
    toks = set(e.split()) - {"open", "the", "tennis", "championships", "masters", "rolex", "cup", "international", "de", "di"}
    mejor, pts = "", 0
    for (t, nombre) in S.tor:
        if t != tour:
            continue
        k = len(toks & set(nombre.split()))
        if k > pts:
            mejor, pts = nombre, k
    return mejor or e
