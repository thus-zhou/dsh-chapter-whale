"""主编室四表、零作品绑定、审批防重放与有界 SSE 广播。"""
import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from integration import agent_room as room


class RoomTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "manager.sqlite3"
        room.initialize(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_does_not_touch_legacy_tables(self):
        db = sqlite3.connect(self.db)
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            db.close()
        for name in ("agent_directives", "agent_tasks", "agent_events", "agent_approvals"):
            self.assertIn(name, tables)
        for legacy in ("projects", "operations", "settings", "request_budget", "usage_events"):
            self.assertNotIn(legacy, tables)

    def test_zero_book_session_binds_in_one_transaction(self):
        directive = room.create_directive(self.db, session_id="prebook_1", project_id=None,
                                          title="县城悬疑", raw_instruction="开一本县城悬疑",
                                          autonomy="auto_chain", max_calls=20)
        task = room.create_task(self.db, directive_id=directive["id"], session_id="prebook_1",
                                project_id=None, role="writer", title="写第一章",
                                tool_name="write_chapter")
        room.append_event(self.db, session_id="prebook_1", project_id=None, directive_id=directive["id"],
                          task_id=task["id"], channel="chief_chat", sender_role="author",
                          kind="text", summary="开一本县城悬疑")
        room.create_approval(self.db, session_id="prebook_1", project_id=None,
                             directive_id=directive["id"], directive_revision=1,
                             task_id=task["id"], kind="publish_authorize", title="发布授权",
                             artifact_fingerprint="fp", approved_scope_hash="scope", detail={})
        bound = room.bind_session_to_project(self.db, session_id="prebook_1", project_id="p1")
        self.assertEqual(bound["updated"]["agent_directives"], 1)
        self.assertEqual(bound["updated"]["agent_tasks"], 1)
        self.assertEqual(bound["updated"]["agent_events"], 1)
        self.assertEqual(bound["updated"]["agent_approvals"], 1)
        self.assertEqual(room.get_directive(self.db, directive["id"])["project_id"], "p1")
        self.assertEqual(room.snapshot(self.db, project_id="p1")["snapshot_seq"], bound["event"]["seq"])

    def test_event_seq_and_snapshot_cursor(self):
        session = "s1"
        first = room.append_event(self.db, session_id=session, project_id="p1", channel="chief_chat",
                                  sender_role="author", kind="text", summary="一")
        second = room.append_event(self.db, session_id=session, project_id="p1", channel="team_room",
                                   sender_role="writer", kind="artifact_card", summary="二")
        self.assertLess(first["seq"], second["seq"])
        self.assertEqual(room.max_seq(self.db, project_id="p1"), second["seq"])
        replay = room.events_after(self.db, after_seq=first["seq"], project_id="p1")
        self.assertEqual([row["seq"] for row in replay], [second["seq"]])
        snapshot = room.snapshot(self.db, project_id="p1")
        self.assertEqual(snapshot["snapshot_seq"], second["seq"])
        self.assertEqual([row["seq"] for row in snapshot["events"]], [first["seq"], second["seq"]])

    def test_topic_isolates_context(self):
        for index in range(3):
            room.append_event(self.db, session_id="s", project_id="p1", topic_id="default",
                              channel="chief_chat", sender_role="author", kind="text",
                              summary=f"旧话题{index}")
        for index in range(2):
            room.append_event(self.db, session_id="s", project_id="p1", topic_id="topic_2",
                              channel="chief_chat", sender_role="author", kind="text",
                              summary=f"新话题{index}")
        old = room.chat_context(self.db, project_id="p1", topic_id="default")
        new = room.chat_context(self.db, project_id="p1", topic_id="topic_2")
        self.assertTrue(all("旧话题" in item["summary"] for item in old))
        self.assertTrue(all("新话题" in item["summary"] for item in new))

    def test_approval_five_checks_and_replay(self):
        directive = room.create_directive(self.db, session_id="s", project_id="p1",
                                          title="范围确认", raw_instruction="改全书")
        approval = room.create_approval(self.db, session_id="s", project_id="p1",
                                        directive_id=directive["id"],
                                        directive_revision=1, task_id="t1", kind="book_scope_confirm",
                                        title="范围确认", artifact_fingerprint="fp1",
                                        approved_scope_hash="scope1", detail={"chapters": [6, 7]})
        capability = approval["capability"]
        # 指纹变化
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="fp2", approved_scope_hash="scope1",
                                  directive_revision=1, capability=capability)
        self.assertEqual(caught.exception.code, "approval_artifact_changed")
        # 调用方 revision 与卡片不一致
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="fp1", approved_scope_hash="scope1",
                                  directive_revision=2, capability=capability)
        self.assertEqual(caught.exception.code, "approval_directive_revision_stale")
        # Agent 自批
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="fp1", approved_scope_hash="scope1",
                                  directive_revision=1, resolved_by="chief", capability=capability)
        self.assertEqual(caught.exception.code, "agents_cannot_approve")
        # 正常批准
        resolved = room.resolve_approval(self.db, approval["id"], approved=True,
                                         artifact_fingerprint="fp1", approved_scope_hash="scope1",
                                         directive_revision=1, decision={"choice": "approve"},
                                         capability=capability)
        self.assertEqual(resolved["status"], "approved")
        # 双击重放
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="fp1", approved_scope_hash="scope1",
                                  directive_revision=1, capability=capability)
        self.assertEqual(caught.exception.code, "approval_not_pending")

    def test_approval_capability_is_required_one_time_and_not_listed(self):
        approval = room.create_approval(self.db, session_id="s", project_id="p1", directive_id=None,
                                        directive_revision=1, task_id=None, kind="publish",
                                        title="发布", artifact_fingerprint="fp",
                                        approved_scope_hash="scope", detail={})
        self.assertTrue(approval["capability"])
        self.assertIsNone(room.get_approval(self.db, approval["id"]).get("capability_hash"))
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="fp", approved_scope_hash="scope",
                                  directive_revision=1)
        self.assertEqual(caught.exception.code, "approval_capability_required")
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  capability="wrong")
        self.assertEqual(caught.exception.code, "approval_capability_invalid")
        resolved = room.resolve_approval(self.db, approval["id"], approved=True,
                                         capability=approval["capability"])
        self.assertEqual(resolved["status"], "approved")
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  capability=approval["capability"])
        self.assertEqual(caught.exception.code, "approval_not_pending")

    def test_pending_approvals_hides_expired_and_dead_cards(self):
        directive = room.create_directive(self.db, session_id="s", project_id="p1",
                                          title="书", raw_instruction="写")
        live = room.create_approval(self.db, session_id="s", project_id="p1",
                                    directive_id=directive["id"], directive_revision=1,
                                    task_id=None, kind="publish", title="有效",
                                    artifact_fingerprint="fp", approved_scope_hash="scope",
                                    detail={})
        room.create_approval(self.db, session_id="s", project_id="p1",
                             directive_id=directive["id"], directive_revision=1,
                             task_id=None, kind="publish", title="过期",
                             artifact_fingerprint="fp", approved_scope_hash="scope",
                             detail={}, ttl_minutes=-1)
        room.bump_directive_revision(self.db, directive["id"])
        self.assertEqual([item["id"] for item in
                          room.pending_approvals(self.db, project_id="p1")], [])
        # A live card at the current revision is still listed, without
        # replayable binding fields.
        current = room.create_approval(self.db, session_id="s", project_id="p1",
                                       directive_id=directive["id"], directive_revision=2,
                                       task_id=None, kind="publish", title="当前",
                                       artifact_fingerprint="fp", approved_scope_hash="scope",
                                       detail={})
        listed = room.pending_approvals(self.db, project_id="p1")
        self.assertEqual([item["id"] for item in listed], [current["id"]])
        for field in ("artifact_fingerprint", "approved_scope_hash", "directive_revision",
                      "capability_hash"):
            self.assertNotIn(field, listed[0])
        self.assertEqual(room.get_approval(self.db, live["id"])["status"], "pending")

    def test_resolve_rejects_cancelled_or_amended_live_directive(self):
        directive = room.create_directive(self.db, session_id="s", project_id="p1",
                                          title="书", raw_instruction="写")
        amended = room.create_approval(self.db, session_id="s", project_id="p1",
                                       directive_id=directive["id"], directive_revision=1,
                                       task_id=None, kind="publish", title="改令前",
                                       artifact_fingerprint="fp", approved_scope_hash="scope",
                                       detail={})
        room.bump_directive_revision(self.db, directive["id"])
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, amended["id"], approved=True,
                                  capability=amended["capability"])
        self.assertEqual(caught.exception.code, "approval_directive_revision_stale")
        # A cancelled directive cannot be approved even by a newly-created
        # pending card.
        agent_room_hub = __import__("integration.agent_hub", fromlist=["cancel_directive"])
        agent_room_hub.cancel_directive(self.db, directive_id=directive["id"])
        late = room.create_approval(self.db, session_id="s", project_id="p1",
                                    directive_id=directive["id"], directive_revision=2,
                                    task_id=None, kind="publish", title="取消后",
                                    artifact_fingerprint="fp", approved_scope_hash="scope",
                                    detail={})
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, late["id"], approved=True,
                                  capability=late["capability"])
        self.assertEqual(caught.exception.code, "approval_directive_cancelled")

    def test_expired_approval(self):
        approval = room.create_approval(self.db, session_id="s", project_id="p1", directive_id=None,
                                        directive_revision=1, task_id=None, kind="publish_authorize",
                                        title="发布", artifact_fingerprint="fp",
                                        approved_scope_hash="scope", detail={}, ttl_minutes=-1)
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="fp", approved_scope_hash="scope",
                                  directive_revision=1, capability=approval["capability"])
        self.assertEqual(caught.exception.code, "approval_expired")
        self.assertEqual(room.get_approval(self.db, approval["id"])["status"], "expired")

    def test_legacy_card_requires_binding_even_with_a_capability(self):
        # R-04: a legacy card has no capability_hash; an arbitrary non-empty
        # capability must not bypass the binding-echo requirement.
        approval = room.create_approval(self.db, session_id="s", project_id="p1",
                                        directive_id=None, directive_revision=1,
                                        task_id=None, kind="publish", title="发布",
                                        artifact_fingerprint="fp", approved_scope_hash="scope",
                                        detail={})
        db = sqlite3.connect(self.db)
        try:
            db.execute("UPDATE agent_approvals SET capability_hash=NULL WHERE id=?", (approval["id"],))
            db.commit()
        finally:
            db.close()
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  capability="anything", resolved_by="author")
        self.assertEqual(caught.exception.code, "approval_binding_required")


class BroadcasterTest(unittest.TestCase):
    def test_slow_client_gets_resync_and_is_dropped(self):
        broadcaster = room.BoundedBroadcaster(maxsize=2)
        event = room.append_event

        async def scenario():
            token, queue = broadcaster.subscribe()
            # 填满并溢出：持久事件应清空队列后下发 resync_required 并断开
            broadcaster.publish({"kind": "artifact_card", "seq": 1, "summary": "a"})
            broadcaster.publish({"kind": "artifact_card", "seq": 2, "summary": "b"})
            broadcaster.publish({"kind": "artifact_card", "seq": 3, "summary": "c"})
            await asyncio.sleep(0.05)
            item = await asyncio.wait_for(queue.get(), timeout=1)
            self.assertEqual(item["kind"], "resync_required")
            await asyncio.sleep(0.05)
            self.assertEqual(broadcaster.subscriber_count(), 0)

        asyncio.run(scenario())

    def test_transient_overflow_is_dropped_without_disconnect(self):
        broadcaster = room.BoundedBroadcaster(maxsize=1)

        async def scenario():
            token, queue = broadcaster.subscribe()
            broadcaster.publish({"kind": "progress_signal", "seq": 1, "summary": "50%"})
            broadcaster.publish({"kind": "progress_signal", "seq": 2, "summary": "60%"})
            await asyncio.sleep(0.05)
            item = await asyncio.wait_for(queue.get(), timeout=1)
            self.assertEqual(item["summary"], "50%")
            self.assertEqual(broadcaster.subscriber_count(), 1)

        asyncio.run(scenario())


class IsolationAndResyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "manager.sqlite3"
        room.initialize(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_snapshot_never_aggregates_other_books(self):
        room.append_event(self.db, session_id="author", project_id="p1", summary="A 书机密")
        room.append_event(self.db, session_id="author", project_id="p2", summary="B 书机密")
        room.append_event(self.db, session_id="author", project_id=None, summary="未绑定对话")
        self.assertEqual([row["summary"] for row in
                          room.snapshot(self.db, project_id="p1")["events"]], ["A 书机密"])
        session = room.snapshot(self.db, session_id="author")
        self.assertEqual([row["summary"] for row in session["events"]], ["未绑定对话"])
        self.assertEqual(session["snapshot_seq"], session["events"][0]["seq"])

    def test_null_project_event_is_not_broadcast_to_book_subscribers(self):
        broadcaster = room.BoundedBroadcaster(maxsize=8)

        async def scenario():
            token_a, queue_a = broadcaster.subscribe(project_id="book-a")
            token_s, queue_s = broadcaster.subscribe(session_id="author")
            broadcaster.publish({"kind": "artifact_card", "seq": 1, "project_id": None,
                                 "session_id": "author", "summary": "未绑定"})
            broadcaster.publish({"kind": "artifact_card", "seq": 2, "project_id": "book-b",
                                 "session_id": "author", "summary": "B 书"})
            await asyncio.sleep(0.05)
            self.assertTrue(queue_a.empty())
            self.assertEqual((await asyncio.wait_for(queue_s.get(), 1))["summary"], "未绑定")
            broadcaster.unsubscribe(token_a)
            broadcaster.unsubscribe(token_s)

        asyncio.run(scenario())

    def test_resync_marker_uses_last_delivered_seq(self):
        broadcaster = room.BoundedBroadcaster(maxsize=1)

        async def scenario():
            token, queue = broadcaster.subscribe(project_id="p1")
            broadcaster.publish({"kind": "artifact_card", "seq": 1, "project_id": "p1", "summary": "一"})
            await asyncio.sleep(0.05)
            self.assertFalse(queue.empty())
            broadcaster.publish({"kind": "artifact_card", "seq": 2, "project_id": "p1", "summary": "二"})
            await asyncio.sleep(0.05)
            marker = await asyncio.wait_for(queue.get(), 1)
            self.assertEqual(marker["kind"], "resync_required")
            # No frame was ever yielded to the client, so the delivered cursor
            # is still 0; using the enqueue seq here would make the client skip
            # events 1..N on reconnect.
            self.assertEqual(marker["seq"], 0)
            self.assertTrue(marker["full_reload"])
            self.assertTrue(marker["resync_required"])
            self.assertEqual(broadcaster.subscriber_count(), 0)

        asyncio.run(scenario())

    def test_resolve_requires_card_binding_fields(self):
        approval = room.create_approval(self.db, session_id="s", project_id="p1", directive_id=None,
                                        directive_revision=1, task_id=None, kind="publish",
                                        title="发布", artifact_fingerprint="fp",
                                        approved_scope_hash="scope", detail={})
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, approval["id"], approved=True,
                                  artifact_fingerprint="", approved_scope_hash="")
        self.assertEqual(caught.exception.code, "approval_binding_required")


if __name__ == "__main__":
    unittest.main()
