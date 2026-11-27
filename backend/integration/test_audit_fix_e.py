"""E 域第四轮修复回归：staged 失效、unknown/浏览器回执、超时回执、导出绑定、质量事实源。

不启动真实浏览器/AI；平台层使用真实文件锁、账本和回执，只替换最终适配器/子进程。
"""
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
from integration import bridge, browser_target as bt, chapter_editor as ce
from integration import chapter_versions as cv, publication_state, publishing as pub
from integration import quality, world_state, writer_runner as writer

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


def _scores(value: int) -> dict:
    return {dim: value for dim in quality.DIMENSIONS}


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


class BrowserAdapter:
    def __init__(self, *, raise_error=None, accepted=True, echo=None):
        self.raise_error = raise_error
        self.accepted = accepted
        self.echo = echo
        self.calls = []

    def publish_chapter(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error is not None:
            raise self.raise_error
        return {"accepted": self.accepted,
                "content_sha256": self.echo if self.echo is not None else kwargs.get("body_sha256")}


class FakePlatform:
    """只替代浏览器步骤的发布器；journal/归档/回执仍走真实代码。"""

    def prepare(self, book):
        pass

    def existing(self, chapter):
        return None

    def open_editor(self, chapter, existing):
        pass

    def fill(self, chapter, volume):
        pass

    def settings(self, used):
        pass

    def submit(self):
        pass

    def verify_published(self, chapter, deadline_seconds=3600, reconcile=False):
        return {"platform_status": "已发布", "verification": "chapter_list_and_body",
                "book_url": "https://fanqienovel.com/main/writer/book/123",
                "verified_at": "2026-01-01T00:00:00+00:00"}


class PendingSubmitTest(unittest.TestCase):
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
                      platform_book_id="b-1", chapters=[1], note="测试授权")

    def submit(self, adapter):
        pub.register_adapter("fanqie", adapter)
        return pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                  platform_book_id="b-1", chapter=1,
                                  title="开端", body=TEXT1)

    def assert_pending_and_blocked(self):
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertIn("publish_pending", receipt)
        self.assertTrue(receipt["staged_at"])
        self.assertEqual(ce.chapter_state(self.project, 1)["publication"]["status"], "staged")
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 1,
                              expected_content_sha256=_disk_sha(self.project, 1))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_unknown_result_writes_pending_and_blocks_delete(self):
        result = self.submit(Adapter(raises=TimeoutError("网关超时")))
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["publication_state"]["recorded"])
        self.assert_pending_and_blocked()

    def test_mismatch_result_writes_pending_and_blocks_delete(self):
        built = pub.format_chapter(1, "开端", TEXT1, platform="fanqie")
        result = self.submit(Adapter(echo="f" * 64))
        self.assertEqual(result["status"], "mismatch")
        self.assertNotEqual(built["sha256"], "f" * 64)
        self.assert_pending_and_blocked()

    def test_accepted_clears_pending_and_blocks_delete(self):
        built = pub.format_chapter(1, "开端", TEXT1, platform="fanqie")
        result = self.submit(Adapter(echo=built["sha256"]))
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["publication_state"]["recorded"])
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertFalse(receipt.get("publish_pending"))
        self.assertEqual(receipt["published_sha256"], _disk_sha(self.project, 1))
        self.assertEqual(ce.chapter_state(self.project, 1)["publication"]["status"], "published")

    def test_reconcile_abandoned_clears_pending(self):
        self.submit(Adapter(raises=TimeoutError("网关超时")))
        built = pub.format_chapter(1, "开端", TEXT1, platform="fanqie")
        resolved = pub.reconcile(
            self.project, platform="fanqie", account="acc", platform_book_id="b-1",
            chapter=1, body_sha256=built["sha256"], resolution="abandoned",
            note="平台侧没有该章", evidence="番茄后台章节列表未见第1章")
        self.assertTrue(resolved["publication_state"]["cleared"])
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertFalse(receipt.get("publish_pending"))
        self.assertFalse(receipt.get("staged_at"))
        ce.delete_chapter(self.project, 1,
                          expected_content_sha256=_disk_sha(self.project, 1))
        self.assertEqual(list((self.project / "正文").glob("*.md")), [])

    def test_receipt_failure_refuses_before_adapter(self):
        adapter = Adapter()
        with patch.object(publication_state, "record_pending",
                          return_value={"recorded": False, "reason": "receipts_busy"}):
            result = self.submit(adapter)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["writes_attempted"], 0)
        self.assertEqual(adapter.calls, [])


class BrowserPublishReceiptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "书"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        _new_chapter(self.project, 1, "开端", TEXT1)
        bt.save_target(self.project, {
            "os": "windows", "arch": "amd64", "runtime": "native",
            "browser": "chromium", "browser_version": "131.0",
            "driver": "playwright", "credential": "reconfigured",
            "scope": "publish", "authorization": "作者授权：第1章"})

    def test_accepted_records_published_and_blocks_delete(self):
        body = _disk_sha(self.project, 1)
        report = bt.publish_once(BrowserAdapter(echo=body), self.project,
                                 book_id="b1", chapter=1, body_sha256=body)
        self.assertEqual(report["status"], "accepted")
        self.assertTrue(report["publication_state"]["recorded"])
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertEqual(receipt["published_sha256"], body)
        self.assertFalse(receipt.get("publish_pending"))
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 1, expected_content_sha256=body)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_unknown_writes_pending_and_blocks_delete(self):
        body = _disk_sha(self.project, 1)
        report = bt.publish_once(BrowserAdapter(raise_error=RuntimeError("连接中断")),
                                 self.project, book_id="b1", chapter=1, body_sha256=body)
        self.assertEqual(report["status"], "unknown")
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertIn("publish_pending", receipt)
        self.assertTrue(receipt["staged_at"])
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 1, expected_content_sha256=body)
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_unbound_body_digest_keeps_pending(self):
        report = bt.publish_once(BrowserAdapter(), self.project,
                                 book_id="b1", chapter=1, body_sha256="d" * 64)
        self.assertEqual(report["status"], "accepted")
        self.assertFalse(report["publication_state"]["recorded"])
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertIn("publish_pending", receipt)
        self.assertNotIn("published_sha256", receipt)

    def test_reconcile_accepted_records_published(self):
        body = _disk_sha(self.project, 1)
        bt.publish_once(BrowserAdapter(raise_error=RuntimeError("超时")), self.project,
                        book_id="b1", chapter=1, body_sha256=body)
        result = bt.reconcile_publish(self.project, book_id="b1", chapter=1,
                                      resolution="accepted", note="后台已出现第1章")
        self.assertEqual(result["changed"], 1)
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertEqual(receipt["published_sha256"], body)
        self.assertFalse(receipt.get("publish_pending"))

    def test_reconcile_abandoned_clears_pending(self):
        body = _disk_sha(self.project, 1)
        bt.publish_once(BrowserAdapter(raise_error=RuntimeError("超时")), self.project,
                        book_id="b1", chapter=1, body_sha256=body)
        bt.reconcile_publish(self.project, book_id="b1", chapter=1,
                             resolution="abandoned", note="后台未出现第1章")
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertFalse(receipt.get("publish_pending"))
        self.assertFalse(receipt.get("staged_at"))
        ce.delete_chapter(self.project, 1, expected_content_sha256=body)


class TimeoutReceiptTest(unittest.TestCase):
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
        receipts = publication_state.load_receipts(self.project)
        for key in ("staged_at", "staged_sha256", "stage"):
            receipts["1"].pop(key, None)
        from fanqie_auto_publish.publication_safety import atomic_json
        atomic_json(publication_state.receipts_path(self.project), receipts)

    def _publish_report(self, command):
        report = Path(command[command.index("--report") + 1])
        origin = json.loads(Path(command[command.index("--plan") + 1]).read_text(encoding="utf-8"))
        return publish.publish_batch(
            FakePlatform(), [self.queue_file],
            self.fanqie / "uploaded" / "测试书", "测试书", "账号A",
            report=report, origin_plan=origin)

    def assert_published_and_blocked(self):
        receipts = publication_state.load_receipts(self.project)
        self.assertEqual(receipts["1"]["published_sha256"], digest_file(self.source))
        with self.assertRaises(ce.ChapterError) as caught:
            ce.delete_chapter(self.project, 1,
                              expected_content_sha256=digest_file(self.source))
        self.assertEqual(caught.exception.code, "chapter_published_readonly")

    def test_timeout_after_confirmation_still_writes_receipt(self):
        def timeout_child(command, timeout):
            self._publish_report(command)
            raise subprocess.TimeoutExpired(command, timeout)

        with patch.object(bridge, "_run_publish_process", side_effect=timeout_child):
            code = bridge.run_publish("测试书", count=1, account="账号A",
                                      project=self.project)
        self.assertEqual(code, 2)
        self.assert_published_and_blocked()

    def test_bad_latest_report_does_not_discard_confirmed_receipt(self):
        def child(command, **kwargs):
            result = self._publish_report(command)
            return subprocess.CompletedProcess(command, result["exit_code"])

        with patch.object(bridge.subprocess, "run", side_effect=child), \
                patch.object(bridge, "latest_publish_report",
                             side_effect=ValueError("report_corrupt")):
            code = bridge.run_publish("测试书", count=1, account="账号A",
                                      project=self.project)
        self.assertEqual(code, 2)
        self.assert_published_and_blocked()


class StageStaleEditTest(unittest.TestCase):
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
        self.created = _new_chapter(self.project, 1, "开端", TEXT1)
        first = bridge.stage_project(self.project, "测试书")
        self.assertEqual(first["staged_count"], 1)
        self.queue_file = next((self.fanqie / "chapters" / "测试书").glob("*.txt"))

    def edit(self, text):
        return ce.save_version(self.project, 1, {
            "title": "开端", "content": text, "source": "author_edit",
            "op_id": f"edit-{uuid.uuid4().hex[:8]}",
            "expected_version_id": self.created["version_id"],
            "expected_content_sha256": self.created["sha256"]})

    def test_edit_then_restage_replaces_own_stale_copy(self):
        self.edit(TEXT1 + "补一句。\n")
        result = bridge.stage_project(self.project, "测试书")
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["staged_count"], 1)
        self.assertTrue(result["staged"][0].get("replaced_stale"))
        receipt = publication_state.chapter_receipt(self.project, 1)
        self.assertEqual(receipt["staged_sha256"], _disk_sha(self.project, 1))

    def test_foreign_queue_edit_still_conflicts(self):
        self.queue_file.write_text("别人改过的待发正文。\n", encoding="utf-8")
        result = bridge.stage_project(self.project, "测试书")
        self.assertEqual(result["staged_count"], 0)
        self.assertEqual(len(result["conflicts"]), 1)

    def test_plan_exposes_quality_advisory(self):
        quality.review(self.project, 1, judgments=[{"scores": _scores(90), "reviewer": "B"}])
        state = bridge.account_state_path("acc")
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        plan = bridge.validate_queue_origin("测试书", account="acc")
        self.assertEqual(plan["chapters"][0]["quality"]["verdict"], "pass")
        self.assertEqual(plan["quality_advisory"]["counts"]["pass"], 1)
        self.assertTrue(plan["quality_advisory"]["advisory_only"])


class ExportBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "书"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        self.created = _new_chapter(self.project, 1, "开端", TEXT1)

    def test_forged_body_is_refused_before_writing(self):
        with self.assertRaises(pub.PublishError) as caught:
            pub.export_chapter(self.project, platform="qimao", chapter=1,
                               title="开端", body="从未进入版本层的正文。\n",
                               account="qm", platform_book_id="b")
        self.assertIn("当前版本", str(caught.exception))
        self.assertFalse((self.project / ".webnovel" / "publish").exists())

    def test_missing_chapter_is_exported_as_unbound(self):
        result = pub.export_chapter(self.project, platform="qimao", chapter=2,
                                    title="草稿", body=TEXT2, account="qm",
                                    platform_book_id="b")
        self.assertFalse(result["version_bound"])
        self.assertFalse(result["review_bound"])
        self.assertIsNone(result["version_id"])
        listing = pub.exports(self.project, platform="qimao", account="qm",
                              platform_book_id="b")
        self.assertFalse(listing["items"][0]["version_bound"])

    def test_current_reviewed_body_exports_bound(self):
        result = pub.export_chapter(self.project, platform="qimao", chapter=1,
                                    title="开端", body=TEXT1, account="qm",
                                    platform_book_id="b")
        self.assertTrue(result["version_bound"])
        self.assertTrue(result["review_bound"])
        self.assertEqual(result["version_id"], self.created["version_id"])


class QualitySourceTest(unittest.TestCase):
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
                      platform_book_id="b-1", chapters=[1], note="测试授权")

    def drop_legacy_review(self):
        receipts = publication_state.load_receipts(self.project)
        receipts["1"].pop("review", None)
        from fanqie_auto_publish.publication_safety import atomic_json
        atomic_json(publication_state.receipts_path(self.project), receipts)

    def test_quality_pass_is_a_review_fact_when_legacy_missing(self):
        quality.review(self.project, 1, judgments=[{"scores": _scores(90), "reviewer": "B"}])
        self.drop_legacy_review()
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title="开端", body=TEXT1)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(adapter.calls), 1)

    def test_quality_block_refuses_before_adapter(self):
        quality.review(self.project, 1, judgments=[{"scores": _scores(10), "reviewer": "B"}])
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title="开端", body=TEXT1)
        self.assertEqual(result["status"], "refused")
        self.assertIn("质量", result["reason"])
        self.assertEqual(result["quality"]["verdict"], "block")
        self.assertEqual(adapter.calls, [])

    def test_stale_quality_pass_does_not_grant_submit(self):
        quality.review(self.project, 1, judgments=[{"scores": _scores(90), "reviewer": "B"}])
        saved = ce.save_version(self.project, 1, {
            "title": "开端", "content": TEXT1 + "新增一段。\n", "source": "author_edit",
            "op_id": f"edit-{uuid.uuid4().hex[:8]}",
            "expected_version_id": self.created["version_id"],
            "expected_content_sha256": self.created["sha256"]})
        ce.author_confirm(self.project, 1, {
            "expected_version_id": saved["version_id"],
            "expected_content_sha256": saved.get("sha256") or saved["content_sha256"],
            "op_id": f"confirm2-{uuid.uuid4().hex[:8]}", "note": "改稿后定稿"})
        self.drop_legacy_review()
        advisory = publication_state.quality_advisory(self.project, 1)
        self.assertTrue(advisory["stale"])
        self.assertEqual(advisory["gate"], "unknown")
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title="开端", body=TEXT1 + "新增一段。\n")
        self.assertEqual(result["status"], "refused")
        self.assertIn("review_missing", result["reason"])
        self.assertEqual(adapter.calls, [])


class WorldContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "书"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / "大纲").mkdir()
        (self.project / "大纲" / "卷一.md").write_text("## 第1章 开端\n故事开始。\n",
                                                       encoding="utf-8")

    def test_prepare_context_persists_manifest(self):
        prepared = writer._prepare_world_context(self.project, 1)
        self.assertIn(prepared["status"], {"injected", "empty"})
        self.assertEqual(prepared["manifest"]["chapter_id"], 1)
        self.assertIsNotNone(world_state.latest_manifest(self.project, 1))

    def test_skill_executor_prompt_block_contains_facts(self):
        SkillExecutor, _ = writer._load_webnovel_services()
        executor = SkillExecutor(project_root=self.project)
        self.assertEqual(executor._world_state_prompt_block(), "")
        executor.world_state_context = "<UNTRUSTED_MATERIAL>\n- 林舟在码头\n</UNTRUSTED_MATERIAL>"
        block = executor._world_state_prompt_block()
        self.assertIn("世界状态事实", block)
        self.assertIn("林舟在码头", block)


if __name__ == "__main__":
    unittest.main()
