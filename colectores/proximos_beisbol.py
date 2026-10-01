# -*- coding: utf-8 -*-
"""
colectores/proximos_beisbol.py - PARTIDOS POR JUGAR de NPB, KBO, LMP, LVBP, LIDOM y ABL.

ESPN no publica estas ligas. Calendario:
  LMP, LVBP, LIDOM, ABL       ->  MLB Stats API  /schedule (con abridor probable cuando lo hay)
  NPB                         ->  npb.jp calendario oficial por mes (la MLB Stats API no trae NPB)
  KBO                         ->  koreabaseball.com GetKboGameList (el mismo endpoint de recolectar_kbo.py)

Devuelve los juegos con el MISMO esquema que colectores/recolectar_proximos.py (id, liga, tipo, fecha_utc,
estado, home/away, cuotas, contexto), para que plataforma.py los trate igual que los de ESPN. No hay cuotas
ni contexto: ESPN no los publica para estas ligas (la pagina lo marca como bloque no disponible).

Uso suelto (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python colectores\\proximos_beisbol.py --dias 3
    python colectores\\proximos_beisbol.py --dias 2 --ligas npb,kbo

Solo stdlib.
"""
import argparse, datetime as dt, json, sys, urllib.parse, urllib.request

API = "https://statsapi.mlb.com/api/v1"
LIGAS_API = {"lmp": (17, 132), "lvbp": (17, 135), "lidom": (17, 131), "abl": (17, 595)}
DEFAULT = ["npb", "kbo", "lmp", "lvbp", "lidom", "abl"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
KBO_LIST = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
KBO_EQ = {"HT": "Kia Tigers", "LG": "LG Twins", "OB": "Doosan Bears", "SS": "Samsung Lions",
          "LT": "Lotte Giants", "NC": "NC Dinos", "KT": "KT Wiz", "WO": "Kiwoom Heroes",
          "SK": "SSG Landers", "SSG": "SSG Landers", "HH": "Hanwha Eagles"}
NO_JUGAR = ("Final", "Postponed", "Cancelled", "Suspended", "Completed Early", "Game Over")


def _get(url, data=None, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json,*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def _equipo(t, probable=None):
    nombre = (t or {}).get("name") or ""
    return {"nombre": nombre, "corto": (t or {}).get("teamName") or nombre.split(" ")[-1] if nombre else "",
            "abrev": (t or {}).get("abbreviation"), "loc": (t or {}).get("locationName"), "logo": None,
            "record": None, "probable": probable, "probable_rol": "SP" if probable else None, "ranking": None}


def juegos_api(liga, desde, hasta, texto=None):
    """MLB Stats API schedule -> lista de juegos por jugar. 'texto' permite probar con una respuesta ya bajada."""
    sid, lid = LIGAS_API[liga]
    if texto is None:
        q = {"sportId": sid, "startDate": desde, "endDate": hasta, "hydrate": "probablePitcher,team",
             "gameType": "R,F,D,L,W,C,P"}
        if lid:
            q["leagueId"] = lid
        texto = _get(API + "/schedule?" + urllib.parse.urlencode(q))
    d = json.loads(texto)
    out = []
    for dia in d.get("dates", []):
        for g in dia.get("games", []):
            est = (g.get("status") or {}).get("detailedState") or (g.get("status") or {}).get("abstractGameState") or ""
            if (g.get("status") or {}).get("abstractGameState") == "Final" or est in NO_JUGAR:
                continue
            tm = g.get("teams") or {}
            away, home = tm.get("away") or {}, tm.get("home") or {}
            pa = (away.get("probablePitcher") or {}).get("fullName")
            ph = (home.get("probablePitcher") or {}).get("fullName")
            f = g.get("gameDate") or ""
            if not f:
                continue
            out.append({"id": "mlbapi-%s" % g.get("gamePk"), "liga": liga, "tipo": "equipos",
                        "fecha_utc": f[:16] + "Z" if f else None, "estado": est,
                        "home": _equipo(home.get("team"), ph), "away": _equipo(away.get("team"), pa),
                        "cuotas": {}, "contexto": {}, "nota": (g.get("seriesDescription") or None),
                        "serie": None, "estadio": (g.get("venue") or {}).get("name")})
    return out


NPB_EQ = {"阪神": "Tigers", "巨人": "Giants", "広島": "Carp", "中日": "Dragons", "ヤクルト": "Swallows",
          "DeNA": "Bay Stars", "ソフトバンク": "Hawks", "日本ハム": "Fighters", "ロッテ": "Marines",
          "西武": "Lions", "オリックス": "Buffaloes", "楽天": "Golden Eagles"}
NPB_URL = "https://npb.jp/games/%d/schedule_%02d_detail.html"


def juegos_npb_html(texto, anio, desde, hasta):
    """Calendario mensual de npb.jp -> juegos sin jugar entre las fechas 'desde' y 'hasta' (date).
    Estructura: <tr id="dateMMDD"> ... team1 (local) / team2 (visita), score1 vacio si no se ha jugado, hora JST."""
    import re
    out = []
    filas = re.split(r'(?=<tr id="date\d{4}")', texto)
    for fila in filas:
        m = re.match(r'<tr id="date(\d{2})(\d{2})"', fila)
        if not m:
            continue
        mes, dia = int(m.group(1)), int(m.group(2))
        try:
            fecha = dt.date(anio, mes, dia)
        except ValueError:
            continue
        if fecha < desde or fecha > hasta:
            continue
        mt = re.search(r'<div class="team1">([^<]*)</div>.*?<div class="team2">([^<]*)</div>', fila, re.S)
        if not mt:
            continue
        loc, vis = mt.group(1).strip(), mt.group(2).strip()
        if loc not in NPB_EQ or vis not in NPB_EQ:
            continue
        sc = re.search(r'<div class="score1">(.*?)</div>', fila, re.S)
        if sc and re.sub(r'(&nbsp;|\s)', "", sc.group(1)):
            continue                                   # ya tiene marcador: jugado
        com = (re.search(r'<div class="comment">(.*?)</div>', fila, re.S) or [None, ""])[1]
        if any(k in com for k in ("中止", "ノーゲーム", "延期")):
            continue                                   # suspendido o pospuesto
        hr = re.search(r'<div class="time">\s*(\d{1,2}):(\d{2})', fila)
        fu = None
        if hr:
            f = dt.datetime(anio, mes, dia, int(hr.group(1)), int(hr.group(2))) - dt.timedelta(hours=9)   # JST -> UTC
            fu = f.strftime("%Y-%m-%dT%H:%MZ")
        else:
            fu = "%s-%02d-%02dT09:00Z" % (anio, mes, dia)
        est = (re.search(r'<div class="place">\s*(.*?)\s*</div>', fila, re.S) or [None, None])[1]
        sp = re.findall(r'<div class="pit">\s*先発：([^<\s]+)', fila)
        pl, pv = (sp[0] if len(sp) > 0 else None), (sp[1] if len(sp) > 1 else None)
        out.append({"id": "npb-%s%02d%02d-%s-%s" % (anio, mes, dia, loc, vis), "liga": "npb", "tipo": "equipos",
                    "fecha_utc": fu, "estado": "Programado",
                    "home": _equipo({"name": NPB_EQ[loc], "teamName": NPB_EQ[loc]}, pl),
                    "away": _equipo({"name": NPB_EQ[vis], "teamName": NPB_EQ[vis]}, pv),
                    "cuotas": {}, "contexto": {}, "nota": None, "serie": None, "estadio": est})
    return out


def juegos_npb(desde, hasta):
    out, vistos = [], set()
    m = dt.date(desde.year, desde.month, 1)
    while m <= hasta:
        texto = _get(NPB_URL % (m.year, m.month))
        for g in juegos_npb_html(texto, m.year, desde, hasta):
            if g["id"] not in vistos:
                vistos.add(g["id"]); out.append(g)
        m = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


def juegos_kbo(fecha, texto=None):
    """fecha AAAAMMDD. Calendario de la KBO -> juegos por jugar (sin hora si el sitio no la publica)."""
    if texto is None:
        data = urllib.parse.urlencode({"leId": "1", "srId": "0,3,4,5,7", "date": fecha}).encode()
        texto = _get(KBO_LIST, data, {"Content-Type": "application/x-www-form-urlencoded",
                                      "Referer": "https://www.koreabaseball.com/"})
    try:
        d = json.loads(texto)
    except json.JSONDecodeError:
        return []
    if isinstance(d, str):
        d = json.loads(d)
    out = []
    for g in (d.get("game", []) if isinstance(d, dict) else []):
        if str(g.get("GAME_STATE_SC")) == "3" or str(g.get("CANCEL_SC_ID", "0")) not in ("0", "", "None"):
            continue                       # 3 = terminado; CANCEL_SC_ID distinto de 0 = suspendido/cancelado
        core = str(g.get("G_ID") or "")[8:]
        aw = "SSG" if core[:3] == "SSG" else core[:2]
        hm = core[3:5] if core[:3] == "SSG" else core[2:4]
        if aw not in KBO_EQ or hm not in KBO_EQ:
            continue
        hora = str(g.get("G_TM") or "").strip()
        fu = None
        try:
            f = dt.datetime.strptime(fecha + hora, "%Y%m%d%H:%M") - dt.timedelta(hours=9)   # KST -> UTC
            fu = f.strftime("%Y-%m-%dT%H:%MZ")
        except ValueError:
            fu = "%s-%s-%sT09:00Z" % (fecha[:4], fecha[4:6], fecha[6:8])
        pa, ph = g.get("T_PIT_P_NM"), g.get("B_PIT_P_NM")        # abridores probables si el sitio los trae
        e_a = _equipo({"name": KBO_EQ[aw]}, pa if isinstance(pa, str) and pa else None)
        e_h = _equipo({"name": KBO_EQ[hm]}, ph if isinstance(ph, str) and ph else None)
        out.append({"id": "kbo-%s" % g.get("G_ID"), "liga": "kbo", "tipo": "equipos", "fecha_utc": fu,
                    "estado": "Programado", "home": e_h, "away": e_a, "cuotas": {}, "contexto": {},
                    "nota": None, "serie": None, "estadio": g.get("S_NM")})
    return out


def recolectar(ligas, dias, hoy=None, verbose=True):
    hoy = hoy or dt.date.today()
    d1, d2 = hoy.isoformat(), (hoy + dt.timedelta(days=dias)).isoformat()
    res = []
    for lg in ligas:
        n = 0
        try:
            if lg == "kbo":
                for i in range(dias + 1):
                    f = (hoy + dt.timedelta(days=i)).strftime("%Y%m%d")
                    js = juegos_kbo(f)
                    res += js; n += len(js)
            elif lg == "npb":
                js = juegos_npb(hoy, hoy + dt.timedelta(days=dias))
                res += js; n += len(js)
            elif lg in LIGAS_API:
                js = juegos_api(lg, d1, d2)
                res += js; n += len(js)
            else:
                continue
        except Exception as ex:
            if verbose:
                print("  %s: no se pudo leer el calendario (%s)" % (lg, str(ex)[:70]))
            continue
        if verbose:
            print("  %-6s %3d partidos por jugar" % (lg, n))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=3)
    ap.add_argument("--ligas", help="coma: npb,kbo,lmp,lvbp,lidom,abl")
    a = ap.parse_args()
    ligas = [x.strip().lower() for x in a.ligas.split(",")] if a.ligas else DEFAULT
    js = recolectar(ligas, a.dias)
    print(json.dumps(js[:2], ensure_ascii=False, indent=1)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
