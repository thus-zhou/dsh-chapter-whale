"""主编三级路由、六大模板、DAG 防线与中途改令。"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from integration import agent_hub as hub
from integration import agent_room as room


class LocalRouteTest(unittest.TestCase):
    def test_zero_call_commands(self):
        self.assertEqual(hub.local_route("全局暂停")["action"], "system_ai_pause")
        self.assertEqual(hub.local_route("暂停这本书的自动任务")["action"], "automation_pause")
        self.assertEqual(hub.local_route("打开第 8 章")["params"]["chapter"], 8)
        self.assertEqual(hub.local_route("今天花了多少钱")["action"], "cost_query")
        self.assertEqual(hub.local_route("执行本章全部批注")["action"], "run_annotations")
        self.assertEqual(hub.local_route("第 3 章那张地图最后谁拿走了？")["action"], "qa_lookup")
        self.assertEqual(hub.local_route("@精修 把这段改克制")["params"]["role"], "editor")

    def test_negated_and_descriptive_sentences_do_not_trigger_side_effects(self):
        # B3-18: negation prefixes and descriptive "所有" sentences must not
        # pause the system or run annotations.
        for text in ("不要全局暂停", "别急停所有角色", "不要执行本章批注",
                     "继续写所有章节", "恢复所有角色的默认设置"):
            self.assertIsNone(hub.local_route(text), text)
        assert_pause = hub.local_route("请立即全局暂停。")
        self.assertTrue(assert_pause["params"]["paused"])
        long_command = hub.local_route("请马上全局暂停，另外把今天的第三章也重写一遍")
        self.assertTrue(long_command["params"]["paused"])
        self.assertTrue(long_command["requires_confirmation"])

    def test_qa_lookup_is_zero_model(self):
        result = hub.qa_lookup("地图谁拿走了", lambda q: [{"snippet": "老周把地图收进抽屉。"}])
        self.assertEqual(result["model_calls"], 0)
        self.assertIn("地图", result["answer"])


class TemplateTest(unittest.TestCase):
    def test_all_six_templates_are_acyclic_and_shallow(self):
        names = ["template_bootstrap_book", "template_plan_and_write", "template_selection_ab",
                 "template_chapter_annotations", "template_book_directive", "template_schedule_preview"]
        for name in names:
            graph = hub.build_template(name, {"count": 2, "chapter": 1})
            self.assertEqual(graph["template"], name)
            self.assertLessEqual(len(graph["nodes"]), hub.MAX_DAG_NODES)

    def test_bootstrap_has_three_ordered_nodes(self):
        graph = hub.build_template("template_bootstrap_book", {"title": "县城悬疑", "count": 3})
        ids = [node["id"] for node in graph["nodes"]]
        self.assertEqual(ids, ["tsk_01", "tsk_02", "tsk_03"])
        self.assertEqual(graph["nodes"][1]["depends_on"], ["tsk_01"])
        self.assertEqual(graph["nodes"][2]["depends_on"], ["tsk_02"])

    def test_route_uses_deterministic_template_without_model(self):
        result = hub.route("开一本县城悬疑，做前十章细纲，直接试写前三章")
        self.assertEqual(result["level"], 1)
        self.assertEqual(result["template"], "template_bootstrap_book")
        self.assertEqual(result["autonomy"], "auto_chain")


class DagGuardTest(unittest.TestCase):
    def node(self, node_id, tool="write_chapter", role="writer", depends=()):
        return {"id": node_id, "tool_name": tool, "role": role, "depends_on": list(depends),
                "params": {}, "title": node_id}

    def test_whitelist_cycle_depth_and_size(self):
        with self.assertRaises(hub.HubError) as caught:
            hub.validate_dag([self.node("a", tool="rm_rf")])
        self.assertEqual(caught.exception.code, "tool_not_allowed")
        with self.assertRaises(hub.HubError) as caught:
            hub.validate_dag([self.node("a", depends=["b"]), self.node("b", depends=["a"])])
        self.assertEqual(caught.exception.code, "dag_cycle")
        chain = [self.node("a"), self.node("b", depends=["a"]),
                 self.node("c", depends=["b"]), self.node("d", depends=["c"])]
        with self.assertRaises(hub.HubError) as caught:
            hub.validate_dag(chain)
        self.assertEqual(caught.exception.code, "dag_too_deep")
        many = [self.node(f"n{i}") for i in range(13)]
        with self.assertRaises(hub.HubError) as caught:
            hub.validate_dag(many)
        self.assertEqual(caught.exception.code, "dag_too_many_nodes")

    def test_planner_gets_two_repairs_then_degrades(self):
        calls = []

        def planner(message, context):
            calls.append(context.get("error"))
            return [self.node("a", tool="not_allowed")]

        result = hub.route("来点复杂的自由编排", planner=planner)
        self.assertEqual(result["level"], 2)
        self.assertTrue(result["degraded"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1], "tool_not_allowed")

    def test_valid_free_dag(self):
        def planner(message, context):
            return [self.node("a", tool="plan_chapters", role="planner"),
                    self.node("b", depends=["a"])]
        result = hub.route("随便编排一个有依赖的复合指令", planner=planner)
        self.assertEqual(result["level"], 2)
        self.assertEqual(result["order"], ["a", "b"])

    def test_risk_metadata_is_exposed_and_flags_approval_nodes(self):
        # B3-20: the tool table's risk column must reach callers.
        validation = hub.validate_dag([
            self.node("a", tool="create_book", role="chief"),
            self.node("b", depends=["a"]),
        ])
        self.assertEqual(validation["risk"], {"a": "high", "b": "low"})
        self.assertEqual(validation["requires_approval"], ["a"])
        self.assertEqual(validation["max_risk"], "high")
        template = hub.route("开一本县城悬疑")
        self.assertEqual(template["level"], 1)
        self.assertEqual(template["max_risk"], "high")
        self.assertIn("tsk_01", template["requires_approval"])
        self.assertEqual(template["risk"]["tsk_01"], "high")

        def planner(message, context):
            return [self.node("a", tool="request_publish_authorization", role="publisher")]
        free = hub.route("来点复杂的自由编排", planner=planner)
        self.assertEqual(free["requires_approval"], ["a"])
        self.assertEqual(free["max_risk"], "high")


class AmendmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "manager.sqlite3"
        room.initialize(self.db)
        self.directive = room.create_directive(self.db, session_id="s", project_id="p",
                                               title="写前三章", raw_instruction="写前三章",
                                               autonomy="auto_chain")
        self.task = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                     project_id="p", role="writer", title="写第2章",
                                     tool_name="write_chapter", status="running")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_amendment_holds_and_evaluates(self):
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="第二章别进山", task_ids=[self.task["id"]])
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        result = hub.evaluate_amendment(self.db, amendment_id=started["amendment_id"],
                                        directive_id=self.directive["id"])
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "pending")

    def test_second_amendment_does_not_release_first_hold(self):
        first = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                    amendment_text="改一", task_ids=[self.task["id"]])
        # 第二次改令覆盖 hold id
        second = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                     amendment_text="改二", task_ids=[self.task["id"]])
        released = hub.release_holds_for_current(self.db, directive_id=self.directive["id"],
                                                 amendment_id=first["amendment_id"])
        self.assertEqual(released, 0)
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        self.assertEqual(room.get_directive(self.db, self.directive["id"])["directive_revision"], 3)

    def test_evaluator_failure_creates_fallback_card(self):
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="改一", task_ids=[self.task["id"]])

        def broken(_):
            raise RuntimeError("model timeout")

        result = hub.evaluate_amendment(self.db, amendment_id=started["amendment_id"],
                                        directive_id=self.directive["id"], evaluator=broken)
        self.assertEqual(result["status"], "fallback")
        approval = result["approval"]
        self.assertEqual(approval["kind"], "amendment_fallback")
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(len(approval["detail"]["choices"]), 3)
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")


class AmendmentPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "manager.sqlite3"
        room.initialize(self.db)
        self.directive = room.create_directive(self.db, session_id="s", project_id="p",
                                               title="写前三章", raw_instruction="写前三章",
                                               autonomy="auto_chain")
        self.task = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                     project_id="p", role="writer", title="写第2章",
                                     tool_name="write_chapter", status="running")

    def tearDown(self):
        self.tmp.cleanup()

    def test_invalid_request_does_not_advance_revision(self):
        with self.assertRaises(hub.HubError) as caught:
            hub.start_amendment(self.db, directive_id=self.directive["id"],
                                amendment_text="改", task_ids=[self.task["id"]], fallback="bogus")
        self.assertEqual(caught.exception.code, "invalid_amendment_fallback")
        self.assertEqual(room.get_directive(self.db, self.directive["id"])["directive_revision"], 1)
        with self.assertRaises(hub.HubError) as caught:
            hub.start_amendment(self.db, directive_id=self.directive["id"],
                                amendment_text="改", task_ids=["tsk_foreign"])
        self.assertEqual(caught.exception.code, "amendment_task_mismatch")
        self.assertEqual(room.get_directive(self.db, self.directive["id"])["directive_revision"], 1)

    def test_amendment_text_persisted_and_update_releases_task(self):
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="第二章别进山", task_ids=[self.task["id"]])
        record = room.get_amendment(self.db, started["amendment_id"])
        self.assertEqual(record["raw_text"], "第二章别进山")
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        result = hub.evaluate_amendment(
            self.db, amendment_id=started["amendment_id"], directive_id=self.directive["id"],
            evaluator=lambda ctx: {"keep": [], "update": [self.task["id"]],
                                   "wait_and_redo": []})
        self.assertEqual(result["status"], "evaluated")
        task = room.get_task(self.db, self.task["id"])
        self.assertEqual(task["status"], "pending")
        self.assertIn("更新", task["wait_reason"])
        self.assertEqual(room.get_amendment(self.db, started["amendment_id"])["status"], "evaluated")

    def test_resume_releases_held_tasks(self):
        hub.start_amendment(self.db, directive_id=self.directive["id"],
                            amendment_text="改", task_ids=[self.task["id"]])
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        resumed = hub.resume_directive(self.db, directive_id=self.directive["id"])
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(resumed["released_tasks"], 1)
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "pending")


class ApprovalLifecycleHubTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "manager.sqlite3"
        room.initialize(self.db)
        self.directive = room.create_directive(self.db, session_id="s", project_id="p",
                                               title="写前三章", raw_instruction="写前三章",
                                               autonomy="auto_chain")
        self.task = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                     project_id="p", role="writer", title="写第2章",
                                     tool_name="write_chapter", status="running")

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, revision=1):
        return room.create_approval(self.db, session_id="s", project_id="p",
                                    directive_id=self.directive["id"],
                                    directive_revision=revision, task_id=None,
                                    kind="publish", title="发布",
                                    artifact_fingerprint="fp", approved_scope_hash="scope",
                                    detail={})

    def test_amendment_supersedes_pending_card(self):
        card = self.card()
        hub.start_amendment(self.db, directive_id=self.directive["id"],
                            amendment_text="改", task_ids=[self.task["id"]])
        item = room.get_approval(self.db, card["id"])
        self.assertEqual(item["status"], "superseded")
        self.assertTrue(item["resolved_at"])
        self.assertEqual(room.pending_approvals(self.db, project_id="p"), [])
        with self.assertRaises(room.RoomError) as caught:
            room.resolve_approval(self.db, card["id"], approved=True,
                                  capability=card["capability"])
        self.assertEqual(caught.exception.code, "approval_not_pending")

    def test_cancel_supersedes_card_and_covers_all_active_states(self):
        waiting_approval = room.create_task(self.db, directive_id=self.directive["id"],
                                            session_id="s", project_id="p", role="writer",
                                            title="等审批", tool_name="write_chapter",
                                            status="awaiting_approval")
        paused = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                  project_id="p", role="writer", title="等预算",
                                  tool_name="write_chapter", status="paused_budget")
        card = self.card()
        hub.cancel_directive(self.db, directive_id=self.directive["id"])
        for task_id in (self.task["id"], waiting_approval["id"], paused["id"]):
            self.assertEqual(room.get_task(self.db, task_id)["status"], "cancelled")
        self.assertEqual(room.get_approval(self.db, card["id"])["status"], "superseded")
        self.assertEqual(room.pending_approvals(self.db, project_id="p"), [])

    def test_resume_supersedes_card_and_requeues_paused_budget(self):
        paused = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                  project_id="p", role="writer", title="等预算",
                                  tool_name="write_chapter", status="paused_budget")
        card = self.card()
        resumed = hub.resume_directive(self.db, directive_id=self.directive["id"])
        self.assertEqual(resumed["released_tasks"], 1)
        self.assertEqual(room.get_task(self.db, paused["id"])["status"], "pending")
        self.assertEqual(room.get_approval(self.db, card["id"])["status"], "superseded")

    def test_amendment_keeps_awaiting_approval_task_and_card_resolvable(self):
        # B4-01: amendment/evaluate must not turn an approval-gated task into
        # pending or supersede the only card.
        waiting = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                   project_id="p", role="writer", title="等审批",
                                   tool_name="publish", status="awaiting_approval")
        card = room.create_approval(self.db, session_id="s", project_id="p",
                                    directive_id=self.directive["id"], directive_revision=1,
                                    task_id=waiting["id"], kind="publish", title="发布",
                                    artifact_fingerprint="fp", approved_scope_hash="scope", detail={})
        amendment = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                        amendment_text="改一句话", task_ids=[waiting["id"]])
        self.assertEqual(room.get_task(self.db, waiting["id"])["status"], "awaiting_approval")
        self.assertEqual(room.get_approval(self.db, card["id"])["status"], "pending")
        hub.evaluate_amendment(self.db, directive_id=self.directive["id"],
                               amendment_id=amendment["amendment_id"])
        self.assertEqual(room.get_task(self.db, waiting["id"])["status"], "awaiting_approval")

    def test_resume_keeps_awaiting_approval_task_and_card(self):
        # R-02: resuming must not turn an approval-gated task into pending.
        waiting = room.create_task(self.db, directive_id=self.directive["id"], session_id="s",
                                   project_id="p", role="writer", title="等审批",
                                   tool_name="publish", status="awaiting_approval")
        card = room.create_approval(self.db, session_id="s", project_id="p",
                                    directive_id=self.directive["id"], directive_revision=1,
                                    task_id=waiting["id"], kind="publish", title="发布",
                                    artifact_fingerprint="fp", approved_scope_hash="scope", detail={})
        hub.resume_directive(self.db, directive_id=self.directive["id"])
        self.assertEqual(room.get_task(self.db, waiting["id"])["status"], "awaiting_approval")
        self.assertEqual(room.get_approval(self.db, card["id"])["status"], "pending")

    def test_amend_and_resume_reject_cancel_committed_after_precheck(self):
        hub.cancel_directive(self.db, directive_id=self.directive["id"])
        stale = dict(self.directive, status="running")
        with mock.patch.object(hub.room, "get_directive", return_value=stale):
            with self.assertRaises(hub.HubError) as caught:
                hub.start_amendment(self.db, directive_id=self.directive["id"],
                                    amendment_text="偷偷复活", task_ids=[])
            self.assertEqual(caught.exception.code, "directive_cancelled")
            with self.assertRaises(hub.HubError) as caught:
                hub.resume_directive(self.db, directive_id=self.directive["id"])
            self.assertEqual(caught.exception.code, "directive_cancelled")
        self.assertEqual(room.get_directive(self.db, self.directive["id"])["status"],
                         "cancelled")

    def test_evaluate_and_release_reject_cancel_committed_after_precheck(self):
        # B4-06: evaluator/release used to rewrite a cancelled amendment to
        # evaluated/released after the pre-check had passed.
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="改一", task_ids=[self.task["id"]])
        hub.cancel_directive(self.db, directive_id=self.directive["id"])
        stale = dict(self.directive, status="running")
        with mock.patch.object(hub.room, "get_directive", return_value=stale):
            with self.assertRaises(hub.HubError) as caught:
                hub.evaluate_amendment(self.db, amendment_id=started["amendment_id"],
                                       directive_id=self.directive["id"])
            self.assertEqual(caught.exception.code, "directive_cancelled")
            with self.assertRaises(hub.HubError) as caught:
                hub.release_holds_for_current(self.db, directive_id=self.directive["id"],
                                              amendment_id=started["amendment_id"])
            self.assertEqual(caught.exception.code, "directive_cancelled")
        amendment = room.get_amendment(self.db, started["amendment_id"])
        self.assertEqual(amendment["status"], "cancelled")
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "cancelled")

    def test_amendment_lifecycle_writes_durable_events(self):
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="改一", task_ids=[self.task["id"]])
        hub.evaluate_amendment(self.db, amendment_id=started["amendment_id"],
                               directive_id=self.directive["id"])
        hub.cancel_directive(self.db, directive_id=self.directive["id"])
        kinds = [row["kind"] for row in room.events_after(self.db, after_seq=0,
                                                          project_id="p")]
        for kind in ("amendment_started", "amendment_evaluated", "directive_cancelled"):
            self.assertIn(kind, kinds)

    def test_role_e_evaluator_parses_model_json(self):
        class Gateway:
            def __init__(self):
                self.calls = []

            def invoke_sync(self, role, messages, **kwargs):
                self.calls.append((role, kwargs))
                return '```json\n{"keep": ["tsk_keep", "tsk_foreign"], "update": [], ' \
                       '"wait_and_redo": ["tsk_redo"]}\n```'

        gateway = Gateway()
        evaluator = hub.role_e_evaluator(gateway, op_id="amend-op")
        result = evaluator({"tasks": [{"id": "tsk_keep", "title": "a", "tool_name": "x",
                                      "status": "held"},
                                     {"id": "tsk_redo", "title": "b", "tool_name": "y",
                                      "status": "held"}],
                            "amendment": {"raw_text": "改"}, "amendment_id": "amd_1"})
        self.assertEqual(result["keep"], ["tsk_keep"])
        self.assertEqual(result["wait_and_redo"], ["tsk_redo"])
        self.assertEqual(gateway.calls[0][0], "E")
        self.assertEqual(gateway.calls[0][1]["stage"], "authorization")

    def test_fallback_card_is_consumed_after_author_approval(self):
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="改一", task_ids=[self.task["id"]])

        def broken(_):
            raise RuntimeError("model timeout")

        result = hub.evaluate_amendment(self.db, amendment_id=started["amendment_id"],
                                        directive_id=self.directive["id"], evaluator=broken)
        self.assertEqual(result["status"], "fallback")
        card = result["approval"]
        self.assertNotIn("capability", card)
        # The agent-created card needs an author-claimed capability.
        capability = room.issue_capability(self.db, card["id"])["capability"]
        resolved = room.resolve_approval(self.db, card["id"], approved=True,
                                         capability=capability)
        self.assertEqual(resolved["status"], "approved")
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        followup = hub.consume_approval(self.db, resolved)
        self.assertEqual(followup["consumed"], "evaluated")
        # Deterministic evaluation releases the held task instead of leaving it
        # frozen forever (B3-15).
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "pending")
        self.assertEqual(room.get_amendment(self.db, started["amendment_id"])["status"],
                         "evaluated")

    def test_repeated_holds_preserve_original_running_status(self):
        first = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                    amendment_text="一改", task_ids=[self.task["id"]])
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        second = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                     amendment_text="二改", task_ids=[self.task["id"]])
        self.assertEqual(second["held_task_ids"], [self.task["id"]])
        released = hub.release_holds_for_current(self.db,
                                                 directive_id=self.directive["id"],
                                                 amendment_id=second["amendment_id"])
        self.assertEqual(released, 1)
        # The original status survives two amendments instead of degrading to
        # pending (B3-14).
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "running")
        self.assertEqual(hub.release_holds_for_current(
            self.db, directive_id=self.directive["id"],
            amendment_id=first["amendment_id"]), 0)

    def test_pending_task_is_held_and_restored_to_pending(self):
        room.update_task(self.db, task_id=self.task["id"], status="pending")
        started = hub.start_amendment(self.db, directive_id=self.directive["id"],
                                      amendment_text="改", task_ids=[self.task["id"]])
        self.assertEqual(started["held_task_ids"], [self.task["id"]])
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "held")
        self.assertEqual(hub.release_holds_for_current(
            self.db, directive_id=self.directive["id"],
            amendment_id=started["amendment_id"]), 1)
        self.assertEqual(room.get_task(self.db, self.task["id"])["status"], "pending")


if __name__ == "__main__":
    unittest.main()
