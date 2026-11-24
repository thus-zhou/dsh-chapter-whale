# 码章鲸 0.7.2 验证记录

本轮修复多书上下文隔离、新书引导、发布预检和排期恢复。完整变更见 [更新日志](CHANGELOG.md)。公开发行状态以 [GitHub Release v0.7.2](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.2) 和 [npm 版本列表](https://www.npmjs.com/package/dsh-chapter-whale?activeTab=versions) 为准（npm `latest = 0.7.2` 已通过 SLSA provenance 与公开下载字节校验：`12,459,335` 字节，SHA-256 `53051abc86c3e4379aba9de6aec208cbafed6d61c19fb46aeb84bc2e7341c95b`，与 GitHub 发行包完全一致）。

Windows 轻量包从 [v0.7.0](https://github.com/thus-zhou/dsh-chapter-whale/releases/tag/v0.7.0) 归档取用固定的 Python 和浏览器运行时（`runtimeAssetBuildId=b181c5765a6e17a54fdc503b1aab0701a109428fbca8969a08bfc88c82957e4f`），始终安装 `v0.7.2` 包内后端代码（`buildId=f3a5f8cbe3bfa70ef1d03604f2647d1f1184d6acabd20b18470cd51a9b8916e3`）。macOS 首启基于 Python 3.11+ 自动创建隔离 `.venv`。`0.7.2` 平台安装与多环境校验均已通过：[Distribution first start #45400377607](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45400377607)（`windows-install` + `macos-install`）与 [Source checks #45401789212](https://github.com/thus-zhou/dsh-chapter-whale/actions/runs/45401789212)。

本轮发布前执行了 Node 测试、100 项后端定向回归测试和托管运行环境完整性校验。真实番茄网页发布与既有 DSH 桌面个人工作区原地升级仍待验证。

---

## 0.7.1 历史记录
`0.7.1` 在 `0.7.0`（[PR #1](https://github.com/thus-zhou/dsh-chapter-whale/pull/1)）基础上正式开放 macOS（Apple Silicon / Intel）DSH 插件支持；后端目录与 Windows 固定运行时清单与 `0.7.0` 完全一致。

Windows 轻量包复用 `v0.7.0` 固定运行时归档（字节数与 SHA-256 记录在 `runtime-download.json`）；macOS 首启基于本机 Python 3.11+ 在 `~/Library/Application Support/ChapterWhale/workspace/.venv` 自动创建隔离环境并安装 `deploy/macos/requirements-macos.txt`。

---

## 本轮定位与许可边界

- **目标版本**：`0.7.2`（Windows x64 完整支持 + macOS Apple Silicon / Intel DSH 插件首启隔离 `.venv` 支持）。
- **组合分发许可**：`GPL-3.0-only`（见 `package.json`、`LICENSES/GPL-3.0.txt`、`THIRD_PARTY_NOTICES.md`、`docs/license-decision.md` 方案 A）。
- **清单摘要（`buildId`）**：`f3a5f8cbe3bfa70ef1d03604f2647d1f1184d6acabd20b18470cd51a9b8916e3`（`runtime-manifest.json`，复用的 `v0.7.0` Windows 运行时归档 `runtimeAssetBuildId=b181c5765a6e17a54fdc503b1aab0701a109428fbca8969a08bfc88c82957e4f`）。

---

## 模块状态与诚实边界

| 能力域 | 本地离线测试 / 代理状态 | 真实环境状态（明确未验） |
| --- | --- | --- |
| DSH 插件桥与原生面板 | 代理写路由白名单防漂移门禁 + 本地回环端到端代理冒烟 + JS 单元测试 | Windows 上用 DSH 0.2.2-rc.3 的独立 Web profile 实装，验证面板、服务启动和建书。桌面 profile 的原地升级待验 |
| 番茄主流程与排期缓冲 | 队列状态机、`capability`/`preview`/`apply`/`stop`/`resume`/`reconcile`/`resolve` 离线全通 | **真实番茄网页发布/定时控件/验证码恢复尚未做真机实测**；未确认能力前默认禁止静默自动排期 |
| 长篇连续性与风格预检 | 实体状态派生、预算门禁、检索影响面、忽略词表与反馈记账离线通过 | 真实长篇生成调优需带模型预算实测（本轮模型预算 = 0） |
| 读者反馈与观察卡 | CSV 预览/导入/撤销批次、脱敏聚类、候选观察卡采纳/撤销/单章重排离线通过 | 观察卡默认不主动写入默认生成提示词 |
| Linux / macOS 常驻存稿 | `linux/{amd64,arm64}` 与 `macos/{arm64,amd64}` 归档打包、sidecar 校验、cross-arch 防护离线通过 | **无真实 Linux ARM64 与 Apple Silicon / Intel macOS 物理机实跑记录** |
| 单目标浏览器与平台契约 | 登录会话状态机、只读结构核对、七猫本地导出与受保护写入拒绝离线通过 | 真实七猫页面未对接；获准单章默认关闭 |
| 运行历史与 Webhook 通知 | 本地运行投影、发件箱/重试/死信处理本地回环接口通过 | **真实外网 Webhook 接收端未实测** |
| 安装包与升级 | 轻量包与完整包分别在独立工作目录验证首次启动 | 既有安装目录的连续升版和回退待验（T22） |

---

## 本轮本地实跑验证快照

- **JS / 桥接 / UI / 门禁测试（`npm test`）**：**102 pass / 0 fail**（含 `client.test.mjs`、`gate.test.mjs` 路由防漂移扫描、`p04-bridge.test.mjs`、`market.test.mjs`、`manifest.test.mjs`、`managed-runtime.test.mjs`、`release-check.test.mjs`）。
- **后端集成离线测试（`python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend`）**：**707 OK（skipped=4）**，0 失败。
- **后端管理端离线测试（`python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend`）**：**151 OK**，0 失败。
- **本地回环代理 E2E 冒烟（`index.js` `createHandler()` + `manager/app.py`，`start_dispatcher=False`，真实模型 = 0，真实外写 = 0）**：**9/9 阶段全通**（`_session` 握手 → 创建项目 → 创建并保存 `platform_scheduled` 任务 → `schedule` 能力/预览/应用/启停/待核对 → `entities`/`precheck`/`ignore`/`action`/`retrieval`/`evidence/impact` → `readers` 字典/预览/导入/评论/观察卡/撤销批次 → `browser/target`+`status` → `publish/platforms` + 七猫导出 + 七猫 `submit` 被拒且 `writes=0` → `runs`/`notifications` → `422 invalid_request` 统一错误体透传）。
- **清单与服务归档构建校验**：
  - `runtime-manifest.json`：`3420` 文件，LF 一致性校验与 `pack-bundle.py` 通过，生成 `dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz` 与 `runtime-download.json`。
  - Linux / macOS 四份服务归档（`linux-amd64` 1180 载荷文件、`linux-arm64` 1180 载荷文件、`macos-arm64` 1177 载荷文件、`macos-amd64` 1177 载荷文件）全部 `--verify` 通过（`ok: true, problems: []`）。
- **验包方法**：见[组装完整发行包](docs/distribution.md#7-组装完整发行包)。
