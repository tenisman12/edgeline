# -*- coding: utf-8 -*-
"""
utilidades/validar_futbol_candidato.py - corre la validacion oficial de futbol (validar_futbol_mercados.py, sin cambiarle
nada mas) con el modelo de referencia y con un candidato (ELO K y olvido delta en las tasas de goles), y compara mercado por mercado.

No escribe salida/validacion_futbol.json: deja la comparacion en trabajo/minar/<fecha>_validacion_futbol_candidato.json.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/validar_futbol_candidato.py --k 40 --delta 0.98 --k0 20 --d0 1.0
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, os, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI)); sys.path.insert(0, AQUI)
from nucleo import io  # noqa: E402

def validador(K, DL):
    """El validador oficial lee F.K_ELO y F.OLVIDO (modelos/futbol.py); se fijan antes de cada corrida."""
    import importlib
    from modelos import futbol as F
    import validar_futbol_mercados as V
    importlib.reload(V)
    F.K_ELO = K; F.OLVIDO = DL
    return vars(V)


def correr(K, DL, meses):
    V = validador(K, DL)
    F = V["F"]
    juegos = F._juegos(None); ult = max(j[0] for j in juegos)
    desde = (dt.date.fromisoformat(ult) - dt.timedelta(days=30 * meses)).isoformat()
    cuotas = V["cargar_cuotas"]()
    ligas = sorted({r.get("league") for r in io.cargar_juegos("futbol", None) if r.get("league")})
    res = {}
    for liga in ligas:
        ac = V["liga_run"](liga, desde, cuotas); res[liga] = {}
        for k, filas in ac.d.items():
            if len(filas) < 50: continue
            res[liga][k] = V["resumen_marcador"](filas) if k == "marcador_exacto_ll" else V["resumen"](filas)
    return {"desde": desde, "hasta": ult, "ligas": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=40.0); ap.add_argument("--delta", type=float, default=0.98)
    ap.add_argument("--meses", type=int, default=24)
    ap.add_argument("--k0", type=float, default=None, help="K de referencia (por omision, el de modelos/futbol.py)")
    ap.add_argument("--d0", type=float, default=1.0, help="olvido de referencia cuando se da --k0")
    a = ap.parse_args()
    from modelos import futbol as FU
    k0, d0 = FU.K_ELO, FU.OLVIDO
    base = correr(a.k0, a.d0, a.meses) if a.k0 else correr(k0, d0, a.meses)
    cand = correr(a.k, a.delta, a.meses)
    FU.K_ELO, FU.OLVIDO = k0, d0
    print("VALIDACION FUTBOL: actual (K %.0f, olvido %.3f) contra candidato (K %.0f, olvido %.3f) | ventana %s a %s" % (
        a.k0 or k0, a.d0 if a.k0 else d0, a.k, a.delta, base["desde"], base["hasta"]))
    filas = []; cambios = {"gana": [], "pierde": []}; n_pub = [0, 0]; mejor = peor = 0
    for liga in sorted(base["ligas"]):
        print("\n== %s ==" % liga)
        print("  %-22s %6s | %8s %6s %-11s | %8s %6s %-11s" % ("MERCADO", "n", "skill", "z", "actual", "skill", "z", "candidato"))
        for k in sorted(base["ligas"][liga]):
            b = base["ligas"][liga][k]; c = cand["ligas"][liga].get(k)
            if not c: continue
            n_pub[0] += b["estado"] == "publicable"; n_pub[1] += c["estado"] == "publicable"
            mejor += c["skill"] > b["skill"]; peor += c["skill"] < b["skill"]
            marca = ""
            if b["estado"] != c["estado"]:
                marca = "  <- GANA" if c["estado"] == "publicable" else "  <- PIERDE"
                cambios["gana" if c["estado"] == "publicable" else "pierde"].append("%s %s" % (liga, k))
            print("  %-22s %6d | %+8.4f %6.2f %-11s | %+8.4f %6.2f %-11s%s" % (
                k, b["n"], b["skill"], b["z"], b["estado"], c["skill"], c["z"], c["estado"], marca))
            filas.append({"liga": liga, "mercado": k, "n": b["n"], "actual": b, "candidato": c})
    print("\nRESUMEN: publicables actual %d, candidato %d | skill sube en %d mercados y baja en %d" % (n_pub[0], n_pub[1], mejor, peor))
    print("  pasan a publicable: %s" % (", ".join(cambios["gana"]) or "ninguno"))
    print("  dejan de ser publicables: %s" % (", ".join(cambios["pierde"]) or "ninguno"))
    out = {"k": a.k, "delta": a.delta, "ventana": [base["desde"], base["hasta"]], "publicables": {"actual": n_pub[0], "candidato": n_pub[1]},
           "skill_sube": mejor, "skill_baja": peor, "cambios": cambios, "mercados": filas}
    ruta = os.path.join(os.path.dirname(AQUI), "trabajo", "minar", "%s_validacion_futbol_candidato.json" % dt.date.today().isoformat())
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(out, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
