# -*- coding: utf-8 -*-
"""
PASO 2 - nucleo/io.py

La UNICA puerta de entrada/salida de datos de Edgeline. Todos los modelos y
scripts importan de aqui; ninguno lee CSVs crudos por su cuenta. Con esto muere
el desorden de "cada script lee de un archivo distinto".

Que ofrece:
  LIGAS                     registro central: liga -> {deporte, nombre, ids API}
  deporte_de(liga)          a que deporte pertenece una liga
  ligas_de(deporte)         que ligas tiene un deporte
  norm(s) / canon(s)        normalizar texto y nombres de equipo
  cargar_juegos(x)          lee datos/<deporte>.csv; x puede ser deporte o liga
  cargar_cuotas()           lee datos/cuotas.csv indexado, con tolerancia de fecha
  cuotas_del_partido(...)   busca cuota de un juego (±dias de tolerancia)
  escribir_monitor(data)    escribe salida/monitor_data.js (window.EDGELINE_DATA)
  ruta(*partes)             arma rutas dentro de la base

Solo stdlib. Colocar en:  C:\\Edgeline\\nucleo\\io.py

Prueba rapida (en C:\\Edgeline):
    python -c "from nucleo import sys
import io; io.diagnostico()"
"""
import io as _io, os, csv, json, re, unicodedata, datetime as _dt

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")

# ------------------------------------------------------------------ rutas
def ruta(*partes):
    return os.path.join(BASE, *partes)

DATOS   = lambda nombre: ruta("datos", nombre)
SALIDA  = lambda nombre: ruta("salida", nombre)

# ------------------------------------------------------------------ registro de ligas
# deporte agrupa las ligas que comparten esquema y modelo. Los ids son de la
# MLB Stats API (para el colector de beisbol); americano/hockey usan otras fuentes.
LIGAS = {
    # --- beisbol (datos/beisbol.csv) ---
    "mlb":    {"deporte": "beisbol",   "nombre": "MLB",    "sportId": 1,  "leagueId": None},
    "npb":    {"deporte": "beisbol",   "nombre": "NPB",    "sportId": 31, "leagueId": None},
    "kbo":    {"deporte": "beisbol",   "nombre": "KBO",    "sportId": 32, "leagueId": None},
    "lmp":    {"deporte": "beisbol",   "nombre": "LMP",    "sportId": 17, "leagueId": 132},
    "lvbp":   {"deporte": "beisbol",   "nombre": "LVBP",   "sportId": 17, "leagueId": 135},
    "lidom":  {"deporte": "beisbol",   "nombre": "LIDOM",  "sportId": 17, "leagueId": 131},
    "abl":    {"deporte": "beisbol",   "nombre": "ABL",    "sportId": 17, "leagueId": 595},
    # --- americano (datos/americano.csv) ---
    "nfl":    {"deporte": "americano", "nombre": "NFL"},
    "ncaafb": {"deporte": "americano", "nombre": "NCAAFB"},
    # --- hockey (datos/hockey.csv) ---
    "nhl":    {"deporte": "hockey",    "nombre": "NHL"},
    # --- futbol (datos/futbol.csv) ---
    "ligamx":    {"deporte": "futbol", "nombre": "Liga MX"},
    "champions": {"deporte": "futbol", "nombre": "Champions League"},
    "laliga":    {"deporte": "futbol", "nombre": "La Liga"},
    "premier":   {"deporte": "futbol", "nombre": "Premier League"},
    "seriea":    {"deporte": "futbol", "nombre": "Serie A"},
    "bundesliga":{"deporte": "futbol", "nombre": "Bundesliga"},
    "ligue1":    {"deporte": "futbol", "nombre": "Ligue 1"},
    "mls":       {"deporte": "futbol", "nombre": "MLS"},
    # --- nba (datos/nba.csv) ---
    "nba":       {"deporte": "nba",    "nombre": "NBA"},
    "ncaamb":    {"deporte": "nba",    "nombre": "NCAA basquetbol"},
    # --- tenis (datos/tenis.csv, match-level) ---
    "atp":       {"deporte": "tenis",  "nombre": "ATP"},
    "wta":       {"deporte": "tenis",  "nombre": "WTA"},
}

# archivo de datos por deporte
ARCHIVO_DEPORTE = {
    "beisbol":   "beisbol.csv",
    "americano": "americano.csv",
    "hockey":    "hockey.csv",
    "futbol":    "futbol.csv",
    "nba":       "nba.csv",
    "tenis":     "tenis.csv",
}

def deporte_de(liga):
    return (LIGAS.get(norm(liga)) or {}).get("deporte")

def ligas_de(deporte):
    return [lg for lg, d in LIGAS.items() if d["deporte"] == deporte]

def deportes():
    return sorted(set(d["deporte"] for d in LIGAS.values()))

# ------------------------------------------------------------------ normalizacion
def _sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def norm(s):
    """clave canonica: minusculas, sin acentos, sin puntuacion, sin espacios extra."""
    s = _sin_acentos(str(s or "")).lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

def canon(nombre):
    """nombre de equipo normalizado para emparejar resultados con cuotas."""
    return norm(nombre)

# ------------------------------------------------------------------ carga de juegos
csv.field_size_limit(min(2 ** 31 - 1, __import__("sys").maxsize))


import sys as _sys
csv.field_size_limit(min(2 ** 31 - 1, _sys.maxsize))


# Mismo equipo con otro nombre en la fuente (se unifica al leer, para que ELO, forma y angulos sigan la franquicia).
# LMP 2025-26: los Mayos de Navojoa jugaron esa temporada en Tucson ("Tucson Baseball Team") y regresan a Navojoa en
# 2026-27 (calendario de salida/sonda_lmp.json).
EQUIPO_ALIAS = {"Tucson Baseball Team": "Mayos de Navojoa"}


def _leer_csv(path):
    """Lee el CSV; una fila rota (escritura simultanea, corte) se descarta y no tumba la lectura.
    Unifica nombres de equipo de EQUIPO_ALIAS en las columnas team / opp / home / away."""
    if not os.path.exists(path):
        return []
    out = []
    with _io.open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = csv.DictReader(f)
        while True:
            try:
                r = next(rd)
            except StopIteration:
                break
            except csv.Error:
                continue
            if r.get(None) is None:
                for c in ("team", "opp", "home", "away", "home_team", "away_team"):
                    v = r.get(c)
                    if v in EQUIPO_ALIAS:
                        r[c] = EQUIPO_ALIAS[v]
                out.append(r)
    return out

def cargar_juegos(x, liga=None):
    """
    Devuelve la lista de filas del CSV del deporte.
    - cargar_juegos("beisbol")      -> todo beisbol
    - cargar_juegos("kbo")          -> solo KBO (detecta el deporte por la liga)
    - cargar_juegos("beisbol","kbo")-> igual, explicito
    Filtra por la columna 'league' (case/acento-insensible).
    """
    dep = x if x in ARCHIVO_DEPORTE else deporte_de(x)
    if dep is None:
        raise ValueError("No conozco deporte ni liga: %r" % x)
    filtro = liga or (x if x not in ARCHIVO_DEPORTE else None)
    filas = _leer_csv(DATOS(ARCHIVO_DEPORTE[dep]))
    if filtro:
        f = norm(filtro)
        filas = [r for r in filas if norm(r.get("league") or r.get("liga")) == f]
    return filas

# ------------------------------------------------------------------ cuotas
def _fecha_iso(s):
    s = str(s or "")[:10]
    try:
        _dt.date.fromisoformat(s); return s
    except ValueError:
        return ""

def cargar_cuotas():
    """
    Indexa datos/cuotas.csv por (liga, home, away) -> {fecha -> {(mercado,sel,pt): fila}}.
    Tolerante a esquemas: acepta home/home_team, away/away_team, date/commence_time_utc.
    """
    idx = {}
    for r in _leer_csv(DATOS("cuotas.csv")):
        lg   = norm(r.get("league") or r.get("liga"))
        home = canon(r.get("home") or r.get("home_team"))
        away = canon(r.get("away") or r.get("away_team"))
        fecha = _fecha_iso(r.get("date") or r.get("game_date") or r.get("commence_time_utc"))
        if not (lg and home and away and fecha):
            continue
        merc = (r.get("market") or "").strip()
        sel  = (r.get("selection") or r.get("outcome") or "").strip()
        pt   = (r.get("point") or r.get("line") or "").strip()
        idx.setdefault((lg, home, away), {}).setdefault(fecha, {})[(merc, sel, pt)] = r
    return idx

def cuotas_del_partido(idx, liga, home, away, fecha, tol=2):
    """cuota de un juego, buscando ±tol dias (la fecha UTC del mercado puede diferir)."""
    k = (norm(liga), canon(home), canon(away))
    porfecha = idx.get(k)
    if not porfecha:
        return {}
    f = _fecha_iso(fecha)
    if f in porfecha:
        return porfecha[f]
    for d in range(1, tol + 1):
        for sgn in (-1, 1):
            try:
                fx = (_dt.date.fromisoformat(f) + _dt.timedelta(days=sgn * d)).isoformat()
            except ValueError:
                continue
            if fx in porfecha:
                return porfecha[fx]
    return {}

# ------------------------------------------------------------------ salida al monitor
def escribir_monitor(data, nombre="monitor_data.js"):
    """Escribe salida/monitor_data.js como  window.EDGELINE_DATA = {...};"""
    os.makedirs(ruta("salida"), exist_ok=True)
    js = "window.EDGELINE_DATA = " + json.dumps(data, ensure_ascii=False, default=str) + ";\n"
    with _io.open(SALIDA(nombre), "w", encoding="utf-8", newline="") as f:
        f.write(js)
    return SALIDA(nombre)

# ------------------------------------------------------------------ diagnostico
def diagnostico():
    print("Base:", BASE)
    print("Deportes:", ", ".join(deportes()))
    for dep in deportes():
        path = DATOS(ARCHIVO_DEPORTE[dep])
        filas = _leer_csv(path)
        ligas = sorted(set(norm(r.get("league") or r.get("liga")) for r in filas)) if filas else []
        marca = "OK" if filas else "vacio/no existe"
        print("  %-10s %-14s %6d filas | ligas: %s"
              % (dep, ARCHIVO_DEPORTE[dep], len(filas), ", ".join(ligas) or "-"))
    cu = cargar_cuotas()
    print("  cuotas.csv  %d juegos indexados" % len(cu))
    print("Ligas registradas:", ", ".join("%s(%s)" % (lg, d["deporte"]) for lg, d in LIGAS.items()))


if __name__ == "__main__":
    diagnostico()
