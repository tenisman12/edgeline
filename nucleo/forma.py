# -*- coding: utf-8 -*-
"""
nucleo/forma.py - FORMA Y ESTADISTICAS POR EQUIPO (o jugador de tenis), igual para todos los deportes.

No toca ninguna probabilidad: describe como llega cada equipo al partido, a partir de tus datos
(datos/<deporte>.csv, datos/equipos/*.csv). Todo se recalcula completo en cada corrida desde el
historial, asi que un juego nuevo cambia rachas, status y osciladores esa misma corrida.

Por equipo devuelve:
  record           temporada, local y visita (W-L o W-D-L)
  racha            racha actual (W3, L2, D1)
  ultimos10        los 10 juegos mas recientes (fecha, rival, sede, marcador, resultado)
  ventanas         temporada | local | visita | L10 | L5 | L3: juegos, W/D/L, anotado y permitido por
                   juego, fuerza ofensiva y defensiva contra el promedio de la liga en esa ventana
                   (1.00 = promedio; defensa menor a 1 = permite menos)
  power            ranking por ELO descriptivo entre los equipos activos (no es el ELO del modelo)
  status           Burning Hot / Hot / Average Up / Average Down / Cold / Dead
  osciladores      forma, ataque, defensa, dif5 (ver OSCILADORES)
  ou4              ultimos 4 totales contra el promedio de la liga (O/U)
  stats            promedio de TODAS las columnas numericas del equipo: temporada y ultimos 10

Fuera de temporada (ultimo juego a mas de 60 dias) se marca fuera_de_temporada y la "temporada"
es la ultima que jugo.

OSCILADORES (comparan la forma reciente con la BASE del mismo equipo):
  La base son los ultimos BASE_N juegos del equipo (por deporte: beisbol 60, hockey 40, nba 40,
  americano 17, futbol 20) cruzando temporadas si la actual no alcanza. Asi hay senal desde el
  primer juego de la temporada; antes se comparaba contra la temporada en curso y al inicio todo
  salia en 0. Las ventanas L10/L5/L3 tambien cruzan temporadas mientras la actual tenga menos de
  5 juegos (se marca incluye_temporada_anterior).
  forma   = %puntos L10 - %puntos base (en fraccion; %puntos = (G + 0.5 E) / juegos)
  ataque  = anotado por juego L10 / base - 1
  defensa = permitido por juego L10 / base - 1   (negativo = esta permitiendo menos)
  dif5    = diferencial por juego L5 - diferencial por juego base
  tendencia: Subiendo si forma >= +0.15, Bajando si forma <= -0.15, si no Estable.

OSCILADORES DETALLADOS (osciladores_detalle), mismas unidades:
  forma3, forma5          %puntos L3 / L5 - base
  ataque3, defensa3       anotado / permitido L3 contra base
  dif10, dif3             diferencial por juego L10 / L3 - base
  volatilidad10           desviacion estandar del diferencial en L10 (que tan erratico llega)
  forma_local, forma_visita   %puntos de sus ultimos 10 como local / visita - base
  ataque_local, defensa_visita   anotado de local / permitido de visita contra base
  elo_mom10               cambio del ELO descriptivo en los ultimos 10 juegos (power momentum)
  ou10                    fraccion de Over en L10 - fraccion de Over en base (contra el promedio de liga)
  carga: juegos_7d (juegos en los 7 dias previos al ultimo), descanso_ultimo (dias entre sus dos
         ultimos juegos), b2b_ultimo (jugo dos dias seguidos al final)
  porteria5 (hockey)      save% L5 - save% base, cuando el CSV trae goalie_sv
  n_base, n_temporada, incluye_temporada_anterior

OSCILADORES TECNICOS (osciladores_tecnicos): indicadores bursatiles traducidos a la serie del equipo
(diferencial de anotacion por partido, cruzando temporadas; ELO descriptivo tras cada juego).
Todos son descriptivos hasta que pesos_capas mida su peso; la literatura (Moskowitz 2021, Miller &
Sanjurjo 2018) advierte que el momentum sobre secuencias cortas y binarias esta sesgado, por eso
aqui se calculan sobre el margen (continuo), no sobre ganar/perder.
  rsi5, rsi10, rsi15      RSI de Wilder sobre el diferencial: 100 * subidas / (subidas + bajadas),
                          donde subida = diferencial positivo (ponderado por margen). 50 = neutro;
                          >70 "sobrecomprado" (racha de margenes altos), <30 "sobrevendido".
  macd, macd_senal, macd_hist   EMA(5) - EMA(20) del diferencial; senal = EMA(9) del MACD;
                          histograma = macd - senal (aceleracion de la forma).
  elo_macd                ELO con K alto (x2) - ELO con K bajo (x0.5): forma reciente contra fuerza de fondo.
  bb_pct_b, bb_ancho      %B de Bollinger del diferencial contra su media movil de 20 (+-2 DE): 0.5 = en la
                          media, >1 arriba de la banda superior, <0 debajo de la inferior; ancho = 4 DE / |media|.
  estocastico_k, estocastico_d   posicion del ELO actual en su rango de 14 juegos (0-100); %D = media de 3.
  roc_elo10               cambio porcentual del ELO en 10 juegos (momentum de rating).
  pitagorico              % victorias esperado por anotado/permitido (exponente por deporte: beisbol
                          pythagenpat RPG^0.287, hockey 1.93, nba 14, americano 2.37, futbol 1.3 sobre
                          puntos con empates); residuo_pitagorico = % real - % esperado en la base
                          (positivo = ha ganado mas de lo que su anotacion justifica: senal de reversion).
  ventana_tecnica         juegos usados (hasta BASE_N, cruzando temporadas)

Solo stdlib.
"""
import csv, io as _io, math, os, datetime as dt

try:
    from nucleo import io
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

SCORE = {"beisbol": ("runs", "runs_opp"), "hockey": ("goals", "goals_opp"),
         "nba": ("points", "points_opp"), "americano": ("points", "points_opp"),
         "futbol": ("goals", "goals_opp")}
# K del ELO descriptivo por deporte (que el ranking se mueva a un ritmo parecido)
K_ELO = {"beisbol": 6.0, "hockey": 8.0, "nba": 5.0, "americano": 8.0, "futbol": 14.0}
HFA = {"beisbol": 24.0, "hockey": 30.0, "nba": 70.0, "americano": 55.0, "futbol": 60.0}
REGRESION = 0.70            # al cambiar de temporada el ELO regresa 30% a 1500
DIAS_FUERA = 60
BASE_N = {"beisbol": 60, "hockey": 40, "nba": 40, "americano": 17, "futbol": 20}
PITAGORAS = {"hockey": 1.93, "nba": 14.0, "americano": 2.37, "futbol": 1.3}   # beisbol: pythagenpat
MIN_TEMP_VENTANAS = 5       # con menos juegos en la temporada, L10/L5/L3 cruzan temporadas
VENT = ("temp", "local", "visita", "L10", "L5", "L3")
_NO_STATS = {"gamePk", "game_id", "season", "is_home", "week", "tipo", "marcador", "league", "liga",
             "season_type", "game_date", "source"}

_CACHE = {}


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _prim(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _sig(z):
    return 0.0 if z < -35 else (1.0 if z > 35 else 1 / (1 + math.exp(-z)))


def _leer(path):
    if path not in _CACHE:
        _CACHE[path] = io._leer_csv(path)
    return _CACHE[path]


def limpiar_cache():
    _CACHE.clear()


# ================================================================== juegos por equipo
def _juegos_equipo(deporte, liga):
    """-> {equipo: [juego,...]} ordenado por fecha. Un juego = dict(f, gp, home, rival, gf, ga, season, fila)."""
    ks, ko = SCORE[deporte]
    filas = _leer(io.DATOS(io.ARCHIVO_DEPORTE[deporte]))
    if liga:
        fl = io.norm(liga)
        filas = [r for r in filas if io.norm(r.get("league") or r.get("liga")) == fl]
    por = {}
    for r in filas:
        gp = str(r.get("gamePk") or r.get("game_id") or "")
        if gp:
            por.setdefault(gp, []).append(r)
    eq = {}
    for gp, par in por.items():
        if len(par) != 2:
            continue
        a, b = par
        sa = _prim(_f(a.get(ks)), _f(b.get(ko)))
        sb = _prim(_f(b.get(ks)), _f(a.get(ko)))
        fecha = (a.get("game_date") or "")[:10]
        if sa is None or sb is None or not fecha:
            continue
        for x, y, gx, gy in ((a, b, sa, sb), (b, a, sb, sa)):
            eq.setdefault(x.get("team"), []).append({
                "f": fecha, "gp": gp, "home": str(x.get("is_home")) in ("1", "1.0", "True", "true"),
                "rival": y.get("team"), "gf": gx, "ga": gy, "season": x.get("season") or "", "fila": x})
    for lst in eq.values():
        lst.sort(key=lambda j: (j["f"], j["gp"]))
    return eq


def _res(j):
    return "W" if j["gf"] > j["ga"] else ("L" if j["gf"] < j["ga"] else "D")


def _elos(eq, deporte, historial=False, k_mult=1.0):
    """ELO descriptivo recorriendo todos los juegos en orden cronologico.
    Con historial=True devuelve tambien {equipo: [(temporada, elo tras cada juego)]}.
    k_mult escala la K (K alta = reacciona rapido, K baja = fuerza de fondo)."""
    k, hfa = K_ELO[deporte] * k_mult, HFA[deporte]
    todos = []
    for t, lst in eq.items():
        for j in lst:
            if j["home"]:
                todos.append((j["f"], j["gp"], t, j["rival"], j["gf"], j["ga"], j["season"]))
    todos.sort()
    elo, ult, hist = {}, {}, {}
    for f, gp, h, a, gh, ga, se in todos:
        for t in (h, a):
            elo.setdefault(t, 1500.0)
            if ult.get(t) not in (None, se):
                elo[t] = 1500.0 + (elo[t] - 1500.0) * REGRESION
            ult[t] = se
        esp = _sig((elo[h] + hfa - elo[a]) / (400.0 / math.log(10)))
        res = 1.0 if gh > ga else (0.5 if gh == ga else 0.0)
        d = k * max(math.log(abs(gh - ga) + 1), 0.7) * (res - esp)
        elo[h] += d
        elo[a] -= d
        hist.setdefault(h, []).append((se, elo[h]))
        hist.setdefault(a, []).append((se, elo[a]))
    if historial:
        return elo, hist
    return elo


# ================================================================== ventanas y osciladores
def _ventana(js):
    n = len(js)
    if not n:
        return {"n": 0}
    w = sum(1 for j in js if j["gf"] > j["ga"])
    l = sum(1 for j in js if j["gf"] < j["ga"])
    gf = sum(j["gf"] for j in js) / n
    ga = sum(j["ga"] for j in js) / n
    return {"n": n, "w": w, "d": n - w - l, "l": l, "gf": round(gf, 3), "ga": round(ga, 3),
            "dif": round(gf - ga, 3), "pts": round((w + 0.5 * (n - w - l)) / n, 3)}


def _recortes(js, season):
    ts = [j for j in js if j["season"] == season]
    return {"temp": ts, "local": [j for j in ts if j["home"]], "visita": [j for j in ts if not j["home"]],
            "L10": ts[-10:], "L5": ts[-5:], "L3": ts[-3:]}


def _status(ult6, rank, n_eq, n_juegos):
    """Burning Hot / Hot / Average Up / Average Down / Cold / Dead (forma de 6 juegos + ranking)."""
    if n_juegos < 6:
        return "New"
    forma = sum(1.0 if j["gf"] > j["ga"] else (0.5 if j["gf"] == j["ga"] else 0.0) for j in ult6) / 6.0
    top, bot = rank <= n_eq * 0.3, rank >= n_eq * 0.7
    if forma >= 5 / 6 and top:
        return "Burning Hot"
    if forma >= 4 / 6:
        return "Average Up" if bot else "Hot"
    if forma <= 1 / 6 and bot:
        return "Dead"
    if forma <= 2 / 6:
        return "Cold" if bot else "Average Down"
    return "Average Up" if top else "Average Down"


def _racha(js):
    if not js:
        return ""
    r = _res(js[-1])
    n = 0
    for j in reversed(js):
        if _res(j) == r:
            n += 1
        else:
            break
    return "%s%d" % (r, n)


def _promedios_stats(filas):
    """promedio de todas las columnas numericas (se ignoran las que casi no traen dato)."""
    if not filas:
        return {}
    out = {}
    for c in filas[0].keys():
        if c in _NO_STATS or c is None:
            continue
        vs = [_f(r.get(c)) for r in filas]
        vs = [v for v in vs if v is not None]
        if len(vs) >= max(1, 0.5 * len(filas)):
            out[c] = round(sum(vs) / len(vs), 3)
    return out


def _osc_stats(base, rec):
    """Oscilador por estadistica: reciente / base - 1 (None si la base es 0 o falta)."""
    out = {}
    for k, v in (rec or {}).items():
        b = (base or {}).get(k)
        if b is None or v is None:
            continue
        out[k] = round(v / b - 1, 3) if b else None
    return out


# ================================================================== clase principal
class Forma:
    """Forma de los equipos de una liga. Se construye una vez por (deporte, liga)."""

    def __init__(self, deporte, liga=None, eq=None):
        self.deporte, self.liga = deporte, liga
        self.eq = eq if eq is not None else _juegos_equipo(deporte, liga)
        self.elo, self.elo_hist = _elos(self.eq, deporte, historial=True)
        self.elo_alto = _elos(self.eq, deporte, k_mult=2.0)
        self.elo_bajo = _elos(self.eq, deporte, k_mult=0.5)
        self.ultima = max((l[-1]["f"] for l in self.eq.values() if l), default="")
        lim = (dt.date.fromisoformat(self.ultima) - dt.timedelta(days=120)).isoformat() if self.ultima else ""
        self.activos = [t for t, l in self.eq.items() if l and l[-1]["f"] >= lim]
        orden = sorted(self.activos, key=lambda t: -self.elo[t])
        self.rank = {t: i + 1 for i, t in enumerate(orden)}
        # promedio de liga por ventana (de los equipos activos, cada uno con su temporada)
        self.lg = {}
        acum = {v: [[], []] for v in VENT}
        tot = []
        for t in self.activos:
            se = self.eq[t][-1]["season"]
            for v, js in _recortes(self.eq[t], se).items():
                w = _ventana(js)
                if w["n"]:
                    acum[v][0].append(w["gf"]); acum[v][1].append(w["ga"])
            tt = [j["gf"] + j["ga"] for j in self.eq[t] if j["season"] == se]
            if tt:
                tot.append(sum(tt) / len(tt))
        for v in VENT:
            gf, ga = acum[v]
            self.lg[v] = {"gf": sum(gf) / len(gf) if gf else None, "ga": sum(ga) / len(ga) if ga else None}
        self.lg_total = sum(tot) / len(tot) if tot else None

    def tiene(self, equipo):
        return equipo in self.eq and bool(self.eq[equipo])

    def equipo(self, nombre, con_stats=True):
        js = self.eq.get(nombre) or []
        if not js:
            return None
        se = js[-1]["season"]
        rec = _recortes(js, se)
        vent = {}
        for v in VENT:
            w = _ventana(rec[v])
            if w["n"]:
                lgv = self.lg.get(v) or {}
                w["of_idx"] = round(w["gf"] / lgv["gf"], 3) if lgv.get("gf") else None
                w["df_idx"] = round(w["ga"] / lgv["ga"], 3) if lgv.get("ga") else None
            vent[v] = w
        def _rec(w):
            return ("%d-%d-%d" % (w["w"], w["d"], w["l"])) if self.deporte == "futbol" else "%d-%d" % (w["w"], w["l"])
        record = {k: (_rec(vent[k]) if vent[k]["n"] else "") for k in ("temp", "local", "visita")}
        ts = [j for j in js if j["season"] == se]
        osc, det = self._osciladores(nombre, js, ts)
        ou = []
        if self.lg_total:
            ou = ["O" if j["gf"] + j["ga"] > self.lg_total else "U" for j in ts[-4:]]
        ultimos = [{"fecha": j["f"], "rival": j["rival"], "sede": "L" if j["home"] else "V",
                    "gf": j["gf"], "ga": j["ga"], "r": _res(j)} for j in reversed(ts[-10:])]
        out = {
            "equipo": nombre, "temporada": se, "ultimo_juego": js[-1]["f"],
            "fuera_de_temporada": bool(self.ultima and (dt.date.fromisoformat(self.ultima) -
                                                        dt.date.fromisoformat(js[-1]["f"])).days > DIAS_FUERA),
            "record": record, "racha": _racha(ts), "ultimos10": ultimos,
            "ventanas": vent, "elo": round(self.elo.get(nombre, 1500.0), 1),
            "power": {"rank": self.rank.get(nombre), "de": len(self.activos)},
            "status": _status(ts[-6:], self.rank.get(nombre, len(self.activos)), len(self.activos), len(ts)),
            "osciladores": osc, "osciladores_detalle": det, "osciladores_tecnicos": self._tecnicos(nombre, js),
            "ou4": "-".join(ou),
        }
        if con_stats:
            nb = BASE_N.get(self.deporte, 40)
            rec_js = js if len(ts) < MIN_TEMP_VENTANAS else ts
            out["stats"] = {"temp": _promedios_stats([j["fila"] for j in ts]),
                            "L10": _promedios_stats([j["fila"] for j in rec_js[-10:]])}
            # oscilador por estadistica: L10 contra la base (ultimos BASE_N juegos, cruzando temporadas)
            out["stats"]["osc_L10"] = _osc_stats(_promedios_stats([j["fila"] for j in js[-nb:]]), out["stats"]["L10"])
        return out


def _elo_corregido(h):
    """Serie de ELO sin el salto artificial del cambio de temporada (se suma de vuelta la regresion)."""
    out, off = [], 0.0
    for i, (se, e) in enumerate(h):
        if i and h[i - 1][0] != se:
            off += (h[i - 1][1] - 1500.0) * (1.0 - REGRESION)
        out.append(e + off)
    return out


def _elo_mom(h, n):
    """Cambio de ELO en los ultimos n juegos, sumando de vuelta la regresion de cambio de temporada
    (si no, el salto artificial a 1500 aparece como caida de forma)."""
    if len(h) < 2:
        return None
    seg = h[-(n + 1):]
    mom = seg[-1][1] - seg[0][1]
    for (s0, e0), (s1, _) in zip(seg, seg[1:]):
        if s0 != s1:
            mom += (e0 - 1500.0) * (1.0 - REGRESION)
    return round(mom, 1)


def _ema(xs, n):
    if not xs:
        return None
    a = 2.0 / (n + 1)
    e = xs[0]
    for x in xs[1:]:
        e = a * x + (1 - a) * e
    return e


def _ema_serie(xs, n):
    out = []
    if not xs:
        return out
    a = 2.0 / (n + 1)
    e = xs[0]
    out.append(e)
    for x in xs[1:]:
        e = a * x + (1 - a) * e
        out.append(e)
    return out


def _rsi(difs, n):
    """RSI de Wilder sobre el diferencial por partido (margen positivo = subida, negativo = bajada)."""
    seg = difs[-n:]
    if len(seg) < max(3, n // 2):
        return None
    up = sum(d for d in seg if d > 0)
    dn = sum(-d for d in seg if d < 0)
    if up + dn == 0:
        return 50.0
    return round(100.0 * up / (up + dn), 1)


def _pitagorico(deporte, gf, ga, n, empates=0):
    if not n or gf <= 0 or ga <= 0:
        return None
    if deporte == "beisbol":
        rpg = (gf + ga) / n
        ex = max(rpg, 1.0) ** 0.287
    else:
        ex = PITAGORAS.get(deporte, 2.0)
    return gf ** ex / (gf ** ex + ga ** ex)


def _tecnicos(self, nombre, js):
    """Osciladores bursatiles sobre la serie del equipo (diferencial por partido y ELO)."""
    nb = BASE_N.get(self.deporte, 40)
    seg = js[-nb:]
    difs = [j["gf"] - j["ga"] for j in seg]
    t = {"ventana_tecnica": len(difs)}
    if len(difs) < 5:
        return t
    for n in (5, 10, 15):
        t["rsi%d" % n] = _rsi(difs, n)
    e5, e20 = _ema_serie(difs, 5), _ema_serie(difs, 20)
    macd = [a - b for a, b in zip(e5, e20)]
    senal = _ema_serie(macd, 9)
    t["macd"] = round(macd[-1], 3); t["macd_senal"] = round(senal[-1], 3); t["macd_hist"] = round(macd[-1] - senal[-1], 3)
    ea, eb = self.elo_alto.get(nombre), self.elo_bajo.get(nombre)
    t["elo_macd"] = round(ea - eb, 1) if ea is not None and eb is not None else None
    w = difs[-20:]
    m = sum(w) / len(w); sd = _pstd(w) or 0.0
    t["bb_pct_b"] = round((difs[-1] - (m - 2 * sd)) / (4 * sd), 3) if sd else None
    t["bb_ancho"] = round(4 * sd / abs(m), 3) if m else None
    h = _elo_corregido(self.elo_hist.get(nombre) or [])
    if len(h) >= 5:
        r = h[-14:]
        lo, hi = min(r), max(r)
        ks = []
        for i in range(max(1, len(h) - 2), len(h) + 1):
            rr = h[max(0, i - 14):i]
            l2, h2 = min(rr), max(rr)
            ks.append(100.0 * (rr[-1] - l2) / (h2 - l2) if h2 > l2 else 50.0)
        t["estocastico_k"] = round(ks[-1], 1); t["estocastico_d"] = round(sum(ks) / len(ks), 1)
        t["roc_elo10"] = round(100.0 * (h[-1] - h[-11]) / h[-11], 2) if len(h) >= 11 else None
    gf = sum(j["gf"] for j in seg); ga = sum(j["ga"] for j in seg); n = len(seg)
    pit = _pitagorico(self.deporte, gf, ga, n)
    if pit is not None:
        wpct = sum(1.0 if j["gf"] > j["ga"] else (0.5 if j["gf"] == j["ga"] else 0.0) for j in seg) / n
        t["pitagorico"] = round(pit, 3); t["residuo_pitagorico"] = round(wpct - pit, 3)
    return t


Forma._tecnicos = _tecnicos


def _pstd(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / n)


def _osciladores(self, nombre, js, ts):
    """Osciladores basicos y detallados contra la BASE (ultimos BASE_N juegos, cruzando temporadas)."""
    nb = BASE_N.get(self.deporte, 40)
    base_js = js[-nb:]
    cruza = len(ts) < MIN_TEMP_VENTANAS
    rec_js = js if cruza else ts          # de donde salen L10/L5/L3
    l10, l5, l3 = _ventana(rec_js[-10:]), _ventana(rec_js[-5:]), _ventana(rec_js[-3:])
    b = _ventana(base_js)
    osc, det = {}, {}
    if not b["n"] or not l10["n"]:
        return osc, det
    def rel(x, y):
        return round(x / y - 1, 3) if y else None
    osc["forma"] = round(l10["pts"] - b["pts"], 3)
    osc["ataque"] = rel(l10["gf"], b["gf"])
    osc["defensa"] = rel(l10["ga"], b["ga"])
    osc["dif5"] = round(l5["dif"] - b["dif"], 3) if l5["n"] else None
    osc["tendencia"] = "Subiendo" if osc["forma"] >= 0.15 else ("Bajando" if osc["forma"] <= -0.15 else "Estable")
    # detallados
    det["forma5"] = round(l5["pts"] - b["pts"], 3) if l5["n"] else None
    det["forma3"] = round(l3["pts"] - b["pts"], 3) if l3["n"] else None
    det["ataque3"] = rel(l3["gf"], b["gf"]) if l3["n"] else None
    det["defensa3"] = rel(l3["ga"], b["ga"]) if l3["n"] else None
    det["dif10"] = round(l10["dif"] - b["dif"], 3)
    det["dif3"] = round(l3["dif"] - b["dif"], 3) if l3["n"] else None
    det["volatilidad10"] = (lambda v: round(v, 3) if v is not None else None)(_pstd([j["gf"] - j["ga"] for j in rec_js[-10:]]))
    loc = [j for j in js if j["home"]][-10:]
    vis = [j for j in js if not j["home"]][-10:]
    wl, wv = _ventana(loc), _ventana(vis)
    det["forma_local"] = round(wl["pts"] - b["pts"], 3) if wl["n"] else None
    det["forma_visita"] = round(wv["pts"] - b["pts"], 3) if wv["n"] else None
    det["ataque_local"] = rel(wl["gf"], b["gf"]) if wl["n"] else None
    det["defensa_visita"] = rel(wv["ga"], b["ga"]) if wv["n"] else None
    h = self.elo_hist.get(nombre) or []
    det["elo_mom10"] = _elo_mom(h, 10)
    if self.lg_total:
        ov = lambda L: sum(1 for j in L if j["gf"] + j["ga"] > self.lg_total) / len(L)
        det["ou10"] = round(ov(rec_js[-10:]) - ov(base_js), 3)
    # carga
    try:
        fechas = [dt.date.fromisoformat(j["f"]) for j in js[-12:]]
        ult = fechas[-1]
        det["carga"] = {"juegos_7d": sum(1 for f in fechas if 0 <= (ult - f).days < 7),
                        "descanso_ultimo": (fechas[-1] - fechas[-2]).days if len(fechas) >= 2 else None,
                        "b2b_ultimo": bool(len(fechas) >= 2 and (fechas[-1] - fechas[-2]).days == 1)}
    except (ValueError, TypeError):
        det["carga"] = None
    if self.deporte == "hockey":
        sv = lambda L: [v for v in (_f(j["fila"].get("goalie_sv")) for j in L) if v is not None]
        s5, sb = sv(rec_js[-5:]), sv(base_js)
        det["porteria5"] = round(sum(s5) / len(s5) - sum(sb) / len(sb), 4) if s5 and sb else None
    det["n_base"] = b["n"]; det["n_temporada"] = len(ts); det["incluye_temporada_anterior"] = cruza
    return osc, det


Forma._osciladores = _osciladores


def _h2h(self, a, b, max_ult=5):
    """Cara a cara en tus datos (todas las temporadas)."""
    js = [j for j in (self.eq.get(a) or []) if j["rival"] == b]
    if not js:
        return {"partidos": 0}
    ga = sum(1 for j in js if j["gf"] > j["ga"])
    gb = sum(1 for j in js if j["gf"] < j["ga"])
    return {"partidos": len(js), "gana_a": ga, "gana_b": gb, "empates": len(js) - ga - gb,
            "ultimos": [{"fecha": j["f"], "sede_a": "L" if j["home"] else "V", "marcador_a": j["gf"],
                         "marcador_b": j["ga"]} for j in reversed(js[-max_ult:])]}


Forma.h2h = _h2h


def forma(deporte, liga=None):
    """Forma ya construida y en cache por (deporte, liga)."""
    k = ("forma", deporte, liga or "")
    if k not in _CACHE:
        _CACHE[k] = Forma(deporte, liga)
    return _CACHE[k]


# ================================================================== forma desde datos/equipos/espn_<liga>_equipos.csv
DEP_ESPN = {"ncaamb": "nba", "ncaafb": "americano", "champions": "futbol", "mls": "futbol", "ligamx": "futbol",
            "premier": "futbol", "laliga": "futbol", "seriea": "futbol", "bundesliga": "futbol", "ligue1": "futbol",
            "nba": "nba", "nfl": "americano"}


def _juegos_equipo_espn(liga):
    """Arma el mismo diccionario de juegos usando 'marcador' de los archivos de equipos de ESPN."""
    ruta = os.path.join(io.BASE, "datos", "equipos", "espn_%s_equipos.csv" % liga)
    filas = _leer(ruta)
    por = {}
    for r in filas:
        gid = str(r.get("game_id") or "")
        if gid:
            por.setdefault(gid, []).append(r)
    eq = {}
    for gid, par in por.items():
        if len(par) != 2:
            continue
        a, b = par
        sa, sb = _f(a.get("marcador")), _f(b.get("marcador"))
        fecha = (a.get("game_date") or "")[:10]
        if sa is None or sb is None or not fecha:
            continue
        for x, y, gx, gy in ((a, b, sa, sb), (b, a, sb, sa)):
            eq.setdefault(x.get("team"), []).append({
                "f": fecha, "gp": gid, "home": str(x.get("is_home")) in ("1", "1.0", "True", "true"),
                "rival": y.get("team"), "gf": gx, "ga": gy, "season": str(x.get("season") or ""), "fila": x})
    for lst in eq.values():
        lst.sort(key=lambda j: (j["f"], j["gp"]))
    return eq


def forma_espn(liga):
    k = ("forma_espn", liga)
    if k not in _CACHE:
        dep = DEP_ESPN.get(liga, "nba")
        _CACHE[k] = Forma(dep, liga, eq=_juegos_equipo_espn(liga))
    return _CACHE[k]


# ================================================================== estadisticas de equipo (datos/equipos/*.csv)
ARCHIVO_EQUIPOS = {"nhl": "nhl_equipos.csv", "nfl": "nfl_equipos.csv", "ncaafb": "espn_ncaafb_equipos.csv"}


def archivo_equipos(liga):
    return ARCHIVO_EQUIPOS.get(liga, "espn_%s_equipos.csv" % liga)


class EstadisticasEquipo:
    """Promedios de las estadisticas ricas por partido (tiros, posesion, EPA, rebotes...)."""

    def __init__(self, liga):
        self.liga = liga
        self.ruta = os.path.join(io.BASE, "datos", "equipos", archivo_equipos(liga))
        filas = _leer(self.ruta)
        # solo temporada regular cuando el archivo la distingue
        self.por = {}
        for r in filas:
            tp = (r.get("tipo") or r.get("season_type") or "").upper()
            if tp in ("PRE", "PRESEASON"):
                continue
            self.por.setdefault(r.get("team"), []).append(r)
        for lst in self.por.values():
            lst.sort(key=lambda r: (r.get("game_date") or "", str(r.get("game_id") or "")))
        self.equipos = [t for t in self.por if t]

    def disponible(self):
        return bool(self.por)

    def de(self, nombre):
        lst = self.por.get(nombre) or []
        if not lst:
            return None
        se = lst[-1].get("season")
        ts = [r for r in lst if r.get("season") == se]
        # base: temporada en curso, o los ultimos 17/40 juegos cruzando temporadas si la actual va empezando
        nb = 17 if self.liga in ("nfl", "ncaafb") else 40
        base = ts if len(ts) >= min(nb, 8) else lst[-nb:]
        temp, l5, l10 = _promedios_stats(ts), _promedios_stats(lst[-5:] if len(ts) < 5 else ts[-5:]), _promedios_stats(lst[-10:] if len(ts) < 10 else ts[-10:])
        pb = _promedios_stats(base)
        return {"temporada": se, "juegos": len(ts), "ultimo_juego": (ts[-1].get("game_date") or "")[:10],
                "temp": temp, "L5": l5, "L10": l10,
                "osciladores": {"L5": _osc_stats(pb, l5), "L10": _osc_stats(pb, l10),
                                "n_base": len(base), "incluye_temporada_anterior": len(base) > len(ts)}}


def estadisticas(liga):
    k = ("eq", liga)
    if k not in _CACHE:
        _CACHE[k] = EstadisticasEquipo(liga)
    return _CACHE[k]


# ================================================================== tenis
_INCOMPLETO = ("RET", "W/O", "DEF", "ABD", "UNP", "WALKOVER", "RETIRED")


def _sets_de(score):
    """'7-6(4) 3-6 6-4' -> [(7,6,True),(3,6,False),(6,4,False)] desde la vista del ganador; None si no se puede leer."""
    out = []
    for tok in str(score or "").replace(",", " ").split():
        t = tok.strip()
        if not t or t.upper() in _INCOMPLETO:
            continue
        tb = "(" in t
        base = t.split("(")[0]
        if "-" not in base:
            continue
        a, _, b = base.partition("-")
        if a.isdigit() and b.isdigit():
            out.append((int(a), int(b), tb))
    return out


def _incompleto(score):
    sc = str(score or "").upper()
    return any(k in sc for k in _INCOMPLETO)


def _dv(a, b, nd=3):
    return round(a / b, nd) if b else None


class FormaTenis:
    """Forma detallada por jugador: games, sets, tiebreaks, saque, resto, break points y breaks, por ventana."""

    def __init__(self):
        filas = _leer(io.DATOS("tenis.csv"))
        self.por = {}
        vistos = set()                       # TML repite algunos partidos de torneos por equipos con otra fecha de torneo
        for r in filas:
            f = str(r.get("tourney_date") or "")
            w, l = r.get("winner_name"), r.get("loser_name")
            if not (f and w and l):
                continue
            k = (r.get("tourney_id"), r.get("round"), w, l)
            if k in vistos:
                continue
            vistos.add(k)
            ordn = (f, _f(r.get("match_num")) or 0.0)
            self.por.setdefault(w, []).append((ordn, True, r))
            self.por.setdefault(l, []).append((ordn, False, r))
        for lst in self.por.values():
            lst.sort(key=lambda x: x[0])

    @staticmethod
    def _fecha(s):
        s = str(s)
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]) if len(s) == 8 and s.isdigit() else s[:10]

    # ---------------------------------------------------------------- agregados
    @staticmethod
    def _agregar(xs):
        """Estadisticas agrupadas (suma y luego cociente) de una lista de (orden, gano, fila)."""
        n = len(xs)
        if not n:
            return {"partidos": 0}
        w = sum(1 for _, g, _ in xs if g)
        out = {"partidos": n, "ganados": w, "perdidos": n - w, "pct_victorias": round(w / n, 3)}
        # --- games, sets, tiebreaks (solo partidos completos)
        gf = gc = sets = sf = tb = comp = max_sets = mins = n_min = 0
        for _, g, r in xs:
            if _incompleto(r.get("score")):
                continue
            ss = _sets_de(r.get("score"))
            if not ss:
                continue
            comp += 1
            for a, b, t in ss:
                gf += a if g else b
                gc += b if g else a
                sf += 1 if ((a > b) == g) else 0
                tb += 1 if t else 0
            sets += len(ss)
            bo = int(_f(r.get("best_of")) or 3)
            if len(ss) == bo:
                max_sets += 1
            m = _f(r.get("minutes"))
            if m and m > 0:
                mins += m; n_min += 1
        if comp:
            out["games"] = {"partidos_completos": comp, "sets_por_partido": _dv(sets, comp, 2),
                            "games_por_partido": _dv(gf + gc, comp, 2), "games_ganados_pp": _dv(gf, comp, 2),
                            "games_perdidos_pp": _dv(gc, comp, 2), "pct_games_ganados": _dv(gf, gf + gc),
                            "games_por_set": _dv(gf + gc, sets, 2), "sets_ganados_pct": _dv(sf, sets),
                            "tiebreaks_por_partido": _dv(tb, comp, 2),
                            "pct_partidos_al_maximo_de_sets": _dv(max_sets, comp),
                            "minutos_por_partido": _dv(mins, n_min, 1)}
        # --- puntos y break points (solo partidos con estadisticas)
        A = {k: 0.0 for k in ("ace", "df", "svpt", "in1", "won1", "won2", "svg", "bps", "bpf",
                             "o_ace", "o_df", "o_svpt", "o_in1", "o_won1", "o_won2", "o_svg", "o_bps", "o_bpf")}
        m = 0
        for _, g, r in xs:
            p, q = ("w_", "l_") if g else ("l_", "w_")
            mi = {k: _f(r.get(p + c)) for k, c in (("ace", "ace"), ("df", "df"), ("svpt", "svpt"), ("in1", "1stIn"),
                  ("won1", "1stWon"), ("won2", "2ndWon"), ("svg", "SvGms"), ("bps", "bpSaved"), ("bpf", "bpFaced"))}
            op = {"o_" + k: _f(r.get(q + c)) for k, c in (("ace", "ace"), ("df", "df"), ("svpt", "svpt"), ("in1", "1stIn"),
                  ("won1", "1stWon"), ("won2", "2ndWon"), ("svg", "SvGms"), ("bps", "bpSaved"), ("bpf", "bpFaced"))}
            if None in mi.values() or None in op.values() or not mi["svpt"] or not op["o_svpt"]:
                continue
            for k, v in list(mi.items()) + list(op.items()):
                A[k] += v
            m += 1
        if m:
            sv_w = A["won1"] + A["won2"]
            o_sv_w = A["o_won1"] + A["o_won2"]
            ret_w = A["o_svpt"] - o_sv_w                      # puntos que gane al resto
            br_c, br_h = A["bpf"] - A["bps"], A["o_bpf"] - A["o_bps"]
            out["saque"] = {"partidos_con_stats": m, "ace_pct": _dv(A["ace"], A["svpt"]), "doble_falta_pct": _dv(A["df"], A["svpt"]),
                            "primer_saque_pct": _dv(A["in1"], A["svpt"]), "gana_con_1er_saque": _dv(A["won1"], A["in1"]),
                            "gana_con_2do_saque": _dv(A["won2"], A["svpt"] - A["in1"]),
                            "puntos_ganados_al_saque": _dv(sv_w, A["svpt"]), "aces_por_partido": _dv(A["ace"], m, 2),
                            "dobles_faltas_por_partido": _dv(A["df"], m, 2), "games_al_saque_por_partido": _dv(A["svg"], m, 1)}
            out["resto"] = {"puntos_ganados_al_resto": _dv(ret_w, A["o_svpt"]), "aces_recibidos_pct": _dv(A["o_ace"], A["o_svpt"]),
                            "gana_vs_1er_saque_rival": _dv(A["o_in1"] - A["o_won1"], A["o_in1"]),
                            "gana_vs_2do_saque_rival": _dv((A["o_svpt"] - A["o_in1"]) - A["o_won2"], A["o_svpt"] - A["o_in1"]),
                            "dominance_ratio": _dv(_dv(ret_w, A["o_svpt"], 6) or 0, 1 - (_dv(sv_w, A["svpt"], 6) or 0), 3),
                            "puntos_ganados_total": _dv(sv_w + ret_w, A["svpt"] + A["o_svpt"])}
            out["breaks"] = {"bp_enfrentados_pp": _dv(A["bpf"], m, 2), "bp_salvados_pct": _dv(A["bps"], A["bpf"]),
                             "breaks_concedidos_pp": _dv(br_c, m, 2), "hold_pct": _dv(A["svg"] - br_c, A["svg"]),
                             "bp_creados_pp": _dv(A["o_bpf"], m, 2), "bp_convertidos_pct": _dv(br_h, A["o_bpf"]),
                             "breaks_hechos_pp": _dv(br_h, m, 2), "break_pct": _dv(br_h, A["o_svg"]),
                             "breaks_totales_pp": _dv(br_c + br_h, m, 2)}
        return out

    @staticmethod
    def _rec(xs):
        w = sum(1 for _, g, _ in xs if g)
        return {"n": len(xs), "w": w, "l": len(xs) - w, "pct": round(w / len(xs), 3) if xs else None}

    def jugador(self, nombre, superficie=None, fecha_ref=None, mejor_de=None):
        lst = self.por.get(nombre) or []
        if not lst:
            return None
        ult = lst[-1][2]
        ult_f = self._fecha(ult.get("tourney_date"))
        ref = fecha_ref or ult_f
        try:
            d_ref = dt.date.fromisoformat(ref[:10])
            lim = (d_ref - dt.timedelta(days=365)).isoformat()
            lim14 = (d_ref - dt.timedelta(days=14)).isoformat()
        except ValueError:
            lim, lim14 = "", ""
        ano = [x for x in lst if self._fecha(x[2].get("tourney_date")) >= lim]
        u10, u5 = lst[-10:], lst[-5:]

        sup = {}
        for sname in ("Hard", "Clay", "Grass", "Carpet"):
            xs = [x for x in ano if (x[2].get("surface") or "").lower() == sname.lower()]
            if xs:
                sup[sname] = self._agregar(xs)
        fmt = {}
        for bo in (3, 5):
            xs = [x for x in ano if int(_f(x[2].get("best_of")) or 3) == bo]
            if xs:
                fmt["mejor_de_%d" % bo] = self._agregar(xs)
        # records contra tipo de rival (12 meses)
        def rival(x):
            g, r = x[1], x[2]
            return (r.get("loser_hand") if g else r.get("winner_hand")), _f(r.get("loser_rank") if g else r.get("winner_rank"))
        vs = {"zurdos": self._rec([x for x in ano if rival(x)[0] == "L"]),
              "diestros": self._rec([x for x in ano if rival(x)[0] == "R"]),
              "top10": self._rec([x for x in ano if rival(x)[1] is not None and rival(x)[1] <= 10]),
              "top11_50": self._rec([x for x in ano if rival(x)[1] is not None and 10 < rival(x)[1] <= 50]),
              "top51_100": self._rec([x for x in ano if rival(x)[1] is not None and 50 < rival(x)[1] <= 100]),
              "fuera_top100": self._rec([x for x in ano if rival(x)[1] is not None and rival(x)[1] > 100])}
        rk = rkp = None
        for _, g, r in reversed(lst):
            rk = _f(r.get("winner_rank" if g else "loser_rank"))
            rkp = _f(r.get("winner_rank_points" if g else "loser_rank_points"))
            if rk is not None:
                break
        pre = "winner_" if lst[-1][1] else "loser_"
        perfil = {"mano": ult.get(pre + "hand"), "altura_cm": _f(ult.get(pre + "ht")), "pais": ult.get(pre + "ioc"),
                  "edad": _f(ult.get(pre + "age")), "ranking": rk, "puntos_ranking": rkp}
        racha = ""
        r0 = lst[-1][1]; n = 0
        for _, g, _ in reversed(lst):
            if g == r0:
                n += 1
            else:
                break
        racha = "%s%d" % ("W" if r0 else "L", n)
        ultimos = []
        for _, g, r in reversed(u10):
            ultimos.append({"fecha": self._fecha(r.get("tourney_date")), "torneo": r.get("tourney_name"),
                            "superficie": r.get("surface"), "ronda": r.get("round"),
                            "rival": r.get("loser_name") if g else r.get("winner_name"),
                            "rank_rival": _f(r.get("loser_rank") if g else r.get("winner_rank")),
                            "r": "W" if g else "L", "marcador": r.get("score"), "minutos": _f(r.get("minutes"))})
        rec10, rec12 = self._rec(u10), self._rec(ano)
        osc = {"forma": round((rec10["pct"] or 0.0) - (rec12["pct"] or 0.0), 3)}
        osc["tendencia"] = "Subiendo" if osc["forma"] >= 0.15 else ("Bajando" if osc["forma"] <= -0.15 else "Estable")
        rec14 = [x for x in lst if self._fecha(x[2].get("tourney_date")) >= lim14]
        mins14 = sum(_f(x[2].get("minutes")) or 0.0 for x in rec14)
        try:
            dias_desde = (d_ref - dt.date.fromisoformat(ult_f)).days
        except ValueError:
            dias_desde = None
        det = {"L5": self._agregar(u5), "L10": self._agregar(u10), "12m": self._agregar(ano)}
        out = {"jugador": nombre, "ultimo_partido": ult_f, "ranking": rk, "racha": racha, "perfil": perfil,
               "ultimos10": ultimos, "record_12m": rec12, "record_L10": rec10,
               "por_superficie_12m": {k: {"n": v["partidos"], "w": v["ganados"], "l": v["perdidos"], "pct": v["pct_victorias"]}
                                      for k, v in sup.items()},
               "detalle": det, "detalle_superficie_12m": sup, "detalle_formato_12m": fmt, "records_vs_12m": vs,
               "carga": {"dias_desde_ultimo": dias_desde, "partidos_14d": len(rec14), "minutos_14d": round(mins14, 0)},
               "osciladores": osc}
        if superficie and superficie in sup:
            out["superficie_hoy"] = {"superficie": superficie, **out["por_superficie_12m"][superficie]}
            out["detalle_superficie_hoy"] = sup[superficie]
        return out

    def h2h(self, a, b, max_ult=5):
        la = [x for x in (self.por.get(a) or []) if
              (x[2].get("loser_name") if x[1] else x[2].get("winner_name")) == b]
        if not la:
            return {"partidos": 0}
        wa = sum(1 for _, g, _ in la if g)
        por_sup = {}
        for _, g, r in la:
            d = por_sup.setdefault(r.get("surface") or "?", [0, 0])
            d[0 if g else 1] += 1
        ult = [{"fecha": self._fecha(r.get("tourney_date")), "torneo": r.get("tourney_name"),
                "superficie": r.get("surface"), "ronda": r.get("round"), "ganador": r.get("winner_name"),
                "marcador": r.get("score")} for _, _, r in reversed(la[-max_ult:])]
        return {"partidos": len(la), "gana_a": wa, "gana_b": len(la) - wa,
                "por_superficie": {k: {"gana_a": v[0], "gana_b": v[1]} for k, v in por_sup.items()}, "ultimos": ult}


def forma_tenis():
    if "tenis" not in _CACHE:
        _CACHE["tenis"] = FormaTenis()
    return _CACHE["tenis"]
