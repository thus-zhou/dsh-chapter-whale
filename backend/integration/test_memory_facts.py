"""M10：事实来源、有效范围与作者更正。全部离线，不调用模型。"""
import hashlib
import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from integration import bridge, memory_library as mem

BODY = "林舟在码头等到黄昏。\n\n他把怀表停在七点二十。\n"


def _id():
    return uuid.uuid4().hex


def _legacy_item(sha, *, title="林舟：在码头", content="林舟在码头等到黄昏。", quote="林舟在码头等到黄昏。", **extra):
    item = {"id": _id(), "category": "fact", "title": title, "content": content, "pinned": False,
            "status": "active", "due_chapter": 0, "clue_state": "",
            "source": {"kind": "chapter", "chapter": 1, "sha256": sha, "quote": quote},
            "created_at": "2026-11-01T10:00:00+08:00", "updated_at": "2026-11-01T10:00:00+08:00",
            "updated_revision": 0}
    item.update(extra)
    return item


class FactsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "正文").mkdir()
        (self.root / ".webnovel").mkdir()
        (self.root / "正文" / "第1章-测试.md").write_text(BODY, encoding="utf-8", newline="\n")
        self.sha = hashlib.sha256((self.root / "正文" / "第1章-测试.md").read_bytes()).hexdigest()
        self.reviewed = mock.patch.object(mem.writer, "reviewed_chapters", return_value={1: {}})
        self.reviewed.start()

    def tearDown(self):
        self.reviewed.stop()
        self.tmp.cleanup()

    def _write(self, items, revision=0):
        doc = mem.empty()
        doc["revision"] = revision
        doc["items"] = items
        bridge.write_json_atomic(mem._path(self.root), doc)
        return doc

    def test_legacy_memory_stays_readable(self):
        self._write([_legacy_item(self.sha)])
        doc = mem.read(self.root)
        self.assertEqual(len(doc["items"]), 1)
        view = mem.public(self.root)["items"][0]
        self.assertEqual(view["claim"], "body_fact")
        self.assertEqual(view["valid_from"], 1)
        self.assertEqual(view["valid_to"], 0)
        self.assertFalse(view["story_time_known"])
        self.assertEqual(view["freshness"], "current")

    def test_source_lookup_detects_changed_body(self):
        self._write([_legacy_item(self.sha)])
        self.assertEqual(mem.public(self.root)["items"][0]["freshness"], "current")
        (self.root / "正文" / "第1章-测试.md").write_text(BODY + "\n补写一段。\n", encoding="utf-8", newline="\n")
        self.assertEqual(mem.public(self.root)["items"][0]["freshness"], "stale")

    def test_future_records_are_not_exposed(self):
        self._write([_legacy_item(self.sha, valid_from=5)])
        early = mem.state(self.root, 4)
        self.assertEqual(early["active"], [])
        self.assertEqual(early["future"][0]["valid_from"], 5)
        ctx = mem.context(self.root, "B", 4, "林舟")
        self.assertEqual(ctx["ids"], [])
        self.assertEqual(ctx["omitted_breakdown"]["future"], 1)
        self.assertEqual(ctx["restricted"][0], {"reason": "future", "count": 1})
        later = mem.state(self.root, 6)
        self.assertEqual(len(later["active"]), 1)

    def test_expired_records_are_hidden(self):
        self._write([_legacy_item(self.sha, valid_to=2)])
        self.assertEqual(len(mem.state(self.root, 2)["active"]), 1)
        after = mem.state(self.root, 3)
        self.assertEqual(after["active"], [])
        self.assertEqual(after["expired"][0]["valid_to"], 2)

    def test_story_time_keeps_unknown(self):
        self._write([_legacy_item(self.sha),
                     _legacy_item(self.sha, title="林舟：旧伤", content="旧伤未愈。", quote="怀表停在七点二十。",
                                  story_time="第三日黄昏", story_time_known=True)])
        view = mem.state(self.root, 3)
        self.assertIn("第三日黄昏", view["story_time"]["known"])
        self.assertEqual(view["story_time"]["unknown"], 1)

    def _candidates(self):
        return {"fact_candidates": [
            {"title": "林舟：怀表时间", "content": "怀表停在七点二十。", "quote": "怀表停在七点二十。", "claim": "body_fact"},
            {"title": "编造条目", "content": "林舟去了北方。", "quote": "林舟去了北方。"},
        ]}

    def test_candidate_quote_must_come_from_body(self):
        result = mem.save_candidates(self.root, 1, self._candidates(), self.sha)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["dropped"], 1)
        stored = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(stored["dropped"][0]["reason"], "quote_not_in_body")

    def test_duplicate_commit_does_not_duplicate_facts(self):
        result = mem.save_candidates(self.root, 1, self._candidates(), self.sha)
        first = mem.commit_candidates(self.root, 1, self.sha)
        self.assertEqual(first["status"], "committed")
        self.assertEqual(first["added"], 1)
        second = mem.commit_candidates(self.root, 1, self.sha)
        self.assertEqual(second["status"], "reused")
        items = [x for x in mem.read(self.root)["items"] if x["source"]["kind"] == "chapter"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["claim"], "body_fact")
        self.assertEqual(items[0]["valid_from"], 1)

    def test_interrupted_commit_is_recoverable(self):
        mem.save_candidates(self.root, 1, self._candidates(), self.sha)
        (self.root / "正文" / "第1章-测试.md").write_text(BODY + "\n新段落。\n", encoding="utf-8", newline="\n")
        with self.assertRaises(ValueError) as caught:
            mem.commit_candidates(self.root, 1, self.sha)
        self.assertIn("正文已变化", str(caught.exception))
        self.assertEqual(len(mem.pending_candidates(self.root)), 1)
        (self.root / "正文" / "第1章-测试.md").write_text(BODY, encoding="utf-8", newline="\n")
        recovered = mem.commit_candidates(self.root, 1, self.sha)
        self.assertEqual(recovered["status"], "committed")
        self.assertEqual(mem.pending_candidates(self.root), [])

    def test_author_correction_keeps_old_evidence(self):
        mem.save_candidates(self.root, 1, self._candidates(), self.sha)
        mem.commit_candidates(self.root, 1, self.sha)
        doc = mem.read(self.root)
        old = next(x for x in doc["items"] if x["source"]["kind"] == "chapter")
        quote_before = old["source"]["quote"]
        content_before = old["content"]
        result = mem.correct(self.root, old["id"], doc["revision"],
                             {"category": "fact", "title": "林舟：怀表时间", "content": "怀表其实停在七点二十五。",
                              "pinned": False, "valid_to": 0},
                             reason="作者核对原稿")
        items = {x["id"]: x for x in result["items"]}
        self.assertEqual(items[old["id"]]["status"], "superseded")
        self.assertEqual(items[old["id"]]["content"], content_before)
        self.assertEqual(items[old["id"]]["source"]["quote"], quote_before)
        new = items[items[old["id"]]["superseded_by"]]
        self.assertEqual(new["claim"], "author_setting")
        self.assertTrue(new["confirmed_by_author"])
        self.assertEqual(new["supersedes"], old["id"])
        self.assertEqual(new["correction_reason"], "作者核对原稿")
        self.assertEqual([x["content"] for x in mem.contract(self.root)], ["怀表其实停在七点二十五。"])

    def test_context_reports_restricted_ranges(self):
        self._write([_legacy_item(self.sha),
                     _legacy_item(self.sha, title="未来事实", content="尚未发生。", quote="怀表停在七点二十。", valid_from=9)])
        ctx = mem.context(self.root, "B", 3, "林舟")
        reasons = {x["reason"]: x["count"] for x in ctx["restricted"]}
        self.assertEqual(reasons["future"], 1)
        self.assertEqual(ctx["omitted"], ctx["omitted_breakdown"]["future"])
        self.assertEqual([x["title"] for x in ctx["facts"]], ["林舟：在码头"])


if __name__ == "__main__":
    unittest.main()
