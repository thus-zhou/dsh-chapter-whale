# 审计报告 D · 前端 / 桌面 UI / 可访问性 / 静态资产 / 构建与测试覆盖

- 仓库：`/home/ubuntu/projects/dsh-chapter-whale`
- 分支：`feat/v0.8-v0.9.5`，HEAD `fe2bc32 fix(ci): normalize cross-platform paths, fsync and sqlite cleanup`
- 方式：只读静态审计 + 在 scratch 副本中执行构建/测试（未修改仓库任何文件，未 commit/push，未联网）
- 范围：`client.js`（WorkbenchPage 与生成块）、`backend/manager/static/workbench.js`、`workbench.css`、`workbench-core.js`、`index.html`、`scripts/build-client-ui.py`、`scripts/shared/workbench-core.js`、`test/workbench-ui.test.mjs`、`test/workbench-core.test.mjs`、`test/client-workbench.test.mjs`、`index.js` 中与 UI 相关的路由/代理
- 证据等级：**实测** = 本次实际执行命令的输出；**静态事实** = 代码/样式表中可直接判定；**静态假设** = 需要运行时才能确认，已在条目标注并降级

## 0. 结论摘要

两套工作台（DSH 面板内 `client.js:WorkbenchPage` 与 本地 Web UI `workbench.js`）共用同一 `workbench-core.js`，共享内核质量较高（字节一致、构建幂等、核心单测为真行为测试）。真正的问题集中在 **UI 适配层**：同一份内核被两套手写实现包了两遍，只有 1183 行的内核共享，UI 层（3025 行 vs 1082 行）完全分叉，导致 IME 守卫、Ctrl+S、草稿落盘、焦点可见性在两套实现里行为不同且互不一致。

| 严重度 | 数量 |
| --- | --- |
| P0 | 0 |
| P1 | 5 |
| P2 | 9 |
| P3 | 12 |
| 合计 | 26 |

未发现可执行 XSS（两次独立取证，见 §5.1）。未发现构建非幂等或生成块字节漂移（见 §5.2）。测试 34/34 通过，但其中 9 条属于"只验存在"的正则断言，且存在一条**假绿**（F15）。

## 1. P1（5 条）

### F1 章节载入半应用：`force` 失效导致跨章正文污染

- 位置：`backend/manager/static/workbench.js:1016-1019`（`applyChapter`）、`workbench.js:1044-1052`（`setEditorValue`）、`workbench.js:941-944`（`openChapter` 的 composing 守卫）
- 机制（静态事实）：
```js
// workbench.js:1044
function setEditorValue(text, title, force) {
  if (!els.editor) return false;
  if (state.composing || (state.adapter && state.adapter.composing)) return false;   // 1046
  if (!force && state.composing) return false;                                       // 1047 ← 不可达
  ...
}
```
  `1047` 被 `1046` 完全包含，`force` 对结果**没有任何影响**。而 `applyChapter` 在调用它之前已经把状态改成新章节：
```js
// workbench.js:984-1001
state.chapter = data; state.currentId = Number(data.id);
state.baseContent = String(data.content || "");
state.adapter = new Core.EditorAdapter({ text: content, title: title });   // 997 已换成新章正文
state.persistedSignature = signature(title, content);                      // 1003 已换成新章签名
// workbench.js:1016
if (!setEditorValue(content, title, true)) {
  banner("输入法仍在组合文字，已推迟载入第 " + state.currentId + " 章。", "error");
  return;                                                                  // 1018 直接返回
}
setEditorEmpty(false);   // 1020 永不执行
```
  `openChapter` 只在**发起请求前**检查 `state.composing`（941），请求 `await` 期间（超时 25s）用户完全可以在标题框或正文框起一个中文输入法组合。
- 影响：
  1. 编辑器 DOM 仍是**上一章**的正文，但 `state.chapter/currentId/baseContent/adapter/persistedSignature` 全部指向**新章**；
  2. `compositionend` → `handleEditorInput`（1056）→ `state.dirty = signature(旧章标题, 旧章正文) !== persistedSignature(新章)` → `true` → 1.5s 后把**旧章正文写入新章的草稿**（`putDraft` 用 `state.currentId`，1365）；此时按 Ctrl+S 则把旧章正文写成**新章的正式版本**；
  3. 若切换前处于"无章节"空态（`setEditorEmpty(true)` 已 `disabled` 编辑器），`1020` 被跳过 → 新章载入后编辑器**仍是 disabled**，界面死锁，仅有一条 banner；
  4. `updateEditorMeta`/`markActiveChapter`/`renderAnnotations` 未执行，侧栏高亮与"第 N 章"标题停在旧值。
- 最小修复：`setEditorValue` 改为 `if (!force && (state.composing || (state.adapter && state.adapter.composing))) return false;`（`force` 时照样写 DOM，仅在核心里标记 composing）；`applyChapter` 把 `setEditorValue` 移到所有状态赋值之前，失败则不落任何状态（或记录 `pendingChapter` 在 `compositionend` 里重放）；`1020` 之前加 `finally` 语义。
- 证据：`sed -n '1044,1052p'` + `sed -n '984,1020p'`（原文见上）；测试用例 `test/workbench-ui.test.mjs:67-75` 通过，但无法覆盖此路径（见 F15）。

### F2 `state.composing` 是单向闩锁，无任何复位路径

- 位置：`workbench.js:370-378`（仅 `compositionstart`/`compositionend` 两个监听）、`workbench.js:941`、`1326-1329`、`1443-1446`
- 机制（静态事实）：`state.composing` 只有两个写入点，全部来自 textarea 的组合事件；**没有** `blur`、`compositioncancel`、`visibilitychange`、超时兜底：
```
$ grep -n "\"blur\"\|onblur\|compositioncancel" backend/manager/static/workbench.js
(无输出)
```
  一旦 `compositionend` 未被补发，`state.composing` 永远为 `true`，而它是三个关键路径的硬闸门：`saveDraftNow`（1326，改为 `scheduleDraftSave(400)` 自循环，400ms 一次永不停止）、`saveVersion`（1443，弹"请完成后再保存"）、`openChapter`/`loadProject`（941/614，禁止切章切作品）。唯一恢复手段是刷新页面。
- 影响：编辑器进入"能打字但永不落盘、不能切章"的状态；配合 F1，`setEditorValue` 也会持续拒绝任何服务端内容。
- 静态假设：`compositionend` 是否会在特定浏览器/切后台/输入法崩溃时漏发，无法在无浏览器环境下确认；但"代码里没有任何复位路径"是既成事实，该缺陷的触发概率完全取决于外部行为，属于典型的单点脆弱设计。
- 最小修复：在 `bindEvents` 中增加 `on(els.editor, "blur", ...)` 与 `document visibilitychange` 重置 `state.composing=false` + `adapter.endComposition()`；`applyChapter` 侧加"推迟后重放"。
- 证据：上述 grep 无输出；`scheduleDraftSave` 自循环见 `1326-1328`。

### F3 移动端选区浮条覆盖底部主导航（z-index 79 vs 40，同一 `bottom:0`）

- 位置：`workbench.css:1336-1350`（`.wb-selbar` 基样式）、`workbench.css:1773-1782`（≤767px 覆盖）、`editorial.css:302-310`（`.mobile-dock`）
- 机制（静态事实）：
  - `.wb-selbar { position: fixed; z-index: 79; left:50%; bottom: calc(14px + env(safe-area-inset-bottom)); }`
  - ≤767px 覆盖为 `left:0; right:0; bottom:0; transform:none; border-radius:0;` → 变成贴底全宽条
  - `.mobile-dock { display:flex; position:fixed; z-index:40; bottom:0; left:0; right:0; }`（`editorial.css:306`）
  - 两者都是 `bottom:0`，浮条 z-index 更高 → **浮条绘制在主导航之上**。
- 影响：手机上有选区时（`showSelBar`，`workbench.js:1862`），"工作台/作品/创作/日更/进度"五个主导航被压在浮条下。`toggleDrawer`/`hideSelectionUI` 只由 `document pointerdown` 触发，而点在浮条上时 `bindEvents` 的 `if (els.selbar.contains(event.target)) return;`（516）会直接返回，于是**想点导航的手指落在"关闭/批注/定位"按钮上**，既不导航也不关闭浮条。
- 定量（按 CSS 计算，非浏览器实测）：dock 高 ≈ 7+ (7+19+5+16.5+7) +7 ≈ 68.5px；selbar 高 ≈ 8+ (6+15.7+6) +8 ≈ 43.7px → 覆盖 dock 下部约 44px（含整个文字标签行），dock 每条链接仅顶部约 10–18px 可点。
- 佐证（同一份 CSS 内部的不一致）：同一断点里 `.toasts { bottom: calc(85px + env(safe-area-inset-bottom)); }`（`editorial.css:310`）已经为底部 dock 让出 85px，而浮条让出 0px。
- 最小修复：`.wb-selbar` 移动端改为 `bottom: calc(85px + env(safe-area-inset-bottom))`（或引入 `--dock-h` 变量），或把浮条改成 dock 上方的可关闭 sheet。
- 证据：`grep -n "z-index" workbench.css` → `1265:80 / 1340:79 / 1381:65 / 1702:70`；`editorial.css:306 z-index:40`。

### F4 面板版工作台没有任何离页落盘（无 `beforeunload` / `pagehide` / `sendBeacon`）

- 位置：`client.js:6261-6277`（`scheduleDraft`/`flushDraft`）、`client.js:6491-6497`（卸载清理）
- 机制（静态事实）：
```
$ grep -n "beforeunload\|pagehide\|visibilitychange\|navigator.sendBeacon" client.js
3216, 9759, 13956   ← 全部属于其它页面（dashboard/reader/background），WorkbenchPage 无
```
  `WorkbenchPage` 只在组件卸载时做一次 fire-and-forget：
```js
React.useEffect(() => () => {
  if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
  if (dirtyRef.current) { const capture = captureDraft(); if (capture) queueDraftSave(capture); }
}, []);   // 6491
```
  本地 Web UI 版是有的：`workbench.js:504-514` 同时挂了 `beforeunload`（脏则 `preventDefault`）与 `visibilitychange→hidden` 立即 `flushDraftNow()`。
- 影响：DSH 面板里关闭窗口/宿主退出时，最近 1.5s 内（`scheduleDraft` 的 1500ms 防抖，`6263`）甚至更久的输入不会被持久化；卸载时发出的 PUT 在进程终止场景下必然被丢弃，且**浏览器连"未保存"提醒都不会弹**（没有 `beforeunload` 返回值）。两套 UI 对同一份数据的安全承诺不同。
- 最小修复：在 `WorkbenchPage` 里补 `beforeunload`（`dirtyRef.current` 时 `preventDefault`）+ `visibilitychange` 立即 `queueDraftSave`，并考虑 `navigator.sendBeacon` 兜底；或把 `workbench.js` 的 flush 策略抽进 core 复用。
- 证据：上述 grep 输出；`workbench.js:504-514` 对照。

### F5 面板正文编辑器没有可见焦点指示（`outline:none` + textarea 不在 `:focus-visible` 列表）

- 位置：`client.js:5827`（`.wb-textarea { ... outline: none; }`）、`client.js:5809`（`.wb-titleinput { ... outline: none; }`）、`client.js:2360`（全局 `:focus-visible` 选择器列表）
- 机制（静态事实）：atelier 的焦点环只覆盖四类元素：
```
.nh-root[data-ui="atelier"] button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible
  { outline: 2px solid var(--a); outline-offset: 4px }
```
  **没有 `textarea`**。而 `.wb-textarea` 又显式 `outline:none`，`.wb-titleinput` 在 `:focus` 时只把 `border-bottom-color` 从 `--line` 换成 `--line-strong`（色差极小）。
- 影响：面板里的主写作区（一个占满中央栏的 textarea）在键盘焦点下视觉上没有任何变化，违反 WCAG 2.4.7（Focus Visible，AA）。键盘用户 Tab 进正文后无法判断焦点在哪；对比本地 Web UI：`style.css` 的 `:focus-visible{outline:2px solid var(--red)}` 未限定标签，textarea 仍然有焦点环（`.wb-editor` 只覆盖了 `border`/`box-shadow`）。
- 最小修复：`:focus-visible` 列表补 `textarea`（或单独 `.wb-textarea:focus-visible{outline:2px solid var(--a);outline-offset:-2px}`），`.wb-titleinput` 的 `:focus` 改为 `:focus-visible` 并加 outline。
- 证据：`grep -n "focus-visible" client.js` → 仅 `client.js:2360` 一处、列表无 textarea；`awk` 抽取 5809/5827 两行原文（见上）。

## 2. P2（9 条）

### F6 Ctrl+S 只在正文 textarea 生效，标题/大纲/设定输入框会触发浏览器"另存为"

- 位置：`workbench.js:383`（`on(els.editor, "keydown", handleEditorKeyDown)`）、`workbench.js:1114-1121`
- 机制：`handleEditorKeyDown` 只绑在 `#wb-editor` 上；`#wb-title`（index.html:165）、`#wb-outline-text`（250）、`#wb-lore-text`（266）、`#wb-bubble-input`（288）、`#wb-annotation-input`（196）均无 keydown 处理，`document` 级也无兜底（对照 `client.js:6480-6489` 面板版是 `document.addEventListener('keydown')` 全局）。
- 影响：作者在标题框里按 Ctrl+S（"改完标题顺手存一下"是最常见操作）→ `preventDefault` 不生效 → Chrome/Edge 弹出"另存为网页"对话框，**章节一个字节都没保存**，且 `beforeunload` 不会介入（不是导航）。
- 最小修复：把 Ctrl+S/Ctrl+Z/Ctrl+Y 提到 `document` 级并判断 `#page-workbench` 是否可见，或至少在 `#wb-title` 上复用 `handleEditorKeyDown`。
- 证据：`grep -n "keydown" workbench.js` 仅 383 行；`index.html` 上述输入框无 `onkeydown`。

### F7 移动端抽屉：无滚动锁、无 `aria-expanded`、无 `aria-modal`、无焦点陷阱，离屏抽屉仍在 Tab 序列

- 位置：`workbench.js:1234-1251`（`toggleDrawer`）、`workbench.css:1699-1734`（≤767px `.wb-left/.wb-right{position:fixed;transform:translateX(-105%)/translateY(105%)}`）、`index.html:147-149`（`#wb-mobile-left/#wb-mobile-right` 无任何 aria）
- 机制（静态事实）：
  1. `toggleDrawer` 只切 `.is-open` class 与 `.wb-backdrop` 的 `hidden`，**从不设置** `document.body` 的滚动锁；而同一份代码里存在现成机制 `style.css:6 body.modal-open{overflow:hidden}`，`app.js:348/351/549` 对 `<dialog>` 是用了的 —— 工作台抽屉没用；
  2. 抽屉靠 `transform: translateX(-105%)` 隐藏，元素仍在渲染树与可访问性树中，内部 100+ 个按钮（章节项、筛选、分页脚）仍然可 Tab 可达、可被读屏枚举；
  3. 触发按钮没有 `aria-expanded`/`aria-controls`，抽屉本身没有 `role="dialog" aria-modal="true"`，也没有焦点移入/陷阱。
- 影响：键盘/读屏用户在手机上会 Tab 进一个看不见的抽屉；打开抽屉后手指在遮罩上滑动会继续滚动背后的正文（滚动链），编辑器滚动位置被意外改变。
- 最小修复：`toggleDrawer` 里同步 `document.body.classList.toggle('modal-open', anyOpen)`，抽屉加 `inert`（关闭时）或 `hidden`，两个触发按钮加 `aria-expanded`/`aria-controls`，打开时 `focus()` 第一个可聚焦元素并在 Escape/关闭时回焦。
- 证据：`grep -rn "modal-open" backend/manager/static/*.js` → 只有 `app.js`；`workbench.js` 无；CSS 原文见上。

### F8 `role="listitem"` 覆盖 `<button>` 语义，章节列表对读屏变成"不可操作项"

- 位置：`workbench.js:835`（`button.setAttribute("role", "listitem")`）、`index.html:160`（`<div class="wb-chapter-list" role="list">`）
- 机制：每个章节项本是 `<button type="button">`，JS 又把 `role` 改成 `listitem`。ARIA 规定显式 role 覆盖原生 role，于是按钮不再是 button，读屏不再播报"按钮"、不提示可回车/空格激活（键盘行为仍由原生元素提供，但语义丢失）。
- 影响：章节列表是工作台唯一的导航入口，读屏用户听到的是"第 12 章 xxx 3000 字，列表项"，不知道可以按。
- 最小修复：删除 `setAttribute("role","listitem")`；若要保留列表语义，用 `<ul role="list"><li><button>` 结构，或给按钮加 `aria-current="true"`（已有，见 931）而不改 role。
- 证据：`grep -n "setAttribute" workbench.js` → `835: button.setAttribute("role", "listitem")`；`index.html:160` 原文 `<div class="wb-chapter-list" id="wb-chapter-list" role="list">`。

### F9 `.wb-tabs` 是 4 列网格，但 HTML 里有 5 个 tab（"世界状态"换行错位）

- 位置：`workbench.css:637-641`（`grid-template-columns: repeat(4, minmax(0, 1fr))`）vs `index.html:185-189`（annotations / check / versions / reference / insights 共 5 个 `role="tab"`）
- 机制（静态事实）：5 个按钮塞进 4 列网格 → 第 5 个"世界状态"落到第二行第 1 列，右栏头部 `padding-right:34px`（`workbench.css:667-670`）只对第一行生效，视觉上出现"一行四个 + 孤零零一个"的错位；同时 `.wb-right-head` 高度增加，挤压下方 `.wb-panel`。
- 影响：右栏工具条明显不整齐；"世界状态"作为新增 tab 在视觉上像被丢弃的项。
- 最小修复：`repeat(4, …)` → `repeat(5, …)`（或 `grid-auto-flow: column; grid-auto-columns: 1fr`），并复核 `.wb-tabs button` 的 `padding: 6px 2px; font-size: 9.5px` 在 5 列下是否还放得下中文标签。
- 证据：`grep -n "repeat(4\|repeat(5)\|wb-tabs" workbench.css` → 仅 `639: repeat(4, minmax(0, 1fr))`；`index.html` 185-189 五个 `data-wb-tab`。

### F10 移动端触摸目标小于 24×24（WCAG 2.5.8 AA）

- 位置：`workbench.css:313-320`（`.wb-filters button`：`font-size:9px; padding:3px 8px`）、`workbench.css:1744-1747`（≤767px `.wb-tabs button{padding:7px 2px;font-size:10px}`）、`workbench.css:1792-1795`（`.wb-selbar-actions button{padding:6px 7px;font-size:9.5px}`）
- 机制（按 CSS 计算）：行高继承 `1.65` → 筛选胶囊高 ≈ 9×1.65+6+2 ≈ **22.9px**；tab ≈ 10×1.65+14 ≈ **30.5px**；浮条按钮 ≈ 9.5×1.65+12 ≈ **27.7px**。20px 级别的筛选条（"全部/未定稿/已发布/待采纳"）低于 24px 下限。
- 影响：手指误触率高；筛选条四个胶囊间距仅 `gap:3px`（308），相邻目标几乎粘连。
- 最小修复：移动端把 `.wb-filters button` 提到 `padding:8px 12px;font-size:11px`，或改用 `min-height:24px`（推荐 44px 的 `.button` 规格）。
- 证据：CSS 原文 + 上述算术；未在真机复测（无浏览器可用，见 §6）。

### F11 选区气泡只对"编辑器矩形"夹取，无视口/标签栏/底栏避让

- 位置：`workbench-core.js:328-361`（`floatBarPosition`）、`workbench.js:1824-1859`（`showBubbleAt`）、`workbench.css:233-243`（`.wb-shell{height:clamp(560px, calc(100vh - 252px), 1080px)}`）
- 机制（静态事实）：`floatBarPosition` 的夹取边界只有 `editorRect`（`minimumTop/maximumTop = editorTop+margin / editorBottom-margin-barHeight`），从不参考 `window.innerHeight`；`showBubbleAt` 传入的是 `getBoundingClientRect()` 的编辑器矩形。而 `.wb-shell` 有 560px 的**最小高度**，在窗口高度 < ~810px 时 shell 底部会超出视口。
- 影响：矮窗口（笔记本 720p、分屏、面板内嵌）里在正文靠下位置划词，气泡被夹到 `editorBottom-8-height`，即视口之外 → 浮条"消失"，用户以为复制/批注坏了（`handleEditorMouseUp` 只在 `coarse` 指针时退回 selbar，鼠标用户没有退路）。
- 最小修复：`floatBarPosition` 增加 `viewport` 入参（`{top:0,bottom:innerHeight}`）参与夹取；或在 `showBubbleAt` 里先 `Math.min(editorRect.bottom, innerHeight)`。
- 证据：核心 328-361 全文；`workbench.css:236` 的 `clamp(560px, …)`；`workbench-core.test.mjs:178-202` 只断言"clamp inside editor"，正好绕过了这一层。

### F12 批注锚点使用陈旧选区（编辑后偏移量不再对应原文）

- 位置：`workbench.js:1985-2009`（`submitAnnotation`）、`workbench.js:1959-1983`（`addLocalAnnotation`）、`workbench.js:1770-1790`（`captureSelection`）
- 机制：选区只在 `select/mouseup/pointerup/keyup` 时刷新（380-384），`handleEditorInput`（1056）不重算。`submitAnnotation` 只判断 `if (!state.selection.text)`，不重新 `captureSelection()`，直接把 `state.selection.startCp/endCp` 发给服务端。
- 影响：划词 → 在选区之前插入/删除几个字 → 点"提交到批注接口"，服务端落库的是错误位置的锚点（可能指向完全不相干的段落），且 `quote` 与 `start/end` 自相矛盾。这类脏数据会污染后续的"待采纳"统计与自动改稿。
- 最小修复：`submitAnnotation` 开头无条件 `captureSelection()`，并在 `handleEditorInput` 里把 `state.selection` 标记为 stale（或按 delta 平移 cp 偏移）。
- 证据：1985-2009 与 1770-1790 原文；`grep -n "captureSelection()" workbench.js` 的调用点不含 `submitAnnotation`。

### F13 SSE 客户端栈零调用（死代码），且 `connectEventStream` 遇非 2xx 永久 `close()` 不重连

- 位置：`workbench-core.js:980-1114`（`connectEventStream`）、`1047-1053`（非 ok → `report` + `close()` + `return`）、`workbench-core.js:363-442`（`SseParser`）、`449-499`（`OrderedEventBuffer`）
- 机制（静态事实）：
```
$ grep -o "Core\.[A-Za-z]*" backend/manager/static/workbench.js | sort | uniq -c
  1 Core.annotationAnchors  3 Core.codepointToUtf*  2 Core.DraftQueue  1 Core.EditorAdapter
  1 Core.floatBarPosition   2 Core.paragraphIndexOf 1 Core.threeWayTextMerge 1 Core.UndoStack
（无 connectEventStream / SseParser / OrderedEventBuffer / canApplyRemote）
$ grep -o "WorkbenchCore\.[A-Za-z]*" client.js | sort | uniq -c
（同上，无 SSE 相关）
```
  SSE 解析器、事件缓冲、重连逻辑**只被三个单测文件调用**，两套 UI 都没有任何实时通道。服务端其实是有 SSE 的（`backend/manager/api_v085.py:139` `yield ": ping\n\n"`，`145 StreamingResponse(media_type="text/event-stream")`）。
- 影响：
  1. 用户视角：工作台没有任何"其他窗口/后台任务已更新"的实时提示，只能刷新页面；而"多窗口并发"正是这套 UI 花了大量代码（`draft_conflict`/`concurrent_modification`/三方合并）在防的问题；
  2. 若将来接上：`connectEventStream` 对任何非 2xx（401 令牌过期、502 代理抖动、503 重启中）直接 `close()` 永久终止，不重试；`reader.read()` 也没有心跳超时，TCP 静默断链时会永远挂住（`run()` 的 while 循环，1060-1066）；
  3. 打包体积：约 500 行死代码随 `client.js` 与静态资源发布。
- 最小修复：要么接上（`WorkbenchPage` 订阅 `/api/projects/{id}/events`，用 `canApplyRemote` 决定是否套用远端版本），要么从 core 里删掉并同步删除对应单测；接线时把非 2xx 改成指数退避重试（401/403 除外），并给 `read()` 加 `Promise.race` 心跳超时。
- 证据：两条 `grep -o` 计数（原文见上）；`workbench-core.test.mjs:360-410` 的用例名就叫"stops on non-200"，把该行为固化成了预期。

### F14 `putDraft` 的纪元兜底最多串行 65 次 PUT，全程阻塞草稿队列

- 位置：`workbench.js:1364-1404`（`putDraft`）、`1376-1391`
- 机制：捕获 `draft_conflict` 且响应未带 `current_draft.draft_id` 时，构造候选纪元 `[remembered, 0..64]`，逐个 `await api(..., 15000)` 重试，直到成功或遇到带 `draft_id` 的冲突。
- 影响：最坏 65 × 15s ≈ 16 分钟，期间 `state.draftQueue` 只跑这一个任务，后续所有草稿保存排队；`saveVersion` 里的 `flushDraftNow()` 也会一起卡住（`1449-1459` 虽然后备降级为"直接保存正式版本"，但那要等 flush 抛错）。用户在界面上只看到"草稿保存中…"不动。
- 最小修复：候选纪元截断到 3–5 个（`remembered` + 相邻两个），把每次超时降到 5s，并在循环里 `await new Promise(r => setTimeout(r, backoff))` 之外加整体截止时间；失败即 `state.draftBlocked = true` 并提示走"保存正式版本"。
- 证据：1376-1401 原文。

## 3. P3（12 条）

### F15 测试以正则验"存在"，IME 断言由不可达行满足（假绿）

- 位置：`test/workbench-ui.test.mjs:67-75`、`101-113`、`155-162`；被验证的 `workbench.js:1046-1047`
- 机制（实测）：
```
$ node --test test/workbench-core.test.mjs test/workbench-ui.test.mjs test/client-workbench.test.mjs
ℹ tests 34  ℹ pass 34  ℹ fail 0
$ grep -n "state\.composing.*return false" backend/manager/static/workbench.js
1046:    if (state.composing || (state.adapter && state.adapter.composing)) return false;
1047:    if (!force && state.composing) return false;
```
  测试里的 `assert.match(js, /state\.composing[^\n]*return false/)` 命中的正是**1047 这条不可达行**，于是"IME 守卫"用例全绿，而 F1 的 `force` 失效完全不被覆盖。同类"只验存在"的还有：
  - `workbench.js should contain the real implementation`（长度 > 40000）
  - `draft and version payloads carry exact…`（`js.includes(field)`，不校验字段是否在正确的请求体里）
  - `mobile layout collapses to drawers and a fixed bottom selection bar`（只断言 CSS 文本含 `position: fixed`，因此 F3 的覆盖问题必然漏过）
  - `no contenteditable and no hidden mirror div`（`assert.match(js, /Core\.floatBarPosition\(/)` 只证明调用存在）
- 影响：这些用例给出的是"文本出现了"的信号，不是"行为正确"的信号；本次 5 条 P1 里没有一条能被它们拦住。
- 最小修复：把 `setEditorValue/applyChapter/toggleDrawer/floatBarPosition` 的判定逻辑抽成可在 `node:test` 里直接调用的纯函数（core 已经是这个模式），或引入 `jsdom` 做 DOM 级断言；至少把 IME 用例改成"组合期 `applyChapter` 不得改变 `state.currentId`"这类行为断言。
- 证据：上述命令输出与 grep 结果。

### F16 两套工作台实现漂移（面板 4 个 tab / Web 5 个，功能不对等）

- 位置：`client.js:7081-7086`（面板 `Segmented` 只有 批注/体检/版本/参考）vs `index.html:185-189`（Web 有 5 个，含"世界状态"）；`client.js:6869-6872`（面板批注页只有计数）vs `workbench.js:1985-2018`（Web 可真正提交批注）
- 机制：只有 `workbench-core.js`（1183 行）是共享生成物；`workbench.js`（3025 行）与 `client.js` 的 WorkbenchPage（1082 行）是两份独立实现，DOM/CSS 也不共享（`workbench.css` 1849 行 vs `client.js:5787-5860` 约 75 行）。
- 影响：同名功能在两套 UI 里能力不同（选区浮条、大纲/设定编辑、导入旧稿、回收站、世界状态面板都只在 Web 版存在），用户与文档会持续对不上；修一个 UI 缺陷要改两处，且本报告的 P1 中有 3 条正是"只在其中一套出现"。
- 最小修复：短期在两套 UI 之间加一条契约测试（同一组 tab/动作必须同时存在），中期把 WorkbenchPage 改成"薄壳 + 共享 DOM 渲染层"。
- 证据：上述行号原文；`wc -l` 输出见 §6。

### F17 断点不一致：767（JS/CSS）vs 760（dock），761–767px 出现 76px 死区

- 位置：`workbench.js:340/494/1222/1237`（`matchMedia("(max-width: 767px)")`）、`workbench.css:1583`（`@media (max-width: 767px)`）、`editorial.css:302`（`@media (max-width: 760px)`，dock 在此显示）
- 机制：761–767px 时工作台已进入抽屉模式并给 `.wb-page` 加了 `padding-bottom: 76px`（`workbench.css:1584-1586`），但底部 dock 不显示（760 才显示）→ 底部 76px 空白。
- 影响：特定窗口宽度下页面底部出现一条无意义空白；`syncPortals` 也已把侧栏挪到 `body`，与桌面态不一致。
- 最小修复：统一到 767（把 `editorial.css:302` 改为 767）或统一到 760。
- 证据：三处 `@media`/`matchMedia` 常量原文。

### F18 `sync_workbench_core` 双写字节不一致路径（潜在静默漂移）

- 位置：`scripts/build-client-ui.py:43-67`，尤其 `50-51` 与 `66`
- 机制：写入 `client.js` 的是 `core_text`（**若源文件无结尾换行会被补一个 `\n`**），写入静态资源的是 `core_bytes`（原样字节）：
```python
if not core_text.endswith('\n'): core_text += '\n'      # 50-51
block = WORKBENCH_BEGIN + core_text + WORKBENCH_END     # 56
(ROOT/'backend/manager/static/workbench-core.js').write_bytes(core_bytes)   # 66
```
- 影响：一旦有人保存 `scripts/shared/workbench-core.js` 时去掉末尾换行，`client.js` 里的块会多一个 `\n`，而 `test/workbench-core.test.mjs:412-418` 仍然全绿（它比的是 static 与 shared 的字节，以及 `client.includes(sharedSource)` —— 多一个换行不影响 `includes`）。漂移不可见。
- 最小修复：两边都用 `core_text.encode('utf-8')` 写，或在校验阶段断言 `client.js` 的嵌入块长度 === `core_bytes` 长度。
- 证据：本次两次构建实测一致（§5.2），说明当前无漂移；风险在于脚本自身的不对称写入。

### F19 `hydrateChapterStates` 只补前 80 章，过滤器对 80 章之后"说谎"

- 位置：`workbench.js:795-820`（`slice(0, 80)`）、`workbench.js:865-879`（`chapterMatchesFilter`：`if (!detail) return true;`）
- 机制：只有前 80 章会被拉取详情并写 `state.chapterStates`；第 81 章起 `chapterDetail()` 返回 `null`，`chapterMatchesFilter` 直接 `return true`，因此"未定稿/已发布/待采纳"三个筛选会把它们**全部算作命中**，计数 `updateChapterCount()`（889-893）也按"命中"累加。
- 影响：长书（>80 章，网文常态）的筛选结果与计数不可信；`updateChapterBadge` 对这些章永远显示"打开时读取"。
- 最小修复：对无 detail 的行返回 `false`（"未知不匹配"），或在筛选激活时按需补拉当前可见区间。
- 证据：795/797/869 原文。

### F20 `loadInsights` 失败被静默吞掉，`#wb-insight-status` 永久停在"正在读取…"

- 位置：`workbench.js:2957`（`if (tab === "insights") loadInsights().catch(() => {});`）、`workbench.js:2968-3016`
- 机制：`loadInsights` 用 `Promise.all` 拉 4 个接口（world-state/tasks/quality/diagnostics），任一失败即 reject；`setRightTab` 的 `.catch(() => {})` 不更新任何 UI。状态行在 2971 被置为"正在读取…"后再无写入。
- 影响：用户看到永久转圈文案，无错误提示、无重试按钮（刷新按钮只重试同一路径，同样静默）。
- 最小修复：`catch((error) => setText(els.insightStatus, "读取失败：" + describeError(error)))`，并把 `Promise.all` 改成 `Promise.allSettled` 分块渲染。
- 证据：2957 与 2971 原文。

### F21 陈旧文案："批注接口将在 Wave 3 启用"（内部迭代用语）与错别字"快速检体"

- 位置：`index.html:200`（`title="批注接口将在 Wave 3 启用"`）、`202`（提示文案）、`207`（`尚未体检。快速检体不调用模型。`）、`291`（气泡里同样写 Wave 3）
- 机制：`probeAnnotationEndpoint`（`workbench.js:1942-1957`）在接口可用时会把 `#wb-annotation-submit` 的 `disabled` 与 `title` 清掉（1949-1950），说明"Wave 3"只是开发期占位文案，上线后仍留在 HTML 初值里，接口不可用时会原样展示给作者。
- 影响：终端用户看到"Wave 3"这种内部排期术语；"检体"是错字（应为"体检"）。
- 最小修复：初始文案改为"批注后端未连接时的本地暂存说明"，错字改正。
- 证据：index.html 上述行原文。

### F22 保存状态 `#wb-save-state` 没有 `aria-live`，状态变化只靠颜色

- 位置：`index.html:167`（`<span class="wb-save-pill" id="wb-save-state">尚未选择</span>`）、`workbench.js:1196-1205`（改文字 + 改 class）
- 机制：只有 `#wb-banner`（`role="status" aria-live="polite"`，index.html:130）和 `#toasts`（385）是 live region；"未保存/已保存/正在保存/草稿冲突"四种状态只写 textContent 与配色（`.is-dirty/.is-saved/.is-busy/.is-error`）。
- 影响：读屏用户无法得知"我刚敲的字存没存"，而自动草稿是这套产品的核心承诺。
- 最小修复：`#wb-save-state` 加 `role="status" aria-live="polite"`；`#wb-banner` 的 `hidden` 切换配合 `aria-atomic="true"`。
- 证据：上述两处原文。

### F23 面板里 `<main>` 嵌套 `<main>`（landmark 重复）

- 位置：`client.js:14371-14373`（shell 的 `<main class="nh-main">` 包住 `body`）与 `client.js:6944/7013`（WorkbenchPage 又渲染 `<main class="wb-pane wb-center">`）
- 机制：`body` 作为 `AppearanceContext.Provider` 的子节点被塞进 `nh-main` 内部，工作台的 `<main>` 因而成为 `<main>` 的后代，违反 HTML 规范（main 不得嵌套），并产生两个未命名的 main landmark。
- 影响：读屏的 landmark 跳转出现两个"主区域"且无法区分。
- 最小修复：工作台把 `e('main', …)` 改成 `e('section', { 'aria-label': '正文编辑' })`。
- 证据：上述行原文。

### F24 `OrderedEventBuffer` 的去重集合无界增长

- 位置：`workbench-core.js:449-499`，`465-469`（`this._ids.add(idKey)` / `this._seqs.add(seq)`），`488-498`（`drain()` 只清 `_events`，不清 `_ids/_seqs`）
- 机制：每个事件的 id 与 seq 永久保留，`drain()` 与 `markSnapshot()` 都不修剪。
- 影响：长时间会话下内存单调增长（单机应用量级不大）。当前该类未被调用（见 F13），所以只是潜在缺陷。
- 最小修复：`drain()` 时或 `markSnapshot()` 后按 `seq` 水位裁剪 `_seqs`，`_ids` 改为只保留最近 N 个（例如 1024 的环形缓冲）。
- 证据：449-499 原文。

### F25 `state.savingDraft` 只写不读（死状态）

- 位置：`workbench.js:84`（声明）、`1333`（置 true）、`1360`（置 false）；`grep -n "savingDraft"` 共 3 处，无读取点
- 机制：两路 `saveDraftNow` 并发时，先完成的一路会把 `savingDraft` 置 false，语义已经不准；但因为没人读，暂时无害。
- 影响：误导后续维护者以为存在"保存中"互斥。
- 最小修复：删除，或真正用于禁用"保存版本"按钮。
- 证据：上述 grep 输出（3 处，全部是赋值）。

### F26 `saveVersion` 在保存进行中被静默 `return`，Ctrl+S 无任何反馈

- 位置：`workbench.js:1442`（`if (!state.currentId || state.savingVersion || state.versionSavePending) return;`）
- 机制：40s 超时的正式保存期间再按 Ctrl+S，直接 return，不 toast、不改按钮文案（`updateEditorMeta` 里虽有"正在保存…"，但那是 `savingVersion` 之后才生效）。
- 影响：用户以为"又存了一次"，实际被吞；若第一次保存最终失败，用户不会补按。
- 最小修复：该分支加 `toast("正在保存，请稍候")`（或按钮 loading 态），与 `openChapter` 的 945-948 处理保持一致。
- 证据：1442 与 945-948 对照。

## 4. 逐项覆盖情况（对照委托的审计要点）

| 委托要点 | 结论 | 对应条目 |
| --- | --- | --- |
| XSS：任何 API 文本进 innerHTML/属性 | **未发现**（两套 UI 零 `innerHTML`，唯一 API→href/src 通道被 `safeHttpUrl/safeQrSrc` 白名单） | §5.1 |
| IME 组合期覆盖 | 发现 2 条：`force` 失效 + `composing` 闩锁 | F1、F2 |
| 撤销栈/草稿队列竞态 | 核心竞态处理正确（`DraftQueue` 串行、`submit` 快照 `editSeq`）；UI 层发现纪元重试阻塞与死状态 | F14、F25 |
| Selection 浮条坐标与移动端底栏 | 发现 2 条 | F3、F11 |
| Ctrl+S 冲突/草稿保留 | 发现 2 条 | F6、F4 |
| 编辑器可访问性（label/tabindex/focus/aria） | 发现 5 条（label 本身合格） | F5、F7、F8、F22、F23 |
| 窄屏抽屉/滚动锁 | 发现 1 条 | F7 |
| SSE 解析与断线重连 | 发现 1 条（实现存在但零接线，且非 2xx 不重连） | F13 |
| 生成块与 shared core 字节一致性 | **一致**（实测） | §5.2 |
| 构建幂等 | **幂等**（实测两次构建字节不变） | §5.2 |
| 测试是否只验存在不验行为 | 9 条正则式断言，其中 1 条假绿 | F15 |

## 5. 未发现问题的部分（负向结论与证据）

### 5.1 XSS：两套 UI 都没有把 API 文本拼进标记

```
$ grep -c "innerHTML" backend/manager/static/workbench.js
0
$ grep -n "dangerouslySetInnerHTML\|innerHTML\|outerHTML\|insertAdjacentHTML\|document.write\|new Function" client.js
（仅命中 7168 行的 `runRetrieval()` 字符串，非该 API）
$ grep -n "setAttribute" backend/manager/static/workbench.js
295,412,543,835,931,1218,1231,1258,1259,1954,2944   ← 全部是 aria-*/title 常量
```
- `workbench.js` 入口注释（1-10 行）声明"Every project-supplied string is written with textContent"，实测成立：所有项目数据走 `node(tag, cls, text)`（117-122）或 `setText`（129-132），`dataset.name = file.name`（2371/2522）是属性**值**而非 HTML 解析。
- `client.js` 全部走 React 元素，无 `dangerouslySetInnerHTML`；唯一的 API→URL 通道在 `10055-10056`，两侧都被门控：
```js
// client.js:13792-13807
function safeHttpUrl(value){ ... return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : ''; }
function safeQrSrc(value){ ... /^data:image\/(?:png|jpe?g|gif|webp|svg\+xml);/i ... return safeHttpUrl(text); }
```
  允许 `data:image/svg+xml` 进入 `<img src>`，但 `<img>` 渲染 SVG 不执行脚本，不构成 XSS。
- 本地 Web UI 的 `#page-workbench` 无内联事件处理器（`test/workbench-ui.test.mjs:165` 亦覆盖）。

### 5.2 字节一致性与构建幂等（实测）

```
$ sha256sum scripts/shared/workbench-core.js backend/manager/static/workbench-core.js
a21c9725…8bf37  scripts/shared/workbench-core.js
a21c9725…8bf37  backend/manager/static/workbench-core.js
$ cmp scripts/shared/workbench-core.js backend/manager/static/workbench-core.js && echo IDENTICAL
IDENTICAL

# client.js 内嵌块 vs shared（解析生成标记后逐字节比较）
begin count: 1  end count: 1
embedded len: 39139  shared len: 39139  equal: True

# 幂等：仓库完整拷贝到 scratch 后连续两次执行构建脚本
$ python3 scripts/build-client-ui.py     # run1
Native stylesheet bytes: 4579609 / Workbench core bytes: 39151
$ diff -q client.js <repo>/client.js && echo "client.js UNCHANGED"
client.js UNCHANGED
$ python3 scripts/build-client-ui.py     # run2
run2 client.js UNCHANGED vs HEAD
```
结论：`scripts/shared → client.js 内嵌块` 与 `scripts/shared → static/` 两条链路当前完全一致；构建对同一输入幂等（无 `.gitattributes` CRLF 干扰，脚本对 `\r` 有显式拒绝，`build-client-ui.py:48-49`）。

### 5.3 共享内核的竞态与偏移处理（读码结论，核心单测为真行为测试）

- `DraftQueue.submit` 在**提交时**快照 `editSeq`，在**完成时**比较，`stale` 语义正确（`workbench-core.js:189-205`）；`_pump` 严格串行（212-231）。
- `utf16ToCodepoint` / `codepointToUtf16` / `sliceCodepoints` 对代理对（emoji）成对处理（38-80），单测覆盖 `甲😀丁`（`workbench-core.test.mjs:111-121`）。
- `threeWayTextMerge` 冲突块按整行扩展、相邻冲突合并（`workbench-core.js:785-830`），标记方向正确：`wbMergeTexts(base, local, remote)` → `threeWayTextMerge(base, remote, local)`（`client.js:5952-5956`），与 core 的 `(base, server, local)` 签名一致，未出现"本地/服务端标反"。
- `UndoStack` 容量裁剪与 redo 失效（`94-150`）单测覆盖（`workbench-core.test.mjs:67-98`）。

## 6. 方法、限制与复现命令

执行过的关键命令（全部只读；唯一写入发生在 scratch 副本）：

```bash
git -C /home/ubuntu/projects/dsh-chapter-whale rev-parse --abbrev-ref HEAD   # feat/v0.8-v0.9.5
git -C … log --oneline -3                                                    # fe2bc32 / 392df8c / f54b933
wc -l client.js backend/manager/static/{workbench.js,workbench.css,workbench-core.js,index.html} \
      scripts/build-client-ui.py scripts/shared/workbench-core.js \
      test/{workbench-ui,workbench-core,client-workbench}.test.mjs index.js
sha256sum scripts/shared/workbench-core.js backend/manager/static/workbench-core.js ; cmp -s …
# scratch 构建探针
tar -cf - client.js assets scripts backend/manager/static | tar -xf - -C $SCRATCH/build-probe
python3 scripts/build-client-ui.py     # ×2，逐次 diff 回仓库
# 测试
node --test test/workbench-core.test.mjs test/workbench-ui.test.mjs test/client-workbench.test.mjs
# ℹ tests 34  ℹ pass 34  ℹ fail 0
# 静态取证
grep -n "innerHTML\|dangerouslySetInnerHTML" …
grep -o "Core\.[A-Za-z]*" backend/manager/static/workbench.js | sort | uniq -c
grep -n "state\.composing.*return false" backend/manager/static/workbench.js
grep -rn "modal-open" backend/manager/static/*.js
grep -n "z-index" backend/manager/static/workbench.css
awk 'NR<=306 && /@media/{last=NR": "$0} END{print last}' backend/manager/static/editorial.css
```

限制（会影响结论强度）：

0. **工作树状态（透明说明）**：本次审计开始时 `git status --short` 为空（工作树干净，HEAD `fe2bc32`）。审计结束（07:47）时出现 5 个**未提交的后端 Python 修改**（`backend/integration/{agent_hub,chapter_editor,chapter_versions,world_state}.py`、`backend/manager/api_v085.py`，mtime 07:42–07:45）。这些**不是本次审计产生**（本报告全程只读，唯一写入在 `~/.hermes/cache/scratch/`），且均不属于本报告审计范围；判断为并发进程所改，未触碰、未回滚。

1. **无浏览器可用**：`browser_exec` 连接 CDP `127.0.0.1:9336` 失败（`Connection refused`），因此 F3/F11 的像素级位置、F5 的焦点环视觉、F7 的滚动链均为 **CSS 计算 + 代码路径推理**，未做真机截图取证；F3 的"覆盖"是结构性结论（同 `bottom:0`、z-index 79 > 40），像素值为估算。
2. **未启动 manager**：所有前端均以静态文件 + 代码路径分析，未做端到端联调；接口契约以 `index.js:WRITE_ROUTES` 与 `workbench.js` 调用点对照为准。
3. 未审计 `app.js`、`liquid-glass.js`、`costs.js`、`providers.js` 等其他页面的前端代码（不在本次范围）。
4. `backend/manager/app.py` 的静态托管只做了旁证（`app.py:2758` `FileResponse(STATIC/"index.html")`、`2761` `app.mount("/static", StaticFiles(...))`、`1261` 静态资源 `Cache-Control: no-cache`），未深入。

## 7. 建议修复顺序

1. **F1 + F2**（同属 IME 状态机）：一起改，`force` 语义 + `composing` 复位 + `applyChapter` 原子化。这是唯一会导致**内容写错章节**的缺陷。
2. **F3**：移动端浮条让出底栏（一行 CSS），顺带修 F11 的视口夹取。
3. **F4 + F6**：草稿落盘与 Ctrl+S 覆盖全输入框——两者都是"用户以为存了其实没存"。
4. **F5 + F7 + F8 + F22**：可访问性四连（焦点环、抽屉、列表语义、保存状态播报）。
5. **F13**：决定 SSE 是接上还是删掉，不要继续以"已测试"的姿态携带死代码。
6. **F15**：把 IME/布局类断言升级为行为断言，否则上述修复没有回归保护。
7. 其余 P2/P3 按 F9（一行 CSS）、F17（一行 CSS）、F21（文案）这类低成本项随版本清理。
