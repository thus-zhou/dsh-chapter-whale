# 码章鲸 0.7.5 验证与发布前记录

0.7.5 在 `feat/v0.7.5` 分支完成对 0.7.4 用户反馈 9 大问题的修复、界面四工作区收敛、免费渠道自愈与「最多 2 次自动审查转人工复核」闭环重构。逐项修复和回归证据见 [复测记录](docs/retest-0.7.5.md)，行为变更见 [更新日志](CHANGELOG.md)。

Windows 轻量插件复用 [v0.7.0 固定 Python 与浏览器运行时](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.0)，始终从 0.7.5 插件包安装后端代码。代码包与运行时清单分别计算 SHA-256 与 `buildId` 校验。

## 2026-11-26 审计后离线验收规模

- **Node / 面板与宿主桥契约（`npm test`）**：共 125 项，`109 pass / 0 fail / 16 skipped`（Linux；Windows/macOS 条件用例跳过）。
- **后端集成层（`python -B -X utf8 -m unittest discover -s backend/integration -t backend`）**：共 `827` 项，全部通过（`0 fail / 0 error / 8 skipped`）。
- **后端管理层（`python -B -X utf8 -m unittest discover -s backend/manager -t backend`）**：共 `187` 项，全部通过（`0 fail / 0 error`）。
- **干净源码门禁（`node scripts/check-release.mjs --local`）**：1168 个文件通过，跳过 2253 个缺席 runtime 项，buildId `efba5d3f679f414181911b8299ce297cec1a470a3fe2dd99315ea3f9736c23de`。
- **完整包门禁（HEAD 源码 + 真实 v0.7.0 runtime）**：3421 个文件全部通过，`downloadRuntime()` 用真实归档字节复现成功。

> `--local` 的 1168 与完整包的 3421 不是同一个口径；前者不校验缺席的 runtime 项，不能单独证明运行时归档对齐。
> `buildId` 覆盖 `backend/` 与 `runtime/` 受管文件（3421 项），不包含 `client.js`、`index.js`、`managed-runtime.mjs` 等根入口；这些文件由客户端/宿主契约测试覆盖。

## 未实测边界说明

- 模型接口与免费渠道服务探测/连接修复以离线测试夹具及本地路由测试验证，未使用真实外部账号凭证或消耗付费额度进行端到端真实生成，真实番茄/七猫写入及 macOS/Linux 物理机环境仍须合入后按实际环境验收。
- 当前仅提交至 PR 分支 `feat/v0.7.5`，**未合并至 `main`、未打 `v0.7.5` 标签、亦未发布至 npm / GitHub Release**。
