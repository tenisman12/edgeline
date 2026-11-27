# -*- coding: utf-8 -*-
"""
nucleo/capa_angulos.py - CAPA BAYESIANA DE ANGULOS sobre el precio del mercado (27-nov-2026, aprobado por Alejandro).

Idea: el mercado (Pinnacle sin vig o consenso) es la base. Cada angulo es una variable 0/1 (o -1 si favorece al otro
lado) y su efecto se estima TODOS JUNTOS en una regresion logistica con el logit del mercado como offset:

    logit(p) = logit(p_mercado) + b1*x1 + b2*x2 + ...

con prior normal N(0, sd) por coeficiente (sd 0.15-0.20 en logit para los angulos que pasaron el protocolo, 0.06-0.08
para los que no). Asi:
  - los angulos se combinan sumando en logit, pero con pesos estimados en conjunto: si dos se traslapan (local perro que
    viene de derrotas) el ajuste reparte el efecto y no se cuenta dos veces;
  - el prior encoge los efectos de muestra corta hacia 0;
  - el ajuste se repite en cada corrida con los juegos nuevos (posterior actualizado).
El ajuste total por partido se limita a +-TOPE_LOGIT. Un grupo se aplica solo si fuera de muestra (30 % mas reciente)
no empeora la log-loss del mercado.

Grupos v1:
  NFL total   (lado favorecido: under) viento 10-20 mph aire libre, noche >= 20:00 ET, lunes, spread <= 3, ambos >= 10 dias
  LMP ganador (lado favorecido: local)  local perro, visitante perro 35-40 % (x = -1), local 3+ derrotas, visita 3+ victorias
Medicion: proyecto claude/angulos-totales-nfl-2026-11-25.md, claude/angulos-beisbol-clima-totales-2026-11-27.md.

    python nucleo/capa_angulos.py            (ajusta y escribe salida/capa_angulos.json)
Solo stdlib.
"""
import csv, datetime as dt, glob, io, json, math, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(REPO, "salida", "capa_angulos.json")
TOPE_LOGIT = 0.35
FRAC_PRUEBA = 0.30

GRUPOS = {
    "nfl_total": {
        "liga": "nfl", "mercado": "Total", "favorece": "under",
        "angulos": [
            ("VIENTO_10_20", "viento 10-20 mph, aire libre", 0.20),
            ("NOCHE", "kickoff >= 20:00 ET", 0.08),
            ("LUNES", "lunes", 0.08),
            ("SPREAD_LE3", "spread <= 3", 0.08),
            ("DESCANSO10", "ambos con 10+ dias de descanso", 0.06),
        ],
    },
    "lmp_ganador": {
        "liga": "lmp", "mercado": "Ganador", "favorece": "home",
        "angulos": [
            ("LOCAL_PERRO", "local perro", 0.20),
            ("VIS_PERRO_35_40", "visitante perro 35-40 %", 0.20),
            ("LOCAL_3DER", "local viene de 3+ derrotas", 0.15),
            ("VIS_3VIC", "visita viene de 3+ victorias", 0.15),
        ],
    },
}


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sig(z):
    return 1.0 / (1.0 + math.exp(-z))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _imp_am(a):
    a = _f(a)
    if a is None or a == 0:
        return None
    return -a / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)


# ---------------------------------------------------------------- datos historicos
def filas_nfl():
    """(fecha, offset logit p_under sin vig, y=1 si under, x) de datos/mercado/nfl_lineas.csv."""
    ruta = os.path.join(REPO, "datos", "mercado", "nfl_lineas.csv")
    out = []
    if not os.path.exists(ruta):
        return out
    with io.open(ruta, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            hs, as_, L = _f(r.get("home_score")), _f(r.get("away_score")), _f(r.get("total_line"))
            po, pu = _imp_am(r.get("over_odds")), _imp_am(r.get("under_odds"))
            if None in (hs, as_, L, po, pu) or hs + as_ == L:
                continue
            p_under = pu / (po + pu)
            w = _f(r.get("wind"))
            aire = str(r.get("roof") or "") in ("outdoors", "open")
            hora = str(r.get("gametime") or "00:00")
            sp = _f(r.get("spread_line"))
            hr, ar = _f(r.get("home_rest")), _f(r.get("away_rest"))
            x = nfl_x(aire, w, int(hora[:2]) + int(hora[3:5]) / 60.0, str(r.get("weekday")) == "Monday",
                      None if sp is None else abs(sp), hr, ar)
            out.append((r.get("gameday") or r.get("game_date"), _lg(p_under), 1 if hs + as_ < L else 0, x))
    return out


def nfl_x(aire, viento_mph, hora_et, lunes, spread_abs, rest_h, rest_a):
    return [1 if (aire and viento_mph is not None and 10 <= viento_mph < 20) else 0,
            1 if hora_et >= 20 else 0,
            1 if lunes else 0,
            1 if (spread_abs is not None and spread_abs <= 3) else 0,
            1 if (rest_h is not None and rest_a is not None and rest_h >= 10 and rest_a >= 10) else 0]


def filas_lmp():
    """(fecha, offset logit p_local sin vig, y=1 si gana el local, x) de mercado/betexplorer/lmp_*_principal.csv
    (rol regular; la temporada en curso viene con etapa vacia). Las rachas se arman con los mismos archivos, as-of."""
    juegos = []
    for f in sorted(glob.glob(os.path.join(REPO, "mercado", "betexplorer", "lmp_*_principal.csv"))):
        with io.open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("etapa") or "") not in ("Main", ""):
                    continue
                cl, cv = _f(r.get("carreras_local")), _f(r.get("carreras_visita"))
                if cl is None or cv is None or not r.get("fecha"):
                    continue
                juegos.append((r["fecha"], r.get("temporada") or "", r["local"], r["visita"], cl, cv, _f(r.get("ml_local")), _f(r.get("ml_visita"))))
    juegos.sort(key=lambda t: t[0])
    racha = {}
    out = []
    for fecha, temp, loc, vis, cl, cv, dl, dv in juegos:
        rl, rv = racha.get((temp, loc), 0), racha.get((temp, vis), 0)
        if dl and dv and dl > 1 and dv > 1 and cl != cv:
            ph = (1 / dl) / ((1 / dl) + (1 / dv))
            out.append((fecha, _lg(ph), 1 if cl > cv else 0, lmp_x(ph, rl, rv)))
        if cl != cv:
            for eq, gano in ((loc, cl > cv), (vis, cv > cl)):
                r0 = racha.get((temp, eq), 0)
                racha[(temp, eq)] = (r0 + 1 if r0 > 0 else 1) if gano else (r0 - 1 if r0 < 0 else -1)
    return out


def lmp_x(p_home, racha_home, racha_away):
    pa = 1 - p_home
    return [1 if p_home < 0.5 else 0,
            -1 if 0.35 <= pa <= 0.40 else 0,
            1 if racha_home <= -3 else 0,
            1 if racha_away >= 3 else 0]


# ---------------------------------------------------------------- ajuste bayesiano (MAP + Laplace)
def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[c][c] != 0:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def _inv(A):
    n = len(A)
    return [list(col) for col in zip(*[_solve(A, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)])]


def ajustar_map(filas, sds):
    k = len(sds)
    b = [0.0] * k
    H = None
    for _ in range(30):
        g = [-b[j] / sds[j] ** 2 for j in range(k)]
        H = [[(-1.0 / sds[i] ** 2 if i == j else 0.0) for j in range(k)] for i in range(k)]
        for _, off, y, x in filas:
            p = _sig(off + sum(b[j] * x[j] for j in range(k)))
            w = p * (1 - p)
            for i in range(k):
                if x[i]:
                    g[i] += (y - p) * x[i]
                    for j in range(k):
                        if x[j]:
                            H[i][j] -= w * x[i] * x[j]
        paso = _solve(H, g)
        b = [b[j] - paso[j] for j in range(k)]
        if max(abs(s) for s in paso) < 1e-7:
            break
    cov = _inv([[-v for v in row] for row in H])
    return b, [math.sqrt(max(cov[j][j], 0)) for j in range(k)]


def _ll(off, y, b, x):
    p = _sig(off + sum(bi * xi for bi, xi in zip(b, x)))
    return math.log(p) if y else math.log(1 - p)


def ajustar_grupo(gid, filas):
    g = GRUPOS[gid]
    sds = [a[2] for a in g["angulos"]]
    filas = sorted(filas, key=lambda t: t[0])
    n = len(filas)
    corte = int(n * (1 - FRAC_PRUEBA))
    b_tr, _ = ajustar_map(filas[:corte], sds)
    d = [_ll(o, y, b_tr, x) - _ll(o, y, [0.0] * len(sds), x) for _, o, y, x in filas[corte:]]
    m = sum(d) / len(d)
    sd = math.sqrt(sum((v - m) ** 2 for v in d) / max(len(d) - 1, 1))
    z = m / sd * math.sqrt(len(d)) if sd > 0 else 0.0
    b, se = ajustar_map(filas, sds)
    angs = []
    for (cod, desc, psd), bj, sj in zip(g["angulos"], b, se):
        nj = sum(1 for _, _, _, x in filas if x[[a[0] for a in g["angulos"]].index(cod)])
        angs.append({"codigo": cod, "descripcion": desc, "prior_sd": psd, "beta": round(bj, 4), "sd_post": round(sj, 4),
                     "pp_aprox_50": round(100 * (_sig(bj) - 0.5), 2), "n_activo": nj})
    return {"liga": g["liga"], "mercado": g["mercado"], "favorece": g["favorece"], "n": n,
            "desde": filas[0][0] if filas else None, "hasta": filas[-1][0] if filas else None,
            "prueba": {"n": len(d), "mejora_logloss_media": round(m, 6), "z": round(z, 2), "corte": filas[corte][0] if d else None},
            "activo": z >= 0, "angulos": angs}


def ajustar(escribir=True):
    res = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "tope_logit": TOPE_LOGIT,
           "metodo": "logistica con offset logit(p mercado sin vig), prior N(0, sd) por angulo, MAP + Laplace; prueba 30 % mas reciente",
           "grupos": {}}
    try:   # los grupos que se ajustan en otro script (nhl_ganador: utilidades/ajustar_capa_nhl.py) se conservan
        with io.open(SALIDA, encoding="utf-8") as fh:
            for gid, g in (json.load(fh).get("grupos") or {}).items():
                if gid not in ("nfl_total", "lmp_ganador"):
                    res["grupos"][gid] = g
    except Exception:
        pass
    for gid, fn in (("nfl_total", filas_nfl), ("lmp_ganador", filas_lmp)):
        try:
            fl = fn()
            if len(fl) >= 300:
                res["grupos"][gid] = ajustar_grupo(gid, fl)
        except Exception as e:  # un grupo roto no tumba al resto
            res["grupos"][gid] = {"error": str(e), "activo": False}
    if escribir:
        with io.open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


# ---------------------------------------------------------------- aplicacion en vivo
_CACHE = None


def _coef():
    global _CACHE
    if _CACHE is None:
        try:
            with io.open(SALIDA, encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    return _CACHE


def _racha_num(s):
    s = str(s or "")
    try:
        n = int(s[1:])
    except ValueError:
        return 0
    return n if s[:1] == "W" else -n if s[:1] == "L" else 0


_HIST = None


def _x_historial(rec, codigos):
    """x de cada angulo del partido segun salida/historial_angulos.csv (ultimo registro por codigo; x > 0 = local)."""
    global _HIST
    if _HIST is None:
        _HIST = {}
        try:
            with io.open(os.path.join(REPO, "salida", "historial_angulos.csv"), encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if r.get("codigo") and r["codigo"] != "_TODOS":
                        _HIST.setdefault((r.get("liga"), str(r.get("id"))), {})[r["codigo"]] = _f(r.get("x")) or 0.0
        except Exception:
            pass
    d = _HIST.get((rec.get("liga"), str(rec.get("id"))))
    if d is None:
        return None
    return [d.get(c, 0.0) for c in codigos]


def x_partido(rec, gid, p_mercado_home=None):
    """Vector de angulos del partido para el grupo (None si no aplica o falta el dato clave)."""
    if gid == "nfl_total":
        cl = rec.get("clima") or {}
        vk = _f(cl.get("viento_kmh"))
        aire = not cl.get("techado", True)
        try:
            h, mi = str(rec.get("hora") or "00:00").split(":")[:2]
            f = dt.date.fromisoformat(rec["fecha"])
        except Exception:
            return None
        dst = 3 <= f.month <= 10 and not (f.month == 3 and f.day < 8) and not (f.month == 10 and f.day > 31)
        hora_et = int(h) + int(mi) / 60.0 + (2 if dst else 1)       # CDMX UTC-6; ET UTC-4 (verano) / UTC-5 (invierno)
        sp = _f((rec.get("cuotas") or {}).get("spread_home"))
        des = ((rec.get("modelo") or {}).get("motor_puntos") or {}).get("descanso") or {}
        return nfl_x(aire, None if vk is None else vk / 1.609344, hora_et, f.weekday() == 0,
                     None if sp is None else abs(sp), _f(des.get("home")), _f(des.get("away")))
    if gid == "nhl_ganador":
        return _x_historial(rec, [x["codigo"] for x in ((_coef().get("grupos") or {}).get(gid) or {}).get("angulos") or []])
    if gid == "lmp_ganador":
        if p_mercado_home is None:
            return None
        fo = rec.get("forma") or {}
        return lmp_x(p_mercado_home, _racha_num((fo.get("home") or {}).get("racha")), _racha_num((fo.get("away") or {}).get("racha")))
    return None


def ajuste(rec, tipo, p_mercado_home=None):
    """(delta_logit a favor del lado que favorece el grupo, lado favorecido, [angulos activos]) o (0, None, [])."""
    C = _coef().get("grupos") or {}
    for gid, g in C.items():
        if not g.get("activo") or g.get("liga") != rec.get("liga") or g.get("mercado") != tipo:
            continue
        x = x_partido(rec, gid, p_mercado_home)
        if not x:
            continue
        tot, act = 0.0, []
        for a, xi in zip(g["angulos"], x):
            if xi:
                tot += a["beta"] * xi
                act.append({"codigo": a["codigo"], "descripcion": a["descripcion"], "x": xi, "beta": a["beta"], "sd_post": a["sd_post"]})
        tope = _coef().get("tope_logit", TOPE_LOGIT)
        tot = max(-tope, min(tope, tot))
        return tot, g["favorece"], act
    return 0.0, None, []


def aplicar(rec, tipo, lado, p, p_mercado_home=None):
    """p ajustada para ese lado y la lista de angulos aplicados."""
    d, fav, act = ajuste(rec, tipo, p_mercado_home)
    if not act or d == 0:
        return p, act, 0.0
    s = 1 if lado == fav else -1
    p2 = _sig(_lg(p) + s * d)
    return p2, act, p2 - p


def sombra(rec, tipo, lado, p, p_mercado_home=None):
    """p con los grupos en sombra (se registran, no deciden): (p, pp, n angulos) o (None, 0, 0)."""
    C = _coef().get("grupos") or {}
    for gid, g in C.items():
        if not g.get("sombra") or g.get("liga") != rec.get("liga") or g.get("mercado") != tipo:
            continue
        x = x_partido(rec, gid, p_mercado_home)
        if not x:
            continue
        tot = sum(a["beta"] * xi for a, xi in zip(g["angulos"], x) if xi)
        tope = _coef().get("tope_logit", TOPE_LOGIT)
        tot = max(-tope, min(tope, tot))
        s = 1 if lado == g["favorece"] else -1
        p2 = _sig(_lg(p) + s * tot)
        return p2, p2 - p, sum(1 for xi in x if xi)
    return None, 0.0, 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    r = ajustar()
    for gid, g in r["grupos"].items():
        if "error" in g:
            print(gid, "ERROR", g["error"]); continue
        print("%s: n %d (%s a %s) | prueba n %d z %+.2f | activo %s" % (gid, g["n"], g["desde"], g["hasta"], g["prueba"]["n"], g["prueba"]["z"], g["activo"]))
        for a in g["angulos"]:
            print("   %-16s beta %+.3f (sd %s) ~%+.1f pp  n %d" % (a["codigo"], a["beta"], "-" if a["sd_post"] is None else "%.3f" % a["sd_post"], a["pp_aprox_50"], a["n_activo"]))
