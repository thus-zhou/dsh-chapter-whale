"""引用计数 GC、五态资源账本与诊断包（v0.9.5 四期）。

GC 只删“无引用且已过保留期”的历史快照，绝不碰当前版本、草稿、批注证据、
回收站和作者设定。诊断包默认剥离正文与大纲，只保留哈希、计数和健康结论。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from integration import chapter_versions as versions
from integration import lock_manager
from integration import workbench_db as wb

# 审计 C-03：snapshots 与 revision_previews 是批注/修订证据，不是可回收
# 预览缓存。它们不再进入 GC 候选集；引用集仍从 SQLite 计算，作为纵深防御。
_PREVIEW_DIRS = ("previews", "preview-cache", "history")
_EVIDENCE_DIRS = ("snapshots", "revision_previews")
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


def _referenced_snapshot_ids(project) -> Set[str]:
    """Snapshot ids still referenced by annotations / previews (audit C-03)."""
    ids: Set[str] = set()
    if not wb.db_path(project).exists():
        return ids
    try:
        with wb.connect(project) as db:
            for row in db.execute("SELECT anchor_json FROM annotations "
                                  "WHERE anchor_json IS NOT NULL AND anchor_json!=''"):
                try:
                    anchor = json.loads(row[0] or "{}")
                except ValueError:
                    continue
                digest = anchor.get("base_snapshot_id") if isinstance(anchor, dict) else None
                if digest:
                    ids.add(str(digest))
            for row in db.execute("SELECT base_snapshot_id FROM preview_index "
                                  "WHERE base_snapshot_id IS NOT NULL AND base_snapshot_id!=''"):
                ids.add(str(row[0]))
    except sqlite3.Error:
        pass
    return ids


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
    # 引用的基线快照 + 全部修订预览都是作者证据，GC 永不触碰。
    for digest in _referenced_snapshot_ids(project):
        protected.add(str((meta_dir / "snapshots" / f"{digest}.txt").resolve()))
    for name in _EVIDENCE_DIRS:
        folder = meta_dir / name
        if folder.is_dir() and not folder.is_symlink():
            for path in folder.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    protected.add(str(path.resolve()))
    if not wb.db_path(project).exists():
        return protected
    try:
        wb.initialize(project)
        with wb.connect(project) as db:
            for row in db.execute("SELECT path, ref_count, protected FROM artifact_refs"):
                if row[0] and (int(row[1] or 0) > 0 or int(row[2] or 0)):
                    protected.add(str((Path(project) / row[0]).resolve()))
    except sqlite3.Error:
        pass
    return protected


def _candidate_files(project) -> List[Path]:
    root = Path(project) / ".webnovel"
    project_root = Path(project).resolve()
    result = []
    for name in _PREVIEW_DIRS:
        folder = root / name
        if folder.is_symlink() or not folder.is_dir():
            continue
        try:
            if project_root not in folder.resolve().parents and folder.resolve() != project_root:
                continue
        except OSError:
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.name not in _KEEP_NAMES and not path.is_symlink():
                try:
                    if project_root not in path.resolve().parents:
                        continue
                except OSError:
                    continue
                result.append(path)
    return sorted(result)


def collect_garbage(project, *, dry_run: bool = True, min_age_seconds: int = 7 * 86400) -> Dict[str, Any]:
    # 审计 C-04：诊断域锁先于 SQLite 事务，GC 与导出不会交错删/读。
    with lock_manager.hold(project, "diagnostics", "diagnostics", timeout=10.0):
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


def resource_ledger(project, costs_db=None) -> Dict[str, Any]:
    states = {state: {"count": 0, "tokens": 0, "cost_cny": 0.0}
              for state in ("reserved", "dispatched", "settled", "unknown_charge", "released")}
    # 审计 C-30：只读账本不得为未初始化的项目创建 workbench.sqlite3。
    if not wb.db_path(project).exists():
        return {"states": states, "tasks": {}, "artifacts": {"count": 0, "bytes": 0},
                "total_tokens": 0, "total_cost_cny": 0.0}
    wb.initialize(project)
    budget_db = Path(costs_db) if costs_db is not None and Path(costs_db).is_file() else None
    if budget_db is None:
        candidate = wb.db_path(project)
        probe = None
        try:
            probe = sqlite3.connect(str(candidate))
            if probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='request_budget'").fetchone():
                budget_db = candidate
        except sqlite3.Error:
            budget_db = None
        finally:
            if probe is not None:
                probe.close()
    if budget_db is not None:
        db = None
        try:
            db = sqlite3.connect(str(budget_db))
            for row in db.execute("SELECT state, COUNT(*), COALESCE(SUM(tokens),0), "
                                  "COALESCE(SUM(cost_cny),0) FROM request_budget GROUP BY state"):
                state = str(row[0])
                if state in states:
                    states[state] = {"count": int(row[1]), "tokens": int(row[2]),
                                     "cost_cny": round(float(row[3]), 4)}
        except sqlite3.Error:
            pass
        finally:
            if db is not None:
                db.close()
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
    root = Path(project)
    # 审计 C-30：对不存在/非项目目录只读返回，绝不 initialize 出
    # ``.webnovel/workbench.sqlite3`` 的写副作用。
    if not root.is_dir():
        return {"status": "missing", "integrity": "missing", "issues": [],
                "chapters": 0, "versions": 0, "drafts": 0,
                "counts": {level: 0 for level in ("P0", "P1", "P2")},
                "disk_free_bytes": 0, "checked_at": _now()}
    db_path = wb.db_path(project)
    db_ready = db_path.exists()
    integrity = "missing"
    if db_ready:
        try:
            wb.initialize(project)
        except sqlite3.Error as exc:
            return {"status": "degraded", "integrity": "error", "issues": [
                {"code": "db_open_failed", "severity": "P0", "detail": str(exc)}],
                "chapters": 0, "versions": 0, "drafts": 0}
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
    indexed: Set[str] = set()
    if db_ready:
        try:
            with wb.connect(project) as db:
                indexed = {str(row[0]) for row in db.execute("SELECT chapter_id FROM chapter_meta")}
        except sqlite3.Error:
            indexed = set()
    for chapter in sorted(indexed):
        if int(chapter) not in mapping:
            # 审计 C-28：chapter_meta 永久保留 uid，正常删章后必然出现该索引；
            # 降为 P2 信息，不再把每次删除都报成 P1 并使整盘永久 degraded。
            issues.append({"code": "orphan_chapter_index", "severity": "P2", "chapter": int(chapter)})
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
    try:
        usage = shutil.disk_usage(root)
        free = usage.free
    except OSError:
        free = 0
    if free and free < 512 * 1024 * 1024:
        issues.append({"code": "disk_low", "severity": "P1", "free_bytes": free})
    blocking = [item for item in issues if item["severity"] in {"P0", "P1"}]
    return {"status": "degraded" if blocking else "ok", "integrity": integrity,
            "chapters": len(mapping), "issues": issues,
            "counts": {level: sum(1 for item in issues if item["severity"] == level)
                       for level in ("P0", "P1", "P2")},
            "disk_free_bytes": free, "checked_at": _now()}


def _strip(value):
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items()
                if str(key).lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [_strip(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 200:
        return value[:80] + "…[stripped]"
    return value


def export_bundle(project, destination, *, allowed_dir=None) -> Dict[str, Any]:
    """Write a diagnostics zip; never create the project database (audit C-30)."""
    if not Path(project).is_dir():
        raise MaintenanceError("project_missing", status=404)
    destination = Path(destination).expanduser()
    project_root = Path(project).resolve()
    try:
        resolved = destination.resolve(strict=False)
    except OSError:
        raise MaintenanceError("destination_invalid")
    if resolved.suffix.lower() != ".zip":
        raise MaintenanceError("destination_must_be_zip")
    if project_root == resolved or project_root in resolved.parents:
        raise MaintenanceError("destination_inside_project")
    # 审计 C-14：调用方（API）固定导出目录；维护层再做一次越界校验。
    if allowed_dir is not None:
        allowed = Path(allowed_dir).expanduser().resolve(strict=False)
        if resolved != allowed and allowed not in resolved.parents:
            raise MaintenanceError("destination_outside_allowed")
    if resolved.exists():
        raise MaintenanceError("destination_exists")
    with lock_manager.hold(project, "diagnostics", "diagnostics", timeout=10.0):
        return _export_bundle_locked(project, destination, resolved)


def _export_bundle_locked(project, destination: Path, resolved: Path) -> Dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {"health": health(project), "ledger": resource_ledger(project),
              "schema_version": wb.SCHEMA_VERSION, "generated_at": _now()}
    mapping = versions.chapter_map(project)
    index = []
    for chapter in sorted(mapping):
        meta = versions.current_version(project, chapter) or {}
        index.append({"chapter_id": chapter, "version_id": meta.get("version_id"),
                      "sha256": versions.file_sha256(mapping[chapter]),
                      "bytes": mapping[chapter].stat().st_size})
    manifest = {"chapters": _strip(index), "count": len(index)}
    handle, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp",
                                         dir=str(destination.parent))
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("diagnostics.json", json.dumps(_strip(report), ensure_ascii=False, indent=2))
            bundle.writestr("chapters.index.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            bundle.writestr("README.txt", "诊断包默认不含正文、大纲与密钥；仅哈希与计数。\n")
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return {"status": "exported", "path": str(destination), "bytes": destination.stat().st_size,
            "contains_content": False}


def system_health(data_dir) -> Dict[str, Any]:
    """Global diagnostic view without project text."""
    root = Path(data_dir)
    checks = []
    # 审计 C-29：costs/agent_room 是按需创建的库；新装环境缺失不等于 degraded。
    for name, required in (("manager.sqlite3", True), ("costs.sqlite3", False),
                           ("agent_room.sqlite3", False)):
        path = root / name
        exists = path.is_file()
        checks.append({"name": name, "ok": exists or not required,
                       "bytes": path.stat().st_size if exists else 0,
                       "state": "ok" if exists else ("missing" if required else "not_created")})
    usage = shutil.disk_usage(root if root.exists() else Path("."))
    checks.append({"name": "disk_free", "ok": usage.free > 512 * 1024 * 1024,
                   "bytes": usage.free})
    return {"status": "ok" if all(item["ok"] for item in checks) else "degraded",
            "checks": checks, "checked_at": _now()}


def self_heal(project, action: str) -> Dict[str, Any]:
    if action == "rebuild_search":
        with lock_manager.hold(project, "diagnostics", "diagnostics", timeout=10.0):
            count = wb.rebuild_search(project)
        return {"status": "healed", "action": action, "documents": count}
    if action == "checkpoint":
        with lock_manager.hold(project, "diagnostics", "diagnostics", timeout=10.0):
            wb.initialize(project)
            with wb.connect(project) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"status": "healed", "action": action}
    raise MaintenanceError("unsafe_heal_action", status=400)
