# 码章鲸 0.7.5 验证与发布记录

0.7.5 在 `feat/v0.7.5` 分支完成对 0.7.4 用户反馈 9 大问题的修复、界面四工作区收敛、免费渠道自愈与「最多 2 次自动审查转人工复核」闭环重构。逐项修复和回归证据见 [复测记录](docs/retest-0.7.5.md)，行为变更见 [更新日志](CHANGELOG.md)。

Windows 轻量插件复用 [v0.7.0 固定 Python 与浏览器运行时](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.0)，始终从 0.7.5 插件包安装后端代码。代码包与运行时清单分别计算 SHA-256 与 `buildId` 校验。

## 2026-11-26 审计后离线验收规模

- **Node / 面板与宿主桥契约（`npm test`）**：共 125 项，`109 pass / 0 fail / 16 skipped`（Linux；Windows/macOS 条件用例跳过）。
- **后端集成层（`python -B -X utf8 -m unittest discover -s backend/integration -t backend`）**：共 `828` 项，全部通过（`0 fail / 0 error / 8 skipped`）。
- **后端管理层（`python -B -X utf8 -m unittest discover -s backend/manager -t backend`）**：共 `187` 项，全部通过（`0 fail / 0 error`）。
- **干净源码门禁（`node scripts/check-release.mjs --local`）**：1168 个文件通过，跳过 2253 个缺席 runtime 项，buildId `9f1cc34920fe1c62b5579e0b3e3e5d9708df20ed728b49a21290cc38e4625e2a`。
- **完整包门禁（HEAD 源码 + 真实 v0.7.0 runtime）**：3421 个文件全部通过，`downloadRuntime()` 用真实归档字节复现成功。

> `--local` 的 1168 与完整包的 3421 不是同一个口径；前者不校验缺席的 runtime 项，不能单独证明运行时归档对齐。
> `buildId` 覆盖 `backend/` 与 `runtime/` 受管文件（3421 项），不包含 `client.js`、`index.js`、`managed-runtime.mjs` 等根入口；这些文件由客户端/宿主契约测试覆盖。

## 公开发布与 CI 验证状态

- **GitHub Release**：[v0.7.5](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.5) 已发布并设为 `latest`（`dsh-chapter-whale-0.7.5.tgz`，`12,462,042` 字节，SHA-256 `c52e25826c89f626de2fedb691eb108cbc72c98389c57b9f4bc554c77f46bce0`）。
- **npm 仓库**：[`dsh-chapter-whale@0.7.5`](https://www.npmjs.com/package/dsh-chapter-whale) 已由 [npm-publish 工作流 #45785086229](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45785086229) 发布为 `latest`，在线包校验与轻量归档逐字节一致。
- **跨平台源码门禁**：[Source checks #45783829392](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45783829392) 全部 10 项作业通过（Ubuntu / Windows / macOS × Node & Python 3.11/3.13 + `macos-first-start`）。
- **公开包首启验证**：[Distribution first start #45784580478](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45784580478) 通过（Windows 完整包 + 轻量包在线拉取 `v0.7.0` 运行时、macOS 隔离 `.venv` 首启）。
- **插件市场同步**：自托管市场清单（`market/index.json`、`market/losebird-entry.json`、`market/catalog-entry.yml`）已更新至 `0.7.5`，社区目录 [awesome-dsh-plugin PR #18894](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/18894) 已同步更新至 `0.7.5` 等待审核。

## 未实测边界说明

- 模型接口与免费渠道服务探测/连接修复以离线测试夹具及本地路由测试验证，未使用真实外部账号凭证或消耗付费额度进行端到端真实生成，真实番茄/七猫写入及 macOS/Linux 物理机环境仍须按实际环境验收。
