"""v0.8–v0.9.5 workbench API surface.

Registered from :mod:`manager.app` through :func:`install`.  Every mutating
route here must also appear in ``index.js`` ``WRITE_ROUTES``; read-only helpers
stay under ``/api/*`` so the host proxy's read gate covers them.

The functions below intentionally return plain dictionaries: the manager's
existing JSON error envelope and body limit middleware already handle the HTTP
contract, while the modules own validation and stable machine codes.
"""
from __future__ import annotations

import functools
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from integration import chapter_editor, outline_editor
from integration import chapter_versions as versions
from integration import revision_plan, workbench_db
from integration import transaction_journal


def install(app: FastAPI, *, project: Callable[[str], Dict[str, Any]],
            ops, load_ai: Callable[[], Dict[str, Any]], project_title: Callable[[str], str],
            data_dir: Path) -> None:
    def _book(identity: str) -> Path:
        item = project(identity)
        return Path(item["path"])

    def guard(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (chapter_editor.ChapterError, outline_editor.OutlineError) as exc:
                payload = {"code": exc.code, "message": exc.code, **exc.detail}
                return JSONResponse(status_code=exc.status, content=payload)
            except versions.VersionConflict as exc:
                return JSONResponse(status_code=409,
                                    content={"code": str(exc) or "version_conflict",
                                             "message": "版本冲突，请刷新后重试"})
            except versions.VersionNotFound as exc:
                return JSONResponse(status_code=404,
                                    content={"code": str(exc) or "version_not_found",
                                             "message": "版本或章节不存在"})
            except transaction_journal.BarrierTimeout:
                return JSONResponse(status_code=409,
                                    content={"code": "backup_barrier_timeout",
                                             "message": "仍有事务未完成，已降级为只读备份提示"})
            except transaction_journal.FileInUse:
                return JSONResponse(status_code=409,
                                    content={"code": "file_in_use_retry",
                                             "message": "文件正被其他程序占用，请稍后重试"})
            except transaction_journal.UnsafePath as exc:
                return JSONResponse(status_code=400,
                                    content={"code": "unsafe_path", "message": str(exc)})
        return wrapper

    # ------------------------------------------------------------- chapters
    @app.post("/api/projects/{identity}/chapters")
    @guard
    def create_chapter(identity: str, data: dict | None = None):
        return chapter_editor.new_chapter(_book(identity), data or {})

    @app.put("/api/projects/{identity}/chapters/{chapter}")
    @guard
    def save_chapter(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.save_version(_book(identity), chapter, data or {})

    @app.delete("/api/projects/{identity}/chapters/{chapter}")
    @guard
    def delete_chapter(identity: str, chapter: int, data: dict | None = None):
        body = data or {}
        return chapter_editor.delete_chapter(
            _book(identity), chapter,
            expected_version_id=str(body.get("expected_version_id") or ""),
            expected_content_sha256=str(body.get("expected_content_sha256") or ""),
            op_id=str(body.get("op_id") or ""))

    @app.put("/api/projects/{identity}/chapters/{chapter}/draft")
    @guard
    def save_chapter_draft(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.save_draft(_book(identity), chapter, data or {})

    @app.delete("/api/projects/{identity}/chapters/{chapter}/draft")
    @guard
    def discard_chapter_draft(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.discard_draft(_book(identity), chapter,
                                            draft_id=(data or {}).get("draft_id"))

    @app.post("/api/projects/{identity}/chapters/{chapter}/quick-check")
    @guard
    def quick_check(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.quick_check(_book(identity), chapter,
                                          content=(data or {}).get("content"))

    @app.post("/api/projects/{identity}/chapters/{chapter}/author-confirm")
    @guard
    def author_confirm(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.author_confirm(_book(identity), chapter, data or {})

    @app.delete("/api/projects/{identity}/chapters/{chapter}/author-confirm")
    @guard
    def author_confirm_revoke(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.revoke_author_confirm(_book(identity), chapter,
                                                   op_id=str((data or {}).get("op_id") or ""))

    @app.post("/api/projects/{identity}/chapters/{chapter}/sync-memory")
    @guard
    def sync_memory(identity: str, chapter: int, data: dict | None = None):
        return chapter_editor.sync_memory_preview(
            _book(identity), chapter,
            expected_version_id=str((data or {}).get("expected_version_id") or ""))

    @app.post("/api/projects/{identity}/chapters/{chapter}/split")
    @guard
    def split_chapter(identity: str, chapter: int, data: dict | None = None):
        body = data or {}
        return chapter_editor.split_chapter(
            _book(identity), chapter, offset=int(body.get("offset") or 0),
            title=str(body.get("title") or ""),
            expected_content_sha256=str(body.get("expected_content_sha256") or ""),
            op_id=str(body.get("op_id") or ""))

    @app.post("/api/projects/{identity}/chapters/merge-tail")
    @guard
    def merge_tail(identity: str, data: dict | None = None):
        return chapter_editor.merge_tail(_book(identity), op_id=str((data or {}).get("op_id") or ""))

    @app.post("/api/projects/{identity}/import-chapters")
    @guard
    def import_chapters(identity: str, data: dict | None = None):
        body = data or {}
        return chapter_editor.import_chapters(
            _book(identity), text=str(body.get("text") or ""),
            start_chapter=body.get("start_chapter"),
            preview=bool(body.get("preview", True)),
            op_id=str(body.get("op_id") or ""))

    @app.get("/api/projects/{identity}/trash")
    @guard
    def trash_list(identity: str):
        return chapter_editor.list_trash(_book(identity))

    @app.post("/api/projects/{identity}/trash/{entry}/restore")
    @guard
    def trash_restore(identity: str, entry: str, data: dict | None = None):
        return chapter_editor.restore_trash(_book(identity), entry,
                                            op_id=str((data or {}).get("op_id") or ""))

    @app.get("/api/projects/{identity}/chapters/{chapter}/previews")
    @guard
    def chapter_previews(identity: str, chapter: int):
        rows = revision_plan.list_previews(_book(identity), chapter)
        try:
            from integration import annotations
            rows = [{**row, "merge_state": annotations.preview_merge_state(_book(identity), chapter, row)} for row in rows]
        except Exception:
            pass
        return {"chapter_id": int(chapter), "previews": rows, "count": len(rows)}

    # -------------------------------------------------------------- outline
    @app.get("/api/projects/{identity}/outline/files")
    @guard
    def outline_files(identity: str):
        return outline_editor.files(_book(identity))

    @app.get("/api/projects/{identity}/outline/files/{filename}")
    @guard
    def outline_read(identity: str, filename: str):
        return outline_editor.read_file(_book(identity), filename)

    @app.put("/api/projects/{identity}/outline/files/{filename}")
    @guard
    def outline_write(identity: str, filename: str, data: dict | None = None):
        body = data or {}
        return outline_editor.write_file(
            _book(identity), filename, content=str(body.get("content") or ""),
            revision=body.get("revision"),
            confirm_removed_chapters=body.get("confirm_removed_chapters"),
            op_id=body.get("op_id"))

    @app.post("/api/projects/{identity}/outline/files")
    @guard
    def outline_create(identity: str, data: dict | None = None):
        body = data or {}
        return outline_editor.create_file(_book(identity), filename=str(body.get("filename") or ""),
                                          content=str(body.get("content") or ""))

    @app.put("/api/projects/{identity}/outline/meta")
    @guard
    def outline_meta(identity: str, data: dict | None = None):
        body = data or {}
        return outline_editor.write_meta(_book(identity), body,
                                         expected_meta_revision=body.get("expected_meta_revision"))

    @app.get("/api/projects/{identity}/lore/files")
    @guard
    def lore_files(identity: str):
        return outline_editor.lore_files(_book(identity))

    @app.get("/api/projects/{identity}/lore/files/{filename}")
    @guard
    def lore_read(identity: str, filename: str):
        return outline_editor.read_lore(_book(identity), filename)

    @app.put("/api/projects/{identity}/lore/files/{filename}")
    @guard
    def lore_write(identity: str, filename: str, data: dict | None = None):
        body = data or {}
        return outline_editor.write_lore(_book(identity), filename,
                                         content=str(body.get("content") or ""),
                                         revision=body.get("revision"))

    @app.get("/api/projects/{identity}/search")
    @guard
    def search(identity: str, q: str = "", limit: int = 20):
        return chapter_editor.search_project(_book(identity), q, limit=max(1, min(int(limit), 100)))

    # --------------------------------------------------------- backup/legacy
    @app.post("/api/projects/{identity}/backup")
    @guard
    def backup(identity: str, data: dict | None = None):
        body = data or {}
        target = body.get("destination")
        destination = Path(target).expanduser() if target else (
            data_dir / "backups" / f"backup-{identity}-{time.strftime('%Y%m%dT%H%M%S')}")
        extra = [data_dir / "manager.sqlite3", data_dir / "costs.sqlite3"]
        return transaction_journal.backup(_book(identity), destination,
                                          extra_sqlite=[p for p in extra if p.is_file()],
                                          wait_seconds=float(body.get("wait_seconds") or 5.0))

    @app.post("/api/projects/{identity}/rollback/export-legacy")
    @guard
    def export_legacy(identity: str, data: dict | None = None):
        body = data or {}
        target = body.get("destination")
        destination = Path(target).expanduser() if target else (
            _book(identity) / ".webnovel" / "exports" / f"legacy-{time.strftime('%Y%m%dT%H%M%S')}")
        return transaction_journal.export_legacy(
            _book(identity), destination, mode=str(body.get("mode") or "current"),
            snapshot_dir=body.get("snapshot_dir"))
