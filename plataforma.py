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
from nucleo import io, mercado, calibrar, equipos, estado, forma, linea, jugadores, sharp
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
    for liga, clave in (("nhl", "hockey"), ("nfl", "nfl"), ("nba", "nba"), ("ncaafb", "ncaafb"), ("ncaamb", "ncaamb"),
                        ("mlb", "beisbol_mlb"), ("npb", "beisbol_npb"), ("kbo", "beisbol_kbo")):
        d = dep.get(clave)
        if not d: continue
        poner(liga, "Ganador", pub(d, "Ganador"))
        poner(liga, "Total", pub(d, "Over/Under (lineas ~promedio)"))
        poner(liga, "Spread", mayoria(d, [k for k in d if k.startswith(("Local cubre margen", "Puck line", "Run line"))]))
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


# ---- capas de decision de pick (ver decidir_picks). Backtest: futbol 20,633 partidos con Pinnacle 2018-2026 y NFL 2,220.
EV_PICK, EV_FUERTE = 0.02, 0.04   # ventaja minima contra la MEJOR cuota: pick / fuerte
CUOTA_MAX = 3.00                  # arriba de 3.00 los longshots pierden (-4% a -9% de ROI en el backtest)
PESO_SHARP = 0.85                 # mezcla: 85% probabilidad sharp (Pinnacle/consenso) + 15% modelo (mas peso al modelo = menos ROI)
EXTRA_SESGO = 0.02                # NFL/NCAAFB: local y over estan sobreapostados (-5% / -6%): piden 2 pts mas de EV
EDGE_REVISAR = 0.10               # edge del modelo arriba de esto = informacion que el modelo no ve: "revisar", no pick
CUOTA_MIN = 1.699          # cuota decimal minima para marcar VALOR/pick (1.70 = -143 americano)
STAKE_PLANO = 1.0      # unidades por pick (stake plano: el track record se mide a 1u por apuesta)
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


def _p_cubre(xh, xa, linea_home, pmf, kmax=20):
    """P(local cubre la linea): margen local + linea_home > 0, con marcadores independientes (pmf(k, mu)).
    linea_home = -1.5 -> local gana por 2+; +1.5 -> local pierde por 1 o gana. Sin push (lineas .5)."""
    if xh is None or xa is None or linea_home is None:
        return None
    ph = [pmf(k, xh) for k in range(kmax)]; pa = [pmf(k, xa) for k in range(kmax)]
    return sum(ph[i] * pa[j] for i in range(kmax) for j in range(kmax) if (i - j) + linea_home > 0)


# ------------------------------------------------------------------ porteros titulares (colectores/recolectar_porteros.py) y xG (recolectar_xg_nhl.py)
_PORTEROS_DIA = {}
_XG_NHL = None


def _porteros_dia(fecha):
    """{nombre de equipo: {portero, estado}} del archivo trabajo/porteros_<fecha>.json; {} si no existe."""
    if fecha in _PORTEROS_DIA:
        return _PORTEROS_DIA[fecha]
    ruta = os.path.join(BASE, "trabajo", "porteros_%s.json" % fecha)
    out = {}
    try:
        with _io.open(ruta, encoding="utf-8") as f:
            out = (json.load(f) or {}).get("equipos") or {}
    except Exception:
        out = {}
    _PORTEROS_DIA[fecha] = out
    return out


def _sv_portero(team, nombre_equipo, fecha):
    """save% en la ventana de 10 juegos del portero anunciado para ese equipo (de nhl_porteros.csv); None sin dato."""
    anuncio = _porteros_dia(fecha).get(nombre_equipo)
    if not anuncio or not anuncio.get("portero"):
        return None, None
    apellido = anuncio["portero"].split()[-1].lower()
    info = {"portero": anuncio["portero"], "estado": anuncio.get("estado"), "sv_ventana": None, "apariciones": None}
    try:
        j = jugadores.hockey(team) or {}
        for q in ((j.get("porteros") or {}).get("jugadores") or []):
            if (q.get("jugador") or "").split()[-1].lower() == apellido:
                info["sv_ventana"] = q.get("sv_pct"); info["apariciones"] = q.get("apariciones"); info["gc_por_juego"] = q.get("gc_por_juego")
                if q.get("sv_pct") is not None and (q.get("apariciones") or 0) >= 3:
                    return float(q["sv_pct"]), info
                break
    except Exception:
        pass
    return None, info


def _xg_nhl(abrev):
    """filas de datos/equipos/nhl_xg.csv para el equipo (temporada actual y anterior, all y 5on5)."""
    global _XG_NHL
    if _XG_NHL is None:
        _XG_NHL = {}
        ruta = os.path.join(BASE, "datos", "equipos", "nhl_xg.csv")
        try:
            with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    _XG_NHL.setdefault((r.get("team") or "").upper(), []).append(r)
        except Exception:
            pass
    rows = _XG_NHL.get((abrev or "").upper()) or []
    if not rows:
        return None
    out = {}
    for r in rows:
        k = "%s_%s" % (r.get("season"), r.get("situacion"))
        out[k] = {c: (float(r[c]) if r.get(c) not in (None, "") and c not in ("team", "team_mp", "nombre", "situacion", "bajado") else r.get(c))
                  for c in ("juegos", "xgf_60", "xga_60", "gf_60", "ga_60", "xg_pct", "corsi_pct", "hd_xgf_60", "hd_xga_60", "suerte_gf", "suerte_ga")}
    return out


def _spread_mercado(q, p_home, xh, xa, pmf):
    """Bloque 'spread' (run line / puck line) a la LINEA DEL MERCADO si existe; si no, -1.5 al favorito del modelo."""
    sp = q.get("spread_home")
    if sp is None:
        sp = -1.5 if p_home >= 0.5 else 1.5
    pc = _p_cubre(xh, xa, float(sp), pmf)
    if pc is None:
        return None
    return {"linea_home": float(sp), "p_home": round(pc, 4), "p_away": round(1 - pc, 4), "linea_es_mercado": q.get("spread_home") is not None}


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
        m["spread"] = _spread_mercado(q, p, r["esperado_home"], r["esperado_away"], beisbol._nb_pmf)
        return m, None

    if dep == "hockey":
        sv_h, por_h = _sv_portero(h, g["home"]["nombre"], fecha)
        sv_a, por_a = _sv_portero(a, g["away"]["nombre"], fecha)
        r = hockey.predecir(c["st"], h, a, linea_total=tot_m or 6.5, sv_home=sv_h, sv_away=sv_a, fecha=fecha)
        if not r:
            return None, "equipo sin historial"
        d = r.get("descanso") or {}
        if sv_h is not None or sv_a is not None:
            nota = "Ajuste por portero titular (Daily Faceoff): %s." % "; ".join(
                "%s %s (%s, sv %.3f en 10 juegos)" % (n, p["portero"], p.get("estado"), p["sv_ventana"])
                for n, p, sv in ((g["home"]["nombre"], por_h, sv_h), (g["away"]["nombre"], por_a, sv_a)) if sv is not None and p)
        elif por_h or por_a:
            nota = "Porteros anunciados sin ventana suficiente para ajustar: %s." % "; ".join(
                "%s %s (%s)" % (n, p["portero"], p.get("estado")) for n, p in ((g["home"]["nombre"], por_h), (g["away"]["nombre"], por_a)) if p)
        else:
            nota = "Sin ajuste por portero titular (sin trabajo/porteros_<fecha>.json; corre colectores/recolectar_porteros.py)."
        if d.get("home_b2b") or d.get("away_b2b"):
            nota += " Back-to-back: %s (ofensiva x%.2f, defensa x%.2f, estimado de los datos)." % (
                " y ".join(n for n, k in ((g["home"]["nombre"], "home_b2b"), (g["away"]["nombre"], "away_b2b")) if d.get(k)),
                d.get("factor_of", 1.0), d.get("factor_df", 1.0))
        return {"p_home": r["p_home"], "p_away": r["p_away"], "unidad": "goles",
                "x_home": r["xg_home"], "x_away": r["xg_away"], "total": r["total"],
                "linea_total": r["linea_total"], "linea_es_mercado": tot_m is not None, "p_over": r["p_over"],
                "confianza": _conf(max(r["p_home"], r["p_away"])),
                "extra": [("Puck line local -1.5", r["p_pl_home"]), ("Puck line visita +1.5", r["p_pl_away"])],
                "spread": _spread_mercado(q, r["p_home"], r["xg_home"], r["xg_away"], lambda k, mu: hockey._pois(mu, k)),
                "descanso": d, "porteros": {"home": por_h, "away": por_a, "sv_home": sv_h, "sv_away": sv_a}, "nota": nota}, None

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
        spf = None
        if hd is not None and r.get("p_handicap_home") is not None:
            spf = {"linea_home": float(hd), "p_home": r["p_handicap_home"], "p_away": round(1 - r["p_handicap_home"], 4), "linea_es_mercado": True}
        return {"derivados": der, "p_home": r["p_home"], "p_draw": r["p_draw"], "p_away": r["p_away"], "unidad": "goles",
                "x_home": r["xg_home"], "x_away": r["xg_away"], "total": r["total_esperado"],
                "linea_total": r["linea_total"], "linea_es_mercado": tot_m is not None, "p_over": r["p_over"],
                "spread": spf, "confianza": _conf(top, tres=True), "extra": [], "nota": c.get("nota")}, None
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
    if m.get("spread") and q.get("spread_home_odds") is not None and q.get("spread_away_odds") is not None \
            and q.get("spread_home") is not None and abs(float(q["spread_home"]) - float(m["spread"]["linea_home"])) < 1e-6:
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
        est = "cuota_baja"       # edge positivo, pero la cuota paga menos que el minimo (1.70)
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
        if liga == "nhl":
            rec["xg_nhl"] = {"home": _xg_nhl(g["home"].get("abrev")), "away": _xg_nhl(g["away"].get("abrev")),
                             "fuente": "MoneyPuck (datos/equipos/nhl_xg.csv)"}

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


def predecir_juegos(juegos, cache, umbral=UMBRAL_EDGE, eventos=None):
    res, sin = [], []
    eventos = eventos if eventos is not None else sharp.cargar(os.path.join(BASE, "salida", "cuotas_casas.json"))[0]
    for g in juegos:
        if not (g.get("cuotas") or {}).get("ml_home") and eventos:
            # NPB, KBO, tenis: ESPN no publica cuotas; se toman de The Odds API (mejor cuota por lado, linea mas comun)
            try:
                prx = sharp.precios(eventos, g["liga"], g.get("fecha_utc"), g["home"]["nombre"], g["away"]["nombre"],
                                    tres_vias=DEPORTE.get(g["liga"]) == "futbol")
                q = sharp.cuotas_desde_sharp(prx)
                if q:
                    g["cuotas"] = q
            except Exception:
                pass
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
        try:
            decidir_picks(rec, g, eventos)
        except Exception as ex:
            rec["picks"] = []; rec["pick_top"] = None
            cache.avisos.append("picks %s %s: %s" % (g["liga"], g["id"], str(ex)[:80]))
        if not rec["modelo"]:
            sin.append("%s: %s @ %s -> %s" % (g["liga"].upper(), g["away"]["nombre"], g["home"]["nombre"], rec["motivo"]))
        res.append(rec)
    res.sort(key=lambda r: (r["fecha"], r["hora"], r["liga"]))
    return res, sin


# ================================================================== capas de decision de pick
_NIVEL = {"premium": 4, "pick": 3, "lean": 2, "revisar": 1, "pasar": 0}
_LIGAS_SESGO = ("nfl", "ncaafb")
# PICK PREMIUM: puntaje 0-100 que junta las capas. Pesos iniciales (se recalibran con el historial: cada pick guarda sus senales).
PESOS = {"precio": 30, "modelo": 20, "forma": 20, "movimiento": 10, "consenso": 10, "h2h": 5, "contexto": 5,
         # capas agregadas (2026-10-02): todo lo que trae la ficha. Pesos iniciales, sin validar: se miden con /minar
         # usando las senales que guarda historial_picks.csv. El puntaje se normaliza por el peso disponible.
         "osciladores": 10, "fuerza": 10, "abridor": 10, "bullpen": 5, "racha": 5}
CORTE = {"premium": 75, "pick": 60, "lean": 45}
# Con menos juegos que esto en la temporada actual, forma/osciladores/racha se apagan y fuerza usa solo el ELO.
# NFL/NCAAFB juegan 12-17 partidos: 3 ya son forma. Tenis no aplica (la ficha es por jugador y por torneo).
MIN_JUEGOS_TEMP = {"americano": 3, "tenis": 0, "default": 5}
_STATUS = {"Burning Hot": 1.0, "Hot": 0.6, "Average Up": 0.3, "Average": 0.0, "New": 0.0, "Average Down": -0.3, "Cold": -0.6, "Dead": -1.0}
_TEND = {"Subiendo": 1.0, "Estable": 0.0, "Bajando": -1.0}


def _bajar(nivel):
    return {"premium": "pick", "pick": "lean", "lean": "pasar"}.get(nivel, nivel)


def _lin(x, x0, x1, tope):
    """x0 -> 0, x1 -> tope, lineal y acotado."""
    if x is None:
        return tope / 2.0
    return max(0.0, min(tope, tope * (x - x0) / float(x1 - x0)))


DIAS_NUEVA_TEMP = 60   # si el ultimo juego del equipo es de hace mas de 60 dias respecto al partido, su "temporada" es la anterior


def _juegos_temp(t, fecha=None):
    """juegos del equipo en la temporada actual (ventana temp). Si su ultimo juego es de hace mas de DIAS_NUEVA_TEMP
    dias respecto al partido (NBA en octubre con 82 juegos de abril), la temporada vigente aun no empieza: 0."""
    if not t:
        return None
    n = ((t.get("ventanas") or {}).get("temp") or {}).get("n")
    n = int(n) if n is not None else 0
    u = (t.get("ultimo_juego") or "")[:10]
    if fecha and u:
        try:
            import datetime as _dt
            if (_dt.date.fromisoformat(fecha[:10]) - _dt.date.fromisoformat(u)).days > DIAS_NUEVA_TEMP:
                return 0
        except ValueError:
            pass
    return n


def temporada_corta(rec):
    """True si alguno de los dos equipos tiene menos de MIN_JUEGOS_TEMP juegos en la temporada actual: la forma reciente,
    los osciladores y la racha serian de la temporada pasada (otro plantel) y no deben puntuar."""
    f = rec.get("forma") or {}
    H, A = f.get("home") or {}, f.get("away") or {}
    if not H or not A:
        return False
    minimo = MIN_JUEGOS_TEMP.get(rec.get("deporte"), MIN_JUEGOS_TEMP["default"])
    if not minimo:
        return False
    nh, na = _juegos_temp(H, rec.get("fecha")), _juegos_temp(A, rec.get("fecha"))
    return min(nh, na) < minimo


def _senal_forma(rec, tipo, lado):
    """-1..1: que tan a favor del lado estan la forma reciente, los osciladores, la tendencia y el status."""
    import math
    f = rec.get("forma") or {}
    H, A = f.get("home") or {}, f.get("away") or {}
    if not H or not A or temporada_corta(rec):
        return None
    def osc(t, k):
        return float(((t.get("osciladores") or {}).get(k)) or 0.0)
    def l10(t, k):
        v = ((t.get("ventanas") or {}).get("L10") or {})
        return v.get(k)
    if tipo == "Total":
        # over: los dos equipos anotan/reciben mas en los ultimos 10 que en la temporada
        def ritmo(t):
            v = t.get("ventanas") or {}; a, b = v.get("L10") or {}, v.get("temp") or {}
            if not a or not b or not (b.get("gf") or 0) + (b.get("ga") or 0):
                return 0.0
            return ((a.get("gf") or 0) + (a.get("ga") or 0)) / float((b.get("gf") or 0) + (b.get("ga") or 0)) - 1.0
        r = (ritmo(H) + ritmo(A)) / 2.0 + 0.3 * (osc(H, "ataque") + osc(A, "ataque")) / 2.0
        x = math.tanh(3.0 * r)
        return x if lado == "over" else -x
    if lado == "draw":
        return None
    me, op = (H, A) if lado == "home" else (A, H)
    d = (osc(me, "forma") - osc(op, "forma"))
    pm, po = l10(me, "pts"), l10(op, "pts")
    if pm is not None and po is not None:
        d += 0.5 * (pm - po)
    d += 0.25 * (_TEND.get((me.get("osciladores") or {}).get("tendencia"), 0) - _TEND.get((op.get("osciladores") or {}).get("tendencia"), 0))
    d += 0.15 * (_STATUS.get(me.get("status"), 0) - _STATUS.get(op.get("status"), 0))
    return math.tanh(1.5 * d)


def _senal_h2h(rec, tipo, lado):
    h = rec.get("h2h_datos") or {}
    ult = h.get("ultimos") or []
    if tipo != "Ganador" or lado == "draw" or not ult:
        return None
    w = 0
    for u in ult[:5]:
        ma, mb = u.get("marcador_a"), u.get("marcador_b")
        if ma is None or mb is None:
            continue
        gana_home = ma > mb
        w += 1 if (gana_home == (lado == "home")) else 0
    n = len([u for u in ult[:5] if u.get("marcador_a") is not None])
    return (2.0 * w / n - 1.0) if n else None


def _senal_mov(rec, tipo, lado):
    mv = rec.get("movimiento") or {}
    if tipo == "Ganador":
        ml = mv.get("ml") or {}
        pts = ml.get("desplaza_pts")
        if pts is None or lado == "draw":
            return None
        hacia = ml.get("hacia")
        x = min(1.0, abs(pts) / 3.0)
        return x if hacia == lado else (-x if hacia in ("home", "away") else 0.0)
    if tipo == "Total":
        t = mv.get("total") or {}
        c = t.get("cambio")
        if c is None:
            return None
        x = min(1.0, abs(c) / 2.0)          # la linea sube = el mercado espera mas puntos (a favor del over)
        return (x if c > 0 else -x) if lado == "over" else (-x if c > 0 else x) if c else 0.0
    sp = mv.get("spread") or {}
    c = sp.get("cambio")
    if c is None:
        return None
    x = min(1.0, abs(c) / 2.0)              # spread del local baja (mas negativo) = mercado cree mas en el local
    return (x if c < 0 else -x) if lado == "home" else (-x if c < 0 else x) if c else 0.0


def _senal_consenso(rec, tipo, lado):
    c = rec.get("consenso") or {}
    f = c.get("fuentes") or {}
    if tipo != "Ganador" or len(f) < 2:        # con el modelo solo no hay consenso que medir
        return None
    return 2.0 * sum(1 for v in f.values() if v == lado) / len(f) - 1.0


def _senal_contexto(rec, tipo, lado):
    les = (rec.get("contexto") or {}).get("lesiones") or {}
    if tipo != "Ganador" or lado == "draw":
        return None
    me, op = ("home", "away") if lado == "home" else ("away", "home")
    d = len(les.get(op) or []) - len(les.get(me) or [])
    x = max(-1.0, min(1.0, d / 4.0))
    if rec.get("deporte") == "beisbol" and not rec[me].get("probable"):
        x -= 0.5
    return max(-1.0, x)


# ------------------------------------------------------------------ capas agregadas: todo lo disponible en la ficha
def _num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _lados_forma(rec):
    f = rec.get("forma") or {}
    H, A = f.get("home") or {}, f.get("away") or {}
    return (H, A) if H and A else (None, None)


def _escala(t):
    """carreras/goles/puntos por juego del equipo en la temporada (para normalizar diferenciales entre deportes)."""
    v = ((t.get("ventanas") or {}).get("temp") or {})
    s = (_num(v.get("gf")) or 0.0) + (_num(v.get("ga")) or 0.0)
    return max(1.0, s / 2.0)


def _senal_osciladores(rec, tipo, lado):
    """-1..1 con los osciladores que la senal de forma no usa: ataque, defensa (negativo = permite menos), dif5 y O/U."""
    import math
    H, A = _lados_forma(rec)
    if H is None or temporada_corta(rec):
        return None
    def o(t, k):
        return _num((t.get("osciladores") or {}).get(k)) or 0.0
    if tipo == "Total":
        if lado not in ("over", "under"):
            return None
        r = (o(H, "ataque") + o(A, "ataque") + o(H, "defensa") + o(A, "defensa")) / 4.0
        ou = [x for t in (H, A) for x in (t.get("ou4") or "").split("-") if x in ("O", "U")]
        po = (sum(1 for x in ou if x == "O") / float(len(ou)) - 0.5) * 2.0 if ou else 0.0
        x = 0.6 * math.tanh(3.0 * r) + 0.4 * po
        return x if lado == "over" else -x
    if lado not in ("home", "away"):
        return None
    me, op = (H, A) if lado == "home" else (A, H)
    d = (o(me, "ataque") - o(op, "ataque")) - (o(me, "defensa") - o(op, "defensa"))
    d += 0.5 * (o(me, "dif5") / _escala(me) - o(op, "dif5") / _escala(op))
    return math.tanh(1.5 * d)


def _senal_fuerza(rec, tipo, lado):
    """-1..1: ELO descriptivo, diferencial de temporada y el split que aplica (local del local, visita del visitante)."""
    import math
    H, A = _lados_forma(rec)
    if H is None or tipo == "Total" or lado not in ("home", "away"):
        return None
    me, op = (H, A) if lado == "home" else (A, H)
    sme, sop = ("local", "visita") if lado == "home" else ("visita", "local")
    def v(t, w, k):
        return _num(((t.get("ventanas") or {}).get(w) or {}).get(k))
    d = ((_num(me.get("elo")) or 1500.0) - (_num(op.get("elo")) or 1500.0)) / 200.0
    if temporada_corta(rec):
        return math.tanh(1.2 * d)          # temporada recien iniciada: solo el ELO (arrastra la fuerza del cierre anterior)
    dm, do = v(me, "temp", "dif"), v(op, "temp", "dif")
    if dm is not None and do is not None:
        d += 0.5 * (dm / _escala(me) - do / _escala(op))
    pm, po = v(me, sme, "pts"), v(op, sop, "pts")
    if pm is not None and po is not None:
        d += (pm - po)
    return math.tanh(1.2 * d)


def _senal_racha(rec, tipo, lado):
    """-1..1: racha actual y % de puntos en los ultimos 5."""
    import math
    H, A = _lados_forma(rec)
    if H is None or tipo == "Total" or lado not in ("home", "away") or temporada_corta(rec):
        return None
    me, op = (H, A) if lado == "home" else (A, H)
    def r(t):
        s = t.get("racha") or ""
        n = int(s[1:]) if len(s) > 1 and s[1:].isdigit() else 0
        return n if s[:1] == "W" else (-n if s[:1] == "L" else 0)
    def p5(t):
        return _num(((t.get("ventanas") or {}).get("L5") or {}).get("pts"))
    d = (r(me) - r(op)) / 6.0
    if p5(me) is not None and p5(op) is not None:
        d += p5(me) - p5(op)
    return math.tanh(1.2 * d)


def _abridor(rec, side):
    j = ((rec.get("jugadores_clave") or {}).get(side) or {})
    r5 = ((j.get("probable") or {}).get("resumen_ultimas5") or {})
    era, whip = _num(r5.get("era")), _num(r5.get("whip"))
    return (era, whip) if era is not None and whip is not None else (None, None)


ERA_REF, WHIP_REF = 4.00, 1.30     # abridor promedio de referencia cuando falta el del rival


def _senal_abridor(rec, tipo, lado):
    """beisbol: -1..1 con ERA y WHIP de las ultimas 5 salidas del abridor anunciado. Sin datos de un abridor se compara
    contra un abridor promedio; sin datos de ninguno no hay senal (KBO hoy)."""
    import math
    if rec.get("deporte") != "beisbol":
        return None
    eh, wh = _abridor(rec, "home")
    ea, wa = _abridor(rec, "away")
    if eh is None and ea is None:
        return None
    eh, wh = (eh, wh) if eh is not None else (ERA_REF, WHIP_REF)
    ea, wa = (ea, wa) if ea is not None else (ERA_REF, WHIP_REF)
    calidad = lambda e, w: (ERA_REF - e) / 2.0 + (WHIP_REF - w) / 0.30      # positivo = mejor que el promedio
    qh, qa = calidad(eh, wh), calidad(ea, wa)
    if tipo == "Total":
        if lado not in ("over", "under"):
            return None
        x = math.tanh(-0.5 * (qh + qa))       # abridores buenos = under
        return x if lado == "over" else -x
    if lado not in ("home", "away"):
        return None
    d = (qh - qa) if lado == "home" else (qa - qh)
    return math.tanh(0.6 * d)


def _senal_bullpen(rec, tipo, lado):
    """beisbol: -1..1 con los pitcheos del bullpen en los ultimos 3 juegos (mas pitcheos = mas cansado)."""
    import math
    if rec.get("deporte") != "beisbol":
        return None
    def bp(side):
        b = (((rec.get("jugadores_clave") or {}).get(side) or {}).get("bullpen") or {})
        return _num(b.get("pitches_total")) or None
    bh, ba = bp("home"), bp("away")
    if bh is None or ba is None:
        return None
    if tipo == "Total":
        if lado not in ("over", "under"):
            return None
        x = math.tanh((bh + ba - 300.0) / 150.0)     # bullpens cargados = mas carreras tarde
        return x if lado == "over" else -x
    if lado not in ("home", "away"):
        return None
    d = (ba - bh) if lado == "home" else (bh - ba)
    return math.tanh(d / 100.0)


def _razonar(rec, k):
    """Texto corto con el debate modelo vs forma vs mercado que lleva a la decision."""
    tipo, lado = k["mercado"].split()[0], k["lado"]
    f = rec.get("forma") or {}
    H, A = f.get("home") or {}, f.get("away") or {}
    me, op = (H, A) if lado == "home" else (A, H)
    def desc(t):
        if not t:
            return ""
        o = t.get("osciladores") or {}; l10 = (t.get("ventanas") or {}).get("L10") or {}
        partes = [x for x in (t.get("racha"), ("L10 %d-%d" % (l10.get("w", 0), l10.get("l", 0))) if l10 else None,
                              o.get("tendencia"), t.get("status")) if x and x not in ("Estable", "Average", "New")]
        return ", ".join(partes)
    fr = []
    fr.append("Modelo %.0f%% a %s%s." % (100 * k["p_modelo"], k["texto"], "" if k["validado"] else " (mercado sin validar)"))
    if tipo == "Ganador" and lado in ("home", "away") and (me or op):
        a, b = desc(me), desc(op)
        if a or b:
            fr.append("Forma: %s (%s) contra %s (%s)." % (rec["home" if lado == "home" else "away"]["nombre"], a or "sin senal",
                                                        rec["away" if lado == "home" else "home"]["nombre"], b or "sin senal"))
    s_ = k["senales"]
    if temporada_corta(rec):
        fr.append("Temporada recien iniciada: la forma reciente seria de la temporada pasada y no puntua; cuenta el precio, el modelo, el ELO y el contexto.")
    if s_.get("forma") is not None:
        fr.append("La forma %s." % ("apoya" if s_["forma"] >= 0.6 * PESOS["forma"] else ("va en contra" if s_["forma"] <= 0.3 * PESOS["forma"] else "no inclina")))
    extra = []
    for cap, nom in (("osciladores", "osciladores"), ("fuerza", "fuerza"), ("abridor", "abridor"), ("bullpen", "bullpen"), ("racha", "racha")):
        v = s_.get(cap)
        if v is not None:
            extra.append("%s %s" % (nom, "a favor" if v >= 0.6 * PESOS[cap] else ("en contra" if v <= 0.4 * PESOS[cap] else "neutro")))
    if extra:
        fr.append("Capas: %s." % ", ".join(extra))
    if s_.get("precio") is not None and k.get("ev") is not None:
        fr.append("Precio %s a %s: EV %+.1f%%." % (k["cuota"], k["casa"] or "la casa", 100 * k["ev"]))
    elif k.get("cuota_min"):
        fr.append("Sin cuota: vale desde %.2f." % k["cuota_min"])
    if s_.get("movimiento") is not None:
        fr.append("Linea %s." % ("a favor" if s_["movimiento"] > 0.6 * PESOS["movimiento"] else ("en contra" if s_["movimiento"] < 0.4 * PESOS["movimiento"] else "quieta")))
    if s_.get("consenso") is not None:
        fr.append("Consenso %s." % ("a favor" if s_["consenso"] >= 0.75 * PESOS["consenso"] else ("dividido" if s_["consenso"] > 0.25 * PESOS["consenso"] else "en contra")))
    fr.append("Decision: %s (%.0f pts)%s." % (k["nivel"].upper(), k["puntaje"], (": " + "; ".join(k["razones"])) if k["razones"] else ""))
    return " ".join(fr)


def puntuar_premium(rec, tipo, lado, ev_sharp, fuente, p_mod, p_sharp, validado):
    """Puntaje PICK PREMIUM 0-100 y sus senales. Devuelve (puntaje, senales, condicion)."""
    sen = {}
    # precio: con varias casas = EV sharp; con una casa = edge del modelo validado contra esa casa; sin cuota = no aplica
    if fuente == "sin_cuota":
        sen["precio"] = None
    elif fuente == "una_casa":
        sen["precio"] = _lin(p_mod - p_sharp, 0.0, 0.08, PESOS["precio"]) if validado else 0.0
    else:
        sen["precio"] = _lin(ev_sharp, -0.05, 0.05, PESOS["precio"])      # EV -5% = 0 pts, cuota justa = 15, +5% = 30
    # modelo
    tope_p = 0.65 if rec.get("deporte") in ("beisbol", "hockey") else 0.72     # en beisbol/hockey 60% ya es un favorito fuerte
    if validado:
        sen["modelo"] = _lin(p_mod - p_sharp, -0.05, 0.08, PESOS["modelo"]) if p_sharp is not None else _lin(p_mod, 0.45, tope_p, PESOS["modelo"])
    else:
        sen["modelo"] = _lin(p_mod, 0.45, tope_p, PESOS["modelo"] / 2.0)
    for k, fn in (("forma", _senal_forma), ("movimiento", _senal_mov), ("consenso", _senal_consenso), ("h2h", _senal_h2h), ("contexto", _senal_contexto),
                  ("osciladores", _senal_osciladores), ("fuerza", _senal_fuerza), ("abridor", _senal_abridor),
                  ("bullpen", _senal_bullpen), ("racha", _senal_racha)):
        x = fn(rec, tipo, lado)
        sen[k] = None if x is None else _lin(x, -1.0, 1.0, PESOS[k])
    disponibles = {k: v for k, v in sen.items() if v is not None}
    peso_disp = sum(PESOS[k] for k in disponibles)
    bruto = sum(disponibles.values())
    puntaje = 100.0 * bruto / peso_disp if peso_disp else 0.0
    # exigencia minima para premium: precio favorable (si hay cuota), forma a favor, y nada fuertemente en contra
    cond = []
    if sen.get("precio") is not None and sen["precio"] < 0.5 * PESOS["precio"]:
        cond.append("precio")
    if sen.get("forma") is not None and sen["forma"] < 0.6 * PESOS["forma"]:
        cond.append("forma")
    if sen.get("movimiento") is not None and sen["movimiento"] < 0.25 * PESOS["movimiento"]:
        cond.append("linea en contra")
    if temporada_corta(rec):
        f = rec.get("forma") or {}
        cond.append("temporada recien iniciada (%s %s j, %s %s j): forma, osciladores y racha apagados" % (
            rec["home"]["nombre"], _juegos_temp(f.get("home"), rec.get("fecha")), rec["away"]["nombre"], _juegos_temp(f.get("away"), rec.get("fecha"))))
    return round(puntaje, 1), {k: (None if v is None else round(v, 1)) for k, v in sen.items()}, cond


def decidir_picks(rec, g, eventos):
    """PICK PREMIUM por mercado y lado: puntaje 0-100 que junta precio (sharp vs mejor cuota), modelo, forma/osciladores,
    movimiento de linea, consenso, H2H y contexto. Vetos duros: pretemporada, empate, cuota fuera de 1.70-3.00,
    modelo >15 pts arriba del mercado (revisar), linea movida >=2 pts en contra. Sin cuota (NPB, KBO, tenis) se
    puntua sin la senal de precio y se entrega la CUOTA MINIMA para que el pick valga."""
    m = rec.get("modelo") or {}
    out = []
    liga = rec["liga"]
    tres = m.get("p_draw") is not None
    pr = sharp.precios(eventos, liga, g.get("fecha_utc"), rec["home"]["nombre"], rec["away"]["nombre"], tres,
                       total=m.get("linea_total") if m.get("linea_es_mercado") else None,
                       spread_home=(m.get("spread") or {}).get("linea_home")) if eventos else {}
    mv = rec.get("movimiento") or {}
    # candidatos: con cuota, cada lado de cada mercado; sin cuota, el ganador segun el modelo
    cand = [(x["mercado"], x["lado"], x) for x in rec.get("mercados") or []]
    if not cand and m.get("p_home") is not None:
        # sin cuota se puntuan LOS DOS lados: la forma puede voltear al favorito del modelo (se queda el que puntue mas)
        lados = {k[2:]: m[k] for k in ("p_home", "p_draw", "p_away") if m.get(k) is not None}
        cand = [("Ganador", l, {"mercado": "Ganador", "lado": l, "cuota": None, "p_modelo": pv, "p_mercado": None, "edge": 0.0, "estado": ""})
                for l, pv in lados.items() if l != "draw"]
    for mkt, lado, x in cand:
        tipo = mkt.split()[0]
        razones = []
        validado = (liga, tipo) not in NO_PUBLICABLE
        p_mod = x["p_modelo"]
        sp = (pr.get(tipo) or {}).get(lado)
        if sp:
            p_sharp, dec, cuota, casa, fuente, n_casas, ev_sharp = sp["p_sharp"], sp["mejor_decimal"], sp["mejor_cuota"], sp["casa"], sp["fuente"], sp["n_casas"], sp["ev"]
        elif x.get("cuota") is not None:
            p_sharp, cuota, casa, fuente, n_casas = x["p_mercado"], x["cuota"], (rec.get("cuotas") or {}).get("casa") or "espn", "una_casa", 1
            dec = mercado.american_a_decimal(cuota); ev_sharp = round(p_sharp * dec - 1, 4)
        else:
            p_sharp, cuota, casa, fuente, n_casas, dec, ev_sharp = None, None, "", "sin_cuota", 0, None, None
        p_fin = (PESO_SHARP * p_sharp + (1 - PESO_SHARP) * p_mod if validado else p_sharp) if p_sharp is not None else p_mod
        ev = (p_fin * dec - 1) if dec else None
        puntaje, sen, cond = puntuar_premium(rec, tipo, lado, ev_sharp, fuente, p_mod, p_sharp, validado)
        nivel = "premium" if puntaje >= CORTE["premium"] else ("pick" if puntaje >= CORTE["pick"] else ("lean" if puntaje >= CORTE["lean"] else "pasar"))
        if nivel == "premium" and cond:
            nivel = "pick"; razones.append("sin premium: " + ", ".join(cond))
        elif cond and any(c.startswith("temporada recien iniciada") for c in cond):
            razones.append([c for c in cond if c.startswith("temporada recien iniciada")][0])
        # ---- vetos duros
        if rec.get("pretemporada"):
            nivel = "pasar"; razones.append("pretemporada")
        if lado == "draw":
            nivel = "pasar"; razones.append("empate: -9% ROI en el backtest")
        if dec is not None and (dec < CUOTA_MIN or dec > CUOTA_MAX):
            if nivel != "pasar": razones.append("cuota %.2f fuera de %.2f-%.2f" % (dec, CUOTA_MIN, CUOTA_MAX))
            nivel = "pasar"
        if liga in _LIGAS_SESGO and nivel in ("pick", "premium") and ((tipo in ("Ganador", "Spread") and lado == "home") or (tipo == "Total" and lado == "over")):
            if puntaje < CORTE[nivel] + 5:
                nivel = _bajar(nivel); razones.append("local/over sobreapostado en %s: pide 5 pts mas" % liga.upper())
        if not validado and nivel != "pasar":
            razones.append("modelo sin validar en este mercado (pesa la mitad)")
        if validado and p_sharp is not None and (p_mod - p_sharp) >= EDGE_SOSPECHOSO and nivel != "pasar":
            nivel = "revisar"; razones.append("modelo %.0f pts arriba del mercado: revisar (lesion, abridor, portero)" % (100 * (p_mod - p_sharp)))
        if nivel in ("pick", "premium") and tipo == "Ganador" and lado in ("home", "away"):
            ml = mv.get("ml") or {}
            if abs(ml.get("desplaza_pts") or 0) >= 2 and ml.get("hacia") not in (lado, "sin_cambio", None):
                nivel = "pasar"; razones.append("la linea se movio %.1f pts en contra desde la apertura" % abs(ml["desplaza_pts"]))
        if fuente == "una_casa" and nivel == "premium":
            razones.append("una sola casa: el precio es contra DraftKings, no contra el mercado completo")
        if ev is not None and ev < 0.01 and nivel in ("pick", "premium"):
            nivel = "lean"; razones.append("EV %+.1f%%: sin margen contra la mejor cuota" % (100 * ev))
        # sin cuota: el pick queda condicionado a la cuota minima
        cuota_min = None
        if fuente == "sin_cuota":
            cuota_min = round(max(CUOTA_MIN, 1.05 / p_mod), 2)
            if 1.0 / p_mod < CUOTA_MIN and nivel in ("pick", "premium"):
                nivel = "lean"; razones.append("favorito claro: la cuota justa es %.2f y no llegara a %.2f" % (1.0 / p_mod, CUOTA_MIN))
            elif nivel in ("pick", "premium"):
                razones.append("sin cuota: vale solo si pagan %.2f o mas" % cuota_min)
        # stake plano: 1 unidad por pick (premium y pick); lean/revisar/pasar no llevan stake.
        stake = STAKE_PLANO if nivel in ("pick", "premium") else 0.0
        texto = {"home": rec["home"]["nombre"], "away": rec["away"]["nombre"], "draw": "Empate", "over": "Over", "under": "Under"}[lado]
        if tipo != "Ganador" and " " in mkt:
            texto = "%s %s" % (texto, mkt.split(" ", 1)[1])
        out.append({"mercado": mkt, "lado": lado, "texto": texto.strip(), "nivel": nivel, "puntaje": puntaje, "senales": sen,
                    "cuota": cuota, "decimal": round(dec, 3) if dec else None, "cuota_min": cuota_min, "casa": casa, "fuente": fuente, "n_casas": n_casas,
                    "p_sharp": None if p_sharp is None else round(p_sharp, 4), "p_modelo": round(p_mod, 4), "p_final": round(p_fin, 4),
                    "ev_sharp": None if ev_sharp is None else round(ev_sharp, 4), "ev": None if ev is None else round(ev, 4),
                    "validado": validado, "stake": round(stake, 4), "razones": razones})
    # un solo lado por mercado: se queda el de mayor puntaje
    mejor = {}
    for k in out:
        if k["nivel"] in ("pick", "premium") and (k["mercado"] not in mejor or k["puntaje"] > mejor[k["mercado"]]["puntaje"]):
            mejor[k["mercado"]] = k
    for k in out:
        if k["nivel"] in ("pick", "premium") and mejor[k["mercado"]] is not k:
            k["nivel"] = "lean"; k["stake"] = 0.0; k["razones"].append("el otro lado puntua mas")
    for k in out:
        try:
            k["razonamiento"] = _razonar(rec, k)
        except Exception:
            k["razonamiento"] = ""
    rec["picks"] = out
    top = max(out, key=lambda z: (_NIVEL[z["nivel"]], z["puntaje"])) if out else None
    rec["pick_top"] = top if top and top["nivel"] in ("premium", "pick", "lean") else None


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


MARGEN_INICIO_MIN = 5     # no se registra nada a menos de 5 min del inicio (ni despues)
_EN_JUEGO = ("final", "en juego", "in progress", "en curso", "terminado", "suspendido", "pospuesto", "postponed", "canceled", "cancelado")


def _inicio_utc(p):
    """Hora de inicio en UTC a partir de fecha + hora de CDMX del partido. None si no hay hora."""
    try:
        if not p.get("hora"):
            return None
        ini = dt.datetime.strptime("%s %s" % (p["fecha"], p["hora"]), "%Y-%m-%d %H:%M")
        return (ini - dt.timedelta(hours=TZ)).replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _ya_empezo(p):
    """True si el partido ya empezo (o empieza en menos de MARGEN_INICIO_MIN) o su estado dice que ya se juega/termino.
    Un pick registrado despues del inicio no cuenta: la cuota ya es en vivo."""
    est = (p.get("estado") or "").lower()
    if any(x in est for x in _EN_JUEGO):
        return True
    ini = _inicio_utc(p)
    if ini is None:
        return False
    return dt.datetime.now(dt.timezone.utc) >= ini - dt.timedelta(minutes=MARGEN_INICIO_MIN)


def _ahora_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def registrar(partidos, ruta):
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "pick", "prob", "confianza",
            "valor_mercado", "valor_lado", "valor_cuota", "valor_edge", "con_precio",
            "nivel", "p_sharp", "p_modelo", "ev", "casa", "fuente", "stake", "razones", "puntaje", "senales", "cuota_min", "razonamiento",
            "inicio_utc", "anulado"]
    existentes = set()
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            previas = list(csv.DictReader(f))
        existentes = {(r["liga"], r["id"], r.get("valor_mercado") or "", r.get("valor_lado") or "") for r in previas}
        existentes |= {(r["liga"], r["id"]) for r in previas if not r.get("nivel")}     # formato viejo: un pick por partido
        if previas and any(k not in previas[0] for k in cols):     # archivo con un formato anterior: se agregan columnas
            for r in previas:
                r.setdefault("con_precio", "si" if r.get("valor_cuota") else "")
                for k in cols:
                    r.setdefault(k, "")
            with _io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(previas)
    nuevos = []
    for p in partidos:
        if p.get("pretemporada") or not _cerca(p) or _ya_empezo(p):
            continue                        # ya empezo (cuota en vivo: no cuenta) o aun falta mucho: se registra en una corrida posterior (mas info: abridores, cuotas)
        if "if necessary" in ((p.get("nota") or "") + " " + (p.get("serie") or "")).lower():
            continue                        # juego condicional: puede no jugarse; se registra cuando deja de decir "If Necessary"
        # picks por mercado (fuerte y pick: los que llevan stake). Lean y revisar no entran al track record.
        for k in p.get("picks") or []:
            if k["nivel"] not in ("premium", "pick") or (p["liga"], p["id"], k["mercado"], k["lado"]) in existentes:
                continue
            nuevos.append({"registrado": _ahora_utc(), "inicio_utc": (_inicio_utc(p).strftime("%Y-%m-%dT%H:%MZ") if _inicio_utc(p) else ""), "liga": p["liga"], "id": p["id"],
                           "fecha": p["fecha"], "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                           "pick": k["texto"], "prob": k["p_final"], "confianza": k["nivel"],
                           "valor_mercado": k["mercado"], "valor_lado": k["lado"], "valor_cuota": k["cuota"], "valor_edge": k["ev"],
                           "con_precio": "si" if k["cuota"] is not None else "no", "nivel": k["nivel"], "p_sharp": k["p_sharp"], "p_modelo": k["p_modelo"],
                           "ev": k["ev"], "casa": k["casa"], "fuente": k["fuente"], "stake": k["stake"], "razones": "; ".join(k["razones"]),
                           "puntaje": k["puntaje"], "senales": json.dumps(k["senales"], ensure_ascii=False), "cuota_min": k["cuota_min"] or "",
                           "razonamiento": k.get("razonamiento", "")})
        # LECTURA del modelo: TODOS los partidos de TODOS los deportes, con o sin cuota, validado o no (decision 2026-10-02).
        # Sin stake: solo mide el acierto del ganador del modelo. VALOR / PICK / PREMIUM siguen con sus propias reglas.
        if p.get("pick") and (p["liga"], p["id"], "", "") not in existentes:
            c = p.get("cuotas") or {}
            lado = p["pick"].get("lado")
            ml = c.get("ml_home") if lado == "home" else (c.get("ml_away") if lado == "away" else None)
            notas = []
            if (p["liga"], "Ganador") in NO_PUBLICABLE:
                notas.append("ganador sin validar")
            notas.append(("cuota ML %+d (%s)" % (ml, c.get("casa", ""))) if ml is not None else "sin cuotas")
            nuevos.append({"registrado": _ahora_utc(), "inicio_utc": (_inicio_utc(p).strftime("%Y-%m-%dT%H:%MZ") if _inicio_utc(p) else ""), "liga": p["liga"], "id": p["id"],
                           "fecha": p["fecha"], "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                           "pick": p["pick"]["texto"], "prob": p["pick"]["prob"], "confianza": p["pick"]["confianza"],
                           "valor_mercado": "", "valor_lado": "", "valor_cuota": "", "valor_edge": "",
                           "con_precio": "si" if ml is not None else "no", "nivel": "lectura", "p_sharp": "", "p_modelo": p["pick"]["prob"], "ev": "",
                           "casa": "", "fuente": "", "stake": 0, "razones": "; ".join(notas), "puntaje": "", "senales": "", "cuota_min": "", "razonamiento": ""})
    if nuevos:
        nuevo_archivo = not os.path.exists(ruta)
        with _io.open(ruta, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            if nuevo_archivo:
                w.writeheader()
            w.writerows(nuevos)
    return len(nuevos)


def registrar_predicciones(partidos, ruta):
    """Una fila por partido y mercado del MODELO (Ganador, Total/Games, Spread, Breaks), registrada antes del juego
    (ventana de HORAS_REGISTRO). Mide al modelo contra la realidad aunque no haya cuota ni pick."""
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "mercado", "lado", "p_modelo", "valor_modelo", "linea",
            "p_mercado", "cuota", "validacion"]
    existentes = set()
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            existentes = {(r["liga"], r["id"], r["mercado"].split()[0]) for r in csv.DictReader(f)}
    ahora = _ahora_utc(); nuevos = []
    for p in partidos:
        m = p.get("modelo")
        if not m or p.get("pretemporada") or not _cerca(p) or _ya_empezo(p):
            continue
        if "if necessary" in ((p.get("nota") or "") + " " + (p.get("serie") or "")).lower():
            continue
        q = p.get("cuotas") or {}; val = p.get("validacion") or {}
        mk = {x["mercado"].split()[0] + "|" + x["lado"]: x for x in p.get("mercados") or []}
        def fila(mercado, lado, pm, vm=None, linea=None):
            base = mercado.split()[0]; x = mk.get(base + "|" + lado) or {}
            nuevos.append({"registrado": ahora, "liga": p["liga"], "id": p["id"], "fecha": p["fecha"], "home": p["home"]["nombre"],
                           "away": p["away"]["nombre"], "mercado": mercado, "lado": lado, "p_modelo": "" if pm is None else round(pm, 4),
                           "valor_modelo": "" if vm is None else round(vm, 3), "linea": "" if linea is None else linea,
                           "p_mercado": x.get("p_mercado", ""), "cuota": x.get("cuota", ""), "validacion": val.get(base if base != "Games" else "Total", "")})
        if (p["liga"], p["id"], "Ganador") not in existentes and m.get("p_home") is not None:
            lados = {k[2:]: m[k] for k in ("p_home", "p_draw", "p_away") if m.get(k) is not None}
            top = _lado_fav(lados); fila("Ganador", top, lados[top])
        if m.get("p_over") is not None and m.get("linea_total") is not None:
            nom = "Games" if p["tipo"] == "tenis" else "Total"
            if (p["liga"], p["id"], nom) not in existentes:
                fila("%s %s" % (nom, m["linea_total"]), "over" if m["p_over"] >= 0.5 else "under",
                     m["p_over"] if m["p_over"] >= 0.5 else 1 - m["p_over"], linea=m["linea_total"])
        sp = m.get("spread")
        if sp and sp.get("linea_home") is not None and (p["liga"], p["id"], "Spread") not in existentes:
            fila("Spread %+g" % sp["linea_home"], "home" if sp["p_home"] >= 0.5 else "away",
                 sp["p_home"] if sp["p_home"] >= 0.5 else sp["p_away"], linea=sp["linea_home"] if sp["p_home"] >= 0.5 else -sp["linea_home"])
        if p["tipo"] == "tenis" and (p["liga"], p["id"], "Breaks") not in existentes:
            for nom, v in m.get("extra") or []:
                if nom == "Breaks esperados" and isinstance(v, (int, float)):
                    fila("Breaks", "total", None, vm=float(v))
    if nuevos:
        nuevo = not os.path.exists(ruta)
        with _io.open(ruta, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            if nuevo: w.writeheader()
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
    npred = registrar_predicciones(partidos, os.path.join(a.salida, "historial_predicciones.csv"))

    con = [p for p in partidos if p["modelo"]]
    val = [p for p in partidos if p["valor"]]
    niv = {}
    for p in partidos:
        for k in p.get("picks") or []:
            niv[k["nivel"]] = niv.get(k["nivel"], 0) + 1
    ev_src, gen = sharp.cargar(os.path.join(BASE, "salida", "cuotas_casas.json"))
    print("\nPICKS por capas: %s | precios multi-casa: %s" % (
        ", ".join("%s %d" % (k, niv.get(k, 0)) for k in ("premium", "pick", "lean", "revisar", "pasar")),
        ("%d eventos (foto %s)" % (len(ev_src), gen)) if ev_src else "NO (solo ESPN: el nivel maximo es lean hasta que corra recolectar_cuotas.py)"))
    for p in partidos:
        for k in p.get("picks") or []:
            if k["nivel"] in ("premium", "pick"):
                print("  %-7s %5.1f pts %s %s | %s @ %s | %s %s a %s (%s) modelo %.1f%% %s stake %gu  senales %s%s" % (
                    k["nivel"].upper(), k["puntaje"], p["fecha"], p["hora"], p["away"]["nombre"], p["home"]["nombre"], k["mercado"], k["texto"],
                    k["cuota"] if k["cuota"] is not None else ("min %.2f" % k["cuota_min"]), k["casa"] or "-", 100 * k["p_modelo"],
                    ("EV %+.1f%%" % (100 * k["ev"])) if k["ev"] is not None else "", k["stake"],
                    " ".join("%s=%s" % (a, b) for a, b in k["senales"].items() if b is not None),
                    ("  [" + "; ".join(k["razones"]) + "]") if k["razones"] else ""))
    print("\n%d partidos: %d con prediccion, %d sin modelo, %d con VALOR (edge >= %d%%)."
          % (len(partidos), len(con), len(partidos) - len(con), len(val), int(a.umbral * 100)))
    if val:
        print("  (el detalle de VALOR esta en su apartado: python utilidades\\ver_predicciones.py --valor)")
    if cache.avisos:
        print("\nAvisos:"); [print("  -", x) for x in cache.avisos]
    if sin:
        print("\nSin prediccion (%d):" % len(sin)); [print("  -", x) for x in sin[:25]]
        if len(sin) > 25: print("  ... y %d mas" % (len(sin) - 25))
    print("\nPicks nuevos registrados en historial_picks.csv: %d | predicciones del modelo registradas: %d" % (nuevos, npred))
    print("Abre:  %s" % rh)


if __name__ == "__main__":
    main()
