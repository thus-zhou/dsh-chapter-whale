# v0.9 平台层独立审计报告（C 部分：锁 / 并发 / 世界状态 / 质量 / 维护 / API / 代理 / SSE）

- 审计对象：`/home/ubuntu/.hermes/cache/scratch/audit-v2-head`，detached HEAD **5e8a2d0**
- 审计时间：2026-11-27
- 运行环境：`/home/ubuntu/venvs/dsh/bin/python3`（Python 3.12.3，SQLite 3.45.1），所有命令均在仓库外执行，仅只读访问仓库
- 方法：逐行读代码 + 在 `/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-c-platform/` 构造最小项目/房间库/HTTP 应用实际复现；不引用 `docs/audits` 旧结论
- 既有测试基线：`integration.test_world_state test_quality test_concurrent_engine test_v09_maintenance test_v09_quality test_audit_v095_regressions` 共 **55 项全部通过**——下述问题全部是现有测试未覆盖的回归/缺口

---

## 0. 结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| **P0** | **3** | 作者确认接口 100% 500；嵌套写事务自锁死（导入旧稿后 15–76 秒 500）；GC 删除仍在使用的批注基线快照 |
| **P1** | **12** | 锁模块零接线、租约/改令/全站暂停语义断裂、SSE 跨项目泄漏与补放丢事件、质量上限与新鲜度失效、改令死路、任意路径写、v0.9 未接入生成管线 |
| **P2** | **32** | 权威/去重/冲突边界、仪表盘截断与假阳性、API 默认值与输入校验、代理细节 |

**最严重 5 条**

1. **C-01** `world_state.confirm_fact` 被文件末尾同名函数覆盖，`POST /world/facts/{id}/confirm` 必定 `500`，且作者确认永远不会把 `ai_inferred` 提升为 `confirmed_prose`——「作者确认是唯一提升权威的路径」这一核心不变量整体失效。
2. **C-02** `quality.review()`、`world_state.add_exemption()`、`annotations.create_annotation(scope=chapter)` 在 `BEGIN IMMEDIATE` 写事务内调用 `wb.chapter_uid()`，后者另开连接再 `BEGIN IMMEDIATE` —— 同线程自锁死，15 秒（单次）/ 76 秒（5 次重试）后抛 `database is locked`；`import_chapters`（「导入旧稿」主路径）不建 `chapter_meta`，因此新导入的书立即命中。
3. **C-03** `collect_garbage` 把 `.webnovel/snapshots`、`.webnovel/revision_previews` 当作可回收目录；`artifact_refs` 在生产代码中**从未被写入**（`register_artifact` 零调用），因此批注基线快照与待审修订预览在 7 天后被物理删除，`apply-hunks/undo-apply/apply_preview` 直接 `snapshot_missing`/404。
4. **C-04** 八级锁序模块 `lock_manager.py` **零生产调用**，`sqlite_scope()` 也从未使用；真实写路径继续用裸 `file_lock` + 嵌套 `write_tx`，C-02 正是该保护缺失的直接后果。
5. **C-06** `recover()` 对过期租约只做「重新入队」，从不检查 `attempts`；一个每次都崩溃/超时的任务会被无限重跑（实测 8 轮 attempts=8 仍 `pending`），持续烧模型费用。

---

## 1. P0

### C-01 [P0] `confirm_fact` 双定义：确认接口 100% 500，权威提升链路整体失效

- **位置**：`backend/integration/world_state.py:214-224`（第一定义，带 `authority_level` 与 `status='pending_confirm'` 校验）、`backend/integration/world_state.py:559-560`（第二定义，覆盖前者）、`backend/integration/world_state.py:563-564`（`reject_fact` 同样被覆盖）；调用方 `backend/manager/api_v09.py:61-66`
- **机制**：Python 模块级后定义覆盖前定义。`api_v09.confirm_fact` 固定传 `authority_level=`，而运行时解析到的是第二定义 `confirm_fact(project, fact_id)`，直接 `TypeError: unexpected keyword argument`。即使不传该参数，第二定义也只是 `set_fact_status(..., "active")`，**不改 authority_level**，且不要求原状态为 `pending_confirm`。`reject_fact` 第二定义把状态写成 `superseded` 而非 `archived`，同样丢失 `pending_confirm` 前置校验——任何 `active` 事实都能被静默「否决」。
- **影响**：
  - 作者在 UI/Agent 侧点击「确认」永远 500，`pending_confirm` 事实只增不减；
  - 所有 AI 提取事实永远停留 `ai_inferred`，`build_context` 的 L2 只收 `pinned / author_locked / confirmed_prose / published_prose`，因此**自动提取的事实永远进不了长期记忆层**；
  - 500 响应把 Python 异常文本原样返回给客户端（`app.py:1306-1308` 的 `redact(str(exc))`），泄露内部函数签名。
- **最小修复**：删除 559-564 的第二定义（或合并为一个带 `authority_level` 的实现），保留 214-233 的校验语义；`reject_fact` 恢复 `status='archived'` 与 `pending_confirm` 前置条件；补一条「确认后 authority 必须提升」的测试。
- **复现**：
  ```
  cd .../tmp-c-platform && PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
  PYTHONPATH=.../audit-v2-head/backend python3 -B -X utf8 t1_world.py
  ```
  实际输出：
  ```
  pending fact authority: ai_inferred pending_confirm
  CONFIRM RAISED: TypeError confirm_fact() got an unexpected keyword argument 'authority_level'
  confirm(no kw) -> ai_inferred active
  reject(active) -> superseded (first def would raise fact_not_pending)
  ```
  真实 FastAPI 应用（`create_app`，临时 `NOVEL_HELPER_ROOT`）：
  ```
  CONFIRM: 500 {"code":"internal_error","message":"服务内部错误：confirm_fact() got an unexpected keyword argument 'authority_level'"}
  CONFIRM2: 500 {"code":"internal_error","message":"服务内部错误：confirm_fact() got an unexpected keyword argument 'authority_level'"}
  ```
  现有 `test_world_state.py:142` 只断言 `status == "active"`，恰好被弱化后的第二定义满足，测试因此长期为绿。

### C-02 [P0] 写事务内嵌套 `write_tx`：同线程自锁死，15–76 秒后 500

- **位置**：
  - `backend/integration/quality.py:126`（`with wb.write_tx`）→ `quality.py:136`（`wb.chapter_uid(project, chapter)`）
  - `backend/integration/world_state.py:615`（`with wb.write_tx`）→ `world_state.py:619`（`wb.chapter_uid(...)`）
  - `backend/integration/annotations.py:177` → `annotations.py:183`；同文件 `509`、`524`、`665`
  - 根因实现：`backend/integration/workbench_db.py:100-131`（每次 `write_tx` 新开连接并 `BEGIN IMMEDIATE`）、`workbench_db.py:511-521`（`ensure_chapter_meta` 在无行时再开 `write_tx`）
- **机制**：`write_tx` 用 `BEGIN IMMEDIATE` 拿写锁；`chapter_uid()` 发现 `chapter_meta` 无该章行时，用**另一条连接**再 `BEGIN IMMEDIATE`。SQLite 不会识别同进程同线程的重入，第二条连接等 `busy_timeout=15000ms` 超时；`write_tx` 外层还有 5 次 jitter 重试，合计约 76 秒，最后抛 `sqlite3.OperationalError: database is locked`。`chapter_meta` 只由 `new_chapter`/部分草稿路径创建，而 **`import_chapters` 走的是 `versions.commit_raw_bytes`，全程不建 `chapter_meta`**（`chapter_editor.py:896-926`；实测导入 2 章后 `chapter_meta rows: []`）。因此不仅是升级旧书，**任何通过「导入旧稿」创建的书在第一次质量体检/豁免/整章批注时都会命中**。
- **影响**：质量体检、书级改令豁免、整章批注三条作者可见链路对新导入的书与旧项目直接 500（前端表现为 76 秒转圈后「服务内部错误」）；同一写事务已持有写锁，期间所有其他写请求排队，放大为全站卡顿。
- **最小修复**：把 `chapter_uid` 的计算移到 `write_tx` **之前**（`build_context` 的 441 行已经这么写），或在 `write_tx` 内改用线程本地 depth + `SAVEPOINT` 实现可重入，并在 `write_tx` 入口 `assert not lock_manager.sqlite_scope()` 之类的守卫（该守卫当前存在但无人调用，见 C-04）。
- **复现**：
  ```
  ... python3 -B -X utf8 t15_nested.py
  add_exemption -> OperationalError: database is locked (15.0s)
  review -> OperationalError: database is locked (75.9s)
  after priming chapter_meta:
   add_exemption: exempted
   review: reviewed
  ```
  ```
  ... python3 -B -X utf8 t35_annot_nested.py
  create_annotation(scope=chapter, legacy chapter) -> OperationalError: database is locked (76.0s)
  ```
  标准「导入旧稿」路径（`t36b_import.py`）：
  ```
  imported: 2 map: {1: '第1章-开端.md', 2: '第2章-继续.md'}
  chapter_meta rows: []
  review on imported chapter -> OperationalError: database is locked (76.0s)
  ```
  静态扫描（`nested_scan.py`）确认 6 处「`with wb.write_tx` 内调用会再开 write_tx 的函数」：
  `annotations.py:183/509/524/665`、`quality.py:136`、`world_state.py:619`。

### C-03 [P0] GC 删除仍在使用的批注基线快照与待审修订预览（不可逆数据丢失）

- **位置**：`backend/integration/maintenance.py:21`（`_PREVIEW_DIRS` 含 `snapshots`、`revision_previews`）、`maintenance.py:38-58`（保护面只有 `正文`、`chapter_versions`、`drafts`、`trash`、`artifact_refs`）、`maintenance.py:74-81`（候选文件枚举）、`maintenance.py:85-111`（删除）；快照写入/读取：`annotations.py:50-80`、`annotations.py:154/172`；修订预览：`revision_plan.py:284-332`
- **机制**：`_protected_paths` 只信任 `artifact_refs`（`ref_count>0` 或 `protected=1`）与固定目录；但 `register_artifact` 在**生产代码中零调用**（全仓仅 `test_audit_v095_regressions.py:96` 使用），`artifact_refs` 永远为空（API `/ledger` 实测 `artifacts: {count:0}`）。`annotations.save_snapshot` 把基线写到 `.webnovel/snapshots/<sha>.txt` 并在 `annotations.base_snapshot_id`/`preview_index.base_snapshot_id` 里引用，却从不登记 artifact。GC 把这些文件当「无引用预览」在超过 `min_age_seconds`（API 下限 1 天，默认 7 天）后删除。
- **影响**：`apply_hunks`、`undo_apply`、`run_annotations`、`revision/accept` 在读取基线时抛 `snapshot_missing`（404）——作者已写好的批注/修订证据无法应用或撤销；`revision_previews/*.json` 被删后待审预览直接从列表消失，且不可重建。模块 docstring 明言「绝不碰…批注证据」，实际行为相反。
- **最小修复**：把 `snapshots`、`revision_previews` 从 `_PREVIEW_DIRS` 移出；GC 只删「在 `annotations`/`preview_index`/`revision_plan` 中无引用且超过保留期」的对象；在 `save_snapshot`/`save_preview` 时调用 `register_artifact(..., ref_count=1)`，或直接按 SQLite 引用表计算保护集。
- **复现**：
  ```
  ... python3 -B -X utf8 t10_gc.py
  snapshot files: ['8cdfbf47...txt'] sizes: [26]
  GC would remove: ['.webnovel/snapshots/8cdfbf47...txt']
  GC removed: 1
  snapshots after GC: []
  read_snapshot -> AnnotationError snapshot_missing
  ```
  走真实 HTTP（`t20_realapp2.py`）：
  ```
  gc dry: 200 1 ['8cdfbf47...txt']
  gc real: 200 1 snapshot exists: False
  ```

---

## 2. P1

### C-04 [P1] 八级锁序模块零接线，`sqlite_scope` 从未使用

- **位置**：`backend/integration/lock_manager.py:1-153`；引用搜索：全仓除 `integration/test_lock_manager.py` 外**无任何 import/调用**；`backend/integration/workbench_db.py:100-131` 的写事务无任何锁序守卫
- **机制**：`hold/ordered/sqlite_scope/held_levels` 是完整的锁序实现，但没有任何生产模块调用；真实代码用 `writer_runner.file_lock` / `publication_safety.file_lock` 直接加锁，且 `write_tx` 可以在已持文件锁时打开（模块文档第 2 条明令禁止「SQLite 写事务打开期间申请 OS 文件锁」）。`lock_manager` 自带的 `SqliteNestingError` 守卫没有任何调用点，因此 C-02 这类嵌套写事务不会被拦截。
- **影响**：`docs`/docstring 宣称的「三期并发地基」不成立；锁序、死锁预防、SQLite 嵌套检测全部是纸面能力。任何跨模块并发写入只能靠 `busy_timeout` 兜底。
- **最小修复**：要么把 `hold()` 接进 `chapter_editor`/`annotations`/`publishing` 的写入口并统一锁文件命名，要么删除该模块与相关宣称；无论哪条路，先在 `wb.write_tx` 内调用 `lock_manager.note_sqlite_enter/exit`（或 `sqlite_scope`），让嵌套检测真正生效。
- **复现**：
  ```
  grep -rn "lock_manager" --include=*.py backend | grep -v test
  （无输出）
  ```
  模块自身不变量（顺序、SQLite 嵌套）在单测/手工验证中是通过的：
  ```
  reverse order -> LockOrderError lock_order_violation {'held': 6, 'requested': 4}
  sqlite nesting -> SqliteNestingError os_lock_inside_sqlite_tx
  ```
  说明「实现存在且正确，只是没人用」。

### C-05 [P1] `lock_manager.hold` 把调用者抛出的 `PublicationBlocked` 当成锁竞争，转成 `RuntimeError`

- **位置**：`backend/integration/lock_manager.py:91-103`
- **机制**：`try: with safety.file_lock(path): ... yield path ... except safety.PublicationBlocked:` 把整个 `with`（含 `yield` 之后的调用者代码）包在 except 里。调用者在锁内再取另一把文件锁失败（`publication_safety` 的 `file_lock` 就是抛 `PublicationBlocked("resource_busy")`），会被外层误判为「本锁忙」而重试；`contextlib` 检测到生成器在 `throw()` 后再次 `yield`，直接抛 `RuntimeError: generator didn't stop after throw()`。
- **影响**：真实的资源忙/写失败被替换成一个与业务无关的 `RuntimeError`，`app.py` 的通用 `RuntimeError` handler 返回 400 `request_failed`，而不是 503 `resource_busy`/409；排查时看不到原始错误码。
- **最小修复**：只把**获取锁**这一步包进 try（`cm = safety.file_lock(path); cm.__enter__()`），拿到锁后单独 `try/finally: cm.__exit__`，让 `yield` 体的异常原样穿透。
- **复现**：
  ```
  ... python3 -B -X utf8 t16_lock.py
  body ran 1 times, raised RuntimeError: generator didn't stop after throw() after 0.02s
  ```

### C-06 [P1] `recover()` 无 attempts 上限：崩溃任务无限重跑

- **位置**：`backend/integration/concurrent_engine.py:332-351`（`recover`）、`228-260`（`claim` 每次先 `recover`）、`315-329`（只有 `fail()` 会按 `max_attempts` 转 `failed`）
- **机制**：过期租约的非 committing 任务一律 `UPDATE ... state='pending'`，不看 `attempts`；而崩溃/被杀的 worker 永远不会调用 `fail()`。`claim()` 每次派发前调用 `recover()`，于是 `pending → running → 租约过期 → pending` 无限循环，`attempts` 单调增长但状态永不 `failed`。
- **影响**：一个每次都崩溃的生成/发布任务会无限重跑，按每次真实模型调用计费；若任务带副作用（发布、落盘）则反复执行。
- **最小修复**：`recover()` 中对 `attempts >= max_attempts` 的行置 `failed` 并写 `exhausted` 事件；`max_attempts` 作为项目/全局配置传入，而不是只在 `fail()` 里默认 3。
- **复现**：
  ```
  ... python3 -B -X utf8 t7b_recover.py
  cycle 1..8: claimed attempts=1..8 -> after recover state=pending
  final: {'state': 'pending', 'attempts': 8, 'lease_owner': None, 'lease_expires': None}
  events: ['submitted','claimed','lease_expired_requeued', ... ×8]
  ```

### C-07 [P1] 提交耗时超过 30 秒租约 → `recovery_required`，worker 既不能续租也不能完成

- **位置**：`backend/integration/concurrent_engine.py:279-287`（`begin_commit` 不延长租约）、`263-276`（`renew` 在 committing 时拒绝延长）、`290-295`（`_mark_recovery`）、`332-351`（`recover` 由任意 `claim` 触发）
- **机制**：`begin_commit` 只置 `committing=1`，`lease_expires` 保持 claim 时的 `now+30s`；`renew` 对 committing 任务直接返回 `{"status":"committing","renewed":false}`，不续期。任何其他 worker 调 `claim()` 都会先 `recover()`，看到「running + committing + 过期」→ `state='recovery_required'`。此后 `renew` 抛 `recovery_required`，`complete` 抛 `task_not_running`，`fail` 也因状态不是 running 而 409；唯一出口是 `retry`（重置 attempts 后从头重跑）。
- **影响**：大章节提交（备份 + fsync + Windows AV 扫描）超过 30 秒是常态；一旦发生，已完成的提交被标记为待对账，重试会重复执行提交（可能重复发布）。任务还会停留在 `recovery_required + committing=1` 的矛盾状态。
- **最小修复**：`begin_commit` 把租约延长到 `now + commit_grace`（如 300s）；`renew` 允许 committing 且 owner 匹配时续期；`recover` 对 committing 任务使用独立的 commit grace，而不是普通租约。
- **复现**：
  ```
  ... python3 -B -X utf8 t34_commit_lease.py
  claimed, lease in 30.0 s
  recover -> [('task_8fe4e370', 'recovery_required')]
  renew -> recovery_required
  complete -> task_not_running
  final state: recovery_required committing: True
  ```

### C-08 [P1] `hold_for_amendment` 冻结「运行中」任务：worker 完成时 409，释放后二次执行

- **位置**：`backend/integration/concurrent_engine.py:354-372`（`hold` 只排除 completed/cancelled/failed，running 也改 `held`）、`387-401`（release 改回 pending）、`298-312`（complete 要求 `state='running'`）
- **机制**：改令到达时把正在跑的任务直接改成 `held`，但不清 `lease_owner`/`lease_expires`，也不通知 worker。worker 的 `begin_commit` 只校验 owner（成功），`complete` 因 `state='held'` 抛 `task_not_running`；`release_amendment` 把任务改回 `pending`，随后被另一个 worker 再次 claim（attempts+1）从头执行。
- **影响**：一次改令会把「已接近完成」的任务作废并重跑，重复产生模型费用与副作用；worker 无法上报失败（`fail` 同样 409），只能等 release。
- **最小修复**：改令只挂起 `pending/held`；对 running 任务设置独立的 `hold_requested` 标志，由 owner 在检查点自行停止并 `fail/requeue`；`begin_commit` 增加 `state='running'` 校验。
- **复现**：
  ```
  ... python3 -B -X utf8 t8_amend.py
  running: running owner: worker-1 lease: 1795754002.34
  after amendment hold: held owner: worker-1
  begin_commit ok
  complete -> SchedulerError task_not_running
  after release: pending
  re-claimed by: worker-2 attempts: 2
  ```

### C-09 [P1] 「全站急停」不约束真正的自动化：只拦 v0.9 队列 claim，而队列没有消费者

- **位置**：`backend/manager/api_v09.py:226-240`（`/api/system/ai/pause`）；`backend/integration/concurrent_engine.py:141-149`（`global_paused`）、`165-182`（唯一使用点 `_task_paused`）；`backend/manager/app.py:1155-1175`（调度循环直接 `ops.start("daily", ...)`）、`app.py:203-210`（`Operations.start` 无暂停判断）
- **机制**：`global_paused()` 只被 `claim()` 的 `_task_paused` 调用；`dispatch()` 每 20 秒调用 `ops.resume_due()` 和 `scheduler.due_jobs` → `ops.start("daily", ...)`，`/api/jobs/{id}/run`、`/generate`、`/plan` 也直接 `ops.start`。`op.start` 只检查升级准入锁，不检查暂停文件/`task_pauses`。同时，全仓没有任何 worker 调用 `/tasks/claim`（唯一引用在 `api_v09.py`），所以 v0.9 队列本身就是装饰性的。
- **影响**：作者点「全站急停」后，自动日更、定时任务、手动触发的生成仍会启动并计费；急停给人的安全感是假的。
- **最小修复**：在 `Operations.start`（或 `_start_admitted`）与 `dispatch()` 入口检查 `concurrent_engine.global_paused()` 与项目级 `task_pauses`；或者把 v0.8 的 ops/scheduler 真正接到 `concurrent_engine` 上，而不是维护两套互不相干的队列。
- **复现/证据**：
  ```
  grep -rn "global_paused" backend --include=*.py
  concurrent_engine.py:141,166  （只有 claim 路径）
  ```
  `t20_realapp2.py`：`POST /api/system/ai/pause {"paused":true}` → 200，`global_paused(): True`；而 `dispatch()`、`ops.start` 中没有任何 `global_paused` 引用（`app.py:1155-1175`、`app.py:203-210`）。

### C-10 [P1] SSE 项目过滤泄漏：`project_id IS NULL` 的事件广播给所有项目流

- **位置**：`backend/integration/agent_room.py:602-610`（`if wanted and event.get("project_id") not in {None, wanted}: continue`）；事件源 `backend/manager/api_v085.py:106-116`（`POST /api/chief/messages` 无项目时 `project_id=None`）
- **机制**：过滤条件把 `None` 视为「通配」，而「未绑定项目的主编室聊天」恰恰用 `project_id=None` 落库。任何订阅了项目 A 的 `/room/stream` 都会收到其他书的主编室消息；持久化查询 `events_after(project_id="A")` 却严格过滤 `project_id='A'`，于是**同一条消息在实时流里出现、重连补放时又消失**。
- **影响**：跨书内容泄露（剧情、指令、可能含未发布设定）；客户端状态与补放历史不一致。
- **最小修复**：过滤改为严格相等（`event.get("project_id") != wanted` 即跳过）；无项目事件单独走「无项目订阅」通道，或在 `bind_session_to_project` 之前不广播。
- **复现**：
  ```
  ... python3 -B -X utf8 t17b_sse.py
  A stream received: [(None, '无项目主编室聊天：另一本书的剧情'), ('A', 'A 自己的事件')]
  B stream received: [(None, '无项目主编室聊天：另一本书的剧情'), ('B', 'B 项目的私密事件')]
  ```

### C-11 [P1] SSE 补放只发「最旧 200 条」且不继续，静默丢事件

- **位置**：`backend/manager/api_v085.py:121-135`（`after=0` 默认值；`events_after(..., limit=200)` 只取一页，取完直接进实时循环）；`backend/integration/agent_room.py:378-397`（升序 `seq > after LIMIT 200`）
- **机制**：首次连接没有 `Last-Event-ID` → `after=0` → 返回 **seq 最小的 200 条**，而不是最近 200 条；若项目事件超过 200，第 201 条到最新一条永远不会通过补放送达，也不会提示 `resync_required`。随后实时队列从「当前」开始，客户端看到的顺序是「远古 200 条 → 现在」，中间整段缺失。重连带旧 `Last-Event-ID` 时同样是「从 after 起的第一页 200 条」，超过一页的缺口同样静默。
- **影响**：繁忙项目（主编室、批量任务事件）的 SSE 客户端长期缺事件且无告警；首连显示的是最旧历史，与「当前状态」不符。
- **最小修复**：`events_after` 循环分页直到取空；`after==0` 时从 `max(0, max_seq - limit)` 起放；单页取满时先发 `resync_required`（或让客户端以 `after=0` 重新拉全量快照）再进实时。
- **复现**：
  ```
  ... python3 -B -X utf8 t17_sse.py
  replay page size: 200 first seq: 1 last seq: 200 max_seq: 250
  silent gap: 50 events never replayed (endpoint does not loop)
  ```

### C-12 [P1] `version_id=''` 让质量「自动审稿上限」永久化、「新鲜度」永不失效

- **位置**：`backend/integration/quality.py:118-133`（`version_id = ""` 时上限查询 `(version_id=? OR ?='')` 退化为「本章全部 B 轨评审」）、`quality.py:177-180`（`stale_review` 要求 `row["version_id"] and current_id`，空串直接 False）
- **机制**：没有版本记录的章节（旧书、直接写入 `正文/` 的文件）`versions.current_version()` 返回 `None` → 存 `version_id=""`。上限查询因此统计**所有**历史 B 轨评审，两次之后永久 409；新鲜度判断因空串短路，正文重写后仪表盘仍显示旧分数/`pass`。
- **影响**：旧项目只能自动审两次，之后无论怎么改都不能再审；作者重写整章后仪表盘仍报「通过」，质量门禁给出假阳性。
- **最小修复**：以正文 `content_sha256` 作为无版本章节的评审键（`quality_reviews` 增列或复用 `version_id=sha`）；上限按 `(chapter_id, content_sha)` 计数；`stale_review` 在 `version_id` 为空时比较内容哈希。
- **复现**：
  ```
  ... python3 -B -X utf8 t26_stale.py
  review version_id: ''
  after rewrite: verdict= pass stale= False total= 80.0
  reviewed count: 1

  ... python3 -B -X utf8 t27_legacy_cap.py
  post-rewrite review -> auto_review_limit {'max_auto_reviews': 2}
  ```

### C-13 [P1] 改令链路断头：`start_amendment` 之后没有任何 evaluate/release 路由，任务永久 `held`

- **位置**：`backend/manager/api_v085.py:192-202`（唯一 amend 路由）、`backend/manager/api_v085.py:209-212`（resume 只改 directive 状态）、`backend/integration/agent_hub.py:306-324`（`start_amendment` 把 running 任务置 `held`）、`agent_hub.py:327-365`（`evaluate_amendment` **无任何路由**）
- **机制**：`POST /directives/{id}/amend` 冻结任务；`evaluate_amendment` 只在 `test_agent_hub.py` 中被调用，没有 HTTP/Agent 入口；`POST /directives/{id}/resume` 只把 directive 标回 `running`，不释放 `agent_tasks`。`concurrent_engine` 里另有一套 `hold_for_amendment/release_amendment`，同样无人调用，且操作的是 `task_queue` 而非 `agent_tasks`。
- **影响**：一次改令后任务永远停在 `held`，指令看起来「进行中」但什么也不会再跑；作者只能删库/重建。文档宣称的「评估→放行/重做」流程不可达。
- **最小修复**：暴露 `POST /directives/{id}/amend/{amendment}/evaluate` 与 `.../release`（或在 resume 中释放本轮 amendment 的 held 任务）；给 held 加超时回退；把 `agent_tasks` 与 `task_queue` 的改令语义统一到一处。
- **复现**：
  ```
  ... python3 -B -X utf8 t33_amend_room.py
  task status: held
  after directive resume, task status: held
  endpoints that could release it: none (evaluate_amendment has no route)
  ```

### C-14 [P1] 诊断导出接受任意 `destination`：可向服务器任意可写路径落 `.zip`

- **位置**：`backend/manager/api_v09.py:330-336`（`target = body["destination"]`）、`backend/integration/maintenance.py:247-259`（只拒绝「项目内」与「已存在」，不限制父目录/根目录）
- **机制**：`destination` 来自请求体，`Path(target).expanduser()` 后仅校验后缀 `.zip`、不在项目内、尚不存在；`os.replace` 直接把临时文件搬到目标。相对路径按服务进程 CWD 解析。`--lan` + 已配对设备可以调用该路由（`device_access.guard` 只做设备鉴权，不做路径约束）。
- **影响**：配对手机/局域网设备可在服务账户可写的任意位置创建/覆盖（不存在时）`.zip` 文件；本机任意进程本来就有文件权限，故本机模式为 P2，LAN/配对模式为 P1。
- **最小修复**：忽略客户端路径，固定写入 `data_dir/diagnostics/<generated>.zip`；若必须自定义，限制在 `data_dir/diagnostics` 下并 `resolve()` 后校验 `is_relative_to`。
- **复现**：
  ```
  ... python3 -B -X utf8 t11_export.py
  wrote: /home/ubuntu/.hermes/cache/scratch/tmpXXX/../escaped.zip exists: True
  relative wrote: rel-export.zip True
  ```
  走真实 HTTP（`t20_realapp2.py`）：
  ```
  export to arbitrary path: 200 /home/ubuntu/.hermes/cache/scratch/tmpXXX/x.zip True
  export to ~/.ssh: 200 {"status":"exported","path":"/home/ubuntu/.ssh/evil.zip","bytes":850,"contains_content":false}
  ```
  （测试文件已删除）

### C-15 [P1] v0.9 平台层未接入生成/自动化管线：世界状态、质量、队列、manifest 都只有 HTTP 面

- **位置**：`backend/manager/api_v09.py:15`（唯一 import 方）；生成侧 `Operations.start`（`app.py:228-288`）派发 `manager/worker.py` → `webnovel-writer`，不读 `world_facts`；`world_state.build_context(persist=True)` 与 `latest_manifest()` 在生产代码中**零调用**（仅 `test_world_state.py`）；`quality.review` 只由 `/quality/{chapter}/review` 调用
- **机制**：全仓 grep `world_facts|quality_reviews|context_manifests|task_queue` 在 `backend/webnovel-writer`、`backend/fanqie_auto_publish`、`backend/manager`（除 `api_v09.py`）中无命中。生成管线仍使用旧的 `memory_library/character_state/continuity`，不消费 v0.9 的权威事实、冲突检测、质量分或租约队列；`context_manifests` 因此永远为空。
- **影响**：v0.9 宣称的「世界状态权威 / 高风险拦截 / 双轨质量门禁 / 并发租约」对真实写作与发布**不产生约束**，只是仪表盘/Agent 可查的旁路数据；C-01/C-17/C-18 这类权威缺陷也因此不会在生成时被放大，但同样意味着这些功能没有实际收益。
- **最小修复**：在生成入口（`ops.start("generate"/"polish")` 的 prompt 组装处）读取 `facts_for_chapter + build_context(persist=True, operation_id=...)`，发布前校验 `quality` 最新 verdict；或在 README/接口文档中明确标注这些端点为「advisory only」，避免误认为已生效。
- **证据**：
  ```
  grep -rn "world_state\|world_facts\|quality_reviews\|task_queue\|context_manifests" \
    --include=*.py backend/webnovel-writer backend/manager backend/fanqie_auto_publish | grep -v backend/integration/
  → 只有 backend/manager/api_v09.py
  grep -rn "build_context(\|latest_manifest(" --include=*.py backend | grep -v "def "
  → api_v09.py:100 (persist=False)、world_state.py:462 (persist=False)、test_world_state.py
  ```

---

## 3. P2

> 以下均为可复现或代码可证的问题；按影响面合并同类项。

### 世界状态：权威 / 去重 / 冲突 / 预算 / 检索

| ID | 位置 | 机制与影响 | 最小修复 | 复现 |
|---|---|---|---|---|
| **C-16** | `world_state.py:126-157` | `upsert_fact` 只比较 `authority_level`；等权威覆盖时用请求体整行替换，`pinned`/`author_locked` 被重置为 0。AI 再提取同一条事实即可静默解除作者锁定。`set_card`（`world_state.py:244-252`）在未传 `pinned` 时同样把卡片取消 pin。 | 现有行 `author_locked=1` 或 `pinned=1` 时，除非显式 `author_edit=true`，否则保留这两个字段（`COALESCE`/`MAX`），并拒绝 AI 覆盖。 | `t2_facts.py`：`after: pinned=False author_locked=False` |
| **C-17** | `world_state.py:533-548` | `existing_pinned` 计算后**从未使用**；`high_risk` 只看谓词/宾语关键词，不看「实体已被 pin」。对已 pin 角色的新推断（如「林溪=敌方卧底」，谓词「身份」不含高风险词）直接 `active`。 | `high_risk = high_risk or existing_pinned`（对 pin 实体的新事实一律 `pending_confirm`）。 | `t2_facts.py`：`extract about pinned entity -> {'accepted': 1} status: active` |
| **C-18** | `world_state.py:87-158`、`179-200`、`316-342` | 去重键含 `valid_from/valid_until`，`upsert_fact` 不会自动关闭旧窗口；同一实体+谓词的新值（修为/位置/年龄）会新增第二行，旧行 `valid_until=NULL` 永远 active。`facts_for_chapter(N)` 同时返回两值，`detect_conflicts` 把正常成长误报为冲突。 | 新事实写入时，把同 `(entity,predicate)` 且 `valid_from < 新值`、`valid_until IS NULL` 的旧行自动置 `valid_until = 新valid_from-1`（或 `superseded`）。 | `t3b_conflict.py`：`facts at ch40: [('炼气一层',1,None),('筑基期',30,None)]`、`conflicts at ch40: 1` |
| **C-19** | `world_state.py:320-322` | `detect_conflicts` 跳过 `lie`/`rumor`，但**不跳过 `belief`**；两个角色对同一事的信念差异被当成世界事实冲突。 | 把 `belief` 加入跳过集合；若要与事实对比，另设「信念 vs 事实」的独立账本。 | `t13_world2.py`：`conflicts among beliefs: 1` |
| **C-20** | `world_state.py:559-564` | 第二定义 `reject_fact` 丢失 `pending_confirm` 前置与 `archived` 语义，任何 active 事实可被静默 superseded（与 C-01 同根）。 | 见 C-01。 | `t1_world.py`：`reject(active) -> superseded` |
| **C-21** | `world_state.py:413`（`max_chapter=chapter`） | 为第 N 章组装上下文时，L5 检索允许 `chapter_id <= N`，包含**本章自己的正文**（若已草稿/索引）。实测第 3 章上下文出现第 3 章的「暗门」。 | 上下文组装用 `max_chapter=chapter-1`；`/world/search` 的显式章节过滤保持不变。 | `t13_world2.py`：`L5 in context for ch3: [1, 3]`、`text mentions ch3 draft? True` |
| **C-22** | `world_state.py:417-433` | L1 永不裁剪；预算 200 字时实际 1661 字，manifest 只如实报 `chars`，无 `over_budget` 标志，调用方无法知道超限。 | manifest 增加 `over_budget: true` 与 `budget_overflow_chars`；L1 超限时显式报错或要求调用方提高预算。 | `t4_budget.py`：`budget 200 actual 1661 over 1461` |
| **C-23** | `world_state.py:347-359` | `_rules` 捕获所有异常返回 `[]`；`shared_memory.json` 损坏时 L1「核心创作契约」静默消失，manifest 无任何 warning。L3 `_outline_for` 同样吞异常。 | 捕获 `(OSError, ValueError)` 并在 manifest 记 `L1: {"error": "rules_unavailable"}`；不要让安全层静默降级。 | `t28_l1.py`：`L1 chars with corrupt shared_memory: 0`、`any warning field: []` |
| **C-24** | `world_state.py:463-466` | `pending_count = len(facts_by_status(..., limit=200))`，积压超过 200 时低报。 | 单独 `SELECT COUNT(*)` 取总数，列表再分页。 | 代码可证（`facts_by_status` 默认 limit=200） |

### 质量双轨

| ID | 位置 | 机制与影响 | 最小修复 | 复现 |
|---|---|---|---|---|
| **C-25** | `quality.py:125`、`quality.py:140` | 传了 `judgments`（B 轨）却 `track: "A"`；`stored_reviewer` 却是 `"auto"`。消费方按 track 统计会错。 | `track = "B" if judgment_list is not None else "A"`。 | `t5_quality.py`：`B-track review -> track: A` |
| **C-26** | `quality.py:159-167` | `sorted(mapping)[:200]` 硬截断，API 不透传 `limit`；205 章的书只显示前 200 章，`total` 也报 200，无分页/无提示。 | API 暴露 `limit/offset`，或返回 `total_chapters` 与实际 `returned`，并在 UI 提示「仅显示前 200 章」。 | `t31_dash_limit.py`：`files 205 dashboard chapters 200 total 200 last id 200` |
| **C-27** | `quality.py:182` | 未评审章节会即时 `local_scores(_chapter_text(...))`；`chapter_map` 取自请求开始，若某章文件在两次系统调用之间消失（另一进程删除/重命名），整个仪表盘抛 `QualityError chapter_missing` 404。 | 单章失败降级为该行 `verdict="missing"`，不拖垮整盘。 | `t5_quality.py`：`dashboard raised: QualityError chapter_missing` |

### 维护 / 诊断

| ID | 位置 | 机制与影响 | 最小修复 | 复现 |
|---|---|---|---|---|
| **C-28** | `maintenance.py:208-210` | `chapter_meta` 设计为永久保留 uid，删除章节后仍存在；health 把「索引有、正文无」一律报 `orphan_chapter_index` P1 → **任何一次正常删章后 `/diagnostics` 永久 degraded**，真实 P1 被噪声淹没。 | 删除章节时写 `deleted_at`/`archived` 标记；health 只对「从未存在过」的索引报警，或降级为 P2/信息。 | `t18_health.py`：`issues: [('orphan_chapter_index', 2)]` |
| **C-29** | `maintenance.py:289-301` | 新装环境尚未产生 `costs.sqlite3`（`costs.scope` 只设 contextvar，不建库），`/api/system/diagnostics` 直接 `degraded`。 | 缺失的库视为 `not_created` 且 `ok=true`，或安装时预创建空库。 | `t21_sysdiag.py`：`costs.sqlite3 ok:false`、`status degraded`（该测试用临时 `db_path`，故 manager.sqlite3 也在别处；生产环境 manager 库存在，缺失的只有 costs） |
| **C-30** | `maintenance.py:247-262` | 导出前先 `health(project)`，`wb.initialize` 会为不存在/非项目的目录创建 `.webnovel/workbench.sqlite3`（GET/导出产生写副作用）。 | 先校验项目标记（`state.json`）再初始化；`health` 对缺失目录只读返回。 | `t18_health.py`：`health(missing) -> ok`（目录被创建） |
| **C-31** | `api_v09.py:295-309` | `POST /api/system/diagnostics/recover` 对未知 `action` 返回 `{"status":"ok"}`，运维误以为已恢复。 | 未知 action 返回 400 `unsupported_action`。 | `t20_realapp2.py`：`unknown recover action: 200 ok` |

### 任务 / 租约 / 暂停

| ID | 位置 | 机制与影响 | 最小修复 | 复现 |
|---|---|---|---|---|
| **C-32** | `concurrent_engine.py:263-276` | `renew` 返回的是**更新前**的 `item["lease_expires"]`；客户端按返回值安排续租会提前/滞后。 | `return {"status":"renewed","lease_expires": new_expiry}`。 | `t7_tasks.py`：`renew returned ...86.76 db now ...86.77 returned==db? False` |
| **C-33** | `concurrent_engine.py:315-329` | `fail` 不校验 owner/lease；任何调用者都能把别人的 running 任务打成 failed/pending。 | 增加 `owner` 参数并校验 `lease_owner`，或至少要求 `lease_owner IS NULL OR = ?`。 | `t7_tasks.py`：`fail without owner -> pending` |
| **C-34** | `concurrent_engine.py:185-205`、`165-182` | `pause` 接受任意 `project:*` 字符串，但 `_task_paused` 只比对 `"project:"+resolve()`；`POST /tasks/pause {"scope":"project:书名"}` 返回 `paused` 却完全不生效。`resume(task:)` 的 `state='paused'` 分支是死代码（pause 从不写该状态），运行中任务也不受任务级 pause 影响。 | 统一 scope 规范化（服务器端只接受 `project:<resolved path>` 或项目 id，内部转换）；`resume(task:)` 删除或实现真正的状态回滚。 | `t22_pause_sse.py`：`paused with relative scope -> claimed anyway: True` |
| **C-35** | `api_v09.py:178-202` | `claim` 缺省 owner `"worker"`，`complete` 缺省 `""`；客户端按缺省值 claim 后按缺省值 complete 必 409。 | 两端统一缺省值（建议都强制显式 owner，缺失即 422）。 | `t23_owner.py`：`complete with default body -> SchedulerError task_not_running` |
| **C-36** | `concurrent_engine.py:57-61`、`64-93` | `_event` 在业务事务提交后另开写事务；事件写失败会让整个 API 500，但任务已入队。`submit` 无幂等键（API 也不透传 `task_id`），客户端重试会产生重复任务。 | `_event` 失败只记日志不抛出；`submit` 接受并强制 `Idempotency-Key`/`task_id`。 | 代码可证（`submit` 先 `write_tx` 再 `_event`） |
| **C-37** | `api_v09.py:167-176` | `blocked_by` 传字符串 `"abc"` 时被 `list("abc")` 拆成三个 blocker，任务永远不 ready；`payload` 非 dict 也照存。 | 校验 `isinstance(body["blocked_by"], list)` 且元素为 str，否则 422。 | 代码可证 |

### API / lifespan

| ID | 位置 | 机制与影响 | 最小修复 | 复现 |
|---|---|---|---|---|
| **C-38** | `app.py:1177-1192` | `notify_task = asyncio.create_task(deliver_notifications())` 无条件执行；`create_app(start_dispatcher=False)` 仍每 3 秒轮询通知库。仓库内 10 个 API 测试都用该参数，而 `notification_hooks.db_path()` 固定指向真实 `integration_data/notifications.sqlite3`（与传入的临时 `db_path` 无关）→ 跑测试可能投递真实通知（邮件/webhook）。 | `if start_dispatcher:` 包住两个后台任务，或仅在显式 `start_workers=True` 时启动；测试用 `CHAPTER_WHALE_NOTIFY_WORKER=0` 不够（任务仍被创建）。 | `t25_lifespan.py`：`notification delivery calls with start_dispatcher=False: 1`（3.5 秒内） |
| **C-39** | `api_v09.py:19` | `configure_global_pause` 是模块级全局变量；同进程多次 `create_app` 时后一个覆盖前一个的暂停文件，测试/多实例互相污染。 | 把暂停路径挂到 `app.state`，由 `claim` 显式传入；或按 `data_dir` 缓存。 | 代码可证 |

### 代理 / SSE（index.js、api_v085）

| ID | 位置 | 机制与影响 | 最小修复 | 复现 |
|---|---|---|---|---|
| **C-40** | `index.js:837-853`、`887-890` | `readBody` 超限时先 `request.destroy()` 再 `sendJson(413)`；socket 已销毁，客户端收到 `ECONNRESET` 而不是 413。且插件上限 64MB、manager 上限 32MB（`index.js:54` vs `app.py:29/1239`），32–64MB 的上传必然被 manager 413，>64MB 则是连接重置。 | 先 `response.writeHead(413)` 并 `end`，再 `request.destroy()`；两端限额统一。 | `node body-limit.mjs`：`server sent 413` / `client error: TypeError fetch failed ECONNRESET` |
| **C-41** | `index.js:893-896` | `request.once('close', abortAll)` 注册在 `await readBody(...)` **之后**；Node 26 在请求体读完时立即触发 `close`（实测），监听永远来不及生效 → 客户端断开后上游 POST 继续跑，不中止。GET/SSE 因无 body、注册在 fetch 前，能正常中止。 | 在 handler 入口就注册 `close`，读取 body 阶段用标志位忽略；或监听 `response.on('close')`。 | `node close-race.mjs`：20 次 POST `aborted 0`；`node sse-disconnect.mjs`：`req close @118`（GET 正常） |
| **C-42** | `agent_room.py:620-629` | 溢出时清空队列、放入 `resync_required`（`seq` = 触发溢出的**最新**事件），然后取消订阅；客户端若按该 `id` 重连，会跳过 256 条积压帧。补放机制本身也丢帧（C-11），二者叠加。 | marker 的 `seq` 用最后一条**已交付**的 seq，或不带 `id:` 让客户端走全量重载；文档明确「resync_required = 全量重载」。 | 代码可证（`queue.put_nowait({... "seq": event.get("seq")})`） |
| **C-43** | `api_v085.py:127-135` | 先 `subscribe()` 再 `events_after()`；两步之间发布的事件既进队列又被补放查询命中，客户端收到重复帧。 | 先查补放、记录 `last_seq`，再订阅并在消费时丢弃 `seq <= last_seq` 的帧；或订阅后再查一次并去重。 | `t24_sse_dup.py`：`delivered twice: [4]` |
| **C-44** | `index.js:994-1022` | `_session` 在 token 校验之前返回 token；gate 1 只校验 `Host` 头是回环名，不校验 `request.socket.remoteAddress`；gate 2 对无 `Origin` 的非浏览器请求直接放行。若 DSH 宿主 webServer 绑定到局域网地址，任何 LAN 客户端发送 `Host: 127.0.0.1:<port>` 即可取得 token 并调用白名单写操作。 | 在 `createHandler` 增加 `request.socket.remoteAddress` 回环校验；`_session` 也要求同源 `Sec-Fetch-Site: same-origin` 或一次性的本机文件令牌。 | 代码可证（`index.js:195` `if (origin === undefined) return undefined`） |

### 其他

| ID | 位置 | 机制与影响 | 最小修复 |
|---|---|---|---|
| **C-45** | `workbench_db.py:447-460` | `initialize()` 每次调用都 `executescript(SCHEMA)`（写事务）；`ws.state()` 一次请求调用 6 次（实测），读接口反复拿写锁。 | 先查 `workbench_meta.schema_version`，一致则直接返回；只在缺失/升级时执行脚本。 |
| **C-46** | `workbench_db.py:850-893` | `tokenize` 产出单字 + 2-gram，`search` 用 `OR` 连接；查「林溪」会命中只含「林」的章节，L5 只取 8 条时混入无关章节（实测 8 条命中里 7 条无关，精确命中排第一）。 | 优先用 2-gram 作为必需项，单字仅作兜底；或对结果做 `query in content` 过滤后再截断。 |
| **C-47** | `concurrent_engine.py:414-443` | 并发引擎的唤醒/启动辅助全部断线：`LoopbackNotifier` POST `/internal/events/notify`，但 manager **没有该路由**（全仓仅测试与 client 端字符串），wake 永远 404/False；`spawn_worker` 用 `stdout=DEVNULL, stderr=STDOUT`，stderr 被并入已被丢弃的 stdout，docstring 所说的「startup errors never hide」恰好相反。二者均无生产调用方。 | 要么删掉这两个辅助，要么在 app.py 注册 `/internal/events/notify`（校验 token、只投递给 EventFanout）并把 stdout 指向日志文件/管道。 |

---

## 4. 已复测通过（这些点未发现回归）

| 项 | 结论 | 证据 |
|---|---|---|
| 质量自动审稿上限的原子性 | 6 线程并发 2 成功 / 4 拒绝，未超上限 | `t6_quality_race.py` |
| 队列 claim 的并发互斥 | 6 线程 `max_slots=1` 只产生 1 个 running | `t9_claim_race.py` |
| 八级锁序的顺序/SQLite 嵌套守卫本身 | 逆序报 `lock_order_violation`；`sqlite_scope` 内取锁报 `os_lock_inside_sqlite_tx` | `t16_lock.py` |
| 低权威不得覆盖高权威 | `ai_inferred` 覆盖 `confirmed_prose` 返回 `ignored_lower_authority` | `t1/t2` |
| GC 符号链接防护 | 候选目录/文件遇 symlink 跳过，`resolve()` 越界拒绝 | 代码 `maintenance.py:67-80` + `test_v09_maintenance` |
| 诊断包剥离正文/密钥 | zip 内无正文、无 `sk-secret` | `test_v09_maintenance.py:44-60` |
| 质量双轨加权 | 缺维度/越界/字符串分数均 400，权重和 1.0 | `t5_quality.py`、`t12_api.py` |
| index.js 写白名单覆盖 | manager 侧 167 条变更路由，白名单缺失 **0**；多出的 10 条中 5 条是 GET（本就可读），另 5 条（`/api/free-model/*`、`/api/ai/roles/{role}/test`）manager 未实现、只会 404，属宽松但无提权 | `route_diff.py` |
| 代理 SSE 客户端断开中止上游 | GET/SSE 在客户端 abort 时 `req close` 触发（Node 26 实测） | `sse-disconnect.mjs` |
| 导出目标在项目内/已存在时拒绝 | `destination_inside_project` / `destination_exists` | `t11_export.py` |
| 现有 55 项 v0.9 单测 | 全部通过（说明以上 P0/P1 均无测试覆盖） | `python3 -m unittest ...` → `Ran 55 tests OK` |

---

## 5. 覆盖矩阵（按任务书要求）

| 要求 | 对应发现 |
|---|---|
| GC 删除面 / 符号链接 / artifact 引用 | C-03（P0）、C-30、§4 符号链接通过 |
| 诊断导出 / 健康 | C-14、C-28、C-29、C-31 |
| 世界状态权威 | C-01、C-16、C-17、C-20 |
| 高风险 | C-17（`existing_pinned` 未使用）、C-19 |
| 去重 | C-18、C-16 |
| 冲突 | C-18、C-19 |
| 预算 | C-22 |
| 检索章节边界 | C-21、C-46 |
| 质量双轨 | C-25、C-12 |
| 上限原子性 | §4 通过 |
| 仪表盘新鲜度 | C-12、C-26、C-27 |
| 任务 claim / lease / complete / fail / recover | C-06、C-07、C-32、C-33、C-35、C-36、C-37 |
| 暂停（全站） | C-09、C-34 |
| 改令 | C-08、C-13 |
| 八级锁序实际接线 | C-04、C-05、C-02 |
| 锁与 SQLite 嵌套 | C-02（P0）、C-04 |
| SSE 项目过滤 | C-10 |
| SSE 重放 | C-11、C-43 |
| SSE 溢出 | C-42 |
| API 输入校验和 500 | C-01、C-02、C-35、C-37；C-31（未知 action 静默成功） |
| index.js 代理 / 白名单 / SSE | C-40、C-41、C-44、§4 白名单通过 |

---

## 6. 建议修复顺序

1. **C-01**（一行删除即可恢复确认链路）→ 立刻可发版。
2. **C-02**（把 `chapter_uid` 提出写事务；6 处一起改）→ 与 C-04 的 `sqlite_scope` 守卫同批。
3. **C-03**（GC 保护面）→ 数据丢失，优先级等同 P0。
4. **C-10/C-11**（SSE 泄漏与丢事件）→ 协议层，改动小、影响面明确。
5. **C-06/C-07/C-08**（租约与改令）→ 需要一次任务状态机梳理，建议和 C-13 一起做。
6. **C-12**（质量键改为内容哈希）→ 迁移旧 `quality_reviews` 可保留原列。
7. **C-09/C-15**（接线）→ 产品决策：要么接进 ops/scheduler 与生成管线，要么在文档中降级为 advisory。
8. 其余 P2 按上表逐条清理；C-28/C-29 建议先修，避免健康信号长期失真。

---

## 7. 复现环境

所有脚本位于 `/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-c-platform/`，统一用：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-c-platform
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 <script>.py
```

- Python 脚本：`t1_world.py`、`t2_facts.py`、`t3b_conflict.py`、`t4_budget.py`、`t5_quality.py`、`t6_quality_race.py`、`t7_tasks.py`、`t7b_recover.py`、`t8_amend.py`、`t9_claim_race.py`、`t10_gc.py`、`t11_export.py`、`t12_api.py`、`t13_world2.py`、`t14_quality2.py`、`t15_nested.py`、`t16_lock.py`、`t17_sse.py`、`t17b_sse.py`、`t18_health.py`、`t19_realapp.py`、`t20_realapp2.py`、`t21_sysdiag.py`、`t22_pause_sse.py`、`t23_owner.py`、`t24_sse_dup.py`、`t25_lifespan.py`、`t26_stale.py`、`t27_legacy_cap.py`、`t28_l1.py`、`t29_dedupe.py`、`t30_search.py`、`t31_dash_limit.py`、`t32_init.py`、`t33_amend_room.py`、`t34_commit_lease.py`、`t35_annot_nested.py`、`t36b_import.py`、`nested_scan.py`、`route_diff.py`
- Node 脚本：`close-semantics.mjs`、`close-race.mjs`、`sse-disconnect.mjs`、`body-limit.mjs`（Node v26.12.1）
- 真实应用测试统一设置 `NOVEL_HELPER_ROOT=<临时目录>`，未在仓库内写入任何文件；`~/.ssh/evil.zip` 测试文件已删除。

---

## 8. 备注与边界

- `api_v09` 的 `POST /world-state/facts` 与 `POST /world/facts` 是两条不同路径（不是重复路由），实测两种 body 形状都可用；`index.js` 白名单两者均已覆盖。
- `api_v09` 的 `chapter`/`max_slots` 传非数字时，在**完整 app** 中会命中 `app.py:1264-1273` 的 `ValueError` 处理器返回 400；在只挂 `api_v09` 的最小 app 中才是 500。因此未作为独立发现（但 `ValueError` 处理器依赖 app 级注册，若有人复用 `api_v09.install` 而不复用 app.py 会退化）。
- 本报告未覆盖 `backend/webnovel-writer` 与 `fanqie_auto_publish` 的内部实现（除锁/快照调用点），它们属于其他审计分区。
