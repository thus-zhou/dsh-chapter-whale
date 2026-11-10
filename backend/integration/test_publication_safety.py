"""Offline publication acceptance: no credentials, network or real chapters."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from integration import bridge
from fanqie_auto_publish import publish
from fanqie_auto_publish.publication_safety import (
    PublicationBlocked, archive_confirmed, atomic_json, body_digest, digest_file,
    file_lock, journal_path, queue_lock, read_json_strict, utc_now, valid_receipt,
)


class FakePlatform:
    def __init__(self, fail=None, status=None, confirmation="已发布", mutate=None):
        self.fail, self.status, self.confirmation, self.mutate = fail, status, confirmation, mutate
        self.calls = []

    def step(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise PublicationBlocked(name + "_blocked")

    def prepare(self, book):
        self.step("prepare")

    def existing(self, chapter):
        self.step("existing")
        return {"status": self.status} if self.status else None

    def open_editor(self, chapter, existing):
        self.step("open_editor")

    def fill(self, chapter, volume):
        self.step("fill")

    def settings(self, used):
        self.ai_used = used
        self.step("settings")
        if self.mutate:
            self.mutate()

    def submit(self):
        self.step("submit")

    def verify_published(self, chapter, deadline_seconds=3600, reconcile=False):
        self.step("verify")
        return {"platform_status": self.confirmation, "verification": "chapter_list_and_body",
                "book_url": "https://fanqienovel.com/main/writer/book/123",
                "verified_at": utc_now()}


class PublicationTest(unittest.TestCase):
    def test_guard_allows_only_authorized_typo_advisory_during_settings_race(self):
        dialog = MagicMock()
        dialog.is_visible.return_value = True
        dialog.inner_text.return_value = "发布提示\n检测到你还有错别字未修改，是否确定提交？\n取消提交"
        dialog.get_by_role.return_value.count.return_value = 0
        dialogs = MagicMock()
        dialogs.count.return_value = 1
        dialogs.nth.return_value = dialog
        empty = MagicMock()
        empty.count.return_value = 0
        body = MagicMock()
        body.inner_text.return_value = ""
        page = MagicMock()
        page.url = "https://fanqienovel.com/main/writer/book/123"
        page.locator.side_effect = lambda selector: (
            body if selector == "body" else dialogs if selector == publish.ACTIVE_DIALOGS else empty
        )
        adapter = publish.FanqieDOM.__new__(publish.FanqieDOM)
        adapter.allow_typo_advisory = True
        with patch.object(adapter, "dismiss_onboarding"):
            adapter.guard(page, allow_settings=True)
        page.screenshot.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = self.root / "chapters" / "测试书"
        self.queue.mkdir(parents=True)
        self.source = self.queue / "001 第1章 初见.txt"
        self.source.write_text("正文第一行。\n正文第二行。\n", encoding="utf-8")
        self.archive = self.root / "uploaded" / "测试书"
        self.report = self.root / "report.json"
        self.addCleanup(self.temp.cleanup)

    def run_batch(self, platform=None, files=None, **kwargs):
        return publish.publish_batch(platform or FakePlatform(), files or [self.source], self.archive,
                                     "测试书", "账号A", report=self.report, **kwargs)

    def test_confirmation_body_receipt_then_archive(self):
        result = self.run_batch()
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["confirmed_count"], 1)
        self.assertFalse(self.source.exists())
        archived = self.archive / self.source.name
        self.assertIsNotNone(valid_receipt(archived, "测试书", 1, "账号A"))
        self.assertEqual(read_json_strict(self.report)["chapters"][0]["archive_path"], str(archived))

    def test_deadline_is_checked_after_settings_before_actual_submit(self):
        platform=FakePlatform(mutate=lambda:os.environ.__setitem__('NOVEL_HELPER_SUBMIT_BEFORE','2000-01-01T00:00:00+00:00'))
        with patch.dict(os.environ,{'NOVEL_HELPER_SUBMIT_BEFORE':'2999-01-01T00:00:00+00:00'}):
            result=self.run_batch(platform)
        self.assertEqual(result['exit_code'],2)
        self.assertEqual(result['reason'],'word_goal_date_expired_before_submit')
        self.assertNotIn('submit',platform.calls)
        self.assertEqual(read_json_strict(journal_path(self.source))['state'],'blocked_before_submit')
        self.assertTrue(self.source.exists())

    def test_click_without_confirmation_is_not_success(self):
        platform = FakePlatform(fail="verify")
        result = self.run_batch(platform)
        self.assertIn("submit", platform.calls)
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(read_json_strict(journal_path(self.source))["state"], "unconfirmed")
        self.assertTrue(self.source.exists())
        self.assertFalse(self.archive.exists())

    def test_unconfirmed_attempt_cannot_be_submitted_again(self):
        self.run_batch(FakePlatform(fail="verify"))
        before = journal_path(self.source).read_bytes()
        platform = FakePlatform()
        result = self.run_batch(platform)
        self.assertEqual(result["reason"], "previous_attempt_requires_reconciliation")
        self.assertNotIn("submit", platform.calls)
        self.assertEqual(journal_path(self.source).read_bytes(), before)

    def test_reconcile_archives_only_after_full_confirmation_without_editor_or_submit(self):
        self.run_batch(FakePlatform(fail='verify'))
        platform=FakePlatform()
        with patch.object(publish,'validate_origin_plan') as validate:
            result=publish.reconcile_batch(platform,[self.source],self.archive,'测试书','账号A',origin_plan={})
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(platform.calls,['prepare','verify'])
        self.assertEqual(validate.call_count,2)
        self.assertIsNotNone(valid_receipt(self.archive/self.source.name,'测试书',1,'账号A'))

    def test_reconcile_cannot_change_identity_or_accept_pending_status(self):
        self.run_batch(FakePlatform(fail='verify'))
        platform=FakePlatform(confirmation='审核中')
        with patch.object(publish,'validate_origin_plan'):
            result=publish.reconcile_batch(platform,[self.source],self.archive,'测试书','账号A',origin_plan={})
        self.assertNotEqual(result['exit_code'],0)
        self.assertTrue(self.source.exists())
        self.assertNotIn('submit',platform.calls)
        with patch.object(publish,'validate_origin_plan'):
            result=publish.reconcile_batch(FakePlatform(),[self.source],self.archive,'测试书','账号B',origin_plan={})
        self.assertEqual(result['reason'],'reconciliation_identity_mismatch')
        self.assertTrue(self.source.exists())

    def test_reconcile_downgrades_platform_draft_to_retryable_unsubmitted(self):
        self.run_batch(FakePlatform(fail='verify'))
        self.assertEqual(read_json_strict(journal_path(self.source))['state'],'unconfirmed')
        class DraftPlatform(FakePlatform):
            def verify_published(self, chapter, deadline_seconds=3600, reconcile=False):
                self.step('verify')
                raise PublicationBlocked('reconcile_found_draft')
        with patch.object(publish,'validate_origin_plan'):
            result=publish.reconcile_batch(DraftPlatform(),[self.source],self.archive,'测试书','账号A',origin_plan={})
        self.assertNotEqual(result['exit_code'],0)
        self.assertEqual(result['reason'],'reconcile_found_draft')
        entry=read_json_strict(journal_path(self.source))
        self.assertEqual(entry['state'],'blocked_before_submit')
        self.assertNotIn('submitted_at',entry)
        self.assertEqual(entry['reason'],'reconciled_platform_draft')
        self.assertTrue(self.source.exists())

    def test_multi_chapter_reconcile_revalidates_only_remaining_queue_files(self):
        second=self.queue/'002 第2章 回信.txt';second.write_text('第二章真实正文。',encoding='utf-8')
        for source in (self.source,second):
            chapter=publish.parse_chapter(source)
            atomic_json(journal_path(source),{'schema':1,'state':'unconfirmed','book':'测试书','account':'账号A',
                **{k:v for k,v in chapter.items() if k!='body'}})
        def validate(plan,files,*args):
            self.assertTrue(all(Path(p).exists() for p in files))
        platform=FakePlatform()
        with patch.object(publish,'validate_origin_plan',side_effect=validate):
            result=publish.reconcile_batch(platform,[self.source,second],self.archive,'测试书','账号A',
                origin_plan={'chapters':[{'chapter_id':1},{'chapter_id':2}]})
        self.assertEqual(result['confirmed_count'],2)
        self.assertEqual(result['exit_code'],0)
        self.assertNotIn('submit',platform.calls)

    def test_pending_draft_and_failed_confirmations_are_refused(self):
        for status in ("草稿", "审核中", "待发布", "发布失败", "success"):
            with self.subTest(status=status):
                journal_path(self.source).unlink(missing_ok=True)
                result = self.run_batch(FakePlatform(confirmation=status))
                self.assertEqual(result["exit_code"], 2)
                self.assertEqual(result["confirmed_count"], 0)
                self.assertTrue(self.source.exists())

    def test_existing_published_is_never_edited(self):
        for status in ("已发布", "审核中", "待发布", "未知"):
            with self.subTest(status=status):
                journal_path(self.source).unlink(missing_ok=True)
                platform = FakePlatform(status=status)
                self.assertEqual(self.run_batch(platform)["exit_code"], 2)
                self.assertNotIn("open_editor", platform.calls)

    def test_explicit_draft_can_be_resumed(self):
        platform = FakePlatform(status="草稿")
        self.assertEqual(self.run_batch(platform)["exit_code"], 0)
        self.assertIn("open_editor", platform.calls)

    def test_ai_declaration_exception_stops_before_click(self):
        platform = FakePlatform(fail="settings")
        result = self.run_batch(platform)
        self.assertEqual(result["exit_code"], 2)
        self.assertNotIn("submit", platform.calls)
        self.assertEqual(read_json_strict(journal_path(self.source))["state"], "blocked_before_submit")

    def test_ai_false_setting_preserved(self):
        platform = FakePlatform()
        self.assertEqual(self.run_batch(platform, ai_used=False)["exit_code"], 0)
        self.assertFalse(platform.ai_used)

    def test_editor_or_risk_error_stops_next_chapter(self):
        other = self.queue / "002 第2章 重逢.txt"
        other.write_text("另一章。", encoding="utf-8")
        platform = FakePlatform(fail="fill")
        result = self.run_batch(platform, [self.source, other])
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(len(result["chapters"]), 1)
        self.assertNotIn("submit", platform.calls)
        self.assertTrue(other.exists())

    def test_queue_mutation_before_submit_stops(self):
        platform = FakePlatform(mutate=lambda: self.source.write_text("被修改", encoding="utf-8"))
        self.assertEqual(self.run_batch(platform)["reason"], "queue_changed")
        self.assertNotIn("submit", platform.calls)

    def test_submit_exception_keeps_uncertain_journal(self):
        result = self.run_batch(FakePlatform(fail="submit"))
        self.assertEqual(result["chapters"][0]["state"], "unconfirmed")
        self.assertTrue(self.source.exists())

    def test_journal_is_durable_before_click(self):
        platform = FakePlatform()
        def submit():
            self.assertEqual(read_json_strict(journal_path(self.source))["state"], "submitting")
            self.assertTrue(self.source.exists())
        platform.submit = submit
        self.assertEqual(self.run_batch(platform)["exit_code"], 0)

    def test_corrupt_journal_stops_without_overwriting(self):
        journal_path(self.source).write_text("{", encoding="utf-8")
        platform = FakePlatform()
        result = self.run_batch(platform)
        self.assertEqual(result["exit_code"], 2)
        self.assertNotIn("submit", platform.calls)

    def test_archive_collision_never_overwrites(self):
        self.archive.mkdir(parents=True)
        destination = self.archive / self.source.name
        destination.write_text("必须保留", encoding="utf-8")
        result = self.run_batch()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["chapters"][0]["state"], "platform_confirmed")
        self.assertEqual(destination.read_text(encoding="utf-8"), "必须保留")
        self.assertTrue(self.source.exists())

    def test_raw_automation_error_does_not_leak(self):
        platform = FakePlatform()
        def fail(*args):
            raise RuntimeError("SECRET_COOKIE_TOKEN")
        platform.submit = fail
        self.assertEqual(self.run_batch(platform)["reason"], "automation_error")
        self.assertNotIn("SECRET_COOKIE_TOKEN", self.report.read_text(encoding="utf-8"))

    def test_body_heading_removal_is_exact(self):
        self.source.write_text("我们在第10章相遇，而不是标题。\n正文。", encoding="utf-8")
        self.assertIn("我们在第10章", publish.parse_chapter(self.source)["body"])

    def test_missing_title_is_blocked(self):
        path = self.queue / "002 第2章.txt"
        path.write_text("正文", encoding="utf-8")
        with self.assertRaises(PublicationBlocked):
            publish.parse_chapter(path)

    def test_duplicate_queue_is_blocked_before_platform(self):
        other = self.queue / "001 第1章 同章.txt"
        other.write_text("另一份正文", encoding="utf-8")
        platform = FakePlatform()
        self.assertEqual(self.run_batch(platform, [self.source, other])["exit_code"], 2)
        self.assertEqual(platform.calls, [])

    def test_count_uses_numeric_chapter_order(self):
        for number in (10, 2):
            (self.queue / f"{number} 第{number}章 标题.txt").write_text("正文", encoding="utf-8")
        args = argparse.Namespace(book="测试书", queue_book="测试书", count=2, volume=None)
        with patch.object(publish, "CHAPTERS_DIR", str(self.root / "chapters")), patch.object(publish, "UPLOADED_DIR", str(self.root / "uploaded")):
            _, files, _, _ = publish.select_plan(args)
        self.assertEqual([publish.parse_chapter(p)["chapter_id"] for p in files], [1, 2])

    def test_legacy_archive_blocks_duplicate(self):
        self.archive.mkdir(parents=True)
        (self.archive / self.source.name).write_text("历史正文", encoding="utf-8")
        args = argparse.Namespace(book="测试书", queue_book="测试书", count=1, volume=None)
        with patch.object(publish, "CHAPTERS_DIR", str(self.root / "chapters")), patch.object(publish, "UPLOADED_DIR", str(self.root / "uploaded")):
            with self.assertRaisesRegex(PublicationBlocked, "chapter_already_archived"):
                publish.select_plan(args)


class BridgePublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_AI_CONFIG": str(self.root / "offline-ai.json")}))
        self.project = self.root / "project"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        self.source = self.project / "正文" / "第1章 初见.md"
        self.source.write_text("# 第1章 初见\n\n正文。\n", encoding="utf-8")
        self.fanqie = self.root / "fanqie_auto_publish"
        self.fanqie.mkdir()
        (self.fanqie / "publish.py").write_text("# subprocess is mocked", encoding="utf-8")
        for key, value in {"FANQIE_ROOT": self.fanqie, "QUEUE_ROOT": self.fanqie / "chapters",
                           "UPLOADED_ROOT": self.fanqie / "uploaded", "MANIFEST_PATH": self.root / "manifest.json",
                           "ACCOUNTS_ROOT": self.root / "accounts", "RUNTIME_ROOT": self.root / "runtime"}.items():
            active = patch.object(bridge, key, value)
            active.start()
            self.addCleanup(active.stop)
        self.addCleanup(self.temp.cleanup)
        for name in ("账号A", "账号B"):
            state = bridge.account_state_path(name)
            state.parent.mkdir(parents=True)
            state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        self.review()
        bridge.stage_project(self.project, "测试书")
        self.queue_file = next((self.fanqie / "chapters" / "测试书").glob("*.txt"))

    def review(self):
        atomic_json(self.project / ".webnovel" / "writer_receipts.json", {
            "1": {"destination": str(self.source.resolve()), "sha256": digest_file(self.source),
                  "review": {"success": True, "review_decision": "pass", "needs_revision": False}}})

    def test_reviewed_origin_passes(self):
        plan = bridge.validate_queue_origin("测试书", self.project, "账号A")
        self.assertEqual(plan["chapters"][0]["file_sha256"], digest_file(self.queue_file))

    def test_uncertain_queue_requires_explicit_readonly_plan_not_submit_plan(self):
        chapter=publish.parse_chapter(self.queue_file)
        atomic_json(journal_path(self.queue_file),{'state':'unconfirmed','book':'测试书','account':'账号A',
            **{k:v for k,v in chapter.items() if k!='body'}})
        with self.assertRaises(ValueError):bridge.validate_queue_origin('测试书',self.project,'账号A')
        plan=bridge.validate_queue_origin('测试书',self.project,'账号A',reconcile_only=True)
        self.assertTrue(plan['reconcile_only'])
        platform=FakePlatform()
        result=publish.publish_batch(platform,[self.queue_file],self.fanqie/'uploaded'/'测试书',
            '测试书','账号A',origin_plan=plan)
        self.assertEqual(result['reason'],'readonly_plan_not_submittable')
        self.assertEqual(platform.calls,[])

    def test_author_minimum_length_is_checked_again_by_bridge_and_child(self):
        plan = bridge.validate_queue_origin("测试书", self.project, "账号A")
        atomic_json(self.project / '.webnovel' / 'publication_policy.json', {'min_body_chars':5001})
        with self.assertRaisesRegex(ValueError, '最低5001'):
            bridge.validate_queue_origin("测试书", self.project, "账号A")
        with self.assertRaisesRegex(ValueError, '最低5001'):
            publish.validate_origin_plan(plan, [self.queue_file], "测试书", "账号A")

    def test_new_contract_blocks_old_receipt_at_bridge_and_child(self):
        plan = bridge.validate_queue_origin("测试书", self.project, "账号A")
        atomic_json(self.project / ".webnovel" / "creative_brief.json", {"schema":1,"revision":1,"brief":{"style":"克制叙述"},"history":[]})
        with self.assertRaisesRegex(ValueError,"创作约定"):
            bridge.validate_queue_origin("测试书", self.project, "账号A")
        with self.assertRaisesRegex(PublicationBlocked,"origin_review_or_content_mismatch"):
            publish.validate_origin_plan(plan,[self.queue_file],"测试书","账号A")
        receipts = read_json_strict(self.project / ".webnovel" / "writer_receipts.json")
        receipts["1"]["creative_contract_hash"] = bridge.creative_contract_hash(self.project)
        atomic_json(self.project / ".webnovel" / "writer_receipts.json", receipts)
        self.assertEqual(bridge.validate_queue_origin("测试书",self.project,"账号A")["chapters"][0]["chapter_id"],1)
        publish.validate_origin_plan(plan,[self.queue_file],"测试书","账号A")

    def test_other_project_is_rejected(self):
        with self.assertRaises(ValueError):
            bridge.validate_queue_origin("测试书", self.root / "other", "账号A")

    def test_same_book_from_other_project_rejected_without_mutation(self):
        before = bridge.MANIFEST_PATH.read_bytes()
        other = self.root / "other"
        (other / "正文").mkdir(parents=True)
        with self.assertRaises(ValueError):
            bridge.stage_project(other, "测试书")
        self.assertEqual(bridge.MANIFEST_PATH.read_bytes(), before)

    def test_source_mutation_invalidates_review(self):
        self.source.write_text("# 第1章 初见\n修改后正文", encoding="utf-8")
        with self.assertRaises(ValueError):
            bridge.validate_queue_origin("测试书", self.project, "账号A")

    def test_queue_mutation_is_rejected(self):
        self.queue_file.write_text("非源正文", encoding="utf-8")
        with self.assertRaises(ValueError):
            bridge.validate_queue_origin("测试书", self.project, "账号A")

    def test_missing_review_is_rejected(self):
        (self.project / ".webnovel" / "writer_receipts.json").unlink()
        with self.assertRaises(ValueError):
            bridge.validate_queue_origin("测试书", self.project, "账号A")

    def test_cross_account_binding_is_rejected(self):
        manifest = bridge.load_manifest()
        manifest["books"]["测试书"]["account"] = "账号A"
        bridge.save_manifest(manifest)
        with self.assertRaises(ValueError):
            bridge.validate_queue_origin("测试书", self.project, "账号B")

    def test_exit_zero_alone_is_rejected(self):
        with patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(bridge.run_publish("测试书", count=1, account="账号A", project=self.project), 2)
        report = bridge.latest_publish_report("测试书", "账号A")
        self.assertFalse(report["verified_success"])
        self.assertEqual(report["subprocess_exit_code"], 0)
        self.assertTrue(self.queue_file.exists())

    def test_explicit_interface_and_true_evidence(self):
        root_state = self.fanqie / "state.json"
        root_state.write_text("LEGACY_SENTINEL", encoding="utf-8")
        def child(command, **kwargs):
            self.assertNotIn("input", kwargs)
            self.assertEqual(command[command.index("--state-file") + 1], str(bridge.account_state_path("账号A")))
            self.assertEqual(command[command.index("--book") + 1], "测试书")
            report = Path(command[command.index("--report") + 1])
            origin = read_json_strict(command[command.index("--plan") + 1])
            result = publish.publish_batch(FakePlatform(), [self.queue_file], self.fanqie / "uploaded" / "测试书",
                                           "测试书", "账号A", report=report, origin_plan=origin)
            return subprocess.CompletedProcess(command, result["exit_code"])
        with patch.object(bridge.subprocess, "run", side_effect=child):
            self.assertEqual(bridge.run_publish("测试书", count=1, account="账号A", project=self.project), 0)
        self.assertEqual(root_state.read_text(encoding="utf-8"), "LEGACY_SENTINEL")
        self.assertTrue(bridge.latest_publish_report("测试书", "账号A")["verified_success"])
        archived = self.fanqie / "uploaded" / "测试书" / self.queue_file.name
        journal_path(archived).unlink()
        self.assertFalse(bridge.latest_publish_report("测试书", "账号A")["verified_success"])

    def test_child_revalidates_review_before_submit(self):
        origin = bridge.validate_queue_origin("测试书", self.project, "账号A")
        platform = FakePlatform(mutate=lambda: self.source.write_text("changed", encoding="utf-8"))
        result = publish.publish_batch(platform, [self.queue_file], self.fanqie / "uploaded" / "测试书",
                                       "测试书", "账号A", origin_plan=origin)
        self.assertEqual(result["exit_code"], 2)
        self.assertNotIn("submit", platform.calls)

    def test_corrupt_manifest_is_preserved(self):
        bridge.MANIFEST_PATH.write_text("{", encoding="utf-8")
        with self.assertRaises(PublicationBlocked):
            bridge.sync_manifest()
        self.assertEqual(bridge.MANIFEST_PATH.read_text(encoding="utf-8"), "{")

    def test_ambiguous_attempt_cannot_be_restaged_even_force(self):
        atomic_json(journal_path(self.queue_file), {"state": "unconfirmed"})
        with self.assertRaises(ValueError):
            bridge.stage_project(self.project, "测试书", force=True)
        self.assertEqual(read_json_strict(journal_path(self.queue_file))["state"], "unconfirmed")

    def test_account_path_alias_is_rejected(self):
        for name in ("../账号A", "账号A.", "账号/A", "CON"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bridge.account_dir(name)

    def test_book_runtime_is_reentrant_with_stage(self):
        with bridge.book_runtime(self.project, "测试书"):
            self.assertEqual(bridge.stage_project(self.project, "测试书")["staged_count"], 0)
            bridge.validate_queue_origin("测试书", self.project, "账号A")


class LockTest(unittest.TestCase):
    def test_other_thread_refused_and_nested_owner_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lock"
            errors = []
            def contend():
                try:
                    with file_lock(path):
                        errors.append("entered")
                except PublicationBlocked:
                    errors.append("busy")
            with file_lock(path):
                with file_lock(path):
                    thread = threading.Thread(target=contend)
                    thread.start()
                    thread.join(5)
                self.assertEqual(errors, ["busy"])
            with file_lock(path):
                self.assertTrue(path.exists())

    def test_os_lock_released_after_child_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lock"
            code = "import os,sys; sys.path.insert(0,os.environ['PYTHONPATH']); from fanqie_auto_publish.publication_safety import file_lock; lock=file_lock(sys.argv[1]); lock.__enter__(); print('locked',flush=True); sys.stdin.readline(); os._exit(7)"
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(bridge.__file__).resolve().parent.parent)
            child = subprocess.Popen([sys.executable, "-c", code, str(path)], env=environment,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                with self.assertRaises(PublicationBlocked):
                    with file_lock(path):
                        pass
                child.communicate("crash\n", timeout=10)
                self.assertEqual(child.returncode, 7)
                with file_lock(path):
                    self.assertTrue(path.exists())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
