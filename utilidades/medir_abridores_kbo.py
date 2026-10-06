# -*- coding: utf-8 -*-
"""
utilidades/medir_abridores_kbo.py - mide si el abridor (as-of, del box oficial de koreabaseball.com) mejora al modelo de
KBO en Ganador, Total esperado y Over/Under, con el mismo walk-forward de la validacion (24 meses, bloques de 30 dias).

Valor del abridor = (carreras permitidas por juego del equipo, as-of) - (FIP del abridor encogido) x IP esperadas / 9.
  FIP del abridor: sus aperturas anteriores (temporada actual + la anterior), con constante de la liga as-of y encogido
  hacia la liga con IP_PRIOR innings. IP esperadas: su promedio por apertura, encogido hacia 5.
Ganador: logit(p) + K x (valor_local - valor_visita). Total: cada abridor quita su valor a las carreras del rival.
K se elige en una mitad y se evalua en la otra (y al reves). Protocolo: z >= 2 y mejora en las dos mitades.
Escribe modelos/abridores_<liga>.json (--liga kbo por defecto; --liga lmp para LMP).

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\medir_abridores_kbo.py
"""
import csv, json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, features as F
from nucleo import abridores as _AB
from modelos import beisbol as B

IP_PRIOR = 30.0
KS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
ESCALAS_TOT = (0.25, 0.5, 0.75, 1.0)


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


LIGA = "kbo"
for _i, _a in enumerate(sys.argv):
    if _a == "--liga" and _i + 1 < len(sys.argv):
        LIGA = sys.argv[_i + 1].lower()


def lanzadores():
    from nucleo import abridores as _AB
    ruta = _AB._ruta(io.BASE, LIGA)
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (r.get("game_date") or "", r.get("game_id") or ""))
    return rows


def valores_abridor(rows):
    """{(game_id, equipo): (fip_encogido, ip_esperadas, aperturas)} as-of (solo aperturas anteriores)."""
    hist = {}              # jugador+equipo-agnostico: por nombre
    liga = {"er": 0.0, "outs": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0}
    out = {}
    por_fecha = {}
    for r in rows:
        por_fecha.setdefault(r["game_date"], []).append(r)
    for fch in sorted(por_fecha):
        dia = por_fecha[fch]
        ip_l = liga["outs"] / 3.0
        cf = (9 * liga["er"] / ip_l - (13 * liga["hr"] + 3 * liga["bb"] - 2 * liga["k"]) / ip_l) if ip_l > 300 else 3.2
        lg_fip = (13 * liga["hr"] + 3 * liga["bb"] - 2 * liga["k"]) / ip_l + cf if ip_l > 300 else 4.6
        for r in dia:
            if not _AB._es_abridor(r):
                continue
            nom = _AB._clave(r)
            temp = int(fch[:4])
            h = [x for x in hist.get(nom, []) if x[0] >= temp - 1]
            outs = sum(x[1] for x in h); ip = outs / 3.0
            fip = ((13 * sum(x[4] for x in h) + 3 * sum(x[3] for x in h) - 2 * sum(x[2] for x in h)) / ip + cf) if ip > 0 else lg_fip
            fip_s = (ip * fip + IP_PRIOR * lg_fip) / (ip + IP_PRIOR)
            ip_esp = ((ip / len(h)) * len(h) + 5.0 * 5) / (len(h) + 5) if h else 5.0
            out[(r["game_id"], r["team"])] = (fip_s, ip_esp, len(h), lg_fip)
        for r in dia:                                 # despues de usar el dia, se suma
            nom = _AB._clave(r)
            o, k, hr, er = (_f(r.get(c)) or 0.0 for c in ("outs", "k", "hr", "er"))
            bb = _f(r.get("bb_hbp"))
            if bb is None:
                bb = (_f(r.get("bb")) or 0.0) + (_f(r.get("hbp")) or 0.0)
            liga["outs"] += o; liga["k"] += k; liga["bb"] += bb; liga["hr"] += hr; liga["er"] += er
            if _AB._es_abridor(r):
                hist.setdefault(nom, []).append((int(fch[:4]), o, k, bb, hr))
    return out


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _lo(p):
    p = min(max(p, 1e-6), 1 - 1e-6); return math.log(p / (1 - p))


def _p_over(mu, L):
    return 1 - sum(B._nb_pmf(k, mu) for k in range(int(math.floor(L)) + 1))


def main():
    V = valores_abridor(lanzadores())
    feats, _ = F.construir("beisbol", LIGA.upper(), 5)
    G = [r for r in feats if r["league"] == LIGA and r.get("y_home") is not None and r.get("total") is not None]
    G.sort(key=lambda r: r["game_date"])
    ultimo = dt.date.fromisoformat(G[-1]["game_date"][:10]); d0 = ultimo - dt.timedelta(days=int(24 * 30.4))
    filas = []
    while d0 <= ultimo:
        d1 = d0 + dt.timedelta(days=30)
        blk = [r for r in G if d0.isoformat() <= r["game_date"][:10] < d1.isoformat()]
        prev = [r for r in G if r["game_date"][:10] < d0.isoformat()]
        if blk and len(prev) >= 300:
            modelo = B.entrenar_logistica(prev)
            if modelo:
                tot_prev = [r["total"] for r in prev]; base_tot = sum(tot_prev) / len(tot_prev)
                hw = sum(r["y_home"] for r in prev) / len(prev)
                L = math.floor(base_tot) + 0.5; fr = sum(1 for t in tot_prev if t > L) / len(tot_prev)
                for r in blk:
                    p = B.prob(modelo, r); xh, xa = B.carreras_esperadas(r)
                    if xh is None:
                        continue
                    if B.COHERENTE:
                        xh, xa = B.ajustar_carreras(xh, xa, p)
                    vh, va = V.get((r["gamePk"], r["home"])), V.get((r["gamePk"], r["away"]))
                    if not vh or not va:
                        continue
                    # carreras que salva cada abridor contra el pitcheo de su equipo (df_ = carreras permitidas por juego)
                    sh = (r["df_home"] - vh[0]) * vh[1] / 9.0
                    sa = (r["df_away"] - va[0]) * va[1] / 9.0
                    filas.append({"p": p, "y": r["y_home"], "xh": xh, "xa": xa, "tot": r["total"], "sh": sh, "sa": sa,
                                  "base_tot": base_tot, "L": L, "fr": fr, "hw": hw})
        d0 = d1
    n = len(filas); h = n // 2
    print("%s: %d partidos en la ventana con abridor de ambos lados" % (LIGA.upper(), n))
    if n < 50:
        print("Muestra insuficiente para medir."); return 1
    A, Bm = filas[:h], filas[h:]

    def ll_gan(F_, k):
        return [_ll(r["p"], r["y"]) - _ll(1 / (1 + math.exp(-(_lo(r["p"]) + k * (r["sh"] - r["sa"])))), r["y"]) for r in F_]

    def mejor_k(F_):
        return max(KS, key=lambda k: sum(ll_gan(F_, k)))
    kA, kB = mejor_k(A), mejor_k(Bm)
    d = ll_gan(Bm, kA) + ll_gan(A, kB)
    def resumen(d, mA, mB):
        mu = sum(d) / len(d); sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (len(d) - 1)) or 1e-9
        z = mu / (sd / math.sqrt(len(d)))
        return {"mejora_milesimas": round(1000 * mu, 3), "z": round(z, 2), "mitades": [round(1000 * mA, 3), round(1000 * mB, 3)],
                "veredicto": "APLICAR" if (len(d) >= 300 and z >= 2.0 and mA > 0 and mB > 0) else "sin mejora demostrada"}
    gB, gA = ll_gan(Bm, kA), ll_gan(A, kB)
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "liga": LIGA, "n": n,
           "ganador": dict(resumen(gB + gA, sum(gA) / len(gA), sum(gB) / len(gB)), k_mitad1=kA, k_mitad2=kB, k_todo=mejor_k(filas))}
    # ganador contra la tasa base (para ver si cruza z 2 de la validacion)
    def skill(F_, k):
        return [_ll(r["hw"], r["y"]) - _ll(1 / (1 + math.exp(-(_lo(r["p"]) + k * (r["sh"] - r["sa"])))), r["y"]) for r in F_]
    for nombre, k in (("modelo_solo", 0.0), ("con_abridor", res["ganador"]["k_todo"])):
        s = skill(filas, k); mu = sum(s) / n; sd = math.sqrt(sum((x - mu) ** 2 for x in s) / (n - 1))
        res["ganador_vs_base_" + nombre] = {"skill_milesimas": round(1000 * mu, 3), "z": round(mu / (sd / math.sqrt(n)), 2),
                                            "mitades": [round(1000 * sum(s[:h]) / h, 3), round(1000 * sum(s[h:]) / (n - h), 3)]}
    # totales
    tot = {}
    for e in ESCALAS_TOT:
        dm, do = [], []
        for r in filas:
            mu0 = r["xh"] + r["xa"]; mu1 = max(r["xh"] - e * r["sa"], 0.5) + max(r["xa"] - e * r["sh"], 0.5)
            dm.append(abs(r["tot"] - mu0) - abs(r["tot"] - mu1))
            y = 1 if r["tot"] > r["L"] else 0
            do.append(_ll(_p_over(mu0, r["L"]), y) - _ll(_p_over(mu1, r["L"]), y))
        out = {}
        for nom, d_ in (("total_mae", dm), ("over_under", do)):
            mu = sum(d_) / n; sd = math.sqrt(sum((x - mu) ** 2 for x in d_) / (n - 1)) or 1e-9
            mA, mB = sum(d_[:h]) / h, sum(d_[h:]) / (n - h); z = mu / (sd / math.sqrt(n))
            out[nom] = {"mejora": round(mu if nom == "total_mae" else 1000 * mu, 4), "z": round(z, 2),
                        "mitades": [round(mA, 4), round(mB, 4)],
                        "veredicto": "APLICAR" if (n >= 300 and z >= 2.0 and mA > 0 and mB > 0) else "sin mejora demostrada"}
        tot["escala_%.2f" % e] = out
    res["totales"] = tot
    g = res["ganador"]
    print("Ganador: K %s/%s  mejora %+.3f milesimas de log-loss  z %.2f  mitades %s -> %s" % (
        g["k_mitad1"], g["k_mitad2"], g["mejora_milesimas"], g["z"], g["mitades"], g["veredicto"]))
    for k in ("modelo_solo", "con_abridor"):
        s = res["ganador_vs_base_" + k]
        print("  contra la tasa base, %-12s skill %+.2f milesimas  z %.2f  mitades %s" % (k, s["skill_milesimas"], s["z"], s["mitades"]))
    for e, o in tot.items():
        print("Totales %s: MAE %+.4f carreras (z %.2f) %s | O/U %+.3f milesimas (z %.2f) %s" % (
            e, o["total_mae"]["mejora"], o["total_mae"]["z"], o["total_mae"]["veredicto"],
            o["over_under"]["mejora"], o["over_under"]["z"], o["over_under"]["veredicto"]))
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "abridores_%s.json" % LIGA), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
