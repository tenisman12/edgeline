# -*- coding: utf-8 -*-
"""
utilidades/picks_del_dia.py - UNA SOLA LISTA: decision por partido (ganador y total) y los MEJORES picks del dia (tope 4).

Analiza TODOS los partidos de salida/proximos.json y para cada uno deja una decision de ganador y una de total,
con su probabilidad final (precio sharp movido por el modelo cuando hay cuota; modelo solo cuando no la hay).
Despues elige los picks apostables con una sola regla de entrada:
  - beisbol (MLB, NPB, KBO): sistema estimado (salida/decidir.json) con confianza alta o media (EV >= 4% contra Pinnacle);
  - demas deportes: Pick Premium con nivel premium o pick, EV >= EV_MIN contra la mejor cuota;
  - cuota 1.70-3.00, sin pretemporada, un pick por partido, ordenados por EV, maximo MAX_PICKS al dia y tope de bank.
Todo lo demas (leans, minima, revisar, lecturas sin precio) se sigue midiendo en sus historiales, pero NO es pick.

Salida: salida/picks_del_dia.json (decisiones + picks) y salida/historial_picks_dia.csv (los picks oficiales, para calificarlos).

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\picks_del_dia.py              # hoy
    python utilidades\\picks_del_dia.py --dias 2     # hoy y manana (los picks oficiales solo se registran para HOY)
    python utilidades\\picks_del_dia.py --max 3
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, os, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_PICKS = int(os.environ.get("EDGELINE_MAX_PICKS", "4"))
TOPE_BANK = 0.10                      # suma de stakes del dia
MIN_APUESTAS_PUBLICO = 2000   # con menos apuestas el reparto boletos/dinero es ruido
# Ligas donde el reparto del TOTAL no se usa por sesgo de fuente. Vacio: NHL salio del veto porque la linea
# de totales se movio HACIA el over (5.5 -> 6.0 en cinco partidos), o sea que el precio corrobora la carga del
# publico en lugar de desmentirla. Que una liga cargue el over es un hecho conocido, no un error de lectura.
# Para revisarlo: utilidades\validar_publico.py (over por liga) y validar_contrapublico.py (si el under paga).
TOTAL_PUBLICO_VETADO = set()
_IGN_NOM = {"the", "fc", "sc", "club", "de", "los", "las", "la", "el", "st", "state", "university"}


def _clave(s):
    """nombre de equipo -> conjunto de palabras comparable entre fuentes distintas."""
    import re, unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return frozenset(w for w in re.split(r"[^a-z0-9]+", s) if w and w not in _IGN_NOM)


def _mismo(a, b):
    """True si los dos nombres se refieren al mismo equipo (mitad de las palabras en comun)."""
    A, B = _clave(a), _clave(b)
    return bool(A and B) and len(A & B) / float(min(len(A), len(B))) >= 0.5
EV_MIN = 0.02                         # Pick Premium (deportes sin sistema estimado)
CUOTA_MIN, CUOTA_MAX = 1.70, 99.0   # sin tope de cuota (acuerdo 4-oct)
STAKE = {"alta": 0.03, "media": 0.02, "premium": 0.02, "pick": 0.01}
TZ = -6


def _dec(am):
    am = float(am)
    return 1 + am / 100.0 if am > 0 else 1 + 100.0 / abs(am)


def _hoy():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()


def decision(rec, dec_bb=None):
    """Decision de ganador y de total del partido con la mejor probabilidad disponible."""
    m = rec.get("modelo") or {}
    picks = rec.get("picks") or []
    # En beisbol manda el sistema estimado: la decision del partido y el pick tienen que salir de la MISMA mezcla,
    # si no el reporte dice que gana un equipo y apuesta al otro.
    g = None
    d = (dec_bb or {}).get((rec["liga"], str(rec["id"]), rec["fecha"])) if dec_bb else None
    if d and d.get("p_final") is not None:
        pf = float(d["p_final"])
        lado = "home" if pf >= 0.5 else "away"
        g = {"lado": lado, "nombre": rec[lado]["nombre"], "p": pf if lado == "home" else 1 - pf,
             "cuota": None, "fuente": "sistema estimado", "cuota_min": None}
        picks = [k for k in picks if not (k["mercado"] == "Ganador")]
    gan = [k for k in picks if k["mercado"] == "Ganador" and k.get("p_final") is not None]
    if g is not None:
        pass                                   # ya la puso el sistema estimado (beisbol)
    elif gan:
        k = max(gan, key=lambda x: x["p_final"])
        g = {"lado": k["lado"], "nombre": k["texto"], "p": k["p_final"], "cuota": k.get("cuota"), "fuente": k.get("fuente"), "cuota_min": k.get("cuota_min")}
    elif m.get("p_home") is not None:
        lado = "home" if m["p_home"] >= (m.get("p_away") or 0) else "away"
        g = {"lado": lado, "nombre": rec[lado]["nombre"], "p": m["p_home"] if lado == "home" else m["p_away"], "cuota": None, "fuente": "modelo", "cuota_min": None}
    else:
        g = None
    tot = [k for k in picks if k["mercado"].startswith("Total") and k.get("p_final") is not None]
    if tot:
        k = max(tot, key=lambda x: x["p_final"])
        t = {"lado": k["lado"], "linea": k["mercado"].split()[1], "p": k["p_final"], "cuota": k.get("cuota"), "fuente": k.get("fuente")}
    elif m.get("p_over") is not None and m.get("linea_total") is not None:
        t = {"lado": "over" if m["p_over"] >= 0.5 else "under", "linea": m["linea_total"], "p": max(m["p_over"], 1 - m["p_over"]), "cuota": None, "fuente": "modelo"}
    else:
        t = None
    if t and rec.get("deporte") == "beisbol" and t.get("fuente") not in ("modelo", None):
        t["nota"] = "total = mercado (el modelo de totales de beisbol no mejora la base)"
    return g, t


def candidatos(rec, dec_bb):
    """picks apostables del partido segun su sistema: beisbol -> decidir; resto -> Pick Premium."""
    out = []
    if rec.get("pretemporada"):
        return out
    if rec.get("deporte") == "beisbol":
        d = dec_bb.get((rec["liga"], str(rec["id"]), rec["fecha"]))
        k = (d or {}).get("pick")
        if d and k and d.get("confianza") in ("alta", "media") and k["mercado"] == "Ganador":   # sin run line (acuerdo 4-oct)
            mercado = "Ganador"
            out.append({"origen": "sistema estimado", "mercado": mercado, "lado": k["lado"], "pick": k["texto"], "cuota": k["cuota"], "decimal": k["decimal"],
                        "casa": k.get("casa"), "p": k["p"], "ev": k["ev"], "confianza": d["confianza"], "stake": STAKE[d["confianza"]],
                        "senales": "%d a favor / %d en contra" % (k.get("senales_favor", 0), k.get("senales_contra", 0)),
                        "razon": "p final %.1f%% (Pinnacle %.1f%%, modelo %.1f%%) contra %s" % (100 * d["p_final"], 100 * (d["p_sharp"] or 0), 100 * (d["p_modelo"] or 0), k["cuota"])})
        return out
    for k in rec.get("picks") or []:
        if k.get("nivel") not in ("premium", "pick") or k.get("ev") is None or k.get("cuota") is None:
            continue
        if str(k.get("mercado", "")).startswith("Spread"):   # solo ganador y totales (acuerdo 4-oct)
            continue
        dec = k.get("decimal") or _dec(k["cuota"])
        if k["ev"] < EV_MIN or not (CUOTA_MIN <= dec <= CUOTA_MAX):
            continue
        out.append({"origen": "pick premium", "mercado": k["mercado"], "lado": k["lado"], "pick": k["texto"], "cuota": k["cuota"], "decimal": round(dec, 3),
                    "casa": k.get("casa"), "p": k.get("p_final"), "ev": k["ev"], "confianza": k["nivel"], "stake": STAKE[k["nivel"]],
                    "senales": "%.0f pts" % (k.get("puntaje") or 0), "razon": (k.get("razonamiento") or "")[:220]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=1)
    ap.add_argument("--max", type=int, default=MAX_PICKS)
    a = ap.parse_args()
    with io.open(os.path.join(BASE, "salida", "proximos.json"), encoding="utf-8") as f:
        D = json.load(f)
    dec_bb = {}
    try:
        with io.open(os.path.join(BASE, "salida", "decidir.json"), encoding="utf-8") as f:
            for d in json.load(f).get("partidos") or []:
                dec_bb[(d["liga"], str(d["id"]), d["fecha"])] = d
    except Exception:
        pass
    hoy = _hoy(); lim = (hoy + dt.timedelta(days=a.dias - 1)).isoformat()
    sel = [p for p in D["partidos"] if hoy.isoformat() <= p["fecha"] <= lim]
    publico = {}
    try:
        with io.open(os.path.join(BASE, "salida", "publico.json"), encoding="utf-8") as f:
            for q in json.load(f).get("partidos") or []:
                publico[(q["liga"], str(q["id"]))] = q
    except Exception:
        pass
    # movimiento de linea (salida/mercado_publico.json): cuanto se movio la probabilidad del grupo sharp
    # desde la apertura, en puntos porcentuales. Es CONTEXTO que se guarda para medir; no cambia p ni EV.
    movim = {}
    try:
        with io.open(os.path.join(BASE, "salida", "mercado_publico.json"), encoding="utf-8") as f:
            for m in json.load(f).get("partidos") or []:
                nom = (m.get("partido") or "").split(" @ ")
                if len(nom) != 2:
                    continue
                movim[(m.get("liga"), _clave(nom[1]), _clave(nom[0]))] = m
    except Exception:
        pass

    def movimiento(p, mercado, lado, nombre=None):
        """(mov_pp del lado apostado, senales del partido). mov > 0 = la linea sharp se movio A FAVOR de ese lado."""
        m = movim.get((p["liga"], _clave(p["home"]["nombre"]), _clave(p["away"]["nombre"])))
        if not m:
            return None, ""
        quiere = "total" if mercado.startswith("Total") else ("handicap" if mercado.startswith("Spread") else "ganador")
        for mk in m.get("mercados") or []:
            if mk.get("mercado") != quiere:
                continue
            mov = mk.get("mov_sharp_pp")
            if mov is None:
                return None, "; ".join(mk.get("senales") or [])
            lado_a = (mk.get("lado_a") or "")
            if quiere == "total":
                mismo = (lado == "over")
            elif quiere == "ganador":
                mismo = _mismo(nombre or "", lado_a)
            else:                                   # handicap: lado_a trae el nombre del equipo con la linea
                mismo = _mismo(p["home"]["nombre"], lado_a) if lado == "home" else not _mismo(p["home"]["nombre"], lado_a)
            return (round(mov if mismo else -mov, 2), "; ".join(mk.get("senales") or []))
        return None, ""

    def lado_publico(q, mercado, lado):
        """% de boletos y dinero del publico en el lado del pick (None si no hay o si el volumen es ruido)."""
        s = (q or {}).get("splits") or {}
        nb = (q or {}).get("num_bets")
        try:
            if nb is not None and float(nb) < MIN_APUESTAS_PUBLICO:
                return None, None
        except (TypeError, ValueError):
            pass
        if mercado.startswith("Total"):
            if (q or {}).get("liga") in TOTAL_PUBLICO_VETADO:
                return None, None      # la fuente carga el over de toda la liga: ese dato no es el publico
            d = s.get("total") or {}; t, m = d.get("tickets_over"), d.get("money_over")
            if lado == "under":
                t, m = (None if t is None else 100 - t), (None if m is None else 100 - m)
        elif mercado.startswith("Spread"):
            d = s.get("spread") or {}; t, m = d.get("tickets_home"), d.get("money_home")
            if lado == "away":
                t, m = (None if t is None else 100 - t), (None if m is None else 100 - m)
        else:
            d = s.get("ml") or {}; t, m = d.get("tickets_home"), d.get("money_home")
            if lado == "away":
                t, m = (None if t is None else 100 - t), (None if m is None else 100 - m)
        return t, m
    partidos, cand = [], []
    for p in sel:
        g, t = decision(p, dec_bb)
        q = publico.get((p["liga"], str(p["id"])))
        mv_g = movimiento(p, "Ganador", "home", g["nombre"])[0] if g else None
        mv_t, sen_mov = movimiento(p, "Total", (t or {}).get("lado") or "over")
        fila = {"liga": p["liga"], "id": str(p["id"]), "fecha": p["fecha"], "hora": p.get("hora"), "home": p["home"]["nombre"], "away": p["away"]["nombre"],
                "pretemporada": bool(p.get("pretemporada")), "ganador": g, "total": t, "sin_modelo": not p.get("modelo"),
                "mov_ganador": mv_g, "mov_total": mv_t, "senales_mercado": sen_mov,
                "publico": {"splits": (q or {}).get("splits"), "atencion": (q or {}).get("atencion")} if q else None}
        partidos.append(fila)
        for c in candidatos(p, dec_bb):
            tk, mn = lado_publico(q, c["mercado"], c["lado"])
            at = (q or {}).get("atencion") or {}
            mv, sen = movimiento(p, c["mercado"], c["lado"], c.get("pick"))
            cand.append(dict(c, liga=p["liga"], id=str(p["id"]), fecha=p["fecha"], hora=p.get("hora"), home=p["home"]["nombre"], away=p["away"]["nombre"],
                             publico_boletos=tk, publico_dinero=mn, notas_home=at.get("home"), notas_away=at.get("away"),
                             mov_linea=mv, senales_mercado=sen))
    # mejores picks de HOY: un pick por partido, por EV, tope de cantidad y de bank
    picks, usados, bank = [], set(), 0.0
    for c in sorted([c for c in cand if c["fecha"] == hoy.isoformat()], key=lambda c: -c["ev"]):
        k = (c["liga"], c["id"])
        if k in usados or len(picks) >= a.max or bank + c["stake"] > TOPE_BANK + 1e-9:
            continue
        usados.add(k); bank += c["stake"]; picks.append(c)
    descartados = [c for c in cand if c["fecha"] == hoy.isoformat() and c not in picks]
    ahora = dt.datetime.now().isoformat(timespec="seconds")
    # consola
    print("PICKS DEL DIA %s | %d partidos analizados | %d candidatos | %d picks (tope %d, bank %.0f%%)" % (hoy, len(partidos), len(cand), len(picks), a.max, 100 * bank))
    for i, c in enumerate(picks, 1):
        pub = ("" if c.get("publico_boletos") is None else " | publico %s%% boletos / %s%% dinero" % (c["publico_boletos"], c["publico_dinero"] if c.get("publico_dinero") is not None else "-"))
        if c.get("mov_linea") is not None:
            pub += " | linea %+.1f pp %s" % (c["mov_linea"], "a favor" if c["mov_linea"] > 0 else "en contra")
        print("  %d. %-5s %s %s | %-22s %-28s cuota %7s EV %+5.1f%% %-7s stake %.0f%% | %s%s" % (
            i, c["liga"], c["fecha"], c["hora"] or "", ("%s @ %s" % (c["away"], c["home"]))[:22], ((c["mercado"] + " " if c["mercado"].startswith("Total") else "") + c["pick"])[:28], c["cuota"], 100 * c["ev"], c["confianza"], 100 * c["stake"], c["senales"], pub))
    if descartados:
        print("  candidatos fuera del tope: " + "; ".join("%s %s EV %+.1f%%" % (c["liga"], c["pick"], 100 * c["ev"]) for c in descartados[:6]))
    print("\nDECISION POR PARTIDO (ganador y total):")
    for f in sorted(partidos, key=lambda x: (x["fecha"], x["liga"], x["hora"] or "")):
        g, t = f["ganador"], f["total"]
        print("  %-6s %s %s %-34s | GANA %-24s %s | %s" % (
            f["liga"], f["fecha"], (f["hora"] or "")[:5], ("%s @ %s" % (f["away"], f["home"]))[:34],
            (g["nombre"][:24] if g else "sin modelo"), ("%.0f%%" % (100 * g["p"]) if g else ""),
            ("%s %s %.0f%%" % (t["lado"].upper(), t["linea"], 100 * t["p"]) if t else "total: sin linea"))
            + ("" if f.get("mov_ganador") is None else " | linea %+.1f pp" % f["mov_ganador"])
            + ("  [pretemporada]" if f["pretemporada"] else ""))
    with io.open(os.path.join(BASE, "salida", "picks_del_dia.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "fecha": hoy.isoformat(), "max_picks": a.max, "tope_bank": TOPE_BANK, "picks": picks, "candidatos_fuera": descartados,
                   "partidos": partidos}, f, ensure_ascii=False, indent=1)
    rh = os.path.join(BASE, "salida", "historial_picks_dia.csv")
    cols = ["registrado", "liga", "id", "fecha", "home", "away", "origen", "mercado", "lado", "pick", "cuota", "p", "ev", "confianza", "stake", "senales",
            "publico_boletos", "publico_dinero", "notas_home", "notas_away", "mov_linea", "senales_mercado"]
    vistos = set()
    if os.path.exists(rh):
        with io.open(rh, encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f); previas = list(r); cab = r.fieldnames or []
            vistos = {(x["liga"], x["id"], x["fecha"]) for x in previas}
        # cabecera vieja: agregar filas con mas campos corre los valores de columna. Se reescribe antes de anexar.
        if cab and cab != cols:
            faltan = [c for c in cab if c not in cols]
            nueva = cols + faltan
            with io.open(rh, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=nueva, extrasaction="ignore")
                w.writeheader()
                for x in previas:
                    w.writerow(x)
            cols = nueva
            print("   (cabecera de historial_picks_dia.csv migrada: %d columnas -> %d, %d filas reescritas)" % (
                len(cab), len(nueva), len(previas)))
    nuevos = 0
    with io.open(rh, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not vistos and f.tell() == 0:
            w.writeheader()
        for c in picks:
            if (c["liga"], c["id"], c["fecha"]) in vistos:
                continue
            w.writerow(dict(c, registrado=ahora)); nuevos += 1
    print("\nEscrito: salida/picks_del_dia.json | historial_picks_dia.csv: %d picks nuevos" % nuevos)


if __name__ == "__main__":
    main()
