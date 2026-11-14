"""人物档案、关系与认知：稳定 ID，来源绑定，作者纠正优先。不调用模型。"""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
import uuid
from contextlib import nullcontext
from pathlib import Path

from . import bridge, writer_runner as writer

SCHEMA = 1
MAX_PERSONS = 800
MAX_CANDIDATES = 6
PROFILE_FIELDS = ("identity", "goal", "motive", "limits", "voice", "history")
SCOPES = {"character": "人物认知", "reader": "读者已知", "author": "作者已知"}
STATUSES = {"confirmed": "已确认", "guess": "只是猜测"}


def _path(project, name="characters.json"):
    project = Path(project).resolve()
    folder = project / ".webnovel"
    path = folder / name
    if folder.is_symlink() or path.is_symlink() or project not in path.resolve().parents:
        raise ValueError("人物档案目录不安全")
    return path


def _norm(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).casefold()


def _text(value, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or "\0" in value or (required and not value.strip()):
        raise ValueError("人物字段为空或超过长度限制")
    return value.strip()


def empty():
    return {"schema_version": SCHEMA, "revision": 0, "persons": {}, "relations": [], "knowledge": [], "history": []}


def read(project):
    path = _path(project)
    if not path.exists():
        return empty()
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("人物档案过大，请先备份检查")
    doc = writer.strict_json(path, empty())
    if (not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA or type(doc.get("revision")) is not int
            or doc["revision"] < 0 or not isinstance(doc.get("persons"), dict)
            or not isinstance(doc.get("relations"), list) or not isinstance(doc.get("knowledge"), list)):
        raise ValueError("人物档案损坏，未覆盖原文件")
    if len(doc["persons"]) > MAX_PERSONS:
        raise ValueError("人物数量已达上限，请先整理")
    return doc


def _commit(project, doc, action):
    doc["revision"] += 1
    doc["updated_at"] = bridge.now_iso()
    doc["history"] = [*doc.get("history", []), {"at": doc["updated_at"], "action": action}][-60:]
    writer.atomic_json(_path(project), doc)


def _blank_profile():
    return {field: "" for field in PROFILE_FIELDS}


def _person_view(item):
    profile = {**_blank_profile(), **(item.get("profile") or {})}
    unknown = [field for field in PROFILE_FIELDS if not str(profile.get(field) or "").strip()]
    return {"id": item["id"], "name": item["name"], "aliases": list(item.get("aliases") or []),
            "profile": profile, "unknown": unknown, "overrides": dict(item.get("overrides") or {}),
            "record_version": int(item.get("record_version") or 1),
            "origin": item.get("origin", ""), "updated_at": item.get("updated_at", "")}


def _find(doc, text):
    """按姓名或别名精确匹配；多个命中视为冲突，绝不猜。"""
    key = _norm(text)
    if not key:
        raise ValueError("人物名称不能为空")
    hits = [item for item in doc["persons"].values()
            if _norm(item.get("name")) == key or any(_norm(alias) == key for alias in item.get("aliases") or [])]
    if len(hits) > 1:
        raise ValueError("同名或别名指向多个人物，请先由作者确认归属")
    return hits[0] if hits else None


def resolve(project, text):
    item = _find(read(project), text)
    return item["id"] if item else None


def upsert_person(project, *, name, aliases=None, profile=None, origin="", person=None, op_id="", _writer_locked=False):
    """新增或更新人物；ID 稳定，别名冲突必须由作者解决。"""
    name = _text(name, 60)
    aliases = [ _text(alias, 60) for alias in (aliases or []) ]
    profile = profile or {}
    unknown_fields = set(profile) - set(PROFILE_FIELDS)
    if unknown_fields:
        raise ValueError("人物档案字段无效")
    with (nullcontext() if _writer_locked else writer.file_lock(_path(project, "writer.lock"))):
        doc = read(project)
        if op_id:
            for row in doc.get("operations", []):
                if row.get("op_id") == op_id:
                    return {"status": "reused", "person": _person_view(doc["persons"][row["person"]])}
        item = doc["persons"].get(person) if person else (_find(doc, name) or None)
        if person and not item:
            raise KeyError("人物不存在")
        for alias in aliases:
            other = _find(doc, alias)
            if other and (not item or other["id"] != item["id"]):
                raise ValueError("别名已被其他人物使用，未合并")
        if item is None:
            item = {"id": uuid.uuid4().hex, "name": name, "aliases": [], "profile": _blank_profile(),
                    "overrides": {}, "record_version": 1, "origin": origin,
                    "created_at": bridge.now_iso(), "updated_at": bridge.now_iso()}
            doc["persons"][item["id"]] = item
        else:
            item["record_version"] = int(item.get("record_version") or 1) + 1
            item["updated_at"] = bridge.now_iso()
        item["name"] = name
        merged = {_norm(x): x for x in item.get("aliases") or []}
        for alias in aliases:
            merged.setdefault(_norm(alias), alias)
        item["aliases"] = [x for x in merged.values() if _norm(x) != _norm(name)]
        if origin and not item.get("origin"):
            item["origin"] = origin
        for field, value in profile.items():
            item["profile"][field] = _text(value, 2000, required=False)
        if op_id:
            doc.setdefault("operations", []).append({"op_id": op_id, "person": item["id"], "at": bridge.now_iso()})
        _commit(project, doc, "person_upsert")
        return {"status": "saved", "person": _person_view(item)}


def correct(project, person, *, field, value, reason=""):
    """作者手动纠正写入 overrides；后续提取不得静默覆盖。"""
    with writer.file_lock(_path(project, "writer.lock")):
        doc = read(project)
        item = doc["persons"].get(person)
        if not item:
            raise KeyError("人物不存在")
        if field not in PROFILE_FIELDS:
            raise ValueError("人物档案字段无效")
        item["overrides"][field] = {"value": _text(value, 2000), "reason": _text(reason, 400, required=False),
                                    "at": bridge.now_iso()}
        item["profile"][field] = item["overrides"][field]["value"]
        item["record_version"] = int(item.get("record_version") or 1) + 1
        item["updated_at"] = bridge.now_iso()
        _commit(project, doc, "author_correction")
        return _person_view(item)


def _person_id(doc, text):
    if text in doc["persons"]:
        return text
    item = _find(doc, text)
    if not item:
        raise ValueError("人物未登记，请先建立档案")
    return item["id"]


def relate(project, *, source, target, kind, direction, chapter, event, quote, sha256, _writer_locked=False):
    """关系变化必须有事件与来源；同一事件只记一次。"""
    with (nullcontext() if _writer_locked else writer.file_lock(_path(project, "writer.lock"))):
        doc = read(project)
        left, right = _person_id(doc, source), _person_id(doc, target)
        if direction not in {"one-way", "mutual"}:
            raise ValueError("关系方向无效")
        if not 1 <= int(chapter) <= 100000 or not re.fullmatch(r"[a-f0-9]{64}", str(sha256 or "")):
            raise ValueError("关系来源无效")
        row = {"id": uuid.uuid4().hex, "source": left, "target": right, "kind": _text(kind, 40),
               "direction": direction, "chapter": int(chapter), "event": _text(event, 400),
               "evidence": {"sha256": sha256, "quote": _text(quote, 800)}, "created_at": bridge.now_iso()}
        for old in doc["relations"]:
            if (old["source"], old["target"], old["kind"], old["chapter"], old["event"]) == \
                    (row["source"], row["target"], row["kind"], row["chapter"], row["event"]):
                return {"status": "reused", "relation": old}
        doc["relations"].append(row)
        _commit(project, doc, "relation_added")
        return {"status": "saved", "relation": row}


def learn(project, *, person, info, chapter, event, scope="character", status="confirmed", quote, sha256, _writer_locked=False):
    """人物获知一条信息：记录事件与章节位置；作者/读者/人物三种认知分开。"""
    with (nullcontext() if _writer_locked else writer.file_lock(_path(project, "writer.lock"))):
        doc = read(project)
        ident = _person_id(doc, person)
        if scope not in SCOPES or status not in STATUSES:
            raise ValueError("认知类别或状态无效")
        if not 1 <= int(chapter) <= 100000 or not re.fullmatch(r"[a-f0-9]{64}", str(sha256 or "")):
            raise ValueError("认知来源无效")
        if not str(quote or "").strip():
            raise ValueError("认知必须带原文依据")
        row = {"id": uuid.uuid4().hex, "person": ident, "info": _text(info, 400), "event": _text(event, 200),
               "chapter": int(chapter), "scope": scope, "status": status,
               "evidence": {"sha256": sha256, "quote": _text(quote, 800)}, "created_at": bridge.now_iso()}
        for old in doc["knowledge"]:
            if (old["person"], old["info"], old["event"], old["chapter"], old["scope"]) == \
                    (row["person"], row["info"], row["event"], row["chapter"], row["scope"]) and old.get("evidence") == row["evidence"]:
                return {"status": "reused", "knowledge": old}
        doc["knowledge"].append(row)
        _commit(project, doc, "knowledge_added")
        return {"status": "saved", "knowledge": row}


def source_status(project, row, cache=None):
    """Keep evidence intact; a changed/missing/ambiguous source needs review."""
    cache = {} if cache is None else cache
    chapter = row.get("chapter")
    if chapter not in cache:
        try:
            body, raw, normalized = _digests(project, chapter)
            cache[chapter] = (body, {raw, normalized})
        except (ValueError, OSError, UnicodeError):
            cache[chapter] = ("", set())
    body, digests = cache[chapter]
    evidence = row.get("evidence") or {}
    return "current" if (evidence.get("sha256") in digests and evidence.get("quote")
                          and evidence["quote"] in body) else "pending_review"


def knows(project, person, chapter, doc=None, cache=None):
    """只返回获知事件确实发生在当前章节之前的认知；猜测单独标注。"""
    doc = read(project) if doc is None else doc
    ident = person if person in doc["persons"] else _person_id(doc, person)
    rows = [row for row in doc["knowledge"] if row["person"] == ident and row["chapter"] < int(chapter)]
    cache = {} if cache is None else cache
    stale = [row for row in rows if source_status(project, row, cache) != "current"]
    rows = [row for row in rows if row not in stale]
    confirmed = [row for row in rows if row["status"] == "confirmed"]
    guesses = [row for row in rows if row["status"] == "guess"]
    return {"confirmed": confirmed, "guess": guesses,
            "pending_review": stale,
            "unknown": "未记录不等于人物不知道；程序只能核对本书记录。"}


def view(project, chapter=0):
    doc = read(project)
    chapter = int(chapter or 0)
    persons = []
    cache = {}
    for item in doc["persons"].values():
        row = _person_view(item)
        knowledge = [entry for entry in doc["knowledge"] if entry["person"] == item["id"]
                     and (not chapter or entry["chapter"] < chapter)]
        relations = [entry for entry in doc["relations"]
                     if item["id"] in (entry["source"], entry["target"])
                     and (not chapter or entry["chapter"] < chapter)]
        row["knowledge"] = [{"id": x["id"], "info": x["info"], "event": x["event"], "chapter": x["chapter"],
                             "scope": x["scope"], "scope_label": SCOPES[x["scope"]],
                             "status": x["status"], "status_label": STATUSES[x["status"]],
                             "source_status": source_status(project, x, cache),
                             "source_status_label": "来源有效" if source_status(project, x, cache) == "current" else "来源已变，待复核",
                             "quote": x["evidence"]["quote"]} for x in sorted(knowledge, key=lambda x: x["chapter"])]
        row["relations"] = [{"id": x["id"], "kind": x["kind"], "direction": x["direction"], "chapter": x["chapter"],
                             "source_status": source_status(project, x, cache),
                             "event": x["event"], "other": x["target"] if x["source"] == item["id"] else x["source"]}
                            for x in sorted(relations, key=lambda x: x["chapter"])]
        persons.append(row)
    names = {pid: item["name"] for pid, item in doc["persons"].items()}
    for row in persons:
        for relation in row["relations"]:
            relation["other_name"] = names.get(relation["other"], "")
    return {"schema_version": SCHEMA, "revision": doc["revision"], "chapter": chapter or None,
            "persons": sorted(persons, key=lambda x: x["name"]), "count": len(persons),
            "note": "同名或别名不会自动合并；作者纠正优先于提取。"}


def context(project, chapter, names=None, doc=None):
    """只挑当前写作相关的人物；没有匹配就不塞整库。"""
    doc = read(project) if doc is None else doc
    wanted = {_norm(name) for name in (names or []) if str(name).strip()}
    lines = ["【人物状态 · 只含当前章节可知的记录】"]
    used = []
    stale = []
    cache = {}
    for item in doc["persons"].values():
        if names is not None and not ({_norm(item["name"])} | {_norm(x) for x in item.get("aliases") or []}) & wanted:
            continue
        row = _person_view(item)
        parts = [f"{row['name']}"]
        if row["aliases"]:
            parts.append("别名 " + "、".join(row["aliases"]))
        for field in ("identity", "goal", "motive", "limits", "voice"):
            if row["profile"].get(field):
                parts.append(f"{field}={row['profile'][field]}")
        known = knows(project, item["id"], chapter, doc, cache)
        stale.extend(row["id"] for row in known["pending_review"])
        for entry in known["confirmed"]:
            if entry["scope"] == "character":
                parts.append(f"第{entry['chapter']}章得知：{entry['info']}")
        for entry in known["guess"]:
            if entry["scope"] == "character":
                parts.append(f"第{entry['chapter']}章起猜疑（未证实）：{entry['info']}")
        lines.append("- " + "；".join(parts))
        used.append(row["id"])
    if not used:
        return {"ids": [], "text": "", "stale": stale}
    lines.append("未知字段保持未知；不要把猜测写成已确认事实，也不要让人物知道本章尚未获知的信息。")
    return {"ids": used, "text": "\n".join(lines), "stale": stale}


def _candidate_rows(review, body, chapter):
    raw = review.get("character_candidates") if isinstance(review, dict) else None
    if not isinstance(raw, list):
        return [], []
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", body))
    kept, dropped = [], []
    for index, entry in enumerate(raw[:MAX_CANDIDATES * 2], 1):
        if len(kept) >= MAX_CANDIDATES:
            dropped.append({"index": index, "reason": "over_limit"})
            continue
        if not isinstance(entry, dict):
            dropped.append({"index": index, "reason": "not_object"})
            continue
        try:
            quote = _text(entry.get("quote"), 800)
        except ValueError:
            dropped.append({"index": index, "reason": "field_invalid"})
            continue
        if len(re.sub(r"\s+", "", quote)) < 4 or quote not in body:
            dropped.append({"index": index, "reason": "quote_not_in_body"})
            continue
        kind = entry.get("kind")
        if kind == "person":
            try:
                name = _text(entry.get("name"), 60)
                field = entry.get("field")
                if field not in PROFILE_FIELDS:
                    raise ValueError("field")
                value = _text(entry.get("value"), 2000)
            except ValueError:
                dropped.append({"index": index, "reason": "field_invalid"})
                continue
            kept.append({"kind": "person", "name": name, "field": field, "value": value, "quote": quote})
        elif kind == "relation":
            kept.append({"kind": "relation", "source": entry.get("source"), "target": entry.get("target"),
                         "relation": _text(entry.get("relation") or "关系变化", 40), "event": _text(entry.get("event"), 200),
                         "quote": quote, "chapter": chapter})
        elif kind == "knowledge":
            kept.append({"kind": "knowledge", "person": entry.get("person"), "info": _text(entry.get("info"), 400),
                         "event": _text(entry.get("event") or "本章获知", 200),
                         "scope": entry.get("scope") if entry.get("scope") in SCOPES else "character",
                         "status": entry.get("status") if entry.get("status") in STATUSES else "confirmed",
                         "quote": quote, "chapter": chapter})
        else:
            dropped.append({"index": index, "reason": "kind_invalid"})
    return kept, dropped


def candidate_path(project, chapter, sha256):
    return _path(project, f"character_candidates/{int(chapter):04d}-{str(sha256)[:16]}.json")


def _digests(project, chapter):
    from fanqie_auto_publish.publication_safety import body_digest

    body_path = [p for p, number in writer._chapter_files(project) if number == chapter]
    if len(body_path) != 1:
        raise ValueError("正文来源缺失或章节重复")
    body = body_path[0].read_text(encoding="utf-8-sig")
    raw = hashlib.sha256(body_path[0].read_bytes()).hexdigest()
    return body, raw, body_digest(body)


def save_candidates(project, chapter, review, body_sha256=None, raw_sha256=None):
    project = Path(project).resolve()
    body, digest, normalized = _digests(project, chapter)
    provided = [value for value in (body_sha256, raw_sha256) if value]
    if provided and not set(provided) & {digest, normalized}:
        raise ValueError("人物候选与当前正文不一致")
    path = candidate_path(project, chapter, digest)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("body_sha256") == digest and existing.get("state") == "committed":
            return {"status": "reused", "count": len(existing.get("candidates") or []), "path": str(path)}
    kept, dropped = _candidate_rows(review, body, chapter)
    writer.atomic_json(path, {"schema_version": 1, "chapter_id": chapter, "body_sha256": digest,
                              "candidates": kept, "dropped": dropped, "state": "pending",
                              "created_at": bridge.now_iso()})
    return {"status": "pending", "count": len(kept), "dropped": len(dropped), "path": str(path)}


def commit_candidates(project, chapter, body_sha256=None, *, _writer_locked=False):
    project = Path(project).resolve()
    body, digest, normalized = _digests(project, chapter)
    if body_sha256 and body_sha256 not in {digest, normalized}:
        raise ValueError("正文已变化，人物候选未提交")
    body_sha256 = digest
    path = candidate_path(project, chapter, digest)
    if not path.exists():
        raise ValueError("没有待提交的人物候选")
    doc_file = json.loads(path.read_text(encoding="utf-8"))
    if doc_file.get("state") == "committed":
        return {"status": "reused", "chapter": chapter}
    if chapter not in writer.reviewed_chapters(project):
        raise ValueError("只能提交具备当前有效审查／E 授权的正文变化")
    added = {"persons": 0, "relations": 0, "knowledge": 0}
    skipped = 0
    for entry in doc_file.get("candidates") or []:
        try:
            if entry["kind"] == "person":
                target = resolve(project, entry["name"])
                if target and entry["field"] in (read(project)["persons"][target].get("overrides") or {}):
                    skipped += 1
                    continue
                before = read(project)["persons"].get(target or "", {}).get("profile", {}).get(entry["field"], "")
                if before and before != entry["value"]:
                    skipped += 1  # 已有不同记录，保持待确认，不静默改写
                    continue
                upsert_person(project, name=entry["name"], profile={entry["field"]: entry["value"]},
                              origin=f"第{chapter}章", person=target, _writer_locked=_writer_locked)
                added["persons"] += 1
            elif entry["kind"] == "relation":
                result = relate(project, source=entry["source"], target=entry["target"], kind=entry["relation"],
                                direction=entry.get("direction", "one-way"), chapter=chapter,
                                event=entry["event"], quote=entry["quote"], sha256=body_sha256, _writer_locked=_writer_locked)
                added["relations"] += 1 if result["status"] == "saved" else 0
            else:
                result = learn(project, person=entry["person"], info=entry["info"], chapter=chapter,
                               event=entry["event"], scope=entry["scope"], status=entry["status"],
                               quote=entry["quote"], sha256=body_sha256, _writer_locked=_writer_locked)
                added["knowledge"] += 1 if result["status"] == "saved" else 0
        except (ValueError, KeyError):
            skipped += 1
    doc_file["state"] = "committed"
    doc_file["applied"] = added
    writer.atomic_json(path, doc_file)
    return {"status": "committed", "chapter": chapter, "added": added, "skipped": skipped}
