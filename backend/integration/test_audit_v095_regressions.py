"""Regression tests for the v0.9.5 adversarial audit's P0/P1 findings."""
import hashlib
import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fanqie_auto_publish import publication_safety as safety
from integration import annotations
from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import concurrent_engine as engine
from integration import invalidation
from integration import maintenance
from integration import memory_library
from integration import outline_editor as oe
from integration import resident_service
from integration import revision_plan as rp
from integration import scenes
from integration import transaction_journal as tj
from integration import version_history
from integration import workbench_db as wb


def project(folder):
    path = Path(folder) / "书"
    (path / "正文").mkdir(parents=True)
    (path / ".webnovel").mkdir(parents=True)
    return path


def seed(book, chapter=1, title="开端", text="旧正文\n"):
    ce.new_chapter(book, {"chapter": chapter, "title": title, "content": text,
                          "op_id": f"new-{chapter}-{uuid.uuid4().hex[:8]}"})


class PathAndVersionTest(unittest.TestCase):
    def test_restore_op_id_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            current = cv.current_version(book, 1) or {}
            outside = Path(folder) / "pwn.json"
            with self.assertRaises(cv.VersionError):
                version_history.restore(book, 1, current["version_id"],
                                        op_id="../../../../pwn")
            self.assertFalse(outside.exists())

    def test_cross_chapter_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, "甲", "甲章正文\n")
            seed(book, 2, "乙", "乙章正文\n")
            first = cv.current_version(book, 1) or {}
            with self.assertRaises(cv.VersionNotFound):
                version_history.read(book, 2, first["sha256"])
            with self.assertRaises(cv.VersionNotFound):
                version_history.restore(book, 2, first["sha256"])

    def test_commit_prepared_record_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            original = cv._store_object
            calls = {"n": 0}

            def fail_once(project_arg, data):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("simulated crash before object write")
                return original(project_arg, data)

            with patch.object(cv, "_store_object", side_effect=fail_once):
                with self.assertRaises(OSError):
                    cv.commit_raw_bytes(book, 1, "新正文\n".encode(), op_id="prepared-retry")
            path = cv.chapter_path(book, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), "旧正文\n")
            with self.assertRaises(cv.VersionConflict) as caught:
                cv.commit_raw_bytes(book, 1, "新正文\n".encode(), op_id="prepared-retry")
            self.assertEqual(caught.exception.args[0], "operation_incomplete")

    def test_new_chapter_expect_absent_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            with self.assertRaises(cv.VersionConflict) as caught:
                cv.commit_raw_bytes(book, 1, "覆盖\n".encode(), allow_new=True,
                                    expect_absent=True, op_id="new-race")
            self.assertEqual(caught.exception.args[0], "chapter_exists")
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), "旧正文\n")


class MaintenanceAndPauseTest(unittest.TestCase):
    def test_gc_protects_registered_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            history = book / ".webnovel" / "history"
            history.mkdir()
            artifact = history / "keep.md"
            artifact.write_text("作者历史", encoding="utf-8")
            old = time.time() - 30 * 86400
            artifact.touch()
            import os
            os.utime(artifact, (old, old))
            maintenance.register_artifact(book, artifact, ref_count=3, protected=True)
            result = maintenance.collect_garbage(book, dry_run=False)
            self.assertTrue(artifact.exists())
            self.assertEqual(result["count"], 0)

    def test_export_refuses_project_and_non_zip_destinations(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            chapter = cv.chapter_path(book, 1)
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.export_bundle(book, chapter)
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.export_bundle(book, Path(folder) / "x.txt")
            existing_zip = Path(folder) / "x.zip"
            existing_zip.write_bytes(b"already here")
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.export_bundle(book, existing_zip)
            self.assertTrue(chapter.is_file())
            self.assertNotEqual(chapter.read_bytes()[:2], b"PK")

    def test_global_pause_blocks_claim_without_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            pause_file = Path(folder) / "global_pause.json"
            previous = engine._GLOBAL_PAUSE_PATH
            engine.configure_global_pause(pause_file)
            try:
                engine.submit(book, {}, priority="P0")
                engine.set_global_pause(True, "test")
                self.assertIsNone(engine.claim(book, "w"))
                engine.set_global_pause(False)
                self.assertIsNotNone(engine.claim(book, "w"))
            finally:
                engine._GLOBAL_PAUSE_PATH = previous


class OutlineLegacyMigrationTest(unittest.TestCase):
    def test_story_plan_chapters_survive_first_meta_write(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            (book / "大纲").mkdir()
            legacy = {
                "schema_version": 1,
                "master_outline": "旧总纲",
                "chapters": {
                    "1": {"id": 1, "title": "开端", "outline": "第一章细纲-旧版",
                          "key_scene": True},
                    "2": {"id": 2, "title": "转折", "outline": "第二章细纲-旧版"},
                },
            }
            (book / ".webnovel" / "story_plan.json").write_text(
                json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            oe.write_meta(book, {"volumes": "第一卷（改）"})
            story = json.loads((book / ".webnovel" / "story_plan.json")
                               .read_text(encoding="utf-8"))
            self.assertEqual(sorted(story["chapters"]), ["1", "2"])
            self.assertEqual(story["chapters"]["1"]["outline"], "第一章细纲-旧版")
            entry = scenes._chapter_entry(book, 1)
            self.assertEqual(entry.get("outline"), "第一章细纲-旧版")


class RecoveryStateMachineTest(unittest.TestCase):
    def _raw_record(self, book, op_id, chapter, data, previous, state="prepared"):
        cv._ensure(book)
        record = {
            "schema_version": 1, "op_id": op_id, "project_id": cv.project_id(book),
            "chapter_id": int(chapter), "candidate_id": None,
            "content_sha256": cv.raw_sha256(data), "previous_sha256": previous,
            "state": state, "done": [], "title": "开端", "raw_bytes": True,
            "created_at": "2026-11-27T00:00:00+00:00",
            "updated_at": "2026-11-27T00:00:00+00:00",
        }
        cv.atomic_json(cv._commit_path(book, op_id), record)
        return record

    def test_raw_commit_without_object_is_conflict_and_does_not_stop_other_records(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            old_path = cv.chapter_path(book, 1)
            old_sha = cv.raw_sha256(old_path.read_bytes())
            self._raw_record(book, "bad-raw", 1, b"missing object\n", old_sha)
            candidate = cv.save_candidate(book, 1, "good candidate\n", op_id="good-cand",
                                          source="writer", title="开端")
            with patch.object(cv, "_write_chapter_bytes", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    cv.commit_candidate(book, 1, candidate["candidate_id"], op_id="good-op",
                                        expected_sha256=old_sha, title="开端")
            results = {item["op_id"]: item["state"] for item in cv.recover_pending(book)}
            self.assertEqual(results["bad-raw"], "conflict")
            self.assertEqual(results["good-op"], "committed")
            bad = cv._load_commit(book, "bad-raw")
            self.assertEqual(bad["state"], "conflict")
            self.assertEqual(bad["conflict_reason"], "source_missing")
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), "good candidate\n")

    def test_resident_recovery_survives_bad_project(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            path = cv.chapter_path(book, 1)
            self._raw_record(book, "bad-raw", 1, b"missing\n",
                             cv.raw_sha256(path.read_bytes()))
            with patch("integration.scheduler.load_scheduler",
                       return_value={"jobs": {"j1": {"project": str(book)}}}):
                fixed = resident_service._recover_pending(Path(folder))
            self.assertEqual(fixed, 1)
            self.assertEqual(cv._load_commit(book, "bad-raw")["state"], "conflict")
            self.assertEqual(path.read_text(encoding="utf-8"), "旧正文\n")

    def test_conflict_is_terminal_and_author_can_discard_or_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            path = cv.chapter_path(book, 1)
            old_sha = cv.raw_sha256(path.read_bytes())
            candidate = cv.save_candidate(book, 1, "写手候选稿\n", op_id="cand-conf",
                                          source="writer", title="开端")
            path.write_text("作者自己改的正文\n", encoding="utf-8", newline="\n")
            self._raw_record(book, "conf-1", 1, b"never used\n", old_sha)
            record = cv._load_commit(book, "conf-1")
            record["candidate_id"] = candidate["candidate_id"]
            record["content_sha256"] = candidate["sha256"]
            cv.atomic_json(cv._commit_path(book, "conf-1"), record)
            first = cv.recover_pending(book)
            self.assertEqual(first[0]["state"], "conflict")
            # Author restores the previous bytes: recovery must not replay.
            path.write_text("旧正文\n", encoding="utf-8", newline="\n")
            self.assertEqual(cv.recover_pending(book), [])
            self.assertEqual(path.read_text(encoding="utf-8"), "旧正文\n")
            discarded = cv.resolve_conflict(book, "conf-1", "discard")
            self.assertEqual(discarded["status"], "discarded")
            self.assertEqual(cv._load_commit(book, "conf-1")["state"], "abandoned")
            self.assertEqual(path.read_text(encoding="utf-8"), "旧正文\n")

            # Explicit author replay lands the candidate.
            self._raw_record(book, "conf-2", 1, b"never used\n", old_sha)
            record = cv._load_commit(book, "conf-2")
            record.update(state="conflict", candidate_id=candidate["candidate_id"],
                          content_sha256=candidate["sha256"], conflict_current=old_sha)
            cv.atomic_json(cv._commit_path(book, "conf-2"), record)
            replayed = cv.resolve_conflict(book, "conf-2", "replay")
            self.assertEqual(replayed["status"], "replayed")
            self.assertEqual(path.read_text(encoding="utf-8"), "写手候选稿\n")
            self.assertEqual(cv.current_version(book, 1)["sha256"], candidate["sha256"])


class SplitDeleteConcurrencyTest(unittest.TestCase):
    def test_split_refuses_to_clobber_concurrent_save(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            text = "第一段。\n\n第二段。\n"
            seed(book, 1, text=text)
            state = ce.chapter_state(book, 1)
            real = cv.commit_raw_bytes

            def race(prj, chapter, data, **kwargs):
                if chapter == 2:
                    current = ce.chapter_state(prj, 1)
                    ce.save_version(prj, 1, {
                        "title": "开端", "content": "作者并发保存的新正文\n",
                        "op_id": "race-save",
                        "expected_version_id": current["version_id"],
                        "expected_content_sha256": current["sha256"]})
                return real(prj, chapter, data, **kwargs)

            with patch.object(cv, "commit_raw_bytes", side_effect=race):
                with self.assertRaises(ce.ChapterError) as caught:
                    ce.split_chapter(book, 1, offset=text.index("第二段"),
                                     expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "split_aborted_concurrent_modification")
            path = cv.chapter_path(book, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), "作者并发保存的新正文\n")
            self.assertEqual(cv.load_index(book)["chapters"]["1"]["current"],
                             cv.file_sha256(path))
            self.assertEqual(sorted(cv.chapter_map(book)), [1])

    def test_delete_refuses_after_concurrent_save_and_leaves_no_trash(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            state = ce.chapter_state(book, 1)
            original = annotations.export_chapter

            def race(prj, chapter):
                current = ce.chapter_state(prj, chapter)
                ce.save_version(prj, chapter, {
                    "title": "开端", "content": "删除窗口内保存的正文\n",
                    "op_id": "race-delete-save",
                    "expected_version_id": current["version_id"],
                    "expected_content_sha256": current["sha256"]})
                return []

            with patch.object(annotations, "export_chapter", side_effect=race):
                with self.assertRaises(ce.ChapterError) as caught:
                    ce.delete_chapter(book, 1, expected_version_id=state["version_id"],
                                      expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "concurrent_modification")
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"),
                             "删除窗口内保存的正文\n")
            self.assertIn("1", cv.load_index(book)["chapters"])
            self.assertEqual(ce.list_trash(book)["entries"], [])

    def test_delete_refuses_when_chapter_has_active_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            state = ce.chapter_state(book, 1)
            with wb.write_tx(book) as db:
                db.execute(
                    "INSERT INTO task_queue(task_id, chapter_id, priority, state, "
                    "blocked_by_json, amendment_fallback, attempts, payload_json, "
                    "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("task_live", 1, "P1", "pending", "[]", "wait", 0, "{}",
                     "2026-11-27T00:00:00+00:00", "2026-11-27T00:00:00+00:00"))
            with self.assertRaises(ce.ChapterError) as caught:
                ce.delete_chapter(book, 1, expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "chapter_has_active_tasks")
            self.assertIsNotNone(cv.chapter_path(book, 1))


class IdempotencyAndRestoreTest(unittest.TestCase):
    def test_save_recovers_completed_commit_when_idempotency_complete_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            state = ce.chapter_state(book, 1)
            payload = {"title": "开端", "content": "第二版正文\n", "op_id": "idem-gap",
                       "expected_version_id": state["version_id"],
                       "expected_content_sha256": state["sha256"]}
            with patch.object(wb, "idempotency_complete",
                              side_effect=RuntimeError("simulated completion failure")):
                first = ce.save_version(book, 1, dict(payload))
            self.assertEqual(first["status"], "saved")
            retried = ce.save_version(book, 1, dict(payload))
            self.assertTrue(retried.get("reused"))
            self.assertEqual(retried["content_sha256"], first["content_sha256"])
            self.assertEqual(len(cv.list_versions(book, 1)), 2)
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), "第二版正文\n")

    def test_split_merge_and_import_op_ids_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            text = "第一段。\n\n第二段。\n"
            seed(book, 1, text=text)
            state = ce.chapter_state(book, 1)
            first = ce.split_chapter(book, 1, offset=text.index("第二段"),
                                     expected_content_sha256=state["sha256"],
                                     op_id="idem-split")
            again = ce.split_chapter(book, 1, offset=text.index("第二段"),
                                     expected_content_sha256=state["sha256"],
                                     op_id="idem-split")
            self.assertTrue(again.get("reused"))
            self.assertEqual(again["new_chapter_id"], first["new_chapter_id"])
            merged = ce.merge_tail(book, op_id="idem-merge")
            merged_again = ce.merge_tail(book, op_id="idem-merge")
            self.assertTrue(merged_again.get("reused"))
            self.assertEqual(merged_again["chapter_id"], merged["chapter_id"])
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            raw = "第1章 甲\n正文甲\n第2章 乙\n正文乙\n"
            imported = ce.import_chapters(book, text=raw, preview=False, op_id="idem-import")
            imported_again = ce.import_chapters(book, text=raw, preview=False,
                                                op_id="idem-import")
            self.assertTrue(imported_again.get("reused"))
            self.assertEqual(imported_again["count"], imported["count"])
            self.assertEqual(sorted(cv.chapter_map(book)), [1, 2])

    def test_restore_title_conflict_is_checked_before_body_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, title="旧标题", text="第一版\n")
            first = cv.current_version(book, 1)
            state = ce.chapter_state(book, 1)
            ce.save_version(book, 1, {"title": "新标题", "content": "第二版\n",
                                      "op_id": "rename-v2",
                                      "expected_version_id": state["version_id"],
                                      "expected_content_sha256": state["sha256"]})
            second = cv.current_version(book, 1)
            (book / "正文" / "第1章-旧标题.md").mkdir()
            with self.assertRaises(cv.VersionConflict) as caught:
                cv.restore_version(book, 1, first["version_id"], op_id="restore-conflict")
            self.assertEqual(caught.exception.args[0], "restore_title_conflict")
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), "第二版\n")
            self.assertEqual(cv.current_version(book, 1)["version_id"], second["version_id"])
            self.assertEqual(len(cv.list_versions(book, 1)), 2)

    def test_restore_rename_updates_receipt_and_commit_path(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, title="旧标题", text="第一版\n")
            first = cv.current_version(book, 1)
            state = ce.chapter_state(book, 1)
            ce.author_confirm(book, 1, {"expected_version_id": state["version_id"],
                                        "expected_content_sha256": state["sha256"]})
            ce.save_version(book, 1, {"title": "新标题", "content": "第二版\n",
                                      "op_id": "rename-v2b",
                                      "expected_version_id": state["version_id"],
                                      "expected_content_sha256": state["sha256"]})
            result = cv.restore_version(book, 1, first["version_id"], op_id="restore-receipt")
            self.assertTrue(result.get("title_renamed"))
            restored_path = book / "正文" / "第1章-旧标题.md"
            self.assertTrue(restored_path.is_file())
            receipts = json.loads((book / ".webnovel" / "writer_receipts.json")
                                  .read_text(encoding="utf-8"))
            self.assertEqual(receipts["1"]["destination"], str(restored_path.resolve()))
            record = cv._load_commit(book, "restore-receipt")
            self.assertEqual(record["chapter_path"], str(restored_path))

    def test_optional_op_ids_replay_new_delete_and_outline_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            first = ce.new_chapter(book, {"chapter": 1, "title": "开端",
                                          "content": "正文\n", "op_id": "new-op"})
            second = ce.new_chapter(book, {"chapter": 1, "title": "开端",
                                           "content": "正文\n", "op_id": "new-op"})
            self.assertTrue(second.get("reused"))
            self.assertEqual(second["chapter_id"], first["chapter_id"])
            self.assertEqual(len(cv.chapter_map(book)), 1)

            seed(book, 2, title="第二章", text="第二章\n")
            state = ce.chapter_state(book, 2)
            deleted = ce.delete_chapter(book, 2, expected_content_sha256=state["sha256"],
                                        op_id="del-op")
            again = ce.delete_chapter(book, 2, expected_content_sha256=state["sha256"],
                                      op_id="del-op")
            self.assertTrue(again.get("reused"))
            self.assertEqual(again["trash_entry"], deleted["trash_entry"])

            outline = book / "大纲"
            outline.mkdir()
            path = outline / "AI规划-0001-0001.md"
            path.write_text("## 第1章 开端\n旧细纲\n", encoding="utf-8", newline="\n")
            revision = oe.read_file(book, path.name)["revision"]
            saved = oe.write_file(book, path.name, content="## 第1章 开端\n新细纲\n",
                                  revision=revision, op_id="outline-op")
            retried = oe.write_file(book, path.name, content="## 第1章 开端\n新细纲\n",
                                    revision=revision, op_id="outline-op")
            self.assertTrue(retried.get("reused"))
            self.assertEqual(retried["revision"], saved["revision"])


class InvalidationAndPreviewTest(unittest.TestCase):
    def _fact(self, book):
        doc = memory_library.read(book)
        digest = cv.file_sha256(cv.chapter_path(book, 1))
        memory_library.save_item(
            book, {"category": "canon", "title": "钥匙", "content": "钥匙在谁手里"},
            doc["revision"], source={"kind": "chapter", "chapter": 1, "sha256": digest,
                                     "quote": "旧正文"})
        saved = memory_library.read(book)
        return next(row for row in saved["items"] if row["title"] == "钥匙")

    def test_invalidation_retries_pending_log_instead_of_reusing(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            fact = self._fact(book)
            (book / ".webnovel" / "invalidation_log.json").unlink(missing_ok=True)
            real = invalidation._mark_facts
            with patch.object(invalidation, "_mark_facts",
                              side_effect=OSError("simulated mark failure")):
                with self.assertRaises(OSError):
                    invalidation.invalidate(book, chapters=[1], reason="chapter_edited",
                                            op_id="invalidate-gap")
            entry = invalidation.read_log(book)["entries"][-1]
            self.assertEqual(entry["state"], "pending")
            result = invalidation.invalidate(book, chapters=[1], reason="chapter_edited",
                                             op_id="invalidate-gap")
            self.assertEqual(result["status"], "invalidated")
            self.assertEqual(len(invalidation.read_log(book)["entries"]), 1)
            saved = memory_library.read(book)
            target = next(row for row in saved["items"] if row["id"] == fact["id"])
            self.assertEqual(target["status"], "needs_review")

    def test_preview_accept_retries_after_mark_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            before = cv.chapter_path(book, 1).read_text(encoding="utf-8")
            preview = rp.save_preview(book, 1, before, "修订后的正文\n",
                                      base_sha256=cv.file_sha256(cv.chapter_path(book, 1)))
            real_mark = rp._mark
            with patch.object(rp, "_mark", side_effect=OSError("simulated mark failure")):
                with self.assertRaises(OSError):
                    rp.accept(book, 1, preview["preview_id"])
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), "修订后的正文\n")
            self.assertEqual(rp.load_preview(book, 1, preview["preview_id"])["state"], "pending")
            retried = rp.accept(book, 1, preview["preview_id"])
            self.assertEqual(retried["status"], "accepted")
            self.assertEqual(rp.load_preview(book, 1, preview["preview_id"])["state"], "accepted")

    def test_annotation_preview_cannot_be_accepted_as_a_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            before = cv.chapter_path(book, 1).read_text(encoding="utf-8")
            preview = rp.save_preview(book, 1, before, "批注候选\n",
                                      base_sha256=cv.file_sha256(cv.chapter_path(book, 1)),
                                      mode="annotation")
            with self.assertRaises(cv.VersionConflict) as caught:
                rp.accept(book, 1, preview["preview_id"])
            self.assertEqual(str(caught.exception), "annotation_preview_requires_hunk_apply")
            self.assertEqual(cv.chapter_path(book, 1).read_text(encoding="utf-8"), before)
            self.assertEqual(rp.load_preview(book, 1, preview["preview_id"])["state"], "pending")


class RollbackAndReceiptTest(unittest.TestCase):
    def test_split_and_merge_can_retry_after_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            text = "第一段内容。\n\n第二段内容。\n"
            seed(book, 1, text=text)
            state = ce.chapter_state(book, 1)
            real_commit = cv.commit_raw_bytes
            calls = {"n": 0}

            def flaky(prj, chapter, data, **kwargs):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("simulated first-half failure")
                return real_commit(prj, chapter, data, **kwargs)

            with patch.object(cv, "commit_raw_bytes", side_effect=flaky):
                with self.assertRaises(RuntimeError):
                    ce.split_chapter(book, 1, offset=text.index("第二段"),
                                     expected_content_sha256=state["sha256"], op_id="split-retry")
            commits = book / ".webnovel" / "chapter_versions" / "commits"
            self.assertEqual([p.name for p in commits.glob("split-*.json")], [])
            retried = ce.split_chapter(book, 1, offset=text.index("第二段"),
                                       expected_content_sha256=state["sha256"],
                                       op_id="split-retry")
            self.assertEqual(retried["status"], "split")
            self.assertEqual(sorted(cv.chapter_map(book)), [1, 2])

            real_delete = ce.delete_chapter

            def failing_delete(*args, **kwargs):
                raise RuntimeError("simulated tail delete failure")

            with patch.object(ce, "delete_chapter", side_effect=failing_delete):
                with self.assertRaises(RuntimeError):
                    ce.merge_tail(book, op_id="merge-retry")
            self.assertEqual(sorted(cv.chapter_map(book)), [1, 2])
            merged = ce.merge_tail(book, op_id="merge-retry")
            self.assertEqual(merged["status"], "merged")
            self.assertEqual(sorted(cv.chapter_map(book)), [1])

    def test_title_fits_character_limit_but_not_filename_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            with self.assertRaises(ce.ChapterError) as caught:
                ce.new_chapter(book, {"chapter": 1, "title": "长" * 100,
                                      "content": "正文\n", "op_id": "too-long"})
            self.assertEqual(caught.exception.code, "title_too_long_for_filesystem")
            self.assertEqual(sorted(cv.chapter_map(book)), [])
            commits = book / ".webnovel" / "chapter_versions" / "commits"
            self.assertEqual(list(commits.glob("*.json")), [])

    def test_backup_is_consistent_when_a_save_lands_mid_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            (book / "大纲").mkdir()
            seed(book)
            state = ce.chapter_state(book, 1)
            dest = Path(folder) / "备份"
            real_copy = tj._copy_tree
            fired = {"done": False}

            def hook(source, dest_root, records, **kwargs):
                if Path(source).name == "大纲" and not fired["done"]:
                    fired["done"] = True
                    ce.save_version(book, 1, {
                        "title": "开端", "content": "备份期间保存的新正文\n",
                        "op_id": "backup-race",
                        "expected_version_id": state["version_id"],
                        "expected_content_sha256": state["sha256"]})
                return real_copy(source, dest_root, records, **kwargs)

            with patch.object(tj, "_copy_tree", side_effect=hook):
                summary = tj.backup(book, dest)
            self.assertGreaterEqual(summary["files"], 1)
            index = json.loads((dest / ".webnovel" / "chapter_versions" / "index.json")
                               .read_text(encoding="utf-8"))
            body = next((dest / "正文").glob("*.md"))
            self.assertEqual(hashlib.sha256(body.read_bytes()).hexdigest(),
                             index["chapters"]["1"]["current"])
            self.assertTrue(tj.inspect_backup(dest)["valid"])

    def test_inspect_backup_reports_index_body_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            backup = Path(folder) / "backup"
            (backup / "正文").mkdir(parents=True)
            (backup / ".webnovel" / "chapter_versions").mkdir(parents=True)
            body = backup / "正文" / "第1章-甲.md"
            body.write_text("旧正文\n", encoding="utf-8", newline="\n")
            index_path = backup / ".webnovel" / "chapter_versions" / "index.json"
            index_path.write_text(json.dumps({"schema_version": 1, "chapters": {
                "1": {"current": "f" * 64}}}), encoding="utf-8")
            manifest = {"format": tj.BACKUP_FORMAT, "files": [
                {"path": "正文/第1章-甲.md", "kind": "file",
                 "sha256": hashlib.sha256(body.read_bytes()).hexdigest(),
                 "size": body.stat().st_size},
                {"path": ".webnovel/chapter_versions/index.json", "kind": "file",
                 "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                 "size": index_path.stat().st_size},
            ]}
            (backup / "backup_manifest.json").write_text(json.dumps(manifest),
                                                         encoding="utf-8")
            inspected = tj.inspect_backup(backup)
            self.assertFalse(inspected["valid"])
            self.assertIn("index_body_mismatch:1", inspected["problems"])

    def test_delete_drop_receipt_keeps_concurrent_confirm(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book, 1, title="标题一", text="第一章\n")
            seed(book, 2, title="标题二", text="第二章\n")
            for number in (1, 2):
                state = ce.chapter_state(book, number)
                ce.author_confirm(book, number, {
                    "expected_version_id": state["version_id"],
                    "expected_content_sha256": state["sha256"]})
            fired = {"done": False}
            real_atomic = safety.atomic_json

            def hook(path, data):
                if (Path(path).name == "writer_receipts.json" and isinstance(data, dict)
                        and "2" not in data and not fired["done"]):
                    fired["done"] = True
                    ce.author_confirm(book, 1, {
                        "expected_version_id": cv.current_version(book, 1)["version_id"],
                        "expected_content_sha256": cv.file_sha256(cv.chapter_path(book, 1)),
                        "note": "并发窗口内的新确认"})
                return real_atomic(path, data)

            with patch.object(safety, "atomic_json", side_effect=hook):
                state = ce.chapter_state(book, 2)
                ce.delete_chapter(book, 2, expected_content_sha256=state["sha256"],
                                  op_id="drop-receipt")
            receipts = json.loads((book / ".webnovel" / "writer_receipts.json")
                                  .read_text(encoding="utf-8"))
            self.assertEqual(sorted(receipts), ["1"])
            self.assertEqual((receipts["1"].get("review") or {}).get("note"),
                             "并发窗口内的新确认")


class TrashAndSymlinkTest(unittest.TestCase):
    def test_restore_trash_restores_annotations_and_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            annotations.create_annotation(book, 1, {"scope": "chapter",
                                                   "instruction": "把这一段改得更紧凑"})
            draft = wb.save_draft(book, 1, title="开端", content="作者尚未提交的草稿\n",
                                  expected_draft_epoch=0, expected_draft_revision=0)
            state = ce.chapter_state(book, 1)
            deleted = ce.delete_chapter(book, 1, expected_content_sha256=state["sha256"])
            restored = ce.restore_trash(book, deleted["trash_entry"])
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(restored["annotations_restored"], 1)
            self.assertTrue(restored["draft_restored"])
            self.assertEqual(annotations.summary(book, 1).get("open_count"), 1)
            survived = wb.get_draft(book, 1)
            self.assertIsNotNone(survived)
            self.assertEqual(survived["content"], "作者尚未提交的草稿\n")
            self.assertEqual(survived["draft_id"], draft["draft_id"])

    def test_symlinked_storage_directories_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            book = project(folder)
            outside = root / "outside"
            outside.mkdir()
            os.symlink(outside, book / ".webnovel" / "chapter_versions")
            with self.assertRaises(cv.VersionConflict) as caught:
                cv.commit_raw_bytes(book, 1, b"body\n", title="开端", op_id="symlink")
            self.assertEqual(caught.exception.args[0], "unsafe_version_store")
            self.assertFalse((outside / "index.json").exists())

            lore = root / "lore-outside"
            lore.mkdir()
            (book / "设定").symlink_to(lore)
            with self.assertRaises(oe.OutlineError) as outline_caught:
                oe.write_lore(book, "世界观.md", content="设定\n")
            self.assertEqual(outline_caught.exception.code, "path_escape")
            self.assertFalse((lore / "世界观.md").exists())

            outside_outline = root / "outline-outside"
            outside_outline.mkdir()
            target = outside_outline / "AI规划-0001-0001.md"
            target.write_text("## 第1章 开端\n旧\n", encoding="utf-8", newline="\n")
            target_revision = hashlib.sha256(target.read_bytes()).hexdigest()
            (book / "大纲").symlink_to(outside_outline)
            with self.assertRaises(oe.OutlineError) as plan_caught:
                oe.write_file(book, target.name, content="## 第1章 开端\n新\n",
                              revision=target_revision)
            self.assertEqual(plan_caught.exception.code, "path_escape")
            self.assertIn("旧", target.read_text(encoding="utf-8"))



class SplitRollbackConcurrencyTest(unittest.TestCase):
    def test_concurrent_chapter_plus_one_survives_split_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            text = "第一段。\n\n第二段。\n"
            seed(book, 1, text=text)
            state = ce.chapter_state(book, 1)
            real = cv.commit_raw_bytes
            fired = {"done": False}

            def race(prj, chapter, data, **kwargs):
                if chapter == 1 and not fired["done"]:
                    fired["done"] = True
                    second = ce.chapter_state(prj, 2)
                    ce.save_version(prj, 2, {
                        "title": "并发下半章", "content": "并发保存的下半章\n",
                        "op_id": "split-race-ch2", "expected_version_id": second["version_id"],
                        "expected_content_sha256": second["sha256"]})
                    ce.author_confirm(prj, 2, {
                        "expected_version_id": cv.current_version(prj, 2)["version_id"],
                        "expected_content_sha256": cv.file_sha256(cv.chapter_path(prj, 2))})
                    raise RuntimeError("simulated first-half failure")
                return real(prj, chapter, data, **kwargs)

            with patch.object(cv, "commit_raw_bytes", side_effect=race):
                with self.assertRaises(ce.ChapterError) as caught:
                    ce.split_chapter(book, 1, offset=text.index("第二段"),
                                     expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "split_rollback_skipped_concurrent")
            index = cv.load_index(book)["chapters"]
            self.assertIn("2", index)
            self.assertEqual(index["2"]["current"], cv.file_sha256(cv.chapter_path(book, 2)))
            self.assertIsNotNone(cv.current_version(book, 2))
            receipts = json.loads((book / ".webnovel" / "writer_receipts.json")
                                  .read_text(encoding="utf-8"))
            self.assertTrue(Path(receipts["2"]["destination"]).is_file())
            self.assertEqual(sorted(cv.chapter_map(book)), [1, 2])


class SaveRenamePartialTest(unittest.TestCase):
    def test_rename_race_returns_partial_and_retry_finishes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            state = ce.chapter_state(book, 1)
            ce.author_confirm(book, 1, {"expected_version_id": state["version_id"],
                                        "expected_content_sha256": state["sha256"]})
            real_write = cv.write_chapter

            def write_then_squat(*args, **kwargs):
                result = real_write(*args, **kwargs)
                (book / "正文" / "第1章-新标题.md").write_text(
                    "外部占位\n", encoding="utf-8", newline="\n")
                return result

            payload = {"title": "新标题", "content": "第二版\n", "op_id": "rename-race-partial",
                       "expected_version_id": state["version_id"],
                       "expected_content_sha256": state["sha256"]}
            with patch.object(cv, "write_chapter", side_effect=write_then_squat):
                result = ce.save_version(book, 1, dict(payload))
            self.assertEqual(result["status"], "partial")
            self.assertTrue(result["title_conflict"])
            self.assertFalse(result["title_renamed"])
            self.assertEqual(len(list((book / "正文").glob("*.md"))), 2)

            (book / "正文" / "第1章-新标题.md").unlink()
            retried = ce.save_version(book, 1, dict(payload))
            self.assertIn(retried["status"], {"saved", "partial"})
            self.assertEqual(cv.chapter_path(book, 1).name, "第1章-新标题.md")
            receipts = json.loads((book / ".webnovel" / "writer_receipts.json")
                                  .read_text(encoding="utf-8"))
            self.assertEqual(Path(receipts["1"]["destination"]).name, "第1章-新标题.md")


class TrashIdempotencyTest(unittest.TestCase):
    def test_restore_trash_rejects_a_second_copy_unless_forced(self):
        with tempfile.TemporaryDirectory() as folder:
            book = project(folder)
            seed(book)
            state = ce.chapter_state(book, 1)
            deleted = ce.delete_chapter(book, 1, expected_content_sha256=state["sha256"])
            first = ce.restore_trash(book, deleted["trash_entry"])
            self.assertEqual(first["chapter_id"], 1)
            with self.assertRaises(ce.ChapterError) as caught:
                ce.restore_trash(book, deleted["trash_entry"])
            self.assertEqual(caught.exception.code, "already_restored")
            self.assertEqual(sorted(cv.chapter_map(book)), [1])
            forced = ce.restore_trash(book, deleted["trash_entry"], force=True)
            self.assertEqual(forced["chapter_id"], 2)
            self.assertEqual(sorted(cv.chapter_map(book)), [1, 2])


if __name__ == "__main__":
    unittest.main()
