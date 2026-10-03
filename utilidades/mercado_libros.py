# -*- coding: utf-8 -*-
"""
utilidades/mercado_libros.py - CASAS SHARP CONTRA CASAS DEL PUBLICO (señal de dinero, gratis).

Los % de boletos y de dinero (splits) son de pago (VSiN gratis solo enseña 1 partido por deporte). Esta es la
aproximacion gratuita con las fotos de The Odds API que ya se bajan:
  - SHARP:   Pinnacle, bolsas (Betfair, Matchbook) y LowVig. Mueven la linea cuando entra dinero profesional.
  - PUBLICO: DraftKings, FanDuel, BetMGM, Fanatics, Caesars, BetRivers, ESPN Bet, Bovada, MyBookie. Inflan el lado
             popular para equilibrar boletos.
Por partido y mercado (ganador, total, handicap) guarda la probabilidad sin vig de cada grupo en cada foto
(salida/mercado_libros.json, se limpia sola 1 dia despues del partido) y lee:
  - Movimiento sharp desde la apertura (pp) y movimiento del publico.
  - Brecha publico - sharp: las casas del publico pagan menos el lado que creen popular. Brecha positiva en un lado
    = el publico esta cargado ahi.
  - Senales: SHARP (Pinnacle se mueve >= 2 pp), SOLO PUBLICO (solo se mueven las recreativas),
    SHARP CONTRA PUBLICO (Pinnacle se mueve al lado contrario del que carga el publico: el equivalente al
    movimiento inverso).

    python utilidades\\mercado_libros.py --actualizar      (lee salida\\cuotas_casas.json y agrega la foto; idempotente)
    python utilidades\\mercado_libros.py --ver [--horas 36] [--liga mlb,nhl]   (lectura de los proximos partidos)
Escribe tambien salida/mercado_publico.json (la lectura) para la pagina y para Claude.
"""
import argparse, datetime as dt, json, os, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from nucleo import sharp, mercado  # noqa: E402

FOTO = os.path.join(BASE, "salida", "cuotas_casas.json")
ESTADO = os.path.join(BASE, "salida", "mercado_libros.json")
LECTURA = os.path.join(BASE, "salida", "mercado_publico.json")
G_SHARP = ("pinnacle", "pinnacle_eu", "betfair_ex_eu", "betfair_ex_uk", "matchbook", "lowvig")
G_PUBLICO = ("draftkings", "fanduel", "betmgm", "fanatics", "williamhill_us", "betrivers", "espnbet", "bovada",
             "mybookieag", "ballybet", "hardrockbet")
MAX_PUNTOS = 16           # fotos guardadas por mercado (la primera siempre se conserva: es la apertura)
UMBRAL_MOV = 2.0          # pp para llamar "movimiento"
UMBRAL_BRECHA = 1.5       # pp de brecha publico - sharp para decir que el publico carga un lado


def _utc(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _leer(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def _escribir(ruta, obj):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ruta)


def _linea_comun(cot, lado):
    pts = [d[lado][1] for d in cot.values() if lado in d and d[lado][1] is not None]
    return max(set(pts), key=pts.count) if pts else None


def _prob_grupo(cot, grupo, lados):
    """promedio de la prob. sin vig del primer lado entre las casas del grupo que cotizan todos los lados."""
    ps = []
    for casa in grupo:
        d = cot.get(casa)
        if not d or any(l not in d for l in lados) or (len(lados) == 2 and "draw" in d):
            continue                                  # 2 vias: fuera las casas que cotizan el empate (3 vias)
        try:
            p = mercado.sin_vig([mercado.prob_implicita(d[l][0]) for l in lados])
        except Exception:
            continue
        if p and p[0]:
            ps.append(p[0])
    return (round(100 * sum(ps) / len(ps), 2), len(ps)) if ps else (None, 0)


def _medir(ev):
    """{mercado: {linea, a, b, p_sharp, n_sharp, p_publico, n_publico}} de un evento (prob del lado a, en %)."""
    out = {}
    cot = sharp._lados(ev, "h2h")
    if cot:
        # 2 vias (beisbol, NHL con prorroga, tenis, NFL); si nadie cotiza a 2 vias (futbol), 3 vias
        ps, ns = _prob_grupo(cot, G_SHARP, ["home", "away"]); pp, npub = _prob_grupo(cot, G_PUBLICO, ["home", "away"])
        if ps is None and pp is None:
            ps, ns = _prob_grupo(cot, G_SHARP, ["home", "away", "draw"]); pp, npub = _prob_grupo(cot, G_PUBLICO, ["home", "away", "draw"])
        if ps is not None or pp is not None:
            out["ganador"] = {"linea": None, "a": "home", "b": "away", "p_sharp": ps, "n_sharp": ns, "p_publico": pp, "n_publico": npub}
    for mk, nombre, la, lb in (("totals", "total", "over", "under"), ("spreads", "handicap", "home", "away")):
        cot = sharp._lados(ev, mk)
        if not cot:
            continue
        pt = _linea_comun(cot, la)
        if pt is None:
            continue
        cot = sharp._lados(ev, mk, pt)
        ps, ns = _prob_grupo(cot, G_SHARP, [la, lb]); pp, npub = _prob_grupo(cot, G_PUBLICO, [la, lb])
        if ps is not None or pp is not None:
            out[nombre] = {"linea": pt, "a": la, "b": lb, "p_sharp": ps, "n_sharp": ns, "p_publico": pp, "n_publico": npub}
    return out


def actualizar():
    foto = _leer(FOTO, None)
    if not foto or not foto.get("eventos"):
        print("Sin foto de cuotas en %s" % FOTO); return 0
    ts = foto.get("generado") or ""
    est = _leer(ESTADO, {"eventos": {}})
    if est.get("ultima_foto") == ts:
        print("La foto %s ya estaba registrada." % ts); return 0
    ahora = _utc(ts) or dt.datetime.now(dt.timezone.utc)
    n = 0
    for ev in foto["eventos"]:
        eid = ev.get("id")
        if not eid:
            continue
        med = _medir(ev)
        if not med:
            continue
        e = est["eventos"].setdefault(eid, {"sport": ev.get("sport"), "liga": sharp.liga_de(ev.get("sport") or ""),
                                            "home": ev.get("home_team"), "away": ev.get("away_team"), "mercados": {}})
        e["inicio"] = ev.get("commence_time")
        ini = _utc(ev.get("commence_time"))
        if ini and ahora >= ini:
            continue                                  # ya empezo: la foto es en vivo, no cuenta
        for mk, m in med.items():
            serie = e["mercados"].setdefault(mk, [])
            serie.append([ts, m["linea"], m["p_sharp"], m["p_publico"], m["n_sharp"], m["n_publico"]])
            if len(serie) > MAX_PUNTOS:
                del serie[1:len(serie) - MAX_PUNTOS + 1]  # conserva la apertura y las ultimas fotos
            n += 1
    # limpieza: fuera los partidos que empezaron hace mas de 1 dia
    lim = ahora - dt.timedelta(days=1)
    for eid in [k for k, v in est["eventos"].items() if (_utc(v.get("inicio")) or ahora) < lim]:
        del est["eventos"][eid]
    est["ultima_foto"] = ts
    _escribir(ESTADO, est)
    print("Foto %s: %d mercados registrados; %d partidos en seguimiento." % (ts, n, len(est["eventos"])))
    return 0


def _etiqueta(e, mk, lado, linea):
    if mk == "total":
        return ("Over" if lado == "over" else "Under") + (" %s" % linea if linea is not None else "")
    nom = e["home"] if lado == "home" else e["away"]
    if mk == "handicap" and linea is not None:
        ln = float(linea) if lado == "home" else -float(linea)
        return "%s %+g" % (nom, ln)
    return nom


def leer_mercado(e, mk, serie):
    """dict con aperturas, actuales, movimientos, brecha y senales (en pp, para el lado a)."""
    a, b = ("over", "under") if mk == "total" else ("home", "away")
    ac = serie[-1]
    misma = [x for x in serie if x[1] == ac[1]]       # las probabilidades solo se comparan sobre la MISMA linea
    ap = misma[0]
    ps0 = next((x[2] for x in misma if x[2] is not None), None)   # primera foto con Pinnacle en esta linea
    pp0, ps1, pp1 = ap[3], ac[2], ac[3]
    mov_s = round(ps1 - ps0, 2) if ps0 is not None and ps1 is not None else None
    mov_p = round(pp1 - pp0, 2) if pp0 is not None and pp1 is not None else None
    brecha = round(pp1 - ps1, 2) if pp1 is not None and ps1 is not None else None
    lado_mov = (a if mov_s > 0 else b) if mov_s else None
    lado_pub = (a if brecha > 0 else b) if brecha else None
    senales = []
    if mov_s is not None and abs(mov_s) >= UMBRAL_MOV:
        senales.append("SHARP hacia %s (%+.1f pp)" % (_etiqueta(e, mk, lado_mov, ac[1]), abs(mov_s)))
    if mov_p is not None and abs(mov_p) >= UMBRAL_MOV and mov_s is not None and abs(mov_s) < 1.0:
        senales.append("SOLO PUBLICO hacia %s (%+.1f pp; Pinnacle quieto)" % (_etiqueta(e, mk, a if mov_p > 0 else b, ac[1]), abs(mov_p)))
    elif mov_p is not None and abs(mov_p) >= UMBRAL_MOV and mov_s is None:
        senales.append("publico se movio hacia %s (%+.1f pp; sin Pinnacle para comparar)" % (_etiqueta(e, mk, a if mov_p > 0 else b, ac[1]), abs(mov_p)))
    if brecha is not None and abs(brecha) >= UMBRAL_BRECHA:
        senales.append("PUBLICO cargado en %s (brecha %.1f pp)" % (_etiqueta(e, mk, lado_pub, ac[1]), abs(brecha)))
        if mov_s is not None and abs(mov_s) >= 1.0 and lado_mov != lado_pub:
            senales.append("SHARP CONTRA PUBLICO: valor del lado %s" % _etiqueta(e, mk, lado_mov, ac[1]))
    l0 = serie[0][1]
    if l0 is not None and ac[1] is not None and float(l0) != float(ac[1]):
        sube = float(ac[1]) > float(l0)
        hacia = ("Over" if sube else "Under") if mk == "total" else (e["away"] if sube else e["home"])
        senales.append("LINEA %s -> %s: se movio hacia %s" % (l0, ac[1], hacia))
    return {"mercado": mk, "lado_a": _etiqueta(e, mk, a, ac[1]), "linea_apertura": l0, "linea": ac[1],
            "p_sharp_apertura": ps0, "p_sharp": ps1, "p_publico_apertura": pp0, "p_publico": pp1,
            "mov_sharp_pp": mov_s, "mov_publico_pp": mov_p, "brecha_pp": brecha, "fotos": len(serie),
            "desde": ap[0], "hasta": ac[0], "senales": senales}


def ver(horas=36, ligas=None, imprimir=True):
    est = _leer(ESTADO, {"eventos": {}})
    ahora = dt.datetime.now(dt.timezone.utc)
    filas = []
    for eid, e in est.get("eventos", {}).items():
        ini = _utc(e.get("inicio"))
        if not ini or ini < ahora - dt.timedelta(hours=4) or ini > ahora + dt.timedelta(hours=horas):
            continue
        if ligas and (e.get("liga") or "") not in ligas:
            continue
        ms = [leer_mercado(e, mk, s) for mk, s in e["mercados"].items() if s]
        filas.append({"id": eid, "liga": e.get("liga"), "inicio_utc": e.get("inicio"),
                      "inicio_cdmx": (ini - dt.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"),
                      "partido": "%s @ %s" % (e["away"], e["home"]), "mercados": ms})
    filas.sort(key=lambda f: (f["liga"] or "", f["inicio_utc"]))
    salida = {"generado": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"), "ultima_foto": est.get("ultima_foto"),
              "grupos": {"sharp": G_SHARP, "publico": G_PUBLICO}, "partidos": filas}
    _escribir(LECTURA, salida)
    if imprimir:
        print("Lectura sharp vs publico | ultima foto %s | %d partidos en %d h" % (est.get("ultima_foto"), len(filas), horas))
        for f in filas:
            print("\n[%s] %s  (%s CDMX)" % ((f["liga"] or "").upper(), f["partido"], f["inicio_cdmx"]))
            for m in f["mercados"]:
                fmt = lambda x: "-" if x is None else "%.1f" % x
                print("  %-9s %-28s sharp %s -> %s | publico %s -> %s | brecha %s | %d fotos" % (
                    m["mercado"], m["lado_a"], fmt(m["p_sharp_apertura"]), fmt(m["p_sharp"]),
                    fmt(m["p_publico_apertura"]), fmt(m["p_publico"]), fmt(m["brecha_pp"]), m["fotos"]))
                for s in m["senales"]:
                    print("            * " + s)
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--actualizar", action="store_true")
    ap.add_argument("--ver", action="store_true")
    ap.add_argument("--horas", type=float, default=36)
    ap.add_argument("--liga", help="ligas separadas por coma (mlb,nhl,npb,kbo,nfl,ncaafb...)")
    a = ap.parse_args()
    if not a.actualizar and not a.ver:
        a.actualizar = a.ver = True
    if a.actualizar:
        actualizar()
    if a.ver:
        ver(a.horas, set(a.liga.split(",")) if a.liga else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
