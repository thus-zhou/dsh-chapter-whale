# C 域独立全量审计（第四轮）

- 仓库/工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v4/head-c`，detached HEAD `ce50d08`（含 `bae08da`/`36f5add`/`5993b91` 修复链）
- 审计范围：`backend/manager/app.py`、`api_v08.py`、`api_v09.py`；`backend/integration/{concurrent_engine,lock_manager,maintenance,world_state,quality,workbench_db}.py`；以及 v0.8/v0.8.5 读路径、backup/export 路径、诊断 GC/export、schema 自愈、task_queue/租约/暂停状态机。
- 方式：只读工作树 + 独立探针；真实 FastAPI TestClient、真实 SQLite（WAL）、真实文件系统权限、线程/受控交错。未修改仓库受版本控制文件，未联网，未 commit/push。所有脚本与输出在 `/home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-c/`。
- 时间：2026-11-27（CST）。Python：`/home/ubuntu/venvs/dsh/bin/python`（3.12.3）。
- 基线：审计前后 `git status` 仅剩审计前已存在的未跟踪 `node_modules`；`HEAD=ce50d08`。
- 基线测试（本轮实跑）：
  - `python -m unittest discover -s backend/manager -t backend` → `Ran 235 tests ... OK`
  - `python -m unittest discover -s backend/integration -t backend` → `Ran 1270 tests ... OK (skipped=9)`

## 0. 结论

**本轮未发现新的 P0。发现 1 条 P1、11 条 P2、10 条 P3（共 22 条）。**

- **C3-01（P1）仍未闭环**：`writer_runner`/`worker.py`/`skill_executor.py` 对 `world_state`、`quality.review`、`task_queue`、`context_manifests` 的引用仍为 0；v0.9 世界状态、质量分、manifest、并发队列对真实生成/发布没有约束。
- **C3-02 已关闭**：backup/export-legacy 的任意目标路径已被 `allowed_dir`/`allowed_snapshot_roots` 拦住，真实 API 探针返回 400，manager 回归 5/5 通过。
- **上一轮点名残余仍然存在**：C3-03（schema 自愈只在 v0.9 入口生效）、C3-04（annotations/previews 读路径建库或只读 500）、C3-05（诊断锁仍在项目内、dry-run 落锁文件）、C3-06（GC 保护集过宽）、C3-13（改令 hold 状态机）、C3-17（deferred 死状态）、C3-18（deferred 绕过项目互斥）、C3-19（锁统一未完成）、C3-20（agent_hub 两套死队列）。
- **本轮新发现**：`upsert_fact` 的显式 `fact_id` 仍完全绕过去重（确定性重复事实，C4-01）；暂停/恢复与 `resume_due` 的急停缺口仍在（C3-23，按影响升为 P2）；v0.9 body 的 `bool("false")` 真值混淆可绕过自动审稿上限（C4-02）；schema 修复只比较列名，不比较主键/约束（C4-03）；failed blocker 永久阻塞下游（C4-04）；读路径把损坏数据库静默降级为空数据（C4-05）。
- **“测试全绿”仍不能作为平台层已闭环的证据**：p9/p17/p25、p30、c4_pause 等均在全量测试通过的情况下复现。

## 1. 统计与严重度口径

| 级别 | 数量 | 含义 |
|---|---:|---|
| P0 | 0 | 本轮无新的不可逆数据丢失/主路径全断 |
| P1 | 1 | 平台层未接线（产品决策未闭环） |
| P2 | 11 | 事务/锁/租约/暂停/世界窗口/路由的可复现缺陷，或已承认残余 |
| P3 | 10 | 健壮性、错误码、响应形状、保留策略、死代码/约束保真 |

> 严重度沿用上轮口径；C3-23 上轮为 P3，本轮因“全站恢复后作品仍永久暂停”和“急停期间 resume_due 仍 spawn”具有实际阻断/安全影响，升为 P2。

## 2. P1

### C3-01 [P1] v0.9 平台层仍是旁路 API：世界状态/质量/队列/manifest 未进入真实生成与发布（C-15 未闭环）

- **位置**：
  - `backend/integration/writer_runner.py:155-157`（质量判断只走 `quality_gate.review_passed`）
  - `backend/integration/writer_runner.py:543-550`（审稿报告写 `quality_gate.save_report`，不读 `quality_reviews`）
  - `backend/integration/writer_runner.py:1242-1262`（发布走 `chapter_versions.commit_raw_bytes`）
  - `backend/manager/worker.py:87-170`（worker 只调用 `studio`/`writer_runner`/`bridge`/`scheduler`）
  - `backend/integration/world_state.py:545-636`（`build_context`）、`653-664`（`latest_manifest`）
  - `backend/manager/api_v09.py:47-50,108-113,172-176,299-323`
- **机制**：
  - 生成 prompt 组装没有任何 `facts_for_chapter`/`build_context` 调用；`world_facts` 只服务 `/world-state` 仪表盘。
  - `build_context(persist=True)` 生产零调用；`latest_manifest()` 生产零调用，`context_manifests` 永远为空（除非测试直接写）。
  - `task_queue` 的生产者只有 `POST /tasks`；消费者只有 `/tasks/claim`（API 自己）。仓库没有 worker 进程轮询 `claim`。
  - `quality.review` 只由 `/quality/{chapter}/review` 调用；`writer_runner` 的发布门禁使用旧 `quality_gate`，`stage` 使用 `reviewed_chapters`（旧回执），v0.9 质量分对发布没有约束。
  - `agent_room.create_task` 只有测试调用；`agent_tasks` 在真实流程中没有生产者。
- **影响**：作者在世界状态面板看到的事实、冲突、质量分、上下文 manifest、队列状态，对真实写作/发布没有约束力；C-15 期间承诺的“世界状态/质量/租约进入主路径”没有发生。C3-13/C3-20 的队列正确性目前只对 API 沙盒成立。
- **证据（静态 grep，命令+输出）**：
  ```bash
  cd .../head-c
  grep -rn "world_state|facts_for_chapter|build_context|quality\.review|task_queue|concurrent_engine" \
    backend/integration/writer_runner.py backend/manager/worker.py \
    backend/webnovel-writer/backend/services/skill_executor.py
  # （无输出）

  grep -rn "build_context(" backend --include=*.py | grep -v "def build_context" | grep -v test_
  # api_v09.py:117（GET /world/context, persist=False）
  # world_state.py:642（state() 内部, persist=False）

  grep -rn "latest_manifest" backend --include=*.py | grep -v "def latest_manifest" | grep -v test_
  # （无输出）

  grep -rn "hold_for_amendment|release_amendment" backend --include=*.py | grep -v "def " | grep -v test_
  # （无输出）

  grep -rn "create_task(" backend --include=*.py | grep -v asyncio | grep -v test_ | grep -v "def "
  # （无输出）
  ```
- **最小修复（产品决策二选一）**：
  1. 接线：在 `ops.start("generate"/"polish"/"batch")` 的 prompt 组装前调用 `build_context(persist=True)`；发布门禁读取 `quality_reviews` + `facts_for_chapter`；把 `task_queue` 交给真实 worker 消费，并在 worker 中调用 `hold_for_amendment`/`release_amendment`；或
  2. 明确降级：在 UI/文档把这些模块标为 `advisory only`，并删除“并发队列/租约/世界状态约束主路径”的对外宣称。

## 3. P2

### C3-03R [P2] Schema 自愈仍只在 v0.9 入口生效；v0.8/v0.8.5 的缺表/缺列继续 500

- **位置**：
  - `backend/integration/workbench_db.py:50-52`：`_REQUIRED_TABLES` 仍只有 9 张表（`chapter_drafts`、`chapter_meta`、`annotations`、`annotation_hunks`、`patch_ledger`、`world_facts`、`quality_reviews`、`task_queue`、`artifact_refs`）。
  - `backend/integration/workbench_db.py:545-557`：`_schema_current` = 版本号 + 9 表 + 仅 `task_queue.hold_requested` 列。
  - `backend/integration/workbench_db.py:560-569`：`_migrate_columns` 只补 `hold_requested`。
  - `backend/integration/workbench_db.py:588-610`：`initialize` 只在 `_schema_current()` 为 false 时 `_apply_schema`。
  - `backend/manager/api_v09.py:38-45`：只有 v0.9 的 `guard` 调 `maintenance.ensure_schema`。
  - `backend/manager/api_v08.py:36-73`、`backend/manager/api_v085.py:25-42`：v0.8/v0.8.5 的 `guard` 没有 schema 修复。
  - `backend/integration/maintenance.py:252-385`：完整的 `_schema_definitions`/`schema_report`/`ensure_schema` 已实现，但只被 v0.9 guard、`health`、`self_heal` 调用。
- **机制**：`maintenance` 已能按 `workbench_db.SCHEMA` 全量比较 22 张表和列，但 `wb.initialize()` 仍用旧的 9 表检查。只要 9 张必需表和 `schema_version='2'` 还在，缺 `preview_index`、`task_pauses`、`context_manifests`、`directive_exemptions`、`search_fts`、`drafts_history` 等表，或缺 `chapter_drafts.draft_epoch`、`quality_reviews.chapter_uid` 等非 `hold_requested` 列，`initialize()` 都直接返回。v0.9 请求会被 guard 修复，v0.8/v0.8.5 请求不会。
- **影响**：
  - 部分恢复/旧构建写入的库，`PUT /chapters/{n}/draft` → 500 `table chapter_drafts has no column named draft_epoch`。
  - `GET /chapters/{n}/previews` → 500 `no such table: preview_index`（`annotations.list_previews` 直接查询）。
  - v0.8/v0.8.5 的其它读写在缺表/缺列时同样 500；只有先访问任一 v0.9 路由或 diagnostics 才会顺带修复。
  - `health` 本身已能报告并修复（上轮“health 报 ok”部分已关闭），但“所有 API 入口自愈”没有完成。
- **证据（真实 API + SQLite）**：
  ```text
  # c4_schema_v08.py
  wb._schema_current after drop column: True
  schema_report after drop column: {'chapter_drafts': ['draft_epoch']}
  1 v08 PUT draft after column drop: 500 {"code":"internal_error",
      "message":"服务内部错误：table chapter_drafts has no column named draft_epoch"}
  1 schema after: {'chapter_drafts': ['draft_epoch']}     # v08 没有自愈

  # c4_api_probe.py
  B schema_report current after drop preview_index: False
  B GET previews after drop: 500 {"code":"internal_error",
      "message":"服务内部错误：no such table: preview_index"}
  B GET world-state (v09 guard) after drop: 200
  B schema after v09 guard: True []
  ```
  `p1_schema.py` 同时证明 `wb._schema_current()` 在 drop `task_pauses`/`context_manifests` 后仍为 `True`，但 `concurrent_engine.pause` 因为自己调 `ensure_schema` 而“unexpectedly OK”——即修复在调用方，而不在 `initialize`。
- **最小修复**：
  - 把 `_schema_definitions`/`_inspect_schema` 下沉到 `workbench_db`（或让 `initialize` 延迟导入 `maintenance`），使 `_schema_current` 使用完整表/列集合；`initialize` 在缺任何表/列时执行完整 `_apply_schema` + `_migrate_columns`。
  - 或在 `api_v08`/`api_v085` 的 `guard` 也调用 `maintenance.ensure_schema`，并对所有 `/api/projects/{identity}` 路由做一次统一 schema 检查（每请求一次，带缓存）。
  - `_migrate_columns` 从 SCHEMA 派生全部列，而不是只补 `hold_requested`。

### C3-04R [P2] 读路径残余：annotations/previews 仍建库或只读 500；`wb.connect` 没有真正的只读模式

- **位置**：
  - `backend/integration/annotations.py:120-122`：`_current_text()` → `wb.get_draft()`。
  - `backend/integration/workbench_db.py:701-705`：`get_draft()` → `_ensure()`。
  - `backend/integration/workbench_db.py:613-626`：`_ensure()` 在 DB 缺失时 `initialize()`。
  - `backend/integration/workbench_db.py:118-140`：`connect()` 无条件 `path.parent.mkdir(parents=True)`，用普通 RW `sqlite3.connect`，`readonly=True` 只加 `PRAGMA query_only=ON`（且全仓无调用者）。
  - `backend/integration/annotations.py:300-302`（`list_annotations`）、`664-678`（`list_previews`）。
  - `backend/manager/api_v085.py:126-129`（GET annotations）；`backend/manager/api_v08.py:167-195`（GET previews）。
- **机制**：
  - `GET /chapters/{n}/annotations` 走 `annotations.list_annotations` → `_current_text` → `wb.get_draft` → `_ensure` → 在从未初始化过的作品上创建完整 `workbench.sqlite3`（29 张表，237,568 字节）。
  - 只读项目（`.webnovel` 0555）且无 DB：`initialize` 打开 RW 失败，`api_v085.guard` 不捕获 `sqlite3.OperationalError` → 500。
  - 只读项目且已有 DB：`wb.connect` 执行 `PRAGMA journal_mode=WAL`（写模式）失败 → `list_annotations`/`list_previews` 抛 `attempt to write a readonly database` → 500。
  - `api_v09` 的 world/quality/tasks 已通过 `_ensure_readable(create=False)` 修复为 200 空数据，但 annotations/previews 没有对应的只读分支。
- **影响**：只读挂载/归档书/只读共享上，v0.8.5 批注列表与 v0.8 预览列表不可用（500）；普通书一次 GET annotations 就产生永久 `.webnovel/workbench.sqlite3`。C3-04 只完成了 world/quality/tasks/diagnostics。
- **证据（真实 API/SQLite）**：
  ```text
  # c4_api_probe.py
  A db before annotations GET: False
  A GET annotations: 200 db after: True size: 237568
  A tables after: 29

  3 read-only GET annotations: 500 {"code":"internal_error",
      "message":"服务内部错误：unable to open database file"}
  3 read-only GET previews: 200              # 无 DB 时 list_previews 有 existence guard
  3 db exists: False

  # 直接函数（已有 DB + .webnovel 0555）
  read-only list_annotations with existing DB raised: OperationalError attempt to write a readonly database
  read-only list_previews raised: OperationalError attempt to write a readonly database
  ```
- **最小修复**：
  - `wb.connect(project, readonly=True)` 改为 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`；只读路径不 `mkdir`、不执行 `PRAGMA journal_mode=WAL`、不创建 `-wal/-shm`。
  - `annotations._current_text`/`list_annotations`/`list_previews` 先走 `_ensure_readable`（或 `get_draft(readonly=True)`）；DB 缺失/不可读时返回空页，而不是建库或 500。
  - `api_v08`/`api_v085` 的 GET 路由统一捕获 `sqlite3.OperationalError` → 503 `readonly_project` 或 200 空页；不要回显绝对路径。
  - `list_previews` 在 DB 存在但缺 `preview_index` 时返回空页或触发 `ensure_schema`。

### C3-05R [P2] 诊断 GC/export 的项目内 OS 锁仍是写副作用：dry-run 也落锁文件，只读项目 500

- **位置**：
  - `backend/integration/maintenance.py:125-153`（`collect_garbage` 第一步 `lock_manager.hold(project,"diagnostics")`）
  - `backend/integration/maintenance.py:485-507`（`export_bundle` 同样）
  - `backend/integration/maintenance.py:559-576`（`self_heal` 同样）
  - `backend/integration/lock_manager.py:73-75`（`.webnovel/locks/L8-*.lock`）
  - `backend/fanqie_auto_publish/publication_safety.py:57-90`（`file_lock` 先 `path.parent.mkdir(parents=True)` 再 `open("a+b")`）
  - `backend/manager/api_v09.py:369-384`
- **机制**：`collect_garbage(dry_run=True)` 文档是“预览”，但为了拿 diagnostics 锁，`safety.file_lock` 在项目内创建永久 `.webnovel/locks/L8-<hash>.lock` 并 `mkdir` 父目录。只读项目/只读 `.webnovel` 上 `mkdir/open` 抛 `PermissionError`；`lock_manager.hold` 只捕获 `PublicationBlocked`，`api_v09.guard` 也不捕获 `OSError`，最终 500 `internal_error` 并回显绝对路径。
- **影响**：诊断 GC（即使 dry-run）/导出/自愈在只读项目上不可用；普通项目每本书被写入一个永不删除的 L8 锁文件；`dry_run` 的“只读”承诺不成立。C-30 的“GET/导出不产生写副作用”没有覆盖 OS 锁。
- **证据**：
  ```text
  # p3
  dry-run status: dry_run count: 0
  lock files created by dry-run: ['L8-0fbf1e8fe676bf3b.lock']
  read-only gc raised: PermissionError [Errno 13] Permission denied: '.../.webnovel/locks'
  read-only export raised: PermissionError [Errno 13] Permission denied: '.../.webnovel/locks'

  # p8（真实 API）
  POST diagnostics/gc read-only: 500 {'code': 'internal_error',
    'message': "服务内部错误：[Errno 13] Permission denied: '.../.webnovel/locks'"}
  ```
  `c4_lock_probe.py` 另外证明：diagnostics 锁与章节锁互不阻塞，两个锁文件可同时存在。
- **最小修复**：
  - 锁根目录改到 `data_dir/locks/`（或系统临时目录），按项目路径哈希命名，避免在被审计项目内落文件。
  - `lock_manager.hold` 把 `OSError`（PermissionError 等）转成 `LockError("lock_unavailable")`（503/409）；`api_v09.guard` 捕获 `LockError`。
  - `collect_garbage(dry_run=True)` 在不拿写锁的情况下做只读扫描，或明确要求可写并在 UI 提示；只读项目导出走无锁只读路径（诊断包只含哈希/计数）。

### C3-06R [P2] GC 保护集仍过宽：所有 snapshots/revision_previews 永不回收；引用计数机制从未启用

- **位置**：
  - `backend/integration/maintenance.py:23-26`（`_PREVIEW_DIRS=("previews","preview-cache","history")`、`_EVIDENCE_DIRS=("snapshots","revision_previews")`）
  - `backend/integration/maintenance.py:67-98`（`_protected_paths` 无条件把整个 `_EVIDENCE_DIRS` 加入保护集）
  - `backend/integration/maintenance.py:101-122`（候选集完全不含 `_EVIDENCE_DIRS`）
  - `backend/integration/maintenance.py:156-170`（`register_artifact`；生产零调用）
- **机制**：C-03 修复把 `snapshots`、`revision_previews` 从候选集移出，并在 `_protected_paths` 里整目录保护；`_referenced_snapshot_ids` 的结果因此是冗余的。`register_artifact` 仍无生产调用，`artifact_refs` 永远为空。GC 实际只可能删除 `.webnovel/{previews,preview-cache,history}` 中过期文件，而这三个目录在当前代码里没有生产者（`history` 只有测试写入）。模块 docstring 说“GC 只删无引用且已过保留期的历史快照”，与实现相反。
- **影响**：未引用的旧快照/修订预览永久累积（磁盘只增不减）；真正需要回收的对象（旧 `drafts_history`、`quality_reviews`、`context_manifests`、`task_events`、`idempotency_keys`）没有保留策略；引用计数 GC 的对外宣称不成立。另一方面，当前“永不删证据”是安全的，不会重演 C-03 数据丢失。
- **证据**：
  ```text
  # p15
  artifact_refs rows: 0
  gc candidates: ['orphan.bin']
  unreferenced snapshot kept: True unreferenced revision preview kept: True legacy preview kept: True
  ```
  （`test_v09_maintenance.py:23-40` 仍依赖 `.webnovel/history` 这个当前无生产者的目录来证明 GC 能删东西。）
- **最小修复**：明确产品策略：
  - 若“证据永不删”：删除 `artifact_refs`/`register_artifact`/“引用计数 GC”宣称，文档改为“snapshots/revision_previews 永久保留”，并加磁盘增长监控；或
  - 若需要回收：把 `snapshots` 放回候选集，只保护 `_referenced_snapshot_ids`（`annotations.anchor_json.base_snapshot_id`/`preview_index.base_snapshot_id`），保留期外且无引用才删；`save_snapshot`/`save_preview` 调用 `register_artifact(ref_count=1)` 或直接信任 SQLite 引用集；为 DB 表增加 retention（C3-25）。

### C3-13R [P2，潜在；接线 worker 前必修] 改令挂起状态机仍不闭环：running hold 不阻止提交，pending/recovery 可被 claim 绕过，release 可把 recovery_required 洗成 pending

- **位置**：
  - `backend/integration/concurrent_engine.py:406-411`（`_ready` 只检查 `state=='pending'`、`blocked_by`、`_task_paused`，不看 `hold_requested`/`hold_amendment_id`）
  - `backend/integration/concurrent_engine.py:478-506`（`begin_commit` 不看 hold 标志）
  - `backend/integration/concurrent_engine.py:525-539`（`complete` 不看 hold 标志）
  - `backend/integration/concurrent_engine.py:542-571`（`fail` 清 `hold_requested` 但不清 `hold_amendment_id`）
  - `backend/integration/concurrent_engine.py:574-608`（`recover` 把过期任务改 pending，保留 `hold_requested`/`hold_amendment_id`）
  - `backend/integration/concurrent_engine.py:611-653`（`hold_for_amendment` 对 `recovery_required` 也设 held）
  - `backend/integration/concurrent_engine.py:669-691`（`release_amendment` held→pending 不清 `committing`）
- **机制（三条独立路径，均已复现）**：
  1. running 被改令挂起后，`begin_commit` 仍成功、`complete` 仍成功；改令评估时任务已 completed，改令无法再影响。
  2. running 任务被 `fail()` 后变 pending，但 `hold_amendment_id` 仍在；`claim()` 的 `_ready` 不检查它，直接再次领取。租约过期后 `recover()` 改 pending 也保留 `hold_requested=1`/`hold_amendment_id`，`claim()` 同样领取（p9）。
  3. `recovery_required`（committing 过期，明确要求人工对账）被 `hold_for_amendment` 改成 held，再 `release_amendment` 改成 pending，且 `committing=1` 残留；`claim()` 重新领取（p17）。
- **影响**：如果 v0.9 队列按设计接线，作者发出改令后任务仍可提交/完成，或改令评估前被重新执行；`recovery_required` 的安全状态被普通改令清掉，可能重复提交同一章。当前 `hold_for_amendment` 无生产调用（C3-20），所以是潜在缺陷，但一旦接线即触发。
- **证据**：
  ```text
  # p9
  held running: ['t-fail']
  after fail(): {'state':'pending','hold_requested':False,'hold_amendment_id':'amd_A'}
  claim while amendment held: t-fail amd_A
  claim after held lease expiry: t-expire {'state':'running','hold_requested':True,'hold_amendment_id':'amd_B'}

  # p17
  recover: [('t-recovery','recovery_required',True)]
  after hold: {'state':'held','committing':True,'lease_owner':None,'hold_amendment_id':'amd-1'}
  after release: {'state':'pending','committing':True,'lease_owner':None}
  re-claim: t-recovery

  # p25
  hold_requested: ['t']
  begin_commit while hold_requested: True
  complete while hold_requested: completed
  ```
- **最小修复**：
  - `_ready`：`hold_requested=1` 或 `hold_amendment_id` 非空时不可领取（除非有显式 release）。
  - `fail`/`recover`：保留/重设 hold 标志，不要清 `hold_requested` 或 `hold_amendment_id`；若任务失败需要离开改令，走 `release_amendment`。
  - `hold_for_amendment`：只处理 `pending`/`held`/`running`，`recovery_required`/`failed`/`interrupted` 原样跳过。
  - `release_amendment`：held→pending 时同时 `committing=0`，并只在 `hold_amendment_id` 仍是本改令时更新。
  - `begin_commit`/`complete`：`hold_requested=1` 或 `hold_amendment_id` 非空且未 release 时返回 409（或 `hold_pending`）。

### C3-17R [P2] `status='deferred'` 仍是死状态：active 过滤和 `resume_due` 都不认识它，且不再阻塞项目互斥

- **位置**：
  - `backend/manager/app.py:520-524`（`_execute`：`child_status=='waiting'` 且不是 generate+batch+两种 failure_kind 时写 `status='deferred'`，提示“调度器将继续原批次”）
  - `backend/manager/app.py:123-127`（`Store.operations(active_only=True)` 只认 `queued/running/awaiting_login/waiting`）
  - `backend/manager/app.py:356-405`（`resume_due` 只处理 `status=='waiting'`）
  - `backend/manager/app.py:202-210`（启动时只把 `queued/running/awaiting_login` 标 interrupted，`deferred` 跨重启保留）
- **机制**：`deferred` 不在 active 集合，`resume_due()` 直接 `continue`；`Operations.__init__` 也不清理。因此该操作永远不会再被唤醒，也不参与项目互斥。`_execute` 只在 generate+batch+`recovery_cooldown/free_pool_wait` 时写 `waiting`；其他 waiting 结果（daily/polish/其他 failure_kind）全部落入 `deferred`。
- **影响**：一个 daily/polish 的等待结果会变成永久僵尸记录；同一本书可以再启动新的 daily（项目互斥看不到 deferred），造成重复任务；UI 提示“调度器将继续原批次”是假的。重启后记录仍在，但永远不会恢复。
- **证据**：
  ```text
  # p30
  active_only sees deferred: []
  after resume_due: deferred resumed: False
  second daily admitted while deferred: queued
  ```
- **最小修复**：统一状态集合：`Store.operations(active_only=True)` 和 `resume_due` 都包含 `deferred`（或让 `_execute` 在有任何 `next_retry_at` 时写 `waiting`）；`Operations.__init__` 将 `deferred` 转为 `waiting`/`interrupted` 并按策略重试；`resume_due` 重新校验 global/project pause 和 maintenance 状态后再 spawn（见 C3-23）。

### C3-18R [P2] 项目互斥已覆盖 publish/stage/polish/review，但 `deferred` 记录仍是盲区

- **位置**：
  - `backend/manager/app.py:196`（`_PROJECT_MUTEX_KINDS = {"generate","daily","publish","stage","polish","review"}`）
  - `backend/manager/app.py:278-306`（同一 identity 检查 + 项目 `meta_pid` 互斥）
  - `backend/manager/app.py:123-127`（`active_only` 不含 `deferred`）
  - `backend/manager/app.py:356-405`（`resume_due` 的 `records` 同样不含 deferred）
- **机制**：C3-18 主体已修：p28 显示 daily 运行中 publish/polish 都返回 409。但互斥查询基于 `operations(active_only=True)`，`deferred` 不在其中；p30 显示一个 deferred daily 存在时，第二个 daily 仍被 admission 放行。即项目互斥对“僵尸 deferred”不可见。
- **影响**：同一作品仍可能出现两个写任务（旧的 deferred 僵尸 + 新任务）；如果旧任务后来被手工恢复，会与新的并发。除此之外 publish/stage/polish/review 的 admission 互斥已生效。
- **证据**：
  ```text
  # p28
  publish: daily=queued publish blocked: 409: 该作品已有写作或日更任务正在执行...
  polish: daily=queued polish blocked: 409: 该作品已有写作或日更任务正在执行...

  # p30
  active_only sees deferred: []
  second daily admitted while deferred: queued
  ```
- **最小修复**：与 C3-17 同一处修复：把 `deferred` 纳入统一 active 集合；或在 `_start_admitted` 额外扫描全部 operations 中 `status in {'deferred','metadata_pending','needs_revision','blocked'}` 的同项目记录并显式提示。真正跨进程的互斥仍建议由子进程生命周期持有项目级 `lock_manager.hold`（C3-19）。

### C3-19R [P2] C-04 章级锁统一仍未完成：`lock_manager` 只服务 maintenance，chapter/annotations/publishing 仍走裸 `safety.file_lock`

- **位置**：
  - `backend/integration/lock_manager.py:78-114`（八级锁 + SQLite 嵌套守卫）
  - `backend/integration/maintenance.py:127,506,562,566,571`（唯一生产调用点）
  - `backend/integration/chapter_editor.py:171,186,720,759,862,1135,1229,1365`（8 处 `safety.file_lock`）；`chapter_versions.py:436,521,730,757,887,945,1058,1109,1195,1237,1260,1416`（12 处）；`revision_plan.py:323,386`（2 处）
  - `backend/integration/annotations.py` **完全没有 `file_lock`**（快照/预览/索引写入仅靠 SQLite 事务）；`publishing.py` 也没有项目级 `file_lock`
  - `backend/manager/app.py:1317-1327`（只把 `LockError` 映射为 HTTP）
- **机制**：`lock_manager` 的级别/顺序/`note_sqlite_enter` 只被 `maintenance` 和 `workbench_db.write_tx` 使用；章级编辑/修订仍使用裸 `safety.file_lock`（不同的锁文件身份），批注/发布则完全没有项目级文件锁，因此：
  - GC/export 的 `diagnostics` 锁不会与章节/批注写互斥；
  - 裸 `safety.file_lock` 不受 `sqlite_depth` 守卫约束，可以在 SQLite 写事务中申请 OS 锁（当前静态扫描未找到直接嵌套，但规则没有强制）；
  - 锁序违规（例如先 chapter_text 再 config）不会被检测。
- **影响**：C-04 的“三期并发地基”仍只覆盖维护域；诊断与编辑可交错，未来若 GC 候选集包含正文/批注共享文件会直接重演 C-03。锁序/死锁保证无法从代码上成立。
- **证据**：
  ```text
  # grep
  lock_manager callers: maintenance.py:127,506,562,566,571 + app.py:1322(异常映射)
  bare file_lock: chapter_editor 8 + chapter_versions 12 + revision_plan 2 = 22
  annotations file_lock count: 0

  # c4_lock_probe.py
  A diagnostics held levels: [8]
  A chapter lock acquired while diagnostics held: True
  A both files: ['L8-0fbf1e8fe676bf3b.lock', 'chapter-0001.lock']
  B diagnostics acquired while bare chapter lock held: True
  C safety.file_lock inside wb.write_tx: acquired (rule not enforced)
  D lock_manager.hold inside write_tx raised: SqliteNestingError os_lock_inside_sqlite_tx
  ```
- **最小修复**：保留 `safety.file_lock` 的兼容身份，但在其上加 `lock_manager` 的级别/顺序登记（或提供 `hold_compat(project, level, path)`）；至少把 diagnostics 与 chapter_text/derived_index/publication 接入同一级别表；GC 的 protected/candidate 计算必须持有与编辑共享的锁（或明确 GC 只处理无生产者的 legacy 目录）。

### C3-20R [P2] `agent_hub` 的 held 语义仍是另一套死队列：`create_task` 无生产调用，`hold_for_amendment` 无调用，`amend` 无法引用 `task_queue`

- **位置**：
  - `backend/integration/agent_room.py:329-351`（`create_task`：`INSERT INTO agent_tasks`；全仓只有测试调用）
  - `backend/integration/agent_hub.py:356-366`（`start_amendment` 只更新 `agent_tasks`；任务缺失/跨指令时 409 `amendment_task_mismatch`）
  - `backend/integration/agent_hub.py:424-447`（`evaluate_amendment` 只处理 `agent_tasks`）
  - `backend/integration/agent_hub.py:486-507`（`resume_directive` 只释放 `agent_tasks`）
  - `backend/integration/concurrent_engine.py:611-691`（`hold_for_amendment`/`release_amendment` 无生产调用）
  - `backend/manager/api_v085.py:340-390`（`amend/evaluate/release/resume` 路由）
- **机制**：v0.85 的 `agent_directives`/`agent_tasks` 与 v0.9 的 `task_queue` 是两张表、两套 ID、两套状态机。`create_task` 没有生产调用者（`create_directive` 不会自动生成任务），所以 `agent_tasks` 在真实流程中为空；`amend` 带 v0.9 `task_queue` ID 会 `amendment_task_mismatch`，不带 task_ids 则改令只 bump revision、没有任务可影响。`concurrent_engine.hold_for_amendment` 也没有调用者，v0.9 队列的 `hold_amendment_id` 只能靠 `submit(parent_task_id)` 继承一个永远不会出现的父任务。
- **影响**：C-13 的“改令评估→放行/重做”在真实流程中不可达；POST resume 只改 directive 状态，不会释放任何 v0.9 任务；作者以为改令生效，实际任务继续按旧计划执行（或根本没有任务）。与 C3-01 一样是平台层未接线的直接证据。
- **证据**：
  ```text
  # grep
  create_task( ... 无生产调用（仅 test_v085_api.py）
  hold_for_amendment/release_amendment ... 无生产调用

  # c4_agent_probe.py（真实 API）
  create directive: 200 {"id":"dir_7c928ceb",...}
  create v09 task: 200 v09-task
  amend with v09 id: 409 {"code":"amendment_task_mismatch","missing":["v09-task"],"foreign":[]}
  resume directive: 200 {"status":"running","released_tasks":0,...}
  v09 task after resume: pending hold: None
  ```
- **最小修复**：二选一：
  1. 废弃 `agent_tasks`，让 `agent_hub` 直接操作 `task_queue`（增加 `directive_id`/`agent_role` 列，`hold_for_amendment` 成为唯一 hold 入口）；
  2. 保留两套，但在 `create_directive`/任务规划时真正创建 `agent_tasks`，并在 `task_queue` 增加 `directive_id` 外键，`amend/evaluate/release` 事务性同步两表；补一个实际 worker 消费。
  在完成前，文档/UI 不应宣称改令可用。

### C4-01 [P2] `upsert_fact` 显式 `fact_id` 仍完全绕过去重：同一逻辑事实确定性产生多行

- **位置**：`backend/integration/world_state.py:183-213`（`explicit_id=True` 时跳过 `duplicate` SELECT）、`241-265`（直接 INSERT/ON CONFLICT）。
- **机制**：C3-08 已把去重 SELECT 移进 `write_tx`，自动 ID 的并发重复已修（20 线程只产生 1 行）。但只要调用方传入 `fact_id`，`existing is None and not explicit_id` 为 false，逻辑键去重整段跳过；两个不同 `fact_id`、同一 entity/subject/predicate/object/valid_from/assertion 的写入会各插一行。API `POST /world/facts` 直接接受 body 中的 `fact_id`。
- **影响**：使用稳定 ID 的客户端（或任何显式传 ID 的抽取器）可以确定性制造重复 active 事实；L2/冲突 dashboard 重复注入，`confirm/reject/ignore` 只命中其中一条，`facts_by_status` 计数虚高。
- **证据**：
  ```text
  # c4_ws 直接 SQLite
  explicit A: saved fixed-A
  explicit B: saved fixed-B
  explicit duplicate rows: [('fixed-A', '测绘员'), ('fixed-B', '测绘员')]

  # 对照：20 线程自动 ID
  ok: 20 errors: 0 []
  rows for logical fact: 1
  ```
- **最小修复**：显式 ID 仅在“该 ID 已存在”时视为更新；若 ID 不存在，仍执行同一逻辑键去重（命中则复用/合并，或 409 `fact_logical_duplicate`）。同时建议对 `(entity_id, subject, predicate, object, assertion_type, valid_from_chapter, valid_until_chapter)` 建表达式唯一索引（NULL 用 `COALESCE`）。

### C3-23R [P2，较上轮升级] 暂停状态机四个边角仍在：全局恢复不清项目行、`resume_due` 不看全局暂停、`global_paused` 失败开放、`system_ai_pause` 先写文件后校验

- **位置**：
  - `backend/manager/app.py:356-405`（`resume_due` 只检查 `project_paused`，无 `global_paused`；由 `dispatch` 1178-1186 在调用前检查，存在 check→spawn 的 TOCTOU）
  - `backend/integration/concurrent_engine.py:289-297`（`global_paused` 对任何异常 `return False`，损坏/不可读的暂停文件按“未暂停”处理）
  - `backend/integration/concurrent_engine.py:388-403`（`project_paused` 对 `sqlite3.Error` 也 `return False`，暂停表损坏时按“未暂停”处理）
  - `backend/manager/api_v09.py:261-276`（`system_ai_pause` 先 `set_global_pause`，后 `_book(identity)`/`pause(book,"global")`；identity 不存在时 404 但全局文件已写）
  - `backend/manager/api_v09.py:263-269`（带 identity 的暂停会写项目 `global` 行；不带 identity 的恢复只删全局文件）
- **机制/影响**：
  1. **全局恢复不清项目行**：`POST /api/system/ai/pause {"identity": id, "paused": true}` 写全局文件 + 项目 `global` 行；随后 `{"paused": false}`（不带 identity）只删全局文件。`project_paused` 仍 true，`/api/jobs/{id}/run` 返回 409，自动化无法恢复。
  2. **resume_due 绕过急停**：`resume_due` 在拿到 `self.lock` 后仍直接 `threading.Thread(_execute)`，不复查 `global_paused`；p10 证明全局暂停中仍 spawn 一个批次。`dispatch` 的检查与 spawn 之间有窗口。
  3. **global_paused 失败开放**：损坏/不可读的 `global_pause.json` 返回 False，自动化继续跑。
  4. **project_paused 失败开放**：`task_pauses` 表损坏/锁定时返回 False，项目暂停失效。
  5. **先写后校验**：错误 identity 的暂停请求返回 404，但全局文件已写；错误 identity 的恢复请求返回 404，但全局文件已被删除。
- **证据**：
  ```text
  # p10
  global_paused: True
  after resume_due during global pause: status = queued worker_spawned = True [...]
  global_paused on corrupt file: False

  # p31
  request: 404 {'code':'not_found','message':'未登记此作品'}
  pause file exists: True {"paused": true, ...}

  # c4_pause_probe.py
  pause with identity: 200 {... 'paused': True ...}
  paused scopes: [{'scope': 'global', ...}]
  resume without identity: 200 {'status': 'resumed', 'scope': 'global', 'paused': False, ...}
  global file paused: False
  project_paused after global resume: True
  paused scopes after global resume: [{'scope': 'global', 'reason': '全站急停', ...}]
  run job after global resume (project row remains): 409 {'code':'conflict',
      'message':'该作品已暂停自动化，请恢复后再执行'}
  ```
- **最小修复**：
  - `resume_due` 在每次 spawn 前重新检查 `global_paused` + `project_paused` + maintenance，并走 `_start_admitted` 或等价 admission；不要在 `resume_due` 内直接 `_execute`。
  - `global_paused` 对“文件存在但不可解析/不可读”应 fail-closed（true）并记录诊断；`project_paused` 对 sqlite 错误也应 fail-closed。
  - `system_ai_pause` 先解析/校验 identity 和项目、再写文件；失败时回滚。全局恢复（不带 identity）遍历项目清 `global` 行，或干脆只在文件层记全局暂停，不写项目行。
  - 503 响应码见 C3-24。

## 4. P3

### C3-21R [P3] `confirm_fact` 仍允许把 pending 事实“确认”成更低权威 `ai_inferred`，并留下双 active

- **位置**：`backend/integration/world_state.py:336-357`；`backend/manager/api_v09.py:72-77`（body 可传任意 `authority_level`）。
- **机制**：只校验 `authority_level in AUTHORITY` 且不是 future/discarded；`ai_inferred` 合法。确认后 `status='active'`、`authority_level='ai_inferred'`；`_close_previous_windows` 用新权威 rank=2，无法关闭旧 `draft_prose`/`confirmed_prose`（rank 3/4），于是两条 active 同时存在；L2 只收 pinned/confirmed/published/author_locked，因此该事实从长期记忆层消失，但冲突 dashboard 又出现。
- **证据**：
  ```text
  # p20
  after confirm: active ai_inferred
  fact in L2: False L2 ids: []

  # c4_ws（旧 draft_prose + 新 pending ai_inferred）
  confirm ai_inferred leaves old active: None new: ai_inferred
  active at 5: [('old3', 'draft_prose'), ('new3', 'ai_inferred')]
  ```
- **最小修复**：确认只接受严格更高的权威（`AUTHORITY[new] > AUTHORITY[old]`，author_locked 特判），默认 confirmed_prose；若需要“确认但不提升”，提供独立 `accept_as_is` 语义并明确 UI。`confirm_fact` 还应拒绝把 `rumor/lie/belief` 当 fact 确认并触发 fact 窗口关闭。

### C3-22R [P3] v0.9 API 手写 `int()` 对 JSON object 仍无兜底：claim/recover/gc 等返回 500 而非 4xx

- **位置**：
  - `backend/manager/api_v09.py:38-49`（`guard` 只捕获 4 个领域异常，不捕获 `TypeError/ValueError/sqlite3`）
  - `backend/manager/api_v09.py:213-217`（`max_slots=int(...)`/`max_attempts`）
  - `backend/manager/api_v09.py:294`（`recover max_attempts=int(...)`）
  - `backend/manager/api_v09.py:375`（`gc min_age_seconds=int(...)`）
  - `backend/manager/api_v09.py:149`（`exemption chapter=int(...)`）
  - `backend/manager/api_v09.py:327-329`（`chapter` path 由 FastAPI 校验，body 的 judgments 等未校验）
- **机制**：v08 的 `guard` 已在 `b7` 中增加 `(TypeError, ValueError)` → 400；v0.9 的 guard 没有。JSON object 传给 `int()` 抛 `TypeError`，落到 app 的 `unhandled_handler` → 500 `internal_error`，并回显内部异常文本。
- **证据**：
  ```text
  # p24
  v08 split offset object: 400 {'code':'invalid_request', ...}
  v08 import start object: 400 {'code':'invalid_request', ...}
  v09 claim max_slots object: 500 {'code':'internal_error',
      'message':"服务内部错误：int() argument must be a string, ... not 'dict'"}

  # c4_api_probe.py
  D v09 claim max_slots object: 500 ...
  D v09 recover max_attempts object: 500 ...
  D v09 gc min_age object: 500 ...
  ```
- **最小修复**：v0.9 `guard` 增加 `(TypeError, ValueError, KeyError, sqlite3.ProgrammingError)` → 400 `invalid_request`；或把这些 body 改成 Pydantic 模型（推荐），让 FastAPI 统一 422。

### C3-24R [P3] 诊断/错误响应形状与错误码：health 缺字段、503 映射为 `request_failed`、500 回显绝对路径/SQL

- **位置**：
  - `backend/integration/maintenance.py:393-398`（缺项目分支返回 `versions/drafts`）vs `maintenance.py:467-471`（正常分支没有这两个键）；`maintenance.py:416-418`（`db_open_failed` 分支缺 `counts/disk_free_bytes/checked_at`）
  - `backend/manager/app.py:1344-1351`（状态映射表没有 503/422；503 → `request_failed`）
  - `backend/manager/app.py:1355-1363`（`unhandled_handler` 把 `str(exc)` 拼进 message；`redact` 只掩密钥，不掩路径）
- **影响**：客户端依赖固定键时会在“项目正常”路径拿不到 `versions/drafts`；全站急停的 503 与其他 503 共用 `request_failed`，UI 无法区分；LAN 客户端可从 500 消息读到服务器绝对路径/SQL 表名（p8 已见 `.../.webnovel/locks`、`no such table: task_pauses`）。
- **证据**：
  ```text
  # c4_health
  normal keys: ['chapters','checked_at','counts','disk_free_bytes','integrity','issues','schema','status']
  missing keys: [...,'drafts',...,'versions']  # 仅缺项目分支有 versions/drafts

  # p11
  run while global paused: 503 {'code':'request_failed','message':'全站急停中，...'}

  # p8
  POST diagnostics/gc read-only: 500 {'code':'internal_error',
    'message':"服务内部错误：[Errno 13] Permission denied: '.../.webnovel/locks'"}
  ```
- **最小修复**：health 所有分支统一 schema；`http_error_handler` 补 503→`service_unavailable`/`paused`、422→`invalid_request`、500→`internal_error`；`unhandled_handler` 只返回通用消息 + 错误 ID，把详细异常写入本地诊断日志/诊断包（不含路径给远端）；`redact` 增加绝对路径/项目名掩码。

### C3-25R [P3] DB 表仍无保留策略，GC 只管文件；`task_events` 等只写不读

- **位置**：
  - `backend/integration/workbench_db.py:471-533`（`drafts_history`、`task_events`、`quality_reviews`、`artifact_refs` 等无 retention）
  - `backend/integration/concurrent_engine.py:66-78`（`task_events` 只 INSERT，全仓无 SELECT）
  - `backend/integration/workbench_db.py:922-927`（`idempotency_gc` 只有测试调用）
  - `backend/integration/maintenance.py:125-153`（GC 只扫目录，不删 DB 行）
  - `backend/integration/world_state.py:628-635`（`context_manifests` 每次 persist 只 INSERT；`latest_manifest` 无调用）
- **影响**：长期使用后 `task_events`/`drafts_history`/`quality_reviews`/`context_manifests`/`task_pauses`/`idempotency_keys` 无界增长；诊断 GC 报告“collected 0”但 DB 持续膨胀；`task_events` 是纯写放大。
- **证据**：
  ```text
  # c4_retention
  gc removed: ['.../.webnovel/history/old.bin']
  db rows after gc: {'task_events': 500, 'drafts_history': 50,
                     'context_manifests': 1, 'idempotency_keys': 0}
  ```
- **最小修复**：在 `collect_garbage` 增加 DB retention（如 `drafts_history` 保留每章 N 条/90 天、`task_events` 保留 30 天、`idempotency_keys` 过期删除、`context_manifests` 每章保留最新 K 条）；为 `task_events` 增加只读 API 或删除写入；`idempotency_gc` 在 app 启动/dispatch 周期调用。

### C3-26R [P3] C-47 的唤醒路径仍无生产者/消费者，且 `/internal/events/notify` 不在 `WRITE_ROUTES`

- **位置**：
  - `backend/integration/concurrent_engine.py:710-787`（`LoopbackNotifier`/`spawn_worker`/`EventFanout` 只有测试调用）
  - `backend/manager/app.py:1258-1276`（路由从 `CHAPTER_WHALE_INTERNAL_TOKEN` 读 token；该环境变量全仓只有路由读取，无生产写入）
  - `index.js:227-395`（`WRITE_ROUTES` 不含 `/internal/events/notify`）
- **机制**：路由本身可用（带正确 env token 返回 200），但生产没有构造 `LoopbackNotifier`、没有设置 token、没有订阅 `app.state.event_fanout`；Node 代理的写白名单也不含该路径。所谓“主进程唤醒路径”在真实运行中不可达。
- **证据**：
  ```text
  # p12
  without env token: 403 {'code':'forbidden','message':'内部令牌无效'}
  with env token: 200 {'ok':True,'subscribers_dropped':0}

  # p16b
  mutating routes: 176 listed non-GET: 175
  MISSING (blocked by proxy):
    POST /internal/events/notify
  ```
- **最小修复**：要么删除 `LoopbackNotifier`/`EventFanout`/路由并移除 C-47 的对外宣称；要么在 manager 启动时生成随机 token 写入子进程 env（或 Unix socket/loopback 鉴权），由 task producer 调用 `notify_callback`，并把路由加入 `WRITE_ROUTES`/代理例外；同时补一个真实订阅者（SSE/worker）。

### C3-27R [P3] dashboard 聚合按页计算；`state()` 搜索包含本章；若干死分支

- **位置**：
  - `backend/integration/quality.py:210-269`（`averages`/`reviewed` 只对当前 `chapters` 窗口求和，不是全书；`262-266`）
  - `backend/integration/world_state.py:650`（`state()` 的 `search` 用 `chapter=chapter`，而 `build_context` 的 L5 用 `max_chapter=chapter-1`）
  - `backend/integration/world_state.py:736`（`fact.get("pinned")` 在 allowed 字段过滤后恒为 None）；`world_state.py:765-775`（`causal_scan` 的 `indirect` 组永不填充）；`quality.py:144`（`_auto_count` 无调用）
- **影响**：超过一页（默认 200 章）时，UI 的“已审/平均分”只是当前页统计；世界状态 dashboard 的“搜索”可能召回本章正文，和上下文包语义不一致；死分支让后续维护误以为有对应能力。
- **证据**：
  ```text
  # c4_quality_probe.py（3 章，仅 1/2 审）
  full chapters: 3 reviewed: 2 plot avg: 73.67
  page limit=1 reviewed: 1 plot avg: 90.0 returned: 1

  state search hits: [(1, '正文:1')]
  context L5 items: []
  ```
- **最小修复**：`averages`/`reviewed`/`unreviewed` 用全书聚合 SQL（或单独 summary 查询），分页只影响 `chapters`；`state()` 的搜索改 `max_chapter=chapter-1` 或明确“dashboard 含本章”；删除/接线死分支。

### C4-02 [P3] v0.9 body 的 `bool("false")` 真值混淆：`force` 可绕过自动审稿上限，`paused` 字符串会反向操作

- **位置**：
  - `backend/manager/api_v09.py:325-329`（`force=bool(body.get("force"))`）
  - `backend/manager/api_v09.py:265`（`paused=bool(body.get("paused", True))`）
  - `backend/manager/api_v09.py:352-353`、`374`（`dry_run=bool(...)`，方向相反：字符串 "false" 仍 dry-run，属安全方向）
  - `backend/manager/api_v09.py:158-160`（`apply_to_existing=bool(...)`）
- **机制**：Python `bool("false")` 为 True。JSON 客户端把布尔值误发成字符串时：`force="false"` 会绕过 `MAX_AUTO_REVIEWS`；`paused="false"` 会执行暂停而不是恢复；`dry_run="false"` 仍只预览。
- **证据**：
  ```text
  # c4_quality_probe.py
  force='false' string: third auto review accepted (bool truthiness)
  ```
- **最小修复**：对布尔字段使用 `is True`/`isinstance(value, bool)` 校验，或改成 Pydantic 请求模型（推荐），让 FastAPI 统一 422。

### C4-03 [P3] Schema 修复只比较列名，不比较主键/约束/类型：缺 PK 的表也会被判定 `current=True`

- **位置**：
  - `backend/integration/maintenance.py:291-312`（`_inspect_schema` 只比较表名 + `PRAGMA table_info` 的列名）
  - `backend/integration/maintenance.py:336-344`（`_addable_column` 剥离 `PRIMARY KEY`/`UNIQUE`/`AUTOINCREMENT`）
  - `backend/integration/maintenance.py:347-385`（`ensure_schema` 只 `ALTER TABLE ADD COLUMN`，不重建表）
- **机制**：`schema_report` 的 `current` 只看“表存在 + 列名齐全 + 版本号”，不看 `pk`、`notnull`、`default`、`UNIQUE`/`CHECK`/`FOREIGN KEY`、索引。一个从旧构建/部分恢复而来、列名齐全但缺主键的 `task_pauses` 会被判定健康；`ensure_schema` 也不会修复。反过来，如果缺的是主键列，`ALTER TABLE ADD COLUMN` 只能加一个无主键列，`schema_report` 随后仍报 `current=True`。
- **影响**：修复后的库可能接受重复主键/重复 scope，破坏 `INSERT OR REPLACE` 语义；`health` 给出假阴性；后续真正写入时才暴露 `UNIQUE constraint`/重复行。
- **证据**：
  ```text
  # c4_pk
  schema current with task_pauses lacking PK: True
  paused rows: [{'scope': 'global', 'reason': 'a', ...},
                {'scope': 'global', 'reason': 'b', ...}]
  ```
- **最小修复**：`_inspect_schema` 额外比较 `PRAGMA table_info` 的 `pk/notnull/dflt_value` 与 `PRAGMA index_list`/`sqlite_master.sql`；对表级约束/索引不一致的表走“重建表 + 复制数据”路径，而不是只 `ADD COLUMN`。`current` 只在完整定义匹配时为 true。

### C4-04 [P3] `blocked_by` 的 failed 上游永久阻塞下游：`blocked_reason` 只报告，没有解除策略

- **位置**：
  - `backend/integration/concurrent_engine.py:146-169`（`_validate_blockers` 只校验存在/自引用/环）
  - `backend/integration/concurrent_engine.py:172-183`（`_blocked_reason` 把 `failed` 作为阻塞原因返回）
  - `backend/integration/concurrent_engine.py:406-411`（`_ready` 只接受 completed/cancelled）
- **机制**：C3-15 已修复 missing/self/cycle 的提交拒绝与 `blocked_reason` 展示，但没有定义 failed blocker 的策略。上游任务 `failed` 后，下游永远 pending；`claim` 返回 None；snapshot 显示 `{"reason":"failed"}`，但没有自动 cancel/fail 子任务、没有 `release_blocker` API、也没有“修复上游后自动继续”的语义。
- **影响**：一次失败会让整条 DAG 静默卡住；作者只能手工重试上游或重建任务；在没有 worker 的当前状态更是“静默卡住”。
- **证据**：
  ```text
  # c4_block2
  up state: failed
  claim down: None
  snapshot reason: [{'task_id': 'up', 'reason': 'failed'}]
  down state: pending
  ```
- **最小修复**：定义失败传播策略（fail/cancel 下游，或要求作者显式 `release_blocker`）；`claim`/`snapshot` 返回 `blocked_reason` 已具备，补一个“解除/重试上游” API；在 submit 时对“已 failed 的 blocker”给出 409 或警告。

### C4-05 [P3] 读路径把 SQLite 错误静默降级为空数据：损坏/锁定的 DB 在 world/quality/queue 上表现为“空”而非“不可用”

- **位置**：
  - `backend/integration/world_state.py:100-115`（`_ensure_readable` 捕获 `sqlite3.Error` → `False`）
  - `backend/integration/quality.py:47-57`（同上；`dashboard` 随后按文件计算并返回 200）
  - `backend/integration/concurrent_engine.py:81-98`（`_ensure` 捕获 `sqlite3.Error` → `False`；`list_tasks` 返回 `[]`，`get` 抛 `task_missing` 404）
  - `backend/integration/world_state.py:639-650`（`state()` 在无库时返回空 cards/facts/conflicts）
  - `backend/integration/quality.py:210-214`（DB 不可读时只返回文件层结果）
- **机制**：C3-04 的“只读/缺库不 500”修复使用了 `except sqlite3.Error: return False`，把“数据库不存在（合法空态）”和“数据库损坏/被独占/权限错误（故障）”合并成同一个空态。`world_state.state`、`quality.dashboard`、`task_queue.list_tasks` 都会返回 200 空数据；只有 `GET /diagnostics` 的 `health()` 会报 `db_open_failed`/`degraded`。
- **影响**：`workbench.sqlite3` 损坏、被其他进程长时间独占、或只读权限错误时，UI 会显示“没有事实/没有审稿/没有任务”，作者可能据此重新审稿/重新入队，造成重复模型调用或重复任务；错误被掩盖到诊断页。
- **证据**：
  ```text
  # c4_corrupt（把 workbench.sqlite3 覆盖为 "not a sqlite database"）
  world_state -> ok
  quality -> ok
  list_tasks -> ok
  snapshot -> ok []
  health: degraded error ['db_open_failed']
  ```
- **最小修复**：区分 `not exists` 与 `sqlite3.Error`：前者返回空态，后者返回 503 `db_unavailable`（带错误 ID，不返回路径/SQL）或至少在响应里带 `degraded: true`/`db_error` 标记；`list_tasks`/`snapshot` 不要用 404/空数组伪装 DB 故障。`health` 已经能报 P0，可作为 UI 的兜底。

## 5. 已关闭/复核（本轮实跑）

| 编号 | 状态 | 本轮证据 |
|---|---|---|
| C3-02 任意导出目标 | **关闭** | p21：backup 400、export-legacy 400；manager `test_audit_v3_fix_c` 5/5 通过；`transaction_journal._is_within` + `allowed_dir`/`allowed_snapshot_roots` |
| C3-07 confirm 关窗 | 关闭（默认路径） | p4 + `test_audit_v3_fix_c`：confirm 后旧窗口关闭（断言 `valid_until=4`）；p27b：显式新 ID 关闭旧窗口；C3-21 降级路径仍留双 active |
| C3-08 并发去重 | 部分关闭 | 20 线程自动 ID 只 1 行；显式 `fact_id` 见 C4-01 |
| C3-09 逻辑键含 assertion | 关闭 | p26：fact/rumor 两个不同 fact_id，fact 行未被改 rumor；`test_audit_v3_fix_c` |
| C3-10 权威 CASE | 关闭 | p27：ai_inferred 不再关闭 draft_prose；旧事实保留 |
| C3-11 begin_commit 过期 | 关闭 | p6：抛 `recovery_required`，不再 +300s |
| C3-12 fail TOCTOU | 关闭 | p7：旧 worker fail 抛 `task_not_running`，新 owner 租约保留 |
| C3-14 submit(task_id) 忽略 payload | 关闭 | p5：payload/priority 变化抛 `task_id_payload_mismatch` 409；同参数 dedup |
| C3-15 blocked_by 校验 | 核心关闭 | p18：missing/self/cycle 均 400；failed 策略见 C4-04 |
| C3-16 set_card 局部更新 | 关闭 | p19：改名后 card_md/aliases/kind/story_time 保留；显式空值可清空 |
| C3-18 项目互斥 | 核心关闭 | p28：publish/polish 与 daily 同时启动被 409；deferred 盲区见 C3-18R |
| C3-03 health 检测 | 核心关闭 | manager `test_audit_v3_fix_c`：首次 degraded + schema_incomplete，第二次 ok；v0.9 guard 自愈 |
| C3-04 world/quality/tasks 只读 | 核心关闭 | p14：read-only world/quality 200（空数据），diagnostics 200；annotations/previews 见 C3-04R |
| C3-05/C3-06/C3-13/C3-17/C3-19/C3-20 | 未关闭 | 见 §3 |
| C3-21/C3-22/C3-24/C3-25/C3-26/C3-27 | 未关闭/部分 | 见 §4 |

## 6. C-01..C-47 与 C-R2 复核矩阵

> “已修”只代表本轮在 C 域重新读过代码/跑过探针或全量测试；“未复审”表示 B/D 域或 Node 代理不在本轮范围，不能据此宣称修好。

| 编号 | 状态 | 本轮证据/说明 |
|---|---|---|
| C-01 | 已修 | p29/回归：confirm 200 active/confirmed_prose，reject-active 409 |
| C-02 | 已修 | `write_tx` 内 `chapter_uid` SAVEPOINT；全量 integration 1270 通过 |
| C-03 | 已修（GC 过保护见 C3-06） | p15：snapshot/revision preview 均保留 |
| C-04 | 部分 | C3-19R：lock_manager 仍只用于 maintenance |
| C-05 | 已修 | test_lock_manager 全绿 |
| C-06 | 已修 | recover attempts>=max → failed |
| C-07 | 已修（begin_commit 过期见 C3-11） | p6 已改为 recovery_required |
| C-08 | 部分 | C3-13R：running hold 仍可提交/完成 |
| C-09 | 部分 | C3-23R：resume_due 无全局检查 |
| C-10 | 未复审 | 合并 B-05 |
| C-11 | 未复审 | 合并 B-14 |
| C-12 | 已修 | `_review_key` 内容哈希 |
| C-13 | 部分 | C3-20R：agent_tasks 无生产者、task_queue 不互通 |
| C-14 | 已修 | diagnostics allowed_dir；p21 |
| C-15 | 未闭环 | C3-01 |
| C-16 | 已修 | facts pin/lock 保留 |
| C-17 | 已修 | `existing_pinned` 接入 high_risk |
| C-18 | 已修（默认路径） | p4/p27b；C3-21 降级路径见 §4 |
| C-19 | 已修 | detect_conflicts 跳过 lie/rumor/belief |
| C-20 | 已修 | 第二定义已删；reject 恢复 archived/pending |
| C-21 | 已修 | build_context L5 `max_chapter=chapter-1` |
| C-22 | 已修 | over_budget/budget_overflow_chars |
| C-23 | 已修 | _rules/_outline_for 返回 warning |
| C-24 | 已修 | count_facts_by_status |
| C-25 | 已修 | track = B if judgments is not None |
| C-26 | 已修 | dashboard limit/offset/total/truncated |
| C-27 | 已修 | 缺章/消失降级 missing |
| C-28 | 已修 | orphan P2 |
| C-29 | 已修 | costs/agent 库缺失不 degraded |
| C-30 | 部分 | C3-04R：annotations/previews 读路径仍建库/500；C3-05R 锁写 |
| C-31 | 已修 | 未知 action 400 unsupported_action |
| C-32 | 已修 | renew 返回更新后的 lease_expires |
| C-33 | 已修 | fail 的 owner 条件已在 UPDATE 内 |
| C-34 | 已修 | _normalize_scope 统一 resolved path |
| C-35 | 已修 | claim 无 owner 422 owner_required |
| C-36 | 部分 | 事件失败吞掉；idempotency_keys 未接入 submit（C3-14 已用 params hash 替代） |
| C-37 | 已修 | blocked_by 字符串 422 invalid_blocked_by |
| C-38 | 已修 | start_dispatcher=False 不启动 dispatch/notify |
| C-39 | 部分 | api_v09 用 per-app pause_path；_start_admitted/dispatch 仍用模块级 DATA（生产单 app） |
| C-40 | 未重跑 | Node 代理 413 drain |
| C-41 | 未复审 | Node |
| C-42 | 未复审 | Node/SSE |
| C-43 | 已修（v3） | 先 replay 再 subscribe，再 replay 补窗 |
| C-44 | 未复审 | Node |
| C-45 | 部分 | C3-03R：`_schema_current` 仍只查 9 表 |
| C-46 | 已修（v3） | `_search_needles`/compact 过滤 |
| C-47 | 部分 | C3-26R：路由存在，但无生产者/订阅者/token，且不在 WRITE_ROUTES |
| **C-R2-01** | 已修（窗口关闭条件） | C3-07 默认路径；C3-21 降级路径见 §4 |
| **C-R2-02/03** | 基本修 | renew 单条 CASE；recover/_mark_recovery 带 owner/expiry；hold 状态机见 C3-13R |
| **C-R2-04** | 已修（项目暂停） | p11：project 409，global 503；resume_due 见 C3-23R |
| **C-R2-05** | 未修 | C3-05R |
| **C-R2-06** | 已修 | C3-14 关闭 |
| **C-R2-07** | 未修 | C3-20R |
| **schema 9 表** | 部分 | C3-03R：maintenance 全量，`wb.initialize` 仍旧 9 表 |
| **诊断 GC/export 写锁副作用** | 未修 | C3-05R |
| **agent_hub held 语义** | 未修 | C3-20R |

## 7. 探针索引与原始输出

所有脚本位于 `/home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-c/probes/`（旧 v3 探针已复制并改路径）。运行模板：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v4/head-c
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
  /home/ubuntu/venvs/dsh/bin/python -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-c/probes/<script>.py
```

| 探针 | 用途 | 本轮关键输出 |
|---|---|---|
| `p1_schema.py` | 9/20 表自愈 | `wb._schema_current=True`；pause/build_context 由调用方 ensure_schema 修复 |
| `p1b_schema_column.py` | 单列自愈 | quality.review 由 quality._ensure_writable 修复 |
| `p1c_schema_fts.py` | search_fts 自愈 | self_heal rebuild_search 成功 |
| `p2_read_side_effect.py` | GET world-state 不建库 | `db after GET: False`；无幽灵 chapter_meta |
| `p3_readonly_gc.py` | dry-run 锁文件/只读 | L8 lock 文件；PermissionError |
| `p4_confirm_window.py` | 确认关旧窗口 | 旧窗口 `valid_until=4`；无冲突 |
| `p5_submit_payload.py` | task_id 参数冲突 | `task_id_payload_mismatch` 409 |
| `p6_commit_expired.py` | 过期 begin_commit | `recovery_required` |
| `p7_fail_toctou.py` | fail 竞态 | 旧 worker `task_not_running`，新租约保留 |
| `p8_api_500.py` | schema/只读 API 映射 | pause/exemptions 200（v09 自愈）；GC 500；health ok |
| `p9_amendment_claim.py` | hold 被 claim 绕过 | fail/recover 后仍可领取 |
| `p10_pause_gaps.py` | resume_due/急停文件 | 全局暂停仍 spawn；损坏文件 false |
| `p11_jobs_pause.py` | jobs run 暂停 | 项目 409 / 全局 503 request_failed / 恢复 queued |
| `p12_wake.py` | 唤醒 token | 无 token 403；有 token 200；无订阅者 |
| `p13_upsert_race.py` | 旧交错探针 | 因去重 SELECT 移入 write_tx 而 barrier 失效；改用 20 线程生成探针 |
| `p14_readonly_reads.py` | 只读 world/quality | 200 空数据；diagnostics 200 |
| `p15_gc_protection.py` | GC 保护集 | 未引用 snapshot/preview 全部保留 |
| `p16b_write_routes.py` | 路由白名单 | 唯一缺失 `/internal/events/notify` |
| `p17_recovery_hold.py` | recovery→held→pending | 重新 claim，committing 残留 |
| `p18_blockers.py` | blocked_by 校验 | missing/self/cycle 均 400 |
| `p19_card_partial.py` | set_card 局部写 | 字段保留 |
| `p20_confirm_downgrade.py` | 确认降级 | active ai_inferred，L2 不收 |
| `p21_export_destination.py` | backup/export 路径 | backup 400 / export-legacy 400 |
| `p24_scalar_500.py` | 标量 TypeError | v08 400；v09 claim 500 |
| `p25_running_hold.py` | running hold | begin_commit/complete 照常 |
| `p26_assertion_merge.py` | fact→rumor | 不同 fact_id，fact 行保留 |
| `p27_authority_case.py` | CASE 权威 | ai_inferred 不关闭 draft_prose |
| `p27b_explicit_id.py` | 显式新 ID 关窗 | 旧窗口关闭 |
| `p28_publish_mutex.py` | 项目互斥 | publish/polish 被 409 |
| `p30_deferred.py` | deferred 死状态 | active 空；resume 不恢复；second daily 可入 |
| `p31_pause_side_effect.py` | 暂停先写后验 | 404 但全局 pause 文件已写 |
| `c4_api_probe.py` | annotations 建库/只读 500；v09 标量 500；v08 previews 500 | 见 §3/§4 |
| `c4_schema_v08.py` | v08 缺列/缺表 500 | `table chapter_drafts has no column named draft_epoch` |
| `c4_ws`（内联） | 显式 fact_id 重复；确认降级 | 两行同逻辑事实；双 active |
| `c4_race`（内联） | 20 线程 upsert | 1 行 |
| `c4_pause_probe.py` | 全局恢复残留 | project_paused True；job run 409 |
| `c4_lock_probe.py` | 锁互斥/规则 2 | diagnostics 与 chapter 锁同时持有；裸锁在 SQLite tx 内可获取 |
| `c4_agent_probe.py` | 两套任务队列 | amend v09 id 409；resume released 0 |
| `c4_quality_probe.py` | 分页聚合/搜索/force | page avg 90 vs full 73.67；state 含本章；force 字符串绕过 |
| `c4_retention`（内联） | DB 保留 | GC 删文件，500 task_events/50 drafts 保留 |
| `c4_pk`（内联） | schema 约束保真 | 缺 PK 仍 current=True；pause 重复行 |
| `c4_block2`（内联） | failed blocker | down 永久 pending，reason=failed |
| `c4_corrupt`（内联） | 读路径 DB 故障 | world/quality/list_tasks 200 空；health degraded db_open_failed |
| `c4_health`（内联） | health 形状 | 正常分支缺 versions/drafts |

### 7.1 关键输出（原文摘录）

```text
# c4_schema_v08.py
wb._schema_current after drop column: True
schema_report after drop column: {'chapter_drafts': ['draft_epoch']}
1 v08 PUT draft after column drop: 500 {"code":"internal_error",
   "message":"服务内部错误：table chapter_drafts has no column named draft_epoch"}
1 schema after: {'chapter_drafts': ['draft_epoch']}

# c4_api_probe.py
A db before annotations GET: False
A GET annotations: 200 db after: True size: 237568
A tables after: 29
B GET previews after drop: 500 {"code":"internal_error",
   "message":"服务内部错误：no such table: preview_index"}
B GET world-state (v09 guard) after drop: 200
3 read-only GET annotations: 500 {"code":"internal_error",
   "message":"服务内部错误：unable to open database file"}
D v09 claim max_slots object: 500 {"code":"internal_error",
   "message":"服务内部错误：int() argument must be a string, ... not 'dict'"}

# p9
held running: ['t-fail']
after fail(): {'state':'pending','hold_requested':False,'hold_amendment_id':'amd_A'}
claim while amendment held: t-fail amd_A
claim after held lease expiry: t-expire {'state':'running','hold_requested':True,'hold_amendment_id':'amd_B'}

# p17
recover: [('t-recovery','recovery_required',True)]
after hold: {'state':'held','committing':True,'lease_owner':None,'hold_amendment_id':'amd-1'}
after release: {'state':'pending','committing':True,'lease_owner':None}
re-claim: t-recovery

# p25
hold_requested: ['t']
begin_commit while hold_requested: True
complete while hold_requested: completed

# p30
active_only sees deferred: []
after resume_due: deferred resumed: False
second daily admitted while deferred: queued

# c4_pause_probe.py
pause with identity: 200 {... 'paused': True ...}
resume without identity: 200 {'status':'resumed', 'paused': False, ...}
global file paused: False
project_paused after global resume: True
run job after global resume (project row remains): 409 {'code':'conflict',
   'message':'该作品已暂停自动化，请恢复后再执行'}

# c4_lock_probe.py
A diagnostics held levels: [8]
A chapter lock acquired while diagnostics held: True
B diagnostics acquired while bare chapter lock held: True
C safety.file_lock inside wb.write_tx: acquired (rule not enforced)
D lock_manager.hold inside write_tx raised: SqliteNestingError os_lock_inside_sqlite_tx

# c4_agent_probe.py
amend with v09 id: 409 {"code":"amendment_task_mismatch","missing":["v09-task"],"foreign":[]}
resume directive: 200 {"status":"running","released_tasks":0,...}
v09 task after resume: pending hold: None

# c4_quality_probe.py
full chapters: 3 reviewed: 2 plot avg: 73.67
page limit=1 reviewed: 1 plot avg: 90.0 returned: 1
state search hits: [(1, '正文:1')]
context L5 items: []
force='false' string: third auto review accepted (bool truthiness)

# c4_retention
gc removed: ['.../.webnovel/history/old.bin']
db rows after gc: {'task_events': 500, 'drafts_history': 50,
                   'context_manifests': 1, 'idempotency_keys': 0}

# c4_pk
schema current with task_pauses lacking PK: True
paused rows: [{'scope': 'global', 'reason': 'a', ...},
              {'scope': 'global', 'reason': 'b', ...}]

# c4_block2
up state: failed
claim down: None
snapshot reason: [{'task_id': 'up', 'reason': 'failed'}]
down state: pending
```

### 7.2 基线

```text
PATH=... python -m unittest discover -s backend/manager -t backend
Ran 235 tests in 87.646s
OK

PATH=... python -m unittest discover -s backend/integration -t backend
Ran 1270 tests in 86.415s
OK (skipped=9)
```

## 8. 未覆盖/边界

- **B/D 域与 Node 代理未逐行复审**：C-10/C-11/C-40/C-41/C-42/C-44 只做交叉引用；`index.js` 只检查 `WRITE_ROUTES` 与 C-47 相关路径，没有重新审计 SSE/代理/body limit 全链路。
- **真实模型/真实番茄发布未调用**：C3-01 的“未接线”是静态代码证明；C3-02 的路径修复用真实 FastAPI/文件系统验证了“任意目标 400 / 默认目标 200”，但没有在真实配对设备上复现网络层。
- **Windows/macOS 文件锁行为未在本机执行**：`msvcrt` 路径、只读 ACL、Windows 长路径可能改变 C3-04/C3-05 的表现；CI 结果不能替代本机。
- **GC 的 DB 表 retention**：C3-25 用 500 行 `task_events`/50 行 `drafts_history` 证明 GC 不删 DB 行，但没有构造长时间运行的增长曲线。
- **`agent_tasks`/`task_queue` 的真实 worker**：仓库没有 v0.9 worker，C3-13/C3-20 的“接线后触发”是静态+状态机探针结论；未在真实 worker 上复现。
- **多进程 SQLite 竞争**：C3-08/C3-12 用双线程/受控交错复现；C4-01 是确定性重复；没有在多进程、WAL checkpoint、Windows AV 下重复压测。
- **权限模型**：C3-02 的 LAN 修复未在真实反向代理/防火墙组合下验证；`--lan` 的设备配对只做了 API 层。
- **读路径 DB 错误 fail-open**：`world_state._ensure_readable`/`quality._ensure_readable`/`concurrent_engine._ensure` 把 `sqlite3.Error` 降级为空数据；本轮只验证了只读/缺库场景，没有在损坏 DB 下逐接口记录 200 空 vs 500 的差异。

## 9. 建议修复顺序

### 合并/发布前（P1）
1. **C3-01**：产品决策——把 world facts/quality/queue 接进 `writer_runner`/`worker.py`，或在 UI/文档明确 `advisory only` 并删除“主路径约束”宣称。

### 本周期（P2，按数据/并发优先）
2. **C3-03R/C3-04R**：先把 schema 检查统一到 `wb.initialize`（全量表/列），再给 v0.8/v0.8.5 guard 接入；同时把 `wb.connect(readonly=True)` 改成真正的 `mode=ro`，修 annotations/previews 的建库与只读 500。
3. **C3-13R**：在任何 worker 接线前修 hold 状态机（`_ready`/`begin_commit`/`complete`/`fail`/`recover`/`hold_for_amendment`/`release_amendment`）。
4. **C3-05R/C3-06R**：诊断锁移出项目；GC 明确证据保留策略；接 `register_artifact` 或删除引用计数。
5. **C3-17R/C3-18R**：统一 active 状态集合，`deferred` 纳入 `active_only`/`resume_due`/`Operations.__init__`，并让项目互斥覆盖。
6. **C3-19R/C3-20R**：章级/批注/发布接入 `lock_manager`；两套任务队列合一或事务性同步。
7. **C3-23R**：暂停/恢复单点状态机；全局恢复清项目行；`resume_due` 走 admission；`global_paused`/`project_paused` fail-closed。
8. **C4-01**：显式 `fact_id` 的逻辑键去重。

### 下一版本（P3）
9. **C3-21R..C3-27R、C4-02..C4-05**：错误码/响应形状/保留策略/唤醒路径/dashboard 聚合/布尔类型/schema 约束保真/failed blocker 策略/读路径 DB 故障降级。

---

AUDIT_STATUS: DONE
