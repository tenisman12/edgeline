# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_tanda6.py - tanda 6 (hipotesis: trabajo/minar/2026-10-09_tanda6.md): angulos por equipo.
Cada partido da dos filas (una por equipo). Resultado: lo que anota el equipo. Base: anotacion esperada as-of
E = (ataque propio + defensa del rival)/2 con olvido, mas un termino de local. Ataque: x = situacion propia.
Defensa: x = situacion del rival (lo que recibe el que esta en la situacion). Reusa las filas y calendarios de las tandas 1-4.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_tanda6.py --cache trabajo/minar/tanda4_cache.pkl
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, bisect, datetime as dt, json, math, os, pickle, sys
from collections import Counter, defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_angulos_tanda5 as T5  # noqa: E402

ALT = {"NHL": {"COL", "UTA"}, "NBA": {"DEN", "UTA"}}
ALT_MX = {"Toluca", "Club America", "Cruz Azul", "UNAM Pumas", "Pachuca", "Puebla"}
# codigo: (nombre, signo ataque, signo defensa)   (None = no se prueba)
DIR = {"b2b": ("segunda noche", -1, +1), "carga7": ("carga de 7 dias (juegos)", -1, +1), "c4en6": ("cuarto juego en 6 noches", -1, +1),
       "c3en4": ("tercer juego en 4 noches", -1, +1), "desc3": ("descanso largo (3+ dias)", +1, -1), "dlibre": ("viene de dia libre", +1, -1),
       "dseg": ("dias seguidos jugando (/10)", -1, +1), "gira": ("gira del visitante", -1, +1), "ot": ("prorroga o extra innings en el anterior", -1, +1),
       "pim": ("castigos del anterior (/10)", -1, +1), "port": ("portero distinto del habitual", None, +1),
       "perdio": ("tras perder por mucho", +1, -1), "gano": ("tras ganar por mucho", -1, +1), "frio": ("frio (racha de derrotas)", +1, -1),
       "cal": ("caliente (racha de victorias)", -1, +1), "seq": ("sequia de anotacion", +1, None), "alt": ("visitante en altura", -1, +1),
       "corto": ("descanso corto (3 dias o menos)", -1, +1), "champ": ("Champions entre semana", -1, +1), "fifa": ("regreso de fecha FIFA (12+ dias)", +1, -1),
       "corta": ("semana corta (5 dias o menos)", -1, +1), "bye": ("viene de semana libre", +1, -1), "jueves": ("jueves por la noche", -1, None),
       "vap": ("abridor propio vapuleado en su salida anterior", None, -1)}


def _ew(L, campo, prior, w0=5.0, d=0.97):
    return T4._ew(L, campo, prior, w0, d)


def situacion(dep, C, e, gp, r, abr):
    i = C.i(e, gp)
    if i is None:
        return None
    g = C.t[e][i]; f = g["fecha"]
    k = T5.PARAM[dep]
    P = [x for x in C.t[e][:i]]
    Pl = [x for x in P if x["gf"] is not None]
    rest = (f - P[-1]["fecha"]).days if P else None
    S = T5.previos(C, e, gp, k["gap"])           # misma temporada, mas reciente primero
    s = {}
    if S:
        u = S[0]
        s["perdio"] = int(u["ga"] - u["gf"] >= k["m"]); s["gano"] = int(u["gf"] - u["ga"] >= k["m"])
        res = lambda x: "W" if x["gf"] > x["ga"] else ("L" if x["gf"] < x["ga"] else "D")
        s["frio"] = int(len(S) >= k["fc"] and all(res(x) == "L" for x in S[:k["fc"]]))
        s["cal"] = int(len(S) >= k["fc"] and all(res(x) == "W" for x in S[:k["fc"]]))
        q = T5.sequia(dep, S, S)
        if q is not None: s["seq"] = int(bool(q))
    win = lambda dias: sum(1 for x in P if 0 < (f - x["fecha"]).days <= dias)
    if dep == "NHL":
        if rest is not None and rest <= 20:
            s["b2b"] = int(rest == 1); s["carga7"] = win(7); s["c4en6"] = int(win(5) >= 3); s["desc3"] = int(rest >= 3)
        if not g["local"]: s["gira"] = int((C.visitas_seguidas(e, gp) or 0) >= 3)
        pv = Pl[-1] if Pl else None
        if pv is not None and rest is not None and rest <= 20:
            if pv.get("ot") is not None: s["ot"] = int(bool(pv["ot"]))
            if pv.get("pim") is not None: s["pim"] = pv["pim"] / 10.0
        act = g.get("portero")
        prev = [x.get("portero") for x in C.t[e][max(0, i - 10):i] if x.get("portero")]
        if act and len(prev) >= 5: s["port"] = int(act != Counter(prev).most_common(1)[0][0])
        if not g["local"]: s["alt"] = int(g["rival"] in ALT["NHL"] and e not in ALT["NHL"])
    elif dep in ("NBA", "NCAAMB"):
        if rest is not None and rest <= 30:
            s["b2b"] = int(rest == 1); s["c3en4"] = int(win(3) >= 2); s["desc3"] = int(rest >= 3)
        if not g["local"]: s["gira"] = int((C.visitas_seguidas(e, gp) or 0) >= 3)
        pv = Pl[-1] if Pl else None
        if dep == "NBA" and pv is not None and pv.get("ot") is not None and rest is not None and rest <= 30: s["ot"] = int(bool(pv["ot"]))
        if dep == "NBA" and not g["local"]: s["alt"] = int(g["rival"] in ALT["NBA"] and e not in ALT["NBA"])
    elif dep == "BEISBOL":
        if rest is not None and rest <= 20:
            s["dlibre"] = int(rest >= 2); s["dseg"] = min(C.dias_seguidos(e, gp) or 0, 20) / 10.0
            pv = Pl[-1] if Pl else None
            if pv is not None and pv.get("ip") is not None: s["ot"] = int(pv["ip"] >= 9.95)
        if not g["local"]: s["gira"] = int((C.visitas_seguidas(e, gp) or 0) >= 6)
        if r.get("liga") == "LMP":
            team = e[1] if isinstance(e, tuple) else e
            v = abr.get((str(gp), team))
            if v is not None: s["vap"] = v
    elif dep == "FUTBOL":
        if rest is not None and rest <= 30:
            s["corto"] = int(rest <= 3)
            s["champ"] = int(any(str(x["gp"]).startswith("ch") and 0 < (f - x["fecha"]).days <= 4 for x in P[-3:]))
        if Pl:
            dl = (f - Pl[-1]["fecha"]).days
            if dl <= 30: s["fifa"] = int(dl >= 12)
        if not g["local"] and r.get("liga") == "LigaMX": s["alt"] = int(g["rival"] in ALT_MX and e not in ALT_MX)
    elif dep in ("NFL", "NCAAFB"):
        if rest is not None and rest <= 21:
            s["corta"] = int(rest <= 5); s["bye"] = int(13 <= rest <= 20)
        s["jueves"] = int(f.weekday() == 3)
    return s


def filas_equipo(dep, filas, C, abr, liga_de):
    # media de la liga hasta el dia anterior (goles por equipo y partido)
    hist = defaultdict(list)
    for e, L in C.t.items():
        for g in L:
            if g["local"] and g["gf"] is not None and g["ga"] is not None:
                hist[liga_de(e)].append((g["fecha"], (g["gf"] + g["ga"]) / 2.0))
    acum = {}
    for lg, L in hist.items():
        L.sort(); fs = [x[0] for x in L]; cs = []; t = 0.0
        for _, v in L: t += v; cs.append(t)
        acum[lg] = (fs, cs)
    out = []
    for r in filas:
        for lado, otro in (("home", "away"), ("away", "home")):
            e, o, gp = r[lado], r[otro], r["gp"]
            g = C.actual(e, gp)
            if not g or g["gf"] is None: continue
            fs, cs = acum.get(liga_de(e), ([], []))
            k = bisect.bisect_left(fs, g["fecha"])
            if k < 50: continue
            media = cs[k - 1] / k
            ie, io_ = C.i(e, gp), C.i(o, gp)
            Le = [x for x in C.t[e][:ie] if x["gf"] is not None]; Lo = [x for x in C.t[o][:io_] if x["gf"] is not None]
            if len(Le) < 5 or len(Lo) < 5: continue
            E = (_ew(Le, "gf", media) + _ew(Lo, "ga", media)) / 2.0
            se, so = situacion(dep, C, e, gp, r, abr), situacion(dep, C, o, gp, r, abr)
            if se is None or so is None: continue
            out.append(dict(fecha=r["fecha"], gp=r["gp"], E=E, T=g["gf"], local=1.0 if lado == "home" else 0.0, se=se, so=so,
                            liga=r.get("liga") or dep))
    return out


def ols(X, Y):
    d = len(X[0]); A = [[sum(x[i] * x[j] for x in X) for j in range(d)] for i in range(d)]
    b = [sum(x[i] * y for x, y in zip(X, Y)) for i in range(d)]
    for i in range(d): A[i][i] += 1e-9
    return M._resolver(A, b)


def evaluar(rows, codigo, nombre, liga, signo, lectura):
    F = sorted([r for r in rows if r.get("x") is not None], key=lambda r: (r["fecha"], str(r["gp"])))
    na_tot = sum(1 for r in F if r["x"] != 0)
    base = {"codigo": codigo, "angulo": nombre, "liga": liga, "lectura": lectura, "n_total": len(F), "n_activo_total": na_tot}
    if len(F) < 200 or na_tot < 30:
        base["veredicto"] = "muestra insuficiente"; return base
    i70 = int(len(F) * 0.7); tr, te = F[:i70], F[i70:]
    w0 = ols([[1.0, r["E"], r["local"]] for r in tr], [r["T"] for r in tr])
    w1 = ols([[1.0, r["E"], r["local"], float(r["x"])] for r in tr], [r["T"] for r in tr])
    if not w0 or not w1:
        base["veredicto"] = "sin ajuste"; return base
    d = []; res1 = []
    for r in te:
        p0 = w0[0] + w0[1] * r["E"] + w0[2] * r["local"]; p1 = w1[0] + w1[1] * r["E"] + w1[2] * r["local"] + w1[3] * r["x"]
        d.append((r["T"] - p0) ** 2 - (r["T"] - p1) ** 2); res1.append(r["T"] - p1)
    n = len(d); m = sum(d) / n; sd = math.sqrt(sum((v - m) ** 2 for v in d) / max(n - 1, 1)) or 1e-12
    z = m / (sd / math.sqrt(n)); h = n // 2
    m1, m2 = sum(d[:h]) / max(h, 1), sum(d[h:]) / max(n - h, 1)
    act = [i for i, r in enumerate(te) if r["x"] != 0]; na = len(act)
    mT = sum(r["T"] for r in te) / n; sdT = math.sqrt(sum((r["T"] - mT) ** 2 for r in te) / max(n - 1, 1)) or 1e-12
    sesgo = (sum(res1[i] for i in act) / na / sdT) if na else None
    # efecto en toda la muestra con su EE (OLS)
    X = [[1.0, r["E"], r["local"], float(r["x"])] for r in F]; Y = [r["T"] for r in F]
    wa = ols(X, Y)
    resid = [y - sum(a * b for a, b in zip(wa, x)) for x, y in zip(X, Y)]
    s2 = sum(v * v for v in resid) / max(len(F) - 4, 1)
    xs = [r["x"] for r in F]; mx = sum(xs) / len(xs); sxx = sum((v - mx) ** 2 for v in xs)
    ee = math.sqrt(s2 / sxx) if sxx > 0 else None
    xt = T4.x_tipico(F) or 1.0
    dir_ok = (w1[3] > 0) == (signo > 0)
    if na < 300: ver = "muestra insuficiente"
    elif dir_ok and z >= 2.0 and m1 > 0 and m2 > 0 and sesgo is not None and abs(sesgo) <= 0.10: ver = "pasa"
    else: ver = "no pasa"
    base.update({"n_prueba": n, "n_activo_prueba": na, "coef_por_unidad": round(w1[3], 4), "direccion_ok": dir_ok,
                 "mejora_mse": round(m, 5), "z": round(z, 2), "mitades": [round(m1, 5), round(m2, 5)],
                 "sesgo_activos_desv": None if sesgo is None else round(sesgo, 3), "veredicto": ver, "x_tipico": xt,
                 "efecto_toda_muestra": round(wa[3] * xt, 3), "ic95_toda_muestra": None if ee is None else [round((wa[3] - 1.96 * ee) * xt, 3), round((wa[3] + 1.96 * ee) * xt, 3)],
                 "desde_prueba": te[0]["fecha"]})
    print("  %-6s %-40s %-8s %-7s n %5d act %5d  efecto %+.3f [%+.3f, %+.3f]  z %+5.2f  mit %+.4f/%+.4f  sesgo %+.3f -> %s" % (
        codigo, nombre[:40], liga[:8], lectura, n, na, base["efecto_toda_muestra"], (base["ic95_toda_muestra"] or [0, 0])[0],
        (base["ic95_toda_muestra"] or [0, 0])[1], z, m1, m2, sesgo or 0.0, ver.upper()))
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    if a.cache and os.path.exists(a.cache):
        D = pickle.load(open(a.cache, "rb"))
    else:
        D = T4.capturar()
        if a.cache: pickle.dump(D, open(a.cache, "wb"))
    ULT = D["ultimo"]
    abr = T5.abridores_previos(M.BASE)
    R = []
    for dep in ("NHL", "NBA", "NCAAMB", "NFL", "NCAAFB", "BEISBOL", "FUTBOL"):
        if dep not in ULT: continue
        filas, C = ULT[dep]
        if dep == "BEISBOL":
            ld = lambda e: e[0] if isinstance(e, tuple) else "?"
        elif dep == "FUTBOL":
            le = {}
            for r in filas: le[r["home"]] = r["liga"]; le[r["away"]] = r["liga"]
            ld = lambda e, le=le: le.get(e, "FUT")
        else:
            ld = lambda e, d=dep: d
        F = filas_equipo(dep, filas, C, abr, ld)
        print("\n%s: %d filas de equipo" % (dep, len(F)))
        codigos = sorted({c for r in F for c in list(r["se"].keys())})
        for c in codigos:
            nom, s_at, s_df = DIR[c]
            if s_at is not None:
                R.append(evaluar([dict(r, x=r["se"].get(c)) for r in F], c, nom, dep, s_at, "ataque"))
            if s_df is not None:
                R.append(evaluar([dict(r, x=r["so"].get(c)) for r in F], c, nom, dep, s_df, "defensa"))
    nuevas = [r for r in R if "z" in r]
    pasan = [r for r in nuevas if r["veredicto"] == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d | falsos 'pasa' esperados ~ %.1f | pasan: %d" % (len(nuevas), 0.023 * len(nuevas), len(pasan)))
    for r in pasan:
        print("  PASA %-6s %-40s %-8s %-7s efecto %+.3f z %+.2f" % (r["codigo"], r["angulo"][:40], r["liga"], r["lectura"], r["efecto_toda_muestra"], r["z"]))
    out = dict(generado=dt.datetime.now().isoformat(timespec="seconds"), hipotesis="trabajo/minar/2026-10-09_tanda6.md",
               k=len(nuevas), falsos_esperados=round(0.023 * len(nuevas), 1), resultados=R)
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-09_tanda6_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
