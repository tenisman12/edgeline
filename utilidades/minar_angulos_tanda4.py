# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_tanda4.py - tanda 4 de angulos situacionales (hipotesis: trabajo/minar/2026-10-09_tanda4.md).

  A. Estimacion de TODOS los angulos de ganador ya medidos con la muestra que haya (offset sobre el modelo, toda la
     muestra, IC 95 % y efecto encogido por Bayes empirico). Descriptivo: dice cuanto moveria el pronostico.
  B. Ganador agrupado: mismo codigo en varias ligas, altitud (G1) y rebote tras paliza (G12). Protocolo completo.
  C. Totales: angulos simetricos contra el total esperado as-of (tasas de anotacion con olvido) y, donde hay cierre
     historico, Over/Under contra el mercado (futbol 2.5, NFL total_line).
  D. Nuevos: F18 derbi (futbol) y T6 jugador local (tenis).
No toca modelos/ ni nucleo/. Reusa las filas de minar_situacionales, minar_cualitativos y minar_angulos_tanda3.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_tanda4.py            # corre todo (unos 5 minutos)
    python utilidades/minar_angulos_tanda4.py --cache trabajo/minar/tanda4_cache.pkl   # guarda / reusa las filas
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, bisect, csv, datetime as dt, io as _io, json, math, os, pickle, sys, time
from collections import defaultdict, Counter

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402

EV_REAL = M.evaluar
KEEP = ("fecha", "gp", "p", "y", "x", "home", "away", "res", "paway", "pm", "corte", "liga")


# ------------------------------------------------------------------ 0. filas de las tres tandas
def capturar():
    CAP = []

    def captura(filas, codigo, nombre, liga, signo, corte=None, base_nombre="modelo"):
        rows = [{k: r[k] for k in KEEP if k in r} for r in filas
                if r.get("x") is not None and r.get("p") is not None and r.get("y") is not None]
        CAP.append(dict(codigo=codigo, nombre=nombre, liga=liga, signo=signo, base=base_nombre, rows=rows))
        return {"veredicto": "capturado"}
    M.evaluar = captura
    t0 = time.time()
    M.correr_hockey(); M.correr_basquet("NBA"); M.correr_basquet("NCAAMB"); M.correr_americano("NFL"); M.correr_americano("NCAAFB")
    M.correr_beisbol(["MLB", "NPB", "KBO", "LMP", "LVBP", "LIDOM", "ABL"]); M.correr_futbol()
    ULT = dict(M.ULTIMO)
    for nom in ("correr_hockey", "correr_basquet", "correr_americano", "correr_beisbol", "correr_futbol"):
        setattr(M, nom, (lambda *a, **k: None))
    import minar_cualitativos as Q
    for dep in ("NHL", "NBA", "BEISBOL", "FUTBOL"):
        filas, C = ULT[dep]; Q.correr(dep, filas, C, Q.ESP)
    filas, C = ULT["NFL"]
    seq = {}
    for r in sorted(filas, key=lambda r: r["fecha"]):
        for e, k in ((r["home"], "coach_h"), (r["away"], "coach_a")):
            if r.get(k): seq.setdefault(e, []).append((r["fecha"], r["gp"], r[k]))
    nuevo = {}
    for e, L in seq.items():
        cambio = None
        for i, (f, gp, co) in enumerate(L):
            if i:
                mismo = (dt.date.fromisoformat(f[:10]) - dt.date.fromisoformat(L[i - 1][0][:10])).days <= 60
                if mismo and co != L[i - 1][2]: cambio = i
                elif not mismo: cambio = None
            if cambio is not None and i - cambio < 3 and co == L[cambio][2]:
                nuevo[(e, gp)] = True
    esp_nfl = dict(Q.ESP); esp_nfl.update({"Q8": -1, "Q9": +1})
    Q.correr("NFL", filas, C, esp_nfl, coach_nuevo=lambda e, gp: nuevo.get((e, gp), False))
    import minar_angulos_tanda3 as T3
    T3._ev_original = captura
    TEN = []
    orig_tenis_eval = T3.evaluar

    def ev_t3(filas, cod, nom, liga, signo, **k):
        if cod == "T3":
            TEN.extend({kk: r[kk] for kk in ("fecha", "gp", "p", "y", "liga")} for r in filas)
        return orig_tenis_eval(filas, cod, nom, liga, signo, **k)
    T3.evaluar = ev_t3
    for f in (T3.hockey, T3.basquet, lambda: T3.americano("NFL"), lambda: T3.americano("NCAAFB"), T3.beisbol, T3.futbol, T3.tenis):
        f()
    M.evaluar = EV_REAL
    print("filas capturadas: %d pruebas en %.0f s" % (len(CAP), time.time() - t0), flush=True)
    return {"cap": CAP, "ultimo": ULT, "tenis": TEN}


# ------------------------------------------------------------------ utilidades
def _lg(p): return M._lg(p)
def _sig(x): return M._sig(x)


def offset_beta(rows):
    """logit(q) = logit(p) + beta*x en toda la muestra. Devuelve beta, EE."""
    b = 0.0; h = 0.0
    for _ in range(60):
        g = h = 0.0
        for r in rows:
            q = _sig(_lg(r["p"]) + b * r["x"]); g += (q - r["y"]) * r["x"]; h += q * (1 - q) * r["x"] ** 2
        if h <= 0: return None, None
        paso = g / h; b -= paso
        if abs(paso) < 1e-10: break
    return b, (1 / math.sqrt(h) if h > 0 else None)


def x_tipico(rows):
    act = sorted(abs(r["x"]) for r in rows if r["x"] != 0)
    return act[len(act) // 2] if act else None


def marcar_prueba(rows, corte=None):
    """marca el 30 % final de un conjunto (o fecha >= corte de cada fila, como beisbol)."""
    R = sorted(rows, key=lambda r: (r["fecha"], str(r.get("gp", ""))))
    i70 = int(len(R) * 0.7)
    for i, r in enumerate(R):
        r["_te"] = (r["fecha"] >= r["corte"]) if r.get("corte") else (i >= i70)
    return R


def evaluar_agrupado(fuentes, codigo, nombre, etiqueta, signo, base="modelo"):
    """une filas de varias pruebas; cada una conserva su propio corte 70/30."""
    G = []
    for rows in fuentes:
        for r in marcar_prueba([dict(r) for r in rows]):
            G.append(dict(r, fecha=("1" if r["_te"] else "0") + r["fecha"]))
    out = EV_REAL(G, codigo, nombre, etiqueta, signo, corte="1", base_nombre=base)
    if out and out.get("desde_prueba"): out["desde_prueba"] = out["desde_prueba"][1:]
    if out is not None:
        out["n_total"] = len(G); out["n_activo_total"] = sum(1 for r in G if r["x"] != 0)
    return out


# ------------------------------------------------------------------ A. estimacion de todos
def parte_a(cap):
    print("\n" + "=" * 100 + "\nA. ESTIMACION CON LA MUESTRA QUE HAYA (offset sobre el modelo, toda la muestra)")
    E = []
    for c in cap:
        if c["base"] != "modelo": continue
        rows = c["rows"]
        xt = x_tipico(rows)
        na = sum(1 for r in rows if r["x"] != 0)
        if not xt or na < 5:
            E.append(dict(codigo=c["codigo"], liga=c["liga"], angulo=c["nombre"], n=len(rows), n_activos=na, sin_estimacion=True)); continue
        b, se = offset_beta(rows)
        if b is None:
            E.append(dict(codigo=c["codigo"], liga=c["liga"], angulo=c["nombre"], n=len(rows), n_activos=na, sin_estimacion=True)); continue
        e, s = b * xt, se * xt
        E.append(dict(codigo=c["codigo"], liga=c["liga"], angulo=c["nombre"], signo_registrado=c["signo"], n=len(rows), n_activos=na,
                      x_tipico=round(xt, 3), beta=round(b, 4), ee=round(se, 4), _e=e, _s=s))
    con = [x for x in E if "_e" in x]
    tau2 = max(0.0, (sum(x["_e"] ** 2 for x in con) - sum(x["_s"] ** 2 for x in con)) / len(con))
    for x in con:
        e, s = x.pop("_e"), x.pop("_s")
        enc = e * tau2 / (tau2 + s * s) if tau2 > 0 else 0.0
        x["pp_50"] = round(100 * (_sig(e) - 0.5), 2)
        x["ic95_50"] = [round(100 * (_sig(e - 1.96 * s) - 0.5), 2), round(100 * (_sig(e + 1.96 * s) - 0.5), 2)]
        x["pp_60"] = round(100 * (_sig(_lg(0.6) + e) - 0.6), 2)
        x["pp_50_encogido"] = round(100 * (_sig(enc) - 0.5), 2)
        x["pp_60_encogido"] = round(100 * (_sig(_lg(0.6) + enc) - 0.6), 2)
        x["z_toda_muestra"] = round(e / s, 2) if s else None
        x["ic_excluye_0"] = (x["ic95_50"][0] > 0) or (x["ic95_50"][1] < 0)
    print("  tau (entre angulos, logit) = %.4f -> encogimiento" % math.sqrt(tau2))
    for x in sorted(con, key=lambda x: -abs(x["pp_50_encogido"]))[:40]:
        print("  %-4s %-40s %-8s n %6d act %5d  %+5.1f pp [%+5.1f, %+5.1f]  encogido %+5.1f pp  (60%%: %+5.1f)" % (
            x["codigo"], x["angulo"][:40], x["liga"][:8], x["n"], x["n_activos"], x["pp_50"], x["ic95_50"][0], x["ic95_50"][1],
            x["pp_50_encogido"], x["pp_60_encogido"]))
    return E, math.sqrt(tau2)


# ------------------------------------------------------------------ B. agrupados
G1 = {("H24", "NHL"), ("K13", "NBA"), ("B25", "MLB"), ("F14", "LigaMX")}
G12 = {("H21", "NHL"), ("K10", "NBA"), ("K10", "NCAAMB"), ("N12", "NFL"), ("N12", "NCAAFB"), ("B21", "TODAS"), ("F13", "7 ligas")}


def parte_b(cap):
    print("\n" + "=" * 100 + "\nB. GANADOR AGRUPADO (protocolo completo)")
    R = []
    todas = {c["codigo"] for c in cap if c["base"] == "modelo" and c["liga"] == "TODAS"}
    mod = [c for c in cap if c["base"] == "modelo" and not (c["liga"] == "MLB" and c["codigo"] in todas)]
    por = defaultdict(list)
    for c in mod: por[c["codigo"]].append(c)
    for cod, L in sorted(por.items()):
        if len(L) < 2: continue
        ligas = "+".join(c["liga"] for c in L)
        out = evaluar_agrupado([c["rows"] for c in L], cod, L[0]["nombre"], ligas, L[0]["signo"])
        if out: R.append(dict(out, grupo="mismo codigo"))
    # T2 encima de la capa T1 que ya esta en produccion (ATP): p_atp = logit^-1(logit p + 0.1637 * x_T1)
    t1 = {str(r["gp"]): r["x"] for c in mod if c["codigo"] == "T1" and c["liga"] == "ATP" for r in c["rows"]}
    cap_t2 = [c for c in mod if c["codigo"] == "T2"]
    if cap_t2:
        fuentes = []
        for c in cap_t2:
            if c["liga"] == "ATP":
                fuentes.append([dict(r, p=_sig(_lg(r["p"]) + 0.1637 * t1.get(str(r["gp"]), 0.0))) for r in c["rows"]])
            else:
                fuentes.append(c["rows"])
        out = evaluar_agrupado(fuentes, "T2", "partido anterior a la distancia, sobre la capa T1", "ATP+WTA prod", +1, base="produccion")
        if out: R.append(dict(out, grupo="mismo codigo, sobre produccion"))
    for etq, S, nom in (("G1", G1, "altitud del local"), ("G12", G12, "rebote tras paliza")):
        L = [c for c in mod if (c["codigo"], c["liga"]) in S]
        out = evaluar_agrupado([c["rows"] for c in L], etq, nom, "+".join(c["liga"] for c in L), +1)
        if out: R.append(dict(out, grupo="mecanismo"))
    return R


# ------------------------------------------------------------------ C. totales
ALT = {"NHL": {"COL", "UTA"}, "NBA": {"DEN", "UTA"}}
ALT_MX = {"Toluca", "Club America", "Cruz Azul", "UNAM Pumas", "Pachuca", "Puebla"}


def _ew(L, campo, prior, w0=5.0, d=0.97):
    s, n, f = prior * w0, w0, 1.0
    for g in reversed(L[-40:]):
        v = g.get(campo)
        if v is None: continue
        s += f * v; n += f; f *= d
    return s / n


def esperado_total(C, filas, liga_de):
    """total esperado as-of: (ataque local + defensa visita)/2 + (ataque visita + defensa local)/2, con olvido y encogido
    a la media de la liga hasta el dia anterior."""
    hist = defaultdict(list)
    for e, L in C.t.items():
        for g in L:
            if g["local"] and g["gf"] is not None and g["ga"] is not None:
                hist[liga_de(e)].append((g["fecha"], g["gf"] + g["ga"]))
    acum = {}
    for lg, L in hist.items():
        L.sort(); fs = [f for f, _ in L]; cs = []
        s = 0.0
        for _, t in L: s += t; cs.append(s)
        acum[lg] = (fs, cs)
    out = {}
    for r in filas:
        h, a, gp = r["home"], r["away"], r["gp"]
        gh = C.actual(h, gp)
        if not gh or gh["gf"] is None or gh["ga"] is None: continue
        f = gh["fecha"]; fs, cs = acum.get(liga_de(h), ([], []))
        k = bisect.bisect_left(fs, f)
        if k < 50: continue
        media = cs[k - 1] / k
        ih, ia = C.i(h, gp), C.i(a, gp)
        Lh = [g for g in C.t[h][:ih] if g["gf"] is not None]; La = [g for g in C.t[a][:ia] if g["gf"] is not None]
        if len(Lh) < 5 or len(La) < 5: continue
        m = media / 2
        E = (_ew(Lh, "gf", m) + _ew(La, "ga", m)) / 2 + (_ew(La, "gf", m) + _ew(Lh, "ga", m)) / 2
        out[str(gp)] = (E, gh["gf"] + gh["ga"])
    return out


def evaluar_total(rows, codigo, nombre, liga, signo):
    """rows: fecha, gp, E, T, x. OLS T ~ a + b E (+ c x) en el 70 %; error cuadratico pareado en el 30 %."""
    F = [r for r in rows if r.get("x") is not None]
    F.sort(key=lambda r: (r["fecha"], str(r["gp"])))
    na_tot = sum(1 for r in F if r["x"] != 0)
    if len(F) < 200 or na_tot < 30:
        out = {"veredicto": "muestra insuficiente", "n": len(F), "n_activo_total": na_tot}
        out.update(codigo=codigo, angulo=nombre, liga=liga, base="total esperado", mercado="total")
        print("  %-5s %-42s %-8s %s" % (codigo, nombre[:42], liga[:8], out)); return out
    i70 = int(len(F) * 0.7); tr, te = F[:i70], F[i70:]

    def ols(X, Y):
        d = len(X[0]); A = [[sum(x[i] * x[j] for x in X) for j in range(d)] for i in range(d)]
        bb = [sum(x[i] * y for x, y in zip(X, Y)) for i in range(d)]
        for i in range(d): A[i][i] += 1e-9
        return M._resolver(A, bb)
    w0 = ols([[1.0, r["E"]] for r in tr], [r["T"] for r in tr])
    w1 = ols([[1.0, r["E"], float(r["x"])] for r in tr], [r["T"] for r in tr])
    if w0 is None or w1 is None:
        return {"codigo": codigo, "angulo": nombre, "liga": liga, "veredicto": "sin ajuste"}
    d = []; res1 = []
    for r in te:
        p0 = w0[0] + w0[1] * r["E"]; p1 = w1[0] + w1[1] * r["E"] + w1[2] * r["x"]
        d.append((r["T"] - p0) ** 2 - (r["T"] - p1) ** 2); res1.append(r["T"] - p1)
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / max(n - 1, 1)) or 1e-12
    z = m / (sd / math.sqrt(n)); h = n // 2
    m1, m2 = sum(d[:h]) / max(h, 1), sum(d[h:]) / max(n - h, 1)
    act = [i for i, r in enumerate(te) if r["x"] != 0]; na = len(act)
    sdT = math.sqrt(sum((r["T"] - sum(x["T"] for x in te) / n) ** 2 for r in te) / max(n - 1, 1))
    sesgo = (sum(res1[i] for i in act) / na / sdT) if na else None
    # efecto descriptivo en toda la muestra (con su EE): T - (a + b E) ~ c x
    wa = ols([[1.0, r["E"], float(r["x"])] for r in F], [r["T"] for r in F])
    resid = [r["T"] - (wa[0] + wa[1] * r["E"] + wa[2] * r["x"]) for r in F]
    s2 = sum(v * v for v in resid) / max(len(F) - 3, 1)
    xs = [r["x"] for r in F]; mx = sum(xs) / len(xs); sxx = sum((x - mx) ** 2 for x in xs)
    ee = math.sqrt(s2 / sxx) if sxx > 0 else None
    xt = x_tipico(F)
    dir_ok = (w1[2] > 0) == (signo > 0)
    if na < 300: ver = "muestra insuficiente"
    elif dir_ok and z >= 2.0 and m1 > 0 and m2 > 0 and sesgo is not None and abs(sesgo) <= 0.10: ver = "pasa"
    else: ver = "no pasa"
    out = {"codigo": codigo, "angulo": nombre, "liga": liga, "base": "total esperado", "mercado": "total",
           "n_prueba": n, "n_activo_prueba": na, "n_total": len(F), "n_activo_total": na_tot, "coef_por_unidad": round(w1[2], 3),
           "direccion_ok": dir_ok, "mejora_mse": round(m, 4), "z": round(z, 2), "mitades": [round(m1, 4), round(m2, 4)],
           "sesgo_activos_desv": None if sesgo is None else round(sesgo, 3), "veredicto": ver,
           "efecto_toda_muestra": round(wa[2] * (xt or 1), 3), "ic95_toda_muestra": None if ee is None else
           [round((wa[2] - 1.96 * ee) * (xt or 1), 3), round((wa[2] + 1.96 * ee) * (xt or 1), 3)], "x_tipico": xt,
           "desde_prueba": te[0]["fecha"]}
    print("  %-5s %-42s %-8s n %5d act %5d  coef %+.3f  efecto %+.3f [%+.3f, %+.3f]  z %+5.2f  mit %+.4f/%+.4f  sesgo %+.3f -> %s" % (
        codigo, nombre[:42], liga[:8], n, na, w1[2], out["efecto_toda_muestra"], (out["ic95_toda_muestra"] or [0, 0])[0],
        (out["ic95_toda_muestra"] or [0, 0])[1], z, m1, m2, sesgo or 0.0, ver.upper()))
    return out


def _ind(v): return 1 if v else 0


def parte_c(cap, ULT):
    print("\n" + "=" * 100 + "\nC. TOTALES")
    R = []
    xcap = {(c["codigo"], c["liga"]): {str(r["gp"]): r["x"] for r in c["rows"]} for c in cap if c["base"] == "modelo"}

    def correr(dep, liga_de, defs, filtro=None):
        filas, C = ULT[dep]
        if filtro: filas = [r for r in filas if filtro(r)]
        ET = esperado_total(C, filas, liga_de)
        base = []
        for r in filas:
            et = ET.get(str(r["gp"]))
            if et: base.append(dict(fecha=r["fecha"], gp=r["gp"], E=et[0], T=et[1], _r=r))
        print("  %s: %d partidos con total esperado as-of" % (dep if not filtro else dep + "*", len(base)))
        for cod, nom, s, fn in defs:
            rows = []
            for b in base:
                try:
                    x = fn(b["_r"], C)
                except (KeyError, TypeError):
                    x = None
                if x is not None: rows.append(dict(b, x=x))
            R.append(evaluar_total(rows, cod, nom, defs_liga[0], s))
        return base

    # NHL
    def nhl_defs():
        def rest(C, e, gp): return C.descanso(e, gp)
        def prev(C, e, gp): return C.prev(e, gp)
        def portero_raro(C, e, gp):
            i = C.i(e, gp); act = C.t[e][i]["portero"]
            if not act: return None
            pv = [g["portero"] for g in C.t[e][max(0, i - 10):i] if g["portero"]]
            if len(pv) < 5: return None
            return act != Counter(pv).most_common(1)[0][0]
        def th7(r, C):
            a, b = portero_raro(C, r["home"], r["gp"]), portero_raro(C, r["away"], r["gp"])
            return None if a is None or b is None else _ind(a) + _ind(b)
        def th3(r, C):
            ph, pa = prev(C, r["home"], r["gp"]), prev(C, r["away"], r["gp"])
            if not ph or not pa or ph["ot"] is None or pa["ot"] is None: return None
            return _ind(ph["ot"]) + _ind(pa["ot"])
        def th4(r, C):
            ph, pa = prev(C, r["home"], r["gp"]), prev(C, r["away"], r["gp"])
            if not ph or not pa or ph["pim"] is None or pa["pim"] is None: return None
            return (ph["pim"] + pa["pim"]) / 10.0
        return [("TH1", "segunda noche (cuenta)", +1, lambda r, C: _ind(rest(C, r["home"], r["gp"]) == 1) + _ind(rest(C, r["away"], r["gp"]) == 1)),
                ("TH2", "carga de 7 dias (suma)", +1, lambda r, C: (C.en_ventana(r["home"], r["gp"], 7) or 0) + (C.en_ventana(r["away"], r["gp"], 7) or 0)),
                ("TH3", "prorroga en el anterior (cuenta)", +1, th3),
                ("TH4", "castigos del anterior (suma/10)", +1, th4),
                ("TH5", "altitud (Colorado, Utah)", +1, lambda r, C: 1 if (r["home"] in ALT["NHL"] and r["away"] not in ALT["NHL"]) else 0),
                ("TH6", "gira del visitante 3+", +1, lambda r, C: _ind((C.visitas_seguidas(r["away"], r["gp"]) or 0) >= 3)),
                ("TH7", "portero distinto del habitual (cuenta)", +1, th7),
                ("TH8", "descanso largo de los dos (3+ dias)", -1, lambda r, C: _ind((rest(C, r["home"], r["gp"]) or 0) >= 3 and (rest(C, r["away"], r["gp"]) or 0) >= 3))]
    defs_liga = ["NHL"]
    correr("NHL", lambda e: "NHL", nhl_defs())

    def bas_defs(liga):
        def rest(C, e, gp): return C.descanso(e, gp)
        def tk4(r, C):
            ph, pa = C.prev(r["home"], r["gp"]), C.prev(r["away"], r["gp"])
            if not ph or not pa or ph.get("ot") is None or pa.get("ot") is None: return None
            return _ind(ph["ot"]) + _ind(pa["ot"])
        D = [("TK1", "segunda noche (cuenta)", -1, lambda r, C: _ind(rest(C, r["home"], r["gp"]) == 1) + _ind(rest(C, r["away"], r["gp"]) == 1)),
             ("TK2", "tercer juego en 4 noches (cuenta)", -1, lambda r, C: _ind((C.en_ventana(r["home"], r["gp"], 3) or 0) >= 2) + _ind((C.en_ventana(r["away"], r["gp"], 3) or 0) >= 2)),
             ("TK4", "prorroga en el anterior (cuenta)", -1, tk4),
             ("TK5", "descanso largo de los dos (3+ dias)", +1, lambda r, C: _ind((rest(C, r["home"], r["gp"]) or 0) >= 3 and (rest(C, r["away"], r["gp"]) or 0) >= 3)),
             ("TK6", "gira del visitante 3+", -1, lambda r, C: _ind((C.visitas_seguidas(r["away"], r["gp"]) or 0) >= 3))]
        if liga == "NBA":
            D.insert(2, ("TK3", "altitud (Denver, Utah)", +1, lambda r, C: 1 if (r["home"] in ALT["NBA"] and r["away"] not in ALT["NBA"]) else 0))
        return D
    for lg in ("NBA", "NCAAMB"):
        defs_liga[0] = lg
        correr(lg, lambda e: lg, bas_defs(lg))

    # beisbol (7 ligas juntas, cada partido con su liga; el corte 70/30 es global por fecha)
    def tb2(r, C):
        ph, pa = C.prev(r["home"], r["gp"]), C.prev(r["away"], r["gp"])
        if not ph or not pa or ph["ip"] is None or pa["ip"] is None: return None
        return _ind(ph["ip"] >= 9.95) + _ind(pa["ip"] >= 9.95)
    bdefs = [("TB1", "Coors Field (MLB)", +1, lambda r, C: (1 if r["home"][1] == "Colorado Rockies" else 0) if r["liga"] == "MLB" else None),
             ("TB2", "extra innings en el anterior (cuenta)", +1, tb2),
             ("TB3", "dias seguidos jugando (suma/10)", +1, lambda r, C: (min(C.dias_seguidos(r["home"], r["gp"]) or 0, 20) + min(C.dias_seguidos(r["away"], r["gp"]) or 0, 20)) / 10.0),
             ("TB4", "los dos vienen de dia libre", -1, lambda r, C: _ind((C.descanso(r["home"], r["gp"]) or 0) >= 2 and (C.descanso(r["away"], r["gp"]) or 0) >= 2)),
             ("TB5", "gira del visitante 6+", +1, lambda r, C: _ind((C.visitas_seguidas(r["away"], r["gp"]) or 0) >= 6))]
    defs_liga[0] = "BEISBOL"
    correr("BEISBOL", lambda e: e[0] if isinstance(e, tuple) else "?", bdefs)

    # futbol
    ciud = json.load(_io.open(os.path.join(CODIGO, "trabajo", "minar", "ciudades_futbol.json"), encoding="utf-8"))["ciudades"]
    def ciudad(liga, e): return (ciud.get(liga) or {}).get(e)
    def derbi(r):
        a, b = ciudad(r["liga"], r["home"]), ciudad(r["liga"], r["away"])
        return None if a is None or b is None else _ind(a == b)
    def ch_reciente(C, e, gp):
        i = C.i(e, gp); f = C.t[e][i]["fecha"]
        return any(str(g["gp"]).startswith("ch") and 0 < (f - g["fecha"]).days <= 4 for g in C.t[e][max(0, i - 3):i])
    def ult_liga(C, e, gp):
        i = C.i(e, gp)
        return next((g for g in reversed(C.t[e][:i]) if g["gf"] is not None), None)
    def tf3(r, C):
        f = C.actual(r["home"], r["gp"])["fecha"]
        lh, la = ult_liga(C, r["home"], r["gp"]), ult_liga(C, r["away"], r["gp"])
        if not lh or not la: return None
        dh, da = (f - lh["fecha"]).days, (f - la["fecha"]).days
        return _ind(12 <= dh <= 30 and 12 <= da <= 30)
    def quedan(C, e, gp):
        i = C.i(e, gp); f = C.t[e][i]["fecha"]
        return sum(1 for g in C.t[e][i + 1:] if g["gf"] is not None and (g["fecha"] - f).days <= 60)
    def tf5(r, C):
        qh, qa = quedan(C, r["home"], r["gp"]), quedan(C, r["away"], r["gp"])
        return _ind(qh <= 4 and qa <= 4)
    fx = xcap.get(("F17", "5 ligas"), {})
    fdefs = [("TF1", "Champions entre semana (cuenta)", +1, lambda r, C: _ind(ch_reciente(C, r["home"], r["gp"])) + _ind(ch_reciente(C, r["away"], r["gp"]))),
             ("TF2", "descanso corto, 3 dias o menos (cuenta)", +1, lambda r, C: _ind((C.descanso(r["home"], r["gp"]) or 9) <= 3) + _ind((C.descanso(r["away"], r["gp"]) or 9) <= 3)),
             ("TF3", "regreso de fecha FIFA (los dos 12+ dias)", -1, tf3),
             ("TF4", "altitud en Liga MX", +1, lambda r, C: (1 if (r["home"] in ALT_MX and r["away"] not in ALT_MX) else 0) if r["liga"] == "LigaMX" else None),
             ("TF5", "ultimas 5 jornadas de los dos", +1, tf5),
             ("TF6", "pelea por no descender (F17 activo)", -1, lambda r, C: (_ind(fx.get(str(r["gp"])) not in (None, 0))) if r["liga"] in ("Premier", "LaLiga", "SerieA", "Bundesliga", "Ligue1") else None),
             ("TF7", "derbi (misma ciudad)", -1, lambda r, C: derbi(r))]
    defs_liga[0] = "7 ligas"
    liga_eq = {}
    for r in ULT["FUTBOL"][0]:
        liga_eq[r["home"]] = r["liga"]; liga_eq[r["away"]] = r["liga"]
    base_fut = correr("FUTBOL", lambda e: liga_eq.get(e, "FUT"), fdefs)

    # NFL / NCAAF
    def wd(r): return dt.date.fromisoformat(r["fecha"][:10]).weekday()
    q8 = xcap.get(("Q8", "NFL"), {}); n16 = xcap.get(("N16", "NFL"), {})
    def ndefs(liga):
        D = [("TN1", "jueves por la noche", -1, lambda r, C: _ind(wd(r) == 3)),
             ("TN2", "viene de semana libre (cuenta)", +1, lambda r, C: _ind(13 <= (C.descanso(r["home"], r["gp"]) or 0) <= 20) + _ind(13 <= (C.descanso(r["away"], r["gp"]) or 0) <= 20)),
             ("TN3", "semana corta, 5 dias o menos (cuenta)", -1, lambda r, C: _ind((C.descanso(r["home"], r["gp"]) or 9) <= 5) + _ind((C.descanso(r["away"], r["gp"]) or 9) <= 5))]
        if liga == "NFL":
            D += [("TN4", "sede neutral", -1, lambda r, C: n16.get(str(r["gp"]))),
                  ("TN5", "partido divisional", -1, lambda r, C: q8.get(str(r["gp"])))]
        return D
    for lg in ("NFL", "NCAAFB"):
        defs_liga[0] = lg
        correr(lg, lambda e: lg, ndefs(lg))

    # ---------------- contra el mercado: futbol Over 2.5 y NFL total_line
    print("\n  CONTRA EL CIERRE (O/U)")
    over = {}
    with _io.open(os.path.join(M.BASE, "datos", "mercado", "futbol_cuotas.csv"), encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            o, u = M._num(x.get("fd_PC_mas2.5")), M._num(x.get("fd_PC_menos2.5"))
            if not (o and u):
                o, u = M._num(x.get("fd_AvgC_mas2.5")), M._num(x.get("fd_AvgC_menos2.5"))
            if o and u:
                over[str(x["gamePk"])] = (1 / o) / (1 / o + 1 / u)
    filas, C = ULT["FUTBOL"]
    fr = {str(r["gp"]): r for r in filas}
    for cod, nom, s, fn in fdefs:
        rows = []
        for b in base_fut:
            pm = over.get(str(b["gp"]))
            if pm is None: continue
            try:
                x = fn(b["_r"], C)
            except (KeyError, TypeError):
                x = None
            if x is not None:
                rows.append(dict(fecha=b["fecha"], gp=b["gp"], p=pm, y=1 if b["T"] > 2.5 else 0, x=x))
        o = EV_REAL(rows, cod, nom + " [Over 2.5]", "7 ligas", s, base_nombre="cierre")
        if o: R.append(dict(o, mercado="over 2.5"))
    lin = {}
    with _io.open(os.path.join(M.BASE, "datos", "mercado", "nfl_lineas.csv"), encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            L, oo, uu = M._num(x.get("total_line")), M._num(x.get("over_odds")), M._num(x.get("under_odds"))
            if L is None: continue
            def dec(a): return None if a is None else (1 + a / 100 if a > 0 else 1 + 100 / abs(a))
            do, du = dec(oo) or 1.91, dec(uu) or 1.91
            lin[x["game_id"]] = (L, (1 / do) / (1 / do + 1 / du))
    filas, C = ULT["NFL"]
    for cod, nom, s, fn in ndefs("NFL"):
        rows = []
        for r in filas:
            g = C.actual(r["home"], r["gp"])
            if not g or g["gf"] is None: continue
            k = str(r["gp"])
            if k not in lin: continue
            L, pm = lin[k]; T = g["gf"] + g["ga"]
            if T == L: continue
            try:
                x = fn(r, C)
            except (KeyError, TypeError):
                x = None
            if x is not None:
                rows.append(dict(fecha=r["fecha"], gp=r["gp"], p=pm, y=1 if T > L else 0, x=x))
        o = EV_REAL(rows, cod, nom + " [total NFL]", "NFL", s, base_nombre="cierre")
        if o: R.append(dict(o, mercado="total NFL"))
    return R


# ------------------------------------------------------------------ D. nuevos
def parte_d(ULT, TEN):
    print("\n" + "=" * 100 + "\nD. NUEVOS: derbi (futbol) y jugador local (tenis)")
    R = []
    ciud = json.load(_io.open(os.path.join(CODIGO, "trabajo", "minar", "ciudades_futbol.json"), encoding="utf-8"))["ciudades"]
    filas, C = ULT["FUTBOL"]
    rows, rows_m = [], []
    for r in filas:
        a, b = (ciud.get(r["liga"]) or {}).get(r["home"]), (ciud.get(r["liga"]) or {}).get(r["away"])
        if a is None or b is None or r.get("paway") is None: continue
        x = (1 if r["p"] < r["paway"] else -1) if a == b else 0
        rows.append(dict(r, x=x))
        if r.get("pm"): rows_m.append(dict(r, x=x, p=r["pm"]))
    n_d = sum(1 for r in rows if r["x"]); print("  derbis en la muestra: %d de %d" % (n_d, len(rows)))
    o = EV_REAL(rows, "F18", "derbi: el no favorito", "7 ligas", +1)
    if o:
        b, se = offset_beta(rows); o["pp_50_toda"] = round(100 * (_sig(b) - .5), 2) if b is not None else None
        o["ic95_toda"] = [round(100 * (_sig(b - 1.96 * se) - .5), 2), round(100 * (_sig(b + 1.96 * se) - .5), 2)] if b is not None else None
        R.append(o)
    o = EV_REAL(rows_m, "F18", "derbi: el no favorito", "7 ligas", +1, base_nombre="cierre")
    if o: R.append(o)
    # tenis
    paises = json.load(_io.open(os.path.join(CODIGO, "trabajo", "minar", "paises_torneos.json"), encoding="utf-8"))["torneos"]
    info = {}
    with _io.open(os.path.join(M.BASE, "datos", "tenis.csv"), encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            info[r["tourney_id"] + "-" + str(r.get("match_num"))] = (r.get("tourney_name"), r.get("winner_name"), r.get("loser_name"),
                                                                    r.get("winner_ioc"), r.get("loser_ioc"))
    for tour in ("ATP", "WTA"):
        rows = []
        for r in TEN:
            if r["liga"] != tour: continue
            t = info.get(r["gp"])
            if not t: continue
            pais = paises.get(t[0])
            if not pais or not t[3] or not t[4]: continue
            w, l, iw, il = t[1], t[2], t[3], t[4]
            p1, p2 = (w, l) if w < l else (l, w)
            i1, i2 = (iw, il) if p1 == w else (il, iw)
            rows.append(dict(r, x=_ind(i1 == pais) - _ind(i2 == pais)))
        print("  %s: %d partidos con pais del torneo, %d con un solo local" % (tour, len(rows), sum(1 for r in rows if r["x"])))
        o = EV_REAL(rows, "T6", "jugador local", tour, +1)
        if o:
            b, se = offset_beta(rows); o["pp_50_toda"] = round(100 * (_sig(b) - .5), 2) if b is not None else None
            o["ic95_toda"] = [round(100 * (_sig(b - 1.96 * se) - .5), 2), round(100 * (_sig(b + 1.96 * se) - .5), 2)] if b is not None else None
            R.append(o)
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    if a.cache and os.path.exists(a.cache):
        D = pickle.load(open(a.cache, "rb")); print("filas leidas de", a.cache)
    else:
        D = capturar()
        if a.cache: pickle.dump(D, open(a.cache, "wb"))
    M.RESULTADOS.clear()
    A, tau = parte_a(D["cap"])
    B = parte_b(D["cap"])
    Cc = parte_c(D["cap"], D["ultimo"])
    Dd = parte_d(D["ultimo"], D["tenis"])
    nuevas = [r for r in B + Cc + Dd if "z" in r]
    pasan = [r for r in nuevas if r.get("veredicto") == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d pruebas nuevas con resultado | falsos 'pasa' esperados ~ %.1f | pasan: %d" % (len(nuevas), 0.023 * len(nuevas), len(pasan)))
    for r in pasan:
        print("  PASA %-5s %-44s %-12s %s z %+.2f" % (r["codigo"], r["angulo"][:44], r["liga"][:12], r.get("base"), r["z"]))
    out = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "hipotesis": "trabajo/minar/2026-10-09_tanda4.md",
           "k": len(nuevas), "falsos_esperados": round(0.023 * len(nuevas), 1), "tau_logit": round(tau, 4),
           "A_estimacion": A, "B_agrupados": B, "C_totales": Cc, "D_nuevos": Dd}
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-09_tanda4_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
