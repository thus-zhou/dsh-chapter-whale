"""版本历史与恢复接口：隔离目录，不发模型调用。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module

from integration import chapter_versions, quality_gate


def review_payload(scores=None):
    return {"success": True, "review_decision": "pass", "needs_revision": False, "raw_review": "结论：无需修改",
            "quality": {"format": "json", "verdict": "pass", "summary": "稳",
                        "scores": scores or {"setting": 90, "plot": 90, "character": 90,
                                             "prose": 90, "dialogue": 90, "style": 90},
                        "issues": [], "not_applicable": []}}


class HistoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-history-api-")
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
        self.path = self.project / "正文" / "第1章-开局.md"
        self.path.write_text("第一版正文。\n", encoding="utf-8")
        chapter_versions.write_chapter(self.project, 1, "第一版正文。\n", op_id="op-a", allow_new=True)
        chapter_versions.write_chapter(self.project, 1, "第二版正文，多了一句。\n", op_id="op-b")
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_workbench_lists_versions_without_body(self):
        response = self.client.get(f"/api/projects/{self.identity}/chapters/1/workbench")
        self.assertEqual(response.status_code, 200, response.text)
        view = response.json()
        self.assertEqual(view["chapter_id"], 1)
        self.assertEqual([row["seq"] for row in view["history"]["versions"]], [2, 1])
        self.assertTrue(view["history"]["versions"][0]["current"])
        self.assertIn("note", view["best"])
        self.assertNotIn("第一版正文", json.dumps(view, ensure_ascii=False))

    def test_version_body_is_read_on_demand(self):
        listing = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions").json()
        oldest = listing["versions"][1]["version_id"]
        body = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions/{oldest}")
        self.assertEqual(body.status_code, 200, body.text)
        self.assertEqual(body.json()["body"].replace("\r\n", "\n"), "第一版正文。\n")
        self.assertEqual(self.client.get(f"/api/projects/{self.identity}/chapters/1/versions/not-a-hash").status_code, 400)

    def test_restore_endpoint_writes_a_new_version(self):
        listing = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions").json()
        oldest = listing["versions"][1]["version_id"]
        response = self.client.post(f"/api/projects/{self.identity}/chapters/1/restore",
                                    json={"version_id": oldest}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "restored")
        self.assertEqual(self.path.read_text(encoding="utf-8").replace("\r\n", "\n"), "第一版正文。\n")
        after = self.client.get(f"/api/projects/{self.identity}/chapters/1/versions").json()
        self.assertEqual(after["versions"][0]["source"], "restored")

    def test_workbench_reports_the_bound_quality_result(self):
        from fanqie_auto_publish.publication_safety import body_digest
        quality_gate.save_report(self.project, 1, review_payload(), body_sha256=body_digest("第二版正文，多了一句。\n"))
        view = self.client.get(f"/api/projects/{self.identity}/chapters/1/workbench").json()
        self.assertTrue(view["report"]["report"]["quality_pass"])
        self.assertTrue(view["report"]["status"]["valid"])
        self.assertEqual(view["history"]["versions"][0]["quality"]["pass"], True)


if __name__ == "__main__":
    unittest.main()
