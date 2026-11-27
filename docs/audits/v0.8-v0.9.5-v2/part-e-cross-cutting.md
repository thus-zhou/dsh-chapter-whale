# 第二次独立审计 · E 部分：跨域补充（生成管线 / 版本唯一事实源）

- 审计对象：`/home/ubuntu/.hermes/cache/scratch/audit-v2-head`，detached HEAD `5e8a2d0`
- 审计方式：只读审阅 + 在仓库外运行最小复现；未修改仓库文件，未联网。
- 说明：A–D 四路各自负责一个域；E 是主编室在汇总时补做的跨域检查，专门验证「所有正文写入口是否都经过 v0.8 版本层与章锁」。A–D 的原始报告不引用旧审计结论。

## 0. 结论摘要

| 级别 | 数量 |
|---|---|
| P0 | 0 |
| P1 | 1 |
| P2 | 0 |
| P3 | 0 |

| 编号 | 级别 | 结论 | 主位置 |
|---|---|---|---|
| E-01 | P1 | `writer_runner` 生成正文直接 `os.link` 到 `正文/`，不经过 `chapter_versions`，生成章节没有版本索引/快照/当前版本，版本层与并发保护对主生成路径失效 | `backend/integration/writer_runner.py:1192-1274`（尤其 `1253`） |

## 1. P1 详细

### E-01 [P1] 生成管线绕过版本层：正文已落盘，`chapter_versions` 为空

**位置**

- `backend/integration/writer_runner.py:1192`：`destination = _chapter_path(project_root, selected_chapter, title)`
- `backend/integration/writer_runner.py:1235-1245`：先写 `writer_receipts.json`，`receipt["destination"]` 指向目标正文路径
- `backend/integration/writer_runner.py:1246-1255`：`tempfile.mkstemp` 写临时文件后 `os.link(temporary, destination)` 直接发布正文
- `backend/integration/writer_runner.py:1257-1274`：只做 `invalidation`、`_commit_review_candidates`、`_sync_committed_artifacts`，全程没有 `chapter_versions.commit_raw_bytes` / `snapshot` / `recover_pending`
- 调用方：`backend/manager/worker.py:135`、`backend/integration/scheduler.py:1008`、`backend/integration/serial_delivery.py:166`、`backend/integration/draft_delivery.py:306`、`backend/integration/local_completion.py:473`，均为生产生成/交付路径。

**机制**

`generate_chapter_async()` 在 `_writer_locked` 临界区内完成审查后，把正文临时文件 `os.link` 到 `正文/第N章-标题.md`，然后写回执。它没有取得 `chapter_editor` 的 `chapter-N.lock`，也没有调用 `chapter_versions` 的提交入口，因此：

1. `chapter_versions/index.json` 没有该章的 `current` 指针，`versions/` 没有版本对象；
2. `chapter_state()` 返回的 `version_id/current_version` 为空，工作台/发布/历史都认为该章“无版本”；
3. 后续 `save_version` 会把这份正文当作 legacy 正文，首次编辑时先补一个 `legacy-adopted` 快照（若实现允许），但生成时刻的版本、审查回执与正文没有原子绑定；
4. 与工作台保存/拆分/删除并发时，`writer_runner` 只持有 `writer.lock`，不持有章锁，无法与 `chapter_editor` 的写入门禁互斥；
5. 崩溃窗口（回执已写、正文已 link、版本未写）没有 `recover_pending` 可恢复，因为根本没有提交记录。

**影响**

- 日更/批量生成是主要写作入口，生成的章节却不在版本历史中：无法按版本回滚、无法证明“当前正文对应哪次审查”、无法用 `expected_version_id` 做并发保护。
- 生成后在工作台首次保存会走 legacy 分支，版本语义与作者手写章节不一致；发布/质量门禁读取 `chapter_state` 时可能把有正文的章节当成无版本/过期。
- 这是 v0.8 计划“所有正文写入口必须经过版本层”红线的直接违反；与 C-15（v0.9 平台层未接入生成管线）相关但不同：C-15 是平台功能没有被消费，本条是 v0.8 版本层被主生成路径绕过。

**最小修复**

把 `writer_runner` 的正文发布改为版本层提交：

```python
chapter_versions.commit_raw_bytes(
    project_root,
    selected_chapter,
    payload,
    title=title,
    source="writer_runner",
    allow_new=True,
    op_id=op_id,
    expected_sha256=expected_sha,  # 真实并发基线；新建章可为 None
)
```

并让 `writer_receipts.destination` 在版本提交成功后再写；提交前取得 `chapter_editor._locked(project_root, selected_chapter)` 或与 `chapter_versions` 共用的章锁。若 `writer_runner` 需要保留“不覆盖已有章”的语义，用 `allow_new=False` + 存在性检查，而不是先 `os.link` 再补索引。

**复现**

脚本：`/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-parent-writer.py`

```bash
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
python3 -B -X utf8 /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-parent-writer.py
```

实际输出：

```text
status generated destination .../正文/第1章-标题.md
disk_sha 292e73f3f6dcc60f438d66d5d261cd2100279bb34ad27ea88b6737014348be12
index_entry None
versions 0
current_version None
```

脚本用 `unittest.mock` 只替换昂贵的生成/审查调用，保留真实的正文发布、回执写入和版本读取路径；正文确实落盘，`chapter_versions` 确实为空。

**边界**

- 本项不复现真实模型/网络调用；版本缺失与生成内容无关，是发布路径结构问题。
- 若未来给 `writer_runner` 增加“只写草稿、不发布”的模式，同样需要在发布点接入版本层；本次审计只覆盖当前 `os.link` 发布路径。
