"""Prueba MLB k=6/100 tras capa de total entrenada solo hasta 2024.

EDGELINE_BASE=$PWD python validar_mlb_capa.py
No reproduce ajustes de clima/parque ni otros mercados de plataforma.py.
"""
import json
import os
import random
from collections import defaultdict

from modelos import beisbol as B
from nucleo import features as F, io, capa_totales as CT


def partidos():
    juegos = F._emparejar(io.cargar_juegos("beisbol", "mlb"))
    return [(f.isoformat(), gp, h.get("team"), a.get("team"),
             (F._f(h.get("runs")) or 0) + (F._f(a.get("runs")) or 0))
            for f, gp, h, a in juegos if F._f(h.get("runs")) is not None
            and F._f(a.get("runs")) is not None
            and (F._f(h.get("runs")) or F._f(a.get("runs")))]


def evaluar(k, partidos_):
    filas, _ = F.construir("beisbol", "mlb", encogimiento_carreras=k)
    train_win = [r for r in filas if int(r["season"]) < 2025 and int(r["season"]) != 2023]
    modelo = B.entrenar_logistica(train_win)
    ritmo = CT.Ritmo([(f,h,a,t) for f, _,h,a,t in partidos_])
    referencia = {}
    train = []
    for r in filas:
        f = r["game_date"]
        if f < "2022-01-01":
            continue
        st = ritmo.estado(f, r["home"], r["away"])
        if not st:
            continue
        h,a = B.carreras_esperadas(r)
        if f < "2025-01-01":
            train.append((h+a,r["total"],*st,f))
        elif f < "2027-01-01" and r["marg_home"] != 0:
            referencia[(r["season"],str(r["gamePk"]))] = (r,h,a,st)
    coef, _ = CT.entrenar(train)
    out = {}
    for llave,(r,h,a,(M,E)) in referencia.items():
        t = CT.total(coef,h+a,M,E)
        # Igual que plataforma._pred: sus dos marcadores se escalan al total.
        ch, ca = B.ajustar_carreras(h,a,B.prob(modelo,r))
        ph, pa = t*ch/(h+a),t*ca/(h+a)
        real_h = (r["total"]+r["marg_home"])/2
        real_a = (r["total"]-r["marg_home"])/2
        out[llave] = (r["game_date"],abs(t-r["total"]),
                     (abs(ph-real_h)+abs(pa-real_a))/2)
    return {"k":k,"train_capa":len(train),"train_ganador":len(train_win),"coef":coef,"out":out}


def main():
    pp=partidos()
    a,b=evaluar(6,pp),evaluar(100,pp)
    comunes=sorted(a["out"].keys() & b["out"].keys())
    rng=random.Random(20261011)
    resultado={"metodo":"Coeficiente y nivel de capa ajustados por separado hasta 2024; misma prueba 2025-26. Sin clima/parque, ni capa de Over/Under.",
               "n":len(comunes),"train_capa":{str(k):v["train_capa"] for k,v in ((6,a),(100,b))},
               "train_ganador":{str(k):v["train_ganador"] for k,v in ((6,a),(100,b))},
               "por_anio":{},"diferencia_k100_menos_k6":{}}
    for yy in ("2025","2026"):
        j=[k for k in comunes if a["out"][k][0].startswith(yy)]
        resultado["por_anio"][yy]={"n":len(j)}
        for nombre,i in (("mae_total",1),("mae_equipo",2)):
            resultado["por_anio"][yy][nombre]={"k6":sum(a["out"][k][i] for k in j)/len(j),
                                                "k100":sum(b["out"][k][i] for k in j)/len(j)}
    por_dia=defaultdict(list)
    for k in comunes:
        x,y=a["out"][k],b["out"][k]
        por_dia[x[0]].append((y[1]-x[1],y[2]-x[2]))
    dias=list(por_dia.values())
    for nombre,i in (("mae_total",0),("mae_equipo",1)):
        delta=[b["out"][k][i+1]-a["out"][k][i+1] for k in comunes]
        draws=[]
        for _ in range(1000):
            muestras=[x for dia in rng.choices(dias,k=len(dias)) for x in dia]
            draws.append(sum(x[i] for x in muestras)/len(muestras))
        draws.sort()
        resultado["diferencia_k100_menos_k6"][nombre]={"media":sum(delta)/len(delta),
                    "ic95_por_dia":[draws[25],draws[974]]}
    destino=os.path.join(os.path.dirname(__file__),"modelos","validacion_mlb_capa_2026.json")
    with open(destino,"w",encoding="utf8") as f:
        json.dump(resultado,f,ensure_ascii=False,indent=2)
    print(json.dumps(resultado,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
