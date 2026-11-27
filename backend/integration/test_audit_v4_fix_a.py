"""Regression tests for the fourth A-domain audit (P2/P3 remediation).

Covers: soft op_id recovery, backup object/rename/evidence completeness,
cross-preview hunks, split/merge annotation migration, outline tombstones,
evidence symlinks, resident backup/restore consistency, undo/apply
transactions and completion-key failures.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integration import annotations as ann
from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import outline_editor as oe
from integration import resident_service as rs
from integration import revision_plan
from integration import text_merge as tm
from integration import transaction_journal as journal
from integration import workbench_db as wb


def make_project(folder) -> Path:
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / "大纲").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def seed(project, chapter: int = 1, text: str = "第一段。\n第二段。\n", title: str = "开端"):
    return cv.commit_raw_bytes(project, chapter, text.encode("utf-8"), title=title,
                               source="test", allow_new=True, action="chapter_new")


def add_annotation(project, chapter: int, text: str, quote: str, *,
                   against: str = "version", instruction: str = "改一下"):
    start = text.index(quote)
    return ann.create_annotation(project, chapter, {
        "scope": "selection", "instruction": instruction, "against": against,
        "anchor": {"char_start": start, "char_end": start + len(quote), "quote": quote}})


def preview_for(project, chapter: int, aid: str, replacement: str, *, op: str,
                output: object = None):
    result = ann.run_annotations(
        project, chapter, {"op_id": op, "annotation_ids": [aid]},
        generate=lambda a, c: (output if output is not None
                               else f"<replacement>{replacement}</replacement>"))
    return result["previews"][0]


def draft_identity(project, chapter: int = 1, content: str = "第一段。\n第二段。\n"):
    draft = wb.get_draft(project, chapter)
    if draft is None:
        draft = wb.save_draft(project, chapter, title="开端", content=content,
                              expected_draft_epoch=0, expected_draft_revision=0)
    return {"draft_id": draft["draft_id"], "draft_epoch": draft["draft_epoch"],
            "draft_revision": draft["draft_revision"]}


def plan_text(chapters):
    payload = {
        "schema_version": 2,
        "chapters": [{"id": c["id"], "title": c["title"], "outline": c["outline"],
                      "chapter_rev": c.get("chapter_rev", 1),
                      **({"deleted": True} if c.get("deleted") else {})}
                     for c in chapters],
        "updated_at": "2026-11-27T00:00:00+00:00",
    }
    comment = "<!-- novel-plan:" + json.dumps(payload, ensure_ascii=False) + " -->\n\n"
    visible = "\n\n".join(f"## 第{c['id']}章 {c['title']}\n{c['outline']}"
                          for c in chapters if not c.get("deleted"))
    return comment + visible + "\n"


class SoftIdempotencyTest(unittest.TestCase):
    def test_new_chapter_retry_recovers_from_authoritative_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            with patch.object(wb, "idempotency_complete", side_effect=RuntimeError("busy")):
                first = ce.new_chapter(project, {"title": "开端", "content": "正文\n",
                                                 "op_id": "new-soft"})
            self.assertEqual(first["status"], "created")
            retried = ce.new_chapter(project, {"title": "开端", "content": "正文\n",
                                               "op_id": "new-soft"})
            self.assertEqual(retried["status"], "created")
            self.assertTrue(retried.get("recovered") or retried.get("reused"))
            self.assertEqual(cv.chapter_map(project).keys(), {1})

    def test_delete_retry_recovers_from_trash_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            meta = seed(project, 2, "二\n")
            sha = cv.file_sha256(cv.chapter_path(project, 2))
            with patch.object(wb, "idempotency_complete", side_effect=RuntimeError("busy")):
                first = ce.delete_chapter(project, 2, expected_version_id=meta["version_id"],
                                          expected_content_sha256=sha, op_id="del-soft")
            self.assertEqual(first["status"], "deleted")
            retried = ce.delete_chapter(project, 2, expected_version_id=meta["version_id"],
                                        expected_content_sha256=sha, op_id="del-soft")
            self.assertEqual(retried["status"], "deleted")
            self.assertEqual(len(ce.list_trash(project)["entries"]), 1)

    def test_merge_retry_recovers_from_commits_and_trash(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "上\n")
            seed(project, 2, "下\n")
            with patch.object(wb, "idempotency_complete", side_effect=RuntimeError("busy")):
                first = ce.merge_tail(project, op_id="merge-soft")
            self.assertEqual(first["status"], "merged")
            retried = ce.merge_tail(project, op_id="merge-soft")
            self.assertEqual(retried["status"], "merged")
            self.assertEqual(len(cv.chapter_map(project)), 1)
            self.assertEqual(len(ce.list_trash(project)["entries"]), 1)


    def test_split_retry_recovers_from_commits(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一段。\n第二段。\n")
            sha = cv.file_sha256(cv.chapter_path(project, 1))
            with patch.object(wb, "idempotency_complete", side_effect=RuntimeError("busy")):
                first = ce.split_chapter(project, 1, offset=len("第一段。\n"),
                                         expected_content_sha256=sha, op_id="split-soft")
            self.assertIn(first["status"], {"split", "partial"})
            retried = ce.split_chapter(project, 1, offset=len("第一段。\n"),
                                       expected_content_sha256=sha, op_id="split-soft")
            self.assertEqual(retried["status"], "split")
            self.assertTrue(retried.get("recovered") or retried.get("reused"))
            self.assertEqual(len(cv.list_versions(project, 1)), 2)
            self.assertEqual(len(cv.list_versions(project, 2)), 1)

    def test_import_retry_recovers_from_commit_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第1章 开端\n一\n\n第2章 转折\n二\n"
            with patch.object(wb, "idempotency_complete", side_effect=RuntimeError("busy")):
                first = ce.import_chapters(project, text=text, preview=False,
                                           op_id="import-soft")
            self.assertEqual(first["status"], "imported")
            retried = ce.import_chapters(project, text=text, preview=False,
                                         op_id="import-soft")
            self.assertEqual(retried["status"], "imported")
            self.assertEqual(retried["count"], 2)
            self.assertEqual(sorted(cv.chapter_map(project)), [1, 2])


class CrossActionAndMergeParamsTest(unittest.TestCase):
    def test_merge_with_reused_op_id_does_not_replay_an_older_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            for number in (1, 2, 3, 4):
                seed(project, number, f"第{number}章正文\n")
            first = ce.merge_tail(project, op_id="merge-params")
            self.assertEqual(first["status"], "merged")
            self.assertEqual(sorted(cv.chapter_map(project)), [1, 2, 3])
            with self.assertRaises(ce.ChapterError) as caught:
                ce.merge_tail(project, op_id="merge-params")
            self.assertEqual(caught.exception.code, "op_id_params_mismatch")
            self.assertEqual(sorted(cv.chapter_map(project)), [1, 2, 3])

    def test_save_cannot_claim_another_action_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            created = ce.new_chapter(project, {"title": "开端", "content": "正文\n",
                                               "op_id": "cross-action"})
            self.assertEqual(created["status"], "created")
            state = ce.chapter_state(project, 1)
            with self.assertRaises(ce.ChapterError) as caught:
                ce.save_version(project, 1, {
                    "title": "开端", "content": "正文\n", "op_id": "cross-action",
                    "expected_version_id": state["version_id"],
                    "expected_content_sha256": state["sha256"]})
            self.assertEqual(caught.exception.code, "op_id_action_mismatch")

    def test_later_save_settles_hunks_left_by_failed_mark_committed(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seeded = seed(project, 1, text)
            aid = add_annotation(project, 1, text, "她推开门。")["id"]
            preview = preview_for(project, 1, aid, "她撞开门。", op="settle-run")
            draft = wb.save_draft(project, 1, title="开端", content=text,
                                  base_version_id=seeded["version_id"],
                                  expected_draft_epoch=0, expected_draft_revision=0)
            ann.apply_hunks(project, 1, {
                "op_id": "settle-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            applied_content = wb.get_draft(project, 1)["content"]
            draft = wb.get_draft(project, 1)
            with patch.object(ann, "mark_committed", side_effect=RuntimeError("busy")):
                first = ce.save_version(project, 1, {
                    "title": "开端", "content": applied_content, "op_id": "settle-save",
                    "expected_version_id": cv.current_version(project, 1)["version_id"],
                    "expected_content_sha256": seeded["content_sha256"],
                    "submitted_draft_id": draft["draft_id"],
                    "submitted_draft_epoch": draft["draft_epoch"],
                    "submitted_draft_revision": draft["draft_revision"]})
            self.assertEqual(first["status"], "saved")
            self.assertTrue(str(first["annotation_settlement"]).startswith("failed"))
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"],
                             "applied_to_draft")
            # A later save with no draft settles the applied hunk.
            ce.save_version(project, 1, {
                "title": "开端", "content": applied_content, "op_id": "settle-later",
                "expected_version_id": cv.current_version(project, 1)["version_id"],
                "expected_content_sha256": cv.file_sha256(cv.chapter_path(project, 1))})
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"],
                             "committed")


class RenameSafetyTest(unittest.TestCase):
    def test_noreplace_rename_does_not_overwrite_external_target(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "第1章-旧.md"
            target = Path(folder) / "第1章-新.md"
            source.write_bytes("源".encode("utf-8"))
            target.write_bytes("外部".encode("utf-8"))
            with self.assertRaises(FileExistsError):
                cv._rename_no_replace(source, target)
            self.assertEqual(target.read_bytes(), "外部".encode("utf-8"))
            self.assertEqual(source.read_bytes(), "源".encode("utf-8"))

    def test_chapter_state_reads_preferred_file_when_duplicate_names_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "索引正文\n", title="旧标题")
            current = cv.current_version(project, 1)
            stale = project / "正文" / "第1章-外部.md"
            stale.write_bytes("外部正文\n".encode("utf-8"))
            state = ce.chapter_state(project, 1)
            self.assertEqual(state["content"], "索引正文\n")
            self.assertIn("第1章-外部.md", state["duplicate_chapter_files"])
            self.assertEqual(state["duplicate_chapter_files_used"], "第1章-旧标题.md")


class BackupCompletenessTest(unittest.TestCase):
    def _versioned(self, project):
        first = seed(project, 1, "第一版\n")
        second = cv.commit_raw_bytes(project, 1, "第二版\n".encode("utf-8"),
                                     title="开端", source="test",
                                     expected_sha256=first["content_sha256"])
        return first, second

    def test_backup_copies_every_index_object_and_detects_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            first, second = self._versioned(project)
            dest = Path(folder) / "备份"
            journal.backup(project, dest)
            objects = dest / ".webnovel" / "chapter_versions" / "objects"
            self.assertTrue((objects / f"{first['content_sha256']}.txt").is_file())
            self.assertTrue((objects / f"{second['content_sha256']}.txt").is_file())
            self.assertTrue(journal.inspect_backup(dest)["valid"])
            (objects / f"{first['content_sha256']}.txt").unlink()
            inspected = journal.inspect_backup(dest)
            self.assertFalse(inspected["valid"])
            self.assertTrue(any(problem.startswith("index_object_missing")
                                for problem in inspected["problems"]))
            with self.assertRaises(journal.TransactionConflict):
                journal.restore_backup(project, dest, confirmed=True)

    def test_backup_reconcile_removes_stale_same_chapter_body(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "旧正文\n", title="旧标题")
            current = cv.commit_raw_bytes(project, 1, "新正文\n".encode("utf-8"),
                                          title="新标题", source="test")
            cv.reconcile_title(project, 1, title="新标题", op_id=current["op_id"])
            dest = Path(folder) / "备份"
            manifest = journal.backup(project, dest)
            # Simulate the copy window: old filename survived the tree copy.
            stale = dest / "正文" / "第1章-旧标题.md"
            stale.write_bytes("旧正文\n".encode("utf-8"))
            document = json.loads((dest / "backup_manifest.json").read_text(encoding="utf-8"))
            document["files"].append({"path": "正文/第1章-旧标题.md", "kind": "file",
                                      "sha256": hashlib.sha256(stale.read_bytes()).hexdigest(),
                                      "size": stale.stat().st_size})
            (dest / "backup_manifest.json").write_text(json.dumps(document), encoding="utf-8")
            self.assertFalse(journal.inspect_backup(dest)["valid"])
            records = document["files"]
            result = journal._reconcile_backup_index(project, dest, records, 5.0)
            self.assertTrue(result["ok"], result)
            self.assertFalse(stale.exists())
            document["files"] = records
            document["count"] = len(records)
            (dest / "backup_manifest.json").write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(journal.inspect_backup(dest)["valid"],
                            journal.inspect_backup(dest)["problems"])

    def test_backup_reconcile_recreates_current_name_after_title_only_rename(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "同样正文\n", title="旧标题")
            current = cv.commit_raw_bytes(project, 1, "同样正文\n".encode("utf-8"),
                                          title="新标题", source="test")
            cv.reconcile_title(project, 1, title="新标题", op_id=current["op_id"])
            dest = Path(folder) / "备份"
            journal.backup(project, dest)
            document = json.loads((dest / "backup_manifest.json").read_text(encoding="utf-8"))
            records = document["files"]
            new_body = dest / "正文" / "第1章-新标题.md"
            old_body = dest / "正文" / "第1章-旧标题.md"
            data = new_body.read_bytes()
            new_body.unlink()
            old_body.write_bytes(data)
            records[:] = [row for row in records if row.get("path") != "正文/第1章-新标题.md"]
            records.append({"path": "正文/第1章-旧标题.md", "kind": "file",
                            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
            result = journal._reconcile_backup_index(project, dest, records, 5.0)
            self.assertTrue(result["ok"], result)
            self.assertTrue(new_body.is_file())
            self.assertFalse(old_body.exists())
            document["files"] = records
            document["count"] = len(records)
            (dest / "backup_manifest.json").write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(journal.inspect_backup(dest)["valid"])

    def test_backup_contains_trash_snapshots_and_revision_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章。\n")
            seed(project, 2, "第二章。\n")
            text = "第一章。\n"
            aid = add_annotation(project, 1, text, "第一章。")["id"]
            preview_for(project, 1, aid, "第一章改。", op="ev-run")
            ce.delete_chapter(project, 2,
                              expected_version_id=cv.current_version(project, 2)["version_id"],
                              expected_content_sha256=cv.file_sha256(cv.chapter_path(project, 2)),
                              op_id="ev-del")
            dest = Path(folder) / "备份"
            journal.backup(project, dest)
            self.assertTrue(any((dest / ".webnovel" / "snapshots").glob("*.txt")))
            self.assertTrue(any((dest / ".webnovel" / "revision_previews").glob("*.json")))
            self.assertTrue(any((dest / ".webnovel" / "trash").glob("*/manifest.json")))
            inspected = journal.inspect_backup(dest)
            self.assertTrue(inspected["valid"], inspected["problems"])
            for folder in (".webnovel/trash", ".webnovel/snapshots",
                           ".webnovel/revision_previews"):
                shutil.rmtree(project / folder, ignore_errors=True)
            journal.restore_backup(project, dest, confirmed=True)
            self.assertTrue(any((project / ".webnovel" / "trash").glob("*/manifest.json")))
            self.assertTrue(any((project / ".webnovel" / "snapshots").glob("*.txt")))
            self.assertEqual(len(ann.list_annotations(project, 1)["annotations"]), 1)
            self.assertNotEqual(ann.list_annotations(project, 1)["annotations"][0]["status"],
                                "relocated_needed")


class CrossPreviewAndSplitTest(unittest.TestCase):
    def test_mixed_preview_baselines_are_rejected_instead_of_silently_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n第二段。\n第三段。\n"
            seed(project, 1, text)
            first = add_annotation(project, 1, text, "第二段。")["id"]
            first_preview = preview_for(project, 1, first, "第二段改。", op="mix-run-1")
            changed = "前言插入。\n" + text
            wb.save_draft(project, 1, title="开端", content=changed,
                          expected_draft_epoch=0, expected_draft_revision=0)
            second = add_annotation(project, 1, changed, "第三段。", against="draft")["id"]
            second_preview = preview_for(project, 1, second, "第三段改。", op="mix-run-2")
            identity = draft_identity(project, content=changed)
            with self.assertRaises(ann.AnnotationError) as caught:
                ann.apply_hunks(project, 1, {
                    "op_id": "mix-apply",
                    "hunk_ids": [first_preview["hunks"][0]["id"], second_preview["hunks"][0]["id"]],
                    "expected_draft_id": identity["draft_id"],
                    "expected_draft_epoch": identity["draft_epoch"],
                    "expected_draft_revision": identity["draft_revision"]})
            self.assertEqual(caught.exception.code, "mixed_base_snapshots")

    def test_split_moves_second_half_annotations(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n第二段。\n"
            seed(project, 1, text)
            aid = add_annotation(project, 1, text, "第二段。")["id"]
            preview_for(project, 1, aid, "第二段改。", op="split-run")
            offset = len("第一段。\n")
            result = ce.split_chapter(project, 1, offset=offset,
                                      expected_content_sha256=cv.file_sha256(
                                          cv.chapter_path(project, 1)), op_id="split-ann")
            self.assertIn(result["status"], {"split", "partial"})
            self.assertEqual(result["annotations_migrated"], 1)
            self.assertEqual(ann.list_annotations(project, 1)["annotations"], [])
            moved = ann.list_annotations(project, 2)["annotations"]
            self.assertEqual(len(moved), 1)
            self.assertEqual(moved[0]["anchor"]["char_start"], 0)
            self.assertEqual(moved[0]["hunks"][0]["chapter_id"], 2)
            self.assertEqual(moved[0]["hunks"][0]["char_start"], 0)

    def test_merge_moves_tail_annotations_onto_previous_chapter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一段。\n")
            seed(project, 2, "第二段。\n")
            aid = add_annotation(project, 2, "第二段。\n", "第二段。")["id"]
            preview_for(project, 2, aid, "第二段改。", op="merge-run")
            merged = ce.merge_tail(project, op_id="merge-ann")
            self.assertEqual(merged["status"], "merged")
            self.assertEqual(merged["annotations_migrated"], 1)
            listing = ann.list_annotations(project, 1)
            self.assertEqual(len(listing["annotations"]), 1)
            item = listing["annotations"][0]
            self.assertEqual(item["id"], aid)
            self.assertEqual(item["relocated"]["status"], "exact")
            self.assertEqual(item["range"]["start"], len("第一段。\n\n"))
            self.assertEqual(item["hunks"][0]["chapter_id"], 1)
            self.assertEqual(item["hunks"][0]["char_start"], len("第一段。\n\n"))


class OutlineTombstoneTest(unittest.TestCase):
    def test_reprinting_copied_tombstone_cannot_delete_readded_chapter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            original = [{"id": 1, "title": "开端", "outline": "一", "chapter_rev": 1},
                        {"id": 2, "title": "转折", "outline": "二", "chapter_rev": 1}]
            path_a = project / "大纲" / "AI规划-0001-0002.md"
            path_a.write_text(plan_text(original), encoding="utf-8", newline="\n")
            revision = oe.read_file(project, path_a.name)["revision"]
            oe.write_file(project, path_a.name, content="## 第1章 开端\n一\n",
                          revision=revision, confirm_removed_chapters=[2])
            # A sync duplicate still carries the tombstone rev 2.
            path_b = project / "大纲" / "AI规划-0001-0002-副本.md"
            path_b.write_text(path_a.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            readd = oe.read_file(project, path_a.name)
            saved = oe.write_file(project, path_a.name,
                                  content="## 第1章 开端\n一\n\n## 第2章 转折\n二改\n",
                                  revision=readd["revision"])
            self.assertEqual(saved["chapter_revs"]["2"], 3)
            recovered = oe.recover_plan(project)
            self.assertIn("2", recovered["chapters"])
            self.assertEqual(recovered["chapters"]["2"]["outline"], "二改")

    def test_equal_revision_tombstone_does_not_pop_a_live_chapter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            live = [{"id": 1, "title": "开端", "outline": "一", "chapter_rev": 1},
                    {"id": 2, "title": "转折", "outline": "二", "chapter_rev": 3}]
            (project / "大纲" / "AI规划-0001-0002.md").write_text(
                plan_text(live), encoding="utf-8", newline="\n")
            tomb = [{"id": 1, "title": "开端", "outline": "一", "chapter_rev": 1},
                    {"id": 2, "title": "转折", "outline": "", "chapter_rev": 3,
                     "deleted": True}]
            (project / "大纲" / "AI规划-0001-0002-副本.md").write_text(
                plan_text(tomb), encoding="utf-8", newline="\n")
            self.assertIn("2", oe.recover_plan(project)["chapters"])


class EvidenceSymlinkTest(unittest.TestCase):
    def test_snapshot_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "她推开门。\n")
            outside = Path(folder) / "outside"
            outside.mkdir()
            (project / ".webnovel" / "snapshots").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ann.AnnotationError) as caught:
                add_annotation(project, 1, "她推开门。\n", "她推开门。")
            self.assertEqual(caught.exception.code, "unsafe_evidence_store")

    def test_revision_preview_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            outside = Path(folder) / "outside"
            outside.mkdir()
            (project / ".webnovel" / "revision_previews").symlink_to(outside,
                                                                     target_is_directory=True)
            with self.assertRaises(cv.VersionConflict) as caught:
                revision_plan.save_preview(project, 1, "前", "后")
            self.assertEqual(str(caught.exception), "unsafe_evidence_store")


class ResidentBackupTest(unittest.TestCase):
    def _root(self, folder, text="正文\n"):
        root = Path(folder) / "root"
        book = root / "works" / "书"
        (book / "正文").mkdir(parents=True)
        (book / ".webnovel").mkdir(parents=True)
        seed(book, 1, text)
        return root, book

    def test_backup_reconciles_index_and_body_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root, book = self._root(folder)
            first = cv.current_version(book, 1)
            second = cv.commit_raw_bytes(book, 1, "新正文\n".encode("utf-8"),
                                         title="开端", source="test")
            dest = Path(folder) / "dest"
            manifest = rs.backup(root, dest)
            self.assertTrue(manifest["ok"], manifest.get("problems"))
            index_path = dest / "works" / "书" / ".webnovel" / "chapter_versions" / "index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            body_path = dest / "works" / "书" / "正文" / "第1章-开端.md"
            # Simulate the split generation the old backup could produce.
            index["chapters"]["1"]["current"] = first["content_sha256"]
            index_path.write_text(json.dumps(index), encoding="utf-8")
            body_path.write_bytes("正文\n".encode("utf-8"))
            reports = rs._reconcile_resident_versions(root, dest, manifest["contents"])
            self.assertTrue(reports and reports[0]["ok"], reports)
            fixed = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(fixed["chapters"]["1"]["current"], second["content_sha256"])
            self.assertEqual(body_path.read_bytes(), "新正文\n".encode("utf-8"))

    def test_restore_rejects_tampered_backup_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root, book = self._root(folder)
            dest = Path(folder) / "dest"
            manifest = rs.backup(root, dest)
            body = dest / "works" / "书" / "正文" / "第1章-开端.md"
            body.write_bytes("被篡改\n".encode("utf-8"))
            with self.assertRaises(ValueError):
                rs.restore(root, Path(manifest["dest"]), force=True)
            self.assertEqual(cv.file_sha256(book / "正文" / "第1章-开端.md"),
                             cv.raw_sha256("正文\n".encode("utf-8")))


class UndoAndApplyTransactionTest(unittest.TestCase):
    def _applied(self, project):
        text = "开头一句。\n她推开门。\n结尾一句。\n"
        seed(project, 1, text)
        aid = add_annotation(project, 1, text, "她推开门。")["id"]
        preview = preview_for(project, 1, aid, "她撞开门。", op="tx-run")
        identity = draft_identity(project, content=text)
        applied = ann.apply_hunks(project, 1, {
            "op_id": "tx-apply", "hunk_ids": [preview["hunks"][0]["id"]],
            "expected_draft_id": identity["draft_id"],
            "expected_draft_epoch": identity["draft_epoch"],
            "expected_draft_revision": identity["draft_revision"]})
        return aid, preview, applied

    def test_undo_rolls_back_draft_and_state_together(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            aid, preview, applied = self._applied(project)
            with patch.object(ce, "save_draft", side_effect=RuntimeError("simulated")):
                with self.assertRaises(RuntimeError):
                    ann.undo_apply(project, 1, {"op_id": "tx-undo-fail"})
            draft = wb.get_draft(project, 1)
            self.assertIn("她撞开门。", draft["content"])
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"],
                             "applied_to_draft")
            with wb.connect(project) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM patch_ledger").fetchone()[0], 1)
            undone = ann.undo_apply(project, 1, {"op_id": "tx-undo-ok"})
            self.assertIn("她推开门。", undone["draft"]["content"])
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "pending")

    def test_reverse_patch_does_not_rewrite_same_sentence_elsewhere(self):
        current = "开头一句。\n她推开门。\n结尾一句。\n她撞开门。\n"
        entry = {"applied_text": "她撞开门。", "before_quote": "她推开门。",
                 "char_start": 6, "char_end": 11,
                 "prefix_ctx": "开头一句。\n", "suffix_ctx": "\n结尾一句。\n"}
        result = tm.reverse_patch(current, entry)
        self.assertEqual(result["status"], "relocated_needed")
        self.assertEqual(result["text"], current)

    def test_apply_completion_failure_can_be_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            aid, preview, _applied = self._applied(project)
            # Re-run on a fresh chapter to inject the completion failure.
            project2 = make_project(folder + "/two")
            aid2, preview2, _ = self._applied(project2)
            with patch.object(ann, "_idempotency_complete", side_effect=RuntimeError("busy")):
                first = ann.apply_hunks(project2, 1, {
                    "op_id": "apply-complete-fail",
                    "hunk_ids": [preview2["hunks"][0]["id"]],
                    "expected_draft_id": wb.get_draft(project2, 1)["draft_id"],
                    "expected_draft_epoch": wb.get_draft(project2, 1)["draft_epoch"],
                    "expected_draft_revision": wb.get_draft(project2, 1)["draft_revision"]})
            self.assertEqual(first["status"], "applied")
            self.assertFalse(first.get("completion_persisted", True))
            retried = ann.apply_hunks(project2, 1, {
                "op_id": "apply-complete-fail",
                "hunk_ids": [preview2["hunks"][0]["id"]],
                "expected_draft_id": wb.get_draft(project2, 1)["draft_id"],
                "expected_draft_epoch": wb.get_draft(project2, 1)["draft_epoch"],
                "expected_draft_revision": wb.get_draft(project2, 1)["draft_revision"]})
            self.assertEqual(retried["status"], "applied")
            self.assertTrue(retried.get("already_applied"))
            self.assertEqual(retried["draft"]["content"].count("她撞开门。"), 1)


class SaveAndDraftRecoveryTest(unittest.TestCase):
    def test_draft_clear_failure_is_reported_and_retry_finishes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seeded = seed(project, 1, "第一版\n")
            draft = wb.save_draft(project, 1, title="开端", content="提交版\n",
                                  expected_draft_epoch=0, expected_draft_revision=0)
            payload = {"title": "开端", "content": "提交版\n", "op_id": "clear-fail",
                       "expected_version_id": seeded["version_id"],
                       "expected_content_sha256": seeded["content_sha256"],
                       "submitted_draft_id": draft["draft_id"],
                       "submitted_draft_epoch": draft["draft_epoch"],
                       "submitted_draft_revision": draft["draft_revision"]}
            with patch.object(wb, "clear_draft_if_matches", side_effect=RuntimeError("busy")):
                first = ce.save_version(project, 1, payload)
            self.assertEqual(first["status"], "saved")
            self.assertFalse(first["draft_cleared"])
            self.assertTrue(first["draft_clear_failed"])
            self.assertIsNotNone(wb.get_draft(project, 1))
            retried = ce.save_version(project, 1, payload)
            self.assertEqual(retried["status"], "saved")
            self.assertTrue(retried["draft_cleared"])
            self.assertIsNone(wb.get_draft(project, 1))

    def test_partial_save_result_is_not_frozen_under_completed_key(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seeded = seed(project, 1, "第一版\n")
            real = cv.reconcile_title
            calls = {"n": 0}

            def flaky(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {"status": "partial", "title_conflict": True,
                            "renamed": False, "title_renamed": False}
                return real(*args, **kwargs)

            with patch.object(cv, "reconcile_title", side_effect=flaky):
                first = ce.save_version(project, 1, {
                    "title": "新标题", "content": "第二版\n", "op_id": "partial-cache",
                    "expected_version_id": seeded["version_id"],
                    "expected_content_sha256": seeded["content_sha256"]})
            self.assertEqual(first["status"], "partial")
            retried = ce.save_version(project, 1, {
                "title": "新标题", "content": "第二版\n", "op_id": "partial-cache",
                "expected_version_id": seeded["version_id"],
                "expected_content_sha256": seeded["content_sha256"]})
            self.assertEqual(retried["status"], "saved")
            self.assertTrue(retried.get("recovered"))
            third = ce.save_version(project, 1, {
                "title": "新标题", "content": "第三版\n", "op_id": "partial-later",
                "expected_version_id": cv.current_version(project, 1)["version_id"],
                "expected_content_sha256": cv.file_sha256(cv.chapter_path(project, 1))})
            self.assertEqual(third["status"], "saved")
            replay = ce.save_version(project, 1, {
                "title": "新标题", "content": "第二版\n", "op_id": "partial-cache",
                "expected_version_id": seeded["version_id"],
                "expected_content_sha256": seeded["content_sha256"]})
            self.assertNotEqual(replay["status"], "partial")


class SplitTitleAndLifecycleTest(unittest.TestCase):
    def test_split_with_custom_title_renames_file_immediately(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n第二段。\n"
            seed(project, 1, text, title="旧标题")
            result = ce.split_chapter(project, 1, offset=len("第一段。\n"), title="新标题",
                                      expected_content_sha256=cv.file_sha256(
                                          cv.chapter_path(project, 1)), op_id="split-title")
            self.assertIn(result["status"], {"split", "partial"})
            state = ce.chapter_state(project, 1)
            self.assertEqual(state["title"], "新标题")
            self.assertTrue((project / "正文" / "第1章-新标题.md").is_file())
            self.assertEqual(cv.current_version(project, 1)["title"], "新标题")

    def test_delete_annotation_clears_preview_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "她推开门。\n")
            aid = add_annotation(project, 1, "她推开门。\n", "她推开门。")["id"]
            preview_for(project, 1, aid, "她撞开门。", op="life-run")
            self.assertEqual(ann.summary(project, 1)["pending_previews"], 1)
            ann.delete_annotation(project, 1, aid)
            self.assertEqual(ann.list_previews(project, 1)["count"], 0)
            self.assertEqual(ann.summary(project, 1)["pending_previews"], 0)

    def test_undo_resets_preview_status(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "她推开门。\n")
            aid = add_annotation(project, 1, "她推开门。\n", "她推开门。")["id"]
            preview = preview_for(project, 1, aid, "她撞开门。", op="undo-prev-run")
            identity = draft_identity(project, content="她推开门。\n")
            ann.apply_hunks(project, 1, {
                "op_id": "undo-prev-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": identity["draft_id"],
                "expected_draft_epoch": identity["draft_epoch"],
                "expected_draft_revision": identity["draft_revision"]})
            states = {row["preview_id"]: row["status"]
                      for row in ann.list_previews(project, 1)["previews"]}
            self.assertEqual(states[preview["preview_id"]], "applied")
            ann.undo_apply(project, 1, {"op_id": "undo-prev"})
            states = {row["preview_id"]: row["status"]
                      for row in ann.list_previews(project, 1)["previews"]}
            self.assertEqual(states[preview["preview_id"]], "pending")

    def test_adopted_landed_hunk_marks_its_preview_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seed(project, 1, text)
            aid = add_annotation(project, 1, text, "她推开门。")["id"]
            preview = preview_for(project, 1, aid, "她撞开门。", op="adopt-prev-run")
            draft = wb.save_draft(project, 1, title="开端",
                                  content="她撞开门。\n",
                                  expected_draft_epoch=0, expected_draft_revision=0)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "adopt-prev-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(applied["status"], "applied")
            states = {row["preview_id"]: row["status"]
                      for row in ann.list_previews(project, 1)["previews"]}
            self.assertEqual(states[preview["preview_id"]], "applied")

    def test_strict_selection_patch_cannot_touch_another_paragraph(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n第二段。\n第三段。\n第四段。\n"
            seed(project, 1, text)
            aid = add_annotation(project, 1, text, "第二段。")["id"]
            output = {"format": "xml_patches",
                      "patches": [{"id": "p1", "start_para": 3, "end_para": 3,
                                   "text": "第四段改。"}]}
            preview = preview_for(project, 1, aid, "", op="strict-run", output=output)
            hunk = preview["hunks"][0]
            self.assertLessEqual(hunk["char_start"], text.index("第二段。") + len("第二段。"))
            identity = draft_identity(project, content=text)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "strict-apply", "hunk_ids": [hunk["id"]],
                "expected_draft_id": identity["draft_id"],
                "expected_draft_epoch": identity["draft_epoch"],
                "expected_draft_revision": identity["draft_revision"]})
            draft = applied["draft"]["content"]
            lines = draft.split("\n")
            self.assertEqual(lines[3], "第四段。")
            self.assertIn("第四段改。", lines[1])


class RejectUndoIdempotencyTest(unittest.TestCase):
    def test_reject_retry_after_completion_failure_reports_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "她推开门。\n")
            aid = add_annotation(project, 1, "她推开门。\n", "她推开门。")["id"]
            preview = preview_for(project, 1, aid, "她撞开门。", op="rej-run")
            hunk_id = preview["hunks"][0]["id"]
            with patch.object(ann, "_idempotency_complete", side_effect=RuntimeError("busy")):
                first = ann.reject_hunks(project, 1, {"op_id": "rej-1", "hunk_ids": [hunk_id]})
            self.assertEqual(first["status"], "rejected")
            retried = ann.reject_hunks(project, 1, {"op_id": "rej-1", "hunk_ids": [hunk_id]})
            self.assertEqual(retried["status"], "rejected")
            self.assertTrue(retried.get("already_rejected"))

    def test_undo_with_op_id_is_replayable(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "她推开门。\n")
            aid = add_annotation(project, 1, "她推开门。\n", "她推开门。")["id"]
            preview = preview_for(project, 1, aid, "她撞开门。", op="undo-idem-run")
            identity = draft_identity(project, content="她推开门。\n")
            ann.apply_hunks(project, 1, {
                "op_id": "undo-idem-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": identity["draft_id"],
                "expected_draft_epoch": identity["draft_epoch"],
                "expected_draft_revision": identity["draft_revision"]})
            first = ann.undo_apply(project, 1, {"op_id": "undo-idem"})
            again = ann.undo_apply(project, 1, {"op_id": "undo-idem"})
            self.assertEqual(first["status"], "reverted")
            self.assertEqual(again["status"], "reverted")
            self.assertIn("她推开门。", again["draft"]["content"])

    def test_discard_draft_reports_revert_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "她推开门。\n")
            aid = add_annotation(project, 1, "她推开门。\n", "她推开门。")["id"]
            preview = preview_for(project, 1, aid, "她撞开门。", op="discard-run")
            identity = draft_identity(project, content="她推开门。\n")
            ann.apply_hunks(project, 1, {
                "op_id": "discard-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": identity["draft_id"],
                "expected_draft_epoch": identity["draft_epoch"],
                "expected_draft_revision": identity["draft_revision"]})
            with patch.object(ann, "revert_draft_hunks", side_effect=RuntimeError("simulated")):
                discarded = ce.discard_draft(project, 1)
            self.assertTrue(discarded["revert_error"])
            self.assertIsNone(wb.get_draft(project, 1))


class RestoreTrashStagingTest(unittest.TestCase):
    def test_retry_finishes_annotations_after_partial_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "第一章。\n")
            seed(project, 2, "第二章。\n")
            aid = add_annotation(project, 2, "第二章。\n", "第二章。")["id"]
            entry = ce.delete_chapter(
                project, 2,
                expected_version_id=cv.current_version(project, 2)["version_id"],
                expected_content_sha256=cv.file_sha256(cv.chapter_path(project, 2)),
                op_id="trash-del")["trash_entry"]
            real = ce._restore_trash_annotations
            with patch.object(ce, "_restore_trash_annotations",
                              side_effect=RuntimeError("simulated annotation failure")):
                first = ce.restore_trash(project, entry, op_id="trash-restore")
            self.assertEqual(first["status"], "partial")
            self.assertFalse(first["annotations_restored"])
            with patch.object(ce, "_restore_trash_annotations", real):
                retried = ce.restore_trash(project, entry, op_id="trash-restore")
            self.assertEqual(retried["status"], "restored")
            self.assertEqual(retried["annotations_restored"], 1)
            restored = ann.list_annotations(project, retried["chapter_id"])["annotations"]
            self.assertEqual(len(restored), 1)
            self.assertEqual(len(ce.list_trash(project)["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
