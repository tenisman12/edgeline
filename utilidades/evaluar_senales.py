# -*- coding: utf-8 -*-
"""
EVALUAR SENALES - mide, sobre TUS juegos pasados, cuanto vale cada senal.

No inventa pesos: los mide. Lee data_maestra/espn_<liga>_summary.jsonl (juegos ya
terminados) y reporta, por deporte:

  - Ventaja de local           : con que frecuencia gana el local (y empata, en futbol).
  - ESPN winprob (pregame)      : accuracy y Brier del modelo de ESPN (si el deporte lo trae).
  - Mercado (moneyline)         : accuracy y Brier de la linea (pickcenter) = el piso a vencer.
                                  Deportes con empate (futbol) se evaluan a 3 resultados
                                  (local / empate / visitante) con la cuota del empate.
  - Calibracion ESPN winprob    : cuando dice 60-70%, ¿realmente gana ~65%?
  - Divergencia ESPN vs mercado : cuando difieren, ¿quien acierta mas?

Uso (en C:\\Edgeline):
    python evaluar_senales.py            (todos los deportes bajados)
    python evaluar_senales.py --liga mlb
"""
import argparse, io, os, json, glob

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")


def am2p(ml):
    ml = float(ml)
    return (-ml) / ((-ml) + 100) if ml < 0 else 100 / (ml + 100)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def evaluar(liga):
    JL = os.path.join(BASE, "data_maestra", "espn_%s_summary.jsonl" % liga)
    if not os.path.exists(JL):
        print("No existe %s." % JL); return

    n = 0; home_w = 0; draws = 0
    wp_ok = wp_n = 0; wp_brier = 0.0
    mk_ok = mk_n = 0; mk_brier = 0.0            # 2 resultados
    m3_ok = m3_n = 0; m3_brier = 0.0; m3_draw_pred = 0   # 3 resultados
    cal = {}
    div_n = div_espn = div_mkt = 0
    UMBRAL = 0.07

    for line in io.open(JL, encoding="utf-8"):
        try:
            sm = json.loads(line)["summary"]
        except Exception:
            continue
        comp = ((sm.get("header") or {}).get("competitions") or [{}])[0]
        cs = comp.get("competitors") or []
        home = next((c for c in cs if c.get("homeAway") == "home"), None)
        away = next((c for c in cs if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        hs, as_ = _f(home.get("score")), _f(away.get("score"))
        estado = ((comp.get("status") or {}).get("type") or {}).get("completed")
        if estado is False or hs is None or as_ is None:
            continue
        if home.get("winner") is None and away.get("winner") is None and hs == as_ == 0 and estado is None:
            continue
        # resultado por marcador: 1 local, 0 empate, -1 visitante
        res = 1 if hs > as_ else (-1 if hs < as_ else 0)
        hw = 1 if res == 1 else 0
        n += 1; home_w += hw; draws += 1 if res == 0 else 0

        # ESPN winprob pregame
        wparr = sm.get("winprobability") or []
        pe = None
        if wparr and wparr[0].get("homeWinPercentage") is not None:
            pe = wparr[0]["homeWinPercentage"]
            wp_n += 1
            if (pe > 0.5) == (hw == 1): wp_ok += 1
            wp_brier += (pe - hw) ** 2
            b = int(min(pe, 0.999) * 10) / 10.0
            c = cal.setdefault(b, [0, 0]); c[0] += hw; c[1] += 1

        # mercado
        pm = None
        pc = sm.get("pickcenter") or []
        if pc:
            ho = (pc[0].get("homeTeamOdds") or {}).get("moneyLine")
            ao = (pc[0].get("awayTeamOdds") or {}).get("moneyLine")
            do = (pc[0].get("drawOdds") or {}).get("moneyLine")
            if ho and ao and do:
                # 3 resultados (futbol): de-vig sobre las tres probabilidades
                ph, pd, pa = am2p(ho), am2p(do), am2p(ao)
                s = ph + pd + pa
                ph, pd, pa = ph / s, pd / s, pa / s
                m3_n += 1
                probs = {1: ph, 0: pd, -1: pa}
                pred = max(probs, key=probs.get)
                if pred == res: m3_ok += 1
                if pred == 0: m3_draw_pred += 1
                m3_brier += sum((probs[k] - (1 if k == res else 0)) ** 2 for k in probs)
            elif ho and ao:
                ph, pa = am2p(ho), am2p(ao); pm = ph / (ph + pa)
                mk_n += 1
                if (pm > 0.5) == (hw == 1): mk_ok += 1
                mk_brier += (pm - hw) ** 2

        if pe is not None and pm is not None and abs(pe - pm) >= UMBRAL:
            div_n += 1
            if (pe > 0.5) == (hw == 1): div_espn += 1
            if (pm > 0.5) == (hw == 1): div_mkt += 1

    if n == 0:
        print("  (%s: sin juegos terminados)" % liga); return
    print("=" * 60)
    print("  %s   (%d juegos terminados)" % (liga.upper(), n))
    print("=" * 60)
    if m3_n:
        print("  Resultados:              local %.1f%% | empate %.1f%% | visitante %.1f%%"
              % (100 * home_w / n, 100 * draws / n, 100 * (n - home_w - draws) / n))
    else:
        print("  Ventaja de local:        gana el local %.1f%%" % (100 * home_w / n))
    if wp_n:
        print("  ESPN winprob (pregame):  acc %.1f%%   Brier %.3f   (n=%d)"
              % (100 * wp_ok / wp_n, wp_brier / wp_n, wp_n))
    if mk_n:
        print("  Mercado (moneyline):     acc %.1f%%   Brier %.3f   (n=%d)"
              % (100 * mk_ok / mk_n, mk_brier / mk_n, mk_n))
    if m3_n:
        print("  Mercado 3 resultados:    acc %.1f%%   Brier(3) %.3f   (n=%d)"
              % (100 * m3_ok / m3_n, m3_brier / m3_n, m3_n))
        print("     (acertar 1X2 al azar ronda 33-45%%; el mercado elige empate en %d de %d)"
              % (m3_draw_pred, m3_n))
    if div_n:
        print("  DIVERGENCIA >=7pts (n=%d):  ESPN acierta %.1f%%  |  mercado %.1f%%"
              % (div_n, 100 * div_espn / div_n, 100 * div_mkt / div_n))
    if cal:
        print("  Calibracion ESPN winprob (dice X% -> gana el local Y%):")
        for b in sorted(cal):
            w, nn = cal[b]
            if nn >= 5:
                print("     dice %2.0f-%2.0f%%  ->  real %5.1f%%   (n=%d)"
                      % (b * 100, b * 100 + 10, 100 * w / nn, nn))
    print()


def descubrir():
    ligas = []
    for p in sorted(glob.glob(os.path.join(BASE, "data_maestra", "espn_*_summary.jsonl"))):
        nombre = os.path.basename(p)
        ligas.append(nombre[len("espn_"):-len("_summary.jsonl")])
    return ligas


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--liga")
    liga = ap.parse_args().liga
    if liga:
        evaluar(liga); return
    ligas = descubrir()
    if not ligas:
        print("No hay espn_*_summary.jsonl en data_maestra."); return
    print("Evaluando: %s\n" % ", ".join(ligas))
    for lg in ligas:
        evaluar(lg)


if __name__ == "__main__":
    main()
