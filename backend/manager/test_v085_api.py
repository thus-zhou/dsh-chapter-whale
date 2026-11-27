"""v0.8.2/v0.8.5 API：批注与主编室。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module
from integration import agent_room


class V085ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-v085-api-")
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json")]
        for item in self.patches:
            item.start()
        self.app = module.create_app(self.root / "manager.db", start_dispatcher=False)
        self.client = TestClient(self.app)
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "v085"}),
                                                               encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)},
                                    headers=self.headers)
        self.identity = response.json()["id"]
        created = self.client.post(f"/api/projects/{self.identity}/chapters",
                                   json={"chapter": 1, "title": "开端",
                                         "content": "她推开门。\n\n屋里很冷。\n"},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_chapter_scope_annotation_lifecycle(self):
        base = f"/api/projects/{self.identity}/chapters/1/annotations"
        created = self.client.post(base, json={"scope": "chapter",
                                               "instruction": "前半章太慢，合并两场问话"},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)
        annotation_id = created.json()["id"]
        listing = self.client.get(base)
        self.assertEqual(listing.json()["annotations"][0]["id"], annotation_id)
        updated = self.client.patch(base + f"/{annotation_id}",
                                    json={"status": "rejected"}, headers=self.headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        deleted = self.client.delete(base + f"/{annotation_id}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_chief_message_directive_and_route(self):
        base = f"/api/projects/{self.identity}/chief"
        message = self.client.post(base + "/messages",
                                   json={"session_id": "author", "text": "今天写两章"},
                                   headers=self.headers)
        self.assertEqual(message.status_code, 200, message.text)
        self.assertEqual(message.json()["channel"], "chief_chat")
        self.assertEqual(message.json()["sender_role"], "system")
        snapshot = self.client.get(base)
        self.assertGreaterEqual(snapshot.json()["snapshot_seq"], 1)
        directive = self.client.post(base + "/directives",
                                     json={"title": "今日", "instruction": "写两章",
                                           "autonomy": "step_confirm"},
                                     headers=self.headers)
        self.assertEqual(directive.status_code, 200, directive.text)
        self.assertTrue(directive.json()["id"].startswith("dir_"))
        route = self.client.post(base + "/route", json={"message": "列出所有角色"},
                                 headers=self.headers)
        self.assertEqual(route.status_code, 200, route.text)
        self.assertIn("level", route.json())

    def test_author_resolves_approval_with_fingerprint_bound_card(self):
        db = self.root / "agent_room.sqlite3"
        directive = agent_room.create_directive(
            db, session_id="author", project_id=self.identity, title="发布",
            raw_instruction="发布")
        approval = agent_room.create_approval(
            db, session_id="author", project_id=self.identity, directive_id=directive["id"],
            directive_revision=1, task_id=None, kind="publish", title="发布确认",
            artifact_fingerprint="fp-1", approved_scope_hash="scope-1", detail={})
        response = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True, "note": "作者确认",
                  "capability": approval["capability"]}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")
        self.assertEqual(response.json()["resolved_by"], "author")
        self.assertEqual(response.json()["decision"]["note"], "作者确认")

    def test_approval_get_does_not_expose_replayable_binding_fields(self):
        db = self.root / "agent_room.sqlite3"
        directive = agent_room.create_directive(
            db, session_id="author", project_id=self.identity, title="发布",
            raw_instruction="发布")
        approval = agent_room.create_approval(
            db, session_id="author", project_id=self.identity, directive_id=directive["id"],
            directive_revision=1, task_id=None, kind="publish", title="发布确认",
            artifact_fingerprint="fp-secret", approved_scope_hash="scope-secret", detail={})
        listing = self.client.get(f"/api/projects/{self.identity}/approvals").json()["approvals"]
        row = next(item for item in listing if item["id"] == approval["id"])
        for field in ("artifact_fingerprint", "approved_scope_hash", "directive_revision",
                      "capability_hash"):
            self.assertNotIn(field, row)
        # Even a caller that knows the stored values cannot self-approve: the
        # card requires the creator's one-time capability (B3-01).
        response = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True, "artifact_fingerprint": "fp-secret",
                  "approved_scope_hash": "scope-secret", "directive_revision": 1},
            headers=self.headers)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["code"], "approval_capability_required")

    def test_approval_requires_strict_boolean(self):
        db = self.root / "agent_room.sqlite3"
        approval = agent_room.create_approval(
            db, session_id="author", project_id=self.identity, directive_id=None,
            directive_revision=1, task_id=None, kind="publish", title="发布确认",
            artifact_fingerprint="fp", approved_scope_hash="scope", detail={})
        base = f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve"
        for body in ({"capability": approval["capability"]},
                     {"approved": "false", "capability": approval["capability"]},
                     {"approved": 0, "capability": approval["capability"]},
                     {"approved": None, "capability": approval["capability"]}):
            response = self.client.post(base, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 400, (body, response.text))
            self.assertEqual(response.json()["code"], "invalid_request")
        self.assertEqual(agent_room.get_approval(db, approval["id"])["status"], "pending")
        ok = self.client.post(base, json={"approved": True,
                                          "capability": approval["capability"]},
                              headers=self.headers)
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_approval_dies_with_amend_or_cancel(self):
        db = self.root / "agent_room.sqlite3"
        for action in ("amend", "cancel"):
            directive = agent_room.create_directive(
                db, session_id="author", project_id=self.identity,
                title=action, raw_instruction="写")
            approval = agent_room.create_approval(
                db, session_id="author", project_id=self.identity,
                directive_id=directive["id"], directive_revision=1, task_id=None,
                kind="publish", title="发布确认", artifact_fingerprint="fp",
                approved_scope_hash="scope", detail={})
            if action == "amend":
                changed = self.client.post(
                    f"/api/projects/{self.identity}/directives/{directive['id']}/amend",
                    json={"instruction": "改方向", "task_ids": []}, headers=self.headers)
            else:
                changed = self.client.post(
                    f"/api/projects/{self.identity}/directives/{directive['id']}/cancel",
                    headers=self.headers)
            self.assertEqual(changed.status_code, 200, changed.text)
            response = self.client.post(
                f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
                json={"approved": True, "capability": approval["capability"]},
                headers=self.headers)
            self.assertEqual(response.status_code, 409, (action, response.text))
            self.assertEqual(response.json()["code"], "approval_not_pending")

    def test_agent_cannot_resolve_approval(self):
        db = self.root / "agent_room.sqlite3"
        approval = agent_room.create_approval(
            db, session_id="author", project_id=self.identity, directive_id="dir_2",
            directive_revision=1, task_id=None, kind="publish", title="发布确认",
            artifact_fingerprint="fp-2", approved_scope_hash="scope-2", detail={})
        response = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True, "resolved_by": "agent"}, headers=self.headers)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["code"], "agents_cannot_approve")


    def _second_project(self) -> str:
        other = self.root / "book-b"
        (other / "正文").mkdir(parents=True)
        (other / ".webnovel").mkdir()
        (other / ".webnovel" / "state.json").write_text(json.dumps({"title": "另一本"}),
                                                        encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(other)},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def test_approval_requires_card_binding_fields(self):
        db = self.root / "agent_room.sqlite3"
        directive = agent_room.create_directive(
            db, session_id="author", project_id=self.identity, title="绑定",
            raw_instruction="绑定")
        approval = agent_room.create_approval(
            db, session_id="author", project_id=self.identity, directive_id=directive["id"],
            directive_revision=1, task_id=None, kind="publish", title="发布确认",
            artifact_fingerprint="fp-bind", approved_scope_hash="scope-bind", detail={})
        missing = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True}, headers=self.headers)
        self.assertEqual(missing.status_code, 400, missing.text)
        self.assertEqual(missing.json()["code"], "approval_binding_required")
        spoofed = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True, "resolved_by": "author"}, headers=self.headers)
        self.assertEqual(spoofed.status_code, 400, spoofed.text)
        self.assertEqual(spoofed.json()["code"], "approval_binding_required")
        stale = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True, "artifact_fingerprint": "fp-edited",
                  "approved_scope_hash": "scope-bind", "directive_revision": 1,
                  "capability": approval["capability"]},
            headers=self.headers)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["code"], "approval_artifact_changed")
        agent_claim = self.client.post(
            f"/api/projects/{self.identity}/approvals/{approval['id']}/resolve",
            json={"approved": True, "resolved_by": "chief",
                  "artifact_fingerprint": "fp-bind", "approved_scope_hash": "scope-bind",
                  "directive_revision": 1, "capability": approval["capability"]},
            headers=self.headers)
        self.assertEqual(agent_claim.status_code, 403, agent_claim.text)

    def test_room_state_and_directive_endpoints_are_book_scoped(self):
        other = self._second_project()
        for identity, text in ((self.identity, "A 书机密"), (other, "B 书机密")):
            response = self.client.post(
                f"/api/projects/{identity}/chief/messages",
                json={"session_id": "author", "text": text}, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
        bare = self.client.get("/api/chief/room/state", params={"session_id": "author"})
        self.assertEqual(bare.status_code, 200, bare.text)
        self.assertEqual(bare.json()["events"], [])
        own = self.client.get(f"/api/projects/{self.identity}/room/state")
        self.assertEqual([row["summary"] for row in own.json()["events"]], ["A 书机密"])
        directive = self.client.post(
            f"/api/projects/{self.identity}/chief/directives",
            json={"title": "A", "instruction": "写两章"}, headers=self.headers).json()
        cancelled = self.client.post(
            f"/api/projects/{other}/directives/{directive['id']}/cancel", headers=self.headers)
        self.assertEqual(cancelled.status_code, 404, cancelled.text)
        self.assertEqual(cancelled.json()["code"], "directive_project_mismatch")
        self.assertEqual(agent_room.get_directive(
            self.root / "agent_room.sqlite3", directive["id"])["status"], "planning")

    def test_amend_evaluate_release_and_resume_paths(self):
        directive = self.client.post(
            f"/api/projects/{self.identity}/chief/directives",
            json={"title": "改令", "instruction": "写三章"}, headers=self.headers).json()
        db_path = self.root / "agent_room.sqlite3"
        task = agent_room.create_task(db_path, directive_id=directive["id"], session_id="author",
                                      project_id=self.identity, role="writer", title="写第二章",
                                      tool_name="write_chapter", status="running")
        started = self.client.post(
            f"/api/projects/{self.identity}/directives/{directive['id']}/amend",
            json={"instruction": "第二章别进山", "task_ids": [task["id"]]},
            headers=self.headers)
        self.assertEqual(started.status_code, 200, started.text)
        amendment_id = started.json()["amendment"]["amendment_id"]
        self.assertEqual(agent_room.get_task(db_path, task["id"])["status"], "held")
        evaluated = self.client.post(
            f"/api/projects/{self.identity}/directives/{directive['id']}/amendments/"
            f"{amendment_id}/evaluate", json={}, headers=self.headers)
        self.assertEqual(evaluated.status_code, 200, evaluated.text)
        self.assertEqual(agent_room.get_task(db_path, task["id"])["status"], "pending")
        self.assertEqual(agent_room.get_amendment(db_path, amendment_id)["raw_text"], "第二章别进山")

        agent_room.update_task(db_path, task_id=task["id"], status="running")
        second = self.client.post(
            f"/api/projects/{self.identity}/directives/{directive['id']}/amend",
            json={"instruction": "再改", "task_ids": [task["id"]]}, headers=self.headers).json()
        released = self.client.post(
            f"/api/projects/{self.identity}/directives/{directive['id']}/amendments/"
            f"{second['amendment']['amendment_id']}/release", headers=self.headers)
        self.assertEqual(released.status_code, 200, released.text)
        self.assertEqual(agent_room.get_task(db_path, task["id"])["status"], "running")

        third = self.client.post(
            f"/api/projects/{self.identity}/directives/{directive['id']}/amend",
            json={"instruction": "三改", "task_ids": [task["id"]]}, headers=self.headers)
        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(agent_room.get_task(db_path, task["id"])["status"], "held")
        resumed = self.client.post(
            f"/api/projects/{self.identity}/directives/{directive['id']}/resume",
            headers=self.headers)
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["released_tasks"], 1)
        self.assertEqual(agent_room.get_task(db_path, task["id"])["status"], "pending")

    def test_scalar_list_fields_return_400_not_500(self):
        base = f"/api/projects/{self.identity}/chapters/1"
        responses = [
            self.client.post(base + "/revision/apply-hunks",
                             json={"op_id": "scalar-1", "hunk_ids": 123}, headers=self.headers),
            self.client.post(base + "/annotations/run",
                             json={"op_id": "scalar-2", "annotation_ids": 123},
                             headers=self.headers),
            self.client.post(f"/api/projects/{self.identity}/chief/messages",
                             json={"text": "x", "mentions": 123}, headers=self.headers),
            self.client.post(f"/api/projects/{self.identity}/chief/directives",
                             json={"title": "x", "instruction": "y", "constraints": 123},
                             headers=self.headers),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(response.json()["code"], "invalid_request")

    def test_invalid_directive_limits_and_budget_are_400(self):
        base = f"/api/projects/{self.identity}/chief/directives"
        for payload in ({"max_calls": 0}, {"max_calls": -1}, {"max_calls": 10**30},
                        {"max_calls": "many"}, {"max_calls": True},
                        {"budget_cap_cny": {}}, {"budget_cap_cny": []},
                        {"budget_cap_cny": "not-a-number"}, {"budget_cap_cny": True},
                        {"budget_cap_cny": "-1"}):
            response = self.client.post(base, json={"title": "x", "instruction": "y", **payload},
                                        headers=self.headers)
            self.assertEqual(response.status_code, 400, (payload, response.text))
            self.assertEqual(response.json()["code"], "invalid_request", payload)
        ok = self.client.post(base, json={"title": "x", "instruction": "y",
                                          "max_calls": 0.5, "budget_cap_cny": "1.5"},
                              headers=self.headers)
        # 0.5 truncates to 0 and is rejected; a valid numeric cap alone works.
        self.assertEqual(ok.status_code, 400, ok.text)
        good = self.client.post(base, json={"title": "x", "instruction": "y",
                                            "max_calls": 2, "budget_cap_cny": "1.5"},
                                headers=self.headers)
        self.assertEqual(good.status_code, 200, good.text)
        self.assertEqual(good.json()["budget_cap_cny"], "1.5")

    def test_message_default_sender_role_is_system(self):
        base = f"/api/projects/{self.identity}/chief"
        message = self.client.post(base + "/messages", json={"text": "随便聊聊"},
                                   headers=self.headers)
        self.assertEqual(message.status_code, 200, message.text)
        self.assertEqual(message.json()["sender_role"], "system")
        explicit = self.client.post(base + "/messages",
                                    json={"text": "作者本人", "sender_role": "author"},
                                    headers=self.headers)
        self.assertEqual(explicit.json()["sender_role"], "author")
        bad = self.client.post(base + "/messages",
                               json={"text": "冒充", "sender_role": "root"},
                               headers=self.headers)
        self.assertEqual(bad.status_code, 400, bad.text)

    def _stream_ids(self, after: int, expected: int):
        async def collect():
            endpoint = next(route.endpoint for route in self.app.routes
                            if getattr(route, "path", "") == "/api/projects/{identity}/room/stream")

            class ImmediateDisconnect:
                headers: dict = {}

                async def is_disconnected(self):
                    return True

            response = await endpoint(self.identity, ImmediateDisconnect(), str(after))
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            ids = []
            for line in "".join(chunks).splitlines():
                if line.startswith("id: ") and line[4:].strip():
                    ids.append(int(line[4:].strip()))
            return ids

        ids = asyncio.run(collect())
        self.assertGreaterEqual(len(ids), expected)
        return ids[:expected]

    def test_sse_replays_every_page_and_never_duplicates(self):
        db_path = self.root / "agent_room.sqlite3"
        for index in range(230):
            agent_room.append_event(db_path, session_id="author", project_id=self.identity,
                                    channel="task_signal", sender_role="system",
                                    kind="task_update", summary=f"事件 {index}")
        recent = self._stream_ids(0, 200)
        self.assertEqual(len(recent), 200)
        self.assertEqual(len(set(recent)), 200)
        # A fresh connection keeps the most recent 200 (seq 31..230), so the
        # 201..230 backlog is no longer skipped forever.
        self.assertEqual(recent[0], 31)
        self.assertEqual(recent[-1], 230)
        resumed = self._stream_ids(100, 130)
        self.assertEqual(resumed[0], 101)
        self.assertEqual(resumed[-1], 230)
        self.assertEqual(len(resumed), len(set(resumed)))
        paged = self._stream_ids(1, 229)
        self.assertEqual(paged[0], 2)
        self.assertEqual(paged[-1], 230)
        self.assertEqual(len(paged), 229)
        self.assertEqual(len(paged), len(set(paged)))

    def test_sse_fresh_replay_is_project_scoped_not_global_window(self):
        db_path = self.root / "agent_room.sqlite3"
        first = [agent_room.append_event(
            db_path, session_id="author", project_id=self.identity,
            channel="task_signal", sender_role="system", kind="task_update",
            summary=f"A {index}")["seq"] for index in range(100)]
        for index in range(156):
            agent_room.append_event(db_path, session_id="other", project_id="other-book",
                                    channel="task_signal", sender_role="system",
                                    kind="task_update", summary=f"B {index}")
        second = [agent_room.append_event(
            db_path, session_id="author", project_id=self.identity,
            channel="task_signal", sender_role="system", kind="task_update",
            summary=f"A late {index}")["seq"] for index in range(44)]
        ids = self._stream_ids(0, 144)
        # The global seq is sparse for this book; fresh replay must still
        # include all 144 of its own events, not only the last 44 (B3-07).
        self.assertEqual(ids, first + second)

    def test_sse_huge_cursor_is_clamped(self):
        ids = self._stream_ids(10**30, 0)
        self.assertEqual(ids, [])


if __name__ == "__main__":
    unittest.main()
