"""六维融合、自动审稿上限与双轨仪表盘（v0.9.5）。"""
import tempfile
import unittest
from pathlib import Path

from integration import chapter_editor as ce
from integration import quality


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
            for _ in range(2):
                quality.review(book, 1, judgments=[{"scores": quality.local_scores("第一段。\n" * 20)}])
            with self.assertRaises(quality.QualityError) as caught:
                quality.review(book, 1, judgments=[{"scores": quality.local_scores("第一段。\n" * 20)}])
            self.assertEqual(caught.exception.code, "auto_review_limit")
            manual = quality.review(book, 1, reviewer="author", force=True)
            self.assertEqual(manual["track"], "B")

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


if __name__ == "__main__":
    unittest.main()
