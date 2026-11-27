"""跨文件事务、备份屏障、安全恢复、降级导出与发布快照的回归测试。"""
import errno
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from integration import transaction_journal as journal


def make_project(folder) -> Path:
    root = Path(folder) / "书"
    for name in ("正文", "大纲", "设定", ".webnovel/chapter_versions/objects"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def tx_file(root: Path, tx_id: str) -> Path:
    return journal.tx_root(root) / f"tx_{tx_id}.json"


def write_sqlite(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS sample (value INTEGER)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def read_sqlite(path: Path) -> int:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute("SELECT value FROM sample").fetchone()[0]
    finally:
        connection.close()


def receipt_document() -> dict:
    return {
        "1": {
            "current": "a" * 64,
            "sha256": "a" * 64,
            "version_id": "ver_0001_abcd1234",
            "content_sha256": "a" * 64,
            "title_digest": "b" * 64,
            "version_fingerprint": "c" * 64,
            "author_confirmed": True,
            "review": {"success": True},
        }
    }


SNAPSHOT = {
    "platform": "fanqie",
    "account_id": "account_1",
    "project_id": "project_1",
    "chapter_uid": "chuid_12345678",
    "chapter_number": 3,
    "version_id": "ver_0003_abcd1234",
    "content_sha256": "a" * 64,
    "body_digest": "b" * 64,
    "title": "第3章 风起",
    "title_digest": "c" * 64,
    "contract_hash": "d" * 64,
    "scheduled_at": "2026-11-26T10:00:00+08:00",
    "approval_id": "apv_20261126_1",
}


class JournalCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = make_project(self.folder)


class TransactionJournalTest(JournalCase):
    def test_write_convenience_and_record_shape(self):
        result = journal.write_text(self.root, "正文/第1章-标题.md", "第一章正文")
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["done"], [0])
        self.assertEqual((self.root / "正文" / "第1章-标题.md").read_text(encoding="utf-8"),
                         "第一章正文")
        record = json.loads(tx_file(self.root, result["tx_id"]).read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "done")
        self.assertEqual(record["steps"][0]["path"], "正文/第1章-标题.md")
        self.assertEqual(record["steps"][0]["sha256"],
                         hashlib.sha256("第一章正文".encode("utf-8")).hexdigest())
        self.assertEqual(record["steps"][0]["size"], len("第一章正文".encode("utf-8")))
        staged = journal.tx_root(self.root) / result["tx_id"] / record["steps"][0]["staged"]
        self.assertTrue(staged.is_file())
        self.assertEqual(journal.pending(self.root), [])
        journal.assert_readable(self.root)

    def test_write_bytes_roundtrip(self):
        payload = bytes(range(32)) + b"\x00\xff"
        result = journal.write_bytes(self.root, "正文/二进制.bin", payload)
        self.assertEqual(result["state"], "done")
        self.assertEqual((self.root / "正文" / "二进制.bin").read_bytes(), payload)

    def test_prepare_rejects_absolute_traversal_and_device_names(self):
        cases = [
            ("../evil.md", "path_traversal"),
            ("正文/../../evil.md", "path_traversal"),
            ("/tmp/evil.md", "absolute_path"),
            ("C:\\evil.md", "absolute_path"),
            ("正文/CON.md", "reserved_name"),
            ("正文/第1章.md ", "trailing_space_or_dot"),
            ("正文/第1章.md.", "trailing_space_or_dot"),
        ]
        for path, code in cases:
            with self.subTest(path=path):
                with self.assertRaises(journal.UnsafePath) as caught:
                    journal.prepare(self.root, [{"kind": "write", "path": path, "content": "x"}])
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(list(journal.tx_root(self.root).glob("tx_*.json")), [])

    def test_prepare_same_tx_id_is_idempotent_but_never_diverges(self):
        steps = [{"kind": "write", "path": "正文/第1章.md", "content": "A"}]
        first = journal.prepare(self.root, steps, tx_id="fixed001")
        second = journal.prepare(self.root, steps, tx_id="tx_fixed001")
        self.assertEqual(first, second)
        self.assertEqual(len(list(journal.tx_root(self.root).glob("tx_*.json"))), 1)
        with self.assertRaises(journal.TransactionConflict) as caught:
            journal.prepare(self.root, [{"kind": "write", "path": "正文/第1章.md",
                                         "content": "B"}], tx_id="fixed001")
        self.assertEqual(caught.exception.code, "tx_exists")

    def test_apply_trusts_only_tx_record_not_index_json(self):
        chapter = self.root / "正文" / "第1章-标题.md"
        chapter.write_text("旧正文", encoding="utf-8")
        index = self.root / ".webnovel" / "chapter_versions" / "index.json"
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章-标题.md", "content": "新正文"},
            {"kind": "rename", "from_path": "正文/第1章-标题.md",
             "to_path": "正文/第1章-新标题.md"},
        ])
        index.write_text("{ 这不是 JSON", encoding="utf-8")
        (self.root / "正文" / "第1章-干扰项.md").write_text("干扰", encoding="utf-8")

        result = journal.apply(self.root, tx_id)

        self.assertEqual(result["state"], "done")
        self.assertEqual((self.root / "正文" / "第1章-新标题.md").read_text(encoding="utf-8"),
                         "新正文")
        self.assertFalse((self.root / "正文" / "第1章-标题.md").exists())
        self.assertEqual((self.root / "正文" / "第1章-干扰项.md").read_text(encoding="utf-8"),
                         "干扰")
        self.assertEqual(index.read_text(encoding="utf-8"), "{ 这不是 JSON")

    def test_apply_is_idempotent_after_done(self):
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章.md", "content": "一次"},
        ])
        first = journal.apply(self.root, tx_id)
        target = self.root / "正文" / "第1章.md"
        before = target.stat().st_mtime_ns
        second = journal.apply(self.root, tx_id)
        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(second["state"], "done")
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_recover_finishes_crash_between_steps(self):
        (self.root / "正文" / "第3章.md").write_text("待删", encoding="utf-8")
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章.md", "content": "一"},
            {"kind": "write", "path": "正文/第2章.md", "content": "二"},
            {"kind": "delete", "path": "正文/第3章.md"},
        ])
        (self.root / "正文" / "第1章.md").write_text("一", encoding="utf-8")
        path = tx_file(self.root, tx_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["state"] = "applying"
        record["done"] = [0]
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

        with self.assertRaises(journal.RecoveryInProgress):
            journal.assert_readable(self.root)
        self.assertEqual(len(journal.pending(self.root)), 1)

        summaries = journal.recover(self.root)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["action"], "applied")
        self.assertEqual(summaries[0]["state"], "done")
        self.assertEqual((self.root / "正文" / "第1章.md").read_text(encoding="utf-8"), "一")
        self.assertEqual((self.root / "正文" / "第2章.md").read_text(encoding="utf-8"), "二")
        self.assertFalse((self.root / "正文" / "第3章.md").exists())
        journal.assert_readable(self.root)

    def test_recover_uses_disk_content_when_done_marker_missing(self):
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章.md", "content": "已写"},
            {"kind": "write", "path": "正文/第2章.md", "content": "未写"},
        ])
        (self.root / "正文" / "第1章.md").write_text("已写", encoding="utf-8")
        # 模拟「第一步的文件已落盘、暂存载荷随后丢失、done 尚未推进」的崩溃现场。
        (journal.tx_root(self.root) / tx_id / "step_000.bin").unlink()

        summaries = journal.recover(self.root)

        self.assertEqual(summaries[0]["action"], "applied")
        self.assertEqual((self.root / "正文" / "第1章.md").read_text(encoding="utf-8"), "已写")
        self.assertEqual((self.root / "正文" / "第2章.md").read_text(encoding="utf-8"), "未写")

    def test_missing_staged_payload_marks_conflict_and_preserves(self):
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章.md", "content": "不会写入"},
        ])
        (journal.tx_root(self.root) / tx_id / "step_000.bin").unlink()

        summaries = journal.recover(self.root)

        self.assertEqual(summaries[0]["action"], "conflict")
        self.assertEqual(summaries[0]["error"], "staged_missing")
        self.assertEqual(summaries[0]["state"], "conflict")
        record = json.loads(tx_file(self.root, tx_id).read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "conflict")
        self.assertEqual(record["conflict"]["code"], "staged_missing")
        self.assertTrue(tx_file(self.root, tx_id).is_file())
        self.assertFalse((self.root / "正文" / "第1章.md").exists())
        self.assertEqual(journal.pending(self.root), [])
        self.assertEqual(journal.recover(self.root)[0]["action"], "skipped")

    def test_recover_marks_corrupt_record_conflict_and_preserves_it(self):
        root = journal.tx_root(self.root)
        root.mkdir(parents=True, exist_ok=True)
        broken = self.root / ".webnovel" / "transactions" / "tx_broken.json"
        broken.write_text("{ 不是 JSON", encoding="utf-8")
        weird = self.root / ".webnovel" / "transactions" / "tx_weird.json"
        weird.write_text(json.dumps({
            "schema": 1, "tx_id": "weird", "state": "applying",
            "steps": [{"kind": "write"}], "done": [],
        }), encoding="utf-8")

        summaries = {item["tx_id"]: item for item in journal.recover(self.root)}

        self.assertEqual(summaries["broken"]["action"], "skipped")
        self.assertTrue(broken.is_file())
        self.assertEqual(summaries["weird"]["action"], "conflict")
        self.assertEqual(summaries["weird"]["error"], "tx_corrupt")
        preserved = json.loads(weird.read_text(encoding="utf-8"))
        self.assertEqual(preserved["state"], "conflict")
        self.assertTrue(weird.is_file())
        self.assertEqual(journal.pending(self.root), [])

    def test_rename_retry_succeeds_after_three_permission_errors(self):
        source = self.folder / "a.md"
        target = self.folder / "b.md"
        source.write_text("内容", encoding="utf-8")
        real_replace = os.replace
        calls = {"count": 0}

        def flaky(src, dst):
            calls["count"] += 1
            if calls["count"] <= 3:
                raise PermissionError(errno.EACCES, "被占用", str(src))
            return real_replace(src, dst)

        with mock.patch("integration.transaction_journal.os.replace", side_effect=flaky):
            result = journal.rename_with_retry(source, target, attempts=6, base_delay=0)

        self.assertEqual(result, target)
        self.assertEqual(calls["count"], 4)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "内容")

    def test_rename_retry_exhaustion_never_deletes_source(self):
        source = self.folder / "a.md"
        target = self.folder / "b.md"
        source.write_text("内容", encoding="utf-8")
        with mock.patch("integration.transaction_journal.os.replace",
                        side_effect=PermissionError(errno.EACCES, "被占用")):
            with self.assertRaises(journal.FileInUse) as caught:
                journal.rename_with_retry(source, target, attempts=3, base_delay=0)
        self.assertEqual(caught.exception.attempts, 3)
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_rename_and_delete_convenience(self):
        (self.root / "正文" / "旧名.md").write_text("正文", encoding="utf-8")
        renamed = journal.rename(self.root, "正文/旧名.md", "正文/新名.md")
        self.assertEqual(renamed["state"], "done")
        self.assertTrue((self.root / "正文" / "新名.md").is_file())
        deleted = journal.delete(self.root, "正文/新名.md")
        self.assertEqual(deleted["state"], "done")
        self.assertFalse((self.root / "正文" / "新名.md").exists())
        again = journal.delete(self.root, "正文/新名.md")
        self.assertEqual(again["state"], "done")

    def test_rename_retry_handles_winerror_and_ebusy(self):
        source = self.folder / "a.md"
        target = self.folder / "b.md"
        source.write_text("内容", encoding="utf-8")
        real_replace = os.replace
        calls = {"count": 0}

        def flaky(src, dst):
            calls["count"] += 1
            if calls["count"] == 1:
                error = OSError(errno.EBUSY, "被占用", str(src))
                error.winerror = 32
                raise error
            return real_replace(src, dst)

        with mock.patch("integration.transaction_journal.os.replace", side_effect=flaky):
            journal.rename_with_retry(source, target, attempts=3, base_delay=0)
        self.assertEqual(calls["count"], 2)
        self.assertTrue(target.is_file())

    def test_rename_retry_propagates_non_retryable_errors(self):
        source = self.folder / "a.md"
        target = self.folder / "b.md"
        source.write_text("内容", encoding="utf-8")
        with mock.patch("integration.transaction_journal.os.replace",
                        side_effect=FileNotFoundError(errno.ENOENT, "没有此文件")):
            with self.assertRaises(FileNotFoundError):
                journal.rename_with_retry(source, target, attempts=3, base_delay=0)
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_staged_corruption_never_truncates_target(self):
        target = self.root / "正文" / "第1章.md"
        target.write_text("原有正文", encoding="utf-8")
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章.md", "content": "新正文内容"},
        ])
        staged = journal.tx_root(self.root) / tx_id / "step_000.bin"
        staged.write_bytes("坏坏坏坏坏".encode("utf-8"))

        with self.assertRaises(journal.TransactionConflict) as caught:
            journal.apply(self.root, tx_id)

        self.assertIn(caught.exception.code, ("staged_corrupt", "staged_size_mismatch"))
        self.assertEqual(target.read_text(encoding="utf-8"), "原有正文")
        record = json.loads(tx_file(self.root, tx_id).read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "applying")
        self.assertEqual(record["last_error"]["code"], caught.exception.code)

    def test_windows_reserved_names(self):
        for name in ("CON", "con", "con.md", "NUL.txt", "COM1.tar.gz", "lpt9",
                     "AUX", "PRN.log", "COM9"):
            with self.subTest(name=name):
                with self.assertRaises(journal.UnsafePath) as caught:
                    journal.validate_windows_name(name)
                self.assertEqual(caught.exception.code, "reserved_name")
        for name in ("bad.", "bad ", "a:b", "a\tb", "", ".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(journal.UnsafePath):
                    journal.validate_windows_name(name)
        for name in ("第1章-标题.md", "chapter_versions", "index.json", "CONSOLE.md"):
            self.assertEqual(journal.validate_windows_name(name), name)

    def test_assert_within_rejects_symlink_escape(self):
        outside = self.folder / "外部"
        outside.mkdir()
        (outside / "secret.txt").write_text("秘密", encoding="utf-8")
        link = self.root / "链接"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"当前环境不能创建符号链接：{exc}")
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.assert_within(self.root, "链接/secret.txt")
        self.assertEqual(caught.exception.code, "symlink")
        with self.assertRaises(journal.UnsafePath):
            journal.assert_within(self.root, "../外部/secret.txt")

    def test_assert_within_rejects_windows_reparse_point(self):
        fake = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400,
                                     st_size=0)

        def not_a_symlink(self):
            return False

        with mock.patch.object(Path, "is_symlink", new=not_a_symlink), \
                mock.patch("integration.transaction_journal.os.lstat", return_value=fake):
            with self.assertRaises(journal.UnsafePath) as caught:
                journal.assert_within(self.root, "junction/evil.md")
        self.assertEqual(caught.exception.code, "reparse_point")

    def test_assert_within_accepts_regular_project_paths(self):
        target = self.root / "正文" / "第1章-标题.md"
        target.write_text("正文", encoding="utf-8")
        self.assertEqual(journal.assert_within(self.root, "正文/第1章-标题.md"), target.resolve())
        self.assertEqual(journal.assert_within(self.root, target), target.resolve())

    def test_meta_is_preserved(self):
        result = journal.write_text(self.root, "正文/第1章.md", "正文",
                                    meta={"op_id": "op_1", "actor": "writer"})
        self.assertEqual(result["meta"]["op_id"], "op_1")
        record = json.loads(tx_file(self.root, result["tx_id"]).read_text(encoding="utf-8"))
        self.assertEqual(record["meta"]["actor"], "writer")


class BackupBarrierTest(JournalCase):
    def build_full_project(self) -> Path:
        (self.root / "正文" / "第1章.md").write_text("hello", encoding="utf-8")
        (self.root / "大纲" / "总纲.md").write_text("大纲", encoding="utf-8")
        (self.root / "设定" / "人物.md").write_text("人物", encoding="utf-8")
        (self.root / ".webnovel" / "chapter_versions" / "index.json").write_text(
            json.dumps({"chapters": {}}), encoding="utf-8")
        (self.root / ".webnovel" / "chapter_versions" / "objects" / "obj.txt").write_text(
            "对象", encoding="utf-8")
        (self.root / ".webnovel" / "writer_receipts.json").write_text(
            json.dumps(receipt_document(), ensure_ascii=False), encoding="utf-8")
        (self.root / ".webnovel" / "story_plan.json").write_text("{}", encoding="utf-8")
        (self.root / ".webnovel" / "story_plan_meta.json").write_text("{}", encoding="utf-8")
        write_sqlite(self.root / ".webnovel" / "workbench.sqlite3", 7)
        return self.root

    def test_backup_manifest_hashes_and_preview_restore(self):
        self.build_full_project()
        destination = self.folder / "备份"
        summary = journal.backup(self.root, destination)

        self.assertEqual(summary["sqlite"], 1)
        manifest_path = destination / "backup_manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], journal.BACKUP_FORMAT)
        self.assertIsInstance(manifest["generation"], int)
        self.assertTrue(manifest["stamp"])
        self.assertEqual(manifest["count"], len(manifest["files"]))
        for entry in manifest["files"]:
            copied = destination.joinpath(*entry["path"].split("/"))
            self.assertTrue(copied.is_file(), entry["path"])
            self.assertEqual(copied.stat().st_size, entry["size"])
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(),
                             entry["sha256"])
        self.assertFalse((destination / ".webnovel" / "transactions").exists())

        inspected = journal.inspect_backup(destination)
        self.assertTrue(inspected["valid"], inspected["problems"])
        self.assertEqual(inspected["files"], manifest["count"])

        (self.root / "正文" / "第1章.md").unlink()
        preview = journal.restore_backup(self.root, destination)
        self.assertFalse(preview["confirmed"])
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(preview["count"], manifest["count"])
        self.assertFalse((self.root / "正文" / "第1章.md").exists())

        restored = journal.restore_backup(self.root, destination, confirmed=True)
        self.assertTrue(restored["confirmed"])
        self.assertEqual(restored["count"], manifest["count"])
        self.assertEqual((self.root / "正文" / "第1章.md").read_text(encoding="utf-8"), "hello")
        self.assertEqual(read_sqlite(self.root / ".webnovel" / "workbench.sqlite3"), 7)

    def test_backup_rejects_destination_inside_project(self):
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.backup(self.root, self.root / "备份")
        self.assertEqual(caught.exception.code, "destination_inside_project")

    def test_backup_waits_for_barrier_and_reports_timeout(self):
        self.build_full_project()
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第2章.md", "content": "二"},
        ])
        destination = self.folder / "备份超时"
        with self.assertRaises(journal.BarrierTimeout):
            journal.backup(self.root, destination, wait_seconds=0.1)
        self.assertFalse(destination.exists())

        journal.apply(self.root, tx_id)
        summary = journal.backup(self.root, destination, wait_seconds=1.0)
        self.assertGreaterEqual(summary["files"], 1)

    def test_barrier_timeout_with_pending_transaction(self):
        journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第1章.md", "content": "未完成"},
        ])
        with self.assertRaises(journal.BarrierTimeout):
            with journal.barrier(self.root, timeout=0.1):
                pass

    def test_barrier_returns_after_pending_drains(self):
        self.build_full_project()
        tx_id = journal.prepare(self.root, [
            {"kind": "write", "path": "正文/第2章.md", "content": "二"},
        ])
        journal.apply(self.root, tx_id)
        with journal.barrier(self.root, timeout=0.5):
            self.assertEqual(journal.pending(self.root), [])

    def test_inspect_backup_detects_tampering(self):
        self.build_full_project()
        destination = self.folder / "备份"
        journal.backup(self.root, destination)
        target = destination / "正文" / "第1章.md"
        target.write_text("world", encoding="utf-8")
        result = journal.inspect_backup(destination)
        self.assertFalse(result["valid"])
        self.assertIn("sha256_mismatch:正文/第1章.md", result["problems"])
        with self.assertRaises(journal.TransactionConflict) as caught:
            journal.restore_backup(self.root, destination, confirmed=True)
        self.assertEqual(caught.exception.code, "backup_corrupt")

    def test_restore_rejects_directory_manifest_traversal(self):
        backup = self.folder / "恶意备份"
        backup.mkdir()
        manifest = {"format": journal.BACKUP_FORMAT, "files": [
            {"path": "../evil.md", "kind": "file", "sha256": "x", "size": 1},
        ]}
        (backup / "backup_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.folder / "evil.md").write_text("原文件", encoding="utf-8")

        with self.assertRaises(journal.UnsafePath) as caught:
            journal.restore_backup(self.root, backup, confirmed=True)
        self.assertEqual(caught.exception.code, "path_traversal")
        self.assertEqual((self.folder / "evil.md").read_text(encoding="utf-8"), "原文件")

    def test_restore_rejects_absolute_manifest_path(self):
        backup = self.folder / "绝对路径备份"
        backup.mkdir()
        manifest = {"format": journal.BACKUP_FORMAT, "files": [
            {"path": "/etc/passwd", "kind": "file", "sha256": "x", "size": 1},
        ]}
        (backup / "backup_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.restore_backup(self.root, backup)
        self.assertEqual(caught.exception.code, "absolute_path")

    def test_restore_rejects_zip_slip(self):
        archive = self.folder / "恶意.zip"
        manifest = {"format": journal.BACKUP_FORMAT, "files": []}
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            stream.writestr("backup_manifest.json", json.dumps(manifest))
            stream.writestr("../evil.md", "evil")
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.restore_backup(self.root, archive)
        self.assertEqual(caught.exception.code, "path_traversal")
        self.assertFalse((self.folder / "evil.md").exists())
        self.assertFalse(journal.inspect_backup(archive)["valid"])

    def test_restore_rejects_zip_bomb(self):
        archive = self.folder / "炸弹.zip"
        manifest = {"format": journal.BACKUP_FORMAT, "files": []}
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            stream.writestr("backup_manifest.json", json.dumps(manifest))
            stream.writestr("高压缩比.txt", b"A" * (3 * 1024 * 1024))
        inspected = journal.inspect_backup(archive, max_ratio=10)
        self.assertFalse(inspected["valid"])
        self.assertTrue(any("zip_bomb_ratio" in item for item in inspected["problems"]))
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.restore_backup(self.root, archive, max_ratio=10)
        self.assertEqual(caught.exception.code, "zip_bomb_ratio")

    def test_backup_copies_extra_sqlite_and_restores_it_when_confirmed(self):
        self.build_full_project()
        manager = self.folder / "manager.sqlite3"
        write_sqlite(manager, 42)
        destination = self.folder / "备份"
        summary = journal.backup(self.root, destination, extra_sqlite=[manager])
        self.assertEqual(summary["sqlite"], 2)

        manifest = json.loads((destination / "backup_manifest.json").read_text(encoding="utf-8"))
        sqlite_entries = [item for item in manifest["files"] if item["kind"] == "sqlite"]
        self.assertEqual(len(sqlite_entries), 2)
        self.assertTrue(any(item["source"] == str(manager) for item in sqlite_entries))

        connection = sqlite3.connect(str(manager))
        try:
            connection.execute("UPDATE sample SET value = 99")
            connection.commit()
        finally:
            connection.close()

        preview = journal.restore_backup(self.root, destination)
        self.assertTrue(any(item["outside_project"] for item in preview["files"]))
        self.assertEqual(read_sqlite(manager), 99)

        journal.restore_backup(self.root, destination, confirmed=True)
        self.assertEqual(read_sqlite(manager), 42)
        self.assertEqual(read_sqlite(self.root / ".webnovel" / "workbench.sqlite3"), 7)

    def test_restore_rejects_symlink_member_in_directory_backup(self):
        outside = self.folder / "外部秘密.txt"
        outside.write_text("秘密", encoding="utf-8")
        backup = self.folder / "链接备份"
        backup.mkdir()
        manifest = {"format": journal.BACKUP_FORMAT, "files": [
            {"path": "链接.txt", "kind": "file", "sha256": "x", "size": 6},
        ]}
        (backup / "backup_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        try:
            os.symlink(outside, backup / "链接.txt")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"当前环境不能创建符号链接：{exc}")

        self.assertFalse(journal.inspect_backup(backup)["valid"])
        with self.assertRaises((journal.UnsafePath, journal.TransactionConflict)):
            journal.restore_backup(self.root, backup, confirmed=True)
        self.assertFalse((self.root / "链接.txt").exists())

    def test_restore_rejects_zip_symlink_member(self):
        archive = self.folder / "链接.zip"
        manifest = {"format": journal.BACKUP_FORMAT, "files": []}
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("backup_manifest.json", json.dumps(manifest))
            info = zipfile.ZipInfo("链接.txt")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            stream.writestr(info, "target")
        self.assertFalse(journal.inspect_backup(archive)["valid"])
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.restore_backup(self.root, archive)
        self.assertEqual(caught.exception.code, "zip_symlink")

    def test_restore_rejects_protected_system_target(self):
        if os.name == "nt":
            self.skipTest("POSIX 专用保护目录断言")
        backup = self.folder / "系统路径备份"
        backup.mkdir()
        manifest = {"format": journal.BACKUP_FORMAT, "files": [
            {"path": "db/00-evil.sqlite3", "kind": "sqlite",
             "source": "/etc/evil.sqlite3", "sha256": "x", "size": 1},
        ]}
        (backup / "backup_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(journal.UnsafePath) as caught:
            journal.restore_backup(self.root, backup, confirmed=True)
        self.assertEqual(caught.exception.code, "protected_path")

    def test_inspect_backup_reports_invalid_manifest(self):
        backup = self.folder / "坏清单"
        backup.mkdir()
        (backup / "backup_manifest.json").write_text(
            json.dumps({"format": 999, "files": []}), encoding="utf-8")
        result = journal.inspect_backup(backup)
        self.assertFalse(result["valid"])
        self.assertEqual(result["problems"], ["manifest:backup_manifest_invalid"])

    def test_zip_backup_roundtrip(self):
        self.build_full_project()
        destination = self.folder / "备份"
        journal.backup(self.root, destination)
        archive = self.folder / "备份.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(destination.rglob("*")):
                if path.is_file():
                    stream.write(path, path.relative_to(destination).as_posix())
        self.assertTrue(journal.inspect_backup(archive)["valid"])
        (self.root / "正文" / "第1章.md").unlink()
        journal.restore_backup(self.root, archive, confirmed=True)
        self.assertEqual((self.root / "正文" / "第1章.md").read_text(encoding="utf-8"), "hello")


class ExportLegacyTest(JournalCase):
    def seed(self) -> None:
        (self.root / "正文" / "第1章.md").write_text("正文一", encoding="utf-8")
        (self.root / "大纲" / "总纲.md").write_text("大纲", encoding="utf-8")
        (self.root / "设定" / "人物.md").write_text("人物", encoding="utf-8")
        (self.root / ".webnovel" / "chapter_versions" / "index.json").write_text(
            json.dumps({"chapters": {}}), encoding="utf-8")
        (self.root / ".webnovel" / "chapter_versions" / "objects" / "obj.txt").write_text(
            "对象", encoding="utf-8")
        (self.root / ".webnovel" / "writer_receipts.json").write_text(
            json.dumps(receipt_document(), ensure_ascii=False), encoding="utf-8")
        (self.root / ".webnovel" / "story_plan.json").write_text("{}", encoding="utf-8")
        (self.root / ".webnovel" / "story_plan_meta.json").write_text("{}", encoding="utf-8")
        (self.root / ".webnovel" / "secrets.json").write_text('{"api_key": "sk-秘密"}',
                                                              encoding="utf-8")
        (self.root / "账号.cookie").write_text("cookie", encoding="utf-8")
        write_sqlite(self.root / ".webnovel" / "workbench.sqlite3", 9)

    def test_clean_export_strips_new_receipt_keys_and_never_copies_state(self):
        self.seed()
        destination = self.folder / "旧版副本"
        summary = journal.export_legacy(self.root, destination, mode="clean")

        receipts = json.loads((destination / ".webnovel" / "writer_receipts.json")
                              .read_text(encoding="utf-8"))
        entry = receipts["1"]
        self.assertEqual(entry["current"], "a" * 64)
        self.assertEqual(entry["sha256"], "a" * 64)
        for key in ("version_id", "content_sha256", "title_digest",
                    "version_fingerprint", "author_confirmed"):
            self.assertNotIn(key, entry)
        self.assertEqual(summary["dropped_receipt_keys"], 5)

        self.assertTrue((destination / "正文" / "第1章.md").is_file())
        self.assertTrue((destination / "大纲" / "总纲.md").is_file())
        self.assertTrue((destination / "设定" / "人物.md").is_file())
        self.assertTrue((destination / ".webnovel" / "chapter_versions" / "index.json").is_file())
        self.assertTrue((destination / ".webnovel" / "chapter_versions" / "objects" / "obj.txt").is_file())
        self.assertTrue((destination / ".webnovel" / "story_plan.json").is_file())
        self.assertTrue((destination / ".webnovel" / "story_plan_meta.json").is_file())

        copied = {path.name for path in destination.rglob("*") if path.is_file()}
        self.assertNotIn("workbench.sqlite3", copied)
        self.assertNotIn("secrets.json", copied)
        self.assertNotIn("账号.cookie", copied)
        self.assertFalse(any(path.name.endswith((".sqlite3", "-wal", "-shm"))
                             for path in destination.rglob("*")))

        readme = (destination / "ROLLBACK-README.txt").read_text(encoding="utf-8")
        self.assertIn("严禁新旧两个版本同时打开", readme)
        self.assertIn("workbench.sqlite3", readme)

    def test_current_export_keeps_new_receipt_keys(self):
        self.seed()
        destination = self.folder / "当前副本"
        journal.export_legacy(self.root, destination, mode="current")
        receipts = json.loads((destination / ".webnovel" / "writer_receipts.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(receipts["1"]["version_id"], "ver_0001_abcd1234")
        self.assertTrue(receipts["1"]["author_confirmed"])

    def test_snapshot_export_reads_the_snapshot_not_live_files(self):
        self.seed()
        backup = self.folder / "升级前快照"
        journal.backup(self.root, backup)
        (self.root / "正文" / "第1章.md").write_text("新版内容", encoding="utf-8")
        destination = self.folder / "快照副本"
        summary = journal.export_legacy(self.root, destination, mode="snapshot",
                                        snapshot_dir=backup)
        self.assertEqual(summary["mode"], "snapshot")
        self.assertEqual((destination / "正文" / "第1章.md").read_text(encoding="utf-8"),
                         "正文一")

    def test_export_rejects_unknown_mode_and_nonempty_destination(self):
        with self.assertRaises(ValueError):
            journal.export_legacy(self.root, self.folder / "x", mode="weird")
        destination = self.folder / "非空"
        destination.mkdir()
        (destination / "旧文件.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            journal.export_legacy(self.root, destination)


class PublicationSnapshotTest(JournalCase):
    def test_snapshot_is_immutable_and_verifiable(self):
        path = journal.write_publication_snapshot(self.root, SNAPSHOT)
        self.assertEqual(path.name, "pub_apv_20261126_1.json")
        self.assertEqual(path.parent, self.root / ".publication" / "snapshots")
        first_bytes = path.read_bytes()
        record = json.loads(first_bytes.decode("utf-8"))
        self.assertEqual(record["chapter_number"], 3)
        self.assertEqual(record["content_sha256"], "a" * 64)

        again = journal.write_publication_snapshot(self.root, dict(SNAPSHOT))
        self.assertEqual(again, path)
        self.assertEqual(path.read_bytes(), first_bytes)

        with self.assertRaises(journal.TransactionConflict) as caught:
            journal.write_publication_snapshot(
                self.root, dict(SNAPSHOT, title_digest="e" * 64,
                                version_id="ver_0004_ffff0000"))
        self.assertEqual(caught.exception.code, "snapshot_immutable")
        self.assertEqual(path.read_bytes(), first_bytes)

        valid = journal.verify_publication_snapshot(self.root, SNAPSHOT["approval_id"])
        self.assertTrue(valid["valid"])
        self.assertIsNone(valid["reason"])

        changed = journal.verify_publication_snapshot(
            self.root, SNAPSHOT["approval_id"], current_version_id="ver_0004_ffff0000")
        self.assertFalse(changed["valid"])
        self.assertEqual(changed["reason"], "version_changed")

        same = journal.verify_publication_snapshot(
            self.root, SNAPSHOT["approval_id"], current_version_id=SNAPSHOT["version_id"])
        self.assertTrue(same["valid"])

    def test_snapshot_requires_every_contract_field(self):
        for field in journal.PUBLICATION_FIELDS:
            with self.subTest(field=field):
                broken = dict(SNAPSHOT)
                broken.pop(field)
                with self.assertRaises(journal.TransactionConflict) as caught:
                    journal.write_publication_snapshot(self.root, broken)
                self.assertEqual(caught.exception.code, "snapshot_incomplete")
        self.assertFalse((self.root / ".publication" / "snapshots").exists())

    def test_snapshot_rejects_unsafe_approval_id(self):
        for approval in ("../evil", "a/b", "CON", ".."):
            with self.subTest(approval=approval):
                with self.assertRaises(journal.UnsafePath):
                    journal.write_publication_snapshot(
                        self.root, dict(SNAPSHOT, approval_id=approval))
        with self.assertRaises(journal.TransactionConflict) as caught:
            journal.write_publication_snapshot(self.root, dict(SNAPSHOT, approval_id=""))
        self.assertEqual(caught.exception.code, "snapshot_incomplete")

    def test_verify_reports_missing_and_corrupt(self):
        missing = journal.verify_publication_snapshot(self.root, "apv_none")
        self.assertFalse(missing["valid"])
        self.assertEqual(missing["reason"], "snapshot_missing")

        path = journal.write_publication_snapshot(self.root, SNAPSHOT)
        path.write_text("{ 坏 JSON", encoding="utf-8")
        corrupt = journal.verify_publication_snapshot(self.root, SNAPSHOT["approval_id"])
        self.assertFalse(corrupt["valid"])
        self.assertEqual(corrupt["reason"], "snapshot_corrupt")


if __name__ == "__main__":
    unittest.main()
