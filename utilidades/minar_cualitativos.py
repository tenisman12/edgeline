# -*- coding: utf-8 -*-
"""
utilidades/minar_cualitativos.py - angulos situacionales cualitativos (motivacion y tabla) en NHL, NBA, NFL, beisbol y futbol.

Hipotesis registrada antes de ver resultados: trabajo/minar/2026-10-09_cualitativos.md
1) Residuo fuera de muestra contra el modelo (evaluador de minar_situacionales: 70/30, log-loss pareado, mismo criterio).
2) TMLE descriptivo: efecto sobre la probabilidad de que gane el equipo en la situacion, ajustado por el modelo y la localia.
No toca modelos/ ni nucleo/. Requiere numpy y scikit-learn.

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python utilidades/minar_cualitativos.py
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import bisect, json, math, os, sys, warnings, zlib
import numpy as np
from sklearn.linear_model import LogisticRegression

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minar_situacionales as M  # noqa: E402

FUERTE, DEBIL, MIN_J = 0.60, 0.40, 8


class Tabla:
    """% de victorias as-of por equipo y temporada (temporada = juegos sin hueco de mas de 60 dias)."""

    def __init__(self, C):
        self.C = C; self.d = {}
        for e, L in C.t.items():
            fechas = [g["fecha"] for g in L]; sid = []; ini = []; s = 0; i0 = 0
            for i, g in enumerate(L):
                if i and (g["fecha"] - L[i - 1]["fecha"]).days > 60: s += 1; i0 = i
                sid.append(s); ini.append(i0)
            tot = {}
            for x in sid: tot[x] = tot.get(x, 0) + 1
            pts = []; cnt = []; acc = 0.0; nn = 0
            for g in L:
                if g["gf"] is not None and g["ga"] is not None:     # juegos sin marcador (Champions agregada) no cuentan
                    acc += 1.0 if g["gf"] > g["ga"] else (0.5 if g["gf"] == g["ga"] else 0.0); nn += 1
                pts.append(acc); cnt.append(nn)
            self.d[e] = (fechas, sid, ini, tot, pts, cnt)

    def wpct(self, e, fecha):
        if e not in self.d: return None
        fechas, sid, ini, tot, pts, cnt = self.d[e]
        k = bisect.bisect_left(fechas, fecha)
        if k == 0 or (fecha - fechas[k - 1]).days > 60: return None
        j = k - 1; b = ini[j] - 1
        n = cnt[j] - (cnt[b] if b >= 0 else 0)
        if n < MIN_J: return None
        return (pts[j] - (pts[b] if b >= 0 else 0.0)) / n

    def pos(self, e, i):
        fechas, sid, ini, tot, pts, cnt = self.d[e]
        return i - ini[i] + 1, tot[sid[i]], sid[i]


def clave_rival(e, rival):
    return (e[0], rival) if isinstance(e, tuple) else rival


def situaciones(r, C, T, coach_nuevo=None):
    """Devuelve {codigo: lado} con lado 'H', 'A', 'AMBOS' o None."""
    th, ta, gp = r["home"], r["away"], r["gp"]
    out = {}
    info = {}
    for lado, e, opp in (("H", th, ta), ("A", ta, th)):
        i = C.i(e, gp)
        if i is None: info[lado] = None; continue
        L = C.t[e]; g = L[i]; f = g["fecha"]
        k, tot, sid = T.pos(e, i)
        prev = L[i - 1] if i > 0 and T.d[e][1][i - 1] == sid else None
        nxt = L[i + 1] if i + 1 < len(L) and T.d[e][1][i + 1] == sid else None
        opp_w = T.wpct(opp, f)
        def fuerza(gg):
            if not gg: return None
            return T.wpct(clave_rival(e, gg["rival"]), gg["fecha"])
        pw, nw = fuerza(prev), fuerza(nxt)
        hoy_debil = opp_w is not None and opp_w <= DEBIL
        # revancha: ultimo enfrentamiento previo en la temporada
        rev = False
        for j in range(i - 1, -1, -1):
            if T.d[e][1][j] != sid: break
            if L[j]["rival"] == g["rival"]:
                rev = L[j]["gf"] is not None and L[j]["gf"] < L[j]["ga"]; break
        racha_l = racha_w = 0; j = i - 1
        while j >= 0 and T.d[e][1][j] == sid and L[j]["gf"] is not None and L[j]["gf"] < L[j]["ga"]: racha_l += 1; j -= 1
        j = i - 1
        while j >= 0 and T.d[e][1][j] == sid and L[j]["gf"] is not None and L[j]["gf"] > L[j]["ga"]: racha_w += 1; j -= 1
        my_w = T.wpct(e, f)
        primer_local = lado == "H" and not any(L[j]["local"] for j in range(i - k + 1, i))
        info[lado] = dict(
            Q1=rev,
            Q2=bool(prev and prev["gf"] is not None and prev["gf"] > prev["ga"] and pw is not None and pw >= FUERTE and hoy_debil),
            Q3=bool(hoy_debil and nw is not None and nw >= FUERTE),
            Q4=bool(hoy_debil and pw is not None and pw >= FUERTE and nw is not None and nw >= FUERTE),
            Q5=primer_local,
            Q6a=racha_l >= 5, Q6b=racha_w >= 5,
            Q7=bool(tot >= 20 and k > 0.85 * tot and my_w is not None and my_w <= DEBIL and opp_w is not None and opp_w >= 0.55),
            Q9=bool(coach_nuevo and coach_nuevo(e, gp)))
    for c in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6a", "Q6b", "Q7", "Q9"):
        h = info.get("H") and info["H"][c]; a = info.get("A") and info["A"][c]
        if info.get("H") is None or info.get("A") is None: out[c] = "X"
        else: out[c] = "AMBOS" if (h and a) else ("H" if h else ("A" if a else None))
    if "div" in r: out["Q8"] = "H" if r.get("div") else None
    return out


def tmle(y, A, W):
    y = np.asarray(y, float); A = np.asarray(A, float); W = np.asarray(W, float)
    q = LogisticRegression(C=1e6, max_iter=3000).fit(np.column_stack([A, W]), y)
    Q1 = q.predict_proba(np.column_stack([np.ones_like(A), W]))[:, 1]; Q0 = q.predict_proba(np.column_stack([np.zeros_like(A), W]))[:, 1]
    Qa = np.where(A == 1, Q1, Q0)
    g = np.clip(LogisticRegression(C=1e6, max_iter=3000).fit(W, A).predict_proba(W)[:, 1], 0.025, 0.975)
    Hc = A / g - (1 - A) / (1 - g)
    lgt = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    eps = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-(lgt(Qa) + eps * Hc))); paso = np.sum(Hc * (y - p)) / max(np.sum(Hc ** 2 * p * (1 - p)), 1e-12); eps += paso
        if abs(paso) < 1e-10: break
    Q1s = 1 / (1 + np.exp(-(lgt(Q1) + eps / g))); Q0s = 1 / (1 + np.exp(-(lgt(Q0) - eps / (1 - g))))
    psi = float(np.mean(Q1s - Q0s)); IC = Hc * (y - np.where(A == 1, Q1s, Q0s)) + (Q1s - Q0s) - psi
    return psi, float(np.std(IC, ddof=1) / math.sqrt(len(y)))


def correr(deporte, filas, C, esperado, coach_nuevo=None):
    T = Tabla(C)
    print("\n%s: %d partidos con prediccion as-of" % (deporte, len(filas)))
    S = [(r, situaciones(r, C, T, coach_nuevo)) for r in filas]
    res = {}
    for c, signo in esperado.items():
        if all(c not in s for _, s in S): continue
        rows = []
        for r, s in S:
            lado = s.get(c)
            if lado in ("X", "AMBOS"): continue
            rows.append(dict(r, x=(1 if lado == "H" else (-1 if lado == "A" else 0))))
        nom = NOMBRES[c]
        if rows and "corte" in rows[0]:
            # beisbol: cada liga con su propio corte 70/30 (como en la tanda 1)
            G = [dict(r, fecha=("1" if r["fecha"] >= r["corte"] else "0") + r["fecha"]) for r in rows]
            out = M.evaluar(G, c, nom, deporte, signo, corte="1")
        else:
            out = M.evaluar(rows, c, nom, deporte, signo)
        # TMLE desde el equipo en la situacion
        ys, As, Ws = [], [], []
        for r in rows:
            if r["x"] == 0:
                lado = "H" if zlib.crc32(str(r["gp"]).encode()) % 2 == 0 else "A"; a = 0
            else:
                lado = "H" if r["x"] > 0 else "A"; a = 1
            gano = (r["y"] == 1) if lado == "H" else ((r.get("res") == "A") if "res" in r else (r["y"] == 0))
            p = r["p"] if lado == "H" else ((r.get("paway") if r.get("paway") is not None else 1 - r["p"]))
            p = min(max(p, 1e-4), 1 - 1e-4)
            ys.append(1.0 if gano else 0.0); As.append(a); Ws.append([math.log(p / (1 - p)), 1.0 if lado == "H" else 0.0])
        na = int(sum(As))
        if na >= 50 and len(As) - na >= 50:
            psi, se = tmle(ys, As, Ws)
            print("        TMLE %-4s efecto para el equipo en la situacion: %+5.1f pp  IC [%+5.1f, %+5.1f]  (expuestos %d)" % (
                c, 100 * psi, 100 * (psi - 1.96 * se), 100 * (psi + 1.96 * se), na))
            if out is not None:
                out["tmle_pp"] = round(100 * psi, 2); out["tmle_ic95"] = [round(100 * (psi - 1.96 * se), 2), round(100 * (psi + 1.96 * se), 2)]
                out["tmle_expuestos"] = na
        res[c] = out
    return res


NOMBRES = {"Q1": "revancha (perdio el ultimo cruce)", "Q2": "bajon tras ganarle a un fuerte", "Q3": "mirando adelante",
           "Q4": "sandwich", "Q5": "primer juego en casa", "Q6a": "racha de 5+ derrotas", "Q6b": "racha de 5+ victorias",
           "Q7": "fin de temporada: debil vs en contienda", "Q8": "partido divisional (local)", "Q9": "entrenador nuevo"}
ESP = {"Q1": +1, "Q2": -1, "Q3": -1, "Q4": -1, "Q5": +1, "Q6a": +1, "Q6b": -1, "Q7": -1}


def main():
    _ev = M.evaluar
    M.evaluar = lambda *a, **k: None
    M.correr_hockey(); M.correr_basquet("NBA"); M.correr_americano("NFL"); M.correr_beisbol(["MLB", "NPB", "KBO", "LMP", "LVBP", "LIDOM", "ABL"])
    M.correr_futbol()
    M.evaluar = _ev; M.RESULTADOS.clear()
    todo = {}
    for dep in ("NHL", "NBA", "BEISBOL", "FUTBOL"):
        filas, C = M.ULTIMO[dep]
        if dep == "BEISBOL":
            # cada liga con su corte 70/30: el evaluador usa el 70 % del conjunto ordenado por fecha
            pass
        todo[dep] = correr(dep, filas, C, ESP)
    # NFL: divisional y entrenador nuevo
    filas, C = M.ULTIMO["NFL"]
    seq = {}
    for r in sorted(filas, key=lambda r: r["fecha"]):
        for e, k in ((r["home"], "coach_h"), (r["away"], "coach_a")):
            if r.get(k): seq.setdefault(e, []).append((r["fecha"], r["gp"], r[k]))
    nuevo = {}
    import datetime as _dt
    for e, L in seq.items():
        cambio = None
        for i, (f, gp, co) in enumerate(L):
            if i:
                mismo_anio = (_dt.date.fromisoformat(f[:10]) - _dt.date.fromisoformat(L[i - 1][0][:10])).days <= 60
                if mismo_anio and co != L[i - 1][2]:
                    cambio = i                      # cambio de entrenador a media temporada
                elif not mismo_anio:
                    cambio = None
            if cambio is not None and i - cambio < 3 and co == L[cambio][2]:
                nuevo[(e, gp)] = True
    esp_nfl = dict(ESP); esp_nfl.update({"Q8": -1, "Q9": +1})
    todo["NFL"] = correr("NFL", filas, C, esp_nfl, coach_nuevo=lambda e, gp: nuevo.get((e, gp), False))
    k = sum(1 for r in M.RESULTADOS if "z" in r)
    pasan = [r for r in M.RESULTADOS if r["veredicto"] == "pasa"]
    print("\n" + "=" * 100)
    print("k = %d pruebas con resultado | falsos 'pasa' esperados por azar ~ %.1f | pasan: %d" % (k, 0.023 * k, len(pasan)))
    for r in pasan:
        print("  PASA %-4s %-40s %-8s efecto %+.1f pp/u  z %+.2f" % (r["codigo"], r["angulo"], r["liga"], r["efecto_pp_por_unidad"], r["z"]))
    ruta = os.path.join(M.SALIDA_MD, "2026-10-09_cualitativos_resultados.json")
    json.dump(M.RESULTADOS, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("resultados en", ruta)


if __name__ == "__main__":
    main()
