# -*- coding: utf-8 -*-
"""
modelos/hockey.py - modelo de hockey (NHL) con la firma comun.

Lee datos/hockey.csv (una fila por equipo-juego: goles a favor/en contra + opcional
stats de portero). Todo as-of. Predice:
  - GANADOR (regulacion + OT),
  - TOTAL de goles (over/under),
  - PUCK LINE (-1.5 / +1.5),
  - ajuste por PORTERO titular cuando hay save% disponible,
  - ajuste por DESCANSO (back-to-back): el factor se estima as-of de los propios datos
    (goles reales / goles esperados de los equipos que jugaron el dia anterior).

Metodo: ELO por goles + tasas ofensiva/defensiva as-of -> goles esperados (Log5) ->
dos Poisson -> todos los mercados. Calibracion Platt sobre las predicciones as-of.
Desde el 5-oct-2026 las tasas mezclan goles reales (25 %) con xG de MoneyPuck por partido (75 %,
datos/equipos/nhl_xg_partidos.csv) y olvidan 3 % por juego. Walk-forward 24 meses: ganador +1.4 % -> +2.3 %
(publicable, z ~4); mejora en ventanas de 12, 18, 24 y 30 meses. Totales: el total se encoge a la mitad hacia
el promedio de la liga (MAE 1.867 -> 1.862); sigue sin superar al promedio con datos de equipo.

Solo stdlib.
"""
import math, sys, os, datetime as _dt

try:
    from nucleo import io
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import io

BASE_ELO = 1500.0; K = 6.0; HFA = 35.0; REGR = 0.75; ESCALA = 400.0
VENT_LOCAL = 0.04; SHRINK = 12; OT_LOCAL = 0.55   # ventaja local en OT
XG_W = float(os.environ.get("EDGELINE_NHL_XG_W", "0.75"))     # peso del xG (MoneyPuck) frente a goles reales (validado 5-oct-2026)
DECAY = float(os.environ.get("EDGELINE_NHL_DECAY", "0.97"))  # olvido por juego de cada equipo (1.0 = sin olvido; validado 5-oct-2026)
LG_DECAY = float(os.environ.get("EDGELINE_NHL_LG_DECAY", "1.0"))  # olvido por juego del promedio de goles de la liga
TOT_K = float(os.environ.get("EDGELINE_NHL_TOT_K", "0.5"))     # cuanto del desvio del total esperado contra la liga se conserva
GSAX_BETA = float(os.environ.get("EDGELINE_NHL_GSAX_BETA", "0.25"))  # goles del rival por gol salvado sobre lo esperado (medido 5-oct-2026)
GSAX_K, GSAX_N = 40, 40                            # encogimiento (aperturas) y ultimas N aperturas del portero
B2B_MIN = 100                                      # juegos back-to-back minimos antes de usar el factor estimado


def _dia(f):
    try: return _dt.date.fromisoformat(str(f)[:10])
    except (TypeError, ValueError): return None


def _es_b2b(fecha_ult, fecha):
    """True si el equipo jugo el dia anterior."""
    a, b = _dia(fecha_ult), _dia(fecha)
    return bool(a and b and (b - a).days == 1)


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
    __slots__=("elo","gf","ga","n","sv","s0","ult","fecha_ult","xf","xa","nx")
    def __init__(s): s.elo=BASE_ELO; s.gf=0.0; s.ga=0.0; s.n=0; s.sv=0.0; s.s0=0; s.ult=None; s.fecha_ult=None; s.xf=0.0; s.xa=0.0; s.nx=0.0
    def _mezcla(s, g, x, lg):
        rg=(g+SHRINK*lg)/(s.n+SHRINK) if s.n else lg
        if XG_W<=0 or s.nx<=0: return rg
        rx=(x+SHRINK*lg)/(s.nx+SHRINK)
        return (1-XG_W)*rg+XG_W*rx
    def of(s,lg): return s._mezcla(s.gf, s.xf, lg)
    def df(s,lg): return s._mezcla(s.ga, s.xa, lg)
    def sumar(s, gf, ga, xgf=None, xga=None):
        if DECAY<1.0:
            s.gf*=DECAY; s.ga*=DECAY; s.n*=DECAY; s.xf*=DECAY; s.xa*=DECAY; s.nx*=DECAY
        s.gf+=gf; s.ga+=ga; s.n+=1
        if xgf is not None and xga is not None:
            s.xf+=xgf; s.xa+=xga; s.nx+=1


_XG = None
def _xg_partidos():
    """{(gamePk, team): (xGF, xGA)} de datos/equipos/nhl_xg_partidos.csv (situacion 'all'). Vacio si no existe."""
    global _XG
    if _XG is None:
        _XG = {}
        ruta = os.path.join(io.BASE, "datos", "equipos", "nhl_xg_partidos.csv")
        if os.path.exists(ruta):
            import csv
            with open(ruta, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    if r.get("situation") == "all":
                        a, b = _f(r.get("xgf")), _f(r.get("xga"))
                        if a is not None and b is not None:
                            _XG[(str(r.get("game_id")), r.get("team"))] = (a, b)
    return _XG

_GSAX = None
def _gsax_hist():
    """{(inicial, apellido): [(fecha, gsax)]} del abridor de cada partido: xG en contra del equipo (MoneyPuck 'all')
    menos goles recibidos (sin el gol de shootout). Medido en utilidades/medir_porteros_nhl.py."""
    global _GSAX
    if _GSAX is None:
        _GSAX = {}
        X = _xg_partidos()
        ruta = os.path.join(io.BASE, "datos", "hockey.csv")
        if X and os.path.exists(ruta):
            import csv
            with open(ruta, encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    g = (r.get("starter_goalie") or "").strip(); x = X.get((str(r.get("gamePk") or "").split(".")[0], r.get("team")))
                    ga = _f(r.get("goals_opp"))
                    if not g or not x or ga is None:
                        continue
                    if (r.get("ended_in") or "") == "SO" and ga > (_f(r.get("goals")) or 0):
                        ga -= 1
                    _GSAX.setdefault(_llave_portero(g), []).append(((r.get("game_date") or "")[:10], x[1] - ga))
            for v in _GSAX.values():
                v.sort()
    return _GSAX


def _llave_portero(nombre):
    import unicodedata
    n = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower().replace(".", " ").split()
    return (n[0][:1], n[-1]) if n else ("", "")


def rating_portero(nombre, fecha=None):
    """GSAx por juego del portero, as-of (aperturas antes de 'fecha'), encogido hacia 0. (rating, aperturas) o (None, 0)."""
    v = [g for f, g in (_gsax_hist().get(_llave_portero(nombre)) or []) if not fecha or f < str(fecha)[:10]][-GSAX_N:]
    if not v:
        return None, 0
    return sum(v) / (len(v) + GSAX_K), len(v)


class _B2B:
    """Acumula goles reales y esperados de los equipos en back-to-back para estimar el factor as-of."""
    __slots__=("gf","xgf","ga","xga","n")
    def __init__(s): s.gf=s.xgf=s.ga=s.xga=0.0; s.n=0
    def factores(s):
        if s.n < B2B_MIN or s.xgf <= 0 or s.xga <= 0: return 1.0, 1.0
        return s.gf/s.xgf, s.ga/s.xga     # (ofensiva del cansado, defensa del cansado)


def _xg_base(th, ta, lg):
    return max(th.of(lg)*ta.df(lg)/lg*(1+VENT_LOCAL), .3), max(ta.of(lg)*th.df(lg)/lg*(1-VENT_LOCAL), .3)


def _aplicar_b2b(xh, xa, b2b_home, b2b_away, fac):
    f_of, f_df = fac
    if b2b_home: xh *= f_of; xa *= f_df
    if b2b_away: xa *= f_of; xh *= f_df
    return max(xh,.3), max(xa,.3)


def entrenar(liga=None, min_j=8):
    juegos=_juegos(liga)
    eq={}; tot=0.0; ng=0; lg=3.0; cal=[]; b2b=_B2B()
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
        bh, ba = _es_b2b(th.fecha_ult, f), _es_b2b(ta.fecha_ult, f)
        # prediccion as-of (con el factor de descanso estimado hasta ayer)
        if th.n>=min_j*(1 if DECAY>=1 else 0.5) and ta.n>=min_j*(1 if DECAY>=1 else 0.5):
            xh0, xa0 = _xg_base(th, ta, lg)
            xh1, xa1 = _aplicar_b2b(xh0, xa0, bh, ba, b2b.factores())
            cal.append((_prob_home(xh1, xa1), 1 if gh>ga_ else 0))
            if bh: b2b.gf+=gh; b2b.xgf+=xh0; b2b.ga+=ga_; b2b.xga+=xa0; b2b.n+=1
            if ba: b2b.gf+=ga_; b2b.xgf+=xa0; b2b.ga+=gh; b2b.xga+=xh0; b2b.n+=1
        # ELO update
        esp=_sig((th.elo+HFA-ta.elo)/(ESCALA/math.log(10)))
        res=1.0 if gh>ga_ else 0.0
        mov=math.log(abs(gh-ga_)+1)
        d=K*mov*(res-esp); th.elo+=d; ta.elo-=d
        X=_xg_partidos(); xh_=X.get((str(gp), h.get("team"))); xa_=X.get((str(gp), a.get("team")))
        th.sumar(gh, ga_, *(xh_ or (None, None))); ta.sumar(ga_, gh, *(xa_ or (None, None)))
        th.fecha_ult=f; ta.fecha_ult=f
        tot=tot*LG_DECAY+gh+ga_; ng=ng*LG_DECAY+2; lg=tot/ng
    a,b=_platt(cal)
    f_of, f_df = b2b.factores()
    return {"eq":eq,"lg":lg,"platt":(a,b),"cal":cal,
            "b2b":{"n":b2b.n,"factor_of":round(f_of,4),"factor_df":round(f_df,4)}}

def _xg(estado, home, away, sv_home=None, sv_away=None, fecha=None, jugo_ayer=(False, False), gsax_home=None, gsax_away=None):
    eq,lg=estado["eq"],estado["lg"]
    th,ta=eq.get(home),eq.get(away)
    if not th or not ta: return None,None
    xh=th.of(lg)*ta.df(lg)/lg*(1+VENT_LOCAL)
    xa=ta.of(lg)*th.df(lg)/lg*(1-VENT_LOCAL)
    # descanso: factor estimado de los datos (goles reales / esperados de equipos en back-to-back)
    if fecha:
        b=estado.get("b2b") or {}
        fac=(b.get("factor_of",1.0), b.get("factor_df",1.0))
        xh,xa=_aplicar_b2b(xh, xa, _es_b2b(getattr(th,"fecha_ult",None), fecha) or bool(jugo_ayer[0]),
                          _es_b2b(getattr(ta,"fecha_ult",None), fecha) or bool(jugo_ayer[1]), fac)
    # ajuste por portero: save% del titular vs liga (~.905). Mejor portero -> menos goles en contra.
    if sv_away is not None: xh *= (1-(sv_away-0.905))/(1)   # portero visitante frena al local
    if sv_home is not None: xa *= (1-(sv_home-0.905))/(1)
    # calidad del portero titular (GSAx as-of): mejora el total esperado (z 3.0, las dos mitades) sin empeorar el ganador
    if gsax_away is not None: xh -= GSAX_BETA*gsax_away
    if gsax_home is not None: xa -= GSAX_BETA*gsax_home
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
def predecir(estado, home, away, linea_total=6.5, sv_home=None, sv_away=None, fecha=None, jugo_ayer=(False, False), gsax_home=None, gsax_away=None):
    """jugo_ayer: (local, visita) segun el calendario de ESPN; marca back-to-back aunque el juego de ayer aun no este en el historial."""
    xh,xa=_xg(estado,home,away,sv_home,sv_away,fecha,jugo_ayer,gsax_home,gsax_away)
    if xh is None: return None
    th,ta=estado["eq"].get(home),estado["eq"].get(away)
    b2b_h=(_es_b2b(getattr(th,"fecha_ult",None), fecha) or bool(jugo_ayer[0])) if fecha else False
    b2b_a=(_es_b2b(getattr(ta,"fecha_ult",None), fecha) or bool(jugo_ayer[1])) if fecha else False
    a,b=estado["platt"]
    lo=lambda p:math.log(min(max(p,1e-6),1-1e-6)/(1-min(max(p,1e-6),1-1e-6)))
    p=_sig(a*lo(_prob_home(xh,xa))+b)
    mu=xh+xa
    lg2=2*estado["lg"]; mu=lg2+TOT_K*(mu-lg2)
    piso=int(math.floor(linea_total))
    p_over=1-sum(_pois(mu,k) for k in range(piso+1))
    # puck line -1.5: P(home - away >= 2) en regulacion (aprox)
    kmax=12; ph=[_pois(xh,k) for k in range(kmax)]; pa=[_pois(xa,k) for k in range(kmax)]
    p_pl_home=sum(ph[i]*pa[j] for i in range(kmax) for j in range(kmax) if i-j>=2)
    conf="alta" if abs(p-.5)>.15 else "media" if abs(p-.5)>.07 else "baja"
    return {"p_home":round(p,4),"p_away":round(1-p,4),
            "xg_home":round(xh,2),"xg_away":round(xa,2),"total":round(mu,2),
            "p_over":round(p_over,4),"linea_total":linea_total,
            "p_pl_home":round(p_pl_home,4),"p_pl_away":round(1-p_pl_home,4),
            "confianza":conf,
            "descanso":{"home_b2b":b2b_h,"away_b2b":b2b_a,
                        "factor_of":(estado.get("b2b") or {}).get("factor_of",1.0),
                        "factor_df":(estado.get("b2b") or {}).get("factor_df",1.0)}}

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
    b=est.get("b2b") or {}
    print("descanso: %d juegos back-to-back | factor ofensiva x%.3f | factor defensa x%.3f"%(b.get("n",0),b.get("factor_of",1),b.get("factor_df",1)))
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
