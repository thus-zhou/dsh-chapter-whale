"""Studio polish write-back must not overwrite a save made in its window."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import revision_workflow, studio
from integration import writer_runner as writer


class DummyExecutor:
    def __init__(self, *args, **kwargs):
        self.polish_token_budget = 0


async def fake_revise(project, chapter, content, sha, contract, executor, config,
                      min_words, meta=None):
    return "润色后的正文\n", {"success": True, "review_decision": "pass", "needs_revision": False}


async def fake_sync(*args, **kwargs):
    return {}


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def seed(book):
    path = book / "正文" / "第1章-开端.md"
    path.write_text("原始正文\n", encoding="utf-8", newline="\n")
    sha = cv.raw_sha256(path.read_bytes())
    ce.save_version(book, 1, {"title": "开端", "content": "原始正文\n", "op_id": "seed",
                              "expected_content_sha256": sha})
    return path


class PolishRaceTest(unittest.TestCase):
    def test_polish_refuses_to_overwrite_a_concurrent_save(self):
        with tempfile.TemporaryDirectory() as folder:
            book = make_project(folder)
            path = seed(book)
            saved = {}

            real_write = studio.bridge._write_text_atomic

            def hook(target, text):
                if "originals" in str(target) and not saved:
                    saved.update(ce.save_version(book, 1, {
                        "title": "开端",
                        "content": "作者在润色回写窗口保存的新正文\n",
                        "op_id": "race-save",
                        "expected_content_sha256": cv.file_sha256(cv.chapter_path(book, 1)),
                        "expected_version_id": cv.current_version(book, 1)["version_id"]}))
                return real_write(target, text)

            with patch.object(revision_workflow, "revise", fake_revise), \
                    patch.object(writer, "_load_webnovel_services",
                                 return_value=(DummyExecutor, lambda: None)), \
                    patch.object(writer, "_sync_committed_artifacts", fake_sync), \
                    patch.object(studio.bridge, "load_manifest", return_value={"books": {}}), \
                    patch.object(studio.bridge, "_write_text_atomic", side_effect=hook):
                with self.assertRaises(cv.VersionConflict) as caught:
                    studio.polish_existing(book, 1)
            self.assertEqual(caught.exception.args[0], "concurrent_modification")
            self.assertEqual(saved.get("status"), "saved")
            self.assertEqual(path.read_text(encoding="utf-8"),
                             "作者在润色回写窗口保存的新正文\n")
            sources = [row.get("source") for row in cv.list_versions(book, 1)]
            self.assertNotIn("studio_polish", sources)


if __name__ == "__main__":
    unittest.main()
