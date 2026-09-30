# -*- coding: utf-8 -*-
"""
GUARDAR JSON ESPN - baja una URL de ESPN y la guarda cruda, con las mismas cabeceras
que usa recolectar_espn.py (ESPN bloquea el agente de PowerShell).

Uso (en C:\\Edgeline):
    python guardar_json_espn.py tennis atp 20260922
    python guardar_json_espn.py tennis wta 20260922
Guarda data_maestra\\<liga>_scoreboard_raw.json
"""
import io, os, sys, json, urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")


def main():
    if len(sys.argv) < 4:
        print("Uso: python guardar_json_espn.py <deporte> <liga> <AAAAMMDD>"); return
    sport, league, fecha = sys.argv[1:4]
    url = "https://site.api.espn.com/apis/site/v2/sports/%s/%s/scoreboard?dates=%s&limit=500" % (sport, league, fecha)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as r:
        data = json.load(r)
    out = os.path.join(BASE, "data_maestra", "%s_scoreboard_raw.json" % league)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("Guardado:", out, "(%d eventos)" % len(data.get("events", [])))


if __name__ == "__main__":
    main()
