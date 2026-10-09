# -*- coding: utf-8 -*-
"""
utilidades/validar_futbol_mercados.py - AUDITORIA de todos los mercados de futbol.

Walk-forward (as-of): cada partido se predice solo con lo ocurrido antes. Para cada
mercado y liga se compara contra la LINEA BASE (tasa historica de la liga hasta ese dia):
  - Brier skill  = 1 - Brier_modelo / Brier_base      (>0 mejora a la base)
  - z pareado    = diferencia de errores cuadrados / error estandar (>=1.64 ~ 95% unilateral)
  - Si hay cuota de cierre (1X2, Over/Under 2.5), tambien Brier vs MERCADO.
Estado:  publicable  = n>=300, skill>0, z>=1.64 y calibrado (|p media - tasa real|<=0.04)
         sin_validar = no supera a la base (se muestra igual, marcado)
Eventos binarios y 1X2 (log-loss multiclase vs base).

Uso (en C:\\Edgeline_repo):
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\validar_futbol_mercados.py            # ventana 24 meses
    python utilidades\\validar_futbol_mercados.py --meses 36
Escribe salida/validacion_futbol.json (la usa plataforma.py) y salida/validacion_futbol.txt
"""
import os, sys, math, json, csv, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io
from modelos import futbol as F
from modelos import futbol_mercados as FM

S = 6
LIN_CORNERS = [8.5, 9.5, 10.5, 11.5]
LIN_TARJ = [2.5, 3.5, 4.5, 5.5]
MIN_N = 300; Z_MIN = 1.64; CAL_MAX = 0.04   # |prob. media - tasa real| maximo (calibracion)


def num(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


class Cnt:
    """Tasa de un conteo por equipo (a favor / en contra) con encogimiento."""
    __slots__ = ("f", "c", "n")
    def __init__(s): s.f = 0.0; s.c = 0.0; s.n = 0


def esperado(a, b, lg_h, lg_a, lg):
    # a = equipo local, b = visita
    ah = ((a.f + S * lg) / (a.n + S)) / lg if a.n else 1.0
    dh = ((b.c + S * lg) / (b.n + S)) / lg if b.n else 1.0
    aa = ((b.f + S * lg) / (b.n + S)) / lg if b.n else 1.0
    da = ((a.c + S * lg) / (a.n + S)) / lg if a.n else 1.0
    return lg_h * ah * dh + lg_a * aa * da


class Acum:
    def __init__(s): s.d = {}
    def add(s, mercado, p, y, pb, pm=None):
        s.d.setdefault(mercado, []).append((p, y, pb, pm))


def brier(p, y): return (p - y) ** 2
def ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -math.log(p if y else 1 - p)


def resumen(filas):
    n = len(filas)
    bm = sum(brier(p, y) for p, y, _, _ in filas) / n
    bb = sum(brier(pb, y) for _, y, pb, _ in filas) / n
    lm = sum(ll(p, y) for p, y, _, _ in filas) / n
    lb = sum(ll(pb, y) for _, y, pb, _ in filas) / n
    d = [brier(pb, y) - brier(p, y) for p, y, pb, _ in filas]
    md = sum(d) / n
    sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1)) if n > 1 else 0
    z = md / (sd / math.sqrt(n)) if sd > 0 else 0.0
    skill = 1 - bm / bb if bb > 0 else 0.0
    out = {"n": n, "brier": round(bm, 4), "brier_base": round(bb, 4), "skill": round(skill, 4),
           "logloss": round(lm, 4), "logloss_base": round(lb, 4), "z": round(z, 2),
           "tasa_real": round(sum(y for _, y, _, _ in filas) / n, 3),
           "p_media": round(sum(p for p, _, _, _ in filas) / n, 3)}
    pm = [(p, y, pm) for p, y, _, pm in filas if pm is not None]
    if len(pm) >= 100:
        out["n_mercado"] = len(pm)
        out["brier_modelo_en_mercado"] = round(sum(brier(p, y) for p, y, _ in pm) / len(pm), 4)
        out["brier_mercado"] = round(sum(brier(q, y) for _, y, q in pm) / len(pm), 4)
    ok = n >= MIN_N and skill > 0 and lm < lb and z >= Z_MIN and abs(out["p_media"] - out["tasa_real"]) <= CAL_MAX
    out["estado"] = "publicable" if ok else "sin_validar"
    return out


def cargar_cuotas():
    ruta = io.ruta("datos", "mercado", "futbol_cuotas.csv")
    d = {}
    if not os.path.exists(ruta): return d
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            d[r["gamePk"]] = r
    return d


def sin_vig(*cs):
    cs = [num(c) for c in cs]
    if any(c is None or c <= 1 for c in cs): return None
    inv = [1 / c for c in cs]; s = sum(inv)
    return [x / s for x in inv]


def liga_run(liga, desde, cuotas):
    juegos = F._juegos(liga)
    eq = {}; sh = sa = 0.0; ng = 0
    cn = {"c": {}, "t": {}}      # corners, tarjetas por equipo
    sums = {"c_h": 0.0, "c_a": 0.0, "t_h": 0.0, "t_a": 0.0, "nc": 0, "nt": 0}
    ht = {"g": 0.0, "gt": 0.0}
    cuenta_marc = {}; ncm = 0
    base = {}                     # tasas base por mercado, expanding
    acum = Acum()
    for f, gp, h, a in juegos:
        gh = num(h.get("goals")); ga_ = num(h.get("goals_opp"))
        if gh is None or ga_ is None: continue
        th = eq.setdefault(h.get("team"), F.Eq()); ta = eq.setdefault(a.get("team"), F.Eq())
        lh = sh / ng if ng else 1.5; la = sa / ng if ng else 1.15
        ch, ca = num(h.get("corners")), num(a.get("corners"))
        yh = (num(h.get("yellow")), num(h.get("red"))); ya = (num(a.get("yellow")), num(a.get("red")))
        th_, tt_ = (None, None)
        if yh[0] is not None and ya[0] is not None:
            th_ = yh[0] + (yh[1] or 0); tt_ = ya[0] + (ya[1] or 0)
        gh1, ga1 = num(h.get("goals_ht")), num(h.get("goals_ht_opp"))
        evalua = f >= desde and th.n >= 6 and ta.n >= 6
        if evalua:
            est = {"eq": eq, "lg": (lh + la) / 2, "lg_home": lh, "lg_away": la}
            ph, pd, pa, xh, xa, P = F._ensamble(est, th, ta, F.W_ENS)
            M = FM.desde_matriz(P, ph, pd, pa)
            real = {"1": gh > ga_, "X": gh == ga_, "2": ga_ > gh,
                    "1X": gh >= ga_, "X2": ga_ >= gh, "12": gh != ga_,
                    "aa_si": gh > 0 and ga_ > 0, "aa_no": not (gh > 0 and ga_ > 0),
                    "over_1.5": gh + ga_ > 1, "over_2.5": gh + ga_ > 2, "over_3.5": gh + ga_ > 3,
                    "under_1.5": gh + ga_ <= 1, "under_2.5": gh + ga_ <= 2, "under_3.5": gh + ga_ <= 3,
                    "local_gana_por_2": gh - ga_ >= 2, "visita_gana_por_2": ga_ - gh >= 2}
            q = cuotas.get(gp) or {}
            pm = {}
            x2 = sin_vig(q.get("fd_AvgCH"), q.get("fd_AvgCD"), q.get("fd_AvgCA"))
            if x2: pm["1"], pm["X"], pm["2"] = x2
            ou = sin_vig(q.get("fd_AvgC_mas2.5"), q.get("fd_AvgC_menos2.5"))
            if ou: pm["over_2.5"], pm["under_2.5"] = ou
            for k, pv in M.items():
                if k not in real: continue
                b = base.get(k, [0, 0]); pb = (b[0] + 1) / (b[1] + 2) if b[1] >= 50 else 0.5
                if b[1] >= 50: pb = b[0] / b[1]
                acum.add(k, pv, 1 if real[k] else 0, pb, pm.get(k))
            # marcador exacto: log-loss vs frecuencia historica de marcadores
            if ncm >= 200:
                pe = P[int(gh)][int(ga_)] if gh < len(P) and ga_ < len(P) else 1e-6
                pbse = (cuenta_marc.get((int(gh), int(ga_)), 0) + 0.5) / (ncm + 0.5 * 64)
                acum.add("marcador_exacto_ll", pe, 1, pbse)
            # primer tiempo
            if gh1 is not None and ga1 is not None and ht["gt"] > 500:
                fr = ht["g"] / ht["gt"]
                M1 = FM.primer_tiempo(xh, xa, fr)
                r1 = {"1T_1": gh1 > ga1, "1T_X": gh1 == ga1, "1T_2": ga1 > gh1,
                      "1T_over_0.5": gh1 + ga1 > 0, "1T_over_1.5": gh1 + ga1 > 1}
                for k, pv in M1.items():
                    b = base.get(k, [0, 0]); pb = b[0] / b[1] if b[1] >= 50 else 0.5
                    acum.add(k, pv, 1 if r1[k] else 0, pb)
            # corners
            if ch is not None and ca is not None and sums["nc"] > 200:
                lgc = (sums["c_h"] + sums["c_a"]) / (2 * sums["nc"])
                mu = esperado(cn["c"].setdefault(h["team"], Cnt()), cn["c"].setdefault(a["team"], Cnt()),
                              sums["c_h"] / sums["nc"], sums["c_a"] / sums["nc"], lgc)
                for k, pv in FM.conteo(mu, LIN_CORNERS).items():
                    l = float(k.split("_")[1]); y = (ch + ca > l) if k.startswith("over") else (ch + ca <= l)
                    kk = "corners_" + k; b = base.get(kk, [0, 0]); pb = b[0] / b[1] if b[1] >= 50 else 0.5
                    acum.add(kk, pv, 1 if y else 0, pb)
            # tarjetas
            if th_ is not None and sums["nt"] > 200:
                lgt = (sums["t_h"] + sums["t_a"]) / (2 * sums["nt"])
                mu = esperado(cn["t"].setdefault(h["team"], Cnt()), cn["t"].setdefault(a["team"], Cnt()),
                              sums["t_h"] / sums["nt"], sums["t_a"] / sums["nt"], lgt)
                for k, pv in FM.conteo(mu, LIN_TARJ).items():
                    l = float(k.split("_")[1]); y = (th_ + tt_ > l) if k.startswith("over") else (th_ + tt_ <= l)
                    kk = "tarjetas_" + k; b = base.get(kk, [0, 0]); pb = b[0] / b[1] if b[1] >= 50 else 0.5
                    acum.add(kk, pv, 1 if y else 0, pb)
        # ---- actualizar estado (despues de predecir)
        exp = F._sig((th.elo + F.HFA_ELO - ta.elo) / (F.ESCALA / math.log(10)))
        res = 1.0 if gh > ga_ else (0.5 if gh == ga_ else 0.0)
        d = F.K_ELO * (res - exp); th.elo += d; ta.elo -= d
        F._sumar(th, gh, ga_); F._sumar(ta, ga_, gh)      # mismo olvido que modelos/futbol.py
        sh += gh; sa += ga_; ng += 1
        T = gh + ga_
        eventos = {"1": gh > ga_, "X": gh == ga_, "2": ga_ > gh, "1X": gh >= ga_, "X2": ga_ >= gh, "12": gh != ga_,
                   "aa_si": gh > 0 and ga_ > 0, "aa_no": not (gh > 0 and ga_ > 0),
                   "over_1.5": T > 1, "over_2.5": T > 2, "over_3.5": T > 3,
                   "under_1.5": T <= 1, "under_2.5": T <= 2, "under_3.5": T <= 3,
                   "local_gana_por_2": gh - ga_ >= 2, "visita_gana_por_2": ga_ - gh >= 2}
        for k, v in eventos.items():
            b = base.setdefault(k, [0, 0]); b[0] += 1 if v else 0; b[1] += 1
        cuenta_marc[(int(gh), int(ga_))] = cuenta_marc.get((int(gh), int(ga_)), 0) + 1; ncm += 1
        if gh1 is not None and ga1 is not None:
            ht["g"] += gh1 + ga1; ht["gt"] += T
            ev1 = {"1T_1": gh1 > ga1, "1T_X": gh1 == ga1, "1T_2": ga1 > gh1,
                   "1T_over_0.5": gh1 + ga1 > 0, "1T_over_1.5": gh1 + ga1 > 1}
            for k, v in ev1.items():
                b = base.setdefault(k, [0, 0]); b[0] += 1 if v else 0; b[1] += 1
        if ch is not None and ca is not None:
            for l in LIN_CORNERS:
                for nm, y in (("over", ch + ca > l), ("under", ch + ca <= l)):
                    b = base.setdefault("corners_%s_%s" % (nm, l), [0, 0]); b[0] += 1 if y else 0; b[1] += 1
            for tm, fo, co in ((h["team"], ch, ca), (a["team"], ca, ch)):
                c = cn["c"].setdefault(tm, Cnt()); c.f += fo; c.c += co; c.n += 1
            sums["c_h"] += ch; sums["c_a"] += ca; sums["nc"] += 1
        if th_ is not None:
            for l in LIN_TARJ:
                for nm, y in (("over", th_ + tt_ > l), ("under", th_ + tt_ <= l)):
                    b = base.setdefault("tarjetas_%s_%s" % (nm, l), [0, 0]); b[0] += 1 if y else 0; b[1] += 1
            for tm, fo, co in ((h["team"], th_, tt_), (a["team"], tt_, th_)):
                c = cn["t"].setdefault(tm, Cnt()); c.f += fo; c.c += co; c.n += 1
            sums["t_h"] += th_; sums["t_a"] += tt_; sums["nt"] += 1
    return acum


def resumen_marcador(filas):
    n = len(filas)
    lm = sum(-math.log(max(p, 1e-9)) for p, _, _, _ in filas) / n
    lb = sum(-math.log(max(pb, 1e-9)) for _, _, pb, _ in filas) / n
    d = [-math.log(max(pb, 1e-9)) + math.log(max(p, 1e-9)) for p, _, pb, _ in filas]
    md = sum(d) / n; sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1))
    z = md / (sd / math.sqrt(n)) if sd > 0 else 0
    return {"n": n, "logloss": round(lm, 4), "logloss_base": round(lb, 4),
            "skill": round(1 - lm / lb, 4), "z": round(z, 2),
            "estado": "publicable" if n >= MIN_N and lm < lb and z >= Z_MIN else "sin_validar"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--meses", type=int, default=24)
    a = ap.parse_args()
    juegos = F._juegos(None)
    ult = max(j[0] for j in juegos)
    desde = (dt.date.fromisoformat(ult) - dt.timedelta(days=30 * a.meses)).isoformat()
    cuotas = cargar_cuotas()
    ligas = sorted({r.get("league") for r in io.cargar_juegos("futbol", None) if r.get("league")})
    res = {}; lineas = []
    lineas.append("VALIDACION MERCADOS DE FUTBOL - walk-forward, ventana desde %s (datos hasta %s)" % (desde, ult))
    lineas.append("Estado: publicable = n>=%d, skill>0, logloss<base y z>=%.2f y calibrado (|p media - tasa|<=%.2f). Si no, sin_validar." % (MIN_N, Z_MIN, CAL_MAX))
    for liga in ligas:
        ac = liga_run(liga, desde, cuotas)
        res[liga] = {}
        lineas.append(""); lineas.append("== %s ==" % liga)
        lineas.append("%-22s %6s %7s %7s %7s %6s  %-11s %s" % ("MERCADO", "n", "tasa", "p_med", "skill", "z", "ESTADO", "vs mercado (Brier mod/merc)"))
        for k in sorted(ac.d):
            filas = ac.d[k]
            if len(filas) < 50: continue
            r = resumen_marcador(filas) if k == "marcador_exacto_ll" else resumen(filas)
            res[liga][k] = r
            mk = ""
            if "brier_mercado" in r: mk = "%.4f / %.4f (n=%d)" % (r["brier_modelo_en_mercado"], r["brier_mercado"], r["n_mercado"])
            lineas.append("%-22s %6d %7s %7s %+7.3f %6.1f  %-11s %s" % (k, r["n"], r.get("tasa_real", ""), r.get("p_media", ""), r["skill"], r["z"], r["estado"], mk))
    txt = "\n".join(lineas)
    print(txt)
    json.dump({"ventana_desde": desde, "datos_hasta": ult, "ligas": res}, open(io.ruta("salida", "validacion_futbol.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(io.ruta("salida", "validacion_futbol.txt"), "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    main()
