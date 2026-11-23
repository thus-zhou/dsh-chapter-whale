"""0.6.1 排期接口：预览只读、能力未证实不建意图、台账冲突不覆盖、旧 PUT 不擦新键。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from manager import app as module
from integration import bridge, platform_schedule, schedule_buffer, scheduler, writer_runner


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


CAPABILITY = {
    "observed_at": "2026-11-21T00:00:00+08:00",
    "source": "author_confirmed",
    "evidence": "作者后台排期页截图",
    "can_read_schedule": True,
    "can_schedule": True,
    "can_confirm_schedule": True,
    "can_confirm_body": True,
    "lead_time_minutes": 30,
    "max_scheduled": 20,
    "max_chapters_per_day": 3,
}


class ScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="schedule-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text('{"title":"测试作品"}', encoding="utf-8")
        self.ai_path = self.root / "ai.json"
        self.ai_path.write_text(json.dumps({"base_url": "https://fixture.invalid/v1", "model": "m",
                                            "api_key": "NOT-A-REAL-KEY"}), encoding="utf-8")
        self.scheduler_path = self.root / "scheduler.json"
        self.patches = [
            patch.object(module, "DATA", self.root),
            patch.object(module, "AI_PATH", self.ai_path),
            patch.object(module.secret_store, "codec", lambda: fake_pair()),
            patch.object(scheduler, "SCHEDULER_PATH", self.scheduler_path),
            patch.object(scheduler, "RUNS_ROOT", self.root / "runs"),
            patch.object(bridge, "COMBINED_ROOT", self.root),
            patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"),
            patch.object(module.Operations, "_execute", lambda self, identity, args: None),
            patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.data)}),
            patch.object(writer_runner, "reviewed_chapters", return_value={
                1: {"sha256": "a" * 64, "word_count": "2000"},
                2: {"sha256": "b" * 64, "word_count": "2100"},
            }),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        module._AI_MIGRATION_TRIED = False
        self.client = TestClient(module.create_app(self.root / "manager.db", start_dispatcher=False))
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        self.identity = "daily"
        registered = self.client.post("/api/projects", json={"path": str(self.project)},
                                      headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.write_scheduler()

    def write_scheduler(self, **overrides):
        job = {"name": "日更", "project": str(self.project), "book": "潮汐钟", "account": "acc",
               "publication_mode": "platform_scheduled", "platform": "fanqie",
               "schedule_buffer": {}, "daily_time": "08:00", "daily_times": [],
               "quota_phases": [], "slot_quotas": None, "delivery_mode": "serial",
               "timezone": "Asia/Shanghai", "chapters_per_run": 1, "word_count": 2000,
               "max_revisions": 1, "volume": None, "approval_mode": "unattended",
               "enabled": True, "created_at": "2026-11-20T00:00:00+08:00",
               "last_attempt_date": "", "last_run_date": "", "last_status": ""}
        job.update(overrides)
        self.scheduler_path.write_text(json.dumps(
            {"version": 2, "revision": 0, "updated_at": "", "jobs": {self.identity: job}},
            ensure_ascii=False), encoding="utf-8")

    def job(self) -> dict:
        return scheduler.load_scheduler()["jobs"][self.identity]

    def record_capability(self, **overrides):
        body = {**CAPABILITY, **overrides}
        response = self.client.post(f"/api/jobs/{self.identity}/schedule/capability",
                                    json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def settings(self, **overrides) -> dict:
        values = {"enabled": True, "target_days": 2, "slots": ["08:00", "12:00"],
                  "chapters_per_slot": 1, "keep_local": 0, "stop_after_gap": True}
        values.update(overrides)
        return values

    def apply(self, expected: str = "", **overrides):
        return self.client.post(f"/api/jobs/{self.identity}/schedule/apply",
                                json={"schedule_buffer": self.settings(**overrides),
                                      "expected_updated_at": expected}, headers=self.headers)

    # --- 只读视图 ---------------------------------------------------------
    def test_view_and_preview_do_not_write_anything(self):
        before = self.scheduler_path.read_text(encoding="utf-8")
        missing = self.client.get("/api/jobs/unknown/schedule", headers=self.headers)
        self.assertEqual(missing.status_code, 404)
        view = self.client.get(f"/api/jobs/{self.identity}/schedule", headers=self.headers)
        self.assertEqual(view.status_code, 200, view.text)
        body = view.json()
        self.assertEqual(body["platform"], "fanqie")
        self.assertEqual(body["settings"]["target_days"], 2)
        # 没登记能力时不能把“没排过”说成“已排期”。
        self.assertEqual(body["capability"].get("can_confirm_schedule"), None)
        self.assertEqual(body["preview"]["status"], "disabled")
        preview = self.client.post(f"/api/jobs/{self.identity}/schedule/preview", headers=self.headers)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(schedule_buffer.store_path(self.identity).exists())
        self.assertEqual(self.scheduler_path.read_text(encoding="utf-8"), before)

    # --- 能力记录 ---------------------------------------------------------
    def test_capability_record_is_reported_and_enables_auto(self):
        result = self.record_capability()
        self.assertTrue(result["auto_allowed"], result)
        view = self.client.get(f"/api/jobs/{self.identity}/schedule", headers=self.headers).json()
        self.assertTrue(view["capability"]["can_confirm_schedule"])
        self.assertEqual(view["capability"]["lead_time_minutes"], 30)
        # 只读能力、不能确认时必须挡住自动排期。
        limited = self.record_capability(can_confirm_schedule=False)
        self.assertFalse(limited["auto_allowed"])
        self.assertIn("未证实", limited["reason"])

    # --- 能力不足只保设置 -------------------------------------------------
    def test_apply_without_capability_saves_settings_but_creates_no_intent(self):
        response = self.apply()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "capability_unknown")
        self.assertEqual(response.json()["settings"]["slots"], ["08:00", "12:00"])
        self.assertEqual(self.job()["schedule_buffer"]["slots"], ["08:00", "12:00"])
        self.assertFalse(schedule_buffer.store_path(self.identity).exists())

    # --- 台账冲突 ---------------------------------------------------------
    def test_apply_rejects_stale_expected_updated_at(self):
        self.record_capability()
        first = self.apply()
        self.assertEqual(first.status_code, 200, first.text)
        stamp = schedule_buffer.load_store(self.identity)["updated_at"]
        self.assertTrue(stamp)
        stale = self.apply(expected="2000-01-01T00:00:00+00:00", target_days=5)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["code"], "stale_buffer")
        self.assertEqual(stale.json()["updated_at"], stamp)
        # 冲突时不能把对方刚写的计划改成自己的。
        self.assertEqual(schedule_buffer.load_store(self.identity)["updated_at"], stamp)
        self.assertEqual(self.job()["schedule_buffer"]["target_days"], 2)
        fresh = self.apply(expected=stamp, target_days=5)
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertEqual(self.job()["schedule_buffer"]["target_days"], 5)

    # --- 旧客户端 PUT -----------------------------------------------------
    def test_old_put_without_schedule_buffer_keeps_saved_plan(self):
        self.record_capability()
        self.assertEqual(self.apply().status_code, 200)
        saved = self.job()["schedule_buffer"]
        self.assertTrue(saved["enabled"])
        body = {"name": "改名", "project": str(self.project), "book": "潮汐钟", "account": "acc",
                "daily_time": "08:00", "timezone": "Asia/Shanghai", "chapters_per_run": 1,
                "word_count": 2000, "max_revisions": 1, "enabled": True,
                "approval_mode": "unattended"}
        response = self.client.put(f"/api/jobs/{self.identity}", json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        after = self.job()
        self.assertEqual(after["name"], "改名")
        self.assertEqual(after["publication_mode"], "platform_scheduled")
        self.assertEqual(after["schedule_buffer"]["slots"], saved["slots"])
        self.assertEqual(after["schedule_buffer"]["target_days"], saved["target_days"])

    # --- 停补货 / 恢复 ----------------------------------------------------
    def test_stop_keeps_existing_intents_and_resume_clears_flag(self):
        self.record_capability()
        self.assertEqual(self.apply().status_code, 200)
        store = schedule_buffer.load_store(self.identity)
        total = len(store["intents"])
        self.assertGreaterEqual(total, 1)
        stopped = self.client.post(f"/api/jobs/{self.identity}/schedule/stop", headers=self.headers)
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertTrue(stopped.json()["stopped"])
        self.assertGreaterEqual(stopped.json()["remote_untouched"], 1)
        self.assertEqual(len(schedule_buffer.load_store(self.identity)["intents"]), total)
        resumed = self.client.post(f"/api/jobs/{self.identity}/schedule/resume", headers=self.headers)
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertFalse(resumed.json()["stopped"])

    # --- 对账 -------------------------------------------------------------
    # --- 模式门槛 / 旧 PUT 保真 / 关补货不覆盖计划 -------------------------
    def test_apply_rejects_task_that_is_not_scheduled_mode(self):
        self.write_scheduler(publication_mode="draft_only", account="")
        response = self.apply()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "not_scheduled_job")
        self.assertFalse(schedule_buffer.store_path(self.identity).exists(),
                         "非排期任务不得留下意图，否则切模式时会一次性补写")

    def test_old_put_keeps_platform_and_account(self):
        self.write_scheduler(platform="qidian", account="acc-qd")
        body = {"name": "改名", "project": str(self.project), "book": "潮汐钟",
                "daily_time": "08:00", "chapters_per_run": 1, "word_count": 2000}
        response = self.client.put(f"/api/jobs/{self.identity}", json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        after = self.job()
        self.assertEqual(after["platform"], "qidian", "旧客户端不传 platform 不得重置为默认平台")
        self.assertEqual(after["account"], "acc-qd", "旧客户端不传 account 不得清空账号")

    def test_disabled_apply_saves_settings_without_clobbering_plan(self):
        self.record_capability()
        self.assertEqual(self.apply().status_code, 200)
        saved = schedule_buffer.load_store(self.identity)["plan"]["planned_count"]
        self.assertGreaterEqual(saved, 1)
        response = self.apply(enabled=False, target_days=3)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["applied"], 0)
        store = schedule_buffer.load_store(self.identity)
        self.assertEqual(store["plan"]["planned_count"], saved, "关补货不能把已有计划覆盖成空预览")
        self.assertEqual(self.job()["schedule_buffer"]["target_days"], 3)

    def test_resolve_clears_review_item(self):
        """结果未知必须能销账，否则排期永久停写。"""
        self.record_capability()
        self.assertEqual(self.apply().status_code, 200)
        entry = schedule_buffer.load_store(self.identity)["intents"][0]
        schedule_buffer.mark_failed(self.identity, entry["key"], "提交结果未知")
        listing = self.client.get(f"/api/jobs/{self.identity}/schedule/review", headers=self.headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(len(listing.json()["items"]), 1)
        resolved = self.client.post(f"/api/jobs/{self.identity}/schedule/resolve",
                                    json={"chapter_id": int(entry["chapter_id"]),
                                          "resolution": "cancelled", "note": "平台没有该章"},
                                    headers=self.headers)
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["changed"], 1)
        again = self.client.get(f"/api/jobs/{self.identity}/schedule/review", headers=self.headers)
        self.assertEqual(again.json()["items"], [])

    def test_reconcile_accepts_manual_rows_without_adapter(self):
        """没有适配器时，作者粘贴的只读清单也能对账。"""
        self.record_capability()
        self.assertEqual(self.apply().status_code, 200)
        entry = schedule_buffer.load_store(self.identity)["intents"][0]
        row = {"chapter_id": entry["chapter_id"], "book_id": "潮汐钟", "account": "acc",
               "state": "已排期", "planned_at": entry["planned_at"],
               "content_sha256": entry["version_sha256"]}
        response = self.client.post(f"/api/jobs/{self.identity}/schedule/reconcile",
                                    json={"rows": [row], "complete": True,
                                          "source": "author_import"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["reconcile"]["verified"], 1)

    def test_apply_rejects_stale_revision(self):
        self.record_capability()
        self.assertEqual(self.apply().status_code, 200)
        revision = int(schedule_buffer.load_store(self.identity)["revision"])
        stale = self.client.post(f"/api/jobs/{self.identity}/schedule/apply",
                                 json={"schedule_buffer": self.settings(target_days=4),
                                       "expected_revision": max(0, revision - 1)},
                                 headers=self.headers)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["code"], "stale_buffer")
        self.assertEqual(stale.json()["revision"], revision)

    def test_reconcile_without_adapter_or_rows_is_a_conflict(self):
        response = self.client.post(f"/api/jobs/{self.identity}/schedule/reconcile",
                                    headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "adapter_unavailable")
        # 没有回读能力时不得凭空写出已排期。
        self.assertFalse(schedule_buffer.store_path(self.identity).exists())


if __name__ == "__main__":
    unittest.main()
