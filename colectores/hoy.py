# -*- coding: utf-8 -*-
"""
HOY - arma el paquete del dia para el flujo "total IA".

Baja lo unico que Claude NO puede alcanzar desde su entorno: los partidos de hoy
y las cuotas, de todas las ligas de beisbol. Deja un archivo chico (hoy.csv) que
subes junto con tu historico (baseball_boxscores.csv). Con esos dos, Claude entrena
y predice el dia en su sesion.

Fuentes (todas las alcanza tu maquina):
    MLB + invierno (LMP/LVBP/LIDOM/ABL)  -> MLB Stats API (schedule)
    NPB                                   -> MLB Stats API sportId 31 (schedule)
    KBO                                   -> koreabaseball GetKboGameList
    cuotas (MLB/NPB/KBO)                  -> The Odds API (h2h + totals)

Uso (en C:\\Edgeline, tu Python normal):
    python hoy.py                     -> partidos de hoy + cuotas -> hoy.csv
    python hoy.py --fecha 2026-09-30
    python hoy.py --sin-cuotas        -> solo partidos (sin llamar The Odds API)

Luego subes a Claude:  hoy.csv  +  data_maestra/baseball_boxscores.csv
y le dices: "predice los de hoy".
"""
import argparse, csv, io, json, os, sys, datetime as dt
import urllib.request, urllib.parse

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
OUT = os.path.join(BASE, "hoy.csv")
STATS = "https://statsapi.mlb.com/api/v1"
KBO_LIST = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
ODDS = "https://api.the-odds-api.com/v4/sports/%s/odds/"
# tu llave de The Odds API (reemplazala si cambia)
ODDS_KEY = os.environ.get("EDGELINE_ODDS_KEY", "21cc03bffa0bf0cc576c768039b50301")

# liga -> (sportId, leagueId) para la MLB Stats API (None = todo el sport)
STATS_LIGAS = {"MLB": (1, None), "NPB": (31, None),
               "LMP": (17, 132), "LVBP": (17, 135), "LIDOM": (17, 131), "ABL": (17, 595)}
# liga -> sport key de The Odds API (las que cubre)
ODDS_LIGAS = {"MLB": "baseball_mlb", "NPB": "baseball_npb", "KBO": "baseball_kbo"}
KBO_EQ = {"HT": "Kia Tigers", "LG": "LG Twins", "OB": "Doosan Bears", "SS": "Samsung Lions",
          "LT": "Lotte Giants", "NC": "NC Dinos", "KT": "KT Wiz", "WO": "Kiwoom Heroes",
          "SK": "SSG Landers", "SSG": "SSG Landers", "HH": "Hanwha Eagles"}


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def post(url, payload):
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.koreabaseball.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("utf-8", "replace")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return json.loads(json.loads(txt))

def norm(s):
    return "".join(c for c in str(s or "").lower() if c.isalnum() or c == " ").strip()


# ---------------- partidos de hoy ----------------
def juegos_statsapi(liga, sportId, leagueId, fecha):
    url = STATS + "/schedule?" + urllib.parse.urlencode(
        {k: v for k, v in {"sportId": sportId, "leagueId": leagueId,
                           "startDate": fecha, "endDate": fecha, "gameType": "R,F,D,L,W,C,P"}.items()
         if v is not None})
    out = []
    for dia in get(url).get("dates", []):
        for g in dia.get("games", []):
            h = ((g.get("teams") or {}).get("home") or {}).get("team", {}).get("name")
            a = ((g.get("teams") or {}).get("away") or {}).get("team", {}).get("name")
            if h and a:
                out.append({"league": liga, "game_date": fecha, "home": h, "away": a})
    return out

def juegos_kbo(fecha):
    ds = fecha.replace("-", "")
    resp = post(KBO_LIST, {"leId": "1", "srId": "0,3,4,5,7", "date": ds})
    out = []
    for g in (resp.get("game", []) if isinstance(resp, dict) else []):
        gid = g.get("G_ID") or ""
        ac = g.get("AWAY_ID") or gid[8:10]; hc = g.get("HOME_ID") or gid[10:12]
        out.append({"league": "KBO", "game_date": fecha,
                    "home": KBO_EQ.get(hc, hc), "away": KBO_EQ.get(ac, ac)})
    return out


# ---------------- cuotas ----------------
def cuotas(liga, sportkey, fecha):
    url = ODDS % sportkey + "?" + urllib.parse.urlencode(
        {"apiKey": ODDS_KEY, "regions": "us,eu", "markets": "h2h,totals",
         "oddsFormat": "american", "dateFormat": "iso"})
    try:
        data = get(url)
    except Exception as e:
        print("  cuotas %s: %s" % (liga, str(e)[:80])); return {}
    idx = {}
    for ev in data:
        if (ev.get("commence_time") or "")[:10] != fecha:
            continue
        h, a = ev.get("home_team"), ev.get("away_team")
        precios = {"ml_home": "", "ml_away": "", "total_line": "", "over": "", "under": ""}
        libros = ev.get("bookmakers") or []
        if libros:
            for m in (libros[0].get("markets") or []):
                if m["key"] == "h2h":
                    for o in m["outcomes"]:
                        if norm(o["name"]) == norm(h): precios["ml_home"] = o.get("price")
                        elif norm(o["name"]) == norm(a): precios["ml_away"] = o.get("price")
                elif m["key"] == "totals":
                    for o in m["outcomes"]:
                        precios["total_line"] = o.get("point")
                        if o["name"].lower() == "over": precios["over"] = o.get("price")
                        elif o["name"].lower() == "under": precios["under"] = o.get("price")
        idx[(norm(h), norm(a))] = precios
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="YYYY-MM-DD (default hoy)")
    ap.add_argument("--sin-cuotas", action="store_true")
    args = ap.parse_args()
    fecha = args.fecha or dt.date.today().isoformat()

    filas = []
    for liga, (sid, lid) in STATS_LIGAS.items():
        try:
            js = juegos_statsapi(liga, sid, lid, fecha)
            print("%-6s %d juegos" % (liga, len(js))); filas += js
        except Exception as e:
            print("%-6s error: %s" % (liga, str(e)[:80]))
    try:
        jk = juegos_kbo(fecha); print("%-6s %d juegos" % ("KBO", len(jk))); filas += jk
    except Exception as e:
        print("KBO    error: %s" % str(e)[:80])

    if not filas:
        print("\nNo hay partidos hoy (%s) en ninguna liga. Prueba otra fecha." % fecha); return

    # pegar cuotas
    if not args.sin_cuotas:
        for liga, sk in ODDS_LIGAS.items():
            cu = cuotas(liga, sk, fecha)
            for f in filas:
                if f["league"] == liga:
                    pr = cu.get((norm(f["home"]), norm(f["away"])), {})
                    f.update(pr)

    cols = ["league", "game_date", "away", "home", "ml_home", "ml_away", "total_line", "over", "under"]
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    con_cuota = sum(1 for f in filas if f.get("ml_home"))
    print("\nEscritos %d partidos (%d con cuota) en:\n  %s" % (len(filas), con_cuota, OUT))
    print("\nAhora sube a Claude:  hoy.csv  +  data_maestra\\baseball_boxscores.csv")
    print("y dile: 'predice los de hoy'.")


if __name__ == "__main__":
    main()
