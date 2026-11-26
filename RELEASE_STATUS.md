# 码章鲸 0.7.4 验证与发行记录

0.7.4 修复了 0.7.3 全量审计确认的 F01–F14。逐项修复和回归证据见 [复测记录](docs/retest-0.7.4.md)，行为变更见 [更新日志](CHANGELOG.md)。

公开安装入口为 [GitHub v0.7.4](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.4) 和 [npm 版本列表](https://www.npmjs.com/package/dsh-chapter-whale?activeTab=versions)。发行流水线核对 GitHub 附件与公开 npm 下载字节一致，并检查 npm latest；具体执行状态以 [Actions](https://github.com/thus-zhou/dsh-chapter-whale/actions) 为准。

Windows 轻量插件复用 [v0.7.0 固定 Python 与浏览器运行时](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.0)，始终从 0.7.4 插件包安装后端代码。插件代码、运行时归档和运行中的后端指纹分别核验。macOS 首启使用 Python 3.11+ 创建隔离 .venv。

托管升级先确认实例身份、进程命令、活动操作和执行锁。空闲旧实例安全重启；有活动任务时保留原任务并显示待升级，不将旧代码视为新版就绪。外部手动启动的服务由原启动器停止。

离线回归覆盖真实实体提取与落库、存稿等待与恢复、四种后保存资料失败、场景缓存失效、实体重提取、SSE 提前结束、并发指标提交与中英文审查结论。模型和浏览器交互使用本地固定响应，未消耗真实模型额度，也未执行真实平台投稿。物理 Intel Mac、真实账号登录、平台定时发布及外网通知仍须按实际环境验收。

市场元数据和社区目录申请见 [投稿记录](market/SUBMISSION.md)。第三方市场由维护者审核或定时刷新，提交更新与实际显示新版分别记录。个人桌面插件安装不在本次发行修改范围内。

## 2026-11-26 公开验收

- [源码跨平台检查](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45726135357) 10 项作业全部通过，覆盖 Windows/Ubuntu/macOS、Python 3.11/3.13 和 macOS 首装。单环境检查规模为 Node 114 项、集成层 731 项、管理层 164 项，环境相关跳过项单独保留。
- [公开发行包首装](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45726703953) Windows 与 macOS 两项通过。实际 0.7.3→0.7.4 包升级在独立 Windows 工作区通过；不支持派发屏障的旧版先点击“停止旧后端”，再重试升级。
- GitHub 插件包 12,472,213 字节，SHA-256 `cda1984aafaf967a02c92d516266233d90f15c763991b9fdffa01e86a8180b50`。代码 buildId `08969775b62761f3c792fd54c1fc9af9285b1288693cf267900d19023e2bc8e7`。
- 自动复审确认的问题均已修复并回归验证。最后一轮 `codex review --uncommitted` 被周额度限制中断，**不能视作无问题结论**。
- npm 已接受上传，公开索引与下载字节仍在核对；最终状态见 [市场机器记录](market/submissions.json)。社区目录更新为 [PR #18894](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/18894)，维护者审核与第三方目录刷新分别记录。
