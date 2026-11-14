"""伏笔与连续性接口：隔离项目，不调用模型。"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module
from integration import continuity, memory_library

BODY = "林舟在码头等到黄昏。\n\n他把怀表停在七点二十。\n"


class ContinuityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-continuity-api-")
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

    def _foreshadow(self):
        doc = memory_library.save_item(self.project, {"category": "foreshadow", "title": "怀表的秘密",
                                                     "content": "七点二十并不普通。", "pinned": False,
                                                     "status": "active", "due_chapter": 3,
                                                     "clue_state": "planned", "source_chapter": 0},
                                       memory_library.read(self.project)["revision"])
        return next(x for x in doc["items"] if x["title"] == "怀表的秘密")

    def test_view_and_transition(self):
        item = self._foreshadow()
        view = self.client.get(f"/api/projects/{self.identity}/continuity?chapter=2").json()
        self.assertEqual(view["count"], 1)
        self.assertEqual(view["foreshadows"][0]["state"], "planned")
        revision = memory_library.read(self.project)["revision"]
        blocked = self.client.post(f"/api/projects/{self.identity}/foreshadow/{item['id']}/transition",
                                   json={"revision": revision, "state": "planted", "chapter": 1,
                                         "quote": "他把怀表停在七点二十。", "sha256": self.sha})
        self.assertEqual(blocked.status_code, 403)
        saved = self.client.post(f"/api/projects/{self.identity}/foreshadow/{item['id']}/transition",
                                 json={"revision": revision, "state": "planted", "chapter": 1,
                                       "event": "怀表首次出现", "quote": "他把怀表停在七点二十。",
                                       "sha256": self.sha}, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["state"], "planted")

    def test_index_and_rebuild_routes(self):
        self.assertEqual(self.client.post(f"/api/projects/{self.identity}/continuity/index",
                                          headers=self.headers).json()["chapters"], 1)
        rebuilt = self.client.post(f"/api/projects/{self.identity}/continuity/rebuild?chapter=1", headers=self.headers)
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        self.assertFalse(rebuilt.json()["needs_review"])

    def test_stale_evidence_blocks_advance(self):
        item = self._foreshadow()
        revision = memory_library.read(self.project)["revision"]
        (self.project / "正文" / "第1章-测试.md").write_text(BODY + "\n改写。\n", encoding="utf-8", newline="\n")
        response = self.client.post(f"/api/projects/{self.identity}/foreshadow/{item['id']}/transition",
                                    json={"revision": revision, "state": "planted", "chapter": 1,
                                          "quote": "他把怀表停在七点二十。", "sha256": self.sha},
                                    headers=self.headers)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertIn("不一致", response.text)


if __name__ == "__main__":
    unittest.main()
