# C 域独立全量审计（第三轮）

- 仓库/工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v3/head-c`，detached HEAD `4f5a5a1`（含 `ca019c7`/`84760a7`/`11e8887` 修复链）
- 审计范围：`backend/manager/app.py`、`api_v08.py`、`api_v085.py`、`api_v09.py`；`backend/integration/{concurrent_engine,lock_manager,maintenance,world_state,quality}.py`；以及 `workbench_db.py`、`agent_hub.py`/`agent_room.py` 的 C 边界、`transaction_journal.py` 的备份/导出路径、`publication_safety.py` 的规则豁免读取、`index.js` 的 `WRITE_ROUTES`。
- 方式：只读工作树 + 独立探针。未修改仓库受版本控制文件，未联网，未 commit/push。所有脚本与输出在 `/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-c/`。
- 时间：2026-11-27（CST）。Python：`/home/ubuntu/venvs/dsh/bin/python`（3.12.3）。
- 基线：审计前后 `git status` 仅剩审计前已存在的未跟踪 `node_modules`；无仓库改动。

## 0. 结论

**本轮未发现新的 P0。发现 2 条 P1、18 条 P2、7 条 P3（共 27 条）。** 其中 C-01/C-02/C-03/C-05/C-06/C-07 等上一轮 P0/P1 的核心修复经探针/测试确认有效；但上一轮明确保留的 **C-15（世界状态/质量/队列未接入真实生成与发布）仍然存在**，并且 v0.9 的 `task_queue` 与 v0.85 的 `agent_tasks` 是两套互不相通的队列，改令挂起链路在生产上没有生产者/消费者。新增的两条最值得优先处理：

1. **C3-02（P1，LAN/配对模式；本机 P2）**：`/api/projects/{id}/backup` 与 `/rollback/export-legacy` 仍接受客户端 `destination`，任意空目录会被创建并把正文、`manager.sqlite3`、`costs.sqlite3` 复制过去；`--lan` + 可信私网/已配对设备可把整本书和账本写到任意可写位置。C-14 只修了 diagnostics zip，未修同类的两个旧导出接口。
2. **C3-01（P1，已知未闭环）**：`writer_runner`/`worker.py`/`skill_executor.py` 对 `world_state`、`quality.review`、`task_queue`、`context_manifests` 的引用为 0；`build_context(persist=True)`/`latest_manifest()` 无生产调用；`/tasks/claim` 只有 API 自己调用；`agent_room.create_task` 只有测试调用。世界事实、质量体检、上下文 manifest、并发队列对真实写作仍不产生约束。

此外，Schema 自愈、只读项目读接口、诊断 GC/export 的项目内写锁、世界窗口确认/去重/权威比较、租约 `begin_commit`/`fail` 竞态、改令挂起状态机、`submit(task_id)` 忽略 payload、`blocked_by` 未校验、`set_card` 局部更新丢内容、`deferred` 操作永不恢复、项目互斥漏掉 publish/stage/polish 等，都是可在当前代码上复现的事务/锁/暂停/路由问题（详见 §3）。

## 1. 统计与严重度口径

| 级别 | 数量 | 含义 |
|---|---:|---|
| P0 | 0 | 本轮无新的不可逆数据丢失/主路径全断 |
| P1 | 2 | 跨作品数据外泄原语（LAN）；核心平台层未接线（产品决策未闭环） |
| P2 | 18 | 事务/锁/租约/暂停/世界窗口/路由的可复现缺陷，或已承认残余 |
| P3 | 7 | 健壮性、错误码、响应形状、死代码/保留策略 |

> 严重度沿用上一轮口径：C-14 的“本机 P2、LAN/配对 P1”同样适用于 C3-02；C3-01 沿用 C-15 的 P1，因为修复需要产品决策而不是局部代码。

## 2. P1

### C3-01 [P1] v0.9 平台层仍是旁路 API：世界状态/质量/队列/manifest 未进入真实生成与发布（C-15 未闭环）

- **位置**：
  - `backend/integration/writer_runner.py:155-157,543-550`（质量判断只走 `quality_gate`；`writer_runner` 发布走 `chapter_versions.commit_raw_bytes`：`writer_runner.py:1242-1262`）
  - `backend/manager/worker.py:110-170`（worker 只调用 `studio`/`writer_runner`/`bridge`/`scheduler`，无世界状态/质量/队列）
  - `backend/integration/world_state.py:429-516`（`build_context(persist=...)`；`latest_manifest` 533-543）
  - `backend/manager/api_v09.py:47-50,108-113,172-176,299-323`
- **机制**：
  - `writer_runner` 的审稿/发布门禁使用 `quality_gate`（旧质量体系），不读 `quality_reviews`；v0.9 `quality.review` 只由 `/quality/{chapter}/review` API 调用。
  - 生成 prompt 组装没有任何 `facts_for_chapter`/`build_context` 调用；`world_facts` 只服务 `/world-state` 仪表盘。
  - `build_context(persist=True)` 生产零调用；`latest_manifest()` 生产零调用，`context_manifests` 永远为空。
  - `task_queue` 的生产者只有 `/api/.../tasks` POST；消费者只有 `/tasks/claim`（API 自身）。仓库没有任何 worker 进程轮询 `claim`。
  - **唯一例外**是 `world_state.add_exemption` 写入的 `directive_exemptions` 会被 `publication_safety._scoped_decisions`（`publication_safety.py:153-200`）读取，作为发布门禁的规则豁免；世界事实、质量、manifest、队列仍未接线。
  - `agent_room.create_task`（`agent_room.py:305`）只有测试调用，`agent_tasks` 在真实流程中没有生产者；`agent_hub.start_amendment` 因此只能对测试数据生效。
- **影响**：作者在世界状态面板看到的事实、冲突、质量分、上下文 manifest、队列状态，对真实写作/发布没有约束力；C-15 期间承诺的“世界状态/质量/租约进入主路径”没有发生。所有 C 域队列/改令/质量相关的“正确性”目前只对 API 沙盒成立。
- **证据（静态，命令+输出）**：
  ```bash
  cd .../head-c
  grep -rn "world_state\|facts_for_chapter\|build_context\|quality\.review\|task_queue\|concurrent_engine" \
    backend/integration/writer_runner.py backend/manager/worker.py \
    backend/webnovel-writer/backend/services/skill_executor.py
  # （无输出）
  grep -rn "concurrent_engine.claim" backend --include=*.py | grep -v test_
  # backend/manager/api_v09.py:207: item = concurrent_engine.claim(...)
  grep -rn "create_task(" backend --include=*.py | grep -v asyncio | grep -v test_ | grep -v "def "
  # （无输出）
  grep -rn "build_context(" backend --include=*.py | grep -v "def build_context" | grep -v test_
  # api_v09.py:111 persist=False; world_state.py:522 persist=False
  grep -rn "latest_manifest" backend --include=*.py | grep -v "def " | grep -v test_
  # （无输出）
  grep -rn "hold_for_amendment" backend --include=*.py | grep -v "def " | grep -v test_
  # （无输出）
  ```
- **最小修复（产品决策二选一）**：
  1. 接线：在 `ops.start("generate"/"polish"/"batch")` 的 prompt 组装前调用 `build_context(persist=True)`；发布门禁读取 `quality_reviews` + `facts_for_chapter`；把 `task_queue` 交给一个真实 worker 消费，并在 worker 中调用 `hold_for_amendment`/`release_amendment`；或
  2. 明确降级：在 UI/文档把这些模块标为 `advisory only`，并删除“并发队列/租约/世界状态约束主路径”的对外宣称；不能让“测试全绿”继续充当已接线证据。

### C3-02 [P1 LAN / P2 本机] backup / export-legacy 接受任意客户端目标路径，复制正文与账本数据库

- **位置**：
  - `backend/manager/api_v08.py:246-256`（`POST .../backup`：`target = body.get("destination")`，`Path(target).expanduser()`，`extra=[manager.sqlite3, costs.sqlite3]`）
  - `backend/manager/api_v08.py:258-267`（`POST .../rollback/export-legacy`：`destination`、`snapshot_dir` 均来自 body）
  - `backend/integration/transaction_journal.py:1333-1354`（`backup`：仅校验“不在当前项目内、目标为空”，随后 `dest.mkdir(parents=True)`，复制 `正文/大纲/设定`、版本对象、workbench DB 与 `extra_sqlite`）
  - `backend/integration/transaction_journal.py:1794-1844`（`export_legacy`：同样 `dest.mkdir` 并按白名单复制正文/大纲/设定/版本）
- **机制**：C-14 只把 diagnostics 导出改成固定 `data_dir/diagnostics` + `allowed_dir`；这两个旧接口仍把 body 中的路径当目标。`backup` 对 `manager.sqlite3`/`costs.sqlite3` 走 SQLite 在线备份，导出为 `db/01-extra-00-manager.sqlite3` 等；`export_legacy` 的 `snapshot_dir` 还是任意读源。
- **影响**：`--lan` 且 `pairing_required=False`（默认的“私网可信”模式）或任一已配对设备，只要能带 `X-Novel-Helper: 1`，即可让桌面端在任意可写位置创建空目录并写入整本书、版本对象、manager/costs 数据库；这是任意写 + 正文/账本外泄原语。本机单用户模式为 P2，LAN/配对模式与 C-14 同评级 P1。`snapshot_dir` 还允许从任意目录读取 `正文/大纲/设定` 再写到目标。
- **证据（真实 FastAPI 探针）**：
  ```bash
  PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
    /home/ubuntu/venvs/dsh/bin/python -B -X utf8 \
    /home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-c/p21_export_destination.py
  ```
  ```text
  backup: 200
  backup files: ['.webnovel/chapter_versions/index.json', ..., 'db/00-workbench.sqlite3',
                 'db/01-extra-00-manager.sqlite3', 'db/02-extra-01-costs.sqlite3',
                 '正文/第1章-开端.md']
  manuscript copied: True
  manager db copied: True
  export-legacy: 200
  legacy files: ['.webnovel/chapter_versions/index.json', ..., '正文/第1章-开端.md']
  ```
  目标 `.../run/p21/exfil/deep/backup` 原本不存在，接口自行创建了多级目录。
- **最小修复**：与 diagnostics 一致，忽略客户端路径，固定写 `data_dir/backups/<generated>` / `data_dir/exports/<generated>`；如必须允许自定义，增加 `allowed_dir` 参数并在 `Maintenance`/`transaction_journal` 层做 `resolve()` 后 `is_relative_to` 校验，同时拒绝 `snapshot_dir` 指向项目外；LAN 模式建议再加独立的导出确认令牌。

## 3. P2

### C3-03 [P2] Schema 自愈只检查 9 张表/1 个列；`health` 仍报 ok，多个 API 500

- **位置**：
  - `backend/integration/workbench_db.py:50-52`（`_REQUIRED_TABLES` 只有 9 张表）
  - `backend/integration/workbench_db.py:545-557`（`_schema_current`：版本号 + 9 表 + 仅 `task_queue.hold_requested` 列）
  - `backend/integration/workbench_db.py:560-569`（`_migrate_columns` 只补这一列）
  - `backend/integration/workbench_db.py:588-610`（`initialize` 只在 `_schema_current()` 为 false 时才 `_apply_schema`）
  - `backend/integration/maintenance.py:227-299`（`health` 不检查 schema 完整性）
  - `backend/manager/api_v09.py:272-277`（`pause` 直接 INSERT `task_pauses`）
  - `backend/integration/world_state.py:683-688`（`add_exemption` 直接 INSERT `directive_exemptions`）
- **机制**：当前 `SCHEMA` 实际有约 20 张表（含 `task_pauses`、`task_events`、`context_manifests`、`conflict_ignores`、`book_directives`、`directive_exemptions`、`preview_index`、`drafts_history`、`search_docs`、`search_fts` 等），`_REQUIRED_TABLES` 只覆盖 9 张；列级检查只有 `task_queue.hold_requested`。一旦数据库被部分恢复/手工删除/旧构建写入而 9 张必需表和 `schema_version='2'` 还在，`initialize()` 直接返回，缺失表和列永远不会补；之后对应功能抛 `sqlite3.OperationalError`，`api_v09.guard` 不捕获 sqlite3 异常，最终 500 `internal_error`。`health` 也不会报告这个状态。
- **影响**：
  - `POST /tasks/pause` → 500 `no such table: task_pauses`（全局/项目暂停入口直接不可用）。
  - `POST /world/exemptions` → 500 `no such table: directive_exemptions`；`publication_safety._scoped_decisions` 的 `except Exception` 会把豁免静默当不存在，发布门禁继续拦截。
  - `quality_reviews.chapter_uid` 被删后，`quality.review` → `table quality_reviews has no column named chapter_uid`。
  - `search_fts` 被删后 `_schema_current` 仍 true，`self_heal('rebuild_search')` → `no such table: search_fts`；`chapter_editor` 的索引写入被 `except Exception` 吞掉，搜索永久为空。
  - `GET /diagnostics` 仍返回 `status: ok` / `integrity: ok`，把损坏的数据库伪装成健康。
- **证据（sqlite/API 探针）**：
  ```bash
  p1_schema.py; p1b_schema_column.py; p1c_schema_fts.py; p8_api_500.py
  ```
  ```text
  # p1
  wb._schema_current(): True
  task_pauses healed: False
  context_manifests healed: False
  pause raised: OperationalError no such table: task_pauses
  build_context raised: OperationalError no such table: context_manifests

  # p1b
  schema_current: True
  quality.review raised: OperationalError table quality_reviews has no column named chapter_uid

  # p1c
  schema_current: True
  self_heal raised: OperationalError no such table: search_fts

  # p8（真实 API）
  POST tasks/pause after drop: 500 {'code': 'internal_error', ...}
  POST world/exemptions after drop: 500 {'code': 'internal_error', ...}
  GET diagnostics: 200 ok ok
  ```
- **最小修复**：`_REQUIRED_TABLES` 补齐所有生产使用的表（含 `task_pauses`、`task_events`、`context_manifests`、`conflict_ignores`、`preview_index`、`directive_exemptions`、`search_docs`、`search_fts` 及 FTS shadow 由 SQLite 自管）；`_schema_current` 对每张表做列集合比较（期望列来自一个显式 schema 清单），缺表/缺列时 `_apply_schema` + `_migrate_columns`；`health` 增加 `schema_current` 检查并报 P0；`self_heal` 增加 `rebuild_schema`。

### C3-04 [P2] 只读项目上的读接口仍创建/写入 workbench 数据库；world/quality 直接 500

- **位置**：
  - `backend/integration/world_state.py:519-530`（`state()` → `build_context` → `chapter_uid`；`detect_conflicts` 379 同样）
  - `backend/integration/workbench_db.py:653-676`（`ensure_chapter_meta` 无行时 `INSERT`）
  - `backend/integration/workbench_db.py:613-626`（`_ensure` 在 DB 缺失时 `initialize`）
  - `backend/integration/quality.py:181-184`（`dashboard` 无条件 `wb.initialize`）
  - `backend/manager/api_v09.py:47-50,299-310`（世界状态/质量 GET）
  - 同类：`backend/integration/annotations.py:120-136`（`_current_text` → `wb.get_draft` → `_ensure`）、`api_v09.py:172-176`（`GET /tasks` → `_ensure_queue`）
- **机制**：所有“读”路径最终都调用 `wb.initialize()`/`ensure_chapter_meta()`/`_ensure()`；后者会创建 `.webnovel/workbench.sqlite3`（必要时 schema）并为请求的章号 `INSERT chapter_meta`。`world_state.state()` 在 `build_context(persist=False)` 和 `detect_conflicts()` 中都会调用 `wb.chapter_uid()`；因此即使 `persist=False`，一个 GET 也会写数据库并为不存在的章号创建永久 `chapter_meta` 行（随后 `health` 报 `orphan_chapter_index`）。
- **影响**：
  - 只读挂载/只读共享/归档书：`GET /world-state`、`GET /quality`、`GET /annotations`、`GET /tasks` 会因 `unable to open database file` 返回 500；`health` 同时报 `ok`，形成“诊断说健康、读接口全挂”。
  - 普通书：任何世界状态/质量 GET 都会在 `.webnovel` 中产生数据库文件和 `chapter_meta` 行；`?chapter=999` 会留下幽灵章号，`health` 永远多出 orphan P2。
- **证据（真实 FastAPI 探针）**：
  ```text
  # p2
  db before GET: False
  GET world-state: 200 999
  db after GET: True
  chapter_meta rows after world-state: [(999,)]
  chapter_meta rows after context: [(888,), (999,)]
  diagnostics status: ok orphan issues: [{'code': 'orphan_chapter_index', 'severity': 'P2', 'chapter': 888}, ...]

  # p14（.webnovel 0555）
  GET world-state read-only: 500 {'code': 'internal_error', 'message': '服务内部错误：unable to open database file'}
  GET quality read-only: 500 {'code': 'internal_error', 'message': '服务内部错误：unable to open database file'}
  GET diagnostics read-only: 200 ok
  ```
- **最小修复**：把“读”与“写”初始化分开：`wb.connect(..., readonly=True)`/`initialize(readonly=True)` 在 DB 或 `chapter_meta` 缺失时返回空数据而不是创建；`world_state.state`/`detect_conflicts` 不再为不存在的章号创建 uid（用 `chapter_meta` 只读查询或内容哈希作为临时键）；`quality.dashboard`/`annotations.list_*`/`list_tasks` 在只读路径走无副作用分支；`health` 增加“读接口可用性”检查（只读/schema/DB 权限）。

### C3-05 [P2] 诊断 GC/export 的项目内 OS 锁是写副作用：dry-run 也落锁文件，只读项目 500（C-R2-05）

- **位置**：
  - `backend/integration/maintenance.py:124-152`（`collect_garbage` 第一步 `lock_manager.hold(project,"diagnostics")`）
  - `backend/integration/maintenance.py:313-335`（`export_bundle` 同样）
  - `backend/integration/maintenance.py:387-397`（`self_heal` 同样）
  - `backend/integration/lock_manager.py:73-76,96-108`（锁路径 `.webnovel/locks/L8-*.lock`）
  - `backend/fanqie_auto_publish/publication_safety.py:57-90`（`file_lock` 先 `path.parent.mkdir(parents=True)` 再 `open("a+b")`）
  - `backend/manager/api_v09.py:363-378`
- **机制**：`collect_garbage(dry_run=True)` 文档是“预览”，但为了拿 diagnostics 锁，`safety.file_lock` 会在项目内创建持久 `.webnovel/locks/L8-<hash>.lock`（并 `mkdir` 父目录）。只读项目/只读 `.webnovel` 上 `mkdir/open` 抛 `PermissionError`，`lock_manager.hold` 只捕获 `PublicationBlocked`，不转换；`api_v09.guard` 也不捕获 OSError，最终 500 `internal_error` 并回显绝对路径。
- **影响**：诊断 GC（即使 dry-run）/导出/自愈在只读项目上不可用；普通项目上每本书被写入一个永不删除的 L8 锁文件；`dry_run` 的“只读”承诺不成立。C-30 的“GET/导出不产生写副作用”只覆盖了 health/ledger/export 的 DB 创建，没有覆盖 OS 锁。
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
- **最小修复**：锁根目录改到 `data_dir/locks/`（或系统临时目录），按项目路径哈希命名，避免在被审计项目内落文件；`lock_manager.hold` 把 `OSError` 转成 `LockError("lock_unavailable")`（503/409）；`collect_garbage(dry_run=True)` 在不拿写锁的情况下做只读扫描，或明确要求可写并在 UI 提示；只读项目导出走无锁只读路径（允许轻微撕裂，诊断包只含哈希/计数）。

### C3-06 [P2] GC 保护集过宽：所有 snapshots/revision_previews 永不回收；引用计数机制从未启用

- **位置**：
  - `backend/integration/maintenance.py:24-25`（`_PREVIEW_DIRS=("previews","preview-cache","history")`、`_EVIDENCE_DIRS=("snapshots","revision_previews")`）
  - `backend/integration/maintenance.py:66-97`（`_protected_paths` 无条件把整个 `_EVIDENCE_DIRS` 加入保护集）
  - `backend/integration/maintenance.py:100-121`（候选集完全不含 `_EVIDENCE_DIRS`）
  - `backend/integration/maintenance.py:155-169`（`register_artifact`；生产零调用）
- **机制**：C-03 修复把 `snapshots`、`revision_previews` 从候选集移出，并在 `_protected_paths` 里整目录保护；`_referenced_snapshot_ids` 的结果因此是冗余的。`register_artifact` 仍无生产调用，`artifact_refs` 永远为空。GC 实际只可能删除 `.webnovel/{previews,preview-cache,history}` 中过期文件，而这三个目录在当前代码里没有生产者（`history` 只有测试写入）。模块 docstring 说“GC 只删无引用且已过保留期的历史快照”，与实现相反。
- **影响**：未引用的旧快照/修订预览永久累积（磁盘只增不减）；真正需要回收的对象（旧 `drafts_history`、`quality_reviews`、`context_manifests`、`task_events`、`idempotency_keys`）没有保留策略；引用计数 GC 的对外宣称不成立。另一方面，当前“永不删证据”是安全的，不会重演 C-03 数据丢失。
- **证据**：
  ```text
  # p15
  artifact_refs rows: 0
  gc candidates: ['orphan.bin']
  unreferenced snapshot kept: True unreferenced revision preview kept: True legacy preview kept: True
  ```
  （测试 `test_v09_maintenance.py:23-40` 还依赖 `.webnovel/history` 这个当前无生产者的目录来证明 GC 能删东西。）
- **最小修复**：明确产品策略：
  - 若“证据永不删”：删除 `artifact_refs`/`register_artifact`/“引用计数 GC”宣称，文档改为“snapshots/revision_previews 永久保留”，并加磁盘增长监控；或
  - 若需要回收：把 `snapshots` 放回候选集，只保护 `_referenced_snapshot_ids`（`annotations.anchor_json.base_snapshot_id`/`preview_index.base_snapshot_id`），保留期外且无引用才删；`save_snapshot`/`save_preview` 调用 `register_artifact(ref_count=1)` 或直接信任 SQLite 引用集；为 DB 表增加按时间/状态的 retention（`drafts_history`、`task_events`、过期 `idempotency_keys`）。

### C3-07 [P2] 确认 pending 事实不会关闭旧窗口；显式 `fact_id` 也跳过窗口关闭

- **位置**：
  - `backend/integration/world_state.py:254-264`（`confirm_fact` 只改 `status/authority_level`）
  - `backend/integration/world_state.py:140-162`（窗口关闭只在 `upsert_fact` 且 `not fact.get("fact_id")`、`status=='active'` 时执行）
  - `backend/integration/world_state.py:87-188`（`upsert_fact` 的 explicit `fact_id` 分支不做 dedupe/close）
- **机制**：被 AI 判为高风险的候选先以 `pending_confirm` 写入；`upsert_fact` 的窗口关闭条件要求 `status=='active'`，所以 pending 时不关闭旧事实（这是 C-R2-01 的正确行为）。作者确认时 `confirm_fact` 只把新事实设为 active/提升权威，没有再执行同一 subject+predicate 的旧窗口关闭 UPDATE；于是旧事实（valid_until NULL）与新事实同时 active。另一个入口：调用方自己传 `fact_id` 创建新事实时，`not fact.get("fact_id")` 为 false，窗口关闭整段被跳过。
- **影响**：作者确认一条与旧事实冲突的推断后，`facts_for_chapter` 同时返回两条 active 事实，`detect_conflicts` 永久报冲突；L2 长期记忆可能同时注入“存活/死亡”两个相反事实。作者只能手动 `ignore_conflict` 压掉 dashboard，不能恢复窗口语义。显式 `fact_id` 的客户端（希望稳定 ID）永远得不到 C-18 的窗口关闭。
- **证据**：
  ```text
  # p4
  confirmed: active confirmed_prose
  active facts at ch5: [('old','存活','confirmed_prose',1,None), ('new','死亡','confirmed_prose',5,None)]
  conflicts: [('ent_1','生死',['存活','死亡'])]
  control old window: [('fact_...', None)]   # 直接 active 写入时旧窗口被关闭
  ```
  ```text
  # p27b_explicit_id.py
  [('old','测绘员',None), ('new','档案员',None)]
  ```
- **最小修复**：把窗口关闭逻辑抽成 `_close_previous_windows(project, fact, db)`，在 `confirm_fact` 的条件 UPDATE 成功后用同一事务调用；`upsert_fact` 的 explicit `fact_id` 分支在“fact_id 不存在且逻辑键无行”时也执行关闭；关闭比较使用真实 `AUTHORITY` 等级（见 C3-10）。

### C3-08 [P2] `upsert_fact` 的去重 SELECT 在写事务之外：并发 upsert 产生重复事实；显式 ID 完全绕过去重

- **位置**：`backend/integration/world_state.py:108-125`（dedupe SELECT 在 `with wb.connect` 中，随后 129 才 `write_tx`）；`world_state.py:106-119`（`fact_id` 存在时整段跳过）
- **机制**：两个线程/进程同时 upsert 同一逻辑事实（无 `fact_id`）时，都先在自己的读连接里执行 `SELECT fact_id ...`，都看到空；随后各自 `BEGIN IMMEDIATE` 串行写入，生成两个不同 `fact_id`。表上没有逻辑唯一约束。显式传不同 `fact_id` 时连 SELECT 都不做，重复是确定性的。
- **影响**：同一事实在 `world_facts` 出现多条 active 行；L2/冲突 dashboard 重复注入；后续 `confirm/reject/ignore` 只命中其中一条；`facts_by_status` 计数虚高。对于 AI 抽取（每章多次调用）或用户双击提交，都会放大。
- **证据（instrumented interleaving，真实 SQLite，两个线程都先 fetchone 到空再写）**：
  ```text
  # p13
  thread results: ['saved', 'saved']
  world_facts rows: [{'fact_id': 'fact_9d1bc0fd', ...}, {'fact_id': 'fact_8b2ce975', ...}]
  duplicate active facts: 2
  ```
- **最小修复**：把 dedupe SELECT 移进同一个 `write_tx`（`BEGIN IMMEDIATE` 已 serializes）；对 `(entity_id, subject, predicate, object, valid_from_chapter, valid_until_chapter, assertion_type)` 建唯一索引（注意 NULL 用表达式索引）；显式 `fact_id` 仅在“该 ID 已存在”时视为更新，否则仍按逻辑键去重。

### C3-09 [P2] 逻辑键漏掉 `assertion_type`：同键 rumor 会把 fact 覆盖成 rumor，冲突检测随之消失

- **位置**：`backend/integration/world_state.py:110-117`（dedupe 条件只有 entity/subject/predicate/object/valid_from/valid_until）；`world_state.py:163-187`（`ON CONFLICT(fact_id) DO UPDATE` 覆盖 `assertion_type`）；`world_state.py:363-372`（`detect_conflicts` 跳过 `lie/rumor/belief`）
- **机制**：`upsert_fact` 认为“同实体+谓词+宾语+有效期”就是同一逻辑事实，不看 `assertion_type` 或 `status`。AI 先写入一条 `fact`，再抽取到同键的 `rumor`（或反过来），会复用同一 `fact_id` 并把 `assertion_type` 覆盖为 rumor；`detect_conflicts` 对 rumor 不检测，于是真实矛盾从 dashboard 消失。若旧行是 `pending_confirm`，同键 active 也会被覆盖为 active（见 C3-13 相邻风险）。
- **影响**：世界事实的叙述层次被破坏；作者看到“已确认”的冲突被一条同键传闻静默降级；`status` 也可被同键写入直接改写。
- **证据**：
  ```text
  # p26
  first: fact_5cad779c fact
  second: fact_5cad779c rumor
  rows: [{'fact_id': 'fact_5cad779c', 'assertion_type': 'rumor', 'status': 'active'}]
  ```
- **最小修复**：逻辑键加入 `assertion_type`（至少 fact/rumor/lie/belief 分开）；`ON CONFLICT` 时对 `status` 做状态机校验（pending 只能由 confirm/reject 改变，不能被普通 upsert 直接改 active）；同一 ID 的更新只允许同 assertion 类型。

### C3-10 [P2] 窗口关闭的权威比较使用简化 CASE：`draft_prose`/`future_plan` 与 `ai_inferred` 同级，AI 推断可关闭草稿级事实

- **位置**：`backend/integration/world_state.py:147-162`（`CASE ? WHEN 'author_locked' 4 WHEN 'published_prose' 3 WHEN 'confirmed_prose' 2 ELSE 1 END` 与旧行同构比较；`AUTHORITY` 定义在 37-39：draft_prose=3、ai_inferred=2）
- **机制**：SQL 的 CASE 把 `draft_prose`、`future_plan`、`discarded_candidate`、`ai_inferred` 全部映射为 1，破坏了 `AUTHORITY` 的实际顺序。新写入 `ai_inferred`（1）与旧 `draft_prose`（1）比较为 `1>=1`，于是关闭旧窗口，尽管 `AUTHORITY` 认为 3>2，且 docstring 声称“lower-authority inference never overwrites a higher-authority row”。
- **影响**：AI 抽取可以关闭作者的草稿级/未来计划事实窗口；旧事实从 `facts_for_chapter` 消失，L2 只留下 AI 推断。与 C-R2-01 的保护目标（pending AI 不得关闭已确认事实）相邻，但这里是 draft_prose 级别。
- **证据**：
  ```text
  # p27
  active at ch5: [('fact_464d5e4d', '档案员', 'ai_inferred', None)]
  ```
  （旧 `draft_prose` 的“测绘员”窗口已被关闭，valid_until 不再为 NULL，fact 不出现在 ch5。）
- **最小修复**：窗口关闭的权威等级直接由 `AUTHORITY` 映射（Python 计算后在 SQL 参数里传 rank，或 SQL CASE 覆盖全部级别），并要求 `new_rank > old_rank` 才能关闭（同 rank 仅允许同 assertion 的新值，按产品定义）；`draft_prose` 至少应高于 `ai_inferred`。

### C3-11 [P2] `begin_commit` 接受已过期租约：zombie worker 可把任务重新锁 300 秒

- **位置**：`backend/integration/concurrent_engine.py:373-390`（`begin_commit` 只检查 `state`/`lease_owner`，UPDATE 不校验 `lease_expires`）；对照 `renew` 345-370 明确要求 `lease_expires >= now`
- **机制**：worker 在 `LEASE_SECONDS=30s` 内未提交、租约已过期但还没被其他 `claim()` 的 `recover()` 处理时，调用 `begin_commit` 仍会成功，并把 `lease_expires` 设为 `now+300s`、`committing=1`。`renew()` 在同样状态下会抛 `recovery_required`。
- **影响**：一个停顿超过 30 秒的 worker 可以“复活”任务并阻止其他 worker 回收；如果它实际已失去执行上下文（例如被系统挂起/网络卡住），会造成长时间假 running。与 pause/改令组合时，过期 worker 仍可进入提交阶段。
- **证据**：
  ```text
  # p6
  expired before calls: True
  begin_commit on expired lease: running committing: True new_expiry_minus_now: 300.0
  renew on expired lease raised: SchedulerError recovery_required
  second state: recovery_required
  ```
- **最小修复**：`begin_commit` 的 UPDATE 增加 `AND (lease_expires IS NULL OR lease_expires >= ?)`；若不满足，先 `_mark_recovery` 并抛 `recovery_required`，与 `renew` 一致；或者显式允许“过期但 owner 仍存活”需要单独配置的 grace 并记录事件。

### C3-12 [P2] `fail()` 的 owner 校验在 UPDATE 之外（TOCTOU）：旧 worker 可清掉新 worker 的租约

- **位置**：`backend/integration/concurrent_engine.py:426-445`（`get` 后检查 `lease_owner`，UPDATE 只按 `state IN ('running','committing')`，没有 `lease_owner=?`）；对照 `complete` 415-421、`renew` 353-358、`begin_commit` 383-386 都带 owner
- **机制**：`fail` 先读任务并比对 `lease_owner`，再开启写事务更新。若在读和写之间租约过期、`recover()` 把任务放回 pending、另一个 worker `claim()` 成 running（新 owner），旧 worker 的 UPDATE 仍会匹配 `state='running'`，把新 worker 的 lease 清空并改成 pending/failed；新 worker 随后 `complete` 得到 409。
- **影响**：任务被重复执行/计费；新 worker 的正常运行被旧 worker 的迟到失败打断；`attempts` 计数不具备真实语义。窗口小但真实，尤其在 30s 租约 + 大章节提交/网络抖动时。
- **证据（instrumented 读取，模拟读后重领）**：
  ```text
  # p7
  before fail: running worker-new attempts: 1
  fail result: pending None attempts: 1
  after fail: pending None attempts: 1
  worker-new complete raised: SchedulerError task_not_running
  ```
- **最小修复**：`fail` 的 UPDATE 加 `AND lease_owner=?`（owner 为空时拒绝或要求显式 `owner=""` 的恢复通道）；若 `rowcount=0`，重新 `get` 并按当前状态返回 409/已恢复；同样建议 `_mark_recovery` 的调用方都带 owner。

### C3-13 [P2，潜在；接线前必修] 改令挂起状态机不闭环：running hold 不阻止提交，pending/recovery 可被 claim 绕过，release 可把 recovery_required 洗成 pending

- **位置**：
  - `concurrent_engine.py:485-526`（`hold_for_amendment`：running 只设 `hold_requested=1`；非 running 除 completed/cancelled/failed 外一律可设 held，包括 `recovery_required`）
  - `concurrent_engine.py:296-306`（`_ready` 只检查 `state=='pending'` + `blocked_by` + `_task_paused`，不看 `hold_requested`/`hold_amendment_id`）
  - `concurrent_engine.py:426-445`（`fail` 清 `hold_requested` 但不清 `hold_amendment_id`）
  - `concurrent_engine.py:448-482`（`recover` 把过期任务改 pending，保留 `hold_requested`/`hold_amendment_id`）
  - `concurrent_engine.py:542-562`（`release_amendment` 把 held 改 pending，不清 `committing`）
  - `concurrent_engine.py:373-390,409-423`（`begin_commit`/`complete` 不看 hold 标志）
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
  after hold: {'state':'held','committing':True,'lease_owner':None,...}
  after release: {'state':'pending','committing':True,'lease_owner':None}
  re-claim: t-recovery

  # p25
  hold_requested: ['t']
  begin_commit while hold_requested: True
  complete while hold_requested: completed
  ```
- **最小修复**：
  - `_ready`：`hold_requested=1` 或 `hold_amendment_id` 非空时不可领取（除非有显式 release）；
  - `fail`/`recover`：保留/重设 hold 标志，不要清 `hold_requested` 或 `hold_amendment_id`；若任务失败需要离开改令，走 `release_amendment`；
  - `hold_for_amendment`：只处理 `pending`/`held`/`running`，`recovery_required`/`failed`/`interrupted` 原样跳过；
  - `release_amendment`：held→pending 时同时 `committing=0`，并只在 `hold_amendment_id` 仍是本改令时更新；
  - `begin_commit`/`complete`：`hold_requested=1` 或 `hold_amendment_id` 非空且未 release 时返回 409（或 `hold_pending`）。

### C3-14 [P2] `submit(task_id=...)` 静默忽略新 payload/priority/chapter（C-R2-06）

- **位置**：`backend/integration/concurrent_engine.py:96-104`（`task_id` 存在时直接 `return {**get(...), "deduplicated": True}`）；`backend/manager/api_v09.py:178-201`（body 校验但不比对）
- **机制**：调用方用同一 `task_id` 重试，但 payload、priority、chapter_id、parent、blocked_by、amendment_fallback 全部不比较；服务端返回旧任务并标记 `deduplicated: true`。`submit` 没有 `params_hash` 或幂等键（`idempotency_keys` 也未接入）。
- **影响**：客户端“用稳定 ID 重试/更新任务”时新意图被静默丢弃；例如把同一 ID 从“存稿”改成“发布”、从 P2 改成 P0，实际仍执行旧任务；用户看到 200，误以为已更新。与 C-36 的“事件失败不 500”叠加后，没有任何冲突信号。
- **证据**：
  ```text
  # p5
  first : fixed-id P1 1 {'intent':'draft','chapter':1}
  second: fixed-id P1 1 {'intent':'draft','chapter':1} True
  same row: True payload preserved: True new priority lost: True
  ```
- **最小修复**：对 `priority/chapter_id/parent_task_id/blocked_by/payload` 计算 `params_hash`，与已有任务比较；不同则 409 `task_id_payload_mismatch`（或 `task_already_submitted` 并返回差异），相同才 dedup；将 `idempotency_keys` 的 `(actor, project, action, op_id)` 接入 submit。

### C3-15 [P2] `blocked_by` 不校验存在/自引用/环：任务永久 pending，`claim()` 静默返回 None

- **位置**：`backend/integration/concurrent_engine.py:90-95`（只校验类型/非空）；`concurrent_engine.py:296-306`（`_ready` 对缺失 blocker 直接 `return False`）；`backend/manager/api_v09.py:185-191`
- **机制**：`submit` 接受任意字符串列表；`_ready` 遍历 blocker，`get()` 找不到就返回 False；自引用/两节点环同样永远不满足。没有环检测，没有“blocker failed”策略，也没有诊断接口告诉作者为什么 pending。
- **影响**：一个拼写错误、自引用或环会让任务永久 pending；`claim` 返回 None（API 200 `{"task": null}`），作者看不出原因；失败的上游任务（`failed`）也会永久阻塞下游（`_ready` 只接受 completed/cancelled）。在没有 worker 的当前状态更是“静默卡住”。
- **证据**：
  ```text
  # p18
  submit with missing blocker: pending ['no-such-task']
  claim missing-blocker task: None
  submit self-cycle: pending ['t-self']
  claim self-cycle task: None
  claim 2-cycle task: None
  ```
- **最小修复**：submit 时批量查询 blockers 是否存在、不是自身，并对新增边做 DFS/拓扑环检测（可用内存图）；对 failed blocker 定义策略（fail/cancel 子任务或要求作者显式解除）；`claim`/`snapshot` 返回 `blocked_reason`（missing/failed/cycle）而不是只给 None。

### C3-16 [P2] `set_card` 局部更新只保留 pinned：改名会清空 card_md/aliases/kind/story_time

- **位置**：`backend/integration/world_state.py:276-300`（`kind=str(card.get("kind") or "character")`、`aliases=list(card.get("aliases") or [])`、`card_md=str(card.get("card_md") or "")`、`story_time=card.get("story_time")`；只有 `pinned` 在 288-291 做了 existing 兜底）
- **机制**：C-16 只修了 `pinned` 的“未传就保留”；其他字段仍用默认值覆盖。一个只带 `entity_id`+`name` 的改名/置顶请求会把既有 `card_md`、别名、kind、story_time 全部重置。
- **影响**：人物卡正文（作者内容）在一次改名/置顶 API 调用后丢失；`list_cards`/L2 上下文立刻变成空卡。当前没有前端写卡入口，但 API 已暴露，且 C-16 的“局部更新”语义只完成了一半。
- **证据**：
  ```text
  # p19
  first: {'name':'林溪','kind':'character','aliases':['小溪'],'pinned':True,
          'story_time':'第一年','card_md':'女主，测绘员，怕水。'}
  rename-only: {'name':'林溪（改名）','kind':'character','aliases':[],'pinned':True,
                'story_time':None,'card_md':''}
  ```
- **最小修复**：按“字段是否出现在请求中”构造 UPDATE；未出现则保留 existing 值；显式 `null`/空字符串作为清空语义（需要 API 文档区分“缺省”和“清空”）；`kind` 对已存在行不要用默认值覆盖。

### C3-17 [P2] `status='deferred'` 是死状态：active 过滤和 `resume_due` 都不认识它，且不再阻塞项目互斥

- **位置**：
  - `backend/manager/app.py:513-518`（`_execute`：`child_status=='waiting'` 且不是 generate+batch+两种 failure_kind 时写 `status='deferred'`，提示“调度器将继续原批次”）
  - `backend/manager/app.py:123-127`（`Store.operations(active_only=True)` 只认 `queued/running/awaiting_login/waiting`）
  - `backend/manager/app.py:351-402`（`resume_due` 只处理 `status=='waiting'`）
  - `backend/manager/app.py:202-205`（启动时只把 `queued/running/awaiting_login` 标 interrupted，`deferred` 跨重启保留）
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

### C3-18 [P2] 项目互斥只覆盖 generate/daily：publish/stage/polish 可与日更同时启动

- **位置**：`backend/manager/app.py:269-271`（同一 identity 检查）；`app.py:273-301`（`if kind in {"generate","daily"}` 才做 project_id 互斥）；`app.py:296-301`
- **机制**：daily 的 identity 是 `job:<id>`，publish/stage/polish 的 identity 是 `project:<id>`；二者的 identity 不同，且后三者不在 generate/daily 互斥块内，`_start_admitted` 直接放行。`publish`/`stage` 走 publication 队列/`writer_receipts.json`，不持有 `writer.lock`；daily 的 `studio.batch` 持有 `writer.lock`/`batch.lock` 但 publication 不参与。
- **影响**：日更正在写章节/回执时，手动 publish 可以启动并读取半更新的回执/正文，生成发布队列；stage 也可能把未完成章节当成已审查；polish 虽然会在自己的 `writer.lock` 上失败（RuntimeError → failed），但会留下一次失败操作并浪费一次 AI 调用。项目级“同一作品只跑一个写任务”的承诺不成立。
- **证据**：
  ```text
  # p28
  publish: daily=queued publish=queued workers=2
  polish: daily=queued polish=queued workers=2
  ```
- **最小修复**：把 project 互斥扩展到所有会读写 `正文`/`writer_receipts`/publication 队列的 kind（publish/stage/polish/review/generate/daily），按 `metadata.project_id` 或 `--project` 解析同一把项目锁；或在整个子进程生命周期持有项目级 `lock_manager.hold(project,"publication"...)`，而不是只在 admission 时检查。

### C3-19 [P2] C-04 章级锁统一仍未完成：`lock_manager` 只服务 maintenance，chapter/annotations/publishing 仍走裸 `safety.file_lock`

- **位置**：
  - `backend/integration/lock_manager.py:78-114`（八级锁 + SQLite 嵌套守卫）
  - `backend/integration/maintenance.py:126,334,389,393`（唯一生产调用点）
  - `backend/integration/chapter_editor.py:171,186,679,718,821,1051,1116,1230`（8 处 `safety.file_lock`）；`chapter_versions.py:420,505,690,804,862,975,1026,1101,1120,1192`；`revision_plan.py:323,386`（2 处 `file_lock`）
  - `backend/integration/annotations.py` **完全没有 `file_lock`**（快照/预览/索引写入仅靠 SQLite 事务）；`publishing.py` 也没有项目级 `file_lock`
  - `backend/manager/app.py:1310-1322`（只把 `LockError` 映射为 HTTP）
- **机制**：`lock_manager` 的级别/顺序/`note_sqlite_enter` 只被 `maintenance` 和 `workbench_db.write_tx` 使用；章级编辑/修订仍使用裸 `safety.file_lock`（不同的锁文件身份），批注/发布则完全没有项目级文件锁，因此：
  - GC/export 的 `diagnostics` 锁不会与章节/批注写互斥；
  - 裸 `safety.file_lock` 不受 `sqlite_depth` 守卫约束，理论上可以在 SQLite 写事务中申请 OS 锁（当前静态扫描未找到直接嵌套，但规则没有强制）；
  - 锁序违规（例如先 chapter_text 再 config）不会被检测。
- **影响**：C-04 的“三期并发地基”仍只覆盖维护域；诊断与编辑可交错，未来若 GC 候选集包含正文/批注共享文件会直接重演 C-03。锁序/死锁保证无法从代码上成立。
- **证据**：
  ```text
  grep -rn "lock_manager" backend --include=*.py | grep -v test_ | grep -v workbench_db.py
  # app.py:1317（仅异常映射）; maintenance.py:19,126,334,389,393

  grep -rn "safety.file_lock\|file_lock(" backend/integration/{chapter_editor,annotations,revision_plan,publishing}.py | wc -l
  # 10
  ```
- **最小修复**：保留 `safety.file_lock` 的兼容身份，但在其上加 `lock_manager` 的级别/顺序登记（或提供 `hold_compat(project, level, path)`）；至少把 diagnostics 与 chapter_text/derived_index/publication 接入同一级别表；GC 的 protected/candidate 计算必须持有与编辑共享的锁（或明确 GC 只处理无生产者的 legacy 目录）。

### C3-20 [P2] `agent_hub` 的 held 语义仍是另一套死队列：`create_task` 无生产调用，`hold_for_amendment` 无调用，`amend` 无法引用 `task_queue`（C-R2-07）

- **位置**：
  - `backend/integration/agent_room.py:305-321`（`create_task`：`INSERT INTO agent_tasks`；全仓只有测试调用）
  - `backend/integration/agent_hub.py:306-366`（`start_amendment` 只更新 `agent_tasks`；任务缺失/跨指令时 409 `amendment_task_mismatch`）
  - `backend/integration/agent_hub.py:369-447`（`evaluate_amendment` 只处理 `agent_tasks`）
  - `backend/integration/agent_hub.py:486-504`（`resume_directive` 只释放 `agent_tasks`）
  - `backend/integration/concurrent_engine.py:485-562`（`hold_for_amendment`/`release_amendment` 无生产调用）
  - `backend/manager/api_v085.py:262-312`（`amend/evaluate/release/resume` 路由）
- **机制**：v0.85 的 `agent_directives`/`agent_tasks` 与 v0.9 的 `task_queue` 是两张表、两套 ID、两套状态机。`create_task` 没有生产调用者（`create_directive` 不会自动生成任务），所以 `agent_tasks` 在真实流程中为空；`amend` 带 v0.9 `task_queue` ID 会 `amendment_task_mismatch`，不带 task_ids 则改令只 bump revision、没有任务可影响。`concurrent_engine.hold_for_amendment` 也没有调用者，v0.9 队列的 `hold_amendment_id` 只能靠 `submit(parent_task_id)` 继承一个永远不会出现的父任务。
- **影响**：C-13 的“改令评估→放行/重做”在真实流程中不可达；POST resume 只改 directive 状态，不会释放任何 v0.9 任务；作者以为改令生效，实际任务继续按旧计划执行（或根本没有任务）。与 C3-01 一样是平台层未接线的直接证据。
- **证据**：
  ```text
  grep -rn "create_task(" backend --include=*.py | grep -v asyncio | grep -v test_ | grep -v "def "
  # （无输出）
  grep -rn "hold_for_amendment" backend --include=*.py | grep -v "def " | grep -v test_
  # （无输出）
  ```
  `test_v085_api.py:177` 是唯一 `agent_room.create_task` 调用点，属测试数据。
- **最小修复**：二选一：
  1. 废弃 `agent_tasks`，让 `agent_hub` 直接操作 `task_queue`（增加 `directive_id`/`agent_role` 列，`hold_for_amendment` 成为唯一 hold 入口）；
  2. 保留两套，但在 `create_directive`/任务规划时真正创建 `agent_tasks`，并在 `task_queue` 增加 `directive_id` 外键，`amend/evaluate/release` 事务性同步两表；补一个实际 worker 消费。
  在完成前，文档/UI 不应宣称改令可用。

## 4. P3

### C3-21 [P3] `confirm_fact` 允许把 pending 事实“确认”成更低权威 `ai_inferred`

- **位置**：`world_state.py:254-264`；`api_v09.py:72-77`（body 可传任意 `authority_level`）
- **机制**：只校验 `authority_level in AUTHORITY` 且不是 future/discarded；`ai_inferred` 合法。确认后 `status='active'`、`authority_level='ai_inferred'`；L2 只收 pinned/confirmed/published/author_locked，因此该事实从长期记忆层消失。
- **证据**：
  ```text
  # p20
  after confirm: active ai_inferred
  fact in L2: False L2 ids: []
  ```
- **最小修复**：确认只接受严格更高的权威（`AUTHORITY[new] > AUTHORITY[old]`，author_locked 特判），默认 confirmed_prose；若需要“确认但不提升”，提供独立 `accept_as_is` 语义并明确 UI。

### C3-22 [P3] API 手写 `int()/float()` 对 JSON object 无兜底：v08/v09 返回 500 而非 422

- **位置**：`api_v08.py:123-129`（`offset=int(body.get("offset") or 0)`）；`api_v08.py:136-144`（`start_chapter` 传入 `chapter_editor.import_preview` 后 `int(dict)`）；`api_v09.py:205-212`（`max_slots=int(...)`/`max_attempts`）、`api_v09.py:333-350`（`min_age_seconds`）、`api_v09.py:141-145`（`chapter=int(...)`）
- **机制**：v08/v09 的 `guard` 不捕获 `TypeError`（v085 已捕获）；`int(dict)` 抛 TypeError，落到 app 的 `unhandled_handler` → 500 `internal_error`，并回显内部异常文本。
- **证据**：
  ```text
  # p24
  v08 split offset object: 500 {'code':'internal_error', ...}
  v08 import start object: 500 {'code':'internal_error', ...}
  v09 claim max_slots object: 500 {'code':'internal_error', ...}
  ```
- **最小修复**：v08/v09 的 `guard` 增加 `(TypeError, ValueError, KeyError)` → 400 `invalid_request`；或把这些 body 改成 Pydantic 模型（推荐），让 FastAPI 统一 422。

### C3-23 [P3] 暂停入口的四个边角：`resume_due` 不看全局暂停、`global_paused` 失败开放、`system_ai_pause` 先写文件后校验、全局恢复不清项目 global 行

- **位置**：
  - `backend/manager/app.py:351-402`（`resume_due` 只检查 `project_paused`，无 `global_paused`；由 `dispatch` 1173-1183 在调用前检查，存在 check→spawn 的 TOCTOU）
  - `backend/integration/concurrent_engine.py:180-188`（`global_paused` 对任何异常 `return False`，损坏/不可读的暂停文件按“未暂停”处理）
  - `backend/manager/api_v09.py:255-270`（`system_ai_pause` 先 `set_global_pause`，后 `_book(identity)`/`pause(book,"global")`；identity 不存在时 404 但全局文件已写）
  - `backend/manager/api_v09.py:263-269`（带 identity 的暂停会写项目 `global` 行；不带 identity 的恢复只删全局文件）
- **影响**：全局急停文件损坏/不可读时自动化会继续；`resume_due` 的 check→thread 窗口内设置急停仍会 spawn 一个批次；错误 identity 的暂停请求返回 404 却把全站停掉，错误 identity 的恢复请求返回 404 却把全站恢复；全局恢复后项目仍被自己的 `global` 行挡住。
- **证据**：
  ```text
  # p10
  after resume_due during global pause: status = queued worker_spawned = True
  global_paused on corrupt file: False

  # p23b
  after global resume: file: False project still paused: True
  scopes: [{'scope':'global', ...}]

  # p31
  request: 404 {'code':'not_found', ...}
  pause file exists: True {"paused": true, ...}
  ```
- **最小修复**：`resume_due` 在 spawn 前重新检查 `global_paused` + `project_paused` + maintenance，并走 `_start_admitted` 或等价 admission；`global_paused` 对“文件存在但不可解析/不可读”应 fail-closed（true）并记录诊断，或至少返回 `unknown` 让调用方拒绝；`system_ai_pause` 先解析/校验 identity 和项目、再写文件，失败时回滚；全局恢复遍历项目清 `global` 行（或干脆只在文件层记全局暂停，不写项目行）。

### C3-24 [P3] 诊断/错误响应形状与错误码：health 缺字段、503 映射为 `request_failed`、500 回显绝对路径

- **位置**：
  - `backend/integration/maintenance.py:232-236`（缺项目分支返回 `versions/drafts`）vs `maintenance.py:295-299`（正常分支没有这两个键）
  - `backend/manager/app.py:1344-1351`（状态映射表没有 503/422/500；503 → `request_failed`）
  - `backend/manager/app.py:1355-1363`（`unhandled_handler` 把 `str(exc)` 拼进 message，`redact` 不掩路径）
- **影响**：客户端依赖固定键时会在“项目正常”路径拿不到 `versions/drafts`；全站急停的 503 与其他 503 共用 `request_failed`，UI 无法区分；LAN 客户端可从 500 消息读到服务器绝对路径/SQL 表名（p8 已见 `.../.webnovel/locks`、`no such table: task_pauses`）。
- **证据**：p8/p11/p31 输出；`p11` 的全局暂停 `run` 返回 `503 {'code':'request_failed', ...}`。
- **最小修复**：health 两个分支统一 schema；`http_error_handler` 补 503→`service_unavailable`/`paused`、422→`invalid_request`、500→`internal_error`；`unhandled_handler` 只返回通用消息 + 错误 ID，把详细异常写入本地诊断日志/诊断包（不含路径给远端）。

### C3-25 [P3] DB 表/死代码没有保留策略，GC 只管文件；`task_events` 等只写不读

- **位置**：
  - `workbench_db.py:471-533`（`drafts_history`、`task_events`、`quality_reviews`、`artifact_refs` 等无 retention）
  - `concurrent_engine.py:65-77`（`task_events` 只 INSERT，全仓无 SELECT）
  - `workbench_db.py:922-927`（`idempotency_gc` 只有测试调用）
  - `maintenance.py:124-152`（GC 只扫目录，不删 DB 行）
  - `world_state.py:511-515`（`context_manifests` 每次 persist 只 INSERT；`latest_manifest` 无调用）
- **影响**：长期使用后 `task_events`/`drafts_history`/`quality_reviews`/`context_manifests`/`task_pauses`/`idempotency_keys` 无界增长；诊断 GC 报告“collected 0”但 DB 持续膨胀；`task_events` 是纯写放大。
- **最小修复**：在 `collect_garbage` 增加 DB retention（如 `drafts_history` 保留每章 N 条/90 天、`task_events` 保留 30 天、`idempotency_keys` 过期删除、`context_manifests` 每章保留最新 K 条）；为 `task_events` 增加只读 API 或删除写入；`idempotency_gc` 在 app 启动/dispatch 周期调用。

### C3-26 [P3] C-47 的唤醒路径仍无生产者/消费者，且 `/internal/events/notify` 不在 `WRITE_ROUTES`

- **位置**：
  - `backend/integration/concurrent_engine.py:575-609`（`LoopbackNotifier`/`spawn_worker` 只有测试调用）
  - `backend/manager/app.py:1249-1267`（路由从 `CHAPTER_WHALE_INTERNAL_TOKEN` 读 token；该环境变量全仓只有测试设置）
  - `backend/manager/app.py:1250-1251`（`fanout` 只被该路由 publish；无订阅者）
  - `index.js:227-395`（`WRITE_ROUTES` 不含 `/internal/events/notify`）
- **机制**：路由本身可用（带正确 env token 返回 200），但生产没有构造 `LoopbackNotifier`、没有设置 token、没有订阅 `app.state.event_fanout`；Node 代理的写白名单也不含该路径。所谓“主进程唤醒路径”在真实运行中不可达。
- **证据**：
  ```text
  # p12
  without env token: 403 {'code':'forbidden', ...}
  with env token: 200 {'ok':True,'subscribers_dropped':0}

  # p16b
  MISSING (blocked by proxy):
    POST /internal/events/notify
  ```
  `grep -rn "LoopbackNotifier\|CHAPTER_WHALE_INTERNAL_TOKEN"` 除测试外无命中。
- **最小修复**：要么删除 `LoopbackNotifier`/`EventFanout`/路由并移除 C-47 的对外宣称；要么在 manager 启动时生成随机 token 写入子进程 env（或 Unix socket/loopback 鉴权），由 task producer 调用 `notify_callback`，并把路由加入 `WRITE_ROUTES`/代理例外；同时补一个真实订阅者（SSE/worker）。

### C3-27 [P3] dashboard 聚合按页计算；`state()` 搜索包含本章；若干死分支

- **位置**：
  - `backend/integration/quality.py:232-238`（`averages`/`reviewed` 只对当前 `chapters` 窗口求和，不是全书）
  - `backend/integration/world_state.py:530`（`state()` 的 `search` 用 `chapter=chapter`，而 `build_context` 的 L5 用 `max_chapter=chapter-1`）
  - `world_state.py:613-618`（`fact.get("pinned")` 在 allowed 字段过滤后恒为 None）；`causal_scan` 的 `indirect` 组永不填充（644）；`quality._auto_count` 无调用
- **影响**：超过一页（默认 200 章）时，UI 的“已审/平均分”只是当前页统计；世界状态 dashboard 的“搜索”可能召回本章正文，和上下文包语义不一致；死分支让后续维护误以为有对应能力。
- **证据**：静态代码；`quality.dashboard` 的 `reviewed=sum(... for row in chapters ...)`、`averages=... / max(1, len(chapters))`。
- **最小修复**：`averages`/`reviewed`/`unreviewed` 用全书聚合 SQL（或单独 summary 查询），分页只影响 `chapters`；`state()` 的搜索改 `max_chapter=chapter-1` 或明确“dashboard 含本章”；删除/接线死分支。

## 5. C-01..C-47 与 C-R2 复核矩阵

> “已修”只代表本轮在 C 域重新读过代码/跑过探针或全量测试；“未复审”表示 B/D 域或 Node 代理不在本轮范围，不能据此宣称修好。

| 编号 | 状态 | 本轮证据/说明 |
|---|---|---|
| C-01 | 已修 | p29：confirm 200 active/confirmed_prose，reject-active 409 `fact_not_pending`；`test_v09_api`/`test_world_state` |
| C-02 | 已修 | p29：`write_tx` 内 `chapter_uid` 成功（SAVEPOINT）；全量 integration 1208 通过 |
| C-03 | 已修（GC 过保护见 C3-06） | p15：snapshot/revision preview 均保留；但未引用快照永不回收 |
| C-04 | 部分 | C3-19：`lock_manager` 仍只用于 maintenance；chapter/revision_plan 裸 `file_lock`，annotations/publishing 无项目锁 |
| C-05 | 已修 | `lock_manager.hold` 只在 acquisition 包 try；body 异常原样穿透（代码+test_lock_manager 全绿） |
| C-06 | 已修 | `recover` attempts>=max → failed（test_concurrent_engine 全绿） |
| C-07 | 已修（begin_commit 过期见 C3-11） | commit_grace 300s + renew CASE；test 通过 |
| C-08 | 部分 | running 只设 `hold_requested`；C3-13 证明 begin_commit/complete 仍可通过 |
| C-09 | 部分 | dispatch/`_start_admitted` 已查全局+项目；`resume_due` 无全局检查（C3-23）；运行中子进程不读暂停；队列无消费者（C3-01） |
| C-10 | 合并 B-05，未复审 | API v085 本轮只做项目绑定抽查 |
| C-11 | 合并 B-14，未复审 | 同上 |
| C-12 | 已修 | `_review_key` 内容哈希；`test_v09_quality` 全绿 |
| C-13 | 部分 | evaluate/release 路由存在；但 `agent_tasks` 无生产者、`task_queue` 不互通（C3-20） |
| C-14 | 已修（diagnostics）；同类 backup/export 未修 | C3-02 |
| C-15 | 未闭环 | C3-01 |
| C-16 | 已修（facts pin/lock）；卡片其他字段未修 | C3-16 |
| C-17 | 已修 | `existing_pinned` 接入 high_risk；test_world_state 通过 |
| C-18 | 已修（auto active 路径）；confirm/explicit ID/权威 CASE 见 C3-07/10 | p4/p27 |
| C-19 | 已修 | `detect_conflicts` 跳过 lie/rumor/belief；test 通过 |
| C-20 | 已修 | 第二定义已删；reject 恢复 archived/pending（p29） |
| C-21 | 已修 | `build_context` L5 `max_chapter=chapter-1`；test 通过 |
| C-22 | 已修 | `over_budget`/`budget_overflow_chars`；test 通过 |
| C-23 | 已修 | `_rules`/`_outline_for` 返回 warning；test 通过 |
| C-24 | 已修 | `count_facts_by_status`；test 通过 |
| C-25 | 已修 | `track = B if judgments is not None`；test 通过 |
| C-26 | 已修 | dashboard `limit/offset/total/truncated`；test 通过 |
| C-27 | 已修 | 缺章/消失降级 `missing`；test 通过 |
| C-28 | 已修 | orphan P2；test 通过 |
| C-29 | 已修 | costs/agent 库缺失不 degraded；test 通过 |
| C-30 | 部分 | health/ledger/export 不建 DB；world/quality/annotations/tasks 读路径仍建（C3-04）；GC 锁仍写（C3-05） |
| C-31 | 已修 | p29：未知 action 400 `unsupported_action` |
| C-32 | 已修 | `renew` 返回更新后的 `lease_expires`（代码/测试） |
| C-33 | 部分 | owner 校验存在；UPDATE 无 owner（C3-12） |
| C-34 | 已修 | `_normalize_scope` 统一 resolved path；test 通过 |
| C-35 | 已修 | p29：claim 无 owner 422 `owner_required` |
| C-36 | 部分 | `_event` 失败吞掉；submit(task_id) 仍忽略 payload（C3-14），无幂等键 |
| C-37 | 已修 | p29：blocked_by 字符串 422 `invalid_blocked_by` |
| C-38 | 已修 | `start_dispatcher=False` 不启动 dispatch/notify；代码+test |
| C-39 | 部分 | `api_v09` 用 per-app `global_pause_path`；但 `_start_admitted`/dispatch 仍用模块级 `DATA`，多 app 同进程仍共享（当前 create_app 不支持 data_dir 参数，生产单 app） |
| C-40 | 已修（commit 84760a7） | Node 代理 413 先 drain；本轮未重跑 Node |
| C-41 | 未复审 | Node |
| C-42 | 合并 B-14，未复审 | Node/SSE |
| C-43 | 已修 | 先 replay 再 subscribe，再 replay 补窗；代码+test |
| C-44 | 未复审 | Node |
| C-45 | 已修（`_schema_current` 先查）；但检查不完整 | C3-03 |
| C-46 | 已修 | `_search_needles`/compact 过滤；test_world_state 通过 |
| C-47 | 部分 | 路由存在，但无生产者/订阅者/token（C3-26），且不在 WRITE_ROUTES |
| **C-R2-01** | 已修（窗口关闭条件）；confirm/CASE 见 C3-07/10 | `upsert_fact` 加 subject、active-only、pinned/author_locked 保护 |
| **C-R2-02/03** | 基本修 | renew 单条 CASE；recover/`_mark_recovery` 带 owner/expiry；`hold_for_amendment` 读写同事务；但 hold 状态机见 C3-13 |
| **C-R2-04** | 已修（项目暂停） | p11：project pause 409，global pause 503；`/jobs/{id}/run` 带 project_path；`resume_due` 查 project_paused |
| **C-R2-05** | 未修 | C3-05：GC/export 项目内锁写副作用、dry-run 落锁文件、只读 500 |
| **C-R2-06** | 未修 | C3-14：submit(task_id) 仍忽略 payload |
| **C-R2-07** | 未修 | C3-20：agent_hub held/两套任务队列 |
| **schema 只查 9 表** | 未修 | C3-03 |
| **诊断 GC/export 写锁副作用** | 未修 | C3-05 |
| **agent_hub held 语义** | 未修 | C3-20 |

## 6. 探针索引与原始输出

所有脚本位于 `/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-c/`。运行模板：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-c
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
  /home/ubuntu/venvs/dsh/bin/python -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-c/<script>.py
```

| 探针 | 用途 | 本轮关键输出 |
|---|---|---|
| `p1_schema.py` | 9/20 表自愈 | `schema_current=True`；`pause`/`build_context` OperationalError |
| `p1b_schema_column.py` | 单列自愈 | `quality.review` no column |
| `p1c_schema_fts.py` | search_fts 自愈 | `self_heal` no such table |
| `p2_read_side_effect.py` | GET 写 DB/chapter_meta | 200 后 DB=true，`chapter_meta=[(999,)]` |
| `p3_readonly_gc.py` | dry-run 锁文件/只读 | L8 lock 文件；PermissionError |
| `p4_confirm_window.py` | 确认不关旧窗口 | ch5 两条 active + conflict |
| `p5_submit_payload.py` | task_id 忽略 payload | 第二次仍旧 payload/priority |
| `p6_commit_expired.py` | 过期 begin_commit | 成功 +300s；renew 则 recovery |
| `p7_fail_toctou.py` | fail 竞态 | 新 owner 任务被改成 pending |
| `p8_api_500.py` | schema/只读 API 映射 | pause/exemption/GC 500；health ok |
| `p9_amendment_claim.py` | hold 被 claim 绕过 | fail/recover 后仍可领取 |
| `p10_pause_gaps.py` | resume_due/急停文件 | 全局暂停仍 spawn；损坏文件 false |
| `p11_jobs_pause.py` | jobs run 暂停 | 项目 409 / 全局 503 / 恢复 queued |
| `p12_wake.py` | 唤醒 token | 无 token 403；有 token 200；无订阅者 |
| `p13_upsert_race.py` | 并发 upsert | 两条相同逻辑事实 |
| `p14_readonly_reads.py` | 只读读接口 | world/quality 500；diagnostics ok |
| `p15_gc_protection.py` | GC 保护集 | 未引用 snapshot/preview 全部保留 |
| `p16b_write_routes.py` | 路由白名单 | 唯一缺失 `/internal/events/notify` |
| `p17_recovery_hold.py` | recovery→held→pending | 重新 claim，committing 残留 |
| `p18_blockers.py` | blocked_by 校验 | missing/self/cycle 全 None |
| `p19_card_partial.py` | set_card 局部写 | card_md/aliases/kind 被清 |
| `p20_confirm_downgrade.py` | 确认降级 | active ai_inferred，L2 不收 |
| `p21_export_destination.py` | backup/export 路径 | 任意目录 200，复制正文+manager DB |
| `p22_blocker_release.py` | 正常 blocker 释放 | 对照组：完成后可领 |
| `p23b_global_resume.py` | 全局恢复残留 | file false，project 仍 paused |
| `p24_scalar_500.py` | 标量 TypeError | v08/v09 三处 500 |
| `p25_running_hold.py` | running hold | begin_commit/complete 照常 |
| `p26_assertion_merge.py` | fact→rumor | 同一 fact_id 变 rumor |
| `p27_authority_case.py` | CASE 权威 | ai_inferred 关闭 draft_prose |
| `p28_publish_mutex.py` | 项目互斥 | publish/polish 与 daily 同时 queued |
| `p29_regression.py` | C-01/02/31/35/37 | 200/409/400/422 全符合 |
| `p30_deferred.py` | deferred 死状态 | active 空；resume 不恢复；second daily 可入 |
| `p31_pause_side_effect.py` | 暂停先写后验 | 404 但全局 pause 文件已写 |

### 6.1 关键输出（原文摘录）

```text
# p13
thread results: ['saved', 'saved']
world_facts rows: [{'fact_id': 'fact_9d1bc0fd', ...}, {'fact_id': 'fact_8b2ce975', ...}]
duplicate active facts: 2

# p21
backup: 200
backup files: [..., 'db/00-workbench.sqlite3', 'db/01-extra-00-manager.sqlite3',
               'db/02-extra-01-costs.sqlite3', '正文/第1章-开端.md']
manuscript copied: True
manager db copied: True

# p28
publish: daily=queued publish=queued workers=2
polish: daily=queued polish=queued workers=2

# p30
active_only sees deferred: []
after resume_due: deferred resumed: False
second daily admitted while deferred: queued
```

### 6.2 基线

```text
PATH=... python -m unittest discover -s backend/manager -t backend
Ran 222 tests in 120.912s
OK

PATH=... python -m unittest discover -s backend/integration -t backend
Ran 1208 tests in 130.671s
OK (skipped=9)
```

## 7. 未覆盖/边界

- **B/D 域与 Node 代理未逐行复审**：C-10/C-11/C-40/C-41/C-42/C-44 只做了交叉引用；`index.js` 只检查了 `WRITE_ROUTES` 与 C-47 相关路径，没有重新审计 SSE/代理/body limit 全链路。
- **真实模型/真实番茄发布未调用**：C3-01 的“未接线”是静态代码证明；C3-02 的 LAN 外泄原语用真实 FastAPI/文件系统验证了“可写任意空目录”，但没有在真实配对设备上复现网络层。
- **Windows/macOS 文件锁行为未在本机执行**：`msvcrt` 路径、只读 ACL、Windows 长路径可能改变 C3-03/C3-05 的表现；CI 结果不能替代本机。
- **GC 的 DB 表 retention**：C3-25 只按代码/表结构判定，没有构造长时间运行的数据库增长曲线。
- **`agent_tasks`/`task_queue` 的真实 worker**：仓库没有 v0.9 worker，C3-13/C3-20 的“接线后触发”是静态+状态机探针结论；未在真实 worker 上复现。
- **多进程 SQLite 竞争**：C3-08/C3-12 用双线程/受控交错复现；没有在多进程、WAL checkpoint、Windows AV 下重复压测。
- **权限模型**：C3-02 的 P1 依赖 `--lan` + 私网免配对或已配对设备；本机单用户模式为 P2。未测试真实反向代理/防火墙组合。

## 8. 建议修复顺序

### 合并/发布前（P1）
1. **C3-02**：把 backup/export-legacy 的 `destination` 固定到 `data_dir` 子目录，`snapshot_dir` 也做 `resolve()` 白名单；LAN 模式加导出确认。
2. **C3-01**：产品决策——要么把 world facts/quality/queue 接进 `writer_runner`/`worker.py`，要么在 UI/文档明确 `advisory only` 并删除“主路径约束”宣称。

### 本周期（P2，按数据/并发优先）
3. **C3-03**：补齐 schema 清单/列检查/health 自愈。
4. **C3-05/C3-06**：诊断锁移到 data_dir；明确 GC 证据保留策略；接 `register_artifact` 或删除引用计数。
5. **C3-07/C3-08/C3-09/C3-10**：世界窗口/确认/去重键/权威 CASE 一次性重写为同一事务、同一键定义。
6. **C3-11/C3-12/C3-13**：租约/owner/改令状态机；在接线 worker 前补回归。
7. **C3-14/C3-15/C3-17/C3-18**：submit 幂等/blocker 校验/deferred 状态/项目互斥。
8. **C3-04/C3-16/C3-19/C3-20**：只读读路径、卡片局部更新、锁统一、两套任务队列合一。

### 下一版本（P3）
9. **C3-21..C3-27**：错误码/响应形状/保留策略/唤醒路径/dashboard 聚合；不要用“测试全绿”掩盖这些静态可证项。

---

AUDIT_STATUS: DONE
