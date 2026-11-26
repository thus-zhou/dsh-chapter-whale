"""两层并发引擎：优先级、三级暂停、父子共享、改令挂起与租约恢复。"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from integration import concurrent_engine as ce


def project(folder):
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


class SchedulingTest(unittest.TestCase):
    def test_p0_preempts_and_p2_keeps_a_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            p2a = ce.submit(book, {"kind": "batch"}, priority="P2", chapter_id=3)
            ce.submit(book, {"kind": "daily"}, priority="P1", chapter_id=2)
            p0 = ce.submit(book, {"kind": "manual"}, priority="P0", chapter_id=1)
            first = ce.claim(book, "w1", max_slots=2)
            self.assertEqual(first["task_id"], p0["task_id"])
            second = ce.claim(book, "w2", max_slots=2)
            self.assertEqual(second["priority"], "P1")
            self.assertIsNone(ce.claim(book, "w3", max_slots=2))
            ce.complete(book, p0["task_id"])
            third = ce.claim(book, "w3", max_slots=2)
            self.assertEqual(third["task_id"], p2a["task_id"])

    def test_p2_never_takes_the_last_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.submit(book, {}, priority="P2")
            self.assertIsNone(ce.claim(book, "w", max_slots=1))

    def test_three_level_pause_and_parent_inheritance(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            parent = ce.submit(book, {"kind": "parent"}, priority="P1")
            child = ce.submit(book, {"kind": "child"}, priority="P2",
                              parent_task_id=parent["task_id"])
            ce.pause(book, "task:" + parent["task_id"], "作者暂停父任务")
            self.assertIsNone(ce.claim(book, "w", max_slots=4))
            ce.resume(book, "task:" + parent["task_id"])
            claimed = ce.claim(book, "w", max_slots=4)
            self.assertEqual(claimed["task_id"], parent["task_id"])
            ce.pause(book, "global", "全站维护")
            ce.complete(book, parent["task_id"])
            self.assertIsNone(ce.claim(book, "w", max_slots=4))
            ce.resume(book, "global")
            self.assertEqual(ce.claim(book, "w", max_slots=4)["task_id"], child["task_id"])

    def test_blocked_by_requires_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            first = ce.submit(book, {}, priority="P1")
            second = ce.submit(book, {}, priority="P0", blocked_by=[first["task_id"]])
            self.assertEqual(ce.claim(book, "w")["task_id"], first["task_id"])
            ce.complete(book, first["task_id"])
            self.assertEqual(ce.claim(book, "w")["task_id"], second["task_id"])

    def test_amendment_hold_and_continue_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            one = ce.submit(book, {}, priority="P1")
            two = ce.submit(book, {}, priority="P2")
            ce.hold_for_amendment(book, "amd_1", [one["task_id"], two["task_id"]])
            self.assertEqual(ce.get(book, one["task_id"])["state"], "held")
            self.assertIsNone(ce.claim(book, "w"))
            released = ce.release_amendment(book, "amd_1")
            self.assertEqual(set(released["released_task_ids"]), {one["task_id"], two["task_id"]})
            self.assertEqual(ce.claim(book, "w")["task_id"], one["task_id"])

            three = ce.submit(book, {}, priority="P1")
            ce.hold_for_amendment(book, "amd_2", [three["task_id"]], fallback="continue")
            self.assertEqual(ce.get(book, three["task_id"])["state"], "pending")

    def test_committing_task_expires_into_recovery_required(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            claimed = ce.claim(book, "w", lease_seconds=0.05)
            self.assertEqual(claimed["task_id"], task["task_id"])
            ce.begin_commit(book, task["task_id"], "w")
            time.sleep(0.08)
            with self.assertRaises(ce.SchedulerError) as caught:
                ce.renew(book, task["task_id"], "w")
            self.assertEqual(caught.exception.code, "recovery_required")
            self.assertEqual(ce.get(book, task["task_id"])["state"], "recovery_required")

    def test_recover_requeues_non_committing_expired(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "w", lease_seconds=-1)
            recovered = ce.recover(book)
            self.assertEqual(recovered[0]["state"], "pending")

    def test_snapshot_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.submit(book, {}, priority="P1")
            snap = ce.snapshot(book)
            self.assertEqual(snap["counts"]["pending"], 1)
            self.assertEqual(snap["max_slots"], 4)


class WakeTest(unittest.TestCase):
    def test_loopback_notifier_contract(self):
        seen = {}

        class Response:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout=0):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["token"] = request.headers.get("X-internal-token")
            return Response()

        notifier = ce.LoopbackNotifier(18765, "secret", opener=opener)
        self.assertTrue(notifier.notify({"kind": "wake", "task": "t1"}))
        self.assertEqual(seen["url"], "http://127.0.0.1:18765/internal/events/notify")
        self.assertEqual(seen["body"]["task"], "t1")
        self.assertEqual(seen["token"], "secret")

    def test_slow_client_gets_resync_and_is_dropped(self):
        fanout = ce.EventFanout(max_pending=2)
        q = fanout.subscribe()
        fanout.publish({"n": 1})
        fanout.publish({"n": 2})
        dropped = fanout.publish({"n": 3})
        self.assertEqual(dropped, [q])
        self.assertEqual(q.get_nowait(), {"kind": "resync_required"})

    def test_spawn_worker_merges_stderr(self):
        import inspect
        source = inspect.getsource(ce.spawn_worker)
        self.assertIn("stderr=subprocess.STDOUT", source)


if __name__ == "__main__":
    unittest.main()
