# -*- coding: utf-8 -*-
"""
utilidades/decidir.py - SISTEMA ESTIMADO DE DECISION (beisbol: MLB, NPB, KBO).

Pone el precio con lo que SI predice (ver utilidades/pesos_capas.py y claude/pesos-capas-resultados.md):
  1. p_modelo  = logistica(ELO, diferencial de temporada) + abridor (carreras que salva contra el pitcheo de su equipo
                 en 5.5 IP, con la ERA de sus ultimas 5 salidas), con los coeficientes de modelos/decidir_beisbol.json.
  2. p_final   = Pinnacle sin vig (o consenso) movido hacia el modelo con peso PESO_MODELO en logit (0.25 fijo hasta
                 que haya cuotas historicas para estimarlo).
  3. Run line  = mapa calibrado por liga logit(p_gana) -> logit(p_cubre -1.5 / +1.5), estimado en pesos_capas.py
                 (el margen normal sobreestimaba la cobertura del favorito).
     Totales   = Pinnacle (el modelo de totales no mejora la base): no se pican.
  4. Pick      = mayor EV entre ML y run line con cuota 1.70-3.00. Confianza: alta EV>=8% (stake 3%), media 4-8% (2%),
                 baja 1-4% (1%), minima <1% (sin stake).
  5. Lectura   = conteo de senales del Pick Premium a favor / en contra (forma, osciladores, fuerza, racha, H2H, linea,
                 consenso, contexto, abridor, bullpen): desempata y se registra para medir si sistema+lectura acierta mas.

Entrada:  salida/proximos.json (plataforma.py) y modelos/decidir_beisbol.json (pesos_capas.py)
Salida:   salida/decidir.json y salida/historial_decidir.csv (una fila por partido y fecha; no repite)

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\decidir.py                 # hoy y manana
    python utilidades\\decidir.py --dias 1 --ligas kbo,npb
    python utilidades\\decidir.py --todos          # tambien los partidos sin cuota (solo p_modelo)
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, math, os, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
PESO_MODELO = float(os.environ.get("EDGELINE_PESO_MODELO", "0.25"))
HFA = 24.0                     # igual que nucleo/forma.py (beisbol)
IP_ABRIDOR = 5.5
IP_PRIOR = 30.0                # la ERA de 5 salidas es ruidosa: se encoge hacia el pitcheo del equipo con 30 IP de prior (fijo hasta estimarlo, punto 20)
CUOTA_MIN, CUOTA_MAX = 1.70, 99.0   # sin tope de cuota (acuerdo 4-oct): el EV decide; solo queda el minimo 1.70
MERCADOS_PICK = tuple((os.environ.get("EDGELINE_MERCADOS_PICK") or "Ganador").split(","))   # el run line se calcula pero no es pick (acuerdo 4-oct)
CONFIANZA = (("alta", 0.08, 0.03), ("media", 0.04, 0.02), ("baja", 0.01, 0.01), ("minima", -9.0, 0.0))
LIGAS = ("mlb", "npb", "kbo")
TZ = -6
# coeficientes de respaldo (estimados con la rama datos del 3-oct-2026, 14,760 juegos MLB/NPB/KBO) si falta el json
DEFECTO = {"ganador": {"beta": [0.039, 0.841, -0.002]}, "margen": {"beta": [-0.17, 1.93, 0.04], "sd": 4.31}, "logit_por_carrera": 0.405,
           "run_line": {"TODAS": {"mapa_-1.5": [-0.736, 0.958], "mapa_+1.5": [0.484, 0.997]}}}


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _phi_inv(p):
    """inversa de la normal estandar (Acklam), suficiente para margenes."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5; r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def _dec(am):
    am = float(am)
    return 1 + am / 100.0 if am > 0 else 1 + 100.0 / abs(am)


def _num(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def coeficientes():
    ruta = os.path.join(BASE, "modelos", "decidir_beisbol.json")
    try:
        with io.open(ruta, encoding="utf-8") as f:
            return json.load(f), "modelos/decidir_beisbol.json"
    except Exception:
        return DEFECTO, "defecto (corre utilidades/pesos_capas.py para estimarlos con tus datos)"


# ------------------------------------------------------------------ modelo
def abridor(rec, lado):
    """carreras que el abridor anunciado salva (o cuesta) contra el pitcheo de su equipo en IP_ABRIDOR innings; 0 sin datos."""
    j = ((rec.get("jugadores_clave") or {}).get(lado) or {}).get("probable") or {}
    r5 = j.get("resumen_ultimas5") or {}
    era = _num(r5.get("era")); ip = _num(r5.get("ip")); juegos = _num(r5.get("juegos")) or 0
    if era is None or not ip or ip < 10 or juegos < 3:
        return 0.0, None
    t = ((rec.get("forma") or {}).get(lado) or {})
    ga = _num(((t.get("ventanas") or {}).get("temp") or {}).get("ga"))
    if ga is None:
        return 0.0, None
    era_aj = (ip * era + IP_PRIOR * ga) / (ip + IP_PRIOR)
    return (ga - era_aj) * IP_ABRIDOR / 9.0, {"nombre": (j.get("jugador") or "").strip(), "era5": era, "ip5": ip, "era_ajustada": round(era_aj, 2), "ga_equipo": ga}


def p_modelo(rec, C):
    f = rec.get("forma") or {}
    H, A = f.get("home") or {}, f.get("away") or {}
    if not H or not A:
        return None, {}
    def dif(t):
        v = ((t.get("ventanas") or {}).get("temp") or {})
        return _num(v.get("dif")) or 0.0
    elo = ((_num(H.get("elo")) or 1500.0) + HFA - (_num(A.get("elo")) or 1500.0)) / 200.0
    d = dif(H) - dif(A)
    b = C["ganador"]["beta"]
    base = b[0] + b[1] * elo + b[2] * d
    sh, ih = abridor(rec, "home"); sa, ia = abridor(rec, "away")
    k = C.get("logit_por_carrera", 0.4)
    logit = base + k * (sh - sa)
    return _sig(logit), {"elo_h": H.get("elo"), "elo_a": A.get("elo"), "dif_h": dif(H), "dif_a": dif(A),
                         "p_base": round(_sig(base), 4), "abridor_h": ih, "abridor_a": ia, "carreras_abridor": round(sh - sa, 2)}


def precios(rec):
    """por mercado/lado: p_sharp (Pinnacle o consenso) y mejor cuota, de los picks de plataforma; None si no hay cuota."""
    out = {}
    for k in rec.get("picks") or []:
        if k.get("cuota") is None or k.get("fuente") == "sin_cuota":
            continue
        out[(k["mercado"].split()[0], k["lado"])] = {"p_sharp": k.get("p_sharp"), "cuota": k["cuota"], "casa": k.get("casa"),
                                                      "linea": k["mercado"].split()[1] if " " in k["mercado"] else None,
                                                      "senales": k.get("senales") or {}, "puntaje": k.get("puntaje"), "nivel": k.get("nivel")}
    return out


def conteo_senales(sen, PESOS):
    """senales del Pick Premium -> (a favor, en contra, lista). 'precio' y 'modelo' no cuentan: ya estan en el EV."""
    fav, con, det = [], [], []
    for cap, v in (sen or {}).items():
        if v is None or cap in ("precio", "modelo") or cap not in PESOS:
            continue
        if v >= 0.6 * PESOS[cap]:
            fav.append(cap)
        elif v <= 0.4 * PESOS[cap]:
            con.append(cap)
    return len(fav), len(con), {"a_favor": fav, "en_contra": con}


def decidir(rec, C, PESOS):
    pm, det = p_modelo(rec, C)
    pr = precios(rec)
    lg = rec["liga"].upper()
    g_h = pr.get(("Ganador", "home")); g_a = pr.get(("Ganador", "away"))
    ps = None
    if g_h and g_h.get("p_sharp") is not None:
        ps = float(g_h["p_sharp"])
    elif g_a and g_a.get("p_sharp") is not None:
        ps = 1 - float(g_a["p_sharp"])
    if pm is None and ps is None:
        return None
    if ps is None:
        pf, fuente = pm, "solo modelo (sin cuota)"
    elif pm is None:
        pf, fuente = ps, "solo mercado (sin ficha)"
    else:
        pf = _sig((1 - PESO_MODELO) * _logit(ps) + PESO_MODELO * _logit(pm)); fuente = "pinnacle %.0f%% + modelo %.0f%%" % (100 * (1 - PESO_MODELO), 100 * PESO_MODELO)
    sd = C["margen"]["sd"]
    margen = sd * _phi_inv(pf)                       # solo informativo
    rl = (C.get("run_line") or {}); mapa = rl.get(lg) or rl.get("TODAS") or DEFECTO["run_line"]["TODAS"]
    def p_cubre_home(linea_home):
        """P(local cubre su linea) con el mapa calibrado logit(p_gana) -> logit(p_cubre); otras lineas: margen normal."""
        try:
            L = float(linea_home)
        except (TypeError, ValueError):
            return None
        if abs(L + 1.5) < 1e-6:
            a, b = mapa["mapa_-1.5"]
        elif abs(L - 1.5) < 1e-6:
            a, b = mapa["mapa_+1.5"]
        else:
            return min(0.95, max(0.05, 1 - _phi((-L - margen) / sd)))
        return min(0.95, max(0.05, _sig(a + b * _logit(pf))))
    sp_h, sp_a = pr.get(("Spread", "home")), pr.get(("Spread", "away"))
    linea_h = (sp_h or {}).get("linea")
    if linea_h is None and sp_a and sp_a.get("linea") is not None:
        try:
            linea_h = str(-float(sp_a["linea"]))
        except ValueError:
            linea_h = None
    p_rl_h = p_cubre_home(linea_h) if linea_h is not None else None
    lados = []
    def lado(mercado, side, p, pr_):
        if not pr_:
            return
        dec = _dec(pr_["cuota"])
        ev = p * dec - 1
        fav, con, det_s = conteo_senales(pr_.get("senales"), PESOS)
        lados.append({"mercado": mercado, "lado": side, "texto": (rec["home"]["nombre"] if side == "home" else rec["away"]["nombre"]) + ("" if mercado == "Ganador" else " " + (pr_.get("linea") or "")),
                      "p": round(p, 4), "cuota": pr_["cuota"], "decimal": round(dec, 3), "casa": pr_.get("casa"), "ev": round(ev, 4),
                      "cuota_min": round(max(CUOTA_MIN, 1.0 / p), 2), "en_rango": CUOTA_MIN <= dec <= CUOTA_MAX,
                      "senales_favor": fav, "senales_contra": con, "senales": det_s, "premium_nivel": pr_.get("nivel"), "premium_pts": pr_.get("puntaje")})
    lado("Ganador", "home", pf, g_h); lado("Ganador", "away", 1 - pf, g_a)
    if p_rl_h is not None:
        lado("Run line", "home", p_rl_h, sp_h); lado("Run line", "away", 1 - p_rl_h, sp_a)
    cand = [l for l in lados if l["en_rango"] and l["mercado"] in MERCADOS_PICK]
    pick = max(cand, key=lambda l: l["ev"]) if cand else None
    conf, stake = "sin pick", 0.0
    if pick:
        for nombre, umbral, st in CONFIANZA:
            if pick["ev"] >= umbral:
                conf, stake = nombre, st; break
        # la lectura solo mueve un escalon y solo si es unanime
        # Regla 3 del criterio: el modelo 10+ pp arriba del mercado EN EL LADO DEL PICK es informacion que el
        # modelo NO ve (abridor, lesion, clima). En KBO pasa seguido porque no hay datos de abridores: revisar, no pick.
        BRECHA_REVISAR = 0.10
        if pm is not None and ps is not None:
            es_home = pick["lado"] == "home"
            pm_l = pm if es_home else 1 - pm
            ps_l = ps if es_home else 1 - ps
            if pm_l - ps_l >= BRECHA_REVISAR:
                conf, stake = "minima", 0.0
                pick["nota_lectura"] = "modelo %.0f pp arriba del mercado en el lado del pick: revisar, no pick" % (
                    100 * (pm_l - ps_l))
        # La lectura en contra ya no pide unanimidad: 3+ en contra con a lo mas 1 a favor baja un escalon.
        if pick["senales_contra"] >= 3 and pick["senales_favor"] <= 1 and conf in ("alta", "media"):
            conf = {"alta": "media", "media": "baja"}[conf]
            stake = {"media": 0.02, "baja": 0.01}[conf]
            pick["nota_lectura"] = "lectura %d en contra contra %d a favor: baja un escalon" % (
                pick["senales_contra"], pick["senales_favor"])
        if pick["senales_favor"] >= 3 and pick["senales_contra"] == 0 and conf in ("media", "baja"):
            conf = {"media": "alta", "baja": "media"}[conf]; stake = {"alta": 0.03, "media": 0.02}[conf]
            pick["nota_lectura"] = "lectura unanime a favor: sube un escalon"
        elif pick["senales_contra"] >= 3 and pick["senales_favor"] == 0 and conf in ("alta", "media"):
            conf = {"alta": "media", "media": "baja"}[conf]; stake = {"media": 0.02, "baja": 0.01}[conf]
            pick["nota_lectura"] = "lectura unanime en contra: baja un escalon"
    return {"liga": rec["liga"], "id": str(rec["id"]), "fecha": rec["fecha"], "hora": rec.get("hora"), "home": rec["home"]["nombre"], "away": rec["away"]["nombre"],
            "p_modelo": None if pm is None else round(pm, 4), "p_sharp": None if ps is None else round(ps, 4), "p_final": round(pf, 4), "fuente": fuente,
            "margen_esperado": round(margen, 2), "linea_home": linea_h, "p_runline_home": None if p_rl_h is None else round(p_rl_h, 4), "detalle_modelo": det, "lados": lados,
            "pick": pick, "confianza": conf, "stake": stake, "pretemporada": bool(rec.get("pretemporada"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=2)
    ap.add_argument("--ligas", default=",".join(LIGAS))
    ap.add_argument("--todos", action="store_true", help="incluir partidos sin cuota")
    a = ap.parse_args()
    try:
        from plataforma import PESOS
    except Exception:
        PESOS = {"forma": 20, "movimiento": 10, "consenso": 10, "h2h": 5, "contexto": 5, "osciladores": 10, "fuerza": 10, "abridor": 10, "bullpen": 5, "racha": 5}
    C, origen = coeficientes()
    with io.open(os.path.join(BASE, "salida", "proximos.json"), encoding="utf-8") as f:
        D = json.load(f)
    hoy = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()
    lim = (hoy + dt.timedelta(days=a.dias - 1)).isoformat()
    ligas = {x.strip() for x in a.ligas.split(",")}
    sel = [p for p in D["partidos"] if p["liga"] in ligas and hoy.isoformat() <= p["fecha"] <= lim and not p.get("pretemporada")]
    out = []
    for p in sel:
        r = decidir(p, C, PESOS)
        if r and (a.todos or r["p_sharp"] is not None):
            out.append(r)
    ahora = dt.datetime.now().isoformat(timespec="seconds")
    print("SISTEMA ESTIMADO | %d partidos (%s) | coeficientes: %s | peso modelo %.2f" % (len(out), ", ".join(sorted(ligas)), origen, PESO_MODELO))
    print("%-4s %-10s %-34s %6s %6s %6s | %-28s %7s %6s %7s %-7s %s" % ("liga", "fecha", "partido", "p_mod", "p_pin", "p_fin", "pick", "cuota", "EV", "c.min", "conf", "senales +/-"))
    for r in sorted(out, key=lambda x: (x["fecha"], x["liga"], x["hora"] or "")):
        k = r["pick"]
        print("%-4s %-10s %-34s %5.1f%% %5.1f%% %5.1f%% | %-28s %7s %+5.1f%% %7s %-7s %s" % (
            r["liga"], r["fecha"], ("%s @ %s" % (r["away"], r["home"]))[:34],
            100 * (r["p_modelo"] or 0), 100 * (r["p_sharp"] or 0), 100 * r["p_final"],
            (k["texto"][:28] if k else "-"), (k["cuota"] if k else ""), (100 * k["ev"] if k else 0.0), (k["cuota_min"] if k else ""),
            r["confianza"], ("%d/%d" % (k["senales_favor"], k["senales_contra"]) if k else "")))
    with io.open(os.path.join(BASE, "salida", "decidir.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "coeficientes": origen, "peso_modelo": PESO_MODELO, "partidos": out}, f, ensure_ascii=False, indent=1)
    # historial: una fila por (liga, id, fecha); no se repite
    rh = os.path.join(BASE, "salida", "historial_decidir.csv")
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "p_modelo", "p_sharp", "p_final", "mercado", "lado", "pick", "cuota", "ev",
            "cuota_min", "confianza", "stake", "senales_favor", "senales_contra", "premium_nivel", "premium_pts"]
    vistos = set()
    if os.path.exists(rh):
        with io.open(rh, encoding="utf-8-sig", newline="") as f:
            vistos = {(x["liga"], x["id"], x["fecha"]) for x in csv.DictReader(f)}
    nuevos = 0
    with io.open(rh, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not vistos and f.tell() == 0:
            w.writeheader()
        for r in out:
            if (r["liga"], r["id"], r["fecha"]) in vistos:
                continue
            k = r["pick"] or {}
            w.writerow({"registrado": ahora, "liga": r["liga"], "id": r["id"], "fecha": r["fecha"], "home": r["home"], "away": r["away"],
                        "p_modelo": r["p_modelo"], "p_sharp": r["p_sharp"], "p_final": r["p_final"], "mercado": k.get("mercado", ""), "lado": k.get("lado", ""),
                        "pick": k.get("texto", ""), "cuota": k.get("cuota", ""), "ev": k.get("ev", ""), "cuota_min": k.get("cuota_min", ""),
                        "confianza": r["confianza"], "stake": r["stake"], "senales_favor": k.get("senales_favor", ""), "senales_contra": k.get("senales_contra", ""),
                        "premium_nivel": k.get("premium_nivel", ""), "premium_pts": k.get("premium_pts", "")})
            nuevos += 1
    print("Escrito: salida/decidir.json | historial_decidir.csv: %d filas nuevas" % nuevos)


if __name__ == "__main__":
    main()
