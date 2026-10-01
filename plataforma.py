# -*- coding: utf-8 -*-
"""
PLATAFORMA (borrador 1) - predice los partidos de los proximos dias, todos los deportes.

Flujo:
  1. recolectar_proximos  -> partidos por jugar + cuotas + contexto (ESPN)
  2. modelos/*            -> tus modelos SIN CAMBIOS: ganador, total, spread por partido
  3. nucleo/mercado       -> edge contra la cuota sin vig + Kelly fraccional
  4. salida               -> salida\\proximos.json + salida\\plataforma_draft.html

El contexto de ESPN (abridor, lesiones, H2H, ATS, ultimos 5, predictor) se MUESTRA junto al
pick; nunca entra al entrenamiento de los modelos.

Uso (en C:\\Edgeline):
    python plataforma.py                       (3 dias, todas las ligas)
    python plataforma.py --dias 5 --ligas mlb,nfl,premier
    python plataforma.py --sin-contexto        (mas rapido)
    python plataforma.py --entrada contexto\\proximos_espn.json   (sin volver a bajar de ESPN)
"""
import argparse, csv, io as _io, os, sys, json, datetime as dt

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, "colectores"))
from nucleo import io, mercado, calibrar, equipos, estado, forma, linea, jugadores
from modelos import beisbol, hockey, americano, nba, futbol
import recolectar_proximos as RP
import proximos_beisbol as PB
import pagina_plataforma as PAG

BASE = io.BASE
UMBRAL_EDGE = 0.03        # edge minimo para marcar VALOR
# Pretemporada: ESPN no la marca en NHL, se detecta por fecha de inicio de la temporada regular.
PRE_INICIO = {"nhl": "2026-09-29"}
# Mercados que NO superaron al baseline en walk-forward: se muestran TODOS los datos, pero no se marcan
# VALOR ni se registran como pick. (liga, tipo) con tipo = Ganador | Total | Spread.
_BEIS = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")
NO_PUBLICABLE = set()
for _l in ("ncaafb", "ncaamb"):          # universitario: con prediccion, pero sin validar hasta que lo confirme el walk-forward
    for _t in ("Ganador", "Total", "Spread"):
        NO_PUBLICABLE.add((_l, _t))
for _l in _BEIS:
    NO_PUBLICABLE.add((_l, "Total")); NO_PUBLICABLE.add((_l, "Spread"))
for _l in ("kbo", "lmp", "lvbp", "lidom", "abl"):      # ganador de beisbol: solo MLB y NPB superan al baseline
    NO_PUBLICABLE.add((_l, "Ganador"))
NO_PUBLICABLE.add(("nhl", "Total")); NO_PUBLICABLE.add(("nhl", "Spread"))
# Futbol: Over/Under 2.5 sin ventaja sobre el baseline en walk-forward (Liga MX -0.1, MLS +0.2, Serie A -0.1);
# tenis: games totales sin ventaja (sesgo de games por set).
for _l in ("ligamx", "mls", "seriea", "atp", "wta"):
    NO_PUBLICABLE.add((_l, "Total"))


AJUSTE_GAMES = {}  # (liga, best_of) -> sesgo de games a corregir (lo calcula validar_mercados.py)
BREAKS_OK = {}     # (liga, best_of) -> los mercados de breaks (totales y over/under) superan la validacion estricta


def _aplicar_validacion():
    """Si existen salida/validacion_mercados.json y validacion_futbol.json (los escriben los validadores walk-forward),
    ellos deciden que mercados son publicables; lo escrito a mano arriba queda solo como respaldo."""
    def cargar(nombre):
        try:
            with open(io.ruta("salida", nombre), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    def pub(d, k):
        return (d.get(k) or {}).get("estado") == "publicable"
    def mayoria(d, claves):
        v = [pub(d, k) for k in claves]
        return bool(v) and sum(v) * 2 > len(v)
    def poner(liga, tipo, ok):
        (NO_PUBLICABLE.discard if ok else NO_PUBLICABLE.add)((liga, tipo))
    vm = cargar("validacion_mercados.json")
    for tour, d in (vm.get("ajustes_tenis") or {}).items():
        for bo, v in d.items():
            AJUSTE_GAMES[(tour.lower(), int(bo))] = float(v)
    dep = vm.get("deportes", {})
    for liga, clave in (("nhl", "hockey"), ("nfl", "nfl"), ("nba", "nba"), ("ncaafb", "ncaafb"), ("ncaamb", "ncaamb")):
        d = dep.get(clave)
        if not d: continue
        poner(liga, "Ganador", pub(d, "Ganador"))
        poner(liga, "Total", pub(d, "Over/Under (lineas ~promedio)"))
        poner(liga, "Spread", mayoria(d, [k for k in d if k.startswith(("Local cubre margen", "Puck line"))]))
    for liga, clave in (("atp", "tenis_ATP"), ("wta", "tenis_WTA")):
        d = dep.get(clave)
        if not d: continue
        poner(liga, "Ganador", pub(d, "Ganador"))
        ou = [k for k in d if k.startswith("Over/Under games")]
        poner(liga, "Total", bool(ou) and all(pub(d, k) for k in ou))
        for bo in (3, 5):
            ks = [k for k in d if k.startswith("Breaks") and "[%d sets]" % bo in k]
            if ks: BREAKS_OK[(liga, bo)] = all(pub(d, k) for k in ks)
    fut = cargar("validacion_futbol.json").get("ligas", {})
    for nombre, d in fut.items():
        liga = nombre.lower()
        poner(liga, "Ganador", pub(d, "1") and pub(d, "2"))
        poner(liga, "Total", pub(d, "over_2.5"))


CUOTA_MIN = 1.80           # cuota decimal minima para marcar VALOR/pick (1.80 = -125 americano)
EDGE_SOSPECHOSO = 0.15    # arriba de esto se pide revisar (falta info: lesion, alineacion...)
_aplicar_validacion()
TZ = RP.TZ_MX

DEPORTE = {"mlb": "beisbol", "npb": "beisbol", "kbo": "beisbol", "lmp": "beisbol", "lvbp": "beisbol",
           "lidom": "beisbol", "abl": "beisbol", "nfl": "americano", "ncaafb": "americano", "nhl": "hockey", "nba": "nba", "ncaamb": "nba",
           "premier": "futbol", "laliga": "futbol", "seriea": "futbol", "bundesliga": "futbol",
           "ligue1": "futbol", "ligamx": "futbol", "champions": "futbol", "mls": "futbol",
           "atp": "tenis", "wta": "tenis"}
NOMBRE = {"mlb": "MLB", "npb": "NPB", "kbo": "KBO", "lmp": "LMP", "lvbp": "LVBP", "lidom": "LIDOM", "abl": "ABL",
          "nfl": "NFL", "ncaafb": "NCAA Fútbol Americano", "nhl": "NHL", "nba": "NBA",
          "ncaamb": "NCAA Basketball", "premier": "Premier League", "laliga": "La Liga",
          "seriea": "Serie A", "bundesliga": "Bundesliga", "ligue1": "Ligue 1", "ligamx": "Liga MX",
          "champions": "Champions League", "mls": "MLS", "atp": "ATP", "wta": "WTA"}
MODS = {"hockey": hockey, "americano": americano, "nba": nba, "futbol": futbol}


# ================================================================== modelos (cache)
class Cache:
    def __init__(self):
        self.est, self.emp, self.avisos, self.ff = {}, {}, [], {}

    def obtener(self, dep, liga):
        k = (dep, "" if dep == "tenis" else liga)      # ATP y WTA comparten el mismo estado
        if k not in self.est:
            try:
                self.est[k] = self._construir(dep, liga)
            except Exception as ex:                     # un deporte roto no tumba a los demas
                self.avisos.append("%s/%s: no se pudo entrenar (%s)" % (dep, liga, str(ex)[:90]))
                self.est[k] = None
        return self.est[k]

    def _construir(self, dep, liga):
        if dep == "beisbol":
            st = estado.beisbol(liga)
            if not st:
                self.avisos.append("%s: datos insuficientes en datos\\beisbol.csv" % liga); return None
            return {"st": st, "emp": equipos.Emparejador(st["nombres"]), "nota": None}
        if dep == "tenis":
            st = estado.tenis()
            if not st:
                self.avisos.append("tenis: falta datos\\tenis.csv"); return None
            return {"st": st, "emp": equipos.EmparejadorJugadores(st["nombres"]), "nota": None}
        mod, nota = MODS[dep], None
        st = mod.entrenar(liga)
        if not st.get("eq"):
            if dep == "futbol" and liga == "champions":
                st = mod.entrenar(None)
                nota = "Modelo entrenado con las 5 ligas europeas (sin historial propio de Champions)."
            elif dep == "americano" and liga != "ncaafb":
                st = mod.entrenar(None)
            if not st.get("eq"):
                self.avisos.append("%s/%s: sin historial en datos\\%s.csv" % (dep, liga, dep)); return None
        return {"st": st, "emp": equipos.Emparejador(list(st["eq"])), "nota": nota}


def _variantes(e):
    v = [e.get("nombre"), e.get("corto"), e.get("loc")]
    if e.get("loc") and e.get("corto"):
        v.append("%s %s" % (e["loc"], e["corto"]))
    return [x for x in v if x]


def _casar(c, e):
    return c["emp"].buscar(_variantes(e), e.get("abrev"))


# ================================================================== prediccion por deporte
def _conf(p, tres=False):
    top = p
    if tres:
        return "alta" if top >= 0.55 else ("media" if top >= 0.45 else "baja")
    return "alta" if top >= 0.65 else ("media" if top >= 0.57 else "baja")


def _pred(g, c, fecha):
    """-> (modelo|None, motivo_si_none). Salida comun a todos los deportes."""
    dep, liga, q = DEPORTE.get(g["liga"]), g["liga"], g.get("cuotas") or {}
    if g["tipo"] != "tenis" and any("/" in (g[l]["nombre"] or "") for l in ("home", "away")):
        return None, "rival por definir (TBD)"            # ganador de una serie aun sin resolver, p. ej. "Phillies/Braves"
    if g["tipo"] == "tenis":
        if "TBD" in ((g["home"]["nombre"] or "").upper(), (g["away"]["nombre"] or "").upper()):
            return None, "rival por definir (TBD)"
        j1, s1 = c["emp"].buscar(g["home"]["nombre"]); j2, s2 = c["emp"].buscar(g["away"]["nombre"])
        if not j1 or not j2:
            return None, "jugador sin historial en tus datos: %s" % (g["home"]["nombre"] if not j1 else g["away"]["nombre"])
        bo = g.get("best_of", 3); linea = 22.5 if bo == 3 else 38.5
        r = estado.tenis_predecir(c["st"], j1, j2, g.get("superficie", "Hard"), bo, linea, tour=g["liga"],
                                  ajuste_games=AJUSTE_GAMES.get((g["liga"], bo), 0.0))
        if not r:
            return None, "muestra insuficiente de saque/resto"
        return {"p_home": r["p1"], "p_away": r["p2"], "unidad": "games",
                "total": r["games_esperados"], "linea_total": linea, "linea_es_mercado": False,
                "p_over": r["p_over_games"], "confianza": _conf(max(r["p1"], r["p2"])),
                "extra": [("Breaks esperados", r["breaks_esperados"]),
                          ("Prob. de al menos un break", r["p_al_menos_un_break"]),
                          ("Hold saque local / visita", "%s / %s" % (r["hold_j1"], r["hold_j2"]))],
                "nota": "Superficie estimada: %s. Best of %d." % (g.get("superficie"), bo)}, None

    h, sh = _casar(c, g["home"]); a, sa = _casar(c, g["away"])
    if not h or not a:
        return None, "equipo sin empate en tus datos: %s" % (g["home"]["nombre"] if not h else g["away"]["nombre"])
    tot_m = q.get("total")

    if dep == "beisbol":
        fila = estado.fila_proximo(c["st"], h, a, fecha)
        if not fila:
            return None, "muestra insuficiente esta temporada"
        r = beisbol.predecir(c["st"]["modelo"], fila, tot_m)
        pa_, pb_ = calibrar.cargar("beisbol", c["st"]["liga"])
        p = calibrar.aplicar(r["p_home"], pa_, pb_)
        m = {"p_home": p, "p_away": 1 - p, "unidad": "carreras",
             "x_home": r["esperado_home"], "x_away": r["esperado_away"], "total": r["total"],
             "linea_total": tot_m, "linea_es_mercado": tot_m is not None, "p_over": r.get("p_over"),
             "confianza": _conf(max(p, 1 - p)), "extra": []}
        if r.get("p_rl_home") is not None:
            m["extra"] += [("Run line local -1.5", r["p_rl_home"]), ("Run line visita +1.5", r["p_rl_away"])]
        return m, None

    if dep == "hockey":
        r = hockey.predecir(c["st"], h, a, linea_total=tot_m or 6.5)
        if not r:
            return None, "equipo sin historial"
        return {"p_home": r["p_home"], "p_away": r["p_away"], "unidad": "goles",
                "x_home": r["xg_home"], "x_away": r["xg_away"], "total": r["total"],
                "linea_total": r["linea_total"], "linea_es_mercado": tot_m is not None, "p_over": r["p_over"],
                "confianza": _conf(max(r["p_home"], r["p_away"])),
                "extra": [("Puck line local -1.5", r["p_pl_home"]), ("Puck line visita +1.5", r["p_pl_away"])],
                "nota": "Sin ajuste por portero titular (ESPN no lo publica antes del juego)."}, None

    if dep in ("americano", "nba"):
        sp = q.get("spread_home")
        r = MODS[dep].predecir(c["st"], h, a, linea_total=tot_m, linea_spread=(-sp if sp is not None else None))
        if not r:
            return None, "equipo sin historial"
        m = {"p_home": r["p_home"], "p_away": r["p_away"], "unidad": "puntos",
             "x_home": r["pts_home"], "x_away": r["pts_away"], "total": r["total_esperado"],
             "linea_total": tot_m, "linea_es_mercado": tot_m is not None, "p_over": r.get("p_over"),
             "confianza": r["confianza"], "margen": r["margen_esperado"], "extra": []}
        if r.get("p_cubre_home") is not None:
            m["spread"] = {"linea_home": sp, "p_home": r["p_cubre_home"], "p_away": 1 - r["p_cubre_home"]}
        return m, None

    if dep == "futbol":
        hd = q.get("spread_home")
        r = futbol.predecir(c["st"], h, a, linea_total=tot_m or 2.5, handicap=(hd if hd is not None else 0.0))
        if not r:
            return None, "equipo sin historial"
        top = max(r["p_home"], r["p_draw"], r["p_away"])
        der = r.get("derivados")
        if der:
            vf = _val_futbol().get(liga, {})
            der["_validacion"] = {k: vf[k]["estado"] for k in der if k in vf}
        return {"derivados": der, "p_home": r["p_home"], "p_draw": r["p_draw"], "p_away": r["p_away"], "unidad": "goles",
                "x_home": r["xg_home"], "x_away": r["xg_away"], "total": r["total_esperado"],
                "linea_total": r["linea_total"], "linea_es_mercado": tot_m is not None, "p_over": r["p_over"],
                "confianza": _conf(top, tres=True), "extra": [], "nota": c.get("nota")}, None
    return None, "sin modelo para este deporte"


_VF = {}
def _val_futbol():
    """Estado de cada mercado de futbol por liga (salida/validacion_futbol.json, lo escribe validar_futbol_mercados.py)."""
    if not _VF:
        try:
            with open(io.ruta("salida", "validacion_futbol.json"), encoding="utf-8") as fh:
                for lg, d in json.load(fh).get("ligas", {}).items():
                    _VF[lg.lower()] = d
        except Exception:
            _VF["_vacio"] = {}
    return _VF


# ================================================================== mercado / edge
def _mercados(g, m, umbral):
    liga = g['liga']
    q, out = g.get("cuotas") or {}, []
    if q.get("ml_home") is not None and q.get("ml_away") is not None:
        lados = [("home", q["ml_home"], m["p_home"]), ("away", q["ml_away"], m["p_away"])]
        if m.get("p_draw") is not None and q.get("ml_draw") is not None:
            lados.append(("draw", q["ml_draw"], m["p_draw"]))
        fair = mercado.sin_vig([mercado.prob_implicita(cu) for _, cu, _ in lados])
        for (lado, cu, p), pf in zip(lados, fair):
            out.append(_fila("Ganador", lado, cu, p, pf, umbral, liga))
    if m.get("linea_es_mercado") and m.get("p_over") is not None and \
            q.get("over_odds") is not None and q.get("under_odds") is not None:
        fair = mercado.sin_vig([mercado.prob_implicita(q["over_odds"]), mercado.prob_implicita(q["under_odds"])])
        out.append(_fila("Total %.1f" % m["linea_total"], "over", q["over_odds"], m["p_over"], fair[0], umbral, liga))
        out.append(_fila("Total %.1f" % m["linea_total"], "under", q["under_odds"], 1 - m["p_over"], fair[1], umbral, liga))
    if m.get("spread") and q.get("spread_home_odds") is not None and q.get("spread_away_odds") is not None:
        fair = mercado.sin_vig([mercado.prob_implicita(q["spread_home_odds"]), mercado.prob_implicita(q["spread_away_odds"])])
        sp = m["spread"]["linea_home"]
        out.append(_fila("Spread %+g" % sp, "home", q["spread_home_odds"], m["spread"]["p_home"], fair[0], umbral, liga))
        out.append(_fila("Spread %+g" % -sp, "away", q["spread_away_odds"], m["spread"]["p_away"], fair[1], umbral, liga))
    return out


def _fila(mkt, lado, cuota, p, pf, umbral, liga=None):
    e = p - pf
    est = "revisar" if e >= EDGE_SOSPECHOSO else ("valor" if e >= umbral else "")
    tipo = mkt.split()[0]
    if est in ("valor", "revisar") and (liga, tipo) in NO_PUBLICABLE:
        est = "sin_validar"      # hay diferencia con el mercado, pero este mercado no vence al baseline
    if est in ("valor", "revisar") and mercado.american_a_decimal(cuota) < CUOTA_MIN:
        est = "cuota_baja"       # edge positivo, pero la cuota paga menos que el minimo (1.80)
    return {"mercado": mkt, "lado": lado, "cuota": cuota, "p_modelo": round(p, 4), "p_mercado": round(pf, 4),
            "edge": round(e, 4), "kelly": round(mercado.kelly(p, cuota), 4) if est == "valor" else 0.0, "estado": est}


def _lado_fav(d):
    return max(d, key=d.get) if d else None


def _consenso(m, mercados, ctx):
    fuentes = {}
    fuentes["modelo"] = _lado_fav({k: m[k] for k in ("p_home", "p_draw", "p_away") if m.get(k) is not None}).replace("p_", "")
    gan = {x["lado"]: x["p_mercado"] for x in mercados if x["mercado"] == "Ganador"}
    if gan:
        fuentes["mercado"] = _lado_fav(gan)
    ph = (ctx or {}).get("espn_pred_home")
    if ph is not None:
        fuentes["espn"] = "home" if ph >= 0.5 else "away"
    n = sum(1 for v in fuentes.values() if v == fuentes["modelo"])
    return {"fuentes": fuentes, "coinciden": n, "de": len(fuentes)}


def _pre_inicio(liga):
    """Fecha de inicio de temporada regular (constante PRE_INICIO). Para la NHL la constante manda aunque tus datos
    traigan juegos de finales de septiembre con id de temporada regular: esos 5 juegos del 29-sep no se pueden confirmar y
    es mas seguro dejar los juegos dudosos fuera del track record que mezclar pretemporada con temporada."""
    return PRE_INICIO.get(liga)


# ================================================================== ficha homogenea (mismos bloques, todos los deportes)
def _fuente_forma(cache, liga, dep):
    """(Forma, Emparejador) de la liga: tus datos del deporte; si no tienen la liga, los archivos de equipos de ESPN."""
    if liga in cache.ff:
        return cache.ff[liga]
    res = (None, None)
    try:
        if dep in forma.SCORE:
            F = forma.forma(dep, liga)
            if F.activos:
                res = (F, equipos.Emparejador(list(F.eq)))
        if res[0] is None:
            F = forma.forma_espn(liga)
            if F.activos:
                res = (F, equipos.Emparejador(list(F.eq)))
    except Exception as ex:
        cache.avisos.append("forma %s: %s" % (liga, str(ex)[:80]))
    cache.ff[liga] = res
    return res


def _lado_nombre(emp, e):
    return emp.buscar(_variantes(e), e.get("abrev"))[0]


def _ficha(rec, g, cache):
    """Agrega a rec los bloques: movimiento, forma, h2h_datos, estadisticas_equipo, jugadores_clave, validacion, bloques."""
    liga, dep, m = g["liga"], DEPORTE.get(g["liga"]), rec.get("modelo")
    bl = {}

    def marca(nombre, ok, motivo=""):
        bl[nombre] = {"ok": bool(ok), "motivo": "" if ok else motivo}
    rec["forma"] = {"home": None, "away": None}
    rec["h2h_datos"] = None
    rec["estadisticas_equipo"] = None
    rec["jugadores_clave"] = None
    rec["movimiento"] = linea.movimiento(g.get("cuotas"), liga, g["id"], g.get("fecha_utc"),
                                         directorio=os.path.join(BASE, "salida"))
    mv = rec["movimiento"]
    marca("movimiento", mv["ml"] or mv["total"] or mv["spread"], "sin cuotas de apertura y actuales para este partido")

    if g["tipo"] == "tenis":
        c = cache.obtener("tenis", liga)
        j1 = j2 = None
        if c:
            j1 = c["emp"].buscar(g["home"]["nombre"])[0]
            j2 = c["emp"].buscar(g["away"]["nombre"])[0]
        ft = forma.forma_tenis()
        sup = g.get("superficie")
        fref = (rec.get("fecha") or "")[:10] or None
        mj = g.get("mejor_de") or g.get("best_of")
        try:
            mj = int(mj) if mj else None
        except (TypeError, ValueError):
            mj = None
        rec["forma"] = {"home": ft.jugador(j1, sup, fref, mj) if j1 else None,
                        "away": ft.jugador(j2, sup, fref, mj) if j2 else None}
        rec["h2h_datos"] = ft.h2h(j1, j2) if (j1 and j2) else None
        okf = bool(rec["forma"]["home"] and rec["forma"]["away"])
        mot = ("rival por definir (TBD)" if "TBD" in ((g["home"]["nombre"] or "").upper(), (g["away"]["nombre"] or "").upper())
               else "jugador sin historial en tus datos")
        marca("forma", okf, mot)
        marca("estadisticas_equipo", okf, mot)
        marca("jugadores_clave", True)
        # estadisticas detalladas: games, saque, resto y breaks por ventana (L5, L10, 12m), superficie y formato
        def _est(f):
            if not f:
                return None
            d = f.get("detalle") or {}
            return {"L5": d.get("L5"), "L10": d.get("L10"), "12m": d.get("12m"),
                    "superficie_12m": f.get("detalle_superficie_12m"), "formato_12m": f.get("detalle_formato_12m"),
                    "superficie_hoy": f.get("detalle_superficie_hoy"), "records_vs_12m": f.get("records_vs_12m"),
                    "carga": f.get("carga")}
        rec["estadisticas_equipo"] = {"fuente": "datos/tenis.csv (games, saque, resto, breaks)",
                                      "home": _est(rec["forma"]["home"]), "away": _est(rec["forma"]["away"])}
    else:
        F, emp = _fuente_forma(cache, liga, dep)
        nh = na = None
        if F:
            nh, na = _lado_nombre(emp, g["home"]), _lado_nombre(emp, g["away"])
            rec["emparejado"] = {"home": nh, "away": na}      # nombre del equipo en tus datos (para auditar el empate)
            fh = F.equipo(nh) if nh else None
            fa = F.equipo(na) if na else None
            rec["forma"] = {"home": fh, "away": fa}
            rec["h2h_datos"] = F.h2h(nh, na) if (nh and na) else None
        marca("forma", rec["forma"]["home"] and rec["forma"]["away"],
              "equipo sin historial en tus datos" if F else "tus datos no traen esta liga todavia")
        # estadisticas de equipo: archivos datos/equipos/*.csv (si hay) y, si no, las columnas del propio historial
        EE = forma.estadisticas(liga)
        est = {"fuente": None, "home": None, "away": None}
        if EE.disponible():
            emp2 = cache.ff.get(("ee", liga))
            if emp2 is None:
                emp2 = cache.ff[("ee", liga)] = equipos.Emparejador(EE.equipos)
            for lado in ("home", "away"):
                nm = _lado_nombre(emp2, g[lado])
                est[lado] = EE.de(nm) if nm else None
            est["fuente"] = os.path.basename(EE.ruta)
        for lado in ("home", "away"):
            if est[lado] is None and rec["forma"][lado] and rec["forma"][lado].get("stats"):
                est[lado] = {"temp": rec["forma"][lado]["stats"]["temp"], "L10": rec["forma"][lado]["stats"]["L10"]}
                est["fuente"] = est["fuente"] or "datos/%s.csv" % (dep or liga)
        for lado in ("home", "away"):                       # las stats ya van en estadisticas_equipo
            if rec["forma"][lado]:
                rec["forma"][lado].pop("stats", None)
        rec["estadisticas_equipo"] = est
        marca("estadisticas_equipo", est["home"] and est["away"], "sin estadisticas de equipo para esta liga")
        # jugadores clave
        jug = {}
        for lado, nm in (("home", nh), ("away", na)):
            if dep == "beisbol" or liga in ("nhl", "nfl"):
                team = nm
            else:
                team = jugadores.resolver_espn(liga, _variantes(g[lado]), g[lado].get("abrev"))
            if team is None:
                hay = bool(jugadores._filas("espn_%s_jugadores.csv" % liga)[0]) if dep != "beisbol" and liga not in ("nhl", "nfl") else True
                jug[lado] = {"disponible": False, "motivo": ("equipo sin empate en los archivos de jugadores" if hay
                                                             else "tus archivos de jugadores no traen %s todavia" % liga)}
            else:
                jug[lado] = jugadores.clave(dep, liga, team, g[lado].get("probable") if dep == "beisbol" else None)
        rec["jugadores_clave"] = jug
        marca("jugadores_clave", jug["home"].get("disponible") and jug["away"].get("disponible"),
              jug["home"].get("motivo") or jug["away"].get("motivo") or "sin datos de jugadores")

    marca("prediccion", m, rec.get("motivo") or "sin prediccion")
    marca("totales", m and m.get("total") is not None, "sin modelo de totales")
    marca("spread", m and (m.get("spread") or any("line" in str(n).lower() for n, _ in (m.get("extra") or []))),
          "sin modelo de spread / run line / puck line")
    q = g.get("cuotas") or {}
    marca("mercado", q.get("ml_home") is not None and q.get("ml_away") is not None, "ESPN aun no publica cuotas")
    marca("contexto", rec.get("contexto"), "ESPN no publico contexto (lesiones, ATS, H2H) para este partido")
    rec["bloques"] = bl
    # estado de cada mercado: sin_modelo (no hay prediccion de ese mercado), sin_validar (no vence al baseline) o publicable
    blq = {"Ganador": "prediccion", "Total": "totales", "Spread": "spread"}
    rec["validacion"] = {t: ("sin_modelo" if not bl.get(blq[t], {}).get("ok")
                             else ("sin_validar" if (liga, t) in NO_PUBLICABLE else "publicable"))
                         for t in ("Ganador", "Total", "Spread")}
    if g.get("tipo") == "tenis":
        bo = 5 if str(g.get("best_of", 3)) == "5" else 3
        rec["validacion"]["Breaks"] = ("sin_modelo" if not bl.get("prediccion", {}).get("ok")
                                       else ("publicable" if BREAKS_OK.get((liga, bo)) else "sin_validar"))


def predecir_juegos(juegos, cache, umbral=UMBRAL_EDGE):
    res, sin = [], []
    for g in juegos:
        utc = dt.datetime.fromisoformat((g["fecha_utc"] or "").replace("Z", "+00:00")).replace(tzinfo=None)
        loc = utc + dt.timedelta(hours=TZ)
        rec = {"id": g["id"], "liga": g["liga"], "liga_nombre": NOMBRE.get(g["liga"], g["liga"]),
               "deporte": DEPORTE.get(g["liga"]), "tipo": g["tipo"], "fecha": loc.strftime("%Y-%m-%d"),
               "hora": loc.strftime("%H:%M"), "estado": g.get("estado"), "nota": g.get("nota"),
               "serie": g.get("serie"), "estadio": g.get("estadio"),
               "home": {k: g["home"].get(k) for k in ("nombre", "abrev", "logo", "record", "probable", "probable_rol", "ranking")},
               "away": {k: g["away"].get(k) for k in ("nombre", "abrev", "logo", "record", "probable", "probable_rol", "ranking")},
               "cuotas": g.get("cuotas") or {}, "contexto": g.get("contexto") or {},
               "modelo": None, "motivo": None, "mercados": [], "valor": None, "alerta": None, "pick": None, "ganador": None,
               "consenso": None}
        for k in ("torneo", "ronda", "cancha", "superficie", "best_of", "superficie_estimada"):
            if k in g:
                rec[k] = g[k]
        dep = DEPORTE.get(g["liga"])
        if not dep:
            rec["motivo"] = "sin modelo para esta liga"
        else:
            c = cache.obtener(dep, g["liga"])
            if not c:
                rec["motivo"] = "modelo no disponible (faltan datos historicos)"
            else:
                m, motivo = _pred(g, c, rec["fecha"])
                if not m:
                    rec["motivo"] = motivo
                else:
                    rec["modelo"] = m
                    rec["mercados"] = _mercados(g, m, umbral)
                    valores = [x for x in rec["mercados"] if x["estado"] == "valor"]
                    if valores:
                        rec["valor"] = max(valores, key=lambda x: x["edge"])
                    if any(x["estado"] == "revisar" for x in rec["mercados"]):
                        rec["alerta"] = ("El modelo difiere mucho del mercado (edge > %d%%). Casi siempre falta informacion "
                                         "que el mercado ya conoce (lesion, alineacion, abridor). Revisa antes de confiar." % int(EDGE_SOSPECHOSO * 100))
                    pre_ini = _pre_inicio(g["liga"])
                    nota_pre = ((g.get("nota") or "") + " " + (g.get("serie") or "")).lower()
                    if g.get("pretemporada") or "pretemporada" in nota_pre or "preseason" in nota_pre \
                            or (pre_ini and rec["fecha"] < pre_ini):
                        rec["pretemporada"] = True
                        rec["valor"] = None
                        for x in rec["mercados"]:
                            if x["estado"] in ("valor", "sin_validar"):
                                x["estado"] = ""; x["kelly"] = 0.0
                        rec["nota"] = ("Pretemporada. " + (rec["nota"] or "")).strip()
                        rec["alerta"] = ("Pretemporada: alineaciones experimentales y el modelo llega con datos de la "
                                         "temporada pasada. No se marca VALOR ni se registra en el historial.")
                    rec["consenso"] = _consenso(m, rec["mercados"], rec["contexto"])
                    lados = {k[2:]: m[k] for k in ("p_home", "p_draw", "p_away") if m.get(k) is not None}
                    top = _lado_fav(lados)
                    texto = {"home": rec["home"]["nombre"], "away": rec["away"]["nombre"], "draw": "Empate"}[top]
                    rec["pick"] = {"lado": top, "texto": texto, "prob": round(lados[top], 4), "confianza": m["confianza"]}
                    # lo que se muestra en la prediccion general: solo quien gana segun el modelo (el pick va en Picks IA)
                    rec["ganador"] = {"lado": top, "nombre": texto, "prob": round(lados[top], 4)}
        try:
            _ficha(rec, g, cache)
        except Exception as ex:                     # un bloque roto no tumba el partido
            rec.setdefault("bloques", {})["error"] = {"ok": False, "motivo": "ficha: %s" % str(ex)[:100]}
            cache.avisos.append("ficha %s %s: %s" % (g["liga"], g["id"], str(ex)[:80]))
        if not rec["modelo"]:
            sin.append("%s: %s @ %s -> %s" % (g["liga"].upper(), g["away"]["nombre"], g["home"]["nombre"], rec["motivo"]))
        res.append(rec)
    res.sort(key=lambda r: (r["fecha"], r["hora"], r["liga"]))
    return res, sin


# ================================================================== historial (base del track record)
HORAS_REGISTRO = 36       # el pick entra al historial cuando faltan <= 36 h para el partido (con mas info: abridores, lesiones, cuotas)


def _cerca(p):
    """True si el partido empieza dentro de HORAS_REGISTRO horas (hora de CDMX). Sin hora, se toma el final del dia."""
    try:
        ini = dt.datetime.strptime("%s %s" % (p["fecha"], p.get("hora") or "23:59"), "%Y-%m-%d %H:%M")
        ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=TZ)      # hora de CDMX
        return ini <= ahora + dt.timedelta(hours=HORAS_REGISTRO)
    except Exception:
        return True


def registrar(partidos, ruta):
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "pick", "prob", "confianza",
            "valor_mercado", "valor_lado", "valor_cuota", "valor_edge", "con_precio"]
    existentes = set()
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            previas = list(csv.DictReader(f))
        existentes = {(r["liga"], r["id"]) for r in previas}
        if previas and "con_precio" not in previas[0]:        # archivo con el formato anterior: se agrega la columna
            for r in previas:
                r["con_precio"] = "si" if r.get("valor_cuota") else ""
            with _io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(previas)
    nuevos = []
    for p in partidos:
        if not p["pick"] or p.get("pretemporada") or (p["liga"], "Ganador") in NO_PUBLICABLE or (p["liga"], p["id"]) in existentes:
            continue
        if not _cerca(p):
            continue                        # aun falta mucho: se registra en una corrida posterior
        if "if necessary" in ((p.get("nota") or "") + " " + (p.get("serie") or "")).lower():
            continue                        # juego condicional: puede no jugarse; se registra cuando deja de decir "If Necessary"
        v = p["valor"] or {}
        nuevos.append({"registrado": dt.datetime.now().isoformat(timespec="seconds"), "liga": p["liga"], "id": p["id"],
                       "fecha": p["fecha"], "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                       "pick": p["pick"]["texto"], "prob": p["pick"]["prob"], "confianza": p["pick"]["confianza"],
                       "valor_mercado": v.get("mercado", ""), "valor_lado": v.get("lado", ""),
                       "valor_cuota": v.get("cuota", ""), "valor_edge": v.get("edge", ""),
                       "con_precio": "si" if p.get("cuotas") else "no"})
    if nuevos:
        nuevo_archivo = not os.path.exists(ruta)
        with _io.open(ruta, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            if nuevo_archivo:
                w.writeheader()
            w.writerows(nuevos)
    return len(nuevos)


# ================================================================== main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=3)
    ap.add_argument("--ligas", help="lista separada por comas (default: todas)")
    ap.add_argument("--sin-contexto", action="store_true")
    ap.add_argument("--entrada", help="usa un proximos_espn.json ya bajado (no llama a ESPN)")
    ap.add_argument("--salida", default=os.path.join(BASE, "salida"))
    ap.add_argument("--umbral", type=float, default=UMBRAL_EDGE)
    a = ap.parse_args()

    if a.entrada:
        with _io.open(a.entrada, encoding="utf-8") as f:
            crudo = json.load(f)
        juegos = crudo["partidos"]
        print("Usando %d partidos de %s (generado %s)" % (len(juegos), a.entrada, crudo.get("generado")))
    else:
        ligas = [x.strip() for x in a.ligas.split(",")] if a.ligas else RP.DEFAULT + PB.DEFAULT
        print("1/3  Partidos por jugar (ESPN), proximos %d dia(s):" % a.dias)
        juegos = RP.recolectar([x for x in ligas if x not in PB.DEFAULT], a.dias, not a.sin_contexto)
        extra = [x for x in ligas if x in PB.DEFAULT]
        if extra:
            print("     NPB, KBO y ligas de invierno (MLB Stats API / koreabaseball.com, sin cuotas):")
            juegos += PB.recolectar(extra, a.dias)
        RP.guardar(juegos)
    if not juegos:
        print("::warning::No hay partidos por jugar en ese rango (o ESPN no respondio). Se conserva el proximos.json anterior.")
        print("No hay partidos por jugar en ese rango."); return

    print("\n2/3  Prediciendo con tus modelos ...")
    cache = Cache()
    partidos, sin = predecir_juegos(juegos, cache, a.umbral)

    print("3/3  Escribiendo salida ...")
    os.makedirs(a.salida, exist_ok=True)
    data = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "tz": TZ, "umbral_edge": a.umbral,
            "ficha": 2,
            "partidos": partidos, "sin_modelo": sin, "avisos": cache.avisos}
    rj = os.path.join(a.salida, "proximos.json")
    with _io.open(rj, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    rh = os.path.join(a.salida, "plataforma_draft.html")
    with _io.open(rh, "w", encoding="utf-8") as f:
        f.write(PAG.render(data))
    nuevos = registrar(partidos, os.path.join(a.salida, "historial_picks.csv"))

    con = [p for p in partidos if p["modelo"]]
    val = [p for p in partidos if p["valor"]]
    print("\n%d partidos: %d con prediccion, %d sin modelo, %d con VALOR (edge >= %d%%)."
          % (len(partidos), len(con), len(partidos) - len(con), len(val), int(a.umbral * 100)))
    if val:
        print("  (el detalle de VALOR esta en su apartado: python utilidades\\ver_predicciones.py --valor)")
    if cache.avisos:
        print("\nAvisos:"); [print("  -", x) for x in cache.avisos]
    if sin:
        print("\nSin prediccion (%d):" % len(sin)); [print("  -", x) for x in sin[:25]]
        if len(sin) > 25: print("  ... y %d mas" % (len(sin) - 25))
    print("\nPicks nuevos registrados en historial_picks.csv: %d" % nuevos)
    print("Abre:  %s" % rh)


if __name__ == "__main__":
    main()
