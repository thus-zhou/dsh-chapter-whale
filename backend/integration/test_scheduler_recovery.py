"""E01.6 只补缺步：上一时段留下的 running/failed/needs_revision 必须在新时段复活。

强杀会留下 `cycle.status="running"`，审查未过会留下 `needs_revision`。旧逻辑对这两种
状态直接跳过，任务从此永远不再被认领，而健康检查仍报正常——静默停更。这里的断言只
关心「跨时段放行、同时段不重复烧钱」这一条边界。
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from integration import bridge, scheduler


def _job(**overrides):
    base = {
        "name": "潮汐钟",
        "project": "",
        "book": "潮汐钟",
        "account": "acc",
        "publication_mode": "draft_only",
        "daily_time": "08:00",
        "daily_times": [],
        "timezone": "Asia/Shanghai",
        "chapters_per_run": 1,
        "word_count": 2000,
        "max_revisions": 1,
        "approval_mode": "unattended",
        "enabled": True,
    }
    base.update(overrides)
    return base


class RetryableTest(unittest.TestCase):
    def test_permanent_states_are_retried_in_a_new_slot(self):
        for status in ("running", "failed", "needs_revision"):
            job = {"cycle": {"status": status}, "last_attempt_slot": "2026-11-20@08:00"}
            self.assertTrue(scheduler.retryable(job, "2026-11-21@08:00"), status)

    def test_same_slot_is_not_retried(self):
        job = {"cycle": {"status": "failed"}, "last_attempt_slot": "2026-11-21@08:00"}
        self.assertFalse(scheduler.retryable(job, "2026-11-21@08:00"))

    def test_missing_attempt_marker_is_not_treated_as_stale(self):
        self.assertFalse(scheduler.retryable({"cycle": {"status": "running"}}, "2026-11-21@08:00"))
        self.assertFalse(scheduler.retryable({"cycle": {}, "last_attempt_slot": "x"}, "y"))
        self.assertFalse(scheduler.retryable({"cycle": {"status": "success"},
                                              "last_attempt_slot": "2026-11-20@08:00"},
                                             "2026-11-21@08:00"))


class DueJobsRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=bridge.COMBINED_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "works" / "潮汐钟"
        (self.project / "正文").mkdir(parents=True)
        self.path = self.root / "scheduler.json"
        self.enterContext(patch.object(scheduler, "SCHEDULER_PATH", self.path))
        self.enterContext(patch.object(scheduler, "RUNS_ROOT", self.root / "runs"))
        self.now = datetime(2026, 11, 21, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    def write(self, job):
        job.setdefault("project", str(self.project))
        job.setdefault("created_at", "2026-11-01T00:00:00+08:00")
        self.path.write_text(json.dumps({
            "version": 2,
            "settings": {"auto_schedule": True},
            "jobs": {"tide": job},
        }, ensure_ascii=False), encoding="utf-8")

    def test_failed_slot_is_due_again_next_slot(self):
        self.write(_job(cycle={"status": "failed"}, last_status="failed",
                        last_attempt_slot="2026-11-20@08:00", last_attempt_date="2026-11-20"))
        due = scheduler.due_jobs(self.now)
        self.assertEqual([row["id"] for row in due], ["tide"])
        self.assertTrue(due[0]["recovering"])

    def test_killed_cycle_is_recovered_across_days(self):
        self.write(_job(cycle={"status": "running"}, last_status="running",
                        last_attempt_slot="2026-11-18@08:00", last_attempt_date="2026-11-18"))
        self.assertEqual(len(scheduler.due_jobs(self.now)), 1)

    def test_revision_pending_does_not_stall_forever(self):
        self.write(_job(cycle={"status": "needs_revision"}, last_status="needs_revision",
                        last_attempt_slot="2026-11-20@08:00", last_attempt_date="2026-11-20"))
        self.assertEqual(len(scheduler.due_jobs(self.now)), 1)

    def test_attempted_this_slot_is_not_repeated(self):
        self.write(_job(cycle={"status": "failed"}, last_status="failed",
                        last_attempt_slot="2026-11-21@08:00", last_attempt_date="2026-11-21"))
        self.assertEqual(scheduler.due_jobs(self.now), [])

    def test_successful_slot_is_not_repeated(self):
        self.write(_job(cycle={"status": "success"}, last_status="success",
                        last_attempt_slot="2026-11-21@08:00", last_attempt_date="2026-11-21"))
        self.assertEqual(scheduler.due_jobs(self.now), [])

    def test_disabled_task_stays_out(self):
        self.write(_job(cycle={"status": "failed"}, enabled=False,
                        last_attempt_slot="2026-11-20@08:00", last_attempt_date="2026-11-20"))
        self.assertEqual(scheduler.due_jobs(self.now), [])


if __name__ == "__main__":
    unittest.main()
