# -*- coding: utf-8 -*-
"""
utilidades/validar_mercados.py - MISMA validacion para TODOS los deportes y TODOS los mercados.

Para cada deporte hace walk-forward sin fuga: parte los ultimos N meses en bloques, entrena el
modelo SOLO con juegos anteriores al bloque (mismo entrenar()/predecir() que usa la plataforma)
y predice los juegos del bloque. Compara contra una linea base sin modelo (frecuencia historica
previa / promedio previo) y reporta la mejora.

Mercados que evalua
  hockey    ganador, total goles (esperado y over/under), puck line +-1.5
  nfl       ganador, margen y spread, total puntos (esperado y over/under)
  nba       ganador, margen y spread, total puntos (esperado y over/under)
  futbol    1X2, total goles (esperado y over 1.5/2.5/3.5), handicap +-0.5/+-1.5
  tenis     ganador, total de games (3 y 5 sets por separado), sets corridos, breaks;
            por circuito (ATP/WTA)
  beisbol   (opcional --beisbol) totales y run line con nucleo.evaluar

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\validar_mercados.py                       (todos)
    python utilidades\\validar_mercados.py --deporte tenis,nba
    python utilidades\\validar_mercados.py --meses 18 --bloque 30
    python utilidades\\validar_mercados.py --beisbol
Lectura: Brier / MAE mas bajo es mejor; "mejora" = cuanto le gana a la linea base.
"""
import argparse, csv, datetime as dt, io as _io, math, os, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
from nucleo import io
from modelos import hockey, americano, nba, futbol, tenis as T
from nucleo import capa_totales as CT


# ------------------------------------------------------------------ metricas
def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


RESULT = {}
AJUSTES = {}      # circuito -> {formato: sesgo de games vigente al final de la validacion}
AJUSTES_BR = {}   # circuito -> {formato: sesgo de breaks vigente al final de la validacion}
RESB = {}         # (circuito, formato) -> residuos de breaks (real - modelo), en orden
Z_MIN = 2.0; CAL_MAX = 0.04
PRECAL = 24       # meses de precalentamiento ANTES de la ventana calificada: solo sirven para que la capa de totales
                  # (nucleo/capa_totales.py) tenga predicciones previas con que ajustarse; no entran a ningun mercado


def brier(P):  return sum((p - y) ** 2 for p, y, *_ in P) / len(P)
def brier_base(P): return sum((b - y) ** 2 for _, y, b in P) / len(P)


class Rep:
    """Acumula registros por mercado e imprime la tabla."""
    def __init__(self):
        self.prob = {}     # mercado -> [(p, y, p_base)]
        self.val = {}      # mercado -> [(pred, real, base)]
        self.multi = {}    # mercado -> [((p...), idx_real, (base...))]
        self.orden = []

    def _reg(self, m):
        if m not in self.orden: self.orden.append(m)

    def add_prob(self, m, p, y, base):
        self._reg(m); self.prob.setdefault(m, []).append((min(max(p, 1e-6), 1 - 1e-6), y, base))

    def add_val(self, m, pred, real, base):
        self._reg(m); self.val.setdefault(m, []).append((pred, real, base))

    def add_multi(self, m, ps, idx, base):
        self._reg(m); self.multi.setdefault(m, []).append((ps, idx, base))

    def resultados(self):
        """Estado de cada mercado con el criterio estricto: n>=300, mejora a la base, z>=2.0 (error pareado),
        mejora en las DOS mitades de la ventana, y calibrado (prob.) / sin sesgo grande (conteos)."""
        out = {}
        def est(d, n, extra_ok=True):
            md = sum(d) / n; sd = math.sqrt(sum((x - md) ** 2 for x in d) / max(n - 1, 1))
            z = md / (sd / math.sqrt(n)) if sd > 0 else 0.0
            h = n // 2; m1 = sum(d[:h]) / max(h, 1); m2 = sum(d[h:]) / max(n - h, 1)
            ok = n >= 300 and md > 0 and z >= Z_MIN and m1 > 0 and m2 > 0 and extra_ok
            return round(z, 2), ("publicable" if ok else "sin_validar"), m1 > 0 and m2 > 0
        for m in self.orden:
            if m in self.prob:
                P = self.prob[m]; n = len(P)
                d = [(b - y) ** 2 - (p - y) ** 2 for p, y, b in P]
                bm, bb = brier(P), brier_base(P)
                pm = sum(p for p, _, _ in P) / n; fr = sum(y for _, y, _ in P) / n
                z, e, dos = est(d, n, abs(pm - fr) <= CAL_MAX)
                out[m] = {"tipo": "prob", "n": n, "skill": round(1 - bm / bb, 4) if bb else 0, "z": z,
                          "p_media": round(pm, 3), "tasa_real": round(fr, 3), "dos_mitades": dos, "estado": e}
            elif m in self.val:
                V = self.val[m]; n = len(V)
                d = [abs(b - r) - abs(a - r) for a, r, b in V]
                mm = sum(abs(a - r) for a, r, _ in V) / n; mb = sum(abs(b - r) for _, r, b in V) / n
                sesgo = sum(a - r for a, r, _ in V) / n
                sd = math.sqrt(sum((a - r - sesgo) ** 2 for a, r, _ in V) / max(n - 1, 1))
                z, e, dos = est(d, n, abs(sesgo) <= 0.10 * sd)
                out[m] = {"tipo": "conteo", "n": n, "skill": round(1 - mm / mb, 4) if mb else 0, "z": z,
                          "sesgo": round(sesgo, 3), "dos_mitades": dos, "estado": e}
        return out

    def imprimir(self, titulo, clave=None):
        ST = {}
        if clave:
            RESULT[clave] = self.resultados()
            ST = {m: r["estado"] for m, r in RESULT[clave].items()}
        print("\n" + "=" * 92); print(titulo); print("=" * 92)
        print("%-34s %6s %9s %9s %9s   %s" % ("MERCADO", "n", "MODELO", "BASE", "MEJORA", "detalle"))
        print("-" * 92)
        for m in self.orden:
            if m in self.prob:
                P = self.prob[m]; n = len(P)
                bm, bb = brier(P), brier_base(P)
                acc = sum(1 for p, y, _ in P if (p >= .5) == (y == 1)) / n
                pm = sum(p for p, _, _ in P) / n; fr = sum(y for _, y, _ in P) / n
                print("%-34s %6d %9.4f %9.4f %8.1f%%   acierto %.1f%% | p prom %.3f vs real %.3f | %s" % (
                    m + " (Brier)", n, bm, bb, 100 * (bb - bm) / bb if bb else 0, 100 * acc, pm, fr, ST.get(m, "")))
            elif m in self.val:
                V = self.val[m]; n = len(V)
                mm = sum(abs(a - r) for a, r, _ in V) / n; mb = sum(abs(b - r) for _, r, b in V) / n
                sesgo = sum(a - r for a, r, _ in V) / n
                sd = math.sqrt(sum((a - r - sesgo) ** 2 for a, r, _ in V) / max(n - 1, 1))
                print("%-34s %6d %9.3f %9.3f %8.1f%%   sesgo %+.3f | desv. residual %.2f | %s" % (
                    m + " (MAE)", n, mm, mb, 100 * (mb - mm) / mb if mb else 0, sesgo, sd, ST.get(m, "")))
            elif m in self.multi:
                M = self.multi[m]; n = len(M)
                def br(ps, i): return sum((p - (1 if k == i else 0)) ** 2 for k, p in enumerate(ps))
                bm = sum(br(ps, i) for ps, i, _ in M) / n; bb = sum(br(b, i) for _, i, b in M) / n
                acc = sum(1 for ps, i, _ in M if max(range(len(ps)), key=lambda k: ps[k]) == i) / n
                print("%-34s %6d %9.4f %9.4f %8.1f%%   acierto %.1f%%" % (
                    m + " (Brier)", n, bm, bb, 100 * (bb - bm) / bb if bb else 0, 100 * acc))
        print("-" * 92)


# ------------------------------------------------------------------ deportes de equipos
CFG = {
    "hockey":  {"mod": hockey,   "dep": "hockey",    "ms": (("goals", "goals_opp"),), "total_step": 1.0, "spread": (),            "titulo": "HOCKEY (NHL)"},
    # OJO (6-oct-2026): nfl y nba NO tenian clave "liga", asi que _juegos(None) cargaba las DOS ligas del archivo
    # juntas (NFL+NCAAF y NBA+NCAA basquet). Eso mezclaba el promedio de anotacion de la liga (NBA ~225 de total,
    # NCAA ~147) e inflaba la linea base: el MAE base del total de "NBA" salia en 29.3 y de ahi el +50% de skill,
    # que era un artefacto de la mezcla, no ventaja. Ahora cada una entrena con su liga.
    "nfl":     {"mod": americano, "dep": "americano", "ms": (("points", "points_opp"),), "total_step": 6.0, "spread": (-6.5, -2.5, 2.5, 6.5), "titulo": "NFL", "liga": "NFL"},
    "nba":     {"mod": nba,      "dep": "nba",       "ms": (("points", "points_opp"),), "total_step": 8.0, "spread": (-8.5, -4.5, 0.5, 4.5, 8.5), "titulo": "NBA", "liga": "NBA"},
    "ncaafb":  {"mod": americano, "dep": "americano", "ms": (("points", "points_opp"),), "total_step": 6.0, "spread": (-10.5, -6.5, -2.5, 2.5, 6.5, 10.5), "titulo": "NCAA FUTBOL AMERICANO", "liga": "NCAAFB"},
    "ncaamb":  {"mod": nba,      "dep": "nba",       "ms": (("points", "points_opp"),), "total_step": 8.0, "spread": (-8.5, -4.5, 0.5, 4.5, 8.5), "titulo": "NCAA BASQUET", "liga": "NCAAMB"},
    "futbol":  {"mod": futbol,   "dep": "futbol",    "ms": (("goals", "goals_opp"),), "total_step": 1.0, "spread": (),            "titulo": "FUTBOL (5 ligas)"},
}


def evaluar_capa(rep, filas, clave, unidad_cal=True):
    """Capa de totales walk-forward: en cada bloque calificado ajusta T* = a + b*T + c*M + d*E + nivel solo con los bloques
    anteriores (precalentamiento incluido) y agrega 'Total esperado (capa)' y 'Over/Under (capa)' al reporte
    (nucleo/capa_totales.py; C6 + C7 de trabajo/minar/2026-10-09_capa_totales.md)."""
    bloques = sorted({x["b"] for x in filas})
    for b in bloques:
        cur = [x for x in filas if x["b"] == b]
        if not cur or not cur[0]["cal"]:
            continue
        prev = [x for x in filas if x["b"] < b]
        if len(prev) < CT.MIN_PREV:
            continue
        coef, res = CT.entrenar([(x["pred"], x["real"], x["M"], x["E"], x["f"]) for x in prev])
        for x in cur:
            t = CT.total(coef, x["pred"], x["M"], x["E"])
            rep.add_val("Total esperado (capa)", t, x["real"], x["base"])
            for L, y, fr in x["ou"]:
                rep.add_prob("Over/Under (capa)", CT.p_over(res, t, L), y, fr)


def guardar_capa(filas, clave):
    """Coeficientes y residuos de toda la muestra (precalentamiento + ventana) -> modelos/capa_totales.json."""
    if len(filas) < CT.MIN_PREV:
        return
    coef, res = CT.entrenar([(x["pred"], x["real"], x["M"], x["E"], x["f"]) for x in filas])
    est = ((RESULT.get(clave) or {}).get("Over/Under (capa)") or {}).get("estado", "sin_validar")
    CT.guardar(io.BASE, clave, coef, res, len(filas), min(x["f"] for x in filas), max(x["f"] for x in filas), est)


def marcador(h, campos):
    for a, b in campos:
        x, y = _f(h.get(a)), _f(h.get(b))
        if x is not None and y is not None:
            return x, y
    return None


def medio(x): return math.floor(x) + 0.5


def validar_equipos(clave, meses, bloque, liga=None):
    c = dict(CFG[clave]); mod = c["mod"]
    clave_json = clave if clave != "futbol" else "futbol_" + str(liga).lower()
    liga = liga or c.get("liga")
    if liga and clave == "futbol": c["titulo"] = "FUTBOL %s" % liga.upper()
    todos = mod._juegos(liga)
    G = []
    for f, gp, h, a in todos:
        m = marcador(h, c["ms"])
        if m: G.append((f, gp, h, a, m[0], m[1]))
    if len(G) < 500:
        print("\n%s: muestra insuficiente (%d juegos)." % (c["titulo"], len(G))); return
    ultimo = dt.date.fromisoformat(G[-1][0]); ini = ultimo - dt.timedelta(days=int(meses * 30.4))
    fechas = sorted({g[0] for g in G if g[0] >= ini.isoformat()})
    if not fechas:
        print("\n%s: sin juegos en la ventana." % c["titulo"]); return
    rep = Rep(); orig = io.cargar_juegos
    d_cal = dt.date.fromisoformat(fechas[0])
    con_capa = clave != "futbol" and PRECAL > 0
    n_pre = int(math.ceil(PRECAL * 30.4 / bloque)) if con_capa else 0
    d0 = d_cal - dt.timedelta(days=bloque * n_pre); nbl = 0; nb_tot = 0
    capa, ritmo = [], (CT.Ritmo([(g[0], g[2].get("team"), g[3].get("team"), g[4] + g[5]) for g in G]) if con_capa else None)
    rep_cal = rep
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=bloque)
        blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
        prev = [g for g in G if g[0] < d0.isoformat()]
        cal = d0 >= d_cal
        rep = rep_cal if cal else Rep()          # precalentamiento: a un reporte que se tira
        if blk and len(prev) >= 300:
            corte = d0.isoformat()
            io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [
                r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
            try:
                est = mod.entrenar(liga)
            finally:
                io.cargar_juegos = orig
            nbl += 1 if cal else 0; nb_tot += 1
            tot_prev = [g[4] + g[5] for g in prev]; mar_prev = [g[4] - g[5] for g in prev]
            base_tot = sum(tot_prev) / len(tot_prev); base_mar = sum(mar_prev) / len(mar_prev)
            hw = sum(1 for g in prev if g[4] > g[5]) / len(prev)
            d_prev = sum(1 for g in prev if g[4] == g[5]) / len(prev)
            a_prev = 1 - hw - d_prev
            lineas = [medio(base_tot + k * c["total_step"]) for k in (-1, 0, 1)]
            fr_over = {L: sum(1 for t in tot_prev if t > L) / len(tot_prev) for L in lineas}
            for f, gp, h, a, gh, ga in blk:
                th, ta = h.get("team"), a.get("team")
                if clave == "hockey":
                    r = mod.predecir(est, th, ta, linea_total=lineas[1])
                elif clave == "futbol":
                    r = mod.predecir(est, th, ta, linea_total=2.5, handicap=0.0)
                else:
                    r = mod.predecir(est, th, ta, linea_total=lineas[1], linea_spread=0.0)
                if not r: continue
                tot = gh + ga; mar = gh - ga
                if clave == "futbol":
                    real = 0 if gh > ga else (1 if gh == ga else 2)
                    rep.add_multi("1X2", (r["p_home"], r["p_draw"], r["p_away"]), real, (hw, d_prev, a_prev))
                    rep.add_prob("Local gana (sin empate)", r["p_home"], 1 if gh > ga else 0, hw)
                else:
                    rep.add_prob("Ganador", r["p_home"], 1 if gh > ga else 0, hw)
                tp = r.get("total") if clave == "hockey" else r.get("total_esperado")
                rep.add_val("Total esperado", tp, tot, base_tot)
                fila_capa = None
                if con_capa and tp is not None:
                    st = ritmo.estado(f, th, ta)
                    if st:
                        fila_capa = {"b": nb_tot, "cal": cal, "f": f, "pred": tp, "real": tot, "base": base_tot,
                                     "M": st[0], "E": st[1], "ou": []}
                        capa.append(fila_capa)
                if clave in ("nfl", "nba"):
                    rep.add_val("Margen esperado (local)", r["margen_esperado"], mar, base_mar)
                if clave == "hockey":
                    rep.add_val("Goles local esperados", r["xg_home"], gh, sum(g[4] for g in prev) / len(prev))
                    rep.add_val("Goles visita esperados", r["xg_away"], ga, sum(g[5] for g in prev) / len(prev))
                if clave == "futbol":
                    for L in (1.5, 2.5, 3.5):
                        rr = mod.predecir(est, th, ta, linea_total=L, handicap=0.0)
                        fb = sum(1 for t in tot_prev if t > L) / len(tot_prev)
                        rep.add_prob("Over %.1f goles" % L, rr["p_over"], 1 if tot > L else 0, fb)
                    for hd in (-1.5, -0.5, 0.5, 1.5):
                        rr = mod.predecir(est, th, ta, linea_total=2.5, handicap=hd)
                        fb = sum(1 for m_ in mar_prev if m_ + hd > 0) / len(mar_prev)
                        rep.add_prob("Handicap local %+.1f" % hd, rr["p_handicap_home"], 1 if mar + hd > 0 else 0, fb)
                else:
                    for L in lineas:
                        rr = mod.predecir(est, th, ta, linea_total=L) if clave == "hockey" else \
                            mod.predecir(est, th, ta, linea_total=L, linea_spread=None)
                        rep.add_prob("Over/Under (lineas ~promedio)", rr["p_over"], 1 if tot > L else 0, fr_over[L])
                        if fila_capa is not None:
                            fila_capa["ou"].append((L, 1 if tot > L else 0, fr_over[L]))
                if clave == "hockey":
                    rep.add_prob("Puck line local -1.5", r["p_pl_home"], 1 if mar >= 2 else 0,
                                 sum(1 for m_ in mar_prev if m_ >= 2) / len(mar_prev))
                    rep.add_prob("Puck line visita +1.5", r["p_pl_away"], 1 if mar < 2 else 0,
                                 sum(1 for m_ in mar_prev if m_ < 2) / len(mar_prev))
                for s in c["spread"]:
                    rr = mod.predecir(est, th, ta, linea_total=None, linea_spread=float(s))
                    fb = sum(1 for m_ in mar_prev if m_ > s) / len(mar_prev)
                    rep.add_prob("Local cubre margen > %+g" % s, rr["p_cubre_home"], 1 if mar > s else 0, fb)
        d0 = d1
    rep = rep_cal
    if con_capa:
        evaluar_capa(rep, capa, clave_json)
    rep.imprimir("%s | ultimos %d meses, %d bloques de %d dias, entrenando solo con lo anterior%s" % (
        c["titulo"], meses, nbl, bloque, (" (capa de totales con %d meses previos de precalentamiento)" % PRECAL) if con_capa else ""), clave=clave_json)
    if con_capa:
        guardar_capa(capa, clave_json)


# ------------------------------------------------------------------ beisbol (MLB, NPB, KBO, ligas de invierno)
def validar_beisbol(liga, meses, bloque):
    """Walk-forward de beisbol con el mismo criterio que los demas deportes: Ganador (logistica entrenada solo con lo
    anterior), Total esperado, Over/Under en lineas ~promedio, Run line local -1.5 / visita +1.5 y run line a la linea
    del favorito. Escribe RESULT["beisbol_<liga>"]; plataforma lo lee para MLB/NPB/KBO."""
    from nucleo import features as F
    from modelos import beisbol as B
    feats, _ = F.construir("beisbol", liga, 5)
    lg = io.norm(liga)
    G = [r for r in feats if r["league"] == lg and r.get("y_home") is not None and r.get("total") is not None]
    G.sort(key=lambda r: r["game_date"])
    if len(G) < 500:
        print("\nBEISBOL %s: muestra insuficiente (%d juegos)." % (liga, len(G))); return
    ultimo = dt.date.fromisoformat(G[-1]["game_date"][:10]); ini = ultimo - dt.timedelta(days=int(meses * 30.4))
    from nucleo import abridores as AB
    VAB = AB.historicos(io.BASE, lg) if AB.aplica(lg) else {}
    K_AB, ESC_AB = AB.coeficientes(lg)
    from nucleo import parques as PQ
    VPQ = PQ.historicos(io.BASE, lg) if PQ.aplica(lg) else {}
    rep = Rep(); d_cal = max(ini, dt.date.fromisoformat(G[0]["game_date"][:10])); nbl = 0; nb_tot = 0
    n_pre = int(math.ceil(PRECAL * 30.4 / bloque)) if PRECAL > 0 else 0
    d0 = max(d_cal - dt.timedelta(days=bloque * n_pre), dt.date.fromisoformat(G[0]["game_date"][:10]))
    if d0 < d_cal:          # que los bloques de la ventana calificada empiecen donde empezaban sin precalentamiento
        d0 = d_cal - dt.timedelta(days=bloque * ((d_cal - d0).days // bloque))
    capa = []; ritmo = CT.Ritmo([(r["game_date"], r["home"], r["away"], r["total"]) for r in G]) if PRECAL > 0 else None
    rep_cal = rep
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=bloque)
        blk = [r for r in G if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in G if r["game_date"][:10] < d0.isoformat()]
        cal = d0 >= d_cal
        rep = rep_cal if cal else Rep()
        if blk and len(prev) >= 300:
            modelo = B.entrenar_logistica(prev)
            if modelo:
                nbl += 1 if cal else 0; nb_tot += 1
                tot_prev = [r["total"] for r in prev]; mar_prev = [r["marg_home"] for r in prev]
                base_tot = sum(tot_prev) / len(tot_prev); hw = sum(r["y_home"] for r in prev) / len(prev)
                lineas = [medio(base_tot + k) for k in (-1, 0, 1)]
                fr_over = {L: sum(1 for t in tot_prev if t > L) / len(tot_prev) for L in lineas}
                fb_rl = sum(1 for m_ in mar_prev if m_ >= 2) / len(mar_prev)
                for r in blk:
                    p = B.prob(modelo, r)
                    xh, xa = B.carreras_esperadas(r)
                    if xh is None: continue
                    if B.COHERENTE:
                        xh, xa = B.ajustar_carreras(xh, xa, p)
                    if VAB:
                        # capa de abridores de KBO (nucleo/abridores.py, medida en utilidades/medir_abridores_kbo.py)
                        vh, va = VAB.get((r["gamePk"], r["home"])), VAB.get((r["gamePk"], r["away"]))
                        if vh and va:
                            sh, sa = AB.carreras_salvadas(r.get("df_home"), vh), AB.carreras_salvadas(r.get("df_away"), va)
                            p = 1 / (1 + math.exp(-(math.log(p / (1 - p)) + K_AB * (sh - sa))))
                            xh, xa = max(xh - ESC_AB * sa, 0.5), max(xa - ESC_AB * sh, 0.5)
                    if VPQ:
                        # capa de parque y clima (nucleo/parques.py, medida en utilidades/capas_totales_beisbol.py):
                        # el total del modelo no sabia donde se juega. Solo toca el total, no el ganador.
                        v = VPQ.get((r["gamePk"], r["home"]))
                        if v:
                            xh, xa = PQ.ajustar(xh, xa, lg, v[0], v[1], v[2])
                    tot, mar = r["total"], r["marg_home"]
                    rep.add_prob("Ganador", p, r["y_home"], hw)
                    rep.add_val("Total esperado", xh + xa, tot, base_tot)
                    fila_capa = None
                    if ritmo is not None:
                        st = ritmo.estado(r["game_date"][:10], r["home"], r["away"])
                        if st:
                            fila_capa = {"b": nb_tot, "cal": cal, "f": r["game_date"][:10], "pred": xh + xa, "real": tot,
                                         "base": base_tot, "M": st[0], "E": st[1], "ou": []}
                            capa.append(fila_capa)
                    for L in lineas:
                        po, _ = B.prob_over(r, L, xh, xa)
                        if po is not None and tot != L:
                            rep.add_prob("Over/Under (lineas ~promedio)", po, 1 if tot > L else 0, fr_over[L])
                            if fila_capa is not None:
                                fila_capa["ou"].append((L, 1 if tot > L else 0, fr_over[L]))
                    rlh, rla = B.prob_run_line(r, 1.5, xh=xh, xa=xa)
                    if rlh is not None:
                        rep.add_prob("Run line local -1.5", rlh, 1 if mar >= 2 else 0, fb_rl)
                        rep.add_prob("Run line visita +1.5", rla, 1 if mar < 2 else 0, 1 - fb_rl)
                        # run line del FAVORITO del modelo (lo que cotiza la casa): -1.5 al favorito
                        if p >= 0.5:
                            rep.add_prob("Run line favorito -1.5", rlh, 1 if mar >= 2 else 0, fb_rl)
                        else:
                            fa = sum(1 for m_ in mar_prev if m_ <= -2) / len(mar_prev)
                            pf = sum(B._nb_pmf(i, xa) * B._nb_pmf(j, xh) for i in range(20) for j in range(20) if i - j >= 2)
                            rep.add_prob("Run line favorito -1.5", pf, 1 if mar <= -2 else 0, fa)
        d0 = d1
    rep = rep_cal
    if ritmo is not None:
        evaluar_capa(rep, capa, "beisbol_" + lg.lower())
    rep.imprimir("BEISBOL %s | ultimos %d meses, %d bloques de %d dias, entrenando solo con lo anterior%s" % (
        liga.upper(), meses, nbl, bloque, (" (capa de totales con %d meses previos de precalentamiento)" % PRECAL) if ritmo is not None else ""),
        clave="beisbol_" + lg.lower())
    if ritmo is not None:
        guardar_capa(capa, "beisbol_" + lg.lower())


# ------------------------------------------------------------------ tenis
def _games_sets(score):
    """-> (games, sets, completo). Marcadores con RET/W/O/DEF no se usan."""
    s = (score or "").strip()
    if not s or any(ch.isalpha() for ch in s):
        return None, None, False
    g = ns = 0
    for tok in s.split():
        tok = tok.split("(")[0]
        if "-" not in tok: return None, None, False
        a, b = tok.split("-", 1)
        try: g += int(a) + int(b); ns += 1
        except ValueError: return None, None, False
    return g, ns, True


def validar_tenis(meses, min_j=10):
    ruta = os.path.join(io.BASE, "datos", "tenis.csv")
    if not os.path.exists(ruta):
        print("\nTENIS: falta datos\\tenis.csv"); return
    with _io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows.sort(key=lambda r: (r.get("tourney_date", ""), r.get("winner_name", "")))
    ult = max((r.get("tourney_date", "") for r in rows), default="")
    if len(ult) < 8:
        print("\nTENIS: fechas no legibles"); return
    d_ult = dt.date(int(ult[:4]), int(ult[4:6]), int(ult[6:8]))
    corte = (d_ult - dt.timedelta(days=int(meses * 30.4))).strftime("%Y%m%d")
    reps = {}
    J = {}
    def g(n): return J.setdefault(n, {"sp": 0., "spw": 0., "rp": 0., "rpw": 0., "elo": {}})
    tsp = {}                      # circuito -> [puntos al saque, ganados]
    from nucleo import velocidad_tenis as VT
    SV = VT.Senales()             # velocidad del torneo y saque por superficie (capa de breaks, medida 6-oct-2026)
    HH = {}   # lineas base (solo pasado) POR CIRCUITO: ATP y WTA tienen niveles de breaks muy distintos
    for r in rows:
        w, l = r.get("winner_name"), r.get("loser_name")
        sup = (r.get("surface") or "Hard").strip() or "Hard"
        bo = 5 if str(r.get("best_of")).split(".")[0] == "5" else 3
        try:
            wsv = float(r["w_svpt"]); wsw = float(r["w_1stWon"]) + float(r["w_2ndWon"])
            lsv = float(r["l_svpt"]); lsw = float(r["l_1stWon"]) + float(r["l_2ndWon"])
        except (KeyError, ValueError, TypeError):
            continue
        if not w or not l or wsv <= 0 or lsv <= 0: continue
        jw, jl = g(w), g(l)
        ew = jw["elo"].get(sup, 1500.0); el = jl["elo"].get(sup, 1500.0)
        tour = (r.get("tour") or "TOUR").upper()
        tt = tsp.setdefault(tour, [0.0, 0.0])
        hist = HH.setdefault(tour, {"g3": [], "g5": [], "ss3": [], "ss5": [], "br3": [], "br5": [], "win": []})
        tour_spw = (tt[1] / tt[0]) if tt[0] else 0.635
        games, nsets, ok = _games_sets(r.get("score"))
        bpw, bpl = _f(r.get("w_bpFaced")), _f(r.get("l_bpFaced"))
        brk = None
        if None not in (bpw, bpl, _f(r.get("w_bpSaved")), _f(r.get("l_bpSaved"))):
            brk = (bpw - _f(r["w_bpSaved"])) + (bpl - _f(r["l_bpSaved"]))
        en_ventana = r.get("tourney_date", "") >= corte
        pr = None
        if en_ventana and jw["sp"] >= min_j * 50 and jl["sp"] >= min_j * 50:
            p1n, p2n = (w, l) if w < l else (l, w)
            j1, j2 = g(p1n), g(p2n)
            d1 = {"spw": j1["spw"] / j1["sp"], "rpw": j1["rpw"] / max(j1["rp"], 1)}
            d2 = {"spw": j2["spw"] / j2["sp"], "rpw": j2["rpw"] / max(j2["rp"], 1)}
            e1 = j1["elo"].get(sup, 1500.0); e2 = j2["elo"].get(sup, 1500.0)
            lineas = (20.5, 22.5, 24.5) if bo == 3 else (34.5, 38.5, 42.5)
            RES = hist.setdefault("res%d" % bo, [])
            aj = (sum(RES[-400:]) / len(RES[-400:])) if len(RES) >= 150 else 0.0     # sesgo de games, solo con el pasado
            pr = T.predecir(d1, d2, sup, bo, tour_spw, lineas[1], e1, e2, aj)
            if ok and games: RES.append(games - pr["games_sin_ajuste"])
            AJUSTES.setdefault(tour, {})[str(bo)] = round(aj, 2)
            rp_ = reps.setdefault(tour, Rep()); tag = "%d sets" % bo
            y = 1 if p1n == w else 0
            fw = 0.5
            rp_.add_prob("Ganador", pr["p1"], y, fw)
            if ok and games:
                H = hist["g%d" % bo]
                if len(H) > 200:
                    mu0 = sum(H) / len(H)
                    rp_.add_val("Total games [%s]" % tag, pr["games_esperados"], games, mu0)
                    for L in lineas:
                        fb = sum(1 for x in H if x > L) / len(H)
                        rp_.add_prob("Over/Under games [%s]" % tag, (T.p_over_linea(pr, L) if hasattr(T, "p_over_linea") else T._p_over_games(pr["games_esperados"], L, T.SD_GAMES[bo])),
                                     1 if games > L else 0, fb)
                    S = hist["ss%d" % bo]
                    if len(S) > 200:
                        ps = pr["p_set_j1"]; n_need = 2 if bo == 3 else 3
                        pcor = pr.get("p_sets_corridos", ps ** n_need + (1 - ps) ** n_need)
                        rp_.add_prob("Ganador en sets corridos [%s]" % tag, pcor,
                                     1 if nsets == n_need else 0, sum(S) / len(S))
            if brk is not None and len(hist["br%d" % bo]) > 200:
                B = hist["br%d" % bo]
                RB = RESB.setdefault((tour, bo), [])
                ajb = (sum(RB[-400:]) / len(RB[-400:])) if len(RB) >= 150 else 0.0     # sesgo de breaks, solo con el pasado
                AJUSTES_BR.setdefault(tour, {})[str(bo)] = round(ajb, 2)
                aj_v = VT.ajuste(SV, tour, bo, r.get("tourney_name") or "", p1n, p2n, sup)[0]
                mu_b = max(0.1, pr["breaks_esperados"] + ajb + aj_v)
                rp_.add_val("Breaks totales [%s]" % tag, mu_b, brk, sum(B) / len(B))
                for L in (medio(sum(B) / len(B)) - 1, medio(sum(B) / len(B)), medio(sum(B) / len(B)) + 1):
                    po = 1 - sum(math.exp(-mu_b) * mu_b ** k / math.factorial(k) for k in range(int(L) + 1))
                    rp_.add_prob("Breaks over/under [%s]" % tag, po, 1 if brk > L else 0,
                                 sum(1 for x in B if x > L) / len(B))
        # historia para lineas base (siempre despues de predecir)
        if ok and games: hist["g%d" % bo].append(games); hist["ss%d" % bo].append(1 if nsets == (2 if bo == 3 else 3) else 0)
        if brk is not None:
            hist["br%d" % bo].append(brk)
            if pr: RESB.setdefault((tour, bo), []).append(brk - pr["breaks_esperados"])
        SV.actualizar(tour, r.get("tourney_name") or "", sup, r.get("tourney_date", ""), w, l, wsv, wsw, lsv, lsw, tour_spw)
        jw["sp"] += wsv; jw["spw"] += wsw; jw["rp"] += lsv; jw["rpw"] += (lsv - lsw)
        jl["sp"] += lsv; jl["spw"] += lsw; jl["rp"] += wsv; jl["rpw"] += (wsv - wsw)
        exp = 1 / (1 + 10 ** (-(ew - el) / 400)); jw["elo"][sup] = ew + 24 * (1 - exp); jl["elo"][sup] = el - 24 * (1 - exp)
        tt[0] += wsv + lsv; tt[1] += wsw + lsw
    if not reps:
        print("\nTENIS: sin partidos en la ventana."); return
    for tour, rp_ in sorted(reps.items()):
        rp_.imprimir("TENIS %s | ultimos %d meses (as-of partido a partido)" % (tour, meses), clave="tenis_" + tour)


def guardar():
    """Escribe salida/validacion_mercados.json (la lee plataforma.py). Mezcla con lo que ya habia: una corrida
    parcial (--deporte nba) solo actualiza ese deporte."""
    import json
    ruta = io.ruta("salida", "validacion_mercados.json"); d = {"deportes": {}}
    try:
        d = json.load(open(ruta, encoding="utf-8"))
    except Exception:
        pass
    if AJUSTES: d["ajustes_tenis"] = AJUSTES
    if AJUSTES_BR: d["ajustes_tenis_breaks"] = AJUSTES_BR
    d["generado"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    d["criterio"] = "n>=300, mejora a la base, z>=%.1f, mejora en las dos mitades, calibrado (prob |p media - tasa|<=%.2f) o sesgo<=0.10 desv. (conteos)" % (Z_MIN, CAL_MAX)
    d.setdefault("deportes", {}).update({k: v for k, v in RESULT.items() if not k.startswith("futbol_")})
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nEscrito:", ruta)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", default="hockey,nfl,nba,futbol,tenis")
    ap.add_argument("--meses", type=int, default=24)
    ap.add_argument("--bloque", type=int, default=30)
    ap.add_argument("--ligas", default="premier,laliga,seriea,bundesliga,ligue1,ligamx,mls",
                    help="ligas de futbol, cada una se valida con su propio modelo y su propia linea base")
    ap.add_argument("--beisbol", action="store_true", help="tambien totales y run line de beisbol (nucleo.evaluar)")
    a = ap.parse_args()
    for d in [x.strip() for x in a.deporte.split(",") if x.strip()]:
        if d == "tenis": validar_tenis(a.meses)
        elif d == "futbol":
            for lg in [x.strip() for x in a.ligas.split(",") if x.strip()]:
                validar_equipos(d, a.meses, a.bloque, lg)
        elif d == "beisbol":
            for lg in ("MLB", "NPB", "KBO", "LMP"):
                validar_beisbol(lg, a.meses, a.bloque)
        elif d == "ncaa":
            for x in ("ncaafb", "ncaamb"): validar_equipos(x, a.meses, a.bloque)
        elif d in CFG: validar_equipos(d, a.meses, a.bloque)
        else: print("deporte desconocido:", d)
    guardar()
    if a.beisbol:
        from nucleo import evaluar
        from modelos import beisbol
        for lg in ("MLB", "NPB", "KBO"):
            print("\n=== BEISBOL %s: totales ===" % lg)
            try: evaluar.correr_totales("beisbol", beisbol, lg)
            except Exception as e: print("  (%s)" % e)
            print("\n=== BEISBOL %s: run line ===" % lg)
            try: evaluar.correr_runline("beisbol", beisbol, lg)
            except Exception as e: print("  (%s)" % e)


if __name__ == "__main__":
    main()
