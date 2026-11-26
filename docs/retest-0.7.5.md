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

## 0.7.5 审计后修复（2026-11-26）

全量审计（4 个 P0、27 个 P1）发现的阻塞项已在 `feat/v0.7.5` 修复并补回归测试：

- **运行时安装**：恢复 v0.7.0 归档的 182 个原始 CRLF/LF 字节哈希，`runtime-download.json` 与新 `buildId` 对齐；当前轻量包全新 Windows 安装不再在 `downloadRuntime()` 拒绝。
- **任务去重**：`POST /api/jobs` 只合并客户端 `model_fields_set` 中的字段，不再用默认值清空 `serial`、配额、时段、排期或 `enabled`。
- **人工复核隔离**：handoff 章节的事实/人物候选只保存为 pending，不写入共享记忆/人物档案；人工 `approve-review` 后才提交。
- **排期门禁**：`platform_scheduled` 在生成前后都检查待复核章，禁止跳过第 N 章继续排第 N+1 章。
- **审查预算**：长度补写/字数纠错不再产生第 3 次 D 审查；`max_revisions=0` 首次未通过直接转人工。
- **前端契约**：批次 `id`、`CostRateInput`、自定义供应商 `models`、发布账号、13 个渠道真实 ID、成本页 `Bars` 崩溃、双端新建任务的 `publication_mode` 均已修复。
- **免费模型/安全**：端口自愈更新真实 client、Node ≥22.21 校验、显式作品授权、`set_default` 不再隐式改全局、`owned_ports` owner 校验、tokenSaver fail-closed。

## 发行、市场与入口修复（E 域，2026-11-26）

| 编号 | 修复 | 回归验证 |
| --- | --- | --- |
| P2-21 | `check-release` 只在 `--local` 跳过缺席的 `runtime/` 项；完整包模式缺 `runtime/` 或 `runtime/python/python.exe` 直接失败 | `scripts/test-release-fix.mjs`：同一份薄清单带 `--local` 通过、不带 `--local` 非零退出并报 runtime 缺失 |
| P2-22 | `pack-bundle.py` 完整包名/URL 改用 `manifest.version`（runtime 0.7.0）；不再覆盖源码根部的 `runtime-download.json`（该文件继续描述已发布的 v0.7.0 runtime 资产及其 `runtimeAssetBuildId`） | 新测试在隔离目录真实执行 `pack-bundle.py`，断言输出 `...runtime-win32-x64-0.7.0.tgz`、`bundle.json` 的 runtime/package 版本正确，并断言完整包前后下载描述逐字节不变 |
| P2-23 | `market/index.json`、`losebird-entry.json`、`catalog-entry.yml` 恢复到已发布的 0.7.4；`check-release` 允许 market 落后于 `package.json` 并给出 note，禁止高于 `package.json` | 新测试断言三处均为 0.7.4、仓库 `--local` 通过且带滞后 note；临时 fixture 中 0.8.0 必须失败 |
| P2-25 | 复跑顺序改为先 `check-release --local` 再跑 backend 测试；测试后再次跑门禁前清理 `backend/integration_data` | 新测试检查文档中的命令顺序与清理命令；`check-release` 继续拒绝 `backend/integration_data` |
| P3-3 | 按 Python 的 `sha256(json.dumps(files, sort_keys=True))` 复算 `buildId`，校验 `packageVersion === package.json.version`，清单拒绝 `test_*.py` | 新测试用 Python 生成的固定 buildId 校验通过；篡改 buildId/packageVersion、加入 `test_foo.py` 均非零退出 |
| P3-4 | README L250 改为「当前分支 `0.7.5` 插件」，与文末「0.7.5 尚未发布」一致 | 新测试断言 README 不再出现「当前 `0.7.4` 插件」 |
| P3-5 | `index.js ensureStarted` 在启动循环每轮及 `delay(600)` 后检查 `signal.aborted`，中止时 kill 子进程并返回 `{started:false, aborted:true}` | 新测试用 600 秒启动超时和 100ms 中止，断言 5 秒内返回 `aborted:true` |

## 离线自动化验证结果（2026-11-26，审计修复后）

复跑顺序（P2-25）：发行门禁必须在干净树先跑。backend 测试会写入 `backend/integration_data`，测试后再次执行门禁前先清理。

```bash
node scripts/check-release.mjs --local        # 先跑发行门禁（干净树）
npm test                                       # JS / 前端契约
PYTHONPATH=backend python -m unittest discover -s backend/integration -t backend
PYTHONPATH=backend python -m unittest discover -s backend/manager -t backend
rm -rf backend/integration_data                # 测试残留；再次执行门禁前必须清理
```

- **干净源码清单校验（`node scripts/check-release.mjs --local`）**：**1168 个文件通过，跳过 2253 个缺席 runtime 项**，buildId `efba5d3f679f414181911b8299ce297cec1a470a3fe2dd99315ea3f9736c23de`；P3-3 起该命令同时复算 buildId、校验 `packageVersion`，并允许 market 以 0.7.4 滞后于 `package.json`（输出 note）。
- **完整包校验（HEAD 源码 + 真实 v0.7.0 runtime）**：**3421 个文件全部通过**，同一 buildId `efba5d3f679f414181911b8299ce297cec1a470a3fe2dd99315ea3f9736c23de`；`downloadRuntime()` 用真实归档字节复现成功。
- **JS / 前端门禁与包契约（`npm test`）**：**125 项，109 pass / 0 fail / 16 skipped**（Linux；Windows/macOS 条件用例跳过），含 `test/client-ui.test.mjs` 的真实递归渲染回归。
- **后端集成层（`backend/integration`）**：**827 tests OK（skipped=8）**，约 35s。
- **后端管理服务层（`backend/manager`）**：**187 tests OK**，约 33s。
- **CSS 内联**：`scripts/build-client-ui.py` 生成结果与 `client.js` 字节一致；新增 26 个唯一 `.nh-*` 选择器。

## 真实环境边界声明

- 上述自动化测试均在离线隔离目录及本地 mock 夹具下完成，**未消耗真实付费模型额度**，**未向真实番茄/七猫作家后台写入数据**，也**未在本任务中实机运行 macOS / Linux 物理机客户端或合并 PR / 打 Tag / 发布 npm**。
- `--local` 跳过 2253 个 runtime 项；完整包校验使用真实 v0.7.0 归档，二者不可混为一个数字。
- Node 版本/代理、Windows DPAPI/PowerShell、macOS `lsof` 跨用户等平台边界仍以代码审查与平台条件测试为准，未做三平台实机点验。
