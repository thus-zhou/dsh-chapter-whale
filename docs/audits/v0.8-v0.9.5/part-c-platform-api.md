# v0.9 平台层只读深度审计：锁 / 并发 / 世界状态 / 质量 / 维护 / API / 代理

## 0. 基线、方法与结论

- 审计对象：`/home/ubuntu/projects/dsh-chapter-whale`，分支 `feat/v0.8-v0.9.5`，HEAD `fe2bc3272194bb818a4caaf517e67cb6bc0f34d1`（`fe2bc32`）。
- 只读约束：本审计未修改仓库文件，未执行 `git commit` / `git push`，未联网。所有复现均在 `git archive HEAD backend` 解包出的 `audit-v095/head/` 副本中运行；报告中的行号均按 HEAD blob。
- 基线说明：审计期间工作区出现了多份未提交修改（`git status` 可见 `agent_hub.py`、`agent_room.py`、`api_v085.py`、`api_v09.py`、`concurrent_engine.py`、`quality.py`、`maintenance.py`、`world_state.py` 等），这些修改不是本审计产生的，也不计入本报告结论；若这些修改修掉了下列条目，合并后应重新核对。所有结论以 HEAD 为准。
- 复现脚本与原始输出：
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_world2.py`
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_engine2.py`
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_maint.py`
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_api.py`
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_quality.py`
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_agent.py`
  - `/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_extra.py`
  - 汇总输出：`/home/ubuntu/.hermes/cache/scratch/audit-v095/outputs.txt`；静态 grep / 清单校验输出：`static-evidence.txt`。
  - 升级清理复现：`/home/ubuntu/.hermes/cache/scratch/audit-v095/probe_stale.mjs`。
- 证据口径：所有 P1 均有实际运行复现；仅凭代码路径/grep、没有运行时故障复现的条目在正文标注“静态”，并按保守口径定级（不把静态缺口升为 P1）。
- 统一复现前缀：
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v095/head
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 ../<probe>.py
```

### 结论计数

| 等级 | 数量 | 含义 |
|---|---:|---|
| P0 | 0 | 无“立即不可恢复 / 全站数据损坏”级问题 |
| P1 | 6 | 发布前必须修：数据丢失、任务状态机破坏、关键安全控制失效、功能完全不可用 |
| P2 | 26 | 重要一致性 / 健壮性 / 发布完整性问题，特定路径可触发 |
| P3 | 8 | 细节、测试盲区、可维护性问题 |

**最严重的 5 条**：

1. **P1-1** GC 删除面失控：`artifact_refs` 的引用/保护标记完全不参与删除决策，`outline-backups` 被当作垃圾，`.webnovel/previews` 为目录符号链接时可删除项目外文件。
2. **P1-2** `diagnostics/export` 接受任意 `destination`，可直接覆盖正在写的章节正文文件（已用 HTTP 复现章节变成 ZIP）。
3. **P1-4** 任务生命周期无状态/owner 守卫：`fail` 可把 `completed` 任务复活为 `pending`，`complete` 可把 `pending` 或 `recovery_required` 直接标完成。
4. **P1-3** AI 提取默认写成 `confirmed_prose`，高风险判定只信调用方传入的 `pinned`；死亡类事实可自动 active，且 `pending_confirm` 事实没有任何查询/确认 API。
5. **P1-5** `/api/system/ai/pause` 不是“全站急停”：无 `identity` 时返回成功但不写任何状态；带 `identity` 时只暂停该书；`task_pauses` 本身是每书 SQLite 表。

---

## 1. 维护 / GC / 诊断包

### P1-1 GC 删除面失控：引用保护未实现、作者大纲备份被删、符号链接可越界

**位置**：`backend/integration/maintenance.py:20`、`:63-73`、`:76-102`、`:105-119`；`backend/integration/outline_editor.py:76-77`、`:244-255`；`backend/integration/revision_plan.py:284-285`。

**机制**：

1. `collect_garbage()` 只调用 `_protected_paths()`；`_protected_paths()` 只保护当前章节文件、`.webnovel/chapter_versions`、`.webnovel/drafts`、`.webnovel/trash` 和两张草稿表的 `content_path`。它**从未查询 `artifact_refs`**；`register_artifact()` 写入的 `ref_count` / `protected` 在删除路径上完全没被读取。全仓库也没有生产代码调用 `register_artifact()`（grep 只见定义与测试），所谓“引用计数 GC”实际未接线。
2. `_PREVIEW_DIRS` 包含 `"outline-backups"`。`outline_editor._backup()` 每次保存大纲都会把旧文件复制到 `.webnovel/outline-backups/`，并按每个 stem 保留最近 30 份，这是作者大纲的回滚材料；GC 只要文件 mtime 超过 7 天就删除。与此同时真正的修订预览目录是 `.webnovel/revision_previews`（`revision_plan.previews_dir()`），不在 `_PREVIEW_DIRS` 中，GC 反而永远清不到。
3. `_candidate_files()` 对 `_PREVIEW_DIRS` 下的目录只做 `folder.is_dir()`，**没有拒绝目录符号链接**；`path.is_symlink()` 只检查叶子文件。若 `.webnovel/previews` 是指向项目外的符号链接，`rglob()` 会遍历目标并删除其中超过保留期的普通文件。

**影响**：维护操作可删除已登记为 `protected=1, ref_count=5` 的产物；可删除作者唯一的大纲回滚备份；可通过一个目录符号链接删除项目外任意可写文件。均为不可恢复数据丢失。

**最小修复**：

- `collect_garbage()` 先查 `SELECT path, protected, ref_count FROM artifact_refs`，将 `protected=1` 或 `ref_count>0` 的 resolved path 加入保护集；没有登记的文件不应默认视为可删。
- 从 `_PREVIEW_DIRS` 移除 `"outline-backups"`，或对其使用与 `outline_editor` 一致的 30 份保留策略；若要清预览，加入 `"revision_previews"`。
- 对每个候选目录先 `if folder.is_symlink(): continue`，并对 `path.resolve()` 做 `project.resolve()` 包含性校验；`rglob` 前拒绝越界根目录。
- GC 与章节/大纲写入之间应持同一把维护锁，避免“保护集快照”与删除之间的竞态。

**复现**：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v095/head
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 ../probe_maint.py
# 输出：
# 1 registered= art_... exists_after_gc= False removed= 1
# 2 outline_backup_exists= False removed= ['.../.webnovel/outline-backups/outline-v1.md']
```

符号链接越界（`probe_extra.py`）：

```text
M2_victim_exists False
```

即项目外 `outside/victim.txt` 被 GC 删除。`P1` 无静态假设，已实际删除。

### P1-2 诊断包导出可覆盖任意文件（含当前章节正文）

**位置**：`backend/integration/maintenance.py:215-234`；`backend/manager/api_v09.py:298-304`。

**机制**：`export_bundle(project, destination)` 直接 `Path(destination)`，仅创建父目录，随后 `zipfile.ZipFile(destination, "w")` 截断写入；没有“目标必须是 .zip / 不得位于作品目录 / 不得是已存在文件”的校验。`/api/projects/{identity}/diagnostics/export` 把请求体 `destination` 原样传入（`Path(target).expanduser()`）。对比 `transaction_journal.backup()` 明确拒绝 `destination_inside_project`（`:1147-1152`），本路径没有同等保护。

**影响**：任何能调用该管理 API 的本地客户端可把 ZIP 写到 `正文/0001.md`、`.webnovel/chapter_versions/...`、`manager.sqlite3` 等任意可写路径，造成章节/数据库被覆盖。已实测章节文件从 7 字节变成 871 字节 ZIP，`PK` 魔数。

**最小修复**：`export_bundle` 内做 `dest = Path(destination).expanduser().resolve()`；拒绝 `dest` 位于 `project` 内、拒绝 `dest` 已存在且不是普通 ZIP 目标、强制 `.zip` 后缀；写临时文件后 `os.replace` 原子落盘；API 只允许服务端生成的 `data_dir/diagnostics/...` 路径，不接受客户端绝对路径。

**复现**：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v095/head
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 ../probe_api.py
# 输出：
# export 200 chapter_before 7 after 871 magic b'PK'
```

### P2-13 资源账本查错数据库，五态 tokens/cost 恒为 0

**位置**：`backend/integration/maintenance.py:122-152`（查询在 `:128-129`）；`backend/integration/workbench_db.py:21-22`；`backend/integration/costs.py:107`。

**机制**：`resource_ledger()` 在项目的 `workbench.sqlite3` 上执行 `SELECT ... FROM request_budget`。但 `workbench_db` 的模块注释明确说 `request_budget` 是既有 v0.7.5 表、属于另一个数据库；`costs.py` 在 `costs.sqlite3` 中创建该表。项目 workbench 库里没有 `request_budget`，`sqlite3.OperationalError` 被 `except sqlite3.Error: pass` 吞掉，五态永远是全 0。

**影响**：`/api/projects/{identity}/ledger` 与诊断包中的 `ledger` 永远报告 0 tokens / 0 成本，作者会误以为没有消耗；成本审计失真。

**最小修复**：`resource_ledger` 接受 `costs_db` 路径（API 已有 `data_dir`），从 `costs.sqlite3` 读 `request_budget`；或删除成本字段，仅保留 `task_queue/artifact_refs` 统计，并在 API 中明确数据来源。

**复现**：`probe_maint.py` 输出：

```text
5 ledger= {'reserved': {'count': 0, 'tokens': 0, ...}, ...}  # 全部 0
```

同时 `grep -n "request_budget" backend/integration/costs.py` 显示建表在 `costs.py:107`。

### P2-14 数据库损坏时 `/diagnostics` 自身 500，无法给出诊断

**位置**：`backend/integration/maintenance.py:155-201`，关键在 `:163-174`。

**机制**：`health()` 先用裸 `sqlite3.connect` 做 `PRAGMA integrity_check`，捕获 `sqlite3.Error` 并记录 `db_open_failed`；但随后在 `:174` 无条件执行 `with wb.connect(project) as db:` 读取 `chapter_meta`，且不在 try 内。`wb.connect()` 第一步执行 `PRAGMA journal_mode=WAL`，对损坏文件抛 `sqlite3.DatabaseError`（`sqlite3.Error` 子类但此处无捕获）。`export_bundle()` 先调用 `health()`，因此导出也会一起失败。

**影响**：数据库损坏正是最需要 `/api/projects/{id}/diagnostics` 和诊断包的时刻，但两者都 500，且外层无法得到结构化 `issues`。

**最小修复**：在 integrity 失败后立即返回 `{"status":"degraded", "issues":[...]}`，跳过后续依赖 DB 的检查；或把 `:174` 到 `versions.load_index` 全部包在 `try/except sqlite3.Error` 中并追加 issue。

**复现**：`probe_extra.py` 输出 `M1_health_raised DatabaseError file is not a database`。

### P2-15 `self_heal("rebuild_search")` 是空操作却报告 healed

**位置**：`backend/integration/maintenance.py:252-261`。

**机制**：`wb.rebuild_search(project) if hasattr(wb, "rebuild_search") else None`；`workbench_db.py` 中没有 `rebuild_search`（HEAD grep 无定义），因此分支永远走 `None`，仍返回 `{"status":"healed"}`。`checkpoint` 分支也不检查 `PRAGMA wal_checkpoint(TRUNCATE)` 的返回值（busy 时可能未完成），同样报 healed。

**影响**：作者在索引损坏时点击“自愈”，界面显示成功，搜索仍不可用；诊断状态被谎报。

**最小修复**：实现 `rebuild_search`（清空 `search_fts` 后按 `search_docs` 重建，或用 `INSERT INTO search_fts(search_fts) VALUES('rebuild')`），不存在时返回 `unsupported_action` 而不是成功；`checkpoint` 检查返回行并在 busy 时返回 `degraded`。

**复现**：`probe_maint.py` 输出 `6 has_rebuild_search= False result= {'status': 'healed', 'action': 'rebuild_search'}`。

### P2-16 `system/diagnostics/recover` 默认执行真实 GC，且可被负保留期放大

**位置**：`backend/manager/api_v09.py:267-278`（`:275`）；`backend/integration/maintenance.py:76-102`；对比 `api_v09.py:290-296` 的项目 GC 默认 `dry_run=True`。

**机制**：`system_recover` 的 `action=="gc"` 分支使用 `dry_run=bool(body.get("dry_run", False))`，缺省即真实删除；项目级 `/diagnostics/gc` 的缺省是 `dry_run=True`。`min_age_seconds` 经 `int(body.get(...) or 7*86400)` 传入，负数会被 `max(0, ...)` 变成 0，cutoff=now，刚生成的文件也满足 `st_mtime <= cutoff` 而被删。

**影响**：名为“recover”的全局端点实际是一个默认破坏性的 GC 入口；配合 P1-1 会删除作者大纲备份/受保护产物。负值参数把保留期保护完全取消。

**最小修复**：`system_recover` 默认 `dry_run=True`，只有显式 `dry_run=false` 且二次确认字段存在才真删；`min_age_seconds` 强制 `>= 86400`；GC 统一只走项目级端点。

**复现**：`probe_api.py` 输出 `recover_gc 200 removed 1 file_exists False`（请求体只带 `identity/action`，没有 `dry_run`）；`probe_maint.py` 输出 `3 fresh_deleted= True count= 1`（`min_age_seconds=-1`）。

### P3-6 诊断包声明“仅哈希与计数”，实际包含章节标题

**位置**：`backend/integration/maintenance.py:220-232`；`backend/integration/maintenance.py:204-212`。

**机制**：`chapters.index.json` 的每个条目包含 `"title": meta.get("title", "")`；`_strip()` 只删除 `content/body/outline/text` 等键并截断长字符串，不删除 `title`。README 文本写“诊断包默认不含正文、大纲与密钥；仅哈希与计数”。

**影响**：章节标题可能包含剧透/敏感信息，与“仅哈希与计数”的承诺不一致；对外发送诊断包时存在信息泄露。

**最小修复**：索引只保留 `chapter_id/version_id/sha256/bytes`，标题改为 `title_sha256` 或明确在 README 中声明会包含标题；如确需标题，提供 `include_titles=False` 开关。

**复现**：`unzip -p diagnostics.zip chapters.index.json` 可见 `title` 字段（`export_bundle` 输出包含 `chapters.index.json`）。

---

## 2. 世界状态

### P1-3 AI 提取的权威等级与高风险门禁可被调用方绕过，且待确认事实不可见

**位置**：`backend/integration/world_state.py:426-476`（关键 `:447`、`:455-462`、`:463-469`）、`:111-116`、`:163-179`、`:479-484`；`backend/manager/api_v09.py:91-110`。

**机制**：

1. `extract_candidates()` 对每条事实写 `"authority_level": raw.get("authority_level") or "confirmed_prose"`（`:461`）。AI 提取默认拿到 4 级 `confirmed_prose`，高于 `draft_prose`（3）和 `ai_inferred`（2）；`upsert_fact()` 的守卫只看同一 `fact_id` 的旧权威（`:113-116`），因此同 `fact_id` 的草稿事实可被“AI 推断”以 confirmed_prose 覆盖。调用方还可以直接传 `authority_level="author_locked"`，代码原样写入（实测）。
2. 高风险判定 `high_risk = fact.get("pinned") and assertion == "fact" and ...`（`:463`）只信**本次传入事实**的 `pinned` 布尔，不查该实体/事实在库中是否作者锁定。调用方省略 `pinned` 时，`"死亡"`、`"身份暴露"` 等高风险事实直接以 `status="active"`、`authority_level="confirmed_prose"` 落库（实测 D）。
3. 置为 `pending_confirm` 的事实只存在于返回值；`facts_for_chapter()` 只查 `status='active'`（`:166`），`state()` 的 `facts` 同样为空；API 没有 list-pending / confirm / reject 路由（`api_v09.py:91-110` 只有 extract）。`confirm_fact()`/`reject_fact()` 是模块函数，无 HTTP 入口。

**影响**：世界状态可被“AI 提取”写入高权威、自动生效的死亡/身份暴露事实，覆盖草稿、污染后续章节上下文；真正被置为 `pending_confirm` 的高风险事实在刷新后完全不可见、无法确认/拒绝，形成“看不见的脏数据”。

**最小修复**：

- `extract_candidates` 强制 `authority_level="ai_inferred"`，拒绝或钳制调用方传入的高权威；作者确认走独立端点并显式提升权威。
- 高风险判定改为“本次 `pinned` 为真 **或** 库中同实体/同 fact_id 已 pinned/author_locked”，且高风险一律 `pending_confirm`，不依赖调用方字段。
- 新增 `GET /world/facts?status=pending_confirm` 和 `POST /world/facts/{id}/confirm|reject`；`state()` 至少返回 pending 计数。
- `upsert_fact` 按 `(entity_id, subject, predicate, object, valid_from, valid_until)` 做逻辑去重（见 P2-2）。

**复现**：`probe_world2.py` 输出：

```text
D_missing_pinned accepted 1 pending 0 status active authority confirmed_prose
D2_ai_authority_written author_locked
D3_pending_visible 1 0 0
```

`D3` 表示提取返回 1 条 pending，但 `facts_for_chapter` 与 `state()` 都是 0 条。

### P2-2 逻辑事实不去重，重复提取产生重复行

**位置**：`backend/integration/world_state.py:87-142`；`backend/integration/workbench_db.py:301-327`。

**机制**：`upsert_fact()` 的 docstring 声称“同一逻辑事实（entity + predicate + object + validity window）会更新而不是重复”，但 SQL 只按 `fact_id` 查重（`:112`），表上也没有 `(entity_id, subject, predicate, object, valid_from, valid_until)` 唯一约束。`extract_candidates()` 每次给新 `fact_id`，同一章重复提取会插入多行。

**影响**：上下文 L2 中同一事实重复出现，`pinned[:40]` 截断会把其他事实挤出；`detect_conflicts` 的分组行数增加；长期运行后世界状态膨胀且难以人工清理。

**最小修复**：在写事务内按逻辑键 `SELECT fact_id FROM world_facts WHERE entity_id IS ? AND subject=? AND predicate=? AND object=? AND COALESCE(valid_from_chapter,-1)=? AND COALESCE(valid_until_chapter,-1)=?`，存在则复用 `fact_id`；同时加唯一索引（对 NULL 用 `COALESCE` 表达式索引或写入哨兵值）。

**复现**：`probe_world2.py` 输出 `A_duplicate_rows 2`（同一个 `base` 调用两次）。

### P2-3 `facts_for_chapter` 按字符串排序权威，`author_locked` 排在 `published_prose` 之后

**位置**：`backend/integration/world_state.py:163-179`，排序在 `:178`。

**机制**：`ORDER BY pinned DESC, authority_level DESC, narrative_chapter` 对 TEXT 列做字典序降序。实际顺序为 `published_prose` → `future_plan` → `draft_prose` → `confirmed_prose` → `author_locked` → `ai_inferred`，与 `AUTHORITY` 数字（author_locked=6 最高）不一致。

**影响**：同一 `pinned` 组内，最高权威的 `author_locked` 排在低权威之后；`build_context` 的 L2 只取 `pinned[:40]`，事实超过 40 条时会优先保留低权威事实、丢掉作者锁定事实。仪表盘/事实列表的优先级同样错误。

**最小修复**：改为 `ORDER BY pinned DESC, CASE authority_level WHEN 'author_locked' THEN 6 ... END DESC, narrative_chapter`，或增加 `authority_rank INTEGER` 列并按其排序。

**复现**：`probe_world2.py` 输出 `B_order [('f_pub','published_prose'), ('f_author','author_locked')]`。

### P2-4 `ignore_conflict` 把事实状态全局改成 `ignored_by_author`，跨章隐藏

**位置**：`backend/integration/world_state.py:244-251`、`:254-260`、`:163-168`；`backend/manager/api_v09.py:55-62`。

**机制**：`ignore_conflict()` 除了写 `conflict_ignores(fact_id, chapter_uid, version_id)`，还执行 `UPDATE world_facts SET status='ignored_by_author' WHERE fact_id=?`（`:249`）。`facts_for_chapter()` 只取 `status='active'`，因此该事实在**所有章节**消失，而不只是被忽略的那一章。API 的 `chapter_uid` 默认空字符串，若调用方不传，则 `conflict_ignores` 的 key 永远匹配不到实际 chapter_uid（`is_ignored` 查 `chapter_uid=?`），但状态已被全局改掉。

**影响**：作者在第 10 章忽略一次“故意为之/回忆杀”的冲突，会让该事实在第 1 章、第 20 章等所有上下文中消失；空 `chapter_uid` 时既不能按章忽略，又永久隐藏事实。

**最小修复**：`ignore_conflict` 只写 `conflict_ignores`，不要改 `world_facts.status`；`detect_conflicts` 已通过 `is_ignored` 抑制报告。若必须改状态，应新增 `ignored_chapters_json` 或按 `(fact_id, chapter_uid)` 存状态。API 校验 `chapter_uid` 非空且属于当前章节。

**复现**：`probe_world2.py` 输出 `C_after_ignore_ch1 0 ch2 0`（在第 2 章 ignore，第 1 章也消失）。

### P2-5 `future_plan` / `discarded_candidate` 事实进入当前章节上下文

**位置**：`backend/integration/world_state.py:163-179`，docstring 在 `:165`。

**机制**：`facts_for_chapter()` 的 docstring 写“future plans are excluded here”，但 WHERE 只有 `status='active'` 和 valid window，没有排除 `authority_level='future_plan'` / `'discarded_candidate'`。`upsert_fact` 默认 `status='active'`，调用方只要写一条 `authority_level=future_plan` 的事实就会被当前章节读到；`detect_conflicts` 也会把它和当前事实比较。

**影响**：后续卷的“结局/身份”计划会作为已发生事实进入第 1 章上下文，造成剧透、时间线污染和假冲突。

**最小修复**：WHERE 增加 `authority_level NOT IN ('future_plan','discarded_candidate')`，或在 `upsert_fact` 对这两类强制 `status='pending_confirm'/'archived'`；`detect_conflicts` 同样排除。

**复现**：`probe_world2.py` 输出 `J_future_plan_in_ch1 [('f2','future_plan')]`。

### P2-6 GET `/world-state` 与 `/world/context` 在数据库里写 manifest

**位置**：`backend/integration/world_state.py:393-396`、`:400-408`；`backend/manager/api_v09.py:33-36`、`:74-78`；`index.js:412-415`。

**机制**：`build_context()` 默认 `persist=True`，每次调用都 `INSERT INTO context_manifests`。`state()` 在 `:403` 调 `build_context(...)`，API 的 `/world-state` 与 `/world/context` 都是 GET。代理的 `allowsRead()` 放行所有 `/api/*` GET（除 `_service`），Gate 4 的 `WRITE_ROUTES` 不覆盖它们。

**影响**：一次 GET 仪表盘/上下文就产生一条永久 manifest；轮询/刷新导致 `context_manifests` 无界增长，且 GET 触发 SQLite 写事务，与并发写争锁。更一般地，GET 的“只读”契约被破坏，写白名单无法审计这条写入。

**最小修复**：`state()` 使用 `build_context(..., persist=False)`；`/world/context` 如果是只读展示也传 `persist=False`，需要持久化时改为显式 POST（并加入 `WRITE_ROUTES`）；给 `context_manifests` 加按章节/时间的保留策略。HEAD 的 `state()` 尚未传 `persist`，见 `world_state.py:403`。

**复现**：`probe_world2.py` 输出 `E_state_calls_manifests 0 -> 2`；`probe_api.py` 输出：

```text
GET world-state 200 manifests 0 -> 1
GET world/context 200 manifests 1 -> 2
```

### P2-7 L5 检索跨全书，未来章节内容泄入当前上下文

**位置**：`backend/integration/world_state.py:360-363`；`backend/integration/workbench_db.py:825-858`。

**机制**：`build_context` 的 L5 调用 `search(project, query, limit=8)`，没有传 `chapter`；`wb.search` 也没有章节参数。索引包含全书所有章节（`index_chapter` 按章写入），因此第 2 章构建上下文时，查询词会命中第 10 章甚至结局章。

**影响**：写作上下文会注入未来剧情/真凶/结局片段，直接导致剧透、前后矛盾；作者看到“按需检索”却不知道它越过了当前叙事位置。

**最小修复**：`search(project, query, chapter=chapter, limit=8)`；`workbench_db.search` 增加 `chapter_id IS NULL OR chapter_id<=?` 的 SQL 过滤（`IS NULL` 用于设定/规则类文档），在 LIMIT 之前过滤，避免 P2-8。

**复现**：`probe_world2.py` 输出 `H_L5_items [...] {'doc_key':'正文:10','chapter_id':10,...}`（目标章节是 2）。

### P2-8 `world/search?chapter=N` 在 LIMIT 之后才过滤，目标章节可能 0 命中

**位置**：`backend/integration/world_state.py:237-241`；`backend/integration/workbench_db.py:839-844`。

**机制**：`wb.search` 先 `ORDER BY rank LIMIT ?` 取全局前 N，`world_state.search` 之后才 `[hit for hit in hits if hit.get("chapter_id") in (None, chapter)]`。如果前 20 条都来自其他章节，目标章节即使有匹配也返回空。

**影响**：`GET /world/search?chapter=30` 在长书中不可靠；L5 若按 P2-7 修复但仍在 Python 后过滤，同样会漏检。

**最小修复**：把章节条件下推到 SQL：`WHERE search_fts MATCH ? AND (d.chapter_id IS NULL OR d.chapter_id=?)`，再 `LIMIT`；Python 侧只做展示过滤。

**复现**：`probe_world2.py` 输出 `G_chapter_filter hits 0 chapters []`（30 章都有“秘境”，查第 30 章返回 0）。

### P2-9 上下文裁剪顺序与预算实现不符：先清 L3/L5，保留 L4，最终超预算

**位置**：`backend/integration/world_state.py:364-378`。

**机制**：`sorted(layers, key=lambda item: item["layer"] in {"L1","L2","L4"})` 把 L3、L5 排到前面，L1/L2/L4 排到后面；循环里按这个顺序把整层截到 0。代码注释写“drop L5 then L3 tails first”，实际是 L3 先于 L5，且 L4 只在最后才被裁剪。`total` 只统计各层 `text`，不统计最终拼装时的 `【Lx·title】` 头（`:379-380`），所以 `manifest["chars"]` 会大于 `budget_chars`。

**影响**：预算紧张时本章细纲（L3）和检索（L5）被清零，上一章结尾（L4）反而保留最多 500 字；写作模型看不到本章细纲。最终文本仍超预算 12 字节/层头，预算契约不成立。

**最小修复**：显式定义裁剪优先级（建议 L5 → L3 → L4 → L2，L1 永不裁剪），按层 `share` 或“保留尾部”裁剪而不是整层清零；把层头长度计入预算；组装后再断言 `len(text) <= budget_chars`，必要时继续裁剪。

**复现**：`probe_world2.py` 输出：

```text
F_budget 500 chars 512 [('L1',0,None),('L2',0,True),('L3',0,True),('L4',500,True),('L5',0,True)]
F_budget 150 chars 162 ...
```

### P3-5 非法 `confidence` 抛 `ValueError`，不是稳定错误码

**位置**：`backend/integration/world_state.py:447`；`backend/manager/api_v09.py:20-30`。

**机制**：`confidence = float(raw.get("confidence") or 0)` 对 `"high"`、`[]` 等抛 `ValueError`；`api_v09.guard` 只捕获 `WorldStateError` 等四类，`ValueError` 落到 `app.py` 的通用 400 `request_failed`，没有 `invalid_confidence` 码。

**影响**：批量提取中一条坏数据使整个请求 400，且调用方拿不到具体字段；与“稳定机器码”的 API 约定不符。

**最小修复**：捕获 `(TypeError, ValueError)`，`rejected.append({"reason":"invalid_confidence"})` 并继续；或抛 `WorldStateError("invalid_confidence")`。HEAD 的 `upsert_fact` 同样有 `float(...)`（`:107`），也应统一。

**复现**：`probe_world2.py` 输出 `K_invalid_confidence ValueError could not convert string to float: 'high'`。

---

## 3. 并发 / 任务 / 锁

### P1-4 任务生命周期无状态与 owner 守卫：`fail` 复活已完成任务，`complete` 跳过对账

**位置**：`backend/integration/concurrent_engine.py:256-265`（complete）、`:268-276`（fail）、`:321-330`（retry）；`backend/manager/api_v09.py:174-184`。

**机制**：

- `complete(project, task_id, owner="")`：只有 `if owner and item["lease_owner"] not in {owner, None}` 才校验；API 默认传 `""`（`api_v09.py:177-178`），因此任何客户端都能完成任何任务，包括 `state='pending'`（从未 claim）和 `state='recovery_required'`（等待对账）。`complete` 不校验当前状态，直接把 `state='completed'`、`committing=0`。
- `fail(project, task_id, error=...)`：**完全没有 owner/state 校验**；对 `completed` 任务只要 `attempts < max_attempts` 就置回 `pending`（实测 `completed -> pending`）。也能把 `recovery_required`、`cancelled` 任务重新排队，并把 `committing` 清零。
- `retry` 允许 `recovery_required` 直接回 `pending` 并清 `committing`（见 P2-21）。
- `recover` 的 `UPDATE ... WHERE task_id=?` 没有 `state='running'` 守卫，完成/失败与 recover 并发时可能把已完成任务改回 pending。

**影响**：一个迟到的 `fail` 回调会把已经提交完成的任务重新执行，造成重复模型调用、重复写章、重复计费；`complete` 可以伪造完成，绕过 `recovery_required` 对账，让 `blocked_by` 的下游任务提前运行。这是 v0.9 任务引擎最严重的一致性缺陷。

**最小修复**：`complete`/`fail` 要求 `state='running'`、`lease_owner==owner`、`lease_expires >= now`；`fail` 对 completed/cancelled/recovery_required 返回 409 或幂等 no-op；`recover` 的 UPDATE 加 `AND state='running' AND lease_owner=?` 作为 fencing；`complete` 清除 `hold_amendment_id/amendment_fallback`。owner 不应由客户端字符串决定，`claim` 应返回服务端生成的 lease token。

**复现**：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v095/head
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 ../probe_engine2.py
# 2a pending_completed= completed
# 2b recovery_state= recovery_required -> after_complete= completed
```

`fail` 复活已完成任务（追加输出）：

```text
T3_before_fail completed
T3_after_fail pending
```

### P2-1 八级锁序模块零生产调用；SQLite 事务内的 OS 锁守卫实际失效

**位置**：`backend/integration/lock_manager.py:65-70`、`:78-104`、`:138-145`；`backend/integration/workbench_db.py:100-105`。

**机制**：`grep -rn "lock_manager\|sqlite_scope" backend --include=*.py` 除 `test_lock_manager.py` 与模块自身外没有任何调用；`chapter_editor`/`outline_editor` 各自用 `publication_safety.file_lock`，不经过 `lock_manager.hold/ordered`。同时 `workbench_db.write_tx()` 从不调用 `lock_manager.sqlite_scope()`/`note_sqlite_enter()`，所以 `hold()` 里的 `_sqlite_depth() > 0` 守卫永远为 0。实测在 `wb.write_tx()` 内成功获取 `chapter_text` OS 锁，没有抛 `SqliteNestingError`。

**影响**：`lock_manager` 的“八级锁序 + SQLite/OS 锁不可嵌套”只是模块级单元测试；生产写入路径既没有锁序，也没有 rule 2 的实际拦截。任何后续代码按文档接入 `hold()` 时会误以为守卫生效；真正的死锁/嵌套风险未被覆盖。

**最小修复**：要么把 `lock_manager` 接入 `chapter_editor`/`outline_editor`/`transaction_journal`，并让 `wb.write_tx` 在 `BEGIN IMMEDIATE` 前后调用 `sqlite_scope()`；要么删除该模块及“八级锁序”文档承诺。若接入，补一条集成测试：`with wb.write_tx(): with lm.hold(...)` 必须抛错。

**复现**：`probe_extra.py` 输出 `L1_os_lock_inside_sqlite_tx acquired`；grep 见 `static-evidence.txt` 的 `grep lock_manager callers` 为空。

### P2-17 没有后台租约回收；`recovery_required`/过期 running 只能靠人工 POST

**位置**：`backend/manager/app.py:1189-1209`（lifespan 只启动 `dispatch` 和 `deliver_notifications`）；`backend/manager/api_v09.py:226-229`；`backend/integration/concurrent_engine.py:279-297`。

**机制**：`concurrent_engine.recover()` 只有 `POST /tasks/recover` 一个入口；`app.py` 的 lifespan 没有周期任务调用它。worker 崩溃后 `state='running'` 且 `lease_expires` 过期不会被任何人回收；`claim()` 用 `len(running) >= max_slots` 判断槽位，过期任务会一直占用槽位。`recovery_required` 也不在 `running` 计数里，但同样不会被自动处理。

**影响**：一次 worker 崩溃即可让该书队列永久卡死（P0/P1 无法 claim），直到作者/外部进程记得调用 recover；不符合“租约到期自动恢复”的文档语义。

**最小修复**：在 lifespan 增加周期任务（如每 10s，按项目列表）调用 `recover()`，并使用项目级锁避免多实例重复；`claim()` 前先回收过期租约；`recovery_required` 在 snapshot 中显式计数并在 UI 告警。

**证据**：`grep -rn "concurrent_engine" backend/manager --include=*.py` 只显示 `api_v09.py` 的路由调用（`static-evidence.txt`），lifespan 无调用；属静态缺口。

### P2-18 `task_queue` 与 `agent_tasks` 双轨，v0.9 调度不控制主编室真实任务

**位置**：`backend/integration/workbench_db.py:392-421`（`task_queue`）；`backend/integration/agent_room.py:99-117`（`agent_tasks`）；`backend/integration/agent_hub.py:306-319`；`backend/manager/api_v085.py:187-196`。

**机制**：v0.9 的 P0/P1/P2、三级暂停、父子、`blocked_by`、`hold_amendment` 全在 `concurrent_engine` 的 `task_queue`；主编室 `/directives/{id}/amend` 调用 `agent_hub.start_amendment()`，它更新的是 `agent_room.sqlite3` 的 `agent_tasks`（`status='held'`）。两者没有同步/桥接；`hold_for_amendment`/`release_amendment` 在生产代码中无调用者（grep 为空）。仓库中也没有调用 `claim()` 的执行器或 UI 消费 `task_queue`（`client.js` 无 `/tasks/`、`/world-state`、`quality/` 等 v0.9 路径）。

**影响**：作者在主编室发起的改令/暂停不会影响 `task_queue`，反之 v0.9 的优先级/槽位/租约也不会约束主编室任务；“P0 快道、P2 留一个作者槽位、改令挂起”在真实工作流中不生效。这是架构级功能落空，而非单点 bug。

**最小修复**：选定唯一任务事实源：让 `agent_hub` 的 amendment 调用 `concurrent_engine.hold_for_amendment`（并共享 task_id），或把 `task_queue` 的优先级/租约语义合并进 `agent_tasks`；删除/标记另一套；补端到端测试“改令后 agent_tasks 与 task_queue 同时 held”。

**证据**：`static-evidence.txt` 中 `CREATE TABLE ... agent_tasks`（`agent_room.py:99`）与 `task_queue`（`workbench_db.py:392`）并存；`grep hold_for_amendment` 无生产调用者。静态结论，未运行双系统联动。

### P2-19 `claim()` 在 `BEGIN IMMEDIATE` 内全表扫描候选，1000 条 pending 已 1.45s

**位置**：`backend/integration/concurrent_engine.py:189-219`，候选查询 `:199-201`、`_ready` `:176-186`、`claim` 写事务 `:193`。

**机制**：`claim()` 在写事务里读取全部 `pending`，按优先级排序后逐条 `_ready()`；`_ready()` 对每条 `blocked_by` 调 `get()`（新连接 + 查询），`_task_paused()` 对每条祖先链再查 `task_pauses`。当 P2 槽位已满（`p2_running >= max_slots-1`）时，所有 P2 候选都被扫描一遍后返回 None，扫描全程持有 `BEGIN IMMEDIATE`。

**影响**：1000 条 P2 pending、3 个 P2 running、max_slots=4 时 `claim()` 返回 None 耗时 **1.453s**，期间所有其他写事务被阻塞；1 万条时约 15s，超过 `busy_timeout=15s` 会导致 API 500。批量导入/历史积压会放大为可用性问题。

**最小修复**：候选查询下推到 SQL 并 `LIMIT`（按 priority/created_at），P2 槽位已满时直接不做 P2 查询；`blocked_by` 用一次 `IN (...)` 批量解析；暂停 scope 一次加载到内存集合；`claim` 尽量减少 `wb.initialize()`（每次 executescript）与嵌套连接。

**复现**：`probe_extra.py` 输出 `T2_claim_none True seconds 1.453`。

### P2-20 改令挂起状态机：running 直接改 held、release 后可被第二个 worker 再 claim；continue 字段永久残留

**位置**：`backend/integration/concurrent_engine.py:300-318`（hold）、`:333-347`（release）、`:76-80`（submit 继承）、`:256-265`（complete）。

**机制**：

- `hold_for_amendment(fallback="wait")` 对 `running` 任务直接 `state='held'`，但不清 `lease_owner/lease_expires`；原 worker 仍可能在写。`release_amendment()` 只把 `state='held'` 改回 `pending`，不清 lease；第二个 worker 可立即 claim 同一任务（实测 w1 仍在跑，w2 已 claim）。
- `fallback="continue"` 时任务状态保持 `pending`，但 `hold_amendment_id` 被写入；`release_amendment()` 只 SELECT `state='held'`，因此该字段永远不会被清除。之后 `submit(parent_task_id=parent)` 只要看到父任务有 `hold_amendment_id` 就把新子任务置为 `held`（`:76-80`），即使改令早已 release；`complete()` 也不清 `hold_amendment_id`。

**影响**：若该模块接入真实执行器，会出现同一任务双执行、作者改令后继续写旧稿、以及后续子任务永久卡在 held 的悬挂状态。当前 `hold_for_amendment` 无 HTTP 路由（见 P1-4 证据），所以定位为**库级 P2**；接入 API 后应升为 P1。

**最小修复**：running 任务不要改 `state`，改为设置 `hold_amendment_id` 标志，由 worker 在安全点检查并退出；`release_amendment` 只释放 `state='held'` 且 lease 已过期/无 owner 的任务；`complete`/`retry`/`release` 统一清理 `hold_amendment_id` 与 `amendment_fallback`；`submit` 继承时检查 amendment 是否仍 active（而不是字段非空）。

**复现**：`probe_engine2.py` 输出：

```text
3 after_hold= held owner= w1 expires=...
3 after_release= pending owner= w1
3 second_claim= ('task_...', 'w2')
4 parent_hold_after_release= amd2
4 child_state= held child_hold= amd2
```

### P2-21 `recovery_required` 的 retry 无 fencing；长 commit 期间租约到期会自触发 recovery

**位置**：`backend/integration/concurrent_engine.py:222-235`（renew）、`:238-246`（begin_commit）、`:321-330`（retry）；`backend/integration/test_concurrent_engine.py:82-93`。

**机制**：`begin_commit()` 只置 `committing=1`，不延长 `lease_expires`；`renew()` 在 `committing` 状态下**不续租**（`:224-228`），租约到期后调用 renew 会把任务标成 `recovery_required`（测试明确断言该行为）。`retry()` 对 `recovery_required` 直接 `state='pending', committing=0, attempts=0`，没有检查原 `lease_owner` 是否仍存活，也没有 fencing token。若原进程仍在写文件/提交，第二个 worker 会再次执行同一 commit。

**影响**：提交窗口超过剩余租约（默认 30s，含大量文件写入/fsync）时，活跃任务被判“需对账”；作者点重试即可与仍在运行的 commit 并发，造成重复写章/重复发布。测试把“提交中到期即 recovery”当成正确行为，但没有覆盖“原 worker 仍活着”的场景。

**最小修复**：`begin_commit` 把租约延长到独立的 commit deadline（如 now+300s），commit 期间 renew 继续延长；`retry(recovery_required)` 要求原 `lease_owner` 已死亡或显式 `force`，并生成新 fencing token 写入 `task_queue`；所有写入方校验 token。

**复现**：`probe_engine2.py` 输出：

```text
6 recovery= recovery_required committing= True
6 after_retry= pending committing= False
```

### P3-3 `ordered()` 同级别多锁按输入顺序稳定排序，固定相反顺序可死锁

**位置**：`backend/integration/lock_manager.py:106-113`。

**机制**：`rows = sorted(..., key=lambda row: row[0])` 只按 level 排序，稳定排序保留同 level 的输入顺序。调用 A `ordered([("chapter_text","1"),("chapter_text","2")])` 与调用 B 反序时，两者先各拿一把再等对方，flock 非阻塞 + 重试 5s 后报 `lock_busy`，表现为活锁/超时而非死锁检测。

**影响**：只要同一级别需要两把锁，锁序规则没有覆盖；当前无生产调用，故 P3。

**最小修复**：排序键加入 key：`key=lambda row: (row[0], row[1], row[2])`，或禁止同级别重复申请并在文档中要求合并为单锁。

**证据**：静态代码路径，未构造双线程复现。

### P3-4 `blocked_by` 缺失/自阻塞/父环无校验，任务永久 pending

**位置**：`backend/integration/concurrent_engine.py:63-92`、`:176-186`、`:128-143`。

**机制**：`submit` 把 `blocked_by` 原样写入 JSON，不校验 id 是否存在；`_ready` 对缺失 blocker 调 `get()` 抛 `SchedulerError` 后 `return False`，任务永远不 ready，也没有告警。自阻塞 `blocked_by=[own_id]` 同样永久 pending。`parent_task_id` 可形成 A→B→A（库级；API 不暴露 task_id，故当前 HTTP 不可构造），`_task_paused` 会无限循环并持有 claim 的写事务。

**影响**：一个拼错的 blocker 让任务静默卡死，不占用槽位但永远不执行；库级父环会让 `claim()` 卡死并阻塞该书所有写入。

**最小修复**：`submit` 校验 blocker 存在、非自身、无环（DFS 深度上限）；`_ready` 对缺失 blocker 记录 `blocked_missing` 事件并在 snapshot 中显示；`_task_paused` 加 visited 集合/深度上限。

**复现**：`probe_engine2.py` 输出 `5 claim= None state= pending`（blocker 为 `missing`）。

### P3-2 `spawn_worker` 把 stderr 合并进 DEVNULL，启动错误永远看不到

**位置**：`backend/integration/concurrent_engine.py:383-389`；`backend/integration/test_concurrent_engine.py:146-149`。

**机制**：`subprocess.Popen(..., stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)` 把 stderr 重定向到 stdout，而 stdout 是 DEVNULL；docstring 却写“Worker stdout/stderr are merged so startup errors never hide”。测试只 `inspect.getsource()` 断言包含 `stderr=subprocess.STDOUT`，没有验证输出去了哪里。

**影响**：worker 启动失败（import error、缺依赖）时没有任何日志，排障只能猜；当前 `spawn_worker` 无生产调用者，故 P3。

**最小修复**：`stdout=subprocess.PIPE`/日志文件，`stderr=subprocess.STDOUT`，由父进程读取并写入 `manager-logs`；或 `stderr=subprocess.PIPE` 单独收集。测试改为实际 spawn 一个向 stderr 打印的进程并断言日志文件非空。

**复现**：追加输出 `P1_spawn_stdout None stderr None returncode 0`。

---

## 4. 质量体检

### P2-10 A 轨本地体检消耗 B 轨“最多两次自动审稿”额度

**位置**：`backend/integration/quality.py:100-106`、`:109-130`（A 轨默认 `reviewer="auto"` 在 `:118-120`、`:130`）；`backend/integration/test_v09_quality.py:36-48`。

**机制**：`review()` 默认 `judgments=None`，走 `local_scores` A 轨，插入 `reviewer="auto"`；`_auto_count()` 统计 `reviewer!='author'` 的所有记录，因此两次零成本本地体检后，第三次 B 轨六维融合审稿会抛 `auto_review_limit`。文档说 A 轨“随时可跑、零模型费用”，B 轨才受 `MAX_AUTO_REVIEWS=2` 限制；测试用默认 A 轨调用两次再断言第三次被拒，等于把错误行为固化。

**影响**：作者点两次“快速体检”后，真正的 AI 六维审稿无法运行；“两轨”退化为共用同一额度。

**最小修复**：`_auto_count` 排除 A 轨（如 `reviewer NOT IN ('author','A-local')`），或给 `quality_reviews` 加 `track` 列并只统计 `track='B'`；A 轨仍可无限运行。

**复现**：`probe_quality.py` 输出 `B_after_two_A blocked auto_review_limit`。

### P2-11 自动审阅上限可被 `reviewer`/`force` 绕过，且“检查-插入”非原子（6 并发 6 条）

**位置**：`backend/integration/quality.py:100-106`、`:115-128`；`backend/manager/api_v09.py:253-259`。

**机制**：

- API 把请求体 `reviewer`、`force` 原样传入。`reviewer="author"` 直接跳过 `_auto_count`（`reviewer != "author"` 才检查）；`force=true` 也跳过。两者都不是作者身份证明，任何本地客户端可发。
- `_auto_count()` 读与后续 `INSERT` 不在同一写事务：`review()` 先查计数，再 `wb.write_tx` 插入。6 个线程同时进入时都读到 0/1，全部插入，实测 6 条 review 全部成功（上限 2）。

**影响**：`MAX_AUTO_REVIEWS=2` 的“铁律”在并发/直接 API 下失效，可能产生 6 次模型审稿成本；`reviewer` 字段可被伪造为 author，审计记录失真。

**最小修复**：在同一个 `write_tx` 内 `SELECT COUNT(*)` + `INSERT`（`BEGIN IMMEDIATE` 已串行化），计数条件加 `track='B'`；`reviewer` 只允许枚举值，`author`/`force` 必须来自经过作者确认的会话标志，不接受请求体裸布尔。

**复现**：`probe_quality.py` 输出：

```text
limit_bypass_third reviewed track B history 3
concurrent_results ['ok','ok','ok','ok','ok','ok']
stored_reviews 6
```

### P2-12 质量仪表盘把旧版本的 review 当作当前版本展示

**位置**：`backend/integration/quality.py:149-180`，读取最新记录在 `:154-166`。

**机制**：`dashboard()` 只按 `id` 取每章最后一条 `quality_reviews`，不比较 `row["version_id"]` 与 `versions.current_version(chapter)["version_id"]`；章节被修改后，仪表盘仍显示旧版本的 `total/verdict/reviewed_at`，并把 `reviewed` 计数加一。

**影响**：作者改稿后看到旧稿的“pass/68.61 分”，误以为新稿已审；质量门禁决策可能基于过期分数。

**最小修复**：对每章 `current_version` 比较 `version_id`；不一致时标记 `stale_review=true`，显示 `reviewed_version_id`，并回退到 `local_scores` 或“未审”状态；`reviewed` 只统计当前版本。

**复现**：`probe_quality.py` 输出：

```text
dashboard_version ver_0001_... current_version ver_0002_... stale True reviewed True
```

### P3-7 仪表盘 `limit` 只取最前 N 章，`track` 标签也可能错

**位置**：`backend/integration/quality.py:157`、`:130`。

**机制**：`for chapter in sorted(mapping)[:int(limit)]` 取的是章节号最小的 N 章，不是最近审阅的 N 章；500 章的书只显示前 200 章。`review()` 返回 `"track": "A" if reviewer == "auto" else "B"`，调用方传 `judgments`（六维 B 轨）但 `reviewer` 保持默认 `"auto"` 时会被标成 A；传 `reviewer="author"` 的本地 A 轨会被标成 B。

**影响**：长书后段永远不在仪表盘；双轨统计/展示错位。

**最小修复**：limit 改为按 `created_at`/章节范围分页；`review()` 增加显式 `track` 参数（`local`/`fused`），不要用 `reviewer` 字符串推断。

**证据**：静态代码路径。

---

## 5. API / 代理 / SSE

### P1-5 `/api/system/ai/pause` 不是全站急停：无 identity 是空操作，有 identity 只停一本书

**位置**：`backend/manager/api_v09.py:202-212`；`backend/integration/concurrent_engine.py:123-125`、`:146-154`；`backend/integration/workbench_db.py:410-414`；文档 `docs/plans/v0.8-v0.9/08_模型资源调度_费用控制与Agent权限.md:59`。

**机制**：

- `system_ai_pause` 在 `identity` 为空时直接 `return {"status":"ok","scope":"global","paused":True}`（`:206-208`），既不写暂停行，也没有任何全局存储。
- 带 `identity` 时 `book = _book(identity)`，调用 `concurrent_engine.pause(book, "global")`；`task_pauses` 表在每个项目的 `workbench.sqlite3` 里，`_paused(project,"global")` 也只查本项目。因此“global”实际是“该项目”。
- 文档明确写“全局 AI 急停（一键冻结全站新派发）”。

**影响**：作者在事故/超支时点击“全站急停”，界面返回成功，但其他书的 P0/P1/P2 任务继续被 claim；无 identity 的调用则什么也没发生。这是安全控制失效，不是普通 UI bug。

**最小修复**：在 manager 级 DB 或 `DATA/global_pause.json` 存全局暂停标志；`claim()` 增加 `global_pause` 参数/路径并首先检查；`system_ai_pause` 无 identity 时遍历 `store.projects()` 或在 manager 层写全局标志，绝不返回假成功；恢复同理。

**复现**：`probe_api.py` 输出：

```text
pause_no_identity 200 {'status':'ok','scope':'global','paused':True}
claim_after_global_pause True
pause_with_identity 200 {'status':'paused','scope':'global'}
other_book_claim True
```

### P1-6 `GET /room/stream` 必然失败：同步路由在线程池里调用 `asyncio.get_running_loop()`

**位置**：`backend/manager/api_v085.py:117-147`（`def room_stream`，`:126` `subscribe()`）；`backend/integration/agent_room.py:576-582`。

**机制**：`room_stream` 是普通 `def`，FastAPI 将其放入 anyio 线程池执行；`agent_room.broadcaster.subscribe()` 默认 `loop = loop or asyncio.get_running_loop()`，工作线程没有运行中的事件循环，抛 `RuntimeError: no running event loop`。在最小 `api_v085.install` 应用上实测请求直接 500；在完整 `app.py` 中会被 `RuntimeError` 处理器转成 400 `request_failed`，同样不可用。

**影响**：文档中的“SSE 四通道流 / Last-Event-ID 重放”完全不可用；任何依赖实时主编室事件的 UI 都拿不到流。当前 `client.js` 未出现 `/room/stream`（grep 为 0），所以影响被“未接入”掩盖，但 API 契约是坏的。

**最小修复**：把 `room_stream` 改为 `async def`（`StreamingResponse` 可由 async 函数返回），在协程内 `subscribe()`；`events_after` 的同步 DB 读取放到 `await asyncio.to_thread(...)`，避免阻塞事件循环；补一个直接请求该路由的 ASGI 测试（现有测试只测 JS 代理路径）。

**复现**：`probe_extra.py` 输出：

```text
S3_room_stream_raised RuntimeError no running event loop
  File ".../api_v085.py", line 126, in room_stream
    token, queue = agent_room.broadcaster.subscribe()
  File ".../agent_room.py", line 577, in subscribe
    loop = loop or asyncio.get_running_loop()
```

### P2-25 SSE 实时帧不按项目过滤：A 项目流收到 B 项目事件

**位置**：`backend/integration/agent_room.py:562-614`（`subscribe`/`publish`）；`backend/manager/api_v085.py:126-141`。

**机制**：`broadcaster.subscribe()` 不接收 project/topic 过滤器；`append_event()` 对每个事件调用 `broadcaster.publish(event)`（全局）；`room_stream` 只对**重放**的 `events_after(project_id=identity)` 做过滤，实时 queue 里的帧原样 `json.dumps` 下发。实测为 book-B 发布事件后，book-A 订阅队列收到 `project_id=book-B, summary='B 项目秘密'`。

**影响**：多作品同时打开时，A 的主编室流会显示 B 的对话/审批/任务摘要；重连后又消失（重放过滤），造成状态错乱和项目间信息泄露。

**最小修复**：`subscribe(project_id=...)` 保存过滤条件，`publish` 只投递匹配的订阅；或在 `frames()` 里对每个帧检查 `event["project_id"] in (identity, None)`，但过滤应发生在入队前，避免慢客户端被无关帧填满。

**复现**：`probe_agent.py` 输出：

```text
S1_queue_for_book_A 1
S1_leaked_project book-B summary B 项目秘密
```

### P2-26 SSE `Last-Event-ID` 重放只取前 200 条，超过部分永久丢失

**位置**：`backend/integration/agent_room.py:373-392`（默认 `limit=200`，`:386`）；`backend/manager/api_v085.py:128-132`。

**机制**：`events_after(...)` 默认 `limit=200`，`room_stream` 调用时没有传 limit、也没有循环翻页；一次 `for event in events_after(...)` 后立即进入 live 循环。若断线期间产生 250 条事件，重连只回放 seq 1..200，201..250 既不回放也不在订阅队列（订阅发生在回放前，队列只含回放开始后的新事件），客户端直接跳到后续 seq。

**影响**：断线超过 200 条事件后消息永久丢失，且没有 `resync_required`/`snapshot_seq` 标记，客户端无法知道缺口；在长任务/批量审稿时很容易触发。

**最小修复**：循环分页直到 `max_seq`，或把 `limit` 提高到可配置上限；回放结束发送 `: synced <seq>` 注释/`snapshot_seq` 事件；若仍有缺口，发送 `resync_required` 让客户端走 snapshot。

**复现**：`probe_agent.py` 输出：

```text
S2_replay_rows 200 first 1 last 200 max 250
S2_second_page 50 first 201
```

### P3-1 `/internal/events/notify` 不存在，`LoopbackNotifier`/`EventFanout` 是死路径

**位置**：`backend/integration/concurrent_engine.py:360-380`、`:392-426`；`backend/manager/app.py`（无 `/internal` 路由）；`backend/integration/test_concurrent_engine.py:112-149`；`index.js:41`、`:1085-1088`。

**机制**：`LoopbackNotifier.notify()` POST `http://127.0.0.1:{port}/internal/events/notify`，但 `app.py` 没有该路由（grep `/internal` 只命中类 docstring 与测试）；即使加上，`local_guard` 对非 GET 要求 `X-Novel-Helper: 1`，而 notifier 只带 `X-Internal-Token`（`app.py:1242-1246`）。代理只注册 `/novel-helper` 前缀，`/internal` 不在代理内（`index.js:41`、`:1085-1088`）。`LoopbackNotifier`/`EventFanout` 在生产中无调用者，测试用 fake opener 只验证 URL/body/token。

**影响**：如果未来把 worker 唤醒接到 `LoopbackNotifier`，永远收到 404/403；测试给出的是“接口形状正确”的假安全感。当前是死代码，故 P3。

**最小修复**：要么实现 `/internal/events/notify`（并允许内部 token 通过 `local_guard`），要么删除 `LoopbackNotifier`/`notify_callback`/`EventFanout`；测试改为对真实 FastAPI 路由发请求，而不是 fake opener。

**证据**：`static-evidence.txt` 的 `grep internal route` 无 `app.py` 路由；`test_concurrent_engine.py:133` 只断言 URL 字符串。

### 正向验证（API / 代理）

- **所有 v0.8–v0.9 API 的非 GET 路由都在 `WRITE_ROUTES`**：脚本枚举 `api_v08.py`/`api_v085.py`/`api_v09.py` 共 **62** 条非 GET，`WRITE_ROUTES` 缺失 **0**（`static-evidence.txt` 输出 `non_GET 62 missing_in_WRITE_ROUTES 0`）。`POST /api/chief/messages`、`POST /api/system/ai/pause`、`POST /api/system/diagnostics/recover` 均在表内（`index.js:243/254/278`）。
- **`/internal/*` 未误入代理**：`parseTarget` 只接受 `/novel-helper/...`，随后 `suffix` 必须以 `/api/` 开头（`index.js:1085-1088`）；`/internal/...` 与 `/novel-helper/internal` 都到不了 manager。管理器也没有 `/internal` 路由，故不存在“内部路由被外部代理”的问题；代价是 P3-1 的 notifier 死路。
- **SSE 代理头部正确**：`forward()` 转发 `last-event-id`（`index.js:872-874`），对 `text/event-stream` 清除 upstream timeout 并逐块转发（`:906-942`），不会把 40 秒预览缓冲成一整块。问题在 manager 端（P1-6/P2-25/P2-26），不在代理。
- **备份/旧版导出路径有保护**：`transaction_journal.backup()` 拒绝 `destination_inside_project`（`:1147-1152`），`export_legacy()` 同样拒绝 `destination_inside_project`/`inside_source`（`:1624-1633`）；这与 P1-2 的 `export_bundle` 形成对比，说明保护是可行的。
- **自愈动作白名单**：`self_heal` 只接受 `rebuild_search`/`checkpoint`，其他抛 `unsafe_heal_action`（`maintenance.py:252-261`），没有任意路径/命令执行面；问题只是 `rebuild_search` 空操作（P2-15）。
- **诊断包剥离正文/密钥**：`_strip()` 删除 `content/body/outline/card_md/text` 等键并截断长字符串（`maintenance.py:204-212`）；`test_v09_maintenance.py:41-58` 也验证了正文和 `sk-secret` 不出现。P3-6 只涉及标题字段。
- **`write_tx` 基础配置正确**：WAL、`busy_timeout=15000`、`BEGIN IMMEDIATE`、指数退避（`workbench_db.py:73-135`）；问题在 `claim()` 把大量只读检查塞进写事务（P2-19），不是事务实现本身。

---

## 6. 运行时清单 / 构建脚本

### P2-22 升级清理按“新清单”删除已复制的源码；清单漏项会删掉仍存在的文件

**位置**：`managed-runtime.mjs:273-299`（`staleCodeFiles`/`removeStaleCode`）、`:481-501`（先 `cp` 源码，再 `removeStaleCode`，最后 `verifyInstalled`）。

**机制**：`prepareManaged` 先把 `PACKAGE_ROOT/backend/<tree>` 整棵复制到安装目录（`:481-487`），然后 `removeStaleCode(rootDir, installed?.codeFiles, codeFiles)` 删除“上一版清单有、这一版清单没有”的文件。删除集合完全由**新 manifest** 决定，而 `verifyInstalled` 也只按同一份新 manifest 校验。若新 manifest 漏列一个仍在源码树中的文件（构建脚本漏扫、手工裁剪、清单损坏），该文件会在复制后被删除；`verifyInstalled` 不预期它，所以校验通过，安装标记照写，运行到 import 时才失败。空 `manifest.files` 时 `staleCodeFiles` 返回上一版全部代码路径，甚至会把刚复制的 `app.py` 删除。

**影响**：一次清单漏项即可造成“安装成功但后端缺模块/无法启动”；用户重装也会重复删除（复制→删除→校验通过），形成难以自愈的升级循环。

**最小修复**：删除前检查 `existsSync(join(codeRoot, name))`，只删除**源码树中已不存在**的文件；`verifyInstalled` 与删除决策不要共用同一份未验证清单；安装后跑一次 `python -c "import manager.app"`/健康检查；`manifest.files` 为空时直接失败，不进入删除流程。

**复现**（Node 单元）：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v095
node probe_stale.mjs
# removed 1 exists_after false
```

即 `nextFiles=[]` 时，上一版清单里的 `integration/needed.py` 被删除；触发条件是静态的“清单漏项”，机制已实证。

### P2-23 `sameCandidate` 快速路径只校验 manager/integration 两棵代码树

**位置**：`managed-runtime.mjs:459-465`。

**机制**：`sameCandidate` 为真时调用 `verifyInstalled(config.rootDir, manifest, ['manager', 'integration'])`，只校验两棵树；`webnovel-writer`、`fanqie_auto_publish`、`vendor` 被跳过。完整安装路径（`:498`）用 `CODE_TREES` 全部五棵。

**影响**：本地修改 `fanqie_auto_publish/publish.py`（发布逻辑）或 `vendor`，只要 buildId 标记匹配，启动即被当作“已安装一致”，不会触发重装/告警；完整性校验存在盲区。

**最小修复**：快速路径也传 `CODE_TREES`；或至少对 `fanqie_auto_publish` 与 `webnovel-writer` 做抽样哈希。成本可接受（1188 个文件）。

**证据**：静态行 `:460`；无运行时复现。

### P2-24 CI 的 `check-release --local` 跳过全部 2253 个 runtime 条目

**位置**：`.github/workflows/ci.yml:25`；`scripts/check-release.mjs:83-97`；`runtime-manifest.json`；`.gitignore:2`。

**机制**：CI 只运行 `node scripts/check-release.mjs --local`。`bundledRuntime` 仅在 `root/runtime/python/python.exe` 存在时为真；`runtime/` 被 `.gitignore` 忽略，干净检出没有 `python.exe`，于是 `:94-97` 对所有 `runtime/` 条目 `continue`，只统计 `skippedRuntime`。HEAD 清单含 **2253** 个 runtime 条目、**1188** 个 backend 条目；CI 实际校验后者。完整包构建时才由 `pack-bundle.py`/`check-release`（无 `--local`）校验 runtime。

**影响**：“CI 全绿”不能证明 runtime 清单未误删/未漏项；如果某次构建把 runtime 条目删掉，CI 仍绿，直到完整包打包/安装才暴露。与本次审计重点“runtime 条目是否误删”直接相关。

**最小修复**：在 distribution workflow 中跑非 `--local` 的 `check-release`；或在 CI 用一份固定的 runtime 文件占位树/发布资产校验 2253 个哈希；至少增加“manifest.runtime 条目数不得低于基线”的断言。

**证据**：`static-evidence.txt`：`backend_entries 1188 mismatches 0 missing 0`、`runtime_entries 2253`、`buildId_ok True`；`ci.yml:25`。

### P3-8 `build-runtime.py` 先写“只有元数据”的 manifest，再扫描文件；中途失败会把清单清空

**位置**：`scripts/build-runtime.py:105-110`（先写 `manifest` 5 个键），`:49-72`（`write_manifest` 末尾才写完整 files）。

**机制**：`main()` 在 `:108` 先 `write_text(json.dumps(manifest))`，此时 `manifest` 只有 `platform/python/pythonSource/pythonSha256/distributionStatus`；随后调用 `write_manifest()`。如果扫描阶段因缺目录、符号链接、CRLF 等抛错，进程退出，仓库里的 `runtime-manifest.json` 已被截成 5 键、无 `files/buildId/packageVersion`。下次 `check-release --local`/`pack-bundle` 直接失败，且旧清单不可恢复（未用临时文件+rename）。

**影响**：一次失败的构建会污染工作区清单；在 CI 上会表现为“清单突然没有 files”，需要手动从 git 恢复。

**最小修复**：先在内存构造完整 `manifest`，写临时文件后 `os.replace` 原子替换；任何扫描错误发生在写盘之前；构建失败时保留旧文件。

**证据**：静态代码路径；未执行破坏性构建。

---

## 7. 测试盲区（解释“CI 全绿”与上述发现并存）

1. `backend/integration/test_v09_maintenance.py:22-39` 只测“未登记的孤文件被删、当前章节被保护”，没有测 `artifact_refs`、`outline-backups`、目录符号链接、默认 `dry_run`。
2. `backend/integration/test_concurrent_engine.py:66-93` 只测显式 hold 的任务，没有测“已有子任务在父任务 held 后仍可 claim”；`test_spawn_worker_merges_stderr`（`:146-149`）只检查源码字符串，不断言输出目的地。
3. `backend/integration/test_world_state.py:120-143` 的高风险用例显式传 `"pinned": True`，恰好绕过 P1-3 的缺陷；没有默认 `confirmed_prose`、重复提取、`future_plan`、GET 写 manifest 的用例。
4. `backend/integration/test_v09_quality.py:36-48` 用 A 轨默认调用验证“两次上限”，把 P2-10 的错误行为固化为期望；没有并发/`force`/版本过期用例。
5. `test/workbench-core.test.mjs:372-384` 只验证代理转发 `/room/stream` 的 URL，没有在 manager 进程内请求该路由；因此 P1-6 的 500 不会被发现。
6. `backend/integration/test_build_scripts.py` 只测 Linux/macOS service archive 的 `--verify`，没有覆盖 `build-runtime.write_manifest`、`pack-bundle`、`staleCodeFiles`、`sameCandidate` 快速路径。

---

## 8. 附录：复现输出（关键行）

完整输出见 `/home/ubuntu/.hermes/cache/scratch/audit-v095/outputs.txt`。关键摘录：

```text
### probe_world2
A_duplicate_rows 2
B_order [('f_pub','published_prose'), ('f_author','author_locked')]
C_after_ignore_ch1 0 ch2 0
D_missing_pinned accepted 1 pending 0 status active authority confirmed_prose
D2_ai_authority_written author_locked
D3_pending_visible 1 0 0
E_state_calls_manifests 0 -> 2
F_budget 500 chars 512 [('L1',0,None),('L2',0,True),('L3',0,True),('L4',500,True),('L5',0,True)]
F_budget 150 chars 162 ...
G_chapter_filter hits 0 chapters []
H_L5_items [{'kind':'retrieval','doc_key':'正文:10','chapter_id':10,'layer':'L5'}]
I_author_locked object 死亡 author_locked False
J_future_plan_in_ch1 [('f2','future_plan')]
K_invalid_confidence ValueError could not convert string to float: 'high'

### probe_engine2
2a pending_completed= completed
2b recovery_state= recovery_required
2b after_complete= completed
3 after_hold= held owner= w1 expires=...
3 after_release= pending owner= w1
3 second_claim= ('task_...', 'w2')
4 parent_hold_after_release= amd2
4 child_state= held child_hold= amd2
5 claim= None state= pending
6 recovery= recovery_required committing= True
6 after_retry= pending committing= False

### probe_maint
1 registered= art_... exists_after_gc= False removed= 1
2 outline_backup_exists= False removed= [.../outline-backups/outline-v1.md]
3 fresh_deleted= True count= 1
4 chapter_bytes_before= 22 after= 865 zip_magic= b'PK'
5 ledger= {...全部 0...}
6 has_rebuild_search= False result= {'status':'healed','action':'rebuild_search'}

### probe_api
GET world-state 200 manifests 0 -> 1
GET world/context 200 manifests 1 -> 2
pause_no_identity 200 {'status':'ok','scope':'global','paused':True}
claim_after_global_pause True
pause_with_identity 200 {'status':'paused','scope':'global'}
other_book_claim True
recover_gc 200 removed 1 file_exists False
export 200 chapter_before 7 after 871 magic b'PK'

### probe_quality
limit_bypass_third reviewed track B history 3
B_after_two_A blocked auto_review_limit
dashboard_version ver_0001_... current_version ver_0002_... stale True reviewed True
concurrent_results ['ok','ok','ok','ok','ok','ok']
stored_reviews 6

### probe_agent
S1_queue_for_book_A 1
S1_leaked_project book-B summary B 项目秘密
S2_replay_rows 200 first 1 last 200 max 250
S2_second_page 50 first 201

### probe_extra
L1_os_lock_inside_sqlite_tx acquired
T1_parent held child running claimed_child True
T2_claim_none True seconds 1.453
M1_health_raised DatabaseError file is not a database
M2_victim_exists False
S3_room_stream_raised RuntimeError no running event loop
P1_spawn_stdout None stderr None returncode 0
```

---

## 9. 汇总建议（按发布阻断顺序）

1. **先修数据丢失面**：P1-1（GC）、P1-2（导出覆盖）、P2-16（system_recover 默认真删）、P2-14（诊断 500）。
2. **再修任务状态机**：P1-4（complete/fail/owner）、P2-21（commit fencing）、P2-17（自动 recover）、P2-20（改令状态机）。
3. **再修世界状态可信度**：P1-3（AI 权威/高风险/待确认）、P2-2/3/4/5/6/7/8/9。
4. **再修安全控制与 SSE**：P1-5（全站急停）、P1-6（room_stream）、P2-25/26。
5. **最后修发布完整性**：P2-22/23/24、P3-8。

> 本报告为只读审计；未对仓库做任何修改，未提交 PR。HEAD `fe2bc32` 的 `runtime-manifest.json` backend 部分自洽（1188 条、0 mismatch、buildId 复算一致），但 runtime 部分 2253 条因 `runtime/` 不入库且 CI `--local` 跳过而未被验证（见 P2-24）。
