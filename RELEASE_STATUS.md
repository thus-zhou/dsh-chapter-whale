# 码章鲸 Release 状态说明（0.7.0 · PR 候选）

当前分支（`feat/v0.7.0`）处于 **0.7.0 统一收口与 Pull Request 审查阶段**：**未合并 `main`、未打 git tag、未发布 GitHub Release、未发布 npm `latest`、未向插件市场提交新版本收录**。

包内追踪文件一律**不硬编码归档或安装包自身的 SHA-256 与字节数**；本轮本地构建的 `0.7.0` 候选产物摘要与验包回执以仓库外忽略目录 `.v070/candidate/HASHES.txt` 为准。

---

## 本轮定位与许可边界

- **目标版本**：`0.7.0`（将 `0.5.0` 之后在 `feat/v0.7.0` 合拢的排期缓冲、连续性与预检、读者反馈、常驻存稿服务包、单目标浏览器试点、多平台能力契约，以及 DSH 前后端联调统一收敛为一版 PR）。
- **组合分发许可**：`GPL-3.0-only`（见 `package.json`、`LICENSES/GPL-3.0.txt`、`THIRD_PARTY_NOTICES.md`、`docs/license-decision.md` 方案 A）。
- **清单摘要（`buildId`）**：`64ac73751d4c525b13d5830e9d09617315a1c424106f63f2b6f19fc25be5fa55`（`runtime-manifest.json`，共 `3418` 个受管文件）。

---

## 模块状态与诚实边界

| 能力域 | 本地离线测试 / 代理状态 | 真实环境状态（明确未验） |
| --- | --- | --- |
| DSH 插件桥与原生面板 | 代理写路由白名单防漂移门禁 + 本地回环端到端代理冒烟 + JS 单元测试 | DSH 桌面端实机 UI 点击回放需安装后在宿主中验收 |
| 番茄主流程与排期缓冲 | 队列状态机、`capability`/`preview`/`apply`/`stop`/`resume`/`reconcile`/`resolve` 离线全通 | **真实番茄网页发布/定时控件/验证码恢复尚未做真机实测**；未确认能力前默认禁止静默自动排期 |
| 长篇连续性与风格预检 | 实体状态派生、预算门禁、检索影响面、忽略词表与反馈记账离线通过 | 真实长篇生成调优需带模型预算实测（本轮模型预算 = 0） |
| 读者反馈与观察卡 | CSV 预览/导入/撤销批次、脱敏聚类、候选观察卡采纳/撤销/单章重排离线通过 | 观察卡默认不主动写入默认生成提示词 |
| Linux / macOS 常驻存稿 | `linux/{amd64,arm64}` 与 `macos/{arm64,amd64}` 归档打包、sidecar 校验、cross-arch 防护离线通过 | **无真实 Linux ARM64 与 Apple Silicon / Intel macOS 物理机实跑记录** |
| 单目标浏览器与平台契约 | 登录会话状态机、只读结构核对、七猫本地导出与受保护写入拒绝离线通过 | 真实七猫页面未对接；获准单章默认关闭 |
| 运行历史与 Webhook 通知 | 本地运行投影、发件箱/重试/死信处理本地回环接口通过 | **真实外网 Webhook 接收端未实测** |
| npm / 市场正式发布与升级 | 轻量/完整候选包打包与本地自洽检验流程覆盖 | 未执行两次真实目录连续升级/回退（T22）、未执行 `npm publish` 与正式发布 |

---

## 本轮本地实跑验证快照

- **JS / 桥接 / UI / 门禁测试（`npm test`）**：**101 pass / 0 fail**（含 `client.test.mjs`、`gate.test.mjs` 路由防漂移扫描、`p04-bridge.test.mjs`、`market.test.mjs`、`manifest.test.mjs`、`managed-runtime.test.mjs`、`release-check.test.mjs`）。
- **后端集成离线测试（`python -B -X utf8 -m unittest discover -s backend/integration -p "test_*.py" -t backend`）**：**707 OK（skipped=4）**，0 失败。
- **后端管理端离线测试（`python -B -X utf8 -m unittest discover -s backend/manager -p "test_*.py" -t backend`）**：**151 OK**，0 失败。
- **本地回环代理 E2E 冒烟（`index.js` `createHandler()` + `manager/app.py`，`start_dispatcher=False`，真实模型 = 0，真实外写 = 0）**：**9/9 阶段全通**（`_session` 握手 → 创建项目 → 创建并保存 `platform_scheduled` 任务 → `schedule` 能力/预览/应用/启停/待核对 → `entities`/`precheck`/`ignore`/`action`/`retrieval`/`evidence/impact` → `readers` 字典/预览/导入/评论/观察卡/撤销批次 → `browser/target`+`status` → `publish/platforms` + 七猫导出 + 七猫 `submit` 被拒且 `writes=0` → `runs`/`notifications` → `422 invalid_request` 统一错误体透传）。
- **清单与服务归档构建校验**：
  - `runtime-manifest.json`：`3418` 文件，LF 一致性校验与 `pack-bundle.py` 通过，生成 `dsh-chapter-whale-runtime-win32-x64-0.7.0.tgz` 与 `runtime-download.json`。
  - Linux / macOS 四份服务归档（`linux-amd64` 1180 载荷文件、`linux-arm64` 1180 载荷文件、`macos-arm64` 1177 载荷文件、`macos-amd64` 1177 载荷文件）全部 `--verify` 通过（`ok: true, problems: []`）。
- **候选包详情与验包回执**：完整包、轻量包、四份服务归档及 `verify-full.json` / `verify-light.json` 摘要统一记录于 `.v070/candidate/HASHES.txt`。
