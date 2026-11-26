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


class ContextTest(unittest.TestCase):
    def test_five_layers_manifest_and_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章。林溪出场。\n")
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
            context = ws.build_context(project, 2, query="旧地图", budget_chars=4000)
            self.assertIn("【L1", context["text"])
            self.assertIn("【L5", context["text"])
            layer_names = {layer["layer"] for layer in context["manifest"]["layers"]}
            self.assertEqual(layer_names, {"L1", "L2", "L3", "L4", "L5"})
            self.assertGreater(context["manifest"]["tokens"], 0)
            self.assertTrue(any(item["kind"] == "retrieval" for item in context["manifest"]["items"]))
            stored = ws.latest_manifest(project, 2)
            self.assertIsNotNone(stored)
            self.assertEqual(stored["chapter_id"], 2)
            # 极小预算也不能砍掉 L1 铁律
            tight = ws.build_context(project, 2, query="旧地图", budget_chars=80)
            self.assertIn("不能在第一章揭晓凶手", tight["text"])


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
