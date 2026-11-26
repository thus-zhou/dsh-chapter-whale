# 码章鲸 0.7.5 验证与发布前记录

0.7.5 在 `feat/v0.7.5` 分支完成对 0.7.4 用户反馈 9 大问题的修复、界面四工作区收敛、免费渠道自愈与「最多 2 次自动审查转人工复核」闭环重构。逐项修复和回归证据见 [复测记录](docs/retest-0.7.5.md)，行为变更见 [更新日志](CHANGELOG.md)。

Windows 轻量插件复用 [v0.7.0 固定 Python 与浏览器运行时](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.0)，始终从 0.7.5 插件包安装后端代码。代码包与运行时清单分别计算 SHA-256 与 `buildId` 校验。

## 2026-11-26 离线验收规模

- **Node / 面板与宿主桥契约（`npm test`）**：共 114 项，`113 pass / 0 fail / 1 skipped`（macOS 首装用例在 Windows 跳过）。
- **后端集成层（`python -B -X utf8 -m unittest discover -s backend/integration -t backend`）**：共 `736` 项，全部通过（`0 fail / 0 error / 4 skipped`）。
- **后端管理层（`python -B -X utf8 -m unittest discover -s backend/manager -t backend`）**：共 `168` 项，全部通过（`0 fail / 0 error`）。
- **发行门禁校验（`node scripts/check-release.mjs --local`）**：通过（受管清单、纯 LF 行尾、`runtime-download.json` 对齐及市场条目一致性全部核验）。

## 未实测边界说明

- 模型接口与免费渠道服务探测/连接修复以离线测试夹具及本地路由测试验证，未使用真实外部账号凭证或消耗付费额度进行端到端真实生成，真实番茄/七猫写入及 macOS/Linux 物理机环境仍须合入后按实际环境验收。
- 当前仅提交至 PR 分支 `feat/v0.7.5`，**未合并至 `main`、未打 `v0.7.5` 标签、亦未发布至 npm / GitHub Release**。
