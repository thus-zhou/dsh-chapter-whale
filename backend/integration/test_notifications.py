"""A04 通知子系统内核的单元测试。

全部用例都注入假的 opener，不打真实网络；时间一律用 ``now=`` 注入，
``sleeper`` 换成空实现，因此整套用例在 5 秒内跑完。
"""

import inspect
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

try:
    from integration import notifications
except ImportError:  # pragma: no cover - 允许直接 python test_notifications.py
    import notifications  # type: ignore[no-redef]


UTC = timezone.utc
BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HOOK = "https://hooks.example.com/services/T00000000/B00000000/abcdefghijklmnop"
SECRET = "s3cr3t-token"


def at(seconds=0.0):
    """相对基准时间的时刻（全部用例都靠它注入时间，从不等真实时钟）。"""
    return BASE + timedelta(seconds=float(seconds))


def offset(stamp):
    """把库里的 ISO8601 字符串换回相对基准时间的秒数。"""
    return (datetime.fromisoformat(str(stamp)) - BASE).total_seconds()


class FakeHeaders:
    """够用的 headers 容器：``_header`` 既支持 dict 也支持 Message。"""

    def __init__(self, values=None):
        self._values = {str(key).lower(): str(value) for key, value in dict(values or {}).items()}

    def get(self, name, default=None):
        return self._values.get(str(name).lower(), default)

    def items(self):
        return list(self._values.items())


class FakeResponse:
    """模拟 ``urlopen`` 的返回对象：``.status`` / ``.headers`` / ``.read()``。"""

    def __init__(self, status=200, body=b'{"ok":true}', headers=None):
        self.status = status
        self.headers = FakeHeaders(headers)
        self._body = body
        self.closed = False

    def read(self, *_args, **_kwargs):
        return self._body

    def close(self):
        self.closed = True


class FakeOpener:
    """按脚本依次返回响应或抛异常，并记录每次请求（便于断言“根本没发”）。"""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if not self.script:
            return FakeResponse(200)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request, timeout)
        return item

    @property
    def bodies(self):
        result = []
        for request in self.calls:
            payload = request.data or b"{}"
            result.append(json.loads(payload.decode("utf-8")))
        return result


class NoSleep:
    """退避一律靠 ``next_attempt_at``，测试里绝不在进程内睡眠。"""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class NotificationTestCase(unittest.TestCase):
    """每个用例一本独立的通知库；收件配置走模块真实的凭据保护路径。"""

    def setUp(self):
        notification_tmp = tempfile.TemporaryDirectory(prefix="notify-")
        self.addCleanup(notification_tmp.cleanup)
        self.tmp = notification_tmp.name
        self.path = os.path.join(self.tmp, "notifications.db")
        self.db = notifications.connect(self.path)
        self.addCleanup(self.db.close)
        self.sleeper = NoSleep()

    # ------------------------------------------------------------------ #
    # 便捷构造
    # ------------------------------------------------------------------ #

    def make_recipient(self, url=HOOK, secret=SECRET, **kwargs):
        return notifications.add_recipient(self.db, url, secret, now=at(0), **kwargs)

    def open_failure(self, *, seconds=0.0, job_id="job-7", event_type="job.paused", payload=None):
        return notifications.open_incident(
            self.db,
            event_type,
            job_id,
            "项目-9f2c",
            "书-3f9a",
            payload if payload is not None else {"reason": "复核未通过"},
            now=at(seconds),
        )

    def queue(self, recipient, *, incident=None, event_type="job.paused", payload=None, seconds=1.0, dedupe_key=""):
        rows = notifications.enqueue(
            self.db,
            incident["id"] if incident else None,
            event_type,
            payload if payload is not None else {"reason": "复核未通过"},
            [recipient],
            now=at(seconds),
            dedupe_key=dedupe_key,
        )
        self.assertEqual(len(rows), 1)
        return rows[0]

    def deliver(self, row, recipient, opener, *, seconds=10.0, **kwargs):
        return notifications.deliver(
            self.db,
            row,
            recipient,
            opener=opener,
            now=at(seconds),
            sleeper=self.sleeper,
            **kwargs,
        )

    # ------------------------------------------------------------------ #
    # 事故去重与恢复
    # ------------------------------------------------------------------ #

    def test_repeated_failure_keeps_one_open_incident(self):
        """同一故障反复失败 20 次只留一个打开中的 incident 与一条事件。"""
        opened = [self.open_failure(seconds=index) for index in range(20)]

        self.assertFalse(opened[0]["deduplicated"])
        self.assertTrue(all(item["deduplicated"] for item in opened[1:]))
        self.assertEqual({item["id"] for item in opened}, {opened[0]["id"]})
        self.assertEqual({item["event_id"] for item in opened}, {opened[0]["event_id"]})
        self.assertEqual(opened[0]["sequence"], 1)
        self.assertEqual(len(notifications.list_events(self.db)), 1)
        self.assertEqual(len(notifications.list_incidents(self.db, status="open")), 1)

    def test_reopen_after_resolve_bumps_sequence(self):
        """恢复后再发生才算新故障：新 incident、sequence 加一、事件也另起一条。"""
        first = self.open_failure()
        resolved = notifications.resolve_incident(self.db, first["id"], "已人工恢复", now=at(30))
        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["payload"]["resolution_note"], "已人工恢复")
        self.assertEqual(notifications.list_incidents(self.db, status="open"), [])

        again = self.open_failure(seconds=60)
        self.assertFalse(again["deduplicated"])
        self.assertNotEqual(again["id"], first["id"])
        self.assertEqual(again["sequence"], 2)
        self.assertNotEqual(again["event_id"], first["event_id"])
        self.assertEqual(len(notifications.list_incidents(self.db)), 2)
        self.assertEqual(len(notifications.list_events(self.db)), 2)

        # 再恢复一次也不该把已恢复的记录改坏
        again_resolved = notifications.resolve_incident(self.db, first["id"], "重复恢复", now=at(70))
        self.assertFalse(again_resolved["resolved"])
        self.assertTrue(again_resolved["already"])

    def test_different_object_gets_its_own_incident(self):
        """fingerprint 含关键对象，换一章/换一个 job 就是另一个故障。"""
        base = self.open_failure()
        other_job = notifications.open_incident(
            self.db, "job.paused", "job-8", "项目-9f2c", "书-3f9a", {"reason": "复核未通过"}, now=at(1)
        )
        other_chapter = notifications.open_incident(
            self.db,
            "job.paused",
            "job-7",
            "项目-9f2c",
            "书-3f9a",
            {"reason": "复核未通过"},
            now=at(2),
            chapter_id="ch-12",
        )
        self.assertNotEqual(base["fingerprint"], other_job["fingerprint"])
        self.assertNotEqual(base["fingerprint"], other_chapter["fingerprint"])
        self.assertEqual(len(notifications.list_incidents(self.db, status="open")), 3)

    # ------------------------------------------------------------------ #
    # 发件箱：幂等、状态机与退避
    # ------------------------------------------------------------------ #

    def test_enqueue_is_idempotent_per_recipient(self):
        """同一事件重复入队不会长出新行，event_id 与 outbox 行都不变。"""
        recipient = self.make_recipient()
        incident = self.open_failure()
        first = notifications.enqueue(
            self.db, incident["id"], "job.paused", {"reason": "重复入队"}, [recipient], now=at(1)
        )
        second = notifications.enqueue(
            self.db,
            incident["id"],
            "job.paused",
            {"reason": "重复入队"},
            [recipient, recipient["id"]],
            now=at(5),
        )
        self.assertEqual(len(notifications.list_outbox(self.db)), 1)
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(first[0]["event_id"], second[0]["event_id"])

    def test_retry_reuses_event_id_and_single_outbox_row(self):
        """同一事件重试三次：event_id 恒定、发件箱始终只有一行（更新而非新增）。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        event_id = row["event_id"]
        states = []
        for index, status in enumerate((500, 500, 200)):
            row = self.deliver(row, recipient["id"], FakeOpener(FakeResponse(status)), seconds=10 + index * 120)
            self.assertEqual(row["event_id"], event_id)
            states.append(row["state"])

        self.assertEqual(states, ["pending", "pending", "sent"])
        rows = notifications.list_outbox(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempts"], 3)
        self.assertEqual(rows[0]["state"], "sent")
        self.assertEqual(rows[0]["response_code"], 200)
        self.assertEqual(notifications.list_events(self.db)[0]["sent_count"], 1)

    def test_accepted_codes_mark_sent(self):
        """只有 200/201/202 才算送达。"""
        recipient = self.make_recipient()
        for index, status in enumerate((200, 201, 202)):
            row = self.queue(recipient, dedupe_key=f"accepted-{status}")
            result = self.deliver(row, recipient["id"], FakeOpener(FakeResponse(status)), seconds=10 + index)
            self.assertEqual(result["state"], "sent")
            self.assertEqual(result["response_code"], status)
            self.assertIsNotNone(result["sent_at"])

    def test_throttle_honours_retry_after_seconds(self):
        """429 按 Retry-After 秒数安排下一次尝试。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        opened = self.deliver(
            row,
            recipient["id"],
            FakeOpener(FakeResponse(429, headers={"Retry-After": "5"})),
            seconds=100,
        )
        self.assertEqual(opened["state"], "pending")
        self.assertAlmostEqual(offset(opened["next_attempt_at"]) - 100.0, 5.0, places=3)
        self.assertIn("429", opened["last_error"])

    def test_retry_after_accepts_http_date(self):
        """Retry-After 也支持 HTTP 日期；越界值被夹住。"""
        target = at(45).strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.assertAlmostEqual(notifications.parse_retry_after(target, at(0)), 45.0, delta=1.0)
        self.assertEqual(notifications.parse_retry_after("999999", at(0)), 86400.0)
        self.assertEqual(notifications.parse_retry_after("not-a-date", at(0)), None)
        self.assertEqual(notifications.parse_retry_after("", at(0)), None)

    def test_server_error_backoff_grows_and_caps(self):
        """5xx 为临时失败：2**attempts 秒退避，带 0..20% 抖动，封顶 1 小时。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        delays = []
        for index in range(3):
            moment = 1000 + index * 4000
            row = self.deliver(row, recipient["id"], FakeOpener(FakeResponse(500)), seconds=moment)
            self.assertEqual(row["state"], "pending")
            delays.append(offset(row["next_attempt_at"]) - moment)

        self.assertTrue(2.0 <= delays[0] <= 2.4, delays)
        self.assertTrue(4.0 <= delays[1] <= 4.8, delays)
        self.assertTrue(8.0 <= delays[2] <= 9.6, delays)
        self.assertEqual(notifications.backoff_delay(20, rng=lambda: 0.0), notifications.BACKOFF_CAP)
        self.assertEqual(notifications.backoff_delay(30, rng=lambda: 1.0), notifications.BACKOFF_CAP)
        self.assertAlmostEqual(notifications.backoff_delay(1, rng=lambda: 1.0), 2.4, places=6)
        self.assertAlmostEqual(notifications.backoff_delay(0, rng=lambda: 0.0), 2.0, places=6)

    def test_invalid_recipient_marks_dead_and_keeps_row(self):
        """410/401 这类错误判定为收件地址失效：dead，进待处理列表，不删除。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        gone = self.deliver(row, recipient["id"], FakeOpener(FakeResponse(410)), seconds=10)
        self.assertEqual(gone["state"], "dead")
        self.assertIn("410", gone["last_error"])
        self.assertEqual([item["id"] for item in notifications.list_outbox(self.db, state=("dead", "failed"))], [gone["id"]])

        # dead 不会被自动重发，只能人工重排
        retry = FakeOpener(FakeResponse(200))
        skipped = self.deliver(gone, recipient["id"], retry, seconds=20)
        self.assertTrue(skipped.get("skipped"))
        self.assertEqual(retry.calls, [])

        requeued = notifications.requeue(self.db, gone["id"], now=at(30))
        self.assertEqual(requeued["state"], "pending")

        # 签名/权限错误同样走 dead
        other = self.queue(recipient, event_type="review_exhausted", seconds=2)
        unauthorized = self.deliver(other, recipient["id"], FakeOpener(FakeResponse(401)), seconds=40)
        self.assertEqual(unauthorized["state"], "dead")
        self.assertIn("401", unauthorized["last_error"])

    # ------------------------------------------------------------------ #
    # 响应丢失：unknown 与人工确认
    # ------------------------------------------------------------------ #

    def test_timeout_marks_unknown_and_never_resends(self):
        """超时说明请求可能已到达对端：unknown，绝不自动重发，只能人工确认。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        lost = self.deliver(row, recipient["id"], FakeOpener(socket.timeout("timed out")), seconds=10)
        self.assertEqual(lost["state"], "unknown")
        self.assertIn("响应丢失", lost["last_error"])
        self.assertEqual([item["id"] for item in notifications.list_outbox(self.db, state="unknown")], [lost["id"]])

        retry = FakeOpener(FakeResponse(200))
        skipped = self.deliver(lost, recipient["id"], retry, seconds=20)
        self.assertTrue(skipped.get("skipped"))
        self.assertEqual(retry.calls, [])

        probe = FakeOpener(FakeResponse(200))
        summary = notifications.run_once(self.db, "worker-1", opener=probe, now=at(30), sleeper=self.sleeper)
        self.assertEqual(summary, {"sent": 0, "retry": 0, "dead": 0, "unknown": 0})
        self.assertEqual(probe.calls, [])

        confirmed = notifications.resolve_unknown(self.db, lost["id"], "sent", "人工确认已送达", now=at(40))
        self.assertEqual(confirmed["state"], "sent")
        self.assertEqual(offset(confirmed["sent_at"]), 40.0)
        with self.assertRaises(notifications.NotificationError):
            notifications.resolve_unknown(self.db, lost["id"], "failed")

    def test_unknown_can_be_confirmed_as_failed(self):
        """人工确认没送达 → failed，进待处理；可以重新排队。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        lost = self.deliver(row, recipient["id"], FakeOpener(ConnectionResetError("reset")), seconds=10)
        self.assertEqual(lost["state"], "unknown")

        failed = notifications.resolve_unknown(self.db, lost["id"], "failed", "对端未收到", now=at(20))
        self.assertEqual(failed["state"], "failed")
        self.assertEqual([item["id"] for item in notifications.list_outbox(self.db, state="failed")], [failed["id"]])
        self.assertEqual(notifications.requeue(self.db, failed["id"], now=at(30))["state"], "pending")

        with self.assertRaises(notifications.NotificationError):
            notifications.resolve_unknown(self.db, failed["id"], "sent")

    def test_mark_unknown_is_manual_and_idempotent(self):
        """mark_unknown 可把卡住的记录标为 unknown，之后绝不自动重发。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        marked = notifications.mark_unknown(self.db, row["id"], "进程崩溃前不确定", now=at(10))
        self.assertEqual(marked["state"], "unknown")

        opener = FakeOpener(FakeResponse(200))
        skipped = self.deliver(row, recipient["id"], opener, seconds=20)
        self.assertTrue(skipped.get("skipped"))
        self.assertEqual(opener.calls, [])

        confirmed = notifications.resolve_unknown(self.db, row["id"], "sent", "人工确认已送达", now=at(30))
        self.assertEqual(confirmed["state"], "sent")
        with self.assertRaises(notifications.NotificationError):
            notifications.mark_unknown(self.db, row["id"], "再标一次", now=at(40))

    # ------------------------------------------------------------------ #
    # 租约与并发
    # ------------------------------------------------------------------ #

    def test_claim_is_exclusive_between_workers(self):
        """两个连接并发取件：同一行只会被一个 worker 拿到。"""
        recipient = self.make_recipient()
        for index in range(3):
            notifications.enqueue(
                self.db,
                None,
                "run.summary",
                {"reason": f"运行汇总 {index}"},
                [recipient],
                now=at(0),
                dedupe_key=f"run-{index}",
            )

        second = notifications.connect(self.path)
        self.addCleanup(second.close)
        first_batch = notifications.claim(self.db, "worker-a", lease_seconds=3600, now=at(10))
        second_batch = notifications.claim(second, "worker-b", lease_seconds=3600, now=at(10))
        self.assertEqual(len(first_batch), 3)
        self.assertEqual(second_batch, [])

        results = {}
        errors = {}
        barrier = threading.Barrier(4)

        def worker(name):
            connection = notifications.connect(self.path)
            try:
                barrier.wait(timeout=10)
                results[name] = [item["id"] for item in notifications.claim(connection, name, now=at(120), lease_seconds=60)]
            except BaseException as error:  # pragma: no cover - 并发失败要能看见原因
                errors[name] = error
            finally:
                connection.close()

        for index in range(3):
            notifications.enqueue(
                self.db,
                None,
                "run.summary",
                {"reason": f"并发汇总 {index}"},
                [recipient],
                now=at(60),
                dedupe_key=f"concurrent-{index}",
            )
        pending_ids = sorted(item["id"] for item in notifications.list_outbox(self.db, state="pending"))
        self.assertEqual(len(pending_ids), 3)

        threads = [threading.Thread(target=worker, args=(f"w{index}",)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertEqual(errors, {})
        claimed = [identity for value in results.values() for identity in value]
        self.assertEqual(sorted(claimed), sorted({*claimed}), "同一行被两个 worker 取走了")
        self.assertEqual(sorted(claimed), pending_ids)

    def test_expired_lease_can_be_reclaimed(self):
        """短租约过期后可以被重新抢占；尝试过的过期租约转 unknown 不再重发。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        first = notifications.claim(self.db, "worker-a", lease_seconds=5, now=at(10))
        self.assertEqual([item["id"] for item in first], [row["id"]])
        self.assertEqual(first[0]["lease_owner"], "worker-a")

        self.assertEqual(notifications.claim(self.db, "worker-b", now=at(12)), [])
        reclaimed = notifications.claim(self.db, "worker-b", now=at(20))
        self.assertEqual([item["id"] for item in reclaimed], [row["id"]])
        self.assertEqual(reclaimed[0]["lease_owner"], "worker-b")

        # 崩溃在“已发出”之后：attempts>0 的过期租约只能转 unknown
        self.db.execute(
            "UPDATE outbox SET state = 'leased', attempts = 1, lease_owner = 'worker-c', lease_until = ?"
            " WHERE id = ?",
            (notifications._iso(at(20)), row["id"]),
        )
        self.assertEqual(notifications.claim(self.db, "worker-d", now=at(200)), [])
        self.assertEqual(notifications.list_outbox(self.db, state="unknown")[0]["id"], row["id"])

    # ------------------------------------------------------------------ #
    # 载荷脱敏
    # ------------------------------------------------------------------ #

    def test_scrub_drops_sensitive_keys_recursively(self):
        """_scrub 递归丢弃正文、令牌、路径等键，保留其余字段。"""
        dirty = {
            "event_type": "job.paused",
            "reason": "等待人工复核",
            "chapter_id": "ch-3",
            "token": "tok-1",
            "Secret": "sec-1",
            "password": "pwd-1",
            "authorization": "Bearer abc",
            "cookie": "sid=1",
            "api_key": "key-1",
            "content": "第三章正文段落",
            "body": "整章正文",
            "text": "全文",
            "draft": "草稿",
            "path": "C:/书/第三章.txt",
            "cwd": "C:/书",
            "nested": {
                "token": "tok-2",
                "reason": "保留我",
                "items": [{"secret": "sec-2", "chapter_id": "ch-4"}],
            },
        }
        clean = notifications._scrub(dirty)

        for key in (
            "token",
            "secret",
            "password",
            "authorization",
            "cookie",
            "api_key",
            "content",
            "body",
            "text",
            "draft",
            "path",
            "cwd",
        ):
            self.assertNotIn(key, clean)
        self.assertEqual(clean["reason"], "等待人工复核")
        self.assertEqual(clean["nested"]["reason"], "保留我")
        self.assertEqual(clean["nested"]["items"], [{"chapter_id": "ch-4"}])

        dumped = json.dumps(clean, ensure_ascii=False)
        for leak in ("tok-1", "sec-1", "pwd-1", "Bearer abc", "key-1", "第三章正文段落", "整章正文", "C:/书", "sid=1"):
            self.assertNotIn(leak, dumped)

    def test_payload_only_has_contracted_fields(self):
        """对外载荷只有约定字段，正文/令牌/路径喂进来也落不到库里。"""
        notifications.open_incident(
            self.db,
            "review_exhausted",
            "job-9",
            "项目-1f3c",
            "书-3f9a",
            {
                "reason": "两轮复核仍未通过",
                "content": "第三章正文……",
                "token": "sk-live-123",
                "path": "C:/书/第三章.txt",
            },
            now=at(0),
        )
        payload = notifications.list_events(self.db)[0]["payload"]
        self.assertEqual(
            set(payload),
            {
                "event_id",
                "event_type",
                "occurred_at",
                "job_id",
                "project_alias",
                "book_alias",
                "chapter_id",
                "reason",
                "next_action",
                "sequence",
            },
        )
        self.assertEqual(payload["reason"], "两轮复核仍未通过")
        self.assertEqual(payload["project_alias"], "项目-1f3c")
        dumped = json.dumps(payload, ensure_ascii=False)
        for leak in ("正文", "sk-live-123", "第三章.txt", "C:/书"):
            self.assertNotIn(leak, dumped)

    def test_alias_mask_is_stable_and_readable(self):
        """别名形如 书-3f9a：同一输入恒定，不同输入不同。"""
        first = notifications.alias_mask("我的第一本书", "书")
        self.assertEqual(first, notifications.alias_mask("我的第一本书", "书"))
        self.assertNotEqual(first, notifications.alias_mask("另一本书", "书"))
        self.assertTrue(first.startswith("书-"))
        self.assertEqual(len(first.split("-")[1]), 4)

    # ------------------------------------------------------------------ #
    # 收件配置与掩码
    # ------------------------------------------------------------------ #

    def test_mask_url_keeps_only_scheme_and_host_prefix(self):
        """掩码只保留 scheme + host 前 6 字符，路径与查询串一律抹掉。"""
        masked = notifications.mask_url(HOOK + "?token=abc")
        self.assertEqual(masked, "https://hooks…/••••")
        self.assertNotIn("example.com", masked)
        self.assertNotIn("token", masked)
        self.assertEqual(notifications.mask_url("https://a.b/hook"), "https://a.b…/••••")
        self.assertEqual(notifications.mask_url("not a url"), "••••")
        self.assertEqual(notifications.mask_url(""), "••••")
        self.assertNotIn("8080", notifications.mask_url("http://127.0.0.1:8080/hook"))

    def test_recipient_metadata_never_echoes_url_or_secret(self):
        """add_recipient 之后，读回接口只有掩码，库里也没有明文。"""
        recipient = self.make_recipient()
        self.assertNotIn("url", recipient)
        self.assertNotIn("secret", recipient)
        self.assertEqual(recipient["masked"], "https://hooks…/••••")

        items = notifications.list_recipients(self.db)
        self.assertEqual(len(items), 1)
        dumped = json.dumps(items, ensure_ascii=False)
        for leak in ("example.com", SECRET, "abcdefghijklmnop", "T00000000"):
            self.assertNotIn(leak, dumped)
        self.assertTrue(items[0]["available"])

        stored = self.db.execute("SELECT * FROM recipients").fetchone()
        for value in tuple(stored):
            if isinstance(value, str):
                self.assertNotIn("hooks.example.com", value)
                self.assertNotIn(SECRET, value)

    def test_recipient_falls_back_to_protected_file(self):
        """没有可用的凭据编解码时，降级为受保护文件并记录警告，仍可投递。"""
        recipient = notifications.add_recipient(self.db, HOOK, SECRET, now=at(0), codec_pair=None)
        self.assertEqual(recipient["protection"], "plaintext-acl")
        self.assertTrue(recipient["warning"])

        stored = self.db.execute("SELECT * FROM recipients WHERE id = ?", (recipient["id"],)).fetchone()
        self.assertEqual(stored["url_blob"], "")
        self.assertEqual(stored["secret_blob"], "")

        vault = os.path.join(self.tmp, notifications.VAULT_DIR_NAME)
        self.assertTrue(os.path.isdir(vault))
        files = os.listdir(vault)
        self.assertEqual(len(files), 1)
        target = os.path.join(vault, files[0])
        with open(target, "r", encoding="utf-8") as handle:
            plaintext = handle.read()
        self.assertIn("hooks.example.com", plaintext)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)

        with open(self.path, "rb") as handle:
            self.assertNotIn(b"hooks.example.com", handle.read())

        self.assertTrue(notifications.list_recipients(self.db)[0]["available"])
        row = self.queue(recipient, event_type="run.summary", seconds=1)
        result = self.deliver(row, recipient["id"], FakeOpener(FakeResponse(200)), seconds=2)
        self.assertEqual(result["state"], "sent")

    def test_disabled_recipient_blocks_delivery(self):
        """停用后不投递：发件记录落 dead 并给出中文原因。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        disabled = notifications.disable_recipient(self.db, recipient["id"], now=at(2))
        self.assertFalse(disabled["enabled"])
        opener = FakeOpener(FakeResponse(200))
        result = self.deliver(row, recipient["id"], opener, seconds=10)
        self.assertEqual(result["state"], "dead")
        self.assertIn("已停用", result["last_error"])
        self.assertEqual(opener.calls, [])

    # ------------------------------------------------------------------ #
    # webhook 目标安全
    # ------------------------------------------------------------------ #

    def test_rejects_insecure_or_private_targets(self):
        """非 https、非回环、带 userinfo、缺 allow_loopback 的地址一律拒绝。"""
        for url in ("http://example.com/hook", "ftp://example.com/hook", "hooks.example.com"):
            with self.subTest(url=url):
                with self.assertRaises(notifications.UnsafeTarget):
                    notifications.add_recipient(self.db, url)
        with self.assertRaises(notifications.UnsafeTarget):
            notifications.validate_url("http://127.0.0.1:8080/hook")
        with self.assertRaises(notifications.UnsafeTarget):
            notifications.validate_url("https://user:pw@hooks.example.com/hook")
        self.assertEqual(
            notifications.validate_url("http://127.0.0.1:8080/hook", allow_loopback=True),
            "http://127.0.0.1:8080/hook",
        )
        loop = notifications.add_recipient(self.db, "http://127.0.0.1:8080/hook", allow_loopback=True, now=at(0))
        self.assertEqual(loop["kind"], "webhook")
        self.assertTrue(loop["allow_loopback"])

    def test_private_delivery_target_is_dead_before_sending(self):
        """即便配置被绕过，投递前仍会校验：内网地址落 dead 且一个字节都不发。"""
        row = self.queue(
            {"id": "rcp_intranet", "masked": "http://10.0…/••••"},
            event_type="run.summary",
            seconds=0,
        )
        opener = FakeOpener(FakeResponse(200))
        forged = {"id": "rcp_intranet", "url": "http://10.0.0.5/hook", "masked": "http://10.0…/••••"}
        result = self.deliver(row, forged, opener, seconds=10)
        self.assertEqual(result["state"], "dead")
        self.assertIn("https", result["last_error"])
        self.assertEqual(opener.calls, [])

    def test_redirect_to_private_network_is_rejected(self):
        """重定向落点是 http://10.0.0.5：拒绝跟随，绝不向内网发第二次请求。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        opener = FakeOpener(FakeResponse(302, headers={"Location": "http://10.0.0.5/hook"}))
        result = self.deliver(row, recipient["id"], opener, seconds=10)
        self.assertEqual(result["state"], "dead")
        self.assertEqual(len(opener.calls), 1)
        self.assertIn("https", result["last_error"])

    def test_redirect_chain_is_capped(self):
        """最多跟随 3 跳，第 4 个重定向落 dead。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        opener = FakeOpener(
            *[
                FakeResponse(307, headers={"Location": f"https://hooks.example.com/hop{index}"})
                for index in range(6)
            ]
        )
        result = self.deliver(row, recipient["id"], opener, seconds=10)
        self.assertEqual(result["state"], "dead")
        self.assertIn("重定向", result["last_error"])
        self.assertEqual(len(opener.calls), notifications.MAX_REDIRECTS + 1)

    def test_redirect_within_public_hosts_is_followed(self):
        """公网内的重定向照常跟随，最终 200 仍算送达。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        opener = FakeOpener(
            FakeResponse(302, headers={"Location": "https://hooks.example.com/next"}),
            FakeResponse(201),
        )
        result = self.deliver(row, recipient["id"], opener, seconds=10)
        self.assertEqual(result["state"], "sent")
        self.assertEqual(len(opener.calls), 2)
        self.assertTrue(opener.calls[1].full_url.endswith("/next"))

    # ------------------------------------------------------------------ #
    # 请求构造与上限
    # ------------------------------------------------------------------ #

    def test_request_shape_and_signature(self):
        """请求头与签名：JSON、UA、幂等键齐全，签名覆盖请求体。"""
        recipient = self.make_recipient()
        row = self.queue(recipient)
        opener = FakeOpener(FakeResponse(200))
        self.deliver(row, recipient["id"], opener, seconds=10)

        request = opener.calls[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers.get("Content-type"), "application/json")
        self.assertEqual(request.headers.get("User-agent"), notifications.USER_AGENT)
        self.assertTrue(notifications.USER_AGENT.startswith("dsh-chapter-whale/"))
        self.assertEqual(request.headers.get("X-chapterwhale-event"), "job.paused")
        self.assertEqual(request.headers.get("X-chapterwhale-event-id"), row["event_id"])
        signature = request.headers.get("X-chapterwhale-signature") or ""
        self.assertTrue(signature.startswith("sha256="))
        self.assertEqual(request.timeout if hasattr(request, "timeout") else notifications.REQUEST_TIMEOUT, 10)

        envelope = opener.bodies[0]
        self.assertEqual(envelope["source"], "dsh-chapter-whale")
        self.assertEqual(envelope["schema"], notifications.SCHEMA_VERSION)
        self.assertEqual(envelope["event_id"], row["event_id"])
        self.assertEqual(envelope["idempotency"], row["event_idempotency"])
        self.assertEqual(envelope["recipient"], recipient["masked"])
        self.assertIn("body", envelope)
        self.assertNotIn("test", envelope)
        self.assertNotIn(SECRET, json.dumps(envelope, ensure_ascii=False))

    def test_oversized_body_is_rejected_without_sending(self):
        """请求体超过 64 KiB 直接落 dead，一个字节都不发。"""
        recipient = self.make_recipient()
        row = self.queue(recipient, payload={"reason": "x" * (70 * 1024)})
        opener = FakeOpener(FakeResponse(200))
        result = self.deliver(row, recipient["id"], opener, seconds=10)
        self.assertEqual(result["state"], "dead")
        self.assertIn("64 KiB", result["last_error"])
        self.assertEqual(opener.calls, [])

    def test_test_send_marks_test_true(self):
        """测试发送：载荷与信封都带 test: true，且不占用业务事件类型。"""
        recipient = self.make_recipient()
        opener = FakeOpener(FakeResponse(200))
        result = notifications.test_send(self.db, recipient["id"], opener=opener, now=at(3))

        self.assertEqual(result["state"], "sent")
        self.assertTrue(result["test"])
        self.assertTrue(result["event_id"])
        envelope = opener.bodies[0]
        self.assertIs(envelope["test"], True)
        self.assertIs(envelope["body"]["test"], True)
        self.assertEqual(envelope["body"]["event_type"], notifications.EVENT_TEST)
        self.assertNotIn(notifications.EVENT_TEST, notifications.EVENT_TYPES)
        self.assertEqual(len(notifications.list_events(self.db)), 1)

    def test_test_send_requires_enabled_recipient(self):
        """停用的收件配置不能发测试消息。"""
        recipient = self.make_recipient()
        notifications.disable_recipient(self.db, recipient["id"], now=at(1))
        with self.assertRaises(notifications.NotificationError):
            notifications.test_send(self.db, recipient["id"], opener=FakeOpener(FakeResponse(200)), now=at(2))

    # ------------------------------------------------------------------ #
    # 汇总、错误脱敏与门面
    # ------------------------------------------------------------------ #

    def test_run_once_summarizes_results(self):
        """run_once 汇总 sent/retry/dead/unknown，失败不影响其他收件人。"""
        good = self.make_recipient()
        retired = notifications.add_recipient(self.db, "https://hooks.example.com/retired", now=at(0))
        notifications.enqueue(self.db, None, "run.summary", {"reason": "汇总 A"}, [good], now=at(0), dedupe_key="a")
        notifications.enqueue(self.db, None, "run.summary", {"reason": "汇总 B"}, [retired], now=at(0), dedupe_key="b")

        summary = notifications.run_once(
            self.db,
            "worker-1",
            opener=FakeOpener(FakeResponse(200), FakeResponse(410)),
            now=at(10),
            sleeper=self.sleeper,
        )
        self.assertEqual(summary, {"sent": 1, "retry": 0, "dead": 1, "unknown": 0})

    def test_redact_error_hides_tokens(self):
        """错误文本里的查询串、Bearer、凭据参数一律抹掉。"""
        message = notifications.redact_error(
            "POST https://hooks.example.com/x?token=abc123 failed: Bearer eyJhbGciOiJIUzI1NiJ9"
        )
        self.assertNotIn("abc123", message)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", message)
        self.assertIn("hooks.example.com/••••", message)
        self.assertIn("Bearer ••••", message)
        self.assertLessEqual(len(notifications.redact_error("x" * 1000)), 400)

    def test_event_store_facade(self):
        """EventStore 只是把连接与 owner 绑在一起的薄门面，行为与模块函数一致。"""
        store = notifications.EventStore(self.path, owner="worker-9")
        self.addCleanup(store.close)

        recipient = store.add_recipient(HOOK, SECRET, now=at(0))
        incident = store.open_incident("publication.needs_check", "job-3", "项目-aaaa", "书-3f9a", {"reason": "发布前检查"})
        rows = store.enqueue(incident["id"], "publication.needs_check", {"reason": "发布前检查"}, [recipient], now=at(1))
        self.assertEqual(len(rows), 1)

        summary = store.run_once(opener=FakeOpener(FakeResponse(202)), now=at(5), sleeper=self.sleeper)
        self.assertEqual(summary, {"sent": 1, "retry": 0, "dead": 0, "unknown": 0})
        self.assertEqual(len(store.list_events()), 1)
        self.assertEqual(store.list_outbox("sent")[0]["state"], "sent")
        self.assertEqual(store.list_recipients()[0]["masked"], "https://hooks…/••••")

    def test_schema_is_idempotent_and_versioned(self):
        """重复 connect 不重建、不丢数据；schema_version 记录版本。"""
        self.make_recipient()
        again = notifications.connect(self.path)
        self.addCleanup(again.close)
        self.assertEqual(len(notifications.list_recipients(again)), 1)
        version = again.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()[0]
        self.assertEqual(version, notifications.SCHEMA_VERSION)
        tables = {row[0] for row in again.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"incidents", "events", "outbox", "recipients", "schema_version"} <= tables)

    def test_unknown_event_type_is_rejected(self):
        """只接受约定的事件类型。"""
        with self.assertRaises(notifications.NotificationError):
            notifications.open_incident(self.db, "job.exploded", "job-1", "项目-1", "书-1", {})
        with self.assertRaises(notifications.NotificationError):
            notifications.enqueue(self.db, None, "wechat.push", {}, [{"id": "rcp_x", "masked": "•"}], now=at(0))

    def test_public_api_is_exported(self):
        """__all__ 里的名字都真实存在，接线依赖的签名与默认值稳定。"""
        for name in notifications.__all__:
            self.assertTrue(hasattr(notifications, name), f"__all__ 声明了不存在的名字：{name}")

        deliver = inspect.signature(notifications.deliver)
        self.assertEqual(list(deliver.parameters)[:3], ["db", "row", "recipient"])
        for keyword in ("opener", "now", "sleeper"):
            self.assertIn(keyword, deliver.parameters)

        claim = inspect.signature(notifications.claim)
        self.assertEqual(claim.parameters["limit"].default, 20)
        self.assertEqual(claim.parameters["lease_seconds"].default, 60)

        run_once = inspect.signature(notifications.run_once)
        self.assertEqual(run_once.parameters["limit"].default, 20)

        self.assertEqual(set(notifications.EVENT_TYPES), {
            "job.paused",
            "review_exhausted",
            "publication.needs_check",
            "incident.resolved",
            "run.summary",
        })
        self.assertNotIn(notifications.EVENT_TEST, notifications.EVENT_TYPES)
        self.assertEqual(set(notifications.STATES), {"pending", "leased", "sent", "unknown", "failed", "dead"})

    def test_schema_matches_contracted_columns(self):
        """三张表的列名与任务书一致，接线时可以直接按名取值。"""
        expected = {
            "incidents": {
                "id", "fingerprint", "event_type", "job_id", "project", "book",
                "opened_at", "resolved_at", "status", "sequence", "payload",
            },
            "events": {"id", "incident_id", "event_id", "event_type", "occurred_at", "payload", "delivery_state"},
            "outbox": {
                "id", "event_id", "event_idempotency", "recipient_id", "recipient_masked",
                "state", "attempts", "next_attempt_at", "last_error", "updated_at", "created_at",
                "lease_until", "lease_owner", "sent_at", "response_code",
            },
        }
        for table, columns in expected.items():
            actual = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
            self.assertTrue(columns <= actual, f"{table} 缺少列：{sorted(columns - actual)}")


if __name__ == "__main__":
    unittest.main()
