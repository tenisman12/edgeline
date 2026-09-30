# -*- coding: utf-8 -*-
"""Valida el MODELO COMBINADO de beisbol (logistica ELO+box  +  probabilidad derivada de carreras).
beisbol.validar() mide solo la logistica; este script mide el ensamble real y lo compara con sus partes.

Por liga, en orden temporal:  55% entrena  |  15% valida (elige el peso w)  |  30% prueba (resultado).
Reporta en PRUEBA: Brier y acierto de  siempre-local, solo-ELO, logistica sola, carreras solas,
ensamble con w por defecto y ensamble con el w elegido en validacion.
Tambien: coherencia (run line con carreras crudas vs ajustadas a la prob. del ensamble).

Uso:  python utilidades\\validar_ensamble.py            (todas las ligas)
      python utilidades\\validar_ensamble.py --ligas mlb,npb,kbo
"""
import argparse, math, os, sys

BASE = os.environ.get("EDGELINE_BASE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from nucleo import features
from modelos import beisbol as B


def brier(ps, ys): return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)
def acc(ps, ys): return sum(1 for p, y in zip(ps, ys) if (p >= .5) == (y == 1)) / len(ys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas"); ap.add_argument("--min_test", type=int, default=60)
    a = ap.parse_args()
    feats, _ = features.construir("beisbol", None)
    porliga = {}
    for r in feats: porliga.setdefault(r["league"], []).append(r)
    sel = {x.strip().lower() for x in a.ligas.split(",")} if a.ligas else None
    cols = ["LOCAL", "ELO", "LOGIST", "CARRER", "MEDIA3", "ENS.35", "ENS.w*"]
    print("%-7s %5s %5s | " % ("LIGA", "TEST", "w*") + " ".join("%-12s" % c for c in cols) + " | mejor parte vs LOCAL y publicable")
    print("-" * 190)
    tot = {c: 0.0 for c in cols}; ntot = 0
    rl = {"crudo": 0.0, "aj": 0.0, "base": 0.0, "n": 0}
    for lg, rows in sorted(porliga.items()):
        if sel and lg.lower() not in sel: continue
        rows.sort(key=lambda r: (r["game_date"], r["gamePk"]))
        n = len(rows)
        i1, i2 = int(n * .55), int(n * .70)
        tr, va, te = rows[:i1], rows[i1:i2], rows[i2:]
        if len(tr) < 80 or len(va) < 30 or len(te) < a.min_test:
            print("%-7s %5d  muestra chica" % (lg, len(te))); continue
        m = B.entrenar_logistica(tr)
        if not m: print("%-7s sin entrenar" % lg); continue
        def partes(filas):
            pl = [B.prob_local(m, r) for r in filas]
            pc = []
            for r, p0 in zip(filas, pl):
                v = B.prob_por_carreras(r)
                pc.append(v if v is not None else p0)
            return pl, pc
        pl_v, pc_v = partes(va); yv = [r["y_home"] for r in va]
        mejor_w, mejor_b = 0.35, 9
        for k in range(0, 11):
            w = k / 10.0
            b = brier([w * x + (1 - w) * y for x, y in zip(pl_v, pc_v)], yv)
            if b < mejor_b: mejor_b, mejor_w = b, w
        # prueba: reentrena con train+val (mas datos), w ya elegido
        m2 = B.entrenar_logistica(tr + va) or m
        m_bak, m = m, m2
        pl_t, pc_t = partes(te); yt = [r["y_home"] for r in te]
        tasa = sum(r["y_home"] for r in tr + va) / len(tr + va)
        p_loc = [tasa] * len(te)
        p_elo = [B._sigmoid((r.get("elo_dif") or 0) / 173.0) for r in te]
        p_e35 = [0.35 * x + 0.65 * y for x, y in zip(pl_t, pc_t)]
        p_ew = [mejor_w * x + (1 - mejor_w) * y for x, y in zip(pl_t, pc_t)]
        p_m3 = [(x + y + z) / 3.0 for x, y, z in zip(p_elo, pl_t, pc_t)]
        res = {"LOCAL": p_loc, "ELO": p_elo, "LOGIST": pl_t, "CARRER": pc_t, "MEDIA3": p_m3, "ENS.35": p_e35, "ENS.w*": p_ew}
        bs = {c: brier(res[c], yt) for c in cols}
        ac = {c: acc(res[c], yt) for c in cols}
        def pareado(base, mod):
            d = [(pb - y) ** 2 - (pm - y) ** 2 for pb, pm, y in zip(base, mod, yt)]
            mu = sum(d) / len(d); sd = math.sqrt(sum((x - mu) ** 2 for x in d) / max(len(d) - 1, 1))
            return mu, sd / math.sqrt(len(d))
        mejor_c = min(("ELO", "LOGIST", "CARRER", "MEDIA3", "ENS.35", "ENS.w*"), key=lambda c: bs[c])
        mu_l, se_l = pareado(res["LOCAL"], res["ENS.w*"])   # version fijada ANTES de ver la prueba (sin sesgo de elegir la mejor)
        mu_e, se_e = pareado(res["ELO"], res["MEDIA3"])
        pub = "SI" if mu_l > 2 * se_l else "no"
        mj = 100 * (bs["LOCAL"] - bs["ENS.w*"]) / bs["LOCAL"]
        print("%-7s %5d %5.1f | " % (lg, len(te), mejor_w) + " ".join("%.3f/%.3f  " % (bs[c], ac[c]) for c in cols) +
              "| ENS.w* vs LOCAL %+.1f%% (EE %.1f%%) publicable:%s | MEDIA3 vs ELO %+.4f (EE %.4f)" % (mj, 100 * se_l / bs["LOCAL"], pub, mu_e, se_e))
        for c in cols: tot[c] += bs[c] * len(te)
        ntot += len(te)
        # coherencia del run line: crudo vs ajustado al ensamble (p del ensamble w*)
        for r, p in zip(te, p_ew):
            xh, xa = B.carreras_esperadas(r)
            if xh is None: continue
            if r.get("marg_home") is None: continue
            y = 1 if r["marg_home"] >= 2 else 0
            xh2, xa2 = B.ajustar_carreras(xh, xa, p)
            p_c, _ = B.prob_run_line(r, 1.5, xh=xh, xa=xa)
            p_a, _ = B.prob_run_line(r, 1.5, xh=xh2, xa=xa2)
            rl["crudo"] += (p_c - y) ** 2; rl["aj"] += (p_a - y) ** 2; rl["n"] += 1
            rl["base"] += (0.36 - y) ** 2
        m = m_bak
    print("-" * 190)
    if ntot:
        print("GLOBAL  %5d       | " % ntot + " ".join("%.3f         " % (tot[c] / ntot) for c in cols))
    print("\nFormato de cada celda: Brier/acierto en PRUEBA (menor Brier = mejor).")
    print("ENS.35 = ensamble con el peso por defecto; ENS.w* = peso elegido en validacion (w = peso de la logistica).")
    if rl["n"]:
        print("\nRUN LINE -1.5 local (Brier, n=%d):  carreras crudas %.4f | ajustadas al ensamble %.4f | siempre 36%% %.4f" % (
            rl["n"], rl["crudo"] / rl["n"], rl["aj"] / rl["n"], rl["base"] / rl["n"]))
    print("PUBLICABLE = el ensamble con w* (fijado en validacion) mejora al baseline 'siempre local' en mas de 2 errores estandar (prueba pareada).")
    print("MEDIA3 = promedio simple de ELO, logistica y carreras (sin pesos que afinar). Diferencia vs ELO: positiva = MEDIA3 mejor.")
    print("LECTURA: el ensamble es util si ENS.w* bate a ELO, a LOGIST y a CARRER a la vez. Si una parte sola gana, el peso debe irse a esa parte.")


if __name__ == "__main__":
    main()
