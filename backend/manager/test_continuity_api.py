"""0.7.0 接口：实体、文风预检、检索 trace、证据影响清单。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from manager import app as module
from integration import bridge, chapter_versions, memory_library, scheduler, writer_runner

BODY = (
    "他推开门，屋里没人。\n\n"
    "总之，这一天过得很不寻常。\n\n"
    "他把外套挂好，坐下。\n\n"
    "总之，这一天过得很不寻常，也很漫长。\n"
)


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


class ContinuityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="continuity-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text('{"title":"测试作品"}', encoding="utf-8")
        self.ai_path = self.root / "ai.json"
        self.ai_path.write_text(json.dumps({"base_url": "https://fixture.invalid/v1", "model": "m",
                                            "api_key": "NOT-A-REAL-KEY"}), encoding="utf-8")
        self.patches = [
            patch.object(module, "DATA", self.root),
            patch.object(module, "AI_PATH", self.ai_path),
            patch.object(module.secret_store, "codec", lambda: fake_pair()),
            patch.object(scheduler, "SCHEDULER_PATH", self.root / "scheduler.json"),
            patch.object(scheduler, "RUNS_ROOT", self.root / "runs"),
            patch.object(bridge, "COMBINED_ROOT", self.root),
            patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"),
            patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.data)}),
            patch.object(writer_runner, "reviewed_chapters", return_value={1: {"sha256": "a" * 64}}),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        module._AI_MIGRATION_TRIED = False
        for chapter in (1, 3):
            chapter_versions.write_chapter(self.project, chapter, BODY, op_id=f"op-{chapter}",
                                           title=f"第{chapter}日", allow_new=True)
        self.client = TestClient(module.create_app(self.root / "manager.db", start_dispatcher=False))
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        registered = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.identity = registered.json().get("id") or registered.json().get("identity")

    def get(self, path, **params):
        return self.client.get(f"/api/projects/{self.identity}{path}", params=params, headers=self.headers)

    # --- 文风预检 -------------------------------------------------------------
    def test_precheck_lists_findings_with_rule_ids(self):
        response = self.get("/precheck", chapter=1)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("style.dup_summary", [row["rule_id"] for row in body["findings"]])
        self.assertTrue(body["rules"])
        self.assertTrue(any(rule["advisory"] is False for rule in body["rules"]))

    def test_precheck_unknown_chapter_is_404(self):
        response = self.get("/precheck", chapter=99)
        self.assertEqual(response.status_code, 404)

    def test_ignore_terms_suppress_findings(self):
        saved = self.client.put(f"/api/projects/{self.identity}/precheck/ignore",
                                json={"terms": ["总之"]}, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["terms"], ["总之"])
        body = self.get("/precheck", chapter=1).json()
        self.assertNotIn("style.dup_summary", [row["rule_id"] for row in body["findings"]])
        self.assertGreaterEqual(body["ignored"], 1)
        self.assertEqual(body["ignore_terms"], ["总之"])

    def test_ignore_terms_reject_oversized_input(self):
        response = self.client.put(f"/api/projects/{self.identity}/precheck/ignore",
                                   json={"terms": ["字" * 41]}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_style_action_is_counted(self):
        response = self.client.post(f"/api/projects/{self.identity}/precheck/action",
                                    json={"rule_id": "style.dup_summary", "action": "accepted",
                                          "note": "已合并"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["action"], "accepted")
        metrics = self.get("/precheck", chapter=1).json()["metrics"]
        self.assertEqual(metrics["accepted"], 1)

    def test_style_action_rejects_unknown_rule(self):
        response = self.client.post(f"/api/projects/{self.identity}/precheck/action",
                                    json={"rule_id": "style.unknown", "action": "accepted"}, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    # --- 实体 -----------------------------------------------------------------
    def test_entities_view_is_empty_before_any_record(self):
        response = self.get("/entities", chapter=3)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json().get("items"), [])

    def sha(self, chapter):
        return chapter_versions.file_sha256(chapter_versions.chapter_path(self.project, chapter))

    # --- 检索 -----------------------------------------------------------------
    def test_retrieval_returns_plan_and_report(self):
        doc = memory_library.read(self.project)
        memory_library.save_item(self.project, {"category": "canon", "title": "开门的细节", "content": "他推开门，屋里没人"},
                                 doc["revision"],
                                 source={"kind": "chapter", "chapter": 1, "sha256": self.sha(1),
                                         "quote": "他推开门，屋里没人"})
        response = self.get("/retrieval", chapter=3, query="开门")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["plan"]["supplied"])
        self.assertIn("plans", body["report"])
        self.assertFalse(body["ready"])

    def test_retrieval_rejects_bad_chapter(self):
        response = self.get("/retrieval", chapter=0)
        self.assertEqual(response.status_code, 400)

    # --- 证据影响 -------------------------------------------------------------
    def test_evidence_impact_lists_affected_facts(self):
        doc = memory_library.read(self.project)
        memory_library.save_item(self.project, {"category": "canon", "title": "旧设定", "content": "钥匙在林砚手里"},
                                 doc["revision"],
                                 source={"kind": "chapter", "chapter": 3, "sha256": self.sha(3), "quote": "钥匙"})
        response = self.get("/evidence/impact", chapter=3)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["chapter"], 3)
        self.assertEqual(len(body["affected"]), 1)
        self.assertIn("coverage", body)


if __name__ == "__main__":
    unittest.main()
