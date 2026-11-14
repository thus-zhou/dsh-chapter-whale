"""文风档案接口：隔离目录，不触发模型调用。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module


class StyleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-style-api-")
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json")]
        for item in self.patches:
            item.start()
        self.client = TestClient(module.create_app(self.root / "manager.db", start_dispatcher=False))
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "隔离测试"}), encoding="utf-8")
        (self.project / ".webnovel" / "creative_brief.json").write_text(
            json.dumps({"schema": 1, "revision": 1, "brief": {"genre": "悬疑"}, "history": []},
                       ensure_ascii=False), encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_empty_profile_is_unavailable(self):
        view = self.client.get(f"/api/projects/{self.identity}/style-profile").json()
        self.assertEqual(view["status"], "unavailable")
        self.assertEqual(view["samples"], [])

    def test_upload_then_adjust_strength_and_delete(self):
        upload = self.client.post(
            f"/api/projects/{self.identity}/samples",
            files={"file": ("样本.txt", "他说：「走吧。」\n".encode("utf-8"), "text/plain")},
            headers=self.headers)
        self.assertEqual(upload.status_code, 200, upload.text)
        sample = upload.json()
        view = self.client.get(f"/api/projects/{self.identity}/style-profile").json()
        self.assertEqual(view["status"], "limited")
        self.assertEqual(view["samples"][0]["name"], "样本.txt")

        saved = self.client.put(f"/api/projects/{self.identity}/style-profile",
                                json={"strength": 80, "enabled": True, "overrides": {"style": "多写动作"}},
                                headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["strength"], 80)
        self.assertEqual(saved.json()["overrides"], {"style": "多写动作"})

        rebuilt = self.client.post(f"/api/projects/{self.identity}/style-profile/rebuild", headers=self.headers)
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        self.assertEqual(len(rebuilt.json()["samples"]), 1)

        removed = self.client.post(f"/api/projects/{self.identity}/samples/{sample['id']}/delete",
                                   headers=self.headers)
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["deleted"], sample["id"])
        self.assertEqual(self.client.get(f"/api/projects/{self.identity}/style-profile").json()["samples"], [])

    def test_invalid_strength_is_rejected(self):
        response = self.client.put(f"/api/projects/{self.identity}/style-profile",
                                   json={"strength": 200}, headers=self.headers)
        self.assertGreaterEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
