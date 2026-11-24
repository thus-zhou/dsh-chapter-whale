"""B01/B02 单测：排期识别、能力记录、缓冲计划、台账幂等与只读对账。

这些测试按审计报告补了此前缺失的路径：跨天重排、过期意图、能力上限为 0、
身份不符/缺正文身份、负向文案、跨午夜、重复行、对账不降级。
"""
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from integration import platform_schedule as ps
from integration import schedule_buffer as sb
from integration import writer_runner as writer

TZ = "Asia/Shanghai"
CAP = {"capabilities": {"can_read_schedule": True, "can_schedule": True,
                        "can_confirm_schedule": True, "can_confirm_body": True,
                        "lead_time_minutes": 0, "max_scheduled": 10,
                        "max_chapters_per_day": 6}}
SHA = {1: "a" * 64, 2: "b" * 64, 3: "c" * 64, 4: "d" * 64, 5: "e" * 64, 6: "f" * 64}


def _job(**overrides):
    job = {"job_id": "daily", "platform": "fanqie", "account": "acc", "book": "潮汐钟",
           "timezone": TZ, "project": "/tmp/proj",
           "schedule_buffer": {"enabled": True, "target_days": 2,
                               "slots": ["08:00", "12:00"], "chapters_per_slot": 1,
                               "keep_local": 0}}
    job.update(overrides)
    return job


def _approved(count=5):
    return [{"chapter_id": i, "version_sha256": SHA[i]} for i in range(1, count + 1)]


def _at(text):
    return datetime.fromisoformat(text + "+08:00")


class PlatformScheduleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": self.temp.name}))

    def test_text_states_and_negative_words(self):
        self.assertEqual(ps.classify_state("已发布"), ps.STATE_PUBLISHED)
        self.assertEqual(ps.classify_state("定时发布"), ps.STATE_SCHEDULED)
        self.assertEqual(ps.classify_state("审核中"), ps.STATE_IN_REVIEW)
        self.assertEqual(ps.classify_state("草稿"), ps.STATE_PLAIN_DRAFT)
        self.assertEqual(ps.classify_state("审核不通过"), ps.STATE_RETURNED)
        # 审计实例：负向词曾被判成已排期。
        self.assertEqual(ps.classify_state("定时发布失败"), ps.STATE_RETURNED)
        self.assertEqual(ps.classify_state("已取消定时发布"), ps.STATE_RETURNED)
        self.assertEqual(ps.classify_state("已发布 审核中"), ps.STATE_UNKNOWN)
        self.assertEqual(ps.classify_state(""), ps.STATE_UNKNOWN)

    def test_row_missing_chapter_id_is_needs_review(self):
        row = ps.normalize_row({"state": "已发布", "book_id": "潮汐钟"}, platform="fanqie",
                               account="acc", book_id="潮汐钟")
        self.assertEqual(row["chapter_id"], "")
        self.assertFalse(row["identity_ok"])

    def test_row_book_mismatch_is_needs_review_and_not_overwritten(self):
        row = ps.normalize_row({"chapter_id": 3, "book_id": "别的作品", "state": "已发布"},
                               platform="fanqie", account="acc", book_id="潮汐钟")
        self.assertEqual(row["book_id"], "别的作品")  # 不得用期望值改写平台事实
        self.assertTrue(any("作品 ID" in reason for reason in row["needs_review"]))

    def test_row_missing_book_is_not_filled_from_expected(self):
        row = ps.normalize_row({"chapter_id": 3, "state": "已发布"}, platform="fanqie",
                               account="acc", book_id="潮汐钟")
        self.assertEqual(row["book_id"], "")
        self.assertFalse(row["identity_ok"])

    def test_account_identity_rules(self):
        mismatch = ps.normalize_row({"chapter_id": 1, "book_id": "潮汐钟", "account": "other",
                                     "state": "已发布"}, platform="fanqie",
                                    account="acc", book_id="潮汐钟")
        self.assertTrue(any("账号" in reason for reason in mismatch["needs_review"]))
        collector = ps.normalize_row({"chapter_id": 1, "book_id": "潮汐钟", "state": "已发布"},
                                     platform="fanqie", account="acc", book_id="潮汐钟")
        self.assertEqual(collector["account"], "acc")
        self.assertEqual(collector["account_source"], "collector")
        self.assertTrue(collector["identity_ok"])

    def test_naive_planned_at_is_marked(self):
        row = ps.normalize_row({"chapter_id": 1, "book_id": "潮汐钟", "account": "acc",
                                "state": "定时发布", "planned_at": "2026-11-22T08:00:00"},
                               platform="fanqie", account="acc", book_id="潮汐钟")
        self.assertTrue(row["timezone_assumed"])
        self.assertIn("+08:00", row["planned_at"])

    def test_duplicate_rows_deduped_and_conflicts_flagged(self):
        base = {"chapter_id": 1, "book_id": "潮汐钟", "account": "acc",
                "content_sha256": SHA[1]}
        snapshot = ps.read_snapshot(
            [{**base, "state": "已发布"}, {**base, "state": "已发布"}],
            platform="fanqie", account="acc", book_id="潮汐钟")
        self.assertEqual(len(snapshot["entries"]), 1)
        self.assertEqual(snapshot["duplicates"], 1)
        conflict = ps.read_snapshot(
            [{**base, "state": "已发布"}, {**base, "state": "草稿"}],
            platform="fanqie", account="acc", book_id="潮汐钟")
        self.assertEqual(len(conflict["entries"]), 0)
        self.assertEqual(len(conflict["conflicts"]), 1)
        self.assertEqual(len(conflict["needs_review"]), 2)

    def test_capability_requires_every_item_and_positive_limits(self):
        self.assertEqual(ps.can_auto_schedule(CAP), (True, ""))
        missing = {"capabilities": {**CAP["capabilities"]}}
        missing["capabilities"].pop("can_confirm_body")
        self.assertFalse(ps.can_auto_schedule(missing)[0])
        zero = {"capabilities": {**CAP["capabilities"], "max_chapters_per_day": 0}}
        self.assertFalse(ps.can_auto_schedule(zero)[0])
        zero_total = {"capabilities": {**CAP["capabilities"], "max_scheduled": 0}}
        self.assertFalse(ps.can_auto_schedule(zero_total)[0])
        unknown = {"capabilities": dict(ps._UNKNOWN_CAPABILITY)}
        self.assertFalse(ps.can_auto_schedule(unknown)[0])

    def test_intent_key_ignores_planned_time(self):
        first = ps.schedule_intent_key("daily", "fanqie", "acc", "潮汐钟", 1, SHA[1])
        second = ps.schedule_intent_key("daily", "fanqie", "acc", "潮汐钟", 1, SHA[1])
        other_platform = ps.schedule_intent_key("daily", "other", "acc", "潮汐钟", 1, SHA[1])
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_platform)
        self.assertNotEqual(first, ps.schedule_intent_key("daily", "fanqie", "acc", "潮汐钟", 1, SHA[2]))

    def test_same_instant_tolerance_is_one_second(self):
        self.assertTrue(ps.same_instant("2026-11-22T08:00:00+08:00", "2026-11-22T00:00:00Z"))
        self.assertTrue(ps.same_instant("2026-11-22T08:00:00+08:00", "2026-11-22T08:00:01+08:00"))
        self.assertFalse(ps.same_instant("2026-11-22T08:00:00+08:00", "2026-11-22T08:01:00+08:00"))

    def test_capability_record_roundtrip(self):
        record = ps.record_capability({"platform": "fanqie", "account": "acc",
                                       "book_id": "潮汐钟",
                                       "capabilities": {"can_schedule": True}})
        self.assertTrue(record["capabilities"]["can_schedule"])
        self.assertIsNone(record["capabilities"]["max_scheduled"])
        loaded = ps.capability_for("fanqie", "acc", "潮汐钟")
        self.assertTrue(loaded["capabilities"]["can_schedule"])
        self.assertIsNone(ps.capability_for("fanqie", "acc", "别的书")["capabilities"]["can_schedule"])


class BufferPlanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": self.temp.name}))

    def settings(self, **overrides):
        settings = {"enabled": True, "target_days": 2, "slots": ["08:00", "12:00"],
                    "chapters_per_slot": 1, "keep_local": 0}
        settings.update(overrides)
        return settings

    def test_three_slots_stop_before_gap(self):
        planned = sb.plan(_job(), now=_at("2026-11-20T09:00:00"),
                          approved=_approved(2), capability=CAP,
                          settings=self.settings(slots=["08:00", "12:00", "20:00"]))
        # 08:00 已过：第一档是 12:00，两章排完，20:00 留下缺口。
        self.assertEqual([entry["planned_at"] for entry in planned["entries"]],
                         ["2026-11-20T12:00:00+08:00", "2026-11-20T20:00:00+08:00"])
        self.assertEqual(planned["coverage"]["gap_at"], "2026-11-21T08:00:00+08:00")
        self.assertIn("未填满", planned["coverage"]["gap_reason"])

    def test_keep_local_leaves_tail_unplanned(self):
        planned = sb.plan(_job(), now=_at("2026-11-20T07:00:00"), approved=_approved(4),
                          capability=CAP, settings=self.settings(keep_local=2))
        self.assertEqual([entry["chapter_id"] for entry in planned["entries"]], [1, 2])
        self.assertEqual(planned["local_remaining"], 2)

    def test_cross_midnight_schedules_next_morning(self):
        planned = sb.plan(_job(), now=_at("2026-11-20T23:30:00"), approved=_approved(2),
                          capability=CAP, settings=self.settings(target_days=1))
        self.assertEqual([entry["planned_at"] for entry in planned["entries"]],
                         ["2026-11-21T08:00:00+08:00", "2026-11-21T12:00:00+08:00"])
        self.assertEqual(planned["status"], "ok")

    def test_lead_time_skips_too_soon_slot(self):
        capability = {"capabilities": {**CAP["capabilities"], "lead_time_minutes": 120}}
        planned = sb.plan(_job(), now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                          capability=capability, settings=self.settings(target_days=1))
        # 07:00 + 120 分钟 = 09:00，08:00 这一档在提前量之内，不排。
        self.assertEqual([entry["planned_at"] for entry in planned["entries"]],
                         ["2026-11-20T12:00:00+08:00"])

    def test_zero_daily_capacity_is_not_unlimited(self):
        capability = {"capabilities": {**CAP["capabilities"], "max_chapters_per_day": 0}}
        planned = sb.plan(_job(), now=_at("2026-11-20T07:00:00"), approved=_approved(2),
                          capability=capability, settings=self.settings())
        self.assertEqual(planned["status"], "capacity_exhausted")
        self.assertEqual(planned["entries"], [])

    def test_max_scheduled_limits_total_in_flight(self):
        capability = {"capabilities": {**CAP["capabilities"], "max_scheduled": 2}}
        planned = sb.plan(_job(), now=_at("2026-11-20T07:00:00"), approved=_approved(4),
                          capability=capability, settings=self.settings(target_days=3))
        self.assertEqual(planned["planned_count"], 2)

    def test_existing_intents_are_not_replanned_cross_day(self):
        job = _job()
        first = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(6),
                        capability=CAP, settings=self.settings())
        self.assertEqual([entry["chapter_id"] for entry in first["entries"]], [1, 2, 3, 4])
        sb.apply_plan("daily", job, first)
        for intent in sb.load_store("daily")["intents"]:
            if intent["chapter_id"] == "1":
                sb.mark_submitted("daily", intent["key"], {"remote_id": "r1"})
        store = sb.load_store("daily")
        # 次日重算：已排的 1–4 章不得换时刻重排，只能补 5、6 章。
        second = sb.plan(job, now=_at("2026-11-21T07:00:00"), approved=_approved(6),
                         intents=store["intents"], capability=CAP, settings=self.settings())
        self.assertEqual([entry["chapter_id"] for entry in second["entries"]], [5, 6])
        self.assertTrue(any("不重复排期" in item for item in second["blockers"]))

    def test_cancelled_intent_is_resurrected_by_replan(self):
        """取消不是墓碑：同章同版本重新进计划时必须复活，而不是永远留在 cancelled。"""
        job = _job()
        first = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(2),
                        capability=CAP, settings=self.settings())
        sb.apply_plan("daily", job, first)
        narrower = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                           capability=CAP, settings=self.settings(target_days=1))
        cancelled = sb.apply_plan("daily", job, narrower)
        self.assertEqual(cancelled["cancelled"], 1)
        wide = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(2),
                       intents=sb.load_store("daily")["intents"], capability=CAP,
                       settings=self.settings())
        revived = sb.apply_plan("daily", job, wide)
        self.assertEqual(revived["replaced"], 1)
        states = {item["chapter_id"]: item["state"] for item in sb.load_store("daily")["intents"]}
        self.assertEqual(states["2"], "planned")

    def test_new_version_of_scheduled_chapter_is_blocked(self):
        """同一章换版本时不能在平台上再排一条：先对账或取消旧意图。"""
        job = _job()
        first = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                        capability=CAP, settings=self.settings(target_days=1))
        sb.apply_plan("daily", job, first)
        changed = [{"chapter_id": 1, "version_sha256": "9" * 64, "words": 2000}]
        planned = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=changed,
                          intents=sb.load_store("daily")["intents"], capability=CAP,
                          settings=self.settings(target_days=1))
        self.assertEqual(planned["entries"], [])
        self.assertTrue(any("另一版本" in item for item in planned["blockers"]))

    def test_resolve_review_unblocks_future_writes(self):
        job = _job()
        first = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                        capability=CAP, settings=self.settings(target_days=1))
        sb.apply_plan("daily", job, first)
        key = sb.load_store("daily")["intents"][0]["key"]
        sb.mark_failed("daily", key, "提交结果未知")
        self.assertEqual(len(sb.review_items("daily")), 1)
        result = sb.resolve_review("daily", 1, "cancelled", note="作者确认平台没有该章")
        self.assertEqual(result["changed"], 1)
        self.assertEqual(sb.review_items("daily"), [])
        self.assertEqual(sb.load_store("daily")["intents"][0]["state"], "cancelled")

    def test_apply_is_idempotent_and_cancels_dropped_slots(self):
        job = _job()
        planned = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(3),
                          capability=CAP, settings=self.settings(target_days=2))
        first = sb.apply_plan("daily", job, planned)
        self.assertEqual(first["added"], 3)
        again = sb.apply_plan("daily", job, planned)
        self.assertEqual((again["added"], again["replaced"], again["cancelled"]), (0, 0, 0))
        narrower = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                           capability=CAP, settings=self.settings(target_days=1))
        third = sb.apply_plan("daily", job, narrower)
        self.assertEqual(third["added"], 0)
        self.assertEqual(third["cancelled"], 2)
        states = {item["chapter_id"]: item["state"] for item in sb.load_store("daily")["intents"]}
        self.assertEqual(states["1"], "planned")
        self.assertEqual(states["2"], "cancelled")

    def test_apply_refuses_submitted_chapter(self):
        job = _job()
        planned = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                          capability=CAP, settings=self.settings(target_days=1))
        sb.apply_plan("daily", job, planned)
        key = planned["entries"][0]["key"]
        sb.mark_submitted("daily", key, {"remote_id": "r1"})
        result = sb.apply_plan("daily", job, planned)
        self.assertEqual(result["added"], 0)
        self.assertTrue(result["blocked"])
        self.assertEqual(sb.load_store("daily")["intents"][0]["state"], "submitted")

    def test_expired_intent_can_be_replanned(self):
        job = _job()
        planned = sb.plan(job, now=_at("2026-11-20T07:00:00"), approved=_approved(1),
                          capability=CAP, settings=self.settings(target_days=1))
        sb.apply_plan("daily", job, planned)
        store = sb.load_store("daily")
        store["intents"][0]["state"] = "expired"
        sb.save_store("daily", store)
        later = sb.plan(job, now=_at("2026-11-21T07:00:00"), approved=_approved(1),
                        intents=sb.load_store("daily")["intents"], capability=CAP,
                        settings=self.settings(target_days=1))
        result = sb.apply_plan("daily", job, later)
        self.assertEqual(result["replaced"], 1)
        self.assertEqual(sb.load_store("daily")["intents"][0]["state"], "planned")

    def test_stop_keeps_remote_plan_and_resume(self):
        job = _job()
        sb.apply_plan("daily", job, sb.plan(job, now=_at("2026-11-20T07:00:00"),
                                            approved=_approved(2), capability=CAP,
                                            settings=self.settings()))
        stopped = sb.stop_replenish("daily")
        self.assertTrue(stopped["stopped"])
        self.assertEqual(stopped["remote_untouched"], 2)
        self.assertEqual(len(sb.load_store("daily")["intents"]), 2)
        resumed = sb.resume_replenish("daily")
        self.assertFalse(resumed["stopped"])

    def test_manual_change_notifies_once(self):
        job = _job()
        sb.apply_plan("daily", job, sb.plan(job, now=_at("2026-11-20T07:00:00"),
                                            approved=_approved(2), capability=CAP,
                                            settings=self.settings()))
        first = sb.note_manual_change("daily", "reschedule")
        second = sb.note_manual_change("daily", "cancel")
        self.assertTrue(first["notify"])
        self.assertFalse(second["notify"])

    def test_capability_unknown_still_previews(self):
        planned = sb.plan(_job(), now=_at("2026-11-20T07:00:00"), approved=_approved(2),
                          capability=ps.capability_for("fanqie", "acc", "潮汐钟"),
                          settings=self.settings())
        self.assertEqual(planned["status"], "ok")
        self.assertFalse(planned["auto_allowed"])
        self.assertEqual(planned["planned_count"], 2)

    def test_disabled_plan_has_no_entries(self):
        planned = sb.plan(_job(), now=_at("2026-11-20T07:00:00"), approved=_approved(2),
                          capability=CAP, settings=self.settings(enabled=False))
        self.assertEqual((planned["status"], planned["entries"]), ("disabled", []))

    def test_approved_candidates_need_receipt(self):
        receipts = {1: {"sha256": SHA[1], "word_count": "2000", "destination": "正文/1.md"},
                    2: {"sha256": "", "word_count": "0"}}
        with patch.object(writer, "reviewed_chapters", return_value=receipts):
            candidates = sb.approved_candidates(Path("/tmp/proj"))
        self.assertEqual([item["chapter_id"] for item in candidates], [1])
        self.assertEqual(candidates[0]["version_sha256"], SHA[1])


    def test_chapters_per_slot_expands_slots_and_distinguishes_capacity_gap(self):
        planned = sb.plan(
            _job(),
            now=_at("2026-11-20T07:00:00"),
            approved=_approved(4),
            capability={"capabilities": {**CAP["capabilities"], "max_chapters_per_day": 6}},
            settings=self.settings(slots=["08:00"], chapters_per_slot=2, target_days=1),
        )
        self.assertEqual([entry["planned_at"] for entry in planned["entries"]],
                         ["2026-11-20T08:00:00+08:00", "2026-11-20T08:00:00+08:00"])
        self.assertEqual(planned["coverage"]["gap_reason"], "")

        capped = sb.plan(
            _job(),
            now=_at("2026-11-20T07:00:00"),
            approved=_approved(4),
            capability={"capabilities": {**CAP["capabilities"], "max_scheduled": 2, "max_chapters_per_day": 6}},
            settings=self.settings(slots=["08:00", "12:00", "18:00"], chapters_per_slot=1, target_days=1),
        )
        self.assertEqual(capped["coverage"]["gap_reason"], "达到平台在排总量上限")


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": self.temp.name}))
        self.job = _job()
        planned = sb.plan(self.job, now=_at("2026-11-20T07:00:00"), approved=_approved(2),
                          capability=CAP, settings={"enabled": True, "target_days": 1,
                                                    "slots": ["08:00", "12:00"],
                                                    "chapters_per_slot": 1, "keep_local": 0})
        sb.apply_plan("daily", self.job, planned)
        self.entries = planned["entries"]

    def row(self, entry, **overrides):
        row = {"chapter_id": entry["chapter_id"], "book_id": "潮汐钟", "account": "acc",
               "state": "定时发布", "planned_at": entry["planned_at"],
               "content_sha256": entry["version_sha256"]}
        row.update(overrides)
        return row

    def snapshot(self, rows, complete=True):
        return ps.read_snapshot(rows, platform="fanqie", account="acc", book_id="潮汐钟",
                                complete=complete)

    def test_reconcile_requires_confirmed_capability(self):
        result = sb.reconcile("daily", self.snapshot([self.row(self.entries[0])]),
                              capability=ps.capability_for("fanqie", "acc", "潮汐钟"))
        self.assertEqual(result["status"], "capability_unknown")
        self.assertEqual(sb.load_store("daily")["intents"][0]["state"], "planned")

    def test_five_identities_verified(self):
        rows = [self.row(entry) for entry in self.entries]
        result = sb.reconcile("daily", self.snapshot(rows), capability=CAP)
        self.assertEqual(result["verified"], 2)
        states = {item["chapter_id"]: item["state"] for item in sb.load_store("daily")["intents"]}
        self.assertEqual(states["1"], "scheduled_verified")
        self.assertEqual(states["2"], "scheduled_verified")

    def test_body_identity_mismatch_goes_to_review(self):
        rows = [self.row(self.entries[0], content_sha256="f" * 64),
                self.row(self.entries[1], content_sha256="f" * 64)]
        result = sb.reconcile("daily", self.snapshot(rows), capability=CAP)
        self.assertEqual(result["verified"], 0)
        self.assertEqual(result["needs_review"], 2)

    def test_missing_body_identity_goes_to_review(self):
        rows = [self.row(self.entries[0], content_sha256=""),
                self.row(self.entries[1], content_sha256="")]
        result = sb.reconcile("daily", self.snapshot(rows), capability=CAP)
        self.assertEqual(result["verified"], 0)
        self.assertEqual(result["needs_review"], 2)

    def test_time_mismatch_goes_to_review(self):
        rows = [self.row(self.entries[0], planned_at="2026-11-21T08:00:00+08:00"),
                self.row(self.entries[1], planned_at="2026-11-21T12:00:00+08:00")]
        result = sb.reconcile("daily", self.snapshot(rows), capability=CAP)
        self.assertEqual(result["verified"], 0)
        self.assertEqual(result["needs_review"], 2)

    def test_verified_is_not_downgraded_by_missing_rows(self):
        sb.reconcile("daily", self.snapshot([self.row(entry) for entry in self.entries]),
                     capability=CAP)
        second = sb.reconcile("daily", self.snapshot([]), capability=CAP)
        self.assertEqual(second["verified"], 0)
        states = [item["state"] for item in sb.load_store("daily")["intents"]]
        self.assertEqual(states, ["scheduled_verified", "scheduled_verified"])

    def test_published_counts_as_published_not_scheduled(self):
        rows = [self.row(self.entries[0], state="已发布"),
                self.row(self.entries[1], state="草稿")]
        result = sb.reconcile("daily", self.snapshot(rows), capability=CAP)
        self.assertEqual(result["published"], 1)
        self.assertEqual(result["needs_review"], 1)

    def test_incomplete_snapshot_does_not_negate(self):
        sb.mark_submitted("daily", self.entries[0]["key"], {"remote_id": "r1"})
        result = sb.reconcile("daily", self.snapshot([], complete=False), capability=CAP)
        self.assertEqual(result["needs_review"], 0)
        self.assertGreaterEqual(result["missing"], 1)

    def test_submitted_missing_from_complete_snapshot_goes_to_review(self):
        sb.mark_submitted("daily", self.entries[0]["key"], {"remote_id": "r1"})
        result = sb.reconcile("daily", self.snapshot([]), capability=CAP)
        self.assertEqual(result["needs_review"], 1)

    def test_published_with_foreign_body_goes_to_review(self):
        """已发布也要核正文身份：别章/别版本的发布不能记到这条意图上。"""
        row = self.row(self.entries[0], state="已发布", content_sha256="f" * 64)
        result = sb.reconcile("daily", self.snapshot([row]), capability=CAP)
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["needs_review"], 1)
        self.assertIn("正文身份", sb.load_store("daily")["intents"][0]["last_error"])

    def test_published_without_body_identity_is_marked_unverified(self):
        row = self.row(self.entries[0], state="已发布", content_sha256="")
        result = sb.reconcile("daily", self.snapshot([row]), capability=CAP)
        self.assertEqual(result["published"], 1)
        remote = sb.load_store("daily")["intents"][0]["remote"]
        self.assertFalse(remote["body_verified"])
        self.assertTrue(remote["planned_at_verified"])

    def test_coverage_summary_reports_facts(self):
        sb.reconcile("daily", self.snapshot([self.row(self.entries[0])]), capability=CAP)
        summary = sb.coverage_summary("daily", self.job)
        self.assertEqual(summary["verified"], 1)
        self.assertEqual(summary["verified_until"], self.entries[0]["planned_at"])
        self.assertTrue(summary["updated_at"])


if __name__ == "__main__":
    unittest.main()
