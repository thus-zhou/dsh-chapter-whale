# 插件市场投稿与收录记录

更新日期：2026-11-15。当前插件版本为 0.5.0，固定运行时版本为 0.4.2。两者按同一 buildId 和归档摘要核对。

本轮状态：

- [GitHub 0.5.0](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.5.0) 已标记为 Latest；自定义市场索引同步到 0.5.0。
- npm `latest` 为 0.5.0；公开下载包与 GitHub 资产、本地验收包一致：16,754,442 字节，SHA-256 `93da62981dd261e9e81b6a8a7138e27e908c05d62db295cf31451261a10ef0cb`。
- 社区目录已合并此前的 [0.4.2 更新 #15347](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/15347)，[更新 #15398](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/15398)现已改为 0.5.0，并附新版演示图入口，仍待维护者合并。
- [实际发行包 Windows 首次启动检查](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/43723929446)和[源码检查](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/43723834223)通过。当前轻量包完成线上运行时下载、校验、启动与写作引擎导入；0.5.0 原生界面另在 DSH 0.2.2-rc.1 独立环境验证。
- README、上手指南及[演示图文档](../docs/screenshots.md)已替换为九张新版界面图，市场资料引用同一套图。按用户要求不更新个人本机插件。

以下表格保留首次投稿的历史记录，不代表已重新核对所有第三方市场的当前缓存。

- npm：https://www.npmjs.com/package/dsh-chapter-whale
- GitHub 完整包：https://github.com/thus-zhou/dsh-chapter-whale/releases/latest
- 自定义市场索引：https://raw.githubusercontent.com/thus-zhou/dsh-chapter-whale/main/market/index.json

## 当前进度

| 市场 / 目录 | 状态 | 入口 |
| --- | --- | --- |
| awesome-dsh-plugin / dshmarket | 首次申请已合并；新版本见上方记录 | [申请或市场](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/14316) |
| losebird DSH Plugin Market | 历史申请已关闭；当前收录状态待核对 | [申请或市场](https://github.com/losebird/dsh-plugin-market/pull/90) |
| Open Plugin Market / dshopen.org | 已投稿，待审核 | [申请或市场](https://github.com/polang233/dsh-plugin-index/issues/430) |
| DSH Plugin Hub / dsh-plugin.org | 已投稿，待审核 | [申请或市场](https://github.com/dshplugin/dsh-plugin-hub/issues/738) |
| 2BingLing DSH Market / dsh.market | 已在公开目录中核对到条目 | [申请或市场](https://github.com/2BingLing/dsh-market/issues/373) |
| bradeGithub DSH Plugins Marketplace | 已在公开目录中核对到条目 | [申请或市场](https://github.com/bradeGithub/DSH-Plugins-Marketplace) |
| LivXue DSH Plugin Shop | 已满足自动发现条件，待刷新 | [申请或市场](https://github.com/LivXue/dsh-plugin-shop) |

“已投稿”表示申请已经公开提交，不表示维护者已经通过审核或完成上架。自动收录状态依据公开目录快照核对，不代表对所有宿主、平台账号和模型完成过人工验收。

## 后续更新方式

- 主流 dshmarket 使用 awesome-dsh-plugin 社区目录。这里只提交一个 YAML 文件，见 `catalog-entry.yml`；没有向市场应用仓库重复提交插件条目。
- losebird 市场只添加一个 curated JSON 文件，见 `losebird-entry.json`；其一键安装来源已设为公开 npm 包，仓库内的真实组件声明保持不变。
- 开放插件市场与 DSH Plugin Hub 已收到 npm 版本、实测安装命令、Windows 与 DSH 版本范围、实机图和组件信息。
- 2BingLing 与 bradeGithub 市场通过 dsh-plugin topic 已自动发现。前者另提交作者自述与安装资料，供后续更新。
- LivXue 市场按 npm keywords 与 GitHub topics 自动发现，不要求重复开收录申请。保留 dsh-plugin、deepseek-harness 等准确标签，等待其目录刷新。
- 机器可读的申请链接与核对来源在 [submissions.json](submissions.json)。后续审核意见请在原申请跟进，避免重复投稿。

## 安装与更新

DSH 桌面版在应用内插件管理添加 `dsh-chapter-whale`。使用 dsh web 的用户：

```powershell
dsh plugin --profile web add dsh-chapter-whale
dsh plugin --profile web update dsh-chapter-whale
```

安装或更新后重启对应的 DSH。自定义 profile 将 web 换成实际名称。npm 包首次启动自动下载并校验固定运行环境；GitHub 完整包包含运行环境。详见 [上手指南](../docs/quickstart.md)。
