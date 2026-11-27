"""两层并发引擎（v0.9 三期）。

P0 快道永远先于 P1 自动日更与 P2 批量；P2 最多占用 ``max_slots - 1`` 个槽，
给作者手动操作保留至少一个空位。暂停分三级：全局 / 项目 / 任务，子任务
继承父任务的暂停与改令挂起。租约到期且处于 ``committing`` 的任务不会被
静默重跑，而是进入 ``recovery_required`` 等对账。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from integration import workbench_db as wb

PRIORITIES = ("P0", "P1", "P2")
MAX_PENDING_FRAMES = 256
LEASE_SECONDS = 30.0
_GLOBAL_PAUSE_PATH: Optional[Path] = None


class SchedulerError(RuntimeError):
    def __init__(self, code: str, *, status: int = 409, detail: Optional[Dict] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def _now() -> float:
    return time.time()


def _row(row) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["blocked_by"] = json.loads(item.pop("blocked_by_json") or "[]")
    except ValueError:
        item["blocked_by"] = []
    try:
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
    except ValueError:
        item["payload"] = {}
    item["committing"] = bool(item.get("committing"))
    return item


def _event(project, task_id: Optional[str], kind: str, detail: Optional[Dict] = None) -> None:
    with wb.write_tx(project) as db:
        db.execute("INSERT INTO task_events(task_id, kind, detail_json, created_at) VALUES(?,?,?,?)",
                   (task_id, kind, json.dumps(detail or {}, ensure_ascii=False),
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))


def submit(project, payload: Dict[str, Any], *, priority: str = "P2",
           chapter_id: Optional[int] = None, task_id: Optional[str] = None,
           parent_task_id: Optional[str] = None, blocked_by: Iterable[str] = (),
           amendment_fallback: str = "wait") -> Dict[str, Any]:
    if priority not in PRIORITIES:
        raise SchedulerError("invalid_priority", status=400)
    if amendment_fallback not in {"wait", "continue"}:
        raise SchedulerError("invalid_amendment_fallback", status=400)
    wb.initialize(project)
    tid = str(task_id or wb.new_id("task"))
    now = _now()
    state = "pending"
    hold = None
    if parent_task_id:
        parent = get(project, parent_task_id)
        if parent.get("hold_amendment_id") and amendment_fallback == "wait":
            state = "held"
            hold = parent["hold_amendment_id"]
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with wb.write_tx(project) as db:
        db.execute(
            "INSERT INTO task_queue(task_id, chapter_id, priority, state, parent_task_id, "
            "blocked_by_json, hold_amendment_id, amendment_fallback, committing, attempts, "
            "payload_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,0,0,?,?,?)",
            (tid, chapter_id, priority, state, parent_task_id,
             json.dumps(list(blocked_by), ensure_ascii=False), hold, amendment_fallback,
             json.dumps(payload or {}, ensure_ascii=False), stamp, stamp),
        )
    _event(project, tid, "submitted", {"priority": priority})
    return get(project, tid)


def _ensure_queue(project) -> None:
    if not wb.db_path(project).exists():
        wb.initialize(project)
        return
    with wb.connect(project) as db:
        row = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_queue'").fetchone()
    if not row:
        wb.initialize(project)


def get(project, task_id: str) -> Dict[str, Any]:
    _ensure_queue(project)
    with wb.connect(project) as db:
        row = db.execute("SELECT * FROM task_queue WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        raise SchedulerError("task_missing", status=404)
    return _row(row)


def list_tasks(project, *, state: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_queue(project)
    query = "SELECT * FROM task_queue" + (" WHERE state=?" if state else "") + \
            " ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, created_at"
    with wb.connect(project) as db:
        rows = db.execute(query, ((state,) if state else ())).fetchall()
    return [_row(row) for row in rows]


def _paused(project, scope: str) -> bool:
    with wb.connect(project) as db:
        return db.execute("SELECT 1 FROM task_pauses WHERE scope=?", (scope,)).fetchone() is not None


def configure_global_pause(path) -> None:
    global _GLOBAL_PAUSE_PATH
    _GLOBAL_PAUSE_PATH = Path(path)


def _global_pause_path() -> Optional[Path]:
    if _GLOBAL_PAUSE_PATH is not None:
        return _GLOBAL_PAUSE_PATH
    value = os.getenv("NOVEL_HELPER_GLOBAL_PAUSE")
    return Path(value) if value else None


def global_paused() -> bool:
    path = _global_pause_path()
    if path is None or not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("paused"))
    except Exception:
        return False


def set_global_pause(paused: bool, reason: str = "") -> Dict[str, Any]:
    path = _global_pause_path()
    if path is None:
        raise SchedulerError("global_pause_path_missing", status=500)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"paused": bool(paused), "reason": str(reason or ""),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return {"status": "paused" if paused else "resumed", "scope": "global", **data}


def _task_paused(project, item: Dict[str, Any]) -> bool:
    if global_paused():
        return True
    if _paused(project, "global") or _paused(project, "project:" + str(Path(project).resolve())):
        return True
    task_id = item["task_id"]
    while task_id:
        if _paused(project, "task:" + task_id):
            return True
        parent = item.get("parent_task_id")
        if not parent:
            break
        try:
            item = get(project, parent)
        except SchedulerError:
            break
        task_id = item["task_id"]
    return False


def pause(project, scope: str, reason: str = "") -> Dict[str, Any]:
    if not (scope == "global" or scope.startswith(("project:", "task:"))):
        raise SchedulerError("invalid_pause_scope", status=400)
    wb.initialize(project)
    with wb.write_tx(project) as db:
        db.execute("INSERT OR REPLACE INTO task_pauses(scope, reason, created_at) VALUES(?,?,?)",
                   (scope, reason, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    _event(project, None, "paused", {"scope": scope, "reason": reason})
    return {"status": "paused", "scope": scope}


def resume(project, scope: str) -> Dict[str, Any]:
    wb.initialize(project)
    with wb.write_tx(project) as db:
        db.execute("DELETE FROM task_pauses WHERE scope=?", (scope,))
        if scope.startswith("task:"):
            db.execute("UPDATE task_queue SET state='pending', updated_at=? WHERE task_id=? "
                       "AND state='paused'", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                             scope.split(":", 1)[1]))
    _event(project, None, "resumed", {"scope": scope})
    return {"status": "resumed", "scope": scope}


def paused_scopes(project) -> List[Dict[str, Any]]:
    _ensure_queue(project)
    with wb.connect(project) as db:
        rows = db.execute("SELECT * FROM task_pauses ORDER BY scope").fetchall()
    return [dict(row) for row in rows]


def _ready(project, item: Dict[str, Any]) -> bool:
    if item["state"] != "pending":
        return False
    for blocker in item.get("blocked_by") or []:
        try:
            other = get(project, blocker)
        except SchedulerError:
            return False
        if other["state"] not in {"completed", "cancelled"}:
            return False
    return not _task_paused(project, item)


def claim(project, owner: str, *, max_slots: int = 4, lease_seconds: float = LEASE_SECONDS) -> Optional[Dict[str, Any]]:
    """Lease one ready task; returns None when the pool is full or idle."""
    wb.initialize(project)
    # 每次派发前回收过期租约；无需依赖作者手动调用 /tasks/recover。
    recover(project)
    max_slots = max(1, int(max_slots))
    with wb.write_tx(project) as db:
        running = [dict(row) for row in db.execute(
            "SELECT * FROM task_queue WHERE state='running'")]
        if len(running) >= max_slots:
            return None
        p2_running = sum(1 for row in running if row["priority"] == "P2")
        candidates = [_row(row) for row in db.execute(
            "SELECT * FROM task_queue WHERE state='pending' ORDER BY CASE priority "
            "WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, created_at")]
        chosen = None
        for item in candidates:
            if not _ready(project, item):
                continue
            if item["priority"] == "P2" and p2_running >= max(0, max_slots - 1):
                continue
            chosen = item
            break
        if chosen is None:
            return None
        db.execute("UPDATE task_queue SET state='running', lease_owner=?, lease_expires=?, "
                   "attempts=attempts+1, updated_at=? WHERE task_id=? AND state='pending'",
                   (owner, _now() + float(lease_seconds),
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), chosen["task_id"]))
    _event(project, chosen["task_id"], "claimed", {"owner": owner})
    item = get(project, chosen["task_id"])
    item["priority_rank"] = PRIORITIES.index(item["priority"])
    return item


def renew(project, task_id: str, owner: str, *, lease_seconds: float = LEASE_SECONDS) -> Dict[str, Any]:
    item = get(project, task_id)
    if item.get("committing"):
        if item.get("lease_expires") and item["lease_expires"] < _now():
            _mark_recovery(project, task_id)
            raise SchedulerError("recovery_required")
        return {"status": "committing", "renewed": False}
    if item["lease_owner"] != owner:
        raise SchedulerError("lease_owner_mismatch")
    with wb.write_tx(project) as db:
        db.execute("UPDATE task_queue SET lease_expires=?, updated_at=? WHERE task_id=?",
                   (_now() + float(lease_seconds),
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
    return {"status": "renewed", "lease_expires": item.get("lease_expires")}


def begin_commit(project, task_id: str, owner: str) -> Dict[str, Any]:
    item = get(project, task_id)
    if item["lease_owner"] != owner:
        raise SchedulerError("lease_owner_mismatch")
    with wb.write_tx(project) as db:
        db.execute("UPDATE task_queue SET committing=1, updated_at=? WHERE task_id=?",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
    _event(project, task_id, "committing")
    return get(project, task_id)


def _mark_recovery(project, task_id: str) -> None:
    with wb.write_tx(project) as db:
        db.execute("UPDATE task_queue SET state='recovery_required', updated_at=? "
                   "WHERE task_id=? AND state='running'",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
    _event(project, task_id, "recovery_required")


def complete(project, task_id: str, *, owner: str = "") -> Dict[str, Any]:
    item = get(project, task_id)
    if item.get("state") == "completed":
        return item
    if item.get("state") != "running" or not owner or item.get("lease_owner") != owner:
        raise SchedulerError("task_not_running", status=409)
    with wb.write_tx(project) as db:
        cur =        db.execute("UPDATE task_queue SET state='completed', lease_owner=NULL, lease_expires=NULL, "
                   "committing=0, hold_amendment_id=NULL, amendment_fallback='wait', updated_at=? "
                   "WHERE task_id=? AND state='running' AND lease_owner=?",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id, owner))
        if not cur.rowcount:
            raise SchedulerError("task_not_running", status=409)
    _event(project, task_id, "completed")
    return get(project, task_id)


def fail(project, task_id: str, *, error: str = "", max_attempts: int = 3) -> Dict[str, Any]:
    item = get(project, task_id)
    if item.get("state") == "completed":
        return item
    if item.get("state") not in {"running", "committing"}:
        raise SchedulerError("task_not_running", status=409)
    state = "pending" if int(item.get("attempts") or 0) < int(max_attempts) else "failed"
    with wb.write_tx(project) as db:
        cur = db.execute("UPDATE task_queue SET state=?, lease_owner=NULL, lease_expires=NULL, "
                         "committing=0, updated_at=? WHERE task_id=? AND state IN ('running','committing')",
                         (state, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
        if not cur.rowcount:
            raise SchedulerError("task_not_running", status=409)
    _event(project, task_id, "failed", {"error": error, "next": state})
    return get(project, task_id)


def recover(project) -> List[Dict[str, Any]]:
    """Expired running tasks: committing → recovery_required, else re-queue."""
    wb.initialize(project)
    rows = []
    with wb.connect(project) as db:
        expired = [dict(row) for row in db.execute(
            "SELECT * FROM task_queue WHERE state='running' AND lease_expires IS NOT NULL "
            "AND lease_expires < ?", (_now(),))]
    for item in expired:
        if item.get("committing"):
            _mark_recovery(project, item["task_id"])
        else:
            with wb.write_tx(project) as db:
                db.execute("UPDATE task_queue SET state='pending', lease_owner=NULL, lease_expires=NULL, "
                           "updated_at=? WHERE task_id=? AND state='running' AND lease_owner=?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), item["task_id"],
                            item.get("lease_owner")))
            _event(project, item["task_id"], "lease_expired_requeued")
        rows.append(get(project, item["task_id"]))
    return rows


def hold_for_amendment(project, amendment_id: str, task_ids: Iterable[str], *,
                       fallback: str = "wait") -> Dict[str, Any]:
    if fallback not in {"wait", "continue"}:
        raise SchedulerError("invalid_amendment_fallback", status=400)
    held = []
    for task_id in task_ids:
        item = get(project, task_id)
        if item["state"] in {"completed", "cancelled", "failed"}:
            continue
        state = "held" if fallback == "wait" else item["state"]
        with wb.write_tx(project) as db:
            db.execute("UPDATE task_queue SET state=?, hold_amendment_id=?, amendment_fallback=?, "
                       "updated_at=? WHERE task_id=?",
                       (state, amendment_id, fallback,
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
        held.append(task_id)
    _event(project, None, "amendment_hold", {"amendment_id": amendment_id, "held": held})
    return {"status": "held", "amendment_id": amendment_id, "held_task_ids": held,
            "fallback": fallback}


def retry(project, task_id: str, *, owner: str = "author") -> Dict[str, Any]:
    item = get(project, task_id)
    if item["state"] not in {"failed", "recovery_required", "interrupted", "cancelled"}:
        raise SchedulerError("task_not_retryable")
    with wb.write_tx(project) as db:
        db.execute("UPDATE task_queue SET state='pending', lease_owner=NULL, lease_expires=NULL, "
                   "committing=0, attempts=0, updated_at=? WHERE task_id=?",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
    _event(project, task_id, "retried", {"owner": owner})
    return get(project, task_id)


def release_amendment(project, amendment_id: str) -> Dict[str, Any]:
    released = []
    with wb.connect(project) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT task_id FROM task_queue WHERE hold_amendment_id=? AND state='held'",
            (amendment_id,))]
    for row in rows:
        with wb.write_tx(project) as db:
            db.execute("UPDATE task_queue SET state='pending', hold_amendment_id=NULL, updated_at=? "
                       "WHERE task_id=?",
                       (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), row["task_id"]))
        released.append(row["task_id"])
    _event(project, None, "amendment_released", {"amendment_id": amendment_id,
                                                  "released": released})
    return {"status": "released", "amendment_id": amendment_id, "released_task_ids": released}


def snapshot(project, *, max_slots: int = 4) -> Dict[str, Any]:
    rows = list_tasks(project)
    return {"max_slots": max_slots,
            "counts": {state: sum(1 for row in rows if row["state"] == state)
                       for state in {row["state"] for row in rows}},
            "paused": paused_scopes(project), "tasks": rows}


# --------------------------------------------------------------- wake / SSE

class LoopbackNotifier:
    """The single main-process wake path: POST /internal/events/notify."""

    def __init__(self, port: int, token: str, *, timeout: float = 2.0,
                 opener: Optional[Callable] = None):
        self.port = int(port)
        self.token = token
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def notify(self, payload: Optional[Dict[str, Any]] = None) -> bool:
        data = json.dumps(payload or {"kind": "wake"}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/internal/events/notify", data=data,
            headers={"Content-Type": "application/json", "X-Internal-Token": self.token},
            method="POST")
        try:
            with self._opener(request, timeout=self.timeout) as response:
                return 200 <= int(getattr(response, "status", 200)) < 300
        except (urllib.error.URLError, OSError, ValueError):
            return False


def spawn_worker(command: List[str], *, cwd: Optional[str] = None,
                 env: Optional[Dict[str, str]] = None) -> subprocess.Popen:
    """Worker stdout/stderr are merged so startup errors never hide."""
    environment = dict(os.environ if env is None else env)
    environment.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.Popen(command, cwd=cwd, env=environment, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)


class EventFanout:
    """Slow-client guard: at most 256 pending frames, then resync_required."""

    def __init__(self, max_pending: int = MAX_PENDING_FRAMES):
        self.max_pending = int(max_pending)
        self._queues: List[queue.Queue] = []
        self._lock = __import__("threading").Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def publish(self, frame: Dict[str, Any]) -> List[queue.Queue]:
        dropped = []
        with self._lock:
            for q in list(self._queues):
                if q.qsize() >= self.max_pending:
                    try:
                        while True:
                            q.get_nowait()
                    except queue.Empty:
                        pass
                    q.put_nowait({"kind": "resync_required"})
                    self._queues.remove(q)
                    dropped.append(q)
                else:
                    q.put_nowait(frame)
        return dropped


def notify_callback(notifier: Optional[LoopbackNotifier]) -> Callable[[Dict[str, Any]], bool]:
    def wake(payload: Dict[str, Any]) -> bool:
        return bool(notifier and notifier.notify(payload))
    return wake
