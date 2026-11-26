"""v0.9 API：世界状态、并发队列、质量体检与诊断。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module


class V09ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-v09-api-")
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
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "v09"}),
                                                               encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]
        created = self.client.post(f"/api/projects/{self.identity}/chapters",
                                   json={"chapter": 1, "title": "开端",
                                         "content": "第一段。\n“你来了。”\n" * 10},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_world_state_and_context(self):
        base = f"/api/projects/{self.identity}/world"
        saved = self.client.post(base + "/facts", json={
            "fact_id": "f1", "entity_id": "ent_1", "domain": "character",
            "subject": "林溪", "predicate": "身份", "object": "测绘员",
            "valid_from_chapter": 1, "authority_level": "author_locked",
            "confidence": 1.0, "pinned": True}, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        facts = self.client.get(base + "/facts?chapter=1")
        self.assertEqual(facts.json()["facts"][0]["object"], "测绘员")
        card = self.client.post(base + "/cards", json={"entity_id": "ent_1", "name": "林溪",
                                                       "pinned": True, "card_md": "女主"},
                                headers=self.headers)
        self.assertEqual(card.status_code, 200, card.text)
        context = self.client.get(base + "/context?chapter=1&q=测绘员")
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(context.json()["manifest"]["chapter_id"], 1)

    def test_task_queue_roundtrip_and_pause(self):
        base = f"/api/projects/{self.identity}/tasks"
        task = self.client.post(base, json={"priority": "P1", "payload": {"kind": "daily"}},
                                headers=self.headers)
        self.assertEqual(task.status_code, 200, task.text)
        task_id = task.json()["task_id"]
        claimed = self.client.post(base + "/claim", json={"owner": "w", "max_slots": 2},
                                   headers=self.headers)
        self.assertEqual(claimed.json()["task"]["task_id"], task_id)
        completed = self.client.post(base + f"/{task_id}/complete", json={"owner": "w"},
                                     headers=self.headers)
        self.assertEqual(completed.json()["state"], "completed")
        paused = self.client.post(base + "/pause", json={"scope": "global"},
                                  headers=self.headers)
        self.assertEqual(paused.json()["status"], "paused")
        resumed = self.client.post(base + "/resume", json={"scope": "global"},
                                   headers=self.headers)
        self.assertEqual(resumed.json()["status"], "resumed")

    def test_quality_limit_and_dashboard(self):
        base = f"/api/projects/{self.identity}/quality"
        first = self.client.post(base + "/1/review", json={}, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.client.post(base + "/1/review", json={}, headers=self.headers)
        third = self.client.post(base + "/1/review", json={}, headers=self.headers)
        self.assertEqual(third.status_code, 409, third.text)
        self.assertEqual(third.json()["code"], "auto_review_limit")
        board = self.client.get(base)
        self.assertEqual(set(board.json()["averages"]),
                         {"plot", "character", "prose", "continuity", "pacing", "commercial"})

    def test_diagnostics_export_and_gc(self):
        base = f"/api/projects/{self.identity}/diagnostics"
        health = self.client.get(base)
        self.assertIn(health.json()["status"], {"ok", "degraded"})
        ledger = self.client.get(f"/api/projects/{self.identity}/ledger")
        self.assertIn("settled", ledger.json()["states"])
        gc = self.client.post(base + "/gc", json={"dry_run": True}, headers=self.headers)
        self.assertEqual(gc.json()["status"], "dry_run")
        destination = self.root / "diagnostics" / "bundle.zip"
        exported = self.client.post(base + "/export",
                                    json={"destination": str(destination)}, headers=self.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertTrue(destination.is_file())


if __name__ == "__main__":
    unittest.main()
