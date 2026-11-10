# 码章鲸 · AI小说写作与番茄发布

**从一个想法，写到下一章。**

DSH 里的长篇小说工作台：做大纲、记住人物和伏笔、生成章节、审查润色，再把你确认的正文交给番茄发布流程。

## 使用方式

在 DSH 的插件管理中添加下方的 GitHub 完整发行包地址，重启 DSH，从侧栏打开「码章鲸」，点击「开始使用码章鲸」。内置 Python、写作后端和 Chromium；无需另装 Python、拉取后端仓库或填写目录。

```text
https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v0.2.0-rc.1/dsh-chapter-whale-0.2.0-rc.1.tgz
```

使用命令行的用户也可以运行：

```powershell
dsh plugin --profile desktop add https://github.com/thus-zhou/dsh-chapter-whale/releases/download/v0.2.0-rc.1/dsh-chapter-whale-0.2.0-rc.1.tgz
```

如果通过 GitHub 源码或市场索引安装，首次启动会自动下载并校验同版本的完整环境；需联网等待下载完成。完整包安装后不需要这一步。

1. 在「开始创作与账号」输入书名、题材和故事想法。
2. 打开「AI 设置」，连接你自己的模型。模型调用由相应服务商计费。
3. 在「创作约定」「大纲与规划」中完善故事，进入「作品与章节」生成、阅读、审查和润色。
4. 需要发布时，在「开始创作与账号」打开番茄登录窗口，自行扫码并完成登录核验。
5. 在番茄作家后台先创建作品；回到「发布队列」，核对账号、平台书名与章节，再确认发布。

登录、验证码、平台审核与作品创建仍由账号本人完成。平台页面变化可能影响发布适配；任务完成与平台发布核验是不同状态，请以平台记录为准。

## 功能

- 长篇记忆：设定、人物、事实、伏笔和章节检查点。
- 多模型分工：规划、初稿、润色、审查与执行。
- 可查看的章节、审查结果和操作历史。
- 发布队列、状态核验与日更任务；全新安装的自动调度默认关闭。
- 模型定价与成本统计。
- 模型工具 `novel_helper` 与面板共用同一套本地接口。

## 环境与数据

当前支持 Windows 10/11 x64，DSH >= 0.2.2-rc.1，Node >= 22。源码安装的首次解包使用 Windows 自带 tar.exe。ARM64、macOS 与 Linux 尚未验收。

作品、账号与配置位于 `%LOCALAPPDATA%\ChapterWhale\workspace`，与插件安装目录分开。后端默认只监听 `127.0.0.1:18765`。更新和卸载插件不会删除作品或账号数据；请自行备份这个目录。

完整包包含浏览器，体积明显大于普通脚本插件。运行时不再临时下载 Python 或浏览器。

## 开发与许可

包名：`dsh-chapter-whale`。搜索关键词：码章鲸、小说助手、AI写作、网文、大纲、长篇记忆、番茄小说、发布。

`backend/` 是不含作品和账号的源码副本；`scripts/build-runtime.py` 从 Python 官方发行和固定版本依赖构建独立环境，输出下载哈希与依赖锁定信息。`runtime/` 为生成产物，不提交到 Git。

当前为 `0.2.0-rc.1` 公开测试版，验收范围见 [RELEASE_STATUS.md](RELEASE_STATUS.md)。各组件声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，根目录 MIT 文本仅对应原连接器代码。
