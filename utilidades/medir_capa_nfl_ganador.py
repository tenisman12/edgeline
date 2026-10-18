# -*- coding: utf-8 -*-
"""
utilidades/medir_capa_nfl_ganador.py - mide el ganador de NFL de produccion con y sin la capa L5 + EPA
(plataforma._ajuste_capas_nfl) en walk-forward. 18-oct-2026.

Motivo: revision.py marco en rojo "NFL Ganador: prometio 68.0% y acerto 52.5% en 40 casos (z -2.09)". La validacion
oficial (validar_mercados.py) mide americano.entrenar SIN la capa; produccion le suma la capa en logit encima de la p ya
calibrada con Platt. Los pesos de la capa (L5 0.93, EPA neto x10 0.187) se midieron sobre el ELO crudo.

Hipotesis y criterio (antes de correr): la capa sirve si (a) mejora el log loss con z >= 2 y en las dos mitades y
(b) la p con capa queda calibrada (|promete - acierta| <= 4 % en el favorito). Si no, la capa pasa a contexto.
Ademas se prueba el peso de la capa reajustado por temporada (logit p = logit p0 + c * capa, c elegido con lo anterior).

Walk-forward: americano.entrenar("NFL") con lo anterior a cada bloque de 30 dias desde 2019-09; la capa se calcula as-of
con datos/americano.csv y datos/equipos/nfl_equipos.csv igual que plataforma._capas_nfl.

Uso:
    python utilidades/medir_capa_nfl_ganador.py
Escribe trabajo/minar/2026-10-18_capa_nfl_ganador.json. Solo stdlib.
"""
import bisect, collections, csv, datetime as dt, io as _io, json, math, os, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO)
from nucleo import io  # noqa: E402
from modelos import americano as A  # noqa: E402

RUTA_OUT = os.path.join(CODIGO, "trabajo", "minar", "2026-10-18_capa_nfl_ganador.json")


def _lo(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _sg(z):
    return 1 / (1 + math.exp(-z))


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -math.log(p if y else 1 - p)


def predicciones():
    todos = A._juegos("NFL"); orig = A._juegos; out = []
    d, fin = dt.date(2019, 9, 1), dt.date.today() + dt.timedelta(days=1)
    try:
        while d < fin:
            d2 = d + dt.timedelta(days=30); c, c2 = d.isoformat(), d2.isoformat()
            blk = [g for g in todos if c <= g[0] < c2]
            if blk:
                A._juegos = lambda liga=None, c=c: [g for g in todos if g[0] < c]
                est = A.entrenar("NFL")
                for f, gp, h, a in blk:
                    ph, pa = A._f(h.get("points")), A._f(h.get("points_opp"))
                    if ph is None or pa is None or ph == pa:
                        continue
                    r = A.predecir(est, h.get("team"), a.get("team"))
                    if r:
                        out.append({"fecha": f, "id": gp, "home": h.get("team"), "away": a.get("team"),
                                    "week": int(float(h.get("week") or 0)), "p0": r["p_home"], "y": 1 if ph > pa else 0})
            d = d2
    finally:
        A._juegos = orig
    return out


def capas():
    por = collections.defaultdict(list)
    with _io.open(io.ruta("datos", "americano.csv"), encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("league") or "").upper() != "NFL":
                continue
            try:
                pf, pa = float(r["points"]), float(r["points_opp"])
            except (TypeError, ValueError, KeyError):
                continue
            if pf != pa:
                por[r.get("team")].append(((r.get("game_date") or "")[:10], str(r.get("season") or "")[:4], pf, pa))
    epa, porte = {}, collections.defaultdict(list)
    ruta = io.ruta("datos", "equipos", "nfl_equipos.csv")
    if os.path.exists(ruta):
        with _io.open(ruta, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    jug = sum(float(r.get(k) or 0) for k in ("attempts", "carries", "sacks_suffered"))
                    e = float(r.get("passing_epa") or 0) + float(r.get("rushing_epa") or 0)
                except ValueError:
                    continue
                v = {"season": str(r.get("season") or "")[:4], "fecha": (r.get("game_date") or "")[:10], "opp": r.get("opp"), "jug": jug, "epa": e}
                epa[(r.get("game_id"), r.get("team"))] = v; porte[r.get("team")].append((v["fecha"], r.get("game_id"), v))
    for t in por: por[t].sort()
    for t in porte: porte[t].sort(key=lambda x: x[0])

    def una(t, f):
        rows = por.get(t, []); rows = rows[:bisect.bisect_left(rows, (f,))]
        if not rows:
            return None
        u5 = rows[-5:]; se = rows[-1][1]; temp = [x for x in rows if x[1] == se]
        prop = [(g, v) for (fe, g, v) in porte.get(t, []) if fe < f and v["season"] == se]
        of = sum(v["epa"] for _, v in prop); jo = sum(v["jug"] for _, v in prop)
        perm = [x for x in (epa.get((g, v["opp"])) for g, v in prop) if x]
        df = sum(x["epa"] for x in perm); jd = sum(x["jug"] for x in perm)
        return {"l5": sum(1 for x in u5 if x[2] > x[3]) / len(u5),
                "epa": ((of / jo) - (df / jd)) if (len(prop) >= 4 and jo and jd) else None,
                "dif": sum(x[2] - x[3] for x in temp) / len(temp) if len(temp) >= 5 else None}

    def shift(h, a, f):
        ch, ca = una(h, f), una(a, f)
        if not ch or not ca:
            return 0.0
        dl5 = ch["l5"] - ca["l5"]
        if ch["epa"] is not None and ca["epa"] is not None:
            return 0.93 * dl5 + 0.187 * (ch["epa"] - ca["epa"]) * 10.0
        dd = (ch["dif"] - ca["dif"]) if (ch["dif"] is not None and ca["dif"] is not None) else 0.0
        return 1.021 * dl5 + 0.043 * dd
    return shift


def calib(v, k):
    n = len(v); P = [(max(x[k], 1 - x[k]), x["y"] if x[k] >= .5 else 1 - x["y"]) for x in v]
    e = sum(p for p, _ in P); a = sum(q for _, q in P); var = sum(p * (1 - p) for p, _ in P)
    return {"n": n, "promete_pct": round(100 * e / n, 1), "acierta_pct": round(100 * a / n, 1), "z": round((a - e) / math.sqrt(var), 2),
            "logloss": round(sum(_ll(x[k], x["y"]) for x in v) / n, 4)}


def mejora(d):
    n = len(d); m = sum(d) / n; s = math.sqrt(sum((q - m) ** 2 for q in d) / (n - 1)); h = n // 2
    return {"n": n, "milesimas": round(1000 * m, 2), "z": round(m / s * math.sqrt(n), 2),
            "mitades": [round(1000 * sum(d[:h]) / h, 2), round(1000 * sum(d[h:]) / (n - h), 2)]}


def main():
    v = predicciones(); sh = capas()
    for x in v:
        x["sh"] = sh(x["home"], x["away"], x["fecha"]); x["p1"] = _sg(_lo(x["p0"]) + x["sh"])
    res = {"generado": dt.date.today().isoformat(), "liga": "NFL", "mercado": "Ganador",
           "sin_capa": calib(v, "p0"), "con_capa": calib(v, "p1"),
           "capa_vs_sin": mejora([_ll(x["p0"], x["y"]) - _ll(x["p1"], x["y"]) for x in v]),
           "semanas_1_6": {"sin_capa": calib([x for x in v if 0 < x["week"] <= 6], "p0"),
                           "con_capa": calib([x for x in v if 0 < x["week"] <= 6], "p1")},
           "bandas_con_capa": {}, "bandas_sin_capa": {}, "peso_reajustado": {}}
    for lo_, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, 1.0)):
        for k, nom in (("p1", "bandas_con_capa"), ("p0", "bandas_sin_capa")):
            b = [x for x in v if lo_ <= max(x[k], 1 - x[k]) < hi]
            if b:
                res[nom]["%.1f-%.1f" % (lo_, hi)] = calib(b, k)
    cs = [i / 20 for i in range(21)]; d_all = []
    for yr in range(2021, dt.date.today().year + 1):
        tr = [x for x in v if x["fecha"][:4] < str(yr)]; te = [x for x in v if x["fecha"][:4] == str(yr)]
        if not tr or not te:
            continue
        c = min(cs, key=lambda c: sum(_ll(_sg(_lo(x["p0"]) + c * x["sh"]), x["y"]) for x in tr))
        d = [_ll(x["p0"], x["y"]) - _ll(_sg(_lo(x["p0"]) + c * x["sh"]), x["y"]) for x in te]
        d_all += d; res["peso_reajustado"][str(yr)] = {"c": c, "n": len(te), "milesimas": round(1000 * sum(d) / len(d), 2)}
    res["peso_reajustado"]["total"] = mejora(d_all)
    cap, cal = res["capa_vs_sin"], res["con_capa"]
    res["veredicto"] = "pasa" if (cap["z"] >= 2 and min(cap["mitades"]) > 0 and abs(cal["promete_pct"] - cal["acierta_pct"]) <= 4) else "no pasa"
    os.makedirs(os.path.dirname(RUTA_OUT), exist_ok=True)
    with _io.open(RUTA_OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("sin_capa", "con_capa", "capa_vs_sin", "veredicto")}, ensure_ascii=False, indent=1))
    print("peso reajustado:", json.dumps(res["peso_reajustado"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
