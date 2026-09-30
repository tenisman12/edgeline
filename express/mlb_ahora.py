# -*- coding: utf-8 -*-
"""
MLB AHORA - prediccion express de MLB para hoy, con el modelo calibrado.

Autonomo: corre en tu maquina (que si alcanza la MLB Stats API), baja el historial
de carreras, arma el modelo que te dio 56.7% en ganador —ENSAMBLE de ELO + la
probabilidad derivada de las carreras (Log5 + binomial negativa)— lo CALIBRA con
Platt sobre el propio historial (walk-forward, sin fuga), y predice los juegos de hoy.

No necesita el refactor ni subir nada. Solo urllib (stdlib).

Uso (en C:\\Edgeline):
    python mlb_ahora.py
    python mlb_ahora.py --fecha 2026-09-30
    python mlb_ahora.py --desde 2022      (mas historia = mejor, mas lento)

Imprime: prob del local (calibrada), carreras esperadas, total y over/under.
"""
import argparse, json, math, sys, datetime as dt
import urllib.request, urllib.parse

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0"}

# modelo
HFA_ELO = 30.0; K_ELO = 6.0; REGR = 0.75; ESCALA = 400.0
VENT_LOCAL = 0.03; NB_DISP = 4.0
W_ENS = 0.30            # peso de la logistica-ELO; el resto es carreras (optimo MLB ~0.3)
SHRINK = 8.0           # encogimiento de tasas a la media de liga


def get(path):
    req = urllib.request.Request(API + path, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)

def sched(d1, d2, sportId=1, gametype="R"):
    url = "/schedule?" + urllib.parse.urlencode(
        {"sportId": sportId, "startDate": d1, "endDate": d2, "gameType": gametype})
    return get(url)

def bajar(desde, hasta_fecha):
    juegos = []
    for season in range(desde, hasta_fecha.year + 1):
        d1 = "%d-03-01" % season
        d2 = min(dt.date(season, 11, 30), hasta_fecha).isoformat()
        try:
            data = sched(d1, d2)
        except Exception as e:
            print("  %d: %s" % (season, str(e)[:70])); continue
        n = 0
        for dia in data.get("dates", []):
            for g in dia.get("games", []):
                if (g.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                t = g.get("teams") or {}
                h, a = t.get("home") or {}, t.get("away") or {}
                hs, as_ = h.get("score"), a.get("score")
                if hs is None or as_ is None:
                    continue
                juegos.append({"season": season, "fecha": g.get("officialDate") or dia.get("date"),
                               "home": h.get("team", {}).get("name"), "away": a.get("team", {}).get("name"),
                               "hs": float(hs), "as": float(as_)})
                n += 1
        print("  %d: %d juegos" % (season, n))
    juegos.sort(key=lambda x: (x["fecha"] or "", x["home"] or ""))
    return juegos


def _sig(z): return 0.0 if z < -35 else (1.0 if z > 35 else 1 / (1 + math.exp(-z)))
def _logit(p): p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))

def _nb_pmf(k, mu, r=NB_DISP):
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))

def prob_carreras(xh, xa, kmax=18):
    ph = [_nb_pmf(k, xh) for k in range(kmax)]
    pa = [_nb_pmf(k, xa) for k in range(kmax)]
    p_home = sum(ph[i] * pa[j] for i in range(kmax) for j in range(i))
    p_tie = sum(ph[i] * pa[i] for i in range(kmax))
    return p_home + 0.52 * p_tie


class Eq:
    __slots__ = ("elo", "gf", "ga", "n", "ultseason")
    def __init__(self): self.elo = 1500.0; self.gf = 0.0; self.ga = 0.0; self.n = 0; self.ultseason = None
    def of(self, lg): return (self.gf + SHRINK * lg) / (self.n + SHRINK) if self.n else lg
    def df(self, lg): return (self.ga + SHRINK * lg) / (self.n + SHRINK) if self.n else lg


def entrenar_y_calibrar(juegos):
    eq = {}; tot = 0.0; ng = 0
    cal = []   # (p_ensamble, y) as-of para Platt
    lg = 4.6
    for j in juegos:
        h, a = j["home"], j["away"]
        if not h or not a:
            continue
        th = eq.setdefault(h, Eq()); ta = eq.setdefault(a, Eq())
        for t in (th, ta):
            if t.ultseason is not None and t.ultseason != j["season"]:
                t.elo = 1500 + (t.elo - 1500) * REGR
            t.ultseason = j["season"]
        # prediccion as-of (antes de ver el resultado)
        if th.n >= 10 and ta.n >= 10:
            p_elo = _sig((th.elo + HFA_ELO - ta.elo) / (ESCALA / math.log(10)))
            xh = th.of(lg) * ta.df(lg) / lg * (1 + VENT_LOCAL)
            xa = ta.of(lg) * th.df(lg) / lg * (1 - VENT_LOCAL)
            p_car = prob_carreras(max(xh, .3), max(xa, .3))
            p = W_ENS * p_elo + (1 - W_ENS) * p_car
            cal.append((p, 1 if j["hs"] > j["as"] else 0))
        # actualizar ELO
        esp = _sig((th.elo + HFA_ELO - ta.elo) / (ESCALA / math.log(10)))
        res = 1.0 if j["hs"] > j["as"] else 0.0
        mov = math.log(abs(j["hs"] - j["as"]) + 1)
        d = K_ELO * mov * (res - esp); th.elo += d; ta.elo -= d
        th.gf += j["hs"]; th.ga += j["as"]; th.n += 1
        ta.gf += j["as"]; ta.ga += j["hs"]; ta.n += 1
        tot += j["hs"] + j["as"]; ng += 2
        lg = tot / ng
    # Platt sobre las predicciones as-of
    a, b = 1.0, 0.0
    if len(cal) > 200:
        X = [_logit(p) for p, _ in cal]; Y = [y for _, y in cal]; n = len(X)
        for _ in range(700):
            ga = gb = 0.0
            for x, y in zip(X, Y):
                e = _sig(a * x + b) - y; ga += e * x; gb += e
            a -= 0.05 * ga / n; b -= 0.05 * gb / n
        acc = sum(1 for (p, y) in cal if (p >= .5) == (y == 1)) / len(cal)
        print("Modelo listo. Accuracy as-of del ensamble: %.3f  (Platt a=%.2f b=%.2f)" % (acc, a, b))
    return eq, lg, (a, b)


def juegos_hoy(fecha):
    # TODOS los juegos de hoy: temporada regular + postemporada, jugados o no.
    data = sched(fecha, fecha, gametype="R,F,D,L,W,C,P")
    out = []
    for dia in data.get("dates", []):
        for g in dia.get("games", []):
            t = g.get("teams") or {}
            h = (t.get("home") or {}).get("team", {}).get("name")
            a = (t.get("away") or {}).get("team", {}).get("name")
            if h and a:
                estado = (g.get("status") or {}).get("abstractGameState") or ""
                out.append((a, h, estado))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha"); ap.add_argument("--desde", type=int, default=2023)
    ap.add_argument("--total", type=float, default=8.5)
    args = ap.parse_args()
    hoy = dt.date.fromisoformat(args.fecha) if args.fecha else dt.date.today()

    print("Bajando historial MLB %d-%d..." % (args.desde, hoy.year))
    juegos = bajar(args.desde, hoy)
    if not juegos:
        print("Sin historial."); return
    eq, lg, (pa, pb) = entrenar_y_calibrar(juegos)

    hj = juegos_hoy(hoy.isoformat())
    if not hj:
        print("\nNo hay juegos MLB el %s." % hoy.isoformat()); return

    print("\nMLB - %s   (linea total %.1f, prob CALIBRADA)" % (hoy.isoformat(), args.total))
    print("-" * 76)
    print("%-26s %8s %6s %6s %6s %7s  %s" %
          ("PARTIDO (V @ L)", "P(local)", "xCL", "xCV", "TOT", "P(over)", "PICK"))
    print("-" * 76)
    for away, home, estado in hj:
        marca = " [jugado]" if estado == "Final" else ""
        th, ta = eq.get(home), eq.get(away)
        if not th or not ta or th.n < 10 or ta.n < 10:
            print("%-26s  (sin historial suficiente)%s" % (away + " @ " + home, marca)); continue
        p_elo = _sig((th.elo + HFA_ELO - ta.elo) / (ESCALA / math.log(10)))
        xh = th.of(lg) * ta.df(lg) / lg * (1 + VENT_LOCAL)
        xa = ta.of(lg) * th.df(lg) / lg * (1 - VENT_LOCAL)
        xh, xa = max(xh, .3), max(xa, .3)
        p_car = prob_carreras(xh, xa)
        p = W_ENS * p_elo + (1 - W_ENS) * p_car
        p = _sig(pa * _logit(p) + pb)     # calibracion
        # over/under
        mu = xh + xa; piso = int(math.floor(args.total))
        p_over = 1 - sum(_nb_pmf(k, mu) for k in range(piso + 1))
        pick = home if p >= .5 else away
        ou = "OVER" if p_over >= .5 else "UNDER"
        conf = "alta" if abs(p - .5) > .12 else ("media" if abs(p - .5) > .06 else "baja")
        print("%-26s %7.1f%% %6.2f %6.2f %6.1f %6.1f%%  %s / %s (%s)" %
              (away + " @ " + home, 100 * p, xh, xa, mu, 100 * p_over, pick, ou, conf))
    print("-" * 76)
    print("xCL/xCV = carreras esperadas local/visita. Prob ya calibrada (Platt).")
    print("MLB ganador ~56-57%% es el techo honesto; el edge real esta en el total y vs cuota.")


if __name__ == "__main__":
    main()
