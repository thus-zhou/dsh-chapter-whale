import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import bridge, notification_hooks as hooks, notifications
except ImportError:
    import bridge
    import notification_hooks as hooks
    import notifications


class NotificationHookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.dict(os.environ, {
            "NOVEL_HELPER_NOTIFICATIONS_DB": str(self.root / "notifications.sqlite3")}))
        self.job = {"project": str(self.root / "潮汐钟"), "book": "潮汐钟",
                    "publication_mode": "draft_only"}

    def record(self, **overrides):
        record = {"job_id": "tide", "status": "success", "publication_mode": "draft_only",
                  "run_date": "2026-03-08", "slot": "2026-03-08@07:30",
                  "started_at": "2026-03-08T07:30:00+08:00",
                  "saved_ids": [1], "saved_words": 2100,
                  "remote_state": "not_applicable", "verification": "local"}
        record.update(overrides)
        return record

    def test_success_without_recipients_still_records_local_event(self):
        summary = hooks.on_run_finished("tide", self.job, self.record())
        self.assertEqual(summary["state"], "recorded")
        db = hooks.connection()
        try:
            events = notifications.list_events(db)
            self.assertEqual([item["event_type"] for item in events], ["run.summary"])
            self.assertEqual(events[0]["recipient_count"], 0)
            self.assertEqual(notifications.list_outbox(db), [])
        finally:
            db.close()

    def test_repeated_review_failure_keeps_one_open_incident(self):
        record = self.record(status="needs_revision", reason_code="review_failed",
                             needs_revision=[{"chapter_id": 2, "issues": ["时间线矛盾"]}],
                             saved_ids=[], last_message="存稿未通过审查")
        for _ in range(20):
            summary = hooks.on_run_finished("tide", self.job, record)
            self.assertEqual(summary["state"], "recorded")
        db = hooks.connection()
        try:
            incidents = notifications.list_incidents(db)
            self.assertEqual(len(incidents), 1)
            self.assertEqual(incidents[0]["status"], "open")
            self.assertEqual(incidents[0]["sequence"], 1)
            self.assertEqual(len(notifications.list_events(db)), 1)
            resolved = hooks.resolve("tide", note="作者已修订")
            self.assertTrue(resolved[0]["resolved"])
            self.assertEqual(notifications.list_incidents(db, status="open"), [])
        finally:
            db.close()
        hooks.on_run_finished("tide", self.job, record)
        db = hooks.connection()
        try:
            incidents = notifications.list_incidents(db)
            self.assertEqual(len(incidents), 2)
            self.assertEqual(sorted(item["sequence"] for item in incidents), [1, 2])
        finally:
            db.close()

    def test_configured_recipient_gets_one_pending_outbox_row_per_event(self):
        db = hooks.connection()
        try:
            recipient = notifications.add_recipient(
                db, "https://hooks.example.com/chapter-whale", "secret-value")
            self.assertNotIn("secret-value", json.dumps(recipient, ensure_ascii=False))
        finally:
            db.close()
        record = self.record(status="blocked", reason_code="budget_exceeded",
                             last_message="预算不足，已停止本批次", saved_ids=[])
        summary = hooks.on_run_finished("tide", self.job, record)
        self.assertEqual(summary["queued"], 1)
        db = hooks.connection()
        try:
            rows = notifications.list_outbox(db)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "pending")
            self.assertEqual(rows[0]["event_idempotency"] != "", True)
            payload = json.dumps(rows[0], ensure_ascii=False)
            self.assertNotIn("secret-value", payload)
            self.assertNotIn(str(self.root), payload)
        finally:
            db.close()
        hooks.on_run_finished("tide", self.job, record)
        db = hooks.connection()
        try:
            self.assertEqual(len(notifications.list_outbox(db)), 1)
        finally:
            db.close()

    def test_notification_failure_never_changes_run_result(self):
        with patch.object(hooks, "connection", side_effect=RuntimeError("磁盘只读")):
            summary = hooks.on_run_finished("tide", self.job, self.record())
        self.assertEqual(summary["state"], "failed")
        self.assertIn("磁盘只读", summary["error"])

    def test_metadata_pending_records_paused_event(self):
        summary = hooks.on_run_finished("tide", self.job,
            self.record(status="metadata_pending", next_action="补同步当前正文"))
        self.assertEqual(summary["state"], "recorded")
        self.assertEqual(summary["events"][0]["event_type"], "job.paused")

    def test_private_local_path_is_not_forwarded_to_notification(self):
        hooks.on_run_finished('tide', self.job, self.record(status='metadata_pending',
            last_message=str(self.root/'private-book'), next_action=str(self.root/'private-action')))
        db=hooks.connection()
        try:
            self.assertNotIn(str(self.root),json.dumps(notifications.list_events(db)))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
