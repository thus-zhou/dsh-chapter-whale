"""有来源的物品归属与状态事件：归属链、故事时间、知情主体。不调用模型。

设计约束（03_v0.7.0 C01）：
- 只记「谁在第几章因为哪段原文持有/交出了什么」，不建通用图谱；
- 同名只是检索入口，跨作品（不同 project）绝不合并；
- 未知与否定分开：查不到返回 ``unknown``，不返回「没有」；
- 同一章内先后不明返回 ``unknown`` 与候选，不按写入顺序猜；
- 全知叙述（``scope="narrator"``）不等于角色已知。
"""
from __future__ import annotations

import re
import hashlib
import unicodedata
import uuid
from contextlib import nullcontext
from pathlib import Path

from . import bridge, writer_runner as writer

SCHEMA = 1
MAX_ITEMS = 2000
MAX_EVENTS = 8000
STATUSES = ("confirmed", "guess")
DISCOVERIES = ("narrated", "inferred", "author")
SCOPES = ("character", "reader", "author", "narrator")


def _path(project, name="entities.json"):
    project = Path(project).resolve()
    folder = project / ".webnovel"
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or project not in path.resolve().parents:
        raise ValueError("实体状态目录不安全")
    return path


def _norm(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).casefold()


def _text(value, limit, required=True, field="实体"):
    if not isinstance(value, str) or len(value) > limit or "\0" in value or (required and not value.strip()):
        raise ValueError(f"{field}为空或超过长度限制")
    return value.strip()


def empty():
    return {"schema_version": SCHEMA, "revision": 0, "items": {}, "events": [], "history": []}


def read(project):
    path = _path(project)
    if not path.exists():
        return empty()
    if path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("实体状态文件过大，请先备份检查")
    doc = writer.strict_json(path, empty())
    if (not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA
            or type(doc.get("revision")) is not int or doc["revision"] < 0
            or not isinstance(doc.get("items"), dict) or not isinstance(doc.get("events"), list)):
        raise ValueError("实体状态文件损坏，未覆盖原文件")
    if len(doc["items"]) > MAX_ITEMS or len(doc["events"]) > MAX_EVENTS:
        raise ValueError("实体或事件数量已达上限，请先整理")
    return doc


def _commit(project, doc, action):
    doc["revision"] += 1
    doc["updated_at"] = bridge.now_iso()
    doc["history"] = [*doc.get("history", []), {"at": doc["updated_at"], "action": action}][-60:]
    writer.atomic_json(_path(project), doc)


def _story_before(candidate, target):
    """故事时间比较：两边都是 ISO 时刻时按时刻，否则只认完全相同。"""
    candidate = str(candidate or "").strip()
    target = str(target or "").strip()
    if not target:
        return True
    if not candidate:
        return False
    if candidate == target:
        return True
    try:
        from datetime import datetime
        left = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        right = datetime.fromisoformat(target.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if (left.tzinfo is None) != (right.tzinfo is None):
        return False
    return left <= right


def _events_for(doc, key):
    return [row for row in doc["events"] if _norm(row.get("entity")) == key]


def _evidence_current(project, row):
    """历史事件仍保留，但只有与当前正文及引文一致时才能成为事实。"""
    chapter = int(row.get("chapter") or 0)
    paths = [p for p in (Path(project) / "正文").glob("*.md")
             if (parsed := bridge.parse_chapter_name(p.name)) and parsed[0] == chapter]
    if len(paths) != 1:
        return False
    try:
        raw = paths[0].read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        return False
    evidence = row.get("evidence") or {}
    return (evidence.get("sha256") == hashlib.sha256(raw).hexdigest()
            and bool(evidence.get("quote")) and evidence["quote"] in text)


def _check_chapter(chapter):
    if type(chapter) is not int or not 1 <= chapter <= 100000:
        raise ValueError("章节位置无效")
    return chapter


def _check_evidence(sha256, quote):
    if not re.fullmatch(r"[a-f0-9]{64}", str(sha256 or "")):
        raise ValueError("来源正文摘要无效")
    return _text(quote, 800, field="原文引文")


def record_item(project, *, entity, holder, chapter, quote, sha256, event="", before=None, after=None,
                status="confirmed", discovery="narrated", knowers=None, story_time="",
                scope="character", op_id="", _writer_locked=False):
    """记一次归属事件（转移/交付/拾取）。同名实体只作检索入口，不跨作品合并。"""
    name = _text(entity, 80, field="实体名称")
    holder = _text(holder, 80, field="持有人")
    chapter = _check_chapter(chapter)
    quote = _check_evidence(sha256, quote)
    if status not in STATUSES:
        raise ValueError("归属状态无效")
    if discovery not in DISCOVERIES:
        raise ValueError("发现方式无效")
    if scope not in SCOPES:
        raise ValueError("认知范围无效")
    if knowers is not None and (not isinstance(knowers, list) or len(knowers) > 20):
        raise ValueError("知情主体必须是最多 20 项的数组")
    knowers = [_text(item, 80, field="知情主体") for item in (knowers or [])]
    key = _norm(name)
    with (nullcontext() if _writer_locked else writer.file_lock(_path(project, "writer.lock"))):
        doc = read(project)
        added = after if after is not None else holder
        item = doc["items"].get(key) or {"key": key, "name": name, "aliases": [], "holder": "", "holder_chapter": 0}
        previous = before if before is not None else item.get("holder", "")
        row = {"id": uuid.uuid4().hex, "entity": name, "attribute": "holder", "before": previous, "after": _text(added, 80, field="事件后归属"),
               "chapter": chapter, "story_time": _text(story_time, 80, required=False, field="故事时间"),
               "knowers": knowers, "scope": scope, "status": status, "discovery": discovery,
               "event": _text(event, 200, required=False, field="事件"), "op_id": str(op_id or ""),
               "evidence": {"sha256": sha256, "quote": quote}, "created_at": bridge.now_iso()}
        for old in doc["events"]:
            if (old.get("entity") == name and old.get("chapter") == chapter and old.get("event") == row["event"]
                    and old.get("evidence") == row["evidence"] and old.get("after") == row["after"]):
                return {"status": "reused", "event": old, "item": item}
        start = int(item.get("holder_chapter") or 0)
        item["name"] = name
        if not start or chapter >= start:
            item["holder"] = row["after"]
            item["holder_chapter"] = chapter
        else:
            item["out_of_order"] = True
        doc["items"][key] = item
        doc["events"].append(row)
        _commit(project, doc, "item_recorded")
        return {"status": "saved", "event": row, "item": item}


def transfer(project, *, entity, from_holder, to_holder, chapter, quote, sha256, **kwargs):
    """转移必须在声明的前持有者确实持有时才记；不符就不写，交给作者核对。

    前持有者的记录若是「猜测」，不能据它写出一条确定转移：那样猜测会被升级成事实。
    作者确认请用 `record_item(status="confirmed", before=...)` 显式覆盖。
    """
    current = holder_at(project, entity, chapter)
    if current["status"] != "known":
        raise ValueError(f"第{chapter}章之前的归属未知（{current.get('reason') or '无记录'}），不能声明转移")
    if str(current.get("confidence") or "confirmed") != "confirmed":
        raise ValueError(f"第{chapter}章之前关于「{entity}」的记录是猜测，不能据此声明转移；请先由作者确认")
    if _norm(current["holder"]) != _norm(from_holder):
        raise ValueError(f"第{chapter}章之前记录持有者是 {current['holder']}，与声明的 {from_holder} 不符")
    return record_item(project, entity=entity, holder=to_holder, before=current["holder"], chapter=chapter,
                       quote=quote, sha256=sha256, **kwargs)


def holder_at(project, entity, chapter, *, story_time=None, doc=None):
    """截止第 N 章（不含本章自身事件）的归属；同章先后不明返回 unknown，不按写入顺序猜。"""
    chapter = _check_chapter(chapter) if chapter else 0
    doc = read(project) if doc is None else doc
    key = _norm(entity)
    rows = [row for row in _events_for(doc, key)
            if (int(row.get("chapter") or 0) < chapter if chapter else True)
            and _story_before(row.get("story_time"), story_time)]
    if not rows:
        return {"status": "unknown", "reason": "no_record_before_chapter", "entity": entity, "chapter": chapter}
    rows.sort(key=lambda row: int(row.get("chapter") or 0))
    top = int(rows[-1].get("chapter") or 0)
    same = [row for row in rows if int(row.get("chapter") or 0) == top]
    same = [row for row in same if _evidence_current(project, row)]
    if not same:
        return {"status": "unknown", "reason": "source_changed", "entity": entity,
                "chapter": top, "note": "来源正文已改动或缺失，请重新提取确认"}
    holders = {str(row.get("after") or "") for row in same}
    if len(holders) > 1:
        return {"status": "unknown", "reason": "same_chapter_order_unknown", "entity": entity, "chapter": top,
                "candidates": [{"holder": row.get("after"), "event": row.get("event"), "quote": row.get("evidence", {}).get("quote")}
                               for row in same]}
    last = same[-1]
    return {"status": "known", "entity": entity, "chapter": chapter, "holder": last.get("after"),
            "source_chapter": top, "confidence": last.get("status"),
            "quote": last.get("evidence", {}).get("quote"), "sha256": last.get("evidence", {}).get("sha256"),
            "event_id": last.get("id")}


def holder_rows(project, chapter, *, limit=20):
    """给提示用的紧凑清单：每条只写「物品：持有者（第N章）」或「未知」。"""
    doc = read(project)
    rows = []
    for key, item in doc.get("items", {}).items():
        view = holder_at(project, item.get("name") or key, chapter, doc=doc)
        name = str(item.get("name") or key)
        if view["status"] == "known":
            rows.append(f"{name}：{view['holder']}（第{view['source_chapter']}章）")
        elif view.get("reason") == "same_chapter_order_unknown":
            rows.append(f"{name}：同章先后不明，暂按未知处理")
        else:
            rows.append(f"{name}：未知")
        if len(rows) >= limit:
            break
    return rows


def item_knowledge(project, person, entity, chapter, *, scope="character", doc=None):
    """角色是否知道该归属：必须有一次在章界内的获知记录；全知叙述不算角色已知。"""
    _check_chapter(chapter)
    if scope not in ("character", "reader"):
        raise ValueError("只能查询角色或读者认知")
    doc = read(project) if doc is None else doc
    key = _norm(entity)
    rows = [row for row in _events_for(doc, key)
            if int(row.get("chapter") or 0) < chapter and row.get("scope") == scope
            and _norm(person) in {_norm(item) for item in row.get("knowers") or []}]
    if not rows:
        return {"status": "unknown", "reason": "no_knowledge_record", "person": person, "entity": entity,
                "note": "未记录不等于人物不知道；程序只能核对本书记录。"}
    top = max(int(row.get("chapter") or 0) for row in rows)
    current = [row for row in rows if int(row.get("chapter") or 0) == top and _evidence_current(project, row)]
    if not current:
        return {"status": "unknown", "reason": "source_changed", "person": person, "entity": entity}
    if len({row.get("after") for row in current}) > 1:
        return {"status": "unknown", "reason": "same_chapter_order_unknown", "person": person, "entity": entity}
    latest = current[-1]
    return {"status": "known", "person": person, "entity": entity, "holder_at_event": latest.get("after"),
            "chapter": int(latest.get("chapter") or 0), "confidence": latest.get("status"),
            "quote": latest.get("evidence", {}).get("quote")}


def view(project, chapter=0, *, doc=None):
    """平面视图：每件物品当前归属与最后一次有据变化。

    `chapter=0` 时按「最后一条事件的下一章」折算，仍然走 holder_at 的同章歧义判定，
    不读 item 上的最后写入缓存——缓存只用于展示，把同章两次写入当成确定归属会谎报事实。
    """
    doc = read(project) if doc is None else doc
    chapter = int(chapter or 0)
    latest = max((int(row.get("chapter") or 0) for row in doc["events"]), default=0)
    horizon = chapter or (latest + 1)
    rows = []
    for key, item in doc["items"].items():
        current = holder_at(project, item.get("name") or key, horizon, doc=doc)
        rows.append({**item, "current": current})
    rows.sort(key=lambda row: row["name"])
    return {"chapter": chapter, "horizon": horizon, "items": rows, "events": len(doc["events"]),
            "revision": doc["revision"],
            "note": "同名只是检索入口；查不到归属是未知，不是没有。"}
