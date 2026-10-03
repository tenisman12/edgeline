# -*- coding: utf-8 -*-
"""
nucleo/jugadores.py - JUGADORES CLAVE POR EQUIPO (forma reciente), igual esquema para todos los deportes.

No cambia ninguna probabilidad: es el insumo del "indicador de influencia, no aplicado" y de la
pantalla del partido. Lee datos/jugadores/*.csv (historial completo, en tu PC) y, si no existe,
datos/jugadores_recientes/*.csv (ultimos ~60 dias, viaja a GitHub y es lo que usa Actions).

Salida de clave(...): siempre un dict {"disponible": bool, "motivo": str, "fuente": archivo,
"ultimo_juego": fecha, ...bloques por deporte}.

  beisbol   probable (ultimas 5 salidas), rotacion, bullpen (carga ultimos 3 dias), bateadores
  hockey    porteros (abridor reciente, sv%), patinadores (puntos ultimos 10)
  nfl       QB, RB, WR/TE (ultimos 4 juegos)
  espn      NBA, NCAA, futbol: jugadores con mas minutos/titularidades (promedios ultimos 5)

Solo stdlib.
"""
import csv as _csv, sys as _sys
_csv.field_size_limit(min(2 ** 31 - 1, _sys.maxsize))
import os, datetime as dt

try:
    from nucleo import io, forma
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io, forma

_NO_NUM = {"game_id", "player_id", "season", "is_home", "game_date", "titular", "abridor", "orden_bate",
           "orden_salida", "dorsal", "tipo", "week"}


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _ruta(nombre):
    for carpeta in ("jugadores", "jugadores_recientes"):
        p = os.path.join(io.BASE, "datos", carpeta, nombre)
        if os.path.exists(p):
            return p
    return None


def _filas(nombre):
    p = _ruta(nombre)
    return (forma._leer(p), p) if p else ([], None)


def _fecha_max(rows):
    return max((r.get("game_date") or "")[:10] for r in rows) if rows else ""


def _sum(rows, k):
    return sum(_f(r.get(k)) or 0.0 for r in rows)


def _ultimos_juegos(rows, n):
    """filas de los ultimos n dias-juego distintos del equipo."""
    fechas = sorted({(r.get("game_date") or "")[:10] for r in rows if r.get("game_date")})
    corte = set(fechas[-n:])
    return [r for r in rows if (r.get("game_date") or "")[:10] in corte]


def _por_jugador(rows):
    d = {}
    for r in rows:
        d.setdefault(r.get("player_id") or r.get("jugador"), []).append(r)
    return d


def _nombre_igual(a, b):
    a, b = io.norm(a), io.norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    pa, pb = a.split(), b.split()
    return pa[-1] == pb[-1] and pa[0][:1] == pb[0][:1]


def _no_disp(motivo, fuente=None):
    return {"disponible": False, "motivo": motivo, "fuente": fuente}


# ================================================================== beisbol
def _ip(outs):
    return "%d.%d" % (int(outs // 3), int(outs % 3))


def _linea_lanzador(rows):
    outs = _sum(rows, "outs")
    er, k, bb, h, hr = (_sum(rows, c) for c in ("er", "k", "bb", "h", "hr"))
    ip = outs / 3.0
    return {"juegos": len(rows), "ip": _ip(outs), "era": round(9 * er / ip, 2) if ip else None,
            "whip": round((h + bb) / ip, 2) if ip else None, "k9": round(9 * k / ip, 2) if ip else None,
            "bb9": round(9 * bb / ip, 2) if ip else None, "hr9": round(9 * hr / ip, 2) if ip else None,
            "pitches_por_juego": round(_sum(rows, "pitches") / len(rows), 1) if rows else None}


def beisbol(liga, team, probable=None):
    lan, pl = _filas("mlb_lanzadores.csv")
    bat, pb = _filas("mlb_bateadores.csv")
    etiqueta = liga.upper()
    lan = [r for r in lan if (r.get("liga") or "").upper() == etiqueta]
    bat = [r for r in bat if (r.get("liga") or "").upper() == etiqueta]
    if not lan and not bat:
        return _no_disp("sin datos de jugadores de %s en tus archivos" % etiqueta, pl or pb)
    tl = [r for r in lan if r.get("team") == team]
    tb = [r for r in bat if r.get("team") == team]
    if not tl and not tb:
        return _no_disp("el equipo no aparece en los archivos de jugadores", pl or pb)
    ult = max(_fecha_max(tl), _fecha_max(tb))
    out = {"disponible": True, "fuente": os.path.basename(pl or pb), "ultimo_juego": ult}

    # probable
    if probable:
        # NPB: el probable viene de npb.jp solo con el apellido en japones (村上); se compara con jugador_jp
        pr_ = probable.strip().replace(" ", "")
        mios = [r for r in lan if _nombre_igual(r.get("jugador"), probable) or (pr_ and (r.get("jugador") or "").replace(" ", "") == pr_)
                or (r.get("jugador_jp") and probable.strip() and (r["jugador_jp"].replace(" ", "").startswith(probable.strip().replace(" ", ""))
                                                                  or probable.strip().replace(" ", "") in r["jugador_jp"].replace(" ", "")))]
        mios.sort(key=lambda r: (r.get("game_date") or "", str(r.get("game_id"))))
        salidas = [r for r in mios if str(r.get("abridor")) in ("1", "1.0")][-5:]
        if salidas:
            out["probable"] = {"jugador": probable, "equipo_ultimo": salidas[-1].get("team"),
                               "resumen_ultimas5": _linea_lanzador(salidas),
                               "salidas": [{"fecha": r["game_date"][:10], "rival": r.get("opp"), "ip": r.get("ip"),
                                            "h": _f(r.get("h")), "er": _f(r.get("er")), "bb": _f(r.get("bb")),
                                            "k": _f(r.get("k")), "hr": _f(r.get("hr")), "pitches": _f(r.get("pitches"))}
                                           for r in reversed(salidas)]}
        else:
            out["probable"] = {"jugador": probable, "resumen_ultimas5": None,
                               "nota": "sin salidas como abridor en tus archivos"}
    # rotacion (ultimos 35 dias del equipo)
    if tl and ult:
        lim = (dt.date.fromisoformat(ult) - dt.timedelta(days=35)).isoformat()
        ab = [r for r in tl if str(r.get("abridor")) in ("1", "1.0") and (r.get("game_date") or "")[:10] >= lim]
        rot = []
        for pid, rs in _por_jugador(ab).items():
            rs.sort(key=lambda r: r["game_date"])
            ult_s = rs[-1]["game_date"][:10]
            d = _linea_lanzador(rs)
            d.update({"jugador": rs[-1].get("jugador"), "salidas": len(rs), "ultima_salida": ult_s,
                      "descanso": (dt.date.fromisoformat(ult) - dt.date.fromisoformat(ult_s)).days})
            rot.append(d)
        rot.sort(key=lambda d: -d["salidas"])
        out["rotacion"] = rot[:6]
        # bullpen: carga de los ultimos 3 dias de juego del equipo
        rel = [r for r in tl if str(r.get("abridor")) not in ("1", "1.0")]
        fechas = sorted({(r.get("game_date") or "")[:10] for r in tl})[-3:]
        rel3 = [r for r in rel if (r.get("game_date") or "")[:10] in fechas]
        carga = []
        for pid, rs in _por_jugador(rel3).items():
            carga.append({"jugador": rs[-1].get("jugador"), "apariciones": len(rs),
                          "pitches": _sum(rs, "pitches"), "ip": _ip(_sum(rs, "outs")),
                          "ultima": max(r["game_date"][:10] for r in rs)})
        carga.sort(key=lambda d: -d["pitches"])
        out["bullpen"] = {"ventana": fechas, "pitches_total": sum(d["pitches"] for d in carga),
                          "relevistas_usados": len(carga), "mas_usados": carga[:6]}
    # bateadores (ultimos 14 dias-juego)
    if tb:
        rec = _ultimos_juegos(tb, 14)
        bs = []
        for pid, rs in _por_jugador(rec).items():
            ab, h, bb, hbp, sf, pa = (_sum(rs, c) for c in ("ab", "h", "bb", "hbp", "sf", "pa"))
            # bases totales: la columna tb si viene; si no (NPB del repositorio), H + 2B + 2x3B + 3xHR
            tbases = sum(_sum([r], "tb") if str(r.get("tb") or "").strip() not in ("", "nan")
                         else _sum([r], "h") + _sum([r], "d2") + 2 * _sum([r], "d3") + 3 * _sum([r], "hr") for r in rs)
            den = ab + bb + hbp + sf
            bs.append({"jugador": rs[-1].get("jugador"), "pos": rs[-1].get("posicion"), "juegos": len(rs),
                       "pa": pa, "avg": round(h / ab, 3) if ab else None,
                       "obp": round((h + bb + hbp) / den, 3) if den else None,
                       "slg": round(tbases / ab, 3) if ab else None,
                       "hr": _sum(rs, "hr"), "rbi": _sum(rs, "rbi"), "bb": bb, "k": _sum(rs, "k"),
                       "titular_pct": round(sum(1 for r in rs if str(r.get("titular")) in ("1", "1.0")) / len(rs), 2)})
        bs.sort(key=lambda d: -d["pa"])
        out["bateadores"] = {"ventana_juegos": 14, "jugadores": bs[:9]}
    return out


# ================================================================== hockey
def hockey(team):
    por, pp = _filas("nhl_porteros.csv")
    pat, pq = _filas("nhl_patinadores.csv")
    if not por and not pat:
        return _no_disp("sin datos de jugadores de NHL en tus archivos")
    tp = [r for r in por if r.get("team") == team and (r.get("tipo") or "REG") != "PRE"]
    ts = [r for r in pat if r.get("team") == team and (r.get("tipo") or "REG") != "PRE"]
    if not tp and not ts:
        return _no_disp("el equipo no aparece en los archivos de jugadores", pp or pq)
    out = {"disponible": True, "fuente": os.path.basename(pp or pq), "ultimo_juego": max(_fecha_max(tp), _fecha_max(ts))}
    rp = _ultimos_juegos(tp, 10)
    ps = []
    for pid, rs in _por_jugador(rp).items():
        rs.sort(key=lambda r: r["game_date"])
        sa, sv = _sum(rs, "tiros_contra"), _sum(rs, "paradas")
        ini = [r for r in rs if str(r.get("abridor")) in ("1", "1.0")]
        ps.append({"jugador": rs[-1].get("jugador"), "apariciones": len(rs), "aperturas": len(ini),
                   "sv_pct": round(sv / sa, 3) if sa else None, "gc_por_juego": round(_sum(rs, "goles_contra") / len(rs), 2),
                   "tiros_contra_por_juego": round(sa / len(rs), 1),
                   "ultima_apertura": max((r["game_date"][:10] for r in ini), default=None),
                   "ultimo_juego": rs[-1]["game_date"][:10]})
    ps.sort(key=lambda d: (-d["aperturas"], -d["apariciones"]))
    out["porteros"] = {"ventana_juegos": 10, "jugadores": ps[:3],
                       "abridor_ultimo_juego": next((d["jugador"] for d in ps if d["ultima_apertura"] == max(
                           (x["ultima_apertura"] or "") for x in ps)), None) if ps else None}
    rs_ = _ultimos_juegos(ts, 10)
    sk = []
    for pid, rs in _por_jugador(rs_).items():
        n = len(rs)
        sk.append({"jugador": rs[-1].get("jugador"), "pos": rs[-1].get("posicion"), "juegos": n,
                   "g": _sum(rs, "goles"), "a": _sum(rs, "asist"), "p": _sum(rs, "puntos"),
                   "mas_menos": _sum(rs, "mas_menos"), "tiros": _sum(rs, "tiros"), "hits": _sum(rs, "hits"),
                   "toi_prom": round(_sum(rs, "toi_min") / n, 1)})
    sk.sort(key=lambda d: (-d["p"], -d["g"]))
    out["patinadores"] = {"ventana_juegos": 10, "jugadores": sk[:6]}
    return out


# ================================================================== nfl
def _col(r, *cands):
    for c in cands:
        v = _f(r.get(c))
        if v is not None:
            return v
    return 0.0


def nfl(team):
    rows, p = _filas("nfl_jugadores.csv")
    if not rows:
        return _no_disp("sin datos de jugadores de NFL en tus archivos")
    tr = [r for r in rows if r.get("team") == team]
    if not tr:
        return _no_disp("el equipo no aparece en los archivos de jugadores", p)
    # ultimos 4 juegos del equipo
    ids = sorted({(r.get("game_date") or "", r.get("game_id")) for r in tr})[-4:]
    g4 = {i[1] for i in ids}
    rec = [r for r in tr if r.get("game_id") in g4]
    out = {"disponible": True, "fuente": os.path.basename(p), "ultimo_juego": (ids[-1][0] or "")[:10],
           "ventana_juegos": len(ids)}

    def agrupa(pos, orden, campos, top):
        res = []
        for pid, rs in _por_jugador([r for r in rec if (r.get("posicion") or "") in pos]).items():
            n = len(rs)
            d = {"jugador": rs[-1].get("jugador"), "pos": rs[-1].get("posicion"), "juegos": n}
            for nombre, cands in campos:
                d[nombre] = round(sum(_col(r, *cands) for r in rs) / n, 1)
            d["_o"] = sum(_col(r, *orden) for r in rs)
            res.append(d)
        res.sort(key=lambda d: -d["_o"])
        for d in res:
            d.pop("_o")
        return res[:top]
    out["qb"] = agrupa(("QB",), ("attempts",), [("att", ("attempts",)), ("cmp", ("completions",)),
                       ("yds", ("passing_yards",)), ("td", ("passing_tds",)),
                       ("int", ("passing_interceptions", "interceptions")), ("sacks", ("sacks_suffered", "sacks")),
                       ("yds_carrera", ("rushing_yards",))], 1)
    out["rb"] = agrupa(("RB", "FB"), ("carries",), [("car", ("carries",)), ("yds", ("rushing_yards",)),
                       ("td", ("rushing_tds",)), ("rec", ("receptions",)), ("yds_rec", ("receiving_yards",))], 2)
    out["receptores"] = agrupa(("WR", "TE"), ("targets",), [("tgt", ("targets",)), ("rec", ("receptions",)),
                               ("yds", ("receiving_yards",)), ("td", ("receiving_tds",))], 5)
    return out


# ================================================================== ESPN (NBA, NCAA, futbol...)
_MIN = ("minutes", "MIN", "min", "minutosJugados", "timeOnIce", "appearances")


def espn(liga, team):
    rows, p = _filas("espn_%s_jugadores.csv" % liga)
    if not rows:
        return _no_disp("sin datos de jugadores de %s en tus archivos" % liga)
    tr = [r for r in rows if r.get("team") == team]
    if not tr:
        return _no_disp("el equipo no aparece en los archivos de jugadores", p)
    ids = sorted({(r.get("game_date") or "", r.get("game_id")) for r in tr})[-5:]
    g5 = {i[1] for i in ids}
    rec = [r for r in tr if r.get("game_id") in g5]
    cols = []
    for c in rec[0].keys():
        if c in _NO_NUM or c is None:
            continue
        vs = [_f(r.get(c)) for r in rec]
        if sum(1 for v in vs if v is not None) >= 0.3 * len(rec):
            cols.append(c)
    mincol = next((c for c in _MIN if c in rec[0]), None)
    js = []
    for pid, rs in _por_jugador(rec).items():
        n = len(rs)
        peso = sum((_f(r.get(mincol)) or 0.0) for r in rs) / n if mincol else 0.0
        js.append({"jugador": rs[-1].get("jugador"), "pos": rs[-1].get("posicion"), "juegos": n,
                   "titular": sum(1 for r in rs if str(r.get("titular")) in ("1", "1.0")),
                   "stats": {c: round(sum(_f(r.get(c)) or 0.0 for r in rs) / n, 2) for c in cols},
                   "_p": (peso, sum(1 for r in rs if str(r.get("titular")) in ("1", "1.0")), n)})
    js.sort(key=lambda d: d["_p"], reverse=True)
    for d in js:
        d.pop("_p")
    return {"disponible": True, "fuente": os.path.basename(p), "ultimo_juego": (ids[-1][0] or "")[:10],
            "ventana_juegos": len(ids), "criterio": mincol or "titularidades", "jugadores": js[:9]}


# ================================================================== nombres de equipo en los archivos de ESPN
_EMP = {}


def resolver_espn(liga, variantes, abrev=None):
    """Nombre del equipo tal como aparece en espn_<liga>_jugadores.csv (o None)."""
    k = "espn_%s_jugadores.csv" % liga
    if k not in _EMP:
        rows, _ = _filas(k)
        nombres = sorted({r.get("team") for r in rows if r.get("team")})
        try:
            from nucleo import equipos
            _EMP[k] = equipos.Emparejador(nombres) if nombres else None
        except Exception:
            _EMP[k] = None
    emp = _EMP[k]
    return emp.buscar(variantes, abrev)[0] if emp else None


# ================================================================== despacho
def clave(deporte, liga, team, probable=None):
    """team = nombre como aparece en el archivo de jugadores de ese deporte/liga."""
    try:
        if deporte == "beisbol":
            return beisbol(liga, team, probable)
        if liga == "nhl":
            return hockey(team)
        if liga == "nfl":
            return nfl(team)
        return espn(liga, team)
    except Exception as ex:                      # un archivo raro no tumba la pagina
        return _no_disp("error al leer jugadores (%s)" % str(ex)[:80])
