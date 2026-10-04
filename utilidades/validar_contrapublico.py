# -*- coding: utf-8 -*-
"""
utilidades/validar_contrapublico.py - ¿PAGA ir contra el publico? Las reglas clasicas, medidas contra el resultado.

Mide las dos reglas del manual de "fade the public" que se pueden medir con lo que guardamos:

  R1  UNDER cuando el over trae >= UMBRAL_OVER % de los boletos (en hockey y futbol el publico carga el over).
  R2  DOG al moneyline cuando el favorito trae >= UMBRAL_FAV % de los boletos (el publico apuesta favoritos).

Cada regla se registra como una apuesta sombra de 1 unidad: no se recomienda, solo se mide. La pregunta no es si
el lado contrario gana, es si gana MAS DE LO QUE PAGA EL PRECIO. Por eso:
  - En el moneyline se usa la probabilidad sin vig del dog como "esperado" y su cuota real para las unidades.
  - En el total no guardamos el precio del over/under, asi que se asume -110 (1.909): el punto de equilibrio es
    52.4 % de acierto. Debajo de eso la regla pierde dinero aunque "acierte mas de la mitad".

Fuentes: salida/publico_<anio>.csv (ultima foto por partido) y salida/historial_predicciones_calificado.csv
(resultado real: ganador y total de carreras/goles/puntos). Solo cuenta partidos con >= MIN_APUESTAS apuestas.

Veredicto con el protocolo del proyecto: n>=300, z>=2.0 y mejora en las dos mitades. Mientras no se cumpla,
dice cuanto falta y NO cambia nada.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\validar_contrapublico.py
    python utilidades\\validar_contrapublico.py --liga nhl --umbral-over 85
Solo stdlib. No toca ningun modelo: solo mide.
"""
import argparse, csv, datetime as dt, io, math, os, re, statistics, sys, unicodedata

N_MIN, Z_MIN = 300, 2.0
MIN_APUESTAS = 2000
CUOTA_TOTAL = 1.909            # -110: lo que se asume para el total mientras no guardemos su precio
BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_IGN = {"the", "fc", "sc", "club", "de", "los", "las", "la", "el", "st", "state", "university"}


def clave(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _IGN)


def num(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def pi(am):
    """momio americano -> probabilidad implicita con vig."""
    if am is None:
        return None
    return (100.0 / (am + 100.0)) if am > 0 else (abs(am) / (abs(am) + 100.0))


def decimal(am):
    if am is None:
        return None
    return 1.0 + (am / 100.0 if am > 0 else 100.0 / abs(am))


def ultimas_fotos(anio, liga=None):
    ruta = os.path.join(BASE, "salida", "publico_%d.csv" % anio)
    if not os.path.exists(ruta):
        return {}, ruta
    ult = {}
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if liga and r.get("liga") != liga:
                continue
            k = (r.get("liga"), r.get("id"), r.get("fecha"))
            if k not in ult or (r.get("ts_utc") or "") > (ult[k].get("ts_utc") or ""):
                ult[k] = r
    return ult, ruta


def resultados():
    """{(liga, fecha, clave_home, clave_away): {'gan': 'home'|'away', 'total': float}}"""
    ruta = os.path.join(BASE, "salida", "historial_predicciones_calificado.csv")
    out = {}
    if not os.path.exists(ruta):
        return out
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for x in csv.DictReader(f):
            if x.get("estado") != "calificado":
                continue
            k = (x.get("liga"), x.get("fecha"), clave(x.get("home")), clave(x.get("away")))
            d = out.setdefault(k, {})
            m = x.get("mercado") or ""
            if m == "Ganador" and (x.get("real") or "").strip() in ("home", "away"):
                d["gan"] = x["real"].strip()
            elif m.startswith("Total"):
                t = num(x.get("real"))
                if t is not None:
                    d["total"] = t
    return out


def indice(res):
    """{(liga, fecha): [(clave_home, clave_away, resultado)]} para emparejar por nombre tolerante."""
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
    """filas = [(esperado, gano, cuota, liga, fecha)] -> (n, esperado, real, z, unidades)."""
    n = len(filas)
    if not n:
        return 0, 0.0, 0.0, 0.0, 0.0
    esp = statistics.mean([e for e, _, _, _, _ in filas])
    real = statistics.mean([g for _, g, _, _, _ in filas])
    var = sum(e * (1 - e) for e, _, _, _, _ in filas)
    z = (real - esp) / (math.sqrt(var) / n) if var > 0 else 0.0
    u = sum((c - 1.0) if g else -1.0 for _, g, c, _, _ in filas)
    return n, esp, real, z, u


def reporte(titulo, filas, nota=""):
    print("\n%s%s" % (titulo, ("  (%s)" % nota if nota else "")))
    if not filas:
        print("   todavia no hay partidos que cumplan la regla. Nada que medir.")
        return
    n, esp, real, z, u = medir(filas)
    print("   n=%d  esperado %.1f%%  real %.1f%%  dif %+.1f pp  z=%+.2f  unidades %+.2f u" % (
        n, 100 * esp, 100 * real, 100 * (real - esp), z, u))
    fechas = sorted({f[4] for f in filas})
    ok_mitades = None
    if len(fechas) > 1:
        corte = fechas[len(fechas) // 2]
        a1 = [f for f in filas if f[4] < corte]; a2 = [f for f in filas if f[4] >= corte]
        for nom, g in (("primera mitad", a1), ("segunda mitad", a2)):
            if g:
                nn, ee, rr, _, uu = medir(g)
                print("     %-14s n=%3d  esperado %.1f%%  real %.1f%%  (dif %+.1f pp, %+.2f u)" % (
                    nom, nn, 100 * ee, 100 * rr, 100 * (rr - ee), uu))
        if a1 and a2:
            ok_mitades = medir(a1)[2] > medir(a1)[1] and medir(a2)[2] > medir(a2)[1]
    for lg in sorted({f[3] for f in filas}):
        g = [f for f in filas if f[3] == lg]
        nn, ee, rr, _, uu = medir(g)
        print("     %-7s n=%3d  esperado %.1f%%  real %.1f%%  (dif %+.1f pp, %+.2f u)" % (
            lg, nn, 100 * ee, 100 * rr, 100 * (rr - ee), uu))
    faltas = []
    if n < N_MIN:
        faltas.append("faltan %d" % (N_MIN - n))
    if z < Z_MIN:
        faltas.append("z=%+.2f (hace falta %.1f)" % (z, Z_MIN))
    if ok_mitades is False:
        faltas.append("no mejora en las dos mitades")
    print("   %s" % ("SIN VALIDAR: %s. Se sigue acumulando." % "; ".join(faltas) if faltas else
                     "PASA. Se puede proponer como capa (lo aprueba Alejandro antes de entrar)."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anio", type=int, default=dt.date.today().year)
    ap.add_argument("--liga")
    ap.add_argument("--umbral-over", type=float, default=80.0, dest="over")
    ap.add_argument("--umbral-fav", type=float, default=70.0, dest="fav")
    a = ap.parse_args()
    ult, ruta = ultimas_fotos(a.anio, a.liga)
    if not ult:
        print("No existe o esta vacio %s: corre colectores\\recolectar_publico.py" % ruta)
        return 1
    res = resultados()
    ind = indice(res)
    hoy = dt.date.today().isoformat()
    r1, r2, sin_res, sin_emparejar, poco = [], [], 0, 0, 0
    emparejados, con_total, con_ml, dispara1, dispara2 = 0, 0, 0, 0, 0
    for (lg, _id, fecha), r in ult.items():
        rr = emparejar(ind, lg, fecha, r.get("home"), r.get("away"))
        if not rr:
            # un partido de hace dias sin resultado no esta pendiente: no empareja con el historial
            if fecha and fecha < hoy:
                sin_emparejar += 1
            else:
                sin_res += 1
            continue
        emparejados += 1
        nb = num(r.get("num_bets"))
        if nb is not None and nb < MIN_APUESTAS:
            poco += 1; continue
        # R1: under cuando el publico carga el over
        ov = num(r.get("total_tickets_over"))
        linea = num(r.get("total_publico")) or num(r.get("total"))
        tot = rr.get("total")
        if ov is not None and linea is not None and tot is not None:
            con_total += 1
            if ov >= a.over:
                dispara1 += 1
        if ov is not None and ov >= a.over and linea is not None and tot is not None and tot != linea:
            # precio real del under si el colector ya lo guarda; si no, -110
            cu = decimal(num(r.get("under_odds")))
            co = decimal(num(r.get("over_odds")))
            if cu and co:
                e = (1.0 / cu) / (1.0 / cu + 1.0 / co)         # sin vig
            else:
                cu, e = CUOTA_TOTAL, 1.0 / CUOTA_TOTAL
            r1.append((e, 1 if tot < linea else 0, cu, lg, fecha))
        # R2: dog cuando el publico carga al favorito
        bh = num(r.get("ml_tickets_home"))
        mh, ma = num(r.get("ml_home")), num(r.get("ml_away"))
        ph, pa = pi(mh), pi(ma)
        if bh is not None and ph is not None and pa is not None and rr.get("gan"):
            con_ml += 1
            fav = "home" if ph > pa else "away"
            boletos_fav = bh if fav == "home" else 100.0 - bh
            dog = "away" if fav == "home" else "home"
            if boletos_fav >= a.fav:
                dispara2 += 1
                e = (pa if dog == "away" else ph) / (ph + pa)          # sin vig
                c = decimal(ma if dog == "away" else mh)
                if c and 0 < e < 1:
                    r2.append((e, 1 if rr["gan"] == dog else 0, c, lg, fecha))
    print("CONTRA EL PUBLICO  (%s)" % os.path.basename(ruta))
    print("   partidos con foto del publico: %d | sin resultado todavia: %d | descartados por volumen bajo: %d" % (
        len(ult), sin_res, poco))
    print("   emparejados con resultado: %d -> con total y linea %d (de esos, %d con el over al %.0f%%+), con cuotas de ML %d (de esos, %d con el favorito al %.0f%%+)" % (
        emparejados, con_total, dispara1, a.over, con_ml, dispara2, a.fav))
    if sin_emparejar:
        print("   %d partidos ya jugados NO emparejaron con el historial (nombres distintos entre fuentes): revisar" % sin_emparejar)
    reporte("R1  UNDER con el over al %.0f%% o mas de los boletos" % a.over, r1,
            "precio asumido -110; punto de equilibrio 52.4%")
    reporte("R2  DOG con el favorito al %.0f%% o mas de los boletos" % a.fav, r2,
            "esperado = probabilidad sin vig del dog")
    print("\nR3 (el favorito no cubre el spread) no se mide todavia: el CSV del publico no guarda el precio del")
    print("spread ni el marcador por equipo. Se agrega cuando el colector los guarde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
