"""Bounded, local-only completion for a frozen serial delivery cycle."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import bridge, scheduler as s, writer_runner as writer


TARGET_IDS = tuple(range(52, 101))
WORD_COUNT = 6000
MAX_REVISIONS = 3
BACKOFF_SECONDS = (60, 300, 900)
_POST_SAVE_KEYS = ("shared_memory", "entities", "rag_indexed", "continuity_written")


class _LocalCompletionStop(RuntimeError):
    def __init__(self, message: str, failure_kind: str = "local_completion_conflict"):
        super().__init__(message)
        self.safe_message = message
        self.failure_kind = failure_kind
        self.retryable = False


def _post_save_complete(post_save: Any) -> bool:
    if not isinstance(post_save, dict):
        return False
    return (
        isinstance(post_save.get("shared_memory"), dict)
        and post_save["shared_memory"].get("status") == "synced"
        and isinstance(post_save.get("entities"), dict)
        and post_save["entities"].get("status") == "synced"
        and post_save.get("rag_indexed") is True
        and post_save.get("continuity_written") is True
    )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_cycle(job: Dict[str, Any], cycle: Dict[str, Any]) -> Path:
    if job.get("delivery_mode") != "serial":
        raise _LocalCompletionStop("本地完稿要求保留 serial delivery_mode", "local_cycle_invalid")
    if cycle.get("local_only") is not True:
        raise _LocalCompletionStop("批次未标记为 local_only，已停止", "local_cycle_invalid")
    targets = cycle.get("target_ids")
    if not isinstance(targets, list) or targets != list(TARGET_IDS):
        raise _LocalCompletionStop("本地完稿目标必须严格为第52至100章", "local_cycle_invalid")
    if type(cycle.get("word_count")) is not int or cycle["word_count"] != WORD_COUNT:
        raise _LocalCompletionStop("本地完稿字数目标无效", "local_cycle_invalid")
    if type(cycle.get("max_revisions")) is not int or cycle["max_revisions"] != MAX_REVISIONS:
        raise _LocalCompletionStop("本地完稿修改轮数无效", "local_cycle_invalid")
    try:
        project = Path(job["project"]).expanduser().resolve(strict=True)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        raise _LocalCompletionStop("本地完稿项目路径无效", "local_cycle_invalid") from None
    return project


def _read_sealed_record(job: Dict[str, Any], cycle: Dict[str, Any], project: Path) -> Dict[str, Any]:
    raw_path = cycle.get("local_sealed_record")
    try:
        path = Path(raw_path)
        if not path.is_absolute() or path.suffix.casefold() != ".json" or path.is_symlink():
            raise ValueError
        path = path.resolve(strict=True)
        if not path.is_file():
            raise ValueError
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
        raise _LocalCompletionStop("sealed51 JSON 不可读取或路径无效", "local_sealed_evidence") from None

    required = {
        "schema": 1,
        "project": str(project),
        "book": job.get("book"),
        "account": job.get("account"),
        "chapter": 51,
        "kind": "qualified_before_future_contract_change",
        "scope": "local_completed_evidence_only_not_publication_qualification",
    }
    if not isinstance(document, dict) or any(document.get(key) != value for key, value in required.items()):
        raise _LocalCompletionStop("sealed51 JSON 字段或用途范围不匹配", "local_sealed_evidence")
    if not isinstance(document.get("captured_at"), str) or not document["captured_at"].strip():
        raise _LocalCompletionStop("sealed51 缺少捕获时间", "local_sealed_evidence")

    try:
        source = Path(document["source"])
        if not source.is_absolute() or source.is_symlink():
            raise ValueError
        source = source.resolve(strict=True)
        body_root = (project / "正文").resolve(strict=True)
        if not _inside(source, body_root) or source.suffix.casefold() != ".md":
            raise ValueError
        chapter_paths = [p.resolve(strict=True) for p, number in writer._chapter_files(project) if number == 51]
        if len(chapter_paths) != 1 or chapter_paths[0] != source:
            raise ValueError
        source_bytes = source.read_bytes()
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        source_text = source_bytes.decode("utf-8-sig")
        body_sha = writer.body_digest(source_text)
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError, KeyError):
        raise _LocalCompletionStop("sealed51 正文路径、章节号或文件内容无效", "local_sealed_evidence") from None

    if document.get("source_sha256") != source_sha or document.get("body_sha256") != body_sha:
        raise _LocalCompletionStop("sealed51 正文哈希已变化，已停止本地完稿", "local_sealed_evidence")
    receipt = document.get("qualified_receipt")
    if not isinstance(receipt, dict):
        raise _LocalCompletionStop("sealed51 缺少原资格快照", "local_sealed_evidence")
    try:
        receipt_path = Path(receipt.get("destination", ""))
        receipt_matches = (
            receipt_path.is_absolute()
            and receipt_path.resolve(strict=True) == source
            and receipt.get("sha256") == source_sha
            and isinstance(receipt.get("review"), dict)
            and _post_save_complete(receipt.get("post_save"))
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        receipt_matches = False
    if not receipt_matches:
        raise _LocalCompletionStop("sealed51 原 receipt 与正文或完整后保存记忆不匹配", "local_sealed_evidence")
    # Deliberately do not re-evaluate the old receipt against today's creative contract.
    return document


def _chapter_paths(project: Path, chapter: int):
    return [path for path, number in writer._chapter_files(project) if number == chapter]


def _body_length(path: Path, chapter: int) -> int:
    from .length_policy import body_chars

    return body_chars(path.read_text(encoding="utf-8-sig"), chapter)


def _chapter_state(project: Path, chapter: int, receipts: Dict[int, Dict[str, Any]]) -> Tuple[str, Optional[Path], Optional[Dict[str, Any]], str]:
    try:
        paths = _chapter_paths(project, chapter)
    except (OSError, RuntimeError, TypeError, ValueError):
        return "conflict", None, None, "正文目录或章节文件状态无效"
    if not paths:
        return "missing", None, None, ""
    if len(paths) != 1:
        return "conflict", None, None, f"第{chapter}章存在多个正文文件，已停止以保护原文"
    source = paths[0]
    try:
        resolved = source.resolve(strict=True)
        body_root = (project / "正文").resolve(strict=True)
        if source.is_symlink() or not _inside(resolved, body_root):
            return "conflict", source, None, f"第{chapter}章正文路径无效，已停止"
        receipt = receipts.get(chapter)
        if not isinstance(receipt, dict):
            return "conflict", source, None, f"第{chapter}章已有正文但当前资格无效，已停止以保护原文"
        source_sha = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if (receipt.get("destination") != str(resolved) or receipt.get("sha256") != source_sha):
            return "conflict", source, receipt, f"第{chapter}章正文与当前资格回执不匹配，已停止以保护原文"
        if _body_length(resolved, chapter) < WORD_COUNT:
            return "conflict", source, receipt, f"第{chapter}章已有正文未达到6000字目标，已停止以保护原文"
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        return "conflict", source, None, f"第{chapter}章正文或资格回执无法安全核对"
    if _post_save_complete(receipt.get("post_save")):
        return "complete", resolved, receipt, ""
    return "repair", resolved, receipt, ""


def _safe_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, _LocalCompletionStop):
        return {"error_type": type(exc).__name__, "message": exc.safe_message,
                "failure_kind": exc.failure_kind, "retryable": False}
    from .failure_info import details

    info = details(exc)
    fields = {key: info[key] for key in ("failure_kind", "http_status", "retryable", "next_retry_at", "error_code")
              if key in info and info[key] is not None}
    summary = f"本地完稿步骤失败（{type(exc).__name__}"
    if fields.get("failure_kind"):
        summary += f"，{fields['failure_kind']}"
    if fields.get("http_status"):
        summary += f"，HTTP {fields['http_status']}"
    if fields.get('error_code'):
        summary += '，'+fields['error_code']
    summary += "）"
    return {"error_type": type(exc).__name__, "message": summary, **fields}


def _alert(job_id: str, chapter: Optional[int], message: str, state: str) -> None:
    root = s.RUNS_ROOT.parent / "alerts"
    bridge.write_json_atomic(root / f"{bridge.safe_dir_name(job_id)}-{chapter or 'unknown'}.json", {
        "job_id": job_id,
        "chapter_id": chapter,
        "state": state,
        "message": message,
        "updated_at": bridge.now_iso(),
    })


def _write_record(job_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
    record["run_record"] = s._write_run_record(job_id, record)
    return record


def _parse_retry_at(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def _recovery_plan(job: Dict[str, Any], project: Path, chapter: Optional[int], cycle: Dict[str, Any],
                   exc: Exception) -> Dict[str, Any]:
    from . import editorial_recovery as editorial
    from .failure_info import details

    previous = cycle.get("local_recovery") if isinstance(cycle.get("local_recovery"), dict) else {}
    same_chapter = previous.get("scope") == "local_completion" and previous.get("chapter_id") == chapter
    if same_chapter:
        attempts = previous.get("attempts", 0)
        editorial_attempts = previous.get("editorial_attempts", 0)
        if (type(attempts) is not int or attempts < 0 or type(editorial_attempts) is not int
                or editorial_attempts < 0):
            raise _LocalCompletionStop("本地恢复计数损坏，已停止自动恢复", "local_recovery_state_invalid")
    else:
        attempts = 0
        editorial_attempts = 0

    failure = details(exc)
    waiting = (failure.get("failure_kind") in {"recovery_cooldown", "free_pool_wait"}
               and _parse_retry_at(failure.get("next_retry_at")) is not None)
    editing = editorial.can_retry(exc, project, chapter) if chapter is not None else False
    if waiting:
        retryable = True
        next_retry_at = failure["next_retry_at"]
        updated_attempts = attempts
    else:
        next_retry_at = None
        updated_attempts = attempts + 1
        if editing:
            editorial_attempts += 1
            retryable = editorial_attempts < editorial.MAX_RECOVERIES
        else:
            retryable = failure.get("retryable") is True and updated_attempts <= len(BACKOFF_SECONDS)

    extra_budget = None
    if not waiting and not retryable and not editing and failure.get("retryable") is True:
        from .retry_budget import extension

        extra_budget = extension(job, s._now_for_job(job))
        if extra_budget:
            retryable = True
            next_retry_at = extra_budget.get("next_retry_at")

    recovery: Dict[str, Any] = {
        "scope": "local_completion",
        "chapter_id": chapter,
        "attempts": updated_attempts,
        "editorial_attempts": editorial_attempts,
        "automatic_retry": retryable,
        "message": _safe_error(exc)["message"],
        **{key: failure[key] for key in ("failure_kind", "http_status", "retryable", "error_code") if key in failure},
    }
    if editing:
        recovery["kind"] = "editorial"
    if extra_budget:
        recovery["cooldown"] = True
        recovery["extra_budget"] = extra_budget
    if retryable:
        if next_retry_at is None:
            prior_index = editorial_attempts - 1 if editing else attempts
            delay = BACKOFF_SECONDS[min(max(0, prior_index), len(BACKOFF_SECONDS) - 1)]
            next_retry_at = (s._now_for_job(job) + timedelta(seconds=delay)).isoformat()
        if _parse_retry_at(next_retry_at) is None:
            recovery.update(automatic_retry=False, failure_kind="invalid_retry_timestamp")
        else:
            recovery["next_retry_at"] = next_retry_at
    return recovery


def _record_failure(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], record: Dict[str, Any],
                    chapter: Optional[int], exc: Exception) -> Dict[str, Any]:
    previous = cycle.get("local_recovery") if isinstance(cycle.get("local_recovery"), dict) else {}
    if (previous.get("scope") == "local_completion" and previous.get("chapter_id") == chapter
            and previous.get("automatic_retry") is False and not previous.get("resolved")):
        message = str(previous.get("message") or "本地完稿已停止，需人工诊断")
        cycle.update(status="failed", stage="local_failed")
        s._update_run(job_id, {"cycle": cycle, "last_status": "failed", "last_message": message})
        record.update(status="failed", error=message, recovery=previous, finished_at=bridge.now_iso())
        return record

    safe = _safe_error(exc)
    try:
        recovery = _recovery_plan(job, Path(job["project"]).resolve(), chapter, cycle, exc)
    except Exception as recovery_exc:
        safe = _safe_error(recovery_exc)
        recovery = {"scope": "local_completion", "chapter_id": chapter, "attempts": 0,
                    "editorial_attempts": 0, "automatic_retry": False,
                    "failure_kind": "local_recovery_planning_failed", "message": safe["message"]}
    retryable = recovery.get("automatic_retry") is True
    cycle["local_recovery"] = recovery
    cycle.update(status="continuing" if retryable else "failed",
                 stage="local_retry_wait" if retryable else "local_failed")
    progress = {"completed": len(cycle.get("local_completed_ids", [])),
                "target_count": len(TARGET_IDS), "sealed_chapter": 51,
                "total_local_chapters": len(TARGET_IDS) + 1, "current_chapter": chapter}
    cycle["local_progress"] = progress
    status = "continuing" if retryable else "failed"
    s._update_run(job_id, {"cycle": cycle, "last_status": status, "last_message": safe["message"]})
    record.update(status="failed", error=safe["message"], error_type=safe["error_type"],
                  recovery=recovery, local_progress=progress, finished_at=bridge.now_iso(),
                  delivery_mode="serial", local_only=True)
    _write_record(job_id, record)
    _alert(job_id, chapter, safe["message"], "retry_wait" if retryable else "needs_attention")
    return record


def _wait_or_stop(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], record: Dict[str, Any],
                  chapter: int) -> Optional[Dict[str, Any]]:
    recovery = cycle.get("local_recovery")
    if not isinstance(recovery, dict) or recovery.get("scope") != "local_completion" or recovery.get("chapter_id") != chapter:
        return None
    if recovery.get("automatic_retry") is False and not recovery.get("resolved"):
        message = str(recovery.get("message") or "本地完稿已停止，需人工诊断")
        cycle.update(status="failed", stage="local_failed")
        s._update_run(job_id, {"cycle": cycle, "last_status": "failed", "last_message": message})
        record.update(status="failed", error=message, recovery=recovery, finished_at=bridge.now_iso(),
                      delivery_mode="serial", local_only=True)
        return record
    if recovery.get("automatic_retry") is True:
        retry_at = _parse_retry_at(recovery.get("next_retry_at"))
        if retry_at is None:
            exc = _LocalCompletionStop("本地恢复时间记录无效，已停止自动恢复", "local_recovery_state_invalid")
            return _record_failure(job_id, job, cycle, record, chapter, exc)
        if retry_at > s._now_for_job(job):
            cycle.update(status="continuing", stage="local_retry_wait")
            progress = {"completed": len(cycle.get("local_completed_ids", [])),
                        "target_count": len(TARGET_IDS), "sealed_chapter": 51,
                        "total_local_chapters": len(TARGET_IDS) + 1, "current_chapter": chapter}
            cycle["local_progress"] = progress
            s._update_run(job_id, {"cycle": cycle, "last_status": "continuing",
                                   "last_message": "本地恢复仍在冷却，等待原章节重试时间"})
            record.update(status="waiting", recovery=recovery, local_progress=progress,
                          delivery_mode="serial", local_only=True)
            return record
    return None


def _repair_saved_chapter(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], record: Dict[str, Any],
                          project: Path, chapter: int) -> Tuple[bool, Optional[Exception]]:
    cycle.update(status="running", stage="local_post_save_repair", current_chapter=chapter)
    s._update_run(job_id, {"cycle": cycle, "last_status": "running", "last_message": "修复本地正文的后保存同步"})
    try:
        from . import studio

        studio.sync_existing_artifacts(project, chapter)
    except Exception as exc:
        return False, exc
    try:
        receipts = writer.reviewed_chapters(project)
        state, _, receipt, message = _chapter_state(project, chapter, receipts)
    except Exception as exc:
        return False, exc
    if state == "complete":
        return True, None
    if state == "repair" and isinstance(receipt, dict):
        post = receipt.get("post_save", {})
        memory = post.get("shared_memory", {}) if isinstance(post, dict) else {}
        if isinstance(memory, dict) and memory.get("status") == "failed" and memory.get("retryable") is True:
            from .failure_info import PostSaveIncomplete

            return False, PostSaveIncomplete(memory)
    return False, _LocalCompletionStop(message or f"第{chapter}章后保存阶段未完整同步，已保留正文并停止")


def _record_progress(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], record: Dict[str, Any],
                     completed: list[int], chapter: int, result_sha: Optional[str]) -> Dict[str, Any]:
    completed = sorted(set(completed) | {chapter})
    cycle["local_completed_ids"] = completed
    cycle.update(status="continuing", stage="local_chapter_complete", current_chapter=chapter)
    cycle["local_progress"] = {"completed": len(completed), "target_count": len(TARGET_IDS),
                                "sealed_chapter": 51, "total_local_chapters": len(TARGET_IDS) + 1,
                                "current_chapter": chapter}
    recovery = cycle.get("local_recovery")
    if isinstance(recovery, dict) and recovery.get("scope") == "local_completion" and recovery.get("chapter_id") == chapter:
        cycle["local_recovery"] = {**recovery, "automatic_retry": False, "resolved": True,
                                   "resolved_at": bridge.now_iso()}
    s._update_run(job_id, {"cycle": cycle, "last_status": "continuing", "last_message": ""})
    record.update(status="progress", local_chapter={"chapter_id": chapter, "body_sha256": result_sha},
                  local_progress=cycle["local_progress"], finished_at=bridge.now_iso(),
                  delivery_mode="serial", local_only=True)
    return _write_record(job_id, record)


def step(job_id: str, job: Dict[str, Any], cycle: Dict[str, Any], record: Dict[str, Any], force: bool = False):
    """Process at most one local chapter; caller owns scheduler and book locks."""
    del force  # Local-only safety gates are never bypassed by --force.
    record.update(mode="local_completion", local_only=True, delivery_mode="serial",
                  target_ids=list(TARGET_IDS), generated=[])
    if cycle.get("status") == "local_complete":
        record.update(status="local_complete", local_publish_state="pending", delivery_mode="serial")
        return record

    chapter: Optional[int] = None
    try:
        project = _validate_cycle(job, cycle)
        _read_sealed_record(job, cycle, project)
        if cycle.get('publish_every')==10:
            from .ten_chapter_delivery import maybe_publish
            batch_result=maybe_publish(job_id,job,cycle,record)
            if batch_result is not None:return batch_result
        completed: list[int] = []
        selected_state = ""
        selected_path: Optional[Path] = None
        selected_receipt: Optional[Dict[str, Any]] = None
        receipts = writer.reviewed_chapters(project)
        for number in TARGET_IDS:
            state, source, receipt, message = _chapter_state(project, number, receipts)
            if state == "complete":
                completed.append(number)
                continue
            if state == "conflict":
                chapter = number
                cycle["local_completed_ids"] = completed
                cycle["local_progress"] = {"completed": len(completed), "target_count": len(TARGET_IDS),
                                            "sealed_chapter": 51, "total_local_chapters": len(TARGET_IDS) + 1,
                                            "current_chapter": number}
                raise _LocalCompletionStop(message or f"第{number}章状态冲突，已停止")
            chapter, selected_state, selected_path, selected_receipt = number, state, source, receipt
            break

        cycle["local_completed_ids"] = completed
        cycle["local_progress"] = {"completed": len(completed), "target_count": len(TARGET_IDS),
                                    "sealed_chapter": 51, "total_local_chapters": len(TARGET_IDS) + 1,
                                    "current_chapter": chapter}
        if chapter is None:
            _read_sealed_record(job, cycle, project)
            cycle.update(status="local_complete", stage="local_complete")
            cycle["local_progress"]["current_chapter"] = None
            job["enabled"] = False
            s._update_run(job_id, {"cycle": cycle, "enabled": False, "last_status": "local_complete",
                                   "last_message": "本地完稿50章已完成，待逐章发布；未发布"})
            record.update(status="local_complete", local_progress=cycle["local_progress"],
                          local_publish_state="pending", publication_confirmed=False,
                          finished_at=bridge.now_iso(), delivery_mode="serial", local_only=True)
            return _write_record(job_id, record)

        waiting = _wait_or_stop(job_id, job, cycle, record, chapter)
        if waiting is not None:
            return waiting

        cycle.update(status="running", stage="local_generation" if selected_state == "missing"
                     else "local_post_save_repair", current_chapter=chapter)
        cycle["local_progress"]["current_chapter"] = chapter
        s._update_run(job_id, {"cycle": cycle, "last_status": "running", "last_message": ""})

        if selected_state == "repair":
            repaired, repair_error = _repair_saved_chapter(job_id, job, cycle, record, project, chapter)
            if not repaired:
                raise repair_error or _LocalCompletionStop(f"第{chapter}章后保存同步未完成")
        else:
            generation_error: Optional[Exception] = None
            try:
                writer.generate_chapter(Path(job["project"]), word_count=WORD_COUNT,
                                        max_revisions=MAX_REVISIONS, chapter_id=chapter)
            except Exception as exc:
                generation_error = exc
            receipts = writer.reviewed_chapters(project)
            state, saved_path, receipt, message = _chapter_state(project, chapter, receipts)
            if generation_error is not None:
                if state == "repair":
                    repaired, repair_error = _repair_saved_chapter(job_id, job, cycle, record, project, chapter)
                    if repaired:
                        generation_error = None
                        state = "complete"
                    else:
                        raise repair_error or generation_error
                elif state == "complete":
                    generation_error = None
                else:
                    if state == "conflict":
                        raise _LocalCompletionStop(message or f"第{chapter}章写入后资格或正文冲突") from generation_error
                    raise generation_error
            if generation_error is None and state == "repair":
                repaired, repair_error = _repair_saved_chapter(job_id, job, cycle, record, project, chapter)
                if not repaired:
                    raise repair_error or _LocalCompletionStop(f"第{chapter}章后保存同步未完成")
            elif generation_error is None and state != "complete":
                raise _LocalCompletionStop(message or f"第{chapter}章生成后未形成有效正文资格")
            selected_path = saved_path
            selected_receipt = receipt

        # Re-read all current qualification and byte evidence before counting success.
        receipts = writer.reviewed_chapters(project)
        final_state, final_path, final_receipt, message = _chapter_state(project, chapter, receipts)
        _read_sealed_record(job, cycle, project)
        if final_state != "complete" or final_path is None or not isinstance(final_receipt, dict):
            raise _LocalCompletionStop(message or f"第{chapter}章未达到本地完稿资格")
        digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
        return _record_progress(job_id, job, cycle, record, completed, chapter, digest)
    except Exception as exc:
        return _record_failure(job_id, job, cycle, record, chapter, exc)
