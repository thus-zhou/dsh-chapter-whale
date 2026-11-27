"""v0.7.5 回滚兼容测试：旧 SQL、旧回执、旧大纲解析与降级导出。"""
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from fanqie_auto_publish import publication_safety as ps
from integration import chapter_versions as cv
from integration import costs
from integration import outline_editor as oe
from integration import studio
from manager import app as module

USAGE_COLUMNS = [
    (0, "id", "TEXT", 0, None, 1),
    (1, "created_at", "TEXT", 1, None, 0),
    (2, "project", "TEXT", 1, None, 0),
    (3, "chapter", "INTEGER", 1, None, 0),
    (4, "stage", "TEXT", 1, None, 0),
    (5, "model", "TEXT", 1, None, 0),
    (6, "payload", "TEXT", 1, None, 0),
]
BUDGET_COLUMNS = [
    (0, "id", "TEXT", 0, None, 1),
    (1, "created_at", "TEXT", 1, None, 0),
    (2, "project", "TEXT", 1, None, 0),
    (3, "chapter", "INTEGER", 1, None, 0),
    (4, "stage", "TEXT", 1, None, 0),
    (5, "day", "TEXT", 1, None, 0),
    (6, "state", "TEXT", 1, None, 0),
    (7, "tokens", "INTEGER", 1, "0", 0),
    (8, "cost_cny", "TEXT", 0, None, 0),
    (9, "unknown_cost", "INTEGER", 1, "0", 0),
    (10, "operation", "TEXT", 0, None, 0),
]
NEW_WORKBENCH_TABLES = {
    "workbench_meta", "chapter_meta", "chapter_drafts", "idempotency_keys",
    "annotations", "annotation_hunks", "patch_ledger", "preview_index",
    "book_directives", "directive_exemptions", "world_facts", "world_entities",
    "context_manifests", "conflict_ignores", "rule_versions", "search_docs",
    "search_fts", "drafts_history",
}


class V075RollbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-v075-rollback-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.manager_db = self.root / "manager.sqlite3"
        self.client = TestClient(module.create_app(self.manager_db, start_dispatcher=False))
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / "大纲").mkdir()
        (self.project / "设定").mkdir()
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(
            json.dumps({"title": "回滚兼容测试"}, ensure_ascii=False), encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]

    # ------------------------------------------------------------------ helpers
    def create_chapter(self, chapter: int = 1, title: str = "开端",
                       content: str = "第一章正文\n") -> dict:
        response = self.client.post(
            f"/api/projects/{self.identity}/chapters",
            json={"chapter": chapter, "title": title, "content": content},
            headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def chapter_state(self, chapter: int = 1) -> dict:
        response = self.client.get(f"/api/projects/{self.identity}/chapters/{chapter}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def write_chapter(self, content: str, chapter: int = 1) -> dict:
        state = self.chapter_state(chapter)
        response = self.client.put(
            f"/api/projects/{self.identity}/chapters/{chapter}",
            json={"title": state["title"], "content": content, "op_id": "rollback-edit",
                  "expected_version_id": state["version_id"],
                  "expected_content_sha256": state["sha256"]},
            headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def receipts(self) -> dict:
        path = self.project / ".webnovel" / "writer_receipts.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------- legacy manager.sqlite3
    def test_legacy_two_column_operations_insert_still_works(self):
        connection = sqlite3.connect(self.manager_db)
        try:
            columns = [tuple(row)[1:3] for row in connection.execute(
                "PRAGMA table_info(operations)")]
            self.assertEqual(columns, [("id", "TEXT"), ("payload", "TEXT")])

            payload = {"id": "legacy-op-1", "kind": "write", "status": "done",
                       "operation_key": "legacy-key-1"}
            connection.execute("INSERT INTO operations VALUES (?, ?)",
                               ("legacy-op-1", json.dumps(payload, ensure_ascii=False)))
            connection.commit()

            payload["status"] = "interrupted"
            connection.execute("UPDATE operations SET payload=? WHERE id=?",
                               (json.dumps(payload, ensure_ascii=False), "legacy-op-1"))
            connection.commit()
        finally:
            connection.close()

        response = self.client.get("/api/operations/legacy-op-1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "interrupted")
        stored = module.Store(self.manager_db).operations()
        self.assertTrue(any(item.get("id") == "legacy-op-1" for item in stored))

        connection = sqlite3.connect(self.manager_db)
        try:
            names = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        self.assertFalse(names & NEW_WORKBENCH_TABLES)

    # ------------------------------------------------ author_confirmed receipt read
    def test_legacy_read_of_author_confirmed_returns_false_not_exception(self):
        created = self.create_chapter(content="作者定稿正文\n")
        confirmed = self.client.post(
            f"/api/projects/{self.identity}/chapters/1/author-confirm",
            json={"expected_version_id": created["version_id"],
                  "expected_content_sha256": created["sha256"],
                  "op_id": "confirm-rollback"},
            headers=self.headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        entry = self.receipts()["1"]
        review = entry["review"]
        self.assertTrue(review["author_confirmed"])
        self.assertEqual(review["review_decision"], "author_confirmed")
        body = ps.body_digest(cv.chapter_path(self.project, 1)
                              .read_text(encoding="utf-8-sig"))

        # 正常绑定仍应通过；旧版两参数调用 / 顶层回执 / 缺身份字段必须安全返回 False。
        self.assertTrue(ps.review_eligible(review, body, self.project, 1))
        self.assertIs(ps.review_eligible(review, body), False)
        self.assertIs(ps.review_eligible(entry, body, self.project, 1), False)
        self.assertIs(ps.review_eligible(review, body, None, None), False)
        self.assertIs(ps.review_eligible(review, body, self.project, 999), False)
        self.assertIs(ps.review_eligible(review, "0" * 64, self.project, 1), False)
        self.assertIs(ps.review_eligible(None, body, self.project, 1), False)

        # 正文被改动后，旧回执绝不能继续放行，也不能抛异常。
        self.write_chapter("正文已被改走\n")
        self.assertIs(ps.review_eligible(review, body, self.project, 1), False)

        without_version = {key: value for key, value in review.items()
                           if key != "confirmed_version_id"}
        without_sha = {key: value for key, value in review.items()
                       if key != "confirmed_content_sha256"}
        self.assertIs(ps.review_eligible(without_version, body, self.project, 1), False)
        self.assertIs(ps.review_eligible(without_sha, body, self.project, 1), False)

    # ------------------------------------------------------- AI plan legacy reader
    def test_ai_plan_with_chapter_rev_parses_under_legacy_assumptions(self):
        name = "AI规划-0001-0002.md"
        initial = "## 第1章 开端\n旧细纲一\n\n## 第2章 承继\n旧细纲二\n"
        updated = "## 第1章 开端\n新细纲一\n\n## 第2章 承继\n新细纲二\n"
        oe.create_file(self.project, filename=name, content=initial)
        revision = oe.read_file(self.project, name)["revision"]
        oe.write_file(self.project, name, content=updated, revision=revision)

        path = self.project / "大纲" / name
        with path.open(encoding="utf-8") as stream:
            first = stream.readline()
        self.assertTrue(first.startswith("<!-- novel-plan:"))
        payload = json.loads(first[len("<!-- novel-plan:"):]
                              .removesuffix("\n").removesuffix(" -->"))
        self.assertIsInstance(payload["chapters"], list)
        for chapter in payload["chapters"]:
            self.assertIsInstance(chapter["chapter_rev"], int)
        visible = [line for line in path.read_text(encoding="utf-8").splitlines()
                   if line.startswith("## 第")]
        self.assertEqual(len(visible), 2)

        # 模拟 v0.7.5 项目：没有 story_plan_meta.json，只有旧 story_plan.json。
        (self.project / ".webnovel" / "story_plan_meta.json").unlink(missing_ok=True)
        self.assertFalse((self.project / ".webnovel" / "story_plan_meta.json").exists())
        (self.project / ".webnovel" / "story_plan.json").write_text(
            json.dumps({"chapters": {}}, ensure_ascii=False), encoding="utf-8")

        recovered = studio.recover_plan(self.project, persist=True)

        self.assertEqual(recovered["chapters"]["1"]["outline"], "新细纲一")
        self.assertIsInstance(recovered["chapters"]["1"]["chapter_rev"], int)
        persisted = json.loads((self.project / ".webnovel" / "story_plan.json")
                               .read_text(encoding="utf-8"))
        self.assertEqual(persisted["chapters"]["1"]["outline"], "新细纲一")

    # ------------------------------------------------------- rollback/export-legacy
    def make_snapshot_export(self):
        content = "导出的第一章\n\n第二段。\n"
        self.create_chapter(content=content)
        self.create_chapter(2, "第二章", "导出的第二章\n")

        snapshot = self.root / "backups" / "snapshot"
        backed = self.client.post(f"/api/projects/{self.identity}/backup",
                                  json={"destination": str(snapshot)}, headers=self.headers)
        self.assertEqual(backed.status_code, 200, backed.text)

        exported = self.root / "exports" / "legacy-copy"
        response = self.client.post(
            f"/api/projects/{self.identity}/rollback/export-legacy",
            json={"destination": str(exported), "mode": "snapshot",
                  "snapshot_dir": str(snapshot)},
            headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return exported, content

    def test_snapshot_export_opens_as_normal_v075_project(self):
        exported, content = self.make_snapshot_export()

        mapping = cv.chapter_map(exported)
        self.assertIn(1, mapping)
        self.assertEqual(mapping[1].read_text(encoding="utf-8"), content)
        digest = cv.file_sha256(mapping[1])
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

        index_path = exported / ".webnovel" / "chapter_versions" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = index["chapters"]["1"]
        self.assertRegex(entry["current"], r"^[0-9a-f]{64}$")
        self.assertEqual(entry["current"], digest)
        self.assertTrue(any(meta["sha256"] == digest for meta in entry["versions"]))

        meta = cv.current_version(exported, 1)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["sha256"], digest)
        self.assertEqual(cv.read_version(exported, 1)["text"], content)

        # v0.7.5 索引没有 current_version_id，只能按 entry["current"] 的 sha 解析。
        entry.pop("current_version_id", None)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        legacy_meta = cv.current_version(exported, 1)
        self.assertIsNotNone(legacy_meta)
        self.assertEqual(legacy_meta["sha256"], digest)
        self.assertEqual(cv.read_version(exported, 1, digest)["text"], content)

    def test_exported_snapshot_is_registrable_by_v075_manager(self):
        exported, _ = self.make_snapshot_export()
        response = self.client.post("/api/projects", json={"path": str(exported)},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    # ------------------------------------------------------------- costs schema
    def test_request_budget_and_usage_events_columns_are_unchanged(self):
        db = costs.connection(self.root / "costs.sqlite3")
        try:
            self.assertEqual([tuple(row) for row in db.execute(
                "PRAGMA table_info(usage_events)")], USAGE_COLUMNS)
            self.assertEqual([tuple(row) for row in db.execute(
                "PRAGMA table_info(request_budget)")], BUDGET_COLUMNS)

            db.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?,?)",
                       ("usage-1", "2026-11-26T00:00:00+00:00", str(self.project),
                        1, "draft", "model-x", json.dumps({"tokens": 1})))
            db.execute("INSERT INTO request_budget VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       ("budget-1", "2026-11-26T00:00:00+00:00", str(self.project),
                        1, "draft", "2026-11-26", "released", 0, "0", 0, "op-1"))
            db.commit()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT state FROM request_budget").fetchone()[0],
                             "released")
            legacy_row = db.execute(
                "SELECT chapter,day,state,tokens,cost_cny,unknown_cost FROM request_budget "
                "WHERE project=?", (str(self.project),)).fetchone()
            self.assertEqual(tuple(legacy_row), (1, "2026-11-26", "released", 0, "0", 0))
        finally:
            db.close()

        # 新表只存在于项目级 workbench.sqlite3，旧库看不到也不会因此报错。
        legacy_db = sqlite3.connect(self.root / "costs.sqlite3")
        try:
            names = {row[0] for row in legacy_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            legacy_db.close()
        self.assertFalse(names & NEW_WORKBENCH_TABLES)


if __name__ == "__main__":
    unittest.main()
