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
import sqlite3
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
# 审计 C-07：大章节提交（备份 + fsync + Windows AV）超过 30 秒是常态，
# 提交阶段使用独立的长租约。
COMMIT_GRACE_SECONDS = 300.0
MAX_ATTEMPTS = 3
# 兼容旧调用方/测试直接读写该模块变量；新代码优先使用按应用分组的注册表。
_GLOBAL_PAUSE_PATH: Optional[Path] = None
_GLOBAL_PAUSE_PATHS: Dict[str, Path] = {}


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
    item["hold_requested"] = bool(item.get("hold_requested"))
    return item


def _event(project, task_id: Optional[str], kind: str, detail: Optional[Dict] = None) -> None:
    """Best-effort audit event.

    审计 C-36：事件写入在业务事务之后；它失败不能让已经入队的任务或已经
    提交的业务返回 500。
    """
    try:
        with wb.write_tx(project) as db:
            db.execute("INSERT INTO task_events(task_id, kind, detail_json, created_at) VALUES(?,?,?,?)",
                       (task_id, kind, json.dumps(detail or {}, ensure_ascii=False),
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    except sqlite3.Error:
        pass


def submit(project, payload: Dict[str, Any], *, priority: str = "P2",
           chapter_id: Optional[int] = None, task_id: Optional[str] = None,
           parent_task_id: Optional[str] = None, blocked_by: Iterable[str] = (),
           amendment_fallback: str = "wait") -> Dict[str, Any]:
    if priority not in PRIORITIES:
        raise SchedulerError("invalid_priority", status=400)
    if amendment_fallback not in {"wait", "continue"}:
        raise SchedulerError("invalid_amendment_fallback", status=400)
    if not isinstance(payload, dict):
        raise SchedulerError("invalid_payload", status=400)
    # 审计 C-37：str 会被 list("abc") 拆成三个 blocker，必须拒绝。
    if isinstance(blocked_by, (str, bytes)):
        raise SchedulerError("invalid_blocked_by", status=400)
    blocked_items = list(blocked_by)
    if any(not isinstance(item, str) or not item.strip() for item in blocked_items):
        raise SchedulerError("invalid_blocked_by", status=400)
    wb.initialize(project)
    tid = str(task_id or wb.new_id("task"))
    if task_id:
        # 审计 C-36：调用方可以通过 task_id 重试；已存在的任务直接返回，
        # 绝不生成第二条重复任务。
        try:
            return {**get(project, tid), "deduplicated": True}
        except SchedulerError:
            pass
    state = "pending"
    hold = None
    if parent_task_id:
        parent = get(project, parent_task_id)
        if parent.get("hold_amendment_id") and amendment_fallback == "wait":
            state = "held"
            hold = parent["hold_amendment_id"]
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with wb.write_tx(project) as db:
            db.execute(
                "INSERT INTO task_queue(task_id, chapter_id, priority, state, parent_task_id, "
                "blocked_by_json, hold_amendment_id, amendment_fallback, committing, attempts, "
                "payload_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,0,0,?,?,?)",
                (tid, chapter_id, priority, state, parent_task_id,
                 json.dumps(blocked_items, ensure_ascii=False), hold, amendment_fallback,
                 json.dumps(payload or {}, ensure_ascii=False), stamp, stamp),
            )
    except sqlite3.IntegrityError:
        existing = get(project, tid)
        return {**existing, "deduplicated": True}
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


def configure_global_pause(path, *, scope: str = "default") -> None:
    """Register a pause file for a scope (CLI default or an explicit app)."""
    global _GLOBAL_PAUSE_PATH
    _GLOBAL_PAUSE_PATHS[str(scope)] = Path(path)
    if str(scope) == "default":
        _GLOBAL_PAUSE_PATH = Path(path)


def _global_pause_path(path=None) -> Optional[Path]:
    if path is not None:
        return Path(path)
    value = os.getenv("NOVEL_HELPER_GLOBAL_PAUSE")
    if value:
        return Path(value)
    return _GLOBAL_PAUSE_PATHS.get("default") or _GLOBAL_PAUSE_PATH


def global_paused(path=None) -> bool:
    target = _global_pause_path(path)
    if target is None or not target.is_file():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return bool(data.get("paused"))
    except Exception:
        return False


def set_global_pause(paused: bool, reason: str = "", *, path=None) -> Dict[str, Any]:
    target = _global_pause_path(path)
    if target is None:
        raise SchedulerError("global_pause_path_missing", status=500)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"paused": bool(paused), "reason": str(reason or ""),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)
    return {"status": "paused" if paused else "resumed", "scope": "global", **data}


def _task_paused(project, item: Dict[str, Any], pause_path=None) -> bool:
    if global_paused(pause_path):
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


def _normalize_scope(project, scope: str) -> str:
    """Accept ``project:<name>`` but always store the resolved project path.

    审计 C-34：``_task_paused`` 只比较 ``project:<resolve()>``，旧的
    ``project:书名`` 会返回 paused 却完全不生效。
    """
    scope = str(scope or "").strip()
    if scope == "global":
        return "global"
    if scope.startswith("project:"):
        return "project:" + str(Path(project).resolve())
    if scope.startswith("task:") and scope.split(":", 1)[1].strip():
        return scope
    raise SchedulerError("invalid_pause_scope", status=400)


def pause(project, scope: str, reason: str = "") -> Dict[str, Any]:
    scope = _normalize_scope(project, scope)
    wb.initialize(project)
    with wb.write_tx(project) as db:
        db.execute("INSERT OR REPLACE INTO task_pauses(scope, reason, created_at) VALUES(?,?,?)",
                   (scope, reason, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        if scope.startswith("task:"):
            # 审计 C-34：任务级暂停也要让运行中的 worker 在检查点停手。
            db.execute("UPDATE task_queue SET hold_requested=1, updated_at=? "
                       "WHERE task_id=? AND state='running'",
                       (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        scope.split(":", 1)[1]))
    _event(project, None, "paused", {"scope": scope, "reason": reason})
    return {"status": "paused", "scope": scope}


def resume(project, scope: str) -> Dict[str, Any]:
    scope = _normalize_scope(project, scope)
    wb.initialize(project)
    with wb.write_tx(project) as db:
        db.execute("DELETE FROM task_pauses WHERE scope=?", (scope,))
        if scope.startswith("task:"):
            # 仅清掉「任务暂停」标志；改令 hold 仍由 hold_amendment_id 管理。
            db.execute("UPDATE task_queue SET hold_requested=0, updated_at=? "
                       "WHERE task_id=? AND hold_amendment_id IS NULL",
                       (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        scope.split(":", 1)[1]))
    _event(project, None, "resumed", {"scope": scope})
    return {"status": "resumed", "scope": scope}


def paused_scopes(project) -> List[Dict[str, Any]]:
    _ensure_queue(project)
    with wb.connect(project) as db:
        rows = db.execute("SELECT * FROM task_pauses ORDER BY scope").fetchall()
    return [dict(row) for row in rows]


def project_paused(project) -> bool:
    """True when this project's task queue is paused (project or global scope).

    审计 C-09：v0.8 的 ops/scheduler 在派发前也要看这里，否则「全站急停」
    只拦住一个没有消费者的 v0.9 队列。
    """
    target = Path(project)
    if not target.is_dir() or not wb.db_path(target).exists():
        return False
    try:
        with wb.connect(target) as db:
            row = db.execute("SELECT 1 FROM task_pauses WHERE scope IN ('global', ?) LIMIT 1",
                             ("project:" + str(target.resolve()),)).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _ready(project, item: Dict[str, Any], pause_path=None) -> bool:
    if item["state"] != "pending":
        return False
    for blocker in item.get("blocked_by") or []:
        try:
            other = get(project, blocker)
        except SchedulerError:
            return False
        if other["state"] not in {"completed", "cancelled"}:
            return False
    return not _task_paused(project, item, pause_path=pause_path)


def claim(project, owner: str, *, max_slots: int = 4, lease_seconds: float = LEASE_SECONDS,
          pause_path=None, max_attempts: int = MAX_ATTEMPTS) -> Optional[Dict[str, Any]]:
    """Lease one ready task; returns None when the pool is full or idle."""
    wb.initialize(project)
    # 每次派发前回收过期租约；无需依赖作者手动调用 /tasks/recover。
    recover(project, max_attempts=max_attempts)
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
            if not _ready(project, item, pause_path=pause_path):
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


def renew(project, task_id: str, owner: str, *, lease_seconds: float = LEASE_SECONDS,
          commit_grace: float = COMMIT_GRACE_SECONDS) -> Dict[str, Any]:
    # Atomic read-modify-write: the old read decided the grace from a stale
    # ``committing`` flag and could shorten a 300s commit lease back to 30s
    # (C-R2-02).  The CASE is evaluated in the same UPDATE that checks owner
    # and a still-live lease.
    now = _now()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with wb.write_tx(project) as db:
        cur = db.execute(
            "UPDATE task_queue SET lease_expires = ? + CASE WHEN committing=1 THEN ? ELSE ? END, "
            "updated_at=? WHERE task_id=? AND state='running' AND lease_owner=? "
            "AND (lease_expires IS NULL OR lease_expires >= ?)",
            (now, float(commit_grace), float(lease_seconds), stamp, task_id, owner, now))
        row = db.execute("SELECT committing, lease_expires FROM task_queue WHERE task_id=?",
                         (task_id,)).fetchone() if cur.rowcount else None
    if not cur.rowcount:
        item = get(project, task_id)
        if item.get("state") == "recovery_required":
            raise SchedulerError("recovery_required")
        if item.get("state") != "running" or item.get("lease_owner") != owner:
            raise SchedulerError("task_not_running", status=409)
        _mark_recovery(project, task_id, owner=owner, expired=True)
        raise SchedulerError("recovery_required")
    return {"status": "committing" if row and row[0] else "renewed",
            "renewed": True, "lease_expires": row[1] if row else None}


def begin_commit(project, task_id: str, owner: str, *,
                 commit_grace: float = COMMIT_GRACE_SECONDS) -> Dict[str, Any]:
    item = get(project, task_id)
    # 审计 C-08：改令不得把 running 改成 held；提交入口只接受仍在 running 的租约。
    if item["state"] != "running":
        raise SchedulerError("task_not_running", status=409)
    if item["lease_owner"] != owner:
        raise SchedulerError("lease_owner_mismatch")
    expiry = _now() + float(commit_grace)
    with wb.write_tx(project) as db:
        cur = db.execute("UPDATE task_queue SET committing=1, lease_expires=?, updated_at=? "
                         "WHERE task_id=? AND state='running' AND lease_owner=?",
                         (expiry, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          task_id, owner))
        if not cur.rowcount:
            raise SchedulerError("task_not_running", status=409)
    _event(project, task_id, "committing", {"commit_grace": float(commit_grace)})
    return get(project, task_id)


def _mark_recovery(project, task_id: str, *, owner: str = "", expired: bool = False) -> None:
    now = _now()
    sql = ("UPDATE task_queue SET state='recovery_required', hold_requested=0, updated_at=? "
           "WHERE task_id=? AND state='running'")
    args = [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id]
    if owner:
        sql += " AND lease_owner=?"
        args.append(owner)
    if expired:
        sql += " AND lease_expires IS NOT NULL AND lease_expires < ?"
        args.append(now)
    with wb.write_tx(project) as db:
        db.execute(sql, tuple(args))
    _event(project, task_id, "recovery_required")


def complete(project, task_id: str, *, owner: str = "") -> Dict[str, Any]:
    item = get(project, task_id)
    if item.get("state") == "completed":
        return item
    if item.get("state") != "running" or not owner or item.get("lease_owner") != owner:
        raise SchedulerError("task_not_running", status=409)
    with wb.write_tx(project) as db:
        cur = db.execute("UPDATE task_queue SET state='completed', lease_owner=NULL, lease_expires=NULL, "
                   "committing=0, hold_requested=0, hold_amendment_id=NULL, amendment_fallback='wait', "
                   "updated_at=? WHERE task_id=? AND state='running' AND lease_owner=?",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id, owner))
        if not cur.rowcount:
            raise SchedulerError("task_not_running", status=409)
    _event(project, task_id, "completed")
    return get(project, task_id)


def fail(project, task_id: str, *, owner: str = "", error: str = "",
         max_attempts: int = MAX_ATTEMPTS) -> Dict[str, Any]:
    item = get(project, task_id)
    if item.get("state") == "completed":
        return item
    if item.get("state") not in {"running", "committing"}:
        raise SchedulerError("task_not_running", status=409)
    # 审计 C-33：调用者必须持有该租约，否则任何人都能打断别人的任务。
    if item.get("lease_owner") and item.get("lease_owner") != owner:
        raise SchedulerError("lease_owner_mismatch")
    state = "pending" if int(item.get("attempts") or 0) < int(max_attempts) else "failed"
    with wb.write_tx(project) as db:
        cur = db.execute("UPDATE task_queue SET state=?, lease_owner=NULL, lease_expires=NULL, "
                         "committing=0, hold_requested=0, updated_at=? "
                         "WHERE task_id=? AND state IN ('running','committing')",
                         (state, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
        if not cur.rowcount:
            raise SchedulerError("task_not_running", status=409)
    _event(project, task_id, "failed", {"error": error, "next": state})
    return get(project, task_id)


def recover(project, *, max_attempts: int = MAX_ATTEMPTS) -> List[Dict[str, Any]]:
    """Expired running tasks: committing → recovery_required, else re-queue.

    审计 C-06：``attempts >= max_attempts`` 的崩溃任务必须终止为 ``failed``，
    否则 ``claim()`` 每次先 recover 会形成 pending→running→过期→pending 的
    无限循环并持续计费。
    """
    wb.initialize(project)
    rows = []
    with wb.connect(project) as db:
        expired = [dict(row) for row in db.execute(
            "SELECT * FROM task_queue WHERE state='running' AND lease_expires IS NOT NULL "
            "AND lease_expires < ?", (_now(),))]
    for item in expired:
        if item.get("committing"):
            _mark_recovery(project, item["task_id"], expired=True)
        elif int(item.get("attempts") or 0) >= int(max_attempts):
            with wb.write_tx(project) as db:
                db.execute("UPDATE task_queue SET state='failed', lease_owner=NULL, lease_expires=NULL, "
                           "committing=0, hold_requested=0, updated_at=? "
                           "WHERE task_id=? AND state='running' AND lease_owner=? "
                           "AND lease_expires IS NOT NULL AND lease_expires < ?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), item["task_id"],
                            item.get("lease_owner"), _now()))
            _event(project, item["task_id"], "exhausted", {"attempts": int(item.get("attempts") or 0)})
        else:
            with wb.write_tx(project) as db:
                db.execute("UPDATE task_queue SET state='pending', lease_owner=NULL, lease_expires=NULL, "
                           "updated_at=? WHERE task_id=? AND state='running' AND lease_owner=? "
                           "AND lease_expires IS NOT NULL AND lease_expires < ?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), item["task_id"],
                            item.get("lease_owner"), _now()))
            _event(project, item["task_id"], "lease_expired_requeued")
        rows.append(get(project, item["task_id"]))
    return rows


def hold_for_amendment(project, amendment_id: str, task_ids: Iterable[str], *,
                       fallback: str = "wait") -> Dict[str, Any]:
    """Freeze pending work; running workers get a cooperative stop flag.

    审计 C-08/C-R2-03：状态读取和写入必须在同一个事务里，并用旧状态做
    条件更新；否则 claim 在读到 pending 之后把任务改成 running，本函数还会
    把它改成 held 并清空租约。
    """
    if fallback not in {"wait", "continue"}:
        raise SchedulerError("invalid_amendment_fallback", status=400)
    held, requested, continued = [], [], []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for task_id in task_ids:
        with wb.write_tx(project) as db:
            row = db.execute("SELECT * FROM task_queue WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                continue
            item = _row(row)
            if item["state"] in {"completed", "cancelled", "failed"}:
                continue
            if item["state"] == "running":
                cur = db.execute("UPDATE task_queue SET hold_requested=1, hold_amendment_id=?, "
                                 "amendment_fallback=?, updated_at=? "
                                 "WHERE task_id=? AND state='running'",
                                 (amendment_id, fallback, stamp, task_id))
                if cur.rowcount:
                    requested.append(task_id)
                continue
            old_state = item["state"]
            state = "held" if fallback == "wait" else old_state
            cur = db.execute("UPDATE task_queue SET state=?, hold_amendment_id=?, amendment_fallback=?, "
                             "lease_owner=CASE WHEN ?='held' THEN NULL ELSE lease_owner END, "
                             "lease_expires=CASE WHEN ?='held' THEN NULL ELSE lease_expires END, "
                             "updated_at=? WHERE task_id=? AND state=?",
                             (state, amendment_id, fallback, state, state, stamp, task_id, old_state))
            if cur.rowcount:
                (held if state == "held" else continued).append(task_id)
    _event(project, None, "amendment_hold", {"amendment_id": amendment_id, "held": held,
                                             "hold_requested": requested})
    return {"status": "held", "amendment_id": amendment_id, "held_task_ids": held,
            "hold_requested_task_ids": requested, "continued_task_ids": continued,
            "fallback": fallback}


def retry(project, task_id: str, *, owner: str = "author") -> Dict[str, Any]:
    item = get(project, task_id)
    if item["state"] not in {"failed", "recovery_required", "interrupted", "cancelled"}:
        raise SchedulerError("task_not_retryable")
    with wb.write_tx(project) as db:
        db.execute("UPDATE task_queue SET state='pending', lease_owner=NULL, lease_expires=NULL, "
                   "committing=0, hold_requested=0, hold_amendment_id=NULL, "
                   "amendment_fallback='wait', attempts=0, updated_at=? WHERE task_id=?",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id))
    _event(project, task_id, "retried", {"owner": owner})
    return get(project, task_id)


def release_amendment(project, amendment_id: str) -> Dict[str, Any]:
    released = []
    with wb.connect(project) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT task_id, state FROM task_queue WHERE hold_amendment_id=? "
            "AND (state='held' OR hold_requested=1)", (amendment_id,))]
    for row in rows:
        with wb.write_tx(project) as db:
            if row["state"] == "held":
                db.execute("UPDATE task_queue SET state='pending', hold_amendment_id=NULL, "
                           "hold_requested=0, updated_at=? WHERE task_id=?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), row["task_id"]))
            else:
                # 运行中的 worker 清掉协作停止标志后继续完成，不重跑。
                db.execute("UPDATE task_queue SET hold_requested=0, hold_amendment_id=NULL, "
                           "updated_at=? WHERE task_id=?",
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
    """Worker stdout/stderr are merged into a readable pipe.

    审计 C-47：旧实现 ``stdout=DEVNULL, stderr=STDOUT`` 把错误也丢进
    ``/dev/null``，docstring 的说法恰好相反。调用方可以读
    ``process.stdout`` 得到启动错误。
    """
    environment = dict(os.environ if env is None else env)
    environment.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.Popen(command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
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
