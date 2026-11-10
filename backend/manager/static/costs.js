"use strict";
(() => {
 const money=value=>'¥'+Number(value || 0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:9});
 const palette=['#2d6150','#bd6749','#d2a35e','#749287','#918192','#7f9270','#bf8c77'];
 $('cost-models').closest('.cost-chart-grid').insertAdjacentHTML('beforeend','<article class="panel"><div class="panel-header"><h2>供应商成本</h2></div><div class="cost-chart" id="cost-providers"></div></article><article class="panel"><div class="panel-header"><h2>自动回退</h2></div><div class="cost-chart" id="cost-fallback"></div></article>');
 let revision=0, sequence=0, chapterCatalog=[], lastProject='', requested=false;
 function query(chapter=true){const p=new URLSearchParams();if($('cost-project').value)p.set('project_id',$('cost-project').value);p.set('days',$('cost-days').value);if(chapter && $('cost-chapter').value!=='')p.set('chapter',$('cost-chapter').value);return p.toString();}
 const blank=text=>`<div class="cost-empty">${esc(text)}</div>`;
 const barList=(items,key='cost_cny',tokens=false)=>{
  const max=Math.max(0,...items.map(x=>Number(x[key])));
  if(!items.length)return blank('模型调用开始后，这里将显示实际记录。');
  return `<div class="cost-bars">${items.map((x,i)=>`<div class="cost-bar-row"><div class="cost-bar-label"><span>${esc(x.label)}</span><strong>${tokens?fmt(x[key]):money(x[key])}</strong></div><div class="cost-bar-track"><span style="width:${max?Math.max(1,Number(x[key])/max*100):0}%;background:${palette[i%palette.length]}"></span></div><small>${fmt(x.calls)} 次调用${x.unpriced?` · ${x.unpriced} 次未定价`:''}</small></div>`).join('')}</div>`;
 };
 function trend(items){
  if(!items.length)return blank('暂无费用记录。');
  const values=items.map(x=>Number(x.cost_cny)), max=Math.max(...values,0.000001);
  const points=values.map((v,i)=>[48+i*524/Math.max(1,values.length-1),182-v/max*140]);
  const path=points.map((p,i)=>`${i?'L':'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');
  return `<svg class="cost-trend" viewBox="0 0 620 220" role="img" aria-label="每日已计算成本趋势"><line x1="48" y1="182" x2="585" y2="182" class="cost-axis"/><line x1="48" y1="42" x2="585" y2="42" class="cost-axis"/><text x="48" y="28">${esc(money(Math.max(...values)))}</text><path d="${path} L${points.at(-1)[0]},182 L48,182 Z" class="cost-area"/><path d="${path}" class="cost-line"/>${points.map((p,i)=>`<circle cx="${p[0]}" cy="${p[1]}" r="4" class="cost-point"><title>${esc(items[i].label)}：${esc(money(items[i].cost_cny))} · ${items[i].calls} 次</title></circle>`).join('')}<text x="48" y="211">${esc(items[0].label)}</text><text x="580" y="211" text-anchor="end">${esc(items.at(-1).label)}</text></svg><p class="field-help">按北京时间统计，只绘制已有调用的日期；未计价部分不含在曲线中。</p>`;
 }
 function donut(items){
  const total=items.reduce((sum,x)=>sum+Number(x.cost_cny),0);
  if(!total)return blank(items.length?(items.every(x=>x.complete)?'当前记录的模型费用为零。':'当前模型尚无已计算金额，可先查看 Token 构成。'):'暂无模型调用。');
  let offset=0;
  const arcs=items.map((x,i)=>{const share=Number(x.cost_cny)/total*100;const node=`<circle cx="80" cy="80" r="57" pathLength="100" fill="none" stroke="${palette[i%palette.length]}" stroke-width="18" stroke-dasharray="${share} ${100-share}" stroke-dashoffset="${-offset}" transform="rotate(-90 80 80)"><title>${esc(x.label)}：${esc(money(x.cost_cny))}</title></circle>`;offset+=share;return node;}).join('');
  return `<div class="cost-donut-layout"><svg viewBox="0 0 160 160" role="img" aria-label="模型成本占比">${arcs}<text x="80" y="77" text-anchor="middle">模型投入</text><text x="80" y="97" text-anchor="middle">${items.length} 个</text></svg><div>${items.map((x,i)=>`<div class="cost-legend"><span style="background:${palette[i%palette.length]}"></span><div><strong>${esc(x.label)}</strong><small>${money(x.cost_cny)} · ${(Number(x.cost_cny)/total*100).toFixed(1)}%</small></div></div>`).join('')}</div></div>`;
 }
 function tokenChart(items){
  const total=items.map(x=>({...x,key_tokens:x.input_tokens+x.output_tokens}));
  const max=Math.max(0,...total.map(x=>x.key_tokens));
  if(!total.length)return blank('暂无 Token 用量。');
  return `<div class="cost-token-legend"><span>● 输入</span><span>● 输出</span></div><div class="cost-bars">${total.map(x=>`<div class="cost-bar-row"><div class="cost-bar-label"><span>${esc(x.label)}</span><strong>${fmt(x.key_tokens)}</strong></div><div class="cost-token-track"><span style="width:${max?x.input_tokens/max*100:0}%"></span><span style="width:${max?x.output_tokens/max*100:0}%"></span></div><small>输入 ${fmt(x.input_tokens)} / 输出 ${fmt(x.output_tokens)}${x.estimated_calls?' · 含估算':''}</small></div>`).join('')}</div>`;
 }
 function table(headers,rows){return `<div class="cost-table-wrap"><table class="cost-table"><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${x}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
 function render(data){
  const s=data.summary, chapters=data.chapters.filter(x=>x.key[1]>0), direct=chapters.reduce((sum,x)=>sum+Number(x.cost_cny),0);
  const unconverted=s.unconverted_amounts?.USD;
  const totalLabel=money(s.cost_cny)+(unconverted?' + US$'+Number(unconverted).toLocaleString('zh-CN',{maximumFractionDigits:9}):'');
  $('cost-stats').innerHTML=stat('已计算总成本',totalLabel,s.complete?'按已保存价格计算':'含未计价或未换算部分','activity')+stat('输入 + 输出 Token',fmt(s.input_tokens+s.output_tokens),`缓存命中 ${fmt(s.cached_tokens)} Token`,'layers')+stat('平均单章直接成本',chapters.length?money(direct/chapters.length):'—','人民币直接成本，不含全书共用费用','book')+stat('模型请求次数',fmt(s.calls),`接口用量 ${s.reported_calls} 次 · 估算 ${s.estimated_calls} 次`,'spark');
  const unlimited=data.resource_policy?.fallback_cost_limit_cny===null;
  const issues=[s.unpriced?`${s.unpriced} 次未定价`:null,s.unknown_usage?`${s.unknown_usage} 次用量未知`:null,s.unconverted?`${s.unconverted} 次缺少汇率`:null,s.ledger_gaps?`${s.ledger_gaps} 条费用记录缺口${unlimited?'，需核对账单':'，已禁止付费回退'}`:null].filter(Boolean);
  $('cost-note').textContent=s.calls?`接口用量计价 ${money(s.reported_cost_cny)} · 估算部分 ${money(s.estimated_cost_cny)}${issues.length?'；'+issues.join('，')+'，总额尚不完整。':'。'}${s.failed_calls?` 包含 ${s.failed_calls} 次失败、中断或待核对请求。`:''}`:'尚无调用记录。设置各模型价格后，后续调用会自动计入；此前消耗无法追溯。';
  $('cost-trend').innerHTML=trend(data.daily);$('cost-stages').innerHTML=barList(data.stages);$('cost-models').innerHTML=donut(data.models);$('cost-tokens').innerHTML=tokenChart(data.stages);
  $('cost-providers').innerHTML=barList(data.providers||[]);
  $('cost-fallback').innerHTML=`<p>已记录回退费用 ${money(data.fallback?.cost_cny)} · ${data.fallback?.calls||0} 次请求</p><p class="field-help">${unlimited?'费用不设上限；仅使用你设置的备选。未定价或未知用量不计作免费。':'每书每日20元；未结算预留不会释放。'}</p>`+((data.fallback_budgets||[]).map(b=>`<p>${esc(b.project.split(/[\\/]/).at(-1))} · 已结算 ${money(b.settled_cny)}，历史预留 ${money(b.reserved_cny)}${b.limit_cny===null?' · 不设费用上限':`，剩余 ${money(b.remaining_cny)}`}</p>`).join(''));
  $('cost-chapters').innerHTML=data.chapters.length?table(['作品 / 章节','输入 Token','输出 Token','已计算成本','请求 / 状态'],data.chapters.map(x=>{
   const p=state.projects.find(p=>p.path===x.key[0]);return [`<strong>${esc(p?.title || (x.key[0]?x.key[0].split(/[\\/]/).at(-1):'系统共用'))}</strong><small>${esc(x.label)}</small>`,fmt(x.input_tokens),fmt(x.output_tokens),money(x.cost_cny),`${x.calls} 次<small>${x.complete?'已计价':'有未计价部分'}${x.estimated_calls?' · 含估算':''}</small>`];
  })):blank('章节开始创作后，将分别列出各章成本。');
  $('cost-requests').innerHTML=data.recent.length?table(['时间 / 环节','模型','输入 / 输出','费用','用量来源'],data.recent.map(x=>[`${esc(time(x.created_at))}<small>${esc(costStage(x.stage))}${x.chapter?' · 第'+x.chapter+'章':''}</small>`,`${esc(x.model)}<small>${esc(x.role || '通用')} · 请求 ${x.attempt}</small>`,`${fmt(x.input_tokens)} / ${fmt(x.output_tokens)}`,x.cost_cny!==null?money(x.cost_cny):x.cost!==null?`${esc(x.price.currency)} ${esc(x.cost)}`:'待计价',`${esc({reported:'接口实测',estimated:'估算',unknown:'未知'}[x.metering])}<small>${esc({success:'完成',failed:'失败',interrupted:'中断',pending:'待核对'}[x.status])}</small>`])):blank('暂无请求。');
  $('cost-export').href='/api/costs/export?'+query();
 }
 const stageNames={planning:'剧情规划',draft:'正文初稿',polish:'润色与修订',review:'一致性审查',learning:'示范学习',memory:'共享记忆',entities:'设定与人物同步',continuity:'连续性摘要',rag:'检索与向量',research:'写前调研',conversation:'创作沟通',brief:'约定扩写',authorization:'E 审查决策',publication:'E 发布决策',probe:'连接测试',other:'其他调用'};
 function costStage(stage){return stageNames[stage] || stage;}
 function sync(){
  const selected=$('cost-project').value, html='<option value="">全部作品</option>'+state.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
  if($('cost-project').innerHTML!==html){$('cost-project').innerHTML=html;if(state.projects.some(p=>p.id===selected))$('cost-project').value=selected;}
  if(location.hash==='#costs')load(false);
 }
 async function load(force=true){
  if(requested && !force)return;
  const current=++sequence;requested=true;
  try{
   const project=$('cost-project').value;
   {
    const all=await api('/api/costs?'+query(false));if(current!==sequence)return;
    chapterCatalog=[...new Set(all.chapters.map(x=>x.key[1]))].sort((a,b)=>a-b);lastProject=project;
    const selected=$('cost-chapter').value, markup='<option value="">全部章节</option>'+chapterCatalog.map(n=>`<option value="${n}">${n?'第 '+n+' 章':'全书与共用'}</option>`).join('');
    if($('cost-chapter').innerHTML!==markup)$('cost-chapter').innerHTML=markup;
    if(chapterCatalog.includes(Number(selected)) && selected!=='')$('cost-chapter').value=selected;
    if($('cost-chapter').value===''){render(all);return;}
   }
   const data=await api('/api/costs?'+query());if(current===sequence)render(data);
  }catch(error){if(current===sequence)$('cost-note').textContent=error.message;}
  finally{if(current===sequence)requested=false;}
 }
 actions['cost-prices']=async()=>{
  const data=await api('/api/costs/pricing');revision=data.revision;
  openDialog('模型价格',`<form id="cost-price-form" class="dialog-form"><p class="field-help">按你的接口账单填写每 100 万 Token 的价格。价格留空表示未定价，填写 0 表示免费；缓存价格留空沿用输入价。</p><label>美元兑人民币汇率（可选）<input name="fx" type="number" min="0.000001" step="any" value="${esc(data.usd_to_cny ?? '')}" placeholder="使用美元报价时填写"></label><div class="cost-price-list">${data.models.map((m,i)=>{const price=data.rates.find(r=>r.base_url===m.base_url && r.model===m.model);return `<fieldset class="cost-price-card" data-index="${i}"><legend>${esc(m.model)} ${m.roles.length?`<span>${esc(m.roles.join(' / '))}</span>`:''}</legend><small>${esc(m.base_url)}</small><div class="cost-price-grid"><label>币种<select name="currency-${i}"><option value="CNY" ${price?.currency==='CNY'?'selected':''}>人民币</option><option value="USD" ${price?.currency==='USD'?'selected':''}>美元</option></select></label><label>输入<input name="input-${i}" type="number" min="0" max="1000000" step="any" value="${esc(price?.input ?? '')}" placeholder="未定价"></label><label>输出<input name="output-${i}" type="number" min="0" max="1000000" step="any" value="${esc(price?.output ?? '')}" placeholder="未定价"></label><label>缓存输入<input name="cached-${i}" type="number" min="0" max="1000000" step="any" value="${esc(price?.cached ?? '')}" placeholder="沿用输入"></label></div></fieldset>`;}).join('') || '<p>先在 AI 设置中选择模型，或开始一次调用。</p>'}</div><label class="cost-reprice"><input type="checkbox" name="reprice"> 补算此前未定价／未换算的记录</label><p class="field-help">已计价记录保留当时的价格与汇率。模型调用费用不含订阅、服务器或平台其他支出。</p>${formEnd('保存价格')}`,async(formData)=>{
   const rates=[];for(let i=0;i<data.models.length;i++){
    const incoming=formData.get(`input-${i}`),outgoing=formData.get(`output-${i}`),cache=formData.get(`cached-${i}`);
    if(incoming==='' && outgoing==='')continue;
    if(incoming==='' || outgoing==='')throw new Error('同一模型请同时填写输入和输出价格，免费项填写 0');
    rates.push({...data.models[i],currency:formData.get(`currency-${i}`),input_per_million:Number(incoming),output_per_million:Number(outgoing),cached_per_million:cache===''?null:Number(cache)});
   }
   const result=await api('/api/costs/pricing','PUT',{revision,rates,usd_to_cny:formData.get('fx')===''?null:Number(formData.get('fx')),reprice_unpriced:formData.has('reprice')});closeDialog();toast(`价格已保存${result.recalculated?'，已补算 '+result.recalculated+' 条记录':''}`);await load();
  });
 };
 for(const id of ['cost-project','cost-days','cost-chapter'])$(id).addEventListener('change',()=>{if(id!=='cost-chapter'){chapterCatalog=[];$('cost-chapter').value='';}load();});
 window.NovelCosts={load,sync};sync();
})();
