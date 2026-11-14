"""定点修订的锚点、范围、长度与预览提交（全部离线，不调用模型）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integration import chapter_versions, revision_plan


BODY = (
    "雨停的时候，站台已经空了。\n\n"
    "她把伞收起来，抖了两下，水珠落在地砖上。\n\n"
    "「你等很久了吗？」他问。\n\n"
    "「不久。」她说，「车晚点。」\n\n"
    "广播响了一次，又安静下来。\n"
)


def project_with_body(root: Path, body: str = BODY, chapter: int = 1) -> Path:
    project = root / "book"
    (project / "正文").mkdir(parents=True, exist_ok=True)
    (project / ".webnovel").mkdir(parents=True, exist_ok=True)
    target = project / "正文" / f"第{chapter}章-雨停.md"
    target.write_text(body, encoding="utf-8", newline="\n")
    return project


class AnchorTests(unittest.TestCase):
    def test_anchor_locates_unique_paragraph(self):
        anchor = revision_plan.locate(BODY, "她把伞收起来，抖了两下，水珠落在地砖上。")
        self.assertEqual(anchor["index"], 1)
        self.assertTrue(revision_plan.verify(BODY, anchor))

    def test_repeated_paragraph_is_ambiguous(self):
        text = "他说好。\n\n他说好。\n"
        with self.assertRaises(revision_plan.AnchorRefused) as caught:
            revision_plan.locate(text, "他说好。")
        self.assertEqual(caught.exception.reason, "anchor_ambiguous")

    def test_anchor_rejected_after_paragraph_changes(self):
        anchor = revision_plan.locate(BODY, "广播响了一次，又安静下来。")
        changed = BODY.replace("广播响了一次，又安静下来。", "广播没有再响。")
        with self.assertRaises(revision_plan.AnchorRefused) as caught:
            revision_plan.verify(changed, anchor)
        self.assertIn(caught.exception.reason, {"anchor_paragraph_changed", "anchor_context_changed"})

    def test_apply_edits_skips_repeated_and_unchanged(self):
        text = "他点头。\n\n他点头。\n"
        updated, report = revision_plan.apply_edits(
            text,
            [
                {"original": "他点头。", "replacement": "他颔首。"},
                {"original": "他颔首。", "replacement": "他颔首。"},
            ],
        )
        self.assertEqual(updated, text)
        self.assertEqual(report["applied"], [])
        self.assertEqual(len(report["skipped"]), 2)


class ScopeTests(unittest.TestCase):
    def test_change_outside_patch_is_refused(self):
        before = "第一段。\n\n第二段。\n\n第三段。\n"
        after = "第一段改。\n\n第二段。\n\n第三段改。\n"
        patch = {"applied": [{"original": "第一段。", "replacement": "第一段改。", "reason": "顺句"}]}
        check = revision_plan.check_scope(before, after, patch)
        self.assertFalse(check["ok"])
        self.assertEqual(check["reason"], "outside_patch")

    def test_patch_without_change_reports_no_change(self):
        patch = {"applied": [{"original": "第一段。", "replacement": "第一段。", "reason": "无变化"}]}
        check = revision_plan.check_scope("第一段。\n", "第一段。\n", patch)
        self.assertEqual(check["reason"], "no_change")

    def test_no_applied_edit(self):
        check = revision_plan.check_scope("甲。\n", "甲。\n", {"applied": [], "skipped": []})
        self.assertEqual(check["reason"], "no_applicable_edit")

    def test_inside_patch_passes(self):
        before = "第一段。\n\n第二段。\n"
        after = "第一段。\n\n第二段被改写。\n"
        patch = {"applied": [{"original": "第二段。", "replacement": "第二段被改写。", "reason": "顺句"}]}
        check = revision_plan.check_scope(before, after, patch)
        self.assertTrue(check["ok"], check)


class LengthTests(unittest.TestCase):
    def test_rewrite_growth_guard(self):
        before = "字" * 2000
        after = "字" * 2400
        self.assertEqual(
            revision_plan.validate_length(before, after, chapter=1, mode="rewrite", min_words=1000)["reason"],
            "growth_too_large",
        )

    def test_short_body_may_grow_to_minimum(self):
        before = "字" * 300
        after = "字" * 1200
        check = revision_plan.validate_length(before, after, chapter=1, mode="targeted_fix", min_words=1000)
        self.assertTrue(check["ok"], check)

    def test_below_minimum(self):
        check = revision_plan.validate_length("字" * 900, "字" * 900 + "新增", chapter=1, mode="targeted_fix", min_words=1000)
        self.assertEqual(check["reason"], "below_min_words")

    def test_identical_body(self):
        check = revision_plan.validate_length(BODY, BODY, chapter=1, mode="targeted_fix", min_words=0)
        self.assertEqual(check["reason"], "no_change")


class ClassifyTests(unittest.TestCase):
    def review(self, issues, decision="needs_revision"):
        return {"review_decision": decision, "quality": {"issues": issues}}

    def test_local_style_issue_is_automatic(self):
        plan = revision_plan.classify(
            self.review([{"dimension": "prose", "severity": "advisory", "issue": "句子偏长", "evidence": "第三段"}])
        )
        self.assertEqual(plan["mode"], "targeted_fix")
        self.assertEqual(len(plan["auto"]), 1)
        self.assertEqual(plan["author"], [])

    def test_structural_issue_goes_to_author(self):
        plan = revision_plan.classify(
            self.review([{"dimension": "plot", "severity": "high", "issue": "主角动机前后矛盾", "evidence": "第二章"}])
        )
        self.assertEqual(plan["author"][0]["dimension"], "plot")

    def test_critical_never_automatic(self):
        plan = revision_plan.classify(
            self.review([{"dimension": "style", "severity": "critical", "issue": "文风与设定冲突", "evidence": "全章"}])
        )
        self.assertEqual(plan["auto"], [])

    def test_missing_issues_become_author_item(self):
        plan = revision_plan.classify({"review_decision": "needs_revision"})
        self.assertEqual(plan["mode"], "none")
        self.assertTrue(plan["author"])

    def test_instructions_are_capped(self):
        issues = [
            {"dimension": "prose", "severity": "advisory", "issue": f"问题{i}", "advice": "缩短"}
            for i in range(9)
        ]
        lines = revision_plan.instructions(issues)
        self.assertIn("【定点修订清单】", lines)
        self.assertEqual(lines.count("\n") + 1, revision_plan.MAX_INSTRUCTION_ITEMS + 1)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = project_with_body(self.root)
        self.base = chapter_versions.file_sha256(self.project / "正文" / "第1章-雨停.md")

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, body):
        return revision_plan.save_preview(
            self.project,
            1,
            BODY,
            body,
            base_sha256=self.base,
            contract_hash="",
            mode="targeted_fix",
            auto_issues=[],
            author_issues=[],
            patch_report={"applied": [{"original": "广播响了一次，又安静下来。", "replacement": "广播没有再响。", "reason": "顺句"}]},
            stop_reason="ready",
        )

    def test_preview_does_not_touch_body(self):
        record = self.save(BODY.replace("广播响了一次，又安静下来。", "广播没有再响。"))
        self.assertEqual(
            chapter_versions.file_sha256(self.project / "正文" / "第1章-雨停.md"), self.base
        )
        public = revision_plan.public(self.project, 1)
        self.assertEqual(public["preview"]["preview_id"], record["preview_id"])
        self.assertGreaterEqual(public["preview"]["diff"]["changes"], 1)

    def test_accept_writes_candidate_and_keeps_history(self):
        body = BODY.replace("广播响了一次，又安静下来。", "广播没有再响。")
        record = self.save(body)
        result = revision_plan.accept(self.project, 1, record["preview_id"])
        self.assertEqual(result["status"], "accepted")
        current = (self.project / "正文" / "第1章-雨停.md").read_text(encoding="utf-8")
        self.assertEqual(current.replace("\r\n", "\n"), body)
        versions = chapter_versions.list_versions(self.project, 1)
        self.assertEqual(len(versions), 1)
        self.assertEqual(revision_plan.public(self.project, 1)["preview"], None)

    def test_accept_refuses_after_body_changed(self):
        record = self.save(BODY.replace("广播响了一次，又安静下来。", "广播没有再响。"))
        (self.project / "正文" / "第1章-雨停.md").write_text(BODY + "\n作者补了一句。\n", encoding="utf-8", newline="\n")
        with self.assertRaises(chapter_versions.VersionConflict) as caught:
            revision_plan.accept(self.project, 1, record["preview_id"])
        self.assertEqual(str(caught.exception), "source_changed")

    def test_accept_twice_is_refused(self):
        record = self.save(BODY.replace("广播响了一次，又安静下来。", "广播没有再响。"))
        revision_plan.accept(self.project, 1, record["preview_id"])
        with self.assertRaises(chapter_versions.VersionConflict) as caught:
            revision_plan.accept(self.project, 1, record["preview_id"])
        self.assertEqual(str(caught.exception), "preview_already_closed")

    def test_reject_keeps_body(self):
        record = self.save(BODY.replace("广播响了一次，又安静下来。", "广播没有再响。"))
        result = revision_plan.reject(self.project, 1, record["preview_id"], "不接受这句")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(
            chapter_versions.file_sha256(self.project / "正文" / "第1章-雨停.md"), self.base
        )


if __name__ == "__main__":
    unittest.main()
