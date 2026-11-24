# 0.7.0 发布验收与本机实装记录

日期：2026-11-24（北京时间）。

## 修改与交付范围

- **UI 与交互重构（Liquid Glass v5）**：在 DSH 原生插件（[client.js](../client.js)、[atelier-native.css](../assets/atelier-native.css)）与独立 Web 控制台（[liquid-glass.js](../backend/manager/static/liquid-glass.js)、[liquid-glass.css](../backend/manager/static/liquid-glass.css)）统一上线 3 岛悬浮胶囊顶栏、四通道严格语义色板、书卷独立护眼稿纸、三套主题、60fps Gemini 极光进度条与四项光学材质实时滑块。
- **0.7.0 后端核心收敛**：整合番茄排期缓冲与状态对账、长篇实体状态与上下文检索、风格预检与忽略词表、读者反馈观察卡、七猫只读导出、Linux/macOS 常驻存稿归档，以及 GPL-3.0-only 合规清单（[RELEASE_STATUS.md](../RELEASE_STATUS.md)）。
- **实机暴露缺陷修复**：补齐工作台 `queue` 声明、修复独立控制台 7 处后端接口字段映射、修正外观抽屉 Flex 高度裁切、门控服务未启动前的 `502` 轮询、修复所有子页面在 Flex 容器下的全宽布局，并统一 `normalizePath` 解析 Windows 8.3 短路径与符号链接。
- **演示图与文档刷新**：在 `DSH 0.2.2-rc.3` 完全隔离 `DSH_HOME` 沙箱中重截 9 张 `0.7.0` 演示图，同步更新 `README.md`、`docs/screenshots.md`、`docs/quickstart.md` 与 `market/*`。

## 本地与云端验证记录

- **Node / 插件门禁（`npm test`）**：`103 / 103` 全部通过（0 失败），新增 `DashboardPage` 无异常渲染、`readAppearance` 迁移限幅、`HUBS` 完整度、`liquid-glass.js` 接口契约及 Windows 8.3 短路径兼容回归检查。
- **发行清单校验（`node scripts/check-release.mjs`）**：通过（`3420` 个受管文件哈希与纯 LF 字节一致，`buildId = b181c5765a6e17a54fdc503b1aab0701a109428fbca8969a08bfc88c82957e4f`）。
- **后端 Python 离线单测（本机 & GitHub Actions CI）**：
  - 本机执行：`backend/integration` `707 OK (skipped=4)`、`backend/manager` `151 OK`，修复 `test_resident_service.py` 与 `test_draft_delivery.py` 路径隔离后测试状态零泄漏。
  - GitHub Actions `Source checks`：Windows / Ubuntu × Python 3.11 / 3.13 + Node 矩阵 **12 / 12 全部通过**。
- **本机 DeepSeek Harness `0.2.2-rc.3` 隔离实装 E2E**：
  - 使用本地 `dsh.cmd` 新建独立 profile 链接加载 `0.7.0`、拉起内嵌 Python manager（`127.0.0.1:18975`）、在 DSH UI 创建作品、切换工作区、切换深浅外观及直接访问独立 Web 端；结果 `dshPageErrors = []`、`dshHttp5xx = []`、`standalonePageErrors = []`、移动端 `390px` 零横向溢出、DSH 代理接口全 200。

## 诚实边界（本轮未实测项）

- 真实番茄 / 七猫作家后台在线登录、真实章节投稿与定时排期交互未在真实站点实测。
- 真实付费模型调用与长篇生成费用消耗未实测。
- Linux ARM64 与 Apple Silicon / Intel macOS 物理机未实机运行。
- 用户个人桌面端 `desktop` profile（仍保持既有 `0.4.4` 与 `%LOCALAPPDATA%\ChapterWhale`）在本轮验收中保持未修改。
