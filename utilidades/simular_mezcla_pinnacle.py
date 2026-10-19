# -*- coding: utf-8 -*-
"""utilidades/simular_mezcla_pinnacle.py - 18-oct-2026. Rehace la seleccion de apuestas sobre las lecturas calificadas
(salida/clv_detalle.csv lista modelo + historial_predicciones_calificado.csv): p del modelo, mezcla con Pinnacle
(w 0.1-0.5) o solo Pinnacle; EV >= 2 %, cuota >= 1.70, 1 u. Tambien compara log loss modelo vs Pinnacle por liga.
Resultados: trabajo/minar/2026-10-18_mezcla_pinnacle.md. Solo stdlib."""
import csv,math,collections
import os
B=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'salida')+os.sep
pred={}
for x in csv.DictReader(open(B+'historial_predicciones_calificado.csv',encoding='utf-8-sig')):
    if x['estado']!='calificado' or x['acierto'] in ('',None): continue
    pred[(x['liga'],x['fecha'],x['home'],x['away'],x['mercado'],x['lado'])]=x
rows=[];miss=0
for c in csv.DictReader(open(B+'clv_detalle.csv',encoding='utf-8-sig')):
    if c['lista']!='modelo' or not c['p_modelo'] or not c['p_registro']: continue
    k=(c['liga'],c['fecha'],c['home'],c['away'],c['mercado'],c['lado']); p=pred.get(k)
    if not p: miss+=1; continue
    try: cu=float(p['cuota'])
    except: continue
    d=1+cu/100 if cu>0 else 1+100/abs(cu)
    rows.append(dict(liga=c['liga'],fecha=c['fecha'],tipo=c['mercado'].split()[0],pm=float(c['p_modelo']),pp=float(c['p_registro']),d=d,y=int(float(p['acierto']))))
print('candidatos',len(rows),'sin cruce',miss, collections.Counter(r['tipo'] for r in rows))
lo=lambda p:math.log(min(max(p,1e-6),1-1e-6)/(1-min(max(p,1e-6),1-1e-6))); sg=lambda z:1/(1+math.exp(-z))
ll=lambda p,y:-math.log(min(max(p if y else 1-p,1e-6),1))
def z(d):
    n=len(d);m=sum(d)/n;s=math.sqrt(sum((q-m)**2 for q in d)/(n-1));return m/s*math.sqrt(n)
# 1) quien predice mejor
for t in ('Ganador','Total','Spread',None):
    v=[r for r in rows if t is None or r['tipo']==t]
    if len(v)<30: continue
    d=[ll(r['pm'],r['y'])-ll(r['pp'],r['y']) for r in v]
    print(f"{t or 'todo'} n {len(v)}: logloss modelo {sum(ll(r['pm'],r['y']) for r in v)/len(v):.4f} pinnacle {sum(ll(r['pp'],r['y']) for r in v)/len(v):.4f} | pinnacle mejor por {1000*sum(d)/len(d):.1f} mil z {z(d):.2f}")
    for w in (0,.1,.25,.35,.5,1):
        L=sum(ll(sg((1-w)*lo(r['pp'])+w*lo(r['pm'])),r['y']) for r in v)/len(v); print(f"   w {w}: {L:.4f}")
# 2) simulacion de apuestas
def sim(name,pf,ev_min=.02,dmin=1.70,tipos=('Ganador','Total')):
    b=[r for r in rows if r['tipo'] in tipos and r['d']>=dmin and pf(r)*r['d']-1>=ev_min]
    if not b: print(name,'0 apuestas'); return
    u=sum((r['d']-1) if r['y'] else -1 for r in b); w=sum(r['y'] for r in b); imp=sum(1/r['d'] for r in b)
    exp_p=sum(pf(r) for r in b); pin=sum(r['pp'] for r in b)
    print(f"{name}: apuestas {len(b)} ganadas {w} ({100*w/len(b):.1f}%) u {u:+.2f} ROI {100*u/len(b):+.1f}% | esperaba {exp_p:.1f}, Pinnacle {pin:.1f}, cuota implicita {imp:.1f} | cuota media {sum(r['d'] for r in b)/len(b):.2f}")
    return b
print()
sim('A modelo (como hoy)',lambda r:r['pm'])
for w in (.5,.35,.25,.1):
    sim(f'B mezcla w={w}',lambda r,w=w:sg((1-w)*lo(r['pp'])+w*lo(r['pm'])))
sim('C solo Pinnacle',lambda r:r['pp'])
print('\n-- EV>=4%')
sim('A modelo',lambda r:r['pm'],.04)
sim('B mezcla w=0.25',lambda r:sg(.75*lo(r['pp'])+.25*lo(r['pm'])),.04)
print('\n-- solo ganador')
sim('A modelo',lambda r:r['pm'],tipos=('Ganador',))
sim('B mezcla w=0.25',lambda r:sg(.75*lo(r['pp'])+.25*lo(r['pm'])),tipos=('Ganador',))
print('-- solo total')
sim('A modelo',lambda r:r['pm'],tipos=('Total',))
sim('B mezcla w=0.25',lambda r:sg(.75*lo(r['pp'])+.25*lo(r['pm'])),tipos=('Total',))
print(min(r['fecha'] for r in rows),max(r['fecha'] for r in rows))
print('\n-- por liga y mercado (modelo menos Pinnacle en log loss; + = modelo mejor)')
g=collections.defaultdict(list)
for r in rows: g[(r['liga'],r['tipo'])].append(r)
for k,v in sorted(g.items(),key=lambda t:-len(t[1])):
    if len(v)<25: continue
    d=[ll(r['pp'],r['y'])-ll(r['pm'],r['y']) for r in v]
    b=[r for r in v if r['tipo']!='Spread' and r['d']>=1.7 and r['pm']*r['d']-1>=.02]
    u=sum((r['d']-1) if r['y'] else -1 for r in b)
    print(f"{k[0]} {k[1]}: n {len(v)} modelo-Pinnacle {1000*sum(d)/len(d):+.1f} mil z {z(d):.2f} | apuestas modelo {len(b)} u {u:+.2f}")
