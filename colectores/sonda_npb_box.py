# -*- coding: utf-8 -*-
"""
colectores/sonda_npb_box.py - prueba si npb.jp entrega el box score completo (bateo y pitcheo por jugador) sin navegador.
Solo imprime lo que contesta; no escribe nada. Pega la salida en el chat para armar el colector (igual que con KBO).

    cd C:\\Edgeline_repo
    python colectores\\sonda_npb_box.py 2026-09-27
"""
import re, sys, urllib.request, html as H

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "ja,en;q=0.8"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def tablas(h):
    out = []
    for t in re.findall(r"<table.*?</table>", h, flags=re.S | re.I):
        filas = []
        for tr in re.findall(r"<tr.*?</tr>", t, flags=re.S | re.I):
            celdas = [H.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.S | re.I)]
            if celdas:
                filas.append(celdas)
        if filas:
            out.append(filas)
    return out


def main():
    dia = sys.argv[1] if len(sys.argv) > 1 else "2026-09-27"
    y, m, d = dia.split("-")
    cands = ["https://npb.jp/games/%s/schedule_%s_detail.html" % (y, m), "https://npb.jp/scores/%s/%s%s/" % (y, m, d)]
    links = []
    for u in cands:
        try:
            st, h = get(u)
            print("%s -> HTTP %s, %d caracteres" % (u, st, len(h)))
            ls = sorted(set(re.findall(r'href="(/scores/%s/%s%s/[^"]+/)(?:index\.html)?"' % (y, m, d), h)))
            print("   enlaces de juegos del dia:", ls[:8])
            links += ls
        except Exception as e:
            print("%s -> error %s" % (u, str(e)[:120]))
    if not links:
        print("No encontre enlaces de juegos para ese dia."); return
    base = "https://npb.jp" + links[0]
    for sub in ("box.html", "index.html", ""):
        u = base + sub
        try:
            st, h = get(u)
        except Exception as e:
            print("\n%s -> error %s" % (u, str(e)[:120])); continue
        print("\n=== %s  HTTP %s, %d caracteres" % (u, st, len(h)))
        T = tablas(h)
        print("Tablas: %d" % len(T))
        for i, t in enumerate(T[:12]):
            print("\n-- tabla %d (%d filas)" % (i, len(t)))
            for fila in t[:4]:
                print("   ", " | ".join(fila)[:220])


if __name__ == "__main__":
    main()
