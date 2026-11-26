"""四级锚点重定位、中间基线 B' 与反向补丁撤销。"""
import random
import tempfile
import unittest

from integration import text_merge as tm


class AnchorTest(unittest.TestCase):
    def test_unicode_codepoint_lf(self):
        text = "甲😀乙\r\n丙"
        self.assertEqual(tm.normalize_lf(text), "甲😀乙\n丙")
        self.assertEqual(tm.codepoint_length("甲😀乙"), 3)
        self.assertEqual(tm.slice_codepoints("甲😀乙", 1, 2), "😀")
        self.assertEqual(tm.clamp_range("甲😀乙", -5, 99), (0, 3))

    def test_exact_when_document_unchanged(self):
        text = "林溪推开门。\n老周抬头。\n"
        anchor = {"quote": "老周抬头。", "char_start": 7, "char_end": 12,
                  "base_snapshot_id": tm.sha256(text)}
        result = tm.relocate_anchor(text, text, anchor)
        self.assertEqual(result["status"], "exact")
        self.assertEqual((result["start"], result["end"]), (7, 12))

    def test_deleting_first_duplicate_never_hits_third(self):
        base = "甲：我知道。\n乙：我知道。\n丙：我知道。\n"
        start = base.index("乙：我知道。") + len("乙：")
        end = start + len("我知道。")
        anchor = {"quote": "我知道。", "char_start": start, "char_end": end,
                  "prefix_ctx": "乙：", "suffix_ctx": "\n丙",
                  "base_snapshot_id": tm.sha256(base)}
        current = base.replace("甲：我知道。\n", "")
        result = tm.relocate_anchor(base, current, anchor)
        self.assertEqual(result["status"], "relocated")
        self.assertEqual(current[result["start"]:result["end"]], "我知道。")
        self.assertIn("乙", current[max(0, result["start"] - 3):result["start"]])

    def test_inside_rewrite_is_overlap_conflict(self):
        base = "她说：我很害怕。\n他点头。\n"
        start, end = base.index("我很害怕"), base.index("我很害怕") + 4
        anchor = {"quote": "我很害怕", "char_start": start, "char_end": end,
                  "prefix_ctx": "她说：", "suffix_ctx": "。\n他点头。",
                  "base_snapshot_id": tm.sha256(base)}
        current = base.replace("我很害怕", "她怕得发抖")
        result = tm.relocate_anchor(base, current, anchor)
        self.assertIn(result["status"], {"overlap_conflict", "relocated_needed"})
        if result["status"] == "overlap_conflict":
            self.assertEqual(result["reason"], "selection_changed")

    def test_ambiguous_duplicate_requires_relocation(self):
        base = "我知道。\n我知道。\n"
        anchor = {"quote": "我知道。", "char_start": 4, "char_end": 8,
                  "prefix_ctx": "", "suffix_ctx": "", "base_snapshot_id": tm.sha256(base)}
        current = base.replace("我知道。\n", "不知道。\n", 1)
        result = tm.relocate_anchor(base, current, anchor)
        self.assertEqual(result["status"], "relocated_needed")


class MergeTest(unittest.TestCase):
    def test_non_overlapping_author_and_ai(self):
        base = "开头。\n中间。\n结尾。\n"
        current = "作者改的开头。\n中间。\n结尾。\n"
        candidate = "开头。\n中间。\nAI 改的结尾。\n"
        result = tm.merge_preview(base, current, candidate)
        self.assertEqual(result["text"], "作者改的开头。\n中间。\nAI 改的结尾。\n")
        self.assertTrue(result["clean"])

    def test_same_range_keeps_both_and_conflicts(self):
        base = "她说：我很害怕。\n"
        current = "她说：她怕得发抖。\n"
        candidate = "她说：她攥紧了门把手。\n"
        result = tm.merge_preview(base, current, candidate)
        self.assertFalse(result["clean"])
        self.assertEqual(result["text"], current, "冲突时不得静默覆盖作者手改")
        self.assertTrue(result["conflicts"])

    def test_adjacent_hunks_use_intermediate_baseline(self):
        base = "第一段。\n第二段。\n第三段。\n"
        h1 = {"id": "hk_01", "char_start": 0, "char_end": 4,
              "before_text": "第一段。", "after_text": "第一段改。"}
        h2 = {"id": "hk_02", "char_start": 5, "char_end": 9,
              "before_text": "第二段。", "after_text": "第二段改。"}
        applied = tm.apply_hunks(base, base, [h1])
        self.assertEqual(applied["text"], "第一段改。\n第二段。\n第三段。\n")
        second = tm.apply_hunks(base, applied["text"], [h2],
                                already_applied=[h1])
        self.assertTrue(second["clean"], second["conflicts"])
        self.assertEqual(second["text"], "第一段改。\n第二段改。\n第三段。\n")

    def test_custom_text_is_used_in_intermediate_base(self):
        base = "第一段。\n第二段。\n"
        h1 = {"id": "hk_01", "char_start": 0, "char_end": 4,
              "before_text": "第一段。", "after_text": "AI 写的第一段。",
              "custom_text": "作者微调的第一段。"}
        h2 = {"id": "hk_02", "char_start": 5, "char_end": 9,
              "before_text": "第二段。", "after_text": "第二段改。"}
        first = tm.apply_hunks(base, base, [{**h1, "custom_text": "作者微调的第一段。"}])
        second = tm.apply_hunks(base, first["text"], [h2],
                                already_applied=[{**h1, "custom_text": "作者微调的第一段。"}])
        self.assertEqual(second["text"], "作者微调的第一段。\n第二段改。\n")
        self.assertTrue(second["clean"])

    def test_author_typing_during_apply_keeps_both(self):
        base = "开头。\n中间。\n结尾。\n"
        current = "开头。\n中间。\n结尾。\n作者新增的一行。\n"
        candidate = "开头。\n中间改。\n结尾。\n"
        result = tm.merge_preview(base, current, candidate)
        self.assertIn("作者新增的一行。", result["text"])
        self.assertIn("中间改。", result["text"])

    def test_reverse_patch_keeps_later_typing(self):
        base = "开头。\n结尾。\n"
        applied = tm.apply_hunks(base, base, [
            {"id": "hk_01", "char_start": 0, "char_end": 3,
             "before_text": "开头。", "after_text": "开头改。"}])
        text = applied["text"] + "作者后来写的一段。\n"
        row = {"applied_text": "开头改。", "before_quote": "开头。",
               "char_start": 0, "char_end": 4}
        reverted = tm.reverse_patch(text, row)
        self.assertEqual(reverted["status"], "reversed")
        self.assertTrue(reverted["text"].startswith("开头。\n结尾。"))
        self.assertIn("作者后来写的一段。", reverted["text"])

    def test_reverse_patch_refuses_ambiguous_duplicate(self):
        text = "重复。\n重复。\n"
        row = {"applied_text": "重复。", "before_quote": "原文。"}
        result = tm.reverse_patch(text, row)
        self.assertEqual(result["status"], "relocated_needed")
        self.assertEqual(result["text"], text)

    def test_random_non_overlapping_invariant(self):
        rng = random.Random(20261126)
        for _ in range(200):
            prefix = "甲乙丙丁" * rng.randint(1, 20)
            suffix = "戊己庚辛" * rng.randint(1, 20)
            base = prefix + "【目标】" + suffix
            # 作者只改开头，AI 只改目标
            current = "作者开头" + base[len("作者开头"):]
            candidate = base.replace("【目标】", "【AI改】")
            result = tm.merge_preview(base, current, candidate)
            self.assertIn("【AI改】", result["text"])
            self.assertTrue(result["text"].startswith("作者开头"))
            self.assertTrue(result["text"].endswith(suffix))
            # 未选中区域在无冲突时必须一字不变
            if result["clean"]:
                self.assertIn(current[:len(current) - len(suffix) - len("【目标】")], result["text"])


if __name__ == "__main__":
    unittest.main()
