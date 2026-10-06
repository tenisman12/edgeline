# -*- coding: utf-8 -*-
"""
colectores/recolectar_kbo_box.py - BOX SCORE COMPLETO de KBO (sitio oficial, sin navegador).

Endpoint: Schedule.asmx/GetBoxScoreScroll (arrHitter: bateo por jugador; arrPitcher: pitcheo por jugador; tableEtc: 2B/3B/HR).
Por juego y equipo guarda:
  bateo   AB, H, RBI, R, 2B, 3B, HR, TB
  pitcheo IP, outs, bateadores enfrentados, pitcheos, AB, H, HR, BB+HBP, K, R, ER
  abridor nombre, IP, ER, K, pitcheos (para la capa de abridores)
Salidas:
  data_maestra/kbo_box.csv              (equipo-juego; lo lleva a datos/beisbol.csv utilidades/semillas.py)
  datos/jugadores/kbo_lanzadores.csv    (lanzador-juego)

    cd C:\\Edgeline_repo
    $env:EDGELINE_BASE = "C:\\Edgeline_repo"
    python colectores\\recolectar_kbo_box.py --prueba 20260927KTOB0     (un juego: imprime lo que leyo)
    python colectores\\recolectar_kbo_box.py                            (todos los juegos KBO que aun no tienen box)
    python colectores\\recolectar_kbo_box.py --desde 2026-09-01         (solo desde una fecha)

Incremental: los juegos que ya estan en kbo_box.csv no se vuelven a pedir. Solo stdlib.
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, time, urllib.parse, urllib.request

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
U_BOX = "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll"
U_LIST = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
OUT = os.path.join(BASE, "data_maestra", "kbo_box.csv")
OUT_P = os.path.join(BASE, "datos", "jugadores", "kbo_lanzadores.csv")
PAUSA = 0.35
EQUIPOS = {"HT": "Kia Tigers", "LG": "LG Twins", "OB": "Doosan Bears", "SS": "Samsung Lions", "LT": "Lotte Giants",
           "NC": "NC Dinos", "KT": "KT Wiz", "WO": "Kiwoom Heroes", "SK": "SSG Landers", "HH": "Hanwha Eagles"}
COLS_P = ["jugador", "rol", "decision", "w", "l", "sv", "ip", "bf", "pitches", "ab", "h", "hr", "bb_hbp", "k", "r", "er", "era_temp"]


def post(url, datos):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode(), headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx"})
    with urllib.request.urlopen(req, timeout=40) as r:
        txt = r.read().decode("utf-8", "replace")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return json.loads(json.loads(txt))


def tabla(x, parte="rows"):
    """Texto de celdas de una tabla del sitio (viene como JSON en texto o como dict). [[celdas],...].
    parte='rows' (cuerpo) o 'tfoot' (pie, donde el sitio pone los totales)."""
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except json.JSONDecodeError:
            return []
    if not isinstance(x, dict):
        return []
    filas = []
    for r in (x.get(parte) or []):
        celdas = [re.sub(r"<[^>]+>", "", str(c.get("Text") or "")).replace("&nbsp;", "").strip() for c in (r.get("row") or [])]
        filas.append(celdas)
    return filas


def n(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def outs_de(ip):
    """'6' -> 18, '1 1/3' -> 4, '2/3' -> 2."""
    s = str(ip or "").strip()
    if not s:
        return None
    total = 0
    for parte in s.split():
        if "/" in parte:
            a, b = parte.split("/")
            total += int(round(3 * float(a) / float(b)))
        else:
            total += 3 * int(float(parte))
    return total


def ip_txt(outs):
    return "%d.%d" % (outs // 3, outs % 3)


def extras(etc, nombres):
    """{equipo_idx: {'d2':..,'d3':..,'hr':..}} desde tableEtc (2루타, 3루타, 홈런)."""
    out = [{"d2": 0, "d3": 0, "hr": 0}, {"d2": 0, "d3": 0, "hr": 0}]
    clave = {"2루타": "d2", "3루타": "d3", "홈런": "hr"}
    for fila in tabla(etc):
        if len(fila) < 2 or fila[0] not in clave:
            continue
        k = clave[fila[0]]
        for m in re.finditer(r"([^\s(]+?)(\d*호)?\d*\(([^)]*)\)", fila[1]):
            nombre = re.sub(r"\d+$", "", m.group(1))
            if k == "hr":
                cuenta = 1
            else:
                cuenta = max(1, len(re.findall(r"\d+", m.group(3))))      # '2 4회' = dobles en el 2.o y 4.o inning
            lados = [i for i in (0, 1) if nombre in nombres[i]]
            if len(lados) == 1:
                out[lados[0]][k] += cuenta
    return out


def leer_box(d):
    """Devuelve (equipos[2], lanzadores[2]) con [0]=visita, [1]=local, o (None, None) si no hay box."""
    hit, pit = d.get("arrHitter") or [], d.get("arrPitcher") or []
    if len(hit) < 2 or len(pit) < 2:
        return None, None
    equipos, lanz, nombres = [], [], []
    for i in (0, 1):
        t1, t3 = tabla(hit[i].get("table1")), tabla(hit[i].get("table3"))
        nombres.append({f[2] for f in t1 if len(f) >= 3})
        ab = h = rbi = r = 0.0
        for f in t3:
            if len(f) >= 4 and all(n(x) is not None for x in f[:4]):
                ab += n(f[0]); h += n(f[1]); rbi += n(f[2]); r += n(f[3])
        pie = [f for f in tabla(hit[i].get("table3"), "tfoot") if len(f) >= 4 and all(n(x) is not None for x in f[:4])]
        if pie:                                   # el pie trae el total del equipo: manda sobre la suma
            ab, h, rbi, r = (n(x) for x in pie[0][:4])
        tp = tabla(pit[i].get("table"))
        ps, tot = [], {"outs": 0, "bf": 0, "pitches": 0, "ab": 0, "h": 0, "hr": 0, "bb_hbp": 0, "k": 0, "r": 0, "er": 0}
        for f in tp:
            if len(f) < 16 or f[0] in ("선수명", "합계", "TOTAL", "Total", ""):
                continue
            o = outs_de(f[6])
            p = dict(zip(COLS_P, f[:17]))
            p["outs"] = o
            p["abridor"] = "1" if f[1] == "선발" else "0"
            ps.append(p)
            tot["outs"] += o or 0
            for k, j in (("bf", 7), ("pitches", 8), ("ab", 9), ("h", 10), ("hr", 11), ("bb_hbp", 12), ("k", 13), ("r", 14), ("er", 15)):
                tot[k] += n(f[j]) or 0
        equipos.append({"bat_atBats": ab, "bat_hits": h, "bat_rbi": rbi, "bat_runs": r,
                        "pit_outs": tot["outs"], "pit_inningsPitched": ip_txt(tot["outs"]), "pit_battersFaced": tot["bf"],
                        "pit_numberOfPitches": tot["pitches"], "pit_atBats": tot["ab"], "pit_hits": tot["h"],
                        "pit_homeRuns": tot["hr"], "pit_baseOnBalls": tot["bb_hbp"], "pit_strikeOuts": tot["k"],
                        "pit_runs": tot["r"], "pit_earnedRuns": tot["er"]})
        lanz.append(ps)
    ex = extras(d.get("tableEtc"), nombres)
    for i in (0, 1):
        e = equipos[i]
        e["bat_doubles"], e["bat_triples"], e["bat_homeRuns"] = ex[i]["d2"], ex[i]["d3"], ex[i]["hr"]
        # el HR del bateo debe coincidir con el HR permitido por el pitcheo rival; si tableEtc no lo trajo se usa ese
        if e["bat_homeRuns"] == 0 and equipos[1 - i]["pit_homeRuns"]:
            e["bat_homeRuns"] = equipos[1 - i]["pit_homeRuns"]
        e["bat_totalBases"] = e["bat_hits"] + e["bat_doubles"] + 2 * e["bat_triples"] + 3 * e["bat_homeRuns"]
        st = next((p for p in lanz[i] if p["abridor"] == "1"), None)
        if st:
            e["abridor"], e["abridor_ip"], e["abridor_er"], e["abridor_k"], e["abridor_pitches"] = \
                st["jugador"], ip_txt(st["outs"] or 0), st["er"], st["k"], st["pitches"]
    return equipos, lanz


_SR = {}


def sr_de(gid):
    """SR_ID y SEASON_ID del juego (regular=0; postemporada 3/4/5/7) con la lista del dia (una consulta por dia)."""
    dia = gid[:8]
    if dia not in _SR:
        try:
            r = post(U_LIST, {"leId": "1", "srId": "0,3,4,5,7", "date": dia})
            _SR[dia] = {g.get("G_ID"): (str(g.get("SR_ID", "0")), str(g.get("SEASON_ID", dia[:4]))) for g in (r.get("game") or [])}
        except Exception:
            _SR[dia] = {}
    return _SR[dia].get(gid, ("0", dia[:4]))


def box(gid):
    sr, season = sr_de(gid)
    return post(U_BOX, {"leId": "1", "srId": sr, "seasonId": season, "gameId": gid})


def leer_csv(ruta):
    if not os.path.exists(ruta):
        return []
    with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def escribir(ruta, filas, fijas):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    cols = fijas + sorted({k for r in filas for k in r if k not in fijas})
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(filas)


def juegos_kbo(desde):
    ids = {}
    for ruta in (os.path.join(BASE, "datos", "beisbol.csv"), os.path.join(BASE, "data_maestra", "baseball_boxscores.csv")):
        for r in leer_csv(ruta):
            if (r.get("league") or "").upper() == "KBO" and (r.get("game_date") or "") >= desde:
                ids[str(r.get("gamePk")).replace(".0", "")] = r.get("game_date")
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2021-01-01")
    ap.add_argument("--prueba", metavar="GAME_ID")
    a = ap.parse_args()
    if a.prueba:
        eqs, lz = leer_box(box(a.prueba))
        if not eqs:
            print("Sin box para %s" % a.prueba); return 1
        for i, lado in ((0, "visita"), (1, "local")):
            print("\n%s %s" % (lado, EQUIPOS.get(a.prueba[8:10] if i == 0 else a.prueba[10:12])))
            print(json.dumps(eqs[i], ensure_ascii=False))
            for p in lz[i]:
                print("   ", p["jugador"], p["rol"], "IP", p["ip"], "ER", p["er"], "K", p["k"], "pitcheos", p["pitches"])
        return 0
    hechos = {r["gamePk"] for r in leer_csv(OUT)}
    pend = sorted((g, f) for g, f in juegos_kbo(a.desde).items() if g not in hechos)
    print("KBO box: %d juegos por bajar (ya guardados %d)" % (len(pend), len(hechos) // 2))
    filas, lanz, ok, sin = leer_csv(OUT), leer_csv(OUT_P), 0, 0
    for j, (gid, fecha) in enumerate(pend, 1):
        try:
            eqs, lz = leer_box(box(gid))
        except Exception as e:
            eqs, lz = None, None
            print("   %s: %s" % (gid, str(e)[:80]))
        if not eqs:
            sin += 1; continue
        cod = (gid[8:10], gid[10:12])
        for i in (0, 1):
            team, opp = EQUIPOS.get(cod[i], cod[i]), EQUIPOS.get(cod[1 - i], cod[1 - i])
            fila = {"gamePk": gid, "league": "KBO", "game_date": fecha, "team": team, "opp": opp, "is_home": str(i)}
            fila.update(eqs[i]); filas.append(fila)
            for p in lz[i]:
                q = {"game_id": gid, "game_date": fecha, "liga": "kbo", "team": team, "opp": opp, "is_home": str(i)}
                q.update(p); lanz.append(q)
        ok += 1
        if j % 50 == 0:
            escribir(OUT, filas, ["gamePk", "league", "game_date", "team", "opp", "is_home"])
            escribir(OUT_P, lanz, ["game_id", "game_date", "liga", "team", "opp", "is_home", "jugador", "abridor"])
            print("  %d/%d juegos (%d con box)" % (j, len(pend), ok))
        time.sleep(PAUSA)
    escribir(OUT, filas, ["gamePk", "league", "game_date", "team", "opp", "is_home"])
    escribir(OUT_P, lanz, ["game_id", "game_date", "liga", "team", "opp", "is_home", "jugador", "abridor"])
    print("Listo: %d juegos con box, %d sin box. %s y %s" % (ok, sin, OUT, OUT_P))
    print("Despues: python utilidades\\semillas.py exportar kbo_box")
    return 0


if __name__ == "__main__":
    sys.exit(main())
