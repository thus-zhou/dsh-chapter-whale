"""E-01/E-03：发布状态回写（staged/published）与提交正文绑定。"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fanqie_auto_publish import publish
from fanqie_auto_publish.publication_safety import digest_file
from integration import bridge, chapter_editor as ce, chapter_versions as cv
from integration import publication_state, publishing as pub

TEXT1 = "第一段。\n\n第二段。\n"
TEXT2 = "承接上一章。\n\n新的段落。\n"


def _disk_sha(project, chapter: int) -> str:
    return cv.file_sha256(cv.chapter_path(project, chapter))


def _new_chapter(project, number: int, title: str, text: str) -> dict:
    created = ce.new_chapter(project, {
        "chapter": number, "title": title, "content": text,
        "op_id": f"new-{number}-{uuid.uuid4().hex[:8]}"})
    ce.author_confirm(project, number, {
        "expected_version_id": created["version_id"],
        "expected_content_sha256": created["sha256"],
        "op_id": f"confirm-{number}-{uuid.uuid4().hex[:8]}",
        "note": "测试定稿"})
    return created


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


class FakePlatform:
    """只替代浏览器步骤的发布器；journal/归档/回执仍走真实代码。"""

    def __init__(self, confirmation="已发布"):
        self.confirmation = confirmation
        self.calls = []

    def prepare(self, book):
        self.calls.append("prepare")

    def existing(self, chapter):
        self.calls.append("existing")
        return None

    def open_editor(self, chapter, existing):
        self.calls.append("open_editor")

    def fill(self, chapter, volume):
        self.calls.append("fill")

    def settings(self, used):
        self.calls.append("settings")

    def submit(self):
        self.calls.append("submit")

    def verify_published(self, chapter, deadline_seconds=3600, reconcile=False):
        self.calls.append("verify")
        return {"platform_status": self.confirmation,
                "verification": "chapter_list_and_body",
                "book_url": "https://fanqienovel.com/main/writer/book/123",
                "verified_at": "2026-01-01T00:00:00+00:00"}


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "书"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()

    def test_forged_or_stale_sha_is_never_written(self):
        _new_chapter(self.project, 1, "开端", TEXT1)
        disk = _disk_sha(self.project, 1)
        forged = publication_state.record_staged(
            self.project, 1, content_sha256="f" * 64)
        self.assertFalse(forged["recorded"])
        self.assertNotIn("staged_at", publication_state.chapter_receipt(self.project, 1))
        self.assertFalse(publication_state.record_published(
            self.project, 1, content_sha256="f" * 64)["recorded"])
        real = publication_state.record_staged(self.project, 1, content_sha256=disk)
        self.assertTrue(real["recorded"])
        self.assertEqual(publication_state.chapter_receipt(self.project, 1)["staged_sha256"], disk)
        # 保留定稿审查回执，不被发布状态覆盖。
        self.assertEqual(
            publication_state.chapter_receipt(self.project, 1)["review"]["review_decision"],
            "author_confirmed")

    def test_historical_version_may_be_marked_published(self):
        created = _new_chapter(self.project, 1, "开端", TEXT1)
        old_sha = _disk_sha(self.project, 1)
        saved = ce.save_version(self.project, 1, {
            "title": "开端", "content": TEXT1 + "补一句。\n", "source": "author_edit",
            "op_id": "edit-1", "expected_version_id": created["version_id"],
            "expected_content_sha256": old_sha})
        ce.author_confirm(self.project, 1, {
            "expected_version_id": saved["version_id"],
            "expected_content_sha256": saved.get("sha256") or saved["content_sha256"],
            "op_id": "confirm-2", "note": "改稿后定稿"})
        result = publication_state.record_published(self.project, 1, content_sha256=old_sha)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["binding"], "version")
        self.assertTrue(ce.chapter_state(self.project, 1)["publication"]["local_diverged"])


class BridgeStageReceiptTest(unittest.TestCase):
    """真实 queue 写入后，delete/split/merge 必须被 409 拒绝。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        self.fanqie = self.root / "fanqie_auto_publish"
        self.fanqie.mkdir()
        (self.fanqie / "publish.py").write_text("# subprocess is mocked\n", encoding="utf-8")
        for key, value in {"FANQIE_ROOT": self.fanqie, "QUEUE_ROOT": self.fanqie / "chapters",
                           "UPLOADED_ROOT": self.fanqie / "uploaded",
                           "MANIFEST_PATH": self.root / "manifest.json",
                           "ACCOUNTS_ROOT": self.root / "accounts",
                           "RUNTIME_ROOT": self.root / "runtime"}.items():
            active = patch.object(bridge, key, value)
            active.start()
            self.addCleanup(active.stop)
        _new_chapter(self.project, 1, "开端", TEXT1)
        _new_chapter(self.project, 2, "承接", TEXT2)
        self.staged = bridge.stage_project(self.project, "测试书")
        self.assertEqual(self.staged["staged_count"], 2)

    def test_stage_writes_staged_receipts(self):
        receipts = publication_state.load_receipts(self.project)
        for number in ("1", "2"):
            self.assertTrue(receipts[number]["staged_at"])
            self.assertEqual(receipts[number]["staged_sha256"], _disk_sha(self.project, int(number)))
            self.assertEqual(receipts[number]["review"]["review_decision"], "author_confirmed")
        self.assertEqual(len(self.staged["publication_receipts"]), 2)
        self.assertTrue(all(item["recorded"] for item in self.staged["publication_receipts"]))

    def test_delete_tail_is_refused(self):
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 2, expected_content_sha256=_disk_sha(self.project, 2))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_split_tail_is_refused(self):
        with self.assertRaises(ce.ChapterError) as caught:
            ce.split_chapter(self.project, 2, offset=2, op_id="split-staged")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_merge_tail_is_refused(self):
        with self.assertRaises(ce.ChapterError) as caught:
            ce.merge_tail(self.project, op_id="merge-staged")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_dry_run_does_not_write_receipts(self):
        other = self.root / "other"
        (other / "正文").mkdir(parents=True)
        (other / ".webnovel").mkdir()
        _new_chapter(other, 1, "开端", TEXT1)
        result = bridge.stage_project(other, "另一本", dry_run=True)
        self.assertNotIn("staged_at", publication_state.chapter_receipt(other, 1))
        self.assertNotIn("publication_receipts", result)


class PublishSubmitBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "书"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        pub.clear_adapters()
        self.addCleanup(pub.clear_adapters)
        self.created = _new_chapter(self.project, 1, "开端", TEXT1)
        pub.set_target_platform(self.project, "fanqie", account="acc",
                                platform_book_id="b-1", book="书")
        pub.bind_book(self.project, platform="fanqie", account="acc",
                      platform_book_id="b-1", title="书", verified_via="manual",
                      observed_chapters=[1])
        pub.authorize(self.project, platform="fanqie", account="acc",
                      platform_book_id="b-1", chapters=[1],
                      note="作者本人在 09:00 授权第1章试投")

    def submit(self, *, body=TEXT1, title="开端", adapter=None):
        if adapter is not None:
            pub.register_adapter("fanqie", adapter)
        return pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                  platform_book_id="b-1", chapter=1,
                                  title=title, body=body)

    def test_accepted_writes_published_state_and_blocks_delete(self):
        built = pub.format_chapter(1, "开端", TEXT1, platform="fanqie")
        adapter = Adapter(echo=built["sha256"])
        result = self.submit(adapter=adapter)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(adapter.calls), 1)
        self.assertTrue(result["publication_state"]["recorded"])
        receipts = publication_state.load_receipts(self.project)
        self.assertEqual(receipts["1"]["published_sha256"], _disk_sha(self.project, 1))
        self.assertEqual(receipts["1"]["publish"]["remote_id"], "r-1")
        state = ce.chapter_state(self.project, 1)
        self.assertEqual(state["publication"]["status"], "published")
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 1,
                              expected_content_sha256=_disk_sha(self.project, 1))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_forged_body_is_refused_before_adapter(self):
        adapter = Adapter()
        with self.assertRaises(pub.PublishError) as caught:
            self.submit(body="一段从未进入版本层、也从未被审查的正文。\n", adapter=adapter)
        self.assertIn("当前版本", str(caught.exception))
        self.assertEqual(adapter.calls, [])
        self.assertNotIn("published_sha256",
                         publication_state.chapter_receipt(self.project, 1))

    def test_missing_review_is_refused_before_adapter(self):
        receipts = publication_state.load_receipts(self.project)
        receipts["1"].pop("review", None)
        from fanqie_auto_publish.publication_safety import atomic_json
        atomic_json(publication_state.receipts_path(self.project), receipts)
        adapter = Adapter()
        result = self.submit(adapter=adapter)
        self.assertEqual(result["status"], "refused")
        self.assertIn("审查", result["reason"])
        self.assertEqual(adapter.calls, [])

    def test_missing_adapter_is_unavailable(self):
        result = self.submit()
        self.assertEqual(result["status"], "unavailable")

    def test_direct_disk_edit_breaks_version_binding(self):
        path = cv.chapter_path(self.project, 1)
        path.write_text("绕过版本层直接改盘。\n", encoding="utf-8")
        adapter = Adapter()
        with self.assertRaises(pub.PublishError) as caught:
            self.submit(body="绕过版本层直接改盘。\n", adapter=adapter)
        self.assertIn("版本", str(caught.exception))
        self.assertEqual(adapter.calls, [])

    def test_reconcile_accepted_writes_published_state(self):
        adapter = Adapter(raises=TimeoutError("网关超时"))
        unknown = self.submit(adapter=adapter)
        self.assertEqual(unknown["status"], "unknown")
        built = pub.format_chapter(1, "开端", TEXT1, platform="fanqie")
        resolved = pub.reconcile(
            self.project, platform="fanqie", account="acc", platform_book_id="b-1",
            chapter=1, body_sha256=built["sha256"], resolution="accepted",
            note="平台侧已出现该章", evidence="番茄后台第1章=已发布")
        self.assertEqual(resolved["state"], "accepted")
        self.assertTrue(resolved["publication_state"]["recorded"])
        receipts = publication_state.load_receipts(self.project)
        self.assertEqual(receipts["1"]["published_sha256"], _disk_sha(self.project, 1))
        self.assertEqual(receipts["1"]["publish"]["source"], "publishing.reconcile")


class LegacyPublishReceiptTest(unittest.TestCase):
    """bridge.run_publish 的真实成功证据 → published_sha256 → 章节只读。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "project"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(
            json.dumps({"progress": {"current_chapter": 0}}), encoding="utf-8")
        self.fanqie = self.root / "fanqie_auto_publish"
        self.fanqie.mkdir()
        (self.fanqie / "publish.py").write_text("# subprocess is mocked\n", encoding="utf-8")
        for key, value in {"FANQIE_ROOT": self.fanqie, "QUEUE_ROOT": self.fanqie / "chapters",
                           "UPLOADED_ROOT": self.fanqie / "uploaded",
                           "MANIFEST_PATH": self.root / "manifest.json",
                           "ACCOUNTS_ROOT": self.root / "accounts",
                           "RUNTIME_ROOT": self.root / "runtime"}.items():
            active = patch.object(bridge, key, value)
            active.start()
            self.addCleanup(active.stop)
        self.enterContext(patch.dict(os.environ, {
            "NOVEL_HELPER_AI_CONFIG": str(self.root / "offline-ai.json")}))
        state = bridge.account_state_path("账号A")
        state.parent.mkdir(parents=True)
        state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        _new_chapter(self.project, 1, "开端", TEXT1)
        self.source = cv.chapter_path(self.project, 1)
        bridge.stage_project(self.project, "测试书")
        self.queue_file = next((self.fanqie / "chapters" / "测试书").glob("*.txt"))
        # 只留审查回执，去掉 staged 字段，证明 published 是发布成功路径自己写的。
        receipts = publication_state.load_receipts(self.project)
        for key in ("staged_at", "staged_sha256", "stage"):
            receipts["1"].pop(key, None)
        from fanqie_auto_publish.publication_safety import atomic_json
        atomic_json(publication_state.receipts_path(self.project), receipts)

    def test_verified_publish_writes_published_receipt_and_blocks_delete(self):
        def child(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            origin = json.loads(Path(command[command.index("--plan") + 1]).read_text(encoding="utf-8"))
            result = publish.publish_batch(
                FakePlatform(), [self.queue_file],
                self.fanqie / "uploaded" / "测试书", "测试书", "账号A",
                report=report, origin_plan=origin)
            return subprocess.CompletedProcess(command, result["exit_code"])

        with patch.object(bridge.subprocess, "run", side_effect=child):
            self.assertEqual(bridge.run_publish("测试书", count=1, account="账号A",
                                                project=self.project), 0)
        receipts = publication_state.load_receipts(self.project)
        self.assertEqual(receipts["1"]["published_sha256"], digest_file(self.source))
        self.assertEqual(receipts["1"]["publish"]["source"], "legacy_publish")
        self.assertEqual(receipts["1"]["review"]["review_decision"], "author_confirmed")
        self.assertEqual(ce.chapter_state(self.project, 1)["publication"]["status"], "published")
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 1,
                              expected_content_sha256=digest_file(self.source))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")


if __name__ == "__main__":
    unittest.main()
