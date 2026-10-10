# -*- coding: utf-8 -*-
"""
nucleo/sharp.py - CAPA DE PRECIO: probabilidad "sharp" y mejor cuota disponible por lado.

Lee salida/cuotas_casas.json (lo escribe colectores/recolectar_cuotas.py con The Odds API: todas las casas
de un partido en un instante) y, para cada partido de proximos.json, entrega por mercado y lado:
  - p_sharp : probabilidad sin vig de la casa de referencia (Pinnacle). Si no esta, la MEDIANA sin vig de
              todas las casas (consenso), que es casi igual de dura de vencer.
  - mejor   : la cuota mas alta disponible para ese lado (y en que casa).
  - ev      : p_sharp * mejor_decimal - 1  -> la ventaja contra la mejor cuota.
  - n_casas : cuantas casas cotizan ese lado.

Por que: el backtest con 20,633 partidos de futbol (Pinnacle apertura/cierre 2018-2026) y 2,220 de NFL
mostro que el modelo contra la linea de cierre PIERDE (-3% a -9% segun banda de edge), mientras que
"probabilidad sharp x mejor cuota del mercado" gana +5% a +8% con 7 de 7 anios positivos.
Esta es la capa que decide; el modelo solo ajusta (ver plataforma.decidir_picks).

Emparejamiento con ESPN: por fecha (misma fecha UTC +-1 dia) y nombres de equipo normalizados
(coincidencia de palabras, tolerante a 'LA Dodgers' vs 'Los Angeles Dodgers').
"""
import io, json, os, re, statistics, unicodedata

from . import mercado

SHARP = ("pinnacle", "pinnacle_eu")
# Casas que NO cuentan para la "mejor cuota": exchanges (cobran comision y su precio no es apostable tal cual).
EXCLUIR = set((os.environ.get("EDGELINE_CASAS_EXCLUIR") or "betfair_ex_eu,betfair_ex_uk,betfair_ex_au,matchbook,smarkets").split(","))
DIARIAS = {"mlb", "npb", "kbo"}   # ligas con el mismo cruce varios dias seguidos: emparejar solo con la fecha exacta
EV_MAX_CASA = 0.08      # una cuota con mas de 8% de EV contra Pinnacle es casi siempre una linea vieja o un mercado distinto: se ignora
# sport key de The Odds API -> liga de Edgeline
LIGA_DE = {"baseball_mlb": "mlb", "baseball_npb": "npb", "baseball_kbo": "kbo", "icehockey_nhl": "nhl",
           "baseball_lmp": "lmp", "baseball_lvbp": "lvbp", "baseball_lidom": "lidom",      # SportsGameOdds (recolectar_cuotas_sgo.py)
           "americanfootball_nfl": "nfl", "americanfootball_ncaaf": "ncaafb", "basketball_nba": "nba",
           "basketball_ncaab": "ncaamb", "soccer_mexico_ligamx": "ligamx", "soccer_epl": "premier",
           "soccer_spain_la_liga": "laliga", "soccer_italy_serie_a": "seriea", "soccer_germany_bundesliga": "bundesliga",
           "soccer_france_ligue_one": "ligue1", "soccer_uefa_champs_league": "champions", "soccer_usa_mls": "mls",
           "tennis_atp_us_open": "atp", "tennis_wta_us_open": "wta"}

_PAL_IGN = {"the", "fc", "cf", "sc", "club", "de", "los", "las", "la", "el", "st", "state", "university"}


def liga_de(sport_key):
    """sport key de The Odds API -> liga de Edgeline. Tenis viene por torneo (tennis_atp_china_open...)."""
    if sport_key in LIGA_DE:
        return LIGA_DE[sport_key]
    if sport_key.startswith("tennis_atp"):
        return "atp"
    if sport_key.startswith("tennis_wta"):
        return "wta"
    return None


def cuotas_desde_sharp(pr):
    """Arma el dict de cuotas que usa plataforma (como el de ESPN) con la MEJOR cuota por lado, para partidos
    sin cuotas de ESPN (NPB, KBO, tenis). Devuelve {} si no hay precios."""
    g = pr.get("Ganador") or {}
    if not g.get("home") or not g.get("away"):
        return {}
    q = {"casa": "mejor de %d casas" % max(g["home"]["n_casas"], g["away"]["n_casas"]),
         "ml_home": g["home"]["mejor_cuota"], "ml_away": g["away"]["mejor_cuota"], "fuente": "odds_api"}
    if g.get("draw"):
        q["ml_draw"] = g["draw"]["mejor_cuota"]
    t = pr.get("Total") or {}
    if t.get("over") and t.get("under"):
        q.update({"total": t.get("_linea"), "over_odds": t["over"]["mejor_cuota"], "under_odds": t["under"]["mejor_cuota"]})
    sp = pr.get("Spread") or {}
    if sp.get("home") and sp.get("away"):
        q.update({"spread_home": sp.get("_linea"), "spread_home_odds": sp["home"]["mejor_cuota"], "spread_away_odds": sp["away"]["mejor_cuota"]})
    return q


def linea_comun(ev, mk):
    """Linea (total o spread del local) mas repetida entre las casas del evento, para pedir precios sobre la misma linea."""
    cot = _lados(ev, mk)
    if mk == "totals":
        pts = [v[1] for d in cot.values() for v in d.values() if v[1] is not None]
    else:
        pts = [d["home"][1] for d in cot.values() if "home" in d and d["home"][1] is not None]
    return max(set(pts), key=pts.count) if pts else None


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _PAL_IGN}


def _parecido(a, b):
    A, B = _norm(a), _norm(b)
    if not A or not B:
        return 0.0
    return len(A & B) / float(min(len(A), len(B)))


def cargar(ruta):
    """salida/cuotas_casas.json -> lista de eventos (cada uno con sus casas). [] si no existe."""
    try:
        with io.open(ruta, encoding="utf-8") as fh:
            d = json.load(fh)
        return d.get("eventos") or [], d.get("generado")
    except Exception:
        return [], None


def _ev_de_partido(eventos, liga, fecha_utc, home, away):
    f = (fecha_utc or "")[:10]
    mejor, puntaje = None, 0.0
    for ev in eventos:
        if liga_de(ev.get("sport") or "") != liga:
            continue
        fe = (ev.get("commence_time") or "")[:10]
        if f and fe and abs((_dia(fe) - _dia(f)).days) > 1:
            continue
        if f and fe and fe != f and liga in DIARIAS:
            continue          # series diarias (MLB, NPB, KBO): el juego de manana NO puede tomar la cuota del de hoy
        s = _parecido(ev.get("home_team"), home) + _parecido(ev.get("away_team"), away)
        if f and fe and fe == f:
            s += 0.5          # misma fecha gana: dos juegos seguidos del mismo cruce (NPB, MLB) no deben compartir cuota
        if s > puntaje:
            mejor, puntaje = ev, s
    return mejor if puntaje >= 1.2 else None        # cada equipo al menos ~60% de coincidencia


def _dia(s):
    import datetime as dt
    return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _lados(ev, mk, punto=None):
    """{casa: {lado: (cuota_americana, point)}} para el mercado mk (h2h | totals | spreads)."""
    out = {}
    for bk in ev.get("bookmakers") or []:
        for m in bk.get("markets") or []:
            if m.get("key") != mk:
                continue
            d = {}
            for o in m.get("outcomes") or []:
                nombre = o.get("name"); pt = o.get("point")
                if mk == "h2h":
                    lado = "draw" if nombre == "Draw" else ("home" if nombre == ev.get("home_team") else "away")
                elif mk == "totals":
                    lado = "over" if nombre == "Over" else "under"
                else:
                    lado = "home" if nombre == ev.get("home_team") else "away"
                if punto is not None and pt is not None and abs(float(pt) - float(punto)) > 1e-6 \
                        and not (mk == "spreads" and lado == "away" and abs(float(pt) + float(punto)) < 1e-6):
                    continue
                if o.get("price") is not None:
                    d[lado] = (float(o["price"]), pt)
            if d:
                out[bk.get("key")] = d
    return out


def _precio(cotiz, lados):
    """cotiz: {casa: {lado: (cuota, pt)}} -> por lado: p_sharp, mejor cuota, casa, n_casas, fuente."""
    if not cotiz:
        return {}
    # mercado comparable: mismas salidas que el modelo. En NHL/MLB varias casas europeas cotizan h2h a 3 vias
    # (tiempo regular, con empate): sus precios de home/away NO son comparables con el 2 vias y se descartan.
    n_l = len(lados)
    cotiz = {c: d for c, d in cotiz.items() if len(d) == n_l or (n_l == 3 and len(d) == 3) or (n_l == 2 and "draw" not in d)}
    casas_ok = {c: d for c, d in cotiz.items() if all(l in d for l in lados)}
    if not casas_ok:
        return {}
    ref = next((c for c in SHARP if c in casas_ok), None)
    if ref:
        probs = mercado.sin_vig([mercado.prob_implicita(casas_ok[ref][l][0]) for l in lados]); fuente = "pinnacle"
    else:
        porlado = []
        for c, d in casas_ok.items():
            porlado.append(mercado.sin_vig([mercado.prob_implicita(d[l][0]) for l in lados]))
        probs = [statistics.median(x[i] for x in porlado) for i in range(len(lados))]
        s = sum(probs); probs = [p / s for p in probs]; fuente = "consenso"
    res = {}
    for i, l in enumerate(lados):
        ofertas = [(d[l][0], c) for c, d in cotiz.items() if l in d and c not in EXCLUIR]
        if not ofertas:
            ofertas = [(d[l][0], c) for c, d in cotiz.items() if l in d]
        ofertas.sort(key=lambda x: -mercado.american_a_decimal(x[0]))
        sospechosas = []
        cu, casa = ofertas[0]
        for cu_, casa_ in ofertas:
            if probs[i] * mercado.american_a_decimal(cu_) - 1 <= EV_MAX_CASA or casa_ in SHARP:
                cu, casa = cu_, casa_; break
            sospechosas.append(casa_)
        dec = mercado.american_a_decimal(cu)
        res[l] = {"p_sharp": round(probs[i], 4), "mejor_cuota": cu, "mejor_decimal": round(dec, 3), "casa": casa,
                  "ev": round(probs[i] * dec - 1, 4), "n_casas": len(ofertas), "fuente": fuente,
                  "ref_cuota": casas_ok[ref][l][0] if ref else None, "ignoradas": sospechosas}
    return res


def precios(eventos, liga, fecha_utc, home, away, tres_vias=False, total=None, spread_home=None):
    """Precios sharp/mejor cuota del partido: {"Ganador": {...}, "Total": {...}, "Spread": {...}} (vacio si no hay).
    total/spread_home = None -> se usa la linea mas comun entre casas; "no" -> no se piden."""
    ev = _ev_de_partido(eventos, liga, fecha_utc, home, away)
    if not ev:
        return {}
    if total is None:
        total = linea_comun(ev, "totals")
    if spread_home is None:
        spread_home = linea_comun(ev, "spreads")
    if total == "no":
        total = None
    if spread_home == "no":
        spread_home = None
    out = {}
    g = _precio(_lados(ev, "h2h"), ["home", "away"] + (["draw"] if tres_vias else []))
    if g:
        out["Ganador"] = g
    if total is not None:
        t = _precio(_lados(ev, "totals", total), ["over", "under"])
        if t:
            out["Total"] = t; out["Total"]["_linea"] = total
    if spread_home is not None:
        s = _precio(_lados(ev, "spreads", spread_home), ["home", "away"])
        if s:
            out["Spread"] = s; out["Spread"]["_linea"] = spread_home
    out["_evento"] = {"home": ev.get("home_team"), "away": ev.get("away_team"), "casas": len(ev.get("bookmakers") or [])}
    return out
