"""三层批注：锚点、XML 防截断、分诊、A/B 与逐块采纳/撤销。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class CandidateCoordinatesTest(unittest.TestCase):
    def test_candidate_uses_base_snapshot_coordinates_after_prefix_insert(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头一句。\n她推开门。\n结尾一句。\n"
            seed(project, text)
            aid = ann.create_annotation(project, 1, {
                "scope": "selection", "instruction": "改动作", "against": "version",
                "anchor": anchor_for(text, "她推开门。")})["id"]
            draft = draft_identity(project)
            ce.save_draft(project, 1, {"title": "开端",
                                       "content": "前缀插入。\n" + text,
                                       "expected_draft_id": draft["draft_id"],
                                       "expected_draft_epoch": draft["draft_epoch"],
                                       "expected_draft_revision": draft["draft_revision"]})
            result = ann.run_annotations(project, 1, {"op_id": "coords", "annotation_ids": [aid]},
                                         generate=lambda a, c: "<replacement>她攥紧门把手。</replacement>")
            preview = result["previews"][0]
            hunk = preview["hunks"][0]
            self.assertEqual(hunk["before_text"], "她推开门。")
            self.assertEqual(preview["candidate_text"],
                             "开头一句。\n她攥紧门把手。\n结尾一句。\n")
            # 应用这份候选后，新句在目标位置，而不是被追加到文末。
            self.assertNotIn("结尾一句。\n她攥紧门把手。", preview["candidate_text"])


class OverlapAndLifecycleTest(unittest.TestCase):
    def _create(self, project, text, quote="她推开门。"):
        return ann.create_annotation(project, 1, {
            "scope": "selection", "instruction": "改", "against": "version",
            "anchor": anchor_for(text, quote)})["id"]

    def test_two_variant_hunks_in_one_request_do_not_both_apply(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她说：我很害怕。\n"
            seed(project, text)
            aid = self._create(project, text, "我很害怕")
            def generate(annotation, context):
                return ("<replacement>她攥紧门把手。</replacement>" if annotation.get("variant") == 0
                        else "<replacement>她声音发抖。</replacement>")
            result = ann.run_annotations(project, 1, {"op_id": "overlap", "annotation_ids": [aid],
                                                      "variants": 2}, generate=generate)
            ids = [preview["hunks"][0]["id"] for preview in result["previews"]]
            draft = draft_identity(project)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "overlap-apply", "hunk_ids": ids,
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertFalse(applied["clean"])
            self.assertTrue(any(item["reason"] == "hunk_overlap" for item in applied["conflicts"]))
            self.assertEqual(len(applied["applied"]), 1)
            self.assertIn("她说：", applied["draft"]["content"])
            self.assertIn("。", applied["draft"]["content"])

    def test_commit_via_save_version_marks_hunk_committed_and_clears_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seed(project, text)
            aid = self._create(project, text)
            preview = ann.run_annotations(project, 1, {"op_id": "commit-run", "annotation_ids": [aid]},
                                          generate=lambda a, c: "<replacement>她撞开门。</replacement>")["previews"][0]
            draft = draft_identity(project)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "commit-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            current = cv.snapshot(project, 1, source="test", note="commit test") or {}
            ce.save_version(project, 1, {
                "op_id": "commit-save", "title": "开端", "content": applied["draft"]["content"],
                "expected_version_id": current.get("version_id"),
                "expected_content_sha256": cv.file_sha256(cv.chapter_path(project, 1)),
                "submitted_draft_id": applied["draft"]["draft_id"],
                "submitted_draft_epoch": applied["draft"]["draft_epoch"],
                "submitted_draft_revision": applied["draft"]["draft_revision"]})
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "committed")
            with wb.connect(project) as db:
                count = db.execute("SELECT COUNT(*) FROM patch_ledger WHERE chapter_id=1").fetchone()[0]
            self.assertEqual(count, 0)

    def test_apply_without_draft_uses_current_epoch_after_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头。\n她推开门。\n结尾。\n"
            seed(project, text)
            aid = self._create(project, text)
            preview = ann.run_annotations(project, 1, {"op_id": "epoch-run", "annotation_ids": [aid]},
                                          generate=lambda a, c: "<replacement>她撞开门。</replacement>")["previews"][0]
            draft = draft_identity(project)
            ann.apply_hunks(project, 1, {"op_id": "epoch-apply-1", "hunk_ids": [preview["hunks"][0]["id"]],
                                         "expected_draft_id": draft["draft_id"],
                                         "expected_draft_epoch": draft["draft_epoch"],
                                         "expected_draft_revision": draft["draft_revision"]})
            ce.discard_draft(project, 1)
            epoch = wb.draft_epoch(project, 1)
            self.assertGreater(epoch, 0)
            second = ann.apply_hunks(project, 1, {"op_id": "epoch-apply-2",
                                                  "hunk_ids": [preview["hunks"][0]["id"]],
                                                  "expected_draft_epoch": epoch})
            self.assertEqual(second["status"], "applied")
            self.assertIn("她撞开门。", second["draft"]["content"])


class AuditBRegressionTest(unittest.TestCase):
    def _ident(self, project):
        return wb.get_draft(project, 1) or {"draft_id": None, "draft_epoch": 0, "draft_revision": 0}

    def _create(self, project, text, quote="她推开门。", occurrence=0):
        return ann.create_annotation(project, 1, {
            "scope": "selection", "instruction": "改", "against": "version",
            "anchor": anchor_for(text, quote, occurrence)})["id"]

    def test_b01_ledger_coordinate_space_keeps_second_apply_clean(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "A。\nB。\nC。\n"
            seed(project, text)
            first = self._create(project, text, "C。")
            preview1 = ann.run_annotations(
                project, 1, {"op_id": "b01-run1", "annotation_ids": [first]},
                generate=lambda a, c: "<replacement>C1。</replacement>")["previews"][0]
            draft = self._ident(project)
            ann.apply_hunks(project, 1, {
                "op_id": "b01-apply1", "hunk_ids": [preview1["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            draft = wb.get_draft(project, 1)
            ce.save_draft(project, 1, {
                "title": "开端", "content": "X。\n" + draft["content"],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            current = wb.get_draft(project, 1)["content"]
            second = ann.create_annotation(project, 1, {
                "scope": "selection", "instruction": "改B", "against": "draft",
                "anchor": anchor_for(current, "B。")})["id"]
            preview2 = ann.run_annotations(
                project, 1, {"op_id": "b01-run2", "annotation_ids": [second]},
                generate=lambda a, c: "<replacement>B1。</replacement>")["previews"][0]
            draft = wb.get_draft(project, 1)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "b01-apply2", "hunk_ids": [preview2["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertTrue(applied["clean"], applied["conflicts"])
            self.assertEqual(applied["draft"]["content"], "X。\nA。\nB1。\nC1。\n")

    def test_b06_multi_patch_uses_declared_paragraph_ranges(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段甲。\n第二段乙。\n第三段丙。\n"
            seed(project, text)
            aid = ann.create_annotation(project, 1, {"scope": "chapter", "instruction": "按段落改"})["id"]
            raw = ('<patch id="p1" start_para="0" end_para="0">第一段改。</patch>'
                   '<patch id="p2" start_para="2" end_para="2">第三段改。</patch>')
            result = ann.run_annotations(project, 1, {"op_id": "b06", "annotation_ids": [aid]},
                                         generate=lambda a, c: raw)
            self.assertEqual(result["status"], "proposed", result["errors"])
            preview = result["previews"][0]
            self.assertEqual(len(preview["hunks"]), 2)
            self.assertEqual(preview["hunks"][0]["before_text"], "第一段甲。")
            self.assertEqual(preview["hunks"][1]["before_text"], "第三段丙。")
            self.assertEqual(preview["candidate_text"], "第一段改。\n第二段乙。\n第三段改。\n")

    def test_b07_custom_text_persisted_and_deletion_is_committed(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头一句。\n她推开门。\n结尾一句。\n"
            seed(project, text)
            aid = self._create(project, text)
            preview = ann.run_annotations(
                project, 1, {"op_id": "b07-run", "annotation_ids": [aid]},
                generate=lambda a, c: "<replacement>她轻轻推开门。</replacement>")["previews"][0]
            hunk_id = preview["hunks"][0]["id"]
            draft = self._ident(project)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "b07-apply", "hunk_ids": [hunk_id],
                "custom_texts": {hunk_id: "她悄悄推开门。"},
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["custom_text"],
                             "她悄悄推开门。")
            stats = ann.mark_committed(project, 1, text=applied["draft"]["content"])
            self.assertEqual(stats["committed"], 1)

            # 纯删除型：原文消失即 committed，而不是永远 committed_modified
            text2 = "她推开门。\n"
            project2 = make_project(tempfile.mkdtemp())
            seed(project2, text2)
            delete_id = self._create(project2, text2)
            delete_preview = ann.run_annotations(
                project2, 1, {"op_id": "b07-del-run", "annotation_ids": [delete_id]},
                generate=lambda a, c: {"format": "xml_replacement", "replacement": ""})["previews"][0]
            draft2 = self._ident(project2)
            deleted = ann.apply_hunks(project2, 1, {
                "op_id": "b07-del-apply", "hunk_ids": [delete_preview["hunks"][0]["id"]],
                "expected_draft_id": draft2["draft_id"], "expected_draft_epoch": draft2["draft_epoch"],
                "expected_draft_revision": draft2["draft_revision"]})
            stats2 = ann.mark_committed(project2, 1, text=deleted["draft"]["content"])
            self.assertEqual(stats2["committed"], 1)
            self.assertEqual(ann.get_annotation(project2, 1, delete_id)["hunks"][0]["status"],
                             "committed")

    def test_b08_author_rewrote_selection_skips_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她说：我很害怕。\n他点头。\n"
            seed(project, text)
            aid = ann.create_annotation(project, 1, {
                "scope": "selection", "instruction": "改", "against": "version",
                "anchor": anchor_for(text, "我很害怕")})["id"]
            draft = self._ident(project)
            ce.save_draft(project, 1, {
                "title": "开端", "content": text.replace("我很害怕", "她怕得发抖"),
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            calls = []
            result = ann.run_annotations(
                project, 1, {"op_id": "b08", "annotation_ids": [aid]},
                generate=lambda a, c: calls.append(1) or "<replacement>x</replacement>")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(calls, [])
            self.assertEqual(ann.get_annotation(project, 1, aid)["status"],
                             "author_rewrote_selection")

    def test_b10_undo_deletion_after_author_prefix_uses_context(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "甲乙丙丁戊NEW。\n"
            seed(project, text)
            aid = ann.create_annotation(project, 1, {
                "scope": "selection", "instruction": "删掉开头", "against": "version",
                "anchor": {"char_start": 0, "char_end": 5, "quote": "甲乙丙丁戊"}})["id"]
            preview = ann.run_annotations(
                project, 1, {"op_id": "b10-run", "annotation_ids": [aid]},
                generate=lambda a, c: {"format": "xml_replacement", "replacement": ""})["previews"][0]
            draft = self._ident(project)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "b10-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(applied["draft"]["content"], "NEW。\n")
            draft = wb.get_draft(project, 1)
            ce.save_draft(project, 1, {
                "title": "开端", "content": "前言。" + draft["content"],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            undone = ann.undo_apply(project, 1, {"op_id": "b10-undo"})
            self.assertEqual(undone["draft"]["content"], "前言。甲乙丙丁戊NEW。\n")

    def test_b12_rejected_annotation_cannot_apply(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "甲改。\n乙句。\n"
            seed(project, text)
            aid = self._create(project, text, "甲改。")
            preview = ann.run_annotations(
                project, 1, {"op_id": "b12-run", "annotation_ids": [aid]},
                generate=lambda a, c: "<replacement>甲再改。</replacement>")["previews"][0]
            ann.update_annotation(project, 1, aid, {"status": "rejected"})
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "rejected")
            draft = self._ident(project)
            with self.assertRaises(ann.AnnotationError) as caught:
                ann.apply_hunks(project, 1, {
                    "op_id": "b12-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                    "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                    "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(caught.exception.code, "no_pending_hunks")

    def test_b13_missing_snapshot_does_not_break_annotation_list(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seed(project, text)
            created = ann.create_annotation(project, 1, {
                "scope": "selection", "instruction": "改", "against": "version",
                "anchor": anchor_for(text, "她推开门。")})
            digest = created["anchor"]["base_snapshot_id"]
            (project / ".webnovel" / "snapshots" / f"{digest}.txt").unlink()
            listing = ann.list_annotations(project, 1)
            self.assertEqual(len(listing["annotations"]), 1)
            item = listing["annotations"][0]
            self.assertEqual(item["relocated"]["status"], "snapshot_missing")
            self.assertEqual(item["status"], "relocated_needed")

    def test_b19_same_op_id_does_not_bill_or_apply_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她推开门。\n"
            seed(project, text)
            aid = self._create(project, text)
            calls = []

            def generate(annotation, context):
                calls.append(context.get("op_id"))
                return "<replacement>她撞开门。</replacement>"

            first = ann.run_annotations(project, 1, {"op_id": "b19-run", "annotation_ids": [aid]},
                                        generate=generate)
            second = ann.run_annotations(project, 1, {"op_id": "b19-run", "annotation_ids": [aid]},
                                         generate=generate)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["previews"][0]["preview_id"], second["previews"][0]["preview_id"])
            hunk_id = first["previews"][0]["hunks"][0]["id"]
            draft = self._ident(project)
            body = {"op_id": "b19-apply", "hunk_ids": [hunk_id],
                    "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                    "expected_draft_revision": draft["draft_revision"]}
            ann.apply_hunks(project, 1, body)
            ann.apply_hunks(project, 1, body)
            with wb.connect(project) as db:
                ledger = db.execute("SELECT COUNT(*) FROM patch_ledger WHERE chapter_id=1").fetchone()[0]
            self.assertEqual(ledger, 1)

    def test_b21_independent_excludes_coupled_members(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "第一段。\n第二段。\n第三段。\n"
            seed(project, text)
            ids = []
            for quote, instruction in (("第一段。", "改一"), ("第二段。", "改二")):
                ids.append(ann.create_annotation(project, 1, {
                    "scope": "selection", "instruction": instruction, "against": "version",
                    "anchor": anchor_for(text, quote)})["id"])
            rows = [ann.get_annotation(project, 1, value) for value in ids]
            triage = ann.triage(project, 1, rows)
            coupled = {value for group in triage["coupled_batch"] for value in group}
            self.assertTrue(coupled)
            self.assertFalse(coupled & set(triage["independent"]))

    def test_b22_conflict_envelope_is_not_labelled_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "甲句。\n乙句。\n丙句。\n"
            seed(project, text)
            aid = self._create(project, text, "丙句。")
            preview = ann.run_annotations(
                project, 1, {"op_id": "b22-run", "annotation_ids": [aid]},
                generate=lambda a, c: "<replacement>丙改。</replacement>")["previews"][0]
            draft = self._ident(project)
            ce.save_draft(project, 1, {
                "title": "开端", "content": text.replace("丙句。", "丙句改了。"),
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            draft = wb.get_draft(project, 1)
            result = ann.apply_hunks(project, 1, {
                "op_id": "b22-apply", "hunk_ids": [preview["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(result["status"], "conflict")
            self.assertEqual(result["applied"], [])
            self.assertTrue(result["conflicts"])
            self.assertEqual(result["draft"]["content"], "甲句。\n乙句。\n丙句改了。\n")

    def test_b23_reject_hunks_and_b24_superseded_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "她说：我很害怕。\n"
            seed(project, text)
            aid = self._create(project, text, "我很害怕")
            result = ann.run_annotations(
                project, 1, {"op_id": "b24-run", "annotation_ids": [aid], "variants": 2},
                generate=lambda a, c: f"<replacement>{'她攥紧门把手。' if a['variant'] == 0 else '她发抖。'}</replacement>")
            variant_a, variant_b = result["previews"]
            draft = self._ident(project)
            ann.apply_hunks(project, 1, {
                "op_id": "b24-apply", "hunk_ids": [variant_a["hunks"][0]["id"]],
                "expected_draft_id": draft["draft_id"], "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            previews = {row["preview_id"]: row["status"]
                        for row in ann.list_previews(project, 1)["previews"]}
            self.assertEqual(previews[variant_b["preview_id"]], "superseded")

            # 逐 hunk 拒绝：另一条批注仍 pending 时可单独拒绝
            other = self._create(project, text, "她说", occurrence=0)
            pending = ann.run_annotations(
                project, 1, {"op_id": "b23-run", "annotation_ids": [other]},
                generate=lambda a, c: "<replacement>她低声说</replacement>")["previews"][0]
            rejected = ann.reject_hunks(project, 1, {
                "op_id": "b23-reject", "hunk_ids": [pending["hunks"][0]["id"]]})
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(ann.get_annotation(project, 1, other)["hunks"][0]["status"], "rejected")


class ApplyAtomicityTest(unittest.TestCase):
    """B-01R-4 / B3-04: draft and hunk state must not diverge."""

    def _prepare(self, project, text, quote, replacement):
        aid = ann.create_annotation(project, 1, {
            "scope": "selection", "instruction": "改得更克制", "against": "version",
            "anchor": {"char_start": text.index(quote), "char_end": text.index(quote) + len(quote),
                       "quote": quote}})["id"]
        result = ann.run_annotations(
            project, 1, {"op_id": f"atomic-run-{aid}", "annotation_ids": [aid]},
            generate=lambda a, c: f"<replacement>{replacement}</replacement>")
        return aid, result["previews"][0]["hunks"][0]["id"]

    def test_hunk_state_failure_rolls_draft_back_and_retry_applies_once(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头一句。\n她推开门。\n结尾一句。\n"
            seed(project, text)
            aid, hunk_id = self._prepare(project, text, "她推开门。", "她推开门。又停了停。")
            identity = draft_identity(project)
            with patch.object(ann, "_recompute_annotation_status",
                              side_effect=RuntimeError("simulated crash in hunk tx")):
                with self.assertRaises(RuntimeError):
                    ann.apply_hunks(project, 1, {
                        "op_id": "atomic-crash", "hunk_ids": [hunk_id],
                        "expected_draft_id": identity["draft_id"],
                        "expected_draft_epoch": identity["draft_epoch"],
                        "expected_draft_revision": identity["draft_revision"]})
            # The draft write is part of the same transaction: no orphan text.
            self.assertIsNone(wb.get_draft(project, 1))
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"], "pending")
            with wb.connect(project) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM patch_ledger").fetchone()[0], 0)

            fresh = draft_identity(project)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "atomic-retry", "hunk_ids": [hunk_id],
                "expected_draft_id": fresh["draft_id"],
                "expected_draft_epoch": fresh["draft_epoch"],
                "expected_draft_revision": fresh["draft_revision"]})
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(applied["draft"]["content"].count("又停了停"), 1)
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"],
                             "applied_to_draft")
            undone = ann.undo_apply(project, 1, {})
            self.assertEqual(undone["status"], "reverted")
            self.assertNotIn("又停了停", undone["draft"]["content"])

    def test_pending_hunk_whose_text_already_landed_is_adopted_not_duplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头一句。\n她推开门。\n结尾一句。\n"
            seed(project, text)
            aid, hunk_id = self._prepare(project, text, "她推开门。", "她推开门。又停了停。")
            # Simulate the old crash window: the draft already contains the
            # candidate but the hunk/ledger transaction never ran.
            draft = wb.save_draft(project, 1, title="开端",
                                  content=text.replace("她推开门。", "她推开门。又停了停。"),
                                  expected_draft_epoch=0, expected_draft_revision=0)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "atomic-orphan", "hunk_ids": [hunk_id],
                "expected_draft_id": draft["draft_id"],
                "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(applied["draft"]["content"].count("又停了停"), 1)
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"],
                             "applied_to_draft")
            with wb.connect(project) as db:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM patch_ledger WHERE hunk_id=?", (hunk_id,)
                ).fetchone()[0], 1)
            undone = ann.undo_apply(project, 1, {})
            self.assertEqual(undone["status"], "reverted")
            self.assertNotIn("又停了停", undone["draft"]["content"])


    def test_pending_replacement_already_landed_is_not_left_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = "开头一句。\n她推开门。\n结尾一句。\n"
            seed(project, text)
            aid, hunk_id = self._prepare(project, text, "她推开门。", "她撞开门。")
            draft = wb.save_draft(project, 1, title="开端",
                                  content=text.replace("她推开门。", "她撞开门。"),
                                  expected_draft_epoch=0, expected_draft_revision=0)
            applied = ann.apply_hunks(project, 1, {
                "op_id": "atomic-orphan-replace", "hunk_ids": [hunk_id],
                "expected_draft_id": draft["draft_id"],
                "expected_draft_epoch": draft["draft_epoch"],
                "expected_draft_revision": draft["draft_revision"]})
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(applied["draft"]["content"].count("她撞开门。"), 1)
            self.assertEqual(ann.get_annotation(project, 1, aid)["hunks"][0]["status"],
                             "applied_to_draft")
            undone = ann.undo_apply(project, 1, {})
            self.assertEqual(undone["status"], "reverted")
            self.assertIn("她推开门。", undone["draft"]["content"])


if __name__ == "__main__":
    unittest.main()
