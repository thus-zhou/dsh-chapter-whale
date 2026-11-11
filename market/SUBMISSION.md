# 插件市场投稿与收录记录

更新日期：2026-11-11。npm 包已公开发布，下载内容与本地验收包一致，并通过 DSH 0.2.2-rc.1 的独立 profile 安装验证。

- npm：https://www.npmjs.com/package/dsh-chapter-whale
- GitHub 完整包：https://github.com/thus-zhou/dsh-chapter-whale/releases/latest
- 自定义市场索引：https://raw.githubusercontent.com/thus-zhou/dsh-chapter-whale/main/market/index.json

## 当前进度

| 市场 / 目录 | 状态 | 入口 |
| --- | --- | --- |
| awesome-dsh-plugin / dshmarket | 已投稿，待审核 | [申请或市场](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/14316) |
| losebird DSH Plugin Market | 已投稿，待审核 | [申请或市场](https://github.com/losebird/dsh-plugin-market/pull/90) |
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
