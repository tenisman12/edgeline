# -*- coding: utf-8 -*-
"""
FICHA DE JUGADOR - record por temporada, forma reciente y bitacora de partidos, desde datos\\jugadores\\.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\ficha_jugador.py lanzadores "Gerrit Cole"
    python utilidades\\ficha_jugador.py bateadores "Aaron Judge" --ultimos 15
    python utilidades\\ficha_jugador.py porteros "Shesterkin"
    python utilidades\\ficha_jugador.py patinadores "McDavid"
    python utilidades\\ficha_jugador.py nfl "Mahomes"
    python utilidades\\ficha_jugador.py espn nba "Jokic"            (ligas de ESPN: nba, ncaamb, premier, ...)
    python utilidades\\ficha_jugador.py lista lanzadores             (quienes hay en el archivo, por partidos)

Muestra TODO: una linea por temporada, carrera, ultimos N partidos (forma) y la bitacora completa
de esos partidos. No se aplica a ningun modelo: es medicion y contexto.
"""
import argparse, csv, os, sys, unicodedata

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(BASE, "datos", "jugadores")


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")


def f(r, k):
    try:
        return float(r.get(k) or 0)
    except ValueError:
        return 0.0


def S(rows, k):
    return sum(f(r, k) for r in rows)


def div(a, b, nd=3):
    return round(a / b, nd) if b else ""


def outs(r):
    v = r.get("outs")
    return f(r, "outs") if v not in (None, "") else 0.0


# ---- especificaciones de metricas por archivo: lista de (columna, funcion(rows) -> valor)
def esp_lanzadores():
    def ip(rows): return round(sum(outs(r) for r in rows) / 3.0, 1)
    def era(rows): o = sum(outs(r) for r in rows); return div(27.0 * S(rows, "er"), o, 2)
    def whip(rows): o = sum(outs(r) for r in rows); return div(3.0 * (S(rows, "h") + S(rows, "bb")), o, 2)
    def per9(k): return lambda rows: div(27.0 * S(rows, k), sum(outs(r) for r in rows), 2)
    return [("J", len), ("GS", lambda rows: int(S(rows, "abridor"))), ("IP", ip), ("ERA", era), ("WHIP", whip),
            ("K/9", per9("k")), ("BB/9", per9("bb")), ("HR/9", per9("hr")),
            ("K-BB%", lambda rows: div(100.0 * (S(rows, "k") - S(rows, "bb")), S(rows, "bf"), 1)),
            ("G-P", lambda rows: "%d-%d" % (S(rows, "ganado"), S(rows, "perdido"))), ("SV", lambda rows: int(S(rows, "salvado"))),
            ("IP/GS", lambda rows: (lambda g: div(sum(outs(r) for r in g) / 3.0, len(g), 1))([r for r in rows if r.get("abridor") == "1"])),
            ("pitch/GS", lambda rows: (lambda g: div(S(g, "pitches"), len(g), 0))([r for r in rows if r.get("abridor") == "1"]))]


def esp_bateadores():
    def tb(rows): return S(rows, "h") + S(rows, "d2") + 2 * S(rows, "d3") + 3 * S(rows, "hr")
    def obp(rows): d = S(rows, "ab") + S(rows, "bb") + S(rows, "hbp") + S(rows, "sf"); return div(S(rows, "h") + S(rows, "bb") + S(rows, "hbp"), d)
    def slg(rows): return div(tb(rows), S(rows, "ab"))
    return [("J", len), ("PA", lambda rows: int(S(rows, "pa"))), ("AVG", lambda rows: div(S(rows, "h"), S(rows, "ab"))),
            ("OBP", obp), ("SLG", slg), ("OPS", lambda rows: (lambda o, s: round(o + s, 3) if o != "" and s != "" else "")(obp(rows), slg(rows))),
            ("HR", lambda rows: int(S(rows, "hr"))), ("RBI", lambda rows: int(S(rows, "rbi"))), ("SB", lambda rows: int(S(rows, "sb"))),
            ("K%", lambda rows: div(100.0 * S(rows, "k"), S(rows, "pa"), 1)), ("BB%", lambda rows: div(100.0 * S(rows, "bb"), S(rows, "pa"), 1))]


def esp_porteros():
    def gaa(rows): return div(60.0 * S(rows, "goles_contra"), S(rows, "toi_min"), 2)
    return [("J", len), ("GS", lambda rows: int(S(rows, "abridor"))), ("tiros", lambda rows: int(S(rows, "tiros_contra"))),
            ("GA", lambda rows: int(S(rows, "goles_contra"))), ("SV%", lambda rows: div(S(rows, "paradas"), S(rows, "tiros_contra"), 3)),
            ("GAA", gaa), ("min", lambda rows: int(S(rows, "toi_min"))),
            ("V-D", lambda rows: "%d-%d" % (sum(1 for r in rows if r.get("decision") == "W"), sum(1 for r in rows if r.get("decision") in ("L", "OT"))))]


def esp_patinadores():
    return [("J", len), ("G", lambda rows: int(S(rows, "goles"))), ("A", lambda rows: int(S(rows, "asist"))),
            ("P", lambda rows: int(S(rows, "puntos"))), ("+/-", lambda rows: int(S(rows, "mas_menos"))),
            ("tiros", lambda rows: int(S(rows, "tiros"))), ("S%", lambda rows: div(100.0 * S(rows, "goles"), S(rows, "tiros"), 1)),
            ("TOI/j", lambda rows: div(S(rows, "toi_min"), len(rows), 1)), ("PP G", lambda rows: int(S(rows, "pp_goles"))),
            ("hits", lambda rows: int(S(rows, "hits"))), ("bloq", lambda rows: int(S(rows, "bloqueos")))]


def esp_nfl():
    cols = [("passing_yards", "pass yds"), ("passing_tds", "pass TD"), ("passing_interceptions", "INT"),
            ("rushing_yards", "rush yds"), ("rushing_tds", "rush TD"), ("receptions", "rec"), ("targets", "tgt"),
            ("receiving_yards", "rec yds"), ("receiving_tds", "rec TD"), ("def_sacks", "sacks"),
            ("def_tackles_solo", "tackl"), ("fantasy_points_ppr", "fant PPR")]
    out = [("J", len)]
    for k, n in cols:
        out.append((n, (lambda kk: lambda rows: round(S(rows, kk), 1) if S(rows, kk) else "")(k)))
    return out


def esp_generico(filas):
    """ESPN: suma de columnas numericas (las que tienen datos)."""
    if not filas:
        return [("J", len)]
    meta = {"game_id", "game_date", "liga", "season", "tipo", "team", "opp", "is_home", "player_id", "jugador", "posicion",
            "titular", "dorsal"}
    cols = []
    for k in filas[0].keys():
        if k in meta:
            continue
        try:
            float(next((r[k] for r in filas if r.get(k) not in ("", None)), "x"))
        except ValueError:
            continue
        cols.append(k)
    out = [("J", len)]
    for k in cols[:14]:
        out.append((k[:11], (lambda kk: lambda rows: round(S(rows, kk), 1))(k)))
    return out


ARCHIVOS = {"lanzadores": ("mlb_lanzadores.csv", esp_lanzadores), "bateadores": ("mlb_bateadores.csv", esp_bateadores),
            "porteros": ("nhl_porteros.csv", esp_porteros), "patinadores": ("nhl_patinadores.csv", esp_patinadores),
            "nfl": ("nfl_jugadores.csv", esp_nfl)}
BITACORA = {"lanzadores": ["game_date", "team", "opp", "abridor", "ip", "h", "r", "er", "bb", "k", "hr", "pitches", "ganado", "perdido"],
            "bateadores": ["game_date", "team", "opp", "orden_bate", "ab", "r", "h", "d2", "hr", "rbi", "bb", "k", "sb"],
            "porteros": ["game_date", "team", "opp", "abridor", "tiros_contra", "paradas", "goles_contra", "sv_pct", "toi_min", "decision"],
            "patinadores": ["game_date", "team", "opp", "goles", "asist", "puntos", "tiros", "mas_menos", "toi_min", "pp_goles"],
            "nfl": ["game_date", "season", "week", "team", "opp", "posicion", "completions", "attempts", "passing_yards", "passing_tds",
                    "carries", "rushing_yards", "targets", "receptions", "receiving_yards", "receiving_tds", "fantasy_points_ppr"]}


def leer(ruta):
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def tabla(filas, cols, anchos=None):
    anchos = anchos or [max(len(str(c)), *(len(str(x[i])) for x in filas)) if filas else len(str(c)) for i, c in enumerate(cols)]
    print("  " + "  ".join(str(c).rjust(w) for c, w in zip(cols, anchos)))
    print("  " + "  ".join("-" * w for w in anchos))
    for x in filas:
        print("  " + "  ".join(str(v).rjust(w) for v, w in zip(x, anchos)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tipo", help="lanzadores | bateadores | porteros | patinadores | nfl | espn | lista")
    ap.add_argument("a", nargs="?"); ap.add_argument("b", nargs="?")
    ap.add_argument("--ultimos", type=int, default=10)
    a = ap.parse_args()

    if a.tipo == "lista":
        nombre = a.a
        if nombre not in ARCHIVOS:
            print("Uso: ficha_jugador.py lista lanzadores|bateadores|porteros|patinadores|nfl"); return
        filas = leer(os.path.join(DIR, ARCHIVOS[nombre][0])); cnt = {}
        for r in filas:
            k = (r["jugador"], r.get("team", "")); cnt[k] = cnt.get(k, 0) + 1
        for (n, t), c in sorted(cnt.items(), key=lambda x: -x[1])[:60]:
            print("  %-28s %-24s %4d juegos" % (n, t, c))
        return

    if a.tipo == "espn":
        liga, buscar = a.a, a.b
        ruta = os.path.join(DIR, "espn_%s_jugadores.csv" % liga); spec = None; bit = None
    else:
        if a.tipo not in ARCHIVOS:
            print("Tipo desconocido."); return
        buscar = a.a; ruta = os.path.join(DIR, ARCHIVOS[a.tipo][0]); spec = ARCHIVOS[a.tipo][1]; bit = BITACORA[a.tipo]
    if not os.path.exists(ruta):
        print("No existe %s. Baja los datos con recolectar_jugadores.py (ver su encabezado)." % ruta); return
    filas = leer(ruta)
    q = norm(buscar)
    ids = {}
    for r in filas:
        if q in norm(r["jugador"]):
            ids.setdefault(r["player_id"], []).append(r)
    if not ids:
        print("Sin resultados para '%s'." % buscar); return
    if len(ids) > 1:
        print("Varios jugadores coinciden (%d). Se muestran todos:\n" % len(ids))
    for pid, rows in sorted(ids.items(), key=lambda x: -len(x[1]))[:5]:
        rows.sort(key=lambda r: (r["game_date"], r["game_id"]))
        equipos = sorted({r["team"] for r in rows})
        print("=" * 100)
        print("%s  (id %s)  equipos: %s  posicion: %s  juegos: %d  %s -> %s" % (
            rows[0]["jugador"], pid, ", ".join(equipos), rows[-1].get("posicion", ""), len(rows), rows[0]["game_date"], rows[-1]["game_date"]))
        print("=" * 100)
        espec = spec() if spec else esp_generico(rows)
        nombres = [n for n, _ in espec]
        print("\nPOR TEMPORADA")
        temps = {}
        for r in rows:
            temps.setdefault(r.get("season") or r["game_date"][:4], []).append(r)
        filas_t = [[t] + [fn(rs) for _, fn in espec] for t, rs in sorted(temps.items())]
        filas_t.append(["CARRERA"] + [fn(rows) for _, fn in espec])
        u = rows[-a.ultimos:]
        filas_t.append(["ult %d" % len(u)] + [fn(u) for _, fn in espec])
        tabla(filas_t, ["temp"] + nombres)
        print("\nBITACORA, ultimos %d partidos" % len(u))
        cols = [c for c in (bit or list(u[0].keys())[:16]) if c in u[0]]
        tabla([[r.get(c, "") for c in cols] for r in reversed(u)], cols)
        print()


if __name__ == "__main__":
    main()
