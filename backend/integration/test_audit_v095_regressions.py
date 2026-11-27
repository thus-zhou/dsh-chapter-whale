"""Regression tests for the v0.9.5 adversarial audit's P0/P1 findings."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import concurrent_engine as engine
from integration import maintenance
from integration import version_history


def project(folder):
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


def seed(book, chapter=1, title="开端", text="旧正文\n"):
    ce.new_chapter(book, {"chapter": chapter, "title": title, "content": text,
                          "op_id": f"new-{chapter}-{len(title)}"})


class PathAndVersionTest(unittest.TestCase):
    def test_restore_op_id_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            current = cv.current_version(book, 1) or {}
            outside = Path(folder) / "pwn.json"
            with self.assertRaises(cv.VersionError):
                version_history.restore(book, 1, current["version_id"],
                                        op_id="../../../../pwn")
            self.assertFalse(outside.exists())

    def test_cross_chapter_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, "甲", "甲章正文\n")
            seed(book, 2, "乙", "乙章正文\n")
            first = cv.current_version(book, 1) or {}
            with self.assertRaises(cv.VersionNotFound):
                version_history.read(book, 2, first["sha256"])
            with self.assertRaises(cv.VersionNotFound):
                version_history.restore(book, 2, first["sha256"])

    def test_commit_prepared_record_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            original = cv._store_object
            calls = {"n": 0}

            def fail_once(project_arg, data):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("simulated crash before object write")
                return original(project_arg, data)

            with patch.object(cv, "_store_object", side_effect=fail_once):
                with self.assertRaises(OSError):
                    cv.commit_raw_bytes(book, 1, "新正文\n".encode(), op_id="prepared-retry")
            path = cv.chapter_path(book, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), "旧正文\n")
            with self.assertRaises(cv.VersionConflict) as caught:
                cv.commit_raw_bytes(book, 1, "新正文\n".encode(), op_id="prepared-retry")
            self.assertEqual(caught.exception.args[0], "operation_incomplete")

    def test_new_chapter_expect_absent_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            with self.assertRaises(cv.VersionConflict) as caught:
                cv.commit_raw_bytes(book, 1, "覆盖\n".encode(), allow_new=True,
                                    expect_absent=True, op_id="new-race")
            self.assertEqual(caught.exception.args[0], "chapter_exists")
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), "旧正文\n")


class MaintenanceAndPauseTest(unittest.TestCase):
    def test_gc_protects_registered_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            history = book / ".webnovel" / "history"
            history.mkdir()
            artifact = history / "keep.md"
            artifact.write_text("作者历史", encoding="utf-8")
            old = time.time() - 30 * 86400
            artifact.touch()
            import os
            os.utime(artifact, (old, old))
            maintenance.register_artifact(book, artifact, ref_count=3, protected=True)
            result = maintenance.collect_garbage(book, dry_run=False)
            self.assertTrue(artifact.exists())
            self.assertEqual(result["count"], 0)

    def test_export_refuses_project_and_non_zip_destinations(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            chapter = cv.chapter_path(book, 1)
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.export_bundle(book, chapter)
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.export_bundle(book, Path(folder) / "x.txt")
            existing_zip = Path(folder) / "x.zip"
            existing_zip.write_bytes(b"already here")
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.export_bundle(book, existing_zip)
            self.assertTrue(chapter.is_file())
            self.assertNotEqual(chapter.read_bytes()[:2], b"PK")

    def test_global_pause_blocks_claim_without_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            pause_file = Path(folder) / "global_pause.json"
            previous = engine._GLOBAL_PAUSE_PATH
            engine.configure_global_pause(pause_file)
            try:
                engine.submit(book, {}, priority="P0")
                engine.set_global_pause(True, "test")
                self.assertIsNone(engine.claim(book, "w"))
                engine.set_global_pause(False)
                self.assertIsNotNone(engine.claim(book, "w"))
            finally:
                engine._GLOBAL_PAUSE_PATH = previous


if __name__ == "__main__":
    unittest.main()
