"""v0.9 API：世界状态、并发队列、质量体检与诊断。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module
from integration import concurrent_engine


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

    def test_confirm_endpoint_raises_authority(self):
        """审计 C-01：确认接口必须 200 且把 ai_inferred 提升为 confirmed_prose。"""
        base = f"/api/projects/{self.identity}/world"
        created = self.client.post(base + "/facts", json={
            "fact_id": "pending_1", "entity_id": "ent_2", "domain": "character",
            "subject": "老周", "predicate": "死亡", "object": "死亡",
            "authority_level": "ai_inferred", "confidence": 0.9,
            "status": "pending_confirm"}, headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)
        confirmed = self.client.post(base + "/facts/pending_1/confirm",
                                     json={"authority_level": "confirmed_prose"},
                                     headers=self.headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "active")
        self.assertEqual(confirmed.json()["authority_level"], "confirmed_prose")
        again = self.client.post(base + "/facts/pending_1/confirm", json={},
                                 headers=self.headers)
        self.assertEqual(again.status_code, 409, again.text)
        self.assertEqual(again.json()["code"], "fact_not_pending")

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
        judgments = [{"scores": {"plot": 80, "character": 80, "prose": 80,
                                  "continuity": 80, "pacing": 80, "commercial": 80}}]
        first = self.client.post(base + "/1/review", json={"judgments": judgments}, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.client.post(base + "/1/review", json={"judgments": judgments}, headers=self.headers)
        third = self.client.post(base + "/1/review", json={"judgments": judgments}, headers=self.headers)
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
        # 审计 C-14：客户端 destination 被忽略，导出只能落在 data_dir/diagnostics。
        outside = self.root / "outside" / "evil.zip"
        exported = self.client.post(base + "/export",
                                    json={"destination": str(outside)}, headers=self.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        written = Path(exported.json()["path"])
        self.assertFalse(outside.exists())
        self.assertTrue(written.is_file())
        self.assertEqual(written.parent.resolve(), (self.root / "diagnostics").resolve())

    def test_unknown_owner_and_blocked_by_are_rejected(self):
        base = f"/api/projects/{self.identity}/tasks"
        # 审计 C-35：claim/complete 都必须显式 owner，不能靠不一致的缺省值。
        claim = self.client.post(base + "/claim", json={}, headers=self.headers)
        self.assertEqual(claim.status_code, 422, claim.text)
        self.assertEqual(claim.json()["code"], "owner_required")
        task = self.client.post(base, json={"task_id": "t_blocked",
                                            "blocked_by": "abc"}, headers=self.headers)
        self.assertEqual(task.status_code, 422, task.text)
        self.assertEqual(task.json()["code"], "invalid_blocked_by")
        bad_payload = self.client.post(base, json={"payload": "text"}, headers=self.headers)
        self.assertEqual(bad_payload.status_code, 422, bad_payload.text)
        self.client.post(base, json={"task_id": "t_owner", "priority": "P1"}, headers=self.headers)
        claimed = self.client.post(base + "/claim", json={"owner": "w"}, headers=self.headers)
        self.assertEqual(claimed.json()["task"]["task_id"], "t_owner")
        missing = self.client.post(base + "/t_owner/complete", json={}, headers=self.headers)
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(missing.json()["code"], "owner_required")

    def test_unknown_recover_action_is_rejected(self):
        # 审计 C-31：未知 action 不能静默返回 200 ok。
        response = self.client.post("/api/system/diagnostics/recover",
                                    json={"identity": self.identity, "action": "whatever"},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["code"], "unsupported_action")

    def test_global_pause_blocks_v09_claim(self):
        # 审计 C-09/C-39：急停文件按应用实例传入 claim。
        pause = self.client.post("/api/system/ai/pause", json={"paused": True},
                                 headers=self.headers)
        self.assertEqual(pause.status_code, 200, pause.text)
        base = f"/api/projects/{self.identity}/tasks"
        self.client.post(base, json={"task_id": "t_pause", "priority": "P1"}, headers=self.headers)
        claimed = self.client.post(base + "/claim", json={"owner": "w"}, headers=self.headers)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertIsNone(claimed.json()["task"])
        self.client.post("/api/system/ai/pause", json={"paused": False}, headers=self.headers)
        self.assertEqual(self.client.post(base + "/claim", json={"owner": "w"},
                                          headers=self.headers).json()["task"]["task_id"],
                         "t_pause")

    def test_operations_start_is_blocked_by_global_pause(self):
        # 审计 C-09：v0.8 ops 入口（日更/生成）也必须看全站急停。
        (self.root / "global_pause.json").write_text(json.dumps({"paused": True}),
                                                    encoding="utf-8")
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self.client.app.state.operations.start(
                "generate", ["run", "--project", str(self.project)], "op:pause")
        self.assertEqual(caught.exception.status_code, 503)

    def test_internal_events_notify_route(self):
        # 审计 C-47：LoopbackNotifier 的 /internal/events/notify 曾不存在。
        with patch.dict("os.environ", {"CHAPTER_WHALE_INTERNAL_TOKEN": "internal-token"}):
            denied = self.client.post("/internal/events/notify", json={"kind": "wake"})
            self.assertEqual(denied.status_code, 403, denied.text)
            accepted = self.client.post("/internal/events/notify", json={"kind": "wake"},
                                        headers={"X-Internal-Token": "internal-token"})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertTrue(accepted.json()["ok"])


class LifespanTests(unittest.TestCase):
    """审计 C-38：start_dispatcher=False 时不得启动通知投递。"""

    def test_install_does_not_overwrite_a_process_global_pause_file(self):
        """审计 C-39：多次 create_app 不能把暂停路径写成模块级全局。"""
        previous = concurrent_engine._GLOBAL_PAUSE_PATH
        with tempfile.TemporaryDirectory(prefix="novel-v09-pause-a-") as first, \
                tempfile.TemporaryDirectory(prefix="novel-v09-pause-b-") as second:
            for folder in (first, second):
                root = Path(folder)
                with patch.object(module, "DATA", root), \
                        patch.object(module, "AI_PATH", root / "ai.json"):
                    module.create_app(root / "manager.db", start_dispatcher=False)
        self.assertIs(concurrent_engine._GLOBAL_PAUSE_PATH, previous)

    def test_disabled_dispatcher_starts_no_background_tasks(self):
        import time as time_module
        with tempfile.TemporaryDirectory(prefix="novel-v09-lifespan-") as folder:
            root = Path(folder)
            with patch.object(module, "DATA", root), \
                    patch.object(module, "AI_PATH", root / "ai.json"), \
                    patch.object(module, "NOTIFY_INTERVAL_SECONDS", 0.01), \
                    patch.object(module, "_deliver_notifications_once") as deliver:
                app = module.create_app(root / "manager.db", start_dispatcher=False)
                with TestClient(app):
                    time_module.sleep(0.15)
                self.assertEqual(deliver.call_count, 0)


if __name__ == "__main__":
    unittest.main()
