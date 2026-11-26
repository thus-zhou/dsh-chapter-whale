"""v0.8 版本身份、标题指纹与原始字节恢复契约。"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from integration import chapter_versions as cv


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


class VersionIdentityTest(unittest.TestCase):
    def test_index_keeps_legacy_current_sha_and_adds_version_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            result = cv.write_chapter(project, 1, "正文\n", op_id="op-1", title="开端", allow_new=True)
            index = cv.load_index(project)
            entry = index["chapters"]["1"]
            meta = entry["versions"][0]
            self.assertEqual(entry["current"], meta["sha256"])
            self.assertRegex(entry["current"], r"^[0-9a-f]{64}$")
            self.assertEqual(entry["current_version_id"], meta["version_id"])
            self.assertRegex(meta["version_id"], r"^ver_0001_[0-9a-f]{8}$")
            self.assertEqual(meta["sha256"], meta["content_sha256"])
            self.assertEqual(meta["version_seq"], 1)
            self.assertEqual(result["state"], "committed")
            self.assertEqual(result["version_id"], meta["version_id"])

    def test_title_only_change_creates_new_version_id(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            first = cv.write_chapter(project, 1, "正文不动\n", op_id="op-1", title="旧标题", allow_new=True)
            old_meta = cv.current_version(project, 1)
            second = cv.write_chapter(project, 1, "正文不动\n", op_id="op-2", title="新标题")
            new_meta = cv.current_version(project, 1)
            self.assertEqual(first["content_sha256"], second["content_sha256"])
            self.assertNotEqual(old_meta["version_id"], new_meta["version_id"])
            self.assertEqual(new_meta["title"], "新标题")
            self.assertEqual(cv.load_index(project)["chapters"]["1"]["current"], first["content_sha256"])
            self.assertEqual(cv.current_version(project, 1)["version_id"], new_meta["version_id"])

    def test_version_fingerprint_and_title_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文\n", op_id="op-1", title="  开端  ", allow_new=True)
            meta = cv.current_version(project, 1)
            self.assertEqual(meta["title_digest"], hashlib.sha256("开端".encode("utf-8")).hexdigest())
            expected = hashlib.sha256((meta["sha256"] + "\x00" + meta["title_digest"]).encode("utf-8")).hexdigest()
            self.assertEqual(meta["version_fingerprint"], expected)
            ref = cv.report_ref(project, 1)
            self.assertEqual(ref["version_uid"], meta["version_id"])
            self.assertEqual(ref["version_fingerprint"], expected)

    def test_restore_accepts_both_identities(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "第一版\n", op_id="op-1", title="开端", allow_new=True)
            first = cv.current_version(project, 1)
            cv.write_chapter(project, 1, "第二版\n", op_id="op-2", title="开端")
            # 新身份
            restored = cv.restore_version(project, 1, first["version_id"], op_id="op-r1")
            self.assertEqual(restored["state"], "committed")
            self.assertEqual(cv.read_version(project, 1)["text"], "第一版\n")
            self.assertEqual(cv.current_version(project, 1)["version_id"], restored["version_id"])
            # 历史 64 位 sha 仍可用
            current_sha = cv.current_version(project, 1)["sha256"]
            cv.write_chapter(project, 1, "第三版\n", op_id="op-3", title="开端")
            cv.restore_version(project, 1, current_sha, op_id="op-r2")
            self.assertEqual(cv.read_version(project, 1)["text"], "第一版\n")

    def test_restore_preserves_bom_and_crlf_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            original = "\ufeff旧稿第一行\r\n旧稿第二行\r\n".encode("utf-8")
            path = project / "正文" / "第1章-原稿.md"
            path.write_bytes(original)
            adopted = cv.adopt_legacy(project, 1)[0]
            self.assertEqual(adopted["sha256"], hashlib.sha256(original).hexdigest())

            cv.write_chapter(project, 1, "规范化新稿\n", op_id="op-new", title="原稿")
            self.assertNotEqual(path.read_bytes(), original)

            cv.restore_version(project, 1, adopted["version_id"], op_id="op-restore")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(cv.file_sha256(path), adopted["sha256"])

    def test_restore_without_title_keeps_current_title(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "第一版\n", op_id="op-1", title="开端", allow_new=True)
            first = cv.current_version(project, 1)
            cv.write_chapter(project, 1, "第二版\n", op_id="op-2", title="开端")
            result = cv.restore_version(project, 1, first["version_id"], op_id="op-r",
                                        restore_title=False)
            self.assertEqual(result["state"], "committed")
            self.assertEqual(cv.read_version(project, 1)["text"], "第一版\n")

    def test_write_chapter_triggers_exactly_one_invalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "第一版\n", op_id="save-1", title="开端", allow_new=True)
            log = json.loads((project / ".webnovel" / "invalidation_log.json").read_text(encoding="utf-8"))
            entries = [e for e in log.get("entries", []) if e.get("op_id") == "save-1"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["reason"], "chapter_edited")

    def test_invalid_selector_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文\n", op_id="op-1", title="开端", allow_new=True)
            with self.assertRaises(cv.VersionNotFound):
                cv.read_version(project, 1, "not-a-version")
            with self.assertRaises(cv.VersionNotFound):
                cv.restore_version(project, 1, "ver_9999_deadbeef")


if __name__ == "__main__":
    unittest.main()
