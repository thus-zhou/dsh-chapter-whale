"""五态预算、指令护栏与 v0.7.5 旧表零破坏。"""
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from integration import costs


LIMITS = {"requests_per_day": 3, "request_tokens": None, "chapter_tokens": None,
          "chapter_cost_cny": None, "project_tokens": None, "project_cost_cny": None,
          "unknown_reserve_cny": "1"}


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "costs.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_request_budget_columns_unchanged(self):
        costs.connection(self.db).close()
        db = sqlite3.connect(self.db)
        try:
            columns = [row[1] for row in db.execute("PRAGMA table_info(request_budget)")]
            self.assertEqual(columns, ["id", "created_at", "project", "chapter", "stage", "day",
                                       "state", "tokens", "cost_cny", "unknown_cost", "operation"])
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("directive_budget_links", tables)
            # 旧版无列名 INSERT 仍然可用
            db.execute("INSERT INTO request_budget VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       ("legacy", "2026-11-26T00:00:00+00:00", "/tmp/p", 1, "draft",
                        "2026-11-26", "settled", 0, "0", 0, ""))
            db.commit()
        finally:
            db.close()

    def test_guard_forces_reservation_without_global_caps(self):
        identity = costs.reserve_request(self.db, "/tmp/book", 1, "draft",
                                         operation="op-1", directive_id="dir_1",
                                         guard={"max_calls": 2})
        self.assertTrue(identity)
        costs.reserve_request(self.db, "/tmp/book", 1, "draft", operation="op-2",
                              directive_id="dir_1", guard={"max_calls": 2})
        with self.assertRaises(costs.BudgetExceeded):
            costs.reserve_request(self.db, "/tmp/book", 1, "draft", operation="op-3",
                                  directive_id="dir_1", guard={"max_calls": 2})
        usage = costs.directive_usage(self.db, "dir_1")
        self.assertEqual(usage["calls"], 2)
        self.assertEqual(usage["states"]["reserved"], 2)

    def test_max_chapters_counts_distinct_chapters(self):
        costs.reserve_request(self.db, "/tmp/book", 1, "draft", operation="a",
                              directive_id="dir_2", guard={"max_chapters": 2})
        costs.reserve_request(self.db, "/tmp/book", 1, "draft", operation="b",
                              directive_id="dir_2", guard={"max_chapters": 2})
        costs.reserve_request(self.db, "/tmp/book", 2, "draft", operation="c",
                              directive_id="dir_2", guard={"max_chapters": 2})
        with self.assertRaises(costs.BudgetExceeded):
            costs.reserve_request(self.db, "/tmp/book", 3, "draft", operation="d",
                                  directive_id="dir_2", guard={"max_chapters": 2})

    def test_concurrent_last_balance_only_one_wins(self):
        guard = {"budget_cap_cny": "1.0"}
        barrier = threading.Barrier(2)
        results = []

        def worker(index):
            barrier.wait()
            try:
                identity = costs.reserve_request(self.db, "/tmp/book", 1, "polish",
                                                 cost_cny="0.6", operation=f"op-{index}",
                                                 directive_id="dir_3", guard=guard)
                results.append(("ok", identity))
            except costs.BudgetExceeded:
                results.append(("blocked", None))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for item in threads:
            item.start()
        for item in threads:
            item.join()
        self.assertEqual(sorted(result[0] for result in results), ["blocked", "ok"])
        self.assertEqual(costs.directive_usage(self.db, "dir_3")["calls"], 1)
        self.assertEqual(costs.ledger_gaps(self.db), 0)

    def test_release_zeros_tokens_and_cost(self):
        identity = costs.reserve_request(self.db, "/tmp/book", 1, "draft",
                                         cost_cny="1.5", tokens=10, operation="op-r",
                                         directive_id="dir_4", guard={"max_calls": 5})
        self.assertTrue(costs.release_request(self.db, identity))
        db = sqlite3.connect(self.db)
        try:
            state, tokens, amount = db.execute(
                "SELECT state, tokens, cost_cny FROM request_budget WHERE id=?", (identity,)).fetchone()
        finally:
            db.close()
        self.assertEqual(state, "released")
        self.assertEqual(tokens, 0)
        self.assertEqual(amount, "0")
        usage = costs.directive_usage(self.db, "dir_4")
        self.assertEqual(usage["calls"], 0)
        self.assertEqual(usage["states"]["released"], 1)

    def test_budget_status_excludes_released_and_exposes_unknown_charge(self):
        reserved = costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="2",
                                         operation="op-1", directive_id="dir_5",
                                         guard={"max_calls": 5})
        released = costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="9",
                                         operation="op-2", directive_id="dir_5",
                                         guard={"max_calls": 5})
        costs.release_request(self.db, released)
        costs.mark_dispatched(self.db, reserved)
        status = costs.budget_status(self.db)
        self.assertEqual(status["released"], 1)
        self.assertEqual(status["dispatched"], 1)
        self.assertEqual(status["cost_project_cny"], "2")
        self.assertEqual(costs.directive_usage(self.db, "dir_5")["calls"], 1)
        costs.settle_request(self.db, reserved, state="unknown_charge")
        status = costs.budget_status(self.db)
        self.assertEqual(status["unknown_charge_requests"], 1)

    def test_directive_guard_zero_cost_unknown_still_counts_calls(self):
        guard = {"max_calls": 1}
        identity = costs.reserve_request(self.db, "/tmp/book", 1, "draft",
                                         operation="op-u", directive_id="dir_6", guard=guard)
        costs.settle_request(self.db, identity, state="settled")
        with self.assertRaises(costs.BudgetExceeded):
            costs.reserve_request(self.db, "/tmp/book", 1, "draft", operation="op-u2",
                                  directive_id="dir_6", guard=guard)


    def test_failed_request_releases_daily_capacity(self):
        first = costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="1", limits=LIMITS)
        costs.settle_request(self.db, first, state="failed")
        second = costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="1", limits=LIMITS)
        third = costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="1", limits=LIMITS)
        self.assertTrue(second and third)
        db = sqlite3.connect(self.db)
        try:
            states = [row[0] for row in db.execute(
                "SELECT state FROM request_budget ORDER BY created_at")]
        finally:
            db.close()
        self.assertEqual(states[0], "released")
        # Two active reservations + the released row fit the 3/day cap; the
        # fourth active reservation fills it and the fifth is blocked.
        costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="1", limits=LIMITS)
        with self.assertRaises(costs.BudgetExceeded):
            costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="1", limits=LIMITS)

    def test_interrupted_request_becomes_unknown_charge(self):
        identity = costs.reserve_request(self.db, "/tmp/book", 1, "draft", cost_cny="1", limits=LIMITS)
        costs.settle_request(self.db, identity, state="cancelled", tokens=5)
        db = sqlite3.connect(self.db)
        try:
            state, tokens, amount = db.execute(
                "SELECT state, tokens, cost_cny FROM request_budget WHERE id=?", (identity,)).fetchone()
        finally:
            db.close()
        self.assertEqual((state, tokens, amount), ("unknown_charge", 5, "1"))

    def test_count_only_guard_does_not_charge_unknown_reserve(self):
        identity = costs.reserve_request(self.db, "/tmp/book", 1, "draft",
                                         directive_id="dir_count", guard={"budget_cap_cny": "2"},
                                         count_only=True, limits=LIMITS)
        db = sqlite3.connect(self.db)
        try:
            amount, unknown = db.execute(
                "SELECT cost_cny, unknown_cost FROM request_budget WHERE id=?", (identity,)).fetchone()
        finally:
            db.close()
        self.assertEqual((amount, unknown), ("0", 0))
        self.assertEqual(costs.directive_usage(self.db, "dir_count")["cost_cny"], "0")

    def test_attempt_finish_settles_failed_and_interrupted_without_gap(self):
        with mock.patch.object(costs, "budget_limits", return_value=LIMITS):
            for expected in ("released", "unknown_charge"):
                with costs.scope(db=str(self.db), project="/tmp/book", chapter=1, stage="draft"):
                    meter = costs.Attempt("https://api.example.com/v1", "m1",
                                          {"messages": [{"content": "x"}]})
                    self.assertTrue(meter.reservation)
                    if expected == "unknown_charge":
                        meter.output("半截输出")
                    meter.finish()
                db = sqlite3.connect(self.db)
                try:
                    row = db.execute(
                        "SELECT state FROM request_budget WHERE id=?", (meter.reservation,)).fetchone()
                finally:
                    db.close()
                self.assertEqual(row[0], expected)
        self.assertEqual(costs.ledger_gaps(self.db), 0)

    def test_old_gap_files_do_not_mark_report_incomplete_forever(self):
        costs.connection(self.db).close()
        gap_dir = Path(str(self.db) + ".gaps")
        gap_dir.mkdir()
        old = gap_dir / "old.json"
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (time.time() - 48 * 3600, time.time() - 48 * 3600))
        report = costs.report(self.db)
        self.assertEqual(report["summary"]["ledger_gaps"], 1)
        self.assertEqual(report["summary"]["gaps_recent"], 0)
        self.assertTrue(report["summary"]["complete"])


if __name__ == "__main__":
    unittest.main()
