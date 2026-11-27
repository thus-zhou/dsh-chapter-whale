"""v0.8.2 / v0.8.5 API：批注、三方合并、主编室与三级路由。"""
from __future__ import annotations

import asyncio
import functools
import json
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from integration import agent_hub, agent_room, annotations, chapter_editor


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
        return wrapper

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
    def chief_room_state(session_id: str = "author", topic_id: str | None = None):
        return agent_room.snapshot(room_db, session_id=session_id, topic_id=topic_id)

    @app.post("/api/chief/messages")
    @guard
    def chief_message_without_project(data: dict | None = None):
        body = data or {}
        session_id = str(body.get("session_id") or "author")
        return agent_room.append_event(
            room_db, session_id=session_id, topic_id=str(body.get("topic_id") or "default"),
            project_id=None, channel="chief_chat", sender_role=str(body.get("sender_role") or "author"),
            kind=str(body.get("kind") or "message"),
            summary=str(body.get("summary") or body.get("text") or ""),
            payload=body.get("payload") or {}, mentions=body.get("mentions") or [])

    @app.get("/api/projects/{identity}/room/stream")
    async def room_stream(identity: str, request: Request, last_event_id: str = ""):
        """SSE four-channel stream with Last-Event-ID replay and 256-frame backpressure."""
        after = 0
        header = request.headers.get("last-event-id") or last_event_id
        try:
            after = max(0, int(header or 0))
        except ValueError:
            after = 0
        token, queue = agent_room.broadcaster.subscribe(project_id=identity)

        async def frames():
            try:
                yield "retry: 1500\n\n"
                replayed = await asyncio.to_thread(
                    agent_room.events_after, room_db, after_seq=after, project_id=identity)
                for event in replayed:
                    yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield f"id: {event.get('seq', '')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("kind") == "resync_required":
                        break
            finally:
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
            sender_role=str(body.get("sender_role") or "author"),
            kind=str(body.get("kind") or "message"),
            summary=str(body.get("summary") or body.get("text") or ""),
            payload=body.get("payload") or {}, mentions=body.get("mentions") or [])
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
            constraints=body.get("constraints") or [], budget_cap_cny=body.get("budget_cap_cny"),
            max_calls=int(body.get("max_calls") or 20))

    @app.post("/api/projects/{identity}/directives/{directive}/amend")
    @guard
    def amend_directive(identity: str, directive: str, data: dict | None = None):
        body = data or {}
        amendment = agent_hub.start_amendment(
            room_db, directive_id=directive,
            amendment_text=str(body.get("instruction") or body.get("text") or ""),
            task_ids=body.get("task_ids") or [], fallback=str(body.get("fallback") or "wait"))
        return {"directive_id": directive,
                "directive_revision": amendment["directive_revision"],
                "amendment": amendment}

    @app.post("/api/projects/{identity}/directives/{directive}/cancel")
    @guard
    def cancel_directive(identity: str, directive: str):
        return agent_room.update_directive(room_db, directive_id=directive, status="cancelled")

    @app.post("/api/projects/{identity}/directives/{directive}/resume")
    @guard
    def resume_directive(identity: str, directive: str):
        return agent_room.update_directive(room_db, directive_id=directive, status="running")

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
        return agent_room.resolve_approval(
            room_db, approval_id=approval, approved=bool(body.get("approved")),
            resolved_by=str(body.get("resolved_by") or "author"),
            artifact_fingerprint=str(body.get("artifact_fingerprint")
                                     or current.get("artifact_fingerprint") or ""),
            approved_scope_hash=str(body.get("approved_scope_hash")
                                    or current.get("approved_scope_hash") or ""),
            directive_revision=body.get("directive_revision", current.get("directive_revision")),
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
