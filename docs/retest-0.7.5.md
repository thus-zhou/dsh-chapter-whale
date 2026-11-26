# 码章鲸 0.7.5 复测与全量回归记录

本文记录针对 0.7.4 用户反馈的 9 项核心问题在 `feat/v0.7.5` 分支的修复内容及离线自动化验证结果。

## 九大核心问题修复清单

| 编号 | 问题现象 | 根因定位与 0.7.5 修复 |
| --- | --- | --- |
| 1 | 部分任务进行时无进度条 | 后端 `Operations` 增加 `NOVEL_HELPER_PROGRESS` 结构化进度解析与关键字推断，`writer_runner`、`studio`、`draft_delivery`、`scheduler` 输出阶段百分比；DSH 面板与独立 Web 端新增通用 `TaskProgressBar`。 |
| 2 | 创建多本书时任务重复出现 | `POST /api/jobs` 按 `(project, publication_mode)` 去重并以「`《书名》· 日更`」作用域命名；新增 `DELETE /api/jobs/{identity}` 与同书 `generate`/`daily` 互斥校验；`Shell` 切书隔离非全局任务。 |
| 3 | 免费模型无法连接 | `managed-runtime.mjs` 与 `ofm_runtime.py` 自动探测并注入可用 Node / 代理与 Windows SID 权限；`free_pool.py` 与 `provider_client.py` 自愈 `ofm-standalone` 回环端口漂移、屏蔽非账号型渠道误锁 `requires_login`、解除无配置文件 `tokenSaver` 误拦；`FreeChannelCard` 补全渠道列表兜底、保留 `loginUrl`/二维码并恢复 3 秒轮询；`/api/free-model/pool` 支持 `project_id` 与自动设默认绑定。 |
| 4 | 操作交互逻辑复杂 | 整合开书弹窗 `NewBookModal`（左上方快捷切换并新建）、创作约定与文风归并入 `OutlinePage`、`PricingPage` 与 `OperationsPage` 归并入 `CostsPage`、番茄登录直接内嵌至 `PublishPage`。 |
| 5 | 样式缺失与前端交互 bug | 在 `assets/atelier-native.css` 补齐 26 个丢失的 `.nh-*` 工具类与 `--nh-text-3`，修复 `.nh-body { z-index: auto }` 解除弹窗被顶栏遮挡问题，修复 `.cw-popover` 溢出滚动、文本域压扁、`usePoll` 返回值、`Modal` 闭包、文风滑块、记忆纠正字段切换、章节弹窗局部无闪烁刷新与预检提交错误。 |
| 6 | 多任务堆叠到顶部 | 移除 `Shell` 顶部堆叠的 `StatusBar` 与新书 `BookStart` 卡片，改为右上角可折叠任务中心徽标与抽屉（`TaskCenterPopover`），集中展示各作品进度条与一键取消。 |
| 7 | 界面太多且入口重复 | 顶栏主区从 6 个收敛为 4 个（`工作台 / 创作室 / 发布与日更 / 模型与系统`），独立 Web 端 `liquid-glass.js` 同步收敛至 4 个主区，并保留旧路由兼容跳转别名。 |
| 8 | 新书陷入死结无法开始第一章 | 统一 `writer_runner` 与 `skill_executor` 细纲章节编号识别（支持前导零、中文数字及 Markdown 变体），单模型无首章细纲时自动兜底规划；`studio.batch()` 自动清理遗留空首章冻结批次并提供前端「继续 / 放弃旧批次」按钮；规划缓存键纳入 Role A 模型配置与开关。 |
| 9 | 审查过多阻断新章节产出 | 所有章节自动审查固定为 **最多 2 次**（`MAX_AUTO_REVIEWS = 2`）；第 2 次仍未通过时立即停止自动审查，将正文、回执与进度以 `needs_human_review` 落盘提交以放行后续第 N+1 章创作，仅平台发布门禁须人工点击「人工复核通过」（`POST /api/projects/{id}/chapters/{ch}/approve-review`）解锁；默认日更 `max_revisions` 下调至 `1`。 |

## 离线自动化验证结果（2026-11-26）

- **JS / 前端门禁与包契约（`npm test`）**：`113 pass / 0 fail / 1 skipped (macOS 仅在 Darwin 环境运行)`（共 114 项，涵盖 `client.test.mjs`、`gate.test.mjs` `WRITE_ROUTES` 防漂移、`manifest.test.mjs`、`p04-bridge.test.mjs` 等）。
- **后端集成层（`backend/integration`）**：`736 tests` 通过（`0 fail / 0 error / 4 skipped`），耗时 `104.046s`。
- **后端管理服务层（`backend/manager`）**：`168 tests` 通过（`0 fail / 0 error`），耗时 `49.176s`。
- **发布清单与纯 LF 校验（`node scripts/check-release.mjs --local`）**：全部受管文件哈希、纯 LF 行尾、`market/*`、`runtime-manifest.json` 与 `runtime-download.json` 校验通过。

## 真实环境边界声明

- 上述自动化测试均在离线隔离目录及本地 mock 夹具下完成，**未消耗真实付费模型额度**，**未向真实番茄/七猫作家后台写入数据**，也**未在本任务中实机运行 macOS / Linux 物理机客户端或合并 PR / 打 Tag / 发布 npm**。
