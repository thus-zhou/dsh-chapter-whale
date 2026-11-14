"""关键访问面：凭据不外泄、未授权写入被拒、跨项目与路径边界（隔离目录）。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module

from integration import chapter_versions

SECRET = "sk-access-test-1234567890"


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-access-")
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json"),
                        patch.object(module.secret_store, "codec", lambda: fake_pair())]
        for item in self.patches:
            item.start()
        module._AI_MIGRATION_TRIED = False
        self.client = TestClient(module.create_app(self.root / "manager.db", start_dispatcher=False))
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book-a"
        self.other = self.root / "book-b"
        for folder in (self.project, self.other):
            (folder / "正文").mkdir(parents=True)
            (folder / ".webnovel").mkdir()
            (folder / ".webnovel" / "state.json").write_text(json.dumps({"title": folder.name}), encoding="utf-8")
        (self.project / "正文" / "第1章-甲的正文.md").write_text("甲的第一章。\n", encoding="utf-8")
        (self.other / "正文" / "第1章-乙的正文.md").write_text("乙的第一章。\n", encoding="utf-8")
        self.identity = self.register(self.project)
        self.other_identity = self.register(self.other)

    def register(self, folder):
        response = self.client.post("/api/projects", json={"path": str(folder)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_saved_key_never_lands_in_the_config_or_the_response(self):
        response = self.client.put("/api/ai", json={"base_url": "https://api.example.com/v1",
                                                    "model": "test-model", "api_key": SECRET},
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(SECRET, response.text)
        self.assertEqual(response.json()["key_masked"], "••••••••")
        self.assertEqual(response.json()["credential_store"]["mode"], "dpapi")
        on_disk = (self.root / "ai.json").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, on_disk)
        store = (self.root / "secrets.dpapi").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, store)
        again = self.client.get("/api/ai")
        self.assertNotIn(SECRET, again.text)
        self.assertTrue(again.json()["configured"])

    def test_redaction_removes_the_saved_key_from_logs(self):
        self.client.put("/api/ai", json={"base_url": "https://api.example.com/v1",
                                         "model": "test-model", "api_key": SECRET}, headers=self.headers)
        text = module.redact(f"request failed with key {SECRET} and sk-abcdefgh12345678")
        self.assertNotIn(SECRET, text)
        self.assertNotIn("sk-abcdefgh12345678", text)
        self.assertIn("[redacted]", text)

    def test_writes_without_the_helper_header_or_from_another_origin_are_refused(self):
        body = {"version_id": "0" * 64}
        self.assertEqual(self.client.post(f"/api/projects/{self.identity}/chapters/1/restore",
                                          json=body).status_code, 403)
        self.assertEqual(self.client.post(f"/api/projects/{self.identity}/chapters/1/restore", json=body,
                                          headers={**self.headers, "origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.put("/api/ai", json={"base_url": "https://api.example.com/v1",
                                                          "model": "m", "api_key": SECRET}).status_code, 403)

    def test_project_boundary_and_path_traversal_are_rejected(self):
        chapter_versions.write_chapter(self.project, 1, "甲的第一章。\n", op_id="op-a", allow_new=True)
        chapter_versions.write_chapter(self.other, 1, "乙的第一章。\n", op_id="op-b", allow_new=True)
        listed = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions")
        self.assertEqual(listed.status_code, 200, listed.text)
        version = listed.json()["versions"][0]["version_id"]
        mine = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions/{version}")
        self.assertEqual(mine.json()["body"].replace("\r\n", "\n"), "甲的第一章。\n")
        traversal = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions/..%2F..%2Fstate.json")
        self.assertIn(traversal.status_code, (400, 404), traversal.text)
        self.assertEqual(self.client.get("/api/projects/not-registered/chapters/1/versions").status_code, 404)
        self.assertEqual(self.client.get(f"/api/projects/{self.identity}/chapters/0/versions").status_code, 400)

    def test_degraded_mode_is_reported_instead_of_claiming_success(self):
        with patch.object(module.secret_store, "codec", lambda: None):
            response = self.client.put("/api/ai", json={"base_url": "https://api.example.com/v1",
                                                        "model": "test-model", "api_key": SECRET},
                                       headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["credential_store"]["mode"], "plaintext-acl")
        self.assertFalse(response.json()["credential_store"]["available"])
        self.assertIn(SECRET, (self.root / "ai.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
