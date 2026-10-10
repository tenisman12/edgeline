# -*- coding: utf-8 -*-
"""
colectores/clima.py - pronostico del clima a la hora de cada partido al aire libre (Open-Meteo, gratis y sin llave).

Lo llama plataforma.py despues de bajar los partidos: a cada partido le agrega g["clima"] con temperatura, humedad,
probabilidad y mm de lluvia, viento y rafagas a la hora del juego, mas "alertas" en texto. Bajo techo -> "techado".

    python colectores\\clima.py --prueba "Atlanta, GA, USA" 2026-10-06T20:00Z      (una consulta, para revisar)

De donde sale el lugar:
  - ESPN (MLB, NFL, NCAAF, NBA, NHL, futbol): ciudad/estado/pais del estadio y el indicador indoor.
  - NPB y KBO: tabla de estadios de abajo (coordenadas fijas; domos marcados como techados).
  - Tenis: ciudad del torneo por palabras clave (tabla), o geocodificando palabras del nombre del torneo.
Solo stdlib. Si Open-Meteo no responde, el partido queda sin "clima" y nada se rompe.
"""
import datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(BASE, "contexto", "geo_cache.json")
GEO = "https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&format=json&name=%s"
FC = ("https://api.open-meteo.com/v1/forecast?latitude=%.3f&longitude=%.3f&timezone=UTC&forecast_days=10"
      "&hourly=temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m")
UA = "Mozilla/5.0 (Edgeline clima)"

# deportes que se juegan bajo techo siempre
TECHADOS = {"nba", "ncaamb", "nhl", "wnba", "shl", "liiga", "ahl", "del"}

# NPB / KBO: nombre del estadio (como lo publica cada liga) -> (lat, lon, techado)
ESTADIOS = {
    # KBO
    "잠실": (37.512, 127.072, False), "문학": (37.437, 126.693, False), "인천": (37.437, 126.693, False),
    "수원": (37.300, 127.010, False), "고척": (37.498, 126.867, True), "대전": (36.317, 127.429, False),
    "대구": (35.841, 128.681, False), "광주": (35.168, 126.889, False), "사직": (35.194, 129.062, False),
    "창원": (35.222, 128.582, False), "포항": (36.008, 129.359, False), "울산": (35.532, 129.265, False),
    "청주": (36.638, 127.470, False),
    # NPB
    "甲子園": (34.721, 135.362, False), "神宮": (35.674, 139.717, False), "東京ドーム": (35.706, 139.752, True),
    "マツダ": (34.392, 132.484, False), "横浜": (35.443, 139.640, False), "バンテリン": (35.186, 136.948, True),
    "ナゴヤドーム": (35.186, 136.948, True), "京セラ": (34.669, 135.476, True), "PayPay": (33.595, 130.362, True),
    "みずほPayPay": (33.595, 130.362, True), "ベルーナ": (35.769, 139.420, True), "楽天": (38.256, 140.903, False),
    "ZOZO": (35.645, 140.031, False), "エスコン": (42.990, 141.550, True), "札幌ドーム": (43.015, 141.410, True),
}

# tenis: palabra clave del torneo -> (lat, lon, techado)
TORNEOS = {
    "shanghai": (31.042, 121.360, False), "wuhan": (30.593, 114.305, False), "beijing": (39.990, 116.390, False),
    "china open": (39.990, 116.390, False), "tokyo": (35.630, 139.790, False), "osaka": (34.630, 135.420, False),
    "ningbo": (29.870, 121.540, False), "almaty": (43.240, 76.890, True), "basel": (47.560, 7.620, True),
    "vienna": (48.200, 16.330, True), "wien": (48.200, 16.330, True), "stockholm": (59.330, 18.060, True),
    "antwerp": (51.220, 4.400, True), "brussels": (50.850, 4.350, True), "paris": (48.840, 2.380, True),
    "metz": (49.120, 6.180, True), "athens": (37.980, 23.730, True), "hong kong": (22.300, 114.170, False),
    "guangzhou": (23.130, 113.260, False), "seoul": (37.520, 127.120, False), "monastir": (35.780, 10.830, False),
    "chennai": (13.080, 80.270, False), "turin": (45.070, 7.690, True), "riyadh": (24.710, 46.680, True),
    "jeddah": (21.540, 39.170, True), "hangzhou": (30.270, 120.150, False), "chengdu": (30.570, 104.060, False),
    "zhuhai": (22.270, 113.570, False), "astana": (51.160, 71.470, True), "moselle": (49.120, 6.180, True),
    "belgrade": (44.790, 20.450, True), "kaohsiung": (22.630, 120.300, False), "jiangxi": (28.680, 115.860, False),
}


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def geocodificar(texto, cache):
    """'Atlanta, GA, USA' -> (lat, lon) con Open-Meteo; usa cache. None si no se encuentra."""
    k = (texto or "").strip().lower()
    if not k:
        return None
    if k in cache:
        return tuple(cache[k]) if cache[k] else None
    ll = None
    for intento in [texto.split(",")[0].strip(), texto]:
        try:
            d = _get(GEO % urllib.parse.quote(intento))
            r = (d.get("results") or [None])[0]
            if r:
                ll = (round(r["latitude"], 3), round(r["longitude"], 3)); break
        except Exception:
            pass
    cache[k] = list(ll) if ll else None
    return ll


def lugar(g, cache):
    """(lat, lon, techado, etiqueta) del partido; None si no se puede ubicar."""
    liga = g.get("liga")
    if liga in TECHADOS:
        return (None, None, True, "bajo techo")
    est = g.get("estadio") or ""
    if liga in ("npb", "kbo"):
        for k, (la, lo, tch) in ESTADIOS.items():
            if k in est:
                return (la, lo, tch, est)
        return None
    if g.get("tipo") != "equipos":            # tenis
        t = (g.get("torneo") or "").lower()
        for k, (la, lo, tch) in TORNEOS.items():
            if k in t:
                return (la, lo, tch, g.get("torneo"))
        for w in re.findall(r"[A-Za-z]{4,}", g.get("torneo") or ""):
            if w.lower() in ("open", "masters", "rolex", "tennis", "championships", "classic", "trophy", "cup", "international"):
                continue
            ll = geocodificar(w, cache)
            if ll:
                return (ll[0], ll[1], False, g.get("torneo"))
        return None
    s = g.get("sede") or {}
    if s.get("techado") is True:
        return (None, None, True, est or "bajo techo")
    txt = ", ".join(x for x in (s.get("ciudad"), s.get("estado"), s.get("pais")) if x)
    ll = geocodificar(txt, cache) if txt else None
    if not ll:
        return None
    return (ll[0], ll[1], False, "%s (%s)" % (est, s.get("ciudad")) if est else txt)


def _hora(fc, utc):
    h = (fc or {}).get("hourly") or {}
    ts = h.get("time") or []
    if not ts:
        return None
    obj = utc.strftime("%Y-%m-%dT%H:00")
    if obj not in ts:
        return None
    i = ts.index(obj)
    v = lambda k: (h.get(k) or [None] * len(ts))[i]
    return {"temp_c": v("temperature_2m"), "humedad": v("relative_humidity_2m"), "prob_lluvia": v("precipitation_probability"),
            "lluvia_mm": v("precipitation"), "viento_kmh": v("wind_speed_10m"), "rafagas_kmh": v("wind_gusts_10m"),
            "dir_viento": v("wind_direction_10m")}


def alertas(c, deporte):
    a = []
    if c.get("prob_lluvia") is not None and c["prob_lluvia"] >= 60 and (c.get("lluvia_mm") or 0) >= 1.0:
        a.append("lluvia probable (%d%%, %.1f mm/h): riesgo de retraso o suspension" % (c["prob_lluvia"], c["lluvia_mm"]))
    elif c.get("prob_lluvia") is not None and c["prob_lluvia"] >= 40:
        a.append("posible lluvia (%d%%)" % c["prob_lluvia"])
    if c.get("viento_kmh") is not None and (c["viento_kmh"] >= 25 or (c.get("rafagas_kmh") or 0) >= 45):
        a.append("viento fuerte %.0f km/h (rafagas %.0f)%s" % (c["viento_kmh"], c.get("rafagas_kmh") or 0,
                 ": afecta pases y patadas" if deporte == "americano" else (": afecta el vuelo de la bola" if deporte == "beisbol" else "")))
    if c.get("temp_c") is not None and c["temp_c"] <= 5:
        a.append("frio %.0f C" % c["temp_c"])
    if c.get("temp_c") is not None and c["temp_c"] >= 32:
        a.append("calor %.0f C" % c["temp_c"])
    return a


def agregar(juegos, deporte_de=None, verbose=True):
    """Agrega g['clima'] a cada partido. deporte_de: dict liga -> deporte (para el texto de las alertas)."""
    cache = _cache()
    fcs, n_ok, n_tch = {}, 0, 0
    for g in juegos:
        try:
            utc = dt.datetime.fromisoformat((g.get("fecha_utc") or "").replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
        try:
            L = lugar(g, cache)
        except Exception:
            L = None
        if not L:
            continue
        la, lo, tch, etq = L
        if tch:
            g["clima"] = {"techado": True, "lugar": etq}; n_tch += 1; continue
        if (utc - dt.datetime.utcnow()).days > 9:
            continue
        k = (round(la, 2), round(lo, 2))
        if k not in fcs:
            try:
                fcs[k] = _get(FC % k); time.sleep(0.1)
            except Exception as e:
                fcs[k] = None
                if verbose: print("  clima: sin respuesta para %s (%s)" % (etq, str(e)[:60]))
        h = _hora(fcs[k], utc)
        if not h:
            continue
        h.update({"techado": False, "lugar": etq, "lat": la, "lon": lo, "fuente": "open-meteo",
                  "hora_utc": utc.strftime("%Y-%m-%dT%H:00Z")})
        h["alertas"] = alertas(h, (deporte_de or {}).get(g.get("liga")))
        g["clima"] = h; n_ok += 1
    _guardar_cache(cache)
    if verbose:
        print("  clima: %d partidos con pronostico, %d bajo techo, %d consultas" % (n_ok, n_tch, len(fcs)))
    return juegos


# ------------------------------------------------------------------ MLB: clima oficial del juego (viento relativo al campo)
MLB_SCHED = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=%s&hydrate=weather"


def _coef_mlb():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "clima_mlb.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return (json.load(f) or {}).get("coef_vigentes") or {}
    except Exception:
        return {}


def ajuste_mlb(temp_f, viento_txt, condicion=""):
    """carreras de mas (o de menos) al total por clima, con los coeficientes medidos (utilidades/medir_clima_mlb.py)."""
    c = _coef_mlb()
    if not c:
        return None
    techo = any(k in (condicion or "") for k in ("Roof Closed", "Dome"))
    m = re.search(r"(\d+)\s*mph", viento_txt or ""); mph = float(m.group(1)) if m else 0.0
    d = (viento_txt or "").split(", ", 1)[1] if ", " in (viento_txt or "") else ""
    x = {"temp_F_menos_72": 0.0 if (techo or temp_f is None) else temp_f - 72.0,
         "mph_hacia_afuera": 0.0 if techo else (mph if d.startswith("Out") else 0.0),
         "mph_hacia_adentro": 0.0 if techo else (mph if d.startswith("In") else 0.0),
         "mph_cruzado": 0.0 if techo else (mph if d in ("L To R", "R To L") else 0.0),
         "lluvia": 1.0 if any(k in (condicion or "") for k in ("Rain", "Drizzle")) else 0.0, "techado": 1.0 if techo else 0.0}
    return round(sum(c.get(k, 0.0) * v for k, v in x.items()), 2)


def agregar_mlb(juegos, verbose=True):
    """Clima oficial de MLB (MLB Stats API, aparece unas horas antes): temperatura, condicion y viento 'Out To CF'.
    Lo agrega en g['clima']['mlb'] con el ajuste medido al total. Sin respuesta: no hace nada."""
    fechas = sorted({(g.get("fecha_utc") or "")[:10] for g in juegos if g.get("liga") == "mlb"})
    extra = set()
    for f in fechas:                      # juegos de noche en EE.UU. caen al dia siguiente en UTC
        try:
            extra.add((dt.date.fromisoformat(f) - dt.timedelta(days=1)).isoformat())
        except ValueError:
            pass
    idx = {}
    for f in sorted(set(fechas) | extra):
        try:
            d = _get(MLB_SCHED % f)
        except Exception as e:
            if verbose: print("  clima MLB %s: sin respuesta (%s)" % (f, str(e)[:60]))
            continue
        for dd in d.get("dates") or []:
            for gm in dd.get("games") or []:
                w = gm.get("weather") or {}
                if not w:
                    continue
                h = ((gm.get("teams") or {}).get("home") or {}).get("team", {}).get("name")
                a = ((gm.get("teams") or {}).get("away") or {}).get("team", {}).get("name")
                idx[(h, a, (gm.get("gameDate") or "")[:13])] = w
                idx.setdefault((h, a, None), w)
    n = 0
    for g in juegos:
        if g.get("liga") != "mlb":
            continue
        k = (g["home"].get("nombre"), g["away"].get("nombre"))
        w = idx.get(k + ((g.get("fecha_utc") or "")[:13],)) or idx.get(k + (None,))
        if not w:
            continue
        try:
            tf = float(w.get("temp")) if w.get("temp") not in (None, "") else None
        except ValueError:
            tf = None
        aj = ajuste_mlb(tf, w.get("wind"), w.get("condition"))
        c = g.get("clima") or {}
        c["mlb"] = {"condicion": w.get("condition"), "temp_f": tf, "viento": w.get("wind"), "ajuste_total_carreras": aj,
                    "fuente": "MLB Stats API"}
        if aj is not None and abs(aj) >= 0.5:
            c.setdefault("alertas", []).append("clima suma %+.1f carreras al total (viento %s, %s F)" % (aj, w.get("wind"), w.get("temp")))
        g["clima"] = c; n += 1
    if verbose and fechas:
        print("  clima MLB oficial: %d juegos" % n)
    return juegos


def texto(c):
    """una linea en espanol para el razonamiento."""
    if not c:
        return ""
    if c.get("techado"):
        return "Clima: bajo techo."
    partes = []
    if c.get("temp_c") is not None: partes.append("%.0f C" % c["temp_c"])
    if c.get("prob_lluvia") is not None: partes.append("lluvia %d%%" % c["prob_lluvia"])
    if c.get("viento_kmh") is not None: partes.append("viento %.0f km/h" % c["viento_kmh"])
    s = "Clima a la hora del juego: %s." % ", ".join(partes)
    if c.get("mlb"):
        m = c["mlb"]
        s += " MLB: %s, %s F, viento %s%s." % (m.get("condicion"), m.get("temp_f"), m.get("viento"),
              (", ajuste medido al total %+.2f carreras" % m["ajuste_total_carreras"]) if m.get("ajuste_total_carreras") is not None else "")
    if c.get("alertas"):
        s += " Ojo: %s." % "; ".join(c["alertas"])
    return s


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--prueba":
        g = {"liga": "mlb", "tipo": "equipos", "fecha_utc": sys.argv[3], "estadio": sys.argv[2],
             "sede": dict(zip(("ciudad", "estado", "pais"), [x.strip() for x in sys.argv[2].split(",")] + [None, None]))}
        agregar([g]); print(json.dumps(g.get("clima"), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
