"""Workbench SQLite foundation: WAL, drafts/ABA, idempotency, FTS 2-gram."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from integration import workbench_db as wb


def project(folder):
    root = Path(folder) / "书"
    (root / "正文").mkdir(parents=True)
    return root


class WorkbenchDbTest(unittest.TestCase):
    def test_wal_and_schema_are_initialized(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            wb.initialize(root)
            with wb.connect(root) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 15000)
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in ("chapter_meta", "chapter_drafts", "idempotency_keys",
                         "annotations", "annotation_hunks", "patch_ledger",
                         "world_facts", "search_docs"):
                self.assertIn(name, tables)

    def test_chapter_uid_is_stable_and_epoch_never_resets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            first = wb.chapter_uid(root, 1)
            self.assertTrue(first.startswith("chuid_"))
            self.assertEqual(first, wb.chapter_uid(root, 1))

            draft = wb.save_draft(root, 1, title="开端", content="第一版",
                                  expected_draft_id=None, expected_draft_epoch=0,
                                  expected_draft_revision=0)
            self.assertEqual(draft["draft_epoch"], 1)
            self.assertEqual(draft["draft_revision"], 1)
            again = wb.save_draft(root, 1, title="开端", content="第二版",
                                  expected_draft_id=draft["draft_id"],
                                  expected_draft_epoch=1, expected_draft_revision=1)
            self.assertEqual(again["draft_revision"], 2)
            cleared = wb.clear_draft_if_matches(root, 1, draft_id=again["draft_id"],
                                                draft_epoch=1, draft_revision=2)
            self.assertTrue(cleared["cleared"])
            third = wb.save_draft(root, 1, title="开端", content="删除后重建",
                                  expected_draft_id=None, expected_draft_epoch=2,
                                  expected_draft_revision=0)
            self.assertEqual(third["draft_epoch"], 3)
            self.assertEqual(third["draft_revision"], 1)

    def test_stale_revision_is_conflict_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            draft = wb.save_draft(root, 1, title="", content="桌面稿",
                                  expected_draft_id=None, expected_draft_epoch=0,
                                  expected_draft_revision=0)
            # 平板拿着旧 revision=1 来写：必须 409，而不是静默覆盖桌面新稿。
            wb.save_draft(root, 1, title="", content="桌面继续写",
                          expected_draft_id=draft["draft_id"], expected_draft_epoch=1,
                          expected_draft_revision=1)
            with self.assertRaises(wb.DraftConflict) as caught:
                wb.save_draft(root, 1, title="", content="平板旧稿",
                              expected_draft_id=draft["draft_id"], expected_draft_epoch=1,
                              expected_draft_revision=1)
            self.assertEqual(caught.exception.current["content"], "桌面继续写")

    def test_ctrl_s_preserves_newer_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            draft = wb.save_draft(root, 1, title="", content="提交的稿",
                                  expected_draft_id=None, expected_draft_epoch=0,
                                  expected_draft_revision=0)
            newer = wb.save_draft(root, 1, title="", content="保存后继续打字",
                                  expected_draft_id=draft["draft_id"], expected_draft_epoch=1,
                                  expected_draft_revision=1)
            result = wb.clear_draft_if_matches(root, 1, draft_id=draft["draft_id"],
                                               draft_epoch=1, draft_revision=1)
            self.assertFalse(result["cleared"])
            self.assertTrue(result["draft_preserved"])
            self.assertEqual(result["current_draft_revision"], 2)
            self.assertEqual(wb.get_draft(root, 1)["content"], "保存后继续打字")
            self.assertEqual(newer["content"], "保存后继续打字")

    def test_idempotency_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            params = {"chapter": 1, "content": "甲"}
            first = wb.idempotency_begin(root, actor="author", project_id="p", action="chapter_save",
                                         op_id="op-1", params=params)
            self.assertEqual(first["status"], "new")
            second = wb.idempotency_begin(root, actor="author", project_id="p", action="chapter_save",
                                          op_id="op-1", params=params)
            self.assertEqual(second["status"], "in_progress")
            mismatch = wb.idempotency_begin(root, actor="author", project_id="p", action="chapter_save",
                                            op_id="op-1", params={"chapter": 2})
            self.assertEqual(mismatch["status"], "mismatch")
            wb.idempotency_complete(root, actor="author", project_id="p", action="chapter_save",
                                    op_id="op-1", response={"ok": True})
            done = wb.idempotency_begin(root, actor="author", project_id="p", action="chapter_save",
                                        op_id="op-1", params=params)
            self.assertEqual(done["status"], "completed")
            self.assertEqual(done["response"], {"ok": True})
            wb.idempotency_fail(root, actor="author", project_id="p", action="chapter_save", op_id="op-2")
            retry = wb.idempotency_begin(root, actor="author", project_id="p", action="chapter_save",
                                         op_id="op-2", params=params)
            self.assertEqual(retry["status"], "new")

    def test_two_character_chinese_name_recall(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            wb.index_document(root, doc_key="正文:1", kind="chapter", chapter_id=1,
                              title="雨夜", content="林溪拿着旧地图走进档案馆。老周在后门等她。")
            hits = wb.search(root, "林溪")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["chapter_id"], 1)
            self.assertIn("林溪", hits[0]["snippet"])
            hits2 = wb.search(root, "老周")
            self.assertTrue(hits2)
            self.assertIn("老周", wb.search(root, "档案馆")[0]["snippet"])

    def test_schema_tables_do_not_collide_with_v075_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            root = project(folder)
            wb.initialize(root)
            with wb.connect(root) as db:
                names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("projects", names)
            self.assertNotIn("operations", names)
            self.assertNotIn("settings", names)
            self.assertNotIn("request_budget", names)
            self.assertNotIn("usage_events", names)


if __name__ == "__main__":
    unittest.main()
