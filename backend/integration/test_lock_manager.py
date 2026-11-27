"""八级锁序、SQLite 嵌套与分域短锁。"""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fanqie_auto_publish import publication_safety as safety
from integration import lock_manager as lm
from integration import workbench_db as wb


class LockManagerTest(unittest.TestCase):
    def test_ascending_order_and_reverse_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            with lm.hold(project, "config"):
                with lm.hold(project, "book_meta"):
                    self.assertEqual(lm.held_levels(), [1, 2])
                    with lm.hold(project, "chapter_text"):
                        self.assertEqual(lm.held_levels(), [1, 2, 4])
                    with self.assertRaises(lm.LockOrderError) as caught:
                        with lm.hold(project, "config"):
                            pass
                    self.assertEqual(caught.exception.code, "lock_order_violation")
            self.assertEqual(lm.held_levels(), [])

    def test_sqlite_transaction_blocks_os_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            with lm.sqlite_scope():
                with self.assertRaises(lm.SqliteNestingError):
                    with lm.hold(Path(folder), "chapter_text"):
                        pass
            with lm.hold(Path(folder), "chapter_text"):
                self.assertEqual(lm.held_levels(), [4])

    def test_ordered_acquires_sorted_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            with lm.ordered(Path(folder), [("publication", "p"), ("config", "c"),
                                           ("chapter_text", "ch1")]):
                self.assertEqual(lm.held_levels(), [1, 4, 6])
            self.assertEqual(lm.held_levels(), [])

    def test_lock_contention_times_out(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            ready, release = threading.Event(), threading.Event()

            def holder():
                with lm.hold(project, "chapter_text", "1", timeout=2):
                    ready.set()
                    release.wait(5)

            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(ready.wait(5))
            started = time.monotonic()
            try:
                with self.assertRaises(lm.LockError) as caught:
                    with lm.hold(project, "chapter_text", "1", timeout=0.12):
                        pass
                self.assertEqual(caught.exception.code, "lock_busy")
                self.assertGreaterEqual(time.monotonic() - started, 0.08)
            finally:
                release.set()
                thread.join(5)

    def test_unknown_level_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(lm.LockError):
                with lm.hold(Path(folder), "nope"):
                    pass

    def test_caller_publication_blocked_propagates_unchanged(self):
        """审计 C-05：锁内业务抛出的 resource_busy 不能被误判为锁竞争。"""
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(safety.PublicationBlocked) as caught:
                with lm.hold(Path(folder), "chapter_text"):
                    raise safety.PublicationBlocked("resource_busy")
            self.assertEqual(str(caught.exception), "resource_busy")
            self.assertEqual(lm.held_levels(), [])

    def test_nested_lock_contention_is_lock_busy_not_runtime_error(self):
        """审计 C-05：调用者在锁内申请第二把忙锁，错误码必须仍是 lock_busy。"""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            ready, release = threading.Event(), threading.Event()

            def holder():
                with lm.hold(project, "publication", "shared", timeout=2):
                    ready.set()
                    release.wait(5)

            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(ready.wait(5))
            try:
                with self.assertRaises(lm.LockError) as caught:
                    with lm.hold(project, "chapter_text", "1"):
                        with lm.hold(project, "publication", "shared", timeout=0.1):
                            pass
                self.assertEqual(caught.exception.code, "lock_busy")
            finally:
                release.set()
                thread.join(5)

    def test_write_tx_marks_sqlite_scope(self):
        """审计 C-04：写事务期间申请 OS 文件锁必须被嵌套守卫拒绝。"""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "书"
            (project / ".webnovel").mkdir(parents=True)
            wb.initialize(project)
            with wb.write_tx(project):
                with self.assertRaises(lm.SqliteNestingError):
                    with lm.hold(project, "chapter_text"):
                        pass
            with lm.hold(project, "chapter_text"):
                with wb.write_tx(project) as db:
                    db.execute("INSERT OR REPLACE INTO workbench_meta(key, value) VALUES('probe','1')")

    def test_write_tx_is_reentrant_via_savepoints(self):
        """审计 C-02：同线程嵌套写事务使用 SAVEPOINT，不再自锁死。"""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "书"
            (project / ".webnovel").mkdir(parents=True)
            wb.initialize(project)
            started = time.monotonic()
            with wb.write_tx(project) as outer:
                outer.execute("INSERT OR REPLACE INTO workbench_meta(key, value) VALUES('outer','1')")
                with wb.write_tx(project) as inner:
                    inner.execute("INSERT OR REPLACE INTO workbench_meta(key, value) VALUES('inner','1')")
                # 内层回滚只撤销内层写入，外层事务仍然有效。
                with self.assertRaises(sqlite3.OperationalError):
                    with wb.write_tx(project) as failing:
                        failing.execute("INSERT OR REPLACE INTO workbench_meta(key, value) VALUES('bad','1')")
                        failing.execute("SELECT * FROM missing_table")
            self.assertLess(time.monotonic() - started, 5.0)
            wb.initialize(project)
            with wb.connect(project) as db:
                rows = {row[0]: row[1] for row in db.execute("SELECT key, value FROM workbench_meta")}
            self.assertEqual(rows.get("outer"), "1")
            self.assertEqual(rows.get("inner"), "1")
            self.assertNotIn("bad", rows)

    def test_ensure_chapter_meta_inside_write_tx_does_not_deadlock(self):
        """审计 C-02：导入旧稿后无 chapter_meta 的书，批注/质量路径不会锁死。"""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "书"
            (project / ".webnovel").mkdir(parents=True)
            wb.initialize(project)
            with wb.write_tx(project) as db:
                uid = wb.chapter_uid(project, 7)
                self.assertTrue(uid.startswith("chuid_"))
                row = db.execute("SELECT chapter_uid FROM chapter_meta WHERE chapter_id=7").fetchone()
                self.assertEqual(row[0], uid)
            self.assertEqual(wb.chapter_uid(project, 7), uid)

    def test_initialize_skips_schema_rewrite_when_current(self):
        """审计 C-45：读接口反复 initialize 时不应每次都写 schema。"""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "书"
            (project / ".webnovel").mkdir(parents=True, exist_ok=True)
            wb.initialize(project)
            with mock.patch.object(wb, "_apply_schema") as apply:
                for _ in range(6):
                    wb.initialize(project)
                apply.assert_not_called()

    def test_initialize_migrates_old_database_columns(self):
        """审计 C-08：旧库缺少 hold_requested 列时必须自动迁移。"""
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "书"
            (project / ".webnovel").mkdir(parents=True)
            wb.initialize(project)
            with wb.connect(project) as db:
                db.execute("ALTER TABLE task_queue DROP COLUMN hold_requested")
                db.execute("UPDATE workbench_meta SET value='1' WHERE key='schema_version'")
            wb.initialize(project)
            with wb.connect(project) as db:
                columns = {row[1] for row in db.execute("PRAGMA table_info(task_queue)")}
                version = db.execute(
                    "SELECT value FROM workbench_meta WHERE key='schema_version'").fetchone()[0]
            self.assertIn("hold_requested", columns)
            self.assertEqual(str(version), str(wb.SCHEMA_VERSION))


if __name__ == "__main__":
    unittest.main()
