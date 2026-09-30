# -*- coding: utf-8 -*-
"""
PANEL DE JUGADOR - ficha profunda de un jugador desde la data de ESPN.

Lee data_maestra/espn_<liga>_players.csv (de extraer_espn.py) y muestra, de cualquier
jugador: su registro juego por juego, promedios y forma reciente. Se adapta a cada
deporte: en NFL las stats vienen por categoria (passing_YDS, rushing_YDS...), asi que
un QB muestra pase+acarreo y no se mezcla con pateadores.

Uso (en C:\\Edgeline):
    python panel_jugador.py --liga nfl --jugador "Hurts"
    python panel_jugador.py --liga nba --jugador "Haliburton"
    python panel_jugador.py --liga nfl --top passing_YDS
    python panel_jugador.py --liga nfl --cols          (lista las stats disponibles)
"""
import argparse, csv, io, os

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")


def cargar(liga):
    p = os.path.join(BASE, "data_maestra", "espn_%s_players.csv" % liga)
    if not os.path.exists(p):
        print("No existe %s. Corre extraer_espn.py --liga %s primero." % (p, liga)); return None
    return list(csv.DictReader(io.open(p, encoding="utf-8-sig")))


def _num(x):
    try:
        if isinstance(x, str) and "/" in x:      # "16/25" -> 16
            return float(x.split("/")[0])
        if isinstance(x, str) and "-" in x and x.replace("-", "").replace(".", "").isdigit():
            return float(x.split("-")[0])
        return float(x)
    except (TypeError, ValueError):
        return None


def stat_cols(rows):
    return [c for c in rows[0].keys() if c.startswith("e_")]


def panel(liga, nombre):
    rows = cargar(liga)
    if not rows: return
    n = nombre.lower().strip()
    # agrupa por jugador exacto; "Allen" puede coincidir con varios
    matches = {}
    for r in rows:
        nm = (r.get("jugador") or "")
        if n in nm.lower() and r.get("jugo") == "1":
            matches.setdefault(nm, []).append(r)
    if not matches:
        print("No encontre '%s' en %s." % (nombre, liga)); return
    exacto = next((nm for nm in matches if nm.lower() == n), None)
    if exacto:
        jug = exacto
    elif len(matches) == 1:
        jug = list(matches)[0]
    else:
        print("\nVarios jugadores coinciden con '%s' (usa el nombre completo):" % nombre)
        for nm in sorted(matches, key=lambda k: -len(matches[k]))[:10]:
            print("   %-26s %-5s %d juegos" % (nm, matches[nm][0].get("team"), len(matches[nm])))
        return
    suyos = matches[jug]; team = suyos[0].get("team")
    suyos.sort(key=lambda r: r.get("game_date", ""))
    # columnas donde ESTE jugador tiene datos
    cols = stat_cols(rows)
    con_dato = [c for c in cols if any((r.get(c) or "") not in ("", None) for r in suyos)]
    # ranking de importancia por LABEL (menor = mas importante). El extractor saca TODAS;
    # esto solo elige cuales mostrar, priorizando las de peso y repartiendo por categoria.
    RANK = {"YDS":1,"PTS":1,"G":1,"H":1,"GOALS":1,"SAVES":1,
            "TD":2,"HR":2,"REB":2,"K":2,"SO":2,"SV":2,"SOG":2,"SHOTS":2,
            "REC":3,"CAR":3,"AST":3,"A":3,"RBI":3,"R":3,"INT":3,
            "STL":4,"BLK":4,"BB":4,"TFL":4,
            "AVG":6,"OBP":6,"ERA":6,"RTG":6,"QBR":6,"FG":6,"3PT":6,
            "MIN":8,"TOI":8,"IP":5,"AB":7}
    def _lab(c): return c[2:].split("_")[-1]
    def _short(c):
        p = c[2:].split("_"); return (p[0][:4] + "_" + p[-1]) if len(p) >= 2 else c[2:]
    con_dato.sort(key=lambda c: (RANK.get(_lab(c), 20), c))
    muestra = con_dato[:7]
    print("\n" + "=" * 74)
    print("  %s  (%s, %s)   -   %d juego(s)" % (jug, team, liga.upper(), len(suyos)))
    print("=" * 74)
    hd = "  ".join("%9s" % _short(c) for c in muestra)
    print("%-11s %s" % ("FECHA", hd)); print("-" * 74)
    for r in suyos[-10:]:
        print("%-11s %s" % (r.get("game_date"), "  ".join("%9s" % (r.get(c) or "-") for c in muestra)))
    print("-" * 74)
    prom = []
    for c in muestra:
        v = [_num(r.get(c)) for r in suyos if _num(r.get(c)) is not None]
        prom.append("%9.1f" % (sum(v) / len(v)) if v else "%9s" % "-")
    print("%-11s %s" % ("PROMEDIO", "  ".join(prom)))
    if muestra:
        c = muestra[0]; allv = [_num(r.get(c)) for r in suyos if _num(r.get(c)) is not None]
        u5 = [_num(r.get(c)) for r in suyos[-5:] if _num(r.get(c)) is not None]
        if allv and u5:
            pa = sum(allv)/len(allv); p5 = sum(u5)/len(u5)
            t = "SUBIENDO" if p5 > pa*1.05 else "BAJANDO" if p5 < pa*0.95 else "estable"
            print("\nForma en %s: ultimos 5 = %.1f vs temporada = %.1f  -> %s" % (c[2:], p5, pa, t))


def top(liga, stat):
    rows = cargar(liga)
    if not rows: return
    cols = stat_cols(rows)
    # match exacto e_<stat>, si no, por substring
    objetivo = "e_" + stat
    if objetivo not in cols:
        cand = [c for c in cols if stat.lower() in c.lower()]
        if len(cand) == 1:
            objetivo = cand[0]
        elif len(cand) > 1:
            print("Varias stats coinciden con '%s':" % stat, ", ".join(c[2:] for c in cand)); return
        else:
            print("No existe '%s'. Usa --cols para ver las disponibles." % stat); return
    agg = {}
    for r in rows:
        if r.get("jugo") != "1": continue
        v = _num(r.get(objetivo))
        if v is None: continue
        a = agg.setdefault(r["jugador"], {"team": r.get("team"), "s": 0.0, "n": 0})
        a["s"] += v; a["n"] += 1
    tabla = sorted(((k, v["team"], v["s"]/v["n"], v["n"]) for k, v in agg.items() if v["n"] >= 1),
                   key=lambda x: -x[2])[:15]
    print("\nTOP 15 por %s (promedio, %s):" % (objetivo[2:], liga.upper()))
    print("%-24s %-5s %9s %4s" % ("JUGADOR", "TEAM", objetivo[2:][:9], "JJ"))
    for nom, tm, pr, nn in tabla:
        print("%-24s %-5s %9.1f %4d" % (nom[:24], tm, pr, nn))


def cols_disponibles(liga):
    rows = cargar(liga)
    if not rows: return
    print("Stats disponibles en %s:" % liga)
    print(", ".join(c[2:] for c in stat_cols(rows)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", required=True)
    ap.add_argument("--jugador"); ap.add_argument("--top"); ap.add_argument("--cols", action="store_true")
    a = ap.parse_args()
    if a.cols: cols_disponibles(a.liga)
    elif a.top: top(a.liga, a.top)
    elif a.jugador: panel(a.liga, a.jugador)
    else: print('Usa --jugador "Nombre"  |  --top passing_YDS  |  --cols')
