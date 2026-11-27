"""Project-level ``.webnovel/workbench.sqlite3`` (WAL) access layer.

All *new* mutable workbench state lives in one SQLite database per project:

* live chapter drafts (``chapter_drafts``) and permanent ``chapter_uid`` records;
* annotations, hunk states, patch ledger and whole-book directives;
* ``idempotency_keys`` for every LLM-billed / mutating entry point;
* world-state facts, manual cards, context manifests and the FTS5 2-gram index.

Text files (``正文/*.md``, ``大纲/*.md``, ``设定/*.md``, ``chapter_versions``)
stay human readable and byte-compatible with v0.7.5.  This module never writes
them; cross-file commits go through :mod:`integration.transaction_journal`.

Design constraints (see ``docs/plans/v0.8-v0.9/05``):

* no new third-party dependency; stdlib ``sqlite3`` only;
* every connection enables ``journal_mode=WAL``, ``busy_timeout=15000``,
  ``synchronous=NORMAL`` and ``foreign_keys=ON``;
* write transactions use ``BEGIN IMMEDIATE`` with bounded jitter retry so a
  dozen worker processes never surface ``SQLITE_BUSY`` to the API;
* existing v0.7.5 tables (``projects`` / ``operations`` / ``settings`` /
  ``request_budget`` / ``usage_events``) are never altered here — this is a
  different database file.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

SCHEMA_VERSION = 2
DB_NAME = "workbench.sqlite3"

_WRITE_RETRY_ATTEMPTS = 5
_WRITE_RETRY_BASE = 0.05
_LOCK_ERRORS = ("database is locked", "database table is locked", "database is busy")

_LOCAL = threading.local()

_REQUIRED_TABLES = {"chapter_drafts", "chapter_meta", "annotations", "annotation_hunks",
                    "patch_ledger", "world_facts", "quality_reviews", "task_queue",
                    "artifact_refs"}


def _tx_stack() -> List[Dict[str, Any]]:
    stack = getattr(_LOCAL, "tx_stack", None)
    if stack is None:
        stack = _LOCAL.tx_stack = []
    return stack


def _tx_key(project) -> str:
    path = db_path(project)
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _active_frame(project) -> Optional[Dict[str, Any]]:
    """The current thread's open write transaction for this exact database."""
    key = _tx_key(project)
    for frame in reversed(_tx_stack()):
        if frame["key"] == key:
            return frame
    return None


def _note_sqlite_enter() -> None:
    try:
        from integration import lock_manager
    except Exception:  # pragma: no cover - standalone import without package
        return
    lock_manager.note_sqlite_enter()


def _note_sqlite_exit() -> None:
    try:
        from integration import lock_manager
    except Exception:  # pragma: no cover
        return
    lock_manager.note_sqlite_exit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def db_path(project) -> Path:
    return Path(project) / ".webnovel" / DB_NAME


def _is_busy(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and any(token in text for token in _LOCK_ERRORS)


def _backoff(attempt: int) -> None:
    delay = _WRITE_RETRY_BASE * (2 ** attempt)
    time.sleep(delay + random.random() * _WRITE_RETRY_BASE)


@contextmanager
def connect(project, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """Open one configured connection; never share a connection across threads."""
    path = db_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=15.0, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        for attempt in range(_WRITE_RETRY_ATTEMPTS):
            try:
                db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if not _is_busy(exc) or attempt == _WRITE_RETRY_ATTEMPTS - 1:
                    raise
                _backoff(attempt)
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA foreign_keys=ON")
        if readonly:
            db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


@contextmanager
def write_tx(project) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` transaction with bounded jitter retry.

    Re-entrant for the same thread + database: a nested ``write_tx`` opens a
    ``SAVEPOINT`` on the outer connection.  SQLite does not recognise two
    connections from one thread as one transaction; opening a second
    ``BEGIN IMMEDIATE`` here used to self-deadlock for the full busy timeout
    (audit C-02: quality review / chapter annotations on imported books).

    Never call this while holding an OS file lock: the two lock layers are
    strictly serial (plan ``03`` §1.2, iron rule A).  ``lock_manager`` is
    notified so an OS lock taken inside a write transaction is rejected
    instead of silently violating the ordering (audit C-04).
    """
    frame = _active_frame(project)
    if frame is not None:
        depth = int(frame["depth"]) + 1
        frame["depth"] = depth
        name = f"wb_nested_{depth}"
        db = frame["db"]
        _note_sqlite_enter()
        db.execute(f"SAVEPOINT {name}")
        try:
            yield db
        except BaseException:
            try:
                db.execute(f"ROLLBACK TO {name}")
                db.execute(f"RELEASE {name}")
            except sqlite3.Error:
                pass
            raise
        else:
            try:
                db.execute(f"RELEASE {name}")
            except sqlite3.Error:
                try:
                    db.execute(f"ROLLBACK TO {name}")
                    db.execute(f"RELEASE {name}")
                except sqlite3.Error:
                    pass
                raise
        finally:
            frame["depth"] = depth - 1
            _note_sqlite_exit()
        return
    with connect(project) as db:
        for attempt in range(_WRITE_RETRY_ATTEMPTS):
            try:
                db.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                if not _is_busy(exc) or attempt == _WRITE_RETRY_ATTEMPTS - 1:
                    raise
                _backoff(attempt)
        stack = _tx_stack()
        stack.append({"key": _tx_key(project), "db": db, "depth": 0})
        _note_sqlite_enter()
        try:
            yield db
        except BaseException:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        else:
            for attempt in range(_WRITE_RETRY_ATTEMPTS):
                try:
                    db.execute("COMMIT")
                    break
                except sqlite3.OperationalError as exc:
                    if not _is_busy(exc) or attempt == _WRITE_RETRY_ATTEMPTS - 1:
                        try:
                            db.execute("ROLLBACK")
                        except sqlite3.Error:
                            pass
                        raise
                    _backoff(attempt)
        finally:
            stack.pop()
            _note_sqlite_exit()


def retry_write(fn, *args, **kwargs):
    """Run ``fn`` again only for transient SQLITE_BUSY/LOCKED errors."""
    for attempt in range(_WRITE_RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if not _is_busy(exc) or attempt == _WRITE_RETRY_ATTEMPTS - 1:
                raise
            _backoff(attempt)


SCHEMA = """
CREATE TABLE IF NOT EXISTS workbench_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapter_meta (
    chapter_id INTEGER PRIMARY KEY,
    chapter_uid TEXT NOT NULL UNIQUE,
    draft_epoch INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapter_drafts (
    chapter_id INTEGER PRIMARY KEY,
    draft_id TEXT NOT NULL UNIQUE,
    chapter_uid TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    draft_epoch INTEGER NOT NULL,
    draft_revision INTEGER NOT NULL,
    base_version_id TEXT,
    base_content_sha256 TEXT,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    cursor_json TEXT NOT NULL DEFAULT '{}',
    dirty INTEGER NOT NULL DEFAULT 1,
    client_session_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    actor TEXT NOT NULL,
    project_id TEXT NOT NULL,
    action TEXT NOT NULL,
    op_id TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    operation_id TEXT,
    response_json TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (actor, project_id, action, op_id)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expiry ON idempotency_keys(expires_at);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    chapter_id INTEGER NOT NULL,
    chapter_uid TEXT NOT NULL,
    scope TEXT NOT NULL,
    anchor_json TEXT,
    instruction TEXT NOT NULL,
    edit_policy TEXT NOT NULL DEFAULT 'strict_selection',
    variants_requested INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    annotation_revision INTEGER NOT NULL DEFAULT 1,
    conflict_with_json TEXT NOT NULL DEFAULT '[]',
    candidate_ids_json TEXT NOT NULL DEFAULT '[]',
    thread_json TEXT NOT NULL DEFAULT '[]',
    group_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_annotations_chapter ON annotations(chapter_id, status);

CREATE TABLE IF NOT EXISTS annotation_hunks (
    id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL,
    preview_id TEXT,
    candidate_id TEXT,
    group_id TEXT,
    chapter_id INTEGER NOT NULL,
    chapter_uid TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    before_text TEXT NOT NULL DEFAULT '',
    after_text TEXT NOT NULL DEFAULT '',
    char_start INTEGER,
    char_end INTEGER,
    applied_draft_id TEXT,
    applied_draft_revision INTEGER,
    applied_range_json TEXT,
    applied_text_sha256 TEXT,
    custom_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hunks_annotation ON annotation_hunks(annotation_id, status);
CREATE INDEX IF NOT EXISTS idx_hunks_preview ON annotation_hunks(preview_id);

CREATE TABLE IF NOT EXISTS patch_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL,
    chapter_uid TEXT NOT NULL,
    preview_id TEXT,
    hunk_id TEXT,
    annotation_id TEXT,
    draft_id TEXT,
    draft_revision INTEGER,
    applied_range_json TEXT,
    before_quote TEXT,
    applied_text TEXT,
    custom INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patch_ledger_chapter ON patch_ledger(chapter_id, id);

CREATE TABLE IF NOT EXISTS preview_index (
    preview_id TEXT PRIMARY KEY,
    chapter_id INTEGER NOT NULL,
    chapter_uid TEXT NOT NULL,
    group_id TEXT,
    annotation_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    base_snapshot_id TEXT,
    base_version_id TEXT,
    artifacts_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS book_directives (
    id TEXT PRIMARY KEY,
    instruction TEXT NOT NULL,
    directive_id TEXT,
    effective_from_chapter INTEGER,
    exceptions_json TEXT NOT NULL DEFAULT '[]',
    apply_to_existing INTEGER NOT NULL DEFAULT 0,
    apply_as_future_rule INTEGER NOT NULL DEFAULT 0,
    future_rule_memory_id TEXT,
    scan_state TEXT NOT NULL DEFAULT 'scanning',
    affected_json TEXT NOT NULL DEFAULT '[]',
    estimated_calls INTEGER NOT NULL DEFAULT 0,
    rule_content_sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS directive_exemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL,
    chapter_uid TEXT NOT NULL,
    version_id TEXT,
    content_sha256 TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_content_sha256 TEXT NOT NULL,
    scan_method TEXT NOT NULL DEFAULT 'keyword_only',
    confirmed_by TEXT NOT NULL DEFAULT 'author',
    verified_at TEXT NOT NULL,
    UNIQUE(chapter_id, rule_id)
);

CREATE TABLE IF NOT EXISTS world_facts (
    fact_id TEXT PRIMARY KEY,
    entity_id TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    domain TEXT NOT NULL,
    assertion_type TEXT NOT NULL DEFAULT 'fact',
    subject TEXT NOT NULL DEFAULT '',
    predicate TEXT NOT NULL DEFAULT '',
    object TEXT NOT NULL DEFAULT '',
    story_time TEXT,
    narrative_chapter INTEGER,
    valid_from_chapter INTEGER,
    valid_until_chapter INTEGER,
    effective_from_chapter INTEGER,
    exceptions_json TEXT NOT NULL DEFAULT '[]',
    source_chapter INTEGER,
    source_chapter_uid TEXT,
    source_version_id TEXT,
    source_quote TEXT,
    authority_level TEXT NOT NULL DEFAULT 'ai_inferred',
    confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    author_locked INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_facts_entity ON world_facts(entity_id, status);
CREATE INDEX IF NOT EXISTS idx_world_facts_chapter ON world_facts(narrative_chapter, status);

CREATE TABLE IF NOT EXISTS world_entities (
    entity_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'character',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    pinned INTEGER NOT NULL DEFAULT 0,
    story_time TEXT,
    card_md TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_manifests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER,
    operation_id TEXT,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conflict_ignores (
    fact_id TEXT NOT NULL,
    chapter_uid TEXT NOT NULL,
    version_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT 'intentional_or_flashback',
    created_at TEXT NOT NULL,
    PRIMARY KEY (fact_id, chapter_uid, version_id)
);

CREATE TABLE IF NOT EXISTS rule_versions (
    rule_id TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    content TEXT NOT NULL,
    effective_from_chapter INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_docs (
    doc_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    chapter_id INTEGER,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    content_sha256 TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    doc_key UNINDEXED,
    tokens,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS drafts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL,
    draft_id TEXT NOT NULL,
    draft_epoch INTEGER NOT NULL,
    draft_revision INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_queue (
    task_id TEXT PRIMARY KEY,
    chapter_id INTEGER,
    priority TEXT NOT NULL,
    state TEXT NOT NULL,
    parent_task_id TEXT,
    blocked_by_json TEXT NOT NULL DEFAULT '[]',
    hold_amendment_id TEXT,
    amendment_fallback TEXT NOT NULL DEFAULT 'wait',
    lease_owner TEXT,
    lease_expires REAL,
    committing INTEGER NOT NULL DEFAULT 0,
    hold_requested INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_queue_ready ON task_queue(state, priority, created_at);
CREATE TABLE IF NOT EXISTS task_pauses (
    scope TEXT PRIMARY KEY,
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    kind TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL,
    chapter_uid TEXT,
    version_id TEXT,
    reviewer TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    total REAL NOT NULL,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_chapter ON quality_reviews(chapter_id, id);
CREATE TABLE IF NOT EXISTS artifact_refs (
    artifact_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref_count INTEGER NOT NULL DEFAULT 0,
    bytes INTEGER NOT NULL DEFAULT 0,
    protected INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _schema_statements() -> List[str]:
    return [part.strip() for part in SCHEMA.split(";") if part.strip()]


def _table_names(db: sqlite3.Connection) -> set:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _schema_current(db: sqlite3.Connection) -> bool:
    """True when the schema version and every required table are present."""
    try:
        row = db.execute("SELECT value FROM workbench_meta WHERE key='schema_version'").fetchone()
    except sqlite3.Error:
        return False
    if not row or str(row[0]) != str(SCHEMA_VERSION):
        return False
    if not _REQUIRED_TABLES.issubset(_table_names(db)):
        return False
    # 列级检查：旧库即使版本号被手工改高，也必须在 _apply_schema 里补列。
    columns = {item[1] for item in db.execute("PRAGMA table_info(task_queue)")}
    return "hold_requested" in columns


def _migrate_columns(db: sqlite3.Connection) -> None:
    """Additive migrations for databases created by an earlier build."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(task_queue)")}
    if "hold_requested" not in columns:
        try:
            db.execute("ALTER TABLE task_queue ADD COLUMN hold_requested INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError as exc:
            # 两个进程同时升级旧库时，后到者会看到 duplicate column；视为已完成。
            if "duplicate column" not in str(exc).lower():
                raise


def _apply_schema(db: sqlite3.Connection) -> None:
    # ``executescript`` implicitly COMMITs an open transaction, which would
    # silently commit the outer tx when initialize() runs in a nested call.
    for statement in _schema_statements():
        db.execute(statement)
    db.execute(
        "INSERT INTO workbench_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    db.execute(
        "INSERT OR IGNORE INTO workbench_meta(key, value) VALUES('commit_generation', '0')"
    )
    _migrate_columns(db)


def initialize(project) -> Path:
    """Create the database and all tables; idempotent and safe on old books.

    A schema check runs first so read-heavy callers (``ws.state()`` opens six
    connections per request) no longer take a write lock every time.  When the
    thread already has a write transaction open, the schema statements run on
    that connection instead of a second one.
    """
    path = db_path(project)
    frame = _active_frame(project)
    if frame is not None:
        _apply_schema(frame["db"])
        return path
    with connect(project) as db:
        if _schema_current(db):
            return path
    # 升级旧库需要写锁；放进 BEGIN IMMEDIATE 里串行化，避免两个进程同时
    # ALTER TABLE 造成 duplicate column。拿到锁后重新检查一次。
    with write_tx(project) as db:
        if _schema_current(db):
            return path
        _apply_schema(db)
    return path


def _ensure(project) -> None:
    frame = _active_frame(project)
    if frame is not None:
        if not _schema_current(frame["db"]):
            initialize(project)
        return
    if not db_path(project).exists():
        initialize(project)
        return
    # Cheap integrity check: older DBs may miss a table or a column added later.
    with connect(project) as db:
        current = _schema_current(db)
    if not current:
        initialize(project)


def _meta(project, key: str, default: Optional[str] = None) -> Optional[str]:
    _ensure(project)
    with connect(project) as db:
        row = db.execute("SELECT value FROM workbench_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def commit_generation(project) -> int:
    return int(_meta(project, "commit_generation", "0") or 0)


def bump_commit_generation(project) -> int:
    _ensure(project)
    with write_tx(project) as db:
        db.execute(
            "INSERT INTO workbench_meta(key, value) VALUES('commit_generation', '1') "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT)"
        )
        row = db.execute("SELECT value FROM workbench_meta WHERE key='commit_generation'").fetchone()
    return int(row[0])


# --------------------------------------------------------------------- chapters

def ensure_chapter_meta(project, chapter: int) -> Dict[str, Any]:
    """Return (and lazily create) the permanent ``chapter_uid`` for a chapter."""
    chapter = int(chapter)
    if chapter <= 0:
        raise ValueError("chapter_number_invalid")
    _ensure(project)
    with connect(project) as db:
        row = db.execute("SELECT * FROM chapter_meta WHERE chapter_id=?", (chapter,)).fetchone()
    if row:
        return dict(row)
    stamp = now_iso()
    uid = new_id("chuid")
    with write_tx(project) as db:
        db.execute(
            "INSERT OR IGNORE INTO chapter_meta(chapter_id, chapter_uid, draft_epoch, created_at, updated_at) "
            "VALUES(?,?,0,?,?)",
            (chapter, uid, stamp, stamp),
        )
        row = db.execute("SELECT * FROM chapter_meta WHERE chapter_id=?", (chapter,)).fetchone()
    return dict(row)


def chapter_uid(project, chapter: int) -> str:
    return str(ensure_chapter_meta(project, chapter)["chapter_uid"])


def list_chapter_meta(project) -> List[Dict[str, Any]]:
    _ensure(project)
    with connect(project) as db:
        return [dict(r) for r in db.execute("SELECT * FROM chapter_meta ORDER BY chapter_id")]


# ----------------------------------------------------------------------- drafts

class DraftConflict(RuntimeError):
    """Raised when ``draft_id/epoch/revision`` do not match the server state."""

    def __init__(self, current: Optional[Dict[str, Any]] = None, *, code: str = "draft_conflict"):
        super().__init__(code)
        self.code = code
        self.current = current or {}


def draft_epoch(project, chapter: int) -> int:
    """Current anti-ABA epoch, available even when no draft row exists."""
    return int(ensure_chapter_meta(project, int(chapter)).get("draft_epoch") or 0)


def get_draft(project, chapter: int) -> Optional[Dict[str, Any]]:
    _ensure(project)
    with connect(project) as db:
        row = db.execute("SELECT * FROM chapter_drafts WHERE chapter_id=?", (int(chapter),)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["cursor"] = json.loads(item.pop("cursor_json") or "{}")
    except ValueError:
        item["cursor"] = {}
    item["dirty"] = bool(item.get("dirty"))
    return item


def save_draft(project, chapter: int, *, title: str, content: str,
               base_version_id: Optional[str] = None,
               base_content_sha256: Optional[str] = None,
               expected_draft_id: Optional[str] = None,
               expected_draft_epoch: int = 0,
               expected_draft_revision: int = 0,
               client_session_id: str = "", cursor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Serialized draft write with ABA protection.

    ``expected_draft_id`` must be ``None`` when no draft exists.  A mismatch in
    any of the three identity fields raises :class:`DraftConflict` and returns
    the current server draft, never silently overwriting the other device.
    """
    chapter = int(chapter)
    if chapter <= 0:
        raise ValueError("chapter_number_invalid")
    _ensure(project)
    stamp = now_iso()
    with write_tx(project) as db:
        meta_row = db.execute("SELECT * FROM chapter_meta WHERE chapter_id=?", (chapter,)).fetchone()
        if meta_row is None:
            db.execute("INSERT OR IGNORE INTO chapter_meta(chapter_id, chapter_uid, draft_epoch, "
                       "created_at, updated_at) VALUES(?,?,0,?,?)",
                       (chapter, new_id("chuid"), stamp, stamp))
            meta_row = db.execute("SELECT * FROM chapter_meta WHERE chapter_id=?", (chapter,)).fetchone()
        meta = dict(meta_row)
        row = db.execute("SELECT * FROM chapter_drafts WHERE chapter_id=?", (chapter,)).fetchone()
        current = dict(row) if row else None
        current_epoch = int(meta.get("draft_epoch") or 0)
        if current:
            if (str(expected_draft_id or "") != str(current["draft_id"])
                    or int(expected_draft_epoch) != int(current["draft_epoch"])
                    or int(expected_draft_revision) != int(current["draft_revision"])):
                raise DraftConflict(current)
            revision = int(current["draft_revision"]) + 1
            epoch = int(current["draft_epoch"])
            draft_id = str(current["draft_id"])
            # 后续自动保存通常不带 base_*；保留首次草稿建立的三方合并基线。
            if base_version_id is None:
                base_version_id = current.get("base_version_id")
            if base_content_sha256 is None:
                base_content_sha256 = current.get("base_content_sha256")
        else:
            if expected_draft_id not in (None, ""):
                raise DraftConflict(None)
            if int(expected_draft_epoch) != current_epoch or int(expected_draft_revision) != 0:
                raise DraftConflict(None)
            epoch = current_epoch + 1
            revision = 1
            draft_id = new_id("drf")
            db.execute("UPDATE chapter_meta SET draft_epoch=?, updated_at=? WHERE chapter_id=?",
                       (epoch, stamp, chapter))
        db.execute(
            "INSERT INTO chapter_drafts(chapter_id, draft_id, chapter_uid, chapter_number, draft_epoch, "
            "draft_revision, base_version_id, base_content_sha256, title, content, cursor_json, dirty, "
            "client_session_id, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(chapter_id) DO UPDATE SET draft_id=excluded.draft_id, "
            "draft_epoch=excluded.draft_epoch, draft_revision=excluded.draft_revision, "
            "base_version_id=excluded.base_version_id, base_content_sha256=excluded.base_content_sha256, "
            "title=excluded.title, content=excluded.content, cursor_json=excluded.cursor_json, "
            "dirty=excluded.dirty, client_session_id=excluded.client_session_id, updated_at=excluded.updated_at",
            (chapter, draft_id, meta["chapter_uid"], chapter, epoch, revision,
             base_version_id, base_content_sha256, str(title or ""), str(content or ""),
             json.dumps(cursor or {}, ensure_ascii=False), 1, str(client_session_id or ""), stamp),
        )
        db.execute(
            "INSERT INTO drafts_history(chapter_id, draft_id, draft_epoch, draft_revision, "
            "content_sha256, created_at) VALUES(?,?,?,?,?,?)",
            (chapter, draft_id, epoch, revision,
             hashlib.sha256(str(content or "").encode("utf-8")).hexdigest(), stamp),
        )
        snapshot = db.execute("SELECT * FROM chapter_drafts WHERE chapter_id=?", (chapter,)).fetchone()
    item = dict(snapshot)
    item["cursor"] = json.loads(item.pop("cursor_json") or "{}")
    item["dirty"] = bool(item.get("dirty"))
    return item


def clear_draft_if_matches(project, chapter: int, *, draft_id: str, draft_epoch: int,
                           draft_revision: int) -> Dict[str, Any]:
    """Delete a draft only when the exact submitted identity still matches.

    ``Ctrl+S`` followed by typing must not lose the newer draft: a revision
    that advanced in the meantime leaves the row untouched.
    """
    chapter = int(chapter)
    stamp = now_iso()
    _ensure(project)
    with write_tx(project) as db:
        row = db.execute("SELECT * FROM chapter_drafts WHERE chapter_id=?", (chapter,)).fetchone()
        if not row:
            return {"cleared": False, "draft_preserved": False, "current_draft_revision": 0}
        current = dict(row)
        if (str(current["draft_id"]) == str(draft_id)
                and int(current["draft_epoch"]) == int(draft_epoch)
                and int(current["draft_revision"]) == int(draft_revision)):
            db.execute("DELETE FROM chapter_drafts WHERE chapter_id=?", (chapter,))
            db.execute("UPDATE chapter_meta SET draft_epoch=?, updated_at=? WHERE chapter_id=?",
                       (int(current["draft_epoch"]) + 1, stamp, chapter))
            return {"cleared": True, "draft_preserved": False, "current_draft_revision": 0}
        return {"cleared": False, "draft_preserved": True,
                "current_draft_revision": int(current["draft_revision"]),
                "current_draft_id": str(current["draft_id"])}


def delete_draft(project, chapter: int, *, draft_id: Optional[str] = None) -> Dict[str, Any]:
    """Drop the active draft and advance ``draft_epoch`` (never reset to zero)."""
    chapter = int(chapter)
    stamp = now_iso()
    _ensure(project)
    with write_tx(project) as db:
        row = db.execute("SELECT * FROM chapter_drafts WHERE chapter_id=?", (chapter,)).fetchone()
        if not row:
            return {"deleted": False}
        current = dict(row)
        if draft_id and str(current["draft_id"]) != str(draft_id):
            raise DraftConflict(current)
        db.execute("DELETE FROM chapter_drafts WHERE chapter_id=?", (chapter,))
        db.execute("UPDATE chapter_meta SET draft_epoch=?, updated_at=? WHERE chapter_id=?",
                   (int(current["draft_epoch"]) + 1, stamp, chapter))
    return {"deleted": True, "draft_id": current["draft_id"],
            "draft_epoch": int(current["draft_epoch"]) + 1}


# ------------------------------------------------------------------ idempotency

def params_hash(params: Any) -> str:
    body = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def idempotency_begin(project, *, actor: str, project_id: str, action: str, op_id: str,
                      params: Any, operation_id: Optional[str] = None,
                      ttl_hours: int = 24) -> Dict[str, Any]:
    """Reserve an ``op_id`` or describe the existing attempt.

    Returns ``{"status": "new"|"in_progress"|"completed"|"failed"|"mismatch"}``.
    Completed responses are cached in ``response_json``; a params hash mismatch
    is always a hard 409 at the API layer (never someone else's result).
    """
    digest = params_hash(params)
    stamp = now_iso()
    _ensure(project)
    expires = datetime.fromtimestamp(
        time.time() + int(ttl_hours) * 3600, tz=timezone.utc
    ).isoformat()
    with write_tx(project) as db:
        row = db.execute(
            "SELECT * FROM idempotency_keys WHERE actor=? AND project_id=? AND action=? AND op_id=?",
            (actor, project_id, action, op_id),
        ).fetchone()
        if row:
            item = dict(row)
            if item["params_hash"] != digest:
                return {"status": "mismatch", "record": item}
            if item["state"] == "completed":
                return {"status": "completed", "record": item,
                        "response": json.loads(item["response_json"] or "null")}
            if item["state"] == "in_progress":
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(
                        str(item.get("created_at")).replace("Z", "+00:00"))).total_seconds()
                except ValueError:
                    age = 0
                if age < 600:
                    return {"status": "in_progress", "record": item}
                db.execute(
                    "UPDATE idempotency_keys SET params_hash=?, operation_id=?, response_json=NULL, "
                    "created_at=?, expires_at=? WHERE actor=? AND project_id=? AND action=? AND op_id=?",
                    (digest, operation_id, stamp, expires, actor, project_id, action, op_id),
                )
                return {"status": "failed_retry", "record": item}
            db.execute(
                "UPDATE idempotency_keys SET state='in_progress', params_hash=?, operation_id=?, "
                "response_json=NULL, created_at=?, expires_at=? "
                "WHERE actor=? AND project_id=? AND action=? AND op_id=?",
                (digest, operation_id, stamp, expires, actor, project_id, action, op_id),
            )
            return {"status": "failed_retry", "record": item}
        db.execute(
            "INSERT INTO idempotency_keys(actor, project_id, action, op_id, params_hash, state, "
            "operation_id, response_json, created_at, expires_at) VALUES(?,?,?,?,?,'in_progress',?,NULL,?,?)",
            (actor, project_id, action, op_id, digest, operation_id, stamp, expires),
        )
    return {"status": "new"}


def idempotency_complete(project, *, actor: str, project_id: str, action: str, op_id: str,
                         response: Any) -> None:
    with write_tx(project) as db:
        db.execute(
            "UPDATE idempotency_keys SET state='completed', response_json=? "
            "WHERE actor=? AND project_id=? AND action=? AND op_id=? AND state!='completed'",
            (json.dumps(response, ensure_ascii=False, default=str), actor, project_id, action, op_id),
        )


def idempotency_fail(project, *, actor: str, project_id: str, action: str, op_id: str) -> None:
    with write_tx(project) as db:
        db.execute(
            "UPDATE idempotency_keys SET state='failed' "
            "WHERE actor=? AND project_id=? AND action=? AND op_id=? AND state!='completed'",
            (actor, project_id, action, op_id),
        )


def idempotency_gc(project, *, now: Optional[str] = None) -> int:
    stamp = now or now_iso()
    _ensure(project)
    with write_tx(project) as db:
        cur = db.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (stamp,))
        return int(cur.rowcount or 0)


# -------------------------------------------------------------------- FTS index

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _cjk_runs(text: str) -> Iterable[Tuple[int, str]]:
    run: List[str] = []
    start = 0
    for index, ch in enumerate(text):
        code = ord(ch)
        if 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
            if not run:
                start = index
            run.append(ch)
        else:
            if run:
                yield start, "".join(run)
                run = []
    if run:
        yield start, "".join(run)


def tokenize(text: str) -> str:
    """Space separated CJK 2-gram + single chars + latin/number words.

    SQLite's built-in ``trigram`` tokenizer requires >=3 characters and thus
    returns zero hits for two-character Chinese names such as 林溪 or 老周.
    Indexing 2-grams *and* single characters under ``unicode61`` fixes that
    without any third-party dependency.
    """
    text = str(text or "")
    tokens: List[str] = []
    for _start, run in _cjk_runs(text):
        tokens.extend(run)
        tokens.extend(run[i:i + 2] for i in range(max(0, len(run) - 1)))
    tokens.extend(match.group(0).lower() for match in _TOKEN_RE.finditer(text)
                  if not (0x3400 <= ord(match.group(0)[0]) <= 0x9FFF))
    return " ".join(tokens)


def index_document(project, *, doc_key: str, kind: str, chapter_id: Optional[int],
                   title: str, content: str) -> None:
    digest = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
    stamp = now_iso()
    tokens = tokenize(f"{title}\n{content}")
    _ensure(project)
    with write_tx(project) as db:
        db.execute("DELETE FROM search_fts WHERE doc_key=?", (doc_key,))
        db.execute(
            "INSERT INTO search_docs(doc_key, kind, chapter_id, title, content, content_sha256, updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(doc_key) DO UPDATE SET kind=excluded.kind, "
            "chapter_id=excluded.chapter_id, title=excluded.title, content=excluded.content, "
            "content_sha256=excluded.content_sha256, updated_at=excluded.updated_at",
            (doc_key, kind, chapter_id, title, content, digest, stamp),
        )
        db.execute("INSERT INTO search_fts(doc_key, tokens) VALUES(?,?)", (doc_key, tokens))


def rebuild_search(project) -> int:
    """Rebuild the FTS mirror from authoritative ``search_docs`` rows."""
    _ensure(project)
    count = 0
    with write_tx(project) as db:
        db.execute("DELETE FROM search_fts")
        for row in db.execute("SELECT doc_key, title, content FROM search_docs"):
            db.execute("INSERT INTO search_fts(doc_key, tokens) VALUES(?,?)",
                       (row[0], tokenize(f"{row[1]}\n{row[2]}")))
            count += 1
    return count


def _search_needles(query: str) -> List[str]:
    """Meaningful terms for post-filtering: CJK 2-grams, latin words.

    ``tokenize`` indexes single characters *and* 2-grams so two-character
    names are findable at all; searching with every token OR-ed together would
    match a chapter that only contains 林 for the query 林溪.  The single
    characters remain indexed, but they are not required query terms.
    """
    needles: List[str] = []
    for token in tokenize(query).split():
        if len(token) >= 2 and token not in needles:
            needles.append(token)
    if not needles:
        raw = str(query or "").strip().casefold()
        if raw:
            needles = [raw]
    return needles


def _compact_cjk(text: str) -> str:
    """CJK/latin text with punctuation and whitespace removed.

    A query like ``林溪`` should still recall ``林，溪走进档案馆`` without
    weakening the requirement to a single character: FTS may match the
    indexed single characters, then this compact form verifies that every
    query character occurs in order once punctuation/whitespace is ignored.
    """
    return "".join(
        ch for ch in str(text or "").casefold()
        if ch.isalnum() or 0x3400 <= ord(ch) <= 0x9FFF or 0xF900 <= ord(ch) <= 0xFAFF
    )


def search(project, query: str, *, limit: int = 20, chapter: Optional[int] = None,
           max_chapter: Optional[int] = None) -> List[Dict[str, Any]]:
    """Deterministic local full-book search (0 model calls)."""
    terms = tokenize(query).split()
    if not terms:
        return []
    # Quote each token so FTS5 does not interpret punctuation as syntax.
    expr = " OR ".join('"' + term.replace('"', '""') + '"' for term in dict.fromkeys(terms))
    _ensure(project)
    needles = _search_needles(query)
    raw_limit = max(64, min(1000, int(limit) * 8))
    with connect(project) as db:
        exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_fts'"
        ).fetchone()
        if not exists:
            return []
        where = "search_fts MATCH ?"
        params: List[Any] = [expr]
        if chapter is not None:
            where += " AND (d.chapter_id IS NULL OR d.chapter_id=?)"
            params.append(int(chapter))
        elif max_chapter is not None:
            where += " AND (d.chapter_id IS NULL OR d.chapter_id<=?)"
            params.append(int(max_chapter))
        params.append(raw_limit)
        rows = db.execute(
            "SELECT d.doc_key, d.kind, d.chapter_id, d.title, d.content, d.updated_at, "
            "bm25(search_fts) AS rank FROM search_fts JOIN search_docs d ON d.doc_key=search_fts.doc_key "
            "WHERE " + where + " ORDER BY rank LIMIT ?",
            tuple(params),
        ).fetchall()
    matched = []
    folded_query = str(query or "").casefold()
    compact_query = _compact_cjk(query)
    for row in rows:
        item = dict(row)
        content = item["content"]
        haystack = content.casefold()
        # Require at least one meaningful term; otherwise a two-character
        # name degrades into "any chapter containing either character".
        # Punctuation inside a name ("林，溪") is ignored only after the FTS
        # candidate matched, so the two-character requirement still holds.
        compact_hit = bool(compact_query) and (
            compact_query in _compact_cjk(content) or compact_query in _compact_cjk(item["title"])
        )
        if needles and not compact_hit and not any(
            needle in haystack or needle in item["title"].casefold()
            for needle in needles
        ):
            continue
        exact = 1 if folded_query and folded_query in haystack else 0
        matched.append((exact, item))
    matched.sort(key=lambda entry: entry[0], reverse=True)
    results = []
    for _exact, item in matched[:max(1, int(limit))]:
        content = item.pop("content")
        index = content.find(query)
        if index < 0:
            haystack = content.casefold()
            index = haystack.find(str(query).casefold())
        if index < 0:
            needles = _search_needles(query)
            for needle in needles:
                index = content.casefold().find(needle)
                if index >= 0:
                    break
        if index < 0:
            index = 0
        item["snippet"] = content[max(0, index - 40): index + max(80, len(str(query)) + 40)].strip()
        item.pop("rank", None)
        results.append(item)
    return results


def drop_document(project, doc_key: str) -> None:
    _ensure(project)
    with write_tx(project) as db:
        db.execute("DELETE FROM search_fts WHERE doc_key=?", (doc_key,))
        db.execute("DELETE FROM search_docs WHERE doc_key=?", (doc_key,))


# ---------------------------------------------------------------------- utility

def table_counts(project) -> Dict[str, int]:
    _ensure(project)
    names = ["chapter_meta", "chapter_drafts", "annotations", "annotation_hunks",
             "patch_ledger", "idempotency_keys", "world_facts", "search_docs"]
    with connect(project) as db:
        return {name: int(db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in names}


def wal_size(project) -> int:
    path = db_path(project)
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += Path(str(path) + suffix).stat().st_size
        except OSError:
            pass
    return total


def checkpoint(project, *, truncate: bool = True) -> None:
    if not db_path(project).exists():
        return
    with connect(project) as db:
        db.execute(f"PRAGMA wal_checkpoint({'TRUNCATE' if truncate else 'PASSIVE'})")
