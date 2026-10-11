# -*- coding: utf-8 -*-
"""
utilidades/minar_cuotas_chidas.py - que tienen las cuotas de 1.80 a 4.50 que pegan (trabajo/minar/2026-10-11_cuotas_chidas.md).

Universo: cada lado con cuota 1.80-4.50 al mejor cierre. 70 % mas viejo de cada deporte: ROI por rangos de cada factor
(explorar). 30 % final: solo las reglas registradas R0-R5, una vez.

    python utilidades/minar_cuotas_chidas.py
Escribe trabajo/minar/2026-10-11_cuotas_chidas_resultados.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json, math, os, pickle, sys
from collections import defaultdict

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, "utilidades"))
import metamodelo as MT  # noqa: E402
import minar_ganador_cuota_espn as GE  # noqa: E402

CMIN, CMAX = 1.80, 4.50
SALIDA = os.path.join(CODIGO, "trabajo", "minar", "2026-10-11_cuotas_chidas_resultados.json")


def lados_futbol():
    F = MT._filas("futbol", os.path.join(MT.BASE, "datos", "cache"))
    out = []
    for r in F:
        c = r.get("cu") or {}
        pc = MT._novig(c.get("PSCH"), c.get("PSCD"), c.get("PSCA"))
        po = MT._novig(c.get("PSH"), c.get("PSD"), c.get("PSA"))
        if not pc or not po:
            continue
        for lado, p, i, sg in (("H", r["p_h"], 0, 1), ("A", r["p_a"], 2, -1)):
            cu = c.get("MaxC" + lado) or c.get("Max" + lado)
            if not cu or p is None:
                continue
            y = int((r["gh"] > r["ga"]) if lado == "H" else (r["ga"] > r["gh"]))
            ang = sum(sg * (r.get(a) or 0) for a in ("F1", "F13", "S1", "S4", "S7"))
            out.append(dict(dep="FUTBOL", fecha=str(r["fecha"])[:10], local=lado == "H", p=p, cuota=cu, y=y,
                            pmk=pc[i], mov=100 * (pc[i] - po[i]), ang=ang))
    return out


def lados_espn():
    U = pickle.load(open(os.path.join(CODIGO, "trabajo", "minar", "tanda7_cache.pkl"), "rb"))
    CU = GE.cuotas_por_juego()
    dec = MT._dec_ml
    out = []
    for liga, dep in GE.LIGAS:
        if dep == "MLB":
            filas = [dict(r, home=r["home"][1] if isinstance(r["home"], tuple) else r["home"],
                          away=r["away"][1] if isinstance(r["away"], tuple) else r["away"]) for r in U["BEISBOL"][0] if r.get("liga") == "MLB"]
        else:
            filas = U[dep][0]
        loc = GE.mapa_ids(liga, filas)
        for r in filas:
            f = str(r["fecha"])[:10]
            gid = loc.get((f, r["home"], r.get("away"))) or loc.get((f, r["home"], None))
            rows = CU.get((liga, gid)) if gid else None
            if not rows:
                continue
            best, nc, no = [0, 0], [], []
            for x in rows:
                h, a = dec(x.get("ml_home_close") or x.get("ml_home")), dec(x.get("ml_away_close") or x.get("ml_away"))
                ho, ao = dec(x.get("ml_home_open")), dec(x.get("ml_away_open"))
                if h and a and 1 / h + 1 / a >= 1.0:
                    nc.append(MT._novig(h, a)[0]); best = [max(best[0], h), max(best[1], a)]
                if ho and ao and 1 / ho + 1 / ao >= 1.0:
                    no.append(MT._novig(ho, ao)[0])
            if not nc or not no or not best[0]:
                continue
            pc, po = sum(nc) / len(nc), sum(no) / len(no)
            yh = int(r["y"] == 1)
            for lado, p, cu, y, pm, mv in (("home", r["p"], best[0], yh, pc, pc - po), ("away", 1 - r["p"], best[1], 1 - yh, 1 - pc, po - pc)):
                out.append(dict(dep=dep, fecha=f, local=lado == "home", p=p, cuota=cu, y=y, pmk=pm, mov=100 * mv, ang=None))
    return out


def resumen(L):
    if not L:
        return {"n": 0}
    L = sorted(L, key=lambda s: s["fecha"]); n = len(L)
    u = [(s["cuota"] - 1) if s["y"] else -1.0 for s in L]
    m = sum(u) / n; sd = (sum((x - m) ** 2 for x in u) / max(n - 1, 1)) ** 0.5; h = n // 2
    return {"n": n, "acierto": round(100 * sum(s["y"] for s in L) / n, 1), "equilibrio": round(100 * sum(1 / s["cuota"] for s in L) / n, 1),
            "cuota": round(sum(s["cuota"] for s in L) / n, 2), "u": round(sum(u), 1), "roi": round(100 * m, 2),
            "z": round(m / sd * n ** 0.5, 2) if sd > 0 else None, "mitades": [round(sum(u[:h]), 1), round(sum(u[h:]), 1)]}


def linea(nombre, r):
    if not r.get("n"):
        return "  %-46s n     0" % nombre
    return "  %-46s n %5d  acierto %5.1f%% (eq %5.1f%%)  cuota %.2f  u %+7.1f  ROI %+6.2f%%  z %5s  mitades %s" % (
        nombre, r["n"], r["acierto"], r["equilibrio"], r["cuota"], r["u"], r["roi"], r["z"], r["mitades"])


RANGOS = {
    "p del modelo": [(0, .35), (.35, .42), (.42, .50), (.50, .58), (.58, 1.01)],
    "modelo - mercado (pp)": [(-99, -5), (-5, 0), (0, 5), (5, 10), (10, 99)],
    "movimiento hacia el lado (pp)": [(-99, -3), (-3, -1), (-1, 1), (1, 3), (3, 99)],
    "cuota": [(1.80, 2.10), (2.10, 2.60), (2.60, 3.20), (3.20, 4.51)],
}


def valor(s, k):
    return {"p del modelo": s["p"], "modelo - mercado (pp)": 100 * (s["p"] - s["pmk"]),
            "movimiento hacia el lado (pp)": s["mov"], "cuota": s["cuota"]}[k]


REGLAS = {
    "R0 todos 1.80-4.50 (control)": lambda s: True,
    "R1 modelo >= 50% y paga 1.80-4.50": lambda s: s["p"] >= 0.50,
    "R2 = R1 y mercado hacia el lado >= +1 pp": lambda s: s["p"] >= 0.50 and s["mov"] >= 1,
    "R3 = R1 y mercado sin moverse en contra": lambda s: s["p"] >= 0.50 and s["mov"] >= 0,
    "R4 perro 2.20-4.50, modelo >= 42%, mov >= +1": lambda s: s["cuota"] >= 2.20 and s["p"] >= 0.42 and s["mov"] >= 1,
    "R5 = R1 y angulos netos a favor >= 1": lambda s: s["p"] >= 0.50 and (s["ang"] or 0) >= 1,
}


def main():
    todos = [s for s in lados_futbol() + lados_espn() if CMIN <= s["cuota"] <= CMAX]
    por = defaultdict(list)
    for s in todos:
        por[s["dep"]].append(s)
    ent, pru = defaultdict(list), defaultdict(list)
    for d, L in por.items():
        L.sort(key=lambda s: s["fecha"]); c = int(len(L) * 0.7)
        ent[d], pru[d] = L[:c], L[c:]
    res = {"explorar": {}, "probar": {}}
    print("EXPLORAR (70 %% mas viejo de cada deporte; lados con cuota %.2f-%.2f al mejor cierre)" % (CMIN, CMAX))
    for d in sorted(ent) + ["JUNTO"]:
        L = sum(ent.values(), []) if d == "JUNTO" else ent[d]
        print("\n%s: %d lados" % (d, len(L)))
        res["explorar"][d] = {}
        for k, rr in RANGOS.items():
            for a, b in rr:
                r = resumen([s for s in L if a <= valor(s, k) < b])
                res["explorar"][d]["%s [%s, %s)" % (k, a, b)] = r
                print(linea("%s [%s, %s)" % (k, a, b), r))
        for nm, f in (("local", lambda s: s["local"]), ("visita", lambda s: not s["local"])):
            r = resumen([s for s in L if f(s)]); res["explorar"][d][nm] = r; print(linea(nm, r))
    print("\n\nPROBAR (30 %% final, reglas registradas)")
    for d in sorted(pru) + ["JUNTO"]:
        L = sum(pru.values(), []) if d == "JUNTO" else pru[d]
        print("\n%s: %d lados (%s a %s)" % (d, len(L), min(s["fecha"] for s in L), max(s["fecha"] for s in L)))
        res["probar"][d] = {}
        for nm, f in REGLAS.items():
            r = resumen([s for s in L if f(s)])
            r["veredicto"] = "pasa" if (r.get("n", 0) >= 300 and (r.get("z") or 0) >= 2 and r.get("roi", 0) > 0 and min(r.get("mitades") or [0]) > 0) else (
                "muestra corta" if r.get("n", 0) < 300 else "no pasa")
            res["probar"][d][nm] = r
            print(linea(nm, r) + "  " + r["veredicto"])
    json.dump(res, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nescrito", SALIDA)


if __name__ == "__main__":
    main()
