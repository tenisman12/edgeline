# -*- coding: utf-8 -*-
"""
colectores/recolectar_publico.py - EL PUBLICO: porcentajes de boletos y dinero por lado, y atencion mediatica por equipo.

Dos fuentes gratuitas, cada una independiente (si una falla, la otra sigue):
  1. Action Network (tablero publico de cuotas): por partido y mercado (ML, spread, total), % de boletos y % de dinero
     en cada lado, del consenso de casas que publica el sitio. Se leen los mismos endpoints publicos que usa su pagina;
     sin cuenta ni llave. Deportes: nfl, nba, mlb, nhl, ncaaf, ncaab (KBO, NPB y tenis no estan).
  2. Google News (RSS, sin llave): cuantas notas salieron sobre cada equipo en las ultimas 48 h. Es el "ruido" mediatico.

Salida:
  salida/publico.json            foto actual (lo lee picks_del_dia.py y la pagina)
  salida/publico_<anio>.csv      una fila por partido/mercado/foto, para medir despues (boletos vs dinero vs resultado)

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python colectores\\recolectar_publico.py                 # partidos de hoy y manana en proximos.json
    python colectores\\recolectar_publico.py --dias 3 --sin-noticias
    python colectores\\recolectar_publico.py --debug nfl      # imprime la respuesta cruda de Action Network y sale
    python colectores\\recolectar_publico.py --ver             # imprime la ultima foto guardada
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
AN_API = "https://api.actionnetwork.com/web/v2/scoreboard/%s?period=game&date=%s"
AN_DEPORTE = {"nfl": "nfl", "nba": "nba", "mlb": "mlb", "nhl": "nhl", "ncaafb": "ncaaf", "ncaamb": "ncaab"}
GN_RSS = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
TZ = -6
PAUSA = 0.5


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _hoy():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()


# ------------------------------------------------------------------ Action Network: boletos y dinero
def _pct(d, lado):
    """saca un porcentaje de un dict de Action Network (acepta 'home'/'away'/'over'/'under' o listas)."""
    if not isinstance(d, dict):
        return None
    v = d.get(lado)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _splits_de(game):
    """Los porcentajes del publico viven en game["markets"][<book_id>]["event"][<mercado>], una lista de salidas con
    side (home/away/over/under) y bet_info {"tickets": {"percent": N}, "money": {"percent": N}}. Action Network repite
    el mismo consenso en cada casa: se toma la casa con mas porcentajes distintos de cero (preferencia por la 15).
    -> {ml: {tickets_home, money_home}, spread: {...}, total: {tickets_over, money_over}, ...}"""
    def num(x):
        try:
            return None if x is None else float(x)
        except (TypeError, ValueError):
            return None
    MERCADOS = (("ml", "moneyline", "home"), ("spread", "spread", "home"), ("total", "total", "over"))
    mejor, out = -1, {}
    for book, m in (game.get("markets") or {}).items():
        ev = (m or {}).get("event") or {}
        cand, n = {"book_id": book}, 0
        for nombre, llave, lado_a in MERCADOS:
            tk = mn = cuota_a = cuota_b = linea = None
            for o in ev.get(llave) or []:
                bi = o.get("bet_info") or {}
                t = num((bi.get("tickets") or {}).get("percent"))
                d = num((bi.get("money") or {}).get("percent"))
                if o.get("side") == lado_a:
                    tk, mn, cuota_a = t, d, o.get("odds")
                    if o.get("value") not in (None, 0):
                        linea = o.get("value")
                else:
                    cuota_b = o.get("odds")
                    if tk is None and t is not None:          # solo vino el otro lado: se complementa
                        tk, mn = 100.0 - t, (None if d is None else 100.0 - d)
            if nombre == "total":
                cand["total"] = {"tickets_over": tk, "money_over": mn}
                cand["total_linea"] = linea
                cand["over_odds"], cand["under_odds"] = cuota_a, cuota_b
            else:
                cand[nombre] = {"tickets_home": tk, "money_home": mn}
                if nombre == "ml":
                    cand["ml_home"], cand["ml_away"] = cuota_a, cuota_b
                else:
                    cand["spread_home"] = linea
            n += sum(1 for v in (tk, mn) if v)                 # cero no cuenta: mercado aun sin accion
        if n > mejor or (n == mejor and str(book) == "15"):
            mejor, out = n, cand
    return out if mejor > 0 else {}


def action_network(deporte, fecha, debug=False):
    """[{home, away, inicio_utc, splits}] del tablero publico para esa fecha (AAAA-MM-DD)."""
    key = AN_DEPORTE.get(deporte)
    if not key:
        return []
    url = AN_API % (key, fecha.replace("-", ""))
    txt = _get(url)
    d = json.loads(txt)
    if debug:
        gs = d.get("games") or []
        print("url:", url); print("claves de la respuesta:", list(d.keys()), "| games:", len(gs))
        if gs:
            g = gs[0]
            print("claves de un juego:", list(g.keys()))
            print("teams:", json.dumps([{k: t.get(k) for k in ("id", "full_name", "display_name", "abbr")} for t in (g.get("teams") or [])], ensure_ascii=False))
            print("home_team_id / away_team_id:", g.get("home_team_id"), g.get("away_team_id"), "| start_time:", g.get("start_time"), "| status:", g.get("status"))
            od = g.get("odds") or []
            print("odds:", len(od), "registros; claves del primero:", list(od[0].keys()) if od else None)
            for o in od[:3]:
                print("  odd:", json.dumps({k: o.get(k) for k in ("book_id", "type", "ml_home", "ml_away", "spread_home", "total", "bet_info")}, ensure_ascii=False)[:700])
            # cualquier clave que suene a boletos/dinero en todo el juego
            def buscar(x, ruta=""):
                if isinstance(x, dict):
                    for k, v in x.items():
                        if any(w in str(k).lower() for w in ("bet", "ticket", "money", "percent", "public", "split", "consensus")):
                            print("  pista:", ruta + "/" + str(k), "=", json.dumps(v, ensure_ascii=False)[:300])
                        buscar(v, ruta + "/" + str(k))
                elif isinstance(x, list):
                    for i, v in enumerate(x[:3]):
                        buscar(v, ruta + "[%d]" % i)
            buscar(g)
        return []
    out = []
    for g in d.get("games") or []:
        eq = {t.get("id"): t for t in (g.get("teams") or [])}
        home = (eq.get(g.get("home_team_id")) or {}).get("full_name") or (eq.get(g.get("home_team_id")) or {}).get("display_name")
        away = (eq.get(g.get("away_team_id")) or {}).get("full_name") or (eq.get(g.get("away_team_id")) or {}).get("display_name")
        sp = _splits_de(g)
        if home and away and sp:
            out.append({"home": home, "away": away, "inicio_utc": g.get("start_time"), "splits": sp,
                        "estado": g.get("status"), "num_bets": g.get("num_bets")})
    return out


# ------------------------------------------------------------------ Google News: atencion
def noticias(equipo, horas=48):
    """numero de notas de Google News sobre el equipo en las ultimas `horas`; None si falla."""
    try:
        txt = _get(GN_RSS % urllib.parse.quote('"%s"' % equipo), timeout=20)
        root = ET.fromstring(txt)
        lim = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=horas)
        n = 0
        for it in root.iter("item"):
            f = (it.findtext("pubDate") or "").strip()
            try:
                when = dt.datetime.strptime(f, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
            if when >= lim:
                n += 1
        return n
    except Exception:
        return None


# ------------------------------------------------------------------ emparejar con proximos.json
_IGN = {"the", "fc", "sc", "club", "de", "los", "las", "la", "el", "st", "state", "university"}


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _IGN}


def _parecido(a, b):
    A, B = _norm(a), _norm(b)
    return len(A & B) / float(min(len(A), len(B))) if A and B else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=2)
    ap.add_argument("--sin-noticias", dest="noticias", action="store_false")
    ap.add_argument("--debug", metavar="DEPORTE")
    ap.add_argument("--ver", action="store_true")
    a = ap.parse_args()
    rj = os.path.join(BASE, "salida", "publico.json")
    if a.ver:
        d = json.load(io.open(rj, encoding="utf-8"))
        print("PUBLICO | generado %s | %d partidos (boletos/dinero en %%)" % (d.get("generado"), len(d.get("partidos") or [])))
        for p in d["partidos"]:
            s = p.get("splits") or {}; ml = s.get("ml") or {}; sp_ = s.get("spread") or {}; tt = s.get("total") or {}
            def pc(x):
                return "-" if x is None else "%.0f" % x
            print("  %-6s %s %-38s ML local %s/%s | spread %s/%s | over %s/%s | apuestas %s | notas %s/%s" % (
                p["liga"], p["fecha"], ("%s @ %s" % (p["away"], p["home"]))[:38],
                pc(ml.get("tickets_home")), pc(ml.get("money_home")), pc(sp_.get("tickets_home")), pc(sp_.get("money_home")),
                pc(tt.get("tickets_over")), pc(tt.get("money_over")), p.get("num_bets") or "-",
                (p.get("atencion") or {}).get("away"), (p.get("atencion") or {}).get("home")))
        return
    if a.debug:
        action_network(a.debug, _hoy().isoformat(), debug=True); return
    with io.open(os.path.join(BASE, "salida", "proximos.json"), encoding="utf-8") as f:
        D = json.load(f)
    hoy = _hoy(); lim = (hoy + dt.timedelta(days=a.dias - 1)).isoformat()
    sel = [p for p in D["partidos"] if hoy.isoformat() <= p["fecha"] <= lim]
    ahora = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 1) splits por liga y fecha
    cache = {}
    def tablero(liga, fecha):
        k = (AN_DEPORTE.get(liga), fecha)
        if k[0] is None:
            return []
        if k not in cache:
            try:
                cache[k] = action_network(liga, fecha); time.sleep(PAUSA)
            except Exception as e:
                print("  Action Network %s %s: %s" % (liga, fecha, str(e)[:100])); cache[k] = []
        return cache[k]
    partidos, con_splits, notas_cache = [], 0, {}
    for p in sel:
        home, away = p["home"]["nombre"], p["away"]["nombre"]
        if "TBD" in (home + away).upper():
            continue
        fila = {"liga": p["liga"], "id": str(p["id"]), "fecha": p["fecha"], "hora": p.get("hora"), "home": home, "away": away, "splits": None, "atencion": None}
        mejor, pts = None, 0.0
        for fecha in (p["fecha"], (dt.date.fromisoformat(p["fecha"]) + dt.timedelta(days=1)).isoformat()):
            for g in tablero(p["liga"], fecha):
                s = _parecido(g["home"], home) + _parecido(g["away"], away)
                if s > pts:
                    mejor, pts = g, s
        if mejor and pts >= 1.2:
            fila["splits"] = mejor["splits"]; fila["splits"]["fuente"] = "action_network"
            fila["num_bets"] = mejor.get("num_bets"); con_splits += 1
        if a.noticias:
            for lado, nombre in (("home", home), ("away", away)):
                if nombre not in notas_cache:
                    notas_cache[nombre] = noticias(nombre); time.sleep(0.3)
            fila["atencion"] = {"home": notas_cache[home], "away": notas_cache[away], "fuente": "google_news_48h"}
        partidos.append(fila)
    with io.open(rj, "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "partidos": partidos}, f, ensure_ascii=False, indent=1)
    # 2) historial plano
    rc = os.path.join(BASE, "salida", "publico_%d.csv" % hoy.year)
    cols = ["ts_utc", "liga", "id", "fecha", "home", "away", "ml_tickets_home", "ml_money_home", "spread_tickets_home", "spread_money_home",
            "total_tickets_over", "total_money_over", "ml_home", "ml_away", "spread_home", "total", "num_bets", "notas_home", "notas_away"]
    nuevo = not os.path.exists(rc)
    with io.open(rc, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if nuevo:
            w.writeheader()
        for p in partidos:
            s = p.get("splits") or {}; at = p.get("atencion") or {}
            if not s and not at:
                continue
            w.writerow({"ts_utc": ahora, "liga": p["liga"], "id": p["id"], "fecha": p["fecha"], "home": p["home"], "away": p["away"],
                        "ml_tickets_home": (s.get("ml") or {}).get("tickets_home", ""), "ml_money_home": (s.get("ml") or {}).get("money_home", ""),
                        "spread_tickets_home": (s.get("spread") or {}).get("tickets_home", ""), "spread_money_home": (s.get("spread") or {}).get("money_home", ""),
                        "total_tickets_over": (s.get("total") or {}).get("tickets_over", ""), "total_money_over": (s.get("total") or {}).get("money_over", ""),
                        "ml_home": s.get("ml_home", ""), "ml_away": s.get("ml_away", ""), "spread_home": s.get("spread_home", ""), "total": s.get("total_linea", ""), "num_bets": p.get("num_bets", ""),
                        "notas_home": at.get("home", ""), "notas_away": at.get("away", "")})
    print("Publico: %d partidos, %d con boletos/dinero (Action Network), noticias %s -> salida/publico.json y %s" % (
        len(partidos), con_splits, "si" if a.noticias else "no", os.path.basename(rc)))
    for p in partidos:
        s = p.get("splits") or {}
        if s:
            ml = s.get("ml") or {}; tt = s.get("total") or {}
            print("  %-6s %-38s ML local boletos %s%% dinero %s%% | over boletos %s%% dinero %s%% | %s apuestas" % (
                p["liga"], ("%s @ %s" % (p["away"], p["home"]))[:38], ml.get("tickets_home"), ml.get("money_home"),
                tt.get("tickets_over"), tt.get("money_over"), p.get("num_bets") or "-"))


if __name__ == "__main__":
    main()
