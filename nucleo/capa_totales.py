# -*- coding: utf-8 -*-
"""
nucleo/capa_totales.py - capa de totales sobre el modelo de cada deporte (minado 9-oct-2026,
trabajo/minar/2026-10-09_capa_totales.md, utilidades/minar_capa_totales.py: C4 + C5).

  T* = a + b*T_modelo + c*M + d*E + nivel
    M = media de totales de la liga con olvido (vida media 400 juegos), con todo lo anterior a la fecha
    E = ritmo de los dos equipos: media con olvido (vida media 20 juegos del equipo) del total de los juegos de cada
        uno, encogida a M con 5 juegos de peso; E = ritmo_local + ritmo_visita - M
    nivel = media de los ultimos 300 residuos (C6: corrige el nivel cuando la anotacion de la liga se mueve)
  p(over L) = fraccion de los residuos del ultimo ano (minimo 300), centrados en el nivel, con T* + r > L (C7;
        distribucion empirica: sirve igual para goles, carreras y puntos, y corrige la forma que el modelo trae mal)

La validacion oficial (utilidades/validar_mercados.py) ajusta a, b, c, d en cada bloque solo con lo anterior, califica
"Total esperado (capa)" y "Over/Under (capa)" y, al final, escribe en modelos/capa_totales.json los coeficientes y los
residuos de toda la muestra. plataforma.py usa la capa solo en las ligas donde "Over/Under (capa)" quedo publicable.
Solo stdlib.
"""
import datetime as dt, json, math, os

VIDA_M = 400.0
VIDA_E = 20.0
K_E = 5.0
N_RES = 3000      # (C5, ya no se usa en produccion)
N_NIVEL = 300     # residuos para el nivel reciente (C6)
DIAS_RES = 365    # ventana de residuos para el over/under (C7)
MIN_PREV = 300
RUTA_JSON = ("modelos", "capa_totales.json")


class Ritmo:
    """M y E as-of (con todo lo anterior a la fecha) a partir de los juegos de la liga [(fecha, local, visita, total)]."""

    def __init__(self, juegos):
        self.J = sorted((str(f)[:10], h, a, float(t)) for f, h, a, t in juegos if f and t is not None)
        self.lam_m = 0.5 ** (1.0 / VIDA_M)
        self.lam_e = 0.5 ** (1.0 / VIDA_E)
        self._i = 0; self._num = self._den = 0.0; self._eq = {}
        self._cache = {}

    def _avanzar(self, fecha):
        """Incorpora todos los juegos con fecha < fecha (las consultas deben ir en orden de fecha)."""
        while self._i < len(self.J) and self.J[self._i][0] < fecha:
            f, h, a, t = self.J[self._i]
            self._num = self.lam_m * self._num + t; self._den = self.lam_m * self._den + 1
            for e in (h, a):
                n_, d_ = self._eq.get(e, (0.0, 0.0)); self._eq[e] = (self.lam_e * n_ + t, self.lam_e * d_ + 1)
            self._i += 1

    def estado(self, fecha, home, away):
        fecha = str(fecha)[:10]
        k = (fecha, home, away)
        if k in self._cache:
            return self._cache[k]
        if self._i and self._i <= len(self.J) and self.J[self._i - 1][0] >= fecha:
            # consulta hacia atras: se reinicia (solo pasa si el llamador no va en orden)
            self._i = 0; self._num = self._den = 0.0; self._eq = {}
        self._avanzar(fecha)
        M = self._num / self._den if self._den else None
        if M is None:
            return None
        def ritmo(e):
            n_, d_ = self._eq.get(e, (0.0, 0.0))
            w = d_ / (d_ + K_E)
            return w * (n_ / d_ if d_ else M) + (1 - w) * M
        out = (M, ritmo(home) + ritmo(away) - M)
        self._cache[k] = out
        return out


def ajustar_ols(X, Y):
    k = len(X[0]); A = [[0.0] * k for _ in range(k)]; b = [0.0] * k
    for v, y in zip(X, Y):
        for i in range(k):
            b[i] += v[i] * y
            for j in range(k):
                A[i][j] += v[i] * v[j]
    for i in range(k):
        A[i][i] += 1e-6
    n = k; M_ = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M_[r][c]))
        M_[c], M_[p] = M_[p], M_[c]
        for r in range(n):
            if r != c and M_[c][c]:
                f = M_[r][c] / M_[c][c]
                for j in range(c, n + 1):
                    M_[r][j] -= f * M_[c][j]
    return [M_[i][n] / M_[i][i] if M_[i][i] else 0.0 for i in range(n)]


def x_fila(pred, M, E):
    return (1.0, float(pred), float(M), float(E))


def total(coef, pred, M, E):
    """coef = [a, b, c, d] o [a, b, c, d, nivel]."""
    t = sum(c * v for c, v in zip(coef[:4], x_fila(pred, M, E)))
    return t + (coef[4] if len(coef) > 4 else 0.0)


def p_over(residuos, t, linea):
    if not residuos or t is None or linea is None:
        return None
    return sum(1 for e in residuos if t + e > linea) / len(residuos)


def entrenar(filas):
    """filas = [(pred, real, M, E, fecha)] en orden -> (coef con el nivel al final, residuos del ultimo ano centrados).
    total(coef, ...) ya incluye el nivel."""
    coef = ajustar_ols([x_fila(p, M, E) for p, _, M, E, _ in filas], [r for _, r, _, _, _ in filas])
    res = [r - total(coef, p, M, E) for p, r, M, E, _ in filas]
    ult = res[-N_NIVEL:]
    nivel = sum(ult) / len(ult) if ult else 0.0
    f_fin = max((str(f)[:10] for *_, f in filas if f), default=None)
    lim = (dt.date.fromisoformat(f_fin) - dt.timedelta(days=DIAS_RES)).isoformat() if f_fin else ""
    rr = [e - nivel for e, x in zip(res, filas) if str(x[4] or "")[:10] >= lim]
    if len(rr) < MIN_PREV:
        rr = [e - nivel for e in res[-MIN_PREV:]]
    return list(coef) + [nivel], rr


# ------------------------------------------------------------------ produccion
_CACHE = {}


def cargar(base):
    ruta = os.path.join(base, *RUTA_JSON)
    if ruta not in _CACHE:
        try:
            _CACHE[ruta] = json.load(open(ruta, encoding="utf-8"))
        except Exception:
            _CACHE[ruta] = {}
    return _CACHE[ruta]


def guardar(base, clave, coef, res, n, desde, hasta, estado):
    ruta = os.path.join(base, *RUTA_JSON)
    try:
        d = json.load(open(ruta, encoding="utf-8"))
    except Exception:
        d = {}
    d["_como"] = ("T* = a + b*T_modelo + c*M + d*E; p(over L) = fraccion de residuos con T* + r > L. "
                  "nucleo/capa_totales.py; minado trabajo/minar/2026-10-09_capa_totales.md")
    d[clave] = {"coef": [round(x, 6) for x in coef], "residuos": [round(x, 3) for x in res], "n": n,
                "desde": desde, "hasta": hasta, "estado_validacion": estado,
                "vida_m": VIDA_M, "vida_e": VIDA_E, "k_e": K_E, "generado": dt.date.today().isoformat()}
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    _CACHE.pop(ruta, None)


_RITMOS = {}
_EQ = {}
# Liga -> juegos minimos de cada equipo en la temporada en curso para usar la capa. NBA: en octubre-noviembre la capa
# subestima el total (sesgo -6.4 puntos y MAE peor que la base en 629 juegos, medido el 9-oct-2026 sobre el walk-forward:
# el ritmo sale de los playoffs y del final de la temporada anterior). Beisbol, NCAAMB y LMP no muestran ese problema.
MIN_TEMPORADA = {"nba": 15}


def juegos_temporada(deporte, liga, equipo, fecha, hueco=45):
    """Juegos del equipo en la temporada en curso: los que van desde el ultimo hueco de mas de `hueco` dias."""
    k = (deporte, liga)
    if k not in _EQ:
        from nucleo import forma as FM
        _EQ[k] = FM._juegos_equipo(deporte, liga)
    fs = [j["f"] for j in _EQ[k].get(equipo) or [] if j["f"] < str(fecha)[:10]]
    if not fs:
        return 0
    d = lambda x: dt.date.fromisoformat(x[:10])
    if (d(str(fecha)[:10]) - d(fs[-1])).days > hueco:
        return 0
    n = 1
    for a_, b_ in zip(reversed(fs[:-1]), reversed(fs[1:])):
        if (d(b_) - d(a_)).days > hueco:
            break
        n += 1
    return n


def ritmo_liga(deporte, liga):
    """Ritmo con todos los juegos de datos/ de la liga (nucleo/forma: mismos nombres de equipo que los modelos)."""
    k = (deporte, liga)
    if k not in _RITMOS:
        from nucleo import forma as FM
        eq = FM._juegos_equipo(deporte, liga)
        J = []
        for t, lst in eq.items():
            for j in lst:
                if j["home"]:
                    J.append((j["f"], t, j["rival"], j["gf"] + j["ga"]))
        _RITMOS[k] = Ritmo(J)
    return _RITMOS[k]


def aplicar(base, clave, deporte, liga, home, away, fecha, pred, linea):
    """-> dict con total y p_over de la capa, o None si la liga no tiene capa publicable."""
    d = cargar(base).get(clave)
    if not d or d.get("estado_validacion") != "publicable" or pred is None:
        return None
    mn = MIN_TEMPORADA.get(clave)
    if mn and min(juegos_temporada(deporte, liga, home, fecha), juegos_temporada(deporte, liga, away, fecha)) < mn:
        return None
    st = ritmo_liga(deporte, liga).estado(fecha, home, away)
    if not st:
        return None
    M, E = st
    t = total(d["coef"], pred, M, E)
    po = None
    if linea is not None:
        if abs(float(linea) - round(float(linea))) < 1e-9:      # linea entera: over sin contar el empate (push)
            r3 = probs_linea(base, clave, t, float(linea))
            po = r3[0] / max(1e-9, r3[0] + r3[1]) if r3 else None
        else:
            po = p_over(d["residuos"], t, float(linea))
    return {"aplicado": True, "clave": clave, "total_modelo": round(float(pred), 2), "total": round(t, 2),
            "p_over": None if po is None else round(po, 4),
            "media_liga": round(M, 2), "ritmo": round(E, 2), "coef": d["coef"], "n": d.get("n")}


def probs_linea(base, clave, t, linea):
    """(p_over, p_under, p_push) a cualquier linea con la distribucion de residuos de la capa (lineas enteras: push =
    residuos que caen a menos de medio punto de la linea)."""
    d = cargar(base).get(clave) or {}
    res = d.get("residuos") or []
    if not res or t is None:
        return None
    n = float(len(res))
    if abs(linea - round(linea)) < 1e-9:
        po = sum(1 for e in res if t + e >= linea + 0.5) / n
        pu = sum(1 for e in res if t + e <= linea - 0.5) / n
        return po, pu, max(0.0, 1 - po - pu)
    po = sum(1 for e in res if t + e > linea) / n
    return po, 1 - po, 0.0
