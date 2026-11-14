# 分发与许可边界（M08）

本文件记录「码章鲸 / DSH Chapter Whale」发行包的来源、校验方式、更新路径与许可现状。
它描述的是**当前实际行为**，不是对未来的承诺。

## 1. 包内各部分的来源

| 部分 | 内容 | 来源 | 校验 |
| --- | --- | --- | --- |
| 插件源码 | `index.js`、`client.js`、`managed-runtime.mjs`、`locale/`、`cordis.patch.yml` | 本仓库 `main` 分支，随 npm 包发布 | npm tarball 与 GitHub Release 附件 |
| 后端 | `backend/manager`（面板与任务）、`backend/integration`（A—E 流水线、成本账本、版本存储、质量门禁）、`backend/fanqie_auto_publish`（发布器与放行规则）、`backend/webnovel-writer`（写作器，编辑器侧 FastAPI） | 本仓库同一提交 | `runtime-manifest.json` 的 sha256 逐文件校验 |
| 固定 Python | `runtime/python`（CPython 3.13.17 embeddable amd64） | `https://www.python.org/ftp/python/3.13.17/python-3.13.17-embeddable-amd64.zip` | 构建时校验 `pythonSha256`，随包内容再进清单 |
| Python 依赖 | `runtime/python/Lib/site-packages`（fastapi、uvicorn、httpx、playwright 等，版本锁定） | PyPI，`requirements-runtime.lock` 记录 `name==version --hash` | `pip --require-hashes` 安装；结果进清单 |
| 浏览器 | `runtime/browsers/chromium-*` | 由锁定的 Playwright 驱动安装 | 结果进清单 |

`runtime-manifest.json` 的 `buildId` 是「所有清单文件路径 + sha256」的摘要。清单包含后端与运行时，不包含插件源码——插件源码来自安装它的 DSH 插件包，属于另一条信任链。

## 2. 信任模型

- **哈希只证明内容一致，不证明来源。** 下载地址被写死为 `https://github.com/thus-zhou/dsh-chapter-whale/releases/download/<tag>/<file>.tgz`，校验大小与 sha256 后才解包；这能挡住传输损坏和错包，但不能替代发布方签名。
- **没有签名清单与可信公钥，自动更新保持关闭**（`managed-runtime.mjs` 的 `AUTO_UPDATE_ENABLED = false`、`updateAvailable()` 固定返回关闭与原因）。程序不会自己去取「最新版本」，新版本由用户手动下载安装包覆盖安装。
- 若要启用可跟随新版本的自动更新，需要先具备：Ed25519（或同级）发布签名、随客户端分发的公钥、签名清单与资产摘要同时校验、错误签名拒绝、降级（版本回退）策略与密钥轮换办法。这些条件目前都不具备，因此该能力不启用。
- 哈希校验、`buildId` 比对、解包路径检查都属于完整性检查；文档与界面不得把它们说成「来源认证」。

## 3. 安装、覆盖与回滚

1. 解包发行包，插件由 DSH 加载；首次启动时 `prepareManaged` 把 `backend/{manager,integration,webnovel-writer,fanqie_auto_publish,vendor}`、`runtime/python`、`runtime/browsers` 复制到 `%LOCALAPPDATA%\ChapterWhale\workspace`。
2. 复制完成后，用 `runtime-manifest.json` 对已安装的后端逐文件复核；有不一致或缺失就报错并且**不写入** `.chapter-whale-release.json`，避免把半成品当作已完成安装。
3. 已有同 `buildId` 的安装再次启动时，会抽查 `manager` 与 `integration` 的关键文件；与清单不符则要求重新安装，而不是继续用旧源码运行。
4. 运行时目录里不得存在后端模块的同名副本（`runtime/python/Lib/site-packages` 下的 `manager`/`integration`/`fanqie_auto_publish`/`services`/`routers`），否则旧源码可能先于新代码被 `import`；`scripts/check-release.mjs` 会拒绝这种清单。
5. 回滚：保留上一版发行包的 tgz 与 `SHA256SUMS.txt`，重新安装即为回滚；工作区里的作品、`.webnovel/`、`integration_data/` 不会被安装流程删除。

## 4. 发行前自动检查

`node scripts/check-release.mjs`（CI 与 `prepublishOnly` 使用）：

- 清单内每个文件存在且 sha256 一致（无捆绑运行时则跳过 `runtime/` 前缀）。
- 拒绝 `backend/{accounts,books,integration_data,playwright-browsers,.env}` 这类本地状态。
- 拒绝清单里的测试残留与私稿痕迹：`__pycache__`、`.pyc/.pyo`、`test_*.py`、`.webnovel/`、`正文/`、`integration_data/`、`*.dpapi`、`*.publish.json`、`scheduler.json*`。
- 要求关键文件在清单内：`backend/manager/app.py`、`backend/integration/writer_runner.py`、`backend/fanqie_auto_publish/publication_safety.py`、`runtime/python/python.exe`。
- 无捆绑运行时，校验 `runtime-download.json` 的 `buildId`、大小、sha256 与固定下载地址；非 `--local` 时 `package.json` 不得为 `private`。

发行包内不含作品正文、账号数据、密钥（`secret_store` 的 DPAPI 文件在工作区，不随包）与测试文件；测试仍保留在源码仓库中。

## 5. 许可现状

| 文件 | 作用 | 现状 |
| --- | --- | --- |
| `LICENSE` | 本仓库自身许可 | MIT（Copyright (c) 2026 novel-helper contributors） |
| `backend/webnovel-writer/LICENSE` | 上游写作器许可 | GPL v3 全文（35 KB），随包分发 |
| `backend/webnovel-writer/README.md` | 上游说明 | 声明 GPL v3 与上游仓库地址 |
| `THIRD_PARTY_NOTICES.md` | 第三方组件汇总 | 覆盖写作器、发布适配、Our Free Model、Python、Chromium/Playwright 与依赖 |
| `backend/vendor/**/LICENSE` | 第三方随包许可 | 各目录保留 |

`npm pack` 实测包含上述全部许可文本（`LICENSE`、`THIRD_PARTY_NOTICES.md`、写作器与 vendor 的 LICENSE），未删除任何随包许可文件。

## 6. 需要项目所有者决定的许可问题

以下问题涉及权利判断，不自行更改全项目许可证，也不作未经核实的法律结论：

1. **根 `LICENSE` 是 MIT，而发行内容包含 GPL v3 的 `backend/webnovel-writer`。** 当前做法是保留上游许可与完整源码。是否需要在 README/发行说明里明确「整体发行包含 GPL v3 组件，MIT 仅适用于本项目自有代码」？
2. **GPL v3 组件的「对应源码」提供方式**：目前随包给了 `backend/webnovel-writer/` 全量源码与 GPL 全文。是否还需要在 Release 页提供单独源码归档链接，或声明源码获取方式（书面要约）？
3. **`backend/vendor/our-free-model-source` 的来源与许可**：现有记录为「依据维护者确认的来源说明」，是否要补充上游仓库 URL 与版本号，便于第三方核实？
4. **发布适配组件（`fanqie_auto_publish`）** 标注为「AI 辅助开发，不附加个人署名」。是否需要补一个明确的版权行（例如「Copyright (c) 2026 novel-helper contributors, MIT」）？
5. **市场条目的许可字段**（`market/catalog-entry.yml`、`index.json`）应与第 1 条结论保持一致；确定后统一更新。

在这些问题有结论前，发行包按现状发布：不删除任何许可文本，不更改 `LICENSE`，不声称「许可已全部核实」。

## 组装完整发行包

```
python scripts/build-runtime.py          # 重建 runtime-manifest.json（发行清单）
python scripts/pack-bundle.py            # npm 文件 + 清单内的 runtime → .tmp/bundle/*.tgz
python scripts/pack-bundle.py --keep-stage   # 保留解包目录用于核对
```

`pack-bundle.py` 只复制清单里列出的文件，组装后检查是否混入 `__pycache__`、`.pyc`、
`test_*.py`；包内 `runtime-download.json` 的 `buildId` 会跟随清单，
其余摘要字段仅供参考，安装器以 Release 页与 `SHA256SUMS.txt` 为准。
