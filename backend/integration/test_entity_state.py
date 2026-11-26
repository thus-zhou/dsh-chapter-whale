"""C01 有来源实体状态：钥匙归属链、同章歧义、故事时间、全知不越界、跨作品隔离。"""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from integration import entity_state as es

Q = "他把钥匙放进袖袋，铜环磕出一声轻响。"
SHA = {n: hashlib.sha256(Q.encode("utf-8")).hexdigest() for n in range(1, 12)}


class EntityStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / ".webnovel").mkdir(parents=True)
        (self.project / "正文").mkdir()
        for n in range(1, 12):
            (self.project / "正文" / f"第{n}章.md").write_text(Q, encoding="utf-8")

    def seed_key(self):
        es.record_item(self.project, entity="黄铜钥匙", holder="林砚", chapter=1, quote=Q, sha256=SHA[1],
                       event="第1章：林砚在码头收下钥匙", knowers=["林砚"], discovery="narrated")
        es.record_item(self.project, entity="黄铜钥匙", holder="阿澜", chapter=3, quote=Q, sha256=SHA[3],
                       event="第3章：交给阿澜", knowers=["林砚", "阿澜"])
        es.record_item(self.project, entity="黄铜钥匙", holder="林砚", chapter=8, quote=Q, sha256=SHA[8],
                       event="第8章：阿澜归还", knowers=["林砚", "阿澜"])

    def test_key_holder_at_chapter_2_5_9(self):
        self.seed_key()
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 2)["holder"], "林砚")
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 5)["holder"], "阿澜")
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 9)["holder"], "林砚")

    def test_before_first_record_is_unknown_not_absent(self):
        self.seed_key()
        result = es.holder_at(self.project, "黄铜钥匙", 1)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "no_record_before_chapter")

    def test_same_chapter_two_holders_is_unknown_with_candidates(self):
        es.record_item(self.project, entity="玉佩", holder="甲", chapter=4, quote=Q, sha256=SHA[4], event="甲拿到")
        es.record_item(self.project, entity="玉佩", holder="乙", chapter=4, quote=Q, sha256=SHA[5], event="乙拿到")
        result = es.holder_at(self.project, "玉佩", 5)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "same_chapter_order_unknown")
        self.assertEqual({item["holder"] for item in result["candidates"]}, {"甲", "乙"})

    def test_flashback_uses_story_time(self):
        es.record_item(self.project, entity="信", holder="沈序", chapter=5, quote=Q, sha256=SHA[6],
                       event="第5章回忆二十年前", story_time="2005-03-01T08:00:00")
        es.record_item(self.project, entity="信", holder="沈序母亲", chapter=5, quote=Q, sha256=SHA[7],
                       event="第5章回忆二十年前更早", story_time="2003-03-01T08:00:00")
        self.assertEqual(es.holder_at(self.project, "信", 6, story_time="2004-01-01T00:00:00")["holder"], "沈序母亲")
        self.assertEqual(es.holder_at(self.project, "信", 6)["status"], "unknown", "同章无故事时间即先后不明")

    def test_transfer_requires_current_holder(self):
        self.seed_key()
        with self.assertRaises(ValueError) as ctx:
            es.transfer(self.project, entity="黄铜钥匙", from_holder="阿澜", to_holder="林砚", chapter=2,
                        quote=Q, sha256=SHA[9])
        self.assertIn("林砚", str(ctx.exception))
        saved = es.transfer(self.project, entity="黄铜钥匙", from_holder="林砚", to_holder="阿澜", chapter=2,
                            quote=Q, sha256=SHA[9], event="第2章：暂交阿澜保管", knowers=["阿澜"])
        self.assertEqual(saved["status"], "saved")
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 3)["holder"], "阿澜")

    def test_guess_is_not_confirmed(self):
        es.record_item(self.project, entity="刀", holder="影卫", chapter=2, quote=Q, sha256=SHA[2],
                       event="林砚猜测刀在影卫手里", status="guess", discovery="inferred")
        self.assertEqual(es.holder_at(self.project, "刀", 3)["confidence"], "guess")

    def test_omniscient_narration_is_not_character_knowledge(self):
        es.record_item(self.project, entity="黄铜钥匙", holder="林砚", chapter=1, quote=Q, sha256=SHA[1],
                       event="叙述者告知", scope="narrator", knowers=["林砚"])
        result = es.item_knowledge(self.project, "林砚", "黄铜钥匙", 2)
        self.assertEqual(result["status"], "unknown")
        es.record_item(self.project, entity="黄铜钥匙", holder="林砚", chapter=2, quote=Q, sha256=SHA[2],
                       event="林砚亲手接过", knowers=["林砚"])
        self.assertEqual(es.item_knowledge(self.project, "林砚", "黄铜钥匙", 3)["status"], "known")

    def test_future_knowledge_is_not_visible(self):
        es.record_item(self.project, entity="钥匙", holder="甲", chapter=6, quote=Q, sha256=SHA[6],
                       event="第6章才知道", knowers=["乙"])
        self.assertEqual(es.item_knowledge(self.project, "乙", "钥匙", 4)["status"], "unknown")
        self.assertEqual(es.item_knowledge(self.project, "乙", "钥匙", 7)["status"], "known")

    def test_same_name_across_projects_do_not_merge(self):
        other = Path(self.temp.name) / "other"
        (other / ".webnovel").mkdir(parents=True)
        (other / "正文").mkdir()
        (other / "正文" / "第1章.md").write_text(Q, encoding="utf-8")
        es.record_item(self.project, entity="钥匙", holder="林砚", chapter=1, quote=Q, sha256=SHA[1], event="本作")
        es.record_item(other, entity="钥匙", holder="程野", chapter=1, quote=Q, sha256=SHA[1], event="另一本")
        self.assertEqual(es.holder_at(self.project, "钥匙", 2)["holder"], "林砚")
        self.assertEqual(es.holder_at(other, "钥匙", 2)["holder"], "程野")

    def test_duplicate_event_is_reused(self):
        first = es.record_item(self.project, entity="钥匙", holder="林砚", chapter=1, quote=Q, sha256=SHA[1], event="交接")
        again = es.record_item(self.project, entity="钥匙", holder="林砚", chapter=1, quote=Q, sha256=SHA[1], event="交接")
        self.assertEqual(again["status"], "reused")
        self.assertEqual(len(es.read(self.project)["events"]), 1)
        self.assertEqual(first["event"]["id"], again["event"]["id"])

    def test_view_reports_unknown_and_pending(self):
        self.seed_key()
        view = es.view(self.project, 5)
        self.assertEqual(view["items"][0]["current"]["holder"], "阿澜")
        self.assertEqual(view["events"], 3)
        view_late = es.view(self.project, 0)
        self.assertEqual(view_late["items"][0]["holder"], "林砚")
        json.dumps(view, ensure_ascii=False)

    def test_view_without_chapter_does_not_trust_last_write(self):
        es.record_item(self.project, entity="玉佩", holder="甲", chapter=4, quote=Q, sha256=SHA[4], event="甲拿到")
        es.record_item(self.project, entity="玉佩", holder="乙", chapter=4, quote=Q, sha256=SHA[5], event="乙拿到")
        ambiguous = es.holder_at(self.project, "玉佩", 5)
        self.assertEqual(ambiguous["status"], "unknown")
        view = es.view(self.project, 0)
        current = view["items"][0]["current"]
        self.assertEqual(current["status"], "unknown")
        self.assertEqual(current["reason"], "same_chapter_order_unknown")
        self.assertEqual(view["horizon"], 5)

    def test_transfer_refuses_guessed_holder(self):
        es.record_item(self.project, entity="黄铜钥匙", holder="林砚", chapter=1, quote=Q, sha256=SHA[1],
                       event="第1章：听说钥匙在林砚手里", status="guess", discovery="inferred")
        with self.assertRaises(ValueError) as raised:
            es.transfer(self.project, entity="黄铜钥匙", from_holder="林砚", to_holder="阿澜", chapter=3,
                        quote=Q, sha256=SHA[3], event="第3章：转交")
        self.assertIn("猜测", str(raised.exception))
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 9)["status"], "known")
        self.assertEqual(len(es.read(self.project)["events"]), 1)

    def test_evidence_is_required(self):
        with self.assertRaises(ValueError):
            es.record_item(self.project, entity="钥匙", holder="林砚", chapter=1, quote="", sha256=SHA[1])
        with self.assertRaises(ValueError):
            es.record_item(self.project, entity="钥匙", holder="林砚", chapter=1, quote=Q, sha256="short")

    def test_changed_or_missing_body_invalidates_holder_and_knowledge(self):
        self.seed_key()
        path = self.project / "正文" / "第3章.md"
        path.write_text("阿澜没有接过钥匙。", encoding="utf-8")
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 5)["reason"], "source_changed")
        self.assertEqual(es.item_knowledge(self.project, "阿澜", "黄铜钥匙", 5)["status"], "unknown")
        path.unlink()
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 5)["status"], "unknown")
        self.assertEqual(len(es.read(self.project)["events"]), 3)

    def test_reextraction_of_changed_chapter_restores_current_facts(self):
        self.seed_key()
        text = "阿澜把钥匙交给沈序。"
        (self.project / "正文/第3章.md").write_text(text, encoding="utf-8")
        es.record_item(self.project, entity="黄铜钥匙", holder="沈序", chapter=3,
                       quote=text, sha256=hashlib.sha256(text.encode()).hexdigest(), knowers=["阿澜"])
        self.assertEqual(es.holder_at(self.project, "黄铜钥匙", 5)["holder"], "沈序")
        self.assertEqual(es.item_knowledge(self.project, "阿澜", "黄铜钥匙", 5)["holder_at_event"], "沈序")

    def test_holder_rows_are_compact_and_mark_unknown(self):
        self.seed_key()
        rows = es.holder_rows(self.project, 5)
        self.assertEqual(len(rows), 1)
        self.assertIn("阿澜", rows[0])
        self.assertIn("第3章", rows[0])
        early = es.holder_rows(self.project, 1)
        self.assertIn("未知", early[0])


if __name__ == "__main__":
    unittest.main()
