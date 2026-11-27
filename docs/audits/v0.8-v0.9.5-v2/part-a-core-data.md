# 第二次独立审计 · A 部分：核心数据 / 版本 / 事务 / 编辑写入门禁

- 审计对象：`/home/ubuntu/.hermes/cache/scratch/audit-v2-head`，detached HEAD `5e8a2d092422faf8407cfbeba5bf190427154ed4`（5e8a2d0）
- 审计方式：只读审阅 + 自写复现脚本；未修改仓库、未联网、未引用/依赖 `docs/audits` 旧报告
- 运行环境：Python 3.12.3（`/home/ubuntu/venvs/dsh`），Linux 6.8
- 复现脚本目录：`/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01/`（`s1`–`s23`，汇总输出 `results.txt`）
- 审计时间：2026-11-27T04:46Z

## 0. 结论摘要

| 严重度 | 数量 |
|---|---|
| P0 | 0 |
| P1 | 4 |
| P2 | 14 |

| 编号 | 严重度 | 结论 | 主要位置 |
|---|---|---|---|
| P1-1 | P1 | `recover_pending` 对 raw 提交回退时 `KeyError`，恢复循环中断；常驻服务启动时直接退出 | `chapter_versions.py:554-559`、`resident_service.py:489-505` |
| P1-2 | P1 | `split_chapter` 回滚无条件把旧字节写回并恢复整份索引快照，抹掉并发窗口内已确认的保存 | `chapter_editor.py:794-808` |
| P1-3 | P1 | `recover_pending` 不跳过 `state=conflict`，后续恢复会重新落地冲突提交，静默覆盖作者已回退/删除的正文 | `chapter_versions.py:545-605` |
| P1-4 | P1 | `delete_chapter` 完全不在写锁内：与保存竞态丢失已确认正文；锁竞争时留下“文件已进回收站、索引仍在”的半删状态；不检查 `task_queue` | `chapter_editor.py:573-648` |
| P2-1 | P2 | `save_version` 提交成功后 `_finish` 失败，幂等键停在 `in_progress`；重试得到 409 而非已提交结果 | `chapter_editor.py:362-378, 503` |
| P2-2 | P2 | `restore_version` 先提交正文再做标题改名；改名冲突时返回 409，但正文和版本已改变 | `chapter_versions.py:847-858` |
| P2-3 | P2 | `restore_version` 改名后不更新 `writer_receipts.destination`，后续排期/发布按回执读旧路径会失败 | `chapter_versions.py:852-857` |
| P2-4 | P2 | 旧书 `story_plan.json` 中未被 `AI规划-*.md` 覆盖的章节细纲，在首次写大纲 meta/文件时被清空 | `outline_editor.py:198-218, 416-447, 573-601` |
| P2-5 | P2 | split/merge 回滚后留下确定性 op 名的已提交记录，原样重试永久 `operation_incomplete` | `chapter_editor.py:785-808, 833-865` |
| P2-6 | P2 | 标题按“字符数”限 120，但最终文件名按 UTF-8 字节超 255；新章返回 500 并留下 `prepared` 提交，阻塞恢复 | `chapter_editor.py:39-41, 101-110`、`chapter_versions.py:272-277, 419-433` |
| P2-7 | P2 | `backup` 的 barrier 只覆盖 transaction_journal，不覆盖 `chapter_versions` 提交；备份可含新索引+旧正文，`inspect_backup` 仍报 valid | `transaction_journal.py:994-1006, 1141-1233` |
| P2-8 | P2 | `invalidate` 先写日志再标记忆；中途失败后同 op 重试返回 `reused`，旧事实永久保持 active | `invalidation.py:142-165` |
| P2-9 | P2 | `revision_plan.accept` 提交正文后才标记 preview；中途失败后重试永远 `source_changed` | `revision_plan.py:391-411` |
| P2-10 | P2 | `op_id` 只在 `save_version`/`author_confirm` 真正幂等；new/delete/split/merge/import/outline 写接口接受但不用，响应丢失后的重试报 409/404 | 多处（见正文） |
| P2-11 | P2 | 回收站恢复不还原删除时归档的批注与草稿，只还原正文/版本 | `chapter_editor.py:604-625, 668-743` |
| P2-12 | P2 | 符号链接的 `大纲/`、`设定/`、`.webnovel/chapter_versions/` 未被拒绝，写入可落到项目外 | `outline_editor.py:109-117, 606-615`、`chapter_versions.py:102-127` |
| P2-13 | P2 | `studio.polish_existing` 回写未把 `expected_sha256` 传给 `commit_raw_bytes`，润色窗口内的保存被静默覆盖 | `studio.py:529-539` |
| P2-14 | P2 | `_drop_receipt` 读改写不带 `receipts.lock`，会覆盖并发 `author_confirm` 刚写入的回执 | `chapter_editor.py:566-570`、`152-160` |

> 注：P2-4、P2-12 的触发依赖旧书/本地目录的前置条件，报告内已注明；不计入“正常单用户默认路径”。

---

## 1. P1 级

### P1-1 `recover_pending` 对 raw 提交回退抛 `KeyError`，恢复循环中断且常驻服务启动失败

**位置**
- `backend/integration/chapter_versions.py:541-606`，关键行 `554`、`558`
- `backend/integration/resident_service.py:489-505`（`_recover_pending` 的捕获范围）
- `backend/integration/resident_service.py:411`（`run()` 启动时调用，外层无 `except`）
- `backend/integration/chapter_editor.py:397-400`（`save_version` 用 `except Exception: pass` 吞掉）

**机制**

`commit_raw_bytes()` 在写正文/对象之前就先落盘提交记录，而这类记录 `candidate_id=None`：

```python
"candidate_id": None,
"raw_bytes": True,
```

进程若在 `atomic_json(commit记录)` 之后、`_store_object(data)` 之前被杀（或 `_store_object` 失败），会留下 `state=prepared` 且对象缺失的记录。`recover_pending()` 读取时：

```python
candidate = read_candidate(...) if record.get("candidate_id") else {}
try:
    data = read_object(project, sha)          # VersionNotFound
except VersionError:
    _store_object(project, _encode(candidate["content"]))   # candidate == {} -> KeyError
```

`KeyError` 不是 `VersionError`，直接冲出整个 `for path in sorted(commits)` 循环，不会处理后面的任何记录；`resident_service._recover_pending()` 只捕获 `(ValueError, OSError, RuntimeError)`，`KeyError` 继续上抛，`run()` 在 `recovered = _recover_pending(base)` 处无兜底 `except`，常驻服务进程直接退出。`save_version` 里的 `except Exception: pass` 则使恢复永久静默失败。

**影响**

- 单个被强杀/磁盘错误留下的 raw 提交（新建章节、导入、拆分、合并、恢复、回收站还原、润色都会走 `commit_raw_bytes`）可让常驻写稿服务无法启动，后续所有自动任务停摆；
- 即使不启动服务，任何 `save_version` 的恢复前置步骤都失败，其他章的半提交永远不被补齐；
- 触发只需一次“提交记录已落盘、对象未落盘”的崩溃窗口，正是该模块声称要处理的场景。

**最小修复**

1. `recover_pending` 内部对每条记录 `try/except Exception` 隔离：无法处理的记录标记为 `recovery_error`/`conflict` 并继续下一条；
2. `candidate_id` 为空且对象缺失时，不要伪造 `candidate["content"]`，直接标记 `conflict`（`source_missing`）并保留现场；
3. `resident_service._recover_pending` 至少捕获 `Exception` 并将项目标记 degraded，避免单坏项目阻断服务启动。

**复现**

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 s2_recover_keyerror.py
```

实际输出（节选）：

```text
commit record written; object exists: False
=== recover_pending raised ===
KeyError: 'content'
resident _recover_pending raised: KeyError 'content'
disc still old: True | commit state: prepared
```

脚本用真实的 `commit_raw_bytes` 记录格式（`candidate_id=None`、`state=prepared`、对象不在 `objects/`），然后调用公开的 `recover_pending()` 与 `resident_service._recover_pending()`；没有 mock 内部恢复逻辑。

---

### P1-2 `split_chapter` 回滚无条件写回旧字节并恢复整份索引快照，抹掉并发已确认的保存

**位置**
- `backend/integration/chapter_editor.py:757-812`
- 关键回滚：`795`（`path.write_bytes(old_bytes)`）、`798`（把 `backup_index` 整体写回）
- 与保存的入口差异：`save_version` 在 `406` 取 `_locked`，`split_chapter` 全程不取任何章锁

**机制**

`split_chapter` 先读 `raw`/`expected_content_sha256`，然后依次提交后半章、前半章。若期间另一个窗口完成一次正常 `save_version`：

1. 保存写入新正文与索引，返回成功；
2. split 的前半章提交因为 `expected_sha256=_raw_sha(raw)` 已不匹配而抛 `concurrent_modification`（这是正确拒绝）；
3. 异常分支却无条件执行 `path.write_bytes(old_bytes)`，把作者刚保存的新正文覆盖回旧字节；再执行
   `_atomic(index.json, json.loads(backup_index))`，把保存刚写入的版本从索引整体回滚；
4. `recover_pending()` 对该保存的提交记录是 `committed`，直接跳过，**不会**修复。

也就是说，split 检测到了并发修改，却用回滚把并发修改销毁了。

**影响**

- 已向客户端返回 `status=saved` 的正文被静默回退，索引中该版本消失（对象与 commit 记录还在，但无入口）；
- 作者看到的是“拆分因并发修改失败”，实际损失的是自己刚保存的那次修改；若没有手工从 objects/commit 恢复，等同于数据丢失；
- 同样的整份索引快照回滚会丢掉 split 窗口内其他章节的版本提交（`index.json` 是整书共享）。

**最小修复**

- split 全程持有 `_locked(project, chapter)`（与 `save_version` 同锁），并在回滚前重新读取并比较 `file_sha256(path)`：只有仍等于本次读取的 `raw` 时才写回；已变化则保留新正文，返回 `split_aborted_concurrent_modification`；
- 不要用整份 `backup_index` 覆盖；在 `versions` 锁内重新 `load_index`，只删除/回滚本次为 `chapter+1` 创建的版本和 `current` 指针；
- 回滚本身的正文写回也应带 `expected_sha256` 条件（或走 `commit_raw_bytes` 的并发校验）。

**复现**

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 s7b_split_clobber_natural.py
```

实际输出：

```text
split error: VersionConflict concurrent_modification
save API said: saved 108b29db2190
index current: 4fe8135da6fb | equals saved: False
versions: [('legacy-adopted', 'ver_0001_df610f83')]
recover_pending: []
```

`saved` 的正文在磁盘上已不存在，索引也没有它；`recover_pending` 返回空，说明不会自动修复。

---

### P1-3 `recover_pending` 重新评估 `conflict` 记录，静默覆盖作者已回退/删除的正文

**位置**
- `backend/integration/chapter_versions.py:545-605`
- 跳过条件：`547` 只跳过 `state == "committed"`，没有跳过 `"conflict"`
- 冲突标记：`815-822`（`_mark_conflict`）

**机制**

`recover_pending()` 对每一个非 `committed` 记录重新执行：

- 若 `entry.current == sha` → 标 committed；
- 若 `current_sha == sha` → 补索引；
- 若 `current_sha in (previous_sha256, None)` → **直接写回候选正文并登记版本**；
- 否则标 `conflict`。

`conflict` 记录在下一次恢复（常驻服务启动、任意 `save_version` 前置调用）会被再次评估。如果作者在冲突后把正文恢复成 `previous_sha256` 对应的旧版本，或删除了该章（`current_sha is None`），第三条分支成立，写手旧候选被自动写回，覆盖作者的回退/删除。`conflict_current` 字段只写不读。

**影响**

- 标记为“需人工处理”的冲突提交不是终态，会在没有作者确认的情况下自行落地；
- 作者明确回退或删除的正文被旧候选覆盖；被删除的章节可能被恢复；
- 与 P1-1 同属恢复状态机：一旦记录存在，服务每次启动都会重试。

**最小修复**

- `recover_pending` 明确跳过 `state in {"committed", "conflict"}`；新增显式的 `resolve_conflict(op_id, action)` 入口，只有作者确认后才允许重放或丢弃；
- 或在 `conflict` 记录上保存 `conflict_current` 并在状态变化时要求人工确认，不允许自动进入写回分支。

**复现**（两阶段，全部走真实 `recover_pending` 状态机）

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 s15b_conflict_natural.py
```

实际输出：

```text
first recover: [{'op_id': 'conf-natural', 'chapter_id': 1, 'state': 'conflict'}]
state after first: conflict
second recover: [{'op_id': 'conf-natural', 'chapter_id': 1, 'state': 'committed'}]
body after second: '写手候选稿X\n'
state after second: committed
```

第一阶段：崩溃残留的 `chapter_written` 记录遇到作者改过的正文，被正确标为 `conflict`；第二阶段：作者把正文恢复为 `previous_sha256` 后，同一 `conflict` 记录被自动重放并覆盖正文。

---

### P1-4 `delete_chapter` 不在写锁内：与保存竞态丢失已确认正文；锁竞争留下半删状态；不检查任务队列

**位置**
- `backend/integration/chapter_editor.py:573-648`
- 状态读取/校验：`577-595`
- 移入回收站：`627`
- 删回执/索引：`639-640`（`_drop_receipt`、`_drop_index_entry`）
- 对照：`save_version` 在 `406` 使用 `_locked(project, chapter)`

**机制**

`delete_chapter` 全程不获取章锁，也不获取 `versions` 锁：

1. 读取 `mapping`、`current_sha`、`meta`，校验 `expected_content_sha256/expected_version_id`；
2. 写回收站副本与 manifest（manifest 记录的是读取时的 `current_sha`）；
3. `os.replace(path, archive / path.name)` 把当前正文移走；
4. 之后才 `_drop_receipt`、`_drop_index_entry`、`wb.delete_draft`。

并发窗口内 `save_version` 可以完整成功（它只取章锁，不取 delete 的锁）。结果是：保存返回 `saved`，但新正文已被移入回收站；随后 delete 删掉索引条目，版本历史消失。更糟的是回收站 manifest 的 `content_sha256/payload_sha256` 仍是旧值，而 `original.md` 已经是新正文，`restore_trash` 的 `trash_payload_corrupt` 校验会拒绝恢复。

另外两种同源问题：

- 若 `_drop_index_entry` 在取 `versions` 锁时遇到另一个提交占用（`file_lock` 非阻塞，抛 `PublicationBlocked("resource_busy")`），正文已经 `os.replace` 走、索引还没删，API 返回 503；用户重试 delete 得到 `chapter_missing`，只能靠手工 restore；
- `task_queue` 中 `pending/running` 的任务不检查（docstring 却声称“未发布、未入队”），删章后任务仍留在队列（见 s20）。

**影响**

- 并发两窗口（一个删除尾章、一个保存）会丢失已确认的保存，且回收站恢复被 manifest 校验拒绝；
- 锁竞争导致“正文已消失、索引仍存在”的半删状态，重试删除 404；
- 队列中仍指向已删除章的任务会在 worker 领取后失败或写回已删除章（取决于 payload）。

**最小修复**

- `delete_chapter` 使用与 `save_version` 相同的 `_locked(project, chapter)`，并在锁内重新读取 `current_sha`、`meta`、`published` 后再校验；
- 在删除前后都按固定顺序获取 `versions` / receipts 锁（`_drop_index_entry` 已取 versions 锁；把整个删除流程纳入同一临界区），失败时把文件从回收站移回并恢复回执；
- 检查 `task_queue WHERE chapter_id=? AND state IN ('pending','running','held')`，有活动任务时返回 409（或要求显式 force）；
- 回收站 manifest 在 `os.replace` 前用同一份字节计算 sha 并校验，避免“manifest 与 payload 不一致”的回收站条目。

**复现**

并发保存：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 s5_delete_race.py
```

```text
delete result: deleted 20261127T124523-ch0001
racing save API said: saved 910c3c3c920b
chapter file still exists: False
index has chapter: False
current_version: None
trash payload sha == manifest payload_sha256: False
trash payload: '作者刚保存的重要新正文\n'
restore failed: trash_payload_corrupt
```

锁竞争半删状态：

```bash
... python3 -B -X utf8 s17_delete_lock.py
```

```text
delete error: PublicationBlocked resource_busy
chapter file exists: False
index still has chapter: True
trash entries: ['20261127T124526-ch0001']
```

任务队列（docstring 声称未入队）：

```bash
... python3 -B -X utf8 s20_delete_queue.py
```

```text
queued task: task_71204fcd pending
delete: deleted
task after delete: {'task_id': 'task_71204fcd', 'chapter_id': 1, 'state': 'pending'}
chapter on disk: None
```

---

## 2. P2 级

### P2-1 `save_version` 提交成功后 `_finish` 失败，幂等键停在 in_progress，重试 409

**位置**：`chapter_editor.py:362-378`（`_idempotent`）、`381-504`（`save_version`）、`503`（`_finish` 在 `_locked` 退出后调用）
**机制**：`_idempotent()` 在开始时把 op 置 `in_progress`；正文/索引提交在 `_locked` 内完成；`_finish()` 在锁外执行 `wb.idempotency_complete`。若 `idempotency_complete` 因 SQLite busy/磁盘错误/进程崩溃失败，提交已经成功，但响应丢失且键停在 `in_progress`。600 秒内重试得到 `op_in_progress`；600 秒后 `failed_retry` 重新执行，`save_version` 先做 `expected_sha != current_sha` 检查（旧期望 vs 新正文），返回 `concurrent_modification`，永远拿不到已提交结果。
**影响**：客户端无法区分“保存成功但回执丢失”和“并发冲突”；用户被误导为别的窗口改了正文；没有任何自动修复路径（commit 记录已 committed，`recover_pending` 跳过）。
**最小修复**：`_finish` 改为 best-effort（失败只记录，不影响已成功的响应）；或在 `_idempotent` 返回 `failed_retry` 时先按 `op_id` 查 `_load_commit`，若记录 `committed` 且 body sha 匹配则直接重建并返回原响应，跳过并发期望检查。
**复现**：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 s4_idem_gap.py
```

```text
first attempt error: RuntimeError simulated crash after commit, before idempotency_complete
body after failed response: '第二版正文\n' changed: True
index current == new body: True | versions: 2
idem state: in_progress
retry now error: op_in_progress 409
retry after ttl error: concurrent_modification 409 正文已在其他窗口、任务或外部编辑器中更新，请比对后保存
final body: '第二版正文\n' | versions: 2
```

---

### P2-2 `restore_version` 先提交后改名，改名冲突时返回 409 但正文/版本已改变

**位置**：`chapter_versions.py:828-859`，关键 `847-857`
**机制**：`restore_version` 先调用 `commit_raw_bytes()`（写正文、登记新版本、更新索引、触发失效），然后才构造 `第N章-{title}.md` 目标并 `replace_with_retry`。若目标名被目录/同名文件占用，`target.exists()` 抛 `restore_title_conflict`，但此时正文已经是恢复内容、索引已经指向新版本。
**影响**：API 报告恢复失败，实际正文已变化；前端可能提示用户重试，重试会再登记一个版本；`chapter_state` 的标题与索引中的 version title 不一致。
**最小修复**：把目标文件名预检放到 `commit_raw_bytes` 之前（与 `save_version` 的 `446-451` 一致）；或者先改名再提交，失败时回滚改名；失败后返回“已恢复正文但标题未改”的结构化部分成功。
**复现**：

```bash
... python3 -B -X utf8 s6_restore_title.py
```

```text
restore error: VersionConflict restore_title_conflict
after disk: '目标版本正文A\n'
body changed despite error: True
version count: 3 | current version: ver_0003_... | target was: ver_0001_...
```

（目标名被 `第5章-新标题.md` 目录占位。）

---

### P2-3 `restore_version` 改名后不更新 `writer_receipts.destination`，发布/排期读旧路径

**位置**：`chapter_versions.py:852-857`（只 `replace_with_retry`，没有回执更新）；对照 `chapter_editor.py:507-526`（`save_version` 的 `_rename_chapter_file` 会更新 `destination`）
**机制**：恢复一个标题不同的版本会把 `第5章-旧标题.md` 改名为 `第5章-新标题.md`，但 `.webnovel/writer_receipts.json` 中 `destination` 仍是旧文件名。`scheduler.py:792`、`draft_delivery.py:86`、`scheduled_delivery.py:145`、`local_completion.py:164` 都直接读取/比对 `receipt["destination"]`，旧路径不存在时排期任务失败或本地完成校验拒绝。
**影响**：一次正常的“恢复旧版本并恢复标题”后，该章无法自动发布/投递，UI 的回执状态与实际文件脱节；需要手工改回执或再保存一次。
**最小修复**：把 `_rename_chapter_file` 的回执更新逻辑抽到 `chapter_versions`（或由 `restore_version` 复用），改名后在同一临界区更新 `destination`；同时更新提交记录里的 `chapter_path`。
**复现**：

```bash
... python3 -B -X utf8 s12_restore_receipt.py
```

```text
restore: restored | old name: 第5章-旧标题.md | now: 第5章-新标题.md
receipt destination: .../书/正文/第5章-旧标题.md
receipt destination exists: False
receipt points at current file: False
```

---

### P2-4 旧书 `story_plan.json` 的章节细纲在首次写大纲 meta/文件时被清空

**位置**：`outline_editor.py:182-218`（`load_meta` 迁移只搬 4 个文本字段，不搬 `chapters`）、`416-447`（`recover_plan` 只从 `AI规划-*.md` 重建）、`226-241`（`_sync_story_plan` 写入 `chapters`）、`573-601`（`write_meta` 触发 `recover_plan(persist=True)`）
**机制**：v0.7.5 的 `studio.plan_async` 同时写 `大纲/AI规划-*.md` 和 `story_plan.json`。但旧书可能存在 `story_plan.json` 有章节、对应 AI规划 md 被改名/删除/只保留了部分章节的情况（或项目由外部工具/手工维护）。`load_meta` 迁移不保留 `chapters`；`_merge_chapters` 只扫描 `AI规划-*.md`；`recover_plan(persist=True)` 于是以空 `chapters` 调 `_sync_story_plan`，把 `story_plan.json` 的章节表覆盖为 `{}`，只在 `conflicts` 里留一条 `outline_file_missing`。
**影响**：升级后作者第一次保存“总纲/分卷/人物弧线”或编辑任一 md 大纲，旧章节细纲从 `story_plan.json` 永久消失（无备份、无迁移）；`scenes._chapter_entry`、`writer_runner` 读到的章节规划变为空；只能靠旧快照恢复。
**最小修复**：迁移时若 `story_plan.json` 有 `chapters` 且没有对应 AI规划 md，保留这些章节（在 meta 中标记 `legacy_chapters`），或生成一个 `AI规划-legacy-*.md` 再重建；`recover_plan` 合并而非覆盖旧 `chapters`，删除需 `confirm_removed_chapters` 显式确认。
**复现**：

```bash
... python3 -B -X utf8 s3_legacy_outline.py
```

```text
before chapters: ['1', '2']
after  chapters: []
conflicts: [('outline_file_missing', ['1', '2'])]
meta exists: True
scenes chapter 1 outline: {'outline': ''}
```

---

### P2-5 split/merge 回滚后留下确定性提交记录，原样重试永久 `operation_incomplete`

**位置**：`chapter_editor.py:785-808`（split 的 `-b`/`-a` 确定性 op 名，回滚只删正文/索引/回执，不删 commit）、`833-865`（merge 的 `merge-{n}-{m}`，回滚不删 commit）
**机制**：split 的后半章提交记录 `split-{N+1}-b` 在回滚时仍为 `committed`；重试时 `commit_raw_bytes` 读到该记录，但目标文件已被回滚删除，`state=="committed" and file_sha==sha and index.current==sha` 不成立，抛 `operation_incomplete`。merge 同理：回滚恢复了前一章旧字节，`merge-{n}-{m}` 记录仍 committed，重试 `commit_candidate` 抛 `operation_incomplete`。
**影响**：一次可处理的失败（磁盘错误、并发修改、删除尾章失败）之后，该章永远无法再次拆分/合并，必须手工删除 `.webnovel/chapter_versions/commits/*.json`；UI 只显示 409，无恢复入口。
**最小修复**：回滚时删除或标记本次创建的 commit 记录为 `abandoned`（连同对象引用计数）；或改用随机 `tx_id` 并在回滚时清理；`commit_raw_bytes/commit_candidate` 对“记录 committed 但目标缺失且记录被标记 aborted”的情况允许重试。
**复现**：

```bash
... python3 -B -X utf8 s1_split_rollback.py
... python3 -B -X utf8 s13_merge_retry.py
```

```text
post-rollback commits: ['split-2-b.json']
retry failed: VersionConflict | operation_incomplete
```

```text
merge failed: RuntimeError simulated failure while deleting merged tail
commit records: ['merge-1-2.json']
retry failed: VersionConflict operation_incomplete
```

---

### P2-6 标题字符数限制与文件名字节限制不一致；超长中文标题留下 prepared 提交并阻塞恢复

**位置**：`chapter_editor.py:39-41`（`MAX_TITLE_CHARS=120`）、`101-110`（只按字符数校验）；`chapter_versions.py:272-277`（文件名 `第N章-{title}.md`）、`419-433`（临时文件 `*.uuid.tmp`）
**机制**：120 个 CJK 字符 = 360 字节；Linux ext4 文件名上限 255 字节，临时文件名还要加 `.` + 32 hex + `.tmp`。`_validate_title` 通过后，`_write_chapter_bytes` 的 `temporary.open("xb")` 抛 `OSError(ENAMETOOLONG)`。`commit_raw_bytes` 在写正文前已经写了 `state=prepared` 提交记录，异常直接上抛，没有清理；之后 `recover_pending` 重放同一记录再次 `ENAMETOOLONG`，并且和 P1-1 一样中断整个恢复循环。
**影响**：较长中文标题的“新建章节/导入/回收站还原”返回 500；项目里留下永久失败的 prepared 记录，阻塞后续恢复；用户无法通过 UI 自行修复，只能删 commit 文件。
**最小修复**：在 `_validate_title`/`_write_chapter_bytes` 前按 UTF-8 字节计算最终文件名（含前缀、后缀、临时后缀），超限即返回 400 `title_too_long_for_filesystem`；`recover_pending` 对 `OSError` 做单记录隔离并标记 conflict。
**复现**：

```bash
... python3 -B -X utf8 s8_title_len.py
```

```text
new_chapter error: OSError 36 [Errno 36] File name too long: '.../第1章-长长...长.md.<uuid>.tmp'
commit files: ['new1.json']
record state: prepared
正文 files: []
recover_pending raised: OSError 36 [Errno 36] File name too long
```

---

### P2-7 `backup` 的 barrier 不覆盖 `chapter_versions` 提交，备份可自相矛盾且 `inspect_backup` 仍 valid

**位置**：`transaction_journal.py:994-1006`（`barrier` 只看 `transactions/tx_*.json`）、`1141-1233`（`backup` 先 `_copy_tree(正文)` 再复制 `chapter_versions/index.json`）
**机制**：`chapter_versions.commit_candidate/commit_raw_bytes` 不创建 transaction_journal 记录，`barrier` 完全看不到它们。备份按“正文 → 大纲 → 设定 → index.json → objects”顺序复制；若保存发生在正文复制之后、index 复制之前，备份得到旧正文 + 新 index；manifest 对每个文件单独算 sha，所以 `inspect_backup` 仍 `valid=True`。
**影响**：备份是恢复的最后一道防线，但可能包含“索引指向的版本正文不在快照里”或相反的不一致；恢复后 `compare_current`/`report_ref` 显示 stale，作者确认失效；若后续再基于该备份恢复，会丢失/错配版本。
**最小修复**：备份与 `save_version` 使用同一写锁（让 `save_version` 也取一个项目级读/写屏障），或至少在 `backup` 内取 `chapter_versions/.lock` 后复制 index 与正文，并在 manifest 中记录 `chapter_versions` 的代次；`inspect_backup` 增加“index current 与正文 sha 一致性”校验。
**复现**：

```bash
... python3 -B -X utf8 s10_backup_race.py
```

```text
backup index current: 394052d68dd3
backup body sha    : 9ac8b4e7bfc4
consistent: False | inspect valid: True
```

---

### P2-8 `invalidate` 先写日志再标记忆；失败/崩溃后同 op 重试返回 `reused`，旧事实永久 active

**位置**：`invalidation.py:142-165`（`_invalidate_once`），日志写入 `156-158`，`_mark_facts` `159`；去重 `147-151`
**机制**：`_invalidate_once` 先把带 `marked` 列表的 entry 写入日志，再调用 `_mark_facts` 修改 `shared_memory.json` 的状态。若 `_mark_facts` 失败（锁、磁盘、进程崩溃），`invalidate` 抛错；`write_chapter` 捕获后把 `invalidation` 记为 `skipped`，正文保存仍成功。之后同一 `op_id` 重试会命中日志去重，返回 `{"status":"reused"}`，不会补标记，也没有其他后台任务重试。
**影响**：被改写章节来源的旧事实继续以 `active` 进入后续生成上下文，违反“源章变化 → 旧证据进待复核”的门禁；日志却显示已标记（`marked` 非空），审计记录与真实状态不一致。
**最小修复**：日志 entry 增加 `state: pending/applied`，先写 pending，`_mark_facts` 成功后再更新 applied；`reused` 分支若发现 pending 则重新执行标记；或先标记再写日志（失败则无日志，重试会重新来）。
**复现**：

```bash
... python3 -B -X utf8 s11_invalidation.py
```

```text
after failure status: active
log entries: 1 | marked in log: 1
retry status: reused | fact status: active
```

---

### P2-9 `revision_plan.accept` 提交正文后才标记 preview；中途失败后重试永远 `source_changed`

**位置**：`revision_plan.py:391-411`，提交 `401-403`，标记 `404`，失效 `406-408`
**机制**：`accept` 先 `commit_candidate`（正文/索引已变），再 `_mark(preview, "accepted")`。若 `_mark` 失败（磁盘、锁）或进程崩溃，preview 仍是 `pending`，但磁盘正文已是候选。重试时 `base = record["base_sha256"]`（旧正文），`current` 是新正文，`current != base` → `VersionConflict("source_changed")`；reject 也会把已提交的 preview 标记为 rejected。
**影响**：用户看到“接受修订失败”，实际正文已改；preview 永远无法关闭，后续 `revision_plan.public` 一直展示 pending 的旧 diff；`invalidation` 也可能未执行（`_mark` 失败在 `invalidate` 之前）。
**最小修复**：accept 改为幂等状态机：重试时若 `current == candidate_sha256` 且 preview pending，直接补 `accepted` 并返回成功（必要时补 invalidation）；或先把 preview 置 `accepting` 再提交，失败可回滚/续跑。
**复现**：

```bash
... python3 -B -X utf8 s19_preview_accept.py
```

```text
accept error: OSError simulated crash after commit, before marking preview accepted
body after failed accept: '修订后的正文\n'
preview state: pending
retry accept error: VersionConflict source_changed
```

---

### P2-10 `op_id` 只在两个入口真正幂等，其他写接口接受但不用

**位置**
- `chapter_editor.py:529-547`（`new_chapter` 只用 `_validate_op_id`，未查/存幂等结果）
- `chapter_editor.py:573-575`（`delete_chapter` 只把 op 写进回收站 manifest）
- `chapter_editor.py:757-760`、`815-816`（split/merge 把 op 拼进 commit op 名，但入口不查已完成结果）
- `chapter_editor.py:896-905`（`import_chapters` 先检查 `chapter_exists`，重试到不了 commit 幂等分支）
- `outline_editor.py:450-452`（`write_file` 只把 op_id 原样返回）

**机制/影响**：网络超时/响应丢失后客户端按同一 `op_id` 重试，服务端无法返回原结果，而是报：
- new_chapter：`operation_id_reused`（不指定 chapter 时先算成 max+1）或 `chapter_exists`；若客户端换新 op 重试则可能多建一章；
- delete：404 `chapter_missing`；
- split：`only_tail_chapter_supported`；
- merge：`merge_needs_two_chapters` / `operation_id_reused`；
- import：`chapter_exists`；
- outline write：`outline_conflict`（revision 已变）。

这些操作实际上都已成功，但调用方得到失败信号，容易触发重复操作或人工误判。

**最小修复**：统一实现“op_id → 结果/资源 id”的持久幂等表（可复用 `workbench_db.idempotency_keys`），在参数校验/资源存在性检查之前查询；或从这些 API 移除 `op_id` 字段，避免虚假的幂等承诺。
**复现**：

```bash
... python3 -B -X utf8 s9_new_chapter_retry.py
... python3 -B -X utf8 s21_outline_retry.py
```

```text
first: created chapter_id: 1
retry same op_id error: VersionConflict operation_id_reused
chapters on disk: ['第1章-开端.md']
```

```text
write: saved | new rev: e9d191ddb21a
retry error: OutlineError outline_conflict
```

（delete/split/merge/import 的 404/409 由同一入口逻辑直接推出，未单独写脚本。）

---

### P2-11 回收站恢复不还原删除时归档的批注与草稿

**位置**：`chapter_editor.py:604-625`（manifest 里保存 `annotations`、`draft`）、`668-743`（`restore_trash` 只提交正文、合并旧版本、写回执）
**机制**：`delete_chapter` 把批注整章导出到 `manifest["annotations"]` 后调用 `annotations.delete_chapter()` 删除数据库行；草稿整行放进 `manifest["draft"]` 后 `wb.delete_draft()`。`restore_trash` 只用 `manifest` 的正文、`index_entry`、`receipt`，没有重新插入 annotations/hunks/patch_ledger/preview_index，也不重建 draft。
**影响**：删除后“恢复”只恢复正文与版本；作者未提交的草稿、未处理的批注从 UI 消失（数据仍在回收站 manifest，`list_trash` 会带出，但没有恢复 API）。若后续清理回收站，则彻底丢失。
**最小修复**：`restore_trash` 在同一事务里把 `manifest["annotations"]` 重新写入 `annotations`/`annotation_hunks`（保留 chapter_uid 映射），并把 `manifest["draft"]` 通过 `wb.save_draft`/直接插入恢复；或明确产品语义，在 UI 标记“批注/草稿不会恢复”并提供导出。
**复现**：

```bash
... python3 -B -X utf8 s16_restore_incomplete.py
```

```text
annotation: ann_cca3b74d | summary: {'open_count': 1, ...}
manifest has annotations: 1 | draft content kept: True
restored: restored | annotations after restore: {'open_count': 0, ...} | draft after restore: None
```

---

### P2-12 符号链接的存储目录未被拒绝，写入可落到项目外

**位置**：`chapter_versions.py:102-103`（`store_root`）、`123-127`（`_ensure` 直接 `mkdir`）；`outline_editor.py:109-117`（`_safe_outline_path` 用 `base.resolve()` 后只比较 `path.parent == base`）、`606-615`（`_safe_lore_path` 同类）
**机制**：若项目内 `大纲`、`设定` 或 `.webnovel/chapter_versions` 已是指向项目外的符号链接：
- `_outline_dir(project).resolve()` 解析到项目外，`path.parent == base` 成立，`write_file/write_lore` 正常写入外部目录；
- `chapter_versions._ensure()` 不检查链接，`objects/index.json/commits` 全部写到外部。

`transaction_journal.assert_within` 会拒绝链接；`memory_library._path`/`invalidation._path` 会拒绝 `.webnovel` 链接；但这两个核心写模块没有同等校验。

**影响**：项目目录被同步工具/手工构造/恶意解压成链接时，版本与大纲数据写到项目外；备份按 `_copy_tree` 跳过链接，会漏掉这些数据；属于路径安全防御缺口（API 本身不创建链接，需要本地或被污染的项目目录作为前置）。
**最小修复**：在 `store_root`/`_outline_dir`/`_lore_dir` 解析后校验 `resolved` 仍在项目内，且逐段 `lstat` 无符号链接（复用 `transaction_journal.assert_within` 或等价实现）；`_ensure` 在创建前拒绝链接的 `.webnovel`/`chapter_versions`。
**复现**：

```bash
... python3 -B -X utf8 s14_symlink.py
```

```text
commit state: committed | objects outside: True | index outside: True | index reads: 1
outline write: saved | outside content updated: True
```

---

### P2-13 `studio.polish_existing` 回写未带 `expected_sha256`，润色窗口内的保存被静默覆盖

**位置**：`studio.py:488-556`，比对 `529`，备份 `531-532`，提交 `536-539`
**机制**：`polish_existing` 在模型返回后做一次 `source.read_bytes()!=old` 检查（529），随后写备份文件、读回执，再调用 `versions.commit_raw_bytes(...)`；提交没有传 `expected_sha256=base_sha`。`commit_raw_bytes` 会以“提交时磁盘当前 sha”作为 `previous_sha256` 并直接覆盖，所以检查之后、提交之前落盘的正常保存不会被发现。`polish_existing` 持有 `writer_runner.file_lock(writer.lock)`，但 `chapter_editor.save_version` 不取该锁，二者可并发。
**影响**：作者在润色回写窗口内保存的新正文被润色稿覆盖；保存 API 已返回 `saved`，版本历史里也留下 `author_edit` 版本，但 `current` 被 `studio_polish` 覆盖，且润色稿基于旧正文生成。`commit_raw_bytes` 的 `parent=current_sha` 还会把润色版本记成“新保存的子版本”，来源关系误导。
**最小修复**：调用 `commit_raw_bytes` 时传 `expected_sha256=base_sha`（即 `old` 的 sha）；冲突时返回 409 并保留备份；或让 `polish_existing` 与 `save_version` 使用同一章锁。
**复现**（模型/执行器用桩，写路径为真实代码）：

```bash
... python3 -B -X utf8 s22_polish_race.py
```

```text
polish: polished
racing save said: saved 3241d4f6ac94
disk now: '润色后的正文\n'
racing save content lost: True
versions: [('legacy-adopted', ...), ('author_edit', ...), ('studio_polish', ...)]
```

---

### P2-14 `_drop_receipt` 读改写不带 `receipts.lock`，覆盖并发 `author_confirm` 的回执

**位置**：`chapter_editor.py:566-570`（`_drop_receipt` 直接 `atomic_json`）；对照 `152-160`（`_write_receipts` 持 `receipts.lock` 并重新读最新）
**机制**：`_drop_receipt` 先 `_read_receipts`，pop 本章，再 `safety.atomic_json` 整表覆盖，全程不取 `receipts.lock`。并发 `author_confirm`（持锁、读最新、合并写回）若在 `_drop_receipt` 读取之后、写回之前完成，其回执会被旧表覆盖。
**影响**：删除章节 A 的同时确认章节 B，B 的确认回执（`review.note`、确认时间、`confirmed_version_id`）可能被恢复成旧值，确认状态丢失但 API 已返回成功；发布门禁会因此把已确认章节判为未确认/过期。
**最小修复**：`_drop_receipt` 复用 `_write_receipts` 的锁与“读最新-合并-写”模式，或提供 `_update_receipts(project, mutate)` 统一入口。
**复现**：

```bash
... python3 -B -X utf8 s23_receipt_lost_update.py
```

```text
receipts before: ['1', '2']
receipts after: ['1']
chapter1 note after:  | concurrent confirm lost: True
```

---

## 3. 复测通过项（旧修复回归 / 关键不变量）

本轮没有因为“测试绿”就直接认定修复：除跑现有测试外，用 `s18_retests.py` 对路径/事务/幂等/草稿/重复章等关键不变量做了独立探针。

### 3.1 现有测试基线

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 -m unittest \
  integration.test_workbench_db integration.test_transaction_journal \
  integration.test_chapter_versions integration.test_chapter_editor \
  integration.test_outline_editor integration.test_invalidation \
  integration.test_revision integration.test_version_identity \
  integration.test_v08_crash_restore integration.test_history
```

```text
Ran 149 tests in 7.781s
OK (skipped=1)
```

```bash
ADVERSARIAL_STRICT=1 ... python3 -m unittest \
  integration.test_chapter_editor_adversarial \
  integration.test_outline_editor_adversarial \
  integration.test_workbench_db_adversarial
```

```text
Ran 82 tests in 11.697s
OK
```

```bash
... python3 -m unittest integration.test_publication_safety \
  integration.test_history integration.test_memory_facts \
  integration.test_workflow integration.test_pipeline_fixes
```

```text
Ran 86 tests in 1.547s
OK
```

**覆盖缺口**：`test_split_failure_leaves_no_orphan_chapter` 只断言“没有孤儿章/索引章一致”，不检查残留 `commits/split-*-b.json` 与重试；`test_transient_failure_does_not_poison_idempotency_key` 只覆盖 `_locked` 内失败，不覆盖 `_finish` 在锁外失败；`test_symlink_in_outline_directory_is_rejected` 只覆盖文件链接，不覆盖目录链接；`test_publication_safety` 不覆盖“提交后副作用失败”的恢复。

### 3.2 独立探针（`s18_retests.py`）

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 s18_retests.py
```

```text
journal ../ path => UnsafePath path_traversal
journal absolute => UnsafePath absolute_path
journal symlink write => TransactionConflict unsafe_path (symlink)
  outside untouched: True
zip-slip inspect => valid: False | problems: ['unsafe:path_traversal']
zip-slip restore => UnsafePath path_traversal
draft stale replay => DraftConflict draft_conflict
idempotency mismatch => mismatch
duplicate chapter => VersionConflict duplicate_chapter_files
```

结论：以下旧关注点在本 HEAD 仍被正确拦截，本轮未发现回归——
- `transaction_journal` 的 `..`/绝对路径/符号链接/zip-slip 拒绝；
- `workbench_db` 的 draft ABA、revision 过期重放、幂等参数不匹配；
- `chapter_versions` 的重复章号/大小写冲突检测；
- `publication_safety` 的作者确认五项绑定、`human_approved` 正文摘要绑定、receipt 的 `file_sha256` 校验（测试层面）。

### 3.3 按模块的结论与未发现项

| 模块 | 本轮结论 |
|---|---|
| `workbench_db.py` | 未发现新的 P0/P1。WAL/busy retry、`BEGIN IMMEDIATE`、draft epoch、idempotency 参数哈希、FTS 重建在测试与探针中正常。设计观察：`connect(readonly=True)` 仍会创建 `.webnovel` 目录/DB 文件；`idempotency_begin` 允许 600 秒后接管仍在运行的 `in_progress`（可能重复执行），本轮未构造出实际双执行。 |
| `transaction_journal.py` | 路径/zip/恢复校验通过；P2-7 为备份一致性缺口。`prepare/apply/recover` 未在 Manager API 暴露，主要影响测试与 CLI。`restore_backup` 对“备份中不存在的现有文件”不做删除（叠加式恢复），属文档需明示的行为，未计入。 |
| `chapter_versions.py` | P1-1/P1-3、P2-2/P2-3/P2-6/P2-12；提交状态机在“正常崩溃+未人工回退”路径可恢复，但 conflict/raw/标题边界有缺口。 |
| `version_history.py` | 主要问题集中在 `restore` 对 `chapter_versions.restore_version` 的调用（P2-2/P2-3）；`best` 只读推荐，未发现写入门禁绕过。 |
| `chapter_editor.py` | P1-2/P1-4、P2-1/P2-5/P2-10/P2-11/P2-14；`save_version` 的预期版本/正文双校验、改名预检、草稿清理在正常路径正确。 |
| `outline_editor.py` | P2-4/P2-12；`write_file` 的 revision、缺失章确认、墓碑、双轨重建在测试中正常。 |
| `invalidation.py` | P2-8；日志/记忆锁顺序（invalidation→memory）未发现死锁。 |
| `publication_safety.py` | 未发现新的可复现 P0/P1/P2；作者确认/质量通过/人工批准/e_decides 四条门禁与正文、版本、标题、合同哈希绑定在测试中成立。 |
| `memory_library.py` | 未发现新的 P0/P1/P2；`save_item`/`correct` 的 revision 乐观锁、`sync_chapter` 提取前/写入前双重正文校验正常。 |
| `studio.py` | P2-13；`batch`/`plan` 的主写路径均持 `writer.lock`，但 `save_version` 不参与该锁，跨模块并发仍是系统性风险。 |

---

## 4. 修复优先级建议

1. **先修 P1-1/P1-3**：给 `recover_pending` 加逐记录隔离、跳过 `conflict`、缺失 candidate 标 conflict；这是恢复/常驻服务的基础。
2. **再修 P1-2/P1-4**：统一 split/merge/delete/restore 与 `save_version` 的章锁与锁顺序；回滚必须先比较当前 sha，禁止整份索引快照覆盖。
3. **P2-5/P2-6**：回滚清理 commit 记录；文件名字节校验；`recover_pending` 对 OSError 隔离。
4. **P2-1/P2-9/P2-10**：统一“提交成功后的响应恢复”与 op_id 幂等语义，避免“实际成功、API 报失败”。
5. **P2-3/P2-11**：恢复路径补齐回执 destination、批注、草稿。
6. **P2-4**：升级迁移先保留 `story_plan.json` 的 legacy chapters，再重建。
7. **P2-7/P2-12/P2-13/P2-14**：备份锁、目录链接校验、润色 expected_sha、回执锁。

---

## 5. 复现环境与脚本清单

- 仓库：`/home/ubuntu/.hermes/cache/scratch/audit-v2-head`（只读；未写入任何仓库文件）
- Python：`/home/ubuntu/venvs/dsh/bin/python3` 3.12.3
- 所有脚本：`/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01/`
  - `s1_split_rollback.py`、`s7b_split_clobber_natural.py`（P1-2/P2-5）
  - `s2_recover_keyerror.py`（P1-1）
  - `s3_legacy_outline.py`（P2-4）
  - `s4_idem_gap.py`（P2-1）
  - `s5_delete_race.py`、`s17_delete_lock.py`、`s20_delete_queue.py`（P1-4）
  - `s6_restore_title.py`、`s12_restore_receipt.py`（P2-2/P2-3）
  - `s8_title_len.py`（P2-6）
  - `s10_backup_race.py`（P2-7）
  - `s11_invalidation.py`（P2-8）
  - `s13_merge_retry.py`（P2-5）
  - `s14_symlink.py`（P2-12）
  - `s15_conflict_resume.py`、`s15b_conflict_natural.py`（P1-3）
  - `s16_restore_incomplete.py`（P2-11）
  - `s19_preview_accept.py`（P2-9）
  - `s21_outline_retry.py`、`s9_new_chapter_retry.py`（P2-10）
  - `s22_polish_race.py`（P2-13）
  - `s23_receipt_lost_update.py`（P2-14）
  - `s18_retests.py`（旧关注点复测）
  - `results.txt`（上述脚本的汇总输出）

通用运行前缀：

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-a-01
PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
PYTHONPATH=/home/ubuntu/.hermes/cache/scratch/audit-v2-head/backend \
python3 -B -X utf8 <脚本名>
```

---

## 6. 备注与边界

- 本报告没有引用 `docs/audits` 旧结论；`ADVERSARIAL_STRICT=1` 只作为“旧缺陷回归”的测试基线，且每条新发现均由独立脚本复现。
- 未做真实断电/Windows 共享冲突测试；P2-7、P2-12 与部分 `OSError` 场景依赖文件系统/并发时序，报告已明确前置条件。
- `transaction_journal.prepare/apply/recover` 未接入 Manager API，相关缺陷影响面按测试/CLI 计；`backup/restore` 是暴露面。
- P1-2、P1-4、P2-13 的复现使用“在真实写路径中插入并发/失败钩子”的方式模拟两个窗口/瞬时 I/O 错误；钩子不改变被测函数的逻辑与断言对象。
