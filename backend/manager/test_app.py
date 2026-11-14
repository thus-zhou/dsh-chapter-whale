"""API tests use isolated local state and never call an external service."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-manager-test-")
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json")]
        for item in self.patches:
            item.start()
        self.app = module.create_app(self.root / "manager.db", start_dispatcher=False)
        self.client = TestClient(self.app)
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "测试作品"}), encoding="utf-8")
        (self.project / "正文" / "第1章-初见.md").write_text("<script>alert(1)</script>\n正文", encoding="utf-8")
        (self.project / "大纲" / "卷一.md").write_text("## 第2章 夜雨\n新的线索", encoding="utf-8")

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def register(self):
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_registration_is_idempotent_and_chapters_are_confined(self):
        first = self.register()
        second = self.register()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.client.get("/api/projects").json()), 1)
        preview = self.client.get(f"/api/projects/{first['id']}/chapters/1")
        self.assertIn("正文", preview.json()["content"])
        self.assertEqual(self.client.get("/api/projects/unknown/chapters/1").status_code, 404)

    def test_cross_origin_and_missing_action_header_are_rejected(self):
        self.assertEqual(self.client.post("/api/projects", json={"path": str(self.project)}).status_code, 403)
        headers = {**self.headers, "Origin": "https://attacker.invalid"}
        self.assertEqual(self.client.post("/api/projects", json={"path": str(self.project)}, headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "attacker.invalid"}).status_code, 400)

    def test_ai_key_is_write_only_and_blank_preserves_it(self):
        config = {"base_url": "https://api.example.org/v1", "model": "test-model", "api_key": "secret-test-123"}
        response = self.client.put("/api/ai", json=config, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secret-test-123", response.text)
        response = self.client.put("/api/ai", json={**config, "api_key": ""}, headers=self.headers)
        self.assertEqual(module.load_ai()["api_key"], "secret-test-123")
        self.assertNotIn("secret-test-123", module.AI_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("secret-test-123", self.client.get("/api/ai").text)

    def test_outline_edit_creates_backup_and_does_not_merge_volumes(self):
        item = self.register()
        url = f"/api/projects/{item['id']}/outline"
        response = self.client.put(url, json={"content": "## 第2章 新的大纲"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list((self.root / "backups").glob("*.md"))), 1)
        (self.project / "大纲" / "卷二.md").write_text("## 第3章", encoding="utf-8")
        self.assertEqual(self.client.put(url, json={"content": "合并"}, headers=self.headers).status_code, 409)

    def test_restarted_operation_is_interrupted(self):
        self.app.state.store.save_operation({"id": "old", "status": "running", "kind": "publish"})
        new_app = module.create_app(self.root / "manager.db", start_dispatcher=False)
        self.assertEqual(new_app.state.store.operation("old")["status"], "interrupted")

    def test_active_operation_is_not_hidden_by_newer_history(self):
        store = self.app.state.store
        store.save_operation({"id":"old-active", "status":"running", "kind":"generate", "identity":"project:book"})
        for number in range(105):
            store.save_operation({"id":str(number), "status":"success", "kind":"stage"})
        self.assertEqual(len(store.operations()), 100)
        self.assertEqual(store.operations(active_only=True)[0]["id"], "old-active")
        with self.assertRaises(module.HTTPException) as caught:
            self.app.state.operations.start("generate", [], "project:book")
        self.assertEqual(caught.exception.status_code, 409)
        restarted = module.Operations(store)
        self.assertEqual(store.operation("old-active")["status"], "interrupted")

    def test_corrupt_ai_during_worker_start_finishes_as_failed(self):
        module.AI_PATH.write_text("[]", encoding="utf-8")
        store = self.app.state.store
        store.save_operation({"id":"broken-config", "status":"queued", "kind":"stage"})
        operations = module.Operations(store)
        # Operations constructor reconciles restart records, then exercise the
        # exact worker path without launching any child or external service.
        store.save_operation({"id":"broken-config", "status":"queued", "kind":"stage"})
        with patch.object(module.subprocess, "Popen") as launch:
            operations._execute("broken-config", [])
        launch.assert_not_called()
        record = store.operation("broken-config")
        self.assertEqual(record["status"], "failed")
        self.assertIn("finished_at", record)

    def test_zero_exit_without_structured_worker_result_is_not_success(self):
        from io import StringIO
        from unittest.mock import MagicMock
        store = self.app.state.store
        operations = module.Operations(store)
        store.save_operation({"id":"missing-result", "status":"queued", "kind":"publish"})
        child = MagicMock()
        child.pid = 999999
        child.stdout = StringIO("finished without receipt\n")
        child.stdin = StringIO()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with patch.object(module, "load_ai", return_value={}), patch.object(module.subprocess, "Popen", return_value=child):
            operations._execute("missing-result", [])
        self.assertEqual(store.operation("missing-result")["status"], "failed")

    def test_corrupt_project_does_not_crash_entire_bookshelf(self):
        item = self.register()
        (self.project / ".webnovel" / "state.json").write_text("[]", encoding="utf-8")
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()[0]["ready"])
        self.assertIn("损坏", response.json()[0]["error"])

    def test_corrupt_ai_is_not_overwritten_as_empty_configuration(self):
        module.AI_PATH.write_text("[]", encoding="utf-8")
        response = self.client.get("/api/ai")
        self.assertFalse(response.json()["configured"])
        response = self.client.put("/api/ai", json={"base_url":"https://example.test/v1","model":"m"}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(module.AI_PATH.read_text(), "[]")

    def test_outline_save_does_not_race_active_writer(self):
        item = self.register()
        with module.writer_runner.file_lock(self.project / ".webnovel" / "writer.lock"):
            response = self.client.put(f"/api/projects/{item['id']}/outline", json={"content":"new outline"}, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertIn("夜雨", (self.project / "大纲" / "卷一.md").read_text(encoding="utf-8"))

    def test_no_generate_without_ai_and_no_publish_without_account(self):
        item = self.register()
        with patch.object(module, "public_ai", return_value={"configured": False}):
            response = self.client.post(f"/api/projects/{item['id']}/generate", json={}, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/publish", json={"project_id": item["id"], "account": "missing-account", "book": "测试作品", "count": 1}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.app.state.store.operations(), [])


if __name__ == "__main__":
    unittest.main()
