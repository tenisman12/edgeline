# -*- coding: utf-8 -*-
"""
nucleo/angulos.py - CAPA CUALITATIVA: angulos situacionales activos en un partido, con lo que se midio de cada uno.

Que hace:
  - Para un partido de salida/proximos.json calcula los angulos situacionales activos (descanso, segunda noche, gira,
    rachas, revancha, bajon, sandwich, primer juego en casa, fin de temporada, tras perder por mucho...) con las MISMAS
    definiciones que se midieron en utilidades/minar_situacionales.py (tanda 1, 8-oct-2026) y
    utilidades/minar_cualitativos.py (9-oct-2026). Usa datos/<deporte>.csv (juegos ya jugados) y proximos.json
    (el siguiente rival).
  - A cada angulo le pega su medicion fuera de muestra (modelos/angulos_medidos.json): cuanto rindio el lado al que
    apunta el angulo contra el modelo (pp), casos, z y veredicto; en los cualitativos tambien el TMLE con su IC 95 %.
  - NO cambia probabilidades, salvo las dos capas que pasaron y aprobo Alejandro (9-oct-2026): K14 ausencias en NBA y
    T1 minutos del partido anterior en ATP, que plataforma.py suma al logit con aplicar_capa(). El resto se muestra,
    se cuentan a favor / en contra del pick y se registran en salida/historial_angulos.csv para medirlos en vivo
    (utilidades/medir_angulos_vivo.py). Un angulo gana peso solo si pasa el protocolo con datos en vivo y Alejandro
    lo aprueba (regla 2 de CLAUDE.md).

Catalogo:  python -m nucleo.angulos --catalogo     (lee trabajo/minar/*_resultados.json y escribe modelos/angulos_medidos.json)
Solo stdlib.
"""
import bisect, csv, datetime as dt, io as _io, json, os, sys

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_CATALOGO = os.path.join(CODIGO, "modelos", "angulos_medidos.json")
FUERTE, DEBIL, MIN_J = 0.60, 0.40, 8          # iguales a minar_cualitativos.py
NEUTRO_PP = 1.0                               # |efecto medido| menor a esto no cuenta ni a favor ni en contra

NOMBRES = {
    "H1": "visita en segunda noche, local descansado", "H2": "local en segunda noche, visita descansada",
    "H4": "un dia de diferencia de descanso", "H6": "tercer juego en 4 noches", "H7": "carga de 7 dias",
    "H8": "regreso de pausa de 7+ dias", "H13": "gira del visitante (2+ seguidos de visita)", "H14": "regreso a casa tras gira de 3+",
    "H15": "ultimo juego de gira del visitante", "H16": "ida y vuelta: revancha inmediata", "H17": "tras prorroga o shootout",
    "H21": "tras perder por 4 o mas", "H22": "tras perder en prorroga/SO",
    "K1": "segunda noche", "K2": "tercer juego en 4 noches", "K3": "diferencia de descanso", "K4": "descanso de 4+ dias",
    "K8a": "gira del visitante (2+ seguidos de visita)", "K8b": "regreso a casa tras gira 3+", "K10": "tras perder por 20 o mas",
    "K11": "tras prorroga",
    "N4": "tras jugar lunes", "N5": "sale de bye contra semana corta", "N8": "segundo juego seguido de visita",
    "N12": "tras perder por 20 o mas",
    "B2": "primer juego tras dia libre", "B5": "dias seguidos jugando", "B10": "primer juego de serie",
    "B11": "ultimo juego de serie (getaway)", "B12": "evitar la barrida", "B13": "gira del visitante (2+ seguidos de visita)",
    "B14": "regreso a casa tras gira de 6+", "B15": "tras extra innings", "B21": "tras perder por 7 o mas",
    "F1": "diferencia de descanso", "F13": "tras perder por 3 o mas",
    "Q1": "revancha (perdio el ultimo cruce)", "Q2": "bajon tras ganarle a un fuerte", "Q3": "mirando adelante",
    "Q4": "sandwich", "Q5": "primer juego en casa", "Q6a": "racha de 5+ derrotas", "Q6b": "racha de 5+ victorias",
    "Q7": "fin de temporada: debil vs en contienda", "Q8": "partido divisional (local)", "Q9": "entrenador nuevo",
    "H18": "partido anterior fisico (castigos)", "N13": "tras ganar en tiempo extra",
    # tanda 3 (9-oct-2026)
    "H23": "cuarto juego en 6 noches", "H24": "altitud (Colorado, Utah)", "K12": "cuarto juego en 6 noches",
    "K13": "altitud (Denver, Utah)", "K14": "ausencias (minutos de los que faltan)",
    "P1": "rebote en playoffs (perdio el anterior)", "P2": "al borde de la eliminacion", "P3": "juego 7",
    "N14": "jueves por la noche", "N15": "costa oeste a la 1 pm en el este", "N17": "perro divisional",
    "B25": "altitud (Coors Field)", "F14": "altitud en Liga MX", "F15": "favorito tras fecha FIFA",
    "F16": "Champions entre semana", "F17": "pelea por no descender",
    "T1": "minutos del partido anterior", "T2": "partido anterior a la distancia", "T3": "carga de 14 dias",
    "T4": "cambio de superficie", "T5": "primer torneo tras un Grand Slam",
}

# liga en vivo -> grupos del catalogo donde se midio cada familia de codigos (el primero que tenga el codigo)
_BEIS = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")
_FUT = ("premier", "laliga", "seriea", "bundesliga", "ligue1", "ligamx", "mls")


def _grupos(liga):
    lg = (liga or "").lower()
    if lg == "nhl": return {"H": ["NHL"], "Q": ["NHL"], "P": ["NHL"]}
    if lg == "nba": return {"K": ["NBA"], "Q": ["NBA"], "P": ["NBA"]}
    if lg == "atp": return {"T": ["ATP"]}
    if lg == "wta": return {"T": ["WTA"]}
    if lg == "ncaamb": return {"K": ["NCAAMB"]}
    if lg == "nfl": return {"N": ["NFL"], "Q": ["NFL"]}
    if lg == "ncaafb": return {"N": ["NCAAFB"]}
    if lg == "mlb": return {"B": ["MLB", "TODAS"], "Q": ["BEISBOL"]}
    if lg in _BEIS: return {"B": ["TODAS"], "Q": ["BEISBOL"]}
    if lg in _FUT: return {"F": ["7 ligas", "LigaMX", "5 ligas"], "Q": ["FUTBOL"]}
    return {}


# ------------------------------------------------------------------ catalogo de mediciones
def construir_catalogo():
    """Lee los resultados del minado (base = modelo) y escribe modelos/angulos_medidos.json. Ningun numero se escribe a mano."""
    fuentes = [("trabajo/minar/2026-10-08_situacionales_tanda1_resultados.json", "trabajo/minar/2026-10-08_situacionales_tanda1.md"),
               ("trabajo/minar/2026-10-09_cualitativos_resultados.json", "trabajo/minar/2026-10-09_cualitativos.md"),
               ("trabajo/minar/2026-10-09_tanda3_resultados.json", "trabajo/minar/2026-10-09_tanda3.md")]
    cat = {}
    for ruta, md in fuentes:
        with _io.open(os.path.join(CODIGO, ruta), encoding="utf-8") as f:
            for r in json.load(f):
                if r.get("base") != "modelo":
                    continue
                k = "%s|%s" % (r["liga"], r["codigo"])
                cat[k] = {"grupo": r["liga"], "codigo": r["codigo"], "angulo": r["angulo"], "veredicto": r["veredicto"],
                          "n_activo_prueba": r.get("n_activo_prueba"), "z": r.get("z"), "efecto_pp": r.get("residuo_firmado_pp"),
                          "tmle_pp": r.get("tmle_pp"), "tmle_ic95": r.get("tmle_ic95"), "desde_prueba": r.get("desde_prueba"),
                          # +1: la hipotesis registrada dice que el lado al que apunta el angulo rinde MAS que el modelo
                          "signo_esperado": None if r.get("beta") is None else (1 if r["beta"] > 0 else -1) * (1 if r.get("direccion_ok") else -1),
                          "fuente": md}
    out = {"generado": dt.date.today().isoformat(),
           "como_leer": "efecto_pp = cuanto gano de mas (+) o de menos (-) el lado al que apunta el angulo contra el modelo "
                        "recalibrado, en el 30 % final (fuera de muestra). tmle_pp = efecto ajustado por la probabilidad del modelo "
                        "y la sede, en toda la muestra, con IC 95 %. Ninguno tiene peso en p: los que dicen 'pasa' (K14 NBA, "
                        "T1 ATP) esperan la aprobacion de Alejandro. Futbol de las tandas 1 y 2 se midio con el modelo de K 20 sin "
                        "olvido; la tanda 3 con K 40 y olvido 0.98.",
           "angulos": cat}
    with _io.open(RUTA_CATALOGO, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


_CAT = None


def catalogo():
    global _CAT
    if _CAT is None:
        try:
            with _io.open(RUTA_CATALOGO, encoding="utf-8") as f:
                _CAT = json.load(f).get("angulos") or {}
        except Exception:
            _CAT = {}
    return _CAT


def medicion(liga, codigo):
    g = _grupos(liga).get(codigo[0], [])
    for grupo in g:
        m = catalogo().get("%s|%s" % (grupo, codigo))
        if m:
            return m
    return None


# ------------------------------------------------------------------ calendario por equipo (juegos ya jugados)
def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


_CAL = {}


def _calendario(liga):
    """liga -> {equipo: [juego, ...]} ordenado. juego: fecha, gp, local, gf, ga, rival, ot, ip, pim."""
    lg = (liga or "").lower()
    if lg in _CAL:
        return _CAL[lg]
    dep = io.deporte_de(lg)
    T = {}
    try:
        filas = io.cargar_juegos(lg)
    except Exception:
        filas = []
    for r in filas:
        if dep == "futbol":
            gf, ga = _f(r.get("goals")), _f(r.get("goals_opp"))
        elif dep == "hockey":
            gf, ga = _f(r.get("goals")), _f(r.get("goals_opp"))
        elif dep == "beisbol":
            gf, ga = _f(r.get("runs")), _f(r.get("runs_opp"))
        else:
            gf, ga = _f(r.get("points")), _f(r.get("points_opp"))
        f = _d(r.get("game_date"))
        if gf is None or ga is None or f is None:
            continue
        fin = (r.get("ended_in") or "").strip()
        ot = None
        if dep == "hockey":
            ot = (fin in ("OT", "SO")) if fin else None
        elif lg == "nba":
            mins = _f(r.get("nba_min")); ot = bool(mins and mins > 241)
        gpk = str(r.get("gamePk") or r.get("game_id") or "")
        post = (r.get("tipo") == "POST") or (dep == "hockey" and len(gpk) == 10 and gpk[4:6] == "03")
        T.setdefault(r.get("team"), []).append(dict(fecha=f, gp=gpk, local=str(r.get("is_home")) in ("1", "1.0", "True"), gf=gf, ga=ga,
                                                    rival=r.get("opp"), ot=ot, ip=_f(r.get("pit_inningsPitched")),
                                                    pim=_f(r.get("pim")), post=post))
    if dep == "futbol":                                   # Champions solo para el descanso (como en el minado)
        ruta = io.ruta("datos", "equipos", "espn_champions_equipos.csv")
        if os.path.exists(ruta) and T:
            with _io.open(ruta, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if r.get("team") in T and _d(r.get("game_date")):
                        T[r["team"]].append(dict(fecha=_d(r["game_date"]), gp="ch" + str(r.get("game_id")), local=str(r.get("is_home")) in ("1", "1.0"),
                                                 gf=None, ga=None, rival=r.get("opp"), ot=None, ip=None, champions=True))
    for L in T.values():
        L.sort(key=lambda g: (g["fecha"], g["gp"]))
    _CAL[lg] = T
    return T


def _previos(L, fecha):
    """juegos antes de la fecha (sin el de hoy)."""
    k = bisect.bisect_left([g["fecha"] for g in L], fecha)
    return L[:k]


def _temporada(P, fecha):
    """juegos de la temporada en curso: hacia atras sin hueco de mas de 60 dias (hoy incluido como punto final)."""
    if not P or (fecha - P[-1]["fecha"]).days > 60:
        return []
    i = len(P) - 1
    while i > 0 and (P[i]["fecha"] - P[i - 1]["fecha"]).days <= 60:
        i -= 1
    return P[i:]


def _temporada_anterior(P, fecha):
    T = _temporada(P, fecha)
    resto = P[:len(P) - len(T)]
    if not resto:
        return []
    return _temporada(resto, resto[-1]["fecha"] + dt.timedelta(days=1))


def _wpct(L, fecha):
    """% de victorias de la temporada antes de la fecha (empate medio), con 8 juegos o mas; si no, None."""
    S = [g for g in _temporada(_previos(L, fecha), fecha) if g["gf"] is not None]
    if len(S) < MIN_J:
        return None
    return sum(1.0 if g["gf"] > g["ga"] else (0.5 if g["gf"] == g["ga"] else 0.0) for g in S) / len(S)


def _en_ventana(P, fecha, dias):
    return sum(1 for g in P if (fecha - g["fecha"]).days <= dias)


def _visitas_seguidas(P, local_hoy, incluye_actual=True):
    c = 1 if (incluye_actual and not local_hoy) else 0
    if incluye_actual and local_hoy:
        return 0
    j = len(P) - 1
    while j >= 0 and not P[j]["local"]:
        c += 1; j -= 1
    return c


def _dias_seguidos(P, fecha):
    fechas = {g["fecha"] for g in P}; c = 0
    while (fecha - dt.timedelta(days=c + 1)) in fechas:
        c += 1
    return c


def _ind(v):
    return 1 if v else 0


# ------------------------------------------------------------------ angulos de un partido
def _equipo(p, lado):
    e = (p.get("emparejado") or {}).get(lado)
    if e:
        return e
    fo = ((p.get("forma") or {}).get(lado) or {}).get("equipo")
    return fo or p[lado]["nombre"]


def _siguiente(p, equipo, todos):
    """siguiente juego del equipo en proximos.json despues de este: (fecha, rival, local) o None."""
    f0 = p["fecha"]; mejor = None
    for q in todos:
        if q is p or q.get("liga") != p.get("liga") or q["fecha"] <= f0:
            continue
        for lado, otro in (("home", "away"), ("away", "home")):
            if _equipo(q, lado) == equipo:
                c = (q["fecha"], _equipo(q, otro), lado == "home")
                if mejor is None or c[0] < mejor[0]:
                    mejor = c
    return mejor


# ------------------------------------------------------------------ ayudas de la tanda 3 y de los medidos que faltaban
ALT_NHL = {"COL", "UTA"}
ALT_NBA = {"DEN", "UTA"}
ALT_MX = {"Toluca", "Club America", "Cruz Azul", "UNAM Pumas", "Pachuca", "Puebla"}
DESCENSO = {"premier", "laliga", "seriea", "bundesliga", "ligue1"}
PAC_NFL = {"SEA", "SF", "LA", "LAC", "LV"}
ESTE_NFL = {"ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND", "JAX", "MIA", "NE", "NYG", "NYJ", "PHI", "PIT", "TB", "WAS"}
_ALIAS_NFL = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}
SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")


def _alias_nfl(t):
    return _ALIAS_NFL.get(t, t)


def _hora_et(p):
    """hora de inicio en el este (texto 'HH:MM', 24 h) desde el estado de ESPN ('10/12 - 1:00 PM EDT'); None si no viene."""
    import re
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)\s*E[DS]T", str(p.get("estado") or ""))
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)
    return "%02d:%s" % (h, m.group(2))


_NFL = None


def _nfl_lineas():
    """de datos/mercado/nfl_lineas.csv: pares divisionales, quien gano en tiempo extra y la secuencia de entrenadores."""
    global _NFL
    if _NFL is not None:
        return _NFL
    _NFL = {"div": set(), "ot_gano": {}, "coach": {}}
    ruta = io.ruta("datos", "mercado", "nfl_lineas.csv")
    if not os.path.exists(ruta):
        return _NFL
    with _io.open(ruta, encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            h, a = _alias_nfl(x.get("home_team")), _alias_nfl(x.get("away_team"))
            f = (x.get("gameday") or "")[:10]
            if x.get("div_game") == "1":
                _NFL["div"].add(frozenset((h, a)))
            hs, as_ = _f(x.get("home_score")), _f(x.get("away_score"))
            if x.get("overtime") == "1" and hs is not None and as_ is not None:
                _NFL["ot_gano"][(h if hs > as_ else a, f)] = True
            for t, c in ((h, x.get("home_coach")), (a, x.get("away_coach"))):
                if c and hs is not None:
                    _NFL["coach"].setdefault(t, []).append((f, c))
    for v in _NFL["coach"].values():
        v.sort()
    return _NFL


def _coach_nuevo(L, team, fecha):
    """igual que minar_cualitativos: primeros 3 juegos tras un cambio de entrenador a media temporada. Hoy se asume el
    entrenador del ultimo juego."""
    S = [c for c in L["coach"].get(team, []) if c[0] < fecha.isoformat()]
    if len(S) < 2:
        return False
    hoy = S[-1][1]; cambio = None
    for i in range(1, len(S)):
        mismo = (_d(S[i][0]) - _d(S[i - 1][0])).days <= 60
        if mismo and S[i][1] != S[i - 1][1]:
            cambio = i
        elif not mismo:
            cambio = None
    if (fecha - _d(S[-1][0])).days > 60 or cambio is None:
        return False
    return len(S) - cambio < 3 and S[cambio][1] == hoy


def _playoffs(Ph, eh, ea, fecha):
    """serie de playoffs en curso entre los dos (juegos POST de la temporada entre ellos, el ultimo hace 7 dias o menos)."""
    S = _temporada(Ph, fecha)
    juegos = [g for g in S if g.get("post") and g["rival"] == ea]
    if not juegos or (fecha - juegos[-1]["fecha"]).days > 7:
        return {}
    wh = sum(1 for g in juegos if g["gf"] > g["ga"]); wa = len(juegos) - wh
    out = {"P1": 1 if juegos[-1]["gf"] < juegos[-1]["ga"] else -1, "P3": 1 if (wh == 3 and wa == 3) else 0}
    out["P2"] = 0 if out["P3"] else (1 if (wa == 3 and wh < 3) else (-1 if (wh == 3 and wa < 3) else 0))
    return out


def _descenso(T, eh, ea, fecha):
    """F17: tabla as-of con los juegos de liga de la temporada en curso (3 puntos por victoria)."""
    tab = {}
    for e, L in T.items():
        S = [g for g in _temporada([g for g in _previos(L, fecha) if g["gf"] is not None], fecha)]
        if S:
            tab[e] = (sum(3 if g["gf"] > g["ga"] else (1 if g["gf"] == g["ga"] else 0) for g in S), len(S))
    n = len(tab)
    if n < 16 or eh not in tab or ea not in tab:
        return None
    tot = 2 * (n - 1)
    orden = sorted((v[0] for v in tab.values()), reverse=True)
    linea, cuarto = orden[n - 4], orden[3]
    amen = lambda e: tab[e][1] >= tot - 10 and tab[e][0] <= linea + 3
    tranq = lambda e: linea + 8 < tab[e][0] < cuarto - 8
    return 1 if (amen(eh) and tranq(ea)) else (-1 if (amen(ea) and tranq(eh)) else 0)


_NBA_MIN = None


def _ausencias_nba(p, fecha):
    """K14 en vivo: jugadores 'Out' en el reporte de ESPN que en los ultimos 5 juegos del equipo jugaron 3 o mas con 20+
    minutos de promedio (misma regla que utilidades/nba_ausencias.py). x = (minutos de la visita - del local) / 48."""
    global _NBA_MIN
    les = (p.get("contexto") or {}).get("lesiones") or {}
    if not les:
        return None
    if _NBA_MIN is None:
        _NBA_MIN = {}
        for sub in ("jugadores", "jugadores_recientes"):
            ruta = io.ruta("datos", sub, "espn_nba_jugadores.csv")
            if not os.path.exists(ruta):
                continue
            with _io.open(ruta, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if (r.get("liga") or "nba").lower() != "nba":
                        continue
                    g = _NBA_MIN.setdefault(r.get("team"), {}).setdefault((r.get("game_date") or "")[:10] + "|" + str(r.get("game_id")), {})
                    g[r.get("jugador")] = _f(r.get("minutes")) or 0.0
    def perdidos(lado):
        juegos = sorted((k, v) for k, v in (_NBA_MIN.get(p[lado]["nombre"]) or {}).items() if k[:10] < fecha.isoformat())[-5:]
        if len(juegos) < 3:
            return None
        tot = 0.0
        for l in les.get(lado) or []:
            if (l.get("estado") or "") != "Out":
                continue
            ms = [v.get(l.get("jugador"), 0.0) for _, v in juegos]
            jugados = [m for m in ms if m > 0]
            if len(jugados) >= 3 and sum(jugados) / len(jugados) >= 20.0:
                tot += sum(jugados) / len(jugados)
        return tot
    mh, ma = perdidos("home"), perdidos("away")
    if mh is None or ma is None:
        return None
    return (ma - mh) / 48.0


_TEN = None
_RONDA = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "ER": 3.5, "R128": 4, "R64": 5, "R32": 6, "RR": 6.5, "R16": 7, "QF": 8, "SF": 9, "BR": 9.5, "F": 10}


def _tenis_hist():
    global _TEN
    if _TEN is not None:
        return _TEN
    _TEN = {}
    ruta = io.ruta("datos", "tenis.csv")
    if not os.path.exists(ruta):
        return _TEN
    with _io.open(ruta, encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            td = r.get("tourney_date") or ""
            try:
                f = dt.date(int(td[:4]), int(td[4:6]), int(td[6:8]))
            except ValueError:
                continue
            if f.year < 2025:
                continue
            bo = 5 if str(r.get("best_of")) == "5" else 3
            sc = str(r.get("score") or "")
            sets = sum(1 for t in sc.split() if "-" in t and t[:1].isdigit())
            m = {"fecha": f, "tid": r.get("tourney_id"), "torneo": (r.get("tourney_name") or "").lower(), "sup": r.get("surface"),
                 "nivel": r.get("tourney_level"), "min": _f(r.get("minutes")), "orden": (td, _RONDA.get(r.get("round"), 5)),
                 "distancia": sets >= bo and "RET" not in sc and "W/O" not in sc}
            for n in (r.get("winner_name"), r.get("loser_name")):
                if n:
                    _TEN.setdefault(n, []).append(m)
    for v in _TEN.values():
        v.sort(key=lambda m: m["orden"])
    return _TEN


# ------------------------------------------------------------------ capas con peso (aprobadas el 9-oct-2026)
CON_PESO = {("nba", "K14"), ("atp", "T1")}     # ya entran en p (plataforma.py); en la capa cualitativa no se cuentan dos veces
_CAPAS = None


def capas_aprobadas():
    """modelos/capas_ausencias_minutos.json (utilidades/pesos_ausencias_minutos.py)."""
    global _CAPAS
    if _CAPAS is None:
        try:
            with _io.open(os.path.join(CODIGO, "modelos", "capas_ausencias_minutos.json"), encoding="utf-8") as f:
                _CAPAS = json.load(f)
        except Exception:
            _CAPAS = {}
    return _CAPAS


def _min_previo(nombre, torneo, hoy):
    """minutos del ultimo partido del jugador en este torneo (mismo criterio que la tanda 3); None si no jugo o sin dato."""
    torneo = (torneo or "").lower()
    L = [m for m in _tenis_hist().get(nombre, []) if m["fecha"] <= hoy and (hoy - m["fecha"]).days <= 14
         and m["torneo"] and m["torneo"] in torneo]
    return L[-1]["min"] if L else None


def x_minutos_atp(j_home, j_away, torneo, fecha):
    """T1: (minutos previos del visitante - del local) / 60; None si alguno no ha jugado en el torneo."""
    hoy = fecha if isinstance(fecha, dt.date) else _d(fecha)
    if not hoy:
        return None
    mh, ma = _min_previo(j_home, torneo, hoy), _min_previo(j_away, torneo, hoy)
    if not mh or not ma:
        return None
    return (ma - mh) / 60.0


def x_ausencias_nba(g, fecha):
    """K14 desde el registro del partido (contexto.lesiones de ESPN, nombres completos de los equipos)."""
    hoy = fecha if isinstance(fecha, dt.date) else _d(fecha)
    return _ausencias_nba({"contexto": g.get("contexto") or {}, "home": g["home"], "away": g["away"]}, hoy) if hoy else None


def aplicar_capa(p_home, liga, codigo, x):
    """logit(p) + beta * x con el beta de modelos/capas_ausencias_minutos.json. Devuelve (p, detalle)."""
    import math as _m
    clave = {("nba", "K14"): "nba_K14", ("atp", "T1"): "atp_T1"}.get(((liga or "").lower(), codigo))
    c = (capas_aprobadas() or {}).get(clave) or {}
    if x is None or c.get("beta") is None:
        return p_home, {"aplicado": False, "motivo": "sin dato para %s" % codigo if x is None else "sin coeficiente"}
    p0 = min(max(p_home, 1e-4), 1 - 1e-4)
    p1 = 1.0 / (1.0 + _m.exp(-(_m.log(p0 / (1 - p0)) + c["beta"] * x)))
    return p1, {"aplicado": True, "codigo": codigo, "nombre": NOMBRES.get(codigo), "x": round(x, 3), "beta": c["beta"],
                "ajuste_pp": round(100 * (p1 - p0), 1), "p_sin_capa": round(p0, 4),
                "fuente": "modelos/capas_ausencias_minutos.json (tanda 3, aprobada 9-oct-2026)"}


def _tenis(p, liga):
    """T1-T5 en vivo con las definiciones de minar_angulos_tanda3.tenis. x + apunta al jugador local (home)."""
    H = _tenis_hist()
    hoy = _d(p.get("fecha"))
    torneo = (p.get("torneo") or "").lower(); sup = p.get("superficie") or p.get("superficie_estimada")
    if not hoy or not H:
        return []
    def info(lado):
        n = ((p.get("forma") or {}).get(lado) or {}).get("jugador") or p[lado]["nombre"]
        L = [m for m in H.get(n, []) if m["fecha"] <= hoy]
        if not L:
            return None
        mismo = [m for m in L if (hoy - m["fecha"]).days <= 14 and m["torneo"] and m["torneo"] in torneo]
        ini = mismo[0]["fecha"] if mismo else hoy
        prev_t = mismo[-1] if mismo else None
        carga = len(mismo) + sum(1 for m in L if m not in mismo and 0 < (ini - m["fecha"]).days <= 14)
        antes = [m for m in L if m not in mismo]
        prev = antes[-1] if antes else None
        cambio = None if (prev is None or (ini - prev["fecha"]).days > 60) else (False if mismo else (prev["sup"] != sup))
        gs = (not any(s in torneo for s in SLAMS)) and any(m["nivel"] == "G" and 0 < (ini - m["fecha"]).days <= 28 for m in antes[-12:])
        return prev_t, carga, cambio, gs
    ih, ia = info("home"), info("away")
    if not ih or not ia:
        return []
    x = {}
    mh, ma = (ih[0] or {}).get("min"), (ia[0] or {}).get("min")
    if mh and ma:
        x["T1"] = (ma - mh) / 60.0
    if ih[0] and ia[0]:
        x["T2"] = _ind(ia[0]["distancia"]) - _ind(ih[0]["distancia"])
    x["T3"] = (ia[1] - ih[1]) / 5.0
    if ih[2] is not None and ia[2] is not None:
        x["T4"] = _ind(ia[2]) - _ind(ih[2])
    x["T5"] = _ind(ia[3]) - _ind(ih[3])
    out = []
    for c, v in x.items():
        if v:
            lado = "home" if v > 0 else "away"
            out.append({"codigo": c, "nombre": NOMBRES.get(c, c), "lado": lado, "equipo": p[lado]["nombre"], "x": round(v, 3),
                        "medicion": medicion(liga, c), "con_peso": (liga, c) in CON_PESO})
    return out


def calcular(p, todos=None):
    """Angulos activos del partido. Devuelve lista de dicts: codigo, nombre, lado (home/away al que apunta el angulo),
    equipo, x, medicion (o None). Vacia si no hay calendario o la liga no tiene angulos medidos."""
    liga = (p.get("liga") or "").lower()
    G = _grupos(liga)
    if not G or p.get("pretemporada"):
        return []
    if "T" in G:
        return _tenis(p, liga)
    fecha = _d(p.get("fecha"))
    T = _calendario(liga)
    eh, ea = _equipo(p, "home"), _equipo(p, "away")
    if not fecha or eh not in T or ea not in T:
        return []
    Ph, Pa = _previos(T[eh], fecha), _previos(T[ea], fecha)
    if not Ph or not Pa:
        return []
    ph, pa = Ph[-1], Pa[-1]
    rh, ra = (fecha - ph["fecha"]).days, (fecha - pa["fecha"]).days
    dep = io.deporte_de(liga)
    x = {}
    if "H" in G:
        bh, ba = rh == 1, ra == 1
        x["H1"] = _ind(ba and not bh)
        x["H2"] = _ind(bh and not ba)
        dd = rh - ra
        x["H4"] = (1 if dd == 1 else -1) if abs(dd) == 1 else 0
        x["H6"] = _ind(_en_ventana(Pa, fecha, 3) >= 2) - _ind(_en_ventana(Ph, fecha, 3) >= 2)
        c7 = _en_ventana(Pa, fecha, 7) - _en_ventana(Ph, fecha, 7)
        x["H7"] = c7
        x["H8"] = _ind(rh >= 7) - _ind(ra >= 7)
        vs = _visitas_seguidas(Pa, False)
        x["H13"] = min(max(vs - 1, 0), 5)
        x["H14"] = _ind(_visitas_seguidas(Ph, True, incluye_actual=False) >= 3)
        sa = _siguiente(p, ea, todos or [])
        x["H15"] = _ind(sa is not None and sa[2] and vs >= 3)
        x16 = 0
        if ph["rival"] == ea and pa["rival"] == eh and ph["fecha"] == pa["fecha"] and rh <= 3:
            x16 = 1 if ph["gf"] < ph["ga"] else -1
        x["H16"] = x16
        if ph["ot"] is not None and pa["ot"] is not None:
            x["H17"] = _ind(pa["ot"]) - _ind(ph["ot"])
            x["H22"] = _ind(ph["ot"] and ph["gf"] < ph["ga"]) - _ind(pa["ot"] and pa["gf"] < pa["ga"])
        x["H21"] = _ind(ph["ga"] - ph["gf"] >= 4) - _ind(pa["ga"] - pa["gf"] >= 4)
    if "K" in G and rh <= 30 and ra <= 30:
        x["K1"] = _ind(ra == 1) - _ind(rh == 1)
        x["K2"] = _ind(_en_ventana(Pa, fecha, 3) >= 2) - _ind(_en_ventana(Ph, fecha, 3) >= 2)
        x["K3"] = max(-2, min(2, rh - ra))
        x["K4"] = _ind(rh >= 4) - _ind(ra >= 4)
        x["K8a"] = min(max(_visitas_seguidas(Pa, False) - 1, 0), 5)
        x["K8b"] = _ind(_visitas_seguidas(Ph, True, incluye_actual=False) >= 3)
        x["K10"] = _ind(ph["ga"] - ph["gf"] >= 20) - _ind(pa["ga"] - pa["gf"] >= 20)
        if liga == "nba":
            x["K11"] = _ind(pa["ot"]) - _ind(ph["ot"])
    if "N" in G and rh <= 40 and ra <= 40:
        if liga == "nfl":
            x["N4"] = _ind(pa["fecha"].weekday() == 0) - _ind(ph["fecha"].weekday() == 0)
        x["N5"] = 1 if (rh >= 13 and ra <= 5) else (-1 if (ra >= 13 and rh <= 5) else 0)
        x["N8"] = _ind(not pa["local"])
        x["N12"] = _ind(ph["ga"] - ph["gf"] >= 20) - _ind(pa["ga"] - pa["gf"] >= 20)
    if "B" in G and rh <= 20 and ra <= 20:
        x["B2"] = _ind(rh >= 2) - _ind(ra >= 2)
        x["B5"] = (min(_dias_seguidos(Pa, fecha), 20) - min(_dias_seguidos(Ph, fecha), 20)) / 10.0
        # serie desde el calendario del local
        j = len(Ph); num = 1; prev_f = fecha
        while j - 1 >= 0 and Ph[j - 1]["rival"] == ea and Ph[j - 1]["local"] and (prev_f - Ph[j - 1]["fecha"]).days <= 1:
            j -= 1; num += 1; prev_f = Ph[j]["fecha"]
        previos = Ph[j:]
        sh = _siguiente(p, eh, todos or [])
        ultimo = not (sh is not None and sh[1] == ea and sh[2] and (_d(sh[0]) - fecha).days <= 1)
        x["B10"] = _ind(num == 1)
        x["B11"] = _ind(ultimo and num >= 2) if todos is not None else 0
        x["B12"] = (_ind(all(g["gf"] < g["ga"] for g in previos)) - _ind(all(g["gf"] > g["ga"] for g in previos))) if len(previos) >= 2 else 0
        x["B13"] = min(max(_visitas_seguidas(Pa, False) - 1, 0), 12) / 10.0
        x["B14"] = _ind(_visitas_seguidas(Ph, True, incluye_actual=False) >= 6)
        ext = lambda g: bool(g["ip"] is not None and g["ip"] >= 9.95)
        x["B15"] = _ind(ext(pa)) - _ind(ext(ph))
        x["B21"] = _ind(ph["ga"] - ph["gf"] >= 7) - _ind(pa["ga"] - pa["gf"] >= 7)
    if "F" in G and rh <= 30 and ra <= 30:
        x["F1"] = max(-3, min(3, rh - ra)) / 3.0
        perdio3 = lambda g: g["gf"] is not None and g["ga"] - g["gf"] >= 3      # el anterior puede ser de Champions (sin marcador)
        x["F13"] = _ind(perdio3(ph)) - _ind(perdio3(pa))
    if "Q" in G:
        info = {}
        for lado, e, opp, P, loc in (("H", eh, ea, Ph, True), ("A", ea, eh, Pa, False)):
            Pl = [g for g in P if g["gf"] is not None]          # solo liga (sin Champions)
            S = _temporada(Pl, fecha)
            opp_w = _wpct(T[opp], fecha)
            hoy_debil = opp_w is not None and opp_w <= DEBIL
            prev = S[-1] if S else None
            pw = _wpct(T.get(prev["rival"], []), prev["fecha"]) if prev else None
            nx = _siguiente(p, e, todos or [])
            nw = _wpct(T.get(nx[1], []), _d(nx[0])) if nx and (_d(nx[0]) - fecha).days <= 60 else None
            rev = False
            for g in reversed(S):
                if g["rival"] == opp:
                    rev = g["gf"] < g["ga"]; break
            rl = rw = 0
            for g in reversed(S):
                if g["gf"] < g["ga"]: rl += 1
                else: break
            for g in reversed(S):
                if g["gf"] > g["ga"]: rw += 1
                else: break
            my_w = _wpct(T[e], fecha)
            tot = len([g for g in _temporada_anterior(Pl, fecha)])
            k = len(S) + 1
            info[lado] = dict(
                Q1=rev,
                Q2=bool(prev and prev["gf"] > prev["ga"] and pw is not None and pw >= FUERTE and hoy_debil),
                Q3=bool(hoy_debil and nw is not None and nw >= FUERTE),
                Q4=bool(hoy_debil and pw is not None and pw >= FUERTE and nw is not None and nw >= FUERTE),
                Q5=bool(loc and S is not None and not any(g["local"] for g in S)),
                Q6a=rl >= 5, Q6b=rw >= 5,
                Q7=bool(tot >= 20 and k > 0.85 * tot and my_w is not None and my_w <= DEBIL and opp_w is not None and opp_w >= 0.55))
        for c in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6a", "Q6b", "Q7"):
            h, a = info["H"][c], info["A"][c]
            x[c] = 0 if (h and a) else (1 if h else (-1 if a else 0))
    # ---------------- medidos en la tanda 1 que faltaban en vivo, y tanda 3 (9-oct-2026)
    if "H" in G:
        if ph.get("pim") is not None and pa.get("pim") is not None:
            x["H18"] = (pa["pim"] - ph["pim"]) / 10.0
        x["H23"] = _ind(_en_ventana(Pa, fecha, 5) >= 3) - _ind(_en_ventana(Ph, fecha, 5) >= 3)
        x["H24"] = 1 if (eh in ALT_NHL and ea not in ALT_NHL) else 0
    if "K" in G and liga == "nba":
        x["K12"] = _ind(_en_ventana(Pa, fecha, 5) >= 3) - _ind(_en_ventana(Ph, fecha, 5) >= 3)
        x["K13"] = 1 if (eh in ALT_NBA and ea not in ALT_NBA) else 0
        k14 = _ausencias_nba(p, fecha)
        if k14 is not None:
            x["K14"] = k14
    if "P" in G:
        x.update(_playoffs(Ph, eh, ea, fecha))
    if liga == "nfl":
        L = _nfl_lineas()
        hk, ak = _alias_nfl(eh), _alias_nfl(ea)
        x["N14"] = 1 if fecha.weekday() == 3 else 0
        et = _hora_et(p)
        x["N15"] = 1 if (ak in PAC_NFL and hk in ESTE_NFL and et is not None and et < "14:00") else 0
        div = frozenset((hk, ak)) in L["div"]
        x["Q8"] = 1 if div else 0
        ph_p = (p.get("modelo") or {}).get("p_home")
        x["N17"] = ((1 if ph_p < 0.5 else -1) if (div and ph_p is not None and ph_p != 0.5) else 0)
        x["N13"] = _ind(L["ot_gano"].get((ak, pa["fecha"].isoformat()))) - _ind(L["ot_gano"].get((hk, ph["fecha"].isoformat())))
        x["Q9"] = _ind(_coach_nuevo(L, hk, fecha)) - _ind(_coach_nuevo(L, ak, fecha))
        if abs(x["Q9"]) != 1:
            x["Q9"] = 0
    if liga == "ncaafb":
        x["N14"] = 1 if fecha.weekday() == 3 else 0
    if liga == "mlb":
        x["B25"] = 1 if eh == "Colorado Rockies" else 0
    if "F" in G:
        if liga == "ligamx":
            x["F14"] = 1 if (eh in ALT_MX and ea not in ALT_MX) else 0
        lh = next((g for g in reversed(Ph) if g["gf"] is not None), None); la = next((g for g in reversed(Pa) if g["gf"] is not None), None)
        if lh and la:
            dh, da = (fecha - lh["fecha"]).days, (fecha - la["fecha"]).days
            m_ = p.get("modelo") or {}
            if 12 <= dh <= 30 and 12 <= da <= 30 and m_.get("p_home") is not None and m_.get("p_away") is not None:
                x["F15"] = 1 if m_["p_home"] >= m_["p_away"] else -1
        ch = lambda P: any(str(g["gp"]).startswith("ch") and 0 < (fecha - g["fecha"]).days <= 4 for g in P[-3:])
        x["F16"] = _ind(ch(Pa)) - _ind(ch(Ph))
        if liga in DESCENSO:
            f17 = _descenso(T, eh, ea, fecha)
            if f17 is not None:
                x["F17"] = f17
    # x con el MISMO signo que en el minado: + apunta al local, - a la visita. El efecto medido es para ese lado.
    out = []
    for c, v in x.items():
        if not v:
            continue
        lado = "home" if v > 0 else "away"
        out.append({"codigo": c, "nombre": NOMBRES.get(c, c), "lado": lado, "equipo": p[lado].get("abrev") or p[lado]["nombre"],
                    "x": v, "medicion": medicion(liga, c), "con_peso": (liga, c) in CON_PESO})
    return out


def efecto(a):
    """efecto medido para el lado al que apunta el angulo (pp) y su signo de conteo: +1 a favor de ese lado, -1 en contra, 0 neutro."""
    m = a.get("medicion") or {}
    e = m.get("efecto_pp")
    if e is None:
        return None, 0
    if a.get("con_peso"):
        return e, 0                      # ya esta dentro de la probabilidad: contarlo otra vez seria doble
    return e, (0 if abs(e) < NEUTRO_PP else (1 if e > 0 else -1))


def _miles(n):
    return "{:,}".format(n) if isinstance(n, int) else str(n)


def texto(a):
    """una linea: que angulo, para quien se midio y que dio."""
    m = a.get("medicion")
    base = "%s %s" % (a["codigo"], a["nombre"])
    if not m or m.get("efecto_pp") is None:
        return base + ": sin medicion"
    t = "%s: %s rindio %+.1f pp contra el modelo fuera de muestra (%s casos, z %s, %s)" % (
        base, a["equipo"], m["efecto_pp"], _miles(m.get("n_activo_prueba")), m.get("z"), m.get("veredicto"))
    if m.get("tmle_pp") is not None and m.get("tmle_ic95"):
        t += "; TMLE %+.1f pp [%+.1f, %+.1f]" % (m["tmle_pp"], m["tmle_ic95"][0], m["tmle_ic95"][1])
    if a.get("con_peso"):
        return t + "; con peso: ya esta dentro de la probabilidad del modelo"
    return t + ("; pasa, sin peso hasta que Alejandro lo apruebe" if m.get("veredicto") == "pasa" else "; sin peso")


def conteo(angs):
    """angulos que favorecen a cada lado segun lo medido (los neutros, |efecto| < 1 pp, no cuentan)."""
    c = {"home": 0, "away": 0}
    for a in angs:
        e, s = efecto(a)
        if s:
            c[a["lado"] if s > 0 else ("away" if a["lado"] == "home" else "home")] += 1
    return c


def resumen_json(a):
    m = a.get("medicion") or {}
    return {"codigo": a["codigo"], "nombre": a["nombre"], "lado": a["lado"], "equipo": a["equipo"], "x": a["x"], "con_peso": bool(a.get("con_peso")),
            "efecto_pp": m.get("efecto_pp"), "n_medido": m.get("n_activo_prueba"), "z": m.get("z"), "veredicto": m.get("veredicto"),
            "tmle_pp": m.get("tmle_pp"), "tmle_ic95": m.get("tmle_ic95"), "texto": texto(a)}


def para_pick(angs, lado_pick):
    """(a_favor, en_contra, textos_si, textos_no) de los angulos respecto al lado del pick (home/away)."""
    fav = con = 0; si = []; no = []
    for a in angs:
        e, s = efecto(a)
        if s == 0:
            continue
        s = s if a["lado"] == lado_pick else -s
        if s > 0:
            fav += 1; si.append("angulo " + texto(a))
        else:
            con += 1; no.append("angulo " + texto(a))
    return fav, con, si, no


if __name__ == "__main__":
    if "--catalogo" in sys.argv:
        c = construir_catalogo()
        print("modelos/angulos_medidos.json: %d angulos medidos" % len(c["angulos"]))
