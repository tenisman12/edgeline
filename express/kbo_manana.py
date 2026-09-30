# -*- coding: utf-8 -*-
"""
express/kbo_manana.py - KBO de manana con el MODELO NUEVO (nucleo + modelos/beisbol), entrenado
con datos\\beisbol.csv (KBO hasta el ultimo dia que hayas descargado). Sin ajuste de abridor.

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python express\\kbo_manana.py                       (manana)
    python express\\kbo_manana.py --fecha 20261001
    python express\\kbo_manana.py --juegos "NC Dinos @ Doosan Bears, KT Wiz @ Kia Tigers"

Baja el calendario de koreabaseball.com (mismo endpoint de recolectar_kbo.py). Escribe
salida\\kbo_manana.csv.
"""
import argparse, csv, datetime as dt, json, os, sys, urllib.parse, urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
from nucleo import io, calibrar, equipos, estado
from modelos import beisbol

U_LIST = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
EQ = {"HT": "Kia Tigers", "LG": "LG Twins", "OB": "Doosan Bears", "SS": "Samsung Lions",
      "LT": "Lotte Giants", "NC": "NC Dinos", "KT": "KT Wiz", "WO": "Kiwoom Heroes",
      "SK": "SSG Landers", "SSG": "SSG Landers", "HH": "Hanwha Eagles"}


def calendario(fecha):
    data = urllib.parse.urlencode({"leId": "1", "srId": "0,3,4,5,7", "date": fecha}).encode()
    req = urllib.request.Request(U_LIST, data=data, headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.koreabaseball.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("utf-8", "replace")
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        d = json.loads(json.loads(txt))
    out = []
    for g in (d.get("game", []) if isinstance(d, dict) else []):
        core = str(g.get("G_ID") or "")[8:]
        aw = "SSG" if core[:3] == "SSG" else core[:2]
        hm = core[3:5] if core[:3] == "SSG" else core[2:4]
        if aw in EQ and hm in EQ:
            out.append((EQ[aw], EQ[hm]))
    return out


def conf(p):
    m = abs(p - 0.5)
    return "alta" if m > 0.20 else ("media" if m > 0.10 else "baja")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha"); ap.add_argument("--juegos"); ap.add_argument("--liga", default="KBO")
    a = ap.parse_args()
    f = a.fecha or (dt.date.today() + dt.timedelta(days=1)).strftime("%Y%m%d")
    fecha_iso = "%s-%s-%s" % (f[:4], f[4:6], f[6:8])

    print("Entrenando el modelo de %s con datos\\beisbol.csv ..." % a.liga)
    est = estado.beisbol(a.liga)
    if not est:
        sys.exit("No hay datos suficientes de %s en datos\\beisbol.csv" % a.liga)
    print("  ultimo juego en tus datos: %s   (entrenado con %d juegos)\n" % (est["ultimo_juego"], est["n_entreno"]))
    emp = equipos.Emparejador(est["nombres"])

    if a.juegos:
        juegos = [tuple(x.strip() for x in j.split("@")) for j in a.juegos.split(",")]
    else:
        juegos = calendario(f)
        if not juegos:
            sys.exit("Sin juegos de KBO el %s." % f)
    pa_, pb_ = calibrar.cargar("beisbol", est["liga"])

    filas = []
    print("%-16s %-16s %-16s %6s %-6s %9s %7s" % ("VISITANTE", "LOCAL", "GANA", "PROB", "CONF", "CARR V-L", "TOTAL"))
    print("-" * 86)
    for vis, loc in juegos:
        h, _ = emp.buscar([loc]); v, _ = emp.buscar([vis])
        if not h or not v:
            print("%-16s %-16s sin empate en tus datos" % (vis, loc)); continue
        fila = estado.fila_proximo(est, h, v, fecha_iso)
        if not fila:
            print("%-16s %-16s muestra insuficiente" % (vis, loc)); continue
        r = beisbol.predecir(est["modelo"], fila, None)
        p = calibrar.aplicar(r["p_home"], pa_, pb_)
        gana, pg = (loc, p) if p >= 0.5 else (vis, 1 - p)
        print("%-16s %-16s %-16s %5.1f%% %-6s %4.1f-%-4.1f %7.1f" % (
            vis, loc, gana, pg * 100, conf(p), r["esperado_away"], r["esperado_home"], r["total"]))
        filas.append({"fecha": fecha_iso, "visitante": vis, "local": loc, "gana": gana,
                      "prob": round(pg, 4), "confianza": conf(p), "carreras_visita": r["esperado_away"],
                      "carreras_local": r["esperado_home"], "total": r["total"],
                      "elo_visita": fila["elo_away"], "elo_local": fila["elo_home"]})
    if filas:
        os.makedirs(os.path.join(RAIZ, "salida"), exist_ok=True)
        ruta = os.path.join(RAIZ, "salida", "kbo_manana.csv")
        with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
        print("\nGuardado en", ruta)


if __name__ == "__main__":
    main()
