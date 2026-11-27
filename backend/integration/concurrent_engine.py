"""两层并发引擎（v0.9 三期）。

P0 快道永远先于 P1 自动日更与 P2 批量；P2 最多占用 ``max_slots - 1`` 个槽，
给作者手动操作保留至少一个空位。暂停分三级：全局 / 项目 / 任务，子任务
继承父任务的暂停与改令挂起。租约到期且处于 ``committing`` 的任务不会被
静默重跑，而是进入 ``recovery_required`` 等对账。
"""
from __future__ import annotations

import hashlib
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


def _is_readonly_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(token in text for token in
               ("readonly", "read-only", "unable to open database", "permission denied", "locked"))


def _ensure(project, *, create: bool = True) -> bool:
    """Initialize/heal the queue schema.

    审计 C3-04：读路径 ``create=False`` 在作品没有 workbench 库时直接返回
    False，不再让一次 GET 创建 ``.webnovel/workbench.sqlite3``。
    审计 C4-05：库存在但损坏时必须报 503 ``db_unavailable``，不能把故障
    伪装成空队列；只读挂载上的读路径仍返回空（写路径再按 503 拒绝）。
    """
    if not wb.db_path(project).exists():
        if not create:
            return False
        try:
            wb.initialize(project)
        except sqlite3.Error as exc:
            raise SchedulerError("db_unavailable", status=503,
                                 detail={"reason": type(exc).__name__}) from None
        return True
    from integration import maintenance
    try:
        maintenance.ensure_schema(project)
        wb.initialize(project)
    except sqlite3.Error as exc:
        if not create and _is_readonly_error(exc):
            return False
        raise SchedulerError("db_unavailable", status=503,
                             detail={"reason": type(exc).__name__}) from None
    return True


def _params_signature(priority: str, chapter_id, parent_task_id, blocked_by,
                      payload, amendment_fallback: str) -> str:
    """Canonical hash of everything that defines the submitted work (C3-14)."""
    return hashlib.sha256(json.dumps({
        "priority": priority,
        "chapter_id": chapter_id,
        "parent_task_id": parent_task_id,
        "blocked_by": list(blocked_by or []),
        "payload": payload or {},
        "amendment_fallback": amendment_fallback,
    }, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _row_signature(item: Dict[str, Any]) -> str:
    return _params_signature(str(item.get("priority") or "P2"), item.get("chapter_id"),
                             item.get("parent_task_id"), item.get("blocked_by") or [],
                             item.get("payload") or {},
                             str(item.get("amendment_fallback") or "wait"))


def _blocker_edges(project) -> Dict[str, set]:
    with wb.connect(project) as db:
        edges: Dict[str, set] = {}
        for row in db.execute("SELECT task_id, blocked_by_json FROM task_queue"):
            try:
                edges[str(row[0])] = set(json.loads(row[1] or "[]"))
            except (TypeError, ValueError):
                edges[str(row[0])] = set()
        return edges


def _reaches(edges: Dict[str, set], start: str, target: str) -> bool:
    stack = [start]
    seen = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node) or ())
    return False


def _validate_blockers(project, task_id: str, blockers: List[str]) -> List[str]:
    """Reject missing/self/cyclic dependencies before the task is queued (C3-15)."""
    unique: List[str] = []
    seen = set()
    for blocker in blockers:
        if blocker == task_id:
            raise SchedulerError("blocked_by_self", status=400,
                                 detail={"task_id": task_id})
        if blocker in seen:
            continue
        seen.add(blocker)
        unique.append(blocker)
    edges = _blocker_edges(project)
    edges[task_id] = set(unique)
    for blocker in unique:
        try:
            get(project, blocker)
        except SchedulerError:
            raise SchedulerError("blocked_by_missing", status=400,
                                 detail={"task_id": task_id, "blocked_by": blocker}) from None
        if _reaches(edges, blocker, task_id):
            raise SchedulerError("blocked_by_cycle", status=400,
                                 detail={"task_id": task_id, "blocked_by": blocker})
    return unique


def _blocked_reason(project, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Why ``_ready`` refuses this task; also surfaced by ``snapshot`` (C3-15)."""
    for blocker in item.get("blocked_by") or []:
        try:
            other = get(project, blocker)
        except SchedulerError:
            return {"task_id": blocker, "reason": "missing", "action": "resubmit_blocker"}
        if other.get("state") == "failed":
            # 审计 C4-04：失败上游不会自动放行；给 UI 一个明确动作，而不是
            # 让下游永久静默 pending。
            return {"task_id": blocker, "reason": "failed", "action": "retry_blocker"}
        if other.get("state") not in {"completed", "cancelled"}:
            return {"task_id": blocker, "reason": str(other.get("state") or "pending")}
    return None


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
    _ensure(project)
    tid = str(task_id or wb.new_id("task"))
    incoming = _params_signature(priority, chapter_id, parent_task_id, blocked_items,
                                 payload, amendment_fallback)
    if task_id:
        # 审计 C3-14：同一 task_id 重试只有在参数完全一致时才是幂等重放；
        # 参数变化必须 409，绝不静默丢弃新意图。
        try:
            existing = get(project, tid)
        except SchedulerError:
            existing = None
        if existing is not None:
            if _row_signature(existing) != incoming:
                raise SchedulerError("task_id_payload_mismatch", status=409,
                                     detail={"task_id": tid})
            return {**existing, "deduplicated": True}
    blocked_items = _validate_blockers(project, tid, blocked_items)
    # 审计 C4-04：对已经 failed 的上游直接拒绝新任务，避免入队即永久阻塞。
    for blocker in blocked_items:
        if get(project, blocker).get("state") == "failed":
            raise SchedulerError("blocked_by_failed", status=409,
                                 detail={"task_id": tid, "blocked_by": blocker,
                                         "action": "retry_blocker"})
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
        if _row_signature(existing) != incoming:
            raise SchedulerError("task_id_payload_mismatch", status=409,
                                 detail={"task_id": tid}) from None
        return {**existing, "deduplicated": True}
    _event(project, tid, "submitted", {"priority": priority})
    return get(project, tid)


def get(project, task_id: str) -> Dict[str, Any]:
    if not _ensure(project, create=False):
        raise SchedulerError("task_missing", status=404)
    with wb.connect(project) as db:
        row = db.execute("SELECT * FROM task_queue WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        raise SchedulerError("task_missing", status=404)
    return _row(row)


def list_tasks(project, *, state: Optional[str] = None) -> List[Dict[str, Any]]:
    if not _ensure(project, create=False):
        return []
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
    """Fail closed: an unreadable/corrupt pause file means "paused".

    审计 C3-23：旧实现对任何异常 ``return False``，损坏的急停文件会让全站
    自动化继续运行。文件不存在仍是唯一的“未暂停”状态。
    """
    target = _global_pause_path(path)
    if target is None or not target.exists():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - unreadable pause file is not permission to run
        return True
    if not isinstance(data, dict) or "paused" not in data:
        return True
    value = data.get("paused")
    return value is True or (isinstance(value, int) and not isinstance(value, bool) and value == 1)


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
    _ensure(project)
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
    _ensure(project)
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
    if not _ensure(project, create=False):
        return []
    with wb.connect(project) as db:
        rows = db.execute("SELECT * FROM task_pauses ORDER BY scope").fetchall()
    return [dict(row) for row in rows]


def project_paused(project) -> bool:
    """True when this project's task queue is paused (project or global scope).

    审计 C-09：v0.8 的 ops/scheduler 在派发前也要看这里，否则「全站急停」
    只拦住一个没有消费者的 v0.9 队列。
    审计 C3-23：暂停表损坏/被锁时按“已暂停”处理（fail-closed），不能因为
    SQLite 错误让作者以为自动化仍在受控状态。
    """
    target = Path(project)
    if not target.is_dir() or not wb.db_path(target).exists():
        return False
    try:
        with wb.connect(target) as db:
            row = db.execute("SELECT 1 FROM task_pauses WHERE scope IN ('global', ?) LIMIT 1",
                             ("project:" + str(target.resolve()),)).fetchone()
    except sqlite3.Error:
        return True
    return row is not None


def _hold_active(item: Dict[str, Any]) -> bool:
    """True when an amendment hold must stop claim/commit/complete.

    审计 C3-13：``hold_requested`` 或尚未释放的 ``hold_amendment_id`` 都必须
    生效；``fallback='continue'`` 是显式的“继续旧计划”开关，因此只有该
    回退值允许任务在改令评估期间继续执行。
    """
    if item.get("hold_requested"):
        return True
    amendment = item.get("hold_amendment_id")
    if not amendment:
        return False
    return str(item.get("amendment_fallback") or "wait") != "continue"


def _ready(project, item: Dict[str, Any], pause_path=None) -> bool:
    if item["state"] != "pending":
        return False
    if _hold_active(item):
        return False
    if _blocked_reason(project, item) is not None:
        return False
    return not _task_paused(project, item, pause_path=pause_path)


def claim(project, owner: str, *, max_slots: int = 4, lease_seconds: float = LEASE_SECONDS,
          pause_path=None, max_attempts: int = MAX_ATTEMPTS) -> Optional[Dict[str, Any]]:
    """Lease one ready task; returns None when the pool is full or idle."""
    _ensure(project)
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
    # 审计 C3-13：改令未释放时不得进入提交；旧实现允许 running 任务在
    # hold_requested=1 时 begin_commit，改令评估时已提交，无法回滚。
    if _hold_active(item):
        raise SchedulerError("hold_pending", status=409,
                             detail={"amendment_id": item.get("hold_amendment_id")})
    now = _now()
    expiry = now + float(commit_grace)
    with wb.write_tx(project) as db:
        # 审计 C3-11：已过期的租约不得借 begin_commit 复活并续 300 秒；
        # 与 renew() 一样要求 lease_expires 仍然有效。
        cur = db.execute("UPDATE task_queue SET committing=1, lease_expires=?, updated_at=? "
                         "WHERE task_id=? AND state='running' AND lease_owner=? "
                         "AND COALESCE(hold_requested,0)=0 "
                         "AND (hold_amendment_id IS NULL OR amendment_fallback='continue') "
                         "AND (lease_expires IS NULL OR lease_expires >= ?)",
                         (expiry, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          task_id, owner, now))
        updated = bool(cur.rowcount)
    if not updated:
        current = get(project, task_id)
        if _hold_active(current):
            raise SchedulerError("hold_pending", status=409,
                                 detail={"amendment_id": current.get("hold_amendment_id")})
        if current.get("state") == "recovery_required":
            raise SchedulerError("recovery_required")
        if current.get("state") != "running" or current.get("lease_owner") != owner:
            raise SchedulerError("task_not_running", status=409)
        _mark_recovery(project, task_id, owner=owner, expired=True)
        raise SchedulerError("recovery_required")
    _event(project, task_id, "committing", {"commit_grace": float(commit_grace)})
    return get(project, task_id)


def _mark_recovery(project, task_id: str, *, owner: str = "", expired: bool = False) -> None:
    now = _now()
    # 审计 C3-13：进入 recovery_required 时保留改令标志；人工对账后由
    # release_amendment 显式清除，不能让恢复流程偷偷放行。
    sql = ("UPDATE task_queue SET state='recovery_required', updated_at=? "
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
    # 审计 C3-13：改令挂起后不得直接完成；必须先 release_amendment。
    if _hold_active(item):
        raise SchedulerError("hold_pending", status=409,
                             detail={"amendment_id": item.get("hold_amendment_id")})
    with wb.write_tx(project) as db:
        cur = db.execute("UPDATE task_queue SET state='completed', lease_owner=NULL, lease_expires=NULL, "
                   "committing=0, hold_requested=0, hold_amendment_id=NULL, amendment_fallback='wait', "
                   "updated_at=? WHERE task_id=? AND state='running' AND lease_owner=? "
                   "AND COALESCE(hold_requested,0)=0 "
                   "AND (hold_amendment_id IS NULL OR amendment_fallback='continue')",
                   (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), task_id, owner))
        if not cur.rowcount:
            current = get(project, task_id)
            if _hold_active(current):
                raise SchedulerError("hold_pending", status=409,
                                     detail={"amendment_id": current.get("hold_amendment_id")})
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
    expected_owner = str(item.get("lease_owner") or "")
    if owner and owner != expected_owner:
        raise SchedulerError("lease_owner_mismatch")
    state = "pending" if int(item.get("attempts") or 0) < int(max_attempts) else "failed"
    with wb.write_tx(project) as db:
        # 审计 C3-12：owner 条件必须和 UPDATE 同一条语句。读后到写前若租约
        # 已过期并被新 worker 领取，旧 worker 的迟到失败不得清掉新租约。
        # 审计 C3-13：失败/重试不得清除改令标志，否则 claim() 会在改令
        # 评估前把任务重新领走；离开改令只能走 release_amendment。
        cur = db.execute("UPDATE task_queue SET state=?, lease_owner=NULL, lease_expires=NULL, "
                         "committing=0, updated_at=? "
                         "WHERE task_id=? AND state IN ('running','committing') "
                         "AND COALESCE(lease_owner,'')=?",
                         (state, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          task_id, expected_owner))
        updated = bool(cur.rowcount)
    if not updated:
        current = get(project, task_id)
        if current.get("state") == "completed":
            return current
        raise SchedulerError("task_not_running", status=409,
                             detail={"state": current.get("state")})
    _event(project, task_id, "failed", {"error": error, "next": state})
    return get(project, task_id)


def recover(project, *, max_attempts: int = MAX_ATTEMPTS) -> List[Dict[str, Any]]:
    """Expired running tasks: committing → recovery_required, else re-queue.

    审计 C-06：``attempts >= max_attempts`` 的崩溃任务必须终止为 ``failed``，
    否则 ``claim()`` 每次先 recover 会形成 pending→running→过期→pending 的
    无限循环并持续计费。
    """
    _ensure(project)
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
                           "committing=0, updated_at=? "
                           "WHERE task_id=? AND state='running' AND lease_owner=? "
                           "AND lease_expires IS NOT NULL AND lease_expires < ?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), item["task_id"],
                            item.get("lease_owner"), _now()))
            _event(project, item["task_id"], "exhausted", {"attempts": int(item.get("attempts") or 0)})
        else:
            # 审计 C3-13：带改令标志的过期任务回到 held（而不是 pending），
            # claim 不得绕过改令；无改令标志才普通重排队。
            next_state = ("held" if item.get("hold_amendment_id")
                          and str(item.get("amendment_fallback") or "wait") != "continue"
                          else "pending")
            with wb.write_tx(project) as db:
                db.execute("UPDATE task_queue SET state=?, lease_owner=NULL, lease_expires=NULL, "
                           "updated_at=? WHERE task_id=? AND state='running' AND lease_owner=? "
                           "AND lease_expires IS NOT NULL AND lease_expires < ?",
                           (next_state, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            item["task_id"], item.get("lease_owner"), _now()))
            _event(project, item["task_id"], "lease_expired_requeued", {"next": next_state})
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
    _ensure(project)
    held, requested, continued = [], [], []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for task_id in task_ids:
        with wb.write_tx(project) as db:
            row = db.execute("SELECT * FROM task_queue WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                continue
            item = _row(row)
            # 审计 C3-13：recovery_required / failed / interrupted 是人工
            # 对账状态，普通改令不能把它们洗成 held 再放行。
            if item["state"] not in {"pending", "held", "running"}:
                continue
            if item["state"] == "running":
                requested_flag = 1 if fallback == "wait" else 0
                cur = db.execute("UPDATE task_queue SET hold_requested=?, hold_amendment_id=?, "
                                 "amendment_fallback=?, updated_at=? "
                                 "WHERE task_id=? AND state='running'",
                                 (requested_flag, amendment_id, fallback, stamp, task_id))
                if cur.rowcount:
                    (requested if fallback == "wait" else continued).append(task_id)
                continue
            old_state = item["state"]
            state = "held" if fallback == "wait" else old_state
            cur = db.execute("UPDATE task_queue SET state=?, hold_requested=?, hold_amendment_id=?, "
                             "amendment_fallback=?, committing=CASE WHEN ?='held' THEN 0 ELSE committing END, "
                             "lease_owner=CASE WHEN ?='held' THEN NULL ELSE lease_owner END, "
                             "lease_expires=CASE WHEN ?='held' THEN NULL ELSE lease_expires END, "
                             "updated_at=? WHERE task_id=? AND state=?",
                             (state, 1 if state == "held" else 0, amendment_id, fallback,
                              state, state, state, stamp, task_id, old_state))
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
    if not _ensure(project, create=False):
        return {"status": "released", "amendment_id": amendment_id, "released_task_ids": []}
    with wb.connect(project) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT task_id, state FROM task_queue WHERE hold_amendment_id=? "
            "AND (state='held' OR hold_requested=1 OR amendment_fallback='continue')",
            (amendment_id,))]
    for row in rows:
        with wb.write_tx(project) as db:
            if row["state"] == "held":
                # 审计 C3-13：held→pending 必须同时清 committing，并只释放
                # 仍属于本改令的任务；旧实现会把 recovery_required 洗成
                # pending 且留下 committing=1。
                db.execute("UPDATE task_queue SET state='pending', hold_amendment_id=NULL, "
                           "hold_requested=0, amendment_fallback='wait', committing=0, updated_at=? "
                           "WHERE task_id=? AND state='held' AND hold_amendment_id=?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            row["task_id"], amendment_id))
            else:
                # 运行中的 worker 清掉协作停止标志后继续完成，不重跑；
                # recovery_required/failed 等状态保持原样，只清改令标志。
                db.execute("UPDATE task_queue SET hold_requested=0, hold_amendment_id=NULL, "
                           "amendment_fallback='wait', updated_at=? "
                           "WHERE task_id=? AND hold_amendment_id=?",
                           (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            row["task_id"], amendment_id))
        released.append(row["task_id"])
    _event(project, None, "amendment_released", {"amendment_id": amendment_id,
                                                  "released": released})
    return {"status": "released", "amendment_id": amendment_id, "released_task_ids": released}


def snapshot(project, *, max_slots: int = 4) -> Dict[str, Any]:
    rows = list_tasks(project)
    for row in rows:
        # 审计 C3-15：pending 任务必须能回答“为什么还没被领取”。
        if row.get("state") == "pending":
            reason = _blocked_reason(project, row)
            if reason:
                row["blocked_reason"] = reason
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
