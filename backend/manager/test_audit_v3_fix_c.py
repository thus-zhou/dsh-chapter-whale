"""C 域第三轮审计 API 回归：C3-02 导出目标、C3-03 schema 自愈、C3-04 只读
读接口、C3-18 项目互斥覆盖 publish/stage/polish。

审计证据见 ``/home/ubuntu/.hermes/cache/scratch/audit-v3/part-c.md``。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from integration import workbench_db as wb
from manager import app as module


class AuditV3FixCApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-v3-fix-c-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json"),
                        # 项目互斥测试只关心 admission，不真正起 worker。
                        patch.object(module.Operations, "_execute",
                                     lambda self, identity, args: None)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = module.create_app(self.root / "manager.db", start_dispatcher=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(
            json.dumps({"title": "审计回归"}), encoding="utf-8")
        registered = self.client.post("/api/projects", json={"path": str(self.project)},
                                      headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.identity = registered.json()["id"]
        created = self.client.post(f"/api/projects/{self.identity}/chapters",
                                   json={"chapter": 1, "title": "开端",
                                         "content": "第一段。\n“你来了。”\n" * 10},
                                   headers=self.headers)
        self.assertEqual(created.status_code, 200, created.text)

    def outside_dir(self) -> Path:
        holder = tempfile.TemporaryDirectory(prefix="audit-v3-outside-")
        self.addCleanup(holder.cleanup)
        return Path(holder.name)

    # ------------------------------------------------------------ C3-02
    def test_backup_destination_is_limited_to_manager_backup_root(self):
        outside = self.outside_dir() / "exfil" / "deep" / "backup"
        rejected = self.client.post(f"/api/projects/{self.identity}/backup",
                                    json={"destination": str(outside)}, headers=self.headers)
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(rejected.json()["code"], "unsafe_path")
        self.assertFalse(outside.exists())

        default = self.client.post(f"/api/projects/{self.identity}/backup",
                                   json={}, headers=self.headers)
        self.assertEqual(default.status_code, 200, default.text)
        destination = Path(default.json()["destination"])
        self.assertTrue(destination.is_relative_to(self.root / "backups"))
        self.assertTrue((destination / "backup_manifest.json").is_file())

        custom = self.root / "backups" / "custom"
        allowed = self.client.post(f"/api/projects/{self.identity}/backup",
                                   json={"destination": str(custom)}, headers=self.headers)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertTrue((custom / "backup_manifest.json").is_file())

    def test_export_legacy_limits_destination_and_snapshot_source(self):
        outside = self.outside_dir()
        bad_destination = outside / "legacy"
        rejected = self.client.post(
            f"/api/projects/{self.identity}/rollback/export-legacy",
            json={"destination": str(bad_destination)}, headers=self.headers)
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(rejected.json()["code"], "unsafe_path")
        self.assertFalse(bad_destination.exists())

        default = self.client.post(f"/api/projects/{self.identity}/rollback/export-legacy",
                                   json={}, headers=self.headers)
        self.assertEqual(default.status_code, 200, default.text)
        destination = Path(default.json()["destination"])
        self.assertTrue(destination.is_relative_to(self.root / "exports"))
        self.assertTrue((destination / "正文").is_dir())

        # snapshot 模式的来源目录同样只能来自作品或管理器备份/导出目录。
        snapshot = outside / "snapshot"
        (snapshot / "正文").mkdir(parents=True)
        (snapshot / "正文" / "第1章-偷读.md").write_text("不应被读取\n", encoding="utf-8")
        stolen = self.client.post(
            f"/api/projects/{self.identity}/rollback/export-legacy",
            json={"destination": str(self.root / "exports" / "stolen"),
                  "mode": "snapshot", "snapshot_dir": str(snapshot)},
            headers=self.headers)
        self.assertEqual(stolen.status_code, 400, stolen.text)
        self.assertEqual(stolen.json()["code"], "unsafe_path")
        self.assertFalse((self.root / "exports" / "stolen").exists())

    # ------------------------------------------------------------ C3-03
    def test_v09_endpoints_self_heal_missing_tables_and_columns(self):
        with wb.write_tx(self.project) as db:
            db.execute("DROP TABLE task_pauses")
        paused = self.client.post(f"/api/projects/{self.identity}/tasks/pause",
                                  json={"scope": "global", "reason": "审计"},
                                  headers=self.headers)
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertEqual(paused.json()["status"], "paused")

        with wb.write_tx(self.project) as db:
            db.execute("ALTER TABLE quality_reviews DROP COLUMN chapter_uid")
            db.execute("DROP TABLE context_manifests")
        reviewed = self.client.post(f"/api/projects/{self.identity}/quality/1/review",
                                    json={}, headers=self.headers)
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        context = self.client.get(f"/api/projects/{self.identity}/world/context?chapter=1",
                                  headers=self.headers)
        self.assertEqual(context.status_code, 200, context.text)

        diagnostics = self.client.get(f"/api/projects/{self.identity}/diagnostics",
                                      headers=self.headers)
        self.assertEqual(diagnostics.status_code, 200, diagnostics.text)
        report = diagnostics.json()
        self.assertTrue(report["schema"]["current"], report)
        self.assertEqual(report["integrity"], "ok")

    # ------------------------------------------------------------ C3-04
    def test_read_only_project_gets_do_not_create_the_database(self):
        other = self.root / "readonly-book"
        (other / "正文").mkdir(parents=True)
        (other / ".webnovel").mkdir()
        (other / ".webnovel" / "state.json").write_text(json.dumps({"title": "只读"}),
                                                        encoding="utf-8")
        (other / "正文" / "第1章-旧稿.md").write_text("第一段。\n", encoding="utf-8",
                                                     newline="\n")
        registered = self.client.post("/api/projects", json={"path": str(other)},
                                      headers=self.headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        identity = registered.json()["id"]
        for path in ("world-state?chapter=999", "quality", "tasks"):
            response = self.client.get(f"/api/projects/{identity}/{path}")
            self.assertEqual(response.status_code, 200, (path, response.text))
        self.assertFalse(wb.db_path(other).exists())
        self.assertFalse((other / ".webnovel" / "locks").exists())

    # ------------------------------------------------------------ C3-18
    def test_project_mutex_covers_publish_stage_polish_and_review(self):
        operations = self.app.state.operations
        daily = operations.start("daily", ["run", "--job-id", "job-c3"], "job:job-c3",
                                 {"project_id": self.identity,
                                  "project_path": str(self.project)})
        self.assertEqual(daily["kind"], "daily")
        attempts = (
            ("publish", ["publish", "--project", str(self.project), "--book", "审计回归",
                         "--account", "作者甲"]),
            ("stage", ["stage", "--project", str(self.project), "--book", "审计回归"]),
            ("polish", ["polish", "--project", str(self.project), "--chapter", "1"]),
            ("review", ["review", "--project", str(self.project), "--chapter", "1"]),
        )
        for kind, args in attempts:
            with self.assertRaises(HTTPException) as caught:
                operations.start(kind, args, f"project:{self.identity}",
                                 {"project_id": self.identity, "book": "审计回归"})
            self.assertEqual(caught.exception.status_code, 409, kind)
            self.assertIn("已有写作或日更任务", str(caught.exception.detail))


if __name__ == "__main__":
    unittest.main()
