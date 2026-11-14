"""版本历史、最佳版本推荐与恢复（离线，不调用模型）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integration import chapter_versions, quality_gate, version_history
from fanqie_auto_publish.publication_safety import body_digest

FIRST = "第一版：雨停。\n\n她把伞收起来。\n"
SECOND = "第二版：雨停了。\n\n她把伞收起来，抖了两下。\n"
THIRD = "第三版：天晴。\n"


def build(root: Path) -> Path:
    project = root / "book"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir()
    chapter_versions.write_chapter(project, 1, FIRST, op_id="op-1", title="雨停", allow_new=True)
    chapter_versions.write_chapter(project, 1, SECOND, op_id="op-2", title="雨停")
    return project


def review(passing: bool, total: int) -> dict:
    scores = {name: total for name in ("setting", "plot", "character", "prose", "dialogue", "style")}
    value = {
        "success": True,
        "review_decision": "pass" if passing else "needs_revision",
        "needs_revision": not passing,
        "quality": {"scores": scores},
    }
    value["quality_gate"] = quality_gate.judge(value)
    return value


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = build(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_versions_are_newest_first_with_current_flag(self):
        data = version_history.history(self.project, 1)
        self.assertEqual([row["seq"] for row in data["versions"]], [2, 1])
        self.assertTrue(data["versions"][0]["current"])
        self.assertFalse(data["versions"][1]["current"])
        self.assertEqual(data["current_version_id"], data["versions"][0]["version_id"])

    def test_quality_and_review_are_linked_by_hash(self):
        first = version_history.history(self.project, 1)["versions"][1]
        quality_gate.save_report(self.project, 1, review(True, 92), body_sha256=first["body_digest"])
        row = version_history.history(self.project, 1)["versions"][1]
        self.assertEqual(row["quality"]["pass"], True)
        self.assertEqual(row["quality"]["total"], 92)

    def test_best_prefers_the_passing_version(self):
        versions = version_history.history(self.project, 1)["versions"]
        old, new = versions[1], versions[0]
        quality_gate.save_report(self.project, 1, review(True, 86), body_sha256=old["body_digest"])
        quality_gate.save_report(self.project, 1, review(False, 99), body_sha256=new["body_digest"])
        best = version_history.best(self.project, 1)
        self.assertEqual(best["status"], "passing")
        self.assertEqual(best["recommended"]["version_id"], old["version_id"])
        self.assertIn("不会自动覆盖", best["note"])

    def test_best_without_passing_version_is_only_a_recommendation(self):
        best = version_history.best(self.project, 1)
        self.assertEqual(best["status"], "no_passing_version")
        self.assertTrue(best["recommended"]["current"])
        current = chapter_versions.read_version(self.project, 1)["text"]
        self.assertEqual(current.replace("\r\n", "\n"), SECOND)

    def test_read_returns_one_version_body(self):
        first = version_history.history(self.project, 1)["versions"][1]
        body = version_history.read(self.project, 1, first["version_id"])
        self.assertEqual(body["body"].replace("\r\n", "\n"), FIRST)
        self.assertEqual(body["bytes"], len(FIRST.encode("utf-8")))


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = build(self.root)
        self.path = next((self.project / "正文").glob("*.md"))
        self.first = version_history.history(self.project, 1)["versions"][1]

    def tearDown(self):
        self.tmp.cleanup()

    def test_restore_writes_a_new_version_and_keeps_the_old_one(self):
        result = version_history.restore(self.project, 1, self.first["version_id"])
        self.assertEqual(result["status"], "restored")
        self.assertEqual(self.path.read_text(encoding="utf-8").replace("\r\n", "\n"), FIRST)
        rows = version_history.history(self.project, 1)["versions"]
        self.assertEqual(rows[0]["source"], "restored")
        self.assertEqual(rows[0]["version_id"], result["version_id"])
        self.assertEqual(len(rows), 3)

    def test_restore_backs_up_uncommitted_author_edits(self):
        self.path.write_text(THIRD, encoding="utf-8", newline="\n")
        result = version_history.restore(self.project, 1, self.first["version_id"])
        backup = version_history.read(self.project, 1, result["backup_version_id"])
        self.assertEqual(backup["body"].replace("\r\n", "\n"), THIRD)
        sources = [row["source"] for row in version_history.history(self.project, 1)["versions"]]
        self.assertIn("backup", sources)

    def test_restore_reports_whether_the_bound_report_still_applies(self):
        first_digest = body_digest(FIRST)
        quality_gate.save_report(self.project, 1, review(True, 90), body_sha256=first_digest)
        stale_before = quality_gate.status(self.project, 1)
        self.assertEqual(stale_before["stale_reason"], "body_changed")
        result = version_history.restore(self.project, 1, self.first["version_id"])
        self.assertTrue(result["report_status"]["valid"], result["report_status"])
        self.assertIsNone(result["report_status"]["stale_reason"])


if __name__ == "__main__":
    unittest.main()
