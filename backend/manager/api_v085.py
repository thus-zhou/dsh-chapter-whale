"""v0.8.2 / v0.8.5 API：批注、三方合并、主编室与三级路由。"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from integration import (agent_hub, agent_room, annotations, chapter_editor, costs,
                         maintenance, model_gateway, workbench_db)


def install(app: FastAPI, *, project: Callable[[str], Dict[str, Any]], data_dir: Path) -> None:
    room_db = Path(data_dir) / "agent_room.sqlite3"
    agent_room.initialize(room_db)

    def _book(identity: str) -> Path:
        return Path(project(identity)["path"])

    def _empty_annotations(chapter, against: str, *, degraded: bool = False,
                           reason: str = "") -> dict:
        """Shape-compatible empty page for a missing/unreadable workbench DB.

        审计 C3-04：v0.8.5 的批注列表是只读路径，不能为了列批注创建
        ``workbench.sqlite3``；只读挂载上也不允许 500。形状与
        ``annotations.list_annotations`` 保持一致，额外带 ``degraded`` 标记。
        """
        result = {"chapter_id": int(chapter), "against": against, "annotations": [],
                  "evaluated_draft_id": None, "evaluated_draft_revision": None,
                  "evaluated_text_sha256": None, "evaluated_version_id": None,
                  "offset_unit": "unicode_codepoint_lf"}
        if degraded:
            result["degraded"] = True
            result["degraded_reason"] = reason or "db_unavailable"
        return result

    def guard(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                identity = kwargs.get("identity")
                if identity:
                    # 审计 C3-03：v0.8.5 批次读/写同样会遇到缺表缺列；旧库
                    # 不能只有访问过 v0.9 才被修复。create=False 不建库。
                    maintenance.ensure_schema(_book(identity))
                return fn(*args, **kwargs)
            except (annotations.AnnotationError, agent_room.RoomError, agent_hub.HubError,
                    chapter_editor.ChapterError) as exc:
                return JSONResponse(status_code=exc.status,
                                    content={"code": exc.code, "message": exc.code,
                                             **(getattr(exc, "detail", {}) or {})})
            except sqlite3.OperationalError as exc:
                # 审计 C3-04：只读挂载上的写请求返回 503，而不是 500 并回显路径。
                return JSONResponse(status_code=503,
                                    content={"code": "db_unavailable",
                                             "message": "数据库当前不可写，请检查项目权限"})
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

    def _author_channel(request: Request | None) -> bool:
        # The event body is not identity.  Author-only operations (speaking as
        # the author, claiming an approval capability, resolving cost gaps)
        # require the dedicated author-channel header, which the desktop shell
        # sends; an agent process cannot become the author by JSON alone
        # (B3-17/B4-02).
        return request is not None and request.headers.get("x-novel-author") == "1"

    def _sender_role(body: dict, request: Request | None = None) -> str:
        # A body field is not identity.  Default to system so an agent that
        # omits the field cannot silently speak as the author (B3-17).
        value = str(body.get("sender_role") or "system").strip()
        if value not in SENDER_ROLES:
            raise agent_room.RoomError("invalid_sender_role",
                                       detail={"field": "sender_role"})
        if value == "author" and not _author_channel(request):
            raise agent_room.RoomError(
                "author_channel_required", status=403,
                detail={"field": "sender_role",
                        "message": "作者身份只能经作者通道声明"})
        return value

    def _max_calls(body: dict) -> int:
        value = body.get("max_calls")
        if value is None:
            return 20
        if isinstance(value, bool):
            raise agent_room.RoomError("invalid_request", detail={"field": "max_calls"})
        if isinstance(value, float) and not value.is_integer():
            # 1.9 used to truncate to 1 silently (B4-08).
            raise agent_room.RoomError(
                "invalid_request",
                detail={"field": "max_calls", "message": "max_calls 必须是整数"})
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
        book = _book(identity)
        if not workbench_db.db_path(book).is_file():
            return _empty_annotations(chapter, against)
        try:
            return annotations.list_annotations(book, int(chapter), against=against)
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            text = str(exc).lower()
            if "not a database" in text or "malformed" in text:
                # 审计 C4-05：损坏库是故障，不是空数据；503 带稳定错误码，
                # 不向 LAN 客户端回显绝对路径。
                raise annotations.AnnotationError("db_unavailable", status=503) from None
            return _empty_annotations(chapter, against, degraded=True,
                                      reason="readonly_or_missing_table")

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
        book = _book(identity)
        if not workbench_db.db_path(book).is_file():
            return {"chapter_id": int(chapter), "previews": [], "count": 0}
        try:
            return annotations.list_previews(book, int(chapter))
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            text = str(exc).lower()
            if "not a database" in text or "malformed" in text:
                raise annotations.AnnotationError("db_unavailable", status=503) from None
            return {"chapter_id": int(chapter), "previews": [], "count": 0,
                    "degraded": True, "degraded_reason": "readonly_or_missing_table"}

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
    def chief_message_without_project(request: Request, data: dict | None = None):
        body = data or {}
        session_id = str(body.get("session_id") or "author")
        return agent_room.append_event(
            room_db, session_id=session_id, topic_id=str(body.get("topic_id") or "default"),
            project_id=None, channel="chief_chat", sender_role=_sender_role(body, request),
            kind=str(body.get("kind") or "message"),
            summary=str(body.get("summary") or body.get("text") or ""),
            payload=body.get("payload") or {}, mentions=_seq(body.get("mentions"), "mentions"))

    def _cursor(value) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        # A hostile/corrupt cursor must not overflow SQLite inside the stream
        # generator (B3-24).
        return max(0, min(parsed, 2**63 - 1))

    async def _event_frames(request: Request, *, project_id=None, session_id=None,
                            after: int = 0, fresh: bool = False):
        page_size = 200
        last_ping = time.monotonic()

        async def replay(cursor: int):
            nonlocal after
            while True:
                batch = await asyncio.to_thread(
                    agent_room.events_after, room_db, after_seq=cursor,
                    project_id=project_id, session_id=session_id, limit=page_size)
                for event in batch:
                    yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    cursor = int(event["seq"])
                    after = cursor
                if len(batch) < page_size:
                    break

        token = None
        try:
            yield "retry: 1500\n\n"
            if fresh:
                # No cursor: replay the newest page of *this* scope, never
                # ``global_latest - 200`` (sparse books would skip history).
                page = await asyncio.to_thread(
                    agent_room.recent_events, room_db, project_id=project_id,
                    session_id=session_id, limit=page_size)
                cursor = 0 if not page else max(0, int(page[0]["seq"]) - 1)
            else:
                cursor = after
            async for chunk in replay(cursor):
                yield chunk
            token, queue = agent_room.broadcaster.subscribe(
                project_id=project_id, session_id=None if project_id else session_id)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    # Cross-process writers only touch SQLite/fanout; a short
                    # DB poll keeps the stream live without sharing a loop
                    # (B3-08).
                    batch = await asyncio.to_thread(
                        agent_room.events_after, room_db, after_seq=after,
                        project_id=project_id, session_id=session_id, limit=page_size)
                    delivered = False
                    for event in batch:
                        seq = event.get("seq")
                        yield f"id: {seq}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        if isinstance(seq, int):
                            after = seq
                            delivered = True
                            if token is not None:
                                agent_room.broadcaster.ack(token, seq)
                    if not delivered and time.monotonic() - last_ping >= 15.0:
                        last_ping = time.monotonic()
                        yield ": ping\n\n"
                    continue
                seq = event.get("seq")
                if event.get("kind") == "resync_required":
                    # Tell the client where replay can restart; a bare
                    # ``full_reload`` with seq 0 used to strand the oldest
                    # backlog (B3-07).
                    oldest = await asyncio.to_thread(
                        agent_room.oldest_seq, room_db, project_id=project_id,
                        session_id=session_id)
                    event = {**event, "oldest_available_seq": oldest}
                elif isinstance(seq, int) and seq <= after:
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

    def _stream_response(request: Request, *, project_id=None, session_id=None,
                         last_event_id: str = "", after_seq=None):
        header = request.headers.get("last-event-id") or last_event_id
        if str(header or "").strip():
            # An explicit Last-Event-ID/media cursor, including "0", is a
            # from-scratch paging request rather than the newest-page default.
            after = _cursor(header)
            fresh = False
        elif after_seq is not None:
            # ?after_seq=0 is the deterministic "page from the beginning"
            # path the overflow marker points at (B3-07).
            after = _cursor(after_seq)
            fresh = False
        else:
            after = 0
            fresh = True
        return StreamingResponse(
            _event_frames(request, project_id=project_id, session_id=session_id,
                          after=after, fresh=fresh),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/projects/{identity}/room/stream")
    async def room_stream(identity: str, request: Request, last_event_id: str = "",
                          after_seq: int | None = None):
        """SSE four-channel stream with paged replay, gap-free subscribe and backpressure."""
        return _stream_response(request, project_id=identity,
                                last_event_id=last_event_id, after_seq=after_seq)

    @app.get("/api/chief/room/stream")
    async def chief_room_stream(request: Request, session_id: str = "author",
                                project_id: str | None = None,
                                last_event_id: str = "", after_seq: int | None = None):
        # Pre-book rooms have no project yet; a session-only stream must read
        # only unbound rows (B3-08/B3-22).
        if project_id:
            return _stream_response(request, project_id=project_id,
                                    last_event_id=last_event_id, after_seq=after_seq)
        return _stream_response(request, session_id=session_id,
                                last_event_id=last_event_id, after_seq=after_seq)

    @app.post("/api/projects/{identity}/chief/topics")
    @guard
    def chief_topic(identity: str):
        return agent_room.new_topic(room_db, project_id=identity)

    @app.post("/api/projects/{identity}/chief/messages")
    @guard
    def chief_message(identity: str, request: Request, data: dict | None = None):
        body = data or {}
        session_id = str(body.get("session_id") or "author")
        topic_id = str(body.get("topic_id") or "default")
        agent_room.bind_session_to_project(room_db, session_id=session_id, project_id=identity)
        event = agent_room.append_event(
            room_db, session_id=session_id, topic_id=topic_id, project_id=identity,
            channel=str(body.get("channel") or "chief_chat"),
            sender_role=_sender_role(body, request),
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
        evaluator = None
        if body.get("role_e") is True:
            # Inject the real Role-E evaluator through the single model exit.
            # Any model/parse failure becomes an amendment_fallback card.
            gateway = model_gateway.ModelGateway(
                project=str(_book(identity)), db_path=Path(data_dir) / "costs.sqlite3")
            evaluator = agent_hub.role_e_evaluator(gateway, op_id=f"amend-{amendment}")
        return agent_hub.evaluate_amendment(room_db, amendment_id=amendment,
                                            directive_id=directive,
                                            evaluator=evaluator,
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
        resolved = agent_room.resolve_approval(
            room_db, approval_id=approval, approved=body["approved"],
            resolved_by="author",
            artifact_fingerprint=str(body.get("artifact_fingerprint") or ""),
            approved_scope_hash=str(body.get("approved_scope_hash") or ""),
            directive_revision=directive_revision,
            capability=capability or None,
            artifact_checker=lambda item: _artifact_still_valid(identity, item),
            decision=body.get("decision") if isinstance(body.get("decision"), dict) else {"note": str(body.get("note") or "")})
        # An amendment_fallback card is only useful if approval actually moves
        # the held task; run the consumer here (B3-15).
        followup = agent_hub.consume_approval(room_db, resolved)
        if followup is not None:
            resolved = {**resolved, "followup": followup}
        return resolved

    @app.post("/api/projects/{identity}/approvals/{approval}/capability")
    @guard
    def approve_capability(identity: str, approval: str, request: Request):
        # Author-channel delivery: an agent-created card stores only the hash,
        # so the creator cannot self-approve (B4-02).
        if not _author_channel(request):
            raise agent_room.RoomError(
                "author_channel_required", status=403,
                detail={"message": "审批 capability 只能经作者通道领取"})
        current = agent_room.get_approval(room_db, approval)
        if str(current.get("project_id") or "") != str(identity):
            raise agent_room.RoomError("approval_project_mismatch", status=404)
        return agent_room.issue_capability(room_db, approval)

    @app.post("/api/projects/{identity}/approvals/{approval}/recreate")
    @guard
    def recreate_card(identity: str, approval: str, request: Request):
        if not _author_channel(request):
            raise agent_room.RoomError(
                "author_channel_required", status=403,
                detail={"message": "重建审批卡只能经作者通道发起"})
        current = agent_room.get_approval(room_db, approval)
        if str(current.get("project_id") or "") != str(identity):
            raise agent_room.RoomError("approval_project_mismatch", status=404)
        return agent_room.recreate_approval(room_db, approval)

    @app.post("/api/projects/{identity}/costs/resolve-gaps")
    @guard
    def resolve_cost_gaps(identity: str, request: Request, data: dict | None = None):
        """Author-only release for cost gap markers (R-03 recovery path)."""
        if not _author_channel(request):
            raise agent_room.RoomError(
                "author_channel_required", status=403,
                detail={"message": "成本缺口只能由作者确认解除"})
        body = data or {}
        kind = body.get("kind")
        book = str(Path(project(identity)["path"]).resolve())
        resolved = costs.resolve_gaps(Path(data_dir) / "costs.sqlite3",
                                      kind=str(kind) if kind else None, project=book)
        return {"resolved": resolved, "project": book}

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
