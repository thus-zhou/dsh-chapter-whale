# 前端 / 桌面 UI / 可访问性 / 静态资产 / 构建与发布链 独立审计（HEAD 5e8a2d0）

- 仓库：`/home/ubuntu/.hermes/cache/scratch/audit-v2-head`（detached HEAD `5e8a2d0`，只读）
- 审计方式：逐文件阅读 + 在独立副本中执行构建/变异 + 用真实 Chromium（Playwright 1.63 / chromium-1200）驱动 `backend/manager/static` 页面，配一个只读 stub API
- 未修改仓库任何受版本控制的文件（`git status` 只有外部进程写入的 `node_modules`；见 §6）
- 临时脚本：`/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-d-*`

## 0. 结论与计数

| 级别 | 数量 |
|---|---|
| P1 | 1 |
| P2 | 9 |
| P3 | 6 |
| P4 | 2 |
| 合计 | 18 |

最严重的 5 条：**D-01**（陈旧草稿静默覆盖正式版本）、**D-03**（切章 IME 文本静默丢失）、**D-06**（DSH 面板输入法状态卡死后自动保存/Ctrl+S 永久失效）、**D-11**（DSH 无草稿 409 后保存死锁）、**D-05**（Ctrl+S 在大纲编辑器里误提交章节正式版本）。其次值得优先处理：**D-02**（批注提交 100% 失败）、**D-04**（移动抽屉焦点/读屏不可用）。

已复测通过：上一轮修复的 Ctrl+S 全局保存、移动抽屉 `aria-expanded`、移动选区条避让 dock、移动筛选目标尺寸、静态侧 IME blur/visibility 兜底、浮动条视口钳制；另外核心内核双份字节一致、生成块与源字节一致、构建幂等、`check-release --local` 通过、三路合并 3000 例无崩溃/无标记失配。详见 §4。

---

## 1. 发现

### D-01（P1）陈旧草稿按“最新版本”身份保存，静默覆盖后台写入的正式版本

**位置**
- `backend/manager/static/workbench.js:994-1004`（`applyChapter` 用 `data.version_id` / `data.sha256` 作为基线，完全忽略 `draftInfo.base_version_id` / `base_content_sha256`）
- `backend/manager/static/workbench.js:1044`（明确提示“基于旧版本，保存时会做并发对比”）
- `backend/manager/static/workbench.js:1317-1322`（草稿 PUT 也用 `state.baseVersionId/baseSha`）
- `backend/manager/static/workbench.js:1494-1495`（正式版本 PUT 的 `expected_version_id` / `expected_content_sha256` 来自同一对被污染的基线）
- 对照：`client.js:6136-6141` 的 DSH 实现刻意使用草稿自己的 base，并在注释里写明“Trusting the newest file sha instead would let a stale draft silently overwrite a background save.”

**机制**
1. 章节当前为 v1，作者打开工作台，草稿（base=v1）已存在；
2. 后台任务/另一窗口把正文保存为 v2；
3. 作者重新打开该章：`GET /chapters/N` 返回 `content=v2`、`draft.content=旧草稿`、`draft.base_version_id=v1`、`draft.stale=true`；
4. `applyChapter` 选择显示草稿正文（正确），但把 `state.baseVersionId` 设为 `v2`、`state.baseSha` 设为 v2 的 sha（错误）；
5. 作者按 Ctrl+S：`expected_version_id=v2`、`expected_content_sha256=v2 的 sha`，内容却是基于 v1 的旧草稿；
6. 服务端 `save_version`（`backend/integration/chapter_editor.py:409-431`）发现 expected 与当前完全一致 → 不报 `concurrent_modification` → 把旧草稿写成 v3，并清掉草稿。v2 的修改被静默覆盖。

**影响**：作者的正式版本可被旧草稿无声回滚；提示语“保存时会做并发对比”是假的。属于数据丢失级缺陷，且只发生在静态 Web 工作台（DSH 面板有正确防护）。

**加重情节**：即使不按 Ctrl+S，只要在同一陈旧草稿上继续输入，1.5s 后的自动草稿保存也会把 `base_version_id/base_content_sha256` 改写成 v2（`workbench_db.py:617-628` 的 UPSERT 会覆盖 base），于是服务端下次计算出的 `draft.stale` 变成 false——陈旧草稿的“陈旧”证据被这次保存抹掉。之后连 DSH 面板也会把这个草稿当成基于 v2 的正常草稿，失去最后一道防护。

**最小修复**
```js
// workbench.js applyChapter()
state.baseContent = String(data.content || "");
state.baseVersionId = state.draft.exists
  ? String(state.draft.baseVersionId || data.version_id || "")
  : String(data.version_id || "");
state.baseSha = state.draft.exists
  ? String(state.draft.baseSha || data.sha256 || data.content_sha256 || "")
  : String(data.sha256 || data.content_sha256 || "");
```
这样陈旧草稿保存时 expected 仍是 v1，服务端返回 409 `concurrent_modification`，走既有的“载入最新正文 / 合并后重试”流程。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
/home/ubuntu/venvs/dsh/bin/python tmp-d-stub.py 8799 &   # stub：GET 章节返回“基于 v1 的草稿 + 当前 v2”
/home/ubuntu/venvs/dsh/bin/python tmp-d-probe6.py
```
**实际输出**（Chromium 实测）
```json
{
  "loaded_value": "旧草稿（基于 v1）",
  "banner": "已恢复未提交草稿（基于旧版本，保存时会做并发对比）。按 Ctrl+S 保存为正式版本。",
  "draft_state": "草稿 d-old · r2",
  "save_requests": [{
    "m": "PUT", "p": "/api/projects/book1/chapters/2",
    "expected_version_id": "v2",
    "expected_sha": "bbbbbbbbbbbb",
    "submitted_draft_id": "d-old"
  }]
}
```
stub 的章节数据：`version_id=v2`、`draft.base_version_id=v1`、`draft.content=旧草稿`。客户端提交的 expected 是 v2，而不是 v1。

---

### D-02（P2）批注提交与后端契约不符：按钮探测成功后 100% 失败，且 GET 结果被丢弃

**位置**
- `backend/manager/static/workbench.js:2012-2042`（POST body：`{start, end, quote, note, note_text, draft_id}`）
- `backend/manager/static/workbench.js:1969-1984`（GET 探测 200 即启用按钮并提示“可以提交到后端”，响应体直接丢弃）
- `backend/integration/annotations.py:137-153`（`create_annotation` 必须要有 `instruction`（非空）和 `anchor.{char_start,char_end,quote}`，且 quote 必须与正文切片一致）
- `backend/manager/api_v085.py:31-35`（`AnnotationError` 统一 400，`code/message` 都是错误码）

**机制**：GET `/annotations` 只验证接口可达；POST 的字段名与后端完全不同——`instruction` 缺失 → `AnnotationError("instruction_required")`（400），即使补上 `instruction`，顶层 `start/end/quote` 也不会进 `anchor` → 再报 `anchor_slice_mismatch`。同时 `probeAnnotationEndpoint` 不保存 GET 结果，`renderAnnotations()` 只渲染 `state.annotations`（仅本页内存），所以即使后端已有批注也永远不显示。

**影响**：静态工作台的“提交到批注接口”是死按钮；“批注接口已返回 200，可以提交到后端”会误导用户以为功能可用。DSH 面板则完全没有批注编辑（见 §2 双实现漂移）。

**最小修复**
```js
await api(path, "POST", {
  instruction: note,
  scope: "selection",
  anchor: { char_start: state.selection.startCp, char_end: state.selection.endCp, quote: state.selection.text },
  base_version_id: state.baseVersionId || null,
  base_content_sha256: state.baseSha || null,
}, 20000);
```
并在探测成功时把 GET 返回的批注合并进列表（或直接 `renderAnnotations` 使用服务端数据）。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
/home/ubuntu/venvs/dsh/bin/python tmp-d-stub.py 8799 &
/home/ubuntu/venvs/dsh/bin/python tmp-d-probe.py
```
**实际输出**（stub 按 `annotations.py` 的同一校验规则返回）
```json
"annotation_requests": [
  {"method":"GET","path":"/api/projects/book1/chapters/2/annotations","body":null},
  {"method":"POST","path":"/api/projects/book1/chapters/2/annotations",
   "body":{"start":0,"end":4,"quote":"第二章正","note":"这里需要更紧张","note_text":"这里需要更紧张","draft_id":null}}
],
"annotation_toasts": ["正式版本已保存×", "annotation_required · instruction_required×"],
"annotation_hint": "批注接口已返回 200，可以提交到后端。"
```
真实后端会返回 `{"code":"instruction_required","message":"instruction_required"}`（400）。

---

### D-03（P2）切章加载期间开始的输入法组合文本被静默覆盖（`force=true` 让 IME 守卫成为死代码）

**位置**
- `backend/manager/static/workbench.js:951-990`（`openChapter` 只在发起请求**前**检查 `state.composing`）
- `backend/manager/static/workbench.js:1031-1035`（`if (!setEditorValue(content, title, true)) { banner("输入法仍在组合文字，已推迟载入…") }`）
- `backend/manager/static/workbench.js:1059-1068`（`setEditorValue` 的守卫：`if (!force && (state.composing || adapter.composing)) return false;`）
- 同样失效的调用：`workbench.js:1718`、`1729`、`1770`

**机制**：`openChapter` 在 `await api(GET)` 之前检查 composing，但请求进行中 textarea 仍可编辑；用户此时开始拼音/五笔组合，`compositionstart` 把 `state.composing=true`。GET 返回后 `applyChapter` 以 `force=true` 调用 `setEditorValue`——守卫被短路，直接覆盖 `textarea.value`，随后 `compositionend` 到来时组合文本已不存在。`if (!setEditorValue(...))` 分支永远不会执行，因此“已推迟载入”提示也永远不会出现。

**影响**：在章节加载窗口（本地通常 10–50ms，慢盘/长章节更久）里输入的 IME 组合文字无提示丢失；这是典型的“修了但没修对”——上一轮为 IME 加了守卫和提示，却用 `force=true` 绕过了它。

**最小修复**
```js
// applyChapter: 不要 force，让守卫生效
if (!setEditorValue(content, title, false)) {
  banner("输入法仍在组合文字，已推迟载入第 " + state.currentId + " 章。", "error");
  return; // 或排队在 compositionend 后重试
}
```
更稳妥：在 GET 期间设置 `els.editor.readOnly = true`，返回后再恢复。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
/home/ubuntu/venvs/dsh/bin/python tmp-d-stub.py 8799 &
/home/ubuntu/venvs/dsh/bin/python tmp-d-probe4.py   # stub 对章节 GET 延迟 1.2s
```
**实际输出**
```json
{
  "start_chapter": "第 2 章 · 第二章",
  "start_value": "第二章正文。",
  "during_request_title": "正在读取第 1 章…",
  "typed_while_waiting": "输入法组合中的文字",
  "after_get_value": "第一段文字，用于选择测试。\n第二段文字。",
  "after_get_title": "第 1 章 · 第一章 开端",
  "banner": "",
  "composing_still_flagged": false
}
```
输入的文字消失，banner 为空（死分支未执行）。

---

### D-04（P2）移动端抽屉：关闭状态仍可聚焦/被读屏访问，打开后焦点不进入

**位置**
- `backend/manager/static/workbench.css:1699-1734`（`@media (max-width: 767px)` 下 `.wb-left`/`.wb-right` 仅 `transform: translateX(-105%) / translateY(105%)`，无 `display:none`/`visibility:hidden`）
- `backend/manager/static/workbench.js:1248-1278`（`toggleDrawer` 只切 `is-open`、backdrop、`modal-open`、`aria-expanded`，不设 `inert`/`aria-hidden`，不移动焦点）
- `backend/manager/static/index.html:147-149`（触发按钮无 `aria-controls`）
- `backend/manager/static/index.html:152`（`aside#wb-left` 无 `role="dialog"` / `aria-modal`）

**机制**：关闭的抽屉只是被平移到视口外，仍留在无障碍树与 Tab 顺序中；打开抽屉后焦点仍留在触发按钮上，背景没有 `inert`，下一次 Tab 会走到抽屉**后面**的编辑器和工具按钮。读屏用户也会把两个“隐藏”面板当成正常内容朗读（其中包含整章列表和批注编辑区）。

**影响**
- WCAG 2.4.3（焦点顺序）、2.4.7（焦点可见——焦点落在视口外的按钮上）、4.1.2（状态/角色）；
- 键盘/读屏用户在手机上无法可靠使用章节目录和本章工具。

**最小修复**
```js
// toggleDrawer(): open 时
if (open) {
  target.inert = false;
  target.removeAttribute('aria-hidden');
  (side === 'left' ? els.leftClose : els.tabs.querySelector('[role=tab]')).focus();
  els.center.inert = true; els.page.querySelector('.wb-mobile-bar').inert = true;
} else {
  target.inert = true;
  target.setAttribute('aria-hidden', 'true');
  (side === 'left' ? els.mobileLeft : els.mobileRight).focus();
  els.center.inert = false; ...
}
```
并在 `index.html` 给触发按钮补 `aria-controls="wb-left"` / `"wb-right"`，给抽屉补 `role="dialog" aria-modal="true"`（或改成语义化的 `<dialog>`）。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
/home/ubuntu/venvs/dsh/bin/python tmp-d-stub.py 8799 &
/home/ubuntu/venvs/dsh/bin/python tmp-d-probe3.py
```
**实际输出**（390×844，关闭态）
```json
{
  "leftTransform": "matrix(1, 0, 0, 1, -352.16, 0)",
  "leftVisibility": "visible", "leftDisplay": "flex",
  "leftInert": false, "leftAriaHidden": null,
  "firstChapterButtonTabIndex": 0,
  "firstChapterButtonRect": {"x": -55.77, "y": 12, "w": 24, "h": 24},
  "leftHasOpenClass": false
}
```
全文档中“在视口外但仍可聚焦”的元素共 **29** 个；从文档最后一个可聚焦元素继续 Tab 会得到 `BODY`，而最后一个可聚焦元素是 `wb-annotation-add`（位于**关闭的**右抽屉内）。

打开右抽屉后：
```json
{"right_open": true, "tabs_after_open_right": ["wb-title","wb-quick-check","wb-save","wb-editor"]}
```
焦点从未进入已打开的抽屉。

---

### D-05（P2）Ctrl+S 在大纲/设定编辑器中提交的是“章节正式版本”，并吞掉浏览器保存

**位置**
- `backend/manager/static/workbench.js:530-537`（document 级 keydown：任何 Ctrl/Cmd+S 都 `preventDefault()` 并 `saveVersion()`）
- `backend/manager/static/workbench.js:1128-1136`（编辑器内的 Ctrl+S 处理，带 `defaultPrevented` 判断）

**机制**：document 级处理器在 `DOMContentLoaded` 时无条件绑定，覆盖整个静态应用；它不判断当前焦点在哪个输入控件、也不判断当前视图。作者在“大纲与设定”里编辑 `#wb-outline-text`（该编辑器只有“保存大纲”按钮，没有快捷键）时按 Ctrl+S，实际提交的是**当前章节的正式版本**；浏览器“保存网页”也被阻止。

**影响**：一次误按就会把当前章节（可能是半成品）写成正式版本并清理草稿；大纲修改没有被保存，用户以为已保存。跨页面（AI 设置等）同样被劫持。

**最小修复**
```js
if ((event.ctrlKey || event.metaKey) && key === 's') {
  const el = document.activeElement;
  const inOutline = el && (el.id === 'wb-outline-text' || el.id === 'wb-lore-text' ||
                           el.closest('#wb-outline-view'));
  if (inOutline) { event.preventDefault(); saveOutlineFile(); return; } // 或直接不拦截
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') &&
      el.id !== 'wb-editor' && el.id !== 'wb-title') return; // 让浏览器/控件自己处理
  ...
}
```

**复现**：同 D-02 的 `tmp-d-probe.py`（其中 Ctrl+S 段落）。
**实际输出**
```json
"ctrl_s_in_outline": [{
  "method": "PUT", "path": "/api/projects/book1/chapters/2",
  "body": {"title":"第二章","content":"第二章正文。","op_id":"save_...","expected_version_id":"v2", "...": "..."}
}],
"ctrl_s_outline_toast": ["正式版本已保存×"]
```
而 `#wb-outline-text` 中刚输入的“大纲里刚敲的一段未保存内容”没有任何 PUT `/outline/files/...` 请求。

---

### D-06（P2）DSH 面板 `composingRef` 永不复位：输入法一旦中断，自动草稿与 Ctrl+S 永久停摆

**位置**
- `client.js:6045`（`const composingRef = React.useRef(false);`）
- `client.js:7016-7024`（只有 `onCompositionStart` 置 true、`onCompositionEnd` 置 false；无 blur/visibilitychange 兜底）
- `client.js:6266-6274`（`scheduleDraft` 在 `composingRef.current` 为 true 时每 1.5s 递归重排，永不保存）
- `client.js:6211-6212`（`persistDraftOnce`：composing 时直接返回 false）
- `client.js:6402-6405`（`saveVersion`：composing 时静默 return）
- 对照：静态实现已在 `workbench.js:370-388` 增加 `blur` 与 `visibilitychange` 复位

**机制**：`compositionend` 并非在所有浏览器/输入法/窗口切换路径上都可靠触发（这正是静态实现上一轮补 blur/visibility 兜底的原因）。DSH 面板没有兜底；一旦漏掉一次 `compositionend`：
- 1500ms 定时器无限自我重排，草稿再也不会发出；
- Ctrl+S 被 `saveVersion` 的 composing 早退静默吞掉；
- 路由切换卸载时的最后一次 `queueDraftSave` 也会在 `persistDraftOnce` 里返回 false。
本次会话的后续输入全部只存在内存里。

**最小修复**
```js
onBlur: () => { composingRef.current = false; adapterRef.current?.endComposition(); },
// 以及 useEffect 里
const reset = () => { composingRef.current = false; };
window.addEventListener('blur', reset);
document.addEventListener('visibilitychange', () => { if (document.hidden) reset(); });
```
（与 `workbench.js:370-388` 对齐。）

**复现**（代码级，无法在无 IME 的 headless Chromium 中真实触发）
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
grep -n "composingRef" client.js
grep -n "compositionstart\|compositionend\|\"blur\"\|visibilitychange" backend/manager/static/workbench.js | head
```
**实际输出**：`client.js` 中 `composingRef` 只有 10 处，置 true/false 仅 7017/7021；而 `workbench.js` 在 370-388 有三组复位路径（compositionend、blur、visibilitychange）。`client.js:6270` 的 `if (composingRef.current) { scheduleDraft(); return; }` 即无限重排点。

---

### D-07（P2）DSH 主编辑器没有可见焦点指示（WCAG 2.4.7）

**位置**
- `client.js:5832`：`.nh-root[data-ui="atelier"] .wb-textarea { ... outline: none; ... }`
- `assets/atelier-base.css:34`：focus-visible 规则只覆盖 `button, a, input, select`，**不含 `textarea`**
- 生成块位置：`client.js:1271-2393`

**机制**：`.wb-textarea` 显式 `outline:none`，而插件的 `:focus-visible` 选择器列表没有 `textarea`（静态 UI 的 `style.css:6` 是全局 `:focus-visible`，不受影响）。键盘用户 Tab 进正文编辑器时没有任何视觉反馈。

**影响**：WCAG 2.4.7（Focus Visible）AA 失败；主编辑区是面板最核心的输入。（本测量只渲染插件自身的 `ATELIER_CSS`/`WORKBENCH_CSS`；若 DSH 宿主另有带 `!important` 的全局 focus 规则才可能覆盖，仓库内没有这种依赖。）

**最小修复**
```css
.nh-root[data-ui="atelier"] :is(button,a,input,select,textarea,summary):focus-visible {
  outline: 2px solid var(--a); outline-offset: 4px;
}
```
或至少补 `.nh-root[data-ui="atelier"] .wb-textarea:focus-visible { outline: 2px solid var(--a); outline-offset: -2px; }`。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
/home/ubuntu/venvs/dsh/bin/python tmp-d-focus.py   # 从 client.js 抽出 ATELIER_CSS + WORKBENCH_CSS 渲染
```
**实际输出**
```json
[
 {"tag":"TEXTAREA","id":"t","outlineStyle":"none","outlineWidth":"0px","outlineColor":"rgb(248, 250, 252)"},
 {"tag":"SUMMARY","id":"s","outlineStyle":"auto","outlineWidth":"1px"},
 {"tag":"BUTTON","id":"b","outlineStyle":"solid","outlineWidth":"2px","outlineColor":"rgb(121, 180, 255)"}
]
```
按钮有 2px 焦点环，textarea 为 0px。

---

### D-08（P2）生成 CSS 漂移在测试与发布链中完全不可见（`assets/*.css` → `client.js` 无字节校验）

**位置**
- `scripts/build-client-ui.py:38-67`（`sync_workbench_core`：把 `scripts/shared/workbench-core.js` 注入 `client.js` 并复制到 `static/`）
- `scripts/build-client-ui.py:70-93`（`main()`：把 `assets/atelier-base.css` + `assets/atelier-native.css` + 字体 base64 生成 `ATELIER_CSS` 块写入 `client.js`）
- `scripts/check-release.mjs:93-117`（只校验 `runtime-manifest.json` 里的文件；`build-runtime.py:49-62` 只收 `backend/` 与 `runtime/`）
- `package.json:101`（`prepublishOnly` 只跑 `check-release --local`）
- `.github/workflows/ci.yml:25-26`（只跑 check-release + npm test，**不重新生成**）
- 现有测试只对 workbench-core 做字节比对：`test/workbench-core.test.mjs:412-418`

**机制**：`assets/atelier-base.css` / `atelier-native.css` 是唯一源文件，但只有手工运行 `build-client-ui.py` 才会进入 `client.js`；`client.js` 与 `assets/` 都不在 `runtime-manifest.json` 中，`check-release` 不看它们，测试也不看 `ATELIER_CSS` 块。改源 CSS 而不重跑构建：全套测试绿、发布校验绿、DSH 面板仍是旧样式。

**影响**：样式/字体修复可以“通过所有门禁但不发货”；发布包与源不一致且无法被发现。当前 HEAD 的字节是一致的（见 §4），但保证只靠人工记忆。

**最小修复**
1. 在 `test/workbench-core.test.mjs` 增加与 `generated workbench copies stay byte-identical` 同级的断言：从 `client.js` 解出 `ATELIER_CSS` 块，与 `fonts+atelier-base+atelier-native` 重新拼接后逐字节比较；同时断言 `assets/*.css` 无 CRLF。
2. CI 加一步 `python scripts/build-client-ui.py && git diff --exit-code client.js assets/atelier-base.css backend/manager/static/workbench-core.js`。

**复现**（在副本中，不动仓库）
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
rsync -a --exclude .git --exclude node_modules audit-v2-head/ mut2/
cd mut2 && rm -rf backend/integration_data
printf '\n.nh-mutation-probe{color:#ff00ff}\n' >> assets/atelier-native.css
node scripts/check-release.mjs --local
node --test test/*.test.mjs
grep -c nh-mutation-probe client.js
# 再跑构建：
/home/ubuntu/venvs/dsh/bin/python scripts/build-client-ui.py >/dev/null
grep -c nh-mutation-probe client.js
```
**实际输出**
```
发行清单校验通过：1188 个文件与清单一致，buildId=8caf3b60...
ℹ tests 159
ℹ pass 143
ℹ fail 0
ℹ skipped 16
client_has_snippet=0          # 源已改，client.js 未变，全部门禁仍绿
client_has_snippet_after_build=1
```

---

### D-09（P2）拆分/合并后旧草稿在新章节上“复活”，可造成正文重复或回退

**位置**
- `backend/manager/static/workbench.js:2830-2847`（`submitSplitChapter`：不 flush、不丢弃草稿，成功后 `openChapter(result.chapter_id, {force:true})`）
- `backend/manager/static/workbench.js:2849-2858`（`submitMergeTail` 同样）
- `backend/manager/static/workbench.js:994-1000`（`applyChapter` 优先加载 `draft.content`）
- `client.js:6593-6615`（`afterMutation`）、`6655-6730`（`splitChapter`/`mergeTail`）同样以草稿优先重载
- `backend/integration/chapter_editor.py:757-812`（`split_chapter` 完全不动草稿；`merge_tail` 只删尾章草稿，不处理前一章草稿）

**机制**：草稿是持久化的（1.5s 自动保存）。拆分只对“正式版本”做切分，前半章上仍挂着拆分前的全文草稿；拆分成功后强制重载该章，`applyChapter` 用草稿内容覆盖显示。作者看到的还是拆分前的全文，而后半章已经独立存在——再保存就得到重复正文。合并时，前一章的旧草稿也会覆盖合并后的正文。`openTool` 里的 `confirm` 只提示“本地修改可能丢失”，并未处理这个会复活的持久草稿。

**影响**：拆分/合并结果被旧草稿“回滚”或复制，属于内容一致性/重复发布风险。需要已存在草稿（本 UI 每次输入都会在 1.5s 后创建），触发概率不低。

**最小修复**：拆分/合并前对受影响章节执行 `DELETE .../draft`（或先 flush 后丢弃），并在成功后以 `skipDraft` 方式重载；或像 DSH 一样在脏状态直接拒绝，但对“已保存草稿”也要提示并清理。

**复现**（代码级；不在无完整后端的 stub 上模拟拆分）
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
sed -n '2830,2858p' backend/manager/static/workbench.js
sed -n '994,1000p' backend/manager/static/workbench.js
grep -n "delete_draft\|draft" backend/integration/chapter_editor.py | sed -n '1,12p'
```
**实际输出**：`submitSplitChapter` 的请求只有 `/split`，之后 `openChapter(...,{force:true})`；`applyChapter` 第 995-996 行 `const content = hasDraft ? String(draftInfo.content) : ...`；`split_chapter` 函数体（757-812）没有任何 `wb.delete_draft` 调用。

---

### D-10（P3）SSE 客户端全链路未接线；且非 2xx 会永久关闭（测试把该行为固化）

**位置**
- `scripts/shared/workbench-core.js:985-1119`（`connectEventStream`）
- `scripts/shared/workbench-core.js:1048-1058`（`!ok` → `report(); close(); return;`，不再重试）
- `scripts/shared/workbench-core.js:416-436`（解析器忽略 SSE 的 `retry:` 字段；服务端 `api_v085.py:131` 明确发送 `retry: 1500`）
- `backend/manager/api_v085.py:118-152`（`/api/projects/{identity}/room/stream`，带 Last-Event-ID 回放与心跳）
- `client.js:1010` / `client.js:1165`：只有定义与导出，**没有任何调用点**
- `backend/manager/static/workbench.js`：无 `connectEventStream` / `EventSource`
- `test/workbench-core.test.mjs:360-410`：断言 `attempts === 1`、`rejected.closed === true`（把“503 不重试”写成期望）

**机制**：manager 的 SSE 端点、`index.js` 的 SSE 代理透传（`index.js:906-945`，还会转发 `Last-Event-ID`）、`workbench-core` 的解析/重连/排序组件都齐了，但没有任何 UI 消费它——`OrderedEventBuffer` 也没有被 `connectEventStream` 使用。即使接上，后端重启/网关 502/503 会让客户端永久 `closed`，必须刷新页面才能恢复；服务端的 `retry: 1500` 也不会生效。

**影响**：所谓“SSE 实时通道”在当前 HEAD 是纯死代码 + 一个会永久断流的客户端；测试只验证了组件本身，给人一种“已接线”的错觉。

**最小修复**：在 `WorkbenchPage`/`workbench.js` 里真正消费 `/room/stream`（用 `connectEventStream` + `OrderedEventBuffer`），并把非 2xx 分支改为：401/403 关闭，其余（429/5xx/网络）按指数退避重试；解析 `retry:` 字段。同时把测试改成断言 503 后会重试（例如 `attempts >= 2`）。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
grep -rn "connectEventStream(" --include=*.js --include=*.mjs . | grep -v node_modules
node - <<'EOF'
const fs=require('fs'),vm=require('vm');const ctx={TextDecoder,TextEncoder,AbortController,setTimeout,clearTimeout,console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('scripts/shared/workbench-core.js','utf8'),ctx);
let attempts=0;const errors=[];
const c=ctx.WorkbenchCore.connectEventStream({url:'/stream',retryDelayMs:5,
  fetchImpl:async()=>{attempts++;return{ok:false,status:503,body:null};},onError:e=>errors.push(e)});
setTimeout(()=>{console.log({attempts,closed:c.closed,status:errors[0]&&errors[0].status});},120);
EOF
```
**实际输出**
```
（grep 只匹配到两处定义 + client.js 注入副本 + test/ 的两处调用，没有生产调用点）
{ attempts: 1, closed: true, status: 503 }
```

---

### D-11（P2）DSH 草稿队列缺少静态实现的两条恢复路径：无草稿 409 的死锁，以及 stale 重排

**位置**
- `client.js:6209-6245`（`persistDraftOnce`：409 一律 `setConflict` + `setDraftState('error')` + `setDirtyFlag(true)`，没有“无草稿”分支）
- `client.js:6256-6264`（`reloadConflict`：`current.content` 不是字符串时只提示刷新并清空 conflict）
- `client.js:6402-6408`（`saveVersion`：`flushDraft()` 返回 false 且 conflict 存在时直接 return）
- `client.js:6266-6274`（`scheduleDraft` 只在下一次 input 时重排，无 stale 分支）
- 对照：`backend/manager/static/workbench.js:1377`（`if (result && result.stale) scheduleDraftSave(500);`）与 `workbench.js:1384-1427`（`putDraft` 的 epoch 回退）

**机制 A（死锁）**：另一标签页/设备丢弃草稿或保存正式版本（`save_version` 清草稿）会推进服务端的 `draft_epoch`（`workbench_db.py:670-686`、`chapter_editor.py:469-475`）；例如平板上的本地 Web 工作台保存了正式版本，桌面 DSH 面板的自动保存就会落入该分支。本标签页仍持有旧 `draft_id`，下次自动保存得到 409 且 `current_draft.draft_id = null`。DSH 把它当成普通冲突：弹 banner、保留 dirty、下一次按键再次 409；`Ctrl+S` 会先 `flushDraft`，同样 409 后 return。`reloadConflict` 因为 `current.content` 不是字符串而只提示“请刷新章节”。结果是**自动保存和正式保存都被卡死**，只能手动刷新页面恢复。静态实现遇到同一情况会在 5 个候选 epoch 上重试（`expected_draft_id=null`），自动恢复。

**机制 B（stale 重排）**：草稿 PUT 飞行中继续输入时，成功后 `editSeq` 已变化，`dirty` 保持 true，但没有新的定时器；用户停手后最后一段输入一直不落草稿，直到下一次按键/Ctrl+S/切章/隐藏页面。

**影响**：机制 A 会让当前章节在会话内完全无法保存（P2）；机制 B 是自动保存空窗，崩溃时丢最后一段（P3）。

**最小修复**：把 `workbench.js:1384-1427` 的 epoch 回退移植到 `persistDraftOnce`（或至少在没有 `current_draft.draft_id` 时设 `draftBlocked` 并提示“刷新章节”，不要无限重试）；成功回调补 `if (editSeqRef.current !== capture.seq) scheduleDraft();`。

**复现**：代码级对照。
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
grep -n "result.stale\|editSeqRef.current === capture.seq\|current_draft" client.js | head
grep -n "result.stale\|expected_draft_epoch: epoch\|draftBlocked = true" backend/manager/static/workbench.js | head
```
**实际输出**：`client.js:6229` 只有 `if (editSeqRef.current === capture.seq) setDirtyFlag(false);`，没有 else；`client.js:6231-6244` 对 409 只做 `setConflict`/`setDraftState('error')`；`workbench.js:1377` 有 `scheduleDraftSave(500)`，`workbench.js:1390-1427` 有 5 次 epoch 重试，`workbench.js:1448-1457` 有无草稿时 `draftBlocked = true` 的分支。

---

### D-12（P3）ARIA 结构错误：`role=list` 下是 button；tabpanel 无 labelledby；tab 无 roving tabindex；视图 tab 的 aria-controls 指向非 tabpanel

**位置**
- `backend/manager/static/index.html:160`（`<div id="wb-chapter-list" role="list">`）
- `backend/manager/static/workbench.js:845-867`（直接 append `<button>`，上一轮修复删掉了 `role="listitem"`）
- `backend/manager/static/index.html:184-222`（`role=tab` 有 `aria-controls`，5 个 `role=tabpanel` 均无 `aria-labelledby`）
- `backend/manager/static/index.html:113-115`（视图切换 `role=tablist`，`aria-controls` 指向 `#wb-write-view` / `#wb-outline-view`，但两者都不是 `role=tabpanel`）
- `backend/manager/static/workbench.js:2969-2989`（只切 `aria-selected`/hidden，无 roving tabindex）

**机制**：`role=list` 要求子项具有 `listitem` 角色；`button` 没有该角色，读屏会宣告“列表，0 项”。上一轮为修正“按钮被 listitem 覆盖”删掉了 `role="listitem"`，但没有改容器，留下更糟的组合。tablist 缺少 APG 期望的 `aria-labelledby`/方向键/单一 tab stop。

**影响**：章节目录对读屏用户不可导航为列表；工具 tabs 的语义关系不完整（P3，非阻断）。

**最小修复**：章节目录改为 `<ul role="list"><li><button>…</button></li></ul>`（或去掉 `role="list"`）；每个 tabpanel 加 `aria-labelledby="<tab id>"`；tab 使用 roving tabindex + 左右方向键；视图切换的两个容器加 `role="tabpanel"`。

**复现**：`tmp-d-probe.py` / `tmp-d-probe2.py`。
**实际输出**
```json
"#wb-chapter-list": {"role": "list", "name": "", "ignored": false},
"ax_chapter_list_children": {"role":"list","childRoles":["button","button"]},
"tabpanels_labelledby": [{"id":"wb-panel-annotations","labelledby":null,"hidden":false}, ...全部 null],
"tabs": [{"text":"批注","controls":"wb-panel-annotations","selected":"true","tabindex":null}, ...全部无 tabindex]
```

---

### D-13（P3）测试主要验证“字符串存在/文件够大”，删掉真实守卫仍然全绿

**位置**
- `test/workbench-ui.test.mjs:31-35`（`js.length > 40000`、`css.length > 12000` 即“实现存在”）
- `test/workbench-ui.test.mjs:67-74`（IME 测试只 `assert.match` 源码里的字符串）
- `test/workbench-ui.test.mjs:93-97`（no-innerHTML 只查源码）
- `test/client-workbench.test.mjs:101-103`（`typeof internals.WorkbenchPage === 'function'` 即“已导出”）
- 全套 159 个测试中，`WorkbenchPage` 从未被渲染；`workbench.js` 从未被执行

**机制**：`workbench-ui.test.mjs` 的 IME 断言依赖 `setEditorValue` 里的 `state.composing ... return false`（1061 行）仍然存在，所以即便把 `handleEditorInput` 的守卫整段删掉，测试依旧通过。类似地，`client-workbench.test.mjs` 只测纯函数（`wbDraftPayload` 等），不测组件行为，因此 D-01/D-03/D-06 这类缺陷没有任何测试能发现。

**影响**：测试给出虚假安全感；上面多个 P1/P2 都是在测试全绿的情况下存在的。

**最小修复**：为 `workbench.js` 增加一个最小 DOM harness（可用 `linkedom`/`happy-dom` 或 Playwright 的 page fixture）覆盖：切换章节期间 composition、陈旧草稿保存、抽屉焦点；为 `WorkbenchPage` 增加真实渲染测试（现有 `client-ui.test.mjs` 已有轻量 renderer 可复用）。至少把“只验字符串”的用例改成行为断言。

**复现**（副本中）
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2
cp -a buildtest mut && cd mut
python3 - <<'EOF'
from pathlib import Path
p=Path('backend/manager/static/workbench.js'); s=p.read_text()
old='  function handleEditorInput() {\n    if (state.composing || (state.adapter && state.adapter.composing)) return;'
assert old in s
p.write_text(s.replace(old,'  function handleEditorInput() {\n    /* MUTATION: guard deleted */'))
EOF
node --test test/workbench-ui.test.mjs
```
**实际输出**
```
✔ IME composition is guarded and .value is not overwritten mid-composition
ℹ pass 12
ℹ fail 0
```
守卫已被删除，测试仍宣称“IME composition is guarded”。

---

### D-14（P3）离页落盘没有 `pagehide` / `keepalive`：移动端关闭页面可能丢最后 ≤1.5s 草稿

**位置**
- `backend/manager/static/workbench.js:514-526`（只有 `beforeunload` 与 `visibilitychange`；`flushDraftNow()` 内部是普通 `fetch`）
- `backend/manager/static/workbench.js:225-240`（`api()` 未设置 `keepalive`）
- `client.js:6495-6515`（DSH 同样：beforeunload + visibilitychange，无 pagehide）
- `client.js:2996-3011`（`api()` 无 `keepalive`）

**机制**：移动端浏览器在页面进入后台/关闭时经常不执行 `beforeunload`；`visibilitychange` 发起的普通 fetch 可能在页面被终止时被丢弃。草稿只在内存 + 1.5s 防抖，没有 localStorage 兜底。

**影响**：在 1.5s 防抖窗口内关闭标签/切后台，最后一次输入丢失。桌面端崩溃同理。影响有限但真实，且修复成本低。

**最小修复**：在 `visibilitychange`/`pagehide` 时用 `fetch(url,{method:'PUT',headers,body,keepalive:true})`（`keepalive` 允许自定义头，`sendBeacon` 不行因为需要 `X-Novel-Helper`）；或同步写一份 localStorage 草稿作为兜底。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
grep -rn "pagehide\|keepalive\|sendBeacon" backend/manager/static/workbench.js client.js
```
**实际输出**：grep 无匹配（退出码 1，输出为空）；两处只有 `beforeunload` + `visibilitychange`。

---

### D-15（P3）`client.js` 5.0 MiB，其中 90.6% 是 base64 字体 CSS；字体在包内还重复分发一份

**位置**
- `client.js:1271-2393`（`BEGIN/END GENERATED ATELIER CSS`）
- `scripts/build-client-ui.py:79-88`（三个 woff2 → base64 → 4096 字符分块字符串）
- `package.json` `files` 同时包含 `client.js` 与 `assets/`

**影响**：插件模块每次加载要解析 5.03 MiB JS + 注入约 4.78 MiB CSS（含 4.4 MiB base64 字体）；npm 包 24.6 MiB 解包体积中 client.js 5.03 MiB、字体文件又 3.17 MiB。`npm pack --dry-run` 实测：1250 个文件、24.6 MiB unpacked / 12.06 MiB packed。

**最小修复**：CJK 字体做子集化（本项目界面用字远少于全字库），或改为按需加载的外部 woff2（`new URL('./assets/fonts/x.woff2', import.meta.url)` 不适用于 DSH 面板时可用宿主静态路由），至少不要同时分发“字体文件 + base64 副本”。

**复现**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
python3 -c "s=open('client.js',encoding='utf-8').read(); i=s.index('const ATELIER_CSS'); j=s.index('const WORKBENCH_CSS'); print('client bytes',len(s.encode()),'ATELIER region',len(s[i:j].encode()),'share',round(100*len(s[i:j].encode())/len(s.encode()),1),'%')"
cd ../buildtest && npm pack --dry-run --json 2>/dev/null > pack.json
python3 -c "import json; d=json.load(open('pack.json'))['dsh-chapter-whale']; print('files',len(d['files']),'unpacked',round(d['unpackedSize']/1048576,2),'MiB','packed',round(d['size']/1048576,2),'MiB'); [print(round(f['size']/1048576,2),'MiB',f['path']) for f in sorted(d['files'],key=lambda x:-x['size'])[:6]]"
```
**实际输出**
```
client bytes 5271255 ATELIER region 4776025 share 90.6 %
files 1250 unpacked 24.6 MiB packed 12.06 MiB
5.03 MiB client.js / 1.87 MiB notosanssc.woff2 / 1.3 MiB notoserifsc.woff2
```

---

### D-16（P3）761–767px 断点重叠：桌面 dock 规则与移动底栏/抽屉规则同时生效

**位置**
- `backend/manager/static/liquid-glass.css:179-187`（`@media (min-width: 761px)` 隐藏 `.sidebar`/`.topbar`，改用顶部 dock）
- `backend/manager/static/editorial.css:302`、`351`、`438`、`507`（`max-width: 767px` 显示 `.mobile-dock`、加 80px 底部内边距）
- `backend/manager/static/workbench.css:1583`（`max-width: 767px` 抽屉改为 fixed）
- `backend/manager/static/editorial.css:422`、`436`（仍是 `max-width: 760px`）

**机制**：上一轮把移动断点从 760 改到 767，但 `liquid-glass.css` 的 `min-width: 761px` 没有同步；在 761–767px 这 7px 内，`sidebar/topbar` 已按桌面隐藏，而移动底栏、80px 底部留白、工作台抽屉的移动形态仍然生效。

**影响**：小尺寸平板/横屏手机在 761–767px 出现“顶部 dock + 底部 dock”双导航、混合布局；是不可见但真实的回归。

**最小修复**：把 `liquid-glass.css` 的 `min-width: 761px` 改为 `768px`，并统一 `editorial.css` 里遗留的 `760px` 为 `767px`（或反过来把移动断点统一到 760）。

**复现**：`tmp-d-probe3.py`。
**实际输出**
```json
"760": {"sidebar":"flex","topbar":"flex","mobileDock":"flex","wbLeftPosition":"fixed","mainPaddingBottom":"80px"},
"763": {"sidebar":"none","topbar":"none","mobileDock":"flex","wbLeftPosition":"fixed","mainPaddingBottom":"80px"},
"767": {"sidebar":"none","topbar":"none","mobileDock":"flex","wbLeftPosition":"fixed","mainPaddingBottom":"80px"},
"768": {"sidebar":"none","topbar":"none","mobileDock":"none","wbLeftPosition":"static","mainPaddingBottom":"42px"}
```

---

### D-17（P4）桌面筛选 chip 23px 高，低于 WCAG 2.5.8 的 24×24

**位置**：`backend/manager/static/workbench.css:313-321`（`padding: 3px 8px; font-size: 9px`），上一轮只在移动端加了 `min-height: 28px`（`workbench.css:1844-1852`）。

**影响**：桌面指针用户（尤其运动障碍）目标偏小；23px 差 1px 未达 AA 最小值，3px 间距也不满足 24px 圆例外。移动端实测 31px 合格。

**最小修复**：桌面也设 `min-height: 24px; padding: 4px 9px;`。

**复现**：`tmp-d-probe5.py`。
**实际输出**：`desktop.filters = [{w:36,h:23},{w:45,h:23},…]`；`mobile.filters = [{w:43,h:31},…]`。

---

### D-18（P4）大纲/设定 textarea 的可访问名只来自 placeholder，输入后即消失

**位置**：`backend/manager/static/index.html:250`（`#wb-outline-text`）、`266`（`#wb-lore-text`）——没有 `<label>`/`aria-label`/`aria-labelledby`。

**影响**：Chromium 会把 placeholder 当 fallback 名称（实测 name=“选择左侧大纲文件后编辑”），但一旦输入，读屏用户失去字段名称；标题 `<strong id="wb-outline-name">` 也没有关联。属 WCAG 1.3.1/4.1.2 的弱实现。

**最小修复**：`aria-labelledby="wb-outline-name"`（并给 `wb-outline-name` 一个固定文案）+ 可选的 `aria-describedby` 指向状态行。

**复现**：`tmp-d-probe2.py`。
**实际输出**
```json
"#wb-outline-text": {"role":"textbox","name":"选择左侧大纲文件后编辑","ignored":false},
"#wb-lore-text": {"role":"textbox","name":"选择左侧设定文件后编辑","ignored":false}
```

---

## 2. 双实现漂移清单（静态 `workbench.js` vs DSH `WorkbenchPage`）

| 能力 | 静态 Web 工作台 | DSH 面板 | 结论 |
|---|---|---|---|
| 编辑器内核（偏移/撤销/合并） | `WorkbenchCore` | `WorkbenchCore`（同源注入） | 一致（字节相同） |
| 陈旧草稿基线 | 用当前版本（D-01） | 用草稿 base（正确） | **漂移（P1）** |
| IME 中断兜底 | blur + visibilitychange | 无（D-06） | **漂移（P2）** |
| 草稿 stale 重排 | `scheduleDraftSave(500)` | 无（D-11） | 漂移（P3） |
| 无草稿 409 的 epoch 恢复 | `putDraft` 5 次回退 | 无，保存死锁（D-11） | **漂移（P2）** |
| 切章 IME 拦截 | openChapter 前检查 + 死守卫 | 无检查 | 两者都有缺陷 |
| 脏状态拆分/删除 | 允许（confirm 后） | 拒绝 | 漂移 |
| 批注 CRUD | 有 UI（契约错误，D-02） | 只有摘要 | 漂移（功能缺失） |
| 导入/回收站/大纲/设定/检索/世界状态 | 全部有 | 无 | 功能面差异 |
| 快捷键 Ctrl+S | 文档级（D-05） | 组件挂载期 | 都有全局性，作用域不同 |
| 主题/外观 | liquid-glass v5 dock | DSH 自带 | 两套视觉系统 |

这里不把“功能面差异”本身判为缺陷（DSH 面板可能是精简版），但 D-01/D-06/D-11 是同一语义的两种实现给出不同安全等级，属于必须收敛的漂移。

## 3. 发布链与清单核对结果

**通过**：
- `node scripts/check-release.mjs --local` → `发行清单校验通过：1188 个文件与清单一致，buildId=8caf3b60...`（HEAD，未受污染时）
- `runtime-manifest.json` 的 `buildId` 用 Python 独立复算（`sha256(json.dumps(files, sort_keys=True))`）与清单一致
- `manifest.packageVersion = 0.7.5` = `package.json.version`；`manifest.version = 0.7.0` 与 `runtime-download.json` 的 `...-0.7.0.tgz` 一致（runtime 复用，检查器按 `manifest.version` 校验 URL，符合设计）
- `runtime-download.json` 的 `buildId` 与清单一致，`runtimeAssetBuildId`/`sha256` 格式合法；`managed-runtime.mjs:186-215` 在下载后用 `runtimeAssetBuildId` 再校验
- `market/index.json` 与 `market/losebird-entry.json` 均为 0.7.5（等于 package.json，检查器允许；是否已发布 npm 无法离线验证）

**风险/缺口**：
- 清单只覆盖 `backend/` + `runtime/`；`client.js`、`assets/`、`package.json` 本身不参与哈希（`build-runtime.py:49-62`），因此 D-08 的漂移不会被 `check-release` 发现。
- `runtime-download.json` 的 `bytes=282727542` / `sha256` 无本地 runtime 资产可对照，本次无法离线验证（环境限制，不是发现）。
- `check-release` 的 CRLF 检查只覆盖 `.py/.js/.css/...` 且要求同时出现 `\r` 与 `\n`；孤立 `\r` 不会触发（低风险，未列入正式发现）。

## 4. 复测与通过项（含上一轮 P1）

| 项 | 方法 | 结果 |
|---|---|---|
| 共享内核双份字节一致 | `sha256sum scripts/shared/workbench-core.js backend/manager/static/workbench-core.js` | 均为 `f2a120c2...`，一致 |
| `client.js` 生成内核块 == 源文件 | Python 切片比较 | `True`，39530 bytes |
| `ATELIER_CSS` == 字体 + base + native | 重新拼装后比较 | `True`，4579598 chars |
| 构建幂等 | 副本中跑 `build-client-ui.py` 后 `diff -rq` | 无差异 |
| 全量测试（隔离副本，装好 `tar`） | `node --test test/*.test.mjs` | 159 tests / 143 pass / 0 fail / 16 skip |
| Ctrl+S（任意焦点） | Playwright 键盘 | 触发 `PUT /chapters/2`，有“正式版本已保存”提示（文档级处理生效；副作用见 D-05） |
| 移动抽屉 `aria-expanded` | Playwright | 初始 `false`，打开后 `true`（修复有效） |
| 移动选区条避让 dock | CSS 检查 | `bottom: calc(85px + env(safe-area-inset-bottom))`（修复有效） |
| 移动筛选目标 | Playwright 测量 | 31px 高（修复有效） |
| 静态 IME blur/visibility 兜底 | 源码 370-388 | 存在（但 DSH 未同步，D-06） |
| 浮动条视口钳制 | 现有单测 + 代码 | 旧断言通过；新增 `viewport` 分支没有单测覆盖（次要测试缺口） |
| 切章前草稿顺序 | Playwright 网络日志 | `PUT .../chapters/2/draft` 先于 `GET .../chapters/1`，无跨章串写 |
| 三路合并 | 3000 组随机输入 | 0 崩溃、0 “clean 但含冲突标记”、0 “非 clean 但无标记” |
| XSS/文本注入（本次范围） | `grep` + 源码审阅 | `client.js`/`workbench.js` 无 `innerHTML/outerHTML/insertAdjacentHTML/document.write`；workbench 全部 `textContent`；client.js 仅 `safeHttpUrl`/`safeQrSrc` 进入 `href/src`，二者有协议白名单；`app.js` 的 29 处 `innerHTML` 抽查未发现未转义的项目文本（模板中的 `${role}`/枚举值为常量） |
| 事件流代理 | `index.js:906-945` | SSE 透传、`Last-Event-ID` 转发、不缓冲，正确 |

## 5. 复现脚本

| 脚本 | 用途 |
|---|---|
| `/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-d-stub.py` | 只读 stub：服务 `backend/manager/static` + 最小 `/api/*`，记录请求到 `tmp-d-requests.jsonl`；支持 `/__delay`、`/__stale` |
| `tmp-d-probe.py` | D-02/D-05/D-12：桌面 AX 树、大纲 Ctrl+S、批注 POST、自动草稿 |
| `tmp-d-probe2.py` | D-12/D-18：可见面板的 AX 名称、切章顺序、tab/panel 关系 |
| `tmp-d-probe3.py` | D-04/D-16：移动抽屉焦点/Tab 顺序、761–767 断点矩阵 |
| `tmp-d-probe4.py` | D-03：延迟 GET 期间 composition 被覆盖 |
| `tmp-d-probe5.py` | D-17：交互目标尺寸 |
| `tmp-d-probe6.py` | D-01：陈旧草稿 Ctrl+S 的 expected 字段 |
| `tmp-d-focus.py` | D-07：从 `client.js` 抽 CSS 后测量焦点环 |
| `/home/ubuntu/.hermes/cache/scratch/audit-v2/buildtest`、`mut`、`mut2` | 构建幂等 / 测试变异 / CSS 漂移实验的隔离副本 |

启动 stub 后所有 Playwright 脚本均以
`/home/ubuntu/venvs/dsh/bin/python <script>` 运行，Chromium 使用
`/home/ubuntu/.cache/ms-playwright/chromium-1200/chrome-linux64/chrome`（Playwright 1.63 默认找 1243，需显式 `executable_path`）。

## 6. 环境与限制

- 仓库无 `runtime/`，`runtime-download.json` 的 282 MB 资产无法离线校验；market 是否已在 npm 发布同样无法离线验证。
- 本机 Playwright 自带 `chromium-1200`，与 `playwright 1.63` 期望的 `1243` 不一致，脚本显式指定可执行文件；这不影响页面行为结论。
- 审计期间仓库目录出现 `node_modules/`（12:32）与 `backend/integration_data/agent_room.sqlite3`（12:31）；我未执行 `npm install` 或 Python 后端测试，判断为并发的其他审计进程写入。本报告所有会写盘的实验都在 `audit-v2/` 下的副本中完成，仓库受版本控制的文件 `git diff` 为空。
- `check-release` 曾在仓库内因外部进程写入的 `backend/integration_data` 报 1 项错误；在干净副本中恢复为通过。这是环境噪声，不是代码发现。
- 无网络：未对 GitHub/npm 资产做可用性验证；未安装任何依赖，使用现有 `node_modules` 与 venv。

---

## 7. 一句话总结

当前 HEAD 的前端“看起来”很完整（无 innerHTML、内核双份字节一致、测试 143 绿），但真实浏览器验证暴露出一个数据丢失级缺陷（陈旧草稿覆盖正式版本）和一组只在真实交互中才出现的 IME/焦点/契约问题；同时构建链无法发现 `client.js` 内嵌 CSS 的漂移，测试体系主要验证字符串存在而非行为，两个工作台实现已经出现安全等级不一致的漂移。
