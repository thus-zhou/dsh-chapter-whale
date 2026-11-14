"""事实来源接口：隔离项目，不触发模型调用。"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module
from integration import memory_library

BODY = "林舟在码头等到黄昏。\n\n他把怀表停在七点二十。\n"


class MemoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-memory-api-")
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
        self.reviewed = patch.object(memory_library.writer, "reviewed_chapters", return_value={1: {}})
        self.reviewed.start()

    def tearDown(self):
        self.reviewed.stop()
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _seed_fact(self):
        review = {"fact_candidates": [{"title": "林舟：怀表", "content": "怀表停在七点二十。",
                                       "quote": "怀表停在七点二十。"}]}
        memory_library.save_candidates(self.project, 1, review, self.sha)
        memory_library.commit_candidates(self.project, 1, self.sha)
        return next(x for x in memory_library.read(self.project)["items"] if x["source"]["kind"] == "chapter")

    def test_state_view_hides_future_content(self):
        self._seed_fact()
        item = memory_library.read(self.project)["items"][0]
        item["valid_from"] = 9
        doc = memory_library.read(self.project)
        doc["items"][0]["valid_from"] = 9
        from integration import bridge
        bridge.write_json_atomic(memory_library._path(self.project), doc)
        view = self.client.get(f"/api/projects/{self.identity}/memory/state?chapter=3").json()
        self.assertEqual(view["active"], [])
        self.assertEqual(view["future"][0]["valid_from"], 9)
        self.assertNotIn("content", view["future"][0])

    def test_author_correction_creates_new_record(self):
        old = self._seed_fact()
        revision = memory_library.read(self.project)["revision"]
        response = self.client.put(
            f"/api/projects/{self.identity}/memory/items/{old['id']}/correct",
            json={"revision": revision, "category": "fact", "title": "林舟：怀表", "content": "怀表停在七点二十五。",
                  "pinned": False, "status": "active", "source_chapter": 0, "due_chapter": 0,
                  "clue_state": "planned", "valid_to": 0, "story_time": "", "reason": "作者核对原稿"},
            headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        items = {x["id"]: x for x in response.json()["items"]}
        self.assertEqual(items[old["id"]]["status"], "superseded")
        self.assertEqual(items[old["id"]]["source"]["quote"], "怀表停在七点二十。")
        new = items[items[old["id"]]["superseded_by"]]
        self.assertEqual(new["claim"], "author_setting")
        self.assertEqual(new["correction_reason"], "作者核对原稿")

    def test_commit_endpoint_and_write_guard(self):
        review = {"fact_candidates": [{"title": "林舟：怀表", "content": "怀表停在七点二十。",
                                       "quote": "怀表停在七点二十。"}]}
        memory_library.save_candidates(self.project, 1, review, self.sha)
        blocked = self.client.post(f"/api/projects/{self.identity}/memory/candidates/1/commit")
        self.assertEqual(blocked.status_code, 403)
        response = self.client.post(f"/api/projects/{self.identity}/memory/candidates/1/commit", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["added"], 1)
        again = self.client.post(f"/api/projects/{self.identity}/memory/candidates/1/commit", headers=self.headers)
        self.assertEqual(again.json()["status"], "reused")


if __name__ == "__main__":
    unittest.main()
