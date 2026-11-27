"""Adversarial tests for ``integration.workbench_db`` (v0.8 Wave 1).

Run with::

    cd /home/ubuntu/projects/dsh-chapter-whale
    PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend \
        python3 -B -X utf8 -m unittest integration.test_workbench_db_adversarial -v

The suite covers the plan 05 §1-§2 contracts: multi-thread and multi-process
draft serialization, ABA, idempotency, FTS5 recall/tokenization, schema
upgrade behavior and Unicode round-trips.  Tests marked
``@unittest.expectedFailure`` encode confirmed defects in the current module;
remove the decorator after the production fix, at which point the test becomes
an ordinary regression test.  The corresponding defects are listed in the
review report.
"""
from __future__ import annotations

import hashlib
import multiprocessing
import sqlite3
import tempfile
import threading
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Empty
from unittest import mock

from integration import workbench_db as wb

LEGACY_TABLES = {"projects", "operations", "settings", "request_budget", "usage_events"}


def _make_project(folder: str) -> Path:
    root = Path(folder) / "书"
    for name in ("正文", "大纲", "设定"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _fts5_enabled() -> bool:
    con = sqlite3.connect(":memory:")
    try:
        return any(row[0] == "ENABLE_FTS5" for row in con.execute("PRAGMA compile_options"))
    finally:
        con.close()


HAS_FTS5 = _fts5_enabled()


def _wal_file(project) -> Path:
    return Path(str(wb.db_path(project)) + "-wal")


def _wal_bytes(project) -> int:
    try:
        return _wal_file(project).stat().st_size
    except OSError:
        return 0


def _mp_worker(project: str, worker_id: int, save_count: int, result_queue) -> None:
    """Child process body: 20 serialized draft saves + 20 idempotent ops."""
    try:
        successes = []
        conflicts = 0
        for index in range(save_count):
            body = f"p{worker_id}-s{index}"
            for _attempt in range(5000):
                current = wb.get_draft(project, 1)
                try:
                    draft = wb.save_draft(
                        project,
                        1,
                        title=f"进程{worker_id}",
                        content=body,
                        expected_draft_id=current["draft_id"] if current else None,
                        expected_draft_epoch=current["draft_epoch"] if current else 0,
                        expected_draft_revision=current["draft_revision"] if current else 0,
                    )
                except wb.DraftConflict:
                    conflicts += 1
                    continue
                successes.append((int(draft["draft_revision"]), body, int(draft["draft_epoch"])))
                break
            else:
                raise RuntimeError("draft save retry limit exhausted")

            op_id = f"mp-{worker_id}-{index}"
            begun = wb.idempotency_begin(
                project,
                actor="worker",
                project_id="mp-project",
                action="chapter_save",
                op_id=op_id,
                params={"worker": worker_id, "index": index},
            )
            if begun["status"] != "new":
                raise AssertionError(f"unexpected status for fresh op_id: {begun['status']!r}")
            wb.idempotency_complete(
                project,
                actor="worker",
                project_id="mp-project",
                action="chapter_save",
                op_id=op_id,
                response={"worker": worker_id, "index": index},
            )
        result_queue.put(("ok", worker_id, successes, conflicts))
    except BaseException as exc:  # noqa: BLE001 - report everything to the parent
        result_queue.put(
            ("error", worker_id, type(exc).__name__, str(exc), traceback.format_exc())
        )


class _WorkbenchBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = _make_project(self._tmp.name)

    def initialize(self) -> None:
        try:
            wb.initialize(self.root)
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).lower():
                self.skipTest("SQLite build lacks FTS5")
            raise

    def history(self, chapter: int = 1) -> list:
        with wb.connect(self.root) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT draft_id, draft_epoch, draft_revision, content_sha256 "
                    "FROM drafts_history WHERE chapter_id=? ORDER BY draft_revision",
                    (chapter,),
                )
            ]


class DraftConcurrencyTest(_WorkbenchBase):
    def test_eight_threads_twenty_saves_each_serialize_without_lost_update(self) -> None:
        self.initialize()
        thread_count, saves_per_thread = 8, 20
        total = thread_count * saves_per_thread
        barrier = threading.Barrier(thread_count)
        lock = threading.Lock()
        successes: list = []
        conflicts: list = []
        errors: list = []

        def worker(tid: int) -> None:
            completed = 0
            try:
                initial = wb.get_draft(self.root, 1)
                if initial is not None:
                    raise AssertionError("chapter had a draft before the race started")
                barrier.wait(timeout=15)
                # Phase 1: every thread submits the same "no draft" identity.
                # Exactly one must win; the other seven must receive DraftConflict.
                body = f"t{tid}-s0"
                try:
                    draft = wb.save_draft(
                        self.root,
                        1,
                        title="并发草稿",
                        content=body,
                        expected_draft_id=None,
                        expected_draft_epoch=0,
                        expected_draft_revision=0,
                    )
                except wb.DraftConflict:
                    with lock:
                        conflicts.append(tid)
                else:
                    with lock:
                        successes.append(
                            (int(draft["draft_revision"]), body, draft["draft_id"],
                             int(draft["draft_epoch"]))
                        )
                    completed = 1

                # Phase 2: every thread performs its remaining successful saves.
                while completed < saves_per_thread:
                    current = wb.get_draft(self.root, 1)
                    if current is None:
                        raise AssertionError("active draft disappeared during contention")
                    body = f"t{tid}-s{completed}"
                    try:
                        draft = wb.save_draft(
                            self.root,
                            1,
                            title="并发草稿",
                            content=body,
                            expected_draft_id=current["draft_id"],
                            expected_draft_epoch=int(current["draft_epoch"]),
                            expected_draft_revision=int(current["draft_revision"]),
                        )
                    except wb.DraftConflict:
                        with lock:
                            conflicts.append(tid)
                        continue
                    with lock:
                        successes.append(
                            (int(draft["draft_revision"]), body, draft["draft_id"],
                             int(draft["draft_epoch"]))
                        )
                    completed += 1
            except BaseException as exc:  # noqa: BLE001 - surfaced by the test
                with lock:
                    errors.append((tid, repr(exc), traceback.format_exc()))

        threads = [
            threading.Thread(target=worker, args=(tid,), daemon=True, name=f"draft-{tid}")
            for tid in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)

        self.assertFalse(any(thread.is_alive() for thread in threads), "worker thread hung")
        self.assertEqual(errors, [])
        self.assertEqual(len(successes), total)
        self.assertGreaterEqual(len(conflicts), thread_count - 1)
        revisions = sorted(item[0] for item in successes)
        self.assertEqual(revisions, list(range(1, total + 1)))

        draft_ids = {item[2] for item in successes}
        epochs = {item[3] for item in successes}
        self.assertEqual(len(draft_ids), 1)
        self.assertEqual(epochs, {1})

        body_by_revision = {item[0]: item[1] for item in successes}
        final = wb.get_draft(self.root, 1)
        self.assertIsNotNone(final)
        self.assertEqual(int(final["draft_revision"]), total)
        self.assertEqual(final["content"], body_by_revision[total])
        self.assertEqual(final["draft_id"], next(iter(draft_ids)))

        history = self.history()
        self.assertEqual(len(history), total)
        self.assertEqual([row["draft_revision"] for row in history], list(range(1, total + 1)))
        for row in history:
            expected = hashlib.sha256(body_by_revision[row["draft_revision"]].encode("utf-8")).hexdigest()
            self.assertEqual(row["content_sha256"], expected)

    def test_aba_replay_after_clear_and_recreate_is_rejected(self) -> None:
        self.initialize()
        first = wb.save_draft(
            self.root, 1, title="开端", content="第一版",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        self.assertEqual((int(first["draft_epoch"]), int(first["draft_revision"])), (1, 1))

        cleared = wb.clear_draft_if_matches(
            self.root, 1,
            draft_id=first["draft_id"],
            draft_epoch=int(first["draft_epoch"]),
            draft_revision=int(first["draft_revision"]),
        )
        self.assertTrue(cleared["cleared"])
        meta_epoch = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])
        self.assertGreater(meta_epoch, int(first["draft_epoch"]))

        # Replay before a new draft exists: old draft_id cannot be reused.
        with self.assertRaises(wb.DraftConflict) as caught:
            wb.save_draft(
                self.root, 1, title="旧平板", content="ABA 重放",
                expected_draft_id=first["draft_id"],
                expected_draft_epoch=int(first["draft_epoch"]),
                expected_draft_revision=int(first["draft_revision"]),
            )
        self.assertEqual(caught.exception.code, "draft_conflict")
        self.assertIsNone(wb.get_draft(self.root, 1))
        self.assertEqual(len(self.history()), 1)

        second = wb.save_draft(
            self.root, 1, title="开端", content="重建版",
            expected_draft_id=None, expected_draft_epoch=meta_epoch,
            expected_draft_revision=0,
        )
        self.assertNotEqual(second["draft_id"], first["draft_id"])
        self.assertGreater(int(second["draft_epoch"]), int(first["draft_epoch"]))
        self.assertGreater(int(second["draft_epoch"]), meta_epoch)
        self.assertEqual(int(second["draft_revision"]), 1)

        # Replay of the old full tuple after the new draft is live.
        with self.assertRaises(wb.DraftConflict):
            wb.save_draft(
                self.root, 1, title="旧平板", content="ABA 重放",
                expected_draft_id=first["draft_id"],
                expected_draft_epoch=int(first["draft_epoch"]),
                expected_draft_revision=int(first["draft_revision"]),
            )
        current = wb.get_draft(self.root, 1)
        self.assertEqual(current["draft_id"], second["draft_id"])
        self.assertEqual(current["content"], "重建版")
        self.assertEqual(len(self.history()), 2)

    def test_clear_preserves_advanced_revision_and_new_draft_id(self) -> None:
        self.initialize()
        first = wb.save_draft(
            self.root, 1, title="稿", content="rev1",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        second = wb.save_draft(
            self.root, 1, title="稿", content="rev2",
            expected_draft_id=first["draft_id"],
            expected_draft_epoch=int(first["draft_epoch"]),
            expected_draft_revision=int(first["draft_revision"]),
        )
        meta_before = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])

        stale = wb.clear_draft_if_matches(
            self.root, 1,
            draft_id=first["draft_id"],
            draft_epoch=int(first["draft_epoch"]),
            draft_revision=int(first["draft_revision"]),
        )
        self.assertFalse(stale["cleared"])
        self.assertTrue(stale["draft_preserved"])
        self.assertEqual(int(stale["current_draft_revision"]), 2)
        self.assertEqual(wb.get_draft(self.root, 1)["content"], "rev2")

        exact = wb.clear_draft_if_matches(
            self.root, 1,
            draft_id=second["draft_id"],
            draft_epoch=int(second["draft_epoch"]),
            draft_revision=int(second["draft_revision"]),
        )
        self.assertTrue(exact["cleared"])
        self.assertIsNone(wb.get_draft(self.root, 1))
        meta_after = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])
        self.assertGreater(meta_after, meta_before)

        third = wb.save_draft(
            self.root, 1, title="稿", content="rev3",
            expected_draft_id=None, expected_draft_epoch=meta_after,
            expected_draft_revision=0,
        )
        self.assertGreater(int(third["draft_epoch"]), int(second["draft_epoch"]))
        self.assertEqual(int(third["draft_revision"]), 1)

        old_again = wb.clear_draft_if_matches(
            self.root, 1,
            draft_id=second["draft_id"],
            draft_epoch=int(second["draft_epoch"]),
            draft_revision=int(second["draft_revision"]),
        )
        self.assertFalse(old_again["cleared"])
        self.assertTrue(old_again["draft_preserved"])
        self.assertEqual(old_again["current_draft_id"], third["draft_id"])
        self.assertEqual(wb.get_draft(self.root, 1)["content"], "rev3")

    def test_delete_draft_advances_epoch_and_rejects_stale_id(self) -> None:
        self.initialize()
        first = wb.save_draft(
            self.root, 1, title="稿", content="rev1",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        before = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])
        deleted = wb.delete_draft(self.root, 1, draft_id=first["draft_id"])
        self.assertTrue(deleted["deleted"])
        self.assertIsNone(wb.get_draft(self.root, 1))
        after = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])
        self.assertGreater(after, before)
        self.assertEqual(int(deleted["draft_epoch"]), after)

        second = wb.save_draft(
            self.root, 1, title="稿", content="fresh",
            expected_draft_id=None, expected_draft_epoch=after,
            expected_draft_revision=0,
        )
        self.assertGreater(int(second["draft_epoch"]), int(first["draft_epoch"]))
        self.assertEqual(int(second["draft_revision"]), 1)
        advanced = wb.save_draft(
            self.root, 1, title="稿", content="rev2",
            expected_draft_id=second["draft_id"],
            expected_draft_epoch=int(second["draft_epoch"]),
            expected_draft_revision=int(second["draft_revision"]),
        )
        self.assertEqual(int(advanced["draft_revision"]), 2)

        with self.assertRaises(wb.DraftConflict):
            wb.delete_draft(self.root, 1, draft_id="drf_00000000")
        current = wb.get_draft(self.root, 1)
        self.assertEqual(current["draft_id"], second["draft_id"])
        self.assertEqual(current["content"], "rev2")

    def test_draft_epoch_never_regresses_when_clear_races_stale_meta(self) -> None:
        """The anti-ABA epoch only advances; clear and save cannot reuse it."""
        self.initialize()
        first = wb.save_draft(
            self.root, 1, title="桌面", content="desktop",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        self.assertEqual(int(first["draft_epoch"]), 1)
        cleared = wb.clear_draft_if_matches(
            self.root, 1, draft_id=first["draft_id"],
            draft_epoch=int(first["draft_epoch"]), draft_revision=int(first["draft_revision"]),
        )
        self.assertTrue(cleared["cleared"])
        meta_after_clear = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])
        self.assertEqual(meta_after_clear, 2)
        second = wb.save_draft(
            self.root, 1, title="旧平板", content="stale",
            expected_draft_id=None, expected_draft_epoch=meta_after_clear,
            expected_draft_revision=0,
        )
        self.assertGreater(int(second["draft_epoch"]), int(first["draft_epoch"]))
        self.assertGreaterEqual(int(second["draft_epoch"]), meta_after_clear)
        meta_final = int(wb.ensure_chapter_meta(self.root, 1)["draft_epoch"])
        self.assertGreaterEqual(meta_final, int(second["draft_epoch"]))


class IdempotencyTest(_WorkbenchBase):
    def test_concurrent_same_op_id_has_exactly_one_new(self) -> None:
        self.initialize()
        thread_count = 8
        barrier = threading.Barrier(thread_count)
        lock = threading.Lock()
        statuses: list = []
        errors: list = []

        def worker() -> None:
            try:
                barrier.wait(timeout=15)
                result = wb.idempotency_begin(
                    self.root, actor="author", project_id="p", action="chapter_save",
                    op_id="op-same", params={"chapter": 1, "content": "甲"},
                )
                with lock:
                    statuses.append(result["status"])
            except BaseException as exc:  # noqa: BLE001 - surfaced by the test
                with lock:
                    errors.append((repr(exc), traceback.format_exc()))

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(statuses), thread_count)
        self.assertEqual(statuses.count("new"), 1)
        self.assertEqual(statuses.count("in_progress"), thread_count - 1)
        with wb.connect(self.root) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT state FROM idempotency_keys").fetchone()[0],
                "in_progress",
            )

    def test_mismatch_completed_response_and_failed_retry(self) -> None:
        self.initialize()
        params = {"chapter": 1, "content": "甲"}
        first = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-1", params=params,
        )
        self.assertEqual(first["status"], "new")

        mismatch = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-1", params={"chapter": 2},
        )
        self.assertEqual(mismatch["status"], "mismatch")
        self.assertNotIn("response", mismatch)
        self.assertEqual(mismatch["record"]["params_hash"], wb.params_hash(params))
        self.assertEqual(mismatch["record"]["state"], "in_progress")

        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-1", params=params,
            )["status"],
            "in_progress",
        )
        response = {"ok": True, "note": "完成😀", "count": 2}
        wb.idempotency_complete(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-1", response=response,
        )
        completed = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-1", params=params,
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["response"], response)
        # A new connection (each call opens one) must still see the cached body.
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-1", params=params,
            )["response"],
            response,
        )

        failed_params = {"chapter": 3}
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-2", params=failed_params,
            )["status"],
            "new",
        )
        wb.idempotency_fail(
            self.root, actor="author", project_id="p", action="chapter_save", op_id="op-2"
        )
        retry = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-2", params=failed_params,
        )
        self.assertIn(retry["status"], {"failed", "failed_retry"})
        self.assertNotIn("response", retry)
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-2", params=failed_params,
            )["status"],
            "in_progress",
        )
        wb.idempotency_complete(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-2", response={"retried": True},
        )
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-2", params=failed_params,
            )["response"],
            {"retried": True},
        )

    def test_completed_idempotency_key_is_terminal_against_late_fail(self) -> None:
        """KNOWN DEFECT P1: idempotency_fail can reopen a completed key.

        A late/timed-out worker reporting failure after another attempt already
        completed resets state to failed; the next begin returns failed_retry and
        re-runs a billed operation that must have been zero-cost replay.
        """
        self.initialize()
        params = {"chapter": 7}
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-terminal", params=params,
            )["status"],
            "new",
        )
        wb.idempotency_complete(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-terminal", response={"charged": True},
        )
        wb.idempotency_fail(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-terminal",
        )
        after = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-terminal", params=params,
        )
        self.assertEqual(after["status"], "completed")
        self.assertEqual(after["response"], {"charged": True})

    def test_completed_response_is_immutable_against_late_complete(self) -> None:
        """KNOWN DEFECT P2: idempotency_complete can overwrite a completed key.

        A duplicate/late worker completion replaces the cached response of the
        already-completed operation; replay then returns the later body.
        """
        self.initialize()
        params = {"chapter": 8}
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="op-immutable", params=params,
            )["status"],
            "new",
        )
        wb.idempotency_complete(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-immutable", response={"attempt": 1},
        )
        wb.idempotency_complete(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-immutable", response={"attempt": 2},
        )
        after = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="op-immutable", params=params,
        )
        self.assertEqual(after["status"], "completed")
        self.assertEqual(after["response"], {"attempt": 1})

    def test_gc_removes_only_expired_rows(self) -> None:
        self.initialize()
        expired_in_progress = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="expired-in-progress", params={"x": 1}, ttl_hours=0,
        )
        self.assertEqual(expired_in_progress["status"], "new")
        expired_completed = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="expired-completed", params={"x": 2}, ttl_hours=0,
        )
        self.assertEqual(expired_completed["status"], "new")
        wb.idempotency_complete(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="expired-completed", response={"done": True},
        )
        alive = wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="chapter_save",
            op_id="alive", params={"x": 3}, ttl_hours=24,
        )
        self.assertEqual(alive["status"], "new")

        future = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        self.assertEqual(wb.idempotency_gc(self.root, now=future), 2)
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="alive", params={"x": 3},
            )["status"],
            "in_progress",
        )
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="expired-in-progress", params={"x": 1},
            )["status"],
            "new",
        )
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="chapter_save",
                op_id="expired-completed", params={"x": 2},
            )["status"],
            "new",
        )
        with wb.connect(self.root) as db:
            states = {
                row[0]: row[1]
                for row in db.execute("SELECT op_id, state FROM idempotency_keys")
            }
        self.assertEqual(states["alive"], "in_progress")


class FtsTest(_WorkbenchBase):
    @unittest.skipUnless(HAS_FTS5, "SQLite build lacks ENABLE_FTS5")
    def test_compile_options_include_fts5(self) -> None:
        self.initialize()
        with wb.connect(self.root) as db:
            options = {row[0] for row in db.execute("PRAGMA compile_options")}
        self.assertIn("ENABLE_FTS5", options)

    @unittest.skipUnless(HAS_FTS5, "SQLite build lacks ENABLE_FTS5")
    def test_tokenize_punctuation_emoji_and_mixed_scripts(self) -> None:
        tokens = wb.tokenize("你好，世界！Hello123 测试。😀").split()
        for expected in ("你", "好", "你好", "世", "界", "世界", "hello123", "测", "试", "测试"):
            self.assertIn(expected, tokens)
        for banned in ("，", "。", "！", "😀"):
            self.assertNotIn(banned, tokens)
        self.assertEqual(wb.tokenize("，。！？😀🎉"), "")
        self.assertEqual(wb.tokenize(""), "")

        mixed = wb.tokenize("第12章 ABC_9").split()
        self.assertIn("12", mixed)
        self.assertIn("abc_9", mixed)
        self.assertIn("第", mixed)
        self.assertIn("章", mixed)

    @unittest.skipUnless(HAS_FTS5, "SQLite build lacks ENABLE_FTS5")
    def test_two_character_name_recall_across_500_paragraphs(self) -> None:
        self.initialize()
        expected_keys = set()
        for index in range(500):
            key = f"正文:{index + 1}"
            expected_keys.add(key)
            wb.index_document(
                self.root,
                doc_key=key,
                kind="chapter",
                chapter_id=index + 1,
                title=f"第{index + 1}章",
                content=f"第{index + 1}段：林溪在档案馆遇见老周。",
            )
        hits = wb.search(self.root, "林溪", limit=1000)
        self.assertEqual(len(hits), 500)
        self.assertEqual({hit["doc_key"] for hit in hits}, expected_keys)
        for hit in hits[:5]:
            self.assertIn("林溪", hit["snippet"])

    @unittest.skipUnless(HAS_FTS5, "SQLite build lacks ENABLE_FTS5")
    def test_name_split_by_chinese_punctuation_is_still_recalled(self) -> None:
        self.initialize()
        wb.index_document(
            self.root, doc_key="chapter:punctuated", kind="chapter", chapter_id=9,
            title="标点", content="林，溪走进档案馆。",
        )
        hits = wb.search(self.root, "林溪")
        self.assertEqual([hit["doc_key"] for hit in hits], ["chapter:punctuated"])

    @unittest.skipUnless(HAS_FTS5, "SQLite build lacks ENABLE_FTS5")
    def test_empty_punctuation_and_emoji_queries_return_empty(self) -> None:
        self.initialize()
        for query in ("", "   ", "\n\t", "，。！？", "😀🎉", '" OR *'):
            with self.subTest(query=query):
                self.assertEqual(wb.search(self.root, query), [])

    @unittest.skipUnless(HAS_FTS5, "SQLite build lacks ENABLE_FTS5")
    def test_reindex_updates_snippet_and_drop_removes_document(self) -> None:
        self.initialize()
        key = "chapter:1"
        wb.index_document(
            self.root, doc_key=key, kind="chapter", chapter_id=1,
            title="旧题", content="旧稿：林溪在档案馆。",
        )
        hits = wb.search(self.root, "林溪")
        self.assertEqual(len(hits), 1)
        self.assertIn("旧稿", hits[0]["snippet"])

        wb.index_document(
            self.root, doc_key=key, kind="chapter", chapter_id=1,
            title="新题", content="新稿：林溪离开档案馆。",
        )
        hits = wb.search(self.root, "林溪")
        self.assertEqual(len(hits), 1)
        self.assertIn("新稿", hits[0]["snippet"])
        self.assertNotIn("旧稿", hits[0]["snippet"])
        with wb.connect(self.root) as db:
            self.assertEqual(
                db.execute("SELECT content FROM search_docs WHERE doc_key=?", (key,)).fetchone()[0],
                "新稿：林溪离开档案馆。",
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM search_fts").fetchone()[0], 1
            )

        wb.drop_document(self.root, key)
        self.assertEqual(wb.search(self.root, "林溪"), [])
        with wb.connect(self.root) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM search_docs WHERE doc_key=?", (key,)).fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM search_fts").fetchone()[0], 0
            )


class SchemaAndContractTest(_WorkbenchBase):
    def test_initialize_is_idempotent_and_preserves_rows(self) -> None:
        self.initialize()
        uid = wb.chapter_uid(self.root, 1)
        draft = wb.save_draft(
            self.root, 1, title="保留", content="数据",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="save", op_id="op-keep",
            params={"x": 1},
        )
        before = wb.table_counts(self.root)
        with wb.connect(self.root) as db:
            tables_before = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

        self.initialize()
        self.initialize()

        self.assertEqual(wb.table_counts(self.root), before)
        self.assertEqual(wb.chapter_uid(self.root, 1), uid)
        kept = wb.get_draft(self.root, 1)
        self.assertEqual(kept["content"], "数据")
        self.assertEqual(kept["draft_id"], draft["draft_id"])
        self.assertEqual(
            wb.idempotency_begin(
                self.root, actor="author", project_id="p", action="save", op_id="op-keep",
                params={"x": 1},
            )["status"],
            "in_progress",
        )
        with wb.connect(self.root) as db:
            tables_after = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertEqual(tables_after, tables_before)
            self.assertEqual(
                db.execute("SELECT value FROM workbench_meta WHERE key='schema_version'").fetchone()[0],
                str(wb.SCHEMA_VERSION),
            )

    def test_table_counts_works_on_an_empty_database_file(self) -> None:
        path = wb.db_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        counts = wb.table_counts(self.root)
        self.assertEqual(
            counts,
            {
                "chapter_meta": 0,
                "chapter_drafts": 0,
                "annotations": 0,
                "annotation_hunks": 0,
                "patch_ledger": 0,
                "idempotency_keys": 0,
                "world_facts": 0,
                "search_docs": 0,
            },
        )
        with wb.connect(self.root) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_checkpoint_truncate_shrinks_wal_after_writes(self) -> None:
        self.initialize()
        with wb.connect(self.root) as keepalive:
            keepalive.execute("SELECT 1").fetchone()
            wb.save_draft(
                self.root, 1, title="大章", content="汉" * 300000,
                expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
            )
            before = _wal_bytes(self.root)
            self.assertGreater(before, 0)
            wb.checkpoint(self.root, truncate=True)
            after = _wal_bytes(self.root)
            self.assertEqual(after, 0)
        with wb.connect(self.root) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_no_v075_tables_and_no_alter_table_source(self) -> None:
        self.initialize()
        with wb.connect(self.root) as db:
            names = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        self.assertEqual(names & LEGACY_TABLES, set())
        source = Path(wb.__file__).read_text(encoding="utf-8").lower()
        for legacy in LEGACY_TABLES:
            self.assertNotRegex(
                source,
                rf"alter\s+table\s+(?:if\s+exists\s+)?[\"']?{legacy}\b",
                f"workbench_db.py must not ALTER legacy table {legacy}",
            )

    def test_chapter_uid_is_stable_and_ids_match_contract_shapes(self) -> None:
        self.initialize()
        uid = wb.chapter_uid(self.root, 3)
        self.assertRegex(uid, r"^chuid_[0-9a-f]{8}$")
        self.assertEqual(uid, wb.chapter_uid(self.root, 3))
        draft = wb.save_draft(
            self.root, 3, title="章", content="内容",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        self.assertRegex(draft["draft_id"], r"^drf_[0-9a-f]{8}$")
        self.assertEqual(uid, wb.chapter_uid(self.root, 3))
        wb.clear_draft_if_matches(
            self.root, 3, draft_id=draft["draft_id"],
            draft_epoch=int(draft["draft_epoch"]),
            draft_revision=int(draft["draft_revision"]),
        )
        self.assertEqual(uid, wb.chapter_uid(self.root, 3))
        rebuilt = wb.save_draft(
            self.root, 3, title="章", content="重建",
            expected_draft_id=None,
            expected_draft_epoch=int(wb.ensure_chapter_meta(self.root, 3)["draft_epoch"]),
            expected_draft_revision=0,
        )
        self.assertNotEqual(rebuilt["draft_id"], draft["draft_id"])
        self.assertEqual(uid, wb.chapter_uid(self.root, 3))
        self.assertEqual(len(wb.list_chapter_meta(self.root)), 1)

    def test_timestamps_are_utc(self) -> None:
        self.initialize()
        stamp = wb.now_iso()
        parsed = datetime.fromisoformat(stamp)
        self.assertEqual(parsed.utcoffset(), timedelta(0))
        self.assertTrue(stamp.endswith("+00:00"))

        wb.save_draft(
            self.root, 1, title="时区", content="UTC",
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
        )
        wb.idempotency_begin(
            self.root, actor="author", project_id="p", action="save", op_id="op-time",
            params={"x": 1}, ttl_hours=24,
        )
        checks = {
            "chapter_meta": ("created_at", "updated_at"),
            "chapter_drafts": ("updated_at",),
            "drafts_history": ("created_at",),
            "idempotency_keys": ("created_at", "expires_at"),
        }
        with wb.connect(self.root) as db:
            for table, columns in checks.items():
                row = db.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
                self.assertIsNotNone(row, table)
                for column in columns:
                    value = row[column]
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.endswith("+00:00"), f"{table}.{column}={value!r}")
                    self.assertEqual(datetime.fromisoformat(value).utcoffset(), timedelta(0))

    def test_unicode_one_megabyte_round_trip_and_invalid_chapter(self) -> None:
        self.initialize()
        title = "第1章 😀 表情标题"
        content = "汉" * 349525 + "😀"
        self.assertGreaterEqual(len(content.encode("utf-8")), 1024 * 1024)
        cursor = {"start": 1, "end": 2, "scroll_top": 3.5, "note": "光标😀"}
        draft = wb.save_draft(
            self.root, 1, title=title, content=content,
            expected_draft_id=None, expected_draft_epoch=0, expected_draft_revision=0,
            cursor=cursor,
        )
        loaded = wb.get_draft(self.root, 1)
        self.assertEqual(loaded["title"], title)
        self.assertEqual(loaded["content"], content)
        self.assertEqual(loaded["cursor"], cursor)
        self.assertEqual(
            self.history()[0]["content_sha256"],
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(draft["draft_id"], loaded["draft_id"])

        for bad in (0, -1):
            with self.subTest(chapter=bad):
                with self.assertRaises(ValueError):
                    wb.save_draft(
                        self.root, bad, title="", content="",
                        expected_draft_id=None, expected_draft_epoch=0,
                        expected_draft_revision=0,
                    )

    def test_partial_old_database_missing_table_is_repaired(self) -> None:
        """KNOWN DEFECT P1: _ensure only checks chapter_drafts.

        An interrupted upgrade (or an older DB missing a later table) keeps the
        chapter_drafts sentinel, so initialize() is never re-run and every
        function touching the missing table raises "no such table".
        """
        self.initialize()
        with wb.connect(self.root) as db:
            db.execute("DROP TABLE annotations")
        counts = wb.table_counts(self.root)
        self.assertEqual(counts["annotations"], 0)

    def test_maintenance_helpers_initialize_a_fresh_project(self) -> None:
        """KNOWN DEFECT P2: clear/delete/gc/bump do not call _ensure.

        On a project where no draft has ever been saved these public helpers
        raise "no such table" instead of returning a graceful no-op.
        """
        cleared = wb.clear_draft_if_matches(
            self.root, 1, draft_id="drf_00000000", draft_epoch=0, draft_revision=0
        )
        self.assertFalse(cleared["cleared"])
        self.assertFalse(wb.delete_draft(self.root, 1)["deleted"])
        self.assertEqual(wb.idempotency_gc(self.root), 0)
        self.assertEqual(wb.bump_commit_generation(self.root), 1)

    def test_concurrent_initializer_retries_a_transient_wal_lock(self) -> None:
        """KNOWN DEFECT P1: connect() does not retry PRAGMA journal_mode=WAL.

        Eight processes calling initialize() on a fresh project reproduced
        "database is locked" at workbench_db.py:81 (2 of 10 runs).  This test
        makes the lock deterministic by holding a read transaction while a
        short-timeout initializer runs, then releases it after 0.35 s.
        """
        path = wb.db_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        holder = sqlite3.connect(
            str(path), timeout=1.0, isolation_level=None, check_same_thread=False
        )
        holder.execute("PRAGMA journal_mode=DELETE")
        holder.execute("CREATE TABLE keep(x)")
        holder.execute("INSERT INTO keep VALUES(1)")
        holder.execute("BEGIN")
        holder.execute("SELECT * FROM keep").fetchone()

        released = threading.Event()

        def release() -> None:
            try:
                holder.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            finally:
                try:
                    holder.close()
                except sqlite3.Error:
                    pass
                released.set()

        timer = threading.Timer(0.35, release)
        timer.start()
        real_connect = sqlite3.connect

        def short_connect(*args, **kwargs):
            kwargs["timeout"] = 0.2
            return real_connect(*args, **kwargs)

        try:
            with mock.patch.object(wb.sqlite3, "connect", side_effect=short_connect):
                wb.initialize(self.root)
        finally:
            timer.cancel()
            timer.join(timeout=5)
            if not released.is_set():
                release()


class MultiProcessTest(_WorkbenchBase):
    def _run_workers(self, count: int, saves: int) -> list:
        methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context("fork" if "fork" in methods else None)
        queue = context.Queue()
        processes = [
            context.Process(target=_mp_worker, args=(str(self.root), worker_id, saves, queue))
            for worker_id in range(count)
        ]
        self.addCleanup(queue.close)

        def cleanup() -> None:
            for process in processes:
                if process.is_alive():
                    process.terminate()
            for process in processes:
                process.join(timeout=5)

        self.addCleanup(cleanup)
        for process in processes:
            process.start()
        results = []
        for _ in processes:
            try:
                results.append(queue.get(timeout=30))
            except Empty:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                self.fail("multiprocess worker did not report within 30 s")
        for process in processes:
            process.join(timeout=60)
        self.assertFalse(any(process.is_alive() for process in processes))
        self.assertEqual([process.exitcode for process in processes], [0] * count)
        return results

    def test_three_processes_twenty_saves_and_idempotency(self) -> None:
        self.initialize()
        results = self._run_workers(3, 20)
        errors = [result for result in results if result[0] != "ok"]
        self.assertEqual(errors, [])
        successes = [item for result in results for item in result[2]]
        self.assertEqual(len(successes), 60)
        revisions = sorted(item[0] for item in successes)
        self.assertEqual(revisions, list(range(1, 61)))
        self.assertEqual({item[2] for item in successes}, {1})
        body_by_revision = {item[0]: item[1] for item in successes}
        expected_hashes = {
            revision: hashlib.sha256(body.encode("utf-8")).hexdigest()
            for revision, body in body_by_revision.items()
        }

        with wb.connect(self.root) as db:
            self.assertEqual(
                [row[0] for row in db.execute("PRAGMA integrity_check")], ["ok"]
            )
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            rows = db.execute(
                "SELECT draft_revision, content_sha256 FROM drafts_history "
                "WHERE chapter_id=1 ORDER BY draft_revision"
            ).fetchall()
            self.assertEqual([row[0] for row in rows], list(range(1, 61)))
            for revision, digest in rows:
                self.assertEqual(digest, expected_hashes[revision])
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM chapter_drafts").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0], 60
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM idempotency_keys WHERE state='completed'"
                ).fetchone()[0],
                60,
            )
            self.assertEqual(
                db.execute("SELECT draft_epoch FROM chapter_meta WHERE chapter_id=1").fetchone()[0],
                1,
            )

        final = wb.get_draft(self.root, 1)
        self.assertEqual(int(final["draft_revision"]), 60)
        self.assertEqual(final["content"], body_by_revision[60])


if __name__ == "__main__":
    unittest.main()
