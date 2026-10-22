const $ = (s) => document.querySelector(s);
let rankingLimit = 50;
let currentRows = [];
let selectedBase = null;
let charts = {retidos:null, indice:null};

const fmt = n => Number(n || 0).toLocaleString('pt-BR', {maximumFractionDigits: 0});
const pct = n => `${(Number(n || 0) * 100).toFixed(1).replace('.', ',')}%`;
const dec = n => Number(n || 0).toFixed(2).replace('.', ',');
const esc = s => String(s ?? '—').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const responsavelSC = r => r.coordenador || r.supervisor || '—';

function clsStatus(s){return String(s||'NORMAL').toLowerCase().replaceAll(' ','-').replace('é','e').replace('í','i').replace('ó','o').replace('á','a');}

function params(includeStatus=true){
  const p=new URLSearchParams();
  [['data', '#dataFilter'],['uf','#ufFilter'],['rm','#rmFilter'],['sc','#scFilter']].forEach(([k,id])=>{
    const el=$(id); const v=el ? el.value : '';
    if(v)p.set(k,v);
  });
  if(includeStatus && $('#statusFilter')?.value)p.set('status',$('#statusFilter').value);
  return p;
}

async function getJSON(url){
  const r=await fetch(url,{cache:'no-store'});
  if(!r.ok)throw new Error(await r.text());
  return r.json();
}

function fillSelect(el, values, allLabel){
  const old=el.value;
  el.innerHTML=`<option value="">${allLabel}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  if(values.includes(old))el.value=old;
}

async function init(){
  try{
    const d=await getJSON('/api/datas');
    $('#dataFilter').innerHTML=d.datas.map(x=>`<option value="${x}">${new Date(x+'T12:00:00').toLocaleDateString('pt-BR')}</option>`).join('');
    await reloadFilters();
    await refresh();
  }catch(e){console.error(e);$('#updated').textContent='Erro ao carregar dados';}
}

async function reloadFilters(){
  const data=$('#dataFilter').value;
  const f=await getJSON('/api/filtros?data='+encodeURIComponent(data));
  fillSelect($('#ufFilter'),f.ufs,'Todas');
  fillSelect($('#rmFilter'),f.rms,'Todos');
  fillSelect($('#scFilter'),f.scs,'Todos');
}

async function refresh(){await Promise.all([loadResumo(),loadRanking(),loadGestao()]);}

async function loadResumo(){
  const r=await getJSON('/api/resumo?'+params(false));
  $('#updated').textContent=r.data?`Dados: ${new Date(r.data+'T12:00:00').toLocaleDateString('pt-BR')} • D-1`:'Sem dados';
  $('#kTotal').textContent=fmt(r.total);
  $('#kMonitorar').textContent=fmt(r.monitorar);
  $('#kPre').textContent=fmt(r.pre_alerta);
  $('#kCritico').textContent=fmt(r.pre_critico);
  $('#kAlerta').textContent=fmt(r.alerta);
  $('#kCapotadas').textContent=fmt(r.capotadas);
  $('#kRetidos').textContent=fmt(r.retidos_10d);
  $('#kReincidentes').textContent=fmt(r.reincidentes_30d);
}

function windowValues(r,w){const k=w.toLowerCase();return [Number(r['retidos_'+k]||0),Number(r['indice_'+k]||0)]}
function limits(w){return {'1D':[500,.5],'3D':[800,.8],'5D':[1000,1],'7D':[1200,1.2],'10D':[1500,1.5]}[w]}
function scoreWindow(r,w){const [q,i]=windowValues(r,w),[ql,il]=limits(w);return Math.min(q/ql,i/il)}

async function loadRanking(){
  const p=params();p.set('limit',rankingLimit);
  const data=await getJSON('/api/ranking?'+p);
  currentRows=data.rows;
  $('#rankingInfo').textContent=`Exibindo ${data.rows.length} de ${data.total} bases`;
  $('#rankingBody').innerHTML=data.rows.map(r=>{
    const [q,idx]=windowValues(r,r.janela_critica||'1D');
    return `<tr data-code="${r.codigo_base}">
      <td><b>${esc(r.nome_base)}</b></td>
      <td>${esc(r.uf)}</td>
      <td>${esc(responsavelSC(r))}</td>
      <td><span class="status-pill ${clsStatus(r.status_risco)}">${esc(r.status_risco)}</span></td>
      <td><b>${esc(r.janela_critica)}</b></td>
      <td class="risk-cell">${pct(r.score_risco)}</td>
      <td>${fmt(q)}</td>
      <td>${dec(idx)}</td>
      <td>${fmt(r.falta_qtd)}</td>
      <td>${dec(r.falta_indice)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="10">Nenhuma base encontrada.</td></tr>';

  document.querySelectorAll('#rankingBody tr[data-code]').forEach(tr=>tr.addEventListener('click',()=>selectBase(Number(tr.dataset.code))));
  renderHeat(data.rows.slice(0,25));
  if(selectedBase && data.rows.some(x=>x.codigo_base===selectedBase)) selectBase(selectedBase,false);
}

function renderHeat(rows){
  $('#heatBody').innerHTML=rows.map(r=>`<tr><td><b>${esc(r.nome_base)}</b></td>${['1D','3D','5D','7D','10D'].map(w=>{const s=scoreWindow(r,w);const c=s>=.9?'h3':s>=.8?'h2':s>=.6?'h1':'h0';return `<td><span class="heat ${c}">${pct(s)}</span></td>`}).join('')}</tr>`).join('');
}

async function loadGestao(){
  const tipo=$('#gestaoTipo').value;
  const d=$('#dataFilter').value;
  const data=await getJSON(`/api/gestao?data=${encodeURIComponent(d)}&tipo=${tipo}`);
  $('#gestaoList').innerHTML=data.rows.slice(0,20).map(x=>`<div class="owner"><div class="owner-top"><span class="owner-name">${esc(x.responsavel)}</span><b>${pct(x.score_max)}</b></div><div class="owner-stats"><div><span>Bases</span><strong>${fmt(x.bases)}</strong></div><div><span>Pré/Crítico</span><strong>${fmt(x.pre_alerta+x.pre_critico)}</strong></div><div><span>Alerta/Cap.</span><strong>${fmt(x.alerta+x.capotadas)}</strong></div><div><span>Retidos 10D</span><strong>${fmt(x.retidos_10d)}</strong></div></div></div>`).join('');
}

async function selectBase(code,scroll=true){
  selectedBase=code;
  let r=currentRows.find(x=>Number(x.codigo_base)===Number(code));
  if(!r){
    const p=params(false);p.set('limit','500');
    const d=await getJSON('/api/ranking?'+p);
    r=d.rows.find(x=>Number(x.codigo_base)===Number(code));
    if(!r)return;
  }
  $('#detailTitle').textContent=`${r.nome_base} • ${r.uf}`;
  $('#detailMeta').textContent=`S/C: ${responsavelSC(r)} • Código ${r.codigo_base}`;
  $('#detailStatus').textContent=r.status_risco;
  $('#detailStatus').className='status-pill '+clsStatus(r.status_risco);
  $('#dMax7').textContent=fmt(r.maior_entrega_prazo_7d);
  $('#dAvg7').textContent=fmt(r.media_entregues_prazo_7d);
  $('#dCap30').textContent=fmt(r.capotamentos_30d);
  $('#dDias').textContent=fmt(r.dias_consecutivos_capotamento);
  $('#dDivergencia').textContent=r.divergencia_regra?'⚠ Divergência':'OK';
  $('#pressureGrid').innerHTML=['1D','3D','5D','7D','10D'].map(w=>{const [q,i]=windowValues(r,w),[ql,il]=limits(w),s=scoreWindow(r,w);const c=s>=.9?'m3':s>=.8?'m2':s>=.6?'m1':'';return `<div class="pressure"><div class="row"><b>${w}</b><strong>${pct(s)}</strong></div><div class="bar"><i class="${c}" style="width:${Math.min(100,s*100)}%"></i></div><small>${fmt(q)} / ${fmt(ql)} retidos<br>Índice ${dec(i)} / ${dec(il)}<br>Falta ${fmt(Math.max(0,ql-q))} • ${dec(Math.max(0,il-i))}</small></div>`}).join('');
  await loadEvolution(code);
  if(scroll)$('#detailPanel').scrollIntoView({behavior:'smooth',block:'start'});
}

async function loadEvolution(code){
  const d=await getJSON(`/api/evolucao/${code}?dias=30`);
  const rows=d.rows;
  const labels=rows.map(x=>new Date(x.data+'T12:00:00').toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}));
  if(charts.retidos)charts.retidos.destroy();
  if(charts.indice)charts.indice.destroy();
  const common={responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:10}}}}};
  charts.retidos=new Chart($('#retidosChart'),{type:'line',data:{labels,datasets:[['1D','retidos_1d'],['3D','retidos_3d'],['5D','retidos_5d'],['7D','retidos_7d'],['10D','retidos_10d']].map(([l,k])=>({label:l,data:rows.map(x=>x[k]),tension:.25,pointRadius:2}))},options:common});
  charts.indice=new Chart($('#indiceChart'),{type:'line',data:{labels,datasets:[['1D','indice_1d'],['3D','indice_3d'],['5D','indice_5d'],['7D','indice_7d'],['10D','indice_10d']].map(([l,k])=>({label:l,data:rows.map(x=>x[k]),tension:.25,pointRadius:2}))},options:common});
}

$('#dataFilter').addEventListener('change',async()=>{await reloadFilters();await refresh()});
['#ufFilter','#rmFilter','#scFilter','#statusFilter'].forEach(id=>$(id).addEventListener('change',refresh));
$('#gestaoTipo').addEventListener('change',loadGestao);
$('#clearFilters').addEventListener('click',()=>{['#ufFilter','#rmFilter','#scFilter','#statusFilter'].forEach(id=>$(id).value='');refresh()});
$('#moreBtn').addEventListener('click',()=>{rankingLimit=Math.min(500,rankingLimit+50);loadRanking()});
$('#exportBtn').addEventListener('click',()=>{window.location='/api/exportar.csv?'+params(false).toString()});

init();
