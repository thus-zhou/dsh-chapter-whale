/* Project-local memory editor. No credentials or memory contents in localStorage. */
(() => {
  const categories={canon:"固定设定",fact:"已发生事实",foreshadow:"伏笔计划",preference:"创作偏好"};
  const clues={planned:"计划埋设",planted:"已埋设",resolved:"已回收"};
  let doc=null,projectId="",signature="",loading=0;
  function render(){
    const valid=doc && projectId===creativeId;
    $("memory-summary").textContent=valid?`${doc.items.filter(x=>x.status==='active').length} 条有效记忆 · 已提取 ${Object.keys(doc.chapters).length} 章${doc.pending_chapters?.length?` · ${doc.pending_chapters.length} 章待补建`:""}${doc.conflicts?` · ${doc.conflicts} 条待确认`:""}${doc.stale?` · ${doc.stale} 条来源失效`:""}`:"请先选择作品。";
    if(!valid){$("memory-list").innerHTML="";return;}
    const query=$("memory-search").value.trim().toLowerCase(),filter=$("memory-filter").value;
    const entries=doc.items.filter(x=>(filter==="archived"?x.status==="archived":x.status!=="archived") &&
      (!filter || (filter==="conflict"?x.status==="conflict":filter==="stale"?x.freshness==="stale":filter==="archived" || x.category===filter)) &&
      `${x.title} ${x.content}`.toLowerCase().includes(query));
    $("memory-list").innerHTML=entries.length?entries.slice(0,100).map(x=>`<article class="memory-card ${x.status==='conflict' || x.freshness==='stale'?'memory-warning':''}">
      <div class="memory-card-heading"><div><span class="pill pill-neutral">${categories[x.category]}</span>${x.pinned?'<span class="pill pill-success">必须记住</span>':""}${x.status==='conflict'?'<span class="pill pill-danger">待确认 · 不参与读取</span>':""}${x.freshness==='stale'?'<span class="pill pill-danger">来源失效 · 不参与读取</span>':""}<h3>${esc(x.title)}</h3></div><button class="button button-secondary button-small" data-action="memory-edit" data-id="${esc(x.id)}">${x.status==='conflict'?"确认／纠正":"编辑"}</button></div>
      <p class="memory-content">${esc(x.content)}</p><div class="memory-source">${x.source.kind==='manual'?"作者确认":`第 ${x.source.chapter} 章自动提取`}${x.source.kind==='manual' && x.source.chapter?` · 来源第 ${x.source.chapter} 章`:""}${x.category==='foreshadow'?` · ${clues[x.clue_state] || '计划'}${x.due_chapter?` · 计划第 ${x.due_chapter} 章回收`:""}`:""}</div>
      ${x.source.quote?`<details class="quiet-details"><summary>查看原文依据</summary><p>${esc(x.source.quote)}</p></details>`:""}</article>`).join("")+(entries.length>100?'<p class="field-help memory-limit">显示前 100 条，请搜索具体主题。</p>':""):empty("还没有这类记忆","手动添加必须记住的设定，或从已保存的合格正文补建。");
  }
  async function load(id){
    const request=++loading;const next=await api(`/api/projects/${url(id)}/memory`);
    if(id!==creativeId || request!==loading)return;
    const nextSignature=JSON.stringify({id,next});
    if(signature===nextSignature)return;
    signature=nextSignature;doc=next;projectId=id;render();
  }
  function editor(item=null){
    if(!creativeId || !doc || projectId!==creativeId)throw new Error("请先选择作品并载入记忆");
    const id=creativeId,revision=doc.revision;
    const opt=(values,selected)=>Object.entries(values).map(([value,label])=>`<option value="${value}" ${value===selected?'selected':''}>${label}</option>`).join("");
    openDialog(item?"编辑这条记忆":"告诉模型：必须记住",`<form class="dialog-form">
      <div class="form-grid"><label>分类<select name="category">${opt(categories,item?.category || "canon")}</select></label><label>状态<select name="status">${opt({active:"确认生效",conflict:"待确认 · 暂不读取",archived:"归档 · 保留记录"},item?.status==='archived'?"archived":"active")}</select></label></div>
      <label>主题<input name="title" maxlength="120" required value="${esc(item?.title || "")}" placeholder="例如：林舟：右手伤势"></label>
      <label>需要记住什么<textarea name="content" rows="4" maxlength="2000" required placeholder="写明事实或规则，不要把未发生的计划写成事实。">${esc(item?.content || "")}</textarea></label>
      <label class="checkbox-label"><input name="pinned" type="checkbox" ${(!item || item.pinned)?"checked":""}> 必须记住 · 优先放入模型上下文</label>
      <details class="quiet-details"><summary>章节与伏笔</summary><div class="form-grid"><label>来源章节<input name="source_chapter" type="number" min="0" max="100000" value="${item?.source.chapter || 0}"></label><label>计划回收章节<input name="due_chapter" type="number" min="0" max="100000" value="${item?.due_chapter || 0}"></label><label>伏笔状态<select name="clue_state">${opt(clues,item?.clue_state || "planned")}</select></label></div><p class="field-help">0 表示不限定；来源章节写完后，才供后续章节读取。伏笔始终单独标为计划。</p></details>
      <p class="field-help">保存表示作者明确确认；纠正后未发布旧稿可能需要重新审查。归档可恢复，不删除原记录。</p>${formEnd("保存记忆")}</form>`,async()=>{
        const form=$("action-dialog").querySelector("form"),value=Object.fromEntries(new FormData(form));
        value.pinned=form.elements.pinned.checked;value.source_chapter=Number(value.source_chapter);value.due_chapter=Number(value.due_chapter);value.revision=revision;
        await api(`/api/projects/${url(id)}/memory/items${item?'/'+url(item.id):''}`,item?"PUT":"POST",value);
        closeDialog();await load(id);toast("记忆已保存，下次创作会读取");
      });
  }
  actions["memory-add"]=()=>editor();
  actions["memory-edit"]=el=>editor(doc?.items.find(x=>x.id===el.dataset.id));
  actions["memory-rebuild"]=async()=>{
    if(!creativeId)throw new Error("请先选择作品");
    if(creativeDirty)throw new Error("请先保存创作约定");
    const id=creativeId;
    openDialog("补建这本书的记忆",`<form class="dialog-form"><p>由 D 从已保存且具备当前有效审查或 E 授权的正文提取事实，每次最多 30 章；已完成章节不重复分析。</p><p class="field-help">会向所选接口发送正文并产生费用。不会改写正文、覆盖手动记忆或发布章节。</p>${formEnd("开始补建")}</form>`,async()=>{operationStarted(await api(`/api/projects/${url(id)}/memory/rebuild`,"POST",{}));closeDialog();});
  };
  actions["memory-preview"]=async()=>{
    if(!creativeId)throw new Error("请先选择作品");
    const result=await api(`/api/projects/${url(creativeId)}/memory/context`);
    openDialog(`第 ${result.chapter} 章的记忆上下文`,`<div class="dialog-content"><p class="field-help">${result.ids.length} 条已选入${result.omitted?`，${result.omitted} 条因预算未纳入`:""}。实际任务会按主题检索。</p><pre class="guide-preview">${esc(result.text || "尚无适用于这一章的记忆。")}</pre></div>`);
  };
  $("memory-search").oninput=render;$("memory-filter").onchange=render;
  window.NovelMemory={load,get project(){return projectId;}};
})();
