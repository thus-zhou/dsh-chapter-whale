"""唯一失效入口：源章变化后，旧证据统一进待复核，并重建连续性索引。不调用模型。

设计约束（03_v0.7.0 C01.4 / C04.3）：
- 生成、导入、人工改章、接受修订、恢复版本都走 ``invalidate()``，不各写一套；
- 同一次操作（``op_id``）只记一次，重复调用不再制造第二份失效记录；
- 失效只标记与重建索引，不删除旧事实、不改写作者正文；
- 记录可回溯：谁在什么时候因为什么原因让哪些章节的哪些证据进入待复核。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict

from . import bridge, writer_runner as writer

SCHEMA = 1
MAX_ENTRIES = 200
REASONS = {
    "chapter_edited": "正文被改写",
    "chapter_imported": "导入新正文",
    "chapter_generated": "重新生成正文",
    "revision_accepted": "接受修订",
    "version_restored": "恢复历史版本",
    "author_corrected": "作者更正设定",
    "manual": "人工触发",
}


def _path(project, name="invalidation_log.json"):
    project = Path(project).resolve()
    folder = project / ".webnovel"
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or project not in path.resolve().parents:
        raise ValueError("失效日志目录不安全")
    return path


def _empty():
    return {"schema_version": SCHEMA, "revision": 0, "entries": []}


def read_log(project):
    path = _path(project)
    if not path.exists():
        return _empty()
    doc = writer.strict_json(path, _empty())
    if (not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA
            or not isinstance(doc.get("entries"), list) or type(doc.get("revision")) is not int):
        raise ValueError("失效日志损坏，未覆盖原文件")
    return doc


def _chapters(value):
    rows = [value] if isinstance(value, int) else list(value or [])
    result = []
    for item in rows:
        if type(item) is not int or not 1 <= item <= 100000:
            raise ValueError("失效章节无效")
        if item not in result:
            result.append(item)
    if not result:
        raise ValueError("失效必须指明章节")
    return sorted(result)


def affected_facts(project, chapters):
    """列出源章落在给定章界内的记忆条目（只读，不改内容）。"""
    from . import memory_library
    doc = memory_library.read(project)
    chapters = set(chapters)
    marked = []
    for item in doc.get("items", []):
        source = item.get("source") or {}
        if int(source.get("chapter") or 0) not in chapters:
            continue
        if str(item.get("status") or "active") != "active":
            continue
        marked.append({"id": str(item.get("id") or ""), "category": item.get("category", ""),
                       "title": item.get("title", ""), "source_chapter": int(source.get("chapter") or 0)})
    return marked


def _mark_facts(project, chapters, *, reason, source, actor):
    """把源章命中的记忆标成 needs_review：它们不再进上下文，等作者复核。

    ``needs_review`` 与 ``conflict`` 分开：前者是「依据的章变了」，后者是「作者设定互相矛盾」。
    旧内容一律保留，只改状态与复核元数据，作者可以据此逐条恢复。
    """
    from . import memory_library
    with writer.file_lock(memory_library._path(project, "memory.lock")):
        return _mark_facts_unlocked(project, chapters, reason=reason, source=source, actor=actor)


def _mark_facts_unlocked(project, chapters, *, reason, source, actor):
    from . import memory_library
    doc = memory_library.read(project)
    wanted = set(chapters)
    marked = []
    for item in doc.get("items", []):
        source_meta = item.get("source") or {}
        if int(source_meta.get("chapter") or 0) not in wanted:
            continue
        if str(item.get("status") or "active") != "active":
            continue
        item["status"] = "needs_review"
        item["review"] = {"reason": reason, "source": str(source or "")[:120],
                          "actor": str(actor or "")[:40], "at": bridge.now_iso()}
        marked.append({"id": str(item.get("id") or ""), "category": item.get("category", ""),
                       "title": item.get("title", ""),
                       "source_chapter": int(source_meta.get("chapter") or 0)})
    if not marked:
        return []
    doc["revision"] = int(doc.get("revision") or 0) + 1
    doc["updated_at"] = bridge.now_iso()
    doc["history"] = [*doc.get("history", []),
                      {"at": doc["updated_at"], "action": "facts_marked_needs_review",
                       "before": f"chapters={sorted(wanted)};count={len(marked)}"}][-80:]
    writer.atomic_json(memory_library._path(project), doc)
    return marked


def invalidate(project, *, chapters, reason, source="", actor="author", op_id="", async_rebuild=False):
    """统一失效入口：记一条日志、标出受影响证据、重建连续性索引。

    ``async_rebuild=True`` 供大书 ``Ctrl+S`` 使用：日志与证据标记同步落盘，
    连续性索引由合并写回的后台线程重建，避免 500–1000 章时阻塞保存响应。
    """
    for attempt in range(20):
        try:
            with writer.file_lock(_path(project, "invalidation.lock")):
                return _invalidate_once(project, chapters=chapters, reason=reason, source=source,
                                        actor=actor, op_id=op_id, async_rebuild=async_rebuild)
        except Exception as exc:
            if exc.__class__.__name__ == "PublicationBlocked" and attempt < 19:
                time.sleep(0.05)
                continue
            raise


def _invalidate_once(project, *, chapters, reason, source="", actor="author", op_id="", async_rebuild=False):
    if reason not in REASONS:
        raise ValueError("失效原因无效")
    chapters = _chapters(chapters)
    doc = read_log(project)
    key = str(op_id or "")
    if key:
        for entry in doc["entries"]:
            if entry.get("op_id") != key:
                continue
            if entry.get("state", "applied") != "applied":
                # The previous attempt wrote the log but crashed/failed before
                # the memory marks landed; retry the marks instead of
                # reporting a successful no-op (A-P2-8).
                reviewing = _mark_facts(project, entry.get("chapters") or chapters,
                                        reason=entry.get("reason") or reason,
                                        source=entry.get("source") or source, actor=actor)
                entry["state"] = "applied"
                entry["applied_at"] = bridge.now_iso()
                if reviewing:
                    entry["marked"] = reviewing
                writer.atomic_json(_path(project), doc)
                rebuilt = _schedule_rebuild(project) if async_rebuild else _rebuild(project)
                return {"status": "invalidated", "entry": entry,
                        "marked": entry.get("marked", []), "reviewing": len(reviewing),
                        "rebuilt": rebuilt, "reapplied": True}
            return {"status": "reused", "entry": entry, "marked": entry.get("marked", [])}
    marked = affected_facts(project, chapters)
    entry = {"op_id": key, "at": bridge.now_iso(), "chapters": chapters, "reason": reason,
             "reason_label": REASONS[reason], "source": str(source or "")[:120], "actor": str(actor or "")[:40],
             "state": "pending", "marked": marked}
    doc["revision"] = int(doc.get("revision") or 0) + 1
    doc["entries"] = [*doc["entries"], entry][-MAX_ENTRIES:]
    writer.atomic_json(_path(project), doc)
    reviewing = _mark_facts(project, chapters, reason=reason, source=source, actor=actor)
    entry["state"] = "applied"
    entry["applied_at"] = bridge.now_iso()
    if reviewing:
        entry["marked"] = reviewing
    writer.atomic_json(_path(project), doc)
    if async_rebuild:
        rebuilt = _schedule_rebuild(project)
    else:
        rebuilt = _rebuild(project)
    return {"status": "invalidated", "entry": entry, "marked": marked, "reviewing": len(reviewing),
            "rebuilt": rebuilt}


_REBUILD_LOCK = threading.Lock()
_REBUILD_PENDING: Dict[str, threading.Event] = {}


def _schedule_rebuild(project) -> bool:
    """Coalesce concurrent rebuild requests per project; return False if failed to start."""
    key = str(Path(project).resolve())
    with _REBUILD_LOCK:
        if key in _REBUILD_PENDING:
            return True
        event = threading.Event()
        _REBUILD_PENDING[key] = event

    def work():
        try:
            _rebuild(project)
        finally:
            with _REBUILD_LOCK:
                _REBUILD_PENDING.pop(key, None)
            event.set()

    try:
        threading.Thread(target=work, name="invalidation-rebuild", daemon=True).start()
        return True
    except RuntimeError:
        with _REBUILD_LOCK:
            _REBUILD_PENDING.pop(key, None)
        return False


def wait_rebuild(project, timeout: float = 10.0) -> bool:
    """Test/verification helper: wait for the coalesced background rebuild."""
    key = str(Path(project).resolve())
    with _REBUILD_LOCK:
        event = _REBUILD_PENDING.get(key)
    if event is None:
        return True
    return bool(event.wait(timeout))


def _rebuild(project):
    """重建连续性索引；旧事实与后续正文都不删，只把依据失效的伏笔列为待复核。"""
    try:
        from . import continuity
        continuity.rebuild(project)
        return True
    except (ValueError, OSError):
        return False


def pending(project, limit=20):
    """最近的失效记录与实际待复核数量（只读）。"""
    doc = read_log(project)
    rows = list(reversed(doc["entries"]))[:max(1, int(limit))]
    return {"revision": int(doc.get("revision") or 0), "entries": rows, "total": len(doc["entries"])}


def summary(project):
    doc = read_log(project)
    by_reason = {}
    for entry in doc["entries"]:
        by_reason[entry.get("reason", "")] = by_reason.get(entry.get("reason", ""), 0) + 1
    return {"revision": int(doc.get("revision") or 0), "entries": len(doc["entries"]),
            "by_reason": by_reason, "last": (doc["entries"][-1] if doc["entries"] else None)}
