"""崩溃故障注入与重启恢复测试（plan 09 §3.2，v0.8 波次）。

每个故障点都用独立子进程 ``os._exit()`` 强杀，父测试进程只读取磁盘现场并
调用公开恢复入口。测试不修改生产代码，也不依赖仓库当前工作目录。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fanqie_auto_publish.publication_safety import PublicationBlocked
from integration import chapter_editor
from integration import chapter_versions as cv
from integration import outline_editor as oe
from integration import transaction_journal as journal
from integration import workbench_db as wb

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_bytes(text: str) -> bytes:
    return text.encode("utf-8")


class CrashCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-crash-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "书"
        for name in ("正文", "大纲", "设定", ".webnovel/chapter_versions/objects"):
            (self.project / name).mkdir(parents=True, exist_ok=True)

    def crash(self, expected: int, script: str, *args) -> None:
        """Run ``script`` in a child interpreter and require a hard exit code."""
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(BACKEND)
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", script,
             str(self.project), *[str(item) for item in args]],
            capture_output=True, text=True, encoding="utf-8",
            env=environment, cwd=str(REPO), timeout=60,
        )
        self.assertEqual(
            result.returncode, expected,
            f"子进程未按预期强杀：rc={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def assert_exact(self, path: Path, text: str) -> None:
        data = path.read_bytes()
        self.assertEqual(data, text_bytes(text))
        self.assertEqual(sha256(data), sha256(text_bytes(text)))


class JournalCrashTest(CrashCase):
    def test_crash_after_prepare_recovers_only_from_tx_and_staged_bytes(self):
        content_one = "第一章崩溃恢复稿\n第二行。\n"
        content_two = "第二章崩溃恢复稿\n"
        script = """
import os, sys
from integration import transaction_journal as journal
journal.prepare(sys.argv[1], [
    {"kind": "write", "path": "正文/第1章-崩溃.md", "content": sys.argv[2]},
    {"kind": "write", "path": "正文/第2章-崩溃.md", "content": sys.argv[3]},
])
os._exit(41)
"""
        self.crash(41, script, content_one, content_two)

        active = journal.pending(self.project)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["state"], "prepared")
        tx_id = active[0]["tx_id"]
        staged = journal.tx_root(self.project) / tx_id / "step_000.bin"
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), text_bytes(content_one))

        # 崩溃后 index.json 可以任意损坏；事务恢复只能信任 tx.json 与暂存字节。
        index_path = self.project / ".webnovel" / "chapter_versions" / "index.json"
        index_path.write_text("{ 这不是可解析的 index", encoding="utf-8")
        with self.assertRaises(journal.RecoveryInProgress):
            journal.assert_readable(self.project)

        summaries = journal.recover(self.project)
        self.assertEqual(summaries[0]["action"], "applied")
        self.assertEqual(summaries[0]["state"], "done")
        self.assert_exact(self.project / "正文" / "第1章-崩溃.md", content_one)
        self.assert_exact(self.project / "正文" / "第2章-崩溃.md", content_two)
        self.assertEqual(index_path.read_text(encoding="utf-8"), "{ 这不是可解析的 index")
        journal.assert_readable(self.project)
        self.assertEqual(journal.pending(self.project), [])

    def test_crash_while_applying_finishes_remaining_steps_after_restart(self):
        content_one = "已写但未推进 done\n"
        content_two = "第二步尚未写入\n"
        doomed = self.project / "正文" / "第9章-待删.md"
        doomed.write_text("等待删除\n", encoding="utf-8")
        tx_id = journal.prepare(self.project, [
            {"kind": "write", "path": "正文/第1章-应用崩溃.md", "content": content_one},
            {"kind": "write", "path": "正文/第2章-应用崩溃.md", "content": content_two},
            {"kind": "delete", "path": "正文/第9章-待删.md"},
        ])

        script = """
import os, sys
from integration import transaction_journal as journal
real = journal._apply_step
def killer(project, record, step):
    real(project, record, step)
    if int(step.get("index")) == 0:
        os._exit(42)
journal._apply_step = killer
journal.apply(sys.argv[1], sys.argv[2])
"""
        self.crash(42, script, tx_id)

        record = json.loads((journal.tx_root(self.project) / f"tx_{tx_id}.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "applying")
        self.assertEqual(record["done"], [])
        self.assert_exact(self.project / "正文" / "第1章-应用崩溃.md", content_one)
        self.assertFalse((self.project / "正文" / "第2章-应用崩溃.md").exists())
        self.assertTrue(doomed.is_file())

        index_path = self.project / ".webnovel" / "chapter_versions" / "index.json"
        index_path.write_text("broken-before-recover", encoding="utf-8")
        summaries = journal.recover(self.project)

        self.assertEqual(summaries[0]["action"], "applied")
        self.assert_exact(self.project / "正文" / "第1章-应用崩溃.md", content_one)
        self.assert_exact(self.project / "正文" / "第2章-应用崩溃.md", content_two)
        self.assertFalse(doomed.exists())
        self.assertEqual(index_path.read_text(encoding="utf-8"), "broken-before-recover")
        self.assertEqual(journal.pending(self.project), [])

    def test_recovery_uses_staged_index_instead_of_corrupt_disk_index(self):
        chapter = self.project / "正文" / "第1章-旧.md"
        chapter.write_text("旧正文\n", encoding="utf-8")
        staged_index = json.dumps(
            {"schema_version": 1, "chapters": {"1": {"current": "a" * 64}}},
            ensure_ascii=False, indent=2,
        ) + "\n"
        journal.prepare(self.project, [
            {"kind": "write", "path": "正文/第1章-旧.md", "content": "新正文\n"},
            {"kind": "write", "path": ".webnovel/chapter_versions/index.json",
             "content": staged_index},
        ])
        index_path = self.project / ".webnovel" / "chapter_versions" / "index.json"
        index_path.write_text("{ 坏 index", encoding="utf-8")

        summary = journal.recover(self.project)

        self.assertEqual(summary[0]["action"], "applied")
        self.assertEqual(summary[0]["state"], "done")
        self.assert_exact(chapter, "新正文\n")
        self.assertEqual(index_path.read_text(encoding="utf-8"), staged_index)


class ChapterVersionCrashTest(CrashCase):
    def seed(self) -> str:
        cv.write_chapter(self.project, 1, "旧正文\n", op_id="seed-1",
                         title="开端", allow_new=True)
        return cv.file_sha256(cv.chapter_path(self.project, 1))

    def commit_record(self, op_id: str) -> dict:
        path = cv.store_root(self.project) / "commits" / f"{op_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_crash_after_object_before_chapter_recovers_forward(self):
        old_sha = self.seed()
        new_text = "对象已写、正文未写的新稿\n"
        candidate = cv.save_candidate(self.project, 1, new_text, op_id="candidate-object",
                                      source="crash-test", title="开端")
        script = """
import os, sys
from integration import chapter_versions as cv
def killer(*args, **kwargs):
    os._exit(43)
cv._write_chapter_bytes = killer
cv.commit_candidate(sys.argv[1], 1, sys.argv[2], op_id="crash-after-object",
                    expected_sha256=sys.argv[3], title="开端")
"""
        self.crash(43, script, candidate["candidate_id"], old_sha)

        record = self.commit_record("crash-after-object")
        self.assertEqual(record["state"], "prepared")
        self.assertEqual(record["done"], ["object"])
        self.assertEqual(cv.file_sha256(cv.chapter_path(self.project, 1)), old_sha)
        object_path = cv.store_root(self.project) / "objects" / f"{candidate['sha256']}.txt"
        self.assertTrue(object_path.is_file())

        cv.recover_pending(self.project)

        record = self.commit_record("crash-after-object")
        self.assertEqual(record["state"], "committed")
        path = cv.chapter_path(self.project, 1)
        self.assertEqual(path.read_bytes(), text_bytes(new_text))
        self.assertEqual(cv.file_sha256(path), candidate["sha256"])
        entry = cv.load_index(self.project)["chapters"]["1"]
        self.assertEqual(entry["current"], candidate["sha256"])
        self.assertTrue(entry["current_version_id"].startswith("ver_"))
        self.assertEqual(cv.current_version(self.project, 1)["sha256"], candidate["sha256"])
        self.assertEqual(cv.read_version(self.project, 1)["text"], new_text)

    def crash_after_chapter_before_index(self):
        old_sha = self.seed()
        new_text = "正文已换、索引未换的新稿\n"
        candidate = cv.save_candidate(self.project, 1, new_text, op_id="candidate-chapter",
                                      source="crash-test", title="开端")
        script = """
import os, sys
from integration import chapter_versions as cv
def killer(*args, **kwargs):
    os._exit(44)
cv._save_index = killer
cv.commit_candidate(sys.argv[1], 1, sys.argv[2], op_id="crash-after-chapter",
                    expected_sha256=sys.argv[3], title="开端")
"""
        self.crash(44, script, candidate["candidate_id"], old_sha)
        return old_sha, candidate, new_text

    def test_crash_after_chapter_before_index_preserves_new_bytes(self):
        old_sha, candidate, new_text = self.crash_after_chapter_before_index()

        record = self.commit_record("crash-after-chapter")
        self.assertEqual(record["state"], "chapter_written")
        self.assertIn("chapter", record["done"])
        path = cv.chapter_path(self.project, 1)
        self.assertEqual(path.read_bytes(), text_bytes(new_text))
        self.assertEqual(cv.file_sha256(path), candidate["sha256"])
        self.assertEqual(cv.load_index(self.project)["chapters"]["1"]["current"], old_sha)
        object_path = cv.store_root(self.project) / "objects" / f"{candidate['sha256']}.txt"
        self.assertTrue(object_path.is_file())

        # 即使当前恢复器把该现场标记为 conflict，也绝不能丢稿或改回旧字节。
        cv.recover_pending(self.project)
        self.assertEqual(path.read_bytes(), text_bytes(new_text))
        self.assertEqual(cv.file_sha256(path), candidate["sha256"])
        self.assertTrue(object_path.is_file())

    def test_crash_after_chapter_before_index_recovers_forward(self):
        old_sha, candidate, new_text = self.crash_after_chapter_before_index()

        cv.recover_pending(self.project)

        record = self.commit_record("crash-after-chapter")
        self.assertEqual(record["state"], "committed",
                         f"正文已写但索引未写时必须向前恢复；实际 {record}")
        entry = cv.load_index(self.project)["chapters"]["1"]
        self.assertEqual(entry["current"], candidate["sha256"])
        self.assertEqual(entry["current_version_id"], record.get("version_id"))
        self.assertEqual(cv.current_version(self.project, 1)["sha256"], candidate["sha256"])
        self.assertEqual(cv.read_version(self.project, 1)["text"], new_text)


class OutlineCrashTest(CrashCase):
    def test_crash_after_authoritative_md_before_story_plan(self):
        name = "AI规划-0001-0003.md"
        initial = (
            "## 第1章 开端\n旧细纲一\n\n"
            "## 第2章 承继\n旧细纲二\n\n"
            "## 第3章 结尾\n旧结尾\n"
        )
        updated = (
            "## 第1章 开端\n旧细纲一\n\n"
            "## 第2章 承继\n旧细纲二\n\n"
            "## 第3章 结尾\n新结局：主角归来。\n"
        )
        oe.create_file(self.project, filename=name, content=initial)
        revision = oe.read_file(self.project, name)["revision"]
        (self.project / ".webnovel" / "story_plan.json").write_text(
            json.dumps({"chapters": {"3": {"id": 3, "title": "结尾", "outline": "旧结尾"}}},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

        script = """
import os, sys
from integration import outline_editor as oe
def killer(*args, **kwargs):
    os._exit(45)
oe._sync_story_plan = killer
oe.write_file(sys.argv[1], "AI规划-0001-0003.md", content=sys.argv[2],
              revision=sys.argv[3])
"""
        self.crash(45, script, updated, revision)

        md_path = self.project / "大纲" / name
        self.assertIn("新结局：主角归来。", md_path.read_text(encoding="utf-8"))
        stale = json.loads((self.project / ".webnovel" / "story_plan.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(stale["chapters"]["3"]["outline"], "旧结尾")

        recovered = oe.recover_plan(self.project, persist=True)

        self.assertEqual(recovered["chapters"]["3"]["outline"], "新结局：主角归来。")
        index = json.loads((self.project / ".webnovel" / "story_plan.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(index["chapters"]["3"]["outline"], "新结局：主角归来。")
        self.assertIsInstance(recovered["chapters"]["3"]["chapter_rev"], int)


class DraftCrashTest(CrashCase):
    def test_crash_mid_draft_delete_rolls_back_and_keeps_draft(self):
        wb.initialize(self.project)
        draft = wb.save_draft(self.project, 1, title="开端", content="作者未保存草稿\n",
                              expected_draft_epoch=0, expected_draft_revision=0)
        script = """
import os, sys
from contextlib import contextmanager
from integration import workbench_db as wb
@contextmanager
def crash_tx(project):
    with wb.connect(project) as db:
        db.execute("BEGIN IMMEDIATE")
        yield db
        os._exit(46)
wb.write_tx = crash_tx
wb.delete_draft(sys.argv[1], 1, draft_id=sys.argv[2])
"""
        self.crash(46, script, draft["draft_id"])

        survived = wb.get_draft(self.project, 1)
        self.assertIsNotNone(survived)
        self.assertEqual(survived["draft_id"], draft["draft_id"])
        self.assertEqual(survived["draft_revision"], draft["draft_revision"])
        self.assertEqual(survived["content"], "作者未保存草稿\n")
        meta = {row["chapter_id"]: row for row in wb.list_chapter_meta(self.project)}[1]
        self.assertEqual(meta["draft_epoch"], draft["draft_epoch"])

        retried = wb.delete_draft(self.project, 1, draft_id=draft["draft_id"])
        self.assertTrue(retried["deleted"])
        self.assertIsNone(wb.get_draft(self.project, 1))
        meta = {row["chapter_id"]: row for row in wb.list_chapter_meta(self.project)}[1]
        self.assertEqual(meta["draft_epoch"], draft["draft_epoch"] + 1)


class BackupBarrierCrashTest(CrashCase):
    def test_backup_barrier_times_out_while_crashed_tx_is_pending(self):
        (self.project / "正文" / "第1章-正常.md").write_text("正常正文\n", encoding="utf-8")
        (self.project / ".webnovel" / "chapter_versions" / "index.json").write_text(
            json.dumps({"schema_version": 1, "chapters": {}}), encoding="utf-8")
        script = """
import os, sys
from integration import transaction_journal as journal
journal.prepare(sys.argv[1], [
    {"kind": "write", "path": "正文/第2章-待完成.md", "content": "待完成正文\\n"},
])
os._exit(49)
"""
        self.crash(49, script)
        self.assertEqual(len(journal.pending(self.project)), 1)
        destination = self.root / "备份"
        with self.assertRaises(journal.BarrierTimeout):
            journal.backup(self.project, destination, wait_seconds=0.1)
        self.assertFalse(destination.exists())

        recovered = journal.recover(self.project)
        self.assertEqual(recovered[0]["action"], "applied")
        summary = journal.backup(self.project, destination, wait_seconds=1.0)
        self.assertGreaterEqual(summary["files"], 2)
        inspected = journal.inspect_backup(destination)
        self.assertTrue(inspected["valid"], inspected["problems"])
        self.assertEqual((destination / "正文" / "第2章-待完成.md").read_text(encoding="utf-8"),
                         "待完成正文\n")


class TrashCrashTest(CrashCase):
    def seed(self) -> str:
        cv.write_chapter(self.project, 1, "第一章正文\n", op_id="trash-1",
                         title="一", allow_new=True)
        cv.write_chapter(self.project, 2, "第二章正文\n", op_id="trash-2",
                         title="二", allow_new=True)
        return cv.file_sha256(cv.chapter_path(self.project, 2))

    def test_crash_before_unlink_keeps_chapter_and_archive_copy(self):
        sha_two = self.seed()
        script = """
import os, sys
from pathlib import Path
from integration import chapter_editor as ce
real = ce.os.replace
body = Path(sys.argv[1]) / "正文"
def killer(src, dst):
    if Path(src).parent == body and Path(dst).parent.parent == Path(sys.argv[1]) / ".webnovel" / "trash":
        os._exit(47)
    return real(src, dst)
ce.os.replace = killer
ce.delete_chapter(sys.argv[1], 2, expected_content_sha256=sys.argv[2],
                  op_id="crash-trash-before-unlink")
"""
        self.crash(47, script, sha_two)

        chapter = self.project / "正文" / "第2章-二.md"
        self.assertTrue(chapter.is_file())
        self.assertEqual(cv.file_sha256(chapter), sha_two)
        entries = chapter_editor.list_trash(self.project)["entries"]
        self.assertEqual(len(entries), 1)
        archive = self.project / ".webnovel" / "trash" / entries[0]["entry"]
        self.assertEqual(entries[0]["content_sha256"], sha_two)
        self.assertEqual((archive / "original.md").read_bytes(), chapter.read_bytes())

    def test_crash_after_unlink_restores_from_trash_without_loss(self):
        sha_two = self.seed()
        script = """
import os, sys
from pathlib import Path
from integration import chapter_editor as ce
real = ce.os.replace
body = Path(sys.argv[1]) / "正文"
trash = Path(sys.argv[1]) / ".webnovel" / "trash"
def killer(src, dst):
    result = real(src, dst)
    if Path(src).parent == body and Path(dst).parent.parent == trash:
        os._exit(48)
    return result
ce.os.replace = killer
ce.delete_chapter(sys.argv[1], 2, expected_content_sha256=sys.argv[2],
                  op_id="crash-trash-after-unlink")
"""
        self.crash(48, script, sha_two)

        self.assertFalse((self.project / "正文" / "第2章-二.md").exists())
        self.assertNotIn(2, cv.chapter_map(self.project))
        entries = chapter_editor.list_trash(self.project)["entries"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]["entry"]
        archive = self.project / ".webnovel" / "trash" / entry
        archived_file = archive / entries[0]["filename"]
        self.assertTrue(archived_file.is_file())
        self.assertEqual(sha256(archived_file.read_bytes()), sha_two)

        restored = chapter_editor.restore_trash(self.project, entry, op_id="restore-after-crash")

        self.assertEqual(restored["chapter_id"], 2)
        path = cv.chapter_path(self.project, 2)
        self.assertEqual(path.read_bytes(), text_bytes("第二章正文\n"))
        self.assertEqual(cv.file_sha256(path), sha_two)
        self.assertEqual(cv.current_version(self.project, 2)["sha256"], sha_two)


class SkippedWorkerCrashTest(CrashCase):
    @unittest.skip("v0.8 波次未包含 worker committing/recovery_required 恢复（plan 09 §3.2 #3）")
    def test_worker_committing_to_recovery_required_is_not_in_this_wave(self):
        pass


class JournalTrustTest(CrashCase):
    def test_corrupt_index_is_never_trusted_or_repaired_by_journal(self):
        index_path = self.project / ".webnovel" / "chapter_versions" / "index.json"
        index_path.write_text(json.dumps({"schema_version": 1, "chapters": {}}),
                              encoding="utf-8")
        journal.prepare(self.project, [
            {"kind": "write", "path": "正文/第1章-可信.md", "content": "事务字节\n"},
        ])
        index_path.write_bytes("{ 损坏的 index".encode("utf-8"))
        before = index_path.read_bytes()

        summary = journal.recover(self.project)

        self.assertEqual(summary[0]["action"], "applied")
        self.assertEqual((self.project / "正文" / "第1章-可信.md").read_bytes(),
                         text_bytes("事务字节\n"))
        self.assertEqual(index_path.read_bytes(), before)


class RestoreExactnessTest(CrashCase):
    def test_restored_chapter_bytes_and_sha_are_exact(self):
        original = "\ufeff旧稿第一行\r\n旧稿第二行\r\n".encode("utf-8")
        path = self.project / "正文" / "第1章-原稿.md"
        path.write_bytes(original)
        adopted = cv.adopt_legacy(self.project, 1)[0]
        cv.write_chapter(self.project, 1, "规范化新稿\n", op_id="edit-1", title="原稿")
        self.assertNotEqual(path.read_bytes(), original)

        restored = cv.restore_version(self.project, 1, adopted["version_id"],
                                       op_id="restore-exact")

        self.assertEqual(restored["state"], "committed")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(cv.file_sha256(path), sha256(original))
        self.assertEqual(cv.current_version(self.project, 1)["sha256"], sha256(original))


class OrphanObjectTest(CrashCase):
    def test_referenced_object_is_never_pruned(self):
        content = "同一份正文被两章引用\n"
        (self.project / "正文" / "第1章-一.md").write_bytes(text_bytes(content))
        (self.project / "正文" / "第2章-二.md").write_bytes(text_bytes(content))
        cv.adopt_legacy(self.project)
        digest = sha256(text_bytes(content))
        object_path = cv.store_root(self.project) / "objects" / f"{digest}.txt"
        self.assertTrue(object_path.is_file())

        first = cv.prune_adopted(self.project, chapter=1)

        self.assertEqual(first["removed"], 1)
        self.assertTrue(object_path.is_file(), "另一章仍引用该对象，绝不能删除")
        self.assertEqual(cv.load_index(self.project)["chapters"]["2"]["current"], digest)

        second = cv.prune_adopted(self.project, chapter=2)

        self.assertEqual(second["removed"], 1)
        self.assertFalse(object_path.exists())


class ConcurrentCommitTest(CrashCase):
    def test_two_threads_same_expected_sha_only_one_wins(self):
        cv.write_chapter(self.project, 1, "基线正文\n", op_id="base-1",
                         title="开端", allow_new=True)
        old_sha = cv.file_sha256(cv.chapter_path(self.project, 1))
        first_text = "线程甲提交稿\n"
        second_text = "线程乙提交稿\n"
        first = cv.save_candidate(self.project, 1, first_text, op_id="thread-a",
                                  source="race", title="开端")
        second = cv.save_candidate(self.project, 1, second_text, op_id="thread-b",
                                   source="race", title="开端")
        barrier = threading.Barrier(2)

        def attempt(candidate_id: str, op_id: str):
            barrier.wait(timeout=10)
            try:
                result = cv.commit_candidate(
                    self.project, 1, candidate_id, op_id=op_id,
                    expected_sha256=old_sha, title="开端")
                return ("ok", result)
            except (cv.VersionConflict, PublicationBlocked) as exc:
                return ("rejected", exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: attempt(*item),
                                    ((first["candidate_id"], "op-thread-a"),
                                     (second["candidate_id"], "op-thread-b"))))

        winners = [item for item in results if item[0] == "ok"]
        losers = [item for item in results if item[0] == "rejected"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        winner = winners[0][1]
        winner_sha = winner["content_sha256"]
        winner_text = first_text if winner_sha == first["sha256"] else second_text
        path = cv.chapter_path(self.project, 1)
        self.assertEqual(path.read_bytes(), text_bytes(winner_text))
        self.assertEqual(cv.file_sha256(path), winner_sha)
        entry = cv.load_index(self.project)["chapters"]["1"]
        self.assertEqual(entry["current"], winner_sha)
        self.assertEqual(entry["current_version_id"], winner["version_id"])
        loser_text = second_text if winner_text == first_text else first_text
        self.assertNotEqual(path.read_text(encoding="utf-8"), loser_text)


if __name__ == "__main__":
    unittest.main()
