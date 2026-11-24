# 许可证文本索引（LICENSES/）

本目录保存随发行包分发的许可证全文与版权行。发行层面的取舍与义务映射见 [`docs/license-decision.md`](../docs/license-decision.md)，逐组件盘点见 [`docs/license-inventory.md`](../docs/license-inventory.md)。

| 文件 | 覆盖对象 | 来源 | 校验 |
| --- | --- | --- | --- |
| `GPL-3.0.txt` | `backend/webnovel-writer/`（GPL-3.0-only）及其与后端组成的整体 | 复制自 `backend/webnovel-writer/LICENSE`；内容为 FSF 标准 GPLv3 全文（git blob `f288702d2fa16d3cdf0035b15a9fcbc552cd88e7`） | 35,149 字节 / 674 行 / UTF-8 / LF；含 `GNU GENERAL PUBLIC LICENSE`、`Version 3, 29 June 2007`、`END OF TERMS AND CONDITIONS` |
| `MIT-chapter-whale.txt` | 本项目自有代码（插件外壳、`backend/manager`、`backend/integration` 等） | 复制自根 `LICENSE`（1082 字节） | 含 `MIT License` 与 `Copyright (c) 2026 novel-helper contributors` |
| `MIT-our-free-model.txt` | `backend/vendor/our-free-model-source/` 及其内嵌 `channel-pack`、`dsh-std` | 复制自 `backend/vendor/our-free-model-source/LICENSE`（1068 字节） | 含 `MIT License` 与 `Copyright (c) 2026 Ebony-Vinyl` |

## 为什么没有 `MIT-webnovel-writer.txt`

上游 `981029l/webnovel-writer` 只声明 GPL v3（`backend/webnovel-writer/README.md:3`、`:508-510`），从未以 MIT 授权，仓库里也不存在 MIT 文本。为它放一份 MIT 文件会凭空制造一项上游没有给出的许可，因此本目录只保留其真实的 GPLv3 全文；上游的 GPL 授权与修改说明在 `GPL-3.0.txt` 与 `docs/license-decision.md` 第 7 节。

## 未收录但随包自带的文本

以下组件的许可证文本由组件自身随包携带，未重复复制到本目录：`backend/vendor/**/LICENSE`、`assets/fonts/*-OFL.txt`、`runtime/python/LICENSE.txt`、各 Python 包的 `*.dist-info/`、`node_modules/<pkg>/LICENSE*`、`runtime/browsers/ffmpeg-1011/COPYING.LGPLv2.1`、`runtime/python/Lib/site-packages/playwright/driver/package/{LICENSE,NOTICE,ThirdPartyNotices.txt}`。

## 维护约定

- 新增或升级带 copyleft 的组件时，同时更新本表、`THIRD_PARTY_NOTICES.md` 与 `docs/license-inventory.md`。
- 许可证全文必须原样保存，不得改写、截断或统一换行；校验方式为字节数 + 关键标题行。
- 上游若改为 “or later”，从 https://www.gnu.org/licenses/ 取得对应版本全文后新增文件，并在 `docs/license-decision.md` §3 记录变更。
