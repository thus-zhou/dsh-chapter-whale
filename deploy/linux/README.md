# 码章鲸常驻存稿服务（Linux amd64 / arm64）

本目录覆盖 0.7.0 起的 Linux 服务化产物：固定依赖、非 root UID、单可写数据卷、单协调器与
优雅停止。支持 `linux/amd64` 与 `linux/arm64` 两种目标；两种架构都**不包含** Chromium、
浏览器发表、OFM 运行时、DSH 宿主模型与免费池策略，这些项在
`integration/resident_service.py` 的能力盘点里标记为 disabled。

查看当前主机能跑哪种目标（不改状态、不调模型）：

```sh
python -B -X utf8 -m integration.resident_service platform
```

输出里 `verified_here` 只对当前主机架构为真；跨架构构建（buildx、交叉编译）不会把
另一格写成已验证，需要真实 aarch64 主机按验收清单重跑。

## 构建产物与架构

| 目标 | 归档名 | 容器平台 | 说明 |
| --- | --- | --- | --- |
| Linux amd64 | `dsh-chapter-whale-service-linux-amd64-<version>.tar.gz` | `linux/amd64` | 0.7.0 起，需实机验收 |
| Linux arm64 | `dsh-chapter-whale-service-linux-arm64-<version>.tar.gz` | `linux/arm64` | 0.7.0 起，需实机验收 |

```sh
# 构建两种架构的归档（构建机上只做打包，不做实机声明）
python -B -X utf8 scripts/build-linux-service.py --arch amd64
python -B -X utf8 scripts/build-linux-service.py --arch arm64

# 校验归档：清单平台/架构、文件名、是否混入 Windows 二进制、脚本是否 CRLF
python -B -X utf8 scripts/build-linux-service.py --arch arm64 \
  --verify .tmp/linux-service/dsh-chapter-whale-service-linux-arm64-<version>.tar.gz

# 容器镜像（buildx 按目标平台拉取同架构 python 基础镜像）
docker buildx build --platform linux/arm64 -f deploy/linux/Dockerfile -t chapter-whale:0.7.0-arm64 .
```

`linux-service-manifest-<arch>.json` 逐文件记 sha256；`verify_archive()` 读 tar 成员本身，
文件名对不上、清单架构不符、含 `.exe/.dll/.pyd/.dylib` 或脚本含 CRLF 都直接判失败。

## 目录与身份

| 项 | 值 |
| --- | --- |
| 进程用户 | `10001:10001`（非 root） |
| 数据卷 | `/data`（唯一可写目录） |
| 作品/任务/正文/记忆/费用/日志 | 全部位于 `/data`，路径映射见下 |
| 配置与机密 | 任务与机密都在 `/data/integration_data`；`/config` 只作为以后放只读机密的挂载点，当前版本启动时不读取它 |
| 时区 | 由任务字段决定（默认 `Asia/Shanghai`），容器 `TZ` 仅影响日志 |
| 卷类型 | 只支持本地块设备（ext4 / xfs / btrfs）。NFS / CIFS / 部分 CSI 卷上的文件锁不可靠，双实例互斥会静默失效 |

`/data` 布局（与桌面版一致，便于同一份数据在两种形态间迁移）：

```
/data/
  integration_data/
    scheduler.json         任务与时段
    runs/                  每次运行的记录与回执
    costs.sqlite3          费用账本（SQLite，含 WAL）
    resident_service/      服务锁、pid、心跳、检查点、备份
  works/<作品>/            正文与 .webnovel 状态
```

## 启动、停止、健康

```sh
# 前台启动（容器 entrypoint 也走这条命令）
python -B -X utf8 -m integration.resident_service start --interval 30

# 起一个轮询周期就退出（部署自检）
python -B -X utf8 -m integration.resident_service start --once

# 健康分项：进程 / 协调器心跳 / 配置 / 卷，不消耗模型额度
python -B -X utf8 -m integration.resident_service health

# 检查点与 pid
python -B -X utf8 -m integration.resident_service status
```

停止：`SIGTERM`（`docker stop`、`systemctl stop` 都是这个信号）。服务先停止认领新任务，
当前章写完后写检查点并退出；进程内有一个守护线程，收到信号后最多再等 25 秒就写
`state=stopping` 并强制退出（不等外部 `SIGKILL`）。强杀后按检查点与运行记录恢复：
启动时先补齐上次未完成的提交，跨时段重试上次 `running` / `failed` / `needs_revision`
的批次，只补缺步。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 正常停止（含 `--once` 自检） |
| 1 | 健康检查不通过（`health` 子命令：进程、心跳、配置、卷任一不满足） |
| 2 | 已有实例持有服务锁（不会重复写章） |
| 4 | 数据卷不可写或空间不足，拒绝启动 |
| 64 | 容器入口：`/data` 不存在 |
| 65 | 容器入口：`/data` 不可写 |

## 备份与还原

```sh
python -B -X utf8 -m integration.resident_service backup
python -B -X utf8 -m integration.resident_service backup --dest /data/integration_data/resident_service/backups/manual-1
python -B -X utf8 -m integration.resident_service restore --source <备份目录>          # 目标为空时才写
python -B -X utf8 -m integration.resident_service restore --source <备份目录> --force  # 明确覆盖
```

备份范围是白名单递归：`works/**`（正文与 `.webnovel` 回执/版本）、`integration_data/**`
（任务、runs、费用库）、`logs/**`；服务自身的锁/pid/心跳/检查点与旧备份不会被打包。
SQLite 走 `backup()` API 并先 `wal_checkpoint(TRUNCATE)`，因此包含 WAL 中尚未落盘的事务。
还原前必须停服：服务锁被持有就拒绝，目标卷与备份记录的根不一致也要显式
`--allow-root-mismatch` 才写；落盘用临时文件 + `os.replace`，并清掉同名的 `-wal/-shm`。

## 系统服务

```sh
sudo install -m 0644 chapter-whale.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start chapter-whale
journalctl -u chapter-whale -f
```

systemd 单元已经声明 `User=10001`、`StateDirectory=chapter-whale`、
`ReadOnlyPaths=/opt/chapter-whale /etc/chapter-whale`、`KillSignal=SIGTERM`、
`TimeoutStopSec=40`（进程内 25 秒兜底之后仍留余量）。若数据卷挂在其他路径，改
`ReadWritePaths` 与 `Environment=NOVEL_HELPER_ROOT=`。

## 容器

```sh
docker build -f deploy/linux/Dockerfile -t chapter-whale-service:0.7.0 .
docker run -d --name chapter-whale \
  -v /srv/chapter-whale:/data \
  -v /srv/chapter-whale-config:/config:ro \
  chapter-whale-service:0.7.0
```

`compose.yaml` 是同样的配置，带健康检查与 `stop_grace_period: 40s`。

## 已做与未做

已在代码与单测层面完成：能力盘点、单协调器（跨进程锁 + pid 指纹）、SIGTERM 停认领 →
写检查点 → 进程内 25 秒兜底退出、健康分项（探活不读模型配置、退出码随 `ok`）、只读卷/
空间不足/缺配置/坏配置/坏任务诊断、正文与回执的递归备份、还原取锁 + 原子落盘 + 清 WAL、
跨时段重试与启动补齐未完成提交。对应测试名见 `RELEASE_STATUS.md` 的验收表。

**未在真实 Linux amd64 实机或真实镜像上运行过**（本机为 Windows）：镜像摘要、空卷首次启动、
同卷重启只补缺步、双实例争抢、磁盘写满、卸载重装挂旧卷都只做了跨进程与替身级验证，
证据状态在 `RELEASE_STATUS.md` 与 `docs/plan/PROGRESS.md` 中如实标注为未验证。
