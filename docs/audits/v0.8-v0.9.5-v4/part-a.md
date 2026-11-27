# A 域第四轮独立审计报告：核心数据 / 版本 / 章节 / 批注 / 合并

- 审计工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v4/head-a`，detached `ce50d08`
- 审计范围：`backend/integration/` 下 `workbench_db.py`、`transaction_journal.py`、`chapter_versions.py`、`chapter_editor.py`、`version_history.py`、`outline_editor.py`、`invalidation.py`、`revision_plan.py`、`studio.py`、`resident_service.py`、`annotations.py`、`text_merge.py`、`quality.py` 及对应测试
- 审计方式：先读第三轮 A 域报告与修复记录，再逐行读当前代码并用独立探针复现；未修改仓库、未 commit、未联网
- 基线测试（仓库根）：
  ```text
  PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
    /home/ubuntu/venvs/dsh/bin/python -B -X utf8 -m unittest discover -s backend/integration -t backend
  → Ran 1270 tests in 90.704s, OK (skipped=9)
  ```
- 探针目录：`/home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-a/`（`probe_a1.py` … `probe_a19.py`；a1–a7 为第三轮探针，已在 ce50d08 上复跑并修正失效注入）

## 0. 严重度口径

| 级别 | 口径 |
|---|---|
| P0 | 直接丢正文/不可恢复的破坏；本轮未发现 |
| P1 | 静默产生正文或版本身份不一致、核心升级/恢复路径不可用，且无自动修复 |
| P2 | 索引/备份/回执/批注状态不一致，或需要手工绕过；不直接丢用户正文 |
| P3 | 契约、展示、清理、幂等边界类问题 |

## 1. 结论计数

| P0 | P1 | P2 | P3 |
|---|---|---|---|
| 0 | 1 | 9 | 16 |

另有 7 条只读推演/无法端到端注入的 **HYPOTHESIS**，不计入上表（见 §6）。所有 P1/P2/P3 均附 `file:line`、机制、影响、最小修复、探针输出。第三轮 A-P1-01/02/03/04 与 R-01 主张均已独立复核；P3-01/P3-07、P2-05/P2-06 已关闭，P2-02/P2-10 为部分收敛，见 §5 对照表。

---

## 2. P1

### P1-05 `restore_trash` 全程不持章锁：恢复窗口内的并发保存被索引/回执回退覆盖

**位置**
- `backend/integration/chapter_editor.py:1023-1174`（`restore_trash` / `_restore_trash_impl`；`1041` 起整段没有 `_locked(project, chapter)`）
- `backend/integration/chapter_editor.py:1125`（`commit_raw_bytes` 落正文/版本；只持版本存储锁）
- `backend/integration/chapter_editor.py:1133-1142`（随后把归档 `index_entry["versions"]` 前插并把 `target["current"]` 强行设回恢复稿 sha）
- `backend/integration/chapter_editor.py:1143-1147`（用归档 receipt 整条覆盖 `writer_receipts[chapter]`）

**机制**
1. `restore_trash` 先用 `chapter_map` 选目标章号，随后调用 `commit_raw_bytes`；正文提交只持 `.webnovel/chapter_versions/.lock`，释放后恢复流程继续写 index 版本列表、收据、批注、草稿，但**从未拿章级锁**。
2. 在这一窗口内，另一个窗口对刚出现的章节执行 `save_version` 是合法的：它会提交新正文、登记新版本、把 index `current` 指向新 sha，并可能改名。
3. 恢复流程随后无条件执行 `target["versions"] = archived_versions + target["versions"]` 且 `target["current"] = result["content_sha256"]`，把并发保存的当前版本指针覆盖回恢复稿；`author_confirm` 等回执也被归档 receipt 覆盖。
4. 结果：磁盘正文是并发保存的新稿，index `current` 是恢复稿旧 sha，`current_version()` 标题/版本号与实际正文不一致；没有 `recover_pending` 或启动修复路径能发现这种“已 committed 但 index current 落后”的状态。
5. 旧 P1-03（split 回滚覆盖 chapter+1）修了 split 的双章锁；`restore_trash` 同类路径未纳入。

**影响**
- 恢复操作返回 `status: restored`，但章节版本身份与正文静默分叉；后续保存可能 409、重复注册版本或把并发稿当作旧版本回退。属于核心恢复路径的版本身份不一致，P1。
- 并发 `author_confirm` 的确认字段会被归档 receipt 覆盖（同一窗口，P2-06 类的回执丢失）。

**最小修复**
- 选定 `chapter` 后，在 `_restore_trash_impl` 全程持有 `_locked(project, chapter)`（与 `save_version` 同一把章锁），锁内重做 `chapter_map`/index 检查；
- 或在写回 `entry_data` 前做 CAS：仅当 `target["current"] == result["content_sha256"]` 且磁盘 sha 仍等于恢复稿时才覆盖；否则保留并发 entry，返回 `restore_conflict`（或把归档版本 append 但不改 current）；
- 回执改用 `_update_receipts(read-latest, 只改 destination/review 快照字段)`，不要整条覆盖。

**探针**
```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v4/head-a
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
  /home/ubuntu/venvs/dsh/bin/python -B -X utf8 ../tmp-a/probe_a13.py
```
关键输出（`commit_raw_bytes` 返回后、恢复继续写 index 前插入一次合法 `save_version`）：
```text
concurrent save: saved
restore status: restored chapter: 1
file: 第1章-并发新标题.md disk_sha: 38e5624bd041
index current: b63b9be080ff
index current_version title: 旧标题
versions sha list: ['b63b9be0', '38e5624b']
```
—— 正文已是并发新稿，index 当前版本仍是恢复的旧稿；无自动修复。

---

## 3. P2

### P2-01 软 `op_id` 完成后不幂等：完成键写失败后重试 409/404，TTL 后重复执行（第三轮残余）

**位置**
- `backend/integration/chapter_editor.py:407-419`（`_finish` 吞掉 `idempotency_complete` 所有异常）
- `backend/integration/chapter_editor.py:422-439`（`_idempotent_soft` / `_finish_soft`）
- 调用点：`new_chapter:678`、`delete_chapter:776`、`split_chapter:1276`、`merge_tail:1387`、`import_chapters:1475`、`restore_trash:1023`
- `backend/integration/workbench_db.py:847-900`（`in_progress` 10 分钟后 TTL 接管）

**机制**
- 业务操作成功，`_finish` 调 `idempotency_complete` 失败（SQLite busy/磁盘满），异常被吞，响应仍成功，但幂等键停在 `in_progress`。
- 客户端重试：10 分钟内 `op_in_progress` 409；10 分钟后 `idempotency_begin` 重置为 `failed_retry` 并**重新执行**。此时业务状态已变：`delete_chapter` → `chapter_missing` 404；`merge_tail` → `merge_needs_two_chapters` 409；`split_chapter` → 只允许尾章 409；`import_chapters` → `chapter_exists` 409；`restore_trash` 虽有 manifest 兜底，其他 soft op 没有“从权威业务状态重建已完成响应”的路径。
- 与 `save_version` 不同，soft op 没有 `_recover_completed_save`。

**影响**
- `op_id` 契约名义存在但完成后不可重放；调用方只能靠列表猜测删除/合并/导入是否生效。P2（不直接丢正文）。

**最小修复**
- soft 操作的业务记录（trash manifest、import commit、split commit）持久化最终响应摘要，`_idempotent_soft` 在 `in_progress`/`failed_retry` 时先从权威状态重建；
- 或把 `idempotency_complete` 与业务事务合并为同一 SQLite 事务/同一次文件写；
- 至少在 TTL 接管前检查业务事实（章已不存在 → 返回 cached deleted，而不是 404）。

**探针**
```bash
... probe_a1.py   # CASE 4
... probe_a7.py   # CASE 28
```
```text
new_chapter first: created 1
new_chapter retry raised: ChapterError op_in_progress op_in_progress
delete first ok; chapters: []
delete retry raised: ChapterError chapter_missing chapter_missing
merge first ok; chapters: [1]
merge retry raised: ChapterError merge_needs_two_chapters merge_needs_two_chapters
```

---

### P2-03 备份索引引用的版本对象可能不在备份里，`inspect_backup` 仍判 valid（第三轮残余）

**位置**
- `backend/integration/transaction_journal.py:1213-1262`（`_reconcile_backup_index` 只复核 index + 正文，不补 `objects/`）
- `backend/integration/transaction_journal.py:1265-1302`（`_backup_index_problems` 不检查 object 是否存在）
- `backend/integration/transaction_journal.py:1367-1370`（objects 在 reconcile 之前整树复制）
- `backend/integration/transaction_journal.py:1673-1702`（`inspect_backup` 只验证 manifest 哈希与 index↔正文）

**机制**
- objects 复制完之后、`_reconcile_backup_index` 之前若有新版本保存：reconcile 会把新 index/正文复制进备份，但新 `objects/<sha>.txt` 已被错过；manifest 没有 objects 完整性检查。
- 恢复后正文可读，但 `read_version(current)`/`read_version(version_id)` 因 `read_object` 找不到对象而 `VersionNotFound("object_missing")`；版本历史/恢复旧版本不可用。

**影响**
- 备份“看起来有效”，实际丢失版本对象；用户按备份迁移/回滚后才发现历史版本不可读。P2（当前正文尚在）。

**最小修复**
- `_reconcile_backup_index` 在同一 versions 锁内从 index 收集全部 `versions[].sha256`，检查/复制 `objects/<sha>.txt` 并校验哈希；
- `_backup_index_problems` 增加 `index_object_missing:<chapter>:<sha>`；
- 无法补齐则 `backup()` 返回非 ok、`inspect_backup` invalid。

**探针**
```bash
... probe_a3.py   # CASE 13
```
```text
index version shas: 2 objects: 1 missing objects: ['5aad9a72...']
inspect valid: True []
restored current: 5aad9a72d595
read current version raised: VersionNotFound object_missing
read by version_id raised: VersionNotFound object_missing
```

---

### P2-04 备份过程中标题改名会产生同章两份正文，备份自报成功但 restore 拒绝整个备份（第三轮残余）

**位置**
- `backend/integration/transaction_journal.py:1357-1362`（先整树复制 `正文`）
- `backend/integration/transaction_journal.py:1213-1262`（reconcile 只补新文件，不删除同章旧文件名/旧 manifest 条目）
- `backend/integration/transaction_journal.py:1265-1302`（`_backup_index_problems` 按 manifest 顺序取每章第一个正文条目）

**机制**
- 正文树复制得到旧文件名；随后一次 `save_version` 同时改标题：project 变成新文件名，index 也更新为新 sha。
- reconcile 发现 dest 正文 sha 与新 index 不符，复制新文件名正文；旧文件与旧 manifest 条目都保留。
- `backup()` 的 `chapter_versions_consistency` 只看 dest 目录里排序后的第一个文件（新文件），判 ok；`inspect_backup`/`restore_backup` 按 manifest 顺序取到旧条目 → `index_body_mismatch:1`，restore 整体拒绝。

**影响**
- 备份命令返回成功，实际备份不可恢复；P2。

**最小修复**
- reconcile 复制新正文后删除 dest 中同章号旧文件名并移除对应 manifest 条目；或检测同章多正文直接让 `backup()` 失败并提示重试。

**探针**
```bash
... probe_a3.py   # CASE 12
```
```text
backup body files: ['第1章-新标题.md', '第1章-旧标题.md']
inspect valid: False problems: ['index_body_mismatch:1']
restore raised: TransactionConflict backup_corrupt: index_body_mismatch:1
```

---

### P2-07 `apply_hunks` 跨 preview 混选时只用一个 base_snapshot，其他 hunk 静默不应用/响应无失败明细（第三轮残余）

**位置**
- `backend/integration/annotations.py:805-815`（`base_preview = next(...)`，只查第一个 pending row 的 preview 快照）
- `backend/integration/annotations.py:866-868`（所有 pending hunk 共用同一 `base_text`）
- `backend/integration/annotations.py:973-982`（响应只有 `applied` + `conflicts`；`relocated_needed` 既不 applied 也不 conflict，被丢弃）
- `backend/integration/text_merge.py:364-430`（`_prepare_hunk` 依赖 hunk 自带 char_start/before_text 所在快照坐标系）

**机制**
- `apply_hunks` 接受任意 `hunk_ids`；不同 annotation 可能在不同草稿基线上生成，各自 preview 的 `base_snapshot_id` 不同。
- 实现只取第一个 pending row 的 preview 快照作为 `base_text`，其余 hunk 的 char_start/char_end 属于另一坐标系；`_prepare_hunk` 可能失败为 `relocated_needed`。
- 顶层 `status` 只要有一个 hunk applied 就是 `applied`；失败 hunk 既不在 applied 也不在 conflicts，`clean=False` 是唯一线索。

**影响**
- 用户选中多个批注一起应用时，部分 hunk 实际没进草稿，接口却报 `applied`，hunk/annotation 仍 pending；P2。

**最小修复**
- 按 `preview_index.base_snapshot_id` 分组；同一请求混用不同快照返回 409 `mixed_base_snapshots`，或逐组用各自 base 计算后再合并；
- 响应增加 `per_hunk: [{hunk_id,status,reason}]` 或至少 `skipped` 列表。

**探针**
```bash
... probe_a9.py
```
```text
order=normal status: applied clean: False
applied: [('ann_..._a_hk_01', 'applied')]
conflicts: []
hunk 1: pending   hunk 2: applied_to_draft
order=reversed 也只应用一个，另一个 pending
```
（两个 preview 的 base 快照不同；`她推开门` 与 `收尾一句` 中总有一个未应用。）

---

### P2-08 split/merge 不迁移批注：split 把后半章批注留在旧章，merge 把尾章批注封进 trash（第三轮残余）

**位置**
- `backend/integration/chapter_editor.py:1297-1365`（`_split_chapter_locked`，没有任何 annotations 处理）
- `backend/integration/chapter_editor.py:1399-1460`（`merge_tail` 通过 `delete_chapter` 删除尾章，批注被归档进 trash）
- `backend/integration/annotations.py:300-339`（`list_annotations` 只按 chapter_id 查）

**机制**
- split 后原 chapter N 的 annotation/hunk 仍挂在 N，base_snapshot 是拆分前全文；第二半正文已移到 N+1。`list_annotations(N)` 显示 `overlap_conflict/relocated_needed`，`apply_hunks` 不可能在原章应用；N+1 没有批注。
- merge 后尾章被 `delete_chapter` 归档，其 annotations 写入 trash manifest；合并后的 previous 章节没有这些批注。

**影响**
- 批注不丢字节（仍在 DB/trash），但从当前编辑视图“消失/不可用”，需手工重建；P2。

**最小修复**
- split：按 offset 将 base 范围 >= offset 的 annotation/hunk 重锚定到 chapter+1（新快照=second payload，char_start 减 offset），并更新 chapter_id/chapter_uid；
- merge：把 last 的 annotations/hunks 平移到 previous（offset=first_text 长度+分隔符），或至少 merge 响应返回 `annotations_archived` 并提供“合并回 previous”。

**探针**
```bash
... probe_a4.py   # CASE 17/18
```
```text
split: chapters [1, 2]; ch1 text '第一段内容。'
annotations ch1: [('ann_...', 'proposed', {'status': 'overlap_conflict', ...})]
annotations ch2: []
apply on ch1: conflict selection_changed
merge: chapters [1]; annotations ch1: []; annotations ch2: chapter_missing
trash annotations: [1]
```

---

### P2-09 大纲重新加回已删章节时 rev 未递增，重复文件中的同 rev 墓碑会再次删除，响应仍报已保存（第三轮残余）

**位置**
- `backend/integration/outline_editor.py:662-664`（`if old_item.get("deleted"): rev = int(old_item.get("chapter_rev") or 0) or 1`，不 +1）
- `backend/integration/outline_editor.py:444`（`_merge_chapters`：`tomb_rev >= current.chapter_rev` 就删除）
- 现有测试只覆盖“同一文件重加、无第二份墓碑”（`test_readding_deleted_chapter_via_write_file`）

**机制**
1. 文件 A 删除章 2 → 墓碑 rev 2。
2. 同步工具/手工复制留下文件 B，其中仍有章 2 墓碑 rev 2。
3. 作者在 A 重新加回章 2：`old_item.deleted` 分支把 live `chapter_rev` 设为 2（不 +1）。
4. `_merge_chapters` 扫描 B 的墓碑 rev 2，`2 >= 2` → 再次 pop；`recover_plan` 和 `story_plan.json` 都没有章 2，`conflicts=[]`；`write_file` 响应却返回 `chapter_revs['2']=2`。

**影响**
- 作者重加的大纲静默消失；由于 rev 永远等于墓碑，重试也不会赢。P2（MD 源文件里的可见文本还在，但派生规划/上下文丢失）。

**最小修复**
- 重加已删章节时 rev 取 `max(old_rev, 当前合并索引 rev, 所有 plan 文件的 tombstone rev) + 1`；
- 或 `_merge_chapters` 仅在墓碑 rev **严格大于** live rev 时删除，等于时保留 live 并报冲突。

**探针**
```bash
... probe_a5.py   # CASE 24
```
```text
write response chapter_revs: {'1': 3, '2': 2}
recovered chapters: ['1']
conflicts: []
story_plan chapters: ['1']
```

---

### P2-10 批注快照 / 修订预览目录仍可被符号链接引到项目外（第三轮残余，chapter_versions 部分已修）

**位置**
- `backend/integration/annotations.py:88-111`（`_snapshot_path`/`save_snapshot`；无 `.webnovel/snapshots` 链接检查）
- `backend/integration/revision_plan.py:284-325`（`previews_dir`/`save_preview`；无 `.webnovel/revision_previews` 链接检查）
- 对照：`backend/integration/chapter_versions.py:106-143` 已对 `objects/candidates/commits/staging` 加 `is_symlink()`/resolve 包含性检查（本轮确认生效）

**机制**
- `.webnovel/snapshots` 或 `.webnovel/revision_previews` 是指向项目外的符号链接时，`save_snapshot`/`save_preview` 直接 `mkdir(exist_ok=True)` 并写入外部目录；备份/迁移不会带这些外部文件，项目本身看似正常。
- 与旧 P2-10 同类：项目外写入 + 备份缺证据。

**影响**
- 批注基线、修订预览落到项目外；迁移后批注/预览不可用；若项目来自同步工具或恶意压缩包，构成越界写入。P2（安全+数据完整性）。

**最小修复**
- 对 `.webnovel/snapshots`、`.webnovel/revision_previews`（以及 `.webnovel` 本身）做与 `_assert_version_store` 相同的 `is_symlink()` + resolve 包含性检查，拒绝 `unsafe_evidence_store`。

**探针**
```bash
... probe_a14.py
```
```text
annotation created: ann_7fb2db91
outside snapshots: ['7e42d54a...txt']
project snapshots dir is symlink: True
preview id: bb7a6fc7...
outside previews: ['.lock', '0001-bb7a6fc7....json']
project previews dir is symlink: True
```

---

### P2-11 `resident_service.backup` 先复制索引后复制正文，缺少版本锁/一致性协调；备份成功但索引与正文不一致（第三轮残余）

**位置**
- `backend/integration/resident_service.py:524-539`（`_backup_tree`：`sorted(folder.rglob("*"))`，`.webnovel/index.json` 排在 `正文/*.md` 前）
- `backend/integration/resident_service.py:542-579`（`backup`：逐文件 `read_bytes`/`write_bytes`，无 `chapter_versions` 锁、无 reconcile、无 manifest 校验）
- `backend/integration/resident_service.py:592-645`（`restore` 只拷贝，不核对 `backup.json` 的 sha/size）

**机制**
- `books/<书>/.webnovel/chapter_versions/index.json` 先被复制；之后若发生一次保存，`正文` 复制到的已是新正文，index 仍是旧 index。
- 备份成功；恢复后 index 的 `current` sha 与磁盘正文 sha 不一致，`current_version`/比对/发布判断都会按旧版本走。

**影响**
- 常驻服务的备份在“备份过程中有人写稿”时产出不一致快照，恢复后才暴露；P2。

**最小修复**
- 复用 `transaction_journal._versions_lock` + `_reconcile_backup_index`：先复制正文树，再在 versions 锁内复制 index/objects 并复核 index↔正文；
- restore 前按 `backup.json.contents` 校验每个文件 sha/size，失败整体拒绝。

**探针**
```bash
... probe_a6.py   # CASE 25
```
```text
backup index current: 145cb87398f7
backup body sha: 116e2889852a
restored index current: 145cb87398f7
restored body sha: 116e2889852a
restored body: '备份窗口内的新正文\n'
```

---

### P2-12 管理端备份白名单漏掉回收站、批注快照、修订预览/候选；`inspect_backup` 仍 valid，恢复后这些用户数据不可用

**位置**
- `backend/integration/transaction_journal.py:1360-1385`（备份只复制 `正文/大纲/设定`、version index/objects、`writer_receipts/story_plan/story_plan_meta/state`，不含 `.webnovel/trash`、`.webnovel/snapshots`、`.webnovel/revision_previews`、`chapter_versions/candidates`）
- `backend/integration/transaction_journal.py:1213-1262`、`1673-1702`（manifest/inspect 只校验已列文件，不校验 SQLite/JSON 中的跨文件引用）
- 产物入口：`backend/manager/api_v08.py:266-283` 明确调用 `transaction_journal.backup`

**机制**
1. `.webnovel/trash/<entry>/` 是删除章节唯一的完整正文副本（`delete_chapter` 把 `正文/*.md` 移入其中）；备份不复制 trash → 备份/迁移后回收站内容永久丢失，`list_trash` 为空。
2. `workbench.sqlite3` 被备份，其中 `annotations.anchor_json.base_snapshot_id`、`preview_index.base_snapshot_id` 指向 `.webnovel/snapshots/*.txt`；`revision_previews` 是修订预览 JSON，且引用 `chapter_versions/candidates`。这些目录都不在备份里 → 恢复后 `list_annotations` 全部 `relocated_needed/snapshot_missing`，`apply_hunks` 直接 `snapshot_missing` 404，修订预览消失。
3. `inspect_backup` 只验证 manifest 中实际存在的文件，因此仍返回 `valid=True`。

**影响**
- 备份“有效”但恢复后：删除章不可恢复、批注无法定位/应用、修订预览丢失；属于用户可见数据丢失（当前正文本身仍在）。P2。

**最小修复**
- 把 `.webnovel/trash`、`.webnovel/snapshots`、`.webnovel/revision_previews`、`.webnovel/chapter_versions/candidates`（以及 `invalidation_log.json`/`shared_memory.json` 等被 SQLite/JSON 引用的状态）纳入备份白名单与 manifest；
- `backup()`/`inspect_backup` 增加“DB/JSON 引用完整性”检查（annotation snapshot id、preview candidate id、trash payload sha）；
- 或者把批注快照/预览改为 SQLite BLOB，消除跨文件引用。

**探针**
```bash
... probe_a15.py   # annotations snapshots / revisions
... probe_a16.py   # trash
```
```text
project snapshots: 1 previews: 2
backup files: 4
backup snapshots exists: False backup previews exists: False
inspect valid: True []
restored annotations: [('ann_...', 'relocated_needed', 'snapshot_missing')]
apply after restore raised: AnnotationError snapshot_missing snapshot_missing
```
```text
trash entries in project: ['20261127T213350-ch0002']
backup files: 5
backup trash exists: False
inspect valid: True []
restored chapters: [1]
restored trash entries: MISSING
list_trash: {'entries': []}
```

---

## 4. P3

### P3-02 `merge_tail` 空 params 幂等缓存会把上一次合并结果当成新操作结果（第三轮残余）

**位置** `backend/integration/chapter_editor.py:1389`
**机制** `_idempotent_soft(project, "chapter_merge", op_id, {})` 的 params 恒为 `{}`；同一 op_id 在不同章节尾/不同时间复用时会直接命中 completed 缓存，响应 `reused=True`，实际未合并。
**影响** 调用方复用 op_id 得到假成功；P3。
**最小修复** 先算出 `previous/last` 及版本 sha 再构造 params；缓存命中时校验章节集合仍匹配，不匹配报 `op_id_params_mismatch`。
**探针/输出** `probe_a1.py CASE 6`：
```text
first merge: {'status': 'merged', 'chapter_id': 1, 'dropped_chapter_id': 2, ...}
second merge with same op_id: {..., 'reused': True}
chapters after second call: [1, 2, 3]
```

### P3-03 `reject_hunks` 接收 op_id 但不使用；`undo_apply` 无幂等键（第三轮残余）

**位置** `backend/integration/annotations.py:1067-1099`（op_id 只校验，不 begin/complete）；`985-1048`（undo 无 op_id）
**机制** 第一次 reject 成功后响应丢失，重试进入 `no_pending_hunks`；undo 重试同理无法重放。`op_id_required` 只是形式。
**影响** 客户端无法安全重试 reject/undo。P3。
**最小修复** 按 `apply_hunks` 模式对 reject_hunks 做 idempotency；undo 引入可选 op_id 并缓存响应。
**探针/输出** `probe_a4.py CASE 19`：
```text
first reject: rejected ['ann_..._hk_01']
second reject raised: AnnotationError no_pending_hunks no_pending_hunks
```

### P3-04 `preview_index` 生命周期不维护：删除批注、undo、adopt 后 preview 计数/状态与 hunk 不一致（第三轮残余，范围扩大）

**位置**
- `backend/integration/annotations.py:276-281`（`delete_annotation` 只删 hunk/annotation，不删/不置 preview）
- `backend/integration/annotations.py:1039-1044`（`undo_apply` 不更新 preview）
- `backend/integration/annotations.py:1051-1064`（`revert_draft_hunks` 不更新 preview）
- `backend/integration/annotations.py:959-971`（apply 只重算 `remaining` pending_rows 的 preview，漏掉 `pre_applied` 的 preview）
**机制**
- 删除 annotation 后 preview_index 仍有 pending 行、hunks=0，summary 的 `pending_previews` 永久虚高；
- undo 后 hunk 回到 pending，但 preview 仍 `applied`；
- `pre_applied`（旧崩溃/作者已写同文）的 hunk 变 applied，但其 preview 仍 `pending`。
**影响** UI 计数与可操作状态错误；无数据丢失。P3。
**最小修复** delete_annotation 同事务删除/置 superseded 对应 preview_index；undo/revert 与 apply 末尾统一重算 preview；apply 的 preview_ids 包含 pre_applied 行。
**探针/输出** `probe_a18.py`：
```text
delete: previews before [('prev_...','pending')] summary pending_previews 1
        previews after  [('prev_...','pending')] summary pending_previews 1, pending_hunks 0
undo:   preview after apply applied -> after undo applied; hunk pending
adopt:  preview pending; hunk applied_to_draft
```

### P3-05 XML `<patch>` 可把修改落到批注选区之外（`edit_policy=strict_selection` 未落实，第三轮残余）

**位置** `backend/integration/annotations.py:598-613`（patch 的 `start_para/end_para` 直接换算 hunk 范围，没有与 annotation 的 `[char_start,char_end)` 求交）；`224`（edit_policy 仅存储）
**机制** 选中“第二段”的批注，模型返回 `start_para=3` 的 patch，`_build_candidate` 生成第四段的 hunk 并允许 apply；`strict_selection` 没有程序保障。
**影响** 模型可以借一个选区批注改写全书任意段落；P3。
**最小修复** `strict_selection` 下将补丁范围 clamp 到批注 range，越界 hunk 拒绝或标 `outside_selection` 并在响应中显式列出。
**探针/输出** `probe_a2.py CASE 9`：
```text
hunk before_text: '第四段。' range: 15 19
applied status: applied draft: '第一段。\n第二段。\n第三段。\n第四段被改。\n'
```

### P3-06 `resident_service.restore` 不校验 manifest 哈希，损坏/篡改备份静默恢复（第三轮残余）

**位置** `backend/integration/resident_service.py:592-645`（读 `backup.json` 只用 `root/created_at`；`_restore_into` 直接 `write_bytes`/`replace`）
**机制** `backup.json.contents` 里有 sha256/size，但 restore 完全忽略；篡改任一正文后 restore 成功返回。
**影响** 恢复路径可把损坏数据写回作品；P3。
**最小修复** 恢复前按 `contents` 全量校验 sha256/size，任一不符整体拒绝；写临时文件 + 原子替换。
**探针/输出** `probe_a6.py CASE 26`：
```text
restore returned: 10
restored body: '被篡改的备份正文\n'
```

### P3-08 `save_version` 跨 action 复用 op_id 时 `_recover_completed_save` 会认领其他操作留下的 commit（第三轮残余）

**位置** `backend/integration/chapter_editor.py:452-517`（只按 op_id/chapter/sha/title 匹配，不校验 action/source）；`chapter_versions.py:1093-1180`（commit 记录不区分 action）
**机制** `new_chapter(..., op_id="X")` 留下 committed commit；随后 `save_version(..., op_id="X")` 若内容/标题相同，`_recover_completed_save` 直接返回 `saved/recovered=True/reused=True`，不再走 `chapter_save` 幂等键，也不创建新版本。
**影响** 若客户端复用 op_id，一个“保存”被误当成已完成的新建；P3（内容相同时无字节损失）。
**最小修复** commit 记录增加 `action` 字段并在 `_recover_completed_save` 比较；或 commit 路径按 action 分目录。
**探针/输出** `probe_a4.py CASE 21`：
```text
save with new_chapter op_id: saved recovered: True reused: True
versions: 1
```

### P3-09 `save_version` 清草稿后的批注结算失败被吞，hunk 永久 `applied_to_draft`，后续不再重试（第三轮残余）

**位置** `backend/integration/chapter_editor.py:633-641`（`wb.clear_draft_if_matches` 成功后 `annotations.mark_committed`，`except Exception: pass`）；`annotations.py:1101-1150`（mark_committed 只在被调用时扫描）
**机制** 提交成功、草稿已清，`mark_committed` 因 SQLite 错误失败被吞；之后没有草稿可再触发（只有带 `submitted_draft_id` 且 clear 成功的保存才会调用），hunk 永远 applied_to_draft、annotation 永远 partially_applied。代码注释“下次提交会再次尝试清理”与实际路径不符。
**影响** 状态机永久卡住；正文正确。P3。
**最小修复** 把 mark_committed 放进提交事务，或在 save/startup 恢复流程中对“无草稿但存在 applied_to_draft hunk”的章节补一次结算。
**探针/输出** `probe_a7.py CASE 30`：
```text
save: saved draft_cleared: True draft: None
hunk: applied_to_draft annotation: partially_applied
after later save: applied_to_draft annotation: partially_applied
```

### P3-10 P2-02 残余：标题改名竞态仍会留下同章双文件，期间整章 GET 409；不再谎报成功但无自动修复

**位置** `backend/integration/chapter_versions.py:1247-1351`（`reconcile_title` 先 `target.exists()` 再 `os.replace`，TOCTOU）；`backend/integration/chapter_versions.py:237-273`（`chapter_path` 双文件抛 `duplicate_chapter_files`）；`chapter_editor.py:590-593` preflight 同窗口
**机制** preflight/reconcile 的 `target.exists()` 与 `os.replace` 之间，外部编辑器/同步工具创建目标文件：`os.replace` 会静默覆盖该外部文件；若 `reconcile_title` 的检查先看到目标存在，则返回 partial，留下旧/新两个同章文件。此后 `chapter_state`/`chapter_path` 直接 409，必须手工删除其中一个；若外部文件被删，重试可完成改名。
**影响** 不再出现第三轮“重试 returned saved/recovered=True 但永不改名”；剩余为显式 partial + 双文件期间整章不可读（需要手工绕过）。P3（第三轮 P2-02 降级残余）。
**最小修复** 用不覆盖的原子改名（Linux `renameat2(RENAME_NOREPLACE)`，或 `os.link` 成功后 unlink 源），并在 partial 响应里给出冲突路径与“删除外部文件后重试”的操作指引；`chapter_state` 可返回单文件快照而不是整章 409。
**探针/输出** `probe_a8.py CASE A8-3` + `probe_a7.py CASE 27`：
```text
first status: partial title_conflict: True renamed: False
files: ['第1章-新标题.md', '第1章-旧标题.md']
chapter_state raised: VersionConflict duplicate_chapter_files
（删除外部文件后重试：saved recovered: True，文件只剩 新标题）
```

### P3-11 P2-05 残余：回收站恢复在正文落地、批注/草稿恢复失败后，重试报 `already_restored` 但批注/草稿仍未恢复

**位置** `backend/integration/chapter_editor.py:1125-1169`（commit 后依次恢复 annotations/draft，最后才写 manifest `restored_at`）；`1050-1075`（retry 只检查 body+index sha，命中就直接 `already_restored`）
**机制** 正文提交成功后 `_restore_trash_annotations`/`_restore_trash_draft` 抛异常；manifest 里已有 `restore_started_at`。重试看到磁盘/索引 sha 等于 payload，就把 manifest 标为已恢复并 409 `already_restored`，但 annotations/draft 从未恢复。
**影响** 用户被告诉“已还原”，批注和草稿实际丢失（仍在 manifest 里，只能手工改 manifest 或 `force` 复制一章）。P3。
**最小修复** manifest 记录 `restore_stage`，重试只补未完成的 annotation/draft 阶段；仅当所有阶段完成才写 `restored_at`/`already_restored`；或在响应中返回 `annotations_restored=False` 的 partial。
**探针/输出** `probe_a10.py CASE 10-2`：
```text
first restore raised: RuntimeError simulated annotation restore failure
chapters after failed restore: [1]
retry raised: ChapterError already_restored {'recovered': True}
annotations on restored chapter: []
```

### P3-12 `undo_apply` 草稿写入与 ledger/hunk 删除仍是两个事务；中间失败后草稿已回退、hunk 仍 applied，重试永久 `undo_relocation_needed`

**位置** `backend/integration/annotations.py:1032-1044`（先 `chapter_editor.save_draft`，再 `wb.write_tx` 删 ledger/重置 hunk）
**机制** `save_draft` 成功（草稿已撤销）后，ledger/hunk 事务失败；草稿已经不含 applied text，但 hunk 仍 `applied_to_draft`、ledger 仍有行。重试 `reverse_patch` 找不到 applied text，抛 `undo_relocation_needed`；只能 discard draft 重置。
**影响** undo 状态机卡住；草稿文本已回退（不丢正文）。P3。
**最小修复** 与 `apply_hunks` 相同：在同一个 `wb.write_tx` 里完成 `wb.save_draft`（嵌套 savepoint）+ ledger/hunk 更新；或持久化 undo intent 后只补状态。
**探针/输出** `probe_a8.py CASE A8-7`：
```text
undo raised: RuntimeError simulated failure before ledger deletion
draft after failed undo: '开头一句。\n她推开门。\n结尾一句。\n'
hunk status after failed undo: applied_to_draft
ledger rows after failed undo: 1
undo retry raised: AnnotationError undo_relocation_needed
```

### P3-13 `reverse_patch` 的“全文唯一出现即撤销”仍会改作者在别处手写的同一句

**位置** `backend/integration/text_merge.py:543-555`（range 不匹配时，若 applied text 在全文唯一出现，就替换该处）
**机制** 应用 hunk 后，作者手动把选区恢复原句，并把 AI 句移到别处；undo 发现记录 range 不是 applied，回退到全文唯一匹配，把别处的作者句子替换成 before_quote。
**影响** 草稿正文被错误改写（A12：`她撞开门。` 消失，出现两个 `她推开门。`）。P3（draft 内容，不直接丢已保存正文）。
**最小修复** 去掉全文唯一出现回退；只接受记录 range 或 ledger 中保存的上下文/snapshot 定位，无法证明时返回 `relocated_needed`（与 R-01 的窄证据原则一致）。
**探针/输出** `probe_a12.py`：
```text
applied: '开头一句。\n她撞开门。\n结尾一句。\n'
draft before undo: '开头一句。\n她推开门。\n结尾一句。\n她撞开门。\n'
undo result: '开头一句。\n她推开门。\n结尾一句。\n她推开门。\n'
count 她推开门: 2 count 她撞开门: 0
```

### P3-14 保存正文已提交后清草稿失败会 500；恢复响应返回 `draft_cleared=False` 但不再尝试清草稿

**位置** `backend/integration/chapter_editor.py:626-641`（`wb.clear_draft_if_matches` 在 try 之外）；`452-517`（`_recover_completed_save` 只读 draft，不重试清理）
**机制** 正文提交成功后 `clear_draft_if_matches` 抛 SQLite 错误 → 首次保存 500；重试走 `_recover_completed_save`，返回 `saved/recovered=True` 但 `draft_cleared=False`，草稿仍在。要清掉草稿必须换一个新 op_id 再保存一次（走 unchanged 分支）。
**影响** 提交成功却报错，客户端可能继续显示/重提旧草稿；不丢正文。P3。
**最小修复** 把 clear 包进 try，失败时返回 saved + `draft_preserved`/`draft_clear_failed`；`_recover_completed_save` 在 draft 仍匹配 `submitted_draft_id` 时补一次幂等 clear。
**探针/输出** `probe_a10.py CASE 10-3`：
```text
first save RAISED after body commit: RuntimeError simulated draft clear failure
body now: '提交版\n'
draft exists: True
retry status: saved recovered: True draft_cleared: False draft exists: True
third save status: unchanged draft_cleared: True draft exists: False
```

### P3-15 `apply_hunks` 提交成功但 idempotency_complete 失败后无法重放结果

**位置** `backend/integration/annotations.py:719-728`（`_idempotency_complete` 在 impl 成功后调用，失败直接抛出）；`60-76`；`803-804`（无 pending 时 `no_pending_hunks`）
**机制** 草稿/hunk/ledger 已提交，`idempotency_complete` 失败 → 首次 500；立即重试 `op_in_progress`；10 分钟后重执行：原参数因 draft revision 变化 `draft_conflict`，刷新 draft identity 则 `op_id_params_mismatch`；hunk 已 applied，`_apply_hunks_impl` 也不会返回结果。客户端永远拿不到已应用的响应。
**影响** 批注已应用但调用方无法确认；P3（不丢草稿文本）。
**最小修复** `_apply_hunks_impl` 在 selected 全部 `applied_to_draft` 时返回 `already_applied` 摘要而不是 `no_pending_hunks`；或把完成响应持久化到 ledger/draft，重试时从权威状态重建；`_idempotency_complete` 失败不回滚业务，但响应中明确 `applied` + `op_id`。
**探针/输出** `probe_a17.py`：
```text
first apply raised after commit: RuntimeError simulated idempotency_complete failure
draft after raise: '开头一句。\n她撞开门。\n结尾一句。\n'
hunk after raise: applied_to_draft
immediate retry raised: AnnotationError op_in_progress
TTL retry raised: AnnotationError draft_conflict
```

### P3-16 `split_chapter` 带自定义标题时只改版本标题，不落文件名/回执；成功响应后标题分叉直到下一次 recover

**位置** `backend/integration/chapter_editor.py:1314-1335`（`first_title` 传给 `commit_raw_bytes`，但 `_split_chapter_locked` 不调用 `reconcile_title`）；对照 `save_version:607-623` 与 `restore_version:1396`
**机制** 章 1 的正文已存在，`commit_raw_bytes` 记录 `title_pending=True`，正文仍写旧文件名；split 返回 `split` 成功，但 `chapter_state` 标题仍是旧标题，版本 index 标题是新标题。只有下一次 `save_version` 开头的 `recover_pending` 才会改名。
**影响** split 成功后标题（索引/版本）与文件名分叉，UI 两套标题；P3（可自动恢复）。
**最小修复** split 两次 commit 后调用 `versions.reconcile_title(project, chapter, title=first_title, op_id=op_a)`，失败时返回 partial `title_conflict`。
**探针/输出** `probe_a11.py`：
```text
result: {'status': 'split', 'chapter_id': 1, 'new_chapter_id': 2}
files: ['第1章-旧标题.md', '第2章-新标题（续）.md']
chapter_state title: 旧标题
current version title: 新标题
commit title_pending: True
recover_pending: renamed True -> 第1章-新标题.md
```

### P3-17 部分保存响应被冻结在 completed 幂等键：修复成功、后续正文再变后，重放原 op_id 仍返回旧的 partial

**位置** `backend/integration/chapter_editor.py:617-623`（partial 也进入 `_finish` 缓存）；`660`（无条件 `_finish`）；`workbench_db.py:903-910`（`UPDATE ... WHERE state!='completed'`，completed 不再更新）
**机制** 第一次保存因改名冲突返回 partial 并被缓存为 completed；删掉外部文件后重试走 `_recover_completed_save` 返回 saved，但 `_finish` 因键已 completed 不再更新响应；之后正文再保存一次使磁盘 sha 变化，`_recover_completed_save` 返回 None，`_idempotent` 把最初缓存的 partial 原样返回（`title_conflict=True`）。
**影响** 老 op_id 重放会得到与当前事实不符的 partial；P3（不影响正文）。
**最小修复** partial 不写 `idempotency_complete`（或单独存 partial 状态）；或允许 `_finish` 在 `_recover_completed_save` 成功时覆盖 completed 响应。
**探针/输出** `probe_a19.py`：
```text
first: partial title_conflict: True
repair: saved recovered: True
later save: saved
replay original op: partial recovered: None title_conflict: True
```

### P3-18 `revert_draft_hunks` 使用自动提交连接，ledger 删除与 hunk 重置不是同一事务；丢弃草稿失败后 hunk 永久 applied_to_draft

**位置** `backend/integration/annotations.py:1051-1064`（`with wb.connect(project)` 下先 DELETE ledger、再 UPDATE hunk；`isolation_level=None` 自动提交）
**机制** DELETE 成功后 UPDATE 失败：ledger 已删、hunk 仍 `applied_to_draft`，draft 又被 `discard_draft` 删掉，之后没有草稿可触发 `mark_committed`，hunk 永久卡住；`discard_draft` 的 `except Exception: reverted=[]` 把失败吞掉。
**影响** 批注状态永久不一致；不丢正文。P3。
**最小修复** 用 `wb.write_tx` 包住 DELETE+UPDATE+preview 重算；`discard_draft` 把 revert 失败作为响应 warning/partial，不要静默。
**探针/输出** `probe_a10.py CASE 10-4`（SQLite trigger 在 UPDATE 时 abort）：
```text
after discard hunk: applied_to_draft ledger: 0 draft: None
```

---

## 5. 第三轮 P1/P2/P3 逐条复核

| 第三轮条目 | 本轮结论 | 证据 |
|---|---|---|
| A-P1-01 标题/回执/recover | **关闭**：rename/receipt 失败返回 partial，重试/恢复补做；commit 记录 `title_pending` 生效 | probe_a8 A8-1/2/3；测试 `test_receipt_failure_is_partial_and_retry_finishes_it`、`test_recover_pending_finishes_rename_after_commit` |
| A-P1-02 草稿与 hunk/ledger 两事务 | **关闭**：单 `write_tx`；故障注入整体回滚，重试只应用一次 | probe_a8 A8-6；测试 `test_hunk_state_failure_rolls_draft_back_and_retry_applies_once` |
| A-P1-03 split 回滚覆盖 chapter+1 | **关闭**：`_split_entry_is_ours` + 保留并发 entry/receipt；返回 `split_rollback_skipped_concurrent` | probe_a5 CASE 22；测试 `test_concurrent_chapter_plus_one_survives_split_rollback` |
| A-P1-04 legacy list 大纲 500/meta 写坏 | **关闭**：list/dict 全入口规范化；未知形状不落空 legacy | probe_a3 CASE 15（`recover_plan chapters ['1','2']`，无异常） |
| R-01 全文唯一出现即已应用 | **主路径关闭**：候选句在别处不再被采纳；apply 仍改选区、undo 只回退选区 | probe_a8 A8-4；测试 `test_author_text_elsewhere_is_not_adopted_as_a_landed_patch` |
| P2-01 soft op 完成后不幂等 | **仍存在**（P2-01） | probe_a1 CASE 4 + probe_a7 CASE 28 |
| P2-02 改名竞态双文件/重试掩盖 | **部分关闭**：不再谎报 saved；双文件期间仍 409，需手工删（P3-10） | probe_a8 A8-3 + probe_a7 CASE 27 |
| P2-03 备份缺版本对象 | **仍存在**（P2-03） | probe_a3 CASE 13 |
| P2-04 备份标题改名双正文 | **仍存在**（P2-04） | probe_a3 CASE 12 |
| P2-05 重复 restore_trash 复制章节 | **基本关闭**：`already_restored`/force 分离；新增批注恢复 partial 残余（P3-11） | probe_a10 CASE 10-2；测试 `test_restore_trash_rejects_a_second_copy_unless_forced` |
| P2-06 改名覆盖并发 confirm | **关闭**：`_sync_receipt_destination` read-latest 只改 destination | probe_a10 CASE 10-1（`receipt note: concurrent confirm`） |
| P2-07 跨 preview 混选 | **仍存在**（P2-07） | probe_a9 |
| P2-08 split/merge 不迁移批注 | **仍存在**（P2-08） | probe_a4 CASE 17/18 |
| P2-09 大纲同 rev 墓碑 | **仍存在**（P2-09） | probe_a5 CASE 24 |
| P2-10 版本子目录符号链接 | **chapter_versions 部分关闭**；annotations/revision_previews 仍可越界（P2-10） | probe_a5 CASE 23（VersionConflict）+ probe_a14（外部写入） |
| P2-11 resident backup 无一致性 | **仍存在**（P2-11） | probe_a6 CASE 25 |
| P3-01 draft_cleared 硬编码 | **关闭**：恢复时读取实际 draft | probe_a1 CASE 5（`draft_cleared: True`） |
| P3-02 merge_tail 空 params | **仍存在**（P3-02） | probe_a1 CASE 6 |
| P3-03 reject/undo 无幂等 | **仍存在**（P3-03） | probe_a4 CASE 19 |
| P3-04 preview 生命周期 | **仍存在且扩大**（P3-04） | probe_a4 CASE 20 + probe_a18 |
| P3-05 strict_selection | **仍存在**（P3-05） | probe_a2 CASE 9 |
| P3-06 resident restore 不校验哈希 | **仍存在**（P3-06） | probe_a6 CASE 26 |
| P3-07 recover_pending 锁竞争写 recovery_error | **关闭**：返回 `deferred/lock_busy`，record 保持 prepared | probe_a7 CASE 29 |
| P3-08 跨 action op_id 认领 commit | **仍存在**（P3-08） | probe_a4 CASE 21 |
| P3-09 mark_committed 失败被吞 | **仍存在**（P3-09） | probe_a7 CASE 30 |

---

## 6. HYPOTHESIS（只读推演/无法端到端注入；不计入计数）

1. **R-01 窄证据在“候选正好在 hunk 位置但作者自己写”时仍会误判。** `annotations.py:747-762` 的插入/替换检查只要 base 位置是 `before` 且 current 同位置是 `applied` 就采纳；若作者手工在选区输入了与模型候选完全相同的句子（而不是旧崩溃留下的），apply 会把它当作已应用，undo 随后把作者手写的句子改回 `before`。`probe_a8.py CASE A8-5`：
   ```text
   apply status: applied; draft 仍是作者文本
   undo draft: '开头一句。\n她推开门。\n结尾一句。\n'   # 作者手写的“她撞开门。”被回退
   ```
   但当前测试 `test_pending_replacement_already_landed_is_not_left_pending`、`test_pending_hunk_whose_text_already_landed_is_adopted_not_duplicated` 明确把“旧崩溃留下的同文”作为预期恢复语义；两种状态在无 durable apply intent 时不可区分，属产品取舍，故不计 finding。若要求严格归属，应只把“有 ledger/apply_intent 证据”的 hunk 当已应用，旧崩溃状态改为 `already_present_unproven`（不生成 undoable ledger）。
2. **`studio.polish_existing` 提交后写回执不是事务**（`studio.py:531-552`）：`commit_raw_bytes` 后读旧 receipts 快照并整表 `atomic_json`，无 `receipts.lock`；并发 `author_confirm` 会丢失，回执写失败会让已提交章节被发布集合排除。依赖模型/Executor，未做端到端注入（第三轮 HYPOTHESIS 2 未变）。
3. **`delete_chapter` 在 `os.replace(path, archive/path.name)` 之后、`_drop_receipt/_drop_index_entry` 之前进程死亡**（`chapter_editor.py:860-892`）：正文只在 trash，index/receipt 仍指向项目路径；`recover_pending` 不处理，章节在 UI 中消失，需手工 restore trash。未做真实进程死亡注入。
4. **`_hunk_already_present` 采纳旧落地文本时，ledger 的 `applied_range_json` 使用 current 坐标而非 base 坐标**（`annotations.py:850-856`、`923-926` 与 `text_merge.build_intermediate_base:275-340`）：若 current 相对 base 有前缀偏移，后续同 preview 的 apply 用错误 offset 重放 ledger，可能删错 base 区间。仅推演，未构造稳定复现。
5. **`adopt_legacy` / `adopt_originals` / `prune_adopted` 仍无 `file_lock`**（`chapter_versions.py:1413-1530`）：load_index → 修改 → `_save_index`，与并发 `commit_raw_bytes` 可能丢索引更新；当前无生产调用点（第三轮 HYPOTHESIS 1 未变）。
6. **`outline_editor.write_file` 不递增 `meta_revision`/`plan_revision`**（`outline_editor.py:603-717`）：客户端只轮询 meta_revision 时看不到大纲文件内容变更；文件 revision 仍在。第三轮 HYPOTHESIS 5 未变。
7. **`mark_committed` 的 ±120 字符窗口可能误判**（`annotations.py:1122-1136`）：相同替换文本在附近出现时可能把已回退 hunk 标成 committed；未构造稳定复现（第三轮 HYPOTHESIS 4 未变）。

---

## 7. 已覆盖边界

- 已逐行读完范围内 13 个生产文件及主要测试；对 A-P1-01/02/03/04、R-01、P2-01/02/03/04/05/06/07/08/09/10/11、P3-01..09 全部重新核对。
- 基线 1270 个测试全绿（skipped=9）；新增回归测试覆盖：
  - `test_chapter_versions.py`：`test_receipt_failure_is_partial_and_retry_finishes_it`、`test_recover_pending_finishes_rename_after_commit`、`test_nested_store_symlink_is_rejected`；
  - `test_annotations.py`：`test_hunk_state_failure_rolls_draft_back_and_retry_applies_once`、`test_pending_hunk_whose_text_already_landed_is_adopted_not_duplicated`、`test_pending_replacement_already_landed_is_not_left_pending`、`test_author_text_elsewhere_is_not_adopted_as_a_landed_patch`；
  - `test_audit_v095_regressions.py`：`test_concurrent_chapter_plus_one_survives_split_rollback`、`test_rename_race_returns_partial_and_retry_finishes_it`、`test_restore_trash_rejects_a_second_copy_unless_forced`、`test_save_recovers_completed_commit_when_idempotency_complete_fails`、`test_story_plan_chapters_survive_first_meta_write`。
- 本轮实际运行探针：a1–a19（见 §8），覆盖故障注入、单事务回滚、并发保存、备份/恢复、符号链接、undo、幂等键 TTL。
- 已确认的正面点：
  - A-P1-01：`restore_version` 回执写失败返回 `status=partial/title_renamed=True/receipt_synced=False`，不 500；同 op 重试补齐；commit 后死亡由 `recover_pending` 补改名+回执。
  - A-P1-02：`annotations.apply_hunks` 故障注入整体回滚，draft 不存在、hunk pending、ledger 0；重试只应用一次。
  - A-P1-03：split 回滚保留并发 chapter+1 的正文/index/receipt/version，返回 `split_rollback_skipped_concurrent`。
  - A-P1-04：list 格式 story_plan 的 `load_meta/files/conflicts/recover_plan/write_meta` 全部不再 500，`legacy_chapters` 正确归一化。
  - `quality.py` 读路径不建库（C3-04 类）未发现新问题；`workbench_db` 嵌套 savepoint 与幂等状态机未发现回归。

## 8. 未覆盖边界与测试缺口

- 未做真实多进程竞争/Windows ACL/杀软占用/磁盘满注入；P1-05、P2-07、P2-11 的窗口为单进程故障注入或代码推演。
- 未端到端运行 `studio.polish_existing`（依赖模型/Executor），仅代码审阅（HYPOTHESIS 2）。
- 未验证真实 DSH React 前端是否会把不同 preview 的 hunk 一起提交（P2-07 的触发面）、是否会重复点击 restore（P2-05/P3-11）、是否会在 partial 后重试旧 op_id（P3-17）。
- 测试缺口（本轮探针已复现但现有套件无覆盖）：
  - backup object 完整性（P2-03）、backup 标题改名双正文（P2-04）、backup trash/snapshots/revision_previews（P2-12）；
  - split/merge 的 annotations 迁移（P2-08）；
  - 多文件同 rev 墓碑重加（P2-09）；
  - 跨 preview 混选（P2-07）；
  - resident backup 索引/正文竞态、restore 哈希校验（P2-11/P3-06）；
  - annotation preview 生命周期（P3-04）、strict_selection（P3-05）、mark_committed/revert 失败（P3-09/P3-18）；
  - restore_trash 与并发 save 的锁窗口（P1-05）；
  - split 自定义标题（P3-16）、save partial 缓存（P3-17）、apply 完成键失败（P3-15）。

## 9. 探针复现命令

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v4/head-a
PY=/home/ubuntu/venvs/dsh/bin/python
export PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend

$PY -B -X utf8 ../tmp-a/probe_a1.py    # P2-01, P3-01, P3-02
$PY -B -X utf8 ../tmp-a/probe_a2.py    # P3-05, overlap, reject+mark
$PY -B -X utf8 ../tmp-a/probe_a3.py    # P2-03, P2-04, P2-05(基础), A-P1-04
#   注：a3 的 CASE 14 现在按设计抛 already_restored，会中断脚本；可单独调用 case_outline_legacy_list()
$PY -B -X utf8 ../tmp-a/probe_a4.py    # P2-08, P3-03, P3-04(delete), P3-08
$PY -B -X utf8 ../tmp-a/probe_a5.py    # P1-03, P2-09, P2-10(chapter_versions 部分)
$PY -B -X utf8 ../tmp-a/probe_a6.py    # P2-11, P3-06
$PY -B -X utf8 ../tmp-a/probe_a7.py    # P2-01(TTL), P2-02 双文件, P3-07(已修), P3-09
$PY -B -X utf8 ../tmp-a/probe_a8.py    # A-P1-01/02, R-01, undo 两事务
$PY -B -X utf8 ../tmp-a/probe_a9.py    # P2-07 跨 preview
$PY -B -X utf8 ../tmp-a/probe_a10.py   # P2-06(已修), P3-11, P3-14, P3-18
$PY -B -X utf8 ../tmp-a/probe_a11.py   # P3-16 split 标题
$PY -B -X utf8 ../tmp-a/probe_a12.py   # P3-13 reverse_patch
$PY -B -X utf8 ../tmp-a/probe_a13.py   # P1-05 restore_trash 并发
$PY -B -X utf8 ../tmp-a/probe_a14.py   # P2-10 annotations/revision 符号链接
$PY -B -X utf8 ../tmp-a/probe_a15.py   # P2-12 snapshots/previews
$PY -B -X utf8 ../tmp-a/probe_a16.py   # P2-12 trash
$PY -B -X utf8 ../tmp-a/probe_a17.py   # P3-15 apply 完成键
$PY -B -X utf8 ../tmp-a/probe_a18.py   # P3-04 preview 生命周期
$PY -B -X utf8 ../tmp-a/probe_a19.py   # P3-17 partial 缓存
```

所有探针只使用 `tempfile.TemporaryDirectory()` 和仓库只读导入，不修改仓库文件；`tmp-a/` 下脚本可复跑。`git status --short` 仅有预先存在的未跟踪 `node_modules`（仓库 `.gitignore` 之外的符号链接目录），无代码改动。
