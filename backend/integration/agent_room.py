"""主编室持久化事件总线、SQLite 四表与有界 SSE 广播器。

Tables live in the global ``manager.sqlite3`` (never in the per-book
``workbench.sqlite3``) and are completely additive: v0.7.5 ignores them.

* ``agent_directives`` — one author macro instruction (revision for amendments)
* ``agent_tasks`` — DAG nodes with checkpoints and artifact refs
* ``agent_events`` — durable chat/task/approval events, ``seq`` is the SSE id
* ``agent_approvals`` — high-risk cards with fingerprint/scope/expiry binding
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
CHANNELS = {"chief_chat", "team_room", "task_signal", "workspace_signal"}
TRANSIENT_KINDS = {"progress_signal", "live_preview_delta", "draft_updated"}
DEFAULT_DB = Path(os.getenv("NOVEL_HELPER_MANAGER_DB",
                            str(Path(__file__).resolve().parents[2] / "integration_data" / "manager.sqlite3")))


class RoomError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _db_path(db_path=None) -> Path:
    return Path(db_path) if db_path else DEFAULT_DB


@contextmanager
def connect(db_path=None):
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=15.0, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        db.close()


@contextmanager
def write_tx(db_path=None):
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            db.execute("ROLLBACK")
            raise
        else:
            db.execute("COMMIT")


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_directives (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_id TEXT,
    directive_revision INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    raw_instruction TEXT NOT NULL,
    autonomy TEXT NOT NULL,
    constraints_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    budget_cap_cny TEXT,
    max_calls INTEGER NOT NULL DEFAULT 20,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_directives_project ON agent_directives(project_id, created_at);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id TEXT PRIMARY KEY,
    directive_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    project_id TEXT,
    role TEXT NOT NULL,
    title TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    params_json TEXT NOT NULL,
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    wait_reason TEXT DEFAULT '',
    operation_id TEXT,
    checkpoint_json TEXT,
    artifact_ref_json TEXT,
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_directive ON agent_tasks(directive_id, status);

CREATE TABLE IF NOT EXISTS agent_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    session_id TEXT NOT NULL,
    topic_id TEXT NOT NULL DEFAULT 'default',
    project_id TEXT,
    directive_id TEXT,
    task_id TEXT,
    channel TEXT NOT NULL,
    sender_role TEXT NOT NULL,
    mentions_json TEXT DEFAULT '[]',
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_events_proj_seq ON agent_events(project_id, seq);
CREATE INDEX IF NOT EXISTS idx_agent_events_sess_seq ON agent_events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_agent_events_topic ON agent_events(project_id, topic_id, seq);

CREATE TABLE IF NOT EXISTS agent_approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_id TEXT,
    directive_id TEXT,
    directive_revision INTEGER NOT NULL DEFAULT 1,
    task_id TEXT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    artifact_fingerprint TEXT,
    approved_scope_hash TEXT,
    expires_at TEXT,
    detail_json TEXT NOT NULL,
    status TEXT NOT NULL,
    resolved_by TEXT,
    decision_json TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_approvals_status ON agent_approvals(project_id, status);

CREATE TABLE IF NOT EXISTS agent_amendments (
    id TEXT PRIMARY KEY,
    directive_id TEXT NOT NULL,
    directive_revision INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    fallback TEXT NOT NULL,
    status TEXT NOT NULL,
    held_task_ids_json TEXT NOT NULL DEFAULT '[]',
    evaluation_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_amendments_directive
  ON agent_amendments(directive_id, directive_revision);
"""


def initialize(db_path=None) -> Path:
    path = _db_path(db_path)
    with connect(db_path) as db:
        db.executescript(SCHEMA)
        db.execute("CREATE TABLE IF NOT EXISTS agent_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO agent_meta(key, value) VALUES('schema_version', '1')")
    return path


def _json(value, default):
    try:
        return json.loads(value) if value is not None else default
    except ValueError:
        return default


def create_directive(db_path=None, *, session_id: str, project_id: Optional[str], title: str,
                     raw_instruction: str, autonomy: str = "step_confirm",
                     constraints: Optional[Sequence[str]] = None, status: str = "planning",
                     budget_cap_cny: Optional[str] = None, max_calls: int = 20) -> Dict[str, Any]:
    if autonomy not in {"propose", "step_confirm", "auto_chain", "dry_run_first"}:
        raise RoomError("invalid_autonomy")
    directive_id = new_id("dir")
    stamp = now_iso()
    with write_tx(db_path) as db:
        db.execute(
            "INSERT INTO agent_directives(id, session_id, project_id, directive_revision, title, "
            "raw_instruction, autonomy, constraints_json, status, budget_cap_cny, max_calls, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (directive_id, session_id, project_id, 1, str(title)[:200], str(raw_instruction),
             autonomy, json.dumps(list(constraints or []), ensure_ascii=False), status,
             budget_cap_cny, int(max_calls), stamp, stamp),
        )
    return get_directive(db_path, directive_id)


def get_directive(db_path=None, directive_id: str = "") -> Dict[str, Any]:
    initialize(db_path)
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM agent_directives WHERE id=?", (directive_id,)).fetchone()
    if not row:
        raise RoomError("directive_missing", status=404)
    item = dict(row)
    item["constraints"] = _json(item.pop("constraints_json"), [])
    return item


def update_directive(db_path=None, directive_id: str = "", **fields) -> Dict[str, Any]:
    allowed = {"title", "status", "budget_cap_cny", "max_calls", "project_id", "autonomy"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return get_directive(db_path, directive_id)
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key}=?" for key in updates)
    with write_tx(db_path) as db:
        db.execute(f"UPDATE agent_directives SET {assignments} WHERE id=?",
                   (*updates.values(), directive_id))
    return get_directive(db_path, directive_id)


def bump_directive_revision(db_path=None, directive_id: str = "") -> Dict[str, Any]:
    """Atomic amendment increment; returns the new revision and id."""
    with write_tx(db_path) as db:
        cur = db.execute("UPDATE agent_directives SET directive_revision=directive_revision+1, "
                         "status='amended', updated_at=? WHERE id=?",
                         (now_iso(), directive_id))
        if not cur.rowcount:
            raise RoomError("directive_missing", status=404)
        row = db.execute("SELECT directive_revision FROM agent_directives WHERE id=?",
                         (directive_id,)).fetchone()
    return {"directive_id": directive_id, "directive_revision": int(row[0])}


def get_amendment(db_path=None, amendment_id: str = "") -> Dict[str, Any]:
    initialize(db_path)
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM agent_amendments WHERE id=?", (amendment_id,)).fetchone()
    if not row:
        raise RoomError("amendment_missing", status=404)
    item = dict(row)
    item["held_task_ids"] = _json(item.pop("held_task_ids_json"), [])
    item["evaluation"] = _json(item.pop("evaluation_json"), None)
    return item


def update_amendment(db_path=None, amendment_id: str = "", **fields) -> Dict[str, Any]:
    allowed = {"status", "evaluation"}
    updates = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        column = "evaluation_json" if key == "evaluation" else key
        updates[column] = json.dumps(value, ensure_ascii=False) if column.endswith("_json") else value
    if not updates:
        return get_amendment(db_path, amendment_id)
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key}=?" for key in updates)
    with write_tx(db_path) as db:
        cur = db.execute(f"UPDATE agent_amendments SET {assignments} WHERE id=?",
                         (*updates.values(), amendment_id))
        if not cur.rowcount:
            raise RoomError("amendment_missing", status=404)
    return get_amendment(db_path, amendment_id)


def bind_session_to_project(db_path=None, session_id: str = "", project_id: str = "") -> Dict[str, Any]:
    """Single transaction: every table's pre-book rows adopt the new project id."""
    if not session_id or not project_id:
        raise RoomError("session_and_project_required")
    stamp = now_iso()
    counts = {}
    with write_tx(db_path) as db:
        for table in ("agent_directives", "agent_tasks", "agent_events", "agent_approvals"):
            cur = db.execute(f"UPDATE {table} SET project_id=? WHERE session_id=? AND project_id IS NULL",
                             (project_id, session_id))
            counts[table] = int(cur.rowcount or 0)
        event = None
        if any(counts.values()):
            event = _append_event_db(db, session_id=session_id, topic_id="default",
                                     project_id=project_id, directive_id=None, task_id=None,
                                     channel="chief_chat", sender_role="system", mentions=[],
                                     kind="project_bound", summary="已建书并绑定原开书对话",
                                     payload={"project_id": project_id}, created_at=stamp)
    return {"status": "bound", "session_id": session_id, "project_id": project_id,
            "updated": counts, "event": event}


def create_task(db_path=None, *, directive_id: str, session_id: str, project_id: Optional[str],
                role: str, title: str, tool_name: str, params: Optional[Dict[str, Any]] = None,
                depends_on: Optional[Sequence[str]] = None, status: str = "pending",
                wait_reason: str = "") -> Dict[str, Any]:
    task_id = new_id("tsk")
    stamp = now_iso()
    with write_tx(db_path) as db:
        db.execute(
            "INSERT INTO agent_tasks(id, directive_id, session_id, project_id, role, title, tool_name, "
            "params_json, depends_on_json, status, wait_reason, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, directive_id, session_id, project_id, role, title, tool_name,
             json.dumps(params or {}, ensure_ascii=False),
             json.dumps(list(depends_on or []), ensure_ascii=False), status, wait_reason,
             stamp, stamp),
        )
    return get_task(db_path, task_id)


def get_task(db_path=None, task_id: str = "") -> Dict[str, Any]:
    initialize(db_path)
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise RoomError("task_missing", status=404)
    item = dict(row)
    item["params"] = _json(item.pop("params_json"), {})
    item["depends_on"] = _json(item.pop("depends_on_json"), [])
    item["checkpoint"] = _json(item.pop("checkpoint_json"), None)
    item["artifact_ref"] = _json(item.pop("artifact_ref_json"), None)
    return item


def update_task(db_path=None, task_id: str = "", **fields) -> Dict[str, Any]:
    mapping = {"status": "status", "wait_reason": "wait_reason", "operation_id": "operation_id",
               "error": "error", "checkpoint": "checkpoint_json", "artifact_ref": "artifact_ref_json",
               "params": "params_json", "depends_on": "depends_on_json", "title": "title"}
    updates = {}
    for key, value in fields.items():
        column = mapping.get(key)
        if not column:
            continue
        updates[column] = json.dumps(value, ensure_ascii=False) if column.endswith("_json") and value is not None else value
    if not updates:
        return get_task(db_path, task_id)
    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key}=?" for key in updates)
    with write_tx(db_path) as db:
        db.execute(f"UPDATE agent_tasks SET {assignments} WHERE id=?", (*updates.values(), task_id))
    return get_task(db_path, task_id)


def list_tasks(db_path=None, *, project_id: Optional[str] = None,
               directive_id: Optional[str] = None, session_id: Optional[str] = None,
               active_only: bool = False, unbound_only: bool = False) -> List[Dict[str, Any]]:
    initialize(db_path)
    query = "SELECT * FROM agent_tasks"
    clauses, params = [], []
    if project_id:
        clauses.append("project_id=?"); params.append(project_id)
    elif unbound_only:
        clauses.append("project_id IS NULL")
    if directive_id:
        clauses.append("directive_id=?"); params.append(directive_id)
    if session_id:
        clauses.append("session_id=?"); params.append(session_id)
    if active_only:
        clauses.append("status IN ('pending','waiting','running','held','awaiting_approval','paused_budget')")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at"
    with connect(db_path) as db:
        rows = [dict(row) for row in db.execute(query, tuple(params))]
    result = []
    for item in rows:
        item["params"] = _json(item.pop("params_json"), {})
        item["depends_on"] = _json(item.pop("depends_on_json"), [])
        item["checkpoint"] = _json(item.pop("checkpoint_json"), None)
        item["artifact_ref"] = _json(item.pop("artifact_ref_json"), None)
        result.append(item)
    return result


def _append_event_db(db, *, session_id: str, topic_id: str, project_id: Optional[str],
                     directive_id: Optional[str], task_id: Optional[str], channel: str,
                     sender_role: str, mentions: Sequence[str], kind: str, summary: str,
                     payload: Dict[str, Any], created_at: str) -> Dict[str, Any]:
    event_id = new_id("evt")
    cur = db.execute(
        "INSERT INTO agent_events(event_id, session_id, topic_id, project_id, directive_id, task_id, "
        "channel, sender_role, mentions_json, kind, summary, payload_json, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, session_id, topic_id or "default", project_id, directive_id, task_id,
         channel, sender_role, json.dumps(list(mentions or []), ensure_ascii=False), kind,
         str(summary)[:4000], json.dumps(payload or {}, ensure_ascii=False), created_at),
    )
    seq = int(cur.lastrowid)
    return {"seq": seq, "event_id": event_id, "session_id": session_id, "topic_id": topic_id or "default",
            "project_id": project_id, "directive_id": directive_id, "task_id": task_id,
            "channel": channel, "sender_role": sender_role, "mentions": list(mentions or []),
            "kind": kind, "summary": summary, "payload": payload, "created_at": created_at}


def append_event(db_path=None, *, session_id: str, topic_id: str = "default",
                 project_id: Optional[str] = None, directive_id: Optional[str] = None,
                 task_id: Optional[str] = None, channel: str = "chief_chat",
                 sender_role: str = "system", mentions: Optional[Sequence[str]] = None,
                 kind: str = "text", summary: str = "", payload: Optional[Dict[str, Any]] = None,
                 created_at: Optional[str] = None) -> Dict[str, Any]:
    if channel not in CHANNELS:
        raise RoomError("invalid_channel")
    initialize(db_path)
    with write_tx(db_path) as db:
        event = _append_event_db(db, session_id=session_id, topic_id=topic_id, project_id=project_id,
                                 directive_id=directive_id, task_id=task_id, channel=channel,
                                 sender_role=sender_role, mentions=list(mentions or []), kind=kind,
                                 summary=summary, payload=payload or {},
                                 created_at=created_at or now_iso())
    broadcaster.publish(event)
    return event


def events_after(db_path=None, *, after_seq: int = 0, project_id: Optional[str] = None,
                 session_id: Optional[str] = None, topic_id: Optional[str] = None,
                 limit: int = 200) -> List[Dict[str, Any]]:
    initialize(db_path)
    clauses = ["seq > ?"]
    params: List[Any] = [int(after_seq)]
    if project_id:
        clauses.append("project_id=?"); params.append(project_id)
    if session_id:
        clauses.append("session_id=?"); params.append(session_id)
    if topic_id:
        clauses.append("topic_id=?"); params.append(topic_id)
    query = "SELECT * FROM agent_events WHERE " + " AND ".join(clauses) + " ORDER BY seq LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with connect(db_path) as db:
        rows = [dict(row) for row in db.execute(query, tuple(params))]
    for item in rows:
        item["mentions"] = _json(item.pop("mentions_json"), [])
        item["payload"] = _json(item.pop("payload_json"), {})
    return rows


def max_seq(db_path=None, *, project_id: Optional[str] = None, session_id: Optional[str] = None) -> int:
    initialize(db_path)
    clause, params = "", ()
    if project_id:
        clause, params = " WHERE project_id=?", (project_id,)
    elif session_id:
        clause, params = " WHERE session_id=?", (session_id,)
    with connect(db_path) as db:
        row = db.execute("SELECT COALESCE(MAX(seq),0) FROM agent_events" + clause, params).fetchone()
    return int(row[0])


def create_approval(db_path=None, *, session_id: str, project_id: Optional[str], directive_id: Optional[str],
                    directive_revision: int, task_id: Optional[str], kind: str, title: str,
                    artifact_fingerprint: str, approved_scope_hash: str, detail: Dict[str, Any],
                    ttl_minutes: int = 120) -> Dict[str, Any]:
    approval_id = new_id("apr")
    expires = (datetime.now(timezone.utc) + timedelta(minutes=int(ttl_minutes))).isoformat()
    stamp = now_iso()
    with write_tx(db_path) as db:
        db.execute(
            "INSERT INTO agent_approvals(id, session_id, project_id, directive_id, directive_revision, "
            "task_id, kind, title, artifact_fingerprint, approved_scope_hash, expires_at, detail_json, "
            "status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (approval_id, session_id, project_id, directive_id, int(directive_revision), task_id,
             kind, title, artifact_fingerprint, approved_scope_hash, expires, json.dumps(detail, ensure_ascii=False),
             "pending", stamp),
        )
    return get_approval(db_path, approval_id)


def get_approval(db_path=None, approval_id: str = "") -> Dict[str, Any]:
    initialize(db_path)
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM agent_approvals WHERE id=?", (approval_id,)).fetchone()
    if not row:
        raise RoomError("approval_missing", status=404)
    item = dict(row)
    item["detail"] = _json(item.pop("detail_json"), {})
    item["decision"] = _json(item.pop("decision_json"), None)
    return item


def resolve_approval(db_path=None, approval_id: str = "", *, approved: bool,
                     artifact_fingerprint: str, approved_scope_hash: str,
                     directive_revision: Optional[int] = None, resolved_by: str = "author",
                     decision: Optional[Dict[str, Any]] = None, now: Optional[str] = None) -> Dict[str, Any]:
    """Five checks then atomic consumption; replay/expired/stale is 409."""
    stamp = now or now_iso()
    if resolved_by != "author":
        raise RoomError("agents_cannot_approve", status=403)
    if not str(artifact_fingerprint or "").strip() or not str(approved_scope_hash or "").strip():
        # The caller must echo the card's binding fields; server defaults made
        # the three binding checks compare stored==stored (B-03).
        raise RoomError("approval_binding_required", status=400)
    expired = False
    with write_tx(db_path) as db:
        row = db.execute("SELECT * FROM agent_approvals WHERE id=?", (approval_id,)).fetchone()
        if not row:
            raise RoomError("approval_missing", status=404)
        item = dict(row)
        if item["status"] != "pending":
            raise RoomError("approval_not_pending", status=409)
        if item.get("expires_at") and str(item["expires_at"]) < stamp:
            db.execute("UPDATE agent_approvals SET status='expired', resolved_at=? WHERE id=?",
                       (stamp, approval_id))
            expired = True
        if expired:
            pass
        elif directive_revision is not None and int(directive_revision) != int(item.get("directive_revision") or 0):
            raise RoomError("approval_directive_revision_stale", status=409)
        elif artifact_fingerprint != item.get("artifact_fingerprint"):
            raise RoomError("approval_artifact_changed", status=409)
        elif approved_scope_hash != item.get("approved_scope_hash"):
            raise RoomError("approval_scope_mismatch", status=409)
        else:
            db.execute("UPDATE agent_approvals SET status=?, resolved_by=?, decision_json=?, resolved_at=? "
                       "WHERE id=? AND status='pending'",
                       ("approved" if approved else "rejected", resolved_by,
                        json.dumps(decision or {}, ensure_ascii=False), stamp, approval_id))
    if expired:
        raise RoomError("approval_expired", status=409)
    return get_approval(db_path, approval_id)


def pending_approvals(db_path=None, *, project_id: Optional[str] = None,
                      session_id: Optional[str] = None,
                      status: Optional[str] = "pending",
                      unbound_only: bool = False) -> List[Dict[str, Any]]:
    initialize(db_path)
    clauses = ["status=?"]
    params: List[Any] = [str(status or "pending")]
    if project_id:
        clauses.append("project_id=?"); params.append(project_id)
    elif unbound_only:
        clauses.append("project_id IS NULL")
    if session_id:
        clauses.append("session_id=?"); params.append(session_id)
    with connect(db_path) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM agent_approvals WHERE " + " AND ".join(clauses) + " ORDER BY created_at", tuple(params))]
    for item in rows:
        item["detail"] = _json(item.pop("detail_json"), {})
        item["decision"] = _json(item.pop("decision_json"), None)
    return rows


def new_topic(db_path=None, *, project_id: str) -> Dict[str, Any]:
    return {"topic_id": new_id("topic"), "project_id": project_id, "created_at": now_iso()}


def chat_context(db_path=None, *, project_id: str, topic_id: str = "default",
                 limit: int = 8, char_limit: int = 12000) -> List[Dict[str, Any]]:
    """Sliding window: newest K rounds under this topic, bounded by chars."""
    initialize(db_path)
    with connect(db_path) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM agent_events WHERE project_id=? AND topic_id=? AND channel='chief_chat' "
            "ORDER BY seq DESC LIMIT ?", (project_id, topic_id, max(1, int(limit) * 2)))]
    rows.reverse()
    picked, size = [], 0
    for item in reversed(rows):
        text = str(item.get("summary") or "")
        if size + len(text) > char_limit:
            continue
        picked.append({"seq": item["seq"], "role": item["sender_role"], "kind": item["kind"],
                       "summary": text, "payload": _json(item.get("payload_json"), {})})
        size += len(text)
    picked.reverse()
    return picked


def snapshot(db_path=None, *, project_id: Optional[str] = None,
             session_id: Optional[str] = None, topic_id: Optional[str] = None,
             limit: int = 100) -> Dict[str, Any]:
    """Room state scoped to one book, or to an unbound session before a book exists.

    A session id is shared by every book ("author"), so a session-only snapshot
    must never aggregate other books' events/directives/tasks/approvals (B-05).
    """
    initialize(db_path)
    if not project_id and not session_id:
        raise RoomError("project_or_session_required")
    clauses, params = [], []
    if project_id:
        clauses.append("project_id=?"); params.append(project_id)
        if session_id:
            clauses.append("session_id=?"); params.append(session_id)
    elif session_id:
        clauses.append("session_id=?"); params.append(session_id)
        clauses.append("project_id IS NULL")
    if topic_id:
        clauses.append("topic_id=?"); params.append(topic_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as db:
        if project_id:
            row = db.execute("SELECT COALESCE(MAX(seq),0) FROM agent_events WHERE project_id=?",
                             (project_id,)).fetchone()
        elif session_id:
            row = db.execute("SELECT COALESCE(MAX(seq),0) FROM agent_events "
                             "WHERE session_id=? AND project_id IS NULL", (session_id,)).fetchone()
        else:
            row = db.execute("SELECT COALESCE(MAX(seq),0) FROM agent_events").fetchone()
        seq = int(row[0])
        events = [dict(row) for row in db.execute(
            "SELECT * FROM agent_events" + where + " ORDER BY seq DESC LIMIT ?",
            (*params, max(1, min(int(limit), 500))))]
    events.reverse()
    for item in events:
        item["mentions"] = _json(item.pop("mentions_json"), [])
        item["payload"] = _json(item.pop("payload_json"), {})
    directives, tasks = [], []
    with connect(db_path) as db:
        if project_id:
            directives = [dict(row) for row in db.execute(
                "SELECT * FROM agent_directives WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
                (project_id,))]
        elif session_id:
            directives = [dict(row) for row in db.execute(
                "SELECT * FROM agent_directives WHERE session_id=? AND project_id IS NULL "
                "ORDER BY created_at DESC LIMIT 20", (session_id,))]
        for item in directives:
            item["constraints"] = _json(item.pop("constraints_json"), [])
    tasks = list_tasks(db_path, project_id=project_id, session_id=session_id, active_only=True,
                       unbound_only=not bool(project_id))
    return {"snapshot_seq": seq, "events": events, "directives": directives,
            "tasks": tasks, "approvals": pending_approvals(
                db_path, project_id=project_id, session_id=session_id,
                unbound_only=not bool(project_id)),
            "project_id": project_id, "session_id": session_id,
            "topic_id": topic_id}


# --------------------------------------------------------------- broadcaster

class BoundedBroadcaster:
    """In-memory fan-out for transient frames, with a hard 256-slot per client.

    Persistent event types are durable in ``agent_events`` and can always be
    replayed by ``seq``; when a slow client overflows, the broadcaster sends
    one ``resync_required`` marker and unsubscribes it instead of buffering
    unbounded memory.
    """

    def __init__(self, maxsize: int = 256):
        self.maxsize = int(maxsize)
        self._subscribers: Dict[str, Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = {}
        self._filters: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self._last_seq: Dict[str, int] = {}
        self._closed: set = set()
        self._lock = threading.RLock()

    def subscribe(self, loop: Optional[asyncio.AbstractEventLoop] = None,
                  *, project_id: Optional[str] = None,
                  session_id: Optional[str] = None) -> Tuple[str, asyncio.Queue]:
        loop = loop or asyncio.get_running_loop()
        token = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        with self._lock:
            self._closed.discard(token)
            self._subscribers[token] = (loop, queue)
            self._filters[token] = (project_id, session_id)
            self._last_seq[token] = 0
        return token, queue

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._closed.add(token)
            self._subscribers.pop(token, None)
            self._filters.pop(token, None)
            self._last_seq.pop(token, None)

    def ack(self, token: str, seq: int) -> None:
        """Record a frame that the SSE generator actually yielded.

        The queue can be drained before a slow consumer reads it; only an ack
        from the generator proves delivery, so a resync marker must never use
        the last enqueue seq (B-14R-1).
        """
        if not isinstance(seq, int) or seq <= 0:
            return
        with self._lock:
            if token not in self._closed and token in self._subscribers:
                self._last_seq[token] = max(self._last_seq.get(token, 0), int(seq))

    def publish(self, event: Dict[str, Any]) -> int:
        dropped = 0
        with self._lock:
            items = list(self._subscribers.items())
        event_project = event.get("project_id")
        event_session = str(event.get("session_id") or "")
        for token, (loop, queue) in items:
            with self._lock:
                want_project, want_session = self._filters.get(token, (None, None))
            if want_project:
                # A book stream only sees that book; a NULL-project event is
                # never broadcast into every book (B-05).
                if event_project != want_project:
                    continue
            elif want_session:
                # A pre-book session sees only its own unbound events.
                if event_project is not None or event_session != want_session:
                    continue
            def put(event=event, queue=queue, token=token):
                with self._lock:
                    if token in self._closed:
                        return
                try:
                    queue.put_nowait(event)
                    # Do not advance the delivered cursor on enqueue: a later
                    # overflow can drain queued frames before the generator
                    # yields them.  Only ack() after a successful yield moves it.
                    return
                except asyncio.QueueFull:
                    pass
                if event.get("kind") not in TRANSIENT_KINDS:
                    # Persistent frame overflow: force a clean resync from the
                    # last frame actually delivered, never from the newest seq
                    # that overflowed the client (B-14/C-42).
                    with self._lock:
                        last = self._last_seq.get(token, 0)
                    try:
                        while not queue.empty():
                            queue.get_nowait()
                        queue.put_nowait({"kind": "resync_required", "channel": "system",
                                          "summary": "连接积压，需重新同步", "seq": last,
                                          "full_reload": True, "resync_required": True})
                    except Exception:
                        pass
                    self.unsubscribe(token)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:
                self.unsubscribe(token)
                dropped += 1
        return dropped

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


broadcaster = BoundedBroadcaster()
