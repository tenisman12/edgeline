# -*- coding: utf-8 -*-
"""
utilidades/validar_movimiento.py - ¿PAGA ir con el movimiento de linea? Se acumula solo y se mide cada dia.

La hipotesis que SI se puede medir de "ir contra el publico": el publico apuesta favoritos, asi que cuando la
linea del grupo sharp se mueve AL OTRO LADO de donde esta el publico, ese lado gana por encima de lo que paga
el cierre. No se mide el % de boletos (empezo el 3-oct-2026, no hay historia): se mide el movimiento, que ya se
guarda hora por hora en salida/cuotas_sharp_2026.csv desde que corre cuotas.yml.

Que hace:
  1. De cuotas_sharp_<anio>.csv saca, por partido y mercado, la probabilidad sharp de APERTURA (primera foto) y de
     CIERRE (ultima foto). El movimiento es cierre - apertura, en puntos porcentuales.
  2. Empareja con el resultado real de historial_predicciones_calificado.csv (por liga, fecha y nombres).
  3. Mide: apostando al lado al que se movio la linea, ¿se gana mas de lo que paga el cierre? Reporta n, esperado,
     real, z, unidades a 1 u por apuesta y el desglose por liga y por mitades.

El veredicto usa el protocolo del proyecto: n>=300, z>=2.0 y mejora en las DOS mitades. Mientras no se cumpla,
imprime cuanto falta y NO cambia nada del modelo.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\validar_movimiento.py
    python utilidades\\validar_movimiento.py --umbral 3 --liga nfl
Solo stdlib. No toca ningun modelo: solo mide.
"""
import argparse, csv, datetime as dt, io, math, os, re, statistics, sys, unicodedata

N_MIN, Z_MIN = 300, 2.0
BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_IGN = {"the", "fc", "sc", "club", "de", "los", "las", "la", "el", "st", "state", "university"}
# cuotas_sharp usa los nombres de deporte de The Odds API; aqui solo hace falta la familia para el reporte
LIGA_DE = (("baseball_mlb", "mlb"), ("baseball_npb", "npb"), ("baseball_kbo", "kbo"), ("icehockey_nhl", "nhl"),
           ("americanfootball_nfl", "nfl"), ("americanfootball_ncaaf", "ncaafb"), ("basketball_nba", "nba"),
           ("basketball_ncaab", "ncaamb"), ("tennis_atp", "atp"), ("tennis_wta", "wta"))


def clave(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _IGN)


def mismo(a, b):
    A, B = clave(a), clave(b)
    return bool(A and B) and len(A & B) / float(min(len(A), len(B))) >= 0.5


def num(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def liga_de(sport):
    for pre, lg in LIGA_DE:
        if (sport or "").startswith(pre):
            return lg
    return (sport or "").split("_")[0]


def movimientos(anio, mercado="h2h"):
    """{(liga, fecha, clave_home, clave_away): {p_open, p_close, home, away}} del grupo sharp."""
    ruta = os.path.join(BASE, "salida", "cuotas_sharp_%d.csv" % anio)
    if not os.path.exists(ruta):
        return {}, ruta
    por = {}
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("mercado") != mercado or r.get("lado") != "home":
                continue
            p = num(r.get("p_sharp"))
            if p is None:
                continue
            if p <= 1.0:
                p *= 100.0                # cuotas_sharp guarda la probabilidad en fraccion (0.7192), aqui se usa en pp
            fecha = (r.get("commence_time") or "")[:10]
            k = (liga_de(r.get("sport")), fecha, clave(r.get("home")), clave(r.get("away")))
            d = por.setdefault(k, {"fotos": [], "home": r.get("home"), "away": r.get("away")})
            d["fotos"].append((r.get("ts_utc") or "", p))
    out = {}
    for k, d in por.items():
        d["fotos"].sort()
        if len(d["fotos"]) < 2:
            continue                      # con una sola foto no hay movimiento que medir
        out[k] = {"p_open": d["fotos"][0][1], "p_close": d["fotos"][-1][1], "fotos": len(d["fotos"]),
                  "home": d["home"], "away": d["away"]}
    return out, ruta


def resultados():
    """{(liga, fecha, clave_home, clave_away): 'home'|'away'} de las predicciones ya calificadas."""
    ruta = os.path.join(BASE, "salida", "historial_predicciones_calificado.csv")
    out = {}
    if not os.path.exists(ruta):
        return out
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for x in csv.DictReader(f):
            if x.get("mercado") != "Ganador" or x.get("estado") != "calificado":
                continue
            r = (x.get("real") or "").strip()
            if r in ("home", "away"):
                out[(x.get("liga"), x.get("fecha"), clave(x.get("home")), clave(x.get("away")))] = r
    return out


def indice(res):
    """{(liga, fecha): [(clave_home, clave_away, lado_ganador)]}"""
    ind = {}
    for (lg, fecha, ch, ca), v in res.items():
        ind.setdefault((lg, fecha), []).append((ch, ca, v))
    return ind

def emparejar(ind, liga, fecha, home, away):
    """Busca el partido en el indice {(liga, fecha): [(clave_home, clave_away, valor)]} tolerando nombres
    distintos entre fuentes (Action Network escribe 'Montreal Canadiens', ESPN escribe otra cosa).
    Primero intenta la coincidencia exacta de conjuntos; si falla, pide 50% de palabras en comun en los dos lados."""
    ch, ca = clave(home), clave(away)
    for a, b, v in ind.get((liga, fecha), ()):
        if a == ch and b == ca:
            return v
    def parecido(A, B):
        return bool(A and B) and len(A & B) / float(min(len(A), len(B))) >= 0.5
    for a, b, v in ind.get((liga, fecha), ()):
        if parecido(a, ch) and parecido(b, ca):
            return v
    return None

def medir(filas):
    """filas = [(esperado, gano, liga, fecha)] -> (n, esperado, real, z, unidades)."""
    n = len(filas)
    if not n:
        return 0, 0.0, 0.0, 0.0, 0.0
    esp = statistics.mean([e for e, _, _, _ in filas])
    real = statistics.mean([g for _, g, _, _ in filas])
    var = sum(e * (1 - e) for e, _, _, _ in filas)
    z = (real - esp) / (math.sqrt(var) / n) if var > 0 else 0.0
    u = sum((1.0 / e - 1.0) if g else -1.0 for e, g, _, _ in filas if e > 0)
    return n, esp, real, z, u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anio", type=int, default=dt.date.today().year)
    ap.add_argument("--umbral", type=float, default=2.0, help="movimiento minimo en puntos porcentuales (default 2)")
    ap.add_argument("--liga")
    a = ap.parse_args()
    mov, ruta = movimientos(a.anio)
    if not mov:
        print("No existe o esta vacio %s: la historia de cuotas sharp la escribe cuotas.yml cada hora." % ruta)
        return 1
    res = resultados()
    ind = indice(res)
    filas, sin_res = [], 0
    for k, m in mov.items():
        if a.liga and k[0] != a.liga:
            continue
        r = emparejar(ind, k[0], k[1], m.get("home"), m.get("away"))
        if r is None:
            sin_res += 1; continue
        d = m["p_close"] - m["p_open"]
        if abs(d) < a.umbral:
            continue
        lado = "home" if d > 0 else "away"
        e = (m["p_close"] if lado == "home" else 100.0 - m["p_close"]) / 100.0
        if not (0.0 < e < 1.0):
            continue
        filas.append((e, 1 if r == lado else 0, k[0], k[1]))
    print("MOVIMIENTO DE LINEA  (%s)" % os.path.basename(ruta))
    print("   partidos con historia de cuotas: %d | ya calificados: %d | esperando resultado: %d" % (
        len(mov), len(mov) - sin_res, sin_res))
    print("   con movimiento >= %.1f pp: %d" % (a.umbral, len(filas)))
    if not filas:
        print("   todavia no hay partidos que cumplan. Nada que medir.")
        return 0
    n, esp, real, z, u = medir(filas)
    print("\nApostar al lado al que se movio la linea sharp:")
    print("   n=%d  esperado %.1f%%  real %.1f%%  dif %+.1f pp  z=%+.2f  unidades %+.2f u" % (
        n, 100 * esp, 100 * real, 100 * (real - esp), z, u))
    mitad = sorted({f[3] for f in filas})
    corte = mitad[len(mitad) // 2] if len(mitad) > 1 else None
    ok_mitades = None
    if corte:
        a1 = [f for f in filas if f[3] < corte]; a2 = [f for f in filas if f[3] >= corte]
        for nom, g in (("primera mitad", a1), ("segunda mitad", a2)):
            if g:
                nn, ee, rr, zz, uu = medir(g)
                print("     %-14s n=%3d  esperado %.1f%%  real %.1f%%  (dif %+.1f pp)" % (nom, nn, 100 * ee, 100 * rr, 100 * (rr - ee)))
        ok_mitades = bool(a1 and a2 and medir(a1)[2] > medir(a1)[1] and medir(a2)[2] > medir(a2)[1])
    print("   por liga:")
    for lg in sorted({f[2] for f in filas}):
        g = [f for f in filas if f[2] == lg]
        nn, ee, rr, zz, uu = medir(g)
        print("     %-7s n=%3d  esperado %.1f%%  real %.1f%%  (dif %+.1f pp, %+.2f u)" % (lg, nn, 100 * ee, 100 * rr, 100 * (rr - ee), uu))
    print("\nVEREDICTO (protocolo: n>=%d, z>=%.1f, mejora en las dos mitades)" % (N_MIN, Z_MIN))
    faltas = []
    if n < N_MIN:
        faltas.append("faltan %d partidos" % (N_MIN - n))
    if z < Z_MIN:
        faltas.append("z=%+.2f (hace falta %.1f)" % (z, Z_MIN))
    if ok_mitades is False:
        faltas.append("no mejora en las dos mitades")
    if faltas:
        print("   SIN VALIDAR: %s. No se usa para decidir; se sigue acumulando." % "; ".join(faltas))
    else:
        print("   PASA. Se puede proponer como capa con peso estimado (lo aprueba Alejandro antes de entrar).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
