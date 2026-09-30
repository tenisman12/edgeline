# -*- coding: utf-8 -*-
"""
nucleo/indicadores.py - panel estilo Z Code para un enfrentamiento.

De los datos (datos/<deporte>.csv) y el historial, calcula por equipo y por juego los
indicadores profundos: power rank, status de forma, rachas, marcador proyectado,
win %, spread forecast, total, TEAM TOTALS, confianza, estrellas y osciladores.

No depende de features: arma su propio estado por equipo (ELO + tasas) para poder
predecir cualquier enfrentamiento futuro. Beisbol de referencia; se generaliza.

Lo que NO calcula (necesita feed pagado): % del publico / consenso de tickets.
"""
import math, sys, os

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

BASE_ELO=1500.0; K=6.0; HFA=24.0; REGR=0.70; ESCALA=400.0
VENT=0.03; NB_DISP=4.0; SHRINK=8


def _f(x):
    try:
        v=float(x); return None if v!=v else v
    except (TypeError,ValueError): return None
def _sig(z): return 0.0 if z<-35 else (1.0 if z>35 else 1/(1+math.exp(-z)))
def _nb(k,mu,r=NB_DISP):
    p=r/(r+mu)
    return math.exp(math.lgamma(k+r)-math.lgamma(r)-math.lgamma(k+1)+r*math.log(p)+k*math.log(1-p))

def _juegos(deporte, liga):
    filas=io.cargar_juegos(deporte,liga)
    pj={}
    for r in filas:
        gp=str(r.get("gamePk") or r.get("game_id") or "")
        pj.setdefault(gp,[]).append(r)
    js=[]
    for gp,par in pj.items():
        if len(par)!=2: continue
        h=next((x for x in par if str(x.get("is_home")) in ("1","1.0","True")),None)
        a=next((x for x in par if x is not h),None)
        if not h or not a: continue
        fecha=(h.get("game_date") or "")[:10]
        if fecha: js.append((fecha,gp,h,a))
    js.sort(key=lambda t:(t[0],t[1]))
    return js

class Eq:
    def __init__(s): s.elo=BASE_ELO; s.gf=0.0; s.ga=0.0; s.n=0; s.ult=None; s.res=[]; s.ou=[]
    def of(s,lg): return (s.gf+SHRINK*lg)/(s.n+SHRINK) if s.n else lg
    def df(s,lg): return (s.ga+SHRINK*lg)/(s.n+SHRINK) if s.n else lg

def construir_estado(deporte="beisbol", liga=None):
    js=_juegos(deporte,liga); eq={}; tot=0.0; ng=0; lg=4.5
    for f,gp,h,a in js:
        gh=_f(h.get("runs")) or _f(h.get("goals")); ga_=_f(h.get("runs_opp")) or _f(h.get("goals_opp"))
        if gh is None or ga_ is None: continue
        th=eq.setdefault(h.get("team"),Eq()); ta=eq.setdefault(a.get("team"),Eq())
        for t in (th,ta):
            if t.ult and t.ult!=f[:4]: t.elo=BASE_ELO+(t.elo-BASE_ELO)*REGR
            t.ult=f[:4]
        esp=_sig((th.elo+HFA-ta.elo)/(ESCALA/math.log(10)))
        res=1.0 if gh>ga_ else 0.0
        d=K*math.log(abs(gh-ga_)+1)*(res-esp); th.elo+=d; ta.elo-=d
        th.gf+=gh; th.ga+=ga_; th.n+=1; ta.gf+=ga_; ta.ga+=gh; ta.n+=1
        th.res.append("W" if gh>ga_ else "L"); ta.res.append("W" if ga_>gh else "L")
        ov = "O" if (gh+ga_)>lg*2 else "U"; th.ou.append(ov); ta.ou.append(ov)
        tot+=gh+ga_; ng+=2; lg=tot/ng
    return {"eq":eq,"lg":lg}

def _status(e, ranks):
    """Burning Hot / Hot / Average Up / Average Down / Cold / Dead segun forma + rank."""
    if e.n<6: return "New"
    w6=e.res[-6:].count("W")
    rank=ranks.get(id(e),16); N=len(ranks) or 30
    top=rank<=N*0.3; bot=rank>=N*0.7
    if w6>=5 and top: return "Burning Hot"
    if w6>=4: return "Hot" if not bot else "Average Up"
    if w6<=1 and bot: return "Dead"
    if w6<=2: return "Cold" if bot else "Average Down"
    return "Average Up" if top else "Average Down"

def _tt_over(mu, linea=2.5):
    piso=int(math.floor(linea))
    return 1-sum(_nb(k,mu) for k in range(piso+1))

def _estrellas(edge_o_conf):
    x=abs(edge_o_conf)
    return min(5.0, round(x/0.045*0.5)/0.5) if x>0 else 0.0

def panel(estado, home, away, linea_total=None, linea_spread=1.5):
    eq=estado["eq"]; lg=estado["lg"]; th,ta=eq.get(home),eq.get(away)
    if not th or not ta: return None
    # ranks por ELO
    orden=sorted(eq.values(), key=lambda e:-e.elo)
    ranks={id(e):i+1 for i,e in enumerate(orden)}; N=len(orden)
    # prediccion
    xh=th.of(lg)*ta.df(lg)/lg*(1+VENT); xa=ta.of(lg)*th.df(lg)/lg*(1-VENT)
    xh,xa=max(xh,.3),max(xa,.3)
    kmax=18; ph=[_nb(k,xh) for k in range(kmax)]; pa=[_nb(k,xa) for k in range(kmax)]
    p_home=sum(ph[i]*pa[j] for i in range(kmax) for j in range(i))+0.52*sum(ph[i]*pa[i] for i in range(kmax))
    p_elo=_sig((th.elo+HFA-ta.elo)/(ESCALA/math.log(10)))
    p_home=0.3*p_elo+0.7*p_home
    lt=linea_total if linea_total is not None else round((xh+xa)*2)/2
    p_over=1-sum(_nb(k,xh+xa) for k in range(int(math.floor(lt))+1))
    p_rl=sum(ph[i]*pa[j] for i in range(kmax) for j in range(kmax) if i-j>=int(math.floor(linea_spread))+1)
    conf=abs(p_home-.5)*2
    def eqinfo(e, gf):
        return {"power_rank":ranks[id(e)],"rating":"%d/%d"%(ranks[id(e)],N),
                "status":_status(e,ranks),"streak":" - ".join(e.res[-6:]),
                "last6":"%dW / %dL"%(e.res[-6:].count("W"),e.res[-6:].count("L")),
                "ou_streak":" - ".join(e.ou[-4:]),
                "tt_over_2.5":round(_tt_over(gf),2)}
    return {
        "home":home,"away":away,
        "score_prediction":"%s %.0f - %s %.0f"%(away,round(xa),home,round(xh)),
        "win_prob":{"home":round(p_home,3),"away":round(1-p_home,3)},
        "confidence":round(conf,3),
        "spread_forecast":{"linea":-linea_spread,"prob_home_cubre":round(p_rl,3)},
        "total":{"linea":lt,"prob_over":round(p_over,3)},
        "estrellas":_estrellas(conf/2),
        "info_home":eqinfo(th,xh),"info_away":eqinfo(ta,xa),
        "nota":"NO incluye %publico/consenso (requiere feed pagado)",
    }


if __name__=="__main__":
    import json
    est=construir_estado("beisbol")
    eq=est["eq"]; nombres=list(eq.keys())
    if len(nombres)>=2:
        # tomar dos equipos con historial
        conh=[n for n in nombres if eq[n].n>=20][:2]
        p=panel(est,conh[0],conh[1])
        print(json.dumps(p,ensure_ascii=False,indent=2))
