# E 域第四轮独立审计报告（发布状态 / 跨域契约 / 路由 / 生成物）

- 工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v4/head-e`，detached `ce50d08`（`docs: correct third audit P1 closure count`）
- 基线：`4f5a5a1`（第三轮审计）→ `bae08da`/`36f5add`/`ce50d08`（第三轮修复）
- 审计方式：只读代码审阅 + 真实 `TestClient`/版本层/回执层探针 + 全量 integration/manager/Node 测试 + `check-release --local`；未联网、未修改 tracked 文件、未 commit。
- Python：`/home/ubuntu/venvs/dsh/bin/python`（3.12.3）；Node `v26.12.1`。所有临时项目/日志写入 `audit-v4/tmp-e/`。
- 测试产生的 `backend/integration_data/`、`__pycache__/` 已清理；最终 `git status --short` 仅剩 `?? node_modules` 软链。

## 0. 结论摘要

| 级别 | 数量 | 条目 |
|---|---|---|
| P0 | 0 | 未发现新的不可逆数据丢失或全站 500 |
| P1 | 2 | E-01R 回执重写路径抹掉已发布事实；E-01B 升级前已发布章节未回填回执 |
| P2 | 8 | E-01C 编辑已入队章节后的 staged 死锁；E-01D unknown/浏览器路径无回执；E-01E 超时/异常分支跳过回执；E-01F 回执形状损坏时只读保护 fail-open；E-01G 与 C3-01 的审查事实源分裂；E-02 空库 500；E-04 reviewed 失真；E-05 版本错误码未映射 |
| P3 | 7 | E-03 export 仍未绑定版本；E-06 build-runtime 默认改 runtime 版本；E-07 RELEASE_STATUS 过期；E-08 `/internal/events/notify` 未接线；E-09 session 丢弃；E-10 quality 分页前端未接；测试残留导致 check-release 本地红 |

**发布门禁结论**：干净工作树 `node scripts/check-release.mjs --local` **通过**，1189 个受管文件与清单一致，`buildId=1079d3627947e433115e9886d8325b544ee7c1927b720941d5c620b89d753bac`；`runtime-download.json.buildId` 与清单同步，`runtimeAssetBuildId=b181...` 保留 v0.7.0 运行时复用。跑完全量测试后 `backend/integration_data/` 会让门禁变红，清理后恢复绿（§7.3）。

**修复核验**：第三轮声称的 E-01 核心路径确实生效——stage 写 `staged_at`、整批/部分批次 `platform_confirmed+archived` 逐章写 `published_sha256`、`publish/submit` accepted 写回执，delete/split/merge 在正常路径返回 409（§2.1 证据）。但“已发布只读”仍可被正常 API 重新审查/润色清空（E-01R），升级前的历史发布也没有回填（E-01B），因此不能把 E-01 记为完整关闭。

---

## 1. 验证基线（全部实跑）

### 1.1 发布门禁

```text
$ cd /home/ubuntu/.hermes/cache/scratch/audit-v4/head-e
$ node scripts/check-release.mjs --local
发行清单校验通过：1189 个文件与清单一致，
buildId=1079d3627947e433115e9886d8325b544ee7c1927b720941d5c620b89d753bac
EXIT=0
```

清单结构：`runtime-manifest.json` 共 3442 项（backend 1189 + runtime 2253），`version=0.7.0`（复用 v0.7.0 runtime）、`packageVersion=0.7.5`；实际 production backend 文件 1189 与清单 backend 项 **完全一致，0 missing / 0 extra**（§7.2）。

测试后的残留（非代码哈希漂移）：

```text
$ node scripts/check-release.mjs --local
后端包混入本地状态：backend/integration_data
发行清单校验失败：1 项（已检查 1189 个文件，跳过 2253 个缺席 runtime 项）。
$ rm -rf backend/integration_data && node scripts/check-release.mjs --local
发行清单校验通过：1189 个文件...
```

### 1.2 全量测试（正确命令）

```text
$ cd head-e && PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
  /home/ubuntu/venvs/dsh/bin/python -B -X utf8 \
  -m unittest discover -s backend/integration -t backend
Ran 1270 tests in 93.976s
OK (skipped=9)

$ ... -m unittest discover -s backend/manager -t backend
Ran 235 tests in 85.925s
OK

$ npm test
tests 185 / pass 169 / fail 0 / skipped 16
```

> 说明：从 `backend/` 目录用 `discover -s integration` 而不带 `-t backend` 会触发相对导入错误；该错误命令的 2 failures/33 errors 不作为产品缺陷。以上为仓库根、`-t backend` 的正确结果。

### 1.3 探针

| 脚本 | 覆盖 |
|---|---|
| `tmp-e/probe_e4.py` | E-01 stage/partial/unknown/timeout/backfill/corrupt/browser；E-02；E-03；E-04；E-05；WRITE_ROUTES；manifest；E-06 |
| `tmp-e/probe_pub_residual.py` | `publishing.submit_chapter` unknown/mismatch、browser reconcile accepted 后仍无回执、DELETE 200 |
| `tmp-e/probe_review_erase.py` | 已发布章节重新审查 → 回执被覆盖 → DELETE 200（真实 `review_existing_chapter_async`，仅 mock AI executor） |
| `tmp-e/probe_polish_erase.py` | 已发布章节润色 → 回执被覆盖 → DELETE 200（真实 `studio.polish_existing`，仅 mock AI/改写器） |
| `tmp-e/probe_staged_edit.py` | 已入队章节编辑后重新 stage 冲突、staged 回执不更新、DELETE 409 死锁 |

日志：`tmp-e/probe_e4.log`、`probe_pub_residual.log`、`probe_review_erase.log`、`probe_polish_erase.log`、`probe_staged_edit.log`、`integration-correct.log`、`manager-correct.log`、`npm-test.log`。

---

## 2. E-01 发布状态：已关闭与残余

### 2.1 已确认关闭的路径（正面核验）

**stage 写 staged 回执**：`backend/integration/bridge.py:608-612` 在 `save_manifest` 后调用 `_record_staged_receipts`；`publication_state.record_staged` (`publication_state.py:123-156`) 在 `receipts.lock` 内合并 `staged_at`/`staged_sha256`/`stage`，保留 `review`。

实测（`probe_e4.log` §E-01 stage）：

```text
stage.receipts: [('1', True, True), ('2', True, True)]        # staged_at 存在，staged_sha == 磁盘 sha
stage.records: [(1, True, None), (2, True, None)]
delete-staged-2: 409 chapter_published_readonly
split-staged-2: 409 chapter_published_readonly
merge-staged: 409 chapter_published_readonly
```

**部分批次 confirmed 逐章回写**：`bridge._record_published_receipts` (`bridge.py:419-458`) 只要求单项 `state == "platform_confirmed" and archived is True`，不等待整批 `verified_success`；`run_publish` 在 `bridge.py:1051` 调用它。实测 3 章批次、第 3 章在 `fill` 阶段失败：

```text
run_publish.exit: 2
partial/receipt-1: {'published': True, 'source': 'legacy_publish'}
partial/receipt-2: {'published': True, 'source': 'legacy_publish'}
partial/receipt-3: {'published': False, 'source': None}
partial/ch3-publication: {'status': 'staged', ...}
partial/merge: 409 chapter_published_readonly
partial/delete-ch3: 409 chapter_published_readonly
```

**publish/submit accepted 回写**：`publishing.submit_chapter` (`publishing.py:681-689`) 成功后调用 `record_published`；`probe_e4.log` 的 `e03/submit-current` 返回 `publication_state.recorded=True`；`test_publication_state.py:225-241` 覆盖 DELETE 409。

因此第三轮“E-01 核心关闭（stage、整批/部分批次 confirmed、submit accepted）”在**新产生的事件**上成立；下面的残余都发生在这条主路径之外。

---

### 2.2 E-01R [P1] 重新审查/润色会覆盖整章回执，抹掉 `published_sha256`/`staged_at`

**位置**
- `backend/integration/writer_runner.py:1369-1378`：`review_existing_chapter_async` 用**新的** `receipt = {"destination","sha256","review","revision_rounds","reviewed_at"}` 覆盖 `receipts[str(chapter_id)]`；只复制 `post_save`，不复制 `published_sha256`/`published_at`/`publish`/`staged_at`/`stage`。
- `backend/manager/app.py:2134-2143`：`POST /api/projects/{identity}/chapters/{chapter}/review` 直接启动 `writer_runner.review_existing_chapter`，不检查发布状态。
- `backend/integration/studio.py:541-552`：`polish_existing` 同样用新回执覆盖；其唯一发布保护是 `studio.py:492-494` 读 `bridge.load_manifest()` 的 `status == "published"`，不看 `writer_receipts`，manifest 缺失/`archive_unverified`/第三层发布时直接放行。
- `backend/integration/writer_runner.py:1378,1380`、`studio.py:552`：`atomic_json(receipts_path, receipts)` 没有使用 `receipts.lock`（对比 `chapter_editor._update_receipts:162-174` 与 `publication_state._update:100-120`），与发布回执写者存在丢更新竞态。

**机制**
`chapter_editor._published_state` 只从回执读 `published_sha256`/`publish.sha256`/`staged_at`（`chapter_editor.py:207-228`）。`review_existing_chapter_async` 在**写回执之前**就构造新字典，且即使审查未通过（`review_failed`）也会先写回执；因此只要对已发布章节调用一次 `/review`，发布事实即被删除。`studio.polish_existing` 在 manifest 保护不成立时同理。

**实测**（`probe_review_erase.log`；真实函数，仅 mock AI executor）

```text
published-record: {'recorded': True, ...}
before: {'status': 'published', 'published_sha256': '7f7adf...', 'local_diverged': False}
review-result: review_failed pass
after: {'status': 'unpublished', 'published_sha256': None, 'local_diverged': False}
receipt-fields: {'published_sha256': False, 'publish': False, 'staged_at': False}
delete-after-review: 200 deleted
```

`probe_polish_erase.log`（真实 `studio.polish_existing`，manifest 无该书绑定）：

```text
before: {'status': 'published', ...}
polish-result: polished pass
after: {'status': 'unpublished', 'published_sha256': None, ...}
receipt-fields: {'published_sha256': False, 'publish': False, 'staged_at': False}
delete-after-polish: 200 deleted
```

**影响**
已发布章节可通过正常 API 重新审查（即使审查失败）变回 `unpublished`，随后 `DELETE /chapters/{n}` 返回 200；`published_diverged` 警告也随之消失。平台侧仍是旧章节，形成静默的平台/本地分叉。`studio.polish` 在 legacy manifest 状态为 `published` 时会被拦截，但第三层发布、manifest 丢失、`archive_unverified`（账号不一致）或旧项目无 manifest 时同样会抹掉回执；而且它只检查 `published`、不检查 `queued`，对已入队章节润色会清掉 `staged_at`，DELETE 同样放行而队列副本仍在。该问题直接推翻第三轮“delete/split/merge 409”的结论。

**最小修复**
1. 所有回执写者统一走一个 `publication_state.update_receipt(project, chapter, mutate)`：在 `receipts.lock` 内读最新、保留未知字段、原子写；禁止 `receipt = {...}` 整章替换。
2. `review_existing_chapter_async` 在写回执前检查 `_published_state`；若已发布/已入队，要么拒绝（`chapter_published_readonly`），要么保留 `published_sha256`/`publish`/`staged_at` 并更新 review。
3. `studio.polish_existing` 改为读回执状态而不是只读 manifest；保留发布字段。
4. 增加“publish → review / polish → DELETE 仍 409”的集成测试。

---

### 2.3 E-01B [P1] 升级前已发布章节没有回填：archived 只写 manifest，不写 `published_sha256`

**位置**
- `backend/integration/bridge.py:525-537`：`stage_project` 遇到 `archived` 章节时只写 `record["chapters"]`（`status="published"/"archive_unverified"`）并放入 `skipped`，**不调用** `publication_state.record_published`。
- `backend/integration/bridge.py:608-612`：`_record_staged_receipts(project_root, display_name, staged + skipped)`，但 `_record_staged_receipts` 只处理 `item["status"] == "queued"`（`bridge.py:391-417`），archived 的 `published`/`archive_unverified` 被过滤。
- `backend/integration/chapter_editor.py:207-228`：`_published_state` 只认 `writer_receipts`，不读 `uploaded/` 归档 journal 或 manifest。

**机制**
0.7.5 项目的已发布章节只有 `uploaded/<book>/*.txt` 与其旁 `.publish.json`（`publication_safety.valid_receipt` 可验证），`writer_receipts` 里只有 review，没有 `published_sha256`。升级到本候选后，首次 `stage_project` 会把这些章节当 archived 跳过，既不写 `staged_at` 也不写 `published_sha256`；`_published_state` 继续返回 `unpublished`，delete/split/merge 的只读保护不生效。没有任何迁移/回填函数（`grep record_published` 仅发现 bridge/publishing 的实时调用）。

**实测**（`probe_e4.log` §E-01 upgrade/backfill；先用真实 `publish_batch` 成功发布，再删除回执的发布字段模拟旧版本，然后重新 stage）

```text
backfill.before: {'published': True}
stage.records: []
backfill.after-re-stage: {'published': False, 'staged': False, 'skipped-status': ['published']}
backfill.chapter-state: {'status': 'unpublished', 'published_sha256': None, 'local_diverged': False}
backfill.delete-tail: 200 deleted (existing published chapter unprotected)
```

**影响**
所有在 0.7.5（或第三轮修复前）已经发布的章节，升级后仍可被删除/拆分/合并；作者看到的状态是“未发布”，与平台事实相反。对新发布路径无影响，因此这是升级/导入数据面的 P1，而不是新发布路径的回归。

**最小修复**
在 `stage_project` 的 archived 分支（`bridge.py:525-537`）对 `valid_receipt` 命中的条目调用：
```python
publication_state.record_published(project_root, chapter_id,
    content_sha256=digest_file(source),
    platform="fanqie", account=record.get("account") or "",
    source="archive_backfill", evidence=str(archived[chapter_id]))
```
若 `record_published` 因源文件已改/版本库无该 sha 返回 `recorded=False`，保留诊断原因；或提供一次性迁移脚本扫描 `uploaded/` + journal 回填。再加“旧归档 → stage → DELETE 409”的测试。

---

### 2.4 E-01C [P2] 已入队章节编辑后 `staged_at` 不失效，HTTP 路径无法重新入队，章节被永久锁死

**位置**
- `backend/integration/chapter_editor.py:602-623`：`save_version` 提交新正文后不更新/清除 `writer_receipts.staged_at`/`staged_sha256`。
- `backend/integration/chapter_editor.py:216-217`：`_published_state` 只要看到 `staged_at` 就返回 `staged`，不比较 `staged_sha256` 与当前正文。
- `backend/integration/bridge.py:575-584`：`stage_project` 遇到同名队列文件内容不同且未 `force` 时返回 `conflict`，不替换队列文件、不更新回执。
- `backend/manager/app.py:797-800`：HTTP `StageInput` 只有 `book`/`chapters`，没有 `force`；`bridge.py:1151` 的 `--force` 只在 CLI 可用。

**机制**
作者先入队（`staged_at=A`），再编辑正文（磁盘=B）。`_published_state` 仍因 `staged_at` 返回 `staged`，delete/split/merge 全部 409；再次 `stage_project` 因同名队列文件内容不同返回 `conflict`，不更新回执；`validate_queue_origin` 又因回执顶层 `sha256` 仍是 A、源文件已是 B 而拒绝发布。HTTP 没有 force，用户既不能发布、也不能删除/拆分/合并，只能改磁盘文件或 CLI `stage --force`。

**实测**（`probe_staged_edit.log`）

```text
first stage: 1 receipt staged True
edit status: saved disk 5da363bc
second stage: staged 0 conflicts [(1, 'conflict')]
receipt after re-stage: {'staged_at': True, 'published_sha256': False} staged_sha==disk False
delete: 409 chapter_published_readonly
validate_queue_origin: ValueError 待发内容未通过与源文件及当前创作约定绑定的审查，请重新审查
```

（`validate_queue_origin` 在 `bridge.py:811-815` 对 `receipt["sha256"] == digest_file(source)` 的检查因 A≠B 失败；即发布也被回执锁死。）

**影响**
正常“先入队、后改稿”工作流会把尾章变成不可发布、不可删除、不可拆分/合并的僵死状态；部分批次失败后第 3 章也会进入此状态。清空队列文件也不会清掉 `staged_at`，因为回执独立存在。

**最小修复**
`save_version` 在提交成功后若检测到 `staged_at` 且新 sha != `staged_sha256`，清除 `staged_at`/`staged_sha256`/`stage`（或写 `stage_stale=true`），并让 `_published_state` 把 stale staged 视为 `unpublished`；同时让 `stage_project` 对“同一 source 的旧队列副本且无 journal”自动替换，或在 HTTP `StageInput` 增加显式 `force`。需要补“stage → edit → re-stage → DELETE”测试。

---

### 2.5 E-01D [P2] 结果不明/浏览器发布路径没有回执：unknown/mismatch 后仍可删除

**位置**
- `backend/integration/publishing.py:650-676`：`submit_chapter` 在适配器抛异常或返回未确认/回执不符时写 ledger `unknown`/`mismatch` 并返回，不写任何 `writer_receipts` 发布/待定状态。
- `backend/integration/browser_target.py:755-770`：`publish_once` accepted 只写 ledger/journal，不调用 `publication_state.record_published`。
- `backend/integration/browser_target.py:819-829`：`reconcile_publish` accepted 也只改 ledger，不写回执。
- `backend/integration/publication_state.py:117-120`：`record_*` 遇 `receipts_busy`/`receipts_corrupt` 只返回 `recorded=False`；`bridge._record_*` 不重试、不阻断发布结果。

**机制**
`_published_state` 只认 `writer_receipts`。第三层 `publishing` 与浏览器路径不经过 `bridge.stage_project`，因此没有 `staged_at` 兜底；`unknown`/`mismatch`/accepted 都可能是平台已写入，但本地回执仍为空，`delete_chapter` 直接放行。`reconcile_publish` 人工确认 accepted 后仍不补回执，说明“对账完成”也不会修复只读状态。

**实测**（`probe_pub_residual.log`）

```text
raise status unknown published False
raise delete-tail: 200 deleted
mismatch status mismatch published False
mismatch delete-tail: 200 deleted
browser-unknown unknown reconcile {'changed': 1, 'resolution': 'accepted', ...} published False
browser-after-reconcile delete: 200 deleted
```

`probe_e4.log` §E-01 browser：

```text
browser/publish: {'status': 'accepted', 'writes_confirmed': 1, 'body_matches': True}
browser/chapter-state: {'status': 'unpublished', 'published_sha256': None, 'local_diverged': False}
browser/receipt: {'published': False}
browser/delete-tail: 200 deleted
```

**影响**
当前 `publishing.current_adapter` 与 `browser_target.current()` 在生产代码中都没有注册点（`grep -rn "register_adapter\|browser_target.register" backend --include='*.py' | grep -v test_` 只有定义），所以第三层/浏览器路径线上默认 `unavailable`，属潜伏契约；一旦接入真实适配器，unknown/mismatch/accepted 都会留下“平台已发、本地可删”的窗口。`receipts_busy` 时 legacy 路径同样可能没有 staged 回执（如果 stage 写入恰好锁忙），退化为同一问题。

**最小修复**
在 intent/unknown 阶段写一个 `publish_pending`（含 content_sha、platform、ledger）回执，让 `_published_state` 返回 `publish_pending` 并阻止 delete/split/merge；accepted/reconcile accepted 写 `record_published`；abandoned 清除 pending。浏览器路径同样在 accepted/reconcile accepted 调 `record_published`，unknown 写 pending。对 `receipts_busy` 增加有限重试/诊断告警，不能在无回执时静默继续。

---

### 2.6 E-01E [P2] 子进程超时/异常分支在已确认章节之后提前返回，跳过回执写入

**位置**
- `backend/integration/bridge.py:1026-1035`：`subprocess.TimeoutExpired` 分支读取 `report_path`（可能已有 `platform_confirmed+archived` 条目），写回 exit 2 后 **直接 return 2**。
- `backend/integration/bridge.py:1051`：回执写入只在正常读取 `latest_publish_report` 之后执行；超时分支与 `except Exception` 分支都不会到达。
- `backend/integration/bridge.py:1046`：`latest_publish_report` 若因指针/报告损坏抛错，也会进入异常分支，跳过 `_record_published_receipts`。

**机制**
发布器在确认并归档某章后挂起/超时，报告已含 `state=platform_confirmed, archived=true`；`run_publish` 读到该报告却因为超时分支提前返回，不写 `published_sha256`。legacy 路径通常还有 `staged_at` 兜底，但如果 stage 回执写入失败（锁忙）或项目是升级前状态，DELETE 仍可执行。

**实测**（`probe_e4.log` §E-01 subprocess timeout，已移除 staged 字段以隔离发布回执）

```text
timeout.exit: 2
timeout.report-chapters: [('platform_confirmed', True, 1)]
timeout.receipt: {'published': False}
timeout.delete-tail: 200 deleted (confirmed chapter unprotected)
```

**影响**
平台已确认的章节在超时/证据读取失败窗口内没有发布回执；若没有 staged 兜底，会被删除/拆分/合并。即使有 staged 兜底，读模型仍显示 staged 而非 published，`published_diverged` 也不会被跟踪。

**最小修复**
把 `_record_published_receipts(plan, child, identity)` 移到 `latest_publish_report` 之前，并在 `TimeoutExpired`/`except Exception` 分支对已读到的 `child` 报告同样调用；把回执写入结果并入报告。补“报告已确认 → 子进程超时 → DELETE 409”的测试。

---

### 2.7 E-01F [P2] `writer_receipts.json` 为合法 JSON 但不是对象时，`_published_state` 按未发布处理（只读保护 fail-open）

**位置**
- `backend/integration/chapter_editor.py:149-158`：`_read_receipts` 对非对象根节点抛 `ChapterError("receipts_corrupt")`。
- `backend/integration/chapter_editor.py:207-228`：`_published_state` 捕获 `ChapterError` 后把 `receipts = {}`，返回 `status="unpublished"`。
- `backend/integration/chapter_editor.py:811-813`（delete）、`:1183`（split）、`:1414`（merge）都依赖该返回值。

**机制**
如果回执文件被写成 `[]`（合法 JSON、错误形状），`_read_receipts` 抛 `ChapterError`，`_published_state` 将其吞掉并报告未发布；delete/split/merge 的保护因此失效。`chapter_state` 的 `_review_state` 不吞该异常，同一文件下详情页会报错，进一步说明这是状态读取不一致。invalid JSON 反而会抛 `PublicationBlocked`（`publication_safety.read_json_strict`），走 400；只有“合法但非对象”会 fail-open。

**实测**（`probe_e4.log` §E-01 corrupt receipts）

```text
corrupt/before-state: {'status': 'published', 'published_sha256': 'aad55b...', ...}
corrupt/_published_state: {'status': 'unpublished', 'published_sha256': None, 'local_diverged': False}
corrupt/split-published: 200 {"status": "split", "chapter_id": 1, "new_chapter_id": 2, ...}
```

**影响**
本地回执损坏/被旧工具写成数组时，已发布章节可以被 split（delete 因 `_chapter_receipt_snapshot` 还会读回执而可能失败，但 split 不读快照，实测 200）。这是只读不变量的 fail-open。

**最小修复**
为 delete/split/merge 使用独立的 `publication_guard_state`：`_read_receipts` 失败时返回 409 `publication_state_unreadable`（fail-closed），而不是当成未发布。详情页可以继续按“未知”降级展示，但写保护必须拒绝。

---

### 2.8 E-01G [P2] E-01/E-03 的审查事实源与 C3-01 平台层分裂：只认 legacy `writer_receipts.review`

**位置**
- `backend/integration/publication_state.py:195-222`：`review_binding` 只读 `chapter_receipt(project, chapter).review`，并要求 `entry["sha256"]`/`destination` 绑定。
- `backend/integration/writer_runner.py:154-157`：legacy `review_passed` 走 `quality_gate.review_passed`；`writer_runner.py:1369-1378` 的 review 回执也是 legacy 结构。
- `backend/integration/quality.py:154-190`：v0.9 `quality.review` 只写 `quality_reviews`，不写 `writer_receipts`。
- `backend/integration/publishing.py:519-521`：`register_adapter` 只有定义；`grep -rn "register_adapter" backend --include='*.py' | grep -v test_` 无生产调用。C3-01 的“平台层未接线”仍然成立。

**机制**
E-03 的新门禁 `publish/submit` 要求 `review_binding` 成功；它无法看到 v0.9 `quality_reviews`。因此：
- 只用 v0.9 `/quality/{chapter}/review` 审查的章节，`publish/submit` 返回 `review_missing`；
- 只有 legacy pass 回执、但 v0.9 quality verdict 为 fail 的章节，仍可通过 `publish/submit`；
- 唯一生产发布路径 `bridge.run_publish` 也仍走 legacy `validate_queue_origin`/`model_roles.publication_gate`，不读 v0.9 质量层。
这与 C3-01 的“世界状态/质量/队列/manifest 未进入真实生成与发布”一致：E-01 的“核心关闭”只对 legacy 路径成立，第三层 `publishing` 的写回执生产者没有生产注册点。

**影响**
当前第三层 `publish/submit` 线上始终 `unavailable`，所以不是现网数据损失；一旦接入真实 adapter，v0.9 质量层的 fail 不能阻止发布、pass 也不能获得提交资格，形成两套审查事实源。发布文档不应把 E-01 表述为覆盖全部平台层。

**最小修复**
二选一：
1. 让 v0.9 `quality.review` 在当前版本上写/更新 `writer_receipts.review`（或提供一个 `review_binding` 可查询的映射），并让 `writer_runner` 的发布门禁读同一事实源；
2. 明确标注 `publishing`/v0.9 质量层为 advisory，未接入前 `publish/submit` 仅接受 legacy `writer_receipts`，并在发布说明中限制 E-01 的适用范围。

---

## 3. E-02 [P2] 空 `workbench.sqlite3` 仍让 `/previews` 500（第三轮未修）

**位置**
- `backend/integration/annotations.py:664-678`：`list_previews` 只判断 `wb.db_path(project).exists()`，随后直接 `SELECT * FROM preview_index`。
- `backend/manager/api_v08.py:169-195`：`chapter_previews` 先 `revision_plan.list_previews`，再 `annotations.list_previews`。
- `backend/manager/api_v085.py:167-168`：`annotations/previews` 直接调用。
- `backend/integration/workbench_db.py:118-138`：`connect` 只建连接，不建表。

**机制**
文件存在但 `preview_index` 表不存在（旧 bug 留下的空库）时，`if not db_path.exists()` 不成立，`connect` 后的查询抛 `sqlite3.OperationalError: no such table: preview_index`，由 app 的 `Exception` 兜底返回 500 `internal_error`。读请求不建表，不会自愈。

**实测**（`probe_e4.log` §E-02）

```text
e02/previews-no-db: 200 {"chapter_id": 1, "previews": [], "count": 0}
e02/previews-empty-db: 500 {"code": "internal_error", "message": "服务内部错误：no such table: preview_index"}
e02/annotations-previews-empty-db: 500 {"code": "internal_error", "message": "服务内部错误：no such table: preview_index"}
```

**影响**
旧书/曾触发过 P2-1 的项目，`GET /chapters/{n}/previews` 与 `GET /annotations/previews` 仍 500；工作台 preview 面板不可用。

**最小修复**
在 `list_previews` 打开连接后先查 `sqlite_master`：
```python
row = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preview_index'").fetchone()
if not row:
    return {"chapter_id": int(chapter), "previews": [], "count": 0}
```
保持“读不建库”。`api_v085` 复用同一函数即可。

---

## 4. E-03 [P3] `publish/export` 仍接受任意正文（submit 已关闭）

**位置**
- `backend/integration/publishing.py:545-586`：`_submission_content` 现在要求请求 body 与服务端当前版本正文一致，并校验 `publication_state.review_binding`；`submit_chapter` 在 adapter 前执行（`publishing.py:614-621`）。
- `backend/manager/app.py:1767-1777`：`publish/export` 仍把请求体 `body` 直接传给 `publishing.export_chapter`。
- `backend/integration/publishing.py:335-373`：`export_chapter` 只写本地导出，不做版本/审查绑定。

**实测**（`probe_e4.log` §E-03）

```text
e03/submit-forged: PublishError 请求正文不是服务器当前版本：请先保存并重新审查当前稿 adapter-calls: 0
e03/export-forged: exported False file-contains: True
e03/submit-current: accepted {'recorded': True, ...}
```

`probe_e4.log` 的 submit 结果确认 E-03 的**提交**部分已关闭：伪正文在 adapter 调用前被拒绝，当前正文 + 审查回执可 accepted 并写发布回执。

**影响**
`publish/export` 导出的本地文件可以被写成从未进入版本层、也未审查的正文；它是本地导出，不直接写平台，因此定为 P3。若后续有人把导出文件手工上传，仍需人工确认。

**最小修复**
导出同样接受 `version_id`/当前正文绑定，或至少在导出 manifest 中写 `review_bound:false`、`version_id:null`，并在 UI 标注“未绑定版本的手工导出”；不要把它与“已审查版本”混用。

---

## 5. E-04 [P2] `chapter_state.reviewed` 编辑后仍为 true；human_approved 与发布门禁相反

**位置**
- `backend/integration/chapter_editor.py:231-261`：`reviewed = bool(review.success and review.review_decision == "pass")`，不比较 `review.body_sha256` 与当前正文；`publish_eligible` 只对 `author_confirmed` 计算（`chapter_editor.py:240-248`），`stale` 只对 confirmed 计算。
- `backend/fanqie_auto_publish/publication_safety.py:310-327`：`review_eligible` 接受 `pass`/`author_confirmed`/`human_approved`/`waived_*`；`human_approved` 只要求 `human_review_approved` 与 body sha。
- `client.js:13531`（另 `4209`/`4257`）：章节详情用 `data.reviewed` 显示“已审查”绿色徽章。

**机制**
`save_version` 提交新正文后不失效旧 `review` 回执；`_review_state` 仍以旧回执的 `success/pass` 报告 `reviewed=true`。同时 `human_approved` 回执在 `_review_state` 下 `reviewed=false`、`publish_eligible=false`，但 `publication_safety.review_eligible` 与 `publish/submit` 的 `review_binding` 返回 ok——UI 说“不能发”，API 说“能发”。

**实测**（`probe_e4.log` §E-04）

```text
e04/before: {'reviewed': True, 'review_status': 'pass', 'publish_eligible': False, 'stale': False}
e04/after-edit: {'reviewed': True, 'review_status': 'pass', 'publish_eligible': False, 'stale': False}
e04/new-disk-sha-equals-receipt: False
```

human_approved 探针：

```text
state {'reviewed': False, 'review_status': 'human_approved', 'publish_eligible': False, 'stale': False}
review_binding {'ok': True, 'review': {... 'review_decision': 'human_approved' ...}}
```

**影响**
作者改稿后仍看到“已审查”，但真正发布门禁为 false；human_approved 章节在 UI 显示不可发布，实际 `publish/submit` 可通过。错误反馈滞后到发布时，且两个接口对同一回执给出相反结论。

**最小修复**
在 `_review_state` 计算 `current_digest = publication_safety.body_digest(current_text)`：
```python
reviewed = review.success and review.review_decision == "pass" and review.body_sha256 == current_digest
publish_eligible = publication_safety.review_eligible(review, current_digest, project, chapter)
stale = bool(review) and not publish_eligible
```
不要只对 `author_confirmed` 计算 eligible；`human_approved` 应显示为已审查/可发布（或统一由门禁决定）。

---

## 6. E-05 [P2] 版本层错误码仍未映射：缺失版本/损坏索引返回 400 `request_failed`

**位置**
- `backend/integration/chapter_versions.py:68-81`：`VersionError`/`VersionConflict`/`VersionNotFound`/`VersionCorrupt`；`VersionCorrupt` 不是前两者的子类。
- `backend/manager/api_v08.py:36-56`：guard 只捕获 `VersionConflict`/`VersionNotFound`，不捕获 `VersionCorrupt`。
- `backend/manager/app.py:2110-2130`：`/versions`、`/versions/{version}`、`/restore` 直接调用 `version_history`，未做版本异常处理。
- `backend/manager/app.py:1315-1333`：通用 `RuntimeError` handler 固定 400 `request_failed`，并保留内部原因字符串。

**实测**（`probe_e4.log` §E-05）

```text
e05/missing-version: 400 {"code": "request_failed", "message": "version_not_found"}
e05/corrupt-index-versions: 400 {"code": "request_failed", "message": "index_schema_unsupported"}
e05/corrupt-index-chapter: 400 {"code": "request_failed", "message": "index_schema_unsupported"}
```

**影响**
`GET /chapters/{n}/versions/ver_9999_deadbeef` 应为 404 `version_not_found`，实际 400 且 code 丢失；损坏 `index.json` 是服务端状态问题，应为 500/409 稳定码，实际 400 并把内部 schema 字符串 `index_schema_unsupported` 暴露给调用方；客户端无法区分“版本不存在”和“请求格式错误”。

**最小修复**
在 app.py 注册 `chapter_versions.VersionError` 处理器：
- `VersionNotFound` → 404 `version_not_found`
- `VersionConflict` → 409 + `str(exc)`（现有语义）
- `VersionCorrupt` → 500 `version_store_corrupt`，只记日志，不返回内部原因
或在 api_v08/api_v085 guard 补齐 `VersionCorrupt`，并让 `/versions`/`/restore` 统一复用。

---

## 7. 路由 / 清单 / 生成物

### 7.1 `WRITE_ROUTES`（通过，无新增漂移）

独立解析 `app.py`、`api_v08.py`、`api_v085.py`、`api_v09.py`、`provider_api.py`、`device_access.py`、`free_model_api.py` 的非 GET 路由，与 `index.js:227-...` 的 180 条白名单比对：

```text
write-routes: files 7 non-get 160 whitelist 180 missing 1
  missing: ('POST', '/internal/events/notify', 'app.py')
write-routes/internal-only: 1
```

唯一缺失仍是 `/internal/events/notify`；它不在 `/api` 命名空间，`index.js parseTarget/allowsMutation` 不会代理它，且自身要求 `x-internal-token`，不是提权路径。新增的 `publish/submit`、`publish/export`、`publish/reconcile`、`browser/publish`、`browser/publish/reconcile` 等均在白名单。Node `gate.test.mjs` 185 项测试通过（169 pass/16 skip）。

### 7.2 manifest 覆盖（通过）

```text
manifest: entries 3442 backend 1189 actual-production 1189 missing 0 extra 0
manifest/buildId-sync: True runtime-version 0.7.0 packageVersion 0.7.5 download-url-version 0.7.0
```

- 实际 production backend 1189 个文件全部在清单；无漏项、无多余项。
- `runtime-download.json.buildId` 与 `runtime-manifest.buildId` 一致（`1079d362...`）；`url` 指向 `v0.7.0/...0.7.0.tgz`，与 `version=0.7.0` 一致；`runtimeAssetBuildId=b181...` 保留旧运行时复用。
- `check-release --local` 对根入口（`index.js`/`client.js`/`cordis.patch.yml` 等）也做了存在性校验；本次通过。

### 7.3 E-06 [P3] `build-runtime --manifest-only` 默认把 runtime 版本改成 packageVersion

**位置**：`scripts/build-runtime.py:68`：`previous.update(version=runtime_version or package_version, ...)`；`--manifest-only` 的 `--runtime-version` 默认 None（`build-runtime.py:116-119`）。

**实测**（临时目录模拟，不改仓库）：

```text
build-runtime/default: version 0.7.5 packageVersion 0.7.5 expected-reuse 0.7.0
build-runtime/explicit: version 0.7.0 rc 0
```

**影响**
维护者按常规命令 `python3 scripts/build-runtime.py --manifest-only` 会把 `runtime-manifest.version` 从 0.7.0 改成 0.7.5，而 `runtime-download.url` 仍指 0.7.0；随后 `check-release` 会报“URL 与版本不符”。必须额外传 `--runtime-version 0.7.0` 才保持复用。

**最小修复**
`runtime_version = runtime_version or previous.get("version") or package_version`；或 `--manifest-only` 强制要求显式 `--runtime-version`，并在 `check-release` 中同时校验 `runtime-download.url` 与 `runtimeAssetBuildId` 的对应关系。

### 7.4 E-07 [P3] `RELEASE_STATUS.md` 与当前树不一致

**位置**：`RELEASE_STATUS.md:12` 仍写 `1168` 文件 / `buildId=9f1cc349...` / Node 125 / integration 828 / manager 187 / 完整包 3421。

**当前树**：`check-release` 1189 文件 / `buildId=1079d362...`；Node 185；integration 1270；manager 235；清单总数 3442。

**影响**：若被当作当前候选包记录，会引用错误的 buildId/测试计数；若只描述已发布 0.7.5，应明确标注适用范围。当前两种解读都没有标注。

**最小修复**：冻结后重新生成计数，或在文件头标注“仅适用于已发布 0.7.5；当前 v0.8–v0.9.5 候选见 remediation v3”。

### 7.5 测试残留导致本地门禁红（P3）

**位置**：`scripts/check-release.mjs:168-169` 把 `backend/integration_data` 视为本地状态混入。

**实测**：全量 integration 测试后 `check-release --local` 报 `后端包混入本地状态：backend/integration_data`；清理后恢复绿。CI 的 `ci.yml` 把 `check-release` 放在测试之前（第 25 行），所以 CI 不红；开发者本地“先跑测试再发布”会红。

**最小修复**：测试用 `NOVEL_HELPER_*`/临时数据目录隔离 `backend/integration_data`，或测试 teardown 清理；文档在发布步骤中明确先清理再跑门禁。

---

## 8. 其它残余（P3）

### 8.1 E-08 `/internal/events/notify` 仍未接线

**位置**：`backend/manager/app.py:1258-1264` 只读 `CHAPTER_WHALE_INTERNAL_TOKEN`；`grep -rn "CHAPTER_WHALE_INTERNAL_TOKEN"` 只命中 app.py 与 `test_v09_api.py`，无生产启动脚本赋值；`grep -rn "LoopbackNotifier" backend --include='*.py' | grep -v test` 只有定义。**影响**：C-47 唤醒路径形式上存在、实际不可用（fail-closed，不是权限洞）。**最小修复**：启动脚本注入随机 token 并与 worker 共享，或删除路由/fanout 并文档标注。

### 8.2 E-09 `chief_room_state` 同时传 project_id 与 session_id 时丢弃 session

**位置**：`backend/manager/api_v085.py:198-205`：`session_id=None if project_id else session_id`。**影响**：API 契约歧义；多 session 客户端会拿到项目下所有 session 的事件。**最小修复**：始终把 `session_id` 传给 `snapshot`（它支持 project+session 联合过滤），或两者同时出现时返回 400。

### 8.3 E-10 quality 分页前端未接（静态判定）

**位置**：`backend/manager/api_v09.py:305-310` 支持 `limit/offset`；`backend/manager/static/workbench.js:3648` 调用 `/quality/dashboard` 不带参数（默认 200）。**影响**：205 章以上的书只显示前 200 章，KPI 与列表不一致。**最小修复**：前端传 `limit/offset` 或显示“仅前 200 章”，并把 `averages/reviewed` 改为全书聚合。

---

## 9. C3-01 与 E-01 的矛盾（结论）

第三轮 remediation 把 E-01 写成“核心关闭”，但同一份文档把 C3-01 写成“平台层未接入、需要产品决策”。本轮证据表明两者应这样理解：

1. **E-01 的关闭只覆盖 legacy `bridge.run_publish` 路径**：`bridge._record_staged_receipts`/`_record_published_receipts` 是唯一生产回执生产者；`publishing.submit_chapter`/`reconcile` 的新回写虽然存在，但 `publishing.register_adapter` 无生产调用（`publishing.py:519-521`，grep 无 test 外调用），线上始终 `unavailable`。
2. **C3-01 仍然成立**：`writer_runner` 的审稿/发布门禁仍走 legacy `quality_gate`（`writer_runner.py:154-157`），v0.9 `quality.review` 只写 `quality_reviews`（`quality.py:184-188`），不进入 `writer_receipts`；`publication_state.review_binding`（`publication_state.py:195-222`）只读 legacy 回执。因此 v0.9 审查与 E-03 的“审查绑定”是两套事实源。
3. **因此**：“E-01 核心关闭”应表述为“legacy 发布状态回写关闭”；不能据此认为 v0.9 平台层发布契约已闭环。若要让 E-03 在第三层可用，必须先决定是否把 v0.9 quality 接入 `writer_receipts`/`review_binding`，否则 `publish/submit` 的审查门禁只对 legacy 回执有效。

---

## 10. 未复现 / 边界

1. **真实平台写入未执行**：`publishing.current_adapter` 与 `browser_target.current()` 在生产代码中没有注册点；E-01D 的 unknown/mismatch/browser 使用 fake adapter 验证路由契约，不声称真实平台已可写。
2. **legacy `/api/publish` 未用真实番茄账号复跑**；E-01B 的旧归档/回执关系用真实 `publish_batch` + 文件系统模拟。
3. **review/polish 探针 mock 了 AI executor/改写器**，但回执写入、`chapter_versions` 提交、`DELETE` 都是真实代码；真实模型调用未执行。
4. **E-01B 的影响限于升级/导入数据**；新发布路径由 §2.1 的实测保护。是否把 E-01B 计为 P1 取决于发布说明是否承诺兼容 0.7.5 已发布书；本轮按“升级用户仍会看到已发布章节可删”计 P1。
5. **本机为 Linux**；Windows 文件锁/ACL、真实 DSH 宿主、真实多进程竞争未覆盖。
6. 未修改 tracked 文件、未 commit、未联网；测试产生的 `backend/integration_data`/`__pycache__` 已清理，最终 `git status --short` 仅 `?? node_modules`。

---

## 11. 最终判定

干净树发布门禁**通过**（1189 文件 / `buildId=1079d362...`），manifest 覆盖完整，WRITE_ROUTES 无新增漏配，integration 1270 / manager 235 / Node 185 全绿；第三轮的 E-01 stage/partial/submit 回写、E-03 submit 绑定确实生效。

但发布状态契约仍不能算完整关闭：

1. **E-01R（P1）**：`/review` 和 `studio.polish` 会覆盖整章回执，已发布章节重新审查后变回 `unpublished`，DELETE 200；这是对“已发布只读”的直接回归。
2. **E-01B（P1）**：升级前已发布章节没有回填，归档只在 manifest 里，`_published_state` 仍返回未发布，旧书全部可删。
3. **E-01C/D/E/F（P2）**：编辑已入队章节会锁死；unknown/browser/timeout 无回执；回执形状损坏时 split fail-open。
4. **E-02/E-04/E-05（P2）**：空库 500、reviewed 失真、版本错误码未映射仍未修。
5. **E-01G（P2）**：E-03 审查门禁只认 legacy 回执，与 C3-01 的 v0.9 质量层分裂。
6. **P3**：export 未绑定、build-runtime 默认版本、RELEASE_STATUS、internal notify、session、quality 分页、测试残留，不阻塞当前干净门禁，但应在发布前清理。

**建议优先级**：先修 E-01R（统一回执写者 + 发布保护）和 E-01B（归档回填），再补 E-01C 的 staged 失效与 E-01D/E 的 pending 回执，最后处理 E-02/E-04/E-05 的读模型与错误码。
