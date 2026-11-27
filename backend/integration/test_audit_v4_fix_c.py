"""第四轮 C 域回归：schema 约束、GC/retention、hold 状态机、显式 fact_id 去重。"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from integration import chapter_editor as ce
from integration import concurrent_engine as ce_engine
from integration import maintenance
from integration import quality
from integration import workbench_db as wb
from integration import world_state as ws


def project(folder) -> Path:
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


class SchemaConstraintTest(unittest.TestCase):
    """C4-03：缺主键的旧表必须被识别并重建，而不是只比列名。"""

    def test_missing_primary_key_is_reported_and_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            wb.initialize(book)
            with wb.write_tx(book) as db:
                db.execute("ALTER TABLE task_pauses RENAME TO task_pauses_old")
                db.execute("CREATE TABLE task_pauses(scope TEXT, reason TEXT, created_at TEXT NOT NULL)")
                db.execute("INSERT INTO task_pauses VALUES('global','a','2026-01-01')")
                db.execute("INSERT INTO task_pauses VALUES('global','b','2026-01-01')")
                db.execute("DROP TABLE task_pauses_old")
            report = maintenance.schema_report(book)
            self.assertFalse(report["current"], report)
            self.assertIn("task_pauses", report["constraint_mismatches"])
            healed = maintenance.ensure_schema(book)
            self.assertTrue(healed["current"], healed)
            with wb.connect(book) as db:
                pk = [row[1] for row in db.execute("PRAGMA table_info(task_pauses)") if row[5]]
                rows = db.execute("SELECT COUNT(*) FROM task_pauses").fetchone()[0]
            self.assertEqual(pk, ["scope"])
            self.assertEqual(rows, 1)


class GcAndRetentionTest(unittest.TestCase):
    """C3-05/C3-25：锁不落在项目内；GC 同时执行 DB 保留策略。"""

    def test_lock_files_stay_outside_the_project(self):
        from integration import lock_manager
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            with lock_manager.hold(book, "diagnostics", "diagnostics"):
                path = lock_manager.lock_path(book, "diagnostics", "diagnostics")
                self.assertFalse(str(path).startswith(str(book.resolve())))
                self.assertTrue(path.is_file())
            self.assertFalse((book / ".webnovel" / "locks").exists())

    def test_gc_applies_bounded_db_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            wb.initialize(book)
            old = "2020-01-01T00:00:00Z"
            with wb.write_tx(book) as db:
                for index in range(500):
                    db.execute("INSERT INTO task_events(task_id, kind, detail_json, created_at) "
                               "VALUES(?,?,?,?)", ("t", "x", "{}", old))
                for index in range(50):
                    db.execute("INSERT INTO drafts_history(chapter_id, draft_id, draft_epoch, "
                               "draft_revision, content_sha256, created_at) VALUES(1,?,?,?,?,?)",
                               (f"d{index}", index, index, "0" * 64, old))
                for index in range(10):
                    db.execute("INSERT INTO context_manifests(chapter_id, operation_id, "
                               "manifest_json, created_at) VALUES(1,?,?,?)",
                               (f"op{index}", "{}", old))
                db.execute("INSERT INTO idempotency_keys(actor, project_id, action, op_id, "
                           "params_hash, state, created_at, expires_at) VALUES(?,?,?,?,?,?,?,?)",
                           ("a", "p", "act", "op", "h", "completed", old, old))
            result = maintenance.collect_garbage(book, dry_run=False, min_age_seconds=0)
            self.assertIn("db_retention", result)
            with wb.connect(book) as db:
                counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                          for table in ("task_events", "drafts_history", "context_manifests",
                                        "idempotency_keys")}
            self.assertEqual(counts["task_events"], 0)
            self.assertEqual(counts["drafts_history"], 20)
            self.assertEqual(counts["context_manifests"], 5)
            self.assertEqual(counts["idempotency_keys"], 0)


class HoldStateMachineTest(unittest.TestCase):
    """C3-13：fail/recover 不得清掉改令标志，recovery_required 不得被洗白。"""

    def test_continue_fallback_does_not_block_running_task(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce_engine.submit(book, {}, priority="P1")
            ce_engine.claim(book, "w")
            held = ce_engine.hold_for_amendment(book, "amd-c", [task["task_id"]],
                                                fallback="continue")
            self.assertEqual(held["continued_task_ids"], [task["task_id"]])
            self.assertTrue(ce_engine.begin_commit(book, task["task_id"], "w")["committing"])
            self.assertEqual(ce_engine.complete(book, task["task_id"], owner="w")["state"],
                             "completed")

    def test_failed_task_keeps_amendment_hold(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce_engine.submit(book, {}, priority="P1")
            ce_engine.claim(book, "w")
            ce_engine.hold_for_amendment(book, "amd_A", [task["task_id"]])
            failed = ce_engine.fail(book, task["task_id"], owner="w", error="boom")
            self.assertEqual(failed["state"], "pending")
            self.assertEqual(failed["hold_amendment_id"], "amd_A")
            self.assertIsNone(ce_engine.claim(book, "w"))
            ce_engine.release_amendment(book, "amd_A")
            self.assertEqual(ce_engine.claim(book, "w")["task_id"], task["task_id"])

    def test_recovery_required_is_not_frozen_or_released(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce_engine.submit(book, {}, priority="P1")
            ce_engine.claim(book, "w")
            ce_engine.begin_commit(book, task["task_id"], "w")
            with wb.write_tx(book) as db:
                db.execute("UPDATE task_queue SET lease_expires=? WHERE task_id=?",
                           (time.time() - 10, task["task_id"]))
            recovered = ce_engine.recover(book)
            self.assertEqual(recovered[0]["state"], "recovery_required")
            held = ce_engine.hold_for_amendment(book, "amd-1", [task["task_id"]])
            self.assertEqual(held["held_task_ids"], [])
            ce_engine.release_amendment(book, "amd-1")
            item = ce_engine.get(book, task["task_id"])
            self.assertEqual(item["state"], "recovery_required")
            self.assertTrue(item["committing"])
            self.assertIsNone(ce_engine.claim(book, "w"))


class ExplicitFactIdTest(unittest.TestCase):
    """C4-01：显式 fact_id 不能绕开逻辑键去重。"""

    def test_two_explicit_ids_for_same_logical_fact_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            base = {"domain": "character", "assertion_type": "fact", "entity_id": "ent-1",
                    "subject": "测绘员", "predicate": "年龄", "object": "三十",
                    "authority_level": "ai_inferred", "confidence": 0.9,
                    "valid_from_chapter": 1, "status": "active"}
            first = ws.upsert_fact(book, {**base, "fact_id": "fixed-A"})
            second = ws.upsert_fact(book, {**base, "fact_id": "fixed-B"})
            self.assertEqual(second["fact"]["fact_id"], "fixed-A")
            with wb.connect(book) as db:
                rows = db.execute("SELECT fact_id FROM world_facts").fetchall()
            self.assertEqual([row[0] for row in rows], ["fixed-A"])


class ConfirmAuthorityTest(unittest.TestCase):
    """C3-21：确认不得降级；非 fact 的确认不改写事实窗口。"""

    def test_confirm_rejects_lower_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            base = {"domain": "character", "assertion_type": "fact", "entity_id": "ent-1",
                    "subject": "甲", "predicate": "身份", "object": "学生",
                    "authority_level": "draft_prose", "confidence": 0.8,
                    "status": "pending_confirm", "valid_from_chapter": 1}
            saved = ws.upsert_fact(book, {**base, "fact_id": "f1"})
            with self.assertRaises(ws.WorldStateError) as caught:
                ws.confirm_fact(book, saved["fact"]["fact_id"], authority_level="ai_inferred")
            self.assertEqual(caught.exception.code, "authority_not_raised")
            confirmed = ws.confirm_fact(book, saved["fact"]["fact_id"])
            self.assertEqual(confirmed["status"], "active")
            self.assertEqual(confirmed["authority_level"], "confirmed_prose")

    def test_confirming_rumor_does_not_close_fact_window(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            fact = ws.upsert_fact(book, {
                "fact_id": "old-fact", "domain": "character", "assertion_type": "fact",
                "entity_id": "ent-1", "subject": "甲", "predicate": "身份", "object": "学生",
                "authority_level": "draft_prose", "confidence": 0.9, "status": "active",
                "valid_from_chapter": 1})
            rumor = ws.upsert_fact(book, {
                "fact_id": "rumor-1", "domain": "character", "assertion_type": "rumor",
                "entity_id": "ent-1", "subject": "甲", "predicate": "身份", "object": "教师",
                "authority_level": "ai_inferred", "confidence": 0.9,
                "status": "pending_confirm", "valid_from_chapter": 2})
            ws.confirm_fact(book, rumor["fact"]["fact_id"])
            with wb.connect(book) as db:
                row = db.execute("SELECT valid_until_chapter FROM world_facts WHERE fact_id='old-fact'"
                                 ).fetchone()
            self.assertIsNone(row[0])
            self.assertEqual(fact["fact"]["fact_id"], "old-fact")


class QualityAggregationTest(unittest.TestCase):
    """C3-27：分页只影响 chapters，averages/reviewed 是全书聚合。"""

    def test_page_does_not_change_full_book_average(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            for chapter in (1, 2, 3):
                ce.new_chapter(book, {"chapter": chapter, "title": f"第{chapter}章",
                                      "content": f"第{chapter}章正文。\n" * 8,
                                      "op_id": f"q-{chapter}"})
            judgments = [{"scores": {dim: 90.0 for dim in quality.DIMENSIONS}}]
            quality.review(book, 1, judgments=judgments, reviewer="auto")
            quality.review(book, 2, judgments=judgments, reviewer="auto")
            full = quality.dashboard(book)
            page = quality.dashboard(book, limit=1)
            self.assertEqual(full["reviewed"], 2)
            self.assertEqual(page["reviewed"], 2)
            self.assertEqual(full["averages"], page["averages"])
            self.assertAlmostEqual(page["averages"]["plot"], 90.0)


class FailedBlockerTest(unittest.TestCase):
    """C4-04：failed 上游不能静默永久阻塞，新任务在提交时被明确拒绝。"""

    def test_submit_against_failed_blocker_is_409(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            upstream = ce_engine.submit(book, {}, priority="P1")
            ce_engine.claim(book, "w")
            failed = ce_engine.fail(book, upstream["task_id"], owner="w",
                                    error="boom", max_attempts=1)
            self.assertEqual(failed["state"], "failed")
            with self.assertRaises(ce_engine.SchedulerError) as caught:
                ce_engine.submit(book, {}, priority="P2", blocked_by=[upstream["task_id"]])
            self.assertEqual(caught.exception.code, "blocked_by_failed")
            self.assertEqual(caught.exception.detail.get("action"), "retry_blocker")


class CorruptDatabaseTest(unittest.TestCase):
    """C4-05：损坏 DB 必须报 503，而不是伪装成空数据。"""

    def test_read_paths_report_db_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.new_chapter(book, {"chapter": 1, "title": "开端", "content": "正文。\n",
                                  "op_id": "corrupt-1"})
            wb.db_path(book).write_bytes(b"not a sqlite database")
            with self.assertRaises(ws.WorldStateError) as caught:
                ws.state(book, chapter=1)
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(caught.exception.code, "db_unavailable")
            with self.assertRaises(quality.QualityError) as caught:
                quality.dashboard(book)
            self.assertEqual(caught.exception.code, "db_unavailable")
            with self.assertRaises(ce_engine.SchedulerError) as caught:
                ce_engine.list_tasks(book)
            self.assertEqual(caught.exception.code, "db_unavailable")


if __name__ == "__main__":
    unittest.main()
