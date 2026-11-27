"""Adversarial probes for ``integration.outline_editor`` (v0.8 wave 2).

Tests decorated with :func:`defect` encode behaviour required by plan
``01_自由编辑_版本契约与多文件大纲设计.md`` (tombstone/chapter_rev authority,
single-writer limits, 500 KB cap).  On the current branch they fail; each
docstring names the defect and its priority.  Run with
``ADVERSARIAL_STRICT=1`` to see them as ordinary failures::

    ADVERSARIAL_STRICT=1 PYTHONPATH=backend python3 -m unittest \
        integration.test_outline_editor_adversarial -v

Without that variable they are ``expectedFailure`` so the suite stays green
while the defect list remains executable and self-documenting.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from fanqie_auto_publish import publication_safety as safety
from integration import outline_editor as oe

STRICT = os.environ.get("ADVERSARIAL_STRICT") == "1"


def defect(case):
    """All listed defects were fixed in this branch; keep the marker readable."""
    return case


def make_project(folder) -> Path:
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / "大纲").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def plan_markdown(rows, tombstones=()) -> str:
    """Build an ``AI规划-*.md`` with hidden chapter metadata + visible rows."""
    chapters = [
        {"id": row["id"], "title": row.get("title", ""),
         "outline": row.get("outline", ""), "chapter_rev": row.get("chapter_rev", 1)}
        for row in rows
    ]
    chapters.extend(
        {"id": number, "deleted": True, "chapter_rev": rev}
        for number, rev in tombstones
    )
    payload = {"schema_version": 2, "chapters": chapters}
    comment = "<!-- novel-plan:" + json.dumps(payload, ensure_ascii=False) + " -->\n\n"
    visible = "\n\n".join(
        f"## 第{row['id']}章 {row.get('title', '')}".rstrip() + "\n" + row.get("outline", "")
        for row in rows
    )
    return comment + visible + ("\n" if visible else "")


def write_plan(project, name, rows, tombstones=()) -> Path:
    path = project / "大纲" / name
    path.write_text(plan_markdown(rows, tombstones), encoding="utf-8", newline="\n")
    return path


class DuplicateAuthorityTest(unittest.TestCase):
    def test_duplicate_chapter_equal_rev_is_conflict_not_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            first = write_plan(project, "AI规划-0001-0001.md",
                              [{"id": 1, "title": "开端", "outline": "版本A", "chapter_rev": 5}])
            second = write_plan(project, "AI规划-0001-0002.md",
                               [{"id": 1, "title": "开端", "outline": "版本B", "chapter_rev": 5}])
            before = (first.read_bytes(), second.read_bytes())
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "版本A")
            self.assertTrue(any(item["kind"] == "duplicate_chapter"
                                for item in recovered["conflicts"]))
            self.assertEqual((first.read_bytes(), second.read_bytes()), before)
            self.assertEqual(oe.recover_plan(project)["chapters"]["1"]["outline"], "版本A")

    def test_duplicate_chapter_higher_rev_wins_and_reports_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            write_plan(project := make_project(folder), "AI规划-0001-0001.md",
                       [{"id": 1, "title": "开端", "outline": "旧", "chapter_rev": 1}])
            write_plan(project, "AI规划-0001-0002.md",
                       [{"id": 1, "title": "开端", "outline": "新", "chapter_rev": 9}])
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "新")
            self.assertTrue(any(item["kind"] == "duplicate_chapter"
                                for item in recovered["conflicts"]))


class TombstoneTest(unittest.TestCase):
    def test_tombstone_survives_external_visible_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = write_plan(project, "AI规划-0001-0002.md", [
                {"id": 1, "title": "开端", "outline": "一", "chapter_rev": 1},
                {"id": 2, "title": "转折", "outline": "二", "chapter_rev": 1}])
            revision = oe.read_file(project, path.name)["revision"]
            oe.write_file(project, path.name, content="## 第1章 开端\n一\n",
                          revision=revision, confirm_removed_chapters=[2])
            raw = path.read_text(encoding="utf-8")
            path.write_text(raw.replace("## 第1章 开端\n一\n", "## 第1章 开端\n一改\n"),
                            encoding="utf-8", newline="\n")
            recovered = oe.recover_plan(project)
            self.assertEqual(sorted(recovered["chapters"]), ["1"])
            self.assertEqual(recovered["chapters"]["1"]["outline"], "一改")
            self.assertTrue(any(item["kind"] == "visible_text_edited"
                                for item in recovered["conflicts"]))

    @defect
    def test_tombstone_is_not_resurrected_from_stale_duplicate_file(self):
        """DEFECT P1: a tombstone in file A loses to a stale live copy in file B.

        ``_merge_chapters`` pops a tombstoned key while scanning its own file,
        then a later file simply re-adds the same chapter.  Deleted chapters
        therefore resurrect from an old duplicate without any conflict and
        without comparing ``chapter_rev``.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            write_plan(project, "AI规划-0001-0001.md", [], [(1, 2)])
            write_plan(project, "AI规划-0001-0002.md",
                       [{"id": 1, "title": "开端", "outline": "陈旧副本", "chapter_rev": 1}])
            recovered = oe.recover_plan(project)
            self.assertNotIn("1", recovered["chapters"])
            self.assertFalse(any(item["kind"] == "duplicate_chapter"
                                 for item in recovered["conflicts"]))

    @defect
    def test_stale_tombstone_does_not_delete_newer_live_chapter(self):
        """DEFECT P1: an old tombstone silently deletes a higher-rev live chapter.

        With file A (live ch1, rev 9) sorted before file B (tombstone ch1,
        rev 2), ``_merge_chapters`` pops ch1 unconditionally when it reaches B.
        The plan requires tombstone comparison by ``chapter_rev``; here the
        stale deletion wins over a much newer authored outline with no conflict.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            write_plan(project, "AI规划-0001-0001.md",
                       [{"id": 1, "title": "开端", "outline": "最新细纲", "chapter_rev": 9}])
            write_plan(project, "AI规划-0001-0002.md", [], [(1, 2)])
            recovered = oe.recover_plan(project)
            self.assertIn("1", recovered["chapters"])
            self.assertEqual(recovered["chapters"]["1"]["outline"], "最新细纲")
            self.assertEqual(recovered["chapters"]["1"]["chapter_rev"], 9)

    @defect
    def test_readding_deleted_chapter_via_write_file(self):
        """DEFECT P1: a chapter cannot be re-added after deletion.

        ``write_file`` appends every old tombstone after the new live rows.
        ``_merge_chapters`` builds ``embedded_rows`` as a last-wins dict, so the
        tombstone overwrites the freshly authored chapter and pops it again.
        The response even reports ``chapter_revs['2']`` while ``recover_plan``
        omits chapter 2.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = write_plan(project, "AI规划-0001-0002.md", [
                {"id": 1, "title": "开端", "outline": "一", "chapter_rev": 1},
                {"id": 2, "title": "转折", "outline": "二", "chapter_rev": 1}])
            revision = oe.read_file(project, path.name)["revision"]
            oe.write_file(project, path.name, content="## 第1章 开端\n一\n",
                          revision=revision, confirm_removed_chapters=[2])
            revision = oe.read_file(project, path.name)["revision"]
            saved = oe.write_file(
                project, path.name,
                content="## 第1章 开端\n一\n\n## 第2章 转折\n二改\n",
                revision=revision)
            recovered = oe.recover_plan(project)
            self.assertIn("2", recovered["chapters"])
            self.assertEqual(recovered["chapters"]["2"]["outline"], "二改")
            # Re-adding must outrank the tombstone rev 2, so the new live rev
            # is 3 rather than 2 (A-P2-09).
            self.assertEqual(saved["chapter_revs"].get("2"), 3)

    @defect
    def test_deleting_whole_plan_file_reports_missing_source(self):
        """DEFECT P2: deleting an AI plan file is not reported as a conflict.

        After ``recover_plan`` persisted chapters 1/2, deleting the single
        authoritative file makes the next rebuild silently wipe both chapters
        (``conflicts == []``).  ``conflicts()`` can spot the stale index before
        recovery, but startup recovery destroys that evidence; the
        ``outline_file_missing`` branch in ``conflicts`` is dead code because
        every plan file is by construction present in ``_all_files``.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = write_plan(project, "AI规划-0001-0002.md", [
                {"id": 1, "title": "开端", "outline": "一", "chapter_rev": 2},
                {"id": 2, "title": "转折", "outline": "二", "chapter_rev": 1}])
            oe.recover_plan(project)
            path.unlink()
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"], {})
            kinds = [item["kind"] for item in recovered["conflicts"]]
            self.assertTrue(any("missing" in kind for kind in kinds), kinds)


class FileSafetyTest(unittest.TestCase):
    def test_corrupt_first_line_json_still_recovers_visible_text(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = project / "大纲" / "AI规划-0001-0001.md"
            path.write_text(
                "<!-- novel-plan:{broken json -->\n\n## 第1章 开端\n正文\n",
                encoding="utf-8", newline="\n")
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "正文")
            self.assertTrue(any(item["kind"] == "plan_comment_missing"
                                for item in recovered["conflicts"]))

    def test_external_visible_edit_then_stale_write_is_409(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = write_plan(project, "AI规划-0001-0001.md",
                              [{"id": 1, "title": "开端", "outline": "旧", "chapter_rev": 1}])
            revision = oe.read_file(project, path.name)["revision"]
            path.write_text(path.read_text(encoding="utf-8").replace("旧", "外部改"),
                            encoding="utf-8", newline="\n")
            before = path.read_bytes()
            with self.assertRaises(oe.OutlineError) as caught:
                oe.write_file(project, path.name,
                              content="## 第1章 开端\n接口改\n", revision=revision)
            self.assertEqual(caught.exception.code, "outline_conflict")
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(path.read_bytes(), before)

    def test_unicode_emoji_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            oe.create_file(project, filename="AI规划-0001-0001.md")
            content = "## 第1章 开端😀\n细纲🎭「引号」\n"
            saved = oe.write_file(project, "AI规划-0001-0001.md", content=content)
            read = oe.read_file(project, "AI规划-0001-0001.md")
            self.assertEqual(read["content"].strip(), content.strip())
            self.assertEqual(saved["revision"], read["revision"])
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["title"], "开端😀")
            self.assertEqual(recovered["chapters"]["1"]["outline"], "细纲🎭「引号」")

    @defect
    def test_500kb_limit_accounts_for_hidden_comment(self):
        """DEFECT P2: the 500 KB cap only measures the visible body.

        ``write_file`` accepts a body just below ``MAX_FILE_BYTES`` and then
        duplicates the whole outline into the hidden ``<!-- novel-plan:... -->``
        comment, producing a file of almost 1 MB (verified 1,024,258 bytes on
        the current branch).  This defeats the stated per-file limit and doubles
        the I/O/memory for every near-cap outline.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            oe.create_file(project, filename="大.md")
            heading = "## 第1章 开端\n"
            body = heading + "a" * (oe.MAX_FILE_BYTES - len(heading.encode()) - 10)
            self.assertLessEqual(len(body.encode("utf-8")), oe.MAX_FILE_BYTES)
            try:
                oe.write_file(project, "大.md", content=body)
            except oe.OutlineError as exc:
                self.assertEqual(exc.status, 413)
                return
            self.assertLessEqual((project / "大纲" / "大.md").stat().st_size,
                                 oe.MAX_FILE_BYTES)

    def test_symlink_in_outline_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            secret = Path(folder) / "secret.md"
            secret.write_text("外部内容\n", encoding="utf-8")
            link = project / "大纲" / "链接.md"
            link.symlink_to(secret)
            with self.assertRaises(oe.OutlineError) as caught:
                oe.read_file(project, "链接.md")
            self.assertEqual(caught.exception.code, "path_escape")
            with self.assertRaises(oe.OutlineError):
                oe.write_file(project, "链接.md", content="覆盖\n")
            self.assertEqual(secret.read_text(encoding="utf-8"), "外部内容\n")
            self.assertNotIn("链接.md", {row["name"] for row in oe.files(project)["files"]})

    @defect
    def test_create_file_rejects_nul_content(self):
        """DEFECT P2: ``create_file`` bypasses the NUL guard used by write_file.

        All outline writes must reject ``\\x00`` per plan §3.3; ``write_file``
        does, but ``create_file`` writes the byte into the Markdown file.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            try:
                oe.create_file(project, filename="坏.md", content="a\x00b")
            except oe.OutlineError as exc:
                self.assertEqual(exc.code, "invalid_content")
            else:
                self.fail("create_file accepted NUL content")

    @defect
    def test_write_meta_rejects_nul_and_non_integer_revision(self):
        """DEFECT P2: meta fields accept NUL and a string revision raises ValueError.

        ``write_meta`` does not validate field characters, and
        ``int(expected_meta_revision)`` escapes as a bare ValueError (500)
        instead of a stable 400/409.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            oe.write_meta(project, {"master_outline": "初始"})
            try:
                oe.write_meta(project, {"master_outline": "a\x00b"})
            except oe.OutlineError:
                pass
            else:
                self.fail("write_meta accepted NUL content")
            try:
                oe.write_meta(project, {"master_outline": "x"},
                              expected_meta_revision="not-an-int")
            except oe.OutlineError:
                pass
            except Exception as exc:  # noqa: BLE001
                self.fail(f"non-integer revision leaked {type(exc).__name__}: {exc}")
            else:
                self.fail("non-integer revision was accepted")

    @defect
    def test_meta_lock_contention_maps_to_409(self):
        """DEFECT P1: a busy outline lock leaks ``PublicationBlocked`` (500).

        ``write_meta`` (and ``write_file``/``write_lore``) uses the same
        non-blocking ``file_lock``; concurrent writers receive a raw runtime
        error instead of ``meta_conflict`` / 409, and the API guard does not
        translate it.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            oe.write_meta(project, {"master_outline": "初始"})
            revision = oe.load_meta(project)["meta_revision"]
            lock_path = project / ".webnovel" / "locks" / "outline.lock"
            ready, release = threading.Event(), threading.Event()

            def holder():
                with safety.file_lock(lock_path):
                    ready.set()
                    release.wait(5)

            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(ready.wait(5))
            try:
                try:
                    oe.write_meta(project, {"master_outline": "并发"},
                                  expected_meta_revision=revision)
                except oe.OutlineError as exc:
                    self.assertEqual(exc.status, 409)
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"leaked {type(exc).__name__}: {exc}")
                else:
                    self.fail("concurrent meta write succeeded")
            finally:
                release.set()
                thread.join(5)

    @defect
    def test_em_dash_arrow_does_not_create_false_conflict(self):
        """DEFECT P2: ``—>`` is rewritten to ``-->`` when reading hidden JSON.

        ``_strip_plan_comment`` applies ``raw.replace("—>", "-->")`` to the
        JSON payload, so any outline containing an em-dash arrow is stored
        differently from the visible text and permanently reports
        ``visible_text_edited`` after every save.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            path = write_plan(project, "AI规划-0001-0001.md",
                              [{"id": 1, "title": "开端", "outline": "旧", "chapter_rev": 1}])
            revision = oe.read_file(project, path.name)["revision"]
            oe.write_file(project, path.name,
                          content="## 第1章 开端\n箭头—>然后\n", revision=revision)
            recovered = oe.recover_plan(project)
            self.assertEqual(recovered["chapters"]["1"]["outline"], "箭头—>然后")
            self.assertFalse(any(item["kind"] == "visible_text_edited"
                                 for item in recovered["conflicts"]))

    @defect
    def test_corrupt_story_plan_meta_is_domain_error(self):
        """DEFECT P2: corrupt meta JSON leaks ``PublicationBlocked`` from every API.

        ``load_meta`` uses ``safety.read_json_strict`` without wrapping it, so
        ``files``/``write_meta``/``recover_plan`` surface a runtime error (500)
        rather than ``story_plan_meta_corrupt``.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            meta = project / ".webnovel" / "story_plan_meta.json"
            meta.write_text("{bad", encoding="utf-8")
            for call in (lambda: oe.files(project),
                         lambda: oe.write_meta(project, {"master_outline": "x"})):
                try:
                    call()
                except oe.OutlineError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"leaked {type(exc).__name__}: {exc}")
                else:
                    self.fail("corrupt meta was accepted")


class MetaAndManualTest(unittest.TestCase):
    def test_meta_concurrent_writers_expected_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            first = oe.write_meta(project, {"master_outline": "一"},
                                  expected_meta_revision=1)
            self.assertEqual(first["meta"]["meta_revision"], 2)
            with self.assertRaises(oe.OutlineError) as caught:
                oe.write_meta(project, {"master_outline": "二"},
                              expected_meta_revision=1)
            self.assertEqual(caught.exception.code, "meta_conflict")
            self.assertEqual(caught.exception.status, 409)
            second = oe.write_meta(project, {"master_outline": "二"},
                                   expected_meta_revision=2)
            self.assertEqual(second["meta"]["meta_revision"], 3)
            self.assertEqual(oe.recover_plan(project)["master_outline"], "二")

    def test_story_plan_rebuild_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            write_plan(project, "AI规划-0001-0001.md",
                       [{"id": 1, "title": "开端", "outline": "一", "chapter_rev": 2}])
            oe.write_meta(project, {"master_outline": "总纲"})
            first = oe.recover_plan(project)
            story = project / ".webnovel" / "story_plan.json"
            story.unlink()
            second = oe.recover_plan(project)
            third = oe.recover_plan(project)
            self.assertTrue(story.is_file())
            self.assertEqual(first["chapters"], second["chapters"])
            self.assertEqual(second["chapters"], third["chapters"])
            self.assertEqual(first["meta_revision"], third["meta_revision"])

    def test_manual_outline_write_does_not_alter_ai_chapters(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            write_plan(project, "AI规划-0001-0001.md",
                       [{"id": 1, "title": "开端", "outline": "AI细纲", "chapter_rev": 1}])
            oe.write_meta(project, {"master_outline": "总纲"})
            oe.create_file(project, filename="卷一.md", content="人工卷纲\n")
            before = oe.recover_plan(project)["chapters"]
            oe.write_file(project, "卷一.md",
                          content="人工卷纲\n\n## 第9章 外部章节\n不得进入索引\n")
            after = oe.recover_plan(project)["chapters"]
            self.assertEqual(before, after)
            self.assertEqual(after["1"]["outline"], "AI细纲")
            self.assertNotIn("9", after)

    def test_lore_traversal_reserved_names_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            for name in ("../x.md", "CON.md", "x .md", "..", ".md", "a\\b.md"):
                with self.subTest(name=name):
                    with self.assertRaises(oe.OutlineError):
                        oe.write_lore(project, name, content="x")
            outside = Path(folder) / "secret.md"
            outside.write_text("secret\n", encoding="utf-8")
            (project / "设定").mkdir(exist_ok=True)
            (project / "设定" / "链接.md").symlink_to(outside)
            with self.assertRaises(oe.OutlineError) as caught:
                oe.write_lore(project, "链接.md", content="覆盖")
            self.assertEqual(caught.exception.code, "path_escape")
            self.assertEqual(outside.read_text(encoding="utf-8"), "secret\n")
            saved = oe.write_lore(project, "世界观.md", content="境界：炼气、筑基\n")
            self.assertEqual(oe.read_lore(project, "世界观.md")["content"],
                             "境界：炼气、筑基\n")
            self.assertTrue(saved["revision"])


if __name__ == "__main__":
    unittest.main()
