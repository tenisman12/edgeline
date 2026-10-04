# -*- coding: utf-8 -*-
"""
utilidades/validar_publico.py - ¿SIRVEN los porcentajes del publico? Tres pruebas con los datos ya guardados.

Lee salida/publico_<anio>.csv (lo escribe colectores/recolectar_publico.py) y responde:

  1. COBERTURA: cuantos partidos y ligas traen boletos/dinero, cuantas casas reportan y cuantos valores extremos
     (>=95% o <=5%) quedan. Muchos extremos = el dato sigue mal leido.
  2. FAVORITISMO: correlacion entre el % de boletos en el local y la probabilidad implicita del moneyline local.
     El publico apuesta favoritos: si la correlacion es alta y positiva (0.6-0.9), el dato es creible.
     Si es cercana a 0, lo que estamos leyendo no es el publico.
  3. BOLETOS vs DINERO: distribucion de la brecha (dinero - boletos). El patron util es brecha negativa grande
     (muchos boletos chicos de un lado, el dinero del otro). Lista los 10 partidos con la brecha mas marcada.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\validar_publico.py
    python utilidades\\validar_publico.py --anio 2026 --liga nfl
Solo stdlib. No cambia ningun modelo: solo mide.
"""
import argparse, csv, datetime as dt, io, math, os, statistics, sys

MIN_APUESTAS = 2000      # debajo de esto la brecha boletos-dinero es ruido (un par de apuestas grandes la mueven)
BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def num(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def prob_implicita(am):
    """momio americano -> probabilidad implicita (con vig)."""
    if am is None:
        return None
    return (100.0 / (am + 100.0)) if am > 0 else (abs(am) / (abs(am) + 100.0))


def correlacion(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anio", type=int, default=dt.date.today().year)
    ap.add_argument("--liga")
    a = ap.parse_args()
    ruta = os.path.join(BASE, "salida", "publico_%d.csv" % a.anio)
    if not os.path.exists(ruta):
        print("No existe %s: corre primero colectores\\recolectar_publico.py" % ruta); return 1
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = [r for r in csv.DictReader(f) if not a.liga or r.get("liga") == a.liga]
    if not filas:
        print("Sin filas."); return 1
    # ultima foto por partido (la mas cercana al inicio)
    ult = {}
    for r in filas:
        k = (r.get("liga"), r.get("id"), r.get("fecha"))
        if k not in ult or (r.get("ts_utc") or "") > (ult[k].get("ts_utc") or ""):
            ult[k] = r
    ult = list(ult.values())
    con = [r for r in ult if num(r.get("ml_tickets_home")) is not None]
    print("1. COBERTURA  (%s, %d fotos, %d partidos distintos)" % (os.path.basename(ruta), len(filas), len(ult)))
    porliga = {}
    for r in ult:
        d = porliga.setdefault(r.get("liga"), [0, 0])
        d[0] += 1; d[1] += 1 if num(r.get("ml_tickets_home")) is not None else 0
    for lg, (t, c) in sorted(porliga.items()):
        print("   %-7s %3d partidos, %3d con boletos/dinero" % (lg, t, c))
    # Un 97/3 es normal en un moneyline de -1500 (NCAAFB): el extremo solo delata un error de lectura
    # cuando aparece en un partido PAREJO (probabilidad implicita del local entre 40 y 60%).
    ext = [r for r in con if num(r["ml_tickets_home"]) >= 95 or num(r["ml_tickets_home"]) <= 5]
    parejos = [r for r in con if (prob_implicita(num(r.get("ml_home"))) or 0.5) and 0.40 <= (prob_implicita(num(r.get("ml_home"))) or 0) <= 0.60]
    ext_par = [r for r in parejos if num(r["ml_tickets_home"]) >= 95 or num(r["ml_tickets_home"]) <= 5]
    print("   extremos (>=95%% o <=5%% de boletos): %d de %d (%.0f%%) -- normales en moneylines de favoritos enormes" % (
        len(ext), len(con), 100.0 * len(ext) / max(1, len(con))))
    print("   extremos en partidos PAREJOS (40-60%% de prob.): %d de %d%s" % (
        len(ext_par), len(parejos), "  <- revisar la lectura" if len(ext_par) > 0.05 * max(1, len(parejos)) else "  <- consistente"))
    vol = [num(r.get("num_bets")) for r in con if num(r.get("num_bets"))]
    if vol:
        print("   apuestas por partido: mediana %.0f, rango %.0f-%.0f (debajo de %d la brecha es ruido)" % (
            statistics.median(vol), min(vol), max(vol), MIN_APUESTAS))
    else:
        print("   sin columna num_bets utilizable (cabecera vieja del CSV: vuelve a correr el colector para migrarla)")
    if con:
        tk = [num(r["ml_tickets_home"]) for r in con]
        print("   boletos en el local: mediana %.0f%%, rango %.0f-%.0f%%" % (statistics.median(tk), min(tk), max(tk)))

    print("\n2. FAVORITISMO  (el publico apuesta favoritos)")
    xs, ys = [], []
    for r in con:
        p = prob_implicita(num(r.get("ml_home")))
        t = num(r.get("ml_tickets_home"))
        if p is not None and t is not None:
            xs.append(100.0 * p); ys.append(t)
    rr = correlacion(xs, ys)
    if rr is None:
        print("   n=%d: hacen falta mas partidos con cuota y boletos." % len(xs))
    else:
        veredicto = "creible" if rr >= 0.6 else ("debil" if rr >= 0.3 else "NO parece ser el publico")
        print("   n=%d  correlacion(prob. implicita del local, %% boletos al local) = %+.2f  -> %s" % (len(xs), rr, veredicto))
        for lo, hi in ((0, 35), (35, 50), (50, 65), (65, 100)):
            b = [y for x, y in zip(xs, ys) if lo <= x < hi]
            if b:
                print("     local al %2d-%2d%% de prob.: %2d partidos, boletos al local %.0f%% (mediana)" % (lo, hi, len(b), statistics.median(b)))

    print("\n3. BOLETOS vs DINERO  (brecha = dinero - boletos, en el local; solo partidos con >=%d apuestas)" % MIN_APUESTAS)
    br, descartados = [], 0
    for r in con:
        t, d = num(r.get("ml_tickets_home")), num(r.get("ml_money_home"))
        if t is None or d is None:
            continue
        nb = num(r.get("num_bets"))
        if nb is not None and nb < MIN_APUESTAS:
            descartados += 1; continue
        br.append((d - t, r))
    if descartados:
        print("   (%d partidos descartados por volumen bajo)" % descartados)
    if not br:
        print("   sin datos de dinero.")
    else:
        v = [x for x, _ in br]
        print("   n=%d  mediana %+.0f pp, desviacion %.0f pp, |brecha|>=10 pp en %d partidos (%.0f%%)" % (
            len(v), statistics.median(v), statistics.pstdev(v) if len(v) > 1 else 0.0,
            sum(1 for x in v if abs(x) >= 10), 100.0 * sum(1 for x in v if abs(x) >= 10) / len(v)))
        br.sort(key=lambda x: x[0])
        print("   Dinero contra los boletos (el patron que buscamos; el dinero esta con el VISITANTE):")
        for x, r in br[:6]:
            print("     %-6s %-34s boletos local %3.0f%% dinero %3.0f%% (%+.0f pp) | %s apuestas" % (
                r["liga"], ("%s @ %s" % (r["away"], r["home"]))[:34], num(r["ml_tickets_home"]), num(r["ml_money_home"]), x, r.get("num_bets") or "-"))
        print("   Dinero con los boletos (publico y dinero del mismo lado, el LOCAL):")
        for x, r in br[-6:][::-1]:
            print("     %-6s %-34s boletos local %3.0f%% dinero %3.0f%% (%+.0f pp) | %s apuestas" % (
                r["liga"], ("%s @ %s" % (r["away"], r["home"]))[:34], num(r["ml_tickets_home"]), num(r["ml_money_home"]), x, r.get("num_bets") or "-"))
    print("\nSiguiente paso: cuando haya resultados, calificar_picks.py --ver separa los picks por 'publico con / contra el pick'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
