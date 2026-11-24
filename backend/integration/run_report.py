"""只读运行投影：渲染它不会启动 worker、不写平台、不改调度状态。

调用方只拿结果展示；任何读取失败都降级成“未知”，绝不因为投影失败而
触发重试、补发或改写章节。恢复动作只以 available_actions 的形式给出建议，
由作者（或明确的接口调用）决定是否执行。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from integration import bridge, costs, length_policy, writer_runner
from integration import scheduler

RUN_ID_RE = r"^[0-9A-Za-z._-]{1,80}$"
SESSION_WINDOW = timedelta(seconds=120)


def ledger_path() -> Path:
    """与 costs.Attempt / 管理服务同源的账本路径。"""
    import os

    value = os.environ.get("NOVEL_HELPER_COST_DB")
    if value:
        return Path(value)
    return Path(bridge.COMBINED_ROOT) / "integration_data" / "costs.sqlite3"


def _runs_root() -> Path:
    return Path(scheduler.RUNS_ROOT)


def _safe_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    if not value or not __import__("re").match(RUN_ID_RE, value) or ".." in value:
        raise ValueError("运行记录编号无效")
    return value


def runs_dir(job_id: str) -> Path:
    return _runs_root() / bridge.safe_dir_name(job_id)


def list_runs(job_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """按时间倒序列出某任务的运行记录摘要；读不到的文件跳过而不是报错。"""
    folder = runs_dir(job_id)
    if not folder.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        if path.is_symlink():
            continue
        record = _read_record(path)
        if record is None:
            continue
        items.append(
            {
                "run_id": path.stem,
                "started_at": record.get("started_at"),
                "finished_at": record.get("finished_at"),
                "status": record.get("status"),
                "mode": record.get("mode"),
                "remote_state": record.get("remote_state") or scheduler.remote_state({"publication_mode": _mode_of(record)}),
                "run_date": record.get("run_date"),
                "slot": record.get("slot"),
                "error": _redact(record.get("error")),
            }
        )
        if len(items) >= max(1, min(int(limit or 20), 100)):
            break
    return items


def _read_record(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _mode_of(record: Dict[str, Any]) -> str:
    cycle = record.get("cycle") if isinstance(record.get("cycle"), dict) else {}
    for candidate in (record.get("publication_mode"), cycle.get("publication_mode")):
        if candidate:
            return str(candidate)
    # 老记录没有该字段：保持旧语义（平台发布），与调度器一致。
    return "publish_now"


def load_run(job_id: str, run_id: str) -> Dict[str, Any]:
    run_id = _safe_run_id(run_id)
    path = runs_dir(job_id) / f"{run_id}.json"
    if not path.is_file() or path.is_symlink():
        raise KeyError("运行记录不存在")
    record = _read_record(path)
    if record is None:
        raise KeyError("运行记录无法读取")
    return record


def _redact(value: Any) -> Any:
    """去掉绝对路径，保留可行动的信息。"""
    if not isinstance(value, str):
        return value
    text = value
    for root in {str(bridge.COMBINED_ROOT), str(Path(scheduler.RUNS_ROOT).parent)}:
        if root:
            text = text.replace(root, "~")
    return text


def _job_timezone(job: Dict[str, Any]) -> ZoneInfo:
    name = str(job.get("timezone") or "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Shanghai")


def _parse_time(value: Any, zone: ZoneInfo) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed


def _slot_line(record: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    zone = _job_timezone(job)
    run_date = record.get("run_date") or (record.get("cycle") or {}).get("run_date")
    slot = record.get("slot") or (record.get("cycle") or {}).get("slot")
    label = None
    when = None
    if run_date:
        try:
            day = datetime.fromisoformat(str(run_date)).date()
            label = f"{day.isoformat()}（{zone.key}）"
            if slot and "@" in str(slot):
                clock = str(slot).split("@", 1)[1]
                when = datetime.fromisoformat(f"{day.isoformat()}T{clock}").replace(tzinfo=zone)
                label = f"{day.isoformat()} {clock}（{zone.key}）"
        except ValueError:
            label = str(run_date)
    return {"run_date": run_date, "slot": slot, "timezone": zone.key, "label": label,
            "starts_at": when.isoformat() if when else None}


def _body_words(path: Path) -> Optional[int]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        return int(length_policy.body_chars(text))
    except Exception:  # noqa: BLE001 - 计数失败只能是未知，不能中断投影
        return None


def _chapter_files(project: Path) -> Dict[int, Path]:
    files: Dict[int, Path] = {}
    folder = project / "正文"
    if not folder.is_dir():
        return files
    for pattern in ("*.md", "*.txt"):
        for path in sorted(folder.rglob(pattern)):
            if path.is_symlink():
                continue
            parsed = bridge.parse_chapter_name(path.name)
            if not parsed:
                continue
            chapter = parsed[0] if isinstance(parsed, tuple) else parsed
            try:
                files.setdefault(int(chapter), path)
            except (TypeError, ValueError):
                continue
    return files


def _target_ids(record: Dict[str, Any]) -> List[int]:
    cycle = record.get("cycle") if isinstance(record.get("cycle"), dict) else {}
    raw: List[Any] = []
    for source in (record.get("target_ids"), cycle.get("target_ids")):
        if isinstance(source, (list, tuple)):
            raw.extend(source)
    for entry in record.get("generated") or []:
        if isinstance(entry, dict) and entry.get("chapter_id"):
            raw.append(entry.get("chapter_id"))
    for entry in cycle.get("draft_chapters") or []:
        if isinstance(entry, dict) and entry.get("chapter_id"):
            raw.append(entry.get("chapter_id"))
    seen: List[int] = []
    for value in raw:
        try:
            chapter = int(value)
        except (TypeError, ValueError):
            continue
        if chapter > 0 and chapter not in seen:
            seen.append(chapter)
    return sorted(seen)


def _cost_block(job: Dict[str, Any], record: Dict[str, Any], project: Path) -> Dict[str, Any]:
    """费用三分：known（有价有量）/ zero（有账本、确实没有调用）/ unknown（不可判定）。"""
    zone = _job_timezone(job)
    started = _parse_time(record.get("started_at"), zone)
    finished = _parse_time(record.get("finished_at"), zone)
    ledger = ledger_path()
    if not ledger.is_file():
        return {"state": "unknown", "reason": "费用账本尚未建立，无法判定本次是否产生调用",
                "currency": "CNY", "known_cost_cny": None, "tokens": None, "requests": None, "missing": None,
                "ledger_gaps": [], "windows": {"from": started.isoformat() if started else None,
                                               "to": finished.isoformat() if finished else None}}
    try:
        events = costs.event_rows(ledger, project=str(project))
        gaps = costs.ledger_gaps(ledger)
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "reason": _redact(f"费用账本不可读：{exc}"), "currency": "CNY",
                "known_cost_cny": None, "tokens": None, "requests": None, "missing": None,
                "ledger_gaps": [], "windows": {"from": started.isoformat() if started else None,
                                               "to": finished.isoformat() if finished else None}}
    if started is not None:
        lower = started - SESSION_WINDOW
        upper = (finished + SESSION_WINDOW) if finished else None
        windowed = []
        for event in events:
            created = _parse_time(event.get("created_at"), zone)
            if created is None or created < lower:
                continue
            if upper is not None and created > upper:
                continue
            windowed.append(event)
        events = windowed
    summary = costs.aggregate(events)
    missing = int(summary.get("unknown_usage") or 0) + int(summary.get("unpriced") or 0) + int(summary.get("unconverted") or 0)
    if not events:
        state = "unknown" if gaps else "zero"
    elif missing:
        state = "partial" if any(event.get("cost_cny") is not None for event in events) else "unknown"
    else:
        state = "known"
    priced = state in {"known", "partial"}
    return {
        "state": state,
        "currency": "CNY",
        "known_cost_cny": summary.get("cost_cny") if priced else None,
        "reported_cost_cny": summary.get("reported_cost_cny") if priced else None,
        "estimated_cost_cny": summary.get("estimated_cost_cny") if priced else None,
        "tokens": {key: summary.get(key) for key in ("input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens")},
        "requests": summary.get("calls"),
        "priced_requests": max(0, summary.get("calls", 0) - missing) if state != "unknown" else None,
        "missing": missing,
        "ledger_gaps": gaps,
        "windows": {"from": started.isoformat() if started else None,
                    "to": finished.isoformat() if finished else None},
    }


def _last_event(record: Dict[str, Any]) -> Dict[str, Any]:
    cycle = record.get("cycle") if isinstance(record.get("cycle"), dict) else {}
    message = record.get("error") or record.get("last_message") or cycle.get("last_message")
    at = record.get("finished_at") or record.get("started_at")
    code = record.get("status") or cycle.get("status")
    return {"at": at, "code": code, "message": _redact(message)}


def _actions(job: Dict[str, Any], record: Dict[str, Any], chapters: List[Dict[str, Any]],
             published: Iterable[int]) -> Dict[str, Any]:
    """按决策表给出可行动作；不执行任何动作。"""
    mode = _mode_of(record)
    status = str(record.get("status") or "")
    published_set = set(published)
    pending = [c for c in chapters if not c["body_saved"] or not c["review_passed"]]
    failed_review = [c for c in chapters if c["body_saved"] and not c["review_passed"]]
    unverified = [c for c in chapters if c["body_saved"] and c["review_passed"] and not c["platform_verified"]]
    if status == "running":
        return {"decision": "wait", "reason": "本次运行仍在进行中，只读核验即可",
                "actions": [{"id": "refresh", "label": "刷新状态", "enabled": True}]}
    if mode == "draft_only":
        if not chapters:
            return {"decision": "retry", "reason": "本次运行没有记录到目标章节",
                    "actions": [{"id": "retry", "label": "重新运行（只存稿）", "enabled": True}]}
        if failed_review:
            return {"decision": "manual", "reason": "有章节未通过审查，需人工修订后重跑；已通过章节不会重写",
                    "actions": [{"id": "open_chapters", "label": "查看待修订章节", "enabled": True},
                                {"id": "retry", "label": "重跑未完成章节", "enabled": True}]}
        if pending:
            return {"decision": "retry", "reason": "仍有章节未保存，可重跑补齐（有界重试）",
                    "actions": [{"id": "retry", "label": "重跑未完成章节", "enabled": True}]}
        return {"decision": "complete", "reason": "本次计划章节均已在本机保存并通过审查",
                "actions": [{"id": "open_chapters", "label": "查看正文", "enabled": True}]}
    intent = bool(record.get("queued_before_publish")) or record.get("publish_exit_code") is not None
    unknown = str(record.get("remote_state") or "") in {"unknown"} or bool(record.get("reconcile_required"))
    if unknown or (intent and record.get("publish_exit_code") not in (0, None)):
        return {"decision": "verify_only", "reason": "已有远端投递意图或结果未知，只做只读核验，不重复提交",
                "actions": [{"id": "verify_remote", "label": "只读核验平台章节", "enabled": True}]}
    if unverified and not intent:
        return {"decision": "retry", "reason": "从未提交且绑定版本未变，可有界重试一次",
                "actions": [{"id": "retry", "label": "重试本次投递", "enabled": True}]}
    if unverified and intent:
        return {"decision": "wait", "reason": "章节已入队或已投递，等待平台回执后再判定",
                "actions": [{"id": "refresh", "label": "刷新状态", "enabled": True}]}
    if chapters and all(c["platform_verified"] for c in chapters):
        return {"decision": "complete", "reason": "平台已核验全部目标章节",
                "actions": [{"id": "open_chapters", "label": "查看章节", "enabled": True}]}
    return {"decision": "manual", "reason": "状态存在歧义（版本、页面或回执不一致），需人工确认",
            "actions": [{"id": "open_chapters", "label": "查看章节与回执", "enabled": True},
                        {"id": "verify_remote", "label": "只读核验平台", "enabled": True}]}


def project_run(job_id: str, job: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """把一次运行记录投影成页面可渲染的只读结构。"""
    record = load_run(job_id, run_id)
    mode = _mode_of(record)
    project = Path(str(record.get("project") or job.get("project") or ""))
    book = str(record.get("book") or job.get("book") or "")
    account = str(record.get("account") or job.get("account") or "")
    targets = _target_ids(record)
    files = _chapter_files(project) if project else {}
    try:
        receipts = writer_runner.reviewed_chapters(project) if project and project.is_dir() else {}
    except Exception:  # noqa: BLE001 - 回执损坏时按“未审查”展示，不猜
        receipts = {}
    published: List[int] = []
    queued: List[int] = []
    if mode != "draft_only" and book:
        try:
            published = list(scheduler._published_ids(book, account or None))
        except Exception:  # noqa: BLE001
            published = []
        try:
            queued = list(scheduler._queue_ids(book))
        except Exception:  # noqa: BLE001
            queued = []
    draft_entries = {}
    cycle = record.get("cycle") if isinstance(record.get("cycle"), dict) else {}
    for entry in cycle.get("draft_chapters") or []:
        if isinstance(entry, dict) and entry.get("chapter_id"):
            try:
                draft_entries[int(entry["chapter_id"])] = entry
            except (TypeError, ValueError):
                continue
    chapters: List[Dict[str, Any]] = []
    for chapter in targets:
        receipt = receipts.get(chapter) if isinstance(receipts, dict) else None
        body = files.get(chapter)
        words = _body_words(body) if body is not None else None
        entry = draft_entries.get(chapter, {})
        review_decision = entry.get("review_decision")
        if not review_decision and isinstance(receipt, dict):
            review = receipt.get("review")
            if isinstance(review, dict):
                review_decision = review.get("review_decision")
        state = "pending"
        if chapter in published:
            state = "published"
        elif chapter in queued:
            state = "queued"
        elif receipt and body is not None:
            state = "reviewed"
        elif body is not None:
            state = "saved_only"
        chapters.append({
            "chapter_id": chapter,
            "body_saved": body is not None,
            "review_passed": bool(receipt) and body is not None,
            "platform_verified": chapter in published,
            "queued": chapter in queued,
            "state": state,
            "words": words if words is not None else entry.get("words"),
            "updated_at": (receipt or {}).get("reviewed_at") or entry.get("updated_at") or record.get("finished_at"),
            "sha256": entry.get("sha256"),
            "review_decision": review_decision if isinstance(review_decision, str) else None,
            "issue": _redact(entry.get("issue")),
        })
    costs_block = _cost_block(job, record, project) if project else {"state": "unknown", "reason": "缺少项目路径"}
    tally = {
        "target": len(chapters),
        "saved": sum(1 for c in chapters if c["body_saved"]),
        "reviewed": sum(1 for c in chapters if c["review_passed"]),
        "published": sum(1 for c in chapters if c["platform_verified"]),
        "pending": sum(1 for c in chapters if not c["review_passed"]),
        "words": sum(int(c["words"] or 0) for c in chapters),
    }
    decision = _actions(job, record, chapters, published)
    return {
        "run_id": _safe_run_id(run_id),
        "job_id": job_id,
        "publication_mode": mode,
        "remote_state": record.get("remote_state") or scheduler.remote_state({"publication_mode": mode}),
        "verification": record.get("verification"),
        "status": record.get("status"),
        "slot": _slot_line(record, job),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "tally": tally,
        "chapters": chapters,
        "costs": costs_block,
        "last_event": _last_event(record),
        "decision": decision["decision"],
        "decision_reason": decision["reason"],
        "available_actions": decision["actions"],
    }
