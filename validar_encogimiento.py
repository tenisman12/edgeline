"""Compara el motor publicado con el prior candidato por liga, por trimestre.

Uso: EDGELINE_BASE=$PWD python validar_encogimiento.py [--cero] [liga ...]

Cada prediccion usa solo los resultados anteriores al primer dia del trimestre.
Los parametros del motor (incluida Platt) se vuelven a entrenar en ese prefijo.
Dentro del trimestre no hay actualizacion diaria: es una prueba aproximada de
sensibilidad, no el backtest final de publicacion. Las candidatas se exploraron
antes en datos que pueden solaparse: no llamar a 2026 test virgen.
"""
import json
import math
import os
import random
import sys
from unittest.mock import patch

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
from modelos import americano, futbol, hockey, nba
from nucleo import encogimiento


MOTORES = {"hockey": hockey, "americano": americano, "nba": nba, "futbol": futbol}
LIMITES = ("2025-01", "2025-04", "2025-07", "2025-10",
           "2026-01", "2026-04", "2026-07", "2026-10", "2027-01")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluar(deporte, liga, limites=LIMITES, candidato=None):
    motor = MOTORES[deporte]
    juegos = motor._juegos(liga)
    por_modo = {modo: [] for modo in ("publicado", "candidato")}
    ventanas = []
    for ini, fin in zip(limites, limites[1:]):
        pasado = [j for j in juegos if j[0] < ini]
        futuro = [j for j in juegos if ini <= j[0] < fin]
        if len(pasado) < 100 or not futuro:
            continue
        evaluables = []
        for fecha, gp, home, away in futuro:
            score_h = _f(home.get("goals") if deporte in ("hockey", "futbol") else home.get("points"))
            score_a = _f(home.get("goals_opp") if deporte in ("hockey", "futbol") else home.get("points_opp"))
            if score_h is None or score_a is None:
                continue
            if deporte != "futbol" and score_h == score_a == 0:
                continue
            if deporte != "futbol" and score_h == score_a:
                continue  # ganador binario requiere juego resuelto
            evaluables.append((fecha, home, away, score_h, score_a))
        if not evaluables:
            continue
        batch = {}
        for modo, referencia in (("publicado", False), ("candidato", True)):
            original_k = encogimiento.k
            def prior(d, l, referencia=False):
                if referencia and candidato is not None:
                    return float(candidato)
                return original_k(d, l, referencia)
            with patch.object(motor, "_juegos", return_value=pasado), patch.object(encogimiento, "k", prior):
                est = motor.entrenar(liga, referencia=referencia)
            filas = []
            for fecha, home, away, gh, ga in evaluables:
                kw = {"fecha": fecha} if deporte == "hockey" else {}
                pred = motor.predecir(est, home.get("team"), away.get("team"), **kw)
                if not pred:
                    continue
                p = ([pred["p_home"], pred["p_draw"], pred["p_away"]]
                     if deporte == "futbol" else [pred["p_home"], pred["p_away"]])
                y = (0 if gh > ga else 2 if deporte == "futbol" and ga > gh
                     else 1 if deporte == "futbol" else 1)
                xh = pred.get("xg_home", pred.get("pts_home"))
                xa = pred.get("xg_away", pred.get("pts_away"))
                total = pred.get("total", pred.get("total_esperado"))
                if None in (xh, xa, total):
                    continue
                p = [max(1e-6, min(1-1e-6, v)) for v in p]
                filas.append((fecha, home.get("team"), away.get("team"), gh, ga, p, y, xh, xa, total))
            batch[modo] = {(f, h, a): row for row in filas
                           for f, h, a, *_ in [row]}
        comun = batch["publicado"].keys() & batch["candidato"].keys()
        for modo in batch:
            por_modo[modo].extend(batch[modo][llave] for llave in sorted(comun))
        ventanas.append({"inicio": ini, "fin": fin, "n": len(comun)})
        print(liga, ini, len(comun), flush=True)

    def resumen(filas):
        if not filas:
            return {"n": 0}
        n = len(filas)
        return {"n": n,
                "brier": round(sum(sum((v-(i==y))**2 for i,v in enumerate(p))/len(p)
                                   for _,_,_,_,_,p,y,_,_,_ in filas)/n, 6),
                "logloss": round(sum(-math.log(p[y]) for _,_,_,_,_,p,y,_,_,_ in filas)/n, 6),
                "acierto": round(sum(p.index(max(p))==y for _,_,_,_,_,p,y,_,_,_ in filas)/n, 6),
                "mae_equipo": round(sum((abs(xh-gh)+abs(xa-ga))/2
                                        for _,_,_,gh,ga,_,_,xh,xa,_ in filas)/n, 6),
                "mae_total": round(sum(abs(total-gh-ga)
                                       for _,_,_,gh,ga,_,_,_,_,total in filas)/n, 6)}

    pub, cand = (resumen(por_modo[m]) for m in ("publicado", "candidato"))
    por_anio = {y: {m: resumen([r for r in por_modo[m] if r[0].startswith(y)])
                    for m in por_modo}
                for y in ("2025", "2026")}
    diferencia_diaria = {}
    for modo in por_modo:
        diferencia_diaria[modo] = {(r[0], r[1], r[2]): r for r in por_modo[modo]}
    dias = {}
    for llave in diferencia_diaria["publicado"].keys() & diferencia_diaria["candidato"].keys():
        a, b = (diferencia_diaria[m][llave] for m in ("publicado", "candidato"))
        def errores(r):
            _,_,_,gh,ga,p,y,xh,xa,total = r
            return (sum((v-(i==y))**2 for i,v in enumerate(p))/len(p),
                    (abs(xh-gh)+abs(xa-ga))/2, abs(total-gh-ga))
        av, bv = errores(a), errores(b)
        dias.setdefault(llave[0], []).append(tuple(v-u for u,v in zip(av,bv)))
    rng = random.Random(20261011)
    d = list(dias.values())
    intervalos = {}
    if d:
        draws = {k: [] for k in ("brier", "mae_equipo", "mae_total")}
        for _ in range(1000):
            elegido = rng.choices(d, k=len(d))
            plano = [e for dia in elegido for e in dia]
            for i, nombre in enumerate(draws):
                draws[nombre].append(sum(e[i] for e in plano)/len(plano))
        for nombre, muestras in draws.items():
            muestras.sort()
            intervalos[nombre] = [round(muestras[25], 6), round(muestras[974], 6)]
    prior = encogimiento.ficha(deporte, liga)
    if candidato is not None:
        prior["k_candidato"] = float(candidato)
    return {"liga": liga, "deporte": deporte, "prior": prior,
            "publicado": pub, "candidato": cand,
            "delta_candidato_menos_publicado":
                {k: round(cand[k]-pub[k], 6) for k in ("brier", "logloss", "acierto", "mae_equipo", "mae_total")}
                if pub["n"] else {}, "ventanas": ventanas,
            "por_anio": por_anio, "ic95_delta_por_fecha": intervalos,
            "nota": "Candidato exploratorio: ventanas trimestrales; seleccion previa de k no independiente."}


def main():
    os.makedirs(os.path.join(RAIZ, "trabajo"), exist_ok=True)
    cero = "--cero" in sys.argv
    ligas = [l for l in sys.argv[1:] if l != "--cero"] or [l for d in MOTORES for l in encogimiento.CANDIDATOS.get(d, {})]
    out = []
    for liga in ligas:
        deporte = next((d for d in MOTORES if liga in encogimiento.CANDIDATOS.get(d, {})), None)
        if not deporte:
            raise ValueError("Liga sin candidato: " + liga)
        out.append(evaluar(deporte, liga, candidato=0 if cero else None))
        archivo = "encogimiento_cero_resultados.json" if cero else "encogimiento_modelo_resultados.json"
        destino = os.path.join(RAIZ, "trabajo", archivo)
        with open(destino, "w", encoding="utf8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
