# D 域独立审计报告 — 前端 / 静态资产 / 构建 / 发布

- 审计对象：`/home/ubuntu/.hermes/cache/scratch/audit-v3/head-d`（detached `4f5a5a1`）
- 审计方式：只读代码审查 + `node --test` / `npm test` + `check-release --local` + 本地静态 fixture（临时端口 8871，Playwright/Chromium，所有探针只写入 `tmp-d/`）
- 仓库状态：审计前后 `git status --short` 均只有 `?? node_modules`；未修改、未提交、未联网
- 基线：`npm test` = 174 tests / 158 pass / 0 fail / 16 skipped；`node scripts/check-release.mjs --local` 通过 1188 个文件，`buildId=c355fa1adf506f530484758c49bbf862330a237631db2a32c988124351c1f47b`

## 0. 结论摘要

**不满足“可发布”条件。** 测试全绿并不能覆盖本轮发现的关键路径：静态直写工作台仍存在 **1 条可静默覆盖后台正文的 P1**、**1 条自动草稿永久锁死的 P1**；DSH 面板的章节切换存在 **未做 IME/保存互斥的 P1 级竞态（代码可证，未在宿主实机跑 React）**；发布门禁还存在 **缺少 `client.js` / `index.js` 仍能通过 `prepublishOnly`** 的 P2 缺口。

最严重的 5 条：

1. **D-01R（P1）** 草稿 `base_content` 为 `null` 或空串时，静态工作台回退到“当前正式正文”作为三方合并 base。实测“旧草稿 v1 + 后台 v2 新增段落”在合并后被还原成旧草稿全文，随后 Ctrl+S 以 v2 的 expected 身份成功覆盖，后台新增段落静默丢失。
2. **D-11S（P1）** `recallDraftEpoch()` 把 `localStorage` 的 `null` 当 `0`，覆盖服务端返回的 `draft_epoch`；首次无草稿自动保存只重试 epoch `0/1/2`，服务端 epoch=9 时直接进入 `draftBlocked`，而且正式保存成功后仍不解锁，自动草稿永久停摆。
3. **D-C1（P1，HYPOTHESIS）** `client.js` 章节切换不等待草稿保存、章节数据到达时也不检查 IME 组合；切换章节/作品时若草稿保存失败或正在组合，内存中的最后输入可能直接丢失；版本保存响应也没有“当前章是否已切换”的校验。
4. **D-01R2（P1/P2）** 静态“载入对方草稿/三方合并”只更新了 `state.draft`，没有 adopt 对方草稿的 `baseVersionId/baseSha/baseContent`；下一次 Ctrl+S 仍用旧 v1 expected，真实服务端必然 409；DSH 的 draft 合并分支同样不更新 `baseRef`。
5. **D-RG1（P2）** `check-release.mjs --local` 对缺失的 `client.js` 只打印“跳过生成产物一致性校验”，对缺失 `index.js` / `managed-runtime.mjs` 完全无感；实测两者都返回 0，`prepublishOnly` 可以发出一个无法加载的插件包。

## 1. 已知残余复核

| 项 | 复核结果 | 说明 |
|---|---|---|
| **D-01-M/N** 陈旧草稿 base / 缺基线 blocked | **未完全关闭** | 正常有 `base_content` 时已使用草稿自身 base；但 `base_content` 为 null/空串时回退当前正文且不 blocked，见 D-01R；冲突解决后未 adopt 基线，见 D-01R2。 |
| **D-02-D** 批注提示 dirty | **部分关闭** | 提交前 `flushDraftNow()` + dirty 检查已生效，POST 契约也正确；但切章后按钮仍 enabled、hint 仍是上一章的“已连接”，点击才提示不可用，见 D-02D。 |
| **D-03-P** GET 期间 IME pending | **GET 路径已关闭，仍有两个缺口** | 延迟 GET 期间开始组合会进入 `pendingChapter`，组合结束/失焦/隐藏后才应用新章；实测组合文字会先作为旧章草稿保存。但 blur/visibility 复位组合时没有 `handleEditorInput()`，组合文字不会标 dirty；DSH 面板完全没有 pending 机制，见 D-03P、D-C1。 |
| **D-04-M** 背景 inert / resize | **部分关闭** | 关闭抽屉已 inert + aria-hidden，打开后焦点进入，resize 到桌面会清理；但 `aria-modal` 抽屉外仍只有 `.sidebar/.topbar/.skip-link` 被 inert，`.mobile-dock`、`.wb-page-head`、`.wb-mobile-bar` 仍可 Tab 进入，见 D-04M。 |
| **D-09** split/merge/restore 草稿 | **部分关闭** | split/restore 的保护已加；merge-tail 只检查“当前章”的草稿，尾章（非当前章）的草稿仍会在无提示下被 `delete_chapter` 删除，见 D-09R。 |
| **D-10** SSE 全链路 | **前端已接线，后端仍无生产者** | 静态和 DSH 都订阅 `/room/stream`，`retry:`/503/关闭已修；但仓库内没有任何 `kind` 含 `chapter`/`draft` 的 `append_event` 生产者，前端刷新条件实际只可能被 `resync_required` 触发。 |
| **D-14-K** visibility/pagehide | **visibility 已修，pagehide 有 bfcache 回归** | `visibilitychange` 走正常 `flushDraftNow()` 并 adopt revision；`pagehide` 无 `event.persisted` 判断，bfcache 返回后会把自己 keepalive 写出的草稿误判为“其他窗口更新”，见 D-14K。 |
| **D-15** 包体 | **未变** | `client.js` 5,284,482 B；字体 3,355,008 B 同时以 base64 内嵌又以 `assets/fonts` 分发；`npm pack` 12,689,949 B / unpacked 25,970,249 B / 1250 files。 |
| **D-05 / D-08 / D-16** | **通过** | Ctrl+S 焦点分发、生成 CSS/core 字节一致、760/761–767 断点矩阵均通过静态与浏览器检查（见 §5）。 |

## 2. P1 级发现

### D-01R（P1）草稿缺 `base_content` / base 为空时回退当前正文，三方合并静默丢掉后台新增正文

**位置**

- `backend/manager/static/workbench.js:212-235`（`resolveDraftBaseline`）
- `backend/manager/static/workbench.js:1151-1155`（`applyChapter`）
- `backend/manager/static/workbench.js:2071-2117`（draft 冲突的 `merge` 分支）
- 服务端冲突响应：`backend/integration/chapter_editor.py:352-359`（`current_draft` 不含 `base_content`）

**机制**

`resolveDraftBaseline` 只在 `baseVersionId` 或 `baseSha` 缺失时 `blocked=true`；当服务端返回的 `draft.base_content` 为 `null`（旧版本已被 GC、版本文件不可读、旧数据迁移）或空字符串（新章 v1 为空正文）时，函数返回 `baseContent: ""` 且 `blocked:false`。随后：

```js
state.baseContent = baseline.baseContent || String(data.content || "");
```

空字符串会触发 `||` 回退，把**当前正式正文**当成草稿的合并基线，而 `state.baseVersionId/baseSha` 仍是旧 v1。之后：

- Ctrl+S 先用旧 v1 expected 保存草稿（服务端 `save_draft` 不校验 base 与当前版本），随后正式保存拿到 409 `concurrent_modification`；
- 用户在冲突面板点“三方合并”，`base = state.baseContent` 已是当前 v2，`server = current_content` 也是 v2，`local = 旧草稿`；
- 三方合并把“local 相对 v2 的整体改写”当成作者意图，返回旧草稿全文且 `conflicts=[]`；
- 合并分支把 `baseVersionId/baseSha` 改成 v2，用户再次 Ctrl+S 以 v2 expected 成功提交，后台 v2 的新增段落被静默覆盖。

这与 D-01 原始 P1 的“陈旧草稿静默覆盖正式版本”是同一数据完整性类别，只是入口从“直接保存”变成了“冲突合并”。

**影响**

- 后台任务/另一个窗口已写入的正式正文被作者的一次“合并”静默回退；
- 作者看不到冲突标记，界面还提示“已三方合并，请核对后按 Ctrl+S 保存”；
- 服务端 `draft_conflict` 响应也没有 `base_content`，前端即使想用对方草稿的 base 也无法取得。

**最小修复**

1. `resolveDraftBaseline`：draft 存在时，`baseContent == null` 必须 `blocked:true`；空字符串是合法 base，不能 blocked。`applyChapter` 不要用 `||`，改为显式 null/undefined 判断：
   ```js
   const hasBase = baseline.baseContent !== null && baseline.baseContent !== undefined;
   state.baseContent = hasBase ? String(baseline.baseContent) : String(data.content || "");
   ```
2. `chapter_editor.save_draft` 的 409 `current_draft` 增加 `base_content`（按 `base_version_id/base_content_sha256` 读取版本正文，和 `chapter_state` 的做法一致），或在冲突时让前端 `GET /versions/{base_id}` 后再合并。
3. 合并前比较 `current.base_version_id/base_content_sha256` 与本地 `state.baseVersionId/baseSha`；不同则拒绝自动合并，提示先载入对方版本。

**验证**

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-d
/home/ubuntu/venvs/dsh/bin/python probe_nullbase_dataloss.py
```

实际输出（节选）：

```text
loaded {'text': '旧草稿正文。', 'baseContent': '当前正式版本 v2。\n新增段落。', 'baseVersionId': 'ver_0001_aaaa', 'blocked': False}
conflict 服务端第 2 章的正文已变化（ver_0002_b…）。你的文字没有被覆盖。…
after merge {'text': '旧草稿正文。', 'baseContent': '当前正式版本 v2。\n新增段落。', 'baseVersionId': 'ver_0002_bbbb', 'dirty': True}
version_saves [
  {"content":"旧草稿正文。","expected_version_id":"ver_0001_aaaa",...},
  {"content":"旧草稿正文。","expected_version_id":"ver_0002_bbbb",...}
]
```

第二次 PUT 已经是 v2 身份、旧稿内容；真实服务端会接受并覆盖 v2。

补充探针 `probe_basecontent.py`（`base_content:null`、`baseVersionId:v1`、当前 v2）输出：

```text
{'baseContent': '当前正式版本 v2。', 'baseVersionId': 'ver_0001_aaaa', 'blocked': False,
 'banner': '已恢复未提交草稿。按 Ctrl+S 保存为正式版本。', 'saveDisabled': False}
```

即：缺基线却提示“可保存”，没有 blocked 警告。

---

### D-11S（P1）`recallDraftEpoch()` 把 `null` 当 `0`：首次自动草稿 epoch 永远错，随后 `draftBlocked` 永久锁死

**位置**

- `backend/manager/static/workbench.js:1613-1620`（`recallDraftEpoch`）
- `backend/manager/static/workbench.js:1156-1160`（`applyChapter` 无草稿时的 epoch 回填）
- `backend/manager/static/workbench.js:1699-1730`（`putDraft` 的 epoch 回退候选）
- `backend/manager/static/workbench.js:1774-1780`（`handleDraftError` 直接锁死）
- `backend/manager/static/workbench.js:1854-1909`（`applySaveResponse` 成功后不解锁）

**机制**

```js
function recallDraftEpoch() {
  try {
    const value = Number(localStorage.getItem(epochStorageKey()));
    return Number.isFinite(value) && value >= 0 ? value : null;
  } catch { return null; }
}
```

`localStorage.getItem` 在没有键时返回 `null`，`Number(null) === 0`，所以函数返回 **0 而不是 null**。`applyChapter` 在服务端返回 `draft.exists=false, draft_epoch=9` 时：

```js
state.draft = draftIdentityFrom(draftInfo);       // epoch=9
const remembered = recallDraftEpoch();           // 实际返回 0
if (remembered !== null) state.draft.epoch = remembered;  // 覆盖成 0
```

首次自动保存发送 `expected_draft_epoch: 0`；服务端 `chapter_meta.draft_epoch=9`，且无草稿行时必须精确匹配，于是 409。`putDraft` 的候选只覆盖 `[tried-2, tried+2]` 并截断 5 个，tried=0 时实际只试 `1,2`，永远到不了 9。错误最终进入 `handleDraftError`，因为 `current.draft_id` 为空，直接：

```js
state.draftBlocked = true;
banner("草稿纪元无法与服务端同步（响应未返回 draft_epoch），自动草稿已暂停；请先保存正式版本。", "error");
```

错误消息也不准确：服务端响应其实带了 `current_draft.draft_epoch=9`，只是前端没读。更严重的是，用户按提示 Ctrl+S 保存正式版本成功后，`applySaveResponse` 只更新 base 和 dirty，**从不把 `state.draftBlocked` 置回 false**；`handleEditorInput` 又因为 blocked 不再 schedule，自动草稿从此永久停摆，直到切章/刷新。

**影响**

- 任何“曾经创建/清理过 3 次以上草稿”的章节，在新浏览器/清空 localStorage 后首次编辑都无法自动保存；
- 提示让用户“先保存正式版本”，但保存后自动草稿仍不恢复，横幅也一直保留；
- 用户如果只依赖 1.5 秒自动草稿，会以为已经保存，实际没有；关闭页面即丢失最后输入。

**最小修复**

1. `const raw = localStorage.getItem(key); if (raw === null) return null;` 然后再 `Number(raw)`。
2. `handleDraftError`/`putDraft` 在 `current.draft_id == null` 且 `current.draft_epoch` 有效时，直接把 `state.draft.epoch` 设为该值并重试/重排，而不是只走 ±2 窗口。
3. `applySaveResponse` 成功后显式 `state.draftBlocked = false`，并清掉“草稿纪元无法同步”的 banner；至少当 `response.draft_cleared || response.unchanged` 时解锁。
4. `rememberDraftEpoch(state.draft.epoch)` 在 `applyChapter` 无草稿分支也应执行，避免下一次再回退到 0。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_epoch_accept.py
/home/ubuntu/venvs/dsh/bin/python probe_blocked_save.py
```

`probe_epoch_accept.py`（服务端只接受 GET 返回的 `draft_epoch=7`，其他返回 409）：

```text
put_epochs [0, 1, 2]
banner 草稿纪元无法与服务端同步（响应未返回 draft_epoch），自动草稿已暂停；请先保存正式版本。
draft_state 草稿 —
save_detail 草稿冲突待处理
```

服务端明明会接受 9，前端从未尝试 9。

`probe_blocked_save.py`（先 409 锁死，再 Ctrl+S 成功保存正式版本）：

```text
after block {'blocked': True, 'dirty': True, ...} puts [0, 1, 2]
after save {'blocked': True, 'dirty': False, 'banner': '草稿纪元无法与服务端同步…', 'base': 'ver_0003_cccc', ...}
after retype {'blocked': True, 'dirty': True, 'saveDetail': '草稿冲突待处理'} puts [0, 1, 2]
```

正式保存已经成功，`blocked` 仍为 True，后续输入不再发草稿。

---

### D-C1（P1，HYPOTHESIS）`client.js` 工作台的章节/作品切换与保存没有互斥，IME/失败路径可丢最后输入

> 说明：DSH 面板需要宿主 module loader 与 React 运行时，本次没有在真实 DSH 宿主实机跑组件；以下为代码路径可证，按 HYPOTHESIS 记录。

**位置**

- `client.js:6245-6314`（`applyServerData` 与章节切换 useEffect）
- `client.js:6404-6407`（`persistDraftOnce` 非当前章失败仅 toast）
- `client.js:6553-6580`（`changeProject` / `selectChapter` 先排队、立刻切换）
- `client.js:6582-6644`（`saveVersion` 响应无条件写全局 `baseRef/identityRef`）

**机制**

1. **IME 覆盖**：章节切换的 `useEffect` 只判断 `key !== loadedKeyRef.current`，没有 `composingRef.current`/pending 守卫；如果新章 GET 在输入法组合期间返回，`applyServerData` 会直接把 textarea 的 value 重置成新章正文，组合中的文字被覆盖。静态 `workbench.js` 已用 `pendingChapter` 修复，`client.js` 没有同步。
2. **草稿保存失败即丢内存文本**：`selectChapter`/`changeProject` 只 `queueDraftSave(capture)` 后立刻 `setSelectedChapter/setProjectId`；`persistDraftOnce` 在 `sameChapter()` 为 false 时只 `toast.push("第 X 章草稿保存失败…")`，不会回滚选择，也不会保留可恢复的 capture。网络失败/409 时，旧章最后输入只存在于已出栈的闭包里。
3. **版本保存响应写到新章**：`saveVersion` 捕获了 `state/owner`，但响应到达后无条件执行 `baseRef.current = {...}`、`setDirtyFlag(false)`、`identityRef` 相关更新；如果用户在请求期间切到另一章，新章的 base/dirty 会被旧章响应覆盖，之后自动保存可能用错 expected，或把新章 dirty 清掉。

**影响**

- 切章时正在输入法组合的文字被覆盖（D-03 的 DSH 对应缺陷）；
- 切章/切书时草稿保存失败，最后 ≤1.5s 输入从界面消失，只剩 toast；
- Ctrl+S 后立即切章，旧章保存响应可能污染新章 baseline，后续保存 409 或漏存。

**最小修复**

- `client.js` 引入与静态一致的 `pendingChapterRef`：章节数据到达且 `composingRef.current` 为真时缓存，`compositionend/blur/visibilitychange` 后再 apply；或至少在 `applyServerData` 的 reset 分支检查 composing 并延后。
- `selectChapter/changeProject` 改为 `await flushDraft()`，失败（无冲突）时回滚选择；有冲突时保持当前章并展示冲突面板。
- `saveVersion` 响应处理前校验 `chapterRef.current.id === state.id && projectRef.current.id === owner.id`；不匹配则只刷新列表，不写 `baseRef/identityRef/dirty`。
- 为 DSH 组件补一个可运行的 React 行为测试（现有 `client-workbench.test.mjs` 只测纯函数）。

**验证**

本次无法启动真实 DSH React 宿主；可用以下静态证据定位：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-d
sed -n '6304,6314p' client.js
sed -n '6404,6407p' client.js
sed -n '6569,6580p' client.js
sed -n '6612,6644p' client.js
```

输出可见：章节 reset 分支没有 composing 判断；非当前章失败只 toast；切换立即 setState；保存响应没有 current-chapter 校验。

## 3. P2 级发现

### D-01R2（P2）草稿冲突“载入对方草稿/合并”后没有 adopt 对方草稿的版本基线

**位置**

- `backend/manager/static/workbench.js:2032-2052`（`reload` 的 draft 分支）
- `backend/manager/static/workbench.js:2088-2117`（`merge` 的 draft 分支）
- `client.js:7030-7078`（DSH `reloadConflict`）
- `client.js:7082-7105`（DSH `mergeConflict` 的 draft 分支）

**机制**

静态 `reload` 的 draft 分支只设置 `state.draft`，没有设置 `state.baseVersionId/baseSha/baseContent`；`merge` 的 draft 分支同样只设置 `state.draft`，**没有**更新 `state.base*`。因此：

- 对方草稿基于 v2、当前文件也是 v2，本地旧 base 是 v1；
- 用户点“载入对方版本”后正文变成 v2 草稿，但 `state.baseVersionId` 仍是 v1；
- 下一次 Ctrl+S 发送 `expected_version_id: v1`，真实服务端 v2 会返回 409；用户被锁在冲突循环里；
- 若用户点“三方合并”，`state.baseContent` 仍是 v1 正文，合并用的 base 错误。

DSH 侧：`reloadConflict` 更新了 `baseRef.version_id/sha256`，但把 `baseRef.content` 设为 `current.content`（对方草稿正文），而不是对方草稿的 base 版本正文；`mergeConflict` 的 draft 分支则完全不更新 `baseRef`。因此 DSH 也会在后续保存/合并时使用错误基线。

**影响**

- “载入对方草稿”后无法直接提交，必须先再次处理并发冲突；
- draft 合并使用了错误 base，可能产生错误合并结果；
- 与 D-01R 叠加时会把“错误 base 合并”升级为静默覆盖。

**最小修复**

- 静态 `resolveConflict` 的 draft 分支同时设置 `state.baseVersionId = current.base_version_id || state.baseVersionId`、`state.baseSha = current.base_content_sha256 || state.baseSha`，并取得 `current.base_content`（见 D-01R 的服务端补充）写入 `state.baseContent`；取不到就 `blocked=true`，禁止合并。
- DSH `mergeConflict` 的 draft 分支更新 `baseRef.current` 为 `current.base_version_id/base_content_sha256/base_content`；`reloadConflict` 的 `content` 改为 `current.base_content`（没有则 blocked）。
- 若服务端不返回 `base_content`，前端在合并前 `GET /api/projects/:id/chapters/:ch` 取 `draft.base_content`，失败则拒绝自动合并。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_draft_reload_base.py
```

实际输出（节选）：

```text
initial {'baseVersionId': 'ver_0001_aaaa', ...}
after reload {'baseVersionId': 'ver_0001_aaaa', 'baseSha': 'aaaa…',
              'draft': {'id': 'drf_server', 'baseVersionId': 'ver_0002_bbbb', ...},
              'text': '服务端新草稿。'}
saves [["version", {"content":"服务端新草稿。","expected_version_id":"ver_0001_aaaa",
                    "submitted_draft_id":"drf_server", ...}]]
```

载入的是基于 v2 的草稿，Ctrl+S 却仍然发送 v1 expected；真实服务端会 409。

---

### D-02D（P2）切章后批注按钮/hint 仍是上一章状态，点击才提示“后端暂不可用”

**位置**

- `backend/manager/static/workbench.js:1176-1178`（`applyChapter` 重置 `annotationsReady/annotationProbed/remoteAnnotations`）
- `backend/manager/static/workbench.js:2308-2325`（`probeAnnotationEndpoint` 只更新 hint/按钮）
- `backend/manager/static/workbench.js:2401-2405`（`submitAnnotation` 用内存 `annotationsReady` 拦截）
- `backend/manager/static/index.html:200-202`（初始 disabled/hint）

**机制**

`applyChapter` 重置了 `state.annotationsReady=false`、`annotationProbed=false`、`remoteAnnotations=[]`，但没有：

- 把 `#wb-annotation-submit` 重新 disabled；
- 把 `#wb-annotation-hint` 改回“正在检测/暂不可用”；
- 主动调用 `probeAnnotationEndpoint()`（默认右栏就是 annotations，`setRightTab` 不会再次触发）。

因此切章后 UI 保留上一章的“批注接口已连接 · 本章 N 条批注”和 enabled 按钮；点击提交时 `submitAnnotation` 才检查 `state.annotationsReady`，toast“批注后端暂不可用，当前只能本地暂存”。如果用户焦点一直在批注输入框（未触发 focus 事件），新章可能永远不会 probe；只能切换右栏或刷新。

**影响**

- 用户以为新章批注可用，实际提交被拒；
- 读屏/键盘用户看到 enabled 按钮但功能不可用（状态不一致）；
- 切作品、切到无章节作品同样会留下旧项目的 hint。

**最小修复**

- `applyChapter`/`resetChapterState` 中统一重置：`els.annotationSubmit.disabled = true`、`setAttribute("title","正在检测批注接口")`、hint 改为“正在检测批注接口…”。
- 在 `applyChapter` 末尾，如果 `state.rightTab === "annotations"`，调用 `probeAnnotationEndpoint()`。
- probe 失败后允许重试（当前 `annotationProbed=true` 会永久阻止同一章重试）。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_annotation.py
```

实际输出：

```text
after probe hint: 批注接口已连接 · 本章 0 条批注。
after probe disabled: None
after switch hint: 批注接口已连接 · 本章 0 条批注。
after switch disabled: None
toasts ["批注后端暂不可用，当前只能本地暂存×"]
```

切到第一章后 hint/disabled 完全没变，点击提交才失败。

---

### D-03P（P2）blur/visibility 复位 IME 时不调用 `handleEditorInput()`，最后一段组合文字不标 dirty、不落草稿

**位置**

- `backend/manager/static/workbench.js:414-436`（composition/blur/visibility 处理）
- `backend/manager/static/workbench.js:1241-1253`（`handleEditorInput`）
- `backend/manager/static/workbench.js:1751-1767`（`flushDraftKeepalive` 只看 `state.dirty`）
- `backend/manager/static/workbench.js:568-585`（beforeunload/pagehide）

**机制**

`compositionend` 会调用 `handleEditorInput()`；但 `blur` 和 `visibilitychange(hidden)` 只做：

```js
state.composing = false;
if (state.adapter) state.adapter.endComposition();
commitPendingChapter(...)
```

没有 `handleEditorInput()`。如果浏览器/输入法漏掉 `compositionend`（这正是 D-03/D-06 兜底要处理的场景），textarea 里已有组合文字，但 `state.dirty` 仍是 false、`persistedSignature` 仍是旧内容；1.5 秒定时器不会启动，`pagehide` 也因 `!state.dirty` 不发 keepalive。用户关闭页面时，这段组合文字不会进入草稿，也不会触发 beforeunload 警告。

标题输入框也没有 composition 跟踪：`#wb-title` 的 input 只检查 `state.composing`（只由正文 textarea 设置），标题组合期间可以触发自动草稿，Ctrl+S 也可能把组合中的半截标题写成正式版本。

**影响**

- 输入法在 blur/切 Tab/手机切后台时中断，最后一段文字只留在 DOM；关闭页面即丢失；
- 标题/大纲（`#wb-outline-text`）组合期间 Ctrl+S 可能保存半截文本；
- 与 `beforeunload` 的 `state.dirty` 判断叠加，用户不会收到离开警告。

**最小修复**

- 在 blur 和 visibilitychange 的 `state.composing=false; adapter.endComposition()` 后调用 `handleEditorInput()`，再 `commitPendingChapter()`。
- 标题输入增加 `compositionstart/compositionend`（或 input 时检查 `event.isComposing`）；outline/lore 的 Ctrl+S 路径也应检查组合状态。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_ime_blur.py
```

实际输出：

```text
after blur {'composing': False, 'dirty': False,
            'value': '第二章正文。拼',
            'persisted': '第二章\x00第二章正文。'}
puts []
after pagehide puts 0
```

textarea 已有“拼”，但 dirty=false、没有任何草稿 PUT；pagehide 也跳过。

对照 `probe_ime_get_async.py`（GET 期间组合）输出：

```text
t+1.4 title 第二章 | banner 输入法仍在组合文字，已推迟载入第 1 章。 | value 第二章正文。拼
after commit title 第一章
draft_puts [{"title":"第二章","content":"第二章正文。拼",...}]
```

说明 `pendingChapter` 主路径是好的；缺口只在 blur/visibility 和 DSH。

---

### D-04M（P2）移动抽屉 `aria-modal=true`，但背景仍有可聚焦区域，Tab 会逃出抽屉

**位置**

- `backend/manager/static/workbench.js:1499-1508`（`setBackgroundInert`）
- `backend/manager/static/workbench.js:1510-1521`（`syncDrawerMode`）
- `backend/manager/static/workbench.js:1561-1564`（`toggleDrawer`）
- `backend/manager/static/index.html:146-150, 386-392`（mobile bar / mobile dock）

**机制**

打开移动抽屉时只对 `.sidebar`、`.topbar`、`.skip-link` 设 `inert`，并把 `.wb-center` 设 inert；但以下仍在无障碍树和 Tab 顺序中：

- `#page-workbench .wb-page-head`（作品选择、视图切换、更多菜单）；
- `.wb-mobile-bar`（代码显式 `els.mobileBar.inert = false`）；
- `.mobile-dock`（底部导航，5 个链接）；
- 页面 footer 等。

抽屉本身被设置 `role="dialog" aria-modal="true"`，语义上要求其余内容不可交互；实际 Tab 从抽屉最后一个按钮会走到 `BODY`，再进入 `cw-nav-pill`（mobile dock）。读屏也会继续读到页面头部和底部导航。关闭状态、焦点进入抽屉、resize 清理均正常，问题只在“打开时的背景”。

**影响**

- WCAG 2.4.3 / 4.1.2 / aria-modal 语义不一致；
- 键盘用户可在“模态”抽屉打开时切到其他页面链接，抽屉不会关闭；
- 读屏用户听到抽屉外内容，焦点顺序混乱。

**最小修复**

- 打开抽屉时对 `.workspace`（含 page head、center、mobile bar）和 `.mobile-dock` 设 inert；不要只对 `.sidebar/.topbar` 设。
- 保留抽屉自身和 `#wb-backdrop` 可交互；关闭按钮在抽屉内，不需要 mobile bar 作为出口。
- 或在 `setBackgroundInert` 中统一选择：`.workspace, .sidebar, .skip-link, .mobile-dock`；关闭时全部恢复。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_aria.py
```

实际输出（390×844，右抽屉打开）：

```text
OPEN {
  "center": {"inert": true},
  "dock": {"inert": false},
  "pageHead": {"inert": false},
  "mobileBar": {"inert": false},
  "sidebar": {"inert": true},
  "topbar": {"inert": true}
}
TAB_SEQUENCE ["wb-right-close","wb-annotation-input","wb-annotation-add","wb-annotation-submit",
              "modal-open","cw-lens-circle cw-project-lens","cw-nav-pill is-active","cw-nav-pill"]
RESIZED {"leftInert": false, "rightInert": false, "centerInert": false,
         "sidebarInert": false, "topbarInert": false, "modalOpen": false, "backdropHidden": true}
```

关闭抽屉的 inert、焦点进入、resize 清理都通过；背景 Tab 逃逸未通过。

---

### D-09R（P2）merge-tail 只检查当前章草稿；尾章（非当前章）的未提交草稿无提示被删除

**位置**

- `backend/manager/static/workbench.js:3161-3164`（`openTool` 只检查 `state.draft`）
- `backend/manager/static/workbench.js:3189-3193`（merge 标签不检查尾章）
- `backend/manager/static/workbench.js:3284-3295`（`submitMergeTail`）
- `client.js:6955-6983`（DSH `mergeTail` 只检查 `identityRef.current.draft_id`）
- `backend/integration/chapter_editor.py:806,857`（`delete_chapter` 把 `wb.get_draft` 写入 manifest 后 `wb.delete_draft`）

**机制**

`openTool("merge")` 的警告条件：

```js
if ((state.dirty || state.draft.exists) && ["delete","split","merge"].includes(kind))
```

这里的 `state.draft` 是**当前打开章节**的草稿。`merge-tail` 实际合并最后两章（`max` 与 `max-1`），与当前章无关。若用户在第一章，尾章（第二章）有未提交草稿：

- 当前章干净 → 不弹 confirm；
- 点“合并最后两章” → 后端 `_merge_tail_locked` 以两章正式正文合并，`delete_chapter(last)` 归档并 `wb.delete_draft(project, last)`；
- 前端随后用当前章的 `oldDraftId`（null 或其他章的 id）去删 `result.chapter_id` 的草稿，既删不到尾章草稿，也不会提示；
- 尾章草稿只存在于回收站 manifest 的 `draft` 字段；界面没有“仅恢复草稿”的入口。

DSH 的 `mergeTail` 同样只检查 `identityRef.current.draft_id`（当前章），不查询尾章。

**影响**

- 用户以为合并的是两章正式稿，尾章的未提交草稿被静默丢弃；
- 虽然回收站可整章恢复并带回草稿，但 UI 未提示，普通用户不会知道；
- 与 D-09 原始 P1 的“无提示删除草稿”同类，只是路径从 split/restore 转到了 merge-tail。

**最小修复**

- 前端在打开 merge 工具前并发 `GET` 最后两章状态，检查两章 `draft.exists`；有草稿就确认或直接拒绝，文案明确说“第 N 章有未提交草稿，合并会归档并删除它”。
- 或后端 `merge_tail` 增加 `draft_exists` 409（可带 `draft_chapter_ids`），要求显式 `discard_drafts=true` 才继续。
- `submitMergeTail` 不要用“当前章”的 draft id 去删结果章草稿；应使用后端返回的 `dropped_chapter_id`/draft 信息清理。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_merge_tail_draft.py
```

实际输出（当前第一章，第二章有 `draft.exists=true`）：

```text
current 第一章 draft 草稿 —
dialog open True
merge label 把第 2 章并入第 1 章；两章都必须未发布。
confirms []
requests []
```

没有任何 confirm，也没有查询/删除尾章草稿的请求；后端合并会按 `chapter_editor.py:857` 删除它。

---

### D-14K（P2）`pagehide` 没有判断 `event.persisted`：bfcache 返回后 keepalive 草稿被误判为“其他窗口更新”

**位置**

- `backend/manager/static/workbench.js:582-585`（`pagehide` 无 event 参数）
- `backend/manager/static/workbench.js:1751-1767`（`flushDraftKeepalive`）
- `client.js:6741-6743`（DSH `onPageHide` 同样无 persisted 判断）
- `client.js:6752`（卸载 cleanup 也调用 keepalive）

**机制**

`pagehide` 在 bfcache 导航时也会触发，且 `event.persisted === true` 表示页面会被缓存、之后可能恢复。当前处理：

```js
on(window, "pagehide", () => {
  if (!state.dirty || state.draftBlocked) return;
  flushDraftKeepalive();
});
```

不判断 `persisted`。`visibilitychange(hidden)` 的正常 `flushDraftNow()` 是异步的，`pagehide` 往往先看到 `state.dirty` 仍为 true 并发 keepalive；keepalive 在服务端创建/推进草稿 revision。页面从 bfcache 恢复后，内存里的 `state.draft` 仍是旧 identity、`dirty=true`，下一次自动保存/输入触发 409，`handleDraftError` 显示“草稿在其他窗口更新了”，把用户自己的 keepalive 草稿当成别人的。

**影响**

- bfcache 返回后出现假冲突，自动草稿暂停；
- 用户需要手动“载入对方草稿”，而内容其实就是自己离开前的文本；
- 移动端返回手势/浏览器前进后退场景较常见。

**最小修复**

- `pagehide` 处理接收 event：`if (event.persisted) return;`，bfcache 场景依赖 `visibilitychange` 的正常 flush/adopt；真正卸载才 keepalive。
- 或在 keepalive 成功后无法 adopt 的情况下，恢复时先 `GET` 当前章并比对 draft id/content，若与本地相同则直接 adopt identity、清 dirty，不弹冲突。

**验证**

```bash
/home/ubuntu/venvs/dsh/bin/python probe_bfcache.py
```

实际输出（模拟 `pagehide persisted=true`，服务端在 keepalive 时创建草稿）：

```text
puts after pagehide [{"content":"第二章正文。bfcache","expected_draft_id":null,"expected_draft_epoch":0,...}]
after restore ... 
conflict title 草稿在其他窗口更新了
conflict msg draft_conflict · 服务端已存在另一份草稿（刚刚），本地草稿没有覆盖它。…
blocked True
```

同一份文本被 keepalive 写成“对方草稿”，恢复后立即假冲突。

---

### D-RG1（P2）`check-release --local` 对缺失根入口不报错，`prepublishOnly` 可发布无法加载的包

**位置**

- `scripts/check-release.mjs:313-325`（`if (!existsSync(clientPath)) notes.push(...)`）
- `scripts/check-release.mjs:146-149`（required 列表只覆盖 backend/runtime）
- `package.json:40-43`（`exports["./client"] = "./client.js"`）
- `package.json:101`（`prepublishOnly: node scripts/check-release.mjs --local`）

**机制**

`client.js` 不存在时：

```js
if (!existsSync(clientPath)) {
  notes.push('未包含 client.js，跳过生成产物一致性校验。');
}
```

只记 note，不 push error。`index.js`、`managed-runtime.mjs`、`cordis.patch.yml` 等根入口既不在 `runtime-manifest.files`，也不在 required 列表，缺失时脚本完全不检查。因此一个缺少 `client.js` 或 `index.js` 的暂存目录仍会输出“校验通过”，`prepublishOnly` 返回 0，npm 可以发布一个 DSH 无法加载的包。

**影响**

- 发布门禁存在结构性盲区：最大的前端产物 `client.js` 缺失时反而被“跳过”；
- 打包脚本/CI 如果漏拷根文件，发布不会被拦截；
- 与 D-15 叠加时，包体检查也没有任何阈值。

**最小修复**

- 在 `check-release` 开头把根入口加入 required：`package.json`、`index.js`、`client.js`、`cordis.patch.yml`、`managed-runtime.mjs`、`runtime-manifest.json`、`runtime-download.json`；缺失即 error。
- 当 `package.json.exports["./client"]` 或 `dsh.client` 存在时，`client.js` 缺失必须是 error，不是 note。
- 增加负向测试：临时目录删除 `client.js` / `index.js` / `managed-runtime.mjs`，断言 `check-release` 退出非 0。

**验证**

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3
rm -rf tmp-d/root-missing-client && mkdir tmp-d/root-missing-client
cp -al head-d/. tmp-d/root-missing-client/ && rm tmp-d/root-missing-client/client.js
cd head-d && node scripts/check-release.mjs --local --root ../tmp-d/root-missing-client; echo EXIT=$?
```

实际输出：

```text
发行清单校验通过：1188 个文件与清单一致，buildId=c355fa1a...
未包含 client.js，跳过生成产物一致性校验。
EXIT=0
```

同样删除 `index.js` + `managed-runtime.mjs`：

```text
发行清单校验通过：1188 个文件与清单一致，buildId=c355fa1a...
EXIT=0
```

---

### D-RG2（P2/P3）同一 `0.7.5` 版本对应不同包体/buildId，`RELEASE_STATUS.md` 仍是旧提交的发布记录

**位置**

- `package.json:3`（`"version": "0.7.5"`）
- `runtime-manifest.json`（`buildId=c355fa1a...`，3441 files）
- `RELEASE_STATUS.md:12-16`（1168 files / 3421 items / buildId `9f1cc349...`）
- `RELEASE_STATUS.md:20`（published tarball `12,462,042` bytes）
- `npm pack --dry-run --json`（当前 `12,689,949` bytes / 1250 files / unpacked 25,970,249）

**机制**

当前 HEAD 已经包含 v0.8–v0.9.5 的后端/前端修改（新增 20 个 backend 文件、client.js 由 5,271,255 增至 5,284,482），但 `package.json` 仍是 `0.7.5`，`CHANGELOG.md` 顶部仍是 0.7.5，`RELEASE_STATUS.md` 仍声称 `0.7.5` 已发布且列出旧 buildId/旧文件数/旧 tarball 字节。结果是：

- 同一个 `0.7.5` 版本号对应两个不同的 buildId 和两份不同字节的 tarball；
- 当前树若直接 `npm publish`，会与已发布的 0.7.5 冲突（README 声称 0.7.5 已上 npm）；
- `check-release --local` 只校验当前树内部一致，不校验“版本号是否已存在/发布文档是否仍对应旧产物”；
- `--local` 的 1188 与完整包 3441 也不是 `RELEASE_STATUS` 的 1168/3421。

**影响**

- 发布可复现性和用户可见的 buildId 对不上；
- 排障时无法判断用户装的是哪一份 0.7.5；
- 若把当前树强行发成 0.7.5，市场/更新器可能拒绝或覆盖失败；若升版又缺 CHANGELOG/RELEASE_STATUS 更新。

**最小修复**

- 发布前把版本升到新的 0.8.x/0.9.x（或明确的预发布号），同步 `runtime-manifest.packageVersion`、`runtime-download` 的版本语义、CHANGELOG、RELEASE_STATUS；
- 在 `check-release` 增加可选 `--expect-version`/发布文档一致性检查（至少 README/RELEASE_STATUS 的 buildId 和文件数不能与当前清单矛盾）；
- CI 发布作业在 `npm view <name>@<version>` 已存在时直接失败（本轮不联网，未执行）。

**验证**

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-d
node -e "const m=require('./runtime-manifest.json'); const p=require('./package.json'); console.log(p.version,m.packageVersion,m.buildId,Object.keys(m.files).length)"
npm pack --dry-run --json > /home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-d/pack.json
node -e "const p=require('/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-d/pack.json')['dsh-chapter-whale']; console.log(p.version,p.size,p.unpackedSize,p.entryCount)"
```

实际输出：

```text
0.7.5 0.7.5 c355fa1adf506f530484758c49bbf862330a237631db2a32c988124351c1f47b 3441
0.7.5 12689949 25970249 1250
```

而 `RELEASE_STATUS.md` 记录的是 `1168 / 3421 / 9f1cc349... / 12,462,042`。

## 4. P3 与次要观察

### D-15（P3，已知残余未修）包体 5.28 MB + 字体双份分发

- `client.js` 5,284,482 B；其中 `@font-face` 的 base64 字体约 4.47 MB（字体源文件合计 3,355,008 B）。
- `package.json files` 同时包含 `client.js` 和 `assets/`，`assets/fonts` 在 pack 中再分发 3.35 MB；`npm pack` 12,689,949 B / unpacked 25,970,249 B / 1250 files。
- `scripts/build-client-ui.py:78-88` 把三份 woff2 直接 base64 内嵌；`assets/fonts/*.woff2` 仍在包内。
- 最小方向：字体子集化/外链、从 `files` 排除 `assets/fonts`（若 DSH 端不需要），或只保留一份分发；在 `check-release` 增加包体上限（例如 8 MB）作为门禁。
- 这是已知残余，本轮未修，不计入新增回归。

### D-10（P3，已知残余）SSE 前端已接线，但后端仍无 chapter/draft 生产者

- 静态 `workbench.js:933-975`、DSH `client.js:6680-6726` 都订阅 `/api/projects/:id/room/stream`，`retry: 1500`、503 重连、`resync_required` 处理均存在。
- 全仓 `append_event` 只来自 agent room/chief 消息；`chapter_editor.save_draft/save_version` 只写 FTS/版本，不广播 `kind` 含 `chapter`/`draft` 的事件。因此前端 `scheduleRoomRefresh`/`onEvent` 的章节刷新条件在正常编辑路径不会触发，只有 `resync_required`（慢客户端溢出）可能触发。
- 影响：跨窗口/后台任务写完正式版本或草稿，工作台不会实时刷新列表/状态；用户需手动刷新或切章。
- 这不是前端新增缺陷，但使本轮“SSE 事件过滤/关闭”只能验证到传输层，无法验证真实业务事件。

### D-ARIA1（P3）“更多”菜单使用 `role="menu"` 但没有方向键/焦点进入

- `index.html:119-126` 的 `#wb-more-menu` 是 `role="menu"`，子项 `role="menuitem"`，但 `toggleMore`（`workbench.js:1440-1444`）只切 hidden/aria-expanded，没有 ArrowUp/Down/Home/End，也没有打开时把焦点移到第一个 menuitem。Tab 可以走，但不符合 menu 键盘模式。最小修复：打开时 focus 第一项，绑定方向键循环，Escape 关闭并回焦 toggle。

### D-ARIA2（P3）DSH 工作台 `Segmented` 没有 tab 语义

- `client.js:3494-3512` 的 `Segmented` 只渲染带 `data-active` 的 button，没有 `role="tablist"/tab`、`aria-selected`、`aria-controls`；`client.js:7377-7386` 的批注/体检/版本/参考切换依赖它。读屏只能听到普通按钮，不知道当前选中项。最小修复：加 tablist/tab/aria-selected/roving tabindex，或改成 `aria-pressed` 的 toggle group。

### D-IME2（P3）标题/大纲/设定输入框没有 composition 保护

- `workbench.js:444-448` 的 `#wb-title` input 只检查 `state.composing`（正文 textarea 的状态）；标题输入法组合会被当成普通输入，1.5 秒自动草稿可能保存半截标题。
- `Ctrl+S` 的 `saveOutlineFile/saveLoreFile`（`workbench.js:595-609`）也不检查组合状态；在 `#wb-outline-text` / `#wb-lore-text` 组合期间按 Ctrl+S 可能保存半截文本。
- 最小修复：给标题/大纲/设定增加 compositionstart/end 标记，或在 input/save 前检查 `event.isComposing`。

### D-ANN2（P3）批注接口探测失败后同一章不再重试

- `probeAnnotationEndpoint` 在请求前设 `state.annotationProbed = true`（`workbench.js:2309-2310`），失败后 `annotationProbed` 仍为 true；同一章再次 focus 输入框会直接 return（2309），只能切章/刷新。后端短暂不可用恢复后，按钮仍是 disabled。最小修复：失败时把 `annotationProbed=false`，或增加“重试”按钮。

### D-ANN3（P3）远端批注 `range.start=null` 被当成 0

- `workbench.js:2333-2339`：`const start = Number(range.start); Number.isFinite(start) ? start : ...`；`Number(null) === 0`，所以 `list_annotations` 在 snapshot 缺失时返回的 `range:{start:null,end:null}` 会被定位到正文开头，而不是显示“无法定位”。最小修复：把 null/undefined 显式排除后再 `Number`。

### D-OPEN1（P3）切章时草稿冲突只显示 banner，不弹冲突面板

- `openChapter` 的 flush 失败 catch（`workbench.js:1105-1115`）和 `loadProject` 的 catch（718-731）只 `banner("切换章节前草稿保存失败…")`，没有调用 `handleDraftError(error)`；`state.draftBlocked` 可能仍为 false，冲突面板不出现。用户无法在界面上选择“载入/合并”，只能继续停留或再触发一次自动保存。最小修复：catch 中若是 `draft_conflict`，调用 `handleDraftError`（它会 showDraftConflict），而不是只 banner。

## 5. 复测通过项

### 5.1 自动化测试与发布校验

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-d
npm test
```

```text
ℹ tests 174
ℹ pass 158
ℹ fail 0
ℹ skipped 16
```

```bash
node scripts/check-release.mjs --local
```

```text
发行清单校验通过：1188 个文件与清单一致，buildId=c355fa1adf506f530484758c49bbf862330a237631db2a32c988124351c1f47b
EXIT=0
```

### 5.2 D-08 生成物一致性

- `client.js` 内嵌 ATELIER CSS 与 `assets/atelier-base.css + atelier-native.css + 3 个 woff2` 逐字节一致；
- `client.js` 内嵌 WORKBENCH CORE、`backend/manager/static/workbench-core.js`、`scripts/shared/workbench-core.js` 三者一致；
- `node --test test/workbench-ui.test.mjs` 的相关用例全部通过。
- 结论：本工作树的 client.js 没有生成物漂移；D-15 只是体积问题，不是内容不一致。

### 5.3 D-05 Ctrl+S 焦点分发

`test/workbench-ui.test.mjs:157-167` 通过：

- `#wb-editor` / `#wb-title` → `save-version`；
- `#wb-outline-text` → `save-outline`；
- `#wb-lore-text` → `save-lore`；
- `#wb-meta-*` → `save-meta`；
- `#wb-annotation-input` → `none`；
- 其他 `DIV` → `save-version`。

补测：在 1280×800 下切到“大纲与设定”，聚焦 `#wb-outline-text` 输入后按 Ctrl+S，只发出 `PUT /api/projects/p1/outline/files/总纲.md`，没有向 `/chapters/2` 发 PUT；toast 为“大纲已保存”。实际输出：

```text
puts [["/api/projects/p1/outline/files/%E6%80%BB%E7%BA%B2.md",
       "{\"content\":\"新大纲\",\"revision\":\"r1\",\"op_id\":\"outline_...\"}"]]
toasts ['大纲已保存×']
```

D-05 原始缺陷已关闭。

### 5.4 D-16 断点矩阵

`probe_breakpoints.py`（390/520/759/760/761/767/768/900/901/1100）实际结果：

| 宽度 | `.wb-shell` | `.mobile-dock` | `.wb-mobile-bar` | 横向滚动 |
|---|---|---|---|---|
| 390 / 520 / 759 / 760 | block（抽屉 fixed） | flex | flex | 无（scrollWidth=viewport） |
| 761 / 767 / 768 | grid（186 + center + 260） | none | none | 无 |
| 900 / 901 / 1100 | grid | none | none | 无 |

761–767 的 7px 重叠带按 D-16 约定走桌面 dock/桌面工作台，没有横向溢出。通过。

## 6. 测试盲区（为什么 174 项全绿仍漏掉这些）

1. `test/workbench-ui.test.mjs:139-155` 的 D-01 回归只断言 `baseVersionId/baseSha`，没有构造 `base_content:null` 或 `base_content:""`，也没有断言 `blocked` 或合并结果；D-01R 的静默覆盖路径不在测试范围内。
2. `workbench.js` 的 `applyChapter`、`recallDraftEpoch`、`putDraft`、`handleDraftError`、`resolveConflict` 都没有行为测试；现有测试通过 `__workbenchTestHooks` 只测 5 个纯函数。
3. `client-workbench.test.mjs` 只测 `wbDraftPayload`、`wbVersionPayload`、`wbMergeTexts` 等纯函数，没有挂载 `WorkbenchPage`；D-C1 的章节切换竞态无法被现有测试发现。
4. `release-check.test.mjs` 只测“manifest 条目缺失”，没有测“根入口缺失”；因此 D-RG1 可以通过。
5. `workbench-ui.test.mjs` 的 IME 测试只测 `editorWriteBlocked` 纯函数，不模拟 blur/visibility 后的 dirty/落盘；D-03P 的失焦丢字不在覆盖范围。

## 7. 探针与证据文件

所有探针只写入 `/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-d/`，未改仓库：

| 文件 | 用途 |
|---|---|
| `probe_aria.py` | 移动抽屉 inert/焦点/Tab 序列/Resize（D-04M） |
| `probe_annotation.py` | 切章后批注按钮/hint 状态（D-02D） |
| `probe_ctrlS_outline.py` | 大纲编辑器 Ctrl+S 只保存大纲（D-05 正向） |
| `probe_ime_get_async.py` | 延迟 GET 期间 IME pending（D-03P 正向） |
| `probe_ime_blur.py` | blur 复位 IME 不落 dirty（D-03P 缺口） |
| `probe_epoch_accept.py` | 服务端 epoch=7 时只试 0/1/2（D-11S） |
| `probe_blocked_save.py` | 锁死后正式保存不解锁（D-11S） |
| `probe_basecontent.py` | `base_content:null` 不 blocked（D-01R） |
| `probe_nullbase_dataloss.py` | 合并后静默覆盖 v2（D-01R） |
| `probe_draft_reload_base.py` | 载入对方草稿后 base 未 adopt（D-01R2） |
| `probe_merge_tail_draft.py` | 尾章草稿无提示（D-09R） |
| `probe_bfcache.py` | pagehide bfcache 假冲突（D-14K） |
| `probe_breakpoints.py` | 760/761/767/900 断点矩阵（D-16） |
| `root-missing-client/`、`root-missing-index/` | 缺根入口的 check-release 反向验证（D-RG1） |
| `pack.json` | `npm pack --dry-run --json` 输出（D-15/D-RG2） |

## 8. 最终判定

- **静态直写工作台（local Web UI）**：不具备发布条件。D-01R 是可复现的静默覆盖后台正文；D-11S 是可复现的首次自动草稿锁死。
- **DSH 面板（client.js）**：现有纯函数测试不足以证明章节切换安全；D-C1 需要真实 React/DSH 宿主回归后再判定。
- **发布门禁**：`check-release --local` 当前通过只能证明“现有的 1188 个 backend 文件哈希一致”，不能证明包完整、版本可发布、根入口存在或包体可接受；D-RG1/D-RG2 必须在发布前关闭。
- **建议修复顺序**：D-01R → D-11S → D-01R2 → D-03P/D-02D → D-04M/D-09R → D-14K → D-RG1/D-RG2；D-15/D-10 作为明确的残余风险继续跟踪，不要用“测试全绿”掩盖。
