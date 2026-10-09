# -*- coding: utf-8 -*-
"""
utilidades/pesos_ausencias_minutos.py - coeficientes de produccion de las dos capas que pasaron la tanda 3
(aprobadas por Alejandro el 9-oct-2026):
  - K14 NBA: ausencias (minutos de los que faltan), encima del modelo de NBA CON sus capas de produccion
    (descanso, back-to-back, net rating L10; pesos de plataforma._ajuste_capas_nba).
  - T1 ATP: minutos del partido anterior en el torneo, encima del modelo de tenis.
Ajuste con offset: logit(q) = logit(p_produccion) + beta * x (un solo parametro, se suma tal cual en plataforma.py).
Ademas se repite la prueba 70/30 sobre la base de produccion (NBA) para confirmar que K14 sigue sumando ahi.
Escribe modelos/capas_ausencias_minutos.json.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/pesos_ausencias_minutos.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import datetime as dt, json, math, os, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI); sys.path.insert(0, os.path.dirname(AQUI))
import minar_situacionales as M  # noqa: E402
import minar_angulos_tanda3 as T3  # noqa: E402


def ajuste_offset(L, X, Y, iters=50):
    """beta de logit(q) = L + beta*X por Newton; devuelve beta y su error estandar."""
    b = 0.0
    for _ in range(iters):
        g = h = 0.0
        for l, x, y in zip(L, X, Y):
            q = M._sig(l + b * x); g += (q - y) * x; h += q * (1 - q) * x * x
        if h <= 0: break
        paso = g / h; b -= paso
        if abs(paso) < 1e-10: break
    return b, (1 / math.sqrt(h) if h > 0 else None)


def nba():
    sys.argv = ["x"]
    import plataforma as P
    T3._silenciar(); M.correr_basquet("NBA"); T3._activar()
    filas, C = M.ULTIMO["NBA"]
    # K14 igual que en la tanda 3
    import io as _io, csv
    from collections import Counter, defaultdict
    ruta = os.path.join(M.BASE, "datos", "equipos", "nba_ausencias.csv")
    loc_abr = defaultdict(set)
    for x in csv.DictReader(_io.open(os.path.join(M.BASE, "datos", "nba.csv"), encoding="utf-8-sig")):
        if x.get("league") == "NBA" and str(x.get("is_home")) in ("1", "1.0", "True"):
            loc_abr[x["game_date"][:10]].add(x["team"])
    A = list(csv.DictReader(_io.open(ruta, encoding="utf-8-sig")))
    par = defaultdict(Counter)
    for x in A:
        if str(x.get("is_home")) in ("1", "1.0", "True"):
            for ab in loc_abr.get(x["game_date"][:10], ()): par[x["team"]][ab] += 1
    nom = {f: c.most_common(1)[0][0] for f, c in par.items() if c}
    aus = {}
    for x in A:
        ab, ao = nom.get(x["team"]), nom.get(x.get("opp"))
        if ab and ao:
            loc = str(x.get("is_home")) in ("1", "1.0", "True")
            h, a = (ab, ao) if loc else (ao, ab)
            aus[(x["game_date"][:10], h, a, loc)] = M._num(x.get("min_ausentes"))
    B_DESC, B_B2B, B_NET = 0.0664, -0.2336, 0.1664          # los de plataforma._ajuste_capas_nba
    R = []
    for r in filas:
        k = (r["fecha"][:10], r["home"], r["away"])
        mh, ma = aus.get(k + (True,)), aus.get(k + (False,))
        if mh is None or ma is None: continue
        ch, ca = P._capas_nba(r["home"], r["fecha"][:10]), P._capas_nba(r["away"], r["fecha"][:10])
        sh = 0.0
        if ch and ca:
            dnet = ((ch["net_rating_L10"] - ca["net_rating_L10"]) / 10.0) if (ch["net_rating_L10"] is not None and ca["net_rating_L10"] is not None) else 0.0
            sh = B_DESC * (ch["descanso_dias"] - ca["descanso_dias"]) + B_B2B * ((1.0 if ch["b2b"] else 0.0) - (1.0 if ca["b2b"] else 0.0)) + B_NET * dnet
        R.append(dict(fecha=r["fecha"], gp=r["gp"], y=r["y"], p=M._sig(M._lg(r["p"]) + sh), x=(ma - mh) / 48.0))
    R.sort(key=lambda r: r["fecha"])
    print("NBA K14 sobre la base de produccion (modelo + descanso, b2b, net rating L10): %d partidos" % len(R))
    out70 = M.evaluar(R, "K14", "ausencias sobre la base de produccion", "NBA", +1, base_nombre="produccion")
    b, se = ajuste_offset([M._lg(r["p"]) for r in R], [r["x"] for r in R], [r["y"] for r in R])
    print("  beta con offset (toda la muestra): %+.4f (EE %.4f) por cada 48 minutos de diferencia" % (b, se))
    return {"beta": round(b, 4), "ee": round(se, 4), "n": len(R), "desde": R[0]["fecha"], "hasta": R[-1]["fecha"],
            "x": "(minutos por juego de los ausentes de la visita - del local) / 48; ausente = 20+ min de promedio en 3 o mas de sus "
                 "ultimos 5 juegos del equipo y no juega (en vivo: 'Out' en el reporte de lesiones de ESPN)",
            "prueba_70_30_sobre_produccion": {k: out70.get(k) for k in ("z", "mitades", "mejora_milesimas", "n_activo_prueba", "calibracion_activos", "veredicto")} if out70 else None}


def atp():
    import csv
    filas = []
    orig = M.evaluar
    capt = {}

    def cap(rows, cod, *a, **k):
        if cod == "T1" and a[1] == "ATP" and k.get("base_nombre", "modelo") == "modelo":
            capt["rows"] = rows
        return None
    M.evaluar = cap
    try:
        T3.tenis()
    finally:
        M.evaluar = orig
    R = [r for r in capt["rows"] if r.get("x") is not None]
    b, se = ajuste_offset([M._lg(r["p"]) for r in R], [r["x"] for r in R], [r["y"] for r in R])
    print("ATP T1: beta con offset (toda la muestra): %+.4f (EE %.4f) por hora de diferencia, n %d" % (b, se, len(R)))
    return {"beta": round(b, 4), "ee": round(se, 4), "n": len(R), "desde": min(r["fecha"] for r in R), "hasta": max(r["fecha"] for r in R),
            "x": "(minutos del partido anterior del rival en el torneo - propios) / 60, desde el lado local; solo si los dos ya jugaron en el torneo"}


def main():
    out = {"generado": dt.date.today().isoformat(), "aprobado": "Alejandro, 9-oct-2026",
           "fuente": "trabajo/minar/2026-10-09_tanda3.md (K14 NBA z 3.97, T1 ATP z 3.87); coeficientes de utilidades/pesos_ausencias_minutos.py",
           "uso": "logit(p) += beta * x en plataforma.py; WTA no (T1 no paso en WTA)",
           "nba_K14": nba(), "atp_T1": atp()}
    ruta = os.path.join(os.path.dirname(AQUI), "modelos", "capas_ausencias_minutos.json")
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("escrito", ruta)


if __name__ == "__main__":
    main()
