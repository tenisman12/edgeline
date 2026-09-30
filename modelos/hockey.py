# -*- coding: utf-8 -*-
"""
modelos/hockey.py - modelo de hockey (NHL) con la firma comun.

Lee datos/hockey.csv (una fila por equipo-juego: goles a favor/en contra + opcional
stats de portero). Todo as-of. Predice:
  - GANADOR (regulacion + OT),
  - TOTAL de goles (over/under),
  - PUCK LINE (-1.5 / +1.5),
  - ajuste por PORTERO titular cuando hay save% disponible.

Metodo: ELO por goles + tasas ofensiva/defensiva as-of -> goles esperados (Log5) ->
dos Poisson -> todos los mercados. Calibracion Platt sobre las predicciones as-of.

Solo stdlib.
"""
import math, sys, os

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

BASE_ELO = 1500.0; K = 6.0; HFA = 35.0; REGR = 0.75; ESCALA = 400.0
VENT_LOCAL = 0.04; SHRINK = 12; OT_LOCAL = 0.55   # ventaja local en OT


def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None

def _sig(z): return 0.0 if z < -35 else (1.0 if z > 35 else 1/(1+math.exp(-z)))

def _pois(mu, k): return math.exp(-mu) * mu**k / math.factorial(k)

# ---------------- armado as-of ----------------
def _juegos(liga=None):
    filas = io.cargar_juegos("hockey", liga)
    porjuego = {}
    for r in filas:
        gp = str(r.get("gamePk") or r.get("game_id") or "")
        porjuego.setdefault(gp, []).append(r)
    juegos = []
    for gp, par in porjuego.items():
        if len(par) != 2: continue
        h = next((x for x in par if str(x.get("is_home")) in ("1","1.0","True")), None)
        a = next((x for x in par if x is not h), None)
        if not h or not a: continue
        f = (h.get("game_date") or "")[:10]
        if f: juegos.append((f, gp, h, a))
    juegos.sort(key=lambda t:(t[0], t[1]))
    return juegos

class Eq:
    __slots__=("elo","gf","ga","n","sv","s0","ult")
    def __init__(s): s.elo=BASE_ELO; s.gf=0.0; s.ga=0.0; s.n=0; s.sv=0.0; s.s0=0; s.ult=None
    def of(s,lg): return (s.gf+SHRINK*lg)/(s.n+SHRINK) if s.n else lg
    def df(s,lg): return (s.ga+SHRINK*lg)/(s.n+SHRINK) if s.n else lg

def entrenar(liga=None, min_j=8):
    juegos=_juegos(liga)
    eq={}; tot=0.0; ng=0; lg=3.0; cal=[]
    season=lambda f: f[:4]
    for f,gp,h,a in juegos:
        gh,ga_=_f(h.get("goals")),_f(h.get("goals_opp"))
        if gh is None: gh=_f(h.get("runs"))            # por si el esquema usa runs
        if ga_ is None: ga_=_f(h.get("runs_opp"))
        ah=_f(a.get("goals")) or _f(a.get("runs")); aa=_f(a.get("goals_opp")) or _f(a.get("runs_opp"))
        gh = gh if gh is not None else ah; ga_ = ga_ if ga_ is not None else aa
        if gh is None or ga_ is None: continue
        th=eq.setdefault(h.get("team"),Eq()); ta=eq.setdefault(a.get("team"),Eq())
        for t in (th,ta):
            if t.ult and t.ult!=season(f): t.elo=BASE_ELO+(t.elo-BASE_ELO)*REGR
            t.ult=season(f)
        # prediccion as-of
        if th.n>=min_j and ta.n>=min_j:
            p=_pred_p(th,ta,lg)
            cal.append((p, 1 if gh>ga_ else 0))
        # ELO update
        esp=_sig((th.elo+HFA-ta.elo)/(ESCALA/math.log(10)))
        res=1.0 if gh>ga_ else 0.0
        mov=math.log(abs(gh-ga_)+1)
        d=K*mov*(res-esp); th.elo+=d; ta.elo-=d
        th.gf+=gh; th.ga+=ga_; th.n+=1; ta.gf+=ga_; ta.ga+=gh; ta.n+=1
        tot+=gh+ga_; ng+=2; lg=tot/ng
    a,b=_platt(cal)
    return {"eq":eq,"lg":lg,"platt":(a,b),"cal":cal}

def _xg(estado, home, away, sv_home=None, sv_away=None):
    eq,lg=estado["eq"],estado["lg"]
    th,ta=eq.get(home),eq.get(away)
    if not th or not ta: return None,None
    xh=th.of(lg)*ta.df(lg)/lg*(1+VENT_LOCAL)
    xa=ta.of(lg)*th.df(lg)/lg*(1-VENT_LOCAL)
    # ajuste por portero: save% del titular vs liga (~.905). Mejor portero -> menos goles en contra.
    if sv_away is not None: xh *= (1-(sv_away-0.905))/(1)   # portero visitante frena al local
    if sv_home is not None: xa *= (1-(sv_home-0.905))/(1)
    return max(xh,0.3),max(xa,0.3)

def _pred_p(th,ta,lg):
    xh=th.of(lg)*ta.df(lg)/lg*(1+VENT_LOCAL); xa=ta.of(lg)*th.df(lg)/lg*(1-VENT_LOCAL)
    return _prob_home(max(xh,.3),max(xa,.3))

def _prob_home(xh,xa,kmax=12):
    ph=[_pois(xh,k) for k in range(kmax)]; pa=[_pois(xa,k) for k in range(kmax)]
    p_reg=sum(ph[i]*pa[j] for i in range(kmax) for j in range(i))
    p_tie=sum(ph[i]*pa[i] for i in range(kmax))
    return p_reg + OT_LOCAL*p_tie

def _platt(cal, iters=600, lr=0.05):
    if len(cal)<200: return 1.0,0.0
    lo=lambda p:math.log(min(max(p,1e-6),1-1e-6)/(1-min(max(p,1e-6),1-1e-6)))
    X=[lo(p) for p,_ in cal]; Y=[y for _,y in cal]; n=len(X); a,b=1.0,0.0
    for _ in range(iters):
        ga=gb=0.0
        for x,y in zip(X,Y):
            e=_sig(a*x+b)-y; ga+=e*x; gb+=e
        a-=lr*ga/n; b-=lr*gb/n
    return a,b

# ---------------- firma comun ----------------
def predecir(estado, home, away, linea_total=6.5, sv_home=None, sv_away=None):
    xh,xa=_xg(estado,home,away,sv_home,sv_away)
    if xh is None: return None
    a,b=estado["platt"]
    lo=lambda p:math.log(min(max(p,1e-6),1-1e-6)/(1-min(max(p,1e-6),1-1e-6)))
    p=_sig(a*lo(_prob_home(xh,xa))+b)
    mu=xh+xa; piso=int(math.floor(linea_total))
    p_over=1-sum(_pois(mu,k) for k in range(piso+1))
    # puck line -1.5: P(home - away >= 2) en regulacion (aprox)
    kmax=12; ph=[_pois(xh,k) for k in range(kmax)]; pa=[_pois(xa,k) for k in range(kmax)]
    p_pl_home=sum(ph[i]*pa[j] for i in range(kmax) for j in range(kmax) if i-j>=2)
    conf="alta" if abs(p-.5)>.15 else "media" if abs(p-.5)>.07 else "baja"
    return {"p_home":round(p,4),"p_away":round(1-p,4),
            "xg_home":round(xh,2),"xg_away":round(xa,2),"total":round(mu,2),
            "p_over":round(p_over,4),"linea_total":linea_total,
            "p_pl_home":round(p_pl_home,4),"p_pl_away":round(1-p_pl_home,4),
            "confianza":conf}

def validar(liga=None):
    """Backtest as-of: entrena viendo solo el pasado y evalua las predicciones que
    hizo antes de cada juego. Reporta acc/brier/logloss, sin y con calibracion Platt."""
    est=entrenar(liga)
    cal=est.get("cal") or []
    if len(cal)<200:
        print("Muestra insuficiente (%d)." % len(cal)); return
    a,b=est["platt"]
    lo=lambda p:math.log(min(max(p,1e-6),1-1e-6)/(1-min(max(p,1e-6),1-1e-6)))
    def acc(P): return sum(1 for p,y in P if (p>=.5)==(y==1))/len(P)
    def brier(P): return sum((p-y)**2 for p,y in P)/len(P)
    def logl(P):
        s=0.0
        for p,y in P:
            p=min(max(p,1e-6),1-1e-6); s+=-(y*math.log(p)+(1-y)*math.log(1-p))
        return s/len(P)
    cal_c=[(_sig(a*lo(p)+b),y) for p,y in cal]
    base=sum(y for _,y in cal)/len(cal)
    print("BACKTEST HOCKEY (as-of, n=%d)"%len(cal))
    print("-"*52)
    print("%-14s %8s %8s %8s"%("","ACC","BRIER","LOGLOSS"))
    print("modelo        %8.3f %8.3f %8.3f"%(acc(cal),brier(cal),logl(cal)))
    print("calibrado     %8.3f %8.3f %8.3f"%(acc(cal_c),brier(cal_c),logl(cal_c)))
    print("siempre local %8.3f %8.3f      -"%(base,sum((base-y)**2 for _,y in cal)/len(cal)))
    print("-"*52)
    print("Techo realista hockey ganador ~0.55-0.58. El valor real esta en total y edge.")
    return est


if __name__=="__main__":
    # prueba de la logica con estado sintetico
    est={"eq":{},"lg":3.0,"platt":(1.0,0.0)}
    class E:
        def __init__(s,of,df,n=50): s.o=of; s.d=df; s.n=n
        def of(s,lg): return s.o
        def df(s,lg): return s.d
    est["eq"]={"Oilers":E(3.6,3.1),"Kings":E(2.9,2.7)}
    print("Oilers (local, ofensivo) vs Kings:")
    for k,v in predecir(est,"Oilers","Kings",6.5).items(): print("  %-14s %s"%(k,v))
    print("\ncon portero visitante elite (sv .930):")
    for k,v in predecir(est,"Oilers","Kings",6.5,sv_away=.930).items(): print("  %-14s %s"%(k,v))
