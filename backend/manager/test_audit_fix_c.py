"""C 域审计回归：任务 PUT 合并、null 语义、legacy 双任务、ID/名称校验、
daily 项目互斥与 approve 后 UI 降级（P2-3 UI / P2-10~P2-15）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from integration import bridge, scheduler
from manager import app as module


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


class AuditFixCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-fix-c-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text('{"title":"测试作品"}', encoding="utf-8")
        self.ai_path = self.root / "ai.json"
        self.ai_path.write_text(json.dumps({"base_url": "https://fixture.invalid/v1", "model": "m",
                                            "api_key": "NOT-A-REAL-KEY"}), encoding="utf-8")
        self.scheduler_path = self.root / "scheduler.json"
        self.db_path = self.root / "manager.db"
        self.patches = [
            patch.object(module, "DATA", self.root),
            patch.object(module, "AI_PATH", self.ai_path),
            patch.object(module, "public_ai", return_value={"configured": True}),
            patch.object(module.secret_store, "codec", lambda: fake_pair()),
            patch.object(scheduler, "SCHEDULER_PATH", self.scheduler_path),
            patch.object(scheduler, "RUNS_ROOT", self.root / "runs"),
            patch.object(bridge, "COMBINED_ROOT", self.root),
            patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"),
            patch.object(module.Operations, "_execute", lambda self, identity, args: None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        module._AI_MIGRATION_TRIED = False
        self.app = module.create_app(self.db_path, start_dispatcher=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        self.register()

    def register(self) -> str:
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def seed_jobs(self, jobs: dict) -> None:
        self.scheduler_path.write_text(json.dumps(
            {"version": 2, "revision": 0, "updated_at": "", "jobs": jobs}, ensure_ascii=False),
            encoding="utf-8")

    def jobs(self) -> dict:
        return scheduler.load_scheduler()["jobs"]

    def job_body(self, **overrides) -> dict:
        body = {"project": str(self.project), "book": "潮汐钟"}
        body.update(overrides)
        return body

    def latest_job(self) -> dict:
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1, jobs)
        return next(iter(jobs.values()))

    # ---- P2-10: PUT 省略字段不得重置 -------------------------------------
    def test_partial_put_preserves_fields_not_sent(self):
        created = self.client.post("/api/jobs", headers=self.headers, json=self.job_body(
            name="夜航", enabled=True, chapters_per_run=3, word_count=4200, max_revisions=2,
            daily_time="08:00", timezone="Asia/Tokyo", platform="qidian", account="作者甲",
            delivery_mode="serial", publication_mode="draft_only",
        ))
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["id"]

        updated = self.client.put(f"/api/jobs/{job_id}", headers=self.headers,
                                  json={"project": str(self.project), "book": "潮汐钟",
                                        "daily_time": "09:30"})
        self.assertEqual(updated.status_code, 200, updated.text)
        job = self.jobs()[job_id]
        self.assertEqual(job["name"], "夜航")
        self.assertIs(job["enabled"], True)
        self.assertEqual(job["chapters_per_run"], 3)
        self.assertEqual(job["word_count"], 4200)
        self.assertEqual(job["max_revisions"], 2)
        self.assertEqual(job["delivery_mode"], "serial")
        self.assertEqual(job["timezone"], "Asia/Tokyo")
        self.assertEqual(job["platform"], "qidian")
        self.assertEqual(job["account"], "作者甲")
        self.assertEqual(job["daily_time"], "09:30")
        self.assertEqual(job["publication_mode"], "draft_only")

    def test_partial_put_keeps_publish_mode_and_cycle_config(self):
        account = self.root / "account.json"
        account.write_text("{}", encoding="utf-8")
        self.seed_jobs({"pub": {
            "name": "发布任务", "project": str(self.project), "book": "潮汐钟", "account": "作者甲",
            "publication_mode": "publish_now", "enabled": True, "daily_time": "08:00",
            "timezone": "Asia/Shanghai", "chapters_per_run": 2, "word_count": 3500,
            "max_revisions": 1, "delivery_mode": "batch",
        }})
        with patch.object(bridge, "account_state_path", lambda name: account):
            # 省略 publication_mode，且显式 null 都不允许把发布任务降级成只存稿。
            for payload in (
                {"project": str(self.project), "book": "潮汐钟"},
                {"project": str(self.project), "book": "潮汐钟", "publication_mode": None},
            ):
                response = self.client.put("/api/jobs/pub", headers=self.headers, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(self.jobs()["pub"]["publication_mode"], "publish_now")

    # ---- P2-11: schedule_buffer 缺省 vs 显式 null -------------------------
    def test_schedule_buffer_null_clears_but_omission_keeps(self):
        created = self.client.post("/api/jobs", headers=self.headers, json=self.job_body(
            publication_mode="draft_only", schedule_buffer={"slots": ["10:00"]},
        ))
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["id"]
        self.assertEqual(self.jobs()[job_id]["schedule_buffer"], {"slots": ["10:00"]})

        cleared = self.client.put(f"/api/jobs/{job_id}", headers=self.headers,
                                  json=self.job_body(schedule_buffer=None))
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(self.jobs()[job_id]["schedule_buffer"])

        restored = self.client.put(f"/api/jobs/{job_id}", headers=self.headers,
                                   json=self.job_body(schedule_buffer={"slots": ["11:00"]}))
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.jobs()[job_id]["schedule_buffer"], {"slots": ["11:00"]})

        # 字段缺省：普通保存不得擦掉刚恢复的缓冲计划。
        kept = self.client.put(f"/api/jobs/{job_id}", headers=self.headers, json=self.job_body())
        self.assertEqual(kept.status_code, 200, kept.text)
        self.assertEqual(self.jobs()[job_id]["schedule_buffer"], {"slots": ["11:00"]})

    # ---- P2-12: legacy publish_now 存在时裸 POST 不得新建双任务 ----------
    def test_bare_post_does_not_create_second_draft_job_for_legacy_publish(self):
        self.seed_jobs({"legacy": {
            "name": "旧发布任务", "project": str(self.project), "book": "潮汐钟",
            "account": "作者甲", "enabled": True, "daily_time": "08:00",
        }})  # 无 publication_mode 字段：按 legacy publish_now 处理。
        bare = self.client.post("/api/jobs", headers=self.headers, json=self.job_body())
        self.assertEqual(bare.status_code, 409, bare.text)
        self.assertIn("显式", bare.json()["message"])
        self.assertEqual(list(self.jobs()), ["legacy"])

        explicit = self.client.post("/api/jobs", headers=self.headers,
                                    json=self.job_body(publication_mode="draft_only"))
        self.assertEqual(explicit.status_code, 200, explicit.text)
        modes = sorted(scheduler.publication_mode(job) for job in self.jobs().values())
        self.assertEqual(modes, ["draft_only", "publish_now"])

    # ---- P2-13: 非法显式 job id 必须 400 ---------------------------------
    def test_illegal_explicit_job_id_is_rejected_not_rewritten(self):
        for bad in ("../escape", "a/b", "a\\b", "a..b", "bad:id", "x" * 81):
            response = self.client.post("/api/jobs", headers=self.headers,
                                        json=self.job_body(job_id=bad))
            self.assertEqual(response.status_code, 400, f"{bad!r}: {response.text}")
            self.assertEqual(self.jobs(), {})

        spaced = self.client.post("/api/jobs", headers=self.headers,
                                  json=self.job_body(job_id="我的 任务"))
        self.assertEqual(spaced.status_code, 200, spaced.text)
        self.assertEqual(spaced.json()["id"], "我的-任务")

    # ---- P2-14: daily 无 metadata 时从 --job-id 解析项目 ------------------
    def test_daily_operation_without_metadata_uses_job_project_for_mutex(self):
        self.seed_jobs({"daily": {
            "name": "日更", "project": str(self.project), "book": "潮汐钟", "account": "",
            "publication_mode": "draft_only", "enabled": True, "daily_time": "08:00",
            "timezone": "Asia/Shanghai", "chapters_per_run": 1, "word_count": 3500,
            "max_revisions": 1, "delivery_mode": "batch",
        }})
        operations = module.Operations(module.Store(self.db_path))
        started = operations.start("daily", ["run", "--job-id", "daily"], "job:daily")
        self.assertEqual(started["kind"], "daily")
        stored = [item for item in module.Store(self.db_path).operations() if item["kind"] == "daily"]
        self.assertEqual(len(stored), 1)
        expected = module.project_path_key(str(self.project.resolve()))
        self.assertEqual(stored[0]["project_id"], expected)

        # 真正生效的项目互斥：同书第二个 daily 必须被挡住，而不是因 project_id 为空放行。
        with self.assertRaises(module.HTTPException) as raised:
            operations.start("daily", ["run", "--job-id", "daily"], "job:daily-2")
        self.assertEqual(raised.exception.status_code, 409)

    def test_daily_operation_unknown_job_still_starts_without_project_key(self):
        operations = module.Operations(module.Store(self.db_path))
        started = operations.start("daily", ["run", "--job-id", "missing"], "job:missing")
        self.assertEqual(started["kind"], "daily")
        stored = [item for item in module.Store(self.db_path).operations() if item["kind"] == "daily"]
        self.assertEqual(len(stored), 1)
        self.assertFalse(stored[0].get("project_id"))

    # ---- P2-15: 默认任务名截断到 96 -------------------------------------
    def test_generated_default_name_is_truncated_to_96(self):
        book = "长" * 96
        created = self.client.post("/api/jobs", headers=self.headers,
                                   json=self.job_body(book=book, publication_mode="draft_only"))
        self.assertEqual(created.status_code, 200, created.text)
        job = self.latest_job()
        self.assertEqual(len(job["name"]), 96)
        self.assertEqual(job["name"], f"《{book}》 · 日更"[:96])

        too_long = self.client.post("/api/jobs", headers=self.headers,
                                    json=self.job_body(book="另一本书", name="名" * 97))
        self.assertEqual(too_long.status_code, 422, too_long.text)

    # ---- P2-3 UI: human_approved 后隐藏“最终审查” ------------------------
    def test_manager_ui_hides_final_review_after_human_approval(self):
        source = (Path(module.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
        preview = source.split('"preview":', 1)[1].split('"approve-review":', 1)[0]
        self.assertIn('c.review_status==="human_approved"', preview)
        self.assertIn('?\'<span class="pill pill-success">人工复核通过</span>\':button("review"', preview)
        self.assertIn("最终审查", preview)

    def test_desktop_chapter_row_replaces_final_review_after_human_approval(self):
        source = (module.ROOT.parent / "client.js").read_text(encoding="utf-8")
        marker = "row.reviewed && row.review_status === 'human_approved'"
        self.assertEqual(source.count(marker), 1)
        segment = source.split(marker, 1)[1].split("'修订预览'", 1)[0]
        self.assertIn("'已批准'", segment)
        self.assertIn("row.human_review_required && !row.reviewed", segment)
        self.assertLess(segment.index("'已批准'"), segment.index("'重新审查'"))


if __name__ == "__main__":
    unittest.main()
