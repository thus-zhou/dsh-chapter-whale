"""0.9.4 接口：单目标浏览器、登录状态、只读核验与真实投递的授权闸门。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from manager import app as module
from integration import bridge, browser_target, scheduler, writer_runner

TARGET = {"os": "windows", "arch": "amd64", "runtime": "native",
          "browser": "chromium", "browser_version": "131.0", "driver": "playwright",
          "credential": "reconfigured", "scope": "read_only"}


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


class FakeBrowser:
    def __init__(self):
        self.calls = []
        self.closed = False

    def launch(self, **kwargs):
        self.calls.append(("launch", kwargs))
        return {"started": True}

    def health(self):
        return {"ok": True}

    def close(self):
        self.closed = True
        return True

    def read_chapter(self, *, book_id, chapter):
        return {"platform": "fanqie", "account": "acc", "book_id": book_id,
                "chapter_id": chapter, "content_sha256": "c" * 64}

    def publish_chapter(self, **kwargs):
        self.calls.append(("publish", kwargs))
        return {"accepted": True, "remote_id": "r-1"}


class BrowserApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="browser-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text('{"title":"测试作品"}', encoding="utf-8")
        self.ai_path = self.root / "ai.json"
        self.ai_path.write_text(json.dumps({"base_url": "https://fixture.invalid/v1",
                                            "model": "m", "api_key": "NOT-A-REAL-KEY"}),
                                encoding="utf-8")
        self.patches = [
            patch.object(module, "DATA", self.root),
            patch.object(module, "AI_PATH", self.ai_path),
            patch.object(module.secret_store, "codec", lambda: fake_pair()),
            patch.object(scheduler, "SCHEDULER_PATH", self.root / "scheduler.json"),
            patch.object(scheduler, "RUNS_ROOT", self.root / "runs"),
            patch.object(bridge, "COMBINED_ROOT", self.root),
            patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"),
            patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.data)}),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        module._AI_MIGRATION_TRIED = False
        browser_target.clear_adapter()
        self.addCleanup(browser_target.clear_adapter)
        self.client = TestClient(module.create_app(self.root / "manager.db", start_dispatcher=False))
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        registered = self.client.post("/api/projects", json={"path": str(self.project)},
                                      headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.identity = registered.json().get("id") or registered.json().get("identity")

    def get(self, path, **params):
        return self.client.get(f"/api/projects/{self.identity}{path}", params=params,
                               headers=self.headers)

    def post(self, path, payload=None):
        return self.client.post(f"/api/projects/{self.identity}{path}", json=payload or {},
                                headers=self.headers)

    def put(self, path, payload):
        return self.client.put(f"/api/projects/{self.identity}{path}", json=payload,
                               headers=self.headers)

    def save_target(self, **overrides):
        payload = dict(TARGET)
        payload.update(overrides)
        return self.put("/browser/target", payload)

    def test_target_roundtrip_and_validation(self):
        self.assertEqual(self.get("/browser/target").json(), {"target": {}})
        response = self.save_target()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["target"]["browser"], "chromium")
        self.assertEqual(self.get("/browser/target").json()["target"]["os"], "windows")
        broken = self.save_target()
        broken_payload = dict(TARGET)
        broken_payload.pop("driver")
        bad = self.put("/browser/target", broken_payload)
        self.assertEqual(bad.status_code, 422, bad.text)

    def test_publish_scope_without_authorization_is_rejected(self):
        response = self.save_target(scope="publish")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["code"], "invalid_target")
        self.assertIn("授权", response.json()["message"])
        ok = self.save_target(scope="publish", authorization="作者授权：书 A 第 3 章")
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_launch_without_adapter_is_a_conflict(self):
        self.save_target()
        response = self.post("/browser/launch")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "adapter_unavailable")
        self.assertFalse((self.project / ".webnovel" / "browser" / "journal.jsonl").exists())

    def test_launch_with_adapter_records_journal(self):
        self.save_target()
        browser = FakeBrowser()
        browser_target.register(browser)
        response = self.client.post(
            f"/api/projects/{self.identity}/browser/launch", params={"headless": "true"},
            headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["started"])
        self.assertTrue(browser.calls[0][1].get("headless"))
        journal = browser_target.read_journal(self.project)
        self.assertEqual(journal[-1]["kind"], "launch")

    def test_login_needs_evidence(self):
        bad = self.post("/browser/login", {"status": "valid"})
        self.assertEqual(bad.status_code, 400, bad.text)
        self.assertEqual(bad.json()["code"], "invalid_login")
        # 客户端无论如何都不能把登录标成 valid：valid/expired 只由适配器回读后写入
        spoofed = self.post("/browser/login", {"status": "valid", "account": "潮汐钟",
                                               "evidence": "a" * 64})
        self.assertEqual(spoofed.status_code, 400, spoofed.text)
        self.assertEqual(spoofed.json()["code"], "invalid_login")
        self.assertEqual(self.get("/browser/status").json()["login"]["status"], "unknown")
        browser_target.record_login(self.project, status="valid", account="潮汐钟",
                                    evidence="a" * 64, source="adapter")
        self.assertEqual(self.get("/browser/status").json()["login"]["status"], "valid")
        human = self.post("/browser/login", {"status": "needs_human", "reason": "扫码超时"})
        self.assertEqual(human.status_code, 200, human.text)
        self.assertEqual(human.json()["status"], "needs_human")

    def test_readonly_verification_reports_identity(self):
        self.save_target()
        browser_target.register(FakeBrowser())
        response = self.post("/browser/readonly", {"book_id": "b1", "chapter": 3})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "verified")
        self.assertEqual(body["writes"], 0)
        self.assertEqual(body["identity"]["chapter_id"], 3)

    def test_readonly_without_adapter_does_not_claim_verified(self):
        self.save_target()
        response = self.post("/browser/readonly", {"book_id": "b1", "chapter": 3})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertEqual(response.json()["writes"], 0)

    def test_publish_requires_scope_then_authorization_then_adapter(self):
        self.save_target()
        refused = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                                 "body_sha256": "d" * 64})
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(refused.json()["code"], "refused")
        self.save_target(scope="publish", authorization="作者授权")
        no_adapter = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                                    "body_sha256": "d" * 64})
        self.assertEqual(no_adapter.status_code, 409, no_adapter.text)
        self.assertEqual(no_adapter.json()["code"], "unavailable")
        browser_target.register(FakeBrowser())
        accepted = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                                  "body_sha256": "d" * 64})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["status"], "accepted")
        duplicate = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                                   "body_sha256": "d" * 64})
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()["status"], "duplicate")
        self.assertEqual(duplicate.json()["writes"], 0)

    def test_publish_reconcile_clears_blocked_chapter(self):
        self.save_target(scope="publish", authorization="作者授权：书 A 第 3 章")

        class Human(FakeBrowser):
            def publish_chapter(self, **kwargs):
                raise browser_target.AdapterNeedsHuman("扫码未完成")

        browser_target.register(Human())
        blocked = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                                 "body_sha256": "d" * 64})
        self.assertEqual(blocked.status_code, 200, blocked.text)
        self.assertEqual(blocked.json()["status"], "needs_human")
        again = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                               "body_sha256": "d" * 64})
        self.assertEqual(again.json()["status"], "duplicate")
        report = self.post("/browser/publish/reconcile", {"book_id": "b1", "chapter": 3,
                                                          "resolution": "abandoned",
                                                          "note": "作者放弃本次投递"})
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["changed"], 1)
        browser_target.register(FakeBrowser())
        fresh = self.post("/browser/publish", {"book_id": "b1", "chapter": 3,
                                               "body_sha256": "d" * 64})
        self.assertEqual(fresh.json()["status"], "accepted")

    def test_capabilities_have_eight_columns(self):
        self.save_target()
        response = self.get("/browser/capabilities")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["columns"]), 8)
        self.assertEqual(set(body["row"]), set(body["columns"]))
        self.assertEqual(body["row"]["publish"], "pending")
        self.assertEqual(body["row"]["readonly"], "pending")
        self.assertEqual(body["evidence"]["readonly"], "")

    def test_status_does_not_write(self):
        self.save_target()
        before = (self.project / ".webnovel" / "browser")
        snapshot = sorted(item.name for item in before.iterdir()) if before.is_dir() else []
        response = self.get("/browser/status")
        self.assertEqual(response.status_code, 200, response.text)
        after = sorted(item.name for item in before.iterdir()) if before.is_dir() else []
        self.assertEqual(snapshot, after)

    # --- audit-095：越界 key、错误体形状、stop 状态码 ---

    def test_reconcile_rejects_traversal_key(self):
        self.save_target(scope="publish", authorization="作者授权")
        victim = self.root / "victim.json"
        victim.write_text('{"keep": "original"}', encoding="utf-8")
        for bad in ("../../victim", "..\\..\\victim", "not-hex"):
            response = self.post("/browser/publish/reconcile", {"key": bad,
                                                                "resolution": "accepted"})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["code"], "invalid_request")
        self.assertEqual(victim.read_text(encoding="utf-8"), '{"keep": "original"}')

    def test_validation_errors_use_code_and_message(self):
        response = self.put("/browser/target", {"os": "windows"})
        self.assertEqual(response.status_code, 422, response.text)
        body = response.json()
        self.assertEqual(body["code"], "invalid_request")
        self.assertIn("message", body)
        missing = self.client.get("/api/projects/does-not-exist/browser/status",
                                  headers=self.headers)
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(missing.json()["code"], "not_found")
        self.assertIn("未登记", missing.json()["message"])

    def test_stop_failure_is_a_conflict(self):
        self.save_target()

        class Broken(FakeBrowser):
            def close(self):
                raise OSError("close exploded")

        browser_target.register(Broken())
        response = self.post("/browser/stop")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "stop_failed")
        browser_target.register(FakeBrowser())
        ok = self.post("/browser/stop")
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_readonly_accepts_expected_digest(self):
        self.save_target()
        browser_target.register(FakeBrowser())
        mismatch = self.post("/browser/readonly", {"book_id": "b1", "chapter": 3,
                                                   "body_sha256": "d" * 64})
        self.assertEqual(mismatch.status_code, 200, mismatch.text)
        self.assertEqual(mismatch.json()["status"], "needs_review")
        matched = self.post("/browser/readonly", {"book_id": "b1", "chapter": 3,
                                                  "body_sha256": "c" * 64})
        self.assertEqual(matched.json()["status"], "verified")
        self.assertEqual(matched.json()["observed_sha256"], "c" * 64)


if __name__ == "__main__":
    unittest.main()
