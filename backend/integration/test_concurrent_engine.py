"""两层并发引擎：优先级、三级暂停、父子共享、改令挂起与租约恢复。"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from integration import concurrent_engine as ce
from integration import workbench_db as wb


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
            ce.complete(book, p0["task_id"], owner="w1")
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
            ce.complete(book, parent["task_id"], owner="w")
            self.assertIsNone(ce.claim(book, "w", max_slots=4))
            ce.resume(book, "global")
            self.assertEqual(ce.claim(book, "w", max_slots=4)["task_id"], child["task_id"])

    def test_blocked_by_requires_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            first = ce.submit(book, {}, priority="P1")
            second = ce.submit(book, {}, priority="P0", blocked_by=[first["task_id"]])
            self.assertEqual(ce.claim(book, "w")["task_id"], first["task_id"])
            ce.complete(book, first["task_id"], owner="w")
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

    def test_begin_commit_extends_lease_and_allows_renew(self):
        """审计 C-07：进入提交流程后租约延长到 commit grace，owner 可续期。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            # C3-11 起 begin_commit 会拒绝已过期租约，夹具必须留足提交前的余量。
            claimed = ce.claim(book, "w", lease_seconds=30)
            self.assertEqual(claimed["task_id"], task["task_id"])
            committed = ce.begin_commit(book, task["task_id"], "w")
            self.assertTrue(committed["committing"])
            self.assertGreater(committed["lease_expires"], time.time() + 200)
            renewed = ce.renew(book, task["task_id"], "w")
            self.assertEqual(renewed["status"], "committing")
            self.assertTrue(renewed["renewed"])
            self.assertEqual(renewed["lease_expires"], ce.get(book, task["task_id"])["lease_expires"])
            self.assertEqual(ce.recover(book), [])
            self.assertEqual(ce.complete(book, task["task_id"], owner="w")["state"], "completed")

    def test_expired_committing_task_requires_recovery(self):
        """审计 C-07：提交租约真的过期时仍进入 recovery_required。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "w")
            ce.begin_commit(book, task["task_id"], "w")
            with wb.write_tx(book) as db:
                db.execute("UPDATE task_queue SET lease_expires=? WHERE task_id=?",
                           (time.time() - 10, task["task_id"]))
            with self.assertRaises(ce.SchedulerError) as caught:
                ce.renew(book, task["task_id"], "w")
            self.assertEqual(caught.exception.code, "recovery_required")
            self.assertEqual(ce.get(book, task["task_id"])["state"], "recovery_required")

    def test_recover_exhausts_attempts_instead_of_looping_forever(self):
        """审计 C-06：崩溃任务达到上限后必须 failed，不能无限重跑。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            states = []
            for _ in range(3):
                claimed = ce.claim(book, "w", lease_seconds=-1, max_attempts=3)
                self.assertEqual(claimed["task_id"], task["task_id"])
                recovered = ce.recover(book, max_attempts=3)
                states.append(recovered[0]["state"])
            self.assertEqual(states, ["pending", "pending", "failed"])
            self.assertEqual(ce.get(book, task["task_id"])["attempts"], 3)
            self.assertIsNone(ce.claim(book, "w", max_attempts=3))

    def test_hold_for_amendment_does_not_freeze_running_task(self):
        """审计 C-08：运行中任务只挂协作停止标志，仍可提交/完成。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "w")
            result = ce.hold_for_amendment(book, "amd_run", [task["task_id"]])
            self.assertEqual(result["held_task_ids"], [])
            self.assertEqual(result["hold_requested_task_ids"], [task["task_id"]])
            held = ce.get(book, task["task_id"])
            self.assertEqual(held["state"], "running")
            self.assertTrue(held["hold_requested"])
            self.assertTrue(ce.begin_commit(book, task["task_id"], "w")["committing"])
            ce.release_amendment(book, "amd_run")
            self.assertFalse(ce.get(book, task["task_id"])["hold_requested"])
            self.assertEqual(ce.complete(book, task["task_id"], owner="w")["state"], "completed")

    def test_begin_commit_rejects_non_running_task(self):
        """审计 C-08：held 任务不能进入提交。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.hold_for_amendment(book, "amd_held", [task["task_id"]])
            with self.assertRaises(ce.SchedulerError) as caught:
                ce.begin_commit(book, task["task_id"], "w")
            self.assertEqual(caught.exception.code, "task_not_running")

    def test_fail_requires_the_current_lease_owner(self):
        """审计 C-33：别的调用者不能把 running 任务打断。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "owner-a")
            with self.assertRaises(ce.SchedulerError) as caught:
                ce.fail(book, task["task_id"], owner="owner-b", error="intruder")
            self.assertEqual(caught.exception.code, "lease_owner_mismatch")
            self.assertEqual(ce.get(book, task["task_id"])["lease_owner"], "owner-a")
            self.assertEqual(ce.fail(book, task["task_id"], owner="owner-a")["state"], "pending")

    def test_project_pause_scope_is_normalized(self):
        """审计 C-34：project:<任意名字> 也必须真正生效。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            ce.submit(book, {}, priority="P1")
            paused = ce.pause(book, "project:书名", "作者暂停")
            self.assertEqual(paused["scope"], "project:" + str(book.resolve()))
            self.assertIsNone(ce.claim(book, "w"))
            ce.resume(book, "project:书名")
            claimed = ce.claim(book, "w")
            self.assertEqual(claimed["state"], "running")
            ce.pause(book, "task:" + claimed["task_id"], "暂停本章")
            self.assertTrue(ce.get(book, claimed["task_id"])["hold_requested"])
            ce.resume(book, "task:" + claimed["task_id"])
            self.assertFalse(ce.get(book, claimed["task_id"])["hold_requested"])
            self.assertEqual(ce.get(book, claimed["task_id"])["state"], "running")

    def test_submit_is_idempotent_with_task_id(self):
        """审计 C-36：客户端重试不得生成重复任务。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            first = ce.submit(book, {"kind": "daily"}, priority="P1", task_id="task_fixed")
            second = ce.submit(book, {"kind": "daily"}, priority="P1", task_id="task_fixed")
            self.assertEqual(first["task_id"], "task_fixed")
            self.assertTrue(second["deduplicated"])
            self.assertEqual(len(ce.list_tasks(book)), 1)

    def test_event_write_failure_does_not_fail_the_business_action(self):
        """审计 C-36：task_events 写失败不能让已提交的任务操作返回错误。"""
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            task = ce.submit(book, {}, priority="P1")
            ce.claim(book, "w")
            with wb.write_tx(book) as db:
                db.execute("DROP TABLE task_events")
            self.assertEqual(ce.complete(book, task["task_id"], owner="w")["state"], "completed")

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

    def test_spawn_worker_captures_stderr(self):
        """审计 C-47：启动错误必须可读，而不是并入被丢弃的 stdout。"""
        import subprocess
        import sys
        process = ce.spawn_worker([sys.executable, "-c",
                                   "import sys; print('boom-startup', file=sys.stderr); sys.exit(3)"])
        output, _ = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 3)
        self.assertIn(b"boom-startup", output or b"")


if __name__ == "__main__":
    unittest.main()
