"""Publish the frozen 51-100 local-completion cycle in five verified groups."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import uuid

from . import bridge, length_policy, scheduler as s, writer_runner as writer


GROUPS = ((51, 60), (61, 70), (71, 80), (81, 90), (91, 100))
TARGET_IDS = list(range(52, 101))
MINIMUM_CHARS = 6000
BACKOFF_SECONDS = (60, 300, 900)
UNKNOWN_MAX_SECONDS = 24 * 60 * 60
_POST_SAVE_KEYS = ("shared_memory", "entities", "rag_indexed", "continuity_written")
_PRE_SUBMIT_STAGES = {
    "queue_parse", "prepare", "chapter_parse", "preparing_journal", "existing_scan",
    "open_editor", "fill", "settings", "editor_recheck", "plan_recheck", "queue_digest", "deadline",
}
_TRANSIENT_ERRORS = {
    "timeout", "timeouterror", "timeoutexception", "playwrighttimeouterror", "readtimeout",
    "connecttimeout", "connectionerror", "clientconnectionerror", "clientconnectorerror", "connecterror",
}


class _DeliveryStop(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now(job: dict) -> datetime:
    value = s._now_for_job(job)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _DeliveryStop("invalid_scheduler_time")
    return value


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _group_key(group: tuple[int, int]) -> str:
    return f"{group[0]}-{group[1]}"


def _same_group(value: dict, group: tuple[int, int]) -> bool:
    return value.get("group_start") == group[0] and value.get("group_end") == group[1]


def _sources(project: Path) -> dict[int, tuple[Path, str, str]]:
    root = (project / "正文").resolve(strict=True)
    result = {}
    for source, chapter, title, markdown in bridge.iter_source_chapters(project):
        resolved = source.resolve(strict=True)
        if source.is_symlink() or root not in resolved.parents:
            raise _DeliveryStop("unsafe_source_path")
        if chapter in result:
            raise _DeliveryStop("duplicate_source_chapter")
        result[chapter] = (resolved, title, markdown)
    return result


def _sealed_51(job: dict, cycle: dict, project: Path) -> dict:
    try:
        from .local_completion import _read_sealed_record

        document = _read_sealed_record(job, cycle, project)
    except Exception:
        raise _DeliveryStop("sealed_51_evidence_invalid") from None
    receipt = document.get("qualified_receipt") if isinstance(document, dict) else None
    if not isinstance(receipt, dict):
        raise _DeliveryStop("sealed_51_receipt_missing")
    return receipt


def _receipt_matches(receipt: object, source: Path) -> bool:
    if not isinstance(receipt, dict):
        return False
    try:
        resolved = source.resolve(strict=True)
        destination = Path(receipt.get("destination", "")).resolve(strict=True)
        source_hash = bridge.digest_file(resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return destination == resolved and receipt.get("sha256") == source_hash


def _memory_complete(receipt: dict) -> bool:
    post = receipt.get("post_save")
    return (
        isinstance(post, dict)
        and isinstance(post.get("shared_memory"), dict)
        and post["shared_memory"].get("status") == "synced"
        and isinstance(post.get("entities"), dict)
        and post["entities"].get("status") == "synced"
        and post.get("rag_indexed") is True
        and post.get("continuity_written") is True
    )


def _verified_archive_ids(job: dict, sources: dict[int, tuple[Path, str, str]]) -> set[int]:
    folder = bridge.UPLOADED_ROOT / bridge.safe_dir_name(job["book"])
    if folder.is_symlink():
        raise _DeliveryStop("unsafe_archive_path")
    archived = bridge.archived_chapters(folder)
    verified = set()
    for chapter in range(51, 101):
        path = archived.get(chapter)
        if path is None:
            continue
        source_data = sources.get(chapter)
        if source_data is None:
            raise _DeliveryStop("archive_source_missing")
        source, _, markdown = source_data
        receipt = bridge.valid_receipt(path, job["book"], chapter, job["account"])
        if not receipt:
            raise _DeliveryStop("archive_receipt_invalid")
        expected_hash = bridge.sha256_text(bridge.markdown_to_plaintext(markdown, chapter))
        if bridge.digest_file(path) != expected_hash:
            raise _DeliveryStop("archive_body_mismatch")
        if receipt.get("file_sha256") != expected_hash:
            raise _DeliveryStop("archive_receipt_hash_mismatch")
        verified.add(chapter)
    return verified


def _chapter_ready(chapter: int, sources: dict[int, tuple[Path, str, str]], receipts: dict,
                   sealed_receipt: dict | None, project: Path) -> bool:
    source_data = sources.get(chapter)
    if source_data is None:
        return False
    source, _, markdown = source_data
    if chapter == 51:
        # The sealed record proves unchanged history, not publication authority.
        # Publication still requires the normal current-qualification reader.
        receipt = receipts.get(chapter,receipts.get(str(chapter)))
        if not isinstance(receipt,dict):raise _DeliveryStop('chapter_51_current_qualification_missing')
    else:
        receipt = receipts.get(chapter, receipts.get(str(chapter)))
    if not _receipt_matches(receipt, source) or not _memory_complete(receipt):
        return False
    try:
        minimum = max(MINIMUM_CHARS, length_policy.minimum(project, chapter))
        if length_policy.body_chars(markdown, chapter) < minimum:
            return False
    except (OSError, TypeError, ValueError):
        raise _DeliveryStop("length_policy_invalid") from None
    return True


def _manifest_guard(job: dict) -> None:
    manifest = bridge.load_manifest()
    safe_book = bridge.safe_dir_name(job["book"])
    item = manifest.get("books", {}).get(safe_book, {})
    if not item:
        return
    if not isinstance(item, dict):
        raise _DeliveryStop("manifest_identity_invalid")
    try:
        project_matches = Path(item.get("project_root", "")).resolve() == Path(job["project"]).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        project_matches = False
    if (item.get("display_name") != job["book"] or not project_matches
            or item.get("account") not in (None, "", job["account"])):
        raise _DeliveryStop("manifest_identity_conflict")


def _queue_snapshot(job: dict, group: tuple[int, int], sources: dict[int, tuple[Path, str, str]],
                    verified: set[int]) -> tuple[dict[int, Path], list[int], dict[int, dict]]:
    root = bridge.QUEUE_ROOT
    if root.is_dir() and any(path.is_file() for path in root.glob("*.txt")):
        raise _DeliveryStop("unassigned_queue_files")
    folder = root / bridge.safe_dir_name(job["book"])
    if folder.is_symlink():
        raise _DeliveryStop("unsafe_queue_path")
    queue = bridge.queued_chapters(folder)
    unknown = []
    journals = {}
    for chapter, path in queue.items():
        if not group[0] <= chapter <= group[1]:
            raise _DeliveryStop("queue_outside_active_group")
        if chapter in verified:
            raise _DeliveryStop("queued_and_archived_conflict")
        if path.is_symlink() or path.resolve().parent != folder.resolve():
            raise _DeliveryStop("unsafe_queue_path")
        source_data = sources.get(chapter)
        if source_data is None:
            raise _DeliveryStop("queue_source_missing")
        _, source_title, markdown = source_data
        title = bridge.parse_chapter_name(path.name)
        expected_hash = bridge.sha256_text(bridge.markdown_to_plaintext(markdown, chapter))
        if (not title or title[0] != chapter or title[1] != source_title
                or bridge.digest_file(path) != expected_hash):
            raise _DeliveryStop("queue_source_or_body_conflict")
        journal = bridge.journal_path(path)
        if not journal.exists():
            continue
        try:
            entry = bridge.read_json_strict(journal)
        except (OSError, ValueError, TypeError):
            raise _DeliveryStop("journal_unreadable") from None
        if not isinstance(entry, dict):
            raise _DeliveryStop("journal_invalid")
        if any(entry.get(key) != value for key, value in {
            "book": job["book"], "account": job["account"], "chapter_id": chapter,
            "file_sha256": bridge.digest_file(path),
        }.items()):
            raise _DeliveryStop("journal_identity_conflict")
        reason = str(entry.get("reason") or "")
        if reason == "platform_rejected_submission":
            raise _DeliveryStop("platform_rejected_submission")
        from fanqie_auto_publish.publication_safety import requires_reconciliation

        if requires_reconciliation(entry):
            unknown.append(chapter)
        elif entry.get("state") not in {"preparing", "blocked_before_submit"}:
            raise _DeliveryStop("journal_state_unrecognized")
        journals[chapter] = entry
    return queue, sorted(unknown), journals


def _alert(job_id: str, group: tuple[int, int], message: str, state: str) -> None:
    root = s.RUNS_ROOT.parent / "alerts"
    bridge.write_json_atomic(root / f"{bridge.safe_dir_name(job_id)}-group-{group[0]}-{group[1]}.json", {
        "job_id": job_id, "chapter_id": group[0], "state": state,
        "message": message, "updated_at": bridge.now_iso(),
    })


def _persist(job_id: str, cycle: dict, record: dict, *, group: tuple[int, int],
             delivery_status: str, stage: str, run_status: str, message: str,
             active: bool, recovery: dict | None = None, disable: bool = False) -> dict:
    prior = cycle.get("batch_delivery") if isinstance(cycle.get("batch_delivery"), dict) else {}
    delivery = dict(prior) if _same_group(prior, group) else {}
    delivery.update(group_start=group[0], group_end=group[1], status=delivery_status,
                    updated_at=bridge.now_iso())
    cycle["batch_delivery"] = delivery
    cycle["publication_batch_active"] = active
    if recovery is None:
        cycle.pop("batch_recovery", None)
    else:
        cycle["batch_recovery"] = recovery
    cycle.update(stage=stage)
    if run_status in {"waiting", "progress", "publishing"}:
        cycle["status"] = "continuing" if run_status in {"waiting","progress"} else "running"
    else:
        cycle["status"] = "failed"
    changes = {"cycle": cycle, "last_status": run_status, "last_message": message}
    if disable:
        changes.update(enabled=False, completion_review_required=True)
    s._update_run(job_id, changes)
    record.update(status=run_status, message=message, batch_delivery=dict(delivery),
                  completion_review_required=bool(disable), finished_at=bridge.now_iso())
    record["run_record"] = s._write_run_record(job_id, record)
    if disable:
        record["platform_completion_review"] = "required"
    return record


def _blocked(job_id: str, cycle: dict, record: dict, group: tuple[int, int], code: str,
             previous: dict | None = None) -> dict:
    old = previous if isinstance(previous, dict) else {}
    recovery = {
        "scope": "ten_chapter_publication", "group_start": group[0], "group_end": group[1],
        "mode": "blocked", "attempts": old.get("attempts", 0),
        "publication_attempts": old.get("publication_attempts", 0),
        "verification_attempts": old.get("verification_attempts", 0),
        "automatic_retry": False, "failure_code": code,
    }
    result = _persist(job_id, cycle, record, group=group, delivery_status="blocked", stage="group_blocked",
                      run_status="failed", message=f"十章发布批次已停止：{code}", active=True, recovery=recovery)
    _alert(job_id, group, f"十章发布批次已停止：{code}", "needs_attention")
    return result


def _wait(job_id: str, cycle: dict, record: dict, group: tuple[int, int], recovery: dict,
          message_code: str = "retry_wait") -> dict:
    recovery = dict(recovery)
    recovery["scope"] = "ten_chapter_publication"
    recovery["group_start"], recovery["group_end"] = group
    recovery["automatic_retry"] = True
    result = _persist(job_id, cycle, record, group=group, delivery_status="waiting",
                      stage="group_retry_wait", run_status="waiting",
                      message=f"十章发布批次等待安全恢复：{message_code}", active=True, recovery=recovery)
    return result


def _checkpoint(job_id: str, cycle: dict, record: dict, group: tuple[int, int], *,
                stage: str, status: str, invocation_id: str, recovery: dict | None) -> None:
    prior = cycle.get("batch_delivery") if isinstance(cycle.get("batch_delivery"), dict) else {}
    delivery = dict(prior) if _same_group(prior, group) else {}
    delivery.update(group_start=group[0], group_end=group[1], status=status,
                    invocation_id=invocation_id, updated_at=bridge.now_iso())
    cycle["batch_delivery"] = delivery
    cycle["publication_batch_active"] = True
    cycle["stage"] = stage
    cycle["status"] = "running"
    if recovery is not None:
        cycle["batch_recovery"] = recovery
    s._update_run(job_id, {"cycle": cycle, "last_status": "running", "last_message": ""})
    record.update(status="publishing" if stage == "group_publish_started" else "reconciling",
                  batch_delivery=dict(delivery))
    record["run_record"] = s._write_run_record(job_id, record)


def _report(bridge_module, job: dict, invocation_id=None) -> dict:
    try:
        value = bridge_module.latest_publish_report(job["book"], job["account"])
    except Exception:
        return {}
    if not isinstance(value,dict):return {}
    if invocation_id is not None and value.get('invocation_id')!=invocation_id:
        raise _DeliveryStop('report_invocation_conflict')
    return value


def _rejected(report: dict, journals: dict[int, dict]) -> bool:
    if report.get("reason") == "platform_rejected_submission":
        return True
    return any(entry.get("reason") == "platform_rejected_submission" for entry in journals.values())


def _transient_pre_submit(report: dict, journals: dict[int, dict]) -> bool:
    if _rejected(report, journals):
        return False
    failure = report.get("failure") if isinstance(report.get("failure"), dict) else {}
    if report.get("publisher_started") is False:
        return (failure.get("retryable") is True
                and failure.get("failure_kind") not in {"authentication", "configuration_or_access", "executor_stop"})
    stage = str(report.get("error_stage") or "")
    error_type = str(report.get("error_type") or "").casefold()
    if stage not in _PRE_SUBMIT_STAGES or error_type not in _TRANSIENT_ERRORS:
        return False
    return all(not entry.get("submitted_at") and entry.get("state") == "blocked_before_submit"
               for entry in journals.values() if entry.get("reason") == "automation_error")


def _verification_recovery(group: tuple[int, int], prior: dict, unknown: list[int], now: datetime) -> dict:
    first = prior.get("first_unknown_at") or now.isoformat()
    first_at = _timestamp(first)
    attempts = prior.get("verification_attempts", 0)
    if type(attempts) is not int or attempts < 0 or first_at is None:
        raise _DeliveryStop("batch_recovery_state_invalid")
    elapsed = (now - first_at).total_seconds()
    allowed = elapsed < UNKNOWN_MAX_SECONDS
    delay = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS) - 1)] if attempts < len(BACKOFF_SECONDS) else 1800
    return {
        "scope": "ten_chapter_publication", "group_start": group[0], "group_end": group[1],
        "mode": "read_only_reconciliation", "attempts": prior.get("attempts", 0),
        "publication_attempts": prior.get("publication_attempts", 0),
        "verification_attempts": attempts, "first_unknown_at": first,
        "unknown_chapters": sorted(unknown), "automatic_retry": allowed,
        "next_retry_at": (now + timedelta(seconds=delay)).isoformat() if allowed else None,
    }


def _schedule_publication_retry(job: dict, group: tuple[int, int], prior: dict, report: dict,
                                now: datetime) -> dict | None:
    failure = report.get("failure") if isinstance(report.get("failure"), dict) else {}
    publication_attempts = prior.get("publication_attempts", 0)
    attempts = prior.get("attempts", 0)
    if type(publication_attempts) is not int or publication_attempts < 0 or type(attempts) is not int or attempts < 0:
        raise _DeliveryStop("batch_recovery_state_invalid")
    next_retry = failure.get("next_retry_at") if failure.get("failure_kind") in {"free_pool_wait", "recovery_cooldown"} else None
    waiting=next_retry is not None
    publication_attempts += 0 if waiting else 1
    attempts += 0 if waiting else 1
    extension = None
    if next_retry is None:
        if publication_attempts <= len(BACKOFF_SECONDS):
            next_retry = (now + timedelta(seconds=BACKOFF_SECONDS[publication_attempts - 1])).isoformat()
        else:
            from .retry_budget import extension as retry_extension

            extension = retry_extension(job, now)
            if extension:
                next_retry = extension.get("next_retry_at")
    if _timestamp(next_retry) is None:
        return None
    result = {
        "scope": "ten_chapter_publication", "group_start": group[0], "group_end": group[1],
        "mode": "pre_submit_retry", "attempts": attempts,
        "publication_attempts": publication_attempts,
        "verification_attempts": prior.get("verification_attempts", 0),
        "automatic_retry": True, "next_retry_at": next_retry,
    }
    if extension:
        result["extra_budget"] = extension
    return result


def _finish_group(job_id: str, job: dict, cycle: dict, record: dict, group: tuple[int, int],
                  sources: dict[int, tuple[Path, str, str]]) -> dict:
    verified = _verified_archive_ids(job, sources)
    if not set(range(group[0], group[1] + 1)).issubset(verified):
        raise _DeliveryStop("group_archive_incomplete")
    all_target = set(range(51, 101)).issubset(verified)
    if all_target:
        cycle.update(status="published_complete", stage="published_complete", current_chapter=None,
                     completion_review_required=True)
        cycle["publication_batch_active"] = False
        cycle.pop("batch_recovery", None)
        delivery = cycle.get("batch_delivery") if isinstance(cycle.get("batch_delivery"), dict) else {}
        cycle["batch_delivery"] = {**delivery, "group_start": group[0], "group_end": group[1],
                                   "status": "published_complete", "updated_at": bridge.now_iso()}
        job["enabled"] = False
        s._update_run(job_id, {"cycle": cycle, "enabled": False, "last_status": "published_complete",
                               "last_message": "第51至100章均有平台回执及正文哈希核验；完结审核仍待确认",
                               "completion_review_required": True})
        record.update(status="published_complete", published_ids=list(range(51, 101)),
                      completion_review_required=True, platform_completion_review="required",
                      finished_at=bridge.now_iso(), batch_delivery=dict(cycle["batch_delivery"]))
        record["run_record"] = s._write_run_record(job_id, record)
        return record
    result = _persist(job_id, cycle, record, group=group, delivery_status="group_verified",
                      stage="group_verified", run_status="progress",
                      message=f"第{group[0]}至{group[1]}章逐章回执及正文哈希已核验", active=False)
    record["published_ids"] = list(range(group[0], group[1] + 1))
    record["run_record"] = s._write_run_record(job_id, record)
    return result


def _validate_recovery(cycle: dict, group: tuple[int, int]) -> dict:
    value = cycle.get("batch_recovery")
    if value is None:
        return {}
    if (not isinstance(value, dict) or value.get("scope") != "ten_chapter_publication"
            or not _same_group(value, group)):
        raise _DeliveryStop("batch_recovery_scope_conflict")
    for key in ("attempts", "publication_attempts", "verification_attempts"):
        number = value.get(key, 0)
        if type(number) is not int or number < 0:
            raise _DeliveryStop("batch_recovery_state_invalid")
    return value


def _retry_due(recovery: dict, now: datetime) -> bool:
    retry_at = _timestamp(recovery.get("next_retry_at"))
    if retry_at is None:
        raise _DeliveryStop("batch_retry_time_invalid")
    return retry_at <= now


def _handle_reconciliation(job_id: str, job: dict, cycle: dict, record: dict, group: tuple[int, int],
                           sources: dict[int, tuple[Path, str, str]], prior: dict,
                           unknown: list[int], now: datetime) -> dict:
    if prior.get('first_unknown_at'):
        first=_timestamp(prior['first_unknown_at'])
        if first is None or first>now:
            return _blocked(job_id,cycle,record,group,'invalid_verification_window',prior)
        if (now-first).total_seconds()>=UNKNOWN_MAX_SECONDS:
            return _blocked(job_id,cycle,record,group,'readonly_reconciliation_window_expired',prior)
    if prior and prior.get("mode") == "read_only_reconciliation" and not _retry_due(prior, now):
        return _wait(job_id, cycle, record, group, prior, "readonly_verification_backoff")
    if prior and prior.get("automatic_retry") is False:
        return _blocked(job_id, cycle, record, group, str(prior.get("failure_code") or "reconciliation_stopped"), prior)
    invocation_id = uuid.uuid4().hex
    recovery = dict(prior) if prior else _verification_recovery(group, {}, unknown, now)
    recovery.update(mode="read_only_reconciliation", unknown_chapters=sorted(unknown), automatic_retry=True)
    if not recovery.get("first_unknown_at"):
        recovery["first_unknown_at"] = now.isoformat()
    _checkpoint(job_id, cycle, record, group, stage="group_reconciliation", status="reconciling",
                invocation_id=invocation_id, recovery=recovery)
    code = bridge.run_publish(job["book"], account=job["account"], project=Path(job["project"]),
                              reconcile_only=True, reconcile_chapters=set(unknown),
                              invocation_id=invocation_id)
    report = _report(bridge, job,invocation_id)
    verified = _verified_archive_ids(job, sources)
    if set(range(group[0], group[1] + 1)).issubset(verified):
        return _finish_group(job_id, job, cycle, record, group, sources)
    queue, remaining_unknown, journals = _queue_snapshot(job, group, sources, verified)
    if _rejected(report, journals):
        return _blocked(job_id, cycle, record, group, "platform_rejected_submission", recovery)
    now = _now(job)
    recovery["verification_attempts"] = recovery.get("verification_attempts", 0) + 1
    first_at = _timestamp(recovery.get("first_unknown_at"))
    if first_at is None or (now - first_at).total_seconds() >= UNKNOWN_MAX_SECONDS:
        return _blocked(job_id, cycle, record, group, "readonly_reconciliation_window_expired", recovery)
    if remaining_unknown:
        recovery = _verification_recovery(group, recovery, remaining_unknown, now)
        return _wait(job_id, cycle, record, group, recovery, "readonly_verification_pending")
    # Reconciliation may have confirmed a platform draft. It never submits in
    # this invocation; the next attempt remains behind the persisted cooldown.
    if any(entry.get("reason") == "reconciled_platform_draft" for entry in journals.values()):
        recovery.update(mode="pre_submit_retry", automatic_retry=True,
                        next_retry_at=(now + timedelta(seconds=BACKOFF_SECONDS[0])).isoformat(),
                        unknown_chapters=[])
        return _wait(job_id, cycle, record, group, recovery, "platform_draft_confirmed_readonly")
    # A successful read-only call can archive the uncertain prefix while later
    # chapters have no attempt record. Resume only after a delay.
    if code == 0 and set(queue).issubset(set(range(group[0], group[1] + 1))):
        recovery.update(mode="pre_submit_retry", automatic_retry=True,
                        next_retry_at=(now + timedelta(seconds=BACKOFF_SECONDS[0])).isoformat(),
                        unknown_chapters=[])
        return _wait(job_id, cycle, record, group, recovery, "readonly_verification_complete")
    return _blocked(job_id, cycle, record, group, "reconciliation_evidence_incomplete", recovery)


def maybe_publish(job_id: str, job: dict, cycle: dict, record: dict):
    """Publish one ready ten-chapter group; return None while local writing can proceed."""
    if cycle.get("publish_every") != 10:
        return None
    group: tuple[int, int] = GROUPS[0]
    try:
        if (cycle.get("local_only") is not True or job.get("delivery_mode") != "serial"
                or cycle.get("target_ids") != TARGET_IDS):
            raise _DeliveryStop("local_cycle_scope_invalid")
        project = Path(job["project"]).expanduser().resolve(strict=True)
        sources = _sources(project)
        verified = _verified_archive_ids(job, sources)
        prior_delivery=cycle.get('batch_delivery') or {}
        if cycle.get('publication_batch_active') and isinstance(prior_delivery,dict):
            prior_group=(prior_delivery.get('group_start'),prior_delivery.get('group_end'))
            if prior_group in GROUPS and set(range(prior_group[0],prior_group[1]+1)).issubset(verified):
                # A process may die after the archive commit but before its
                # group checkpoint. Reconcile that group, never submit it again.
                return _finish_group(job_id,job,cycle,record,prior_group,sources)
        group = next((candidate for candidate in GROUPS
                      if not set(range(candidate[0], candidate[1] + 1)).issubset(verified)), None)
        if group is None:
            group = GROUPS[-1]
            return _finish_group(job_id, job, cycle, record, group, sources)

        recovery = _validate_recovery(cycle, group)
        receipts = writer.reviewed_chapters(project)
        sealed_receipt = None
        if group[0] == 51 and 51 not in verified:
            sealed_receipt = _sealed_51(job, cycle, project)
        ready = all(chapter in verified or _chapter_ready(chapter, sources, receipts, sealed_receipt, project)
                    for chapter in range(group[0], group[1] + 1))
        if not ready:
            if recovery or cycle.get("publication_batch_active"):
                raise _DeliveryStop("active_group_readiness_lost")
            return None

        _manifest_guard(job)
        queue, unknown, journals = _queue_snapshot(job, group, sources, verified)
        now = _now(job)
        if recovery.get("mode") == "blocked" or recovery.get("automatic_retry") is False:
            return _blocked(job_id, cycle, record, group,
                            str(recovery.get("failure_code") or "batch_recovery_stopped"), recovery)
        if recovery.get("mode") == "read_only_reconciliation":
            if unknown:
                return _handle_reconciliation(job_id, job, cycle, record, group, sources, recovery, unknown, now)
            if not set(range(group[0], group[1] + 1)).issubset(verified):
                if recovery.get("next_retry_at") and not _retry_due(recovery, now):
                    return _wait(job_id, cycle, record, group, recovery, "readonly_recovery_wait")
                # Unknown state disappeared without matching archive or draft evidence.
                raise _DeliveryStop("reconciliation_state_disappeared")
        elif unknown:
            return _handle_reconciliation(job_id, job, cycle, record, group, sources, recovery, unknown, now)

        if recovery.get("mode") == "pre_submit_retry" and not _retry_due(recovery, now):
            return _wait(job_id, cycle, record, group, recovery, "pre_submit_backoff")

        # Pre-existing non-51 submit journals require a durable batch checkpoint
        # proving this is the same previously classified safe retry.
        for chapter, entry in journals.items():
            if chapter == 51:
                if entry.get("submitted_at") or entry.get("reason") in {
                    "platform_rejected_submission", "existing_chapter_requires_reconciliation",
                }:
                    raise _DeliveryStop("chapter_51_journal_not_safe_draft")
                continue
            if recovery.get("mode") != "pre_submit_retry":
                raise _DeliveryStop("unclassified_pre_submit_journal")

        remaining = sorted(set(range(group[0], group[1] + 1)) - verified)
        preview = bridge.stage_project(project, book_name=job["book"], selected_ids=set(remaining), dry_run=True)
        if preview.get("conflicts") or preview.get("invalid"):
            raise _DeliveryStop("stage_conflict_or_invalid")
        staged = bridge.stage_project(project, book_name=job["book"], selected_ids=set(remaining))
        if staged.get("conflicts") or staged.get("invalid"):
            raise _DeliveryStop("stage_conflict_or_invalid")
        queue, unknown, journals = _queue_snapshot(job, group, sources, verified)
        if unknown:
            return _handle_reconciliation(job_id, job, cycle, record, group, sources, recovery, unknown, _now(job))
        if set(queue) != set(remaining):
            raise _DeliveryStop("queue_not_exact_group_remainder")
        bridge.validate_queue_origin(job["book"], project=project, account=job["account"])

        invocation_id = uuid.uuid4().hex
        _checkpoint(job_id, cycle, record, group, stage="group_publish_started", status="publishing",
                    invocation_id=invocation_id, recovery=recovery or None)
        code = bridge.run_publish(job["book"], count=len(remaining), volume=job.get("volume"),
                                  account=job["account"], project=project, invocation_id=invocation_id)
        report = _report(bridge, job,invocation_id)
        verified = _verified_archive_ids(job, sources)
        if set(range(group[0], group[1] + 1)).issubset(verified):
            return _finish_group(job_id, job, cycle, record, group, sources)

        queue, unknown, journals = _queue_snapshot(job, group, sources, verified)
        if unknown:
            prior = dict(recovery)
            first = prior.get("first_unknown_at") or _now(job).isoformat()
            prior["first_unknown_at"] = first
            if prior.get("mode") != "read_only_reconciliation":
                prior["verification_attempts"] = 0
            pending = _verification_recovery(group, prior, unknown, _now(job))
            return _wait(job_id, cycle, record, group, pending, "submission_result_unknown")
        if _rejected(report, journals):
            return _blocked(job_id, cycle, record, group, "platform_rejected_submission", recovery)
        if code != 0 and _transient_pre_submit(report, journals):
            pending = _schedule_publication_retry(job, group, recovery, report, _now(job))
            if pending is not None:
                return _wait(job_id, cycle, record, group, pending, "explicit_pre_submit_transient")
        raise _DeliveryStop("publish_not_fully_verified")
    except _DeliveryStop as exc:
        prior = cycle.get("batch_recovery") if isinstance(cycle.get("batch_recovery"), dict) else {}
        return _blocked(job_id, cycle, record, group, exc.code, prior)
    except Exception:
        prior = cycle.get("batch_recovery") if isinstance(cycle.get("batch_recovery"), dict) else {}
        return _blocked(job_id, cycle, record, group, "delivery_precondition_or_execution_error", prior)
