"""多文件大纲：双轨权威、修订号、墓碑、外部编辑与独立资料夹。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import outline_editor as oe


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / "大纲").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def plan_text(chapters, master="总纲", rev=0):
    payload = {
        "schema_version": 2,
        "master_outline": master,
        "volumes": "第一卷",
        "character_arcs": "女主成长",
        "foreshadowing": "旧地图",
        "chapters": [{"id": c["id"], "title": c["title"], "outline": c["outline"],
                      "key_scene": c.get("key_scene", False), "chapter_rev": re.get("chapter_rev", rev)}
                     for c, re in zip(chapters, chapters)],
        "updated_at": "2026-11-26T00:00:00+00:00",
    }
    comment = "<!-- novel-plan:" + json.dumps(payload, ensure_ascii=False) + " -->\n\n"
    return comment + "\n\n".join(f"## 第{c['id']}章 {c['title']}\n{c['outline']}" for c in chapters)


class OutlineFilesTest(unittest.TestCase):
    def test_files_and_read_strip_hidden_comment(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            (project / "大纲" / "总纲.md").write_text("全书总纲\n", encoding="utf-8", newline="\n")
            (project / "大纲" / "AI规划-0001-0002.md").write_text(
                plan_text([{"id": 1, "title": "开端", "outline": "第一章细纲", "chapter_rev": 2},
                           {"id": 2, "title": "转折", "outline": "第二章细纲", "chapter_rev": 1}]),
                encoding="utf-8", newline="\n")
            listing = oe.files(project)
            names = {row["name"] for row in listing["files"]}
            self.assertEqual(names, {"总纲.md", "AI规划-0001-0002.md"})
            ai = next(row for row in listing["files"] if row["name"].startswith("AI规划"))
            self.assertEqual(ai["chapter_range"], [1, 2])
            self.assertEqual(ai["chapter_revs"], {"1": 2, "2": 1})
            read = oe.read_file(project, "AI规划-0001-0002.md")
            self.assertNotIn("novel-plan", read["content"])
            self.assertIn("## 第1章 开端", read["content"])

    def test_meta_is_single_authority_and_conflict_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            first = oe.write_meta(project, {"master_outline": "总纲一", "volumes": "卷一"},
                                  expected_meta_revision=1)
            self.assertEqual(first["meta"]["meta_revision"], 2)
            self.assertEqual(oe.recover_plan(project)["master_outline"], "总纲一")
            with self.assertRaises(oe.OutlineError) as caught:
                oe.write_meta(project, {"master_outline": "总纲二"}, expected_meta_revision=1)
            self.assertEqual(caught.exception.code, "meta_conflict")
            second = oe.write_meta(project, {"master_outline": "总纲二"}, expected_meta_revision=2)
            self.assertEqual(second["meta"]["meta_revision"], 3)
            story = json.loads((project / ".webnovel" / "story_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(story["master_outline"], "总纲二")

    def test_write_file_increments_rev_and_recovers_after_index_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = project / "大纲" / "AI规划-0001-0002.md"
            path.write_text(plan_text([{"id": 1, "title": "开端", "outline": "旧结局"},
                                       {"id": 2, "title": "转折", "outline": "第二章"}], rev=1),
                            encoding="utf-8", newline="\n")
            revision = oe.read_file(project, path.name)["revision"]
            content = "## 第1章 开端\n新结局\n\n## 第2章 转折\n第二章改"
            saved = oe.write_file(project, path.name, content=content, revision=revision)
            self.assertEqual(saved["chapter_revs"]["1"], 2)
            self.assertEqual(saved["chapter_revs"]["2"], 2)
            # 模拟写完 .md 后、写 story_plan.json 前崩溃
            (project / ".webnovel" / "story_plan.json").unlink()
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "新结局")

    def test_missing_heading_requires_confirmation_and_tombstones(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = project / "大纲" / "AI规划-0001-0002.md"
            path.write_text(plan_text([{"id": 1, "title": "开端", "outline": "第一章"},
                                       {"id": 2, "title": "转折", "outline": "第二章"}], rev=3),
                            encoding="utf-8", newline="\n")
            revision = oe.read_file(project, path.name)["revision"]
            content = "## 第1章 开端\n第一章改"
            with self.assertRaises(oe.OutlineError) as caught:
                oe.write_file(project, path.name, content=content, revision=revision)
            self.assertEqual(caught.exception.code, "missing_chapter_headings")
            self.assertEqual(caught.exception.detail["missing_chapters"], [2])
            saved = oe.write_file(project, path.name, content=content, revision=revision,
                                  confirm_removed_chapters=[2])
            self.assertEqual(saved["tombstones"], [2])
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "第一章改")
            self.assertNotIn("2", recovered["chapters"])

    def test_duplicate_chapter_prefers_higher_rev_and_reports_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            (project / "大纲" / "AI规划-0001-0001.md").write_text(
                plan_text([{"id": 1, "title": "开端", "outline": "版本A"}], rev=1),
                encoding="utf-8", newline="\n")
            (project / "大纲" / "AI规划-0001-0001-副本.md").write_text(
                plan_text([{"id": 1, "title": "开端", "outline": "版本B"}], rev=5),
                encoding="utf-8", newline="\n")
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "版本B")
            self.assertTrue(any(item["kind"] == "duplicate_chapter" for item in recovered["conflicts"]))

    def test_external_edit_is_authoritative_and_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = project / "大纲" / "AI规划-0001-0001.md"
            path.write_text(plan_text([{"id": 1, "title": "开端", "outline": "旧细纲"}], rev=1),
                            encoding="utf-8", newline="\n")
            # 外部编辑器只改可见正文，不动首行 JSON
            raw = path.read_text(encoding="utf-8")
            head, _, visible = raw.partition("\n\n")
            path.write_text(head + "\n\n" + visible.replace("旧细纲", "作者手改的新结局"),
                            encoding="utf-8", newline="\n")
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "作者手改的新结局")
            self.assertTrue(any(item["kind"] == "visible_text_edited" for item in recovered["conflicts"]))

    def test_lore_folder_is_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            oe.write_lore(project, "世界观.md", content="境界：炼气、筑基\n")
            self.assertEqual(oe.read_lore(project, "世界观.md")["content"], "境界：炼气、筑基\n")
            self.assertEqual(oe.lore_files(project)["files"][0]["name"], "世界观.md")
            self.assertEqual(oe.files(project)["files"], [])

    def test_windows_and_traversal_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            for name in ("CON.md", "aux.md", "nul.txt", "第1章 .md", "第1章..md", "../x.md", "子目录/x.md"):
                with self.assertRaises(oe.OutlineError):
                    oe.create_file(project, filename=name)

    def test_manual_outline_never_touches_ai_chapter_index(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            (project / "大纲" / "AI规划-0001-0001.md").write_text(
                plan_text([{"id": 1, "title": "开端", "outline": "AI细纲"}], rev=1),
                encoding="utf-8", newline="\n")
            oe.write_meta(project, {"master_outline": "总纲"})
            oe.create_file(project, filename="卷一.md", content="人工卷纲")
            before = oe.recover_plan(project)["chapters"]
            oe.write_file(project, "卷一.md", content="人工卷纲改")
            after = oe.recover_plan(project)["chapters"]
            self.assertEqual(before, after)
            self.assertEqual(after["1"]["outline"], "AI细纲")


class LegacyListChaptersTest(unittest.TestCase):
    def test_list_shaped_legacy_plan_is_normalized_at_every_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            legacy = {
                "schema_version": 1,
                "master_outline": "旧总纲",
                "chapters": [
                    {"id": 1, "title": "开端", "outline": "第一章细纲-旧版", "key_scene": True},
                    {"id": 2, "title": "转折", "outline": "第二章细纲-旧版"},
                ],
            }
            (project / ".webnovel" / "story_plan.json").write_text(
                json.dumps(legacy, ensure_ascii=False), encoding="utf-8", newline="\n")
            payload = {"schema_version": 1, "chapters": [
                {"id": 1, "title": "开端", "outline": "AI第一章", "chapter_rev": 1},
                {"id": 2, "title": "转折", "outline": "AI第二章", "chapter_rev": 1},
            ]}
            plan = "<!-- novel-plan:" + json.dumps(payload, ensure_ascii=False) + " -->\n\n"
            plan += "## 第1章 开端\nAI第一章\n\n## 第2章 转折\nAI第二章\n"
            path = project / "大纲" / "AI规划-0001-0002.md"
            path.write_text(plan, encoding="utf-8", newline="\n")

            files = oe.files(project)
            self.assertEqual(len(files["files"]), 1)
            meta = oe.load_meta(project)
            self.assertEqual(sorted(meta["legacy_chapters"]), ["1", "2"])
            self.assertEqual(len(oe.conflicts(project)), 0)

            recovered = oe.recover_plan(project)
            self.assertEqual(sorted(recovered["chapters"]), ["1", "2"])
            self.assertEqual(recovered["chapters"]["1"]["outline"], "AI第一章")

            oe.write_meta(project, {"volumes": "第一卷"})
            story = json.loads((project / ".webnovel" / "story_plan.json")
                               .read_text(encoding="utf-8"))
            self.assertEqual(sorted(story["chapters"]), ["1", "2"])
            self.assertEqual(story["chapters"]["1"]["outline"], "AI第一章")

            revision = oe.read_file(project, path.name)["revision"]
            saved = oe.write_file(project, path.name,
                                  content="## 第1章 开端\n改过的细纲\n\n## 第2章 转折\nAI第二章\n",
                                  revision=revision)
            self.assertEqual(saved["status"], "saved")
            self.assertEqual(saved["chapter_revs"]["1"] >= 2, True)


if __name__ == "__main__":
    unittest.main()
