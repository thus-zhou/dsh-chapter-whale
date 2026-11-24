"""唯一失效入口：源章变化后，旧证据统一进待复核，并重建连续性索引。不调用模型。

设计约束（03_v0.7.0 C01.4 / C04.3）：
- 生成、导入、人工改章、接受修订、恢复版本都走 ``invalidate()``，不各写一套；
- 同一次操作（``op_id``）只记一次，重复调用不再制造第二份失效记录；
- 失效只标记与重建索引，不删除旧事实、不改写作者正文；
- 记录可回溯：谁在什么时候因为什么原因让哪些章节的哪些证据进入待复核。
"""
from __future__ import annotations

from pathlib import Path

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


def invalidate(project, *, chapters, reason, source="", actor="author", op_id=""):
    """统一失效入口：记一条日志、标出受影响证据、重建连续性索引。"""
    if reason not in REASONS:
        raise ValueError("失效原因无效")
    chapters = _chapters(chapters)
    doc = read_log(project)
    key = str(op_id or "")
    if key:
        for entry in doc["entries"]:
            if entry.get("op_id") == key:
                return {"status": "reused", "entry": entry, "marked": entry.get("marked", [])}
    marked = affected_facts(project, chapters)
    entry = {"op_id": key, "at": bridge.now_iso(), "chapters": chapters, "reason": reason,
             "reason_label": REASONS[reason], "source": str(source or "")[:120], "actor": str(actor or "")[:40],
             "marked": marked}
    doc["revision"] = int(doc.get("revision") or 0) + 1
    doc["entries"] = [*doc["entries"], entry][-MAX_ENTRIES:]
    writer.atomic_json(_path(project), doc)
    reviewing = _mark_facts(project, chapters, reason=reason, source=source, actor=actor)
    rebuilt = _rebuild(project)
    return {"status": "invalidated", "entry": entry, "marked": marked, "reviewing": len(reviewing),
            "rebuilt": rebuilt}


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
