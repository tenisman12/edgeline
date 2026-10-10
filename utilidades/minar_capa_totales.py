# -*- coding: utf-8 -*-
"""
utilidades/minar_capa_totales.py - capa de totales sobre el modelo de cada deporte (hipotesis en
trabajo/minar/2026-10-09_capa_totales.md).

Corre el MISMO walk-forward de utilidades/validar_mercados.py, empezando --meses atras (48 por defecto), y captura por juego
el total del modelo, el real, la base oficial y los p_over por linea. Despues prueba tres capas ajustadas SOLO con
predicciones de bloques anteriores y califica los ultimos --calificar meses (24) con el criterio oficial (Rep.resultados):
  C1 total encogido      T* = a + b*T_modelo + c*M (M = media de totales de la liga con olvido, vida media 400 juegos)
  C2 over/under empirico p(over L) = fraccion de los ultimos 3000 residuos previos (real - T*) con T* + r > L
  C3 recalibracion       logit q = a + b*logit p_modelo
  C4 total con ritmo     T* = a + b*T_modelo + c*M + d*E (E = ritmo de los dos equipos: media con olvido del total de sus
                         juegos, vida media 20, encogido a M con 5 juegos) -- agregada despues de ver C1-C3
  C5 over/under de C4    igual que C2 con los residuos de C4
  C6 C4 + nivel reciente T* + media de los ultimos 300 residuos (agregada al ver la calibracion de LMP)
  C7 over/under de C6    residuos del ultimo ano (minimo 300), centrados en el nivel reciente

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_capa_totales.py --deporte hockey,nba,nfl,ncaamb,beisbol,futbol
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, math, os, pickle, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI); sys.path.insert(0, os.path.dirname(AQUI))
import validar_mercados as VM  # noqa: E402
from nucleo import io  # noqa: E402

VIDA_M = 400.0       # vida media (juegos) de la media de liga con olvido
VIDA_E = 20.0        # vida media (juegos del equipo) del ritmo de cada equipo (C4)
N_RES = 3000         # residuos previos que forman la distribucion de C2
MIN_PREV = 300       # predicciones previas minimas para ajustar la capa
CTX = {"key": None, "L": None, "fecha": None}
CAP = {}


# ------------------------------------------------------------------ captura
def _parchar():
    o_val, o_prob = VM.Rep.add_val, VM.Rep.add_prob

    def add_val(self, m, pred, real, base):
        if m == "Total esperado" and CTX["key"]:
            CAP[CTX["key"]].append({"t": "T", "pred": pred, "real": real, "base": base, "f": CTX["fecha"],
                                    "h": CTX.get("h"), "a": CTX.get("a")})
        return o_val(self, m, pred, real, base)

    def add_prob(self, m, p, y, base):
        if CTX["key"] and (m.startswith("Over/Under") or (m.startswith("Over ") and m.endswith("goles"))):
            L = CTX["L"] if m.startswith("Over/Under") else float(m.split()[1])
            ult = len(CAP[CTX["key"]]) - 1
            while ult >= 0 and CAP[CTX["key"]][ult]["t"] != "T":
                ult -= 1
            CAP[CTX["key"]].append({"t": "OU", "p": p, "y": y, "base": base, "L": L, "i": ult, "m": m})
        return o_prob(self, m, p, y, base)

    VM.Rep.add_val, VM.Rep.add_prob = add_val, add_prob


def _envolver_modulo(mod):
    if getattr(mod, "_capa_env", False):
        return
    o_pred, o_ent = mod.predecir, mod.entrenar

    def predecir(*a, **k):
        CTX["L"] = k.get("linea_total")
        if len(a) >= 3:
            CTX["h"], CTX["a"] = a[1], a[2]
        return o_pred(*a, **k)

    def entrenar(*a, **k):
        try:
            CTX["fecha"] = io.cargar_juegos.__defaults__[-1]
        except Exception:
            CTX["fecha"] = None
        return o_ent(*a, **k)

    mod.predecir, mod.entrenar, mod._capa_env = predecir, entrenar, True


def _envolver_beisbol():
    from modelos import beisbol as B
    if getattr(B, "_capa_env", False):
        return
    o_po, o_prob = B.prob_over, B.prob

    def prob_over(r, linea, *a, **k):
        CTX["L"] = linea
        return o_po(r, linea, *a, **k)

    def prob(modelo, r, *a, **k):
        CTX["fecha"] = (r.get("game_date") or "")[:10]
        CTX["h"], CTX["a"] = r.get("home"), r.get("away")
        return o_prob(modelo, r, *a, **k)

    B.prob_over, B.prob, B._capa_env = prob_over, prob, True


def capturar(deportes, meses, bloque, ligas_fut):
    _parchar()
    for d in deportes:
        if d == "beisbol":
            _envolver_beisbol()
            for lg in ("MLB", "NPB", "KBO", "LMP"):
                CTX["key"] = "beisbol_" + lg.lower(); CAP[CTX["key"]] = []
                VM.validar_beisbol(lg, meses, bloque)
        elif d == "futbol":
            _envolver_modulo(VM.CFG["futbol"]["mod"])
            for lg in ligas_fut:
                CTX["key"] = "futbol_" + lg.lower(); CAP[CTX["key"]] = []
                VM.validar_equipos("futbol", meses, bloque, lg)
        elif d in VM.CFG:
            _envolver_modulo(VM.CFG[d]["mod"])
            CTX["key"] = d; CAP[d] = []
            VM.validar_equipos(d, meses, bloque)
    CTX["key"] = None
    return CAP


# ------------------------------------------------------------------ capas
def _ols3(X, Y):
    """Minimos cuadrados con 3 columnas (1, x1, x2) por ecuaciones normales; si es singular, cae a (1, x1)."""
    import itertools
    n = len(X)
    A = [[0.0] * 3 for _ in range(3)]; b = [0.0] * 3
    for (x1, x2), y in zip(X, Y):
        v = (1.0, x1, x2)
        for i, j in itertools.product(range(3), range(3)):
            A[i][j] += v[i] * v[j]
        for i in range(3):
            b[i] += v[i] * y
    try:
        return _resolver(A, b)
    except ZeroDivisionError:
        A2 = [[A[0][0], A[0][1]], [A[1][0], A[1][1]]]; b2 = [b[0], b[1]]
        s = _resolver(A2, b2)
        return [s[0], s[1], 0.0]


def _ols(X, Y):
    k = len(X[0]); A = [[0.0] * k for _ in range(k)]; b = [0.0] * k
    for v, y in zip(X, Y):
        for i in range(k):
            b[i] += v[i] * y
            for j in range(k):
                A[i][j] += v[i] * v[j]
    for i in range(k):
        A[i][i] += 1e-6
    return _resolver(A, b)


def _resolver(A, b):
    n = len(b); M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-9:
            raise ZeroDivisionError
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _logistica(xs, ys, it=25):
    a, b = 0.0, 1.0
    for _ in range(it):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            q = _sig(a + b * x); w = q * (1 - q)
            g0 += y - q; g1 += (y - q) * x
            h00 += w; h01 += w * x; h11 += w * x * x
        h00 += 1e-6; h11 += 1e-6
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        a += (h11 * g0 - h01 * g1) / det; b += (h00 * g1 - h01 * g0) / det
    return a, b


def bloques(rows):
    """Asigna bloque a cada fila T (cambia la base oficial = cambia el bloque) y la media M con olvido as-of por bloque."""
    T = [r for r in rows if r["t"] == "T"]
    blk, prev_base = -1, None
    for r in T:
        if r["base"] != prev_base:
            blk += 1; prev_base = r["base"]
        r["b"] = blk
    # M as-of: media con olvido de los totales de bloques anteriores
    lam = 0.5 ** (1.0 / VIDA_M)
    num = den = 0.0; actual = 0; buf = []
    for r in T:
        if r["b"] != actual:
            for x in buf:
                num = lam * num + x; den = lam * den + 1
            buf = []; actual = r["b"]
        r["M"] = num / den if den else r["base"]
        buf.append(r["real"])
    # E as-of por bloque: ritmo de cada equipo = media con olvido del total de sus juegos (bloques anteriores)
    lam_e = 0.5 ** (1.0 / VIDA_E)
    eq = {}; actual = 0; buf = []
    for r in T:
        if r["b"] != actual:
            for x in buf:
                for t in (x.get("h"), x.get("a")):
                    n_, d_ = eq.get(t, (0.0, 0.0)); eq[t] = (lam_e * n_ + x["real"], lam_e * d_ + 1)
            buf = []; actual = r["b"]

        def ritmo(t, M=r["M"]):
            n_, d_ = eq.get(t, (0.0, 0.0))
            k = d_ / (d_ + 5.0)        # encogido a la media de la liga con 5 juegos de peso
            return k * (n_ / d_ if d_ else M) + (1 - k) * M
        r["E"] = ritmo(r.get("h")) + ritmo(r.get("a")) - r["M"]
        buf.append(r)
    return T


def evaluar(clave, rows, meses_cal, ultimo_cal):
    T = bloques(rows)
    if not T:
        return None
    OU = [r for r in rows if r["t"] == "OU"]
    idx = {id(r): k for k, r in enumerate(rows)}
    pos_T = {k: r for k, r in enumerate(rows) if r["t"] == "T"}
    nb = max(r["b"] for r in T) + 1
    fechas_b = {}
    for r in T:
        if r.get("f"):
            fechas_b.setdefault(r["b"], r["f"])
    fin = max((f for f in fechas_b.values() if f), default=None)
    corte = (dt.date.fromisoformat(fin[:10]) - dt.timedelta(days=int(meses_cal * 30.4))).isoformat() if fin else None
    out = {"C0": VM.Rep(), "C1": VM.Rep(), "C2": VM.Rep(), "C3": VM.Rep(), "C4": VM.Rep(), "C5": VM.Rep(), "C6": VM.Rep(), "C7": VM.Rep()}
    coef_ult = None
    for b in range(nb):
        prev = [r for r in T if r["b"] < b]
        cur = [r for r in T if r["b"] == b]
        fb = fechas_b.get(b)
        if len(prev) < MIN_PREV or not cur or (corte and fb and fb < corte):
            # fuera de la ventana calificada, pero sus predicciones (ya con la capa) alimentan residuos
            continue
        a0, b1, c2 = _ols3([(r["pred"], r["M"]) for r in prev], [r["real"] for r in prev])
        coef_ult = (a0, b1, c2)
        q = _ols([(1.0, r["pred"], r["M"], r["E"]) for r in prev], [r["real"] for r in prev])
        res_all = [r["real"] - sum(c * v for c, v in zip(q, (1.0, r["pred"], r["M"], r["E"]))) for r in prev]
        res4 = res_all[-N_RES:]
        # C6: nivel reciente (media de los ultimos 300 residuos); C7: residuos del ultimo ano (minimo 300)
        nivel = sum(res_all[-300:]) / len(res_all[-300:])
        f_fin = max((r["f"] for r in prev if r.get("f")), default=None)
        if f_fin:
            lim = (dt.date.fromisoformat(f_fin[:10]) - dt.timedelta(days=365)).isoformat()
            res7 = [e - nivel for e, r in zip(res_all, prev) if (r.get("f") or "") >= lim]
        else:
            res7 = []
        if len(res7) < 300:
            res7 = [e - nivel for e in res_all[-300:]]
        res = [r["real"] - (a0 + b1 * r["pred"] + c2 * r["M"]) for r in prev][-N_RES:]
        prevOU = [o for o in OU if pos_T.get(o["i"]) is not None and pos_T[o["i"]]["b"] < b]
        la, lb = _logistica([_logit(o["p"]) for o in prevOU], [o["y"] for o in prevOU]) if len(prevOU) >= MIN_PREV else (0.0, 1.0)
        ids = {id(r) for r in cur}
        for r in cur:
            ts = a0 + b1 * r["pred"] + c2 * r["M"]
            r["ts"] = ts
            out["C0"].add_val("Total esperado", r["pred"], r["real"], r["base"])
            out["C1"].add_val("Total esperado", ts, r["real"], r["base"])
            r["t4"] = sum(c * v for c, v in zip(q, (1.0, r["pred"], r["M"], r["E"])))
            out["C4"].add_val("Total esperado", r["t4"], r["real"], r["base"])
            r["t6"] = r["t4"] + nivel
            out["C6"].add_val("Total esperado", r["t6"], r["real"], r["base"])
        for o in OU:
            t = pos_T.get(o["i"])
            if t is None or id(t) not in ids or o["L"] is None:
                continue
            m = o["m"]
            out["C0"].add_prob(m, o["p"], o["y"], o["base"])
            pe = sum(1 for e in res if t["ts"] + e > o["L"]) / len(res)
            out["C2"].add_prob(m, pe, o["y"], o["base"])
            out["C3"].add_prob(m, _sig(la + lb * _logit(o["p"])), o["y"], o["base"])
            out["C5"].add_prob(m, sum(1 for e in res4 if t["t4"] + e > o["L"]) / len(res4), o["y"], o["base"])
            out["C7"].add_prob(m, sum(1 for e in res7 if t["t6"] + e > o["L"]) / len(res7), o["y"], o["base"])
    R = {k: v.resultados() for k, v in out.items()}
    return {"resultados": R, "coef_ultimo": coef_ult, "desde": corte, "hasta": fin}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", default="hockey,nba,nfl,ncaamb,beisbol,futbol")
    ap.add_argument("--meses", type=int, default=48)
    ap.add_argument("--calificar", type=int, default=24)
    ap.add_argument("--bloque", type=int, default=30)
    ap.add_argument("--ligas", default="premier,laliga,seriea,bundesliga,ligue1,ligamx,mls")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--salida", default=os.path.join(os.path.dirname(AQUI), "trabajo", "minar", "2026-10-09_capa_totales_resultados.json"))
    a = ap.parse_args()
    deps = [x.strip() for x in a.deporte.split(",") if x.strip()]
    if a.cache and os.path.exists(a.cache):
        C = pickle.load(open(a.cache, "rb"))
    else:
        C = capturar(deps, a.meses, a.bloque, [x.strip() for x in a.ligas.split(",") if x.strip()])
        if a.cache:
            pickle.dump(C, open(a.cache, "wb"))
    Z = {}
    k = 0
    for clave, rows in C.items():
        r = evaluar(clave, rows, a.calificar, None)
        if not r:
            continue
        Z[clave] = r
        print("\n=== %s (calificado %s a %s; coef. ultimo bloque a, b, c = %s)" % (
            clave, r["desde"], r["hasta"], ", ".join("%.3f" % x for x in r["coef_ultimo"]) if r["coef_ultimo"] else "-"))
        for cap in ("C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7"):
            for m, x in r["resultados"][cap].items():
                if cap != "C0":
                    k += 1
                print("  %s %-30s n %5d  skill %+.4f  z %5.2f  %s  %s" % (
                    cap, m, x["n"], x["skill"], x["z"],
                    ("sesgo %+.3f" % x["sesgo"]) if x["tipo"] == "conteo" else ("p %.3f vs %.3f" % (x["p_media"], x["tasa_real"])),
                    x["estado"]))
    print("\nk = %d pruebas (C1-C7); falsos 'pasa' esperados ~ %.1f" % (k, 0.023 * k))
    json.dump({"generado": dt.datetime.now().isoformat(timespec="minutes"), "k": k, "deportes": Z},
              open(a.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("escrito", a.salida)


if __name__ == "__main__":
    main()
