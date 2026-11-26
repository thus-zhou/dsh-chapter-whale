"""v0.7.5 security / runtime regression tests.

Covers the audit items that protect the free-model path and the privacy
boundary:

- P1-10: port self-healing reaches the *live* client and is persisted.
- P1-11: Node runtime precedence and the ``NODE_USE_ENV_PROXY`` version floor.
- P1-12: imports never fall back to “all registered books”.
- P1-13: saving a pool only changes the global default on an explicit request.
- P1-23: ``owned_ports`` only trusts DSH host processes, never any listener.
- P2-18: the standalone service calls ``runtime.refreshCatalog``.
- P2-26/P2-28: tokenSaver fails closed, honours ``DSH_HOME`` and covers the
  standalone/free-pool branches.
- P2-27: anonymous kilo-auto/openrouter lanes do not require an account login.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from integration import (
    bridge,
    costs,
    free_channels,
    free_pool,
    model_roles,
    ofm_runtime,
    providers,
    scheduler,
)
from integration.provider_client import ProviderClient
from manager import app as manager_app

HEADERS = {"X-Novel-Helper": "1"}
OLD_URL = "http://127.0.0.1:24999/v1"
LIVE_URL = "http://127.0.0.1:25600/v1"


class FakeChat:
    """Records the URL actually used for each request."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.calls = []
        self.last_response_meta = {}
        self.timeout = 30

    async def chat(self, messages, **kwargs):
        self.calls.append(self.base_url)
        return "ok"

    async def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(self.base_url)
        return "ok"

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(self.base_url)
        yield "ok"


def _standalone_config(project, fallbacks=None):
    config = {
        "provider_schema": 1,
        "multi_model": False,
        "default_binding": {"provider_id": "ofm-standalone", "model_id": "free/model", "fallbacks": fallbacks or []},
        "providers": {
            "ofm-standalone": {
                "id": "ofm-standalone", "name": "OFM", "protocol": "ofm_standalone",
                "base_url": OLD_URL, "api_key": "fictional", "revision": 1,
                "allowed_projects": [str(Path(project).resolve())],
            }
        },
    }
    return config


class PortSelfHealingTests(unittest.TestCase):
    """P1-10: healing must reach the object that sends the request."""

    def test_provider_client_heals_live_client_and_persists_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "book"
            project.mkdir()
            cfg_path = root / "ai.json"
            config = _standalone_config(project)
            cfg_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            primary = FakeChat(OLD_URL)
            client = ProviderClient("B", config, primary, lambda binding: FakeChat(OLD_URL))
            with (
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.object(model_roles, "config_path", return_value=cfg_path),
                mock.patch.object(ofm_runtime, "ensure_started", return_value={"url": "http://127.0.0.1:25600"}),
                mock.patch.object(ofm_runtime, "HOME", root / "ofm-home"),
                costs.scope(project=str(project)),
            ):
                self.assertEqual(asyncio.run(client.chat([])), "ok")
            self.assertEqual(primary.calls, [LIVE_URL], "实际请求必须打到自愈后的端口")
            self.assertEqual(client._config["providers"]["ofm-standalone"]["base_url"], LIVE_URL)
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["providers"]["ofm-standalone"]["base_url"], LIVE_URL)
            backup = cfg_path.with_name(cfg_path.name + ".bak")
            self.assertTrue(backup.is_file(), "自愈写回前必须保留原配置备份")
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["providers"]["ofm-standalone"]["base_url"], OLD_URL)

    def test_factory_resolves_from_live_config_after_healing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "book"
            project.mkdir()
            config = _standalone_config(project)
            config["resource_policy"] = {"fallback_cost_limit_cny": None}
            config["default_binding"]["fallbacks"] = [{"provider_id": "ofm-standalone", "model_id": "free/model"}]
            config["providers"]["ofm-standalone"]["revision"] = 1

            class FailingChat(FakeChat):
                async def chat(self, messages, **kwargs):
                    self.calls.append(self.base_url)
                    raise TimeoutError("fictional timeout")

            primary = FailingChat(OLD_URL)
            created = []

            def factory(binding):
                # Same closure shape as model_roles.service: resolve() reads the
                # config object that ProviderClient now shares with us.
                resolved = providers.resolve(config, binding)
                item = FakeChat(resolved["base_url"])
                created.append(item)
                return item

            client = ProviderClient("B", config, primary, factory)
            with (
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.object(model_roles, "config_path", return_value=root / "missing.json"),
                mock.patch.object(ofm_runtime, "ensure_started", return_value={"url": "http://127.0.0.1:25600"}),
                mock.patch.object(ofm_runtime, "HOME", root / "ofm-home"),
                costs.scope(project=str(project)),
            ):
                self.assertEqual(asyncio.run(client.chat([])), "ok")
            self.assertTrue(created, "主模型失败后应调用 factory")
            self.assertEqual(created[0].base_url, LIVE_URL, "factory 必须从已自愈的 live config 解析")
            self.assertEqual(created[0].calls, [LIVE_URL])


    def test_free_pool_factory_client_receives_live_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "book"
            project.mkdir()
            cfg_path = root / "ai.json"
            cfg_path.write_text(json.dumps({"providers": {}}), encoding="utf-8")
            ofm_home = root / "ofm-home"
            ofm_home.mkdir()
            (ofm_home / "settings.json").write_text(json.dumps({"tokenSaver": {"enabled": False}}), encoding="utf-8")
            config = {
                "provider_schema": 1, "multi_model": True,
                "roles": {"B": {"provider_id": "free-pool", "model_id": "auto", "fallbacks": []}},
                "default_binding": {"provider_id": "free-pool", "model_id": "auto"},
                "providers": {
                    "free-pool": {"id": "free-pool", "name": "池", "protocol": "free_pool", "base_url": OLD_URL,
                        "api_key": "fictional", "allowed_projects": [str(project.resolve())],
                        "pool_members": [{"model_id": "opencode/free", "roles": ["B"]}], "revision": 1},
                    "ofm-standalone": {"id": "ofm-standalone", "name": "OFM", "protocol": "ofm_standalone",
                        "base_url": OLD_URL, "api_key": "fictional", "allowed_projects": [str(project.resolve())], "revision": 1},
                },
            }
            created = []

            def factory(binding):
                item = FakeChat(OLD_URL)
                created.append(item)
                return item

            client = free_pool.FreePoolClient("B", config, factory)
            with (
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.object(ofm_runtime, "ensure_started", return_value={"url": "http://127.0.0.1:25600"}),
                mock.patch.object(ofm_runtime, "HOME", ofm_home),
                mock.patch.object(model_roles, "config_path", return_value=cfg_path),
                costs.scope(project=str(project)),
            ):
                self.assertEqual(asyncio.run(client.chat([])), "ok")
            self.assertEqual(client.base_url, LIVE_URL)
            self.assertEqual(created[0].calls, [LIVE_URL], "free-pool 交给 factory 的客户端也必须改到新端口")


class NodeRuntimeTests(unittest.TestCase):
    """P1-11: ``NOVEL_HELPER_NODE`` wins and old Node is not silently accepted."""

    def test_version_floor_for_env_proxy(self):
        supported = ["v22.21.0", "v22.22.1", "v24.5.0", "v24.11.0", "v25.0.0", "v26.12.1"]
        rejected = ["v20.19.0", "v22.20.0", "v22.0.0", "v23.11.0", "v24.4.0", "", None, "unknown"]
        for version in supported:
            self.assertTrue(ofm_runtime.node_version_supported(version), version)
        for version in rejected:
            self.assertFalse(ofm_runtime.node_version_supported(version), version)

    def test_env_runtime_outranks_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_node = root / "env-node"
            path_node = root / "path-node"
            env_node.write_text("stub", encoding="utf-8")
            path_node.write_text("stub", encoding="utf-8")
            with (
                mock.patch("shutil.which", return_value=str(path_node)),
                mock.patch.dict(os.environ, {"NOVEL_HELPER_NODE": str(env_node)}, clear=False),
            ):
                resolved, extra = ofm_runtime._resolve_node_runtime()
            self.assertEqual(Path(resolved), env_node.resolve())
            self.assertEqual(extra, {})

    def test_old_node_rejected_only_when_a_proxy_is_configured(self):
        with mock.patch.object(ofm_runtime, "_node_version", return_value="v20.19.0"):
            with self.assertRaises(ValueError) as caught:
                ofm_runtime._check_node_runtime("/usr/bin/node", {}, proxy_configured=True)
            self.assertIn("22.21", str(caught.exception))
            ok, note = ofm_runtime._check_node_runtime("/usr/bin/node", {}, proxy_configured=False)
            self.assertFalse(ok)
            self.assertIn("22.21", note)


class ImportPrivacyTests(unittest.TestCase):
    """P1-12: missing project scope must never mean “every book”."""

    def _dsh_settings(self, root, include_token_saver=True):
        target = root / "dsh" / "our-free-model" / "settings.json"
        target.parent.mkdir(parents=True)
        doc = {"forward": {"enabled": True, "port": 19001, "key": "fictional"}, "forwardKey": "fictional"}
        if include_token_saver:
            doc["tokenSaver"] = {"enabled": False}
        target.write_text(json.dumps(doc), encoding="utf-8")
        return target

    def test_import_dsh_empty_list_does_not_fall_back_to_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self._dsh_settings(root)
            with (
                mock.patch.object(providers, "verify_dsh_gateway"),
                mock.patch.object(scheduler, "load_scheduler", side_effect=AssertionError("不允许回退到任务列表")),
            ):
                updated, identity = providers.import_dsh({}, settings_path=settings, projects=[])
                updated_none, identity_none = providers.import_dsh(updated, settings_path=settings, projects=None)
            self.assertEqual(updated["providers"][identity]["allowed_projects"], [])
            self.assertEqual(updated_none["providers"][identity_none]["allowed_projects"], [])

    def test_import_dsh_token_saver_unknown_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self._dsh_settings(root, include_token_saver=False)
            with mock.patch.object(providers, "verify_dsh_gateway"):
                with self.assertRaises(ValueError) as caught:
                    providers.import_dsh({}, settings_path=settings, projects=[str(root)])
            self.assertIn("状态未知", str(caught.exception))

    def test_import_channel_rejects_missing_project_before_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(free_channels, "scan") as scan:
                with self.assertRaises(ValueError):
                    free_channels.import_channel({}, {"channel_id": "trae", "authorize_project": True})
                scan.assert_not_called()

    def test_import_channel_intersects_registered_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registered = (root / "book").resolve()
            other = (root / "other").resolve()
            registered.mkdir()
            other.mkdir()
            catalog = {"endpoint": "http://127.0.0.1:19001/v1",
                "models": [{"id": "trae/model-free", "channel": "trae"}], "checked_at": "2026-01-01T00:00:00+08:00"}
            with (
                mock.patch.object(free_channels, "scan", return_value=(catalog, "fictional-key")),
                mock.patch.object(free_channels, "cache_path", return_value=root / "cache.json"),
            ):
                with self.assertRaises(ValueError):
                    free_channels.import_channel({}, {"channel_id": "trae", "authorize_project": True,
                        "project": str(other)}, known_projects={str(registered)})
                updated, identity, _ = free_channels.import_channel({}, {"channel_id": "trae", "authorize_project": True,
                    "projects": [str(registered), str(other)]}, known_projects={str(registered)})
            self.assertEqual(updated["providers"][identity]["allowed_projects"], [str(registered)])

    def test_http_imports_require_explicit_registered_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(json.dumps({"title": "隐私测试"}), encoding="utf-8")
            cfg_path = root / "ai.json"
            bridge.write_json_atomic(cfg_path, {"provider_schema": 1, "providers": {}, "roles": {}, "default_binding": {}})
            settings = self._dsh_settings(root)
            catalog = {"endpoint": "http://127.0.0.1:19001/v1",
                "models": [{"id": "trae/model-free", "channel": "trae"}], "checked_at": "2026-01-01T00:00:00+08:00"}
            with (
                mock.patch.object(manager_app, "DATA", root / "data"),
                mock.patch.object(manager_app, "AI_PATH", cfg_path),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.dict(os.environ, {"DSH_HOME": str(root / "dsh")}, clear=False),
                mock.patch.object(providers, "verify_dsh_gateway"),
                mock.patch.object(free_channels, "scan", return_value=(catalog, "fictional-key")),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                client.app.state.store.register(proj)

                # DSH import without an explicit book gets an empty allow-list.
                response = client.post("/api/ai/providers/dsh/import", headers=HEADERS, json={})
                self.assertEqual(response.status_code, 200, response.text)
                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                dsh_provider = next(v for v in saved["providers"].values() if v["protocol"] == "dsh_local")
                self.assertEqual(dsh_provider["allowed_projects"], [])

                # Free-channel import without a book is rejected outright.
                response = client.post("/api/ai/free-channels/import", headers=HEADERS,
                    json={"channel_id": "trae", "authorize_project": True})
                self.assertEqual(response.status_code, 400, response.text)

                # With an explicit registered book it is authorized for that book only.
                response = client.post("/api/ai/free-channels/import", headers=HEADERS,
                    json={"channel_id": "trae", "authorize_project": True, "project": str(proj)})
                self.assertEqual(response.status_code, 200, response.text)
                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                channel_provider = next(v for v in saved["providers"].values() if v.get("protocol") == "dsh_channel")
                self.assertEqual(channel_provider["allowed_projects"], [str(proj.resolve())])

                # A dsh import naming a registered book records exactly that book.
                response = client.post("/api/ai/providers/dsh/import", headers=HEADERS, json={"project": str(proj)})
                self.assertEqual(response.status_code, 200, response.text)
                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                dsh_provider = next(v for v in saved["providers"].values() if v["protocol"] == "dsh_local")
                self.assertEqual(dsh_provider["allowed_projects"], [str(proj.resolve())])

                # ``project_id`` is accepted as the same explicit scope.
                response = client.post("/api/ai/providers/dsh/import", headers=HEADERS, json={"project_id": client.app.state.store.projects()[0]["id"]})
                self.assertEqual(response.status_code, 200, response.text)
                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                dsh_provider = next(v for v in saved["providers"].values() if v["protocol"] == "dsh_local")
                self.assertEqual(dsh_provider["allowed_projects"], [str(proj.resolve())])

                # An unregistered path is refused instead of being stored as scope.
                response = client.post("/api/ai/providers/dsh/import", headers=HEADERS,
                    json={"project": str(root / "not-registered")})
                self.assertEqual(response.status_code, 400, response.text)


class OwnedPortTests(unittest.TestCase):
    """P1-23: only DSH host processes may receive the gateway key."""

    SAMPLE = "\n".join([
        "p101", "cnode", "n127.0.0.1:25600", "n[::1]:25600",
        "p102", "cpython3", "n127.0.0.1:24999",
        "p103", "cElectron", "n127.0.0.1:3000", "n[::1]:3001",
        "p104", "cnode", "n0.0.0.0:8000",
        "p105", "cjava", "n192.168.1.5:9000",
        "p106", "cDeepSeek ", "n127.0.0.1:3100",
    ])

    @unittest.skipIf(os.name == "nt", "Unix lsof branch")
    def test_lsof_owner_filter(self):
        completed = mock.Mock(returncode=0, stdout=self.SAMPLE)
        with mock.patch.object(free_channels.subprocess, "run", return_value=completed) as run:
            ports = free_channels.owned_ports()
        self.assertEqual(ports, [3000, 3001, 3100, 25600])
        args = run.call_args.args[0]
        self.assertIn("-F", args)
        self.assertIn("pcn", args)
        self.assertIn("-u", args, "必须限制为当前用户进程")

    def test_untrusted_listener_is_not_returned(self):
        rows = free_channels._parse_lsof_listeners("\n".join([
            "p201", "cpython3", "n127.0.0.1:25600",
            "p202", "cncat", "n127.0.0.1:25601",
        ]))
        self.assertEqual([row["command"] for row in rows], ["python3", "ncat"])
        self.assertTrue(all(not free_channels._host_process(row["command"]) for row in rows))

    def test_windows_script_uses_exact_install_paths_only(self):
        script = free_channels.windows_owned_ports_script([r"C:\Program Files\DeepSeek Harness\DeepSeek Harness.exe"])
        self.assertNotIn("-like", script)
        self.assertIn("-in $taskHosts", script)
        self.assertIn("DeepSeek Harness.exe", script)


class TokenSaverTests(unittest.TestCase):
    """P2-26 / P2-28: fail closed, honour DSH_HOME, cover OFM and free-pool."""

    def test_only_explicit_false_passes(self):
        self.assertFalse(free_channels.token_saver_enabled({"tokenSaver": {"enabled": False}}))
        for settings in ({}, {"tokenSaver": {}}, {"tokenSaver": {"enabled": None}},
                         {"tokenSaver": {"enabled": "off"}}, {"tokenSaver": {"rtk": False}}, None, []):
            self.assertTrue(free_channels.token_saver_enabled(settings), settings)

    def test_dsh_home_and_snapshot_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dsh = root / "dsh"
            (dsh / "our-free-model").mkdir(parents=True)
            (dsh / "our-free-model" / "settings.json").write_text(json.dumps({"forward": {"enabled": True}}), encoding="utf-8")
            db_path = root / "costs.sqlite3"
            with (
                mock.patch.dict(os.environ, {"DSH_HOME": str(dsh)}, clear=False),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
            ):
                self.assertEqual(free_channels.home(), dsh)
                snapshot = free_channels.snapshot({"providers": {}}, db_path)
            self.assertTrue(snapshot["compression_enabled"], "缺 tokenSaver 字段必须按开启处理")

    def test_request_gate_blocks_unknown_dsh_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "book"
            project.mkdir()
            dsh = root / "dsh"
            (dsh / "our-free-model").mkdir(parents=True)
            (dsh / "our-free-model" / "settings.json").write_text(json.dumps({"forward": {"enabled": True}}), encoding="utf-8")
            config = {"provider_schema": 1, "multi_model": False,
                "default_binding": {"provider_id": "dsh", "model_id": "m", "fallbacks": []},
                "providers": {"dsh": {"id": "dsh", "name": "dsh", "protocol": "dsh_local",
                    "base_url": "http://127.0.0.1:19001/v1", "api_key": "fictional", "revision": 1,
                    "allowed_projects": [str(project.resolve())]}}}
            client = ProviderClient("B", config, FakeChat(OLD_URL), lambda binding: FakeChat(OLD_URL))
            with (
                mock.patch.dict(os.environ, {"DSH_HOME": str(dsh)}, clear=False),
                mock.patch.object(providers, "verify_dsh_gateway"),
                costs.scope(project=str(project)),
            ):
                with self.assertRaises(ValueError) as caught:
                    with client._scope(config["default_binding"], False, [], 100):
                        pass
            self.assertIn("状态未知", str(caught.exception))

    def test_standalone_and_free_pool_check_ofm_token_saver(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "book"
            project.mkdir()
            ofm_home = root / "ofm-home"
            ofm_home.mkdir()
            (ofm_home / "settings.json").write_text(json.dumps({"tokenSaver": {"enabled": True}}), encoding="utf-8")
            config = _standalone_config(project)
            client = ProviderClient("B", config, FakeChat(OLD_URL), lambda binding: FakeChat(OLD_URL))
            with (
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.object(ofm_runtime, "HOME", ofm_home),
                mock.patch.object(ofm_runtime, "ensure_started", return_value={"url": "http://127.0.0.1:25600"}),
                costs.scope(project=str(project)),
            ):
                with self.assertRaises(ValueError) as caught:
                    with client._scope(config["default_binding"], False, [], 100):
                        pass
            self.assertIn("提示词压缩", str(caught.exception))


class PoolDefaultTests(unittest.TestCase):
    """P1-13: only ``set_default is True`` may change the global binding."""

    def test_authorizing_a_book_does_not_change_global_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "book"
            (proj / ".webnovel").mkdir(parents=True)
            (proj / "正文").mkdir(parents=True)
            (proj / ".webnovel" / "state.json").write_text(json.dumps({"title": "默认绑定测试"}), encoding="utf-8")
            cfg_path = root / "ai.json"
            config = {"provider_schema": 1, "multi_model": False, "roles": {},
                "default_binding": {"provider_id": "paid", "model_id": "paid-model"},
                "providers": {"paid": {"id": "paid", "name": "付费", "protocol": "openai_compatible",
                    "base_url": "https://paid.invalid/v1", "api_key": "fictional", "enabled": True,
                    "revision": 1, "models": [], "pricing": {}}}}
            bridge.write_json_atomic(cfg_path, config)
            ofm_home = root / "ofm-home"
            ofm_home.mkdir()
            bridge.write_json_atomic(ofm_home / "settings.json", {"forwardKey": "ofm-key"})
            with (
                mock.patch.object(manager_app, "DATA", root / "data"),
                mock.patch.object(manager_app, "AI_PATH", cfg_path),
                mock.patch.object(scheduler, "SCHEDULER_PATH", root / "scheduler.json"),
                mock.patch.object(scheduler, "RUNS_ROOT", root / "runs"),
                mock.patch.object(bridge, "RUNTIME_ROOT", root / "runtime"),
                mock.patch.object(ofm_runtime, "HOME", ofm_home),
                mock.patch.object(ofm_runtime, "health", return_value={"running": True, "url": "http://127.0.0.1:25600"}),
                mock.patch.object(ofm_runtime, "request", return_value={"catalog": [{"id": "opencode/qwen-free", "routable": True}]}),
                mock.patch("integration.free_pool.clear_recovery"),
            ):
                application = manager_app.create_app(root / "db.sqlite", start_dispatcher=False)
                client = TestClient(application)
                pid = client.app.state.store.register(proj)
                response = client.put("/api/free-model/pool", headers=HEADERS, json={
                    "members": [{"model_id": "opencode/qwen-free", "roles": ["A", "B", "C", "D", "E"], "quota_confirmed": True}],
                    "project_id": pid, "authorize_project": True, "set_default": False,
                })
                self.assertEqual(response.status_code, 200, response.text)
                saved = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["default_binding"]["provider_id"], "paid")
                self.assertIn(str(proj), saved["providers"]["free-pool"]["allowed_projects"])


class AnonymousLaneTests(unittest.TestCase):
    """P2-27: anonymous lanes must not be locked behind “requires login”."""

    def test_kilo_auto_and_openrouter_are_exempt(self):
        for model in ("kilo-auto/free", "kilo-auto/frontier", "openrouter/free", "opencode/grok-free", "kilo/x", "combo:anything"):
            self.assertFalse(free_pool._requires_account_login(model), model)
        for model in ("zcode/glm-free", "qoder/x", "trae/some-model"):
            self.assertTrue(free_pool._requires_account_login(model), model)


class ProviderModelsTests(unittest.TestCase):
    """Custom providers may persist the models field the client sends."""

    def test_custom_provider_models_are_saved(self):
        config = {"provider_schema": 1, "providers": {}, "default_binding": {}}
        doc, identity = providers.save(config, "", {
            "name": "自定义中转",
            "base_url": "https://api.example.com/v1",
            "api_key": "test-key",
            "protocol": "openai_compatible",
            "models": ["model-a", "model-b"],
        })
        self.assertEqual(doc["providers"][identity]["models"], ["model-a", "model-b"])


class ServiceWiringTests(unittest.TestCase):
    def test_standalone_refresh_uses_runtime_handle(self):
        source = (BACKEND / "integration" / "ofm_service.mjs").read_text(encoding="utf-8")
        self.assertIn("service.runtime?.refreshCatalog", source)
        self.assertNotIn("service.refreshCatalog", source)


if __name__ == "__main__":
    unittest.main()
