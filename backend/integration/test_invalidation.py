"""C01.4 统一失效入口：五个入口共用一条日志，旧证据进待复核，索引重建但不删正文。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import chapter_versions, invalidation, memory_library, revision_plan, version_history

FIRST = "第一版：雨停。\n\n她把伞收起来。\n"
SECOND = "第二版：雨停了。\n\n她把伞收起来，抖了两下。\n"
QUOTE = "她把伞收起来"
SHA = "a" * 64


class InvalidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        chapter_versions.write_chapter(self.project, 1, FIRST, op_id="op-1", title="雨停", allow_new=True)
        chapter_versions.write_chapter(self.project, 1, SECOND, op_id="op-2", title="雨停")
        chapter_versions.write_chapter(self.project, 3, FIRST, op_id="op-3", title="第三日", allow_new=True)
        # v0.8：提交层现在会为每次写章记一条失效日志；这些用例只验证各自的
        # 失效入口，先清空建场日志，避免把初始化当作用例产物。
        (self.project / ".webnovel" / "invalidation_log.json").unlink(missing_ok=True)

    def fact(self, chapter=3, title="钥匙在谁手里"):
        doc = memory_library.read(self.project)
        digest = chapter_versions.file_sha256(chapter_versions.chapter_path(self.project, chapter))
        memory_library.save_item(
            self.project, {"category": "canon", "title": title, "content": "钥匙在林砚手里"},
            doc["revision"], source={"kind": "chapter", "chapter": chapter, "sha256": digest, "quote": QUOTE})
        saved = memory_library.read(self.project)
        return next(row for row in saved["items"] if row["title"] == title)

    def test_marks_only_facts_from_that_chapter(self):
        kept = self.fact(chapter=1, title="旧设定")
        target = self.fact(chapter=3)
        result = invalidation.invalidate(self.project, chapters=[3], reason="chapter_edited", source="author-edit")
        self.assertEqual(result["status"], "invalidated")
        ids = {row["id"] for row in result["marked"]}
        self.assertIn(target["id"], ids)
        self.assertNotIn(kept["id"], ids)
        self.assertTrue(result["rebuilt"])

    def test_invalidated_facts_leave_the_prompt_context(self):
        self.fact(chapter=3)
        before = memory_library.context(self.project, chapter=5, query="钥匙")
        self.assertIn("钥匙在林砚手里", before["text"])
        result = invalidation.invalidate(self.project, chapters=[3], reason="chapter_edited")
        self.assertEqual(result["reviewing"], 1)
        saved = memory_library.read(self.project)
        target = next(row for row in saved["items"] if row["title"] == "钥匙在谁手里")
        self.assertEqual(target["status"], "needs_review")
        self.assertEqual(target["review"]["reason"], "chapter_edited")
        after = memory_library.context(self.project, chapter=5, query="钥匙")
        self.assertNotIn("钥匙在林砚手里", after["text"])

    def test_same_op_id_is_recorded_once(self):
        self.fact(chapter=3)
        first = invalidation.invalidate(self.project, chapters=[3], reason="revision_accepted", op_id="accept-1")
        again = invalidation.invalidate(self.project, chapters=[3], reason="revision_accepted", op_id="accept-1")
        self.assertEqual(first["status"], "invalidated")
        self.assertEqual(again["status"], "reused")
        self.assertEqual(len(invalidation.read_log(self.project)["entries"]), 1)

    def test_unknown_reason_and_bad_chapter_are_refused(self):
        with self.assertRaises(ValueError):
            invalidation.invalidate(self.project, chapters=[3], reason="made_up")
        with self.assertRaises(ValueError):
            invalidation.invalidate(self.project, chapters=[0], reason="manual")

    def test_restore_triggers_same_invalidation(self):
        self.fact(chapter=1)
        history = version_history.history(self.project, 1)
        old = [row for row in history["versions"] if not row["current"]][0]["version_id"]
        result = version_history.restore(self.project, 1, old)
        self.assertEqual(result["status"], "restored")
        log = invalidation.read_log(self.project)
        self.assertEqual(log["entries"][-1]["reason"], "version_restored")
        self.assertEqual(set(log["entries"][-1]["chapters"]), {1})

    def test_accept_preview_triggers_invalidation(self):
        current = chapter_versions.chapter_path(self.project, 1).read_text(encoding="utf-8")
        preview = revision_plan.save_preview(self.project, 1, current, current.replace("雨停了", "雨停了又下"),
                                            base_sha256=chapter_versions.file_sha256(
                                                chapter_versions.chapter_path(self.project, 1)))
        result = revision_plan.accept(self.project, 1, preview["preview_id"])
        self.assertEqual(result["status"], "accepted")
        log = invalidation.read_log(self.project)
        self.assertEqual(log["entries"][-1]["reason"], "revision_accepted")
        self.assertEqual(set(log["entries"][-1]["chapters"]), {1})
        self.assertIn("invalidated", result)

    def test_log_survives_and_stays_bounded(self):
        for index in range(3):
            invalidation.invalidate(self.project, chapters=[1], reason="manual", op_id=f"op-{index}")
        doc = invalidation.pending(self.project, limit=2)
        self.assertEqual(doc["total"], 3)
        self.assertEqual(len(doc["entries"]), 2)
        json.dumps(invalidation.summary(self.project)["by_reason"], ensure_ascii=False)

    def test_no_facts_still_rebuilds_index(self):
        result = invalidation.invalidate(self.project, chapters=[3], reason="chapter_generated")
        self.assertEqual(result["marked"], [])
        self.assertTrue(result["rebuilt"])
        self.assertEqual(invalidation.pending(self.project)["entries"][0]["reason"], "chapter_generated")


if __name__ == "__main__":
    unittest.main()
