"""v0.8.2 / v0.8.5 API：批注、三方合并、主编室与三级路由。"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from integration import agent_hub, agent_room, annotations, chapter_editor, costs


def install(app: FastAPI, *, project: Callable[[str], Dict[str, Any]], data_dir: Path) -> None:
    room_db = Path(data_dir) / "agent_room.sqlite3"
    agent_room.initialize(room_db)

    def _book(identity: str) -> Path:
        return Path(project(identity)["path"])

    def guard(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (annotations.AnnotationError, agent_room.RoomError, agent_hub.HubError,
                    chapter_editor.ChapterError) as exc:
                return JSONResponse(status_code=exc.status,
                                    content={"code": exc.code, "message": exc.code,
                                             **(getattr(exc, "detail", {}) or {})})
            except (TypeError, ValueError, KeyError, OverflowError,
                    sqlite3.ProgrammingError) as exc:
                # Malformed scalar where a list/object was expected is a
                # request error, never an unhandled 500 (B-15/B3-16).
                return JSONResponse(status_code=400,
                                    content={"code": "invalid_request",
                                             "message": f"请求字段不合法：{type(exc).__name__}"})
        return wrapper

    def _seq(value, field: str) -> list:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        raise agent_room.RoomError("invalid_request", detail={"field": field,
                                                              "message": f"{field} 必须是数组"})

    def _directive(identity: str, directive: str) -> dict:
        item = agent_room.get_directive(room_db, directive)
        if str(item.get("project_id") or "") != str(identity):
            raise agent_room.RoomError("directive_project_mismatch", status=404)
        return item

    SENDER_ROLES = {"author", "system", "chief", "planner", "writer", "editor",
                    "reviewer", "publisher", "agent", "worker"}

    def _sender_role(body: dict) -> str:
        # A body field is not identity.  Default to system so an agent that
        # omits the field cannot silently speak as the author (B3-17).
        value = str(body.get("sender_role") or "system").strip()
        if value not in SENDER_ROLES:
            raise agent_room.RoomError("invalid_sender_role",
                                       detail={"field": "sender_role"})
        return value

    def _max_calls(body: dict) -> int:
        value = body.get("max_calls")
        if value is None:
            return 20
        if isinstance(value, bool):
            raise agent_room.RoomError("invalid_request", detail={"field": "max_calls"})
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            raise agent_room.RoomError("invalid_request",
                                       detail={"field": "max_calls"}) from None
        if not 1 <= parsed <= 10**6:
            raise agent_room.RoomError(
                "invalid_request",
                detail={"field": "max_calls", "message": "max_calls 必须在 1..1000000"})
        return parsed

    def _budget_cap(body: dict):
        value = body.get("budget_cap_cny")
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise agent_room.RoomError("invalid_request",
                                       detail={"field": "budget_cap_cny"})
        try:
            return costs.number(value)
        except (TypeError, ValueError):
            raise agent_room.RoomError(
                "invalid_request", detail={"field": "budget_cap_cny",
                                           "message": "budget_cap_cny 必须是非负数字"}) from None

    def _artifact_still_valid(identity: str, item: dict) -> bool:
        """Revalidate an artifact handle bound in ``detail`` at resolve time.

        Cards that do not declare an artifact path keep their existing
        contract; cards that do can no longer be approved after the file was
        deleted or replaced (B3-01).
        """
        detail = item.get("detail") or {}
        value = detail.get("artifact_path")
        if not isinstance(value, str) or not value.strip():
            return True
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = Path(project(identity)["path"]) / candidate
        try:
            if not candidate.is_file():
                return False
            expected = str(detail.get("artifact_sha256") or "")
            if str(detail.get("fingerprint_algo") or "") == "sha256" and expected:
                return hashlib.sha256(candidate.read_bytes()).hexdigest() == expected
        except OSError:
            return False
        return True

    # ------------------------------------------------------------ annotations
    @app.get("/api/projects/{identity}/chapters/{chapter}/annotations")
    @guard
    def list_annotations(identity: str, chapter: int, against: str = "draft"):
        return annotations.list_annotations(_book(identity), int(chapter), against=against)

    @app.post("/api/projects/{identity}/chapters/{chapter}/annotations")
    @guard
    def create_annotation(identity: str, chapter: int, data: dict | None = None):
        return annotations.create_annotation(_book(identity), int(chapter), data or {})

    @app.patch("/api/projects/{identity}/chapters/{chapter}/annotations/{annotation}")
    @guard
    def update_annotation(identity: str, chapter: int, annotation: str, data: dict | None = None):
        return annotations.update_annotation(_book(identity), int(chapter), annotation, data or {})

    @app.delete("/api/projects/{identity}/chapters/{chapter}/annotations/{annotation}")
    @guard
    def delete_annotation(identity: str, chapter: int, annotation: str):
        return annotations.delete_annotation(_book(identity), int(chapter), annotation)

    @app.post("/api/projects/{identity}/chapters/{chapter}/annotations/run")
    @guard
    def run_annotations(identity: str, chapter: int, data: dict | None = None):
        return annotations.run_annotations(_book(identity), int(chapter), data or {})

    @app.post("/api/projects/{identity}/chapters/{chapter}/annotations/{annotation}/followup")
    @guard
    def followup_annotation(identity: str, chapter: int, annotation: str, data: dict | None = None):
        body = data or {}
        updated = annotations.update_annotation(
            _book(identity), int(chapter), annotation,
            {"instruction": str(body.get("instruction") or body.get("text") or "")})
        if body.get("run"):
            return annotations.run_annotations(
                _book(identity), int(chapter),
                {"annotation_ids": [annotation], "op_id": body.get("op_id"),
                 "against": body.get("against") or "draft"})
        return updated

    @app.get("/api/projects/{identity}/chapters/{chapter}/annotations/previews")
    @guard
    def annotation_previews(identity: str, chapter: int):
        return annotations.list_previews(_book(identity), int(chapter))

    @app.post("/api/projects/{identity}/chapters/{chapter}/revision/apply-hunks")
    @guard
    def apply_hunks(identity: str, chapter: int, data: dict | None = None):
        return annotations.apply_hunks(_book(identity), int(chapter), data or {})

    @app.post("/api/projects/{identity}/chapters/{chapter}/revision/reject-hunks")
    @guard
    def reject_hunks(identity: str, chapter: int, data: dict | None = None):
        return annotations.reject_hunks(_book(identity), int(chapter), data or {})

    @app.post("/api/projects/{identity}/chapters/{chapter}/revision/undo-apply")
    @guard
    def undo_apply(identity: str, chapter: int, data: dict | None = None):
        return annotations.undo_apply(_book(identity), int(chapter), data or {})

    # ------------------------------------------------------------- agent room
    @app.get("/api/projects/{identity}/chief")
    @guard
    def chief_snapshot(identity: str, topic_id: str | None = None):
        return agent_room.snapshot(room_db, project_id=identity, topic_id=topic_id)

    @app.get("/api/projects/{identity}/room/state")
    @guard
    def room_state(identity: str, topic_id: str | None = None):
        return agent_room.snapshot(room_db, project_id=identity, topic_id=topic_id)

    @app.get("/api/chief/room/state")
    @guard
    def chief_room_state(session_id: str = "author", project_id: str | None = None,
                         topic_id: str | None = None):
        # Without a project this returns only unbound (pre-book) session rows;
        # it must never aggregate every book that shares session_id="author"
        # (B-05/C-10).
        return agent_room.snapshot(room_db, project_id=project_id,
                                   session_id=None if project_id else session_id,
                                   topic_id=topic_id)

    @app.post("/api/chief/messages")
    @guard
    def chief_message_without_project(data: dict | None = None):
        body = data or {}
        session_id = str(body.get("session_id") or "author")
        return agent_room.append_event(
            room_db, session_id=session_id, topic_id=str(body.get("topic_id") or "default"),
            project_id=None, channel="chief_chat", sender_role=_sender_role(body),
            kind=str(body.get("kind") or "message"),
            summary=str(body.get("summary") or body.get("text") or ""),
            payload=body.get("payload") or {}, mentions=_seq(body.get("mentions"), "mentions"))

    @app.get("/api/projects/{identity}/room/stream")
    async def room_stream(identity: str, request: Request, last_event_id: str = ""):
        """SSE four-channel stream with paged replay, gap-free subscribe and backpressure."""
        after = 0
        header = request.headers.get("last-event-id") or last_event_id
        try:
            after = int(header or 0)
        except (TypeError, ValueError):
            after = 0
        # A hostile/corrupt cursor must not overflow SQLite inside the stream
        # generator (B3-24).
        after = max(0, min(after, 2**63 - 1))
        page_size = 200

        async def frames():
            nonlocal after
            token = None
            try:
                yield "retry: 1500\n\n"

                async def replay_from(cursor: int):
                    nonlocal after
                    while True:
                        batch = await asyncio.to_thread(
                            agent_room.events_after, room_db, after_seq=cursor,
                            project_id=identity, limit=page_size)
                        for event in batch:
                            yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                            cursor = int(event["seq"])
                            after = cursor
                            if token is not None:
                                # Replay frames were delivered too; without an
                                # ack an overflow marker can fall back to 0
                                # (B3-24).
                                agent_room.broadcaster.ack(token, cursor)
                        if len(batch) < page_size:
                            break

                # C-43/B3-07: replay first, subscribe second.  A fresh client
                # gets the newest page of *its own* project, not
                # ``global_latest - 200`` (sparse books would skip history).
                if after == 0:
                    page = await asyncio.to_thread(agent_room.recent_events, room_db,
                                                   project_id=identity, limit=page_size)
                    start = 0 if not page else max(0, int(page[0]["seq"]) - 1)
                else:
                    start = after
                async for chunk in replay_from(start):
                    yield chunk
                token, queue = agent_room.broadcaster.subscribe(project_id=identity)
                # Close the replay→subscribe race: anything appended in that
                # window is replayed now; live duplicates are dropped by seq.
                async for chunk in replay_from(after):
                    yield chunk
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    seq = event.get("seq")
                    # A resync control frame must bypass the seq<=after
                    # filter: it can legitimately carry the last delivered
                    # seq (including 0) and still needs to reach the client.
                    if event.get("kind") != "resync_required" and isinstance(seq, int) and seq <= after:
                        continue
                    yield f"id: {seq if seq is not None else ''}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if isinstance(seq, int):
                        after = seq
                        agent_room.broadcaster.ack(token, seq)
                    if event.get("kind") == "resync_required":
                        break
            finally:
                if token is not None:
                    agent_room.broadcaster.unsubscribe(token)

        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/api/projects/{identity}/chief/topics")
    @guard
    def chief_topic(identity: str):
        return agent_room.new_topic(room_db, project_id=identity)

    @app.post("/api/projects/{identity}/chief/messages")
    @guard
    def chief_message(identity: str, data: dict | None = None):
        body = data or {}
        session_id = str(body.get("session_id") or "author")
        topic_id = str(body.get("topic_id") or "default")
        agent_room.bind_session_to_project(room_db, session_id=session_id, project_id=identity)
        event = agent_room.append_event(
            room_db, session_id=session_id, topic_id=topic_id, project_id=identity,
            channel=str(body.get("channel") or "chief_chat"),
            sender_role=_sender_role(body),
            kind=str(body.get("kind") or "message"),
            summary=str(body.get("summary") or body.get("text") or ""),
            payload=body.get("payload") or {}, mentions=_seq(body.get("mentions"), "mentions"))
        return event

    @app.get("/api/projects/{identity}/chief/messages")
    @guard
    def chief_context(identity: str, topic_id: str = "default"):
        return {"events": agent_room.chat_context(room_db, project_id=identity, topic_id=topic_id)}

    @app.post("/api/projects/{identity}/chief/directives")
    @guard
    def chief_directive(identity: str, data: dict | None = None):
        body = data or {}
        return agent_room.create_directive(
            room_db, session_id=str(body.get("session_id") or "author"), project_id=identity,
            title=str(body.get("title") or "未命名指令"),
            raw_instruction=str(body.get("instruction") or body.get("raw_instruction") or ""),
            autonomy=str(body.get("autonomy") or "step_confirm"),
            constraints=_seq(body.get("constraints"), "constraints"),
            budget_cap_cny=_budget_cap(body),
            max_calls=_max_calls(body))

    @app.post("/api/projects/{identity}/directives/{directive}/amend")
    @guard
    def amend_directive(identity: str, directive: str, data: dict | None = None):
        body = data or {}
        _directive(identity, directive)
        amendment = agent_hub.start_amendment(
            room_db, directive_id=directive,
            amendment_text=str(body.get("instruction") or body.get("text") or ""),
            task_ids=_seq(body.get("task_ids"), "task_ids"),
            fallback=str(body.get("fallback") or "wait"))
        return {"directive_id": directive,
                "directive_revision": amendment["directive_revision"],
                "amendment": amendment}

    @app.post("/api/projects/{identity}/directives/{directive}/amendments/{amendment}/evaluate")
    @guard
    def evaluate_amendment(identity: str, directive: str, amendment: str,
                           data: dict | None = None):
        body = data or {}
        _directive(identity, directive)
        record = agent_room.get_amendment(room_db, amendment)
        if str(record.get("directive_id")) != str(directive):
            raise agent_room.RoomError("amendment_directive_mismatch", status=404)
        return agent_hub.evaluate_amendment(room_db, amendment_id=amendment,
                                            directive_id=directive,
                                            context=body.get("context") if isinstance(
                                                body.get("context"), dict) else None)

    @app.post("/api/projects/{identity}/directives/{directive}/amendments/{amendment}/release")
    @guard
    def release_amendment(identity: str, directive: str, amendment: str):
        _directive(identity, directive)
        record = agent_room.get_amendment(room_db, amendment)
        if str(record.get("directive_id")) != str(directive):
            raise agent_room.RoomError("amendment_directive_mismatch", status=404)
        released = agent_hub.release_holds_for_current(
            room_db, directive_id=directive, amendment_id=amendment)
        return {"status": "released", "directive_id": directive,
                "amendment_id": amendment, "released_tasks": released}

    @app.post("/api/projects/{identity}/directives/{directive}/cancel")
    @guard
    def cancel_directive(identity: str, directive: str):
        _directive(identity, directive)
        return agent_hub.cancel_directive(room_db, directive_id=directive)

    @app.post("/api/projects/{identity}/directives/{directive}/resume")
    @guard
    def resume_directive(identity: str, directive: str):
        _directive(identity, directive)
        return agent_hub.resume_directive(room_db, directive_id=directive)

    @app.get("/api/projects/{identity}/approvals")
    @guard
    def approvals(identity: str, status: str = "pending"):
        return {"approvals": agent_room.pending_approvals(room_db, project_id=identity,
                                                          status=status)}

    @app.post("/api/projects/{identity}/approvals/{approval}/resolve")
    @guard
    def resolve_approval(identity: str, approval: str, data: dict | None = None):
        body = data or {}
        current = agent_room.get_approval(room_db, approval)
        if str(current.get("project_id") or "") != str(identity):
            raise agent_room.RoomError("approval_project_mismatch", status=404)
        # ``resolved_by`` in the body is a claim, not identity.  The author
        # surface refuses agent claims, then ignores the field entirely.
        if "resolved_by" in body and str(body.get("resolved_by") or "") != "author":
            raise agent_room.RoomError("agents_cannot_approve", status=403)
        if "approved" not in body or type(body.get("approved")) is not bool:
            # bool("false") is True: a type slip must never become an
            # irreversible approval (B3-19).
            raise agent_room.RoomError(
                "invalid_request",
                detail={"field": "approved", "message": "approved 必须是布尔值"})
        capability = str(body.get("capability") or "").strip()
        missing = []
        if not capability:
            missing = [field for field in ("artifact_fingerprint", "approved_scope_hash")
                       if not str(body.get(field) or "").strip()]
            if "directive_revision" not in body:
                missing.append("directive_revision")
        if missing:
            raise agent_room.RoomError(
                "approval_binding_required", status=400,
                detail={"missing": missing,
                        "message": "审批必须回传卡片绑定的指纹、作用域与指令 revision"})
        directive_revision = None
        if "directive_revision" in body:
            try:
                directive_revision = int(body.get("directive_revision"))
            except (TypeError, ValueError):
                raise agent_room.RoomError("approval_binding_required", status=400,
                                           detail={"field": "directive_revision"}) from None
        return agent_room.resolve_approval(
            room_db, approval_id=approval, approved=body["approved"],
            resolved_by="author",
            artifact_fingerprint=str(body.get("artifact_fingerprint") or ""),
            approved_scope_hash=str(body.get("approved_scope_hash") or ""),
            directive_revision=directive_revision,
            capability=capability or None,
            artifact_checker=lambda item: _artifact_still_valid(identity, item),
            decision=body.get("decision") if isinstance(body.get("decision"), dict) else {"note": str(body.get("note") or "")})

    @app.post("/api/projects/{identity}/chief/route")
    @guard
    def chief_route(identity: str, data: dict | None = None):
        body = data or {}
        return agent_hub.route(str(body.get("message") or body.get("text") or ""))

    @app.post("/api/projects/{identity}/chief/commands")
    @guard
    def chief_command(identity: str, data: dict | None = None):
        body = data or {}
        route = agent_hub.local_route(str(body.get("message") or ""))
        if route is None:
            return {"status": "not_local"}
        return {"status": "local", **route}
