"""伏笔状态、冲突检测与来源依赖索引。全部确定性检查，不调用模型。"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

from . import bridge, memory_library as memory, writer_runner as writer

SCHEMA = 1
STATES = {"planned": "计划", "planted": "已埋设", "developing": "推进中",
          "resolved": "已回收", "paused": "作者暂缓", "cancelled": "作者取消"}
ORDER = {"planned": 0, "planted": 1, "developing": 2, "resolved": 3}
WITH_EVIDENCE = {"planted", "developing", "resolved"}
MAX_TRANSITIONS = 40
INDEX_NAME = "continuity_index.json"


def _index_path(project):
    project = Path(project).resolve()
    folder = project / ".webnovel"
    path = folder / INDEX_NAME
    if folder.is_symlink() or path.is_symlink() or project not in path.resolve().parents:
        raise ValueError("依赖索引目录不安全")
    return path


def _chapter_body(project, chapter):
    return memory._chapter(Path(project), chapter)


def transitions(item):
    return [{"state": row.get("state"), "state_label": STATES.get(row.get("state"), ""),
             "chapter": row.get("chapter", 0), "event": row.get("event", ""),
             "at": row.get("at", ""), "author": bool(row.get("author"))}
            for row in item.get("transitions") or []]


def transition(project, identity, revision, state, *, chapter=0, event="", quote="", sha256="",
               expected="", note="", author=False):
    """状态前进必须有正文依据；计划埋设不等于已写入正文。"""
    if state not in STATES:
        raise ValueError("伏笔状态无效")
    project = Path(project).resolve()
    doc = memory.read(project)
    if doc["revision"] != revision:
        raise ValueError("记忆已更新，请重新载入后再保存")
    item = next((x for x in doc["items"] if x["id"] == identity and x["category"] == "foreshadow"), None)
    if not item:
        raise KeyError("伏笔不存在")
    current = item.get("clue_state") or "planned"
    if state in WITH_EVIDENCE:
        if not (1 <= int(chapter) <= 100000):
            raise ValueError("状态前进需要章节位置")
        body, digest = _chapter_body(project, int(chapter))
        if sha256 and digest != sha256:
            raise ValueError("状态依据与当前正文不一致")
        sha256 = digest
        if not str(quote or "").strip() or quote.strip() not in body:
            raise ValueError("状态依据必须引用该章原文")
    elif state == "cancelled" and not str(note or "").strip() and not author:
        raise ValueError("取消伏笔需要说明原因")
    if state in ORDER and current in ORDER and ORDER[state] < ORDER[current] and not author:
        raise ValueError("状态不能无依据回退；如确需回退请由作者确认")
    row = {"state": state, "chapter": int(chapter or 0), "event": str(event or "")[:200],
           "quote": str(quote or "")[:800], "sha256": str(sha256 or ""), "note": str(note or "")[:400],
           "author": bool(author), "at": bridge.now_iso()}
    item["clue_state"] = state
    item["expected"] = str(expected or item.get("expected") or "")[:400]
    item["note"] = str(note or item.get("note") or "")[:400]
    if state in WITH_EVIDENCE:
        item["actual"] = {"chapter": int(chapter), "sha256": str(sha256), "quote": str(quote)[:800],
                          "state": state, "recorded_at": bridge.now_iso()}
    item["transitions"] = [*(item.get("transitions") or []), row][-MAX_TRANSITIONS:]
    item["updated_at"] = bridge.now_iso()
    item["updated_revision"] = doc["revision"] + 1
    memory._commit(project, doc, {"id": item["id"], "from": current, "to": state}, "foreshadow_transition")
    return {"status": "saved", "state": state, "state_label": STATES[state],
            "item": {"id": item["id"], "title": item["title"], "state": state,
                     "transitions": transitions(item), "expected": item.get("expected", ""),
                     "actual": item.get("actual") or {}}}


def conflicts(project):
    """只做可确定的检查：逾期、无依据的回收、来源失效、范围矛盾。"""
    project = Path(project).resolve()
    doc = memory.read(project)
    cache = {}
    chapter_now = writer.next_chapter_id(project)
    rows = []
    for item in doc["items"]:
        if item["status"] != "active" or item["category"] != "foreshadow":
            continue
        state = item.get("clue_state") or "planned"
        due = int(item.get("due_chapter") or 0)
        if state in {"planned", "planted", "developing"} and due and due <= chapter_now:
            rows.append({"kind": "overdue", "severity": "high", "item": item["id"], "title": item["title"],
                         "message": f"计划第{due}章前回收，但当前状态是“{STATES[state]}”", "chapter": due})
        actual = item.get("actual") or {}
        if state == "resolved" and not actual.get("sha256"):
            rows.append({"kind": "resolved_without_evidence", "severity": "high", "item": item["id"],
                         "title": item["title"], "message": "标记已回收，但没有正文依据", "chapter": 0})
        if actual.get("chapter"):
            try:
                _, digest = _chapter_body(project, int(actual["chapter"]))
            except (ValueError, OSError):
                digest = ""
            if digest and digest != actual.get("sha256"):
                rows.append({"kind": "source_stale", "severity": "high", "item": item["id"], "title": item["title"],
                             "message": f"第{actual['chapter']}章正文已变化，伏笔依据失效", "chapter": actual["chapter"]})
        if item.get("source", {}).get("kind") == "chapter":
            state_fresh = memory.freshness(project, item, cache)
            if state_fresh == "stale":
                rows.append({"kind": "source_stale", "severity": "high", "item": item["id"], "title": item["title"],
                             "message": "伏笔来源正文已变化", "chapter": item["source"].get("chapter", 0)})
        if int(item.get("valid_to") or 0) and int(item.get("valid_from") or 0) > int(item["valid_to"]):
            rows.append({"kind": "invalid_range", "severity": "advisory", "item": item["id"], "title": item["title"],
                         "message": "有效范围起点晚于终点", "chapter": 0})
    return rows


def _derived(project, chapter):
    """列出某章正文产生的派生记录；只用已有引用，不重复解析正文。"""
    doc = memory.read(project)
    derived = []
    for item in doc["items"]:
        source = item.get("source") or {}
        if source.get("kind") == "chapter" and source.get("chapter") == chapter:
            derived.append({"kind": "memory", "id": item["id"], "title": item["title"]})
    try:
        from . import character_state
        chars = character_state.read(project)
        for row in chars.get("knowledge") or []:
            if row.get("chapter") == chapter:
                derived.append({"kind": "knowledge", "id": row["id"], "title": row.get("info", "")[:60]})
        for row in chars.get("relations") or []:
            if row.get("chapter") == chapter:
                derived.append({"kind": "relation", "id": row["id"], "title": row.get("kind", "")})
    except (ValueError, OSError):
        pass
    return derived


def build_index(project):
    """来源记录 → 派生记录/报告 的轻量索引；正文哈希只算一次。"""
    project = Path(project).resolve()
    doc = memory.read(project)
    chapters = {}
    for path, number in writer._chapter_files(project):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        chapters[str(number)] = {"sha256": digest, "bytes": path.stat().st_size,
                                 "title": path.stem, "derived": _derived(project, number)}
    reports = []
    report_dir = project / ".webnovel" / "quality_reports"
    if report_dir.is_dir():
        for path in sorted(report_dir.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            reports.append({"chapter": row.get("chapter_id"), "report_id": row.get("report_id"),
                            "body_sha256": row.get("body_sha256"), "file": path.name})
    index = {"schema_version": SCHEMA, "built_at": bridge.now_iso(), "chapters": chapters,
             "reports": reports, "review_attempts": sorted(
                 str(p.name) for p in (project / ".webnovel" / "review_attempts").glob("*.json"))
             if (project / ".webnovel" / "review_attempts").is_dir() else [],
             "memory_revision": doc["revision"]}
    writer.atomic_json(_index_path(project), index)
    return {"chapters": len(chapters), "reports": len(reports), "derived": sum(len(x["derived"]) for x in chapters.values())}


def read_index(project):
    path = _index_path(project)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def impact(project):
    """对比索引与当前正文：列出已知受影响范围，并明确未知范围。"""
    project = Path(project).resolve()
    index = read_index(project) or {"chapters": {}}
    stored = {int(k): v for k, v in (index.get("chapters") or {}).items()}
    changed, missing = [], []
    current = {}
    for path, number in writer._chapter_files(project):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        current[number] = digest
        old = stored.get(number)
        if old and old.get("sha256") != digest:
            changed.append({"chapter": number, "derived": old.get("derived") or [],
                            "reports": [r for r in index.get("reports") or [] if r.get("chapter") == number]})
        elif old is None:
            missing.append(number)
    removed = [n for n in stored if n not in current]
    known = changed + [{"chapter": n, "derived": [], "reports": []} for n in missing]
    return {"changed": changed, "added": missing, "removed": removed,
            "affected": len(known), "unknown": "索引只覆盖已知引用；未记录依赖的历史章节可能仍受影响，无法保证绝对无影响。",
            "built_at": index.get("built_at", "")}


def rebuild(project, chapter=None):
    """不调用模型的局部重建：重算索引，失效记录只标记不删除。"""
    project = Path(project).resolve()
    before = read_index(project)
    counts = build_index(project)
    doc = memory.read(project)
    marked = []
    for item in doc["items"]:
        if item["category"] != "foreshadow" or item["status"] != "active":
            continue
        actual = item.get("actual") or {}
        if not actual.get("chapter"):
            continue
        if chapter and int(actual["chapter"]) != int(chapter):
            continue
        try:
            _, digest = _chapter_body(project, int(actual["chapter"]))
        except (ValueError, OSError):
            digest = ""
        if digest and digest != actual.get("sha256"):
            marked.append({"id": item["id"], "title": item["title"], "chapter": actual["chapter"]})
    return {"index": counts, "stale": marked, "chapter": chapter or None,
            "previous": bool(before), "needs_review": bool(marked)}


def view(project, chapter=0):
    project = Path(project).resolve()
    chapter = int(chapter or writer.next_chapter_id(project))
    doc = memory.read(project)
    rows = []
    for item in doc["items"]:
        if item["category"] != "foreshadow" or item["status"] != "active":
            continue
        state = item.get("clue_state") or "planned"
        rows.append({"id": item["id"], "title": item["title"], "state": state, "state_label": STATES[state],
                     "due_chapter": int(item.get("due_chapter") or 0), "expected": item.get("expected", ""),
                     "actual": item.get("actual") or {}, "transitions": transitions(item),
                     "source_chapter": item["source"].get("chapter", 0), "summary": item.get("content", "")[:200],
                     "overdue": bool(int(item.get("due_chapter") or 0) and int(item["due_chapter"]) <= chapter
                                     and state in {"planned", "planted", "developing"})})
    rows.sort(key=lambda x: (ORDER.get(x["state"], 9), x["due_chapter"] or 99999))
    issues = conflicts(project)
    return {"schema_version": SCHEMA, "chapter": chapter, "foreshadows": rows, "count": len(rows),
            "conflicts": issues, "impact": impact(project), "states": STATES,
            "note": "“计划埋设”不等于已写入正文；“计划回收”不等于实际回收；状态变化必须有来源。"}
