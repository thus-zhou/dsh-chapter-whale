"""Linux amd64 常驻存稿服务：单协调器、检查点、健康分项与卷校验。

本模块只做「服务化」这一层：认领与写稿完全复用 scheduler/run_once，
不复制生成、审查、落稿逻辑。目标机是可独立运行的 Linux amd64，
不依赖 Windows DSH、浏览器或 OFM；首版关闭未验证渠道。
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import bridge, scheduler as s, writer_runner as writer

SCHEMA = 1
DEFAULT_INTERVAL = 30
DEFAULT_SHUTDOWN_SECONDS = 25
MIN_FREE_BYTES = 256 * 1024 * 1024
CHECKPOINT_NAME = "checkpoint.json"
HEARTBEAT_NAME = "heartbeat.json"
PID_NAME = "service.pid"
LOCK_NAME = "service.lock"
BACKUP_DIR = "backups"

# 每一项都必须在代码里落实，不能只写在文档里。
INVENTORY: List[Dict[str, str]] = [
    {"item": "python", "status": "supported", "note": "目标解释器 3.11+，仓库不携带便携运行时"},
    {"item": "lock", "status": "supported", "note": "POSIX fcntl 咨询锁，进程退出即释放"},
    {"item": "atomic_replace", "status": "supported", "note": "os.replace 同卷原子替换，写入后 fsync"},
    {"item": "case_sensitive", "status": "supported", "note": "路径比较使用 resolve 后的大小写敏感值"},
    {"item": "signal", "status": "supported", "note": "SIGTERM/SIGINT 停认领，当前章结束后写检查点退出"},
    {"item": "timezone", "status": "supported", "note": "任务时区来自 zoneinfo，缺少 tzdata 时显式回退并标记"},
    {"item": "credential", "status": "replaced", "note": "DPAPI 密文不迁移，目标机重新配置密钥"},
    {"item": "browser", "status": "disabled", "note": "首版不装 Chromium，不开放浏览器发表"},
    {"item": "free_service", "status": "disabled", "note": "免费池策略不因平台变化而改变，首版不启用"},
    {"item": "dsh_bridge", "status": "disabled", "note": "不依赖 Windows DSH 宿主模型，远程管理仅本机"},
    {"item": "ofm", "status": "disabled", "note": "未验证的 OFM 运行时在首版关闭"},
]

_STOP: Dict[str, bool] = {"requested": False, "signal": ""}


def service_dir(root: Optional[Path] = None) -> Path:
    base = Path(root) if root else bridge.COMBINED_ROOT
    return base / "integration_data" / "resident_service"


def service_paths(root: Optional[Path] = None) -> Dict[str, Path]:
    folder = service_dir(root)
    return {
        "dir": folder,
        "lock": folder / LOCK_NAME,
        "pid": folder / PID_NAME,
        "heartbeat": folder / HEARTBEAT_NAME,
        "checkpoint": folder / CHECKPOINT_NAME,
        "backups": folder / BACKUP_DIR,
    }


def inventory() -> List[Dict[str, str]]:
    """能力盘点（E01.1）：支持/替换/关闭三态，供部署核对。"""
    return [dict(row) for row in INVENTORY]


def service_now(tz_name: str = "Asia/Shanghai") -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name or "Asia/Shanghai"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=8)))


def free_bytes(path: Path) -> int:
    try:
        return int(shutil.disk_usage(str(path)).free)
    except OSError:
        return -1


def volume_report(root: Optional[Path] = None, *, min_free: int = MIN_FREE_BYTES) -> Dict[str, Any]:
    """卷可用性：可写、只读、剩余空间。只读卷必须显式诊断，不能空库开调度。"""
    base = Path(root) if root else bridge.COMBINED_ROOT
    report: Dict[str, Any] = {"path": str(base), "ok": False, "status": "unknown", "reason": ""}
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report.update(status="missing", reason=f"数据目录不可创建：{exc}")
        return report
    probe = base / ".resident-write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as exc:
        status = "read_only" if getattr(exc, "errno", None) not in (28, 122) else "low_space"
        reason = ("数据卷只读：" if status == "read_only" else "磁盘已满，无法写入：") + str(exc)
        report.update(status=status, reason=reason)
        return report
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    free = free_bytes(base)
    report["free_bytes"] = free
    if free < 0:
        report.update(status="unknown", reason="无法读取剩余空间")
        return report
    if free < min_free:
        report.update(status="low_space", reason=f"剩余空间不足：{free} 字节，低于 {min_free}")
        return report
    report.update(ok=True, status="ok")
    return report


def config_report(root: Optional[Path] = None) -> Dict[str, Any]:
    """配置可用性：ready/empty/broken。empty 与 broken 都不认领任务。"""
    if root is None:
        path = Path(s.SCHEDULER_PATH)
        base = bridge.COMBINED_ROOT
    else:
        base = Path(root)
        path = base / "integration_data" / "scheduler.json"
    if not Path(path).exists():
        return {"ok": False, "status": "empty", "path": str(path), "jobs": 0,
                "reason": "尚未初始化任务配置：先建任务再开调度"}
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "status": "broken", "path": str(path), "jobs": 0,
                "reason": f"任务配置损坏：{exc}"}
    jobs = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(jobs, dict):
        return {"ok": False, "status": "broken", "path": str(path), "jobs": 0,
                "reason": "任务配置缺少 jobs 字典"}
    # 配置自检要够深：否则坏任务会一路走到认领阶段才失败，然后卡在重试边界上。
    version = document.get("version")
    if version != 2:
        return {"ok": False, "status": "broken", "path": str(path), "jobs": len(jobs),
                "reason": f"任务配置版本不受支持：{version!r}（需要 2）"}
    settings = document.get("settings")
    if not isinstance(settings, dict) or settings.get("auto_schedule") is not True:
        return {"ok": False, "status": "broken", "path": str(path), "jobs": len(jobs),
                "reason": "调度总开关未打开：服务会一直空转，先在界面开启自动调度"}
    if not jobs:
        return {"ok": False, "status": "empty", "path": str(path), "jobs": 0,
                "reason": "还没有任务：先建任务再开调度"}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            return {"ok": False, "status": "broken", "path": str(path), "jobs": len(jobs),
                    "reason": f"任务 {job_id} 不是对象"}
        for field in ("name", "project", "daily_time"):
            if not str(job.get(field) or "").strip():
                return {"ok": False, "status": "broken", "path": str(path), "jobs": len(jobs),
                        "reason": f"任务 {job_id} 缺少 {field}"}
        project = Path(str(job.get("project")))
        if not project.is_dir():
            return {"ok": False, "status": "broken", "path": str(path), "jobs": len(jobs),
                    "reason": f"任务 {job_id} 的作品目录不存在：{project}"}
    return {"ok": True, "status": "ready", "path": str(path), "jobs": len(jobs), "reason": ""}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(root: Optional[Path] = None) -> int:
    path = service_paths(root)["pid"]
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


class SingletonBusy(RuntimeError):
    """已有实例持有服务锁。"""


class Service:
    """单协调器：OS 锁 + pid 指纹，双实例不重复写章。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else bridge.COMBINED_ROOT
        self.paths = service_paths(self.root)
        self.paths["dir"].mkdir(parents=True, exist_ok=True)
        self._lock = None
        self.pid = os.getpid()

    def acquire(self) -> "Service":
        try:
            self._lock = writer.file_lock(self.paths["lock"], blocking=False)
            self._lock.__enter__()
        except RuntimeError as exc:
            raise SingletonBusy(f"已有常驻实例持有服务锁：{self.paths['lock']}") from exc
        self.paths["pid"].write_text(str(self.pid), encoding="utf-8")
        return self

    def release(self) -> None:
        try:
            if read_pid(self.root) == self.pid and self.paths["pid"].exists():
                self.paths["pid"].unlink()
        except OSError:
            pass
        if self._lock is not None:
            try:
                self._lock.__exit__(None, None, None)
            except Exception:
                pass
            self._lock = None

    def __enter__(self) -> "Service":
        return self.acquire()

    def __exit__(self, *exc: Any) -> None:
        self.release()


def health(root: Optional[Path] = None, *, interval: float = DEFAULT_INTERVAL,
           max_age: Optional[int] = None) -> Dict[str, Any]:
    """健康分项：进程、协调器心跳、配置、卷。探活不调用模型。

    `ok` 由四项合成，`reasons` 说明为什么不算健康——只输出字段而不判定，
    HEALTHCHECK 就等于永远 healthy。
    """
    paths = service_paths(root)
    pid = read_pid(root)
    alive = _pid_alive(pid)
    heartbeat = bridge.read_json(paths["heartbeat"], {}) or {}
    beat_at = heartbeat.get("at") or ""
    age = None
    if beat_at:
        try:
            age = int((datetime.now(timezone.utc) - datetime.fromisoformat(beat_at)).total_seconds())
        except (TypeError, ValueError):
            age = None
    config = config_report(root)
    volume = volume_report(root)
    limit = int(max_age if max_age is not None else max(90, float(interval) * 3))
    reasons = []
    if not alive:
        reasons.append("process_not_running")
    if age is None:
        reasons.append("no_heartbeat")
    elif age > limit:
        reasons.append(f"heartbeat_stale:{age}s>{limit}s")
    if not config["ok"]:
        reasons.append(f"config_{config['status']}")
    if not volume["ok"]:
        reasons.append(f"volume_{volume['status']}")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "process": {"pid": pid, "alive": alive,
                    "schema": SCHEMA, "shutdown_requested": bool(_STOP["requested"])},
        "coordinator": {"heartbeat_at": beat_at, "age_seconds": age,
                        "state": heartbeat.get("state") or "unknown",
                        "job_id": heartbeat.get("job_id") or "",
                        "degraded": heartbeat.get("degraded") or ""},
        "config": config,
        "volume": volume,
    }


def write_checkpoint(root: Optional[Path] = None, value: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    paths = service_paths(root)
    payload = {"schema": SCHEMA, "at": bridge.now_iso(), **(value or {})}
    bridge.write_json_atomic(paths["checkpoint"], payload)
    return payload


def read_checkpoint(root: Optional[Path] = None) -> Dict[str, Any]:
    value = bridge.read_json(service_paths(root)["checkpoint"], {}) or {}
    return value if isinstance(value, dict) else {}


def write_heartbeat(root: Optional[Path] = None, **value: Any) -> None:
    paths = service_paths(root)
    bridge.write_json_atomic(paths["heartbeat"], {"schema": SCHEMA, "at": bridge.now_iso(), **value})


def request_stop(signum: int = 0, frame: Any = None) -> None:
    _STOP["requested"] = True
    _STOP["signal"] = str(signum or "")


def _start_stop_watchdog(root: Optional[Path], seconds: float) -> None:
    """收到信号后限时退出：单个任务卡住时由守护线程兜底。

    主循环只在任务边界检查信号，一次生成可能远超 25 秒；没有这条兜底，
    「限时退出」就只是文档里的一句话（systemd 到点会 SIGKILL）。
    """
    import threading

    def watch() -> None:
        while not _STOP["requested"]:
            time.sleep(0.2)
        deadline = time.monotonic() + max(1.0, float(seconds))
        while time.monotonic() < deadline:
            time.sleep(0.2)
        _safe(write_checkpoint, root, {"state": "stopping", "reason": "shutdown_timeout",
                                      "signal": _STOP["signal"]})
        sys.stderr.write("resident_service: 已停认领，但当前任务超过限时，强制退出\n")
        sys.stderr.flush()
        # 退出码 1：任务超时是异常终止，launchd（KeepAlive.SuccessfulExit=false）
        # 与 systemd（Restart=on-failure）都应该重启；用 0 会被当成正常退出而不重启。
        os._exit(1)

    threading.Thread(target=watch, name="shutdown-watchdog", daemon=True).start()


def install_signal_handlers() -> None:
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, request_stop)
        except (ValueError, OSError):
            continue


def _safe(call: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """状态写入不许把服务打死：只读卷或磁盘满时降级为 stderr 诊断。

    返回错误文本（空串表示成功）。调用方据此把 degraded 写进内存态，
    而不是让 PermissionError/ENOSPC 直接冒到进程外——那会变成 exit 1，
    运维脚本就分不清「卷坏了」和「代码崩了」。
    """
    try:
        call(*args, **kwargs)
        return ""
    except OSError as error:
        sys.stderr.write(f"resident_service: 状态写入失败：{error}\n")
        sys.stderr.flush()
        return str(error)


def run(
    root: Optional[Path] = None,
    *,
    interval: float = DEFAULT_INTERVAL,
    once: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    shutdown_seconds: int = DEFAULT_SHUTDOWN_SECONDS,
    max_cycles: int = 0,
    force_exit: bool = True,
) -> int:
    """常驻主循环：停认领 → 当前章结束 → 写检查点 → 限时退出。

    返回 0 正常；2 已有实例；3 配置不可调度；4 卷不可写。
    """
    base = Path(root) if root else bridge.COMBINED_ROOT
    # --root 必须同时管住调度读写，否则配置读的是新卷、任务却从进程默认路径来。
    original = (s.SCHEDULER_PATH, s.RUNS_ROOT)
    if root is not None:
        s.SCHEDULER_PATH = base / "integration_data" / "scheduler.json"
        s.RUNS_ROOT = base / "integration_data" / "runs"
    volume = volume_report(base)
    if not volume["ok"]:
        _safe(write_checkpoint, base, {"state": "refused", "reason": volume["status"],
                                       "detail": volume.get("reason", "")})
        if root is not None:
            s.SCHEDULER_PATH, s.RUNS_ROOT = original
        return 4
    service = Service(base)
    try:
        service.acquire()
    except SingletonBusy as exc:
        # 不覆盖正在工作那个实例的检查点，只留一行诊断。
        sys.stderr.write(f"resident_service: 已有实例在跑：{exc}\n")
        sys.stderr.flush()
        if root is not None:
            s.SCHEDULER_PATH, s.RUNS_ROOT = original
        return 2
    cycles = 0
    counts = {"claimed": 0, "skipped": 0, "failed": 0, "blocked": 0}
    state = "idle"
    degraded = ""
    if force_exit and not once:
        _start_stop_watchdog(base, shutdown_seconds)
    try:
        # 上次被强杀留下的 running/failed 批次：先补齐提交，再交给 due_jobs 重试。
        recovered = _recover_pending(base)
        while not _STOP["requested"]:
            config = config_report(base)
            volume = volume_report(base)
            degraded = "" if config["ok"] and volume["ok"] else (
                config["status"] if not config["ok"] else volume["status"])
            _safe(write_heartbeat, base, state=state, degraded=degraded)
            if degraded:
                error = _safe(write_checkpoint, base, {
                    "state": "degraded", "reason": config["reason"] or volume["reason"],
                    "cycles": cycles, **counts, "recovered": recovered})
                state = "degraded"
                if once or (max_cycles and cycles + 1 >= max_cycles):
                    return 0
                cycles += 1
                if not error:
                    _wait(max(1.0, float(interval)))
                continue
            state = "polling"
            try:
                due = s.due_jobs()
            except Exception as exc:  # 单坏任务不能拖垮整个服务
                _safe(write_heartbeat, base, state="poll_error", degraded=str(exc))
                due = []
            for summary in due:
                if _STOP["requested"]:
                    break
                job_id = summary["id"] if isinstance(summary, dict) else str(summary)
                _safe(write_heartbeat, base, state="running", job_id=job_id)
                try:
                    result = s.run_once(job_id)
                    counts[_outcome(result)] += 1
                except Exception as exc:
                    counts["failed"] += 1
                    _safe(write_heartbeat, base, state="job_failed", job_id=job_id, degraded=str(exc))
            state = "idle"
            _safe(write_checkpoint, base, {"state": "running", "cycles": cycles + 1,
                                           **counts, "last_poll_at": clock().isoformat(),
                                           "recovered": recovered})
            cycles += 1
            if once or (max_cycles and cycles >= max_cycles):
                break
            if _STOP["requested"]:
                break
            _wait(max(1.0, float(interval)))
        state = "stopped"
        _safe(write_checkpoint, base, {"state": "stopped", "cycles": cycles, **counts,
                                       "signal": _STOP["signal"],
                                       "shutdown_seconds": shutdown_seconds,
                                       "recovered": recovered})
        return 0
    finally:
        service.release()
        if root is not None:
            s.SCHEDULER_PATH, s.RUNS_ROOT = original


def _wait(seconds: float) -> None:
    """分片等待：信号到来后最多再等一片，不会被 PEP475 睡满整段。"""
    remaining = max(0.0, float(seconds))
    while remaining > 0 and not _STOP["requested"]:
        step = min(0.2, remaining)
        time.sleep(step)
        remaining -= step


def _outcome(result: Any) -> str:
    status = ""
    if isinstance(result, dict):
        status = str(result.get("status") or "")
    if status == "success":
        return "claimed"
    if status in {"already_ran", "busy", "skipped", "stopped"}:
        return "skipped"
    if status == "blocked":
        return "blocked"
    return "failed"


def _recover_pending(base: Path) -> int:
    """把上次强杀留下的未完成提交补齐；坏项目只诊断，不阻断服务。"""
    from . import chapter_versions, scheduler

    fixed = 0
    try:
        data = scheduler.load_scheduler()
    except (ValueError, OSError) as error:
        sys.stderr.write(f"resident_service: 读调度失败，跳过提交恢复：{error}\n")
        return 0
    for job in (data.get("jobs") or {}).values():
        if not isinstance(job, dict) or not job.get("project"):
            continue
        try:
            fixed += len(chapter_versions.recover_pending(Path(job["project"])))
        except (ValueError, OSError, RuntimeError) as error:
            sys.stderr.write(f"resident_service: 恢复提交失败（{job.get('project')}）：{error}\n")
    return fixed


BACKUP_TREES = ("works", "integration_data", "logs")


def _sqlite_files(root: Path) -> Iterable[Path]:
    skip = service_paths(root)["backups"].resolve()
    for pattern in ("*.sqlite3", "*.sqlite"):
        for path in sorted(root.rglob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if skip == resolved or skip in resolved.parents:
                continue
            yield path


def _backup_tree(base: Path) -> Iterable[Path]:
    """备份范围：正文、版本/回执、运行记录、日志；不含服务自身状态与旧备份。"""
    skip = service_dir(base).resolve()
    for name in BACKUP_TREES:
        folder = base / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if skip == resolved or skip in resolved.parents:
                continue
            if path.suffix in {".sqlite3", ".sqlite"} or path.name.endswith(("-wal", "-shm")):
                continue  # SQLite 走 backup API，避免拷到半写状态
            yield path


def backup(root: Optional[Path] = None, dest: Optional[Path] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """一致性备份：SQLite 用 backup API，正文/回执/运行记录按白名单递归复制。"""
    base = Path(root) if root else bridge.COMBINED_ROOT
    if not dest:
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        target = service_paths(base)["backups"] / f"backup-{stamp}"
    else:
        target = Path(dest)
    target.mkdir(parents=True, exist_ok=True)
    manifest_files: List[Dict[str, Any]] = []
    for db_path in _sqlite_files(base):
        relative = db_path.relative_to(base)
        out = target / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(db_path))
        try:
            clone = sqlite3.connect(str(out))
            try:
                source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                source.backup(clone)
            finally:
                clone.close()
        finally:
            source.close()
        manifest_files.append({"path": str(relative), "kind": "sqlite",
                               "sha256": _file_sha(out), "bytes": out.stat().st_size})
    for item in _backup_tree(base):
        relative = item.relative_to(base)
        out = target / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        data = item.read_bytes()
        out.write_bytes(data)
        manifest_files.append({"path": str(relative), "kind": "copy",
                               "sha256": _digest(data), "bytes": len(data)})
    manifest = {"schema": SCHEMA, "created_at": bridge.now_iso(), "files": len(manifest_files),
                "root": str(base), "dest": str(target), "contents": manifest_files}
    bridge.write_json_atomic(target / "backup.json", manifest)
    return manifest


def _digest(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _digest(path.read_bytes())


def restore(root: Optional[Path] = None, source: Optional[Path] = None, *,
            force: bool = False, allow_root_mismatch: bool = False) -> Dict[str, Any]:
    """还原：先拿服务锁，原子落盘，清掉旧 WAL，再核对 root。"""
    base = Path(root) if root else bridge.COMBINED_ROOT
    if not source:
        candidates = sorted(service_paths(base)["backups"].glob("backup-*"))
        if not candidates:
            raise ValueError("没有可用的备份目录")
        source = candidates[-1]
    source = Path(source)
    manifest_path = source / "backup.json"
    if not manifest_path.exists():
        raise ValueError(f"备份缺少 backup.json：{source}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = str(manifest.get("root") or "")
    if recorded and not allow_root_mismatch:
        try:
            same = Path(recorded).resolve() == base.resolve()
        except OSError:
            same = False
        if not same:
            raise ValueError(f"备份来自另一个卷：{recorded}；确认要还原请显式允许换卷")
    # 服务锁比 pid 可靠：持锁说明真有实例在工作（容器里 pid 1 在宿主看不见）。
    try:
        with writer.file_lock(service_paths(base)["lock"], blocking=False):
            restored = _restore_into(base, source, force)
    except ValueError:
        raise
    except (RuntimeError, OSError) as error:
        raise ValueError(f"服务仍在运行：先停止再还原（{error}）") from None
    return {"schema": SCHEMA, "restored": restored, "source": str(source),
            "created_at": manifest.get("created_at", ""), "forced": bool(force)}


def _restore_into(base: Path, source: Path, force: bool) -> int:
    restored = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name == "backup.json":
            continue
        relative = path.relative_to(source)
        out = base / relative
        if out.exists() and not force:
            raise ValueError(f"目标已有同名文件，拒绝覆盖：{relative}")
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.name + ".restore.tmp")
        temp.write_bytes(path.read_bytes())
        os.replace(temp, out)
        if out.suffix in {".sqlite3", ".sqlite"}:
            for suffix in ("-wal", "-shm"):
                sidecar = out.with_name(out.name + suffix)
                if sidecar.exists():
                    sidecar.unlink()
        restored += 1
    return restored


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="码章鲸常驻存稿服务（Linux/macOS amd64/arm64）")
    parser.add_argument("command", choices=["start", "health", "inventory", "status",
                                            "backup", "restore", "checkpoint", "platform"])
    parser.add_argument("--root", default="")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--dest", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-root-mismatch", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else None
    if args.command == "start":
        install_signal_handlers()
        return run(root, interval=args.interval, once=args.once, max_cycles=args.max_cycles)
    if args.command == "health":
        report = health(root, interval=args.interval)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["ok"]:
            return 0
        sys.stderr.write("resident_service: 不健康：" + ",".join(report["reasons"]) + "\n")
        return 1
    if args.command == "inventory":
        print(json.dumps(inventory(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "platform":
        from . import platform_support
        print(json.dumps(platform_support.matrix(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps({"pid": read_pid(root), "checkpoint": read_checkpoint(root)},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "checkpoint":
        print(json.dumps(read_checkpoint(root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "backup":
        print(json.dumps(backup(root, Path(args.dest) if args.dest else None),
                         ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(restore(root, Path(args.source) if args.source else None, force=args.force,
                             allow_root_mismatch=bool(args.allow_root_mismatch)),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
