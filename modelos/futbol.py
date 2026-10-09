# -*- coding: utf-8 -*-
"""
modelos/futbol.py - futbol con ENSAMBLE de dos modelos.

Combina, como en beisbol:
  - MODELO DE MARCADOR (Dixon-Coles / Poisson): 1X2, total, handicap.
  - MODELO ML (ELO): probabilidad de ganador por rating.
El ganador final ensambla ambos (peso w); validar() compara y elige el mejor w
EN TU DATA antes de adoptarlo. Solo stdlib.
"""
import math, sys, os

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

SHRINK=6; RHO=-0.08; HFA_ELO=60.0; K_ELO=40.0; ESCALA=400.0; W_ENS=0.4   # validar() con datos reales: mejor w=0.4 (2026-09-29)
# K_ELO 20 -> 40 y OLVIDO 1.0 -> 0.98 (aprobado por Alejandro el 9-oct-2026): forma mas rapida. Fuera de muestra 1X2 z 1.82;
# validacion oficial 80 -> 89 mercados publicables. trabajo/minar/2026-10-09_forma_rapida.md
OLVIDO=0.98   # peso de cada juego anterior del equipo en las tasas de goles (0.98: el juego de hace 35 pesa la mitad)


def _f(x):
    try:
        v=float(x); return None if v!=v else v
    except (TypeError,ValueError): return None
def _pri(a,b): return a if a is not None else b
def _pois(mu,k): return math.exp(-mu)*mu**k/math.factorial(k)
def _sig(z): return 0.0 if z<-35 else (1.0 if z>35 else 1/(1+math.exp(-z)))

def _juegos(liga=None):
    filas=io.cargar_juegos("futbol",liga); pj={}
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
    __slots__=("gf","ga","n","elo")
    def __init__(s): s.gf=0.0; s.ga=0.0; s.n=0; s.elo=1500.0
    def atk(s,lg): return ((s.gf+SHRINK*lg)/(s.n+SHRINK))/lg if s.n else 1.0
    def dfn(s,lg): return ((s.ga+SHRINK*lg)/(s.n+SHRINK))/lg if s.n else 1.0

def _sumar(t,gf,ga):
    t.gf=OLVIDO*t.gf+gf; t.ga=OLVIDO*t.ga+ga; t.n=OLVIDO*t.n+1

def entrenar(liga=None, w=W_ENS):
    juegos=_juegos(liga); eq={}; sh=sa=0.0; n=0
    for f,gp,h,a in juegos:
        gh=_pri(_f(h.get("goals")),_f(h.get("runs"))); ga_=_pri(_f(h.get("goals_opp")),_f(h.get("runs_opp")))
        if gh is None or ga_ is None: continue
        sh+=gh; sa+=ga_; n+=1
    lg_home=sh/n if n else 1.5; lg_away=sa/n if n else 1.15; lg=(lg_home+lg_away)/2
    cnt={"c":{},"t":{},"c_h":0.0,"c_a":0.0,"nc":0,"t_h":0.0,"t_a":0.0,"nt":0,"ht_g":0.0,"ht_t":0.0}
    for f,gp,h,a in juegos:
        gh=_pri(_f(h.get("goals")),_f(h.get("runs"))); ga_=_pri(_f(h.get("goals_opp")),_f(h.get("runs_opp")))
        if gh is None or ga_ is None: continue
        th=eq.setdefault(h.get("team"),Eq()); ta=eq.setdefault(a.get("team"),Eq())
        exp=_sig((th.elo+HFA_ELO-ta.elo)/(ESCALA/math.log(10)))
        res=1.0 if gh>ga_ else (0.5 if gh==ga_ else 0.0)
        d=K_ELO*(res-exp); th.elo+=d; ta.elo-=d
        _sumar(th,gh,ga_); _sumar(ta,ga_,gh)
        _acum_conteos(cnt,h,a,gh,ga_)
    return {"eq":eq,"lg":lg,"lg_home":lg_home,"lg_away":lg_away,"w":w,"cnt":cnt}

def _acum_conteos(cnt,h,a,gh,ga_):
    """Tasas por equipo de corners, tarjetas y fraccion de goles del 1T (para los mercados derivados)."""
    ch,ca=_f(h.get("corners")),_f(a.get("corners"))
    if ch is not None and ca is not None:
        for tm,fo,co in ((h.get("team"),ch,ca),(a.get("team"),ca,ch)):
            c=cnt["c"].setdefault(tm,[0.0,0.0,0]); c[0]+=fo; c[1]+=co; c[2]+=1
        cnt["c_h"]+=ch; cnt["c_a"]+=ca; cnt["nc"]+=1
    yh,ya=_f(h.get("yellow")),_f(a.get("yellow"))
    if yh is not None and ya is not None:
        th_=yh+(_f(h.get("red")) or 0); ta_=ya+(_f(a.get("red")) or 0)
        for tm,fo,co in ((h.get("team"),th_,ta_),(a.get("team"),ta_,th_)):
            c=cnt["t"].setdefault(tm,[0.0,0.0,0]); c[0]+=fo; c[1]+=co; c[2]+=1
        cnt["t_h"]+=th_; cnt["t_a"]+=ta_; cnt["nt"]+=1
    g1,g2=_f(h.get("goals_ht")),_f(h.get("goals_ht_opp"))
    if g1 is not None and g2 is not None:
        cnt["ht_g"]+=g1+g2; cnt["ht_t"]+=gh+ga_

def _esp_conteo(cnt,k,home,away,S=6):
    """Media esperada (local+visita) de corners ('c') o tarjetas ('t'); None si no hay datos suficientes."""
    nn=cnt["nc" if k=="c" else "nt"]
    if nn<200: return None
    sh=cnt["%s_h"%k]/nn; sa=cnt["%s_a"%k]/nn; lg=(sh+sa)/2
    a=cnt[k].get(home,[0.0,0.0,0]); b=cnt[k].get(away,[0.0,0.0,0])
    def r(v,n): return ((v+S*lg)/(n+S))/lg if n else 1.0
    return sh*r(a[0],a[2])*r(b[1],b[2])+sa*r(b[0],b[2])*r(a[1],a[2])

def _dc(i,j,xh,xa):
    if i==0 and j==0: return 1-xh*xa*RHO
    if i==0 and j==1: return 1+xh*RHO
    if i==1 and j==0: return 1+xa*RHO
    if i==1 and j==1: return 1-RHO
    return 1.0

def _poisson_1x2(estado, th, ta):
    lg=estado["lg"]
    xh=estado["lg_home"]*th.atk(lg)*ta.dfn(lg); xa=estado["lg_away"]*ta.atk(lg)*th.dfn(lg)
    kmax=8; P=[[_pois(xh,i)*_pois(xa,j)*_dc(i,j,xh,xa) for j in range(kmax)] for i in range(kmax)]
    s=sum(sum(r) for r in P); P=[[x/s for x in r] for r in P]
    ph=sum(P[i][j] for i in range(kmax) for j in range(kmax) if i>j)
    pd=sum(P[i][i] for i in range(kmax)); pa=1-ph-pd
    return ph,pd,pa,xh,xa,P

def _ensamble(estado, th, ta, w):
    ph,pd,pa,xh,xa,P=_poisson_1x2(estado,th,ta)
    e=_sig((th.elo+HFA_ELO-ta.elo)/(ESCALA/math.log(10)))     # ELO: P(home mejor)
    # ELO redistribuye la masa decisiva (no-empate) entre local/visita
    dec=1-pd; ph_e=e*dec; pa_e=(1-e)*dec
    H=w*ph_e+(1-w)*ph; A=w*pa_e+(1-w)*pa; D=pd
    s=H+A+D
    return H/s, D/s, A/s, xh, xa, P

def predecir(estado, home, away, linea_total=2.5, handicap=0.0, w=None):
    eq=estado["eq"]; th,ta=eq.get(home),eq.get(away)
    if not th or not ta: return None
    w=estado.get("w",W_ENS) if w is None else w
    ph,pd,pa,xh,xa,P=_ensamble(estado,th,ta,w)
    kmax=len(P); piso=int(math.floor(linea_total))
    p_over=1-sum(P[i][j] for i in range(kmax) for j in range(kmax) if i+j<=piso)
    p_hand=sum(P[i][j] for i in range(kmax) for j in range(kmax) if (i-j)+handicap>0)
    der=None
    try:
        from modelos import futbol_mercados as FM
        der=FM.desde_matriz(P,ph,pd,pa)
        cnt=estado.get("cnt")
        if cnt:
            if cnt["ht_t"]>500: der.update(FM.primer_tiempo(xh,xa,cnt["ht_g"]/cnt["ht_t"]))
            mc=_esp_conteo(cnt,"c",home,away)
            if mc: der.update({"corners_"+k:v for k,v in FM.conteo(mc,[8.5,9.5,10.5,11.5]).items()}); der["corners_esperados"]=mc
            mt=_esp_conteo(cnt,"t",home,away)
            if mt: der.update({"tarjetas_"+k:v for k,v in FM.conteo(mt,[2.5,3.5,4.5,5.5]).items()}); der["tarjetas_esperadas"]=mt
    except Exception:
        der=None
    return {"derivados":der,"p_home":round(ph,4),"p_draw":round(pd,4),"p_away":round(pa,4),
            "xg_home":round(xh,2),"xg_away":round(xa,2),"total_esperado":round(xh+xa,2),
            "p_over":round(p_over,4),"linea_total":linea_total,
            "p_handicap_home":round(p_hand,4),"handicap":handicap,
            "resultado_prob":("Local" if ph>=max(pd,pa) else "Empate" if pd>=pa else "Visita")}

def validar(liga=None, min_j=6):
    """Compara MARCADOR (Poisson) vs ML (ELO) vs ENSAMBLE en el 1X2, as-of, y elige w."""
    juegos=_juegos(liga)
    if not juegos: print("Sin datos/futbol.csv."); return
    eq={}; sh=sa=0.0; ng=0; datos=[]
    for f,gp,h,a in juegos:
        gh=_pri(_f(h.get("goals")),_f(h.get("runs"))); ga_=_pri(_f(h.get("goals_opp")),_f(h.get("runs_opp")))
        if gh is None or ga_ is None: continue
        th=eq.setdefault(h.get("team"),Eq()); ta=eq.setdefault(a.get("team"),Eq())
        lh=sh/ng if ng else 1.5; la=sa/ng if ng else 1.15
        if th.n>=min_j and ta.n>=min_j:
            est={"eq":eq,"lg":(lh+la)/2,"lg_home":lh,"lg_away":la}
            ph,pd,pa,_,_,_=_poisson_1x2(est,th,ta)
            e=_sig((th.elo+HFA_ELO-ta.elo)/(ESCALA/math.log(10)))
            real="H" if gh>ga_ else "A" if ga_>gh else "D"
            datos.append((ph,pd,pa,e,real))
        exp=_sig((th.elo+HFA_ELO-ta.elo)/(ESCALA/math.log(10)))
        res=1.0 if gh>ga_ else (0.5 if gh==ga_ else 0.0)
        d=K_ELO*(res-exp); th.elo+=d; ta.elo-=d
        _sumar(th,gh,ga_); _sumar(ta,ga_,gh)
        sh+=gh; sa+=ga_; ng+=1
    if len(datos)<150: print("Muestra insuficiente (%d)."%len(datos)); return
    def evalw(w):
        acc=0; br=0.0
        for ph,pd,pa,e,real in datos:
            dec=1-pd; H=w*e*dec+(1-w)*ph; A=w*(1-e)*dec+(1-w)*pa; D=pd; s=H+A+D; H/=s; A/=s; D/=s
            pick="H" if H>=max(D,A) else "D" if D>=A else "A"
            acc+=(pick==real); br+=(H-(1 if real=="H" else 0))**2
        return acc/len(datos), br/len(datos)
    a0,b0=evalw(0.0); a1,b1=evalw(1.0)
    mejor=min((i/10 for i in range(11)), key=lambda w:evalw(w)[1])
    am,bm=evalw(mejor)
    print("BACKTEST FUTBOL 1X2 (as-of, n=%d)"%len(datos)); print("-"*52)
    print("%-16s %10s %8s"%("MODELO","ACC 1X2","BRIER"))
    print("Marcador (w=0)   %10.3f %8.3f"%(a0,b0))
    print("ELO (w=1)        %10.3f %8.3f"%(a1,b1))
    print("Ensamble w=%.1f   %10.3f %8.3f"%(mejor,am,bm))
    print("-"*52); print("1X2 ~0.50-0.54 es bueno (el empate es dificil). Mejor w=%.1f."%mejor)
    return mejor


if __name__=="__main__":
    est={"lg":1.35,"lg_home":1.55,"lg_away":1.15,"w":0.5,"eq":{}}
    class E:
        def __init__(s,a,d,elo,n=20): s.a=a; s.d=d; s.n=n; s.elo=elo
        def atk(s,lg): return s.a
        def dfn(s,lg): return s.d
    est["eq"]={"City":E(1.5,0.7,1750),"Luton":E(0.8,1.3,1400)}
    print("Man City (local) vs Luton:")
    for k,v in predecir(est,"City","Luton",2.5,-1.0).items(): print("  %-18s %s"%(k,v))
