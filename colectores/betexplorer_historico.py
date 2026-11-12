# -*- coding: utf-8 -*-
"""
colectores/betexplorer_historico.py - momios HISTORICOS de beisbol (LMP, LMB, LVBP, LIDOM) desde BetExplorer.

BetExplorer no tiene API: este script lee sus paginas publicas como lo hace un navegador, despacio (--pausa 1.5 s por
pagina) y guardando el avance (si se corta, al volver a correrlo se salta lo ya guardado). Corre en la PC de Alejandro:
desde GitHub Actions BetExplorer suele bloquear.

Que baja, por temporada:
  1. /baseball/mexico/<liga>-<temporada>/results/  (temporada regular y playoffs): id, fecha, local, visita, marcador.
  2. Por juego, los momios por casa de cada mercado:
       ha = ganador (local / visita)       ou = total de carreras (over / under, cada linea)
       ah = run line / handicap (local / visita, cada linea)
     con la cuota final de cada casa (la ultima antes del juego) y la hora en que la casa la puso.

Escribe semillas/betexplorer_beisbol.csv (una fila por juego, mercado, casa y linea; cuotas en DECIMAL, como las da
BetExplorer) y, al terminar, semillas/betexplorer_beisbol_principal.csv: UNA fila por juego con la linea que ponen las
casas (la de cuotas mas parejas, ~1.85 / 1.95) en ganador, total y run line, media de casas y BetInAsia (sharp) aparte.
Las casas que contradicen al resto en la misma linea se descartan (>12 pp de la mediana). Las casas que salen dependen
del pais desde donde se consulta.  Rehacer el resumen sin bajar nada:  --resumir

Uso (PowerShell):
    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python -m pip install beautifulsoup4
    # 1) prueba con un solo juego (guarda lo que responde BetExplorer en trabajo/betexplorer_sonda/ para revisar)
    python colectores/betexplorer_historico.py --sonda
    # 2) una temporada
    python colectores/betexplorer_historico.py --liga lmp --temporadas 2024-2025
    # 3) todo LMP desde 2013-14
    python colectores/betexplorer_historico.py --liga lmp --temporadas 2013-2014:2025-2026
    # LMB (temporada de un solo anio)
    python colectores/betexplorer_historico.py --liga lmb --temporadas 2019:2025
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, csv, gzip, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Falta beautifulsoup4: python -m pip install beautifulsoup4"); sys.exit(1)

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB = "https://www.betexplorer.com"
SALIDA = os.path.join(BASE, "semillas", "betexplorer_beisbol.csv")
SONDA = os.path.join(BASE, "trabajo", "betexplorer_sonda")
LIGAS = {"lmp": ("mexico", "lmp", 2), "lmb": ("mexico", "lmb", 1),
         "lvbp": ("venezuela", "lvbp", 2), "lidom": ("dominican-republic", "lidom", 2)}
MERCADOS = ["ha", "ou", "ah"]
# BetExplorer carga los momios por AJAX; se prueban estas rutas en orden y se usa la primera que responda con tabla
# (12-nov-2026, de res/js/all.min.js: url "/match-odds/"+id+"/"+tipo+"/"+mercado+"/odds/?lang="+idioma, tipo 0 = pre, 1 = post)
RUTAS_ODDS = ["/match-odds/{id}/0/{m}/odds/?lang=en", "/match-odds/{id}/1/{m}/odds/?lang=en",
              "/match-odds/{id}/0/{m}/bestOdds/?lang=en", "/match-odds-old/{id}/0/{m}/0/en/"]
COLS = ["liga", "temporada", "etapa", "match_id", "fecha", "local", "visita", "carreras_local", "carreras_visita",
        "mercado", "casa", "linea", "cuota_1", "cuota_2", "actualizada", "url"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _get(url, ajax=False, referer=None):
    h = {"User-Agent": UA, "Accept-Language": "es-MX,es;q=0.9,en;q=0.8", "Accept-Encoding": "gzip"}
    if ajax:
        h.update({"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        return b.decode("utf-8", errors="replace")


def _num(s):
    try:
        return float(str(s).replace(",", ".").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def _temporadas(txt, partes):
    """'2013-2014:2025-2026' -> ['2013-2014', ...]; '2019:2025' -> ['2019', ...]; 'actual' -> ['']"""
    out = []
    for pz in txt.split(","):
        pz = pz.strip()
        if pz == "actual":
            out.append(""); continue
        if ":" in pz:
            a, b = pz.split(":")
            y0, y1 = int(a[:4]), int(b[:4])
            for y in range(y0, y1 + 1):
                out.append("%d-%d" % (y, y + 1) if partes == 2 else str(y))
        else:
            out.append(pz)
    return out


def url_temporada(liga, temp):
    pais, slug, _ = LIGAS[liga]
    return "%s/baseball/%s/%s/" % (WEB, pais, slug + ("-" + temp if temp else ""))


def leer_resultados(html, url_base):
    """-> (juegos, etapas). juegos: dicts con match_id, url, fecha, local, visita, marcador; etapas: {nombre: url}"""
    s = BeautifulSoup(html, "html.parser")
    etapas = {}
    for a in s.select("a[href*='?stage=']"):
        etapas[a.get_text(" ", strip=True) or a["href"]] = urllib.parse.urljoin(url_base or WEB, a["href"])
    juegos, etapa = [], ""
    for tr in s.select("table tr"):
        th = tr.find("th")
        if th and not tr.find("a", href=True):
            etapa = th.get_text(" ", strip=True); continue
        a = None
        for x in tr.find_all("a", href=True):
            if re.search(r"/[A-Za-z0-9]{8}/?$", x["href"]):
                a = x; break
        if not a:
            continue
        href = urllib.parse.urljoin(url_base or WEB, a["href"])
        mid = re.search(r"/([A-Za-z0-9]{8})/?$", href).group(1)
        nombres = [t.strip() for t in a.get_text(" ", strip=True).split(" - ")]
        txt = tr.get_text(" ", strip=True)
        sc = re.search(r"\b(\d{1,2}):(\d{1,2})\b", txt)
        fe = re.search(r"(\d{2})\.(\d{2})\.(\d{4})?", txt)
        juegos.append({"match_id": mid, "url": href, "etapa": etapa,
                       "fecha": ("%s-%s-%s" % (fe.group(3), fe.group(2), fe.group(1))) if fe and fe.group(3) else (fe.group(0) if fe else ""),
                       "local": nombres[0] if nombres else "", "visita": nombres[1] if len(nombres) > 1 else "",
                       "carreras_local": sc.group(1) if sc else "", "carreras_visita": sc.group(2) if sc else ""})
    return juegos, etapas


def _fecha_be(x):
    """'29,01,2025,01,55' -> '2025-01-29 01:55' (hora del servidor de BetExplorer)."""
    p = (x or "").replace('"', "").split(",")
    return "%s-%s-%s %s:%s" % (p[2], p[1], p[0], p[3], p[4]) if len(p) >= 5 else ""


def leer_odds(html_tabla, mercado):
    """respuesta de /match-odds/ -> [{casa, linea, cuota_1, cuota_2, actualizada}]
    (12-nov-2026: una <tbody id="all-odds-<linea>"> por linea; cada <tr> es una casa con dos <td data-odd>)."""
    s = BeautifulSoup(html_tabla, "html.parser")
    filas = []
    for tb in s.select("tbody[id^='all-odds-']"):
        ln = _num(tb["id"].replace("all-odds-", "")) if mercado != "ha" else None
        for tr in tb.find_all("tr", recursive=False):
            tds = [td for td in tr.find_all("td") if td.has_attr("data-odd")]
            if len(tds) < 2:
                continue
            x = tr.select_one("a.in-bookmaker-logo-link")
            casa = x.get_text(" ", strip=True) if x else (tds[0].get("data-bookie") or tr.get("data-bid", ""))
            filas.append({"casa": casa, "linea": "" if ln is None else ln,
                          "cuota_1": _num(tds[0]["data-odd"]), "cuota_2": _num(tds[1]["data-odd"]),
                          "actualizada": _fecha_be(tds[0].get("data-created"))})
    return filas


def odds_de_juego(mid, url, mercado, ruta_ok):
    rutas = [ruta_ok[0]] if ruta_ok[0] else RUTAS_ODDS
    for r in rutas:
        u = WEB + r.format(id=mid, m=mercado)
        try:
            t = _get(u, ajax=True, referer=url)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise
            continue
        except Exception:
            continue
        try:
            html = json.loads(t).get("odds") or ""
        except Exception:
            html = t
        if "all-odds-" in html:
            ruta_ok[0] = r
            return leer_odds(html, mercado)
    return []


def ya_guardados():
    if not os.path.exists(SALIDA):
        return set()
    with io.open(SALIDA, encoding="utf-8-sig", newline="") as f:
        return {(r["match_id"], r["mercado"]) for r in csv.DictReader(f)}


def guardar(filas):
    if not filas:
        return
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    existe = os.path.exists(SALIDA)
    with io.open(SALIDA, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not existe:
            w.writeheader()
        w.writerows(filas)


def sonda():
    """Un juego de prueba (final LMP 2024-25): guarda lo que responde cada ruta para revisar si cambio la estructura."""
    os.makedirs(SONDA, exist_ok=True)
    u = url_temporada("lmp", "2024-2025") + "results/"
    html = _get(u)
    io.open(os.path.join(SONDA, "resultados.html"), "w", encoding="utf-8").write(html)
    juegos, etapas = leer_resultados(html, u)
    print("Resultados LMP 2024-25: %d juegos leidos; etapas: %s" % (len(juegos), list(etapas)))
    for j in juegos[:3]:
        print("  ", j)
    if not juegos:
        print("No se leyeron juegos: mandar trabajo/betexplorer_sonda/resultados.html"); return
    j = juegos[0]
    for m in MERCADOS:
        for r in RUTAS_ODDS:
            url = WEB + r.format(id=j["match_id"], m=m)
            try:
                t = _get(url, ajax=True, referer=j["url"])
                nom = "%s_%d.txt" % (m, RUTAS_ODDS.index(r))
                io.open(os.path.join(SONDA, nom), "w", encoding="utf-8").write(t)
                try:
                    h = json.loads(t).get("odds") or ""
                except Exception:
                    h = t
                fl = leer_odds(h, m) if "all-odds-" in h else []
                print("%s %-34s -> %d bytes, %d filas de casas %s" % (m, r, len(t), len(fl), fl[:2]))
            except Exception as e:
                print("%s %-34s -> %s" % (m, r, e))
        time.sleep(1.5)
    print("Respuestas guardadas en", SONDA)


PRINC = ["liga", "temporada", "etapa", "match_id", "fecha", "local", "visita", "carreras_local", "carreras_visita",
         "ml_local", "ml_visita", "ml_casas", "total", "over", "under", "total_casas", "total_real",
         "rl_local", "rl_cuota_local", "rl_cuota_visita", "rl_casas",
         "bia_ml_local", "bia_ml_visita", "bia_over", "bia_under", "bia_rl_local", "bia_rl_visita", "url"]


def _limpias(filas):
    """quita la casa que contradice al resto en la misma linea (p. ej. over y under al reves): su probabilidad
    sin vig del lado 1 se aleja mas de 12 pp de la mediana de las casas."""
    ps = []
    for f in filas:
        a, b = 1 / f["c1"], 1 / f["c2"]
        ps.append(a / (a + b))
    if len(filas) < 3:
        return filas
    med = sorted(ps)[len(ps) // 2]
    return [f for f, p in zip(filas, ps) if abs(p - med) <= 0.12]


def _linea_principal(filas):
    """{linea: [filas]} -> (linea, cuota media 1, cuota media 2, n casas) de la linea con las cuotas mas parejas
    (la que ponen las casas, ~1.85 / 1.95). En empate gana la que tiene mas casas."""
    mejor = None
    for ln, fs in filas.items():
        fs = _limpias(fs)
        if not fs:
            continue
        c1 = sum(f["c1"] for f in fs) / len(fs)
        c2 = sum(f["c2"] for f in fs) / len(fs)
        clave = (abs(c1 - c2), -len(fs))
        if mejor is None or clave < mejor[0]:
            mejor = (clave, ln, round(c1, 3), round(c2, 3), len(fs), fs)
    return mejor[1:] if mejor else None


def resumir(entrada, salida):
    """CSV con todas las lineas -> una fila por juego: ganador (media de casas), total y run line PRINCIPALES y,
    aparte, BetInAsia (precio sharp) en esas mismas lineas."""
    if not os.path.exists(entrada):
        return 0
    por = {}
    with io.open(entrada, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c1, c2 = _num(r.get("cuota_1")), _num(r.get("cuota_2"))
            if not c1 or not c2 or c1 <= 1 or c2 <= 1:
                continue
            j = por.setdefault(r["match_id"], {"info": r, "ha": {}, "ou": {}, "ah": {}})
            ln = _num(r.get("linea")) if r["mercado"] != "ha" else 0.0
            if ln is None or r["mercado"] not in ("ha", "ou", "ah"):
                continue
            j[r["mercado"]].setdefault(ln, []).append({"casa": r["casa"], "c1": c1, "c2": c2})
    filas = []
    for mid, j in por.items():
        i = j["info"]
        o = {k: i.get(k, "") for k in ("liga", "temporada", "etapa", "match_id", "fecha", "local", "visita",
                                       "carreras_local", "carreras_visita", "url")}
        try:
            o["total_real"] = int(i["carreras_local"]) + int(i["carreras_visita"])
        except (TypeError, ValueError):
            o["total_real"] = ""
        def bia(fs):
            x = [f for f in fs if f["casa"].lower() == "betinasia"]
            return (x[0]["c1"], x[0]["c2"]) if x else ("", "")
        ha = _linea_principal(j["ha"])
        if ha:
            o.update(ml_local=ha[1], ml_visita=ha[2], ml_casas=ha[3])
            o["bia_ml_local"], o["bia_ml_visita"] = bia(j["ha"][ha[0]])
        ou = _linea_principal(j["ou"])
        if ou:
            o.update(total=ou[0], over=ou[1], under=ou[2], total_casas=ou[3])
            o["bia_over"], o["bia_under"] = bia(j["ou"][ou[0]])
        ah = _linea_principal(j["ah"])
        if ah:
            o.update(rl_local=ah[0], rl_cuota_local=ah[1], rl_cuota_visita=ah[2], rl_casas=ah[3])
            o["bia_rl_local"], o["bia_rl_visita"] = bia(j["ah"][ah[0]])
        filas.append(o)
    filas.sort(key=lambda r: (r.get("fecha") or "", r["match_id"]))
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    with io.open(salida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PRINC, extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    print("  linea principal por juego: %d juegos -> %s" % (len(filas), salida))
    return len(filas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", default="lmp", choices=sorted(LIGAS))
    ap.add_argument("--temporadas", default="2024-2025", help="'2013-2014:2025-2026', '2019:2025', 'actual' o lista con comas")
    ap.add_argument("--mercados", default=",".join(MERCADOS))
    ap.add_argument("--pausa", type=float, default=1.5, help="segundos entre paginas")
    ap.add_argument("--max-juegos", type=int, default=0, help="tope de juegos por temporada (0 = todos)")
    ap.add_argument("--sonda", action="store_true")
    ap.add_argument("--salida", default=None, help="CSV de salida (por defecto semillas/betexplorer_beisbol.csv)")
    ap.add_argument("--listar", action="store_true", help="solo imprime la lista de temporadas en JSON (para Actions)")
    ap.add_argument("--resumir", action="store_true", help="solo arma el CSV de linea principal por juego desde lo ya bajado")
    a = ap.parse_args()
    if a.listar:
        print(json.dumps(_temporadas(a.temporadas, LIGAS[a.liga][2]))); return 0
    if a.salida:
        global SALIDA
        SALIDA = os.path.abspath(a.salida)
    if a.sonda:
        return sonda()
    if a.resumir:
        resumir(SALIDA, SALIDA.replace(".csv", "_principal.csv")); return 0
    hechos = ya_guardados()
    mercados = [m.strip() for m in a.mercados.split(",") if m.strip()]
    ruta_ok = [None]
    for temp in _temporadas(a.temporadas, LIGAS[a.liga][2]):
        u0 = url_temporada(a.liga, temp) + "results/"
        try:
            html = _get(u0)
        except Exception as e:
            print("%s %s: no se pudo leer %s (%s)" % (a.liga, temp, u0, e)); continue
        juegos, etapas = leer_resultados(html, u0)
        vistos = {j["match_id"] for j in juegos}
        for nom, ue in etapas.items():      # playoffs y demas etapas
            time.sleep(a.pausa)
            try:
                jj, _ = leer_resultados(_get(ue), ue)
            except Exception:
                continue
            for j in jj:
                if j["match_id"] not in vistos:
                    j["etapa"] = j["etapa"] or nom; juegos.append(j); vistos.add(j["match_id"])
        if a.max_juegos:
            juegos = juegos[:a.max_juegos]
        print("%s %s: %d juegos" % (a.liga.upper(), temp or "actual", len(juegos)))
        n_filas = 0
        for i, j in enumerate(juegos, 1):
            filas = []
            for m in mercados:
                if (j["match_id"], m) in hechos:
                    continue
                time.sleep(a.pausa)
                try:
                    od = odds_de_juego(j["match_id"], j["url"], m, ruta_ok)
                except urllib.error.HTTPError as e:
                    print("BetExplorer respondio HTTP %s: se detiene. Esperar un rato y volver a correr (sigue donde quedo)." % e.code)
                    guardar(filas); return 1
                for o in od:
                    filas.append(dict(liga=a.liga, temporada=temp, etapa=j["etapa"], match_id=j["match_id"], fecha=j["fecha"],
                                      local=j["local"], visita=j["visita"], carreras_local=j["carreras_local"],
                                      carreras_visita=j["carreras_visita"], mercado=m, url=j["url"], **o))
                if not od:      # se marca como hecho con una fila vacia para no pedirlo otra vez
                    filas.append(dict(liga=a.liga, temporada=temp, etapa=j["etapa"], match_id=j["match_id"], fecha=j["fecha"],
                                      local=j["local"], visita=j["visita"], carreras_local=j["carreras_local"],
                                      carreras_visita=j["carreras_visita"], mercado=m, casa="", linea="", cuota_1="", cuota_2="",
                                      actualizada="", url=j["url"]))
                hechos.add((j["match_id"], m))
            guardar(filas); n_filas += len(filas)
            if i % 10 == 0:
                print("  %d/%d juegos, %d filas" % (i, len(juegos), n_filas))
        print("  listo: %d filas nuevas en %s" % (n_filas, SALIDA))
    resumir(SALIDA, SALIDA.replace(".csv", "_principal.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
