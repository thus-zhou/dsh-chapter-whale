import io
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from integration import bridge, ofm_runtime, scheduler, writer_runner
from manager import app as manager_app

HEADERS = {"X-Novel-Helper": "1"}


class V075ManagerApiTests(unittest.TestCase):
    def test_operation_progress_parsing_via_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            ops_dir = data_dir / "operations"
            ops_dir.mkdir(parents=True)
            ai_path = root / "ai.json"
            bridge.write_json_atomic(ai_path, {"base_url": "", "model": "", "api_key": ""})
            bridge.write_json_atomic(ops_dir / "op-prog-1.json", {"status": "success", "count": 1})

            store = manager_app.Store(data_dir / "db.sqlite")
            ops = manager_app.Operations(store)
            op_payload = {
                "id": "op-prog-1",
                "kind": "generate",
                "identity": "p1",
                "project_id": "p1",
                "project_title": "测试之书",
                "status": "queued",
                "created_at": bridge.now_iso(),
                "log_tail": "",
            }
            store.save_operation(op_payload)

            fake_proc = mock.Mock()
            fake_proc.pid = 4242
            fake_proc.poll.return_value = 0
            fake_proc.stdin = None
            fake_proc.stdout = io.StringIO(
                'NOVEL_HELPER_PROGRESS:{"stage":"B","label":"撰写第1章初稿","percent":42,"chapter":1}\n'
                "普通日志行\n"
            )
            fake_proc.wait.return_value = 0

            with (
                mock.patch.object(manager_app, "DATA", data_dir),
                mock.patch.object(manager_app, "AI_PATH", ai_path),
                mock.patch("subprocess.Popen", return_value=fake_proc),
            ):
                seen_progress = []
                original_save = store.save_operation
                def capture(payload):
                    seen_progress.append(dict(payload.get("progress") or {}))
                    return original_save(payload)
                store.save_operation = capture
                ops._execute("op-prog-1", ["generate", "p1"])

            finished = store.operation("op-prog-1")
            self.assertEqual(finished["status"], "success")
            self.assertEqual(finished["project_title"], "测试之书")
            # P2-27: the 42% progress line must be observed, not only the final 100.
            self.assertTrue(any(p.get("percent") == 42 and p.get("stage") == "B" for p in seen_progress))
            self.assertEqual(finished["progress"]["percent"], 100)
            self.assertEqual(finished["progress"]["chapter"], 1)

    def test_job_deduplication_book_scoped_name_and_delete_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book1"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(json.dumps({"title": "星海归途"}), encoding="utf-8")

            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", root / "ai.json"),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                client.app.state.store.register(proj)

                r1 = client.post(
                    "/api/jobs",
                    headers=HEADERS,
                    json={
                        "project": str(proj),
                        "book": "星海归途",
                        "publication_mode": "draft_only",
                        "daily_time": "09:00",
                        "chapters_per_run": 1,
                        "word_count": 3500,
                        "max_revisions": 1,
                        "enabled": True,
                    },
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                first = r1.json()
                self.assertEqual(first["name"], "《星海归途》 · 日更")

                # Re-submitting same (project, publication_mode) deduplicates to existing job.
                r2 = client.post(
                    "/api/jobs",
                    headers=HEADERS,
                    json={
                        "project": str(proj),
                        "book": "星海归途",
                        "publication_mode": "draft_only",
                        "daily_time": "10:30",
                        "chapters_per_run": 2,
                        "word_count": 4000,
                        "max_revisions": 1,
                        "enabled": True,
                    },
                )
                self.assertEqual(r2.status_code, 200, r2.text)
                second = r2.json()
                self.assertEqual(second["id"], first["id"])
                self.assertEqual(second["daily_time"], "10:30")
                jobs_list = client.get("/api/jobs").json()
                if isinstance(jobs_list, dict):
                    jobs_list = jobs_list.get("jobs", [])
                self.assertEqual(len(jobs_list), 1)

                r_del = client.delete(f"/api/jobs/{first['id']}", headers=HEADERS)
                self.assertEqual(r_del.status_code, 200, r_del.text)
                self.assertTrue(r_del.json()["deleted"])
                jobs_after = client.get("/api/jobs").json()
                if isinstance(jobs_after, dict):
                    jobs_after = jobs_after.get("jobs", [])
                self.assertEqual(len(jobs_after), 0)

    def test_job_recreate_only_merges_submitted_fields(self):
        """P0-2: a second POST must not reset serial/quota/times with model defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book-quota"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(
                json.dumps({"title": "配额之书"}), encoding="utf-8")
            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", root / "ai.json"),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                client.app.state.store.register(proj)
                created = client.post("/api/jobs", headers=HEADERS, json={
                    "project": str(proj), "book": "配额之书", "publication_mode": "draft_only",
                    "daily_time": "08:00", "daily_times": ["08:00", "20:00"],
                    "delivery_mode": "serial",
                    "quota_phases": [{"start_date": "2026-01-01", "end_date": "2026-12-31",
                                      "chapters_per_run": 3, "word_count": 4200}],
                    "chapters_per_run": 3, "word_count": 4200, "max_revisions": 2,
                    "enabled": True,
                })
                self.assertEqual(created.status_code, 200, created.text)
                job_id = created.json()["id"]
                # A plain "new task" form only sends the basics; saved plan must survive.
                again = client.post("/api/jobs", headers=HEADERS, json={
                    "project": str(proj), "book": "配额之书", "publication_mode": "draft_only",
                    "chapters_per_run": 2, "word_count": 4000,
                    "max_revisions": 1,
                })
                self.assertEqual(again.status_code, 200, again.text)
                jobs = {item["id"]: item for item in client.get("/api/jobs").json()}
                saved = jobs[job_id]
                self.assertEqual(saved["delivery_mode"], "serial")
                self.assertEqual(saved["daily_times"], ["08:00", "20:00"])
                self.assertEqual(saved["quota_phases"][0]["chapters_per_run"], 3)
                self.assertEqual(saved["word_count"], 4000)
                self.assertEqual(saved["daily_time"], "08:00", "省略的时段必须保留")
                self.assertTrue(saved["enabled"], "省略 enabled 不得把任务停用")

    def test_explicit_job_id_conflict_is_rejected(self):
        """P2-10: explicit ids cannot bypass (project, publication_mode) dedup."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book-explicit"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(
                json.dumps({"title": "显式之书"}), encoding="utf-8")
            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", root / "ai.json"),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                client.app.state.store.register(proj)
                first = client.post("/api/jobs", headers=HEADERS, json={
                    "project": str(proj), "book": "显式之书", "publication_mode": "draft_only",
                    "daily_time": "08:00", "enabled": True,
                })
                self.assertEqual(first.status_code, 200, first.text)
                first_id = first.json()["id"]
                conflict = client.post("/api/jobs", headers=HEADERS, json={
                    "job_id": "another-id", "project": str(proj), "book": "显式之书",
                    "publication_mode": "draft_only", "daily_time": "08:00", "enabled": True,
                })
                self.assertEqual(conflict.status_code, 409, conflict.text)
                reused = client.post("/api/jobs", headers=HEADERS, json={
                    "job_id": first_id, "project": str(proj), "book": "显式之书",
                    "publication_mode": "draft_only", "daily_time": "10:00", "enabled": True,
                })
                self.assertEqual(reused.status_code, 200, reused.text)
                self.assertEqual(reused.json()["id"], first_id)
                self.assertEqual(len(client.get("/api/jobs").json()), 1)

    def test_concurrent_job_create_yields_one_record(self):
        """P1-6: check-then-create is serialized; concurrent POSTs cannot duplicate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book-race"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(
                json.dumps({"title": "并发之书"}), encoding="utf-8")
            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", root / "ai.json"),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                client.app.state.store.register(proj)
                payload = {"project": str(proj), "book": "并发之书",
                           "publication_mode": "draft_only", "daily_time": "08:00",
                           "enabled": True}
                barrier = threading.Barrier(4)

                def create():
                    local = TestClient(application)
                    barrier.wait()
                    response = local.post("/api/jobs", headers=HEADERS, json=payload)
                    return response.status_code

                with ThreadPoolExecutor(max_workers=4) as pool:
                    statuses = list(pool.map(lambda _: create(), range(4)))
                self.assertEqual(statuses, [200, 200, 200, 200])
                self.assertEqual(len(client.get("/api/jobs").json()), 1)

    def test_invalid_progress_values_do_not_fail_operation(self):
        """P1-9: non-numeric/regressing percent is ignored; progress stays monotonic."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            ops_dir = data_dir / "operations"
            ops_dir.mkdir(parents=True)
            ai_path = root / "ai.json"
            bridge.write_json_atomic(ai_path, {"base_url": "", "model": "", "api_key": ""})
            bridge.write_json_atomic(ops_dir / "op-progress.json", {"status": "success"})
            store = manager_app.Store(data_dir / "db.sqlite")
            ops = manager_app.Operations(store)
            store.save_operation({"id": "op-progress", "kind": "generate", "identity": "p1",
                                  "project_id": "p1", "status": "queued",
                                  "created_at": bridge.now_iso(), "log_tail": ""})
            fake_proc = mock.Mock()
            fake_proc.pid = 4343
            fake_proc.poll.return_value = 0
            fake_proc.stdin = None
            fake_proc.stdout = io.StringIO(
                'NOVEL_HELPER_PROGRESS:{"stage":"B","percent":80}\n'
                'NOVEL_HELPER_PROGRESS:{"stage":"B","percent":20}\n'
                'NOVEL_HELPER_PROGRESS:{"stage":"D","percent":[50],"current":[1]}\n'
                'NOVEL_HELPER_PROGRESS:{"stage":"D","percent":15,"current":2,"total":3}\n'
            )
            fake_proc.wait.return_value = 0
            seen = []
            original = store.save_operation

            def capture(payload):
                value = (payload.get("progress") or {}).get("percent")
                if type(value) is int:
                    seen.append(value)
                return original(payload)

            with (
                mock.patch.object(manager_app, "DATA", data_dir),
                mock.patch.object(manager_app, "AI_PATH", ai_path),
                mock.patch("subprocess.Popen", return_value=fake_proc),
                mock.patch.object(store, "save_operation", side_effect=capture),
            ):
                ops._execute("op-progress", ["generate", "p1"])
            finished = store.operation("op-progress")
            self.assertEqual(finished["status"], "success")
            self.assertEqual(finished["progress"]["percent"], 100)
            self.assertTrue(all(a <= b for a, b in zip(seen, seen[1:])), seen)
            self.assertIn(80, seen)

    def test_approve_review_rejects_non_handoff_chapter(self):
        """P1-22: approve-review cannot grant publishing rights to ordinary chapters."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book-approve"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(
                json.dumps({"title": "复核之书"}), encoding="utf-8")
            body = "# 第1章 旧章\n\n这一段是普通正文，没有经过两次自动审查。"
            chapter_file = proj / "正文" / "第1章-旧章.md"
            chapter_file.write_text(body, encoding="utf-8")
            (proj / ".webnovel" / "writer_receipts.json").write_text(json.dumps({
                "1": {"destination": str(chapter_file), "sha256": "a" * 64,
                      "review": {"success": True, "review_decision": "pass",
                                 "needs_revision": False}}
            }), encoding="utf-8")
            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", root / "ai.json"),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                pid = client.app.state.store.register(proj)
                response = client.post(
                    f"/api/projects/{pid}/chapters/1/approve-review",
                    headers=HEADERS, json={"note": "想直接通过"})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn("待人工复核", response.json()["message"])

    def test_project_mutex_includes_waiting_operations(self):
        """P1-7: a deferred (waiting) operation still blocks a second writer for the project."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = manager_app.Store(root / "db.sqlite")
            ops = manager_app.Operations(store)
            with mock.patch.object(manager_app, "DATA", root):
                store.save_operation({"id": "wait-1", "kind": "generate", "identity": "project:p1",
                                      "project_id": "p1", "status": "waiting",
                                      "created_at": bridge.now_iso()})
                with self.assertRaises(Exception) as caught:
                    ops.start("generate", ["batch", "--project", str(root / "book")],
                              "project:p1", {"project_id": "p1"})
            self.assertEqual(getattr(caught.exception, "status_code", None), 409)

    def test_project_path_key_is_stable_for_unregistered_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = manager_app.project_path_key(Path(tmp) / "a")
            second = manager_app.project_path_key(str((Path(tmp) / "a")) + "/")
            self.assertTrue(first.startswith("path:"))
            self.assertEqual(first, second)
            self.assertNotEqual(first, manager_app.project_path_key(Path(tmp) / "b"))

    def test_approve_review_and_abandon_batch_endpoints(self):
        batch_hex = "b" * 32
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book2"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(json.dumps({"title": "测试书2"}), encoding="utf-8")
            body = "# 第1章 序幕\n\n测试正文内容，用于章节人工复核接口验证。"
            ch_file = proj / "正文" / "第1章-序幕.md"
            ch_file.write_text(body, encoding="utf-8")
            digest = writer_runner.body_digest(body)
            review_handoff = {
                "chapter": 1,
                "body_sha256": digest,
                "success": True,
                "review_decision": "needs_human_review",
                "human_review_required": True,
                "auto_review_count": 2,
            }
            (proj / ".webnovel" / "writer_receipts.json").write_text(
                json.dumps({"1": {"review": review_handoff, "destination": str(ch_file)}}, ensure_ascii=False),
                encoding="utf-8",
            )
            batches_dir = proj / ".webnovel" / "batches"
            batches_dir.mkdir(parents=True)
            (batches_dir / f"{batch_hex}.json").write_text(
                json.dumps({"id": batch_hex, "status": "running", "targets": [1], "completed": []}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", root / "ai.json"),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                pid = client.app.state.store.register(proj)

                r_app = client.post(
                    f"/api/projects/{pid}/chapters/1/approve-review",
                    headers=HEADERS,
                    json={"note": "接口复核通过"},
                )
                self.assertEqual(r_app.status_code, 200, r_app.text)
                self.assertEqual(r_app.json()["status"], "approved")
                self.assertEqual(r_app.json()["receipt"]["review"]["review_decision"], "human_approved")

                ch_list = client.get(f"/api/projects/{pid}/chapters").json()["chapters"]
                self.assertTrue(ch_list[0]["reviewed"])
                self.assertEqual(ch_list[0]["review_status"], "human_approved")
                self.assertFalse(ch_list[0]["human_review_required"])

                r_ab = client.post(f"/api/projects/{pid}/batches/{batch_hex}/abandon", headers=HEADERS, json={})
                self.assertEqual(r_ab.status_code, 200, r_ab.text)
                self.assertEqual(r_ab.json()["status"], "abandoned")

    def test_free_pool_endpoint_accepts_project_id_and_set_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book3"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(json.dumps({"title": "免费池测试"}), encoding="utf-8")
            cfg_path = root / "ai.json"
            bridge.write_json_atomic(cfg_path, {"providers": {}, "roles": {}, "default_binding": {}})
            ofm_home = root / "ofm_home"
            ofm_home.mkdir(parents=True)
            bridge.write_json_atomic(ofm_home / "settings.json", {"forwardKey": "ofm-secret-key"})

            with (
                mock.patch.object(manager_app, "DATA", root),
                mock.patch.object(manager_app, "AI_PATH", cfg_path),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.object(ofm_runtime, "HOME", ofm_home),
                mock.patch.object(ofm_runtime, "health", return_value={"running": True, "url": "http://127.0.0.1:25600"}),
                mock.patch.object(ofm_runtime, "request", return_value={"catalog": [{"id": "opencode/qwen-free", "routable": True}]}),
                mock.patch("integration.free_pool.clear_recovery") as clear_rec,
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                pid = client.app.state.store.register(proj)

                r_pool = client.put(
                    "/api/free-model/pool",
                    headers=HEADERS,
                    json={
                        "members": [
                            {"model_id": "opencode/qwen-free", "roles": ["A", "B", "C", "D", "E"], "quota_confirmed": True}
                        ],
                        "project_id": pid,
                        "authorize_project": True,
                        "set_default": True,
                    },
                )
                self.assertEqual(r_pool.status_code, 200, r_pool.text)
                clear_rec.assert_called_once()
                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["default_binding"]["provider_id"], "free-pool")
                self.assertIn(str(proj.resolve()),
                              [str(Path(p).resolve()) for p in saved["providers"]["free-pool"]["allowed_projects"]])


if __name__ == "__main__":
    unittest.main()
