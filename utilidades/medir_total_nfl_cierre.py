# -*- coding: utf-8 -*-
"""
utilidades/medir_total_nfl_cierre.py - mide el Over/Under de la NFL de produccion (modelos/americano.py) contra la
LINEA DE CIERRE del mercado (datos/mercado/nfl_lineas.csv, columna total_line). 18-oct-2026.

Motivo: revision.py marco en rojo "NFL Total: prometio 59.3% y acerto 41.0% en 39 casos (z -2.32)". La validacion
oficial (validar_mercados.py) dio el O/U de NFL como publicable porque compara contra la tasa historica, no contra la
linea de la casa. Lo que se apuesta es contra la linea de la casa.

Hipotesis y criterio (escritos antes de correr): si el modelo tiene ventaja contra el cierre, (a) elige el lado correcto
en mas del 50 % de los partidos con z >= 2 y (b) su p_over le gana en log loss a p = 0.5 con z >= 2 y en las dos mitades.
Si no cumple, el Total de NFL deja de ser publicable (no genera pick); el modelo y su lectura se siguen mostrando.

Reproduce produccion en una sola pasada as-of (cada partido se predice con lo anterior): ELO y ataque/defensa de
americano.py, sesgo y desviacion del total con los ultimos VENT_TOT residuos (>= 150), p_over = 1 - Phi((linea - total)/sd).

Uso:
    python utilidades/medir_total_nfl_cierre.py
Escribe trabajo/minar/2026-10-18_total_nfl_cierre.json. Solo stdlib.
"""
import io as _io, json, math, os, sys
import csv

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO)
from nucleo import io  # noqa: E402
from modelos import americano as A  # noqa: E402

RUTA_OUT = os.path.join(CODIGO, "trabajo", "minar", "2026-10-18_total_nfl_cierre.json")


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _z_dif(d):
    n = len(d)
    if n < 2:
        return None
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return None if sd == 0 else m / sd * math.sqrt(n)


def pasada():
    lineas = {}
    with _io.open(io.ruta("datos", "mercado", "nfl_lineas.csv"), encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                lineas[r["game_id"]] = float(r["total_line"])
            except (TypeError, ValueError, KeyError):
                pass
    eq = {}; tot = 0.0; ng = 0; lg = 22.0; rt = []; out = []
    for f, gp, h, a in A._juegos("NFL"):
        ph = A._f(h.get("points")); pa = A._f(h.get("points_opp"))
        if ph is None or pa is None:
            continue
        th = eq.setdefault(h.get("team"), A.Eq()); ta = eq.setdefault(a.get("team"), A.Eq())
        for t in (th, ta):
            if t.ult and t.ult != f[:4]:
                t.elo = A.BASE_ELO + (t.elo - A.BASE_ELO) * A.REGR
            t.ult = f[:4]
        base = (th.of(lg) + ta.of(lg) + th.df(lg) + ta.df(lg)) / 2
        if th.n >= 4 and ta.n >= 4:
            v = rt[-A.VENT_TOT:]
            lin = lineas.get(gp)
            if len(v) >= 150 and lin is not None and ph + pa != lin:
                m = sum(v) / len(v); sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
                total = base + m
                p = 1 - A._cdf((lin - total) / sd)
                out.append({"fecha": f, "id": gp, "total": total, "linea": lin, "p_over": p, "y": 1 if ph + pa > lin else 0})
            rt.append((ph + pa) - base)
        esp = A._sig((th.elo + A.HFA - ta.elo) / (A.ESCALA / math.log(10)))
        res = 1.0 if ph > pa else (0.0 if ph < pa else .5)
        d = A.K * math.log(abs(ph - pa) + 1) * (res - esp); th.elo += d; ta.elo -= d
        th.pf += ph; th.pa += pa; th.n += 1; ta.pf += pa; ta.pa += ph; ta.n += 1
        tot += ph + pa; ng += 2; lg = tot / ng
    return out


def resumen(v):
    n = len(v)
    lado = [1 if (x["p_over"] > .5) == (x["y"] == 1) else 0 for x in v]
    ac = sum(lado) / n
    z_lado = (ac - .5) / math.sqrt(.25 / n)
    d = [_ll(.5, x["y"]) - _ll(x["p_over"], x["y"]) for x in v]   # > 0: el modelo le gana a p = 0.5
    mit = n // 2
    return {"n": n, "desde": v[0]["fecha"], "hasta": v[-1]["fecha"],
            "acierto_lado_pct": round(100 * ac, 1), "z_lado": round(z_lado, 2),
            "p_lado_media_pct": round(100 * sum(max(x["p_over"], 1 - x["p_over"]) for x in v) / n, 1),
            "dif_total_linea_media": round(sum(abs(x["total"] - x["linea"]) for x in v) / n, 2),
            "logloss_vs_50_milesimas": round(1000 * sum(d) / n, 2), "z_logloss": round(_z_dif(d) or 0, 2),
            "mitades_milesimas": [round(1000 * sum(d[:mit]) / mit, 2), round(1000 * sum(d[mit:]) / (n - mit), 2)]}


def main():
    v = pasada()
    if not v:
        print("sin partidos con linea de cierre"); return 1
    res = {"generado": "2026-10-18", "liga": "NFL", "mercado": "Total contra la linea de cierre",
           "todo": resumen(v),
           "desde_2023": resumen([x for x in v if x["fecha"] >= "2023-08-01"]),
           "por_temporada": {}}
    for t in sorted(set(x["fecha"][:4] for x in v)):
        s = [x for x in v if x["fecha"][:4] == t]
        if len(s) >= 50:
            res["por_temporada"][t] = resumen(s)
    a, b = res["todo"], res["desde_2023"]
    pasa = (a["z_lado"] >= 2.0 and b["z_logloss"] >= 2.0 and min(b["mitades_milesimas"]) > 0)
    res["veredicto"] = "pasa" if pasa else "no pasa"
    os.makedirs(os.path.dirname(RUTA_OUT), exist_ok=True)
    with _io.open(RUTA_OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("todo", "desde_2023", "veredicto")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
