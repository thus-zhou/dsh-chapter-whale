"use strict";
// All text originating in projects, APIs and logs is escaped before rendering.
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const url = encodeURIComponent;
const fmt = (n) => Number(n || 0).toLocaleString("zh-CN");
const time = (s) => s ? new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(s)) : "—";
const statusNames = {queued:"等待执行",running:"执行中",continuing:"继续更新",progress:"本章已完成",configured:"服务已启动",expired:"当天补量已到期",awaiting_login:"等待扫码确认",success:"已完成",failed:"失败",partial:"部分完成",interrupted:"已中断",cancelled:"已取消",cancelling:"取消中",awaiting_approval:"等待日期批准",disabled:"已停用",already_ran:"今日已完成",already_run:"今日已完成",busy:"其他任务运行中",generated:"正文已保存",reviewed:"审查通过",authorized:"E 授权继续",review_failed:"审查未通过"};
function quotaLabel(j) {
 if(j.cycle?.publish_every===10)return `每完成10章发布一批 · 每章至少${fmt(j.cycle.word_count)}字 · 至第${fmt(j.cycle.stop_after_chapter || 100)}章`;
 if(j.cycle?.local_only)return `本地完稿至第${fmt(j.cycle.stop_after_chapter || 100)}章 · 每章至少${fmt(j.cycle.word_count)}字 · 完稿后补发`;
 const day=new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai"}).format(new Date());
 const goal=j.daily_word_goal?.target || (j.cycle?.run_date===day && j.cycle?.word_goal_target);
 if(goal)return `今日目标 ${fmt(goal)} 字 · 每章约 ${fmt(j.word_count)} 字`;
 return j.effective_quota?`今日目标 ${fmt(j.effective_quota.daily_chapters)} 章 · 每章约 ${fmt(j.effective_quota.word_count)} 字`:`基础配额 ${fmt(j.chapters_per_run)} 章/批`;
}
statusNames.waiting="等待自动恢复";
statusNames.local_complete="本地完稿 · 待发布";
statusNames.published_complete="章节已全部发布 · 完结状态待核验";
function operationWait(o) {
 if(o.status!=="waiting")return "";
 const when=o.result?.next_retry_at;
 return `<p class="operation-wait" role="status">保留原批次，${when?`下次恢复 ${esc(time(when))}`:"等待可用模型"}；不重复创建章节。${button("cancel-operation",o.id,"取消等待")}</p>`;
}
function jobProgress(j) {
 const c=j.cycle || {}, r=(c.publication_batch_active?c.batch_recovery:c.local_recovery || c.recovery) || {}, chapter=c.current_chapter?`第${c.current_chapter}章 · `:"";
 if(j.last_status==='published_complete')return '目标章节均已平台正文核验；作品完结审核与收益状态仍需分别确认';
 if(c.local_only && j.last_status==='local_complete')return "本地全稿已完成资格与记忆同步，尚不代表平台已发布或完结审核通过";
 const budget=j.runtime?.recovery_budget,remaining=budget?(budget.limit===null?` · 额外恢复不限次数 · 已用 ${fmt(budget.used)} 次`:` · 共享恢复预算余 ${budget.remaining}/${budget.limit}`):'';
 if(j.last_status==="failed" || (j.last_status!=="running" && r.automatic_retry && !r.resolved && r.next_retry_at)) {
  const action=r.automatic_retry?`自动恢复等待，下次 ${time(r.next_retry_at)}`:"已暂停，需要处理";
  return chapter+action+"："+String(r.message || j.last_message || "请查看运行记录").slice(0,600)+remaining;
 }
 if(j.last_status==="running"){
  const request=j.runtime?.last_request;
  const detail=request?` · 最近模型 ${request.role||''} ${request.model||''}${request.provider_name?' / '+request.provider_name:''} · 请求开始 ${time(request.created_at)}`:'';
  return chapter+(c.publication_batch_active?'正在发布本组或核验已提交章节；不重复提交':c.publish_every===10?'写作、审查与记忆同步；本组满10章后发布':c.local_only?"本地创作、审查与记忆同步；平台发布暂停":c.stage==="publish_started"?"正在提交或等待平台核验；不会重复提交":"正在写作、审查或同步记忆")+detail+remaining;
 }
 if(j.last_message)return String(j.last_message).slice(0,600);
 if(j.last_status==='success' && j.next_due)return `本批次已完成 · 下次开始 ${time(j.next_due)}`;
 return "";
}
const kindNames = {generate:"批量创作",review:"最终审查",polish:"章节润色",learn:"示范学习",plan:"剧情规划",memory:"共享记忆补建",login:"账号登录",stage:"章节入队",publish:"发布章节",daily:"日更任务",ai_test:"连接测试"};
const active = (s) => ["queued","running","awaiting_login","cancelling"].includes(s);
const iconPaths = {
 grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 book:'<path d="M3 4h7l2 2 2-2h7v16h-7l-2 1-2-1H3zM12 6v15"/>',
 users:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M17 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 5"/>',
 calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18M8 15h2M14 15h2"/>',
 send:'<path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/>',
 activity:'<path d="M2 12h5l3-8 4 16 3-8h5"/>',
 spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
 shield:'<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z"/><path d="m8 12 3 3 5-6"/>',
 menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',
 refresh:'<path d="M20 7v5h-5M4 17v-5h5M20 12a8 8 0 0 0-14-5M4 12a8 8 0 0 0 14 5"/>',
 moon:'<path d="M21 14A9 9 0 0 1 10 3a9 9 0 1 0 11 11Z"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
 search:'<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
 layers:'<path d="m12 2 10 5-10 5L2 7zM2 12l10 5 10-5M2 17l10 5 10-5"/>',
 lock:'<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
 close:'<path d="m6 6 12 12M18 6 6 18"/>',check:'<path d="m4 12 5 5L20 6"/>',
 warning:'<path d="m12 3 10 18H2zM12 9v5M12 17h.01"/>',file:'<path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6"/>'
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${iconPaths[name] || iconPaths.file}</svg>`;
function icons(root=document) { root.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML=icon(el.dataset.icon); }); }
function badge(status) { const cls = ["success","reviewed","generated"].includes(status) ? "pill-success" : ["failed","interrupted","review_failed","partial"].includes(status) ? "pill-danger" : "pill-neutral"; return `<span class="pill ${cls}">${esc(statusNames[status] || status || "尚未运行")}</span>`; }
function empty(title, description) { return `<div class="empty-state"><div class="empty-icon">${icon("book")}</div><h3>${esc(title)}</h3><p>${esc(description)}</p></div>`; }
function button(action, id, text, cls="button-secondary", extra="") { return `<button class="button ${cls}" data-action="${action}" data-id="${esc(id)}" ${extra}>${esc(text)}</button>`; }
let state = {projects:[], accounts:[], jobs:[], operations:[], queue:{books:[]}, diagnostics:{checks:[]}, ai:{}, settings:{}};
let loaded=false, syncing=false, aiDirty=false, queueDirty=false, detailId=null, aiConfigRevision=0;
const chapterCache = new Map();
const chapterVersions = new Map();
const expanded = new Set();
const announced = new Map();
const pages = {dashboard:"工作台",projects:"作品管理",creative:"创作工作台",accounts:"发布账号",jobs:"日更任务",queue:"发布队列",logs:"运行日志",ai:"AI 设置",costs:"成本分析",diagnostics:"系统诊断"};
const briefLabels={genre:"题材与基调",audience:"目标读者",premise:"核心故事与卖点",characters:"人物与关系",style:"语言与文风",perspective:"叙事视角",pacing:"剧情节奏与章末钩子",world:"世界观与边界",ending:"主线与结局方向",avoid:"禁止内容与写作雷区",requirements:"其他明确要求"};
let creativeId="", creativeDoc=null, creativeDirty=false, creativeBusy=false, creativeLoading=false;
let modelFormRevision=0, creativeAutoAttempted=false, rolesDirty=false, studioTab="brief", modelOptions=[], rolesSignature="", studioSignature="";
const roleLabels={A:["规划","总纲 · 弧线 · 伏笔 · 示范分析"],B:["初稿","按章节细纲生成正文"],C:["润色","重点章 · 对话 · 去 AI 腔"],D:["审查","设定 · 成长 · 伏笔回收"],E:["执行","沟通 · 决策 · 调度 · 发布工具"]};
const projectById = id => state.projects.find(p=>p.id===id);
const jobById = id => state.jobs.find(p=>p.id===id);

async function api(path, method="GET", data, timeout=20000) {
 const controller = new AbortController(); const timer=setTimeout(()=>controller.abort(),timeout);
 try {
  const response=await fetch(path,{method,signal:controller.signal,headers:{...(method!=="GET" ? {"X-Novel-Helper":"1","Content-Type":"application/json"}: {})},...(data!==undefined ? {body:JSON.stringify(data)}:{})});
  const payload=await response.json();
  if(response.status===401) {location.assign('/pair'); throw new Error('设备登录已失效，请重新配对');}
  if(!response.ok) { const detail=payload.detail; throw new Error(typeof detail==="string" ? detail : Array.isArray(detail) ? detail.map(x=>`${x.loc?.slice(1).join(" / ")}: ${x.msg}`).join("；") : "请求失败"); }
  return payload;
 } catch(error) { if(error.name==="AbortError") throw new Error("请求超时，请检查本地服务和运行日志"); throw error; }
 finally { clearTimeout(timer); }
}
function toast(message, error=false) {
 if(error && $("action-dialog").open) {
  let alert=$("modal-error");
  if(!alert){alert=document.createElement("div");alert.id="modal-error";alert.className="error-inline";alert.setAttribute("role","alert");$("dialog-body").prepend(alert);}
  alert.textContent=message;
 }
 const el=document.createElement("div"); el.className=`toast${error?" error":""}`;
 el.innerHTML=`${icon(error?"warning":"check")}<div>${esc(message)}</div><button class="icon-button" aria-label="关闭提示">${icon("close")}</button>`;
 el.querySelector("button").onclick=()=>el.remove();while($("toasts").children.length>=2)$("toasts").firstElementChild.remove();$("toasts").append(el); setTimeout(()=>el.remove(),error?12000:6500);
}
async function busy(el, fn) { const previous=el?.disabled; if(el)el.disabled=true; try { return await fn(); } catch(e){toast(e.message,true);} finally{if(el && el.isConnected) el.disabled=previous;} }
function operationStarted(op) { toast("操作已启动，可在运行日志中查看进度"); announced.set(op.id,op.status); refresh(); }
function route() {
 const key=location.hash.slice(1).split("/")[0] || "dashboard";
 const current=pages[key]?key:"dashboard";
 document.querySelectorAll(".page").forEach(p=>p.hidden=p.id!==`page-${current}`);
 document.querySelectorAll("[data-page]").forEach(p=>{p.classList.toggle("active",p.dataset.page===current); if(p.dataset.page===current)p.setAttribute("aria-current","page");else p.removeAttribute("aria-current");});
 $("breadcrumb-page").textContent=pages[current]; menu(false);
 if(current==="creative")renderCreativeNavigation();
 if(current==="costs")window.NovelCosts?.load();
}
function menu(open) { $("sidebar").classList.toggle("open",open); $("sidebar-backdrop").hidden=!open; $("menu-toggle").setAttribute("aria-expanded",String(open)); }
function stat(label, value, description, symbol) {return `<div class="stat-card"><div class="stat-label">${icon(symbol)} ${esc(label)}</div><div class="stat-value">${esc(value)}</div><div class="stat-detail">${esc(description)}</div></div>`;}
function projectRow(p) { return `<div class="list-row"><span class="row-icon">${icon("book")}</span><div class="row-content"><h3>${esc(p.title)}</h3><p>${esc(p.genre)} · ${fmt(p.chapters)} 章</p></div>${button("chapters",p.id,"查看")}</div>`; }
function operationRow(o) {return `<div class="operation-row"><div class="row-icon">${icon(o.kind==="publish"?"send":"activity")}</div><div class="row-content"><h3>${esc(kindNames[o.kind] || o.kind)}</h3><p>${time(o.created_at)} <span>${esc(o.book || o.account || o.id.slice(0,8))}</span>${o.status==="waiting" && o.result?.next_retry_at?`<span>下次恢复 ${esc(time(o.result.next_retry_at))}</span>`:""}</p></div>${badge(o.status)}${button("operation",o.id,"详情")}</div>`;}
function chapterRows(id) {
 const items=chapterCache.get(id); if(!items)return `<div class="loading-text">正在读取章节…</div>`;
 if(items.error)return `<div class="error-inline">${esc(items.error)}</div>`;
 if(!items.length)return `<div class="loading-text">尚无正文。请先完善大纲，然后生成第一章。</div>`;
 return `<div class="chapter-table">${items.map(c=>`<div class="chapter-row"><div><strong>第 ${fmt(c.id)} 章 · ${esc(c.title || "无标题")}</strong><small>${fmt(c.words)} 字 · ${c.reviewed?(c.review_status==="waived_by_author_rule"?"按作者规则免审":c.review_status==="waived_by_E"?"E 授权继续":"审查通过"):"待处理"}</small></div><div class="chapter-actions">${button("preview",id,"查看","button-secondary",`data-chapter="${c.id}"`)}</div></div>`).join("")}</div>`;
}
function renderProjects() {
 const query=$("project-search").value.trim().toLowerCase();
 const items=state.projects.filter(p=>`${p.title} ${p.genre} ${p.path}`.toLowerCase().includes(query));
 $("projects-count").textContent=`${items.length} 部作品`;
 $("projects-list").innerHTML=items.length?items.map(p=>`<article class="project-card"><div class="project-main"><div class="project-top"><span class="pill pill-neutral">${esc(p.genre)}</span><span class="muted">${p.ready?"大纲已就绪":"待完善大纲"}</span></div><h2 class="project-title">${esc(p.title)}</h2><p class="project-path">${esc(p.path)}</p>${p.error?`<p class="error-inline">${esc(p.error)}</p>`:""}<div class="project-metrics"><span><strong>${fmt(p.chapters)}</strong> 章</span><span><strong>${fmt(p.words)}</strong> 字</span><span>${fmt(p.outline_count)} 份大纲</span></div><div class="form-actions">${button("creative",p.id,"创作沟通")}${button("chapters",p.id,expanded.has(p.id)?"收起章节":"章节书架")}${button("outline",p.id,"编辑大纲")}${button("generate",p.id,"生成下一章","button-primary")}</div></div><div id="chapters-${esc(p.id)}" class="project-chapters" ${expanded.has(p.id)?"":"hidden"}>${expanded.has(p.id)?chapterRows(p.id):""}</div></article>`).join(""):empty(query?"没有匹配的作品":"你的书架，等待第一个故事","可以创建一个作品，也可以登记已有写作项目。","create-project","新建作品");
}

function renderCreativeNavigation(){
 const select=$("creative-project"), previous=select.value;
 const markup=options(state.projects,"id","title","请选择作品");
 if(select.innerHTML!==markup){select.innerHTML=markup;select.value=creativeId || previous;}
 select.disabled=creativeBusy || creativeLoading;
 if(location.hash==="#creative" && !creativeId && state.projects.length && !creativeLoading && !creativeAutoAttempted){creativeAutoAttempted=true;loadCreative(state.projects[0].id).catch(e=>toast(e.message,true));}
 $("creative-empty").hidden=!!creativeDoc;$("creative-workspace").hidden=!creativeDoc;
}
function renderCreativeDocument(){
 if(!creativeDoc)return;
 const hints={premise:"主角想获得什么？主要冲突是什么？故事最独特的卖点是什么？",style:"例如：简洁、克制、有画面感，少形容词，不用说教式旁白。",characters:"主角身份、目标、弱点；重要人物与关系；不能随意改变的人设。",avoid:"例如：禁止无脑降智、重复上一章、强行误会、突然开挂。"};
 const field=([key,label])=>`<label class="${["premise","characters","world","style","avoid","requirements"].includes(key)?"full":""}">${esc(label)}<textarea name="${key}" maxlength="3000" rows="${key==="characters"?3:2}" placeholder="${esc(hints[key] || "可留空，与 AI 一起明确")}">${esc(creativeDoc.brief[key] || "")}</textarea></label>`;
 const basic=["genre","perspective","premise","characters","style"];
 $("brief-fields").innerHTML=Object.entries(briefLabels).filter(([k])=>basic.includes(k)).map(field).join("")+`<details class="quiet-details full brief-advanced"><summary>更多创作要求</summary><div class="form-grid">${Object.entries(briefLabels).filter(([k])=>!basic.includes(k)).map(field).join("")}</div></details>`;
 $("creative-save-state").textContent=Object.values(creativeDoc.brief).some(Boolean)?"已保存，写作时生效":"尚未填写约定";
 $("creative-save-state").className="pill pill-neutral";
 $("creative-messages").innerHTML=creativeDoc.history.length?creativeDoc.history.map(m=>`<div class="chat-message ${m.role=== "user"?"chat-user":"chat-assistant"}"><small>${m.role==="user"?"你":"策划搭档"}</small><div>${esc(m.content)}</div></div>`).join(""):`<div class="chat-welcome"><span>${icon("spark")}</span><h3>一段对话，勾勒一个世界。</h3><p>告诉 AI 你的想法，让它追问细节、梳理人物与主线。也可以直接填写左侧约定。</p></div>`;
 const last=creativeDoc.history.at(-1);
 const proposal=creativeDoc.proposal || (last?.proposal_applied?{}:last?.proposal) || {};
 $("creative-proposal").hidden=!Object.keys(proposal).length;
 $("creative-proposal").innerHTML=Object.keys(proposal).length?`<h3>AI 建议 · 尚未生效</h3><dl>${Object.entries(proposal).map(([key,value])=>`<dt>${esc(briefLabels[key] || key)}</dt><dd>${esc(value || "（清空此项）")}</dd>`).join("")}</dl><button class="button button-secondary" data-action="apply-creative">采用并保存这份建议</button><p class="field-help">将更新建议列出的字段，其他已确认要求保持不变；不会改写大纲和正文。</p>`:"";
 icons($("creative-workspace"));$("creative-messages").scrollTop=$("creative-messages").scrollHeight;
 const learning=creativeDoc.learning;
 $("learning-guide-panel").hidden=!learning?.guide;
 $("learning-guide").textContent=learning?.guide || "";
 $("learning-coverage").textContent=learning?`${learning.mode==="full"?"逐段":"代表段落"} · ${learning.segments} 段`:"";
}
async function loadCreative(id){
 if(creativeBusy || creativeLoading)throw new Error("请等待当前创作沟通完成");
 if(!id){$("creative-project").value=creativeId;return;}
 if(creativeDirty && !confirm("有尚未保存的创作约定。放弃这些修改并载入？")){ $("creative-project").value=creativeId;return; }
 creativeLoading=true;creativeLock(true);
 try{const doc=await api(`/api/projects/${url(id)}/creative`);creativeId=id;creativeDoc=doc;creativeDirty=false;$("creative-project").value=id;renderCreativeDocument();await loadStudio();}
 finally{creativeLoading=false;creativeLock(false);renderCreativeNavigation();}
}
function creativeLock(value){
 creativeBusy=value;$("creative-project").disabled=value;
 for(const el of $("creative-workspace").querySelectorAll("button,input,textarea"))el.disabled=value;
}

function setStudioTab(tab){
 studioTab=tab;
 for(const key of ["brief","learning","planning","memory"]){$("studio-"+key).hidden=key!==tab;const button=document.querySelector(`[data-studio-tab="${key}"]`);button.setAttribute("aria-selected",String(key===tab));button.tabIndex=key===tab?0:-1;}
 if(tab==="memory" && creativeId && window.NovelMemory)window.NovelMemory.load(creativeId).catch(e=>toast(e.message,true));
}
async function loadStudio(){
 if(!creativeId)return;
 const id=creativeId;const [samples,plan]=await Promise.all([api(`/api/projects/${url(id)}/samples`),api(`/api/projects/${url(id)}/plan`)]);
 if(window.NovelMemory && (studioTab==="memory" || window.NovelMemory.project!==id))await window.NovelMemory.load(id);
 if(id!==creativeId)return;
 const signature=JSON.stringify({id,samples,plan});if(studioSignature===signature)return;studioSignature=signature;
 const names={uploaded:"待分析",analyzing:"分析中",learned:"已学习",failed:"可继续分析"};
 $("samples-list").innerHTML=samples.map(s=>`<div class="sample-row"><div><strong>${esc(s.name)}</strong><small>${fmt(s.characters)} 字${s.total_segments?` · ${s.analyzed_segments || 0}/${s.total_segments} 段`:""}</small></div><span class="pill ${s.status==="learned"?"pill-success":"pill-neutral"}">${esc(names[s.status] || s.status)}</span>${["failed","uploaded"].includes(s.status)?button("learn-sample",s.id,"继续","button-small",`data-full="${s.mode==="full"?1:0}"`):""}</div>`).join("");
 $("story-plan").innerHTML=plan.master_outline?`<details open><summary>总大纲</summary><pre>${esc(plan.master_outline)}</pre></details>`+[ ["volumes","分卷剧情"],["character_arcs","人物弧线"],["foreshadowing","核心伏笔"]].map(([key,title])=>`<details><summary>${title}</summary><pre>${esc(plan[key] || "")}</pre></details>`).join("")+`<div class="planned-chapters">${Object.values(plan.chapters || {}).sort((a,b)=>a.id-b.id).map(c=>`<details><summary>第${fmt(c.id)}章 ${esc(c.title)}${c.key_scene?'<span class="pill pill-neutral">重点章</span>':""}</summary><pre>${esc(c.outline)}</pre></details>`).join("")}</div>`:`<div class="loading-text">还没有 AI 规划。已有手工细纲可直接用于创作。</div>`;
}
function renderRoles(){
 if(rolesDirty)return;
 const signature=JSON.stringify({roles:state.ai.roles,multi:state.ai.multi_model,polish:state.ai.polish_mode,policy:state.ai.review_policy});
 if(signature===rolesSignature){updateRoleOptions();return;}rolesSignature=signature;
 $("multi-model").checked=!!state.ai.multi_model;$("polish-mode").value=state.ai.polish_mode || "key";
 $("review-policy").value=state.ai.review_policy || "e_decides";
 $("role-fields").innerHTML=Object.entries(roleLabels).map(([role,[label,description]])=>{const saved=state.ai.roles?.[role] || {};return `<div class="role-card"><div class="role-heading"><span class="role-letter">${role}</span><div><h3>${label}</h3><small>${description}</small></div></div><label><span class="sr-only">模型 ${role}</span><input name="${role}-model" value="${esc(saved.model || "")}" list="role-model-options" placeholder="选择模型，留空继承通用配置" maxlength="200"></label><details class="quiet-details"><summary>单独连接</summary><label>API 地址<input name="${role}-base_url" type="url" value="${esc(saved.base_url || "")}" placeholder="留空使用通用地址"></label><label>API Key<input name="${role}-api_key" type="password" autocomplete="new-password" placeholder="${saved.key_masked?"留空保留已保存密钥":"留空继承同一接口密钥"}"></label><button type="button" class="button button-secondary button-small" data-action="scan-role" data-id="${role}">读取此接口模型</button></details></div>`;}).join("");
 updateRoleOptions();
}
function updateRoleOptions(){
 const ids=[...new Set([...modelOptions,state.ai.model,...Object.values(state.ai.roles || {}).map(r=>r.model)].filter(Boolean))];
 $("role-model-options").innerHTML=ids.map(id=>`<option value="${esc(id)}"></option>`).join("");
}
async function saveBrief(brief){
 creativeDoc=await api(`/api/projects/${url(creativeId)}/creative`,"PUT",{brief,revision:creativeDoc.revision});
 creativeDirty=false;renderCreativeDocument();toast("创作约定已保存，下次写作与审查时生效");
}
function renderAccounts() {
 $("accounts-list").innerHTML=state.accounts.length?state.accounts.map(a=>`<article class="account-card"><div class="account-heading"><span class="account-avatar">${esc(a.name.slice(0,1))}</span><div><h2>${esc(a.name)}</h2><p>${a.logged_in?"已保存登录状态 · 有效性以平台检查为准":"尚未保存登录状态"}</p></div>${badge(a.login_operation?.status || (a.logged_in?"success":"disabled"))}</div><p class="project-path">${esc(a.state_file)}</p><div class="form-actions">${button("login",a.name,"启动登录")}${a.login_operation?.status==="awaiting_login"?button("confirm-login",a.name,"已完成扫码，确认登录","button-primary"):""}${a.login_operation?button("operation",a.login_operation.id,"查看登录进度"):""}</div></article>`).join(""):empty("先添加一个发布账号","每个账号独立保存登录状态。登录窗口需要你完成扫码。","login","添加账号");
}
function renderJobs() {
 const enabled=!!state.settings.scheduler_enabled; $("scheduler-enabled").disabled=false; $("scheduler-enabled").checked=enabled;
 $("scheduler-label").textContent=enabled?"已开启":"已暂停"; $("scheduler-description").textContent=enabled?"管理服务运行期间，按各任务设置的时区执行。":"自动调度已暂停。可以先试运行，再开启日更计划。";
 $("jobs-list").innerHTML=state.jobs.length?state.jobs.map(j=>`<article class="job-card"><div class="job-head"><div><span class="eyebrow">${esc((j.daily_times?.length?j.daily_times:[j.daily_time]).join(" / "))} · ${esc(j.timezone)}</span><h2>${esc(j.name)}</h2></div>${badge(j.last_status || (j.enabled?"queued":"disabled"))}</div><div class="job-meta"><span>${esc(j.book)}</span><span>${esc(j.account)}</span><span>${quotaLabel(j)}</span><span>全自动 · 自动核验</span></div>${jobProgress(j)?`<p class="field-help" role="status">${esc(jobProgress(j))}</p>`:""}<div class="job-actions form-actions">${button("edit-job",j.id,"编辑")}${button("toggle-job",j.id,j.enabled?"暂停":"启用")}${button("run-job",j.id,"立即执行","button-primary",j.enabled?"":"disabled")}</div></article>`).join(""):empty("安排一个更新时刻","选择作品与账号，设定每天的时间和频率。","new-job","创建日更任务");
}
function options(items, valueKey, labelKey, placeholder) { return `<option value="">${esc(placeholder)}</option>${items.map(x=>`<option value="${esc(x[valueKey])}">${esc(x[labelKey])}</option>`).join("")}`; }
function renderQueue() {
 const q=state.queue; $("queue-stats").innerHTML=stat("待发章节",fmt(q.queued),"已准备的本地发布队列","layers")+stat("已核验归档",fmt(q.published),"具备发布回执的归档章节","check")+stat("待核验旧归档",fmt(q.archive_unverified),"旧归档不会自动当作已发布","info");
 $("queue-list").innerHTML=q.books?.length?q.books.map(b=>`<div class="queue-book-row"><h3>${esc(b.book)}</h3><p class="project-path">${esc(b.folder)}</p><div class="queue-numbers"><span>待发 <strong>${fmt(b.queued)}</strong></span><span>已核验 <strong>${fmt(b.published)}</strong></span><span>待核验 ${fmt(b.archive_unverified)}</span></div></div>`).join(""):empty("发布队列还是空的","先生成或审查一章正文，再加入发布队列。");
 for(const [id,items,key,label,placeholder] of [["queue-project",state.projects,"id","title","请选择作品"],["queue-account",state.accounts.filter(a=>a.logged_in),"name","name","请选择已登录账号"]]){
  const el=$(id),old=el.value, html=options(items,key,label,placeholder);
  if(document.activeElement!==el && el.innerHTML!==html){el.innerHTML=html;el.value=old;}
 }
}
function renderLogs() {
 const text=$("log-search").value.toLowerCase(), filter=$("log-status").value;
 const items=state.operations.filter(o=>`${kindNames[o.kind]} ${o.id} ${o.book || ""}`.toLowerCase().includes(text)).filter(o=>!filter || filter==="active"&&active(o.status) || filter==="success"&&o.status==="success" || filter==="failure"&&["failed","interrupted","partial"].includes(o.status));
 $("operations-list").innerHTML=items.length?items.map(operationRow).join(""):empty("目前没有运行记录","生成、登录与发布的过程会保存在这里。");
}
function renderDiagnostics() {
 const d=state.diagnostics;
 $("diagnostics-summary").innerHTML=`<div class="diagnostics-banner ${d.ready?"":"issue"}">${icon(d.ready?"check":"info")}<div><h2>${d.ready?"环境已准备，先做单章试运行":"还有准备工作需要完成"}</h2><p>${d.ready?"真实平台发布需要目标作品与有效账号。":"查看下面的检查项，补齐配置后再开始写作与发布。"}</p></div></div>`;
 $("diagnostics-list").innerHTML=(d.checks || []).map(c=>`<div class="check-row ${c.ok?"":"failed"}">${icon(c.ok?"check":"warning")}<div><h3>${esc(c.name)}</h3><p>${esc(c.detail)}</p></div><span class="pill ${c.ok?"pill-success":"pill-neutral"}">${c.ok?"就绪":"待处理"}</span></div>`).join("");
}
function render() {
 const q=state.queue; $("nav-queue").textContent=fmt(q.queued);
 $("dashboard-stats").innerHTML=stat("创作作品",fmt(state.projects.length),"从大纲到正文","book")+stat("正文总字数",fmt(state.projects.reduce((n,p)=>n+Number(p.words || 0),0)),"本地正文的字符统计","file")+stat("待发布章节",fmt(q.queued),"经审查后进入队列","send")+stat("正在运行",fmt(state.operations.filter(o=>active(o.status)).length),"每个步骤都有记录","activity");
 $("dashboard-projects").innerHTML=state.projects.length?state.projects.slice(0,3).map(projectRow).join(""):empty("第一本书，还在酝酿中","用一份大纲开始你的故事。","create-project","新建作品");
 $("dashboard-jobs").innerHTML=state.jobs.length?state.jobs.slice(0,3).map(j=>`<div class="list-row"><span class="row-icon">${icon("clock")}</span><div class="row-content"><h3>${esc(j.name)}</h3><p>${esc(j.daily_time)} · ${esc(j.book)} · ${j.enabled?"已启用":"暂停中"}</p></div></div>`).join(""):empty("为下一章，留一个时刻","首次试发通过后，再安排日更。","new-job","创建日更");
 $("dashboard-operations").innerHTML=state.operations.length?state.operations.slice(0,4).map(operationRow).join(""):empty("创作旅程，马上开始","你的第一条运行记录会出现在这里。");
 renderProjects();renderAccounts();renderJobs();renderQueue();renderLogs();renderDiagnostics();renderCreativeNavigation();renderRoles();
 if(!aiDirty) { $("ai-base-url").value=state.ai.base_url || ""; $("ai-model").value=state.ai.model || ""; }
 $("ai-status").textContent=state.ai.configured?"已保存配置":"尚未配置";
 $("ai-status").className=`pill ${state.ai.configured?"pill-success":"pill-neutral"}`;
 $("ai-key-hint").textContent=state.ai.configured?"已保存密钥：••••••••。留空保持现有密钥。":"尚未保存密钥。请输入 API Key 后保存。";
 icons();
}
async function refresh() {
 if(syncing)return; syncing=true;
 const aiRevision=aiConfigRevision;
 try { const next=await api("/api/overview"); if(aiRevision!==aiConfigRevision)next.ai=state.ai; state={...state,...next}; render();
  $("connection-text").textContent="创作服务已连接"; $("connection-dot").classList.add("online"); $("connection-banner").hidden=true;
  $("sync-label").textContent=`已同步 ${new Date().toLocaleTimeString("zh-CN",{timeZone:"Asia/Shanghai",hour:"2-digit",minute:"2-digit"})}`;
  let chapterChanged=false,studioChanged=false;
  if(loaded) for(const o of state.operations){const prev=announced.get(o.id);if(prev && active(prev)&&!active(o.status)){toast(`${kindNames[o.kind] || o.kind}：${statusNames[o.status] || o.status}`,o.status==="failed");if(["generate","review","polish"].includes(o.kind))chapterChanged=true;if(["learn","plan"].includes(o.kind) && o.project_id===creativeId)studioChanged=true;}announced.set(o.id,o.status);}
  else state.operations.forEach(o=>announced.set(o.id,o.status));
  loaded=true;
  window.NovelCosts?.sync();
  if(chapterChanged){chapterCache.clear();for(const id of expanded)await loadChapters(id);}
  for(const id of expanded){const p=state.projects.find(x=>x.id===id);if(p&&(chapterCache.get(id)?.length!==p.chapters||chapterVersions.get(id)!==p.chapters_revision)){await loadChapters(id);chapterVersions.set(id,p.chapters_revision);}}
  window.NovelProviders?.sync();
  if(studioChanged && creativeId && !creativeDirty && !creativeBusy && !creativeLoading)await loadCreative(creativeId);
  else if(creativeId && !creativeBusy && !creativeLoading)await loadStudio();
  if(detailId && $("operation-dialog").open) await showOperation(detailId,false);
 } catch(error) {$("connection-text").textContent="连接需要检查";$("connection-banner").textContent=error.message;$("connection-banner").hidden=false;$("connection-dot").classList.remove("online");}
 finally{syncing=false;}
}
function openDialog(title, content, onSubmit) {
 $("dialog-title").textContent=title; $("dialog-body").innerHTML=content;
 const d=$("action-dialog"); if(!d.open)d.showModal(); document.body.classList.add("modal-open"); icons(d);
 const form=d.querySelector("form"); if(form && onSubmit) form.onsubmit=e=>{e.preventDefault();busy(form.querySelector('[type="submit"]'),async()=>{if(!form.reportValidity())return; await onSubmit(new FormData(form),form);});};
}
function closeDialog(){ $("action-dialog").close(); if(!$("operation-dialog").open) document.body.classList.remove("modal-open"); }
const formEnd=(label="保存")=>`<div class="form-actions"><button type="button" class="button button-secondary" data-action="close-dialog">取消</button><button type="submit" class="button button-primary">${label}</button></div></form>`;
function loginDialog(name="") {openDialog("添加 / 登录发布账号",`<form class="dialog-form"><p class="dialog-description">在新浏览器窗口中扫码登录。完成后返回发布账号页，确认登录状态。</p><label>账号名称<input name="name" maxlength="96" value="${esc(name)}" required placeholder="例如：主账号"></label>${formEnd("启动登录")}`,async data=>{const op=await api("/api/accounts/login","POST",{name:data.get("name").trim()});closeDialog();location.hash="accounts";operationStarted(op);});}
async function loadChapters(id) {try {const result=await api(`/api/projects/${url(id)}/chapters`);chapterCache.set(id,result.chapters);}catch(e){chapterCache.set(id,{error:e.message});} const el=$(`chapters-${id}`);if(el)el.innerHTML=chapterRows(id);}
async function showOperation(id, open=true) {
 const o=await api(`/api/operations/${url(id)}`); detailId=id;
 $("operation-title").textContent=kindNames[o.kind] || "操作详情";
 $("operation-detail").innerHTML=`<div class="operation-summary">${badge(o.status)}${operationWait(o)}<dl class="detail-grid"><dt>开始时间</dt><dd>${time(o.created_at)}</dd><dt>结束时间</dt><dd>${time(o.finished_at)}</dd><dt>操作编号</dt><dd>${esc(o.id)}</dd></dl>${o.error && o.status!=="waiting"?`<p class="operation-error">${esc(o.error)}</p>`:""}${["failed","interrupted","cancelled"].includes(o.status) && o.batch_id && o.project_id?button("resume-batch",o.project_id,"继续原批次","button-primary",`data-batch="${esc(o.batch_id)}"`):""}<div class="log-title">运行日志${active(o.status)?button("cancel-operation",o.id,"取消操作"):""}</div><pre class="log-box">${esc(o.log_tail || "等待运行日志…")}</pre>${o.result?`<details class="quiet-details"><summary>执行结果</summary><pre class="operation-result">${esc(JSON.stringify(o.result,null,2))}</pre></details>`:""}</div>`;
 if(open && !$("operation-dialog").open){$("operation-dialog").showModal();document.body.classList.add("modal-open");}
}
function jobDialog(job=null) {
 if(!state.projects.length){toast("请先新建或登记作品",true);return;}
 if(!state.accounts.some(a=>a.logged_in)){toast("请先在发布账号页完成登录",true);return;}
 const j=job || {name:"日更任务",daily_time:"08:00",timezone:"Asia/Shanghai",chapters_per_run:1,word_count:3500,max_revisions:2,approval_mode:"unattended",enabled:false};
 openDialog(job?"编辑日更":"安排日更",`<form class="dialog-form"><div class="form-grid"><label class="full">任务名称<input name="name" value="${esc(j.name)}" required maxlength="96"></label><label class="full">作品<select name="project" required>${options(state.projects,"path","title","请选择作品")}</select></label><label class="full">番茄书名<input name="book" value="${esc(j.book || "")}" required maxlength="96"></label><label class="full">账号<select name="account" required>${options(state.accounts.filter(a=>a.logged_in),"name","name","请选择账号")}</select></label><label class="full">每日更新时间<input name="daily_times_text" value="${esc((j.daily_times?.length?j.daily_times:[j.daily_time]).join(", "))}" required placeholder="08:00, 18:00"><small>逗号分隔，最多 8 个时间点；每个时段独立计数。</small></label><label>每次章节数<input type="number" name="chapters_per_run" min="1" max="50" value="${j.chapters_per_run}" required></label><label>每章字数<input type="number" name="word_count" min="500" max="10000" value="${j.word_count}" required></label><label>时区<input name="timezone" value="${esc(j.timezone)}" required></label><label>修订轮数<input type="number" name="max_revisions" min="0" max="5" value="${j.max_revisions ?? 2}" required></label><input type="hidden" name="approval_mode" value="unattended"><p class="field-help full">自动写作、审查、同步记忆、发布并核验，无需逐章或按日期批准。</p><label class="check-label full"><input type="checkbox" name="enabled" ${j.enabled?"checked":""}>启用任务</label></div>${formEnd()}`,async(data,form)=>{const payload=Object.fromEntries(data);payload.daily_times=payload.daily_times_text.split(/[,，、\s]+/).filter(Boolean);delete payload.daily_times_text;payload.daily_time=payload.daily_times[0];for(const key of ["word_count","chapters_per_run","max_revisions"])payload[key]=Number(payload[key]);payload.enabled=form.elements.enabled.checked;await api(job?`/api/jobs/${url(job.id)}`:"/api/jobs",job?"PUT":"POST",payload);closeDialog();toast("日更已保存");await refresh();});
 const form=$("action-dialog").querySelector("form");form.elements.project.value=j.project || "";form.elements.account.value=j.account || "";form.elements.approval_mode.value="unattended";
 form.elements.project.onchange=()=>{const p=state.projects.find(p=>p.path===form.elements.project.value);if(p && !form.elements.book.value)form.elements.book.value=p.title;};
}
function queuePayload() {const form=$("queue-form");return {project_id:form.elements.project_id.value,book:form.elements.book.value.trim(),account:form.elements.account.value,count:Number(form.elements.count.value),ai_used:true};}
const actions = {
 "close-dialog":()=>closeDialog(),
 "close-operation":()=>{$("operation-dialog").close();detailId=null;if(!$("action-dialog").open)document.body.classList.remove("modal-open");},
 "create-project":()=>openDialog("给新故事，一个名字",`<form class="dialog-form"><label>作品名称<input name="title" required maxlength="90" placeholder="你的下一本小说"></label><label>题材<input name="genre" value="玄幻" required maxlength="90"></label><label>第一卷大纲 <span class="label-note">可先留空</span><textarea name="outline" placeholder="## 第1章 初见&#10;本章目标、冲突与结尾钩子。&#10;&#10;## 第2章 夜雨&#10;下一章的情节。"></textarea></label><p class="field-help">作品保存在 O 盘 books 目录。可先到“创作沟通”商量怎么写，再补上含明确章节号的大纲。</p>${formEnd("创建作品")}`,async data=>{const project=await api("/api/projects/create","POST",Object.fromEntries(data));closeDialog();toast("作品已创建，可以开始沟通");await refresh();location.hash="creative";await loadCreative(project.id);}),
 "register-project":()=>openDialog("登记已有写作项目",`<form class="dialog-form"><label>项目绝对路径<input name="path" required placeholder="O:\\我的小说项目"></label><p class="field-help">项目应包含 .webnovel/state.json、正文和大纲目录。登记不会覆盖原文件。</p>${formEnd("登记作品")}`,async data=>{await api("/api/projects","POST",{path:data.get("path").trim()});closeDialog();toast("作品已登记");location.hash="projects";await refresh();}),
 "login":el=>loginDialog(el.dataset.id || ""),
 "confirm-login":async el=>{operationStarted(await api(`/api/accounts/${url(el.dataset.id)}/confirm-login`,"POST",{}));},
 "chapters":async el=>{const id=el.dataset.id;location.hash="projects";if(expanded.has(id))expanded.delete(id);else expanded.add(id);renderProjects();if(expanded.has(id))await loadChapters(id);},
 "preview":async el=>{const c=await api(`/api/projects/${url(el.dataset.id)}/chapters/${el.dataset.chapter}`);openDialog(`第${c.id}章 · ${c.title || "正文"}`,`<div class="dialog-content"><div class="form-actions">${button("review",el.dataset.id,"最终审查","button-secondary",`data-chapter="${c.id}"`)}${button("polish-chapter",el.dataset.id,"润色并审查","button-primary",`data-chapter="${c.id}"`)}</div></div><pre class="chapter-preview">${esc(c.content)}</pre>`);},
 "review":async el=>{operationStarted(await api(`/api/projects/${url(el.dataset.id)}/chapters/${el.dataset.chapter}/review`,"POST",{}));},
 "outline":async el=>{const id=el.dataset.id;const outline=await api(`/api/projects/${url(id)}/outline`);openDialog("故事的大纲",`<form class="dialog-form"><p class="field-help">${outline.editable?"保存前会自动备份原大纲。":"此项目有多份大纲。这里只读展示，请按卷编辑原文件。"}</p><textarea name="content" ${outline.editable?"":"readonly"}>${esc(outline.content)}</textarea>${outline.editable?formEnd("保存大纲"):'</form>'}`,outline.editable?async data=>{await api(`/api/projects/${url(id)}/outline`,"PUT",{content:data.get("content")});closeDialog();toast("大纲已保存，原稿已备份");await refresh();}:null);},
 "generate":el=>{const id=el.dataset.id;openDialog("开始创作",`<form class="dialog-form"><p class="dialog-description">${esc(projectById(id)?.title)}</p><div class="pipeline-strip">${Object.entries(roleLabels).slice(0,4).map(([r,[label]])=>`<span><b>${r}</b>${label}</span>`).join("")}</div><div class="form-grid"><label>本次章节数<input type="number" name="count" value="1" min="1" max="30" required></label><label>每章目标字数<input type="number" name="word_count" value="3500" min="500" max="10000" required></label></div><details class="quiet-details"><summary>高级设置</summary><label>最多修订轮数<input type="number" name="max_revisions" value="2" min="0" max="5" required></label></details><p class="field-help">D 通过或 E 明确授权后保存，不立即发布。多模型启用后，缺少细纲时由 A 补齐。</p>${formEnd("开始创作")}`,async data=>{operationStarted(await api(`/api/projects/${url(id)}/generate`,"POST",{count:Number(data.get("count")),word_count:Number(data.get("word_count")),max_revisions:Number(data.get("max_revisions"))}));closeDialog();});},
 "studio-generate":()=>{if(!creativeId)throw new Error("请先选择作品");return actions.generate({dataset:{id:creativeId}});},
 "studio-outline":()=>{if(!creativeId)throw new Error("请先选择作品");return actions.outline({dataset:{id:creativeId}});},
 "polish-chapter":async el=>{const op=await api(`/api/projects/${url(el.dataset.id)}/chapters/${el.dataset.chapter}/polish`,"POST",{});closeDialog();operationStarted(op);},
 "resume-batch":async el=>{const op=await api(`/api/projects/${url(el.dataset.id)}/batches/${url(el.dataset.batch)}/resume`,"POST",{});$("operation-dialog").close();detailId=null;document.body.classList.remove("modal-open");operationStarted(op);},
 "new-job":()=>jobDialog(),"edit-job":el=>jobDialog(jobById(el.dataset.id)),
 "toggle-job":async el=>{const j=jobById(el.dataset.id);await api(`/api/jobs/${url(j.id)}`,"PUT",{...j,enabled:!j.enabled});toast(j.enabled?"任务已暂停":"任务已启用");await refresh();},
 "run-job":async el=>operationStarted(await api(`/api/jobs/${url(el.dataset.id)}/run`,"POST",{})),
 "recover-job":async el=>{const r=await api(`/api/jobs/${url(el.dataset.id)}/recover`,"POST",{});toast(r.applied?"已确认本章尚未提交，批次已恢复；稍后自动重试":(r.detail||r.status||"无需恢复"));await refresh();},
 "queue-stage":async()=>{const p=queuePayload();if(!p.project_id || !p.book)throw new Error("请选择作品并填写平台书名");operationStarted(await api(`/api/projects/${url(p.project_id)}/stage`,"POST",{book:p.book}));},
 "operation":el=>showOperation(el.dataset.id),
 "cancel-operation":async el=>{await api(`/api/operations/${url(el.dataset.id)}/cancel`,"POST",{});toast("已请求取消，请核对运行日志");await refresh();},
 "test-ai":async()=>{const op=await api("/api/ai/test","POST",{});operationStarted(op);await showOperation(op.id);},
 "scan-models":async()=>{
  const revision=modelFormRevision;
  $("models-result").textContent="正在读取当前接口的模型列表…";$("ai-model-select").disabled=true;
  try{const result=await api("/api/ai/models","POST",{base_url:$("ai-base-url").value.trim(),api_key:$("ai-key").value},40000);
   if(revision!==modelFormRevision){$("models-result").textContent="地址或密钥已变化，请重新读取列表。";return;}
   $("ai-model-select").innerHTML='<option value="">请选择文本对话模型</option>'+result.models.map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join("");
   $("ai-model-select").disabled=!result.models.length;$("ai-model-select").value=result.models.includes($("ai-model").value)?$("ai-model").value:"";
   modelOptions=result.models;updateRoleOptions();
   $("models-result").textContent=`读取到 ${result.count} 个模型。${result.message}`;
  }catch(e){$("models-result").textContent=e.message;throw e;}
 },
 "creative":async el=>{location.hash="creative";await loadCreative(el.dataset.id);},
 "expand-brief":async()=>{
  if(!creativeDoc || creativeBusy)throw new Error("请先选择作品并等待当前操作完成");
  const brief=Object.fromEntries(new FormData($("brief-form")));if(!Object.values(brief).some(v=>v.trim()))throw new Error("先填写几条简略想法，再让 AI 润色");
  creativeLock(true);
  try{const result=await api(`/api/projects/${url(creativeId)}/creative/expand`,"POST",{brief,revision:creativeDoc.revision},80000);
   openDialog("AI 润色预览",`<form class="dialog-form"><dl class="brief-preview">${Object.entries(result.brief).filter(([,v])=>v).map(([k,v])=>`<dt>${esc(briefLabels[k])}</dt><dd>${esc(v)}</dd>`).join("")}</dl>${formEnd("采用并保存")}`,async()=>{creativeLock(true);try{await saveBrief(result.brief);closeDialog();}finally{creativeLock(false);}});
  }finally{creativeLock(false);}
 },
 "learn-sample":async el=>{if(!creativeDoc || creativeDirty)throw new Error("请先保存创作约定");operationStarted(await api(`/api/projects/${url(creativeId)}/samples/${url(el.dataset.id)}/learn`,"POST",{revision:creativeDoc.revision,full:el.dataset.full==="1"}));},
 "scan-role":async el=>{const role=el.dataset.id,form=$("roles-form");const input=form.elements[`${role}-model`];const result=await api("/api/ai/models","POST",{role,base_url:form.elements[`${role}-base_url`].value.trim() || state.ai.base_url,api_key:form.elements[`${role}-api_key`].value},40000);modelOptions=[...new Set([...modelOptions,...result.models])];updateRoleOptions();input.focus();toast(`读到 ${result.count} 个模型，可在模型栏选择`);},
 "test-roles":async()=>{const op=await api("/api/ai/roles/test","POST",{});operationStarted(op);await showOperation(op.id);},
 "reload-creative":async()=>{const id=creativeId || $("creative-project").value || state.projects[0]?.id;if(id)await loadCreative(id);},
 "apply-creative":async()=>{
  if(creativeBusy)throw new Error("请等待当前沟通完成");
  if(creativeDirty)throw new Error("请先保存左侧修改，再采用建议，避免覆盖未保存内容");
  const proposal=creativeDoc?.proposal || creativeDoc?.history.at(-1)?.proposal;
  if(!proposal || !Object.keys(proposal).length)return;
  creativeLock(true);try{await saveBrief({...creativeDoc.brief,...proposal});$("creative-proposal").hidden=true;}finally{creativeLock(false);}
 },
 "check-diagnostics":async()=>{state.diagnostics=await api("/api/diagnostics");renderDiagnostics();toast("环境检查已更新");}
};
actions["connect-devices"]=async()=>{
 const data=await api('/api/access');
 if(data.pairing_required===false){
  const links=(data.addresses||[]).map(x=>`<div class="device-address"><span class="pill pill-neutral">${esc(x.kind)}</span><a href="${esc(x.url)}/" target="_blank" rel="noopener">${esc(x.url)}</a></div>`).join('');
  openDialog('手机与平板访问',`<div class="dialog-content device-content"><p class="device-intro">同一可信网络，打开即用。</p><p>${data.local?'在手机或平板浏览器直接打开下列地址，不需要配对码。':'你已通过可信网络连接，无需配对或设备登录。'}</p>${links||(!data.local?'':'<p>暂未发现私有地址。连接可信局域网或Tailscale后重新启动小说助手。</p>')}<p class="field-help">接入该局域网或Tailscale网络的人可能管理作品、模型设置并触发生成或发布。仅在可信网络使用，不开放公网；电脑需保持运行。</p></div>`);
  return;
 }
 if(!data.local){
  openDialog('已连接编辑部',`<div class="dialog-content device-content"><p>你正在远程管理这台电脑上的小说。电脑需保持运行。</p><button class="button button-secondary" data-action="device-logout">退出此设备</button></div>`);
  return;
 }
 const links=data.addresses.map(x=>`<div class="device-address"><span class="pill pill-neutral">${esc(x.kind)}</span><a href="${esc(x.url)}/pair" target="_blank" rel="noopener">${esc(x.url)}</a></div>`).join('');
 const devices=data.devices.map(x=>`<div class="device-row"><div><strong>${esc(x.name)}</strong><small>${new Date(x.created_at*1000).toLocaleDateString('zh-CN')} 已连接</small></div><button class="button button-small button-secondary" data-action="revoke-device" data-id="${esc(x.id)}">移除</button></div>`).join('');
 openDialog('连接手机与平板',`<div class="dialog-content device-content"><p class="device-intro">换一块屏幕，接着写。</p><p>在设备浏览器打开下面的地址，再输入配对码。</p>${links || '<p>暂未找到可用地址。请连接局域网或 Tailscale 后重新启动小说助手。</p>'}<p class="field-help">局域网地址适用于可信的同一 Wi-Fi；Tailscale 地址需要两端登录同一网络，传输经过加密。配对设备可管理作品和设置。</p><div class="device-pairing"><button class="button button-primary" data-action="create-pair-code" ${data.enabled?'':'disabled'}>生成配对码</button><output id="device-code" aria-live="polite"></output><small id="device-code-expiry"></small></div>${devices?`<h3>已连接设备</h3>${devices}`:''}<p class="field-help">重启服务会断开全部设备，重新配对即可。</p></div>`);
};
actions['create-pair-code']=async()=>{const result=await api('/api/access/code','POST',{});$('device-code').textContent=result.code;$('device-code-expiry').textContent=`有效至 ${new Date(result.expires_at*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} · 仅可使用一次`;};
actions['revoke-device']=async el=>{await api(`/api/access/devices/${url(el.dataset.id)}`,'DELETE');await actions['connect-devices']();toast('设备已断开');};
actions['device-logout']=async()=>{await api('/api/access/logout','POST',{});location.assign('/pair');};
document.addEventListener("click",e=>{const el=e.target.closest("[data-action]");if(el && !el.disabled){const fn=actions[el.dataset.action];if(fn)busy(el,()=>fn(el));}});
$("queue-form").addEventListener("input",()=>{queueDirty=true;});
$("queue-project").addEventListener("change",()=>{const p=projectById($("queue-project").value);if(p)$("queue-book").value=p.title;});
$("queue-form").onsubmit=e=>{e.preventDefault();if(!e.target.reportValidity())return;const p=queuePayload();if(!p.account){toast("请选择已登录账号",true);return;}openDialog("确认这次发布",`<form class="dialog-form"><div class="confirmation-summary"><dl class="detail-grid"><dt>作品</dt><dd>${esc(p.book)}</dd><dt>账号</dt><dd>${esc(p.account)}</dd><dt>章节数</dt><dd>队列中的前 ${p.count} 章</dd><dt>AI 声明</dt><dd>使用 AI：是</dd></dl></div><p class="field-help">将向番茄平台提交现有队列。若平台状态无法确认，系统会停止并保留记录。</p>${formEnd("确认并发布")}`,async()=>{operationStarted(await api("/api/publish","POST",p));closeDialog();});};
$("ai-form").addEventListener("input",()=>{aiDirty=true;});
for(const id of ["ai-base-url","ai-key"])$(id).addEventListener("input",()=>{modelFormRevision++;$("ai-model-select").disabled=true;$("ai-model-select").innerHTML='<option value="">地址或密钥已变化，请重新读取</option>';$("models-result").textContent="请读取当前接口的模型列表，或手动填写模型 ID。";});
$("ai-model-select").onchange=e=>{if(e.target.value){$("ai-model").value=e.target.value;aiDirty=true;}};
$("ai-form").onsubmit=e=>{e.preventDefault();busy(e.target.querySelector('[type="submit"]'),async()=>{const payload=Object.fromEntries(new FormData(e.target));const saved=await api("/api/ai","PUT",payload);$("ai-key").value="";state.ai=saved;aiConfigRevision++;modelFormRevision++;aiDirty=false;$("ai-status").textContent=saved.configured?"已保存配置":"尚未配置";$("ai-status").className=`pill ${saved.configured?"pill-success":"pill-neutral"}`;toast("AI 配置已保存");await refresh();});};
$("creative-project").onchange=e=>busy(null,()=>loadCreative(e.target.value));
for(const button of document.querySelectorAll("[data-studio-tab]")){
 button.onclick=()=>setStudioTab(button.dataset.studioTab);
 button.onkeydown=e=>{if(["ArrowLeft","ArrowRight"].includes(e.key)){e.preventDefault();const keys=["brief","learning","planning","memory"];setStudioTab(keys[(keys.indexOf(studioTab)+(e.key==="ArrowRight"?1:keys.length-1))%keys.length]);document.querySelector(`[data-studio-tab="${studioTab}"]`).focus();}};
}
$("roles-form").addEventListener("input",()=>{rolesDirty=true;});$("multi-model").onchange=()=>{rolesDirty=true;};
 $("roles-form").onsubmit=e=>{e.preventDefault();busy(e.target.querySelector('[type="submit"]'),async()=>{const roles={};for(const role of Object.keys(roleLabels))roles[role]={model:e.target.elements[`${role}-model`].value,base_url:e.target.elements[`${role}-base_url`].value,api_key:e.target.elements[`${role}-api_key`].value};state.ai=await api("/api/ai/roles","PUT",{multi_model:$("multi-model").checked,polish_mode:$("polish-mode").value,review_policy:$("review-policy").value,roles});aiConfigRevision++;for(const role of Object.keys(roleLabels))e.target.elements[`${role}-api_key`].value="";rolesDirty=false;rolesSignature="";toast("模型分工已保存");await refresh();});};
$("sample-file").onchange=e=>{$("sample-file-name").textContent=e.target.files[0]?.name || "选择 TXT，或拖入这里";};
const drop=$('sample-file').closest('.file-drop');drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragging');};drop.ondragleave=()=>drop.classList.remove('dragging');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragging');if(e.dataTransfer.files.length){$("sample-file").files=e.dataTransfer.files;$("sample-file").dispatchEvent(new Event('change'));}};
$("sample-form").onsubmit=e=>{e.preventDefault();busy(e.target.querySelector('[type="submit"]'),async()=>{if(!creativeDoc || creativeDirty)throw new Error("请先选择作品并保存约定");const file=$("sample-file").files[0];if(!file || !file.name.toLowerCase().endsWith('.txt') || file.size>5*1024*1024)throw new Error("请选择不超过 5 MB 的 TXT");const id=creativeId,revision=creativeDoc.revision,full=$("sample-mode").value==="full";const body=new FormData();body.append("file",file);const response=await fetch(`/api/projects/${url(id)}/samples`,{method:"POST",headers:{"X-Novel-Helper":"1"},body});const uploaded=await response.json();if(!response.ok)throw new Error(uploaded.detail || "上传失败");operationStarted(await api(`/api/projects/${url(id)}/samples/${url(uploaded.id)}/learn`,"POST",{revision,full}));$("sample-file").value="";$("sample-file-name").textContent="选择 TXT，或拖入这里";await loadStudio();});};
$("plan-form").onsubmit=e=>{e.preventDefault();busy(e.target.querySelector('[type="submit"]'),async()=>{if(!creativeId || creativeDirty)throw new Error("请先选择作品并保存约定");operationStarted(await api(`/api/projects/${url(creativeId)}/plan`,"POST",{count:Number(e.target.elements.count.value)}));});};
$("brief-form").addEventListener("input",()=>{creativeDirty=true;$("creative-save-state").textContent="有未保存修改";});
$("brief-form").onsubmit=e=>{e.preventDefault();if(!creativeDoc || creativeBusy)return;const brief=Object.fromEntries(new FormData(e.target));busy(null,async()=>{creativeLock(true);try{await saveBrief(brief);}finally{creativeLock(false);}});};
$("creative-chat-form").onsubmit=e=>{e.preventDefault();if(!creativeDoc || creativeBusy)return;
 if(creativeDirty){toast("请先保存左侧创作约定，让 AI 按最新要求讨论",true);return;}
 const message=$("creative-message").value.trim();if(!message)return;
 busy(null,async()=>{creativeLock(true);const status=$("creative-chat-status");status.hidden=false;status.textContent="AI 正在思考你的故事…";
  try{creativeDoc=await api(`/api/projects/${url(creativeId)}/creative/chat`,"POST",{message,revision:creativeDoc.revision},45000);$("creative-message").value="";renderCreativeDocument();status.textContent="回复已保存。AI 的建议只有点击采用后才会影响写作。";}
  catch(error){status.textContent=error.message;throw error;}finally{creativeLock(false);}
 });};
$("scheduler-enabled").onchange=e=>busy(e.target,async()=>{try{state.settings=await api("/api/settings","PUT",{scheduler_enabled:e.target.checked});toast(e.target.checked?"自动调度已开启，管理服务需保持运行":"自动调度已暂停");}finally{renderJobs();}});
$("project-search").oninput=renderProjects;$("log-search").oninput=renderLogs;$("log-status").onchange=renderLogs;
$("refresh-button").onclick=()=>{queueDirty=false;refresh();};
$("menu-toggle").onclick=()=>menu(!$("sidebar").classList.contains("open"));$("sidebar-backdrop").onclick=()=>menu(false);
$("theme-button").onclick=()=>{const dark=document.documentElement.dataset.theme!=="dark";document.documentElement.dataset.theme=dark?"dark":"light";localStorage.setItem("novel-helper-theme",dark?"dark":"light");$("theme-button").setAttribute("aria-label",dark?"切换浅色模式":"切换深色模式");};
document.documentElement.dataset.theme=localStorage.getItem("novel-helper-theme") || "light";
for(const d of document.querySelectorAll("dialog")){d.addEventListener("close",()=>{if(!document.querySelector("dialog[open]"))document.body.classList.remove("modal-open");});}
window.addEventListener("hashchange",route);
const now=new Date();$("date-day").textContent=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",day:"2-digit"}).format(now).replace("日","");$("date-weekday").textContent=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",weekday:"long"}).format(now);$("date-month").textContent=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"long"}).format(now);
icons();route();refresh();setInterval(refresh,8000);
