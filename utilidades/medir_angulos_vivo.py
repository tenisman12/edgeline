# -*- coding: utf-8 -*-
"""
utilidades/medir_angulos_vivo.py - mide EN VIVO los angulos situacionales que registra picks_del_dia.py.

Lee salida/historial_angulos.csv (angulos activos de cada partido antes de empezar, con la probabilidad del modelo para
el lado al que apunta el angulo) y el resultado real de datos/<deporte>.csv. Para cada angulo y grupo de ligas:
  residuo = gano (1/0) - p del modelo, menos el residuo medio de TODOS los partidos de esa liga y ese lado
            (filas _TODOS; asi la calibracion general del modelo no se confunde con el angulo).
Da n, efecto en pp, z, las dos mitades y el veredicto con el protocolo de siempre: n >= 300, z >= 2.0 en la direccion
registrada en el minado y las dos mitades del mismo lado. Mientras no pase dice "muestra insuficiente" o "no pasa".
No cambia nada: un angulo que pase se le lleva a Alejandro para decidir si gana peso (regla 2 de CLAUDE.md).

Escribe salida/angulos_vivo.json.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/medir_angulos_vivo.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import csv, datetime as dt, io as _io, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, angulos as ANG  # noqa: E402

N_MIN, Z_MIN = 300, 2.0


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


_RES = {}


def resultados(liga):
    """(fecha, equipo, rival) -> (gf, ga) con los juegos ya jugados de la liga."""
    if liga in _RES:
        return _RES[liga]
    dep = io.deporte_de(liga); out = {}
    try:
        filas = io.cargar_juegos(liga)
    except Exception:
        filas = []
    for r in filas:
        if dep in ("futbol", "hockey"):
            gf, ga = _f(r.get("goals")), _f(r.get("goals_opp"))
        elif dep == "beisbol":
            gf, ga = _f(r.get("runs")), _f(r.get("runs_opp"))
        else:
            gf, ga = _f(r.get("points")), _f(r.get("points_opp"))
        if gf is not None and ga is not None:
            out[((r.get("game_date") or "")[:10], r.get("team"), r.get("opp"))] = (gf, ga)
    _RES[liga] = out
    return out


def gano(r):
    """1/0 si el lado del registro gano; None si el partido no esta en los datos (todavia no se juega o no cuadra)."""
    R = resultados(r["liga"])
    eq, riv = (r["home_key"], r["away_key"]) if r["lado"] == "home" else (r["away_key"], r["home_key"])
    f0 = dt.date.fromisoformat(r["fecha"][:10])
    for d in (0, -1, 1):                          # tolerancia de un dia por la zona horaria de la fuente
        k = ((f0 + dt.timedelta(days=d)).isoformat(), eq, riv)
        if k in R:
            gf, ga = R[k]
            return 1 if gf > ga else 0
    return None


def grupo(liga, codigo):
    g = ANG._grupos(liga).get(codigo[0]) or []
    return g[0] if g else (liga or "").upper()


def total_real(r):
    """goles/carreras/puntos del partido; None si todavia no esta en los datos."""
    R = resultados(r["liga"])
    f0 = dt.date.fromisoformat(r["fecha"][:10])
    for d in (0, -1, 1):
        k = ((f0 + dt.timedelta(days=d)).isoformat(), r["home_key"], r["away_key"])
        if k in R:
            return R[k][0] + R[k][1]
    return None


def totales():
    """angulos de TOTALES en vivo (salida/historial_angulos_total.csv, desde el 10-oct-2026): residuo = total real - total
    del modelo, menos el residuo medio de la liga (filas _TODOS). Pendiente por unidad de x (minimos cuadrados por el
    origen) con su z y las dos mitades; mismo protocolo (n >= 300, z >= 2.0 en la direccion registrada en el minado)."""
    ruta = io.ruta("salida", "historial_angulos_total.csv")
    if not os.path.exists(ruta):
        return {}
    with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    hoy = dt.date.today().isoformat()
    base = {}; L = []
    for r in filas:
        if r["fecha"] >= hoy:
            continue
        tm, x = _f(r.get("total_modelo")), _f(r.get("x"))
        if tm is None or x is None:
            continue
        t = total_real(r)
        if t is None:
            continue
        if r["codigo"] == "_TODOS":
            b = base.setdefault(r["liga"], [0.0, 0]); b[0] += t - tm; b[1] += 1
        else:
            L.append((r, x, t - tm))
    off = {k: v[0] / v[1] for k, v in base.items() if v[1]}
    cat = ANG.catalogo_totales(); G = {}
    for r, x, res in L:
        gr = next((g for g in ANG._grupo_total(r["liga"]) if "%s|%s" % (g, r["codigo"]) in cat), (r["liga"] or "").upper())
        G.setdefault((gr, r["codigo"]), []).append((r["fecha"], x, res - off.get(r["liga"], 0.0)))
    out = {}
    print("\nTOTALES EN VIVO (total real - total del modelo, menos el de la liga) | %d partidos" % sum(v[1] for v in base.values()))
    for (gr, cod), V in sorted(G.items(), key=lambda kv: -len(kv[1])):
        V.sort(key=lambda t: t[0]); n = len(V)

        def pend(W):
            sxx = sum(x * x for _, x, _ in W)
            return (sum(x * e for _, x, e in W) / sxx, sxx) if sxx > 0 else (None, 0)
        b, sxx = pend(V)
        if b is None:
            continue
        s2 = sum((e - b * x) ** 2 for _, x, e in V) / max(n - 1, 1)
        z = b / math.sqrt(s2 / sxx) if s2 > 0 else 0.0
        b1, _ = pend(V[:n // 2]); b2, _ = pend(V[n // 2:])
        m = cat.get("%s|%s" % (gr, cod)) or {}
        signo = None
        if m.get("coef_por_unidad") is not None and m.get("direccion_ok") is not None:
            signo = (1 if m["coef_por_unidad"] > 0 else -1) * (1 if m["direccion_ok"] else -1)
        if n < N_MIN:
            ver = "muestra insuficiente"
        elif signo and z * signo >= Z_MIN and b1 is not None and b2 is not None and b1 * signo > 0 and b2 * signo > 0:
            ver = "pasa"
        else:
            ver = "no pasa"
        out["%s|%s" % (gr, cod)] = {"grupo": gr, "codigo": cod, "angulo": ANG.NOMBRES_T.get(cod, cod), "n": n,
                                    "por_unidad": round(b, 4), "z": round(z, 2),
                                    "mitades": [None if b1 is None else round(b1, 4), None if b2 is None else round(b2, 4)],
                                    "signo_esperado": signo, "historico_por_unidad": m.get("coef_por_unidad"), "veredicto": ver,
                                    "desde": V[0][0], "hasta": V[-1][0]}
        print("  %-8s %-4s %-42s n %4d  por unidad %+8.3f  z %+5.2f  (historico %s) -> %s" % (
            gr, cod, ANG.NOMBRES_T.get(cod, cod)[:42], n, b, z, m.get("coef_por_unidad"), ver.upper()))
    return out


def main():
    ruta = io.ruta("salida", "historial_angulos.csv")
    if not os.path.exists(ruta):
        print("Sin salida/historial_angulos.csv todavia."); return
    with _io.open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    hoy = dt.date.today().isoformat()
    base = {}; angs = []
    for r in filas:
        if r["fecha"] >= hoy:
            continue
        p = _f(r.get("p_modelo_lado"))
        if p is None:
            continue
        y = gano(r)
        if y is None:
            continue
        res = y - p
        if r["codigo"] == "_TODOS":
            b = base.setdefault((r["liga"], r["lado"]), [0.0, 0]); b[0] += res; b[1] += 1
        else:
            angs.append((r, res))
    off = {k: v[0] / v[1] for k, v in base.items() if v[1]}
    G = {}
    for r, res in angs:
        k = (grupo(r["liga"], r["codigo"]), r["codigo"])
        G.setdefault(k, []).append((r["fecha"], res - off.get((r["liga"], r["lado"]), 0.0), r))
    out = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "partidos_base": sum(v[1] for v in base.values()) // 2,
           "protocolo": "n >= %d, z >= %.1f en la direccion registrada, las dos mitades del mismo lado" % (N_MIN, Z_MIN), "angulos": {}}
    print("ANGULOS EN VIVO (residuo contra el modelo, menos la calibracion de la liga) | %d partidos calificados" % out["partidos_base"])
    for (gr, cod), L in sorted(G.items(), key=lambda kv: -len(kv[1])):
        L.sort(key=lambda t: t[0]); v = [t[1] for t in L]; n = len(v); m = sum(v) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
        z = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
        h = n // 2; m1 = sum(v[:h]) / h if h else None; m2 = sum(v[h:]) / (n - h) if n - h else None
        se_ = _f(L[0][2].get("signo_esperado"))
        signo = int(se_) if se_ in (1.0, -1.0) else None
        if n < N_MIN:
            ver = "muestra insuficiente"
        elif signo and z * signo >= Z_MIN and m1 is not None and m2 is not None and m1 * signo > 0 and m2 * signo > 0:
            ver = "pasa"
        else:
            ver = "no pasa"
        med = ANG.medicion(L[0][2]["liga"], cod) or {}
        out["angulos"]["%s|%s" % (gr, cod)] = {"grupo": gr, "codigo": cod, "angulo": ANG.NOMBRES.get(cod, cod), "n": n,
                                               "efecto_pp": round(100 * m, 2), "z": round(z, 2),
                                               "mitades_pp": [None if m1 is None else round(100 * m1, 2), None if m2 is None else round(100 * m2, 2)],
                                               "signo_esperado": signo, "veredicto": ver,
                                               "medido_historico_pp": med.get("efecto_pp"), "desde": L[0][0], "hasta": L[-1][0]}
        print("  %-8s %-4s %-42s n %4d  efecto %+6.1f pp  z %+5.2f  (historico %s pp) -> %s" % (
            gr, cod, ANG.NOMBRES.get(cod, cod)[:42], n, 100 * m, z,
            "%+.1f" % med["efecto_pp"] if med.get("efecto_pp") is not None else "-", ver.upper()))
    out["totales"] = totales()
    with _io.open(io.ruta("salida", "angulos_vivo.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Escrito: salida/angulos_vivo.json")


if __name__ == "__main__":
    main()
