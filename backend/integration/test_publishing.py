"""0.10.0：平台契约、导出、只读登记与获准单章。"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integration import bridge, publishing as pub


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


TITLE = "潮声"
BODY = "林砚推开门。\n\n屋里没有人。\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "潮汐钟"
        (self.project / ".webnovel").mkdir(parents=True)
        pub.clear_adapters()

    def ready(self, platform="fanqie", account="acc", book="b-1", chapter=1):
        pub.set_target_platform(self.project, platform, account=account,
                                platform_book_id=book, book="潮汐钟")
        pub.bind_book(self.project, platform=platform, account=account,
                      platform_book_id=book, title="潮汐钟", verified_via="manual",
                      observed_chapters=[1])
        pub.authorize(self.project, platform=platform, account=account,
                      platform_book_id=book, chapters=[chapter],
                      note="作者本人在 09:00 授权第1章试投")


class CapabilityTest(Base):
    def test_two_platforms_and_unknown_is_refused(self):
        rows = {row["platform"]: row for row in pub.capabilities()}
        self.assertEqual(set(rows), {"fanqie", "qimao"})
        self.assertTrue(rows["fanqie"]["publishable"])
        self.assertFalse(rows["qimao"]["publishable"])
        self.assertEqual(rows["qimao"]["submission"], "manual_upload")
        with self.assertRaises(pub.PublishError):
            pub.capabilities("qidian")

    def test_unknown_platform_cannot_be_target(self):
        with self.assertRaises(pub.PublishError):
            pub.set_target_platform(self.project, "qidian")
        with self.assertRaises(pub.PublishError):
            pub.export_chapter(self.project, platform="qidian", chapter=1,
                               title=TITLE, body=BODY)

    def test_none_capability_is_not_publishable(self):
        with patch.dict(pub.CAPABILITIES["fanqie"], {"can_schedule": None}):
            row = pub.capabilities("fanqie")[0]
            self.assertFalse(row["publishable"])

    def test_target_roundtrip_keeps_identity(self):
        pub.set_target_platform(self.project, "qimao", account="qm-acc",
                                platform_book_id="qm-9", book="潮汐钟")
        target = pub.target_platform(self.project)
        self.assertEqual(target["platform"], "qimao")
        self.assertEqual(target["account"], "qm-acc")
        self.assertEqual(target["platform_book_id"], "qm-9")


class ExportTest(Base):
    def test_export_writes_file_and_manifest_without_uploading(self):
        result = pub.export_chapter(self.project, platform="qimao", chapter=2,
                                    title=TITLE, body=BODY, account="qm-acc",
                                    platform_book_id="qm-9")
        self.assertEqual(result["status"], "exported")
        self.assertFalse(result["uploaded"])
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("第2章 潮声"))
        self.assertIn("林砚推开门。", text)
        manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["items"][0]["sha256"], result["sha256"])
        self.assertEqual(manifest["items"][0]["chapter"], 2)

    def test_empty_body_and_oversized_chapter_are_refused(self):
        with self.assertRaises(pub.PublishError):
            pub.export_chapter(self.project, platform="qimao", chapter=1,
                               title=TITLE, body="  \n\n ")
        with patch.object(pub, "MAX_EXPORT_BYTES", 10):
            with self.assertRaises(pub.PublishError):
                pub.export_chapter(self.project, platform="qimao", chapter=1,
                                   title=TITLE, body=BODY)

    def test_title_gets_chapter_prefix_once(self):
        built = pub.format_chapter(3, "第3章 潮声", BODY, platform="qimao")
        self.assertEqual(built["title"], "第3章 潮声")
        built = pub.format_chapter(3, "", BODY, platform="qimao")
        self.assertEqual(built["title"], "第3章")

    def test_second_export_replaces_same_chapter_in_manifest(self):
        for body in (BODY, BODY + "她回来了。\n"):
            pub.export_chapter(self.project, platform="qimao", chapter=2,
                               title=TITLE, body=body, account="qm", platform_book_id="b")
        items = pub.exports(self.project, platform="qimao", account="qm",
                            platform_book_id="b")["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["chapter"], 2)


class BindingAndAuthorizationTest(Base):
    def test_manual_binding_is_registered_not_verified(self):
        record = pub.bind_book(self.project, platform="qimao", account="qm",
                               platform_book_id="b", observed_chapters=[1, 2])
        self.assertEqual(record["status"], "registered")
        claimed = pub.bind_book(self.project, platform="qimao", account="qm1",
                                platform_book_id="b1", verified_via="readonly_probe",
                                observed_chapters=[1])
        self.assertEqual(claimed["status"], "registered")
        self.assertIn("证据", claimed["note"])
        verified = pub.bind_book(self.project, platform="qimao", account="qm2",
                                 platform_book_id="b2", verified_via="readonly_probe",
                                 observed_chapters=[1],
                                 probe_evidence={"platform": "qimao",
                                                 "platform_book_id": "b2",
                                                 "chapters": [1]})
        self.assertEqual(verified["status"], "verified")

    def test_binding_requires_identity_and_known_source(self):
        with self.assertRaises(pub.PublishError):
            pub.bind_book(self.project, platform="qimao", account="", platform_book_id="b")
        with self.assertRaises(pub.PublishError):
            pub.bind_book(self.project, platform="qimao", account="a", platform_book_id="b",
                          verified_via="guess")

    def test_authorization_requires_note_and_binds_scope(self):
        with self.assertRaises(pub.PublishError):
            pub.authorize(self.project, platform="fanqie", account="a",
                          platform_book_id="b", chapters=[1], note="")
        with self.assertRaises(pub.PublishError):
            pub.authorize(self.project, platform="fanqie", account="a",
                          platform_book_id="b", chapters=[], note="有依据")
        pub.authorize(self.project, platform="fanqie", account="a", platform_book_id="b",
                      chapters=[1], note="第一次")
        pub.authorize(self.project, platform="fanqie", account="a", platform_book_id="b",
                      chapters=[2], note="第二次")
        items = pub.load_authorizations(self.project)["items"]
        self.assertEqual(len(items), 2)
        active = [item for item in items if item.get("active")]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["chapters"], [2])
        revoked = [item for item in items if not item.get("active")]
        self.assertEqual(len(revoked), 1)
        self.assertTrue(revoked[0].get("revoked_at"))
        self.assertEqual(revoked[0]["note"], "第一次")
        self.assertEqual(pub.authorization_for(self.project, platform="fanqie", account="a",
                                               platform_book_id="b", chapter=1), {})
        self.assertTrue(pub.authorization_for(self.project, platform="fanqie", account="a",
                                              platform_book_id="b", chapter=2))

    def test_expired_authorization_is_not_used(self):
        pub.authorize(self.project, platform="fanqie", account="a", platform_book_id="b",
                      chapters=[1], note="过期授权", expires_at="2020-01-01T00:00:00+08:00")
        self.assertEqual(pub.authorization_for(self.project, platform="fanqie", account="a",
                                               platform_book_id="b", chapter=1), {})


class SubmitGateTest(Base):
    def test_second_platform_never_calls_adapter(self):
        adapter = Adapter()
        pub.register_adapter("qimao", adapter)
        pub.set_target_platform(self.project, "qimao", account="qm", platform_book_id="b")
        result = pub.submit_chapter(self.project, platform="qimao", account="qm",
                                    platform_book_id="b", chapter=1, title=TITLE, body=BODY)
        self.assertEqual(result["status"], "refused")
        self.assertIn("导出", result["reason"])
        self.assertEqual(adapter.calls, [])

    def test_missing_adapter_binding_and_authorization_are_separate(self):
        no_adapter = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                        platform_book_id="b", chapter=1,
                                        title=TITLE, body=BODY)
        self.assertEqual(no_adapter["status"], "unavailable")
        pub.register_adapter("fanqie", Adapter())
        no_binding = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                        platform_book_id="b", chapter=1,
                                        title=TITLE, body=BODY)
        self.assertEqual(no_binding["status"], "refused")
        self.assertIn("只读绑定", no_binding["reason"])
        pub.bind_book(self.project, platform="fanqie", account="acc", platform_book_id="b")
        no_auth = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                     platform_book_id="b", chapter=1,
                                     title=TITLE, body=BODY)
        self.assertEqual(no_auth["status"], "refused")
        self.assertIn("授权", no_auth["reason"])


class SubmitTest(Base):
    def setUp(self):
        super().setUp()
        self.ready()

    def test_accepted_writes_once_and_matches_body(self):
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        built = pub.format_chapter(1, TITLE, BODY, platform="fanqie")
        adapter.echo = built["sha256"]
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title=TITLE, body=BODY)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["writes_confirmed"], 1)
        self.assertTrue(result["body_matches"])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0]["body_sha256"], built["sha256"])
        entry = pub.ledger_entry(self.project, platform="fanqie", account="acc",
                                 platform_book_id="b-1", chapter=1,
                                 body_sha256=built["sha256"])
        self.assertEqual(entry["state"], "accepted")

    def test_duplicate_is_refused_before_adapter(self):
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        pub.submit_chapter(self.project, platform="fanqie", account="acc",
                           platform_book_id="b-1", chapter=1, title=TITLE, body=BODY)
        again = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                   platform_book_id="b-1", chapter=1, title=TITLE, body=BODY)
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(len(adapter.calls), 1)

    def test_new_version_of_same_chapter_gets_its_own_ledger(self):
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        pub.submit_chapter(self.project, platform="fanqie", account="acc",
                           platform_book_id="b-1", chapter=1, title=TITLE, body=BODY)
        changed = BODY.replace("没有人", "只有风")
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title=TITLE, body=changed)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(adapter.calls), 2)

    def test_unknown_result_is_recorded_and_not_retried(self):
        adapter = Adapter(raises=TimeoutError("网关超时"))
        pub.register_adapter("fanqie", adapter)
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title=TITLE, body=BODY)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["writes_attempted"], 1)
        self.assertEqual(result["writes_confirmed"], 0)
        again = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                   platform_book_id="b-1", chapter=1,
                                   title=TITLE, body=BODY)
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(len(adapter.calls), 1)

    def test_unaccepted_response_is_unknown(self):
        adapter = Adapter(accepted=False)
        pub.register_adapter("fanqie", adapter)
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title=TITLE, body=BODY)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("未确认接收", result["reason"])

    def test_body_mismatch_is_visible(self):
        adapter = Adapter(echo="f" * 64)
        pub.register_adapter("fanqie", adapter)
        result = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                    platform_book_id="b-1", chapter=1,
                                    title=TITLE, body=BODY)
        self.assertEqual(result["status"], "mismatch")
        self.assertFalse(result["body_matches"])
        self.assertEqual(result["writes_confirmed"], 0)

    def test_reconcile_resolves_unknown(self):
        adapter = Adapter(raises=TimeoutError("超时"))
        pub.register_adapter("fanqie", adapter)
        built = pub.format_chapter(1, TITLE, BODY, platform="fanqie")
        pub.submit_chapter(self.project, platform="fanqie", account="acc",
                           platform_book_id="b-1", chapter=1, title=TITLE, body=BODY)
        done = pub.reconcile(self.project, platform="fanqie", account="acc",
                             platform_book_id="b-1", chapter=1,
                             body_sha256=built["sha256"], resolution="accepted",
                             note="平台侧已出现该章",
                             evidence="fanqie 后台第1章状态=已发布")
        self.assertEqual(done["state"], "accepted")
        with self.assertRaises(pub.PublishError):
            pub.reconcile(self.project, platform="fanqie", account="acc",
                          platform_book_id="b-1", chapter=1,
                          body_sha256=built["sha256"], resolution="abandoned",
                          note="再改一次", evidence="同一证据")
        with self.assertRaises(pub.PublishError):
            pub.reconcile(self.project, platform="fanqie", account="acc",
                          platform_book_id="b-1", chapter=1,
                          body_sha256=built["sha256"], resolution="maybe")
        with self.assertRaises(pub.PublishError):
            pub.reconcile(self.project, platform="fanqie", account="acc",
                          platform_book_id="b-1", chapter=9,
                          body_sha256="a" * 64, resolution="accepted",
                          note="无记录", evidence="无")
        with self.assertRaises(pub.PublishError):
            pub.reconcile(self.project, platform="fanqie", account="acc",
                          platform_book_id="b-1", chapter=1,
                          body_sha256=built["sha256"], resolution="abandoned",
                          note="缺证据")


class MigrationTest(Base):
    def test_requires_identity_and_copies_once(self):
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"):
            missing = pub.migrate_legacy(self.project, book="潮汐钟")
            self.assertEqual(missing["status"], "needs_review")
            source = Path(bridge.QUEUE_ROOT) / bridge.safe_dir_name("潮汐钟")
            source.mkdir(parents=True)
            (source / "第0001章 潮声.txt").write_text("第一版正文", encoding="utf-8")
            first = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(first["status"], "migrated")
            self.assertEqual(first["copied"], 1)
            second = pub.migrate_legacy(self.project, account="acc",
                                        platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(second["status"], "already_migrated")
            self.assertEqual(second["copied"], 0)
            copied = Path(first["entries"][0]["dest"])
            self.assertEqual(copied.read_text(encoding="utf-8"), "第一版正文")

    def test_empty_legacy_returns_nothing_to_migrate(self):
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"), \
                patch.object(bridge, "UPLOADED_ROOT", Path(self.temp.name) / "archive"):
            result = pub.migrate_legacy(self.project, account="acc",
                                        platform_book_id="b-1", book="潮汐钟")
        self.assertEqual(result["status"], "nothing_to_migrate")

    def test_missing_book_name_is_not_guessed(self):
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"):
            result = pub.migrate_legacy(self.project, account="acc", platform_book_id="b-1")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("书名", result["reason"])
        self.assertEqual(result["copied"], 0)

    def test_identical_text_in_two_chapters_is_copied_twice(self):
        # 同文不同章不能被「同摘要去重」吞掉，否则会丢章。
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"):
            source = Path(bridge.QUEUE_ROOT) / bridge.safe_dir_name("潮汐钟")
            source.mkdir(parents=True)
            (source / "第0001章 潮声.txt").write_text("同样的正文", encoding="utf-8")
            (source / "第0002章 潮声.txt").write_text("同样的正文", encoding="utf-8")
            first = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(first["copied"], 2)
            second = pub.migrate_legacy(self.project, account="acc",
                                        platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(second["copied"], 0)
            self.assertEqual(second["skipped"], 2)

    def test_export_refuses_when_namespace_is_a_link(self):
        if os.name != "nt":
            self.skipTest("仅在 Windows 上验证目录联接")
        target = Path(self.temp.name) / "outside"
        target.mkdir(parents=True)
        folder = pub.namespace(self.project, "fanqie", account="acc",
                               platform_book_id="b-1")
        folder.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(folder), str(target)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("无法创建目录联接")
        with self.assertRaises(pub.PublishError) as caught:
            pub.export_chapter(self.project, platform="fanqie", chapter=1,
                               title=TITLE, body=BODY, account="acc",
                               platform_book_id="b-1")
        self.assertIn("越界", str(caught.exception))


class StatusTest(Base):
    def test_status_lists_everything_without_writing(self):
        self.ready()
        pub.export_chapter(self.project, platform="fanqie", chapter=1, title=TITLE,
                           body=BODY, account="acc", platform_book_id="b-1")
        before = sorted(path.name for path in Path(self.temp.name).rglob("*") if path.is_file())
        report = pub.status(self.project)
        after = sorted(path.name for path in Path(self.temp.name).rglob("*") if path.is_file())
        self.assertEqual(before, after)
        self.assertEqual(report["target"]["platform"], "fanqie")
        self.assertEqual(len(report["platforms"]), 2)
        self.assertEqual(report["exports"]["fanqie"]["items"][0]["chapter"], 1)
        self.assertEqual(len(report["bindings"]), 1)
        self.assertEqual(len(report["authorizations"]), 1)

    def test_status_is_empty_on_fresh_project(self):
        report = pub.status(self.project)
        self.assertEqual(report["target"], {})
        self.assertEqual(report["ledger"], [])
        self.assertFalse((self.project / ".webnovel" / "publish").exists())


class Audit100RegressionTest(Base):
    def test_accounts_get_separate_namespaces(self):
        pub.export_chapter(self.project, platform="fanqie", chapter=1, title=TITLE,
                           body=BODY, account="acc-a", platform_book_id="b-1")
        pub.export_chapter(self.project, platform="fanqie", chapter=1, title=TITLE,
                           body=BODY.replace("没有人", "只有风"), account="acc-b",
                           platform_book_id="b-1")
        first = pub.exports(self.project, platform="fanqie", account="acc-a",
                            platform_book_id="b-1")
        second = pub.exports(self.project, platform="fanqie", account="acc-b",
                             platform_book_id="b-1")
        self.assertNotEqual(first["items"][0]["sha256"], second["items"][0]["sha256"])
        self.assertNotEqual(first["folder"], second["folder"])
        self.assertTrue(Path(first["folder"]).is_dir())
        self.assertTrue(Path(second["folder"]).is_dir())

    def test_ledger_key_separates_platform(self):
        adapter = Adapter()
        pub.register_adapter("fanqie", adapter)
        self.ready()
        sha = pub.format_chapter(1, TITLE, BODY, platform="fanqie")["sha256"]
        accepted = pub.submit_chapter(self.project, platform="fanqie", account="acc",
                                      platform_book_id="b-1", chapter=1,
                                      title=TITLE, body=BODY)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(pub.ledger_entry(self.project, platform="fanqie", account="acc",
                                          platform_book_id="b-1", chapter=1,
                                          body_sha256=sha)["state"], "accepted")
        self.assertEqual(pub.ledger_entry(self.project, platform="qimao", account="acc",
                                          platform_book_id="b-1", chapter=1,
                                          body_sha256=sha), {})
        self.assertEqual(len(adapter.calls), 1)

    def test_authorizing_one_book_keeps_the_other(self):
        pub.authorize(self.project, platform="fanqie", account="acc",
                      platform_book_id="b-1", chapters=[1], note="书一")
        pub.authorize(self.project, platform="fanqie", account="acc",
                      platform_book_id="b-2", chapters=[1], note="书二")
        first = pub.authorization_for(self.project, platform="fanqie", account="acc",
                                      platform_book_id="b-1", chapter=1)
        second = pub.authorization_for(self.project, platform="fanqie", account="acc",
                                       platform_book_id="b-2", chapter=1)
        self.assertEqual(first["note"], "书一")
        self.assertEqual(second["note"], "书二")

    def test_corrupt_manifest_is_replaced_not_fatal(self):
        folder = pub.namespace(self.project, "fanqie", account="acc",
                               platform_book_id="b-1") / pub.EXPORT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text("[1, 2]", encoding="utf-8")
        result = pub.export_chapter(self.project, platform="fanqie", chapter=1,
                                    title=TITLE, body=BODY, account="acc",
                                    platform_book_id="b-1")
        self.assertEqual(result["status"], "exported")
        listing = pub.exports(self.project, platform="fanqie", account="acc",
                              platform_book_id="b-1")
        self.assertTrue(listing["corrupt"])
        self.assertEqual(len(listing["items"]), 1)

    def test_over_long_body_is_refused_before_writing(self):
        with self.assertRaises(pub.PublishError) as caught:
            pub.export_chapter(self.project, platform="fanqie", chapter=1,
                               title=TITLE, body="字" * (pub.MAX_EXPORT_BYTES),
                               account="acc", platform_book_id="b-1")
        self.assertIn("字节", str(caught.exception))


class Audit101RegressionTest(Base):
    """audit-101 指出的「改坏也绿」的四处，各补一条能变红的用例。"""

    def test_corrupt_ledger_is_counted_not_hidden(self):
        folder = pub.namespace(self.project, "fanqie", account="acc",
                               platform_book_id="b-1") / pub.LEDGER_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "0123456789abcdef.json").write_text("{bad", encoding="utf-8")
        (folder / "fedcba9876543210.json").write_text("[]", encoding="utf-8")
        report = pub.status(self.project)
        self.assertEqual(report["corrupt_ledgers"], 2)
        self.assertEqual(report["ledger"], [])

    def test_status_does_not_write_ledgers(self):
        folder = pub.namespace(self.project, "fanqie", account="acc",
                               platform_book_id="b-1") / pub.LEDGER_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "0123456789abcdef.json"
        path.write_text('{"state": "accepted"}', encoding="utf-8")
        before = path.read_bytes()
        pub.status(self.project)
        self.assertEqual(path.read_bytes(), before)

    def test_migration_conflict_keeps_existing_target(self):
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"):
            source = Path(bridge.QUEUE_ROOT) / bridge.safe_dir_name("潮汐钟")
            source.mkdir(parents=True)
            (source / "第0001章 潮声.txt").write_text("旧正文", encoding="utf-8")
            dest = pub.namespace(self.project, "fanqie", account="acc",
                                 platform_book_id="b-1") / "queue" / "第0001章.txt"
            dest.parent.mkdir(parents=True)
            dest.write_text("作者已手改过的正文", encoding="utf-8")
            result = pub.migrate_legacy(self.project, account="acc",
                                        platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(len(result["conflicts"]), 1)
            self.assertEqual(result["copied"], 0)
            self.assertEqual(dest.read_text(encoding="utf-8"), "作者已手改过的正文")
            ledger = json.loads((pub.namespace(self.project, "fanqie", account="acc",
                                               platform_book_id="b-1")
                                 / pub.MIGRATION_NAME).read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["conflicts"]), 1)

    def test_interrupted_copy_is_recovered_on_rerun(self):
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"):
            source = Path(bridge.QUEUE_ROOT) / bridge.safe_dir_name("潮汐钟")
            source.mkdir(parents=True)
            (source / "第0001章 潮声.txt").write_text("已写完的正文", encoding="utf-8")
            first = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(first["copied"], 1)
            ledger_path = (pub.namespace(self.project, "fanqie", account="acc",
                                         platform_book_id="b-1") / pub.MIGRATION_NAME)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["entries"][0]["state"] = "copying"
            ledger["entries"][0]["verified"] = False
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            again = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(again["copied"], 1)
            self.assertTrue(again["entries"][0]["verified"])
            self.assertEqual(again["entries"][0]["state"], "copied")
            third = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(third["copied"], 0)
            self.assertEqual(third["skipped"], 1)

    def test_pending_entry_with_missing_target_is_copied_again(self):
        # 台账写着 copying、目标文件却不存在（崩溃在复制前后）：必须重新写，而不是当成已完成。
        with patch.object(bridge, "QUEUE_ROOT", Path(self.temp.name) / "queue"):
            source = Path(bridge.QUEUE_ROOT) / bridge.safe_dir_name("潮汐钟")
            source.mkdir(parents=True)
            (source / "第0001章 潮声.txt").write_text("崩溃前没写完的正文", encoding="utf-8")
            first = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(first["copied"], 1)
            target = Path(first["entries"][0]["dest"])
            target.unlink()
            ledger_path = (pub.namespace(self.project, "fanqie", account="acc",
                                         platform_book_id="b-1") / pub.MIGRATION_NAME)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["entries"][0]["state"] = "copying"
            ledger["entries"][0]["verified"] = False
            ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
            again = pub.migrate_legacy(self.project, account="acc",
                                       platform_book_id="b-1", book="潮汐钟")
            self.assertEqual(again["copied"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "崩溃前没写完的正文")

    def test_probe_evidence_needs_every_observed_chapter(self):
        evidence = {"platform": "fanqie", "platform_book_id": "b-1", "chapters": [1]}
        partial = pub.bind_book(self.project, platform="fanqie", account="acc",
                                platform_book_id="b-1", title="潮汐钟",
                                verified_via="readonly_probe", observed_chapters=[1, 2],
                                probe_evidence=evidence)
        self.assertEqual(partial["status"], "registered")
        self.assertIn("探测证据", partial["note"])
        full = pub.bind_book(self.project, platform="fanqie", account="acc",
                             platform_book_id="b-1", title="潮汐钟",
                             verified_via="readonly_probe", observed_chapters=[1],
                             probe_evidence=evidence)
        self.assertEqual(full["status"], "verified")

    def test_export_checks_bounds_before_creating_directories(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        folder = pub.namespace(self.project, "fanqie", account="acc",
                               platform_book_id="b-1")
        folder.mkdir(parents=True, exist_ok=True)
        link = folder / pub.EXPORT_DIR
        made = True
        if hasattr(os, "symlink"):
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError:
                made = False
        if not made:
            self.skipTest("当前账户不能创建符号链接")
        with self.assertRaises(pub.PublishError) as caught:
            pub.export_chapter(self.project, platform="fanqie", chapter=2, title=TITLE,
                               body=BODY, account="acc", platform_book_id="b-1")
        self.assertIn("越界", str(caught.exception))
        self.assertFalse((outside / "第0002章.txt").exists())
