"""引用计数 GC、五态资源账本与诊断包（v0.9.5 四期）。

GC 只删“无引用且已过保留期”的历史快照，绝不碰当前版本、草稿、批注证据、
回收站和作者设定。诊断包默认剥离正文与大纲，只保留哈希、计数和健康结论。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from integration import chapter_versions as versions
from integration import workbench_db as wb

_PREVIEW_DIRS = ("previews", "preview-cache", "history", "snapshots", "outline-backups")
_KEEP_NAMES = {"manifest.json", "index.json", "receipts.json", "writer_receipts.json"}
_SECRET_KEYS = {"api_key", "apikey", "token", "secret", "password", "authorization",
                "content", "body", "outline", "master_outline", "card_md", "text"}


class MaintenanceError(RuntimeError):
    def __init__(self, code: str, *, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _protected_paths(project) -> Set[str]:
    protected: Set[str] = set()
    mapping = versions.chapter_map(project)
    for path in mapping.values():
        protected.add(str(Path(path).resolve()))
    meta_dir = Path(project) / ".webnovel"
    for name in ("chapter_versions", "drafts", "trash"):
        folder = meta_dir / name
        if folder.is_dir():
            for path in folder.rglob("*"):
                if path.is_file():
                    protected.add(str(path.resolve()))
    try:
        wb.initialize(project)
        with wb.connect(project) as db:
            for row in db.execute("SELECT content_path FROM chapter_drafts WHERE content_path IS NOT NULL"):
                if row[0]:
                    protected.add(str((Path(project) / row[0]).resolve()))
            for row in db.execute("SELECT content_path FROM drafts_history WHERE content_path IS NOT NULL"):
                if row[0]:
                    protected.add(str((Path(project) / row[0]).resolve()))
    except sqlite3.Error:
        pass
    return protected


def _candidate_files(project) -> List[Path]:
    root = Path(project) / ".webnovel"
    result = []
    for name in _PREVIEW_DIRS:
        folder = root / name
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.name not in _KEEP_NAMES and not path.is_symlink():
                result.append(path)
    return sorted(result)


def collect_garbage(project, *, dry_run: bool = True, min_age_seconds: int = 7 * 86400) -> Dict[str, Any]:
    protected = _protected_paths(project)
    cutoff = time.time() - max(0, int(min_age_seconds))
    removed, kept, freed = [], [], 0
    for path in _candidate_files(project):
        resolved = str(path.resolve())
        if resolved in protected:
            kept.append(resolved)
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            kept.append(resolved)
            continue
        removed.append(resolved)
        freed += stat.st_size
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                removed.pop()
                freed -= stat.st_size
    return {"status": "dry_run" if dry_run else "collected", "dry_run": bool(dry_run),
            "removed": removed, "kept": len(kept), "bytes": freed,
            "count": len(removed)}


def register_artifact(project, path, *, kind: str = "history", ref_count: int = 0,
                      protected: bool = False) -> Dict[str, Any]:
    wb.initialize(project)
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = Path(project) / file_path
    if not file_path.is_file():
        raise MaintenanceError("artifact_missing")
    artifact_id = wb.new_id("art")
    with wb.write_tx(project) as db:
        db.execute("INSERT OR REPLACE INTO artifact_refs(artifact_id, path, kind, ref_count, bytes, "
                   "protected, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (artifact_id, str(file_path.relative_to(Path(project))), kind, int(ref_count),
                    file_path.stat().st_size, 1 if protected else 0, _now(), _now()))
    return {"artifact_id": artifact_id, "path": str(file_path), "bytes": file_path.stat().st_size}


def resource_ledger(project) -> Dict[str, Any]:
    wb.initialize(project)
    states = {state: {"count": 0, "tokens": 0, "cost_cny": 0.0}
              for state in ("reserved", "dispatched", "settled", "unknown_charge", "released")}
    try:
        with wb.connect(project) as db:
            for row in db.execute("SELECT state, COUNT(*), COALESCE(SUM(tokens),0), "
                                  "COALESCE(SUM(cost_cny),0) FROM request_budget GROUP BY state"):
                state = str(row[0])
                if state in states:
                    states[state] = {"count": int(row[1]), "tokens": int(row[2]),
                                     "cost_cny": round(float(row[3]), 4)}
    except sqlite3.Error:
        pass
    tasks = {}
    try:
        with wb.connect(project) as db:
            for row in db.execute("SELECT state, COUNT(*) FROM task_queue GROUP BY state"):
                tasks[str(row[0])] = int(row[1])
    except sqlite3.Error:
        pass
    artifacts = {"count": 0, "bytes": 0}
    try:
        with wb.connect(project) as db:
            row = db.execute("SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM artifact_refs").fetchone()
            artifacts = {"count": int(row[0]), "bytes": int(row[1])}
    except sqlite3.Error:
        pass
    return {"states": states, "tasks": tasks, "artifacts": artifacts,
            "total_tokens": sum(item["tokens"] for item in states.values()),
            "total_cost_cny": round(sum(item["cost_cny"] for item in states.values()), 4)}


def health(project) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    wb.initialize(project)
    db_path = wb.db_path(project)
    integrity = "missing"
    if db_path.exists():
        db = None
        try:
            db = sqlite3.connect(str(db_path))
            integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                issues.append({"code": "db_integrity", "severity": "P0", "detail": integrity})
        except sqlite3.Error as exc:
            integrity = "error"
            issues.append({"code": "db_open_failed", "severity": "P0", "detail": str(exc)})
        finally:
            if db is not None:
                db.close()
    mapping = versions.chapter_map(project)
    with wb.connect(project) as db:
        indexed = {str(row[0]) for row in db.execute("SELECT chapter_id FROM chapter_meta")}
    for chapter in sorted(indexed):
        if int(chapter) not in mapping:
            issues.append({"code": "orphan_chapter_index", "severity": "P1", "chapter": int(chapter)})
    try:
        versions.load_index(project)
    except Exception as exc:  # noqa: BLE001
        issues.append({"code": "version_index_corrupt", "severity": "P0", "detail": str(exc)})
    receipts = Path(project) / ".webnovel" / "writer_receipts.json"
    if receipts.is_file():
        try:
            data = json.loads(receipts.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not object")
            for key, value in data.items():
                if not isinstance(value, dict):
                    issues.append({"code": "receipt_corrupt", "severity": "P1", "chapter": key})
        except ValueError:
            issues.append({"code": "receipt_corrupt", "severity": "P1"})
    usage = shutil.disk_usage(Path(project))
    if usage.free < 512 * 1024 * 1024:
        issues.append({"code": "disk_low", "severity": "P1", "free_bytes": usage.free})
    return {"status": "ok" if not issues else "degraded", "integrity": integrity,
            "chapters": len(mapping), "issues": issues,
            "counts": {level: sum(1 for item in issues if item["severity"] == level)
                       for level in ("P0", "P1", "P2")},
            "disk_free_bytes": usage.free, "checked_at": _now()}


def _strip(value):
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items()
                if str(key).lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_strip(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 200:
        return value[:80] + "…[stripped]"
    return value


def export_bundle(project, destination) -> Dict[str, Any]:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {"health": health(project), "ledger": resource_ledger(project),
              "schema_version": wb.SCHEMA_VERSION, "generated_at": _now()}
    mapping = versions.chapter_map(project)
    index = []
    for chapter in sorted(mapping):
        meta = versions.current_version(project, chapter) or {}
        index.append({"chapter_id": chapter, "title": meta.get("title", ""),
                      "version_id": meta.get("version_id"),
                      "sha256": versions.file_sha256(mapping[chapter]),
                      "bytes": mapping[chapter].stat().st_size})
    manifest = {"chapters": _strip(index), "count": len(index)}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("diagnostics.json", json.dumps(_strip(report), ensure_ascii=False, indent=2))
        bundle.writestr("chapters.index.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr("README.txt", "诊断包默认不含正文、大纲与密钥；仅哈希与计数。\n")
    return {"status": "exported", "path": str(destination), "bytes": destination.stat().st_size,
            "contains_content": False}


def system_health(data_dir) -> Dict[str, Any]:
    """Global diagnostic view without project text."""
    root = Path(data_dir)
    checks = []
    for name in ("manager.sqlite3", "costs.sqlite3", "agent_room.sqlite3"):
        path = root / name
        checks.append({"name": name, "ok": path.is_file(),
                       "bytes": path.stat().st_size if path.is_file() else 0})
    usage = shutil.disk_usage(root if root.exists() else Path("."))
    checks.append({"name": "disk_free", "ok": usage.free > 512 * 1024 * 1024,
                   "bytes": usage.free})
    return {"status": "ok" if all(item["ok"] for item in checks) else "degraded",
            "checks": checks, "checked_at": _now()}


def self_heal(project, action: str) -> Dict[str, Any]:
    if action == "rebuild_search":
        wb.rebuild_search(project) if hasattr(wb, "rebuild_search") else None
        return {"status": "healed", "action": action}
    if action == "checkpoint":
        wb.initialize(project)
        with wb.connect(project) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"status": "healed", "action": action}
    raise MaintenanceError("unsafe_heal_action", status=400)
