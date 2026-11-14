"""创作流程接口：隔离目录，不发模型调用。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module


class WorkflowApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-workflow-api-")
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
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "流程测试"}), encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_empty_project_reports_the_idea_step(self):
        response = self.client.get(f"/api/projects/{self.identity}/workflow", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state["next"], "idea")
        self.assertEqual([step["id"] for step in state["steps"]],
                         ["idea", "essentials", "direction", "samples", "writing", "results"])
        self.assertTrue(all(step["action"]["page"] for step in state["steps"]))

    def test_progress_reflects_brief_plan_and_chapter(self):
        (self.project / ".webnovel" / "creative_brief.json").write_text(json.dumps(
            {"brief": {"genre": "悬疑", "premise": "失忆者记得死者", "style": "冷硬短句"}}, ensure_ascii=False),
            encoding="utf-8", newline="\n")
        (self.project / ".webnovel" / "story_plan.json").write_text(json.dumps(
            {"chapters": [{"id": 1, "outline": "开端"}]}, ensure_ascii=False), encoding="utf-8", newline="\n")
        (self.project / "正文" / "第1章-开局.md").write_text("正文" * 100, encoding="utf-8", newline="\n")
        state = self.client.get(f"/api/projects/{self.identity}/workflow", headers=self.headers).json()
        done = {step["id"] for step in state["steps"] if step["done"]}
        self.assertTrue({"idea", "essentials", "direction", "writing"} <= done)
        self.assertEqual(state["next"], "results")
        self.assertEqual(state["counts"]["chapters"], 1)

    def test_chapter_detail_reports_words_and_review_state(self):
        body = "第一章正文，含标点与空白。\n"
        (self.project / "正文" / "第1章-开局.md").write_text(body, encoding="utf-8", newline="\n")
        response = self.client.get(f"/api/projects/{self.identity}/chapters/1", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["words"], len([c for c in body if not c.isspace()]))
        self.assertIn("reviewed", data)
        self.assertIn("review_status", data)
        self.assertFalse(data["reviewed"])

    def test_unknown_project_is_404(self):
        response = self.client.get("/api/projects/ffffff/workflow", headers=self.headers)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
