# 插件市场投稿与收录记录

更新日期：2026-11-25（0.7.3 全量审计修复启停与重启恢复、单模型存稿、排期恢复与前后端交互缺陷）。当前插件版本为 `0.7.3`（Windows x64 与 macOS Apple Silicon / Intel 双平台），代码清单 `buildId` 为 `5d373751c849b159df18f80337e3ccdc6758ce5eb27e1617d3c575860f424a46`，Windows 固定运行时归档复用 `v0.7.0`（`runtimeAssetBuildId=b181c5765a6e17a54fdc503b1aab0701a109428fbca8969a08bfc88c82957e4f`；macOS 首启自动建 `.venv`）。

本轮 `0.7.3` 同步状态：

- [GitHub Release v0.7.3](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.3) 已发布为 Latest：
  - 跨平台插件包 `dsh-chapter-whale-0.7.3.tgz`：`12,465,536` 字节，SHA-1 `40a9b8c3626ffd46842c4229072b5e06b712bfa0`，SHA-256 `07801973764488ac33f76f5d3c210cb2239786a696610ce51b7bc911d8f6aa52`。
  - 校验清单 `SHA256SUMS.txt`：`94` 字节，SHA-256 `8067dcac9243aec9d4428b9baa0c28baa07df9c706c3300c7531c7a491b0f30f`。
  - Windows 完整运行时大包沿用 [v0.7.0](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.0) 的 `dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz`（`282,727,542` 字节，SHA-256 `bdb594c6ca122f215ba8068e75453c3688e6cd9e720f40eaa0ae6ac175b8d52d`），始终安装 `0.7.3` 包内后端代码。
  - 自托管索引 [market/index.json](index.json) 已同步至 `0.7.3`（`publishTimestamp: 1795563263`），社区 JSON 条目 [losebird-entry.json](losebird-entry.json) 与 [catalog-entry.yml](catalog-entry.yml) 均已同步至 `0.7.3`。
- npm `latest` 已发布为 `0.7.3`（`https://www.npmjs.com/package/dsh-chapter-whale`，含 SLSA provenance attestation），公开 registry 下载校验与 GitHub Release `v0.7.3` 逐字节一致（`12,465,536` 字节，SHA-1 `40a9b8c3626ffd46842c4229072b5e06b712bfa0`，SHA-256 `07801973764488ac33f76f5d3c210cb2239786a696610ce51b7bc911d8f6aa52`；[Publish verified release to npm #45512631920](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45512631920)）；基于 npm 索引的第三方市场（`Open Plugin Market`、`DSH Plugin Hub`、`2BingLing`、`bradeGithub`、`LivXue`）按 `latest` 自动同步刷新。
- 社区目录已同步更新 [PR #18605](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/18605) 至 `0.7.3`（`open`，Windows x64 + macOS）。
- [Distribution first start 双平台首发校验 #45511406123](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45511406123)（`windows-install` + `macos-install`）及 [Source checks #45511334800](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45511334800)（Windows / Ubuntu / `macos-latest` 与 `macos-first-start`）均已通过；另有 Windows `DSH 0.2.2-rc.3` 隔离沙箱 UI 实装记录（[retest-0.7.0.md](../docs/retest-0.7.0.md)）。
- README、[上手指南](../docs/quickstart.md)、[状态记录](../RELEASE_STATUS.md)、[macOS 说明](../deploy/macos/README.md) 及 [演示图集](../docs/screenshots.md) 已同步。按约束未修改个人桌面端 `0.5.0` 配置。

以下表格保留首次投稿的历史记录，不代表已重新核对所有第三方市场的当前缓存。

- npm：https://www.npmjs.com/package/dsh-chapter-whale
- GitHub 完整包：https://github.com/thus-zhou/dsh-chapter-whale/releases/latest
- 自定义市场索引：https://raw.githubusercontent.com/thus-zhou/dsh-chapter-whale/main/market/index.json

## 当前进度

| 市场 / 目录 | 状态 | 入口 |
| --- | --- | --- |
| awesome-dsh-plugin / dshmarket | 首次申请已合并；0.7.3 更新在 PR #18605 | [申请或市场](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/18605) |
| losebird DSH Plugin Market | 历史申请已关闭；当前收录状态待核对 | [申请或市场](https://github.com/losebird/dsh-plugin-market/pull/90) |
| Open Plugin Market / dshopen.org | 已收录（issue #430 已关闭）；按 npm latest 自动同步 | [申请或市场](https://github.com/polang233/dsh-plugin-index/issues/430) |
| DSH Plugin Hub / dsh-plugin.org | 已收录（issue #738 已关闭）；稳定版按 npm latest 冷却期后自动同步 | [申请或市场](https://github.com/dshplugin/dsh-plugin-hub/issues/738) |
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
