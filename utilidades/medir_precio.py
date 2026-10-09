# -*- coding: utf-8 -*-
"""
utilidades/medir_precio.py - donde y cuando esta el mejor precio, y si apostar cuando una casa paga mas que el precio
justo de Pinnacle deja ganancia.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_precio.md
Precio justo = probabilidad sin vig del cierre de Pinnacle. CLV = cuota tomada x p justa - 1.
No cambia modelos ni picks.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/medir_precio.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, datetime as dt, glob, io as _io, json, math, os, sys
from collections import Counter, defaultdict
import numpy as np

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO)
from nucleo import io  # noqa: E402

BASE = io.BASE
LO, HI = 1.80, 3.00
CASAS = [("PS", "Pinnacle"), ("B365", "Bet365"), ("BW", "Bwin"), ("IW", "Interwetten"), ("WH", "William Hill"),
         ("VC", "VC Bet"), ("Avg", "promedio"), ("Max", "maximo")]
RNG = np.random.default_rng(11)


def _n(x):
    try:
        v = float(x); return v if v == v and v > 1.0 else None
    except (TypeError, ValueError):
        return None


def _novig(*o):
    if not all(o): return None
    s = sum(1 / v for v in o); return [(1 / v) / s for v in o]


def _col(casa, cierre, lado):
    """nombre de columna football-data. lado: H D A O U."""
    c = casa + ("C" if cierre else "")
    if lado in "HDA": return "fd_%s%s" % (c, lado)
    pre = {"PS": "P"}.get(casa, casa) + ("C" if cierre else "")
    return "fd_%s_%s2.5" % (pre, "mas" if lado == "O" else "menos")


def cargar_futbol():
    goles = {}
    with _io.open(os.path.join(BASE, "datos", "futbol.csv"), encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            if str(x.get("is_home")) in ("1", "1.0", "True"):
                try: goles[str(x["gamePk"])] = (float(x["goals"]), float(x["goals_opp"]))
                except (TypeError, ValueError): pass
    lados = []
    with _io.open(os.path.join(BASE, "datos", "mercado", "futbol_cuotas.csv"), encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            g = goles.get(str(x["gamePk"]))
            if g is None:
                try: g = (float(x["fd_FTHG"]), float(x["fd_FTAG"]))
                except (TypeError, ValueError, KeyError): continue
            gh, ga = g
            gana = {"H": gh > ga, "D": gh == ga, "A": gh < ga, "O": gh + ga > 2.5, "U": gh + ga < 2.5}
            for mercado, L in (("1X2", "HDA"), ("OU", "OU")):
                jc = _novig(*[_n(x.get(_col("PS", True, l))) for l in L])
                if not jc: continue
                je = _novig(*[_n(x.get(_col("PS", False, l))) for l in L])
                for i, l in enumerate(L):
                    pr = {}
                    for c, _ in CASAS:
                        pr[(c, 0)] = _n(x.get(_col(c, False, l))); pr[(c, 1)] = _n(x.get(_col(c, True, l)))
                    lados.append(dict(fecha=x["game_date"][:10], liga=x["league"], mercado=mercado, lado=l, gana=gana[l],
                                      pj=jc[i], pje=je[i] if je else None, fav=(jc[i] == max(jc)), pr=pr))
    lados.sort(key=lambda a: a["fecha"])
    return lados


def resumen(S, cuota):
    if not S: return None
    o = np.array([cuota(a) for a in S]); w = np.array([1.0 if a["gana"] else 0.0 for a in S])
    g = np.where(w > 0, o - 1, -1.0); clv = np.array([cuota(a) * a["pj"] - 1 for a in S]); n = len(S)
    z = clv.mean() / (clv.std(ddof=1) / math.sqrt(n)) if n > 1 and clv.std() > 0 else 0.0
    bayes = RNG.dirichlet(np.ones(n), 2000) @ g if n >= 2 else np.array([g.mean()])
    boot = np.array([g[RNG.integers(0, n, n)].mean() for _ in range(1000)]) if n >= 2 else np.array([g.mean()])
    return {"n": n, "cuota_media": round(float(o.mean()), 3), "acierto": round(100 * float(w.mean()), 1),
            "roi": round(100 * float(g.mean()), 2), "ic95_roi": [round(100 * float(np.percentile(boot, 2.5)), 1), round(100 * float(np.percentile(boot, 97.5)), 1)],
            "p_roi_pos": round(float((bayes > 0).mean()), 3), "clv": round(100 * float(clv.mean()), 2), "clv_z": round(float(z), 2),
            "clv_pos_pct": round(100 * float((clv > 0).mean()), 1)}


def descriptivo(L):
    out = {}
    print("\n1) FUTBOL HISTORICO: lados con cuota %.2f-%.2f; CLV contra el cierre sin vig de Pinnacle" % (LO, HI))
    print("   %-13s %-8s %6s %6s %7s %8s %7s %6s" % ("casa", "momento", "n", "cuota", "acierto", "ROI", "CLV", "CLV>0"))
    for c, nom in CASAS:
        for t, tn in ((0, "temprana"), (1, "cierre")):
            S = [a for a in L if a["pr"][(c, t)] and LO <= a["pr"][(c, t)] <= HI]
            r = resumen(S, lambda a, c=c, t=t: a["pr"][(c, t)])
            if not r or r["n"] < 300: continue
            out["%s_%s" % (nom, tn)] = r
            print("   %-13s %-8s %6d %6.2f %6.1f%% %+7.2f%% %+6.2f%% %5.1f%%" % (nom, tn, r["n"], r["cuota_media"], r["acierto"], r["roi"], r["clv"], r["clv_pos_pct"]))
    print("\n   Esperar o no (mismo lado, cuota temprana entre %.2f y %.2f): cambio de la cuota al cierre" % (LO, HI))
    esp = {}
    for c, nom in CASAS:
        for fav, fn in ((True, "favorito"), (False, "no favorito")):
            S = [a for a in L if a["fav"] == fav and a["pr"][(c, 0)] and a["pr"][(c, 1)] and LO <= a["pr"][(c, 0)] <= HI]
            if len(S) < 300: continue
            ch = np.array([a["pr"][(c, 1)] / a["pr"][(c, 0)] - 1 for a in S])
            esp["%s_%s" % (nom, fn)] = {"n": len(S), "cambio_medio_pct": round(100 * float(ch.mean()), 2),
                                        "sube_pct": round(100 * float((ch > 0).mean()), 1), "baja_pct": round(100 * float((ch < 0).mean()), 1)}
            print("   %-13s %-11s n %6d  cambio medio %+5.2f%%  sube %5.1f%%  baja %5.1f%%" % (nom, fn, len(S), 100 * ch.mean(), 100 * (ch > 0).mean(), 100 * (ch < 0).mean()))
    out["esperar"] = esp
    return out


def regla(L):
    print("\n2) REGLA: apostar si la cuota temprana >= (1 + m) / p sin vig de Pinnacle temprana; cuota %.2f-%.2f" % (LO, HI))
    E = [a for a in L if a["pje"]]
    fechas = sorted({a["fecha"] for a in E}); corte = fechas[int(len(fechas) * 0.7)]
    print("   lados con Pinnacle temprana y cierre: %d | prueba desde %s" % (len(E), corte))
    out = {"desde_prueba": corte}
    for c, nom in (("B365", "Bet365"), ("Max", "maximo")):
        sel = lambda a, m, c=c: a["pr"][(c, 0)] and LO <= a["pr"][(c, 0)] <= HI and a["pr"][(c, 0)] * a["pje"] >= 1 + m
        cu = lambda a, c=c: a["pr"][(c, 0)]
        exp = {}
        for m in (0.0, 0.02, 0.04, 0.06):
            exp[m] = resumen([a for a in E if a["fecha"] < corte and sel(a, m)], cu)
            r = exp[m]
            if r: print("   %-8s m %2.0f%%  70%%: n %6d  cuota %.2f  ROI %+6.2f%%  CLV %+5.2f%%" % (nom, 100 * m, r["n"], r["cuota_media"], r["roi"], r["clv"]))
        ok = {m: r for m, r in exp.items() if r and r["n"] >= 100}
        mb = max(ok, key=lambda m: ok[m]["roi"])
        te = resumen([a for a in E if a["fecha"] >= corte and sel(a, mb)], cu)
        ver = "pasa" if (te and te["n"] >= 300 and te["roi"] > 0 and te["p_roi_pos"] >= 0.90 and te["clv"] > 0 and te["clv_z"] >= 2.0
                         and exp[mb]["roi"] > 0) else ("muestra insuficiente" if not te or te["n"] < 300 else "no pasa")
        print("   %-8s PRUEBA m %2.0f%%: n %d  acierto %.1f%%  cuota %.2f  ROI %+.2f%% IC [%+.1f, %+.1f]  P(ROI>0) %.2f  CLV %+.2f%% (z %.2f, %.0f%% positivos) -> %s" % (
            nom, 100 * mb, te["n"], te["acierto"], te["cuota_media"], te["roi"], te["ic95_roi"][0], te["ic95_roi"][1], te["p_roi_pos"],
            te["clv"], te["clv_z"], te["clv_pos_pct"], ver.upper()))
        por_m = {}
        for mk, mn in (("1X2", "1X2"), ("OU", "totales")):
            r = resumen([a for a in E if a["fecha"] >= corte and sel(a, mb) and a["mercado"] == mk], cu)
            if r:
                por_m[mn] = r
                print("            %-8s n %5d  ROI %+6.2f%%  CLV %+5.2f%%" % (mn, r["n"], r["roi"], r["clv"]))
        out[nom] = {"explorar": {str(m): r for m, r in exp.items()}, "m_elegido": mb, "prueba": te, "por_mercado": por_m, "veredicto": ver}
    return out


def _dec(a):
    try: a = float(a)
    except (TypeError, ValueError): return None
    if a == 0: return None
    return 1 + a / 100.0 if a > 0 else 1 + 100.0 / -a


def _ts(s):
    try: return dt.datetime.fromisoformat((s or "").replace("Z", "")[:19])
    except ValueError: return None


def en_vivo():
    filas = []
    rutas = sorted(glob.glob(io.ruta("salida", "cuotas_sharp_*.csv"))) or sorted(glob.glob(os.path.join(CODIGO, "salida", "cuotas_sharp_*.csv")))
    for ruta in rutas:
        with _io.open(ruta, encoding="utf-8-sig") as fh:
            filas += [r for r in csv.DictReader(fh) if r.get("fuente") == "pinnacle"]
    grupos = defaultdict(list)
    for r in filas:
        if r.get("lado") == "draw" and not r["sport"].startswith("soccer"): continue
        t, ini = _ts(r["ts_utc"]), _ts(r["commence_time"])
        p = None
        try: p = float(r["p_sharp"])
        except (TypeError, ValueError): pass
        if not t or not ini or p is None or t >= ini: continue
        grupos[(r["event_id"], r["mercado"], r["lado"], r.get("linea") or "")].append((t, ini, p, _dec(r.get("mejor_cuota")), r.get("casa"), r["sport"].split("_")[0]))
    cajas = [(48, 999, "48 h o mas"), (24, 48, "24-48 h"), (12, 24, "12-24 h"), (6, 12, "6-12 h"), (3, 6, "3-6 h"), (0, 3, "menos de 3 h")]
    acc = defaultdict(list); casas = Counter(); casas_dep = defaultdict(Counter); nlados = 0
    for k, F in grupos.items():
        F.sort()
        pc = F[-1][2]                                   # cierre: ultima foto antes del inicio
        if (F[-1][1] - F[-1][0]).total_seconds() > 6 * 3600: continue   # sin foto cercana al inicio
        nlados += 1
        for t, ini, p, o, casa, dep in F:
            if not o or not (LO <= o <= HI): continue
            h = (ini - t).total_seconds() / 3600
            caja = next(n for a, b, n in cajas if a <= h < b)
            acc[caja].append((o * p - 1, o * pc - 1)); casas[casa] += 1; casas_dep[dep][casa] += 1
    print("\n3) EN VIVO 2026 (fotos de The Odds API, %d lados con foto en las 6 h previas al inicio)" % nlados)
    print("   mejor cuota del mercado entre %.2f y %.2f, contra Pinnacle sin vig en ese momento y contra su cierre" % (LO, HI))
    out = {"lados": nlados, "por_hora": {}, "casa_mejor": {}, "casa_mejor_por_deporte": {}}
    for _, _, n in cajas:
        V = acc.get(n, [])
        if not V: continue
        a = np.array(V)
        out["por_hora"][n] = {"n": len(V), "ev_momento": round(100 * float(a[:, 0].mean()), 2), "clv": round(100 * float(a[:, 1].mean()), 2),
                              "clv_pos_pct": round(100 * float((a[:, 1] > 0).mean()), 1)}
        print("   %-13s n %5d  EV en ese momento %+5.2f%%  CLV %+5.2f%%  CLV>0 %5.1f%%" % (n, len(V), 100 * a[:, 0].mean(), 100 * a[:, 1].mean(), 100 * (a[:, 1] > 0).mean()))
    tot = sum(casas.values())
    print("   casa con la mejor cuota (de %d fotos):" % tot, ", ".join("%s %.0f%%" % (c, 100 * v / tot) for c, v in casas.most_common(8)))
    out["casa_mejor"] = {c: round(100 * v / tot, 1) for c, v in casas.most_common(12)}
    for dep, C in casas_dep.items():
        t2 = sum(C.values())
        out["casa_mejor_por_deporte"][dep] = {c: round(100 * v / t2, 1) for c, v in C.most_common(5)}
        print("     %-17s %s" % (dep, ", ".join("%s %.0f%%" % (c, 100 * v / t2) for c, v in C.most_common(5))))
    return out


def main():
    L = cargar_futbol()
    print("FUTBOL: %d lados con cierre de Pinnacle" % len(L))
    out = {"descriptivo": descriptivo(L), "regla": regla(L), "en_vivo": en_vivo()}
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-09_precio_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresultados en", ruta)


if __name__ == "__main__":
    main()
