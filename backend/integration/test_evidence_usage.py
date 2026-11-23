"""C02 证据使用台账：提供记账、定位、反向索引、20 章标注集指标。"""
import tempfile
import unittest
from pathlib import Path

from integration import chapter_versions, evidence_usage as eu, memory_library

BODY = (
    "雨停之后，林砚把伞收起来。\n\n"
    "他没有马上走，站在檐下看了很久。\n\n"
    "钥匙在口袋里硌着他，那是第3章从沈岚手里接过来的东西。\n"
)
QUOTE = "钥匙在口袋里硌着他"
SHA = "b" * 64


class EvidenceUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        for chapter in range(1, 21):
            chapter_versions.write_chapter(
                self.project, chapter, f"第{chapter}章\n\n" + BODY, op_id=f"op-{chapter}",
                title=f"第{chapter}日", allow_new=True)
        self.body = BODY

    def fact(self, chapter=3, title="钥匙在谁手里"):
        doc = memory_library.read(self.project)
        memory_library.save_item(
            self.project, {"category": "canon", "title": title, "content": "钥匙在林砚手里"},
            doc["revision"], source={"kind": "chapter", "chapter": chapter, "sha256": SHA, "quote": QUOTE})
        saved = memory_library.read(self.project)
        return next(row for row in saved["items"] if row["title"] == title)

    def sha(self, chapter=3):
        return chapter_versions.file_sha256(chapter_versions.chapter_path(self.project, chapter))

    # --- 提供记账 -------------------------------------------------------------
    def test_supply_log_keeps_ids_and_omitted_reasons(self):
        result = eu.log_supply(self.project, chapter=7, stage="B", version_sha=SHA, evidence_ids=["f1", "f2"],
                               omitted=[{"id": "f3", "reason": "超出预算"}])
        self.assertEqual(result["status"], "logged")
        row = eu.read_log(self.project, 7)[0]
        self.assertEqual(row["supplied"], ["f1", "f2"])
        self.assertEqual(row["omitted"][0]["reason"], "超出预算")

    def test_same_supply_is_logged_once(self):
        first = eu.log_supply(self.project, chapter=7, stage="B", version_sha=SHA, evidence_ids=["f1"])
        second = eu.log_supply(self.project, chapter=7, stage="B", version_sha=SHA, evidence_ids=["f1", "f2"])
        self.assertEqual(first["status"], "logged")
        self.assertEqual(second["status"], "reused")
        self.assertEqual(len(eu.read_log(self.project, 7)), 1)

    def test_supply_rejects_bad_stage_and_chapter(self):
        with self.assertRaises(ValueError):
            eu.log_supply(self.project, chapter=0, stage="B", version_sha=SHA, evidence_ids=[])
        with self.assertRaises(ValueError):
            eu.log_supply(self.project, chapter=7, stage="", version_sha=SHA, evidence_ids=[])

    # --- 采用状态 -------------------------------------------------------------
    def test_model_claim_is_not_confirmation(self):
        with self.assertRaises(ValueError) as caught:
            eu.record_use(self.project, chapter=7, fact_id="f1", state="confirmed", actor="model")
        self.assertIn("确认必须由作者操作", str(caught.exception))
        saved = eu.record_use(self.project, chapter=7, fact_id="f1", state="candidate", actor="model",
                              quote="钥匙在口袋里")
        self.assertEqual(saved["status"], "recorded")

    def test_author_confirmation_is_recorded(self):
        result = eu.record_use(self.project, chapter=7, fact_id="f1", state="confirmed", actor="author")
        self.assertEqual(result["entry"]["state"], "confirmed")

    def test_unknown_state_is_rejected(self):
        with self.assertRaises(ValueError):
            eu.record_use(self.project, chapter=7, fact_id="f1", state="adopted")

    # --- 定位 -----------------------------------------------------------------
    def test_literal_quote_is_located_with_paragraph(self):
        found = eu.locate_use(self.project, chapter=3, version_sha=self.sha(3), quote=QUOTE)
        self.assertEqual(found["status"], "located")
        paragraphs = [row for row in self.body.split("\n\n")]
        self.assertIn(QUOTE, paragraphs[found["paragraph"] - 1])

    def test_paraphrase_is_only_a_candidate(self):
        found = eu.locate_use(self.project, chapter=3, version_sha=self.sha(3),
                              quote="钥匙一直硌着他的口袋，是从沈岚那里拿的")
        self.assertEqual(found["status"], "candidate")
        self.assertGreaterEqual(found["similarity"], 0.25)
        self.assertLess(found["similarity"], 0.6)

    def test_missing_quote_is_reported_not_guessed(self):
        found = eu.locate_use(self.project, chapter=3, version_sha=self.sha(3), quote="他们在码头打了一架")
        self.assertEqual(found["status"], "missing")

    def test_stale_version_is_not_called_located(self):
        found = eu.locate_use(self.project, chapter=3, version_sha=SHA, quote=QUOTE)
        self.assertEqual(found["status"], "stale_version")
        self.assertIn("重新定位", found["note"])

    def test_cross_paragraph_quote_is_ambiguous(self):
        found = eu.locate_use(self.project, chapter=3, version_sha=self.sha(3),
                              quote="林砚把伞收起来。\n\n他没有马上走")
        self.assertEqual(found["status"], "ambiguous")

    def test_locate_requires_quote(self):
        with self.assertRaises(ValueError):
            eu.locate_use(self.project, chapter=3, version_sha=self.sha(3), quote="  ")

    # --- 反向索引 -------------------------------------------------------------
    def test_reverse_index_rebuilds_from_log(self):
        fact = self.fact()
        eu.record_use(self.project, chapter=7, fact_id=fact["id"], state="located", quote=QUOTE)
        eu.record_use(self.project, chapter=9, fact_id=fact["id"], state="confirmed", actor="author")
        index = eu.reverse_index(self.project)
        self.assertEqual(index["3"][fact["id"]]["uses"][0]["chapter"], 7)
        self.assertEqual([row["chapter"] for row in index["3"][fact["id"]]["uses"]], [7, 9])

    def test_reverse_index_is_stable_after_repeat_writes(self):
        fact = self.fact()
        eu.record_use(self.project, chapter=7, fact_id=fact["id"], state="candidate")
        eu.record_use(self.project, chapter=7, fact_id=fact["id"], state="located", quote=QUOTE)
        index = eu.reverse_index(self.project)
        uses = index["3"][fact["id"]]["uses"]
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0]["state"], "located")

    def test_reverse_index_ignores_facts_without_source(self):
        doc = memory_library.read(self.project)
        memory_library.save_item(self.project, {"category": "preference", "title": "偏好", "content": "爱喝茶"},
                                 doc["revision"])
        manual = next(row for row in memory_library.read(self.project)["items"] if row["title"] == "偏好")
        eu.record_use(self.project, chapter=7, fact_id=manual["id"], state="located")
        self.assertEqual(eu.reverse_index(self.project), {})

    # --- 覆盖范围 -------------------------------------------------------------
    def test_backfill_marks_partial_coverage(self):
        eu.log_supply(self.project, chapter=1, stage="B", version_sha=SHA, evidence_ids=["f1"])
        eu.log_supply(self.project, chapter=5, stage="B", version_sha=SHA, evidence_ids=["f1"], op_id="backfill")
        rows = eu.read_log(self.project)
        self.assertEqual(eu.coverage(self.project)["exact"], [1, 5])
        self.assertTrue(any(row["chapter"] == 5 for row in rows))

    def test_supplies_summary_is_limited(self):
        eu.log_supply(self.project, chapter=1, stage="B", version_sha=SHA, evidence_ids=["f1"])
        summary = eu.supplies(self.project)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["entries"][0]["chapter"], 1)

    # --- 20 章标注集 ----------------------------------------------------------
    def fixture(self):
        dependencies = [
            {"source_chapter": 3, "use_chapters": [7]},
            {"source_chapter": 3, "use_chapters": [9]},
            {"source_chapter": 5, "use_chapters": [8]},
            {"source_chapter": 5, "use_chapters": [11]},
            {"source_chapter": 6, "use_chapters": [12]},
            {"source_chapter": 6, "use_chapters": [14]},
            {"source_chapter": 9, "use_chapters": [15]},
            {"source_chapter": 9, "use_chapters": [16]},
            {"source_chapter": 12, "use_chapters": [18]},
            {"source_chapter": 12, "use_chapters": [19]},
        ]
        distractors = [{"source_chapter": 4, "chapter": 10}, {"source_chapter": 8, "chapter": 13}]
        return {"dependencies": dependencies, "distractors": distractors}

    def test_metrics_with_fixture_counts_precision_and_recall(self):
        facts = {}
        for chapter in (3, 5, 6, 9, 12):
            facts[chapter] = self.fact(chapter=chapter, title=f"设定{chapter}")
        for chapter in (7, 8, 9, 11, 12, 14, 15, 16, 18, 19):
            source = next(row["source_chapter"] for row in self.fixture()["dependencies"]
                          for use in row["use_chapters"] if use == chapter)
            eu.record_use(self.project, chapter=chapter, fact_id=facts[source]["id"], state="located", quote=QUOTE)
        report = eu.metrics(self.project, self.fixture())
        self.assertEqual(report["samples"], 10)
        self.assertEqual(report["recall"], 1.0)
        self.assertEqual(report["missed"], [])
        self.assertEqual(report["distractor_count"], 2)

    def test_metrics_without_fixture_reports_counts_only(self):
        report = eu.metrics(self.project)
        self.assertIsNone(report["precision"])
        self.assertIsNone(report["recall"])
        self.assertEqual(report["samples"], 0)

    def test_context_includes_entity_block_and_supply_trace(self):
        from integration import entity_state
        entity_state.record_item(self.project, entity="黄铜钥匙", holder="林砚", chapter=1, quote=QUOTE, sha256=SHA)
        self.fact()
        context = memory_library.context(self.project, chapter=5, query="钥匙",
                                         trace={"stage": "B", "version_sha": SHA})
        self.assertIn("物品与事件", context["text"])
        self.assertIn("林砚", context["entity_text"])
        self.assertEqual(context["trace"]["status"], "logged")
        self.assertEqual([row["chapter"] for row in eu.read_log(self.project)], [5])


if __name__ == "__main__":
    unittest.main()
