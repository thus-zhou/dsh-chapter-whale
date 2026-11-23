"""管理接口契约：稳定操作键只派发一次，运行记录端点只读。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from manager import app as module
from integration import bridge, scheduler


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


class JobsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobs-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text('{"title":"测试作品"}', encoding="utf-8")
        self.ai_path = self.root / "ai.json"
        self.ai_path.write_text(json.dumps({"base_url": "https://fixture.invalid/v1", "model": "m",
                                            "api_key": "NOT-A-REAL-KEY"}), encoding="utf-8")
        self.scheduler_path = self.root / "scheduler.json"
        self.runs_root = self.root / "runs"
        self.patches = [
            patch.object(module, "DATA", self.root),
            patch.object(module, "AI_PATH", self.ai_path),
            patch.object(module.secret_store, "codec", lambda: fake_pair()),
            patch.object(scheduler, "SCHEDULER_PATH", self.scheduler_path),
            patch.object(scheduler, "RUNS_ROOT", self.runs_root),
            patch.object(bridge, "COMBINED_ROOT", self.root),
            patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"),
            patch.object(module.Operations, "_execute", lambda self, identity, args: None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        module._AI_MIGRATION_TRIED = False
        self.app = module.create_app(self.root / "manager.db", start_dispatcher=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}

    def register(self) -> str:
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _job(self) -> dict:
        return {"name": "日更", "project": str(self.project), "book": "潮汐钟", "account": "",
                "daily_time": "08:00", "timezone": "Asia/Shanghai", "chapters_per_run": 2,
                "word_count": 3000, "max_revisions": 1, "enabled": True, "approval_mode": "unattended",
                "delivery_mode": "serial", "publication_mode": "draft_only"}

    def _write_scheduler(self) -> None:
        self.scheduler_path.write_text(json.dumps({"version": 2, "revision": 0, "updated_at": "",
                                                   "jobs": {"daily": self._job()}}, ensure_ascii=False),
                                       encoding="utf-8")

    # --- 稳定操作键 -------------------------------------------------------
    def test_same_operation_key_returns_the_same_generation_operation(self):
        identity = self.register()
        body = {"word_count": 3000, "max_revisions": 1, "count": 1, "scenes": 0,
                "operation_key": "trial-20261116-abcdefgh"}
        first = self.client.post(f"/api/projects/{identity}/generate", json=body, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(f"/api/projects/{identity}/generate", json=body, headers=self.headers)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertTrue(second.json().get("deduplicated"))
        operations = [item for item in module.Store(self.root / "manager.db").operations()
                      if item["kind"] == "generate"]
        self.assertEqual(len(operations), 1)

    def test_different_keys_create_separate_operations_and_bad_keys_are_rejected(self):
        identity = self.register()
        base = {"word_count": 3000, "max_revisions": 1, "count": 1, "scenes": 0}
        first = self.client.post(f"/api/projects/{identity}/generate",
                                 json={**base, "operation_key": "trial-key-0001"}, headers=self.headers).json()
        store = module.Store(self.root / "manager.db")
        finished = store.operation(first["id"])
        finished.update(status="succeeded", finished_at="2026-11-16T00:00:00+00:00")
        store.save_operation(finished)
        second = self.client.post(f"/api/projects/{identity}/generate",
                                  json={**base, "operation_key": "trial-key-0002"}, headers=self.headers).json()
        self.assertNotEqual(first["id"], second["id"])
        bad = self.client.post(f"/api/projects/{identity}/generate",
                               json={**base, "operation_key": "短"}, headers=self.headers)
        self.assertEqual(bad.status_code, 422, bad.text)

    def test_operation_key_survives_restart(self):
        identity = self.register()
        body = {"word_count": 3000, "max_revisions": 1, "count": 1, "scenes": 0,
                "operation_key": "trial-persisted-01"}
        first = self.client.post(f"/api/projects/{identity}/generate", json=body, headers=self.headers).json()
        restart = module.create_app(self.root / "manager.db", start_dispatcher=False)
        with TestClient(restart) as client:
            again = client.post(f"/api/projects/{identity}/generate", json=body, headers=self.headers)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["id"], first["id"])
        self.assertTrue(again.json().get("deduplicated"))

    # --- 运行记录只读投影 -------------------------------------------------
    def test_run_endpoints_are_read_only_and_404_for_unknown_jobs(self):
        self._write_scheduler()
        boom = AssertionError("只读端点不得执行任务")
        with patch.object(scheduler, "run_once", side_effect=boom), \
             patch.object(scheduler, "add_job", side_effect=boom), \
             patch.object(scheduler, "update_job", side_effect=boom):
            empty = self.client.get("/api/jobs/daily/runs", headers=self.headers)
            self.assertEqual(empty.status_code, 200, empty.text)
            self.assertEqual(empty.json(), [])
            self.assertEqual(self.client.get("/api/jobs/daily/runs/missing", headers=self.headers).status_code, 404)
            self.assertEqual(self.client.get("/api/jobs/unknown/runs", headers=self.headers).status_code, 404)
            folder = self.runs_root / bridge.safe_dir_name("daily")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "run-1.json").write_text(json.dumps({
                "project": str(self.project), "target_ids": [1], "status": "success",
                "started_at": "2026-11-16T00:00:00+00:00", "finished_at": "2026-11-16T00:05:00+00:00",
                "cycle": {"run_date": "2026-11-16", "slot": "08:00", "target_ids": [1],
                          "publication_mode": "draft_only"}}), encoding="utf-8")
            listing = self.client.get("/api/jobs/daily/runs", headers=self.headers)
            self.assertEqual([row["run_id"] for row in listing.json()], ["run-1"])
            detail = self.client.get("/api/jobs/daily/runs/run-1", headers=self.headers)
            self.assertEqual(detail.status_code, 200, detail.text)
            payload = detail.json()
            self.assertEqual(payload["publication_mode"], "draft_only")
            self.assertEqual(payload["remote_state"], "not_applicable")
            self.assertEqual(payload["tally"]["target"], 1)
            traversal = self.client.get("/api/jobs/daily/runs/%2e%2e%2fx", headers=self.headers)
            self.assertIn(traversal.status_code, {400, 404}, traversal.text)


if __name__ == "__main__":
    unittest.main()
