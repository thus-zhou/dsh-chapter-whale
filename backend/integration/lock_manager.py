"""八级锁序与分域短锁（v0.9 三期并发地基）。

规则只有三条，违反即抛稳定错误码：

1. 只能在较低的已持有级别之上申请更高级别；反向申请会死锁，直接拒绝。
2. SQLite 写事务打开期间绝不申请 OS 文件锁（先锁文件，再开事务）。
3. 分域 RMW 只持有本域锁，锁内不调用其他域的重活。

锁文件常驻不删除：删除 inode 会让两个进程同时“持有”同一把锁。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from fanqie_auto_publish import publication_safety as safety

LEVELS: Dict[str, int] = {
    "config": 1,
    "book_meta": 2,
    "volume_plan": 3,
    "chapter_text": 4,
    "derived_index": 5,
    "publication": 6,
    "agent_room": 7,
    "diagnostics": 8,
}
DOMAINS = ("chapter_text", "outline", "memory", "publication", "agent", "costs",
           "diagnostics", "config")
_STATE = threading.local()


class LockError(RuntimeError):
    def __init__(self, code: str, *, status: int = 409, detail: Optional[Dict] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


class LockOrderError(LockError):
    pass


class SqliteNestingError(LockError):
    pass


def _held() -> List[Tuple[int, str]]:
    stack = getattr(_STATE, "stack", None)
    if stack is None:
        stack = _STATE.stack = []
    return stack


def _sqlite_depth() -> int:
    return int(getattr(_STATE, "sqlite_depth", 0))


def note_sqlite_enter() -> None:
    _STATE.sqlite_depth = _sqlite_depth() + 1


def note_sqlite_exit() -> None:
    _STATE.sqlite_depth = max(0, _sqlite_depth() - 1)


def _project_key(project) -> str:
    try:
        target = str(Path(project).expanduser().resolve())
    except (OSError, RuntimeError):
        target = str(project or "")
    return hashlib.sha256(os.path.normcase(target).encode("utf-8")).hexdigest()[:16]


def lock_directory(project) -> Path:
    """Where this project's lock files live.

    审计 C3-05：旧实现把锁写进被审计项目的 ``.webnovel/locks``。一次
    dry-run GC 也会在只读书/归档书上留下永久锁文件并抛 PermissionError。
    锁因此移到管理器数据目录（``NOVEL_HELPER_MANAGER_DATA/locks``），没有
    数据目录时退到系统临时目录；项目路径只作为命名空间哈希。
    """
    override = os.getenv("NOVEL_HELPER_LOCK_DIR")
    if override:
        root = Path(override)
    else:
        # 固定使用系统临时目录下的同一命名空间：管理器与子进程即使环境变量
        # 不同也必须竞争同一把锁。项目路径只作为命名空间哈希。
        root = Path(tempfile.gettempdir()) / "novel-helper-locks"
    return root / _project_key(project)


def _lock_path(project, level: str, key: str) -> Path:
    digest = hashlib.sha256(f"{level}:{key}".encode("utf-8")).hexdigest()[:16]
    try:
        directory = lock_directory(project)
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # 只读项目/只读临时目录不能再变成 500；上层把 LockError 映射为 503。
        raise LockError("lock_unavailable", status=503,
                        detail={"level": level, "reason": type(exc).__name__}) from None
    return directory / f"L{LEVELS[level]}-{digest}.lock"


@contextmanager
def hold(project, level: str, key: str = "", *, timeout: float = 5.0):
    """Acquire one level; retries briefly so a short UI save does not 500.

    Only the *acquisition* is retried.  Once the lock is held, an exception
    raised by the caller inside the ``with`` block must propagate unchanged:
    catching ``PublicationBlocked`` around the ``yield`` used to swallow a
    nested lock's ``resource_busy`` and turn it into ``generator didn't stop
    after throw`` (audit C-05).
    """
    if level not in LEVELS:
        raise LockError("unknown_lock_level")
    if _sqlite_depth() > 0:
        raise SqliteNestingError("os_lock_inside_sqlite_tx")
    stack = _held()
    if stack and LEVELS[level] < stack[-1][0]:
        raise LockOrderError("lock_order_violation",
                             detail={"held": stack[-1][0], "requested": LEVELS[level]})
    path = _lock_path(project, level, key)
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        # A fresh context manager per attempt: contextlib clears its generator
        # after __enter__, so the failed attempt cannot be retried.
        context = safety.file_lock(path)
        try:
            context.__enter__()
            break
        except safety.PublicationBlocked:
            if time.monotonic() >= deadline:
                raise LockError("lock_busy", detail={"level": level, "key": key}) from None
            time.sleep(0.02)
        except OSError as exc:
            # 权限/磁盘错误是「锁不可用」，不是 500；调用方按 503 重试。
            raise LockError("lock_unavailable", status=503,
                            detail={"level": level, "reason": type(exc).__name__}) from None
    stack.append((LEVELS[level], level))
    try:
        yield path
    finally:
        stack.pop()
        context.__exit__(None, None, None)


@contextmanager
def ordered(project, requests: Iterable[Tuple[str, str]], *, timeout: float = 5.0):
    """Acquire several locks in ascending order; release in reverse."""
    rows = []
    for level, key in requests:
        if level not in LEVELS:
            raise LockError("unknown_lock_level")
        rows.append((LEVELS[level], level, key))
    rows.sort(key=lambda row: row[0])
    with _ExitStack() as stack:
        for _, level, key in rows:
            stack.enter_context(hold(project, level, key, timeout=timeout))
        yield


class _ExitStack:
    def __init__(self):
        self._contexts = []

    def __enter__(self):
        return self

    def enter_context(self, context):
        value = context.__enter__()
        self._contexts.append(context)
        return value

    def __exit__(self, exc_type, exc, tb):
        error = None
        for context in reversed(self._contexts):
            try:
                context.__exit__(exc_type, exc, tb)
            except Exception as caught:  # noqa: BLE001 - release everything
                error = error or caught
        return False


@contextmanager
def sqlite_scope():
    """Mark the current thread as inside a SQLite write transaction."""
    note_sqlite_enter()
    try:
        yield
    finally:
        note_sqlite_exit()


def held_levels() -> List[int]:
    return [level for level, _ in _held()]


def lock_path(project, level: str, key: str = "") -> Path:
    return _lock_path(project, level, key)
