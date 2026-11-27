"""引用计数 GC、诊断包剥离与资源账本。"""
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from integration import annotations
from integration import chapter_editor as ce
from integration import maintenance
from integration import workbench_db as wb


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

    def test_gc_keeps_referenced_snapshots_and_pending_previews(self):
        """审计 C3-06：引用计数生效；未引用旧快照可回收，待审预览永久保护。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "开端", "content": "正文内容\n",
                                  "op_id": "m-4"})
            digest = annotations.save_snapshot(book, "正文内容\n")
            snapshot = book / ".webnovel" / "snapshots" / f"{digest}.txt"
            orphan_digest = annotations.save_snapshot(book, "无人引用\n")
            orphan_snapshot = book / ".webnovel" / "snapshots" / f"{orphan_digest}.txt"
            with wb.write_tx(book) as db:
                db.execute(
                    "INSERT INTO annotations(id, chapter_id, chapter_uid, scope, anchor_json, "
                    "instruction, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("ann-1", 1, wb.chapter_uid(book, 1), "selection",
                     json.dumps({"base_snapshot_id": digest}), "test", "2026-01-01T00:00:00Z",
                     "2026-01-01T00:00:00Z"))
            previews = book / ".webnovel" / "revision_previews"
            previews.mkdir()
            preview = previews / "0001-abc.json"
            preview.write_text(json.dumps({"preview_id": "abc", "chapter_id": 1,
                                           "state": "pending"}), encoding="utf-8")
            old = time.time() - 30 * 86400
            for path in (snapshot, orphan_snapshot, preview):
                os.utime(path, (old, old))
            dry = maintenance.collect_garbage(book, dry_run=True, min_age_seconds=0)
            self.assertNotIn(str(snapshot.resolve()), dry["removed"])
            self.assertNotIn(str(preview.resolve()), dry["removed"])
            self.assertIn(str(orphan_snapshot.resolve()), dry["removed"])
            maintenance.collect_garbage(book, dry_run=False, min_age_seconds=0)
            self.assertTrue(snapshot.is_file())
            self.assertFalse(orphan_snapshot.is_file())
            self.assertTrue(preview.is_file())
            self.assertEqual(annotations.read_snapshot(book, digest), "正文内容\n")

    def test_health_on_missing_project_does_not_create_database(self):
        """审计 C-30：GET/导出前的健康检查不得产生写副作用。"""
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "不存在"
            report = maintenance.health(missing)
            self.assertEqual(report["status"], "missing")
            self.assertFalse((missing / ".webnovel").exists())
            report = maintenance.health(Path(folder))
            self.assertFalse((Path(folder) / ".webnovel" / "workbench.sqlite3").exists())
            with tempfile.TemporaryDirectory() as outside:
                exported = maintenance.export_bundle(Path(folder), Path(outside) / "diag.zip")
                self.assertTrue(Path(exported["path"]).is_file())
            self.assertFalse((Path(folder) / ".webnovel" / "workbench.sqlite3").exists())

    def test_health_orphan_index_is_informational_after_normal_delete(self):
        """审计 C-28：正常删章后 chapter_meta 仍在，不能永久 P1 degraded。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "开端", "content": "一\n", "op_id": "m-5"})
            body = next((book / "正文").glob("*.md"))
            body.unlink()
            report = maintenance.health(book)
            orphan = [item for item in report["issues"] if item["code"] == "orphan_chapter_index"]
            self.assertEqual(len(orphan), 1)
            self.assertEqual(orphan[0]["severity"], "P2")
            self.assertEqual(report["status"], "ok")

    def test_system_health_treats_lazy_databases_as_not_created(self):
        """审计 C-29：新装环境没有 costs.sqlite3 不应直接 degraded。"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "manager.sqlite3").write_bytes(b"")
            report = maintenance.system_health(root)
            costs = next(item for item in report["checks"] if item["name"] == "costs.sqlite3")
            self.assertTrue(costs["ok"])
            self.assertEqual(costs["state"], "not_created")
            self.assertEqual(report["status"], "ok")

    def test_export_rejects_destination_outside_allowed_directory(self):
        """审计 C-14：即便调用方传了路径，维护层也拒绝越界导出。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "开端", "content": "一\n", "op_id": "m-6"})
            allowed = Path(folder) / "diagnostics"
            outside = Path(folder) / "elsewhere" / "x.zip"
            with self.assertRaises(maintenance.MaintenanceError) as caught:
                maintenance.export_bundle(book, outside, allowed_dir=allowed)
            self.assertEqual(caught.exception.code, "destination_outside_allowed")
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
