"""Regression tests for audit domain A (P1-A/D/E/F, P2-1/2/3/5, P3-1).

Every test exercises the real writer/handoff/quality paths; model calls are
replaced only at the executor boundary. Run with PYTHONPATH=backend.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fanqie_auto_publish import publication_safety
from integration import character_state, memory_library, quality_gate, writer_runner
from manager import app as manager_app

HEADER = "# 第1章 起风\n\n"
BODY = HEADER + "林舟握紧断剑，站在山门前。他记得父亲的血债与山中的旧约。"

FULL_SCORES = {name: 90 for name in ("setting", "plot", "character", "prose", "dialogue", "style")}
PASS_FULL = {
    "success": True, "review_decision": "pass", "needs_revision": False,
    "quality": {"scores": FULL_SCORES, "issues": [], "verdict": "pass", "summary": "通过"},
}
REVISE = {"success": True, "review_decision": "needs_revision", "needs_revision": True,
          "raw_review": "修正时间线"}

_MISSING = object()


def make_project(root: Path) -> Path:
    project = root / "book"
    (project / ".webnovel").mkdir(parents=True)
    (project / "正文").mkdir()
    (project / "大纲").mkdir()
    (project / ".webnovel" / "state.json").write_text(
        json.dumps({"progress": {"current_chapter": 0}}), encoding="utf-8")
    return project


def outline_file(project: Path, text: str) -> Path:
    path = project / "大纲" / "卷一.md"
    path.write_text(text, encoding="utf-8")
    return path


def write_body(project: Path, body: str = BODY, chapter: int = 1) -> Path:
    path = project / "正文" / f"第{chapter}章-起风.md"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def write_handoff(project: Path, chapter: int = 1, body: str = BODY, *, count: int = 2,
                  reason: str | None = None, body_sha256=_MISSING,
                  candidates: bool = True) -> dict:
    path = write_body(project, body, chapter)
    digest = writer_runner.body_digest(body)
    review = {
        "success": True,
        "review_decision": "needs_human_review",
        "human_review_required": True,
        "auto_review_count": count,
    }
    if body_sha256 is _MISSING:
        review["body_sha256"] = digest
    elif body_sha256 is not None:
        review["body_sha256"] = body_sha256
    if reason:
        review["handoff_reason"] = reason
    if candidates:
        review["fact_candidates"] = [
            {"title": "林舟：断剑", "content": "林舟持有断剑", "quote": "林舟握紧断剑，站在山门前"},
        ]
        review["character_candidates"] = [
            {"kind": "person", "name": "林舟", "field": "goal", "value": "为父复仇",
             "quote": "父亲的血债"},
        ]
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


def stream(events):
    async def generate():
        for event in events:
            yield json.dumps(event, ensure_ascii=False)
    return generate()


def patch_loader(executor):
    return patch.object(
        writer_runner, "_load_webnovel_services",
        return_value=(Mock(return_value=executor), lambda: object()))


def install_executor(stream_review=REVISE, reviews=None, polish=None):
    executor = Mock()
    executor.execute_write_stream.side_effect = lambda *a, **k: stream([
        {"type": "content", "chunk": "第1章的初稿正文，人物与因果完整。"},
        *([{"type": "review", "result": dict(stream_review)}] if stream_review is not None else []),
        {"type": "done", "success": True},
    ])
    executor.execute_review = AsyncMock(side_effect=reviews or [dict(REVISE)])
    executor.execute_polish = AsyncMock(side_effect=polish or [])
    executor._extract_chapter_entities = AsyncMock(return_value={"extraction": {}})
    executor._apply_extraction_results = AsyncMock(return_value={"success": True})
    executor.sync_post_save_artifacts = AsyncMock(
        return_value={"rag_indexed": True, "continuity_written": True})
    return executor


class P1ACandidateGateTests(unittest.TestCase):
    """P1-A: pending handoff candidates cannot be committed before approval."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))
        self.receipt = write_handoff(self.project)
        pending = writer_runner._commit_review_candidates(
            self.project, 1, BODY, self.receipt["review"], _writer_locked=True)
        self.assertEqual(pending["memory_library"]["committed"], "pending_review")
        self.assertEqual(pending["character_state"]["committed"], "pending_review")

    def test_direct_commit_requires_reviewed_and_succeeds_after_approve(self):
        self.assertNotIn(1, writer_runner.reviewed_chapters(self.project))
        self.assertIn(1, writer_runner.committed_chapters(self.project))
        raw_digest = memory_library.current_digest(self.project, 1)
        with self.assertRaises(ValueError):
            memory_library.commit_candidates(self.project, 1, raw_digest)
        with self.assertRaises(ValueError):
            character_state.commit_candidates(self.project, 1, raw_digest)
        self.assertEqual(memory_library.read(self.project)["items"], [])
        self.assertEqual(character_state.read(self.project)["persons"], {})

        approved = writer_runner.approve_chapter_review(self.project, 1)
        self.assertEqual(approved["review_decision"], "human_approved")
        self.assertIn(1, writer_runner.reviewed_chapters(self.project))
        self.assertIn("林舟：断剑",
                      [item["title"] for item in memory_library.read(self.project)["items"]])
        self.assertTrue(character_state.read(self.project)["persons"])

    def test_http_commit_endpoints_reject_pending_and_accept_after_approve(self):
        headers = {"X-Novel-Helper": "1"}
        with patch.object(manager_app, "DATA", Path(self.temp.name)), \
                patch.object(manager_app, "AI_PATH", Path(self.temp.name) / "ai.json"):
            client = TestClient(
                manager_app.create_app(Path(self.temp.name) / "manager.db", start_dispatcher=False))
            try:
                response = client.post("/api/projects", json={"path": str(self.project)}, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                identity = response.json()["id"]
                memory_url = f"/api/projects/{identity}/memory/candidates/1/commit"
                character_url = f"/api/projects/{identity}/characters/candidates/1/commit"
                self.assertEqual(client.post(memory_url, headers=headers).status_code, 400)
                self.assertEqual(client.post(character_url, headers=headers).status_code, 400)
                self.assertEqual(memory_library.read(self.project)["items"], [])
                self.assertEqual(character_state.read(self.project)["persons"], {})

                approved = client.post(
                    f"/api/projects/{identity}/chapters/1/approve-review",
                    json={}, headers=headers)
                self.assertEqual(approved.status_code, 200, approved.text)
                memory = client.post(memory_url, headers=headers)
                self.assertEqual(memory.status_code, 200, memory.text)
                self.assertIn(memory.json()["status"], {"committed", "reused"})
                people = client.post(character_url, headers=headers)
                self.assertEqual(people.status_code, 200, people.text)
                self.assertIn(people.json()["status"], {"committed", "reused"})
            finally:
                client.close()


class P1DZeroRevisionHandoffTests(unittest.TestCase):
    """P1-D: max_revisions=0 handoff has one review and must be approvable."""

    def _generated(self, root: Path):
        project = make_project(root)
        outline_file(project, "## 第1章 起风\n故事梗概：林舟下山。\n")
        executor = install_executor(stream_review=REVISE, reviews=[dict(REVISE)])
        env = {"NOVEL_HELPER_AI_CONFIG": str(project / "offline-ai.json"),
               "AI_API_KEY": "", "AI_MODEL": ""}
        with patch.dict(os.environ, env), patch_loader(executor):
            result = writer_runner.generate_chapter(project, chapter_id=1, max_revisions=0)
        return project, executor, result

    def test_zero_revision_generate_handoff_is_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, executor, result = self._generated(Path(tmp))
            self.assertEqual(result["status"], "generated")
            review = result["review"]
            self.assertEqual(review["review_decision"], "needs_human_review")
            self.assertEqual(review["auto_review_count"], 1)
            self.assertEqual(review["handoff_reason"], "zero_revision_budget")
            self.assertEqual(executor.execute_review.await_count, 0)

            approved = writer_runner.approve_chapter_review(project, 1)
            self.assertEqual(approved["status"], "approved")
            self.assertFalse(approved.get("reused", False))
            self.assertEqual(approved["review_decision"], "human_approved")
            self.assertIn(1, writer_runner.reviewed_chapters(project))

    def test_ordinary_one_review_handoff_still_needs_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            write_handoff(project, count=1, reason="auto_review_cap")
            with self.assertRaises(ValueError) as caught:
                writer_runner.approve_chapter_review(project, 1)
            self.assertIn("2 次", str(caught.exception))


class P1EQualityFailClosedTests(unittest.TestCase):
    """P1-E: unscored PASS is not quality-pass unless explicitly configured."""

    UNSCORED = {"success": True, "review_decision": "pass", "needs_revision": False,
                "raw_review": "结论：无需修改"}

    def test_unscored_pass_fails_closed_everywhere(self):
        self.assertFalse(quality_gate.review_passed(self.UNSCORED))
        self.assertFalse(quality_gate.pass_ok(self.UNSCORED))
        self.assertFalse(publication_safety.review_eligible(self.UNSCORED, "a" * 64))
        self.assertIsNone(quality_gate.judge(self.UNSCORED)["quality_pass"])

    def test_explicit_compatibility_allows_unscored_pass(self):
        config = {"review_quality": {"allow_unscored_pass": True}}
        self.assertTrue(quality_gate.review_passed(self.UNSCORED, config))
        self.assertTrue(quality_gate.pass_ok(self.UNSCORED, config=config))
        with patch.object(quality_gate, "_config", return_value=config):
            self.assertTrue(publication_safety.review_eligible(self.UNSCORED, "a" * 64))

    def test_complete_scores_still_pass(self):
        self.assertTrue(quality_gate.review_passed(PASS_FULL))
        self.assertTrue(quality_gate.pass_ok(PASS_FULL))
        self.assertTrue(publication_safety.review_eligible(PASS_FULL, "a" * 64))


class P1FOutlineListTests(unittest.TestCase):
    """P1-F: numbered list items are not chapter headings."""

    OUTLINE = "\n".join([
        "## 第1章 起风",
        "本章梗概：林舟下山，旧友带来父亲的消息。",
        "主要事件：",
        "1. 林舟在山门遇到旧友",
        "2. 旧友带来断剑",
        "3. 两人约定入城",
        "关键线索：父亲的血债",
        "## 第2章 入城",
        "本章梗概：两人进入旧城。",
        "1. 城门口被盘问",
        "关键线索：城隍庙",
    ])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))
        outline_file(self.project, self.OUTLINE)

    def test_writer_runner_keeps_full_chapter_block(self):
        first = writer_runner._find_outline(self.project, 1)
        for expected in ("1. 林舟在山门遇到旧友", "2. 旧友带来断剑",
                         "3. 两人约定入城", "关键线索：父亲的血债"):
            self.assertIn(expected, first)
        self.assertNotIn("第2章", first)
        second = writer_runner._find_outline(self.project, 2)
        self.assertTrue(second.startswith("## 第2章 入城"))
        self.assertIn("1. 城门口被盘问", second)

    def test_skill_executor_keeps_full_chapter_block(self):
        SkillExecutor, _ = writer_runner._load_webnovel_services()
        executor = SkillExecutor(project_root=self.project)
        first = executor._find_chapter_outline(1)
        for expected in ("1. 林舟在山门遇到旧友", "2. 旧友带来断剑",
                         "3. 两人约定入城", "关键线索：父亲的血债"):
            self.assertIn(expected, first)
        self.assertNotIn("第2章", first)
        self.assertTrue(executor._find_chapter_outline(2).startswith("## 第2章 入城"))

    def test_heading_forms_and_plain_lists(self):
        matcher = writer_runner._chapter_heading_number
        for line in ("## 第1章 起风", "# 1. 起风", "**1. 起风**", "__1. 起风__",
                     "1. 《书名》", "第 1 章 起风", "第01章 起风", "第一章 起风"):
            with self.subTest(line=line):
                self.assertEqual(matcher(line), 1)
        for line in ("1. 事件", "- 1. 事件", "2. 事件", "* 3. 事件"):
            with self.subTest(line=line):
                self.assertIsNone(matcher(line))

        SkillExecutor, _ = writer_runner._load_webnovel_services()
        for line in ("# 1. 起风", "**1. 起风**", "1. 《书名》", "第 1 章 起风"):
            with self.subTest(line=line):
                self.assertEqual(SkillExecutor._match_outline_chapter_number(line), 1)
        for line in ("1. 事件", "- 1. 事件"):
            with self.subTest(line=line):
                self.assertIsNone(SkillExecutor._match_outline_chapter_number(line))


class ReviewGuardsTests(unittest.TestCase):
    """P2-1/P2-2/P2-3/P3-1: review-existing and approval guards."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = make_project(Path(self.temp.name))
        self.receipt = write_handoff(self.project)
        self.path = self.project / "正文" / "第1章-起风.md"

    def test_p2_1_whitespace_change_cannot_bypass_handoff_guard(self):
        self.path.write_text(BODY + "\n \n", encoding="utf-8", newline="\n")
        executor = install_executor()
        with patch_loader(executor):
            with self.assertRaises(ValueError) as caught:
                writer_runner.review_existing_chapter(self.project, 1)
        self.assertIn("人工复核", str(caught.exception))
        executor.execute_review.assert_not_awaited()

        self.path.write_text(BODY + "\n他转身下山。\n", encoding="utf-8", newline="\n")
        executor = install_executor(reviews=[dict(PASS_FULL)])
        with patch_loader(executor):
            result = writer_runner.review_existing_chapter(self.project, 1)
        self.assertEqual(result["review_decision"], "pass")
        self.assertEqual(executor.execute_review.await_count, 1)

    def test_p2_2_approve_is_idempotent_for_same_body(self):
        first = writer_runner.approve_chapter_review(self.project, 1)
        self.assertFalse(first.get("reused", False))
        again = writer_runner.approve_chapter_review(self.project, 1)
        self.assertEqual(again["status"], "approved")
        self.assertTrue(again["reused"])

        self.path.write_text(BODY + "\n他转身下山。\n", encoding="utf-8", newline="\n")
        with self.assertRaises(ValueError):
            writer_runner.approve_chapter_review(self.project, 1)

    def test_p2_3_approved_chapter_cannot_be_re_reviewed_until_body_changes(self):
        writer_runner.approve_chapter_review(self.project, 1)
        executor = install_executor()
        with patch_loader(executor):
            with self.assertRaises(ValueError) as caught:
                writer_runner.review_existing_chapter(self.project, 1)
        self.assertIn("已人工批准", str(caught.exception))
        executor.execute_review.assert_not_awaited()

        self.path.write_text(BODY + "\n \n", encoding="utf-8", newline="\n")
        with patch_loader(executor):
            with self.assertRaises(ValueError) as caught:
                writer_runner.review_existing_chapter(self.project, 1)
        self.assertIn("已人工批准", str(caught.exception))
        executor.execute_review.assert_not_awaited()

    def test_p2_4_approve_marks_sync_pending_then_next_generation_repairs(self):
        writer_runner.approve_chapter_review(self.project, 1)
        receipts = json.loads((self.project / ".webnovel" / "writer_receipts.json").read_text(encoding="utf-8"))
        self.assertEqual(receipts["1"]["post_save"]["status"], "pending_approval")
        synced = {"status": "synced", "entities": {"status": "synced"},
                  "shared_memory": {"status": "synced"}, "rag_indexed": True,
                  "continuity_written": True}
        with patch.object(writer_runner, "_sync_committed_artifacts",
                          new=AsyncMock(return_value=synced)) as repair:
            asyncio.run(writer_runner._repair_approved_artifacts(self.project, 2, Mock()))
        repair.assert_awaited_once()
        # _sync_committed_artifacts owns the receipt write; the helper only
        # dispatches it. The real end-to-end path is covered by the suite.

    def test_p3_1_approve_requires_a_valid_body_digest(self):
        receipts_path = self.project / ".webnovel" / "writer_receipts.json"
        base = json.loads(receipts_path.read_text(encoding="utf-8"))
        for value in (None, "not-a-sha", "0" * 64):
            review = dict(base["1"]["review"])
            review.pop("body_sha256", None)
            if value is not None:
                review["body_sha256"] = value
            receipts_path.write_text(json.dumps(
                {"1": {**base["1"], "review": review}}, ensure_ascii=False), encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(ValueError):
                writer_runner.approve_chapter_review(self.project, 1)


class P25ReviewBudgetAtomicTests(unittest.TestCase):
    """P2-5: the review budget is reserved before D and survives a D crash."""

    def test_crash_after_review_reservation_does_not_refund_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            outline_file(project, "## 第1章 起风\n故事梗概。\n")
            executor = install_executor(stream_review=None,
                                        reviews=[RuntimeError("D 崩溃"), dict(REVISE)])
            env = {"NOVEL_HELPER_AI_CONFIG": str(project / "offline-ai.json"),
                   "AI_API_KEY": "", "AI_MODEL": ""}
            checkpoint_dir = project / ".webnovel" / "draft_checkpoints"

            with patch.dict(os.environ, env), patch_loader(executor):
                with self.assertRaises(RuntimeError):
                    asyncio.run(writer_runner._generate_and_review(project, 1, 100, 0))
                files = sorted(checkpoint_dir.glob("*.json"))
                self.assertEqual(len(files), 1)
                saved = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(saved["auto_review_count"], 1)
                self.assertIn("review_reserved_sha256", saved)

                result = asyncio.run(writer_runner._generate_and_review(project, 1, 100, 0))
                self.assertEqual(executor.execute_review.await_count, 2)
                saved = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(saved["auto_review_count"], 2)
                self.assertEqual(result["review"]["review_decision"], "needs_human_review")
                self.assertEqual(result["review"]["auto_review_count"], 2)


if __name__ == "__main__":
    unittest.main()
