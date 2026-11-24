"""P05：守护进程必须认清启动所有者、端口来源与实例身份，且不做任何平台写入。"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from integration import bridge, owned_service, run_description, watchdog, writer_runner


class _Handler(BaseHTTPRequestHandler):
    payload = {}
    status = 200

    def do_GET(self):  # noqa: N802 - http.server 规定的方法名
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默，避免污染测试输出
        pass


class FakeManager:
    """本机 127.0.0.1 上的假管理服务；端口 0 表示随机空闲端口。"""

    def __init__(self, payload=None, port=0):
        handler = type("BoundHandler", (_Handler,), {"payload": payload or {}, "status": 200})
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def set_payload(self, payload, status=200):
        self.server.RequestHandlerClass.payload = payload
        self.server.RequestHandlerClass.status = status

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.servers = []
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self._close_servers)
        self.state_path = Path(self.temp.name) / "watchdog.json"
        self.patches = [
            patch.object(watchdog, "state_path", lambda: self.state_path),
            patch.object(bridge, "RUNTIME_ROOT", Path(self.temp.name) / "runtime"),
            patch.object(bridge, "stage_project", side_effect=AssertionError("守护进程不得入队发布")),
            patch.object(bridge, "run_publish", side_effect=AssertionError("守护进程不得发布")),
            patch.object(bridge, "sync_manifest", side_effect=AssertionError("守护进程不得同步清单")),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _close_servers(self):
        for server in self.servers:
            server.close()

    def serve(self, payload=None, port=0):
        manager = FakeManager(payload or {
            "status": "healthy", "service": "novel-helper-manager",
            "root": str(self.root.resolve()), "port": port,
            "pid": os.getpid(), "startup_id": "startup-new", "release_id": "rel-1",
            "started_at": "2026-11-16T00:00:00+00:00",
        }, port)
        self.servers.append(manager)
        return manager

    def write_description(self, **fields):
        return run_description.write(self.root, **fields)

    # ---------------------------------------------------------------- 端口来源

    def test_port_comes_from_run_description_or_default(self):
        self.assertEqual(watchdog.service_port(self.root), 8765)
        self.assertEqual(watchdog.service_port(self.root, {"port": 19001}), 19001)
        self.assertEqual(watchdog.service_port(self.root, {"port": 70000}), 8765)
        self.assertEqual(watchdog.service_port(self.root, {"port": "abc"}), 8765)
        self.assertIsNone(run_description.valid_port(0))
        self.assertIsNone(run_description.valid_port(65536))
        self.assertEqual(run_description.valid_port(65535), 65535)

    def test_health_requires_service_name(self):
        manager = self.serve({"service": "some-other-service", "root": str(self.root)})
        self.assertFalse(watchdog.manager_ready(manager.port))
        self.assertEqual(watchdog.manager_health(manager.port)["service"], "some-other-service")

    # ------------------------------------------------------------- 身份与冲突

    def test_foreign_service_is_reported_not_killed(self):
        manager = self.serve({"service": "windows-printer-spooler", "root": str(self.root)})
        with patch.object(watchdog, "start_manager", side_effect=AssertionError("不得启动")):
            with self.assertRaises(RuntimeError) as caught:
                watchdog.check(root=self.root, port=manager.port, mode="standalone")
        self.assertIn("不是码章鲸管理服务", str(caught.exception))
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["reason"], "foreign")

    def test_other_workspace_is_reported(self):
        manager = self.serve({"service": "novel-helper-manager", "root": str(Path(self.temp.name) / "other")})
        with self.assertRaises(RuntimeError) as caught:
            watchdog.check(root=self.root, port=manager.port, mode="standalone")
        self.assertIn("其他工作区", str(caught.exception))

    def test_description_port_conflict_stops_autostart(self):
        manager = self.serve({}, port=0)
        self.write_description(mode="standalone", owner="watchdog", port=manager.port + 1)
        with patch.object(watchdog, "start_manager", side_effect=AssertionError("冲突时不得启动")):
            with self.assertRaises(RuntimeError) as caught:
                watchdog.check(root=self.root, port=manager.port, mode="standalone")
        self.assertIn("运行描述记录端口", str(caught.exception))

    def test_stale_description_is_refreshed_after_restart(self):
        manager = self.serve()
        self.write_description(mode="standalone", owner="watchdog", port=manager.port,
                               startup_id="startup-old", root=str(self.root.resolve()))
        with patch.object(watchdog, "ensure_started", return_value={"started": False}), \
                patch.object(watchdog, "serial_ready", return_value=True):
            state = watchdog.check(root=self.root, port=manager.port, mode="standalone")
        self.assertEqual(state["status"], "healthy")
        description = run_description.read(self.root)
        self.assertEqual(description["startup_id"], "startup-new")
        self.assertEqual(description["mode"], "standalone")
        self.assertEqual(description["owner"], "watchdog")

    # ------------------------------------------------------------------ 自动拉起

    def test_dsh_managed_mode_never_starts_a_second_manager(self):
        with patch.object(watchdog, "start_manager", side_effect=AssertionError("托管模式不得自启")):
            state = watchdog.check(root=self.root, port=self.serve({}).port + 1000, mode="dsh_managed")
        self.assertEqual(state["status"], "waiting_for_host")
        self.assertEqual(state["reason"], "host_owned_manager")

    def test_standalone_mode_starts_manager_with_cli(self):
        seen = {}
        manager = {}

        def fake_start(root, port, python=""):
            seen.update(root=str(root), port=port, python=python)
            manager["server"] = self.serve(port=port)
            return {"pid": os.getpid(), "port": port, "python": python}

        free = self.serve({})
        port = free.port
        free.close()
        self.servers.remove(free)
        with patch.object(watchdog, "start_manager", side_effect=fake_start), \
                patch.object(watchdog, "ensure_started", return_value={"started": False}), \
                patch.object(watchdog, "serial_ready", return_value=True):
            state = watchdog.check(root=self.root, port=port, mode="standalone")
        self.assertEqual(seen["port"], port)
        self.assertEqual(seen["root"], str(self.root.resolve()))
        self.assertTrue(state["manager_started"])
        description = run_description.read(self.root)
        self.assertEqual(description["port"], port)
        self.assertEqual(description["service"], "novel-helper-manager")

    def test_occupied_port_without_health_keeps_process(self):
        # 端口有人在听，但 /api/health 返回 500：既不能杀进程，也不能改端口。
        manager = self.serve()
        manager.set_payload({"detail": "unhealthy"}, 500)
        with patch.object(watchdog, "start_manager", side_effect=AssertionError("占用时不得启动")):
            with self.assertRaises(RuntimeError) as caught:
                watchdog.check(root=self.root, port=manager.port, mode="standalone")
        self.assertIn("保留现有进程", str(caught.exception))

    def test_two_watchdogs_serialize_on_the_watchdog_lock(self):
        manager = self.serve()
        with writer_runner.file_lock(bridge.RUNTIME_ROOT / "watchdog.lock"):
            with patch.object(watchdog, "ensure_started", return_value={"started": False}), \
                    patch.object(watchdog, "serial_ready", return_value=True):
                with self.assertRaises(RuntimeError) as caught:
                    watchdog.check(root=self.root, port=manager.port, mode="standalone")
        self.assertIn("已有任务正在运行", str(caught.exception))

    # ------------------------------------------------ owned_service 只杀自己家的空闲协调器

    def test_owned_service_refuses_unsafe_pids(self):
        state_file = Path(self.temp.name) / "serial.json"
        cases = [
            {"pid": os.getpid(), "started_at": "bogus", "checked_at": "bogus"},
            {"pid": 0, "started_at": "2026-11-16T00:00:00+00:00", "checked_at": "2026-11-16T00:00:00+00:00"},
            {"pid": os.getpid(), "active_job": "tide", "started_at": "2026-11-16T00:00:00+00:00",
             "checked_at": "2026-11-16T00:00:00+00:00"},
            {"pid": os.getpid(), "child_pid": 1234, "started_at": "2026-11-16T00:00:00+00:00",
             "checked_at": "2026-11-16T00:00:00+00:00"},
        ]
        for value in cases:
            state_file.write_text(json.dumps(value), encoding="utf-8")
            with patch.object(owned_service, "subprocess", create=True), \
                    patch("subprocess.run", side_effect=AssertionError("不得执行停止命令")):
                self.assertFalse(owned_service.restart_stale_coordinator(
                    self.root, state_file))

    def test_fresh_heartbeat_is_not_restarted(self):
        state_file = Path(self.temp.name) / "serial.json"
        state_file.write_text(json.dumps({"pid": os.getpid(), "started_at": bridge.now_iso(),
                                          "checked_at": bridge.now_iso()}), encoding="utf-8")
        with patch("subprocess.run", side_effect=AssertionError("新鲜心跳不得重启")):
            self.assertFalse(owned_service.restart_stale_coordinator(self.root, state_file))

    # ------------------------------------------------------------- 只读身份核对

    def test_check_mode_is_read_only(self):
        manager = self.serve()
        before = self.state_path.exists()
        code = watchdog.main(["--root", str(self.root), "--port", str(manager.port), "--check"])
        self.assertEqual(code, 0)
        self.assertEqual(self.state_path.exists(), before)
        self.assertEqual(run_description.read(self.root), {})

    def test_check_mode_reports_mismatch_with_nonzero_exit(self):
        manager = self.serve({"service": "novel-helper-manager",
                              "root": str(Path(self.temp.name) / "other")})
        self.assertEqual(watchdog.main(["--root", str(self.root), "--port", str(manager.port), "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
