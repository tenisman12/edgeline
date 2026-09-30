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
from nucleo import io, mercado, calibrar, equipos, estado
from modelos import beisbol, hockey, americano, nba, futbol
import recolectar_proximos as RP
import pagina_plataforma as PAG

BASE = io.BASE
UMBRAL_EDGE = 0.03        # edge minimo para marcar VALOR
# Pretemporada: ESPN no la marca en NHL, se detecta por fecha de inicio de la temporada regular.
PRE_INICIO = {"nhl": "2026-10-07"}
# Mercados que NO superaron al baseline en walk-forward: se muestran TODOS los datos, pero no se marcan
# VALOR ni se registran como pick. (liga, tipo) con tipo = Ganador | Total | Spread.
_BEIS = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")
NO_PUBLICABLE = set()
for _l in _BEIS:
    NO_PUBLICABLE.add((_l, "Total")); NO_PUBLICABLE.add((_l, "Spread"))
for _l in ("kbo", "lmp", "lvbp", "lidom", "abl"):      # ganador de beisbol: solo MLB y NPB superan al baseline
    NO_PUBLICABLE.add((_l, "Ganador"))
NO_PUBLICABLE.add(("nhl", "Total")); NO_PUBLICABLE.add(("nhl", "Spread"))
EDGE_SOSPECHOSO = 0.15    # arriba de esto se pide revisar (falta info: lesion, alineacion...)
TZ = RP.TZ_MX

DEPORTE = {"mlb": "beisbol", "nfl": "americano", "ncaafb": "americano", "nhl": "hockey", "nba": "nba",
           "premier": "futbol", "laliga": "futbol", "seriea": "futbol", "bundesliga": "futbol",
           "ligue1": "futbol", "ligamx": "futbol", "champions": "futbol", "mls": "futbol",
           "atp": "tenis", "wta": "tenis"}
NOMBRE = {"mlb": "MLB", "nfl": "NFL", "ncaafb": "NCAA Fútbol Americano", "nhl": "NHL", "nba": "NBA",
          "ncaamb": "NCAA Basketball", "premier": "Premier League", "laliga": "La Liga",
          "seriea": "Serie A", "bundesliga": "Bundesliga", "ligue1": "Ligue 1", "ligamx": "Liga MX",
          "champions": "Champions League", "mls": "MLS", "atp": "ATP", "wta": "WTA"}
MODS = {"hockey": hockey, "americano": americano, "nba": nba, "futbol": futbol}


# ================================================================== modelos (cache)
class Cache:
    def __init__(self):
        self.est, self.emp, self.avisos = {}, {}, []

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
            elif dep == "americano":
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
    if g["tipo"] == "tenis":
        j1, s1 = c["emp"].buscar(g["home"]["nombre"]); j2, s2 = c["emp"].buscar(g["away"]["nombre"])
        if not j1 or not j2:
            return None, "jugador sin historial en tus datos: %s" % (g["home"]["nombre"] if not j1 else g["away"]["nombre"])
        bo = g.get("best_of", 3); linea = 22.5 if bo == 3 else 38.5
        r = estado.tenis_predecir(c["st"], j1, j2, g.get("superficie", "Hard"), bo, linea)
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
        return {"p_home": r["p_home"], "p_draw": r["p_draw"], "p_away": r["p_away"], "unidad": "goles",
                "x_home": r["xg_home"], "x_away": r["xg_away"], "total": r["total_esperado"],
                "linea_total": r["linea_total"], "linea_es_mercado": tot_m is not None, "p_over": r["p_over"],
                "confianza": _conf(top, tres=True), "extra": [], "nota": c.get("nota")}, None
    return None, "sin modelo para este deporte"


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
               "modelo": None, "motivo": None, "mercados": [], "valor": None, "alerta": None, "pick": None,
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
                    if g.get("pretemporada") or (g["liga"] in PRE_INICIO and rec["fecha"] < PRE_INICIO[g["liga"]]):
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
        if not rec["modelo"]:
            sin.append("%s: %s @ %s -> %s" % (g["liga"].upper(), g["away"]["nombre"], g["home"]["nombre"], rec["motivo"]))
        res.append(rec)
    res.sort(key=lambda r: (r["fecha"], r["hora"], r["liga"]))
    return res, sin


# ================================================================== historial (base del track record)
def registrar(partidos, ruta):
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "pick", "prob", "confianza",
            "valor_mercado", "valor_lado", "valor_cuota", "valor_edge"]
    existentes = set()
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
            existentes = {(r["liga"], r["id"]) for r in csv.DictReader(f)}
    nuevos = []
    for p in partidos:
        if not p["pick"] or p.get("pretemporada") or (p["liga"], "Ganador") in NO_PUBLICABLE or (p["liga"], p["id"]) in existentes:
            continue
        v = p["valor"] or {}
        nuevos.append({"registrado": dt.datetime.now().isoformat(timespec="seconds"), "liga": p["liga"], "id": p["id"],
                       "fecha": p["fecha"], "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                       "pick": p["pick"]["texto"], "prob": p["pick"]["prob"], "confianza": p["pick"]["confianza"],
                       "valor_mercado": v.get("mercado", ""), "valor_lado": v.get("lado", ""),
                       "valor_cuota": v.get("cuota", ""), "valor_edge": v.get("edge", "")})
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
        ligas = [x.strip() for x in a.ligas.split(",")] if a.ligas else RP.DEFAULT
        print("1/3  Partidos por jugar (ESPN), proximos %d dia(s):" % a.dias)
        juegos = RP.recolectar(ligas, a.dias, not a.sin_contexto)
        RP.guardar(juegos)
    if not juegos:
        print("No hay partidos por jugar en ese rango."); return

    print("\n2/3  Prediciendo con tus modelos ...")
    cache = Cache()
    partidos, sin = predecir_juegos(juegos, cache, a.umbral)

    print("3/3  Escribiendo salida ...")
    os.makedirs(a.salida, exist_ok=True)
    data = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "tz": TZ, "umbral_edge": a.umbral,
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
    for p in val:
        v = p["valor"]
        print("  VALOR  %-9s %s @ %s   %s %s  cuota %+d  edge %+.1f%%  kelly %.1f%%"
              % (p["liga"].upper(), p["away"]["nombre"], p["home"]["nombre"], v["mercado"], v["lado"],
                 v["cuota"], v["edge"] * 100, v["kelly"] * 100))
    if cache.avisos:
        print("\nAvisos:"); [print("  -", x) for x in cache.avisos]
    if sin:
        print("\nSin prediccion (%d):" % len(sin)); [print("  -", x) for x in sin[:25]]
        if len(sin) > 25: print("  ... y %d mas" % (len(sin) - 25))
    print("\nPicks nuevos registrados en historial_picks.csv: %d" % nuevos)
    print("Abre:  %s" % rh)


if __name__ == "__main__":
    main()
