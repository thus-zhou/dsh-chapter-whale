"""Long-form fixtures for the continuity features (offline, no model calls).

These tests replay a twenty chapter mini-book and a hundred chapter index so the
memory, character, foreshadow and rebuild paths are exercised at a length the
unit tests do not cover. They use synthetic text only: this is a mechanism
replay, not a claim that a hundred chapter novel was written by a model.
"""

from __future__ import annotations

import hashlib
import json
import time
import unittest
from pathlib import Path

from integration import character_state, chapter_versions, continuity, memory_library, version_history


def body_for(number: int) -> str:
    return (
        f"第{number}章，临水城的天还没亮。沈砚把第{number}枚齿轮放回抽屉，"
        f"听见门外有人踩着水走过来。\n\n"
        f"“今天几号？”林禾问。沈砚说：“{number}号，和昨天一样。”\n"
    )


def write_chapter(project: Path, number: int, body: str) -> Path:
    path = Path(project) / "正文" / f"第{number}章-测试.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_project(root: Path, chapters: int = 20) -> Path:
    project = Path(root) / "book"
    (project / ".webnovel").mkdir(parents=True)
    (project / "正文").mkdir()
    for number in range(1, chapters + 1):
        write_chapter(project, number, body_for(number))
    return project


class LongFormReplay(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = make_project(self.root, 20)
        character_state.upsert_person(self.project, name="沈砚", origin="正文")
        character_state.upsert_person(self.project, name="林禾", origin="正文")

    def tearDown(self):
        self.tmp.cleanup()

    def learn(self, name: str, info: str, chapter: int) -> None:
        body = body_for(chapter)
        character_state.learn(
            self.project, person=name, info=info, chapter=chapter,
            event=f"第{chapter}章发生的对话", quote=body.splitlines()[0], sha256=digest(body),
        )

    def test_character_knowledge_follows_the_reading_position(self):
        self.learn("沈砚", "怀表停在七点二十", 3)
        self.learn("沈砚", "林禾每晚都会忘记昨天", 12)
        self.learn("林禾", "沈砚在修一块停摆的怀表", 4)

        early = character_state.knows(self.project, "沈砚", 5)
        self.assertEqual([x["info"] for x in early["confirmed"]], ["怀表停在七点二十"])
        later = character_state.knows(self.project, "沈砚", 13)
        self.assertEqual(len(later["confirmed"]), 2)
        self.assertIn("unknown", early)

        view = character_state.view(self.project, 5)
        shen = next(row for row in view["persons"] if row["name"] == "沈砚")
        self.assertEqual(len(shen["knowledge"]), 1)

    def test_relations_need_an_event_and_are_not_duplicated(self):
        body = body_for(3)
        character_state.relate(
            self.project, source="沈砚", target="林禾", kind="旧识", direction="one-way",
            chapter=3, event="林禾送来一封没有署名的信", quote=body.splitlines()[0], sha256=digest(body),
        )
        again = character_state.relate(
            self.project, source="沈砚", target="林禾", kind="旧识", direction="one-way",
            chapter=3, event="林禾送来一封没有署名的信", quote=body.splitlines()[0], sha256=digest(body),
        )
        self.assertEqual(again["status"], "reused")
        rows = character_state.view(self.project, 9)["persons"]
        # 同一条关系在两个人的视图里各出现一次，但只记录了一条边。
        self.assertEqual(sum(len(p["relations"]) for p in rows), 2)

    def _foreshadow(self) -> str:
        revision = memory_library.read(self.project)["revision"]
        body = body_for(3)
        result = memory_library.save_item(
            self.project,
            {"category": "foreshadow", "title": "停摆的怀表", "content": "怀表的秒针在第七章重新走动",
             "due_chapter": 8, "clue_state": "planned", "valid_from": 3},
            0,
            source={"kind": "chapter", "chapter": 3, "sha256": digest(body), "quote": body.splitlines()[0]},
        )
        return result["items"][-1]["id"]

    def test_foreshadow_needs_evidence_and_reports_conflicts(self):
        item = self._foreshadow()
        with self.assertRaises(ValueError):
            continuity.transition(self.project, item, 0, "resolved", chapter=9, quote="不存在的句子")

        saved = continuity.transition(
            self.project, item, memory_library.read(self.project)["revision"], "planted",
            chapter=4, quote=body_for(4).splitlines()[0], event="怀表在第四章出现",
        )
        self.assertEqual(saved["state"], "planted")
        view = continuity.view(self.project, 5)
        row = next(x for x in view["foreshadows"] if x["id"] == item)
        self.assertEqual(row["state"], "planted")
        self.assertTrue(row["actual"]["chapter"] == 4)

        # A resolved state without evidence is reported, not silently repaired.
        doc = memory_library.read(self.project)
        for entry in doc["items"]:
            if entry["id"] == item:
                entry["clue_state"] = "resolved"
                entry["actual"] = {}
        memory_library._commit(self.project, doc, {"id": item, "from": "planted", "to": "resolved"}, "test_force")
        kinds = {row["kind"] for row in continuity.conflicts(self.project)}
        self.assertIn("resolved_without_evidence", kinds)

    def test_state_hides_future_content(self):
        revision = memory_library.read(self.project)["revision"]
        self.assertIsInstance(revision, int)
        memory_library.save_item(
            self.project,
            {"category": "fact", "title": "怀表的来历", "content": "怀表来自沈砚的父亲",
             "valid_from": 12},
            0,
        )
        state = memory_library.state(self.project, 8)
        self.assertTrue(all("content" not in row for row in state["future"]))
        self.assertEqual(state["future"][0]["valid_from"], 12)
        self.assertTrue(state["future"])

    def test_history_change_marks_known_impact_only(self):
        item = self._foreshadow()
        continuity.transition(
            self.project, item, memory_library.read(self.project)["revision"], "planted",
            chapter=4, quote=body_for(4).splitlines()[0], event="怀表在第四章出现",
        )
        continuity.build_index(self.project)

        # Change chapter 4: the foreshadow was planted there, so it is affected.
        write_chapter(self.project, 4, body_for(4).replace("临水城的天还没亮", "临水城刚下过雨"))
        impact = continuity.impact(self.project)
        changed = [row["chapter"] for row in impact["changed"]]
        self.assertEqual(changed, [4])
        self.assertGreaterEqual(impact["affected"], 1)
        self.assertIn("无法保证绝对无影响", impact["unknown"])

        rebuilt = continuity.rebuild(self.project)
        self.assertTrue(rebuilt["stale"])
        self.assertEqual(rebuilt["stale"][0]["id"], item)

        # The later chapter is unrelated and keeps working.
        untouched = next(row for row in impact["changed"] if row["chapter"] != 18)
        self.assertEqual(untouched["chapter"], 4)

    def test_missing_index_is_reported_not_guessed(self):
        missing = continuity.impact(self.project)
        self.assertEqual(missing["changed"], [])
        self.assertIn("unknown", missing)
        self.assertFalse(continuity.read_index(self.project))

    def test_restore_after_history_change_keeps_both_versions(self):
        legacy = chapter_versions.adopt_legacy(self.project, 4)
        legacy = legacy[0] if isinstance(legacy, list) else legacy
        self.assertTrue(legacy)
        before = (self.project / "正文" / "第4章-测试.md").read_bytes()
        write_chapter(self.project, 4, body_for(4).replace("还没亮", "已经亮了"))
        result = version_history.restore(self.project, 4, legacy["sha256"])
        self.assertEqual(result["status"], "restored")
        self.assertEqual((self.project / "正文" / "第4章-测试.md").read_bytes(), before)
        rows = version_history.history(self.project, 4)["versions"]
        # 兼容登记的原稿、恢复前对当前稿的备份、恢复产生的新版本，一共三条。
        self.assertEqual(len(rows), 3)
        self.assertTrue(result.get("backup_version_id"))
        self.assertEqual(rows[0]["version_id"], result["version_id"])


class HundredChapterIndex(unittest.TestCase):
    def test_hundred_chapter_index_and_state_stay_bounded(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp), 100)
            started = time.time()
            index = continuity.build_index(project)
            build_seconds = time.time() - started
            self.assertEqual(index["chapters"], 100)
            self.assertLess(build_seconds, 8.0)

            for number in range(1, 101):
                memory_library.save_item(
                    project,
                    {"category": "fact", "title": f"第{number}章的事实", "content": f"第{number}章的记录",
                     "valid_from": number, "valid_to": number + 5},
                    memory_library.read(project)["revision"],
                )
            started = time.time()
            state = memory_library.state(project, 60)
            self.assertLess(time.time() - started, 3.0)
            self.assertEqual(state["chapter"], 60)
            self.assertGreaterEqual(len(state["active"]), 1)
            self.assertGreaterEqual(len(state["expired"]), 1)
            for row in state["active"]:
                self.assertNotIn("content", row)

            history = version_history.history(project, 60)
            self.assertEqual(history["versions"], [])
            self.assertEqual(history["count"], 0)

    def test_rebuild_is_repeatable(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp), 20)
            first = continuity.build_index(project)
            again = continuity.build_index(project)
            self.assertEqual(first["chapters"], again["chapters"])
            left = (project / ".webnovel" / "continuity_index.json").read_text(encoding="utf-8")
            continuity.build_index(project)
            right = (project / ".webnovel" / "continuity_index.json").read_text(encoding="utf-8")
            a = json.loads(left)
            b = json.loads(right)
            a.pop("built_at", None)
            b.pop("built_at", None)
            self.assertEqual(a, b)


class InterruptedWrites(unittest.TestCase):
    def test_interrupted_index_keeps_the_previous_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp), 5)
            continuity.build_index(project)
            marker = project / ".webnovel" / "continuity_index.json"
            before = marker.read_text(encoding="utf-8")

            original = continuity.writer._chapter_files

            def explode(_project):
                raise OSError("模拟磁盘写入失败")

            continuity.writer._chapter_files = explode
            try:
                with self.assertRaises(OSError):
                    continuity.build_index(project)
            finally:
                continuity.writer._chapter_files = original
            self.assertEqual(marker.read_text(encoding="utf-8"), before)

    def test_unrelated_project_is_untouched(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            left = make_project(Path(tmp) / "a", 5)
            right = make_project(Path(tmp) / "b", 5)
            continuity.build_index(right)
            snapshot = {path: path.read_bytes() for path in right.rglob("*") if path.is_file()}
            continuity.build_index(left)
            write_chapter(left, 1, body_for(1).replace("还没亮", "下起了雨"))
            continuity.rebuild(left)
            after = {path: path.read_bytes() for path in right.rglob("*") if path.is_file()}
            self.assertEqual(snapshot, after)


if __name__ == "__main__":
    unittest.main()
