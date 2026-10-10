# -*- coding: utf-8 -*-
"""
colectores/proximos_hockey.py - PARTIDOS POR JUGAR de SHL, Liiga, AHL y DEL.

ESPN no publica estas ligas. El calendario sale de las mismas fuentes oficiales que la historia
(colectores/recolectar_hockey_ligas.py), asi que los nombres de equipo son identicos a los de datos/hockey.csv:
  SHL    stats.swehockey.se   calendario de la temporada (fecha y hora de Suecia)
  Liiga  liiga.fi/api/v2      juegos de la temporada (hora UTC)
  AHL    HockeyTech           calendario de la temporada (hora con zona)
  DEL    penny-del.org        /spiele/team: ligas a cada partido; de la pagina del partido salen nombres y hora

Devuelve los juegos con el MISMO esquema que colectores/recolectar_proximos.py y proximos_beisbol.py (id, liga, tipo,
fecha_utc, estado, home/away, cuotas, contexto), para que plataforma.py los trate igual que los de ESPN. Las cuotas
salen de The Odds API (salida/cuotas_casas.json) como en NPB y KBO; la DEL no esta en The Odds API.

Uso suelto (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python colectores\\proximos_hockey.py --dias 3
    python colectores\\proximos_hockey.py --dias 2 --ligas shl,del

Solo stdlib.
"""
import argparse, datetime as dt, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recolectar_hockey_ligas as RH  # noqa: E402

DEFAULT = ["shl", "liiga", "ahl", "del"]
NOMBRE = {"shl": "SHL", "liiga": "Liiga", "ahl": "AHL", "del": "DEL"}


# ------------------------------------------------------------------ hora local de Europa -> UTC (sin tzdata)
def _ultimo_domingo(anio, mes):
    d = dt.date(anio, mes + 1, 1) - dt.timedelta(days=1) if mes < 12 else dt.date(anio, 12, 31)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def europa_a_utc(fecha, hora, base_utc=1):
    """hora local de Europa central (Suecia, Alemania: base_utc 1) o del este (Finlandia: 2) -> datetime UTC.
    Horario de verano de la UE: del ultimo domingo de marzo al ultimo domingo de octubre."""
    f = dt.date.fromisoformat(fecha)
    h, m = [int(x) for x in hora.split(":")[:2]]
    verano = _ultimo_domingo(f.year, 3) <= f < _ultimo_domingo(f.year, 10)
    return dt.datetime(f.year, f.month, f.day, h, m) - dt.timedelta(hours=base_utc + (1 if verano else 0))


def _equipo(nombre):
    return {"nombre": nombre, "corto": nombre, "abrev": None, "loc": None, "logo": None, "record": None,
            "probable": None, "probable_rol": None, "ranking": None}


def _juego(liga, gid, fu, home, away, estadio=None):
    return {"id": "%s-%s" % (liga, gid), "liga": liga, "tipo": "equipos", "fecha_utc": fu, "estado": "Programado",
            "home": _equipo(home), "away": _equipo(away), "cuotas": {}, "contexto": {}, "nota": None,
            "serie": None, "estadio": estadio}


def _en_ventana(fu, desde, hasta):
    return fu is not None and desde.isoformat() <= fu[:10] <= hasta.isoformat()


# ------------------------------------------------------------------ por liga
def liiga(desde, hasta):
    temp = desde.year + 1 if desde.month >= 7 else desde.year
    out = []
    for g in RH.get_json("https://liiga.fi/api/v2/games?tournament=runkosarja&season=%d" % temp):
        if g.get("ended") or g.get("started"):
            continue
        h, a = g.get("homeTeam") or {}, g.get("awayTeam") or {}
        fu = (g.get("start") or "")[:16]
        fu = fu + "Z" if fu else None
        if not (h.get("teamName") and a.get("teamName")) or not _en_ventana(fu, desde, hasta):
            continue
        out.append(_juego("liiga", "%d-%s" % (temp, g.get("id")), fu, h["teamName"], a["teamName"],
                          (g.get("iceRink") or {}).get("name")))
    return out


def ahl(desde, hasta):
    temps = RH.ahl_temporadas(0)
    if not temps:
        return []
    d = RH.get_json(RH.HT + "feed=modulekit&view=schedule&season_id=%s" % temps[0][1])
    out = []
    for g in (d.get("SiteKit") or {}).get("Schedule") or []:
        if str(g.get("final")) == "1" or str(g.get("started")) == "1":
            continue
        iso = g.get("GameDateISO8601") or ""
        try:
            t = dt.datetime.fromisoformat(iso)
            fu = (t - t.utcoffset()).strftime("%Y-%m-%dT%H:%MZ") if t.utcoffset() is not None else None
        except ValueError:
            fu = None
        if not fu:
            fu = "%sT23:00Z" % (g.get("date_played") or "")[:10]
        if not _en_ventana(fu, desde, hasta):
            continue
        out.append(_juego("ahl", g.get("game_id") or g.get("id"), fu, RH.nombre_ahl(g, "home"), RH.nombre_ahl(g, "visiting"),
                          g.get("venue_name")))
    return out


def shl(desde, hasta):
    h = RH.get_txt("https://stats.swehockey.se/ScheduleAndResults/Schedule/%s" % RH.SHL_ACTUAL)
    out = []
    fecha = ""
    for fila in re.split(r"<tr[\s>]", h)[1:]:
        mf = re.search(r"(\d{4}-\d{2}-\d{2})", fila)
        if mf:
            fecha = mf.group(1)
        if "/Game/Events/" in fila or not fecha:
            continue                                         # con liga a los eventos = ya se jugo (o se esta jugando)
        celdas = [RH.limpio(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
        hora = next((m.group(1) for c in celdas for m in [re.search(r"\b(\d{1,2}:\d{2})\b", c)] if m), None)
        equipos = next((c for c in celdas if " - " in c and re.search(r"[A-Za-zÅÄÖåäö]{3}", c)
                        and not re.search(r"\d{2}:\d{2}", c) and not re.fullmatch(r"\d+\s*-\s*\d+", c)), None)
        if not equipos or not hora:
            continue
        eh, ea = [x.strip() for x in equipos.split(" - ", 1)]
        fu = europa_a_utc(fecha, hora, 1).strftime("%Y-%m-%dT%H:%MZ")
        if not _en_ventana(fu, desde, hasta):
            continue
        estadio = celdas[-1] if celdas and celdas[-1] not in (equipos,) and not re.search(r"\d", celdas[-1]) else None
        out.append(_juego("shl", "%s-%s-%s" % (fecha, eh, ea), fu, eh, ea, estadio))
    return out


def del_(desde, hasta):
    links = set()
    for url in ("/spiele/team", "/spiele"):
        try:
            links |= set(re.findall(r"/statistik/spieldetails/[\w\-]+_\d+", RH.get_txt(RH.DEL_WEB + url)))
        except Exception:
            pass
        if links:
            break
    out = []
    for l in sorted(links):
        m = re.search(r"/(\d{2})(\d{2})(\d{4})_[\w\-]+_(\d+)$", l)
        if not m:
            continue
        fecha = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
        if not (desde.isoformat() <= fecha <= hasta.isoformat()):
            continue
        try:
            pag = RH.get_txt(RH.DEL_WEB + l)
        except Exception:
            continue
        if RH.del_leer_juego(pag, int(m.group(4))):
            continue                                         # ya tiene marcador final
        t = re.search(r"<title>(.*?)</title>", pag, re.S)
        t = RH.limpio(t.group(1)) if t else ""
        mt = re.search(r"- ([^-]+?) gg\. (.+?) am \d{2}\.\d{2}\.\d{4}", t)
        if not mt:
            continue
        hora = re.search(r"\b(\d{1,2}:\d{2})\s*Uhr", RH.limpio(pag))
        fu = europa_a_utc(fecha, hora.group(1) if hora else "19:30", 1).strftime("%Y-%m-%dT%H:%MZ")
        out.append(_juego("del", m.group(4), fu, mt.group(1).strip(), mt.group(2).strip()))
    return out


LECTOR = {"liiga": liiga, "ahl": ahl, "shl": shl, "del": del_}


def recolectar(ligas, dias, hoy=None, verbose=True):
    hoy = hoy or dt.date.today()
    desde, hasta = hoy - dt.timedelta(days=1), hoy + dt.timedelta(days=dias)
    res = []
    for lg in ligas:
        if lg not in LECTOR:
            continue
        try:
            js = LECTOR[lg](desde, hasta)
        except Exception as ex:
            if verbose:
                print("  %s: no se pudo leer el calendario (%s)" % (lg, str(ex)[:70]))
            continue
        res += js
        if verbose:
            print("  %-6s %3d partidos por jugar" % (lg, len(js)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=3)
    ap.add_argument("--ligas", help="coma: shl,liiga,ahl,del")
    a = ap.parse_args()
    ligas = [x.strip().lower() for x in a.ligas.split(",")] if a.ligas else DEFAULT
    js = recolectar(ligas, a.dias)
    for g in js[:12]:
        print("  %-6s %s  %s @ %s" % (g["liga"], g["fecha_utc"], g["away"]["nombre"], g["home"]["nombre"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
