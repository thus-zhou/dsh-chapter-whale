"""端到端回归：评估报告 F01—F06 的真实主链路接线。

这些用例不调用模型：只验证指纹、候选时机、人物上下文、门槛重算、预算失败停止、
修订轮数上限与报告约定绑定在**生产函数**上的行为。
"""
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from integration import bridge, character_state, costs, memory_library, quality_gate
from integration import resource_policy, scene_writer, writer_runner

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
            committed = memory_library.commit_candidates(root, 1, raw)
            self.assertEqual(committed["status"], "committed")
            self.assertGreaterEqual(committed["added"], 1)
            titles = [item["title"] for item in memory_library.read(root)["items"]]
            self.assertIn("怀表停在七点二十", titles)

    def test_character_candidates_accept_normalized_digest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root)
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
            context = memory_library.context(root, role="B", chapter=2)
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


class RevisionLimitTest(unittest.TestCase):
    """F05：自动修订轮数由资源策略封顶。"""

    def test_policy_caps_requested_rounds(self):
        self.assertEqual(writer_runner.effective_revisions(2, {"resource_policy": {"revision_rounds": 0}}), 0)
        self.assertEqual(writer_runner.effective_revisions(3, {"resource_policy": {"revision_rounds": 3}}), 3)
        self.assertEqual(writer_runner.effective_revisions(5, {"resource_policy": {"revision_rounds": 2}}), 2)
        self.assertEqual(writer_runner.effective_revisions(2, {}), 1)


if __name__ == "__main__":
    unittest.main()
