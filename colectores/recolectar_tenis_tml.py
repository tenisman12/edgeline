# -*- coding: utf-8 -*-
"""
RECOLECTAR TENIS (TennisMyLife) - ATP y WTA con estadisticas de saque, actualizado a diario.

Fuente: stats.tennismylife.org (mismo formato que Sackmann: w_svpt, w_1stWon, w_bpFaced...). La lista de
archivos y sus URLs sale de https://stats.tennismylife.org/api/data-files. Se bajan solo los del año en curso:
    ATP: <año>.csv y ongoing_tourneys.csv        WTA: <año>_wta.csv y wta_ongoing_tourneys.csv

Se agregan solo partidos desde --desde (por defecto 45 dias antes de la ultima fecha de datos\\tenis.csv) que
NO estan ya en el historial: se compara por cruce (ganador, perdedor) en esa ventana, asi no se duplica lo que
ya viene de Sackmann aunque cambie la convencion de fecha o de ronda. Los nombres se alinean al historial.

Uso:  python colectores\\recolectar_tenis_tml.py [--desde 20260801]
Escribe data_maestra\\tennis_tml.csv  (actualizar_todo.py lo mezcla en datos\\tenis.csv)
"""
import argparse, csv, io, json, os, re, subprocess, unicodedata, datetime as dt
import urllib.request

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")
OUT = os.path.join(BASE, "data_maestra", "tennis_tml.csv")
DATOS = os.path.join(BASE, "datos", "tenis.csv")
API = "https://stats.tennismylife.org/api/data-files"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def norm(s):
    t = "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def http(url, binario=False):
    """urllib con User-Agent de navegador; si falla, curl (ya probado que pasa donde Python no)."""
    err = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()
    except Exception as ex:
        err = str(ex)[:60]
    exe = "curl.exe" if os.name == "nt" else "curl"
    out = subprocess.run([exe, "-sS", "-L", "-m", "120", url], capture_output=True, timeout=150)
    if out.returncode == 0 and out.stdout:
        return out.stdout
    raise RuntimeError("%s | curl: %s" % (err, (out.stderr or b"").decode("utf-8", "replace")[:60]))


def lista_archivos():
    js = json.loads(http(API).decode("utf-8", "replace"))
    return {f["name"]: f["url"] for f in js.get("files", []) if f.get("name") and f.get("url")}


def leer_csv(binario):
    txt = binario.decode("utf-8-sig", "replace")
    return list(csv.DictReader(io.StringIO(txt)))


def historial():
    nombres, pares, ult = {}, set(), ""
    if not os.path.exists(DATOS):
        return nombres, pares, ult
    with io.open(DATOS, encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in ("winner_name", "loser_name"):
            if r.get(c): nombres.setdefault(norm(r[c]), r[c])
        ult = max(ult, r.get("tourney_date") or "")
    return nombres, rows, ult


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="AAAAMMDD; por defecto 45 dias antes de la ultima fecha de datos\\tenis.csv")
    args = ap.parse_args()
    nombres, rows_h, ult = historial()
    hoy = dt.date.today()
    if args.desde:
        desde = args.desde
    elif len(ult) == 8:
        desde = (dt.date(int(ult[:4]), int(ult[4:6]), int(ult[6:8])) - dt.timedelta(days=45)).strftime("%Y%m%d")
    else:
        desde = (hoy - dt.timedelta(days=60)).strftime("%Y%m%d")
    # cruces ya presentes en la ventana (sin importar fecha exacta ni ronda)
    pares = {(norm(r.get("winner_name")), norm(r.get("loser_name")))
             for r in rows_h if (r.get("tourney_date") or "") >= desde}
    print("Ventana TML: desde %s | cruces ya en el historial: %d" % (desde, len(pares)))
    try:
        archivos = lista_archivos()
    except Exception as ex:
        print("No se pudo leer la lista de archivos de TML (%s); no se escribe nada." % str(ex)[:100]); return
    y = hoy.year
    pedir = [("ATP", "%d.csv" % y), ("ATP", "ongoing_tourneys.csv"),
             ("WTA", "%d_wta.csv" % y), ("WTA", "wta_ongoing_tourneys.csv")]
    filas, cols, nuevos, dups, vistos = [], [], {"ATP": 0, "WTA": 0}, 0, set()
    for tour, nombre in pedir:
        url = archivos.get(nombre)
        if not url:
            print("  %s %-26s no aparece en la lista de TML" % (tour, nombre)); continue
        try:
            rows = leer_csv(http(url))
        except Exception as ex:
            print("  %s %-26s error al bajar (%s)" % (tour, nombre, str(ex)[:60])); continue
        n = 0
        for r in rows:
            if (r.get("tourney_date") or "") < desde: continue
            w, l = r.get("winner_name"), r.get("loser_name")
            if not w or not l: continue
            kw, kl = norm(w), norm(l)
            if (kw, kl) in pares:
                dups += 1; continue
            llave = (tour, r.get("tourney_id"), r.get("match_num"), kw, kl)
            if llave in vistos: continue
            vistos.add(llave)
            r = dict(r); r["tour"] = tour
            r["winner_name"] = nombres.get(kw, w); r["loser_name"] = nombres.get(kl, l)
            filas.append(r); n += 1
            for c in r:
                if c not in cols: cols.append(c)
        nuevos[tour] += n
        print("  %s %-26s %5d filas nuevas de %d" % (tour, nombre, n, len(rows)))
    if not filas:
        print("Sin partidos nuevos (ya en el historial: %d); no se escribe nada." % dups); return
    fechas = sorted(r.get("tourney_date") or "" for r in filas)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cols = ["tour"] + [c for c in cols if c != "tour"]
    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", restval=""); w.writeheader(); w.writerows(filas)
    con_saque = sum(1 for r in filas if r.get("w_svpt") not in (None, ""))
    print("Escritos %d partidos (ATP %d, WTA %d), fechas %s a %s; con estadisticas de saque: %d; ya estaban: %d" % (
        len(filas), nuevos["ATP"], nuevos["WTA"], fechas[0], fechas[-1], con_saque, dups))


if __name__ == "__main__":
    main()
