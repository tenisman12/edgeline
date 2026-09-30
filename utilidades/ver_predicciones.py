# -*- coding: utf-8 -*-
"""Muestra TODAS las predicciones de salida\\proximos.json, sin esconder ninguna.
Uso:  python utilidades\\ver_predicciones.py --ligas mlb,nhl --fecha 2026-09-30 --dias 2
      (sin --fecha: manana; sin --ligas: todas)
Cada juego: probabilidades de ambos lados, pick (siempre el favorito), carreras/goles esperados, total con Over/Under,
run line / puck line, cuotas y edge de TODOS los mercados con cuota, probables ESPN (contexto) y avisos.
* = pretemporada (aprox. por fecha; no cuenta para el historial). Sin ajuste por abridor/portero/lesiones."""
import argparse, datetime as dt, io, json, os

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")
PRE_INICIO = {"nhl": "2026-10-07"}


def pct(x): return "%5.1f%%" % (100 * x) if x is not None else "   -  "


def es_pre(p):
    if p.get("pretemporada"): return True
    ini = PRE_INICIO.get(p["liga"])
    return bool(ini and p["fecha"] < ini)


def ab(t): return t.get("abrev") or t["nombre"].split()[-1]


def cuota(c): return "%+d" % c if c is not None else "-"


def _imp(o): return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def _nv(a, b):
    x, y = _imp(a), _imp(b); return x / (x + y)


def movimiento(c, v, h):
    """Movimiento de linea apertura -> actual (ESPN/DraftKings). Dinero implicito: hacia donde se movio la probabilidad sin margen."""
    out = []
    if None not in (c.get("ml_home"), c.get("ml_away"), c.get("ml_home_open"), c.get("ml_away_open")):
        a, b = _nv(c["ml_home_open"], c["ml_away_open"]), _nv(c["ml_home"], c["ml_away"])
        d = 100 * (b - a)
        lado = ab(h) if d > 0 else ab(v)
        out.append("ML %s %s / %s %s  ->  %s %s / %s %s   (prob. sin margen de %s: %.1f%% -> %.1f%%, %+.1f pts %s)" % (
            ab(v), cuota(c["ml_away_open"]), ab(h), cuota(c["ml_home_open"]), ab(v), cuota(c["ml_away"]), ab(h), cuota(c["ml_home"]),
            ab(h), 100 * a, 100 * b, d, ("hacia " + lado) if abs(d) >= 0.05 else "sin cambio"))
    if c.get("total") is not None and c.get("total_open") is not None:
        t0, t1 = c["total_open"], c["total"]
        out.append("TOTAL %.1f -> %.1f  %s" % (t0, t1, "(sin cambio)" if t0 == t1 else ("(sube %+.1f)" % (t1 - t0) if t1 > t0 else "(baja %+.1f)" % (t1 - t0))))
    if c.get("spread_home") is not None and c.get("spread_home_open") is not None:
        s0, s1 = c["spread_home_open"], c["spread_home"]
        out.append("SPREAD local %+g -> %+g  %s" % (s0, s1, "(sin cambio)" if s0 == s1 else ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas"); ap.add_argument("--fecha"); ap.add_argument("--dias", type=int, default=1)
    ap.add_argument("--archivo", default=os.path.join(BASE, "salida", "proximos.json"))
    a = ap.parse_args()
    with io.open(a.archivo, encoding="utf-8") as f:
        d = json.load(f)
    f0 = dt.date.fromisoformat(a.fecha) if a.fecha else dt.date.today() + dt.timedelta(days=1)
    fechas = [(f0 + dt.timedelta(days=i)).isoformat() for i in range(a.dias)]
    ligas = {x.strip().lower() for x in a.ligas.split(",")} if a.ligas else None
    print("Predicciones (proximos.json generado %s) | * = pretemporada | horas CDMX\n" % d.get("generado"))
    hubo = False
    for fe in fechas:
        ps_dia = [p for p in d["partidos"] if p["fecha"] == fe and (ligas is None or p["liga"] in ligas)]
        for lg in sorted({p["liga"] for p in ps_dia}):
            hubo = True
            print("=" * 100); print("%s  %s" % (lg.upper(), fe)); print("=" * 100)
            for p in [x for x in ps_dia if x["liga"] == lg]:
                m = p.get("modelo"); h, v = p["home"], p["away"]
                pre = "  [PRETEMPORADA]" if es_pre(p) else ""
                print("\n%s%s  %s @ %s%s   %s" % ("*" if pre else " ", p["hora"], v["nombre"], h["nombre"], pre, p.get("nota") or ""))
                if p.get("serie"): print("      serie: %s" % p["serie"])
                if not m:
                    print("      modelo: sin datos suficientes (%s)" % p.get("motivo")); continue
                u = m.get("unidad", "")
                print("      PROBABILIDAD  %-4s %s   %-4s %s" % (ab(v), pct(m["p_away"]), ab(h), pct(m["p_home"])))
                pk = p.get("pick") or {}
                print("      PICK          %s (%s) | confianza %s" % (pk.get("texto"), pct(pk.get("prob")).strip(), pk.get("confianza")))
                print("      %-13s %-4s %.2f   %-4s %.2f   total %.2f" % (u.upper() + " ESP.", ab(v), m["x_away"], ab(h), m["x_home"], m["total"]))
                if m.get("linea_total"):
                    print("      TOTAL %.1f (%s)   Over %s   Under %s" % (
                        m["linea_total"], "linea de mercado" if m.get("linea_es_mercado") else "linea de referencia",
                        pct(m.get("p_over")).strip(), pct(1 - m["p_over"] if m.get("p_over") is not None else None).strip()))
                else:
                    print("      TOTAL sin linea publicada todavia (modelo %.2f)" % m["total"])
                for nom, pr in m.get("extra") or []:
                    print("      %-26s %s" % (nom, pct(pr).strip()))
                if m.get("nota"): print("      nota: %s" % m["nota"])
                c = p.get("cuotas")
                if c:
                    print("      CUOTAS (%s): ML %s %s / %s %s | total %s over %s under %s" % (
                        c.get("casa"), ab(v), cuota(c.get("ml_away")), ab(h), cuota(c.get("ml_home")),
                        c.get("total"), cuota(c.get("over_odds")), cuota(c.get("under_odds"))))
                    for t in movimiento(c, v, h): print("      MOVIMIENTO  " + t)
                    print("      %-22s %-9s %8s %9s %9s %8s" % ("MERCADO", "lado", "cuota", "p modelo", "p mercado", "edge"))
                    for x in p.get("mercados") or []:
                        print("      %-22s %-9s %8s %9s %9s %+7.1f%%%s" % (
                            x["mercado"], x["lado"], cuota(x["cuota"]), pct(x["p_modelo"]).strip(), pct(x["p_mercado"]).strip(),
                            100 * x["edge"], "  <- VALOR" if x.get("estado") == "valor" else ("  (dif. sin validar: este mercado no vence al baseline)" if x.get("estado") == "sin_validar" else "")))
                else:
                    print("      CUOTAS: aun no publicadas")
                pj = [x for x in (v.get("probable"), h.get("probable")) if x]
                if pj: print("      probables ESPN (contexto, no se aplican): %s / %s" % (v.get("probable") or "?", h.get("probable") or "?"))
                if p.get("alerta"): print("      AVISO: %s" % p["alerta"])
    if not hubo:
        print("No hay partidos en esas fechas/ligas.")
        fs = sorted({p["fecha"] for p in d["partidos"] if ligas is None or p["liga"] in ligas})
        if fs: print("Fechas con partidos en el archivo: %s" % ", ".join(fs[:12]))
    if d.get("avisos"):
        print("\nAvisos del modelo:"); [print("  - " + x) for x in d["avisos"]]


if __name__ == "__main__":
    main()
