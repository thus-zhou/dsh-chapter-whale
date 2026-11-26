"""v0.8.2/v0.8.5 API：批注与主编室。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module


class V085ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-v085-api-")
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
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "v085"}),
                                                               encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)},
                                    headers=self.headers)
        self.identity = response.json()["id"]
        created = self.client.post(f"/api/projects/{self.identity}/chapters",
                                   json={"chapter": 1, "title": "开端",
                                         "content": "她推开门。\n\n屋里很冷。\n"},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_chapter_scope_annotation_lifecycle(self):
        base = f"/api/projects/{self.identity}/chapters/1/annotations"
        created = self.client.post(base, json={"scope": "chapter",
                                               "instruction": "前半章太慢，合并两场问话"},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)
        annotation_id = created.json()["id"]
        listing = self.client.get(base)
        self.assertEqual(listing.json()["annotations"][0]["id"], annotation_id)
        updated = self.client.patch(base + f"/{annotation_id}",
                                    json={"status": "rejected"}, headers=self.headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        deleted = self.client.delete(base + f"/{annotation_id}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_chief_message_directive_and_route(self):
        base = f"/api/projects/{self.identity}/chief"
        message = self.client.post(base + "/messages",
                                   json={"session_id": "author", "text": "今天写两章"},
                                   headers=self.headers)
        self.assertEqual(message.status_code, 200, message.text)
        self.assertEqual(message.json()["channel"], "chief_chat")
        snapshot = self.client.get(base)
        self.assertGreaterEqual(snapshot.json()["snapshot_seq"], 1)
        directive = self.client.post(base + "/directives",
                                     json={"title": "今日", "instruction": "写两章",
                                           "autonomy": "step_confirm"},
                                     headers=self.headers)
        self.assertEqual(directive.status_code, 200, directive.text)
        self.assertTrue(directive.json()["id"].startswith("dir_"))
        route = self.client.post(base + "/route", json={"message": "列出所有角色"},
                                 headers=self.headers)
        self.assertEqual(route.status_code, 200, route.text)
        self.assertIn("level", route.json())


if __name__ == "__main__":
    unittest.main()
