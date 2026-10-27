# -*- coding: utf-8 -*-
"""
utilidades/analizar_cuotas_lmp.py - cuotas de LMP capturadas en vivo contra resultados y contra el modelo.

Fuente: semillas/lmp_cuotas_2026.csv (una fila por momio). Se llena en cada analisis de LMP con:
  - scores24 (paginas "-prediction": momio previo; a veces Bovada, a veces sin casa) y
  - las capturas de Novibet que pega Alejandro (con la hora de la captura).
Columnas: fecha_cdmx, local, visita, fuente, casa, captura, mercado_tipo (ML | Total | TT), equipo_total (solo TT),
lado (equipo para ML; O/U para totales), linea, momio (americano), final_local, final_visita.

Mide (todo descriptivo; nada cambia probabilidades ni picks):
  1. Mercado contra resultado: lado publicado de ML, totales y totales por equipo; por rango de momio, local/visita,
     over/under y linea. Probabilidad implicita sin vig: exacta si estan los dos lados de la misma casa y captura;
     con un solo lado se quita la mitad de un vig de 4.5 % (supuesto).
  2. Modelo contra mercado (juegos con prediccion en salida/historial_predicciones_calificado.csv): Brier del modelo y
     del mercado en el mismo juego, desacuerdos y quien acerto, apuestas sombra a 1 u en el lado con momio cuando el
     modelo da EV >= 4 %.
  3. Total del modelo (Carreras local + visita del motor) contra la linea y contra el real: sesgo, MAE y lado.
  4. Movimiento entre capturas de Novibet del mismo juego.
Escribe salida/cuotas_lmp_analisis.json.

Uso:
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/analizar_cuotas_lmp.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, json, math, os
from collections import defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("EDGELINE_BASE", CODIGO)
VIG_UN_LADO = 0.0225
EV_MIN = 0.04


def _r(*p):
    return os.path.join(BASE, *p)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def dec(am):
    am = float(am)
    return 1 + (am / 100 if am > 0 else 100 / -am)


def imp(am):
    return 1 / dec(am)


def _z(gan, esp):
    n = len(gan)
    if n == 0:
        return None
    var = sum(p * (1 - p) for p in esp)
    return round((sum(gan) - sum(esp)) / math.sqrt(var), 2) if var > 0 else None


def resumen(filas):
    """filas: dicts con gano (0/1), p (prob sin vig), dec (cuota decimal)."""
    n = len(filas)
    if not n:
        return {"n": 0}
    g = [f["gano"] for f in filas]
    p = [f["p"] for f in filas]
    u = sum((f["dec"] - 1) if f["gano"] else -1 for f in filas)
    return {"n": n, "gano": sum(g), "acierto_pct": round(100 * sum(g) / n, 1),
            "implicita_pct": round(100 * sum(p) / n, 1), "z": _z(g, p),
            "unidades": round(u, 2), "roi_pct": round(100 * u / n, 1)}


def cargar_cuotas():
    with open(_r("semillas", "lmp_cuotas_2026.csv"), encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def resultado(f):
    a, b = _num(f["final_local"]), _num(f["final_visita"])
    if a is None or b is None:
        return None
    t = f["mercado_tipo"]
    if t == "ML":
        if a == b:
            return None
        return int((f["lado"] == f["local"] and a > b) or (f["lado"] == f["visita"] and b > a))
    lin = _num(f["linea"])
    if t == "Total":
        v = a + b
    else:
        v = a if f["equipo_total"] == f["local"] else b
    if v == lin:
        return None
    return int(v > lin) if f["lado"] == "O" else int(v < lin)


def prob_sin_vig(filas):
    """agrega 'p' a cada fila: exacta si estan los dos lados en la misma (juego, fuente, casa, captura, mercado, linea)."""
    grupos = defaultdict(list)
    for f in filas:
        k = (f["fecha_cdmx"], f["local"], f["fuente"], f["casa"], f["captura"], f["mercado_tipo"], f["equipo_total"], f["linea"])
        grupos[k].append(f)
    for g in grupos.values():
        lados = {f["lado"] for f in g}
        if len(g) == 2 and len(lados) == 2:
            s = imp(g[0]["momio"]) + imp(g[1]["momio"])
            for f in g:
                f["p"], f["p_metodo"] = imp(f["momio"]) / s, "dos_lados"
        else:
            for f in g:
                f["p"], f["p_metodo"] = imp(f["momio"]) / (1 + VIG_UN_LADO), "un_lado"
    return filas


def banda(am):
    am = float(am)
    if am >= 100:
        return "+100 o mas"
    if am > -130:
        return "-101 a -129"
    if am > -160:
        return "-130 a -159"
    if am > -200:
        return "-160 a -199"
    return "-200 o menos"


def cargar_modelo():
    """por (fecha, local): p_home del modelo y total del motor (ultima prediccion registrada antes del juego)."""
    ruta = _r("salida", "historial_predicciones_calificado.csv")
    out = defaultdict(dict)
    if not os.path.exists(ruta):
        return out
    with open(ruta, encoding="utf-8-sig") as fp:
        filas = [r for r in csv.DictReader(fp) if r.get("liga") == "lmp"]
    filas.sort(key=lambda r: r.get("registrado", ""))
    for r in filas:
        k = (r["fecha"], r["home"])
        m = r["mercado"]
        if m == "Ganador":
            p = _num(r["p_modelo"])
            if p is not None:
                out[k]["p_home"] = p if r["lado"] == "home" else 1 - p
        elif m.startswith("Carreras local"):
            out[k]["x_home"] = _num(r["valor_modelo"])
        elif m.startswith("Carreras visita"):
            out[k]["x_away"] = _num(r["valor_modelo"])
    return out


def completar_finales(C):
    """marcador final desde datos/beisbol.csv (fila del local) cuando la captura no lo trae."""
    ruta = next((p for p in (_r("datos", "beisbol.csv"), _r("trabajo", "datos", "datos", "beisbol.csv")) if os.path.exists(p)), None)
    if not ruta:
        return C
    fin = {}
    with open(ruta, encoding="utf-8-sig") as fp:
        for r in csv.DictReader(fp):
            if str(r.get("league", "")).lower() == "lmp" and str(r.get("is_home")) in ("1", "1.0", "True") and r.get("runs") not in ("", None):
                fin[(r["game_date"][:10], r["team"])] = (r["runs"], r["runs_opp"])
    for f in C:
        if _num(f["final_local"]) is None and (f["fecha_cdmx"], f["local"]) in fin:
            f["final_local"], f["final_visita"] = fin[(f["fecha_cdmx"], f["local"])]
    return C


def principal():
    C = prob_sin_vig(completar_finales(cargar_cuotas()))
    for f in C:
        f["gano"] = resultado(f)
        f["dec"] = dec(f["momio"])
    cal = [f for f in C if f["gano"] is not None]
    # una sola fila por (juego, mercado, lado, linea): preferir Novibet ultima captura > Bovada > resto
    def prioridad(f):
        return (f["fuente"] == "Novibet", f["captura"], f["casa"] == "Bovada")
    unico = {}
    for f in sorted(cal, key=prioridad):
        unico[(f["fecha_cdmx"], f["local"], f["mercado_tipo"], f["equipo_total"], f["lado"], f["linea"])] = f
    U = list(unico.values())
    out = {"fuente": "semillas/lmp_cuotas_2026.csv", "filas": len(C), "calificadas": len(U),
           "juegos": len({(f["fecha_cdmx"], f["local"]) for f in C}),
           "supuesto": "un solo lado publicado: p = implicita / 1.0225 (vig total 4.5 %)"}

    # 1. mercado contra resultado
    ml = [f for f in U if f["mercado_tipo"] == "ML"]
    fav = [f for f in ml if float(f["momio"]) < 0 and f["p"] > 0.5]
    out["ml_lado_publicado"] = resumen(ml)
    out["ml_favoritos"] = resumen(fav)
    out["ml_perros"] = resumen([f for f in ml if f["p"] < 0.5])
    out["ml_por_banda"] = {b: resumen([f for f in ml if banda(f["momio"]) == b])
                           for b in ["-200 o menos", "-160 a -199", "-130 a -159", "-101 a -129", "+100 o mas"]}
    out["ml_favorito_local"] = resumen([f for f in fav if f["lado"] == f["local"]])
    out["ml_favorito_visita"] = resumen([f for f in fav if f["lado"] == f["visita"]])
    tot = [f for f in U if f["mercado_tipo"] == "Total"]
    out["total_over"] = resumen([f for f in tot if f["lado"] == "O"])
    out["total_under"] = resumen([f for f in tot if f["lado"] == "U"])
    lineas = defaultdict(list)
    for f in tot:
        lineas[f["linea"]].append(f)
    out["total_por_linea"] = {}
    for lin, fs in sorted(lineas.items(), key=lambda x: float(x[0])):
        reales = [float(f["final_local"]) + float(f["final_visita"]) for f in fs]
        out["total_por_linea"][lin] = {"n": len(fs), "over_real_pct": round(100 * sum(r > float(lin) for r in reales) / len(fs), 1),
                                       "over": resumen([f for f in fs if f["lado"] == "O"]),
                                       "under": resumen([f for f in fs if f["lado"] == "U"])}
    tt = [f for f in U if f["mercado_tipo"] == "TT"]
    out["tt_over"] = resumen([f for f in tt if f["lado"] == "O"])
    out["tt_under"] = resumen([f for f in tt if f["lado"] == "U"])

    # 2 y 3. modelo contra mercado
    M = cargar_modelo()
    comp, sombra, desac = [], [], []
    tot_cmp = []
    por_juego = defaultdict(list)
    for f in U:
        por_juego[(f["fecha_cdmx"], f["local"])].append(f)
    for k, fs in por_juego.items():
        m = M.get(k)
        if not m:
            continue
        a, b = float(fs[0]["final_local"]), float(fs[0]["final_visita"])
        y = 1 if a > b else 0
        mls = [f for f in fs if f["mercado_tipo"] == "ML"]
        if "p_home" in m and mls and a != b:
            f = mls[0]
            pm_home = f["p"] if f["lado"] == f["local"] else 1 - f["p"]
            ph = m["p_home"]
            comp.append({"bm": (ph - y) ** 2, "bk": (pm_home - y) ** 2, "ph": ph, "pk": pm_home, "y": y})
            if (ph - 0.5) * (pm_home - 0.5) < 0:
                desac.append(int((ph > 0.5) == (y == 1)))
            for f in mls:
                p_lado = ph if f["lado"] == f["local"] else 1 - ph
                ev = p_lado * f["dec"] - 1
                if ev >= EV_MIN:
                    sombra.append({"gano": f["gano"], "p": p_lado, "dec": f["dec"], "ev": ev})
        if m.get("x_home") is not None and m.get("x_away") is not None:
            tm = m["x_home"] + m["x_away"]
            for f in fs:
                if f["mercado_tipo"] == "Total":
                    lin = float(f["linea"])
                    tot_cmp.append({"modelo": tm, "linea": lin, "real": a + b,
                                    "lado_modelo_ok": int((tm > lin) == (a + b > lin)) if a + b != lin else None})
                    break
    if comp:
        n = len(comp)
        out["modelo_vs_mercado_ml"] = {
            "n": n, "brier_modelo": round(sum(c["bm"] for c in comp) / n, 4), "brier_mercado": round(sum(c["bk"] for c in comp) / n, 4),
            "acierto_modelo_pct": round(100 * sum((c["ph"] > 0.5) == (c["y"] == 1) for c in comp) / n, 1),
            "acierto_mercado_pct": round(100 * sum((c["pk"] > 0.5) == (c["y"] == 1) for c in comp) / n, 1),
            "desacuerdos": len(desac), "desacuerdos_gana_modelo": sum(desac),
            "brecha_media_pp": round(100 * sum(abs(c["ph"] - c["pk"]) for c in comp) / n, 1)}
    out["sombra_modelo_ev4"] = resumen(sombra)
    if tot_cmp:
        n = len(tot_cmp)
        ok = [t["lado_modelo_ok"] for t in tot_cmp if t["lado_modelo_ok"] is not None]
        out["total_modelo_vs_linea"] = {
            "n": n, "media_modelo": round(sum(t["modelo"] for t in tot_cmp) / n, 2),
            "media_linea": round(sum(t["linea"] for t in tot_cmp) / n, 2), "media_real": round(sum(t["real"] for t in tot_cmp) / n, 2),
            "mae_modelo": round(sum(abs(t["modelo"] - t["real"]) for t in tot_cmp) / n, 2),
            "mae_linea": round(sum(abs(t["linea"] - t["real"]) for t in tot_cmp) / n, 2),
            "lado_modelo_acierto_pct": round(100 * sum(ok) / len(ok), 1) if ok else None, "n_lado": len(ok)}

    # 4. movimiento entre capturas de Novibet
    mov = []
    nov = defaultdict(dict)
    for f in C:
        if f["fuente"] == "Novibet" and f["mercado_tipo"] == "ML":
            nov[(f["fecha_cdmx"], f["local"], f["lado"])][f["captura"]] = f
    for (fe, lo, lado), caps in nov.items():
        if len(caps) >= 2:
            ks = sorted(caps)
            p0, p1 = caps[ks[0]]["p"], caps[ks[-1]]["p"]
            mov.append({"fecha": fe, "local": lo, "lado": lado, "de": caps[ks[0]]["momio"], "a": caps[ks[-1]]["momio"],
                        "mov_pp": round(100 * (p1 - p0), 1), "gano": caps[ks[-1]]["gano"]})
    out["novibet_movimiento"] = mov

    os.makedirs(_r("salida"), exist_ok=True)
    with open(_r("salida", "cuotas_lmp_analisis.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    principal()
