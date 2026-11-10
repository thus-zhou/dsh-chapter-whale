/* Provider-scoped selectors. No credentials are stored in browser storage. */
(() => {
 let doc=null,editing=false,busy=false,renderedStamp='',view='bindings';
 const scans=new Map(),pendingChecks=new Set(),checks=new Map();
 const effortNames={auto:'自动',off:'关闭思考',low:'低',medium:'中',high:'高',max:'最高'};
 const probeNames={text:'短文本响应正常',json:'结构化响应正常',stream:'流式响应正常',tools:'工具调用正常'};
 const request=(path,method='GET',body)=>api(path,method,body,130000);
 const panel=document.createElement('article');panel.className='panel provider-panel';panel.id='provider-panel';
 panel.innerHTML=`<section id="provider-library" role="tabpanel" aria-labelledby="ai-tab-providers" hidden><div class="panel-header"><div><h2>供应商</h2><p class="field-help">连接一次，供所有角色选择。</p></div><div class="form-actions"><button class="button button-secondary" id="provider-dsh" type="button">连接 Our Free Model</button><button class="button button-primary" id="provider-add" type="button">添加供应商</button></div></div><div id="provider-list" class="provider-list"></div></section><section id="provider-team" role="tabpanel" aria-labelledby="ai-tab-bindings"><div class="panel-header"><div><h2>模型分工</h2><p class="field-help">每个角色各司其职，也可选择免费渠道池。</p></div><span class="team-caption">A → B → C → D → E</span></div><div class="panel-form"><form id="provider-bindings"><div id="provider-selectors" class="provider-selectors"></div><div class="binding-savebar"><p class="field-help" id="provider-save-status" role="status">修改后保存，下一次执行生效。</p><button class="button button-primary" type="submit">保存模型选择</button></div><details class="quiet-details binding-budget"><summary>回退与费用规则</summary><p class="field-help">仅调用你明确选择的备选。自动付费回退每书每天额外最多20元，额外恢复共用每日6次上限；缺少报价不调用。免费池按顺序轮换，预算耗尽后等待恢复。</p></details></form></div></section>`;
 $('page-ai').insertBefore(panel,$('page-ai').querySelector('.settings-layout'));
 function options(selected){return '<option value="">选择供应商</option>'+(doc?.providers||[]).filter(p=>p.enabled).map(p=>`<option value="${esc(p.id)}" ${p.id===selected?'selected':''}>${esc(p.name)}</option>`).join('');}
 function picker(role,binding,attribute='data-model',suffix='',required=false){
  const p=doc.providers.find(x=>x.id===binding.provider_id),id=`models-${role}${suffix}`,menu=`model-menu-${role}${suffix}`;
  return `<span class="model-picker"><span class="model-input"><input ${attribute} role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${menu}" aria-label="${role}${suffix?'备选':''}模型" value="${esc(binding.model_id||'')}" placeholder="${role==='default'?'选择模型，也可搜索':'选择模型或继承通用模型'}" autocomplete="off" ${required?'required':''}><button type="button" class="model-trigger" data-picker-toggle aria-label="${role}${suffix?'备选':''}选择模型" title="展开模型列表">⌄</button></span><div class="model-menu" id="${menu}" role="listbox" aria-label="${role}模型列表" hidden></div><datalist id="${id}">${(p?.models||[]).map(m=>`<option value="${esc(m)}"></option>`).join('')}</datalist></span>`;
 }
 function choices(role,binding={}){
  const p=doc.providers.find(x=>x.id===binding.provider_id),required=role==='default'||binding.provider_id;
  const fallback=p||doc.providers.find(x=>x.id===doc.default_binding?.provider_id);
  return `<details class="provider-binding" data-role="${role}" ${role==='default'&&!binding.model_id?'open':''}>
   <summary class="binding-identity"><span class="binding-letter" aria-hidden="true">${role==='default'?'✦':role}</span><span class="binding-title"><strong>${role==='default'?'通用模型':roleLabels[role][0]}</strong><small>${role==='default'?'未单独指定时使用':roleLabels[role][1]}</small></span><span class="binding-current"><b>${esc(binding.model_id||(!binding.provider_id?doc.default_binding?.model_id:'')||'尚未选择')}</b><small>${esc(fallback?.name||'点击设置')}</small></span><span class="binding-chevron" aria-hidden="true">⌄</span></summary>
   <div class="binding-controls"><label><span class="binding-label">供应商</span><span class="sr-only">${role}供应商</span><select data-provider>${options(binding.provider_id).replace('选择供应商',role==='default'?'选择供应商':'继承通用模型')}</select></label><label><span class="binding-label">模型</span>${picker(role,binding,'data-model','',required)}</label>
   <div class="role-tools"><label><span class="binding-label">思考强度</span><select data-effort aria-label="${role}思考强度">${Object.entries(effortNames).map(([value,name])=>`<option value="${value}" ${value===(binding.reasoning_effort||'auto')?'selected':''}>${name}</option>`).join('')}</select></label><div class="role-tools-actions"><button type="button" class="button button-secondary button-small" data-role-models>刷新模型</button><button type="button" class="button button-secondary button-small" data-role-test>检测当前选择</button></div><p class="role-check" data-role-check role="status">未检测 · 不会自动发起付费请求</p></div>
   <details class="quiet-details binding-fallbacks"><summary>备选${binding.fallbacks?.length?' · '+binding.fallbacks.length:''}</summary><div data-fallbacks>${[0,1,2].map(i=>{const b=binding.fallbacks?.[i]||{};return `<div class="provider-fallback"><label><span class="field-help">备选 ${i+1} · 供应商</span><select data-fallback-provider>${options(b.provider_id)}</select></label><label><span class="field-help">模型</span>${picker(role,b,'data-fallback-model',`-fallback-${i}`)}</label></div>`;}).join('')}</div></details>
   <p class="binding-note">思考档位以接口实际支持为准。检测会调用当前模型并计入成本，不测试备选。</p></div></details>`;
 }
 function effective(row){
  const base=$('provider-selectors').querySelector('[data-role="default"]');
  const provider_id=row.querySelector('[data-provider]').value||base?.querySelector('[data-provider]').value;
  const model_id=row.querySelector('[data-model]').value.trim()||(!row.querySelector('[data-provider]').value?base?.querySelector('[data-model]').value.trim():'');
  return {provider_id,model_id,reasoning_effort:row.querySelector('[data-effort]').value};
 }
 const signature=(b)=>JSON.stringify([b.provider_id,b.model_id,b.reasoning_effort||'auto',b.provider_revision||doc.providers.find(p=>p.id===b.provider_id)?.revision||0]);
 function paintCheck(row){
  if(!row)return;const role=row.dataset.role,node=row.querySelector('[data-role-check]'),button=row.querySelector('[data-role-test]'),check=checks.get(role);
  let status='untested',message='未检测 · 点击后会真实调用当前模型';
  if(pendingChecks.has(role)){status='checking';message='正在检测 · 不会自动改用备选';}
  else if(check){
   if(signature(check)!==signature(effective(row))){status='stale';message='选择已更改，请重新检测';}
   else {status=check.status==='ok'?'ok':check.status==='inconclusive'?'stale':'failed';message=(status==='ok'?`${probeNames[check.probe_mode]||probeNames.text} · ${(check.elapsed_ms/1000).toFixed(1)} 秒`:check.message||'未收到有效响应')+` · ${time(check.checked_at)}`;if(check.scope==='one_pool_candidate')message+=` · 池中候选 ${check.tested_model_id}`;}
  }
  node.textContent=message;node.dataset.status=status;button.disabled=pendingChecks.has(role);button.textContent=pendingChecks.has(role)?'检测中…':'检测当前选择';
  let dot=row.querySelector('[data-role-health]');if(!dot){dot=document.createElement('i');dot.className='role-health';dot.dataset.roleHealth='';row.querySelector('.binding-title strong').append(dot);}
  dot.dataset.status=status;dot.title=message;dot.setAttribute('aria-label',message);
 }
 function pickerProvider(picker){const fallback=picker.closest('.provider-fallback');return fallback?fallback.querySelector('[data-fallback-provider]').value:effective(picker.closest('[data-role]')).provider_id;}
 function closePickers(except){for(const p of panel.querySelectorAll('.model-picker'))if(p!==except){p.querySelector('.model-menu').hidden=true;p.querySelector('input').setAttribute('aria-expanded','false');p.querySelector('input').removeAttribute('aria-activedescendant');p.closest('[data-role]').classList.remove('is-picking');}}
 function fillMenu(picker,query=''){
  const provider=doc.providers.find(p=>p.id===pickerProvider(picker)),menu=picker.querySelector('.model-menu'),input=picker.querySelector('input');
  const models=(provider?.models||[]).filter(m=>m.toLowerCase().includes(query.toLowerCase())),shown=models.slice(0,120);
  menu.innerHTML=shown.map((m,i)=>`<button type="button" role="option" tabindex="-1" id="${menu.id}-option-${i}" data-model-option="${esc(m)}" aria-selected="${m===input.value}">${esc(m)}</button>`).join('')+(!shown.length?'<span class="model-empty">没有匹配项，可直接输入模型 ID</span>':'')+(models.length>120?'<span class="model-empty">继续输入以缩小范围</span>':'');
  picker.dataset.active='-1';input.removeAttribute('aria-activedescendant');
 }
 async function scanModels(providerId){
  if(!providerId)throw Error('请先选择供应商');
  if(!scans.has(providerId))scans.set(providerId,request(`/api/ai/providers/${url(providerId)}/models`,'POST',{}).then(result=>{
   const p=doc.providers.find(x=>x.id===providerId);if(p)p.models=result.models;
   for(const picker of panel.querySelectorAll('.model-picker'))if(pickerProvider(picker)===providerId){picker.querySelector('datalist').innerHTML=result.models.map(m=>`<option value="${esc(m)}"></option>`).join('');if(!picker.querySelector('.model-menu').hidden)fillMenu(picker);}
   return result;
  }).finally(()=>scans.delete(providerId)));
  return scans.get(providerId);
 }
 async function openPicker(picker,query=''){
  closePickers(picker);picker.closest('[data-role]').classList.add('is-picking');
  const menu=picker.querySelector('.model-menu'),input=picker.querySelector('input'),pid=pickerProvider(picker),provider=doc.providers.find(p=>p.id===pid);
  fillMenu(picker,query);menu.hidden=false;input.setAttribute('aria-expanded','true');input.focus();
  if(provider && !provider.models?.length && picker.dataset.scannedProvider!==pid){
   picker.dataset.scannedProvider=pid;menu.innerHTML='<span class="model-empty">正在读取模型列表…</span>';
   try{await scanModels(pid);if(picker.isConnected && pickerProvider(picker)===pid)fillMenu(picker,query);}catch(e){menu.textContent=e.message+'；仍可手动输入模型 ID';}
  }
 }
 function pick(picker,value){
  const input=picker.querySelector('input'),row=picker.closest('[data-role]');input.value=value;
  if(!picker.closest('.provider-fallback') && !row.querySelector('[data-provider]').value){row.querySelector('[data-provider]').value=effective(row).provider_id;input.required=true;}
  closePickers();input.dispatchEvent(new Event('input',{bubbles:true}));closePickers();input.focus();
 }
 async function testRow(row){
  const role=row.dataset.role;if(pendingChecks.has(role))return;
  const binding=effective(row),provider=doc.providers.find(x=>x.id===binding.provider_id);
  if(!binding.model_id || !provider){toast('请先选择供应商和模型',true);return;}
  pendingChecks.add(role);paintCheck(row);
  try{const result=await request(`/api/ai/roles/${role}/test`,'POST',{binding,provider_revision:provider.revision||0});checks.set(role,result);}
  catch(e){checks.set(role,{...binding,provider_revision:provider.revision||0,status:'failed',message:e.message,checked_at:new Date().toISOString(),elapsed_ms:0});}
  finally{pendingChecks.delete(role);paintCheck($('provider-selectors').querySelector(`[data-role="${role}"]`));}
 }
 function render(){
  if(!doc)return;
  const stamp=JSON.stringify([doc.providers,doc.roles,doc.default_binding,doc.needs_migration,doc.multi_model,doc.polish_mode,doc.review_policy,doc.editorial_release_rule]);
  for(const [role,value] of Object.entries(doc.role_checks||{}))if(!checks.has(role)||Date.parse(value.checked_at)>Date.parse(checks.get(role).checked_at))checks.set(role,value);
  if(stamp===renderedStamp){for(const row of panel.querySelectorAll('[data-role]'))paintCheck(row);return;}renderedStamp=stamp;
  $('provider-list').innerHTML=doc.needs_migration?'<div class="panel-form"><p>保留现有连接，建立供应商列表。</p><button id="provider-migrate" class="button button-secondary">迁移现有设置</button></div>':doc.providers.length?doc.providers.map(p=>{const managed=['free_pool','ofm_standalone'].includes(p.protocol);const type=p.protocol==='free_pool'?'免费渠道池':p.protocol==='ofm_standalone'?'独立免费服务':p.protocol==='dsh_local'?'DSH本机转发':'OpenAI兼容';return `<div class="provider-row"><span class="provider-monogram" aria-hidden="true">${esc(managed?'免':p.name.slice(0,1))}</span><div class="provider-description"><strong>${esc(p.name)}</strong><small>${esc(p.base_url)}</small><span class="field-help">${type} · ${p.has_key?'密钥已保存':'缺少密钥'} · ${p.models?.length||0} 个模型</span></div><div class="form-actions"><button class="button button-secondary button-small" data-provider-edit="${esc(p.id)}">${managed?'管理免费额度':'编辑与报价'}</button>${managed?'':`<button class="button button-ghost button-small" data-provider-models="${esc(p.id)}">读取模型</button><details class="provider-more"><summary aria-label="更多供应商操作">···</summary><button class="button button-ghost button-small" data-provider-delete="${esc(p.id)}">移除供应商</button></details>`}</div></div>`}).join(''):'<div class="provider-empty">还没有供应商。添加接口后，即可为各角色选择模型。</div>';
  if(!editing){
   $('provider-selectors').innerHTML=doc.needs_migration?'':['default',...'ABCDE'].map(r=>choices(r,r==='default'?doc.default_binding:doc.roles[r])).join('');
   if(!doc.needs_migration){
    $('provider-save-status').textContent='修改后保存，下一次执行生效。';$('provider-save-status').classList.remove('is-dirty');
    $('provider-selectors').insertAdjacentHTML('afterbegin',`<div class="team-enable"><label class="check-label"><input id="provider-multi" type="checkbox" ${doc.multi_model?'checked':''}>启用 A–E 分工</label><span class="field-help">关闭时统一使用通用模型</span></div>`);
    $('provider-selectors').insertAdjacentHTML('beforeend',`<details class="quiet-details provider-policy"><summary>创作策略</summary><div class="provider-policy-fields"><label>润色范围<select id="provider-polish"><option value="key">重点章节</option><option value="all">每章</option><option value="none">仅手动</option></select></label><label>审稿决策<select id="provider-review"><option value="e_decides">E 授权决策 · D 提供建议</option><option value="strict">D 必须通过</option></select></label></div></details>`);
    $('provider-polish').value=doc.polish_mode||'key';$('provider-review').value=doc.review_policy||'strict';
   }
  }
  setView(view);
  let releaseHint=$('editorial-release-hint');if(!releaseHint){releaseHint=document.createElement('p');releaseHint.id='editorial-release-hint';releaseHint.className='field-help';panel.querySelector('.provider-policy')?.append(releaseHint);}
  releaseHint.textContent=doc.editorial_release_rule?.enabled?'作者规则已启用：两次有效审查后，第三次润色完成即免D复审；仍检查字数、记忆和平台发布结果。':'';
  releaseHint.hidden=!releaseHint.textContent;
  const policy=doc.resource_policy||{};
  const budget=panel.querySelector('.binding-budget');
  budget.querySelector('summary').textContent='Token 与费用策略';
  budget.querySelector('p').textContent=(policy.provider_managed_tokens?'Token、缓存与自动思考交由供应商管理；程序不发送输出Token上限。':'Token 按现有模型请求设置。')+(policy.fallback_cost_limit_cny===null?' 费用不设上限，付费备选仍只使用你选择的连接；用量及未知费用照常记录。':' 自动付费回退每书每天额外最多20元；缺少报价不调用。')+' 故障恢复次数、超时和发布核验仍保留。';
  panel.dataset.costLimit=policy.fallback_cost_limit_cny===null?'unlimited':'limited';
  let hint=$('resource-policy-hint');if(!hint){hint=document.createElement('p');hint.id='resource-policy-hint';hint.className='field-help resource-policy-hint';$('provider-team').querySelector('.panel-header').after(hint);}
  hint.textContent=policy.fallback_cost_limit_cny===null?'费用不设上限'+(policy.provider_managed_tokens?' · Token 跟随供应商':'')+' · 自动恢复与发布核验保留':'';
  hint.hidden=!hint.textContent;
  for(const row of panel.querySelectorAll('[data-role]'))paintCheck(row);
  if(editing)for(const row of $('provider-selectors').querySelectorAll('[data-role]')){
   for(const select of row.querySelectorAll('[data-provider],[data-fallback-provider]')){const value=select.value;select.innerHTML=options(value);select.value=value;}
   const p=doc.providers.find(x=>x.id===row.querySelector('[data-provider]').value);
   row.querySelector('datalist').innerHTML=(p?.models||[]).map(m=>`<option value="${esc(m)}"></option>`).join('');
  }
  const migrate=$('provider-migrate');if(migrate)migrate.onclick=()=>act(async()=>{doc=await request('/api/ai/providers/migrate','POST',{});render();});
 }
 async function act(fn){if(busy)return;busy=true;try{await fn();}catch(e){toast(e.message,true);}finally{busy=false;if(!editing)await sync(true);}}
 async function sync(force=false){if(!force&&(busy||editing||panel.querySelector('.model-menu:not([hidden])')))return;try{doc=await request('/api/ai/providers');render();}catch(e){$('provider-list').textContent=e.message;}}
 function edit(id){const p=doc?.providers.find(x=>x.id===id)||{},wasEditing=editing;
  if(['free_pool','ofm_standalone'].includes(p.protocol)){document.querySelector('[data-mode="free"]')?.click();toast('此连接由免费额度工作台管理，密钥不会显示在网页中');return;}
  openDialog(id?'编辑供应商':'添加供应商',`<form id="provider-editor" class="panel-form"><label>名称<input name="name" value="${esc(p.name||'')}" required maxlength="100"></label><label>接口地址<input name="base_url" type="url" value="${esc(p.base_url||'')}" required></label><label>协议<select name="protocol"><option value="openai_compatible">OpenAI兼容</option><option value="dsh_local" ${p.protocol==='dsh_local'?'selected':''}>DSH本机网关</option></select></label><label>密钥<input name="api_key" type="password" autocomplete="new-password" placeholder="留空保持同一接口密钥"></label><details class="quiet-details"><summary>模型报价与免费标记</summary><label>每百万Token报价（JSON，按模型ID）<textarea name="pricing" rows="5">${esc(JSON.stringify(p.pricing||{},null,2))}</textarea></label><p class="field-help">例：{"模型ID":{"input":"1","output":"2","cached":"1","currency":"CNY"}}。美元报价还需 usd_to_cny。</p><label>已确认免费模型ID（每行一个）<textarea name="free_models" rows="3">${esc((p.free_models||[]).join('\n'))}</textarea></label></details><div class="form-actions"><button class="button button-primary" type="submit">保存供应商</button><button class="button button-secondary" id="provider-test" type="button" ${id?'':'disabled'}>测试模型</button></div></form>`);
  $('provider-editor').onsubmit=e=>{e.preventDefault();act(async()=>{const f=Object.fromEntries(new FormData(e.target));if(!f.api_key)delete f.api_key;f.pricing=JSON.parse(f.pricing||'{}');f.free_models=f.free_models.split('\n').map(x=>x.trim()).filter(Boolean);doc=await request('/api/ai/providers'+(id?'/'+url(id):''),id?'PUT':'POST',f);$('action-dialog').close();editing=wasEditing;render();toast('供应商已保存');});};
  $('provider-test').onclick=()=>act(async()=>{const model=prompt('测试模型ID（调用会产生该接口费用）',p.models?.[0]||'');if(!model)return;await request('/api/ai/providers/'+url(id)+'/test','POST',{model_id:model});toast('模型已返回有效文本');});
  if(id){
   const advanced=$('provider-editor').querySelector('details');
   advanced.insertAdjacentHTML('beforeend','<button class="button button-secondary" type="button" id="provider-reprice">按已保存报价补算本供应商未定价记录</button>');
   $('provider-reprice').onclick=()=>act(async()=>{const r=await request('/api/ai/providers/'+url(id)+'/reprice','POST',{});toast(`已补算 ${r.recalculated} 条；历史已计价记录未改动`);});
  }
 }
 panel.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.providerEdit!==undefined)edit(b.dataset.providerEdit);if(b.dataset.providerModels)act(async()=>{const r=await request('/api/ai/providers/'+url(b.dataset.providerModels)+'/models','POST',{});await sync();toast(`读到 ${r.count} 个模型`);});if(b.dataset.providerDelete&&confirm('移除供应商？已被模型引用时不会移除。'))act(async()=>{await request('/api/ai/providers/'+url(b.dataset.providerDelete),'DELETE');await sync();});});
 $('provider-add').onclick=()=>edit();
 $('provider-dsh').onclick=()=>act(async()=>{await request('/api/ai/providers/dsh/import','POST',{});await sync();toast('已连接本机DSH配置，尚未替换正式角色');});
 function updateSummary(row){if(!row)return;const defaultRow=$('provider-selectors').querySelector('[data-role="default"]');const providerId=row.querySelector('[data-provider]').value||defaultRow?.querySelector('[data-provider]').value;const model=row.querySelector('[data-model]').value.trim()||(!row.querySelector('[data-provider]').value?defaultRow?.querySelector('[data-model]').value.trim():'')||'尚未选择';row.querySelector('.binding-current b').textContent=model;row.querySelector('.binding-current small').textContent=doc.providers.find(p=>p.id===providerId)?.name||'点击设置';}
 $('provider-bindings').addEventListener('input',e=>{
  editing=true;$('provider-save-status').textContent='有未保存的修改';$('provider-save-status').classList.add('is-dirty');
  const row=e.target.closest('[data-role]');
  if(e.target.matches('[data-model]') && e.target.value.trim() && !row.querySelector('[data-provider]').value){row.querySelector('[data-provider]').value=effective(row).provider_id;e.target.required=true;}
  if(e.target.matches('[data-model],[data-fallback-model]'))openPicker(e.target.closest('.model-picker'),e.target.value.trim());
  updateSummary(row);for(const item of $('provider-selectors').querySelectorAll('[data-role]')){if(e.target.closest('[data-role="default"]'))updateSummary(item);paintCheck(item);}
 });
 $('provider-bindings').addEventListener('invalid',e=>{const row=e.target.closest('.provider-binding');if(row)row.open=true;},true);
 $('provider-bindings').addEventListener('toggle',e=>{if(!e.target.matches('.provider-binding')||!e.target.open||matchMedia('(prefers-reduced-motion: reduce)').matches)return;e.target.querySelector('.binding-controls').animate([{opacity:0,transform:'translateY(-5px)'},{opacity:1,transform:'translateY(0)'}],{duration:200,easing:'ease-out'});},true);
 $('provider-bindings').addEventListener('change',e=>{
  if(!e.target.matches('[data-provider],[data-fallback-provider]'))return;
  closePickers();const row=e.target.closest('[data-role]'),p=doc.providers.find(x=>x.id===e.target.value),scope=e.target.closest('.provider-fallback')||row;
  scope.querySelector('datalist').innerHTML=(p?.models||[]).map(m=>`<option value="${esc(m)}"></option>`).join('');const input=scope.querySelector('.model-picker input');input.value='';input.required=!e.target.matches('[data-fallback-provider]')&&(Boolean(e.target.value)||row.dataset.role==='default');delete input.closest('.model-picker').dataset.scannedProvider;
  for(const item of $('provider-selectors').querySelectorAll('[data-role]')){updateSummary(item);paintCheck(item);}
 });
 $('provider-bindings').addEventListener('click',e=>{
  const picker=e.target.closest('.model-picker'),row=e.target.closest('[data-role]');
  if(e.target.closest('[data-model-option]')){e.preventDefault();pick(picker,e.target.closest('[data-model-option]').dataset.modelOption);return;}
  if(e.target.closest('[data-picker-toggle]')){e.preventDefault();const menu=picker.querySelector('.model-menu');if(menu.hidden)openPicker(picker);else closePickers();return;}
  if(e.target.matches('[role="combobox"]'))openPicker(picker);
  if(e.target.closest('[data-role-test]'))testRow(row);
  if(e.target.closest('[data-role-models]')){
   const button=e.target.closest('[data-role-models]'),pid=effective(row).provider_id;button.disabled=true;button.textContent='读取中…';
   scanModels(pid).then(result=>toast(`读到 ${result.count} 个模型，点击模型右侧箭头选择`)).catch(e=>toast(e.message,true)).finally(()=>{button.disabled=false;button.textContent='刷新模型';});
  }
 });
 $('provider-bindings').addEventListener('mousedown',e=>{if(e.target.closest('[data-model-option]'))e.preventDefault();});
 $('provider-bindings').addEventListener('keydown',e=>{
  const picker=e.target.closest('.model-picker');if(!picker||!e.target.matches('input'))return;
  const menu=picker.querySelector('.model-menu');
  if(e.key==='Escape'){closePickers();e.preventDefault();e.stopPropagation();return;}
  if(!['ArrowDown','ArrowUp','Enter'].includes(e.key))return;
  if(menu.hidden){if(e.key!=='Enter'){openPicker(picker);e.preventDefault();}return;}
  const options=[...menu.querySelectorAll('[data-model-option]')];if(!options.length)return;
  e.preventDefault();let i=Number(picker.dataset.active??-1);
  if(e.key==='Enter'){pick(picker,options[Math.max(0,i)].dataset.modelOption);return;}
  i=(i+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;picker.dataset.active=String(i);
  options.forEach((x,n)=>x.classList.toggle('is-highlighted',n===i));e.target.setAttribute('aria-activedescendant',options[i].id);options[i].scrollIntoView({block:'nearest'});
 });
 document.addEventListener('click',e=>{if(!e.target.closest('.model-picker'))closePickers();});
 $('provider-bindings').addEventListener('focusout',e=>{const picker=e.target.closest('.model-picker');if(picker&&!picker.contains(e.relatedTarget))closePickers();});
 $('provider-bindings').onsubmit=e=>{e.preventDefault();closePickers();act(async()=>{const payload={roles:{},multi_model:$('provider-multi').checked,polish_mode:$('provider-polish').value,review_policy:$('provider-review').value};for(const row of e.target.querySelectorAll('[data-role]')){const binding={provider_id:row.querySelector('[data-provider]').value,model_id:row.querySelector('[data-model]').value.trim(),reasoning_effort:row.querySelector('[data-effort]').value,fallbacks:[]};for(const f of row.querySelectorAll('.provider-fallback')){const provider_id=f.querySelector('select').value,model_id=f.querySelector('input').value.trim();if(provider_id&&model_id)binding.fallbacks.push({provider_id,model_id});else if(provider_id||model_id)throw Error('备选必须同时选择供应商和模型');}if(row.dataset.role==='default')payload.default_binding=binding;else payload.roles[row.dataset.role]=binding;}doc=await request('/api/ai/bindings','PUT',payload);editing=false;renderedStamp='';render();aiConfigRevision++;toast('模型选择已保存；当前请求不受影响');});};
 function setView(mode){view=mode;panel.hidden=mode==='free'||Boolean(doc?.needs_migration&&mode==='bindings');$('provider-library').hidden=mode!=='providers';$('provider-team').hidden=mode!=='bindings';for(const node of $('page-ai').querySelectorAll('.settings-layout,.roles-panel'))node.hidden=!doc?.needs_migration||mode!=='bindings';}
 window.NovelProviders={sync:()=>sync(),setView};sync();
})();
