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
_OP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
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


def _write_receipts(project, receipts: Dict[str, Any]) -> None:
    path = _receipts_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / "receipts.lock"
    with safety.file_lock(lock):
        # 重新读最新，绝不拿旧整表覆盖其他章的并行回执。
        latest = _read_receipts(project)
        latest.update(receipts)
        safety.atomic_json(path, latest)


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
    disk = versions.file_sha256(versions.chapter_path(project, chapter))
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
        payload["draft"] = {
            "exists": bool(draft),
            "draft_id": (draft or {}).get("draft_id"),
            "draft_epoch": epoch,
            "draft_revision": (draft or {}).get("draft_revision"),
            "base_version_id": (draft or {}).get("base_version_id"),
            "base_sha256": (draft or {}).get("base_content_sha256"),
            "base_content_sha256": (draft or {}).get("base_content_sha256"),
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


def _finish(project, action: str, op_id: str, response: Dict[str, Any]) -> None:
    wb.idempotency_complete(project, actor="author", project_id=str(Path(project).resolve()),
                            action=action, op_id=op_id, response=response)


def save_version(project, chapter: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """提交正式版本；所有磁盘写入持有单章锁并带乐观并发校验。"""
    chapter = int(chapter)
    if chapter <= 0:
        raise ChapterError("chapter_invalid")
    title = _validate_title(data.get("title", ""))
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
        unchanged = bool(path and _body_digest(current_text) == _body_digest(content)
                         and current_title == title)

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
            if current_sha is not None and path and title != current_title:
                result["renamed"] = _rename_chapter_file(project, chapter, path, title)
            result["status"] = "saved"
            result["unchanged"] = False

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


def _rename_chapter_file(project, chapter: int, source: Path, title: str) -> bool:
    """Rename ``第N章-旧标题.md`` to the new title with Windows retry protection."""
    target = source.with_name(f"第{int(chapter)}章" + (f"-{title}" if title else "") + ".md")
    if target == source:
        return False
    if target.exists() and target.resolve() != source.resolve():
        raise ChapterError("chapter_filename_conflict", status=409)
    try:
        from integration import transaction_journal as journal
        journal.rename_with_retry(source, target)
    except Exception as exc:
        if exc.__class__.__name__ == "FileInUse":
            raise ChapterError("file_in_use_retry", status=409) from None
        raise
    receipts = _read_receipts(project)
    entry = receipts.get(str(int(chapter)))
    if isinstance(entry, dict):
        entry["destination"] = str(target.resolve())
        _write_receipts(project, {str(int(chapter)): entry})
    return True


def new_chapter(project, data: Dict[str, Any]) -> Dict[str, Any]:
    title = _validate_title(data.get("title") or "未命名章节")
    content = _validate_content(data.get("content") or "")
    mapping = versions.chapter_map(project)
    chapter = int(data.get("chapter") or (max(mapping) + 1 if mapping else 1))
    if str(chapter) in {str(x) for x in mapping}:
        raise ChapterError("chapter_exists", status=409)
    uid = wb.chapter_uid(project, chapter)
    result = versions.commit_raw_bytes(project, chapter, content.encode("utf-8"), title=title,
                                       op_id=_validate_op_id(data.get("op_id") or uuid.uuid4().hex),
                                       source="author_new", note="新建空白章节", allow_new=True)
    try:
        wb.index_document(project, doc_key=f"正文:{chapter}", kind="chapter", chapter_id=chapter,
                          title=title, content=content)
    except Exception:
        pass
    return {"status": "created", "chapter_id": chapter, "chapter_uid": uid, "title": title,
            "version_id": result.get("version_id"), "sha256": result.get("content_sha256")}


def _chapter_receipt_snapshot(project, chapter: int) -> Dict[str, Any]:
    return _read_receipts(project).get(str(int(chapter))) or {}


def _index_entry(project, chapter: int) -> Dict[str, Any]:
    return (versions.load_index(project)["chapters"].get(str(int(chapter))) or {})


def _drop_index_entry(project, chapter: int) -> None:
    index = versions.load_index(project)
    if str(int(chapter)) in index["chapters"]:
        index["chapters"].pop(str(int(chapter)), None)
        versions._save_index(project, index)


def _drop_receipt(project, chapter: int) -> None:
    receipts = _read_receipts(project)
    if str(int(chapter)) in receipts:
        receipts.pop(str(int(chapter)), None)
        safety.atomic_json(_receipts_path(project), receipts)


def delete_chapter(project, chapter: int, *, expected_version_id: str = "",
                   expected_content_sha256: str = "", op_id: str = "") -> Dict[str, Any]:
    """受限删除：仅未发布、未入队且为尾章或空章的章节，归档而非物理删除。"""
    chapter = int(chapter)
    mapping = versions.chapter_map(project)
    if chapter not in mapping:
        raise ChapterError("chapter_missing", status=404)
    path = mapping[chapter]
    text = _decode(path.read_bytes())
    is_tail = chapter == max(mapping)
    if not is_tail and _count_words(text) > 0:
        raise ChapterError("only_tail_chapter_deletable", status=409)
    published = _published_state(project, chapter)
    if published["status"] in {"published", "staged"}:
        raise ChapterError("chapter_published_readonly", status=409)
    current_sha = versions.file_sha256(path)
    meta = versions.current_version(project, chapter) or {}
    if expected_content_sha256 and expected_content_sha256 != current_sha:
        raise ChapterError("concurrent_modification", status=409)
    if not expected_content_sha256:
        raise ChapterError("expected_version_required")
    if expected_version_id and expected_version_id not in {meta.get("version_id"), meta.get("sha256")}:
        raise ChapterError("concurrent_modification", status=409)
    op = op_id or f"delete-{chapter}-{uuid.uuid4().hex[:8]}"
    archive_base = Path(project) / ".webnovel" / _TRASH / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-ch{chapter:04d}"
    archive = archive_base
    suffix = 1
    while archive.exists():
        suffix += 1
        archive = Path(str(archive_base) + f"-{suffix}")
    archive.mkdir(parents=True, exist_ok=False)
    manifest = {
        "chapter_id": chapter,
        "chapter_uid": wb.chapter_uid(project, chapter),
        "title": versions.parse_chapter_name(path.name)[1],
        "filename": path.name,
        "content_sha256": current_sha,
        "version_id": meta.get("version_id"),
        "payload_sha256": current_sha,
        "deleted_at": _now(),
        "index_entry": _index_entry(project, chapter),
        "receipt": _chapter_receipt_snapshot(project, chapter),
        "draft": wb.get_draft(project, chapter),
        "annotations": [],
        "op_id": op,
    }
    try:
        from integration import annotations
        manifest["annotations"] = annotations.export_chapter(project, chapter)
    except Exception:
        pass
    (archive / "original.md").write_bytes(path.read_bytes())
    safety.atomic_json(archive / "manifest.json", manifest)
    try:
        os.replace(path, archive / path.name)
    except OSError as exc:
        raise ChapterError("delete_failed") from exc
    try:
        wb.delete_draft(project, chapter)
    except Exception:
        pass
    try:
        from integration import annotations
        annotations.delete_chapter(project, chapter)
    except Exception:
        pass
    _drop_receipt(project, chapter)
    _drop_index_entry(project, chapter)
    try:
        wb.drop_document(project, f"正文:{chapter}")
    except Exception:
        pass
    if isinstance(manifest.get("draft"), dict):
        _drop_draft_doc(project, chapter, manifest["draft"].get("draft_id"))
    return {"status": "deleted", "chapter_id": chapter, "trash_entry": archive.name,
            "archived_to": str(archive)}


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


def restore_trash(project, entry: str, *, op_id: str = "") -> Dict[str, Any]:
    safe_entry = str(entry or "")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", safe_entry):
        raise ChapterError("trash_entry_invalid")
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
    title = str(manifest.get("title") or "")
    uid = str(manifest.get("chapter_uid") or "")
    result = versions.commit_raw_bytes(project, chapter, data, title=title,
                                       op_id=op_id or f"restore-trash-{uuid.uuid4().hex[:8]}",
                                       source="trash-restored", allow_new=True,
                                       note=f"从回收站还原 {safe_entry}")
    if uid:
        with wb.write_tx(project) as db:
            db.execute("UPDATE chapter_meta SET chapter_uid=?, updated_at=? WHERE chapter_id=?",
                       (uid, wb.now_iso(), chapter))
    entry_data = manifest.get("index_entry") or {}
    if isinstance(entry_data, dict) and entry_data.get("versions"):
        index = versions.load_index(project)
        target = versions._chapter_entry(index, chapter)
        existing = {v.get("sha256") for v in target.get("versions", [])}
        target["versions"] = [v for v in entry_data["versions"] if v.get("sha256") not in existing] + target.get("versions", [])
        target["current"] = result.get("content_sha256")
        target["current_version_id"] = result.get("version_id")
        versions._save_index(project, index)
    receipt = manifest.get("receipt") or {}
    if isinstance(receipt, dict) and receipt:
        receipt = dict(receipt)
        receipt["destination"] = str(versions.chapter_path(project, chapter) or "")
        _write_receipts(project, {str(chapter): receipt})
    try:
        wb.index_document(project, doc_key=f"正文:{chapter}", kind="chapter", chapter_id=chapter,
                          title=title, content=_decode(data))
    except Exception:
        pass
    return {"status": "restored", "entry": safe_entry, "chapter_id": chapter,
            "chapter_uid": uid, "renumbered": renumbered,
            "title": title, "content_sha256": result.get("content_sha256")}


def _require_tail_unpublished(project, chapter: int) -> Path:
    mapping = versions.chapter_map(project)
    if chapter not in mapping:
        raise ChapterError("chapter_missing", status=404)
    if chapter != max(mapping):
        raise ChapterError("only_tail_chapter_supported", status=409)
    if _published_state(project, chapter)["status"] in {"published", "staged"}:
        raise ChapterError("chapter_published_readonly", status=409)
    return mapping[chapter]


def split_chapter(project, chapter: int, *, offset: int, title: str = "",
                  expected_content_sha256: str = "", op_id: str = "") -> Dict[str, Any]:
    chapter = int(chapter)
    op_id = _validate_op_id(op_id)
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
    first_title = _validate_title(title or base_title)
    second_title = _validate_title(f"{first_title}（续）")
    backup_index = json.dumps(versions.load_index(project), ensure_ascii=False)
    old_bytes = raw
    new_path = versions._new_chapter_path(project, chapter + 1, second_title)
    try:
        versions.commit_raw_bytes(project, chapter, first.encode("utf-8"), title=first_title,
                                  op_id=(op_id + "-a") if op_id else f"split-{chapter}-a",
                                  source="split", expected_sha256=_raw_sha(raw),
                                  note="尾章拆分（上）")
        created = versions.commit_raw_bytes(project, chapter + 1, second.encode("utf-8"),
                                            title=second_title,
                                            op_id=(op_id + "-b") if op_id else f"split-{chapter + 1}-b",
                                            source="split", allow_new=True,
                                            note="尾章拆分（下）")
    except Exception:
        path.write_bytes(old_bytes)
        from fanqie_auto_publish.publication_safety import atomic_json as _atomic
        # 恢复拆分前的索引快照，并清掉可能已创建的下半章文件。
        _atomic(versions._paths(project)["index"], json.loads(backup_index))
        for candidate in (new_path, versions.chapter_path(project, chapter + 1)):
            if candidate and Path(candidate).exists():
                try:
                    Path(candidate).unlink()
                except OSError:
                    pass
        _drop_index_entry(project, chapter + 1)
        _drop_receipt(project, chapter + 1)
        raise
    wb.chapter_uid(project, chapter + 1)
    return {"status": "split", "chapter_id": chapter, "new_chapter_id": chapter + 1,
            "first_version_id": versions.current_version(project, chapter).get("version_id"),
            "second_version_id": created.get("version_id")}


def merge_tail(project, *, op_id: str = "") -> Dict[str, Any]:
    op_id = _validate_op_id(op_id)
    mapping = versions.chapter_map(project)
    if len(mapping) < 2:
        raise ChapterError("merge_needs_two_chapters", status=409)
    last, previous = max(mapping), max(mapping) - 1
    if previous not in mapping:
        raise ChapterError("merge_needs_adjacent_chapters", status=409)
    for number in (last, previous):
        if _published_state(project, number)["status"] in {"published", "staged"}:
            raise ChapterError("chapter_published_readonly", status=409)
    first_text = _normalize_lf(_decode(mapping[previous].read_bytes())).rstrip()
    second_text = _normalize_lf(_decode(mapping[last].read_bytes())).lstrip("\n")
    merged = first_text + "\n\n" + second_text
    title = versions.parse_chapter_name(mapping[previous].name)[1]
    result = versions.write_chapter(project, previous, merged,
                                    op_id=(op_id + "-merge") if op_id else f"merge-{previous}-{last}",
                                    expected_sha256=_raw_sha(mapping[previous].read_bytes()),
                                    title=title, source="merge", note="尾章合并")
    deleted = delete_chapter(project, last,
                             expected_content_sha256=_raw_sha(mapping[last].read_bytes()),
                             op_id=(op_id + "-drop") if op_id else f"merge-drop-{last}")
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
    plan = import_preview(project, text=text, start_chapter=start_chapter)
    if preview:
        return {"status": "preview", **plan}
    existing = versions.chapter_map(project)
    targets = [plan["start_chapter"] + offset for offset in range(plan["count"])]
    if any(chapter in existing for chapter in targets):
        raise ChapterError("chapter_exists", status=409)
    created = []
    try:
        for offset, item in enumerate(plan["chapters"]):
            chapter = plan["start_chapter"] + offset
            title = _validate_title(item["title"])
            content = _validate_content(item["content"])
            result = versions.commit_raw_bytes(project, chapter, content.encode("utf-8"), title=title,
                                               op_id=(op_id + f"-{chapter}") if op_id else f"import-{chapter}-{uuid.uuid4().hex[:8]}",
                                               source="imported", allow_new=True, note="导入旧稿")
            created.append({"chapter_id": chapter, "title": title, "version_id": result.get("version_id"),
                            "words": item["words"]})
    except Exception:
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
        raise
    return {"status": "imported", "count": len(created), "chapters": created}


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
