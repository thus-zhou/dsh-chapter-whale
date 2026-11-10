# 组合层命令与状态

主使用方式是 O:\小说助手\启动小说助手.cmd 和 http://127.0.0.1:8765。此目录提供同一流程的 CLI 入口，保持原写作、发布仓库的独立结构；上游运行时代码已包含本次审查修复。

## 核心链路

writer_runner：A 大纲 → B 正文 → C 润色 → D 审查／E 授权 → 原子保存正文和内容绑定回执 → 角色/RAG/连续性同步。未启用多模型时兼容原单模型流程。

bridge：来源验证 → Markdown 转 TXT → 绑定项目/书名/账号 → 发布器 → 明确平台状态与正文匹配 → 回执及归档。

scheduler：固定当天时段批次 → 恢复未完成的同一批次 → 内容资格与发布证据核对 → 记录结果。网页支持每日 1–8 个时段，每个时段独立配额，同一成功时段不会再次生成发布。

model_roles：各角色独立模型／连接、凭据隔离、一次运行配置快照和实际请求路由。studio：TXT 分段学习与断点、约定扩写预览、A 剧情规划、固定批量创作和旧稿润色备份。
memory_library：每本书独立的共享记忆，作者确认优先、正文引用／哈希绑定、按主题与章节检索。A–E 实际请求接入；正文保存后 D 提取事实，已知提取失败先修复再写下一章。原有角色／RAG／连续性记录仍保留。详见根目录共享记忆库说明.md。

## 常用命令

```powershell
$py = "O:\小说助手\.venv\Scripts\python.exe"

& $py .\integration\bridge.py login --account "主账号"
& $py .\integration\bridge.py accounts
& $py .\integration\writer_runner.py --project "O:\小说项目" --dry-run
& $py .\integration\writer_runner.py --project "O:\小说项目" --word-count 3500 --max-revisions 2
& $py .\integration\writer_runner.py --project "O:\小说项目" --review-existing --chapter 1
& $py .\integration\bridge.py stage --project "O:\小说项目" --book-name "平台书名" --chapter 1
& $py .\integration\bridge.py publish --project "O:\小说项目" --book "平台书名" --account "主账号" --count 1
& $py .\integration\bridge.py status
```

CLI login 仍需要在浏览器登录后回终端按回车。推荐使用管理界面的登录确认功能，由后台检测作者后台控件后保存。发布器读取指定账号状态文件，不交换根 state.json，也不打印 Cookie。

CLI stage 是显式转换工具，不代表审查通过；实际 publish 会检查源文件、TXT、内容资格回执和账号绑定。管理界面的入队选择 D 明确通过或 E 有效授权的章节。修改正文或约定后必须重新处理；不得手工编辑回执以绕过检查。

在 AI 设置选择“全自动决策”，E 可以明确豁免 D 意见；记录为 waived_by_E，授权绑定正文哈希，并非审查通过。严格模式不接受旧 E 豁免。E 负责发布工具调用前的决策，可以停止提交，但不能伪造平台登录或把没有证据的提交记成成功。发布仍由浏览器执行器实际操作，不赋予模型任意操作系统命令权限。

## 任务

```powershell
& $py .\integration\scheduler.py add --job-id "日更A" --project "O:\小说项目" --book "平台书名" --account "主账号" --time 08:00 --chapters-per-run 1 --word-count 3500
& $py .\integration\scheduler.py list
& $py .\integration\scheduler.py run-once --job-id "日更A"
& $py .\integration\scheduler.py disable --job-id "日更A"
& $py .\integration\scheduler.py enable --job-id "日更A"
& $py .\integration\scheduler.py settings --auto-schedule on
& $py .\integration\scheduler.py daemon
```

自动调度开关默认关闭；界面与 daemon 共享该开关。按日期批准模式：

```powershell
& $py .\integration\scheduler.py approve --job-id "日更A" --for-date "2026-10-13"
```

confirm_24h 是兼容字段名，行为是按日期批准，并不是一个提醒系统。任务配置实质改变会撤销旧批准。--force 可以忽略停用或日期批准，但仍不能忽略当天时段已成功的配额、内容资格或内容完整性检查。失败时先恢复原时段，不自动追加新一批；CLI add 的 --time 保持单时段兼容，多时段通过网页设置。

## 发布证据

逐章任务失败后继续原日更任务，不另建手工创作批次。提交前的临时模型故障保留原中间稿、修改历史和累计次数，按有界退避恢复；C输出截断、空补丁或无效JSON不算修订成功。鉴权、额度耗尽、正文/账号冲突或恢复预算耗尽会明确停止。

点击提交后结果不明，只能对原章节做只读核验，不能再次提交。平台正文与状态确认后才归档；字数以真实“字数”列为准，未知数字不按0累计、不使用本地估算替代。

章节超过15条时会出现分页。发布器仅操作当前页签的分页，扫描全部页和草稿箱核对重复；支持番茄已观察到的Arco列表控件及明确容器内按钮。屏幕外的其他页签控件不参与查询，字数刷新不算翻页完成；未知布局会停止，不能靠删回执或再次发布绕过。修复布局后应先只读恢复原提交，再继续原批次。

- platform_confirmed：章节列表状态“已发布”，对应正文一致，且具备匹配账号的回执。
- archive_unverified：只有旧归档文件，没有相应证据；不计入已发布，也不自动重发。
- submitting / unconfirmed：提交已开始但结果不确定；停止自动重发，要求核对平台。
- blocked_before_submit：提交前被登录、风险、书籍、标题、DOM、声明等条件阻断。

结构化报告位于 fanqie_auto_publish/.publication/reports。API bridge.latest_publish_report(book, account) 返回 report_path 与 verified_success。退出码 0 单独不能证明发布成功。

平台 DOM 变动会停止流程，需要针对真实页面适配。本次离线模拟和回归通过不代表已经完成真实账号发文，更不能据此承诺收益。
