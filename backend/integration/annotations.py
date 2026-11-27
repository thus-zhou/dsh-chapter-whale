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
import os
import re
import tempfile
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
                     "accepted", "rejected", "relocated_needed", "author_rewrote_selection"}
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


def _as_list(value: Any, field: str) -> List[str]:
    """Normalize a JSON array field; a scalar is a request error, never 500."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise AnnotationError("invalid_request", detail={"field": field,
                                                     "message": f"{field} 必须是数组"})


def _idempotency_begin(project, action: str, op_id: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    result = wb.idempotency_begin(project, actor="author",
                                  project_id=str(Path(project).resolve()),
                                  action=action, op_id=op_id, params=params)
    if result["status"] == "mismatch":
        raise AnnotationError("op_id_params_mismatch", status=409)
    if result["status"] == "completed":
        return result.get("response")
    if result["status"] == "in_progress":
        raise AnnotationError("op_in_progress", status=409,
                              detail={"message": "同一操作正在执行，请稍候"})
    return None


def _idempotency_complete(project, action: str, op_id: str, response: Dict[str, Any]) -> None:
    wb.idempotency_complete(project, actor="author", project_id=str(Path(project).resolve()),
                            action=action, op_id=op_id, response=response)


def _idempotency_fail(project, action: str, op_id: str) -> None:
    try:
        wb.idempotency_fail(project, actor="author", project_id=str(Path(project).resolve()),
                            action=action, op_id=op_id)
    except Exception:
        pass


def _evidence_dir(project, name: str) -> Path:
    """Return ``.webnovel/<name>`` only when it cannot escape the project.

    ``.webnovel/snapshots`` may arrive as a symlink from a synced or hostile
    project; writing through it would place annotation baselines outside the
    book and silently omit them from backups (A-P2-10).
    """
    root = Path(project).resolve()
    base = Path(project) / ".webnovel"
    for folder in (base, base / name):
        try:
            if folder.is_symlink():
                raise AnnotationError("unsafe_evidence_store", status=409)
        except OSError as exc:
            raise AnnotationError("unsafe_evidence_store", status=409) from exc
        if folder.exists():
            try:
                resolved = folder.resolve()
            except OSError as exc:
                raise AnnotationError("unsafe_evidence_store", status=409) from exc
            if resolved != root and root not in resolved.parents:
                raise AnnotationError("unsafe_evidence_store", status=409)
    return base / name


def _snapshot_path(project, digest: str) -> Path:
    return _evidence_dir(project, "snapshots") / f"{digest}.txt"


def save_snapshot(project, text: str) -> str:
    text = text_merge.normalize_lf(text)
    digest = _sha(text)
    path = _snapshot_path(project, digest)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            from fanqie_auto_publish.publication_safety import replace_with_retry
            replace_with_retry(Path(temporary), path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
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
        # Chapter-scope annotations keep the public anchor contract (None);
        # the base snapshot is created when the preview is produced, where the
        # actual model base is known (B-01R-2).
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
        if updates.get("status") == "rejected":
            # Rejection must reach the hunk state machine in the same
            # transaction, otherwise ``apply_hunks`` can still commit a
            # rejected annotation (B-12).
            db.execute("UPDATE annotation_hunks SET status='rejected', updated_at=? "
                       "WHERE annotation_id=? AND chapter_id=? AND status='pending'",
                       (updates["updated_at"], annotation_id, int(chapter)))
            preview_ids = [row[0] for row in db.execute(
                "SELECT DISTINCT preview_id FROM annotation_hunks "
                "WHERE annotation_id=? AND preview_id IS NOT NULL", (annotation_id,))]
            for preview_id in preview_ids:
                states = [row[0] for row in db.execute(
                    "SELECT status FROM annotation_hunks WHERE preview_id=?", (preview_id,))]
                preview_status = "superseded" if states and all(
                    state in {"superseded", "rejected"} for state in states) else "pending"
                db.execute("UPDATE preview_index SET status=?, updated_at=? WHERE preview_id=?",
                           (preview_status, updates["updated_at"], preview_id))
    return {"status": "updated", **get_annotation(project, chapter, annotation_id)}


def _refresh_preview_status(db, preview_id: Optional[str], stamp: str) -> None:
    """Recompute one preview row from its hunks (never leave phantom pending)."""
    if not preview_id:
        return
    states = [row[0] for row in db.execute(
        "SELECT status FROM annotation_hunks WHERE preview_id=?", (preview_id,))]
    if not states:
        status = "superseded"
    elif any(state in {"applied_to_draft", "committed", "committed_modified"} for state in states):
        status = "applied"
    elif all(state in {"superseded", "rejected"} for state in states):
        status = "superseded"
    else:
        status = "pending"
    db.execute("UPDATE preview_index SET status=?, updated_at=? WHERE preview_id=?",
               (status, stamp, preview_id))


def delete_annotation(project, chapter: int, annotation_id: str) -> Dict[str, Any]:
    get_annotation(project, chapter, annotation_id)
    stamp = _now()
    with wb.write_tx(project) as db:
        # Drop the preview rows together with their hunks; otherwise the
        # summary keeps reporting a pending preview with zero hunks forever
        # (A-P3-04).
        preview_ids = [row[0] for row in db.execute(
            "SELECT DISTINCT preview_id FROM annotation_hunks "
            "WHERE annotation_id=? AND preview_id IS NOT NULL", (annotation_id,))]
        db.execute("DELETE FROM annotation_hunks WHERE annotation_id=?", (annotation_id,))
        db.execute("DELETE FROM annotations WHERE id=? AND chapter_id=?",
                   (annotation_id, int(chapter)))
        for preview_id in preview_ids:
            db.execute("DELETE FROM preview_index WHERE preview_id=?", (preview_id,))
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
    return {"open_count": counts.get("open", 0) + counts.get("conflicted", 0)
            + counts.get("relocated_needed", 0) + counts.get("author_rewrote_selection", 0),
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
            try:
                located = text_merge.relocate_anchor(
                    read_snapshot(project, anchor.get("base_snapshot_id")), current_text, anchor)
            except AnnotationError as exc:
                # One damaged snapshot reference must not hide the whole
                # chapter's annotations from the author.
                item["relocated"] = {"status": "snapshot_missing", "reason": exc.code,
                                     "start": None, "end": None}
                item["range"] = {"start": None, "end": None}
                item["status"] = "relocated_needed"
                continue
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
        # ``expected_ids`` refers to annotation ids, but ``<patch id>`` is a
        # model-chosen block id.  Requiring block ids to equal the annotation
        # id rejected every multi-block reply; uniqueness above is the real
        # contract (B-06).
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
    try:
        current_text, _ = _current_text(project, chapter, against="draft")
    except Exception:
        current_text = ""
    for item in annotations:
        anchor = item.get("anchor") or {}
        start = int(anchor.get("char_start") or 0)
        end = int(anchor.get("char_end") or 0)
        if anchor and current_text:
            try:
                base_text = read_snapshot(project, anchor.get("base_snapshot_id"))
                located = text_merge.relocate_anchor(base_text, current_text, anchor)
                if located.get("start") is not None and located.get("end") is not None:
                    start, end = int(located["start"]), int(located["end"])
            except Exception:
                pass
        rows.append((item, start, end,
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
    # ``coupled_batch`` members must not also appear in ``independent`` or an
    # outer orchestrator could execute them twice (B-21).
    grouped = {value for group in conflicts for value in group} | {value for group in coupled for value in group}
    independent = [value for value in independent if value not in grouped]
    return {"conflicts": conflicts, "coupled_batch": coupled, "independent": independent}


def run_annotations(project, chapter: int, data: Dict[str, Any], *,
                    generate: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
    """Idempotent entry point for annotation generation (B-19)."""
    chapter = int(chapter)
    op_id = str(data.get("op_id") or "")
    if not op_id:
        raise AnnotationError("op_id_required")
    raw_ids = data.get("annotation_ids")
    ids = _as_list(raw_ids, "annotation_ids")
    params = {"annotation_ids": sorted(ids),
              "variants": int(data.get("variants") or 0),
              "against": str(data.get("against") or "draft"),
              "triage": bool(data.get("triage", True))}
    cached = _idempotency_begin(project, "annotations.run", op_id, params)
    if cached is not None:
        return cached
    try:
        result = _run_annotations_impl(project, chapter, data, generate=generate, op_id=op_id)
    except BaseException:
        _idempotency_fail(project, "annotations.run", op_id)
        raise
    _idempotency_complete(project, "annotations.run", op_id, result)
    return result


def _run_annotations_impl(project, chapter: int, data: Dict[str, Any], *,
                          generate: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None,
                          op_id: str = "") -> Dict[str, Any]:
    """Execute one/all annotations; ``generate`` is the ModelGateway adapter.

    A/B variants share one ``op_id`` and one group id; each variant lands in a
    separate preview/hunk set.  Model output may be XML or JSON and gets at most
    one format repair through the same gateway.
    """
    chapter = int(chapter)
    op_id = str(op_id or data.get("op_id") or "")
    if not op_id:
        raise AnnotationError("op_id_required")
    current_text, origin = _current_text(project, chapter, against=str(data.get("against") or "draft"))
    with wb.connect(project) as db:
        ids = _as_list(data.get("annotation_ids"), "annotation_ids")
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
    # Chapter-scope annotations have no anchor; the preview base is the current
    # text at generation time.  Persist it so apply_hunks can use the same
    # coordinate space after the author edits the draft (B-01R-2).
    chapter_base_snapshot = save_snapshot(project, current_text) if any(
        not (item.get("anchor") or {}) for item in rows) else None
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
            "status": "chapter_scope", "start": 0,
            "end": text_merge.codepoint_length(current_text)}
        if located["status"] in {"relocated_needed", "overlap_conflict"}:
            status = "author_rewrote_selection" if located["status"] == "overlap_conflict" \
                else "relocated_needed"
            # The model must not be billed to rewrite text the author already
            # changed; the stored range would point at unrelated prose (B-08).
            with wb.write_tx(project) as db:
                db.execute("UPDATE annotations SET status=?, updated_at=? WHERE id=?",
                           (status, _now(), item["id"]))
            continue
        with wb.write_tx(project) as db:
            db.execute("UPDATE annotations SET status='running', updated_at=? WHERE id=?",
                       (_now(), item["id"]))
        context = {
            "base_text": base_text, "current_text": current_text,
            "range": [located.get("start"), located.get("end")],
            "scope": item.get("scope"), "instruction": item.get("instruction"),
            "edit_policy": item.get("edit_policy"), "op_id": op_id,
        }
        for variant in range(variants):
            try:
                output = generate({**item, "variant": variant, "op_id": op_id}, context)
                parsed = output if isinstance(output, dict) and "format" in output else parse_edit_output(
                    str(output or ""), expected_ids=[item["id"]])
            except Exception as exc:
                errors.append({"annotation_id": item["id"], "variant": variant,
                               "error": getattr(exc, "code", None) or str(exc)[:200]})
                continue
            built = _build_candidate(project, chapter, {**item, "variant": variant}, base_text, current_text,
                                     located, parsed, group_id=group_id,
                                     base_snapshot_id=chapter_base_snapshot)
            previews.append(built)
    for item in rows:
        remaining = _pending_count(project, item["id"])
        if remaining:
            with wb.write_tx(project) as db:
                db.execute("UPDATE annotations SET status='proposed', updated_at=? WHERE id=?",
                           (_now(), item["id"]))
        else:
            # 全部 variant 失败时不能把批注永久留在 running；恢复为 open 让默认重跑能选中。
            with wb.write_tx(project) as db:
                db.execute("UPDATE annotations SET status='open', updated_at=? "
                           "WHERE id=? AND status='running'", (_now(), item["id"]))
    return {"status": "proposed" if previews else "failed", "chapter_id": chapter,
            "group_id": group_id, "previews": previews, "triage": triage_result,
            "errors": errors, "op_id": op_id}


def _build_candidate(project, chapter: int, annotation: Dict[str, Any], base_text: str,
                     current_text: str, located: Dict[str, Any], parsed: Dict[str, Any],
                     *, group_id: str, base_snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    variant = int(annotation.get("variant") or 0)
    variant_name = "AB"[variant] if variant < 2 else str(variant)
    preview_id = wb.new_id("prev") + "_" + variant_name.lower()
    # ``located`` is in current-draft coordinates (it was relocated against the
    # draft).  Hunk coordinates, before_text and candidate_text must all use
    # the *base snapshot* coordinates the preview is built on, or an insertion
    # before the selection silently turns the edit into an append.
    anchor = annotation.get("anchor") or {}
    start = int(anchor.get("char_start", located.get("start") or 0))
    end = int(anchor.get("char_end", located.get("end") or 0))
    if end < start:
        start, end = end, start
    if parsed.get("format") == "xml_patches":
        hunks = []
        paragraphs = revision_plan.paragraphs(base_text)
        for index, patch in enumerate(parsed["patches"], 1):
            hunk_start, hunk_end = start, end
            p_start = patch.get("start_para")
            p_end = patch.get("end_para")
            if isinstance(p_start, int) and 0 <= p_start < len(paragraphs):
                last = p_end if isinstance(p_end, int) and p_start <= p_end < len(paragraphs) else p_start
                hunk_start = int(paragraphs[p_start]["start"])
                hunk_end = int(paragraphs[last]["end"])
                if hunk_end < hunk_start:
                    hunk_start, hunk_end = hunk_end, hunk_start
            if str(annotation.get("edit_policy") or "") == "strict_selection":
                # A model-chosen paragraph range must never let one selection
                # annotation rewrite paragraphs outside the author's selection
                # (A-P3-05).  Clamp both ends into [start, end]; a patch that
                # lies entirely before/after becomes an insertion at the
                # corresponding selection boundary.
                hunk_start = min(max(hunk_start, start), end)
                hunk_end = min(max(hunk_end, start), end)
                if hunk_end < hunk_start:
                    hunk_start, hunk_end = hunk_end, hunk_start
            hunks.append({"id": f"hk_{index:02d}", "char_start": hunk_start, "char_end": hunk_end,
                          "before_text": text_merge.slice_codepoints(base_text, hunk_start, hunk_end),
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
             "pending", (annotation.get("anchor", {}).get("base_snapshot_id")
                            if annotation.get("anchor") else base_snapshot_id),
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


def _selected_states(project, chapter: int, selected: List[str]) -> set:
    if not selected:
        return set()
    placeholders = ",".join("?" for _ in selected)
    with wb.connect(project) as db:
        rows = db.execute(
            f"SELECT status FROM annotation_hunks WHERE chapter_id=? AND id IN ({placeholders})",
            (int(chapter), *selected)).fetchall()
    return {str(row[0]) for row in rows}


def list_previews(project, chapter: int) -> Dict[str, Any]:
    # A read must not create an empty workbench DB.  Old/registered-but-never-
    # edited books have no preview_index; return an empty page instead of 500
    # (X-P2-1).
    if not wb.db_path(project).exists():
        return {"chapter_id": int(chapter), "previews": [], "count": 0}
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
    """Merge state for annotation-mode previews only.

    Revision-plan previews have no annotation hunks; returning a fabricated
    ``unknown`` state for them misled the preview list (B-26).  Callers mark
    non-annotation previews with ``merge_state: null`` instead.
    """
    if str(preview.get("mode") or "annotation") != "annotation" or not preview.get("hunks"):
        return {"clean": None, "conflicts": [], "applicable": False}
    try:
        current, _ = _current_text(project, chapter, against="draft")
        base = read_snapshot(project, preview.get("base_snapshot_id") or "")
        hunks = preview.get("hunks") or []
        result = text_merge.apply_hunks(base, current, hunks,
                                        base_snapshot_id=preview.get("base_snapshot_id"))
        return {"clean": result["clean"], "conflicts": result["conflicts"], "applicable": True}
    except Exception:
        return {"clean": False, "conflicts": [], "unknown": True, "applicable": True}


# --------------------------------------------------------------- apply / undo

def apply_hunks(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent entry point for hunk application (B-19)."""
    chapter = int(chapter)
    op_id = str(data.get("op_id") or "")
    if not op_id:
        raise AnnotationError("op_id_required")
    target = str(data.get("target") or "draft")
    selected = _as_list(data.get("hunk_ids"), "hunk_ids")
    if not selected:
        raise AnnotationError("hunk_ids_required")
    custom = data.get("custom_texts") if isinstance(data.get("custom_texts"), dict) else {}
    params = {"target": target, "hunk_ids": sorted(selected),
              "custom_texts": {str(key): str(value) for key, value in custom.items()},
              "expected_draft_id": str(data.get("expected_draft_id") or ""),
              "expected_draft_epoch": int(data.get("expected_draft_epoch") or 0),
              "expected_draft_revision": int(data.get("expected_draft_revision") or 0)}
    try:
        cached = _idempotency_begin(project, "annotations.apply_hunks", op_id, params)
    except AnnotationError as exc:
        # A failed completion write leaves the key in_progress even though the
        # draft/hunk commit landed.  When every selected hunk is already
        # applied, rebuild the response from that authoritative state
        # (A-P3-15); otherwise the operation may really be running.
        if exc.code == "op_in_progress" and _selected_states(project, chapter, selected) == {"applied_to_draft"}:
            try:
                return _apply_hunks_impl(project, chapter, data, op_id=op_id, target=target,
                                         selected=selected)
            except AnnotationError:
                pass
        raise
    if cached is not None:
        return cached
    try:
        result = _apply_hunks_impl(project, chapter, data, op_id=op_id, target=target,
                                   selected=selected)
    except BaseException:
        _idempotency_fail(project, "annotations.apply_hunks", op_id)
        raise
    try:
        _idempotency_complete(project, "annotations.apply_hunks", op_id, result)
    except Exception:
        # The draft/hunk/ledger commit already succeeded.  A completion-key
        # failure must not turn it into a 500; a retry reconstructs the result
        # from the applied_to_draft rows (A-P3-15).
        result = {**result, "completion_persisted": False}
    return result


def _hunk_already_present(project, base_text: str, current_text: str,
                          row: Dict[str, Any], base_snapshot_id: Optional[str] = None
                          ) -> Optional[Dict[str, Any]]:
    """Prove that a pending hunk's result is already in the current draft.

    A crash between the old two transactions could leave the draft containing
    the candidate while the hunk stayed ``pending``.  Re-applying an insertion
    duplicated prose and a replacement became a permanent conflict.  This
    check makes the retry adopt the landed text instead (B-01R-4/B3-04).
    """
    before = str(row.get("before_text") or "")
    applied = str(row.get("custom_text") if row.get("custom_text") is not None
                  else row.get("after_text") or "")
    if not applied or applied == before:
        return None
    if before:
        start, end = text_merge.clamp_range(base_text, row.get("char_start") or 0,
                                            row.get("char_end") or 0)
        if (text_merge.slice_codepoints(base_text, start, end) == before
                and text_merge.slice_codepoints(current_text, start, end) == applied):
            return {"start": start, "end": end, "applied_text": applied}
        # Insertion case: the old crash landed the candidate at the exact
        # hunk position (the base still has only ``before`` there).  This is
        # narrow evidence; do not use a whole-document "unique occurrence"
        # guess that can mistake the author's own sentence for a landed patch
        # (R-01).
        if (text_merge.slice_codepoints(base_text, start, end) == before
                and text_merge.slice_codepoints(current_text, start, start + text_merge.codepoint_length(applied))
                == applied):
            return {"start": start, "end": start + text_merge.codepoint_length(applied),
                    "applied_text": applied}
    anchor = {"quote": before, "char_start": row.get("char_start"),
              "char_end": row.get("char_end"),
              "base_snapshot_id": base_snapshot_id or row.get("base_snapshot_id")}
    if before:
        located = text_merge.relocate_anchor(base_text, current_text, anchor)
        if located.get("status") in {"exact", "relocated"}:
            start, end = int(located["start"]), int(located["end"])
            if text_merge.slice_codepoints(current_text, start, end) == applied:
                return {"start": start, "end": end, "applied_text": applied}
    # Do not infer "already applied" from a unique occurrence of the target
    # text.  The author may have typed the same sentence elsewhere; treating
    # that as a landed patch silently skips the real selection edit, and a
    # later undo would rewrite the author's unrelated sentence.  Only the
    # exact range/relocated quote above is evidence of this hunk (R-01).
    return None


def _apply_hunks_impl(project, chapter: int, data: Dict[str, Any], *,
                      op_id: str, target: str, selected: List[str]) -> Dict[str, Any]:
    chapter = int(chapter)
    with wb.connect(project) as db:
        placeholders = ", ".join("?" for _ in selected)
        rows = [_row_hunk(r) for r in db.execute(
            "SELECT h.* FROM annotation_hunks h JOIN annotations a ON a.id=h.annotation_id "
            f"WHERE h.chapter_id=? AND h.id IN ({placeholders}) AND a.status<>'rejected'",
            (chapter, *selected))]
        ledger = [dict(r) for r in db.execute(
            "SELECT l.*, p.base_snapshot_id AS base_snapshot_id FROM patch_ledger l "
            "LEFT JOIN preview_index p ON p.preview_id=l.preview_id "
            "WHERE l.chapter_id=? ORDER BY l.id", (chapter,))]
        applied_rows = [row for row in rows if row["status"] == "applied_to_draft"]
        pending_rows = [row for row in rows if row["status"] == "pending"]
        preview_snapshots: Dict[str, Optional[str]] = {}
        for preview_id in sorted({row.get("preview_id") for row in rows if row.get("preview_id")}):
            preview_row = db.execute(
                "SELECT base_snapshot_id FROM preview_index WHERE preview_id=?",
                (preview_id,)).fetchone()
            preview_snapshots[preview_id] = preview_row[0] if preview_row else None
    if not rows:
        raise AnnotationError("no_pending_hunks")
    draft = wb.get_draft(project, chapter)
    if not pending_rows:
        if not applied_rows:
            raise AnnotationError("no_pending_hunks")
        # A retry after the draft/hunk commit but before idempotency_complete
        # must be able to read the result back instead of getting a conflict
        # (A-P3-15).
        summary_rows = []
        for row in applied_rows:
            applied_range = row.get("applied_range") or []
            summary_rows.append({
                "hunk_id": row["id"], "status": "already_applied",
                "start": applied_range[0] if len(applied_range) == 2 else row.get("char_start"),
                "end": applied_range[1] if len(applied_range) == 2 else row.get("char_end"),
                "applied_text": (row.get("custom_text") if row.get("custom_text") is not None
                                 else row.get("after_text") or ""),
                "before_text": str(row.get("before_text") or ""),
            })
        return {"status": "applied", "already_applied": True, "chapter_id": chapter,
                "draft": draft, "applied": summary_rows, "conflicts": [], "clean": True,
                "skipped": []}
    distinct_snapshots = {value for value in preview_snapshots.values() if value}
    if len(distinct_snapshots) > 1:
        # Hunks generated against different draft baselines use different
        # coordinate systems; silently applying only the first preview's base
        # dropped the rest while still reporting "applied" (A-P2-07).
        raise AnnotationError("mixed_base_snapshots", status=409, detail={
            "previews": preview_snapshots,
            "message": "所选批注来自不同草稿基线，请分组应用",
        })
    if draft and target != "draft":
        raise AnnotationError("draft_exists_target_draft_required", status=409)
    if draft:
        if (str(data.get("expected_draft_id") or "") != str(draft.get("draft_id"))
                or int(data.get("expected_draft_epoch") or 0) != int(draft.get("draft_epoch") or 0)
                or int(data.get("expected_draft_revision") or 0) != int(draft.get("draft_revision") or 0)):
            raise AnnotationError("draft_conflict", status=409, detail={"current_draft": draft})
    current_text = (draft or {}).get("content") if draft else _current_text(project, chapter)[0]
    base_text = current_text
    base_snapshot_id = None
    base_preview = next((row.get("preview_id") for row in pending_rows if row.get("preview_id")), None)
    if base_preview:
        base_snapshot_id = preview_snapshots.get(base_preview)
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
                            "applied_text": row.get("applied_text"),
                            "before_quote": row.get("before_quote"),
                            "base_snapshot_id": row.get("base_snapshot_id"),
                            "preview_id": row.get("preview_id"),
                            "hunk_id": row.get("hunk_id"),
                            "draft_revision": row.get("draft_revision")})
    custom = data.get("custom_texts") if isinstance(data.get("custom_texts"), dict) else {}
    for row in pending_rows:
        if row["id"] in custom:
            row["custom_text"] = str(custom[row["id"]])
    # Ledger rows are stronger evidence than a stale ``pending`` status: a
    # crashed old transaction may have written the ledger but not the hunk.
    ledger_by_hunk = {row.get("hunk_id"): row for row in ledger if row.get("hunk_id")}
    pre_applied: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for row in pending_rows:
        ledger_row = ledger_by_hunk.get(row["id"])
        if ledger_row:
            applied_range = []
            try:
                applied_range = json.loads(ledger_row.get("applied_range_json") or "null") or []
            except ValueError:
                applied_range = []
            pre_applied.append({
                "hunk_id": row["id"], "status": "applied",
                "start": applied_range[0] if len(applied_range) == 2 else row.get("char_start"),
                "end": applied_range[1] if len(applied_range) == 2 else row.get("char_end"),
                "applied_text": ledger_row.get("applied_text") or "",
                "before_text": ledger_row.get("before_quote") or "",
            })
            continue
        present = _hunk_already_present(project, base_text, current_text, row,
                                        base_snapshot_id=base_snapshot_id)
        if present is not None:
            pre_applied.append({"hunk_id": row["id"], "status": "applied", **present,
                                "before_text": str(row.get("before_text") or "")})
            continue
        remaining.append(row)
    pending_rows = remaining
    result = text_merge.apply_hunks(base_text, current_text, pending_rows,
                                    already_applied=already, ledger=ledger_rows,
                                    base_snapshot_id=base_snapshot_id)
    text = result["text"]
    current_path = versions.chapter_path(project, chapter)
    current_title = versions.parse_chapter_name(current_path.name)[1] if current_path else ""
    text_changed = text != current_text
    stamp = _now()
    # Draft row and hunk/ledger/preview state share one SQLite transaction:
    # a failure before COMMIT rolls the draft back with them, so a retry can
    # never duplicate an insertion or leave a replacement permanently pending
    # (B-01R-4/B3-04).
    with wb.write_tx(project) as db:
        if draft:
            if text_changed or not pre_applied:
                updated = chapter_editor.save_draft(project, chapter, {
                    "title": data.get("title") or (draft.get("title") or current_title),
                    "content": text,
                    "expected_draft_id": draft["draft_id"],
                    "expected_draft_epoch": draft["draft_epoch"],
                    "expected_draft_revision": draft["draft_revision"],
                    "base_version_id": draft.get("base_version_id"),
                    "base_content_sha256": draft.get("base_content_sha256"),
                })
                draft = updated["draft"]
        else:
            epoch = wb.draft_epoch(project, chapter)
            client_epoch = data.get("expected_draft_epoch")
            if client_epoch is not None and int(client_epoch) != int(epoch):
                raise AnnotationError("draft_conflict", status=409,
                                      detail={"current_draft": None, "draft_epoch": epoch})
            updated = chapter_editor.save_draft(project, chapter, {
                "title": data.get("title") or current_title,
                "content": text, "expected_draft_id": None, "expected_draft_epoch": epoch,
                "expected_draft_revision": 0,
            })
            draft = updated["draft"]
        superseded_previews: set = set()
        for item in list(result["results"]) + pre_applied:
            hunk_id = item["hunk_id"]
            chosen = next((row for row in rows if row["id"] == hunk_id), None)
            custom_value = (chosen or {}).get("custom_text")
            if item["status"] == "applied":
                db.execute(
                    "UPDATE annotation_hunks SET status='applied_to_draft', applied_draft_id=?, "
                    "applied_draft_revision=?, applied_range_json=?, applied_text_sha256=?, "
                    "custom_text=?, updated_at=? WHERE id=?",
                    (draft["draft_id"], draft["draft_revision"],
                     json.dumps([item.get("start"), item.get("end")]),
                     _sha(item.get("applied_text") or ""), custom_value, stamp, hunk_id))
                db.execute(
                    "INSERT INTO patch_ledger(chapter_id, chapter_uid, preview_id, hunk_id, annotation_id, "
                    "draft_id, draft_revision, applied_range_json, before_quote, applied_text, custom, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (chapter, wb.chapter_uid(project, chapter),
                     (chosen or {}).get("preview_id"), hunk_id, (chosen or {}).get("annotation_id"),
                     draft["draft_id"], draft["draft_revision"],
                     json.dumps([item.get("base_start", item.get("start")),
                                 item.get("base_end", item.get("end"))]),
                     item.get("before_text") or "",
                     item.get("applied_text") or "", 1 if custom_value is not None else 0, stamp))
            elif item["status"] == "already_applied":
                db.execute("UPDATE annotation_hunks SET status='applied_to_draft', applied_draft_id=?, "
                           "applied_draft_revision=?, updated_at=? WHERE id=?",
                           (draft["draft_id"], draft["draft_revision"], stamp, hunk_id))
                if hunk_id not in ledger_by_hunk:
                    landed_text = ((chosen or {}).get("custom_text")
                                   if (chosen or {}).get("custom_text") is not None
                                   else (chosen or {}).get("after_text") or "")
                    db.execute(
                        "INSERT INTO patch_ledger(chapter_id, chapter_uid, preview_id, hunk_id, annotation_id, "
                        "draft_id, draft_revision, applied_range_json, before_quote, applied_text, custom, created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (chapter, wb.chapter_uid(project, chapter),
                         (chosen or {}).get("preview_id"), hunk_id, (chosen or {}).get("annotation_id"),
                         draft["draft_id"], draft["draft_revision"],
                         json.dumps([item.get("start"), item.get("end")]),
                         (chosen or {}).get("before_text") or "",
                         landed_text, 1 if custom_value is not None else 0, stamp))
            if item["status"] in {"applied", "already_applied"}:
                group_id = (chosen or {}).get("group_id")
                if group_id:
                    overlapped = [row[0] for row in db.execute(
                        "SELECT preview_id FROM annotation_hunks WHERE group_id=? AND id<>? "
                        "AND status='pending' AND char_start < ? AND ? < char_end",
                        (group_id, hunk_id, int(item.get("end") or 0), int(item.get("start") or 0)))]
                    db.execute(
                        "UPDATE annotation_hunks SET status='superseded', updated_at=? "
                        "WHERE group_id=? AND id<>? AND status='pending' "
                        "AND char_start < ? AND ? < char_end",
                        (stamp, group_id, hunk_id,
                         int(item.get("end") or 0), int(item.get("start") or 0)))
                    superseded_previews.update(value for value in overlapped if value)
        preview_ids = {row.get("preview_id") for row in rows if row.get("preview_id")}
        preview_ids |= superseded_previews
        for preview_id in preview_ids:
            _refresh_preview_status(db, preview_id, stamp)
        _recompute_annotation_status(project, {row["annotation_id"] for row in rows}, db=db)
    applied = [item for item in result["results"] if item["status"] == "applied"] + pre_applied
    if applied:
        outcome = "applied"
    elif result["conflicts"]:
        outcome = "conflict"
    else:
        outcome = "noop"
    skipped = [{"hunk_id": item.get("hunk_id"), "status": item.get("status"),
                "reason": item.get("reason")}
               for item in result["results"]
               if item.get("status") not in {"applied", "already_applied", "overlap_conflict"}]
    return {"status": outcome, "chapter_id": chapter, "draft": draft,
            "applied": applied,
            "conflicts": result["conflicts"], "clean": result["clean"],
            "skipped": skipped}


def undo_apply(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    chapter = int(chapter)
    op_id = str(data.get("op_id") or "")
    params = {"ledger_id": data.get("ledger_id")}
    if op_id:
        cached = _idempotency_begin(project, "annotations.undo_apply", op_id, params)
        if cached is not None:
            return cached
    try:
        result = _undo_apply_impl(project, chapter, data)
    except BaseException:
        if op_id:
            _idempotency_fail(project, "annotations.undo_apply", op_id)
        raise
    if op_id:
        try:
            _idempotency_complete(project, "annotations.undo_apply", op_id, result)
        except Exception:
            pass
    return result


def _undo_apply_impl(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
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
    entry = {
        "applied_text": row.get("applied_text"), "before_quote": row.get("before_quote"),
        "char_start": applied_range[0] if len(applied_range) == 2 else None,
        "char_end": applied_range[1] if len(applied_range) == 2 else None,
    }
    if row.get("preview_id") and entry["char_start"] is not None:
        # The ledger offset is only meaningful in the preview's base snapshot.
        # Passing that snapshot's context lets reverse_patch follow an author
        # who typed before the patch without ever falling back to a global
        # "unique occurrence" guess (A-P3-13).
        with wb.connect(project) as db:
            preview_row = db.execute("SELECT base_snapshot_id FROM preview_index WHERE preview_id=?",
                                     (row.get("preview_id"),)).fetchone()
        if preview_row and preview_row[0]:
            try:
                base = read_snapshot(project, preview_row[0])
            except AnnotationError:
                base = ""
            if base:
                start = entry["char_start"] or 0
                before = str(row.get("before_quote") or "")
                entry["prefix_ctx"] = text_merge.slice_codepoints(base, max(0, start - 32), start)
                entry["suffix_ctx"] = text_merge.slice_codepoints(
                    base, start + text_merge.codepoint_length(before),
                    start + text_merge.codepoint_length(before) + 32)
    result = text_merge.reverse_patch(draft.get("content") or "", entry)
    if result["status"] != "reversed":
        raise AnnotationError("undo_relocation_needed", status=409, detail={"reason": result.get("reason")})
    stamp = _now()
    # Draft rollback, ledger deletion and hunk reset must commit together: a
    # failure after the draft was saved used to leave the hunk applied forever
    # with a ledger row that no longer matches the draft (A-P3-12).
    with wb.write_tx(project) as db:
        updated = chapter_editor.save_draft(project, chapter, {
            "title": draft.get("title") or "", "content": result["text"],
            "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
            "expected_draft_revision": draft["draft_revision"],
            "base_version_id": draft.get("base_version_id"),
            "base_content_sha256": draft.get("base_content_sha256"),
        })
        db.execute("DELETE FROM patch_ledger WHERE id=?", (row["id"],))
        if row.get("hunk_id"):
            db.execute("UPDATE annotation_hunks SET status='pending', applied_draft_id=NULL, "
                       "applied_draft_revision=NULL, applied_range_json=NULL, updated_at=? WHERE id=?",
                       (stamp, row["hunk_id"]))
        _refresh_preview_status(db, row.get("preview_id"), stamp)
        if row.get("annotation_id"):
            _recompute_annotation_status(project, {row["annotation_id"]}, db=db)
    return {"status": "reverted", "chapter_id": chapter, "draft": updated["draft"],
            "range": [result.get("start"), result.get("end")]}


def revert_draft_hunks(project, chapter: int, draft_id: Optional[str]) -> List[str]:
    stamp = _now()
    with wb.write_tx(project) as db:
        rows = [dict(r) for r in db.execute(
            "SELECT id, annotation_id, preview_id FROM annotation_hunks "
            "WHERE chapter_id=? AND applied_draft_id=? AND status='applied_to_draft'",
            (int(chapter), draft_id))]
        db.execute("DELETE FROM patch_ledger WHERE chapter_id=? AND draft_id=?",
                   (int(chapter), draft_id))
        db.execute("UPDATE annotation_hunks SET status='pending', applied_draft_id=NULL, "
                   "applied_draft_revision=NULL, applied_range_json=NULL, updated_at=? "
                   "WHERE chapter_id=? AND applied_draft_id=? AND status='applied_to_draft'",
                   (stamp, int(chapter), draft_id))
        for preview_id in {row.get("preview_id") for row in rows if row.get("preview_id")}:
            _refresh_preview_status(db, preview_id, stamp)
        _recompute_annotation_status(project, {row["annotation_id"] for row in rows
                                               if row.get("annotation_id")}, db=db)
    return [row["id"] for row in rows]


def reject_hunks(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Reject individual hunks without touching the draft (B-23)."""
    chapter = int(chapter)
    op_id = str(data.get("op_id") or "")
    if not op_id:
        raise AnnotationError("op_id_required")
    selected = _as_list(data.get("hunk_ids"), "hunk_ids")
    if not selected:
        raise AnnotationError("hunk_ids_required")
    params = {"hunk_ids": sorted(selected)}
    try:
        cached = _idempotency_begin(project, "annotations.reject_hunks", op_id, params)
    except AnnotationError as exc:
        if exc.code == "op_in_progress" and _selected_states(project, chapter, selected) == {"rejected"}:
            try:
                return _reject_hunks_impl(project, chapter, selected)
            except AnnotationError:
                pass
        raise
    if cached is not None:
        return cached
    try:
        result = _reject_hunks_impl(project, chapter, selected)
    except BaseException:
        _idempotency_fail(project, "annotations.reject_hunks", op_id)
        raise
    try:
        _idempotency_complete(project, "annotations.reject_hunks", op_id, result)
    except Exception:
        pass
    return result


def _reject_hunks_impl(project, chapter: int, selected: List[str]) -> Dict[str, Any]:
    with wb.connect(project) as db:
        placeholders = ",".join("?" for _ in selected)
        rows = [dict(r) for r in db.execute(
            f"SELECT id, annotation_id, preview_id, status FROM annotation_hunks "
            f"WHERE chapter_id=? AND id IN ({placeholders}) AND status IN ('pending','rejected')",
            (chapter, *selected))]
    pending = [row for row in rows if row["status"] == "pending"]
    if not pending:
        if rows:
            # A retry whose response was lost must not become "no pending
            # hunks": the author's rejections already landed (A-P3-03).
            return {"status": "rejected", "chapter_id": chapter,
                    "rejected": [row["id"] for row in rows], "already_rejected": True}
        raise AnnotationError("no_pending_hunks")
    stamp = _now()
    with wb.write_tx(project) as db:
        for row in pending:
            db.execute("UPDATE annotation_hunks SET status='rejected', updated_at=? "
                       "WHERE id=? AND status='pending'", (stamp, row["id"]))
        for preview_id in {row.get("preview_id") for row in pending if row.get("preview_id")}:
            _refresh_preview_status(db, preview_id, stamp)
        _recompute_annotation_status(project, {row["annotation_id"] for row in pending}, db=db)
    rejected = [row["id"] for row in rows]
    return {"status": "rejected", "chapter_id": chapter, "rejected": rejected}


def mark_committed(project, chapter: int, *, text: str, draft_id: Optional[str] = None) -> Dict[str, Any]:
    """After Ctrl+S: honestly attribute each applied hunk within ±120 codepoints.

    All row updates run in one write transaction so a failure cannot leave a
    half-committed hunk set (B-29).
    """
    chapter = int(chapter)
    committed = 0
    modified = 0
    annotations_touched: set = set()
    stamp = _now()
    with wb.write_tx(project) as db:
        rows = [_row_hunk(r) for r in db.execute(
            "SELECT * FROM annotation_hunks WHERE chapter_id=? AND status='applied_to_draft'",
            (chapter,))]
        for row in rows:
            applied_range = row.get("applied_range") or []
            applied_text = (row.get("custom_text") if row.get("custom_text") is not None
                            else row.get("after_text") or "")
            before_text = str(row.get("before_text") or "")
            start = int(applied_range[0]) if len(applied_range) == 2 else 0
            span = text_merge.codepoint_length(applied_text) if applied_text \
                else text_merge.codepoint_length(before_text)
            window = text_merge.slice_codepoints(text, max(0, start - 120), start + span + 120)
            if applied_text:
                status = "committed" if applied_text in window else "committed_modified"
            else:
                # Pure deletion: it landed when the original quote is gone.
                status = "committed" if before_text and before_text not in window \
                    else "committed_modified"
            db.execute("UPDATE annotation_hunks SET status=?, updated_at=? WHERE id=?",
                       (status, stamp, row["id"]))
            committed += status == "committed"
            modified += status == "committed_modified"
            if row.get("annotation_id"):
                annotations_touched.add(row["annotation_id"])
            if row.get("preview_id"):
                db.execute("UPDATE preview_index SET status='committed', updated_at=? "
                           "WHERE preview_id=?", (stamp, row["preview_id"]))
        db.execute("DELETE FROM patch_ledger WHERE chapter_id=?", (chapter,))
        _recompute_annotation_status(project, annotations_touched, db=db)
    return {"committed": committed, "committed_modified": modified}


def migrate_split(project, chapter: int, offset: int, split_text: str,
                  second_text: str) -> Dict[str, Any]:
    """Re-anchor the second half's annotations to the new chapter.

    Split moves body bytes; leaving the annotations on the old chapter makes
    them permanently ``relocated_needed`` and the new chapter empty (A-P2-08).
    Only annotations whose selection starts at/after the split point move;
    earlier selections keep their (still valid) old-chapter anchor.
    """
    chapter = int(chapter)
    split_text = text_merge.normalize_lf(split_text)
    second_text = text_merge.normalize_lf(second_text)
    offset = int(offset)
    second_digest = save_snapshot(project, second_text)
    split_digest = _sha(split_text)
    uid = wb.chapter_uid(project, chapter + 1)
    moved_annotations: List[str] = []
    moved_hunks = 0
    with wb.connect(project) as db:
        annotations_rows = [_row_annotation(r) for r in db.execute(
            "SELECT * FROM annotations WHERE chapter_id=?", (chapter,))]
        preview_rows = {row["preview_id"]: dict(row) for row in db.execute(
            "SELECT preview_id, base_snapshot_id FROM preview_index WHERE chapter_id=?", (chapter,))}
    for item in annotations_rows:
        anchor = item.get("anchor") or {}
        if not anchor:
            continue
        try:
            base = read_snapshot(project, anchor.get("base_snapshot_id"))
        except AnnotationError:
            continue
        located = text_merge.relocate_anchor(base, split_text, anchor)
        if located.get("status") not in {"exact", "relocated"}:
            continue
        start, end = int(located["start"]), int(located["end"])
        if start < offset:
            continue
        new_start, new_end = start - offset, end - offset
        new_anchor = dict(anchor)
        new_anchor.update({
            "char_start": new_start, "char_end": new_end,
            "para_start": text_merge.paragraph_index(second_text, new_start),
            "para_end": text_merge.paragraph_index(second_text, new_end),
            "prefix_ctx": text_merge.context_of(second_text, new_start, new_end)[0],
            "suffix_ctx": text_merge.context_of(second_text, new_start, new_end)[1],
            "base_snapshot_id": second_digest,
            "base_origin": "split",
        })
        stamp = _now()
        with wb.write_tx(project) as db:
            db.execute("UPDATE annotations SET chapter_id=?, chapter_uid=?, anchor_json=?, "
                       "updated_at=? WHERE id=?",
                       (chapter + 1, uid, json.dumps(new_anchor, ensure_ascii=False), stamp,
                        item["id"]))
            hunks = [dict(r) for r in db.execute(
                "SELECT h.id, h.char_start, h.char_end, p.base_snapshot_id AS preview_base "
                "FROM annotation_hunks h LEFT JOIN preview_index p ON p.preview_id=h.preview_id "
                "WHERE h.annotation_id=?", (item["id"],))]
            for hunk in hunks:
                preview_base = hunk.get("preview_base")
                if preview_base not in {None, split_digest, anchor.get("base_snapshot_id")}:
                    db.execute("UPDATE annotation_hunks SET status='superseded', chapter_id=?, "
                               "chapter_uid=?, updated_at=? WHERE id=?",
                               (chapter + 1, uid, stamp, hunk["id"]))
                    continue
                h_start = int(hunk.get("char_start") or 0)
                h_end = int(hunk.get("char_end") or 0)
                if h_start < offset and h_end > offset:
                    # Straddles the split point: it belongs to neither half.
                    db.execute("UPDATE annotation_hunks SET status='superseded', chapter_id=?, "
                               "chapter_uid=?, updated_at=? WHERE id=?",
                               (chapter + 1, uid, stamp, hunk["id"]))
                    continue
                db.execute("UPDATE annotation_hunks SET chapter_id=?, chapter_uid=?, "
                           "char_start=MAX(char_start-?, 0), char_end=MAX(char_end-?, 0), "
                           "updated_at=? WHERE id=?",
                           (chapter + 1, uid, offset, offset, stamp, hunk["id"]))
                moved_hunks += 1
            for preview_id, preview in preview_rows.items():
                if preview.get("base_snapshot_id") in {split_digest, anchor.get("base_snapshot_id")}:
                    preview_rows[preview_id]["base_snapshot_id"] = second_digest
            db.execute("UPDATE preview_index SET chapter_id=?, chapter_uid=?, base_snapshot_id=?, "
                       "updated_at=? WHERE annotation_id=?",
                       (chapter + 1, uid, second_digest, stamp, item["id"]))
        moved_annotations.append(item["id"])
    return {"annotations": moved_annotations, "hunks": moved_hunks, "chapter_id": chapter + 1}


def _annotation_status_updates(db, ids: List[str]) -> List[tuple]:
    placeholders = ",".join("?" for _ in ids)
    rows = [dict(r) for r in db.execute(
        f"SELECT annotation_id, status FROM annotation_hunks "
        f"WHERE annotation_id IN ({placeholders})", tuple(ids))]
    current = {str(row[0]): str(row[1] or "") for row in db.execute(
        f"SELECT id, status FROM annotations WHERE id IN ({placeholders})", tuple(ids))}
    grouped: Dict[str, List[str]] = {}
    for row in rows:
        grouped.setdefault(row["annotation_id"], []).append(row["status"])
    updates = []
    for annotation_id in ids:
        states = grouped.get(annotation_id)
        if not states:
            continue
        if all(state in TERMINAL_HUNKS for state in states):
            landed = any(state in {"committed", "committed_modified"} for state in states)
            status = "accepted" if landed else "rejected"
        elif any(state in {"committed", "committed_modified"} for state in states):
            status = "partially_applied"
        elif any(state == "applied_to_draft" for state in states):
            status = "partially_applied"
        elif any(state == "pending" for state in states):
            status = "open"
        else:
            status = "rejected"
        if current.get(annotation_id) == "rejected" and status in {"accepted", "partially_applied"}:
            # Rejection is a one-way author decision for the remaining hunks.
            status = "rejected"
        updates.append((status, _now(), annotation_id))
    return updates


def _recompute_annotation_status(project, annotation_ids: Iterable[str], *, db=None) -> None:
    ids = sorted({str(value) for value in annotation_ids if value})
    if not ids:
        return
    if db is not None:
        updates = _annotation_status_updates(db, ids)
        if updates:
            db.executemany("UPDATE annotations SET status=?, updated_at=? WHERE id=?", updates)
        return
    with wb.connect(project) as connection:
        updates = _annotation_status_updates(connection, ids)
    if updates:
        with wb.write_tx(project) as connection:
            connection.executemany("UPDATE annotations SET status=?, updated_at=? WHERE id=?",
                                   updates)


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
