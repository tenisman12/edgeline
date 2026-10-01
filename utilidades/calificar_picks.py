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
        "valor_resultado", "valor_unidades"]


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
        return {"marcador": sc, "ganador": "home" if w == j1 else "away"}, None


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


def procesar(filas, hoy=None):
    hoy = hoy or dt.date.today()
    E, T = Equipos(), Tenis()
    out = []
    for r in filas:
        o = {k: r.get(k, "") for k in COLS}
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
    por = {}
    for x in cal: por.setdefault(x["liga"], []).append(x)
    cub = []
    c = [x for x in cal if x["estado"] == "calificado" and x["acierto"] != "" and num(x["prob"]) is not None]
    for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
        b = [x for x in c if lo <= num(x["prob"]) < hi]
        if b:
            cub.append({"rango": "%d-%d%%" % (lo * 100, min(hi, 1.0) * 100), "n": len(b),
                        "prob_media_pct": round(100.0 * sum(num(x["prob"]) for x in b) / len(b), 1),
                        "acierto_pct": round(100.0 * sum(int(x["acierto"]) for x in b) / len(b), 1)})
    return {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "total": grupo(cal),
            "por_liga": {k: grupo(v) for k, v in sorted(por.items())}, "calibracion": cub}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--historial", default=io.ruta("salida", "historial_picks.csv"))
    a = ap.parse_args()
    if not os.path.exists(a.historial):
        print("No existe", a.historial); return
    with open(a.historial, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    cal = procesar(filas)
    ruta = io.ruta("salida", "historial_calificado.csv")
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(cal)
    rs = resumen(cal)
    json.dump(rs, open(io.ruta("salida", "track_record.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    t = rs["total"]
    print("TRACK RECORD | %d picks: %d calificados, %d pendientes, %d sin resultado, %d anulados" % (
        t["picks"], t["calificados"], t["pendientes"], t["sin_resultado"], t["anulados"]))
    print("%-8s %6s %6s %8s %8s %8s   %s" % ("LIGA", "picks", "calif", "acierto", "p media", "brier", "VALOR (apuestas, unidades, ROI)"))
    for lg, d in rs["por_liga"].items():
        v = d.get("valor")
        print("%-8s %6d %6d %7s%% %7s%% %8s   %s" % (lg, d["picks"], d["calificados"], d.get("acierto_pct", "-"),
              d.get("prob_media_pct", "-"), d.get("brier", "-"),
              ("%d apuestas, %+.2fu, ROI %+.1f%%" % (v["apuestas"], v["unidades"], v["roi_pct"])) if v else "-"))
    if t.get("calificados"):
        print("TOTAL    %6d %6d %7s%% %7s%% %8s" % (t["picks"], t["calificados"], t["acierto_pct"], t.get("prob_media_pct", "-"), t["brier"]))
        print("Calibracion:", "; ".join("%s: n=%d, esperado %s%%, real %s%%" % (b["rango"], b["n"], b["prob_media_pct"], b["acierto_pct"]) for b in rs["calibracion"]))
    sr = [x for x in cal if x["estado"] == "sin_resultado"]
    for x in sr[:10]:
        print("  sin resultado:", x["liga"], x["fecha"], x["away"], "@", x["home"], "|", x["marcador"])
    print("Escrito:", ruta)


if __name__ == "__main__":
    main()
