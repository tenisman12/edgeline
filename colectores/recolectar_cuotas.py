# -*- coding: utf-8 -*-
"""
RECOLECTAR CUOTAS - snapshots para línea de cierre y movimiento.

Captura las cuotas de The Odds API en este instante y las AÑADE a un historial con
la hora de captura. Corriendo esto varias veces al día tienes, para cada juego:
  - la APERTURA (primer snapshot),
  - el CIERRE (último antes del partido),
  - todo el MOVIMIENTO intermedio,
que es lo que hace falta para medir CLV (¿le ganaste a la línea de cierre?) y para
mostrar cómo se movió la cuota.

No borra: cada corrida agrega filas nuevas. Una fila por (juego, mercado, selección, libro, hora).

Requisitos: tu llave de The Odds API en la variable de entorno EDGELINE_ODDS_KEY.
  Windows:  set EDGELINE_ODDS_KEY=tu_llave
  Actions:  secret ODDS_KEY

Uso (en tu compu):
  python recolectar_cuotas.py
  python recolectar_cuotas.py --deportes baseball_mlb,icehockey_nhl

Ideal: correrlo cada 2-3 horas (tarea programada / Action en cron) durante el día.
Escribe/actualiza:  data_maestra/market_odds_history.csv
"""
import argparse, csv, io, os, sys, json, datetime as dt
import urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "data_maestra", "market_odds_history.csv")
KEY = os.environ.get("EDGELINE_ODDS_KEY", "")
API = "https://api.the-odds-api.com/v4/sports/%s/odds/"
API_SPORTS = "https://api.the-odds-api.com/v4/sports/?apiKey=%s"       # lista de deportes activos: NO gasta creditos
PREFIJOS = ("tennis_atp", "tennis_wta")                                  # tenis: una clave por torneo, se descubren cada vez

# sport keys de The Odds API para tus deportes
# Todos los deportes de Edgeline deben tener cuota y linea: tambien NPB, KBO y tenis (los torneos se descubren solos).
DEPORTES = ["baseball_mlb", "baseball_npb", "baseball_kbo", "icehockey_nhl",
            "americanfootball_nfl", "americanfootball_ncaaf", "basketball_nba", "basketball_ncaab",
            "soccer_mexico_ligamx", "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
            "soccer_germany_bundesliga", "soccer_france_ligue_one", "soccer_uefa_champs_league", "soccer_usa_mls"]
SALIDA = os.path.join(BASE, "salida", "cuotas_casas.json")           # foto COMPLETA mas reciente (todas las casas): la lee plataforma.py
HIST = os.path.join(BASE, "salida", "cuotas_sharp_%s.csv")           # historia compacta por lado (sharp + mejor cuota) para CLV
HORAS = 60                                                            # solo partidos que empiezan en <= 60 h (ahorra creditos y espacio)
REGIONES = os.environ.get("EDGELINE_ODDS_REGIONES", "us,eu")            # eu: Pinnacle, bet365...; us: DraftKings, FanDuel... (6 creditos por deporte)
MERCADOS = "h2h,spreads,totals"
PRESUPUESTO = int(os.environ.get("EDGELINE_ODDS_PRESUPUESTO", "72"))   # creditos por corrida. Plan 20k/mes: 72 x 8 fotos/dia = ~17.3k/mes
PROXIMOS = os.path.join(BASE, "contexto", "proximos_espn.json")        # para priorizar los deportes que SI tienen partidos hoy
TOPE_MES = int(os.environ.get("EDGELINE_ODDS_TOPE_MES", "19000"))      # freno duro: nunca pasar del plan (20,000) aunque se lancen corridas a mano
CONTADOR = os.path.join(BASE, "salida", "odds_creditos.json")          # creditos usados por mes (lo lleva este script)

COLS = ["fetched_at_utc", "sport", "commence_time_utc", "home_team", "away_team",
        "bookmaker", "market", "selection", "point", "price_american"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Edgeline/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def snapshot(sportkey, ahora, eventos=None):
    url = API % sportkey + "?" + urllib.parse.urlencode(
        {"apiKey": KEY, "regions": REGIONES, "markets": MERCADOS,
         "oddsFormat": "american", "dateFormat": "iso"})
    try:
        data = get(url)
    except Exception as e:
        print("  %-26s error: %s" % (sportkey, str(e)[:70])); return []
    lim = (dt.datetime.strptime(ahora, "%Y-%m-%dT%H:%M:%SZ") + dt.timedelta(hours=HORAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = [ev for ev in data if (ev.get("commence_time") or "") <= lim]
    filas = []
    for ev in data:
        if eventos is not None:
            eventos.append({"sport": sportkey, "id": ev.get("id"), "commence_time": ev.get("commence_time"),
                            "home_team": ev.get("home_team"), "away_team": ev.get("away_team"),
                            "bookmakers": [{"key": bk.get("key"), "markets": [{"key": m.get("key"), "outcomes": [
                                {"name": o.get("name"), "price": o.get("price"), "point": o.get("point")}
                                for o in m.get("outcomes", [])]} for m in bk.get("markets", [])]}
                                for bk in ev.get("bookmakers", [])]})
        home, away = ev.get("home_team"), ev.get("away_team")
        ct = ev.get("commence_time")
        for bk in ev.get("bookmakers", []):
            bname = bk.get("key")
            for m in bk.get("markets", []):
                mk = m.get("key")
                for o in m.get("outcomes", []):
                    filas.append({"fetched_at_utc": ahora, "sport": sportkey,
                                  "commence_time_utc": ct, "home_team": home, "away_team": away,
                                  "bookmaker": bname, "market": mk,
                                  "selection": o.get("name"), "point": o.get("point", ""),
                                  "price_american": o.get("price")})
    print("  %-26s %d juegos, %d filas" % (sportkey, len(data), len(filas)))
    return filas


def _creditos_mes():
    mes = dt.date.today().strftime("%Y-%m")
    try:
        with io.open(CONTADOR, encoding="utf-8") as f:
            d = json.load(f)
        return int(d.get(mes, 0))
    except Exception:
        return 0


def _sumar_creditos(n):
    mes = dt.date.today().strftime("%Y-%m")
    d = {}
    try:
        with io.open(CONTADOR, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        pass
    d[mes] = int(d.get(mes, 0)) + n
    os.makedirs(os.path.dirname(CONTADOR), exist_ok=True)
    with io.open(CONTADOR, "w", encoding="utf-8") as f:
        json.dump(d, f)


def priorizar(deportes):
    """Ordena los deportes por cuantos partidos con modelo tienen hoy/manana (contexto/proximos_espn.json); los que no
    tienen partidos se quitan. Asi el presupuesto se gasta donde hay algo que puntuar."""
    try:
        sys.path.insert(0, BASE)
        from nucleo import sharp
        with io.open(PROXIMOS, encoding="utf-8") as f:
            juegos = json.load(f).get("partidos") or []
    except Exception:
        return deportes
    lim = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=HORAS)).strftime("%Y-%m-%dT%H:%M")
    n = {}
    for g in juegos:
        if (g.get("fecha_utc") or "")[:16] <= lim:
            n[g.get("liga")] = n.get(g.get("liga"), 0) + 1
    # NPB, KBO y ligas de invierno no estan en ESPN: su calendario viene de proximos_beisbol (se piden siempre que esten activas)
    try:
        sys.path.insert(0, os.path.join(BASE, "colectores"))
        import proximos_beisbol as PB
        for g in PB.recolectar(["npb", "kbo"], 3, verbose=False):
            n[g["liga"]] = n.get(g["liga"], 0) + 1
    except Exception:
        for lg in ("npb", "kbo"):
            n.setdefault(lg, 1)
    con = [(n.get(sharp.liga_de(d) or "", 0), d) for d in deportes]
    con = [x for x in con if x[0] > 0] or [(0, d) for d in deportes]
    return [d for _, d in sorted(con, key=lambda x: -x[0])]


def guardar_compacto(eventos, ahora):
    """salida/cuotas_casas.json (foto completa de ahora) + fila por lado en salida/cuotas_sharp_<anio>.csv (CLV)."""
    sys.path.insert(0, BASE)
    from nucleo import sharp
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with io.open(SALIDA, "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "eventos": eventos}, f, ensure_ascii=False)
    ruta = HIST % ahora[:4]
    cols = ["ts_utc", "sport", "event_id", "commence_time", "home", "away", "mercado", "lado", "linea",
            "p_sharp", "fuente", "mejor_cuota", "casa", "n_casas", "ref_cuota"]
    existe = os.path.exists(ruta); n = 0
    with io.open(ruta, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not existe:
            w.writeheader()
        for ev in eventos:
            for mk, lados, linea in (("h2h", None, None), ("totals", None, "pt"), ("spreads", None, "pt")):
                cot = sharp._lados(ev, mk)
                if not cot:
                    continue
                # linea mas comun entre casas (totals/spreads), para comparar lo mismo
                pts = [v[1] for d in cot.values() for v in d.values() if v[1] is not None]
                pt = max(set(pts), key=pts.count) if pts else None
                if mk != "h2h":
                    cot = sharp._lados(ev, mk, pt if mk == "totals" else (pt if pt is not None else None))
                    if mk == "spreads" and pt is not None:
                        # usar la linea del local como referencia
                        hp = [d["home"][1] for d in cot.values() if "home" in d and d["home"][1] is not None]
                        pt = max(set(hp), key=hp.count) if hp else pt
                        cot = sharp._lados(ev, mk, pt)
                tres = any("draw" in d for d in cot.values())
                lados_mk = {"h2h": ["home", "away"] + (["draw"] if tres else []), "totals": ["over", "under"], "spreads": ["home", "away"]}[mk]
                pr = sharp._precio(cot, lados_mk)
                for lado, x in pr.items():
                    w.writerow({"ts_utc": ahora, "sport": ev["sport"], "event_id": ev.get("id"), "commence_time": ev.get("commence_time"),
                                "home": ev.get("home_team"), "away": ev.get("away_team"), "mercado": mk, "lado": lado,
                                "linea": "" if pt is None else pt, "p_sharp": x["p_sharp"], "fuente": x["fuente"],
                                "mejor_cuota": x["mejor_cuota"], "casa": x["casa"], "n_casas": x["n_casas"],
                                "ref_cuota": "" if x["ref_cuota"] is None else x["ref_cuota"]}); n += 1
    print("Foto compacta: %d eventos en %s; %d filas sharp en %s" % (len(eventos), SALIDA, n, ruta))


def _edad_foto_horas():
    """horas desde 'generado' de salida/cuotas_casas.json; None si no hay foto legible."""
    try:
        with open(SALIDA, encoding="utf-8") as f:
            gen = json.load(f).get("generado") or ""
        t = dt.datetime.fromisoformat(gen.replace("Z", "+00:00"))
        if not t.tzinfo:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600.0
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deportes", help="lista separada por comas (default: todos)")
    ap.add_argument("--solo-compacto", action="store_true", help="no acumular data_maestra/market_odds_history.csv (Actions)")
    ap.add_argument("--min-horas", type=float, default=0, dest="min_horas",
                    help="no gastar creditos si la ultima foto (salida/cuotas_casas.json) tiene menos de N horas")
    args = ap.parse_args()
    if args.min_horas > 0:
        edad = _edad_foto_horas()
        if edad is not None and edad < args.min_horas:
            print("Foto de cuotas de hace %.1f h (< %.1f h): no se piden cuotas, 0 creditos." % (edad, args.min_horas)); return
        print("Ultima foto de cuotas: %s; se pide una nueva." % ("sin foto" if edad is None else "hace %.1f h" % edad))
    if not KEY:
        print("Falta la llave. Configura EDGELINE_ODDS_KEY (set EDGELINE_ODDS_KEY=tu_llave)."); return
    deportes = (args.deportes or os.environ.get("EDGELINE_ODDS_DEPORTES") or "").split(",")
    deportes = [d.strip() for d in deportes if d.strip()] or DEPORTES
    try:
        activos = [x["key"] for x in get(API_SPORTS % KEY) if x.get("active")]
        extra = [k for k in activos if k.startswith(PREFIJOS) and k not in deportes]      # torneos de tenis en curso
        deportes = [d for d in deportes if d in activos] + extra
        print("Deportes activos en The Odds API: %d; candidatos %d (tenis en curso: %s)" % (len(activos), len(deportes), ", ".join(extra) or "ninguno"))
    except Exception as e:
        print("No se pudo leer la lista de deportes (%s); se usan los configurados." % str(e)[:60])
    deportes = priorizar(deportes)
    costo = len(MERCADOS.split(",")) * len(REGIONES.split(","))
    usados = _creditos_mes()
    disponibles = max(0, TOPE_MES - usados)
    if disponibles < costo:
        print("Tope mensual alcanzado (%d de %d creditos usados este mes): no se piden cuotas hasta el mes que entra." % (usados, TOPE_MES)); return
    presupuesto = min(PRESUPUESTO, disponibles)
    maximo = max(1, presupuesto // costo)
    print("Creditos usados este mes: %d de %d; esta foto puede gastar hasta %d." % (usados, TOPE_MES, presupuesto))
    if len(deportes) > maximo:
        print("Presupuesto %d creditos (%d por deporte): se piden %d de %d deportes: %s" % (presupuesto, costo, maximo, len(deportes), ", ".join(deportes[:maximo])))
        deportes = deportes[:maximo]
    _sumar_creditos(len(deportes) * costo)
    ahora = dt.datetime.now(dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"

    print("Snapshot de cuotas %s" % ahora)
    filas, eventos = [], []
    for sk in deportes:
        filas += snapshot(sk, ahora, eventos)
    if not filas:
        print("Sin cuotas (¿deportes fuera de temporada o llave sin crédito?)."); return
    guardar_compacto(eventos, ahora)
    if args.solo_compacto:
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    existe = os.path.exists(OUT)
    with io.open(OUT, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if not existe:
            w.writeheader()
        w.writerows(filas)
    print("\nAgregadas %d filas a:\n  %s" % (len(filas), OUT))
    print("Corre esto cada 2-3 h para tener apertura->cierre y el movimiento.")


if __name__ == "__main__":
    main()
