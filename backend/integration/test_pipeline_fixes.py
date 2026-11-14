"""端到端回归：评估报告 F01—F06 的真实主链路接线。

这些用例不调用模型：只验证指纹、候选时机、人物上下文、门槛重算、预算失败停止、
修订轮数上限与报告约定绑定在**生产函数**上的行为。
"""
import json
import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from integration import bridge, character_state, costs, memory_library, quality_gate
from integration import resource_policy, scene_writer, writer_runner, chapter_versions, version_history, model_roles

BODY = "# 第1章 起点\n\n他把表放在桌上。\n\n「七点二十。」她说。\n"
SCORES = {"setting": 90, "plot": 90, "character": 90, "prose": 90, "dialogue": 90, "style": 90}


def make_project(root: Path) -> Path:
    (root / "正文").mkdir(parents=True)
    web = root / ".webnovel"
    web.mkdir()
    (web / "creative_brief.json").write_text(
        json.dumps({"schema": 1, "revision": 1, "history": [],
                    "brief": {"genre": "悬疑", "premise": "停表", "style": "短句"}},
                   ensure_ascii=False),
        encoding="utf-8")
    path = root / "正文" / "第1章-起点.md"
    path.write_text(BODY, encoding="utf-8", newline="\n")
    return path


def review_payload():
    return {
        "success": True,
        "review_decision": "pass",
        "needs_revision": False,
        "quality": {"scores": dict(SCORES)},
        "fact_candidates": [
            {"title": "怀表停在七点二十", "content": "怀表停在七点二十", "quote": "「七点二十。」她说。"},
        ],
        "character_candidates": [
            {"kind": "knowledge", "person": "她", "info": "她看见了停在七点二十的表",
             "event": "递表", "quote": "「七点二十。」她说。"},
        ],
    }


def bind_receipt(root: Path, path: Path, review: dict) -> None:
    """真实主链路在落盘前就写好回执；测试里补上同样的绑定。"""
    writer_runner.atomic_json(root / ".webnovel" / "writer_receipts.json",
                              {"1": {"destination": str(path.resolve()),
                                     "sha256": bridge.digest_file(path),
                                     "creative_contract_hash": bridge.creative_contract_hash(root),
                                     "review": review, "revision_rounds": 0}})


class CandidateLifecycleTest(unittest.TestCase):
    """F01：规范化摘要与原始字节摘要都要能核对，且候选只在正文落盘后提交。"""

    def test_normalized_digest_is_accepted_and_commits(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_project(root)
            review = review_payload()
            writer_runner._record_review_attempt(root, 1, BODY, review)
            bind_receipt(root, path, review)
            digest = bridge.body_digest(BODY)
            saved = memory_library.save_candidates(root, 1, review, digest)
            self.assertEqual(saved["status"], "pending")
            self.assertEqual(saved["count"], 1)
            raw = bridge.digest_file(root / "正文" / "第1章-起点.md")
            committed = memory_library.commit_candidates(root, 1, digest)
            self.assertEqual(committed["status"], "committed")
            self.assertGreaterEqual(committed["added"], 1)
            titles = [item["title"] for item in memory_library.read(root)["items"]]
            self.assertIn("怀表停在七点二十", titles)

    def test_character_candidates_accept_normalized_digest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_project(root)
            path.write_text(BODY, encoding="utf-8-sig", newline="\r\n")
            character_state.upsert_person(root, name="她")
            saved = character_state.save_candidates(root, 1, review_payload(), bridge.body_digest(BODY))
            self.assertEqual(saved["status"], "pending")
            self.assertEqual(saved["count"], 1)

    def test_review_attempt_binds_contract_and_defers_candidates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_project(root)
            review = review_payload()
            writer_runner._record_review_attempt(root, 1, BODY, review)
            bind_receipt(root, path, review)
            record = quality_gate.latest(root, 1)
            self.assertIsNotNone(record)
            self.assertEqual(record["contract_hash"], bridge.creative_contract_hash(root))
            facts = root / ".webnovel" / "fact_candidates"
            self.assertFalse(facts.is_dir() and list(facts.glob("*.json")))
            result = writer_runner._commit_review_candidates(root, 1, BODY, review)
            self.assertEqual(result["memory_library"]["committed"], "committed")
            self.assertGreaterEqual(result["memory_library"]["added"], 1)


class CharacterContextTest(unittest.TestCase):
    """F02：人物限制与认知必须出现在真实写作提示里。"""

    def test_memory_context_carries_character_limits(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            character_state.upsert_person(root, name="阿岚", profile={"limits": "不能游泳"})
            context = memory_library.context(root, role="B", chapter=2, query="阿岚")
            self.assertIn("不能游泳", context["text"])
            self.assertIn("不能游泳", context["characters"])

    def test_scene_prompt_carries_character_limits(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            character_state.upsert_person(root, name="阿岚", profile={"limits": "不能游泳"})
            card = {"id": "s1", "position": 1, "characters": ["阿岚"], "purpose": "递表",
                    "facts": [], "info_change": "", "target_chars": 600, "must_follow": "", "calm": False}
            prompt = scene_writer._prompt(root, 2, card, "", "")
            self.assertIn("不能游泳", prompt)
            self.assertEqual(prompt.count("不能游泳"), 1)

    def test_stale_knowledge_is_excluded_but_evidence_remains(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_project(root)
            character_state.upsert_person(root, name="她")
            character_state.learn(root, person="她", info="密码是七点二十", chapter=1,
                                  event="递表", quote="「七点二十。」她说。", sha256=bridge.digest_file(path))
            self.assertIn("密码是七点二十", memory_library.context(root, chapter=2, query="她")["text"])
            path.write_text(BODY.replace("七点二十", "八点三十"), encoding="utf-8")
            ctx = memory_library.context(root, chapter=2, query="她")
            self.assertNotIn("密码是七点二十", ctx["text"])
            self.assertEqual(ctx["omitted_breakdown"]["stale"], 1)
            row = character_state.view(root, 2)["persons"][0]["knowledge"][0]
            self.assertEqual(row["source_status"], "pending_review")
            self.assertEqual(len(character_state.read(root)["knowledge"]), 1)
            path.unlink()
            self.assertEqual(character_state.knows(root, "她", 2)["confirmed"], [])

    def test_characters_share_budget_and_are_filtered(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            for index in range(12):
                character_state.upsert_person(root, name=f"人物{index}号", profile={"limits": "限制" * 500})
            ctx = memory_library.context(root, chapter=2, query="无关场景", budget=500)
            self.assertLessEqual(len(ctx["text"]), 500)
            with self.assertRaises(memory_library.ContextBudgetExceeded):
                memory_library.context(root, chapter=2, names=["人物1号"], budget=500)
            with self.assertRaises(memory_library.ContextBudgetExceeded):
                scene_writer._prompt(root, 2, {"characters": ["人物1号"]}, "", "要求" * 12000)
            ctx = memory_library.context(root, chapter=2, names=["人物1号"], budget=2000)
            self.assertLessEqual(len(ctx["text"]), 2000)
            self.assertIn("人物1号", ctx["text"])
            self.assertNotIn("人物2号", ctx["text"])
            value = {"category": "canon", "title": "世界规则", "content": "既定规则" * 350}
            memory_library.save_item(root, value, 0)
            ctx = memory_library.context(root, chapter=2, names=["人物1号"], budget=2000)
            self.assertLessEqual(len(ctx["text"]), 2000)
            self.assertEqual(ctx["omitted_breakdown"]["budget"], 1)
            self.assertIn("因上下文预算未纳入", ctx["text"])
            item = memory_library.read(root)["items"][0]
            memory_library.save_item(root, {**value, "pinned": True}, 1, identity=item["id"])
            with self.assertRaises(memory_library.ContextBudgetExceeded):
                memory_library.context(root, chapter=2, names=["人物1号"], budget=2000)


class ImportedReviewTest(unittest.TestCase):
    def test_first_import_review_commits_candidates_and_failed_rereview_revokes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_project(root)
            path.write_text(BODY, encoding="utf-8-sig", newline="\r\n")
            character_state.upsert_person(root, name="她")
            executor = mock.Mock()
            executor.execute_review = mock.AsyncMock(return_value=review_payload())
            with mock.patch.object(writer_runner, "_load_webnovel_services", return_value=(mock.Mock(return_value=executor), lambda: object())), \
                 mock.patch.object(model_roles, "load_config", return_value={}), \
                 mock.patch.object(writer_runner, "_sync_committed_artifacts", mock.AsyncMock(return_value={})):
                result = asyncio.run(writer_runner.review_existing_chapter_async(root, 1))
                self.assertEqual(result["status"], "reviewed")
                receipt = writer_runner.strict_json(root / ".webnovel/writer_receipts.json", {})["1"]
                self.assertEqual(receipt["candidates"]["memory_library"]["added"], 1)
                self.assertEqual(receipt["candidates"]["character_state"]["added"]["knowledge"], 1)
                self.assertEqual(len(memory_library.read(root)["items"]), 1)
                self.assertEqual(len(character_state.read(root)["knowledge"]), 1)
                executor.execute_review.return_value = {"success": True, "review_decision": "needs_revision", "needs_revision": True}
                original_commit = writer_runner._commit_review_candidates
                def assert_revoked(*args, **kwargs):
                    self.assertNotIn(1, writer_runner.reviewed_chapters(root))
                    return original_commit(*args, **kwargs)
                with mock.patch.object(writer_runner, "_commit_review_candidates", side_effect=assert_revoked) as commit:
                    result = asyncio.run(writer_runner.review_existing_chapter_async(root, 1))
                    self.assertEqual(result["status"], "review_failed")
                    self.assertNotIn(1, writer_runner.reviewed_chapters(root))
                    commit.assert_called_once()


class GateRecomputeTest(unittest.TestCase):
    """F03/F06：门槛与约定变化必须按当前状态重算，不能沿用缓存通过。"""

    def test_threshold_change_recomputes_public_report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            review = review_payload()
            quality_gate.save_report(root, 1, review, body_sha256=bridge.body_digest(BODY),
                                     contract_hash=bridge.creative_contract_hash(root))
            loose = {"review_quality": {"threshold_total": 85, "threshold_item": 70}}
            strict = {"review_quality": {"threshold_total": 95, "threshold_item": 70}}
            self.assertTrue(quality_gate.public_report(root, 1, config=loose)["report"]["quality_pass"])
            strict_view = quality_gate.public_report(root, 1, config=strict)
            self.assertFalse(strict_view["report"]["quality_pass"])
            self.assertEqual(strict_view["report"]["thresholds"]["total"], 95)
            self.assertFalse(quality_gate.pass_ok(review, config=strict))
            self.assertTrue(quality_gate.pass_ok(review, config=loose))

    def test_contract_change_marks_report_stale(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            quality_gate.save_report(root, 1, review_payload(), body_sha256=bridge.body_digest(BODY),
                                     contract_hash=bridge.creative_contract_hash(root))
            self.assertIsNone(quality_gate.public_report(root, 1)["status"]["stale_reason"])
            brief = root / ".webnovel" / "creative_brief.json"
            doc = json.loads(brief.read_text(encoding="utf-8"))
            doc["brief"]["style"] = "长句铺陈"
            doc["revision"] = 2
            brief.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8", newline="\n")
            status = quality_gate.public_report(root, 1)["status"]
            self.assertFalse(status["valid"])
            self.assertEqual(status["stale_reason"], "contract_changed")

    def test_unbound_report_is_not_treated_as_valid(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
            quality_gate.save_report(root, 1, review_payload(), body_sha256=bridge.body_digest(BODY))
            status = quality_gate.public_report(root, 1)["status"]
            self.assertFalse(status["valid"])
            self.assertEqual(status["stale_reason"], "contract_unbound")

    def test_history_recomputes_thresholds_and_contract_for_historical_body(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_project(root)
            old = chapter_versions.snapshot(root, 1)
            review = review_payload()
            review["quality_gate"] = quality_gate.judge(review, {"review_quality": {"threshold_total": 85}})
            quality_gate.save_report(root, 1, review, body_sha256=bridge.body_digest(BODY),
                                     contract_hash=bridge.creative_contract_hash(root))
            path.write_text("改过的正文", encoding="utf-8")
            chapter_versions.snapshot(root, 1)
            strict = {"review_quality": {"threshold_total": 95}}
            self.assertEqual(version_history.best(root, 1, config=strict)["status"], "no_passing_version")
            self.assertEqual(version_history.best(root, 1)["status"], "passing")
            brief = root / ".webnovel/creative_brief.json"
            data = json.loads(brief.read_text(encoding="utf-8"))
            data["brief"]["style"] = "长句"
            writer_runner.atomic_json(brief, data)
            result = version_history.best(root, 1)
            self.assertEqual(result["status"], "no_passing_version")
            self.assertEqual(result["recommended"]["quality"]["stale_reason"], "contract_changed")
            brief.unlink()
            self.assertEqual(version_history.best(root, 1)["recommended"]["quality"]["stale_reason"], "contract_changed")
            self.assertEqual(quality_gate.status(root, 1, body_sha256=bridge.body_digest(BODY))["stale_reason"], "contract_changed")
            quality_gate.save_report(root, 1, review, body_sha256=bridge.body_digest(BODY))
            writer_runner.atomic_json(brief, data)
            self.assertEqual(version_history.best(root, 1)["recommended"]["quality"]["stale_reason"], "contract_unbound")


class BudgetStopTest(unittest.TestCase):
    """F04：预算已开启但预留写不进去时，必须在发请求之前停止。"""

    def test_reservation_failure_blocks_attempt(self):
        with TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "costs.sqlite3")
            limits = {"requests_per_day": 5, "request_tokens": None, "chapter_tokens": None,
                      "project_tokens": None, "chapter_cost_cny": None, "project_cost_cny": None,
                      "unknown_reserve_cny": "1"}
            with mock.patch.object(costs, "connection", side_effect=sqlite3.OperationalError("locked")):
                with self.assertRaises(costs.BudgetExceeded):
                    costs.reserve_request(db, "p", 1, "draft", tokens=100, limits=limits)

    def test_attempt_stops_before_http_when_reservation_fails(self):
        with TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "costs.sqlite3")
            limits = {"requests_per_day": 5, "request_tokens": None, "chapter_tokens": None,
                      "project_tokens": None, "chapter_cost_cny": None, "project_cost_cny": None,
                      "unknown_reserve_cny": "1"}
            costs._INITIALIZED_DBS.clear()
            with costs.scope(db=db, project="p", chapter=1, stage="draft"):
                with mock.patch.object(costs, "budget_limits", return_value=limits):
                    with mock.patch.object(costs, "reserve_request", side_effect=sqlite3.OperationalError("locked")):
                        with self.assertRaises(costs.BudgetExceeded):
                            costs.Attempt("http://127.0.0.1:1/v1", "m",
                                          {"messages": [{"role": "user", "content": "x"}], "max_tokens": 10})

    def test_corrupt_database_blocks_the_whole_attempt_initialization(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "broken.sqlite3"
            db.write_bytes(b"not a sqlite database")
            limits = {"requests_per_day": 0}
            with costs.scope(db=str(db), project="p", chapter=1), \
                 mock.patch.object(costs, "budget_limits", return_value=limits):
                with self.assertRaises(costs.BudgetExceeded):
                    costs.Attempt("https://example.com/v1", "m", {"max_tokens": 10})
            self.assertEqual(db.read_bytes(), b"not a sqlite database")


class RevisionLimitTest(unittest.TestCase):
    """F05：自动修订轮数由资源策略封顶。"""

    def test_policy_caps_requested_rounds(self):
        self.assertEqual(writer_runner.effective_revisions(2, {"resource_policy": {"revision_rounds": 0}}), 0)
        self.assertEqual(writer_runner.effective_revisions(3, {"resource_policy": {"revision_rounds": 3}}), 3)
        self.assertEqual(writer_runner.effective_revisions(5, {"resource_policy": {"revision_rounds": 2}}), 2)
        self.assertEqual(writer_runner.effective_revisions(2, {}), 1)


if __name__ == "__main__":
    unittest.main()
