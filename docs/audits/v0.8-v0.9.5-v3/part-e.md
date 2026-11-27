# E 域独立审计报告（跨域契约 / 发布 / 路由 / 生成管线）

- 工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v3/head-e`，detached `4f5a5a1`（`docs: 更新修复提交链与 CI 记录`）
- 审计方式：只读代码审阅 + 真实 `TestClient` HTTP 探针 + 全量 manager/integration 测试 + `check-release --local`；未联网、未修改 tracked 文件、未 commit。
- Python：`/home/ubuntu/venvs/dsh/bin/python`（3.12.3）；探针与临时状态全部写入 `audit-v3/tmp-e/`。
- 说明：探针运行时测试套件曾在工作树生成 `backend/integration_data/` 与 `__pycache__`（均被 git 忽略），审计结束前已清理；最终 `git status --short` 仅剩 `?? node_modules` 软链。

## 0. 结论摘要

| 级别 | 数量 | 条目 |
|---|---|---|
| P0 | 0 | 未发现新的不可逆数据丢失或全站 500 |
| P1 | 1 | E-01 发布状态读模型无生产者：已发布章节可被删除/合并/拆分，发布分叉永远不告警 |
| P2 | 8 | E-02 空 workbench DB 仍 500；E-03 `publish/submit` 正文不绑定版本/审查；E-04 `chapter_state.reviewed` 编辑后仍为 true；E-05 版本错误码未映射；X-P2-2 全站恢复不恢复项目；X-P2-4 审批无生产者；X-P2-5 running→held；X-P2-6 standalone SSE 无 chapter/draft 生产者 |
| P3 | 5 | E-06 `build-runtime --manifest-only` 默认改 runtime 版本；E-07 `RELEASE_STATUS.md` 过期；E-08 `/internal/events/notify` 未接线；E-09 `chief_room_state` 丢弃 session；E-10 quality 分页前端未接（静态判定） |

**发布门禁结论**：干净工作树 `node scripts/check-release.mjs --local` **通过**，1188 个受管后端文件与清单一致，`buildId=c355fa1a...`；`runtime-download.json.buildId` 与清单同步，`runtimeAssetBuildId=b181...` 保留旧运行时复用。**但**跑完全量测试后工作树会多出 `backend/integration_data/`，再跑门禁会红；清理后恢复绿（见 §5）。

---

## 1. X 报告残余复核

### 1.1 X-P2-2（REPRODUCED）全站恢复不清理项目级 `global` 暂停行

**位置**
- `backend/manager/api_v09.py:255-270`：`system_ai_pause` 仅在请求带 `identity` 时写/删项目 `task_pauses(scope='global')`。
- `backend/integration/concurrent_engine.py:278-293`：`project_paused` 把 `scope='global'` 也当作项目暂停。
- `backend/manager/app.py:265-266`：`Operations._start_admitted` 命中 `project_paused` 后 409。

**机制**
`{"paused":true,"identity":X}` 同时写全局暂停文件和 X 项目的 `global` 行；自然恢复 `{"paused":false}`（不带 identity）只把全局文件写成 `paused:false`，不会删除 X 项目的 `global` 行。`project_paused(X)` 仍为真，`/generate`、`/stage`、`/publish` 等仍被 409 拦截。

**实测**（`tmp-e/probe_e.py`；项目 `潮汐钟`）
```
global-pause: 200 {'status': 'paused', ...}
project-paused-after-global: True
global-resume: 200 {'status': 'resumed', ...}
global-file-exists-after-resume: True      # 文件仍在，内容 paused=false
project-paused-after-resume: True
ops.start-after-global-resume: 409 {'code': 'conflict', 'message': '该作品已暂停自动化，请恢复后再执行'}
manual-project-resume: 200 {'status': 'resumed', 'scope': 'global'}
project-paused-after-manual: False
ops.start-after-manual: 200
```
因此不是“永久无法恢复”（`/api/projects/{id}/tasks/resume` 仍能清），但**全站恢复接口返回 resumed 与实际项目状态矛盾**，且自动化入口继续 409。

**影响**
全站恢复后曾带 identity 暂停过的作品仍不能生成/日更/发布，直到作者再点一次作品级恢复；接口语义自相矛盾。当前没有 `POST /api/system/ai/pause` 的前端调用，故影响 API 消费者与运维自动化。

**最小修复**
在全局暂停文件里记录 `paused_projects`（或由 `create_app` 传入项目枚举），恢复时遍历 `concurrent_engine.resume(book, "global")`；或者明确要求 pause/resume 必须带同一 identity，缺 identity 时拒绝而不是“只恢复一半”。

**复现命令**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-e
PYTHONPATH=backend /home/ubuntu/venvs/dsh/bin/python -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-e/probe_e.py
```

---

### 1.2 X-P2-4（REPRODUCED）审批卡片无生产路径，旧客户端稳定 400

**位置**
- `backend/manager/api_v085.py:276-288`：`evaluate_amendment` HTTP 路由只传 `context`，不传 `evaluator`。
- `backend/integration/agent_hub.py:397-422`：只有 `evaluator` 抛异常才 `room.create_approval(...)`；默认确定性 evaluator 不会抛。
- `backend/manager/api_v085.py:331-350`：`resolve` 强制要求 `artifact_fingerprint`/`approved_scope_hash`/`directive_revision`。

**机制**
全仓 `create_approval` 的生产调用只有 `agent_hub.evaluate_amendment` 的 `except` 分支；没有任何 HTTP 路由或前端创建 approval。`grep -rn "create_approval" backend --include='*.py' | grep -v test_` 只返回 `agent_hub.py:412` 与定义 `agent_room.py:461`。HTTP `evaluate` 不注入 evaluator，因此 fallback 永不触发；`GET /approvals` 在正常流程中永远为空。

**实测**
```
approvals-before: {'approvals': []}
amend: 200 ... held_task_ids ...
evaluate: 200 {'status': 'evaluated', 'wait_and_redo': [...]}
approvals-after-evaluate: {'approvals': []}
approval-legacy-body: 400 {'code': 'approval_binding_required', 'missing': ['artifact_fingerprint','approved_scope_hash','directive_revision']}
```
绑定字段齐全的手工卡片（探针直接 `agent_room.create_approval` 创建，非生产入口）可以 200 resolve，说明严格校验本身没写错，是**契约没有生产者/客户端**。

**影响**
C-13 的“评估失败 → 人工裁决”链路仍未闭环；审批列表生产为空，旧调用方（只带 `approved`/`note`）稳定 400；严格绑定无法端到端验证。

**最小修复**
二选一：
1. 在 `evaluate` 路由注入真实 evaluator，并在失败时创建卡片；同时加审批 UI/API 创建入口；
2. 明确把审批标记为 API-only，`resolve` 对“卡片带绑定字段但调用方没回传”的情况降级，或保留严格模式但文档说明旧客户端必须升级。

**复现**：同上探针，输出见 §5。

---

### 1.3 X-P2-5（REPRODUCED）`agent_hub` 仍把 running 改 held，测试固化矛盾

**位置**
- `backend/integration/agent_hub.py:352-360`：`UPDATE agent_tasks SET status='held' ... WHERE status IN ('running','waiting','held')`
- `backend/integration/agent_hub.py:436-444`：evaluate 默认把 held 任务放回 `pending`。
- `backend/manager/test_v085_api.py:186`：仍断言 running → amend → `held`。
- 对照 `backend/integration/concurrent_engine.py:491-525`：C-08 已改为 running 只置 `hold_requested`，不直接改 held。

**实测**
```
amend: 200 ... held_task_ids: [tsk_...]
task-after-amend: held
evaluate: 200 ... wait_and_redo: [tsk_...]
task-after-evaluate: pending
```
即一次改令把运行中任务直接置 held，评估后再回 pending 重跑；`agent_hub` 的状态机与 `concurrent_engine` 的协作式 hold 语义相反。

**影响**
若外部 worker 以 `status='running'` 作为写回/完成前置条件，改令后写回会失败；即使不失败，接近完成的任务也会被重跑，浪费模型费用/副作用。v0.8.5 没有 agent task 的 HTTP claim/complete 路由，当前生产 worker 影响有限，但契约已写反，测试还把矛盾固化为期望。

**最小修复**
`start_amendment` 对 running 只写 `hold_requested`/`wait_reason`（给 `agent_tasks` 加列或复用 wait_reason 的协作语义），不改 `status`；evaluate/release 按标志释放；同步改 `test_v085_api.py:186` 的期望。

**复现**：同上探针。

---

### 1.4 X-P2-6（REPRODUCED）standalone 工作台 SSE 无 chapter/draft 生产者

**位置**
- `backend/manager/static/workbench.js:961-974`：只对 `kind === "resync_required"` 或 kind 含 `chapter`/`draft` 的事件刷新列表。
- `backend/manager/api_v085.py:137-147`、`:228-242`：后端唯一 `agent_room.append_event` 生产路径是 chief messages，默认 `kind="message"`。
- `backend/integration/chapter_editor.py` / `api_v08.py` 保存章节/草稿时均不调用 `append_event`/broadcaster。

**实测**
```
room-events-before: []
room-events-after: []
chapter/draft-event-count: 0
```
即使 HTTP 创建章节并保存草稿成功，room 事件仍为空；`workbench.js` 没有 `setInterval`/轮询，其他窗口保存后列表不会刷新。

**影响**
D 域的“实时刷新”只对主编室消息之外的未来事件有效；当前实际不生效。DSH 面板另有轮询，掩盖了 standalone 工作台的问题。

**最小修复**
在章节保存/草稿保存/删除/拆分/合并/恢复成功后由后端产生 `chapter_saved`/`draft_updated` 事件（经 `agent_room.append_event` 或专用 broadcaster）；或恢复工作台轮询并删除这段无效 SSE 过滤。

**复现**：同上探针。

---

### 1.5 X-P2-1 部分修复：无 DB 已修，空 DB 仍 500（新编号 E-02）

见 §2.1。`GET /previews` 在**完全没有** `workbench.sqlite3` 时已返回 200/[]；但如果文件存在但没有 `preview_index` 表（旧 bug 留下的空库），仍 500。X-P2-1 只加了 `if not db_path.exists()`，没有检查 schema。

### 1.6 已确认修复的 X 项

- **X-P1-1**：干净树 `check-release --local` 通过（1188 文件，`buildId=c355fa1a...`）；`runtime-download.json.buildId` 同步。跑测试后的残留问题见 §5。
- **X-P1-2**：`world_state.py:585-591` 对 AI `raw` 做白名单，丢弃 `author_edit/pinned/author_locked/status/authority_level/fact_id`；`test_world_state` 覆盖。
- **X-P2-3**：`app.py:1318-1322` 已识别 `lock_manager.LockError`，`lock_busy` → 503 + `Retry-After`，其他 LockError 按 `exc.status`；不再统一 400 `request_failed`。

---

## 2. 新发现（本轮）

### 2.1 E-01 [P1] 发布状态读模型无生产者：已发布章节可被删除/合并/拆分

**位置**
- `backend/integration/chapter_editor.py:207-223`：`_published_state` 只从 `writer_receipts.json` 读 `published_sha256` / `publish.sha256` / `staged_at`。
- `backend/integration/chapter_editor.py:770`：`delete_chapter` 用 `published["status"]` 阻止删除。
- `backend/integration/chapter_editor.py:1087`：`_require_tail_unpublished` 用同一状态阻止 split。
- `backend/integration/chapter_editor.py:1279`：`merge_tail` 用同一状态阻止 merge。
- `backend/integration/bridge.py:439-548`：`stage_project` 只写队列 manifest/`staged` 返回值，不写 `writer_receipts.staged_at`。
- `backend/fanqie_auto_publish/publish.py:871-996`：发布成功只写 journal/report，不写 `writer_receipts.published_sha256`。
- `backend/integration/publishing.py:608-615`：新发布模块只写自己的 intent ledger `accepted`，也不写 `writer_receipts`。

**机制**
`_published_state` 读取的三个字段在**全部生产代码中没有写入者**：`grep -rn "published_sha256\|staged_at" backend --include='*.py' | grep -v test_` 只返回 `chapter_editor.py:216/217/221/602-604` 的读取；`staged_at` 同样只有读取。唯一的写入者是测试 `test_chapter_editor_adversarial.py:479-480` 的 `test_published_or_staged_fake_receipt_is_refused`（名字已经说明是“fake receipt”）。因此：

- 旧 `/api/publish` 真实发布成功、`bridge.stage_project` 入队成功，都不会让 `chapter_state.publication.status` 变成 `published`/`staged`；
- `chapter_state.publication` 永远是 `unpublished`，`published_diverged` 永远 false；
- `delete_chapter` / `split` / `merge_tail` 的“已发布只读”保护永远不触发。

**实测**
用新发布模块的 fake adapter 走完整 `publish/submit`（能力→绑定→授权→意图→适配器→回读），然后：
```
publish-submit-forged-body: 200 {'status':'accepted','writes_confirmed':1,...}
chapter-state-after-publish: {'status': 'unpublished', 'published_sha256': None, 'local_diverged': False}
publish-status-after-submit: ... 'ledger': [{'chapter':1,'state':'accepted',...}]
delete-after-accepted-publish: 200 {'status': 'deleted', ... 'trash_entry': ...}
publish-status-after-delete: {'ledger': [{'chapter':1,'state':'accepted',...}], 'corrupt_ledgers': 0}
```
即“发布账本已 accepted”，但章节状态仍 unpublished，随后 `DELETE /chapters/1` 成功。旧发布路径没有 fake adapter 的便利，但静态证据同样显示它不写 receipts（这也是 v0.7.5 真实队列路径）。

**影响**
- 作者在工作台看到的“未发布/已入队”状态永远错误；编辑已发布章节不会出现 `published_diverged` 警告。
- 已发布章节可被删除、与下一章合并或拆分；本地正文会进回收站（不是永久删除），但平台侧仍是旧章节，形成静默的平台/本地分叉。这是“发布后只读”不变量的直接破坏。
- 新发布模块的 accepted ledger 与章节状态是两套事实源，`publishing.status` 与 `chapter_state.publication` 对同一章给出相反结论。

**最小修复**
二选一（推荐同时做读侧兼容）：
1. 在 `bridge.stage_project` 成功、legacy `run_publish` 确认成功、`publishing.submit_chapter` accepted、`browser_target.publish_once` accepted 后，把 `staged_at`/`published_sha256`（以及平台/账号/receipt）写回对应章节的 `writer_receipts`；
2. 或让 `_published_state` 聚合 `.webnovel/publish/<platform>/.../intents`、`.webnovel/browser/publish_ledger` 与队列 manifest，不再只信 `writer_receipts`。

并增加“真实 stage/publish 账本 → delete/split/merge 被 409 拒绝”的集成测试，替代 fake receipt 测试。

**复现**：`tmp-e/probe_e.py`，关键输出见上。

---

### 2.2 E-02 [P2] 空 `workbench.sqlite3` 仍让 `/previews` 500（X-P2-1 修不完整）

**位置**
- `backend/integration/annotations.py:664-678`：`list_previews` 只判断 `wb.db_path(project).exists()`，然后直接 `wb.connect` + `SELECT * FROM preview_index`。
- `backend/manager/api_v08.py:157-166`：`chapter_previews` 无条件调用 `annotations.list_previews`。
- `backend/manager/api_v085.py:95-98`：`annotation_previews` 同样直接调用。
- `backend/integration/workbench_db.py:117-138`：`connect` 只建连接，不建表。

**机制**
空文件存在时，X-P2-1 的 `if not db_path.exists()` 不成立；`connect` 打开空库，`preview_index` 不存在 → `sqlite3.OperationalError` → app 兜底 500 `internal_error`。这正好是旧 P2-1 bug 留下的现场：旧代码在第一次读时创建过空库，升级后这些用户仍会 500。

**实测**
```
previews/no-db: 200 {'chapter_id': 1, 'previews': [], 'count': 0}
previews/empty-db: 500 {'code': 'internal_error', 'message': '服务内部错误：no such table: preview_index'}
previews/empty-db-tables: []
annotation-previews/empty-db: 500 {'code': 'internal_error', 'message': '服务内部错误：no such table: preview_index'}
```

**影响**
旧书/曾触发过 P2-1 的项目，`GET /chapters/{n}/previews` 与 `GET /annotations/previews` 仍然 500；读请求不建表，也不会自愈。

**最小修复**
在 `list_previews` 里先查 `sqlite_master` 是否存在 `preview_index`；不存在直接返回 `{previews: [], count: 0}`（不要为读建库）。或调用 `wb._ensure` 前先判断 schema，但需保持“读不建库”的 C-30 约束。`api_v085.annotation_previews` 复用同一修复。

**复现**：同上探针。

---

### 2.3 E-03 [P2] `publish/submit` 的正文不绑定当前版本/审查回执；与 legacy 发布门禁语义相反

**位置**
- `backend/manager/app.py:1811-1818`：`publish_submit` 直接把请求体的 `title/body` 传给 `publishing.submit_chapter`。
- `backend/integration/publishing.py:543-568`：只校验能力、adapter、binding、chapter 级 authorization，然后 `format_chapter(chapter,title,body)`；不读取 `chapter_versions`，不检查 `writer_receipts`/`publication_safety.review_eligible`。
- 对照 `backend/integration/bridge.py:734-741`：legacy `validate_queue_origin` 要求 `review_eligible(...)`、receipt destination/sha 与源文件一致、`qualification_contract_matches(...)`。

**机制**
新“第三层受控提交”的信任边界是“chapter 级授权”，不是“正文内容 = 当前已审查版本”。任何客户端（或被旧页面缓存的编辑器内容）都可以提交任意 body；ledger 只按格式化后的 body sha 去重，不证明该 body 来自版本层。`publish/export` 同样接受任意 body（只写本地导出，不写平台）。

**实测**
项目磁盘正文是 `第一章正文。`，版本 id 为 `ver_0001_...`；用 fake adapter 注册后提交：
```
chapter-disk-before-publish: 第一章正文。
publish-submit-forged-body: 200 {'status':'accepted','writes_confirmed':1,...}
publish-adapter-received: 第1章 第一章

这是一段从未进入版本层、也从未被审查的正文。
```
即 adapter 收到的 body 与当前版本完全不同，仍 accepted。

**影响**
- 当前 `publishing.current_adapter` 在**生产代码中没有注册点**（`grep -rn register_adapter backend --include='*.py' | grep -v test` 只返回定义），所以线上默认返回 `unavailable`，不是当前可实际写入的 P1；
- 一旦接入真实平台 adapter，这条路径会绕过 legacy 的“审查回执 + 版本 + 创作约定”门禁，成为真实发布绕过；属于高风险的潜伏契约。
- 产品上需要明确：第三层是“作者手工直发”还是“已审查版本发布”。当前文档/UI把 body 当自由文本，和 legacy 门禁的承诺冲突。

**最小修复**
- 要求 `version_id`（或 `chapter_uid`+`content_sha256`），服务端从 `chapter_versions.read_version` 取正文，禁止请求体直接提供 body；或
- 保留手工 body，但强制调用 `publication_safety.review_eligible` 校验该格式化 body 对应的回执，并要求 `manual_override` 显式标记；`publish/export` 同样标注“未绑定版本”。

**复现**：同上探针（fake adapter 仅用于验证路由契约，不声称生产可用）。

---

### 2.4 E-04 [P2] `chapter_state.reviewed` 编辑后仍为 true；客户端显示“已审查”，实际发布门禁为 false

**位置**
- `backend/integration/chapter_editor.py:226-255`：`_review_state` 只看 `review.success`/`review.review_decision`，不比较 `review.body_sha256` 与当前正文。
- `backend/integration/chapter_editor.py:486-615`：`save_version` 提交新正文后没有清除/失效 `writer_receipts.review`。
- `client.js:13371`：章节弹窗用 `data.reviewed` 显示绿色“已审查”徽章。
- `backend/fanqie_auto_publish/publication_safety.py:310-327`：真实发布门禁对 `pass`/`human_approved` 都要求 `body_sha256` 与当前正文一致。

**机制**
`_review_state.reviewed = review.success && review_decision == "pass"`，没有绑定当前正文；`save_version`（作者编辑）不会清 review 回执，只写新版本并触发 invalidation。于是回执仍是旧正文的 pass，`GET /chapters/{id}` 仍报告 reviewed=true / review_status=pass，而 `publication_safety.review_eligible` 对当前正文返回 false。

**实测**（用与 `writer_runner` 同结构的 pass 回执，随后作者保存新正文）
```
review-stale/chapter-state: {'reviewed': True, 'review_status': 'pass',
                             'publish_eligible': False, 'stale': False}
review-stale/gate: False
```
`client.js` 的章节详情因此会显示“已审查”，但实际发布会被 `review_eligible` 拒绝。

**影响**
作者/API 消费者误以为改稿后仍具备发布资格；真正的门禁在 publish 时才失败，错误反馈滞后。`publish_eligible` 对 `human_approved` 也恒为 false（只对 `author_confirmed` 计算），与 `publication_safety` 接受 `human_approved` 不一致。

**最小修复**
在 `_review_state` 计算 `current_digest = safety.body_digest(current_text)`，将 `reviewed` 改为 `review.body_sha256 == current_digest && ...`；增加 `review_stale` 字段。`publish_eligible` 对任何 decision 调用 `publication_safety.review_eligible(review, current_digest, project, chapter)`；或在 `save_version` 时把旧 review 标为 stale（保留历史证据，不物理删除）。

**复现**：同上探针。

---

### 2.5 E-05 [P2] 版本层错误码未映射：缺失版本/损坏索引返回 400 `request_failed`

**位置**
- `backend/integration/chapter_versions.py:66-79`：`VersionError`/`VersionConflict`/`VersionNotFound`/`VersionCorrupt`，后者不是前两者的子类。
- `backend/manager/api_v08.py:36-63`：guard 只捕获 `VersionConflict`/`VersionNotFound`，不捕获 `VersionCorrupt`。
- `backend/manager/app.py:2108-2127`：`/versions`、`/versions/{version}`、`/restore` 路由直接调用 `version_history`，没有版本异常处理。
- `backend/manager/app.py:1310-1327`：通用 `RuntimeError` handler 固定 400 `request_failed`。

**实测**
```
missing-version/get: 400 {'code': 'request_failed', 'message': 'version_not_found'}
corrupt-index/chapter: 400 {'code': 'request_failed', 'message': 'index_schema_unsupported'}
corrupt-index/versions: 400 {'code': 'request_failed', 'message': 'index_schema_unsupported'}
```
`GET /chapters/{n}/versions/ver_9999_deadbeef` 应是 404 `version_not_found`，却变成 400 且 code 丢失；损坏 `index.json` 是服务端状态问题，应至少 409/500 稳定码，却返回 400 并暴露内部 `index_schema_unsupported`。`api_v085` 的 annotations 路径也会经 `versions.current_version` 触发 `VersionCorrupt`，同样落到 400。

**影响**
客户端无法区分“版本不存在”和“请求格式错误”；损坏索引被误报为客户端错误，排障/重试策略错误；内部 schema 字符串泄露给调用方。

**最小修复**
在 `app.py` 注册 `chapter_versions.VersionError` 处理器：`VersionNotFound` → 404 `version_not_found`，`VersionConflict` → 409 + 具体 code，`VersionCorrupt` → 500 `version_store_corrupt`（只记日志，不返回内部路径/字符串）；或在 `api_v08`/`api_v085` guard 中补齐并让版本路由统一使用。

**复现**：同上探针。

---

## 3. 发布清单 / 路由 / 权限核对

### 3.1 `check-release --local`（通过）

```text
$ cd head-e && node scripts/check-release.mjs --local
发行清单校验通过：1188 个文件与清单一致，
buildId=c355fa1adf506f530484758c49bbf862330a237631db2a32c988124351c1f47b
```

- `runtime-manifest.json`：3441 项（backend 1188 + runtime 2253），`packageVersion=0.7.5`，`version=0.7.0`（复用 v0.7.0 runtime）。
- `runtime-download.json`：`buildId` 与清单一致；`runtimeAssetBuildId=b181...` 与 CHANGELOG 的 0.7.0/0.7.1 runtime 一致；`managed-runtime.downloadRuntime` 只复用匹配的 runtime 文件，不混用 backend。
- **manifest 覆盖**：实际 production backend 1188 个文件全部在清单；未覆盖的 96 个是 95 个 `test_*.py` + `backend/.npmignore`（构建脚本按设计排除）。未发现漏掉的 production 模块。
- **根入口缺口是已知设计**：`client.js`/`index.js`/`managed-runtime.mjs`/`deploy/`/`assets/` 不在 runtime manifest，`RELEASE_STATUS.md:15-16` 明确说明由 npm/客户端契约测试覆盖；不重复计为 drift。

### 3.2 `WRITE_ROUTES` 与生产写路由

用脚本解析 `app.py/api_v08/api_v085/api_v09/provider_api/device_access/free_model_api` 的 160 条非 GET 生产路由，与 `index.js` 的 180 条白名单比对：

```text
files 7 non-get 160 missing 1
('POST', '/internal/events/notify', 'backend/manager/app.py')
```

- 唯一缺失是 `/internal/events/notify`；该路由不在 `/api` 命名空间，`index.js parseTarget`/`allowsMutation` 不会代理它，且它自身要求 `x-internal-token`，不是提权路径。
- 其余 159 条全部覆盖；新增的 publish/directive/approval/world/tasks 路由均在白名单。Node `gate.test.mjs` 174 项通过（防漂移测试也通过）。

### 3.3 `/internal/*` 权限

- `app.py:1253-1267` 的 `/internal/events/notify` 跳过 `X-Novel-Helper` 与 Origin 校验，只靠 `CHAPTER_WHALE_INTERNAL_TOKEN`；无 token 返回 403（探针验证），有 token 返回 200。
- 但全仓只有 `app.py` 读取该 env、`test_v09_api.py` 注入；**没有任何生产启动脚本设置它**，也没有 `LoopbackNotifier` 的生产调用方；`EventFanout` 只有该路由 publish，没有 subscribe。因此该唤醒路径实际不可用（fail-closed，不是安全洞）。
- 结论：权限本身“只有 token 才能写”，没有匿名提权；问题是未接线/死代码（见 E-08）。

### 3.4 生成管线版本层（通过）

- `writer_runner.py:1254` 生成正文改走 `chapter_versions.commit_raw_bytes`，在 `chapter_editor._locked` 章锁内提交，回执在提交成功后写；旧的 `os.link` 直写路径已不存在（只剩注释）。
- `studio.polish_existing` 在 `studio.py:536` 走 `commit_raw_bytes`；`chapter_editor.save_version` 走 `write_chapter`；`new_chapter`/`import_chapters`/`split`/`merge`/`restore_trash` 均走 `commit_raw_bytes`/`write_chapter`；`revision_plan.accept` 走 `commit_candidate`。
- 未发现新的生成路径直接写 `正文/`。`bridge.stage_project` 只写队列文件，不是正文本体。

---

## 4. 新发现的 P3

### 4.1 E-06 [P3] `build-runtime --manifest-only` 默认把 runtime 版本从 0.7.0 改成 0.7.5，导致 `runtime-download` URL 失配

**位置**
- `scripts/build-runtime.py:49-69`：`previous.update(version=runtime_version or package_version, ...)`。
- `scripts/build-runtime.py:112-119`：`--manifest-only` 直接 `write_manifest(args.runtime_version)`，`--runtime-version` 默认 None。
- `scripts/check-release.mjs:165-176`：`runtimeVersion = manifest.version`，URL 必须匹配 `v<runtimeVersion>/...0.7.0.tgz`。

**机制**
当前清单 `version=0.7.0`、`packageVersion=0.7.5`。按 X 报告/常见命令只跑 `python3 scripts/build-runtime.py --manifest-only`，`version` 被改成 `0.7.5`，而 `runtime-download.json.url` 仍指向 `v0.7.0/...0.7.0.tgz`；`check-release` 会报“URL 与版本不符”。必须额外传 `--runtime-version 0.7.0` 才保持复用。

**实测**（临时目录模拟，不改仓库）
```
manifest.version = 0.7.5
manifest.packageVersion = 0.7.5
runtime-download expected URL = v0.7.5/...
existing runtime-download URL  = .../v0.7.0/dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz
```

**影响**
发布维护者按文档重建清单时容易把 runtime 版本号写错，门禁红或误发一个指向不存在 v0.7.5 runtime 的下载描述。

**最小修复**
`runtime_version = runtime_version or previous.get("version") or package_version`；或 `--manifest-only` 强制要求显式 `--runtime-version`，并在 `check-release` 中同时校验 `runtime-download.url` 与 `runtimeAssetBuildId` 的对应关系。

**复现**：临时目录模拟输出见 `tmp-e/build-runtime-sim.log`（未改仓库）。

### 4.2 E-07 [P3] `RELEASE_STATUS.md` 与当前树不一致

**位置**：`RELEASE_STATUS.md:7-16`。

**证据**
- 文档 `1168` 文件 / `buildId=9f1cc349...` / Node 125 项 / integration 828 / manager 187 / 完整包 3421。
- 当前树：`check-release` **1188** 文件 / `buildId=c355fa1a...`；Node 174；integration 1208；manager 222；清单总数 3441。
- `docs/remediation/v0.8-v0.9.5-remediation-v2.md:69-71` 已记录当前 `1188/c355fa1a...`，说明 `RELEASE_STATUS` 停留在上一轮验收。

**影响**
若把该文件当作当前候选包的发布记录，会引用错误的 buildId/测试计数；若它只描述已发布的 0.7.5，则需明确标注“不适用于当前分支”。当前两种解读都没有标注，属于发布文档漂移。

**最小修复**
在最终冻结后重新生成 `RELEASE_STATUS` 的 buildId/计数，或在文件头标注“仅适用于已发布 0.7.5，当前 v0.8–v0.9.5 候选见 remediation v2”。

### 4.3 E-08 [P3] `/internal/events/notify` 未接线：令牌无生产赋值、fanout 无订阅者

**位置**：`app.py:1253-1267`；`concurrent_engine.py:612-646`（`EventFanout`）；`concurrent_engine.py:575-595`（`LoopbackNotifier`）。

**证据**
- `grep -rn "CHAPTER_WHALE_INTERNAL_TOKEN" .` 仅 `app.py` 读取 + `test_v09_api.py` 注入，无生产赋值。
- `grep -rn "LoopbackNotifier" backend --include='*.py' | grep -v test` 只有定义，无调用。
- 探针：无 token 403；带 token 200 `{'ok': True, 'subscribers_dropped': 0}`，说明 publish 没有订阅者。
**影响**：C-47 的“唤醒路径”形式上存在、实际不可用；不是权限漏洞（fail-closed），但属于未映射的运维契约。
**最小修复**：启动脚本注入随机内部 token 并与 worker 共享；把 `EventFanout` 接到实际 SSE/唤醒消费者，或删除路由/fanout 并文档标注。

### 4.4 E-09 [P3] `chief_room_state` 同时传 `project_id` 与 `session_id` 时丢弃 session

**位置**：`api_v085.py:126-135`。
**实测**：`GET /api/chief/room/state?project_id=X&session_id=A` 返回 `sessions=['A','B']`，session 参数被静默忽略。
**影响**：API 契约歧义；当前无前端同时传两者，但自动化/多 session 客户端会拿到过多事件。
**最小修复**：始终把 `session_id` 传给 `snapshot`（它已支持 project+session 联合过滤），或同时传两者时返回 400。

### 4.5 E-10 [P3][HYPOTHESIS] quality 分页只改后端，standalone 工作台仍取默认 200

**位置**：`api_v09.py:299-310` 支持 `limit/offset`；`quality.py:181-236` 的 `averages`/`reviewed` 只统计当前窗口；`workbench.js:3446` 调用 `/quality/dashboard` 不带参数。
**状态**：静态证据，未构造 205 章项目实跑（标注 HYPOTHESIS）。影响 205 章以上的书只显示前 200 章、KPI 页面不一致；修复为前端传 `limit/offset` 或显示“仅前 200 章”，并把 `averages/reviewed` 改为全书聚合。

---

## 5. 验证记录

### 5.1 发布门禁

```text
$ node scripts/check-release.mjs --local
发行清单校验通过：1188 个文件与清单一致，buildId=c355fa1adf506f530484758c49bbf862330a237631db2a32c988124351c1f47b
EXIT=0
```

跑完全量 Python 测试后再跑门禁（测试残留，非代码失败）：
```text
$ node scripts/check-release.mjs --local --json tmp-e/check-release.json
后端包混入本地状态：backend/integration_data
发行清单校验失败：1 项（已检查 1188 个文件，跳过 2253 个缺席 runtime 项）
$ rm -rf backend/integration_data && node scripts/check-release.mjs --local
发行清单校验通过：1188 个文件...
```
这是测试隔离问题（A-D 域既有残留），不是清单哈希漂移；CI 的 `ci.yml` 把门禁放在测试之前，故 CI 不会红。开发者本地跑完测试后发布需先清理。

### 5.2 全量测试

```text
# integration
Ran 1208 tests in 79.920s
OK (skipped=9)

# manager
Ran 222 tests in 123.593s
OK

# Node
ℹ tests 174
ℹ pass 158
ℹ fail 0
ℹ skipped 16
```

### 5.3 探针

脚本：`/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-e/probe_e.py`
日志：`/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-e/probe_e.log`
环境：`PYTHONPATH=backend /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ...`
探针只使用 `tmp-e/probe-e-*` 临时项目；末尾创建的 `backend/integration_data` 已清理。

关键输出（节选）：
```text
previews/no-db: 200 {'chapter_id': 1, 'previews': [], 'count': 0}
previews/empty-db: 500 {'code': 'internal_error', 'message': '服务内部错误：no such table: preview_index'}
previews/empty-db-tables: []

global-resume: 200 {'status': 'resumed', ...}
project-paused-after-resume: True
ops.start-after-global-resume: 409 {'code': 'conflict', 'message': '该作品已暂停自动化，请恢复后再执行'}

task-after-amend: held
task-after-evaluate: pending
approvals-after-evaluate: {'approvals': []}
directive-status-after-evaluate: amended

approval-legacy-body: 400 {'code': 'approval_binding_required', 'missing': [...]}
approval-bound-body: 200 {'status': 'approved', ...}

room-events-before: []
room-events-after: []
chapter/draft-event-count: 0

review-stale/chapter-state: {'reviewed': True, 'review_status': 'pass',
                             'publish_eligible': False, 'stale': False}
review-stale/gate: False

missing-version/get: 400 {'code': 'request_failed', 'message': 'version_not_found'}
corrupt-index/chapter: 400 {'code': 'request_failed', 'message': 'index_schema_unsupported'}
corrupt-index/versions: 400 {'code': 'request_failed', 'message': 'index_schema_unsupported'}

publish-submit-forged-body: 200 {'status': 'accepted', 'writes_confirmed': 1, ...}
publish-adapter-received: 第1章 第一章

这是一段从未进入版本层、也从未被审查的正文。

chapter-state-after-publish: {'status': 'unpublished', 'published_sha256': None, 'local_diverged': False}
delete-after-accepted-publish: 200 {'status': 'deleted', ...}
publish-status-after-delete: {'ledger': [{'chapter': 1, 'state': 'accepted', ...}], ...}

chief-room-state-both-params: 200 sessions=['A', 'B']
internal-no-token: 403 {'code': 'forbidden', 'message': '内部令牌无效'}
internal-with-token: 200 {'ok': True, 'subscribers_dropped': 0}
```

### 5.4 清单覆盖 / 路由比对

```text
MISSING from manifest (96):
  backend/.npmignore
  backend/integration/test_*.py ... (95 个测试文件)
manifest backend 1188 / actual production 1188

WRITE_ROUTES missing: 1
  POST /internal/events/notify
```

---

## 6. 未复现 / 边界

1. **真实平台写入未执行**：`publishing.current_adapter` 与 `browser_target.current()` 在生产代码中均无注册点；E-03 使用 fake adapter 验证路由契约，不声称真实平台已可写。接入真实 adapter 后 E-03 会升级为 P1。
2. **legacy `/api/publish` 未跑真实账号**：E-01 的 legacy 不写 `writer_receipts` 是静态证据（`grep` 无写入者、`publish.py` 只写 journal/report）；未用真实番茄账号复跑。
3. **E-10** 未构造 205 章项目实跑，标 HYPOTHESIS。
4. **E-07** 的“过期”判断取决于 `RELEASE_STATUS.md` 是否被当作当前分支记录；若只描述已发布 0.7.5，应加适用范围标注。
5. 未修改仓库 tracked 文件、未 commit、未联网；测试产生的 `backend/integration_data`/`__pycache__` 已清理。

---

## 7. 最终判定

当前工作树**干净状态下可通过发布门禁**：`check-release --local` 1188 文件与 `buildId=c355fa1a...` 一致，`runtime-download` 同步，manifest 覆盖全部 production backend 文件，WRITE_ROUTES 无新增漏配，生成主路径已全部走版本层。

但跨域仍有必须处理的问题：

1. **E-01（P1）**：发布状态读模型没有生产者，已发布章节的只读保护实际失效；这是发布/编辑之间最严重的契约断裂，应优先修。
2. **X-P2-2/P2-4/P2-5/P2-6**：四个 X 残余均独立复现，不是“报告误报”；其中 P2-2/P2-6 是 API/前端用户可见行为，P2-4/P2-5 是链路未闭环。
3. **E-02/E-03/E-04/E-05**：空库 500、第三层发布未绑定版本/审查、reviewed 状态失真、版本错误码未映射，都是本轮新发现的跨层矛盾。
4. **P3**：发布工具默认值、`RELEASE_STATUS`、`/internal` 未接线、session 过滤、quality 分页仍是残余问题，不阻塞当前干净门禁，但应在发布前清理。
