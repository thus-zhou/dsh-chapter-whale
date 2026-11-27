"""六维融合、自动审稿上限与双轨仪表盘（v0.9.5）。"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from integration import annotations
from integration import chapter_editor as ce
from integration import quality
from integration import workbench_db as wb
from integration import world_state as ws


def project(folder):
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


def seed(path, chapter, text):
    ce.new_chapter(path, {"chapter": chapter, "title": f"第{chapter}章", "content": text,
                          "op_id": f"q-{chapter}"})


class QualityTest(unittest.TestCase):
    def test_fuse_requires_all_dimensions_and_range(self):
        good = {dim: 80 for dim in quality.DIMENSIONS}
        fused = quality.fuse([{"scores": good}, {"scores": {dim: 70 for dim in quality.DIMENSIONS}}])
        self.assertEqual(fused["total"], 75.0)
        self.assertEqual(fused["verdict"], "pass")
        with self.assertRaises(quality.QualityError) as caught:
            quality.fuse([{"scores": {"plot": 80}}])
        self.assertEqual(caught.exception.code, "missing_dimension")
        broken = dict(good)
        broken["plot"] = 101
        with self.assertRaises(quality.QualityError):
            quality.fuse([{"scores": broken}])

    def test_auto_review_limit_is_two(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, "第一段。\n“你来了。”\n" * 20)
            first = quality.review(book, 1)
            self.assertEqual(first["track"], "A")
            quality.review(book, 1)
            # A 轨本地体检零模型调用，可无限运行，不占 B 轨额度。
            self.assertEqual(quality.review(book, 1)["track"], "A")
            # B 轨（六维融合）最多两次。
            judges = [{"scores": quality.local_scores("第一段。\n" * 20)}]
            for _ in range(2):
                self.assertEqual(quality.review(book, 1, judgments=judges)["track"], "B")
            with self.assertRaises(quality.QualityError) as caught:
                quality.review(book, 1, judgments=judges)
            self.assertEqual(caught.exception.code, "auto_review_limit")
            manual = quality.review(book, 1, judgments=judges, reviewer="author", force=True)
            self.assertEqual(manual["track"], "B")

    def test_legacy_chapter_uses_content_hash_and_goes_stale(self):
        """审计 C-12：无版本章节按正文哈希计数与判新鲜度。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            body = book / "正文" / "第1章-旧稿.md"
            body.write_text("第一段。\n“你来了。”\n" * 20, encoding="utf-8", newline="\n")
            first = quality.review(book, 1)
            self.assertEqual(first["version_id"], "")
            self.assertTrue(first["review_key"].startswith("sha256:"))
            judges = [{"scores": quality.local_scores(body.read_text(encoding="utf-8"))}]
            for _ in range(2):
                quality.review(book, 1, judgments=judges)
            with self.assertRaises(quality.QualityError) as caught:
                quality.review(book, 1, judgments=judges)
            self.assertEqual(caught.exception.code, "auto_review_limit")
            board = quality.dashboard(book)
            self.assertFalse(board["chapters"][0]["stale_review"])
            body.write_text("完全重写后的正文。\n" + "“新的对白。”\n" * 20,
                            encoding="utf-8", newline="\n")
            board = quality.dashboard(book)
            self.assertTrue(board["chapters"][0]["stale_review"])
            self.assertEqual(board["chapters"][0]["verdict"], "stale")
            # 内容变化后按新哈希重新获得两次自动审稿额度。
            rewritten = quality.review(book, 1, judgments=[
                {"scores": quality.local_scores(body.read_text(encoding="utf-8"))}])
            self.assertNotEqual(rewritten["review_key"], first["review_key"])
            self.assertFalse(quality.dashboard(book)["chapters"][0]["stale_review"])

    def test_dashboard_pagination_and_missing_chapter_degrade(self):
        """审计 C-26/C-27：分页信息准确，单章缺失不拖垮整盘。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            for chapter in (1, 2, 3):
                seed(book, chapter, f"第{chapter}章正文。\n")
            board = quality.dashboard(book, limit=2)
            self.assertEqual(board["total_chapters"], 3)
            self.assertEqual(board["total"], 3)
            self.assertEqual(board["returned"], 2)
            self.assertTrue(board["truncated"])
            second = quality.dashboard(book, limit=2, offset=2)
            self.assertEqual([row["chapter_id"] for row in second["chapters"]], [3])
            self.assertFalse(second["truncated"])
            original = quality._chapter_text
            def flaky(project_arg, chapter_arg):
                if int(chapter_arg) == 2:
                    raise quality.QualityError("chapter_missing", status=404)
                return original(project_arg, chapter_arg)
            with mock.patch.object(quality, "_chapter_text", side_effect=flaky):
                board = quality.dashboard(book)
            verdicts = {row["chapter_id"]: row["verdict"] for row in board["chapters"]}
            self.assertEqual(verdicts[2], "missing")
            self.assertEqual(board["total"], 3)

    def test_dashboard_has_six_dimensions_and_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, "短。\n")
            quality.review(book, 1)
            board = quality.dashboard(book)
            self.assertEqual(set(board["averages"]), set(quality.DIMENSIONS))
            self.assertEqual(board["total"], 1)
            self.assertTrue(board["chapters"][0]["verdict"] in {"pass", "revise", "block"})
            self.assertIn("labels", board)

    def test_imported_book_quality_exemption_and_annotation_do_not_deadlock(self):
        """审计 C-02：导入旧稿不建 chapter_meta，质量/豁免/批注不得自锁死。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            text = "第1章 开端\n第一段正文。\n“你来了。”\n\n第2章 继续\n第二段正文。\n"
            imported = ce.import_chapters(book, text=text, preview=False, op_id="q-import")
            self.assertEqual(imported["count"], 2)
            self.assertEqual(wb.list_chapter_meta(book), [])
            started = time.monotonic()
            self.assertEqual(quality.review(book, 1)["status"], "reviewed")
            self.assertEqual(ws.add_exemption(book, chapter=2, rule_id="r1",
                                              rule_text="不得血腥")["status"], "exempted")
            annotation = annotations.create_annotation(
                book, 1, {"scope": "chapter", "instruction": "加强环境描写"})
            self.assertEqual(annotation["status"], "created")
            self.assertLess(time.monotonic() - started, 5.0)


if __name__ == "__main__":
    unittest.main()
