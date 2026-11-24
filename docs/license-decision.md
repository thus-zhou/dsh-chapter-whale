# 许可证路线 A 决策（组合分发 · GPLv3 对齐）

- 决策日期：2026-11-16
- 适用范围：`dsh-chapter-whale` 0.6.0 及后续发行（npm 插件包 + GitHub Release 完整运行包 + 插件市场条目）
- 事实依据：`docs/license-inventory.md`（59 条盘点，含逐条证据路径与行号）

## 1. 结论摘要

| 问题 | 结论 |
| --- | --- |
| 内嵌写作器的实际许可 | **GPL-3.0-only**（上游只声明 “GPL v3”，无 “or later”），见 §3 |
| 本项目自有代码 | MIT（`LICENSE:1-21`），在组合发行中同时对接收者按 GPLv3 提供 |
| 发行包整体 | 按 **GPL-3.0-only** 组合分发；MIT 与各第三方许可继续对各自部分有效 |
| 组合还是聚合 | 后端进程内 `import` 写作器模块 → **组合作品**；JS 插件 ↔ 后端 HTTP/子进程、字体、Python/Chromium → **聚合**，见 §4 |
| 源码提供 | 公开仓库 + 发行 tag + 两个构建脚本 + 三份锁定文件，见 §6 |
| 当前放行状态 | 本地修复与候选验证放行；公开完整包与市场分发**未放行**，见 §9 |

## 2. 为什么选路线 A

三条候选路线：

| 路线 | 做法 | 代价 |
| --- | --- | --- |
| **A（选定）** | 保留内嵌写作架构，发行声明整体按 GPLv3 组合分发，随包提供完整对应源码 | 发行包整体成为 GPLv3 作品；市场条款需允许 GPLv3 |
| B | 把 `backend/webnovel-writer/` 拆成用户自装的独立可选组件，主包只留 MIT | 拆掉 `backend/integration/writer_runner.py:27-29` 的同进程导入路径，重做技能执行、项目存储与提示词链路；首次安装多一步；功能回退风险高 |
| C | 换用 MIT 写作器重写 | 推翻已验收的写作/审查/状态机能力，工期不可控 |

选 A 的具体理由：

1. **架构事实不可逆。** `backend/integration/writer_runner.py:27-29` 把 `webnovel-writer/backend` 插入 `sys.path`，`:41-42` 直接 `from services import ai_service` / `from services.skill_executor import SkillExecutor`；管理端服务进程 `backend/manager/app.py:32` 把仓库根加入 `sys.path` 并由 `:1326-1336` 启动，写作调用经 `writer_runner` 在**同一进程**内完成。要拆成“独立程序”必须重写调用边界，而不是改个声明。
2. **GPLv3 允许商业与闭源周边共存，只约束组合作品本身。** 我们的 JS 插件层、字体、运行时依赖各自独立，仍按原许可分发（§4 的聚合部分），不需要放弃 MIT。
3. **MIT 与 GPLv3 兼容。** 自有 MIT 代码可以原样进入 GPLv3 组合发行，无需改变仓库里 MIT 的授权（FSF 的兼容性结论见 https://www.gnu.org/licenses/license-compatibility.en.html ：MIT 是 GPL 兼容许可，可与其他 GPL 代码组合）。
4. **合规成本最低且可验证。** 只需要三件事：完整许可证文本、完整对应源码、修改说明；三者都能用现有脚本与清单哈希证明，不需要新构建管线。

结论：路线 A 是唯一不牺牲已验收功能、又能用可核查证据满足 GPLv3 的方案。

## 3. 实际 GPL 版本标识

| 证据 | 内容 |
| --- | --- |
| `backend/webnovel-writer/README.md:3` | `[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)` |
| `backend/webnovel-writer/README.md:508-510` | `## License` → `GPL v3 - 详见 [LICENSE](LICENSE)` |
| `backend/webnovel-writer/LICENSE:1-2` | `GNU GENERAL PUBLIC LICENSE` / `Version 3, 29 June 2007` |
| `backend/webnovel-writer/LICENSE:621` | `END OF TERMS AND CONDITIONS`（全文完整，未截断） |

**判定：`GPL-3.0-only`。**

- 上游 README 两处都只说 “GPL v3”，没有 “or (at your option) any later version”，也没有 “GPL-3.0-or-later” 之类表述。
- `backend/webnovel-writer/LICENSE` 里出现的 “or any later version” 共三处：`:572-574`（正文第 14 条 Revised Versions 的模板文字）、`:587`（第 14 条对“如何应用”的说明）、`:640`（How to Apply 的示例声明 `Copyright (C) <year> <name> ... either version 3 of the License, or (at your option) any later version`）。这三处属于 GPL 标准文本的固定措辞，不是上游对自身版本的额外授权。
- 上游仓库 `981029l/webnovel-writer` 的 GitHub API `license` 字段为空，HEAD 提交 `2dc4359e162bb2d165e6f4458dac8bab41475be9` 甚至不含 `LICENSE` 文件——现在的 `backend/webnovel-writer/LICENSE` 是本项目按 README 声明补齐的 GPLv3 标准全文（git blob `f288702d2fa16d3cdf0035b15a9fcbc552cd88e7`）。

因此：**没有 “or later” 授权，本项目不主张、也不声明可以按 GPLv4 或任何后续版本使用该组件。** 若上游未来改成 “or later”，做法是：从 https://www.gnu.org/licenses/ 取得新版全文，保存为 `LICENSES/GPL-4.0.txt`（或对应版本名），同步更新本文件 §3、`THIRD_PARTY_NOTICES.md` 与 `README.md` 的版本标注；届时可把发行声明改为 `GPL-3.0-or-later`。

## 4. 组合作品与聚合的边界

GNU 的判定标准（引文来自 https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation ）：

> “Mere aggregation of two programs means putting them side by side on the same CD-ROM or hard disk… separate programs, not parts of a single program.”
> “Combining two modules means connecting them together so that they form a single larger program. If either part is covered by the GPL, the whole combination must also be released under the GPL.”

同一 FAQ 也指出：通过管道、socket、命令行参数通信的，通常属于两个独立程序。据此，本项目划两条线：

### 4.1 组合（GPLv3 覆盖整块）

| 事实 | 证据 |
| --- | --- |
| 后端把写作器 `backend/` 目录插入 `sys.path` | `backend/integration/writer_runner.py:27-29` |
| 后端在同一进程内直接 import 写作器服务类/模块（`services.ai_service`、`services.skill_executor.SkillExecutor`），并复用其全局 AI 配置对象 | `backend/integration/writer_runner.py:38-61`（`:41-42` 导入，`:44-59` 读写 `ai_service` 配置） |
| 管理端服务进程由 `backend/manager/app.py:32` 组装、`:1326-1336` 启动；写作器自带的 FastAPI 应用（`backend/webnovel-writer/backend/main.py:29`、`:34`、`:55-57`）与其路由保持可独立运行 | 同上；`backend/manager/app.py` |
| 数据面共享同一个工作区/项目目录、提示词存储与状态文件 | `backend/webnovel-writer/backend/services/project_prompt_store.py`、`backend/webnovel-writer/backend/services/projects_manager.py`；`backend/manager/app.py:577-594`（`.webnovel/state.json`） |

这些模块之间是函数调用与共享内存对象，不是进程间通信——按 FAQ 的定义构成 **single larger program**。结论：**后端 Python 部分（`backend/` 全目录，含本项目自有的 `manager/`、`integration/`）作为整体按 GPLv3 分发**；其中自有文件同时对接收者保留 MIT 授权（MIT 兼容 GPLv3，不产生冲突）。

### 4.2 聚合（各自许可独立）

| 部分 | 与后端的关系 | 许可 |
| --- | --- | --- |
| JS 插件（`index.js`、`client.js`、`managed-runtime.mjs`、`locale/`） | 通过 HTTP 与子进程启动/管理后端，不 import Python 代码 | MIT（A1） |
| 字体（`assets/fonts/*.woff2`） | 静态资源，由浏览器加载 | OFL-1.1（E1–E3） |
| CPython 与 35 个 Python 依赖 | 解释器与库，独立程序/库 | PSF-2.0、MIT/BSD/Apache-2.0/MPL-2.0 等（F1–F36） |
| Node 依赖（10 个） | 安装器解包用，独立库 | MIT/ISC/BlueOak-1.0.0（G1–G10） |
| Chromium / FFmpeg / WinLDD / Playwright driver | 独立可执行程序，由后端以子进程或 CDP 驱动 | 见 H1–H4（部分待核验） |

一句话表述（可直接用于发行说明）：

> 本发行版把 GPLv3 的写作器与后端集成在同一进程内，因此**后端与写作器组成的整体按 GPLv3 分发**，完整源码与构建脚本见仓库对应 tag；插件外壳、字体、Python/Node 运行时与浏览器属于独立程序或独立资源，仍按各自许可证分发（MIT、OFL-1.1、PSF-2.0、Apache-2.0 等），互不影响。

## 5. GPLv3 义务与本项目的对应动作

| GPLv3 条款 | 要求 | 本项目落点 |
| --- | --- | --- |
| §4 | 修改版必须显著标注修改及日期 | 本文件 §7 列出 29 个修改文件与 3 个新增文件的路径与性质；`THIRD_PARTY_NOTICES.md` 文首组合分发说明指向本节 |
| §5(a) | 随作品附带许可证副本 | `LICENSES/GPL-3.0.txt`（35,149 B / 674 行，含 `TERMS AND CONDITIONS` 与 `END OF TERMS AND CONDITIONS`） |
| §5(b) | 保留所有版权与无担保声明 | 未删除上游任何文件头或声明；上游 README 原样随包（`backend/webnovel-writer/README.md`） |
| §5(c) | 提供对应源码（网络服务器亦可视作提供） | 公开仓库 + 发行 tag + 构建脚本，见 §6 |
| §6 | 以目标代码形式分发时须提供对应源码 | 本项目 GPL 部分**以 `.py` 源码随包分发**（`.pyc` 被 `scripts/build-runtime.py:56-57` 过滤），因此主要适用 §5；`runtime-manifest.json` 逐文件 sha256 可证明随包字节与源码一致 |
| §6 Installation Information | 仅对 User Product 要求 | 本产品是通用 Windows 桌面软件，不是消费者设备固件，不适用；且以源码分发，无需安装信息 |
| §7 | 不得附加额外限制 | 发行条款、市场条目与 EULA 不得对 GPL 部分加限制（市场条款审查见 §9） |
| §8–§9 | 终止与接受 | 违规即终止；安装/使用即接受，`THIRD_PARTY_NOTICES.md` 明示 |
| §10 | 下游自动获得授权 | 下游从本项目再分发时自动获得上游 GPLv3 授权，无需另行联系上游 |
| §11 | 专利授权 | 本项目对自有贡献随 GPLv3 一并给出专利许可；上游贡献由上游给出 |

补充：`backend/webnovel-writer/` 的 29 个修改文件与 3 个新增文件均已随包提供源码，接收者可完整重建；未使用任何 “GPL 例外” 或附加条款。

## 6. 二进制分发的对应源码

完整运行包（`dsh-chapter-whale-runtime-win32-x64-<version>.tgz`）由 `scripts/pack-bundle.py` 按 `runtime-manifest.json` 逐文件复制生成，`buildId` 为全部清单文件路径与 sha256 的摘要（`scripts/build-runtime.py:63-65`）。对应源码由以下部分构成，全部公开可取：

| 对应源码组成 | 位置 | 作用 |
| --- | --- | --- |
| 插件与后端源码（含 GPL 写作器全量源码） | 仓库 `https://github.com/thus-zhou/dsh-chapter-whale`，tag `v0.6.0` | 运行时包内 `backend/` 的全部字节来源 |
| 运行时组装脚本 | `scripts/build-runtime.py`（`:69-102` 主流程；`:107-109` `--manifest-only`） | 下载并校验 CPython、按锁装依赖、装 Chromium、生成清单 |
| 发行包组装脚本 | `scripts/pack-bundle.py` | 按清单复制 + `npm pack`，产物即完整包 |
| Python 依赖锁定 | `requirements-runtime.lock`（35 行 `name==version --hash=sha256:…`） | `build-runtime.py:85-88` 以 `--require-hashes` 安装，保证与发行包一致 |
| Node 依赖锁定 | `package-lock.json` | `npm ci` 复现安装器依赖 |
| 运行时清单 | `runtime-manifest.json`（`buildId`、逐文件 sha256、`pythonSha256`） | 校验重建结果与发行包逐字节一致 |
| 上游来源锁定 | 写作器提交 `2dc4359e162bb2d165e6f4458dac8bab41475be9`；vendor 修订 `25151bab43ff28bfc0eef5a3dbec4443ecc6d2f2`（`backend/vendor/ofm-source-lock.json:2-3`） | 证明内嵌来源与修改基线 |

恢复构建命令（Windows / PowerShell 7，可直接复制）：

```powershell
# 1. 取对应源码（与发行包同 tag）
git clone https://github.com/thus-zhou/dsh-chapter-whale.git
Set-Location dsh-chapter-whale
git checkout v0.6.0

# 2. 复现 Node 侧（安装器依赖，与 package-lock.json 一致）
npm ci

# 3. 复现运行时（Python 3.13.x 解释器仅用于执行构建脚本，脚本本身只用标准库）
python scripts/build-runtime.py           # 下载 CPython 3.13.17 + 按 requirements-runtime.lock 装 35 个依赖 + 安装 chromium-1243
# 仅需重建清单时： python scripts/build-runtime.py --manifest-only

# 4. 组装完整运行包
python scripts/pack-bundle.py             # 产物：.tmp/bundle/dsh-chapter-whale-runtime-win32-x64-<version>.tgz
```

校验：重建后 `runtime-manifest.json` 的 `buildId` 应与发行包一致（当前 0.4.2 运行时为 `79a1db4ee1f940169ef80b58c7b3a4f6317947939caf8955575f85c70bef0e0f`）；不一致说明依赖或浏览器版本漂移，不得对外发布。

## 7. 修改说明（GPLv3 §4/§5）

基线：上游提交 `2dc4359e162bb2d165e6f4458dac8bab41475be9`（2026-07-25，`master`）。逐 git blob 比对：987 个本地文件里 930 个与上游字节一致，29 个不一致，另有 28 个本地新增（25 个 `__pycache__/*.pyc` + 3 个源码 + `LICENSE`）。

**修改文件（29 个）**

| 目录（均在 `backend/webnovel-writer/` 下） | 文件 |
| --- | --- |
| `backend/webnovel-writer/backend/` | `dependencies.py`、`main.py`、`utils.py` |
| `backend/webnovel-writer/backend/routers/` | `ai.py`、`chapters.py`、`characters.py`、`entities.py`、`fanqie.py`、`outlines.py`、`projects.py`、`rag.py` |
| `backend/webnovel-writer/backend/services/` | `ai_service.py`、`fanqie_publisher.py`、`genre_catalog.py`、`genre_writer_agent.py`、`project_prompt_store.py`、`projects_manager.py`、`skill_executor.py` |
| `backend/webnovel-writer/.claude/scripts/` | `archive_manager.py`、`backup_manager.py`、`extract_chapter_context.py`、`security_utils.py`、`update_state.py` |
| `backend/webnovel-writer/.claude/scripts/data_modules/` | `api_client.py`、`config.py`、`index_manager.py`、`migrate_state_to_sqlite.py`、`rag_adapter.py`、`state_manager.py` |

**新增文件（3 个）**：`backend/webnovel-writer/backend/services/creative_brief.py`、`backend/webnovel-writer/backend/services/reset_derived_data.py`、`backend/webnovel-writer/backend/services/usage_meter.py`。

**修改性质**（抽样）：`backend/webnovel-writer/backend/dependencies.py:8` 定义 `_validate_project_root()`（`backend/webnovel-writer/backend/dependencies.py:56`、`:63` 调用），拒绝盘符根、用户目录、系统目录与过浅路径；`backend/webnovel-writer/backend/main.py:29` 把 CORS 从 `allow_origins=["*"]` 收紧为 `allow_origin_regex`，`:34` 加入 `TrustedHostMiddleware`；其余为本地集成、路径解析与安全加固。修改日期统记为 2026-11（v0.5.0–v0.6.0 开发期）。

**未修改部分**：`backend/webnovel-writer/` 下其余 930 个文件按原样内嵌分发；上游 `LICENSE` 文件由本项目补齐（同上）。`backend/vendor/` 相对锁定修订有 4 项本地补丁，已在 `backend/vendor/ofm-source-lock.json:4-9` 逐条登记（DPAPI 凭据、原始提示词且无 LAN 中继、可选自动签到、移除内置 Gemini OAuth 默认客户端凭据），并保留 MIT 声明（见 `THIRD_PARTY_NOTICES.md`）。

## 8. 其他许可族的最小合规动作

| 许可族 | 义务要点 | 本项目落点 |
| --- | --- | --- |
| MIT（自有、vendor） | 保留版权与许可文本 | `LICENSES/MIT-chapter-whale.txt`、`LICENSES/MIT-our-free-model.txt`；vendor 目录内 LICENSE 原样保留 |
| OFL-1.1（3 款字体） | 保留版权与许可、修改版不得用保留字体名 | `assets/fonts/*-OFL.txt` 原样保留；字体已改名 `Whale Geometric` / `Whale Text` / `Whale Editorial`（`assets/fonts/README.md:7-11`） |
| Apache-2.0（aiohttp、playwright、requests 等） | 附许可与 NOTICE，标明修改 | 各包 `dist-info` 自带 LICENSE；Playwright driver 目录内 `NOTICE`、`ThirdPartyNotices.txt` 原样保留 |
| MPL-2.0（certifi） | 文件级 copyleft，未修改即原样分发即可 | 未修改，随包 `certifi-2026.10.23.dist-info` |
| PSF-2.0（CPython、typing_extensions 等） | 保留许可文本 | `runtime/python/LICENSE.txt` 随包 |

## 9. 分发放行矩阵

| 场景 | 放行条件 | 当前状态 |
| --- | --- | --- |
| 本地修复、内部候选验证 | 无需额外条件（不对外分发） | **放行** |
| 内测分发（受控对象、非公开） | 随包带 `LICENSES/`、`THIRD_PARTY_NOTICES.md`；告知 GPLv3 与源码位置 | **放行**（需先完成 §10 的必做项 1–2） |
| npm 发布插件包（源码形态） | `package.json` 的 `license` 改为 `GPL-3.0-only`；`files` 增加 `LICENSES/`；README 许可章节就位 | **未放行**（等字段变更，见 §11） |
| GitHub Release 完整运行包（公开二进制） | 上述 + 发行 tag 与源码可获取 + `runtime-manifest.json` buildId 与包一致 + 待核验项（H1–H4）在 notices 中有明确披露 | **未放行** |
| 插件市场分发（losebird 等） | 上述 + 市场条款允许 GPLv3 组件 + 市场元数据 license 与实际一致（`market/losebird-entry.json:24`） | **未放行**（市场条款需人工确认） |
| 二次开发/下游再分发 | 下游自动获得上游 GPLv3 授权（§10），须保留 `LICENSES/` 与修改说明 | 放行（由下游自行承担合规） |

阻塞项只有三类：①`package.json` 字段与 `files` 白名单（主 agent 统一改）；②市场条款确认；③H1–H4 的浏览器/FFmpeg 声明披露。功能与源码侧没有阻塞。

## 10. 必做项与待核验

必做（发布前）：

1. `package.json` 增加 `files` 项 `"LICENSES/"`，否则 npm 包不含 GPLv3 全文（GPLv3 §5(a) 不满足）。
2. 发行说明与 README 指向 `docs/license-decision.md` 的源码获取段（§6）。
3. 每个公开 Release 的 tag 必须与发行包 `runtime-manifest.json` 的版本一致，且 tag 内包含本文件。

待核验（详见 `docs/license-inventory.md` §3）：D1 `backend/fanqie_auto_publish` 的权利归属；H1 Chromium 第三方许可文本；H2 FFmpeg 构建是否含 GPL 组件；H3 WinLDD；H4 Playwright 内嵌 `node.exe`。前四项未闭环前，发行说明只能按“已知信息 + 明确披露”表述，不得声称已核对全部第三方条款。

## 11. package.json 变更建议

| 字段 | 现值 | 建议值 | 理由 |
| --- | --- | --- | --- |
| `license` | `SEE LICENSE IN THIRD_PARTY_NOTICES.md`（`package.json:7`） | `GPL-3.0-only` | 发行包按 §4 构成 GPLv3 组合作品，SPDX 标识是唯一能被 npm、市场与合规扫描器正确解析的写法；`SEE LICENSE IN …` 不是 SPDX 表达式，工具链会当作未知许可，市场审核也常直接拒绝 |
| `files` | 无 `LICENSES/`（`package.json:44-63`） | 追加 `"LICENSES/"` | 保证 GPLv3 全文与 MIT 文本随 npm 包分发（GPLv3 §5(a)） |
| 其他 | 不变 | 不变 | 版本号由主 agent 统一改；不改 `dependencies`/`peerDependencies` |

选择 `GPL-3.0-only` 而不是 `GPL-3.0-or-later`：上游没有 “or later” 声明（§3），标 `-or-later` 会超出上游授权范围。

选择 SPDX 而不是保留 `SEE LICENSE`：本项目的混合许可已由 `THIRD_PARTY_NOTICES.md` + `LICENSES/` 完整表达；`license` 字段的职责是给机器读的“整体分发条款”，而整体就是 GPLv3。若出于品牌考虑坚持显示“多许可”，替代写法是 `"license": "GPL-3.0-only"` 配合 `README` 中一句“自有代码同时以 MIT 提供”，而不是把字段改回自由文本。

配套（不在本文件改动范围，供主 agent 执行）：

```jsonc
// package.json 片段
"license": "GPL-3.0-only",
"files": [
  "LICENSE",
  "LICENSES/",
  "THIRD_PARTY_NOTICES.md",
  // …其余保持不变
]
```

市场元数据同步：`market/losebird-entry.json:24` 的 `"license"` 已改为 `"GPL-3.0-only"`（与 §11 一致）；`longDescription`（`:14`）中“连接器 MIT，写作器 GPL v3”的表述保留，建议其后补一句“整体发行按 GPLv3 组合分发，详见仓库 LICENSES/ 与 docs/license-decision.md”（该字段不属于许可证字段，本次未改）。
