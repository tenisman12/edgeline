# -*- coding: utf-8 -*-
"""
utilidades/evaluar_lmp_carreras.py - que tan preciso es el modelo de CARRERAS de LMP por temporada.

Usa lo mismo que produccion, juego por juego y sin ver el futuro:
  - motor de carreras (nucleo/motor_carreras.py, parametros de modelos/motor_carreras.json): carreras esperadas de cada
    equipo con Kalman + abridor + parque; en LMP es el que pone el total esperado y las carreras por equipo.
  - capa de totales de produccion (utilidades/motor_carreras.produccion: logistica media3 + capa con bloques anteriores);
    en LMP es la que decide el Over/Under.
  - referencia ingenua: el promedio de carreras de todos los juegos anteriores.
Por temporada: error medio del total (MAE) y sesgo, carreras por equipo, y Over/Under a la linea .5 mas cercana al
promedio previo (como el validador): acierto del lado que marca cada uno, Brier y calibracion.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    git pull
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/evaluar_lmp_carreras.py                  # temporadas 2024-25 y 2025-26
    python utilidades/evaluar_lmp_carreras.py --temporadas 2022,2023,2024,2025
Escribe salida/evaluacion_lmp_carreras.json.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, io as _io, json, math, os, sys
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
from nucleo import io  # noqa: E402
from nucleo import motor_carreras as MC  # noqa: E402
import motor_carreras as UM  # noqa: E402  (utilidades/motor_carreras.py: produccion reproducida)


def temporada(f):
    d = dt.date.fromisoformat(f[:10])
    return str(d.year if d.month >= 8 else d.year - 1)


def _z(d):
    n = len(d)
    if n < 30:
        return None
    m = sum(d) / n; sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
    return round(m / sd * n ** 0.5, 2) if sd > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temporadas", default="2024,2025")
    a = ap.parse_args()
    quiero = {t.strip() for t in a.temporadas.split(",") if t.strip()}
    cfg = json.load(_io.open(os.path.join(CODIGO, "modelos", "motor_carreras.json"), encoding="utf-8"))["ligas"]["lmp"]
    prm, r_nb = cfg["parametros"], cfg.get("r_nb", 4)
    G = MC.juegos("LMP")
    ABR = UM.abridores_rel("LMP", G); PQD = MC.parques_delta("LMP", G)
    pred = MC.correr(G, prm, ABR, PQD, r_nb)
    P = UM.produccion("LMP")
    print("LMP: %d juegos; motor con %s (r %s); produccion reproducida %d (con capa %d)" % (
        len(G), prm, r_nb, len(P), sum(1 for v in P.values() if "t_capa" in v)))
    acum = [0.0, 0.0, 0.0, 0]
    filas = []
    for g in G:
        tot = g["rh"] + g["ra"]
        if acum[3] >= 300 and g["gp"] in pred and g["gp"] in P and temporada(g["f"]) in quiero:
            base = acum[0] / acum[3]; Lm = UM.medio(base)
            leq = (UM.medio(acum[1] / acum[3]), UM.medio(acum[2] / acum[3]))
            lh, la = pred[g["gp"]][:2]
            mk = MC.mercados(lh, la, r_nb, [Lm], leq)
            pp = P[g["gp"]]
            fila = dict(t=temporada(g["f"]), f=g["f"], rh=g["rh"], ra=g["ra"], tot=tot, base=base, base_h=acum[1] / acum[3],
                        base_a=acum[2] / acum[3], L=Lm, lh=lh, la=la, p_over_motor=mk["over"][Lm], t_prod=pp["xh"] + pp["xa"])
            if "t_capa" in pp:
                fila["t_capa"] = pp["t_capa"]
                fila["p_over_capa"] = min(max(sum(1 for e in pp["res_capa"] if pp["t_capa"] + e > Lm) / len(pp["res_capa"]), 0.01), 0.99)
            filas.append(fila)
        acum[0] += tot; acum[1] += g["rh"]; acum[2] += g["ra"]; acum[3] += 1
    res = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "parametros_motor": prm, "temporadas": {}}
    for t in sorted(quiero) + ["todas"]:
        L = [x for x in filas if t == "todas" or x["t"] == t]
        L = [x for x in L if "t_capa" in x]
        if not L:
            continue
        n = len(L); L.sort(key=lambda x: x["f"]); h = n // 2
        o = {"n": n, "carreras_por_juego": round(sum(x["tot"] for x in L) / n, 2)}
        for nombre, k in (("motor", "mot"), ("capa_produccion", "t_capa"), ("modelo_sin_capa", "t_prod"), ("promedio_previo", "base")):
            pr = [(x["lh"] + x["la"]) if k == "mot" else x[k] for x in L]
            err = [abs(p - x["tot"]) for p, x in zip(pr, L)]
            o["total_" + nombre] = {"esperado_medio": round(sum(pr) / n, 2), "mae": round(sum(err) / n, 3),
                                    "sesgo": round(sum(p - x["tot"] for p, x in zip(pr, L)) / n, 2)}
        d = [abs(x["base"] - x["tot"]) - abs(x["lh"] + x["la"] - x["tot"]) for x in L]
        o["total_motor"]["mejora_mae_vs_promedio"] = round(sum(d) / n, 3); o["total_motor"]["z"] = _z(d)
        o["total_motor"]["mitades"] = [round(sum(d[:h]) / max(h, 1), 3), round(sum(d[h:]) / max(n - h, 1), 3)]
        d2 = [abs(x["t_capa"] - x["tot"]) - abs(x["lh"] + x["la"] - x["tot"]) for x in L]
        o["total_motor"]["mejora_mae_vs_capa"] = round(sum(d2) / n, 3); o["total_motor"]["z_vs_capa"] = _z(d2)
        for lado, kr, kl, kb in (("local", "rh", "lh", "base_h"), ("visita", "ra", "la", "base_a")):
            em = [abs(x[kl] - x[kr]) for x in L]; eb = [abs(x[kb] - x[kr]) for x in L]
            o["carreras_" + lado] = {"real_media": round(sum(x[kr] for x in L) / n, 2), "esperado_motor": round(sum(x[kl] for x in L) / n, 2),
                                     "mae_motor": round(sum(em) / n, 3), "mae_promedio": round(sum(eb) / n, 3),
                                     "z": _z([b - m for b, m in zip(eb, em)])}
        # Over/Under a la linea .5 cercana al promedio previo (sin push)
        U = [x for x in L if x["tot"] != x["L"]]
        lineas = defaultdict(int)
        for x in U:
            lineas[x["L"]] += 1
        o["over_under"] = {"n": len(U), "lineas_usadas": dict(sorted(lineas.items())),
                           "over_real_pct": round(100 * sum(x["tot"] > x["L"] for x in U) / len(U), 1)}
        for nombre, k in (("capa_produccion", "p_over_capa"), ("motor", "p_over_motor")):
            ac = sum((x[k] >= 0.5) == (x["tot"] > x["L"]) for x in U) / len(U)
            br = sum((x[k] - (1 if x["tot"] > x["L"] else 0)) ** 2 for x in U) / len(U)
            fuertes = [x for x in U if abs(x[k] - 0.5) >= 0.05]
            acf = (sum((x[k] >= 0.5) == (x["tot"] > x["L"]) for x in fuertes) / len(fuertes)) if fuertes else None
            cal = defaultdict(lambda: [0, 0.0, 0])
            for x in U:
                pf = max(x[k], 1 - x[k]); yf = (x["tot"] > x["L"]) if x[k] >= 0.5 else (x["tot"] < x["L"])
                b = "50-55" if pf < .55 else ("55-60" if pf < .60 else ("60-65" if pf < .65 else "65+"))
                cal[b][0] += 1; cal[b][1] += pf; cal[b][2] += yf
            o["over_under"][nombre] = {"acierto_pct": round(100 * ac, 1), "brier": round(br, 4),
                                       "acierto_con_5pp_o_mas_pct": round(100 * acf, 1) if acf is not None else None,
                                       "n_con_5pp_o_mas": len(fuertes),
                                       "calibracion": {b: {"n": v[0], "p_media": round(100 * v[1] / v[0], 1), "real": round(100 * v[2] / v[0], 1)}
                                                       for b, v in sorted(cal.items())}}
        res["temporadas"][t] = o
        print("\n=== temporada %s (n %d, %.2f carreras por juego)" % (t, n, o["carreras_por_juego"]))
        for k in ("total_motor", "total_capa_produccion", "total_modelo_sin_capa", "total_promedio_previo"):
            print("  %-24s %s" % (k, o[k]))
        print("  carreras_local           %s" % o["carreras_local"])
        print("  carreras_visita          %s" % o["carreras_visita"])
        ou = o["over_under"]
        print("  over/under: n %d, lineas %s, over salio %.1f%%" % (ou["n"], ou["lineas_usadas"], ou["over_real_pct"]))
        for k in ("capa_produccion", "motor"):
            print("    %-16s %s" % (k, ou[k]))
    os.makedirs(os.path.join(CODIGO, "salida"), exist_ok=True)
    json.dump(res, _io.open(os.path.join(CODIGO, "salida", "evaluacion_lmp_carreras.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nresumen en salida/evaluacion_lmp_carreras.json")


if __name__ == "__main__":
    main()
