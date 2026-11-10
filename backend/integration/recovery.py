"""Explicit recovery for a serial daily job whose cycle stopped.

The only repair this module performs is the one that is provably safe: a
journal in ``preparing`` / ``blocked_before_submit`` without ``submitted_at``
means the 提交 button was never clicked (``publish.py`` writes
``state="submitting"`` immediately *before* the click), so the same chapter
may be retried without risking a duplicate publication.

Anything that might already have reached the platform goes only to the existing
read-only reconciler. The coordinator may dispatch that check automatically;
it cannot re-arm a submit or reset a verification window or recovery budget.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from . import bridge, scheduler


RETRY_STATES = {"preparing", "blocked_before_submit"}
SUBMITTED_STATES = {"submitting", "unconfirmed", "platform_confirmed"}


def _job(document: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    job = document.get("jobs", {}).get(job_id)
    if not isinstance(job, dict):
        raise ValueError(f"任务不存在：{job_id}")
    return job


def _queue_entry(job: Dict[str, Any], chapter: int):
    """Return (queue file, journal data) for one queued chapter, if any."""
    from fanqie_auto_publish.publication_safety import journal_path, read_json_strict
    _, _, folder = bridge.find_queue_book(job["book"])
    queued = bridge.queued_chapters(folder)
    source = queued.get(chapter)
    if source is None:
        return None, None
    path = journal_path(source)
    if not path.exists():
        return source, None
    data = read_json_strict(path)
    if not isinstance(data, dict):
        raise ValueError('提交记录格式损坏，禁止按不存在恢复')
    return source, data


def inspect(job_id: str) -> Dict[str, Any]:
    """Read-only diagnosis of a stopped serial cycle."""
    document = scheduler.load_scheduler()
    job = _job(document, job_id)
    cycle = job.get("cycle") if isinstance(job.get("cycle"), dict) else None
    report: Dict[str, Any] = {
        "job_id": job_id,
        "enabled": job.get("enabled"),
        "last_status": job.get("last_status"),
        "cycle_status": (cycle or {}).get("status"),
        "stage": (cycle or {}).get("stage"),
    }
    if not cycle:
        report.update(status="no_cycle", detail="任务还没有创建过批次，无需恢复")
        return report
    if cycle.get("status") == "success":
        report.update(status="nothing_to_do", detail="当前批次已完成，无需恢复")
        return report
    recovery = cycle.get("recovery") if isinstance(cycle.get("recovery"), dict) else {}
    chapter = recovery.get("chapter_id") or cycle.get("current_chapter")
    report.update(
        chapter_id=chapter,
        mode=recovery.get("mode"),
        automatic_retry=recovery.get("automatic_retry"),
        message=recovery.get("message"),
    )
    if not isinstance(chapter, int) or chapter <= 0:
        report.update(status="no_chapter", detail="批次未记录当前章节，无法自动恢复")
        return report
    source, entry = _queue_entry(job, chapter)
    if source is None:
        report.update(status="not_queued", detail="该章不在待发队列中（可能已归档），请只读核对")
        return report
    state = (entry or {}).get("state")
    report.update(queue_file=source.name, journal_state=state,
                  submitted_at=(entry or {}).get("submitted_at"))
    if entry is None:
        # No journal for this queued file means publish.py never started it:
        # it writes the journal before any submit click. This also covers a
        # chapter re-queued under a new file name after an identity fix.
        report.update(status="retry_safe",
                      detail="该章尚无提交记录（journal 不存在），可安全重试")
        return report
    from fanqie_auto_publish.publication_safety import requires_reconciliation
    if requires_reconciliation(entry):
        report.update(status="needs_readonly_reconciliation",
                      detail="journal 表明可能已经提交，禁止重试；请先只读核对平台")
        return report
    if state not in RETRY_STATES:
        report.update(status="unknown", detail="journal 状态无法判定，自动挂起并保留证据")
        return report
    from . import serial_delivery
    reason = serial_delivery.recoverable_before_submit(job, chapter)
    if reason is None:
        report.update(status="identity_mismatch",
                      detail="journal 与当前队列/回执不一致，自动挂起且不覆盖证据")
        return report
    report.update(status="retry_safe",
                  detail="journal 证明提交按钮从未点击，可安全重试同一章草稿")
    return report


def recover(job_id: str, apply: bool = False, automatic: bool = False) -> Dict[str, Any]:
    if apply:
        from . import writer_runner
        with writer_runner.file_lock(bridge.RUNTIME_ROOT / 'scheduler-execution.lock'):
            with bridge.runtime_lock('recovery-' + job_id):
                return _recover_locked(job_id, automatic=automatic)
    return _recover_locked(job_id, apply=False, automatic=automatic)


def _recover_locked(job_id, apply=True, automatic=False):
    """Diagnose, then (with apply=True) put the batch back to a retryable state."""
    report = inspect(job_id)
    readonly = report.get('status') == 'needs_readonly_reconciliation'
    if report.get("status") not in {"retry_safe", 'needs_readonly_reconciliation'} or not apply:
        report["applied"] = False
        return report

    chapter = int(report["chapter_id"])
    with scheduler.config_transaction() as document:
        job = _job(document, job_id)
        cycle = job.get("cycle")
        if not isinstance(cycle, dict):
            raise ValueError("批次已不存在，请重新读取")
        if cycle.get("status") == "running":
            raise ValueError("批次正在运行，拒绝并发恢复")
        previous = cycle.get("recovery") if isinstance(cycle.get("recovery"), dict) else {}
        if automatic and (not document.get('settings',{}).get('auto_schedule') or
                not job.get('enabled',True) or cycle.get('status')!='failed'):
            return {**report,'applied':False,'status':'automatic_recovery_not_applicable'}
        if automatic and (not readonly or previous.get('automatic_retry') or
                cycle.get('automatic_reconciliation_chapter')==chapter or
                previous.get('failure_kind') in {'auth','authentication','executor_stop','evidence_corrupt',
                    'configuration','configuration_or_access'}):
            return {**report,'applied':False,'status':'automatic_recovery_not_applicable'}
        if readonly:
            from datetime import datetime
            now = scheduler._now_for_job(job)
            since = previous.get('first_unknown_at') or report.get('submitted_at') or now.isoformat()
            stamp = datetime.fromisoformat(since)
            if stamp.tzinfo is None or stamp > now:
                raise ValueError('核验时间记录无效，自动挂起并保留证据')
            if (now-stamp).total_seconds() >= 86400:
                return {**report,'applied':False,'status':'verification_window_expired'}
        cycle.update(status="continuing", stage="publish_started" if readonly else "publication_retry", current_chapter=chapter)
        if readonly:
            cycle.setdefault('publish_attempt', {'chapter_id': chapter})
        else:
            cycle.pop("publish_attempt", None)
        cycle["recovery"] = {
            "chapter_id": chapter,
            "attempts": previous.get('attempts', 0),
            "automatic_retry": readonly,
            "mode": "read_only_reconciliation" if readonly else "pre_submit_retry",
            "message": "平台可能已有本章，自动只读核验，禁止重复提交" if readonly else "已确认本章尚未提交，等待原执行器重试",
            "publication_attempts": previous.get("publication_attempts", 0),
            "verification_attempts": previous.get('verification_attempts',0),
        }
        if readonly:
            cycle['recovery'].update(first_unknown_at=since,next_retry_at=now.isoformat())
            if automatic:cycle['automatic_reconciliation_chapter']=chapter
        job.update(cycle=cycle, last_status="continuing",
                   last_message="等待只读核验本章平台状态" if readonly else "已确认本章尚未提交，等待重试")
    report.update(applied=True, status="recovered",
                  detail="已恢复为 continuing；下一步只读核验本章" if readonly else "已恢复为 continuing；常驻协调器会在下一次轮询时重试本章")
    return report


def reconcile_waiting(document):
    """Automatically dispatch unambiguous read-only checks, once per chapter.

    Never re-arm a submit, reset a recovery/fee budget, repair conflicting
    identities, or override a deliberate E/platform stop.
    """
    if not document.get('settings',{}).get('auto_schedule'):
        return []
    results=[]
    for identity,job in document.get('jobs',{}).items():
        if not isinstance(job,dict):continue
        cycle=job.get('cycle') or {}
        if not isinstance(cycle,dict):continue
        # Local completion / ten-chapter delivery owns its separate persisted
        # recovery. The legacy one-chapter reconciler must not rewrite it.
        if cycle.get('local_only'):continue
        if (job.get('delivery_mode')!='serial' or not job.get('enabled',True)
                or cycle.get('status')!='failed' or (cycle.get('recovery') or {}).get('automatic_retry')
                or cycle.get('automatic_reconciliation_chapter')==cycle.get('current_chapter')):
            continue
        try:
            result=recover(identity,apply=True,automatic=True)
            if result.get('applied'):results.append(result)
        except (ValueError,RuntimeError,OSError,KeyError,TypeError):
            # Corrupt/mismatched state remains a blocker for this book only.
            continue
    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="日更批次安全恢复（只允许重试确定未提交的章节）")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--apply", action="store_true", help="执行恢复；默认只做只读诊断")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)
    try:
        result = recover(args.job_id, apply=args.apply)
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        result = {"job_id": args.job_id, "status": "error", "applied": False,
                  "detail": str(exc)[:2000]}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"恢复失败：{result['detail']}")
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"状态：{result.get('status')}")
        print(f"说明：{result.get('detail', '')}")
        if result.get("applied"):
            print("已执行恢复。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
