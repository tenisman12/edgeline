# -*- coding: utf-8 -*-
"""
utilidades/decidir_v2.py - DECISION POR CAPAS para todos los deportes menos beisbol (beisbol: utilidades/decidir.py).

Razona como lo hacemos a mano, con pesos medidos y todo guardado:
  1. Mercado: probabilidad sharp (Pinnacle; si no hay, consenso de casas) por lado, con la mejor cuota.
  2. Modelo: vota SOLO si ese mercado esta validado en esa liga (salida/validacion_mercados.json). Mezcla en logit: p_final = inv(logit(p_sharp) + w*(logit(p_modelo) - logit(p_sharp))),
     con w por liga (NHL 0.5, NFL 0.5 con -3.4 pp al over, NBA/NCAAF/tenis/futbol 0.35). Si el modelo esta
     "sin_validar" en ese mercado, pesa la mitad.
  3. EV = p_final * cuota - 1; confianza alta >= 8%, media 4-8%, baja 1-4%, minima < 1%; unidades 3/2/1/0.
     Cuota minima 1.70; sin cuota maxima. Solo Ganador y Total (nunca Spread). Siempre un lado del total.
  4. Brecha modelo-mercado en el lado del pick: ganador >= 10 pp -> minima y "revisar"; >= 15 pp -> "buscar la causa".
     Total: 10-15 pp baja un nivel de confianza (la probabilidad del total se mueve mas); >= 15 pp minima.
  5. Senales a favor / en contra (cada una con su fuente y su peso medido): modelo, mercado, movimiento de linea,
     capas medidas (tiros/PDO en NHL, L5/diferencial en NFL), back-to-back del rival, rebote tras 3+ derrotas,
     portero/abridor confirmado.
  6. Dudas medidas: bloques sin dato, modelo sin validar, una sola casa, portero sin confirmar, pocos juegos de
     temporada, capas no aplicadas; cada duda dice cuanto puede mover la decision.
Devuelve por partido: ganador (lado, p_final, cuota, EV, confianza, unidades, cuota_min, conteo, por_que_si, por_que_no),
total (igual, siempre con lado), dudas y un texto de razonamiento. picks_del_dia.py lo usa para la lista oficial.

    python utilidades\\decidir_v2.py            (imprime las decisiones de hoy; no escribe nada: lo escribe picks_del_dia)
Solo stdlib.
"""
import argparse, datetime as dt, io, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from nucleo import sharp as _sharp
except Exception:
    _sharp = None
try:
    from modelos import beisbol as _bb          # binomial negativa con la dispersion medida por liga
except Exception:
    _bb = None

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PESO_MODELO = {"nhl": 0.5, "nfl": 0.5, "ncaafb": 0.35, "nba": 0.35, "ncaamb": 0.35, "atp": 0.35, "wta": 0.35}
PESO_DEFAULT = 0.25                     # futbol y lo demas
# REGLA 4-oct (tarde): solo se apuesta lo VALIDADO. Si utilidades/validar_mercados.py no certifico ese mercado en esa
# liga (walk-forward, n>=300, z>=2, mejora en las dos mitades, calibrado), no hay pick: ni con peso reducido ni con
# nota al pie. El modelo se sigue mostrando como lectura, con 0 unidades.
SOLO_VALIDADO = True
AJUSTE_OVER = {"nfl": -0.034}           # el modelo de NFL sobreestima el over 3.4 pp (medido)
CUOTA_MIN = 1.70
CUOTA_LONGSHOT = 4.0                    # arriba de +300 la confianza baja un nivel (sin tope de cuota: sigue siendo pick)
UNIDADES = {"alta": 3, "media": 2, "baja": 1, "minima": 0, "sin_cuota": 0, "no_validado": 0}
BRECHA_REVISAR, BRECHA_BUSCAR = 0.10, 0.15
TZ = -6
# total: desviacion del total real alrededor del esperado del modelo, por deporte (de los MAE medidos: sd ~ 1.25*MAE)
SD_TOTAL = {"americano": 13.0, "nba": 19.0, "beisbol": 4.3, "tenis": 4.5}
EV_MAX_LINEA = 0.12          # una linea con mas de 12% de EV contra el modelo mezclado suele ser vieja o de otro mercado: se ignora
_EVENTOS = None


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _inv(z):
    return 1.0 / (1.0 + math.exp(-z))


def confianza(ev):
    if ev is None:
        return "sin_cuota"
    return "alta" if ev >= 0.08 else "media" if ev >= 0.04 else "baja" if ev >= 0.01 else "minima"


UNIDADES_CERO = ("minima", "sin_cuota", "no_validado")


def _lados(rec, tipo):
    """{lado: entrada de rec['picks']} del mercado (Ganador / Total)."""
    out = {}
    for k in rec.get("picks") or []:
        if k["mercado"].split()[0] == tipo and k.get("lado") in ("home", "away", "over", "under"):
            out[k["lado"]] = k
    return out


def _senales(rec, tipo, lado, p_mod, p_sharp, mov):
    """Lista de senales con direccion (+1 a favor del lado, -1 en contra, 0 neutra), fuente y peso medido."""
    s = []
    m = rec.get("modelo") or {}
    if p_mod is not None and p_sharp is not None:
        dif = p_mod - p_sharp
        s.append({"capa": "modelo vs mercado", "dir": 1 if dif >= 0.01 else (-1 if dif <= -0.01 else 0), "valor": "%+.1f pp" % (100 * dif), "peso": "voto completo (w por liga)"})
    elif p_mod is not None:
        s.append({"capa": "modelo", "dir": 1 if p_mod > 0.5 else -1, "valor": round(p_mod, 3), "peso": "sin cuota: el modelo es la unica probabilidad"})
    if mov is not None and abs(mov) >= 1.0:
        s.append({"capa": "movimiento de linea", "dir": 1 if mov > 0 else -1, "valor": round(mov, 1), "peso": "informacion, no ventaja (medido en futbol: apostar al movimiento pierde)"})
    cm = m.get("capas_medidas") or {}
    if tipo == "Ganador" and cm.get("aplicado"):
        pp = cm.get("ajuste_pp") or 0.0
        d = 1 if (pp > 0) == (lado == "home") else -1
        if abs(pp) >= 1.0:
            s.append({"capa": "capas medidas (%s)" % ("tiros L10 y PDO" if rec["liga"] == "nhl" else "L5 y diferencial"), "dir": d, "valor": round(abs(pp), 1),
                      "peso": "ya dentro del modelo: %+.1f pp" % pp})
    dsc = m.get("descanso") or {}
    if tipo == "Ganador" and (dsc.get("home_b2b") or dsc.get("away_b2b")):
        rival_b2b = dsc.get("away_b2b") if lado == "home" else dsc.get("home_b2b")
        propio_b2b = dsc.get("home_b2b") if lado == "home" else dsc.get("away_b2b")
        if rival_b2b and not propio_b2b:
            s.append({"capa": "rival en back-to-back", "dir": 1, "valor": 1, "peso": "+1.7 milesimas; cansado gana 44% vs 51% (ya en el modelo)"})
        elif propio_b2b and not rival_b2b:
            s.append({"capa": "propio back-to-back", "dir": -1, "valor": 1, "peso": "idem"})
    fr = rec.get("forma") or {}
    if tipo == "Ganador" and rec.get("deporte") in ("beisbol", "hockey"):
        for side, sign in (("home", 1 if lado == "home" else -1), ("away", 1 if lado == "away" else -1)):
            racha = str(((fr.get(side) or {}).get("racha")) or "")
            try:
                n = int(racha[1:])
            except ValueError:
                n = 0
            if racha.startswith("L") and n >= 3:
                s.append({"capa": "%s viene de %d derrotas" % (side, n), "dir": sign, "valor": racha, "peso": "+2-3 pp de rebote (medido)"})
            elif racha.startswith("W") and n >= 3:
                s.append({"capa": "%s viene de %d victorias" % (side, n), "dir": -sign, "valor": racha, "peso": "-1 a -2 pp (medido)"})
    por = m.get("porteros") or {}
    if tipo == "Ganador" and rec.get("liga") == "nhl":
        for side, sign in (("home", 1 if lado == "home" else -1), ("away", 1 if lado == "away" else -1)):
            p = por.get(side) or {}
            if p and str(p.get("estado", "")).lower().startswith("confirm"):
                s.append({"capa": "portero %s confirmado (%s)" % (side, p.get("portero")), "dir": 0, "valor": p.get("sv_ventana"), "peso": "contexto: sv% de 10 juegos no predice (medido ~0)"})
    return s


def _dudas(rec, tipo, lado_k, p_sharp, fuente):
    d = []
    m = rec.get("modelo") or {}
    val = (rec.get("validacion") or {}).get(tipo)
    if val and val != "publicable":
        d.append({"duda": "mercado %s sin validar en esta liga" % tipo, "efecto": "el modelo no vota: p_final = mercado; no se apuesta"})
    if p_sharp is None:
        d.append({"duda": "sin cuota de mercado", "efecto": "p_final = modelo; el pick vale solo si pagan la cuota minima"})
    elif fuente == "una_casa":
        d.append({"duda": "una sola casa (no Pinnacle)", "efecto": "la probabilidad de mercado puede estar 1-2 pp desviada"})
    bl = rec.get("bloques") or {}
    for b, v in bl.items():
        if isinstance(v, dict) and not v.get("ok") and b in ("forma", "estadisticas_equipo", "jugadores_clave", "movimiento"):
            d.append({"duda": "sin %s (%s)" % (b, v.get("motivo") or "sin dato"), "efecto": "contexto incompleto; no cambia p_final"})
    cm = m.get("capas_medidas")
    if cm is not None and not cm.get("aplicado"):
        d.append({"duda": "capas medidas no aplicadas (%s)" % cm.get("motivo", ""), "efecto": "faltan hasta +-6 pp de ajuste"})
    if rec.get("liga") == "nhl" and tipo == "Ganador":
        por = m.get("porteros") or {}
        for side in ("home", "away"):
            p = por.get(side)
            if not p:
                d.append({"duda": "portero de %s sin anunciar" % side, "efecto": "titular vs suplente: 3.5 pp en bruto, ~0 tras controlar por equipo"})
            elif not str(p.get("estado", "")).lower().startswith("confirm"):
                d.append({"duda": "portero de %s sin confirmar (%s)" % (side, p.get("portero")), "efecto": "idem"})
    for side in ("home", "away"):
        n = (((rec.get("forma") or {}).get(side) or {}).get("osciladores_detalle") or {}).get("n_temporada")
        if n is not None and n < 5:
            d.append({"duda": "%s con %d juegos de temporada" % (side, n), "efecto": "diferencial de temporada poco fiable; el ELO manda"})
            break
    return d


def _eventos():
    """salida/cuotas_casas.json (todas las casas, todas las lineas) cargado una vez."""
    global _EVENTOS
    if _EVENTOS is None:
        _EVENTOS = []
        if _sharp is not None:
            for base in (os.path.join(REPO, "salida"), os.path.join(BASE, "salida")):
                ruta = os.path.join(base, "cuotas_casas.json")
                if os.path.exists(ruta):
                    _EVENTOS = _sharp.cargar(ruta)[0] or []
                    break
    return _EVENTOS


def _pois_cdf(k, mu):
    """P(X <= k) Poisson."""
    if k < 0:
        return 0.0
    t = math.exp(-mu); acc = t
    for i in range(1, int(k) + 1):
        t *= mu / i; acc += t
    return min(1.0, acc)


def p_over_modelo(rec, linea):
    """Probabilidad del modelo de que el total pase la linea: (p_over, p_under, p_push) desde el total esperado."""
    m = rec.get("modelo") or {}
    mu = m.get("total")
    if mu is None:
        return None
    dep = rec.get("deporte"); tipo = rec.get("tipo")
    entera = abs(linea - round(linea)) < 1e-9
    if dep == "beisbol" and _bb is not None:
        rd = _bb.disp_total(rec.get("liga"))
        piso = int(math.floor(linea))
        pu = sum(_bb._nb_pmf(k, mu, rd) for k in range(0, piso + 1))
        if entera:
            push = _bb._nb_pmf(int(linea), mu, rd)
            return 1 - pu, max(0.0, pu - push), push
        return 1 - pu, pu, 0.0
    if dep in ("hockey", "futbol"):
        if entera:
            po = 1 - _pois_cdf(linea, mu); pu = _pois_cdf(linea - 1, mu)
        else:
            po = 1 - _pois_cdf(math.floor(linea), mu); pu = 1 - po
        return po, pu, max(0.0, 1 - po - pu)
    sd = SD_TOTAL.get("tenis" if tipo == "tenis" else dep, 10.0)
    def phi(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
    if entera:
        po = 1 - phi((linea + 0.5 - mu) / sd); pu = phi((linea - 0.5 - mu) / sd)
    else:
        po = 1 - phi((linea - mu) / sd); pu = 1 - po
    return po, pu, max(0.0, 1 - po - pu)


def _dec_am(x):
    x = float(x)
    return 1 + x / 100.0 if x > 0 else 1 + 100.0 / abs(x)


def comprar_linea(rec, w, excluir_casas=None):
    """Recorre TODAS las lineas de total de todas las casas y devuelve el (lado, linea, casa) con mejor EV, mezclando el
    modelo (p a esa linea) con el mercado de esa casa sin vig con el peso w. El margen en totales suele estar en la
    linea (6.0 vs 6.5), no en la cuota. Devuelve None si no hay evento o no hay lineas con los dos lados."""
    ev = None
    if _sharp is not None and _eventos():
        try:
            ev = _sharp._ev_de_partido(_eventos(), rec["liga"], rec.get("fecha_utc") or rec.get("fecha"), rec["home"]["nombre"], rec["away"]["nombre"])
        except Exception:
            ev = None
    if not ev:
        return None
    excl = set(excluir_casas or (getattr(_sharp, "EXCLUIR", set()) if _sharp else set()))
    lados = _sharp._lados(ev, "totals")
    opciones = []
    for casa, d in lados.items():
        if casa in excl or "over" not in d or "under" not in d:
            continue
        (co, pto), (cu, ptu) = d["over"], d["under"]
        if pto is None or ptu is None or abs(float(pto) - float(ptu)) > 1e-6:
            continue
        L = float(pto); do, du = _dec_am(co), _dec_am(cu)
        po_m, pu_m = 1.0 / do, 1.0 / du; s_ = po_m + pu_m
        po_mkt, pu_mkt = po_m / s_, pu_m / s_
        pm = p_over_modelo(rec, L)
        if pm is None:
            continue
        po_mod, pu_mod, push = pm
        # mezcla sobre probabilidad condicional a no-push
        def mix(p_mkt, p_mod):
            return _inv(_lg(p_mkt) + w * (_lg(p_mod) - _lg(p_mkt)))
        po_f = mix(po_mkt, po_mod / max(1e-6, 1 - push)) * (1 - push)
        pu_f = mix(pu_mkt, pu_mod / max(1e-6, 1 - push)) * (1 - push)
        for lado, dec, pf, pmk, pmo in (("over", do, po_f, po_mkt, po_mod), ("under", du, pu_f, pu_mkt, pu_mod)):
            evv = pf * dec - 1 + push * 1.0 * 0  # push devuelve la apuesta: EV = pf*dec + push*1 - 1
            evv = pf * dec + push - 1
            if evv > EV_MAX_LINEA:
                continue
            opciones.append({"casa": casa, "linea": L, "lado": lado, "decimal": round(dec, 3), "cuota_am": co if lado == "over" else cu,
                             "p_mercado": round(pmk, 4), "p_modelo": round(pmo, 4), "p_final": round(pf, 4), "p_push": round(push, 4), "ev": round(evv, 4)})
    if not opciones:
        return None
    opciones.sort(key=lambda o: -o["ev"])
    mejor = opciones[0]
    lineas = sorted({o["linea"] for o in opciones})
    return {"mejor": mejor, "n_casas": len({o["casa"] for o in opciones}), "lineas_disponibles": lineas,
            "top": opciones[:5]}


def decidir_mercado(rec, tipo, movs=None):
    """Decision de un mercado (Ganador o Total): evalua los dos lados y se queda con el de mejor EV (o mayor p sin cuota)."""
    m = rec.get("modelo") or {}
    liga = rec["liga"]
    w0 = PESO_MODELO.get(liga, PESO_DEFAULT)
    val = (rec.get("validacion") or {}).get(tipo)
    validado = (val == "publicable")
    w = w0 if validado else 0.0        # sin validacion el modelo no vota: la probabilidad es la del mercado
    lados = _lados(rec, tipo)
    if not lados:
        if tipo == "Ganador" and m.get("p_home") is not None:
            lados = {"home": {"p_modelo": m["p_home"], "p_sharp": None, "decimal": None, "cuota": None, "fuente": "sin_cuota", "mercado": "Ganador"},
                     "away": {"p_modelo": m["p_away"], "p_sharp": None, "decimal": None, "cuota": None, "fuente": "sin_cuota", "mercado": "Ganador"}}
        elif tipo == "Total" and m.get("p_over") is not None and m.get("linea_total") is not None:
            lados = {"over": {"p_modelo": m["p_over"], "p_sharp": None, "decimal": None, "cuota": None, "fuente": "sin_cuota", "mercado": "Total %s" % m["linea_total"]},
                     "under": {"p_modelo": 1 - m["p_over"], "p_sharp": None, "decimal": None, "cuota": None, "fuente": "sin_cuota", "mercado": "Total %s" % m["linea_total"]}}
        else:
            return None
    evals = []
    for lado, k in lados.items():
        p_mod = k.get("p_modelo"); p_sh = k.get("p_sharp"); dec = k.get("decimal")
        if p_mod is None and p_sh is None:
            continue
        if tipo == "Total" and p_mod is not None and liga in AJUSTE_OVER:
            p_mod = min(max(p_mod + (AJUSTE_OVER[liga] if lado == "over" else -AJUSTE_OVER[liga]), 0.01), 0.99)
        if p_sh is None:
            p_fin = p_mod
        elif p_mod is None:
            p_fin = p_sh
        else:
            p_fin = _inv(_lg(p_sh) + w * (_lg(p_mod) - _lg(p_sh)))
        ev = (p_fin * dec - 1) if dec else None
        mov = None
        if movs:
            mov = movs.get((tipo, lado))
        brecha = (p_mod - p_sh) if (p_mod is not None and p_sh is not None) else None
        evals.append({"lado": lado, "mercado": k.get("mercado", tipo), "p_modelo": None if p_mod is None else round(p_mod, 4),
                      "p_sharp": None if p_sh is None else round(p_sh, 4), "p_final": round(p_fin, 4), "peso_modelo": w,
                      "cuota": k.get("cuota"), "decimal": dec, "casa": k.get("casa"), "fuente": k.get("fuente"),
                      "ev": None if ev is None else round(ev, 4), "brecha_modelo_mercado": None if brecha is None else round(brecha, 4),
                      "mov_linea": mov, "senales": _senales(rec, tipo, lado, p_mod, p_sh, mov)})
    if not evals:
        return None
    con_ev = [e for e in evals if e["ev"] is not None]
    mejor = max(con_ev, key=lambda e: e["ev"]) if con_ev else max(evals, key=lambda e: e["p_final"])
    compra = None
    if tipo == "Total":
        try:
            compra = comprar_linea(rec, w)
        except Exception:
            compra = None
        if compra and (mejor["ev"] is None or compra["mejor"]["ev"] > (mejor["ev"] or -1) + 0.005):
            b = compra["mejor"]
            # la linea alternativa sustituye a la de referencia: misma estructura, con casa y linea propias
            ref = dict(mejor)
            mejor = {"lado": b["lado"], "mercado": "Total %g" % b["linea"], "p_modelo": b["p_modelo"], "p_sharp": b["p_mercado"], "p_final": b["p_final"],
                     "peso_modelo": w, "cuota": b["cuota_am"], "decimal": b["decimal"], "casa": b["casa"], "fuente": "linea_comprada",
                     "ev": b["ev"], "brecha_modelo_mercado": round(b["p_modelo"] - b["p_mercado"], 4), "mov_linea": ref.get("mov_linea"),
                     "senales": _senales(rec, tipo, b["lado"], b["p_modelo"], b["p_mercado"], ref.get("mov_linea")),
                     "linea_referencia": {"mercado": ref["mercado"], "lado": ref["lado"], "ev": ref["ev"], "decimal": ref["decimal"]}}
    conf = confianza(mejor["ev"])
    razones_no = []
    if SOLO_VALIDADO and not validado:
        razones_no.append("mercado %s de %s sin validar (walk-forward: el modelo no le gana a la base): lectura, no pick" % (tipo, liga.upper()))
        conf = "no_validado"
    if mejor["decimal"] is not None and mejor["decimal"] < CUOTA_MIN:
        razones_no.append("cuota %.2f menor a %.2f" % (mejor["decimal"], CUOTA_MIN)); conf = "minima" if conf != "sin_cuota" else conf
    br = mejor["brecha_modelo_mercado"]
    if br is not None and br >= BRECHA_BUSCAR:
        razones_no.append("modelo %.0f pp arriba del mercado: buscar la causa (lesion, alineacion, portero) antes de apostar" % (100 * br)); conf = "minima" if conf != "sin_cuota" else conf
    elif br is not None and br >= BRECHA_REVISAR:
        if tipo == "Ganador":
            razones_no.append("modelo %.0f pp arriba del mercado: revisar" % (100 * br)); conf = "minima" if conf != "sin_cuota" else conf
        else:
            razones_no.append("modelo %.0f pp arriba del mercado en el total: baja un nivel" % (100 * br))
            conf = {"alta": "media", "media": "baja", "baja": "minima"}.get(conf, conf)
    if mejor["decimal"] is not None and mejor["decimal"] > CUOTA_LONGSHOT and conf in ("alta", "media", "baja"):
        razones_no.append("cuota %.2f: el EV de un longshot depende de 1-2 pp de probabilidad que el modelo no afina; baja un nivel" % mejor["decimal"])
        conf = {"alta": "media", "media": "baja", "baja": "minima"}[conf]
    if rec.get("pretemporada"):
        razones_no.append("pretemporada"); conf = "minima"
    favor = [s for s in mejor["senales"] if s["dir"] > 0]; contra = [s for s in mejor["senales"] if s["dir"] < 0]
    if len(contra) > len(favor) and conf in ("alta", "media", "baja"):
        razones_no.append("mas senales en contra (%d) que a favor (%d): baja un nivel" % (len(contra), len(favor)))
        conf = {"alta": "media", "media": "baja", "baja": "minima"}[conf]
    for s in contra:
        razones_no.append("%s en contra (%s)" % (s["capa"], s["valor"]))
    razones_si = ["%s a favor (%s; %s)" % (s["capa"], s["valor"], s["peso"]) for s in favor]
    if mejor["ev"] is not None:
        razones_si.insert(0, "p final %.1f%% contra cuota %.2f: EV %+.1f%%" % (100 * mejor["p_final"], mejor["decimal"], 100 * mejor["ev"]))
    if mejor.get("linea_referencia"):
        lr = mejor["linea_referencia"]
        razones_si.append("linea comprada en %s (%s): mejor que la de referencia %s %s (EV %s)" % (
            mejor["casa"], mejor["mercado"], lr["lado"], lr["mercado"], ("%+.1f%%" % (100 * lr["ev"])) if lr["ev"] is not None else "-"))
    cuota_min = round(max(CUOTA_MIN, 1.0 / mejor["p_final"]), 2)
    texto = {"home": rec["home"]["nombre"], "away": rec["away"]["nombre"], "over": "Over", "under": "Under"}[mejor["lado"]]
    if tipo == "Total" and " " in mejor["mercado"]:
        texto = "%s %s" % (texto, mejor["mercado"].split(" ", 1)[1])
        if mejor.get("fuente") == "linea_comprada":
            texto += " (%s)" % mejor["casa"]
    return {"mercado": mejor["mercado"], "lado": mejor["lado"], "pick": texto, "p_final": mejor["p_final"], "p_modelo": mejor["p_modelo"],
            "p_sharp": mejor["p_sharp"], "peso_modelo": w, "cuota": mejor["cuota"], "decimal": mejor["decimal"], "casa": mejor["casa"], "fuente": mejor["fuente"],
            "ev": mejor["ev"], "cuota_min": cuota_min, "confianza": conf, "unidades": UNIDADES.get(conf, 0),
            "brecha_modelo_mercado": mejor["brecha_modelo_mercado"], "mov_linea": mejor["mov_linea"],
            "conteo": {"a_favor": len(favor), "en_contra": len(contra)}, "por_que_si": razones_si, "por_que_no": razones_no,
            "senales": mejor["senales"], "dudas": _dudas(rec, tipo, mejor, mejor["p_sharp"], mejor["fuente"]), "lados": evals,
            "compra_linea": compra, "linea_referencia": mejor.get("linea_referencia")}


def decidir_partido(rec, movs=None):
    """{'ganador': ..., 'total': ..., 'razonamiento': texto} para un partido que no es beisbol."""
    g = decidir_mercado(rec, "Ganador", movs)
    t = decidir_mercado(rec, "Total", movs)
    m = rec.get("modelo") or {}
    partes = []
    if m.get("x_home") is not None:
        partes.append("Modelo: %s %.1f - %s %.1f (total %.1f%s); gana %s %.0f%%." % (
            rec["home"]["nombre"], m["x_home"], rec["away"]["nombre"], m["x_away"], m.get("total") or 0,
            (" vs linea %s" % m["linea_total"]) if m.get("linea_total") is not None else "",
            rec["home"]["nombre"] if (m.get("p_home") or 0) >= 0.5 else rec["away"]["nombre"], 100 * max(m.get("p_home") or 0, m.get("p_away") or 0)))
    if m.get("nota"):
        partes.append(m["nota"])
    for nom, d in (("Ganador", g), ("Total", t)):
        if not d:
            partes.append("%s: sin modelo ni cuota." % nom); continue
        partes.append("%s: %s, p final %.1f%% (mercado %s, modelo %s, peso modelo %.2f)%s -> %s, %d u. A favor %d / en contra %d. Si: %s. No: %s. Dudas: %s." % (
            nom, d["pick"], 100 * d["p_final"], ("%.1f%%" % (100 * d["p_sharp"])) if d["p_sharp"] is not None else "sin cuota",
            ("%.1f%%" % (100 * d["p_modelo"])) if d["p_modelo"] is not None else "-", d["peso_modelo"],
            (", cuota %.2f EV %+.1f%%" % (d["decimal"], 100 * d["ev"])) if d["ev"] is not None else (", cuota minima %.2f" % d["cuota_min"]),
            d["confianza"], d["unidades"], d["conteo"]["a_favor"], d["conteo"]["en_contra"],
            "; ".join(d["por_que_si"]) or "-", "; ".join(d["por_que_no"]) or "-", "; ".join(x["duda"] for x in d["dudas"]) or "ninguna"))
    return {"ganador": g, "total": t, "razonamiento": " ".join(partes)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=1)
    a = ap.parse_args()
    sal = os.path.join(REPO, "salida") if os.path.exists(os.path.join(REPO, "salida", "proximos.json")) else os.path.join(BASE, "salida")
    with io.open(os.path.join(sal, "proximos.json"), encoding="utf-8") as f:
        D = json.load(f)
    hoy = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()
    fechas = {(hoy + dt.timedelta(days=i)).isoformat() for i in range(a.dias)}
    for p in D["partidos"]:
        if p.get("fecha") not in fechas or p.get("deporte") == "beisbol" or not p.get("modelo"):
            continue
        d = decidir_partido(p)
        print("\n%s %s %s  %s @ %s" % (p["liga"], p["fecha"], p.get("hora"), p["away"]["nombre"], p["home"]["nombre"]))
        print("  " + d["razonamiento"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
