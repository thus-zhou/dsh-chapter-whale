"""一期作者显式定稿 `author_confirmed` 与按章合同指纹。"""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fanqie_auto_publish import publication_safety as ps
from integration import chapter_versions as cv


def make_project(folder):
    project = Path(folder) / "书"
    (project / "正文").mkdir(parents=True)
    (project / ".webnovel").mkdir(parents=True)
    return project


def receipt(project, chapter=1, **overrides):
    meta = cv.current_version(project, chapter)
    path = cv.chapter_path(project, chapter)
    text = path.read_text(encoding="utf-8-sig")
    review = {
        "success": True,
        "review_decision": "author_confirmed",
        "needs_revision": False,
        "author_confirmed": True,
        "confirmed_by": "author",
        "confirmed_version_id": meta["version_id"],
        "confirmed_content_sha256": meta["content_sha256"],
        "confirmed_title": cv.parse_chapter_name(path.name)[1],
        "confirmed_title_digest": meta["title_digest"],
        "confirmed_version_fingerprint": meta["version_fingerprint"],
        "body_sha256": ps.body_digest(text),
    }
    review.update(overrides)
    return review


class AuthorConfirmedTest(unittest.TestCase):
    def test_author_confirmed_passes_with_exact_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文内容\n", op_id="op-1", title="开端", allow_new=True)
            review = receipt(project)
            self.assertTrue(ps.review_eligible(review, review["body_sha256"], project, 1))
            self.assertFalse(ps.review_eligible(review, "0" * 64, project, 1))

    def test_changed_body_or_title_invalidates_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文内容\n", op_id="op-1", title="开端", allow_new=True)
            review = receipt(project)
            path = cv.chapter_path(project, 1)
            path.write_text("正文内容被手改\n", encoding="utf-8", newline="\n")
            self.assertFalse(ps.review_eligible(review, review["body_sha256"], project, 1))

        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文内容\n", op_id="op-1", title="开端", allow_new=True)
            review = receipt(project)
            old = cv.chapter_path(project, 1)
            old.rename(old.with_name("第1章-新标题.md"))
            self.assertFalse(ps.review_eligible(review, review["body_sha256"], project, 1))

    def test_missing_or_legacy_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文内容\n", op_id="op-1", title="开端", allow_new=True)
            review = receipt(project)
            self.assertFalse(ps.review_eligible({**review, "author_confirmed": False},
                                                review["body_sha256"], project, 1))
            self.assertFalse(ps.review_eligible({**review, "confirmed_version_id": "a" * 64},
                                                review["body_sha256"], project, 1))
            self.assertFalse(ps.review_eligible(review, review["body_sha256"], None, None))

    def test_human_approved_branch_stays_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, "正文内容\n", op_id="op-1", title="开端", allow_new=True)
            body = ps.body_digest(cv.chapter_path(project, 1).read_text(encoding="utf-8"))
            approved = {"review_decision": "human_approved", "human_review_approved": True,
                        "body_sha256": body}
            self.assertTrue(ps.review_eligible(approved, body, project, 1))
            # 分支由 review_decision 决定；author_confirmed 回执不能冒充 human_approved
            self.assertFalse(ps.review_eligible(
                {"review_decision": "author_confirmed", "human_review_approved": True,
                 "body_sha256": body}, body, project, 1))

    def test_future_rule_does_not_revoke_earlier_chapter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            (project / ".webnovel" / "creative_brief.json").write_text(
                json.dumps({"brief": {"genre": "悬疑"}, "learning": {}}, ensure_ascii=False),
                encoding="utf-8", newline="\n")
            memory = {
                "schema": 1, "revision": 1, "chapters": {}, "history": [],
                "items": [{
                    "id": "a" * 32, "category": "canon", "title": "化名规则",
                    "content": "从第6章起女主对外用化名林溪", "status": "active",
                    "pinned": False, "updated_revision": 1,
                    "source": {"kind": "manual", "chapter": 0},
                    "effective_from_chapter": 6,
                }],
            }
            (project / ".webnovel" / "shared_memory.json").write_text(
                json.dumps(memory, ensure_ascii=False), encoding="utf-8", newline="\n")
            global_hash = ps.creative_contract_hash(project)
            first = ps.creative_contract_hash_for_chapter(project, 1)
            fifth = ps.creative_contract_hash_for_chapter(project, 5)
            sixth = ps.creative_contract_hash_for_chapter(project, 6)
            self.assertNotEqual(global_hash, first)
            self.assertEqual(first, fifth)
            self.assertEqual(sixth, global_hash)
            self.assertNotEqual(first, sixth)

    def test_author_verified_exemption_is_scoped_to_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            (project / ".webnovel" / "creative_brief.json").write_text(
                json.dumps({"brief": {"genre": "悬疑"}, "learning": {}}, ensure_ascii=False),
                encoding="utf-8", newline="\n")
            memory = {
                "schema": 1, "revision": 1, "chapters": {}, "history": [],
                "items": [{
                    "id": "b" * 32, "category": "canon", "title": "规则",
                    "content": "全书不得出现血腥描写", "status": "active",
                    "pinned": False, "updated_revision": 1,
                    "source": {"kind": "manual", "chapter": 0},
                }],
            }
            (project / ".webnovel" / "shared_memory.json").write_text(
                json.dumps(memory, ensure_ascii=False), encoding="utf-8", newline="\n")
            cv.write_chapter(project, 8, "第八章正文\n", op_id="op-8", title="第八章", allow_new=True)
            meta = cv.current_version(project, 8)
            bound = ps.creative_contract_hash_for_chapter(project, 8)
            self.assertIn("__author_memory__", json.loads(json.dumps(
                ps._contract_values(project, 8))))
            from integration import workbench_db
            workbench_db.initialize(project)
            uid = workbench_db.chapter_uid(project, 8)
            with workbench_db.write_tx(project) as db:
                db.execute(
                    "INSERT INTO directive_exemptions(chapter_id, chapter_uid, version_id, content_sha256, "
                    "rule_id, rule_content_sha256, scan_method, confirmed_by, verified_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (8, uid, meta["version_id"], meta["content_sha256"],
                     "b" * 32, hashlib.sha256("全书不得出现血腥描写".encode()).hexdigest(),
                     "world_state_plus_llm", "author", workbench_db.now_iso()),
                )
            exempt = ps.creative_contract_hash_for_chapter(project, 8)
            self.assertNotEqual(bound, exempt)
            # 正文再改一个字节，旧豁免立即失效
            cv.write_chapter(project, 8, "第八章正文改\n", op_id="op-8b", title="第八章")
            changed = ps.creative_contract_hash_for_chapter(project, 8)
            self.assertNotEqual(exempt, changed)


if __name__ == "__main__":
    unittest.main()
