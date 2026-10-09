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
  - NO cambia probabilidades: ninguno paso el protocolo (n >= 300, z >= 2.0, dos mitades, calibrado). Se muestran,
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
    "Q7": "fin de temporada: debil vs en contienda",
}

# liga en vivo -> grupos del catalogo donde se midio cada familia de codigos (el primero que tenga el codigo)
_BEIS = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")
_FUT = ("premier", "laliga", "seriea", "bundesliga", "ligue1", "ligamx", "mls")


def _grupos(liga):
    lg = (liga or "").lower()
    if lg == "nhl": return {"H": ["NHL"], "Q": ["NHL"]}
    if lg == "nba": return {"K": ["NBA"], "Q": ["NBA"]}
    if lg == "ncaamb": return {"K": ["NCAAMB"]}
    if lg == "nfl": return {"N": ["NFL"], "Q": ["NFL"]}
    if lg == "ncaafb": return {"N": ["NCAAFB"]}
    if lg == "mlb": return {"B": ["MLB", "TODAS"], "Q": ["BEISBOL"]}
    if lg in _BEIS: return {"B": ["TODAS"], "Q": ["BEISBOL"]}
    if lg in _FUT: return {"F": ["7 ligas"], "Q": ["FUTBOL"]}
    return {}


# ------------------------------------------------------------------ catalogo de mediciones
def construir_catalogo():
    """Lee los resultados del minado (base = modelo) y escribe modelos/angulos_medidos.json. Ningun numero se escribe a mano."""
    fuentes = [("trabajo/minar/2026-10-08_situacionales_tanda1_resultados.json", "trabajo/minar/2026-10-08_situacionales_tanda1.md"),
               ("trabajo/minar/2026-10-09_cualitativos_resultados.json", "trabajo/minar/2026-10-09_cualitativos.md")]
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
                        "y la sede, en toda la muestra, con IC 95 %. Ninguno paso: no tienen peso en p. Futbol se midio con el "
                        "modelo de K 20 sin olvido (antes del 9-oct).",
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
        T.setdefault(r.get("team"), []).append(dict(fecha=f, gp=str(r.get("gamePk") or r.get("game_id") or ""),
                                                    local=str(r.get("is_home")) in ("1", "1.0", "True"), gf=gf, ga=ga,
                                                    rival=r.get("opp"), ot=ot, ip=_f(r.get("pit_inningsPitched"))))
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


def calcular(p, todos=None):
    """Angulos activos del partido. Devuelve lista de dicts: codigo, nombre, lado (home/away al que apunta el angulo),
    equipo, x, medicion (o None). Vacia si no hay calendario o la liga no tiene angulos medidos."""
    liga = (p.get("liga") or "").lower()
    G = _grupos(liga)
    if not G or p.get("pretemporada"):
        return []
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
    # x con el MISMO signo que en el minado: + apunta al local, - a la visita. El efecto medido es para ese lado.
    out = []
    for c, v in x.items():
        if not v:
            continue
        lado = "home" if v > 0 else "away"
        out.append({"codigo": c, "nombre": NOMBRES.get(c, c), "lado": lado, "equipo": p[lado].get("abrev") or p[lado]["nombre"],
                    "x": v, "medicion": medicion(liga, c)})
    return out


def efecto(a):
    """efecto medido para el lado al que apunta el angulo (pp) y su signo de conteo: +1 a favor de ese lado, -1 en contra, 0 neutro."""
    m = a.get("medicion") or {}
    e = m.get("efecto_pp")
    if e is None:
        return None, 0
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
    return t + "; sin peso"


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
    return {"codigo": a["codigo"], "nombre": a["nombre"], "lado": a["lado"], "equipo": a["equipo"], "x": a["x"],
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
