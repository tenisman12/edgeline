# -*- coding: utf-8 -*-
"""
utilidades/clv.py - CLV: le ganamos o no a la linea de cierre de Pinnacle (la unica prueba de ventaja real contra las casas).

Para cada pick (lista oficial, VALOR, sistema de beisbol) y para cada prediccion del modelo busca en
salida/cuotas_sharp_<ano>.csv la ultima foto de Pinnacle ANTES del inicio del partido (el cierre) y la foto vigente
cuando se registro el pick, en el mismo mercado, lado y linea. Calcula:

  - clv_ev_pct  = p_cierre_sin_vig * cuota_tomada_decimal - 1      (EV medido contra el cierre; > 0 = le ganaste)
  - clv_precio_pct = cuota_tomada / cuota_cierre_pinnacle - 1       (diferencia de precio con margen)
  - mov_pp      = (p_cierre - p_al_registrar) en el lado del pick, en puntos porcentuales (> 0 = la linea se movio a favor)

Para TODAS las predicciones del modelo mide si el mercado se mueve hacia el modelo:
  hacia_modelo = signo(p_modelo - p_al_registrar) * (p_cierre - p_al_registrar). Si el modelo trae informacion que el
  mercado no tenia, el promedio es > 0. Se da n, media, z y por mitades, con el mismo protocolo que la validacion
  (n >= 300, z >= 2.0, las dos mitades). Mientras no lo cumpla dice SIN DEMOSTRAR.

Escribe salida/clv.json (resumen) y salida/clv_detalle.csv (fila por pick/prediccion). Corre en cada actualizacion.

    cd C:\\Edgeline_repo
    python utilidades\\clv.py            (calcula y muestra el resumen)
"""
import csv, glob, json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, sharp

MK = {"h2h": "Ganador", "totals": "Total", "spreads": "Spread"}


def _dec(a):
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if 1.0 < a < 50 and abs(a) < 50:          # ya es decimal
        return a
    return 1 + a / 100.0 if a > 0 else 1 + 100.0 / abs(a)


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def _k(nombre):
    return " ".join(sorted(sharp._norm(nombre)))


def _ts(s):
    s = (s or "").strip().replace("Z", "")
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s[:19])
    except ValueError:
        return None


def cargar_fotos():
    """(liga, home, away, mercado, lado, linea) -> lista ordenada de fotos (ts, p_sharp, ref_cuota, fuente, inicio)."""
    out = {}
    for ruta in sorted(glob.glob(io.ruta("salida", "cuotas_sharp_*.csv"))):
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                lg = sharp.liga_de(r.get("sport") or "")
                ts, ini = _ts(r.get("ts_utc")), _ts(r.get("commence_time"))
                p = _f(r.get("p_sharp"))
                if not lg or ts is None or ini is None or p is None or ts > ini:
                    continue
                mk = MK.get(r.get("mercado"), r.get("mercado"))
                lin = _f(r.get("linea"))
                k = (lg, _k(r.get("home")), _k(r.get("away")), mk, r.get("lado"), None if mk == "Ganador" else lin)
                out.setdefault(k, []).append((ts, p, _f(r.get("ref_cuota")), r.get("fuente"), ini))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def _clave(liga, home, away, mercado, lado, linea=None):
    m = (mercado or "").split()
    mk = m[0] if m else ""
    if mk == "Total" and linea is None and len(m) > 1:
        linea = _f(m[1])
    if mk == "Spread" and linea is None and len(m) > 1:
        linea = _f(m[1])
        if linea is not None and lado == "away":
            linea = -linea if linea else linea
    return (liga, _k(home), _k(away), mk, lado, None if mk == "Ganador" else linea)


def medir(fotos, liga, home, away, mercado, lado, registrado, cuota=None, linea=None):
    k = _clave(liga, home, away, mercado, lado, linea)
    serie = fotos.get(k)
    if not serie:
        return None
    reg = _ts(registrado)
    cierre = serie[-1]
    antes = [x for x in serie if reg and x[0] <= reg]
    al_reg = antes[-1] if antes else serie[0]
    if reg and reg > cierre[4]:
        return None                                  # registrado despues del inicio: no cuenta
    d = {"p_registro": round(al_reg[1], 4), "p_cierre": round(cierre[1], 4), "mov_pp": round(100 * (cierre[1] - al_reg[1]), 2),
         "cuota_cierre": cierre[2], "fuente_cierre": cierre[3], "fotos": len(serie)}
    dt_ = _dec(cuota)
    if dt_:
        d["clv_ev_pct"] = round(100 * (cierre[1] * dt_ - 1), 2)
        dc = _dec(cierre[2])
        if dc:
            d["clv_precio_pct"] = round(100 * (dt_ / dc - 1), 2)
    return d


def _leer(nombre):
    ruta = io.ruta("salida", nombre)
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _stats(xs):
    n = len(xs)
    if not n:
        return {"n": 0}
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    z = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "media": round(m, 3), "z": round(z, 2), "positivos_pct": round(100.0 * sum(1 for x in xs if x > 0) / n, 1)}


def _protocolo(filas, campo):
    xs = [r[campo] for r in filas if r.get(campo) is not None]
    st = _stats(xs)
    if st["n"] >= 2:
        h = st["n"] // 2
        a, b = _stats(xs[:h]), _stats(xs[h:])
        st["mitades"] = [a.get("media"), b.get("media")]
        ok = st["n"] >= 300 and st["z"] >= 2.0 and (a.get("media") or 0) > 0 and (b.get("media") or 0) > 0
        st["veredicto"] = "DEMOSTRADO" if ok else "SIN DEMOSTRAR"
    return st


def main():
    fotos = cargar_fotos()
    det = []
    listas = [("oficial", "historial_picks_dia_calificado.csv", "historial_picks_dia.csv", "cuota"),
              ("valor", "historial_calificado.csv", "historial_picks.csv", "valor_cuota"),
              ("beisbol", "historial_decidir_calificado.csv", "historial_decidir.csv", "cuota")]
    for nombre, cal, base, ccuota in listas:
        filas = _leer(cal) or _leer(base)
        for r in filas:
            mercado = r.get("mercado") or r.get("valor_mercado") or "Ganador"
            lado = r.get("lado") or r.get("valor_lado")
            cuota = r.get(ccuota) or r.get("cuota")
            if not lado or not cuota:
                continue
            m = medir(fotos, r.get("liga"), r.get("home"), r.get("away"), mercado, lado, r.get("registrado"), cuota)
            if not m:
                continue
            m.update({"lista": nombre, "registrado": r.get("registrado"), "liga": r.get("liga"), "fecha": r.get("fecha"),
                      "home": r.get("home"), "away": r.get("away"), "mercado": mercado, "lado": lado, "cuota": cuota,
                      "resultado": r.get("resultado") or r.get("valor_resultado") or ""})
            det.append(m)
    # todas las predicciones del modelo: se mueve el mercado hacia el modelo?
    preds = []
    for r in _leer("historial_predicciones_calificado.csv") or _leer("historial_predicciones.csv"):
        pm = _f(r.get("p_modelo"))
        if pm is None:
            continue
        m = medir(fotos, r.get("liga"), r.get("home"), r.get("away"), r.get("mercado"), r.get("lado"), r.get("registrado"),
                  r.get("cuota"), _f(r.get("linea")))
        if not m:
            continue
        signo = 1 if pm > m["p_registro"] else -1 if pm < m["p_registro"] else 0
        if signo == 0:
            continue
        m.update({"lista": "modelo", "registrado": r.get("registrado"), "liga": r.get("liga"), "fecha": r.get("fecha"),
                  "home": r.get("home"), "away": r.get("away"), "mercado": r.get("mercado"), "lado": r.get("lado"),
                  "p_modelo": pm, "hacia_modelo_pp": round(signo * m["mov_pp"], 2)})
        preds.append(m)
    # una prediccion por partido y mercado (la primera registrada) para no contar dos veces el mismo movimiento
    vistos, unicas = set(), []
    for m in sorted(preds, key=lambda x: x["registrado"] or ""):
        k = (m["liga"], m["home"], m["away"], (m["mercado"] or "").split()[0], m["fecha"])
        if k in vistos:
            continue
        vistos.add(k); unicas.append(m)
    det.sort(key=lambda x: x["registrado"] or "")
    res = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "nota": "clv_ev_pct = EV contra la probabilidad sin vig de Pinnacle al cierre. hacia_modelo = cuanto se movio el cierre hacia el lado que marcaba el modelo.",
           "picks": {}, "modelo": {}}
    for nombre in ("oficial", "valor", "beisbol"):
        fs = [x for x in det if x["lista"] == nombre]
        bl = {"total": _protocolo(fs, "clv_ev_pct"), "mov_pp": _stats([x["mov_pp"] for x in fs]), "por_liga": {}}
        for lg in sorted({x["liga"] for x in fs}):
            bl["por_liga"][lg] = _protocolo([x for x in fs if x["liga"] == lg], "clv_ev_pct")
        res["picks"][nombre] = bl
    res["modelo"]["total"] = _protocolo(unicas, "hacia_modelo_pp")
    for lg in sorted({x["liga"] for x in unicas}):
        res["modelo"].setdefault("por_liga", {})[lg] = _protocolo([x for x in unicas if x["liga"] == lg], "hacia_modelo_pp")
    for mk in ("Ganador", "Total", "Spread"):
        res["modelo"].setdefault("por_mercado", {})[mk] = _protocolo([x for x in unicas if (x["mercado"] or "").startswith(mk)], "hacia_modelo_pp")
    with open(io.ruta("salida", "clv.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    cols = ["lista", "registrado", "liga", "fecha", "home", "away", "mercado", "lado", "cuota", "p_modelo", "p_registro", "p_cierre",
            "mov_pp", "hacia_modelo_pp", "cuota_cierre", "fuente_cierre", "clv_ev_pct", "clv_precio_pct", "fotos", "resultado"]
    with open(io.ruta("salida", "clv_detalle.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(det + unicas)
    print("CLV contra el cierre de Pinnacle")
    for nombre, bl in res["picks"].items():
        t = bl["total"]
        if t.get("n"):
            print("  %-8s n=%-4d CLV medio %+.2f%%  positivos %.0f%%  z %.2f  -> %s" % (nombre, t["n"], t["media"], t["positivos_pct"], t["z"], t.get("veredicto", "")))
        else:
            print("  %-8s sin picks con cierre todavia" % nombre)
    t = res["modelo"]["total"]
    if t.get("n"):
        print("  modelo   n=%-4d el cierre se movio %+.2f pp hacia el modelo  z %.2f  -> %s" % (t["n"], t["media"], t["z"], t.get("veredicto", "")))
        for lg, s in (res["modelo"].get("por_liga") or {}).items():
            print("     %-8s n=%-4d %+.2f pp  z %.2f" % (lg, s["n"], s["media"], s["z"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
