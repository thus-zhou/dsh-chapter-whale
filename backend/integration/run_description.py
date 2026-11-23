"""工作区级运行描述：谁在什么端口、用什么解释器持有管理服务。

运行描述只记录本机事实，供 watchdog、插件与管理服务互相识别启动实例，
不写入任何平台语义。任何字段冲突都必须让守护进程停止自动拉起并给出提示，
而不是杀掉进程或猜测端口。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import bridge

SCHEMA_VERSION = 1
RELATIVE = Path("integration_data") / "run-description.json"
MODES = ("dsh_managed", "standalone")
OWNERS = ("plugin", "watchdog", "manual")
DEFAULT_PORT = 8765
SERVICE_NAME = "novel-helper-manager"


def normalize_path(value):
    return os.path.normcase(os.path.abspath(str(value)))


def path(root_dir):
    return Path(root_dir).resolve() / RELATIVE


def valid_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def read(root_dir):
    target = path(root_dir)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return {}
    return value


def write(root_dir, **fields):
    current = read(root_dir)
    merged = {**current, **{key: value for key, value in fields.items() if value is not None}}
    merged["schema_version"] = SCHEMA_VERSION
    merged["updated_at"] = bridge.now_iso()
    bridge.write_json_atomic(path(root_dir), merged)
    return merged


def clear(root_dir):
    try:
        path(root_dir).unlink()
    except FileNotFoundError:
        return False
    return True


def describe(root_dir, *, mode, owner, port, health=None, python="", entry="", pid=None):
    """把当前观察结果收敛成一条描述；pid/startup_id 只能来自健康响应。"""
    health = health or {}
    return write(
        root_dir,
        mode=mode,
        owner=owner,
        port=valid_port(port),
        root=str(Path(root_dir).resolve()),
        python=str(python or ""),
        entry=str(entry or ""),
        pid=pid if isinstance(pid, int) else health.get("pid"),
        startup_id=health.get("startup_id"),
        release_id=health.get("release_id"),
        service=health.get("service"),
        started_at=health.get("started_at"),
    )


def compare(description, health, root, port):
    """比较描述与健康响应；返回 {ok, kind, message}，kind ∈ none/foreign/stale/conflict。"""
    health = health or {}
    service = health.get("service")
    if service and service != SERVICE_NAME:
        return {"ok": False, "kind": "foreign",
                "message": f"端口 {port} 上运行的不是码章鲸管理服务（{service}），保留现有进程"}
    observed_root = health.get("root")
    if observed_root and normalize_path(observed_root) != normalize_path(root):
        return {"ok": False, "kind": "foreign",
                "message": f"端口 {port} 上的管理服务属于其他工作区（{observed_root}），保留现有进程"}
    if not description:
        return {"ok": True, "kind": "none", "message": ""}
    described_port = valid_port(description.get("port"))
    if described_port and described_port != valid_port(port):
        return {"ok": False, "kind": "conflict",
                "message": f"运行描述记录端口 {described_port}，本次启动使用 {port}；已停止自动拉起，请统一配置后重试"}
    described_root = description.get("root")
    if described_root and normalize_path(described_root) != normalize_path(root):
        return {"ok": False, "kind": "conflict",
                "message": f"运行描述属于其他工作区（{described_root}），已停止自动拉起"}
    described_startup = description.get("startup_id")
    observed_startup = health.get("startup_id")
    if described_startup and observed_startup and described_startup != observed_startup:
        return {"ok": False, "kind": "stale",
                "message": "运行描述记录的启动实例已经退出，当前端口上是新的实例"}
    return {"ok": True, "kind": "none", "message": ""}


def matches(description, health, root, port):
    return compare(description, health, root, port)["ok"]
