"""Audit B workstream regressions (2026-11-26 v0.7.5).

Covers P1-C (scheduling must not skip unreviewed/duplicate/edited/needs_revision
chapters), P2-6 (polish writes the body before candidate files), P2-7
(skipped_pending is visible in run reports), P2-8 (0-byte bodies are missing),
P3-2 (expired intent superseded by a new version) and P2-9 (PUT cannot create a
second job with the same project + publication mode).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND = Path(__file__).resolve().parents[1]
import sys

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from integration import (bridge, character_state, memory_library, platform_adapters,
                         platform_schedule as ps, run_report, schedule_buffer as sb,
                         scheduled_delivery as sd, scheduler, studio, writer_runner)

PLATFORM, ACCOUNT, BOOK = "fanqie", "acc", "潮汐钟"


# ---- fixtures ---------------------------------------------------------------

def make_project(root: Path) -> Path:
    project = root / "book"
    (project / ".webnovel").mkdir(parents=True)
    (project / "正文").mkdir()
    (project / "大纲").mkdir()
    return project


def body_text(chapter: int) -> str:
    return f"# 第{chapter}章 测试\n\n这是第{chapter}章的正文，包含足够的内容用于审查回执绑定。"


def chapter_path(project: Path, chapter: int, suffix: str = "") -> Path:
    return project / "正文" / f"第{chapter}章-测试{suffix}.md"


def write_receipt(project: Path, chapter: int, path: Path, review: dict) -> dict:
    receipt = {
        "destination": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "review": review,
        "creative_contract_hash": "",
        "reviewed_at": "2026-11-26T00:00:00+08:00",
    }
    receipts_path = project / ".webnovel" / "writer_receipts.json"
    data = json.loads(receipts_path.read_text("utf-8")) if receipts_path.is_file() else {}
    data[str(chapter)] = receipt
    receipts_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return receipt


def write_chapter(project: Path, chapter: int, *, receipt: str | None = "approved",
                  suffix: str = "", body: str | None = None) -> Path:
    path = chapter_path(project, chapter, suffix)
    text = body_text(chapter) if body is None else body
    path.write_text(text, encoding="utf-8")
    if receipt is None:
        return path
    digest = writer_runner.body_digest(text)
    if receipt == "needs_revision":
        review = {"success": True, "review_decision": "needs_revision", "needs_revision": True}
    elif receipt == "handoff":
        review = {"success": True, "review_decision": "needs_human_review",
                  "human_review_required": True, "auto_review_count": 2,
                  "body_sha256": digest}
    else:
        review = {"success": True, "review_decision": "human_approved",
                  "human_review_approved": True, "needs_revision": False,
                  "body_sha256": digest}
    write_receipt(project, chapter, path, review)
    return path


def capability() -> dict:
    return {"platform": PLATFORM, "account": ACCOUNT, "book_id": BOOK,
            "observed_at": "2026-11-26T00:00:00+08:00", "source": "author_confirmed",
            "capabilities": {"can_read_schedule": True, "can_schedule": True,
                             "can_confirm_schedule": True, "can_confirm_body": True,
                             "lead_time_minutes": 0, "max_scheduled": 10,
                             "max_chapters_per_day": 6}}


def scheduled_job(project: Path, **overrides) -> dict:
    job = {"name": "日更", "project": str(project), "book": BOOK, "account": ACCOUNT,
           "platform": PLATFORM, "publication_mode": "platform_scheduled",
           "timezone": "Asia/Shanghai", "daily_time": "08:00", "daily_times": [],
           "chapters_per_run": 1, "word_count": 1000, "max_revisions": 1,
           "approval_mode": "unattended", "enabled": True,
           "schedule_buffer": {"enabled": True, "target_days": 2,
                               "slots": ["08:00", "12:00"],
                               "chapters_per_slot": 1, "keep_local": 0,
                               "stop_after_gap": True}}
    job.update(overrides)
    return job


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def submit_scheduled(self, job, intent, chapter_path):
        self.calls.append((str(intent["chapter_id"]), chapter_path))
        return {"scheduled": True, "remote_id": f"r-{intent['chapter_id']}",
                "planned_at": intent["planned_at"], "chapter_id": intent["chapter_id"],
                "book_id": BOOK, "account": ACCOUNT}

    def read_schedule(self, platform, account, book_id):
        return []


# ---- P1-C: real step -> approved_candidates -> plan -> apply_plan -> submit ---

class ScheduledBlockingChainTests(unittest.TestCase):
    """Each scenario runs the real scheduled_delivery.step chain end to end."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-schedule-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.root / "data")}))
        self.enterContext(patch.object(sd.draft_delivery, "step", side_effect=self._fake_generate))
        self.enterContext(patch.object(sd.s, "_update_run"))
        self.published: list[int] = []
        self.enterContext(patch.object(sd.s, "_published_ids",
                                      side_effect=lambda book, account=None: list(self.published)))
        platform_adapters.clear()
        self.addCleanup(platform_adapters.clear)
        self.adapter = FakeAdapter()
        platform_adapters.register(PLATFORM, self.adapter)
        ps.record_capability(capability())
        self.job = scheduled_job(self.project)

    @staticmethod
    def _fake_generate(job_id, job_doc, cycle, quota, record, force, **kwargs):
        cycle["remote_state"] = "not_attempted"
        return {"status": "success", "job_id": job_id, "record": record, **kwargs}

    def run_step(self):
        cycle = {"status": "running"}
        result = sd.step("daily", self.job, cycle, {}, {"job_id": "daily"}, False)
        return result, cycle

    def assert_no_schedule(self):
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(sb.load_store("daily")["intents"], [])

    def test_a_unreviewed_first_chapter_blocks_later_reviewed(self):
        write_chapter(self.project, 1, receipt=None)
        for chapter in (2, 3, 4):
            write_chapter(self.project, chapter)
        self.assertEqual(sb.approved_candidates(self.project), [])
        result, _ = self.run_step()
        self.assertEqual(result["schedule"]["planned_count"], 0)
        self.assertEqual(result["schedule"]["submitted"], 0)
        self.assert_no_schedule()

    def test_b_duplicate_chapter_number_blocks_later_reviewed(self):
        write_chapter(self.project, 2, suffix="-甲")
        write_chapter(self.project, 2, suffix="-乙")
        for chapter in (3, 4):
            write_chapter(self.project, chapter)
        self.assertEqual(sb.approved_candidates(self.project), [])
        result, _ = self.run_step()
        self.assertEqual(result["schedule"]["planned_count"], 0)
        self.assert_no_schedule()

    def test_c_edited_handoff_invalidates_receipt_and_blocks(self):
        write_chapter(self.project, 1)
        path = write_chapter(self.project, 2, receipt="handoff")
        for chapter in (3, 4):
            write_chapter(self.project, chapter)
        # The author edits the handoff body: its receipt no longer binds.
        path.write_text(body_text(2) + "\n作者改稿后的新句子。\n", encoding="utf-8")
        approved = sb.approved_candidates(self.project)
        self.assertEqual([item["chapter_id"] for item in approved], [1])
        result, _ = self.run_step()
        self.assertEqual([call[0] for call in self.adapter.calls], ["1"])
        self.assertEqual(result["schedule"]["submitted"], 1)

    def test_d_needs_revision_chapter_blocks_later_reviewed(self):
        write_chapter(self.project, 1)
        write_chapter(self.project, 2, receipt="needs_revision")
        for chapter in (3, 4):
            write_chapter(self.project, chapter)
        approved = sb.approved_candidates(self.project)
        self.assertEqual([item["chapter_id"] for item in approved], [1])
        result, _ = self.run_step()
        self.assertEqual([call[0] for call in self.adapter.calls], ["1"])
        self.assertEqual(result["schedule"]["submitted"], 1)

    def test_e_published_chapter_without_receipt_does_not_block(self):
        write_chapter(self.project, 1, receipt=None)
        for chapter in (2, 3):
            write_chapter(self.project, chapter)
        self.published = [1]
        approved = sb.approved_candidates(self.project, published=self.published)
        self.assertEqual([item["chapter_id"] for item in approved], [2, 3])
        result, _ = self.run_step()
        self.assertEqual([call[0] for call in self.adapter.calls], ["2", "3"])
        self.assertEqual(result["schedule"]["submitted"], 2)

    def test_submit_planned_stops_when_earlier_body_lost_its_receipt(self):
        # Intents can already exist from an earlier round; a chapter that loses
        # its receipt afterwards must still stop submit, not silently skip.
        write_chapter(self.project, 1, receipt=None)
        for chapter in (2, 3):
            write_chapter(self.project, chapter)
        store = sb.load_store("daily")
        for chapter, sha in ((2, self._sha(2)), (3, self._sha(3))):
            planned_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds")
            store["intents"].append({
                "key": ps.schedule_intent_key("daily", PLATFORM, ACCOUNT, BOOK, chapter, sha),
                "job_id": "daily", "platform": PLATFORM, "account": ACCOUNT, "book_id": BOOK,
                "chapter_id": str(chapter), "version_sha256": sha, "planned_at": planned_at,
                "state": "planned", "attempts": 0, "submitted_at": "", "remote": {},
                "last_error": "", "created_at": planned_at,
            })
        sb.save_store("daily", store)
        stats = sd._submit_planned("daily", self.job, capability(), sb.load_store("daily"))
        self.assertEqual(stats["submitted"], 0)
        self.assertIn("缺少有效审查记录", stats["blocked"])
        self.assertEqual(self.adapter.calls, [])
        states = {item["chapter_id"]: item["state"] for item in sb.load_store("daily")["intents"]}
        self.assertEqual(states, {"2": "planned", "3": "planned"})

    def _sha(self, chapter: int) -> str:
        receipt = writer_runner.reviewed_chapters(self.project)[chapter]
        return str(receipt["sha256"])


class SchedulerBlockingGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-gate-")
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))

    def test_unreviewed_chapter_counts_as_blocking_not_only_handoff(self):
        write_chapter(self.project, 1, receipt=None)
        for chapter in (2, 3):
            write_chapter(self.project, chapter)
        self.assertEqual(scheduler.human_pending_chapters(self.project), [1])
        message = scheduler.scheduled_human_pending_block(self.project)
        self.assertIsNotNone(message)
        self.assertIn("第 [1] 章待人工复核", message)
        self.assertIn("3", message)

    def test_published_chapter_is_not_blocking(self):
        write_chapter(self.project, 1, receipt=None)
        for chapter in (2, 3):
            write_chapter(self.project, chapter)
        self.assertEqual(scheduler.human_pending_chapters(self.project, [1]), [])
        self.assertIsNone(scheduler.scheduled_human_pending_block(self.project, [1]))


# ---- P2-6: polish writes the body before candidates --------------------------

class _DummyExecutor:
    def __init__(self, project, ai):
        self.project = project
        self.ai_service = ai
        self.polish_token_budget = 0


class PolishHandoffOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-polish-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.root / "data")}))
        self.enterContext(patch.object(studio.bridge, "load_manifest", return_value={}))
        self.enterContext(patch.object(studio.roles, "load_config", return_value={}))
        self.enterContext(patch.object(studio.roles, "enabled", return_value=False))
        self.enterContext(patch.object(writer_runner, "_load_webnovel_services",
                                      return_value=(_DummyExecutor, lambda: object())))

    def test_handoff_polish_keeps_pending_candidates_and_approve_commits(self):
        old = body_text(1) + "\n旧稿句子。\n"
        rewritten = (body_text(1) + "\n林舟握紧断剑，站在山门前。风雪更大了。"
                     "他记起父亲的血债。\n")
        source = write_chapter(self.project, 1, receipt=None, body=old)
        review = {
            "success": True, "review_decision": "needs_human_review",
            "human_review_required": True, "auto_review_count": 2,
            "body_sha256": writer_runner.body_digest(rewritten),
            "fact_candidates": [
                {"title": "林舟：断剑", "content": "林舟持有断剑",
                 "quote": "林舟握紧断剑，站在山门前"},
            ],
            "character_candidates": [
                {"kind": "person", "name": "林舟", "field": "goal", "value": "为父复仇",
                 "quote": "他记起父亲的血债"},
            ],
        }
        with patch("integration.revision_workflow.revise", new=AsyncMock(return_value=(rewritten, review))):
            result = studio.polish_existing(self.project, 1, min_words=1)
        self.assertEqual(result["status"], "polished")
        self.assertEqual(source.read_text(encoding="utf-8"), rewritten)

        receipts = json.loads((self.project / ".webnovel" / "writer_receipts.json")
                              .read_text("utf-8"))
        candidates = receipts["1"]["candidates"]
        self.assertEqual(candidates["memory_library"]["committed"], "pending_review")
        self.assertNotEqual(candidates["memory_library"].get("status"), "failed")
        self.assertEqual(candidates["character_state"]["committed"], "pending_review")
        self.assertNotEqual(candidates["character_state"].get("status"), "failed")

        fact_files = list(memory_library._path(self.project.resolve(), "fact_candidates").glob("*.json"))
        self.assertEqual(len(fact_files), 1)
        self.assertEqual(json.loads(fact_files[0].read_text("utf-8"))["state"], "pending")
        character_files = list((self.project / ".webnovel" / "character_candidates").glob("*.json"))
        self.assertEqual(len(character_files), 1)
        self.assertEqual(json.loads(character_files[0].read_text("utf-8"))["state"], "pending")

        approved = writer_runner.approve_chapter_review(self.project, 1)
        self.assertEqual(approved["review_decision"], "human_approved")
        titles = [item["title"] for item in memory_library.read(self.project)["items"]]
        self.assertIn("林舟：断剑", titles)
        self.assertTrue(character_state.read(self.project)["persons"])


# ---- P2-8: 0-byte bodies are missing, and batch regenerates them -------------

class EmptyBodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-empty-")
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))

    def test_zero_byte_and_whitespace_bodies_are_missing(self):
        chapter_path(self.project, 1).write_text("", encoding="utf-8")
        chapter_path(self.project, 2).write_text("# 第2章 正文\n\n有内容。\n", encoding="utf-8")
        chapter_path(self.project, 3).write_text(" \n\t\n", encoding="utf-8")
        completed, missing = studio._completed_with_bodies(
            self.project, {"completed": [1, 2, 3]})
        self.assertEqual(completed, [2])
        self.assertEqual(missing, [1, 3])

    def test_batch_regenerates_empty_body_without_file_exists(self):
        identity = "a" * 32
        empty = chapter_path(self.project, 1)
        empty.write_text("", encoding="utf-8")
        chapter_path(self.project, 2).write_text(body_text(2), encoding="utf-8")
        batches = self.project / ".webnovel" / "batches"
        batches.mkdir(parents=True)
        (batches / f"{identity}.json").write_text(json.dumps({
            "id": identity, "targets": [1, 2], "word_count": 1000,
            "max_revisions": 1, "scenes": 0, "status": "running",
            "completed": [1, 2], "created_at": "2026-11-26T00:00:00+08:00",
        }, ensure_ascii=False), encoding="utf-8")

        generated = []

        async def fake_generate(project, word_count, max_revisions, chapter, dry_run, scenes=0):
            generated.append(chapter)
            target = chapter_path(project, chapter, "-重生")
            target.write_text(body_text(chapter), encoding="utf-8")
            return {"status": "generated", "chapter_id": chapter, "destination": str(target)}

        with patch.object(writer_runner, "_generate_chapter_locked", new=fake_generate):
            result = studio.batch(self.project, 2, 1000, 1, identity)

        self.assertEqual(generated, [1])
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["recovered_missing_bodies"], [1])
        self.assertEqual(len(result["quarantined_empty_bodies"]), 1)
        self.assertTrue(chapter_path(self.project, 1, "-重生").read_text("utf-8").strip())
        self.assertTrue(Path(result["quarantined_empty_bodies"][0]).is_file())

    def test_batch_quarantines_empty_target_missing_from_completed(self):
        identity = "b" * 32
        chapter_path(self.project, 1).write_text("", encoding="utf-8")
        chapter_path(self.project, 2).write_text(body_text(2), encoding="utf-8")
        batches = self.project / ".webnovel" / "batches"
        batches.mkdir(parents=True)
        (batches / f"{identity}.json").write_text(json.dumps({
            "id": identity, "targets": [1, 2], "word_count": 1000,
            "max_revisions": 1, "scenes": 0, "status": "running",
            "completed": [2], "created_at": "2026-11-26T00:00:00+08:00",
        }, ensure_ascii=False), encoding="utf-8")

        async def fake_generate(project, word_count, max_revisions, chapter, dry_run, scenes=0):
            target = chapter_path(project, chapter, "-重生")
            target.write_text(body_text(chapter), encoding="utf-8")
            return {"status": "generated", "chapter_id": chapter, "destination": str(target)}

        with patch.object(writer_runner, "_generate_chapter_locked", new=fake_generate):
            result = studio.batch(self.project, 2, 1000, 1, identity)
        self.assertEqual(result["completed"], [2, 1])
        self.assertEqual(len(result["quarantined_empty_bodies"]), 1)
        self.assertTrue(chapter_path(self.project, 1, "-重生").read_text("utf-8").strip())


# ---- P2-7: skipped_pending is visible in the run report ----------------------

class RunReportSkippedPendingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-report-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)
        self.enterContext(patch.dict(os.environ, {
            "NOVEL_HELPER_DATA": str(self.root / "data"),
            "NOVEL_HELPER_COST_DB": str(self.root / "no-costs.sqlite3"),
        }))
        self.runs = self.root / "runs"
        self.enterContext(patch.object(run_report.scheduler, "RUNS_ROOT", self.runs))
        for chapter in (1, 2, 3):
            chapter_path(self.project, chapter).write_text(body_text(chapter), encoding="utf-8")
        self.run_id = "20261126T080000-deadbeef"
        folder = self.runs / bridge.safe_dir_name("daily")
        folder.mkdir(parents=True)
        record = {
            "job_id": "daily", "project": str(self.project), "book": BOOK,
            "publication_mode": "draft_only", "status": "success",
            "started_at": "2026-11-26T08:00:00+08:00",
            "finished_at": "2026-11-26T08:01:00+08:00",
            "target_ids": [1, 3], "skipped_pending": [2],
            "cycle": {"target_ids": [1, 3], "skipped_pending": [2]},
        }
        (folder / f"{self.run_id}.json").write_text(json.dumps(record, ensure_ascii=False),
                                                   encoding="utf-8")
        self.job = {"name": "日更", "project": str(self.project), "book": BOOK,
                    "timezone": "Asia/Shanghai"}

    def test_skipped_pending_chapter_is_reported_and_decision_is_manual(self):
        report = run_report.project_run("daily", self.job, self.run_id)
        self.assertEqual(report["skipped_pending"], [2])
        row = next(item for item in report["chapters"] if item["chapter_id"] == 2)
        self.assertEqual(row["state"], "skipped_pending_review")
        self.assertTrue(row["body_saved"])
        self.assertEqual(report["tally"]["skipped_pending"], 1)
        self.assertIn(2, [item["chapter_id"] for item in report["chapters"]])
        self.assertEqual(report["decision"], "manual")
        self.assertIn("第2章待人工复核", report["decision_reason"])


# ---- P3-2: expired intent is superseded by a new version ---------------------

class ExpiredIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-intent-")
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_DATA": str(self.temp.name)}))
        self.job = {"job_id": "daily", "platform": PLATFORM, "account": ACCOUNT, "book": BOOK}

    def test_new_version_supersedes_expired_intent(self):
        old_key = ps.schedule_intent_key("daily", PLATFORM, ACCOUNT, BOOK, 2, "a" * 64)
        new_key = ps.schedule_intent_key("daily", PLATFORM, ACCOUNT, BOOK, 2, "b" * 64)
        store = sb.load_store("daily")
        store["intents"].append({
            "key": old_key, "job_id": "daily", "platform": PLATFORM, "account": ACCOUNT,
            "book_id": BOOK, "chapter_id": "2", "version_sha256": "a" * 64,
            "planned_at": "2026-11-25T08:00:00+08:00", "state": "expired",
            "attempts": 1, "submitted_at": "", "remote": {}, "last_error": "计划时刻已过",
            "created_at": "2026-11-25T00:00:00+08:00",
        })
        sb.save_store("daily", store)
        planned = {"entries": [{
            "chapter_id": 2, "version_sha256": "b" * 64,
            "planned_at": "2026-11-27T08:00:00+08:00", "key": new_key,
        }]}
        result = sb.apply_plan("daily", self.job, planned)
        self.assertEqual(result["superseded"], 1)
        states = {item["key"]: item["state"] for item in sb.load_store("daily")["intents"]}
        self.assertEqual(states[old_key], "superseded")
        self.assertEqual(states[new_key], "planned")
        self.assertNotIn("expired", states.values())


# ---- P2-9: PUT cannot duplicate project + publication mode -------------------

def scheduler_job(project: Path, book: str, mode: str) -> dict:
    return {
        "name": f"{book} 任务", "project": str(project), "book": book, "account": ACCOUNT,
        "platform": PLATFORM, "publication_mode": mode, "daily_time": "08:00",
        "daily_times": [], "timezone": "Asia/Shanghai", "chapters_per_run": 1,
        "word_count": 1000, "max_revisions": 1, "approval_mode": "unattended",
        "enabled": True, "created_at": "2026-11-01T00:00:00+08:00",
    }


class UpdateJobDuplicateModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-b-jobs-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)
        self.path = self.root / "scheduler.json"
        self.enterContext(patch.object(scheduler, "SCHEDULER_PATH", self.path))
        self.enterContext(patch.object(scheduler, "RUNS_ROOT", self.root / "runs"))
        account_file = self.root / "account.json"
        account_file.write_text("{}", encoding="utf-8")
        self.enterContext(patch.object(scheduler.bridge, "account_state_path",
                                      return_value=account_file))
        self.path.write_text(json.dumps({
            "version": 2, "settings": {"auto_schedule": True},
            "jobs": {"live": scheduler_job(self.project, "书甲", "publish_now"),
                     "draft": scheduler_job(self.project, "书乙", "draft_only")},
        }, ensure_ascii=False), encoding="utf-8")

    def test_put_changing_mode_to_existing_mode_is_rejected_and_unchanged(self):
        with self.assertRaises(ValueError) as caught:
            scheduler.update_job("draft", {"publication_mode": "publish_now"})
        self.assertIn("相同发布方式", str(caught.exception))
        # The manager maps FileExistsError to HTTP 409; keep that contract.
        self.assertIsInstance(caught.exception, FileExistsError)
        saved = json.loads(self.path.read_text("utf-8"))["jobs"]["draft"]
        self.assertEqual(saved["publication_mode"], "draft_only")

    def test_put_that_keeps_unique_mode_still_works(self):
        result = scheduler.update_job("draft", {"name": "改名"})
        self.assertEqual(result["name"], "改名")
        saved = json.loads(self.path.read_text("utf-8"))["jobs"]["draft"]
        self.assertEqual(saved["publication_mode"], "draft_only")


if __name__ == "__main__":
    unittest.main()
