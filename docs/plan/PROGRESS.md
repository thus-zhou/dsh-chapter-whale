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

