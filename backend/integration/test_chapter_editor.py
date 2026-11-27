"""自由直写闭环：草稿、正式版本、定稿、回收站、拆合与导入。"""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import workbench_db as wb


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def save(project, chapter, content, title="开端", **extra):
    data = {"title": title, "content": content, "op_id": extra.pop("op_id", f"op-{chapter}-{content[:6]}"),
            "source": "author_edit", "allow_new": extra.pop("allow_new", False)}
    data.update(extra)
    return ce.save_version(project, chapter, data)


def seed(project, chapter=1, content="第一段。\n\n第二段。\n", title="开端"):
    created = ce.new_chapter(project, {"chapter": chapter, "title": title, "content": content,
                                       "op_id": f"new-{chapter}-{uuid.uuid4().hex[:8]}"})
    return created


class DraftTest(unittest.TestCase):
    def test_draft_serialization_and_aba(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            one = ce.save_draft(project, 1, {"title": "开端", "content": "草稿一",
                                             "expected_draft_id": None, "expected_draft_epoch": 0,
                                             "expected_draft_revision": 0})
            draft = one["draft"]
            two = ce.save_draft(project, 1, {"title": "开端", "content": "草稿二",
                                             "expected_draft_id": draft["draft_id"],
                                             "expected_draft_epoch": draft["draft_epoch"],
                                             "expected_draft_revision": draft["draft_revision"]})
            with self.assertRaises(ce.ChapterError) as caught:
                ce.save_draft(project, 1, {"title": "开端", "content": "平板旧稿",
                                           "expected_draft_id": draft["draft_id"],
                                           "expected_draft_epoch": draft["draft_epoch"],
                                           "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(caught.exception.code, "draft_conflict")
            self.assertEqual(caught.exception.detail["current_draft"]["content"], "草稿二")
            self.assertEqual(two["draft"]["draft_revision"], 2)

            # 丢弃后重建：epoch 继续递增，旧 draft_id 不能复用
            ce.discard_draft(project, 1)
            with self.assertRaises(ce.ChapterError):
                ce.save_draft(project, 1, {"title": "开端", "content": "旧设备",
                                           "expected_draft_id": draft["draft_id"],
                                           "expected_draft_epoch": draft["draft_epoch"],
                                           "expected_draft_revision": 2})
            three = ce.save_draft(project, 1, {"title": "开端", "content": "新草稿",
                                               "expected_draft_id": None, "expected_draft_epoch": 2,
                                               "expected_draft_revision": 0})
            self.assertEqual(three["draft"]["draft_epoch"], 3)

    def test_ctrl_s_preserves_newer_typing(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            draft = ce.save_draft(project, 1, {"title": "开端", "content": "提交前的稿",
                                               "expected_draft_id": None, "expected_draft_epoch": 0,
                                               "expected_draft_revision": 0})["draft"]
            newer = ce.save_draft(project, 1, {"title": "开端", "content": "提交后继续打字",
                                               "expected_draft_id": draft["draft_id"],
                                               "expected_draft_epoch": draft["draft_epoch"],
                                               "expected_draft_revision": draft["draft_revision"]})["draft"]
            state = ce.chapter_state(project, 1)
            result = save(project, 1, "提交前的稿", op_id="ctrl-s",
                          expected_version_id=state["version_id"],
                          expected_content_sha256=state["sha256"],
                          submitted_draft_id=draft["draft_id"],
                          submitted_draft_epoch=draft["draft_epoch"],
                          submitted_draft_revision=draft["draft_revision"])
            self.assertTrue(result["draft_preserved"])
            self.assertEqual(wb.get_draft(project, 1)["content"], "提交后继续打字")
            self.assertEqual(newer["draft_revision"], 2)


class SaveVersionTest(unittest.TestCase):
    def test_expected_version_is_mandatory_for_existing_chapter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            with self.assertRaises(ce.ChapterError) as caught:
                save(project, 1, "改稿", op_id="op-1")
            self.assertEqual(caught.exception.code, "expected_version_required")

    def test_save_detects_external_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            cv.chapter_path(project, 1).write_text("外部编辑器改过\n", encoding="utf-8", newline="\n")
            with self.assertRaises(ce.ChapterError) as caught:
                save(project, 1, "我的新稿", op_id="op-x",
                     expected_version_id=state["version_id"],
                     expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "concurrent_modification")
            self.assertEqual(cv.chapter_path(project, 1).read_text(encoding="utf-8"), "外部编辑器改过\n")

    def test_unchanged_save_does_not_create_version(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            before = len(cv.list_versions(project, 1))
            result = save(project, 1, state["content"], op_id="op-same",
                          expected_version_id=state["version_id"],
                          expected_content_sha256=state["sha256"])
            self.assertTrue(result["unchanged"])
            self.assertEqual(len(cv.list_versions(project, 1)), before)

    def test_title_change_renames_file_and_updates_version(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            result = save(project, 1, state["content"], title="雨夜测绘图", op_id="op-title",
                          expected_version_id=state["version_id"],
                          expected_content_sha256=state["sha256"])
            self.assertTrue(result.get("renamed"))
            self.assertEqual(cv.chapter_path(project, 1).name, "第1章-雨夜测绘图.md")
            self.assertEqual(cv.current_version(project, 1)["title"], "雨夜测绘图")
            self.assertNotEqual(cv.current_version(project, 1)["version_id"], state["version_id"])

    def test_idempotent_op_id_does_not_duplicate_version(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            first = save(project, 1, "新正文\n", op_id="same-op",
                         expected_version_id=state["version_id"],
                         expected_content_sha256=state["sha256"])
            before = len(cv.list_versions(project, 1))
            second = save(project, 1, "新正文\n", op_id="same-op",
                          expected_version_id=state["version_id"],
                          expected_content_sha256=state["sha256"])
            self.assertTrue(second.get("reused"))
            self.assertEqual(first["content_sha256"], second["content_sha256"])
            self.assertEqual(len(cv.list_versions(project, 1)), before)
            with self.assertRaises(ce.ChapterError) as caught:
                save(project, 1, "另一篇\n", op_id="same-op",
                     expected_version_id=state["version_id"],
                     expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "op_id_params_mismatch")

    def test_legacy_bom_crlf_is_snapshotted_before_first_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            original = "\ufeff旧稿第一行\r\n旧稿第二行\r\n".encode("utf-8")
            (project / "正文" / "第1章-旧稿.md").write_bytes(original)
            state = ce.chapter_state(project, 1)
            self.assertEqual(state["sha256"], cv.raw_sha256(original))
            save(project, 1, "新稿\n", title="旧稿", op_id="legacy-save",
                 expected_version_id=None, expected_content_sha256=state["sha256"])
            # 原稿已作为 v1 逐字节归档，恢复后 BOM 与 CRLF 一字不差
            first = cv.list_versions(project, 1)[0]
            self.assertEqual(first["source"], "legacy-adopted")
            self.assertEqual(first["sha256"], cv.raw_sha256(original))
            cv.restore_version(project, 1, first["version_id"], op_id="legacy-restore")
            self.assertEqual((project / "正文" / "第1章-旧稿.md").read_bytes(), original)

    def test_author_confirm_and_revoke(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            confirmed = ce.author_confirm(project, 1, {
                "expected_version_id": state["version_id"],
                "expected_content_sha256": state["sha256"], "op_id": "confirm-1"})
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertTrue(ce.chapter_state(project, 1)["review_state"]["author_confirmed"])
            self.assertTrue(ce.chapter_state(project, 1)["review_state"]["publish_eligible"])

            # 改标题立即失效
            save(project, 1, state["content"], title="新标题", op_id="op-retitle",
                 expected_version_id=state["version_id"],
                 expected_content_sha256=state["sha256"])
            review = ce.chapter_state(project, 1)["review_state"]
            self.assertTrue(review["author_confirmed"])
            self.assertFalse(review["publish_eligible"])

            revoked = ce.revoke_author_confirm(project, 1)
            self.assertTrue(revoked["changed"])
            self.assertFalse(ce.chapter_state(project, 1)["review_state"]["author_confirmed"])


class DestructiveEditTest(unittest.TestCase):
    def test_delete_tail_then_restore_renumbered(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章\n")
            seed(project, 2, "第二章\n", title="第二章")
            listed = ce.list_trash(project)
            self.assertEqual(listed["entries"], [])
            chapter2 = ce.chapter_state(project, 2)
            deleted = ce.delete_chapter(project, 2, expected_content_sha256=chapter2["sha256"])
            self.assertEqual(deleted["status"], "deleted")
            self.assertEqual(sorted(cv.chapter_map(project)), [1])
            # 新建第 2 章后还原旧第 2 章：自动顺延为第 3 章
            seed(project, 2, "新第二章\n", title="新第二章")
            restored = ce.restore_trash(project, deleted["trash_entry"])
            self.assertEqual(restored["chapter_id"], 3)
            self.assertTrue(restored["renumbered"])
            self.assertEqual(cv.read_version(project, 3)["text"], "第二章\n")

    def test_cannot_delete_middle_nonempty_chapter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章\n")
            seed(project, 2, "第二章\n", title="第二章")
            seed(project, 3, "第三章\n", title="第三章")
            with self.assertRaises(ce.ChapterError) as caught:
                ce.delete_chapter(project, 2, expected_content_sha256=ce.chapter_state(project, 2)["sha256"])
            self.assertEqual(caught.exception.code, "only_tail_chapter_deletable")

    def test_split_and_merge_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n\n第二段。\n\n第三段。\n"
            seed(project, 1, text)
            state = ce.chapter_state(project, 1)
            split = ce.split_chapter(project, 1, offset=text.index("第二段"),
                                     expected_content_sha256=state["sha256"])
            self.assertEqual(split["new_chapter_id"], 2)
            merged = ce.merge_tail(project)
            self.assertEqual(merged["chapter_id"], 1)
            self.assertEqual(sorted(cv.chapter_map(project)), [1])

    def test_import_preview_and_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "原创第一章\n")
            raw = "第1章 开端\n正文甲\n第2章 转折\n正文乙\n"
            preview = ce.import_chapters(project, text=raw, preview=True)
            self.assertEqual(preview["count"], 2)
            self.assertEqual(preview["start_chapter"], 2)
            imported = ce.import_chapters(project, text=raw, preview=False, op_id="import-1")
            self.assertEqual(imported["count"], 2)
            self.assertEqual(sorted(cv.chapter_map(project)), [1, 2, 3])
            self.assertIn("正文乙", cv.read_version(project, 3)["text"])


class LocalToolsTest(unittest.TestCase):
    def test_quick_check_is_local_and_finds_issues(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "他说：“走吧。。。”\n\n我突然笑了，突然又停了，不禁冷笑。\n")
            result = ce.quick_check(project, 1)
            self.assertEqual(result["model_calls"], 0)
            self.assertLess(result["elapsed_ms"], 800)
            kinds = {item["type"] for item in result["issues"]}
            self.assertTrue(kinds & {"punctuation_repeat", "quote_unbalanced", "verbal_tics"})

    def test_local_search_finds_two_character_name(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "林溪拿着旧地图。\n\n老周在档案馆等她。\n")
            ce.index_project(project)
            hits = ce.search_project(project, "林溪")
            self.assertEqual(hits["count"], 1)
            self.assertEqual(hits["results"][0]["chapter_id"], 1)

    def test_memory_preview_detects_char_fact_change(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "老周三年前死了。\n")
            state = ce.chapter_state(project, 1)
            save(project, 1, "老周三年前未死。\n", op_id="op-mem",
                 expected_version_id=state["version_id"],
                 expected_content_sha256=state["sha256"])
            preview = ce.sync_memory_preview(project, 1)
            self.assertTrue(preview["needs_badge"])
            self.assertTrue(preview["triggers"])


if __name__ == "__main__":
    unittest.main()
