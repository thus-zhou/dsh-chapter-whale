# D 域独立审计报告（第四轮）— 前端 / 静态资产 / 构建 / 发布

- 审计对象：`/home/ubuntu/.hermes/cache/scratch/audit-v4/head-d`（detached `ce50d08`，修复提交链 `bae08da` → `36f5add`；`node_modules` 为软链）
- 审计方式：只读代码审查 + `npm test` + `node scripts/check-release.mjs --local` + 本地静态 fixture（`127.0.0.1:8873`，Playwright + 系统 Chrome，所有探针只写 `tmp-d/`）+ 生成物重建比对
- 仓库状态：审计开始/结束时 `git status --short` 均只有 `?? node_modules`；未提交、未联网
- 基线：
  - `npm test` = **185 tests / 169 pass / 0 fail / 16 skipped**
  - `check-release --local` = **1189 个文件**，`buildId=1079d3627947e433115e9886d8325b544ee7c1927b720941d5c620b89d753bac`
  - 上一轮报告：`docs/audits/v0.8-v0.9.5-v3/part-d.md`（基线 `4f5a5a1`）；修复记录：`docs/remediation/v0.8-v0.9.5-remediation-v3.md`

## 0. 结论摘要

**本轮未发现 P1；上一轮两条 P1（D-01R、D-11S）与 D-C1 的代码路径修复均实测成立。** 但仍有 **5 条 P2**：1 条是本轮 D-RG1 修复的发布门禁残余，1 条是章节切换的数据丢失缺口，3 条是上轮未关闭的已知 P2。发布门禁仍不能证明“发出去的包可加载”。

最严重的发现：

1. **D-R4-02（P2，D-RG1 残余）** `check-release` 只检查“根入口文件存在”，不检查它是否被 `package.json files` 打进包：把 `client.js` 从 `files` 删除后，`check-release --local` 仍 EXIT 0，而 `npm pack` 的 1250 个条目里没有 `client.js`——`prepublishOnly` 仍可发布一个缺少 client 的包。
2. **D-R4-03（P2，数据丢失缺口）** 章节 GET 飞行期间用户在旧章节输入的文字会被新章节正文静默覆盖（静态实测 700ms 延迟下输入“临时输入”，最终编辑器只剩第一章正文，且没有任何草稿 PUT）。DSH 的 `applyServerData` 在 key 变化时同样不看 `dirtyRef`。
3. **D-R4-01（P3，新回归）** D-01R2 的异步取基线没有章节/作品 token：在“载入对方草稿”的 GET 飞行期间，若用户确认“丢弃本地内容”切章（或走 merge/split/restore 的 `force` 切章），会把**上一章的草稿正文、draft id、base 版本**写进当前章节（实测 current=1，编辑器/标题/draft/base 全是第 2 章的内容）。普通未确认的 dirty 切章被 `openChapter` 的 confirm 挡住，所以定为 P3。

P2 全表：

| ID | 级别 | 状态 | 摘要 |
|---|---|---|---|
| D-R4-02 | P2（新，D-RG1 残余） | 未修 | 根入口只查存在，不查 `files` 打包归属；缺 client.js 的包仍可通过门禁 |
| D-R4-03 | P2（缺口） | 未修 | 章节 GET 期间输入被新章正文覆盖（静态 + DSH） |
| D-02D | P2（上轮遗留） | 未修 | 切章后批注按钮/hint 仍是上一章状态 |
| D-04M | P2（上轮遗留） | 未修 | `aria-modal` 抽屉打开时 `.mobile-dock/.wb-page-head/.wb-mobile-bar` 仍可 Tab |
| D-RG2 | P2（上轮遗留） | 未修 | `0.7.5` 对应多个 buildId/包体，`RELEASE_STATUS.md` 仍是旧记录 |

P3 新观察：D-R4-01（异步取基线跨章污染）、D-R4-04（reload/merge 在 IME 守卫前已改写 state）、D-R4-05（静态草稿保存响应未做章节归属校验）、D-R4-06（blocked 草稿横幅承诺 Ctrl+S，但缺 base id 时服务端 400）、D-R4-07（blocked+dirty 时 `commitPendingChapter` 跳过保存直接换章）、D-R4-08（DSH reload 对方草稿取不到 base_content，需等 15s 轮询）、D-R4-09（merge-tail 文案/上一章残留草稿/非连续章号提示）。

## 1. 已知项复核

| 项 | 本轮结果 | 证据/说明 |
|---|---|---|
| **D-01R** 草稿 null base 静默覆盖 | **关闭** | `resolveDraftBaseline` 对 `base_content:null` 返回 `blocked:true`，`applyChapter` 不再用 `||` 回填当前正文；实测“旧草稿 v1 + 后台 v2”按 Ctrl+S 409，点“三方合并”被拒，没有第二次以 v2 身份写回。 |
| **D-11S** draft epoch null / 锁死 | **关闭** | `recallDraftEpoch` 区分 `null`；实测服务端 epoch=9 时首个草稿 PUT 就发 9 并成功；强制全部 409 时 4 轮后 blocked，Ctrl+S 正式保存成功后 `blocked:false`、banner 清空，继续输入恢复自动草稿（epoch 1）。 |
| **D-C1** 切换/IME/保存竞态（DSH） | **代码路径成立，仍有新缺口** | `selectChapter/changeProject` 先 flush、失败不切换；`pendingChapterRef` 在 composing 时暂缓；`wbSameChapterRef` 阻止旧章保存响应写新章。但 D-R4-03/04/08 是同一区域的残余；无真实 React 宿主实机。 |
| **D-01R2** 载入/合并未 adopt 对方 base | **静态关闭；DSH 部分** | 静态 reload 实测下一步 Ctrl+S 发送 `expected:ver_0002_bbbb`（对方 base）；merge 对不同 base 会拒绝并提示先载入。DSH 冲突载荷仍无 `base_content`，reload 后 base 可能 blocked 到下一次 15s 轮询（D-R4-08）。 |
| **D-02D** 批注 hint/按钮 dirty | **仍开放** | 切章后 hint/按钮保持上一章；点击提交才 toast 不可用（实测）。见 §4.1。 |
| **D-03P** blur/visibility IME 丢字 | **主路径关闭；标题仍开放** | 正文 blur 后 dirty=true 且 2.2s 内出现含组合尾字的草稿 PUT；标题组合仍会保存半截标题（D-IME2）。 |
| **D-04M** 抽屉背景 inert | **仍开放** | Tab 仍逃逸到 `.cw-lens-circle`/`.cw-nav-pill`；`setBackgroundInert` 只覆盖 `.sidebar/.topbar/.skip-link`。见 §4.2。 |
| **D-09R** merge-tail 尾章草稿 | **关闭（主路径）** | 打开合并工具前并发 GET 最后两章；实测弹窗先 confirm“第 2 章还有未提交草稿……”，确认后才开对话框；提交清理只作用于当前合并章。文案/上一章残留见 D-R4-09。 |
| **D-14K** pagehide bfcache | **关闭** | 浏览器实测 `pagehide persisted=true` 不发 keepalive；`persisted=false` 发 1 次，内容正确。 |
| **D-RG1** 缺根入口仍通过 | **关闭（存在性）；打包归属仍开放** | 删除 `client.js`/`index.js`/`managed-runtime.mjs` 均 EXIT=1；但 `files` 漏掉 client.js 时仍通过（D-R4-02）。 |
| **D-RG2** 同版本多包体/发布记录 | **仍开放** | `package.json` 仍 0.7.5；`RELEASE_STATUS.md` 仍是 `1168 / 9f1cc3… / 12,462,042`，当前 `1189 / 1079d3… / 12,718,047`。 |
| **D-15** 包体/字体双份 | **仍开放** | `client.js` 5,293,292 B；字体 3,355,008 B 同时内嵌和随包分发；`npm pack` 12,718,047 B / unpacked 26,086,042 / 1251 files。 |
| **D-05 / D-08 / D-16** | **通过** | 单测通过；重建 `client.js` 与当前 HEAD sha256 完全一致（`ddc525e7…`）；760/761/767/900/1100 断点无横向溢出。 |

## 2. 新回归与 P2

### D-R4-02（P2，D-RG1 残余）`check-release` 只校验根入口“存在”，不校验它被 `package.json files` 打进包

**位置**

- `scripts/check-release.mjs:31-65`（`declaredRootEntries`：把 `exports/main/dsh.patch/files` 的并集做存在性检查）
- `scripts/check-release.mjs:362-365`（`client.js` 缺失时的旧 note 分支）
- `package.json:47-70`（`files` 是 npm 的发布 allow-list）
- `package.json:101`（`prepublishOnly: node scripts/check-release.mjs --local`）

**机制**

`rootEntries` 是 `exports`、`files`、`main`、`dsh.bundle.patch` 的**并集**。检查只做 `existsSync(path) && statSync(path).isFile()`。因此如果 `package.json` 的 `files` 数组漏掉 `client.js`（但 `exports["./client"]` 仍指向它），文件在源码树里存在 → 检查通过；而 `npm pack` 只按 `files` 收录 → 包里没有 `client.js`。`prepublishOnly` 只跑这个脚本，不跑 `npm test`，所以可以发布一个无法加载的包。

**实测**（`tmp-d/release-gate.log`；副本只改 `package.json` 的 `files`，`client.js` 仍在树里）：

```text
== files-no-client (client.js present, omitted from package.json files)
发行清单校验通过：1189 个文件与清单一致，buildId=1079d362...
EXIT=0
== pack files-no-client
1250 false          # npm pack 的 1250 个条目中没有 client.js
```

对照：删除 `client.js`/`index.js`/`managed-runtime.mjs` 文件本身均 EXIT=1（存在性检查已生效）。

**影响**

- D-RG1 声称“缺失根入口即 error”，但对“文件在、包里没有”的同类事故仍无门禁；
- 打包脚本/手工改 `files` 后，发布不会被拦截，用户装到包后 DSH 无法加载 client；
- 现有 `test/release-check.test.mjs` 只断言真实 `package.json.files` 含三个入口，没有构造“从 files 删除但文件仍存在”的反例，所以测试也覆盖不到。

**最小修复**

- 对每个真正被宿主加载的根入口（`exports`/`main`/`dsh.bundle.patch` 的解析结果），要求它被 `files` 的某个字符串或目录前缀匹配；或直接跑 `npm pack --dry-run --json` 并断言 `client.js/index.js/managed-runtime.mjs/cordis.patch.yml` 出现在 packlist。
- 增加负向测试：复制 fixture 后从 `pkg.files` 删除 `client.js`，保留文件，断言 `check-release` 退出非 0。
- 若不想引入 npm packlist 依赖，最小硬编码：`const REQUIRED_PACKED = ['index.js','client.js','managed-runtime.mjs','cordis.patch.yml'];` 逐个检查 `files` 匹配。

### D-R4-03（P2，数据丢失缺口）章节 GET 期间输入的文字被新章正文静默覆盖（静态 + DSH）

**位置**

- `backend/manager/static/workbench.js:1156-1198`（`openChapter` 在 GET **之前**检查 dirty）
- `backend/manager/static/workbench.js:1200-1256`（`applyChapter` 用 `setEditorValue(content,title,true)` 强制覆盖，未再检查 dirty）
- `client.js:6367-6384`（DSH：`key !== loadedKeyRef.current` 分支只检查 `composingRef`，不检查 `dirtyRef`）
- `client.js:6347-6352`（`applyServerData` 无条件 `setText(doc.content)`）

**机制**

静态 `openChapter` 的流程是：检查 `state.dirty` → 发 GET → `applyChapter`。GET 飞行期间编辑器仍可编辑；用户输入后 `state.dirty=true`，但 GET 返回的 `applyChapter` 不再看 dirty，直接 `setEditorValue(..., true)` 覆盖并把 `state.dirty=false`。如果输入发生在 1.5s 草稿防抖触发之前，连草稿都不会落盘。

DSH 同理：`selectChapter` 先把 dirty 草稿 flush 掉再 `setSelectedChapter`；新章的 `chapterPoll` 数据到达时，`key !== loadedKeyRef.current` 分支只挡 IME，不挡 dirty；`applyServerData` 直接 `setText`。

**实测**（`tmp-d/p_switch_typing.py`，第 2 章已打开，点击第 1 章时 GET 延迟 700ms，点击后 100ms 输入“临时输入”）：

```text
after {'current': 1, 'text': '第一章正文。', 'dirty': False}
puts []
```

输入完全消失，且没有任何草稿 PUT。

**影响**

- 章节加载窗口内的输入无提示丢失；窗口等于 GET 延迟（本地正常 <100ms，慢盘/长章节/远程宿主可达数百 ms 到秒级）；
- 与 D-03P 的 IME 场景是同一类“切换期间输入”缺口：v3 的 `pendingChapter` 只覆盖 `composing`，不覆盖普通输入；
- DSH 同样存在（代码路径可证，未能挂载真实 React 宿主实测）。

**最小修复**

- 静态：GET 前记录 `const wasDirty = state.dirty`，`applyChapter` 里若 `state.dirty` 为真则不要 `force=true`，改为把 `data` 放入 `pendingChapter` 并在用户确认“丢弃本地输入/先保存”后应用；或在 GET 期间把编辑器 `readOnly/disabled`（并给“正在读取第 N 章…”提示）。
- DSH：把 `key !== loadedKeyRef` 分支的 `if (composingRef.current)` 扩展为 `if (composingRef.current || dirtyRef.current)`，dirty 时缓存 pending，`flushDraft` 成功后再 `applyServerData`；失败则留在当前章并提示。
- 补一个“GET 延迟期间键入”的浏览器回归测试（静态可直接用现成 fixture；DSH 至少用纯函数/组件测试覆盖 key 变化 + dirty 分支）。

## 3. P3 新观察

### D-R4-01（P3，新回归）`resolveConflict` 的异步取基线没有章节/作品 token：确认/强制切章后会把对方草稿写进当前章

**位置**

- `backend/manager/static/workbench.js:2139-2161`（`fetchConflictDraftBase`）
- `backend/manager/static/workbench.js:2163-2206`（reload 分支：`await` 后直接写 `state.draft/base*` 并 `setEditorValue`）
- `backend/manager/static/workbench.js:2240-2290`（merge 分支同样 `await` 后直接写）
- 参考：`workbench.js:1156-1198`（`openChapter` 有 `chapterToken`，但 `resolveConflict` 没用）

**机制**

`resolveConflict` 在开头捕获 `conflict`，但随后 `await fetchConflictDraftBase()`（GET `/chapters/<current>`，可被网络拖慢）。GET 返回后代码无条件：

```js
state.draft = {... adopted ...};
state.baseVersionId = adopted.baseVersionId;
state.baseSha = adopted.baseSha;
state.baseContent = adopted.baseContent;
state.draftBlocked = Boolean(adopted.blocked);
if (!setEditorValue(String(current.content||""), String(current.title||""), false)) ...
```

触发切换的路径有三类：(a) 冲突时 `draftBlocked+dirty`，`openChapter` 弹“切换会丢掉本地未保存内容。继续？”，用户点“继续”后 GET 继续飞行；(b) `dirty=false + draftBlocked=true`（例如 `draft_preserved` 后 `reconcilePreservedDraft` 展示冲突）时 `openChapter` 不弹 confirm，直接切章；(c) merge/split/restore 的 `openChapter(..., {force:true})`。随后旧请求返回，把上一章的对方草稿正文、标题、`draft_id/epoch/revision`、`baseVersionId/baseSha/baseContent` 全部写进新章。普通未确认的 dirty 切章会被 confirm 挡住（实测 dismiss 后 current 不变），所以定为 P3。

**实测**（`tmp-d/p_conflict_switch3.py`：2 章、GET 延迟 1.5s、冲突面板打开后点“载入对方版本”，200ms 后点第 1 章并**接受** confirm）：

```text
before {'current': 2, 'dirty': True, 'blocked': True}
DIALOG 当前章节有草稿冲突，切换会丢掉本地未保存内容。继续？
after click {'current': 1, 'dirty': False, 'blocked': False}
after race {'current': 1, 'title': '服务器草稿', 'text': '服务器草稿正文。',
            'draftId': 'drf_server', 'base': 'ver_0002_bbbb',
            'dirty': False, 'conflictHidden': True}
```

当前章是 1，但编辑器、标题、draft id、base 都是第 2 章的。（早期 `p_conflict_switch.py` 用了 3 章 fixture，应用默认打开最后一章第 3 章，点第 3 章是 no-op，不能作为跨章证据；以 `cs3.out` 为准。）

**影响**

- 当前章的编辑器被替换成上一章的草稿，标题也变成上一章的草稿标题；
- 下一次 Ctrl+S 用上一章的 `expected_version_id/sha` 去写当前章，真实服务端必然 409；若用户点“用我的版本覆盖”，会把上一章草稿正文写成当前章新版本（显式操作，但语义已错）；
- 自动草稿会以上一章的 draft identity 向当前章 PUT，触发 409/纪元重试，界面进入假冲突；
- 属于 D-01R2 修复引入的新异步竞态（v3 的 reload/merge 是同步的）；触发需要用户确认丢弃或 force 切章，故 P3。

**最小修复**

- `resolveConflict` 开头捕获 `const chapterId = state.currentId, projectId = state.projectId;`，每次 `await` 后先校验仍相等，否则放弃本次 reload/merge（可 toast“章节已切换，已取消载入/合并”）。
- `fetchConflictDraftBase(current, {chapterId, projectId})` 显式接收目标，不要从全局 state 取；GET 后用同一 token 再校验。
- 同类问题也存在于 `prepareMergeTail`（`workbench.js:3376-3392`）：GET 期间切换作品后，dialog 可能在切换后弹出，而 `submitMergeTail` 使用**新的** `state.projectId` 执行 merge-tail，合并的是新作品的尾章；建议同样加 project token，或在 `openDialog` 前校验 `state.projectId` 未变。

### D-R4-04（P3）reload/merge 在 IME 守卫**之前**已改写 draft/base：`setEditorValue` 拒绝时 state 已指向对方草稿

**位置**：`workbench.js:2178-2206`（先写 `state.draft/base*`，再 `setEditorValue` 守卫）；merge 分支 `2261-2290` 同样。

**实测**（`tmp-d/p_reload.py` 的 ime 场景：冲突面板打开后、正文仍在组合中，用 `element.click()` 触发 reload，不触发 blur）：

```text
ime after programmatic reload {'composing': True, 'blocked': False,
  'draftId': 'drf_server', 'draftBase': 'ver_0002_bbbb',
  'base': 'ver_0002_bbbb', 'text': '本地草稿正文。新拼', 'dirty': True, ...}
ime draft_puts [... {"expected_draft_id": "drf_server", "expected_draft_epoch": 5,
                     "expected_draft_revision": 1, "content": "本地草稿正文。新拼"}]
```

即：编辑器保留本地文本，但 `state.draft` 已是对方草稿、`base` 已切到 v2、`blocked=false`；组合结束后 1.5s 自动 PUT 以对方草稿 identity 提交本地文本，覆盖对方草稿（内容未合并）。真实鼠标点击会先 blur 结束组合，所以正常指针路径安全；键盘/读屏/脚本激活（不移动焦点）可触发。

**最小修复**：先 `setEditorValue` 成功后再写 `state.draft/base*`；或在失败分支回滚到操作前的快照。merge 分支同理。

### D-R4-05（P3）静态 `saveDraftNow` 的响应没有章节归属校验

**位置**：`workbench.js:1729-1769`（`state.draft = draftIdentityFrom(draft)`、`updateChapterBadge(state.currentId)`）；`applyChapter` 在 1230-1236 替换 `state.draftQueue`。

`saveDraftNow` 捕获的 PUT 若在强制换章（merge/split/restore 的 `openChapter(...,{force:true})`，或 blocked 草稿下确认切作品）之后返回，会把旧章的 draft id/epoch 写到新章 `state.draft`，并以新 `state.currentId` 更新 badge。后续自动保存会拿旧章 identity 打新章（服务端 409/纪元重试），或 `discardChapterDraft` 用错身份。概率低（强制换章 + 草稿 PUT 飞行），但属于静态与 DSH 的不对称：DSH `persistDraftOnce` 有 `sameChapter()` 守卫。

**最小修复**：`saveDraftNow` 开头记录 `const chapterId=state.currentId, token=state.chapterToken;`，响应后若 token/chapterId 变化则丢弃结果（保留旧章 identity 由其自身队列处理），`handleDraftError` 同样加 token 守卫。

### D-R4-06（P3）blocked 草稿横幅承诺“Ctrl+S 直接保存”，但缺 base id 时（有版本元数据的章节）服务端 400

**位置**：`workbench.js:1265-1270`（banner）、`224-230`（缺 base id 时仍 blocked）、`1930`（`expected_version_id: state.baseVersionId || ""`）；服务端 `chapter_editor.py:565-566`（有版本时 `not expected_version or not expected_sha` → `expected_version_required`，status 400）。

**实测**（`tmp-d/p_legacy.py`，draft 有 `base_content` 但 `base_version_id/base_sha256` 为 null）：

```text
loaded {'baseVersionId': '', 'baseSha': '', 'blocked': True,
        'banner': '...可按 Ctrl+S 直接保存正式版本。'}
saves [{'expected_version': '', 'expected_sha': '', 'content': '旧草稿正文。'}]
after {'banner': '保存失败：expected_version_required · expected_version_id 与 expected_content_sha256 必填', ...}
```

**影响**：缺少 `base_version_id/base_sha256` 的草稿在有版本元数据的章节上恢复后无法提交（既不能自动草稿，也不能正式保存），只能手工复制；不造成静默覆盖，但横幅承诺与实际行为矛盾。（无版本元数据、但仍带 `base_sha256` 的老章可走服务端 legacy 首次保存路径，不在本缺口内。）

**最小修复**：blocked 文案区分“base 正文未知但版本 id/sha 已知”（Ctrl+S 可试）与“版本 id/sha 也缺失”（禁用保存/提示先载入最新正文）；后者提供显式“以当前正文为基线保存”的确认路径（GET 当前章取 `version_id/sha256` 后填 expected）。

### D-R4-07（P3）`commitPendingChapter` 在 `draftBlocked && dirty` 时跳过保存，直接把 pending 章应用

**位置**：`workbench.js:1277-1291`。

```js
if (state.dirty && !state.draftBlocked) { try { await flushDraftNow(); } catch ... }
...
applyChapter(data);
```

`openChapter`（1169-1179）对 blocked+dirty 有 confirm，但 `commitPendingChapter` 没有。场景：blocked 草稿章、用户有未落盘输入、章节 GET 在输入法组合期间到达（`pendingChapter`），组合结束 → `handleEditorInput` 标 dirty → `commitPendingChapter` 跳过 flush → `applyChapter` 覆盖，输入丢失且无确认。修复：与 `openChapter` 一致，blocked+dirty 时 `window.confirm` 或保留 pending/提示先处理冲突。

### D-R4-08（P3）DSH `reloadConflict`/`mergeConflict` 取不到对方草稿的 `base_content`，blocked 依赖 15s 轮询

**位置**：服务端冲突载荷 `backend/integration/chapter_editor.py:359-364` 仍只返回 `draft_id/epoch/revision/title/content/base_version_id/base_content_sha256/updated_at`；DSH `client.js:7201`（reload）与 `7243-7251`（merge）只调用 `wbDraftBaseAdoption(current, baseRef.current)`，不会 GET；`POLL_MS=15000`（`client.js:1202`）。

当对方草稿 base 与本地 base 不同且载荷无 `base_content` 时，`wbDraftBaseAdoption` 返回 `blocked:true, content:''`；“载入服务器草稿”后 `baseRef.blocked=true`，`mergeConflict` 直接拒绝。只有下一次 `chapterPoll`（GET 含 `draft.base_content`）才会解除（15s 级）。期间 Ctrl+S 会用对方草稿 base 发请求，文件已前进时 409，形成“载入后仍不能合并”的短时死角。

**最小修复**：服务端把 `base_content` 加入 `draft_conflict` 的 `current_draft`（与 `chapter_state` 一致）；或 DSH reload/merge 前 GET `/chapters/<id>` 取 `draft.base_content`（静态 `fetchConflictDraftBase` 已有实现，可复用逻辑）。

### D-R4-09（P3）merge-tail 的提示/残留草稿/非连续章号

- **位置**：`workbench.js:288-292`（`mergeTailDraftMessage`）、`3376-3392`（`prepareMergeTail`）、`3482-3497`（`submitMergeTail`）；`client.js:7101-7112`（DSH）。
- **文案与行为不一致**：提示说“合并会归档并在回收站中保留整章（含草稿）”，但后端 `merge_tail` 只归档**尾章**（`chapter_editor.py:1429-1431` 的 `delete_chapter(last)`）；**上一章（合并目标）的草稿不会被归档也不会被删除**，合并后仍作为陈旧草稿保留。若当前章不是目标章，`submitMergeTail` 不会清理它；下次打开合并章会恢复“基于旧版本”的草稿，用户需再合并一次。不是数据丢失，但提示误导。
- **非连续章号**：前端 `previous = last - 1` 直接 GET；若中间章被删（空章可删），GET 404 → toast“检查尾章草稿失败”，而真实原因应是 `merge_needs_adjacent_chapters`。建议用 `chapters` 排序后的倒数第二个 id，并明确提示“最后两章不连续，无法合并”。
- **异步项目竞态**同 D-R4-01：`prepareMergeTail` 的 GET 飞行期间切作品，dialog 可能在切换后弹出，确认后用新 `state.projectId` 合并新作品的尾章。

## 4. 上轮 P2 仍开放

### 4.1 D-02D（P2）切章后批注按钮/hint 仍是上一章状态

**位置**：`workbench.js:1247-1249`（`applyChapter` 只重置 `annotationsReady/annotationProbed/remoteAnnotations`）、`2486-2505`（`probeAnnotationEndpoint` 才改 hint/按钮）、`2580-2596`（`submitAnnotation` 用内存 `annotationsReady` 拦截）、`index.html:200-202`。

`applyChapter` 不重置 `#wb-annotation-submit.disabled`/`title`/`#wb-annotation-hint`，也不在 `rightTab==="annotations"` 时重新 probe。实测（`tmp-d/p_annotation.py`）：

```text
after probe hint: 批注接口已连接 · 本章 0 条批注。
after probe disabled: None
chapter1 title 第一章
after switch hint: 批注接口已连接 · 本章 0 条批注。
after switch disabled: None
toasts ["批注后端暂不可用，当前只能本地暂存×"]
```

**最小修复**：`applyChapter` 统一 `els.annotationSubmit.disabled=true`、`setAttribute("title","正在检测批注接口")`、hint 改“正在检测批注接口…”；末尾若 `state.rightTab==="annotations"` 调 `probeAnnotationEndpoint()`；probe 失败时允许重试（`annotationProbed=false`）。

### 4.2 D-04M（P2）`aria-modal` 抽屉打开时背景仍有可聚焦区域

**位置**：`workbench.js:1575-1584`（`setBackgroundInert` 只选 `.sidebar/.topbar/.skip-link`）、`1586-1597`（`syncDrawerMode` 明确 `els.mobileBar.inert=false`）、`index.html:103`（`.wb-page-head`）、`146-150`（`.wb-mobile-bar`）、`386-392`（`.mobile-dock`）。

实测 390×844 右抽屉打开（`tmp-d/p_aria.py`）：

```text
OPEN: right inert=false, center inert=true, dock inert=false,
      pageHead inert=false, mobileBar inert=false, sidebar/topbar inert=true
TAB_SEQUENCE ["wb-right-close","wb-annotation-input","wb-annotation-add",
              "modal-open","cw-lens-circle cw-project-lens",
              "cw-nav-pill is-active","cw-nav-pill"]
RESIZED all inert=false / dialog closed
```

关闭状态、焦点进入、resize 清理通过；问题只在“打开时的背景”。**最小修复**：`setBackgroundInert` 覆盖 `.workspace`（含 page head/center/mobile bar）、`.mobile-dock`；不要只覆盖 sidebar/topbar。

### 4.3 D-RG2（P2）`0.7.5` 对应多个包体/构建，`RELEASE_STATUS.md` 仍是旧记录

**位置**：`package.json:3`（0.7.5）、`CHANGELOG.md:1`（0.7.5）、`RELEASE_STATUS.md:9-16,20`、`runtime-manifest.json`（buildId `1079d3…`，3442 项）、`runtime-download.json`（buildId 同步）。

实测：

```text
package 0.7.5
manifest 0.7.5 1079d3627947e433115e9886d8325b544ee7c1927b720941d5c620b89d753bac 3442
check-release --local: 1189 files
npm pack: 0.7.5 12,718,047 B / unpacked 26,086,042 / 1251 files
RELEASE_STATUS: 1168 files / 9f1cc349… / 12,462,042 B / npm test 125 / integration 828 / manager 187
```

当前测试实际是 `npm test 185`、`manager 235`、`integration 1270`（修复记录），发布文档与当前树严重不一致。**最小修复**：发布前升到新版本并同步 CHANGELOG/RELEASE_STATUS/runtime-manifest/runtime-download；`check-release` 增加 `--expect-version` 或至少校验 RELEASE_STATUS 的 buildId/文件数与当前清单不矛盾；CI 在 `npm view <name>@<version>` 已存在时失败（本轮不联网，未执行）。

## 5. P3/已知遗留

- **D-15（P3）包体**：`client.js` 5,293,292 B；`assets/fonts` 合计 3,355,008 B 同时以 base64 内嵌并在包里分发；`npm pack` 12,718,047 B / 26,086,042 unpacked / 1251 files。`scripts/build-client-ui.py:78-88` 仍直接 base64 内嵌三份 woff2；`package.json files` 仍含 `assets/`。建议字体子集化/外链、从 `files` 排除 `assets/fonts`（若宿主不需要），并给 `check-release` 加包体上限。
- **D-IME2（P3）标题/大纲/设定无组合保护**：`workbench.js:505-509` 的标题 input 只看正文 `state.composing`（恒 false 于标题组合）；实测标题组合中自动草稿 PUT `title:"第"`。DSH `client.js:7406-7411` 的标题 input 也没有 `onCompositionStart/End`。`Ctrl+S` 的 `saveOutlineFile/saveLoreFile` 同样不检查组合。
- **D-ARIA1（P3）**：`workbench.js:1516-1520` `toggleMore` 仍无方向键/焦点进入。
- **D-ARIA2（P3）**：`client.js:3494-3512` `Segmented` 仍无 `role=tablist/tab`、`aria-selected`。
- **D-10（P3）**：静态/DSH 都订阅 `/room/stream`，但真实章节写入路径（`chapter_editor.save_draft/save_version/publishing`）不调用 `agent_room.append_event`，仓库内没有业务侧的 `chapter`/`draft` 事件生产者；前端章节刷新实际只能由 `resync_required` 触发（`agent_room.append_event` 的调用点只在 room/chief 消息接口，`kind` 由请求体自填）。
- **D-OPEN1（P3）**：`openChapter` 的 flush 失败 catch（`workbench.js:1174-1177`）仍只 banner，不调用 `handleDraftError`；draft_conflict 时冲突面板不出现。

## 6. 复测通过项与证据

### 6.1 自动化与发布门禁

```text
npm test: 185 tests, 169 pass, 0 fail, 16 skipped
check-release --local: 1189 files, buildId=1079d3627947e433115e9886d8325b544ee7c1927b720941d5c620b89d753bac, EXIT=0
```

### 6.2 D-01R（关闭）

`tmp-d/nullbase.out`：

```text
loaded {'text': '旧草稿正文。', 'baseContent': None, 'baseVersionId': 'ver_0001_aaaa',
        'blocked': True,
        'banner': '已恢复草稿，但缺少基线正文，自动草稿与三方合并已暂停；可按 Ctrl+S 直接保存正式版本。'}
conflict 服务端第 2 章的正文已变化（ver_0002_b…）。你的文字没有被覆盖。…
after merge click {'conflictHidden': False, 'baseContent': None, 'blocked': True,
                   'text': '旧草稿正文。', 'dirty': False}
version_saves [{"expected_version_id":"ver_0001_aaaa", ...},
               {"expected_version_id":"ver_0001_aaaa", ...}]
```

没有第二次以 v2 身份写回；合并按钮被 `state.draftBlocked` 拒绝（消息/冲突面板保留）。D-01R 原始静默覆盖路径关闭。

### 6.3 D-11S（关闭）

`tmp-d/epoch.out`：

```text
A loaded {'epoch': 9, 'blocked': False, 'banner': ''}
A puts [9] accepted [9]
B after reject puts [9, 0, 7, 8, 10, 11, 9, 0, 7, 8, 10, 11, ...]
B blocked? {'blocked': True, 'banner': '草稿纪元仍无法同步，自动草稿已暂停；按 Ctrl+S 保存正式版本后会自动恢复。', 'retries': 4, 'dirty': True}
B after save {'blocked': False, 'banner': '', 'base': 'ver_0003_cccc', 'dirty': False}
B resume puts [1] {'blocked': False, 'dirty': False, 'id': 'drf_new'}
```

### 6.4 D-14K（关闭）

`tmp-d/bf.out`：

```text
after bfcache pagehide puts [] dirty True
after teardown pagehide puts [{'content': '第二章正文。bfcache', 'epoch': 0}]
```

### 6.5 D-09R（关闭主路径）

`tmp-d/mt.out`：

```text
current 第一章 draft 草稿 —
dialog open True
merge label 把第 2 章并入第 1 章；两章都必须未发布。
confirms ['第 2 章 还有未提交草稿；合并会归档并在回收站中保留整章（含草稿）。继续？']
requests []
```

### 6.6 D-01R2（静态关闭）

`tmp-d/reload.out` normal 场景：

```text
normal after reload {'base': 'ver_0002_bbbb', 'baseSha': 'bbbb…', 'baseContent': 'v2 正文。',
                     'blocked': False, 'text': '服务器草稿正文。', 'dirty': False}
normal version_saves [{'expected': 'ver_0002_bbbb', 'content': '服务器草稿正文。改'}]
```

载入对方草稿后 Ctrl+S 使用对方 base，未再沿用本地 v1。`tmp-d/merge-draft.out` 对不同 base 拒绝自动合并：

```text
foreign after merge {... 'blocked': True, 'conflictHidden': False,
  'msg': '对方草稿基于另一个版本（ver_0002_b…），自动合并可能覆盖后台正文。请先载入对方草稿，核对后再保存。'}
```

### 6.7 D-RG1（存在性关闭）

`tmp-d/release-gate.log`：

```text
== root-missing-client: 缺少根入口：client.js … EXIT=1
== root-missing-index: 缺少根入口：index.js … EXIT=1
== root-missing-runtime: 缺少根入口：managed-runtime.mjs … EXIT=1
```

### 6.8 D-08 / D-05 / D-16

- **D-08**：在独立完整副本中运行 `python scripts/build-client-ui.py`，生成的 `client.js` 与 HEAD `client.js` 的 sha256 均为 `ddc525e7f2cb744df862985c50e112245ab9c7e8267ab711466adc905b7d4664`；`npm test` 的 ATELIER CSS/core 字节一致用例通过。
- **D-05**：`test/workbench-ui.test.mjs` 的 `ctrlSIntentFor` 用例通过；代码未改动。
- **D-16**：`tmp-d/bp.out` 在 390/520/759/760 走移动布局、761/767/768/900/901/1100 走桌面布局，`docScrollW == viewport`，无横向溢出。

### 6.9 D-C1（DSH）代码复核

- `selectChapter/changeProject`（`client.js:6651-6699`）在 dirty 时先 `await draftChainRef.current` + `flushDraft()`，失败留在当前章；`persistDraftOnce` 的 `sameChapter()`（6418-6423）阻止旧章响应写新章；
- `saveVersion`（`6701-6794`）响应前用 `wbSameChapterRef`（6732）校验；
- `pendingChapterRef`（6371-6378、6518-6531）在 composing 时暂缓并在 compositionend/blur 后提交。
- 但这些改动同时留下 D-R4-03/04/08；且仍**没有**真实 React/DSH 宿主的行为测试（`client-workbench.test.mjs` 只测纯函数）。

## 7. 测试盲区（为什么 185 项全绿仍漏掉本轮）

1. `test/workbench-ui.test.mjs:139-176` 的 D-01R/D-01R2 只测 `resolveDraftBaseline/conflictDraftBaseline` 纯函数，没有测 `resolveConflict` 的 `await` 前后章节一致性，也没有测“GET 期间切章”（D-R4-01）。
2. `test/client-workbench.test.mjs` 只测 `wbDraftBaseAdoption/wbMergeBaseCompatible/wbSameChapterRef/wbMergeTailDraftMessage` 纯函数；没有挂载 `WorkbenchPage`，D-R4-03/04/08 的异步路径不可见。
3. `test/workbench-ui.test.mjs` 的 IME 用例只覆盖 `editorWriteBlocked` 和 blur 纯函数；没有“章节 GET 期间输入”“blocked+dirty 的 pendingChapter”场景（D-R4-03/07）。
4. `test/release-check.test.mjs` 的负向用例只删**文件本身**，没有构造“文件存在但从 `files` 删除”的打包归属反例（D-R4-02）。
5. `probe_annotation`/`probe_aria` 这类浏览器回归不在 `npm test` 中；D-02D/D-04M 因此可以长期全绿。

## 8. 证据文件

所有探针只写入 `/home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-d/`，未改仓库（审计中一次临时副本因 `cp -al` 硬链接触发了 `head-d/package.json` 的 `files` 删改，已立即 `git checkout -- package.json` 恢复，最终 `git status` 仅 `?? node_modules`）：

| 文件 | 用途 |
|---|---|
| `p_nullbase.py` / `nullbase.out` | D-01R：null base 不合并、不静默覆盖 |
| `p_epoch.py` / `epoch.out` | D-11S：epoch=9 直连成功、blocked→正式保存解锁 |
| `p_reload.py` / `reload.out` | D-01R2 reload adopt；D-R4-04 IME 守卫顺序 |
| `p_merge_draft.py` / `merge-draft.out` | D-01R2 异 base 拒绝合并 |
| `p_ime.py` / `ime.out` | D-03P blur 落盘；D-IME2 标题半截 |
| `p_bfcache.py` / `bf.out` | D-14K pagehide persisted |
| `p_merge_tail.py` / `mt.out` | D-09R 尾章草稿 confirm |
| `p_annotation.py` / `ann.out` | D-02D 切章后 hint/按钮 |
| `p_aria.py` / `aria.out` | D-04M 背景 inert/Tab 序列 |
| `p_breakpoints.py` / `bp.out` | D-16 断点矩阵 |
| `p_conflict_switch3.py` / `cs3.out` | D-R4-01 确认切章后的跨章污染（早期 `p_conflict_switch.py`/`cs.out` 为无效 fixture，未使用） |
| `p_switch_typing.py` / `st.out` | D-R4-03 GET 期间输入丢失 |
| `p_legacy.py` / `lg.out` | D-R4-06 blocked 横幅与 400 |
| `static-server.py` | 8873 静态 fixture |
| `release-gate.log`、`pack.json`、`pack-noclient.json`、`files-no-client/` | D-RG1 存在性通过 + D-R4-02 打包归属缺口 |
| `buildcopy/` | D-08 重建 client.js 字节一致 |

## 9. 最终判定

- **静态直写工作台**：上一轮两条 P1（D-01R/D-11S）已真实关闭；但“冲突载入”新引入跨章竞态（D-R4-01），章节 GET 期间输入仍会丢（D-R4-03），blocked 草稿还有三条 P3 边界。**仍不具备“可发布”条件**。
- **DSH 面板**：D-C1 的保存/IME 互斥代码路径成立，但 D-R4-03（dirty 时 key 变化覆盖）、D-R4-04（reload 顺序）、D-R4-08（base_content 缺失）仍存在；无真实宿主回归，建议按 HYPOTHESIS 继续跟踪。
- **发布门禁**：D-RG1 的“文件存在”检查已生效，但 D-R4-02（`files` 未包含根入口仍通过）意味着 `prepublishOnly` 仍不能证明包可加载；D-RG2 的版本/发布记录未更新；D-15 包体/字体双份未处理。发布前必须先关闭 D-R4-02 与 D-RG2。
- **建议修复顺序**：D-R4-02 → D-R4-03 → D-02D/D-04M → D-RG2 → D-R4-06/D-R4-01/D-R4-04/D-R4-05/D-R4-07/D-R4-08 → D-15。
