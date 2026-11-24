"""0.6.1 排期执行器（审计后）：能力未证实只落本地、无适配器不谎报、过期不补写、
写入前重验版本、结果未知不重试、待对账时整轮停写。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from integration import (platform_adapters, platform_schedule as ps, schedule_buffer as sb,
                         scheduled_delivery as sd, writer_runner as writer)

BOOK, ACCOUNT, PLATFORM = "潮汐钟", "acc", "fanqie"


def capability(**overrides):
    caps = {"can_read_schedule": True, "can_schedule": True, "can_confirm_schedule": True,
            "can_confirm_body": True, "lead_time_minutes": 0, "max_scheduled": 10,
            "max_chapters_per_day": 6}
    caps.update(overrides)
    return {"platform": PLATFORM, "account": ACCOUNT, "book_id": BOOK,
            "observed_at": "2026-11-21T00:00:00+08:00", "source": "author_confirmed",
            "capabilities": caps}


class FakeAdapter:
    def __init__(self, *, fail: bool = False, reject: bool = False, vague: bool = False):
        self.fail, self.reject, self.vague = fail, reject, vague
        self.calls = []

    def submit_scheduled(self, job, intent, chapter_path):
        self.calls.append((str(intent["chapter_id"]), chapter_path))
        if self.fail:
            raise RuntimeError("平台超时，结果未知")
        if self.reject:
            return {"scheduled": False, "reason": "平台拒绝：该书今日排期满"}
        if self.vague:
            return {"status": "ok"}
        return {"scheduled": True, "remote_id": f"r-{intent['chapter_id']}",
                "planned_at": intent["planned_at"], "chapter_id": intent["chapter_id"],
                "book_id": BOOK, "account": ACCOUNT}

    def read_schedule(self, platform, account, book_id):
        return []


def job(**overrides):
    values = {
        "name": "日更", "project": str(Path(tempfile.gettempdir())), "book": BOOK,
        "account": ACCOUNT, "platform": PLATFORM, "publication_mode": "platform_scheduled",
        "timezone": "Asia/Shanghai", "daily_time": "08:00", "daily_times": [],
        "schedule_buffer": {"enabled": True, "target_days": 1, "slots": ["08:00", "12:00"],
                            "chapters_per_slot": 1, "keep_local": 0, "stop_after_gap": True},
    }
    values.update(overrides)
    return values


def receipt(chapter: int, sha: str) -> dict:
    return {"sha256": sha, "word_count": "2000", "destination": f"正文/第{chapter}章.md"}


class ScheduledDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scheduled-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "works" / BOOK
        self.project.mkdir(parents=True)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.root / "data")}))
        platform_adapters.clear()
        self.addCleanup(platform_adapters.clear)
        # 生成/审查/落稿由 draft_delivery 自己的测试覆盖；这里只验证排期口径。
        self.enterContext(patch.object(sd.draft_delivery, "step", side_effect=self._fake_generate))
        self.receipts = {1: receipt(1, "a" * 64), 2: receipt(2, "b" * 64)}
        self.reviewed = self.enterContext(patch.object(
            writer, "reviewed_chapters", side_effect=lambda p: dict(self.receipts)))
        self.record = {"job_id": "daily"}
        self.cycle = {"status": "running"}
        self.job = job(project=str(self.project))
        # 调度器存储不在本测试职责内：只验证 cycle 投影本身。
        self.enterContext(patch.object(sd.s, "_update_run"))

    @staticmethod
    def _fake_generate(job_id, job_doc, cycle, quota, record, force, **kwargs):
        cycle["remote_state"] = "not_attempted"
        return {"status": "success", "job_id": job_id, "record": record, **kwargs}

    # --- 夹具：直接种一条“已计划”意图，避开真实时钟与时段 -------------------
    def seed(self, chapter: int, sha: str, *, offset_minutes: int = 180,
             state: str = "planned") -> str:
        planned_at = (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)) \
            .astimezone(ps.job_zone("Asia/Shanghai")[0]).isoformat(timespec="seconds")
        key = ps.schedule_intent_key("daily", PLATFORM, ACCOUNT, BOOK, chapter, sha)
        store = sb.load_store("daily")
        store["intents"] = [item for item in store["intents"] if item.get("key") != key]
        store["intents"].append({
            "key": key, "job_id": "daily", "platform": PLATFORM, "account": ACCOUNT,
            "book_id": BOOK, "chapter_id": str(chapter), "version_sha256": sha,
            "planned_at": planned_at, "state": state, "attempts": 0, "submitted_at": "",
            "remote": {}, "last_error": "", "created_at": planned_at,
        })
        sb.save_store("daily", store)
        return key

    def submit(self, **cap) -> dict:
        return sd._submit_planned("daily", self.job, capability(**cap), sb.load_store("daily"))

    def states(self) -> dict:
        return {item["chapter_id"]: item["state"] for item in sb.load_store("daily")["intents"]}

    # --- 能力与开关 -----------------------------------------------------------
    def test_capability_unknown_only_leaves_local_draft(self):
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        result = sd.step("daily", self.job, self.cycle, {}, self.record, False)
        self.assertEqual(result["schedule_status"], "capability_unknown")
        self.assertEqual(result["remote_state"], "capability_unknown")
        self.assertEqual(result["publication"]["mode"], "platform_scheduled")
        self.assertEqual(adapter.calls, [])
        self.assertEqual(sb.load_store("daily")["intents"], [])
        self.assertEqual(self.cycle["remote_state"], "capability_unknown")

    def test_stopped_buffer_does_not_touch_remote_plan(self):
        ps.record_capability(capability())
        key = self.seed(1, "a" * 64, offset_minutes=180)
        sb.stop_replenish("daily")
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        result = sd.step("daily", self.job, self.cycle, {}, self.record, False)
        self.assertEqual(result["schedule_status"], "stopped")
        self.assertEqual(adapter.calls, [])
        self.assertEqual(self.states()["1"], "planned", "关闭补货不得撤销已有意图")
        self.assertEqual(sb.load_store("daily")["intents"][0]["key"], key)

    # --- 提交 ---------------------------------------------------------------
    def test_submit_records_remote_identity_and_counts_once(self):
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64)
        self.seed(2, "b" * 64)
        stats = self.submit()
        self.assertEqual(stats["submitted"], 2)
        self.assertEqual([chapter for chapter, _ in adapter.calls], ["1", "2"])
        store = sb.load_store("daily")
        self.assertEqual({item["state"] for item in store["intents"]}, {"submitted"})
        first = store["intents"][0]
        self.assertEqual(first["remote"]["remote_id"], "r-1")
        self.assertEqual(first["remote"]["book_id"], BOOK)
        self.assertEqual(first["attempts"], 1)
        # 再跑一轮：已提交的章不得重复写。
        again = self.submit()
        self.assertEqual(again["submitted"], 0)
        self.assertEqual(len(adapter.calls), 2)

    def test_missing_adapter_blocks_without_fake_schedule(self):
        self.seed(1, "a" * 64)
        stats = self.submit()
        self.assertIn("适配器", stats["blocked"])
        self.assertEqual(stats["submitted"], 0)
        intent = sb.load_store("daily")["intents"][0]
        self.assertEqual(intent["state"], "planned", "没有适配器不等于平台已收")
        self.assertEqual(intent["attempts"], 0)

    def test_rejected_is_terminal_not_retried(self):
        adapter = FakeAdapter(reject=True)
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64)
        stats = self.submit()
        self.assertEqual(stats["rejected"], 1)
        intent = sb.load_store("daily")["intents"][0]
        self.assertEqual(intent["state"], "failed")
        self.assertEqual(intent["attempts"], 1)
        self.submit()
        self.assertEqual(len(adapter.calls), 1, "明确拒绝不得自动重试")

    def test_changed_body_is_stale_and_never_submitted(self):
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64)
        self.seed(2, "b" * 64)
        # 计划时是 a/b，提交前第 1 章正文被改过。
        self.reviewed.side_effect = lambda p: {1: receipt(1, "c" * 64), 2: receipt(2, "b" * 64)}
        stats = self.submit()
        self.assertEqual(stats["stale"], 1)
        self.assertEqual([chapter for chapter, _ in adapter.calls], ["2"])
        states = self.states()
        self.assertEqual(states["1"], "stale")
        self.assertEqual(states["2"], "submitted")

    def test_unknown_result_stops_batch_and_never_retries(self):
        adapter = FakeAdapter(fail=True)
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64)
        self.seed(2, "b" * 64)
        stats = self.submit()
        self.assertEqual(stats["unknown"], 1)
        self.assertIn("只读对账", stats["blocked"])
        self.assertEqual(len(adapter.calls), 1, "结果未知必须先停下，不能继续写第二章")
        states = self.states()
        self.assertEqual(states["1"], "needs_review")
        self.assertEqual(states["2"], "planned")
        # 有待对账的章时整轮不写：第二章也不得被顺带提交。
        again = self.submit()
        self.assertEqual(again["submitted"], 0)
        self.assertIn("待对账", again["blocked"])
        self.assertEqual(len(adapter.calls), 1)

    def test_vague_result_is_unknown_not_success(self):
        adapter = FakeAdapter(vague=True)
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64)
        stats = self.submit()
        self.assertEqual(stats["submitted"], 0)
        self.assertEqual(stats["unknown"], 1)
        self.assertEqual(self.states()["1"], "needs_review")

    def test_expired_intent_is_not_submitted(self):
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64, offset_minutes=-5)
        stats = self.submit()
        self.assertEqual(stats["expired"], 1)
        self.assertEqual(adapter.calls, [], "过期意图迟到提交在平台上等于立即发布")
        intent = sb.load_store("daily")["intents"][0]
        self.assertEqual(intent["state"], "expired")
        self.assertEqual(intent["attempts"], 0)

    def test_lead_time_defers_slot_without_writing(self):
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64, offset_minutes=30)
        stats = self.submit(lead_time_minutes=120)
        self.assertEqual(stats["too_soon"], 1)
        self.assertEqual(adapter.calls, [])
        self.assertEqual(self.states()["1"], "planned")

    def test_max_scheduled_limits_batch(self):
        adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, adapter)
        self.seed(1, "a" * 64)
        self.seed(2, "b" * 64)
        stats = self.submit(max_scheduled=1)
        self.assertEqual(stats["submitted"], 1)
        self.assertIn("上限", stats["blocked"])
        self.assertEqual(len(adapter.calls), 1)


if __name__ == "__main__":
    unittest.main()
