# -*- coding: utf-8 -*-
"""
RECOLECTAR TENIS (ESPN) - resultados ATP/WTA recientes desde el scoreboard publico de ESPN, sin llave.

Una llamada por fecha devuelve el torneo completo (todas sus rondas). Se consulta cada 5 dias y se
deduplica por torneo, asi que actualizar una semana cuesta 2-4 llamadas por circuito.
ESPN no da saque/resto: las filas nuevas traen marcador, ronda, mejor de 3/5 y superficie, con las
columnas de saque vacias. El ELO por superficie las usa; el promedio de saque solo usa filas con saque.

Reglas para parecerse a la data de Sackmann (tour-level):
  - solo individuales (Men's/Women's Singles), sin rondas de clasificacion, sin walkovers
  - eventos que no son Grand Slam: solo partidos con AMBOS jugadores conocidos en datos\\tenis.csv
    (deja fuera Challenger/WTA 125/ITF)
  - nombres alineados al historial (sin acentos ni mayusculas) para no partir a un jugador en dos

Uso:  python colectores\\recolectar_tenis_espn.py [--desde 2026-08-25] [--hasta 2026-09-29]
Escribe data_maestra\\tennis_espn.csv  (actualizar_todo.py lo mezcla en datos\\tenis.csv)
"""
import argparse, csv, io, json, os, re, subprocess, unicodedata, datetime as dt
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")
OUT = os.path.join(BASE, "data_maestra", "tennis_espn.csv")
DATOS = os.path.join(BASE, "datos", "tenis.csv")
URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/%s/scoreboard?dates=%s"
COLS = ["tour", "tourney_date", "tourney_name", "surface", "tourney_level", "best_of", "round",
        "winner_name", "loser_name", "score"]
GRUPO_TOUR = {"men's singles": "ATP", "women's singles": "WTA"}
ESTADOS_OK = {"STATUS_FINAL": "", "STATUS_RETIRED": " RET"}

ARCILLA = ("roland garros", "french open", "madrid", "rome", "italian", "monte", "barcelona", "hamburg",
           "estoril", "houston", "marrakech", "bucharest", "munich", "geneva", "lyon", "bastad", "gstaad",
           "umag", "kitzbuhel", "bogota", "buenos aires", "rio", "santiago", "cordoba", "cagliari", "parma",
           "palermo", "prague", "rabat", "strasbourg", "charleston", "lausanne", "warsaw", "budapest",
           "portoroz", "iasi", "florianopolis", "sao paulo", "belgrade", "sardinia", "tenerife", "antalya",
           "montreux", "kia open", "madeira", "hassan", "bucarest", "gijon", "quito", "santa cruz")
PASTO = ("wimbledon", "halle", "queen", "hertogenbosch", "libema", "rosmalen", "mallorca", "eastbourne",
         "newport", "stuttgart", "birmingham", "nottingham", "berlin", "bad homburg", "surbiton", "ilkley")


def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", sin_acentos(s).lower()).strip()


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def bajar(tour, fecha):
    """ESPN responde 403 al User-Agent de Python en algunas redes; curl.exe si pasa. Se prueban los dos."""
    url = URL % (tour, fecha.strftime("%Y%m%d"))
    err = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as ex:
        err = str(ex)[:50]
    try:
        exe = "curl.exe" if os.name == "nt" else "curl"
        out = subprocess.run([exe, "-sS", "-L", "-m", "60", url], capture_output=True, timeout=90)
        return json.loads(out.stdout.decode("utf-8", "replace"))
    except Exception as ex:
        print("  %s %s: sin respuesta (%s | curl: %s)" % (tour, fecha, err, str(ex)[:40]))
        return None


def historial():
    """-> (nombre normalizado -> nombre canonico, torneo normalizado -> superficie, ultima fecha, pares recientes)"""
    nombres, sup, ult, pares = {}, {}, "", set()
    if not os.path.exists(DATOS):
        return nombres, sup, ult, pares
    with io.open(DATOS, encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in ("winner_name", "loser_name"):
            if r.get(c): nombres.setdefault(norm(r[c]), r[c])
        if r.get("tourney_name") and r.get("surface"):
            sup[norm(r["tourney_name"])] = r["surface"]           # gana la mas reciente (filas ordenadas)
        ult = max(ult, r.get("tourney_date") or "")
    corte = (dt.date(int(ult[:4]), int(ult[4:6]), int(ult[6:8])) - dt.timedelta(days=60)).strftime("%Y%m%d") if len(ult) == 8 else ""
    for r in rows:
        if (r.get("tourney_date") or "") >= corte:
            pares.add((norm(r.get("winner_name")), norm(r.get("loser_name"))))    # cruce, sin fecha ni ronda
    return nombres, sup, ult, pares


def superficie(nombre, hist_sup):
    n = norm(nombre)
    if n in hist_sup: return hist_sup[n]
    if any(k in n for k in PASTO): return "Grass"
    if any(k in n for k in ARCILLA): return "Clay"
    return "Hard"


def marcador(win, los):
    sets = []
    for a, b in zip(win.get("linescores") or [], los.get("linescores") or []):
        try:
            gw, gl = int(a["value"]), int(b["value"])
        except (KeyError, TypeError, ValueError):
            continue
        s = "%d-%d" % (gw, gl)
        tbs = [x.get("tiebreak") for x in (a, b) if x.get("tiebreak") is not None]
        if tbs: s += "(%d)" % min(int(t) for t in tbs)
        sets.append(s)
    return " ".join(sets)


def ronda(txt):
    t = (txt or "").strip()
    return {"Quarterfinal": "QF", "Semifinal": "SF", "Final": "F"}.get(t, t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="AAAA-MM-DD; por defecto 7 dias antes de la ultima fecha del historial")
    ap.add_argument("--hasta", help="AAAA-MM-DD; por defecto hoy")
    args = ap.parse_args()
    nombres, hsup, ult, pares = historial()
    hoy = dt.date.today()
    if args.desde:
        d0 = dt.date.fromisoformat(args.desde)
    elif len(ult) == 8:
        d0 = dt.date(int(ult[:4]), int(ult[4:6]), int(ult[6:8])) - dt.timedelta(days=7)
    else:
        d0 = hoy - dt.timedelta(days=30)
    d1 = dt.date.fromisoformat(args.hasta) if args.hasta else hoy
    print("Ventana ESPN: %s a %s" % (d0, d1))

    eventos = {}                                   # (tour_endpoint, id evento) -> evento
    d = d0
    while d <= d1:
        for tour in ("atp", "wta"):
            js = bajar(tour, d)
            for e in (js or {}).get("events") or []:
                eventos.setdefault(e.get("id"), e)
        d += dt.timedelta(days=5)
    if not eventos:
        print("ESPN no devolvio torneos; no se escribe nada."); return

    filas, vistos, descartes = [], set(), {"clasif": 0, "walkover": 0, "desconocidos": 0, "duplicado": 0}
    for e in eventos.values():
        nombre = e.get("name") or ""
        major = bool(e.get("major"))
        inicio = (e.get("date") or "")[:10].replace("-", "")
        if not inicio or not (d0 - dt.timedelta(days=25)).strftime("%Y%m%d") <= inicio <= d1.strftime("%Y%m%d"):
            continue
        sup = superficie(nombre, hsup)
        n_ev = 0
        for g in e.get("groupings") or []:
            tour = GRUPO_TOUR.get(((g.get("grouping") or {}).get("displayName") or "").lower())
            if not tour: continue
            for c in g.get("competitions") or []:
                cid = c.get("id")
                if cid in vistos: continue
                vistos.add(cid)
                rd = (c.get("round") or {}).get("displayName") or ""
                if "qualif" in rd.lower():
                    descartes["clasif"] += 1; continue
                est = (c.get("status") or {}).get("type", {}).get("name")
                if est == "STATUS_WALKOVER":
                    descartes["walkover"] += 1; continue
                if est not in ESTADOS_OK: continue
                comp = c.get("competitors") or []
                if len(comp) != 2: continue
                win = next((x for x in comp if x.get("winner")), None)
                los = next((x for x in comp if x is not win), None)
                if not win or not los: continue
                nw = (win.get("athlete") or {}).get("displayName"); nl = (los.get("athlete") or {}).get("displayName")
                if not nw or not nl: continue
                kw, kl = norm(nw), norm(nl)
                if not major and (kw not in nombres or kl not in nombres):
                    descartes["desconocidos"] += 1; continue
                if (kw, kl) in pares:
                    descartes["duplicado"] += 1; continue   # ya esta en el historial (p. ej. bajado de TML con saque)
                sc = marcador(win, los)
                if not sc: continue
                # ESPN reporta 5 periodos segun el endpoint consultado, no segun el circuito real:
                # mejor de 5 solo en los Grand Slam masculinos; todo lo demas es mejor de 3.
                bo = 5 if (tour == "ATP" and major) else 3
                filas.append({"tour": tour, "tourney_date": inicio, "tourney_name": nombre, "surface": sup,
                              "tourney_level": "G" if major else "", "best_of": bo, "round": ronda(rd),
                              "winner_name": nombres.get(kw, nw), "loser_name": nombres.get(kl, nl),
                              "score": sc + ESTADOS_OK[est]})
                n_ev += 1
        print("  %-28s %s  %-5s %4d partidos" % (nombre[:28], inicio, sup, n_ev))
    if not filas:
        print("Sin partidos nuevos; no se escribe nada."); return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader(); w.writerows(filas)
    print("Descartados: %d clasificacion, %d walkovers, %d con jugadores desconocidos (Challenger/125/ITF), %d ya en el historial" % (
        descartes["clasif"], descartes["walkover"], descartes["desconocidos"], descartes["duplicado"]))
    print("Escritos %d partidos en %s" % (len(filas), OUT))
    print("Revisa la superficie de cada torneo en la lista de arriba; si alguna esta mal, dimelo.")


if __name__ == "__main__":
    main()
