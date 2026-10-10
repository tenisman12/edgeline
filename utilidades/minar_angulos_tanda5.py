# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_tanda5.py - tanda 5 (hipotesis: trabajo/minar/2026-10-09_tanda5.md): rachas cortadas, frio contra
caliente, sequia de anotacion, tras gran sorpresa, tras paliza, abridor vapuleado (LMP/NPB); ganador y totales.
Reusa las filas as-of de las tandas 1-4 (minar_angulos_tanda4.capturar) y su evaluador. No toca modelos/ ni nucleo/.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_tanda5.py --cache trabajo/minar/tanda4_cache.pkl
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io as _io, json, math, os, pickle, sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402

TAU = 0.0924
PARAM = {   # margen "por mucho", racha larga, frio/caliente, dias maximos entre juegos de la misma temporada, umbral de sorpresa
    "NHL": dict(m=4, larga=5, fc=3, gap=20, sorpresa=0.30),
    "NBA": dict(m=20, larga=5, fc=3, gap=20, sorpresa=0.30),
    "NCAAMB": dict(m=20, larga=5, fc=3, gap=20, sorpresa=0.30),
    "NFL": dict(m=20, larga=3, fc=2, gap=21, sorpresa=0.30),
    "NCAAFB": dict(m=20, larga=3, fc=2, gap=21, sorpresa=0.30),
    "BEISBOL": dict(m=7, larga=5, fc=3, gap=20, sorpresa=0.30),
    "FUTBOL": dict(m=3, larga=3, fc=2, gap=30, sorpresa=0.25),
}


def _res(g):
    return "W" if g["gf"] > g["ga"] else ("L" if g["gf"] < g["ga"] else "D")


def previos(C, e, gp, gap):
    """juegos anteriores de la misma temporada (con marcador), del mas reciente al mas viejo."""
    i = C.i(e, gp)
    if i is None:
        return None
    f = C.t[e][i]["fecha"]; out = []
    for g in reversed(C.t[e][:i]):
        if g["gf"] is None:
            continue
        if (f - g["fecha"]).days > gap:
            break
        out.append(g); f = g["fecha"]
    return out


def sequia(dep, P, temporada):
    if dep == "BEISBOL":
        return len(P) >= 3 and all(g["gf"] <= 2 for g in P[:3])
    if dep == "NHL":
        return len(P) >= 3 and all(g["gf"] <= 1 for g in P[:3])
    if dep in ("NBA", "NCAAMB"):
        if len(temporada) < 8: return None
        prom = sum(g["gf"] for g in temporada) / len(temporada)
        return all(g["gf"] < 0.9 * prom for g in P[:3])
    if dep in ("NFL", "NCAAFB"):
        return len(P) >= 2 and all(g["gf"] <= 13 for g in P[:2])
    return len(P) >= 2 and all(g["gf"] == 0 for g in P[:2])


def construir(dep, filas, C, abridor_previo=None):
    k = PARAM[dep]
    pmap = {}
    for r in filas:
        ph = r["p"]; pa = r.get("paway") if r.get("paway") is not None else 1 - ph
        pmap[(r["home"], str(r["gp"]))] = ph; pmap[(r["away"], str(r["gp"]))] = pa
    out = []
    for r in filas:
        info = {}
        for lado in ("home", "away"):
            e = r[lado]
            P = previos(C, e, r["gp"], k["gap"])
            if P is None:
                info = None; break
            temp = P
            d = {}
            if not P:
                d.update(S1=0, S2=0, S3=0, frio=False, cal=False, S7=False, S8=0, ult=None)
            else:
                u = P[0]; resto = P[1:1 + k["larga"]]
                d["S1"] = 1 if (u["gf"] - u["ga"] >= k["m"]) else 0
                d["paliza"] = 1 if abs(u["gf"] - u["ga"]) >= k["m"] else 0
                d["S2"] = 1 if (_res(u) != "W" and len(resto) == k["larga"] and all(_res(g) == "W" for g in resto)) else 0
                d["S3"] = 1 if (_res(u) == "W" and len(resto) == k["larga"] and all(_res(g) == "L" for g in resto)) else 0
                d["frio"] = len(P) >= k["fc"] and all(_res(g) == "L" for g in P[:k["fc"]])
                d["cal"] = len(P) >= k["fc"] and all(_res(g) == "W" for g in P[:k["fc"]])
                d["S7"] = sequia(dep, P, temp)
                pu = pmap.get((e, str(u["gp"])))
                d["S8"] = 1 if (_res(u) == "W" and pu is not None and pu <= k["sorpresa"]) else 0
            if abridor_previo is not None:
                d["S9"] = abridor_previo(r, lado)
            info[lado] = d
        if info is None:
            continue
        h, a = info["home"], info["away"]
        x = dict(fecha=r["fecha"], gp=r["gp"], p=r["p"], y=r["y"], home=r["home"], away=r["away"], liga=r.get("liga") or dep,
                 corte=r.get("corte"), _r=r)
        x["S1"] = h["S1"] - a["S1"]; x["S2"] = h["S2"] - a["S2"]; x["S3"] = h["S3"] - a["S3"]
        x["S4"] = (1 if (h["frio"] and a["cal"]) else (-1 if (a["frio"] and h["cal"]) else 0))
        x["S7"] = None if (h["S7"] is None or a["S7"] is None) else int(bool(h["S7"])) - int(bool(a["S7"]))
        x["S8"] = h["S8"] - a["S8"]
        if abridor_previo is not None:
            x["S9"] = None if (h.get("S9") is None or a.get("S9") is None) else h["S9"] - a["S9"]
        x["TS1"] = h.get("paliza", 0) + a.get("paliza", 0)
        x["TS5"] = int(h["frio"] and a["frio"]); x["TS6"] = int(h["cal"] and a["cal"])
        x["TS7"] = None if x["S7"] is None else int(bool(h["S7"])) + int(bool(a["S7"]))
        out.append(x)
    return out


def abridores_previos(base):
    """LMP y NPB: (game_id, equipo) -> 1 si el abridor de ese juego permitio 5+ carreras limpias en su salida anterior."""
    res = {}
    for lg in ("lmp", "npb"):
        ruta = os.path.join(base, "datos", "abridores", "%s_lanzadores.csv" % lg)
        if not os.path.exists(ruta):
            continue
        S = []
        with _io.open(ruta, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("abridor")) in ("1", "1.0", "True"):
                    S.append((r["jugador"], r["game_date"][:10], str(r["game_id"]), r["team"], M._num(r.get("er"))))
        S.sort()
        ult = {}
        for jug, f, gid, team, er in S:
            prev = ult.get(jug)
            if prev is not None and (dt.date.fromisoformat(f) - dt.date.fromisoformat(prev[0])).days <= 20 and prev[1] is not None:
                res[(gid, team)] = 1 if prev[1] >= 5 else 0
            ult[jug] = (f, er)
    return res


def describir(rows, etiqueta):
    R = [r for r in rows if r.get("x") is not None]
    na = sum(1 for r in R if r["x"] != 0)
    if na < 5:
        return {"liga": etiqueta, "n": len(R), "n_activos": na, "sin_estimacion": True}
    b, se = T4.offset_beta(R)
    if b is None:
        return {"liga": etiqueta, "n": len(R), "n_activos": na, "sin_estimacion": True}
    xt = T4.x_tipico(R); e, s = b * xt, se * xt
    enc = e * TAU ** 2 / (TAU ** 2 + s * s)
    sg = T4._sig
    return {"liga": etiqueta, "n": len(R), "n_activos": na, "pp_50": round(100 * (sg(e) - .5), 2),
            "ic95_50": [round(100 * (sg(e - 1.96 * s) - .5), 2), round(100 * (sg(e + 1.96 * s) - .5), 2)],
            "pp_50_encogido": round(100 * (sg(enc) - .5), 2), "x_tipico": xt, "beta": round(b, 5), "ee": round(se, 5)}


NOMBRES = {"S1": ("tras ganar por mucho", -1), "S2": ("racha de victorias cortada", +1), "S3": ("racha de derrotas cortada", -1),
           "S4": ("frio contra caliente (hacia el frio)", +1), "S7": ("sequia de anotacion", +1), "S8": ("tras gran sorpresa", -1),
           "S9": ("abridor vapuleado en su salida anterior", +1)}
TOT = {"TS1": ("tras paliza (cuenta)", +1), "TS5": ("los dos frios", -1), "TS6": ("los dos calientes", +1), "TS7": ("sequia de anotacion (cuenta)", -1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    if a.cache and os.path.exists(a.cache):
        D = pickle.load(open(a.cache, "rb"))
    else:
        D = T4.capturar()
        if a.cache: pickle.dump(D, open(a.cache, "wb"))
    ULT = D["ultimo"]; M.RESULTADOS.clear()
    abr = abridores_previos(M.BASE)
    print("abridores con salida previa (LMP/NPB): %d" % len(abr))
    FILAS = {}
    for dep in ("NHL", "NBA", "NCAAMB", "NFL", "NCAAFB", "BEISBOL", "FUTBOL"):
        if dep not in ULT: continue
        filas, C = ULT[dep]
        fn = None
        if dep == "BEISBOL":
            def fn(r, lado, _abr=abr):
                lg = r.get("liga")
                if lg not in ("LMP", "NPB"): return None
                e = r[lado]; team = e[1] if isinstance(e, tuple) else e
                return _abr.get((str(r["gp"]), team))
        FILAS[dep] = construir(dep, filas, C, fn)
        print("%s: %d partidos" % (dep, len(FILAS[dep])))
    R = {"ganador": [], "agrupado": [], "totales": [], "estimacion": []}
    print("\n" + "=" * 100 + "\nGANADOR POR DEPORTE")
    for cod, (nom, s) in NOMBRES.items():
        fuentes = []
        for dep, F in FILAS.items():
            rows = [dict(r, x=r.get(cod)) for r in F if r.get(cod) is not None]
            if not rows: continue
            o = T4.evaluar_agrupado([rows], cod, nom, dep, s)
            if o: R["ganador"].append(o)
            R["estimacion"].append(dict(describir(rows, dep), codigo=cod, angulo=nom))
            if dep == "BEISBOL":
                lmp = [r for r in rows if r["liga"] == "LMP"]
                if lmp: R["estimacion"].append(dict(describir(lmp, "LMP"), codigo=cod, angulo=nom))
            fuentes.append(rows)
        if len(fuentes) > 1:
            o = T4.evaluar_agrupado(fuentes, cod, nom, "todos", s)
            if o: R["agrupado"].append(o)
            R["estimacion"].append(dict(describir([r for f in fuentes for r in f], "todos"), codigo=cod, angulo=nom))
    print("\n" + "=" * 100 + "\nTOTALES")
    for dep, F in FILAS.items():
        filas, C = ULT[dep]
        if dep == "BEISBOL":
            ld = lambda e: e[0] if isinstance(e, tuple) else "?"
        elif dep == "FUTBOL":
            le = {}
            for r in filas: le[r["home"]] = r["liga"]; le[r["away"]] = r["liga"]
            ld = lambda e, le=le: le.get(e, "FUT")
        else:
            ld = lambda e, d=dep: d
        ET = T4.esperado_total(C, filas, ld)
        for cod, (nom, s) in TOT.items():
            rows = []
            for r in F:
                et = ET.get(str(r["gp"]))
                if et and r.get(cod) is not None:
                    rows.append(dict(fecha=r["fecha"], gp=r["gp"], E=et[0], T=et[1], x=r[cod]))
            R["totales"].append(T4.evaluar_total(rows, cod, nom, dep, s))
    nuevas = [r for r in R["ganador"] + R["agrupado"] + R["totales"] if r and "z" in r]
    pasan = [r for r in nuevas if r.get("veredicto") == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d | falsos 'pasa' esperados ~ %.1f | pasan: %d" % (len(nuevas), 0.023 * len(nuevas), len(pasan)))
    for r in pasan:
        print("  PASA %s %s %s z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["z"]))
    print("\nESTIMACION (toda la muestra, pp para un partido de 50 %; encogido)")
    for e in R["estimacion"]:
        if "pp_50" in e:
            print("  %-3s %-40s %-8s n %6d act %5d  %+5.1f pp [%+5.1f, %+5.1f]  encogido %+5.1f" % (
                e["codigo"], e["angulo"][:40], e["liga"], e["n"], e["n_activos"], e["pp_50"], e["ic95_50"][0], e["ic95_50"][1], e["pp_50_encogido"]))
    out = dict(generado=dt.datetime.now().isoformat(timespec="seconds"), hipotesis="trabajo/minar/2026-10-09_tanda5.md",
               k=len(nuevas), falsos_esperados=round(0.023 * len(nuevas), 1), **R)
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-09_tanda5_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
