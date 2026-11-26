"""Adversarial probes for ``integration.chapter_editor`` (v0.8 wave 2).

Tests decorated with :func:`defect` encode behaviour required by plan
``01_自由编辑_版本契约与多文件大纲设计.md`` / the v0.8 contract.  On the
current branch they fail; each docstring names the defect and its priority.
Run with ``ADVERSARIAL_STRICT=1`` to see them as ordinary failures::

    ADVERSARIAL_STRICT=1 PYTHONPATH=backend python3 -m unittest \
        integration.test_chapter_editor_adversarial -v

Without that variable they are ``expectedFailure`` so the suite stays green
while the defect list remains executable and self-documenting.
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fanqie_auto_publish import publication_safety as safety
from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import workbench_db as wb

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


def seed(project, chapter: int = 1, content: str = "第一段。\n\n第二段。\n",
         title: str = "开端") -> dict:
    return ce.new_chapter(project, {
        "chapter": chapter, "title": title, "content": content,
        "op_id": f"new-{chapter}-{time.time_ns()}",
    })


def save(project, chapter: int, content: str, title: str = "开端", **extra) -> dict:
    data = {
        "title": title, "content": content,
        "op_id": extra.pop("op_id", f"op-{chapter}-{time.time_ns()}"),
        "source": "author_edit",
        "allow_new": extra.pop("allow_new", False),
    }
    data.update(extra)
    return ce.save_version(project, chapter, data)


def snapshot(project, chapter: int = 1) -> dict:
    path = cv.chapter_path(project, chapter)
    entry = cv.load_index(project)["chapters"].get(str(chapter)) or {}
    return {
        "name": path.name if path else None,
        "bytes": path.read_bytes() if path else None,
        "versions": len(cv.list_versions(project, chapter)) if path else 0,
        "current": entry.get("current"),
        "current_version_id": entry.get("current_version_id"),
        "title": ce.chapter_state(project, chapter)["title"] if path else None,
    }


class TitleSafetyTest(unittest.TestCase):
    def test_windows_reserved_names_and_trailing_dots_fail_before_write(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            before = snapshot(project)
            for title in ("CON", "con.md", "PRN", "AUX", "NUL", "COM1", "COM9",
                          "LPT1", "LPT9", "结尾.", "结尾..", "结尾 ."):
                with self.subTest(title=title):
                    with self.assertRaises(ce.ChapterError) as caught:
                        save(project, 1, "新正文\n", title=title)
                    self.assertTrue(caught.exception.code.startswith("invalid_title"))
                    self.assertEqual(snapshot(project), before)

    @defect
    def test_invalid_windows_characters_fail_before_write(self):
        """DEFECT P1: titles containing < > " | ? * \\ \\ / are accepted.

        ``_validate_title`` delegates to ``transaction_journal.validate_windows_name``,
        which only rejects control characters, ':', trailing space/dot and device
        names; it never applies the module's own ``_WINDOWS_BAD`` character
        class.  ``< > " | ? * \\`` therefore create real files on Linux (and
        fail only after commit on Windows); ``/`` raises a bare ValueError from
        ``Path.with_name`` after the body and index were already committed.
        """
        for title in ("a<b", "a>b", 'a"b', "a|b", "a?b", "a*b", "a\\b", "a/b"):
            with self.subTest(title=title), tempfile.TemporaryDirectory() as folder:
                project = make_project(folder)
                seed(project)
                state = ce.chapter_state(project, 1)
                before = snapshot(project)
                try:
                    save(project, 1, "新正文\n", title=title,
                         expected_version_id=state["version_id"],
                         expected_content_sha256=state["sha256"])
                except ce.ChapterError:
                    pass
                except Exception as exc:  # noqa: BLE001 - this is the defect
                    self.fail(f"{title!r} raised non-domain {type(exc).__name__}: {exc}")
                else:
                    self.fail(f"{title!r} was accepted and written")
                self.assertEqual(snapshot(project), before)

    @defect
    def test_lone_surrogate_content_is_domain_error(self):
        """DEFECT P2: content with a lone surrogate escapes as UnicodeEncodeError.

        ``_validate_content`` measures ``text.encode('utf-8')`` without guarding
        it, and ``new_chapter`` encodes directly; JSON clients can send
        ``\\ud800`` and receive a 500 instead of a stable 400.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            probes = {
                "save": lambda: save(project, 1, "surrogate \ud800", op_id="sur-save",
                                     expected_version_id=state["version_id"],
                                     expected_content_sha256=state["sha256"]),
                "draft": lambda: ce.save_draft(project, 1, {
                    "title": "开端", "content": "draft \ud800", "expected_draft_id": None,
                    "expected_draft_epoch": 0, "expected_draft_revision": 0}),
                "new": lambda: ce.new_chapter(project, {
                    "chapter": 9, "title": "x", "content": "\ud800", "op_id": "sur-new"}),
                "preview": lambda: ce.import_preview(project, text="第1章 开端\n\ud800\n"),
            }
            for label, call in probes.items():
                with self.subTest(probe=label):
                    try:
                        call()
                    except ce.ChapterError:
                        pass
                    except Exception as exc:  # noqa: BLE001
                        self.fail(f"{label} raised {type(exc).__name__}: {exc}")
                    else:
                        self.fail(f"{label} accepted a lone surrogate")


class RenameTest(unittest.TestCase):
    def test_rename_with_preexisting_target_file_preserves_both(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            target = project / "正文" / "第1章-新标题.md"
            target.write_text("另一个文件\n", encoding="utf-8")
            before = {p.name: p.read_bytes() for p in (project / "正文").glob("*.md")}
            with self.assertRaises((ce.ChapterError, cv.VersionConflict)) as caught:
                save(project, 1, "新正文\n", title="新标题", op_id="reg-target",
                     expected_version_id=state["version_id"],
                     expected_content_sha256=state["sha256"])
            self.assertIn(getattr(caught.exception, "status", 409), (409,))
            after = {p.name: p.read_bytes() for p in (project / "正文").glob("*.md")}
            self.assertEqual(before, after)
            self.assertEqual(len(cv.list_versions(project, 1)), 1)

    def test_rename_retries_winerror32_three_times_and_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            original = "原始正文\n第二行\n"
            seed(project, 1, original)
            state = ce.chapter_state(project, 1)
            real_replace = cv.os.replace
            failures = {"count": 0}

            def flaky_replace(source, target):
                if "重命名后" in str(target) and failures["count"] < 3:
                    failures["count"] += 1
                    error = PermissionError(13, "sharing violation")
                    error.winerror = 32
                    raise error
                return real_replace(source, target)

            cv.os.replace = flaky_replace
            try:
                result = save(project, 1, state["content"], title="重命名后",
                              op_id="rename-retry",
                              expected_version_id=state["version_id"],
                              expected_content_sha256=state["sha256"])
            finally:
                cv.os.replace = real_replace
            self.assertEqual(failures["count"], 3)
            self.assertTrue(result.get("renamed"))
            path = cv.chapter_path(project, 1)
            self.assertEqual(path.name, "第1章-重命名后.md")
            self.assertEqual(path.read_bytes(), original.encode("utf-8"))
            self.assertEqual(cv.current_version(project, 1)["title"], "重命名后")

    @defect
    def test_rename_target_directory_conflict_does_not_commit_partial_state(self):
        """DEFECT P1: a rename conflict returns 409 after body+index already changed.

        ``save_version`` calls ``versions.write_chapter`` before
        ``_rename_chapter_file``.  A directory squatting on the target filename
        (invisible to ``chapter_path`` because it is not a file) makes the
        rename raise ``chapter_filename_conflict`` while the old file now holds
        the new body and ``index.json`` already points at a new version whose
        title differs from the on-disk filename.  The same partial commit
        happens when six WinError 32 retries are exhausted.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            (project / "正文" / "第1章-新标题.md").mkdir()
            before = snapshot(project)
            with self.assertRaises(ce.ChapterError) as caught:
                save(project, 1, "标题冲突也要写进去\n", title="新标题",
                     op_id="dir-conflict", expected_version_id=state["version_id"],
                     expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "chapter_filename_conflict")
            self.assertEqual(snapshot(project), before)


class LockAndRaceTest(unittest.TestCase):
    @defect
    def test_lock_contention_returns_409_not_publication_blocked(self):
        """DEFECT P1: a busy chapter lock leaks ``PublicationBlocked`` (HTTP 500).

        ``_locked`` uses ``publication_safety.file_lock`` in non-blocking mode.
        The v0.8 contract requires the losing writer to receive a stable 409;
        instead the raw ``PublicationBlocked('resource_busy')`` escapes
        ``api_v08.guard``, and the already-reserved idempotency key is never
        failed.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            lock_path = project / ".webnovel" / "locks" / "chapter-0001.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            ready, release = threading.Event(), threading.Event()

            def holder():
                with safety.file_lock(lock_path):
                    ready.set()
                    release.wait(5)

            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(ready.wait(5))
            try:
                with self.assertRaises(Exception) as caught:  # noqa: BLE001
                    save(project, 1, "抢锁稿\n", op_id="busy-1",
                         expected_version_id=state["version_id"],
                         expected_content_sha256=state["sha256"])
            finally:
                release.set()
                thread.join(5)
            self.assertIsInstance(caught.exception, ce.ChapterError,
                                  f"leaked {type(caught.exception).__name__}")
            self.assertEqual(caught.exception.status, 409)

    @defect
    def test_transient_failure_does_not_poison_idempotency_key(self):
        """DEFECT P1: any failure after ``idempotency_begin`` blocks retries for 24h.

        ``save_version`` reserves ``op_id`` before the chapter lock and never
        calls ``workbench_db.idempotency_fail`` in an ``except`` block, so a
        transient lock/OS failure leaves state='in_progress' and the same
        payload can only ever receive ``op_in_progress`` (409).
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            payload = {
                "title": "开端", "content": "重试稿\n", "op_id": "poison-1",
                "expected_version_id": state["version_id"],
                "expected_content_sha256": state["sha256"],
            }
            lock_path = project / ".webnovel" / "locks" / "chapter-0001.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            ready, release = threading.Event(), threading.Event()

            def holder():
                with safety.file_lock(lock_path):
                    ready.set()
                    release.wait(5)

            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(ready.wait(5))
            try:
                with self.assertRaises(Exception):  # noqa: BLE001
                    ce.save_version(project, 1, dict(payload))
            finally:
                release.set()
                thread.join(5)
            try:
                retried = ce.save_version(project, 1, dict(payload))
            except Exception as exc:  # noqa: BLE001 - the defect is the retry block
                self.fail(f"retry raised {type(exc).__name__}: {exc}")
            self.assertEqual(retried["status"], "saved")
            self.assertEqual(cv.chapter_path(project, 1).read_text(encoding="utf-8"),
                             "重试稿\n")

    def test_two_threads_never_duplicate_version_or_diverge_index(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            barrier = threading.Barrier(2)
            outcomes = []
            lock = threading.Lock()

            def worker(content, ordinal):
                barrier.wait(5)
                try:
                    result = save(project, 1, content, op_id=f"race-{ordinal}",
                                  expected_version_id=state["version_id"],
                                  expected_content_sha256=state["sha256"])
                    with lock:
                        outcomes.append(("ok", result))
                except Exception as exc:  # noqa: BLE001 - data invariants only here
                    with lock:
                        outcomes.append(("error", exc))

            threads = [threading.Thread(target=worker, args=(f"稿件{i}\n", i))
                       for i in (0, 1)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            successes = [item for kind, item in outcomes if kind == "ok"]
            self.assertEqual(len(successes), 1, outcomes)
            winner = successes[0]
            path = cv.chapter_path(project, 1)
            disk_sha = cv.file_sha256(path)
            entry = cv.load_index(project)["chapters"]["1"]
            self.assertEqual(disk_sha, winner["content_sha256"])
            self.assertEqual(entry["current"], disk_sha)
            self.assertEqual(cv.current_version(project, 1)["content_sha256"], disk_sha)
            self.assertEqual(len(cv.list_versions(project, 1)), 2)
            self.assertEqual(sum(1 for item in cv.list_versions(project, 1)
                                 if item.get("sha256") == disk_sha), 1)


class DraftIdentityTest(unittest.TestCase):
    def test_draft_created_after_commit_survives_the_late_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            first = ce.save_draft(project, 1, {
                "title": "开端", "content": "提交前的稿", "expected_draft_id": None,
                "expected_draft_epoch": 0, "expected_draft_revision": 0})["draft"]
            real_clear = wb.clear_draft_if_matches
            late = {}

            def clear_after_new_typing(prj, chapter, **kwargs):
                late["draft"] = wb.save_draft(
                    prj, chapter, title="开端", content="Ctrl+S 之后继续打字",
                    expected_draft_id=first["draft_id"],
                    expected_draft_epoch=first["draft_epoch"],
                    expected_draft_revision=first["draft_revision"])
                return real_clear(prj, chapter, **kwargs)

            wb.clear_draft_if_matches = clear_after_new_typing
            try:
                result = save(project, 1, "提交前的稿", op_id="ctrl-s-race",
                              expected_version_id=state["version_id"],
                              expected_content_sha256=state["sha256"],
                              submitted_draft_id=first["draft_id"],
                              submitted_draft_epoch=first["draft_epoch"],
                              submitted_draft_revision=first["draft_revision"])
            finally:
                wb.clear_draft_if_matches = real_clear
            self.assertTrue(result["draft_preserved"])
            self.assertFalse(result["draft_cleared"])
            current = wb.get_draft(project, 1)
            self.assertEqual(current["content"], "Ctrl+S 之后继续打字")
            self.assertEqual(current["draft_revision"], 2)
            self.assertEqual(current["draft_id"], late["draft"]["draft_id"])

    def test_exact_identity_clears_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            draft = ce.save_draft(project, 1, {
                "title": "开端", "content": "待提交", "expected_draft_id": None,
                "expected_draft_epoch": 0, "expected_draft_revision": 0})["draft"]
            result = save(project, 1, "待提交", op_id="ctrl-s-exact",
                          expected_version_id=state["version_id"],
                          expected_content_sha256=state["sha256"],
                          submitted_draft_id=draft["draft_id"],
                          submitted_draft_epoch=draft["draft_epoch"],
                          submitted_draft_revision=draft["draft_revision"])
            self.assertTrue(result["draft_cleared"])
            self.assertIsNone(wb.get_draft(project, 1))

    def test_draft_epoch_monotonic_across_discard_delete_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            epochs = [wb.ensure_chapter_meta(project, 1)["draft_epoch"]]
            ce.save_draft(project, 1, {
                "title": "开端", "content": "d1", "expected_draft_id": None,
                "expected_draft_epoch": epochs[-1], "expected_draft_revision": 0})
            epochs.append(wb.ensure_chapter_meta(project, 1)["draft_epoch"])
            ce.discard_draft(project, 1)
            epochs.append(wb.ensure_chapter_meta(project, 1)["draft_epoch"])
            ce.save_draft(project, 1, {
                "title": "开端", "content": "d2", "expected_draft_id": None,
                "expected_draft_epoch": epochs[-1], "expected_draft_revision": 0})
            epochs.append(wb.ensure_chapter_meta(project, 1)["draft_epoch"])
            state = ce.chapter_state(project, 1)
            deleted = ce.delete_chapter(project, 1,
                                        expected_content_sha256=state["sha256"])
            epochs.append(wb.ensure_chapter_meta(project, 1)["draft_epoch"])
            ce.restore_trash(project, deleted["trash_entry"])
            epochs.append(wb.ensure_chapter_meta(project, 1)["draft_epoch"])
            self.assertEqual(epochs, sorted(epochs))
            self.assertIsNone(wb.get_draft(project, 1))
            fresh = ce.save_draft(project, 1, {
                "title": "开端", "content": "restored", "expected_draft_id": None,
                "expected_draft_epoch": epochs[-1], "expected_draft_revision": 0})
            self.assertGreater(fresh["draft"]["draft_epoch"], epochs[-1])


class TrashTest(unittest.TestCase):
    def test_delete_restore_collision_twice_missing_payload_and_bad_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            seed(project, 2, "二\n", title="第二章")
            state = ce.chapter_state(project, 2)
            first = ce.delete_chapter(project, 2,
                                      expected_content_sha256=state["sha256"])
            seed(project, 2, "新二\n", title="新二")
            restored = ce.restore_trash(project, first["trash_entry"])
            self.assertEqual((restored["chapter_id"], restored["renumbered"]), (3, True))
            state3 = ce.chapter_state(project, 3)
            second = ce.delete_chapter(project, 3,
                                       expected_content_sha256=state3["sha256"])
            seed(project, 3, "新三\n", title="新三")
            again = ce.restore_trash(project, second["trash_entry"])
            self.assertEqual((again["chapter_id"], again["renumbered"]), (4, True))
            self.assertEqual(sorted(cv.chapter_map(project)), [1, 2, 3, 4])

            state4 = ce.chapter_state(project, 4)
            missing = ce.delete_chapter(project, 4,
                                        expected_content_sha256=state4["sha256"])
            archive = project / ".webnovel" / "trash" / missing["trash_entry"]
            for payload in archive.glob("*.md"):
                payload.unlink()
            with self.assertRaises(ce.ChapterError) as caught:
                ce.restore_trash(project, missing["trash_entry"])
            self.assertEqual(caught.exception.code, "trash_payload_missing")
            with self.assertRaises(ce.ChapterError) as caught:
                ce.restore_trash(project, "../" + missing["trash_entry"])
            self.assertEqual(caught.exception.code, "trash_entry_invalid")

    def test_published_or_staged_fake_receipt_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            seed(project, 2, "二\n", title="第二章")
            state = ce.chapter_state(project, 2)
            receipts = project / ".webnovel" / "writer_receipts.json"
            for payload in ({"published_sha256": state["sha256"]},
                            {"staged_at": "2026-11-26T00:00:00+00:00"},
                            {"publish": {"sha256": state["sha256"]}}):
                receipts.write_text(json.dumps({"2": payload}), encoding="utf-8")
                with self.subTest(payload=payload):
                    with self.assertRaises(ce.ChapterError) as caught:
                        ce.delete_chapter(project, 2,
                                          expected_content_sha256=state["sha256"])
                    self.assertEqual(caught.exception.code, "chapter_published_readonly")
                    self.assertIsNotNone(cv.chapter_path(project, 2))

    @defect
    def test_corrupt_trash_manifest_is_domain_error(self):
        """DEFECT P2: a corrupt manifest escapes as ``PublicationBlocked`` (500).

        ``restore_trash`` calls ``safety.read_json_strict`` directly instead of
        translating its ``PublicationBlocked('invalid_json')`` into a stable
        ``ChapterError('trash_entry_corrupt')``; ``api_v08.guard`` only catches
        ``ChapterError``/``OutlineError``.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            seed(project, 2, "二\n", title="第二章")
            state = ce.chapter_state(project, 2)
            deleted = ce.delete_chapter(project, 2,
                                        expected_content_sha256=state["sha256"])
            manifest = (project / ".webnovel" / "trash" / deleted["trash_entry"]
                        / "manifest.json")
            manifest.write_text("{ not json", encoding="utf-8")
            try:
                entries = ce.list_trash(project)["entries"]
            except Exception as exc:  # noqa: BLE001 - also leaks PublicationBlocked
                self.fail(f"list_trash raised {type(exc).__name__}: {exc}")
            self.assertEqual(entries, [])
            try:
                ce.restore_trash(project, deleted["trash_entry"])
            except ce.ChapterError as exc:
                self.assertEqual(exc.code, "trash_entry_corrupt")
            except Exception as exc:  # noqa: BLE001
                self.fail(f"leaked {type(exc).__name__}: {exc}")
            else:
                self.fail("corrupt manifest was restored")

    @defect
    def test_restore_rejects_manifest_filename_outside_archive(self):
        """DEFECT P1 (security): ``manifest['filename']`` is trusted as a path.

        ``restore_trash`` joins the manifest filename without containment
        checks.  An absolute path (or ``../`` traversal) is read and committed
        byte-for-byte as the restored chapter, allowing arbitrary local files
        to be imported into ``正文/``.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            secret = Path(folder) / "secret.md"
            secret.write_text("外部机密内容\n", encoding="utf-8")
            seed(project, 1, "一\n")
            seed(project, 2, "二\n", title="第二章")
            state = ce.chapter_state(project, 2)
            deleted = ce.delete_chapter(project, 2,
                                        expected_content_sha256=state["sha256"])
            manifest_path = (project / ".webnovel" / "trash"
                             / deleted["trash_entry"] / "manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["filename"] = str(secret)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ce.ChapterError):
                ce.restore_trash(project, deleted["trash_entry"])
            restored = cv.chapter_path(project, 2)
            self.assertIsNone(restored)
            self.assertNotIn("外部机密内容", "\n".join(
                p.read_text(encoding="utf-8")
                for p in (project / "正文").glob("*.md")))

    @defect
    def test_restore_rejects_tampered_payload(self):
        """DEFECT P1 (integrity): archived bytes are not checked against the manifest.

        ``delete_chapter`` records ``content_sha256`` but ``restore_trash``
        never verifies the payload; a corrupted/tampered trash file is silently
        committed as a new official version and the returned sha differs from
        the manifest.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            seed(project, 2, "二\n", title="第二章")
            state = ce.chapter_state(project, 2)
            deleted = ce.delete_chapter(project, 2,
                                        expected_content_sha256=state["sha256"])
            archive = project / ".webnovel" / "trash" / deleted["trash_entry"]
            manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
            payload = archive / manifest["filename"]
            payload.write_text("被篡改的正文\n", encoding="utf-8")
            with self.assertRaises(ce.ChapterError):
                ce.restore_trash(project, deleted["trash_entry"])
            self.assertIsNone(cv.chapter_path(project, 2))

    @defect
    def test_second_delete_in_same_second_does_not_crash(self):
        """DEFECT P2: trash directory names only have second resolution.

        ``delete -> restore -> delete`` inside one wall-clock second calls
        ``archive.mkdir(exist_ok=False)`` on an existing directory and raises a
        bare ``FileExistsError`` (500).  Reproduced deterministically by
        freezing ``chapter_editor.datetime``.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            real_datetime = ce.datetime

            class FrozenDateTime(real_datetime):
                @classmethod
                def now(cls, tz=None):
                    stamp = real_datetime(2026, 1, 1, 12, 0, 0)
                    return stamp.replace(tzinfo=tz) if tz else stamp

            ce.datetime = FrozenDateTime
            try:
                first = ce.delete_chapter(
                    project, 1,
                    expected_content_sha256=cv.file_sha256(cv.chapter_path(project, 1)))
                ce.restore_trash(project, first["trash_entry"])
                second = ce.delete_chapter(
                    project, 1,
                    expected_content_sha256=cv.file_sha256(cv.chapter_path(project, 1)))
                self.assertEqual(second["status"], "deleted")
            except Exception as exc:  # noqa: BLE001 - bare FileExistsError is the defect
                self.fail(f"second delete raised {type(exc).__name__}: {exc}")
            finally:
                ce.datetime = real_datetime

    @defect
    def test_delete_requires_expected_version_identity(self):
        """DEFECT P2: ``expected_version_id`` is accepted but never checked.

        The plan requires DELETE to carry ``expected_version_id``; passing a
        bogus identity while the content sha still matches deletes the chapter.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            sha = cv.file_sha256(cv.chapter_path(project, 1))
            with self.assertRaises(ce.ChapterError):
                ce.delete_chapter(project, 1,
                                  expected_version_id="ver_9999_deadbeef",
                                  expected_content_sha256=sha)
            self.assertIsNotNone(cv.chapter_path(project, 1))


class SplitTest(unittest.TestCase):
    def test_split_rejects_boundary_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "甲😀乙")
            state = ce.chapter_state(project, 1)
            before = cv.chapter_path(project, 1).read_bytes()
            for offset in (0, -1, len(state["content"]), len(state["content"]) + 3):
                with self.subTest(offset=offset):
                    with self.assertRaises(ce.ChapterError) as caught:
                        ce.split_chapter(project, 1, offset=offset,
                                         expected_content_sha256=state["sha256"])
                    self.assertEqual(caught.exception.code, "split_offset_invalid")
                    self.assertEqual(cv.chapter_path(project, 1).read_bytes(), before)
                    self.assertEqual(sorted(cv.chapter_map(project)), [1])

    def test_split_emoji_boundary_keeps_all_characters(self):
        original = "甲乙😀丙丁戊"
        for offset in (1, 3, len(original) - 1):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as folder:
                project = make_project(folder)
                seed(project, 1, original)
                state = ce.chapter_state(project, 1)
                ce.split_chapter(project, 1, offset=offset,
                                 expected_content_sha256=state["sha256"],
                                 op_id=f"emoji-split-{offset}")
                first = cv.chapter_path(project, 1).read_text(encoding="utf-8")
                second = cv.chapter_path(project, 2).read_text(encoding="utf-8")
                self.assertTrue(first.endswith("\n"))
                self.assertEqual(first[:-1] + second, original)

    @defect
    def test_split_at_space_boundary_preserves_characters(self):
        """DEFECT P2: ``first.rstrip()`` drops meaningful whitespace at the split.

        Splitting ``abc def`` at offset 4 (after the space) turns the space into
        the inserted newline: ``abc\\n`` + ``def``.  The contract says no bytes
        may be lost or reordered; only an inserted boundary newline is allowed.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            original = "abc def"
            seed(project, 1, original)
            state = ce.chapter_state(project, 1)
            ce.split_chapter(project, 1, offset=4,
                             expected_content_sha256=state["sha256"],
                             op_id="space-split")
            first = cv.chapter_path(project, 1).read_text(encoding="utf-8")
            second = cv.chapter_path(project, 2).read_text(encoding="utf-8")
            self.assertEqual(first[:-1] + second, original)

    @defect
    def test_split_failure_leaves_no_orphan_chapter(self):
        """DEFECT P1: rollback restores index+first half but leaks chapter N+1.

        The ``except`` block in ``split_chapter`` rewrites the original file and
        restores the index snapshot, but it never removes the second chapter
        file already written by the failed ``commit_raw_bytes``.  The result is
        a chapter present in ``chapter_map``/on disk but absent from
        ``index.json``, so retrying split sees a non-tail chapter and the index
        is permanently inconsistent until manual cleanup.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            original = "第一段。\n\n第二段。\n"
            seed(project, 1, original)
            state = ce.chapter_state(project, 1)
            real_commit = cv.commit_raw_bytes

            def failing_commit(prj, chapter, data, **kwargs):
                if chapter == 2:
                    cv._write_chapter_bytes(prj, chapter, bytes(data),
                                            kwargs.get("title") or "")
                    raise OSError("disk full while committing second half")
                return real_commit(prj, chapter, data, **kwargs)

            cv.commit_raw_bytes = failing_commit
            try:
                with self.assertRaises(Exception):
                    ce.split_chapter(project, 1, offset=original.index("第二段"),
                                     expected_content_sha256=state["sha256"],
                                     op_id="fail-split")
            finally:
                cv.commit_raw_bytes = real_commit
            self.assertEqual(cv.chapter_path(project, 1).read_bytes(),
                             original.encode("utf-8"))
            self.assertEqual(sorted(cv.chapter_map(project)),
                             sorted(int(key) for key in
                                    cv.load_index(project)["chapters"].keys()))


class ImportTest(unittest.TestCase):
    def test_preview_handles_bom_crlf_and_is_zero_write(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "\ufeff第1章 开端\r\n正文甲\r\n\r\n第2章：转折\r\n正文乙\r\n"
            before = sorted(p.name for p in (project / "正文").glob("*"))
            preview = ce.import_preview(project, text=text)
            self.assertEqual(preview["count"], 2)
            self.assertEqual([item["title"] for item in preview["chapters"]],
                             ["开端", "转折"])
            self.assertTrue(all("\r" not in item["content"]
                                and "\ufeff" not in item["content"]
                                for item in preview["chapters"]))
            self.assertEqual(sorted(p.name for p in (project / "正文").glob("*")),
                             before)
            self.assertEqual(cv.chapter_map(project), {})

    def test_import_duplicate_start_chapter_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            before = {p.name: p.read_bytes() for p in (project / "正文").glob("*.md")}
            with self.assertRaises(ce.ChapterError) as caught:
                ce.import_chapters(
                    project, text="第1章 一\n新内容\n第2章 二\n二内容\n",
                    start_chapter=1, preview=False, op_id="dup-start")
            self.assertEqual(caught.exception.code, "chapter_exists")
            after = {p.name: p.read_bytes() for p in (project / "正文").glob("*.md")}
            self.assertEqual(before, after)

    @defect
    def test_import_is_atomic_when_later_chapter_conflicts(self):
        """DEFECT P1: import writes earlier chapters before reporting a conflict.

        Existing chapters 1 and 3 plus ``start_chapter=2`` imports chapter 2,
        then hits chapter 3 and returns ``chapter_exists``.  The caller sees a
        409 but chapter 2 has already been committed and indexed; retrying the
        identical import can never succeed.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "一\n")
            seed(project, 3, "三\n", title="第三章")
            with self.assertRaises(ce.ChapterError) as caught:
                ce.import_chapters(
                    project,
                    text="第2章 二\n第二章正文\n第3章 三\n第三章正文\n",
                    start_chapter=2, preview=False, op_id="partial-import")
            self.assertEqual(caught.exception.code, "chapter_exists")
            self.assertIsNone(cv.chapter_path(project, 2))
            self.assertEqual(len(cv.list_versions(project, 2)), 0)

    @defect
    def test_import_matches_heading_without_separator(self):
        """DEFECT P2: ``第1章开端`` (no space) is not recognised as a heading.

        ``_CHAPTER_HEADING`` ends with ``\\b``; when the title starts with
        another word character (the normal Chinese web-novel form), no boundary
        exists and the whole file previews as zero chapters.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            preview = ce.import_preview(project, text="第1章开端\n正文甲\n")
            self.assertEqual(preview["count"], 1)
            self.assertEqual(preview["chapters"][0]["content"].strip(), "正文甲")

    def test_huge_import_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "x" * (ce.MAX_IMPORT_BYTES + 1)
            with self.assertRaises(ce.ChapterError) as caught:
                ce.import_preview(project, text=text)
            self.assertEqual(caught.exception.status, 413)
            self.assertEqual(cv.chapter_map(project), {})


class QuickCheckTest(unittest.TestCase):
    def test_large_disk_file_is_local_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "x")
            text = "正常文本。" * 200000  # ~3 MB, exceeds the save limit on purpose
            cv.chapter_path(project, 1).write_text(text, encoding="utf-8")
            started = time.perf_counter()
            result = ce.quick_check(project, 1)
            elapsed = time.perf_counter() - started
            self.assertEqual(result["model_calls"], 0)
            self.assertGreaterEqual(result["issue_count"], 0)
            self.assertLess(elapsed, 5.0)

    def test_malicious_quotes_stay_local_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "x")
            text = "“" * 60000  # ~180 KB, inside the 200 KB save limit
            started = time.perf_counter()
            result = ce.quick_check(project, 1, content=text)
            elapsed = time.perf_counter() - started
            self.assertEqual(result["model_calls"], 0)
            self.assertLess(elapsed, 3.0)
            self.assertGreaterEqual(result["issue_count"], 1)

    @defect
    def test_quick_check_1mb_buffer_does_not_throw(self):
        """DEFECT P2: ``quick_check`` reuses the 200 KB save cap for editor buffers.

        A 1 MB unsaved buffer (or a 1 MB chapter produced by an external
        editor) is rejected with ``content_too_large`` instead of being checked
        locally and bounded.  Reading a 1 MB file from disk works, so the two
        entry paths disagree.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project, 1, "x")
            try:
                result = ce.quick_check(project, 1, content="a" * (1024 * 1024))
            except Exception as exc:  # noqa: BLE001 - throwing is the defect
                self.fail(f"quick_check raised {type(exc).__name__}: {exc}")
            self.assertEqual(result["model_calls"], 0)
            self.assertIn("issue_count", result)


class IdempotencyTest(unittest.TestCase):
    def test_completed_response_replays_after_module_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            payload = {"title": "开端", "content": "重放稿\n", "op_id": "replay-1",
                       "expected_version_id": state["version_id"],
                       "expected_content_sha256": state["sha256"]}
            first = ce.save_version(project, 1, dict(payload))
            module = importlib.reload(ce)
            second = module.save_version(project, 1, dict(payload))
            self.assertTrue(second.get("reused"))
            self.assertEqual(first["content_sha256"], second["content_sha256"])
            self.assertEqual(len(cv.list_versions(project, 1)), 2)

    def test_mismatched_params_are_409_and_do_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            first = save(project, 1, "第一稿\n", op_id="mismatch-1",
                         expected_version_id=state["version_id"],
                         expected_content_sha256=state["sha256"])
            before = cv.chapter_path(project, 1).read_bytes()
            with self.assertRaises(ce.ChapterError) as caught:
                save(project, 1, "第二稿\n", op_id="mismatch-1",
                     expected_version_id=state["version_id"],
                     expected_content_sha256=state["sha256"])
            self.assertEqual(caught.exception.code, "op_id_params_mismatch")
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(cv.chapter_path(project, 1).read_bytes(), before)
            self.assertEqual(len(cv.list_versions(project, 1)), 2)
            self.assertEqual(first["content_sha256"], cv.file_sha256(
                cv.chapter_path(project, 1)))

    @defect
    def test_corrupt_receipt_does_not_report_failure_after_commit(self):
        """DEFECT P2: a malformed receipt entry fails the response after commit.

        ``_read_receipts`` validates only the top-level JSON object, so a list
        value makes ``_published_state`` raise ``AttributeError`` *after*
        ``write_chapter`` committed the new body and version.  The API returns
        500 although the save happened, and the idempotency key is left
        in_progress.
        """
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            state = ce.chapter_state(project, 1)
            path = cv.chapter_path(project, 1)
            before = {"bytes": path.read_bytes(), "versions": len(cv.list_versions(project, 1)),
                      "current": cv.load_index(project)["chapters"]["1"]["current"]}
            (project / ".webnovel" / "writer_receipts.json").write_text(
                json.dumps({"1": ["not-a-dict"]}), encoding="utf-8")
            try:
                ce.save_version(project, 1, {
                    "title": "开端", "content": "改稿\n", "op_id": "receipt-1",
                    "expected_version_id": state["version_id"],
                    "expected_content_sha256": state["sha256"]})
            except ce.ChapterError:
                pass
            except Exception as exc:  # noqa: BLE001
                self.fail(f"leaked {type(exc).__name__}: {exc}")
            after = {"bytes": path.read_bytes(), "versions": len(cv.list_versions(project, 1)),
                     "current": cv.load_index(project)["chapters"]["1"]["current"]}
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
