# -*- coding: utf-8 -*-
"""
utilidades/guardar_lecturas.py - guarda las lecturas de Picks IA hechas en una sesion de Claude (sin API)
con el MISMO formato que utilidades/picks_ia.py, para que el historial y la calificacion sean uno solo.

Entrada: un archivo JSON con una lista de lecturas (formato de ia/instrucciones_picks.md):
  [{"liga":"nhl","id":"401...","lectura":"...","decision":"PICK","mercado":"Ganador","lado":"home",
    "cuota":2.05,"stake":1.0}, ...]

Hace:
  - valida decision, lado, stake y que (liga, id) exista en salida/proximos.json
  - completa partido/fecha/hora desde proximos.json
  - mezcla en salida/picks_ia.json por (liga, id) (no borra lecturas de otras ligas o dias)
  - agrega a salida/historial_ia.csv solo lo nuevo (una lectura por partido; la primera queda registrada)

Uso:
    python utilidades/guardar_lecturas.py trabajo/lecturas_2026-10-02.json
    python utilidades/guardar_lecturas.py trabajo/lecturas.json --origen claude-code --probar
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, datetime as dt, io, json, os

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECISIONES = {"PREMIUM", "PICK", "LEAN", "REVISAR", "PASAR"}
LADOS = {"home", "away", "over", "under", "draw", None}
COLS = ["registrado", "liga", "id", "fecha", "partido", "decision", "mercado", "lado", "cuota", "stake", "lectura"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--origen", default="claude-sesion", help="se guarda en modelo_ia de picks_ia.json")
    ap.add_argument("--probar", action="store_true", help="valida e imprime, no escribe nada")
    a = ap.parse_args()

    with io.open(a.archivo, encoding="utf-8") as f:
        lecturas = json.load(f)
    if isinstance(lecturas, dict):
        lecturas = lecturas.get("lecturas", [])
    with io.open(os.path.join(BASE, "salida", "proximos.json"), encoding="utf-8") as f:
        por_id = {(p["liga"], str(p["id"])): p for p in json.load(f)["partidos"]}

    ok, errores = [], []
    for l in lecturas:
        l["id"] = str(l.get("id"))
        p = por_id.get((l.get("liga"), l["id"]))
        if not p:
            errores.append("%s %s: no esta en proximos.json" % (l.get("liga"), l["id"])); continue
        dec = str(l.get("decision", "")).upper()
        if dec not in DECISIONES:
            errores.append("%s %s: decision invalida %r" % (l["liga"], l["id"], l.get("decision"))); continue
        l["decision"] = dec
        if l.get("lado") not in LADOS:
            errores.append("%s %s: lado invalido %r" % (l["liga"], l["id"], l.get("lado"))); continue
        if dec in ("PREMIUM", "PICK"):
            if not l.get("mercado") or l.get("cuota") is None:
                errores.append("%s %s: %s sin mercado o sin cuota" % (l["liga"], l["id"], dec)); continue
            if float(l["cuota"]) < 1.80:
                errores.append("%s %s: cuota %.2f < 1.80" % (l["liga"], l["id"], float(l["cuota"]))); continue
            l["stake"] = 1.0
        else:
            l["stake"] = 0.0
        if not str(l.get("lectura", "")).strip():
            errores.append("%s %s: lectura vacia" % (l["liga"], l["id"])); continue
        l["partido"] = "%s @ %s" % (p["away"]["nombre"], p["home"]["nombre"])
        l["fecha"], l["hora"] = p["fecha"], p.get("hora")
        ok.append(l)

    for e in errores:
        print("ERROR", e)
    print("%d lecturas validas, %d con error" % (len(ok), len(errores)))
    if a.probar or not ok:
        return 1 if errores else 0

    ahora = dt.datetime.now().isoformat(timespec="seconds")
    rj = os.path.join(BASE, "salida", "picks_ia.json")
    previas = []
    if os.path.exists(rj):
        with io.open(rj, encoding="utf-8") as f:
            previas = json.load(f).get("lecturas", [])
    nuevas_ids = {(l["liga"], l["id"]) for l in ok}
    mezcla = [l for l in previas if (l.get("liga"), str(l.get("id"))) not in nuevas_ids] + ok
    with io.open(rj, "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "modelo_ia": a.origen, "lecturas": mezcla}, f, ensure_ascii=False, indent=1)

    rh = os.path.join(BASE, "salida", "historial_ia.csv")
    vistos = set()
    if os.path.exists(rh):
        with io.open(rh, encoding="utf-8-sig", newline="") as f:
            vistos = {(r["liga"], r["id"]) for r in csv.DictReader(f)}
    nuevos = [l for l in ok if (l["liga"], l["id"]) not in vistos]
    escribir_cab = not os.path.exists(rh) or os.path.getsize(rh) == 0
    with io.open(rh, "a", encoding="utf-8-sig" if escribir_cab else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if escribir_cab:
            w.writeheader()
        for l in nuevos:
            w.writerow({"registrado": ahora, **{k: l.get(k, "") for k in COLS[1:]}})
    print("picks_ia.json: %d lecturas en total | historial_ia.csv: %d nuevas" % (len(mezcla), len(nuevos)))
    for l in ok:
        if l["decision"] in ("PREMIUM", "PICK"):
            print("  %-7s %s %s | %s | %s %s a %s" % (l["decision"], l["fecha"], l["hora"], l["partido"],
                                                    l["mercado"], l["lado"], l["cuota"]))
    return 1 if errores else 0


if __name__ == "__main__":
    _sys.exit(main())
