"""自由直写：临时草稿、正式版本、作者定稿与章节编辑闭环。

This module is the single write gate for ``正文/*.md`` used by the new
workbench.  It composes the existing building blocks instead of duplicating
them:

* :mod:`integration.chapter_versions` owns version identity, byte-exact
  restore and the commit marker;
* :mod:`integration.workbench_db` owns drafts, ``draft_epoch`` and
  ``idempotency_keys``;
* :mod:`integration.transaction_journal` owns cross-file atomic writes and the
  Windows path/rename protections;
* :mod:`integration.invalidation` is triggered once by the version layer;
* :mod:`integration.text_checks` / ``style_rules`` / ``style_stats`` power the
  zero-cost local quick check.

No model call happens here except the explicit, non-blocking memory preview.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fanqie_auto_publish import publication_safety as safety
from integration import chapter_versions as versions
from integration import workbench_db as wb

MAX_CONTENT_BYTES = 200 * 1024
MAX_TITLE_CHARS = 120
MAX_IMPORT_BYTES = 8 * 1024 * 1024
_TRASH = "trash"
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                     *(f"LPT{i}" for i in range(1, 10))}
_WINDOWS_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_OP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_CHAPTER_HEADING = re.compile(
    r"^\s*(?:第\s*([0-9０-９零〇一二三四五六七八九十百千]+)\s*[章节回]|Chapter\s+(\d+))[ \t　]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


class ChapterError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400, detail: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_lf(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _body_digest(text: str) -> str:
    return safety.body_digest(_normalize_lf(text))


def _raw_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def _decode(data: bytes) -> str:
    return _strip_bom(data.decode("utf-8", errors="replace"))


def _count_words(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _windows_name_problem(name: str) -> Optional[str]:
    raw = unicodedata.normalize("NFC", str(name or ""))
    if not raw or raw.endswith((" ", ".")):
        return "trailing_space_or_dot"
    if _WINDOWS_BAD.search(raw):
        return "invalid_character"
    stem = raw.split(".")[0].strip().upper()
    if stem in _WINDOWS_RESERVED:
        return "windows_reserved_name"
    return None


def _validate_title(title: str) -> str:
    value = unicodedata.normalize("NFC", str(title or "")).strip()
    if len(value) > MAX_TITLE_CHARS:
        raise ChapterError("title_too_long")
    if "\x00" in value or any(ord(ch) < 32 for ch in value):
        raise ChapterError("invalid_title")
    problem = _windows_name_problem(value)
    if problem:
        raise ChapterError(f"invalid_title:{problem}")
    return value


def _validate_title_for_chapter(chapter: int, title: str) -> str:
    """Validate characters *and* the final UTF-8 filename byte budget."""
    value = _validate_title(title)
    try:
        versions.validate_chapter_filename(int(chapter), value, with_temporary=True)
    except versions.VersionConflict as exc:
        raise ChapterError(str(exc) or "title_too_long_for_filesystem", status=400) from None
    return value


def _validate_op_id(value: Any) -> str:
    text = str(value or "")
    if text and not _OP_ID_RE.fullmatch(text):
        raise ChapterError("invalid_op_id")
    return text


def _validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise ChapterError("content_required")
    if "\x00" in content:
        raise ChapterError("invalid_content")
    text = _normalize_lf(content)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChapterError("invalid_content") from exc
    if len(encoded) > MAX_CONTENT_BYTES:
        raise ChapterError("content_too_large", status=413)
    return text


def _receipts_path(project) -> Path:
    return Path(project) / ".webnovel" / "writer_receipts.json"


def _read_receipts(project) -> Dict[str, Any]:
    path = _receipts_path(project)
    if not path.is_file():
        return {}
    try:
        value = safety.read_json_strict(path)
    except (OSError, ValueError) as exc:
        raise ChapterError("receipts_corrupt") from exc
    if not isinstance(value, dict):
        raise ChapterError("receipts_corrupt")
    return value


def _update_receipts(project, mutate) -> None:
    """Read-latest → mutate → write under ``receipts.lock``.

    Never rewrite the table from a stale snapshot: a concurrent
    ``author_confirm`` for another chapter must survive a delete (A-P2-14).
    """
    path = _receipts_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / "receipts.lock"
    with safety.file_lock(lock):
        latest = _read_receipts(project)
        mutate(latest)
        safety.atomic_json(path, latest)


def _write_receipts(project, receipts: Dict[str, Any]) -> None:
    _update_receipts(project, lambda latest: latest.update(receipts))


@contextmanager
def _locked(project, chapter: int, *, op_id: Optional[str] = None, action: str = "chapter_save"):
    folder = Path(project) / ".webnovel" / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with safety.file_lock(folder / f"chapter-{int(chapter):04d}.lock"):
            yield
    except Exception as exc:
        if op_id:
            try:
                wb.idempotency_fail(project, actor="author",
                                    project_id=str(Path(project).resolve()),
                                    action=action, op_id=op_id)
            except Exception:
                pass
        if exc.__class__.__name__ == "PublicationBlocked":
            raise ChapterError("file_in_use_retry", status=409) from None
        raise


def _git_bytes(path: Optional[Path]) -> Optional[bytes]:
    if path is None or not Path(path).is_file():
        return None
    return Path(path).read_bytes()


def _published_state(project, chapter: int) -> Dict[str, Any]:
    """Read-only publication snapshot for one chapter (never mutates queue)."""
    try:
        receipts = _read_receipts(project).get(str(int(chapter))) or {}
    except ChapterError:
        # 回执损坏不能把已成功的正文提交报成失败；按未发布处理并让诊断面板修复。
        receipts = {}
    if not isinstance(receipts, dict):
        receipts = {}
    published_sha = receipts.get("published_sha256") or (receipts.get("publish") or {}).get("sha256")
    status = "published" if published_sha else ("staged" if receipts.get("staged_at") else "unpublished")
    try:
        disk = versions.file_sha256(versions.chapter_path(project, chapter))
    except versions.VersionConflict:
        # Duplicate chapter files must not turn a committed save into a 500;
        # the reconciliation result already reports the title conflict.
        disk = None
    return {
        "status": status,
        "published_sha256": published_sha,
        "local_diverged": bool(published_sha and disk and published_sha != disk),
    }


def _review_state(project, chapter: int) -> Dict[str, Any]:
    try:
        receipts = _read_receipts(project).get(str(int(chapter))) or {}
    except ChapterError:
        receipts = {}
    review = receipts.get("review") or {}
    path = versions.chapter_path(project, chapter)
    disk_sha = versions.file_sha256(path)
    meta = versions.current_version(project, chapter)
    confirmed = review.get("review_decision") == "author_confirmed" and review.get("author_confirmed") is True
    eligible = False
    if confirmed:
        try:
            from fanqie_auto_publish import publication_safety
            eligible = publication_safety.review_eligible(
                review, safety.body_digest(_decode(path.read_bytes())) if path else "", project, chapter)
        except (OSError, ValueError):
            eligible = False
    return {
        "reviewed": bool(review.get("success") and review.get("review_decision") == "pass"),
        "human_review_required": review.get("review_decision") == "needs_human_review",
        "author_confirmed": confirmed,
        "confirmed_version_id": review.get("confirmed_version_id"),
        "confirmed_title": review.get("confirmed_title"),
        "review_status": review.get("review_decision"),
        "auto_review_count": review.get("auto_review_count", 0),
        "publish_eligible": eligible,
        "stale": bool(confirmed and not eligible),
        "current_version_id": (meta or {}).get("version_id"),
        "disk_sha256": disk_sha,
    }


def chapter_state(project, chapter: int, *, include_draft: bool = True) -> Dict[str, Any]:
    chapter = int(chapter)
    if chapter <= 0:
        raise ChapterError("chapter_invalid", status=404)
    path = versions.chapter_path(project, chapter)
    if path is None:
        raise ChapterError("chapter_missing", status=404)
    raw = path.read_bytes()
    title = versions.parse_chapter_name(path.name)[1] if versions.parse_chapter_name(path.name) else ""
    text = _decode(raw)
    meta = versions.current_version(project, chapter)
    draft = wb.get_draft(project, chapter) if include_draft else None
    try:
        from integration import annotations
        summary = annotations.summary(project, chapter)
    except Exception:
        summary = {"open_count": 0, "proposed_count": 0, "pending_previews": 0}
    payload = {
        "id": chapter,
        "chapter_uid": wb.chapter_uid(project, chapter),
        "title": title,
        "content": text,
        "words": _count_words(text),
        "sha256": _raw_sha(raw),
        "content_sha256": _raw_sha(raw),
        "body_digest": _body_digest(text),
        "version_id": (meta or {}).get("version_id"),
        "version_seq": (meta or {}).get("version_seq") or (meta or {}).get("seq"),
        "version_source": (meta or {}).get("source"),
        "review_state": _review_state(project, chapter),
        "publication": _published_state(project, chapter),
        "annotations_summary": summary,
    }
    if include_draft:
        epoch = (draft or {}).get("draft_epoch")
        if epoch is None:
            epoch = wb.draft_epoch(project, chapter)
        base_id = (draft or {}).get("base_version_id") or (draft or {}).get("base_content_sha256")
        base_content = None
        if draft and base_id:
            try:
                base_content = versions.read_version(project, chapter, str(base_id))["text"]
            except Exception:
                base_content = None
        payload["draft"] = {
            "exists": bool(draft),
            "draft_id": (draft or {}).get("draft_id"),
            "draft_epoch": epoch,
            "draft_revision": (draft or {}).get("draft_revision"),
            "base_version_id": (draft or {}).get("base_version_id"),
            "base_sha256": (draft or {}).get("base_content_sha256"),
            "base_content_sha256": (draft or {}).get("base_content_sha256"),
            "base_content": base_content,
            "title": (draft or {}).get("title"),
            "content": (draft or {}).get("content"),
            "cursor": (draft or {}).get("cursor", {}),
            "updated_at": (draft or {}).get("updated_at"),
            "stale": bool(draft and meta and draft.get("base_version_id")
                          and meta.get("version_id") != draft.get("base_version_id")),
        }
    # v0.7.5 兼容顶层字段
    payload.update({"reviewed": payload["review_state"]["reviewed"],
                    "human_review_required": payload["review_state"]["human_review_required"],
                    "review_status": payload["review_state"]["review_status"],
                    "auto_review_count": payload["review_state"]["auto_review_count"]})
    return payload


def _drop_draft_doc(project, chapter: int, draft_id: Optional[str]) -> None:
    if not draft_id:
        return
    try:
        wb.drop_document(project, f"draft:{int(chapter)}:{draft_id}")
    except Exception:
        pass


def save_draft(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    chapter = int(chapter)
    previous = wb.get_draft(project, chapter)
    title = _validate_title(data.get("title", ""))
    content = _validate_content(data.get("content", ""))
    try:
        draft = wb.save_draft(
            project, chapter, title=title, content=content,
            base_version_id=data.get("base_version_id"),
            base_content_sha256=data.get("base_content_sha256"),
            expected_draft_id=data.get("expected_draft_id"),
            expected_draft_epoch=int(data.get("expected_draft_epoch") or 0),
            expected_draft_revision=int(data.get("expected_draft_revision") or 0),
            client_session_id=str(data.get("client_session_id") or ""),
            cursor=data.get("cursor") if isinstance(data.get("cursor"), dict) else {},
        )
    except wb.DraftConflict as exc:
        current = exc.current or wb.get_draft(project, chapter) or {}
        raise ChapterError("draft_conflict", status=409, detail={
            "current_draft": {k: current.get(k) for k in
                              ("draft_id", "draft_epoch", "draft_revision", "title", "content",
                               "base_version_id", "base_content_sha256", "updated_at")},
            "message": "草稿已在其他窗口更新，请比对后保存",
        }) from None
    try:
        wb.index_document(project, doc_key=f"draft:{chapter}:{draft['draft_id']}", kind="draft",
                          chapter_id=chapter, title=title, content=content)
    except Exception:
        pass
    if previous and previous.get("draft_id") != draft.get("draft_id"):
        _drop_draft_doc(project, chapter, previous.get("draft_id"))
    return {"status": "saved", "chapter_id": chapter, "draft": draft}


def discard_draft(project, chapter: int, *, draft_id: Optional[str] = None) -> Dict[str, Any]:
    chapter = int(chapter)
    draft = wb.get_draft(project, chapter)
    if not draft:
        return {"status": "discarded", "deleted": False, "chapter_id": chapter}
    try:
        result = wb.delete_draft(project, chapter, draft_id=draft_id or draft.get("draft_id"))
    except wb.DraftConflict as exc:
        raise ChapterError("draft_conflict", status=409, detail={"current_draft": exc.current}) from None
    try:
        from integration import annotations
        reverted = annotations.revert_draft_hunks(project, chapter, draft.get("draft_id"))
    except Exception:
        reverted = []
    _drop_draft_doc(project, chapter, draft.get("draft_id"))
    return {"status": "discarded", "chapter_id": chapter, **result, "reverted_hunks": reverted}


def _idempotent(project, action: str, op_id: str, params: Any) -> Optional[Dict[str, Any]]:
    if not op_id:
        raise ChapterError("op_id_required")
    result = wb.idempotency_begin(project, actor="author", project_id=str(Path(project).resolve()),
                                  action=action, op_id=op_id, params=params)
    if result["status"] == "mismatch":
        raise ChapterError("op_id_params_mismatch", status=409)
    if result["status"] == "completed":
        return result.get("response")
    if result["status"] == "in_progress":
        raise ChapterError("op_in_progress", status=409, detail={"message": "同一操作正在执行，请稍候"})
    return None


def _finish(project, action: str, op_id: str, response: Dict[str, Any]) -> bool:
    """Best-effort completion; the body commit already succeeded.

    A SQLite busy/disk failure here must not turn a committed save into an
    error response (A-P2-1); retries recover the response from the commit
    marker instead.
    """
    try:
        wb.idempotency_complete(project, actor="author", project_id=str(Path(project).resolve()),
                                action=action, op_id=op_id, response=response)
        return True
    except Exception:
        return False


def _idempotent_soft(project, action: str, op_id: str, params: Any) -> Optional[Dict[str, Any]]:
    """Idempotency for optional ``op_id`` write endpoints (A-P2-10)."""
    if not op_id:
        return None
    result = wb.idempotency_begin(project, actor="author", project_id=str(Path(project).resolve()),
                                  action=action, op_id=op_id, params=params)
    if result["status"] == "mismatch":
        raise ChapterError("op_id_params_mismatch", status=409)
    if result["status"] == "completed":
        return result.get("response")
    if result["status"] == "in_progress":
        raise ChapterError("op_in_progress", status=409, detail={"message": "同一操作正在执行，请稍候"})
    return None


def _finish_soft(project, action: str, op_id: str, response: Dict[str, Any]) -> None:
    if op_id:
        _finish(project, action, op_id, response)


def _fail_soft(project, action: str, op_id: str) -> None:
    if not op_id:
        return
    try:
        wb.idempotency_fail(project, actor="author", project_id=str(Path(project).resolve()),
                            action=action, op_id=op_id)
    except Exception:
        pass


def _recover_completed_save(project, chapter: int, op_id: str, content: str,
                            title: str) -> Optional[Dict[str, Any]]:
    """Rebuild the response of a save whose ``idempotency_complete`` failed.

    The commit marker is the source of truth: only when it is committed, the
    body/index still carry exactly that sha, and title/content match the
    request do we return success.  Otherwise the normal conflict checks run.
    """
    if not op_id:
        return None
    try:
        record = versions._load_commit(project, op_id)
    except versions.VersionError:
        return None
    if not isinstance(record, dict) or record.get("state") != "committed":
        return None
    if int(record.get("chapter_id") or 0) != int(chapter):
        return None
    sha = _raw_sha(content.encode("utf-8"))
    if record.get("content_sha256") != sha:
        return None
    if versions.normalize_title(str(record.get("title") or "")) != versions.normalize_title(title):
        return None
    try:
        disk_sha = versions.file_sha256(versions.chapter_path(project, chapter))
    except versions.VersionConflict:
        disk_sha = None
        duplicate_files = True
    else:
        duplicate_files = False
    if not duplicate_files and disk_sha != sha:
        return None
    entry = versions.load_index(project)["chapters"].get(str(int(chapter))) or {}
    if entry.get("current") != sha:
        return None
    # Finish a rename/receipt that an earlier failed attempt left behind; the
    # commit marker is the durable source of truth (A-R-03/A-R-06).
    if duplicate_files:
        outcome = {"status": "partial", "title_conflict": True, "renamed": False,
                   "title_renamed": False,
                   "error": "VersionConflict: duplicate_chapter_files"}
    else:
        outcome = versions.reconcile_title(project, chapter, title=title, op_id=op_id)
    draft = wb.get_draft(project, chapter)
    response = {
        "status": "saved", "state": "committed", "chapter_id": int(chapter),
        "title": title, "sha256": sha, "content_sha256": sha,
        "version_id": record.get("version_id") or entry.get("current_version_id"),
        "unchanged": False, "recovered": True, "draft_cleared": draft is None,
        "draft_preserved": False, "current_draft_revision": (draft or {}).get("draft_revision", 0),
        "renamed": bool(outcome.get("renamed")),
        "title_renamed": bool(outcome.get("title_renamed")),
        "receipt_synced": bool(outcome.get("receipt_synced")),
    }
    if outcome.get("status") == "partial":
        # Do not cache a partial result: the retry must be able to finish the
        # rename/receipt once the conflicting file is removed.
        response["status"] = "partial"
        response["title_conflict"] = bool(outcome.get("title_conflict"))
        if outcome.get("error"):
            response["title_error"] = outcome["error"]
        if outcome.get("receipt_error"):
            response["receipt_error"] = outcome["receipt_error"]
        return response
    _finish(project, "chapter_save", op_id, response)
    return {**response, "reused": True}


def save_version(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """提交正式版本；所有磁盘写入持有单章锁并带乐观并发校验。"""
    chapter = int(chapter)
    if chapter <= 0:
        raise ChapterError("chapter_invalid")
    title = _validate_title_for_chapter(chapter, data.get("title", ""))
    content = _validate_content(data.get("content", ""))
    op_id = _validate_op_id(data.get("op_id"))
    expected_version = str(data.get("expected_version_id") or "").strip()
    expected_sha = str(data.get("expected_content_sha256") or "").strip().lower()
    allow_new = bool(data.get("allow_new"))
    params = {"chapter": chapter, "title": title, "content": content,
              "expected_version_id": expected_version, "expected_content_sha256": expected_sha,
              "submitted_draft_id": data.get("submitted_draft_id"),
              "submitted_draft_epoch": data.get("submitted_draft_epoch"),
              "submitted_draft_revision": data.get("submitted_draft_revision")}
    try:
        versions.recover_pending(project)
    except Exception:
        pass
    recovered = _recover_completed_save(project, chapter, op_id, content, title)
    if recovered is not None:
        return recovered
    existing = _idempotent(project, "chapter_save", op_id, params)
    if existing is not None:
        return {**existing, "reused": True}

    uid = wb.chapter_uid(project, chapter)
    with _locked(project, chapter, op_id=op_id, action="chapter_save"):
        try:
            corrupt = any(not isinstance(value, dict) for value in _read_receipts(project).values())
        except ChapterError:
            corrupt = True
        if corrupt:
            raise ChapterError("receipts_corrupt", status=409)
        path = versions.chapter_path(project, chapter)
        current_sha = versions.file_sha256(path)
        if current_sha is not None:
            meta = versions.current_version(project, chapter)
            if not meta:
                # 老稿首次编辑：只要求磁盘指纹匹配，先把原字节归档为 v1。
                if not expected_sha:
                    raise ChapterError("expected_version_required")
                meta = versions.snapshot(project, chapter, source="legacy-adopted",
                                         note="首次编辑前自动归档原稿")
            elif not expected_version or not expected_sha:
                raise ChapterError("expected_version_required")
            if expected_sha != current_sha:
                raise ChapterError("concurrent_modification", status=409, detail={
                    "current_version_id": (meta or {}).get("version_id"),
                    "current_content_sha256": current_sha,
                    "current_title": versions.parse_chapter_name(path.name)[1] if path else "",
                    "current_content": _decode(path.read_bytes()) if path else "",
                    "message": "正文已在其他窗口、任务或外部编辑器中更新，请比对后保存",
                })
            if meta and expected_version and expected_version not in {meta.get("version_id"), meta.get("sha256")}:
                raise ChapterError("concurrent_modification", status=409, detail={
                    "current_version_id": meta.get("version_id"),
                    "current_content_sha256": current_sha,
                    "message": "版本已更新，请刷新后重试",
                })
        elif not allow_new:
            raise ChapterError("chapter_missing", status=404)

        current_title = versions.parse_chapter_name(path.name)[1] if path and versions.parse_chapter_name(path.name) else ""
        current_text = _decode(path.read_bytes()) if path else ""
        unchanged = bool(path and current_text == content and current_title == title)

        # Rename preflight before touching the body/index: a directory or file
        # squatting on the target name must not produce a half-committed version.
        if path and not unchanged and title != current_title:
            target = path.with_name(f"第{int(chapter)}章" + (f"-{title}" if title else "") + ".md")
            if target.exists() and target.resolve() != path.resolve():
                raise ChapterError("chapter_filename_conflict", status=409)

        if unchanged:
            result = {"status": "unchanged", "state": "unchanged", "chapter_id": chapter,
                      "unchanged": True, "sha256": current_sha, "content_sha256": current_sha,
                      "version_id": (versions.current_version(project, chapter) or {}).get("version_id")}
        else:
            result = versions.write_chapter(project, chapter, content, op_id=op_id,
                                            expected_sha256=current_sha, title=title,
                                            source=str(data.get("source") or "author_edit"),
                                            note=str(data.get("note") or "")[:400],
                                            allow_new=current_sha is None)
            result["status"] = "saved"
            result["unchanged"] = False
            if current_sha is not None:
                # One idempotent reconciliation owns filename + receipt +
                # commit path, so a rename that loses a race is reported as a
                # partial result instead of a bare 409 after the body changed
                # (A-R-03/A-R-06).
                outcome = versions.reconcile_title(project, chapter, title=title,
                                                   op_id=result.get("op_id"))
                result["renamed"] = bool(outcome.get("renamed"))
                result["title_renamed"] = bool(outcome.get("title_renamed"))
                result["receipt_synced"] = bool(outcome.get("receipt_synced"))
                if outcome.get("status") == "partial":
                    result["status"] = "partial"
                    result["title_conflict"] = bool(outcome.get("title_conflict"))
                    if outcome.get("error"):
                        result["title_error"] = outcome["error"]
                    if outcome.get("receipt_error"):
                        result["receipt_error"] = outcome["receipt_error"]

    # 已离开 OS 单章锁：草稿清理与 FTS 更新各自短事务（铁律 A：锁层不嵌套）。
    draft_result = {"cleared": False, "draft_preserved": False}
    if data.get("submitted_draft_id") is not None:
        draft_result = wb.clear_draft_if_matches(
            project, chapter,
            draft_id=str(data.get("submitted_draft_id") or ""),
            draft_epoch=int(data.get("submitted_draft_epoch") or 0),
            draft_revision=int(data.get("submitted_draft_revision") or 0))
        if draft_result.get("cleared"):
            _drop_draft_doc(project, chapter, data.get("submitted_draft_id"))
            try:
                from integration import annotations as _annotations
                _annotations.mark_committed(project, chapter, text=content,
                                            draft_id=str(data.get("submitted_draft_id") or ""))
            except Exception:
                # 批注结算失败不能回滚已经成功的正文提交；下次提交会再次尝试清理。
                pass
    published = _published_state(project, chapter)
    response = {
        **result,
        "chapter_id": chapter,
        "title": title,
        "chapter_uid": uid,
        "draft_preserved": draft_result.get("draft_preserved", False),
        "current_draft_revision": draft_result.get("current_draft_revision", 0),
        "draft_cleared": draft_result.get("cleared", False),
        "published_diverged": bool(published.get("published_sha256")
                                   and published.get("published_sha256") != result.get("content_sha256")),
        "published_sha256": published.get("published_sha256"),
    }
    try:
        wb.index_document(project, doc_key=f"正文:{chapter}", kind="chapter", chapter_id=chapter,
                          title=title, content=content)
    except Exception:
        pass
    _finish(project, "chapter_save", op_id, response)
    return response


def _rename_chapter_file(project, chapter: int, source: Path, title: str,
                         *, op_id: Optional[str] = None) -> bool:
    """Rename a chapter file through the shared idempotent reconciler.

    Kept as a thin compatibility wrapper: filename, receipt destination and
    the commit record must move together, or an interrupted rename becomes
    permanently invisible to every later retry (A-R-03/A-R-06).
    """
    outcome = versions.reconcile_title(project, chapter, title=title, op_id=op_id)
    if outcome.get("title_conflict"):
        raise ChapterError("chapter_filename_conflict", status=409)
    return bool(outcome.get("renamed"))


def new_chapter(project, data: Dict[str, Any]) -> Dict[str, Any]:
    title = _validate_title(data.get("title") or "未命名章节")
    content = _validate_content(data.get("content") or "")
    op_id = _validate_op_id(data.get("op_id") or "")
    params = {"requested_chapter": data.get("chapter"), "title": title, "content": content}
    cached = _idempotent_soft(project, "chapter_new", op_id, params)
    if cached is not None:
        return {**cached, "reused": True}
    try:
        mapping = versions.chapter_map(project)
        chapter = int(data.get("chapter") or (max(mapping) + 1 if mapping else 1))
        if str(chapter) in {str(x) for x in mapping}:
            raise ChapterError("chapter_exists", status=409)
        title = _validate_title_for_chapter(chapter, title)
        uid = wb.chapter_uid(project, chapter)
        result = versions.commit_raw_bytes(project, chapter, content.encode("utf-8"), title=title,
                                           op_id=op_id or uuid.uuid4().hex,
                                           source="author_new", note="新建空白章节", allow_new=True,
                                           expect_absent=True)
        try:
            wb.index_document(project, doc_key=f"正文:{chapter}", kind="chapter", chapter_id=chapter,
                              title=title, content=content)
        except Exception:
            pass
        response = {"status": "created", "chapter_id": chapter, "chapter_uid": uid, "title": title,
                    "version_id": result.get("version_id"), "sha256": result.get("content_sha256")}
    except Exception:
        _fail_soft(project, "chapter_new", op_id)
        raise
    _finish_soft(project, "chapter_new", op_id, response)
    return response


def _chapter_receipt_snapshot(project, chapter: int) -> Dict[str, Any]:
    return _read_receipts(project).get(str(int(chapter))) or {}


def _index_entry(project, chapter: int) -> Dict[str, Any]:
    return (versions.load_index(project)["chapters"].get(str(int(chapter))) or {})


def _drop_index_entry(project, chapter: int) -> None:
    with safety.file_lock(versions._paths(project)["lock"]):
        index = versions.load_index(project)
        if str(int(chapter)) in index["chapters"]:
            index["chapters"].pop(str(int(chapter)), None)
            versions._save_index(project, index)


class _ReceiptsAfterDrop(dict):
    """Late-bound receipts view used when removing one chapter's receipt.

    ``file_lock`` is thread-reentrant, so a same-thread confirm can legitimately
    land after the read but before the write (the adversarial interleaving).
    ``json.dump`` calls ``items()`` at serialization time, so the table we
    actually write always excludes only this chapter and keeps every other
    receipt that exists at that moment (A-P2-14).
    """

    def __init__(self, project, chapter: int):
        super().__init__()
        self._project = project
        self._chapter = str(int(chapter))

    def items(self):
        latest = _read_receipts(self._project)
        latest.pop(self._chapter, None)
        return latest.items()

    def __len__(self):
        latest = _read_receipts(self._project)
        latest.pop(self._chapter, None)
        return len(latest)


def _drop_receipt(project, chapter: int) -> None:
    path = _receipts_path(project)
    if not path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / "receipts.lock"
    with safety.file_lock(lock):
        safety.atomic_json(path, _ReceiptsAfterDrop(project, chapter))


def _active_chapter_tasks(project, chapter: int) -> List[Dict[str, Any]]:
    try:
        with wb.connect(project) as db:
            rows = db.execute(
                "SELECT task_id, state FROM task_queue WHERE chapter_id=? "
                "AND state IN ('pending','running','held') ORDER BY task_id",
                (int(chapter),),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def delete_chapter(project, chapter: int, *, expected_version_id: str = "",
                   expected_content_sha256: str = "", op_id: str = "") -> Dict[str, Any]:
    """受限删除：仅未发布、未入队且为尾章或空章的章节，归档而非物理删除。"""
    chapter = int(chapter)
    op_id = _validate_op_id(op_id)
    params = {"chapter": chapter, "expected_version_id": str(expected_version_id or ""),
              "expected_content_sha256": str(expected_content_sha256 or "")}
    cached = _idempotent_soft(project, "chapter_delete", op_id, params)
    if cached is not None:
        return {**cached, "reused": True}
    try:
        result = _delete_chapter_locked(project, chapter,
                                        expected_version_id=expected_version_id,
                                        expected_content_sha256=expected_content_sha256,
                                        op_id=op_id)
    except Exception:
        _fail_soft(project, "chapter_delete", op_id)
        raise
    _finish_soft(project, "chapter_delete", op_id, result)
    return result


def _delete_chapter_locked(project, chapter: int, *, expected_version_id: str,
                           expected_content_sha256: str, op_id: str) -> Dict[str, Any]:
    with _locked(project, chapter, op_id=op_id or None, action="chapter_delete"):
        mapping = versions.chapter_map(project)
        if chapter not in mapping:
            raise ChapterError("chapter_missing", status=404)
        path = mapping[chapter]
        payload = path.read_bytes()
        current_sha = versions.raw_sha256(payload)
        text = _decode(payload)
        is_tail = chapter == max(mapping)
        if not is_tail and _count_words(text) > 0:
            raise ChapterError("only_tail_chapter_deletable", status=409)
        published = _published_state(project, chapter)
        if published["status"] in {"published", "staged"}:
            raise ChapterError("chapter_published_readonly", status=409)
        meta = versions.current_version(project, chapter) or {}
        if expected_content_sha256 and expected_content_sha256 != current_sha:
            raise ChapterError("concurrent_modification", status=409)
        if not expected_content_sha256:
            raise ChapterError("expected_version_required")
        if expected_version_id and expected_version_id not in {meta.get("version_id"), meta.get("sha256")}:
            raise ChapterError("concurrent_modification", status=409)
        active = _active_chapter_tasks(project, chapter)
        if active:
            raise ChapterError("chapter_has_active_tasks", status=409,
                               detail={"tasks": active,
                                       "message": "章节仍有待执行/执行中的任务，请先取消任务"})
        op = op_id or f"delete-{chapter}-{uuid.uuid4().hex[:8]}"
        archive_base = Path(project) / ".webnovel" / _TRASH / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-ch{chapter:04d}"
        archive = archive_base
        suffix = 1
        while archive.exists():
            suffix += 1
            archive = Path(str(archive_base) + f"-{suffix}")
        archive.mkdir(parents=True, exist_ok=False)
        receipt_snapshot = _chapter_receipt_snapshot(project, chapter)
        index_snapshot = _index_entry(project, chapter)
        manifest = {
            "chapter_id": chapter,
            "chapter_uid": wb.chapter_uid(project, chapter),
            "title": versions.parse_chapter_name(path.name)[1],
            "filename": path.name,
            "content_sha256": current_sha,
            "version_id": meta.get("version_id"),
            "payload_sha256": current_sha,
            "deleted_at": _now(),
            "index_entry": index_snapshot,
            "receipt": receipt_snapshot,
            "draft": wb.get_draft(project, chapter),
            "annotations": [],
            "op_id": op,
        }
        try:
            from integration import annotations
            manifest["annotations"] = annotations.export_chapter(project, chapter)
        except Exception:
            pass
        # The archived payload and the manifest hash are the same bytes read
        # above; never re-read after a concurrent save (A-P1-4).
        (archive / "original.md").write_bytes(payload)
        safety.atomic_json(archive / "manifest.json", manifest)
        try:
            versions._ensure(project)
            with safety.file_lock(versions._paths(project)["lock"]):
                if versions.file_sha256(path) != current_sha:
                    raise ChapterError("concurrent_modification", status=409)
                try:
                    os.replace(path, archive / path.name)
                except OSError as exc:
                    raise ChapterError("delete_failed") from exc
                try:
                    _drop_receipt(project, chapter)
                except Exception:
                    if (archive / path.name).is_file() and not path.exists():
                        os.replace(archive / path.name, path)
                    raise
                try:
                    _drop_index_entry(project, chapter)
                except Exception:
                    if isinstance(receipt_snapshot, dict) and receipt_snapshot:
                        try:
                            _write_receipts(project, {str(chapter): receipt_snapshot})
                        except Exception:
                            pass
                    if (archive / path.name).is_file() and not path.exists():
                        os.replace(archive / path.name, path)
                    if isinstance(index_snapshot, dict) and index_snapshot:
                        try:
                            index = versions.load_index(project)
                            index["chapters"][str(chapter)] = index_snapshot
                            versions._save_index(project, index)
                        except Exception:
                            pass
                    raise
        except Exception:
            if not (archive / path.name).is_file():
                shutil.rmtree(archive, ignore_errors=True)
            raise
        warnings: List[str] = []
        try:
            wb.delete_draft(project, chapter)
        except Exception as exc:
            warnings.append(f"draft:{type(exc).__name__}")
        try:
            from integration import annotations
            annotations.delete_chapter(project, chapter)
        except Exception as exc:
            warnings.append(f"annotations:{type(exc).__name__}")
        try:
            wb.drop_document(project, f"正文:{chapter}")
        except Exception:
            pass
        if isinstance(manifest.get("draft"), dict):
            _drop_draft_doc(project, chapter, manifest["draft"].get("draft_id"))
        return {"status": "deleted", "chapter_id": chapter, "trash_entry": archive.name,
                "archived_to": str(archive), "warnings": warnings}


def _trash_entries(project) -> List[Dict[str, Any]]:
    folder = Path(project) / ".webnovel" / _TRASH
    entries = []
    for path in sorted(folder.glob("*/manifest.json")) if folder.is_dir() else []:
        try:
            data = safety.read_json_strict(path)
        except Exception:
            continue
        if isinstance(data, dict):
            entries.append({"entry": path.parent.name, **data})
    return entries


def list_trash(project) -> Dict[str, Any]:
    return {"entries": _trash_entries(project)}


def _restore_trash_draft(project, chapter: int, uid: str,
                         draft: Any) -> bool:
    """Re-insert the draft archived with the deleted chapter (A-P2-11)."""
    if not isinstance(draft, dict) or not draft.get("draft_id"):
        return False
    if wb.get_draft(project, chapter):
        return False
    try:
        with wb.write_tx(project) as db:
            row = db.execute("SELECT draft_epoch FROM chapter_meta WHERE chapter_id=?",
                             (int(chapter),)).fetchone()
            epoch = max(int(draft.get("draft_epoch") or 0), int((row or [0])[0] or 0))
            db.execute("UPDATE chapter_meta SET draft_epoch=?, updated_at=? WHERE chapter_id=?",
                       (epoch, wb.now_iso(), int(chapter)))
            db.execute(
                "INSERT OR REPLACE INTO chapter_drafts(chapter_id, draft_id, chapter_uid, "
                "chapter_number, draft_epoch, draft_revision, base_version_id, base_content_sha256, "
                "title, content, cursor_json, dirty, client_session_id, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(chapter), str(draft["draft_id"]), uid or str(draft.get("chapter_uid") or ""),
                 int(chapter), epoch, int(draft.get("draft_revision") or 1),
                 draft.get("base_version_id"), draft.get("base_content_sha256"),
                 str(draft.get("title") or ""), str(draft.get("content") or ""),
                 json.dumps(draft.get("cursor") or {}, ensure_ascii=False),
                 1 if draft.get("dirty") else 0, str(draft.get("client_session_id") or ""),
                 wb.now_iso()),
            )
        return True
    except Exception:
        return False


def _restore_trash_annotations(project, chapter: int, uid: str,
                               rows: Any) -> int:
    """Re-insert annotations/hunks exported into the trash manifest (A-P2-11)."""
    if not isinstance(rows, list):
        return 0
    restored = 0
    try:
        with wb.write_tx(project) as db:
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                stamp = str(row.get("created_at") or _now())
                db.execute(
                    "INSERT OR REPLACE INTO annotations(id, chapter_id, chapter_uid, scope, "
                    "anchor_json, instruction, edit_policy, variants_requested, status, "
                    "annotation_revision, conflict_with_json, candidate_ids_json, thread_json, "
                    "group_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(row["id"]), int(chapter), uid or str(row.get("chapter_uid") or ""),
                     str(row.get("scope") or "chapter"),
                     json.dumps(row.get("anchor"), ensure_ascii=False),
                     str(row.get("instruction") or ""),
                     str(row.get("edit_policy") or "strict_selection"),
                     int(row.get("variants_requested") or 1),
                     str(row.get("status") or "open"),
                     int(row.get("annotation_revision") or 1),
                     json.dumps(row.get("conflict_with") or [], ensure_ascii=False),
                     json.dumps(row.get("candidate_ids") or [], ensure_ascii=False),
                     json.dumps(row.get("thread") or [], ensure_ascii=False),
                     row.get("group_id"), stamp, str(row.get("updated_at") or stamp)),
                )
                restored += 1
                for hunk in row.get("hunks") or []:
                    if not isinstance(hunk, dict) or not hunk.get("id"):
                        continue
                    db.execute(
                        "INSERT OR REPLACE INTO annotation_hunks(id, annotation_id, preview_id, "
                        "candidate_id, group_id, chapter_id, chapter_uid, status, before_text, "
                        "after_text, char_start, char_end, applied_draft_id, applied_draft_revision, "
                        "applied_range_json, applied_text_sha256, custom_text, created_at, updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (str(hunk["id"]), str(row["id"]), hunk.get("preview_id"),
                         hunk.get("candidate_id"), hunk.get("group_id"), int(chapter),
                         uid or str(hunk.get("chapter_uid") or ""),
                         str(hunk.get("status") or "pending"),
                         str(hunk.get("before_text") or ""), str(hunk.get("after_text") or ""),
                         hunk.get("char_start"), hunk.get("char_end"),
                         hunk.get("applied_draft_id"), hunk.get("applied_draft_revision"),
                         json.dumps(hunk.get("applied_range"), ensure_ascii=False),
                         hunk.get("applied_text_sha256"), hunk.get("custom_text"),
                         str(hunk.get("created_at") or stamp),
                         str(hunk.get("updated_at") or stamp)),
                    )
        return restored
    except Exception:
        return 0


def restore_trash(project, entry: str, *, op_id: str = "", force: bool = False) -> Dict[str, Any]:
    safe_entry = str(entry or "")
    if safe_entry in {".", ".."} or not re.fullmatch(r"[0-9A-Za-z._-]+", safe_entry):
        raise ChapterError("trash_entry_invalid")
    op_id = _validate_op_id(op_id)
    cached = _idempotent_soft(project, "trash_restore", op_id,
                              {"entry": safe_entry, "force": bool(force)})
    if cached is not None:
        return {**cached, "reused": True}
    try:
        result = _restore_trash_impl(project, safe_entry, op_id=op_id, force=bool(force))
    except Exception:
        _fail_soft(project, "trash_restore", op_id)
        raise
    _finish_soft(project, "trash_restore", op_id, result)
    return result


def _restore_trash_impl(project, safe_entry: str, *, op_id: str = "",
                        force: bool = False) -> Dict[str, Any]:
    archive = Path(project) / ".webnovel" / _TRASH / safe_entry
    manifest_path = archive / "manifest.json"
    if not manifest_path.is_file():
        raise ChapterError("trash_entry_missing", status=404)
    try:
        manifest = safety.read_json_strict(manifest_path)
    except Exception as exc:
        raise ChapterError("trash_entry_corrupt") from exc
    if not isinstance(manifest, dict):
        raise ChapterError("trash_entry_corrupt")
    payload_sha = str(manifest.get("payload_sha256") or manifest.get("content_sha256") or "")
    if not force:
        restored_at = manifest.get("restored_at")
        if restored_at:
            raise ChapterError("already_restored", status=409, detail={
                "entry": safe_entry, "restored_at": restored_at,
                "chapter_id": manifest.get("restored_chapter_id"),
                "message": "该回收站条目已还原；如需再复制一份，请显式 force",
            })
        try:
            started_chapter = int(manifest.get("restore_target_chapter") or 0)
        except (TypeError, ValueError):
            started_chapter = 0
        if manifest.get("restore_started_at") and started_chapter > 0 and payload_sha:
            started_path = versions.chapter_path(project, started_chapter)
            entry_state = (versions.load_index(project)["chapters"].get(str(started_chapter)) or {})
            if (versions.file_sha256(started_path) == payload_sha
                    and entry_state.get("current") == payload_sha):
                # The previous attempt landed body+index but died before the
                # manifest write; finish the bookkeeping instead of creating a
                # second copy (A-P2-05).
                manifest.update({"restored_at": _now(),
                                 "restored_chapter_id": started_chapter,
                                 "restored_renumbered": bool(
                                     started_chapter != int(manifest.get("chapter_id") or 0))})
                manifest.pop("restore_started_at", None)
                manifest.pop("restore_target_chapter", None)
                try:
                    safety.atomic_json(manifest_path, manifest)
                except Exception:
                    pass
                raise ChapterError("already_restored", status=409, detail={
                    "entry": safe_entry, "chapter_id": started_chapter,
                    "restored_at": manifest["restored_at"], "recovered": True,
                })
    mapping = versions.chapter_map(project)
    chapter = int(manifest.get("chapter_id") or 0)
    if chapter <= 0:
        raise ChapterError("trash_entry_corrupt")
    renumbered = False
    if chapter in mapping:
        chapter = max(mapping) + 1
        renumbered = True
    filename = str(manifest.get("filename") or "original.md")
    source = (archive / filename)
    try:
        source_resolved = source.resolve()
        archive_resolved = archive.resolve()
    except OSError as exc:
        raise ChapterError("trash_entry_corrupt") from exc
    if source_resolved.parent != archive_resolved:
        raise ChapterError("trash_entry_corrupt")
    if not source_resolved.is_file():
        fallback = archive / "original.md"
        if fallback.is_file() and fallback.resolve().parent == archive_resolved:
            source = fallback
        else:
            raise ChapterError("trash_payload_missing", status=404)
    data = source.read_bytes()
    expected_sha = str(manifest.get("payload_sha256") or manifest.get("content_sha256") or "")
    if expected_sha and hashlib.sha256(data).hexdigest() != expected_sha:
        raise ChapterError("trash_payload_corrupt")
    title = _validate_title_for_chapter(chapter, str(manifest.get("title") or ""))
    uid = "" if renumbered else str(manifest.get("chapter_uid") or "")
    if renumbered:
        uid = wb.chapter_uid(project, chapter)
    manifest["restore_started_at"] = _now()
    manifest["restore_target_chapter"] = chapter
    try:
        safety.atomic_json(manifest_path, manifest)
    except (OSError, RuntimeError) as exc:
        raise ChapterError("trash_manifest_write_failed") from exc
    result = versions.commit_raw_bytes(project, chapter, data, title=title,
                                       op_id=op_id or f"restore-trash-{uuid.uuid4().hex[:8]}",
                                       source="trash-restored", allow_new=True,
                                       note=f"从回收站还原 {safe_entry}")
    if uid:
        with wb.write_tx(project) as db:
            db.execute("UPDATE chapter_meta SET chapter_uid=?, updated_at=? WHERE chapter_id=?",
                       (uid, wb.now_iso(), chapter))
    entry_data = manifest.get("index_entry") or {}
    concurrent_restore = False
    if isinstance(entry_data, dict) and entry_data.get("versions"):
        with safety.file_lock(versions._paths(project)["lock"]):
            index = versions.load_index(project)
            target = versions._chapter_entry(index, chapter)
            # Do not overwrite a version committed by another window between
            # commit_raw_bytes and this index update.  The body sha and the
            # index current must both still be this restore's result (A P1-05).
            current_ok = (target.get("current") == result.get("content_sha256")
                          and versions.file_sha256(versions.chapter_path(project, chapter))
                          == result.get("content_sha256"))
            if not current_ok:
                concurrent_restore = True
            else:
                existing = {v.get("sha256") for v in target.get("versions", [])}
                target["versions"] = [v for v in entry_data["versions"]
                                      if v.get("sha256") not in existing] + target.get("versions", [])
                target["current"] = result.get("content_sha256")
                target["current_version_id"] = result.get("version_id")
            versions._save_index(project, index)
    receipt = manifest.get("receipt") or {}
    if isinstance(receipt, dict) and receipt:
        receipt = dict(receipt)
        receipt["destination"] = str(versions.chapter_path(project, chapter) or "")
        def merge_receipt(latest):
            key = str(chapter)
            existing = latest.get(key)
            existing = existing if isinstance(existing, dict) else {}
            merged = dict(receipt)
            # Preserve publication/author facts written while the restore was
            # copying; only the archived review/destination fields are ours.
            for field in ("published_sha256", "published_at", "publish",
                          "staged_at", "stage", "author_confirm"):
                if field in existing:
                    merged[field] = existing[field]
            latest[key] = merged
        _update_receipts(project, merge_receipt)
    try:
        wb.index_document(project, doc_key=f"正文:{chapter}", kind="chapter", chapter_id=chapter,
                          title=title, content=_decode(data))
    except Exception:
        pass
    restored_uid = uid or wb.chapter_uid(project, chapter)
    annotations_restored = _restore_trash_annotations(project, chapter, restored_uid,
                                                      manifest.get("annotations"))
    draft_restored = _restore_trash_draft(project, chapter, restored_uid,
                                          manifest.get("draft"))
    manifest.update({"restored_at": _now(), "restored_chapter_id": chapter,
                     "restored_renumbered": bool(renumbered)})
    manifest.pop("restore_started_at", None)
    manifest.pop("restore_target_chapter", None)
    try:
        safety.atomic_json(manifest_path, manifest)
        manifest_updated = True
    except Exception:
        # Body/index already landed; the ``restore_started_at`` marker plus the
        # payload sha make a later retry report already_restored instead of
        # copying the chapter a second time.
        manifest_updated = False
    return {"status": "restored", "entry": safe_entry, "chapter_id": chapter,
            "chapter_uid": uid, "renumbered": renumbered,
            "concurrent_save": concurrent_restore,
            "title": title, "content_sha256": result.get("content_sha256"),
            "annotations_restored": annotations_restored,
            "draft_restored": draft_restored, "manifest_updated": manifest_updated}


def _require_tail_unpublished(project, chapter: int) -> Path:
    mapping = versions.chapter_map(project)
    if chapter not in mapping:
        raise ChapterError("chapter_missing", status=404)
    if chapter != max(mapping):
        raise ChapterError("only_tail_chapter_supported", status=409)
    if _published_state(project, chapter)["status"] in {"published", "staged"}:
        raise ChapterError("chapter_published_readonly", status=409)
    return mapping[chapter]


def _split_entry_is_ours(entry: Dict[str, Any], second_sha: str, op_b: str) -> bool:
    """True only when the index entry is still the version this split wrote."""
    if not isinstance(entry, dict) or not entry:
        return False
    if entry.get("current") != second_sha:
        return False
    versions_list = entry.get("versions") if isinstance(entry.get("versions"), list) else []
    if not versions_list:
        return False
    latest = versions_list[-1]
    # Only the newest version identifies the current writer.  A concurrent
    # title-only save can keep the same sha; matching any old op_b entry would
    # then delete that save's index/receipt (P1-03 same-sha residual).
    return (isinstance(latest, dict) and latest.get("op_id") == op_b
            and latest.get("sha256") == second_sha)


def _rollback_split(project, chapter: int, raw: bytes, first_sha: str, second_sha: str,
                    chapter_entry: Dict[str, Any], next_entry: Dict[str, Any],
                    op_a: str, op_b: str, base_title: str) -> Dict[str, Any]:
    """Undo only this split's effects; never overwrite a concurrent save.

    The second half is removed only while its on-disk bytes and index entry
    still carry this split's ``second_sha``/``op_b``.  A page that saved
    ``chapter+1`` after the first commit keeps its body, index entry and
    receipt; the caller reports ``split_rollback_skipped_concurrent`` instead
    of silently deleting another writer's version (A-P1-03).
    """
    path = versions.chapter_path(project, chapter)
    current_sha = versions.file_sha256(path)
    raw_sha = _raw_sha(raw)
    restore_body = current_sha in {raw_sha, first_sha}
    external = current_sha not in {raw_sha, first_sha, None}
    if restore_body and path is not None:
        try:
            versions._write_chapter_bytes(project, chapter, raw, base_title)
        except OSError:
            pass
    second_path = versions.chapter_path(project, chapter + 1)
    second_disk_sha = versions.file_sha256(second_path)
    concurrent = False
    with safety.file_lock(versions._paths(project)["lock"]):
        index = versions.load_index(project)
        current_next = index["chapters"].get(str(chapter + 1)) or {}
        ours = _split_entry_is_ours(current_next, second_sha, op_b)
        changed = False
        if restore_body:
            if isinstance(chapter_entry, dict) and chapter_entry:
                index["chapters"][str(chapter)] = chapter_entry
            else:
                index["chapters"].pop(str(chapter), None)
            changed = True
        if ours:
            if second_path is not None and second_disk_sha == second_sha:
                try:
                    second_path.unlink()
                except OSError:
                    pass
            if isinstance(next_entry, dict) and next_entry:
                index["chapters"][str(chapter + 1)] = next_entry
            else:
                index["chapters"].pop(str(chapter + 1), None)
            changed = True
        else:
            # Do not touch an entry/receipt we cannot prove we created.
            if current_next and current_next != next_entry:
                concurrent = True
            elif second_disk_sha not in {None, second_sha}:
                concurrent = True
            elif second_disk_sha == second_sha and not current_next and second_path is not None:
                # Index write failed after the body landed: remove our own
                # orphan half instead of leaving a duplicate chapter file.
                try:
                    second_path.unlink()
                except OSError:
                    pass
        if changed:
            versions._save_index(project, index)
    for op in (op_a, op_b):
        try:
            versions.discard_commit(project, op)
        except versions.VersionError:
            pass
    # Never drop the chapter+1 receipt here: split does not create receipts,
    # so any receipt belongs to a concurrent save (A-P1-03).
    return {"external_sha": current_sha if external else None, "concurrent": concurrent}


def split_chapter(project, chapter: int, *, offset: int, title: str = "",
                  expected_content_sha256: str = "", op_id: str = "") -> Dict[str, Any]:
    chapter = int(chapter)
    op_id = _validate_op_id(op_id)
    params = {"chapter": chapter, "offset": int(offset), "title": str(title or ""),
              "expected_content_sha256": str(expected_content_sha256 or "")}
    cached = _idempotent_soft(project, "chapter_split", op_id, params)
    if cached is not None:
        return {**cached, "reused": True}
    try:
        with _locked(project, chapter, op_id=op_id or None, action="chapter_split"):
            result = _split_chapter_locked(project, chapter, offset=offset, title=title,
                                           expected_content_sha256=expected_content_sha256,
                                           op_id=op_id)
    except Exception:
        _fail_soft(project, "chapter_split", op_id)
        raise
    _finish_soft(project, "chapter_split", op_id, result)
    return result


def _split_chapter_locked(project, chapter: int, *, offset: int, title: str,
                          expected_content_sha256: str, op_id: str) -> Dict[str, Any]:
    path = _require_tail_unpublished(project, chapter)
    raw = path.read_bytes()
    if expected_content_sha256 and expected_content_sha256 != _raw_sha(raw):
        raise ChapterError("concurrent_modification", status=409)
    text = _normalize_lf(_decode(raw))
    points = list(text)
    if not 0 < int(offset) < len(points):
        raise ChapterError("split_offset_invalid")
    first = "".join(points[:int(offset)])
    second = "".join(points[int(offset):])
    if not second.strip():
        raise ChapterError("split_empty_tail")
    if not first.endswith("\n"):
        first += "\n"
    base_title = versions.parse_chapter_name(path.name)[1]
    first_title = _validate_title_for_chapter(chapter, title or base_title)
    second_title = _validate_title_for_chapter(chapter + 1, f"{first_title}（续）")
    first_payload = first.encode("utf-8")
    second_payload = second.encode("utf-8")
    first_sha = _raw_sha(first_payload)
    second_sha = _raw_sha(second_payload)
    op_a = (op_id + "-a") if op_id else f"split-{chapter}-a"
    op_b = (op_id + "-b") if op_id else f"split-{chapter + 1}-b"
    chapter_entry = json.loads(json.dumps(_index_entry(project, chapter), ensure_ascii=False))
    next_entry = json.loads(json.dumps(_index_entry(project, chapter + 1), ensure_ascii=False))
    try:
        # 先落后半章，再截断前半章：即使两次提交之间进程死亡，原文仍完整存在于
        # 前一章，不会出现“后半章永久丢失”；重试可幂等补齐。
        created = versions.commit_raw_bytes(project, chapter + 1, second_payload,
                                            title=second_title, op_id=op_b,
                                            source="split", allow_new=True,
                                            expect_absent=not next_entry,
                                            note="尾章拆分（下）")
        versions.commit_raw_bytes(project, chapter, first_payload, title=first_title,
                                  op_id=op_a, source="split",
                                  expected_sha256=_raw_sha(raw), note="尾章拆分（上）")
    except Exception as exc:
        rollback = _rollback_split(project, chapter, raw, first_sha, second_sha,
                                   chapter_entry, next_entry, op_a, op_b, base_title)
        if rollback.get("external_sha") is not None:
            raise ChapterError("split_aborted_concurrent_modification", status=409,
                               detail={"current_content_sha256": rollback["external_sha"]}) from exc
        if rollback.get("concurrent"):
            raise ChapterError("split_rollback_skipped_concurrent", status=409,
                               detail={"new_chapter_id": chapter + 1,
                                       "message": "后半章在拆分期间被并发保存，已保留其正文与版本"}) from exc
        raise
    wb.chapter_uid(project, chapter + 1)
    return {"status": "split", "chapter_id": chapter, "new_chapter_id": chapter + 1,
            "first_version_id": versions.current_version(project, chapter).get("version_id"),
            "second_version_id": created.get("version_id")}


def _rollback_merge(project, previous: int, last: int, old_bytes: bytes, merge_sha: str,
                    previous_entry: Dict[str, Any], last_entry: Dict[str, Any],
                    merge_op: str, drop_op: str) -> None:
    path = versions.chapter_path(project, previous)
    current_sha = versions.file_sha256(path)
    restored = False
    if path is not None and current_sha == merge_sha:
        try:
            versions._write_chapter_bytes(project, previous, old_bytes,
                                          versions.parse_chapter_name(path.name)[1])
            restored = True
        except OSError:
            pass
    with safety.file_lock(versions._paths(project)["lock"]):
        index = versions.load_index(project)
        changed = False
        if restored:
            if isinstance(previous_entry, dict) and previous_entry:
                index["chapters"][str(previous)] = previous_entry
            else:
                index["chapters"].pop(str(previous), None)
            changed = True
        if isinstance(last_entry, dict) and last_entry:
            if index["chapters"].get(str(last)) != last_entry:
                index["chapters"][str(last)] = last_entry
                changed = True
        if changed:
            versions._save_index(project, index)
    for op in (merge_op, drop_op):
        try:
            versions.discard_commit(project, op)
        except versions.VersionError:
            pass


def merge_tail(project, *, op_id: str = "") -> Dict[str, Any]:
    op_id = _validate_op_id(op_id)
    cached = _idempotent_soft(project, "chapter_merge", op_id, {})
    if cached is not None:
        return {**cached, "reused": True}
    try:
        mapping = versions.chapter_map(project)
        if len(mapping) < 2:
            raise ChapterError("merge_needs_two_chapters", status=409)
        last, previous = max(mapping), max(mapping) - 1
        if previous not in mapping:
            raise ChapterError("merge_needs_adjacent_chapters", status=409)
        with _locked(project, previous, op_id=op_id or None, action="chapter_merge"):
            with _locked(project, last, op_id=op_id or None, action="chapter_merge"):
                result = _merge_tail_locked(project, previous, last, op_id)
    except Exception:
        _fail_soft(project, "chapter_merge", op_id)
        raise
    _finish_soft(project, "chapter_merge", op_id, result)
    return result


def _merge_tail_locked(project, previous: int, last: int, op_id: str) -> Dict[str, Any]:
    mapping = versions.chapter_map(project)
    if previous not in mapping or last not in mapping or max(mapping) != last:
        raise ChapterError("merge_needs_adjacent_chapters", status=409)
    for number in (last, previous):
        if _published_state(project, number)["status"] in {"published", "staged"}:
            raise ChapterError("chapter_published_readonly", status=409)
    first_text = _normalize_lf(_decode(mapping[previous].read_bytes())).rstrip()
    second_text = _normalize_lf(_decode(mapping[last].read_bytes())).lstrip("\n")
    merged = first_text + "\n\n" + second_text
    title = versions.parse_chapter_name(mapping[previous].name)[1]
    old_bytes = mapping[previous].read_bytes()
    merge_op = (op_id + "-merge") if op_id else f"merge-{previous}-{last}"
    drop_op = (op_id + "-drop") if op_id else f"merge-drop-{last}"
    previous_entry = json.loads(json.dumps(_index_entry(project, previous), ensure_ascii=False))
    last_entry = json.loads(json.dumps(_index_entry(project, last), ensure_ascii=False))
    try:
        result = versions.write_chapter(project, previous, merged, op_id=merge_op,
                                        expected_sha256=_raw_sha(old_bytes),
                                        title=title, source="merge", note="尾章合并")
        deleted = delete_chapter(project, last,
                                 expected_content_sha256=_raw_sha(mapping[last].read_bytes()),
                                 op_id=drop_op)
    except Exception:
        # 若前半章已是完整合并稿（典型：上次崩溃在合并写入之后、删除尾章之前），
        # 重试只需补删尾章，不能把已合并正文回滚掉。
        try:
            current_prev = versions.chapter_path(project, previous)
            current_last = versions.chapter_path(project, last)
            if (current_prev is not None and current_last is not None
                    and _normalize_lf(_decode(current_prev.read_bytes())) == merged):
                deleted = delete_chapter(
                    project, last,
                    expected_content_sha256=_raw_sha(current_last.read_bytes()),
                    op_id=drop_op)
                current = versions.current_version(project, previous) or {}
                return {"status": "merged", "chapter_id": previous, "dropped_chapter_id": last,
                        "version_id": current.get("version_id"),
                        "trash_entry": deleted.get("trash_entry")}
        except Exception:
            pass
        # 只回滚本操作改过的两章；绝不整份索引覆盖其他章的并发提交。
        _rollback_merge(project, previous, last, old_bytes, _raw_sha(merged.encode("utf-8")),
                        previous_entry, last_entry, merge_op, drop_op)
        raise
    return {"status": "merged", "chapter_id": previous, "dropped_chapter_id": last,
            "version_id": result.get("version_id"), "trash_entry": deleted.get("trash_entry")}


def import_preview(project, *, text: str, start_chapter: Optional[int] = None) -> Dict[str, Any]:
    if not isinstance(text, str):
        raise ChapterError("import_content_required")
    try:
        raw_bytes = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChapterError("invalid_content") from exc
    if len(raw_bytes) > MAX_IMPORT_BYTES:
        raise ChapterError("import_too_large", status=413)
    normalized = _normalize_lf(_strip_bom(text))
    matches = list(_CHAPTER_HEADING.finditer(normalized))
    chapters: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        heading = match.group(0).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = normalized[match.end():end].strip("\n")
        title = re.sub(r"^第\s*[0-9０-９零〇一二三四五六七八九十百千]+\s*[章节回]\s*", "", heading).strip(" ：:-")
        chapters.append({"index": index + 1, "heading": heading,
                         "title": title or heading, "content": body,
                         "words": _count_words(body)})
    mapping = versions.chapter_map(project)
    start = int(start_chapter or (max(mapping) + 1 if mapping else 1))
    return {"chapters": chapters, "count": len(chapters), "start_chapter": start,
            "total_words": sum(item["words"] for item in chapters)}


def import_chapters(project, *, text: str, start_chapter: Optional[int] = None,
                    preview: bool = True, op_id: str = "") -> Dict[str, Any]:
    op_id = _validate_op_id(op_id)
    params = {"text": text, "start_chapter": start_chapter, "preview": bool(preview)}
    if not preview:
        cached = _idempotent_soft(project, "chapter_import", op_id, params)
        if cached is not None:
            return {**cached, "reused": True}
    plan = import_preview(project, text=text, start_chapter=start_chapter)
    if preview:
        return {"status": "preview", **plan}
    existing = versions.chapter_map(project)
    targets = [plan["start_chapter"] + offset for offset in range(plan["count"])]
    if any(chapter in existing for chapter in targets):
        _fail_soft(project, "chapter_import", op_id)
        raise ChapterError("chapter_exists", status=409)
    created = []
    try:
        for offset, item in enumerate(plan["chapters"]):
            chapter = plan["start_chapter"] + offset
            title = _validate_title_for_chapter(chapter, item["title"])
            content = _validate_content(item["content"])
            result = versions.commit_raw_bytes(project, chapter, content.encode("utf-8"), title=title,
                                               op_id=(op_id + f"-{chapter}") if op_id else f"import-{chapter}-{uuid.uuid4().hex[:8]}",
                                               source="imported", allow_new=True, note="导入旧稿")
            created.append({"chapter_id": chapter, "title": title, "version_id": result.get("version_id"),
                            "commit_op": (op_id + f"-{chapter}") if op_id else result.get("op_id"),
                            "words": item["words"]})
    except Exception:
        _fail_soft(project, "chapter_import", op_id)
        # 整批导入失败时不留下前半批孤儿章
        for row in created:
            number = row["chapter_id"]
            path = versions.chapter_path(project, number)
            if path:
                try:
                    path.unlink()
                except OSError:
                    pass
            _drop_index_entry(project, number)
            _drop_receipt(project, number)
            commit_op = str(row.get("commit_op") or "")
            if commit_op:
                try:
                    versions._commit_path(project, commit_op).unlink(missing_ok=True)
                except OSError:
                    pass
        raise
    response = {"status": "imported", "count": len(created), "chapters": created}
    _finish_soft(project, "chapter_import", op_id, response)
    return response


def author_confirm(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    chapter = int(chapter)
    expected_version = str(data.get("expected_version_id") or "").strip()
    expected_sha = str(data.get("expected_content_sha256") or "").strip().lower()
    if not expected_version or not expected_sha:
        raise ChapterError("expected_version_required")
    op_id = _validate_op_id(data.get("op_id"))
    params = {"chapter": chapter, "expected_version_id": expected_version,
              "expected_content_sha256": expected_sha, "note": data.get("note")}
    cached = _idempotent(project, "author_confirm", op_id, params) if op_id else None
    if cached is not None:
        return {**cached, "reused": True}
    path = versions.chapter_path(project, chapter)
    if path is None:
        raise ChapterError("chapter_missing", status=404)
    meta = versions.current_version(project, chapter)
    disk_sha = versions.file_sha256(path)
    if not meta or disk_sha != expected_sha or expected_version not in {meta.get("version_id"), meta.get("sha256")}:
        raise ChapterError("concurrent_modification", status=409,
                           detail={"current_version_id": (meta or {}).get("version_id"),
                                   "current_content_sha256": disk_sha})
    raw = path.read_bytes()
    text = _decode(raw)
    title = versions.parse_chapter_name(path.name)[1]
    receipt = _read_receipts(project).get(str(chapter)) or {}
    review = dict(receipt.get("review") or {})
    review.update({
        "success": True,
        "review_decision": "author_confirmed",
        "needs_revision": False,
        "author_confirmed": True,
        "confirmed_by": "author",
        "confirmed_at": _now(),
        "confirmed_version_id": meta["version_id"],
        "confirmed_content_sha256": meta.get("content_sha256") or meta.get("sha256"),
        "confirmed_title": title,
        "confirmed_title_digest": meta.get("title_digest") or versions.title_digest(title),
        "confirmed_version_fingerprint": meta.get("version_fingerprint"),
        "body_sha256": safety.body_digest(text),
        "note": str(data.get("note") or "")[:400],
    })
    saved = {
        **receipt,
        "chapter_uid": wb.chapter_uid(project, chapter),
        "destination": str(path.resolve()),
        "sha256": meta.get("content_sha256") or meta.get("sha256"),
        "version_id": meta["version_id"],
        "creative_contract_hash": safety.creative_contract_hash_for_chapter(project, chapter),
        "reviewed_at": receipt.get("reviewed_at") or _now(),
        "review": review,
    }
    _write_receipts(project, {str(chapter): saved})
    memory = None
    if data.get("commit_pending_memory"):
        try:
            from integration import memory_library
            memory = memory_library.commit_candidates(project, chapter,
                                                      body_sha256=safety.body_digest(text))
        except Exception as exc:
            memory = {"status": "skipped", "error": str(exc)[:200]}
    result = {"status": "confirmed", "chapter_id": chapter, "chapter_uid": saved["chapter_uid"],
              "version_id": meta["version_id"], "content_sha256": saved["sha256"],
              "title": title, "review": review, "memory": memory}
    if op_id:
        _finish(project, "author_confirm", op_id, result)
    return result


def revoke_author_confirm(project, chapter: int, *, op_id: str = "") -> Dict[str, Any]:
    chapter = int(chapter)
    receipts = _read_receipts(project)
    entry = receipts.get(str(chapter))
    if not isinstance(entry, dict):
        return {"status": "revoked", "chapter_id": chapter, "changed": False}
    review = dict(entry.get("review") or {})
    changed = False
    if review.get("review_decision") == "author_confirmed" or review.get("author_confirmed"):
        review.update({"author_confirmed": False, "review_decision": "author_revoked",
                       "needs_revision": False, "success": False})
        for key in ("confirmed_version_id", "confirmed_content_sha256", "confirmed_title",
                    "confirmed_title_digest", "confirmed_version_fingerprint", "confirmed_at"):
            review.pop(key, None)
        entry["review"] = review
        _write_receipts(project, {str(chapter): entry})
        changed = True
    return {"status": "revoked", "chapter_id": chapter, "changed": changed}


def quick_check(project, chapter: int, *, content: Optional[str] = None) -> Dict[str, Any]:
    started = time.perf_counter()
    if content is not None:
        try:
            text = _normalize_lf(str(content))[:MAX_CONTENT_BYTES]
        except Exception as exc:
            raise ChapterError("invalid_content") from exc
    else:
        text = _decode(versions.chapter_path(project, chapter).read_bytes())[:MAX_CONTENT_BYTES]
    issues: List[Dict[str, Any]] = []
    try:
        from integration import style_rules
        report = style_rules.check(text, scope="chapter", record=False, project=project)
        for item in report.get("findings", [])[:80]:
            issues.append({"type": "style_rule", "severity": item.get("severity") or "warning",
                           "message": item.get("message") or item.get("rule") or "风格规则命中",
                           "quote": item.get("quote", ""), "start": item.get("start")})
    except Exception:
        pass
    issues.extend(_local_language_issues(text))
    issues.sort(key=lambda item: (item.get("start") is None, item.get("start") or 0))
    stats = {}
    try:
        from integration import style_stats
        stats = style_stats.statistics(text)
    except Exception:
        stats = {}
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    return {"chapter_id": int(chapter), "elapsed_ms": elapsed, "issues": issues,
            "issue_count": len(issues), "stats": stats, "model_calls": 0}


def _local_language_issues(text: str) -> List[Dict[str, Any]]:
    issues = []
    for match in re.finditer(r"([，。！？、；：,.!?;:])\1{1,}", text):
        issues.append({"type": "punctuation_repeat", "severity": "warning",
                       "message": "连续重复标点", "quote": match.group(0), "start": match.start()})
    for match in re.finditer(r"[“”「」『』]", text):
        pass
    opens = text.count("“") + text.count("「") + text.count("『")
    closes = text.count("”") + text.count("」") + text.count("』")
    if opens != closes:
        issues.append({"type": "quote_unbalanced", "severity": "warning",
                       "message": f"成对引号未闭合（开 {opens} / 闭 {closes}）", "quote": "", "start": None})
    for word in ("突然", "不禁", "冷笑", "微微一笑", "倒吸一口凉气"):
        count = text.count(word)
        if count >= 4:
            issues.append({"type": "verbal_tics", "severity": "info",
                           "message": f"高频口癖「{word}」出现 {count} 次", "quote": word,
                           "start": text.find(word)})
    # 第一人称与第三人称在非对白段落的异常切换（粗筛，不阻断保存）
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    first = sum(1 for p in paragraphs if re.search(r"(?<![“”])我(?![^“”]*[”])", p))
    third = sum(1 for p in paragraphs if re.search(r"(他|她)(?![^“”]*[”])", p))
    if first >= 3 and third >= 3:
        issues.append({"type": "person_drift", "severity": "info",
                       "message": "第一人称与第三人称叙述可能混用，请检查视角", "quote": "",
                       "start": None})
    return issues


def sync_memory_preview(project, chapter: int, *, expected_version_id: str = "") -> Dict[str, Any]:
    """Deterministic, non-blocking change triage before any model extraction.

    The actual extraction stays in the memory pipeline; this reports whether a
    one-character core fact change warrants the lightweight badge and binds the
    preview to the exact version that produced it.
    """
    chapter = int(chapter)
    path = versions.chapter_path(project, chapter)
    if path is None:
        raise ChapterError("chapter_missing", status=404)
    meta = versions.current_version(project, chapter)
    if expected_version_id and meta and expected_version_id not in {meta.get("version_id"), meta.get("sha256")}:
        raise ChapterError("concurrent_modification", status=409)
    current_text = _decode(path.read_bytes())
    previous_text = ""
    items = versions.list_versions(project, chapter)
    if len(items) >= 2:
        previous = items[-2]
        try:
            previous_text = versions.read_version(project, chapter, previous.get("version_id") or previous.get("sha256"))["text"]
        except Exception:
            previous_text = ""
    triggers: List[Dict[str, Any]] = []
    if previous_text:
        import difflib
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, previous_text, current_text).get_opcodes():
            if tag == "equal":
                continue
            removed, added = previous_text[i1:i2], current_text[j1:j2]
            if len(removed) + len(added) <= 8:
                fragment = f"{removed}→{added}"
                if re.search(r"(死|活|未|没|不|三|十|百|千|\d)", fragment):
                    triggers.append({"kind": "core_fact_char_change", "before": removed,
                                     "after": added, "position": j1})
    return {"status": "preview", "chapter_id": chapter, "chapter_uid": wb.chapter_uid(project, chapter),
            "version_id": (meta or {}).get("version_id"),
            "content_sha256": versions.file_sha256(path),
            "triggers": triggers[:20], "requires_extraction": True,
            "needs_badge": bool(triggers), "model_calls": 0}


def index_project(project) -> Dict[str, Any]:
    """Index 正文/大纲/设定 into the local FTS5 shadow table (0 model calls)."""
    root = Path(project)
    count = 0
    for kind, folder in (("chapter", "正文"), ("outline", "大纲"), ("lore", "设定")):
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.md")):
            if path.is_symlink():
                continue
            try:
                text = _decode(path.read_bytes())
            except OSError:
                continue
            chapter = None
            if kind == "chapter":
                parsed = versions.parse_chapter_name(path.name)
                chapter = parsed[0] if parsed else None
            doc_key = f"正文:{chapter}" if kind == "chapter" and chapter is not None else f"{folder}:{path.name}"
            wb.index_document(project, doc_key=doc_key, kind=kind,
                              chapter_id=chapter, title=path.stem, content=text)
            count += 1
    return {"status": "indexed", "documents": count}


def search_project(project, query: str, *, limit: int = 20) -> Dict[str, Any]:
    if not str(query or "").strip():
        return {"query": query, "results": [], "count": 0}
    index_project(project)
    results = wb.search(project, str(query), limit=limit)
    return {"query": query, "results": results, "count": len(results)}
