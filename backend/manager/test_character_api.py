"""人物接口：隔离项目，不调用模型。"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module
from integration import character_state

BODY = "林舟在码头等到黄昏。\n\n沈青说：“怀表停在七点二十。”\n"


class CharacterApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-character-api-")
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
        (self.project / "正文" / "第1章-测试.md").write_text(BODY, encoding="utf-8", newline="\n")
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "隔离测试"}), encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]
        self.sha = hashlib.sha256((self.project / "正文" / "第1章-测试.md").read_bytes()).hexdigest()
        self.reviewed = patch.object(character_state.writer, "reviewed_chapters", return_value={1: {}})
        self.reviewed.start()

    def tearDown(self):
        self.reviewed.stop()
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_people_and_correction(self):
        added = self.client.post(f"/api/projects/{self.identity}/characters",
                                 json={"name": "林舟", "aliases": ["阿舟"], "identity": "码头工人"},
                                 headers=self.headers)
        self.assertEqual(added.status_code, 200, added.text)
        person = added.json()["person"]
        duplicate = self.client.post(f"/api/projects/{self.identity}/characters",
                                     json={"name": "林舟", "aliases": ["舟哥"]}, headers=self.headers)
        self.assertEqual(duplicate.json()["person"]["id"], person["id"])
        blocked = self.client.put(f"/api/projects/{self.identity}/characters/{person['id']}/correct",
                                  json={"field": "goal", "value": "复仇", "reason": "作者设定"})
        self.assertEqual(blocked.status_code, 403)
        corrected = self.client.put(f"/api/projects/{self.identity}/characters/{person['id']}/correct",
                                    json={"field": "goal", "value": "找回妹妹", "reason": "作者设定"},
                                    headers=self.headers)
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()["profile"]["goal"], "找回妹妹")
        view = self.client.get(f"/api/projects/{self.identity}/characters?chapter=2").json()
        self.assertEqual(view["count"], 1)
        self.assertEqual(sorted(view["persons"][0]["aliases"]), ["舟哥", "阿舟"])

    def test_candidate_commit_route(self):
        self.client.post(f"/api/projects/{self.identity}/characters", json={"name": "沈青"}, headers=self.headers)
        review = {"character_candidates": [{"kind": "knowledge", "person": "沈青", "info": "怀表停在七点二十",
                                            "event": "看到怀表", "quote": "怀表停在七点二十。",
                                            "scope": "character", "status": "confirmed"}]}
        character_state.save_candidates(self.project, 1, review, self.sha)
        first = self.client.post(f"/api/projects/{self.identity}/characters/candidates/1/commit", headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["added"]["knowledge"], 1)
        again = self.client.post(f"/api/projects/{self.identity}/characters/candidates/1/commit", headers=self.headers)
        self.assertEqual(again.json()["status"], "reused")

    def test_invalid_chapter_and_field(self):
        added = self.client.post(f"/api/projects/{self.identity}/characters", json={"name": "林舟"},
                                 headers=self.headers).json()["person"]
        bad = self.client.put(f"/api/projects/{self.identity}/characters/{added['id']}/correct",
                              json={"field": "age", "value": "30"}, headers=self.headers)
        self.assertGreaterEqual(bad.status_code, 400)
        ch = self.client.post(f"/api/projects/{self.identity}/characters/candidates/0/commit", headers=self.headers)
        self.assertGreaterEqual(ch.status_code, 400)


if __name__ == "__main__":
    unittest.main()
