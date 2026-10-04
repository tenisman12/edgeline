# -*- coding: utf-8 -*-
"""
colectores/recolectar_xg_nhl.py - goles esperados (xG) y Corsi por equipo de NHL, de MoneyPuck -> datos/equipos/nhl_xg.csv

Que hace: baja el resumen por equipo de MoneyPuck (temporada regular actual y anterior) y guarda, por equipo,
temporada y situacion (all / 5on5): juegos, xG a favor y en contra por 60 min, goles a favor y en contra por 60,
xG%, Corsi% y la "suerte" (goles reales menos esperados). plataforma.py lo pega a la ficha como xg_nhl.

Por que: los goles reales en 2-3 juegos son ruido; el xG corrige la suerte y es, en la literatura de hockey,
el dato con mas poder predictivo despues del portero. Entra como contexto y a pesos_capas para medir su peso.

    python colectores\\recolectar_xg_nhl.py              (temporada actual y anterior)
    python colectores\\recolectar_xg_nhl.py --temporadas 2025,2026

Fuente: https://moneypuck.com/moneypuck/playerData/seasonSummary/<year>/regular/teams.csv  (year = ano de inicio)
Solo stdlib.
"""
import argparse, csv, datetime as dt, io, os, subprocess, sys, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SALIDA = os.path.join(BASE, "datos", "equipos", "nhl_xg.csv")
UA = "Mozilla/5.0 (Edgeline)"
URL = "https://moneypuck.com/moneypuck/playerData/seasonSummary/%d/regular/teams.csv"
SITUACIONES = ("all", "5on5")
# MoneyPuck -> abreviatura de ESPN (la que trae proximos.json); los demas coinciden
A_ESPN = {"LAK": "LA", "SJS": "SJ", "TBL": "TB", "NJD": "NJ", "UTA": "UTAH", "ARI": "UTAH", "WSH": "WSH", "MTL": "MTL"}


def bajar(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace"), None
    except Exception as e:
        try:
            exe = "curl.exe" if os.name == "nt" else "curl"
            out = subprocess.run([exe, "-sL", "--max-time", "60", "-A", UA, url], capture_output=True, timeout=90)
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", "replace"), None
        except Exception as e2:
            return None, "%s / %s" % (e, e2)
        return None, str(e)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def filas(year):
    txt, err = bajar(URL % year)
    if not txt:
        print("  %d: sin respuesta (%s)" % (year, err)); return []
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        if (r.get("situation") or "") not in SITUACIONES:
            continue
        it = _f(r.get("iceTime")) or 0.0           # segundos
        h = it / 3600.0
        if h <= 0:
            continue
        gp = _f(r.get("games_played")) or 0
        xgf, xga = _f(r.get("xGoalsFor")) or 0.0, _f(r.get("xGoalsAgainst")) or 0.0
        gf, ga = _f(r.get("goalsFor")) or 0.0, _f(r.get("goalsAgainst")) or 0.0
        cf, ca = _f(r.get("shotAttemptsFor")) or 0.0, _f(r.get("shotAttemptsAgainst")) or 0.0
        hd_f, hd_a = _f(r.get("highDangerxGoalsFor")) or 0.0, _f(r.get("highDangerxGoalsAgainst")) or 0.0
        team = (r.get("team") or "").strip()
        out.append({"season": year, "team_mp": team, "team": A_ESPN.get(team, team), "nombre": r.get("name") or "",
                    "situacion": r["situation"], "juegos": int(gp), "minutos": round(it / 60.0, 1),
                    "xgf_60": round(xgf / h, 3), "xga_60": round(xga / h, 3), "gf_60": round(gf / h, 3), "ga_60": round(ga / h, 3),
                    "xg_pct": round(xgf / (xgf + xga), 4) if xgf + xga else None,
                    "corsi_pct": round(cf / (cf + ca), 4) if cf + ca else None,
                    "hd_xgf_60": round(hd_f / h, 3), "hd_xga_60": round(hd_a / h, 3),
                    "suerte_gf": round(gf - xgf, 2), "suerte_ga": round(ga - xga, 2),
                    "bajado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    print("  %d: %d filas (%s)" % (year, len(out), "/".join(SITUACIONES)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temporadas", help="anos de inicio separados por coma; sin esto: actual y anterior")
    a = ap.parse_args()
    if a.temporadas:
        years = [int(x) for x in a.temporadas.split(",")]
    else:
        hoy = dt.date.today()
        y = hoy.year if hoy.month >= 9 else hoy.year - 1
        years = [y - 1, y]
    rows = []
    for y in years:
        rows += filas(y)
    if not rows:
        print("Sin datos; no se escribe nada."); return 1
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("Escrito %s (%d filas)" % (SALIDA, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
