/* Independent account channels. No gateway/third-party keys enter the browser. */
(()=>{
 const target=$('page-ai'),provider=$('provider-panel');if(!target||!provider)return;
 const tabs=document.createElement('div');tabs.className='free-mode-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','模型设置');
 tabs.innerHTML='<button type="button" id="ai-tab-bindings" role="tab" aria-selected="true" aria-controls="provider-team" data-mode="bindings">模型分工</button><button type="button" id="ai-tab-providers" role="tab" aria-selected="false" aria-controls="provider-library" tabindex="-1" data-mode="providers">供应商</button><button type="button" id="ai-tab-free" role="tab" aria-selected="false" aria-controls="free-model-hub" tabindex="-1" data-mode="free">免费额度接入</button>';
 target.insertBefore(tabs,provider);
 const slider=document.createElement('span');slider.className='ai-tab-slider';slider.setAttribute('aria-hidden','true');tabs.prepend(slider);
 function moveSlider(){const selected=tabs.querySelector('[aria-selected="true"]');if(selected){slider.style.width=selected.offsetWidth+'px';slider.style.transform=`translateX(${selected.offsetLeft}px)`;}}
 new ResizeObserver(moveSlider).observe(tabs);moveSlider();
 // A compositor-sized local spotlight, coalesced to one update per frame.
 // Touch devices and reduced-motion users get a static surface.
 const pointerMotion=matchMedia('(hover: hover) and (prefers-reduced-motion: no-preference)');
 let pointerFrame=0,pointerCard=null,pointerPosition=null;
 target.addEventListener('pointermove',e=>{if(!pointerMotion.matches)return;const card=e.target.closest('.provider-binding,.free-channel');if(!card)return;if(pointerCard!==card){pointerCard?.style.removeProperty('--pointer-alpha');pointerCard=card;}const rect=card.getBoundingClientRect();pointerPosition=[e.clientX-rect.left,e.clientY-rect.top];if(!pointerFrame)pointerFrame=requestAnimationFrame(()=>{pointerFrame=0;if(!pointerCard||!pointerPosition)return;pointerCard.style.setProperty('--pointer-x',pointerPosition[0]+'px');pointerCard.style.setProperty('--pointer-y',pointerPosition[1]+'px');pointerCard.style.setProperty('--pointer-alpha','.08');});});
 target.addEventListener('pointerleave',()=>{if(pointerFrame)cancelAnimationFrame(pointerFrame);pointerFrame=0;pointerCard?.style.removeProperty('--pointer-alpha');pointerCard=null;});
 const panel=document.createElement('article');panel.className='panel free-hub';panel.hidden=true;panel.id='free-model-hub';
 panel.innerHTML=`<div class="panel-header"><div><span class="eyebrow">FREE MODEL WORKSPACE</span><h2>免费额度接入</h2><p class="field-help">独立运行 · 网页授权 · 凭据加密留在本机</p></div><button type="button" id="free-start" class="button button-primary">启动独立渠道服务</button></div>
 <div class="free-hub-body"><p id="free-service-status" role="status">正在检查本地服务…</p><div id="free-error" role="alert"></div>
 <section id="free-active" hidden><div class="free-toolbar"><div id="free-summary" class="free-summary"></div><label class="check-label"><input id="free-auto-checkin" type="checkbox">每日自动签到</label><button type="button" id="free-refresh" class="button button-secondary">刷新状态与模型</button></div>
 <p class="field-help">登录、余额、领取和模型开关都在下方渠道内完成。验证码或扫码需你完成；部分本机回调登录需在电脑浏览器进行。官方额度与可用性以渠道实时返回为准。</p>
 <div id="free-channel-detail" hidden><button id="free-detail-back" type="button" class="button button-secondary">返回全部渠道</button><div id="free-detail-root"></div></div><div id="free-channel-grid" class="free-channel-grid"></div>
 <section class="free-pool-editor" aria-labelledby="free-pool-title"><div><span class="eyebrow">YOUR FREE POOL</span><h3 id="free-pool-title">免费渠道池</h3><p class="field-help">按顺序轮换你选入的模型。每个 A–E 角色可选择固定模型或此池；付费备选在“模型分工”中单独配置。</p></div>
 <div class="free-pool-add"><label>模型<input id="free-pool-model" list="free-pool-catalog" placeholder="搜索或输入已列出的模型ID"><datalist id="free-pool-catalog"></datalist></label><button id="free-pool-add" type="button" class="button button-secondary">加入池</button></div>
 <div id="free-pool-members"></div><label>授权作品<select id="free-pool-project"><option value="">选择作品</option></select></label>
 <label class="check-label"><input id="free-pool-quota" type="checkbox">我确认所选模型使用免费额度，而非付费订阅或按量计费</label>
 <label class="check-label"><input id="free-pool-privacy" type="checkbox">允许这些渠道处理所选作品正文和必要记忆，不发送番茄登录态及无关文件</label>
 <div class="free-pool-footer"><span class="field-help" id="free-pool-rule">免费轮换 → 明确配置的付费备选。费用策略读取中；额外恢复仍共用每日6次上限。</span><button id="free-pool-save" type="button" class="button button-primary">保存免费池</button></div></section></section></div>`;
 target.insertBefore(panel,provider);
 panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','ai-tab-free');
 // The pool is a short, expandable control, not the bottom of a 13-card scroll.
 const pool=panel.querySelector('.free-pool-editor'),poolDetails=document.createElement('details');
 poolDetails.className='free-pool-disclosure';poolDetails.innerHTML='<summary><span>免费渠道池<small>选择模型与授权作品</small></span><span class="pool-disclosure-action">配置</span></summary>';
 pool.before(poolDetails);poolDetails.append(pool);$('free-active').insertBefore(poolDetails,$('free-channel-detail'));
 const filters=document.createElement('div');filters.className='free-channel-filters';
 filters.innerHTML='<label class="search-field"><input id="free-channel-search" type="search" aria-label="搜索免费渠道" placeholder="搜索渠道、平台或模型…"></label><label class="inline-filter"><span class="sr-only">渠道状态</span><select id="free-channel-filter" aria-label="渠道状态"><option value="all">全部渠道</option><option value="connected">已登录</option></select></label>';
 $('free-active').insertBefore(filters,$('free-channel-detail'));
 const noChannels=document.createElement('p');noChannels.id='free-channel-empty';noChannels.className='free-channel-empty';noChannels.hidden=true;noChannels.textContent='没有匹配的渠道';$('free-channel-grid').after(noChannels);
 if($('provider-dsh'))$('provider-dsh').hidden=true;
 let current,summary,statuses={},members=[],busy=false,closeDetail=null,module=null,loaded=false;
 const call=(path,method='GET',body)=>api('/api/free-model'+path,method,body,200000);
 const rpc=async(method,payload={})=>{const result=await call('/rpc','POST',{method,payload});if(!result.ok)throw Error(result.error?.message||'渠道操作未完成');return result.value};
 const error=reason=>{$('free-error').textContent=reason?.message||String(reason)};
 async function act(fn){if(busy)return;busy=true;panel.setAttribute('aria-busy','true');$('free-error').textContent='';const controls=[...panel.querySelectorAll('#free-start,#free-refresh,#free-auto-checkin,#free-pool-save')].map(node=>[node,node.disabled]);for(const[node]of controls)node.disabled=true;try{await fn()}catch(reason){error(reason)}finally{busy=false;panel.removeAttribute('aria-busy');for(const[node,disabled]of controls)node.disabled=disabled}}
 function renderMembers(){
  $('free-pool-members').innerHTML=members.length?members.map((row,index)=>`<div class="free-member" data-index="${index}"><strong>${esc(row.model_id)}</strong><div class="free-member-roles">${[...'ABCDE'].map(role=>`<label><input type="checkbox" data-role="${role}" ${row.roles.includes(role)?'checked':''}>${role}</label>`).join('')}</div><div><button type="button" data-up="${index}" class="button button-ghost button-small" ${index?'':'disabled'} aria-label="上移模型${index+1}">↑</button><button type="button" data-remove="${index}" class="button button-ghost button-small">移除</button></div></div>`).join(''):'<p class="field-help">尚未选入模型。不会自动替换你的正式模型。</p>';
 }
 function renderChannels(){
  const channels=module.channels;
  $('free-summary').textContent=summary?`${Object.values(statuses).filter(s=>(s.accounts?.enabled||0)>0&&!s.closed).length} / ${channels.length} 渠道已登录 · ${summary?.catalog?.length||0} 个目录模型`:'正在读取渠道与模型…';
  $('free-channel-grid').innerHTML=channels.map(row=>{const state=statuses[row.id],connected=state?.accounts?.enabled>0&&!state?.closed;return `<article class="free-channel" data-connected="${Boolean(connected)}" data-search="${esc([row.name,row.org,row.note].join(' ').toLowerCase())}"><div class="free-channel-top"><span class="free-channel-mark" aria-hidden="true">${esc(row.name.slice(0,2).toUpperCase())}</span><span class="free-state ${connected?'ready':''}">${!state?'读取中':state.closed?'已关闭':connected?'已登录':'待登录'}</span></div><h3>${esc(row.name)}</h3><span class="field-help">${esc(row.org)}</span><p>${esc(row.note)}</p><div class="free-channel-bottom"><div class="free-channel-counts"><span>账号 <b>${state?.accounts?.total??'—'}</b></span><span>模型 <b>${state?Math.max(0,(state.models?.total||0)-(state.models?.disabled||0)):'—'}</b></span></div><button type="button" class="button button-secondary button-small" data-channel="${esc(row.id)}" aria-label="管理${esc(row.name)}账号与额度">管理额度 <span aria-hidden="true">↗</span></button></div></article>`}).join('');
  filterChannels();
  $('free-pool-catalog').innerHTML=(summary?.catalog||[]).filter(x=>x.routable).map(x=>`<option value="${esc(x.id)}">${esc(x.name||x.id)}</option>`).join('');
 }
 async function refresh(refreshModels=false){
  if(!current?.running)return;
  if(!module)module=await import('/static/ofm-channel-card.js');
  renderChannels();
  const [catalog,state,auto]=await Promise.all([
   call(refreshModels?'/refresh':'/summary',refreshModels?'POST':'GET',refreshModels?{}:undefined),
   rpc('provider.status',{providers:module.channels.map(x=>x.id)}),rpc('usage.autoCheckin',{})
  ]);
  summary=catalog;statuses=state.statuses||{};$('free-auto-checkin').checked=auto.autoCheckin?.enabled===true;
  renderChannels();
 }
 async function load(){
  current=await call('/status');$('free-start').hidden=current.running;$('free-active').hidden=!current.running;
  $('free-pool-rule').textContent='免费轮换 → 明确配置的付费备选。'+(current.resource_policy?.fallback_cost_limit_cny===null?'费用不设上限；':current.resource_policy?.fallback_cost_limit_cny!==undefined?'每书每天额外≤20元，预算耗尽后等待恢复；':'费用策略以模型分工中的生效设置为准；')+'额外恢复仍共用每日6次上限。';
  $('free-service-status').textContent=current.running?`独立服务运行中 · ${current.endpoint} · 不依赖 dsh`:'独立服务未启动。点击启动后可在此网页登录账号；不会读取或迁移 dsh 登录态。';
  if(!loaded){members=structuredClone(current.pool_members||[]);renderMembers();const projects=await api('/api/projects');$('free-pool-project').innerHTML='<option value="">选择作品</option>'+projects.map(p=>`<option value="${esc(p.path)}">${esc(p.title||p.name||p.path)}</option>`).join('');loaded=true;}
  await refresh();
 }
 function filterChannels(){const search=$('free-channel-search').value.trim().toLowerCase(),connected=$('free-channel-filter').value==='connected';let count=0;for(const card of $('free-channel-grid').children){card.hidden=!card.dataset.search.includes(search)||(connected&&card.dataset.connected!=='true');if(!card.hidden)count++;}$('free-channel-empty').hidden=count>0||!$('free-channel-detail').hidden;}
 $('free-channel-search').oninput=filterChannels;$('free-channel-filter').onchange=filterChannels;
 tabs.onclick=e=>{const button=e.target.closest('[data-mode]');if(!button)return;const free=button.dataset.mode==='free';for(const tab of tabs.querySelectorAll('button')){tab.setAttribute('aria-selected',String(tab===button));tab.tabIndex=tab===button?0:-1;}moveSlider();panel.hidden=!free;window.NovelProviders?.setView(button.dataset.mode);if(free){act(load)}else{window.NovelProviders?.sync();closeDetail?.();closeDetail=null;$('free-channel-detail').hidden=true;$('free-channel-grid').hidden=false;filters.hidden=false;}};
 tabs.onkeydown=e=>{const buttons=[...tabs.querySelectorAll('[role=tab]')],index=buttons.indexOf(document.activeElement);if(index<0)return;let next;if(e.key==='ArrowRight')next=(index+1)%buttons.length;else if(e.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=buttons.length-1;else return;e.preventDefault();buttons[next].focus();buttons[next].click();};
 $('free-start').onclick=()=>act(async()=>{await call('/start','POST',{});await load()});
 $('free-refresh').onclick=()=>act(()=>refresh(true));
 $('free-auto-checkin').onchange=e=>act(async()=>{try{await rpc('usage.autoCheckin',{enabled:e.target.checked})}catch(reason){e.target.checked=!e.target.checked;throw reason}});
 $('free-channel-grid').onclick=e=>{const button=e.target.closest('[data-channel]');if(!button)return;act(async()=>{closeDetail?.();$('free-channel-grid').hidden=true;$('free-channel-detail').hidden=false;filters.hidden=true;$('free-channel-empty').hidden=true;closeDetail=await module.mount($('free-detail-root'),button.dataset.channel,statuses[button.dataset.channel],()=>{refresh().catch(error)})})};
 $('free-detail-back').onclick=()=>{closeDetail?.();closeDetail=null;$('free-channel-detail').hidden=true;$('free-channel-grid').hidden=false;filters.hidden=false;act(()=>refresh())};
 $('free-pool-add').onclick=()=>{const model=$('free-pool-model').value.trim();if(!summary?.catalog?.some(x=>x.id===model&&x.routable)){error('请先选择当前已列出的模型');return}if(members.some(x=>x.model_id===model))return;members.push({model_id:model,roles:[...'ABCDE'],quota_confirmed:true});$('free-pool-model').value='';renderMembers()};
 $('free-pool-members').onchange=e=>{const row=e.target.closest('[data-index]');if(row)members[Number(row.dataset.index)].roles=[...row.querySelectorAll('[data-role]:checked')].map(x=>x.dataset.role)};
 $('free-pool-members').onclick=e=>{const up=e.target.closest('[data-up]'),remove=e.target.closest('[data-remove]');if(up){const index=Number(up.dataset.up);if(index)[members[index-1],members[index]]=[members[index],members[index-1]]}if(remove)members.splice(Number(remove.dataset.remove),1);if(up||remove)renderMembers()};
 $('free-pool-save').onclick=()=>act(async()=>{if(!$('free-pool-quota').checked||!$('free-pool-privacy').checked)throw Error('请先确认免费额度类型和作品隐私授权');await call('/pool','PUT',{members,project:$('free-pool-project').value,authorize_project:true});window.NovelProviders?.sync();toast('免费池已保存；请在模型分工中选择免费渠道池，当前正式绑定未改动')});
 window.addEventListener('hashchange',()=>{if(location.hash!=='#ai'){closeDetail?.();closeDetail=null;$('free-channel-detail').hidden=true;$('free-channel-grid').hidden=false;filters.hidden=false;}});
})();
