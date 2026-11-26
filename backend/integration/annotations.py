"""三层批注、Hunk 六态、攒批注分诊与候选合并编排。

Persistent state lives in ``workbench.sqlite3`` (single ACID database).  Large
text payloads (baseline snapshots, candidate previews) stay content-addressed
in files; only ids, offsets and statuses live in SQL.  Selection relocation is
always delegated to :mod:`integration.text_merge` — this module never invents a
second offset algorithm.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from integration import chapter_editor
from integration import chapter_versions as versions
from integration import revision_plan
from integration import text_merge
from integration import workbench_db as wb

HUNK_STATES = {"pending", "applied_to_draft", "committed", "committed_modified",
               "superseded", "rejected"}
ANNOTATION_STATES = {"open", "conflicted", "running", "proposed", "partially_applied",
                     "accepted", "rejected", "relocated_needed"}
TERMINAL_HUNKS = {"committed", "committed_modified", "superseded", "rejected"}


class AnnotationError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _snapshot_path(project, digest: str) -> Path:
    return Path(project) / ".webnovel" / "snapshots" / f"{digest}.txt"


def save_snapshot(project, text: str) -> str:
    text = text_merge.normalize_lf(text)
    digest = _sha(text)
    path = _snapshot_path(project, digest)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return digest


def read_snapshot(project, digest: str) -> str:
    path = _snapshot_path(project, digest)
    if not path.is_file():
        raise AnnotationError("snapshot_missing", status=404)
    return path.read_text(encoding="utf-8")


def _current_text(project, chapter: int, *, against: str = "version") -> Tuple[str, Dict[str, Any]]:
    draft = wb.get_draft(project, chapter)
    if against == "draft" and draft:
        return (draft.get("content") or "",
                {"origin": "draft", "draft_id": draft.get("draft_id"),
                 "draft_epoch": draft.get("draft_epoch"),
                 "draft_revision": draft.get("draft_revision"),
                 "text_sha256": _sha(text_merge.normalize_lf(draft.get("content") or ""))})
    path = versions.chapter_path(project, chapter)
    if path is None:
        raise AnnotationError("chapter_missing", status=404)
    text = path.read_bytes().decode("utf-8", errors="replace").lstrip("\ufeff")
    meta = versions.current_version(project, chapter) or {}
    return (text_merge.normalize_lf(text),
            {"origin": "version", "version_id": meta.get("version_id"),
             "content_sha256": meta.get("content_sha256") or meta.get("sha256"),
             "text_sha256": _sha(text_merge.normalize_lf(text))})


def _row_annotation(row) -> Dict[str, Any]:
    item = dict(row)
    for key in ("anchor_json", "conflict_with_json", "candidate_ids_json", "thread_json"):
        try:
            item[key[:-5]] = json.loads(item.pop(key) or "null")
        except ValueError:
            item[key[:-5]] = None
    return item


def _row_hunk(row) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["applied_range"] = json.loads(item.pop("applied_range_json") or "null")
    except ValueError:
        item["applied_range"] = None
    return item


def get_annotation(project, chapter: int, annotation_id: str) -> Dict[str, Any]:
    with wb.connect(project) as db:
        row = db.execute("SELECT * FROM annotations WHERE id=? AND chapter_id=?",
                         (annotation_id, int(chapter))).fetchone()
    if not row:
        raise AnnotationError("annotation_missing", status=404)
    item = _row_annotation(row)
    with wb.connect(project) as db:
        hunks = [_row_hunk(h) for h in db.execute(
            "SELECT * FROM annotation_hunks WHERE annotation_id=? ORDER BY char_start, id",
            (annotation_id,))]
    item["hunks"] = hunks
    item["hunk_states"] = {h["id"]: h for h in hunks}
    return item


def create_annotation(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    chapter = int(chapter)
    scope = str(data.get("scope") or "selection")
    if scope not in {"selection", "chapter"}:
        raise AnnotationError("invalid_scope")
    instruction = str(data.get("instruction") or "").strip()
    if not instruction or len(instruction) > 4000:
        raise AnnotationError("instruction_required")
    if scope == "selection":
        base_text, origin = _current_text(project, chapter, against=str(data.get("against") or "draft"))
        anchor = data.get("anchor") if isinstance(data.get("anchor"), dict) else {}
        start = int(anchor.get("char_start") or 0)
        end = int(anchor.get("char_end") or 0)
        start, end = text_merge.clamp_range(base_text, start, end)
        quote = text_merge.normalize_lf(str(anchor.get("quote") or ""))
        if not quote or text_merge.slice_codepoints(base_text, start, end) != quote:
            raise AnnotationError("anchor_slice_mismatch")
        digest = save_snapshot(project, base_text)
        anchor = {
            "offset_unit": "unicode_codepoint_lf",
            "chapter_uid": wb.chapter_uid(project, chapter),
            "base_snapshot_id": digest,
            "base_origin": origin["origin"],
            "base_version_id": origin.get("version_id") or data.get("base_version_id"),
            "base_content_sha256": origin.get("content_sha256") or data.get("base_content_sha256"),
            "char_start": start, "char_end": end,
            "para_start": text_merge.paragraph_index(base_text, start),
            "para_end": text_merge.paragraph_index(base_text, end),
            "quote": quote, "quote_sha256": _sha(quote),
            "prefix_ctx": text_merge.context_of(base_text, start, end)[0],
            "suffix_ctx": text_merge.context_of(base_text, start, end)[1],
            "occurrence_hint": base_text.count(quote),
        }
    else:
        base_text, origin = _current_text(project, chapter, against="version")
        digest = save_snapshot(project, base_text)
        anchor = None
    annotation_id = wb.new_id("ann")
    stamp = _now()
    thread = [{"role": "author", "text": instruction, "at": stamp}]
    with wb.write_tx(project) as db:
        db.execute(
            "INSERT INTO annotations(id, chapter_id, chapter_uid, scope, anchor_json, instruction, "
            "edit_policy, variants_requested, status, annotation_revision, conflict_with_json, "
            "candidate_ids_json, thread_json, group_id, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (annotation_id, chapter, wb.chapter_uid(project, chapter), scope,
             json.dumps(anchor, ensure_ascii=False), instruction,
             str(data.get("edit_policy") or "strict_selection"),
             int(data.get("variants_requested") or 1), "open", 1, "[]", "[]",
             json.dumps(thread, ensure_ascii=False), data.get("group_id"), stamp, stamp),
        )
    return {"created": True, "annotation_status": "open",
            **get_annotation(project, chapter, annotation_id), "status": "created"}


def update_annotation(project, chapter: int, annotation_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    item = get_annotation(project, chapter, annotation_id)
    updates = {}
    if "instruction" in data:
        value = str(data.get("instruction") or "").strip()
        if not value or len(value) > 4000:
            raise AnnotationError("instruction_required")
        updates["instruction"] = value
        updates["annotation_revision"] = int(item.get("annotation_revision") or 1) + 1
        thread = list(item.get("thread") or [])
        thread.append({"role": "author", "text": value, "at": _now()})
        updates["thread_json"] = json.dumps(thread, ensure_ascii=False)
    if "status" in data:
        status = str(data.get("status") or "")
        if status not in ANNOTATION_STATES:
            raise AnnotationError("invalid_annotation_status")
        updates["status"] = status
    if not updates:
        return {"status": "unchanged", **item}
    updates["updated_at"] = _now()
    assignments = ", ".join(f"{key}=?" for key in updates)
    with wb.write_tx(project) as db:
        db.execute(f"UPDATE annotations SET {assignments} WHERE id=? AND chapter_id=?",
                   (*updates.values(), annotation_id, int(chapter)))
    return {"status": "updated", **get_annotation(project, chapter, annotation_id)}


def delete_annotation(project, chapter: int, annotation_id: str) -> Dict[str, Any]:
    get_annotation(project, chapter, annotation_id)
    with wb.write_tx(project) as db:
        db.execute("DELETE FROM annotation_hunks WHERE annotation_id=?", (annotation_id,))
        db.execute("DELETE FROM annotations WHERE id=? AND chapter_id=?", (annotation_id, int(chapter)))
    return {"status": "deleted", "annotation_id": annotation_id}


def summary(project, chapter: int) -> Dict[str, Any]:
    with wb.connect(project) as db:
        rows = list(db.execute("SELECT status, COUNT(*) AS n FROM annotations WHERE chapter_id=? GROUP BY status",
                               (int(chapter),)))
        pending = db.execute("SELECT COUNT(*) FROM annotation_hunks WHERE chapter_id=? AND status IN ('pending','applied_to_draft')",
                             (int(chapter),)).fetchone()[0]
        previews = db.execute("SELECT COUNT(*) FROM preview_index WHERE chapter_id=? AND status='pending'",
                              (int(chapter),)).fetchone()[0]
    counts = {str(row["status"]): int(row["n"]) for row in rows}
    return {"open_count": counts.get("open", 0) + counts.get("conflicted", 0) + counts.get("relocated_needed", 0),
            "proposed_count": counts.get("proposed", 0),
            "partially_applied_count": counts.get("partially_applied", 0),
            "pending_previews": int(previews), "pending_hunks": int(pending), "by_status": counts}


def list_annotations(project, chapter: int, *, against: str = "draft") -> Dict[str, Any]:
    chapter = int(chapter)
    current_text, evaluated = _current_text(project, chapter, against=against)
    with wb.connect(project) as db:
        rows = [_row_annotation(r) for r in db.execute(
            "SELECT * FROM annotations WHERE chapter_id=? ORDER BY created_at", (chapter,))]
        hunk_rows = {}
        for row in db.execute("SELECT * FROM annotation_hunks WHERE chapter_id=? ORDER BY char_start, id",
                              (chapter,)):
            item = _row_hunk(row)
            hunk_rows.setdefault(item["annotation_id"], []).append(item)
    for item in rows:
        item["hunks"] = hunk_rows.get(item["id"], [])
        item["hunk_states"] = {h["id"]: h for h in item["hunks"]}
        anchor = item.get("anchor") or {}
        if anchor:
            located = text_merge.relocate_anchor(
                read_snapshot(project, anchor.get("base_snapshot_id")), current_text, anchor)
            item["relocated"] = located
            item["range"] = {"start": located.get("start"), "end": located.get("end")}
            if located["status"] == "relocated_needed":
                item["status"] = "relocated_needed"
        else:
            item["range"] = None
            item["relocated"] = {"status": "chapter_scope", "start": None, "end": None}
    return {"chapter_id": chapter, "against": against, "annotations": rows,
            "evaluated_draft_id": evaluated.get("draft_id"),
            "evaluated_draft_revision": evaluated.get("draft_revision"),
            "evaluated_text_sha256": evaluated.get("text_sha256"),
            "evaluated_version_id": evaluated.get("version_id"),
            "offset_unit": "unicode_codepoint_lf"}


# --------------------------------------------------------------- parsing

def parse_edit_output(raw: str, *, expected_ids: Sequence[str] = ()) -> Dict[str, Any]:
    """Parse XML-delimited output first (robust for weak models), then JSON."""
    text = str(raw or "")
    if not text.strip():
        raise AnnotationError("empty_model_output")
    nonce_match = re.search(r"<novel-edit\b[^>]*nonce=\"([A-Za-z0-9_-]+)\"", text)
    replacement = None
    used_nonce = False
    if nonce_match:
        nonce = re.escape(nonce_match.group(1))
        match = re.search(rf"<replacement\b[^>]*nonce=\"{nonce}\">(.*)</replacement>", text, re.S)
        if match:
            replacement = match.group(1)
            used_nonce = True
    if replacement is None:
        # First opening and last closing tag: protects literal closing tags in prose.
        open_at = text.find("<replacement>")
        close_at = text.rfind("</replacement>")
        if open_at >= 0 and close_at > open_at:
            replacement = text[open_at + len("<replacement>"):close_at]
    patches = []
    for match in re.finditer(r"<patch\b([^>]*)>(.*?)</patch>", text, re.S):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group(1) or ""))
        patches.append({"id": attrs.get("id") or attrs.get("annotation") or "",
                        "start_para": int(attrs["start_para"]) if str(attrs.get("start_para", "")).isdigit() else None,
                        "end_para": int(attrs["end_para"]) if str(attrs.get("end_para", "")).isdigit() else None,
                        "reason": attrs.get("reason") or "", "text": match.group(2)})
    if patches:
        ids = [row["id"] for row in patches]
        if len(ids) != len(set(ids)) or any(not value for value in ids):
            raise AnnotationError("duplicate_or_missing_patch_id")
        if expected_ids and set(ids) - set(expected_ids):
            raise AnnotationError("unknown_patch_id")
        return {"format": "xml_patches", "patches": patches}
    if replacement is not None:
        value = replacement.strip("\n")
        if not value.strip():
            raise AnnotationError("empty_replacement")
        if "<replacement" in value or (not used_nonce and "</replacement>" in value):
            raise AnnotationError("replacement_tag_collision")
        return {"format": "xml_replacement", "replacement": value}
    # JSON fallback
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
        except ValueError as exc:
            raise AnnotationError("invalid_model_json") from exc
        if isinstance(value, dict) and isinstance(value.get("replacement"), str) and value["replacement"].strip():
            return {"format": "json", "replacement": value["replacement"],
                    "explanation": str(value.get("explanation") or "")}
    raise AnnotationError("unparseable_model_output")


# --------------------------------------------------------------- triage / run

def triage(project, chapter: int, annotations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Group annotations: conflicts, adjacent/semantic coupled, independent."""
    rows = []
    for item in annotations:
        anchor = item.get("anchor") or {}
        rows.append((item, int(anchor.get("char_start") or 0), int(anchor.get("char_end") or 0),
                     int(anchor.get("para_start") or 0), int(anchor.get("para_end") or 0)))
    conflicts: List[List[str]] = []
    coupled: List[List[str]] = []
    independent: List[str] = []
    for index, (item, start, end, p_start, p_end) in enumerate(rows):
        joined = False
        for other_index in range(index):
            other, o_start, o_end, o_pstart, o_pend = rows[other_index]
            overlap = start < o_end and o_start < end
            near = abs(p_start - o_pstart) <= 3 or abs(p_end - o_pend) <= 3
            if overlap and item.get("instruction") != other.get("instruction"):
                conflicts.append([other["id"], item["id"]])
                joined = True
                break
            if near:
                target = next((group for group in coupled if other["id"] in group), None)
                if target is None:
                    coupled.append([other["id"], item["id"]])
                elif item["id"] not in target:
                    target.append(item["id"])
                joined = True
                break
        if not joined and not any(item["id"] in group for group in conflicts):
            independent.append(item["id"])
    return {"conflicts": conflicts, "coupled_batch": coupled, "independent": independent}


def run_annotations(project, chapter: int, data: Dict[str, Any], *,
                    generate: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """Execute one/all annotations; ``generate`` is the ModelGateway adapter.

    A/B variants share one ``op_id`` and one group id; each variant lands in a
    separate preview/hunk set.  Model output may be XML or JSON and gets at most
    one format repair through the same gateway.
    """
    chapter = int(chapter)
    op_id = str(data.get("op_id") or "")
    if not op_id:
        raise AnnotationError("op_id_required")
    current_text, origin = _current_text(project, chapter, against=str(data.get("against") or "draft"))
    with wb.connect(project) as db:
        ids = [str(x) for x in (data.get("annotation_ids") or [])]
        if ids:
            rows = []
            for aid in ids:
                row = db.execute("SELECT * FROM annotations WHERE id=? AND chapter_id=?",
                                 (aid, chapter)).fetchone()
                if row:
                    rows.append(_row_annotation(row))
        else:
            rows = [_row_annotation(r) for r in db.execute(
                "SELECT * FROM annotations WHERE chapter_id=? AND status IN ('open','conflicted') ORDER BY created_at",
                (chapter,))]
    if not rows:
        raise AnnotationError("no_open_annotations")
    triage_result = triage(project, chapter, rows) if data.get("triage", True) else {
        "conflicts": [], "coupled_batch": [], "independent": [row["id"] for row in rows]}
    if generate is None:
        try:
            from integration import model_gateway
            generate = model_gateway.annotation_generator(project, chapter)
        except Exception:
            raise AnnotationError("model_gateway_unavailable", status=409,
                                  detail={"message": "请先在模型设置中配置可用的精修角色"}) from None
    variants = 2 if int(data.get("variants") or 0) == 2 else 1
    group_id = wb.new_id("grp")
    previews = []
    errors = []
    for item in rows:
        if item["id"] in {aid for group in triage_result["conflicts"] for aid in group}:
            with wb.write_tx(project) as db:
                db.execute("UPDATE annotations SET status='conflicted', updated_at=? WHERE id=?",
                           (_now(), item["id"]))
            continue
        anchor = item.get("anchor") or {}
        base_text = read_snapshot(project, anchor.get("base_snapshot_id")) if anchor else current_text
        located = text_merge.relocate_anchor(base_text, current_text, anchor) if anchor else {
            "status": "chapter_scope", "start": 0, "end": text_merge.codepoint_length(current_text)}
        if located["status"] == "relocated_needed":
            with wb.write_tx(project) as db:
                db.execute("UPDATE annotations SET status='relocated_needed', updated_at=? WHERE id=?",
                           (_now(), item["id"]))
            continue
        with wb.write_tx(project) as db:
            db.execute("UPDATE annotations SET status='running', updated_at=? WHERE id=?",
                       (_now(), item["id"]))
        context = {
            "base_text": base_text, "current_text": current_text,
            "range": [located.get("start"), located.get("end")],
            "scope": item.get("scope"), "instruction": item.get("instruction"),
            "edit_policy": item.get("edit_policy"),
        }
        for variant in range(variants):
            try:
                output = generate({**item, "variant": variant}, context)
                parsed = output if isinstance(output, dict) and "format" in output else parse_edit_output(
                    str(output or ""), expected_ids=[item["id"]])
            except Exception as exc:
                errors.append({"annotation_id": item["id"], "variant": variant,
                               "error": getattr(exc, "code", None) or str(exc)[:200]})
                continue
            built = _build_candidate(project, chapter, item, base_text, current_text,
                                     located, parsed, group_id=group_id)
            previews.append(built)
    for item in rows:
        remaining = _pending_count(project, item["id"])
        if remaining:
            with wb.write_tx(project) as db:
                db.execute("UPDATE annotations SET status='proposed', updated_at=? WHERE id=?",
                           (_now(), item["id"]))
    return {"status": "proposed" if previews else "failed", "chapter_id": chapter,
            "group_id": group_id, "previews": previews, "triage": triage_result,
            "errors": errors, "op_id": op_id}


def _build_candidate(project, chapter: int, annotation: Dict[str, Any], base_text: str,
                     current_text: str, located: Dict[str, Any], parsed: Dict[str, Any],
                     *, group_id: str) -> Dict[str, Any]:
    variant = int(annotation.get("variant") or 0)
    variant_name = "AB"[variant] if variant < 2 else str(variant)
    preview_id = wb.new_id("prev") + "_" + variant_name.lower()
    start = int(located.get("start") or 0)
    end = int(located.get("end") or 0)
    if parsed.get("format") == "xml_patches":
        hunks = []
        for index, patch in enumerate(parsed["patches"], 1):
            hunks.append({"id": f"hk_{index:02d}", "char_start": start, "char_end": end,
                          "before_text": text_merge.slice_codepoints(base_text, start, end),
                          "after_text": patch["text"]})
    else:
        replacement = str(parsed.get("replacement") or "")
        before = text_merge.slice_codepoints(base_text, start, end)
        hunks = [{"id": "hk_01", "char_start": start, "char_end": end,
                  "before_text": before, "after_text": replacement}]
    candidate_text = text_merge.apply_hunks(base_text, base_text, hunks)["text"]
    preview = revision_plan.save_preview(project, chapter, base_text, candidate_text,
                                         base_sha256=(versions.current_version(project, chapter) or {}).get("sha256"),
                                         mode="annotation", preview_id=preview_id)
    with wb.write_tx(project) as db:
        db.execute(
            "INSERT INTO preview_index(preview_id, chapter_id, chapter_uid, group_id, annotation_id, "
            "status, base_snapshot_id, base_version_id, artifacts_json, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (preview_id, chapter, wb.chapter_uid(project, chapter), group_id, annotation["id"],
             "pending", annotation.get("anchor", {}).get("base_snapshot_id") if annotation.get("anchor") else None,
             annotation.get("anchor", {}).get("base_version_id") if annotation.get("anchor") else None,
             json.dumps({"variant": variant_name, "explanation": parsed.get("explanation", "")},
                        ensure_ascii=False), _now(), _now()),
        )
        for hunk in hunks:
            hunk_id = f"{annotation['id']}_{preview_id}_{hunk['id']}"
            hunk["db_id"] = hunk_id
            hunk["id"] = hunk_id
            db.execute(
                "INSERT INTO annotation_hunks(id, annotation_id, preview_id, candidate_id, group_id, "
                "chapter_id, chapter_uid, status, before_text, after_text, char_start, char_end, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (hunk_id, annotation["id"], preview_id,
                 preview.get("preview_id"), group_id, chapter, wb.chapter_uid(project, chapter),
                 "pending", hunk["before_text"], hunk["after_text"], hunk["char_start"],
                 hunk["char_end"], _now(), _now()),
            )
        candidates = json.loads((db.execute("SELECT candidate_ids_json FROM annotations WHERE id=?",
                                            (annotation["id"],)).fetchone() or ["[]"])[0] or "[]")
        candidates.append(preview_id)
        db.execute("UPDATE annotations SET candidate_ids_json=?, updated_at=? WHERE id=?",
                   (json.dumps(candidates, ensure_ascii=False), _now(), annotation["id"]))
    return {"preview_id": preview_id, "annotation_id": annotation["id"], "variant": variant_name,
            "hunks": hunks, "candidate_text": candidate_text,
            "revision": preview.get("preview_id")}


def _pending_count(project, annotation_id: str) -> int:
    with wb.connect(project) as db:
        return int(db.execute("SELECT COUNT(*) FROM annotation_hunks WHERE annotation_id=? AND status='pending'",
                              (annotation_id,)).fetchone()[0])


def list_previews(project, chapter: int) -> Dict[str, Any]:
    with wb.connect(project) as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM preview_index WHERE chapter_id=? ORDER BY created_at", (int(chapter),))]
        for row in rows:
            row["artifacts"] = json.loads(row.pop("artifacts_json") or "{}")
            row["hunks"] = [_row_hunk(h) for h in db.execute(
                "SELECT * FROM annotation_hunks WHERE preview_id=? ORDER BY char_start, id",
                (row["preview_id"],))]
    return {"chapter_id": int(chapter), "previews": rows, "count": len(rows)}


def preview_merge_state(project, chapter: int, preview: Dict[str, Any]) -> Dict[str, Any]:
    try:
        current, _ = _current_text(project, chapter, against="draft")
        base = read_snapshot(project, preview.get("base_snapshot_id") or "")
        hunks = preview.get("hunks") or []
        result = text_merge.apply_hunks(base, current, hunks)
        return {"clean": result["clean"], "conflicts": result["conflicts"]}
    except Exception:
        return {"clean": False, "conflicts": [], "unknown": True}


# --------------------------------------------------------------- apply / undo

def apply_hunks(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    chapter = int(chapter)
    op_id = str(data.get("op_id") or "")
    if not op_id:
        raise AnnotationError("op_id_required")
    target = str(data.get("target") or "draft")
    selected = [str(x) for x in (data.get("hunk_ids") or [])]
    if not selected:
        raise AnnotationError("hunk_ids_required")
    draft = wb.get_draft(project, chapter)
    if draft and target != "draft":
        raise AnnotationError("draft_exists_target_draft_required", status=409)
    if draft:
        if (str(data.get("expected_draft_id") or "") != str(draft.get("draft_id"))
                or int(data.get("expected_draft_epoch") or 0) != int(draft.get("draft_epoch") or 0)
                or int(data.get("expected_draft_revision") or 0) != int(draft.get("draft_revision") or 0)):
            raise AnnotationError("draft_conflict", status=409, detail={"current_draft": draft})
    with wb.connect(project) as db:
        placeholders = ",".join("?" for _ in selected)
        rows = [_row_hunk(r) for r in db.execute(
            f"SELECT * FROM annotation_hunks WHERE chapter_id=? AND id IN ({placeholders})",
            (chapter, *selected))]
        ledger = [dict(r) for r in db.execute(
            "SELECT * FROM patch_ledger WHERE chapter_id=? ORDER BY id", (chapter,))]
        applied_rows = [row for row in rows if row["status"] == "applied_to_draft"]
        pending_rows = [row for row in rows if row["status"] == "pending"]
    if not pending_rows:
        raise AnnotationError("no_pending_hunks")
    current_text = (draft or {}).get("content") if draft else _current_text(project, chapter)[0]
    base_text = current_text
    base_snapshot_id = None
    if rows and rows[0].get("preview_id"):
        with wb.connect(project) as db:
            preview_row = db.execute("SELECT base_snapshot_id FROM preview_index WHERE preview_id=?",
                                     (rows[0]["preview_id"],)).fetchone()
        base_snapshot_id = preview_row[0] if preview_row else None
    if base_snapshot_id:
        base_text = read_snapshot(project, base_snapshot_id)
    already = [dict(row) for row in applied_rows]
    for row in already:
        row["custom_text"] = row.get("custom_text")
    ledger_rows = []
    for row in ledger:
        try:
            applied_range = json.loads(row.get("applied_range_json") or "null") or []
        except ValueError:
            applied_range = []
        ledger_rows.append({"char_start": applied_range[0] if len(applied_range) == 2 else None,
                            "char_end": applied_range[1] if len(applied_range) == 2 else None,
                            "applied_text": row.get("applied_text")})
    custom = data.get("custom_texts") if isinstance(data.get("custom_texts"), dict) else {}
    for row in pending_rows:
        if row["id"] in custom:
            row["custom_text"] = str(custom[row["id"]])
    result = text_merge.apply_hunks(base_text, current_text, pending_rows,
                                    already_applied=already, ledger=ledger_rows)
    text = result["text"]
    current_path = versions.chapter_path(project, chapter)
    current_title = versions.parse_chapter_name(current_path.name)[1] if current_path else ""
    if draft:
        updated = chapter_editor.save_draft(project, chapter, {
            "title": data.get("title") or (draft.get("title") or current_title),
            "content": text,
            "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
            "expected_draft_revision": draft["draft_revision"],
            "base_version_id": draft.get("base_version_id"),
            "base_content_sha256": draft.get("base_content_sha256"),
        })
        draft = updated["draft"]
    else:
        updated = chapter_editor.save_draft(project, chapter, {
            "title": data.get("title") or current_title,
            "content": text, "expected_draft_id": None, "expected_draft_epoch": 0,
            "expected_draft_revision": 0,
        })
        draft = updated["draft"]
    stamp = _now()
    with wb.write_tx(project) as db:
        for item in result["results"]:
            hunk_id = item["hunk_id"]
            if item["status"] == "applied":
                db.execute(
                    "UPDATE annotation_hunks SET status='applied_to_draft', applied_draft_id=?, "
                    "applied_draft_revision=?, applied_range_json=?, applied_text_sha256=?, updated_at=? "
                    "WHERE id=?", (draft["draft_id"], draft["draft_revision"],
                                   json.dumps([item["start"], item["end"]]),
                                   _sha(item.get("applied_text") or ""), stamp, hunk_id))
                db.execute(
                    "INSERT INTO patch_ledger(chapter_id, chapter_uid, preview_id, hunk_id, annotation_id, "
                    "draft_id, draft_revision, applied_range_json, before_quote, applied_text, custom, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (chapter, wb.chapter_uid(project, chapter),
                     next((row.get("preview_id") for row in pending_rows if row["id"] == hunk_id), None),
                     hunk_id, next((row.get("annotation_id") for row in pending_rows if row["id"] == hunk_id), None),
                     draft["draft_id"], draft["draft_revision"],
                     json.dumps([item["start"], item["end"]]), item.get("before_text") or "",
                     item.get("applied_text") or "", 1 if any(row["id"] == hunk_id and row.get("custom_text") is not None
                                                               for row in pending_rows) else 0, stamp))
            elif item["status"] == "already_applied":
                db.execute("UPDATE annotation_hunks SET status='applied_to_draft', applied_draft_id=?, "
                           "applied_draft_revision=?, updated_at=? WHERE id=?",
                           (draft["draft_id"], draft["draft_revision"], stamp, hunk_id))
            if item["status"] in {"applied", "already_applied"}:
                chosen = next((row for row in pending_rows if row["id"] == hunk_id), None)
                group_id = (chosen or {}).get("group_id")
                if group_id:
                    db.execute(
                        "UPDATE annotation_hunks SET status='superseded', updated_at=? "
                        "WHERE group_id=? AND id<>? AND status='pending' "
                        "AND char_start < ? AND ? < char_end",
                        (stamp, group_id, hunk_id,
                         int(item.get("end") or 0), int(item.get("start") or 0)))
    _recompute_annotation_status(project, {row["annotation_id"] for row in rows})
    return {"status": "applied", "chapter_id": chapter, "draft": draft,
            "applied": [item for item in result["results"] if item["status"] == "applied"],
            "conflicts": result["conflicts"], "clean": result["clean"]}


def undo_apply(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    chapter = int(chapter)
    ledger_id = data.get("ledger_id")
    with wb.connect(project) as db:
        if ledger_id is not None:
            row = db.execute("SELECT * FROM patch_ledger WHERE id=? AND chapter_id=?",
                             (int(ledger_id), chapter)).fetchone()
        else:
            row = db.execute("SELECT * FROM patch_ledger WHERE chapter_id=? ORDER BY id DESC LIMIT 1",
                             (chapter,)).fetchone()
    if not row:
        raise AnnotationError("ledger_entry_missing", status=404)
    row = dict(row)
    draft = wb.get_draft(project, chapter)
    if not draft:
        raise AnnotationError("draft_missing", status=409)
    try:
        applied_range = json.loads(row.get("applied_range_json") or "null") or []
    except ValueError:
        applied_range = []
    result = text_merge.reverse_patch(draft.get("content") or "", {
        "applied_text": row.get("applied_text"), "before_quote": row.get("before_quote"),
        "char_start": applied_range[0] if len(applied_range) == 2 else None,
        "char_end": applied_range[1] if len(applied_range) == 2 else None,
    })
    if result["status"] != "reversed":
        raise AnnotationError("undo_relocation_needed", status=409, detail={"reason": result.get("reason")})
    updated = chapter_editor.save_draft(project, chapter, {
        "title": draft.get("title") or "", "content": result["text"],
        "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
        "expected_draft_revision": draft["draft_revision"],
        "base_version_id": draft.get("base_version_id"),
        "base_content_sha256": draft.get("base_content_sha256"),
    })
    with wb.write_tx(project) as db:
        db.execute("DELETE FROM patch_ledger WHERE id=?", (row["id"],))
        if row.get("hunk_id"):
            db.execute("UPDATE annotation_hunks SET status='pending', applied_draft_id=NULL, "
                       "applied_draft_revision=NULL, applied_range_json=NULL, updated_at=? WHERE id=?",
                       (_now(), row["hunk_id"]))
    if row.get("annotation_id"):
        _recompute_annotation_status(project, {row["annotation_id"]})
    return {"status": "reverted", "chapter_id": chapter, "draft": updated["draft"],
            "range": [result.get("start"), result.get("end")]}


def revert_draft_hunks(project, chapter: int, draft_id: Optional[str]) -> List[str]:
    with wb.connect(project) as db:
        rows = [dict(r) for r in db.execute(
            "SELECT id FROM annotation_hunks WHERE chapter_id=? AND applied_draft_id=? "
            "AND status='applied_to_draft'", (int(chapter), draft_id))]
        db.execute("DELETE FROM patch_ledger WHERE chapter_id=? AND draft_id=?", (int(chapter), draft_id))
        db.execute("UPDATE annotation_hunks SET status='pending', applied_draft_id=NULL, "
                   "applied_draft_revision=NULL, applied_range_json=NULL, updated_at=? "
                   "WHERE chapter_id=? AND applied_draft_id=? AND status='applied_to_draft'",
                   (_now(), int(chapter), draft_id))
    ids = [row["id"] for row in rows]
    _recompute_annotation_status(project, set())
    return ids


def mark_committed(project, chapter: int, *, text: str, draft_id: Optional[str] = None) -> Dict[str, Any]:
    """After Ctrl+S: honestly attribute each applied hunk within ±120 codepoints."""
    chapter = int(chapter)
    committed = 0
    modified = 0
    with wb.connect(project) as db:
        rows = [_row_hunk(r) for r in db.execute(
            "SELECT * FROM annotation_hunks WHERE chapter_id=? AND status='applied_to_draft'",
            (chapter,))]
        for row in rows:
            applied_range = row.get("applied_range") or []
            applied_text = row.get("after_text") or ""
            start = int(applied_range[0]) if len(applied_range) == 2 else 0
            window = text_merge.slice_codepoints(text, max(0, start - 120),
                                                 start + text_merge.codepoint_length(applied_text) + 120)
            status = "committed" if applied_text and applied_text in window else "committed_modified"
            db.execute("UPDATE annotation_hunks SET status=?, updated_at=? WHERE id=?",
                       (status, _now(), row["id"]))
            committed += status == "committed"
            modified += status == "committed_modified"
            if row.get("annotation_id"):
                _recompute_annotation_status(project, {row["annotation_id"]})
        db.execute("DELETE FROM patch_ledger WHERE chapter_id=?", (chapter,))
    return {"committed": committed, "committed_modified": modified}


def _recompute_annotation_status(project, annotation_ids: Iterable[str]) -> None:
    for annotation_id in annotation_ids:
        with wb.connect(project) as db:
            rows = [dict(r) for r in db.execute(
                "SELECT status FROM annotation_hunks WHERE annotation_id=?", (annotation_id,))]
        if not rows:
            continue
        states = [row["status"] for row in rows]
        if all(state in TERMINAL_HUNKS for state in states):
            landed = any(state in {"committed", "committed_modified"} for state in states)
            status = "accepted" if landed else "rejected"
        elif any(state in {"committed", "committed_modified"} for state in states):
            status = "partially_applied"
        elif any(state == "applied_to_draft" for state in states):
            status = "partially_applied"
        elif any(state == "pending" for state in states):
            status = "proposed" if any(state in {"applied_to_draft"} for state in states) else "open"
        else:
            status = "rejected"
        with wb.write_tx(project) as db:
            db.execute("UPDATE annotations SET status=?, updated_at=? WHERE id=?",
                       (status, _now(), annotation_id))


def export_chapter(project, chapter: int) -> List[Dict[str, Any]]:
    with wb.connect(project) as db:
        rows = [_row_annotation(r) for r in db.execute(
            "SELECT * FROM annotations WHERE chapter_id=?", (int(chapter),))]
        for row in rows:
            row["hunks"] = [_row_hunk(h) for h in db.execute(
                "SELECT * FROM annotation_hunks WHERE annotation_id=?", (row["id"],))]
    return rows


def delete_chapter(project, chapter: int) -> None:
    with wb.write_tx(project) as db:
        db.execute("DELETE FROM annotation_hunks WHERE chapter_id=?", (int(chapter),))
        db.execute("DELETE FROM annotations WHERE chapter_id=?", (int(chapter),))
        db.execute("DELETE FROM patch_ledger WHERE chapter_id=?", (int(chapter),))
        db.execute("DELETE FROM preview_index WHERE chapter_id=?", (int(chapter),))
