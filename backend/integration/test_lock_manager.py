"""八级锁序、SQLite 嵌套与分域短锁。"""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from integration import lock_manager as lm


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


if __name__ == "__main__":
    unittest.main()
