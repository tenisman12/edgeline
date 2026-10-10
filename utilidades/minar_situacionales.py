# -*- coding: utf-8 -*-
"""
utilidades/minar_situacionales.py - angulos situacionales (calendario y desgaste) contra el modelo, con un solo metodo.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-08_situacionales_tanda1.md

Metodo (el mismo para todos los deportes):
  1. Probabilidad del modelo AS-OF partido por partido (sin ver el futuro):
       NHL, NBA, NCAA basquet, NFL, NCAAF -> la lista `cal` de entrenar(), emparejada a su partido.
       Beisbol -> entrenar_logistica con el 35 % mas antiguo predice el 35-70 %; con el 70 % predice el 30 % final.
       Futbol -> futbol.entrenar reentrenado por bloques de 30 dias solo con lo anterior.
  2. 70 % mas antiguo: se ajusta  logit(q) = a*logit(p) + b  (base)  y  a*logit(p) + b + beta*x  (angulo).
  3. 30 % mas reciente (se mira una vez): log-loss pareado base - angulo, z, mitades, calibracion en los activos.
  4. Pasa si: beta en la direccion registrada, z >= 2.0, mejora en las dos mitades, |p media - tasa| <= 0.04 en
     los activos y n activo >= 300 en el 30 %.
  5. NFL y futbol: se repite con la probabilidad sin vig del cierre como base (contra el mercado).
No toca modelos/ ni nucleo/.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_situacionales.py --deporte hockey,nba,ncaamb,nfl,ncaafb,beisbol,futbol
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io as _io, json, math, os, sys
from collections import defaultdict, Counter

CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO)
from nucleo import io  # noqa: E402

BASE = io.BASE
SALIDA_MD = os.path.join(CODIGO, "trabajo", "minar")
RESULTADOS = []
ULTIMO = {}   # deporte -> (filas, calendario): lo reusan otros scripts de minado


# ------------------------------------------------------------------ utilidades numericas
def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sig(x):
    if x < -35: return 1e-15
    if x > 35: return 1 - 1e-15
    return 1 / (1 + math.exp(-x))


def _ll(q, y):
    q = min(max(q, 1e-9), 1 - 1e-9)
    return -(y * math.log(q) + (1 - y) * math.log(1 - q))


def _resolver(A, b):
    n = len(b); M = [A[i][:] + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12: return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1): M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def _logistica(X, Y, iters=30, l2=1e-4):
    """Newton (IRLS). X: lista de vectores (con el intercepto incluido)."""
    d = len(X[0]); w = [0.0] * d; w[0] = 1.0 if d > 1 else 0.0
    for _ in range(iters):
        g = [0.0] * d; H = [[0.0] * d for _ in range(d)]
        for x, y in zip(X, Y):
            z = sum(wi * xi for wi, xi in zip(w, x)); p = _sig(z); r = p - y; s = p * (1 - p)
            for i in range(d):
                g[i] += r * x[i]
                for j in range(d): H[i][j] += s * x[i] * x[j]
        for i in range(d): g[i] += l2 * w[i]; H[i][i] += l2
        paso = _resolver(H, g)
        if paso is None: break
        w = [wi - si for wi, si in zip(w, paso)]
        if max(abs(s) for s in paso) < 1e-8: break
    return w


# ------------------------------------------------------------------ evaluador unico
def evaluar(filas, codigo, nombre, liga, signo, corte=None, base_nombre="modelo"):
    """filas: dicts con fecha, p, y, x (x None = sin dato -> fuera de esta prueba). signo: +1 / -1 esperado."""
    F = [r for r in filas if r.get("x") is not None and r.get("p") is not None and r.get("y") is not None]
    F.sort(key=lambda r: (r["fecha"], r.get("gp", "")))
    if len(F) < 200:
        return _guardar(codigo, nombre, liga, base_nombre, {"veredicto": "muestra insuficiente", "n": len(F)})
    if corte is None:
        i70 = int(len(F) * 0.7)
    else:
        i70 = next((i for i, r in enumerate(F) if r["fecha"] >= corte), len(F))
    tr, te = F[:i70], F[i70:]
    act_tr = [r for r in tr if r["x"] != 0]; act_te = [r for r in te if r["x"] != 0]
    if len(act_tr) < 30 or not te:
        return _guardar(codigo, nombre, liga, base_nombre, {"veredicto": "muestra insuficiente", "n_activo_prueba": len(act_te),
                                                            "n_activo_explorar": len(act_tr)})
    Ytr = [r["y"] for r in tr]
    w0 = _logistica([[1.0, _lg(r["p"])] for r in tr], Ytr)
    w1 = _logistica([[1.0, _lg(r["p"]), float(r["x"])] for r in tr], Ytr)
    beta = w1[2]
    d = []; q0s = []; q1s = []
    for r in te:
        L = _lg(r["p"])
        q0 = _sig(w0[0] + w0[1] * L); q1 = _sig(w1[0] + w1[1] * L + w1[2] * r["x"])
        d.append(_ll(q0, r["y"]) - _ll(q1, r["y"])); q0s.append(q0); q1s.append(q1)
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / max(n - 1, 1)) or 1e-12
    z = m / (sd / math.sqrt(n))
    h = n // 2
    m1 = sum(d[:h]) / max(h, 1); m2 = sum(d[h:]) / max(n - h, 1)
    idx = [i for i, r in enumerate(te) if r["x"] != 0]
    na = len(idx)
    if na:
        ya = sum(te[i]["y"] for i in idx) / na
        cal1 = sum(q1s[i] for i in idx) / na - ya
        res0 = ya - sum(q0s[i] for i in idx) / na
        # residuo firmado: lo que el modelo falla en la direccion del angulo (x>0 favorece al local)
        sres = sum((te[i]["y"] - q0s[i]) * (1 if te[i]["x"] > 0 else -1) for i in idx) / na
    else:
        ya = cal1 = res0 = sres = None
    dir_ok = (beta > 0) == (signo > 0)
    if na < 300:
        ver = "muestra insuficiente"
    elif dir_ok and z >= 2.0 and m1 > 0 and m2 > 0 and abs(cal1) <= 0.04:
        ver = "pasa"
    else:
        ver = "no pasa"
    out = {"n_prueba": n, "n_activo_prueba": na, "n_explorar": len(tr), "beta": round(beta, 4),
           "efecto_pp_por_unidad": round(25 * beta, 2), "direccion_ok": dir_ok,
           "mejora_milesimas": round(1000 * m, 3), "z": round(z, 2), "mitades": [round(1000 * m1, 3), round(1000 * m2, 3)],
           "residuo_firmado_pp": None if sres is None else round(100 * sres, 2),
           "calibracion_activos": None if cal1 is None else round(cal1, 4), "veredicto": ver,
           "desde_prueba": te[0]["fecha"]}
    return _guardar(codigo, nombre, liga, base_nombre, out)


def _guardar(codigo, nombre, liga, base_nombre, out):
    out.update({"codigo": codigo, "angulo": nombre, "liga": liga, "base": base_nombre})
    RESULTADOS.append(out)
    if "z" in out:
        print("  %-4s %-44s %-7s %-8s n %5d act %5d  beta %+.3f (%+.1f pp/u)  mej %+.3f  z %+5.2f  mit %+.3f/%+.3f  res %+5.1f pp  cal %+.3f  -> %s" % (
            codigo, nombre[:44], liga[:7], base_nombre[:8], out["n_prueba"], out["n_activo_prueba"], out["beta"],
            out["efecto_pp_por_unidad"], out["mejora_milesimas"], out["z"], out["mitades"][0], out["mitades"][1],
            out["residuo_firmado_pp"] or 0.0, out["calibracion_activos"] or 0.0, out["veredicto"].upper()))
    else:
        print("  %-4s %-44s %-7s %-8s %s %s" % (codigo, nombre[:44], liga[:7], base_nombre[:8], out["veredicto"].upper(),
                                                  {k: v for k, v in out.items() if k.startswith("n")}))
    return out


# ------------------------------------------------------------------ calendario por equipo
def _d(s): return dt.date.fromisoformat(str(s)[:10])


class Calendario:
    """Juegos de cada equipo en orden. Cada juego: dict con fecha (date), gp, local (bool), gf, ga, rival, extra."""

    def __init__(self):
        self.t = defaultdict(list); self.pos = {}

    def agregar(self, equipo, fecha, gp, local, gf, ga, rival, **extra):
        self.t[equipo].append(dict(fecha=_d(fecha), gp=str(gp), local=local, gf=gf, ga=ga, rival=rival, **extra))

    def cerrar(self):
        for e, L in self.t.items():
            L.sort(key=lambda g: (g["fecha"], g["gp"]))
            for i, g in enumerate(L): self.pos[(e, g["gp"])] = i

    def i(self, e, gp): return self.pos.get((e, str(gp)))

    def prev(self, e, gp, k=1):
        i = self.i(e, gp)
        return self.t[e][i - k] if i is not None and i - k >= 0 else None

    def sig(self, e, gp):
        i = self.i(e, gp)
        return self.t[e][i + 1] if i is not None and i + 1 < len(self.t[e]) else None

    def actual(self, e, gp):
        i = self.i(e, gp)
        return self.t[e][i] if i is not None else None

    def descanso(self, e, gp):
        a, p = self.actual(e, gp), self.prev(e, gp)
        return (a["fecha"] - p["fecha"]).days if a and p else None

    def en_ventana(self, e, gp, dias):
        i = self.i(e, gp)
        if i is None: return None
        f = self.t[e][i]["fecha"]; c = 0; j = i - 1
        while j >= 0 and (f - self.t[e][j]["fecha"]).days <= dias:
            c += 1; j -= 1
        return c

    def visitas_seguidas(self, e, gp, incluye_actual=True):
        i = self.i(e, gp)
        if i is None: return None
        j = i if incluye_actual else i - 1; c = 0
        while j >= 0 and not self.t[e][j]["local"]:
            c += 1; j -= 1
        return c

    def dias_seguidos(self, e, gp):
        """dias consecutivos con juego antes de hoy."""
        i = self.i(e, gp)
        if i is None: return None
        f = self.t[e][i]["fecha"]; fechas = {g["fecha"] for g in self.t[e][:i]}; c = 0
        while (f - dt.timedelta(days=c + 1)) in fechas: c += 1
        return c


def _diff(a, b):
    return None if a is None or b is None else a - b


def _ind(v): return 1 if v else 0


# ------------------------------------------------------------------ as-of desde `cal` (hockey, nba, americano)
def asof_cal(mod, liga, fn):
    orig_j = mod._juegos
    todos = orig_j(liga)
    CUR = [None]; recs = []

    class _It(list):
        def __iter__(self):
            for it in list.__iter__(self):
                CUR[0] = it
                yield it

    orig_f = getattr(mod, fn)

    def _w(*a, **k):
        recs.append(CUR[0]); return orig_f(*a, **k)
    mod._juegos = lambda l=None: _It(orig_j(l))
    setattr(mod, fn, _w)
    try:
        est = mod.entrenar(liga)
    finally:
        mod._juegos = orig_j; setattr(mod, fn, orig_f)
    cal = est["cal"]
    if len(cal) != len(recs):
        raise RuntimeError("alineacion rota: cal %d, registros %d" % (len(cal), len(recs)))
    return todos, est, cal, recs


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ HOCKEY
def correr_hockey(liga="NHL"):
    """liga: NHL (por defecto) o SHL, LIIGA, AHL, DEL (mismo modelo entrenado por liga, 10-oct-2026)."""
    from modelos import hockey as H
    print("\nHOCKEY (%s): prediccion as-of del modelo (con su factor de segunda noche)" % liga)
    todos, est, cal, recs = asof_cal(H, liga, "_aplicar_b2b")
    C = Calendario()
    for f, gp, h, a in todos:
        gh, ga = _num(h.get("goals")), _num(h.get("goals_opp"))
        if gh is None or ga is None: continue
        fin = (h.get("ended_in") or "").strip()
        ot = (fin in ("OT", "SO")) if fin else None      # None = el archivo no dice como termino (temporadas viejas)
        for row, loc, gf, gc, riv in ((h, True, gh, ga, a.get("team")), (a, False, ga, gh, h.get("team"))):
            C.agregar(row.get("team"), f, gp, loc, gf, gc, riv, ot=ot, pim=_num(row.get("pim")),
                      portero=(row.get("starter_goalie") or "").strip() or None)
    C.cerrar()
    filas = []
    for (p, y), (f, gp, h, a) in zip(cal, recs):
        th, ta = h.get("team"), a.get("team")
        rh, ra = C.descanso(th, gp), C.descanso(ta, gp)
        if rh is None or ra is None: continue
        bh, ba = rh == 1, ra == 1
        r = dict(fecha=f, gp=gp, p=p, y=y, home=th, away=ta)
        ph, pa = C.prev(th, gp), C.prev(ta, gp)
        sa, nh = C.sig(ta, gp), C.actual(th, gp)
        r["H1"] = _ind(ba and not bh)
        r["H2"] = _ind(bh and not ba)
        dd = rh - ra
        r["H4"] = (1 if dd == 1 else -1) if abs(dd) == 1 else 0
        def tres_en_4(e):
            return (C.en_ventana(e, gp, 3) or 0) >= 2
        r["H6"] = _ind(tres_en_4(ta)) - _ind(tres_en_4(th))
        r["H7"] = (C.en_ventana(ta, gp, 7) or 0) - (C.en_ventana(th, gp, 7) or 0)
        r["H8"] = _ind(rh >= 7) - _ind(ra >= 7)
        r["H13"] = min(max((C.visitas_seguidas(ta, gp) or 1) - 1, 0), 5)
        r["H14"] = _ind((C.visitas_seguidas(th, gp, incluye_actual=False) or 0) >= 3)
        r["H15"] = _ind(sa is not None and sa["local"] and (C.visitas_seguidas(ta, gp) or 0) >= 3)
        x16 = 0
        if ph and pa and ph["rival"] == ta and ph["gp"] == pa["gp"] and (nh["fecha"] - ph["fecha"]).days <= 3:
            x16 = 1 if ph["gf"] < ph["ga"] else -1
        r["H16"] = x16
        ot_ok = ph is not None and pa is not None and ph["ot"] is not None and pa["ot"] is not None
        r["H17"] = (_ind(pa["ot"]) - _ind(ph["ot"])) if ot_ok else None
        r["H18"] = None if not (ph and pa and ph["pim"] is not None and pa["pim"] is not None) else (pa["pim"] - ph["pim"]) / 10.0
        r["H21"] = _ind(ph and ph["ga"] - ph["gf"] >= 4) - _ind(pa and pa["ga"] - pa["gf"] >= 4)
        r["H22"] = (_ind(ph["ot"] and ph["gf"] < ph["ga"]) - _ind(pa["ot"] and pa["gf"] < pa["ga"])) if ot_ok else None
        # porteros
        def portero_info(e):
            i = C.i(e, gp); act = C.t[e][i]["portero"]
            if not act: return None
            prev = [g["portero"] for g in C.t[e][max(0, i - 10):i] if g["portero"]]
            if len(prev) < 5: return None
            usual = Counter(prev).most_common(1)[0][0]
            c = 0; j = i - 1
            while j >= 0 and C.t[e][j]["portero"] == act: c += 1; j -= 1
            return act != usual, min(c, 10)
        ih, ia = portero_info(th), portero_info(ta)
        if ih and ia:
            r["H19"] = _ind(ba and ia[0]) - _ind(bh and ih[0])
            r["H20"] = (ia[1] - ih[1]) / 10.0
        else:
            r["H19"] = r["H20"] = None
        filas.append(r)
    print("  partidos con descanso conocido: %d (de %d predicciones as-of)" % (len(filas), len(cal)))
    ULTIMO[liga] = (filas, C)
    defs = [("H1", "visita en segunda noche, local descansado", +1), ("H2", "local en segunda noche, visita descansada", -1),
            ("H4", "un dia de diferencia de descanso", +1), ("H6", "tercer juego en 4 noches", +1),
            ("H7", "carga de 7 dias", +1), ("H8", "regreso de pausa de 7+ dias", -1), ("H13", "gira larga del visitante", +1),
            ("H14", "regreso a casa tras gira de 3+", -1), ("H15", "ultimo juego de gira del visitante", -1),
            ("H16", "ida y vuelta: revancha inmediata", +1), ("H17", "tras prorroga o shootout", +1),
            ("H18", "partido anterior fisico (castigos)", +1), ("H19", "portero suplente en segunda noche", +1),
            ("H20", "carga del portero", +1), ("H21", "tras perder por 4 o mas", +1), ("H22", "tras perder en prorroga/SO", +1)]
    for cod, nom, s in defs:
        evaluar([dict(r, x=r[cod]) for r in filas], cod, nom, liga, s)


# ------------------------------------------------------------------ BASQUET
def correr_basquet(liga):
    from modelos import nba as N
    print("\nBASQUET %s: prediccion as-of del modelo" % liga)
    todos, est, cal, recs = asof_cal(N, liga, "_vistas")
    w = est.get("w", 0.5)
    C = Calendario()
    for f, gp, h, a in todos:
        gh, ga = _num(h.get("points")), _num(h.get("points_opp"))
        if gh is None or ga is None: continue
        mins = _num(h.get("nba_min"))
        ot = bool(liga == "NBA" and mins and mins > 241)
        for row, loc, gf, gc, riv in ((h, True, gh, ga, a.get("team")), (a, False, ga, gh, h.get("team"))):
            C.agregar(row.get("team"), f, gp, loc, gf, gc, riv, ot=ot)
    C.cerrar()
    filas = []
    for (pe, psc, y), (f, gp, h, a) in zip(cal, recs):
        th, ta = h.get("team"), a.get("team")
        rh, ra = C.descanso(th, gp), C.descanso(ta, gp)
        if rh is None or ra is None or rh > 30 or ra > 30: continue   # primer juego de temporada fuera
        r = dict(fecha=f, gp=gp, p=w * pe + (1 - w) * psc, y=y, home=th, away=ta)
        ph, pa = C.prev(th, gp), C.prev(ta, gp)
        r["K1"] = _ind(ra == 1) - _ind(rh == 1)
        r["K2"] = _ind((C.en_ventana(ta, gp, 3) or 0) >= 2) - _ind((C.en_ventana(th, gp, 3) or 0) >= 2)
        r["K3"] = max(-2, min(2, rh - ra))
        r["K4"] = _ind(rh >= 4) - _ind(ra >= 4)
        r["K8a"] = min(max((C.visitas_seguidas(ta, gp) or 1) - 1, 0), 5)
        r["K8b"] = _ind((C.visitas_seguidas(th, gp, incluye_actual=False) or 0) >= 3)
        r["K10"] = _ind(ph and ph["ga"] - ph["gf"] >= 20) - _ind(pa and pa["ga"] - pa["gf"] >= 20)
        r["K11"] = (_ind(pa and pa["ot"]) - _ind(ph and ph["ot"])) if liga == "NBA" else None
        filas.append(r)
    print("  partidos: %d (de %d predicciones as-of)" % (len(filas), len(cal)))
    ULTIMO[liga] = (filas, C)
    defs = [("K1", "segunda noche", +1), ("K2", "tercer juego en 4 noches", +1), ("K3", "diferencia de descanso", +1),
            ("K4", "descanso de 4+ dias", +1), ("K8a", "gira larga del visitante", +1), ("K8b", "regreso a casa tras gira 3+", -1),
            ("K10", "tras perder por 20 o mas", +1), ("K11", "tras prorroga", +1)]
    for cod, nom, s in defs:
        if cod == "K11" and liga != "NBA": continue
        evaluar([dict(r, x=r[cod]) for r in filas], cod, nom, liga, s)


# ------------------------------------------------------------------ AMERICANO
_ALIAS_NFL = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def _ml_prob(ml):
    ml = _num(ml)
    if ml is None or ml == 0: return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def correr_americano(liga):
    from modelos import americano as A
    print("\n%s: prediccion as-of del modelo" % liga)
    todos, est, cal, recs = asof_cal(A, liga, "_vistas")
    w = est.get("w", 0.5)
    C = Calendario()
    for f, gp, h, a in todos:
        gh, ga = _num(h.get("points")), _num(h.get("points_opp"))
        if gh is None or ga is None: continue
        for row, loc, gf, gc, riv in ((h, True, gh, ga, a.get("team")), (a, False, ga, gh, h.get("team"))):
            C.agregar(row.get("team"), f, gp, loc, gf, gc, riv)
    C.cerrar()
    dias = Counter(_d(f).weekday() for f, gp, h, a in todos)
    print("  dias de la semana de los juegos (0=lunes ... 6=domingo):", dict(sorted(dias.items())))
    # lineas de cierre y tiempo extra (solo NFL)
    lin = {}
    if liga == "NFL":
        ruta = os.path.join(BASE, "datos", "mercado", "nfl_lineas.csv")
        if os.path.exists(ruta):
            with _io.open(ruta, encoding="utf-8-sig") as fh:
                for x in csv.DictReader(fh):
                    hm, aw = _ALIAS_NFL.get(x["home_team"], x["home_team"]), _ALIAS_NFL.get(x["away_team"], x["away_team"])
                    ph_, pa_ = _ml_prob(x.get("home_moneyline")), _ml_prob(x.get("away_moneyline"))
                    pm = ph_ / (ph_ + pa_) if ph_ and pa_ else None
                    lin[(x["gameday"][:10], hm, aw)] = (pm, x.get("overtime") == "1", _num(x.get("home_moneyline")),
                                                         _num(x.get("away_moneyline")), x.get("div_game") == "1",
                                                         x.get("home_coach"), x.get("away_coach"))
    def _clave(f, h, a):
        return (f[:10], _ALIAS_NFL.get(h, h), _ALIAS_NFL.get(a, a))
    filas = []
    for (pe, psc, y), (f, gp, h, a) in zip(cal, recs):
        th, ta = h.get("team"), a.get("team")
        rh, ra = C.descanso(th, gp), C.descanso(ta, gp)
        if rh is None or ra is None or rh > 40 or ra > 40: continue
        r = dict(fecha=f, gp=gp, p=w * pe + (1 - w) * psc, y=y, home=th, away=ta)
        ph, pa = C.prev(th, gp), C.prev(ta, gp)
        info = lin.get(_clave(f, th, ta))
        r["pm"] = info[0] if info else None
        if info:
            r["ml_h"], r["ml_a"], r["div"], r["coach_h"], r["coach_a"] = info[2], info[3], info[4], info[5], info[6]
        if liga == "NFL":
            r["N4"] = _ind(pa and pa["fecha"].weekday() == 0) - _ind(ph and ph["fecha"].weekday() == 0)
        r["N5"] = (1 if (rh >= 13 and ra <= 5) else (-1 if (ra >= 13 and rh <= 5) else 0))
        r["N8"] = _ind(pa is not None and not pa["local"])
        r["N12"] = _ind(ph and ph["ga"] - ph["gf"] >= 20) - _ind(pa and pa["ga"] - pa["gf"] >= 20)
        if liga == "NFL":
            def gano_ot(e, g):
                if not g: return False
                rv = g["rival"]; k = _clave(g["fecha"].isoformat(), e if g["local"] else rv, rv if g["local"] else e)
                inf = lin.get(k)
                return bool(inf and inf[1] and g["gf"] > g["ga"])
            r["N13"] = _ind(gano_ot(ta, pa)) - _ind(gano_ot(th, ph)) if lin else None
        filas.append(r)
    con_m = sum(1 for r in filas if r.get("pm") is not None)
    ULTIMO[liga] = (filas, C)
    print("  partidos: %d (de %d predicciones as-of); con cierre: %d" % (len(filas), len(cal), con_m))
    defs = [("N4", "tras jugar lunes", +1), ("N5", "sale de bye contra semana corta", +1),
            ("N8", "segundo juego seguido de visita", +1), ("N12", "tras perder por 20 o mas", +1),
            ("N13", "tras ganar en tiempo extra", +1)]
    for cod, nom, s in defs:
        if cod in ("N4", "N13") and liga != "NFL": continue
        evaluar([dict(r, x=r.get(cod)) for r in filas], cod, nom, liga, s)
        if con_m:
            evaluar([dict(r, x=r.get(cod), p=r["pm"]) for r in filas if r.get("pm") is not None], cod, nom, liga, s,
                    base_nombre="cierre")


# ------------------------------------------------------------------ BEISBOL
def _hora(s):
    s = (s or "").strip().upper()
    try:
        t = dt.datetime.strptime(s, "%I:%M %p"); return t.hour + t.minute / 60
    except ValueError:
        return None


def _ip(x):
    v = _num(x)
    if v is None: return None
    ent = int(v); fr = round((v - ent) * 10)
    return ent + fr / 3.0


def _abridores(liga):
    """(gamePk, equipo) -> lista cronologica de aperturas del abridor de ese juego: [(fecha, ip), ...] previas."""
    nombre = {"LMP": "lmp_lanzadores.csv", "NPB": "npb_lanzadores.csv"}.get(liga)
    if not nombre: return None
    ruta = os.path.join(BASE, "datos", "abridores", nombre)
    if not os.path.exists(ruta): return None
    porjug = defaultdict(list); juego = {}
    with _io.open(ruta, encoding="utf-8-sig") as fh:
        for x in csv.DictReader(fh):
            ab = str(x.get("abridor") or "").strip() in ("1", "1.0", "True", "true") or str(x.get("orden_salida") or "").strip() in ("1", "1.0")
            if not ab: continue
            ip = _ip(x.get("ip"))
            if ip is None: continue
            porjug[x.get("player_id") or x.get("jugador")].append((_d(x["game_date"]), str(x["game_id"]), ip))
            juego[(str(x["game_id"]), x.get("team"))] = x.get("player_id") or x.get("jugador")
    for k in porjug: porjug[k].sort()
    return porjug, juego


def correr_beisbol(ligas):
    from nucleo import features as Fz
    from modelos import beisbol as B
    from nucleo import abridores as AB
    print("\nBEISBOL: logistica entrenada con el 35 %% / 70 %% mas antiguo (%s)" % ",".join(ligas))
    # calendario desde beisbol.csv
    C = Calendario()
    with _io.open(os.path.join(BASE, "datos", "beisbol.csv"), encoding="utf-8-sig") as fh:
        crudo = list(csv.DictReader(fh))
    for x in crudo:
        if x.get("league") not in ligas: continue
        gf, gc = _num(x.get("runs")), _num(x.get("runs_opp"))
        if gf is None or gc is None: continue
        C.agregar((x["league"], x["team"]), x["game_date"], x["gamePk"], str(x.get("is_home")) in ("1", "1.0", "True"),
                  gf, gc, x["opp"], hora=_hora(x.get("primer_pitcheo")), ip=_ip(x.get("pit_inningsPitched")))
    C.cerrar()
    todas = []
    for liga in ligas:
        feats, _ = Fz.construir("beisbol", liga, 5)
        lg = io.norm(liga)
        G = [r for r in feats if r["league"] == lg and r.get("y_home") is not None]
        G.sort(key=lambda r: r["game_date"])
        if len(G) < 600:
            print("  %s: muestra insuficiente (%d)" % (liga, len(G))); continue
        i35, i70 = int(len(G) * 0.35), int(len(G) * 0.70)
        VAB = AB.historicos(io.BASE, lg) if AB.aplica(lg) else {}
        K_AB, _esc = AB.coeficientes(lg)
        m1 = B.entrenar_logistica(G[:i35]); m2 = B.entrenar_logistica(G[:i70])
        abr = _abridores(liga)
        n0 = len(todas)
        for k, r in enumerate(G[i35:], start=i35):
            mod = m1 if k < i70 else m2
            p = B.prob(mod, r)
            if VAB:
                vh, va = VAB.get((r["gamePk"], r["home"])), VAB.get((r["gamePk"], r["away"]))
                if vh and va:
                    sh, sa = AB.carreras_salvadas(r.get("df_home"), vh), AB.carreras_salvadas(r.get("df_away"), va)
                    p = _sig(_lg(p) + K_AB * (sh - sa))
            gp = str(r["gamePk"]); eh, ea = (liga, r["home"]), (liga, r["away"])
            if C.i(eh, gp) is None or C.i(ea, gp) is None: continue
            rh, ra = C.descanso(eh, gp), C.descanso(ea, gp)
            if rh is None or ra is None or rh > 20 or ra > 20: continue
            f = r["game_date"][:10]
            fila = dict(fecha=f, gp=gp, p=p, y=r["y_home"], liga=liga, corte=G[i70]["game_date"][:10], home=eh, away=ea)
            ah, aa = C.actual(eh, gp), C.actual(ea, gp)
            ph, pa = C.prev(eh, gp), C.prev(ea, gp)
            def dia_tras_noche(act, pr):
                if not act or not pr or act["hora"] is None or pr["hora"] is None: return None
                return (act["fecha"] - pr["fecha"]).days == 1 and pr["hora"] >= 17 and act["hora"] < 17
            dn_h, dn_a = dia_tras_noche(ah, ph), dia_tras_noche(aa, pa)
            fila["B1"] = None if dn_h is None or dn_a is None else _ind(dn_a) - _ind(dn_h)
            fila["B2"] = _ind(rh >= 2) - _ind(ra >= 2)
            fila["B5"] = (min(C.dias_seguidos(ea, gp) or 0, 20) - min(C.dias_seguidos(eh, gp) or 0, 20)) / 10.0
            # serie desde el calendario del local
            Lh = C.t[eh]; i = C.i(eh, gp)
            j = i
            while j - 1 >= 0 and Lh[j - 1]["rival"] == Lh[i]["rival"] and Lh[j - 1]["local"] == Lh[i]["local"] \
                    and (Lh[j]["fecha"] - Lh[j - 1]["fecha"]).days <= 1:
                j -= 1
            num = i - j + 1
            ultimo = not (i + 1 < len(Lh) and Lh[i + 1]["rival"] == Lh[i]["rival"] and Lh[i + 1]["local"] == Lh[i]["local"]
                          and (Lh[i + 1]["fecha"] - Lh[i]["fecha"]).days <= 1)
            fila["B10"] = _ind(num == 1)
            fila["B11"] = _ind(ultimo and num >= 2)
            previos = Lh[j:i]
            if len(previos) >= 2:
                fila["B12"] = _ind(all(g["gf"] < g["ga"] for g in previos)) - _ind(all(g["gf"] > g["ga"] for g in previos))
            else:
                fila["B12"] = 0
            fila["B13"] = min(max((C.visitas_seguidas(ea, gp) or 1) - 1, 0), 12) / 10.0
            fila["B14"] = _ind((C.visitas_seguidas(eh, gp, incluye_actual=False) or 0) >= 6)
            ext = lambda g: bool(g and g["ip"] is not None and g["ip"] >= 9.95)
            fila["B15"] = _ind(ext(pa)) - _ind(ext(ph))
            fila["B21"] = _ind(ph and ph["ga"] - ph["gf"] >= 7) - _ind(pa and pa["ga"] - pa["gf"] >= 7)
            if abr:
                porjug, juego = abr
                def info_abr(team):
                    pid = juego.get((gp, team))
                    if not pid: return None
                    hist = [t for t in porjug[pid] if t[1] != gp and t[0] < _d(f)]
                    if len(hist) < 3: return None
                    corto = sum(t[2] for t in hist[-3:]) / 3 < 3.0
                    desc = (_d(f) - hist[-1][0]).days
                    return corto, desc <= 4
                ih, ia = info_abr(r["home"]), info_abr(r["away"])
                if ih and ia:
                    fila["B18"] = _ind(ia[0]) - _ind(ih[0]); fila["B19"] = _ind(ia[1]) - _ind(ih[1])
            todas.append(fila)
        print("  %s: %d partidos evaluables (prueba desde %s)" % (liga, len(todas) - n0, G[i70]["game_date"][:10]))
    ULTIMO["BEISBOL"] = (todas, C)
    defs = [("B1", "dia tras noche", +1), ("B2", "primer juego tras dia libre", +1), ("B5", "dias seguidos jugando", +1),
            ("B10", "primer juego de serie", +1), ("B11", "ultimo juego de serie (getaway)", +1),
            ("B12", "evitar la barrida", +1), ("B13", "gira larga del visitante", +1),
            ("B14", "regreso a casa tras gira de 6+", -1), ("B15", "tras extra innings", +1),
            ("B18", "abridor corto (LMP/NPB)", +1), ("B19", "abridor con 4 dias o menos (LMP/NPB)", +1),
            ("B21", "tras perder por 7 o mas", +1)]
    # cada liga con su propio corte 70/30; se evalua junto (todas) y MLB sola
    for cod, nom, s in defs:
        F = [dict(r, x=r.get(cod)) for r in todas]
        _evaluar_por_corte(F, cod, nom, "TODAS", s)
        if cod not in ("B18", "B19"):
            _evaluar_por_corte([r for r in F if r["liga"] == "MLB"], cod, nom, "MLB", s)


def _evaluar_por_corte(F, cod, nom, etiqueta, s):
    """Cada liga trae su propio corte 70/30; se marca 'prueba' por fila y se junta."""
    for r in F: r["_te"] = r["fecha"] >= r["corte"]
    tr = [r for r in F if not r["_te"]]; te = [r for r in F if r["_te"]]
    # truco: fechas ficticias para que el evaluador respete el corte por liga
    G = [dict(r, fecha=("0" + r["fecha"])) for r in tr] + [dict(r, fecha=("1" + r["fecha"])) for r in te]
    out = evaluar(G, cod, nom, etiqueta, s, corte="1")
    if out and out.get("desde_prueba"): out["desde_prueba"] = out["desde_prueba"][1:]


# ------------------------------------------------------------------ FUTBOL
LIGAS_FUT = ["Premier", "LaLiga", "SerieA", "Bundesliga", "Ligue1", "LigaMX", "MLS"]


def correr_futbol(bloque=30):
    from modelos import futbol as FU
    print("\nFUTBOL: modelo reentrenado por bloques de %d dias solo con lo anterior" % bloque)
    C = Calendario()
    with _io.open(os.path.join(BASE, "datos", "futbol.csv"), encoding="utf-8-sig") as fh:
        crudo = list(csv.DictReader(fh))
    for x in crudo:
        gf, gc = _num(x.get("goals")), _num(x.get("goals_opp"))
        if gf is None or gc is None: continue
        C.agregar(x["team"], x["game_date"], x["gamePk"], str(x.get("is_home")) in ("1", "1.0", "True"), gf, gc, x["opp"])
    ruta_ch = os.path.join(BASE, "datos", "equipos", "espn_champions_equipos.csv")
    n_ch = 0
    if os.path.exists(ruta_ch):
        eqs = {x["team"] for x in crudo}
        with _io.open(ruta_ch, encoding="utf-8-sig") as fh:
            for x in csv.DictReader(fh):
                if x["team"] in eqs:
                    C.agregar(x["team"], x["game_date"], "ch" + str(x["game_id"]), str(x.get("is_home")) in ("1", "1.0"),
                              None, None, x["opp"]); n_ch += 1
    C.cerrar()
    print("  juegos de Champions agregados al calendario: %d" % n_ch)
    # cierres de Pinnacle
    pin = {}; CUOTAS_FUT = {}
    ruta_c = os.path.join(BASE, "datos", "mercado", "futbol_cuotas.csv")
    if os.path.exists(ruta_c):
        with _io.open(ruta_c, encoding="utf-8-sig") as fh:
            for x in csv.DictReader(fh):
                hh, dd_, aa = (_num(x.get(k)) for k in ("fd_PSCH", "fd_PSCD", "fd_PSCA"))
                if not (hh and dd_ and aa):
                    hh, dd_, aa = (_num(x.get(k)) for k in ("fd_AvgCH", "fd_AvgCD", "fd_AvgCA"))
                if hh and dd_ and aa:
                    s = 1 / hh + 1 / dd_ + 1 / aa
                    pin[str(x["gamePk"])] = (1 / hh) / s
                mx = tuple(_num(x.get(k)) for k in ("fd_MaxH", "fd_MaxD", "fd_MaxA"))
                ps = tuple(_num(x.get(k)) for k in ("fd_PSCH", "fd_PSCD", "fd_PSCA"))
                CUOTAS_FUT[str(x["gamePk"])] = {"max": mx, "pin": ps, "res": x.get("fd_FTR")}
    filas = []
    orig = io.cargar_juegos
    for liga in LIGAS_FUT:
        todos = FU._juegos(liga)
        G = [(f, gp, h, a) for f, gp, h, a in todos if _num(h.get("goals")) is not None and _num(h.get("goals_opp")) is not None]
        if len(G) < 600: continue
        i0 = 300; d0 = _d(G[i0][0]); ultimo = _d(G[-1][0]); n0 = len(filas)
        while d0 <= ultimo:
            d1 = d0 + dt.timedelta(days=bloque)
            blk = [g for g in G if d0.isoformat() <= g[0] < d1.isoformat()]
            if blk:
                corte = d0.isoformat()
                io.cargar_juegos = lambda x, liga=None, _o=orig, _c=corte: [r for r in _o(x, liga) if (r.get("game_date") or "")[:10] < _c]
                try:
                    est = FU.entrenar(liga)
                finally:
                    io.cargar_juegos = orig
                for f, gp, h, a in blk:
                    th, ta = h.get("team"), a.get("team")
                    rr = FU.predecir(est, th, ta, linea_total=2.5, handicap=0.0)
                    if not rr: continue
                    gh, ga = _num(h.get("goals")), _num(h.get("goals_opp"))
                    rh, ra = C.descanso(th, gp), C.descanso(ta, gp)
                    if rh is None or ra is None or rh > 30 or ra > 30: continue
                    ph, pa = C.prev(th, gp), C.prev(ta, gp)
                    def perdio3(g): return bool(g and g["gf"] is not None and g["ga"] - g["gf"] >= 3)
                    filas.append(dict(fecha=f, gp=gp, p=rr["p_home"], pdraw=rr.get("p_draw"), paway=rr.get("p_away"),
                                      home=th, away=ta, cuotas=CUOTAS_FUT.get(str(gp)),
                                      res=("H" if gh > ga else ("D" if gh == ga else "A")),
                                      y=1 if gh > ga else 0, liga=liga, pm=pin.get(str(gp)),
                                      F1=max(-3, min(3, rh - ra)) / 3.0, F13=_ind(perdio3(ph)) - _ind(perdio3(pa))))
            d0 = d1
        print("  %s: %d partidos" % (liga, len(filas) - n0))
    print("  con cierre de Pinnacle: %d de %d" % (sum(1 for r in filas if r["pm"]), len(filas)))
    ULTIMO["FUTBOL"] = (filas, C)
    for cod, nom, s in (("F1", "diferencia de descanso", +1), ("F13", "tras perder por 3 o mas", +1)):
        evaluar([dict(r, x=r[cod]) for r in filas], cod, nom, "7 ligas", s)
        evaluar([dict(r, x=r[cod], p=r["pm"]) for r in filas if r["pm"]], cod, nom, "7 ligas", s, base_nombre="cierre")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", default="hockey,nba,ncaamb,nfl,ncaafb,beisbol,futbol")
    a = ap.parse_args()
    for d in [x.strip() for x in a.deporte.split(",") if x.strip()]:
        if d == "hockey": correr_hockey()
        elif d == "nba": correr_basquet("NBA")
        elif d == "ncaamb": correr_basquet("NCAAMB")
        elif d == "nfl": correr_americano("NFL")
        elif d == "ncaafb": correr_americano("NCAAFB")
        elif d == "beisbol": correr_beisbol(["MLB", "NPB", "KBO", "LMP", "LVBP", "LIDOM", "ABL"])
        elif d == "futbol": correr_futbol()
    k = sum(1 for r in RESULTADOS if "z" in r)
    pasan = [r for r in RESULTADOS if r["veredicto"] == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d pruebas con resultado | falsos 'pasa' esperados por azar ~ %.1f | pasan: %d" % (k, 0.023 * k, len(pasan)))
    for r in pasan:
        print("  PASA  %-4s %-44s %-7s base %-7s efecto %+.1f pp/u  z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["base"],
                                                                          r["efecto_pp_por_unidad"], r["z"]))
    os.makedirs(SALIDA_MD, exist_ok=True)
    ruta = os.path.join(SALIDA_MD, "2026-10-08_situacionales_tanda1_resultados.json")
    previos = []
    if os.path.exists(ruta):
        try:
            previos = json.load(_io.open(ruta, encoding="utf-8"))
        except Exception:
            previos = []
    llaves = {(r["codigo"], r["liga"], r["base"]) for r in RESULTADOS}
    previos = [r for r in previos if (r["codigo"], r["liga"], r["base"]) not in llaves]
    with _io.open(ruta, "w", encoding="utf-8") as fh:
        json.dump(previos + RESULTADOS, fh, ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
