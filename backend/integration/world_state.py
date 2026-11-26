"""长篇小说世界状态引擎（确定性核心）。

Storage is the per-book ``workbench.sqlite3`` (never a second database).  The
engine unifies the existing memory/character/entity/continuity concepts under
eight fact domains and provides:

* deterministic five-layer context assembly with a transparent
  ``context_manifest`` (L1 rules → L2 long-term → L3 volume → L4 recent →
  L5 retrieval);
* Python 2-gram + single-character FTS5 search (two-character Chinese names);
* manual pinned cards with ``entity_id`` / ``pinned`` / ``story_time``;
* chapter-scoped validity windows and authority precedence;
* an author-ignored conflict ledger so intentional twists are not re-reported.

AI extraction and causal impact analysis live in the same module but only run
when a caller supplies a model callback (plan phase 4).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from integration import chapter_editor, outline_editor
from integration import chapter_versions as versions
from integration import text_merge
from integration import workbench_db as wb

DOMAINS = {"character", "knowledge", "item", "timeline", "world_rule", "foreshadow",
           "event_fact", "author_rule"}
ASSERTION_TYPES = {"fact", "rumor", "lie", "belief"}
AUTHORITY = {"discarded_candidate": 0, "future_plan": 1, "ai_inferred": 2,
             "draft_prose": 3, "confirmed_prose": 4, "published_prose": 5,
             "author_locked": 6}
FACT_STATUSES = {"active", "pending_confirm", "superseded", "needs_review",
                 "conflicted", "ignored_by_author", "archived"}
HIGH_RISK_PREDICATES = {"死亡", "死了", "身亡", "销毁", "永久丢失", "身份暴露", "秘密暴露"}


class WorldStateError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))


def _token_estimate(text: str) -> int:
    # Deterministic, deliberately conservative: CJK ~1.5 chars/token, latin ~4.
    cjk = sum(1 for ch in str(text) if 0x3400 <= ord(ch) <= 0x9FFF)
    other = len(str(text)) - cjk
    return int(cjk / 1.5 + other / 4) + 1


def token_estimate(text: str) -> int:
    return _token_estimate(text)


def _row_fact(row) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["exceptions"] = json.loads(item.pop("exceptions_json") or "[]")
    except ValueError:
        item["exceptions"] = []
    item["pinned"] = bool(item.get("pinned"))
    item["author_locked"] = bool(item.get("author_locked"))
    return item


def upsert_fact(project, fact: Dict[str, Any]) -> Dict[str, Any]:
    """Insert/update one fact with authority + status validation.

    The same logical fact (entity + predicate + object + validity window) is
    updated instead of duplicated; a lower-authority inference never overwrites
    a higher-authority row.
    """
    domain = str(fact.get("domain") or "")
    if domain not in DOMAINS:
        raise WorldStateError("invalid_domain")
    assertion = str(fact.get("assertion_type") or "fact")
    if assertion not in ASSERTION_TYPES:
        raise WorldStateError("invalid_assertion_type")
    authority = str(fact.get("authority_level") or "ai_inferred")
    if authority not in AUTHORITY:
        raise WorldStateError("invalid_authority")
    status = str(fact.get("status") or "active")
    if status not in FACT_STATUSES:
        raise WorldStateError("invalid_status")
    fact_id = str(fact.get("fact_id") or wb.new_id("fact"))
    confidence = float(fact.get("confidence") or 0.0)
    if not 0.0 <= confidence <= 1.0:
        raise WorldStateError("invalid_confidence")
    pinned = 1 if fact.get("pinned") else 0
    with wb.write_tx(project) as db:
        existing = db.execute("SELECT * FROM world_facts WHERE fact_id=?", (fact_id,)).fetchone()
        if existing:
            previous = _row_fact(existing)
            if AUTHORITY.get(previous.get("authority_level"), 0) > AUTHORITY.get(authority, 0):
                return {"status": "ignored_lower_authority", "fact": previous}
        db.execute(
            "INSERT INTO world_facts(fact_id, entity_id, pinned, domain, assertion_type, subject, "
            "predicate, object, story_time, narrative_chapter, valid_from_chapter, valid_until_chapter, "
            "effective_from_chapter, exceptions_json, source_chapter, source_chapter_uid, source_version_id, "
            "source_quote, authority_level, confidence, status, author_locked, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(fact_id) DO UPDATE SET entity_id=excluded.entity_id, pinned=excluded.pinned, "
            "domain=excluded.domain, assertion_type=excluded.assertion_type, subject=excluded.subject, "
            "predicate=excluded.predicate, object=excluded.object, story_time=excluded.story_time, "
            "narrative_chapter=excluded.narrative_chapter, valid_from_chapter=excluded.valid_from_chapter, "
            "valid_until_chapter=excluded.valid_until_chapter, effective_from_chapter=excluded.effective_from_chapter, "
            "exceptions_json=excluded.exceptions_json, source_chapter=excluded.source_chapter, "
            "source_chapter_uid=excluded.source_chapter_uid, source_version_id=excluded.source_version_id, "
            "source_quote=excluded.source_quote, authority_level=excluded.authority_level, "
            "confidence=excluded.confidence, status=excluded.status, author_locked=excluded.author_locked, "
            "updated_at=excluded.updated_at",
            (fact_id, fact.get("entity_id"), pinned, domain, assertion, str(fact.get("subject") or ""),
             str(fact.get("predicate") or ""), str(fact.get("object") or ""), fact.get("story_time"),
             fact.get("narrative_chapter"), fact.get("valid_from_chapter"), fact.get("valid_until_chapter"),
             fact.get("effective_from_chapter"),
             json.dumps(list(fact.get("exceptions") or []), ensure_ascii=False),
             fact.get("source_chapter"), fact.get("source_chapter_uid"), fact.get("source_version_id"),
             fact.get("source_quote"), authority, confidence, status,
             1 if fact.get("author_locked") else 0, _now()),
        )
    return {"status": "saved", "fact": get_fact(project, fact_id)}


def get_fact(project, fact_id: str) -> Dict[str, Any]:
    wb.initialize(project)
    with wb.connect(project) as db:
        row = db.execute("SELECT * FROM world_facts WHERE fact_id=?", (fact_id,)).fetchone()
    if not row:
        raise WorldStateError("fact_missing", status=404)
    return _row_fact(row)


def set_fact_status(project, fact_id: str, status: str) -> Dict[str, Any]:
    if status not in FACT_STATUSES:
        raise WorldStateError("invalid_status")
    with wb.write_tx(project) as db:
        db.execute("UPDATE world_facts SET status=?, updated_at=? WHERE fact_id=?",
                   (status, _now(), fact_id))
    return get_fact(project, fact_id)


def facts_for_chapter(project, chapter: int, *, domain: Optional[str] = None,
                      entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Only facts valid at narrative chapter N; future plans are excluded here."""
    clauses = ["status='active'",
               "(valid_from_chapter IS NULL OR valid_from_chapter <= ?)",
               "(valid_until_chapter IS NULL OR valid_until_chapter >= ?)"]
    params: List[Any] = [int(chapter), int(chapter)]
    if domain:
        clauses.append("domain=?"); params.append(domain)
    if entity_id:
        clauses.append("entity_id=?"); params.append(entity_id)
    wb.initialize(project)
    with wb.connect(project) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM world_facts WHERE " + " AND ".join(clauses) +
            " ORDER BY pinned DESC, authority_level DESC, narrative_chapter", tuple(params))]
    return [_row_fact(row) for row in rows]


def set_card(project, card: Dict[str, Any]) -> Dict[str, Any]:
    entity_id = str(card.get("entity_id") or wb.new_id("ent"))
    name = str(card.get("name") or "").strip()
    if not name:
        raise WorldStateError("card_name_required")
    wb.initialize(project)
    kind = str(card.get("kind") or "character")
    aliases = list(card.get("aliases") or [])
    with wb.write_tx(project) as db:
        db.execute(
            "INSERT INTO world_entities(entity_id, name, kind, aliases_json, pinned, story_time, card_md, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET name=excluded.name, kind=excluded.kind, "
            "aliases_json=excluded.aliases_json, pinned=excluded.pinned, story_time=excluded.story_time, "
            "card_md=excluded.card_md, updated_at=excluded.updated_at",
            (entity_id, name, kind, json.dumps(aliases, ensure_ascii=False),
             1 if card.get("pinned") else 0, card.get("story_time"), str(card.get("card_md") or ""), _now()),
        )
    return get_card(project, entity_id)


def get_card(project, entity_id: str) -> Dict[str, Any]:
    wb.initialize(project)
    with wb.connect(project) as db:
        row = db.execute("SELECT * FROM world_entities WHERE entity_id=?", (entity_id,)).fetchone()
    if not row:
        raise WorldStateError("card_missing", status=404)
    item = dict(row)
    item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
    item["pinned"] = bool(item.get("pinned"))
    return item


def list_cards(project, *, pinned_only: bool = False) -> List[Dict[str, Any]]:
    wb.initialize(project)
    query = "SELECT * FROM world_entities" + (" WHERE pinned=1" if pinned_only else "") + \
            " ORDER BY pinned DESC, name"
    with wb.connect(project) as db:
        rows = [dict(row) for row in db.execute(query)]
    for item in rows:
        item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
        item["pinned"] = bool(item.get("pinned"))
    return rows


def index_chapter(project, chapter: int) -> int:
    path = versions.chapter_path(project, chapter)
    if path is None:
        return 0
    text = path.read_bytes().decode("utf-8", errors="replace").lstrip("\ufeff")
    meta = versions.current_version(project, chapter) or {}
    wb.index_document(project, doc_key=f"正文:{chapter}", kind="chapter", chapter_id=chapter,
                      title=(meta.get("title") or path.stem), content=text)
    return 1


def search(project, query: str, *, chapter: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
    hits = wb.search(project, query, limit=limit)
    if chapter is not None:
        hits = [hit for hit in hits if hit.get("chapter_id") in (None, int(chapter))]
    return hits


def ignore_conflict(project, fact_id: str, *, chapter_uid: str, version_id: str = "",
                    reason: str = "intentional_or_flashback") -> Dict[str, Any]:
    with wb.write_tx(project) as db:
        db.execute("INSERT OR REPLACE INTO conflict_ignores(fact_id, chapter_uid, version_id, reason, created_at) "
                   "VALUES(?,?,?,?,?)", (fact_id, chapter_uid, version_id, reason, _now()))
        db.execute("UPDATE world_facts SET status='ignored_by_author', updated_at=? WHERE fact_id=?",
                   (_now(), fact_id))
    return {"status": "ignored", "fact_id": fact_id, "chapter_uid": chapter_uid, "reason": reason}


def is_ignored(project, fact_id: str, chapter_uid: str, version_id: str) -> bool:
    wb.initialize(project)
    with wb.connect(project) as db:
        row = db.execute("SELECT 1 FROM conflict_ignores WHERE fact_id=? AND chapter_uid=? "
                         "AND (version_id=? OR version_id='')",
                         (fact_id, chapter_uid, version_id)).fetchone()
    return bool(row)


def detect_conflicts(project, chapter: int) -> List[Dict[str, Any]]:
    """Same entity/predicate with incompatible objects at the same story time."""
    facts = facts_for_chapter(project, chapter)
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for fact in facts:
        if fact.get("assertion_type") in {"lie", "rumor"}:
            continue
        key = (str(fact.get("entity_id") or fact.get("subject") or ""),
               str(fact.get("predicate") or ""))
        grouped.setdefault(key, []).append(fact)
    conflicts = []
    for (entity, predicate), rows in grouped.items():
        if len(rows) < 2:
            continue
        objects = {_normalize(row.get("object")) for row in rows}
        if len(objects) > 1:
            chapter_uid = wb.chapter_uid(project, chapter)
            version_id = (versions.current_version(project, chapter) or {}).get("version_id") or ""
            live = [row for row in rows if not is_ignored(project, row["fact_id"], chapter_uid, version_id)]
            if len({_normalize(row.get("object")) for row in live}) > 1:
                conflicts.append({"entity_id": entity, "predicate": predicate,
                                  "facts": [{key: row.get(key) for key in
                                             ("fact_id", "object", "story_time", "source_chapter",
                                              "source_quote", "authority_level", "status")}
                                            for row in live],
                                  "message": f"{entity} 的「{predicate}」存在相互矛盾的事实"})
    return conflicts


# ------------------------------------------------------------- context pack

def _rules(project, chapter: int) -> List[Dict[str, Any]]:
    try:
        from integration import memory_library
        items = memory_library.contract(project)
    except Exception:
        return []
    result = []
    for item in items:
        effective = item.get("effective_from_chapter")
        if isinstance(effective, int) and effective > int(chapter):
            continue
        result.append(item)
    return result


def _outline_for(project, chapter: int) -> Dict[str, Any]:
    try:
        plan = outline_editor.recover_plan(project, persist=False)
        return plan.get("chapters", {}).get(str(int(chapter))) or {}
    except Exception:
        return {}


def _previous_tail(project, chapter: int, limit: int = 300) -> str:
    if chapter <= 1:
        return ""
    path = versions.chapter_path(project, chapter - 1)
    if path is None:
        return ""
    text = path.read_bytes().decode("utf-8", errors="replace").lstrip("\ufeff")
    points = text_merge.to_codepoints(text)
    return "".join(points[-limit:])


def build_context(project, chapter: int, *, query: str = "", budget_chars: int = 24000,
                  operation_id: Optional[str] = None) -> Dict[str, Any]:
    """Five-layer deterministic context + manifest (no model call)."""
    chapter = int(chapter)
    layers: List[Dict[str, Any]] = []

    def add(layer: str, title: str, items: List[Dict[str, Any]], text: str, char_share: float):
        layers.append({"layer": layer, "title": title, "items": items, "text": text,
                       "chars": len(text), "tokens": _token_estimate(text),
                       "share": char_share})

    rules = _rules(project, chapter)
    rule_text = "\n".join(f"- {item.get('title')}: {item.get('content')}" for item in rules)
    add("L1", "核心创作契约", [{"kind": "author_rule", "id": item.get("id"),
                              "effective_from_chapter": item.get("effective_from_chapter")}
                             for item in rules], rule_text, 0.10)
    cards = list_cards(project, pinned_only=True)
    facts = facts_for_chapter(project, chapter)
    pinned = [fact for fact in facts if fact.get("pinned") or fact.get("authority_level") in
              {"author_locked", "confirmed_prose", "published_prose"}]
    l2_text = "\n".join(
        [f"- 人物卡 {card['name']}（{card['kind']}）：{card.get('card_md', '')}" for card in cards] +
        [f"- {fact.get('subject')}{fact.get('predicate')}{fact.get('object')}" for fact in pinned[:40]])
    add("L2", "全书长期记忆", [{"kind": "card", "entity_id": card["entity_id"]} for card in cards] +
        [{"kind": "fact", "fact_id": fact["fact_id"]} for fact in pinned[:40]], l2_text, 0.20)
    outline = _outline_for(project, chapter)
    l3_text = f"- 本章细纲：{outline.get('title', '')} {outline.get('outline', '')}".strip()
    add("L3", "分卷中期记忆", [{"kind": "outline", "chapter": chapter}], l3_text, 0.15)
    previous = _previous_tail(project, chapter)
    l4_text = f"- 上一章结尾：{previous}\n- 本章细纲：{outline.get('outline', '')}"
    add("L4", "近期短期记忆", [{"kind": "previous_chapter", "chapter": chapter - 1},
                              {"kind": "outline", "chapter": chapter}], l4_text, 0.30)
    hits = search(project, query, limit=8) if str(query or "").strip() else []
    l5_text = "\n".join(f"- 第{hit.get('chapter_id') or '?'}章：{hit.get('snippet', '')}" for hit in hits)
    add("L5", "按需精确检索", [{"kind": "retrieval", "doc_key": hit.get("doc_key"),
                                "chapter_id": hit.get("chapter_id")} for hit in hits], l5_text, 0.25)
    # Budget trimming: drop L5 then L3 tails first, never L1 rules.
    total = sum(layer["chars"] for layer in layers)
    for layer in sorted(layers, key=lambda item: item["layer"] in {"L1", "L2", "L4"}):
        if total <= budget_chars:
            break
        overflow = total - budget_chars
        text = layer["text"]
        if layer["layer"] == "L1":
            continue
        keep = max(0, len(text) - overflow)
        layer["text"] = text[:keep]
        layer["chars"] = len(layer["text"])
        layer["tokens"] = _token_estimate(layer["text"])
        layer["trimmed"] = True
        total = sum(item["chars"] for item in layers)
    text = "\n\n".join(f"【{layer['layer']}·{layer['title']}】\n{layer['text']}"
                       for layer in layers if layer["text"])
    manifest = {
        "chapter_id": chapter,
        "chapter_uid": wb.chapter_uid(project, chapter),
        "query": query,
        "budget_chars": budget_chars,
        "chars": len(text),
        "tokens": _token_estimate(text),
        "layers": [{key: layer.get(key) for key in
                    ("layer", "title", "chars", "tokens", "share", "trimmed")} for layer in layers],
        "items": [{**item, "layer": layer["layer"]} for layer in layers for item in layer["items"]],
        "generated_at": _now(),
    }
    with wb.write_tx(project) as db:
        db.execute("INSERT INTO context_manifests(chapter_id, operation_id, manifest_json, created_at) "
                   "VALUES(?,?,?,?)",
                   (chapter, operation_id, json.dumps(manifest, ensure_ascii=False), _now()))
    return {"text": text, "manifest": manifest}


def state(project, *, chapter: int = 1, query: str = "") -> Dict[str, Any]:
    """Read-only world-state dashboard: cards, valid facts, conflicts, manifest."""
    chapter = max(1, int(chapter))
    context = build_context(project, chapter, query=query)
    return {"chapter_id": chapter, "cards": list_cards(project),
            "facts": facts_for_chapter(project, chapter),
            "conflicts": detect_conflicts(project, chapter),
            "manifest": context["manifest"], "context": context["text"],
            "search": search(project, query, chapter=chapter) if query else []}


def latest_manifest(project, chapter: int) -> Optional[Dict[str, Any]]:
    wb.initialize(project)
    with wb.connect(project) as db:
        row = db.execute("SELECT manifest_json FROM context_manifests WHERE chapter_id=? "
                         "ORDER BY id DESC LIMIT 1", (int(chapter),)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return None


# ------------------------------------------------------------ phase 4 hooks

def extract_candidates(project, chapter: int, payload: Dict[str, Any], *,
                       extractor: Optional[Callable[[Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """AI increment extraction with the dirty-data guardrails.

    High-risk changes to pinned entities are never auto-active: they land in
    ``pending_confirm``.  Low-confidence facts do not overwrite existing rows.
    """
    if extractor is not None:
        payload = extractor(payload)
    facts = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts, list) or len(facts) > 32:
        raise WorldStateError("invalid_extraction")
    accepted, pending, rejected = [], [], []
    for raw in facts:
        if not isinstance(raw, dict):
            rejected.append({"reason": "not_object"})
            continue
        domain = str(raw.get("domain") or "")
        if domain not in DOMAINS:
            rejected.append({"reason": "invalid_domain"})
            continue
        confidence = float(raw.get("confidence") or 0)
        assertion = str(raw.get("assertion_type") or "fact")
        if assertion not in ASSERTION_TYPES:
            rejected.append({"reason": "invalid_assertion_type"})
            continue
        if confidence < 0.75:
            rejected.append({"reason": "low_confidence", "confidence": confidence})
            continue
        fact = {
            **raw, "fact_id": raw.get("fact_id") or wb.new_id("fact"),
            "confidence": confidence, "assertion_type": assertion,
            "narrative_chapter": chapter, "source_chapter": chapter,
            "source_chapter_uid": wb.chapter_uid(project, chapter),
            "source_version_id": (versions.current_version(project, chapter) or {}).get("version_id"),
            "status": "active", "authority_level": raw.get("authority_level") or "confirmed_prose",
        }
        high_risk = (fact.get("pinned") and assertion == "fact" and
                     any(word in str(fact.get("predicate") or "") or word in str(fact.get("object") or "")
                         for word in HIGH_RISK_PREDICATES))
        if high_risk:
            fact["status"] = "pending_confirm"
            saved = upsert_fact(project, fact)
            pending.append(saved["fact"])
        else:
            saved = upsert_fact(project, fact)
            accepted.append(saved["fact"])
    return {"status": "extracted", "accepted": accepted, "pending_confirm": pending,
            "rejected": rejected, "counts": {"accepted": len(accepted),
                                              "pending_confirm": len(pending),
                                              "rejected": len(rejected)}}


def confirm_fact(project, fact_id: str) -> Dict[str, Any]:
    return set_fact_status(project, fact_id, "active")


def reject_fact(project, fact_id: str) -> Dict[str, Any]:
    return set_fact_status(project, fact_id, "superseded")


def causal_scan(project, *, change: str, apply_to_existing: bool = True,
                effective_from_chapter: Optional[int] = None) -> Dict[str, Any]:
    """Five-group causal impact for a whole-book change (deterministic part).

    ``apply_to_existing=False`` defaults the new rule to
    ``max_existing_chapter + 1`` so old chapters keep their qualification.
    """
    mapping = versions.chapter_map(project)
    max_existing = max(mapping) if mapping else 0
    keyword = str(change or "").strip()
    if not keyword:
        raise WorldStateError("change_required")
    groups = {"direct": [], "likely": [], "indirect": [], "future_plan": [], "exempt": []}
    words = [word for word in re.split(r"[\s，。、“”「」]+", keyword) if len(word) >= 2][:8]
    for chapter in sorted(mapping):
        text = mapping[chapter].read_bytes().decode("utf-8", errors="replace")
        hits = [word for word in words if word in text]
        if not hits:
            groups["exempt"].append({"chapter": chapter, "reason": "no_hit"})
        elif any(word in text for word in ("葬礼", "尸体", "遗嘱", "死亡", "复仇")):
            groups["direct"].append({"chapter": chapter, "hits": hits})
        else:
            groups["likely"].append({"chapter": chapter, "hits": hits})
    try:
        plan = outline_editor.recover_plan(project, persist=False)
        for key, item in plan.get("chapters", {}).items():
            if int(key) > max_existing and any(word in str(item.get("outline") or "") for word in words):
                groups["future_plan"].append({"chapter": int(key), "title": item.get("title"),
                                              "hits": [word for word in words
                                                       if word in str(item.get("outline") or "")]})
    except Exception:
        pass
    effective = effective_from_chapter
    if effective is None:
        effective = max_existing + 1 if not apply_to_existing else 1
    return {"status": "scanned", "change": change, "effective_from_chapter": effective,
            "apply_to_existing": apply_to_existing, "max_existing_chapter": max_existing,
            "groups": groups,
            "estimated_calls": len(groups["direct"]) + len(groups["likely"]) + len(groups["future_plan"])}


def add_exemption(project, *, chapter: int, rule_id: str, rule_text: str,
                  scan_method: str = "keyword_only") -> Dict[str, Any]:
    meta = versions.current_version(project, chapter) or {}
    path = versions.chapter_path(project, chapter)
    content_sha = versions.file_sha256(path) if path else ""
    if not content_sha:
        raise WorldStateError("chapter_missing", status=404)
    with wb.write_tx(project) as db:
        db.execute("INSERT OR REPLACE INTO directive_exemptions(chapter_id, chapter_uid, version_id, "
                   "content_sha256, rule_id, rule_content_sha256, scan_method, confirmed_by, verified_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?)",
                   (int(chapter), wb.chapter_uid(project, chapter), meta.get("version_id"), content_sha,
                    rule_id, _sha(rule_text), scan_method, "author", _now()))
    return {"status": "exempted", "chapter_id": int(chapter), "rule_id": rule_id,
            "content_sha256": content_sha}
