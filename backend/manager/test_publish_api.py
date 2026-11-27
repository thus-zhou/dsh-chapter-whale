"""0.10.0：平台契约与第二平台接口。"""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from integration import bridge, chapter_editor as ce, publishing as pub, scheduler
from manager import app as module

TITLE = "潮声"
BODY = "林砚推开门。\n\n屋里没有人。\n"


class Adapter:
    def __init__(self, *, accepted=True, raises=None, echo=None):
        self.accepted = accepted
        self.raises = raises
        self.echo = echo
        self.calls = []

    def submit_draft(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        payload = {"accepted": self.accepted, "remote_id": "r-1"}
        if self.echo is not None:
            payload["body_sha256"] = self.echo
        elif "body_sha256" in kwargs:
            payload["body_sha256"] = kwargs["body_sha256"]
        return payload

    def read_chapter(self, **kwargs):
        return {"chapter_id": kwargs.get("chapter")}


class PublishApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.ai_path = self.root / "ai.json"
        self.projects = self.root / "works"
        self.projects.mkdir()
        self.enterContext(patch.object(module, "DATA", self.data))
        self.enterContext(patch.object(module, "AI_PATH", self.ai_path))
        self.enterContext(patch.object(module.secret_store, "codec", lambda: None))
        self.enterContext(patch.object(scheduler, "SCHEDULER_PATH", self.root / "scheduler.json"))
        self.enterContext(patch.object(scheduler, "RUNS_ROOT", self.root / "runs"))
        self.enterContext(patch.object(bridge, "COMBINED_ROOT", self.root))
        self.enterContext(patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"))
        self.client = TestClient(module.create_app(self.root / "manager.db",
                                                   start_dispatcher=False))
        self.headers = {"X-Novel-Helper": "1"}
        pub.clear_adapters()
        self.addCleanup(pub.clear_adapters)
        self.project = self.projects / "潮汐钟"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(
            json.dumps({"progress": {"current_chapter": 0}}), encoding="utf-8")
        registered = self.client.post("/api/projects", json={"path": str(self.project)},
                             headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.identity = registered.json().get("id") or registered.json().get("identity")

    def post(self, suffix, payload):
        return self.client.post(f"/api/projects/{self.identity}/publish/{suffix}",
                                json=payload, headers=self.headers)

    def ready(self, platform="fanqie", account="acc", book="b-1"):
        self.client.put(f"/api/projects/{self.identity}/publish/target",
                        json={"platform": platform, "account": account,
                              "platform_book_id": book, "book": "潮汐钟"},
                        headers=self.headers)
        self.post("bind", {"platform": platform, "account": account,
                           "platform_book_id": book, "title": "潮汐钟"})
        self.post("authorize", {"platform": platform, "account": account,
                                "platform_book_id": book, "chapters": [1],
                                "note": "作者本人在 09:00 授权"})

    def publishable(self, chapter=1, text=BODY, title=TITLE):
        """真实正文 + 作者定稿回执：由服务端版本层提供发布正文（E-03）。"""
        created = ce.new_chapter(self.project, {
            "chapter": chapter, "title": title, "content": text,
            "op_id": f"api-new-{chapter}-{uuid.uuid4().hex[:8]}"})
        ce.author_confirm(self.project, chapter, {
            "expected_version_id": created["version_id"],
            "expected_content_sha256": created["sha256"],
            "op_id": f"api-confirm-{chapter}-{uuid.uuid4().hex[:8]}",
            "note": "测试定稿"})
        return created

    def test_platforms_expose_two_and_publishable_only_for_fanqie(self):
        response = self.client.get(f"/api/projects/{self.identity}/publish/platforms",
                                     headers=self.headers)
        self.assertEqual(response.status_code, 200)
        rows = {row["platform"]: row for row in response.json()["platforms"]}
        self.assertEqual(set(rows), {"fanqie", "qimao"})
        self.assertTrue(rows["fanqie"]["publishable"])
        self.assertFalse(rows["qimao"]["publishable"])

    def test_unknown_platform_is_rejected(self):
        response = self.client.put(
            f"/api/projects/{self.identity}/publish/target",
            json={"platform": "qidian"}, headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_export_requires_identity_and_manifested(self):
        anonymous = self.post("export", {"platform": "qimao", "chapter": 2,
                                         "title": TITLE, "body": BODY})
        self.assertEqual(anonymous.status_code, 422)
        response = self.post("export", {"platform": "qimao", "chapter": 2,
                                        "title": TITLE, "body": BODY,
                                        "account": "qm", "platform_book_id": "b"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["uploaded"])
        self.assertTrue(Path(body["path"]).is_file())
        listing = self.client.get(
            f"/api/projects/{self.identity}/publish/exports",
            params={"platform": "qimao", "account": "qm", "platform_book_id": "b"},
            headers=self.headers)
        self.assertEqual(listing.json()["items"][0]["chapter"], 2)

    def test_bind_and_authorize_errors_are_coded(self):
        bad_bind = self.post("bind", {"platform": "qimao", "account": "",
                                      "platform_book_id": "b"})
        self.assertEqual(bad_bind.status_code, 422)
        no_note = self.post("authorize", {"platform": "qimao", "account": "qm",
                                          "platform_book_id": "b", "chapters": [1],
                                          "note": ""})
        self.assertEqual(no_note.status_code, 422)

    def test_qimao_submit_is_refused_without_calling_adapter(self):
        adapter = Adapter()
        pub.register_adapter("qimao", adapter)
        self.ready("qimao", "qm", "b")
        response = self.post("submit", {"platform": "qimao", "account": "qm",
                                        "platform_book_id": "b", "chapter": 1,
                                        "title": TITLE, "body": BODY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "refused")
        self.assertEqual(adapter.calls, [])

    def test_fanqie_submit_needs_adapter_then_accepts_once(self):
        self.ready()
        self.publishable()
        missing = self.post("submit", {"platform": "fanqie", "account": "acc",
                                       "platform_book_id": "b-1", "chapter": 1,
                                       "title": TITLE, "body": BODY})
        self.assertEqual(missing.json()["status"], "unavailable")
        adapter = Adapter(echo=pub.format_chapter(1, TITLE, BODY,
                                                  platform="fanqie")["sha256"])
        pub.register_adapter("fanqie", adapter)
        accepted = self.post("submit", {"platform": "fanqie", "account": "acc",
                                        "platform_book_id": "b-1", "chapter": 1,
                                        "title": TITLE, "body": BODY})
        self.assertEqual(accepted.json()["status"], "accepted")
        self.assertTrue(accepted.json()["body_matches"])
        again = self.post("submit", {"platform": "fanqie", "account": "acc",
                                     "platform_book_id": "b-1", "chapter": 1,
                                     "title": TITLE, "body": BODY})
        self.assertEqual(again.json()["status"], "duplicate")
        self.assertEqual(len(adapter.calls), 1)

    def test_forged_body_is_rejected_before_adapter(self):
        self.ready()
        self.publishable()
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        response = self.post("submit", {"platform": "fanqie", "account": "acc",
                                        "platform_book_id": "b-1", "chapter": 1,
                                        "title": TITLE,
                                        "body": "一段从未进入版本层、也从未被审查的正文。\n"})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["code"], "invalid_submit")
        self.assertEqual(adapter.calls, [])

    def test_unknown_result_then_reconcile(self):
        self.ready()
        self.publishable()
        adapter = Adapter(raises=TimeoutError("网关超时"))
        pub.register_adapter("fanqie", adapter)
        unknown = self.post("submit", {"platform": "fanqie", "account": "acc",
                                       "platform_book_id": "b-1", "chapter": 1,
                                       "title": TITLE, "body": BODY})
        self.assertEqual(unknown.json()["status"], "unknown")
        digest = pub.format_chapter(1, TITLE, BODY, platform="fanqie")["sha256"]
        resolved = self.post("reconcile", {"platform": "fanqie", "account": "acc",
                                           "platform_book_id": "b-1", "chapter": 1,
                                           "body_sha256": digest,
                                           "resolution": "accepted",
                                           "note": "平台已有该章",
                                           "evidence": "番茄后台第1章=已发布"})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["state"], "accepted")

    def test_status_aggregates_and_writes_nothing(self):
        self.ready()
        before = sorted(path.name for path in self.project.rglob("*") if path.is_file())
        response = self.client.get(f"/api/projects/{self.identity}/publish/status",
                                     headers=self.headers)
        after = sorted(path.name for path in self.project.rglob("*") if path.is_file())
        self.assertEqual(before, after)
        body = response.json()
        self.assertEqual(body["target"]["platform"], "fanqie")
        self.assertEqual(len(body["bindings"]), 1)
        self.assertEqual(len(body["authorizations"]), 1)

    def test_export_rejects_empty_body(self):
        blank = self.post("export", {"platform": "qimao", "chapter": 1,
                                     "title": TITLE, "body": ""})
        self.assertEqual(blank.status_code, 422)
        response = self.post("export", {"platform": "qimao", "chapter": 1,
                                        "title": TITLE, "body": "   ",
                                        "account": "qm", "platform_book_id": "b"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_export")

    def test_unhandled_error_uses_same_envelope(self):
        from unittest.mock import patch
        self.ready()
        relaxed = TestClient(self.client.app, raise_server_exceptions=False)
        with patch.object(module.publishing, "status",
                          side_effect=ZeroDivisionError("内部炸了")):
            response = relaxed.get(f"/api/projects/{self.identity}/publish/status",
                                    headers=self.headers)
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(response.json()["code"], "internal_error")
        self.assertIn("内部炸了", response.json()["message"])

    def test_body_over_byte_limit_is_rejected(self):
        too_big = "字" * (module.publishing.MAX_EXPORT_BYTES // 3 + 10)
        response = self.post("export", {"platform": "fanqie", "chapter": 1,
                                        "title": TITLE, "body": too_big,
                                        "account": "acc", "platform_book_id": "b-1"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["code"], "invalid_request")
        self.assertIn("字节", response.json()["message"])

    def test_declared_oversize_body_is_payload_too_large(self):
        # 中间件按 Content-Length 直接拒绝：码值必须与文档写的一致，且不读正文。
        oversized = str(33 * 1024 * 1024)
        response = self.client.post(
            f"/api/projects/{self.identity}/publish/export",
            headers={**self.headers, "content-length": oversized},
            content=b"{}")
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()["code"], "payload_too_large")
