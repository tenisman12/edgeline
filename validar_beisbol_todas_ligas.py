"""Compara el motor de béisbol por liga con entrenamiento anterior a 2025.

Uso: EDGELINE_BASE=$PWD python validar_beisbol_todas_ligas.py

El candidato k=100 común es exploratorio. KBO=200 y NPB=150 proceden de
investigación anterior y su selección no es independiente de este periodo.
El ejercicio no incluye parque, clima, abridores, mercado ni probabilidad O/U.
"""
import json
import math
import os
import random
from collections import defaultdict

from modelos import beisbol as B
from nucleo import capa_totales as CT, features as F, io

LIGAS = ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl")
K_PREVIO = {"mlb": 100, "npb": 150, "kbo": 200, "lmp": 100}
CORTE = "2025-01-01"


def media(xs):
    return sum(xs) / len(xs) if xs else None


def datos_reales(liga):
    juegos = F._emparejar(io.cargar_juegos("beisbol", liga))
    return [(f.isoformat(), h["team"], a["team"], F._f(h.get("runs")) + F._f(a.get("runs")))
            for f, _, h, a in juegos if F._f(h.get("runs")) is not None
            and F._f(a.get("runs")) is not None
            and (F._f(h.get("runs")) or F._f(a.get("runs")))]


def evaluar(liga, k, reales):
    filas, saltados = F.construir("beisbol", liga, encogimiento_carreras=k)
    train = [r for r in filas if r["game_date"] < CORTE]
    test = [r for r in filas if CORTE <= r["game_date"] < "2027-01-01" and r["marg_home"] != 0]
    if len(train) < 50 or len(test) < 20:
        return {"k": k, "n_train": len(train), "n_test": len(test), "insuficiente": True}
    modelo = B.entrenar_logistica(train)
    ritmo = CT.Ritmo(reales)
    datos_capa, estados = [], {}
    for r in filas:
        st = ritmo.estado(r["game_date"], r["home"], r["away"])
        if st is None:
            continue
        h, a = B.carreras_esperadas(r)
        if h is None:
            continue
        if r["game_date"] < CORTE:
            datos_capa.append((h + a, r["total"], *st, r["game_date"]))
        else:
            estados[(r["game_date"], str(r["gamePk"]))] = st
    if len(datos_capa) < 50:
        return {"k": k, "n_train": len(train), "n_test": len(test), "n_capa": len(datos_capa), "insuficiente": True}
    coef, _ = CT.entrenar(datos_capa)
    out = {}
    for r in test:
        ident = (r["game_date"], str(r["gamePk"]))
        st = estados.get(ident)
        if st is None:
            continue
        p = min(max(B.prob(modelo, r), 1e-6), 1 - 1e-6)
        h, a = B.carreras_esperadas(r)
        t = CT.total(coef, h + a, *st)
        ch, ca = B.ajustar_carreras(h, a, p)
        fh, fa = t * ch / (h + a), t * ca / (h + a)
        gh = (r["total"] + r["marg_home"]) / 2
        ga = (r["total"] - r["marg_home"]) / 2
        y = r["y_home"]
        out[ident] = {
            "brier": (p - y) ** 2,
            "logloss": -math.log(p if y else 1 - p),
            "acierto": int((p >= .5) == bool(y)),
            "mae_equipo_base": (abs(h - gh) + abs(a - ga)) / 2,
            "mae_total_base": abs(h + a - r["total"]),
            "mae_equipo_final": (abs(fh - gh) + abs(fa - ga)) / 2,
            "mae_total_final": abs(t - r["total"]),
        }
    return {"k": k, "n_train": len(train), "n_test": len(test), "n_capa": len(datos_capa),
            "saltados": saltados, "out": out}


def resumen(base, otro, seed):
    ids = sorted(set(base["out"]) & set(otro["out"]))
    campos = next(iter(base["out"].values())).keys()
    por_fecha = defaultdict(list)
    for ident in ids:
        por_fecha[ident[0]].append(ident)
    dias = list(por_fecha.values())
    rng = random.Random(seed)
    muestras = [rng.choices(dias, k=len(dias)) for _ in range(500)]
    def red(x): return round(x, 6)
    ans = {"n_comun": len(ids), "n_dias": len(dias), "base": {}, "candidato": {}, "delta": {}, "por_anio": {}}
    for campo in campos:
        dif = {i: otro["out"][i][campo] - base["out"][i][campo] for i in ids}
        ci = sorted(sum(dif[i] for d in draw for i in d) / sum(len(d) for d in draw)
                    for draw in muestras)
        ans["base"][campo] = red(media([base["out"][i][campo] for i in ids]))
        ans["candidato"][campo] = red(media([otro["out"][i][campo] for i in ids]))
        ans["delta"][campo] = {"media": red(media(list(dif.values()))),
                               "ic95_fecha": [red(ci[12]), red(ci[487])]}
    for year in ("2025", "2026"):
        j = [i for i in ids if i[0].startswith(year)]
        ans["por_anio"][year] = {"n": len(j), "delta_brier": red(media([otro["out"][i]["brier"] - base["out"][i]["brier"] for i in j])) if j else None,
                                 "delta_mae_total_final": red(media([otro["out"][i]["mae_total_final"] - base["out"][i]["mae_total_final"] for i in j])) if j else None}
    return ans


def main():
    resultado = {"corte": CORTE, "ligas": {}, "metodo": "Variables as-of; logística y capa de total ajustadas por k con partidos anteriores a 2025; test 2025-26, con IC bootstrap por fecha. No parque/clima/abridores/mercado/O-U. Candidatos exploratorios, elegidos antes de este cálculo, pero algunos proceden de exploración solapada."}
    for liga in LIGAS:
        reales = datos_reales(liga)
        if not reales:
            raise RuntimeError(f"Sin juegos históricos para {liga}; comprueba EDGELINE_BASE")
        ks = list(dict.fromkeys((6, 0, 100, K_PREVIO.get(liga, 100))))
        resultados = {k: evaluar(liga, k, reales) for k in ks}
        base = resultados[6]
        comparaciones = {}
        for k in ks:
            if k == 6:
                continue
            x = resultados[k]
            if "out" in x and "out" in base:
                comparaciones[str(k)] = resumen(base, x, 20261011 + k)
            else:
                comparaciones[str(k)] = {"insuficiente": True}
        resultado["ligas"][liga] = {"k_comparados": ks, "n_train": base["n_train"],
                                    "n_test": base["n_test"], "n_capa": base.get("n_capa"),
                                    "comparaciones": comparaciones}
        print(liga, base["n_test"], {k: (v.get("delta", {}).get("brier", {}).get("media"),
                                      v.get("delta", {}).get("mae_total_final", {}).get("media"))
                                    for k, v in comparaciones.items()}, flush=True)
    destino = os.path.join(os.path.dirname(__file__), "modelos", "validacion_beisbol_todas_ligas_2026.json")
    with open(destino, "w", encoding="utf8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print("Guardado", destino)


if __name__ == "__main__":
    main()
