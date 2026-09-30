# -*- coding: utf-8 -*-
"""
EXTRAER ESPN - convierte el summary.jsonl crudo en tablas usables.

Lee data_maestra/espn_<liga>_summary.jsonl (lo genera recolectar_espn.py modo 'juegos')
y saca:
  espn_<liga>_winprob.csv   - win probability de ESPN (apertura=pregame, final) por juego.
                              La pregame es el modelo de ESPN: BENCHMARK para comparar.
  espn_<liga>_players.csv    - box score por JUGADOR (para paneles profundos).
  espn_<liga>_gameinfo.csv   - estadio, asistencia, arbitros.

Nota: para juegos pasados, ESPN NO trae cuotas en el summary (odds vacio); esas van por
The Odds API. Aqui sacamos lo que si esta: win prob, box de jugadores, contexto.

Uso:
    python extraer_espn.py --liga nba
"""
import argparse, csv, io, os, json

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")


def _meta(sm):
    h = sm.get("header") or {}
    comp = ((h.get("competitions") or [{}])[0])
    home = away = ""; hs = as_ = ""
    for c in comp.get("competitors", []):
        ab = (c.get("team") or {}).get("abbreviation")
        if c.get("homeAway") == "home": home = ab; hs = c.get("score")
        else: away = ab; as_ = c.get("score")
    return {"home": home, "away": away, "home_score": hs, "away_score": as_,
            "game_date": (comp.get("date") or "")[:10]}


def extraer(liga):
    JL = os.path.join(BASE, "data_maestra", "espn_%s_summary.jsonl" % liga)
    if not os.path.exists(JL):
        print("No existe", JL); return
    wp, players, gi = [], [], []
    n = 0
    for line in io.open(JL, encoding="utf-8"):
        try:
            o = json.loads(line); sm = o["summary"]; gid = o.get("game_id")
        except Exception:
            continue
        m = _meta(sm); n += 1
        # win probability (ESPN)
        w = sm.get("winprobability") or []
        if w:
            wp.append({"game_id": gid, **m,
                       "espn_wp_home_pregame": round(w[0].get("homeWinPercentage", ""), 4) if w[0].get("homeWinPercentage") is not None else "",
                       "espn_wp_home_final": round(w[-1].get("homeWinPercentage", ""), 4) if w[-1].get("homeWinPercentage") is not None else "",
                       "n_puntos": len(w)})
        # box score por jugador: UNA fila por jugador, stats etiquetadas por categoria
        # (NFL/MLB/soccer tienen varias categorias: pase/acarreo/recepcion/despeje...).
        for tb in (sm.get("boxscore") or {}).get("players") or []:
            team = (tb.get("team") or {}).get("abbreviation")
            bloques = tb.get("statistics") or []
            multi = len(bloques) > 1
            pmap = {}
            for i, st in enumerate(bloques):
                labels = st.get("labels") or []
                # categoria del bloque (pase, acarreo...). Si no viene y hay varios, usa indice.
                cat = (st.get("name") or st.get("text") or st.get("type") or "")
                cat = "".join(c for c in str(cat).lower() if c.isalnum())
                if multi and not cat:
                    cat = "g%d" % i
                pref = ("e_%s_" % cat) if cat else "e_"
                for a in st.get("athletes") or []:
                    ath = a.get("athlete") or {}
                    nom = ath.get("displayName")
                    fila = pmap.setdefault(nom, {
                        "game_id": gid, "game_date": m["game_date"], "team": team, "jugador": nom,
                        "posicion": (ath.get("position") or {}).get("abbreviation", "") if isinstance(ath.get("position"), dict) else "",
                        "titular": 1 if a.get("starter") else 0,
                        "jugo": 0 if a.get("didNotPlay") else 1})
                    for lab, val in zip(labels, a.get("stats") or []):
                        fila[pref + lab] = val
            players.extend(pmap.values())
        # contexto
        info = sm.get("gameInfo") or {}
        gi.append({"game_id": gid, **m,
                   "venue": (info.get("venue") or {}).get("fullName"),
                   "attendance": info.get("attendance"),
                   "arbitros": "; ".join(o.get("displayName", "") for o in (info.get("officials") or []))})

    def guardar(filas, nombre, fijas):
        if not filas:
            print("  (sin %s)" % nombre); return
        OUT = os.path.join(BASE, "data_maestra", nombre)
        extras = sorted({k for f in filas for k in f if k not in fijas})
        cols = fijas + extras
        with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(filas)
        print("  %-28s %d filas, %d cols" % (nombre, len(filas), len(cols)))

    print("Procesados %d juegos:" % n)
    guardar(wp, "espn_%s_winprob.csv" % liga, ["game_id", "game_date", "home", "away", "home_score", "away_score"])
    guardar(players, "espn_%s_players.csv" % liga, ["game_id", "game_date", "team", "jugador", "posicion", "titular", "jugo"])
    guardar(gi, "espn_%s_gameinfo.csv" % liga, ["game_id", "game_date", "home", "away"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--liga", required=True)
    extraer(ap.parse_args().liga)
