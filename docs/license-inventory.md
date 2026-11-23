# 许可证与第三方组件盘点（P06 · 许可证路线 A）

- 盘点日期：2026-11-16（Asia/Shanghai）
- 盘点对象：发行包 `dsh-chapter-whale` 及其随包内容（插件源码、后端、固定运行时）
- 证据基准：仓库当前工作树字节；`runtime-manifest.json` 的 buildId `79a1db4ee1f940169ef80b58c7b3a4f6317947939caf8955575f85c70bef0e0f`（版本 0.4.2 运行时）
- 性质：技术与文本核对，不构成法律意见；结论的取舍见 `docs/license-decision.md`

## 0. 方法与证据分级

| 证据类型 | 取得方式 | 用于 |
| --- | --- | --- |
| 许可证全文 | 直接读取仓库文件、`Get-FileHash`、逐行定位 | 判定许可证族与版本，记录字节数/行号 |
| Python 包许可 | `runtime/python/Lib/site-packages/<pkg>-<ver>.dist-info/METADATA` 的 `License` / `License-Expression` 字段 | 逐包给出版本与 SPDX 标识 |
| Node 包许可 | `package-lock.json` 的 `license` 字段 + `node_modules/<pkg>/LICENSE*` 实体文件 | 直接依赖与传递依赖 |
| 上游一致性 | GitHub REST API 读取 `981029l/webnovel-writer` 提交 `2dc4359e162bb2d165e6f4458dac8bab41475be9` 的 recursive tree，对本地 987 个文件逐个计算 git blob SHA-1 并比对 | 判断“是否修改” |
| 分发形态 | 文件类型与目录结构（`.py`/`.mjs` 源码，`.pyd`/`.dll`/`.exe`/`.woff2` 二进制） | 区分源码分发与二进制分发 |

比对基线说明：本地 `backend/webnovel-writer` 共 987 个文件，上游同提交共 1055 个 blob（含 `frontend/`、`scripts/`、`task/` 等本项目未随包分发的目录）。逐文件比对结果：930 个文件与上游字节一致；29 个文件不一致；本地另有 28 个文件不在上游（其中 25 个是 `__pycache__/*.pyc` 构建残留，3 个是新增源码）；上游有 96 个文件未随包。

## 1. 汇总表

编号用于下文与 `THIRD_PARTY_NOTICES.md` 对照。“修改”一列只表示相对上游/原始发行物是否被本项目改动。

| 编号 | 组件 | 版本 | 来源 | 许可证 | 文本/证据位置 | 修改 | 形态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | dsh-chapter-whale 插件本体（`index.js`、`client.js`、`managed-runtime.mjs`、`locale/`、`backend/manager`、`backend/integration`） | 0.5.0（`package.json:3`） | https://github.com/thus-zhou/dsh-chapter-whale（`package.json:12-19`） | MIT | `LICENSE:1-21`（1082 B）；`LICENSES/MIT-chapter-whale.txt` | 自有代码 | 源码 |
| B1 | webnovel-writer 写作器（内嵌） | 上游提交 `2dc4359e162bb2d165e6f4458dac8bab41475be9`（2026-07-25，上游无版本号字段） | https://github.com/981029l/webnovel-writer | GPL-3.0-only | `backend/webnovel-writer/README.md:3`、`:508-510`；`backend/webnovel-writer/LICENSE:1-2`（35149 B / 674 行） | 是（29 个文件，见 §2.2） | 源码 |
| C1 | Our Free Model（`backend/vendor/our-free-model-source`） | 元包 2.5.5（`package.json:3`）；standalone 2.5.4（`packages/standalone/package.json:3`）；锁定修订 `25151bab43ff28bfc0eef5a3dbec4443ecc6d2f2` | https://github.com/Ebony-Vinyl/dsh-our-free-model（`backend/vendor/ofm-source-lock.json:2-3`） | MIT | `backend/vendor/our-free-model-source/LICENSE:1-3`；`package.json:66` | 是（4 项本地补丁，见 §2.3） | 源码 |
| C2 | channel-pack（OFM 内嵌） | 随 C1 锁定修订 | 随 C1 | MIT | `backend/vendor/our-free-model-source/vendor/channel-pack/LICENSE:1-3`（Copyright (c) 2026 Jet） | 随 C1 | 源码 |
| C3 | dsh-std（OFM 内嵌） | 随 C1 锁定修订 | 随 C1 | MIT | `backend/vendor/our-free-model-source/vendor/dsh-std/LICENSE:1-3`（Copyright (c) 2026 DSH Standard contributors） | 随 C1 | 源码 |
| D1 | 番茄发布适配（`backend/fanqie_auto_publish`） | 无版本字段 | 仓库内组件；`THIRD_PARTY_NOTICES.md` 记为“AI 辅助开发，依据维护者确认的来源说明” | **未声明 → 待核验** | `backend/fanqie_auto_publish/README.md` 无许可章节；目录内无 LICENSE 文件 | 自有/来源待核 | 源码 |
| E1 | Manrope（子集，`Whale Geometric`） | 无版本号；来源仓库当前版本 | https://github.com/google/fonts/tree/main/ofl/manrope（`assets/fonts/README.md:7`） | OFL-1.1 | `assets/fonts/manrope-OFL.txt:1`、`:3`、`:9` | 是（子集化、改名、转 WOFF2，`assets/fonts/README.md:11`） | 二进制（woff2） |
| E2 | Noto Sans SC（子集，`Whale Text`） | 无版本号 | https://github.com/google/fonts/tree/main/ofl/notosanssc（`assets/fonts/README.md:8`） | OFL-1.1 | `assets/fonts/notosanssc-OFL.txt:1`、`:3`、`:9` | 同上 | 二进制（woff2） |
| E3 | Noto Serif SC（子集 400 字重，`Whale Editorial`） | 无版本号 | https://github.com/google/fonts/tree/main/ofl/notoserifsc（`assets/fonts/README.md:9`） | OFL-1.1 | `assets/fonts/notoserifsc-OFL.txt:1`、`:3-4`、`:10` | 同上 | 二进制（woff2） |
| F1 | CPython（embeddable amd64） | 3.13.17 | https://www.python.org/ftp/python/3.13.17/python-3.13.17-embeddable-amd64.zip（`runtime-manifest.json:4-6`，sha256 `0ba1ee4b…`） | PSF-2.0 | `runtime/python/LICENSE.txt:63`、`:66` | 否 | 二进制 |
| F2–F36 | Python 运行时依赖 35 个 | 见 §2.6 | PyPI（`requirements-runtime.lock` 逐行 `name==version --hash`） | 见 §2.6 | 各包 `dist-info/METADATA` | 否 | 二进制 wheel + 源码 `.py` |
| G1 | `@deepseek-ai/cordis` | 4.1.0 | npm（`package-lock.json:35-40`） | MIT | `package-lock.json:40`；`node_modules/@deepseek-ai/cordis/LICENSE` | 否 | 源码 |
| G2 | `@deepseek-ai/cosmokit` | 1.9.0 | npm（`package-lock.json:61-66`） | MIT | `package-lock.json:65` | 否 | 源码 |
| G3 | `@deepseek-ai/schemastery` | 3.19.0 | npm（`package-lock.json:67-76`） | MIT | `package-lock.json:71` | 否 | 源码 |
| G4 | `@isaacs/fs-minipass` | 4.0.1 | npm（`package-lock.json:77-88`） | ISC | `package-lock.json:81` | 否 | 源码 |
| G5 | `@standard-schema/spec` | 1.1.0 | npm（`package-lock.json:89-94`） | MIT | `package-lock.json:93` | 否 | 源码 |
| G6 | `chownr` | 3.0.0 | npm（`package-lock.json:95-103`） | BlueOak-1.0.0 | `package-lock.json:99` | 否 | 源码 |
| G7 | `minipass` | 7.1.3 | npm（`package-lock.json:104-112`） | BlueOak-1.0.0 | `package-lock.json:108` | 否 | 源码 |
| G8 | `minizlib` | 3.1.0 | npm（`package-lock.json:113-124`） | MIT | `package-lock.json:117` | 否 | 源码 |
| G9 | `tar`（node-tar） | 7.5.23 | npm（`package-lock.json:125-140`） | BlueOak-1.0.0 | `package-lock.json:129`；`node_modules/tar/LICENSE.md` | 否 | 源码 |
| G10 | `yallist` | 5.0.0 | npm（`package-lock.json:141-149`） | BlueOak-1.0.0 | `package-lock.json:145` | 否 | 源码 |
| H1 | Playwright 浏览器 Chromium | chromium-1243（Chrome for Testing 153.0.8010.12） | 由 Playwright 1.63.0 驱动下载（`scripts/build-runtime.py:93-97`） | Chromium BSD-3-Clause + 第三方（文本未随包）→ **待核验** | `runtime/browsers/chromium-1243/chrome-win64/ABOUT:1-6`、`153.0.8010.12.manifest:4-6` | 否 | 二进制 |
| H2 | Playwright FFmpeg | ffmpeg-1011（`ffmpeg-win64.exe`，3,490,816 B） | 同上 | LGPL-2.1（构建选项待核验） | `runtime/browsers/ffmpeg-1011/COPYING.LGPLv2.1` | 否 | 二进制 |
| H3 | Playwright WinLDD 辅助程序 | winldd-1007（`PrintDeps.exe`，258,560 B） | 同上 | **未随附许可文本 → 待核验** | `runtime/browsers/winldd-1007/` 仅可执行文件与两个零字节标记 | 否 | 二进制 |
| H4 | Playwright driver（`playwright-core` + 内嵌 `node.exe`） | 1.63.0 / Node.js v24.21.0 | https://github.com/microsoft/playwright | Apache-2.0（driver）；Node.js MIT（node.exe 许可文本未随包）→ **node.exe 待核验** | `runtime/python/Lib/site-packages/playwright/driver/package/package.json`（`"license": "Apache-2.0"`）；`driver/package/LICENSE`、`NOTICE`、`ThirdPartyNotices.txt` | 否 | 二进制 |

## 2. 分组明细

### 2.1 自身代码（A1）

| 事实 | 证据 |
| --- | --- |
| 插件包名 `dsh-chapter-whale`，版本 `0.5.0` | `package.json:2-3` |
| `package.json` 当前许可字段为 `SEE LICENSE IN THIRD_PARTY_NOTICES.md` | `package.json:7`；`package-lock.json:10` |
| 根许可为 MIT，版权行 `Copyright (c) 2026 novel-helper contributors` | `LICENSE:1`、`LICENSE:3`，全文 21 行 1082 B |
| 仓库地址与主页 | `package.json:12-19` |
| `files` 白名单当前不含 `LICENSES/` | `package.json:44-63`（逐项见该区间，无 `LICENSES/`） |

结论：A1 为 MIT 自有代码。它同时通过 `sys.path` 导入 GPLv3 的写作器模块（见 §2.2），因此**发行包整体**不能只按 MIT 描述；这一点在 `docs/license-decision.md` 第 3、4 节处理。

### 2.2 内嵌写作器（B1）

许可证判定链：

| 证据 | 内容 | 含义 |
| --- | --- | --- |
| `backend/webnovel-writer/README.md:3` | `[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)` | 声明 GPL v3 |
| `backend/webnovel-writer/README.md:508-510` | `## License` / `GPL v3 - 详见 [LICENSE](LICENSE)` | 声明 GPL v3，无 “or later” |
| `backend/webnovel-writer/LICENSE:1-2` | `GNU GENERAL PUBLIC LICENSE` / `Version 3, 29 June 2007` | 全文为 GPLv3 标准文本 |
| `backend/webnovel-writer/LICENSE:621` | `END OF TERMS AND CONDITIONS` | 全文完整，未截断 |
| `backend/webnovel-writer/LICENSE:572-574`、`:640` | “or any later version” 仅出现在 GPL 正文第 14 条与 “How to Apply” 示例声明中 | 属于许可证模板文字，**不是**上游对版本选择的声明 |
| GitHub API `repos/981029l/webnovel-writer` | `license` 字段为空；默认分支 `master`；HEAD `2dc4359e162bb2d165e6f4458dac8bab41475be9`（2026-07-25） | 上游仓库 HEAD 未附 LICENSE 文件 |

判定：上游只声明“GPL v3”，没有 “or later”，也没有逐文件许可头 → 按 **GPL-3.0-only** 处理（SPDX 表达 `GPL-3.0-only`）。本地 `backend/webnovel-writer/LICENSE` 是 GPLv3 标准全文（git blob SHA-1 `f288702d2fa16d3cdf0035b15a9fcbc552cd88e7`，与 FSF 发布文本一致），由本项目补齐——上游该提交并不包含 LICENSE 文件。

修改情况（与上游 `2dc4359e` 逐 blob 比对）：

| 类别 | 数量 | 明细 |
| --- | --- | --- |
| 与上游字节一致 | 930 | — |
| 与上游不一致 | 29 | 均在 `backend/webnovel-writer/` 下：`backend/{dependencies,main,utils}.py`、`backend/routers/{ai,chapters,characters,entities,fanqie,outlines,projects,rag}.py`、`backend/services/{ai_service,fanqie_publisher,genre_catalog,genre_writer_agent,project_prompt_store,projects_manager,skill_executor}.py`、`.claude/scripts/{archive_manager,backup_manager,extract_chapter_context,security_utils,update_state}.py`、`.claude/scripts/data_modules/{api_client,config,index_manager,migrate_state_to_sqlite,rag_adapter,state_manager}.py` |
| 本地新增（源码） | 3 | `backend/webnovel-writer/backend/services/creative_brief.py`、`backend/webnovel-writer/backend/services/reset_derived_data.py`、`backend/webnovel-writer/backend/services/usage_meter.py` |
| 本地新增（许可/构建残留） | 26 | `backend/webnovel-writer/LICENSE`（GPLv3 全文）与 25 个 `__pycache__/*.pyc` |

修改性质（抽样证据）：`backend/webnovel-writer/backend/dependencies.py:8` 定义 `_validate_project_root()`（在 `:56`、`:63` 调用），拒绝盘符根、用户目录、系统目录与过浅路径；`backend/webnovel-writer/backend/main.py:29` 将 CORS 从 `allow_origins=["*"]` 收紧为 `allow_origin_regex`，`:34` 加入 `TrustedHostMiddleware`；其余文件为同类的本地集成与安全加固改动。发行包生成时 `__pycache__`/`.pyc` 会被 `scripts/build-runtime.py:56-57` 过滤，不随包。

### 2.3 vendor（C1–C3）

| 事实 | 证据 |
| --- | --- |
| 来源仓库与锁定修订 | `backend/vendor/ofm-source-lock.json:2`、`:3` |
| 本地补丁 4 项：当前用户 DPAPI 凭据、原始提示词且无 LAN 中继、可选自动签到、移除内置 Gemini OAuth 默认客户端凭据 | `backend/vendor/ofm-source-lock.json:4-9` |
| 顶层许可 MIT，版权 `Copyright (c) 2026 Ebony-Vinyl` | `backend/vendor/our-free-model-source/LICENSE:1-3`；`package.json:66` |
| 版本：元包 2.5.5 / standalone 2.5.4 | `backend/vendor/our-free-model-source/package.json:3`；`packages/standalone/package.json:3` |
| 内嵌 channel-pack：MIT，`Copyright (c) 2026 Jet` | `backend/vendor/our-free-model-source/vendor/channel-pack/LICENSE:1-3` |
| 内嵌 dsh-std：MIT，`Copyright (c) 2026 DSH Standard contributors` | `backend/vendor/our-free-model-source/vendor/dsh-std/LICENSE:1-3` |
| 文件级完整性清单（92 个文件 sha256） | `backend/vendor/ofm-source-lock.json` 的 `files` 字段 |

### 2.4 发布适配（D1）

| 事实 | 证据 |
| --- | --- |
| 目录内无 `LICENSE`/`COPYING`/`NOTICE` | `backend/fanqie_auto_publish/` 文件清单（`login.py`、`publication_safety.py`、`publish.py`、`README.md`、`requirements.txt`） |
| README 无许可章节，仅有“作品版权”与打赏文案 | `backend/fanqie_auto_publish/README.md:17`、`:124` |
| 现有对外说明把它记为“AI 辅助开发，依据维护者确认的来源说明” | `THIRD_PARTY_NOTICES.md:23` |
| 依赖仅 `playwright`、`pillow` | `backend/fanqie_auto_publish/requirements.txt:1-2` |

结论：许可与权利归属未在仓库内声明 → 列入待核验。发行包仍随附其源码，未删除任何声明。

### 2.5 字体（E1–E3）

| 字体 | CSS 名 | 文件 | OFL 文本 | 关键行 |
| --- | --- | --- | --- | --- |
| Manrope | Whale Geometric | `assets/fonts/manrope.woff2`（33,816 B） | `assets/fonts/manrope-OFL.txt`（4,387 B） | `:1` 版权行、`:3` OFL 1.1 声明、`:9` 许可全文标题 |
| Noto Sans SC | Whale Text | `assets/fonts/notosanssc.woff2`（1,958,332 B） | `assets/fonts/notosanssc-OFL.txt`（4,388 B） | `:1` 版权行（Adobe，保留字体名 Source）、`:3`、`:9` |
| Noto Serif SC | Whale Editorial | `assets/fonts/notoserifsc.woff2`（1,362,860 B） | `assets/fonts/notoserifsc-OFL.txt`（4,350 B） | `:1` 版权行、`:3-4`、`:10` |

修改说明：`assets/fonts/README.md:11` 记录“按界面文本与 GB2312 常用字符做子集、修改字体内部名称并转成 WOFF2；宋体固定 400 字重”。OFL-1.1 允许修改与再分发，要求保留版权与许可文本、且修改版不得使用原保留字体名——改名（Whale *）与保留 `*-OFL.txt` 已满足这两点。

### 2.6 Python 运行时依赖（F1–F36）

解释器：CPython 3.13.17 embeddable（`runtime-manifest.json:3-6`），许可 PSF-2.0（`runtime/python/LICENSE.txt:63`）。下表版本与 `requirements-runtime.lock` 逐行对应（行号即该文件行号），许可取自随包 `dist-info/METADATA`。

| 包 | 版本 | 许可证 | 证据（lock 行；METADATA 行） |
| --- | --- | --- | --- |
| fastapi | 0.141.1 | MIT | `requirements-runtime.lock:1`；`runtime/python/Lib/site-packages/fastapi-0.141.1.dist-info/METADATA:6` |
| uvicorn | 0.53.0 | BSD-3-Clause | `requirements-runtime.lock:2`；`.../uvicorn-0.53.0.dist-info/METADATA:11` |
| pydantic | 2.13.5 | MIT | `requirements-runtime.lock:3`；`.../pydantic-2.13.5.dist-info/METADATA:11` |
| httpx | 0.28.1 | BSD-3-Clause | `requirements-runtime.lock:4`；`.../httpx-0.28.1.dist-info/METADATA:10` |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT | `requirements-runtime.lock:5`；`.../aiohttp-3.14.3.dist-info/METADATA:6` |
| playwright | 1.63.0 | Apache-2.0 | `requirements-runtime.lock:6`；`.../playwright-1.63.0.dist-info/METADATA:6` |
| filelock | 4.1.1 | MIT | `requirements-runtime.lock:7`；`.../filelock-4.1.1.dist-info/METADATA:10` |
| tzdata | 2026.5 | Apache-2.0 | `requirements-runtime.lock:8`；`.../tzdata-2026.5.dist-info/METADATA:8` |
| pydantic_core | 2.46.5 | MIT | `requirements-runtime.lock:9`；`.../pydantic_core-2.46.5.dist-info/METADATA:30` |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | `requirements-runtime.lock:10`；`.../greenlet-3.5.6.dist-info/METADATA:7` |
| httpcore | 1.0.9 | BSD-3-Clause | `requirements-runtime.lock:11`；`.../httpcore-1.0.9.dist-info/METADATA:9` |
| multidict | 6.9.1 | Apache-2.0 | `requirements-runtime.lock:12`；`.../multidict-6.9.1.dist-info/METADATA:8` |
| pyee | 13.0.1 | MIT | `requirements-runtime.lock:13`；`.../pyee-13.0.1.dist-info/METADATA:6` |
| yarl | 1.25.1 | Apache-2.0 | `requirements-runtime.lock:14`；`.../yarl-1.25.1.dist-info/METADATA:10` |
| python-multipart | 0.0.33 | Apache-2.0 | `requirements-runtime.lock:15`；`.../python_multipart-0.0.33.dist-info/METADATA:11` |
| aiofiles | 25.1.0 | Apache-2.0 | `requirements-runtime.lock:16`；`.../aiofiles-25.1.0.dist-info/METADATA:9` |
| pillow | 13.0.0 | MIT-CMU | `requirements-runtime.lock:17`；`.../pillow-13.0.0.dist-info/METADATA:6` |
| requests | 2.34.2 | Apache-2.0 | `requirements-runtime.lock:18`；`.../requests-2.34.2.dist-info/METADATA:7` |
| charset-normalizer | 3.5.2 | MIT | `requirements-runtime.lock:19`；`.../charset_normalizer-3.5.2.dist-info/METADATA:7` |
| idna | 3.20 | BSD-3-Clause | `requirements-runtime.lock:20`；`.../idna-3.20.dist-info/METADATA:8` |
| urllib3 | 2.8.0 | MIT | `requirements-runtime.lock:21`；`.../urllib3-2.8.0.dist-info/METADATA:12` |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | `requirements-runtime.lock:22`；`.../aiohappyeyeballs-2.7.1.dist-info/METADATA:5` |
| aiosignal | 1.4.0 | Apache-2.0 | `requirements-runtime.lock:23`；`.../aiosignal-1.4.0.dist-info/METADATA:8` |
| annotated-doc | 0.0.5 | MIT | `requirements-runtime.lock:24`；`.../annotated_doc-0.0.5.dist-info/METADATA:6` |
| annotated-types | 0.8.0 | MIT | `requirements-runtime.lock:25`；`.../annotated_types-0.8.0.dist-info/METADATA:9` |
| attrs | 26.1.0 | MIT | `requirements-runtime.lock:26`；`.../attrs-26.1.0.dist-info/METADATA:11` |
| certifi | 2026.10.23 | MPL-2.0 | `requirements-runtime.lock:27`；`.../certifi-2026.10.23.dist-info/METADATA:8` |
| click | 8.5.1 | BSD-3-Clause | `requirements-runtime.lock:28`；`.../click-8.5.1.dist-info/METADATA:8` |
| frozenlist | 1.8.0 | Apache-2.0 | `requirements-runtime.lock:29`；`.../frozenlist-1.8.0.dist-info/METADATA:8` |
| h11 | 0.16.0 | MIT | `requirements-runtime.lock:30`；`.../h11-0.16.0.dist-info/METADATA:8` |
| propcache | 0.5.4 | Apache-2.0 | `requirements-runtime.lock:31`；`.../propcache-0.5.4.dist-info/METADATA:10` |
| starlette | 1.10.0 | BSD-3-Clause | `requirements-runtime.lock:32`；`.../starlette-1.10.0.dist-info/METADATA:12` |
| anyio | 4.16.0 | MIT | `requirements-runtime.lock:33`；`.../anyio-4.16.0.dist-info/METADATA:6` |
| typing_extensions | 4.16.0 | PSF-2.0 | `requirements-runtime.lock:34`；`.../typing_extensions-4.16.0.dist-info/METADATA:9` |
| typing-inspection | 0.4.5 | MIT | `requirements-runtime.lock:35`；`.../typing_inspection-0.4.5.dist-info/METADATA:10` |

说明：`certifi` 为 MPL-2.0（文件级弱 copyleft，未修改即按原样分发，合规）；`aiohttp`、`greenlet` 为双许可/组合标识，按各自声明处理。35 个包全部能从随包 `dist-info` 直接判定，**无“待核验”**。

### 2.7 Node 依赖（G1–G10）

`package.json` 直接依赖 2 个运行时包（`@deepseek-ai/schemastery`、`tar`）+ 1 个开发依赖（`@deepseek-ai/cordis`），其余 7 个为传递依赖；`react` 是可选 peer，不随包。版本与许可以 `package-lock.json` 为准，实体许可见 `node_modules/<pkg>/LICENSE*`。

| 包 | 版本 | 许可证 | lock 行 | 关系 |
| --- | --- | --- | --- | --- |
| `@deepseek-ai/cordis` | 4.1.0 | MIT | `package-lock.json:35-40`（许可在 `:40`） | dev + 可选 peer |
| `@deepseek-ai/cosmokit` | 1.9.0 | MIT | `:61-66`（`:65`） | 传递 |
| `@deepseek-ai/schemastery` | 3.19.0 | MIT | `:67-76`（`:71`） | 直接 |
| `@isaacs/fs-minipass` | 4.0.1 | ISC | `:77-88`（`:81`） | 传递 |
| `@standard-schema/spec` | 1.1.0 | MIT | `:89-94`（`:93`） | 传递 |
| `chownr` | 3.0.0 | BlueOak-1.0.0 | `:95-103`（`:99`） | 传递 |
| `minipass` | 7.1.3 | BlueOak-1.0.0 | `:104-112`（`:108`） | 传递 |
| `minizlib` | 3.1.0 | MIT | `:113-124`（`:117`） | 传递 |
| `tar` | 7.5.23 | BlueOak-1.0.0 | `:125-140`（`:129`） | 直接（安装器解包） |
| `yallist` | 5.0.0 | BlueOak-1.0.0 | `:141-149`（`:145`） | 传递 |

说明：npm 包不把这些依赖打进 tarball，由安装方按 lock 解析；`files` 白名单与 `node_modules` 无关（`package.json:44-63`）。

### 2.8 Playwright 浏览器与驱动（H1–H4）

| 事实 | 证据 |
| --- | --- |
| 浏览器由锁定 Playwright 安装，路径固定在 `runtime/browsers` | `scripts/build-runtime.py:93-97`（`PLAYWRIGHT_BROWSERS_PATH` + `playwright install chromium --no-shell`） |
| Chromium 版本 153.0.8010.12，版权行 Google LLC 2026 | `runtime/browsers/chromium-1243/chrome-win64/ABOUT:1-6`；`153.0.8010.12.manifest:4-6` |
| Chromium 目录内没有 LICENSE/COPYING/credits 文件 | 目录递归检索无命中（`chrome-win64/` 仅 `ABOUT` 与 `chrome://credits` 入口） |
| FFmpeg 随附 LGPL-2.1 全文 | `runtime/browsers/ffmpeg-1011/COPYING.LGPLv2.1`（26,526 B） |
| WinLDD 仅 `PrintDeps.exe` 与两个零字节标记文件 | `runtime/browsers/winldd-1007/` |
| Playwright driver 1.63.0 Apache-2.0，附 LICENSE/NOTICE/ThirdPartyNotices | `runtime/python/Lib/site-packages/playwright/driver/package/package.json`（`"license": "Apache-2.0"`）、同目录 `LICENSE`、`NOTICE`、`ThirdPartyNotices.txt` |
| driver 内嵌 `node.exe` v24.21.0，无独立 Node.js 许可文本 | 运行 `driver/node.exe -v` 得 `v24.21.0`；目录内无 Node 许可文件 |

## 3. 待核验清单（5 条）

| 编号 | 条目 | 待核验内容 | 当前依据 | 建议动作 |
| --- | --- | --- | --- | --- |
| D1 | `backend/fanqie_auto_publish` | 权利归属与许可（是否允许再分发） | `backend/fanqie_auto_publish/README.md` 无许可章节；`THIRD_PARTY_NOTICES.md:23` 仅记“AI 辅助开发” | 由维护者书面确认来源与授权，再补 `LICENSES/` 文本或版权行 |
| H1 | Chromium 153.0.8010.12 | 分发条款与第三方许可文本 | `ABOUT:1-6` 指向 `chrome://terms`/`chrome://credits`，随包无文本 | 在发行说明附 Chromium 的 BSD-3-Clause 声明与 credits 获取方式，或随包附 `LICENSES/Chromium-credits.html` |
| H2 | FFmpeg（ffmpeg-1011） | 构建是否含 GPL 组件（决定 LGPL-2.1 还是 GPL） | 仅随附 `COPYING.LGPLv2.1`，无构建配置 | 记录 Playwright 官方构建说明；如需绝对确定，向 Playwright 发行说明核对 |
| H3 | WinLDD `PrintDeps.exe` | 许可文本 | 目录内无任何许可文件 | 归入 Playwright 的 Apache-2.0 分发说明，并在 notices 注明 |
| H4 | Playwright driver 内嵌 `node.exe` v24.21.0 | Node.js 许可文本未随包 | 仅有 Playwright 的 LICENSE/NOTICE | 在 notices 注明 Node.js 版本与 MIT 许可，并附文本链接 |

## 4. 统计

- 条目总数：**59**（A1 1 + B1 1 + C 3 + D 1 + E 3 + F 36 + G 10 + H 4）
- 已从随包文本或元数据直接判定：**54**
- 待核验：**5**（D1、H1、H2、H3、H4）
- 修改过的分发物：B1（29 个文件 + 3 个新增源码 + LICENSE 补齐）、C1–C3（4 项本地补丁）、E1–E3（子集/改名/WOFF2）
- 未修改：A1 自有代码（相对自身基线）、F1–F36、G1–G10、H1–H4

> 本盘点只陈述文件与元数据里能读到的事实；许可证的解释与发行取舍见 `docs/license-decision.md`。
