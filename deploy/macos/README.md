# 码章鲸常驻存稿服务 · macOS（ARM64 / Intel，原生进程，0.7.0 起）

本目录覆盖 **macOS 原生进程** 两种组合：Apple Silicon（`macos-arm64`）与 Intel（`macos-amd64`，0.7.0 起）。
没有容器格，没有浏览器/登录格，也不承诺 DSH 桌面宿主兼容。
本机没有在真实 macOS 上跑过验收；在补齐实机证据前，这两格都保持「待实机」。

## 两种归档

| 目标 | 归档名 | 适用机器 |
| --- | --- | --- |
| `macos-arm64` | `dsh-chapter-whale-service-macos-arm64-<version>.tar.gz` | Apple Silicon 原生 |
| `macos-amd64` | `dsh-chapter-whale-service-macos-amd64-<version>.tar.gz` | Intel Mac 原生 |

构建命令：

```sh
python scripts/build-macos-service.py --arch arm64     # 或在 Apple Silicon 上交叉构建 Intel 包
python scripts/build-macos-service.py --arch amd64
python scripts/build-macos-service.py --arch amd64 --verify .tmp/macos-service/dsh-chapter-whale-service-macos-amd64-<version>.tar.gz
```

**Rosetta 不算 Intel 实机**：在 Apple Silicon 上经 Rosetta 跑 x86_64 解释器时，
`resident_service platform` 会把 `macos-amd64` 标成 `rosetta_translation:not_native`，
不能据此把 Intel 格写成已验证。交叉构建同理，只证明「包能构建、校验通过」。

## 安装布局

| 路径 | 用途 | 可写 |
| --- | --- | --- |
| `/opt/chapter-whale` | 代码（本归档解包后改名） | 否 |
| `/Users/Shared/chapter-whale` | 数据卷：正文、任务、数据库、日志 | 是，唯一可写卷 |
| `~/Library/LaunchAgents/com.chapterwhale.service.plist` | 启动项 | — |

代码目录与数据卷可以换位置，但两者必须分开；数据卷不要放在网络盘上。

## 安装步骤

```sh
sudo mkdir -p /opt/chapter-whale /Users/Shared/chapter-whale/logs
sudo tar -xzf dsh-chapter-whale-service-macos-arm64-<version>.tar.gz -C /opt/chapter-whale
sudo chown -R "$(id -un)":"$(id -gn)" /Users/Shared/chapter-whale
mkdir -p ~/Library/LaunchAgents
cp /opt/chapter-whale/deploy/macos/com.chapterwhale.service.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/com.chapterwhale.service.plist
```

> `launchctl bootstrap` 需要 plist 里 `ProgramArguments`、`WorkingDirectory` 指向的路径真实存在；
> 解包后目录名若不是 `/opt/chapter-whale`，先改 plist 再 bootstrap，否则会反复重启。

## 启动、健康、停止

```sh
launchctl print gui/"$(id -u)"/com.chapterwhale.service | head -40   # 看 state / pid
cd /opt/chapter-whale/backend && PYTHONPATH=. python3 -B -X utf8 -m integration.resident_service health --root /Users/Shared/chapter-whale
launchctl bootout gui/"$(id -u)"/com.chapterwhale.service             # 发 SIGTERM，服务停认领后退出
```

`health` 的退出码：`0` 四段都正常；`1` 有任一段不健康（原因打印在 stderr）。
进程内还有 25 秒兜底：收到 SIGTERM 后先停认领、写检查点，超时由守护线程强制退出；
plist 的 `ExitTimeOut` 是 40 秒，给上面的兜底留出余量。

前台手动跑（不走 launchd、便于看输出）：

```sh
CHAPTER_WHALE_CODE=/opt/chapter-whale CHAPTER_WHALE_ROOT=/Users/Shared/chapter-whale \
  /opt/chapter-whale/deploy/macos/run.command
```

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 正常停止（含 `--once` 跑完） |
| 1 | 健康检查不通过、未捕获异常，或看门狗在限时后强制退出（`state=stopping`；`KeepAlive` 会重启） |
| 2 | 已有实例持有任务锁（只写 stderr，不覆盖检查点；launchd 会在 `ThrottleInterval` 后重试） |
| 4 | 数据卷不可用（只读或空间不足；同上，会重试） |
| 64 | `run.command`：找不到安装目录 |
| 65 | `run.command`：数据卷不存在 |
| 66 | `run.command`：数据卷不可写 |
| 69 | `run.command`：PATH 里找不到 `python3` |

## 能力与边界

- **有**：单实例锁（同一数据卷只允许一个协调器）、崩溃/失败任务跨时段重试、启动补齐未完成步骤、
  时区按任务配置、SIGTERM 停认领 + 检查点、`health` 四段、白名单备份与校验还原。
- **没有**：浏览器自动化、平台登录、发布写操作、DSH 桥接、通知外发。
  这些在 macOS 两种架构上都是「未开放」，不要按标题推断为已接入。
- 凭据：本版不迁移任何 Windows DPAPI 密文；模型密钥在目标机器上重新配置。
  非 Windows 主机上 `credential_codec` 会明确拒绝 DPAPI 分支，属预期行为。
- 解释器：Intel 包要用原生 x86_64 的 `python3`（`arch -x86_64` 或 Rosetta 只作临时排障，
  其结果不作为实机证据）。LaunchAgent 不继承登录 shell 的 PATH，`plist` 已显式给
  `PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`；
  安装前用 `command -v python3` 确认命中的是 3.11+ 原生解释器。若装在别处，
  请同时改 `ProgramArguments[0]`（绝对路径）与 `PATH`，不要只改 PATH。

## 文件系统注意事项

- 默认 APFS 大小写不敏感：`正文/第0001章.md` 与 `第0001章.MD` 会被视为同一文件。
  服务按后缀小写列出正文，并在「同一个名字只差大小写」时判 `case_conflict`，
  不会静默覆盖；跨平台迁库前请先统一扩展名大小写。
- 路径允许空格与中文；`run.command` 全部使用带引号的变量，不要改成裸路径拼接。
- 数据卷先用本地盘。NAS（SMB/NFS）上的文件锁语义不可靠，会破坏单实例保证；
  需要异地副本时用 `backup` 产物做离线备份，不要把数据卷直接放到网络盘。

## 备份与还原

```sh
cd /opt/chapter-whale/backend
PYTHONPATH=. python3 -B -X utf8 -m integration.resident_service backup \
  --root /Users/Shared/chapter-whale --dest /Users/Shared/chapter-whale-backup-$(date +%Y%m%d)
```

备份是白名单递归（`works/`、`integration_data/`、`logs/`），跳过服务自身状态目录与 `-wal/-shm`，
并写 `backup.json`（相对路径 + sha256 + 卷标识）。还原前必须先 `launchctl bootout`：
服务持锁时还原会被拒绝；换了数据卷位置时需显式 `--allow-root-mismatch`。

## 已做 / 未做（如实）

- 已做：macOS ARM64 与 Intel 两种归档的构建与架构校验（拒 ELF、`.so`、Windows 二进制、CRLF 脚本、
  链接成员与路径穿越成员，并按构建口径校验载荷摘要与文件数）、LaunchAgent 与 `run.command` 两种启动方式。
- 未做：真实 Apple Silicon 与 Intel Mac 上的安装/重启/断电/磁盘满/只读卷验收；`launchctl` 行为的实机证据；
  代码签名与公证（本版不分发 `.app`，只有 tar.gz 与脚本）。
- 构建脚本在仓库里（`scripts/build-macos-service.py`），不在 npm 安装包内。
