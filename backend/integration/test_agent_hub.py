"""主编三级路由、六大模板、DAG 防线与中途改令。"""
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
