# A 域独立审计报告：核心数据 / 版本 / 章节 / 批注 / 合并

- 审计工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v3/head-a`，detached `4f5a5a1`
- 审计范围：`backend/integration/` 下 `workbench_db.py`、`transaction_journal.py`、`chapter_versions.py`、`chapter_editor.py`、`version_history.py`、`outline_editor.py`、`invalidation.py`、`revision_plan.py`、`studio.py`、`resident_service.py`、`annotations.py`、`text_merge.py`、`quality.py` 及对应测试
- 审计方式：逐行读代码 + 在 `tmp-a/` 写只读探针做故障注入；未修改仓库、未 commit、未联网
- 基线测试（仓库根）：
  ```
  PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
    /home/ubuntu/venvs/dsh/bin/python -B -X utf8 -m unittest discover -s backend/integration -t backend
  → Ran 1208 tests in 101.6s, OK (skipped=9)
  ```
- 探针目录：`/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-a/`，`probe_a1.py` … `probe_a6.py`

## 0. 严重度口径

| 级别 | 口径 |
|---|---|
| P0 | 直接丢正文/不可恢复的破坏；本次未发现 |
| P1 | 静默产生正文或版本身份不一致、核心升级/恢复路径不可用，且无自动修复 |
| P2 | 索引/备份/回执/批注状态不一致，或需要手工绕过；不直接丢用户正文 |
| P3 | 契约、展示、清理、幂等边界类问题 |

## 1. 结论计数

| P0 | P1 | P2 | P3 |
|---|---|---|---|
| 0 | 4 | 11 | 9 |

另有 6 条只读推演、未做故障注入的 **HYPOTHESIS**，不计入上表（见 §6）。

所有 P0/P1/P2/P3 条目均已用探针复现；每条附 `file:line`、机制、影响、最小修复、探针命令与关键输出。上一轮残余 A-R-03/04/05/06、A-P2 outline legacy、backup 缺版本对象、merge_tail 空 params、B-01R-4 均已重新复现并重判，见 §7 对照表。

---

## 2. P1

### P1-01 提交后的标题改名与回执更新不在事务/恢复状态机内；失败后重试返回成功但永不补齐（A-R-03/A-R-06）

**位置**
- `backend/integration/chapter_versions.py:1130-1186`（`restore_version`：先 `commit_raw_bytes`，再改名，再 `_update_receipt_destination` / `_update_commit_chapter_path`）
- `backend/integration/chapter_versions.py:1095-1113`、`1116-1127`（回执与 commit 记录更新；只捕获 `OSError/ValueError`，`PublicationBlocked` 会直接逃逸）
- `backend/integration/chapter_versions.py:663-789`（`recover_pending`：第 678 行把 `committed` 当终态直接跳过，不含改名/回执补偿）
- `backend/integration/chapter_editor.py:571-572`（`save_version` 在 `write_chapter` 提交后才 `_rename_chapter_file`）
- `backend/integration/chapter_editor.py:447-483`（`_recover_completed_save` 只校验 commit/正文/索引，不校验磁盘文件名标题，也不更新回执）

**机制**
1. `restore_version` 的正文提交（对象/正文/索引/commit=committed）与目标文件名改名、回执 `destination`、commit 记录 `chapter_path` 是四个独立步骤，没有 durable 状态。
2. 改名成功后回执写入失败（ENOSPC、权限、`writer_receipts.json` 损坏导致 `read_json_strict` 抛 `PublicationBlocked`）→ `restore_version` 抛异常，调用方看到 500；此时正文已是旧版本、文件已改名为旧标题，但回执仍指向已不存在的“新标题”路径，commit 记录 `chapter_path` 也仍指向旧路径。
3. 客户端用同一 `op_id` 重试：`commit_raw_bytes` 命中已 committed 且正文/索引匹配，直接返回旧记录；`needs_rename` 此时为 False，于是既不改名也不更新回执/commit path，`title_renamed` 还被置为 `True`。永久不一致。
4. 进程在“commit 完成、改名未做”之间死亡：`recover_pending` 看到 `state=committed` 直接跳过；索引里的版本标题是历史标题，磁盘文件名仍是当前标题；若之后没有用户再次 restore，不会修复。
5. `save_version` 同构：`write_chapter` 提交后 `_rename_chapter_file` 失败（Windows 文件占用/AV）→ 409；重试走 `_recover_completed_save`，只校验 sha/索引，直接返回 `saved/recovered=True`，标题改名永远不会发生。

**影响**
- `writer_runner.reviewed_chapters/committed_chapters` 要求 `receipt["destination"] == 实际路径`；回执过期会让该章从可发布/已提交集合中静默消失（`writer_runner.py:218`、`draft_delivery.py:86`、`scheduler.py:792`）。
- 标题（索引/版本）与文件名（`chapter_state().title` 来自文件名）长期分叉，历史和 UI 各显示一套。
- 属于“静默状态丢失 + 需手工修”的 P1，而不是正文丢失。

**最小修复**
- 把“目标文件名、回执 destination、commit.chapter_path”写入 commit 记录的 durable 字段（例如 `pending_title`/`title_rename_done`），`recover_pending` 对 `committed` 但 `title_rename_done=false` 的记录补做幂等改名与回执同步；
- 或在 `restore_version`/`_recover_completed_save` 里无条件做一次幂等对账：以 `versions.chapter_path()` 的实际文件名为准，若文件名标题 != 记录标题则尝试改名，并把回执 destination 同步到实际路径（失败降级为明确的 partial 结果而不是谎报成功）；
- `_update_receipt_destination` 应捕获 `PublicationBlocked` 并转为结构化 partial，而不是让它在改名后 500。

**探针**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-a
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
  /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a1.py
```
关键输出（CASE 1，回执写入失败后重试同一 op_id）：
```
after failed receipt update files: ['第1章-旧标题.md']
after failed receipt update destination: .../第1章-新标题.md
retry title_renamed: True title_conflict: None
after retry receipt destination: .../第1章-新标题.md      # 仍是坏路径
after retry commit chapter_path: .../第1章-新标题.md      # 仍是坏路径
```
CASE 2（commit 后、改名时进程死亡）：
```
commit state: committed title: 旧标题 chapter_path: .../第1章-新标题.md
index current title: 旧标题
files after recover: ['第1章-新标题.md']
recover_pending: []
index title after recover: 旧标题
```

---

### P1-02 `apply_hunks` 草稿写与 hunk/ledger 状态是两个事务；崩溃后重试会把插入型修改重复应用（B-01R-4）

**位置**
- `backend/integration/annotations.py:732-883`（`_apply_hunks_impl`）
- `backend/integration/annotations.py:795-816`（`chapter_editor.save_draft`，独立的 `wb.save_draft` 事务 + 独立 FTS 事务）
- `backend/integration/annotations.py:819-873`（第二个 `wb.write_tx`：hunk 状态、patch_ledger、preview_index）
- `backend/integration/text_merge.py:397-482`（重试时从当前草稿重新判定 hunk）

**机制**
1. `_apply_hunks_impl` 先调用 `chapter_editor.save_draft(...)` 把合并结果写入草稿（事务 1），然后才在第二个事务里把 hunk 置 `applied_to_draft`、写 `patch_ledger`。
2. 两事务之间失败/进程死亡：草稿已含修改，hunk 仍 `pending`、ledger 为空。
3. 客户端之后刷新草稿身份再点“应用”（新 op_id、新的 `expected_draft_*`）：
   - **插入型** hunk（before_text 仍完整存在，replacement 是追加）：`relocate_anchor` 能找到原 quote，`delta_ranges` 里的插入点与 hunk 的 `[start,end)` 不相交，`_overlaps` 为 False → **再插入一遍**；随后 hunk 被置 applied。
   - **替换/删除型**：原 range 已被替换/删除，`relocate_anchor` 走 `_range_in_replace` → `overlap_conflict`；hunk 永远 pending，草稿却已含修改。没有“已应用”证据可恢复。
4. 即使客户端用**原请求参数**重试，`expected_draft_*` 已失配（首次调用前无草稿、现在有 rev1），得到 `draft_conflict`；用刷新后的身份重试才会触发上面的重复插入。

**影响**
- 插入型修改会造成**草稿正文静默重复**（相当于作者重试一次就多一句），是实际文本损坏路径。
- 替换/删除型会造成“正文已改、hunk 永久 pending、annotation 永远 proposed/partially_applied”的死状态；用户只能丢弃草稿（丢其他编辑）后重来。
- 现有测试只覆盖“单事务成功”和 ledger 跨快照，没有覆盖两事务之间的崩溃窗口。

**最小修复**
- 将草稿行更新（`chapter_drafts` + `drafts_history` + epoch 校验）与 hunk 状态、`patch_ledger`、`preview_index` 合并进**同一个 SQLite 事务**；或
- 在写草稿前先持久化 `apply_intent`（hunk 集合 + 预期草稿身份 + 目标文本 sha），第二个事务失败后由恢复入口据此判定“已落草稿”并只补状态，绝不再次改文本；
- 至少对插入型 hunk 在应用前检查 `replacement` 是否已紧邻 `before_text` 出现并返回 `already_applied`，作为兜底（不能覆盖所有边界）。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a2.py
```
关键输出（CASE 7/insert，第二个事务人为失败后，用刷新后的草稿身份重试）：
```
first apply raised: RuntimeError simulated process death before hunk state tx
draft after crash: '开头一句。\n她推开门。又停了停。\n结尾一句。\n'
hunk status after crash: pending applied_draft_id: None
ledger rows: []
fresh-identity retry: applied clean: True conflicts: []
final draft: '开头一句。\n她推开门。又停了停。又停了停。\n结尾一句。\n'
```
替换型（同一脚本 CASE 7/replace）：
```
fresh-identity retry: conflict ... reason: selection_changed
hunk status after retry: pending
```

---

### P1-03 split 回滚无条件覆盖/删除并发保存的 chapter+1 索引与回执

**位置**
- `backend/integration/chapter_editor.py:1092-1142`（`_rollback_split`）
- 关键行：`1125-1131`（`next_entry` 为空就 `index["chapters"].pop(str(chapter + 1))`）
- 关键行：`1138-1141`（无条件 `_drop_receipt(project, chapter + 1)`）
- `backend/integration/chapter_editor.py:1193-1210`（split 先提交 chapter+1，再截断 chapter；全程只持 chapter 锁）

**机制**
1. `split_chapter` 只锁 `chapter`，不锁新生成的 `chapter+1`。
2. 第一次 `commit_raw_bytes(chapter+1)` 成功后，另一个客户端可以合法地保存 `chapter+1`（`save_version` 只锁 chapter+1）。
3. 第二次 `commit_raw_bytes(chapter)` 失败时，`_rollback_split` 用 split 之前拍下的 `next_entry`（空）判断：`elif str(chapter+1) in index: pop`，**无条件删掉并发保存刚写入的 chapter+1 索引项**；同时无条件 `_drop_receipt(chapter+1)`。
4. 并发保存的正文文件因 sha 不等于 split 的 `second_sha` 被保留，但其版本索引/当前版本指针/回执全部丢失 → 索引有文件、无 entry；`current_version(chapter+1)` 返回 None；后续保存退化成“老稿首次编辑”。

**影响**
- 违反“版本对象/manifest/索引一致性”：正文在、索引无；并发作者的版本历史不可见，回执（若已确认）被删。
- 属静默丢失并发写者的版本身份，P1；正文字节本身未丢。

**最小修复**
- 回滚 chapter+1 前先校验“当前索引 entry 仍是本次 split 生成的”（例如 `entry.current == second_sha` 或最后版本的 `op_id == op_b`）；不匹配则保留并发 entry，并在返回结果里报 `split_rollback_skipped_concurrent`。
- 同理，只有 chapter+1 仍等于本 split 产生的正文/回执时才删除索引和回执；否则保留并以 409 返回人工处理。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a5.py
```
关键输出（CASE 22）：
```
split raised: RuntimeError simulated first-half failure
chapters: [1, 2]
index keys: ['1']
  ch2 file=第2章-并发保存的下半章.md disk_sha=4a6594defad9 index_current=MISSING
  ch2 current_version=None
chapter_state(2): {'title': '并发保存的下半章', ..., 'version_id': None}
```

---

### P1-04 v0.7.5 `story_plan.json` 的 chapters 列表格式会使大纲读/写/恢复全部 500，并把空 `legacy_chapters` 固化进 meta

**位置**
- `backend/integration/outline_editor.py:205-243`（`load_meta`；第 239 行只在 `chapters` 是 dict 时写入 `legacy_chapters`，list 直接变成 `{}`，随后 `safety.atomic_json(meta)` 落盘）
- `backend/integration/outline_editor.py:409-445`（`conflicts`：`set((story.get("chapters") or {}).keys())`，list 无 `.keys()`）
- `backend/integration/outline_editor.py:492-542`（`recover_plan`；第 525 行 `previous = value.get("chapters") or {}`，第 530 行 `sorted(previous, key=lambda key: int(key))`，元素是 dict 时 `int(dict)`）
- `backend/integration/studio.py:235-278` 的旧版兼容明确说明“规划章节既可能是列表，也可能是 {章号: {...}}”

**机制**
1. v0.7.5 的 `workflow._plan_chapters` 注释和旧 `studio.recover_plan` 都明确支持 `chapters` 为 list；这是实际存在过的格式。
2. 升级后第一次打开大纲（`GET outline/files` → `load_meta`）：`legacy_chapters` 变成 `{}` 并写入 `story_plan_meta.json`，随后 `files()` 内 `conflicts()` 读 story_plan 的 list 调 `.keys()` → `AttributeError` → 500。
3. `write_meta`/`recover_plan`：`previous` 是 list，`sorted(..., key=int)` → `TypeError`；`write_meta` 在异常前已经写入 meta，等于“写一半”。
4. `studio.plan_async` 的 `except (ValueError, OSError, RuntimeError)` 不包含 `TypeError`；一旦 meta 已被 `load_meta` 提前创建，后续 AI 规划也直接崩。
5. `world_state._outline_for` 会 catch 所有异常降级，但它同样会先 `load_meta`，把空 `legacy_chapters` 固化；即使用户只是打开世界观面板，也会不可逆地丢掉升级快照。

**影响**
- 对 list 格式旧书：大纲 tab 500、`write_meta` 500、AI 规划失败、`world_state` 大纲降级；`legacy_chapters` 空快照落盘后，后续即使修好代码也无法从 meta 恢复这些章节细纲。
- 属于升级迁移不可用 + 迁移证据被提前写坏，P1。

**最小修复**
- 在 `load_meta` 首次迁移时把 `chapters` 的 list 规范化为 `{str(id): item}` 后再写 `legacy_chapters`（与 `studio.recover_plan` 的规范化逻辑复用）；
- `conflicts`/`recover_plan` 对 list 先规范化，`sorted` 前过滤非 int key；
- 迁移写 meta 前先完成规范化，失败不落 meta（或写临时文件后原子替换）。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a3.py
```
关键输出（CASE 15；story_plan: `"chapters": [ {...}, {...} ]`）：
```
meta legacy_chapters: {}
files raised: AttributeError 'list' object has no attribute 'keys'
conflicts raised: AttributeError 'list' object has no attribute 'keys'
recover_plan raised: TypeError int() argument must be ... not 'dict'
write_meta raised: TypeError int() argument must be ... not 'dict'
```

---

## 3. P2

### P2-01 soft `op_id` 完成后不幂等：重试 409/404，超时重跑可能重复执行（A-R-05）

**位置**
- `backend/integration/chapter_editor.py:417-434`（`_idempotent_soft` / `_finish_soft`；`_finish` 在 402-414 吞掉所有完成失败）
- 调用点：`new_chapter` 642、`delete_chapter` 742、`split_chapter` 1151、`merge_tail` 1254、`import_chapters` 1354、`restore_trash` 987、`outline_editor.write_file` 558-569
- `backend/integration/workbench_db.py:847-900`（`idempotency_begin`：`in_progress` 10 分钟后才允许接管）

**机制**
- 操作成功但 `wb.idempotency_complete` 失败（SQLite busy/磁盘满）；`_finish` 吞掉异常，第一个响应仍是成功，但幂等键停在 `in_progress`。
- 客户端因超时/丢响应重试：10 分钟内一律 `op_in_progress` 409；10 分钟后 `idempotency_begin` 重置为 `failed_retry` 并**重新执行**，此时业务状态已变：
  - `delete_chapter` → `chapter_missing` 404；
  - `merge_tail` → `merge_needs_two_chapters` 409；
  - `split_chapter` → 只允许尾章，409；
  - `import_chapters` → `chapter_exists` 409；
  - `restore_trash`（带 op_id）→ `operation_id_reused`，不带 op_id 则生成重复章（见 P2-05）。
- 与 `save_version` 不同，soft 操作没有 `_recover_completed_save` 那样的“从 commit 标记重建响应”路径。

**影响**
- `op_id` 契约（A-P2-10）名义存在但完成后不可重放；客户端无法确认“删/合/导入是否已生效”，只能靠读列表猜测。

**最小修复**
- soft 操作的 commit/trash/manifest 记录里持久化最终响应摘要（或 action+op_id 映射），`_idempotent_soft` 在 `in_progress`/`failed_retry` 时先从权威状态重建已完成响应；
- 或把 `idempotency_complete` 改为同业务事务提交（同一 SQLite 事务/同一次文件写），让“成功”与“已记录”原子化；
- 至少 10 分钟接管前检查业务事实（例如 chapter 已不存在 → 返回 cached deleted，而不是 404）。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a1.py   # CASE 4（立即重试 409）
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a7.py   # CASE 28（TTL 后重跑 404/409）
```
关键输出：
```
new_chapter first: created 1
new_chapter retry raised: ChapterError op_in_progress
merge_tail first: merged 1
merge_tail retry raised: ChapterError op_in_progress
```
10 分钟接管后（单独探针）：
```
delete retry raised: ChapterError chapter_missing
merge retry raised: ChapterError merge_needs_two_chapters
```

---

### P2-02 标题改名竞态会留下同章双文件；`_recover_completed_save` 掩盖未改名，重试后章节不可读

**位置**
- `backend/integration/chapter_editor.py:554-559`（preflight 只检查改名目标是否已存在）
- `backend/integration/chapter_editor.py:571-572`（提交后才改名）
- `backend/integration/chapter_editor.py:615-634`（`_rename_chapter_file`；目标存在即 `chapter_filename_conflict`）
- `backend/integration/chapter_versions.py:221-256`（`chapter_path` 发现两个章号文件即 `duplicate_chapter_files`）

**机制**
- preflight 与 `_rename_chapter_file` 之间有窗口；外部编辑器/同步工具/另一个进程在此期间创建 `第N章-新标题.md` 后，`save_version` 已经在旧文件名写入了新正文和索引，然后改名失败抛 409，留下旧文件名 + 新文件名两份同章文件。
- 重试时 `_recover_completed_save` 先调用 `versions.chapter_path` → `duplicate_chapter_files`（VersionConflict），不会进入 restored 分支；`chapter_state`（GET）也直接 409。
- 若竞态文件随后被删，重试会 `recovered=True` 返回成功，但改名从未发生（版本标题是新标题、文件名仍是旧标题）——与 P1-01 同根。

**影响**
- 章节被双文件“锁死”直到手工删除其中一个；即便恢复单文件，标题也未真正应用。P2（触发窗口窄，但恢复路径很硬）。

**最小修复**
- `_rename_chapter_file` 失败时若检测到“目标已存在且当前文件仍是本事务刚写入的正文”，应把这次提交标记为 `title_pending` 并在响应里明确 `renamed=false`+冲突路径，而不是让普通重试走 `recovered=True`；
- `_recover_completed_save` 增加文件名标题校验（见 P1-01），不匹配时返回 None 让正常路径重试改名；
- 改名实现改为“先检查/占位目标，再 os.replace”，失败时回滚到单一文件状态。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a7.py   # CASE 27
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a1.py   # CASE 3（改名成功但回执失败的路径）
```
关键输出：
```
first save raised: ChapterError chapter_filename_conflict
files: ['第1章-新标题.md', '第1章-旧标题.md']
retry raised: VersionConflict duplicate_chapter_files      # 保留双文件时
chapter_state raised: VersionConflict duplicate_chapter_files
```
（若竞态文件随后被删除，`probe_a1.py CASE 3` 的重试返回 `saved/recovered=True` 且永不改名。）

---

### P2-03 备份索引引用的版本对象可能不在备份里，`inspect_backup` 仍判 valid（backup 缺版本对象）

**位置**
- `backend/integration/transaction_journal.py:1358-1366`（先复制 index，再复制 objects，最后 `_reconcile_backup_index`）
- `backend/integration/transaction_journal.py:1213-1262`（只复核 index + 正文，不补 objects）
- `backend/integration/transaction_journal.py:1265-1302`、`1668-1696`（`_backup_index_problems`/`inspect_backup` 不检查 object 是否存在）
- `backend/integration/transaction_journal.py:1333-1431`（`backup` 返回成功）

**机制**
- objects 目录复制之后、`_reconcile_backup_index` 之前若有新版本保存：新 index/body 会被 reconcile 复制进备份，但新 `objects/<sha>.txt` 已被错过；备份 manifest 没有 objects 的完整性检查。
- `inspect_backup` 只验证 manifest 哈希 + index↔正文，仍返回 `valid=True`。
- 恢复后正文文件可读，但 `read_version(current)`/`read_version(version_id)` 因 `read_object` 找不到对象而 `VersionNotFound("object_missing")`；版本历史/恢复旧版本不可用。

**影响**
- 备份“看起来有效”，实际丢失版本对象；用户按备份迁移/回滚后才发现历史版本不可读。P2（当前正文尚在）。

**最小修复**
- `_reconcile_backup_index` 在同一 versions 锁内从 index 收集全部 `versions[].sha256`，检查 `objects/<sha>.txt` 是否存在且哈希匹配，缺失则从源对象目录复制；
- `_backup_index_problems` 增加 `index_object_missing:<chapter>:<sha>`；
- 若无法补齐，`backup()` 返回非 ok 并且 `inspect_backup` invalid。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a3.py   # CASE 13
```
关键输出：
```
index version shas: 2 objects: 1 missing objects: ['5aad9a72...']
inspect valid: True []
restored current: 5aad9a72d595
read current version raised: VersionNotFound object_missing
read by version_id raised: VersionNotFound object_missing
```

---

### P2-04 备份过程中标题改名会产生重复正文路径，备份自报成功但 restore 拒绝整个备份

**位置**
- `backend/integration/transaction_journal.py:1355-1357`（先整树复制 `正文`）
- `backend/integration/transaction_journal.py:1052-1089`（`_copy_tree` 逐文件登记 manifest）
- `backend/integration/transaction_journal.py:1213-1262`（reconcile 只补新文件，不删除同章旧文件名）
- `backend/integration/transaction_journal.py:1265-1302`（`_backup_index_problems` 按 manifest 顺序取每章第一个正文条目）

**机制**
- 正文树复制时得到旧文件名；随后一次 `save_version` 同时改标题：project 里变成新文件名，index 也更新为新 sha。
- `_reconcile_backup_index` 发现 dest 正文 sha 与新 index 不符，复制新文件名正文；**旧的同名章文件与旧 manifest 条目都保留**。
- `backup()` 的 `chapter_versions_consistency` 只看 dest 目录里排序后的第一个文件（新文件），判 ok；但 `inspect_backup`/`restore_backup` 的 `_backup_index_problems` 按 manifest 顺序取到旧条目 → `index_body_mismatch:1`，restore 直接 `backup_corrupt` 整体拒绝。

**影响**
- 备份命令返回成功，实际备份不可恢复；用户只有在需要恢复时才发现。P2。

**最小修复**
- reconcile 复制新正文后，删除 dest 中同一章号的旧文件名（并在 `records` 中移除对应 manifest entry），或同一章号只保留 index 指向的路径；
- 或者 detect “same chapter number multiple body files” 直接让 `backup()` 失败并提示重试，不允许产出带重复章节的备份。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a3.py   # CASE 12
```
关键输出：
```
backup body files: ['第1章-新标题.md', '第1章-旧标题.md']
inspect valid: False problems: ['index_body_mismatch:1']
restore raised: TransactionConflict backup_corrupt: index_body_mismatch:1
```

---

### P2-05 `restore_trash` 可重复执行同一归档，第二次把同一章改号复制

**位置**
- `backend/integration/chapter_editor.py:982-1078`（`restore_trash` / `_restore_trash_impl`）
- 归档 manifest 没有 `restored_at` / `restored_chapter` 状态；成功后不移动/标记归档
- `backend/integration/chapter_editor.py:1014-1017`（章号已存在则 `max(mapping)+1` 改号）

**机制**
- 第一次 restore 生成 chapter N；归档仍在 `.webnovel/trash/<entry>`，`list_trash` 仍返回该 entry。
- 第二次（无 op_id 或 op_id 过期后）restore：N 已存在 → 改号到 N+1，`commit_raw_bytes` 再写一份相同正文，版本/批注/草稿也再插入一份（版本 id 可能重复）。
- 有 op_id 时第二次会因 `commit_raw_bytes` 的 `operation_id_reused` 失败；无 op_id 时直接成功复制。

**影响**
- 同一章在书里出现两份，可能被后续合并/发布/全文检索当两章处理；P2（可手工删除，但作者未必察觉）。

**最小修复**
- restore 成功后写回 manifest（`restored_at`、`restored_chapter_id`），之后同一 entry 再 restore 返回 `already_restored`（除非显式 `force`）；或把归档移入 `trash/.restored/`；
- 更彻底：让 `restore_trash` 支持“恢复为同一章号”时替换/冲突，而不是静默改号。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a3.py   # CASE 14
```
关键输出：
```
first restore: restored chapter: 1 renumbered: False
second restore: restored chapter: 2 renumbered: True
chapters: [1, 2]
  ch 1 '被删正文\n'
  ch 2 '被删正文\n'
trash list still: ['20261127T183709-ch0001']
```

---

### P2-06 标题改名重写回执时覆盖并发 `author_confirm`

**位置**
- `backend/integration/chapter_editor.py:615-634`（`_rename_chapter_file`：`_read_receipts` 在锁外读，随后 `_write_receipts({chapter: entry})` 用旧 entry 整体覆盖）
- `backend/integration/chapter_editor.py:162-174`（`_update_receipts` 只做顶层 key merge，无法保留同一 chapter entry 内并发更新的字段）
- 对照：`chapter_versions.py:1095-1113` 的 `_update_receipt_destination` 是在 `receipts.lock` 内 read-latest + 只改 destination，是正确的；rename 路径没有复用它

**机制**
- `save_version` 提交后调用 `_rename_chapter_file`：先 `_read_receipts` 拿到旧快照，再改名，再 `_write_receipts`。
- 若另一个请求在这个窗口里 `author_confirm` 成功（写入 `review.confirmed_version_id`/`note` 等），rename 的 `_write_receipts` 会用旧 entry 覆盖整个 `"<chapter>"` 值，确认被静默丢弃；destination 反而更新了。
- 与 A-P2-14 的 delete 路径同类，但 rename 路径未修。

**影响**
- 作者确认丢失；`review_eligible` 会按旧确认版本判定 stale，发布被阻塞；需重新确认。P2。

**最小修复**
- `_rename_chapter_file` 改为 `_update_receipts(project, mutate)`：在 `receipts.lock` 内重新读取、只更新 `destination`（直接复用 `chapter_versions._update_receipt_destination`）；
- 或者把 destination 更新做成独立的小字段更新（read-latest under lock），不整 entry 覆盖。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a3.py   # CASE 16
```
关键输出：
```
renamed: True files: ['第1章-新标题.md']
receipt note: first confirm            # 并发写入的 "concurrent confirm" 消失
receipt destination: .../第1章-新标题.md
```

---

### P2-07 `apply_hunks` 跨 preview 混选时只用一个 base_snapshot，其他 hunk 静默不应用/响应无失败明细

**位置**
- `backend/integration/annotations.py:757-767`（`base_preview = next(...)`、只查这一个 preview 的 `base_snapshot_id`）
- `backend/integration/annotations.py:789-791`（所有 pending hunk 共用同一 base_text）
- `backend/integration/annotations.py:874-883`（响应只含 `applied` 和 `conflicts`；`relocated_needed` 既不 applied 也不 conflict，被丢弃）
- `backend/integration/text_merge.py:429-457`（`_prepare_hunk` 依赖 hunk 自带的 char_start/before_text）

**机制**
- `apply_hunks` API 接受任意 `hunk_ids`；不同 annotation 可能在不同时间、不同草稿基线上生成，各自 preview 的 `base_snapshot_id` 不同。
- 实现只取第一个 pending row 的 preview 快照作为 `base_text`，其余 hunk 的 `char_start/char_end` 属于另一坐标系；`_prepare_hunk` 用 before_text 重新定位，可能失败为 `relocated_needed`，也可能在上下文相似时错误落位（quote 唯一时通常能救回，但依赖 shift/上下文）。
- 顶层 `status` 只要有一个 hunk applied 就是 `"applied"`；失败 hunk 不出现在 `applied`、不出现在 `conflicts`，`clean=False` 是唯一线索。

**影响**
- 用户选中多个批注一起应用时，部分 hunk 实际上没进草稿，但接口报 “applied”，hunk/annotation 仍 pending；P2（可再次单独应用，但状态和 UI 误导）。

**最小修复**
- 按 `preview_index.base_snapshot_id` 分组；同一请求混用不同快照时返回 409 `mixed_base_snapshots`，或逐组用各自 base 计算后再合并；
- 响应增加 `per_hunk: [{hunk_id,status,reason}]` 或至少把 `relocated_needed` 放进结果/`skipped` 列表，不要只返回 applied+conflicts。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a2.py   # CASE 8
```
关键输出（prefix=120，两个 preview 的 base 快照不同）：
```
prefix=120 status: applied clean: False conflicts: []
prefix=120 draft: '前前...\n开头一句。\n她推开门。\n收尾一句。\n'
```
—— `她撞开门。`（preview1）没有应用，接口却报 applied；hunk 仍 pending。

---

### P2-08 split/merge 不迁移批注：split 把后半章批注留在旧章，merge 把尾章批注封进 trash

**位置**
- `backend/integration/chapter_editor.py:1145-1214`（`split_chapter`，没有任何 annotations 处理）
- `backend/integration/chapter_editor.py:1274-1320`（`merge_tail`，尾章通过 `delete_chapter` 删除，批注被归档进 trash）
- `backend/integration/annotations.py:300-339`（`list_annotations` 只按 chapter_id 查，不会跨章迁移）

**机制**
- split 后：原 chapter N 的 annotation/hunk 仍挂在 N，base_snapshot 是拆分前的全文；第二半正文已移到 N+1。`list_annotations(N)` 显示 `overlap_conflict/relocated_needed`，`apply_hunks` 不可能在原章应用；N+1 没有批注。
- merge 后：尾章 last 被 `delete_chapter` 归档，其 annotations 被写入 trash manifest；合并后的 previous 章节没有这些批注。作者要找回只能 restore trash（会再建一章）。

**影响**
- 批注不丢字节（仍在 DB/trash），但从当前编辑视图“消失/不可用”，需手工重建；P2（首尾章的批注是作者重要工作）。

**最小修复**
- split：按 offset 将 base 范围 >= offset 的 annotation/hunk 重新锚定到 chapter+1（新快照=second payload，char_start 减去 offset），并更新 chapter_id/chapter_uid；无法重锚的标 `relocated_needed` 并保留在 N+1。
- merge：把 last 的 annotations/hunks 平移到 previous（offset = first_text 长度 + 分隔符），或至少在 merge 响应里返回 `annotations_archived` 提示，并在 trash 恢复时提供“合并回 previous”选项。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a4.py   # CASE 17/18
```
关键输出：
```
split: split chapters: [1, 2]
ch1 text: '第一段内容。\n'
ch2 text: '第二段内容。\n第三段内容。\n'
annotations ch1: [('ann_...', 'proposed', {'status': 'overlap_conflict', ...})]
annotations ch2: []
apply on ch1: conflict [{'reason': 'selection_changed', ...}]
```
```
merge: merged chapters: [1]
annotations ch1: []
annotations ch2 raised: AnnotationError chapter_missing
trash annotations: [1]
```

---

### P2-09 大纲重新加回已删章节时 rev 未递增，重复文件中的同 rev 墓碑会再次删除，响应仍报已保存

**位置**
- `backend/integration/outline_editor.py:600-621`（`write_file` 生成 payload）
- 关键行 `604-608`：`if old_item.get("deleted"): rev = int(old_item.get("chapter_rev") or 0) or 1` —— 不加 1
- `backend/integration/outline_editor.py:338-387`（`_merge_chapters`；第 386 行 `tomb_rev >= current.chapter_rev` 就删除）
- 现有测试 `test_readding_deleted_chapter_via_write_file` 只覆盖“同一文件重加、无第二份墓碑”

**机制**
1. 文件 A 删除章 2 → 墓碑 rev 2。
2. 同步工具/手工复制留下文件 B，其中仍有章 2 墓碑 rev 2。
3. 作者在 A 重新加回章 2：`old_item.deleted` 分支把 live `chapter_rev` 设为 2（不 +1），且不把墓碑写入 A（章 2 在 new_numbers 中）。
4. `_merge_chapters` 扫描 B 的墓碑 rev 2，`2 >= 2` → 再次 pop；`recover_plan` 和 `story_plan.json` 都没有章 2，`conflicts=[]`；`write_file` 响应却返回 `chapter_revs['2']=2`。

**影响**
- 作者重加的大纲静默消失；由于 rev 永远等于墓碑，重试也不会赢。P2（MD 源文件里的可见文本还在，但派生规划/前后文上下文丢失）。

**最小修复**
- 重加已删章节时 rev 取 `max(old_rev, 当前合并索引 rev, 所有 plan 文件的 tombstone rev) + 1`；
- 或在 `_merge_chapters` 中仅当墓碑 rev **严格大于** live rev 才删除（等于时保留 live 并报冲突），避免同 rev 墓碑压过重加。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a5.py   # CASE 24
```
关键输出：
```
write response chapter_revs: {'1': 3, '2': 2}
recovered chapters: ['1']
conflicts: []
story_plan chapters: ['1']
```

---

### P2-10 `chapter_versions` 只拒绝根目录符号链接，objects/candidates/commits 子目录可把版本数据写到项目外

**位置**
- `backend/integration/chapter_versions.py:104-128`（`_assert_version_store` 只检查 `.webnovel`、`chapter_versions` 两层）
- `backend/integration/chapter_versions.py:153-157`（`_ensure` 创建 `objects/candidates/commits/staging`，不检查是否为链接）
- `backend/integration/chapter_versions.py:355-374`（`_store_object` 直接写 `objects/<sha>.txt`）
- 同类：`annotations.py:87-110`（snapshots 目录）、`revision_plan.py:284-325`（revision_previews）也未检查子目录链接

**机制**
- `.webnovel/chapter_versions/objects` 是指向项目外的符号链接时，`_assert_version_store` 通过（只 resolve `chapter_versions`），`_store_object` 的 temp+replace 写在外部目录；正文/index/commit 仍在项目内。
- 备份不会包含外部 objects；迁移/拷贝项目后历史版本对象缺失；同时这是明确的项目外写入。

**影响**
- 版本对象与 index 分离到项目外，备份/迁移丢对象；若项目来自同步工具或恶意压缩包，构成越界写入。P2（安全+数据完整性）。

**最小修复**
- `_assert_version_store` 或 `_ensure` 对每个子目录（objects/candidates/commits/staging）做 `is_symlink()` 和 resolve 包含性检查；annotations/revision_plan 的 snapshots 同理。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a5.py   # CASE 23
```
关键输出：
```
new_chapter: created
outside objects: ['2373f217....txt']      # 对象落在项目外
project body files: ['第1章-开端.md']
```

---

### P2-11 `resident_service.backup` 先复制索引后复制正文，缺少版本锁/一致性协调；备份成功但索引与正文不一致

**位置**
- `backend/integration/resident_service.py:524-539`（`_backup_tree`：`sorted(folder.rglob("*"))` 一次性排序，`.webnovel/index.json` 排在 `正文/*.md` 前）
- `backend/integration/resident_service.py:542-579`（`backup`：逐个 `read_bytes`/`write_bytes`，无 `chapter_versions` 锁、无 reconcile、无 manifest 校验）
- `backend/integration/resident_service.py:592-645`（`restore` 只拷贝，不核对 `backup.json` 中的 sha/size）

**机制**
- `books/<书>/.webnovel/chapter_versions/index.json`（`.` 排序在 CJK `正文` 前）先被复制；之后若发生一次保存，`正文` 复制到的已是新正文，index 仍是旧 index。
- 备份成功（manifest 写成功）；恢复后 index 的 `current` sha 与磁盘正文 sha 不一致，`current_version`/比对/发布判断都会按旧版本走。
- restore 同样不校验 `backup.json` 的 `contents` 哈希，损坏/篡改的正文会被静默写入。

**影响**
- 常驻服务的备份在“备份过程中有人写稿”时产出不一致快照，恢复后才暴露；P2（与 transaction_journal 的 reconcile 相比是明显缺口）。

**最小修复**
- 备份时复用 `transaction_journal._versions_lock` + `_reconcile_backup_index` 的思路：先复制正文树，再在 versions 锁内复制 index/objects，并复核 index↔正文；
- 或者直接调用 `transaction_journal.backup` 的版本一致性逻辑，不要另写一套；
- restore 前按 `backup.json.contents` 校验每个文件 sha/size，失败整体拒绝。

**探针**
```bash
... /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a6.py   # CASE 25
```
关键输出：
```
backup index current: 145cb87398f7
backup body sha: 116e2889852a
restored index current: 145cb87398f7
restored body sha: 116e2889852a
restored body: '备份窗口内的新正文\n'
```

---

## 4. P3

### P3-01 `_recover_completed_save` 硬编码 `draft_cleared=False`（A-R-04）

**位置** `backend/integration/chapter_editor.py:475-483`
**机制** 首次保存已清草稿，但 `idempotency_complete` 失败；重试走 commit 恢复分支，响应固定 `"draft_cleared": False`，而 `wb.get_draft()` 已为 None。
**影响** 客户端可能认为草稿仍在、继续显示/重提旧草稿；响应契约失真。
**最小修复** 恢复时读 `wb.get_draft(project, chapter)`，按实际是否还有 draft 返回；或把 `draft_cleared`/submitted draft 身份写进 commit 记录。
**探针/输出** `probe_a1.py CASE 5`：
```
first save draft_cleared: True draft after: None
retry reused: True recovered: True draft_cleared: False draft after retry: None
```

### P3-02 `merge_tail` 空 params 幂等缓存会把上一次合并结果当成新操作结果

**位置** `backend/integration/chapter_editor.py:1252-1271`（`_idempotent_soft(project, "chapter_merge", op_id, {})`）
**机制** params 恒为 `{}`，同一 op_id 在不同章节尾/不同时间复用时会直接命中 completed 缓存；响应 `reused=True`，实际未合并。
**影响** 调用方复用 op_id（客户端缺陷/重放）时得到假成功；若依赖“重试合并”会误以为已处理。
**最小修复** 先算出 `previous/last` 及其 sha 再构造 params（或在缓存命中时校验章节集合仍匹配，不匹配报 `op_id_params_mismatch`）。
**探针/输出** `probe_a1.py CASE 6`：
```
first merge: chapter_id 1 dropped 2
second merge with same op_id: status merged reused True (chapter_id 1, dropped 2)
chapters after second call: [1, 2, 3]     # 2/3 根本没合并
```

### P3-03 `reject_hunks` 接收 op_id 但不使用；`undo_apply` 无幂等键

**位置** `backend/integration/annotations.py:968-999`（op_id 只校验，不 begin/complete）；`886-949`（undo_apply 无 op_id）
**机制** 第一次 reject 成功后响应丢失，重试进入 `no_pending_hunks`；undo 重试同理无法重放。`op_id_required` 只是形式。
**影响** 客户端无法安全重试 reject/undo。
**最小修复** 按 `apply_hunks` 模式对 reject_hunks 做 idempotency；undo 引入可选 op_id 并缓存响应。
**探针/输出** `probe_a4.py CASE 19`：
```
first reject: rejected [...]
second reject raised: AnnotationError no_pending_hunks
```

### P3-04 删除批注/撤销应用后 `preview_index` 生命周期不维护：孤儿 preview、pending_previews 永久虚高、preview 状态与 hunks 不一致

**位置** `backend/integration/annotations.py:276-281`（delete_annotation 只删 hunk/annotation）；`819-872`（apply 置 preview=applied）；`940-949`（undo_apply 不回写 preview）；`952-965`（revert_draft_hunks 不回写 preview）
**机制** 删除 annotation 后 preview_index 仍有一行 pending、hunks=0；summary 的 `pending_previews` 永远 +1；undo/revert 后 hunk 回到 pending，但 preview 仍显示 applied。
**影响** UI 计数与可操作状态错误；无数据丢失。
**最小修复** delete_annotation 同事务删除/置 superseded 对应 preview_index；undo/revert 后重算 preview 状态（复用 apply 末尾的 recompute 逻辑）。
**探针/输出** `probe_a4.py CASE 20`：
```
previews after delete: 1 [('prev_...', 'pending', 0)]
summary after delete: {'pending_previews': 1, ...}
```

### P3-05 XML `<patch>` 可把修改落到批注选区之外（`edit_policy=strict_selection` 未落实）

**位置** `backend/integration/annotations.py:598-618`（patch 的 `start_para/end_para` 直接换算 hunk 范围，没有与 annotation 的 `[char_start,char_end)` 求交）；`224`（edit_policy 仅存储）
**机制** 选中“第二段”的批注，模型返回 `start_para=3` 的 patch，`_build_candidate` 生成第四段的 hunk 并允许 apply。
**影响** 模型可以借一个选区批注改写全书任意段落；预览能看见 hunk 的 before_text，但“严格选区”策略没有程序保障。
**最小修复** `strict_selection` 下将补丁范围 clamp 到批注 range，越界 hunk 拒绝或标 `outside_selection` 并在响应里显式列出。
**探针/输出** `probe_a2.py CASE 9`：
```
hunk before_text: '第四段。' range: 15 19
applied status: applied draft: '第一段。\n第二段。\n第三段。\n第四段被改。\n'
```

### P3-06 `resident_service.restore` 不校验 manifest 哈希，损坏/篡改备份静默恢复

**位置** `backend/integration/resident_service.py:592-645`（读 `backup.json` 只用 `root/created_at`；`_restore_into` 直接 `write_bytes`/`replace`）
**机制** `backup.json.contents` 里有 sha256/size，但 restore 完全忽略；篡改任一正文后 restore 成功返回。
**影响** 恢复路径可把损坏数据写回作品；无完整性证明。
**最小修复** 恢复前按 `contents` 全量校验 sha256/size，任一不符整体拒绝；写临时文件 + 原子替换。
**探针/输出** `probe_a6.py CASE 26`：
```
restore returned: 10
restored body: '被篡改的备份正文\n'
```

### P3-07 `recover_pending` 把 versions 锁竞争当成单条记录失败，写入 `recovery_error`

**位置** `backend/integration/chapter_versions.py:778-788`（`except OSError` 后 `except Exception` → `_mark_recovery_failure(..., "recovery_error")`）；`651-660`（`_mark_recovery_failure` 直接写记录）
**机制** 另一个进程/线程正在提交同一 record 时持有 `.webnovel/chapter_versions/.lock`，`file_lock` 非阻塞抛 `PublicationBlocked`；`recover_pending` 没有把它当“deferred”，而是把磁盘记录改成 `recovery_error`。
**影响** 并发恢复/保存时可能把正在完成的 commit 记录短暂改成非终态；下一次恢复会重算（若对象缺失可能升级为 conflict），增加不必要的人工介入。
**最小修复** 捕获 `PublicationBlocked`/`BlockingIOError`，返回 `{"action":"deferred","reason":"lock_busy"}`，绝不写 record。
**探针/输出** `probe_a7.py CASE 29`：
```
recover result while lock held: [{'op_id': 'pending-x', 'state': 'recovery_error', 'error': 'resource_busy'}]
record state: recovery_error
```

### P3-08 `save_version` 跨 action 复用 op_id 时 `_recover_completed_save` 会认领其他操作留下的 commit

**位置** `backend/integration/chapter_editor.py:447-483`（只按 op_id/chapter/sha/title 匹配，不校验 action/source）；`chapter_versions.py:486-519`（commit 记录不区分 action）
**机制** `new_chapter(..., op_id="X")` 留下 committed commit；随后 `save_version(..., op_id="X")` 若内容/标题相同，`_recover_completed_save` 直接返回 `saved/recovered=True/reused=True`，不会再走 `chapter_save` 的幂等键，也不创建新版本。
**影响** 若客户端复用 op_id（常见于“复制上一次请求”），一个“保存”被误当成已完成的新建；P3（内容相同时无字节损失）。
**最小修复** commit 记录增加 `action` 字段并在 `_recover_completed_save` 比较；或 commit 路径按 action 分目录。
**探针/输出** `probe_a4.py CASE 21`：
```
save with new_chapter op_id: saved recovered: True reused: True
versions: 1
```

### P3-09 `save_version` 清草稿后的批注结算失败被吞，hunk 永久 `applied_to_draft`，后续不再重试

**位置** `backend/integration/chapter_editor.py:576-592`（`wb.clear_draft_if_matches` 成功后 `annotations.mark_committed`，`except Exception: pass`）；`annotations.py:1002-1043`（mark_committed 只在被调用时扫描全部 applied_to_draft）
**机制** 提交成功、草稿已清，`mark_committed` 因 SQLite 错误失败被吞；之后没有草稿可再触发 `mark_committed`（只有带 `submitted_draft_id` 且 clear 成功的保存才会调用），hunk 永远 applied_to_draft、annotation 永远 partially_applied。代码注释“下次提交会再次尝试清理”与实际路径不符。
**影响** 状态机永久卡住，作者看到未结算批注；正文正确。
**最小修复** 把 `mark_committed` 放进提交事务，或在 save/startup 的恢复流程中对“无草稿但存在 applied_to_draft hunk”的章节补一次结算；至少把失败记录到章节状态并暴露修复入口。
**探针/输出** `probe_a7.py CASE 30`：
```
save: saved draft_cleared: True draft: None
hunk status: applied_to_draft annotation: partially_applied
after later save hunk: applied_to_draft annotation: partially_applied
```

---

## 5. 逐条复核的上一轮残余

| 残余 | 本轮结论 | 证据 |
|---|---|---|
| A-R-03 恢复后标题改名/回执 | **仍存在** → P1-01（回执失败重试不补齐；commit 后死亡不补改名） | probe_a1 CASE 1/2 |
| A-R-04 draft_cleared 硬编码 | **仍存在** → P3-01 | probe_a1 CASE 5 |
| A-R-05 soft op_id 不幂等 | **仍存在** → P2-01（完成失败后 409；TTL 后 404/重复） | probe_a1 CASE 4 + 单独 TTL 探针 |
| A-R-06 restore 回执更新崩溃 | **仍存在** → P1-01（与 A-R-03 同根；改名后回执失败永久不回补） | probe_a1 CASE 1 |
| A-P2 outline legacy 回填/删除 | **部分修复但仍有新缺口**：dict 格式已覆盖；**list 格式迁移崩溃** → P1-04；重复文件墓碑重加 → P2-09 | probe_a3 CASE 15；probe_a5 CASE 24 |
| backup 缺版本对象 | **仍存在** → P2-03 | probe_a3 CASE 13 |
| merge_tail 空 params 缓存 | **仍存在** → P3-02 | probe_a1 CASE 6 |
| B-01R-4 apply_hunks 草稿与状态两个事务 | **仍存在** → P1-02（插入型重复应用；替换/删除死状态） | probe_a2 CASE 7 |

---

## 6. HYPOTHESIS（只读推演，未故障注入；不计入计数）

1. **`adopt_legacy` / `adopt_originals` / `prune_adopted` 无 `file_lock`**（`chapter_versions.py:1189-1287`）：load_index → 修改 → `_save_index`，与并发 `commit_raw_bytes` 可能丢索引更新。当前仓库没有生产调用点（仅测试/迁移脚本可能调用），故未提升为确认缺陷。
2. **`studio.polish_existing` 提交后写回执不是事务**（`studio.py:536-552`）：`commit_raw_bytes` 后写 `writer_receipts.json`；若写回执失败，正文已新、回执旧 sha，章节被发布集合排除。因依赖模型/Executor，未做实际故障注入。
3. **`chapter_editor.save_version` 清草稿在 `_locked` 之外且不在 try 内**（`chapter_editor.py:576-592`）：`wb.clear_draft_if_matches` 抛 SQLite 错误会让已提交的保存返回 500；重试可通过 commit 恢复，但首次响应丢失。属可恢复的 post-commit 副作用。
4. **`annotations.mark_committed` 的 ±120 字符窗口可能误判**（`annotations.py:1025-1031`）：若相同替换文本在附近出现，可能把已回退的 hunk 标成 committed；未构造出稳定复现。
5. **`outline_editor.write_file` 不递增 `meta_revision`/`plan_revision`**（`outline_editor.py:545-669`）：客户端只轮询 meta_revision 时看不到大纲文件内容变更；文件 revision 仍在，故列为契约疑问。
6. **`restore_trash` 改号恢复会复制同一批 version_id 到第二章节**（`chapter_editor.py:1049-1058`）：重复 restore 后两个章节共享 `ver_*` 身份；与 P2-05 同根，未单独计数。

---

## 7. 已覆盖边界

- 已逐行读完范围内 13 个生产文件及主要测试：`workbench_db`、`transaction_journal`、`chapter_versions`、`chapter_editor`、`version_history`、`outline_editor`、`invalidation`、`revision_plan`、`studio`、`resident_service`、`annotations`、`text_merge`、`quality`。
- 已实际运行：
  - 基线 1208 个测试全绿；
  - `probe_a1.py`：restore/save 改名+回执、soft op_id、draft_cleared、merge 缓存；
  - `probe_a2.py`：apply_hunks 两事务崩溃（replace/delete/insert）、跨 preview 快照、选区外 patch、重叠 hunk、拒绝后 mark；
  - `probe_a3.py`：backup 改名竞态、backup 缺对象、trash 重复恢复、legacy list 迁移、rename 覆盖 confirm；
  - `probe_a4.py`：split/merge 批注、reject 幂等、删除批注孤儿 preview、跨 action op_id；
  - `probe_a5.py`：split 回滚覆盖并发 chapter+1、版本子目录符号链接、重复文件墓碑重加；
  - `probe_a6.py`：resident backup 索引/正文竞态、restore 不校验哈希；
  - `probe_a7.py`：改名双文件卡死、soft op TTL 后 404/409、recover 锁竞争、mark_committed 失败卡死。
- 已确认/复核的覆盖点：`workbench_db` 的嵌套 savepoint、幂等键状态机、draft epoch/ABA；`transaction_journal` 的 prepare/apply/recover 幂等与 staged 校验；版本对象/内容 sha 双哈希；split/merge/delete 的正常路径与已测回滚；现有测试对 A-P1/A-P2 系列回归的覆盖。

## 8. 未覆盖边界

- `transaction_journal.write_text/write_bytes/rename/delete` 在生产代码中没有调用点（只有 backup/export_legacy 使用 journal），其“prepare 后作者手改再 apply 覆盖”的语义未按生产路径评估。
- `adopt_legacy` / `adopt_originals` / `prune_adopted` 无生产调用点，仅按代码推演（见 HYPOTHESIS 1）。
- 多进程真实并发只依赖现有测试的 3 进程用例；本次探针是单进程故障注入，不能量化真实进程竞争窗口（尤其 P1-01/P2-02/P2-06）。
- Windows 特有的 `WinError 5/32/33`、ACL、杀软占用、junction 行为未在 Linux 环境实测；P2-02/P1-01 在 Windows 上触发概率应更高。
- 磁盘满、权限拒绝、fsync 失败均以异常模拟，未做真实文件系统故障注入。
- `resident_service.run` 的调度循环、信号处理、watchdog、systemd/launchd 重启语义未做端到端验证；只测了 backup/restore 数据路径。
- `studio.plan_async` / `polish_existing` / 模型网关 / 网络调用未实际运行（只读代码）；HYPOTHESIS 2 属此类。
- UI/前端契约未审计：无法确认前端是否会把不同 preview 的 hunk 一起提交（P2-07）、是否会在失败后刷新草稿身份再重试（P1-02）、是否会重复点击恢复回收站（P2-05）。
- `quality.py` 逐行读完并跑过现有测试，未发现数据一致性缺陷；仅发现 `_auto_count` 未被使用的死代码（不计 finding）。
- 未做模糊测试/属性测试；`text_merge` 的随机不重叠不变量已有测试，但跨快照/跨 preview 组合未覆盖。

## 9. 探针复现命令

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v3/head-a
PY=/home/ubuntu/venvs/dsh/bin/python
export PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend

$PY -B -X utf8 ../tmp-a/probe_a1.py   # P1-01, P2-01, P2-02, P3-01, P3-02
$PY -B -X utf8 ../tmp-a/probe_a2.py   # P1-02, P2-07, P3-05
$PY -B -X utf8 ../tmp-a/probe_a3.py   # P1-04, P2-03, P2-04, P2-05, P2-06
$PY -B -X utf8 ../tmp-a/probe_a4.py   # P2-08, P3-03, P3-04, P3-08
$PY -B -X utf8 ../tmp-a/probe_a5.py   # P1-03, P2-09, P2-10
$PY -B -X utf8 ../tmp-a/probe_a6.py   # P2-11, P3-06
$PY -B -X utf8 ../tmp-a/probe_a7.py   # P2-01(TTL), P2-02(双文件), P3-07, P3-09
```

所有探针只使用 `tempfile.TemporaryDirectory()` 和仓库只读导入，不修改仓库文件；`tmp-a/` 下的脚本可复跑。
