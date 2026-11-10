# 第三方组件与来源

本软件由多个组件组合而成，项目使用 AI 辅助开发。以下保留随包组件要求的声明。

| 组件 | 许可状态 | 处理 |
| --- | --- | --- |
| 原 dsh-novel-helper 连接器 | MIT，保留原 LICENSE | 新增托管环境与首装功能另见修改记录 |
| webnovel-writer 写作器 | 上游 README 声明 GPL v3 | 保留 README，随包附 GPL v3 全文与修改记录；对应源码在 backend/webnovel-writer/，原仓库为 https://github.com/981029l/webnovel-writer |
| 发布适配组件 | AI 辅助开发 | 依据维护者确认的来源说明，不附加个人署名 |
| Our Free Model 及锁定依赖 | MIT 等，保留各目录许可证 | 来源与本地补丁见 backend/vendor/ofm-source-lock.json |
| Python | PSF License，随官方发行保留 LICENSE.txt | 下载来源和 SHA-256 见 runtime-manifest.json |
| Chromium / Playwright / Python 依赖 | 各自许可 | 保留发行包和 dist-info 中的许可证，不删除相关文本 |

权利与联系处理：如发现来源、许可或权利问题，请通过仓库 Issue 联系维护者；维护者将核实并处理。此说明不替代任何组件的许可证。

修改记录（2026-11-10）：增加自带 Windows 环境、独立用户数据目录、首装建书与登录入口、作品切换和发布账号/书名选择；托管模式不读取旧的全局模型配置。现有个人部署没有被替换。
