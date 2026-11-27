"""第四轮 C 域 API 回归：v0.8/v0.8.5 自愈、只读读路径、deferred、急停。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from integration import concurrent_engine, studio, workbench_db as wb
from manager import app as module


class AuditV4FixCApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-v4-fix-c-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = module.create_app(self.root / "manager.db", start_dispatcher=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(
            json.dumps({"title": "第四轮审计"}), encoding="utf-8")
        registered = self.client.post("/api/projects", json={"path": str(self.project)},
                                      headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.identity = registered.json()["id"]
        created = self.client.post(f"/api/projects/{self.identity}/chapters",
                                   json={"chapter": 1, "title": "开端",
                                         "content": "第一段。\n“你来了。”\n" * 10},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)

    def _readonly_project(self, with_db: bool) -> tuple[str, Path]:
        path = self.root / ("readonly-db" if with_db else "readonly-empty")
        (path / "正文").mkdir(parents=True)
        (path / ".webnovel").mkdir()
        (path / ".webnovel" / "state.json").write_text(json.dumps({"title": "只读"}),
                                                       encoding="utf-8")
        (path / "正文" / "第1章-旧稿.md").write_text("第一段。\n", encoding="utf-8",
                                                     newline="\n")
        if with_db:
            wb.initialize(path)
        response = self.client.post("/api/projects", json={"path": str(path)},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"], path

    # ------------------------------------------------------------ C3-03
    def test_v08_draft_column_and_preview_table_self_heal(self):
        with wb.write_tx(self.project) as db:
            db.execute("ALTER TABLE chapter_drafts DROP COLUMN draft_epoch")
            db.execute("DROP TABLE preview_index")
        draft = self.client.put(f"/api/projects/{self.identity}/chapters/1/draft",
                                json={"title": "开端", "content": "草稿一",
                                      "expected_draft_id": None, "expected_draft_epoch": 0,
                                      "expected_draft_revision": 0}, headers=self.headers)
        self.assertEqual(draft.status_code, 200, draft.text)
        previews = self.client.get(
            f"/api/projects/{self.identity}/chapters/1/previews")
        self.assertEqual(previews.status_code, 200, previews.text)
        from integration import maintenance
        self.assertTrue(maintenance.schema_report(self.project)["current"])

    def test_v085_annotation_table_self_heals(self):
        with wb.write_tx(self.project) as db:
            db.execute("DROP TABLE annotations")
        response = self.client.get(
            f"/api/projects/{self.identity}/chapters/1/annotations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["annotations"], [])

    # ------------------------------------------------------------ C3-04
    def test_read_only_missing_database_gets_do_not_create_it(self):
        identity, path = self._readonly_project(with_db=False)
        for suffix in ("chapters/1/annotations", "chapters/1/annotations/previews",
                       "chapters/1/previews"):
            response = self.client.get(f"/api/projects/{identity}/{suffix}")
            self.assertEqual(response.status_code, 200, (suffix, response.text))
        self.assertFalse(wb.db_path(path).exists())

    def test_read_only_existing_database_gets_do_not_500(self):
        identity, path = self._readonly_project(with_db=True)
        webnovel = path / ".webnovel"
        db_file = wb.db_path(path)
        try:
            os.chmod(db_file, 0o444)
            os.chmod(webnovel, 0o555)
            for suffix in ("chapters/1/annotations", "chapters/1/annotations/previews",
                           "chapters/1/previews", "world-state?chapter=1", "quality", "tasks"):
                response = self.client.get(f"/api/projects/{identity}/{suffix}")
                self.assertEqual(response.status_code, 200, (suffix, response.text))
            gc = self.client.post(f"/api/projects/{identity}/diagnostics/gc",
                                  json={"dry_run": True}, headers=self.headers)
            self.assertEqual(gc.status_code, 200, gc.text)
            exported = self.client.post(f"/api/projects/{identity}/diagnostics/export",
                                        json={}, headers=self.headers)
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertFalse((webnovel / "locks").exists())
        finally:
            os.chmod(webnovel, 0o755)
            os.chmod(db_file, 0o644)

    # ------------------------------------------------------------ C3-17/C3-18
    def test_deferred_operation_is_active_and_blocks_project_mutex(self):
        store = self.app.state.store
        operations = self.app.state.operations
        operations._execute = Mock()
        payload = {"id": "op-deferred", "kind": "daily", "identity": "job:old",
                   "status": "deferred", "project_id": self.identity,
                   "created_at": "2026-01-01T00:00:00Z",
                   "result": {"error": "waiting"}}
        store.save_operation(payload)
        active = store.operations(active_only=True)
        self.assertIn("op-deferred", [row["id"] for row in active])
        with self.assertRaises(HTTPException) as caught:
            operations.start("daily", ["run", "--job-id", "new"], "job:new",
                             {"project_id": self.identity,
                              "project_path": str(self.project)})
        self.assertEqual(caught.exception.status_code, 409)
        operations.resume_due()
        self.assertEqual(store.operation("op-deferred")["status"], "interrupted")
        admitted = operations.start("daily", ["run", "--job-id", "new"], "job:new",
                                    {"project_id": self.identity,
                                     "project_path": str(self.project)})
        self.assertEqual(admitted["status"], "queued")

    # ------------------------------------------------------------ C3-23
    def test_invalid_identity_pause_has_no_side_effect(self):
        pause_file = self.root / "global_pause.json"
        missing = self.client.post("/api/system/ai/pause",
                                   json={"identity": "missing", "paused": True},
                                   headers=self.headers)
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertFalse(pause_file.exists())
        missing_resume = self.client.post("/api/system/ai/pause",
                                          json={"identity": "missing", "paused": False},
                                          headers=self.headers)
        self.assertEqual(missing_resume.status_code, 404, missing_resume.text)
        self.assertFalse(pause_file.exists())

    def test_global_resume_clears_project_pause_rows(self):
        paused = self.client.post("/api/system/ai/pause",
                                  json={"identity": self.identity, "paused": True},
                                  headers=self.headers)
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertTrue(concurrent_engine.project_paused(self.project))
        resumed = self.client.post("/api/system/ai/pause", json={"paused": False},
                                   headers=self.headers)
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertFalse(concurrent_engine.project_paused(self.project))
        self.assertEqual([row for row in concurrent_engine.paused_scopes(self.project)
                          if row["scope"] == "global"], [])

    def test_resume_due_does_not_spawn_during_global_pause(self):
        operations = self.app.state.operations
        operations._execute = Mock()
        store = self.app.state.store
        batch_id = "a" * 32
        retry = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        batch = studio.project_file(self.project, "batches", batch_id)
        batch.parent.mkdir(parents=True, exist_ok=True)
        batch.write_text(json.dumps({"id": batch_id, "status": "waiting",
                                     "recovery": {"next_retry_at": retry}}),
                         encoding="utf-8")
        payload = {"id": "op-resume", "kind": "generate", "identity": "batch:" + batch_id,
                   "status": "deferred", "project_id": self.identity,
                   "batch_id": batch_id, "created_at": "2026-01-01T00:00:00Z",
                   "result": {"failure_kind": "recovery_cooldown", "next_retry_at": retry,
                              "project": str(self.project), "batch_id": batch_id}}
        store.save_operation(payload)
        (self.root / "global_pause.json").write_text(json.dumps({"paused": True}),
                                                     encoding="utf-8")
        operations.resume_due()
        self.assertEqual(store.operation("op-resume")["status"], "deferred")
        operations._execute.assert_not_called()
        (self.root / "global_pause.json").write_text(json.dumps({"paused": False}),
                                                     encoding="utf-8")
        operations.resume_due()
        self.assertEqual(store.operation("op-resume")["status"], "queued")
        operations._execute.assert_called_once()

    # ------------------------------------------------------------ C3-22/C4-02/C3-24
    def test_v09_scalar_and_boolean_inputs_are_400(self):
        base = f"/api/projects/{self.identity}/tasks"
        claimed = self.client.post(base + "/claim", json={"owner": "w", "max_slots": {"x": 1}},
                                   headers=self.headers)
        self.assertEqual(claimed.status_code, 400, claimed.text)
        self.assertEqual(claimed.json()["code"], "invalid_request")
        quality = self.client.post(
            f"/api/projects/{self.identity}/quality/1/review",
            json={"force": "false"}, headers=self.headers)
        self.assertEqual(quality.status_code, 400, quality.text)
        paused = self.client.post("/api/system/ai/pause",
                                  json={"paused": "false"}, headers=self.headers)
        self.assertEqual(paused.status_code, 400, paused.text)
        self.assertFalse((self.root / "global_pause.json").exists())

    def test_health_response_shape_is_uniform(self):
        response = self.client.get(f"/api/projects/{self.identity}/diagnostics")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        for key in ("versions", "drafts", "counts", "disk_free_bytes", "checked_at"):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()
