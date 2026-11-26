"""Regression tests for the v0.7.5 backend audit fixes (P0-2/P0-3/P0-4, P1-1/2/3/5, P2-29/30)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from integration import (character_state, draft_delivery, length_policy, memory_library,
                         revision_workflow, scheduler, studio, text_checks, writer_runner)

HEADER = "# 第1章 起风\n\n"
BODY = HEADER + "林舟握紧断剑，站在山门前。他记得父亲的血债与山中的旧约。"

PASS = {"success": True, "review_decision": "pass", "needs_revision": False}
REVISE = {"success": True, "review_decision": "needs_revision", "needs_revision": True,
          "raw_review": "修正时间线"}


def make_project(root: Path) -> Path:
    project = root / "book"
    (project / ".webnovel").mkdir(parents=True)
    (project / "正文").mkdir()
    (project / "大纲").mkdir()
    return project


def write_handoff(project: Path, chapter: int = 1, body: str = BODY) -> dict:
    path = project / "正文" / f"第{chapter}章-起风.md"
    path.write_text(body, encoding="utf-8")
    digest = writer_runner.body_digest(body)
    review = {
        "success": True,
        "review_decision": "needs_human_review",
        "human_review_required": True,
        "auto_review_count": writer_runner.MAX_AUTO_REVIEWS,
        "body_sha256": digest,
        "fact_candidates": [
            {"title": "林舟：断剑", "content": "林舟持有断剑", "quote": "林舟握紧断剑，站在山门前"},
        ],
        "character_candidates": [
            {"kind": "person", "name": "林舟", "field": "goal", "value": "为父复仇",
             "quote": "父亲的血债"},
        ],
    }
    receipt = {
        "destination": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "review": review,
        "revision_rounds": 0,
        "reviewed_at": "2026-11-26T00:00:00+08:00",
    }
    receipts_path = project / ".webnovel" / "writer_receipts.json"
    receipts_path.write_text(json.dumps({str(chapter): receipt}, ensure_ascii=False),
                             encoding="utf-8")
    return receipt


class HandoffIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))
        self.receipt = write_handoff(self.project)

    def test_handoff_candidates_stay_pending_and_commit_after_approval(self):
        """P0-3: unapproved candidates never enter shared memory or character profiles."""
        review = self.receipt["review"]
        result = writer_runner._commit_review_candidates(
            self.project, 1, BODY, review, _writer_locked=True)
        self.assertEqual(result["memory_library"]["committed"], "pending_review")
        self.assertEqual(result["memory_library"]["added"], 0)
        self.assertEqual(result["character_state"]["committed"], "pending_review")
        self.assertEqual(result["character_state"]["added"], 0)
        self.assertEqual(memory_library.read(self.project)["items"], [])
        self.assertEqual(character_state.read(self.project)["persons"], {})
        candidate_files = list(memory_library._path(self.project.resolve(), "fact_candidates").glob("*.json"))
        self.assertEqual(len(candidate_files), 1)
        memory_doc = json.loads(candidate_files[0].read_text("utf-8"))
        self.assertEqual(memory_doc["state"], "pending")

        executor = Mock()
        receipts_path = self.project / ".webnovel" / "writer_receipts.json"
        receipts = {**json.loads(receipts_path.read_text("utf-8"))}
        post = asyncio.run(writer_runner._sync_committed_artifacts(
            executor, 1, BODY, receipts["1"], receipts, receipts_path))
        self.assertEqual(post["shared_memory"]["status"], "pending_review")
        self.assertFalse(executor._extract_chapter_entities.called)
        self.assertTrue(draft_delivery._metadata_complete(receipts["1"]))

        with self.assertRaises(ValueError):
            writer_runner.approve_chapter_review(
                self.project, 1, expected_sha256="0" * 64)
        approved = writer_runner.approve_chapter_review(
            self.project, 1, note="看过了", expected_sha256=self.receipt["sha256"])
        self.assertEqual(approved["review_decision"], "human_approved")
        titles = [item["title"] for item in memory_library.read(self.project)["items"]]
        self.assertIn("林舟：断剑", titles)
        person = character_state.read(self.project)["persons"]
        self.assertTrue(person)
        self.assertEqual(next(iter(person.values()))["profile"]["goal"], "为父复仇")
        self.assertIn(1, writer_runner.reviewed_chapters(self.project))

    def test_existing_handoff_chapter_recovers_without_file_exists(self):
        """P1-3: crash-window recovery must report needs_human_review, not FileExistsError."""
        with patch.object(writer_runner, "_load_webnovel_services",
                          side_effect=AssertionError("不得调用 AI")):
            result = writer_runner.generate_chapter(self.project, chapter_id=1)
        self.assertEqual(result["status"], "needs_human_review")
        self.assertTrue(result["recovered"])
        self.assertEqual(result["review"]["review_decision"], "needs_human_review")

    def test_final_review_does_not_overwrite_pending_handoff(self):
        """P1-27: review-existing must refuse to clobber a pending human handoff."""
        with patch.object(writer_runner, "_load_webnovel_services",
                          side_effect=AssertionError("不得调用 AI")):
            with self.assertRaises(ValueError) as caught:
                writer_runner.review_existing_chapter(self.project, 1)
        self.assertIn("人工复核", str(caught.exception))
        receipt = json.loads((self.project / ".webnovel" / "writer_receipts.json").read_text("utf-8"))["1"]
        self.assertEqual(receipt["review"]["review_decision"], "needs_human_review")

    def test_sync_chapter_and_rebuild_skip_handoff(self):
        """P1-5/P2-30: handoff bodies are skipped, not retried as failed memory."""
        with patch.object(memory_library.roles, "json_call", AsyncMock(side_effect=AssertionError("不得调用模型"))):
            synced = asyncio.run(memory_library.sync_chapter(self.project, 1, BODY))
            rebuilt = memory_library.rebuild(self.project)
        self.assertEqual(synced["status"], "skipped_pending_review")
        self.assertEqual(rebuilt["processed"], 0)
        self.assertEqual(memory_library.read(self.project)["items"], [])


class SchedulingGateTests(unittest.TestCase):
    def test_scheduled_blocks_only_when_a_later_chapter_was_reviewed(self):
        """P0-4: a pending handoff must stop scheduling any later reviewed chapter."""
        project = Path("/tmp/project")  # patched below; path content is irrelevant
        with (
            patch.object(writer_runner, "reviewed_chapters", return_value={1: {}, 3: {}}),
            patch.object(writer_runner, "committed_chapters", return_value={1: {}, 2: {}, 3: {}}),
            patch.object(writer_runner, "existing_chapter_ids", return_value={1, 2, 3}),
        ):
            message = scheduler.scheduled_human_pending_block(project)
        self.assertIn("第 [2] 章待人工复核", message)
        self.assertIn("3", message)
        with (
            patch.object(writer_runner, "reviewed_chapters", return_value={1: {}}),
            patch.object(writer_runner, "committed_chapters", return_value={1: {}, 2: {}}),
            patch.object(writer_runner, "existing_chapter_ids", return_value={1, 2}),
        ):
            self.assertIsNone(scheduler.scheduled_human_pending_block(project))

    def test_publish_targets_before_handoff_are_not_blocked(self):
        """P1-4: earlier passed chapters may publish; only targets at/after handoff wait."""
        self.assertEqual(scheduler.targets_blocked_by_pending([2], [1]), [])
        self.assertEqual(scheduler.targets_blocked_by_pending([2], [2, 3]), [2, 3])
        self.assertEqual(scheduler.targets_blocked_by_pending([], [1, 2]), [])
        self.assertEqual(scheduler.split_targets_by_pending([2], [1, 2, 3]), ([1], [2, 3]))


class ReviewBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))
        self.state = self.project / ".webnovel" / "state.json"
        self.state.write_text(json.dumps({"progress": {"current_chapter": 0}}), encoding="utf-8")
        (self.project / "大纲" / "卷一.md").write_text(
            "## 第1章 起风\n故事梗概。", encoding="utf-8")
        patcher = patch.dict(os.environ, {"NOVEL_HELPER_AI_CONFIG": str(self.project / "offline-ai.json"),
                                          "AI_API_KEY": "", "AI_MODEL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _executor(self, reviews, polish, stream_review=None):
        async def stream(events):
            for event in events:
                yield json.dumps(event, ensure_ascii=False)

        executor = Mock()
        executor.execute_write_stream.side_effect = lambda *a, **k: stream([
            {"type": "content", "chunk": "初稿"},
            {"type": "review", "result": dict(stream_review or PASS)},
            {"type": "done", "success": True},
        ])
        executor.execute_polish = AsyncMock(side_effect=polish)
        executor.execute_review = AsyncMock(side_effect=reviews)
        loader = patch.object(writer_runner, "_load_webnovel_services",
                              return_value=(Mock(return_value=executor), lambda: object()))
        loader.start()
        self.addCleanup(loader.stop)
        return executor

    def test_cap_blocks_third_review_after_length_and_count_fixes(self):
        """P1-1: after two reviews, further length/count changes hand off without D."""
        long_body = "长" * 80
        executor = self._executor(
            [dict(PASS)],
            [{"success": True, "content": long_body},
             {"success": True, "content": long_body + "改"}],
        )
        with (
            patch.object(length_policy, "minimum", return_value=50),
            patch.object(length_policy, "body_chars",
                         side_effect=lambda text, chapter: len(re.sub(r"\s+", "", text))),
            patch.object(text_checks, "issues", return_value=["程序发现计数错误"]),
            patch.object(text_checks, "require", return_value=None),
        ):
            result = asyncio.run(writer_runner._generate_and_review(self.project, 1, 100, 2))
        self.assertEqual(executor.execute_review.await_count, 1)
        self.assertEqual(executor.execute_polish.await_count, 2)
        self.assertEqual(result["review"]["review_decision"], "needs_human_review")
        self.assertTrue(result["review"]["human_review_required"])
        self.assertEqual(result["review"]["auto_review_count"], writer_runner.MAX_AUTO_REVIEWS)

    def test_zero_revision_budget_hands_off_instead_of_raising(self):
        """P1-2: max_revisions=0 must hand off, not raise RuntimeError."""
        executor = self._executor([dict(REVISE)], [], stream_review=REVISE)
        result = asyncio.run(writer_runner._generate_and_review(self.project, 1, 100, 0))
        self.assertEqual(result["review"]["review_decision"], "needs_human_review")
        self.assertTrue(result["human_review_required"])
        self.assertEqual(executor.execute_polish.await_count, 0)
        self.assertEqual(executor.execute_review.await_count, 0)


class BatchAndPolishHelpersTests(unittest.TestCase):
    def test_non_preview_polish_at_cap_returns_handoff(self):
        """P1-26: polish_existing must not raise ValueError when the review cap is hit."""
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            content = "原文正文，用于润色检查。"
            contract = "contract-hash"
            source_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            identity = {"chapter": 1, "source_sha256": source_sha,
                        "contract": contract, "min_words": 0}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
            path = project / ".webnovel" / "draft_checkpoints" / f"revision-1-{key}.json"
            path.parent.mkdir(parents=True)
            review = {"success": True, "review_decision": "needs_revision", "needs_revision": True}
            path.write_text(json.dumps({
                **identity, "polished": content, "review": review,
                "review_body_sha256": writer_runner.body_digest(content),
                "auto_review_count": writer_runner.MAX_AUTO_REVIEWS,
                "revision_attempts": 0, "reviews": [],
            }, ensure_ascii=False), encoding="utf-8")
            executor = Mock()
            rewritten, handoff = asyncio.run(revision_workflow.revise(
                project, 1, content, source_sha, contract, executor, {}, 0, meta=None))
        self.assertEqual(rewritten, content)
        self.assertEqual(handoff["review_decision"], "needs_human_review")
        self.assertTrue(handoff["human_review_required"])
        self.assertEqual(handoff["auto_review_count"], writer_runner.MAX_AUTO_REVIEWS)

    def test_batch_completed_is_intersected_with_existing_bodies(self):
        """P2-29: a completed chapter whose body vanished must be regenerated, not skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            (project / "正文" / "第2章-留存.md").write_text("正文", encoding="utf-8")
            completed, missing = studio._completed_with_bodies(project, {"completed": [1, 2]})
        self.assertEqual(completed, [2])
        self.assertEqual(missing, [1])


if __name__ == "__main__":
    unittest.main()
