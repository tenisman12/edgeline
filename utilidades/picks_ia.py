# -*- coding: utf-8 -*-
"""
utilidades/picks_ia.py - PICKS IA: la lectura razonada de cada partido, generada por Claude a partir del paquete
completo de Edgeline (modelo, cuotas, precio sharp, forma/osciladores, H2H, movimiento, consenso, lesiones,
puntaje Pick Premium). Sigue las reglas de ia/instrucciones_picks.md.

Entrada:  salida/proximos.json (lo escribe plataforma.py)
Salida:   salida/picks_ia.json        lectura y decision por partido (el dia que se pide)
          salida/historial_ia.csv     una fila por lectura, para medir a la IA contra el puntaje y contra el modelo

Llave: variable de entorno ANTHROPIC_API_KEY (en Actions: secret ANTHROPIC_API_KEY). Nunca en el codigo ni en el chat.
Modelo: EDGELINE_IA_MODELO (por defecto claude-sonnet-5-5).

Uso:
    python utilidades\\picks_ia.py                 # partidos de hoy y manana con cuota
    python utilidades\\picks_ia.py --dias 1 --ligas mlb,nhl
    python utilidades\\picks_ia.py --simular        # sin llamar a la API: prueba el empaquetado y el guardado
"""
import argparse, csv, datetime as dt, io, json, os, sys, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = "https://api.anthropic.com/v1/messages"
MODELO = os.environ.get("EDGELINE_IA_MODELO", "claude-sonnet-5-5")
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LOTE = 12          # partidos por llamada
TZ = -6


def _paquete(p):
    """Lo que ve la IA de cada partido: todo lo relevante, sin bloques pesados (estadisticas largas)."""
    k = {x: p.get(x) for x in ("liga", "id", "fecha", "hora", "nota", "serie", "estadio", "pretemporada", "modelo",
                               "cuotas", "mercados", "consenso", "movimiento", "h2h_datos", "validacion", "alerta")}
    k["home"] = {x: p["home"].get(x) for x in ("nombre", "record", "probable", "probable_rol", "ranking")}
    k["away"] = {x: p["away"].get(x) for x in ("nombre", "record", "probable", "probable_rol", "ranking")}
    f = p.get("forma") or {}
    def forma(t):
        if not t:
            return None
        return {x: t.get(x) for x in ("racha", "record", "status", "osciladores", "ou4", "elo", "power", "ranking", "carga")} | \
               {"L10": ((t.get("ventanas") or {}).get("L10")), "temp": ((t.get("ventanas") or {}).get("temp")),
                "ultimos5": (t.get("ultimos10") or [])[:5]}
    k["forma"] = {"home": forma(f.get("home")), "away": forma(f.get("away"))}
    c = p.get("contexto") or {}
    k["contexto"] = {"lesiones": c.get("lesiones"), "espn_pred_home": c.get("espn_pred_home"), "ats": c.get("ats")}
    k["premium"] = [{x: q.get(x) for x in ("mercado", "lado", "texto", "nivel", "puntaje", "senales", "cuota", "casa",
                                           "p_sharp", "p_modelo", "p_final", "ev", "cuota_min", "razones", "razonamiento")}
                    for q in (p.get("picks") or []) if q.get("nivel") != "pasar" or q.get("puntaje", 0) >= 40]
    return k


def _llamar(instrucciones, paquete):
    body = {"model": MODELO, "max_tokens": 4000,
            "system": instrucciones + "\n\nResponde SOLO con el JSON (lista), sin texto alrededor.",
            "messages": [{"role": "user", "content": "Partidos:\n" + json.dumps(paquete, ensure_ascii=False)}]}
    req = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"),
                                 headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    txt = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[txt.find("["):txt.rfind("]") + 1]
    return json.loads(txt)


def _simular(paquete):
    out = []
    for p in paquete:
        top = max(p["premium"], key=lambda q: q.get("puntaje") or 0) if p["premium"] else None
        out.append({"liga": p["liga"], "id": p["id"], "decision": (top["nivel"].upper() if top else "PASAR"),
                    "mercado": top["mercado"] if top else None, "lado": top["lado"] if top else None,
                    "cuota": top["cuota"] if top else None, "stake": 0.01 if top and top["nivel"] == "pick" else 0.0,
                    "lectura": (top["razonamiento"] if top else "Sin candidatos con puntaje.") + " [simulado]"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=2)
    ap.add_argument("--ligas", help="coma: mlb,nhl,...")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--todos", action="store_true", help="incluir partidos sin cuota (por defecto solo con cuota)")
    a = ap.parse_args()
    ruta = os.path.join(BASE, "salida", "proximos.json")
    with io.open(ruta, encoding="utf-8") as f:
        D = json.load(f)
    hoy = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()
    lim = (hoy + dt.timedelta(days=a.dias - 1)).isoformat()
    ligas = set(x.strip() for x in a.ligas.split(",")) if a.ligas else None
    sel = [p for p in D["partidos"] if p.get("modelo") and hoy.isoformat() <= p["fecha"] <= lim
           and (ligas is None or p["liga"] in ligas) and (a.todos or (p.get("cuotas") or {}).get("ml_home"))]
    if not sel:
        print("No hay partidos que leer."); return
    with io.open(os.path.join(BASE, "ia", "instrucciones_picks.md"), encoding="utf-8") as f:
        instr = f.read()
    if not a.simular and not KEY:
        print("Falta ANTHROPIC_API_KEY (variable de entorno / secret). Usa --simular para probar sin API."); return 1
    paquetes = [_paquete(p) for p in sel]
    lecturas = []
    for i in range(0, len(paquetes), LOTE):
        lote = paquetes[i:i + LOTE]
        try:
            res = _simular(lote) if a.simular else _llamar(instr, lote)
        except Exception as e:
            print("  lote %d: error %s" % (i // LOTE + 1, str(e)[:120])); continue
        lecturas += res
        print("  lote %d/%d: %d lecturas" % (i // LOTE + 1, (len(paquetes) + LOTE - 1) // LOTE, len(res)))
    ahora = dt.datetime.now().isoformat(timespec="seconds")
    por_id = {(p["liga"], p["id"]): p for p in sel}
    for l in lecturas:
        p = por_id.get((l.get("liga"), str(l.get("id"))))
        if p:
            l["partido"] = "%s @ %s" % (p["away"]["nombre"], p["home"]["nombre"]); l["fecha"] = p["fecha"]; l["hora"] = p["hora"]
    with io.open(os.path.join(BASE, "salida", "picks_ia.json"), "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "modelo_ia": MODELO if not a.simular else "simulado", "lecturas": lecturas}, f, ensure_ascii=False, indent=1)
    rh = os.path.join(BASE, "salida", "historial_ia.csv")
    cols = ["registrado", "liga", "id", "fecha", "partido", "decision", "mercado", "lado", "cuota", "stake", "lectura"]
    vistos = set()
    if os.path.exists(rh):
        with io.open(rh, encoding="utf-8-sig", newline="") as f:
            vistos = {(r["liga"], r["id"]) for r in csv.DictReader(f)}
    nuevos = [l for l in lecturas if (l.get("liga"), str(l.get("id"))) not in vistos]
    with io.open(rh, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not vistos and f.tell() == 0:
            w.writeheader()
        for l in nuevos:
            w.writerow({"registrado": ahora, **{k: l.get(k, "") for k in cols[1:]}})
    print("Picks IA: %d lecturas (%d nuevas en historial_ia.csv) -> salida/picks_ia.json" % (len(lecturas), len(nuevos)))
    for l in lecturas:
        if l.get("decision") in ("PREMIUM", "PICK"):
            print("  %-7s %s %s | %s | %s %s a %s" % (l["decision"], l.get("fecha"), l.get("hora"), l.get("partido"), l.get("mercado"), l.get("lado"), l.get("cuota")))


if __name__ == "__main__":
    sys.exit(main() or 0)
