"""M03 checks: 六维评分、唯一门禁、报告绑定与过期。固定响应，不调用模型。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fanqie_auto_publish import publication_safety
from integration import quality_gate, quality_score


def payload(scores=None, issues=None, not_applicable=None, verdict=None, summary="理由"):
    return {"scores": scores or {"setting": 90, "plot": 90, "character": 90, "prose": 90, "dialogue": 90, "style": 90},
            "issues": issues or [], "not_applicable": not_applicable or [], "verdict": verdict or "pass", "summary": summary}


def review(**extra):
    base = {"success": True, "review_decision": "pass", "needs_revision": False, "raw_review": "结论：无需修改"}
    base.update(extra)
    return base


class ScoreTest(unittest.TestCase):
    def test_defaults_are_the_documented_heuristic(self):
        values = quality_score.settings()
        self.assertEqual(values["threshold_total"], 85)
        self.assertEqual(values["threshold_item"], 70)
        self.assertEqual(values["weights"], {"setting": 15, "plot": 20, "character": 15, "prose": 15, "dialogue": 15, "style": 20})
        self.assertEqual(values["source"], "ai_internal_heuristic")

    def test_custom_weights_are_normalized(self):
        values = quality_score.settings({"review_quality": {"weights": {"plot": 2, "style": 1}, "threshold_total": 80}})
        self.assertAlmostEqual(sum(values["weights"].values()), 100)
        self.assertAlmostEqual(values["weights"]["plot"], 200 / 3)
        self.assertEqual(values["threshold_total"], 80)

    def test_invalid_settings_are_rejected(self):
        for bad in ({"threshold_total": "高分"}, {"weights": {"plot": -1}}, {"weights": {"plot": 0, "style": 0}},
                    {"threshold_item": 120}):
            with self.assertRaises(ValueError):
                quality_score.settings({"review_quality": bad})

    def test_weighted_total_uses_only_scored_dimensions(self):
        computed = quality_score.compute(payload({"setting": 100, "plot": 50}))
        self.assertAlmostEqual(computed["total"], round((100 * 15 + 50 * 20) / 35, 2))
        self.assertIn("character", computed["missing"])
        self.assertFalse(computed["complete"])

    def test_not_applicable_dimensions_are_excluded_not_zeroed(self):
        scores = {key: 90 for key, _ in quality_score.DIMENSIONS if key != "dialogue"}
        computed = quality_score.compute(payload(scores, not_applicable=["dialogue"]))
        self.assertIn("dialogue", computed["not_applicable"])
        self.assertNotIn("dialogue", computed["scores"])
        self.assertTrue(computed["complete"])

    def test_json_is_extracted_from_prose_and_fences(self):
        text = "先说一下总体印象。\n```json\n" + json.dumps(payload({"setting": 88, "plot": 88, "character": 88,
                                                                   "prose": 88, "dialogue": 88, "style": 88}),
                                                         ensure_ascii=False) + "\n```\n以上。"
        computed = quality_score.compute(text)
        self.assertEqual(computed["format"], "json")
        self.assertEqual(computed["total"], 88.0)

    def test_plain_text_review_is_kept_as_unscored(self):
        computed = quality_score.compute("结论：无需修改\n原因：节奏稳。\n意见：无")
        self.assertEqual(computed["format"], "text")
        self.assertIsNone(computed["total"])
        self.assertEqual(computed["missing"], [key for key, _ in quality_score.DIMENSIONS])

    def test_out_of_range_scores_are_reported_not_clamped(self):
        computed = quality_score.compute(payload({"setting": 140, "plot": 90, "character": 90,
                                                  "prose": 90, "dialogue": 90, "style": 90}))
        self.assertNotIn("setting", computed["scores"])
        self.assertEqual(computed["error"], "score_invalid:setting")

    def test_explicit_verdict_beats_advisory_wording(self):
        text = json.dumps({"conclusion": "结论：无需修改", "verdict": "pass",
                           "issues": [{"dimension": "文笔", "severity": "advisory", "issue": "可更紧凑",
                                       "advice": "建议补强环境描写"}]}, ensure_ascii=False)
        self.assertEqual(quality_score.extract(text)["verdict"], "pass")
        self.assertEqual(quality_score.extract(json.dumps({"verdict": "needs_revision"}))["verdict"], "needs_revision")
        self.assertEqual(quality_score.extract(json.dumps({"conclusion": "结论：需修改"}, ensure_ascii=False))["verdict"],
                         "needs_revision")
        self.assertIsNone(quality_score.extract(json.dumps({"verdict": "maybe"}))["verdict"])


class GateTest(unittest.TestCase):
    def test_normal_pass(self):
        result = quality_gate.judge(review(quality=payload()))
        self.assertTrue(result["quality_pass"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["computed"]["total"], 90.0)

    def test_threshold_boundary(self):
        exact = payload({key: 85 for key, _ in quality_score.DIMENSIONS})
        self.assertTrue(quality_gate.judge(review(quality=exact))["quality_pass"])
        below = payload({key: 84 for key, _ in quality_score.DIMENSIONS})
        result = quality_gate.judge(review(quality=below))
        self.assertFalse(result["quality_pass"])
        self.assertIn("total_below_threshold", result["reasons"])

    def test_single_dimension_below_item_threshold_blocks(self):
        scores = {key: 95 for key, _ in quality_score.DIMENSIONS}
        scores["dialogue"] = 60
        result = quality_gate.judge(review(quality=payload(scores)))
        self.assertFalse(result["quality_pass"])
        self.assertIn("dimension_below_threshold", result["reasons"])
        self.assertEqual(result["restricted"], ["对话"])

    def test_critical_with_evidence_blocks_even_with_high_scores(self):
        issues = [{"dimension": "setting", "severity": "critical", "issue": "死者复活", "evidence": "第3章原文"}]
        result = quality_gate.judge(review(quality=payload(issues=issues)))
        self.assertFalse(result["quality_pass"])
        self.assertEqual(result["reasons"], ["blocking_issue"])
        self.assertEqual(result["restricted"], ["设定自洽"])

    def test_unverified_suspicion_does_not_block_but_is_visible(self):
        issues = [{"dimension": "plot", "severity": "high", "issue": "疑似时间线冲突"}]
        result = quality_gate.judge(review(quality=payload(issues=issues)))
        self.assertTrue(result["quality_pass"])
        self.assertEqual(len(result["unverified"]), 1)

    def test_missing_dimension_is_insufficient_not_failed(self):
        result = quality_gate.judge(review(quality=payload({"setting": 90, "plot": 90})))
        self.assertIsNone(result["quality_pass"])
        self.assertIn("dimensions_missing", result["reasons"])

    def test_legacy_text_review_has_no_fabricated_score(self):
        result = quality_gate.judge(review())
        self.assertIsNone(result["quality_pass"])
        self.assertTrue(result["legacy_unscored"])
        self.assertEqual(result["reasons"], ["scores_missing"])

    def test_model_verdict_conflict_is_conservative(self):
        result = quality_gate.judge({"success": True, "review_decision": "needs_revision", "needs_revision": True,
                                     "quality": payload(verdict="pass")})
        self.assertFalse(result["quality_pass"])
        self.assertIn("model_verdict_conflict", result["reasons"])

    def test_publication_gate_requires_quality_but_keeps_legacy_compatible(self):
        self.assertTrue(publication_safety.review_eligible(review(), "digest"))
        failing = review(quality=payload({key: 60 for key, _ in quality_score.DIMENSIONS}))
        self.assertFalse(publication_safety.review_eligible(failing, "digest"))
        self.assertFalse(publication_safety.review_eligible({**review(), "review_decision": "unknown"}, "digest"))

    def test_review_passed_wrapper(self):
        self.assertTrue(quality_gate.review_passed(review()))
        self.assertFalse(quality_gate.review_passed(review(quality=payload({key: 60 for key, _ in quality_score.DIMENSIONS}))))
        self.assertFalse(quality_gate.review_passed({"success": False}))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cw-quality-')
        self.project = Path(self.tmp.name)
        (self.project / '.webnovel').mkdir()
        self.config_path = self.project / 'ai_config.json'
        self._old = os.environ.get('NOVEL_HELPER_AI_CONFIG')
        os.environ['NOVEL_HELPER_AI_CONFIG'] = str(self.config_path)

    def tearDown(self):
        if self._old is None:
            os.environ.pop('NOVEL_HELPER_AI_CONFIG', None)
        else:
            os.environ['NOVEL_HELPER_AI_CONFIG'] = self._old
        self.tmp.cleanup()

    def test_stored_review_carries_the_weighted_total(self):
        """真实审查落盘的是 compute 的结果：报告要直接有总分，而不是只有分项。"""
        computed = quality_score.compute(payload())
        self.assertIsNotNone(computed["total"])
        self.assertAlmostEqual(computed["total"], 90.0)
        record = quality_gate.save_report(self.project, 1, review(quality=computed), body_sha256="aaa")
        path = quality_gate.reports_dir(self.project) / f"{1:04d}-{record['report_id']}.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["review"]["quality"]["total"], computed["total"])

    def test_report_binds_body_and_expires_on_change(self):
        record = quality_gate.save_report(self.project, 1, review(quality=payload()), body_sha256='aaa',
                                          contract_hash='c1')
        self.assertEqual(record['chapter_id'], 1)
        self.assertTrue(quality_gate.status(self.project, 1, body_sha256='aaa', contract_hash='c1')['valid'])
        changed = quality_gate.status(self.project, 1, body_sha256='bbb', contract_hash='c1')
        self.assertEqual(changed['stale_reason'], 'body_changed')
        contract = quality_gate.status(self.project, 1, body_sha256='aaa', contract_hash='c2')
        self.assertEqual(contract['stale_reason'], 'contract_changed')

    def test_config_change_only_requires_recompute(self):
        quality_gate.save_report(self.project, 1, review(quality=payload()), body_sha256='aaa')
        self.config_path.write_text(json.dumps({'review_quality': {'threshold_total': 80}}), encoding='utf-8')
        status = quality_gate.status(self.project, 1, body_sha256='aaa')
        self.assertTrue(status['valid'])
        self.assertEqual(status['stale_reason'], 'config_changed')
        self.assertTrue(status['recompute_only'])

    def test_public_report_exposes_reasons_and_restricted_scope(self):
        issues = [{"dimension": "style", "severity": "high", "issue": "文风跳脱", "evidence": "第2章"}]
        quality_gate.save_report(self.project, 2, review(quality=payload(issues=issues)), body_sha256='x')
        view = quality_gate.public_report(self.project, 2)
        self.assertFalse(view['report']['quality_pass'])
        self.assertEqual(view['report']['restricted'], ['文风'])
        self.assertEqual(view['report']['reasons'], ['blocking_issue'])
        self.assertEqual(quality_gate.public_report(self.project, 9)['status']['stale_reason'], 'no_report')

    def test_multiple_reports_keep_history_and_latest_wins(self):
        # Windows clocks can return the same timestamp for adjacent writes.
        with mock.patch.object(quality_gate, '_now', return_value='2026-11-15T00:00:00+00:00'):
            quality_gate.save_report(self.project, 1, review(quality=payload(verdict='pass')), body_sha256='a')
            second = quality_gate.save_report(self.project, 1, review(raw_review='结论：需修改',
                                                                 review_decision='needs_revision',
                                                                 needs_revision=True,
                                                                 quality=payload({k: 60 for k, _ in quality_score.DIMENSIONS})),
                                              body_sha256='b')
        self.assertEqual(len(quality_gate.history(self.project, 1)), 2)
        self.assertEqual(quality_gate.latest(self.project, 1)['report_id'], second['report_id'])
        third = quality_gate.save_report(self.project, 1, second['review'], body_sha256='c')
        self.assertNotEqual(third['report_id'], second['report_id'])
        self.assertEqual(len(quality_gate.history(self.project, 1)), 3)
        self.assertEqual(quality_gate.latest(self.project, 1)['body_sha256'], 'c')


if __name__ == '__main__':
    unittest.main()
