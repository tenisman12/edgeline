# -*- coding: utf-8 -*-
"""
utilidades/minar_forma_rapida.py - prueba si los modelos de futbol y NFL mejoran reaccionando mas rapido a la forma.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_forma_rapida.md
Futbol: ELO K mas alto y olvido en las tasas de goles (una pasada as-of por liga, misma formula que modelos/futbol.py).
NFL: ELO K mas alto (misma formula que modelos/americano.py) y media exponencial del margen, encima de la capa de
produccion (L5 + EPA neto de temporada) reajustada en el 70 %.
Eleccion en el 70 % mas antiguo, prueba unica en el 30 %. No modifica modelos/ ni plataforma.py.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_forma_rapida.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, io as _io, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402
from modelos import futbol as FU  # noqa: E402
from modelos import americano as AM  # noqa: E402

BASE = M.BASE
_lg, _sig, _ll = M._lg, M._sig, M._ll


def _z(d):
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / max(n - 1, 1)) or 1e-12
    h = n // 2
    return m, m / (sd / math.sqrt(n)), sum(d[:h]) / max(h, 1), sum(d[h:]) / max(n - h, 1)


def _fit_pred(Xtr, Ytr, Xte):
    w = M._logistica(Xtr, Ytr)
    pr = lambda X: [_sig(sum(a * b for a, b in zip(w, x))) for x in X]
    return w, pr(Xtr), pr(Xte)


# ================================================================== FUTBOL
def _pin_futbol():
    out = {}
    ruta = os.path.join(BASE, "datos", "mercado", "futbol_cuotas.csv")
    if not os.path.exists(ruta): return out
    with _io.open(ruta, encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            o = [M._num(x.get(k)) for k in ("fd_PSCH", "fd_PSCD", "fd_PSCA")]
            if not all(o): o = [M._num(x.get(k)) for k in ("fd_AvgCH", "fd_AvgCD", "fd_AvgCA")]
            if all(o):
                s = sum(1 / v for v in o); out[str(x["gamePk"])] = tuple((1 / v) / s for v in o)
    return out


def pasada_futbol(liga, K, delta, w=FU.W_ENS, i0=300):
    """Prediccion as-of partido por partido con la formula de modelos/futbol.py; K del ELO y olvido delta en las tasas."""
    G = [(f, gp, h, a) for f, gp, h, a in FU._juegos(liga)
         if M._num(h.get("goals")) is not None and M._num(h.get("goals_opp")) is not None]
    eq = {}; sh = sa = 0.0; n = 0; out = []; racha = {}
    for i, (f, gp, h, a) in enumerate(G):
        gh, ga = float(h["goals"]), float(h["goals_opp"])
        tn, an = h.get("team"), a.get("team")
        th, ta = eq.get(tn), eq.get(an)
        if i >= i0 and th and ta and n:
            lh, la = sh / n, sa / n
            est = {"eq": eq, "lg": (lh + la) / 2, "lg_home": lh, "lg_away": la}
            ph, pd, pa, _, _, P = FU._ensamble(est, th, ta, w)
            po = sum(P[x][y] for x in range(len(P)) for y in range(len(P)) if x + y >= 3)
            out.append(dict(fecha=f, gp=str(gp), liga=liga, ph=ph, pd=pd, pa=pa, po=po, over=1 if gh + ga >= 3 else 0,
                            res="H" if gh > ga else ("D" if gh == ga else "A"),
                            rh=racha.get(tn, 0), ra=racha.get(an, 0)))
        th = eq.setdefault(tn, FU.Eq()); ta = eq.setdefault(an, FU.Eq())
        exp = _sig((th.elo + FU.HFA_ELO - ta.elo) / (FU.ESCALA / math.log(10)))
        res = 1.0 if gh > ga else (0.5 if gh == ga else 0.0)
        d = K * (res - exp); th.elo += d; ta.elo -= d
        for t, gf, gc in ((th, gh, ga), (ta, ga, gh)):
            t.gf = delta * t.gf + gf; t.ga = delta * t.ga + gc; t.n = delta * t.n + 1
        racha[tn] = racha.get(tn, 0) + 1 if gh < ga else 0
        racha[an] = racha.get(an, 0) + 1 if ga < gh else 0
        sh += gh; sa += ga; n += 1
    return out


def correr_futbol():
    KS = [20.0, 30.0, 40.0, 60.0]; DS = [1.0, 0.995, 0.99, 0.98, 0.97]
    pin = _pin_futbol()
    res = {}
    for K in KS:
        for dl in DS:
            filas = []
            for liga in M.LIGAS_FUT:
                filas += pasada_futbol(liga, K, dl)
            filas.sort(key=lambda r: (r["fecha"], r["gp"]))
            res[(K, dl)] = filas
            print("  futbol K %.0f delta %.3f: %d partidos" % (K, dl, len(filas)))
    base = res[(20.0, 1.0)]
    n = len(base); corte = base[int(n * 0.7)]["fecha"]
    for k, F in res.items():
        assert [r["gp"] for r in F] == [r["gp"] for r in base], "partidos distintos entre configuraciones"
    ll = lambda r: -math.log(max({"H": r["ph"], "D": r["pd"], "A": r["pa"]}[r["res"]], 1e-9))
    tr_ll = {k: sum(ll(r) for r in F if r["fecha"] < corte) / sum(1 for r in F if r["fecha"] < corte) for k, F in res.items()}
    print("\nFUTBOL | %d partidos as-of | prueba desde %s" % (n, corte))
    for k in sorted(tr_ll): print("  K %4.0f  delta %.3f  log-loss 1X2 en el 70 %%: %.5f" % (k[0], k[1], tr_ll[k]))
    kb = min(tr_ll, key=tr_ll.get)
    print("  elegido en el 70 %%: K %.0f delta %.3f" % kb)
    B = [r for r in base if r["fecha"] >= corte]; C = [r for r in res[kb] if r["fecha"] >= corte]
    d = [ll(b) - ll(c) for b, c in zip(B, C)]
    m, z, m1, m2 = _z(d)
    calb = sum(c["ph"] for c in C) / len(C) - sum(1 for c in C if c["res"] == "H") / len(C)
    cal0 = sum(b["ph"] for b in B) / len(B) - sum(1 for b in B if b["res"] == "H") / len(B)
    ver = "pasa" if (kb != (20.0, 1.0) and z >= 1.64 and m1 > 0 and m2 > 0 and abs(calb) <= 0.04 and len(d) >= 300) else "no pasa"
    print("  PRUEBA: log-loss 1X2 base %.5f  elegido %.5f | mejora %+.3f milesimas z %+.2f mitades %+.3f / %+.3f | calibracion local base %+.4f elegido %+.4f -> %s" % (
        sum(ll(b) for b in B) / len(B), sum(ll(c) for c in C) / len(C), 1000 * m, z, 1000 * m1, 1000 * m2, cal0, calb, ver.upper()))
    out = {"n": n, "desde_prueba": corte, "n_prueba": len(d), "logloss_explorar": {"K%.0f_d%.3f" % k: round(v, 5) for k, v in tr_ll.items()},
           "elegido": {"K": kb[0], "delta": kb[1]}, "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2),
           "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)], "calibracion_local": {"base": round(cal0, 4), "elegido": round(calb, 4)},
           "veredicto": ver}
    # el olvido tambien mueve los goles esperados: over 2.5 base contra elegido (no decide, cuida que no se rompa)
    mo, zo, o1, o2 = _z([_ll(b["po"], b["over"]) - _ll(c["po"], c["over"]) for b, c in zip(B, C)])
    calo = sum(c["po"] for c in C) / len(C) - sum(c["over"] for c in C) / len(C)
    calo0 = sum(b["po"] for b in B) / len(B) - sum(b["over"] for b in B) / len(B)
    out["over25"] = {"mejora_milesimas": round(1000 * mo, 3), "z": round(zo, 2), "mitades": [round(1000 * o1, 3), round(1000 * o2, 3)],
                     "calibracion": {"base": round(calo0, 4), "elegido": round(calo, 4)}}
    print("  over 2.5 (prueba) elegido contra base: %+.3f milesimas z %+.2f mitades %+.3f / %+.3f | calibracion base %+.4f elegido %+.4f" % (
        1000 * mo, zo, 1000 * o1, 1000 * o2, calo0, calo))
    # tambien la configuracion "mas rapida" de la rejilla, como referencia
    for kref in ((60.0, 0.97), (40.0, 0.98)):
        Cr = [r for r in res[kref] if r["fecha"] >= corte]
        mr, zr, a1, a2 = _z([ll(b) - ll(c) for b, c in zip(B, Cr)])
        out["referencia_K%.0f_d%.3f" % kref] = {"mejora_milesimas": round(1000 * mr, 3), "z": round(zr, 2)}
        print("  referencia K %.0f delta %.3f contra base: mejora %+.3f milesimas z %+.2f" % (kref[0], kref[1], 1000 * mr, zr))
    # rachas de 5+ derrotas en la prueba: residuo del equipo en racha, base contra elegido
    for nom, Fx in (("base", B), ("elegido", C)):
        rr = []
        for r in Fx:
            if r["rh"] >= 5 and r["ra"] < 5: rr.append((1 if r["res"] == "H" else 0) - r["ph"])
            elif r["ra"] >= 5 and r["rh"] < 5: rr.append((1 if r["res"] == "A" else 0) - r["pa"])
        if rr:
            mm = sum(rr) / len(rr); se = math.sqrt(sum((v - mm) ** 2 for v in rr) / max(len(rr) - 1, 1) / len(rr))
            out["racha5_derrotas_" + nom] = {"n": len(rr), "residuo_pp": round(100 * mm, 2), "ic95": [round(100 * (mm - 1.96 * se), 1), round(100 * (mm + 1.96 * se), 1)]}
            print("  racha de 5+ derrotas (prueba) %-8s n %d  gana %+.1f pp contra lo que dice el modelo [%+.1f, %+.1f]" % (
                nom, len(rr), 100 * mm, 100 * (mm - 1.96 * se), 100 * (mm + 1.96 * se)))
    # contra el cierre de Pinnacle (ganador local, binario)
    out["contra_pinnacle"] = _contra_cierre([(r["fecha"], pin.get(r["gp"], (None,))[0], r["ph"], 1 if r["res"] == "H" else 0) for r in base],
                                            [(r["fecha"], pin.get(r["gp"], (None,))[0], r["ph"], 1 if r["res"] == "H" else 0) for r in res[kb]],
                                            corte, "futbol")
    return out


def _contra_cierre(Fb, Fc, corte, nombre):
    """Fb/Fc: (fecha, p_cierre, p_modelo, y). Peso del modelo encima del cierre (logit) y mejora fuera de muestra."""
    out = {}
    for etq, F in (("base", Fb), ("elegido", Fc)):
        F = [x for x in F if x[1]]
        tr = [x for x in F if x[0] < corte]; te = [x for x in F if x[0] >= corte]
        if len(tr) < 200 or len(te) < 100: continue
        X0 = lambda S: [[1.0, _lg(x[1])] for x in S]; X1 = lambda S: [[1.0, _lg(x[1]), _lg(x[2])] for x in S]
        Y = [x[3] for x in tr]
        w0, _, q0 = _fit_pred(X0(tr), Y, X0(te)); w1, _, q1 = _fit_pred(X1(tr), Y, X1(te))
        d = [_ll(a, x[3]) - _ll(b, x[3]) for a, b, x in zip(q0, q1, te)]
        m, z, m1, m2 = _z(d)
        out[etq] = {"n_explorar": len(tr), "n_prueba": len(te), "coef_modelo": round(w1[2], 3), "coef_cierre": round(w1[1], 3),
                    "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2)}
        print("  %s contra el cierre (%s): coef. modelo %+.3f, cierre %+.3f | fuera de muestra %+.3f milesimas z %+.2f (n %d)" % (
            nombre, etq, w1[2], w1[1], 1000 * m, z, len(te)))
    return out


# ================================================================== NFL
def _season(h, f):
    s = str(h.get("season") or "")[:4]
    if s.isdigit(): return s
    y, mo = int(f[:4]), int(f[5:7])
    return str(y - 1 if mo <= 3 else y)


def _epa_nfl():
    """(season, team) -> lista (fecha, epa_of, jugadas_of, epa_permitido, jugadas_def)."""
    ruta = os.path.join(BASE, "datos", "equipos", "nfl_equipos.csv")
    if not os.path.exists(ruta): return {}
    por = {}
    with _io.open(ruta, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            def fl(k):
                try: return float(r.get(k) or 0)
                except ValueError: return 0.0
            por[(str(r["game_id"]), r["team"])] = (str(r.get("season") or "")[:4], (r.get("game_date") or "")[:10], r.get("opp"),
                                                   fl("passing_epa") + fl("rushing_epa"), fl("attempts") + fl("carries") + fl("sacks_suffered"))
    out = {}
    for (gid, t), (s, f, opp, e, j) in por.items():
        o = por.get((gid, opp))
        if not o: continue
        out.setdefault((s, t), []).append((f, e, j, o[3], o[4]))
    for v in out.values(): v.sort()
    return out


def _epa_asof(E, s, t, f):
    L = [x for x in E.get((s, t), []) if x[0] < f]
    if len(L) < 4: return None
    jo = sum(x[2] for x in L); jd = sum(x[4] for x in L)
    if not jo or not jd: return None
    return sum(x[1] for x in L) / jo - sum(x[3] for x in L) / jd


def pasada_nfl(K, min_j=4):
    """Misma formula que modelos/americano.entrenar (ELO con regresion entre temporadas), K variable; mas capas as-of."""
    E = _epa_nfl()
    js = AM._juegos("NFL"); eq = {}; out = []
    hist = {}; ewm = {hl: {} for hl in (2, 3, 5)}; rach = {}; temp = {}
    for f, gp, h, a in js:
        ph = AM._f(h.get("points")) or AM._f(h.get("runs")); pa_ = AM._f(h.get("points_opp")) or AM._f(h.get("runs_opp"))
        if ph is None or pa_ is None: continue
        tn, an = h.get("team"), a.get("team")
        th = eq.setdefault(tn, AM.Eq()); ta = eq.setdefault(an, AM.Eq())
        for t in (th, ta):
            if t.ult and t.ult != f[:4]: t.elo = AM.BASE_ELO + (t.elo - AM.BASE_ELO) * AM.REGR
            t.ult = f[:4]
        s = _season(h, f)
        if th.n >= min_j and ta.n >= min_j:
            pe = AM._cdf(((th.elo + AM.HFA - ta.elo) / AM.ELO_POR_PUNTO) / AM.SD_MARGEN)
            def l5(t):
                u = hist.get(t, [])[-5:]
                return sum(1.0 for x in u if x > 0) / len(u) if u else None
            def dift(t):
                u = temp.get((s, t), [])
                return sum(u) / len(u) if len(u) >= 5 else None
            eh, ea = _epa_asof(E, s, tn, f), _epa_asof(E, s, an, f)
            out.append(dict(fecha=f, gp=str(gp), home=tn, away=an, pe=pe, y=1 if ph > pa_ else 0,
                            l5h=l5(tn), l5a=l5(an), epah=eh, epaa=ea, difh=dift(tn), difa=dift(an),
                            ewm={hl: ewm[hl].get(tn, 0.0) - ewm[hl].get(an, 0.0) for hl in ewm},
                            rh=rach.get(tn, 0), ra=rach.get(an, 0)))
        esp = _sig((th.elo + AM.HFA - ta.elo) / (AM.ESCALA / math.log(10)))
        res = 1.0 if ph > pa_ else (0.0 if ph < pa_ else .5)
        d = K * math.log(abs(ph - pa_) + 1) * (res - esp); th.elo += d; ta.elo -= d
        th.pf += ph; th.pa += pa_; th.n += 1; ta.pf += pa_; ta.pa += ph; ta.n += 1
        for t, mg in ((tn, ph - pa_), (an, pa_ - ph)):
            if mg != 0: hist.setdefault(t, []).append(mg)
            temp.setdefault((s, t), []).append(mg)
            for hl in ewm:
                al = 1 - 0.5 ** (1.0 / hl); ewm[hl][t] = ewm[hl].get(t, 0.0) + al * (mg - ewm[hl].get(t, 0.0))
            rach[t] = rach.get(t, 0) + 1 if mg > 0 else 0
    return out


def _x_nfl(r, pe=None, hl=None):
    pe = r["pe"] if pe is None else pe
    dl5 = (r["l5h"] - r["l5a"]) if (r["l5h"] is not None and r["l5a"] is not None) else 0.0
    if r["epah"] is not None and r["epaa"] is not None:
        de, dd = 10.0 * (r["epah"] - r["epaa"]), 0.0
    else:
        de = 0.0; dd = (r["difh"] - r["difa"]) if (r["difh"] is not None and r["difa"] is not None) else 0.0
    x = [1.0, _lg(pe), dl5, de, dd]
    if hl: x.append(r["ewm"][hl] / 10.0)
    return x


def correr_nfl():
    KS = [20.0, 30.0, 40.0, 60.0]; HL = [2, 3, 5]
    # chequeo: la pasada con K 20 reproduce la cal de modelos/americano.entrenar
    ref = AM.entrenar("NFL")["cal"]; R = {K: pasada_nfl(K) for K in KS}
    dif = max(abs(a[0] - b["pe"]) for a, b in zip(ref, R[20.0])) if len(ref) == len(R[20.0]) else None
    print("\nNFL | chequeo contra modelos/americano: %d vs %d predicciones, diferencia maxima %s" % (
        len(ref), len(R[20.0]), "%.2e" % dif if dif is not None else "longitud distinta"))
    base = R[20.0]; n = len(base); i70 = int(n * 0.7); corte = base[i70]["fecha"]
    tr = [r for r in base if r["fecha"] < corte]; te = [r for r in base if r["fecha"] >= corte]
    Ytr = [r["y"] for r in tr]; Yte = [r["y"] for r in te]
    print("NFL | %d partidos as-of | prueba desde %s (%d)" % (n, corte, len(te)))
    llm = lambda Q, Y: sum(_ll(q, y) for q, y in zip(Q, Y)) / len(Y)
    w0, qtr0, qte0 = _fit_pred([_x_nfl(r) for r in tr], Ytr, [_x_nfl(r) for r in te])
    print("  base (K 20 + capa L5/EPA reajustada): pesos logit %s | log-loss 70 %% %.5f" % ([round(v, 3) for v in w0], llm(qtr0, Ytr)))
    # sin capa, para ver cuanto aporta la capa de produccion en la prueba
    _, _, qsc = _fit_pred([[1.0, _lg(r["pe"])] for r in tr], Ytr, [[1.0, _lg(r["pe"])] for r in te])
    def comparar(qa, qb, act=None):
        d = [_ll(a, y) - _ll(b, y) for a, b, y in zip(qa, qb, Yte)]
        m, z, m1, m2 = _z(d)
        cal = sum(qb) / len(qb) - sum(Yte) / len(Yte)
        return m, z, m1, m2, cal
    m, z, m1, m2, _ = comparar(qsc, qte0)
    print("  referencia: la capa de produccion sobre el ELO solo, en la prueba: %+.3f milesimas z %+.2f" % (1000 * m, z))
    out = {"n": n, "desde_prueba": corte, "n_prueba": len(te), "pesos_base": [round(v, 4) for v in w0],
           "capa_produccion_en_prueba": {"mejora_milesimas": round(1000 * m, 3), "z": round(z, 2)}}
    # A: K
    trK = {}; teK = {}
    for K in KS:
        trr = [r for r in R[K] if r["fecha"] < corte]; tee = [r for r in R[K] if r["fecha"] >= corte]
        assert [r["gp"] for r in tee] == [r["gp"] for r in te]
        w, qa, qb = _fit_pred([_x_nfl(r) for r in trr], Ytr, [_x_nfl(r) for r in tee])
        trK[K] = llm(qa, Ytr); teK[K] = qb
        print("  A  K %.0f  log-loss 70 %%: %.5f" % (K, trK[K]))
    kb = min(trK, key=trK.get)
    m, z, m1, m2, cal = comparar(qte0, teK[kb])
    ver = "pasa" if (kb != 20.0 and z >= 2.0 and m1 > 0 and m2 > 0 and abs(cal) <= 0.04) else "no pasa"
    print("  A  PRUEBA: K %.0f contra K 20 | %+.3f milesimas z %+.2f mitades %+.3f / %+.3f calibracion %+.4f -> %s" % (
        kb, 1000 * m, z, 1000 * m1, 1000 * m2, cal, ver.upper()))
    out["A_K"] = {"logloss_explorar": {str(int(k)): round(v, 5) for k, v in trK.items()}, "elegido": kb, "mejora_milesimas": round(1000 * m, 3),
                  "z": round(z, 2), "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)], "calibracion": round(cal, 4), "veredicto": ver}
    for kref in (40.0, 60.0):
        mr, zr, _, _, _ = comparar(qte0, teK[kref])
        out["A_K"]["referencia_K%.0f" % kref] = {"mejora_milesimas": round(1000 * mr, 3), "z": round(zr, 2)}
        print("     referencia K %.0f contra K 20: %+.3f milesimas z %+.2f" % (kref, 1000 * mr, zr))
    # B: media exponencial del margen
    trH = {}; teH = {}; wH = {}
    for hl in HL:
        w, qa, qb = _fit_pred([_x_nfl(r, hl=hl) for r in tr], Ytr, [_x_nfl(r, hl=hl) for r in te])
        trH[hl] = llm(qa, Ytr); teH[hl] = qb; wH[hl] = w
        print("  B  vida media %d  coef %+.3f por 10 puntos  log-loss 70 %%: %.5f (base %.5f)" % (hl, w[-1], trH[hl], llm(qtr0, Ytr)))
    hb = min(trH, key=trH.get)
    m, z, m1, m2, cal = comparar(qte0, teH[hb])
    ver = "pasa" if (wH[hb][-1] > 0 and z >= 2.0 and m1 > 0 and m2 > 0 and abs(cal) <= 0.04) else "no pasa"
    print("  B  PRUEBA: vida media %d contra base | %+.3f milesimas z %+.2f mitades %+.3f / %+.3f calibracion %+.4f -> %s" % (
        hb, 1000 * m, z, 1000 * m1, 1000 * m2, cal, ver.upper()))
    out["B_ewm"] = {"logloss_explorar": {str(k): round(v, 5) for k, v in trH.items()}, "elegido": hb, "coef": round(wH[hb][-1], 4),
                    "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2), "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)],
                    "calibracion": round(cal, 4), "veredicto": ver}
    # racha de 5+ victorias: residuo contra el ELO solo y contra la base de produccion (toda la prueba)
    for nom, Q in (("ELO solo", qsc), ("base produccion", qte0)):
        rr = []
        for r, q in zip(te, Q):
            if r["rh"] >= 5 and r["ra"] < 5: rr.append(r["y"] - q)
            elif r["ra"] >= 5 and r["rh"] < 5: rr.append((1 - r["y"]) - (1 - q))
        if rr:
            mm = sum(rr) / len(rr); se = math.sqrt(sum((v - mm) ** 2 for v in rr) / max(len(rr) - 1, 1) / len(rr))
            out["racha5_victorias_" + nom.replace(" ", "_")] = {"n": len(rr), "residuo_pp": round(100 * mm, 2),
                                                                  "ic95": [round(100 * (mm - 1.96 * se), 1), round(100 * (mm + 1.96 * se), 1)]}
            print("  racha de 5+ victorias (prueba) contra %-16s n %d  gana %+.1f pp mas de lo que dice [%+.1f, %+.1f]" % (
                nom, len(rr), 100 * mm, 100 * (mm - 1.96 * se), 100 * (mm + 1.96 * se)))
    # contra el cierre: la base de produccion y la mejor de A
    M.evaluar = lambda *a, **k: None
    M.correr_americano("NFL")
    pm = {(r["fecha"][:10], r["home"], r["away"]): r.get("pm") for r in M.ULTIMO["NFL"][0]}
    qall0 = _fit_pred([_x_nfl(r) for r in tr], Ytr, [_x_nfl(r) for r in base])[2]
    rk = R[kb]; qallk = _fit_pred([_x_nfl(r) for r in rk if r["fecha"] < corte], Ytr, [_x_nfl(r) for r in rk])[2]
    out["contra_cierre"] = _contra_cierre([(r["fecha"], pm.get((r["fecha"][:10], r["home"], r["away"])), q, r["y"]) for r, q in zip(base, qall0)],
                                          [(r["fecha"], pm.get((r["fecha"][:10], r["home"], r["away"])), q, r["y"]) for r, q in zip(rk, qallk)],
                                          corte, "NFL")
    return out


def main():
    out = {"futbol": correr_futbol(), "nfl": correr_nfl()}
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_forma_rapida_resultados.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresultados en", ruta)


if __name__ == "__main__":
    main()
