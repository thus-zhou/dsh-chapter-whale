"""M04 文风学习：隔离目录、纯离线，不调用任何模型。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import style_profile, style_stats, studio
from integration import writer_runner as writer

SAMPLE_A = "他说：「走吧。」她没有回答。\n" * 60
SAMPLE_B = "风从窗外吹进来，桌上的纸翻了一页，他抬手压住，又继续写下去。\n" * 40


def make_project(root):
    project = Path(root)
    (project / ".webnovel").mkdir(parents=True)
    (project / ".webnovel" / "creative_brief.json").write_text(
        json.dumps({"schema": 1, "revision": 1, "brief": {"genre": "悬疑", "style": "短句"},
                    "history": []}, ensure_ascii=False), encoding="utf-8")
    return project


class StyleStatsTests(unittest.TestCase):
    def test_statistics_are_reproducible_and_labelled(self):
        first = style_stats.statistics(SAMPLE_A)
        second = style_stats.statistics(SAMPLE_A)
        self.assertEqual(first, second)
        self.assertGreater(first["dialogue_ratio"], 0)
        self.assertIn("程序统计", first["note"])
        self.assertGreaterEqual(first["punctuation"].get("。", 0), 1)

    def test_sample_plan_stays_within_budget(self):
        text = SAMPLE_A * 200
        plan = style_stats.sample_plan(text, 42000)
        self.assertLessEqual(sum(item["length"] for item in plan), 42000)
        self.assertEqual(plan[0]["label"], "开头")
        self.assertEqual(plan[-1]["label"], "结尾")
        for item in plan:
            self.assertLessEqual(item["start"] + item["length"], len(text))
        short = style_stats.sample_plan("短短一段。", 42000)
        self.assertEqual(short[0]["label"], "全文")

    def test_summary_marks_program_statistics(self):
        rows = style_stats.summary(style_stats.statistics(SAMPLE_A))
        self.assertTrue(any("程序统计" in row for row in rows))


class StyleProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-style-")
        self.project = make_project(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_records_statistics_and_degrades_to_limited(self):
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        view = style_profile.public(self.project)
        self.assertEqual(view["status"], "limited")
        self.assertEqual(len(view["samples"]), 1)
        self.assertEqual(view["samples"][0]["sample_id"], record["id"])
        self.assertGreater(view["samples"][0]["characters"], 0)
        self.assertEqual(view["samples"][0]["state"], "stats_only")
        self.assertEqual(view["instruction"], "")

    def test_learning_result_marks_ready_and_injects_guide(self):
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        style_profile.after_learn(self.project, record["id"], guide="短句推进，对话留白。", segments=1)
        view = style_profile.public(self.project)
        self.assertEqual(view["status"], "ready")
        effective = style_profile.effective(self.project)
        self.assertIn("短句推进", effective["guide"])
        self.assertIn("参考强度 60/100", effective["instruction"])

    def test_failure_keeps_statistics(self):
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        style_profile.mark_failed(self.project, record["id"], "模型超时")
        entry = style_profile.read(self.project)["samples"][record["id"]]
        self.assertEqual(entry["state"], "failed")
        self.assertGreater(entry["stats"]["characters"], 0)
        self.assertEqual(style_profile.public(self.project)["status"], "limited")

    def test_options_persist_and_digest_changes(self):
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        style_profile.after_learn(self.project, record["id"], guide="短句。")
        before = style_profile.digest(project=self.project)
        style_profile.options(self.project, strength=85, overrides={"style": "少用形容词"})
        after = style_profile.digest(project=self.project)
        self.assertNotEqual(before, after)
        kept = style_profile.read(self.project)
        self.assertEqual(kept["strength"], 85)
        self.assertEqual(kept["overrides"], {"style": "少用形容词"})
        style_profile.options(self.project, enabled=False)
        self.assertEqual(style_profile.digest(project=self.project), "")
        self.assertEqual(style_profile.effective(self.project)["guide"], "")

    def test_invalid_strength_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 到 100"):
            style_profile.options(self.project, strength=101)

    def test_merged_statistics_are_weighted_by_characters(self):
        first = studio.upload(self.project, "a.txt", SAMPLE_A.encode("utf-8"))
        second = studio.upload(self.project, "b.txt", SAMPLE_B.encode("utf-8"))
        merged = style_profile.public(self.project)["stats"]
        self.assertEqual(merged["characters"], len(SAMPLE_A) + len(SAMPLE_B))
        low = style_profile.read(self.project)["samples"][second["id"]]["stats"]["dialogue_ratio"]
        high = style_profile.read(self.project)["samples"][first["id"]]["stats"]["dialogue_ratio"]
        self.assertGreater(merged["dialogue_ratio"], low)
        self.assertLessEqual(merged["dialogue_ratio"], high)

    def test_delete_removes_files_and_profile_entry(self):
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        style_profile.after_learn(self.project, record["id"], guide="短句。")
        studio.delete_sample(self.project, record["id"])
        self.assertEqual(style_profile.read(self.project)["samples"], {})
        self.assertEqual(studio.sample_list(self.project), [])
        self.assertFalse((self.project / ".webnovel" / "samples" / (record["id"] + ".txt")).exists())

    def test_contract_hash_binds_enabled_profile_only(self):
        from fanqie_auto_publish import publication_safety
        baseline = publication_safety.creative_contract_hash(self.project)
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        style_profile.after_learn(self.project, record["id"], guide="短句。")
        bound = publication_safety.creative_contract_hash(self.project)
        self.assertNotEqual(baseline, bound)
        style_profile.options(self.project, enabled=False)
        self.assertEqual(publication_safety.creative_contract_hash(self.project), baseline)

    def test_guidance_injection_stops_when_disabled(self):
        writer._load_webnovel_services()
        from services.creative_brief import load_guidance
        record = studio.upload(self.project, "样本.txt", SAMPLE_A.encode("utf-8"))
        style_profile.after_learn(self.project, record["id"], guide="短句推进。")
        self.assertIn("作者文风参考", load_guidance(self.project))
        style_profile.options(self.project, enabled=False)
        self.assertNotIn("作者文风参考", load_guidance(self.project))


class StyleBudgetTests(unittest.TestCase):
    def test_representative_budget_follows_context_policy(self):
        self.assertEqual(studio.learning_budget({}), 12000)
        configured = {"resource_policy": {"model_window": 128000, "context_profile": "generous"}}
        self.assertEqual(studio.learning_budget(configured), 32000)
        narrow = {"resource_policy": {"model_window": 6000, "context_profile": "quick"}}
        self.assertGreaterEqual(studio.learning_budget(narrow), 2000)


if __name__ == "__main__":
    unittest.main()
