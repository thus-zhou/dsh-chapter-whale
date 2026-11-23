"""Windows 计划任务入口：恢复本机服务并核对启动实例身份。

两种模式必须分清启动所有者：
- dsh_managed：管理服务由 DSH 插件启动并持有；watchdog 只核对健康、恢复逐章协调器，
  绝不另起第二个管理器。
- standalone：没有宿主时由 watchdog 按解释器 + manager/app.py CLI 启动管理服务，
  端口取自工作区运行描述（或显式覆盖），只探测 127.0.0.1 的单个端口。

本模块不做任何平台写入。端口被别的进程占用时保留现状并报告冲突。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from . import bridge, run_description, writer_runner
from .serial_service import ensure_started, LOCK as SERIAL_LOCK, STATE as SERIAL_STATE

ROOT = Path(__file__).resolve().parents[1]
MANAGER_ENTRY = ROOT / "manager" / "app.py"
HEALTH_TIMEOUT = 3
START_TIMEOUT = 90
MODE_ENV = "CHAPTER_WHALE_SERVICE_MODE"


def state_path():
    """守护状态写在工作区数据目录，绝不落在后台源码树里。"""
    return Path(bridge.COMBINED_ROOT) / "integration_data" / "serial_service" / "watchdog.json"


def service_mode(description=None):
    override = os.environ.get(MODE_ENV, "").strip()
    if override in run_description.MODES:
        return override
    mode = (description or {}).get("mode")
    return mode if mode in run_description.MODES else "standalone"


def service_port(root=None, description=None):
    """端口只有一个来源：运行描述；没有描述时退回默认 8765。"""
    described = run_description.valid_port((description or {}).get("port"))
    if described:
        return described
    return run_description.DEFAULT_PORT


def manager_health(port):
    """读取健康响应；连接失败返回 None，错误服务返回其响应体。"""
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=HEALTH_TIMEOUT) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def manager_ready(port):
    health = manager_health(port)
    return bool(health) and health.get("service") == run_description.SERVICE_NAME


def port_in_use(port):
    port = run_description.valid_port(port)
    if not port:
        return False
    with socket.socket() as probe:
        probe.settimeout(2)
        try:
            return probe.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def service_python(root, description=None):
    """独立模式解释器：环境变量 → 运行描述 → 工作区 .venv → 当前解释器。

    每一层都要求文件确实存在；不依赖盘符或 PATH 偶然命中。
    """
    candidates = [os.environ.get("CHAPTER_WHALE_PYTHON", ""), (description or {}).get("python", ""),
                  str(Path(root) / ".venv" / "Scripts" / "python.exe"), sys.executable]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and Path(value).is_file():
            return value
    return ""


def start_manager(root, port, python=""):
    python = python or service_python(root)
    if not python:
        raise RuntimeError("找不到可执行解释器，无法启动管理服务；请重新安装完整发行包或在运行描述里指定 python")
    if not MANAGER_ENTRY.is_file():
        raise RuntimeError(f"发行包缺少管理服务入口：{MANAGER_ENTRY}")
    log_dir = Path(root) / "integration_data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = open(log_dir / f"{stamp}.manager.out.log", "ab")
    err = open(log_dir / f"{stamp}.manager.err.log", "ab")
    try:
        child = subprocess.Popen(
            [python, "-X", "utf8", "-u", str(MANAGER_ENTRY), "--port", str(port)],
            cwd=str(root), stdout=out, stderr=err, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        out.close()
        err.close()
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if manager_ready(port):
            return {"pid": child.pid, "port": port, "python": python}
        if child.poll() is not None:
            raise RuntimeError(f"管理服务启动后立即退出（退出码 {child.returncode}），请检查 {log_dir} 下的日志")
        time.sleep(.5)
    raise RuntimeError("管理服务启动后未通过健康检查，请看 integration_data/logs 下的日志")


def serial_ready():
    try:
        with writer_runner.file_lock(SERIAL_LOCK):
            return False
    except RuntimeError as exc:
        if "已有任务正在运行" not in str(exc) and "resource_busy" not in str(exc):
            raise
    value = bridge.read_json(SERIAL_STATE, {})
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(value["checked_at"])).total_seconds()
        return 0 <= age < 60 and value.get("status") in {"running", "waiting_for_existing_worker"}
    except (KeyError, TypeError, ValueError):
        return False


def _write_state(**fields):
    payload = {"checked_at": bridge.now_iso(), **fields}
    bridge.write_json_atomic(state_path(), payload)
    return payload


def check(root=None, port=None, mode=None):
    root = Path(root or bridge.COMBINED_ROOT).resolve()
    description = run_description.read(root)
    port = run_description.valid_port(port) or service_port(root, description)
    mode = mode or service_mode(description)

    with writer_runner.file_lock(bridge.RUNTIME_ROOT / "watchdog.lock"):
        health = manager_health(port)
        verdict = run_description.compare(description, health, root, port)
        if verdict["kind"] in {"foreign", "conflict"}:
            _write_state(status="error", reason=verdict["kind"], message=verdict["message"],
                         port=port, mode=mode, service={})
            raise RuntimeError(verdict["message"])
        healthy = bool(health) and health.get("service") == run_description.SERVICE_NAME
        started = None
        if not healthy:
            if port_in_use(port):
                message = f"{port} 端口已有服务但健康检查未通过；保留现有进程，未盲目改端口"
                _write_state(status="error", reason="port_conflict", message=message,
                             port=port, mode=mode, service={})
                raise RuntimeError(message)
            if mode == "dsh_managed":
                message = "DSH 托管模式下管理服务应由插件启动；守护进程不另起第二个管理器"
                return _write_state(status="waiting_for_host", reason="host_owned_manager",
                                    message=message, port=port, mode=mode, service={})
            started = start_manager(root, port, service_python(root, description))

        health = manager_health(port) or {}
        description = run_description.describe(
            root, mode=mode, owner="plugin" if mode == "dsh_managed" else "watchdog",
            port=port, health=health, python=service_python(root, description),
            entry=str(MANAGER_ENTRY),
        )

        result = ensure_started()
        recovered = False
        if not serial_ready():
            from .owned_service import restart_stale_coordinator

            if restart_stale_coordinator(ROOT, SERIAL_STATE):
                result = ensure_started()
                recovered = True
        deadline = time.monotonic() + 20
        while not serial_ready():
            if time.monotonic() >= deadline:
                raise RuntimeError("逐章执行器未提供有效心跳，请检查服务日志")
            time.sleep(.5)
        return _write_state(
            status="healthy", reason="", port=port, mode=mode, manager_started=started,
            manager_restarted=bool(started), recovered_owned_idle_service=recovered,
            manager={"pid": health.get("pid"), "startup_id": health.get("startup_id"),
                     "release_id": health.get("release_id"), "service": health.get("service")},
            serial_service=result, run_description=description,
        )


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="码章鲸本机服务守护")
    parser.add_argument("--root", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--mode", choices=run_description.MODES, default="")
    parser.add_argument("--check", action="store_true", help="只核对，不改变任何状态")
    args = parser.parse_args(argv)
    if args.check:
        root = Path(args.root).resolve() if args.root else Path(bridge.COMBINED_ROOT).resolve()
        description = run_description.read(root)
        port = run_description.valid_port(args.port) or service_port(root, description)
        health = manager_health(port)
        verdict = run_description.compare(description, health, root, port)
        print(json.dumps({"ok": verdict["ok"], "kind": verdict["kind"],
                          "message": verdict["message"], "port": port,
                          "description": description, "health": health}, ensure_ascii=False))
        return 0 if verdict["ok"] else 1
    check(root=args.root or None, port=args.port or None, mode=args.mode or None)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        from .serial_delivery import safe_message

        bridge.write_json_atomic(state_path(), {"checked_at": bridge.now_iso(), "status": "error",
                                                  "message": safe_message(exc)})
        raise SystemExit(1)
    raise SystemExit(code)
