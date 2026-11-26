"""引用计数 GC、诊断包剥离与资源账本。"""
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from integration import chapter_editor as ce
from integration import maintenance


def project(folder):
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


class MaintenanceTest(unittest.TestCase):
    def test_gc_protects_current_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "开端", "content": "正文内容\n",
                                  "op_id": "m-1"})
            history = book / ".webnovel" / "history"
            history.mkdir()
            orphan = history / "orphan.md"
            orphan.write_text("旧快照", encoding="utf-8")
            old = time.time() - 30 * 86400
            os.utime(orphan, (old, old))
            dry = maintenance.collect_garbage(book, dry_run=True)
            self.assertEqual(dry["count"], 1)
            self.assertTrue(orphan.exists())
            real = maintenance.collect_garbage(book, dry_run=False)
            self.assertEqual(real["bytes"], len("旧快照".encode()))
            self.assertFalse(orphan.exists())
            self.assertTrue((book / "正文").glob("*.md"))

    def test_diagnostic_bundle_strips_content_and_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "秘密标题", "content": "这是不能外泄的正文。\n",
                                  "op_id": "m-2"})
            (book / ".webnovel" / "writer_receipts.json").write_text(json.dumps({"1": {
                "api_key": "sk-secret", "content": "正文", "published_sha256": "x"}}),
                encoding="utf-8")
            destination = Path(folder) / "diag.zip"
            result = maintenance.export_bundle(book, destination)
            self.assertFalse(result["contains_content"])
            with zipfile.ZipFile(destination) as bundle:
                text = bundle.read("diagnostics.json").decode("utf-8")
                names = bundle.namelist()
            self.assertNotIn("这是不能外泄的正文", text)
            self.assertNotIn("sk-secret", text)
            self.assertIn("chapters.index.json", names)
            self.assertTrue(maintenance.health(book)["status"] in {"ok", "degraded"})

    def test_ledger_counts_states(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "开端", "content": "一\n", "op_id": "m-3"})
            ledger = maintenance.resource_ledger(book)
            self.assertEqual(set(ledger["states"]),
                             {"reserved", "dispatched", "settled", "unknown_charge", "released"})
            self.assertGreaterEqual(ledger["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
