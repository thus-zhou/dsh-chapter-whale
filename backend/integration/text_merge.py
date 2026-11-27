"""选区锚点重定位与同章三方合并引擎（纯函数，零模型依赖）。

All offsets are ``unicode_codepoint_lf``: text is LF-normalised first, then
indexed by Unicode code points (not UTF-16 units).  The backend is the single
source of truth for review-mode highlight ranges; the browser never re-runs
this algorithm on its own.

Four-stage relocation (plan ``02`` §3.1):

1. exact — the whole document is byte-identical to the anchor snapshot;
2. diff-mapped — map through unchanged blocks and re-check speaker context;
3. overlap — the author rewrote the anchored range itself;
4. unplaceable — deleted/ambiguous, keep the candidate and ask the author.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

CONTEXT_CHARS = 64
MATCH_THRESHOLD = 0.78
MARGIN_THRESHOLD = 0.15


def normalize_lf(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def to_codepoints(text: str) -> List[str]:
    return list(normalize_lf(text))


def codepoint_length(text: str) -> int:
    return len(to_codepoints(text))


def slice_codepoints(text: str, start: int, end: int) -> str:
    points = to_codepoints(text)
    return "".join(points[max(0, int(start)):max(0, int(end))])


def clamp_range(text: str, start: int, end: int) -> Tuple[int, int]:
    length = codepoint_length(text)
    start = max(0, min(int(start), length))
    end = max(start, min(int(end), length))
    return start, end


def paragraph_index(text: str, offset: int) -> int:
    text = normalize_lf(text)
    offset = max(0, min(int(offset), codepoint_length(text)))
    return normalize_lf(text).count("\n", 0, offset) if offset else 0


def context_of(text: str, start: int, end: int, *, size: int = CONTEXT_CHARS) -> Tuple[str, str]:
    points = to_codepoints(text)
    start, end = clamp_range(text, start, end)
    return "".join(points[max(0, start - size):start]), "".join(points[end:end + size])


def _context_score(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def context_similarity(prefix_a: str, suffix_a: str, prefix_b: str, suffix_b: str) -> float:
    """Weighted neighbour similarity; a matching speaker line dominates."""
    before = _context_score(prefix_a[-CONTEXT_CHARS:], prefix_b[-CONTEXT_CHARS:])
    after = _context_score(suffix_a[:CONTEXT_CHARS], suffix_b[:CONTEXT_CHARS])
    return round(0.55 * before + 0.45 * after, 6)


def _map_position(base: str, current: str, position: int) -> Optional[int]:
    a = to_codepoints(base)
    b = to_codepoints(current)
    position = max(0, min(int(position), len(a)))
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal" and i1 <= position <= i2:
            return j1 + (position - i1)
    return None


def _point_in_replace(base: str, current: str, position: int) -> bool:
    a = to_codepoints(base)
    b = to_codepoints(current)
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in {"replace", "delete"} and i1 <= position <= i2:
            return True
        if tag == "insert" and i1 == i2 == position:
            return True
    return False



def _map_range(base: str, current: str, start: int, end: int) -> Optional[Tuple[int, int]]:
    """Map a base range into current using unchanged diff blocks only."""
    a = to_codepoints(base)
    b = to_codepoints(current)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" and i1 <= start and end <= i2:
            shift = j1 - i1
            return start + shift, end + shift
    return None


def _range_in_replace(base: str, current: str, start: int, end: int) -> bool:
    a = to_codepoints(base)
    b = to_codepoints(current)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in {"replace", "delete"} and i1 < end and start < i2:
            return True
        if tag == "insert" and i1 == i2 and start <= i1 <= end:
            return True
    return False


def relocate_anchor(base_text: str, current_text: str, anchor: Dict[str, Any]) -> Dict[str, Any]:
    """Four-stage relocation, returning machine-readable status + range."""
    base = normalize_lf(base_text)
    current = normalize_lf(current_text)
    quote = normalize_lf(str(anchor.get("quote") or ""))
    if not quote:
        return {"status": "relocated_needed", "reason": "empty_quote", "start": None, "end": None}
    start = int(anchor.get("char_start") or 0)
    end = int(anchor.get("char_end") or 0)
    start, end = clamp_range(base, start, end)
    base_snapshot = str(anchor.get("base_snapshot_id") or "")
    points = to_codepoints(current)

    # Level 1: whole document unchanged.
    if base_snapshot and sha256(current) == base_snapshot:
        if "".join(points[start:end]) == quote:
            return {"status": "exact", "start": start, "end": end, "score": 1.0,
                    "level": 1, "quote": quote}

    prefix_a, suffix_a = context_of(base, start, end)
    anchor["prefix_ctx"] = anchor.get("prefix_ctx") or prefix_a
    anchor["suffix_ctx"] = anchor.get("suffix_ctx") or suffix_a
    prefix_a = str(anchor.get("prefix_ctx") or prefix_a)
    suffix_a = str(anchor.get("suffix_ctx") or suffix_a)

    # Level 2a: map through an unchanged block.
    mapped = _map_range(base, current, start, end)
    if mapped is not None:
        m_start, m_end = mapped
        if "".join(points[m_start:m_end]) == quote:
            p_b, s_b = context_of(current, m_start, m_end)
            score = context_similarity(prefix_a, suffix_a, p_b, s_b)
            # Diff-mapping through an unchanged block is strong evidence; the
            # 0.78 threshold is reserved for free-text candidate search below.
            if score >= 0.5 or not str(anchor.get("prefix_ctx") or anchor.get("suffix_ctx") or ""):
                return {"status": "relocated", "start": m_start, "end": m_end,
                        "score": score, "level": 2, "quote": quote}

    # Level 2b: search every exact quote occurrence, require a unique winner.
    candidates: List[Dict[str, Any]] = []
    cursor = 0
    while True:
        found = current.find(quote, cursor)
        if found < 0:
            break
        c_start, c_end = found, found + len(quote)
        p_b, s_b = context_of(current, c_start, c_end)
        score = context_similarity(prefix_a, suffix_a, p_b, s_b)
        candidates.append({"start": c_start, "end": c_end, "score": score})
        cursor = found + max(1, len(quote))
    if candidates:
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        best = ranked[0]
        second = ranked[1]["score"] if len(ranked) > 1 else -1.0
        if best["score"] >= MATCH_THRESHOLD and best["score"] - second >= MARGIN_THRESHOLD:
            return {"status": "relocated", "start": best["start"], "end": best["end"],
                    "score": best["score"], "level": 2, "quote": quote,
                    "candidates": len(candidates)}
        if len(ranked) > 1:
            return {"status": "relocated_needed", "start": None, "end": None,
                    "score": best["score"], "level": 4, "reason": "ambiguous_quote",
                    "quote": quote, "candidates": len(candidates)}

    # Level 3: the anchor range itself was rewritten by the author.
    if _range_in_replace(base, current, start, end):
        return {"status": "overlap_conflict", "start": start, "end": end, "level": 3,
                "reason": "selection_changed", "quote": quote}

    # Level 4: deleted or no usable context.
    return {"status": "relocated_needed", "start": None, "end": None, "level": 4,
            "reason": "anchor_not_found", "quote": quote}


def locate_hunk(base_text: str, current_text: str, hunk: Dict[str, Any]) -> Dict[str, Any]:
    anchor = hunk.get("anchor") if isinstance(hunk.get("anchor"), dict) else {
        "quote": hunk.get("before_text") or "",
        "char_start": hunk.get("char_start"),
        "char_end": hunk.get("char_end"),
        "base_snapshot_id": hunk.get("base_snapshot_id"),
    }
    return relocate_anchor(base_text, current_text, anchor)


def diff_hunks(before: str, after: str, *, prefix: str = "hk") -> List[Dict[str, Any]]:
    """Character diff split into hunks, IDs stable per ordered position."""
    a = to_codepoints(before)
    b = to_codepoints(after)
    hunks = []
    for index, (tag, i1, i2, j1, j2) in enumerate(
            difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes(), 1):
        if tag == "equal":
            continue
        hunks.append({
            "id": f"{prefix}_{index:02d}",
            "kind": tag,
            "char_start": i1, "char_end": i2,
            "start": i1, "end": i2,
            "before_text": "".join(a[i1:i2]),
            "after_text": "".join(b[j1:j2]),
        })
    return hunks


def _overlaps(start: int, end: int, ranges: Iterable[Tuple[int, int]]) -> bool:
    for left, right in ranges:
        if left == right and start == end:
            if left == start:
                return True
            continue
        if start < right and left < end:
            return True
        # A pure insertion strictly inside a replaced range is a conflict too.
        if start == end and left < start < right:
            return True
    return False


def build_intermediate_base(base_text: str, applied: Sequence[Dict[str, Any]],
                            *, ledger: Sequence[Dict[str, Any]] = ()) -> str:
    """Apply already-adopted hunks (and their custom text) to the original base.

    This is the ``B'`` baseline that prevents two adjacent hunks from the same
    preview being mistaken for independent author edits on the second apply.
    """
    text = normalize_lf(base_text)
    # Apply from the end so earlier offsets remain valid; ledger entries carry
    # the actual text that landed on disk (custom_text included).
    entries = []
    for row in ledger:
        if not isinstance(row, dict):
            continue
        applied_text = row.get("applied_text")
        start = row.get("char_start", row.get("applied_start"))
        end = row.get("char_end", row.get("applied_end"))
        if applied_text is None or start is None or end is None:
            continue
        entries.append((int(start), int(end), str(applied_text)))
    for hunk in applied:
        start = hunk.get("char_start", hunk.get("start"))
        end = hunk.get("char_end", hunk.get("end"))
        replacement = hunk.get("custom_text", hunk.get("after_text"))
        if start is None or end is None or replacement is None:
            continue
        entries.append((int(start), int(end), str(replacement)))
    points = to_codepoints(text)
    for start, end, replacement in sorted(entries, key=lambda item: item[0], reverse=True):
        start, end = clamp_range(text, start, end)
        points[start:end] = to_codepoints(replacement)
    return "".join(points)


def _prepare_hunk(base: str, intermediate: str, current: str,
                  hunk: Dict[str, Any]) -> Dict[str, Any]:
    """Map a hunk from original B to the intermediate B', then to U."""
    before_text = str(hunk.get("before_text") or hunk.get("quote") or "")
    start_point = hunk.get("char_start", hunk.get("start"))
    end_point = hunk.get("char_end", hunk.get("end"))
    if not before_text:
        first = _map_position(base, intermediate, int(start_point or 0))
        if first is None:
            if _point_in_replace(base, intermediate, int(start_point or 0)):
                return {"status": "overlap_conflict", "start": start_point, "end": end_point,
                        "reason": "intermediate_baseline_changed"}
            return {"status": "relocated_needed", "reason": "insertion_anchor_missing"}
        second = _map_position(intermediate, current, first)
        if second is None:
            if _point_in_replace(intermediate, current, first):
                return {"status": "overlap_conflict", "start": first, "end": first,
                        "reason": "insertion_point_changed"}
            return {"status": "relocated_needed", "reason": "insertion_anchor_missing"}
        return {"status": "relocated", "start": second, "end": second, "score": 1.0}
    step = relocate_anchor(base, intermediate, {
        "quote": before_text, "char_start": start_point, "char_end": end_point,
        "base_snapshot_id": hunk.get("base_snapshot_id"),
    })
    if step["status"] not in {"exact", "relocated"}:
        return step
    prefix, suffix = context_of(intermediate, int(step["start"]), int(step["end"]))
    return relocate_anchor(intermediate, current, {
        "quote": before_text, "char_start": int(step["start"]), "char_end": int(step["end"]),
        "prefix_ctx": prefix, "suffix_ctx": suffix,
    })


def apply_hunks(base_text: str, current_text: str, hunks: Sequence[Dict[str, Any]], *,
                already_applied: Sequence[Dict[str, Any]] = (),
                ledger: Sequence[Dict[str, Any]] = (),
                author_windows: Optional[Sequence[Tuple[int, int]]] = None) -> Dict[str, Any]:
    """Apply selected AI hunks to the author's current text.

    ``already_applied``/``ledger`` construct the intermediate baseline ``B'``.
    Hunks that do not overlap the author's independent edits are merged at
    their relocated offsets; overlapping hunks keep both versions and are
    reported as conflicts; unplaceable hunks are returned untouched.
    """
    base = normalize_lf(base_text)
    current = normalize_lf(current_text)
    intermediate = build_intermediate_base(base, already_applied, ledger=ledger)
    # Author-independent change ΔU = diff(B' → U), expressed as base coordinates.
    delta_ranges = []
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(
            None, to_codepoints(intermediate), to_codepoints(current), autojunk=False).get_opcodes():
        if tag != "equal":
            delta_ranges.append((i1, i2))
    if author_windows:
        delta_ranges.extend((int(a), int(b)) for a, b in author_windows)

    results = []
    conflicts = []
    # Sort descending by mapped start so insertions do not shift later offsets.
    prepared = []
    for hunk in hunks:
        located = _prepare_hunk(base, intermediate, current, hunk)
        prepared.append((hunk, located))
    prepared.sort(key=lambda item: (item[1].get("start") is None,
                                    -(item[1].get("start") or 0)))
    text_points = to_codepoints(current)
    applied_ranges = []
    for hunk, located in prepared:
        hunk_id = str(hunk.get("id") or hunk.get("hunk_id") or "")
        replacement = str(hunk.get("custom_text") if hunk.get("custom_text") is not None
                          else hunk.get("after_text") or "")
        before = str(hunk.get("before_text") or hunk.get("quote") or "")
        if located["status"] == "relocated_needed":
            results.append({"hunk_id": hunk_id, "status": "relocated_needed",
                            "reason": located.get("reason")})
            continue
        if located["status"] == "overlap_conflict":
            conflicts.append({"hunk_id": hunk_id, "status": "overlap_conflict",
                              "reason": located.get("reason"),
                              "start": located.get("start"), "end": located.get("end"),
                              "current_text": before, "candidate_text": replacement})
            results.append({"hunk_id": hunk_id, "status": "overlap_conflict"})
            continue
        start, end = int(located["start"]), int(located["end"])
        if any(_overlaps(start, end, [other]) or
               (start == end and other[0] <= start < max(other[1], other[0] + 1))
               for other in applied_ranges):
            conflicts.append({"hunk_id": hunk_id, "status": "overlap_conflict",
                              "reason": "hunk_overlap", "start": start, "end": end,
                              "current_text": "".join(text_points[start:end]),
                              "candidate_text": replacement})
            results.append({"hunk_id": hunk_id, "status": "overlap_conflict"})
            continue
        if _overlaps(start, end, delta_ranges):
            # Same replacement already present -> dedupe; otherwise conflict.
            existing = "".join(text_points[start:end])
            if existing == replacement:
                results.append({"hunk_id": hunk_id, "status": "already_applied",
                                "start": start, "end": end})
                continue
            conflicts.append({"hunk_id": hunk_id, "status": "overlap_conflict",
                              "reason": "author_edited_same_range", "start": start, "end": end,
                              "current_text": existing, "candidate_text": replacement})
            results.append({"hunk_id": hunk_id, "status": "overlap_conflict"})
            continue
        text_points[start:end] = to_codepoints(replacement)
        applied_ranges.append((start, start + codepoint_length(replacement)))
        results.append({"hunk_id": hunk_id, "status": "applied", "start": start,
                        "end": start + codepoint_length(replacement),
                        "applied_text": replacement, "before_text": before})
    return {"text": "".join(text_points), "results": results, "conflicts": conflicts,
            "clean": not conflicts and all(row["status"] in {"applied", "already_applied"}
                                           for row in results)}


def reverse_patch(current_text: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Undo one ledger row without touching the author's later typing.

    If the applied text is still exactly present at the recorded range it is
    replaced by the original quote.  If the author edited around it, the
    reverse is attempted by unique-quote relocation; ambiguous cases return
    ``relocated_needed`` and change nothing.
    """
    current = normalize_lf(current_text)
    applied = str(entry.get("applied_text") or "")
    before = str(entry.get("before_quote") or "")
    start = entry.get("char_start", entry.get("applied_start"))
    end = entry.get("char_end", entry.get("applied_end"))
    if not applied:
        if not before:
            return {"text": current, "status": "noop", "reason": "empty_applied_text"}
        # 删除型补丁：applied_text 为空，但 before_quote 仍保存被删原文。
        points = to_codepoints(current)
        position = int(start) if start is not None else 0
        position = max(0, min(position, len(points)))
        points[position:position] = to_codepoints(before)
        return {"text": "".join(points), "status": "reversed", "start": position,
                "end": position + codepoint_length(before)}
    points = to_codepoints(current)
    if start is not None and end is not None:
        start, end = clamp_range(current, start, end)
        if "".join(points[start:end]) == applied:
            points[start:end] = to_codepoints(before)
            return {"text": "".join(points), "status": "reversed", "start": start,
                    "end": start + codepoint_length(before)}
    occurrences = []
    cursor = 0
    while True:
        found = current.find(applied, cursor)
        if found < 0:
            break
        occurrences.append(found)
        cursor = found + max(1, len(applied))
    if len(occurrences) == 1:
        found = occurrences[0]
        points[found:found + len(applied)] = to_codepoints(before)
        return {"text": "".join(points), "status": "reversed", "start": found,
                "end": found + codepoint_length(before)}
    return {"text": current, "status": "relocated_needed",
            "reason": "applied_text_not_unique" if occurrences else "applied_text_missing"}


def merge_preview(base_text: str, current_text: str, candidate_text: str) -> Dict[str, Any]:
    """Three-way merge of a whole-chapter preview against in-flight edits."""
    base = normalize_lf(base_text)
    current = normalize_lf(current_text)
    candidate = normalize_lf(candidate_text)
    hunks = diff_hunks(base, candidate)
    result = apply_hunks(base, current, hunks)
    return {"text": result["text"], "hunks": result["results"],
            "conflicts": result["conflicts"], "clean": result["clean"]}
