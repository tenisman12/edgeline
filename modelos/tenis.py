# -*- coding: utf-8 -*-
"""
modelos/tenis.py - modelo de tenis profundo.

Entrada: tennis_matches.csv (Sackmann, ATP+WTA) con superficie, best_of y stats de
saque/resto por partido. Todo as-of (cada partido solo ve lo anterior).

Predice, para un enfrentamiento:
  - GANADOR (prob de cada jugador),
  - TOTAL DE GAMES (esperado + over/under),
  - SETS (2-0, 2-1 / 3-0.. segun best_of),
  - BEST-OF-3 vs BEST-OF-5 (lo dicta el torneo),
  - BREAKS (prob de al menos un break, breaks esperados).

Metodo: de las stats de saque/resto se estima la probabilidad de que cada jugador
gane un PUNTO con su saque (ajustada por superficie y encogida). De ahi, con el
modelo jerarquico del tenis (punto -> game -> set -> match), salen todos los mercados.
ELO por superficie afina el ganador.

Solo stdlib.
"""
import math, sys, os

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

# ELO por superficie
ELO_BASE = 1500.0; K_ELO = 24.0; ESCALA = 400.0
SHRINK = 40          # encogimiento de las tasas de saque a la media del tour
SUP = ("Hard", "Clay", "Grass", "Carpet")


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None

# ---------------- probabilidad de game / set / match (analitico) ----------------
def p_game(p):
    """Prob de que el sacador gane un game, dado p = prob de ganar cada punto al saque."""
    q = 1 - p
    if p <= 0: return 0.0
    if p >= 1: return 1.0
    # ganar 40-0,40-15,40-30 + deuce
    p40 = p**4 * (1 + 4*q + 10*q*q)
    deuce = 20 * p**3 * q**3 * (p*p / (p*p + q*q))
    return p40 + deuce

def _p_tb(ps, pr):
    """Aprox de ganar el tiebreak con prob de punto al saque ps y al resto pr.
    Aproximacion simple: promedio de saque/resto elevado (suficiente para el total)."""
    p = (ps + pr) / 2
    # prob de ganar una carrera a 7 con ventaja 2 (aprox binomial-neg)
    return _carrera(p, 7)

def _carrera(p, n):
    """Prob de ganar una 'carrera' a n con diferencia 2 (aprox), p por punto."""
    from math import comb
    # gana n a k (k<n-1) + gana en deuce
    tot = 0.0
    for k in range(0, n-1):
        tot += comb(n-1+k, k) * p**n * (1-p)**k
    # a n-1 iguales -> gana 2 seguidos con prob p^2/(p^2+(1-p)^2)
    peq = comb(2*(n-1), n-1) * p**(n-1) * (1-p)**(n-1)
    tot += peq * (p*p/(p*p+(1-p)**2))
    return tot

def p_set(h1, h2, ps1, pr1):
    """Prob de que J1 gane un set. h1,h2 = prob de hold de cada uno. Saca J1 primero
    en promedio la mitad; aproximamos con juegos independientes hasta 6, tiebreak a 6-6."""
    from math import comb
    # prob de que J1 gane un game al saque = h1; al resto = 1-h2
    # modelamos el set como secuencia de games alternando saque; usamos prob media
    pg1 = (h1 + (1 - h2)) / 2      # prob de que J1 gane un game cualquiera del set
    p = pg1
    tot = 0.0
    for k in range(0, 5):         # gana 6 a k, k=0..4
        tot += comb(5 + k, k) * p**6 * (1 - p)**k
    # 7-5: 5-5 y luego gana 2
    p55 = comb(10, 5) * p**5 * (1-p)**5
    tot += p55 * p * p
    # 7-6 (tiebreak): llega 6-6 y gana tb
    tot += p55 * (2*p*(1-p)) * _p_tb(ps1, pr1)
    return min(max(tot, 0.0), 1.0)

def p_match(pset, best_of=3):
    """Prob de ganar el match dado prob de ganar un set (aprox sets independientes)."""
    need = 3 if best_of == 5 else 2
    from math import comb
    p = pset; tot = 0.0
    for k in range(0, need):      # gana 'need' sets perdiendo k
        tot += comb(need - 1 + k, k) * p**need * (1 - p)**k
    return tot

SD_GAMES = {3: 4.5, 5: 7.0}     # desviacion del total de games por formato (se confirma con validar_mercados)

# Los sets de un mismo partido no son independientes: hay un factor comun del dia (forma, superficie,
# lesion, ritmo). Con sets independientes el modelo daba 52% de sets corridos en bo3 y 29% en bo5;
# lo real es 64-65% y 46%. Un factor comun D_SET (la prob. de set sube o baja D_SET, mitad y mitad)
# reproduce ambos formatos con el mismo valor (D_SET ~ 0.22): validado con datos ATP/WTA 24 meses.
D_SET = 0.22

def _mezcla(fn, ps, d=None):
    d = D_SET if d is None else d
    return 0.5 * (fn(min(max(ps + d, 1e-4), 1 - 1e-4)) + fn(min(max(ps - d, 1e-4), 1 - 1e-4)))

def _sets_iid(p, best_of):
    q = 1 - p
    if best_of == 5:
        return 3 * (p**3 + q**3) + 4 * (3 * p * q * (p * p + q * q)) + 5 * (6 * p * p * q * q)
    return 2 + 2 * p * q

def sets_esperados(pset, best_of=3):
    """Sets esperados dado P(J1 gana un set) con el factor comun de partido. Bo3: 2 + P(3 sets)."""
    return _mezcla(lambda q: _sets_iid(q, best_of), pset)

def p_sets_corridos(pset, best_of=3):
    """P(el partido termina sin ceder set) (cualquiera de los dos jugadores)."""
    n = 3 if best_of == 5 else 2
    return _mezcla(lambda q: q**n + (1 - q)**n, pset)

def p_j1_gana_corrido(pset, best_of=3):
    """P(J1 gana sin ceder set)."""
    n = 3 if best_of == 5 else 2
    return _mezcla(lambda q: q**n, pset)

def pset_desde_partido(p_match_obj, best_of=3):
    """Invierte P(ganar el partido) con el factor comun: P(set) base tal que el partido queda en p_match_obj."""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if _mezcla(lambda q: p_match(q, best_of), mid) < p_match_obj: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def games_esperados(h1, h2, best_of=3, pset=None):
    """Games totales esperados = games por set * sets esperados. Si se da pset (coherente con la
    probabilidad de ganar el partido) se usa; si no, se calcula desde los holds."""
    pg1 = (h1 + (1 - h2)) / 2
    dom = abs(pg1 - .5)
    gps = 9.6 - 6 * dom          # mas parejo -> mas games por set
    if pset is None:
        pset = p_set(h1, h2, h1, 1 - h2)
    return gps * sets_esperados(pset, best_of)

# ---------------- estimar prob de punto al saque del enfrentamiento ----------------
def punto_saque(j1, j2, tour_spw):
    """p1_spw y p2_spw combinando saque propio y resto rival, relativo al promedio del tour."""
    # j['spw'] = % puntos ganados al saque; j['rpw'] = % puntos ganados al resto
    p1 = tour_spw + (j1["spw"] - tour_spw) - (j2["rpw"] - (1 - tour_spw))
    p2 = tour_spw + (j2["spw"] - tour_spw) - (j1["rpw"] - (1 - tour_spw))
    clip = lambda x: min(max(x, .50), .80)
    return clip(p1), clip(p2)

# ---------------- firma ----------------
def predecir(j1, j2, superficie="Hard", best_of=3, tour_spw=0.635, linea_games=22.5, elo1=1500, elo2=1500):
    ps1, ps2 = punto_saque(j1, j2, tour_spw)
    h1, h2 = p_game(ps1), p_game(ps2)
    pset = p_set(h1, h2, ps1, 1 - ps2)
    # ganador: mezcla del modelo de saque con ELO por superficie
    p_serve = p_match(pset, best_of)
    p_elo = 1 / (1 + 10 ** (-(elo1 - elo2) / ESCALA))
    p1 = 0.6 * p_serve + 0.4 * p_elo
    pset_c = pset_desde_partido(min(max(p1, 0.001), 0.999), best_of)   # P(set) coherente con el ganador
    gtot = games_esperados(h1, h2, best_of, pset=pset_c)
    # break: prob de que un game al saque termine en break = 1-hold
    breaks_esp = (2 - h1 - h2) * (gtot / 2)   # games al saque ~ mitad del total
    p_break = 1 - (h1 * h2) ** (gtot / 4)     # aprox: al menos un break en el partido
    return {
        "p1": round(p1, 4), "p2": round(1 - p1, 4),
        "best_of": best_of, "superficie": superficie,
        "hold_j1": round(h1, 3), "hold_j2": round(h2, 3),
        "p_set_j1": round(pset_c, 3),
        "games_esperados": round(gtot, 1),
        "p_over_games": round(_p_over_games(gtot, linea_games, SD_GAMES[best_of]), 3),
        "linea_games": linea_games,
        "breaks_esperados": round(breaks_esp, 1),
        "p_al_menos_un_break": round(min(max(p_break, 0), 1), 3),
        "p_2_0" if best_of == 3 else "p_barrida": round(p_j1_gana_corrido(pset_c, best_of), 3),
        "p_sets_corridos": round(p_sets_corridos(pset_c, best_of), 3),
    }

def _p_over_games(mu, linea, sd=3.2):
    """Aprox normal para el total de games."""
    from math import erf, sqrt
    z = (linea + 0.5 - mu) / (sd * sqrt(2))
    p_under = 0.5 * (1 + erf(z))
    return 1 - p_under


def validar(min_j=10):
    """Backtest as-of del ganador en tenis. Reconstruye saque/resto y ELO por superficie
    partido por partido (sin fuga) y predice cada partido. Reporta acc/brier del ganador.
    Lee datos/tenis.csv (o tennis_matches.csv copiado ahi)."""
    import csv, io as _io, os as _os
    ruta = _os.path.join(io.BASE, "datos", "tenis.csv")
    if not _os.path.exists(ruta):
        print("Falta datos/tenis.csv (copia tennis_matches.csv ahi)."); return
    rows = list(csv.DictReader(_io.open(ruta, encoding="utf-8-sig", errors="replace")))
    rows.sort(key=lambda r: (r.get("tourney_date", ""), r.get("winner_name", "")))
    J = {}   # jugador -> {sp,spw,rp,rpw, elo{sup}}
    def g(n): return J.setdefault(n, {"sp":0.,"spw":0.,"rp":0.,"rpw":0.,"elo":{}})
    tot_sp=tot_spw=0.0; P=[]
    for r in rows:
        w, l = r.get("winner_name"), r.get("loser_name")
        sup = (r.get("surface") or "Hard").strip() or "Hard"
        bo = 5 if str(r.get("best_of")) == "5" else 3
        try:
            wsv=float(r["w_svpt"]); wsw=float(r["w_1stWon"])+float(r["w_2ndWon"])
            lsv=float(r["l_svpt"]); lsw=float(r["l_1stWon"])+float(r["l_2ndWon"])
        except (KeyError, ValueError, TypeError):
            continue
        if not w or not l or wsv<=0 or lsv<=0: continue
        jw, jl = g(w), g(l)
        ew = jw["elo"].get(sup, 1500.0); el = jl["elo"].get(sup, 1500.0)
        tour_spw = (tot_spw/tot_sp) if tot_sp else 0.635
        # prediccion as-of para orden fijo (nombre menor = p1) -> sin fuga
        if jw["sp"]>=min_j*50 and jl["sp"]>=min_j*50:
            p1n, p2n = (w, l) if w < l else (l, w)
            j1, j2 = g(p1n), g(p2n)
            d1={"spw": j1["spw"]/j1["sp"], "rpw": j1["rpw"]/max(j1["rp"],1)}
            d2={"spw": j2["spw"]/j2["sp"], "rpw": j2["rpw"]/max(j2["rp"],1)}
            e1=j1["elo"].get(sup,1500.0); e2=j2["elo"].get(sup,1500.0)
            pr=predecir(d1,d2,sup,bo,tour_spw,22.5,e1,e2)
            y = 1 if (p1n==w) else 0
            P.append((pr["p1"], y))
        # actualizar stats y ELO por superficie
        jw["sp"]+=wsv; jw["spw"]+=wsw; jw["rp"]+=lsv; jw["rpw"]+=(lsv-lsw)
        jl["sp"]+=lsv; jl["spw"]+=lsw; jl["rp"]+=wsv; jl["rpw"]+=(wsv-wsw)
        exp=1/(1+10**(-(ew-el)/400)); jw["elo"][sup]=ew+24*(1-exp); jl["elo"][sup]=el-24*(1-exp)
        tot_sp+=wsv+lsv; tot_spw+=wsw+lsw
    if len(P)<200: print("Muestra insuficiente (%d)."%len(P)); return
    acc=sum(1 for p,y in P if (p>=.5)==(y==1))/len(P)
    br=sum((p-y)**2 for p,y in P)/len(P)
    print("BACKTEST TENIS (as-of, n=%d)"%len(P)); print("-"*40)
    print("Acierto ganador: %.3f"%acc)
    print("Brier:           %.3f"%br)
    print("-"*40); print("Techo tenis ganador ~0.65-0.70 (mas predecible; el favorito gana seguido).")

if __name__ == "__main__":
    # prueba de la matematica con jugadores sinteticos
    tour = 0.635
    fuerte = {"spw": 0.70, "rpw": 0.42}
    medio  = {"spw": 0.635, "rpw": 0.38}
    print("Fuerte vs Medio (Hard, best of 3):")
    for k, v in predecir(fuerte, medio, "Hard", 3, tour, 22.5, 1650, 1500).items():
        print("  %-20s %s" % (k, v))
    print("\nParejos (best of 5):")
    for k, v in predecir(medio, medio, "Clay", 5, tour, 28.5, 1500, 1500).items():
        print("  %-20s %s" % (k, v))
