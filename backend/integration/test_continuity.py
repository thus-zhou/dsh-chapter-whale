"""伏笔状态、冲突与依赖索引：离线测试，不调用模型。"""
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from integration import continuity, memory_library as memory

BODY = "林舟在码头等到黄昏。\n\n他把怀表停在七点二十。\n"


class ContinuityCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir()
        (self.root / ".webnovel").mkdir()
        self._write_chapter(1, BODY)
        self._write_chapter(2, "沈青翻到这页笔记。\n\n她记下了七点二十。\n")
        self.sha1 = self._sha(1)
        self.sha2 = self._sha(2)
        self.reviewed = mock.patch.object(memory.writer, "reviewed_chapters", return_value={1: {}, 2: {}})
        self.reviewed.start()
        self.revision = memory.read(self.root)["revision"]

    def tearDown(self):
        self.reviewed.stop()
        self.tmp.cleanup()

    def _write_chapter(self, number, text):
        (self.root / "正文" / f"第{number}章-测试.md").write_text(text, encoding="utf-8", newline="\n")

    def _sha(self, number):
        return hashlib.sha256((self.root / "正文" / f"第{number}章-测试.md").read_bytes()).hexdigest()

    def _foreshadow(self, title="怀表的秘密", due=3, content="七点二十这个时间并不普通。"):
        doc = memory.save_item(self.root, {"category": "foreshadow", "title": title, "content": content,
                                           "pinned": False, "status": "active", "due_chapter": due,
                                           "clue_state": "planned", "source_chapter": 0},
                               self.revision)
        return next(x for x in doc["items"] if x["title"] == title)

    def _revision(self):
        return memory.read(self.root)["revision"]

    def test_full_lifecycle_from_plan_to_resolution(self):
        item = self._foreshadow()
        planted = continuity.transition(self.root, item["id"], self._revision(), "planted", chapter=1,
                                        event="怀表首次出现", quote="他把怀表停在七点二十。", sha256=self.sha1)
        self.assertEqual(planted["state"], "planted")
        developing = continuity.transition(self.root, item["id"], self._revision(), "developing", chapter=2,
                                           event="沈青记下时间", quote="她记下了七点二十。", sha256=self.sha2)
        self.assertEqual(developing["state"], "developing")
        resolved = continuity.transition(self.root, item["id"], self._revision(), "resolved", chapter=2,
                                         event="时间含义揭晓", quote="她记下了七点二十。", sha256=self.sha2)
        self.assertEqual(resolved["state"], "resolved")
        self.assertEqual(len(resolved["item"]["transitions"]), 3)
        self.assertEqual([x["chapter"] for x in resolved["item"]["transitions"]], [1, 2, 2])

    def test_no_evidence_cannot_advance(self):
        item = self._foreshadow()
        with self.assertRaises(ValueError) as caught:
            continuity.transition(self.root, item["id"], self._revision(), "planted", chapter=1,
                                  event="口头说已埋设", quote="", sha256=self.sha1)
        self.assertIn("引用该章原文", str(caught.exception))
        with self.assertRaises(ValueError):
            continuity.transition(self.root, item["id"], self._revision(), "planted", chapter=1,
                                  event="章节对不上", quote="他把怀表停在七点二十。", sha256=self.sha2)
        self.assertEqual(memory.read(self.root)["items"][0]["clue_state"], "planned")

    def test_planned_is_not_written_into_body(self):
        item = self._foreshadow()
        view = continuity.view(self.root, 1)
        row = next(x for x in view["foreshadows"] if x["id"] == item["id"])
        self.assertEqual(row["state"], "planned")
        self.assertEqual(row["actual"], {})
        self.assertFalse(row["transitions"])

    def test_overdue_is_reported(self):
        self._foreshadow(due=1)
        rows = continuity.conflicts(self.root)
        self.assertIn("overdue", [x["kind"] for x in rows])

    def test_resolved_without_evidence_is_reported(self):
        item = self._foreshadow(due=0)
        doc = memory.read(self.root)
        doc["items"][0]["clue_state"] = "resolved"
        memory.writer.atomic_json(memory._path(self.root), doc)
        rows = continuity.conflicts(self.root)
        self.assertIn("resolved_without_evidence", [x["kind"] for x in rows])

    def test_body_change_makes_evidence_stale(self):
        item = self._foreshadow()
        continuity.transition(self.root, item["id"], self._revision(), "planted", chapter=1,
                              event="怀表首次出现", quote="他把怀表停在七点二十。", sha256=self.sha1)
        self._write_chapter(1, BODY + "\n补写一句。\n")
        rows = continuity.conflicts(self.root)
        self.assertIn("source_stale", [x["kind"] for x in rows])
        self.assertEqual(len(memory.read(self.root)["items"]), 1, "失效只标记，不删除")

    def test_index_and_impact_keep_unrelated_records(self):
        item = self._foreshadow()
        continuity.transition(self.root, item["id"], self._revision(), "planted", chapter=1,
                              event="怀表首次出现", quote="他把怀表停在七点二十。", sha256=self.sha1)
        self.assertEqual(continuity.build_index(self.root)["chapters"], 2)
        self._write_chapter(2, "沈青翻到这页笔记。\n\n她划掉了那个时间。\n")
        report = continuity.impact(self.root)
        self.assertEqual([x["chapter"] for x in report["changed"]], [2])
        self.assertIn("无法保证绝对无影响", report["unknown"])
        self.assertEqual(len(memory.read(self.root)["items"]), 1)

    def test_rebuild_marks_stale_without_deleting(self):
        item = self._foreshadow()
        continuity.transition(self.root, item["id"], self._revision(), "planted", chapter=1,
                              event="怀表首次出现", quote="他把怀表停在七点二十。", sha256=self.sha1)
        continuity.build_index(self.root)
        self._write_chapter(1, BODY + "\n再补一句。\n")
        result = continuity.rebuild(self.root, 1)
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["stale"][0]["id"], item["id"])
        self.assertEqual(len(memory.read(self.root)["items"]), 1)

    def test_cancel_requires_reason(self):
        item = self._foreshadow()
        with self.assertRaises(ValueError):
            continuity.transition(self.root, item["id"], self._revision(), "cancelled")
        ok = continuity.transition(self.root, item["id"], self._revision(), "cancelled", note="改了主线")
        self.assertEqual(ok["state_label"], "作者取消")


if __name__ == "__main__":
    unittest.main()
