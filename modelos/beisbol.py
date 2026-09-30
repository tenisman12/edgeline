# -*- coding: utf-8 -*-
"""
PASO 4 - modelos/beisbol.py

UN modelo de beisbol para las 7 ligas (MLB, NPB, KBO, LMP, LVBP, LIDOM, ABL).
Mismo esquema de entrada (nucleo/features), misma firma de salida:

    predecir(modelo, fila) -> {
        "p_home":   prob de que gane el local (calibrada),
        "esperado_home", "esperado_away", "total":  carreras esperadas,
        "edge":     None aqui (lo llena la capa de mercado con las cuotas),
        "confianza": "alta" | "media" | "baja",
    }

Como funciona:
  - Regresion logistica (stdlib, L2) sobre las DIFERENCIAS de features as-of que
    ya calcula nucleo/features (elo, cs, ca, obp, iso, K%, BB%, FIP, K9, BB9, HR9,
    WHIP, descanso). Es lo que aprovecha el box score completo.
  - Carreras esperadas via las tasas cs/ca de cada equipo (ritmo ofensivo/defensivo).
  - Se ENTRENA por liga (cada liga tiene su nivel de carreras y su ventaja local),
    con walk-forward temporal para medir sin fuga.

No usa numpy ni sklearn: corre en cualquier Python. La calibracion fina (Platt)
la formaliza nucleo/calibrar (Paso 5); aqui ya va una version integrada.

Colocar en:  C:\\Edgeline\\modelos\\beisbol.py

Uso (en C:\\Edgeline, con datos/beisbol.csv):
    python -c "import sys; sys.path.insert(0,'.'); from modelos import beisbol; beisbol.validar('beisbol')"
"""
import math, sys, os

try:
    from nucleo import io, features
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io, features

FEATS = ["elo_dif", "cs_dif", "ca_dif", "obp_dif", "iso_dif", "k_pct_dif",
         "bb_pct_dif", "fip_dif", "k9_dif", "bb9_dif", "hr9_dif", "whip_dif",
         "descanso_dif"]

# ------------------------------------------------------------------ logistica (stdlib)
def _sigmoid(z):
    if z < -35: return 0.0
    if z > 35:  return 1.0
    return 1.0 / (1.0 + math.exp(-z))

def _estandarizar(filas):
    """media y desviacion por feature (ignorando None)."""
    mu, sd = {}, {}
    for f in FEATS:
        vals = [r[f] for r in filas if r.get(f) is not None]
        m = sum(vals) / len(vals) if vals else 0.0
        var = sum((v - m) ** 2 for v in vals) / len(vals) if vals else 1.0
        mu[f] = m; sd[f] = math.sqrt(var) or 1.0
    return mu, sd

def _vec(r, mu, sd):
    """feature -> z-score; None imputa a 0 (la media)."""
    return [((r[f] - mu[f]) / sd[f]) if r.get(f) is not None else 0.0 for f in FEATS]

def entrenar_logistica(filas, iters=400, lr=0.3, l2=1.0):
    mu, sd = _estandarizar(filas)
    X = [_vec(r, mu, sd) for r in filas]
    y = [r["y_home"] for r in filas]
    n, d = len(X), len(FEATS)
    if n < 30:
        return None
    w = [0.0] * d; b = 0.0
    for _ in range(iters):
        gw = [0.0] * d; gb = 0.0
        for xi, yi in zip(X, y):
            p = _sigmoid(sum(wj * xj for wj, xj in zip(w, xi)) + b)
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
        b -= lr * (gb / n)
    return {"w": w, "b": b, "mu": mu, "sd": sd,
            "cs_home": _prom(filas, "cs_home"), "ca_home": _prom(filas, "ca_home")}

def _prom(filas, k):
    vals = [r[k] for r in filas if r.get(k) is not None]
    return sum(vals) / len(vals) if vals else None

def prob_local(modelo, r):
    z = sum(wj * xj for wj, xj in zip(modelo["w"], _vec(r, modelo["mu"], modelo["sd"]))) + modelo["b"]
    return _sigmoid(z)

# ------------------------------------------------------------------ CARRERAS / TOTALES
VENTAJA_LOCAL = 0.03   # el local anota ~3% mas
NB_DISP = 4.0          # dispersion de la binomial negativa para carreras (var > media)

def carreras_esperadas(r):
    """Log5 de carreras: ataque propio x defensa rival, relativo al ritmo de la liga.
    Usa los NIVELES as-of (of_/df_), no las diferencias. Devuelve (xhome, xaway)."""
    lg = r.get("lg_rs") or 4.5
    ofh, ofa = r.get("of_home"), r.get("of_away")
    dfh, dfa = r.get("df_home"), r.get("df_away")
    if None in (ofh, ofa, dfh, dfa) or not lg:
        return None, None
    xh = (ofh * dfa / lg) * (1 + VENTAJA_LOCAL)
    xa = (ofa * dfh / lg) * (1 - VENTAJA_LOCAL)
    return max(xh, 0.3), max(xa, 0.3)

def _nb_pmf(k, mu, r=NB_DISP):
    """P(X=k) binomial negativa con media mu y dispersion r (var = mu + mu^2/r)."""
    p = r / (r + mu)
    # C(k+r-1, k) p^r (1-p)^k  con r real via gamma
    lg = math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
    return math.exp(lg + r * math.log(p) + k * math.log(1 - p))

def prob_over(r, linea):
    """P(total de carreras > linea) con la suma de dos binomiales negativas
    aproximada por una NB de media = xhome + xaway."""
    xh, xa = carreras_esperadas(r)
    if xh is None:
        return None, None
    mu = xh + xa
    piso = int(math.floor(linea))
    p_under = sum(_nb_pmf(k, mu) for k in range(0, piso + 1))
    return 1 - p_under, mu

def prob_run_line(r, linea=1.5, kmax=20, xh=None, xa=None):
    """Probabilidad de que el LOCAL cubra el run line -linea (ej -1.5 = ganar por 2+).
    Sale de la distribucion del diferencial de carreras (dos NegBinom).
    Devuelve (p_local_cubre, p_visita_cubre). Sin push: el margen es entero."""
    if xh is None or xa is None:
        xh, xa = carreras_esperadas(r)
    if xh is None:
        return None, None
    ph = [_nb_pmf(k, xh) for k in range(kmax)]
    pa = [_nb_pmf(k, xa) for k in range(kmax)]
    need = int(math.floor(linea)) + 1          # 1.5 -> margen local >= 2
    p_home = sum(ph[i] * pa[j] for i in range(kmax) for j in range(kmax) if i - j >= need)
    return p_home, 1 - p_home


def prob_por_carreras(r, kmax=18):
    """Probabilidad de que gane el LOCAL derivada de las carreras esperadas:
    P(carreras_local > carreras_visita) con dos binomiales negativas independientes.
    Es una vision del ganador desde el ritmo de carreras, distinta a la del ELO."""
    xh, xa = carreras_esperadas(r)
    if xh is None:
        return None
    ph = [_nb_pmf(k, xh) for k in range(kmax)]
    pa = [_nb_pmf(k, xa) for k in range(kmax)]
    p_home = sum(ph[i] * pa[j] for i in range(kmax) for j in range(i))
    p_tie = sum(ph[i] * pa[i] for i in range(kmax))
    return p_home + 0.52 * p_tie   # los empates se resuelven en extras (~favor local)

def p_gana_carreras(xh, xa, kmax=18):
    """P(gana el local) desde carreras esperadas xh, xa (dos NB independientes; empates -> extras)."""
    ph = [_nb_pmf(k, xh) for k in range(kmax)]
    pa = [_nb_pmf(k, xa) for k in range(kmax)]
    p_home = sum(ph[i] * pa[j] for i in range(kmax) for j in range(i))
    p_tie = sum(ph[i] * pa[i] for i in range(kmax))
    return p_home + 0.52 * p_tie


def ajustar_carreras(xh, xa, p_obj, iters=28):
    """COHERENCIA: reparte el mismo total de carreras (xh+xa) entre local y visita hasta que la
    probabilidad de ganar que implican las carreras sea p_obj (la del ensamble). Asi ganador,
    carreras esperadas y run line salen de UNA sola distribucion."""
    mu = xh + xa
    lo, hi = 0.15, 0.85
    for _ in range(iters):
        mid = (lo + hi) / 2
        if p_gana_carreras(mu * mid, mu * (1 - mid)) < p_obj: lo = mid
        else: hi = mid
    s = (lo + hi) / 2
    return mu * s, mu * (1 - s)


COHERENTE = True       # carreras esperadas y run line ajustados a la prob. del ensamble

# ------------------------------------------------------------------ ENSAMBLE ganador
# Combina la logistica (vision ELO+box) con la prob derivada de las carreras
# (vision de ritmo). w = peso de la logistica. La prob de carreras suele predecir
# el ganador MEJOR que la logistica, asi que el w optimo tiende a favorecerla.
W_ENSAMBLE = 0.35        # default global (favorece carreras); por liga se afina
_W_CACHE = {}

def _peso(liga):
    """Peso del ensamble para una liga: usa el guardado por el afinador, si existe."""
    if liga in _W_CACHE:
        return _W_CACHE[liga]
    try:
        from nucleo import calibrar as C
        w = C.cargar_w("beisbol", io.norm(liga), default=W_ENSAMBLE)
    except Exception:
        w = W_ENSAMBLE
    _W_CACHE[liga] = w
    return w

MODO_PROB = "media3"     # "media3" = promedio simple ELO + logistica + carreras (sin pesos por liga); "ensamble" = w*logistica+(1-w)*carreras

def prob(modelo, r, w=None):
    """Probabilidad de ganador del local. Por defecto MEDIA3: promedio simple de tres vistas
    (ELO, logistica con box score, prob. implicita de las carreras). Validada walk-forward:
    iguala o mejora a ELO solo en MLB/ABL/LMP y evita pesos por liga ruidosos.
    Es la firma que usa el backtest (evaluar prefiere 'prob' sobre 'prob_local')."""
    pl = prob_local(modelo, r)
    pc = prob_por_carreras(r)
    if MODO_PROB == "media3" and w is None:
        pe = _sigmoid((r.get("elo_dif") or 0) / 173.0)
        partes = [pe, pl] + ([pc] if pc is not None else [])
        return sum(partes) / len(partes)
    if w is None:
        w = _peso(io.norm(r.get("league") or ""))
    if pc is None:
        return pl
    return w * pl + (1 - w) * pc

# ------------------------------------------------------------------ firma comun
def predecir(modelo, r, linea_total=None):
    p = prob(modelo, r)
    xh, xa = carreras_esperadas(r)
    if xh is None:   # respaldo si faltan niveles
        base = modelo.get("cs_home") or 4.5
        xh = base + (r.get("cs_dif") or 0) / 2.0 - (r.get("ca_dif") or 0) / 2.0
        xa = base - (r.get("cs_dif") or 0) / 2.0 + (r.get("ca_dif") or 0) / 2.0
        xh, xa = max(xh, 0.5), max(xa, 0.5)
    xh_crudo, xa_crudo = xh, xa
    if COHERENTE:
        xh, xa = ajustar_carreras(xh, xa, p)
    total = xh + xa
    margen = abs(p - 0.5)
    conf = "alta" if margen > 0.20 else ("media" if margen > 0.10 else "baja")
    out = {"p_home": round(p, 4),
           "esperado_home": round(xh, 2), "esperado_away": round(xa, 2),
           "esperado_home_crudo": round(xh_crudo, 2), "esperado_away_crudo": round(xa_crudo, 2),
           "total": round(total, 2), "edge": None, "confianza": conf}
    if linea_total is not None:
        po, _ = prob_over(r, linea_total)
        out["p_over"] = round(po, 4) if po is not None else None
        out["linea_total"] = linea_total
    # run line -1.5 / +1.5
    rlh, rla = prob_run_line(r, 1.5, xh=xh, xa=xa)
    if rlh is not None:
        out["p_rl_home"] = round(rlh, 4)   # local -1.5 (gana por 2+)
        out["p_rl_away"] = round(rla, 4)   # visita +1.5
    return out

# ------------------------------------------------------------------ validacion walk-forward
def _brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ys)

def _logloss(ps, ys):
    s = 0.0
    for p, y in zip(ps, ys):
        p = min(max(p, 1e-6), 1 - 1e-6)
        s += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return s / len(ys)

def validar(deporte="beisbol", liga=None, test_frac=0.30):
    """
    Split temporal por liga: entrena con lo viejo, prueba con lo nuevo (sin fuga).
    Reporta accuracy, Brier y logloss vs dos baselines: 'siempre local' y 'solo ELO'.
    """
    feats, _ = features.construir(deporte, liga)
    if not feats:
        print("Sin features. Falta datos/%s.csv." % deporte); return
    porliga = {}
    for r in feats:
        porliga.setdefault(r["league"], []).append(r)

    print("%-8s %6s | %-18s | %-18s | %-18s" %
          ("LIGA", "TEST", "MODELO (acc/brier)", "SOLO ELO", "SIEMPRE LOCAL"))
    print("-" * 82)
    glob = {"n": 0, "acc": 0, "br": 0.0}
    for lg, rows in sorted(porliga.items()):
        rows.sort(key=lambda r: (r["game_date"], r["gamePk"]))
        corte = int(len(rows) * (1 - test_frac))
        tr, te = rows[:corte], rows[corte:]
        if len(tr) < 50 or len(te) < 20:
            print("%-8s %6d | muestra chica" % (lg, len(te))); continue
        modelo = entrenar_logistica(tr)
        if not modelo:
            print("%-8s %6d | no entreno" % (lg, len(te))); continue
        ys = [r["y_home"] for r in te]
        ps = [prob_local(modelo, r) for r in te]
        # baselines
        p_elo = [_sigmoid((r.get("elo_dif") or 0) / 173.0) for r in te]  # 173 ~ escala logit de ELO
        tasa_local = sum(r["y_home"] for r in tr) / len(tr)
        acc = sum(1 for p, y in zip(ps, ys) if (p >= .5) == (y == 1)) / len(ys)
        acc_elo = sum(1 for p, y in zip(p_elo, ys) if (p >= .5) == (y == 1)) / len(ys)
        acc_loc = sum(1 for y in ys if y == 1) / len(ys)
        print("%-8s %6d | acc %.3f  br %.3f | acc %.3f  br %.3f | acc %.3f  br %.3f" %
              (lg, len(te), acc, _brier(ps, ys),
               acc_elo, _brier(p_elo, ys), acc_loc, _brier([tasa_local] * len(ys), ys)))
        glob["n"] += len(te); glob["acc"] += acc * len(te); glob["br"] += _brier(ps, ys) * len(te)
    if glob["n"]:
        print("-" * 82)
        print("GLOBAL   %6d | acc %.3f  br %.3f (ponderado por n de test)" %
              (glob["n"], glob["acc"] / glob["n"], glob["br"] / glob["n"]))
    print("\nLECTURA: el modelo es util si su acc/brier le gana a 'solo ELO' y a 'siempre local'.")
    print("Beisbol es ruidoso: acc realista de ganador ~0.55-0.58 walk-forward.")


if __name__ == "__main__":
    validar(sys.argv[1] if len(sys.argv) > 1 else "beisbol",
            sys.argv[2] if len(sys.argv) > 2 else None)
