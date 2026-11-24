"""创作流程状态：只读、零模型调用。"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from integration import workflow


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir()
        (self.root / ".webnovel").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def brief(self, **fields):
        (self.root / ".webnovel" / "creative_brief.json").write_text(
            json.dumps({"brief": fields}, ensure_ascii=False), encoding="utf-8", newline="\n")

    def plan(self, count=1):
        (self.root / ".webnovel" / "story_plan.json").write_text(
            json.dumps({"chapters": [{"id": i + 1, "outline": "细纲"} for i in range(count)]}, ensure_ascii=False),
            encoding="utf-8", newline="\n")

    def chapter(self, number=1):
        (self.root / "正文" / f"第{number}章-起点.md").write_text("正文" * 200, encoding="utf-8", newline="\n")

    def step(self, state, identity):
        return next(item for item in state["steps"] if item["id"] == identity)

    def test_empty_project_points_at_the_idea(self):
        state = workflow.state(self.root)
        self.assertEqual(state["next"], "idea")
        self.assertFalse(self.step(state, "idea")["done"])
        self.assertFalse(self.step(state, "writing")["done"])
        self.assertEqual(state["counts"]["chapters"], 0)

    def test_optional_creative_fields_do_not_block_the_outline(self):
        self.brief(genre="悬疑", premise="失忆者记得死者")
        state = workflow.state(self.root)
        essentials = self.step(state, "essentials")
        self.assertTrue(essentials["done"])
        self.assertIn("文风", essentials["detail"])
        self.assertEqual(state["next"], "direction")

    def test_plan_and_chapter_progress(self):
        state = workflow.state(self.root)
        self.assertFalse(self.step(state, "direction")["done"])
        self.plan(3)
        state = workflow.state(self.root)
        self.assertEqual(state["counts"]["plan_chapters"], 3)
        self.assertFalse(self.step(state, "direction")["done"])
        outline_dir = self.root / "大纲"
        outline_dir.mkdir()
        (outline_dir / "卷一.md").write_text("# 第1章 开端\n主角醒来。\n", encoding="utf-8", newline="\n")
        state = workflow.state(self.root)
        self.assertTrue(self.step(state, "idea")["done"])
        self.assertTrue(self.step(state, "direction")["done"])
        self.assertEqual(state["next"], "writing")
        self.chapter(2)
        state = workflow.state(self.root)
        self.assertTrue(self.step(state, "writing")["done"])
        self.assertIn("最新第 2 章", self.step(state, "writing")["detail"])

    def test_report_marks_results_done(self):
        self.chapter(1)
        self.assertFalse(self.step(workflow.state(self.root), "results")["done"])
        reports = self.root / ".webnovel" / "quality_reports"
        reports.mkdir()
        (reports / "0001-abc.json").write_text(json.dumps({
            "schema_version": 1, "chapter_id": 1, "report_id": "abc",
            "body_sha256": "0" * 64, "version_id": "0" * 64,
            "review_config_hash": "x", "review": {"review_decision": "pass", "needs_revision": False,
            "quality_gate": {"quality_pass": True, "computed": {"total": 90}}},
        }, ensure_ascii=False), encoding="utf-8", newline="\n")
        state = workflow.state(self.root)
        self.assertTrue(self.step(state, "results")["done"])

    def test_state_is_read_only(self):
        self.brief(genre="悬疑", premise="创意", style="短句")
        self.plan(1)
        self.chapter(1)
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        workflow.state(self.root)
        after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_dict_shaped_plan_is_counted_before_an_outline_is_ready(self):
        """A 规划可以是按章号索引的元数据，写作仍需要可识别的细纲。"""
        (self.root / ".webnovel" / "story_plan.json").write_text(json.dumps(
            {"chapters": {"1": {"title": "开端"}, "2": {"title": "转折"}}}, ensure_ascii=False),
            encoding="utf-8", newline="\n")
        state = workflow.state(self.root)
        self.assertEqual(state["counts"]["plan_chapters"], 2)
        self.assertFalse(self.step(state, "direction")["done"])

    def test_sample_count_is_reported(self):
        samples = self.root / ".webnovel" / "samples"
        samples.mkdir()
        (samples / ("a" * 32 + ".txt")).write_text("示范文本", encoding="utf-8", newline="\n")
        (samples / ("a" * 32 + ".json")).write_text(json.dumps({"id": "a" * 32, "name": "sample.txt"}, ensure_ascii=False),
                                                    encoding="utf-8", newline="\n")
        state = workflow.state(self.root)
        self.assertEqual(state["counts"]["samples"], 1)
        self.assertTrue(self.step(state, "samples")["done"])


if __name__ == "__main__":
    unittest.main()
