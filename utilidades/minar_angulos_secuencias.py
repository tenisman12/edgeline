# -*- coding: utf-8 -*-
"""
utilidades/minar_angulos_secuencias.py - red convolucional sobre la secuencia de partidos, random forest y TMLE por angulo.

Complemento de minar_angulos_bayes_hockey.py / minar_angulos_bayes.py (mismas filas, mismo walk-forward, mismo veredicto).

Hipotesis (registradas antes de correr, 10-oct-2026):
  H-CNN  una red convolucional 1D que lee los ultimos 10 partidos de cada equipo (gano, local, descanso, residuo contra el
         modelo, dias desde ese juego) encuentra patrones de racha o reversion que el modelo no tiene: mejora la prediccion
         as-of fuera de muestra (z >= 2.0, las dos mitades, calibrado).
  H-RF   un random forest con logit(p), liga y todos los angulos mejora la prediccion as-of (mismo criterio).
  TMLE   efecto causal de cada angulo sobre ganar, ajustado por la probabilidad del modelo y la sede, en toda la muestra;
         con k angulos se exige |z| >= z de Bonferroni (0.05 / k, dos colas). Es estimacion, no prediccion.

La base de la comparacion es la misma recalibracion por liga (a_liga + b_liga * logit p) sin angulos ni secuencias.
Walk-forward: reentrena cada 3 meses (costo), predice cada mes con lo entrenado antes.

Uso:
    python utilidades/minar_angulos_secuencias.py --deporte hockey|nba|beisbol
Necesita las filas en cache (correr antes minar_angulos_bayes_hockey.py o minar_angulos_bayes.py --deporte X) y torch.
Escribe trabajo/minar/2026-10-10_secuencias_<deporte>_resultados.json
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, json, math, os, pickle, sys
from collections import defaultdict, deque

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
CODIGO = os.path.dirname(AQUI)
sys.path.insert(0, CODIGO); sys.path.insert(0, AQUI)
import minar_angulos_bayes_hockey as B  # noqa: E402

LARGO = 10          # partidos previos por equipo
CANALES = 6         # gano, local, descanso/7, residuo contra el modelo, dias desde ese juego/30, hay dato


def cargar(dep):
    if dep == "hockey":
        F = pickle.load(open(B.RUTA_CACHE, "rb"))
        return F, B.LIGAS, B.ANG
    import minar_angulos_bayes as G
    cfg = G.CFG[dep]
    F = pickle.load(open(os.path.join(CODIGO, "trabajo", "minar", "bayes_%s_filas.pkl" % dep), "rb"))
    F = [r for r in F if r["liga"] in cfg["ligas"]]
    return F, cfg["ligas"], cfg["ang"]


def secuencias(F):
    """para cada partido, los ultimos LARGO partidos de local y visita ANTES de esa fecha (sin fuga)."""
    hist = defaultdict(lambda: deque(maxlen=LARGO))
    ultimo = {}
    S = np.zeros((len(F), 2, LARGO, CANALES), np.float32)
    porfecha = defaultdict(list)
    for i, r in enumerate(F):
        porfecha[r["fecha"]].append(i)
    for f in sorted(porfecha):
        fd = dt.date.fromisoformat(f)
        for i in porfecha[f]:                                  # primero se leen todas las secuencias del dia
            r = F[i]
            for k, e in enumerate((r["home"], r["away"])):
                H = list(hist[(r["liga"], e)])
                for j, g in enumerate(reversed(H)):            # j = 0 es el partido mas reciente
                    S[i, k, LARGO - 1 - j] = [g[0], g[1], g[2], g[3], min((fd - g[4]).days, 60) / 30.0, 1.0]
        for i in porfecha[f]:                                  # y despues se agregan los resultados del dia
            r = F[i]
            for e, local, gano, p in ((r["home"], 1.0, r["y"], r["p"]), (r["away"], 0.0, 1 - r["y"], 1 - r["p"])):
                key = (r["liga"], e)
                desc = min((fd - ultimo[key]).days, 14) / 7.0 if key in ultimo else 1.0
                hist[key].append((float(gano), local, desc, float(gano) - p, fd))
                ultimo[key] = fd
    return S


# ------------------------------------------------------------------ red convolucional
def _cnn(nl):
    import torch
    import torch.nn as nn

    class Red(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Sequential(nn.Conv1d(CANALES, 16, 3, padding=1), nn.ReLU(), nn.Conv1d(16, 16, 3, padding=1), nn.ReLU())
            self.cab = nn.Sequential(nn.Linear(48, 16), nn.ReLU(), nn.Linear(16, 1))
            self.a = nn.Parameter(torch.zeros(nl)); self.b = nn.Parameter(torch.ones(nl))

        def forward(self, seq, off, li):
            n = seq.shape[0]
            z = self.conv(seq.reshape(n * 2, LARGO, CANALES).transpose(1, 2)).mean(dim=2).reshape(n, 2, 16)
            h, a = z[:, 0], z[:, 1]
            return self.a[li] + self.b[li] * off + self.cab(torch.cat([h, a, h - a], dim=1)).squeeze(1)
    return Red()


def entrenar_cnn(S, off, li, y, nl, semilla=0):
    import torch
    torch.manual_seed(semilla); np.random.seed(semilla)
    n = len(y); cut = int(n * 0.85)                            # ultimo 15 % del entrenamiento para parar a tiempo
    T = lambda a, t=torch.float32: torch.tensor(a, dtype=t)
    Xs, Xo, Xl, Y = T(S), T(off), T(li, torch.long), T(y)
    m = _cnn(nl)
    opt = torch.optim.Adam(m.parameters(), lr=2e-3, weight_decay=1e-3)
    perd = torch.nn.BCEWithLogitsLoss()
    mejor, estado, paciencia = 1e9, None, 0
    for ep in range(40):
        m.train()
        idx = np.random.permutation(cut)
        for k in range(0, cut, 256):
            bi = idx[k:k + 256]
            opt.zero_grad(); l = perd(m(Xs[bi], Xo[bi], Xl[bi]), Y[bi]); l.backward(); opt.step()
        m.eval()
        with torch.no_grad():
            v = float(perd(m(Xs[cut:], Xo[cut:], Xl[cut:]), Y[cut:]))
        if v < mejor - 1e-5:
            mejor, estado, paciencia = v, {k: t.clone() for k, t in m.state_dict().items()}, 0
        else:
            paciencia += 1
            if paciencia >= 4:
                break
    m.load_state_dict(estado)
    m.eval()
    return m


def predecir_cnn(m, S, off, li):
    import torch
    with torch.no_grad():
        z = m(torch.tensor(S), torch.tensor(off, dtype=torch.float32), torch.tensor(li, dtype=torch.long))
    return 1 / (1 + np.exp(-z.numpy()))


# ------------------------------------------------------------------ walk-forward
def walk_forward(F, S, cada=3, inicio_frac=0.4):
    from sklearn.ensemble import RandomForestClassifier
    i0 = int(len(F) * inicio_frac)
    meses = sorted({r["fecha"][:7] for r in F[i0:]})
    idx_mes = defaultdict(list)
    for i, r in enumerate(F):
        idx_mes[r["fecha"][:7]].append(i)
    out, mods = [], None
    nl = len(B.LIGAS)
    for k, m in enumerate(meses):
        tr = [i for mm in idx_mes if mm < m for i in idx_mes[mm]]
        te = idx_mes[m]
        if len(tr) < 2000 or not te:
            continue
        tr.sort()
        Ftr, Fte = [F[i] for i in tr], [F[i] for i in te]
        li, off, X, y, sd = B.matrices(Ftr)
        lt, ot, Xt, yt, _ = B.matrices(Fte, sd)
        if mods is None or k % cada == 0:
            mb = B.Jerarquico(nl, len(B.ANG), 1, 1, con_angulos=False).ajustar(li, off, X, y)
            Z = np.column_stack([off, np.eye(nl)[li], X])
            rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=200, max_features=0.3, n_jobs=-1, random_state=0).fit(Z, y)
            cnn = entrenar_cnn(S[tr], off, li, y, nl)
            mods = (mb, rf, cnn)
            print("  %s  reentrena con %6d partidos" % (m, len(tr)))
        mb, rf, cnn = mods
        q0 = mb.predecir(lt, ot, Xt)
        qr = rf.predict_proba(np.column_stack([ot, np.eye(nl)[lt], Xt]))[:, 1]
        qc = predecir_cnn(cnn, S[te], ot, lt)
        for r, a, b_, c in zip(Fte, q0, qr, qc):
            out.append(dict(liga=r["liga"], fecha=r["fecha"], y=r["y"], q0=float(a), qr=float(b_), qc=float(c)))
    return out


# ------------------------------------------------------------------ TMLE por angulo (toda la muestra)
def tmle_angulos(F):
    import minar_cualitativos as Q
    import zlib
    k = len(B.ANG)
    zc = _z_bonf(0.05 / k)
    res = []
    for c in B.ANG:
        ys, As, Ws = [], [], []
        for r in F:
            x = r["x"].get(c, 0.0)
            if x == 0:
                lado = "H" if zlib.crc32(r["gp"].encode()) % 2 == 0 else "A"; a = 0
            else:
                lado = "H" if x > 0 else "A"; a = 1
            gano = r["y"] == 1 if lado == "H" else r["y"] == 0
            p = r["p"] if lado == "H" else 1 - r["p"]
            p = min(max(p, 1e-4), 1 - 1e-4)
            ys.append(1.0 if gano else 0.0); As.append(a); Ws.append([math.log(p / (1 - p)), 1.0 if lado == "H" else 0.0])
        na = int(sum(As))
        if na < 50 or len(As) - na < 50:
            res.append({"codigo": c, "expuestos": na, "sin_estimacion": True}); continue
        psi, se = Q.tmle(ys, As, Ws)
        z = psi / se if se > 0 else 0.0
        res.append({"codigo": c, "expuestos": na, "efecto_pp": round(100 * psi, 2),
                    "ic95": [round(100 * (psi - 1.96 * se), 2), round(100 * (psi + 1.96 * se), 2)], "z": round(z, 2),
                    "pasa_bonferroni": abs(z) >= zc})
    return {"k": k, "z_bonferroni": round(zc, 2), "angulos": sorted(res, key=lambda r: -abs(r.get("z") or 0))}


def _z_bonf(alfa):
    from scipy.stats import norm
    return float(norm.ppf(1 - alfa / 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deporte", required=True, choices=["hockey", "nba", "beisbol"])
    a = ap.parse_args()
    F, ligas, ang = cargar(a.deporte)
    if "home" not in F[0]:
        sys.exit("las filas en cache no traen home/away: vuelve a correr minar_angulos_bayes.py --deporte %s sin --cache" % a.deporte)
    B.LIGAS, B.ANG = ligas, ang
    print("%s: %d partidos, %d angulos" % (a.deporte, len(F), len(ang)))
    S = secuencias(F)
    print("secuencias listas: %s" % (S.shape,))
    P = walk_forward(F, S)
    nombre = {"hockey": "HOCKEY", "nba": "BASQUET", "beisbol": "BEISBOL"}[a.deporte]
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "deporte": a.deporte}
    for clave, etiqueta in (("qc", "red convolucional (10 partidos)"), ("qr", "random forest")):
        res[etiqueta] = {"total": B.veredicto([dict(p, q1=p[clave]) for p in P], nombre),
                         "por_liga": [B.veredicto([dict(p, q1=p[clave]) for p in P if p["liga"] == L], L) for L in ligas]}
    print("\nRESULTADO")
    for etiqueta in ("red convolucional (10 partidos)", "random forest"):
        for v in [res[etiqueta]["total"]] + res[etiqueta]["por_liga"]:
            if v.get("n"):
                print("  %-32s %-8s n %6d  mejora %+.3f mil  z %+5.2f  mitades %+.3f/%+.3f  Brier %+.2f%%  cal %+.4f  -> %s" % (
                    etiqueta, v["grupo"], v["n"], v["mejora_milesimas"], v["z"], v["mitades"][0], v["mitades"][1],
                    v["brier_mejora_pct"], v["calibracion"], v["veredicto"].upper()))
    print("\nTMLE por angulo (toda la muestra)")
    T = tmle_angulos(F)
    res["tmle"] = T
    print("  k %d, z de Bonferroni %.2f" % (T["k"], T["z_bonferroni"]))
    for r in T["angulos"]:
        if r.get("sin_estimacion"):
            print("  %-4s expuestos %6d  sin estimacion" % (r["codigo"], r["expuestos"])); continue
        print("  %-4s expuestos %6d  efecto %+5.2f pp  IC [%+5.2f, %+5.2f]  z %+5.2f  %s" % (
            r["codigo"], r["expuestos"], r["efecto_pp"], r["ic95"][0], r["ic95"][1], r["z"], "PASA" if r["pasa_bonferroni"] else ""))
    ruta = os.path.join(CODIGO, "trabajo", "minar", "2026-10-10_secuencias_%s_resultados.json" % a.deporte)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nresultados en", ruta)


if __name__ == "__main__":
    main()
