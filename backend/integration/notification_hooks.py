"""把运行结果接到本地事件列表与通知发件箱（只存稿链路的接线层）。

约束（来自 A04 验收）：
- 通知失败绝不影响章节：本模块对外只返回汇总，不向调用方抛异常；
- 同一故障重复 20 次只保留一个打开中的 incident，恢复后再发生另建 sequence+1；
- 事件载荷不带正文、令牌、私有用户名与绝对路径；
- 没有配置收件人时仍然留本地事件，不建空发件箱。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import bridge, notifications

EVENT_PAUSED = "job.paused"
EVENT_REVIEW = "review_exhausted"
EVENT_NEEDS_CHECK = "publication.needs_check"
EVENT_RESOLVED = "incident.resolved"
EVENT_SUMMARY = "run.summary"


def db_path() -> Path:
    override = os.environ.get("NOVEL_HELPER_NOTIFICATIONS_DB")
    if override:
        return Path(override).expanduser()
    return bridge.COMBINED_ROOT / "integration_data" / "notifications.sqlite3"


def connection():
    return notifications.connect(db_path())


def _alias(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return notifications.alias_mask(bridge.safe_dir_name(text), label)


def _run_key(job_id: str, record: Dict[str, Any]) -> str:
    seed = "|".join(str(record.get(key) or "") for key in ("started_at", "run_date", "slot"))
    return hashlib.sha256(f"{job_id}|{seed}".encode("utf-8")).hexdigest()[:20]


def _saved(record: Dict[str, Any]) -> Dict[str, Any]:
    ids = [int(item) for item in record.get("saved_ids") or [] if isinstance(item, int)]
    return {"saved_chapters": len(ids), "saved_words": int(record.get("saved_words") or 0)}


def on_run_finished(job_id: str, job: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """把一次只存稿运行映射成事件；任何异常都只记在返回值里。"""
    summary: Dict[str, Any] = {"events": [], "queued": 0, "state": "skipped"}
    try:
        status = str(record.get("status") or "")
        mode = str(record.get("publication_mode") or job.get("publication_mode") or "draft_only")
        if status not in {"success", "needs_revision", "blocked", "failed", "metadata_pending", "waiting"}:
            return summary
        db = connection()
        try:
            recipients = [item for item in notifications.list_recipients(db)
                          if item.get("enabled", True)]
            payload = {
                "run_date": record.get("run_date"),
                "slot": record.get("slot"),
                "status": status,
                "publication_mode": mode,
                "reason_code": record.get("reason_code"),
                "next_action": record.get("next_action"),
                "next_retry_at": record.get("next_retry_at"),
                **_saved(record),
            }
            alias = {"project": _alias(job.get("project", ""), "项目"),
                     "book": _alias(job.get("book", ""), "作品")}
            # Detailed local diagnostics can contain project paths or provider
            # response fragments. Notifications carry a controlled reason code.
            reason = str(record.get("reason_code") or status)[:120]
            payload['next_action'] = '查看本机运行记录并继续原任务' if payload.get('next_action') else None
            if status == "needs_revision":
                event_type = EVENT_REVIEW
                payload["reason"] = reason
                missing = record.get("needs_revision") or []
                chapter = missing[0].get("chapter_id") if missing and isinstance(missing[0], dict) else None
                incident = notifications.open_incident(
                    db, event_type, job_id, alias["project"], alias["book"], payload,
                    chapter_id=chapter)
                summary["events"].append({"event_type": event_type,
                                          "incident": incident["id"],
                                          "sequence": incident.get("sequence"),
                                          "deduplicated": bool(incident.get("deduplicated"))})
                if not incident.get("deduplicated"):
                    rows = notifications.enqueue(db, incident["id"], event_type, payload, recipients,
                                                 store_without_recipients=True)
                    summary["queued"] += len(rows)
            elif status in {"blocked", "failed", "metadata_pending", "waiting"}:
                event_type = EVENT_PAUSED
                payload["reason"] = reason
                incident = notifications.open_incident(
                    db, event_type, job_id, alias["project"], alias["book"], payload)
                summary["events"].append({"event_type": event_type,
                                          "incident": incident["id"],
                                          "sequence": incident.get("sequence"),
                                          "deduplicated": bool(incident.get("deduplicated"))})
                if not incident.get("deduplicated"):
                    rows = notifications.enqueue(db, incident["id"], event_type, payload, recipients,
                                                 store_without_recipients=True)
                    summary["queued"] += len(rows)
            else:
                rows = notifications.enqueue(
                    db, None, EVENT_SUMMARY, payload, recipients,
                    dedupe_key=f"run:{_run_key(job_id, record)}", store_without_recipients=True)
                summary["events"].append({"event_type": EVENT_SUMMARY,
                                          "recipients": len(rows)})
                summary["queued"] += len(rows)
            summary["state"] = "recorded"
            return summary
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - 通知失败绝不回滚章节
        summary["state"] = "failed"
        summary["error"] = notifications.redact_error(f"{type(exc).__name__}: {exc}")
        return summary


def resolve(job_id: str, note: str = "") -> List[Dict[str, Any]]:
    """作者手动恢复后关闭该任务打开的 incident，并投递恢复事件。"""
    resolved: List[Dict[str, Any]] = []
    db = connection()
    try:
        recipients = [item for item in notifications.list_recipients(db) if item.get("enabled", True)]
        for incident in notifications.list_incidents(db, status="open", limit=100):
            if incident.get("job_id") != job_id:
                continue
            result = notifications.resolve_incident(db, incident["id"], note=note)
            if result.get("resolved"):
                notifications.enqueue(db, incident["id"], EVENT_RESOLVED,
                                      {"reason": note[:400], "job_id": job_id}, recipients,
                                      store_without_recipients=True)
            resolved.append(result)
    finally:
        db.close()
    return resolved


__all__ = ["connection", "db_path", "on_run_finished", "resolve",
           "EVENT_PAUSED", "EVENT_REVIEW", "EVENT_NEEDS_CHECK", "EVENT_RESOLVED", "EVENT_SUMMARY"]
