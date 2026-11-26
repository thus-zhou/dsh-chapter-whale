"""A01：publication_mode 字段穿透 + 只存稿（draft_only）闭环。

只存稿的验收口径（本文件全部断言围绕它）：
- 生成 + 完整审查 + 本机落稿都发生；
- stage_project / run_publish / sync_manifest 一次都不发生；
- 完成与否只看 writer_runner 的本地回执；
- 审查没过保留正文与问题，批次停在 needs_revision，重跑只补没过的章；
- 旧任务没有该字段时仍是发布语义，旧 PUT 不带该键也不会被降级。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integration import bridge, daily_word_goal, draft_delivery, model_roles, scheduler, writer_runner as writer


def _args(**overrides):
    values = {
        "job_id": "tide", "name": "潮汐钟日更", "project": "", "book": "潮汐钟",
        "account": "", "daily_time": "08:00", "daily_times": [],
        "quota_phases": [], "slot_quotas": None, "delivery_mode": "batch",
        "timezone": "Asia/Shanghai", "chapters_per_run": 1, "word_count": 2000,
        "max_revisions": 1, "volume": None, "approval_mode": "unattended",
        "disabled": False,
    }
    values.update(overrides)
    return type("Args", (), values)()


class DraftDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=writer.COMBINED_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "works" / "潮汐钟"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        self.state = self.project / ".webnovel" / "state.json"
        self.state.write_text(json.dumps({"progress": {"current_chapter": 0}}), encoding="utf-8")
        self.scheduler_path = self.root / "scheduler.json"
        self.enterContext(patch.object(scheduler, "SCHEDULER_PATH", self.scheduler_path))
        self.enterContext(patch.object(scheduler, "RUNS_ROOT", self.root / "runs"))
        # 协调器锁与平台队列锁默认落在 repo 下；不隔离就会把测试状态写进源码树。
        self.enterContext(patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"))
        self.enterContext(patch.object(bridge, "FANQIE_ROOT", self.root / "fanqie"))
        self.enterContext(patch.object(bridge, "MANIFEST_PATH", self.root / "manifest.json"))
        self.enterContext(patch.dict(os.environ, {
            "NOVEL_HELPER_AI_CONFIG": str(self.root / "ai.json"),
            "AI_API_KEY": "", "AI_MODEL": "",
            "NOVEL_HELPER_NOTIFICATIONS_DB": str(self.root / "notifications.sqlite3"),
        }))
        self.enterContext(patch.object(model_roles, "load_config", return_value={}))
        self.enterContext(patch.object(model_roles, "enabled", return_value=True))
        # 平台侧动作一律禁止：任何一次调用都是回归。
        for name in ("stage_project", "run_publish", "sync_manifest", "validate_queue_origin"):
            self.enterContext(patch.object(
                bridge, name, side_effect=AssertionError(f"只存稿不得调用 bridge.{name}")))
        self.receipts = {}
        self.enterContext(patch.object(
            draft_delivery.writer, "reviewed_chapters", side_effect=lambda project: dict(self.receipts)))
        self.generate = self.enterContext(patch.object(draft_delivery.writer, "generate_chapter"))

    # --- 夹具 -----------------------------------------------------------------
    def add_job(self, **overrides):
        values = {"project": str(self.project)}
        values.update(overrides)
        return scheduler.add_job(_args(**values))

    def write_chapter(self, chapter, text=None):
        path = self.project / "正文" / f"第{chapter:04d}章 潮声.md"
        path.write_text(text or f"第{chapter}章\n\n林禾在码头听见怀表响了一声，潮水退了半尺。", encoding="utf-8")
        return path

    def fake_receipt(self, chapter, path):
        import hashlib
        return {"chapter_id": chapter, "destination": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "review": {"success": True, "review_decision": "pass",
                           "quality": {"format": "json", "verdict": "pass", "issues": [], "not_applicable": [],
                                       "scores": {"setting": 90, "plot": 90, "character": 90,
                                                 "prose": 90, "dialogue": 90, "style": 90}}}, "reviewed_at": bridge.now_iso(),
                "post_save": {"shared_memory": {"status": "synced"}, "entities": {"status": "synced"},
                              "rag_indexed": True, "continuity_written": True},
                "creative_contract_hash": bridge.creative_contract_hash(self.project)}

    def generate_ok(self, project, word_count, max_revisions, chapter_id):
        path = self.write_chapter(chapter_id)
        self.receipts[chapter_id] = self.fake_receipt(chapter_id, path)
        return {"project": str(project), "chapter_id": chapter_id, "destination": str(path),
                "status": "reviewed", "review": {"success": True, "review_decision": "pass",
                    "quality": {"format": "json", "verdict": "pass", "issues": [], "not_applicable": [],
                                "scores": {"setting": 90, "plot": 90, "character": 90,
                                          "prose": 90, "dialogue": 90, "style": 90}}}}

    # --- 字段穿透 ---------------------------------------------------------------
    def test_new_job_defaults_to_draft_only_without_account(self):
        summary = self.add_job()
        self.assertEqual(summary["publication_mode"], "draft_only")
        self.assertEqual(summary["remote_state"], "not_applicable")
        self.assertEqual(summary["drafts"], {"saved": 0, "reviewed": 0, "pending": 0, "words": 0, "updated_at": ""})
        self.assertEqual(summary["account"], "")

    def test_publish_job_still_requires_login(self):
        with self.assertRaises(ValueError):
            self.add_job(publication_mode="publish_now")
        with self.assertRaises(FileNotFoundError) as caught:
            self.add_job(publication_mode="publish_now", account="林禾")
        self.assertIn("尚未登录", str(caught.exception))

    def test_platform_scheduled_requires_account_and_rejects_unknown_modes(self):
        # 0.6.1 起 platform_scheduled 是一等模式；但排期必须绑定账号，否则无法回读身份。
        with self.assertRaises(ValueError) as caught:
            self.add_job(publication_mode="platform_scheduled")
        self.assertIn("账号", str(caught.exception))
        self.assertIn("platform_scheduled", scheduler.PUBLICATION_MODES)
        with self.assertRaises(ValueError):
            scheduler.validate_publication_mode("every_other_day")

    def test_legacy_job_without_field_keeps_publish_semantics(self):
        legacy = {"project": str(self.project), "book": "潮汐钟", "account": "林禾"}
        self.assertEqual(scheduler.publication_mode(legacy), "publish_now")
        self.assertTrue(scheduler.is_publish_job(legacy))
        legacy["publication_mode"] = ""
        self.assertEqual(scheduler.publication_mode(legacy), "publish_now")

    def test_old_put_without_field_does_not_downgrade(self):
        scheduler.SCHEDULER_PATH.write_text(json.dumps({"schema_version": 1, "jobs": {"old": {
            "name": "旧任务", "project": str(self.project), "book": "潮汐钟", "account": "林禾",
            "daily_time": "08:00", "daily_times": [], "timezone": "Asia/Shanghai",
            "chapters_per_run": 1, "word_count": 2000, "max_revisions": 1, "volume": None,
            "approval_mode": "unattended", "enabled": False, "delivery_mode": "batch",
        }}}, ensure_ascii=False), encoding="utf-8")
        patched = self.enterContext(patch.object(
            scheduler.bridge, "account_state_path", side_effect=lambda name: Path(__file__)))
        self.assertTrue(patched)
        updated = scheduler.update_job("old", {"name": "改名后"})
        self.assertEqual(updated["name"], "改名后")
        # 语义必须原样保留：仍是发布任务，绝不能被降级成只存稿。
        self.assertEqual(updated["publication_mode"], "publish_now")
        self.assertTrue(scheduler.is_publish_job(scheduler.load_scheduler()["jobs"]["old"]))

    def test_binding_conflict_is_skipped_for_draft_jobs(self):
        self.enterContext(patch.object(bridge, "account_state_path", side_effect=lambda name: Path(__file__)))
        self.add_job(job_id="pub", publication_mode="publish_now", account="林禾")
        other = self.root / "works" / "另一本"
        (other / "正文").mkdir(parents=True)
        # 同名书 + 不同项目：发布任务之间会冲突，只存稿任务不占平台位置，必须放行。
        summary = self.add_job(job_id="draft", project=str(other))
        self.assertEqual(summary["publication_mode"], "draft_only")

    # --- 只存稿执行 -------------------------------------------------------------
    def test_two_chapter_draft_run_writes_body_and_never_touches_platform(self):
        self.add_job(chapters_per_run=2)
        self.generate.side_effect = self.generate_ok
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["target_ids"], [1, 2])
        self.assertEqual(result["remote_state"], "not_applicable")
        self.assertEqual(result["verification"], draft_delivery.DRAFT_VERIFICATION)
        self.assertEqual(sorted(p.name for p in (self.project / "正文").glob("*.md")),
                         ["第0001章 潮声.md", "第0002章 潮声.md"])
        summary = scheduler._job_summary("tide", scheduler.load_scheduler()["jobs"]["tide"])
        self.assertEqual(summary["drafts"]["reviewed"], 2)
        self.assertEqual(summary["remote_state"], "not_applicable")

    def test_draft_run_starts_after_existing_hundred_chapters(self):
        for chapter in range(1, 101):
            self.write_chapter(chapter, f"第{chapter}章\n\n旧稿正文。")
        self.add_job(chapters_per_run=2)
        self.generate.side_effect = self.generate_ok
        result = scheduler.run_once("tide")
        self.assertEqual(result["target_ids"], [101, 102])
        self.assertEqual(result["status"], "success")

    def test_budget_exhaustion_keeps_saved_chapters_and_stops_batch(self):
        self.add_job(chapters_per_run=2)
        calls = []

        def budget(project, word_count, max_revisions, chapter_id):
            calls.append(chapter_id)
            if chapter_id == 2:
                raise draft_delivery.costs.BudgetExceeded("每日预算已用完")
            return self.generate_ok(project, word_count, max_revisions, chapter_id)

        self.generate.side_effect = budget
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "budget_exceeded")
        self.assertEqual(result["saved_ids"], [1])
        self.assertEqual(calls, [1, 2])
        job = scheduler.load_scheduler()["jobs"]["tide"]
        self.assertEqual(job["cycle"]["status"], "blocked")
        self.assertEqual(job["cycle"]["failure_kind"], "budget_exceeded")
        self.assertEqual([p.name for p in (self.project / "正文").glob("*.md")], ["第0001章 潮声.md"])

    def test_review_failure_keeps_body_and_stops_as_needs_revision(self):
        self.add_job()
        body = {"path": None}

        def failing(project, word_count, max_revisions, chapter_id):
            body["path"] = self.write_chapter(chapter_id)  # 正文留盘，但不写回执
            raise RuntimeError("保存前审查验证失败")

        self.generate.side_effect = failing
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "needs_revision")
        self.assertEqual(result["reason_code"], "review_failed")
        self.assertTrue(body["path"].is_file())
        job = scheduler.load_scheduler()["jobs"]["tide"]
        self.assertEqual(job["cycle"]["status"], "needs_revision")
        self.assertEqual(job["cycle"]["target_ids"], [1])
        self.assertEqual(job["last_status"], "needs_revision")
        self.assertIn("第 1 章", job["last_message"])

    def test_rerun_only_retries_the_chapter_that_failed(self):
        self.add_job(chapters_per_run=2)
        calls = []

        def pass_one(project, word_count, max_revisions, chapter_id):
            calls.append(chapter_id)
            if chapter_id == 2:
                self.write_chapter(chapter_id)
                raise RuntimeError("保存前审查验证失败")
            return self.generate_ok(project, word_count, max_revisions, chapter_id)

        self.generate.side_effect = pass_one
        self.assertEqual(scheduler.run_once("tide")["status"], "needs_revision")
        self.assertEqual(calls, [1, 2])

        def pass_two(project, word_count, max_revisions, chapter_id):
            calls.append(chapter_id)
            return self.generate_ok(project, word_count, max_revisions, chapter_id)

        calls.clear()
        self.generate.side_effect = pass_two
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "success")
        self.assertEqual(calls, [2])  # 第 1 章已有有效回执，不得重写
        self.assertEqual(sorted(result["target_ids"]), [1, 2])

    def test_body_saved_but_memory_failed_is_not_rewritten(self):
        self.add_job()

        def memory_failure(project, word_count, max_revisions, chapter_id):
            self.generate_ok(project, word_count, max_revisions, chapter_id)
            self.receipts[chapter_id]["post_save"]["shared_memory"] = {"status": "failed"}
            raise RuntimeError("共享记忆同步失败")

        self.generate.side_effect = memory_failure
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "metadata_pending")
        self.assertEqual(result["memory_pending"], [1])
        first_body = (self.project / "正文" / "第0001章 潮声.md").read_bytes()
        calls = []

        def pass_two(project, word_count, max_revisions, chapter_id):
            calls.append(chapter_id)
            return self.generate_ok(project, word_count, max_revisions, chapter_id)

        self.generate.side_effect = pass_two
        def repair(project, chapter):
            self.receipts[chapter]["post_save"]["shared_memory"] = {"status": "synced"}
            return self.receipts[chapter]["post_save"]
        with patch("integration.studio.sync_existing_artifacts", side_effect=repair):
            self.assertEqual(scheduler.run_once("tide")["status"], "success")
        self.assertNotIn(1, calls)  # 回执仍在，第 1 章正文不会重写
        self.assertEqual((self.project / "正文" / "第0001章 潮声.md").read_bytes(), first_body)

    def test_zero_revisions_reaches_generator(self):
        self.add_job(max_revisions=0)
        self.generate.side_effect = self.generate_ok
        self.assertEqual(scheduler.run_once("tide")["status"], "success")
        self.assertEqual(self.generate.call_args.kwargs["max_revisions"], 0)

    def test_wait_survives_reload_and_resumes_same_targets_when_due(self):
        from datetime import datetime, timedelta
        from integration.free_pool import PoolWait
        self.add_job(chapters_per_run=2)
        scheduler.update_settings({"auto_schedule": True})
        now = scheduler._now_for_job({"timezone": "Asia/Shanghai"})
        target = now + timedelta(minutes=5)
        self.generate.side_effect = PoolWait(target=target)
        waiting = scheduler.run_once("tide")
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["target_ids"], [1, 2])
        job = scheduler.load_scheduler()["jobs"]["tide"]
        self.assertEqual(datetime.fromisoformat(scheduler.next_due(job, now)), target)
        self.assertEqual(scheduler.due_jobs(now), [])
        self.assertEqual([j["id"] for j in scheduler.due_jobs(target + timedelta(seconds=1))], ["tide"])
        self.generate.side_effect = self.generate_ok
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["target_ids"], [1, 2])

    def test_each_missing_post_save_step_stops_completion_without_consuming_slot(self):
        for key in ("shared_memory", "entities", "rag_indexed", "continuity_written"):
            with self.subTest(key=key):
                self.receipts.clear()
                job_id = "missing-" + key
                self.add_job(job_id=job_id)
                try:
                    def partial(project, word_count, max_revisions, chapter_id):
                        value = self.generate_ok(project, word_count, max_revisions, chapter_id)
                        self.receipts[chapter_id]["post_save"][key] = False
                        return value
                    self.generate.side_effect = partial
                    result = scheduler.run_once(job_id)
                    self.assertEqual(result["status"], "metadata_pending")
                    job = scheduler.load_scheduler()["jobs"][job_id]
                    self.assertFalse(job.get("completed_slots"))
                finally:
                    with scheduler.config_transaction() as data:
                        data["jobs"].pop(job_id, None)

    def test_missing_model_blocks_without_writing(self):
        self.add_job()
        self.enterContext(patch.object(model_roles, "enabled", return_value=False))
        result = scheduler.run_once("tide")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason_code"], "model_unavailable")
        self.assertFalse(list((self.project / "正文").glob("*.md")))

    def test_transient_continuity_failure_with_synced_memory_retries(self):
        self.add_job()
        def partial(project, word_count, max_revisions, chapter_id):
            result = self.generate_ok(project, word_count, max_revisions, chapter_id)
            self.receipts[chapter_id]['post_save'].update(continuity_written=False,
                continuity_failure={'failure_kind':'transport','retryable':True})
            return result
        self.generate.side_effect = partial
        result = scheduler.run_once('tide')
        self.assertEqual(result['status'], 'waiting')
        self.assertEqual(result['failure_kind'], 'transport')
        self.assertTrue(result['cycle']['recovery']['automatic_retry'])

    def test_draft_progress_counts_local_receipts(self):
        path = self.write_chapter(1, "第1章\n\n林禾把怀表按在胸口，听见潮声倒退。")
        self.receipts[1] = self.fake_receipt(1, path)
        job = {"project": str(self.project), "book": "潮汐钟", "account": "",
               "timezone": "Asia/Shanghai", "publication_mode": "draft_only",
               "daily_word_goals": {scheduler._job_today({"timezone": "Asia/Shanghai"}): 3000}}
        value = daily_word_goal.progress(job, scheduler._job_today(job))
        self.assertEqual(value["source"], "local_review_receipts")
        self.assertEqual(value["counted_chapters"], [1])
        self.assertGreater(value["confirmed_words"], 0)


class SingleModelRequireModelTest(unittest.TestCase):
    def test_single_model_provider_schema_v1_is_accepted(self):
        cfg = {
            "provider_schema": 1,
            "multi_model": False,
            "default_binding": {"provider_id": "p1", "model_id": "m1"},
            "roles": {"B": {"provider_id": "", "model_id": ""}},
        }
        with patch.object(model_roles, "enabled", return_value=False), \
             patch.object(model_roles, "load_config", return_value=cfg), \
             patch.object(model_roles, "connection", return_value={"model": "m1", "api_key": "sk-test"}):
            self.assertIsNone(draft_delivery._require_model())

    def test_unconfigured_provider_schema_v1_is_rejected(self):
        cfg = {
            "provider_schema": 1,
            "multi_model": False,
            "default_binding": {"provider_id": "", "model_id": ""},
            "roles": {},
        }
        with patch.object(model_roles, "enabled", return_value=False), \
             patch.object(model_roles, "load_config", return_value=cfg), \
             patch.object(model_roles, "connection", return_value={"model": "", "api_key": ""}):
            msg = draft_delivery._require_model()
            self.assertIsInstance(msg, str)
            self.assertTrue(msg)


if __name__ == "__main__":
    unittest.main()
