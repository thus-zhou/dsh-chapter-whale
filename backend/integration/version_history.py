"""章节历史、最佳版本推荐与恢复（只读推荐，恢复是显式操作）。

版本数据来自 :mod:`chapter_versions`；审查回执与质量报告的关联只按哈希匹配，
不猜章号，也不把过期报告当成通过依据。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import chapter_versions

SCHEMA_VERSION = 1
_MAX_VERSIONS = 200


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def attempts(project, chapter: int) -> List[Dict[str, Any]]:
    """该章的全部审查回执，按时间倒序。"""
    folder = Path(project) / ".webnovel" / "review_attempts"
    if not folder.is_dir():
        return []
    rows = []
    for path in folder.glob(f"{int(chapter):04d}-*.json"):
        record = _read_json(path)
        if record.get("chapter_id") in (int(chapter), str(int(chapter))):
            rows.append(record)
    rows.sort(key=lambda item: item.get("reviewed_at") or "", reverse=True)
    return rows


def _reports(project, chapter: int) -> List[Dict[str, Any]]:
    from . import quality_gate

    return quality_gate.history(project, chapter)


def _attach(meta: Dict[str, Any], receipts: List[Dict[str, Any]], reports: List[Dict[str, Any]],
            config=None, contract_hash="") -> Dict[str, Any]:
    from . import quality_gate

    digest = meta.get("body_digest")
    sha = meta.get("sha256")
    linked = [r for r in receipts if r.get("body_sha256") == digest]
    report = next((r for r in reports if r.get("version_id") and r.get("version_id") == sha), None)
    if report is None:
        report = next((r for r in reports if r.get("body_sha256") in {digest, sha}), None)
    quality = None
    if report:
        review = report.get("review") or {}
        gate = quality_gate.judge(review, config)
        bound_contract = report.get("contract_hash")
        stale_reason = ("contract_unbound" if not bound_contract else "contract_changed") if (
            (contract_hash or bound_contract) and bound_contract != contract_hash) else None
        computed = gate.get("computed") or {}
        quality = {
            "report_id": report.get("report_id"),
            "pass": gate.get("quality_pass") is True and stale_reason is None,
            "stale_reason": stale_reason,
            "total": computed.get("total"),
            "blocking": len(computed.get("blocking") or []),
            "created_at": report.get("created_at"),
        }
    return {
        "version_id": sha,
        "seq": meta.get("seq"),
        "sha256": sha,
        "body_digest": digest,
        "bytes": meta.get("bytes"),
        "source": meta.get("source"),
        "op_id": meta.get("op_id"),
        "run_id": meta.get("run_id"),
        "attempt_id": meta.get("attempt_id"),
        "parent": meta.get("parent"),
        "title": meta.get("title"),
        "note": meta.get("note"),
        "created_at": meta.get("created_at"),
        "current": bool(meta.get("current")),
        "reviews": [
            {
                "reviewed_at": row.get("reviewed_at"),
                "decision": (row.get("review") or {}).get("review_decision"),
                "needs_revision": (row.get("review") or {}).get("needs_revision"),
            }
            for row in linked[:3]
        ],
        "quality": quality,
    }


def history(project, chapter: int, *, limit: int = _MAX_VERSIONS, config=None) -> Dict[str, Any]:
    """版本列表：轮次倒序，带原稿/当前/候选引用与关联的质量结论。"""
    versions = chapter_versions.list_versions(project, chapter)
    current = chapter_versions.current_version(project, chapter)
    current_id = (current or {}).get("sha256")
    receipts = attempts(project, chapter)
    reports = _reports(project, chapter)
    from . import bridge
    contract_hash = bridge.creative_contract_hash(project)
    rows = []
    for meta in reversed(versions[-limit:]):
        meta = dict(meta)
        meta["current"] = meta.get("sha256") == current_id
        rows.append(_attach(meta, receipts, reports, config, contract_hash))
    from . import revision_plan

    preview = revision_plan.public(project, chapter).get("preview")
    return {
        "schema_version": SCHEMA_VERSION,
        "chapter_id": int(chapter),
        "current_version_id": current_id,
        "versions": rows,
        "pending_preview": preview,
        "count": len(rows),
    }


def read(project, chapter: int, version_id: str) -> Dict[str, Any]:
    """按需读取某一版正文（大文本不随列表返回）。"""
    result = chapter_versions.read_version(project, chapter, version_id)
    return {
        "chapter_id": int(chapter),
        "version_id": result.get("sha256"),
        "sha256": result.get("sha256"),
        "body": result.get("text") or "",
        "bytes": len((result.get("text") or "").encode("utf-8")),
    }


def _rank_key(row: Dict[str, Any]) -> tuple:
    quality = row.get("quality") or {}
    passed = quality.get("pass") is True
    total = quality.get("total")
    return (
        0 if passed else 1,
        quality.get("blocking") if quality.get("blocking") is not None else 99,
        -(total if isinstance(total, (int, float)) else -1),
        row.get("bytes") or 0,
        row.get("created_at") or "",
    )


def best(project, chapter: int, *, config=None) -> Dict[str, Any]:
    """推荐候选：先满足硬检查与质量门槛，再比较严重问题、分项与改动范围。

    只给建议，从不改写当前正文；作者手动选定或恢复的正文不会被后台覆盖。
    """
    data = history(project, chapter, config=config)
    if not data["versions"]:
        return {"chapter_id": int(chapter), "status": "no_versions", "recommended": None,
                "note": "还没有保存过的版本", "compared": []}
    scored = [row for row in data["versions"] if row.get("quality")]
    if not scored:
        current = next((row for row in data["versions"] if row.get("current")), data["versions"][0])
        return {
            "chapter_id": int(chapter),
            "status": "no_passing_version",
            "recommended": current,
            "note": "还没有质量报告；当前正文保持不变，先审查再比较版本",
            "compared": [],
        }
    ranked = sorted(scored, key=_rank_key)
    top = ranked[0]
    quality = top.get("quality") or {}
    status = "passing" if quality.get("pass") is True else "no_passing_version"
    note = ("仅为推荐，不会自动覆盖当前正文；恢复需要作者确认" if status == "passing"
            else "没有质量通过的版本；下表只作参考，不会自动覆盖当前正文")
    return {
        "chapter_id": int(chapter),
        "status": status,
        "recommended": top,
        "note": note,
        "compared": [
            {
                "version_id": row.get("version_id"),
                "pass": (row.get("quality") or {}).get("pass"),
                "total": (row.get("quality") or {}).get("total"),
                "blocking": (row.get("quality") or {}).get("blocking"),
                "bytes": row.get("bytes"),
                "created_at": row.get("created_at"),
            }
            for row in ranked[:5]
        ],
    }


def restore(project, chapter: int, version_id: str, *, op_id: Optional[str] = None, config=None) -> Dict[str, Any]:
    """恢复旧版本：备份当前稿、登记新版本、重算报告有效性。"""
    before = chapter_versions.current_version(project, chapter)
    snapshot = chapter_versions.snapshot(project, chapter, source="backup", note=f"恢复前备份（来自 {version_id[:12]}）")
    identifier = op_id or f"restore-{uuid.uuid4().hex}"
    result = chapter_versions.restore_version(project, chapter, version_id, op_id=identifier,
                                              note=f"恢复 {version_id[:12]}")
    from . import quality_gate

    after = chapter_versions.current_version(project, chapter)
    report = quality_gate.status(project, chapter, config=config)
    return {
        "status": "restored",
        "chapter_id": int(chapter),
        "op_id": identifier,
        "version_id": (after or {}).get("sha256"),
        "sha256": (after or {}).get("sha256"),
        "backup_version_id": (snapshot or before or {}).get("sha256"),
        "report_status": report,
        "commit": result,
    }


def workbench(project, chapter: int, *, config=None) -> Dict[str, Any]:
    """章节质量工作台的最小聚合视图：报告、版本、候选与最佳推荐。"""
    from . import quality_gate, revision_plan

    latest = history(project, chapter, limit=20, config=config)
    return {
        "chapter_id": int(chapter),
        "report": quality_gate.public_report(project, chapter, config),
        "history": latest,
        "preview": revision_plan.public(project, chapter).get("preview"),
        "best": best(project, chapter, config=config),
    }
