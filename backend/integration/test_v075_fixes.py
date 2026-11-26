import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fanqie_auto_publish import publication_safety
from integration import costs, free_pool, ofm_runtime, studio, writer_runner


def _load_skill_executor_mod():
    target = BACKEND / "webnovel-writer" / "backend" / "services" / "skill_executor.py"
    if not target.exists():
        return None
    spec = importlib.util.spec_from_file_location("test_skill_executor", target)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


class V075FixesIntegrationTests(unittest.TestCase):
    def test_max_auto_reviews_constant_and_outline_matching(self):
        self.assertEqual(writer_runner.MAX_AUTO_REVIEWS, 2)
        skill_mod = _load_skill_executor_mod()
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "book"
            outline_dir = proj / "大纲"
            outline_dir.mkdir(parents=True)
            for text, expected in [
                ("## 第01章 破局\n内容A", "破局"),
                ("### 第一章：初入江湖\n内容B", "初入江湖"),
                ("## 第 1 章   测试章节\n内容C", "测试章节"),
            ]:
                (outline_dir / "卷一.md").write_text(text, encoding="utf-8")
                sec = writer_runner._find_outline(proj, 1)
                self.assertIn("内容", sec)
                self.assertEqual(writer_runner._outline_title(sec, 1), expected)
                if skill_mod is not None:
                    self.assertEqual(skill_mod.SkillExecutor._match_outline_chapter_number(text.splitlines()[0]), 1)

    def test_human_review_handoff_blocks_publish_until_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            chapters_dir = project / "正文"
            chapters_dir.mkdir(parents=True)
            (project / ".webnovel").mkdir(parents=True)
            body = "# 第1章 风起\n\n测试正文内容，用于验证人工复核门禁与发布状态转换。"
            chapter_file = chapters_dir / "第1章-风起.md"
            chapter_file.write_text(body, encoding="utf-8")
            digest = writer_runner.body_digest(body)

            handoff_receipt = {
                "chapter": 1,
                "body_sha256": digest,
                "success": True,
                "review_decision": "needs_human_review",
                "human_review_required": True,
                "auto_review_count": 2,
                "review": {"success": True, "review_decision": "needs_human_review", "human_review_required": True,
                           "auto_review_count": 2, "body_sha256": digest},
            }
            self.assertFalse(publication_safety.review_eligible(handoff_receipt["review"], digest))

            receipts_path = project / ".webnovel" / "writer_receipts.json"
            receipts_path.write_text(
                json.dumps({"1": {"review": handoff_receipt["review"], "destination": str(chapter_file)}}, ensure_ascii=False),
                encoding="utf-8",
            )

            approved = writer_runner.approve_chapter_review(project, 1, note="人工核验通过")
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(approved["review_decision"], "human_approved")
            receipt = approved["receipt"]
            self.assertTrue(receipt["review"]["human_review_approved"])
            self.assertTrue(publication_safety.review_eligible(receipt["review"], digest))
            self.assertFalse(publication_safety.review_eligible(receipt["review"], "different-digest"))

    def test_pending_batches_and_abandon_batch_work(self):
        batch_hex = "a" * 32
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            state_dir = project / ".webnovel"
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text(
                json.dumps({"progress": {"current_chapter": 0, "total_words": 0}}, ensure_ascii=False),
                encoding="utf-8",
            )
            batches_dir = state_dir / "batches"
            batches_dir.mkdir(parents=True)
            stale_file = batches_dir / f"{batch_hex}.json"
            stale_file.write_text(
                json.dumps(
                    {
                        "id": batch_hex,
                        "status": "running",
                        "targets": [1],
                        "completed": [],
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            pending = studio.pending_batches(project)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["id"], batch_hex)

            abandoned = studio.abandon_batch(project, batch_hex)
            self.assertEqual(abandoned["status"], "abandoned")
            self.assertIn(batch_hex, abandoned["abandoned"])
            saved = json.loads(stale_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "abandoned")
            self.assertEqual(studio.pending_batches(project), [])

    def test_free_pool_non_login_channel_and_loopback_port_sync(self):
        self.assertFalse(free_pool._requires_account_login("opencode/minimax-m2.5-free"))
        self.assertFalse(free_pool._requires_account_login("kilo/qwen"))
        self.assertFalse(free_pool._requires_account_login("combo:auto"))
        self.assertTrue(free_pool._requires_account_login("iflow/glm-5"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "book"
            project.mkdir()
            config_doc = {
                "providers": {
                    "ofm-standalone": {
                        "protocol": "ofm_standalone",
                        "base_url": "http://127.0.0.1:24999/v1",
                        "api_key": "ofm-key",
                        "enabled": True,
                    },
                    "free-pool": {
                        "protocol": "free_pool",
                        "base_url": "http://127.0.0.1:24999/v1",
                        "enabled": True,
                        "allowed_projects": [str(project)],
                        "pool_members": [
                            {"model_id": "opencode/qwen-free", "roles": ["A", "B", "C", "D", "E"], "quota_confirmed": True}
                        ],
                    },
                },
                "default_binding": {"provider_id": "free-pool", "model_id": "auto"},
            }
            with (
                mock.patch("integration.ofm_runtime.ensure_started", return_value={"url": "http://127.0.0.1:25600"}),
                costs.scope(project=project),
            ):
                client = free_pool.FreePoolClient("B", config_doc, lambda spec: spec)
                proj_path, choices = client._choices()
                self.assertEqual(Path(proj_path).resolve(), project.resolve())
                self.assertEqual(len(choices), 1)
                self.assertEqual(client.base_url, "http://127.0.0.1:25600/v1")
                self.assertEqual(client.config["providers"]["ofm-standalone"]["base_url"], "http://127.0.0.1:25600/v1")

    def test_ofm_runtime_resolve_node_prefers_env_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_node = Path(tmp) / "node.exe"
            fake_node.write_text("stub", encoding="utf-8")
            with (
                mock.patch("shutil.which", return_value=None),
                mock.patch.dict("os.environ", {"NOVEL_HELPER_NODE": str(fake_node)}, clear=False),
            ):
                resolved, extra_env = ofm_runtime._resolve_node_runtime()
                self.assertEqual(Path(resolved), fake_node.resolve())
                self.assertEqual(extra_env, {})


if __name__ == "__main__":
    unittest.main()
