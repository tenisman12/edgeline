# -*- coding: utf-8 -*-
"""
colectores/recolectar_porteros.py - porteros titulares de NHL (Daily Faceoff) -> trabajo/porteros_<fecha>.json

Que hace: baja https://www.dailyfaceoff.com/starting-goalies/<fecha> y saca, por equipo, el portero
proyectado o confirmado y su estado (Confirmed / Likely / Expected / Unconfirmed). plataforma.py lo lee
para alimentar el ajuste por portero del modelo de hockey (save% del titular en su ventana de 10 juegos).

    python colectores\\recolectar_porteros.py                  (hoy y manana, hora CDMX)
    python colectores\\recolectar_porteros.py --fecha 2026-10-04
    python colectores\\recolectar_porteros.py --fecha 2026-10-04 --debug   (guarda el HTML en trabajo/ para revisar el parser)

Salida: trabajo/porteros_<fecha>.json
    {"fecha": "2026-10-04", "fuente": "dailyfaceoff", "bajado": "...Z",
     "equipos": {"Vancouver Canucks": {"portero": "Kevin Lankinen", "estado": "Unconfirmed"}, ...}}

Si la pagina no responde o el parser no encuentra nada, escribe el archivo con "equipos": {} y motivo;
nunca inventa porteros. Solo stdlib.
"""
import argparse, datetime as dt, html, json, os, re, subprocess, sys, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRABAJO = os.path.join(BASE, "trabajo")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edgeline/1.0"
URL = "https://www.dailyfaceoff.com/starting-goalies/%s"
TZ = -6

EQUIPOS = ["Anaheim Ducks", "Boston Bruins", "Buffalo Sabres", "Calgary Flames", "Carolina Hurricanes", "Chicago Blackhawks",
           "Colorado Avalanche", "Columbus Blue Jackets", "Dallas Stars", "Detroit Red Wings", "Edmonton Oilers", "Florida Panthers",
           "Los Angeles Kings", "Minnesota Wild", "Montreal Canadiens", "Nashville Predators", "New Jersey Devils", "New York Islanders",
           "New York Rangers", "Ottawa Senators", "Philadelphia Flyers", "Pittsburgh Penguins", "San Jose Sharks", "Seattle Kraken",
           "St. Louis Blues", "Tampa Bay Lightning", "Toronto Maple Leafs", "Utah Mammoth", "Vancouver Canucks", "Vegas Golden Knights",
           "Washington Capitals", "Winnipeg Jets"]
# como los escribe Daily Faceoff cuando no coincide con nuestro nombre (sin esto se perdia todo el partido STL-CHI)
ALIAS = {"St Louis Blues": "St. Louis Blues", "St.Louis Blues": "St. Louis Blues", "Montréal Canadiens": "Montreal Canadiens",
         "Utah Hockey Club": "Utah Mammoth", "Utah HC": "Utah Mammoth", "LA Kings": "Los Angeles Kings",
         "NY Rangers": "New York Rangers", "NY Islanders": "New York Islanders", "Tampa Bay Lightning ": "Tampa Bay Lightning"}
ESTADOS = ("Confirmed", "Likely", "Expected", "Probable", "Unconfirmed", "Projected")


def bajar(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace"), None
    except Exception as e:
        try:
            exe = "curl.exe" if os.name == "nt" else "curl"
            out = subprocess.run([exe, "-sL", "--max-time", "40", "-A", UA, url], capture_output=True, timeout=60)
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", "replace"), None
        except Exception as e2:
            return None, "%s / %s" % (e, e2)
        return None, str(e)


def _texto(h):
    h = re.sub(r"<script.*?</script>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "\n", h)
    t = html.unescape(t)
    return [ALIAS.get(l.strip(), l.strip()) for l in t.splitlines() if l.strip()]


def _buscar_json(h):
    """Daily Faceoff es Next.js: intenta el JSON embebido (__NEXT_DATA__) y busca pares equipo/portero/estado."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, flags=re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return {}
    out = {}

    def walk(o):
        if isinstance(o, dict):
            keys = {k.lower() for k in o}
            # nodos tipo {team: {...name}, goalie/name..., status...}
            nombre_eq = None
            for k in ("teamName", "team_name", "name", "fullName"):
                if k in o and isinstance(o[k], str) and o[k] in EQUIPOS:
                    nombre_eq = o[k]
            if nombre_eq is None and isinstance(o.get("team"), dict):
                for k in ("name", "fullName", "teamName"):
                    if isinstance(o["team"].get(k), str) and o["team"][k] in EQUIPOS:
                        nombre_eq = o["team"][k]
            if nombre_eq:
                portero = None; estado = None
                for k in ("goalieName", "goalie_name", "playerName", "starterName", "starter"):
                    v = o.get(k)
                    if isinstance(v, str) and v:
                        portero = v
                    elif isinstance(v, dict):
                        portero = v.get("name") or v.get("fullName") or portero
                for k in ("status", "newsStrength", "confirmation", "state"):
                    v = o.get(k)
                    if isinstance(v, str) and v:
                        estado = v
                if portero:
                    out[nombre_eq] = {"portero": portero.strip(), "estado": (estado or "Unconfirmed").strip().title()}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def _es_nombre(s):
    """nombre de persona: 2-3 palabras con mayuscula, sin digitos, % ni siglas de stats."""
    return bool(re.fullmatch(r"[A-Z][A-Za-z'\.\-\u00C0-\u017F]+(?: [A-Z][A-Za-z'\.\-\u00C0-\u017F]+){1,2}", s)) and not re.search(r"\d|%|GAA|SV|Goalie|Starting|Lineup", s) and s not in EQUIPOS


def _buscar_texto(lineas):
    """Respaldo sobre el texto visible. Estructura real de Daily Faceoff (vista 2026-10-04):
        <Visitante> / at / <Local> / <hora ISO> / <portero visitante> / <Confirmed|Unconfirmed> / ... / <portero local> / <estado> / ...
    Se lee por tarjeta: el encabezado es equipo, "at", equipo; dentro, cada portero es un nombre de persona seguido
    inmediatamente por su estado. El primero es del visitante y el segundo del local."""
    out = {}
    n = len(lineas)
    i = 0
    while i < n:
        if lineas[i] in EQUIPOS and i + 2 < n and lineas[i + 1].lower() in ("at", "vs", "vs.", "@") and lineas[i + 2] in EQUIPOS:
            away, home = lineas[i], lineas[i + 2]
            porteros = []
            j = i + 3
            while j < n and len(porteros) < 2:
                if lineas[j] in EQUIPOS and j + 2 < n and lineas[j + 1].lower() in ("at", "vs", "vs.", "@") and lineas[j + 2] in EQUIPOS:
                    break                                   # siguiente tarjeta sin completar los dos porteros
                if _es_nombre(lineas[j]) and j + 1 < n and any(lineas[j + 1].startswith(e) for e in ESTADOS):
                    estado = next(e for e in ESTADOS if lineas[j + 1].startswith(e))
                    porteros.append({"portero": lineas[j], "estado": estado})
                    j += 2
                    continue
                j += 1
            if porteros:
                out.setdefault(away, porteros[0])
            if len(porteros) > 1:
                out.setdefault(home, porteros[1])
            i = j
        else:
            i += 1
    return out


def recolectar(fecha, debug=False):
    url = URL % fecha
    h, err = bajar(url)
    res = {"fecha": fecha, "fuente": "dailyfaceoff", "url": url, "bajado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "equipos": {}}
    if not h:
        res["motivo"] = "sin respuesta: %s" % err
        return res
    if debug:
        os.makedirs(TRABAJO, exist_ok=True)
        with open(os.path.join(TRABAJO, "dailyfaceoff_%s.html" % fecha), "w", encoding="utf-8") as f:
            f.write(h)
    eq = _buscar_texto(_texto(h))          # estructura verificada (equipo / at / equipo / porteros)
    if len(eq) < 2:
        eq = _buscar_json(h)
    res["equipos"] = eq
    if not eq:
        res["motivo"] = "la pagina respondio pero el parser no encontro porteros (corre con --debug y revisa el HTML)"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="YYYY-MM-DD; sin fecha: hoy y manana (CDMX)")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if a.fecha:
        fechas = [a.fecha]
    else:
        hoy = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()
        fechas = [hoy.isoformat(), (hoy + dt.timedelta(days=1)).isoformat()]
    os.makedirs(TRABAJO, exist_ok=True)
    for f in fechas:
        r = recolectar(f, a.debug)
        ruta = os.path.join(TRABAJO, "porteros_%s.json" % f)
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=1)
        print("%s: %d equipos con portero -> %s%s" % (f, len(r["equipos"]), ruta, ("  [%s]" % r["motivo"]) if r.get("motivo") else ""))
        for t, v in sorted(r["equipos"].items()):
            print("   %-24s %-22s %s" % (t, v["portero"], v["estado"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
