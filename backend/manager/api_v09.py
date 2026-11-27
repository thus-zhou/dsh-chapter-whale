"""v0.9 API：并发队列、世界状态、质量体检与诊断维护。"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from integration import concurrent_engine, costs, maintenance, quality, world_state


def install(app: FastAPI, *, project: Callable[[str], Dict[str, Any]], data_dir: Path) -> None:
    concurrent_engine.configure_global_pause(Path(data_dir) / "global_pause.json")
    def _book(identity: str) -> Path:
        return Path(project(identity)["path"])

    def guard(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (world_state.WorldStateError, concurrent_engine.SchedulerError,
                    quality.QualityError, maintenance.MaintenanceError) as exc:
                return JSONResponse(status_code=exc.status,
                                    content={"code": exc.code, "message": exc.code,
                                             **(getattr(exc, "detail", {}) or {})})
        return wrapper

    # ----------------------------------------------------------- world state
    @app.get("/api/projects/{identity}/world-state")
    @guard
    def world_state_view(identity: str, chapter: int = 1, q: str = ""):
        return world_state.state(_book(identity), chapter=int(chapter), query=q)

    @app.post("/api/projects/{identity}/world-state/facts")
    @guard
    def upsert_world_fact(identity: str, data: dict | None = None):
        body = data or {}
        return world_state.upsert_fact(_book(identity), body.get("fact") if isinstance(
            body.get("fact"), dict) else body)

    @app.get("/api/projects/{identity}/world/facts")
    @guard
    def facts(identity: str, chapter: int = 1, domain: str | None = None,
              status: str | None = None):
        if status:
            return {"facts": world_state.facts_by_status(_book(identity), status)}
        return {"facts": world_state.facts_for_chapter(_book(identity), int(chapter), domain=domain)}

    @app.get("/api/projects/{identity}/world/facts/pending")
    @guard
    def pending_facts(identity: str):
        return {"facts": world_state.facts_by_status(_book(identity), "pending_confirm")}

    @app.post("/api/projects/{identity}/world/facts/{fact_id}/confirm")
    @guard
    def confirm_fact(identity: str, fact_id: str, data: dict | None = None):
        body = data or {}
        return world_state.confirm_fact(_book(identity), fact_id,
                                       authority_level=str(body.get("authority_level") or "confirmed_prose"))

    @app.post("/api/projects/{identity}/world/facts/{fact_id}/reject")
    @guard
    def reject_fact(identity: str, fact_id: str):
        return world_state.reject_fact(_book(identity), fact_id)

    @app.post("/api/projects/{identity}/world/facts")
    @guard
    def upsert_fact(identity: str, data: dict | None = None):
        return world_state.upsert_fact(_book(identity), data or {})

    @app.post("/api/projects/{identity}/world/facts/{fact_id}/ignore")
    @guard
    def ignore_fact(identity: str, fact_id: str, data: dict | None = None):
        body = data or {}
        return world_state.ignore_conflict(_book(identity), fact_id,
                                           chapter_uid=str(body.get("chapter_uid") or ""),
                                           version_id=str(body.get("version_id") or ""),
                                           reason=str(body.get("reason") or "intentional_or_flashback"))

    @app.get("/api/projects/{identity}/world/cards")
    @guard
    def cards(identity: str, pinned: bool = False):
        return {"cards": world_state.list_cards(_book(identity), pinned_only=pinned)}

    @app.post("/api/projects/{identity}/world/cards")
    @guard
    def set_card(identity: str, data: dict | None = None):
        return world_state.set_card(_book(identity), data or {})

    @app.get("/api/projects/{identity}/world/context")
    @guard
    def context(identity: str, chapter: int = 1, q: str = "", budget: int = 24000):
        return world_state.build_context(_book(identity), int(chapter), query=q,
                                         budget_chars=max(200, min(int(budget), 200000)),
                                         persist=False)

    @app.get("/api/projects/{identity}/world/conflicts")
    @guard
    def conflicts(identity: str, chapter: int = 1):
        return {"conflicts": world_state.detect_conflicts(_book(identity), int(chapter))}

    @app.get("/api/projects/{identity}/world/search")
    @guard
    def world_search(identity: str, q: str = "", chapter: int | None = None, limit: int = 20):
        return {"hits": world_state.search(_book(identity), q, chapter=chapter,
                                           limit=max(1, min(int(limit), 100)))}

    @app.post("/api/projects/{identity}/world/extract")
    @guard
    def extract(identity: str, chapter: int = 1, data: dict | None = None):
        return world_state.extract_candidates(_book(identity), int(chapter), data or {})

    @app.post("/api/projects/{identity}/world/causal-scan")
    @guard
    def causal(identity: str, data: dict | None = None):
        body = data or {}
        return world_state.causal_scan(_book(identity), change=str(body.get("change") or ""),
                                       apply_to_existing=bool(body.get("apply_to_existing", True)),
                                       effective_from_chapter=body.get("effective_from_chapter"))

    @app.post("/api/projects/{identity}/world/exemptions")
    @guard
    def exemption(identity: str, data: dict | None = None):
        body = data or {}
        return world_state.add_exemption(_book(identity), chapter=int(body.get("chapter") or 0),
                                         rule_id=str(body.get("rule_id") or ""),
                                         rule_text=str(body.get("rule_text") or ""))

    @app.post("/api/projects/{identity}/book-directives/scan")
    @guard
    def book_directive_scan(identity: str, data: dict | None = None):
        body = data or {}
        scan = world_state.causal_scan(
            _book(identity), change=str(body.get("change") or body.get("instruction") or ""),
            apply_to_existing=bool(body.get("apply_to_existing", False)),
            effective_from_chapter=body.get("effective_from_chapter"))
        return {"directive_id": "scan_" + hashlib.sha256(
                    json.dumps(scan, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()[:16], **scan}

    @app.post("/api/projects/{identity}/book-directives/{directive}/execute")
    @guard
    def book_directive_execute(identity: str, directive: str, data: dict | None = None):
        body = data or {}
        if body.get("action") == "exempt":
            return world_state.add_exemption(
                _book(identity), chapter=int(body.get("chapter") or 0),
                rule_id=str(body.get("rule_id") or directive),
                rule_text=str(body.get("rule_text") or ""))
        return {"status": "requires_model", "directive_id": directive,
                "message": "试改/批量需由主编室模型执行"}

    # ---------------------------------------------------------------- tasks
    @app.get("/api/projects/{identity}/tasks")
    @guard
    def tasks(identity: str, state: str | None = None):
        return concurrent_engine.snapshot(_book(identity)) if not state else {
            "tasks": concurrent_engine.list_tasks(_book(identity), state=state)}

    @app.post("/api/projects/{identity}/tasks")
    @guard
    def submit_task(identity: str, data: dict | None = None):
        body = data or {}
        return concurrent_engine.submit(_book(identity), body.get("payload") or {},
                                        priority=str(body.get("priority") or "P2"),
                                        chapter_id=body.get("chapter_id"),
                                        parent_task_id=body.get("parent_task_id"),
                                        blocked_by=body.get("blocked_by") or (),
                                        amendment_fallback=str(body.get("amendment_fallback") or "wait"))

    @app.post("/api/projects/{identity}/tasks/claim")
    @guard
    def claim_task(identity: str, data: dict | None = None):
        body = data or {}
        item = concurrent_engine.claim(_book(identity), str(body.get("owner") or "worker"),
                                       max_slots=int(body.get("max_slots") or 4))
        return {"task": item}

    @app.post("/api/projects/{identity}/tasks/{task_id}/renew")
    @guard
    def renew_task(identity: str, task_id: str, data: dict | None = None):
        return concurrent_engine.renew(_book(identity), task_id,
                                       str((data or {}).get("owner") or "worker"))

    @app.post("/api/projects/{identity}/tasks/{task_id}/commit")
    @guard
    def commit_task(identity: str, task_id: str, data: dict | None = None):
        return concurrent_engine.begin_commit(_book(identity), task_id,
                                              str((data or {}).get("owner") or "worker"))

    @app.post("/api/projects/{identity}/tasks/{task_id}/complete")
    @guard
    def complete_task(identity: str, task_id: str, data: dict | None = None):
        return concurrent_engine.complete(_book(identity), task_id,
                                          owner=str((data or {}).get("owner") or ""))

    @app.post("/api/projects/{identity}/tasks/{task_id}/fail")
    @guard
    def fail_task(identity: str, task_id: str, data: dict | None = None):
        return concurrent_engine.fail(_book(identity), task_id,
                                      error=str((data or {}).get("error") or ""))

    @app.post("/api/projects/{identity}/tasks/{task}/retry")
    @guard
    def retry_task(identity: str, task: str, data: dict | None = None):
        return concurrent_engine.retry(_book(identity), task,
                                       owner=str((data or {}).get("owner") or "author"))

    @app.post("/api/projects/{identity}/automation/pause")
    @guard
    def automation_pause(identity: str, data: dict | None = None):
        body = data or {}
        book = _book(identity)
        scope = "project:" + str(book.resolve())
        if body.get("paused", True):
            return concurrent_engine.pause(book, scope, reason=str(body.get("reason") or "作者暂停"))
        return concurrent_engine.resume(book, scope)

    @app.post("/api/system/ai/pause")
    @guard
    def system_ai_pause(data: dict | None = None):
        body = data or {}
        paused = bool(body.get("paused", True))
        result = concurrent_engine.set_global_pause(
            paused, reason=str(body.get("reason") or ("全站急停" if paused else "全站恢复")))
        identity = str(body.get("identity") or "")
        if identity:
            book = _book(identity)
            if paused:
                concurrent_engine.pause(book, "global", reason=str(body.get("reason") or "全站急停"))
            else:
                concurrent_engine.resume(book, "global")
        return result

    @app.post("/api/projects/{identity}/tasks/pause")
    @guard
    def pause_tasks(identity: str, data: dict | None = None):
        body = data or {}
        return concurrent_engine.pause(_book(identity), str(body.get("scope") or "global"),
                                       reason=str(body.get("reason") or ""))

    @app.post("/api/projects/{identity}/tasks/resume")
    @guard
    def resume_tasks(identity: str, data: dict | None = None):
        return concurrent_engine.resume(_book(identity), str((data or {}).get("scope") or "global"))

    @app.post("/api/projects/{identity}/tasks/recover")
    @guard
    def recover_tasks(identity: str):
        return {"recovered": concurrent_engine.recover(_book(identity))}

    @app.get("/api/projects/{identity}/directives/{directive}/cost")
    @guard
    def directive_cost(identity: str, directive: str):
        db_path = Path(data_dir) / "costs.sqlite3"
        return costs.directive_usage(db_path, directive)

    # -------------------------------------------------------------- quality
    @app.get("/api/projects/{identity}/quality/dashboard")
    @guard
    def quality_dashboard_alias(identity: str):
        return quality.dashboard(_book(identity))

    @app.get("/api/projects/{identity}/quality")
    @guard
    def quality_board(identity: str):
        return quality.dashboard(_book(identity))

    @app.get("/api/projects/{identity}/quality/{chapter}")
    @guard
    def quality_history(identity: str, chapter: int):
        return {"chapter_id": int(chapter), "reviews": quality.history(_book(identity), int(chapter))}

    @app.post("/api/projects/{identity}/quality/{chapter}/review")
    @guard
    def quality_review(identity: str, chapter: int, data: dict | None = None):
        body = data or {}
        return quality.review(_book(identity), int(chapter), judgments=body.get("judgments"),
                              reviewer=str(body.get("reviewer") or "auto"),
                              force=bool(body.get("force")))

    # --------------------------------------------------------- diagnostics
    @app.get("/api/system/diagnostics")
    @guard
    def system_diagnostics():
        return maintenance.system_health(data_dir)

    @app.post("/api/system/diagnostics/recover")
    @guard
    def system_recover(data: dict | None = None):
        body = data or {}
        identity = str(body.get("identity") or "")
        if identity and body.get("action") in {"gc", "export"}:
            book = _book(identity)
            if body["action"] == "gc":
                return maintenance.collect_garbage(
                    book, dry_run=bool(body.get("dry_run", True)),
                    min_age_seconds=max(86400, int(body.get("min_age_seconds") or 7 * 86400)))
            destination = Path(body.get("destination") or (
                data_dir / "diagnostics" / f"recover-{os.getpid()}-{int(time.time())}.zip"))
            return maintenance.export_bundle(book, destination)
        return {"status": "ok", "recovered": [], "message": "没有可自动恢复的卡单"}

    @app.get("/api/projects/{identity}/diagnostics")
    @guard
    def diagnostics(identity: str):
        return maintenance.health(_book(identity))

    @app.get("/api/projects/{identity}/ledger")
    @guard
    def ledger(identity: str):
        return maintenance.resource_ledger(_book(identity),
                                           costs_db=Path(data_dir) / "costs.sqlite3")

    @app.post("/api/projects/{identity}/diagnostics/gc")
    @guard
    def garbage(identity: str, data: dict | None = None):
        body = data or {}
        return maintenance.collect_garbage(_book(identity),
                                           dry_run=bool(body.get("dry_run", True)),
                                           min_age_seconds=max(86400, int(body.get("min_age_seconds") or 7 * 86400)))

    @app.post("/api/projects/{identity}/diagnostics/export")
    @guard
    def export_diagnostics(identity: str, data: dict | None = None):
        target = (data or {}).get("destination")
        destination = Path(target).expanduser() if target else (
            data_dir / "diagnostics" / f"diagnostics-{identity}-{int(time.time())}.zip")
        return maintenance.export_bundle(_book(identity), destination)

    @app.post("/api/projects/{identity}/diagnostics/heal")
    @guard
    def heal(identity: str, data: dict | None = None):
        return maintenance.self_heal(_book(identity), str((data or {}).get("action") or ""))
