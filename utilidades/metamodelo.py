# -*- coding: utf-8 -*-
"""
utilidades/metamodelo.py - evalua el metamodelo apilado (nucleo/metamodelo.py) walk-forward.

Capas, en el orden de un tipster: mercado sharp (Pinnacle sin vig al decidir) -> desacuerdo del modelo -> angulos
situacionales -> publico/movimiento. Los pesos los pone el ajuste con datos anteriores; nada se fija a mano.

Datos con historia de precios (los unicos donde se puede medir de verdad):
  - Futbol 7 ligas, 1X2 y Over/Under 2.5: Pinnacle TEMPRANA (se decide ahi) y CIERRE (para el CLV), mejor precio del
    mercado y Bet365 (datos/mercado/futbol_cuotas.csv).
  - NFL ganador: moneyline de cierre (datos/mercado/nfl_lineas.csv). Sin temprana: se mide contra el cierre mismo.
  - 2026 en vivo, todos los deportes con publico (salida/historial_predicciones_calificado.csv + salida/publico_2026.csv):
    muestra corta, solo para ver hacia donde apunta el publico.

Metricas fuera de muestra:
  - log-loss por partido: mercado al decidir, modelo solo, metamodelo y (referencia) cierre de Pinnacle.
  - apuestas a 1 u: cuota >= 1.80, EV del metamodelo >= umbral, una por partido; acierto, unidades, ROI, CLV contra el
    cierre sin vig, por mitades. Comparado con apostar por el EV del modelo solo.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    git pull
    python utilidades/metamodelo.py                # futbol + nfl + vivo
    python utilidades/metamodelo.py --solo futbol

Escribe salida/metamodelo.json (resumen) y trabajo/minar/<fecha>_metamodelo_resultados.json (detalle).
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io as _io, json, math, os, pickle, sys
from collections import defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
from nucleo import io  # noqa: E402
from nucleo import metamodelo as MM  # noqa: E402

BASE = io.BASE
CUOTA_MIN = 1.80
UMBRALES = (0.02, 0.04, 0.06, 0.08)


def _n(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _novig(*c):
    if any((x is None or x <= 1.0) for x in c):
        return None
    s = sum(1 / x for x in c)
    return [(1 / x) / s for x in c]


def _dec_ml(ml):
    ml = _n(ml)
    if ml is None or ml == 0:
        return None
    return 1 + (ml / 100 if ml > 0 else 100 / -ml)


# ------------------------------------------------------------------ construccion de lados
ANG_FUT = ["F1", "F13", "S1", "S4", "S7"]
ANG_NFL = ["N4", "N8", "N12", "N13", "S1", "S4", "S7"]


def lados_futbol(filas):
    """1X2 y O/U 2.5. Decide con Pinnacle temprana; CLV contra el cierre de Pinnacle."""
    x12, ou = [], []
    for r in filas:
        c = r.get("cu") or {}
        y3 = "H" if r["gh"] > r["ga"] else ("D" if r["gh"] == r["ga"] else "A")
        pe = _novig(c.get("PSH"), c.get("PSD"), c.get("PSA"))
        pc = _novig(c.get("PSCH"), c.get("PSCD"), c.get("PSCA"))
        if pe and pc:
            for i, (lado, pm) in enumerate((("H", r["p_h"]), ("D", r["p_d"]), ("A", r["p_a"]))):
                sg = 1 if lado == "H" else (-1 if lado == "A" else 0)
                x12.append(dict(juego=r["gp"], fecha=r["fecha"], liga=r["liga"], lado=lado, y=int(y3 == lado),
                                p_mkt=pe[i], p_close=pc[i], p_mod=pm, es_empate=int(lado == "D"),
                                ang={a: sg * (r.get(a) or 0) for a in ANG_FUT},
                                cuota={"pinnacle": c.get("PS" + lado), "mejor": c.get("Max" + lado), "bet365": c.get("B365" + lado)}))
        oe = _novig(c.get("P_mas2.5"), c.get("P_menos2.5")); oc = _novig(c.get("PC_mas2.5"), c.get("PC_menos2.5"))
        if oe and oc and r.get("p_over") is not None:
            tot = r["gh"] + r["ga"]
            for i, (lado, pm, k) in enumerate((("over", r["p_over"], "mas2.5"), ("under", 1 - r["p_over"], "menos2.5"))):
                ou.append(dict(juego=r["gp"], fecha=r["fecha"], liga=r["liga"], lado=lado, y=int((tot > 2.5) == (lado == "over")),
                               p_mkt=oe[i], p_close=oc[i], p_mod=pm, ang={},
                               cuota={"pinnacle": c.get("P_" + k), "mejor": c.get("Max_" + k), "bet365": c.get("B365_" + k)}))
    return x12, ou


def lados_nfl(filas):
    out = []
    for r in filas:
        dh, da = _dec_ml(r.get("ml_h")), _dec_ml(r.get("ml_a"))
        p = _novig(dh, da)
        if not p or r.get("p") is None:
            continue
        for i, (lado, pm, cu) in enumerate((("home", r["p"], dh), ("away", 1 - r["p"], da))):
            sg = 1 if lado == "home" else -1
            out.append(dict(juego=str(r["gp"]), fecha=str(r["fecha"]), liga="NFL", lado=lado, y=int((r["y"] == 1) == (lado == "home")),
                            p_mkt=p[i], p_close=p[i], p_mod=pm, ang={a: sg * (r.get(a) or 0) for a in ANG_NFL},
                            cuota={"cierre": cu}))
    return out


# ------------------------------------------------------------------ metricas
def _ll_juegos(lados, clave):
    por = defaultdict(list)
    for s in lados:
        por[s["juego"]].append(s)
    ll = []
    for L in por.values():
        t = sum(s[clave] for s in L)
        if t <= 0:
            continue
        pv = [s[clave] / t for s in L if s["y"] == 1]
        if pv:
            ll.append(-math.log(max(pv[0], 1e-9)))
    return ll


def _z_pareado(a, b):
    d = [x - y for x, y in zip(a, b)]
    if len(d) < 30:
        return None, None
    m = sum(d) / len(d); sd = (sum((x - m) ** 2 for x in d) / (len(d) - 1)) ** 0.5
    return m, (m / sd * len(d) ** 0.5 if sd > 0 else None)


def comparar_ll(pred):
    por = defaultdict(list)
    for s in pred:
        por[s["juego"]].append(s)
    jj = [L for L in por.values() if all(s.get("q") is not None for s in L)]
    flat = [s for L in jj for s in L]
    out = {"partidos": len(jj)}
    base = _ll_juegos(flat, "p_mkt")
    for nombre, clave in (("mercado_al_decidir", "p_mkt"), ("modelo_solo", "p_mod"), ("metamodelo", "q"), ("cierre_pinnacle", "p_close")):
        v = _ll_juegos(flat, clave)
        m, z = _z_pareado(base, v)
        out[nombre] = {"logloss": round(sum(v) / len(v), 5), "mejora_vs_mercado_milesimas": round(1000 * m, 2) if m is not None else None,
                       "z": round(z, 2) if z is not None else None}
    # mitades del metamodelo contra el mercado
    jj.sort(key=lambda L: L[0]["fecha"]); h = len(jj) // 2
    mit = []
    for part in (jj[:h], jj[h:]):
        fl = [s for L in part for s in L]
        a, b = _ll_juegos(fl, "p_mkt"), _ll_juegos(fl, "q")
        mit.append(round(1000 * (sum(a) - sum(b)) / max(len(a), 1), 2))
    out["metamodelo"]["mitades_milesimas"] = mit
    return out


def apostar(pred, clave_p, fuente, umbral, cuota_min=CUOTA_MIN):
    """Una apuesta por partido: el lado con mayor EV que cumpla cuota >= cuota_min y EV >= umbral."""
    por = defaultdict(list)
    for s in pred:
        por[s["juego"]].append(s)
    ap = []
    for L in por.values():
        mejor = None
        for s in L:
            c = (s.get("cuota") or {}).get(fuente); p = s.get(clave_p)
            if c is None or p is None or c < cuota_min:
                continue
            ev = p * c - 1
            if ev >= umbral and (mejor is None or ev > mejor[0]):
                mejor = (ev, s, c)
        if mejor:
            ev, s, c = mejor
            ap.append(dict(fecha=s["fecha"], liga=s.get("liga"), lado=s["lado"], cuota=c, ev=ev, gano=s["y"],
                           u=(c - 1) if s["y"] else -1.0, clv=c * s["p_close"] - 1))
    return ap


def resumen_apuestas(ap):
    if not ap:
        return {"n": 0}
    ap = sorted(ap, key=lambda a: a["fecha"]); n = len(ap); u = [a["u"] for a in ap]
    m = sum(u) / n; sd = (sum((x - m) ** 2 for x in u) / max(n - 1, 1)) ** 0.5
    cl = [a["clv"] for a in ap]; mc = sum(cl) / n; sdc = (sum((x - mc) ** 2 for x in cl) / max(n - 1, 1)) ** 0.5
    h = n // 2
    return {"n": n, "ganadas": sum(a["gano"] for a in ap), "acierto_pct": round(100 * sum(a["gano"] for a in ap) / n, 1),
            "cuota_media": round(sum(a["cuota"] for a in ap) / n, 2), "unidades": round(sum(u), 2), "roi_pct": round(100 * m, 2),
            "z_roi": round(m / sd * n ** 0.5, 2) if sd > 0 else None,
            "clv_pct": round(100 * mc, 2), "z_clv": round(mc / sdc * n ** 0.5, 2) if sdc > 0 else None,
            "mitades_unidades": [round(sum(u[:h]), 2), round(sum(u[h:]), 2)]}


def capas(nombre, lados, variantes, fuentes, min_entreno, dias_bloque):
    """Lo que aporta cada capa: se agrega una por una y se mide el log-loss y las apuestas fuera de muestra."""
    out = {}
    print("\n  APORTE POR CAPA (%s)" % nombre)
    for etiqueta, fac in variantes:
        L = [dict(s) for s in lados]
        pred, _ = MM.walk_forward(L, fac, dias_bloque=dias_bloque, min_entreno=min_entreno)
        ll = comparar_ll(pred)
        o = {"ll_vs_mercado_milesimas": ll["metamodelo"]["mejora_vs_mercado_milesimas"], "z": ll["metamodelo"]["z"],
             "mitades": ll["metamodelo"]["mitades_milesimas"]}
        txt = []
        for f in fuentes:
            r = resumen_apuestas(apostar(pred, "q", f, 0.04))
            o["apuestas_%s_ev4" % f] = r
            if r["n"]:
                txt.append("%s: n %d u %+.1f ROI %+.1f%% CLV %+.2f%%" % (f, r["n"], r["unidades"], r["roi_pct"], r["clv_pct"]))
        out[etiqueta] = o
        print("    %-34s log-loss vs mercado %+6.2f milesimas (z %5s, mitades %s) | %s" % (etiqueta, o["ll_vs_mercado_milesimas"] or 0,
              o["z"], o["mitades"], " | ".join(txt)))
    return out


def evaluar(nombre, lados, factory, fuentes, min_entreno, dias_bloque=30, variantes=None):
    pred, hist = MM.walk_forward([dict(s) for s in lados], factory, dias_bloque=dias_bloque, min_entreno=min_entreno)
    if not pred:
        print("  %s: sin prediccion (poca historia)" % nombre); return None
    out = {"mercado": nombre, "desde": pred[0]["fecha"][:10], "hasta": pred[-1]["fecha"][:10], "ll": comparar_ll(pred),
           "coeficientes_ultimo": hist[-1][1], "apuestas": {}}
    print("\n" + "=" * 100)
    print("%s  | prueba fuera de muestra %s -> %s | %d partidos" % (nombre, out["desde"], out["hasta"], out["ll"]["partidos"]))
    for k in ("mercado_al_decidir", "modelo_solo", "metamodelo", "cierre_pinnacle"):
        v = out["ll"][k]
        print("  log-loss %-20s %.5f   vs mercado %+7s milesimas  z %s" % (k, v["logloss"], v["mejora_vs_mercado_milesimas"], v["z"]))
    print("  metamodelo por mitades (milesimas vs mercado):", out["ll"]["metamodelo"]["mitades_milesimas"])
    print("  pesos (ultimo ajuste):", out["coeficientes_ultimo"])
    for f in fuentes:
        for clave, etiqueta in (("q", "metamodelo"), ("p_mkt", "mercado_solo"), ("p_mod", "modelo_solo")):
            for u in UMBRALES:
                r = resumen_apuestas(apostar(pred, clave, f, u))
                out["apuestas"]["%s|%s|ev%d" % (etiqueta, f, round(u * 100))] = r
                if r["n"]:
                    print("  %-11s cuota %-8s EV>=%2d%%  n %5d  acierto %5.1f%%  cuota %.2f  u %+8.2f  ROI %+6.2f%% (z %5s)  CLV %+6.2f%% (z %5s)  mitades %s"
                          % (etiqueta, f, round(u * 100), r["n"], r["acierto_pct"], r["cuota_media"], r["unidades"], r["roi_pct"],
                             r["z_roi"], r["clv_pct"], r["z_clv"], r["mitades_unidades"]))
    if variantes:
        out["capas"] = capas(nombre, lados, variantes, fuentes, min_entreno, dias_bloque)
    return out


# ------------------------------------------------------------------ 2026 en vivo (publico)
def vivo():
    """Ganador 2026: modelo vs Pinnacle al registrar + publico de Action Network. Muestra corta: descriptivo."""
    rp = os.path.join(CODIGO, "salida", "historial_predicciones_calificado.csv")
    ru = os.path.join(CODIGO, "salida", "publico_2026.csv")
    if not (os.path.exists(rp) and os.path.exists(ru)):
        return None
    pub = {}
    for x in csv.DictReader(_io.open(ru, encoding="utf-8-sig")):
        t, m = _n(x.get("ml_tickets_home")), _n(x.get("ml_money_home"))
        if t is None or t in (0, 100):
            continue
        pub[(x["liga"], x["id"])] = (t / 100, (m / 100) if m not in (None, 0, 100) else None)   # la ultima foto gana
    lados = []
    for r in csv.DictReader(_io.open(rp, encoding="utf-8-sig")):
        if r["mercado"] != "Ganador" or r["estado"] != "calificado":
            continue
        pm, pk, c = _n(r["p_modelo"]), _n(r["p_mercado"]), _n(r["cuota"])
        if pm is None or pk is None or not (0.02 < pk < 0.98):
            continue
        u = pub.get((r["liga"], r["id"]))
        if not u:
            continue
        t_home, m_home = u
        es_home = r["lado"] == "home"
        t = t_home if es_home else 1 - t_home
        mm = (m_home if es_home else 1 - m_home) if m_home is not None else t
        lados.append(dict(juego=r["liga"] + r["id"], fecha=r["fecha"], liga=r["liga"], lado=r["lado"], y=int(r["acierto"] == "1"),
                          p_mkt=pk, p_mod=pm, p_close=pk, pub={"boletos": t - 0.5, "dinero_menos_boletos": mm - t},
                          cuota={"registro": _dec_ml(c)}))
    if len(lados) < 40:
        return {"n": len(lados), "nota": "muestra muy corta"}
    lados.sort(key=lambda s: s["fecha"])
    # descriptivo: el lado del publico (boletos > 55 %) contra el mercado
    out = {"n": len(lados), "ligas": sorted({s["liga"] for s in lados})}
    for nombre, f in (("publico_cargado_>=60%", lambda s: s["pub"]["boletos"] >= 0.10),
                      ("contra_publico_<=40%", lambda s: s["pub"]["boletos"] <= -0.10),
                      ("dinero_>_boletos_+10pp", lambda s: s["pub"]["dinero_menos_boletos"] >= 0.10)):
        L = [s for s in lados if f(s)]
        if L:
            out[nombre] = {"n": len(L), "real_pct": round(100 * sum(s["y"] for s in L) / len(L), 1),
                           "mercado_pct": round(100 * sum(s["p_mkt"] for s in L) / len(L), 1),
                           "modelo_pct": round(100 * sum(s["p_mod"] for s in L) / len(L), 1)}
    mm = MM.Metamodelo(publico=["boletos", "dinero_menos_boletos"]).ajustar(lados)
    out["pesos_toda_la_muestra"] = mm.coef()
    print("\n" + "=" * 100)
    print("2026 EN VIVO con publico (ganador; %d lados de %s) - descriptivo" % (len(lados), ", ".join(out["ligas"])))
    for k, v in out.items():
        if isinstance(v, dict):
            print("  %-26s %s" % (k, v))
    return out


# ------------------------------------------------------------------ main
def _filas(deporte, cache):
    ruta = os.path.join(cache, "metamodelo_%s.pkl" % deporte)
    if os.path.exists(ruta) and (dt.datetime.now().timestamp() - os.path.getmtime(ruta)) < 20 * 3600:
        return pickle.load(open(ruta, "rb"))
    import gen_filas_metamodelo as G
    F = G.futbol() if deporte == "futbol" else G.nfl()
    os.makedirs(cache, exist_ok=True); pickle.dump(F, open(ruta, "wb"))
    return F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="futbol,nfl,vivo")
    ap.add_argument("--l_ang", type=float, default=200.0)
    ap.add_argument("--cache", default=os.path.join(BASE, "datos", "cache"))
    a = ap.parse_args()
    res = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "cuota_min": CUOTA_MIN, "resultados": []}
    solo = {x.strip() for x in a.solo.split(",")}
    if "futbol" in solo:
        x12, ou = lados_futbol(_filas("futbol", a.cache))
        f12 = lambda: MM.Metamodelo(angulos=ANG_FUT, extras=["es_empate"], l_ang=a.l_ang)
        fou = lambda: MM.Metamodelo()
        v12 = [("1 mercado recalibrado", lambda: MM.Metamodelo(extras=["es_empate"], usar_modelo=False)),
               ("2 + modelo", lambda: MM.Metamodelo(extras=["es_empate"])),
               ("3 + angulos (completo)", f12)]
        vou = [("1 mercado recalibrado", lambda: MM.Metamodelo(usar_modelo=False)), ("2 + modelo (completo)", fou)]
        res["resultados"].append(evaluar("Futbol 1X2 (7 ligas)", x12, f12, ("pinnacle", "mejor", "bet365"), min_entreno=2000, variantes=v12))
        res["resultados"].append(evaluar("Futbol Over/Under 2.5", ou, fou, ("pinnacle", "mejor", "bet365"), min_entreno=2000, variantes=vou))
    if "nfl" in solo:
        L = lados_nfl(_filas("nfl", a.cache))
        fn = lambda: MM.Metamodelo(angulos=ANG_NFL, l_ang=a.l_ang)
        vn = [("1 mercado recalibrado", lambda: MM.Metamodelo(usar_modelo=False)), ("2 + modelo", lambda: MM.Metamodelo()),
              ("3 + angulos (completo)", fn)]
        res["resultados"].append(evaluar("NFL ganador (contra el cierre)", L, fn, ("cierre",), min_entreno=500, dias_bloque=60, variantes=vn))
    if "vivo" in solo:
        res["vivo_2026"] = vivo()
    res["resultados"] = [r for r in res["resultados"] if r]
    os.makedirs(os.path.join(CODIGO, "salida"), exist_ok=True)
    json.dump(res, _io.open(os.path.join(CODIGO, "salida", "metamodelo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresumen en salida/metamodelo.json")


if __name__ == "__main__":
    main()
