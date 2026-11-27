"""C 域第三轮审计回归（P2）：schema 自愈、只读读路径、世界窗口/去重/权威、
租约与 owner、submit 契约、blocked_by 校验与卡片局部更新。

对应 C3-03 / C3-04 / C3-07 / C3-08 / C3-09 / C3-10 / C3-11 / C3-12 / C3-14 /
C3-15 / C3-16。全部断言基于真实 SQLite 与真实文件系统，不 mock 业务逻辑。
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from integration import concurrent_engine as ce
from integration import maintenance
from integration import quality
from integration import workbench_db as wb
from integration import world_state as ws


def project(folder) -> Path:
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


def legacy_chapter(book: Path, chapter: int = 1, text: str = "第一段。\n“你来了。”\n") -> Path:
    path = book / "正文" / f"第{chapter}章-旧稿.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def insert_task(book: Path, task_id: str, *, state: str = "pending",
                blocked_by=(), priority: str = "P1") -> None:
    wb.initialize(book)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with wb.write_tx(book) as db:
        db.execute(
            "INSERT INTO task_queue(task_id, chapter_id, priority, state, parent_task_id, "
            "blocked_by_json, hold_amendment_id, amendment_fallback, committing, attempts, "
            "payload_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,0,0,?,?,?)",
            (task_id, None, priority, state, None, json.dumps(list(blocked_by)),
             None, "wait", "{}", stamp, stamp))


class SchemaSelfHealTest(unittest.TestCase):
    """C3-03：缺表/缺列必须被检查、报告并从 SCHEMA 修复。"""

    def test_missing_tables_and_columns_are_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            wb.initialize(book)
            self.assertTrue(maintenance.schema_report(book)["current"])
            with wb.write_tx(book) as db:
                db.execute("DROP TABLE task_pauses")
                db.execute("DROP TABLE context_manifests")
                db.execute("DROP TABLE search_fts")
                db.execute("ALTER TABLE quality_reviews DROP COLUMN chapter_uid")
            drift = maintenance.schema_report(book)
            self.assertFalse(drift["current"])
            self.assertIn("task_pauses", drift["missing_tables"])
            self.assertIn("search_fts", drift["missing_tables"])
            self.assertIn("chapter_uid", drift["missing_columns"]["quality_reviews"])

            healed = maintenance.ensure_schema(book)
            self.assertTrue(healed["current"], healed)
            self.assertTrue(healed.get("repaired"))
            again = maintenance.schema_report(book)
            self.assertTrue(again["current"])
            self.assertEqual(again["missing_tables"], [])
            self.assertEqual(again["missing_columns"], {})

            # 修复后原功能恢复：暂停可用、质量体检可写、FTS 重建可用。
            ce.pause(book, "global", "测试")
            self.assertEqual(ce.paused_scopes(book)[0]["scope"], "global")
            legacy_chapter(book)
            self.assertEqual(quality.review(book, 1)["status"], "reviewed")
            healed_search = maintenance.self_heal(book, "rebuild_search")
            self.assertEqual(healed_search["status"], "healed")

    def test_health_reports_schema_drift_and_heals(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            wb.initialize(book)
            with wb.write_tx(book) as db:
                db.execute("DROP TABLE task_pauses")
            first = maintenance.health(book)
            codes = [item["code"] for item in first["issues"]]
            self.assertIn("schema_incomplete", codes)
            self.assertEqual(first["status"], "degraded")
            self.assertTrue(first["schema"]["current"], "本次请求内应已完成修复")
            second = maintenance.health(book)
            self.assertNotIn("schema_incomplete", [item["code"] for item in second["issues"]])
            self.assertEqual(second["status"], "ok")
            self.assertEqual(maintenance.self_heal(book, "rebuild_schema")["status"], "healed")

    def test_schema_report_never_creates_database(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            report = maintenance.schema_report(book)
            self.assertFalse(report["exists"])
            self.assertFalse(report["current"])
            self.assertFalse(maintenance.ensure_schema(book)["exists"])
            self.assertFalse(wb.db_path(book).exists())


class ReadOnlyPathTest(unittest.TestCase):
    """C3-04：只读项目的 GET 不建库，也不为任意章号写 chapter_meta。"""

    def test_dashboard_reads_do_not_create_database(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            legacy_chapter(book)
            state = ws.state(book, chapter=999)
            self.assertEqual(state["facts"], [])
            self.assertEqual(state["cards"], [])
            context = ws.build_context(book, 888, persist=False)
            self.assertEqual(context["manifest"]["chapter_uid"], "")
            board = quality.dashboard(book)
            self.assertEqual(board["total_chapters"], 1)
            snapshot = ce.snapshot(book)
            self.assertEqual(snapshot["tasks"], [])
            self.assertFalse(wb.db_path(book).exists())

    def test_world_state_does_not_create_ghost_chapter_meta(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ws.set_card(book, {"entity_id": "ent_1", "name": "林溪", "pinned": True})
            ws.state(book, chapter=999)
            with wb.connect(book) as db:
                rows = [row[0] for row in db.execute("SELECT chapter_id FROM chapter_meta")]
            self.assertNotIn(999, rows)


class FactWindowTest(unittest.TestCase):
    """C3-07 / C3-09 / C3-10：确认关窗、逻辑键含 assertion_type、权威分级。"""

    def test_confirm_closes_previous_window(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ws.upsert_fact(book, {"fact_id": "old", "entity_id": "e1", "domain": "character",
                                  "subject": "林溪", "predicate": "生死", "object": "存活",
                                  "valid_from_chapter": 1, "authority_level": "confirmed_prose",
                                  "status": "active"})
            ws.upsert_fact(book, {"fact_id": "new", "entity_id": "e1", "domain": "character",
                                  "subject": "林溪", "predicate": "生死", "object": "死亡",
                                  "valid_from_chapter": 5, "authority_level": "ai_inferred",
                                  "status": "pending_confirm"})
            self.assertIsNone(ws.get_fact(book, "old")["valid_until_chapter"])
            ws.confirm_fact(book, "new", authority_level="confirmed_prose")
            self.assertEqual(ws.get_fact(book, "old")["valid_until_chapter"], 4)
            at_five = ws.facts_for_chapter(book, 5)
            self.assertEqual([(row["fact_id"], row["object"]) for row in at_five],
                             [("new", "死亡")])
            self.assertEqual(ws.detect_conflicts(book, 5), [])

    def test_explicit_id_new_fact_closes_previous_window(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            base = {"entity_id": "e1", "domain": "character", "subject": "林溪",
                    "predicate": "身份", "authority_level": "confirmed_prose", "status": "active"}
            ws.upsert_fact(book, {**base, "fact_id": "old", "object": "测绘员",
                                  "valid_from_chapter": 1})
            ws.upsert_fact(book, {**base, "fact_id": "new", "object": "档案员",
                                  "valid_from_chapter": 5})
            self.assertEqual([row["fact_id"] for row in ws.facts_for_chapter(book, 5)
                              if row["predicate"] == "身份"], ["new"])

    def test_ai_inferred_cannot_close_draft_prose_window(self):
        """C3-10：draft_prose(3) 高于 ai_inferred(2)，旧 SQL 把两者当同级。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ws.upsert_fact(book, {"entity_id": "e1", "domain": "character", "subject": "林溪",
                                  "predicate": "身份", "object": "测绘员",
                                  "valid_from_chapter": 1, "authority_level": "draft_prose"})
            ws.upsert_fact(book, {"entity_id": "e1", "domain": "character", "subject": "林溪",
                                  "predicate": "身份", "object": "档案员",
                                  "valid_from_chapter": 5, "authority_level": "ai_inferred"})
            at_five = [row["object"] for row in ws.facts_for_chapter(book, 5)
                       if row["predicate"] == "身份"]
            self.assertEqual(sorted(at_five), ["档案员", "测绘员"])
            old = next(row for row in ws.facts_for_chapter(book, 5) if row["object"] == "测绘员")
            self.assertIsNone(old["valid_until_chapter"])

    def test_assertion_type_is_part_of_the_logical_key(self):
        """C3-09：同键 rumor 不得复用 fact 行、也不得改写其 assertion_type。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            base = {"entity_id": "e1", "domain": "character", "subject": "老周",
                    "predicate": "生死", "object": "死亡", "valid_from_chapter": 1,
                    "authority_level": "confirmed_prose"}
            first = ws.upsert_fact(book, {**base, "assertion_type": "fact"})["fact"]
            second = ws.upsert_fact(book, {**base, "assertion_type": "rumor"})["fact"]
            self.assertNotEqual(first["fact_id"], second["fact_id"])
            self.assertEqual(ws.get_fact(book, first["fact_id"])["assertion_type"], "fact")
            self.assertEqual(ws.get_fact(book, second["fact_id"])["assertion_type"], "rumor")

    def test_explicit_id_cannot_change_assertion_type(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            base = {"fact_id": "f1", "entity_id": "e1", "domain": "character",
                    "subject": "老周", "predicate": "生死", "object": "死亡",
                    "valid_from_chapter": 1, "authority_level": "confirmed_prose"}
            ws.upsert_fact(book, {**base, "assertion_type": "fact"})
            with self.assertRaises(ws.WorldStateError) as caught:
                ws.upsert_fact(book, {**base, "assertion_type": "rumor"})
            self.assertEqual(caught.exception.code, "assertion_type_mismatch")
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(ws.get_fact(book, "f1")["assertion_type"], "fact")

    def test_plain_upsert_does_not_promote_pending_fact(self):
        """C3-09：pending 只能由 confirm/reject 走出。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            base = {"entity_id": "e1", "domain": "character", "subject": "老周",
                    "predicate": "生死", "object": "死亡", "valid_from_chapter": 1,
                    "authority_level": "ai_inferred"}
            ws.upsert_fact(book, {**base, "status": "pending_confirm"})
            saved = ws.upsert_fact(book, {**base, "status": "active"})["fact"]
            self.assertEqual(saved["status"], "pending_confirm")


class FactDedupConcurrencyTest(unittest.TestCase):
    """C3-08：去重 SELECT 与写入同一写事务，双线程只产生一行。"""

    def test_concurrent_upsert_produces_one_row(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            wb.initialize(book)
            barrier = threading.Barrier(2)
            results = []
            errors = []

            def worker():
                try:
                    barrier.wait(timeout=5)
                    results.append(ws.upsert_fact(book, {
                        "entity_id": "e1", "domain": "character", "subject": "林溪",
                        "predicate": "身份", "object": "测绘员", "valid_from_chapter": 1,
                        "authority_level": "ai_inferred", "confidence": 0.9}))
                except Exception as exc:  # noqa: BLE001 - 线程内异常要回传
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            with wb.connect(book) as db:
                rows = db.execute("SELECT fact_id FROM world_facts WHERE subject='林溪'").fetchall()
            self.assertEqual(len(rows), 1)


class LeaseContractTest(unittest.TestCase):
    """C3-11 / C3-12：过期租约不得进入提交；fail 的 owner 校验进入 UPDATE。"""

    def test_begin_commit_rejects_expired_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "worker", lease_seconds=-1)
            with self.assertRaises(ce.SchedulerError) as caught:
                ce.begin_commit(book, task["task_id"], "worker")
            self.assertEqual(caught.exception.code, "recovery_required")
            current = ce.get(book, task["task_id"])
            self.assertEqual(current["state"], "recovery_required")
            self.assertFalse(current["committing"])

    def test_fail_cannot_clear_a_reclaimed_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "worker-old")
            stale = ce.get(book, task["task_id"])
            real_get = ce.get
            calls = {"count": 0}

            def fake_get(project_arg, task_id):
                calls["count"] += 1
                if calls["count"] == 1:
                    return dict(stale)
                return real_get(project_arg, task_id)

            # 模拟读后重领：另一个 worker 已拿到新租约。
            with wb.write_tx(book) as db:
                db.execute("UPDATE task_queue SET lease_owner='worker-new', lease_expires=?, "
                           "attempts=1 WHERE task_id=?",
                           (time.time() + 60, task["task_id"]))
            with mock.patch.object(ce, "get", side_effect=fake_get):
                with self.assertRaises(ce.SchedulerError) as caught:
                    ce.fail(book, task["task_id"], owner="worker-old", error="late failure")
            self.assertEqual(caught.exception.code, "task_not_running")
            current = real_get(book, task["task_id"])
            self.assertEqual(current["state"], "running")
            self.assertEqual(current["lease_owner"], "worker-new")
            self.assertIsNotNone(current["lease_expires"])


class SubmitContractTest(unittest.TestCase):
    """C3-14 / C3-15：task_id 参数冲突、blocked_by 校验与 blocked_reason。"""

    def test_task_id_with_different_payload_is_a_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            first = ce.submit(book, {"intent": "draft"}, priority="P1", task_id="fixed")
            self.assertEqual(first["task_id"], "fixed")
            with self.assertRaises(ce.SchedulerError) as caught:
                ce.submit(book, {"intent": "publish"}, priority="P0", task_id="fixed")
            self.assertEqual(caught.exception.code, "task_id_payload_mismatch")
            self.assertEqual(caught.exception.status, 409)
            same = ce.submit(book, {"intent": "draft"}, priority="P1", task_id="fixed")
            self.assertTrue(same["deduplicated"])
            self.assertEqual(same["priority"], "P1")
            self.assertEqual(len(ce.list_tasks(book)), 1)

    def test_missing_self_and_cycle_blockers_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            with self.assertRaises(ce.SchedulerError) as missing:
                ce.submit(book, {}, task_id="t-missing", blocked_by=["no-such-task"])
            self.assertEqual(missing.exception.code, "blocked_by_missing")
            self.assertEqual(missing.exception.status, 400)
            with self.assertRaises(ce.SchedulerError) as self_ref:
                ce.submit(book, {}, task_id="t-self", blocked_by=["t-self"])
            self.assertEqual(self_ref.exception.code, "blocked_by_self")
            # 既有损坏数据形成的环：x1 -> x2，再提交 x2 -> x1 必须被拒绝。
            insert_task(book, "x1", blocked_by=["x2"])
            with self.assertRaises(ce.SchedulerError) as cycle:
                ce.submit(book, {}, task_id="x2", blocked_by=["x1"])
            self.assertEqual(cycle.exception.code, "blocked_by_cycle")
            self.assertEqual([row["task_id"] for row in ce.list_tasks(book)], ["x1"])

    def test_snapshot_explains_why_pending_task_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            insert_task(book, "waiting", blocked_by=["ghost"])
            self.assertIsNone(ce.claim(book, "w", max_slots=4))
            snapshot = ce.snapshot(book)
            row = next(item for item in snapshot["tasks"] if item["task_id"] == "waiting")
            self.assertEqual(row["blocked_reason"], {"task_id": "ghost", "reason": "missing"})


class CardPartialUpdateTest(unittest.TestCase):
    """C3-16：只改名字/置顶不得清空 card_md/aliases/kind/story_time。"""

    def test_partial_update_keeps_untouched_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ws.set_card(book, {"entity_id": "ent_1", "name": "林溪", "kind": "character",
                               "aliases": ["小溪"], "pinned": True, "story_time": "第一年",
                               "card_md": "女主，测绘员，怕水。"})
            renamed = ws.set_card(book, {"entity_id": "ent_1", "name": "林溪（改名）"})
            self.assertEqual(renamed["name"], "林溪（改名）")
            self.assertEqual(renamed["kind"], "character")
            self.assertEqual(renamed["aliases"], ["小溪"])
            self.assertEqual(renamed["story_time"], "第一年")
            self.assertEqual(renamed["card_md"], "女主，测绘员，怕水。")
            self.assertTrue(renamed["pinned"])
            # 显式空值是清空语义，不是缺省。
            cleared = ws.set_card(book, {"entity_id": "ent_1", "name": "林溪（改名）",
                                         "aliases": [], "card_md": ""})
            self.assertEqual(cleared["aliases"], [])
            self.assertEqual(cleared["card_md"], "")
            self.assertEqual(cleared["kind"], "character")


if __name__ == "__main__":
    unittest.main()
