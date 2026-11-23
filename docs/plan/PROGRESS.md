# Chapter Whale 进度记录

方案：`方案_优化终版_v3.0`（plan_version 3.0）。本文件是本仓库唯一进度记录，`docs/plan/STATE.json` 是机器可读状态。
规则：代码实现、真实模型验证、GitHub 推送、Release 四类状态分别记录，互不冒充。

---

## M00 基线（2026-11-14）

### 结论

- 仓库、分支、远端、工作区均已确认为可开发状态；`docs/plan/` 此前不存在，因此**没有任何模块可以复用**，M00 是第一个模块。
- 现有代码不是"只有文档声明"：方案里点名的复用目标（writer_runner、revision_workflow、studio、memory_library、costs、fallback_budget、publication_safety）在 `backend/integration/` 与 `backend/fanqie_auto_publish/` 中**真实存在**，且已有 148 项后端测试。

### 实际版本与环境

| 项 | 实测值 |
| --- | --- |
| 分支 / HEAD | `main` / `78d09ec`（与方案 reference_commit 一致）|
| 工作区 | 干净，0 改动；`## main...origin/main` 未分叉 |
| 版本 | `0.2.0-rc.1`（`package.json:3`，`package-lock.json:3,9`）|
| 已有标签 | 仅 `v0.2.0-rc.1` |
| 依赖 | Node ≥22（实测 v24.18.0）；捆绑 Python 3.13.17（`runtime/python/python.exe`）|
| 平台 | 运行环境仅 win32-x64（`package.json` bundle.platforms）|
| 插件形态 | DSH 插件：`index.js`(1061 行) 宿主 + `client.js`(3954 行) Web 面板 + `managed-runtime.mjs` 托管 Python 后端 |

### 目录与复用表（实测行号）

| 复用目标 | 真实位置 | 用途 | 后续模块 |
| --- | --- | --- | --- |
| 正文与回执 | `backend/integration/writer_runner.py`（851 行）：`review_passed` :154、`reviewed_chapters` :160、`_record_review_attempt` :343、`_generate_and_review` :354、`main` :912 | A→B→C→D→E 主链路、正文保存、回执 | M01 M03 M05 |
| 正文落盘 | `正文/第{章号}章 {标题}.md`；文件名由 `bridge.output_filename` 生成，实际写入在 job 交付层（`serial_delivery.py`/`ten_chapter_delivery.py` → `bridge.stage_project`）| 现有正文只有单一当前版本 | M01 |
| 草稿检查点 | `.webnovel/draft_checkpoints/{章:04d}-{key}.json`（`schema:1`、`draft`/`draft_sha256`/`polished`/`polished_sha256`）；key = sha256(章号+字数+约定+大纲+plan 哈希) | 已有不可变中间稿，但约定一变即孤儿 | M01 |
| 审查尝试 | `.webnovel/review_attempts/{章:04d}-{uuid}.json` = `{chapter_id, reviewed_at, body_sha256, review}` | 已有多条历史，缺索引与当前版本指针 | M01 M03 |
| 放行判定 | `backend/fanqie_auto_publish/publication_safety.py:184 review_eligible()` | 唯一放行函数 | M03 |
| 旧判定 | `backend/integration/writer_runner.py:154 review_passed()` | 将被改造成兼容包装器 | M03 |
| 原子写/锁 | `publication_safety.py:39 atomic_json()`、`:57 file_lock()`、`:103 queue_lock()`、`:107 account_lock()` | 已具备临时文件+fsync+重试替换、非阻塞 OS 锁 | M01 |
| 正文哈希 | `publication_safety.py:180 body_digest()`（规范化文本）、`:111 digest_file()`（原始字节） | 报告/回执绑定 | M01 M03 |
| 创作约定绑定 | `publication_safety.py:115 creative_contract_hash()` | 约定+文风+作者记忆 → 单一哈希 | M03 M04 |
| 发布证据 | `publication_safety.py:205 journal_path()`、`:220 valid_receipt()`、`:245 archive_confirmed()`、`:263 validate_origin_plan()` | 发布队列最终资格 | M03 M08 |
| 修订流程 | `backend/integration/revision_workflow.py:76`,`:81` | C 修订 + D 复审 | M05 |
| 作者规则豁免 | `backend/integration/editorial_release.py:109`,`:119`,`:157` | `waived_by_author_rule` | M03 |
| E 豁免 | `backend/integration/model_roles.py:272` | `waived_by_E` | M03 |
| 费用账本 | `backend/integration/costs.py`（`Attempt`、`scope`、`attributed`、`report`、`export_csv`）；库 `integration_data/costs.sqlite3`，表 `usage_events(id, created_at, project, chapter, stage, model, payload)` + `pricing(id=1,payload)`，WAL | 逐请求入账 | M02 |
| 预留/结算 | `backend/integration/fallback_budget.py:reserve/settle/status`（`BEGIN IMMEDIATE`，每项目每日 20 CNY，仅 fallback 路径生效） | 预算占用 | M02 |
| 恢复预算 | `backend/integration/retry_budget.py:status/extension` | 每日重试上限 | M02 |
| 共享记忆 | `backend/integration/memory_library.py`（22KB，`contract()` 参与约定哈希）| 作者确认优先 | M10 M11 M12 |
| 创作台/调度 | `backend/integration/studio.py`、`scheduler.py`、`manager/app.py`（55KB，127.0.0.1:8765）| 现有 UI 后端路由 | M06 M14 |
| 插件代理 | `index.js:211 WRITE_ROUTES`（写白名单）、`:294 allowsRead`、`:876 assertToolPath` | 新写接口必须同时登记 | 全模块 |
| 前端 | `client.js`：`api()` `:688`、`usePoll` `:847`、`useService` `:772`、导航 `:3564`、路由表 `:3763` | 新面板入口 | M03 M06 M14 |

### 放行调用链（实测）

```
writer_runner 章节完成
  └ review_passed(review)            writer_runner.py:154        （旧判定：success 且 needs_revision 为假）
  └ review_eligible(review, body_digest(text), project, chapter)  publication_safety.py:184
      ├ review_decision == "pass"                                → 质量通过
      ├ review_decision == "waived_by_author_rule"               → editorial_release.valid(review, digest)
      └ review_decision == "waived_by_E"                         → model_roles.enabled() && review_policy == "e_decides"
                                                                    && executor_authorization.body_sha256 == 当前正文
发布队列
  └ validate_origin_plan()            publication_safety.py:263
      └ qualification_contract_matches() :140  （约定哈希 + 51 章窄范围豁免证据）
      └ review_eligible() 复查当前正文
      └ valid_receipt() 复查发布证据
```

要点：放行已经**由正文规范化哈希绑定**，不是布尔开关；作者豁免与 E 豁免都带独立授权对象，不会伪装成 `pass`。M03 要做的是把"质量判断"从两个函数收敛到一个入口，并补上六维评分与报告过期判定，而不是另起一套。

### 已核对的自动化检查

| 检查 | 命令 | 实测结果 |
| --- | --- | --- |
| 插件测试 | `npm test` | 47 通过，0 失败，1.4s，无外网 |
| 后端集成测试 | `python -m unittest discover -s backend\integration -p "test_*.py" -t backend` | 93 通过，7.2s |
| 后端管理测试 | `python -m unittest discover -s backend\manager -p "test_*.py" -t backend` | 55 通过，12.0s |
| 发行清单 | `node scripts/check-release.mjs --local` | 见 M08（改动代码后需重新生成 manifest 才通过）|

注：Windows 控制台读中文需 `$env:PYTHONIOENCODING='utf-8'`，否则输出乱码；unittest 用 stderr 打印进度，`[exit code: 1]` 不代表失败，以 `OK` / `FAILED` 行为准。

### 关键风险

1. **发行清单会因任何代码改动而失效**：`runtime-manifest.json` 记录了每个发行文件的 sha256，`scripts/check-release.mjs:10-13` 逐项校验。改代码后必须用 `scripts/build-runtime.py` 重建 manifest（含 `buildId`），不能手改哈希。
2. **版本号重复 12 处**（`package.json`、`package-lock.json`、`market/index.json:81`、`market/losebird-entry.json:8`、`market/submissions.json:5`、`market/catalog-entry.yml:4`、`docs/quickstart.md:28,203`、`README.md:135,144,215,217`、`RELEASE_STATUS.md:1,18,32,36`、`runtime-download.json:2`、`runtime-manifest.json:2`、`scripts/build-runtime.py:55`）。`runtime-download.json` 的 `sha256`/`bytes`/`buildId` 必须与实际 tgz 一致。
3. **CI 只跑 JS 测试**（`.github/workflows/ci.yml`：windows+ubuntu，node 22，`npm test`），后端 148 项测试当前不在 CI 中 → M03 需要把后端隔离测试接入 CI。
4. **市场版本漂移不会被干净 CI 抓到**：`test/market.test.mjs:79` 在没有 DSH 安装时跳过版本比对。
5. **托管模式重装会覆盖代码目录**（`managed-runtime.mjs:83` force 复制 manager/integration/webnovel-writer/fanqie_auto_publish/vendor）；用户数据在 `%LOCALAPPDATA%\ChapterWhale\workspace\integration_data`（不覆盖）。本项目自身开发在仓库内进行，不受此影响。
6. **写接口必须三处同步**：`index.js:211 WRITE_ROUTES` + `index.js:876 assertToolPath` + `client.js` 导航/路由；`test/gate.test.mjs:178` 会校验表与解析器一致。
7. 方案目录的模块文档只是需求，不等于已完成；`docs/plan/` 此前不存在即为证据。

### 仅属旧文档声明、本次未复核的内容

- `RELEASE_STATUS.md` 中的真实平台发布记录、GitHub Release 资产哈希、npm 安装实测、社区目录 PR 状态（需联网核对，未在本轮执行）。
- 真实模型生成质量、真实账号发布成功率（方案明确不在普通模块验证）。

### 后续模块工作量（初判）

小：M00、M07；中：M01、M02、M04、M05、M06、M08、M10、M11、M12、M13、M14；大：M03、M09、M15。

### 下一步

M01：在既有 `.webnovel/review_attempts/` 与回执上扩展正文版本能力（保存候选、读取/列出版本、比较当前版本、提交候选、幂等操作标识），保留旧格式兼容读取。

## M01 正文版本与提交（completed）

**新增** `backend/integration/chapter_versions.py`（唯一新增存储层，未换库、未改 `正文/*.md` 结构、未批量重写旧数据）：

| 目录（`<project>/.webnovel/chapter_versions/`）| 作用 |
| --- | --- |
| `objects/<sha256>.txt` | 不可变正文，按**原始字节** sha256 命名；读时校验，哈希不符报 `VersionCorrupt` |
| `index.json` | 每章 `current` + 版本列表（`seq`/`sha256`/`body_digest`/`source`/`op_id`/`run_id`/`attempt_id`/`parent`），`schema_version:1`，102 章约 72KB |
| `candidates/<id>.json` | 候选稿：正文 + 基线版本 + 来源引用，提交前不碰当前稿 |
| `commits/<op_id>.json` | 提交标记：`prepared → chapter_written → committed`，崩溃留 `conflict` |
| `.lock` | 复用 `publication_safety.file_lock`（跨进程非阻塞锁，同线程可重入）|

**两种哈希分工**（报告契约基础）：`sha256` = 原始字节（校验对象、判断并发修改、保存后读回一致）；`body_digest()` = 规范化文本（统一换行 + 去行尾空白），与既有 review 回执的 `body_sha256` **同一算法**——实测真实项目 52 条回执全部能按此关联到版本。

**API**：`save_candidate` / `commit_candidate` / `write_chapter`（一步）/ `read_version` / `list_versions` / `current_version` / `compare_current` / `report_ref` / `recover_pending` / `restore_version` / `adopt_legacy` / `adopt_originals` / `link_review_attempts` / `prune_adopted`。

**约定**：`project_id` = 项目绝对路径（`/` 分隔）；`chapter_id` = 整数章号；`version_id` = 正文原始字节 sha256；`op_id` = 幂等操作标识（同 op 重复提交返回原记录，内容不同报 `operation_id_reused`）；`run_id`/`attempt_id` 由调用方透传。

**提交顺序与失败语义**：`expected_sha256` 与磁盘当前字节不符即 `concurrent_modification`，绝不覆盖；多文件写入**不是事务**，只是"逐个原子写 + 提交标记 + `recover_pending()` 补齐"，补齐时若当前稿已被第三方改成第三种内容则标 `conflict` 并保留现场。兼容登记（`adopt_legacy`/`adopt_originals`）只读、幂等、不改 `.md`；`prune_adopted` 只删本模块登记的兼容条目与无引用对象。

**检查**（全部离线、0 次模型调用）：
- `test_chapter_versions.py` 10 项全过：旧格式读取、保存后读回一致、并发修改拒绝覆盖、重复 op 不加版本、写入失败 + `recover_pending` 补齐、对象被篡改检出、迁移→回滚→再迁移、旧 `originals` 按哈希引用、回执关联、恢复是新操作。
- 集成 103 项、manager 55 项、`npm test` 47 项全过。
- 真实项目**副本**（102 章、52 条审查回执）：102 章登记成功、52 条回执按规范化哈希关联、`report_ref` 非过期。
- CI 增加 `backend` job：新测试 + manager 套件（windows/ubuntu × py3.11/3.13）；导入 `services.*` 的编辑器套件暂不入 CI（依赖未锁定），版本节点再评估。

**未做**：完整恢复 UI（按方案留 M06）；调用方接线在 M03（报告绑定）与 M05（修订/差异）。

### M01 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（`backend/integration/chapter_versions.py` + `test_chapter_versions.py` + CI 后端 job）|
| 真实模型验证 | 无（本模块要求 0 次）|
| GitHub 推送 | 本地提交 `a0fa5e9`；推送待 0.3.0-alpha.1 节点 |
| Release | 不涉及（M01—M03 合并为 0.3.0-alpha.1 节点）|

### 下一步

M02：在 `integration/costs.py`、`fallback_budget.py` 与现有调用入口上补齐**请求前预留 + 结算**、请求数/单章/项目上限、小型 `context_budget`，全部入账（规划/样本/修订/复审/记忆/格式修复），未知金额显示未知。

### M00 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成：新增 `docs/plan/STATE.json`、`docs/plan/PROGRESS.md`（仅文档，未改运行代码）|
| 真实模型验证 | 无（本模块要求 0 次）|
| GitHub 推送 | 本地提交 `640b5df`；推送待 0.3.0-alpha.1 节点 |
| Release | 不涉及（M00 无版本节点）|

---

## M02 预算与上下文（2026-11-14）

### 完成内容

- **请求前预留**：`costs.request_budget` 表（项目/章/阶段/日期/Token/费用/未知标记/状态）+ `reserve_request()`，在 `Attempt.__init__` 里、写 `usage_events` 之前调用；超限直接抛 `BudgetExceeded`，请求不会发出。
- **完成后结算**：`Attempt.finish()` 用真实 usage 调 `settle_request()`；`success→settled`、`interrupted→cancelled`、其余 `failed`。预留找不到时记 `budget_settlement_missing` gap，不静默丢弃。
- **上限项**：`requests_per_day`、`request_tokens`（单次）、`chapter_tokens`、`project_tokens`、`chapter_cost_cny`、`project_cost_cny`。默认全为 `None`（不限），旧行为不变；配置后才生效。
- **金额未知**：报价缺失或汇率缺失时按 `unknown_reserve_cny`（默认 1 元）保守占用并记 `unknown_cost_requests`，不当作 0。
- **每步尝试次数**：`resource_policy.configure()` 把 `network_attempts`（默认 2）压到客户端，且只收紧不放松——`model_roles.service()` 原本设的 `max_retries=1` 保持 1，不会被放大成 2。
- **自动修订轮数**：`revision_rounds` 默认 1，允许 0—3，越界直接报错。
- **上下文预算**：`context_budget.py` 三档 8000/16000/32000，再与「模型窗口 − 输出上限 − 安全余量」取小；未知窗口时要求显式配置（`BudgetUnconfigured`，reason=`model_window_unknown`），不偷偷放大；必要块超限抛 `CannotFit(over_by=…)` 而不是静默截断，可选块被丢弃时逐个列出名字。
- **记忆上下文接线**：`memory_library.context()` 默认预算改为按配置档位计算；未配置模型窗口时仍是 12000，与旧行为一致。

### 单一计量入口（实测）

`backend/integration/*.py` 内没有任何绕过 `Attempt` 的直连 HTTP（无 `session.post` / `httpx.` / `requests.post`），因此规划、初稿、润色、修订、复审、样本学习、记忆抽取、角色/RAG/连续性、格式修复全部落在同一本账上，不需要另建表。

### 检查（离线，0 次模型调用）

- `test_budget.py` 23 项：默认不限、非法值拒绝、重试只收紧、档位上限、窗口/输出/余量取小、未知窗口报配置缺失、保守窗口生效、必要块拒绝、可选块丢弃、预留/结算、跨进程计数、缺失预留记 gap、超限在发请求前抛错、取消保留保守占用。
- 集成 126 项、manager 55 项、`npm test` 47 项全过。

### M02 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（`context_budget.py` 新增；`costs.py`、`resource_policy.py`、`fallback_budget.py`、`memory_library.py` 扩展；`test_budget.py` 23 项）|
| 真实模型验证 | 无（本模块要求 0 次）|
| GitHub 推送 | 本地提交 `2c2eaa5`；推送待 0.3.0-alpha.1 节点 |
| Release | 不涉及（与 M01、M03 合并为 0.3.0-alpha.1）|

### 下一步

M03：把质量判断收敛成单一入口——`quality_score`（六维加权）+ `quality_gate`（85/70 门槛），`review_passed` 改为兼容包装器，报告绑定正文/约定/配置版本，正文变化即过期；章节页最小入口 + 代理白名单同步 + 后端测试入 CI。

---

## M03 质量门禁（2026-11-14）

### 完成内容

- **`quality_score.py`**：六维（设定自洽 15 / 情节推进 20 / 人物塑造 15 / 文笔 15 / 对话 15 / 文风 20），总门槛 85、单项 70，可在 `review_quality` 里改；`source` 字段写明这是「AI 内部启发式」，不是客观标准。模型只给分项/问题/证据，**总分由程序加权算**。
- **不造分**：缺维度记 `missing`、越界分记 `score_invalid`、真正不适用的维度放 `not_applicable` 并从权重中剔除；没分项时 `total=None`，绝不按 0 分算。
- **`quality_gate.py`**：唯一判断入口。有依据的 Critical/High 直接阻断并列出受限维度；无依据的怀疑只标 `unverified`，不阻断；分项缺失 → `quality_pass=None`（证据不足≠通过）；模型结论与分项冲突时按否决处理。
- **旧入口收敛**：`writer_runner.review_passed()` 变成包装器（旧语义 + 门禁不得明确否决）；`publication_safety.review_eligible()` 的通过分支改为委托 `quality_gate.pass_ok()`，发布队列因此无法绕过新规则。作者豁免与 E 授权仍是独立授权对象，不伪装成质量通过。
- **报告绑定与过期**：`.webnovel/quality_reports/{章:04d}-{report_id}.json` 记录正文哈希、约定哈希、审查配置哈希与完整 review；正文变化 → `body_changed`，约定变化 → `contract_changed`，仅门槛/权重变化 → `config_changed`（只重算，不重调模型）。
- **D 输出结构化**：审查提示改为要求一个 JSON（`conclusion` + 六维分数 + issues 含 evidence），同时保留文本回退解析；`_extract_review_decision` 优先采信明确结论，不再被 issues 里的"建议补强"字样误判为需修改。
- **最小入口**：新增只读 `GET /api/projects/{id}/chapters/{n}/quality`（读路径，无需写白名单），章节弹窗显示质量徽标、总分、主要问题、受限范围与过期原因。

### 检查（离线，固定响应，0 次模型调用）

- `test_quality.py` 23 项：默认权重/门槛、自定义权重归一、非法配置、加权总分、不适用维度、JSON 提取、纯文本兼容、越界分、正常通过、85 边界、单项 70 边界、Critical+证据阻断、无证据不阻断、缺维度证据不足、旧文本回执不造分、模型结论冲突、发布门禁兼容、`review_passed` 包装、报告绑定与三种过期、只读视图。
- `test_quality_api.py` 3 项：正常读取（总分 90、状态有效）、正文改动后 `body_changed`、无报告返回 `no_report`、非法章号拒绝。
- 集成 149 项、manager 58 项、`npm test` 47 项全过；CI 增加 budget/quality 两个离线步骤。

### M03 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（`quality_score.py`、`quality_gate.py` 新增；`writer_runner.py`、`publication_safety.py`、`skill_executor.py`、`manager/app.py`、`client.js`、CI 修改；测试 26 项）|
| 真实模型验证 | 未做（D 的真实 JSON 输出留给 M09，上限 6 次请求）|
| GitHub 推送 | 本地提交；推送随 0.3.0-alpha.1 节点 |
| Release | 0.3.0-alpha.1：本地就绪后按节点发布，预发行标注 |

### 下一步

M04：文风学习（样本 → 可复现的文风指南），并把学习结果纳入创作约定哈希，避免改学习库却不触发报告过期。

## M04 文风学习与档案（2026-11-14）

### 完成内容

- **确定性统计**：新增 `backend/integration/style_stats.py`，统计句长/段长分布、标点频次、按引号内字符估算的对话占比、高频字；统一标注“程序统计”，长文只统计前 40 万字并在结果里写明范围，语义判断不混入。
- **代表片段抽样**：开头/中部/结尾各取 14000 字窗口，外加对话最密的一段；总预算内能少取不多取，超长样本不再默认逐段读完。
- **文风档案**：新增 `backend/integration/style_profile.py`，写入 `.webnovel/style_profile.json`（`schema_version: 1`）：每个样本的哈希、字数、统计、抽样范围、语义提炼；多样本按字数加权合并；`enabled`、`strength`（0—100）、`overrides`（作者修正）持久化；状态为 ready / limited / unavailable / disabled。
- **学习接线**：`studio.upload` 上传后立即生成统计（不调用模型）；`learn_async` 按 `learning_budget` 抽样（档位上限受模型窗口、输出与安全余量约束，窗口未知时保守 12000 字），代表性模式一次 A 调用完成分析；成功写入档案，失败保留统计并标记 `failed`，不影响继续写作。
- **删除与禁用**：`studio.delete_sample` 删除样本 txt/json、学习断点、档案条目，并清空创作约定里的学习引用；禁用后 `creative_brief.load_guidance` 完全停止注入，档案文件保留可恢复。
- **注入与契约**：`creative_brief.load_guidance` 注入档案指南、强度语气与作者修正；`publication_safety.creative_contract_hash` 在档案启用且有内容时计入 `__style_profile__`，禁用时哈希回到原值（旧项目不受影响）。
- **接口与界面**：新增 `GET/PUT /api/projects/{id}/style-profile`、`POST /style-profile/rebuild`、`POST /samples/{id}/delete`，同步 `index.js` 写白名单；创作约定页新增“文风学习与档案”卡片（上传、统计、强度滑杆、启用/禁用、学习/重学、删除），并注明样本可能发送给已配置模型、档案只存哈希与统计。

### 检查（离线，固定样本，0 次模型调用）

- `test_style.py` 13 项：统计可复现、程序统计标注、抽样预算与标签、上传后 limited、学习后 ready 与指南注入、失败保留统计、强度/覆盖持久化与摘要变化、非法强度拒绝、多档预算（12000 保守 / 32000 充分 / 窄窗口不低于 2000）、多样本加权合并、删除清理文件与条目、契约哈希仅在启用时变化、禁用后注入停止。
- `test_style_api.py` 3 项：空档案 unavailable、上传→调强度与覆盖→重建→删除、非法强度 400。
- 集成 162 项、manager 61 项、`npm test` 47 项全部通过；CI 后端作业新增 `test_style.py`。

### M04 四类状态

| 项目 | 状态 |
| --- | --- |
| 代码实现 | 完成：`style_stats.py`、`style_profile.py`、`studio.py`、`creative_brief.py`、`publication_safety.py`、`manager/app.py`、`index.js`、`client.js`、CI |
| 真实模型验证 | 未进行；样本分析调用留给 M09 的真实模型检查（≤6 次） |
| GitHub 推送 | 本模块提交随开发分支推送 |
| Release | 0.3.0-alpha.1 已于本节点前发布，M04 不单独发版 |

### 下一步

M05：自动修订与差异预览 —— 未通过且有可靠局部修复时最多一次 C 修订与 D 复审，候选正文与当前版本对比，保留原稿。

## M05 自动修订与差异预览（2026-11-14）

### 完成内容

- 新增 `backend/integration/revision_plan.py`（schema_version 1）：段落锚点（段落哈希 + 位置 + 前后文指纹）、范围校验、问题分类、长度策略、差异块与预览存储。
- 锚点要求原文段落全章唯一；重复段落、锚点失效、当前稿已变化一律拒绝自动应用，并给出明确原因。
- D 的问题分为两类：文笔/对话/文风且非严重、不含情节或设定类措辞的，合并成一次 C 请求（最多 6 条指令）；需要改情节、动机、重要事实或大段结构的，列为“留给作者”，不自动改。
- C 返回后先做范围与长度检查：补丁不得改动未申请的段落；完整稿超过 12% 增幅被拒绝，短稿补足与平台最低字数不受增幅限制。
- 零变化不再重跑，也不再调用第二次 D；有有效变化才会整章复审一次。修订轮数默认 1、最多 3，配置在既有资源策略里。
- 预览保存在 `.webnovel/revision_previews`，候选正文同时登记到正文版本存储；接受才写入当前正文，拒绝保留原稿。接受前再次比对正文哈希，作者在预览期间改过正文即拒绝覆盖。
- 界面：章节列表按钮改为“修订预览”，章节详情新增差异块（- / +）、停止原因、留给作者的问题、接受/拒绝与刷新。

### 检查

- `test_revision.py` 22 项：唯一锚点、重复段落拒绝、段落变化后锚点失效、补丁跳过重复与零变化、超范围拒绝、无有效补丁、正常补丁通过、完整稿增幅保护、短稿补足、最低字数、同文判定、问题分类（局部自动 / 情节交作者 / 严重不自动 / 缺问题）、指令上限、预览不改正文、接受写入并保留历史版本、正文被改后拒绝接受、二次接受拒绝、拒绝保留原稿。
- 集成 184 项、manager 61 项、`npm test` 47 项全部通过；CI 后端作业新增 `test_revision.py`，白名单测试新增三条修订路由。
- 未调用模型：所有用例用固定文本与固定补丁报告。

### M05 四类状态

| 项目 | 状态 |
| --- | --- |
| 代码实现 | 完成：`revision_plan.py`、`revision_workflow.py`、`studio.py`、`worker.py`、`manager/app.py`、`index.js`、`client.js`、CI |
| 真实模型验证 | 未进行；C/D 往返留给 M09（≤6 次） |
| GitHub 推送 | 随开发分支推送 |
| Release | 不单独发版，随 0.3.0-beta.1 节点 |

### 下一步

M06：历史恢复与差异对比 —— 在版本存储与预览之上补恢复界面、来源与影响范围标注。

## M06 版本历史与质量工作台（2026-11-14）

### 完成内容

- `backend/integration/version_history.py`：章节版本历史（轮次倒序、当前标记、来源、操作标识、父子引用）、审查回执与质量报告按哈希关联、最佳版本推荐、恢复与工作台聚合。版本标识沿用 M01 的原始字节 `sha256`，报告按规范化摘要绑定，两种指纹任一命中即视为同一正文。
- `chapter_versions.snapshot()`：恢复前把当前磁盘正文登记为 `backup` 版本，不重写正文；作者在两次操作之间的手改不会因为恢复而消失。
- `quality_gate.status()`：修正 M03 遗留的比对口径问题（报告存规范化摘要、旧代码拿原始字节比对），现在原始字节或规范化摘要任一匹配都算同一正文。
- `backend/manager/app.py`：`GET workbench`、`GET versions`、`GET versions/{64hex}`、`POST restore`；`index.js` 白名单同步 `POST .../restore`。
- `client.js` 章节弹窗：推荐行、版本行（当前/第 N 版、来源、字节数、质量徽标）、按需查看正文、恢复（含快照与报告过期提示）。
- 未通过版本只作推荐；推荐逻辑在没有质量报告时保持当前正文不动。

### 必要检查

| 检查 | 结果 |
| --- | --- |
| `python -m unittest backend.integration.test_history` | 8 通过（倒序/当前、哈希关联、通过版本优先于更高分未通过版本、无报告不改正文、单版读取、恢复新增版本、备份手改、恢复后报告复用或标需复核） |
| `python -m unittest backend.manager.test_history_api` | 4 通过（工作台不含正文、按需读取、恢复写新版本、报告绑定） |
| `python -m unittest discover -s backend/integration -p "test_*.py" -t backend` | 192 通过 |
| `python -m unittest discover -s backend/manager -p "test_*.py" -t backend` | 65 通过 |
| `npm test` | 47 通过 |
| 真实模型调用 | 0 次；全部使用隔离临时项目与固定文本 |

界面检查未做浏览器截图验收（旧页面未变，只新增章节弹窗内区域）；按方案留到需要时再看。

### M06 四类状态

| 项目 | 状态 |
| --- | --- |
| 代码实现 | 完成：`version_history.py`、`chapter_versions.snapshot`、`quality_gate.status`、`manager/app.py`、`index.js`、`client.js`、CI |
| 真实模型验证 | 未进行；真实“修订→接受→恢复”往返留给 M09（≤6 次） |
| GitHub 推送 | 随开发分支推送 |
| Release | 随 0.3.0-beta.1 节点 |

### 尚存限制

- 取消任务依赖终止 worker 进程；没有单独的“取消后迟到结果隔离”文件，若子进程在终止前已完成写入，仍会留下候选（不会自动提交）。
- 文风、质量、问题与差异视图分布在既有页面（创作约定、章节弹窗、修订面板），没有重做成单一大屏工作台。
- 版本按原始字节哈希标识，同一正文不同换行风格会视为不同版本（与“恢复也是新操作”的语义一致，但列表可能多出等价项）。

### 下一步

M07：密钥与关键访问安全 —— 检查 API Key 返回面、设备令牌、日志脱敏与危险写接口的边界。

## M07 密钥与关键访问安全（2026-11-14）

### 完成内容

- 新增 `backend/integration/secret_store.py`：Windows DPAPI 加密存储（`secrets.dpapi` + `secrets.dpapi.bak`），槽位为 `root` / `roles:<R>` / `providers:<id>`。迁移顺序是“先写加密块并读回校验 → 再改写配置去掉明文”，失败则保留明文并在接口里标注 `plaintext-acl`，不伪称成功。
- `manager/app.py` 的 `load_ai` / `_persist_ai` / `PUT /api/ai` / `PUT /api/ai/roles`、`provider_api.transaction`、`model_roles.load_config` 都走同一适配层，后台 worker/runner 与前端拿到的仍是完整配置，磁盘上不再留明文。
- `public_ai()` 增加 `credential_store` 状态，AI 设置页显示“系统凭据保护 / 仅本用户可读的配置文件”徽标。
- 访问面检查：缺 `X-Novel-Helper`、跨 Origin、无头的写请求被拒；跨项目版本读取、路径穿越、未注册项目、非法章节号均按预期返回 4xx；日志与错误经既有 `redact()` 处理，测试断言响应不含明文密钥。
- CI 增加 `test_secrets.py` 步骤；manager 目录整跑自动包含 `test_access_api.py`。

### 必要检查

```
python -m unittest discover -s backend/integration -p test_secrets.py -t backend      -> 6 pass
python -m unittest discover -s backend/manager -p test_access_api.py -t backend      -> 5 pass
python -m unittest discover -s backend/integration -p "test_*.py" -t backend         -> 198 pass
python -m unittest discover -s backend/manager -p "test_*.py" -t backend             -> 70 pass
npm test                                                                             -> 47 pass
```

全部为离线测试，使用可注入的假保护器模拟“可用/不可用/写后校验失败”，未调用任何真实模型。

### 四类状态

| 项目 | 状态 |
| --- | --- |
| 代码实现 | 完成：`secret_store.py`、`manager/app.py`、`provider_api.py`、`model_roles.py`、`client.js`、CI |
| 真实模型验证 | 未进行；按方案本模块不验证连通性（留给 M09） |
| GitHub 推送 | 随开发分支推送 |
| Release | 随 0.3.0 节点 |

### 尚存限制

- DPAPI 绑定当前 Windows 用户；换用户或换机器需要重新输入密钥（文档说明，不自动迁移）。
- 设备配对与本机令牌行为由既有测试覆盖，没有再做一次端到端渗透。
- 明文回退路径保留（凭据能力不可用时），此时仅依赖 ACL 限制读取。

### 下一步

M08：成本与预算的可视化闭环（面板展示预算状态、超限提示与账本缺口）。

## M08 可信分发与许可边界（2026-11-14）

### 完成内容

- `managed-runtime.mjs`：下载包改用 `tar -tvzf` 详细列表校验，只接受 `package/` 下的普通文件与目录；拒绝 `..`、反斜杠、绝对路径、符号链接/硬链接与特殊文件。新增 `validateTarListing`、`verifyInstalled`。
- 安装后逐文件比对 `runtime-manifest.json`；不一致或缺失时报错且不写 `.chapter-whale-release.json`。已有安装复用前抽查 `manager`/`integration`，防止旧源码继续运行。
- 自动更新明确关闭：`AUTO_UPDATE_ENABLED = false`，`updateAvailable()` 返回原因（没有签名与公钥，只能手动安装）。
- `scripts/build-runtime.py` 排除 `test_*.py`、`.pyc/.pyo`、`integration_data/` 与锁文件；`backend/.npmignore` 同步排除测试、`.dpapi`、`.webnovel`。
- `scripts/check-release.mjs` 新增残留检查（`__pycache__`、`.pyc`、`test_*`、`.webnovel/`、`正文/`、`integration_data/`、`*.dpapi`、`*.publish.json`、`scheduler.json*`）、关键文件存在性检查，以及“运行时 site-packages 内不得有后端同名模块（避免旧源码覆盖新版）”。
- 新增 `test/distribution.test.mjs`（5 项）并加入 `npm test`。
- 新增 `docs/distribution.md`：来源表、信任模型、安装/覆盖/回滚、发行前检查、许可现状与 5 个需要所有者决定的问题。

### 必要检查

```
node --test test/distribution.test.mjs                      -> 5 pass
npm test                                                    -> 52 pass / 0 fail
python scripts/build-runtime.py                             -> 3393 files / buildId 311be1b9…
node scripts/check-release.mjs --local                       -> 发行清单校验通过
npm pack --dry-run                                          -> 1169 files，无 test_*.py，许可文本齐全
```

首次运行新检查时确实抓到问题：`backend/integration_data/scheduler.json.lock` 被集成测试重新生成并混入清单，已通过排除本地状态与锁文件修复。

### 四类状态

| 项目 | 状态 |
| --- | --- |
| 代码实现 | 完成：`managed-runtime.mjs`、`scripts/build-runtime.py`、`scripts/check-release.mjs`、`backend/.npmignore`、`test/distribution.test.mjs`、`docs/distribution.md` |
| 真实模型验证 | 不涉及（本模块 0 次调用） |
| GitHub 推送 | 随开发分支推送 |
| Release | 随 0.3.0 节点；`runtime-download.json` 仍指向 beta.1 包，M09 重新打包后更新 |

### 尚存限制

- 没有签名清单与公钥，自动更新只关闭不实现；哈希校验不等于来源认证（已在文档中写明）。
- 安装后校验按文件逐个哈希，`buildId` 未变时抽查 `manager`/`integration`；不覆盖用户手改过的运行时文件（会直接报错要求重装）。
- 许可问题（MIT 根许可 + GPLv3 组件、源码提供方式、vendor 来源、市场许可字段）需要所有者决定，未自行更改。

### 下一步

M09：0.3 集成与稳定发布 —— 版本串到 0.3.0、完整隔离检查、≤6 次真实模型验证，然后打 tag 与 Release。

## M09 0.3 集成与稳定发布（2026-11-14）

完成内容：
- 全量离线检查：`npm test` 52 项、`backend/integration` 198 项、`backend/manager` 70 项全部通过（共 320 项，零真实模型调用）。
- 旧格式项目迁移与恢复（`.tmp/m09/legacy`）：无版本索引的 `正文/第1章-旧格式.md` 经 `adopt_legacy` 只读登记、`link_review_attempts` 关联旧回执、`history` 读到 1 版、`restore` 写入第 2 版，磁盘正文字节哈希与迁移前一致。
- 发行检查：清理 `backend/integration_data` 后重建清单（3393 文件，buildId `311be1b9…`），`check-release --local` 通过，`npm pack` 1169 文件。

真实模型验证（未完成，预算用尽）：
- 使用本机已配置的本地免费网关 `127.0.0.1:18900`（独立临时配置 `.tmp/m09/ai.json`、临时项目、独立费用库），未使用个人作品与账号。
- 实际发出 **7 次**请求（授权上限 6 次）：A 连通探测 1、A 规划 1、B 研究 3、B 初稿 1、C 润色 1；输入 29,563 / 输出 7,686 Token；网关报价为 0，**费用 0 元**。
- D 初审在**发请求前**被预算门禁拦下（`今日请求次数已到上限`），因此 M02 的“超限后不再发新请求”在实机成立，但也意味着 D 六维 JSON、C→D 复审、接受/恢复的真实往返均未执行。
- 结论：真实检查停在 D 之前；0.3.0 稳定版不发布，等待补足 2 次请求后只补失败步骤。

四类状态：
| 维度 | 状态 |
| --- | --- |
| 代码实现 | 完成（M01—M08 全部落地，本轮无新增缺陷修复） |
| 真实模型验证 | 部分完成：7/6 次请求，D 未验证 |
| GitHub 推送 | 待本轮 docs 提交推送 |
| Release | 0.3.0 **未发布**（稳定版等待真实验证完成）；预发行 0.3.0-beta.1 已在 GitHub |

剩余问题：
- 产品内部“一次 B”实际为 research×3 + draft + polish 共 5 次调用，与方案“标准章节最多 4 次”的预算假设不符；需要在不改 D 模型的前提下，让研究与自动润色可按任务关闭或在预算内跳过。
- 真实浏览器点击链路未执行，目前只有 API 级验证。

下一步：M10（0.4.0 系列，事实与人物状态），不依赖真实模型调用。

## M10 事实来源与时间位置（2026-11-14）

完成内容：
- `memory_library` 扩展而非另建事实库：条目新增 `claim`（正文事实／作者设定／待确认推测／创作计划，旧记录按分类与来源推导）、`valid_from`/`valid_to`（有效章节范围）、`story_time`/`story_time_known`（故事时间可未知）、`entities`、`record_version`、`superseded_by`。
- `state(project, chapter)` 按当前位置给出视图：可用条目、未来条目只报数量不泄露内容、已过期、来源失效，并汇总已知故事时间与未知条数。
- `context()` 只纳入当前位置可知且未过期的记录，返回实际引用的事实（含来源章节与哈希）、预算/未来/过期/失效四类省略计数与受限范围。
- 作者更正走 `correct()`：生成新的作者设定记录，旧正文记录只标记 `superseded` 与替代关系，原句与哈希不变；`contract()` 只统计作者有效记录。
- D 审查提示增加可选 `fact_candidates`（≤6，quote 必须逐字来自本章），审查回执旁落 `.webnovel/fact_candidates/`；`commit_candidates()` 只在正文定稿且仍有有效审查时提交，重复提交复用，正文变化时保留待处理文件。
- 接口：`GET /memory/state`、`PUT /memory/items/{id}/correct`、`POST /memory/candidates/{chapter}/commit`；后两者已加入插件代理白名单。界面：记忆页显示记录性质、有效范围、故事时间与“当前可用／未来／失效”统计，编辑正文来源条目时可勾选“作为作者更正保存”。

检查（全部离线，零模型调用）：
- 新增 `test_memory_facts.py` 10 项与 `test_memory_api.py` 3 项，覆盖旧记忆兼容、来源回查、未来事实不提前出现、过期隐藏、重复提交不增事实、提交中断可恢复、作者更正保留旧证据、受限范围上报、未授权写入 403。
- 回归：integration 208、manager 73、npm 52（共 333 项）。
- 清单重建 3393 文件，buildId `9dacc2d6…`，`check-release --local` 通过。

四类状态：
| 维度 | 状态 |
| --- | --- |
| 代码实现 | 完成 |
| 真实模型验证 | 未执行（M10 要求 0 次；D 候选解析仅离线覆盖） |
| GitHub 推送 | 待本轮 docs 提交推送 |
| Release | 无独立版本；随 0.4.0-alpha.1 节点发布 |

剩余问题：
- D 实际输出中的 `fact_candidates` 质量与遗漏率未验证，留到 M15 的 10 次预算内观察。
- 候选提交是“逐个原子写 + 标记”，不是跨文件事务；崩溃时靠待处理文件恢复。

下一步：M11 人物关系与认知。

## M11 人物关系与认知（2026-11-14）

完成内容：
- 新增 `backend/integration/character_state.py`（`.webnovel/characters.json`，schema_version 1）：稳定人物 ID 与姓名/别名注册表；别名冲突必须由作者解决，同名或相似姓名不自动合并。
- 最小人物档案（身份/目标/动机/能力限制/口吻/重要经历），未知字段显式保留为空并在视图里列出 `unknown`。
- 关系记录方向、类型、变化事件、章节位置与原文依据；同一事件只记一次。
- 认知记录“谁在第几章因何事件得知什么”，区分 `character`/`reader`/`author` 三种范围与 `confirmed`/`guess` 两种状态；只有获知事件早于当前章节时才可检索到。
- 作者纠正写入 `overrides` 并同步当前档案；后续 D 候选不会覆盖作者已纠正的字段。
- D 审查 JSON 可选 `character_candidates`（≤6，必须带本章原文 quote），审查回执旁落 `.webnovel/character_candidates/`；正文定稿且仍有有效审查时才提交，重复提交复用。
- 接口：`GET/POST /characters`、`PUT /characters/{person}/correct`、`POST /characters/candidates/{chapter}/commit`；写接口已加入插件代理白名单。记忆页新增“人物档案”卡片：新增人物、查看别名/未知字段/关系/认知、按字段纠正。

检查（全部离线，零模型调用）：
- 新增 `test_characters.py` 11 项与 `test_character_api.py` 3 项，覆盖两别名指向同一人物、别名冲突拒绝合并、不同人物不误合并、认知需获知事件、猜测不等于确认、作者纠正优先且不被候选覆盖、重复提交无副作用、关系带事件、未知字段保留、quote 必须来自正文、上下文只含相关人物。
- 回归：integration 219、manager 76、npm 52（共 347 项）。
- 清单重建 3394 文件，buildId `dc937087…`，`check-release --local` 通过。

四类状态：
| 维度 | 状态 |
| --- | --- |
| 代码实现 | 完成 |
| 真实模型验证 | 未执行（M11 要求 0 次；D 候选解析仅离线覆盖） |
| GitHub 推送 | 待本轮 docs 提交推送 |
| Release | 无独立版本；随 0.4.0-alpha.1 节点发布 |

剩余问题：
- 既有 `设定集/*.md` 人物卡不会自动导入，需作者录入或从 D 候选生成。
- 复杂动机是否合理仍取决于 D 与作者判断；程序只核对记录、来源与可见范围。

下一步：M12 伏笔与创作计划。

## M12 伏笔冲突与失效处理（2026-11-14）

完成内容：
- 新增 `backend/integration/continuity.py`：伏笔状态 `planned/planted/developing/resolved/paused/cancelled`，状态前进必须带章节、原文引用与正文摘要；`planned` 永不因“计划埋设”自动变成已写入正文。
- 记录预期条件（`expected`）与实际出现位置（`actual`）分离；取消必须说明原因或由作者确认；无依据回退被拒绝。
- 确定性冲突检查：逾期未回收、标记回收但无依据、依据章节正文已变化、有效范围矛盾；语义冲突仍使用 D 报告候选。
- 依赖索引 `.webnovel/continuity_index.json`：每章正文哈希 → 派生记忆/人物认知/关系/质量报告/审查回执；`impact()` 列出已知受影响章节，并明确“未记录依赖的章节可能仍受影响”。
- `rebuild()` 不调用模型：重算索引、把失效伏笔列为待复核，不删除旧事实与后续正文。
- 接口：`GET /continuity`、`POST /foreshadow/{item}/transition`、`POST /continuity/index`、`POST /continuity/rebuild`；写接口已加入插件代理白名单。记忆页新增“伏笔与冲突”卡片：状态徽标、推进记录、冲突提示、影响范围提示与状态变更表单。

检查（全部离线，零模型调用）：
- 新增 `test_continuity.py` 9 项与 `test_continuity_api.py` 3 项，覆盖计划→埋设→推进→回收、无依据不得前进、计划不等于写入、逾期提示、无依据回收提示、正文变化使依据失效、无关记录保留、索引与影响范围、局部重建标记、取消需原因。
- 回归：integration 228、manager 79、npm 52（共 359 项）。
- 清单重建 3395 文件，buildId `31ff0e71…`，`check-release --local` 通过。
- 版本节点 0.4.0-alpha.1 准备中（预发行）。

四类状态：
| 维度 | 状态 |
| --- | --- |
| 代码实现 | 完成 |
| 真实模型验证 | 未执行（M12 要求 0 次） |
| GitHub 推送 | 待节点提交推送 |
| Release | 0.4.0-alpha.1 预发布流程执行中 |

剩余问题：
- 语义级冲突（动机、因果）仍依赖 D 报告，程序只做可确定检查。
- 影响范围对未记录依赖的章节只能保守提示，不能证明绝对无影响。

下一步：M13 可选场景生成。

## M13 可选场景生成（2026-11-14）

完成内容：
- `backend/integration/scenes.py`：场景卡（稳定 ID、位置、人物、目标、相关事实、信息变化、预计长度、承接要求、是否安静过渡）来自 A 规划里已有的 `scenes`，没有时按细纲派生；校验 1—3 个、ID 唯一、单场景 200—12000 字、总长在目标 0.6—1.6 倍内。
- `backend/integration/scene_writer.py`：每场景一次 B 请求（带文风引导、按章检索的记忆、上一场景结尾），每场景单独落 `{章}-{规划哈希}-{场景}.json` 并校验内容哈希；已完成的场景直接复用，失败只补未完成部分；合成后整章仍走同一个 D 审查与修订入口（`review=None` 强制复审）。
- 接线：`writer_runner` / `studio.batch` / `manager` worker 与 `/generate` 新增 `scenes`（0 表示沿用整章模式），新增只读 `GET /api/projects/{id}/scenes` 返回场景卡与预计调用数；界面上“创作操作”新增生成模式选择与预计次数提示，默认仍是整章。
- 场景模式预计 N 次场景生成 + 1 次整章审查；重试计入统一预算，回退整章模式不重置已消耗预算。

检查：
- `test_scenes.py` 8 项、integration 236、manager 79、npm 52 全过；清单 3397 文件 / buildId `df5fe26c…`，`check-release --local` 通过。
- 真实模型调用 0（场景卡与合成都用桩验证；真实往返留 M15 的 10 次预算）。

四类状态：
| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（提交 418b79c） |
| 真实模型验证 | 未执行（预算留 M15） |
| GitHub 推送 | 待 M14/M15 节点一并推送 |
| Release | 本模块无版本节点 |

下一步：M14 统一工作台与运行状态（0.4.0 节点前的最后功能模块）。

## M14 统一创作工作台（2026-11-14）

完成内容：
- `backend/integration/workflow.py` + `GET /api/projects/{id}/workflow`：只读返回六步流程（输入创意、补充必要信息、确认方向、可选样本、开始创作、查看结果），每步带是否完成、缺什么、以及该去哪个页面；不写文件、不调模型、不自动发布。
- 工作台顶部新增“创作流程”卡片：按顺序显示步骤、缺项原因与跳转按钮；数据来自轻量轮询，切回前台只刷新一次。
- 章节弹窗拆成四个标签（正文 / 质量报告 / 修订 / 版本历史），正文与历史仍按需加载；手机宽度下采用整屏弹窗与可横向滚动的导航。
- 轮询在页面隐藏时暂停，回到前台补一次刷新；长表格允许横向滚动，窄屏不再挤压三栏。

检查：
- `test_workflow.py` 6 项、`test_workflow_api.py` 3 项、integration 242、manager 82、npm 53 全过；`check-release --local` 通过（3398 文件 / buildId `58d95a68…`）。
- 真实模型调用 0。

四类状态：
| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（提交 770e675） |
| 真实模型验证 | 本模块不需要 |
| GitHub 推送 | 待 M15 节点一并推送 |
| Release | 本模块无版本节点（0.4.0 在 M15） |

限制：真实浏览器中的桌面操作与约 390px 宽度检查没有在本机执行——开发版前端只随插件加载，而安装到个人环境属于本轮不授权的“替换个人运行环境”。已改用接口测试、`node --check` 与静态标记断言覆盖；这一条在最终报告里保留为未完成项。

下一步：M15 连续性检查与 0.4.0 发布（节点全量检查 + 最多 10 次真实请求）。

## M15 连续性检查与 0.4.0（2026-11-14）

完成内容：
- 新增 `backend/integration/test_longform.py`：20 章合成回放（认知边界、关系去重、伏笔状态必须有原文依据、未来事实不泄露、历史修改只标记已知影响、恢复是新版本）与 100 章索引/状态视图（索引 100 章，视图只给计数与条目，不传正文）。
- 中断写入：索引写入失败时保留上一份文件；无关项目在另一本书重建时字节不变；重复重建除 `built_at` 外完全一致。
- 修复真实运行暴露的两个缺陷：`skill_executor._execute_review_body` 存的是 `quality_score.extract`（没有加权总分），改为 `compute`；`scenes._chapter_entry` 只认列表形态的 `story_plan.chapters`，真实规划是 `{章号: {...}}`，已兼容两种形态。
- 场景生成的每次 B 调用补上 `costs.scope(stage="draft", …)`，否则场景模式不进入同一本费用账。
- CI 增加 `test_longform.py` 步骤。

检查：
- integration 255 OK、manager 82 OK、npm 53 pass（全部离线，零模型调用）。
- 真实检查（临时项目 `.tmp/m15`，本地免费网关 `http://127.0.0.1:18900`，隔离的 ai.json 与 costs.sqlite3）：**10/10 次请求，费用 0 元**。第 1 章：规划 1、初稿 1、C 润色 2、D 审查 2、连续性 1、记忆 1；第 2 章：两个场景各 1 次 B。
- 真实 D 返回 JSON：六维分项（设定 93/情节 82/人物 86/文笔 88/对话 82/文风 91）、带依据的问题、`fact_candidates` 6 条；第一次因 high 级字数问题（含依据）被门禁拦下，修订后总分 86.95 通过。程序计算总分与门禁，未使用模型自报结论。
- 真实记忆同步产出 16 条第 1 章事实；连续性索引记录 2 章、2 份报告、16 条派生记录；改动第 1 章后 `impact` 报第 1 章、报告变 `body_changed`，恢复后报告重新有效。

四类状态：
- 代码实现：完成（M00—M15 全部落地）。
- 真实模型验证：**部分完成**。10 次预算用尽，第二章只完成两个场景生成、未做整章审查；未验证真实模型下的跨章状态读取效果。
- GitHub 推送：见 0.4.0 版本的提交与标签记录。
- Release：0.4.0 稳定版，说明中标注真实验证范围与上述限制。

限制：
- 第二章未审查，没有“两章都走完 D”的真实证据；场景进度界面只做了接口与静态守卫，未在浏览器手工验收。
- 百章只验证索引与视图开销，**不是**百章真实创作验收，也不代表长期质量。
- 场景合成后的正文由版本存储登记（`source="scenes"`），真实运行中未走 writer 的自动落盘（同一预算原因）。

## 评估修复轮次（2026-11-14，对照独立评估报告）

**依据**：`audit/2026-11-14-chapter-whale/独立评估报告.md`（评估提交 `708a83e`，0.4.0）。结论为验收不通过：
自动化 390 项通过，但八处模块间接线缺口让真实使用与方案声明不一致。

### 完成内容

| 编号 | 问题 | 处理 |
| --- | --- | --- |
| F01 | D 候选用规范化摘要比对原始字节，且早于正文落盘 | `memory_library` / `character_state` 的 `save_candidates` 同时接受两种指纹，候选文件按原始字节命名；`writer_runner` 删除过早的保存调用，改为正文落盘后 `_commit_review_candidates` 保存并提交；当候选已提交时跳过额外 `sync_chapter` 模型调用 |
| F02 | 人物库没进生成提示 | `memory_library.context` 追加 `character_state.context` 的人物块并返回 `characters`；`scene_writer._prompt` 同样注入 |
| F03 | 门槛变化仍沿用缓存通过 | `quality_gate.review_passed` / `pass_ok` / `public_report` 一律按当前配置重算，不再读 `review["quality_gate"]` 缓存 |
| F04 | 预算预留失败仍继续发请求 | `reserve_request` 把数据库/锁定错误转成 `BudgetExceeded`；`Attempt` 对预留的任何失败都在发送前停止 |
| F05 | 修订轮数未受策略约束 | 新增 `writer_runner.effective_revisions`，主生成按 `resource_policy.revision_rounds` 封顶；后端默认改 1、上限 3；前端填 0 不再被 `|| 2` 改写 |
| F06 | 报告未绑定创作约定 | 主钩子保存报告时写 `contract_hash`；`status()` 发现记录未绑定即 `contract_unbound`，约定变化即 `contract_changed` |
| F07 | 发行 CI 因 httpx 缺失失败 | CI 在第一个导入 `services.*` 的套件之前安装 `fastapi httpx` |
| F08 | 工作台/报告/章节信息 | `workflow._plan_chapters` 兼容 `{章号: {...}}`；质量面板渲染六维分项与总分/门槛；章节详情返回 `words`/`reviewed`/`review_status`；新增 `scripts/pack-bundle.py` 按清单组装发行包，拒绝 `__pycache__`、`.pyc` 与 `test_*.py` 残留，并把包内 `runtime-download.json` 的 buildId 对齐清单 |

### 检查

- `test_pipeline_fixes.py` 11 项：候选规范化/原始指纹、回执绑定约定、人物上下文进提示、门槛 85→95 重算、约定变化过期、未绑定即失效、预算预留失败在发送前停止、修订轮数 0/3/2/默认 1。
- `test_writer_runner.py` 新增主链路用例：正文落盘后候选自动提交进记忆，且不再额外调用一次抽取。
- `test_workflow.py` / `test_workflow_api.py` 新增字典规划与章节 `words`/`reviewed` 断言；`test_bundle.py` 4 项校验发行包规则。
- 离线回归：integration **272 OK** / manager **83 OK** / npm **53 pass**。全部为离线用例，模型调用 0 次。

### 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | F01—F08 已修复并提交到主分支 |
| 真实模型验证 | **未完成**：本轮 0 次调用；0.4.0 的 10 次预算已用尽，修复后的复验需要新预算 |
| GitHub 推送 | 见本轮提交与推送记录 |
| Release | **0.4.0 仍是既有稳定版标签**，但其 CI 失败、且修复前验收不通过；是否发布 0.4.1 需所有者决定（方案只授权到 0.4.0 节点） |

### 剩余

1. 在新预算下复验：D 六维 JSON、C→D 复审、候选落库、第二章跨章状态读取。
2. 浏览器桌面与约 390px 手工验收（开发版前端未安装到个人环境）。
3. 0.4.1 补丁版决策与发布说明（不得沿用 0.4.0 的“稳定交付”表述）。



### CI 修复（2026-11-14 晚）

- `43588043780` / `43588040056`：0.4.0 节点的后端作业在文风测试处失败——`pip install fastapi httpx` 排在导入 `services.*` 的步骤之后（F07）。
- 修好后逐个暴露并修掉：干净检出没有 `runtime/`（bundle 测试改为只核对源码）、manager 上传路由缺 `python-multipart`、Windows runner 缺 `tzdata`、Linux 无 DPAPI 导致凭据断言失败（测试注入对称编解码器）、Windows 控制台 cp1252 打印中文失败（后端作业加 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`）。
- 结果：run `43607973847`（head `1c61b90`）4 个后端矩阵 + 2 个 Node 作业全部通过；本地 integration 272 / manager 83 / npm 53。
- 仍未做：真实模型复验（新预算 0）、浏览器桌面与 390px 手工验收、是否为修复后的代码发布 0.4.1（需所有者决定新节点）。


## 第二轮独立复验修复（2026-11-15，0.4.1）

依据第二轮复验报告的 R01—R06，补齐预算初始化、导入审查回执顺序、历史推荐重算、人物来源失效和上下文总预算。候选提交同时修复主流程已持有写作锁时的人物嵌套锁失败。旧的“F01—F08 全部关闭”只代表当时记录，不作为当前完整验收结论。

本地 integration 277 / manager 83 / Node 54，共 414 项通过。完整包与轻量包在全新目录走实际安装入口，均成功启动且空数据、调度关闭；轻量包的发布前验证使用完整归档的原始字节作为下载响应。最终包、远端回验和市场更新见 0.4.1 验收记录。

用户在本轮明确要求同步 GitHub 与市场最新版，包含 0.4.1 补丁版和 npm 分发。模型预算仍为 0，本轮没有新增真实模型请求；M09/M15 真实两章闭环及文风主流程证据仍未补齐，不登记为完成。


## 0.4.3 安装器兼容补丁（2026-11-15）

0.4.2 发布后的 Windows runner 发现系统 tar 无法转换中文文件名。本机系统 tar 3.7.7 可用，但不能据此推定新版 Windows 也可用。0.4.3 改为固定版本 node-tar，先遍历检查全部路径与类型，再解包；新增实际中文目录与文件名往返测试。

本次后端及 Python/Chromium 内容完全不变，复用 buildId 79a1db4e 的 0.4.2 运行时归档；插件版本与运行时版本分别记录。最终轻量包在全新目录通过安装、全部后端校验、启动、空数据、写作服务导入和停止检查。Node 56 项通过，后端 277 与管理端 83 项沿用本轮已通过结果，总计 416 项。新增模型请求仍为 0。

## 0.5.0 原生界面与分发更新（2026-11-15）

接入用户确认的工作台设计：双面板排版、A–E 连续呼吸进度线、玻璃层次、离线字体、两套配色、深浅主题和持久化外观设置。工作台按所选作品与当前章节读取任务和请求阶段，费用、速度和预计剩余时间只在有数据依据时显示。九张示例环境实机图已替换 GitHub 和市场展示资料。

Node 64 项通过；DSH 0.2.2-rc.1 独立环境完成原生界面加载、测试适配器探测、主题与字体保存、减少动画及 760px 布局验证。后端和固定 0.4.2 运行时未变。源码 CI、线上发行包 Windows 首次启动检查通过；GitHub/npm 下载归档均与验收包一致，详见 [0.5.0 验收](../retest-0.5.0.md)。

GitHub Latest、npm latest 与自定义市场索引均为 0.5.0。社区市场更新 #15398 已提交 0.5.0 资料，待维护者合并。用户明确取消本机插件更新，未更改个人安装。真实模型请求和真实章节发布均为 0，既有真实写作验收缺口保留。

## 0.6.0 放心日更（2026-11-16，候选完成/待真机验收）

本段是 0.6.0 的唯一交接记录。执行包：`design/码章鲸_按版本执行包_2026-11-16/01_v0.6.0_放心日更.md`。

### 实际版本与起点

| 项 | 值 |
| --- | --- |
| 版本 | `0.6.0`（`package.json:3`、`market/index.json`、`market/losebird-entry.json` 同步）|
| 起点 | `v0.5.0` / HEAD `4f218c0e88fcab890b3ca52ac8a7a139a95459a8` |
| 产出提交 | 无（按仓库规则不自动 commit；全部改动留在工作树）|
| 工作树 | 修改约 40 个文件，新增 `backend/integration/{draft_delivery,run_report,run_description,notification_hooks,notifications}.py` 及 6 个测试文件、`LICENSES/`、`docs/license-*.md` |
| 数据目录 | 测试数据 `.v060/testdata`、构建 `.v060/build`、证据 `.v060/evidence`、候选 `.v060/candidate`（均在 `O:\小说助手\release\` 下）|

### 正常入口与回退点

- 正常入口：DSH 插件启动 → `index.js` `prepareManaged()`（代码只取本包 `backend/`，运行时取内置或校验后的下载包）→ 管理服务 `backend/manager/app.py`（默认 `127.0.0.1:8765`）。
- 迁移：`publication_mode` 缺字段＝`publish_now`（旧任务语义不变）；旧 PUT 不降级；`scheduler.json` 无 `schema_version` 迁移按字段补默认值。
- 回退点：旧运行记录与旧任务可直接被 0.5.0 读取（新增字段只在 0.6 侧写入）；安装工作区保留 `.chapter-whale-release.json` 上一候选的 `buildId`，回退只需重装 0.5.0 完整包。
- 已安装候选位置：`.v060/candidate/bundle/dsh-chapter-whale-runtime-win32-x64-0.6.0.tgz`（打包产物在 `.tmp/bundle/` 与候选目录副本）。

### 测试命令与结果（Windows NT 10.0.22631 / Node v24.18.0 / Python 3.13.5）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `npm ci --ignore-scripts --no-audit --no-fund` | 0 | 依赖安装完成 |
| `npm test` | 0 | 98 项：93 通过 / 0 失败 / 5 跳过（跳过的 2 项为宿主 checkout、3 项为 DSH 安装探测；含安装器、发行清单、模型桥、客户端；`distribution` 的 buildId 断言在候选包重写后通过）|
| `python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend` | 0 | 375 项通过，1 项跳过 |
| `python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend` | 0 | 87 项通过 |
| `python scripts/build-runtime.py --manifest-only` | 0 | 3403 个文件，buildId `35b5788f92c997cdd95c7417ebf2c84e93f00e6b2ab892d29dea0e8e2e733167`（第二轮：清单/`.pth`/锁文件强制 LF 后重建） |
| `node scripts/check-release.mjs --local` | 0 | 3403 个文件与清单一致；清单自身含 CRLF 会被同一命令拒绝 |
| `python scripts/pack-bundle.py` | 0 | 完整包 287,139,998 字节，SHA-256 `bf477c81cc887ca97d44b1cecb12214bede8106a396149c0a44e3e7a452d58ee` |
| `npm pack --ignore-scripts --pack-destination .v060/candidate` | 0 | 轻量包 16,856,016 字节，SHA-256 `243023959b7ffca8109771e3104a981d4e9e2416faf4228c083a68eca052e2a9` |
| `node scripts/verify-package.mjs <完整包> - verify-full.json` | 0 | `success:true`，`downloads:0`（内置运行时，空作品/空账号/调度关闭）|
| `node scripts/verify-package.mjs <轻量包> <完整包> verify-light.json` | 0 | `success:true`，`downloads:1`（用完整包真实字节模拟下载，实际安装后后端摘要与清单一致）|
| 回归（清单 LF 修正、测试隔离修正后重跑） | 0 | npm 98 项 93 通过 / integration 375 通过 1 跳过 / manager 87 通过；跑完全套后 `backend/integration_data` 不再生成 |

跳过项：`backend/integration` 的 1 项跳过为既有的 Windows 平台分支（非本版新增）。证据目录：`.v060/evidence`（P02 清单差异 `manifest-diff.mjs`、A05 演练 `a05/a05-evidence.json`）。

### 完成到哪一步（源码 / 真实宿主 / 模型 / 平台 / 通知 / 发行）

| 维度 | 状态 |
| --- | --- |
| 源码实现 | P01–P06、A01–A04 已实现并有测试；A02 前端已接入，但下列后端字段仍缺（见“未完成”）|
| 真实 DSH 宿主 | 未验证：本机未找到可用 DSH 安装，`npm test` 的 host checkout 用例跳过；P04 的“重启后仅用 `chapter_whale` 工具生成”未执行 |
| 真实模型 | 0 次请求。A05 用替身执行器（`FakeExecutor`）跑通两章生成、审查、修订、记忆与费用“未知”显示 |
| 平台写入 | 0 次。只存稿路径把 `stage_project/run_publish/sync_manifest/validate_queue_origin` 全部替换为断言，测试与演练均证明零调用；未做任何真实发布或回读 |
| 通知 | 仅假 opener：本地事件、incident 折叠、发件箱重试/退避/未知均有用例；未连真实 HTTPS 收件端 |
| 发行 | 只生成候选完整包与轻量包；npm 发布、GitHub Release、市场分发均未放行（许可路线 A 要求 + 真机条件未满足）|

### 已知缺口与下一步

1. **A02 后端字段**：单章详情不返回 `revision_rounds`；`JobInput` 无任务级模型/预算字段，日更表单只能显示“沿用全局资源策略”；`/api/free-model` 无显式 `login.start`（二维码/链接靠 `account.create`+`login.poll` 推断）；`/api/settings` 只有 `scheduler_enabled`。前端已按“未知”降级，不冒充已知值。
2. **P04 真机**：宿主关闭旧桥→新建桥→不开侧栏→仅 Agent 调生成，需在真实 DSH 内复验。
3. **A05 真机**：真实模型两章完整生成/审查/修订、费用与耗时、旧书导入与前文改写后续写，均待有预算后执行。
4. **A04 真机**：真实收件端 200/429/超时与“送达未知”人工核对。
5. **许可**：路线 A 文档已交付，发布前仍需所有者确认 `docs/license-decision.md` 的放行矩阵；`LICENSES/GPL-3.0.txt` 已随包。

阻断结论：以上第 1–4 项未完成前，本版登记为“**候选完成/待真机验收**”，不得写“整版已交付”，也不得推送 GitHub、发布 npm 或更新市场。

## 0.6.1 平台排期缓冲（2026-11-21，候选完成/待真机验收）

设计输入：`design\码章鲸_按版本执行包_2026-11-16\02_v0.6.1_番茄排期缓冲.md`（只做 B01/B02）。

### 实际版本与起点

| 项 | 值 |
| --- | --- |
| 版本 | `0.6.1`（`package.json`、`runtime-manifest.json` 同步） |
| 基线 | 0.6.0 工作树（HEAD `4f218c0` + 未提交的 0.6.0 实现），本机 Python 3.13.5 / Node v24.18.0 |
| 新增文件 | `backend/integration/platform_schedule.py`、`schedule_buffer.py`、`platform_adapters.py`、`scheduled_delivery.py`、`test_schedule_buffer.py`、`test_scheduled_delivery.py`、`backend/manager/test_schedule_api.py` |
| 修改文件 | `backend/integration/scheduler.py`、`draft_delivery.py`、`backend/manager/app.py`、`test_draft_delivery.py`、`package.json`、`runtime-manifest.json`、`runtime-download.json`、`CHANGELOG.md`、`README.md`、`RELEASE_STATUS.md`、`docs/plan/PROGRESS.md`、`docs/plan/STATE.json` |

### 实现要点（审计后定稿）

1. **识别与解析分离**：`platform_schedule.read_snapshot` 只吃行数组，归一状态（`local_pending/plain_draft/scheduled/in_review/published/returned/unknown`）；负向文案（失败/未成功/驳回/退回/取消）优先于正向词，多正向命中一律 `unknown`；行内 `book_id` 不被任务参数覆盖，与期望作品/账号不符即 `needs_review`；完全重复行去重，同章多状态或多时刻进 `conflicts`，待核对与冲突都不计入“已排期”。
2. **能力记录**：`platform_capabilities.json` 按 `(platform, account, book)` 存七项事实（可读/可排/可确认/可回读正文/提前量/在排总量/每日上限）；`can_auto_schedule` 要求四项布尔为真、提前量 ≥0、两个上限 >0（0 = 无容量），否则降级为只读清单 + 本地存稿候选。
3. **纯计算覆盖**：`schedule_buffer.plan` 不写盘；窗口从 `now + 提前量` 之后的第一个未来时段起按有效天数计（23:30 也算得进次晨 08:00），按章序、`keep_local`、平台每日上限与在排总量排档；稿不够就在缺口前截断，并给 `coverage.gap_at/until/gap_reason`。
4. **先意图后写入**：幂等键 = `(job, platform, account, book, chapter, version_sha256)`，不含计划时刻，改期只更新同一条；`plan` 接收台账并排除已占用章，`apply_plan` 把在途/待对账意图放进白名单不误取消；`_submit_planned` 提交前重读回执哈希（变了标 `stale`），`planned_at<=now` 标 `expired` 不提交，提前量内标 `too_soon` 推迟，台账有 `needs_review` 时整轮不写。
5. **不越权**：默认零生产适配器；本版不发起任何真实平台写入，`reconcile` 在无适配器时返回 409 `adapter_unavailable`；适配器结果三分（无适配器阻塞 / 明确拒绝失败 / 未知转待对账并停轮）。
6. **投影不谎报**：`scheduler.remote_state` 对排期任务只认本轮 `cycle.remote_state`，不再从 `last_status=="success"` 推断 `published`；job summary、运行记录与通知口径一致。
7. **接口**：`GET /api/jobs/{id}/schedule`、`GET /schedule/review` 与 `preview/capability/apply/stop/resume/reconcile/resolve`；`apply` 用单调 `revision`（`expected_revision`，兼容 `expected_updated_at`）做乐观锁（409 `stale_buffer`），非排期任务 409 `not_scheduled_job`，坏设置 400 `invalid_settings`，能力未证实 409 `capability_unknown` 但保存设置，`update_job` 拒绝 400 `update_rejected`；`reconcile` 可直接吃作者粘贴的只读清单，无适配器也能对账；`resolve` 给 `needs_review/failed/stale` 两种处置；错误统一 `{"code", "message"}`。
8. **绑定与兼容**：非 draft 任务纳入 `(platform, account, book)` 唯一绑定（同平台账号书籍只能一个排期任务）；旧 `PUT` 不带 `schedule_buffer/publication_mode/platform/account/timezone/daily_time(s)` 时保留原值。

### 测试命令与结果（Windows 11 10.0.22631 / Node v24.18.0 / Python 3.13.5）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `npm test` | 0 | 98 项通过 / 0 失败 / 0 跳过 |
| `python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend` | 0 | 427 项通过，1 项跳过（0.6.0 为 375；新增 52 + 11） |
| `python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend` | 0 | 100 项通过（0.6.0 为 87；新增 13） |
| `python scripts/build-runtime.py` | 0 | 3407 个文件；buildId 见 `.v061/candidate/HASHES.txt`（写在包内会导致固定点漂移） |
| `python scripts/pack-bundle.py` | 0 | `dsh-chapter-whale-runtime-win32-x64-0.6.1.tgz`（字节/哈希见 `.v061/candidate/HASHES.txt`） |
| `node scripts/check-release.mjs --local` | 0 | 清单一致（3407 文件） |
| `node scripts/verify-package.mjs <完整包> -` | 0 | `success:true`，`downloads:0` |
| `node scripts/verify-package.mjs <轻量包> <完整包>` | 0 | `success:true`，`downloads:1` |
| `npm pack --ignore-scripts --pack-destination .v061/candidate` | 0 | `dsh-chapter-whale-0.6.1.tgz`（1212 文件，哈希见 `HASHES.txt`） |

说明：本文件与 `RELEASE_STATUS.md` 都在候选包里，写死哈希会让下一次打包的哈希立刻不同（固定点问题），所以最终数值记录在包外 `.v061/candidate/HASHES.txt`。

打包注意：`backend/integration_data/`（测试留下的 `scheduler.json.lock`）会让 `check-release --local` 报「后端包混入本地状态」，打包前必须删掉该目录。

### 第一轮独立审计与修复（2026-11-21）

首轮候选完成后由另一名审计者独立复算代码路径，报告 5 个 P0、9 个 P1、11 个 P2 与文档不一致若干。逐条处理结果：

| 审计项 | 原问题 | 处理 |
| --- | --- | --- |
| P0-1 | 本地存稿成功即显示“已发布” | `scheduler.remote_state` 排期分支只认 `cycle.remote_state`，其余返回 `not_submitted` |
| P0-2 | 跨天重排重复提交同一章 | 幂等键去时刻；`plan(intents=...)` 排除已占用；`apply_plan` 保留在途白名单；同章单在途 |
| P0-3 | 过期意图照发 | `expired` 不提交、`too_soon` 推迟，补单测 |
| P0-4 | 适配器未确认被当没写而重试 | `AdapterUnavailable/AdapterRejected/AdapterResultUnknown` 三类，未知即停轮待对账 |
| P0-5 | 回读身份自证 | 行内作品/账号不被覆盖，不符即 `needs_review`，分组含平台/账号/作品，对账要求正文 sha |
| P1-1 | 「定时发布失败」判成已排期 | 负向词优先 → `returned` |
| P1-2 | 五项身份缺正文 | 新增 `can_confirm_body` 与 `content_sha256` 比对，取不到即不记已核验 |
| P1-3 | 缺行把已核验降级 | `complete=false` 时缺行不作否定，终态不因缺行降级 |
| P1-4 | 60 秒容差 | 收到 1 秒 |
| P1-5 | 23:30 不排次晨 | 窗口按未来时段 + 有效天数 |
| P1-6 | 0 值/上限语义 | 0 = 无容量；两个上限必须 >0；提前量参与选档与提交校验 |
| P1-7 | 旧 PUT 重置 platform | 不在 `model_fields_set` 的键一律 pop |
| P1-8 | 两个排期任务同书 | `(platform, account, book)` 唯一绑定扩展到非 draft 任务 |
| P1-9 | 通知口径相反 | 排期结论写回 `cycle`，`status` 只表示本地生成，`schedule_status` 表示排期 |
| P2-1/P2-2 | apply 不校验模式、用旧 job 算计划 | 非排期任务 409 `not_scheduled_job`；更新后重读 job 再算 |
| P2-3 | 错误体两套形状 | 全部改 `JSONResponse({"code","message"})` |
| P2-5 | 秒级乐观锁 | store 增加单调 `revision`，`expected_updated_at` 对 revision 和 updated_at 双校验 |
| P2-6 | 关补货仍覆盖 plan | `enabled=false` 只存设置不动 plan |
| P2-9 | `_patch_record` 写入边界 | 限定 `RUNS_ROOT` 下绝对路径，捕 `OSError/TypeError/ValueError` |
| P2-10 | 重复行/缺 ID 行 | 完全重复行去重，缺 `chapter_id` 行进 `needs_review` 不参与冲突 |
| P3 | 未使用形参、注释与代码相反、测试盲区 | `_finish` 用上 `verification`；注释改正；补跨午夜/过期/能力 0 值/stop 后再 step/旧 PUT 非 fanqie 用例 |

未采纳：P2-7 `stop_after_gap` 语义、P2-8 `note_manual_change` 接线（需要在真实采集面上判断“平台侧被手工改动”，本版无适配器，先留函数与单测，等真实采集面接入再挂路由）。

### 第二轮独立审计与修复（2026-11-21）

同一名审计者复算修复后的代码，确认第一轮 2 项 P0 闭合并新报 2 个 P0、4 个 P1 与若干 P2/P3。处理结果：

| 审计项 | 原问题 | 处理 |
| --- | --- | --- |
| P0-1 | `published` 分支跳过身份校验，平台返回已发即记账 | 同样校验正文 sha256 与计划时刻；不符转 `needs_review`，无正文身份时写 `body_verified=false` 但保留在已发数（平台已发是事实） |
| P0-2 | 计划变空时在途意图被标 `cancelled`，同 key 永久排不上 | `apply_plan` 增加 `cancelled` 复活分支，重排时重置为 `planned` 并清尝试次数 |
| P1-1 | 逐章提交只改内存，循环结束才落盘 | 每成功一章立即 `save_store`；两处“结果未知”停批前也落盘 |
| P1-2 | `in_flight` 不含 `scheduled_verified`，可超在排上限 | 新增 `PLATFORM_STATES=("submitted","scheduled_verified")` 作为平台占额口径，覆盖汇总另计本地 `planned` |
| P1-3 | `plan(remote=…)` 是死参数 | 传入 `last_reconcile.rows`，排除平台已有计划的章 |
| P1-4 | `needs_review` 无出口，排期永久停写 | 新增 `GET /schedule/review` 与 `POST /schedule/resolve`（`cancelled`/`planned`） |
| P2-1 | 同章换版本后双意图泄漏容量 | `plan` 增 `occupied_chapters`：同章另一版本在途即阻塞并保留该章 |
| P2-2 | `cycle.remote_state` 跨轮粘滞 | 每轮开始重置为 `not_attempted` |
| P2-3 | 排期成功文案仍写“仅本机，未发布” | 按模式分流为“本地已审定，排期待平台回读确认” |
| P2-4 | 空 `expected_updated_at` 绕过版本校验 | 改用单调 `revision`；空串视为未申领租约 |
| P2-5 | `update_job` 的 `ValueError` 直接 500 | 映射 400 `update_rejected` |
| P3-1/P3-3 | 无适配器时 `reconcile` 恒 409；`已排期` 文案未入词表 | 接受作者粘贴清单；词表补「已排期/已预约/排期中/已安排发布」 |
| P3-2 | `timezone_assumed` 靠字符串猜时区 | 改为解析后判 `tzinfo is None` |

文档问题（已改）：`RELEASE_STATUS.md` 的 T06/T07/T11 引用了不存在的测试名，已换成真实用例名；`CHANGELOG.md` 三句结论过强，已限定为“重算与建单时”“已取消可复活”等实际行为。

### 完成到哪一步（四类状态）

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 已完成：识别/能力/计划/意图/执行器/接口/兼容/绑定八块，默认零平台写入；两轮独立审计的 P0 全部闭合 |
| 真实模型验证 | 未做：本机无可用模型，执行器测试用替身生成；`real_model_budget.max_requests=0` |
| GitHub 推送 | 未做：用户未要求 commit/push |
| Release | 只到候选包：完整包与轻量包均通过 `verify-package`，npm/GitHub/市场未放行 |

### 已知缺口与下一步

1. **T22 升级回退**：0.6.0 候选包本机已不存在，无法构造两个真实版本连续升级两次；下次发行前需保留上一版包再演练。
2. **T26/T27 真机**：跨午夜/跨月、提前量、时区边界有单测，真实时钟回拨与两执行者并发未实测。
3. **真实平台**：B01 的采集面（登录、页面/接口读取）仍未接入，`can_read_schedule/can_confirm_body` 只能手工确认；本版按设计“不能区分时只交只读清单与本地存稿候选”。
4. **界面**：本版只做后端与接口，侧栏没有排期缓冲的编辑面板；`GET /schedule` 已给出 `settings/capability/preview/state` 供前端直接渲染。
5. **`note_manual_change` 未接线**：函数与单测就位，但手工取消/改期/替稿的检测依赖真实采集面，等适配器接入后挂到 reconcile 结果上。

## 0.7.0 长篇连续性与文风（2026-11-21，候选完成/待真机验收）

设计输入：`design\码章鲸_按版本执行包_2026-11-16\03_v0.7.0_长篇连续性与文风.md`（只做 C01–C04）。

### 实际版本与起点

| 项 | 值 |
| --- | --- |
| 版本 | `0.7.0`（`package.json`、`runtime-manifest.json` 同步） |
| 基线 | 0.6.1 候选工作树（本机 Python 3.13.5 / Node v24.18.0） |
| 新增文件 | `backend/integration/entity_state.py`、`invalidation.py`、`evidence_usage.py`、`retrieval_plan.py`、`style_rules.py`、`backend/integration/test_entity_state.py`、`test_invalidation.py`、`test_evidence_usage.py`、`test_retrieval_plan.py`、`test_style_rules.py`、`backend/manager/test_continuity_api.py` |
| 修改文件 | `backend/integration/revision_plan.py`、`version_history.py`、`revision_workflow.py`、`quality_gate.py`、`memory_library.py`、`backend/manager/app.py`、`package.json`、`runtime-manifest.json`、`CHANGELOG.md`、`README.md`、`RELEASE_STATUS.md`、`docs/plan/PROGRESS.md`、`docs/plan/STATE.json`、`market/*.json` |

### 实现要点

1. **C01 实体状态**：`.webnovel/entities.json` 存物品与事件；`holder_at` 严格取「本章之前」的记录，写本章时不能拿本章结果自证；同章多候选返回 `same_chapter_order_unknown` 而不是按写入顺序猜；事件带实体/属性/前后值/生效章界/知情主体/来源章 sha256 与引文/发现方式；闪回用 `story_time` 独立折算；`scope="narrator"` 不入角色已知；跨作品同名不合并（按作品目录隔离，同名只走检索入口）。
2. **C01 统一失效**：`invalidation.invalidate(chapters, reason, source, actor, op_id)` 是唯一入口，按 `op_id` 幂等，写 `.webnovel/invalidation_log.json` 并触发 `continuity.rebuild`；`revision_plan.accept` 与 `version_history.restore` 已接线，生成/导入/人工改走同一函数；日志保留最近 200 条，`pending/summary/affected_facts` 供界面读。
3. **C02 证据使用**：`evidence_usage` 以 jsonl 记「送了哪些证据、哪些没送、为什么」；`log_supply` 同章+阶段+版本去重；`record_use` 的 `confirmed` 只接受 `actor="author"`（模型自述只能是 `candidate`）；`locate_use` 先逐字定位、再按二元组重合给候选、最后才 `missing`，不用旧字符偏移；`reverse_index` 完全从日志折叠，可重建；`metrics(fixture)` 报精确率/召回率/漏定位/干扰项。
4. **C03 检索进规划**：`retrieval_plan.plan` 固定六段顺序（作品→有效来源/版本→章界→认知/视角→BM25 排序→预算），`bm25` 的 idf 用 document frequency；`sanitize_query` 先脱敏人名；每次规划可落 trace（送入证据、未选原因、耗时、磁盘），`report` 聚合；索引按 `(模型, 分块)` 隔离，`switch_index` 用 `os.replace` 原子替换并保留上一版，`search` 在索引损坏时回落 `text_fallback`；默认不启用向量模型。
5. **C04 文风规则**：`style_rules.RULES` 每条带 ID/类别/条件/适用范围/来源日期/正反例/严重度/忽略范围；本地检测重复小结、解释性收尾、同义反复、同质对白；平台规则 `advisory=True` 只提醒；`revision_workflow.revise` 在建议里附本地定位（只改位置不动情节），`quality_gate.judge` 新增并列 `local_style` 段但不参与 `quality_pass`；忽略词表按作品存 `.webnovel/style_ignore.json`；`metrics` 只报每百段提示数与采纳/忽略/误报计数，附「不宣称文风指标下降」。
6. **上下文小块**：`memory_library.context` 仅有实体记录时追加「物品与事件」小块（`entity_state.holder_rows`），并支持 `trace=` 写供证日志；实体文本走独立小预算，不挤掉伏笔与人物限制。
7. **接口**：`GET /api/projects/{id}/entities`、`/precheck`、`/retrieval`、`/evidence/impact`，`PUT /precheck/ignore`、`POST /precheck/action`；全部只读或只改本地设定，不写正文、不触发平台写入；错误沿用 `{"code", "message"}`。
8. **不越界**：本版不接读者数据、不做 Linux/其他平台、不默认捆绑向量模型；平台类规则不参与过审判定，也不宣称「AI 味下降」。

### 测试命令与结果（Windows 11 10.0.22631 / Node v24.18.0 / Python 3.13.5）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `npm test` | 0 | 98 项通过 / 0 失败 / 0 跳过 |
| `python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend` | 0 | 489 项通过，1 项跳过（0.6.1 为 427；新增 13 + 7 + 18 + 13 + 11） |
| `python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend` | 0 | 107 项通过（0.6.1 为 100；新增 10） |
| `python scripts/build-runtime.py` | 0 | 3412 个文件；buildId 见 `.v070/candidate/HASHES.txt` |
| `python scripts/pack-bundle.py` | 0 | `dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz`（字节/哈希见 `HASHES.txt`） |
| `node scripts/check-release.mjs --local` | 0 | 清单一致（3412 文件） |
| `node scripts/verify-package.mjs <完整包> -` | 0 | `success:true`，`downloads:0` |
| `node scripts/verify-package.mjs <轻量包> <完整包>` | 0 | `success:true`，`downloads:1` |
| `npm pack --ignore-scripts --pack-destination .v070/candidate` | 0 | `dsh-chapter-whale-0.7.0.tgz`（哈希见 `HASHES.txt`） |

打包注意：`backend/integration_data/`（测试遗留锁文件）会让 `check-release --local` 报「后端包混入本地状态」，打包前必须删掉。

### 完成到哪一步（四类状态）

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 已完成：五个模块 + 四处接线 + 六个接口 + 六套测试；不新增平台写入 |
| 真实模型验证 | 未做：本机无可用模型，`real_model_budget.max_requests=0` |
| GitHub 推送 | 未做：用户未要求 commit/push |
| Release | 只到候选包：两个包本机 verify 通过；npm/GitHub/市场未发布 |

### 已知缺口与下一步

1. **T22 升级回退**：本机没有 0.6.1 完整包副本，无法构造「连续升级两次 + 回退」真实演练。
2. **真实长篇**：100 章以上真实作品未跑，当前只有 `test_longform.py` 合成夹具；`entity_state`/`evidence_usage` 在 500 章量级未压测。
3. **向量检索**：`retrieval_plan` 只实现 BM25 与文本回落，本地嵌入模型未接（设计允许默认关闭）。
4. **界面**：只读接口已就绪，侧栏尚无实体/预检/检索面板。
5. **C02.4 的「已排期/已发章只给只读影响清单」**：`/evidence/impact` 已返回只读清单，但尚未与 0.6.1 的排期状态联动过滤。

## 0.8.0 读者反馈与可撤销建议（2026-11-21，候选完成/待真机验收）

设计输入：`design\码章鲸_按版本执行包_2026-11-16\04_v0.8.0_读者反馈与可撤销建议.md`（只做 D01/D02）。

### 实际版本与起点

| 项 | 值 |
| --- | --- |
| 版本 | `0.8.0`（`package.json`、`runtime-manifest.json`、`market/*.json` 同步） |
| 起点 | 0.7.0 候选工作树（本机 Windows 11 / Python 3.13.5 / Node v24.18.0） |
| 运行时 | 3415 文件，buildId `7c88f7b8ca8a097e7ea82ab406dfa753868cbb7ac63fa4b7d65f90fd13e68242`（审计修复后重打） |

### 实现要点

1. `reader_metrics.py`：四项指标字段字典（官方名、粒度、单位、分母、分母可见性、窗口、时区、来源、口径版本）；「章节跳出率」列为平台未提供，出现即拒绝，不本地臆造。
2. 导入分两步：`preview` 逐行给有效/重复/修订/拒绝原因，把待确认计划暂存到 `.webnovel/reader_previews/` 并返回 30 分钟有效的 token，不写观测；`commit` 凭 token 取回计划、校验存储摘要后在事务里落地，预览后数据变了就拒绝旧 token，缺 token 一律 400；存在拒绝行时整批不写，只有显式 `allow_partial` 才写入有效行并记 `partial`。
3. 每条读数固定存平台/作品/章/指标/窗口起止/观测时刻/值/单位/分母/来源/口径版本/批次；稳定键只看「哪一次观测」，同键改值或改分母都是「修订」并保完整快照（≤20 版）；`DELETE /readers/batches/{id}` 按批次撤销，新增行删除、修订行整条回退（值/分母/单位一起回退）；`0` 是真实读数，分母未知留空不填零。
4. 读图可回源：点带批次、口径版本与成熟度（发布不足 7 天标 `new`），图下固定列「分母未知/含新章/样本不足」等局限；非法指标返回 400 而不是 500。
5. 评论只当数据：去标签、压空白、截 200 字；命中控制指令话术的整条原文丢弃并标记（指纹按原文算，避免多条被标记的评论撞成一条），不执行也不转述进提示；聚类跳过被标记项；每次导入自动生成批次号。
6. `observation.py`：观察卡记作品/章节/指标变化/窗口/分母/脱敏评论/备选解释/到期；生命周期为候选→采纳→指定章段生效→到期或撤销；大纲差异只读并有 `GET /readers/observations/{id}/outline`。
7. 注入闸门：只有「已采纳 + 本章在范围内 + 未到期 + 属于当前作品」才进 `revision_workflow` 的修订建议、`quality_gate` 的并列 `reader_advice` 与 `memory_library.context` 的上下文块；候选/忽略/撤销/到期一律零注入；提醒块受剩余上下文预算约束，超出即截断并记入 `restricted`。
8. 新增接口：`GET /readers/dictionary`、`POST /readers/preview`、`POST /readers/import`、`DELETE /readers/batches/{id}`、`GET /readers/series`、`GET|POST /readers/comments`、`POST|GET /readers/observations`、`POST /readers/observations/expire`、`GET /readers/observations/{id}`、`GET /readers/observations/{id}/outline`、`POST /readers/observations/{id}/action`；读接口不写盘（到期只按 `now` 纯计算过滤，落库要显式 `expire`），全部不改正文、不触发平台写入。

### 测试

| 套件 | 结果 |
| --- | --- |
| `npm test` | 98 pass / 0 fail |
| `backend/integration` | 553 tests OK（skipped=1） |
| `backend/manager` | 124 tests OK |
| 新增 | `test_reader_metrics.py` 23、`test_observation.py` 17、`test_reader_api.py` 17 |

### 第一轮独立审计与修复（audit-080）

只读审计结论「有阻断」。修复项：撤销导入补 `DELETE /readers/batches/{id}`（P0-1）；修订历史改存完整快照，回退不再丢分母（P0-2）；token 服务端暂存并绑定存储摘要（P1-1）；拒绝行默认整批不写（P1-2）；稳定键不含分母、比较含分母，分母修正成修订（P1-3）；观察卡与注入按 `work_id` 隔离（P1-4）；`/readers/series` 非法指标 400（P1-5）；读路径不写盘，新增 `POST /readers/observations/expire`（P1-6）；提醒块纳入预算核算（P2-1）；评论自动批次、`skipped` 先物化（P2-3）；被标记评论指纹按原文（P2-4）；作品级指标非数字章号报错（P2-5）；大纲差异补接口（P3）。

### 完成到哪一步（四类状态）

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 已完成：字典/预览/提交/回源/撤销/观察卡/注入闸门/接口八块；未采纳零注入有按真实提示文本的断言 |
| 真实模型验证 | 未做：`real_model_budget.max_requests=0`，本版不需要模型调用 |
| GitHub 推送 | 未做：用户未要求 commit/push |
| Release | 只到候选包：完整包与轻量包均通过 `verify-package`，npm/GitHub/市场未发布 |

### 已知缺口与下一步

1. **真实平台 CSV**：只按设计文档的 11 列解析，平台实际列名与编码未核；后续接真实导出时先跑一次预览对表。
2. **T22 升级回退**：本机没有上一版已发布包，无法演练「连续升级两次并回退」；下次发版前保留上一版包。
3. **T24 安装包**：两包 verify 通过，但没在干净安装目录做真实安装与首次启动。
4. **界面**：只有接口，没有读者数据页与观察卡列表页。
5. **评论聚类**：只按关键词主题，未接平台原生分类。
6. **与排期/发布未联动**：采纳提醒只作用于生成与修订提示，不影响排期计划。

## 0.9.0 Linux x64 常驻存稿（2026-11-21，候选完成/待真机验收）

设计输入：`design\码章鲸_按版本执行包_2026-11-16\05_v0.9.0_Linux_x64常驻存稿.md`（只做 E01）。

### 实际版本与起点

| 项 | 值 |
| --- | --- |
| 版本 | `0.9.0`（`package.json`、`runtime-download.json`、`market/*.json` 同步） |
| 起点 | 0.8.0 候选工作树（本机 Windows 11 / Python 3.13.5 / Node v24.18.0） |
| 运行时 | 3415 文件（审计后），buildId 见 `.v090/candidate/HASHES.txt` |
| Linux 归档 | 1177 文件，`dsh-chapter-whale-service-linux-amd64-0.9.0.tar.gz` |

### 实现要点

1. `resident_service.py`：`start/health/inventory/status/backup/restore/checkpoint` 子命令，独立于 DSH 宿主运行。
2. 单实例靠文件锁：第二个进程拿不到锁以退出码 2 停下，只写 stderr（不覆盖正在工作实例的检查点），绝不重复写章；pid 只用于展示，陈旧 pid 不算存活。
3. 能力盘点 11 项，标 supported/replaced/disabled 并给原因：账号凭据在 Linux 按「重新配置」，浏览器/DSH 桥/OFM/免费服务首版关闭。
4. 启动先验卷：写探针确认可写（只读卷 `read_only`、`ENOSPC` 记 `low_space`）、剩余空间低于 256 MB 记 `low_space`；不可用时写 `refused` 检查点并退出码 4（状态写入失败也只降级诊断，不再 traceback）。
5. 配置 `ready` 要求 `version==2`、`settings.auto_schedule is true`、任务字段完整且作品目录存在；`empty`/`broken` 都不认领，只写心跳与检查点，服务不崩。
6. `SIGTERM`/`SIGINT` 只置位：主循环在任务边界停认领，进程内守护线程在 `--shutdown-seconds`（默认 25）后写 `state=stopping` 并强制退出；`_wait` 分片等待，不会被 PEP475 睡满整段。
7. 只补缺步：启动先 `recover_pending` 补齐未完成提交；`scheduler.retryable()` 跨时段放行上次 `running`/`failed`/`needs_revision`，同一时段不重复烧钱；`claimed/skipped/failed/blocked` 按 `run_once` 返回状态分项。
8. `health` 分进程/协调器/配置/卷四段并给 `ok`/`reasons`，`health` 子命令按 `ok` 返回 0/1，探活不读模型配置。
9. 备份白名单递归 `works/**`（正文+回执/版本）、`integration_data/**`（含 runs）、`logs/**`，跳过服务自身状态与旧备份；SQLite 走 `wal_checkpoint(TRUNCATE)` + `backup()`；`restore` 先取服务锁、校验备份根、`os.replace` 原子落盘并清 `-wal/-shm`。
10. `--root` 同时管住 `scheduler.SCHEDULER_PATH`/`RUNS_ROOT`（结束后还原），配置与任务不会一个读新卷一个读默认路径。
11. 部署与打包：`deploy/linux/` 给 Dockerfile（非 root 10001、`/data` 唯一可写卷、`PYTHONUTF8`/`LANG`、`HEALTHCHECK`、`STOPSIGNAL SIGTERM`、不声明 `EXPOSE`）、compose（只读根、cap_drop ALL、no-new-privileges）、systemd 单元与运维 README（卷类型只支持本地块设备）；`scripts/build-linux-service.py` 出确定性归档（mtime/uid/gid 归零、gzip mtime 0、严格后缀遇 CRLF 即失败、文档进包时统一转 LF）。

### 测试

| 套件 | 结果 |
| --- | --- |
| `npm test` | 98 pass / 0 fail |
| `backend/integration` | 582 tests OK（skipped=1） |
| `backend/manager` | 124 tests OK |
| 本版新增 | `test_resident_service.py` 36 项、`test_scheduler_recovery.py` 9 项（跨进程单实例、只读卷与磁盘满、配置自检、限时退出兜底、备份含正文与回执、还原取锁与根校验、health 退出码、跨时段重试） |

### 第一轮独立审计与修复（audit-090）

| 编号 | 原问题 | 修复 |
| --- | --- | --- |
| P0-1 | `due_jobs` 永久跳过 running/failed/needs_revision，失败即静默停更 | `retryable(job, slot)` 跨时段放行并标 `recovering`；启动 `recover_pending` |
| P0-2 | `shutdown_seconds` 只进检查点，没有计时器 | 守护线程计时后写 `stopping` 并 `os._exit(0)` |
| P0-3 | 备份不含正文/回执/runs/日志，还原不能重建 | 白名单递归备份 + 逐文件 sha256 manifest；还原取锁、原子落盘、清 WAL |
| P0-4 | 验收表引用 4 个不存在的测试名，README 与实现不符 | 验收表改实跑用例名；README 重写 `/config`、限时、退出码、卷类型、备份范围 |
| P1-1/P1-2 | 只读卷/磁盘满在写检查点时崩成 exit 1，且 ENOSPC 被误判只读 | 状态写入统一 `_safe()`；探针按 errno 区分 |
| P1-3 | `restore` 不认锁、非原子、不清 WAL、不校验根 | 取 `file_lock`、`os.replace`、删 `-wal/-shm`、根不符需显式允许 |
| P1-4 | 备份把旧备份再打包 | 递归跳过服务状态目录 |
| P1-5 | `health` 恒 exit 0 | 按 `ok` 返回 0/1 |
| P1-6 | `claimed` 把 busy/blocked 都算认领 | 按状态分项累计 |
| P1-7 | 双实例只在 flock 卷上成立且未声明 | README 明确只支持本地块设备 |
| P2-2 | `--root` 不管调度 | `run()` 注入 scheduler 路径并在结束时还原 |

### 完成到哪一步（四类状态）

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 已完成：服务循环/单实例/自检/限时退出/只补缺步/备份还原/部署文件/确定性归档 |
| 真实模型验证 | 未做：`real_model_budget.max_requests=0`，本版按设计只跑本地存稿 |
| GitHub 推送 | 未做：用户未要求 commit/push |
| Release | 只到候选：Windows 两包 `verify-package` 通过，Linux 归档产出 sha256；未发布 |

### 已知缺口与下一步

1. **无真实 Linux 实机**：systemd 单元与 compose 只做静态检查，未实际启动；T19/T35 未验证，镜像 digest 与 `systemd-analyze verify` 未进 CI。
2. **T22 升级回退**：备份已含正文/回执/runs，但本机没有上一版已发布包，无法演练连续升级两次并回退。
3. **T24 安装包**：两包 verify 通过，未在干净安装目录真实安装并首启。
4. **凭据迁移**：Linux 上要求重新配置账号，未做加密凭据的跨平台迁移。
5. **首版关闭的能力**：浏览器登录、DSH 桥、OFM、免费模型服务在 Linux 上均 disabled，需后续版本逐项评估。

## 0.9.1 Linux ARM64 目标平台（2026-11-21，候选完成/待实机验收）

| 项 | 值 |
| --- | --- |
| 起点 | 0.9.0 Linux amd64 常驻存稿（已交付候选） |
| 交付版本 | 0.9.1（package.json / market / README 同步） |
| 本版范围 | 只扩 `linux/arm64` 目标：构建、校验、文档口径；不接浏览器发表、不承诺 DSH 桌面宿主 |
| 运行时 | 3416 文件（清单随 `platform_support.py` 增加而变化），buildId 见 `.v091/candidate/HASHES.txt` |
| Linux 归档 | `dsh-chapter-whale-service-linux-amd64-0.9.1.tar.gz` 与 `-arm64-` 两份，字节/哈希见同一文件 |

### 实现要点

1. `platform_support.py`：`normalize_arch()` 只认 `x86_64/amd64/x64` 与 `aarch64/arm64`，其余返回空串，绝不猜架构；`target_for_arch()` 做反查。
2. `check_target()` 只在「Linux + 同架构」时 `ok=True`；跨架构写 `host_arch_mismatch:amd64!=arm64`，非 Linux 写 `host_not_linux:windows`，未知机器名写 `unknown_arch:...`，供文档与界面把该格标成「待实机」。
3. `verify_manifest()` / `verify_archive()` 三处一致：清单 `platform`、`arch` 与归档文件名必须互相对上；读 tar 成员本身，改名绕过、混入 `.exe/.dll/.pyd/.dylib/.msi/.bat/.ps1`、严格后缀含 CRLF、清单缺失或重复都判失败。
4. `build-linux-service.py --arch amd64|arm64`：归档名与 `linux-service-manifest-<arch>.json` 带架构，`--verify` 直接调用上面的归档校验；确定性归档参数不变。
5. 常驻服务新增 `platform` 子命令，输出能力矩阵（每格 `container` 平台、Python 下限、`verified_here`、原因）；`inventory` 仍只描述本机能力。
6. Dockerfile 说明改为 buildx 按目标平台构建；base image 仍按 tag 拉取（离线自行同步 digest），arm64 产物以真实 aarch64 主机验收为准。
7. 运维 README 增「构建产物与架构」段：两种归档名、两条构建命令、`--verify` 命令、buildx 命令，以及「跨架构构建不写已验证」的口径。

### 测试命令与结果（Windows 11 10.0.22631 / Node v24.18.0 / Python 3.13.5）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `npm test` | 0 | 98 项通过 / 0 失败 / 0 跳过 |
| `python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend` | 0 | 598 项通过，1 项跳过（0.9.0 为 582；新增 `test_platform_support.py` 16 项） |
| `python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend` | 0 | 124 项通过 |
| `python scripts/build-linux-service.py --arch amd64` / `--arch arm64` | 0 | 两份归档 + 各自 `.sha256` + `linux-service-manifest-<arch>.json` |
| `python scripts/build-linux-service.py --arch arm64 --verify <归档>` | 0 | `ok: true`，无 `problems` |
| `node scripts/check-release.mjs --local` / `verify-package.mjs` | 0 | 清单一致；两包 `success:true`（downloads 0 / 1） |

### 完成到哪一步（四类状态）

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 已完成：架构归一、主机匹配、清单/归档校验、双架构构建入口、`platform` 子命令、部署文档 |
| 真实模型验证 | 未做：本版不触模型，`real_model_budget.max_requests=0` |
| GitHub 推送 | 未做：用户未要求 commit/push |
| Release | 只到候选：双架构归档 + Windows 两包 verify 通过；未发布 |

### 已知缺口与下一步

1. **无真实 aarch64 主机**：arm64 归档只完成构建与静态校验，`verified_here` 在本机为 `false`；T20 的 arm64 格仍写「待实机」。
2. **容器镜像未构建**：buildx 命令已写入 README，但本机未执行 `docker buildx build --platform linux/arm64`，镜像 digest 未记录。
3. **T22 升级回退**：仍缺上一版已发布包，无法演练连续升级两次并回退。
4. **T19/T35**：amd64 与 arm64 都未在真实 systemd 主机上启动，动态守护只做了单元测试与子进程用例。
5. **跨架构迁移**：同一份 `/data` 在 amd64 与 arm64 之间搬运未实测；文档只声明「数据格式一致、凭据需重配」。

---

## 0.9.2 macOS ARM64 本地存稿（2026-11-22，候选完成/待实机验收）

**实际版本与起点**

| 项 | 值 |
|---|---|
| 版本 | 0.9.2（`package.json` / `market/*.json` / `README` 同步） |
| 起点 | 0.9.1 的 Linux 双架构目标与 0.9.0 的服务契约 |
| 本版新增 | `deploy/macos/`（plist + run.command + README）、`scripts/build-macos-service.py`、`platform_support` 的 `macos-arm64` 格、`test_macos_deploy.py` |
| 平台写入 | 零（无浏览器、无登录、无发布调用） |

**实现要点**

1. `platform_support.TARGETS` 增 `macos-arm64`（`system="darwin"`、`launcher="launchd"`、`container=""`）；`check_target()` 改为按目标自带 `system` 比对，非 Darwin 返回 `host_system_mismatch:*`。
2. `matrix()` 每格给出 `target/arch/system/container/launcher/python/verified_here/reason/note`；同一次运行最多一格 `verified_here=True`（测试断言）。
3. `verify_archive()` 增 macos 专属拒绝：ELF 头 → `elf_binary`，`.so/.so.1/.a` → `linux_object`；仍保留 Windows 二进制、CRLF、清单计数与 platform/arch/文件名一致性检查。
4. `scripts/build-macos-service.py` 独立入口：固定 `macos-arm64`，内嵌无时间戳 `service-build.json`（确定性 gzip/tar），产出归档、`.sha256`、`macos-service-manifest.json`，`--verify` 复用 `verify_archive`。
5. `deploy/macos/com.chapterwhale.service.plist`：`launchctl bootstrap` 安装，`RunAtLoad`、`KeepAlive.SuccessfulExit=false`、`ThrottleInterval=30`、`ExitTimeOut=40`、日志写数据卷 `logs/`。
6. `deploy/macos/run.command`：`set -eu`、路径全引号、缺安装目录 64 / 缺数据卷 65 / 不可写 66，`exec` 前导出 `PYTHONPATH`/`PYTHONUTF8`。
7. `deploy/macos/README.md` 写明：只支持本地盘（NAS/SMB 锁不可靠）、APFS 默认大小写不敏感、浏览器与登录是「未开放」格、凭据在目标机重配且不迁移 DPAPI 密文、实机证据缺失前保持「待实机」。
8. `resident_service platform` 子命令输出三格矩阵，macOS 行在本机（Windows/Linux）恒为未验证，不冒充实机。

**测试结果**

| 检查 | 结果 |
|---|---|
| `npm test` | 98 pass / 0 fail |
| integration 全量 | 612 tests OK（skipped=1） |
| manager 全量 | 124 tests OK |
| `test_macos_deploy.py` | 13 tests OK |
| `test_platform_support.py` | 17 tests OK（含 macOS 三格矩阵） |
| macOS 归档 `--verify` | `{"ok": true, "problems": []}` |
| Windows 清单 | 3416 files（buildId 见 `.v092/candidate/HASHES.txt`） |
| 安装包自检 | 两包 `success:true`（downloads 0 / 1） |

**四类状态**

| 类别 | 状态 |
|---|---|
| 代码实现 | 完成（服务契约复用，macOS 目标、归档、启动配置、文档齐备） |
| 真实模型验证 | 未做（本版不产生真实付费调用） |
| GitHub 推送 | 未做（本轮不 commit/push） |
| Release | 未发布（候选包在 `.v092/candidate/`，需实机验收） |

**已知缺口**

1. 无真实 Apple Silicon：安装/启动/健康/停止/断电/磁盘满/只读卷全部为离线校验与脚本审阅。
2. `launchctl` 的 `ExitTimeOut` 与进程内 25 秒兜底的先后顺序未实测。
3. T22（升级两次 + 回退）与 T19（卸载重装挂旧卷）未在 macOS 上演练。
4. 代码签名与公证未做（本版只发 tar.gz 与脚本，不发 `.app`）。
5. 跨架构迁移只在文档写明步骤，未实测。

**下一步**

等 `audit-092` 报告并按报告修；随后 0.9.3（macOS Intel）、0.9.4（单目标浏览器与登录）、0.10.0（第二发布平台）。

## 0.9.3 macOS Intel 目标与归档内容校验（2026-11-22，候选完成/待实机验收）

| 项 | 值 |
| --- | --- |
| 起点 | 0.9.2（macOS ARM64 候选） |
| 交付版本 | 0.9.3（package.json / market / README 同步） |
| 运行时清单 | 3416 个文件，buildId 见 `.v093/candidate/HASHES.txt` |
| 服务归档 | Linux amd64/arm64 各 1178 载荷、macOS arm64/amd64 各 1175 载荷 |
| 本轮测试 | integration 622（skipped=1）、manager 124、`npm test` 98 pass |

**实现要点**

1. `platform_support.TARGETS` 增 `macos-amd64`，矩阵四格；`matrix()` 把 `host_matches` 与 `verified_here` 拆开，后者只由真实运行写回，当前恒 `False`。
2. `check_target` 对 Rosetta 下的 x86_64 解释器报 `rosetta_translation:not_native`，Intel 格不会因 macOS 跑通而被标成已验证。
3. `verify_archive` 改为校验内容：按构建口径重算载荷摘要（`payload_digest_mismatch`）、比对 `files` 计数（`file_count_mismatch`）、`files` 必须为整数（`manifest_field_type:files`）、必填字段缺失即失败、清单只认归档根（`manifest_not_at_root`）、同名成员重复即失败（`duplicate_member`）。
4. 归档成员安全：符号链接/硬链接报 `link_member`，`..` 与绝对路径报 `unsafe_path`，损坏归档返回 `archive_unreadable` 而不是抛异常。
5. ELF 架构：Linux 目标校验 `e_machine`（amd64 `0x3E`、arm64 `0xB7`）；macOS 目标继续拒 ELF 与 `.so/.so.1/.a`。
6. 构建卫生：两个构建脚本排除历史归档与 `.sha256`，并拒绝 `--out` 落在收集范围；`--verify` 的退出码跟随 `ok`（失败即非 0），并与 `.sha256`、外部 `*-service-manifest-<arch>.json` 三方比对。
7. 大小写不敏感卷：`chapter_versions.chapter_path` 按后缀小写列出正文，并在「同一名字只差大小写」时抛 `case_conflict`，避免在 APFS 上静默覆盖作者原稿。
8. macOS 部署：`plist` 显式给 `PATH`（launchd 不继承登录 shell PATH），`run.command` 用 `${@+"$@"}` 兼容 bash 3.2，README 补 `command -v python3`、`id -gn`、`mkdir -p` 与「构建脚本不在 npm 包内」。
9. 平台写入仍为零：无浏览器、无登录、无发布接口调用。

**测试**

| 套件 | 数量 | 结果 |
| --- | --- | --- |
| integration | 622（skipped=1） | OK |
| manager | 124 | OK |
| `test_platform_support.py` | 27 | OK |
| `test_macos_deploy.py` | 15 | OK |
| `npm test` | 98 | 98 pass / 0 fail |

**审计与修复**

| 来源 | 问题 | 处理 |
| --- | --- | --- |
| audit-091 P1-1 | `verify_archive` 不校验载荷摘要 | 已改：摘要 + 文件数 + 字段类型 |
| audit-091 P1-2/P1-3 | 清单可躲子目录、重复成员被覆盖 | 已改：根目录约束 + `duplicate_member` |
| audit-091 P1-4 | `--verify` 只信 `--arch`、不读 sidecar | 已改：三方比对 + 退出码 |
| audit-091 P1-5 | `--out` 可自我打包 | 已改：收集排除 + 路径断言 |
| audit-092 P0-1 | HASHES 与归档不符、归档不在候选目录 | 已改：六份产物同目录，HASHES 由脚本按字节重算 |
| audit-092 P1-1 | `--verify` 恒返回 0 | 已改：`raise SystemExit(0 if ok else 1)` |
| audit-092 P1-2 | README 大小写承诺与实现相反 | 已改：实现抛 `case_conflict`，README 同步 |
| audit-092 P1-3 | plist 解释器在干净 Mac 上不可用 | 已改：显式 `PATH` + README 核对步骤 |
| audit-092 P1-4 | symlink/硬链接/路径穿越绕过 | 已改：`link_member` / `unsafe_path` |
| audit-092 P1-5 | 文档测试数字失准 | 已改：27 / 15 / 622 按实跑写 |

**四类状态**

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（0.9.3 全部条目落地并有测试） |
| 真实模型验证 | 未做（本轮仍不产生真实付费调用） |
| GitHub 推送 | 未做（未 commit、未 push） |
| Release | 候选（`.v093/candidate/` 六份产物 + HASHES + verify 回执） |

**已知缺口**

1. 无 Apple Silicon 与 Intel Mac 实机，macOS 两格的运行验收为 0。
2. 无 aarch64 主机，Linux arm64 仍只是构建与校验。
3. T22 升级两次并回退未验证（缺上一版已发布安装包）。
4. 浏览器、登录、发布写入仍未开放，不能按版本号推断为已接入。
5. 构建脚本只校验归档自身一致性，未与工作树逐文件比对（同源证明靠 buildId 与 manifest）。

## 0.9.4 单目标浏览器与登录试点（2026-11-22，候选完成/待实机与真实登录验收）

| 项 | 值 |
| --- | --- |
| 版本 | 0.9.4（package.json / market / README / STATE 一致） |
| 起点 | 0.9.3 候选（四格支持矩阵 + 归档内容校验） |
| 运行时清单 | 见 `.v094/candidate/HASHES.txt`（文件数与 buildId 以该文件为准） |
| 测试 | `npm test` 98 pass；integration 658 OK（skipped=3）；manager 135 OK；浏览器专测 24 + 11 |

> 复审（audit-095）后：`test_browser_target.py` 33 项（skipped=2）、`test_browser_api.py` 15 项；0.10.0 完成时 integration 合计 700 项（含 0.10.0 新增用例），manager 148 项。

### 完成内容

1. `backend/integration/browser_target.py`：唯一 target 八项必填（OS/架构/原生或容器/浏览器与版本/驱动/凭据/平台/范围），publish 另需授权依据；`os`/`arch`/`runtime`/`scope` 走枚举、版本号按形状校验、driver 限字符集；读盘后重新校验。
2. profile 受管：`ensure_profile`/`status`/`launch` 统一用 target 里的路径，越界、符号链接与 Windows 目录联接都拒绝；POSIX 上 0700；登录、journal、账本、target 都按作品隔离。
3. 登录只认证据：`valid`/`expired` 只能由适配器回读写入，客户端只能报 unknown/needs_human/cancelled；`valid` 的证据必须是页面摘要；取消/超时写终态。
4. 启动分类：缺二进制/驱动、权限不足、等待扫码分别报原因；适配器未确认 `started` 不算启动；无适配器直接拒绝。
5. 只读核验：逐项比对平台、作品 ID、章号与正文摘要（64 位十六进制），不适配给具体待处理项；`writes` 取适配器回报，>0 判待处理；journal 记只读证据。
6. 真实投递：授权只认 target 上保存的记录；幂等账本独立于 journal（只增不裁），同章同摘要 `duplicate`，改稿换摘要才新建；`needs_human`/`aborted`/`unknown` 留终态，`POST /browser/publish/reconcile` 清账后可重投。
7. journal 改 JSONL 只追加 + 进程锁 + 文件与目录 fsync：两进程各 30 条不丢，200 条裁剪不影响幂等。
8. 八列能力矩阵 + `evidence`：`schedule` 无替身为 pending，`browser_login`/`readonly` 只认适配器写入的 valid。
9. 十个接口：status/target(GET,PUT)/launch/stop/health/login/readonly/publish/publish-reconcile/capabilities；浏览器路由错误体统一 `{"code","message"}`；读接口不写盘。

### 测试结果

| 套件 | 结果 |
| --- | --- |
| `npm test` | 98 pass / 0 fail |
| integration 全量 | 658 tests OK（skipped=3） |
| manager 全量 | 135 tests OK |
| `integration.test_browser_target` | 33 tests OK（2 skipped：符号链接、POSIX 权限位；audit-095 后） |
| `manager.test_browser_api` | 15 tests OK（audit-095 后） |

### 第一轮独立审计与修复（audit-094）

| 编号 | 原问题 | 修复 |
| --- | --- | --- |
| P0-1 | 只读核验只判非空 + 章号，另一本书/另一平台/假摘要也 verified | 逐项比对 platform/book_id/chapter_id/正文摘要 |
| P0-2 | 同章可投递两次（journal 裁剪 + 授权自证） | 独立幂等账本；授权只认 target 记录 |
| P0-3 | journal 读-改-写无锁，丢条目 | JSONL 只追加 + 进程锁 + fsync |
| P0-4 | profile 可被 junction 绕过、target.profile 被忽略 | 最终路径判越界与 reparse point；统一用 target 值 |
| P0-5 | 登录 valid 可由一次 HTTP 自证 | 仅适配器可写 valid/expired |
| P1-1 | 八列矩阵无证据 | `capability_evidence()`；simulated 需适配器写入 |
| P1-2 | 错误体不统一、多处 500 | 统一 `{"code","message"}`；stop/health/capabilities 加保护 |
| P1-3 | 非数值 chapter_id 500 | 转 `needs_review` |
| P1-4 | needs_human 后永久 duplicate | 终态 + reconcile 清账 |
| P1-5 | `writes` 硬编码 0 | 取适配器回报 |
| P2-1/2/6/7 | 字段任意字符串、读盘不复校验、headless 零覆盖、空 stop 写盘 | 枚举与形状校验、读后复校验、query 参数用例、空态直接返回 |

### 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（target/profile/登录/只读/投递闸门/矩阵/接口） |
| 真实模型验证 | 未涉及（本版不调用模型） |
| GitHub 推送 | 未推送（用户未要求） |
| Release | 候选产物已生成，未发布 |

### 已知缺口

1. 真实 Chromium/驱动与真实扫码登录未执行；`verified_here` 仍恒 False。
2. 真实只读核验与真实单章投递未执行（需书面授权）。
3. 0.9.3 → 0.9.4 升级两次与回退未演练（缺上一版安装包）。
4. Linux/macOS 归档与 systemd/launchd 安装未在对应实机复验。
5. 浏览器被占锁、页面结构变化、同名不同平台书等真实异常路径只有离线替身覆盖。

## 0.10.0 平台能力契约与单个第二平台（2026-11-22，候选完成/待真实账号与格式核对）

### 实际版本与起点

| 项 | 值 |
| --- | --- |
| 版本 | `package.json` 0.10.0（上一交付 0.9.4） |
| 起点 | 工作树 HEAD `4f218c0` + 0.6.1–0.9.4 未提交改动 |
| 本版新增模块 | `backend/integration/publishing.py` |
| 本版新增测试 | `backend/integration/test_publishing.py`（40，skipped=1）、`backend/manager/test_publish_api.py`（12） |
| 运行时文件 | 见 `.v0100/candidate/HASHES.txt`（文件数与 buildId） |

### 实现要点

1. **能力契约**：`CAPABILITIES` 写番茄与七猫两项，字段 `can_export`/`can_draft`/`can_schedule`/`can_verify_body`/`can_submit` 为三态；`capabilities()` 推导 `publishable`，只有四项**均为** `True` 且 `can_submit is True` 才为真，`None` 一律按不可发布。
2. **target_platform 与命名空间**：`set_target_platform` 写 `.webnovel/publish/targets.json`；`namespace()` 生成 `<platform>/<账号-短hash>/<平台作品ID>` 目录，缺账号或平台作品 ID 直接抛错（不再回落占位名，避免两本书互相覆盖）。
3. **旧记录显式迁移**：`migrate_legacy` 只允许 `platform=fanqie`，按 `(类型, 章号, 摘要)` 去重，先写台账（`copying`）再复制并回写 `copied/verified`，写 `migration.json`；缺身份、目标冲突或文件不可读返回 `needs_review` 并保留原位。
4. **第一层导出**：`format_chapter` 规范化标题（补「第N章」前缀并校验章号一致）、段落与字数（`chars` 去标题与标点）并算摘要；`export_chapter` 先过越界校验再 `mkdir`，写章节文件与 `manifest.json`，旧摘要压进 `versions`，坏清单重建并标 `corrupt`，返回 `uploaded: False`。
5. **第二层只读登记**：`bind_book` 区分 `manual`/`readonly_probe`，人工登记停在 `registered`；`readonly_probe` 必须带匹配的 `probe_evidence`（平台/作品 ID/观测章号）才 `verified`。
6. **第三层获准单章**：`submit_chapter` 依次校验能力、适配器、只读绑定、服务端授权；任一步缺失返回 `refused`/`unavailable` 且 `writes: 0`，不调用适配器；七猫即使注册适配器也恒 `refused`。
7. **幂等与未知**：意图先写 `<namespace>/intents/<key>.json`（键含平台/账号/作品/章/`body_sha256`），同章同摘要再投 `duplicate`；异常或未确认 → `unknown` + `writes_attempted: 1`；回执摘要不符 → `mismatch` + `writes_confirmed: 0`；`unknown`/`mismatch` 只对账不重发（`allow_duplicate` 不可绕过）；成功记 `accepted`/`echoed_sha256`/`body_matches`/`writes_confirmed`。
8. **对账与授权**：`reconcile` 限 `intent|unknown|mismatch → accepted|abandoned`，`abandoned` 终态，`note` 与 `evidence` 必填；`authorize` 再授权把旧记录置 `active=false` + `revoked_at`，保留依据。
9. **接口**：九个 `/publish/*` 路由；错误体统一 `{"code","message"}`（422、HTTPException、未捕获异常 500 `internal_error`、413 `payload_too_large`）；`status` 遍历两平台只读，严格读取账本，坏 JSON/非对象计入 `corrupt_ledgers`。
10. **文档与版本**：`package.json`/`market/index.json`（`plugins[0].versions[]` 单对象）/`market/losebird-entry.json`/`README.md`/`docs/plan/STATE.json`（`current_module=M24`，`releases["0.10.0"]` 记候选与实测计数）同步 0.10.0；`CHANGELOG.md` 新增 0.10.0 段。

### 测试结果

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| Node | `npm test` | 98 pass / 0 fail |
| 集成 | `python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend` | 707 tests OK（skipped=4） |
| 管理端 | 同命令指向 `backend/manager` | 151 tests OK |
| 平台契约 | `python -B -X utf8 -m unittest discover -s backend/integration -p "test_publishing.py" -t backend` | 40 OK（skipped=1） |
| 平台接口 | `python -B -X utf8 -m unittest discover -s backend/manager -p "test_publish_api.py" -t backend` | 12 OK |

### 四类状态

| 类别 | 状态 |
| --- | --- |
| 代码实现 | 完成（`publishing.py` + 九个接口 + 测试） |
| 真实模型验证 | 不适用（本版无模型调用路径改动） |
| 真实平台验证 | 未开始：无七猫账号/格式核对，无本版番茄复验；平台写入 0 |
| GitHub 推送 / Release | 未执行（本轮未授权新的公开发行） |
| 安装包 | 两包 `verify-package` 通过；未在全新目录走最短用户路径 |

### 第二轮独立审计与修复（audit-101）

| 编号 | 原问题 | 处理 |
| --- | --- | --- |
| P1-A | `corrupt_ledgers` 恒 0：`_read` 从不抛错，坏账本静默消失 | `_read(strict=True)` 抛 `PublishError`；坏 JSON/非对象/空对象都计数；补两条用例 |
| P1-B | 无 `Exception` 兜底，413 仍是 `{"detail"}` | 全局异常处理器 → 500 `internal_error`；`runtime_health` 413 改 `payload_too_large`；补两条 API 用例 |
| P1-C | 迁移崩溃后 `copying` 条目被当作已迁移，该章永久不复制 | `seen` 只认 `copied+verified`；`copying` 按目标摘要复核后补记；补恢复用例 |
| P2-D | `STATE.json` 无 0.10.0 | 补 `releases["0.10.0"]`（清单/计数/两包摘要/候选未发布） |
| P2-E | `.v0100/verify-*.json` 是旧构建的陈旧回执 | 删除；回执统一在 `.v0100/candidate/`，HASHES 给相对路径 |
| P2-F | 回执无法自证字节 | `verify-package.mjs` 增 `archiveBytes`/`archiveSha256`，重跑对齐 |
| P2-G | 文档把未修写成已修 | 先改代码，再按实测回填 RELEASE_STATUS 与本文件 |
| P3-H | `allow_duplicate` 是死参数 | 删除；`unknown`/`mismatch` 只能对账 |
| P3-I | body 上限按字符计，与字节口径不符 | `field_validator` 按 UTF-8 字节 ≤ 1 MiB 校验 |
| 测试 | `conflicts`、`probe_evidence` 章号不足、`mkdir` 顺序、坏账本、`status` 写入零覆盖 | 新增 `Audit101RegressionTest` 7 项（含目标字节不变、413 码值、`copying` 但目标缺失需重写） |

### 第一轮独立审计与修复（audit-100）

| 编号 | 原问题 | 处理 |
| --- | --- | --- |
| P0-1 | 候选包与源码/清单三方不一致，`check-release --local` 失败 | 冻结源码后串行执行「回归 → 清单 → 两包 → 四归档 → verify」，产物与源码一次对齐 |
| P0-2 | 审计窗口内仓库被持续编辑，测试基线不稳 | 本轮先改完再跑全量，随后再重建清单，避免边改边打 |
| P0-3 | 缺账号/作品 ID 时两本书导出互相覆盖 | `namespace()` 缺身份抛错；目录带账号短 hash；导出先越界校验再落盘 |
| P0-4 | 回执正文不符仍记「已确认写入」 | 新增 `mismatch`，`writes_confirmed=0`，只允许带证据对账 |
| P1-1 | 迁移可跨平台污染 | 迁移源只允许 `fanqie`，其它平台 `needs_review` |
| P1-2 | 迁移非原子，失败无台账 | 每文件先记 `copying` 再复制，回写 `copied/verified` |
| P1-3 | 目标已存在时静默覆盖 | 摘要不同 → `conflicts` + `needs_review` |
| P1-4 | `reconcile` 无状态机、无证据 | 限定转移表，`abandoned` 终态，`note`/`evidence` 必填 |
| P1-5 | 授权替换删除历史 | 旧记录 `active=false` + `revoked_at`，保留依据 |
| P1-6 | `status` 只看目标平台 | 遍历 `PLATFORMS` 汇总 |
| P1-7 | `readonly_probe` 可自报 `verified` | 需匹配 `probe_evidence`，否则只记 `registered` |
| P1-8 | 错误体混 `{"detail"}` 与 `{"code","message"}` | 全局 422 / HTTPException / 未捕获异常统一 `{"code","message"}` |
| P1-9 | 坏形状清单触发 500 | 类型校验后重建并标 `corrupt`；`status` 计 `corrupt_ledgers` |
| P2 | 中文章号双前缀、字数口径、1 MB 上限不可达、越界晚于 mkdir、`allow_duplicate` 强制重发 | 章号一致性校验、`chars` 去标题标点、API 上限按 UTF-8 字节 ≤ 1 MiB、先校验后 `mkdir`、`unknown`/`mismatch` 不再可绕过 |
| 测试 | 账号隔离、跨平台账本键、授权隔离三处变异未红 | 新增 `test_accounts_get_separate_namespaces`、`test_ledger_key_separates_platform`、`test_authorizing_one_book_keeps_the_other`、`test_corrupt_manifest_is_replaced_not_fatal`、`test_over_long_body_is_refused_before_writing` |

### 已知缺口

1. 七猫没有任何官方提交方式证据，`can_submit: False`；导出格式只按通用纯文本核对。
2. 旧队列迁移只覆盖「身份齐全且唯一」的路径；同名、缺身份的历史文件保留原位，未做批量人工核对流程。
3. 第三层真实提交依赖 0.9.4 的浏览器适配器，本版未重跑真实投递链路。
4. T22 升级两次与回退、T24 全新目录最短路径、T10 真实双账号隔离均未演练。
5. 四份服务归档与 Windows 包只做到离线构建与 `--verify`，无新增实机证据。

### 下一步

- 拿到七猫账号与后台格式说明后：核对导出格式 → 只读绑定稳定作品 ID → 在明确授权下单章试点一次，并记录脱敏回执。
- 若真实提交仍无稳定回执，保持「只交导出」结论，不把七猫写进支持矩阵。

## 0.6.1–0.10.0 收口（2026-11-22）

九个版本全部做到「候选完成」，每一版都经过至少一轮独立只读复审，并按复审报告修完 P0/P1 后再重打包。全部版本**未 commit、未 push、未发布**；真实平台、真实模型、真实设备与真实安装目录的验证仍然留白，逐版列在对应的「尚未完成的真机条件」里。

| 版本 | 主题 | 关键交付 | 本版收尾时测试 | 独立复审 |
| --- | --- | --- | --- | --- |
| 0.6.1 | 番茄排期缓冲 | 排期识别与能力证实、纯计算覆盖、意图台账与对账、`platform_scheduled` 全贯通 | 98 / 422 / 97 | audit-061、audit-061b（两轮 P0 全闭合） |
| 0.7.0 | 长篇连续性与文风 | `entity_state`（物品归属与认知按章折算）、统一失效入口、证据使用日志与反向索引、BM25 优先的可控检索、带规则 ID 的可撤销文风建议 | 98 / 489 / 107 | audit-070（C01–C04 覆盖度与生产者缺口） |
| 0.8.0 | 读者反馈与可撤销建议 | 指标字典与两步导入、分母未知不填零、观察卡生命周期、三条注入路径同一闸门 | 98 / 553 / 124 | audit-080（token 绑定、整批拒、批次撤销、作品隔离、只读 GET） |
| 0.9.0 | Linux x64 常驻存稿 | 独立服务与容器/systemd、单实例、只补缺步、SIGTERM 限时退出、备份还原与 health | 98 / 582 / 124 | audit-090（`due_jobs` 跨时段重试、看门狗、备份白名单、配置自检） |
| 0.9.1 | Linux ARM64 | 架构归一、主机匹配、归档校验（摘要/文件数/清单位置/重复成员/ELF 架构/链接与越界）、双架构构建 | 98 / 598 / 124 | audit-091（校验面与可复现性） |
| 0.9.2 | macOS ARM64 | LaunchAgent、`run.command`、macOS 归档校验（拒 ELF 与 `.so`）、能力矩阵 | 98 / 612 / 124 | audit-092（plist PATH、大小写冲突、候选产物缺失） |
| 0.9.3 | macOS Intel | 四格平台矩阵、Rosetta 识别、`host_matches`/`verified_here` 拆分、ELF `e_machine` 校验 | 98 / 622 / 124 | audit-093（外部锚点、sidecar 必需、`chapter_path` 性能） |
| 0.9.4 | 单目标浏览器与登录 | 唯一 target、受管 profile（拒 junction/越界）、登录只认适配器证据、只读逐项核验零写入、投递先落账本 + replace 语义 | 98 / 658 / 135 | audit-094、audit-095（账本越界、账号与摘要比对、并发抢占、错误体统一） |
| 0.10.0 | 平台契约与第二平台 | 两平台能力矩阵（七猫手动上传）、命名空间按账号隔离、导出与台账、只读绑定与授权历史、提交四关与对账状态机、迁移台账 | 98 / 707 / 151 | audit-100、audit-101、audit-102（三方一致、命名空间覆盖、回执诚实性、413 单一码值） |

产物位置：每版 `<版本目录>/candidate/`（`.v061`、`.v070`、`.v080`、`.v090`、`.v091`、`.v092`、`.v093`、`.v094`、`.v0100`）下有安装包、服务归档、外部清单与 `HASHES.txt`；包内文档不写死自身哈希，一律以 `HASHES.txt` 为准。

复核入口（本机 Windows 11 / Python 3.13.5 / Node v24.18.0 已实跑）：`npm test`、两套 `unittest discover`、`node scripts/check-release.mjs --local`、`node scripts/verify-package.mjs`（两个包）、`python scripts/build-linux-service.py --arch <a> --verify <归档>`、`python scripts/build-macos-service.py --arch <a> --verify <归档>`。

仍待真实环境验证的共性条件：真实番茄/七猫账号与页面结构；真实模型调用（本轮真实模型预算为 0）；真实 Linux ARM64 与 Apple Silicon/Intel 机器；真实安装目录下的升级两次与回退演练；真实 webhook 与通知；`npm` 正式发布。任何一条未满足时，对应支持格只能写「模拟/待验」，不能写成已支持。
## 0.7.0 统一收口与 PR 交付（2026-11-23）

- **目标与收敛决定**：按用户确认将 0.6.1 → 0.10.0 阶段积攒的改动统一收敛为一个 `0.7.0` 版本并在分支 `feat/v0.7.0` 提交面向 `main` 的 GitHub PR（**不合并、不发包、不提交第三方市场**）。
- **DSH 插件前后端补全与缺陷修复**：
  - `index.js`：补全 29 条非 GET 后端写路由至 `WRITE_ROUTES`；修复 `makeTool()` 解析统一 `{"code", "message"}` 错误体；`test/gate.test.mjs` 新增对 `backend/manager/*.py` 路由表的防漂移自动化比对。
  - `client.js`：新增 `apiErrorMessage()` 修复 `api()` 错误读取；扩展 `PUBLICATION_LABELS` 与 `ScheduleCard` 支持并保留 `draft_only / publish_now / platform_scheduled`、账号与平台字段；新增 `ScheduleBufferPanel`、`RunsNotificationsPanel`、升级 `JobsPage`（多任务、配置/排期/运行子页、修复 `draft` 切换与保存清空字段问题）；扩展 `PublishPage`、`MemoryPage`、独立侧栏 `ReadersPage` 与 `ChapterModal`「预检」标签。
  - 许可证统一确认 `GPL-3.0-only`（`package.json`、`package-lock.json`、`LICENSES/`、`THIRD_PARTY_NOTICES.md`、`market/losebird-entry.json`）。
  - 仓库外评估报告写入 `O:\小说助手\design\xingyue-borrowed\EVALUATION_for_chapter_whale.md`（`0.7.0` 暂不合入）。
- **本轮验证快照（本机实跑）**：
  - `npm test`：**101 pass / 0 fail**（含 `client.test.mjs`、`gate.test.mjs`、`p04-bridge.test.mjs`、`market.test.mjs`、`manifest.test.mjs`、`managed-runtime.test.mjs`、`release-check.test.mjs`）
  - `backend/integration`：**707 OK（skipped=4）**；`backend/manager`：**151 OK**
  - 本地回环代理 E2E 冒烟（`index.js` + `manager/app.py`，`start_dispatcher=False`，真实模型 = 0，外部写入 = 0）：**9/9 阶段全通**（含 `platform_scheduled`、`schedule`、`entities`/`precheck`/`retrieval`/`evidence/impact`、`readers`、`browser` 只读、七猫写入拒绝 `writes=0`、`runs`/`notifications`、`422 invalid_request` 错误体透传）
  - `runtime-manifest.json`：**3418 文件**，`buildId`: `04e29797f2e80aab87bcf2767460ae663b814d9a096c896140f78f47a1dbf1c7`
  - 候选产物：`pack-bundle.py`、`npm pack`、四份 Linux/macOS 服务归档（`--verify` 全通）、`check-release.mjs --local` 与 `verify-package.mjs` 结果/哈希统一记于 `.v070/candidate/HASHES.txt`
  - **仍未验证项**：真实番茄/七猫网页与账号、真实模型调用（预算=0）、真实 Linux ARM64 与 Apple Silicon/Intel 物理机、连续升级两次与回退（T22）、真实外网 Webhook、npm/GitHub 正式发布
