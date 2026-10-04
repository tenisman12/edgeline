# -*- coding: utf-8 -*-
"""
utilidades/breaks.py - mercado de BREAKS totales en tenis: del modelo a la decision, con la linea de la casa.

Que hace:
  1. Lista los partidos de tenis proximos (salida/proximos.json) con los breaks esperados del modelo, el ajuste por
     sesgo medido (el modelo sobreestima ~0.3 breaks en tu historial calificado) y la desviacion tipica del error,
     para que sepas que linea seria "justa" antes de abrir la casa.
  2. Recibe la linea y cuotas de la casa (The Odds API no trae breaks, asi que se capturan a mano), calcula la
     probabilidad de over/under con una normal centrada en el modelo ajustado, el EV de cada lado y decide:
        pick solo si |modelo_ajustado - linea| >= UMBRAL (1.0 break), EV > 0 y cuota >= 1.70; siempre 1 unidad.
     Registra la linea en salida/historial_breaks.csv aunque no haya pick (asi se mide tambien la linea de la casa).
  3. calificar_picks.py califica ese archivo contra los breaks reales (bp enfrentados - bp salvados, de tenis.csv):
     acierto, unidades, ROI, y si el modelo le gana a la linea (MAE modelo vs MAE linea).

Sesgo y desviacion se recalculan solos del historial calificado (Breaks, n >= 30); si no hay, usa 0.3 y 2.1.

Uso (en C:\\Edgeline_repo; salida/ se toma del repo, datos/ de EDGELINE_BASE):
    python utilidades\\breaks.py                                   partidos de hoy y manana con breaks del modelo
    python utilidades\\breaks.py --dias 1                          solo hoy
    python utilidades\\breaks.py linea Swiatek 6.5 -115 +105       linea 6.5, over -115, under +105 (americano o decimal)
    python utilidades\\breaks.py linea Swiatek 6.5 1.87 1.95
    python utilidades\\breaks.py linea 184337 6.5 1.87 1.95        tambien por id del partido
  El nombre puede ser apellido de cualquiera de los dos jugadores; si hay mas de un partido que coincide, lo dice.
"""
import os, sys, csv, json, math, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io

UMBRAL = 1.0          # breaks de diferencia minima entre modelo ajustado y linea
CUOTA_MIN = 1.70
UNIDADES = 1.0
SESGO_DEF, SD_DEF = 0.3, 2.1
COLS = ["registrado", "liga", "id", "fecha", "home", "away", "torneo", "breaks_modelo", "sesgo", "sd", "breaks_ajustado",
        "linea", "cuota_over", "cuota_under", "p_over", "p_under", "ev_over", "ev_under", "pick", "cuota", "unidades", "motivo"]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _salida(nombre):
    """salida/ vive en el repo (rama main); si EDGELINE_BASE apunta a la carpeta de datos (C:\\Edgeline), usa la del repo."""
    r = os.path.join(REPO, "salida", nombre)
    return r if os.path.exists(os.path.join(REPO, "salida", "proximos.json")) else io.ruta("salida", nombre)


RUTA = _salida("historial_breaks.csv")


def _dec(x):
    """cuota americana o decimal -> decimal."""
    s = str(x).strip().replace(",", ".")
    v = float(s)
    if s.startswith(("+", "-")) or abs(v) >= 100:
        return round(1 + 100.0 / v, 4) if v > 0 else round(1 + 100.0 / abs(v), 4)
    return v


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def calibracion():
    """(sesgo = real - modelo, sd del error) del historial calificado de Breaks; defaults si n < 30."""
    ruta = _salida("historial_predicciones_calificado.csv")
    if not os.path.exists(ruta):
        return -SESGO_DEF, SD_DEF, 0
    err = []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("mercado") or "").split()[:1] == ["Breaks"] and r.get("estado") == "calificado":
                try:
                    err.append(float(r["real"]) - float(r["valor_modelo"]))
                except (TypeError, ValueError):
                    pass
    n = len(err)
    if n < 30:
        return -SESGO_DEF, SD_DEF, n
    m = sum(err) / n
    sd = math.sqrt(sum((e - m) ** 2 for e in err) / (n - 1))
    return round(m, 3), round(sd, 3), n


def probabilidades(ajustado, linea, sd):
    """p_over, p_under, p_push con normal(ajustado, sd); linea entera -> push posible (breaks son enteros)."""
    if abs(linea - round(linea)) < 1e-9:
        p_over = 1 - _phi((linea + 0.5 - ajustado) / sd)
        p_under = _phi((linea - 0.5 - ajustado) / sd)
    else:
        p_over = 1 - _phi((linea - ajustado) / sd)
        p_under = 1 - p_over
    return p_over, p_under, max(0.0, 1 - p_over - p_under)


def partidos(dias=2):
    ruta = _salida("proximos.json")
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    hoy = dt.date.today()
    fechas = {(hoy + dt.timedelta(days=i)).isoformat() for i in range(dias)}
    out = []
    for p in d.get("partidos", []):
        if p.get("tipo") != "tenis" or not p.get("modelo") or p.get("fecha") not in fechas:
            continue
        b = None
        for nom, v in p["modelo"].get("extra") or []:
            if nom == "Breaks esperados" and isinstance(v, (int, float)):
                b = float(v)
        if b is None:
            continue
        out.append({"liga": p["liga"], "id": str(p["id"]), "fecha": p["fecha"], "hora": p.get("hora", ""), "torneo": p.get("torneo", ""),
                    "home": p["home"]["nombre"], "away": p["away"]["nombre"], "breaks": b,
                    "games": p["modelo"].get("total"), "nota": p["modelo"].get("nota", "")})
    return sorted(out, key=lambda x: (x["fecha"], x["hora"]))


def buscar(ps, clave):
    k = io.norm(clave)
    ex = [p for p in ps if p["id"] == clave]
    if ex:
        return ex
    return [p for p in ps if k in io.norm(p["home"]) or k in io.norm(p["away"])]


def decidir(p, linea, c_over, c_under, sesgo, sd):
    aj = p["breaks"] + sesgo
    po, pu, _ = probabilidades(aj, linea, sd)
    ev_o, ev_u = po * c_over - 1, pu * c_under - 1
    dif = aj - linea
    pick, cuota, motivo = "", "", ""
    if abs(dif) < UMBRAL:
        motivo = "diferencia %.2f < %.1f break: ruido" % (dif, UMBRAL)
    elif dif > 0:
        if c_over < CUOTA_MIN: motivo = "over: cuota %.2f < %.2f" % (c_over, CUOTA_MIN)
        elif ev_o <= 0: motivo = "over: EV %.1f%% <= 0" % (100 * ev_o)
        else: pick, cuota, motivo = "over", c_over, "modelo %.1f vs linea %g, EV %+.1f%%" % (aj, linea, 100 * ev_o)
    else:
        if c_under < CUOTA_MIN: motivo = "under: cuota %.2f < %.2f" % (c_under, CUOTA_MIN)
        elif ev_u <= 0: motivo = "under: EV %.1f%% <= 0" % (100 * ev_u)
        else: pick, cuota, motivo = "under", c_under, "modelo %.1f vs linea %g, EV %+.1f%%" % (aj, linea, 100 * ev_u)
    return {"registrado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "liga": p["liga"], "id": p["id"],
            "fecha": p["fecha"], "home": p["home"], "away": p["away"], "torneo": p["torneo"], "breaks_modelo": round(p["breaks"], 2),
            "sesgo": sesgo, "sd": sd, "breaks_ajustado": round(aj, 2), "linea": linea, "cuota_over": c_over, "cuota_under": c_under,
            "p_over": round(po, 4), "p_under": round(pu, 4), "ev_over": round(ev_o, 4), "ev_under": round(ev_u, 4),
            "pick": pick, "cuota": cuota, "unidades": UNIDADES if pick else 0, "motivo": motivo}


def registrar(fila):
    existe = os.path.exists(RUTA)
    filas = []
    if existe:
        with open(RUTA, encoding="utf-8-sig", newline="") as f:
            filas = [r for r in csv.DictReader(f) if not (r["liga"] == fila["liga"] and r["id"] == fila["id"])]
    filas.append(fila)
    os.makedirs(os.path.dirname(RUTA), exist_ok=True)
    with open(RUTA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(filas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", nargs="?", default="ver", choices=["ver", "linea"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--dias", type=int, default=2)
    a = ap.parse_args()
    sesgo, sd, n = calibracion()
    ps = partidos(a.dias)
    print("Calibracion: sesgo %+.2f breaks (real - modelo), sd del error %.2f, n=%d%s" % (sesgo, sd, n, "" if n >= 30 else " (defaults)"))
    if a.accion == "ver":
        if not ps:
            print("Sin partidos de tenis con modelo en salida/proximos.json para %d dia(s)." % a.dias); return
        print("%-5s %-7s %-6s %-30s %-30s %6s %6s  %s" % ("liga", "id", "hora", "jugador 1", "jugador 2", "model", "ajust", "torneo"))
        for p in ps:
            print("%-5s %-7s %-6s %-30s %-30s %6.1f %6.1f  %s" % (p["liga"], p["id"], p["hora"], p["home"][:30], p["away"][:30],
                                                                 p["breaks"], p["breaks"] + sesgo, p["torneo"]))
        print("\nLinea justa ~ 'ajust'. Pick solo si la casa esta a >= %.1f break de distancia y cuota >= %.2f." % (UMBRAL, CUOTA_MIN))
        print("Cargar linea: python utilidades\\breaks.py linea <apellido|id> <linea> <cuota over> <cuota under>")
        return
    if len(a.args) != 4:
        print("Uso: breaks.py linea <apellido|id> <linea> <cuota over> <cuota under>"); return 1
    clave, linea, co, cu = a.args
    linea = float(linea.replace(",", ".")); co, cu = _dec(co), _dec(cu)
    m = buscar(ps, clave)
    if not m:
        print("No encontre un partido de tenis proximo con '%s' (mira la lista con: breaks.py)" % clave); return 1
    if len(m) > 1:
        print("Mas de un partido coincide; usa el id:")
        for p in m: print("  %s  %s vs %s  (%s %s)" % (p["id"], p["home"], p["away"], p["fecha"], p["hora"]))
        return 1
    p = m[0]
    fila = decidir(p, linea, co, cu, sesgo, sd)
    registrar(fila)
    print("%s vs %s  (%s, %s %s)" % (p["home"], p["away"], p["torneo"], p["fecha"], p["hora"]))
    print("  modelo %.1f breaks (%.1f games) -> ajustado %.1f;  linea %g  over %.2f / under %.2f" % (p["breaks"], p["games"] or 0, fila["breaks_ajustado"], linea, co, cu))
    print("  p_over %.1f%%  p_under %.1f%%   EV over %+.1f%%  EV under %+.1f%%" % (100 * fila["p_over"], 100 * fila["p_under"], 100 * fila["ev_over"], 100 * fila["ev_under"]))
    if fila["pick"]:
        print("  PICK: %s %g @ %.2f, %.0f unidad  (%s)" % (fila["pick"].upper(), linea, fila["cuota"], fila["unidades"], fila["motivo"]))
    else:
        print("  SIN PICK: %s" % fila["motivo"])
    print("  Registrado en salida/historial_breaks.csv (se califica solo con calificar_picks.py / Actions).")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
