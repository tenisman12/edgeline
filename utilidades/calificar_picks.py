# -*- coding: utf-8 -*-
"""
utilidades/calificar_picks.py - CALIFICA los picks del historial contra los resultados reales.

Lee salida/historial_picks.csv (favorito del modelo + VALOR, registrados ANTES del juego),
busca el resultado en tus datos (datos/*.csv, que actualizar_todo.py mantiene al dia) y escribe:
  salida/historial_calificado.csv   cada pick con resultado, acierto, Brier y resultado del VALOR (unidades)
  salida/track_record.json          resumen por liga, calibracion y VALOR (lo usa la pagina)
Es idempotente: se recalcula todo cada vez; un pick sin resultado todavia queda 'pendiente'.

Reglas
  - Ganador: acierto si el pick coincide con el ganador. Empate en futbol = fallo del pick.
  - Tenis: se empata por nombres de jugadores dentro de la ventana del torneo (TML fecha el partido con el
    inicio del torneo). W/O = anulado. RET cuenta como resultado normal.
  - VALOR: Ganador (home/away/draw), Total X (over/under) y Spread (lado con su linea); +1u = cuota ganada
    (momio americano), -1u = perdido, 0 = push.
  - Juegos sin resultado en tus datos tras 4 dias quedan 'sin_resultado' (revisar nombres o datos).

Uso (en C:\\Edgeline_repo):
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades\\calificar_picks.py
"""
import os, sys, csv, json, math, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io, equipos

TENIS = ("atp", "wta")
DEPORTE = {"mlb": "beisbol", "npb": "beisbol", "kbo": "beisbol", "lmp": "beisbol", "lvbp": "beisbol", "lidom": "beisbol",
           "abl": "beisbol", "nfl": "americano", "ncaafb": "americano", "nhl": "hockey", "nba": "nba", "ncaamb": "nba",
           "premier": "futbol", "laliga": "futbol", "seriea": "futbol", "bundesliga": "futbol", "ligue1": "futbol",
           "ligamx": "futbol", "champions": "futbol", "mls": "futbol"}
COLS = ["registrado", "liga", "id", "fecha", "home", "away", "pick", "prob", "confianza", "estado", "marcador",
        "ganador_real", "acierto", "brier", "valor_mercado", "valor_lado", "valor_cuota", "valor_edge",
        "valor_resultado", "valor_unidades", "con_precio", "nivel", "puntaje", "senales", "p_sharp", "cuota_cierre", "clv_pct"]


def num(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def dia(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def ganancia(cuota, res):
    """momio americano -> unidades por 1u apostada."""
    if res == "push": return 0.0
    if res == "perdio": return -1.0
    c = num(cuota)
    if not c: return None
    return c / 100.0 if c > 0 else 100.0 / abs(c)


# ------------------------------------------------------------------ resultados de equipos
class Equipos:
    def __init__(self):
        self.cache = {}

    def _liga(self, liga):
        if liga in self.cache: return self.cache[liga]
        dep = DEPORTE.get(liga)
        try:
            filas = io.cargar_juegos(dep, liga) if dep else []
        except Exception:
            filas = []
        pj = {}
        for r in filas:
            gp = str(r.get("gamePk") or r.get("game_id") or "")
            pj.setdefault(gp, []).append(r)
        juegos = []; nombres = set()
        for gp, par in pj.items():
            if len(par) != 2: continue
            h = next((x for x in par if str(x.get("is_home")) in ("1", "1.0", "True")), None)
            a = next((x for x in par if x is not h), None)
            if not h or not a: continue
            gh = num(h.get("goals") if h.get("goals") not in (None, "") else h.get("runs") if h.get("runs") not in (None, "") else h.get("points"))
            ga = num(h.get("goals_opp") if h.get("goals_opp") not in (None, "") else h.get("runs_opp") if h.get("runs_opp") not in (None, "") else h.get("points_opp"))
            f = dia(h.get("game_date"))
            if gh is None or ga is None or not f: continue
            juegos.append((f, h.get("team"), a.get("team"), gh, ga)); nombres.update((h.get("team"), a.get("team")))
        self.cache[liga] = (juegos, equipos.Emparejador(sorted(n for n in nombres if n)))
        return self.cache[liga]

    def resultado(self, liga, fecha, home, away):
        juegos, emp = self._liga(liga)
        if not juegos: return None, "sin datos de la liga"
        h, _ = emp.buscar([home]); a, _ = emp.buscar([away])
        if not h or not a: return None, "equipo sin empate en tus datos"
        f0 = dia(fecha)
        cand = [j for j in juegos if j[1] == h and j[2] == a and abs((j[0] - f0).days) <= 1]
        if not cand: return None, None
        cand.sort(key=lambda j: abs((j[0] - f0).days))
        if len(cand) > 1 and abs((cand[0][0] - f0).days) == abs((cand[1][0] - f0).days):
            return None, "doble jornada: ambiguo"
        f, _, _, gh, ga = cand[0]
        return {"gh": gh, "ga": ga, "marcador": "%g-%g" % (gh, ga),
                "ganador": "home" if gh > ga else "away" if ga > gh else "draw"}, None


# ------------------------------------------------------------------ resultados de tenis
class Tenis:
    def __init__(self):
        self.filas = None

    def _cargar(self):
        if self.filas is not None: return
        self.filas = [r for r in io._leer_csv(io.DATOS("tenis.csv"))]
        nombres = {r.get("winner_name") for r in self.filas} | {r.get("loser_name") for r in self.filas}
        self.emp = equipos.EmparejadorJugadores(sorted(n for n in nombres if n))
        self.idx = {}
        for r in self.filas:
            self.idx.setdefault((r.get("winner_name"), r.get("loser_name")), []).append(r)

    def resultado(self, liga, fecha, home, away):
        self._cargar()
        if not self.filas: return None, "sin datos de tenis"
        j1, _ = self.emp.buscar(home); j2, _ = self.emp.buscar(away)
        if not j1 or not j2: return None, "jugador sin empate en tus datos"
        f0 = dia(fecha); mejor = None
        for w, l in ((j1, j2), (j2, j1)):
            for r in self.idx.get((w, l), []):
                if (r.get("tour") or "").lower() not in ("", liga):
                    continue
                td = str(r.get("tourney_date") or "")
                try:
                    t = dt.datetime.strptime(td[:8], "%Y%m%d").date() if td[:8].isdigit() else dia(td)
                except ValueError:
                    t = None
                if not t: continue
                d = (f0 - t).days            # el partido es el dia del torneo o despues
                if -1 <= d <= 16 and (mejor is None or abs(d) < mejor[0]):
                    mejor = (abs(d), w, r)
        if not mejor: return None, None
        _, w, r = mejor
        sc = str(r.get("score") or "")
        if "W/O" in sc.upper() or "WALK" in sc.upper():
            return {"anulado": True, "marcador": sc}, None
        out = {"marcador": sc, "ganador": "home" if w == j1 else "away"}
        # games totales (solo marcadores completos) y breaks (bp enfrentados - bp salvados, de ambos)
        g = 0; ok = bool(sc) and not any(ch.isalpha() for ch in sc)
        for tok in sc.split():
            tok = tok.split("(")[0]
            try:
                a, b = tok.split("-", 1); g += int(a) + int(b)
            except ValueError:
                ok = False
        if ok and g:
            out["games"] = g
        try:
            bw = float(r.get("w_bpFaced")) - float(r.get("w_bpSaved")); bl = float(r.get("l_bpFaced")) - float(r.get("l_bpSaved"))
            out["breaks"] = bw + bl
        except (TypeError, ValueError):
            pass
        return out, None


# ------------------------------------------------------------------ calificacion
def lado_pick(pick, home, away):
    p = (pick or "").strip().lower()
    if p in (home.strip().lower(), ): return "home"
    if p in (away.strip().lower(), ): return "away"
    if p in ("empate", "draw"): return "draw"
    return "home" if p and p in home.strip().lower() else "away" if p and p in away.strip().lower() else None


def calificar_valor(r, res):
    mk = (r.get("valor_mercado") or "").strip(); lado = (r.get("valor_lado") or "").strip()
    if not mk or not lado or res.get("gh") is None and mk.split()[0] != "Ganador":
        return "", ""
    base = mk.split()[0]
    out = None
    if base == "Ganador":
        out = "gano" if res["ganador"] == lado else "perdio"
    elif base == "Total":
        L = num(mk.split()[1]); t = res["gh"] + res["ga"]
        out = "push" if t == L else ("gano" if (t > L) == (lado == "over") else "perdio")
    elif base == "Spread":
        L = num(mk.split()[1]); m = (res["gh"] - res["ga"]) if lado == "home" else (res["ga"] - res["gh"])
        out = "push" if m + L == 0 else ("gano" if m + L > 0 else "perdio")
    if not out: return "", ""
    u = ganancia(r.get("valor_cuota"), out)
    return out, ("" if u is None else round(u, 3))


def _cierres():
    """Ultima foto sharp por (liga, home, away, mercado, lado) desde salida/cuotas_sharp_*.csv: la linea de cierre."""
    import glob
    from nucleo import sharp
    out = {}
    for ruta in sorted(glob.glob(io.ruta("salida", "cuotas_sharp_*.csv"))):
        try:
            with open(ruta, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    lg = sharp.liga_de(r.get("sport") or "")
                    if not lg or (r.get("ts_utc") or "") > (r.get("commence_time") or ""):
                        continue
                    mk = {"h2h": "Ganador", "totals": "Total", "spreads": "Spread"}.get(r.get("mercado"), r.get("mercado"))
                    k = (lg, sharp._norm(r.get("home")) and " ".join(sorted(sharp._norm(r.get("home")))),
                         " ".join(sorted(sharp._norm(r.get("away")))), mk, r.get("lado"))
                    if k not in out or r["ts_utc"] > out[k]["ts_utc"]:
                        out[k] = r
        except Exception:
            continue
    return out


def _clv(r, cierres):
    """CLV = cuota tomada / cuota sharp de cierre - 1 (en %). Positivo = le ganaste a la linea de cierre."""
    if not cierres or not r.get("valor_cuota") or not r.get("nivel") or r["nivel"] == "lectura":
        return "", ""
    from nucleo import sharp
    mk = (r.get("valor_mercado") or "").split()[0] if r.get("valor_mercado") else ""
    k = (r["liga"], " ".join(sorted(sharp._norm(r["home"]))), " ".join(sorted(sharp._norm(r["away"]))), mk, r.get("valor_lado"))
    c = cierres.get(k)
    if not c or not c.get("ref_cuota") and not c.get("mejor_cuota"):
        return "", ""
    try:
        from nucleo import mercado
        cierre = float(c.get("ref_cuota") or c.get("mejor_cuota"))
        tom = mercado.american_a_decimal(float(r["valor_cuota"])); cie = mercado.american_a_decimal(cierre)
        return cierre, round(100 * (tom / cie - 1), 2)
    except Exception:
        return "", ""


def procesar(filas, hoy=None):
    hoy = hoy or dt.date.today()
    cierres = _cierres()
    E, T = Equipos(), Tenis()
    out = []
    for r in filas:
        o = {k: r.get(k, "") for k in COLS}
        o["cuota_cierre"], o["clv_pct"] = _clv(r, cierres)
        liga = r["liga"]
        fuente = T if liga in TENIS else E
        try:
            res, aviso = fuente.resultado(liga, r["fecha"], r["home"], r["away"])
        except Exception as e:
            res, aviso = None, "error: %s" % e
        if res is None:
            f = dia(r["fecha"])
            o["estado"] = "sin_resultado" if (f and (hoy - f).days > 4) else "pendiente"
            if aviso: o["marcador"] = aviso
            out.append(o); continue
        if res.get("anulado"):
            o["estado"] = "anulado"; o["marcador"] = res["marcador"]; out.append(o); continue
        o["estado"] = "calificado"; o["marcador"] = res["marcador"]; o["ganador_real"] = res["ganador"]
        lp = lado_pick(r.get("pick"), r["home"], r["away"])
        if lp:
            ac = 1 if lp == res["ganador"] else 0
            o["acierto"] = ac
            p = num(r.get("prob"))
            if p is not None: o["brier"] = round((p - ac) ** 2, 4)
        o["valor_resultado"], o["valor_unidades"] = calificar_valor(r, res)
        out.append(o)
    return out


def resumen(cal):
    def grupo(rs):
        c = [x for x in rs if x["estado"] == "calificado" and x["acierto"] != ""]
        n = len(c)
        d = {"picks": len(rs), "calificados": n, "pendientes": sum(1 for x in rs if x["estado"] == "pendiente"),
             "sin_resultado": sum(1 for x in rs if x["estado"] == "sin_resultado"),
             "anulados": sum(1 for x in rs if x["estado"] == "anulado")}
        if n:
            ac = sum(int(x["acierto"]) for x in c)
            ps = [num(x["prob"]) for x in c if num(x["prob"]) is not None]
            d.update({"aciertos": ac, "acierto_pct": round(100.0 * ac / n, 1),
                      "prob_media_pct": round(100.0 * sum(ps) / len(ps), 1) if ps else None,
                      "brier": round(sum(float(x["brier"]) for x in c if x["brier"] != "") / max(1, sum(1 for x in c if x["brier"] != "")), 4)})
        v = [x for x in rs if x["valor_resultado"] in ("gano", "perdio", "push") and x["valor_unidades"] != ""]
        if v:
            u = sum(float(x["valor_unidades"]) for x in v)
            d["valor"] = {"apuestas": len(v), "ganadas": sum(1 for x in v if x["valor_resultado"] == "gano"),
                          "unidades": round(u, 2), "roi_pct": round(100.0 * u / len(v), 1)}
        return d
    sin_precio = [x for x in cal if x.get("con_precio") == "no"]      # lecturas del modelo sin cuota (NPB, KBO...)
    cal = [x for x in cal if x.get("con_precio") != "no"]
    por = {}
    for x in cal: por.setdefault(x["liga"], []).append(x)
    por_dep = {}
    for x in cal: por_dep.setdefault(io.deporte_de(x["liga"]) or x["liga"], []).append(x)
    por_niv = {}
    for x in cal: por_niv.setdefault(x.get("nivel") or "pick", []).append(x)
    clv = [float(x["clv_pct"]) for x in cal if x.get("clv_pct") not in ("", None)]
    por_sp = {}
    for x in sin_precio: por_sp.setdefault(x["liga"], []).append(x)
    cub = []
    c = [x for x in cal if x["estado"] == "calificado" and x["acierto"] != "" and num(x["prob"]) is not None]
    for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
        b = [x for x in c if lo <= num(x["prob"]) < hi]
        if b:
            cub.append({"rango": "%d-%d%%" % (lo * 100, min(hi, 1.0) * 100), "n": len(b),
                        "prob_media_pct": round(100.0 * sum(num(x["prob"]) for x in b) / len(b), 1),
                        "acierto_pct": round(100.0 * sum(int(x["acierto"]) for x in b) / len(b), 1)})
    return {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "total": grupo(cal),
            "por_liga": {k: grupo(v) for k, v in sorted(por.items())}, "por_deporte": {k: grupo(v) for k, v in sorted(por_dep.items())}, "calibracion": cub,
            "por_nivel": {k: grupo(v) for k, v in sorted(por_niv.items())},
            "clv": {"n": len(clv), "medio_pct": round(sum(clv) / len(clv), 2) if clv else None,
                    "positivos_pct": round(100 * sum(1 for c in clv if c > 0) / len(clv), 1) if clv else None},
            "sin_precio": {"total": grupo(sin_precio), "por_liga": {k: grupo(v) for k, v in sorted(por_sp.items())}}}


# ------------------------------------------------------------------ TODAS las predicciones del modelo (no solo picks)
PCOLS = ["registrado", "liga", "id", "fecha", "home", "away", "mercado", "lado", "p_modelo", "valor_modelo", "linea",
         "p_mercado", "cuota", "validacion", "estado", "marcador", "real", "acierto", "brier", "error_abs"]


def calificar_predicciones(hoy=None):
    """salida/historial_predicciones.csv -> historial_predicciones_calificado.csv + resumen por liga x mercado.
    Mercados: Ganador (prob), Total/Games <linea> (prob de over), Spread <linea> (prob de que cubra el local),
    Breaks (conteo esperado). Mide al MODELO contra la realidad, con o sin cuota."""
    hoy = hoy or dt.date.today()
    ruta = io.ruta("salida", "historial_predicciones.csv")
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    E, T = Equipos(), Tenis(); out = []
    for r in filas:
        o = {k: r.get(k, "") for k in PCOLS}
        fuente = T if r["liga"] in TENIS else E
        try:
            res, aviso = fuente.resultado(r["liga"], r["fecha"], r["home"], r["away"])
        except Exception as e:
            res, aviso = None, "error: %s" % e
        if res is None:
            f = dia(r["fecha"]); o["estado"] = "sin_resultado" if (f and (hoy - f).days > 4) else "pendiente"; out.append(o); continue
        if res.get("anulado"):
            o["estado"] = "anulado"; out.append(o); continue
        o["marcador"] = res.get("marcador", ""); base = (r["mercado"] or "").split()[0]
        p = num(r.get("p_modelo")); L = num(r.get("linea")); y = None
        if base == "Ganador":
            y = 1 if res["ganador"] == r["lado"] else 0; o["real"] = res["ganador"]
        elif base in ("Total", "Games"):
            t = res.get("games") if base == "Games" else (None if res.get("gh") is None else res["gh"] + res["ga"])
            if t is None or L is None: o["estado"] = "sin_dato"; out.append(o); continue
            o["real"] = t
            if t == L: o["estado"] = "push"; out.append(o); continue
            y = 1 if (t > L) == (r["lado"] == "over") else 0
        elif base == "Spread":
            if res.get("gh") is None or L is None: o["estado"] = "sin_dato"; out.append(o); continue
            m = (res["gh"] - res["ga"]) if r["lado"] == "home" else (res["ga"] - res["gh"]); o["real"] = res["gh"] - res["ga"]
            if m + L == 0: o["estado"] = "push"; out.append(o); continue
            y = 1 if m + L > 0 else 0
        elif base == "Breaks":
            b = res.get("breaks"); v = num(r.get("valor_modelo"))
            if b is None or v is None: o["estado"] = "sin_dato"; out.append(o); continue
            o["real"] = b; o["error_abs"] = round(abs(v - b), 3); o["estado"] = "calificado"; out.append(o); continue
        else:
            o["estado"] = "sin_dato"; out.append(o); continue
        o["estado"] = "calificado"; o["acierto"] = y
        if p is not None: o["brier"] = round((p - y) ** 2, 4)
        out.append(o)
    with open(io.ruta("salida", "historial_predicciones_calificado.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PCOLS); w.writeheader(); w.writerows(out)
    res = {}
    for o in out:
        if o["estado"] != "calificado": continue
        k = (o["liga"], (o["mercado"] or "").split()[0]); g = res.setdefault(k, {"n": 0, "ac": 0, "br": 0.0, "nb": 0, "ea": 0.0, "ne": 0, "p": 0.0})
        g["n"] += 1
        if o["acierto"] != "": g["ac"] += int(o["acierto"]); g["p"] += float(o["p_modelo"] or 0)
        if o["brier"] != "": g["br"] += float(o["brier"]); g["nb"] += 1
        if o["error_abs"] != "": g["ea"] += float(o["error_abs"]); g["ne"] += 1
    tabla = {}
    for (lg, mk), g in sorted(res.items()):
        tabla["%s|%s" % (lg, mk)] = {"n": g["n"], "acierto_pct": round(100 * g["ac"] / g["nb"], 1) if g["nb"] else None,
                                     "p_media_pct": round(100 * g["p"] / g["nb"], 1) if g["nb"] else None,
                                     "brier": round(g["br"] / g["nb"], 4) if g["nb"] else None,
                                     "mae": round(g["ea"] / g["ne"], 3) if g["ne"] else None}
    pend = sum(1 for o in out if o["estado"] == "pendiente")
    return {"total": len(out), "calificadas": sum(1 for o in out if o["estado"] == "calificado"), "pendientes": pend, "por_liga_mercado": tabla}


# ------------------------------------------------------------------ Picks IA (del API en salida/picks_ia.json o manuales en ia/lecturas/*.json)
def calificar_ia(hoy=None):
    """Junta las lecturas IA (API: salida/historial_ia.csv; manuales: ia/lecturas/*.json con el mismo formato) y las
    califica por decision (PREMIUM/PICK/LEAN) y mercado. Escribe salida/historial_ia_calificado.csv."""
    import glob
    hoy = hoy or dt.date.today()
    lect = []
    rh = io.ruta("salida", "historial_ia.csv")
    if os.path.exists(rh):
        with open(rh, encoding="utf-8-sig", newline="") as f:
            lect += [dict(r, fuente="api") for r in csv.DictReader(f)]
    for ruta in sorted(glob.glob(io.ruta("ia", "lecturas", "*.json"))):
        try:
            d = json.load(open(ruta, encoding="utf-8"))
            for l in (d.get("lecturas") if isinstance(d, dict) else d) or []:
                lect.append(dict(l, fuente="manual", archivo=os.path.basename(ruta)))
        except Exception as e:
            print("  lectura IA ilegible %s: %s" % (ruta, e))
    if not lect:
        return None
    vistos = set(); out = []
    E, T = Equipos(), Tenis()
    for l in lect:
        k = (l.get("liga"), str(l.get("id")), l.get("mercado") or "", l.get("lado") or "")
        if k in vistos:
            continue
        vistos.add(k)
        partido = l.get("partido") or ""
        home, away = (l.get("home"), l.get("away")) if l.get("home") else ((partido.split(" @ ")[1], partido.split(" @ ")[0]) if " @ " in partido else ("", ""))
        o = {"fuente": l.get("fuente"), "liga": l.get("liga"), "id": l.get("id"), "fecha": l.get("fecha"), "home": home, "away": away,
             "decision": (l.get("decision") or "").upper(), "mercado": l.get("mercado") or "", "lado": l.get("lado") or "",
             "cuota": l.get("cuota") or "", "stake": l.get("stake") or "", "lectura": l.get("lectura") or "",
             "estado": "", "marcador": "", "resultado": "", "unidades": ""}
        if o["decision"] not in ("PREMIUM", "PICK") or not o["mercado"] or not o["lado"] or not home:
            o["estado"] = "sin_apuesta"; out.append(o); continue
        fuente = T if o["liga"] in TENIS else E
        try:
            res, _ = fuente.resultado(o["liga"], o["fecha"], home, away)
        except Exception as e:
            res = None
        if res is None:
            f = dia(o["fecha"] or ""); o["estado"] = "sin_resultado" if (f and (hoy - f).days > 4) else "pendiente"; out.append(o); continue
        if res.get("anulado"):
            o["estado"] = "anulado"; out.append(o); continue
        o["marcador"] = res.get("marcador", "")
        r2 = {"valor_mercado": o["mercado"], "valor_lado": o["lado"], "valor_cuota": o["cuota"]}
        o["resultado"], o["unidades"] = calificar_valor(r2, res)
        o["estado"] = "calificado" if o["resultado"] else "sin_dato"
        out.append(o)
    cols = ["fuente", "liga", "id", "fecha", "home", "away", "decision", "mercado", "lado", "cuota", "stake", "estado", "marcador", "resultado", "unidades", "lectura"]
    with open(io.ruta("salida", "historial_ia_calificado.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(out)
    res = {}
    for o in out:
        if o["estado"] != "calificado": continue
        g = res.setdefault(o["decision"], {"n": 0, "gano": 0, "u": 0.0})
        g["n"] += 1; g["gano"] += 1 if o["resultado"] == "gano" else 0; g["u"] += float(o["unidades"] or 0)
    return {"lecturas": len(out), "apuestas": sum(1 for o in out if o["decision"] in ("PREMIUM", "PICK")),
            "pendientes": sum(1 for o in out if o["estado"] == "pendiente"),
            "por_decision": {k: {"n": v["n"], "acierto_pct": round(100 * v["gano"] / v["n"], 1), "unidades": round(v["u"], 2), "roi_pct": round(100 * v["u"] / v["n"], 1)} for k, v in res.items()}}


def imprimir(rs):
    """Imprime el track record (general, por liga, por deporte, por nivel, CLV, sin precio, predicciones, IA) de un dict rs."""
    t = rs["total"]
    print("TRACK RECORD (%s) | %d picks: %d calificados, %d pendientes, %d sin resultado, %d anulados" % (
        rs.get("generado", ""), t["picks"], t["calificados"], t["pendientes"], t["sin_resultado"], t["anulados"]))
    print("%-8s %6s %6s %8s %8s %8s   %s" % ("LIGA", "picks", "calif", "acierto", "p media", "brier", "VALOR (apuestas, unidades, ROI)"))
    for lg, d in rs["por_liga"].items():
        v = d.get("valor")
        print("%-8s %6d %6d %7s%% %7s%% %8s   %s" % (lg, d["picks"], d["calificados"], d.get("acierto_pct", "-"),
              d.get("prob_media_pct", "-"), d.get("brier", "-"),
              ("%d apuestas, %+.2fu, ROI %+.1f%%" % (v["apuestas"], v["unidades"], v["roi_pct"])) if v else "-"))
    if t.get("calificados"):
        print("TOTAL    %6d %6d %7s%% %7s%% %8s" % (t["picks"], t["calificados"], t["acierto_pct"], t.get("prob_media_pct", "-"), t["brier"]))
        print("Calibracion:", "; ".join("%s: n=%d, esperado %s%%, real %s%%" % (b["rango"], b["n"], b["prob_media_pct"], b["acierto_pct"]) for b in rs["calibracion"]))
    print("\nPOR DEPORTE")
    for dp, d in rs.get("por_deporte", {}).items():
        v = d.get("valor")
        print("%-10s %6d %6d %7s%% %7s%% %8s   %s" % (dp, d["picks"], d["calificados"], d.get("acierto_pct", "-"), d.get("prob_media_pct", "-"),
              d.get("brier", "-"), ("%d apuestas, %+.2fu, ROI %+.1f%%" % (v["apuestas"], v["unidades"], v["roi_pct"])) if v else "-"))
    print("\nPOR NIVEL (premium / pick): acierto y ROI del VALOR")
    for nv, d in rs.get("por_nivel", {}).items():
        v = d.get("valor")
        print("%-8s %6d %6d %7s%% %7s%%   %s" % (nv, d["picks"], d["calificados"], d.get("acierto_pct", "-"), d.get("prob_media_pct", "-"),
              ("%d apuestas, %+.2fu, ROI %+.1f%%" % (v["apuestas"], v["unidades"], v["roi_pct"])) if v else "-"))
    c = rs.get("clv") or {}
    if c.get("n"):
        print("CLV (cuota tomada vs cierre sharp): n=%d, medio %+.2f%%, con CLV positivo %.0f%%" % (c["n"], c["medio_pct"], c["positivos_pct"]))
    sp = rs.get("sin_precio", {})
    if sp.get("total", {}).get("picks"):
        print("\nLECTURAS SIN PRECIO (modelo sin cuotas; no cuentan en el track record de picks)")
        for lg, d in sp["por_liga"].items():
            print("%-8s %6d %6d %7s%% %7s%% %8s" % (lg, d["picks"], d["calificados"], d.get("acierto_pct", "-"),
                  d.get("prob_media_pct", "-"), d.get("brier", "-")))
    rp = rs.get("predicciones_modelo")
    if rp:
        print("\nPREDICCIONES DEL MODELO (todos los mercados, con o sin cuota): %d registradas, %d calificadas, %d pendientes" % (rp["total"], rp["calificadas"], rp["pendientes"]))
        print("%-8s %-8s %6s %8s %8s %8s %6s" % ("LIGA", "MERCADO", "n", "acierto", "p media", "brier", "MAE"))
        for k, d in rp["por_liga_mercado"].items():
            lg, mk = k.split("|")
            print("%-8s %-8s %6d %7s%% %7s%% %8s %6s" % (lg, mk, d["n"], d["acierto_pct"] if d["acierto_pct"] is not None else "-",
                  d["p_media_pct"] if d["p_media_pct"] is not None else "-", d["brier"] if d["brier"] is not None else "-", d["mae"] if d["mae"] is not None else "-"))
    ria = rs.get("picks_ia")
    if ria:
        print("\nPICKS IA (API + manuales en ia/lecturas): %d lecturas, %d apuestas, %d pendientes" % (ria["lecturas"], ria["apuestas"], ria["pendientes"]))
        for k, d in ria["por_decision"].items():
            print("  %-8s n=%d acierto %.1f%% unidades %+.2f ROI %+.1f%%" % (k, d["n"], d["acierto_pct"], d["unidades"], d["roi_pct"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--historial", default=io.ruta("salida", "historial_picks.csv"))
    ap.add_argument("--ver", action="store_true",
                    help="solo mostrar salida/track_record.json tal como lo dejo el bot (despues de git pull), sin recalcular con los datos locales")
    a = ap.parse_args()
    if a.ver:
        rt = io.ruta("salida", "track_record.json")
        if not os.path.exists(rt):
            print("No existe", rt, "(haz git pull)"); return
        with open(rt, encoding="utf-8") as f:
            imprimir(json.load(f))
        return
    if not os.path.exists(a.historial):
        print("No existe", a.historial); return
    with open(a.historial, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    cal = procesar(filas)
    ruta = io.ruta("salida", "historial_calificado.csv")
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(cal)
    rs = resumen(cal)
    rs["generado"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    rp = calificar_predicciones()
    if rp:
        rs["predicciones_modelo"] = rp
    ria = calificar_ia()
    if ria:
        rs["picks_ia"] = ria
    json.dump(rs, open(io.ruta("salida", "track_record.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    imprimir(rs)
    sr = [x for x in cal if x["estado"] == "sin_resultado"]
    for x in sr[:10]:
        print("  sin resultado:", x["liga"], x["fecha"], x["away"], "@", x["home"], "|", x["marcador"])
    print("Escrito:", ruta)


if __name__ == "__main__":
    main()
