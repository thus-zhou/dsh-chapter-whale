"""E01：Linux amd64 常驻存稿服务的单协调器、检查点、健康分项与备份还原。"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from integration import bridge, model_roles, resident_service as svc, scheduler, writer_runner


class ResidentServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        self.data = self.root / "integration_data"
        self.data.mkdir()
        self.addCleanup(patch.stopall)
        self.scheduler_path = self.data / "scheduler.json"
        self.enterContext(patch.object(scheduler, "SCHEDULER_PATH", self.scheduler_path))
        self.enterContext(patch.object(scheduler, "RUNS_ROOT", self.data / "runs"))
        self.enterContext(patch.object(bridge, "RUNTIME_ROOT", self.data / "runtime"))

    def write_jobs(self, count=1):
        jobs = {}
        project = self.root / "book"
        project.mkdir(parents=True, exist_ok=True)
        for index in range(1, count + 1):
            jobs[f"job{index}"] = {
                "name": f"任务{index}", "project": str(project), "book": "潮汐钟",
                "timezone": "Asia/Shanghai", "daily_time": "08:00", "enabled": True,
                "publication_mode": "draft_only",
            }
        self.scheduler_path.write_text(json.dumps(
            {"version": 2, "revision": 0, "settings": {"auto_schedule": True}, "jobs": jobs},
            ensure_ascii=False), encoding="utf-8")

    # --- E01.1 能力盘点 ---------------------------------------------------------
    def test_inventory_marks_supported_replaced_and_disabled(self):
        rows = svc.inventory()
        by_item = {row["item"]: row for row in rows}
        self.assertEqual(by_item["python"]["status"], "supported")
        self.assertEqual(by_item["credential"]["status"], "replaced")
        self.assertEqual(by_item["browser"]["status"], "disabled")
        self.assertEqual(by_item["dsh_bridge"]["status"], "disabled")
        self.assertEqual(by_item["ofm"]["status"], "disabled")
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(row["note"] for row in rows))

    def test_inventory_returns_copies(self):
        first = svc.inventory()
        first[0]["status"] = "tampered"
        self.assertEqual(svc.inventory()[0]["status"], "supported")

    # --- E01.5 健康分项 --------------------------------------------------------
    def test_health_separates_process_coordinator_config_and_volume(self):
        self.write_jobs(1)
        report = svc.health(self.root)
        self.assertTrue({"process", "coordinator", "config", "volume", "ok", "reasons"} <= set(report))
        self.assertIn("alive", report["process"])
        self.assertEqual(report["config"]["status"], "ready")
        self.assertEqual(report["config"]["jobs"], 1)
        self.assertTrue(report["volume"]["ok"])
        self.assertEqual(report["coordinator"]["state"], "unknown")
        # 没有进程心跳时整体不健康，HEALTHCHECK 才有意义。
        self.assertFalse(report["ok"])
        self.assertIn("process_not_running", report["reasons"])

    def test_health_never_touches_model_config(self):
        boom = AssertionError("探活不得读取模型配置")
        with patch.object(model_roles, "load_config", side_effect=boom):
            report = svc.health(self.root)
        self.assertIn("config", report)

    # --- E01.3 配置与卷诊断 -----------------------------------------------------
    def test_missing_config_is_empty_not_ready(self):
        report = svc.config_report(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "empty")
        self.assertIn("先建任务", report["reason"])

    def test_broken_config_is_reported(self):
        self.scheduler_path.write_text("{ not json", encoding="utf-8")
        report = svc.config_report(self.root)
        self.assertEqual(report["status"], "broken")

    def test_config_without_jobs_dict_is_broken(self):
        self.scheduler_path.write_text(json.dumps({"version": 2}), encoding="utf-8")
        self.assertEqual(svc.config_report(self.root)["status"], "broken")

    def test_config_with_auto_schedule_off_is_broken_not_ready(self):
        self.write_jobs(1)
        document = json.loads(self.scheduler_path.read_text(encoding="utf-8"))
        document["settings"]["auto_schedule"] = False
        self.scheduler_path.write_text(json.dumps(document), encoding="utf-8")
        report = svc.config_report(self.root)
        self.assertEqual(report["status"], "broken")
        self.assertIn("总开关", report["reason"])

    def test_config_with_missing_project_is_broken(self):
        self.write_jobs(1)
        document = json.loads(self.scheduler_path.read_text(encoding="utf-8"))
        document["jobs"]["job1"]["project"] = str(self.root / "nowhere")
        self.scheduler_path.write_text(json.dumps(document), encoding="utf-8")
        report = svc.config_report(self.root)
        self.assertEqual(report["status"], "broken")
        self.assertIn("作品目录不存在", report["reason"])

    def test_read_only_volume_still_returns_four_without_traceback(self):
        with patch.object(svc, "volume_report",
                          return_value={"ok": False, "status": "read_only", "reason": "只读"}):
            with patch.object(bridge, "write_json_atomic",
                              side_effect=PermissionError(13, "Permission denied")):
                code = svc.run(self.root, once=True)
        self.assertEqual(code, 4)

    def test_root_governs_scheduler_path(self):
        self.write_jobs(1)
        original = scheduler.SCHEDULER_PATH
        calls = []
        with patch.object(scheduler, "due_jobs", side_effect=lambda: calls.append(scheduler.SCHEDULER_PATH) or []):
            svc.run(self.root, once=True)
        self.assertEqual(Path(calls[0]), self.scheduler_path)
        self.assertEqual(scheduler.SCHEDULER_PATH, original)

    def test_read_only_volume_is_diagnosed(self):
        target = self.root / "data/probe"
        with patch.object(Path, "write_text", side_effect=OSError("read-only file system")):
            report = svc.volume_report(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "read_only")
        self.assertIn("只读", report["reason"])
        self.assertFalse(target.exists())

    def test_low_space_stops_scheduling(self):
        report = svc.volume_report(self.root, min_free=10 ** 15)
        self.assertEqual(report["status"], "low_space")
        self.assertFalse(report["ok"])

    def test_full_disk_is_not_misreported_as_read_only(self):
        import errno

        with patch.object(Path, "write_text",
                          side_effect=OSError(errno.ENOSPC, "No space left on device")):
            report = svc.volume_report(self.root)
        self.assertEqual(report["status"], "low_space")
        self.assertIn("磁盘已满", report["reason"])

    def test_health_command_exit_code_follows_ok(self):
        self.write_jobs(1)
        self.assertEqual(svc.main(["health", "--root", str(self.root)]), 1)
        service = svc.Service(self.root).acquire()
        self.addCleanup(service.release)
        svc.write_heartbeat(self.root, state="idle")
        self.assertEqual(svc.main(["health", "--root", str(self.root)]), 0)

    # --- E01.4 单协调器 ---------------------------------------------------------
    def test_second_instance_is_refused_and_first_still_owns_pid(self):
        first = svc.Service(self.root).acquire()
        self.addCleanup(first.release)
        self.assertEqual(svc.read_pid(self.root), os.getpid())
        with self.assertRaises(svc.SingletonBusy):
            svc.Service(self.root).acquire()
        self.assertTrue(svc.health(self.root)["process"]["alive"])

    def test_release_clears_pid_and_allows_reacquire(self):
        service = svc.Service(self.root).acquire()
        service.release()
        self.assertFalse(svc.service_paths(self.root)["pid"].exists())
        again = svc.Service(self.root).acquire()
        again.release()

    def test_stale_pid_file_is_not_treated_as_alive(self):
        svc.service_paths(self.root)["dir"].mkdir(parents=True, exist_ok=True)
        svc.service_paths(self.root)["pid"].write_text("999999", encoding="utf-8")
        self.assertFalse(svc._pid_alive(999999))
        self.assertFalse(svc.health(self.root)["process"]["alive"])

    def test_second_process_cannot_claim_the_same_job(self):
        """跨进程：父进程持锁时，子进程启动必须退出码 2 且不认领任务。"""
        import subprocess
        import sys

        service = svc.Service(self.root).acquire()
        self.addCleanup(service.release)
        backend = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(backend)
        env["NOVEL_HELPER_ROOT"] = str(self.root)
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-m", "integration.resident_service",
             "start", "--root", str(self.root), "--once"],
            cwd=str(backend), env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 2, result.stderr)
        # 探活式启动不能覆盖正在工作那个实例的检查点。
        self.assertNotEqual(svc.read_checkpoint(self.root).get("state"), "duplicate")

    # --- E01.4 主循环与停止 -----------------------------------------------------
    def test_once_claims_nothing_when_config_empty(self):
        calls = []
        with patch.object(scheduler, "due_jobs", side_effect=lambda: calls.append(1) or []):
            code = svc.run(self.root, once=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        checkpoint = svc.read_checkpoint(self.root)
        self.assertEqual(checkpoint["state"], "degraded")
        self.assertIn("尚未初始化", checkpoint["reason"])

    def test_once_runs_due_job_and_writes_checkpoint(self):
        self.write_jobs(1)
        seen = []
        with patch.object(scheduler, "due_jobs", return_value=[{"id": "job1"}]):
            with patch.object(scheduler, "run_once",
                              side_effect=lambda job_id: seen.append(job_id) or {"status": "success"}):
                code = svc.run(self.root, once=True)
        self.assertEqual(code, 0)
        self.assertEqual(seen, ["job1"])
        checkpoint = svc.read_checkpoint(self.root)
        self.assertEqual(checkpoint["cycles"], 1)
        self.assertEqual(checkpoint["claimed"], 1)
        self.assertEqual(checkpoint["skipped"], 0)
        self.assertEqual(checkpoint["state"], "stopped")

    def test_outcome_is_counted_by_status_not_by_call(self):
        self.write_jobs(1)
        results = {"status": "busy"}
        with patch.object(scheduler, "due_jobs", return_value=[{"id": "job1"}]):
            with patch.object(scheduler, "run_once", side_effect=lambda job_id: results):
                svc.run(self.root, once=True)
        checkpoint = svc.read_checkpoint(self.root)
        self.assertEqual(checkpoint["claimed"], 0)
        self.assertEqual(checkpoint["skipped"], 1)
        results = {"status": "blocked"}
        with patch.object(scheduler, "due_jobs", return_value=[{"id": "job1"}]):
            with patch.object(scheduler, "run_once", side_effect=lambda job_id: results):
                svc.run(self.root, once=True)
        self.assertEqual(svc.read_checkpoint(self.root)["blocked"], 1)

    def test_stop_request_prevents_new_claims(self):
        self.write_jobs(2)
        seen = []

        def due():
            return [{"id": "job1"}, {"id": "job2"}]

        def claim(job_id):
            seen.append(job_id)
            svc.request_stop(15)

        with patch.object(scheduler, "due_jobs", side_effect=due):
            with patch.object(scheduler, "run_once", side_effect=claim):
                svc._STOP.update(requested=False, signal="")
                code = svc.run(self.root, once=True)
        self.assertEqual(code, 0)
        self.assertEqual(seen, ["job1"])
        checkpoint = svc.read_checkpoint(self.root)
        self.assertEqual(checkpoint["state"], "stopped")
        self.assertEqual(checkpoint["signal"], "15")
        svc._STOP.update(requested=False, signal="")

    def test_read_only_volume_refuses_to_start(self):
        with patch.object(svc, "volume_report", return_value={"ok": False, "status": "read_only", "reason": "x"}):
            code = svc.run(self.root, once=True)
        self.assertEqual(code, 4)
        self.assertEqual(svc.read_checkpoint(self.root)["state"], "refused")

    def test_broken_due_jobs_does_not_kill_service(self):
        self.write_jobs(1)
        with patch.object(scheduler, "due_jobs", side_effect=ValueError("scheduler.json 必须是对象")):
            code = svc.run(self.root, once=True, max_cycles=1)
        self.assertEqual(code, 0)
        self.assertEqual(svc.read_checkpoint(self.root)["claimed"], 0)

    def test_job_failure_is_recorded_but_service_continues(self):
        self.write_jobs(1)
        with patch.object(scheduler, "due_jobs", return_value=[{"id": "job1"}]):
            with patch.object(scheduler, "run_once", side_effect=RuntimeError("模型不可用")):
                code = svc.run(self.root, once=True)
        self.assertEqual(code, 0)
        self.assertEqual(svc.read_checkpoint(self.root)["claimed"], 0)

    # --- E01.7 备份与还原 -------------------------------------------------------
    def make_db(self, name="costs.sqlite3"):
        path = self.data / name
        connection = sqlite3.connect(str(path))
        connection.execute("create table if not exists cost (id integer primary key, value text)")
        connection.execute("insert into cost (value) values ('x')")
        connection.commit()
        connection.close()
        return path

    def test_backup_copies_sqlite_and_json_state(self):
        self.make_db()
        self.write_jobs(1)
        manifest = svc.backup(self.root)
        target = Path(manifest["dest"])
        self.assertTrue((target / "integration_data" / "costs.sqlite3").exists())
        self.assertTrue((target / "integration_data" / "scheduler.json").exists())
        self.assertTrue((target / "backup.json").exists())
        clone = sqlite3.connect(str(target / "integration_data" / "costs.sqlite3"))
        try:
            self.assertEqual(clone.execute("select count(*) from cost").fetchone()[0], 1)
        finally:
            clone.close()

    def test_restore_refuses_to_overwrite_existing_files(self):
        self.write_jobs(1)
        manifest = svc.backup(self.root)
        with self.assertRaises(ValueError):
            svc.restore(self.root, Path(manifest["dest"]))
        restored = svc.restore(self.root, Path(manifest["dest"]), force=True)
        self.assertGreater(restored["restored"], 0)

    def test_backup_includes_chapters_receipts_and_runs(self):
        chapter = self.root / "works" / "潮汐钟" / "正文" / "第0001章 潮声.md"
        chapter.parent.mkdir(parents=True, exist_ok=True)
        chapter.write_text("第1章 潮声\n\n林砚把钥匙收进内袋。\n", encoding="utf-8")
        receipt = self.root / "works" / "潮汐钟" / ".webnovel" / "writer_receipts.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"1": {"sha256": "a" * 64}}), encoding="utf-8")
        runs = self.data / "runs" / "job1" / "20260101-run.json"
        runs.parent.mkdir(parents=True, exist_ok=True)
        runs.write_text(json.dumps({"status": "success"}), encoding="utf-8")
        manifest = svc.backup(self.root)
        target = Path(manifest["dest"])
        self.assertTrue((target / "works/潮汐钟/正文/第0001章 潮声.md").exists())
        self.assertTrue((target / "works/潮汐钟/.webnovel/writer_receipts.json").exists())
        self.assertTrue((target / "integration_data/runs/job1/20260101-run.json").exists())
        paths = {Path(row["path"]).as_posix() for row in manifest["contents"]}
        self.assertIn("works/潮汐钟/正文/第0001章 潮声.md", paths)
        self.assertTrue(all(row["sha256"] for row in manifest["contents"]))

    def test_backup_does_not_pack_previous_backups(self):
        svc.backup(self.root)
        second = svc.backup(self.root)
        paths = {row["path"] for row in second["contents"]}
        self.assertFalse(any("resident_service" in path for path in paths))

    def test_restore_refuses_when_lock_held_without_pid(self):
        manifest = svc.backup(self.root)
        service = svc.Service(self.root).acquire()
        self.addCleanup(service.release)
        svc.service_paths(self.root)["pid"].unlink(missing_ok=True)
        with self.assertRaises(ValueError) as caught:
            svc.restore(self.root, Path(manifest["dest"]), force=True)
        self.assertIn("服务仍在运行", str(caught.exception))

    def test_restore_rejects_other_root_unless_allowed(self):
        self.write_jobs(1)
        manifest = svc.backup(self.root)
        other = self.root / "other"
        other.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError) as caught:
            svc.restore(other, Path(manifest["dest"]))
        self.assertIn("另一个卷", str(caught.exception))
        allowed = svc.restore(other, Path(manifest["dest"]), allow_root_mismatch=True)
        self.assertGreater(allowed["restored"], 0)

    def test_health_reports_stale_heartbeat(self):
        self.write_jobs(1)
        svc.write_heartbeat(self.root, state="idle")
        report = svc.health(self.root, interval=1, max_age=-1)
        self.assertFalse(report["ok"])
        self.assertTrue(any(reason.startswith("heartbeat_stale") for reason in report["reasons"]))

    def test_shutdown_watchdog_forces_exit_after_limit(self):
        import subprocess
        import sys

        backend = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(backend)
        script = (
            "from pathlib import Path\n"
            "import time\n"
            "from integration import resident_service as svc\n"
            f"svc._start_stop_watchdog(Path({str(self.root)!r}), 0.5)\n"
            "svc.request_stop(15)\n"
            "time.sleep(30)\n"
            "print('not-exited')\n"
        )
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script],
                                cwd=str(backend), env=env, capture_output=True, text=True, timeout=60)
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertLess(elapsed, 20, "限时退出没有生效")
        self.assertNotIn("not-exited", result.stdout)

    # --- E01.6 时区 -------------------------------------------------------------
    def test_service_now_uses_job_timezone(self):
        shanghai = svc.service_now("Asia/Shanghai")
        utc = svc.service_now("UTC")
        self.assertEqual(shanghai.utcoffset().total_seconds(), 8 * 3600)
        self.assertEqual(utc.utcoffset().total_seconds(), 0)

    def test_unknown_timezone_falls_back_and_is_marked(self):
        value = svc.service_now("Not/AZone")
        self.assertEqual(value.utcoffset().total_seconds(), 8 * 3600)
