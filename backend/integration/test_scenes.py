"""场景卡与分场景生成：离线测试，模型调用全部用桩替代。"""
import asyncio
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from integration import scene_writer, scenes, writer_runner


class ScenesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir()
        (self.root / ".webnovel").mkdir()
        (self.root / ".webnovel" / "story_plan.json").write_text(json.dumps({
            "chapters": [{"id": 1, "title": "第一章", "outline": "林舟来到码头。他等了一整天。黄昏时怀表停了。沈青留下字条。"}],
        }, ensure_ascii=False), encoding="utf-8", newline="\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_derives_cards_without_model(self):
        planned = scenes.plan(self.root, 1, count=2, word_count=2000)
        self.assertEqual(planned["source"], "derived")
        self.assertEqual(len(planned["cards"]), 2)
        self.assertEqual([c["id"] for c in planned["cards"]], ["s1", "s2"])
        total = sum(c["target_chars"] for c in planned["cards"])
        self.assertTrue(1600 <= total <= 2400)

    def test_plan_prefers_author_supplied_cards(self):
        path = self.root / ".webnovel" / "story_plan.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["chapters"][0]["scenes"] = [
            {"purpose": "林舟等到黄昏", "target_chars": 1000, "calm": True},
            {"purpose": "怀表停摆", "target_chars": 1000},
        ]
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8", newline="\n")
        planned = scenes.plan(self.root, 1, count=2, word_count=2000)
        self.assertEqual(planned["source"], "plan")
        self.assertTrue(planned["cards"][0]["calm"])

    def test_validation_rejects_bad_cards(self):
        with self.assertRaises(ValueError):
            scenes.validate([], 2000)
        bad = [{"id": "s1", "target_chars": 1000}, {"id": "s1", "target_chars": 1000}]
        with self.assertRaises(ValueError):
            scenes.validate(bad, 2000)
        with self.assertRaises(ValueError):
            scenes.validate([{"id": "s1", "target_chars": 100}], 5000)

    def test_store_and_stale_detection(self):
        planned = scenes.plan(self.root, 1, count=2, word_count=2000)
        scenes.store(self.root, 1, planned)
        loaded = scenes.load(self.root, 1)
        self.assertFalse(loaded["stale"])
        path = self.root / ".webnovel" / "story_plan.json"
        path.write_text(json.dumps({"chapters": [{"id": 1, "outline": "改写后的细纲。"}]}, ensure_ascii=False),
                        encoding="utf-8", newline="\n")
        self.assertTrue(scenes.load(self.root, 1)["stale"])

    def _draft(self, responses, count=2):
        calls = []

        async def fake(role, prompt, **kwargs):
            calls.append(prompt)
            return responses[len(calls) - 1]

        with mock.patch.object(scene_writer.model_roles, "json_call", side_effect=fake):
            result = asyncio.run(scene_writer.draft(self.root, 1, 2000, count))
        return result, calls

    def test_two_scenes_compose_and_resume(self):
        result, calls = self._draft([{"text": "第一场正文。" * 20}, {"text": "第二场正文。" * 20}])
        self.assertEqual(result["requests"], 2)
        self.assertEqual([s["reused"] for s in result["scenes"]], [False, False])
        self.assertTrue(result["content"].startswith("第一场正文"))
        self.assertLess(result["content"].index("第一场"), result["content"].index("第二场"))
        again, calls2 = self._draft([], count=2)
        self.assertEqual(again["requests"], 0)
        self.assertEqual([s["reused"] for s in again["scenes"]], [True, True])
        self.assertEqual(calls2, [])
        self.assertEqual(again["content"], result["content"])

    def test_failure_keeps_completed_scene(self):
        class Boom(RuntimeError):
            pass

        calls = []

        async def fake(role, prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return {"text": "第一场正文。" * 20}
            raise Boom("第二场请求失败")

        with mock.patch.object(scene_writer.model_roles, "json_call", side_effect=fake):
            with self.assertRaises(Boom):
                asyncio.run(scene_writer.draft(self.root, 1, 2000, 2))
        files = list((self.root / ".webnovel" / "scenes").glob("0001-*-s1.json"))
        self.assertEqual(len(files), 1)
        resumed, calls2 = self._draft([{"text": "第二场正文。" * 20}], count=2)
        self.assertEqual(resumed["requests"], 1)
        self.assertEqual([s["reused"] for s in resumed["scenes"]], [True, False])

    def test_estimate_counts_review(self):
        self.assertEqual(scene_writer.estimate(2)["requests"], 3)
        self.assertEqual(scene_writer.estimate(9)["scenes"], 3)

    def test_writer_accepts_scene_mode(self):
        import inspect
        self.assertEqual(inspect.signature(writer_runner._generate_and_review).parameters["scenes"].default, 0)
        self.assertEqual(inspect.signature(writer_runner.generate_chapter_async).parameters["scenes"].default, 0)


    def test_dict_shaped_story_plan_is_understood(self):
        """真实规划把 chapters 写成 {章号: {...}}；场景卡读取不能只认列表。"""
        path = self.root / ".webnovel" / "story_plan.json"
        path.write_text(json.dumps({
            "chapters": {"2": {"id": 2, "title": "送表的邮差", "outline": "沈砚核对字迹。林禾再次送信。"}},
        }, ensure_ascii=False), encoding="utf-8", newline="\n")
        cards = scenes.plan(self.root, 2, count=1, word_count=800)
        self.assertEqual(len(cards["cards"]), 1)


if __name__ == "__main__":
    unittest.main()
