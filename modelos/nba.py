# -*- coding: utf-8 -*-
"""
modelos/nba.py - NBA con la firma comun y ENSAMBLE de dos vistas (ELO + anotacion).

Igual que beisbol/americano: el ganador combina la vista ELO y la vista de anotacion
reciente; validar() compara y halla el mejor peso EN TU DATA. Mercados: ganador,
spread, total. Solo stdlib.
"""
import os, math, sys

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

BASE_ELO=1500.0; K=20.0; HFA=100.0; REGR=0.75; ESCALA=400.0
ELO_POR_PUNTO=28.0; SD_MARGEN=11.5; SHRINK=8; HFA_PTS=2.7
SD_TOT=19.0   # respaldo si no hay muestra; entrenar() la aprende de los residuos
W_ENS=0.8      # validar() con datos reales: mejor w=0.8 (NBA, 2026-09-29)


def _f(x):
    try:
        v=float(x); return None if v!=v else v
    except (TypeError,ValueError): return None
def _sig(z): return 0.0 if z<-35 else (1.0 if z>35 else 1/(1+math.exp(-z)))
def _cdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def _lo(p): p=min(max(p,1e-6),1-1e-6); return math.log(p/(1-p))

def _juegos(liga=None):
    filas=io.cargar_juegos("nba",liga); pj={}
    for r in filas:
        gp=str(r.get("gamePk") or r.get("game_id") or ""); pj.setdefault(gp,[]).append(r)
    js=[]
    for gp,par in pj.items():
        if len(par)!=2: continue
        h=next((x for x in par if str(x.get("is_home")) in ("1","1.0","True")),None)
        a=next((x for x in par if x is not h),None)
        if not h or not a: continue
        fecha=(h.get("game_date") or "")[:10]
        if fecha: js.append((fecha,gp,h,a))
    js.sort(key=lambda t:(t[0],t[1])); return js

class Eq:
    __slots__=("elo","pf","pa","n","ult")
    def __init__(s): s.elo=BASE_ELO; s.pf=0.0; s.pa=0.0; s.n=0; s.ult=None
    def of(s,lg): return (s.pf+SHRINK*lg)/(s.n+SHRINK) if s.n else lg
    def df(s,lg): return (s.pa+SHRINK*lg)/(s.n+SHRINK) if s.n else lg

def _vistas(th,ta,lg):
    m_elo=(th.elo+HFA-ta.elo)/ELO_POR_PUNTO
    m_sc=((th.of(lg)+ta.df(lg))-(ta.of(lg)+th.df(lg)))+HFA_PTS   # local anota of+df_rival-lg ; visita of+df_local-lg
    return m_elo, m_sc, _cdf(m_elo/SD_MARGEN), _cdf(m_sc/SD_MARGEN)

def _platt(pairs, iters=600, lr=0.05):
    if len(pairs)<120: return 1.0,0.0
    X=[_lo(p) for p,_ in pairs]; Y=[y for _,y in pairs]; n=len(X); a,b=1.0,0.0
    for _ in range(iters):
        ga=gb=0.0
        for x,y in zip(X,Y):
            e=_sig(a*x+b)-y; ga+=e*x; gb+=e
        a-=lr*ga/n; b-=lr*gb/n
    return a,b

VENT_TOT = int(os.environ.get("EDGELINE_NBA_VENT_TOT", "500"))   # juegos recientes para el sesgo del total


def entrenar(liga=None, min_j=5, w=W_ENS):
    js=_juegos(liga); eq={}; tot=0.0; ng=0; lg=113.0; cal=[]; rm=[]; rt=[]
    for f,gp,h,a in js:
        ph=_f(h.get("points")) or _f(h.get("runs")); pa_=_f(h.get("points_opp")) or _f(h.get("runs_opp"))
        if ph is None or pa_ is None: continue
        th=eq.setdefault(h.get("team"),Eq()); ta=eq.setdefault(a.get("team"),Eq())
        for t in (th,ta):
            if t.ult and t.ult!=f[:4]: t.elo=BASE_ELO+(t.elo-BASE_ELO)*REGR
            t.ult=f[:4]
        if th.n>=min_j and ta.n>=min_j:
            m_elo_,m_sc_,pe,psc=_vistas(th,ta,lg)
            cal.append((pe,psc,1 if ph>pa_ else 0))
            rm.append((ph-pa_)-(w*m_elo_+(1-w)*m_sc_))
            rt.append((ph+pa_)-(th.of(lg)+ta.of(lg)+th.df(lg)+ta.df(lg))/2)
        esp=_sig((th.elo+HFA-ta.elo)/(ESCALA/math.log(10)))
        res=1.0 if ph>pa_ else 0.0
        d=K*math.log(abs(ph-pa_)+1)*(res-esp); th.elo+=d; ta.elo-=d
        th.pf+=ph; th.pa+=pa_; th.n+=1; ta.pf+=pa_; ta.pa+=ph; ta.n+=1
        tot+=ph+pa_; ng+=2; lg=tot/ng
    platt=_platt([(w*pe+(1-w)*psc,y) for pe,psc,y in cal])
    def _ms(v,sd0):
        if len(v)<150: return 0.0, sd0
        m=sum(v)/len(v); return m, math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))
    sesgo_m,sd_m=_ms(rm,SD_MARGEN); sesgo_t,sd_t=_ms(rt[-VENT_TOT:],SD_TOT)   # sesgo del total: solo lo reciente (la anotacion sube cada temporada)
    return {"eq":eq,"lg":lg,"platt":platt,"cal":cal,"w":w,
            "sesgo_m":sesgo_m,"sd_m":sd_m,"sesgo_t":sesgo_t,"sd_t":sd_t}

def predecir(estado, home, away, linea_total=None, linea_spread=None, w=None):
    eq,lg=estado["eq"],estado["lg"]; th,ta=eq.get(home),eq.get(away)
    if not th or not ta: return None
    w=estado.get("w",W_ENS) if w is None else w
    m_elo,m_sc,pe,psc=_vistas(th,ta,lg)
    margen=w*m_elo+(1-w)*m_sc+estado.get("sesgo_m",0.0)      # corregido por el sesgo local aprendido
    total=(th.of(lg)+ta.of(lg)+th.df(lg)+ta.df(lg))/2+estado.get("sesgo_t",0.0)
    sd_m=estado.get("sd_m",SD_MARGEN); sd_t=estado.get("sd_t",SD_TOT)
    xh=(total+margen)/2; xa=(total-margen)/2
    a,b=estado["platt"]
    p=_sig(a*_lo(w*pe+(1-w)*psc)+b)
    out={"p_home":round(p,4),"p_away":round(1-p,4),"margen_esperado":round(margen,1),
         "pts_home":round(xh,1),"pts_away":round(xa,1),"total_esperado":round(total,1),
         "confianza":"alta" if abs(p-.5)>.15 else "media" if abs(p-.5)>.07 else "baja"}
    if linea_spread is not None:
        out["p_cubre_home"]=round(1-_cdf((linea_spread-margen)/sd_m),4); out["linea_spread"]=linea_spread
    if linea_total is not None:
        out["p_over"]=round(1-_cdf((linea_total-total)/sd_t),4); out["linea_total"]=linea_total
    return out

def validar(liga=None):
    est=entrenar(liga); cal=est.get("cal") or []
    if len(cal)<150: print("Muestra insuficiente (%d)."%len(cal)); return
    acc=lambda P:sum(1 for p,y in P if (p>=.5)==(y==1))/len(P)
    br=lambda P:sum((p-y)**2 for p,y in P)/len(P)
    elo=[(pe,y) for pe,_,y in cal]; sco=[(ps,y) for _,ps,y in cal]
    mejor=min((i/10 for i in range(11)), key=lambda w:br([(w*pe+(1-w)*ps,y) for pe,ps,y in cal]))
    ens=[(mejor*pe+(1-mejor)*ps,y) for pe,ps,y in cal]
    print("BACKTEST NBA (as-of, n=%d)"%len(cal)); print("-"*56)
    print("%-16s %8s %8s"%("VISTA","ACC","BRIER"))
    print("ELO              %8.3f %8.3f"%(acc(elo),br(elo)))
    print("Anotacion        %8.3f %8.3f"%(acc(sco),br(sco)))
    print("Ensamble w=%.1f   %8.3f %8.3f"%(mejor,acc(ens),br(ens)))
    print("-"*56)
    print("Techo NBA ~0.66-0.70. Mejor peso ELO: w=%.1f."%mejor)
    return mejor


if __name__=="__main__":
    est={"eq":{},"lg":113.0,"platt":(1.0,0.0),"w":0.5}
    class E:
        def __init__(s,elo,of,df,n=10): s.elo=elo; s.o=of; s.d=df; s.n=n; s.ult="2026"
        def of(s,lg): return s.o
        def df(s,lg): return s.d
    est["eq"]={"Celtics":E(1650,120,110),"Wizards":E(1400,110,120)}
    print("Celtics (local) vs Wizards:")
    for k,v in predecir(est,"Celtics","Wizards",linea_total=228.5,linea_spread=9.5).items():
        print("  %-18s %s"%(k,v))
