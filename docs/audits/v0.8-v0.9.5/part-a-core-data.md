# v0.8–v0.9.5 数据完整性 / 版本 / 事务 / 编辑写入门禁审计（Part A：核心数据）

## 0. 审计基线与方法

- 仓库：`/home/ubuntu/projects/dsh-chapter-whale`
- 分支：`feat/v0.8-v0.9.5`
- 审计基线：`HEAD = fe2bc32`（`git rev-parse HEAD` 输出 `fe2bc3272194bb818a4caaf517e67cb6bc0f34d1`）。
- 工作树状态：审计开始时 `git status --short` 为空；审计过程中工作树出现了**其他进程的未提交修改**（`agent_hub.py`、`chapter_editor.py`、`chapter_versions.py`、`world_state.py`、`api_v085.py`，其中 `chapter_versions.py` 已包含一个 `_require_id` 修补）。本报告的所有行号、读取和复现均基于 `git archive HEAD` 导出的干净快照 `/home/ubuntu/.hermes/cache/scratch/audit-v095/head`，**不包含工作树上的未提交改动**。我没有修改仓库任何文件，也没有执行 `git commit/push`。
- 审计范围：逐文件通读 `workbench_db.py`、`transaction_journal.py`、`chapter_versions.py`、`version_history.py`、`chapter_editor.py`、`outline_editor.py`、`invalidation.py`、`publication_safety.py`、`memory_library.py`、`studio.py`，并对照 `test_workbench_db*.py`、`test_chapter_versions.py`、`test_version_identity.py`、`test_transaction_journal.py`、`test_chapter_editor*.py`、`test_v08_crash_restore.py`、`test_invalidation.py` 及 manager API 调用方。
- 现有回归基线（干净快照）：

```text
$ PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 -m unittest \
    integration.test_workbench_db integration.test_chapter_versions \
    integration.test_version_identity integration.test_transaction_journal \
    integration.test_chapter_editor integration.test_chapter_editor_adversarial \
    integration.test_v08_crash_restore integration.test_invalidation
Ran 144 tests in 10.733s
OK (skipped=1)
```

- 证据等级：每条发现均给出实际执行过的命令/关键输出；无法在单机安全复现的边界问题明确标注 `静态假设`，并按规则降级。所有探测脚本位于 `/home/ubuntu/.hermes/cache/scratch/audit-v095/`，只在临时目录中运行，不写仓库。

## 1. 严重度计数

| 级别 | 数量 | 定义 |
| --- | ---: | --- |
| P0 | 1 | 任意路径写入 / 数据破坏或不可恢复状态 |
| P1 | 10 | 可复现的数据丢失、静默假成功、崩溃恢复错误、版本门禁绕过 |
| P2 | 15 | 边界/兼容/并发破坏或备份一致性缺口 |
| P3 | 10 | 卫生、防御纵深、性能或低频边界 |
| **合计** | **36** | |

---

## 2. P0

### P0-1 `op_id` 路径穿越：可从 API 在作品目录之外任意创建 JSON 文件，并可持久化阻断保存

**位置**
- `backend/integration/chapter_versions.py:381-382`（`_commit_path` 直接把 `op_id` 拼进 `commits/{op_id}.json`）
- `backend/integration/chapter_versions.py:748-752`（`commit_raw_bytes` 用该路径做存在性读取/写入）
- `backend/integration/version_history.py:205-217`（`restore` 原样透传 `op_id`）
- `backend/integration/chapter_editor.py:656-702`（`restore_trash` 原样透传 `op_id`）
- `backend/manager/app.py:768-771`（`RestoreInput.op_id` 无格式约束）
- `backend/manager/api_v08.py:151-155`（trash restore 直接取 body 的 `op_id`）

**机制**
`op_id` 来自 HTTP 请求，`restore` / `restore_trash` 没有像 `save_version` 那样调用 `_validate_op_id`。`_commit_path` 使用 `Path(commits) / f"{op_id}.json"`：`..` 可逃出 `commits`，绝对路径会直接替换整个路径。`writer.atomic_json` / `publication_safety.atomic_json` 会 `mkdir(parents=True)`，因此不存在的父目录也会被创建。已存在的合法 JSON 会被 `_load_commit` 的“像 commit 记录”检查偶然拦住（否则抛 `operation_id_reused`），但**不存在的路径可以任意创建**；若在 `.webnovel/writer_receipts.json` 不存在时把 `op_id` 指到该位置，会把 commit 记录写成回执文件，之后所有保存都因 `receipts_corrupt` 永久 409。

**影响**
- 作品目录之外任意新建 `.json` 文件（路径完全由请求控制，包含绝对路径）。
- 可创建 `.webnovel/writer_receipts.json`、`story_plan_meta.json`、`creative_brief.json` 等“缺失时才写入”的状态文件，造成持久化 409/500 或元数据损坏。
- 这是 API 可达的写入原语，不是本地脚本问题。

**复现/证据**

```text
$ AUDIT_BACKEND=/home/ubuntu/.hermes/cache/scratch/audit-v095/head/backend \
  PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
  python3 -B -X utf8 /home/ubuntu/.hermes/cache/scratch/audit-v095/probe_p0.py
relative escape target: /home/ubuntu/.hermes/cache/scratch/tmpo44jg8tk/pwn-out.json exists: True
escaped record state: committed op_id: ../../../../pwn-out
absolute op_id target exists: True path: .../outside/pwn.json
absolute restore status: restored
receipts exists before: False
receipts exists after: True
subsequent save blocked: ChapterError receipts_corrupt receipts_corrupt
```

`probe_p0.py` 通过 `version_history.restore(project, 1, <合法 ver_id>, op_id="../../../../pwn-out")` 写入作品外文件；绝对路径同样成功；第三个项目用 `op_id="../../writer_receipts"` 生成伪回执后，下一次 `save_version` 被 `receipts_corrupt` 拒绝。

**最小修复**
在 `chapter_versions.py` 内部统一做标识符校验（不能只依赖 `chapter_editor`）：`_commit_path`、`save_candidate`、`read_candidate`、`read_object` 只接受 `[A-Za-z0-9][A-Za-z0-9._-]{0,119}` 且拒绝 `.`/`..`/分隔符/绝对路径；`restore` 与 `restore_trash` 入口也调用同一校验。更稳妥的是 op id 只作为记录字段保存，文件名使用 `uuid4().hex`。

---

## 3. P1

### P1-1 提交记录状态未校验：`prepared/chapter_written` 的重试被当成成功，接口返回 `saved` 但磁盘未变

**位置**
- `backend/integration/chapter_versions.py:445-449`（`commit_candidate`）
- `backend/integration/chapter_versions.py:748-752`（`commit_raw_bytes`）
- `backend/integration/chapter_editor.py:455-463`（无条件设置 `result["status"]="saved"`）

**机制**
两处都只比较 `existing["chapter_id"]` 与 `existing["content_sha256"]`，不检查 `existing["state"]=="committed"`。第一次提交若在 `prepared`（对象/正文/索引尚未写）或 `chapter_written` 阶段失败，记录会留在磁盘；客户端用同一 `op_id` 重试时，`_load_commit` 命中记录并**直接返回**，不会补写正文或索引。`save_version` 随后把任何 `result` 标成 `saved`。

**影响**
用户看到 `status: saved` 和新的 `content_sha256`，但磁盘仍是旧正文，`index.json` 仍是旧版本；若用户关闭编辑器，未落盘内容只残留在 candidate JSON 中，属于静默未保存。还会让后续“同内容保存”走 `unchanged` 分支，永远不修复索引。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_retry_prepared.py
first attempt raised: OSError simulated crash before object write
commit record after failure: state='prepared' done=[]
retry response: status='saved' state='prepared' content_sha=8291179e5113 reused=None
disk after retry: 旧正文
index current: 145cb87398f7 version_id: ver_0001_cfe6efa8
commit record after retry: state='prepared' done=[]
```

第一次用 monkeypatch 让 `_store_object` 抛 `OSError`（等价于对象写入前崩溃），第二次用同一 payload 重试；响应 `saved`、`state=prepared`，磁盘和索引都还是旧值。

**最小修复**
只有 `state=="committed"` 且目标正文 sha、索引 `current` 均匹配时才允许作为幂等结果返回；`prepared/chapter_written` 记录必须走 `recover_pending` 的补写路径或抛 `operation_incomplete`。`save_version` 在返回 `saved` 前复核 `versions.file_sha256(path) == result["content_sha256"]` 且索引 current 一致。

### P1-2 拆分在两个独立提交之间崩溃会永久丢掉后半章

**位置**
- `backend/integration/chapter_editor.py:742-789`（`split_chapter`）
- 特别是 `763-775` 的两次 `commit_raw_bytes`，以及 `776-789` 只在 Python 异常路径回滚，未覆盖进程崩溃

**机制**
`split_chapter` 先把原章写成前半章（`commit_raw_bytes`），再写新章（后半章）。原字节 `old_bytes` 和索引备份只在当前进程内存中；`except Exception` 不会捕获 `SystemExit`/`os._exit`/断电。崩溃发生在两次提交之间时：前半章已落盘且索引已更新，后半章不存在，`recover_pending()` 对已完成的第一个提交无动作，也没有 journal/垃圾箱副本。

**影响**
原文后半部分从正文目录、`index.json`、`objects/` 全部消失（如果该章此前没有版本对象），属于不可恢复的作者正文丢失；重试也不能恢复，因为章节已变成非尾章或文件名已变。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_split_crash.py
split aborted with: SystemExit simulated process death between the two commits
chapter5 bytes: '上半部分需要保留。\n\n'
chapter6 exists: False
map: [5]
index chapters: ['5']
old full sha in objects: False
tail text still anywhere on disk: False
recover_pending: []
chapter5 after recovery: '上半部分需要保留。\n\n'
```

**最小修复**
拆分前把完整原文进入回收站/`originals` 或版本对象，并使用 `transaction_journal` 的多步事务（至少保证“后半章已写”先于“前半章截断”）；启动恢复必须能根据 tx 记录补齐或回滚。仅在异常时回滚内存快照不足以覆盖崩溃。

### P1-3 导入失败回滚不清理 commit 标记；同 `op_id` 重试报告成功但缺章

**位置**
- `backend/integration/chapter_editor.py:848-881`（`import_chapters`）
- `869-881` 的回滚只删除正文文件/索引/回执，不删除 `commits/*.json`
- `chapter_versions.py:748-752` 的既有提交命中逻辑

**机制**
导入第 2 章成功、第 3 章失败时，回滚删除第 2 章正文与索引，但保留第 2 章 `commits/<op>-2.json`（`state=committed`）。客户端用同一 `op_id` 重试时，第 2 章命中该记录直接返回，不会重建正文或索引；第 3 章正常写入。最终响应 `count=2`，章节列表包含 `[2,3]`，但磁盘只有第 3 章。

**影响**
导入接口报告成功且返回两章，实际丢失第 2 章；用户无法从 UI 发现缺章。第 2 章内容只可能在 `objects/` 里（若对象已写），但没有索引条目，属于不可恢复的“幽灵章节”。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_import_retry.py
first import raised: OSError simulated failure before third chapter write
after failure map: [1]
chapter2 file after rollback: None
chapter2 commit record exists: True
retry result count: 2 chapters: [2, 3]
after retry map: [1, 3]
chapter2 file after retry: None
chapter2 versions after retry: 0
chapter3 text: 乙内容
```

**最小修复**
回滚必须同时删除/失效对应 commit 标记和 candidate 状态（或给每次导入 attempt 独立的命名空间）；重试遇到既有记录时，必须校验正文文件与索引实际存在且匹配，否则补写而不是直接返回。更彻底的做法是把整批导入包成一个 journal 事务。

### P1-4 正文已写、索引未写的崩溃没有 workbench 恢复路径；同内容重试被判 `unchanged`，索引永久陈旧

**位置**
- `backend/integration/chapter_versions.py:731-789`（`commit_raw_bytes` 中先写正文 `773`，再写索引 `783`）
- `backend/integration/chapter_editor.py:450-453`（`unchanged` 分支只返回旧版本，不修复索引）
- `backend/integration/chapter_versions.py:524`（`recover_pending`）
- `backend/integration/resident_service.py:489-503`（唯一生产调用者，只遍历 scheduler jobs 的项目）

**机制**
`commit_raw_bytes` 的提交标记在正文写完后才推进索引；进程在两者之间被杀时，磁盘正文是新内容，`index.json` 仍是旧 current。workbench 项目如果没有 scheduler job，不会被 `resident_service._recover_pending` 扫描。用户重新打开后 `chapter_state` 返回旧 `version_id` + 新 `sha256`；由于正文文本与编辑器内容相同，`save_version` 走 `unchanged` 分支，不重建索引。

**影响**
版本历史、`current_version_id`、`report_ref`、`author_confirm` 都指向旧版本，磁盘却是新正文；后续依赖“当前版本”的发布/审查会持续 `stale`。只有手工调用 `recover_pending` 才能修复。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_commit_crash.py
save aborted: SystemExit simulated power loss before index update
disk: '崩溃前已写正文\n'
chapter_state version_id: ver_0001_fdbbd401 sha: 99a8df134dd0
index current: 145cb87398f7
index current == disk: False
retry status: unchanged unchanged: True
index still stale: True
manual recover_pending: [{'op_id': 'crash-save', 'chapter_id': 1, 'state': 'committed'}]
index after manual recover == disk: True
```

**最小修复**
在打开项目/保存前执行 `chapter_versions.recover_pending`（不能只依赖 scheduler）；`save_version` 发现磁盘 sha 与索引 current 不一致时，先修复索引/登记版本，再判断 `unchanged`。长期应把正文与索引放进同一个 `transaction_journal` 事务。

### P1-5 删除/恢复用整份 `index.json` 读改写且不持有版本锁，并发保存的版本条目会丢失

**位置**
- `backend/integration/chapter_editor.py:547-551`（`_drop_index_entry`）
- `backend/integration/chapter_editor.py:554-558`（`_drop_receipt`）
- `backend/integration/chapter_editor.py:708-715`（`restore_trash` 合并旧版本后整份写回）

**机制**
删除/恢复先 `load_index`，再 `_save_index`，但既不持有 `chapter_versions` 的 `.lock`，也不持章节锁。另一个进程在此期间完成保存并写入了新版本，删除方随后用过期的内存索引覆盖磁盘索引，丢掉新版本条目；正文文件却已更新。

**影响**
`index.json` 的 `current` 与磁盘 sha 不一致，最新正文没有版本记录；版本历史、恢复、审查绑定和发布校验全部基于错误版本。属于可复现的版本元数据丢失。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_index_race.py
versions before: 1
deleter paused after loading index
concurrent save status: saved sha: 4a6594defad9
delete result: deleted
index chapter1 versions after race: 1
index current: f3e05d1df403 version_id: ver_0001_7ac24f33
disk sha: 4a6594defad9 text: '并发保存的新正文\n'
index current == disk: False
saved version present in index: False
```

**最小修复**
所有索引/回执的读改写统一放到 `file_lock(paths["lock"])`（或专用的 `index.lock` / `receipts.lock`）内，使用“读取-修改-原子写”不可分割的 helper；删除/恢复不能基于锁外快照写整表。回执同理。

### P1-6 `invalidate()` 无项目锁；并发失效会丢日志和待复核标记，且绕过 memory.lock

**位置**
- `backend/integration/invalidation.py:117-145`（读取 log、追加、整份写回）
- `backend/integration/invalidation.py:84-114`（`_mark_facts` 直接读写 shared_memory.json）
- `backend/integration/memory_library.py:209-212`（正常作者编辑会持 `memory.lock`）

**机制**
`invalidate` 先 `read_log`，在 `_mark_facts` 中再 `memory_library.read`，最后分别 `writer.atomic_json` 写回；全过程没有项目级锁。两个章节并发保存时，双方读到同一个 `revision`，后写者覆盖前者；`_mark_facts` 也不持有 `memory.lock`，与作者 `save_item` 并发时同样会覆盖整份记忆文件。

**影响**
一次失效记录可能完全消失，受影响事实不会被标 `needs_review`，后续生成会把已变更章节的旧事实当作有效证据。日志中还可能出现“标记了 marked 但实际未标记”的不一致，`op_id` 重放会直接 `reused` 而不再补标。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_invalidation_race.py
errors: {}
revision: 1
entry count: 1
entry op_ids: ['op-1']
entry chapters: [[1]]
```

两个线程分别对第 1、2 章调用 `invalidate`，人为在 `affected_facts` 同步；最终只有 `op-1` 一条记录，`op-2` 丢失。

**最小修复**
为 `invalidation_log.json` 增加项目级锁（可与 `writer.lock` 或独立的 `invalidation.lock` 统一），并让 `_mark_facts` 通过 `memory_library` 的加锁修改 API 写入；日志增加 `state=completed`，重放未完成项时补做标记/重建，而不是直接 `reused`。

### P1-7 `merge_tail` 非原子：合并写入成功、删除尾章失败时正文重复且无法重试

**位置**
- `backend/integration/chapter_editor.py:796-819`
- `811-814` 先写合并后的前一章，`815-817` 再删除尾章

**机制**
两步都是独立提交；删除失败（磁盘满、文件占用、并发发布检查）或进程崩溃后，前一章已经包含尾章全文，尾章仍然存在。用同一 `op_id` 重试时，`write_chapter` 的 candidate 记录已存在但内容不同，抛 `candidate_id_reused`，无法自动恢复；不带 op id 重试则会把尾章再拼一次。

**影响**
正文出现重复段落，版本历史中留下一个“合并但未删除”的中间状态；作者只能手工删尾章/恢复版本。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_merge_fail.py
merge raised: OSError simulated delete failure after merge write
map after failed merge: [1, 2, 3]
chapter2: '第2章正文。\n\n第3章正文。\n'
chapter3: '第3章正文。\n'
retry failed: VersionConflict candidate_id_reused
```

**最小修复**
把 merge 变成一个 journal 事务或至少先归档/删除尾章再合并，并在异常时把前一章恢复到旧版本；为 merge 使用独立的幂等键和可恢复状态机，不能依赖已存在的 candidate 记录。

### P1-8 并发 `new_chapter` 对同一章号都返回 created，后者静默覆盖前者

**位置**
- `backend/integration/chapter_editor.py:519-529`
- `backend/integration/chapter_versions.py:748-758`（`allow_new=True` 时只在 `current_sha is None` 下拒绝，已有正文不拒绝）

**机制**
`new_chapter` 在锁外 `chapter_map` 检查“章号不存在”，然后 `commit_raw_bytes(... allow_new=True)`。两个并发请求都通过检查后，`commit_raw_bytes` 的 `.lock` 只序列化写入，不校验“应该不存在”；第二次看到已有正文仍会写入，并登记第二个版本。文件名保持第一次的标题，版本元数据却是第二次的标题。

**影响**
两个调用者都收到 `created`，但其中一个正文被覆盖；文件名为甲、版本 current 标题为乙，`chapter_state` 的标题/版本指纹分裂，`author_confirm` 可能失败。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_new_race.py
results: {'甲': ('created', '甲', 'ver_0001_...'), '乙': ('created', '乙', 'ver_0002_...')}
map: [1]
final file: 第1章-甲.md '乙的内容\n'
version count: 2 titles: ['甲', '乙']
current version title: 乙
both caller content present in objects: True
```

**最小修复**
章号生成与“章号不存在”校验放入同一章节锁/数据库事务；`commit_raw_bytes` 增加 `expected_absent` 前置条件（当前文件存在则 `chapter_exists`），不能只靠 `allow_new`。`new_chapter` 还应使用幂等键。

### P1-9 64 位 sha 版本选择器不校验章节归属，可把第 1 章正文恢复进第 2 章

**位置**
- `backend/integration/chapter_versions.py:719-728`（`_resolve_version`：任何 64hex 都接受）
- `backend/integration/chapter_versions.py:615-635`（`read_version` 用该 sha 读对象）
- `backend/integration/chapter_versions.py:801-826`（`restore_version` 用该对象写当前章）

**机制**
`_resolve_version` 只在本章版本列表中查找 `ver_...`/sha；查不到时，只要选择器匹配 `[0-9a-f]{64}` 就原样返回 `(None, selector)`。`read_version` 会读取该对象，`restore_version` 会把该对象写入任意 `chapter`。对象的 sha 是内容哈希，不携带章节归属。

**影响**
API 允许把第 1 章的正文读成第 2 章版本，甚至覆盖第 2 章正文；虽然旧版本会保留，但属于跨章内容破坏，且报告/回执会按第 2 章绑定错误内容。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_cross_chapter.py
chapter1 sha: b91a29e97ba8
chapter2 before: 乙章正文
history.read(chapter=2, chapter1_sha) body: 甲章正文 version_uid: None
history.restore(chapter=2, chapter1_sha) status: restored
chapter2 after: 甲章正文
chapter2 current sha == chapter1 sha: True
```

**最小修复**
仅在 64hex 命中本章 `versions`、本章 `unattributed`（或显式 `allow_foreign_version=True` 的迁移路径）时才接受；否则 `VersionNotFound`。`read_version` 与 `restore_version` 共用这一归属校验。

### P1-10 `studio.polish_existing` 直接写正文，绕过版本索引、章节锁和幂等门禁

**位置**
- `backend/integration/studio.py:487-551`
- 关键写入 `540`：`bridge._write_text_atomic(source, rewritten)`；`545-546` 直接写 receipts
- 对照 `backend/integration/chapter_editor.py:163-168` 的章节锁与 `chapter_versions.write_chapter` 的版本提交

**机制**
`polish_existing` 只持 `writer.lock`，不持 `locks/chapter-N.lock`，也不调用 `chapter_versions.commit_raw_bytes`/`save_version`。它把润色后的正文原子替换到 `正文`，但 `index.json` 仍记录旧 sha/旧版本；`chapter_state` 返回旧 `version_id` + 新 `sha256`。同时 `save_version` 不获取 `writer.lock`，所以两条写路径没有共同互斥锁；在 `polish` 的“最终复核”和 `bridge._write_text_atomic` 之间，workbench 保存可以插入，存在丢失更新窗口。

**影响**
润色成功的正文没有版本记录，历史/报告/发布校验基于旧版本；并发 workbench 保存与润色互相覆盖（后写者赢），且没有共同审计链。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_polish_bypass.py
polish status: polished
disk: '润色后的正文\n'
index current: 9f3e50e7a1b2 version_id: ver_0001_0bea4990
index current == disk: False
versions: [('ver_0001_0bea4990', '9f3e50e7a1b2')]
chapter_state version_id: ver_0001_0bea4990 sha: 462df341b849
```

（`revision_workflow.revise` 被替换为固定返回，仅用于把 `polish_existing` 的写盘路径跑到真实代码；索引陈旧是实际结果。）

**最小修复**
把 `studio.polish_existing` 的正文写回改为调用 `chapter_versions.commit_raw_bytes`（并放在章节锁/幂等键内），或让所有正文写入统一走 `chapter_editor.save_version` 的内部写门面；润色回执应在版本提交成功后写入。

---

## 4. P2

### P2-1 `transaction_journal` 的事务/恢复层未接入正文写路径；`conflict` 状态对读取门禁不可见

**位置**
- `backend/integration/transaction_journal.py:844-874`（`pending` 只列 `prepared/applying`；`assert_readable` 只看 `pending`）
- `backend/integration/transaction_journal.py:924-931`（`recover` 把失败事务标 `conflict`）
- 生产调用检索：`grep -rn "journal.prepare\|journal.apply\|journal.recover\|assert_readable" backend --include='*.py' | grep -v test_` 只返回定义；`chapter_editor.split/merge/import` 均未使用 journal。

**机制/影响**
事务记录一旦进入 `conflict`（例如第 1 步已应用、第 2 步暂存损坏），`pending()` 返回空，`assert_readable()` 不抛 `RecoveryInProgress`；读取者会看到半提交状态。与此同时，正文写入路径并未使用 `prepare/apply`，所以模块文档宣称的跨文件保护在生产中不存在，只有测试覆盖。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 - <<'PY' ... journal.prepare 两步，改坏 step_001.bin，apply + recover ...
apply raised: TransactionConflict staged_size_mismatch
partial disk A/B: True False
recover: [{'state':'conflict','done':[0],'action':'conflict','error':'staged_size_mismatch', ...}]
pending after conflict: []
assert_readable: PASSED (no 409)
```

**最小修复**
`assert_readable` 同时检测 `conflict` 记录并对读取返回 409；`pending()`/诊断可见 conflict；在项目打开与关键读取入口调用 `recover`。长期让章节写路径实际使用 journal，而不是仅保留模块。

### P2-2 `in_progress` 幂等键无租约/无 GC 调用，失败后永久 409

**位置**
- `backend/integration/chapter_editor.py:397-401`（先占 key，再 `chapter_uid`）
- `backend/integration/chapter_editor.py:465-493`（提交成功后的草稿清理/完成在锁外）
- `backend/integration/workbench_db.py:696-764`（`in_progress` 不检查过期时间；`idempotency_gc`）
- 生产调用检索：`idempotency_gc` 除定义外零调用。

**机制**
若在提交成功后、`idempotency_complete` 前发生异常/崩溃（草稿清理、索引、回执、响应），key 停在 `in_progress`。`idempotency_begin` 对 `in_progress` 永远返回 409，没有心跳/租约；24 小时 TTL 也不会生效，因为 `idempotency_gc` 从未被调用。

**影响**
同一 `op_id` 重试永久 `op_in_progress`；用户以为保存失败，实际可能已提交；数据库中的 `idempotency_keys` 只增不减。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_idem_stuck.py
first save raised: RuntimeError simulated failure after chapter commit
disk after failed response: '已提交但响应失败的新正文\n'
idempotency state: {'state': 'in_progress'}
retry blocked: ChapterError op_in_progress op_in_progress
```

**最小修复**
为 `in_progress` 增加 `lease_expires_at`/心跳；在维护任务/项目打开时调用 `idempotency_gc`；把 `save_version` 从 `_idempotent` 到 `_finish` 的全过程放入统一的 `try/except`，失败时 `idempotency_fail`，成功但响应失败时允许按提交记录重放。

### P2-3 `snapshot()` 会把 `current_version_id` 回退到首个同 sha 版本；历史把两个版本都标成 current

**位置**
- `backend/integration/chapter_versions.py:686-716`（循环第一个 `sha256 == sha` 的 meta 就设置 current）
- `backend/integration/version_history.py:106-119`（`current` 只比较 sha）

**机制**
标题-only 变更会产生两个不同 `version_id`、相同 `sha256` 的版本。`snapshot()` 不优先匹配当前 `current_version_id`，而是取 `versions` 列表里第一个同 sha 的旧版本，导致 current 身份回退；`history()` 又用 sha 判断，两个版本都显示 `current: true`。

**影响**
作者定稿/恢复后 `current_version` 的标题、`title_digest`、`version_fingerprint` 变成旧值；发布快照和审查绑定可能拒绝或绑定错误版本；UI 显示两个“当前版本”。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_snapshot_rewind.py
before snapshot: current uid: ver_0002_... title: 新标题 filename: 第1章-新标题.md
after snapshot: current uid: ver_0001_... title: 旧标题 filename: 第1章-新标题.md
history rows (uid,title,current): [('ver_0002_...','新标题',True), ('ver_0001_...','旧标题',True)]
```

**最小修复**
`snapshot()` 优先保留 `entry["current_version_id"]` 指向的 meta；仅在 current 不存在/不匹配时才按 sha 回退。`history()` 的 `current` 用 `version_id == current_version_id` 判断（sha 兼容只作为 fallback）。

### P2-4 回收站恢复丢失 `chapter_uid`、批注和草稿；删除后的章号会被新章复用同一 UID

**位置**
- `backend/integration/chapter_editor.py:601-606`（manifest 存 `chapter_uid`、draft、annotations）
- `backend/integration/chapter_editor.py:619-626`（删除 draft、annotations）
- `backend/integration/chapter_editor.py:699-706`（恢复时只 `UPDATE chapter_meta`，新章号行不存在则 0 行）
- `backend/integration/chapter_editor.py:561-636`（删除不清理/退役 `chapter_meta`）

**机制**
删除章 2 时 `chapter_meta(2)` 保留；新建章 2 时 `wb.chapter_uid` 返回旧 UID（身份被复用）。旧章恢复若因章号占用改名为 3，`UPDATE chapter_meta WHERE chapter_id=3` 没有行，既不创建 UID 也不保留旧 UID；`restore_trash` 只恢复正文、索引和回执，不恢复 annotations 与 draft。

**影响**
`chapter_uid` 永久身份契约失效；恢复后的章没有 DB UID，`wb.chapter_uid(3)` 会生成全新 UID；批注、hunk、草稿只留在 trash manifest 中，API 无法恢复，属于用户批注数据丢失。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_trash_identity.py
annotations before delete: {'open_count': 1, ...}
manifest chapter_uid: chuid_4e2aa923 annotations archived: 1
restored chapter: 3 renumbered: True response uid: chuid_4e2aa923
chapter_meta row for 3: None
annotations for 3 after restore: 0
old uid preserved: False | wb.chapter_uid(3) now: chuid_e9e2f5ee

$ ... 删除章2后新建章2 ...
deleted uid: chuid_84259186 new chapter2 uid: chuid_84259186 reused: True
```

**最小修复**
删除时把 `chapter_meta` 移到 retired 表或记录 tombstone，绝不让新章复用旧 UID；恢复时 `INSERT OR IGNORE` 创建/迁移 `chapter_meta` 行；从 manifest 恢复 annotations/hunks/draft（或明确标注“仅归档、不恢复”并提供导入接口）。

### P2-5 备份屏障只等 journal，不等章节写入；备份可同时包含旧正文和新索引，`inspect_backup` 仍判定有效

**位置**
- `backend/integration/transaction_journal.py:1141-1173`
- `1156` 的 `barrier` 只检查 `tx_*.json`；`1163-1173` 先复制 `正文`，再复制 `index.json`/objects
- `backend/integration/transaction_journal.py:1353-1394` 的 `verify` 只逐文件校验 sha/大小，不校验索引 current 与正文 sha 的对应关系

**机制**
`chapter_versions` 写入不使用 journal，`barrier` 看不到它。备份复制 `正文` 后、复制 `index.json` 前，章节提交可以完成；备份于是得到旧正文文件 + 新索引 + 新对象。manifest 的每个文件 sha 都正确，`inspect_backup` 返回 `valid=True`。

**影响**
恢复此类备份会得到 current 指向新版本、正文却是旧内容的项目；版本历史/发布/审查绑定错误，而且备份自检无法发现。备份“跨存储一致性”承诺未实现。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_backup_race.py
backup paused after copying 正文, before index
concurrent save done, disk: '备份期间的新正文\n'
backup body: '备份前旧正文\n'
backup index current sha: aaae685730df
backup index matches backup body: False
inspect valid: True
```

**最小修复**
备份屏障必须覆盖 `chapter_versions` 的写锁/章节锁，或在备份期间禁止所有正文提交；复制 index 与正文必须在同一读锁/同一业务时刻。manifest 增加 `index_current`、`chapter_sha` 交叉校验，`inspect_backup` 对不一致判 invalid。

### P2-6 多文件大纲墓碑可被“编辑陈旧副本”复活

**位置**
- `backend/integration/outline_editor.py:487-511`（`write_file` 只读取当前文件的旧 plan，生成/保留本文件 tombstone）
- `backend/integration/outline_editor.py:351-362`（`_merge_chapters` 只在全局 merge 时应用 tombstone）
- `backend/integration/outline_editor.py:490-498`（新行 rev 只参考本文件与“当前可见 chapters”，已被 tombstone 的章节不在 `chapters` 中）

**机制**
章节 1 在文件 A 被删除后，A 留下 tombstone rev 2；文件 B 仍含陈旧的章 1（rev 1）。对 B 做正常保存时，`chapters.get("1")` 因 tombstone 已不存在而为空，rev 只按 B 旧值 +1；保存一次或多次后 rev 超过 tombstone，`_merge_chapters` 的 `tomb_rev >= current_rev` 不再成立，章 1 复活。

**影响**
作者已删除的大纲章节重新出现在 `story_plan.json` 和规划上下文；后续 AI 生成可能写回已删除剧情。冲突列表还不报告 tombstone 竞争。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_tombstone.py
after setup: ['1', '9']
after delete via A: ['9']
after B edit #1: chapters=['9', '1'] source=AI规划-0002-0002.md rev=3 conflicts=[]
```

**最小修复**
`write_file` 必须加载全局 tombstone 表，任何新行 rev 必须大于该章最高 tombstone（或直接拒绝重新引入 tombstoned id，除非作者显式确认）；删除时把 tombstone 同步到所有仍含该章的文件，或让 tombstone 不依赖单个文件。

### P2-7 `load_meta()` 在读取路径无锁写默认 meta，可覆盖 `write_meta()` 刚写入的作者设定

**位置**
- `backend/integration/outline_editor.py:182-218`（meta 缺失时构建默认值并 `safety.atomic_json`）
- `backend/integration/outline_editor.py:572-600`（`write_meta` 在 outline 锁内写入）

**机制**
`load_meta` 是读函数，但 meta 文件缺失时会写默认 meta，且不持有 `outline.lock`。两个首次请求并发时，一个 reader 已读到“缺失”并在慢速写默认值，writer 在锁内写入作者总纲；reader 随后用默认值覆盖，作者总纲和 `meta_revision` 丢失。

**影响**
首次打开/写 meta 的竞争会静默丢失 `master_outline`/`volumes`/`character_arcs`/`foreshadowing`，且 revision 回退，后续 `expected_meta_revision` 冲突。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_meta_race.py
reader paused before writing default meta
write_meta returned; meta now: 作者总纲
final master_outline: '' meta_revision: 1
```

**最小修复**
读路径不写盘；迁移由 `ensure_meta()` 在 outline 锁内用 `O_EXCL` 创建，或 `load_meta` 缺失时只返回内存默认值；写入方负责原子创建。

### P2-8 大纲/设定 `revision` 可省略，外部编辑会被静默覆盖

**位置**
- `backend/integration/outline_editor.py:450-469`（只有 `if revision and revision != current_rev` 才拒绝）
- `backend/integration/outline_editor.py:638-648`（`write_lore` 同样可选）

**机制**
API 的 `revision` 是可选的。调用方不传（或传空）时，`write_file` 读取当前文件后用旧内容整份覆盖，外部编辑器的并发改动没有冲突检测；只有在传了 revision 时才是 If-Match。

**影响**
外部编辑器/另一客户端对大纲的修改被最后一次保存覆盖，违背“外部编辑冲突显式报告”的设计目标。

**复现/证据**

```text
$ ... 先 create_file，外部写入“外部编辑器写的新细纲”，再 write_file(revision=None) ...
revision=None write: OK -> external edit overwritten: True
stale revision write: OutlineError outline_conflict
```

**最小修复**
对已存在文件强制要求 `revision`（缺失返回 428/409）；新增文件才允许省略。`write_lore` 同样处理。

### P2-9 `create_file` 不持 outline 锁，两个并发创建都返回 created 且后者覆盖前者

**位置**
- `backend/integration/outline_editor.py:545-569`

**机制**
`create_file` 先 `path.exists()`，随后写临时文件并 `replace_with_retry`，全程不持 `outline.lock`。两个请求同时通过存在性检查，后一个 `os.replace` 覆盖前一个；两者都返回 `created`。

**影响**
新建大纲文件的其中一份内容丢失，且没有冲突提示。

**复现/证据**

```text
$ ... 两个线程 create_file 同名，replace_with_retry 同步 ...
results: {'b': 'created', 'a': 'created'}
final content: '## 第1章 乙\nB\n'
```

**最小修复**
`create_file` 进入 `_lock(project)` 并用 `O_EXCL`/`_create_bytes_exclusive` 创建；已存在返回 409。

### P2-10 任意以数字开头的 `.md` 会被解析成章节，`1.5设定备注.md` 可使整本书的章节操作失败

**位置**
- `backend/integration/chapter_versions.py:50-53`（第二个正则 `^\s*0*(\d+)(?:[：:\-＿_\s]*(.*))?$` 允许任意数字前缀）
- `backend/integration/chapter_versions.py:196-217`（`chapter_path`/`chapter_map` 的重复章节检测）

**机制**
`parse_chapter_name("1.5设定备注.md")` 返回 `(1, ".5设定备注")`。若同一目录已有 `第1章-正文.md`，`chapter_map`/`chapter_path` 抛 `duplicate_chapter_files`；`new_chapter`、`chapter_state`、`save_version` 等所有依赖章节枚举的入口一起失败。

**影响**
作者在 `正文` 目录放一个数字开头的备注文件即可让工作台无法读写章节（可用性破坏），且错误码是 `duplicate_chapter_files`，不易定位。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_chapter_names.py
numeric note parse: (1, '.5设定备注')
chapter_map failed: VersionConflict duplicate_chapter_files
chapter_path failed: VersionConflict duplicate_chapter_files
new_chapter failed: VersionConflict duplicate_chapter_files
```

**最小修复**
收紧 `_CHAPTER_PATTERNS`：数字形式要求分隔符（`[：:\-＿_\s]+`）或整名匹配；`1.5...` 不应被识别为章节。必要时把无分隔符的数字文件列为 `unattributed` 而不是章节。

### P2-11 POSIX 合法标题含 `:` 的章节可删除但无法恢复，卡在回收站

**位置**
- `backend/integration/chapter_editor.py:697-702`（`restore_trash` 把 manifest 标题交给 `commit_raw_bytes`）
- `backend/integration/chapter_versions.py:264-269`（`_new_chapter_path` 用 `_WINDOWS_BAD` 拒绝 `:`）
- `backend/integration/chapter_editor.py:101-110`（`_validate_title` 同样拒绝）

**机制**
POSIX 上可存在 `第1章-a:b.md`，`chapter_state` 标题为 `a:b`，`delete_chapter` 可以归档。恢复时章号已空，`commit_raw_bytes` 走 `_new_chapter_path`，标题校验抛 `invalid_chapter_title`；由于 commit 记录/对象已经写入一部分，恢复失败且回收站条目保留，无法通过 UI 恢复。

**影响**
作者在 Linux/macOS 上的既有章节删除后无法恢复；这类文件在 v0.7.5 兼容项目中可能存在。编辑保存同标题也会被 `invalid_title` 拒绝。

**复现/证据**

```text
$ AUDIT_BACKEND=... python3 .../probe_chapter_names.py
parsed title: (1, 'a:b')
delete status: deleted entry: 20261127T075506-ch0001
restore failed: VersionConflict invalid_chapter_title
chapter exists after failed restore: None
trash still lists entry: True
```

**最小修复**
恢复时先对标题做可逆的 Windows 安全编码（或沿用原文件名，标题只做元数据）；如不能安全落盘，应在删除前拒绝该章，而不是删除后才失败。`save_version` 对旧标题提供兼容清洗/重命名路径。

### P2-12 `unchanged` 判定使用规范化 body digest，会静默丢弃 Markdown 硬换行/文件尾换行等编辑

**位置**
- `backend/integration/chapter_editor.py:69-70`（`_body_digest` 先 `_normalize_lf` 再 `safety.body_digest`）
- `backend/fanqie_auto_publish/publication_safety.py:255-260`（`normalized_body` 对每行 `rstrip` 并整体 `strip`）
- `backend/integration/chapter_editor.py:438-453`（`unchanged` 分支不写盘）

**机制**
`body_digest` 去掉每行尾随空白和文件首尾空白。Markdown 用“行尾两个空格”表示硬换行；这类编辑及文件尾换行变化会被判为 `unchanged`，`save_version` 返回成功但不写入，随后 `clear_draft_if_matches` 还可能清掉提交的草稿。

**影响**
作者有意的排版修改被静默丢弃；如果同时提交草稿，草稿内容也被清除，属于小范围但真实的正文数据丢失。

**复现/证据**

```text
$ ... save_version(content="第一行  \n第二行\n") against disk "第一行\n第二行\n" ...
status: unchanged unchanged: True
requested bytes equal disk: False
disk: '第一行\n第二行\n'
body digest old/new equal: True
```

**最小修复**
`unchanged` 必须用原始字节/精确文本比较（或至少保留行尾空白的 digest）；`body_digest` 只用于审查报告绑定，不用于“是否需要写盘”。

### P2-13 `restore_version(restore_title=True)` 不重命名文件，版本标题与文件名永久分裂

**位置**
- `backend/integration/chapter_versions.py:801-826`（`title=meta["title"]`）
- `backend/integration/chapter_versions.py:408-422`（`_write_chapter_bytes` 找到现有 path 后只写内容，不改名）

**机制**
恢复旧版本时如果旧标题与当前文件名不同，`commit_raw_bytes` 只把历史标题写进版本元数据；`_write_chapter_bytes` 复用当前路径，不执行 `chapter_editor._rename_chapter_file`。结果 `current_version.title` 是旧标题，磁盘文件名仍是新标题。

**影响**
`chapter_state` 标题来自文件名，`report_ref` 的 title digest 来自版本元数据，两者不一致；后续 `author_confirm`/发布快照可能以不同标题通过不同检查。

**复现/证据**

```text
$ ... 新题章恢复旧题版本 ...
before restore file: 第1章-新题.md
restored version title: 旧题 file: 第1章-新题.md
chapter_state title: 新题
```

**最小修复**
恢复标题时调用统一的 `_rename_chapter_file`（带事务/回滚），或在 `restore_title=True` 时同步把版本标题更新为当前文件名标题；二者必须一致。

### P2-14 `export_legacy` 的 API 默认目标在作品目录内，必然被自身安全校验拒绝

**位置**
- `backend/manager/api_v08.py:239-247`（未指定 destination 时默认 `_book(identity)/.webnovel/exports/...`）
- `backend/integration/transaction_journal.py:1624-1628`（`_is_within(project_path, dest)` 抛 `destination_inside_project`）

**机制**
API 默认目标在 `.webnovel/exports`，而 `export_legacy` 明确拒绝作品内目标；不传 `destination` 的请求 100% 失败。

**影响**
UI 的“导出旧版副本”默认按钮不可用（400 `unsafe_path`），只能让用户手填作品外路径。

**复现/证据**

```text
$ ... export_legacy(project, project/".webnovel"/"exports"/"legacy-1") ...
export default inside project: UnsafePath destination_inside_project
```

**最小修复**
默认目标改到 `data_dir/exports` 等作品外目录，或在 `export_legacy` 中显式允许项目内 `.webnovel/exports` 子目录（并排除递归复制该目录）。

### P2-15 版本 id 序号超过 9999 后，manager 的 `ver_\d{4}` 正则拒绝合法版本 id

**位置**
- `backend/integration/chapter_versions.py:90-91`（`f"ver_{int(seq):04d}_{uuid...}"`，宽度只是最小 4 位）
- `backend/manager/app.py:2059-2064`（读取路由 `ver_\d{4}_[0-9a-f]{8}`）
- `backend/manager/app.py:768-771`（`RestoreInput` 同样）
- `backend/integration/chapter_versions.py:726` 的 64hex fallback 仍可用，但 UI 的版本 uid 不可读/不可恢复

**机制**
第 10000 个版本 `new_version_id(10000)` 生成 `ver_10000_xxxxxxxx`；两个 API 正则都只接受 4 位序号，返回 400。64hex sha 仍可读，但 UI 显示的是 `ver_...` uid。

**影响**
超长连载（单章 1 万次保存）后，版本历史中的 uid 无法通过读取/恢复 API 使用；属于边界兼容问题。

**复现/证据**

```text
$ python3 - <<'PY' ... new_version_id(10000) + 两个 manager 正则 ...
5-digit version id: ver_10000_824306b6
manager read pattern: False
restore pattern: False
```

**最小修复**
统一版本 id 契约为 `ver_[0-9]{4,}_[0-9a-f]{8}`，或固定使用 8 位序号；manager 两处正则同步放宽。

---

## 5. P3

以下为卫生/低频边界，除注明外为静态假设（无执行证据），按规则降级。

### P3-1 `op_id` 允许 `:`，Windows 上会生成非法文件名
- 位置：`chapter_editor.py:46`（`_OP_ID_RE` 含 `:`）、`chapter_versions.py:381-382`（`{op_id}.json`）。
- 机制：Windows 文件名不允许 `:`；ISO 时间戳风格的 op id（`2026-11-27T07:00:00`）在保存/恢复时会 `OSError`。Linux CI 无法暴露。
- 最小修复：`_OP_ID_RE` 去掉 `:`，或 op id 只作为元数据、文件名改用 uuid。

### P3-2 回执整表读改写：`author_confirm`/`revoke`/`_drop_receipt` 可覆盖其他章节的回执
- 位置：`chapter_editor.py:152-160`（`_write_receipts` 合并整章条目）、`885-950`（`author_confirm` 不持章节锁）、`953-970`（`revoke`）、`554-558`（`_drop_receipt`）。
- 机制：`_write_receipts` 虽然重读最新，但调用方传入的是整章 entry；并发另一进程更新同章 review/回执时，旧 entry 整体覆盖新字段。`_drop_receipt` 更是在锁外读全表后写回，能丢掉其他章节的新回执。
- 影响：发布/审查证据丢失或回退；与 P1-5 同类，但走 receipts 文件。
- 最小修复：所有回执写都持 `receipts.lock`，按字段级 patch（或重新读取后只改目标 key），禁止整章 entry 覆盖。

### P3-3 `restore_backup` 非原子、无业务锁、可写作品外 `.db`
- 位置：`transaction_journal.py:1500-1559`（逐文件写入，`1539-1550`）；`_validate_outside_target` 只限制后缀与系统目录。
- 机制：恢复先覆盖正文/索引/objects，再写 SQLite；中途失败/崩溃留下半恢复项目；恢复时 Manager/Worker 可能仍在写同一项目，且外部 SQLite 目标可以是任意 `.sqlite3/.db`（只要作者确认）。无回滚、无 journal、无锁。
- 影响：恢复失败可造成混合版本；运行中恢复可能让打开的连接继续写已 unlink 的 DB；外部目标可覆盖其他应用数据库。
- 最小修复：恢复前取得项目级排他锁/停止服务，整批通过 journal 原子替换；外部 DB 恢复要求显式 `--force` 并校验目标身份，禁止覆盖正在使用的 DB。

### P3-4 正文/JSON 写入缺目录 fsync，断电后目录项可能丢失
- 位置：`chapter_versions.py:408-422`、`publication_safety.py:39-50`、`bridge.py:553-562`。
- 机制：文件内容 fsync 后 `os.replace`，但没有 `os.open(parent); os.fsync`；`transaction_journal._atomic_write_bytes` 做了目录 fsync，其他写路径没有。断电后可能出现“文件内容持久但目录项未持久”。
- 影响：崩溃/断电后章节文件或索引可能回到旧目录项；与 P1-4 叠加。
- 最小修复：统一使用带目录 fsync 的 atomic helper；或全部走 transaction_journal 的写入封装。

### P3-5 `adopt_legacy`/`adopt_originals` 无锁，迁移与用户保存并发会丢索引
- 位置：`chapter_versions.py:869-903`、`906-927`。
- 机制：读取 index、追加版本、`_save_index` 全程不在 `.lock` 内；并发 `commit_candidate` 已持锁写入后，adopt 用旧快照覆盖。
- 影响：升级迁移期间用户保存的版本可能从索引消失。
- 最小修复：`with file_lock(paths["lock"])` 包住整个 adopt 流程。

### P3-6 `studio` 批处理/规划/删除样本的崩溃窗口
- 位置：`studio.py:471-483`（章节生成返回后、`completed` 写回前崩溃）、`193-228`（先写 `AI规划-*.md` 再写 `story_plan.json`）、`161-177`（先删样本/检查点再清 `creative_brief.learning`）。
- 机制/影响：批处理崩溃后章节存在但未记 completed，恢复时 `_generate_chapter_locked` 对非空章节抛 `FileExistsError`；规划文件已存在而索引未写时下次规划拒绝覆盖；样本已删但 learning 仍指向它，`reject_sample_copy` 读文件 500。
- 最小修复：分别把“章节+completed”“规划 md+index”“样本删除+learning 清空”做成可恢复状态机/事务，恢复时先核对磁盘再继续。

### P3-7 `sync_chapter` 全量替换本章机器事实；空提取会删除旧事实
- 位置：`memory_library.py:606-620`（先过滤本章所有 machine items，再按新 candidates 重加）
- 机制：短章路径允许模型返回空 `facts`，代码会把本章旧机器事实全部删除并把章节标记 synced；长章 `extract` 空结果会抛错，但短章不会。
- 影响：一次模型空输出可清空该章已确认事实；上下文随后缺少历史证据。
- 最小修复：空提取不删除旧事实，标记 `empty_extraction` 待确认；或区分“模型明确无事实”与“提取失败”。

### P3-8 `transaction_journal` 的损坏/冲突记录处理不完整
- 位置：`pending` 844-861 跳过无法解析的 `tx_*.json`；`recover` 889-901 把无效记录标 skipped 但不进入 conflict；`prepare` 失败会留下 staging 目录（无 GC）。
- 机制/影响：损坏的 tx 记录既不阻塞读取也不出现在诊断；崩溃后 staging 目录无限增长。与 P2-1 的读取门禁问题叠加。
- 最小修复：损坏记录写 `.conflict` 标记/诊断列表并让读取 409；启动清理孤儿 staging（保留 N 天）。

### P3-9 备份/发布快照的边界
- 位置：`transaction_journal.py:1058-1075`（`_copy_tree` 静默跳过 symlink，manifest 只记 skipped，`inspect_backup` 仍 valid）；`1118`（`source.as_uri() + "?mode=ro"` 对含 `?`/`#` 的路径无效）；`235-263`（`_create_bytes_exclusive` 在无硬链接文件系统上的 fallback 先 `exists` 再 `rename`，并发可覆盖）；`1699-1712`（快照只检查字段非空，不校验 content_sha256/body_digest/title_digest 与 version_id 的交叉一致）。
- 影响：备份可能少文件但显示有效；特殊路径备份失败；快照可写入内部不一致字段并被 `verify` 判 valid。
- 最小修复：skipped symlink 在 `inspect_backup` 判 invalid/需确认；URI 使用 `Path.as_uri` 编码或 `file:` 构造；快照写入/复验时交叉校验正文、版本和标题摘要。

### P3-10 低风险卫生项
- `chapter_versions.py:319`/`369`：`read_object`/`read_candidate` 的 path 参数未做字符集校验（HEAD 中依赖调用方约束；P0-1 的同类防御应一并收紧）。
- `chapter_versions.py:129-143`：`load_index` 对损坏 JSON 抛 `PublicationBlocked`（非 `VersionError`），API guard 不捕获，返回 500 而非可诊断的 409。
- `chapter_versions.py:528-530`：`recover_pending` 对单个损坏 commit 文件无 try，可能中断整个恢复循环。
- `chapter_versions.py:849-850`：`prune_adopted` 把 `current` 设为 `keep[-1]`，不校验该版本是否等于磁盘；删掉 adopted 后 current 可能指向旧正文。
- `version_history.py:16`/`version_history.py:116`：`limit=0` 时 `versions[-0:]` 返回全部版本，不是空；负 limit 行为也不直观。
- `chapter_editor.py:241-260`：`chapter_state` 是 GET，却会创建 `chapter_meta`/DB；只读接口产生写入副作用。
- `chapter_editor.py:1102-1107`：`search_project` 每次搜索都全量 `index_project`，大书搜索是 O(N) 写事务。
- `workbench_db.py:376-380`：整个 SCHEMA 依赖 FTS5；SQLite 未编译 FTS5 时 `initialize` 整体失败，不只是搜索不可用。
- `workbench_db.py:485-497`：`commit_generation`/`bump_commit_generation` 无生产调用方，读取一致性代次未实现。
- `chapter_editor.py:81-82`：`_decode` 用 `errors="replace"` 读取非法 UTF-8，编辑器保存回写会把原字节替换成 U+FFFD（若有版本对象可恢复，但无版本的老稿会实质改写）。

---

## 6. 覆盖与未覆盖说明

- 已实际读取并交叉检查：`workbench_db.py` 全部 893 行、`transaction_journal.py` 全部 1794 行、`chapter_versions.py` 全部 946 行、`version_history.py` 249 行、`chapter_editor.py` 1107 行、`outline_editor.py` 660 行、`invalidation.py` 211 行、`publication_safety.py` 419 行、`memory_library.py` 862 行、`studio.py` 583 行；对应测试与 manager `api_v08.py`、`app.py` 的调用入口。
- 现有 144 个相关测试全部通过（skip 1），说明上述问题主要是**测试未覆盖的崩溃/并发/边界路径**，不是既有用例回归。
- 未覆盖：Windows 实机（`op_id` 冒号、junction/重解析点行为只能静态判断）；真实断电（用 `SystemExit`/monkeypatch 模拟崩溃边界）；大书 12000 条记忆/1000 章性能未做基准，仅标注性能风险。
- 与工作树的关系：审计期间其他进程的未提交修改不在本报告基线内；如果父 agent 要在当前工作树上复核，请先确认 `git status`，并注意 P0-1 的 `_require_id` 修补可能已覆盖部分问题。

## 7. 复现脚本索引

| 脚本 | 覆盖发现 |
| --- | --- |
| `probe_p0.py` | P0-1 |
| `probe_retry_prepared.py` | P1-1 |
| `probe_split_crash.py` | P1-2 |
| `probe_import_retry.py` | P1-3 |
| `probe_commit_crash.py` | P1-4 |
| `probe_index_race.py` | P1-5 |
| `probe_invalidation_race.py` | P1-6 |
| `probe_merge_fail.py` | P1-7 |
| `probe_new_race.py` | P1-8 |
| `probe_cross_chapter.py` | P1-9 |
| `probe_polish_bypass.py` | P1-10 |
| `probe_idem_stuck.py` | P2-2 |
| `probe_snapshot_rewind.py` | P2-3 |
| `probe_trash_identity.py` | P2-4 |
| `probe_backup_race.py` | P2-5 |
| `probe_tombstone.py` | P2-6 |
| `probe_meta_race.py` | P2-7 |
| `probe_chapter_names.py` | P2-10/P2-11 |
| `probe_import_retry.py` | P2-15（附带） |
| journal 冲突探测 | P2-1（内联脚本，见正文） |
| 版本 id 正则探测 | P2-15（内联脚本） |
| create_file 竞争、外部编辑覆盖 | P2-8/P2-9（内联脚本） |
