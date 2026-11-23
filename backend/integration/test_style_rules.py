"""C04 文风规则：规则字段完整、四类检测、平台只提醒、忽略词表、指标不夸大。"""
import tempfile
import unittest
from pathlib import Path

from integration import style_rules as sr

DUP = (
    "他推开门，屋里没人。\n\n"
    "总之，这一天过得很不寻常。\n\n"
    "他把外套挂好，坐下。\n\n"
    "总之，这一天过得很不寻常，也很漫长。\n"
)
DUP_DIFFERENT = (
    "他推开门，屋里没人。\n\n"
    "总之，这一天过得很不寻常。\n\n"
    "他把外套挂好，坐下。\n\n"
    "总之，钥匙最后还是没找到。\n"
)
TAIL = (
    "雨还在下。\n\n"
    "他没有回头。\n\n"
    "也就是说，他终于明白，自己再也不会回来了。\n"
)
TAUT = "他非常非常高兴，高兴高兴得说不出话。\n"
DIALOGUE = (
    "「我觉得我们应该先去找老周问问情况。」\n\n"
    "「我觉得也是，先找老周问问情况。」\n\n"
    "「我觉得雨停之前最好别动。」\n\n"
    "「我觉得还是等雨停了再说。」\n"
)
PLATFORM = "这样写保证过审，一定能上推荐。\n"


class StyleRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "book"
        (self.project / ".webnovel").mkdir(parents=True)

    def ids(self, result):
        return [row["rule_id"] for row in result["findings"]]

    # --- 规则表 ---------------------------------------------------------------
    def test_rule_id_carries_all_fields(self):
        rows = sr.public()
        self.assertTrue(rows)
        required = {"rule_id", "category", "condition", "scope", "source_date", "positive",
                    "negative", "severity", "ignore_scope", "advisory"}
        for row in rows:
            self.assertTrue(required <= set(row), row["rule_id"])
            self.assertIn(row["category"], sr.CATEGORIES)
            self.assertIn(row["severity"], sr.SEVERITIES)
            self.assertNotEqual(row["positive"], row["negative"])

    def test_platform_rule_is_advisory_only(self):
        result = sr.check(PLATFORM, project=self.project)
        self.assertIn("platform.no_basis_claim", self.ids(result))
        self.assertEqual(result["advisory_only"], ["platform.no_basis_claim"])
        row = next(item for item in result["findings"] if item["rule_id"] == "platform.no_basis_claim")
        self.assertTrue(row["advisory"])

    # --- 四类写作检测 ---------------------------------------------------------
    def test_duplicate_summary_is_flagged_after_first(self):
        result = sr.check(DUP, project=self.project)
        hits = [row for row in result["findings"] if row["rule_id"] == "style.dup_summary"]
        self.assertEqual(len(hits), 1)
        self.assertIn("很漫长", hits[0]["quote"])

    def test_two_different_summaries_are_not_called_duplicate(self):
        result = sr.check(DUP_DIFFERENT, project=self.project)
        self.assertNotIn("style.dup_summary", self.ids(result))

    def test_explainer_tail_is_flagged_with_position(self):
        result = sr.check(TAIL, project=self.project)
        hit = next(row for row in result["findings"] if row["rule_id"] == "style.explainer_tail")
        self.assertEqual(hit["paragraph"], 2)
        self.assertGreaterEqual(hit["range"][0], 0)

    def test_tautology_skips_whitelisted_stack_words(self):
        result = sr.check(TAUT, project=self.project)
        quotes = [row["quote"] for row in result["findings"] if row["rule_id"] == "style.tautology"]
        self.assertIn("非常非常", quotes)
        self.assertNotIn("慢慢", " ".join(quotes))
        clean = sr.check("他慢慢走过去，渐渐看清了。\n", project=self.project)
        self.assertEqual(clean["findings"], [])

    def test_homogeneous_dialogue_is_flagged_once(self):
        result = sr.check(DIALOGUE, project=self.project)
        hits = [row for row in result["findings"] if row["rule_id"] == "style.homogeneous_dialogue"]
        self.assertEqual(len(hits), 1)

    def test_clean_text_has_no_findings(self):
        result = sr.check("雨停在檐角。\n\n他收起伞，走进巷子。\n", project=self.project)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["paragraphs"], 2)

    # --- 忽略词表 -------------------------------------------------------------
    def test_ignored_idiom_is_not_flagged(self):
        sr.ignore_terms(self.project, ["总之"])
        result = sr.check(DUP, ignore_terms=sr.ignore_terms(self.project), project=self.project)
        self.assertNotIn("style.dup_summary", self.ids(result))
        self.assertGreaterEqual(result["ignored"], 1)

    def test_ignore_terms_are_bounded(self):
        with self.assertRaises(ValueError):
            sr.ignore_terms(self.project, [f"词{index}" for index in range(21)])
        with self.assertRaises(ValueError):
            sr.ignore_terms(self.project, ["字" * 41])

    # --- 指标 -----------------------------------------------------------------
    def test_metrics_report_counts(self):
        sr.check(DUP, project=self.project)
        sr.record_action(self.project, "style.dup_summary", "accepted")
        sr.record_action(self.project, "style.dup_summary", "ignored")
        sr.record_action(self.project, "style.tautology", "false_positive", note="角色口癖")
        report = sr.metrics(self.project)
        self.assertEqual(report["checks"], 1)
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["ignored"], 1)
        self.assertEqual(report["false_positive"], 1)
        self.assertIsNotNone(report["per_100_paragraphs"])
        self.assertIn("不宣称", report["note"])

    def test_unknown_rule_or_action_is_rejected(self):
        with self.assertRaises(ValueError):
            sr.record_action(self.project, "style.unknown", "accepted")
        with self.assertRaises(ValueError):
            sr.record_action(self.project, "style.dup_summary", "maybe")


if __name__ == "__main__":
    unittest.main()
