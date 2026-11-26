"""三层批注：锚点、XML 防截断、分诊、A/B 与逐块采纳/撤销。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import annotations as ann
from integration import chapter_editor as ce
from integration import chapter_versions as cv
from integration import text_merge as tm
from integration import workbench_db as wb


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def seed(project, text="雨点敲在铁皮上。\n她推开门。\n"):
    ce.new_chapter(project, {"chapter": 1, "title": "开端", "content": text,
                             "op_id": f"new-{len(text)}"})


def anchor_for(text, quote, occurrence=0):
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = text.find(quote, cursor)
        cursor = start + 1
    if start < 0:
        raise AssertionError("quote not found")
    return {"char_start": start, "char_end": start + len(quote), "quote": quote}


def draft_identity(project):
    draft = wb.get_draft(project, 1)
    return draft or {"draft_id": None, "draft_epoch": 0, "draft_revision": 0}


class CreateAndListTest(unittest.TestCase):
    def test_anchor_snapshot_and_live_relocation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            text = "雨点敲在铁皮上。\n她推开门。\n"
            created = ann.create_annotation(project, 1, {
                "scope": "selection", "instruction": "别直写害怕", "against": "version",
                "anchor": anchor_for(text, "她推开门。")})
            self.assertEqual(created["status"], "created")
            self.assertTrue(created["anchor"]["base_snapshot_id"])
            # 作者在前面插入一段，高亮区间必须随正文移动
            draft = draft_identity(project)
            ce.save_draft(project, 1, {"title": "开端", "content": "新插入的一段。\n" + text,
                                       "expected_draft_id": None, "expected_draft_epoch": 0,
                                       "expected_draft_revision": 0})
            listing = ann.list_annotations(project, 1, against="draft")
            item = listing["annotations"][0]
            self.assertEqual(item["relocated"]["status"], "relocated")
            self.assertEqual(item["range"]["start"], text.index("她推开门。") + len("新插入的一段。\n"))
            self.assertTrue(listing["evaluated_draft_id"])

    def test_anchor_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            with self.assertRaises(ann.AnnotationError) as caught:
                ann.create_annotation(project, 1, {
                    "scope": "selection", "instruction": "x",
                    "anchor": {"char_start": 0, "char_end": 3, "quote": "错误引用"}})
            self.assertEqual(caught.exception.code, "anchor_slice_mismatch")

    def test_chapter_scope_has_no_anchor(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            seed(project)
            created = ann.create_annotation(project, 1, {
                "scope": "chapter", "instruction": "前半章太慢，合并两场问话"})
            self.assertIsNone(created["anchor"])
            self.assertEqual(ann.summary(project, 1)["open_count"], 1)


class ParseTest(unittest.TestCase):
    def test_literal_closing_tag_does_not_truncate(self):
        raw = "<replacement>他说：“到此为止。”</replacement>\n<explanation>收紧</explanation>"
        parsed = ann.parse_edit_output(raw)
        self.assertEqual(parsed["replacement"], "他说：“到此为止。”")

    def test_nonce_protects_inner_closing_tag(self):
        raw = ('<novel-edit nonce="abc"><replacement nonce="abc">正文里出现 </replacement> 也不算截断'
               '</replacement></novel-edit>')
        parsed = ann.parse_edit_output(raw)
        self.assertIn("正文里出现 </replacement> 也不算截断", parsed["replacement"])

    def test_duplicate_patch_id_is_rejected(self):
        raw = '<patch id="a">一</patch><patch id="a">二</patch>'
        with self.assertRaises(ann.AnnotationError) as caught:
            ann.parse_edit_output(raw)
        self.assertEqual(caught.exception.code, "duplicate_or_missing_patch_id")

    def test_json_fallback(self):
        parsed = ann.parse_edit_output('{"replacement": "改好了", "explanation": "更克制"}')
        self.assertEqual(parsed["replacement"], "改好了")
        self.assertEqual(parsed["format"], "json")

    def test_empty_output_is_rejected(self):
        with self.assertRaises(ann.AnnotationError):
            ann.parse_edit_output("   ")


class RunApplyUndoTest(unittest.TestCase):
    def _create(self, project, text, quote):
        return ann.create_annotation(project, 1, {
            "scope": "selection", "instruction": "改得更克制", "against": "version",
            "anchor": anchor_for(text, quote)})["id"]

    def test_run_xml_creates_preview_and_hunks(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "雨点敲在铁皮上。\n她推开门。\n"
            seed(project, text)
            aid = self._create(project, text, "她推开门。")

            def generate(annotation, context):
                return "<replacement>她攥紧门把手，指节发白。</replacement><explanation>动作表现紧张</explanation>"

            result = ann.run_annotations(project, 1, {"op_id": "run-1", "annotation_ids": [aid]},
                                         generate=generate)
            self.assertEqual(result["status"], "proposed")
            self.assertEqual(len(result["previews"]), 1)
            preview = result["previews"][0]
            self.assertIn("攥紧门把手", preview["candidate_text"])
            self.assertEqual(len(preview["hunks"]), 1)
            self.assertTrue(preview["hunks"][0]["id"].startswith(aid))
            self.assertEqual(ann.get_annotation(project, 1, aid)["status"], "proposed")

    def test_apply_then_undo_keeps_later_typing(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头。\n她推开门。\n结尾。\n"
            seed(project, text)
            aid = self._create(project, text, "她推开门。")
            result = ann.run_annotations(project, 1, {"op_id": "run-2", "annotation_ids": [aid]},
                                         generate=lambda a, c: "<replacement>她轻轻推开门。</replacement>")
            hunk_id = result["previews"][0]["hunks"][0]["id"]
            draft = draft_identity(project)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "apply-1", "hunk_ids": [hunk_id],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(applied["status"], "applied")
            self.assertIn("她轻轻推开门。", applied["draft"]["content"])
            # 作者在别处继续手打
            again = ce.save_draft(project, 1, {
                "title": "开端", "content": applied["draft"]["content"] + "作者后加的一段。\n",
                "expected_draft_id": applied["draft"]["draft_id"],
                "expected_draft_epoch": applied["draft"]["draft_epoch"],
                "expected_draft_revision": applied["draft"]["draft_revision"]})
            undone = ann.undo_apply(project, 1, {"op_id": "undo-1"})
            self.assertIn("她推开门。", undone["draft"]["content"])
            self.assertIn("作者后加的一段。", undone["draft"]["content"])
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "pending")

    def test_two_variants_share_group_and_supersede_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她说：我很害怕。\n"
            seed(project, text)
            aid = self._create(project, text, "我很害怕")

            def generate(annotation, context):
                variant = annotation.get("variant")
                return f"<replacement>{'她攥紧门把手。' if variant == 0 else '她声音发抖。'}</replacement>"

            result = ann.run_annotations(project, 1, {"op_id": "ab-1", "annotation_ids": [aid],
                                                      "variants": 2}, generate=generate)
            self.assertEqual(len(result["previews"]), 2)
            variant_a, variant_b = result["previews"]
            draft = draft_identity(project)
            ann.apply_hunks(project, 1, {
                "op_id": "apply-a", "hunk_ids": [variant_a["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            b_state = ann.get_annotation(project, 1, aid)["hunk_states"][variant_b["hunks"][0]["id"]]
            self.assertEqual(b_state["status"], "superseded")

    def test_discard_draft_reverts_applied_hunks(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seed(project, text)
            aid = self._create(project, text, "她推开门。")
            result = ann.run_annotations(project, 1, {"op_id": "run-d", "annotation_ids": [aid]},
                                         generate=lambda a, c: "<replacement>她撞开门。</replacement>")
            hunk_id = result["previews"][0]["hunks"][0]["id"]
            draft = draft_identity(project)
            ann.apply_hunks(project, 1, {
                "op_id": "apply-d", "hunk_ids": [hunk_id],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            ce.discard_draft(project, 1)
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "pending")

    def test_committed_modified_attribution(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seed(project, text)
            aid = self._create(project, text, "她推开门。")
            result = ann.run_annotations(project, 1, {"op_id": "run-c", "annotation_ids": [aid]},
                                         generate=lambda a, c: "<replacement>她撞开门。</replacement>")
            hunk_id = result["previews"][0]["hunks"][0]["id"]
            draft = draft_identity(project)
            ann.apply_hunks(project, 1, {
                "op_id": "apply-c", "hunk_ids": [hunk_id],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            # 作者把 AI 结果大改成另一句，提交后必须诚实记 committed_modified
            stats = ann.mark_committed(project, 1, text="她轻轻叩了两下门。\n")
            self.assertEqual(stats["committed_modified"], 1)
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "committed_modified")


class TriageTest(unittest.TestCase):
    def test_overlapping_conflict_and_adjacent_coupled(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n第二段。\n第三段。\n第四段。\n第五段。\n"
            seed(project, text)
            first = ann.create_annotation(project, 1, {"scope": "selection", "instruction": "删掉这句",
                                                       "against": "version",
                                                       "anchor": anchor_for(text, "第二段。")})
            second = ann.create_annotation(project, 1, {"scope": "selection", "instruction": "给这句加心理戏",
                                                        "against": "version",
                                                        "anchor": anchor_for(text, "第二段。")})
            third = ann.create_annotation(project, 1, {"scope": "selection", "instruction": "加强光影",
                                                       "against": "version",
                                                       "anchor": anchor_for(text, "第三段。")})
            rows = [ann.get_annotation(project, 1, x["id"]) for x in (first, second, third)]
            triage = ann.triage(project, 1, rows)
            self.assertTrue(any(set(group) == {first["id"], second["id"]} for group in triage["conflicts"]))
            self.assertTrue(any(first["id"] in group and third["id"] in group
                                for group in triage["coupled_batch"]))


if __name__ == "__main__":
    unittest.main()
