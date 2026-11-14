"""质量报告只读接口：隔离目录，不发模型调用。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module

from integration import quality_gate
from integration.chapter_versions import file_sha256


def review_payload(scores=None):
    return {"success": True, "review_decision": "pass", "needs_revision": False, "raw_review": "结论：无需修改",
            "quality": {"format": "json", "verdict": "pass", "summary": "节奏稳",
                        "scores": scores or {"setting": 90, "plot": 90, "character": 90,
                                             "prose": 90, "dialogue": 90, "style": 90},
                        "issues": [], "not_applicable": []}}


class QualityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-quality-api-")
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
        self.body = self.project / "正文" / "第1章-开局.md"
        self.body.write_text("第一章正文。\n", encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_quality_view_reports_scores_and_expiry(self):
        quality_gate.save_report(self.project, 1, review_payload(), body_sha256=file_sha256(self.body))
        response = self.client.get(f"/api/projects/{self.identity}/chapters/1/quality")
        self.assertEqual(response.status_code, 200, response.text)
        view = response.json()
        self.assertTrue(view["report"]["quality_pass"])
        self.assertEqual(view["report"]["total"], 90.0)
        self.assertTrue(view["status"]["valid"])

        self.body.write_text("第一章正文，已经改过。\n", encoding="utf-8")
        changed = self.client.get(f"/api/projects/{self.identity}/chapters/1/quality").json()
        self.assertEqual(changed["status"]["stale_reason"], "body_changed")

    def test_missing_report_is_not_reported_as_pass(self):
        view = self.client.get(f"/api/projects/{self.identity}/chapters/9/quality").json()
        self.assertIsNone(view["report"])
        self.assertEqual(view["status"]["stale_reason"], "no_report")

    def test_invalid_chapter_number_is_rejected(self):
        response = self.client.get(f"/api/projects/{self.identity}/chapters/0/quality")
        self.assertGreaterEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
