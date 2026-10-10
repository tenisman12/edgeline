# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_hockey_ligas.py - los MISMOS angulos situacionales de NHL medidos en SHL, Liiga, AHL y DEL.

Hipotesis: las de NHL ya registradas (trabajo/minar/2026-10-08_situacionales_tanda1.md, 2026-10-09_cualitativos.md,
2026-10-09_tanda3.md a 2026-10-09_tanda6.md), con las mismas definiciones, signos y protocolo. Cada liga se mide sola,
contra su propio modelo as-of (modelos/hockey.py entrenado con esa liga). Nada se ajusta a mano.

  Ganador   H1-H22 (tanda 1), H23 (tanda 3), Q1-Q7 (cualitativos, con TMLE), S1-S8 (tanda 5).
            Fuera: H24 y TH5 (altitud de Colorado y Utah), H19/H20/TH7/port (porteros: estas fuentes no traen el titular)
            y P1-P3 (playoffs: solo fase regular).
  Totales   TH1-TH4, TH6, TH8 (tanda 4) y TS1, TS5-TS7 (tanda 5) contra el total esperado as-of.
  Equipo    ataque y defensa por equipo (tanda 6).

Escribe trabajo/minar/2026-10-10_hockey_ligas_resultados.json; nucleo/angulos.py lo lee con --catalogo.
Requiere numpy y scikit-learn (TMLE de los cualitativos), como minar_cualitativos.py.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_angulos_hockey_ligas.py
    python -m nucleo.angulos --catalogo
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, os, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_situacionales as M  # noqa: E402
import minar_cualitativos as Q  # noqa: E402
import minar_angulos_tanda4 as T4  # noqa: E402
import minar_angulos_tanda5 as T5  # noqa: E402
import minar_angulos_tanda6 as T6  # noqa: E402

LIGAS = ["SHL", "LIIGA", "AHL", "DEL"]
RUTA = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_hockey_ligas_resultados.json")
SIN_DATO = {"H19", "H20"}        # porteros: las fuentes de estas ligas no traen el titular


def defs_totales():
    """tanda 4 (NHL) sin TH5 (altitud) ni TH7 (portero)."""
    _i = T4._ind

    def th3(r, C):
        ph, pa = C.prev(r["home"], r["gp"]), C.prev(r["away"], r["gp"])
        if not ph or not pa or ph["ot"] is None or pa["ot"] is None: return None
        return _i(ph["ot"]) + _i(pa["ot"])

    def th4(r, C):
        ph, pa = C.prev(r["home"], r["gp"]), C.prev(r["away"], r["gp"])
        if not ph or not pa or ph["pim"] is None or pa["pim"] is None: return None
        return (ph["pim"] + pa["pim"]) / 10.0
    rest = lambda C, e, gp: C.descanso(e, gp)
    return [("TH1", "segunda noche (cuenta)", +1, lambda r, C: _i(rest(C, r["home"], r["gp"]) == 1) + _i(rest(C, r["away"], r["gp"]) == 1)),
            ("TH2", "carga de 7 dias (suma)", +1, lambda r, C: (C.en_ventana(r["home"], r["gp"], 7) or 0) + (C.en_ventana(r["away"], r["gp"], 7) or 0)),
            ("TH3", "prorroga en el anterior (cuenta)", +1, th3),
            ("TH4", "castigos del anterior (suma/10)", +1, th4),
            ("TH6", "gira del visitante 3+", +1, lambda r, C: _i((C.visitas_seguidas(r["away"], r["gp"]) or 0) >= 3)),
            ("TH8", "descanso largo de los dos (3+ dias)", -1,
             lambda r, C: _i((rest(C, r["home"], r["gp"]) or 0) >= 3 and (rest(C, r["away"], r["gp"]) or 0) >= 3))]


def liga(L, R):
    print("\n" + "#" * 100 + "\n# %s\n" % L + "#" * 100)
    n0 = len(M.RESULTADOS)
    M.correr_hockey(L)                                         # H1-H22 con su evaluador (se guardan en M.RESULTADOS)
    filas, C = M.ULTIMO[L]
    if not filas:
        print("  %s: sin partidos con prediccion as-of" % L); return
    for r in filas:
        r["H23"] = M._ind((C.en_ventana(r["away"], r["gp"], 5) or 0) >= 3) - M._ind((C.en_ventana(r["home"], r["gp"], 5) or 0) >= 3)
    print("\n%s tanda 3" % L)
    M.evaluar([dict(r, x=r["H23"]) for r in filas], "H23", "cuarto juego en 6 noches", L, +1)
    print("\n%s cualitativos" % L)
    Q.correr(L, filas, C, Q.ESP)                              # Q1-Q7 (tambien con M.evaluar) + TMLE
    print("\n%s tanda 5" % L)
    F5 = T5.construir("NHL", filas, C)                        # mismos parametros que NHL (margen 4, racha 5, frio 3, hueco 20)
    for cod, (nom, s) in T5.NOMBRES.items():
        if cod == "S9":
            continue
        rows = [dict(r, x=r.get(cod)) for r in F5 if r.get(cod) is not None]
        if rows:
            M.evaluar(rows, cod, nom, L, s)
    # estimacion con toda la muestra (para lo que moveria hoy): todos los de ganador de esta liga
    for out in M.RESULTADOS[n0:]:
        cod = out["codigo"]
        if cod in SIN_DATO:
            continue
        if cod.startswith("S"):
            rows = [dict(r, x=r.get(cod)) for r in F5 if r.get(cod) is not None]
        elif cod.startswith("Q"):
            continue                                            # Q: el TMLE de toda la muestra ya va en su resultado
        else:
            rows = [dict(r, x=r.get(cod)) for r in filas if r.get(cod) is not None]
        R["estimacion"].append(dict(T5.describir(rows, L), codigo=cod, angulo=out["angulo"]))
    R["ganador"] += [dict(x) for x in M.RESULTADOS[n0:] if x["codigo"] not in SIN_DATO]
    # totales
    print("\n%s totales" % L)
    ET = T4.esperado_total(C, filas, lambda e: L)
    base = [dict(fecha=r["fecha"], gp=r["gp"], E=ET[str(r["gp"])][0], T=ET[str(r["gp"])][1], _r=r) for r in filas if str(r["gp"]) in ET]
    print("  %s: %d partidos con total esperado as-of" % (L, len(base)))
    for cod, nom, s, fn in defs_totales():
        rows = []
        for b in base:
            try:
                x = fn(b["_r"], C)
            except (KeyError, TypeError):
                x = None
            if x is not None:
                rows.append(dict(b, x=x))
        R["totales"].append(T4.evaluar_total(rows, cod, nom, L, s))
    x5 = {str(r["gp"]): r for r in F5}
    for cod, (nom, s) in T5.TOT.items():
        rows = [dict(b, x=x5[str(b["gp"])].get(cod)) for b in base if str(b["gp"]) in x5 and x5[str(b["gp"])].get(cod) is not None]
        R["totales"].append(T4.evaluar_total(rows, cod, nom, L, s))
    # por equipo (tanda 6)
    print("\n%s por equipo" % L)
    FE = T6.filas_equipo("NHL", filas, C, {}, lambda e: L)
    print("  %s: %d filas de equipo" % (L, len(FE)))
    for c in sorted({c for r in FE for c in r["se"]}):
        if c in ("port", "alt"):
            continue
        nom, s_at, s_df = T6.DIR[c]
        if s_at is not None:
            R["equipos"].append(T6.evaluar([dict(r, x=r["se"].get(c)) for r in FE], c, nom, L, s_at, "ataque"))
        if s_df is not None:
            R["equipos"].append(T6.evaluar([dict(r, x=r["so"].get(c)) for r in FE], c, nom, L, s_df, "defensa"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas", default=",".join(LIGAS))
    a = ap.parse_args()
    R = {"ganador": [], "estimacion": [], "totales": [], "equipos": []}
    M.RESULTADOS.clear()
    for L in [x.strip().upper() for x in a.ligas.split(",") if x.strip()]:
        liga(L, R)
    k = sum(1 for x in R["ganador"] + R["totales"] + R["equipos"] if "z" in x)
    pasan = [x for x in R["ganador"] + R["totales"] + R["equipos"] if x.get("veredicto") == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d pruebas | falsos 'pasa' esperados por azar ~ %.1f | pasan: %d" % (k, 0.023 * k, len(pasan)))
    for x in pasan:
        print("  PASA %-5s %-44s %-6s %s z %+.2f" % (x["codigo"], x["angulo"][:44], x["liga"], x.get("lectura") or x.get("base"), x["z"]))
    out = dict(generado=dt.datetime.now().isoformat(timespec="seconds"),
               hipotesis="las de NHL (tandas 1, 3, 4, 5, 6 y cualitativos), mismas definiciones y protocolo, cada liga sola",
               k=k, falsos_esperados=round(0.023 * k, 1), **R)
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("resultados en", RUTA)


if __name__ == "__main__":
    main()
