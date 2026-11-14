"""人物档案、关系与认知：离线测试，不调用模型。"""
import hashlib
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from integration import character_state as people

BODY = "林舟在码头等到黄昏。\n\n沈青说：“怀表停在七点二十。”\n"


def _id():
    return uuid.uuid4().hex


class CharacterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir()
        (self.root / ".webnovel").mkdir()
        (self.root / "正文" / "第1章-测试.md").write_text(BODY, encoding="utf-8", newline="\n")
        self.sha = hashlib.sha256((self.root / "正文" / "第1章-测试.md").read_bytes()).hexdigest()
        self.reviewed = mock.patch.object(people.writer, "reviewed_chapters", return_value={1: {}})
        self.reviewed.start()

    def tearDown(self):
        self.reviewed.stop()
        self.tmp.cleanup()

    def test_two_aliases_resolve_to_one_person(self):
        first = people.upsert_person(self.root, name="林舟", aliases=["阿舟"])["person"]
        self.assertEqual(people.resolve(self.root, "阿舟"), first["id"])
        again = people.upsert_person(self.root, name="林舟", aliases=["舟哥"])["person"]
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(sorted(again["aliases"]), ["舟哥", "阿舟"])

    def test_alias_collision_is_refused(self):
        people.upsert_person(self.root, name="林舟", aliases=["阿舟"])
        people.upsert_person(self.root, name="沈青")
        with self.assertRaises(ValueError) as caught:
            people.upsert_person(self.root, name="沈青", aliases=["阿舟"])
        self.assertIn("别名已被其他人物使用", str(caught.exception))
        self.assertEqual(len(people.read(self.root)["persons"]), 2)

    def test_different_people_are_not_merged(self):
        left = people.upsert_person(self.root, name="林舟")["person"]
        right = people.upsert_person(self.root, name="林舟的哥哥")["person"]
        self.assertNotEqual(left["id"], right["id"])
        self.assertEqual(people.resolve(self.root, "林舟"), left["id"])

    def test_knowledge_requires_learning_event(self):
        person = people.upsert_person(self.root, name="沈青")["person"]
        people.learn(self.root, person=person["id"], info="怀表停在七点二十", chapter=1,
                     event="沈青看到怀表", quote="怀表停在七点二十。", sha256=self.sha)
        before = people.knows(self.root, person["id"], 1)
        self.assertEqual(before["confirmed"], [])
        after = people.knows(self.root, person["id"], 3)
        self.assertEqual(len(after["confirmed"]), 1)
        self.assertEqual(after["confirmed"][0]["chapter"], 1)

    def test_guess_is_not_confirmed(self):
        person = people.upsert_person(self.root, name="沈青")["person"]
        people.learn(self.root, person=person["id"], info="林舟隐瞒了时间", chapter=1,
                     event="沈青起疑", scope="character", status="guess",
                     quote="怀表停在七点二十。", sha256=self.sha)
        view = people.knows(self.root, person["id"], 3)
        self.assertEqual(view["confirmed"], [])
        self.assertEqual(len(view["guess"]), 1)
        text = people.context(self.root, 3, ["沈青"])["text"]
        self.assertIn("猜疑（未证实）", text)

    def test_author_correction_wins_and_survives_candidates(self):
        person = people.upsert_person(self.root, name="林舟")["person"]
        people.correct(self.root, person["id"], field="goal", value="找回失踪的妹妹", reason="作者设定")
        review = {"character_candidates": [{"kind": "person", "name": "林舟", "field": "goal",
                                            "value": "复仇", "quote": "林舟在码头等到黄昏。"}]}
        self.assertEqual(people.save_candidates(self.root, 1, review, self.sha)["count"], 1)
        people.commit_candidates(self.root, 1, self.sha)
        profile = people.read(self.root)["persons"][person["id"]]["profile"]
        self.assertEqual(profile["goal"], "找回失踪的妹妹")
        self.assertEqual(people.read(self.root)["persons"][person["id"]]["overrides"]["goal"]["reason"], "作者设定")

    def test_duplicate_candidate_commit_has_no_side_effects(self):
        people.upsert_person(self.root, name="林舟")
        people.upsert_person(self.root, name="沈青")
        review = {"character_candidates": [
            {"kind": "relation", "source": "林舟", "target": "沈青", "relation": "互相试探",
             "event": "码头偶遇", "quote": "林舟在码头等到黄昏。"},
            {"kind": "knowledge", "person": "沈青", "info": "怀表停在七点二十", "event": "看到怀表",
             "quote": "怀表停在七点二十。", "scope": "character", "status": "confirmed"},
        ]}
        people.save_candidates(self.root, 1, review, self.sha)
        first = people.commit_candidates(self.root, 1, self.sha)
        self.assertEqual(first["added"]["relations"], 1)
        self.assertEqual(first["added"]["knowledge"], 1)
        second = people.commit_candidates(self.root, 1, self.sha)
        self.assertEqual(second["status"], "reused")
        doc = people.read(self.root)
        self.assertEqual(len(doc["relations"]), 1)
        self.assertEqual(len(doc["knowledge"]), 1)

    def test_relation_change_has_event_and_chapter(self):
        people.upsert_person(self.root, name="林舟")
        people.upsert_person(self.root, name="沈青")
        result = people.relate(self.root, source="林舟", target="沈青", kind="信任下降", direction="one-way",
                               chapter=1, event="发现对方隐瞒", quote="沈青说：“怀表停在七点二十。”", sha256=self.sha)
        self.assertEqual(result["status"], "saved")
        view = people.view(self.root, 2)
        row = next(x for x in view["persons"] if x["name"] == "林舟")
        self.assertEqual(row["relations"][0]["event"], "发现对方隐瞒")
        self.assertEqual(row["relations"][0]["other_name"], "沈青")

    def test_unknown_fields_stay_unknown(self):
        people.upsert_person(self.root, name="林舟", profile={"identity": "码头工人"})
        row = people.view(self.root, 1)["persons"][0]
        self.assertEqual(row["profile"]["identity"], "码头工人")
        self.assertEqual(row["profile"]["motive"], "")
        self.assertIn("motive", row["unknown"])

    def test_candidate_quote_must_come_from_body(self):
        people.upsert_person(self.root, name="林舟")
        review = {"character_candidates": [{"kind": "person", "name": "林舟", "field": "goal",
                                            "value": "复仇", "quote": "正文里没有这句话。"}]}
        result = people.save_candidates(self.root, 1, review, self.sha)
        self.assertEqual(result["count"], 0)
        import json
        stored = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(stored["dropped"][0]["reason"], "quote_not_in_body")

    def test_context_only_includes_wanted_people(self):
        people.upsert_person(self.root, name="林舟", profile={"identity": "码头工人"})
        people.upsert_person(self.root, name="沈青", profile={"identity": "记者"})
        text = people.context(self.root, 2, ["林舟"])["text"]
        self.assertIn("林舟", text)
        self.assertNotIn("沈青", text)


if __name__ == "__main__":
    unittest.main()
