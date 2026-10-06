# -*- coding: utf-8 -*-
"""
colectores/sonda_kbo_box.py - prueba si el sitio de KBO entrega el box score completo (AB, H, HR, K, IP por jugador)
sin navegador. Solo imprime lo que contesta; no escribe nada. Pega la salida en el chat para armar el colector.

    cd C:\\Edgeline_repo
    python colectores\\sonda_kbo_box.py 20260927
"""
import json, sys, urllib.parse, urllib.request

LISTA = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
CANDIDATOS = ["https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll",
              "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScore",
              "https://www.koreabaseball.com/ws/Schedule.asmx/GetScoreBoardScroll"]


def post(url, datos):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode(), headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    dia = sys.argv[1] if len(sys.argv) > 1 else "20260927"
    st, txt = post(LISTA, {"leId": "1", "srId": "0,3,4,5,7", "date": dia})
    try:
        juegos = json.loads(txt).get("game", [])
    except Exception:
        juegos = []
    print("Lista %s: HTTP %s, %d juegos" % (dia, st, len(juegos)))
    if not juegos:
        print(txt[:800]); return
    g = juegos[0]
    p = {"leId": "1", "srId": str(g.get("SR_ID", "0")), "seasonId": str(g.get("SEASON_ID", dia[:4])), "gameId": g.get("G_ID")}
    print("Juego de prueba:", p)
    for url in CANDIDATOS:
        print("\n=== %s" % url)
        try:
            st, txt = post(url, p)
            print("HTTP %s, %d caracteres" % (st, len(txt)))
            try:
                d = json.loads(txt)
                print("Llaves:", list(d.keys())[:20] if isinstance(d, dict) else type(d).__name__)
            except Exception:
                pass
            print(txt[:2500])
        except Exception as e:
            print("Error:", str(e)[:200])


if __name__ == "__main__":
    main()
