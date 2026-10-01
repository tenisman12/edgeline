# -*- coding: utf-8 -*-
"""
colectores/proximos_beisbol.py - PARTIDOS POR JUGAR de NPB, KBO, LMP, LVBP, LIDOM y ABL.

ESPN no publica estas ligas. Calendario:
  NPB, LMP, LVBP, LIDOM, ABL  ->  MLB Stats API  /schedule (con abridor probable cuando lo hay)
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
LIGAS_API = {"npb": (31, None), "lmp": (17, 132), "lvbp": (17, 135), "lidom": (17, 131), "abl": (17, 595)}
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
