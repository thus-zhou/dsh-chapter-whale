# 0.7.5 插件市场同步记录

更新日期：2026-11-26。版本 `0.7.5`；Windows 轻量包复用固定 `v0.7.0` 运行时，安装本包后端；macOS 使用隔离 Python 环境。

| 渠道 | 本轮状态 | 证据 |
| --- | --- | --- |
| GitHub Release | 已公开，包 12,462,042 字节 | [v0.7.5](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.5) |
| npm | 已公开，latest=0.7.5，公开下载与GitHub包逐字节一致 | [发布后校验](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45785086229) |
| 自托管市场 | index.json、catalog-entry.yml、losebird-entry.json 已更新为0.7.5 | [索引](index.json) |
| awesome-dsh-plugin / dshmarket | 0.7.3 更新已合并；0.7.5 更新已同步至 PR #18894，等待审核 | [PR #18894](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/18894) |
| losebird | 已收录，当前公开快照仍为v0.7.3，等待自动刷新 | [公开目录](https://raw.githubusercontent.com/losebird/dsh-plugin-market/main/registry/all.json) |
| Open Plugin Market、DSH Plugin Hub | 既有收录申请已关闭，按npm索引刷新；不重复投稿 | [机器记录](submissions.json) |
| 2BingLing、bradeGithub、LivXue | 保留自动发现资料，第三方缓存刷新单独核对 | [机器记录](submissions.json) |

[源代码跨平台检查](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45783829392) 与 [公开包首装检查](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45784580478) 已通过。社区申请提交、维护者合并、npm公开可下载及第三方目录显示新版是不同状态，不相互替代。

个人桌面插件安装未修改。完整修复证据见 [复测记录](../docs/retest-0.7.5.md)。
