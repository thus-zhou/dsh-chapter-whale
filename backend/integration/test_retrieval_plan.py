"""C03 检索规划：过滤顺序、BM25 优先、trace、坏索引回落、索引原子切换、不外发正文。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import chapter_versions, memory_library, retrieval_plan as rp

BODY = "第{n}章\n\n雨停之后，林砚把伞收起来。\n\n钥匙在口袋里硌着他。\n"


class RetrievalPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        for chapter in (1, 3, 5, 7, 9):
            chapter_versions.write_chapter(
                self.project, chapter, BODY.format(n=chapter), op_id=f"op-{chapter}",
                title=f"第{chapter}日", allow_new=True)

    def fact(self, *, title, content, chapter=3, category="canon", extra=None):
        doc = memory_library.read(self.project)
        value = {"category": category, "title": title, "content": content}
        value.update(extra or {})
        digest = chapter_versions.file_sha256(chapter_versions.chapter_path(self.project, chapter))
        memory_library.save_item(
            self.project, value, doc["revision"],
            source={"kind": "chapter", "chapter": chapter, "sha256": digest, "quote": "雨停之后"})
        return next(row for row in memory_library.read(self.project)["items"] if row["title"] == title)

    # --- 顺序与打分 -----------------------------------------------------------
    def test_filter_order_is_works_then_version_then_chapter_then_perspective(self):
        self.fact(title="旧钥匙", content="钥匙在沈岚手里", chapter=3)
        self.fact(title="未来钥匙", content="钥匙被熔了", chapter=9)
        doc = memory_library.read(self.project)
        for item in doc["items"]:
            if item["title"] == "未来钥匙":
                item["valid_from"] = 8
        memory_library._commit(self.project, doc, doc["revision"], "edit")
        result = rp.plan(self.project, 5, "钥匙", trace=False)
        titles = [row["why"] for row in result["supplied"]]
        self.assertIn("旧钥匙", titles)
        self.assertNotIn("未来钥匙", titles)

    def test_bm25_scores_repeat_terms_higher(self):
        self.fact(title="钥匙一", content="钥匙钥匙钥匙")
        self.fact(title="钥匙二", content="钥匙")
        result = rp.plan(self.project, 5, "钥匙", trace=False)
        scores = {row["why"]: row["score"] for row in result["supplied"]}
        self.assertGreater(scores.get("钥匙一", 0), 0)
        self.assertGreaterEqual(scores.get("钥匙一", 0), scores.get("钥匙二", 0))

    def test_bm25_is_empty_without_query(self):
        self.fact(title="钥匙", content="钥匙在林砚手里")
        result = rp.plan(self.project, 5, "", trace=False)
        self.assertEqual(result["mode"], "bm25_empty")
        self.assertEqual(result["supplied"], [])
        reasons = {row["reason"] for row in result["omitted"]}
        self.assertIn("与查询无语义命中", reasons)

    def test_fixed_settings_are_supplied_without_query(self):
        doc = memory_library.read(self.project)
        memory_library.save_item(self.project, {"category": "canon", "title": "世界设定", "content": "钥匙共有三把"},
                                 doc["revision"])
        pinned = self.fact(title="钉住的线索", content="钥匙会发烫", extra={"pinned": True})
        self.assertTrue(pinned["id"])
        result = rp.plan(self.project, 5, "", trace=False)
        titles = [row["why"] for row in result["supplied"]]
        self.assertTrue(any(title.startswith("世界设定") for title in titles), titles)
        self.assertTrue(any(title.startswith("钉住的线索") for title in titles), titles)

    def test_stale_source_is_excluded_and_counted(self):
        self.fact(title="仍有效", content="钥匙在林砚手里")
        chapter_versions.write_chapter(self.project, 3, BODY.format(n=3) + "\n她换了锁。\n",
                                       op_id="op-3b", title="第3日")
        result = rp.plan(self.project, 5, "钥匙", trace=False)
        self.assertEqual(result["counts"]["stale"], 1)
        self.assertNotIn("仍有效", [row["why"] for row in result["supplied"]])
        reasons = {row["reason"] for row in result["omitted"]}
        self.assertTrue(any("来源已失效" in reason for reason in reasons))

    def test_omitted_reason_is_recorded_for_over_budget(self):
        for index in range(6):
            self.fact(title=f"设定{index}", content="钥匙" + "很长的内容" * 40)
        result = rp.plan(self.project, 5, "钥匙", budget=300, trace=False)
        reasons = {row["reason"] for row in result["omitted"]}
        self.assertIn("超出预算", reasons)
        self.assertLess(result["used"], 300 + 400)

    # --- 认知/视角 ------------------------------------------------------------
    def test_character_perspective_drops_unknown_facts(self):
        self.fact(title="角色未知", content="钥匙其实在井里")
        known = self.fact(title="角色已知", content="钥匙在口袋里")
        result = rp.plan(self.project, 5, "钥匙", perspective="character", knowledge=[known["id"]], trace=False)
        self.assertNotIn("角色未知", [row["why"] for row in result["supplied"]])
        self.assertIn("角色已知", [row["why"] for row in result["supplied"]])
        reader = rp.plan(self.project, 5, "钥匙", perspective="reader", trace=False)
        self.assertIn("角色未知", [row["why"] for row in reader["supplied"]])

    def test_manual_setting_is_visible_without_knowledge(self):
        doc = memory_library.read(self.project)
        memory_library.save_item(self.project, {"category": "canon", "title": "世界设定", "content": "钥匙共有三把"},
                                 doc["revision"])
        result = rp.plan(self.project, 5, "钥匙", knowledge=[], trace=False)
        self.assertIn("世界设定", [row["why"] for row in result["supplied"]])

    def test_query_is_sanitized_before_scoring(self):
        self.fact(title="钥匙", content="钥匙在林砚手里")
        result = rp.plan(self.project, 5, "林砚 拿着钥匙？", names=["林砚"], trace=False)
        self.assertEqual(result["query"], "【人物】 拿着钥匙？")
        self.assertEqual(result["removed_names"], ["林砚"])

    # --- trace ----------------------------------------------------------------
    def test_trace_records_omitted_reason_and_report_counts(self):
        self.fact(title="钥匙", content="钥匙在林砚手里")
        self.fact(title="雨", content="雨一直下")
        result = rp.plan(self.project, 5, "钥匙", op_id="B")
        self.assertTrue(result["trace"]["path"].endswith(".json"))
        saved = json.loads(Path(result["trace"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["chapter"], 5)
        self.assertTrue(saved["omitted"])
        report = rp.report(self.project)
        self.assertEqual(report["plans"], 1)
        self.assertEqual(report["supplied"], 1)

    def test_trace_files_are_capped(self):
        self.fact(title="钥匙", content="钥匙在林砚手里")
        for _index in range(rp.TRACE_LIMIT + 3):
            rp.plan(self.project, 5, "钥匙", op_id="B", trace=True)
        files = list((self.project / ".webnovel" / "retrieval_traces").glob("ch*.json"))
        self.assertLessEqual(len(files), rp.TRACE_LIMIT)

    # --- 索引 -----------------------------------------------------------------
    def test_index_switch_is_atomic_and_keeps_previous(self):
        first = rp.switch_index(self.project, model="local", chunk=256)
        self.assertTrue(first["kept_previous"] is False)
        second = rp.switch_index(self.project, model="bge", chunk=512)
        self.assertEqual(second["active"]["previous"], {"model": "local", "chunk": 256})
        self.assertEqual(rp.active_index(self.project)["model"], "bge")
        self.assertTrue(rp.index_ready(self.project))

    def test_broken_index_falls_back_to_text(self):
        rp.switch_index(self.project, model="local", chunk=256)
        active = self.project / ".webnovel" / "retrieval" / "active.json"
        active.write_text("{", encoding="utf-8")
        self.fact(title="钥匙", content="钥匙在林砚手里")
        result = rp.search(self.project, 5, "钥匙", trace=False)
        self.assertIsNone(result["fallback"])
        self.assertEqual(result["mode"], "bm25")

    def test_no_body_leaves_without_permission(self):
        self.fact(title="钥匙", content="钥匙在林砚手里")
        result = rp.plan(self.project, 5, "钥匙", trace=False)
        blob = json.dumps(result, ensure_ascii=False)
        self.assertTrue(result["supplied"])
        self.assertNotIn("雨停之后", blob, "正文原句不得随规划结果外带")
        self.assertNotIn("钥匙在林砚手里", blob, "记忆正文只在本地装填，不随规划外带")

    def test_invalid_chapter_and_budget_are_rejected(self):
        with self.assertRaises(ValueError):
            rp.plan(self.project, 0, "钥匙", trace=False)
        with self.assertRaises(ValueError):
            rp.plan(self.project, 5, "钥匙", budget=10, trace=False)


if __name__ == "__main__":
    unittest.main()
