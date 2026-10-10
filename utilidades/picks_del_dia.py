# -*- coding: utf-8 -*-
"""
utilidades/picks_del_dia.py - UNA SOLA LISTA: decision por partido (ganador y total) y los MEJORES picks del dia (tope 4).

Analiza TODOS los partidos de salida/proximos.json y para cada uno deja una decision de ganador y una de total,
con su probabilidad final (precio sharp movido por el modelo cuando hay cuota; modelo solo cuando no la hay).
Despues elige los picks apostables con una sola regla de entrada:
  - beisbol (MLB, NPB, KBO): sistema estimado (salida/decidir.json) con confianza alta o media (EV >= 4% contra Pinnacle);
  - demas deportes: Pick Premium con nivel premium o pick, EV >= EV_MIN contra la mejor cuota;
  - cuota desde 1.70 (sin tope), sin pretemporada, hasta un ganador y un total por partido, ordenados por EV, maximo MAX_PICKS al dia y tope de bank.
Todo lo demas (leans, minima, revisar, lecturas sin precio) se sigue midiendo en sus historiales, pero NO es pick.

Salida: salida/picks_del_dia.json (decisiones + picks) y salida/historial_picks_dia.csv (los picks oficiales, para calificarlos).

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\picks_del_dia.py              # hoy
    python utilidades\\picks_del_dia.py --dias 2     # hoy y manana (los picks oficiales solo se registran para HOY)
    python utilidades\\picks_del_dia.py --max 3
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decidir_v2 as V2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from nucleo import angulos as ANG     # capa cualitativa: angulos activos con su medicion, sin peso en p
except Exception as _e:                   # sin la capa la lista sigue saliendo igual
    ANG = None; print("  capa de angulos no disponible: %s" % _e)

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_PICKS = int(os.environ.get("EDGELINE_MAX_PICKS", "4"))   # maximo 4 al dia, cada uno con confianza y por que si / por que no (Alejandro, 6-oct-2026)
TOPE_BANK = 0.10                      # suma de stakes del dia
MIN_APUESTAS_PUBLICO = 2000   # con menos apuestas el reparto boletos/dinero es ruido
# Ligas donde el reparto del TOTAL no se usa por sesgo de fuente. Vacio: NHL salio del veto porque la linea
# de totales se movio HACIA el over (5.5 -> 6.0 en cinco partidos), o sea que el precio corrobora la carga del
# publico en lugar de desmentirla. Que una liga cargue el over es un hecho conocido, no un error de lectura.
# Para revisarlo: utilidades\validar_publico.py (over por liga) y validar_contrapublico.py (si el under paga).
TOTAL_PUBLICO_VETADO = set()
_IGN_NOM = {"the", "fc", "sc", "club", "de", "los", "las", "la", "el", "st", "state", "university"}


def _clave(s):
    """nombre de equipo -> conjunto de palabras comparable entre fuentes distintas."""
    import re, unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _IGN_NOM)


def _mismo(a, b):
    """True si los dos nombres se refieren al mismo equipo (mitad de las palabras en comun)."""
    A, B = _clave(a), _clave(b)
    return bool(A and B) and len(A & B) / float(min(len(A), len(B))) >= 0.5
EV_MIN = 0.02                         # Pick Premium (deportes sin sistema estimado)
CUOTA_MIN, CUOTA_MAX = 1.70, 99.0   # sin tope de cuota (acuerdos 4-oct y 6-oct)
STAKE = {"alta": 0.03, "media": 0.02, "baja": 0.01, "premium": 0.02, "pick": 0.01}   # unidades 3/2/1 (acuerdo 4-oct)
TZ = -6


def _dec(am):
    am = float(am)
    return 1 + am / 100.0 if am > 0 else 1 + 100.0 / abs(am)


def _hoy():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()


def decision(rec, dec_bb=None, v2=None):
    """Decision de ganador y de total del partido con la mejor probabilidad disponible.
    Fuera de beisbol manda decidir_v2 (mezcla por capas con pesos medidos); beisbol sigue con decidir.py."""
    m = rec.get("modelo") or {}
    picks = rec.get("picks") or []
    if v2 and rec.get("deporte") != "beisbol":
        g = t = None
        dg, dtot = v2.get("ganador"), v2.get("total")
        if dg:
            # "ganador" = el lado con p_final >= 50% (quien gana); el valor puede estar en el otro lado (va en valor/)
            fav = max(dg.get("lados") or [], key=lambda e: e["p_final"]) if dg.get("lados") else None
            if fav and fav["lado"] != dg["lado"]:
                g = {"lado": fav["lado"], "nombre": rec[fav["lado"]]["nombre"], "p": fav["p_final"], "cuota": fav.get("cuota"), "fuente": "decidir_v2 (%s, peso modelo %.2f)" % (fav.get("fuente"), dg["peso_modelo"]),
                     "cuota_min": None, "ev": fav.get("ev"), "confianza": None, "unidades": 0, "conteo": None,
                     "valor": {"lado": dg["lado"], "nombre": dg["pick"], "p": dg["p_final"], "cuota": dg["cuota"], "ev": dg["ev"], "confianza": dg["confianza"], "unidades": dg["unidades"], "conteo": dg["conteo"]}}
            else:
                g = {"lado": dg["lado"], "nombre": dg["pick"], "p": dg["p_final"], "cuota": dg["cuota"], "fuente": "decidir_v2 (%s, peso modelo %.2f)" % (dg["fuente"], dg["peso_modelo"]),
                     "cuota_min": dg["cuota_min"], "ev": dg["ev"], "confianza": dg["confianza"], "unidades": dg["unidades"], "conteo": dg["conteo"]}
        if dtot:
            t = {"lado": dtot["lado"], "linea": dtot["mercado"].split()[1] if " " in dtot["mercado"] else m.get("linea_total"), "p": dtot["p_final"], "cuota": dtot["cuota"],
                 "fuente": "decidir_v2 (%s, peso modelo %.2f)" % (dtot["fuente"], dtot["peso_modelo"]), "ev": dtot["ev"], "confianza": dtot["confianza"], "unidades": dtot["unidades"], "conteo": dtot["conteo"]}
        if g or t:
            return g, t
    # En beisbol manda el sistema estimado: la decision del partido y el pick tienen que salir de la MISMA mezcla,
    # si no el reporte dice que gana un equipo y apuesta al otro.
    g = None
    d = (dec_bb or {}).get((rec["liga"], str(rec["id"]), rec["fecha"])) if dec_bb else None
    if d and d.get("p_final") is not None:
        pf = float(d["p_final"])
        lado = "home" if pf >= 0.5 else "away"
        g = {"lado": lado, "nombre": rec[lado]["nombre"], "p": pf if lado == "home" else 1 - pf,
             "cuota": None, "fuente": "sistema estimado", "cuota_min": None}
        picks = [k for k in picks if not (k["mercado"] == "Ganador")]
    gan = [k for k in picks if k["mercado"] == "Ganador" and k.get("p_final") is not None]
    if g is not None:
        pass                                   # ya la puso el sistema estimado (beisbol)
    elif gan:
        k = max(gan, key=lambda x: x["p_final"])
        g = {"lado": k["lado"], "nombre": k["texto"], "p": k["p_final"], "cuota": k.get("cuota"), "fuente": k.get("fuente"), "cuota_min": k.get("cuota_min")}
    elif m.get("p_home") is not None:
        lado = "home" if m["p_home"] >= (m.get("p_away") or 0) else "away"
        g = {"lado": lado, "nombre": rec[lado]["nombre"], "p": m["p_home"] if lado == "home" else m["p_away"], "cuota": None, "fuente": "modelo", "cuota_min": None}
    else:
        g = None
    tot = [k for k in picks if k["mercado"].startswith("Total") and k.get("p_final") is not None]
    if tot:
        k = max(tot, key=lambda x: x["p_final"])
        t = {"lado": k["lado"], "linea": k["mercado"].split()[1], "p": k["p_final"], "cuota": k.get("cuota"), "fuente": k.get("fuente")}
    elif m.get("p_over") is not None and m.get("linea_total") is not None:
        t = {"lado": "over" if m["p_over"] >= 0.5 else "under", "linea": m["linea_total"], "p": max(m["p_over"], 1 - m["p_over"]), "cuota": None, "fuente": "modelo"}
    else:
        t = None
    if rec.get("deporte") == "beisbol" and v2 and v2.get("total"):
        # 9-oct-2026: el total de beisbol pasa por decidir_v2 (capa de totales validada en MLB, NPB y LMP)
        dtot = v2["total"]
        t = {"lado": dtot["lado"], "linea": dtot["mercado"].split()[1] if " " in dtot["mercado"] else m.get("linea_total"), "p": dtot["p_final"], "cuota": dtot["cuota"],
             "fuente": "decidir_v2 (%s, peso modelo %.2f)" % (dtot["fuente"], dtot["peso_modelo"]), "ev": dtot["ev"], "confianza": dtot["confianza"], "unidades": dtot["unidades"], "conteo": dtot["conteo"]}
    return g, t


_DESCAL = None


SENAL_TXT = {"forma": "forma reciente", "h2h": "historial directo", "osciladores": "osciladores", "bullpen": "bullpen",
             "racha": "racha", "consenso": "modelo y mercado del mismo lado", "fuerza": "fuerza (ELO)", "movimiento": "movimiento de linea",
             "abridor": "abridor", "contexto": "contexto"}


def _abridor_txt(d, lado, a_favor):
    det = d.get("detalle_modelo") or {}
    ca = det.get("carreras_abridor")
    if ca in (None, 0, 0.0):
        return []
    mio = ca if lado == "home" else -ca
    if (mio > 0) != a_favor:
        return []
    return ["abridor %s %.2f carreras" % ("a favor" if mio > 0 else "en contra", abs(mio))]


def _osc(p, lado):
    o = (((p.get("forma") or {}).get(lado) or {}).get("osciladores")) or {}
    return o if any(o.get(k) not in (None, 0, 0.0) for k in ("forma", "ataque", "defensa", "dif5")) else None


def osciladores_txt(p, mercado, lado):
    """Osciladores de los dos equipos, SIEMPRE en por que si / por que no. Contexto sin peso: medidos el 6-oct-2026
    (trabajo/minar/2026-10-06_osciladores.md) no suman sobre las capas de produccion. Defensa: negativo = permite menos.
    Devuelve (texto, a_favor)."""
    h, a = _osc(p, "home"), _osc(p, "away")
    nh, na = p["home"].get("abrev") or p["home"]["nombre"], p["away"].get("abrev") or p["away"]["nombre"]
    if not h and not a:
        return "osciladores: sin senal (menos de 5 juegos en la temporada)", False
    def t(n, o):
        if not o:
            return "%s sin senal" % n
        return "%s forma %+.2f, ataque %+.2f, defensa %+.2f, dif5 %+.2f, %s" % (
            n, o.get("forma") or 0, o.get("ataque") or 0, o.get("defensa") or 0, o.get("dif5") or 0, (o.get("tendencia") or "-").lower())
    txt = "osciladores (contexto, sin peso): " + t(nh, h) + " | " + t(na, a)
    if str(mercado).startswith(("Total", "Games")):
        sube = sum(((o or {}).get("ataque") or 0) + ((o or {}).get("defensa") or 0) for o in (h, a))
        return txt, (sube > 0) == (str(lado).lower() == "over")
    me, op = (h, a) if lado == "home" else (a, h) if lado == "away" else (None, None)
    if me is None and op is None:
        return txt, True
    return txt, ((me or {}).get("forma") or 0) >= ((op or {}).get("forma") or 0)


def descalibrados():
    """(liga, 'Ganador'|'Total') donde el historial en vivo promete mucho mas de lo que acierta: n >= 30,
    p media - acierto >= 10 pp y z >= 2 (binomial). Ahi el modelo no se apuesta hasta que se corrija.
    Ejemplo (6-oct-2026): totales de NCAAF prometieron 60% y acertaron 39% (57 casos) contra la linea de la casa."""
    global _DESCAL
    if _DESCAL is not None:
        return _DESCAL
    import csv, math
    _DESCAL = {}
    ruta = os.path.join(BASE, "salida", "historial_predicciones_calificado.csv")
    if not os.path.exists(ruta):
        return _DESCAL
    acc = {}
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("estado") != "calificado" or r.get("acierto") in ("", None):
                continue
            tipo = (r.get("mercado") or "").split()[0]
            tipo = {"Games": "Total"}.get(tipo, tipo)
            if tipo not in ("Ganador", "Total"):
                continue
            try:
                p, y = float(r["p_modelo"]), int(float(r["acierto"]))
            except (TypeError, ValueError):
                continue
            a = acc.setdefault((r.get("liga"), tipo), [0, 0.0, 0.0, 0.0])
            a[0] += 1; a[1] += p; a[2] += y; a[3] += p * (1 - p)
    for k, (n, sp, sy, var) in acc.items():
        if n >= 30 and var > 0:
            gap = (sp - sy) / n; z = (sp - sy) / math.sqrt(var)
            if gap >= 0.10 and z >= 2.0:
                _DESCAL[k] = {"n": n, "p_media": round(sp / n, 3), "acierto": round(sy / n, 3), "z": round(z, 2)}
    return _DESCAL


def _marca(ap):
    """Una linea corta para la consola: que mercados de este partido son apostables y por que no los otros."""
    if not ap:
        return ""
    ok = [k for k, v in ap.items() if v.get("apostable")]
    no = ["%s: %s" % (k, v.get("motivo")) for k, v in ap.items() if not v.get("apostable") and v.get("motivo")]
    if ok:
        return "  >> APOSTABLE: " + ", ".join(ok) + (("  (" + "; ".join(no) + ")") if no else "")
    return "  (solo lectura: " + "; ".join(no) + ")"


def apostabilidad(rec, v2, dec_bb):
    """Por mercado, si ese partido puede generar pick y, si no, por que. Marca el NIVEL 1 (lectura de todos los
    partidos, que se califica para acumular muestra) para que nunca se confunda con el NIVEL 2 (la seleccion).
    Motivos, en el mismo orden en que cortan: pretemporada, mercado descalibrado en vivo, mercado sin validar
    en la liga, sin cuota, cuota fuera de rango, EV bajo el minimo, confianza insuficiente. 'apostable' en true
    significa que paso TODAS las capas y entro a candidatos; el tope de 4 al dia se aplica despues."""
    out = {}
    if rec.get("pretemporada"):
        return {"ganador": {"apostable": False, "motivo": "pretemporada"},
                "total": {"apostable": False, "motivo": "pretemporada"}}
    malos = descalibrados()
    def _descal(nombre):
        k = (rec.get("liga"), "Total" if nombre == "total" else "Ganador")
        d = malos.get(k)
        if not d:
            return None
        return ("mercado %s de %s descalibrado en vivo: prometio %.0f%% y acerto %.0f%% en %d casos" % (
            nombre, (rec.get("liga") or "").upper(), 100 * d["p_media"], 100 * d["acierto"], d["n"]))
    if rec.get("deporte") == "beisbol":
        d = (dec_bb or {}).get((rec["liga"], str(rec["id"]), rec["fecha"])) or {}
        k = d.get("pick") or {}
        mot = _descal("ganador")
        if not mot:
            if not d:
                mot = "sin sistema estimado (sin cuota de Pinnacle para este partido)"
            elif not k or k.get("mercado") != "Ganador":
                mot = "el sistema estimado no propone ganador"
            elif d.get("confianza") not in ("alta", "media"):
                mot = "confianza %s (en beisbol se exige alta o media)" % d.get("confianza")
        out["ganador"] = {"apostable": mot is None, "motivo": mot, "confianza": d.get("confianza"),
                          "ev": k.get("ev"), "cuota": k.get("decimal"), "cuota_min": k.get("cuota_min")}
    nombres = (("total", (v2 or {}).get("total")),) if rec.get("deporte") == "beisbol" else \
        (("ganador", (v2 or {}).get("ganador")), ("total", (v2 or {}).get("total")))
    for nombre, d in nombres:
        if not d:
            out[nombre] = {"apostable": False, "motivo": "sin modelo para este partido"}
            continue
        conf, dec, ev = d.get("confianza"), d.get("decimal"), d.get("ev")
        motivo = _descal(nombre)
        if motivo:
            pass
        elif conf in ("solo_mercado", "no_validado"):
            motivo = "mercado %s de %s: el modelo todavia no le gana a la tasa historica, p final = mercado" % (nombre, (rec.get("liga") or "").upper())
        elif d.get("fuente") == "sin_cuota" or dec is None:
            motivo = "sin cuota de mercado"
        elif dec < CUOTA_MIN:
            motivo = "cuota %.2f por debajo del minimo %.2f" % (dec, CUOTA_MIN)
        elif dec > CUOTA_MAX:
            motivo = "cuota %.2f por encima del maximo %.2f" % (dec, CUOTA_MAX)
        elif ev is None or ev < 0.01:
            motivo = "EV %+.1f%% por debajo del minimo +1.0%%" % (100 * (ev or 0))
        elif conf not in ("alta", "media", "baja"):
            motivo = "confianza %s" % conf
        out[nombre] = {"apostable": motivo is None, "motivo": motivo,
                       "confianza": conf, "ev": ev, "cuota": dec, "cuota_min": d.get("cuota_min")}
    return out


def candidatos(rec, dec_bb, v2=None):
    """picks apostables del partido segun su sistema: beisbol -> decidir; resto -> decidir_v2 (capas medidas)."""
    out = []
    if rec.get("pretemporada"):
        return out
    out_ = _candidatos(rec, dec_bb, v2)
    malos = descalibrados()
    return [k for k in out_ if (rec.get("liga"), "Total" if str(k.get("mercado", "")).startswith(("Total", "Games")) else "Ganador") not in malos]


def _candidatos(rec, dec_bb, v2=None):
    out = []
    if v2:
        if rec.get("deporte") == "beisbol":
            out += _candidatos_v2(rec, (v2.get("total"),))     # el total de beisbol por decidir_v2 (9-oct-2026)
        else:
            return _candidatos_v2(rec, (v2.get("ganador"), v2.get("total")))
    return out + _candidatos_resto(rec, dec_bb)


def _candidatos_v2(rec, decs):
    out = []
    if True:
        for d in decs:
            if not d or d["confianza"] not in ("alta", "media", "baja") or d.get("decimal") is None or d["fuente"] == "sin_cuota":
                continue
            if d["decimal"] < CUOTA_MIN or d["decimal"] > CUOTA_MAX or d.get("ev") is None or d["ev"] < 0.01:
                continue
            out.append({"origen": "decidir_v2", "mercado": d["mercado"], "lado": d["lado"], "pick": d["pick"], "cuota": d["cuota"], "decimal": round(d["decimal"], 3),
                        "casa": d.get("casa"), "p": d["p_final"], "ev": d["ev"], "confianza": d["confianza"], "stake": STAKE[d["confianza"]], "unidades": d["unidades"],
                        "senales": "%d a favor / %d en contra" % (d["conteo"]["a_favor"], d["conteo"]["en_contra"]),
                        "razon": ("p final %.1f%% (mercado %s, modelo %s, peso %.2f) contra %.2f | si: %s | no: %s | dudas: %s" % (
                            100 * d["p_final"], ("%.1f%%" % (100 * d["p_sharp"])) if d["p_sharp"] is not None else "-",
                            ("%.1f%%" % (100 * d["p_modelo"])) if d["p_modelo"] is not None else "-", d["peso_modelo"], d["decimal"],
                            "; ".join(d["por_que_si"][1:]) or "-", "; ".join(d["por_que_no"]) or "-", "; ".join(x["duda"] for x in d["dudas"]) or "ninguna"))[:900],
                        "_si": list(d["por_que_si"][1:]), "_no": list(d["por_que_no"]) + [x["duda"] for x in d["dudas"]]})
    return out


def _candidatos_resto(rec, dec_bb):
    out = []
    if rec.get("deporte") == "beisbol":
        d = dec_bb.get((rec["liga"], str(rec["id"]), rec["fecha"]))
        k = (d or {}).get("pick")
        if d and k and d.get("confianza") in ("alta", "media") and k["mercado"] == "Ganador":   # sin run line (acuerdo 4-oct)
            mercado = "Ganador"
            out.append({"origen": "sistema estimado", "mercado": mercado, "lado": k["lado"], "pick": k["texto"], "cuota": k["cuota"], "decimal": k["decimal"],
                        "casa": k.get("casa"), "p": k["p"], "ev": k["ev"], "confianza": d["confianza"], "stake": STAKE[d["confianza"]],
                        "senales": "%d a favor / %d en contra" % (k.get("senales_favor", 0), k.get("senales_contra", 0)),
                        "razon": "p final %.1f%% (Pinnacle %.1f%%, modelo %.1f%%) contra %s" % (100 * d["p_final"], 100 * (d["p_sharp"] or 0), 100 * (d["p_modelo"] or 0), k["cuota"]),
                        "_si": ["modelo %.1f%% contra Pinnacle %.1f%%" % (100 * (d["p_modelo"] or 0), 100 * (d["p_sharp"] or 0))] + _abridor_txt(d, k["lado"], True)
                               + [SENAL_TXT.get(x, x) for x in ((k.get("senales") or {}).get("a_favor") or [])],
                        "_no": _abridor_txt(d, k["lado"], False) + [SENAL_TXT.get(x, x) for x in ((k.get("senales") or {}).get("en_contra") or [])]})
        return out
    for k in rec.get("picks") or []:
        if k.get("nivel") not in ("premium", "pick") or k.get("ev") is None or k.get("cuota") is None:
            continue
        if str(k.get("mercado", "")).startswith("Spread"):   # solo ganador y totales (acuerdo 4-oct)
            continue
        dec = k.get("decimal") or _dec(k["cuota"])
        if k["ev"] < EV_MIN or not (CUOTA_MIN <= dec <= CUOTA_MAX):
            continue
        out.append({"origen": "pick premium", "mercado": k["mercado"], "lado": k["lado"], "pick": k["texto"], "cuota": k["cuota"], "decimal": round(dec, 3),
                    "casa": k.get("casa"), "p": k.get("p_final"), "ev": k["ev"], "confianza": k["nivel"], "stake": STAKE[k["nivel"]],
                    "senales": "%.0f pts" % (k.get("puntaje") or 0), "razon": (k.get("razonamiento") or "")[:220],
                    "_si": [x.strip() for x in (k.get("razonamiento") or "").split(". ") if x.strip() and "Decision" not in x][:5],
                    "_no": list(k.get("razones") or [])})
    return out


def _angulos(p, todos):
    if ANG is None:
        return []
    try:
        return ANG.calcular(p, todos)
    except Exception as e:
        print("  angulos fallo en %s %s: %s" % (p.get("liga"), p.get("id"), e))
        return []


def _empezado(p, ahora_cdmx):
    try:
        h = (p.get("hora") or "00:00")[:5]
        return dt.datetime.fromisoformat("%s %s" % (p["fecha"], h)) <= ahora_cdmx
    except ValueError:
        return p["fecha"] < ahora_cdmx.date().isoformat()


COLS_ANG = ["registrado", "liga", "id", "fecha", "home", "away", "home_key", "away_key", "codigo", "angulo", "lado", "x",
            "p_modelo_lado", "efecto_medido_pp", "veredicto_medido", "signo_esperado"]


def registrar_angulos(regs, ahora):
    """salida/historial_angulos.csv: para cada partido no empezado, los angulos activos (y una fila _TODOS por lado, que
    sirve para restar la calibracion del modelo en la liga). Se reescribe lo de partidos no empezados en cada corrida;
    lo de partidos ya empezados queda fijo. Lo mide utilidades/medir_angulos_vivo.py."""
    rh = os.path.join(BASE, "salida", "historial_angulos.csv")
    filas = []
    if os.path.exists(rh):
        with io.open(rh, encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
    nuevos = {(r["liga"], r["id"], r["fecha"]) for r in regs}
    filas = [r for r in filas if (r.get("liga"), r.get("id"), r.get("fecha")) not in nuevos] + regs
    filas.sort(key=lambda r: (r["fecha"], r["liga"], r["id"], r["codigo"], r["lado"]))
    with io.open(rh, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS_ANG, extrasaction="ignore")
        w.writeheader()
        for r in filas:
            w.writerow(r)
    return len(regs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=1)
    ap.add_argument("--max", type=int, default=MAX_PICKS)
    a = ap.parse_args()
    with io.open(os.path.join(BASE, "salida", "proximos.json"), encoding="utf-8") as f:
        D = json.load(f)
    dec_bb = {}
    try:
        with io.open(os.path.join(BASE, "salida", "decidir.json"), encoding="utf-8") as f:
            for d in json.load(f).get("partidos") or []:
                dec_bb[(d["liga"], str(d["id"]), d["fecha"])] = d
    except Exception:
        pass
    hoy = _hoy(); lim = (hoy + dt.timedelta(days=a.dias - 1)).isoformat()
    sel = [p for p in D["partidos"] if hoy.isoformat() <= p["fecha"] <= lim]
    publico = {}
    try:
        with io.open(os.path.join(BASE, "salida", "publico.json"), encoding="utf-8") as f:
            for q in json.load(f).get("partidos") or []:
                publico[(q["liga"], str(q["id"]))] = q
    except Exception:
        pass
    # movimiento de linea (salida/mercado_publico.json): cuanto se movio la probabilidad del grupo sharp
    # desde la apertura, en puntos porcentuales. Es CONTEXTO que se guarda para medir; no cambia p ni EV.
    movim = {}
    try:
        with io.open(os.path.join(BASE, "salida", "mercado_publico.json"), encoding="utf-8") as f:
            for m in json.load(f).get("partidos") or []:
                nom = (m.get("partido") or "").split(" @ ")
                if len(nom) != 2:
                    continue
                movim[(m.get("liga"), _clave(nom[1]), _clave(nom[0]))] = m
    except Exception:
        pass

    def movimiento(p, mercado, lado, nombre=None):
        """(mov_pp del lado apostado, senales del partido). mov > 0 = la linea sharp se movio A FAVOR de ese lado."""
        m = movim.get((p["liga"], _clave(p["home"]["nombre"]), _clave(p["away"]["nombre"])))
        if not m:
            return None, ""
        quiere = "total" if mercado.startswith("Total") else ("handicap" if mercado.startswith("Spread") else "ganador")
        for mk in m.get("mercados") or []:
            if mk.get("mercado") != quiere:
                continue
            mov = mk.get("mov_sharp_pp")
            if mov is None:
                return None, "; ".join(mk.get("senales") or [])
            lado_a = (mk.get("lado_a") or "")
            if quiere == "total":
                mismo = (lado == "over")
            elif quiere == "ganador":
                mismo = _mismo(nombre or "", lado_a)
            else:                                   # handicap: lado_a trae el nombre del equipo con la linea
                mismo = _mismo(p["home"]["nombre"], lado_a) if lado == "home" else not _mismo(p["home"]["nombre"], lado_a)
            return (round(mov if mismo else -mov, 2), "; ".join(mk.get("senales") or []))
        return None, ""

    def lado_publico(q, mercado, lado):
        """% de boletos y dinero del publico en el lado del pick (None si no hay o si el volumen es ruido)."""
        s = (q or {}).get("splits") or {}
        nb = (q or {}).get("num_bets")
        try:
            if nb is not None and float(nb) < MIN_APUESTAS_PUBLICO:
                return None, None
        except (TypeError, ValueError):
            pass
        if mercado.startswith("Total"):
            if (q or {}).get("liga") in TOTAL_PUBLICO_VETADO:
                return None, None      # la fuente carga el over de toda la liga: ese dato no es el publico
            d = s.get("total") or {}; t, m = d.get("tickets_over"), d.get("money_over")
            if lado == "under":
                t, m = (None if t is None else 100 - t), (None if m is None else 100 - m)
        elif mercado.startswith("Spread"):
            d = s.get("spread") or {}; t, m = d.get("tickets_home"), d.get("money_home")
            if lado == "away":
                t, m = (None if t is None else 100 - t), (None if m is None else 100 - m)
        else:
            d = s.get("ml") or {}; t, m = d.get("tickets_home"), d.get("money_home")
            if lado == "away":
                t, m = (None if t is None else 100 - t), (None if m is None else 100 - m)
        return t, m
    partidos, cand, regs_ang = [], [], []
    ahora_cdmx = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=TZ)
    reg_ts = dt.datetime.now().isoformat(timespec="seconds")
    for p in sel:
        v2 = None
        if p.get("modelo"):              # beisbol: decidir_v2 solo decide el TOTAL; el ganador sigue en decidir.py
            movs = {}
            for tipo, lados in (("Ganador", ("home", "away")), ("Total", ("over", "under"))):
                for ld in lados:
                    nombre = p[ld]["nombre"] if ld in ("home", "away") else None
                    mv_, _ = movimiento(p, tipo, ld, nombre)
                    if mv_ is not None:
                        movs[(tipo, ld)] = mv_
            try:
                v2 = V2.decidir_partido(p, movs)
            except Exception as e:
                v2 = None; print("  decidir_v2 fallo en %s %s: %s" % (p["liga"], p["id"], e))
        g, t = decision(p, dec_bb, v2)
        q = publico.get((p["liga"], str(p["id"])))
        mv_g = movimiento(p, "Ganador", "home", g["nombre"])[0] if g else None
        mv_t, sen_mov = movimiento(p, "Total", (t or {}).get("lado") or "over")
        fila = {"liga": p["liga"], "id": str(p["id"]), "fecha": p["fecha"], "hora": p.get("hora"), "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                "pretemporada": bool(p.get("pretemporada")), "ganador": g, "total": t, "sin_modelo": not p.get("modelo"),
                "mov_ganador": mv_g, "mov_total": mv_t, "senales_mercado": sen_mov,
                "publico": {"splits": (q or {}).get("splits"), "atencion": (q or {}).get("atencion")} if q else None,
                "nivel": 1, "es_lectura": True, "apostable": apostabilidad(p, v2, dec_bb),
                "decision_v2": v2}
        angs = _angulos(p, D["partidos"])
        fila["angulos"] = [ANG.resumen_json(x) for x in angs] if angs else []
        try:
            angs_t = ANG.calcular_totales(p, D["partidos"]) if ANG is not None else []
        except Exception as _e:
            angs_t = []; print("  angulos de totales fallo en %s %s: %s" % (p.get("liga"), p.get("id"), _e))
        fila["angulos_total"] = angs_t
        try:
            fila["marcador_angulos"] = ANG.calcular_equipos(p) if ANG is not None else None
        except Exception as _e:
            fila["marcador_angulos"] = None; print("  marcador con angulos fallo en %s %s: %s" % (p.get("liga"), p.get("id"), _e))
        fila["angulos_conteo"] = ANG.conteo(angs) if angs else None
        if ANG is not None and not p.get("pretemporada") and not _empezado(p, ahora_cdmx) and ANG._grupos(p.get("liga")):
            m_ = p.get("modelo") or {}
            hk, ak = ANG._equipo(p, "home"), ANG._equipo(p, "away")
            base_ = dict(registrado=reg_ts, liga=p["liga"], id=str(p["id"]), fecha=p["fecha"], home=p["home"]["nombre"],
                         away=p["away"]["nombre"], home_key=hk, away_key=ak)
            for ld in ("home", "away"):
                if m_.get("p_" + ld) is not None:
                    regs_ang.append(dict(base_, codigo="_TODOS", angulo="todos los partidos", lado=ld, x=0, p_modelo_lado=m_["p_" + ld]))
            for x in angs:
                md = x.get("medicion") or {}
                if m_.get("p_" + x["lado"]) is None:
                    continue
                regs_ang.append(dict(base_, codigo=x["codigo"], angulo=x["nombre"], lado=x["lado"], x=x["x"],
                                     p_modelo_lado=m_["p_" + x["lado"]], efecto_medido_pp=md.get("efecto_pp"),
                                     veredicto_medido=md.get("veredicto"), signo_esperado=md.get("signo_esperado")))
        partidos.append(fila)
        for c in candidatos(p, dec_bb, v2):
            tk, mn = lado_publico(q, c["mercado"], c["lado"])
            at = (q or {}).get("atencion") or {}
            mv, sen = movimiento(p, c["mercado"], c["lado"], c.get("pick"))
            cand.append(dict(c, liga=p["liga"], id=str(p["id"]), fecha=p["fecha"], hora=p.get("hora"), home=p["home"]["nombre"], away=p["away"]["nombre"],
                             torneo=p.get("torneo") or p.get("liga_nombre"), ronda=p.get("ronda") or p.get("nota"), cancha=p.get("cancha") or p.get("superficie") or p.get("superficie_estimada"),
                             publico_boletos=tk, publico_dinero=mn, notas_home=at.get("home"), notas_away=at.get("away"),
                             mov_linea=mv, senales_mercado=sen))
            cc = cand[-1]
            si, no = list(cc.pop("_si", None) or []), list(cc.pop("_no", None) or [])
            if mv is not None and abs(mv) >= 1.0:
                (si if mv > 0 else no).append("linea sharp %s %+.1f pp desde la apertura" % ("a favor" if mv > 0 else "en contra", mv))
            if sen and "SOLO PUBLICO" in sen:
                no.append("movimiento hecho por el publico (%s)" % sen[:80])
            if tk is not None:
                if tk >= 70: no.append("publico cargado en este lado (%s%% de boletos)" % tk)
                elif tk <= 35: si.append("publico del otro lado (%s%% de boletos aqui)" % tk)
            ruido = ("capas medidas no aplicadas",)
            si = [x for x in si if not x.startswith(ruido)]; no = [x for x in no if not x.startswith(ruido)]
            si, no = si[:6], no[:6]
            os_txt, os_favor = osciladores_txt(p, c["mercado"], c["lado"])
            if os_txt:
                (si if os_favor else no).append(os_txt)
            # capa cualitativa: angulos activos, con lo medido de cada uno; sin peso en p ni en el EV
            cc["angulos"] = "; ".join("%s:%s" % (x["codigo"], x["lado"]) for x in angs)
            cc["angulos_favor"] = cc["angulos_contra"] = None
            if angs and c["lado"] in ("home", "away") and not str(c["mercado"]).startswith(("Total", "Games")):
                fa, co, s_a, n_a = ANG.para_pick(angs, c["lado"])
                cc["angulos_favor"], cc["angulos_contra"] = fa, co
                si += s_a[:3]; no += n_a[:3]
            elif angs_t and c["lado"] in ("over", "under"):
                fa, co, s_a, n_a = ANG.totales_para_pick(angs_t, c["lado"])
                cc["angulos_favor"], cc["angulos_contra"] = fa, co
                cc["angulos"] = "; ".join("%s:%+.2f" % (x["codigo"], x["moveria"]) for x in angs_t)
                si += s_a[:3]; no += n_a[:3]
            cc["por_que_si"] = si; cc["por_que_no"] = no
    # mejores picks de HOY: hasta un ganador y un total por partido (Alejandro, 9-oct-2026: "quiero tambien picks de
    # totales"), por EV, tope de cantidad y de bank
    picks, usados, bank = [], set(), 0.0
    for c in sorted([c for c in cand if c["fecha"] == hoy.isoformat()], key=lambda c: -c["ev"]):
        k = (c["liga"], c["id"], "Total" if str(c.get("mercado", "")).startswith(("Total", "Games")) else "Ganador")
        if k in usados or len(picks) >= a.max or bank + c["stake"] > TOPE_BANK + 1e-9:
            continue
        usados.add(k); bank += c["stake"]; picks.append(c)
    descartados = [c for c in cand if c["fecha"] == hoy.isoformat() and c not in picks]
    ahora = dt.datetime.now().isoformat(timespec="seconds")
    # consola
    print("NIVEL 2 - PICKS SELECCIONADOS %s | %d partidos leidos | %d candidatos que pasaron todas las capas | %d picks (tope %d, bank %.0f%%)" % (
        hoy, len(partidos), len(cand), len(picks), a.max, 100 * bank))
    for i, c in enumerate(picks, 1):
        pub = ("" if c.get("publico_boletos") is None else " | publico %s%% boletos / %s%% dinero" % (c["publico_boletos"], c["publico_dinero"] if c.get("publico_dinero") is not None else "-"))
        if c.get("mov_linea") is not None:
            pub += " | linea %+.1f pp %s" % (c["mov_linea"], "a favor" if c["mov_linea"] > 0 else "en contra")
        sede = ("  [%s%s]" % (c.get("torneo") or "", (" - " + c["ronda"]) if c.get("ronda") else "")) if c.get("torneo") else ""
        print("  %d. %-5s %s %s | %-22s %-28s cuota %7s EV %+5.1f%% %-7s stake %.0f%% | %s%s%s" % (
            i, c["liga"], c["fecha"], c["hora"] or "", ("%s @ %s" % (c["away"], c["home"]))[:22], ((c["mercado"] + " " if c["mercado"].startswith("Total") else "") + c["pick"])[:28], c["cuota"], 100 * c["ev"], c["confianza"], 100 * c["stake"], c["senales"], pub, sede))
        print("       por que si: %s" % ("; ".join(c.get("por_que_si") or []) or "-"))
        print("       por que no: %s" % ("; ".join(c.get("por_que_no") or []) or "-"))
        if c.get("angulos_favor") is not None:
            print("       angulos: %d a favor / %d en contra (sin peso; activos: %s)" % (c["angulos_favor"], c["angulos_contra"], c.get("angulos") or "-"))
    if descartados:
        print("  candidatos fuera del tope: " + "; ".join("%s %s EV %+.1f%%" % (c["liga"], c["pick"], 100 * c["ev"]) for c in descartados[:6]))
    print("\nNIVEL 1 - LECTURA DE TODOS LOS PARTIDOS (se califica para acumular muestra; NO son picks):")
    for f in sorted(partidos, key=lambda x: (x["fecha"], x["liga"], x["hora"] or "")):
        g, t = f["ganador"], f["total"]
        print("  %-6s %s %s %-34s | GANA %-24s %s | %s" % (
            f["liga"], f["fecha"], (f["hora"] or "")[:5], ("%s @ %s" % (f["away"], f["home"]))[:34],
            (g["nombre"][:24] if g else "sin modelo"), ("%.0f%%" % (100 * g["p"]) if g else ""),
            ("%s %s %.0f%%" % (t["lado"].upper(), t["linea"], 100 * t["p"]) if t else "total: sin linea"))
            + ("" if f.get("mov_ganador") is None else " | linea %+.1f pp" % f["mov_ganador"])
            + ("  [pretemporada]" if f["pretemporada"] else "")
            + _marca(f.get("apostable"))
            + (("  | angulos " + ", ".join("%s(%s)" % (x["codigo"], x["equipo"]) for x in f["angulos"])) if f.get("angulos") else ""))
    with io.open(os.path.join(BASE, "salida", "picks_del_dia.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "fecha": hoy.isoformat(), "max_picks": a.max, "tope_bank": TOPE_BANK,
                   "como_leer": {
                       "nivel_2_picks": "'picks': la seleccion. Ya pasaron mercado validado y calibrado, capas medidas, "
                                        "EV >= +1%%, cuota entre %.2f y %.2f, conteo de senales y el tope de %d al dia. "
                                        "Esto es lo unico que se apuesta." % (CUOTA_MIN, CUOTA_MAX, a.max),
                       "nivel_2_fuera": "'candidatos_fuera': pasaron todas las capas y quedaron fuera solo por el tope del dia.",
                       "nivel_1_lectura": "'partidos': la prediccion de TODOS los partidos y mercados, con es_lectura=true. "
                                          "Se registra y se califica para acumular muestra. NO son picks. El campo 'apostable' "
                                          "de cada mercado dice si puede generar pick y, si no, por que.",
                       # Las claves de descalibrados() son tuplas (liga, mercado) y json.dump no las acepta:
                       # reventaba AQUI, despues de imprimir el reporte completo en consola, asi que la corrida
                       # se veia bien y salida/picks_del_dia.json se quedaba con la version anterior.
                       # El telefono lee ese JSON. Se serializan como "liga Mercado".
                       "descalibrados": {("%s %s" % (lg or "?", mk)): v for (lg, mk), v in descalibrados().items()},
                       "angulos": "'angulos' de cada partido: angulos situacionales activos (nucleo/angulos.py) con su medicion "
                                  "fuera de muestra (modelos/angulos_medidos.json). efecto_pp = cuanto rindio el equipo al que "
                                  "apunta el angulo contra el modelo. Ninguno paso la validacion: no cambian p ni EV. "
                                  "'angulos_conteo' = cuantos favorecen a cada lado (los de menos de 1 pp no cuentan). "
                                  "Se miden en vivo en salida/angulos_vivo.json."},
                   "picks": picks, "candidatos_fuera": descartados,
                   "partidos": partidos}, f, ensure_ascii=False, indent=1)
    rh = os.path.join(BASE, "salida", "historial_picks_dia.csv")
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "origen", "mercado", "lado", "pick", "cuota", "p", "ev", "confianza", "stake", "senales",
            "publico_boletos", "publico_dinero", "notas_home", "notas_away", "mov_linea", "senales_mercado", "unidades", "razon",
            "torneo", "ronda", "cancha", "por_que_si", "por_que_no", "angulos", "angulos_favor", "angulos_contra"]
    vistos = set()
    if os.path.exists(rh):
        with io.open(rh, encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f); previas = list(r); cab = r.fieldnames or []
            vistos = {(x["liga"], x["id"], x["fecha"]) for x in previas}
        # cabecera vieja: agregar filas con mas campos corre los valores de columna. Se reescribe antes de anexar.
        if cab and cab != cols:
            faltan = [c for c in cab if c not in cols]
            nueva = cols + faltan
            with io.open(rh, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=nueva, extrasaction="ignore")
                w.writeheader()
                for x in previas:
                    w.writerow(x)
            cols = nueva
            print("   (cabecera de historial_picks_dia.csv migrada: %d columnas -> %d, %d filas reescritas)" % (
                len(cab), len(nueva), len(previas)))
    nuevos = 0
    with io.open(rh, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not vistos and f.tell() == 0:
            w.writeheader()
        for c in picks:
            if (c["liga"], c["id"], c["fecha"]) in vistos:
                continue
            w.writerow(dict(c, registrado=ahora, por_que_si=" | ".join(c.get("por_que_si") or []),
                            por_que_no=" | ".join(c.get("por_que_no") or []))); nuevos += 1
    n_ang = registrar_angulos(regs_ang, ahora) if regs_ang else 0
    print("\nEscrito: salida/picks_del_dia.json | historial_picks_dia.csv: %d picks nuevos | historial_angulos.csv: %d filas de partidos no empezados" % (nuevos, n_ang))


if __name__ == "__main__":
    main()
