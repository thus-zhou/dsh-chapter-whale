"""0.9.4：单目标浏览器与登录试点的离线验收。

全部用替身适配器；本文件不启动任何真实浏览器，也不产生平台写入。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from integration import browser_target as bt, writer_runner as writer


class FakeBrowser:
    def __init__(self, *, fail=None, started=True, row=None, accepted=True, publish_error=None):
        self.fail = fail
        self.started = started
        self.row = row
        self.accepted = accepted
        self.publish_error = publish_error
        self.calls = []
        self.closed = False

    def launch(self, **kwargs):
        self.calls.append(("launch", kwargs))
        if self.fail == "missing":
            raise FileNotFoundError("chromium")
        if self.fail == "denied":
            raise PermissionError("profile")
        if self.fail == "timeout":
            raise TimeoutError("扫码未完成")
        return {"started": self.started, "profile": kwargs.get("profile")}

    def health(self):
        return {"ok": True, "ready": True}

    def close(self):
        self.closed = True
        return True

    def read_chapter(self, *, book_id, chapter):
        if self.fail == "needs_human":
            raise bt.AdapterNeedsHuman("验证码未完成")
        if self.row is not None:
            return self.row
        return {"platform": "fanqie", "account": "acc", "book_id": book_id,
                "chapter_id": chapter, "content_sha256": "c" * 64}

    def publish_chapter(self, **kwargs):
        self.calls.append(("publish", kwargs))
        if self.publish_error is not None:
            raise self.publish_error
        return {"accepted": self.accepted}


class BrowserTargetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=writer.COMBINED_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "作品 潮汐 钟"
        self.project.mkdir(parents=True)

    def target(self, **overrides):
        values = {"os": "windows", "arch": "amd64", "runtime": "native",
                  "browser": "chromium", "browser_version": "131.0",
                  "driver": "playwright", "credential": "reconfigured",
                  "scope": "read_only"}
        values.update(overrides)
        return values

    def test_target_requires_every_field(self):
        broken = self.target()
        broken.pop("driver")
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.save_target(self.project, broken)
        self.assertIn("driver", str(caught.exception))

    def test_publish_scope_needs_authorization(self):
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.save_target(self.project, self.target(scope="publish"))
        self.assertIn("授权", str(caught.exception))
        saved = bt.save_target(self.project, self.target(scope="publish",
                                                          authorization="作者授权：书 A 第 3 章"))
        self.assertEqual(saved["scope"], "publish")

    def test_profile_must_stay_inside_project(self):
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.save_target(self.project, self.target(profile=str(Path(self.temp.name) / "outside")))
        self.assertIn("作品目录内", str(caught.exception))

    def test_profile_symlink_is_refused(self):
        real = Path(self.temp.name) / "real-profile"
        real.mkdir()
        link = bt.profile_path(self.project)
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("本机不支持创建符号链接")
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.save_target(self.project, self.target(profile=str(link)))
        self.assertIn("符号链接", str(caught.exception))

    def test_profile_is_private(self):
        path = bt.ensure_profile(self.project)
        if os.name == "nt":
            self.skipTest("Windows 没有 POSIX 权限位；Linux/macOS 上按 0700 建立")
        mode = path.stat().st_mode & 0o777
        self.assertEqual(mode & 0o077, 0, f"profile 权限过宽：{oct(mode)}")

    def test_launch_refuses_without_target_or_adapter(self):
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.launch(FakeBrowser(), self.project)
        self.assertIn("还没有配置 target", str(caught.exception))
        bt.save_target(self.project, self.target())
        with self.assertRaises(bt.AdapterUnavailable) as caught:
            bt.launch(None, self.project)
        self.assertIn("适配器", str(caught.exception))

    def test_launch_classifies_failures(self):
        bt.save_target(self.project, self.target())
        with self.assertRaises(bt.AdapterUnavailable) as caught:
            bt.launch(FakeBrowser(fail="missing"), self.project)
        self.assertIn("浏览器或驱动不存在", str(caught.exception))
        with self.assertRaises(bt.AdapterUnavailable) as caught:
            bt.launch(FakeBrowser(fail="denied"), self.project)
        self.assertIn("权限不足", str(caught.exception))
        with self.assertRaises(bt.AdapterNeedsHuman) as caught:
            bt.launch(FakeBrowser(fail="timeout"), self.project)
        self.assertIn("启动等待超时", str(caught.exception))
        with self.assertRaises(bt.AdapterUnavailable) as caught:
            bt.launch(FakeBrowser(started=False), self.project)
        self.assertIn("未确认浏览器已启动", str(caught.exception))

    def test_launch_writes_journal_and_survives_restart(self):
        bt.save_target(self.project, self.target())
        session = bt.launch(FakeBrowser(), self.project)
        self.assertTrue(session["started"])
        entries = bt.read_journal(self.project)
        self.assertEqual([item["kind"] for item in entries], ["launch"])
        # 重启＝重新读盘：journal 是只追加的 JSONL，重启后仍在
        lines = (bt.state_dir(self.project) / bt.JOURNAL_NAME).read_text(
            encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["kind"], "launch")

    def test_login_needs_evidence_and_keeps_cancelled(self):
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.record_login(self.project, status="valid")
        self.assertIn("账号别名与页面证据", str(caught.exception))
        data = bt.record_login(self.project, status="valid", account="潮汐钟",
                              evidence="e" * 64)
        self.assertEqual(data["status"], "valid")
        self.assertEqual(bt.login_state(self.project)["account"], "潮汐钟")
        bt.record_login(self.project, status="cancelled", reason="作者取消扫码")
        self.assertEqual(bt.login_state(self.project)["status"], "cancelled")

    def test_readonly_requires_all_identities_and_writes_nothing(self):
        row = {"platform": "fanqie", "account": "acc", "book_id": "b1",
               "chapter_id": 3}
        report = bt.verify_readonly(FakeBrowser(row=row), self.project, book_id="b1", chapter=3)
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("content_sha256", report["reason"])
        self.assertEqual(report["writes"], 0)
        ok = bt.verify_readonly(FakeBrowser(), self.project, book_id="b1", chapter=3)
        self.assertEqual(ok["status"], "verified")
        self.assertEqual(ok["writes"], 0)
        self.assertEqual(ok["identity"]["chapter_id"], 3)
        self.assertEqual(bt.verify_readonly(FakeBrowser(), self.project, book_id="", chapter=3)["status"],
                         "needs_review")
        self.assertEqual(bt.verify_readonly(None, self.project, book_id="b1", chapter=3)["status"],
                         "unavailable")
        self.assertFalse([item for item in bt.read_journal(self.project) if item["kind"] == "publish"])

    def test_readonly_reports_needs_human_and_page_change(self):
        report = bt.verify_readonly(FakeBrowser(fail="needs_human"), self.project,
                                    book_id="b1", chapter=3)
        self.assertEqual(report["status"], "needs_human")
        self.assertIn("验证码", report["reason"])
        row = {"platform": "fanqie", "account": "acc", "book_id": "b1",
               "chapter_id": 4, "content_sha256": "c" * 64}
        mismatch = bt.verify_readonly(FakeBrowser(row=row), self.project, book_id="b1", chapter=3)
        self.assertEqual(mismatch["status"], "needs_review")
        self.assertIn("章号", mismatch["reason"])

    def test_publish_requires_scope_then_writes_intent_once(self):
        bt.save_target(self.project, self.target())
        refused = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                  body_sha256="d" * 64)
        self.assertEqual(refused["status"], "refused")
        self.assertEqual(refused["writes"], 0)
        bt.save_target(self.project, self.target(scope="publish", authorization="作者授权"))
        report = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                 body_sha256="d" * 64)
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["writes"], 1)
        again = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(again["writes"], 0)
        entries = [item for item in bt.read_journal(self.project) if item["kind"] == "publish"]
        self.assertEqual(entries[0]["state"], "intent")
        self.assertEqual(entries[-1]["state"], "accepted")

    def test_unknown_publish_result_is_not_retried(self):
        bt.save_target(self.project, self.target(scope="publish", authorization="作者授权"))
        browser = FakeBrowser(publish_error=RuntimeError("连接中断"))
        report = bt.publish_once(browser, self.project, book_id="b1", chapter=3,
                                 body_sha256="d" * 64)
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(report["writes"], 1)
        self.assertIn("只对账", report["reason"])
        self.assertEqual(len(browser.calls), 1)
        again = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(again["status"], "duplicate")

    def test_capability_row_has_eight_columns_with_three_values(self):
        bt.save_target(self.project, self.target())
        bt.record_login(self.project, status="valid", account="acc", evidence="a" * 64)
        row = bt.capability_row(self.project)
        self.assertEqual(tuple(row), bt.COLUMNS)
        self.assertEqual(len(row), 8)
        self.assertTrue(set(row.values()) <= set(bt.STATUSES))
        self.assertEqual(row["publish"], bt.PENDING)
        self.assertEqual(row["browser_login"], bt.SIMULATED)
        empty = bt.capability_row(None)
        self.assertEqual(set(empty.values()), {bt.PENDING})

    def test_status_summarises_without_writing(self):
        bt.save_target(self.project, self.target())
        before = (bt.state_dir(self.project) / bt.JOURNAL_NAME)
        status = bt.status(self.project)
        self.assertEqual(status["target"]["browser"], "chromium")
        self.assertEqual(status["journal"], 0)
        self.assertFalse(before.exists())


class HardeningTest(unittest.TestCase):
    """审计发现的门禁绕过：身份自证、账本被裁剪、并发丢日志、profile 联接。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=writer.COMBINED_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "作品 潮汐 钟"
        self.project.mkdir(parents=True)
        self.target = {"os": "windows", "arch": "amd64", "runtime": "native",
                       "browser": "chromium", "browser_version": "131.0",
                       "driver": "playwright", "credential": "reconfigured",
                       "scope": "publish", "authorization": "作者授权：番茄《潮汐钟》第3章",
                       "platform": "fanqie"}

    def row(self, **overrides):
        values = {"platform": "fanqie", "account": "acc", "book_id": "b1",
                  "chapter_id": 3, "content_sha256": "c" * 64}
        values.update(overrides)
        return values

    def test_readonly_refuses_other_book_platform_and_weak_digest(self):
        bt.save_target(self.project, self.target)
        other_book = bt.verify_readonly(FakeBrowser(row=self.row(book_id="OTHER")),
                                        self.project, book_id="b1", chapter=3)
        self.assertEqual(other_book["status"], "needs_review")
        self.assertIn("作品 ID", other_book["reason"])
        other_platform = bt.verify_readonly(FakeBrowser(row=self.row(platform="qidian")),
                                            self.project, book_id="b1", chapter=3)
        self.assertEqual(other_platform["status"], "needs_review")
        self.assertIn("平台不符", other_platform["reason"])
        weak = bt.verify_readonly(FakeBrowser(row=self.row(content_sha256="x")),
                                  self.project, book_id="b1", chapter=3)
        self.assertEqual(weak["status"], "needs_review")
        self.assertIn("sha256", weak["reason"])
        broken = bt.verify_readonly(FakeBrowser(row=self.row(chapter_id="third")),
                                    self.project, book_id="b1", chapter=3)
        self.assertEqual(broken["status"], "needs_review")
        self.assertIn("不是数字", broken["reason"])

    def test_readonly_reports_adapter_writes(self):
        report = bt.verify_readonly(FakeBrowser(row=self.row(writes=2)),
                                    self.project, book_id="b1", chapter=3)
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["writes"], 2)
        self.assertIn("写入", report["reason"])

    def test_client_cannot_mark_login_valid(self):
        bt.save_target(self.project, self.target)
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.record_login(self.project, status="valid", account="acc",
                            evidence="a" * 64, source="client")
        self.assertIn("客户端", str(caught.exception))
        data = bt.record_login(self.project, status="valid", account="acc",
                               evidence="a" * 64, source="adapter")
        self.assertEqual(data["status"], "valid")
        self.assertEqual(bt.capability_row(self.project)["browser_login"], bt.SIMULATED)
        bt.record_login(self.project, status="needs_human", reason="扫码超时", source="client")
        self.assertEqual(bt.capability_row(self.project)["browser_login"], bt.PENDING)

    def test_ledger_survives_journal_trimming(self):
        bt.save_target(self.project, self.target)
        first = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(first["status"], "accepted")
        for index in range(250):
            bt.append_journal(self.project, {"kind": "readonly", "index": index})
        again = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(len(bt.read_journal(self.project)), bt.MAX_JOURNAL)
        without_replace = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                          body_sha256="e" * 64)
        self.assertEqual(without_replace["status"], "refused")
        self.assertIn("replace", without_replace["reason"])
        changed = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                  body_sha256="e" * 64, replace=True)
        self.assertEqual(changed["status"], "accepted")
        old = bt.ledger_state(self.project, bt._intent_key("b1", 3, "d" * 64))
        self.assertEqual(old["state"], "superseded")

    def test_reconcile_clears_needs_human(self):
        bt.save_target(self.project, self.target)
        blocked = bt.publish_once(FakeBrowser(publish_error=bt.AdapterNeedsHuman("扫码")),
                                  self.project, book_id="b1", chapter=3, body_sha256="d" * 64)
        self.assertEqual(blocked["status"], "needs_human")
        retry = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(retry["status"], "duplicate")
        report = bt.reconcile_publish(self.project, book_id="b1", chapter=3,
                                      resolution="abandoned", note="作者放弃本次投递")
        self.assertEqual(report["changed"], 1)
        fresh = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(fresh["status"], "accepted")

    def test_journal_append_is_process_safe(self):
        import subprocess
        import sys

        backend = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(backend)
        script = (
            "from pathlib import Path\n"
            "from integration import browser_target as bt\n"
            "root = Path(r'%s')\n"
            "for index in range(30):\n"
            "    bt.append_journal(root, {'kind': 'concurrent', 'index': index})\n"
        ) % self.project
        processes = [subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-c", script],
                                      cwd=str(backend), env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(2)]
        for process in processes:
            _, err = process.communicate(timeout=120)
            self.assertEqual(process.returncode, 0, err.decode("utf-8", "replace"))
        entries = [item for item in bt.read_journal(self.project, limit=0)
                   if item.get("kind") == "concurrent"]
        self.assertEqual(len(entries), 60)

    @unittest.skipUnless(os.name == "nt", "junction 只在 Windows 上可建")
    def test_windows_junction_profile_is_refused(self):
        import subprocess

        outside = Path(self.temp.name) / "outside"
        outside.mkdir(parents=True, exist_ok=True)
        link = bt.state_dir(self.project) / bt.PROFILE_DIR
        link.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest(f"无法创建 junction：{result.stderr.strip()}")
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.save_target(self.project, dict(self.target, profile=str(link)))
        self.assertIn("profile", str(caught.exception))

    def test_stop_without_adapter_writes_nothing(self):
        bt.stop(None, self.project)
        self.assertFalse((bt.state_dir(self.project) / bt.JOURNAL_NAME).exists())

    def test_tampered_target_is_rejected_on_read(self):
        bt.save_target(self.project, self.target)
        path = bt.state_dir(self.project) / bt.TARGET_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["profile"] = str(Path(self.temp.name) / "outside-profile")
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.load_target(self.project)
        self.assertIn("作品目录内", str(caught.exception))


class Audit095RegressionTest(unittest.TestCase):
    """audit-095 的 P0/P1：路径穿越、身份自证、改稿重投、假证据、脏账本。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=writer.COMBINED_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "作品"
        self.project.mkdir(parents=True)
        self.target = {"os": "windows", "arch": "amd64", "runtime": "native",
                       "browser": "chromium", "browser_version": "131.0",
                       "driver": "playwright", "credential": "reconfigured",
                       "scope": "publish", "authorization": "作者书面授权 2026-11-22",
                       "account": "acc"}
        bt.save_target(self.project, self.target)

    def test_reconcile_key_cannot_traverse(self):
        for bad in ("../../victim", "..\\..\\victim", "a" * 64, "zzzzzzzzzzzzzzzz"):
            with self.assertRaises(bt.BrowserTargetError):
                bt.reconcile_publish(self.project, key=bad, resolution="abandoned")
        outside = Path(self.temp.name) / "victim.json"
        outside.write_text('{"keep": "original"}', encoding="utf-8")
        with self.assertRaises(bt.BrowserTargetError):
            bt.reconcile_publish(self.project, key="../victim", resolution="accepted")
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"keep": "original"}')

    def test_readonly_checks_account_and_expected_digest(self):
        row = {"platform": "fanqie", "account": "acc-EVIL", "book_id": "b1",
               "chapter_id": 3, "content_sha256": "c" * 64}
        report = bt.verify_readonly(FakeBrowser(row=row), self.project,
                                    book_id="b1", chapter=3)
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("账号不符", report["reason"])
        row["account"] = "acc"
        report = bt.verify_readonly(FakeBrowser(row=row), self.project,
                                    book_id="b1", chapter=3,
                                    expect_body_sha256="d" * 64)
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("正文摘要", report["reason"])
        report = bt.verify_readonly(FakeBrowser(row=row), self.project,
                                    book_id="b1", chapter=3,
                                    expect_body_sha256="c" * 64)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["observed_sha256"], "c" * 64)

    def test_changed_body_needs_explicit_replace(self):
        first = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                body_sha256="d" * 64)
        self.assertEqual(first["status"], "accepted")
        refused = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                  body_sha256="e" * 64)
        self.assertEqual(refused["status"], "refused")
        replaced = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                   body_sha256="e" * 64, replace=True)
        self.assertEqual(replaced["status"], "accepted")
        old = bt.ledger_state(self.project, bt._intent_key("b1", 3, "d" * 64))
        self.assertEqual(old["state"], "superseded")

    def test_second_writer_loses_the_claim(self):
        key = bt._intent_key("b1", 3, "d" * 64)
        bt._claim_ledger(self.project, key, {"state": "intent", "book_id": "b1",
                                             "chapter": 3, "body_sha256": "d" * 64})
        report = bt.publish_once(FakeBrowser(), self.project, book_id="b1", chapter=3,
                                 body_sha256="d" * 64)
        self.assertEqual(report["status"], "duplicate")

    def test_corrupt_and_dirty_ledgers_do_not_block_reconcile(self):
        folder = bt.state_dir(self.project) / bt.LEDGER_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "aaa.json").write_text("{ not json", encoding="utf-8")
        (folder / ("b" * 16 + ".json")).write_text(
            json.dumps({"book_id": "b1", "chapter": "第三章", "state": "unknown"}),
            encoding="utf-8")
        (folder / ("c" * 16 + ".json")).write_text(
            json.dumps({"book_id": "b1", "chapter": 3, "state": "unknown"}),
            encoding="utf-8")
        report = bt.reconcile_publish(self.project, book_id="b1", chapter=3,
                                      resolution="abandoned")
        self.assertEqual(report["changed"], 1)
        self.assertGreaterEqual(report["skipped"], 1)
        self.assertGreaterEqual(report["corrupt"], 1)

    def test_readonly_column_needs_a_real_journal_entry(self):
        bt.record_login(self.project, status="valid", account="acc",
                        evidence="a" * 64, source="adapter")
        self.assertEqual(bt.capability_row(self.project)["readonly"], bt.PENDING)
        self.assertEqual(bt.capability_evidence(self.project)["readonly"], "")
        row = {"platform": "fanqie", "account": "acc", "book_id": "b1",
               "chapter_id": 3, "content_sha256": "c" * 64}
        bt.verify_readonly(FakeBrowser(row=row), self.project, book_id="b1", chapter=3)
        self.assertEqual(bt.capability_row(self.project)["readonly"], bt.SIMULATED)
        self.assertIn("journal:readonly", bt.capability_evidence(self.project)["readonly"])

    def test_handwritten_login_cannot_claim_valid(self):
        path = bt.state_dir(self.project) / bt.LOGIN_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": "valid", "account": "acc",
                                    "evidence": "not-a-digest", "source": "adapter",
                                    "checked_at": "2019-05-05T00:00:00+08:00"}),
                        encoding="utf-8")
        state = bt.login_state(self.project)
        self.assertEqual(state["status"], "unknown")
        self.assertTrue(state.get("stale"))
        self.assertEqual(bt.capability_row(self.project)["browser_login"], bt.PENDING)

    def test_broken_utf8_in_journal_is_tolerated(self):
        path = bt.state_dir(self.project) / bt.JOURNAL_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"kind":"x"}\n\xff\xfe not utf8\n')
        entries = bt.read_journal(self.project)
        self.assertEqual([item.get("kind") for item in entries], ["x"])

    def test_profile_cannot_be_project_root(self):
        with self.assertRaises(bt.BrowserTargetError) as caught:
            bt.save_target(self.project, dict(self.target, profile="."))
        self.assertIn("浏览器状态目录", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
