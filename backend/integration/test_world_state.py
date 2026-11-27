"""世界状态确定性核心：事实域、2-gram 检索、五级上下文与防脏数据。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import chapter_editor as ce
from integration import outline_editor as oe
from integration import world_state as ws


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    (project / "大纲").mkdir()
    return project


def seed(project, chapter, text, title=None):
    ce.new_chapter(project, {"chapter": chapter, "title": title or f"第{chapter}章",
                             "content": text, "op_id": f"n-{chapter}-{len(text)}"})


class FactTest(unittest.TestCase):
    def test_validity_windows_and_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "林溪拿着青铜令牌。\n")
            fact = ws.upsert_fact(project, {
                "fact_id": "fact_1", "entity_id": "ent_lin", "domain": "item",
                "subject": "林溪", "predicate": "持有", "object": "青铜令牌",
                "valid_from_chapter": 1, "valid_until_chapter": 2,
                "authority_level": "confirmed_prose", "confidence": 0.99,
                "source_chapter": 1, "pinned": True,
            })["fact"]
            self.assertTrue(fact["pinned"])
            self.assertEqual(len(ws.facts_for_chapter(project, 1)), 1)
            self.assertEqual(len(ws.facts_for_chapter(project, 2)), 1)
            self.assertEqual(ws.facts_for_chapter(project, 3), [])
            # 低权威推断不得覆盖已确认事实
            ignored = ws.upsert_fact(project, {
                "fact_id": "fact_1", "entity_id": "ent_lin", "domain": "item",
                "subject": "林溪", "predicate": "持有", "object": "木牌",
                "authority_level": "ai_inferred", "confidence": 0.9,
            })
            self.assertEqual(ignored["status"], "ignored_lower_authority")
            self.assertEqual(ws.get_fact(project, "fact_1")["object"], "青铜令牌")

    def test_manual_card_pin_and_story_time(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            card = ws.set_card(project, {
                "entity_id": "ent_lin", "name": "林溪", "kind": "character",
                "aliases": ["小溪"], "pinned": True, "story_time": "第一卷·第3天夜",
                "card_md": "女主，测绘员，怕黑。",
            })
            self.assertTrue(card["pinned"])
            self.assertEqual(card["aliases"], ["小溪"])
            self.assertEqual(ws.list_cards(project, pinned_only=True)[0]["entity_id"], "ent_lin")

    def test_conflict_detection_and_author_ignore(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "老周死了。\n")
            base = {"entity_id": "ent_zhou", "domain": "character", "subject": "老周",
                    "predicate": "生死", "authority_level": "confirmed_prose", "confidence": 0.95,
                    "valid_from_chapter": 1}
            ws.upsert_fact(project, {**base, "fact_id": "f1", "object": "死亡", "source_chapter": 1})
            ws.upsert_fact(project, {**base, "fact_id": "f2", "object": "存活", "source_chapter": 1})
            conflicts = ws.detect_conflicts(project, 1)
            self.assertEqual(len(conflicts), 1)
            self.assertEqual({row["fact_id"] for row in conflicts[0]["facts"]}, {"f1", "f2"})
            uid = ws.wb.chapter_uid(project, 1)
            ws.ignore_conflict(project, "f2", chapter_uid=uid, reason="故意为之/回忆杀")
            self.assertFalse(any("老周" in item["message"] for item in ws.detect_conflicts(project, 1)))

    def test_two_character_name_recall(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "雨点敲在铁皮上。林溪推开门，老周在档案馆等她。\n")
            ws.index_chapter(project, 1)
            self.assertEqual(len(ws.search(project, "林溪")), 1)
            self.assertEqual(len(ws.search(project, "老周")), 1)

    def test_two_character_search_does_not_match_single_characters(self):
        """审计 C-46：查「林溪」不能命中只含「林」或只含「溪」的章节。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "林中没有人。\n")
            seed(project, 2, "林溪推门进来。\n")
            seed(project, 3, "溪水长流。\n")
            for chapter in (1, 2, 3):
                ws.index_chapter(project, chapter)
            hits = ws.search(project, "林溪")
            self.assertEqual([hit["chapter_id"] for hit in hits], [2])


class ContextTest(unittest.TestCase):
    def test_five_layers_manifest_and_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章。林溪在档案馆查旧地图。\n")
            seed(project, 2, "第二章。旧地图在档案馆。\n")
            (project / ".webnovel" / "shared_memory.json").write_text(json.dumps({
                "schema": 1, "revision": 1, "chapters": {}, "history": [],
                "items": [{"id": "a" * 32, "category": "canon", "title": "铁律",
                           "content": "不能在第一章揭晓凶手", "status": "active", "pinned": True,
                           "updated_revision": 1, "source": {"kind": "manual", "chapter": 0}}],
            }, ensure_ascii=False), encoding="utf-8", newline="\n")
            (project / "大纲" / "AI规划-0001-0002.md").write_text(
                "<!-- novel-plan:{\"schema_version\":2,\"chapters\":[{\"id\":2,\"title\":\"档案馆\",\"outline\":\"林溪查旧地图\",\"chapter_rev\":1}]} -->\n\n"
                "## 第2章 档案馆\n林溪查旧地图\n", encoding="utf-8", newline="\n")
            ws.set_card(project, {"entity_id": "ent_lin", "name": "林溪", "kind": "character",
                                  "pinned": True, "card_md": "测绘员"})
            ws.index_chapter(project, 2)
            ws.index_chapter(project, 1)
            context = ws.build_context(project, 2, query="旧地图", budget_chars=4000)
            self.assertIn("【L1", context["text"])
            self.assertIn("【L5", context["text"])
            layer_names = {layer["layer"] for layer in context["manifest"]["layers"]}
            self.assertEqual(layer_names, {"L1", "L2", "L3", "L4", "L5"})
            self.assertGreater(context["manifest"]["tokens"], 0)
            self.assertTrue(any(item["kind"] == "retrieval" for item in context["manifest"]["items"]))
            # 审计 C-21：为第 2 章组装上下文时，L5 只能检索第 1 章及更早，
            # 不能把第 2 章自己的正文回灌给模型。
            retrieval_chapters = [item["chapter_id"] for item in context["manifest"]["items"]
                                  if item["kind"] == "retrieval"]
            self.assertEqual(retrieval_chapters, [1])
            stored = ws.latest_manifest(project, 2)
            self.assertIsNotNone(stored)
            self.assertEqual(stored["chapter_id"], 2)
            # 极小预算也不能砍掉 L1 铁律
            tight = ws.build_context(project, 2, query="旧地图", budget_chars=80)
            self.assertIn("不能在第一章揭晓凶手", tight["text"])


class AuthorityAndDedupTest(unittest.TestCase):
    def test_confirm_raises_authority_and_reject_requires_pending(self):
        """审计 C-01/C-20：确认必须提升 authority，否决只接受 pending。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "老周死了。\n")
            ws.set_card(project, {"entity_id": "ent_zhou", "name": "老周", "pinned": True})
            extracted = ws.extract_candidates(project, 1, {"facts": [{
                "entity_id": "ent_zhou", "domain": "character", "subject": "老周",
                "predicate": "死亡", "object": "死亡", "confidence": 0.96}]})
            pending = extracted["pending_confirm"][0]
            self.assertEqual(pending["authority_level"], "ai_inferred")
            confirmed = ws.confirm_fact(project, pending["fact_id"],
                                        authority_level="confirmed_prose")
            self.assertEqual(confirmed["status"], "active")
            self.assertEqual(confirmed["authority_level"], "confirmed_prose")
            with self.assertRaises(ws.WorldStateError) as caught:
                ws.confirm_fact(project, pending["fact_id"])
            self.assertEqual(caught.exception.code, "fact_not_pending")
            with self.assertRaises(ws.WorldStateError) as caught:
                ws.reject_fact(project, pending["fact_id"])
            self.assertEqual(caught.exception.code, "fact_not_pending")
            second = ws.upsert_fact(project, {
                "fact_id": "fact_reject", "entity_id": "ent_zhou2", "domain": "character",
                "subject": "老周", "predicate": "去向", "object": "失踪",
                "authority_level": "ai_inferred", "confidence": 0.9,
                "status": "pending_confirm"})["fact"]
            rejected = ws.reject_fact(project, second["fact_id"])
            self.assertEqual(rejected["status"], "archived")

    def test_upsert_and_partial_card_keep_author_pin(self):
        """审计 C-16：同权威覆盖与局部卡片更新不得清掉 pinned/author_locked。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            ws.upsert_fact(project, {"fact_id": "f_pin", "entity_id": "ent_lin",
                                     "domain": "character", "subject": "林溪",
                                     "predicate": "身份", "object": "测绘员",
                                     "authority_level": "confirmed_prose",
                                     "confidence": 1.0, "pinned": True,
                                     "author_locked": True})
            ws.upsert_fact(project, {"fact_id": "f_pin", "entity_id": "ent_lin",
                                     "domain": "character", "subject": "林溪",
                                     "predicate": "身份", "object": "测绘员",
                                     "authority_level": "confirmed_prose",
                                     "confidence": 1.0})
            fact = ws.get_fact(project, "f_pin")
            self.assertTrue(fact["pinned"])
            self.assertTrue(fact["author_locked"])
            ws.set_card(project, {"entity_id": "ent_lin", "name": "林溪", "pinned": True,
                                  "card_md": "女主"})
            ws.set_card(project, {"entity_id": "ent_lin", "name": "林溪", "card_md": "测绘员"})
            self.assertTrue(ws.get_card(project, "ent_lin")["pinned"])

    def test_new_value_closes_previous_window(self):
        """审计 C-18：同一实体+谓词的新值关闭旧窗口，不再同时 active。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            ws.upsert_fact(project, {"entity_id": "ent_lin", "domain": "character",
                                     "subject": "林溪", "predicate": "修为",
                                     "object": "炼气一层", "authority_level": "confirmed_prose",
                                     "confidence": 1.0, "valid_from_chapter": 1})
            ws.upsert_fact(project, {"entity_id": "ent_lin", "domain": "character",
                                     "subject": "林溪", "predicate": "修为",
                                     "object": "筑基期", "authority_level": "confirmed_prose",
                                     "confidence": 1.0, "valid_from_chapter": 30})
            at_40 = ws.facts_for_chapter(project, 40)
            self.assertEqual([row["object"] for row in at_40], ["筑基期"])
            self.assertEqual(ws.detect_conflicts(project, 40), [])
            at_10 = [row["object"] for row in ws.facts_for_chapter(project, 10)]
            self.assertEqual(at_10, ["炼气一层"])

    def test_belief_differences_are_not_world_conflicts(self):
        """审计 C-19：角色信念差异不是事实冲突。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            base = {"entity_id": "ent_zhou", "domain": "character", "subject": "老周",
                    "predicate": "生死", "authority_level": "confirmed_prose",
                    "confidence": 0.9, "valid_from_chapter": 1, "assertion_type": "belief"}
            ws.upsert_fact(project, {**base, "object": "死亡"})
            ws.upsert_fact(project, {**base, "object": "存活"})
            self.assertEqual(len(ws.facts_for_chapter(project, 1)), 2)
            self.assertEqual(ws.detect_conflicts(project, 1), [])

    def test_pinned_entity_fact_inference_goes_pending(self):
        """审计 C-17：对已 pin 实体的普通新事实也必须作者确认。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "林溪是测绘员。\n")
            ws.set_card(project, {"entity_id": "ent_lin", "name": "林溪", "pinned": True})
            result = ws.extract_candidates(project, 1, {"facts": [{
                "entity_id": "ent_lin", "domain": "character", "subject": "林溪",
                "predicate": "身份", "object": "敌方卧底", "confidence": 0.9}]})
            self.assertEqual(result["counts"]["pending_confirm"], 1)
            self.assertEqual(result["counts"]["accepted"], 0)

    def test_pending_count_is_exact_beyond_page_limit(self):
        """审计 C-24：pending_count 不能等于被截断到 200 的列表长度。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            wb = ws.wb
            wb.initialize(project)
            with wb.write_tx(project) as db:
                for index in range(205):
                    db.execute(
                        "INSERT INTO world_facts(fact_id, domain, subject, predicate, object, "
                        "authority_level, confidence, status, updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (f"bulk_{index}", "character", "批量", "状态", str(index),
                         "ai_inferred", 0.9, "pending_confirm", "2026-01-01T00:00:00Z"))
            state = ws.state(project, chapter=1)
            self.assertEqual(len(state["pending_facts"]), 200)
            self.assertEqual(state["pending_count"], 205)

    def test_budget_overflow_and_rule_error_surface_in_manifest(self):
        """审计 C-22/C-23：超预算与 L1 规则不可用必须显式进入 manifest。"""
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章。\n")
            shared = project / ".webnovel" / "shared_memory.json"
            shared.write_text(json.dumps({
                "schema": 1, "revision": 1, "chapters": {}, "history": [],
                "items": [{"id": "b" * 32, "category": "canon", "title": "超长契约",
                           "content": "禁" * 600, "status": "active", "pinned": True,
                           "updated_revision": 1, "source": {"kind": "manual", "chapter": 0}}],
            }, ensure_ascii=False), encoding="utf-8", newline="\n")
            context = ws.build_context(project, 1, budget_chars=80)
            self.assertTrue(context["manifest"]["over_budget"])
            self.assertGreater(context["manifest"]["budget_overflow_chars"], 0)
            shared.write_text("{broken", encoding="utf-8")
            context = ws.build_context(project, 1, budget_chars=80)
            codes = [row["code"] for row in context["manifest"]["warnings"]]
            self.assertIn("rules_unavailable", codes)


class ExtractionTest(unittest.TestCase):
    def test_high_risk_goes_pending_and_low_confidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "老周死了。\n")
            ws.set_card(project, {"entity_id": "ent_zhou", "name": "老周", "kind": "character",
                                  "pinned": True})
            result = ws.extract_candidates(project, 1, {"facts": [
                {"entity_id": "ent_zhou", "pinned": True, "domain": "character",
                 "subject": "老周", "predicate": "死亡", "object": "死亡",
                 "confidence": 0.96, "assertion_type": "fact", "story_time": "第3天"},
                {"entity_id": "ent_zhou", "domain": "character", "subject": "老周",
                 "predicate": "受伤", "object": "轻伤", "confidence": 0.5},
                {"entity_id": "ent_zhou", "domain": "character", "subject": "老周",
                 "predicate": "说谎", "object": "其实没死", "confidence": 0.9,
                 "assertion_type": "lie"},
            ]})
            self.assertEqual(result["counts"]["pending_confirm"], 1)
            self.assertEqual(result["counts"]["rejected"], 1)
            self.assertEqual(result["counts"]["accepted"], 1)
            pending = result["pending_confirm"][0]
            self.assertEqual(pending["status"], "pending_confirm")
            confirmed = ws.confirm_fact(project, pending["fact_id"])
            self.assertEqual(confirmed["status"], "active")

    def test_causal_scan_defaults_to_max_plus_one(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "化名沈知微。\n")
            seed(project, 2, "老周的葬礼。\n")
            (project / "大纲" / "AI规划-0003-0004.md").write_text(
                "<!-- novel-plan:{\"schema_version\":2,\"chapters\":[{\"id\":3,\"title\":\"化名\",\"outline\":\"女主用化名\",\"chapter_rev\":1}]} -->\n\n"
                "## 第3章 化名\n女主用化名\n", encoding="utf-8", newline="\n")
            scan = ws.causal_scan(project, change="老周 化名", apply_to_existing=False)
            self.assertEqual(scan["effective_from_chapter"], 3)
            self.assertEqual([row["chapter"] for row in scan["groups"]["future_plan"]], [3])
            exempted = ws.add_exemption(project, chapter=1, rule_id="rule_1", rule_text="不得出现血腥")
            self.assertEqual(exempted["status"], "exempted")


if __name__ == "__main__":
    unittest.main()


class WindowScopeTest(unittest.TestCase):
    def test_pending_or_cross_subject_fact_does_not_close_author_window(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            ws.upsert_fact(project, {"entity_id": "ent_lin", "domain": "character",
                                     "subject": "林溪", "predicate": "修为", "object": "炼气一层",
                                     "authority_level": "author_locked", "confidence": 1.0,
                                     "valid_from_chapter": 1, "pinned": True,
                                     "author_locked": True})
            # A pending AI candidate must not close the author-locked window.
            ws.upsert_fact(project, {"entity_id": "ent_lin", "domain": "character",
                                     "subject": "林溪", "predicate": "修为", "object": "筑基期",
                                     "authority_level": "ai_inferred", "confidence": 1.0,
                                     "valid_from_chapter": 5, "status": "pending_confirm"})
            # A different subject with a null/other entity must not close it either.
            ws.upsert_fact(project, {"entity_id": None, "domain": "character",
                                     "subject": "张三", "predicate": "修为", "object": "金丹",
                                     "authority_level": "ai_inferred", "confidence": 1.0,
                                     "valid_from_chapter": 6})
            facts = ws.facts_for_chapter(project, 10)
            author = next(row for row in facts if row["subject"] == "林溪")
            self.assertIsNone(author.get("valid_until_chapter"))
