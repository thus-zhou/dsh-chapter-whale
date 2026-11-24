# 第三方组件与来源

## 本发行版组合分发说明

本发行版（`dsh-chapter-whale`）内嵌了上游写作器 **webnovel-writer**，其许可证为 **GNU General Public License, Version 3（GPL-3.0-only）**：上游 `backend/webnovel-writer/README.md:3` 与 `:508-510` 只声明 “GPL v3”，未声明 “or later”。该写作器由后端在同一进程内导入并调用（`backend/integration/writer_runner.py:27-29`、`:41-42`），因此**后端与写作器组成的整体按 GPLv3 组合分发**。

- 完整许可证文本位于 [`LICENSES/`](LICENSES/)：GPLv3 全文见 `LICENSES/GPL-3.0.txt`（35,149 字节 / 674 行），本项目自有代码的 MIT 文本见 `LICENSES/MIT-chapter-whale.txt`，vendor 的 MIT 文本见 `LICENSES/MIT-our-free-model.txt`。
- 对应源码、上游基线提交、构建脚本（`scripts/build-runtime.py`、`scripts/pack-bundle.py`）、依赖锁定文件与可直接复制的重建命令，见 [`docs/license-decision.md`](docs/license-decision.md) 第 6 节；修改说明见同文件第 7 节。
- 本项目自有代码仍以 MIT 授权；插件外壳、字体、Python/Node 运行时与浏览器属于独立程序或独立资源，按各自许可证分发，不因组合分发而改变。
- 逐组件的版本、来源 URL、许可证文本位置与证据行号见 [`docs/license-inventory.md`](docs/license-inventory.md)。

## 组件清单

### 内嵌与派生组件

| 编号 | 组件 | 版本 | 许可证 | 来源 | 许可证文本位置 |
| --- | --- | --- | --- | --- | --- |
| A1 | dsh-chapter-whale 插件本体（插件外壳、`backend/manager`、`backend/integration`） | 0.7.0 | MIT（自有源码）；整体发行 `GPL-3.0-only` | https://github.com/thus-zhou/dsh-chapter-whale | 根 `LICENSE`；`LICENSES/MIT-chapter-whale.txt`；`LICENSES/GPL-3.0.txt` |
| B1 | webnovel-writer 写作器 | 上游提交 `2dc4359e162bb2d165e6f4458dac8bab41475be9` | GPL-3.0-only | https://github.com/981029l/webnovel-writer | `backend/webnovel-writer/LICENSE`；`LICENSES/GPL-3.0.txt` |
| C1 | Our Free Model（含 OFM 本地补丁） | 2.5.5（standalone 2.5.4），修订 `25151bab43ff28bfc0eef5a3dbec4443ecc6d2f2` | MIT | https://github.com/Ebony-Vinyl/dsh-our-free-model | `backend/vendor/our-free-model-source/LICENSE`；`LICENSES/MIT-our-free-model.txt` |
| C2 | channel-pack（OFM 内嵌） | 随 C1 | MIT（Copyright (c) 2026 Jet） | 随 C1 | `backend/vendor/our-free-model-source/vendor/channel-pack/LICENSE` |
| C3 | dsh-std（OFM 内嵌） | 随 C1 | MIT（Copyright (c) 2026 DSH Standard contributors） | 随 C1 | `backend/vendor/our-free-model-source/vendor/dsh-std/LICENSE` |
| D1 | 番茄发布适配（`backend/fanqie_auto_publish`） | 无版本字段 | 未声明（待核验） | 维护者确认的来源说明，AI 辅助开发 | 目录内无 LICENSE；见 `docs/license-inventory.md` §2.4 |
| E1 | Manrope（子集，界面名 Whale Geometric） | 无版本号 | OFL-1.1 | https://github.com/google/fonts/tree/main/ofl/manrope | `assets/fonts/manrope-OFL.txt` |
| E2 | Noto Sans SC（子集，界面名 Whale Text） | 无版本号 | OFL-1.1 | https://github.com/google/fonts/tree/main/ofl/notosanssc | `assets/fonts/notosanssc-OFL.txt` |
| E3 | Noto Serif SC（子集 400 字重，界面名 Whale Editorial） | 无版本号 | OFL-1.1 | https://github.com/google/fonts/tree/main/ofl/notoserifsc | `assets/fonts/notoserifsc-OFL.txt` |

### Python 运行时

| 编号 | 组件 | 版本 | 许可证 | 来源 | 许可证文本位置 |
| --- | --- | --- | --- | --- | --- |
| F1 | CPython（embeddable amd64） | 3.13.17 | PSF-2.0 | https://www.python.org/ftp/python/3.13.17/python-3.13.17-embeddable-amd64.zip（SHA-256 见 `runtime-manifest.json`） | `runtime/python/LICENSE.txt` |
| F2–F36 | Python 依赖 35 个（见下表） | 锁定于 `requirements-runtime.lock` | MIT / BSD-3-Clause / Apache-2.0 / PSF-2.0 / MPL-2.0 / MIT-CMU 等 | PyPI | 各包 `runtime/python/Lib/site-packages/<包>-<版本>.dist-info/`（`METADATA` 许可字段 + 随包 LICENSE） |

| 包 | 版本 | 许可证 | 包 | 版本 | 许可证 |
| --- | --- | --- | --- | --- | --- |
| fastapi | 0.141.1 | MIT | uvicorn | 0.53.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT | httpx | 0.28.1 | BSD-3-Clause |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT | playwright | 1.63.0 | Apache-2.0 |
| filelock | 4.1.1 | MIT | tzdata | 2026.5 | Apache-2.0 |
| pydantic_core | 2.46.5 | MIT | greenlet | 3.5.6 | MIT AND PSF-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause | multidict | 6.9.1 | Apache-2.0 |
| pyee | 13.0.1 | MIT | yarl | 1.25.1 | Apache-2.0 |
| python-multipart | 0.0.33 | Apache-2.0 | aiofiles | 25.1.0 | Apache-2.0 |
| pillow | 13.0.0 | MIT-CMU | requests | 2.34.2 | Apache-2.0 |
| charset-normalizer | 3.5.2 | MIT | idna | 3.20 | BSD-3-Clause |
| urllib3 | 2.8.0 | MIT | aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiosignal | 1.4.0 | Apache-2.0 | annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT | attrs | 26.1.0 | MIT |
| certifi | 2026.10.23 | MPL-2.0 | click | 8.5.1 | BSD-3-Clause |
| frozenlist | 1.8.0 | Apache-2.0 | h11 | 0.16.0 | MIT |
| propcache | 0.5.4 | Apache-2.0 | starlette | 1.10.0 | BSD-3-Clause |
| anyio | 4.16.0 | MIT | typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.5 | MIT | — | — | — |

### Node 依赖

npm 不把依赖打进包内，安装时按 `package-lock.json` 解析；下表为直接依赖与全部传递依赖。

| 编号 | 包 | 版本 | 许可证 | 来源 | 许可证文本位置 |
| --- | --- | --- | --- | --- | --- |
| G1 | `@deepseek-ai/cordis` | 4.1.0 | MIT | npm | `node_modules/@deepseek-ai/cordis/LICENSE` |
| G2 | `@deepseek-ai/cosmokit` | 1.9.0 | MIT | npm | `node_modules/@deepseek-ai/cosmokit/LICENSE` |
| G3 | `@deepseek-ai/schemastery` | 3.19.0 | MIT | npm | `node_modules/@deepseek-ai/schemastery/LICENSE` |
| G4 | `@isaacs/fs-minipass` | 4.0.1 | ISC | npm | `node_modules/@isaacs/fs-minipass/LICENSE` |
| G5 | `@standard-schema/spec` | 1.1.0 | MIT | npm | `node_modules/@standard-schema/spec/LICENSE` |
| G6 | `chownr` | 3.0.0 | BlueOak-1.0.0 | npm | `node_modules/chownr/LICENSE.md` |
| G7 | `minipass` | 7.1.3 | BlueOak-1.0.0 | npm | `node_modules/minipass/LICENSE.md` |
| G8 | `minizlib` | 3.1.0 | MIT | npm | `node_modules/minizlib/LICENSE` |
| G9 | `tar`（node-tar） | 7.5.23 | BlueOak-1.0.0 | https://github.com/isaacs/node-tar | `node_modules/tar/LICENSE.md` |
| G10 | `yallist` | 5.0.0 | BlueOak-1.0.0 | npm | `node_modules/yallist/LICENSE.md` |

安装器使用 node-tar 解码 UTF-8 文件名并拒绝越界路径，见 `docs/distribution.md`。

### 浏览器与自动化运行时

| 编号 | 组件 | 版本 | 许可证 | 来源 | 许可证文本位置 |
| --- | --- | --- | --- | --- | --- |
| H1 | Playwright Chromium | chromium-1243（Chrome for Testing 153.0.8010.12） | Chromium BSD-3-Clause 及第三方许可（文本未随包，待核验） | 由 Playwright 1.63.0 安装 | `runtime/browsers/chromium-1243/chrome-win64/ABOUT`（指向 `chrome://terms`、`chrome://credits`） |
| H2 | Playwright FFmpeg | ffmpeg-1011 | LGPL-2.1（构建选项待核验） | 由 Playwright 1.63.0 安装 | `runtime/browsers/ffmpeg-1011/COPYING.LGPLv2.1` |
| H3 | Playwright WinLDD | winldd-1007 | 未随附文本（待核验） | 由 Playwright 1.63.0 安装 | `runtime/browsers/winldd-1007/` 无许可文件 |
| H4 | Playwright driver（`playwright-core` 1.63.0，内嵌 Node.js v24.21.0） | 1.63.0 / v24.21.0 | Apache-2.0；Node.js MIT（文本未随包，待核验） | https://github.com/microsoft/playwright | `runtime/python/Lib/site-packages/playwright/driver/package/{LICENSE,NOTICE,ThirdPartyNotices.txt}` |

## 修改记录（相对上游原始发行物）

- **webnovel-writer**：29 个文件与上游 `2dc4359e` 不一致，3 个新增源码文件；修改性质为本地集成、路径校验与安全加固（CORS 收紧为 `allow_origin_regex`、增加 `TrustedHostMiddleware`、`_validate_project_root()` 路径校验等）。逐文件清单见 `docs/license-decision.md` 第 7 节。上游 `LICENSE` 文件由本项目按上游 README 声明补齐。
- **Our Free Model**：4 项本地补丁（当前用户 DPAPI 凭据、原始提示词且无 LAN 中继、可选自动签到、移除内置 Gemini OAuth 默认客户端凭据），逐条登记于 `backend/vendor/ofm-source-lock.json:4-9`。
- **字体**：按界面文本与 GB2312 常用字符做子集、修改字体内部名称并转换为 WOFF2；保留各字体版权与 OFL 全文（`assets/fonts/README.md:11`）。
- **Python/Node 依赖与浏览器**：未修改，按锁定版本原样分发。

## 待核验

`backend/fanqie_auto_publish` 的权利归属、Chromium 第三方许可文本、FFmpeg 构建选项、WinLDD 与内嵌 `node.exe` 的许可文本尚未闭环，明细与建议动作见 `docs/license-inventory.md` 第 3 节。上述条目不改变本文对已核实组件的结论；在闭环前，发行说明按“已知信息 + 明确披露”表述。

权利与联系处理：如发现来源、许可或权利问题，请通过仓库 Issue 联系维护者；维护者将核实并处理。此说明不替代任何组件的许可证。

修改记录（2026-11-10）：增加自带 Windows 环境、独立用户数据目录、首装建书与登录入口、作品切换和发布账号/书名选择；托管模式不读取旧的全局模型配置。现有个人部署没有被替换。

修改记录（2026-11-16，许可证路线 A）：新增 `LICENSES/` 与 `docs/license-inventory.md`、`docs/license-decision.md`；本文按盘点补齐组件条目与版本、来源、文本位置，并在文首加入组合分发说明。未改动任何组件代码。
