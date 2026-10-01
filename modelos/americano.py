# -*- coding: utf-8 -*-
"""
modelos/americano.py - NFL con la firma comun y ENSAMBLE de dos vistas.

Igual que en beisbol, el ganador combina dos vistas as-of:
  - VISTA ELO: prob del margen esperado por la diferencia de ELO.
  - VISTA ANOTACION: prob del margen esperado por las tasas de puntos recientes.
El ensamble (peso w) suele ser mas preciso; validar() compara las dos y encuentra el
mejor w EN TU DATA antes de adoptarlo.

Mercados: ganador, spread, total. Solo stdlib.
"""
import math, sys, os

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

BASE_ELO=1500.0; K=20.0; HFA=48.0; REGR=0.75; ESCALA=400.0
ELO_POR_PUNTO=25.0; SD_MARGEN=13.5; SHRINK=6; HFA_PTS=1.9
SD_TOT=13.0   # respaldo si no hay muestra; entrenar() la aprende de los residuos
VENT_TOT=300  # juegos recientes para corregir el sesgo del total
W_ENS=1.0      # peso de la vista ELO; validar() con datos reales: mejor w=1.0 (NFL, 2026-09-29)


def _f(x):
    try:
        v=float(x); return None if v!=v else v
    except (TypeError,ValueError): return None
def _sig(z): return 0.0 if z<-35 else (1.0 if z>35 else 1/(1+math.exp(-z)))
def _cdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def _lo(p): p=min(max(p,1e-6),1-1e-6); return math.log(p/(1-p))

def _juegos(liga=None):
    filas=io.cargar_juegos("americano",liga); pj={}
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
    """margenes esperados por ELO y por anotacion, y sus prob de local."""
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

def entrenar(liga=None, min_j=4, w=W_ENS):
    js=_juegos(liga); eq={}; tot=0.0; ng=0; lg=22.0; cal=[]; rm=[]; rt=[]
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
        res=1.0 if ph>pa_ else (0.0 if ph<pa_ else .5)
        d=K*math.log(abs(ph-pa_)+1)*(res-esp); th.elo+=d; ta.elo-=d
        th.pf+=ph; th.pa+=pa_; th.n+=1; ta.pf+=pa_; ta.pa+=ph; ta.n+=1
        tot+=ph+pa_; ng+=2; lg=tot/ng
    platt=_platt([(w*pe+(1-w)*psc,y) for pe,psc,y in cal])
    def _ms(v,sd0):
        if len(v)<150: return 0.0, sd0
        m=sum(v)/len(v); return m, math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))
    sesgo_m,sd_m=_ms(rm,SD_MARGEN); sesgo_t,sd_t=_ms(rt[-VENT_TOT:],SD_TOT)   # sesgo del total: solo lo reciente (el nivel de anotacion cambia entre temporadas)
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
    """Compara VISTA ELO vs VISTA ANOTACION vs ENSAMBLE y halla el mejor peso w."""
    est=entrenar(liga); cal=est.get("cal") or []
    if len(cal)<150: print("Muestra insuficiente (%d)."%len(cal)); return
    acc=lambda P:sum(1 for p,y in P if (p>=.5)==(y==1))/len(P)
    br=lambda P:sum((p-y)**2 for p,y in P)/len(P)
    elo=[(pe,y) for pe,_,y in cal]; sco=[(ps,y) for _,ps,y in cal]
    mejor=min((i/10 for i in range(11)), key=lambda w:br([(w*pe+(1-w)*ps,y) for pe,ps,y in cal]))
    ens=[(mejor*pe+(1-mejor)*ps,y) for pe,ps,y in cal]
    print("BACKTEST AMERICANO (as-of, n=%d)"%len(cal)); print("-"*56)
    print("%-16s %8s %8s"%("VISTA","ACC","BRIER"))
    print("ELO              %8.3f %8.3f"%(acc(elo),br(elo)))
    print("Anotacion        %8.3f %8.3f"%(acc(sco),br(sco)))
    print("Ensamble w=%.1f   %8.3f %8.3f"%(mejor,acc(ens),br(ens)))
    print("-"*56)
    print("Mejor peso ELO: w=%.1f. Ponlo en el modelo con entrenar(w=%.1f)."%(mejor,mejor))
    return mejor


if __name__=="__main__":
    est={"eq":{},"lg":22.0,"platt":(1.0,0.0),"w":0.5}
    class E:
        def __init__(s,elo,of,df,n=8): s.elo=elo; s.o=of; s.d=df; s.n=n; s.ult="2026"
        def of(s,lg): return s.o
        def df(s,lg): return s.d
    est["eq"]={"Chiefs":E(1650,27,20),"Raiders":E(1470,20,25)}
    print("Chiefs (local) vs Raiders:")
    for k,v in predecir(est,"Chiefs","Raiders",linea_total=45.5,linea_spread=6.5).items():
        print("  %-18s %s"%(k,v))
