"""Paragraph-anchored revision previews.

Text-only helpers: nothing here calls a model.  A preview keeps the candidate
body, the diff, the reason for stopping and the issues that were deliberately
left to the author; accepting it commits through the chapter version store, so
the previous body stays readable and a stale preview can never overwrite a body
the author edited in the meantime.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import chapter_versions
from fanqie_auto_publish.publication_safety import (
    PublicationBlocked,
    atomic_json,
    body_digest,
    file_lock,
    read_json_strict,
)

SCHEMA_VERSION = 1
GROWTH_LIMIT = 0.12
MIN_GUARD_CHARS = 1000
MAX_HUNKS = 40
MAX_INSTRUCTION_ITEMS = 6
MAX_TEXT = 400

STRUCTURAL = re.compile(
    r"情节|动机|设定|时间线|人设|人物关系|伏笔|改名|删除|新增|顺序|因果|逻辑|世界观|金手指|大纲|走向"
)


class AnchorRefused(ValueError):
    """A paragraph anchor cannot be resolved against the current body."""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


class RevisionStopped(RuntimeError):
    """Stopped on purpose; the candidate (if any) is kept for preview."""

    def __init__(self, reason: str, message: str = "", candidate: Optional[str] = None,
                 author_issues: Optional[Iterable[Dict[str, Any]]] = None):
        super().__init__(message or reason)
        self.reason = reason
        self.candidate = candidate
        self.author_issues = list(author_issues or [])


# ------------------------------------------------------------------ 段落锚点

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def paragraphs(text: str) -> List[Dict[str, Any]]:
    """Non-empty lines with their index, offsets and neighbours' digests."""
    lines = text.split("\n")
    rows: List[Dict[str, Any]] = []
    offset = 0
    for raw in lines:
        if raw.strip():
            rows.append({"index": len(rows), "text": raw, "start": offset, "end": offset + len(raw)})
        offset += len(raw) + 1
    for position, row in enumerate(rows):
        row["sha256"] = _sha(row["text"])
        before = rows[position - 1]["text"] if position else ""
        after = rows[position + 1]["text"] if position + 1 < len(rows) else ""
        row["context"] = _sha(before + "\x00" + after)
    return rows


def locate(text: str, original: str) -> Dict[str, Any]:
    """Resolve one replacement target to a unique paragraph anchor."""
    piece = original if isinstance(original, str) else ""
    if not piece.strip():
        raise AnchorRefused("anchor_empty")
    count = text.count(piece)
    if count == 0:
        raise AnchorRefused("anchor_not_found", {"original": piece[:80]})
    if count > 1:
        raise AnchorRefused("anchor_ambiguous", {"original": piece[:80], "occurrences": count})
    for row in paragraphs(text):
        if piece in row["text"]:
            return {"index": row["index"], "sha256": row["sha256"], "context": row["context"],
                    "text": row["text"], "offset": text.find(piece)}
    raise AnchorRefused("anchor_not_in_paragraph", {"original": piece[:80]})


def verify(text: str, anchor: Dict[str, Any]) -> Dict[str, Any]:
    """Re-check an anchor against a possibly edited body."""
    rows = paragraphs(text)
    index = anchor.get("index")
    if not isinstance(index, int) or not 0 <= index < len(rows):
        raise AnchorRefused("anchor_index_moved", {"index": index})
    row = rows[index]
    if row["sha256"] != anchor.get("sha256"):
        raise AnchorRefused("anchor_paragraph_changed", {"index": index})
    if row["context"] != anchor.get("context"):
        raise AnchorRefused("anchor_context_changed", {"index": index})
    return row


def apply_edits(text: str, edits: Iterable[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    """Apply edits with the same uniqueness rule the C executor uses."""
    updated = text
    applied: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for item in edits or []:
        if not isinstance(item, dict):
            skipped.append({"reason": "not_object"})
            continue
        original = str(item.get("original") or "")
        replacement = str(item.get("replacement") or "")
        reason = str(item.get("reason") or "").strip()
        if not original.strip():
            skipped.append({"reason": "original_empty", "original": original[:80]})
            continue
        if original == replacement:
            skipped.append({"reason": "replacement_unchanged", "original": original[:80]})
            continue
        occurrences = updated.count(original)
        if occurrences != 1:
            skipped.append({"reason": f"occurrences:{occurrences}", "original": original[:80]})
            continue
        updated = updated.replace(original, replacement, 1)
        applied.append({"reason": reason, "original": original[:80], "replacement": replacement[:80]})
    return updated, {"applied": applied, "skipped": skipped}


def check_scope(before: str, after: str, patch_report: Optional[Dict[str, Any]],
                edits: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Reject anything the declared edits do not explain.

    The executor's report truncates text for display, so the check works on
    paragraph-level blocks: every changed block must be covered by one of the
    applied edit prefixes, and the number of changed blocks may not exceed the
    number of applied edits.
    """
    report = patch_report if isinstance(patch_report, dict) else {}
    applied = report.get("applied") if isinstance(report.get("applied"), list) else []
    if edits is not None:
        _, applied = apply_edits(before, edits)
    if not applied:
        return {"ok": False, "reason": "no_applicable_edit"}
    if body_digest(before) == body_digest(after):
        return {"ok": False, "reason": "no_change"}

    left = [row["text"] for row in paragraphs(before)]
    right = [row["text"] for row in paragraphs(after)]
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    touched = [(tag, left[i1:i2], right[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]
    if len(touched) > len(applied):
        return {"ok": False, "reason": "outside_patch", "blocks": len(touched), "edits": len(applied)}
    originals = [str(row.get("original") or "") for row in applied]
    replacements = [str(row.get("replacement") or "") for row in applied]
    for tag, old_block, new_block in touched:
        old_text = "\n".join(old_block)
        new_text = "\n".join(new_block)
        if old_text:
            if not any(piece and piece in old_text for piece in originals):
                return {"ok": False, "reason": "outside_patch", "block": _clip(old_text)}
        elif not any(piece and piece in new_text for piece in replacements):
            return {"ok": False, "reason": "outside_patch", "block": _clip(new_text)}
    return {"ok": True, "applied": len(applied), "blocks": len(touched)}


# ------------------------------------------------------------------ 问题分类

def _issues_of(review: Dict[str, Any]) -> List[Dict[str, Any]]:
    quality = review.get("quality") if isinstance(review, dict) else None
    source = quality.get("issues") if isinstance(quality, dict) else None
    if not isinstance(source, list):
        source = review.get("issues") if isinstance(review, dict) else None
    rows = []
    for item in source or []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "dimension": str(item.get("dimension") or ""),
            "severity": str(item.get("severity") or "advisory"),
            "issue": str(item.get("issue") or "").strip(),
            "evidence": str(item.get("evidence") or "").strip(),
            "advice": str(item.get("advice") or "").strip(),
        })
    return [row for row in rows if row["issue"]]


def classify(review: Dict[str, Any]) -> Dict[str, Any]:
    """Split D's issues into locally patchable ones and author decisions."""
    auto: List[Dict[str, Any]] = []
    author: List[Dict[str, Any]] = []
    for row in _issues_of(review):
        local_dimension = row["dimension"] in {"prose", "dialogue", "style"}
        structural = bool(STRUCTURAL.search(row["issue"] + row["advice"]))
        if local_dimension and row["severity"] != "critical" and not structural:
            auto.append(row)
        else:
            author.append(row)
    if not auto and not author and (review.get("review_decision") == "needs_revision"):
        author.append({"dimension": "", "severity": "advisory", "issue": "D 要求修改但未给出可定位问题",
                       "evidence": "", "advice": "请由作者判断修改范围"})
    return {"mode": "targeted_fix" if auto else "none", "auto": auto, "author": author}


def instructions(auto: Iterable[Dict[str, Any]]) -> str:
    rows = list(auto)[:MAX_INSTRUCTION_ITEMS]
    if not rows:
        return ""
    lines = ["【定点修订清单】只处理下列问题，逐条在原文中精确替换；未列出的段落保持原样。"]
    for index, row in enumerate(rows, 1):
        text = f"{index}. （{row.get('dimension') or '文字'}）{row.get('issue')}"
        if row.get("evidence"):
            text += f"；依据：{row['evidence']}"
        if row.get("advice"):
            text += f"；建议：{row['advice']}"
        lines.append(text)
    return "\n".join(lines)


# ------------------------------------------------------------------ 长度与差异

def _chars(text: str, chapter: int) -> int:
    from .length_policy import body_chars
    return body_chars(text, chapter)


def validate_length(before: str, after: str, *, chapter: int, mode: str = "targeted_fix",
                    min_words: int = 0, growth_limit: float = GROWTH_LIMIT) -> Dict[str, Any]:
    """Program-side length policy; the growth guard never blocks a short draft."""
    if body_digest(before) == body_digest(after):
        return {"ok": False, "reason": "no_change"}
    old = _chars(before, chapter)
    new = _chars(after, chapter)
    if min_words and new < min_words:
        return {"ok": False, "reason": "below_min_words", "chars": new, "min_words": min_words}
    if mode == "rewrite" and old >= MIN_GUARD_CHARS and new > old * (1 + growth_limit):
        # 只有“短稿补足到最低字数”可以突破增幅保护；完整稿的扩写仍受限。
        if not (min_words and old < min_words):
            return {"ok": False, "reason": "growth_too_large", "before_chars": old, "after_chars": new,
                    "growth_limit": growth_limit}
    return {"ok": True, "before_chars": old, "after_chars": new}


def _clip(text: str) -> str:
    text = text or ""
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"


def diff(before: str, after: str, *, max_hunks: int = MAX_HUNKS) -> Dict[str, Any]:
    left = [row["text"] for row in paragraphs(before)]
    right = [row["text"] for row in paragraphs(after)]
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    hunks: List[Dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append({"op": tag, "line": i1 + 1, "before": _clip("\n".join(left[i1:i2])),
                      "after": _clip("\n".join(right[j1:j2]))})
    before_chars = len(re.sub(r"\s+", "", before))
    after_chars = len(re.sub(r"\s+", "", after))
    return {
        "changes": len(hunks),
        "hunks": hunks[:max_hunks],
        "truncated": len(hunks) > max_hunks,
        "before_chars": before_chars,
        "after_chars": after_chars,
        "delta_chars": after_chars - before_chars,
        "ratio": round(abs(after_chars - before_chars) / max(1, before_chars), 4),
    }


# ------------------------------------------------------------------ 预览存储

def previews_dir(project) -> Path:
    return Path(project) / ".webnovel" / "revision_previews"


def _preview_path(project, chapter: int, preview_id: str) -> Path:
    return previews_dir(project) / f"{int(chapter):04d}-{preview_id}.json"


def save_preview(project, chapter: int, before: str, after: str, *, base_sha256: Optional[str] = None,
                 contract_hash: str = "", mode: str = "targeted_fix",
                 auto_issues: Iterable[Dict[str, Any]] = (), author_issues: Iterable[Dict[str, Any]] = (),
                 patch_report: Optional[Dict[str, Any]] = None, stop_reason: str = "",
                 preview_id: Optional[str] = None) -> Dict[str, Any]:
    """Store the candidate body plus its diff; does not touch 正文."""
    project = Path(project)
    folder = previews_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    identity = preview_id or uuid.uuid4().hex[:16]
    candidate = chapter_versions.save_candidate(
        project, chapter, after, source="revision", base_sha256=base_sha256, note=stop_reason or "revision preview")
    record = {
        "schema_version": SCHEMA_VERSION,
        "preview_id": identity,
        "chapter_id": int(chapter),
        "base_sha256": base_sha256,
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": candidate["sha256"],
        "candidate_body_digest": candidate["body_digest"],
        "contract_hash": contract_hash,
        "mode": mode,
        "auto_issues": list(auto_issues or []),
        "author_issues": list(author_issues or []),
        "patch_report": patch_report or {},
        "diff": diff(before, after),
        "stop_reason": stop_reason,
        "state": "pending",
        "created_at": chapter_versions._now(),
    }
    path = _preview_path(project, chapter, identity)
    with file_lock(folder / ".lock"):
        atomic_json(path, record)
    return {k: v for k, v in record.items() if k != "patch_report"}


def load_preview(project, chapter: int, preview_id: str) -> Dict[str, Any]:
    path = _preview_path(project, chapter, preview_id)
    if not path.is_file():
        raise chapter_versions.VersionNotFound("preview_missing")
    record = read_json_strict(path)
    if not isinstance(record, dict) or record.get("chapter_id") != int(chapter):
        raise chapter_versions.VersionCorrupt("preview_damaged")
    return record


def list_previews(project, chapter: int) -> List[Dict[str, Any]]:
    folder = previews_dir(project)
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob(f"{int(chapter):04d}-*.json")):
        try:
            record = read_json_strict(path)
        except PublicationBlocked:
            continue
        if isinstance(record, dict) and record.get("chapter_id") == int(chapter):
            rows.append(record)
    rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return rows


def latest(project, chapter: int, *, pending_only: bool = True) -> Optional[Dict[str, Any]]:
    for record in list_previews(project, chapter):
        if not pending_only or record.get("state") == "pending":
            return record
    return None


def public(project, chapter: int) -> Dict[str, Any]:
    record = latest(project, chapter)
    if not record:
        return {"chapter_id": int(chapter), "preview": None}
    return {
        "chapter_id": int(chapter),
        "preview": {
            "preview_id": record["preview_id"],
            "state": record.get("state"),
            "stop_reason": record.get("stop_reason") or "",
            "mode": record.get("mode"),
            "created_at": record.get("created_at"),
            "base_sha256": record.get("base_sha256"),
            "candidate_sha256": record.get("candidate_sha256"),
            "diff": record.get("diff") or {},
            "author_issues": record.get("author_issues") or [],
            "auto_issues": record.get("auto_issues") or [],
        },
    }


def _mark(project, chapter: int, preview_id: str, state: str, **extra) -> Dict[str, Any]:
    record = load_preview(project, chapter, preview_id)
    record.update(state=state, updated_at=chapter_versions._now(), **extra)
    path = _preview_path(project, chapter, preview_id)
    with file_lock(previews_dir(project) / ".lock"):
        atomic_json(path, record)
    return record


def accept(project, chapter: int, preview_id: str, *, expected_sha256: Optional[str] = None,
           op_id: Optional[str] = None) -> Dict[str, Any]:
    """Commit the candidate, refusing if the body moved since the preview."""
    record = load_preview(project, chapter, preview_id)
    if record.get("state") != "pending":
        raise chapter_versions.VersionConflict("preview_already_closed")
    base = expected_sha256 if expected_sha256 is not None else record.get("base_sha256")
    current = chapter_versions.file_sha256(chapter_versions.chapter_path(project, chapter))
    if base is not None and current != base:
        raise chapter_versions.VersionConflict("source_changed")
    commit = chapter_versions.commit_candidate(
        project, chapter, record["candidate_id"], op_id=op_id or f"preview-{preview_id}",
        expected_sha256=current, allow_new=current is None)
    _mark(project, chapter, preview_id, "accepted", accepted_at=chapter_versions._now())
    return {"status": "accepted", "chapter_id": int(chapter), "preview_id": preview_id,
            "sha256": commit.get("content_sha256") or commit.get("sha256"), "commit": commit}


def reject(project, chapter: int, preview_id: str, reason: str = "") -> Dict[str, Any]:
    record = load_preview(project, chapter, preview_id)
    if record.get("state") != "pending":
        raise chapter_versions.VersionConflict("preview_already_closed")
    _mark(project, chapter, preview_id, "rejected", reject_reason=str(reason or "")[:200])
    return {"status": "rejected", "chapter_id": int(chapter), "preview_id": preview_id}
