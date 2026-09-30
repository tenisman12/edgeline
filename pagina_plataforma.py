# -*- coding: utf-8 -*-
"""
pagina_plataforma.py - dibuja salida\\plataforma_draft.html a partir de proximos.json.

Una sola pagina autocontenida (sin servidor, sin internet): abre el .html y listo.
Los datos van embebidos; el JS los pinta con textContent (nada se interpreta como HTML).
"""
import json


def render(data):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return HTML.replace("__DATA__", payload)


HTML = r"""<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Edgeline Próximos</title>
<style>
:root{
  --bg:#f4f5f7; --surface:#ffffff; --surface2:#f0f2f5; --ink:#0f1722; --muted:#5a6575; --line:#e2e6ec;
  --accent:#0a7f5f; --accent-soft:#dff4ec; --warn:#a85a00; --warn-soft:#fff0d9;
  --away:#3b6fd4; --home:#0a7f5f; --draw:#9aa4b2; --shadow:0 1px 2px rgba(15,23,34,.06),0 4px 14px rgba(15,23,34,.05);
  --w:#0a7f5f; --l:#c2413b; --d:#8a94a3;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0c1118; --surface:#141b25; --surface2:#1b2432; --ink:#e7ecf3; --muted:#94a1b4; --line:#263143;
  --accent:#3ddc97; --accent-soft:#12372c; --warn:#ffb454; --warn-soft:#3a2a10;
  --away:#6f9bff; --home:#3ddc97; --draw:#6b7788; --shadow:none; --w:#3ddc97; --l:#ff7b72; --d:#8391a5;
  color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0c1118; --surface:#141b25; --surface2:#1b2432; --ink:#e7ecf3; --muted:#94a1b4; --line:#263143;
  --accent:#3ddc97; --accent-soft:#12372c; --warn:#ffb454; --warn-soft:#3a2a10;
  --away:#6f9bff; --home:#3ddc97; --draw:#6b7788; --shadow:none; --w:#3ddc97; --l:#ff7b72; --d:#8391a5;
  color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  padding-inline:16px;padding-block:0 40px}
.wrap{max-width:1080px;margin:0 auto}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding-block:20px 8px}
.brand{display:flex;align-items:baseline;gap:10px;min-width:0}
.brand b{font-size:22px;letter-spacing:-.02em}
.brand span{color:var(--muted);font-size:13px}
button{font:inherit;color:inherit;cursor:pointer}
.ghost{background:transparent;border:1px solid var(--line);border-radius:8px;padding:6px 10px;color:var(--muted)}
.ghost:hover{color:var(--ink);border-color:var(--muted)}
.strip{display:flex;flex-wrap:wrap;gap:8px 20px;padding-block:6px 14px;color:var(--muted);font-size:13px}
.strip b{color:var(--ink);font-variant-numeric:tabular-nums}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);padding-block:10px;border-bottom:1px solid var(--line);
  display:flex;flex-direction:column;gap:8px}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tab,.chip{border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:5px 12px;font-size:13px;color:var(--muted)}
.tab[aria-pressed=true],.chip[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip small{opacity:.7;margin-left:4px;font-variant-numeric:tabular-nums}
.switch{margin-left:auto;display:flex;gap:6px;align-items:center;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,480px),1fr));gap:14px;padding-block:16px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:14px 16px;
  display:flex;flex-direction:column;gap:10px;min-width:0}
.top{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;color:var(--muted);font-size:12px}
.lg{font-weight:600;color:var(--ink);text-transform:uppercase;letter-spacing:.06em;font-size:11px}
.hora{font-variant-numeric:tabular-nums}
.badge{margin-left:auto;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;white-space:normal}
.badge.valor{background:var(--accent-soft);color:var(--accent)}
.badge.revisar{background:var(--warn-soft);color:var(--warn)}
.teams{display:flex;flex-direction:column;gap:6px}
.team{display:grid;grid-template-columns:1fr auto;gap:2px 10px;align-items:baseline;min-width:0}
.team .n{font-weight:600;font-size:15px;overflow-wrap:anywhere}
.team .n i{font-style:normal;font-weight:400;color:var(--muted);font-size:12px;margin-left:6px}
.team .p{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.team .s{grid-column:1/-1;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.team.pickside .p{color:var(--accent)}
.pbar{display:flex;height:8px;border-radius:99px;overflow:hidden;background:var(--surface2)}
.pbar i{display:block;height:100%}
.pick{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;font-size:13px}
.pick b{font-size:14px}
.tag{border-radius:6px;padding:1px 7px;font-size:11px;font-weight:600;background:var(--surface2);color:var(--muted)}
.tag.alta{background:var(--accent-soft);color:var(--accent)} .tag.media{background:var(--surface2);color:var(--ink)}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.kv div{background:var(--surface2);border-radius:10px;padding:8px 10px;min-width:0}
.kv small{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.kv span{font-weight:600;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.market{display:flex;flex-wrap:wrap;gap:4px 16px;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.market b{color:var(--ink)}
.alerta{background:var(--warn-soft);color:var(--warn);border-radius:10px;padding:8px 10px;font-size:12px}
.none{color:var(--muted);font-size:13px;background:var(--surface2);border-radius:10px;padding:8px 10px}
details{border-top:1px solid var(--line);padding-top:8px}
summary{cursor:pointer;color:var(--muted);font-size:13px;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";display:inline-block;width:1em}
details[open] summary::before{content:"▾ "}
.sec{margin-top:10px}
.sec h4{margin:0 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.tbl{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
.tbl th,.tbl td{text-align:right;padding:4px 6px;border-bottom:1px solid var(--line)}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tblw{overflow-x:auto}
.pos{color:var(--accent);font-weight:600}
.pills{display:flex;gap:4px;align-items:center}
.pill{width:22px;height:22px;border-radius:6px;display:grid;place-items:center;color:#fff;font-size:11px;font-weight:700}
.pill.W{background:var(--w)} .pill.L{background:var(--l)} .pill.D,.pill.T{background:var(--d)}
ul.l{margin:0;padding-left:16px;font-size:12px} ul.l li{margin:1px 0}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.empty{padding:40px 0;text-align:center;color:var(--muted)}
footer{color:var(--muted);font-size:12px;padding-top:8px;border-top:1px solid var(--line);line-height:1.5}
.avisos{background:var(--warn-soft);color:var(--warn);border-radius:10px;padding:8px 12px;font-size:12px;margin-block:8px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand"><b>Edgeline</b><span id="sub"></span></div>
    <button class="ghost" id="tema" type="button">Tema</button>
  </header>
  <div class="strip" id="strip"></div>
  <div class="bar">
    <div class="row" id="dias"></div>
    <div class="row"><div class="row" id="deportes"></div>
      <label class="switch"><input type="checkbox" id="soloValor"> Solo con valor</label></div>
  </div>
  <div id="avisos"></div>
  <div class="grid" id="lista"></div>
  <footer>Borrador. Probabilidades de modelos estadísticos propios contrastadas con la línea de DraftKings (vía ESPN).
  No garantizan resultados ni constituyen asesoría financiera. El contexto (abridores, lesiones, H2H) se muestra
  como referencia y no alimenta a los modelos. Horarios en hora de Ciudad de México.</footer>
</div>
<script>
const DATA = __DATA__;
const P = DATA.partidos || [];
const $ = id => document.getElementById(id);
function h(tag, attrs, ...kids){
  const e = document.createElement(tag);
  for (const [k,v] of Object.entries(attrs||{})){
    if (v==null || v===false) continue;
    if (k==='class') e.className=v; else if (k==='style') e.style.cssText=v; else e.setAttribute(k,v===true?'':v);
  }
  for (const c of kids.flat()){ if (c==null||c===false) continue; e.append(c.nodeType?c:document.createTextNode(String(c))); }
  return e;
}
const pct = (x,d=0) => x==null ? '–' : (x*100).toFixed(d)+'%';
const cuota = x => x==null ? '–' : (x>0?'+':'')+Math.round(x);
const num = (x,d=1) => x==null ? '–' : Number(x).toFixed(d);
const LADO = {home:'Local', away:'Visita', draw:'Empate', over:'Over', under:'Under'};

// ---------- estado de filtros
let dia = null, dep = 'todos', soloValor = false;
const dias = [...new Set(P.map(p=>p.fecha))].sort();
dia = dias[0] || null;

function etiquetaDia(f, i){
  const d = new Date(f+'T12:00:00Z');
  const t = d.toLocaleDateString('es-MX',{weekday:'short',day:'numeric',month:'short',timeZone:'UTC'});
  const gen = (DATA.generado||'').slice(0,10);
  const pre = f===gen ? 'Hoy · ' : (i===1 && dias[0]===gen ? 'Mañana · ' : '');
  return pre + t;
}

function resumen(){
  const con = P.filter(p=>p.modelo).length, val = P.filter(p=>p.valor).length;
  $('sub').textContent = 'Partidos de los próximos días · generado ' + (DATA.generado||'').replace('T',' ');
  const s = $('strip'); s.textContent='';
  [['Partidos',P.length],['Con predicción',con],['Con valor',val],['Sin modelo',P.length-con]]
    .forEach(([k,v])=>s.append(h('span',{},k+' ',h('b',{},v))));
  const av = $('avisos'); av.textContent='';
  if ((DATA.avisos||[]).length) av.append(h('div',{class:'avisos'}, 'Avisos: '+DATA.avisos.join(' · ')));
}

function barras(){
  const d = $('dias'); d.textContent='';
  dias.forEach((f,i)=>{
    const b = h('button',{class:'tab',type:'button','aria-pressed':f===dia}, etiquetaDia(f,i));
    b.onclick=()=>{dia=f; pintar();}; d.append(b);
  });
  const enDia = P.filter(p=>p.fecha===dia);
  const cuenta = {}; enDia.forEach(p=>cuenta[p.liga_nombre]=(cuenta[p.liga_nombre]||0)+1);
  const c = $('deportes'); c.textContent='';
  const todos = h('button',{class:'chip',type:'button','aria-pressed':dep==='todos'},'Todos',h('small',{},enDia.length));
  todos.onclick=()=>{dep='todos'; pintar();}; c.append(todos);
  Object.keys(cuenta).sort().forEach(n=>{
    const b = h('button',{class:'chip',type:'button','aria-pressed':dep===n}, n, h('small',{},cuenta[n]));
    b.onclick=()=>{dep=n; pintar();}; c.append(b);
  });
}

function equipo(p, lado){
  const e = p[lado], m = p.modelo;
  const prob = m ? (lado==='home'?m.p_home:m.p_away) : null;
  const sub = [e.probable ? (e.probable_rol||'Prob.')+': '+e.probable : null,
               m && m.x_home!=null ? 'esp. '+num(lado==='home'?m.x_home:m.x_away, m.unidad==='goles'?2:1)+' '+m.unidad : null]
              .filter(Boolean).join(' · ');
  return h('div',{class:'team'+(p.pick && p.pick.lado===lado?' pickside':'')},
    h('div',{class:'n'}, e.nombre, e.record ? h('i',{},e.record):null, e.ranking?h('i',{},'#'+e.ranking):null),
    h('div',{class:'p'}, prob==null?'':pct(prob)),
    sub ? h('div',{class:'s'},sub) : null);
}

function barraProb(m){
  const seg = (v,c)=>h('i',{style:'width:'+(v*100).toFixed(2)+'%;background:'+c});
  return h('div',{class:'pbar',role:'img','aria-label':'Probabilidades del modelo'},
    seg(m.p_away,'var(--away)'), m.p_draw!=null?seg(m.p_draw,'var(--draw)'):null, seg(m.p_home,'var(--home)'));
}

function mov(a,b){ return (a!=null && b!=null && a!==b) ? cuota(a)+' → '+cuota(b) : cuota(b); }

function mercadoFila(p){
  const q = p.cuotas||{}; if (!Object.keys(q).length) return null;
  const it = [];
  if (q.ml_home!=null) it.push(h('span',{},'ML visita ',h('b',{},mov(q.ml_away_open,q.ml_away)),' · local ',h('b',{},mov(q.ml_home_open,q.ml_home)),
      q.ml_draw!=null?[' · empate ',h('b',{},cuota(q.ml_draw))]:null));
  if (q.total!=null) it.push(h('span',{},'Total ',h('b',{},(q.total_open!=null&&q.total_open!==q.total?q.total_open+' → ':'')+q.total),
      q.over_odds!=null?' (o '+cuota(q.over_odds)+' / u '+cuota(q.under_odds)+')':''));
  if (q.spread_home!=null) it.push(h('span',{},'Spread local ',h('b',{},(q.spread_home>0?'+':'')+q.spread_home)));
  return h('div',{class:'market'}, ...it, h('span',{}, q.casa||''));
}

function metricas(p){
  const m = p.modelo; const k = [];
  if (m.x_home!=null && m.x_away!=null) k.push(['Marcador esperado', num(m.x_away, m.unidad==='goles'?2:1)+' – '+num(m.x_home, m.unidad==='goles'?2:1)]);
  if (m.total!=null){
    const vs = m.p_over!=null ? (m.p_over>=.5?'Over ':'Under ')+pct(m.p_over>=.5?m.p_over:1-m.p_over)+' vs '+m.linea_total+(m.linea_es_mercado?'':' (ref.)') : '';
    k.push(['Total esperado '+m.unidad, num(m.total,m.unidad==='goles'?2:1)+(vs?'  ·  '+vs:'')]);
  }
  if (m.spread) k.push(['Spread '+(m.spread.linea_home>0?'+':'')+m.spread.linea_home+' local', 'cubre local '+pct(m.spread.p_home)]);
  if (m.margen!=null) k.push(['Margen esperado', (m.margen>0?'local +':'visita +')+num(Math.abs(m.margen))]);
  (m.extra||[]).forEach(([a,b])=>k.push([a, typeof b==='number' && b<=1 && !/esperados/i.test(a) ? pct(b) : b]));
  return h('div',{class:'kv'}, k.map(([a,b])=>h('div',{},h('small',{},a),h('span',{},b))));
}

function tablaMercados(p){
  const ms = p.mercados||[]; if(!ms.length) return null;
  const nombre = x => x.lado==='home'?p.home.nombre:x.lado==='away'?p.away.nombre:LADO[x.lado]||x.lado;
  return h('div',{class:'sec'},h('h4',{},'Modelo vs mercado (sin vig)'),
    h('div',{class:'tblw'},h('table',{class:'tbl'},
      h('thead',{},h('tr',{},['Mercado','Lado','Cuota','Modelo','Mercado','Edge'].map(t=>h('th',{},t)))),
      h('tbody',{},ms.map(x=>h('tr',{},
        h('td',{},x.mercado),h('td',{},nombre(x)),h('td',{},cuota(x.cuota)),h('td',{},pct(x.p_modelo,1)),h('td',{},pct(x.p_mercado,1)),
        h('td',{class:x.estado==='valor'?'pos':''},(x.edge>0?'+':'')+(x.edge*100).toFixed(1)+'%'+(x.estado==='valor'?' · Kelly '+pct(x.kelly,1):x.estado==='revisar'?' · revisar':'')))))))
  );
}

function contexto(p){
  const c = p.contexto||{}, blocks = [];
  const nl = {home:p.home.nombre, away:p.away.nombre};
  if (c.lesiones && (c.lesiones.home||c.lesiones.away)){
    blocks.push(h('div',{class:'sec'},h('h4',{},'Lesiones'),h('div',{class:'two'},
      ['away','home'].map(l=>h('div',{},h('b',{},nl[l]),
        (c.lesiones[l]||[]).length ? h('ul',{class:'l'}, c.lesiones[l].map(x=>h('li',{},x.jugador+(x.pos?' ('+x.pos+')':'')+' – '+(x.estado||'')))) : h('div',{class:'s'},'Sin reportes')))))); }
  if (c.h2h) blocks.push(h('div',{class:'sec'},h('h4',{},'Cara a cara'),h('div',{},c.h2h.resumen||c.h2h.titulo||''),
      (c.h2h.ultimos||[]).length?h('ul',{class:'l'},c.h2h.ultimos.map(u=>h('li',{},u.fecha+' · '+u.marcador))):null));
  if (c.ultimos5) blocks.push(h('div',{class:'sec'},h('h4',{},'Últimos 5'),h('div',{class:'two'},
      ['away','home'].map(l=>h('div',{},h('div',{},nl[l]),h('div',{class:'pills'},(c.ultimos5[l]||[]).map(g=>h('span',{class:'pill '+(g.res||'D'),title:(g.vs||'')+' '+(g.rival||'')+' '+(g.score||'')},g.res||'·')))))))) ;
  if (c.ats) blocks.push(h('div',{class:'sec'},h('h4',{},'Contra el spread (ATS)'),h('div',{class:'two'},
      ['away','home'].map(l=>h('div',{},h('b',{},nl[l]),h('ul',{class:'l'},(c.ats[l]||[]).map(r=>h('li',{},r[0]+' '+r[1]))))))));
  if (c.espn_pred_home!=null) blocks.push(h('div',{class:'sec'},h('h4',{},'Predictor de ESPN'),
      h('div',{}, nl.home+' '+pct(c.espn_pred_home,1)+' · '+nl.away+' '+pct(1-c.espn_pred_home,1))));
  if (p.modelo && p.modelo.nota) blocks.push(h('div',{class:'sec'},h('div',{class:'s',style:'color:var(--muted);font-size:12px'},p.modelo.nota)));
  if (p.estadio) blocks.push(h('div',{class:'sec'},h('div',{style:'color:var(--muted);font-size:12px'},'Sede: '+p.estadio)));
  return blocks;
}

function tarjeta(p){
  const top = h('div',{class:'top'}, h('span',{class:'lg'},p.liga_nombre), h('span',{class:'hora'},p.hora+' MX'),
      p.nota?h('span',{},p.nota):null, p.serie?h('span',{},p.serie):null);
  if (p.valor){
    const v=p.valor, nom = v.lado==='home'?p.home.nombre:v.lado==='away'?p.away.nombre:(LADO[v.lado]||v.lado);
    top.append(h('span',{class:'badge valor'},'VALOR · '+v.mercado+' '+nom+' '+cuota(v.cuota)+' · +'+(v.edge*100).toFixed(1)+'%'));
  } else if (p.alerta) top.append(h('span',{class:'badge revisar'},'REVISAR'));

  const c = h('article',{class:'card'}, top);
  c.append(h('div',{class:'teams'}, equipo(p,'away'), equipo(p,'home')));
  if (p.modelo){
    c.append(barraProb(p.modelo));
    if (p.modelo.p_draw!=null) c.append(h('div',{class:'market'},h('span',{},'Empate ',h('b',{},pct(p.modelo.p_draw)))));
    const cs = p.consenso, f = cs && cs.fuentes;
    c.append(h('div',{class:'pick'}, 'Pick del modelo: ', h('b',{},p.pick.texto+' '+pct(p.pick.prob)),
      h('span',{class:'tag '+p.pick.confianza},'confianza '+p.pick.confianza),
      cs && cs.de>1 ? h('span',{class:'tag',title:Object.entries(f).map(([k,v])=>k+': '+(LADO[v]||v)).join(' · ')}, cs.coinciden+'/'+cs.de+' fuentes coinciden') : null));
    c.append(metricas(p));
  } else {
    c.append(h('div',{class:'none'},'Sin predicción: '+(p.motivo||'sin datos')+'. Se muestra la línea y el contexto de ESPN.'));
  }
  const mf = mercadoFila(p); if (mf) c.append(mf);
  if (p.alerta) c.append(h('div',{class:'alerta'},p.alerta));
  const det = [p.modelo?tablaMercados(p):null, ...contexto(p)].filter(Boolean);
  if (det.length) c.append(h('details',{}, h('summary',{},'Detalle y contexto'), det));
  return c;
}

function pintar(){
  barras();
  const L = $('lista'); L.textContent='';
  let xs = P.filter(p=>p.fecha===dia && (dep==='todos'||p.liga_nombre===dep) && (!soloValor||p.valor));
  xs.sort((a,b)=> (b.valor?1:0)-(a.valor?1:0) || a.hora.localeCompare(b.hora));
  if (!xs.length) L.append(h('div',{class:'empty'},'No hay partidos con esos filtros.'));
  xs.forEach(p=>L.append(tarjeta(p)));
}

// ---------- tema (respeta el del sistema; el boton lo alterna)
(function(){
  const r = document.documentElement; let m = 'auto';
  try { m = localStorage.getItem('edgeline-tema') || 'auto'; } catch(e){}
  const aplicar = () => { if (m==='auto') r.removeAttribute('data-theme'); else r.setAttribute('data-theme',m); $('tema').textContent='Tema: '+({auto:'sistema',light:'claro',dark:'oscuro'}[m]); };
  $('tema').onclick = () => { m = m==='auto'?'dark':m==='dark'?'light':'auto'; try{localStorage.setItem('edgeline-tema',m);}catch(e){} aplicar(); };
  aplicar();
})();
$('soloValor').onchange = e => { soloValor = e.target.checked; pintar(); };
resumen(); pintar();
</script>
</body>
</html>
"""
