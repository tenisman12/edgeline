# -*- coding: utf-8 -*-
"""
colectores/recolectar_arbitros_nhl.py - arbitros de cada partido de NHL (API publica de la NHL) y medicion de su efecto
en goles totales y castigos, fuera de muestra.

Baja (incremental, solo los partidos que faltan de datos/hockey.csv):
    https://api-web.nhle.com/v1/gamecenter/<gameId>/right-rail   -> gameInfo.referees / gameInfo.linesmen
    (si no trae arbitros, prueba /landing)
Guarda datos/equipos/nhl_arbitros.csv: game_id, fecha, arbitro1, arbitro2, juez_linea1, juez_linea2.

Mide (--medir, o al final de la bajada): por arbitro, residuo medio de goles totales y de minutos de castigo de sus
partidos ANTERIORES (encogido), contra una base as-of (promedio de ambos equipos). Protocolo: z >= 2 y las dos mitades.
Escribe modelos/arbitros_nhl.json.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python colectores\\recolectar_arbitros_nhl.py --prueba 2025020001     (un partido, imprime lo que contesta)
    python colectores\\recolectar_arbitros_nhl.py                         (baja lo que falta y mide)
    python colectores\\recolectar_arbitros_nhl.py --medir
"""
import argparse, csv, json, math, os, sys, time, urllib.request, datetime as dt

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SALIDA = os.path.join(BASE, "datos", "equipos", "nhl_arbitros.csv")
URLS = ("https://api-web.nhle.com/v1/gamecenter/%s/right-rail", "https://api-web.nhle.com/v1/gamecenter/%s/landing")
COLS = ["game_id", "fecha", "arbitro1", "arbitro2", "juez_linea1", "juez_linea2"]
K = 40


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Edgeline)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _nombres(lista):
    out = []
    for x in lista or []:
        if isinstance(x, dict):
            # formato real (api-web, 2026): {"fullName": {"default": "Kelly Sutherland"}, "sweaterNumber": 11}
            v = x.get("fullName") or x.get("default") or x.get("name")
            if isinstance(v, dict):
                v = v.get("default")
            if not v:
                v = ((x.get("firstName") or {}).get("default", "") + " " + (x.get("lastName") or {}).get("default", ""))
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        elif isinstance(x, str):
            out.append(x)
    return out


def _buscar(d):
    """encuentra referees/linesmen en cualquier nivel del JSON."""
    if isinstance(d, dict):
        if "referees" in d:
            return _nombres(d.get("referees")), _nombres(d.get("linesmen"))
        for v in d.values():
            r = _buscar(v)
            if r and r[0]:
                return r
    elif isinstance(d, list):
        for v in d:
            r = _buscar(v)
            if r and r[0]:
                return r
    return None


def arbitros(gid):
    for u in URLS:
        try:
            r = _buscar(_get(u % gid))
        except Exception:
            r = None
        if r and r[0]:
            return r
    return None


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def partidos():
    out = {}
    with open(os.path.join(BASE, "datos", "hockey.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if str(r.get("is_home")).replace(".0", "") != "1":
                continue
            out[str(r.get("gamePk")).split(".")[0]] = r
    return out


def leer():
    if not os.path.exists(SALIDA):
        return {}
    with open(SALIDA, encoding="utf-8-sig", newline="") as f:
        return {r["game_id"]: r for r in csv.DictReader(f)}


def guardar(ya):
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(sorted(ya.values(), key=lambda r: (r["fecha"], r["game_id"])))


def bajar(max_n=None):
    P = partidos(); ya = leer()
    falta = [g for g in sorted(P, key=lambda g: P[g].get("game_date") or "") if g not in ya]
    if max_n:
        falta = falta[-max_n:]
    print("Partidos sin arbitros: %d" % len(falta))
    for i, g in enumerate(falta, 1):
        r = arbitros(g)
        if r:
            refs, lin = r
            ya[g] = {"game_id": g, "fecha": (P[g].get("game_date") or "")[:10], "arbitro1": refs[0] if refs else "",
                     "arbitro2": refs[1] if len(refs) > 1 else "", "juez_linea1": lin[0] if lin else "", "juez_linea2": lin[1] if len(lin) > 1 else ""}
        if i % 200 == 0:
            guardar(ya); print("   ... %d/%d" % (i, len(falta)))
        time.sleep(0.15)
    guardar(ya)
    print("Listo: %d partidos con arbitros en %s" % (len(ya), SALIDA))


def medir():
    P = partidos(); A = leer()
    G = []
    for g, r in P.items():
        a = A.get(g)
        gh, ga = _f(r.get("goals")), _f(r.get("goals_opp"))
        pim = (_f(r.get("pim")) or 0) + (_f(r.get("pim_opp")) or 0)
        if a and gh is not None and ga is not None:
            G.append({"f": (r.get("game_date") or "")[:10], "h": r.get("team"), "a": r.get("opp"), "tot": gh + ga, "pim": pim,
                      "refs": [x for x in (a["arbitro1"], a["arbitro2"]) if x]})
    G.sort(key=lambda x: x["f"])
    if len(G) < 500:
        print("Muy pocos partidos con arbitros (%d)." % len(G)); return 1
    res = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "n": len(G)}
    for campo in ("tot", "pim"):
        eq = {}; ref = {}; lg = [0.0, 0]; d = []
        for g in G:
            lgm = lg[0] / lg[1] if lg[1] else (6.0 if campo == "tot" else 16.0)
            def m(t):
                s, n = eq.get(t, (0.0, 0)); return (s + 20 * lgm) / (n + 20)
            base = (m(g["h"]) + m(g["a"])) / 2
            aj = sum((ref.get(x, (0.0, 0))[0] / (ref.get(x, (0.0, 0))[1] + K)) for x in g["refs"]) / max(1, len(g["refs"]))
            y = g[campo]
            if lg[1] > 1000:
                d.append(((y - base) ** 2 - (y - base - aj) ** 2, abs(y - base) - abs(y - base - aj)))
            for x in g["refs"]:
                s, n = ref.get(x, (0.0, 0)); ref[x] = (s + (y - base), n + 1)
            for t in (g["h"], g["a"]):
                s, n = eq.get(t, (0.0, 0)); eq[t] = (s + y, n + 1)
            lg[0] += y; lg[1] += 1
        N = len(d); h = N // 2
        def z(i):
            x = [v[i] for v in d]; mu = sum(x) / N; sd = math.sqrt(sum((v - mu) ** 2 for v in x) / (N - 1)) or 1e-9
            return mu, mu / (sd / math.sqrt(N)), [sum(x[:h]) / h, sum(x[h:]) / (N - h)]
        mse, zm, _ = z(0); mae, za, mit = z(1)
        ok = N >= 300 and za >= 2.0 and min(mit) > 0
        nom = "goles totales" if campo == "tot" else "minutos de castigo"
        print("  %-18s n=%d  MAE %+.4f (z %.2f)  MSE %+.4f (z %.2f)  mitades %s -> %s" % (
            nom, N, mae, za, mse, zm, [round(v, 4) for v in mit], "APLICAR" if ok else "sin mejora demostrada"))
        res[campo] = {"mejora_mae": round(mae, 4), "z_mae": round(za, 2), "mejora_mse": round(mse, 4), "z_mse": round(zm, 2),
                      "mitades_mae": [round(v, 4) for v in mit], "veredicto": "APLICAR" if ok else "sin mejora demostrada",
                      "arbitros": {x: round(s / (n + K), 3) for x, (s, n) in ref.items() if n >= 30}}
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelos", "arbitros_nhl.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prueba"); ap.add_argument("--medir", action="store_true"); ap.add_argument("--max", type=int)
    a = ap.parse_args()
    if a.prueba:
        for u in URLS:
            try:
                d = _get(u % a.prueba); print(u % a.prueba, "->", _buscar(d))
            except Exception as e:
                print(u % a.prueba, "error:", str(e)[:120])
        return 0
    if not a.medir:
        bajar(a.max)
    return medir()


if __name__ == "__main__":
    sys.exit(main())
