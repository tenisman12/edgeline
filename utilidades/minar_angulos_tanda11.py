# -*- coding: utf-8 -*-
"""utilidades/minar_angulos_tanda11.py - tanda 11 (13-oct-2026) en todos los deportes: secuencia (S11 perdio el ultimo, S12 racha en dosis, S13 perdio cerrado) y senal del
modelo (S15 persecucion, S16 deriva del modelo con el equipo). Misma estimacion que la tanda 4: toda la muestra con
offset logit(p) recalibrado, beta por unidad de x, encogido por Bayes empirico con tau 0.0924; ademas el veredicto 70/30."""
import os, sys, math, json
CODIGO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODIGO); sys.path.insert(0, os.path.join(CODIGO, 'utilidades'))
import minar_situacionales as M
SALIDA = os.path.join(CODIGO, 'trabajo', 'minar', '2026-10-13_tanda11_resultados.json')
TAU = 0.0924
lg, sg = M._lg, M._sig
CERRADO = {'BEISBOL': 1, 'NHL': 1, 'NBA': 3, 'NCAAMB': 3, 'NFL': 3, 'NCAAFB': 3, 'FUTBOL': 1}
SIGNO = {'S11': +1, 'S12': -1, 'S13': +1, 'S15': -1, 'S16': +1}
NOMBRE = {'S11': 'perdio su ultimo juego', 'S12': 'racha en dosis (mas caliente)', 'S13': 'perdio cerrado el ultimo',
          'S15': 'persecucion: el modelo lo eligio, perdio y lo vuelve a elegir', 'S16': 'supera al modelo en sus ultimos 10'}


def estados(dep, filas, T):
    PG = {str(r['gp']): r for r in filas}
    def p_eq(gp, e):
        r = PG.get(str(gp))
        if not r: return None
        return r['p'] if r['home'] == e else 1 - r['p']
    E = {}
    for e, L in T.items():
        for i, g in enumerate(L):
            prev = []; j = i - 1
            while j >= 0 and (L[j + 1]['fecha'] - L[j]['fecha']).days <= 60:
                if L[j]['gf'] is not None: prev.append(L[j])
                j -= 1
            if not prev: continue
            res = [1 if h['gf'] > h['ga'] else (0 if h['gf'] < h['ga'] else None) for h in prev]
            k = 0
            for v in res:
                if v is not None and v == res[0]: k += 1
                else: break
            racha = 0 if res[0] is None else (k if res[0] == 1 else -k)
            mg = prev[0]['gf'] - prev[0]['ga']
            pe0 = p_eq(prev[0]['gp'], e)
            rr = [((1 if h['gf'] > h['ga'] else 0) - p_eq(h['gp'], e)) for h in prev[:10]
                  if p_eq(h['gp'], e) is not None and h['gf'] != h['ga']]
            E[(e, str(g['gp']))] = dict(perdio=int(mg < 0), racha=racha, cerrado=int(-CERRADO[dep] <= mg < 0),
                                        pick_perdio=None if pe0 is None else int(pe0 > 0.5 and mg < 0),
                                        res10=sum(rr) / len(rr) if len(rr) >= 6 else None)
    return E


def angulos(r, E):
    sh, sa = E.get((r['home'], str(r['gp']))), E.get((r['away'], str(r['gp'])))
    if not sh or not sa: return {}
    x = {'S11': sh['perdio'] - sa['perdio'],
         'S12': (max(-5, min(5, sh['racha'])) - max(-5, min(5, sa['racha']))) / 5.0,
         'S13': sh['cerrado'] - sa['cerrado']}
    if sh['pick_perdio'] is not None and sa['pick_perdio'] is not None:
        hoy_h = r['p'] > 0.5
        x['S15'] = int(hoy_h and sh['pick_perdio'] == 1) - int((not hoy_h) and sa['pick_perdio'] == 1)
    if sh['res10'] is not None and sa['res10'] is not None:
        x['S16'] = round(sh['res10'] - sa['res10'], 4)
    return x


def logit_fit(X, Y, iters=40):
    """logistica con Newton; devuelve w y errores estandar."""
    k = len(X[0]); w = [0.0] * k
    for _ in range(iters):
        g = [0.0] * k; H = [[0.0] * k for _ in range(k)]
        for xi, yi in zip(X, Y):
            z = sum(a * b for a, b in zip(w, xi)); q = 1 / (1 + math.exp(-max(-30, min(30, z))))
            for a in range(k):
                g[a] += (yi - q) * xi[a]
                for b in range(k): H[a][b] += q * (1 - q) * xi[a] * xi[b]
        for a in range(k): H[a][a] += 1e-6
        d = M._resolver(H, g)
        w = [a + b for a, b in zip(w, d)]
        if max(abs(v) for v in d) < 1e-8: break
    # inversa de H para el error estandar del ultimo coeficiente
    e = [0.0] * k; e[-1] = 1.0
    col = M._resolver(H, e)
    return w, math.sqrt(max(col[-1], 1e-12))


def estimar(nombre, filas, cod):
    F = [r for r in filas if r.get(cod) is not None and r.get('p') is not None and 0 < r['p'] < 1]
    act = [abs(r[cod]) for r in F if r[cod] != 0]
    if len(act) < 30: return None
    X = [[1.0, lg(r['p']), float(r[cod])] for r in F]; Y = [r['y'] for r in F]
    w, ee = logit_fit(X, Y)
    act.sort(); xt = act[len(act) // 2]
    b = w[2]; s = ee * xt
    be = b * TAU ** 2 / (TAU ** 2 + s * s)
    pp = lambda v: round(100 * (sg(v) - 0.5), 2)
    return dict(liga=nombre, codigo=cod, angulo=NOMBRE[cod], n=len(F), n_activos=len(act), beta=round(b, 5), ee=round(ee, 5),
                x_tipico=xt, pp_50=pp(b * xt), ic95_50=[pp((b - 1.96 * ee) * xt), pp((b + 1.96 * ee) * xt)],
                beta_encogido=round(be, 6), pp_50_encogido=pp(be * xt))


CORRER = {'BEISBOL': (lambda: M.correr_beisbol(['MLB', 'KBO', 'NPB', 'LMP', 'LVBP', 'LIDOM', 'ABL']), 'BEISBOL'),
          'NHL': (lambda: M.correr_hockey('NHL'), 'NHL'), 'NBA': (lambda: M.correr_basquet('NBA'), 'NBA'),
          'NCAAMB': (lambda: M.correr_basquet('NCAAMB'), 'NCAAMB'), 'NFL': (lambda: M.correr_americano('NFL'), 'NFL'),
          'NCAAFB': (lambda: M.correr_americano('NCAAFB'), 'NCAAFB'), 'FUTBOL': (lambda: M.correr_futbol(), 'FUTBOL')}
EST, RES = [], []
for dep, (fn, clave) in CORRER.items():
    fn()
    filas, C = M.ULTIMO[clave]; T = C.t
    E = estados(dep, filas, T)
    for r in filas: r.update(angulos(r, E))
    print('\n=====', dep, len(filas), 'partidos')
    for cod, s in SIGNO.items():
        e = estimar(dep, filas, cod)
        if e:
            EST.append(e)
            print('  %-4s %-58s n %6d act %6d  crudo %+5.2f pp [%+.1f, %+.1f]  encogido %+5.2f pp (x tipico %s)' % (
                cod, NOMBRE[cod], e['n'], e['n_activos'], e['pp_50'], *e['ic95_50'], e['pp_50_encogido'], e['x_tipico']))
        M.RESULTADOS.clear()
        Fx = [dict(r, x=r.get(cod)) for r in filas]
        if dep == 'BEISBOL': M._evaluar_por_corte(Fx, cod, NOMBRE[cod], dep, s)
        else: M.evaluar(Fx, cod, NOMBRE[cod], dep, s)
        RES.extend(M.RESULTADOS)
json.dump({'ganador': RES, 'estimacion': EST, 'tau_logit': TAU}, open(SALIDA, 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('\npasan:', [(r['liga'], r['codigo']) for r in RES if r['veredicto'] == 'pasa'])

# Uso (PowerShell):
#     cd C:\Edgeline_repo
#     $env:EDGELINE_BASE = "C:\Edgeline_repo"
#     python utilidades/minar_angulos_tanda11.py
#     python -m nucleo.angulos --catalogo
