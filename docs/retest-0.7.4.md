# 0.7.4 审计修复与复测

目标：修复 2026-11-25 对 0.7.3 审计确认的 14 项缺陷。版本号采用 semver `0.7.4`。

| 编号 | 修复 | 回归证据 |
| --- | --- | --- |
| F01 | 提取结果产生后校验实体名，独立应用入口在写文件前验证集合和路径 | `test_audit_074` 真实提取、应用和 `_sync_committed_artifacts` 创建地点档案并保存 synced 回执 |
| F02 | 比对当前插件后端指纹，升级先验证归属、进程命令、活动操作和执行锁 | `test/upgrade.test.mjs`、`manager.test_upgrade`；`scripts/verify-upgrade.mjs` 使用前后版本真实 tarball |
| F03 | 未指定浏览器路径时保留 Playwright 默认发现行为 | `test_audit_074` 在无覆盖变量分支进入登录逻辑，浏览器使用桩 |
| F04 | 保存原批次、故障类型与恢复时间；网络重试有上限，配置问题暂停 | `test_draft_delivery` 等待前不派发，重读状态后到期恢复原目标；总览显示恢复时间 |
| F05 | 正文、审查、记忆、实体、RAG 与连续性就绪才计成功；恢复只补同一正文 | `test_draft_delivery` 分别注入四类后保存失败；`test_notification_hooks` 验证暂停事件 |
| F06 | 读取手写 Markdown 章纲，编辑后以当前章纲为准，缺细纲停止 | `test_scenes` 验证请求包含关键事件，以及 Markdown 覆盖旧 JSON 规划 |
| F07 | 缓存绑定提示词、创作约定、目标篇幅、场景划分和前场衔接 | `test_scenes` 验证相同输入零请求，修改输入后重新生成，失败后仅补未完成场景 |
| F08 | 读取归属和知情记录时验证当前正文摘要及引文；保留历史，重提取恢复 | `test_entity_state` 覆盖改稿、删稿、重提取与同章歧义 |
| F09 | SSE EOF 缺少 DONE/finish_reason 时报告中断，保留已收到内容 | `test_audit_074` 本地 HTTP 服务验证提前 EOF、DONE 与 finish_reason |
| F10 | 零次修订不再变成一次 | `test_draft_delivery.test_zero_revisions_reaches_generator` |
| F11 | 指标提交、评论与撤销使用同一事务锁，批次使用随机 ID | `test_reader_metrics` 并发提交一个成功、另一个过期，无覆盖丢失 |
| F12 | 补充日期解析所需的 re 导入 | `test_audit_074` 验证斜线日期解析 |
| F13 | 摘要提供真实最大章号，Web 预检和检索使用该字段；空作品给出提示 | `manager.project_summary` 和独立 Web 章号调用路径，只有第5章时不再请求第1章 |
| F14 | 审查否定结论优先识别，未知结论不直接放行 | `test_audit_074` 真实 normalize → quality_gate，六项90分仍拒绝“不通过，需修改” |

本地验证命令：

```powershell
npm test
python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend
python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend
node scripts/check-release.mjs --local
```

首次安装由 `scripts/verify-package.mjs` 在独立工作区验证，跨版本升级由 `scripts/verify-upgrade.mjs` 对照实际包验证。代码复审使用 `codex review --uncommitted`，确认的问题修复后复测并重新审查。公开发行和市场回读状态见 [发行记录](../RELEASE_STATUS.md) 和 [市场记录](../market/submissions.json)。

这些验证不等于真实模型文笔、真实平台发布或所有物理设备验收；本轮没有调用真实模型及发布账号。
