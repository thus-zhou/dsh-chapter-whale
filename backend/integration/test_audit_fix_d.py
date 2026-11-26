"""D-domain audit regressions for v0.7.5 (P1-B, P2-16…P2-20, P2-24).

The paid-primary/OFM-fallback test drives the real
``model_roles.service()`` path against local fake HTTP servers: a paid
``openai_compatible`` primary and an OFM fallback.  No real model or quota is
used; the assertions are about which key reaches which listener.
"""
import asyncio
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from integration import bridge, costs, free_channels, model_roles, ofm_runtime, providers
from integration.provider_client import ProviderClient

PAID_SECRET = "PAID-SECRET"
OFM_KEY = "ofm-key"


class RecordingServer:
    """Tiny loopback HTTP server that records method/path/auth/body."""

    def __init__(self, responder):
        self.requests = []
        self._responder = responder
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length) if length else b''
                record = {'method': self.command, 'path': self.path,
                          'authorization': self.headers.get('Authorization') or '',
                          'body': body}
                with outer._lock:
                    outer.requests.append(record)
                status, payload = outer._responder(record)
                raw = json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = _handle
            do_POST = _handle

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}/v1'
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def chat_reply(text):
    def respond(request):
        return 200, {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]}
    return respond


def chat_fail_once(text):
    state = {'remaining': 1}

    def respond(request):
        if state['remaining']:
            state['remaining'] -= 1
            return 500, {'error': {'code': 'server_error'}}
        return 200, {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]}
    return respond


def health_ok(request):
    return 200, {'service': 'our-free-model', 'ok': True}


def health_wrong_service(request):
    return 200, {'service': 'something-else', 'ok': True}


class PaidPrimaryFallbackTests(unittest.TestCase):
    """P1-B: an OFM fallback heal must never rewrite the paid primary."""

    def _config(self, project, paid_url):
        return {
            'provider_schema': 1,
            'multi_model': True,
            'roles': {'B': {'provider_id': 'paid', 'model_id': 'paid-model',
                            'fallbacks': [{'provider_id': 'ofm', 'model_id': 'free/model'}]}},
            'default_binding': {'provider_id': 'paid', 'model_id': 'paid-model', 'fallbacks': []},
            'providers': {
                'paid': {'id': 'paid', 'name': '付费主模型', 'protocol': 'openai_compatible',
                         'base_url': paid_url, 'api_key': PAID_SECRET, 'enabled': True,
                         'revision': 1, 'models': [], 'pricing': {}},
                'ofm': {'id': 'ofm', 'name': 'OFM', 'protocol': 'ofm_standalone',
                        'base_url': 'http://127.0.0.1:9/v1', 'api_key': OFM_KEY,
                        'enabled': True, 'revision': 1,
                        'allowed_projects': [str(Path(project).resolve())]},
            },
            'resource_policy': {'fallback_cost_limit_cny': None},
        }

    def _runtime(self, root, cfg_path, config, ofm_port, ofm_home):
        return (
            mock.patch.object(bridge, 'RUNTIME_ROOT', root / 'runtime'),
            mock.patch.object(model_roles, 'config_path', return_value=cfg_path),
            mock.patch.object(ofm_runtime, 'ensure_started',
                              return_value={'url': f'http://127.0.0.1:{ofm_port}'}),
            mock.patch.object(ofm_runtime, 'HOME', ofm_home),
            mock.patch('integration.provider_circuit.active', return_value=False),
        )

    def test_ofm_fallback_heal_leaves_paid_primary_and_key_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_a = root / 'book-a'
            project_b = root / 'book-b'
            project_a.mkdir()
            project_b.mkdir()
            ofm_home = root / 'ofm-home'
            ofm_home.mkdir()
            (ofm_home / 'settings.json').write_text(
                json.dumps({'tokenSaver': {'enabled': False}}), encoding='utf-8')
            cfg_path = root / 'ai.json'

            paid = RecordingServer(chat_fail_once('paid-ok'))
            ofm = RecordingServer(chat_reply('ofm-ok'))
            try:
                config = self._config(project_a, paid.url)
                # The fallback may only target its own allowed book; the paid
                # book does not need an OFM grant.
                config['providers']['ofm']['allowed_projects'] = [
                    str(project_a.resolve()), str(project_b.resolve())]
                cfg_path.write_text(json.dumps(config), encoding='utf-8')

                patches = self._runtime(root, cfg_path, config, ofm.port, ofm_home)
                with patches[0], patches[1], patches[2], patches[3], patches[4]:
                    with costs.scope(project=str(project_a.resolve())):
                        client = model_roles.service('B', config)
                        self.assertIsInstance(client, ProviderClient)
                        with contextlib.redirect_stdout(io.StringIO()):
                            first = asyncio.run(client.chat(
                                [{'role': 'user', 'content': 'chapter one'}]))
                    self.assertEqual(first, 'ofm-ok')
                    self.assertEqual(client._primary.base_url, paid.url,
                                     'OFM fallback heal must not rewrite the paid primary')
                    self.assertEqual(client._client.base_url, ofm.url,
                                     'the OFM fallback itself must still be healed')
                    self.assertEqual(config['providers']['paid']['base_url'], paid.url)

                    with costs.scope(project=str(project_b.resolve())):
                        with contextlib.redirect_stdout(io.StringIO()):
                            second = asyncio.run(client.chat(
                                [{'role': 'user', 'content': 'chapter two'}]))
                    self.assertEqual(second, 'paid-ok')

                self.assertEqual([r['authorization'] for r in paid.requests],
                                 [f'Bearer {PAID_SECRET}', f'Bearer {PAID_SECRET}'])
                self.assertTrue(ofm.requests, 'fallback must actually call the fake OFM')
                self.assertEqual({r['authorization'] for r in ofm.requests},
                                 {f'Bearer {OFM_KEY}'})
                self.assertNotIn(PAID_SECRET, json.dumps(
                    [r['authorization'] for r in ofm.requests]))
                self.assertNotIn(PAID_SECRET, b' '.join(r['body'] for r in ofm.requests).decode())
            finally:
                paid.close()
                ofm.close()

    def test_token_saver_interception_does_not_rewrite_paid_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'book'
            project.mkdir()
            ofm_home = root / 'ofm-home'
            ofm_home.mkdir()
            # Fail closed: the fallback is rejected before any OFM request.
            (ofm_home / 'settings.json').write_text(
                json.dumps({'tokenSaver': {'enabled': True}}), encoding='utf-8')
            cfg_path = root / 'ai.json'

            paid = RecordingServer(chat_fail_once('paid-ok'))
            ofm = RecordingServer(chat_reply('ofm-ok'))
            try:
                config = self._config(project, paid.url)
                cfg_path.write_text(json.dumps(config), encoding='utf-8')
                patches = self._runtime(root, cfg_path, config, ofm.port, ofm_home)
                with patches[0], patches[1], patches[2], patches[3], patches[4]:
                    with costs.scope(project=str(project.resolve())):
                        client = model_roles.service('B', config)
                        with self.assertRaises(ValueError) as caught:
                            with contextlib.redirect_stdout(io.StringIO()):
                                asyncio.run(client.chat([{'role': 'user', 'content': 'raw prose'}]))
                    self.assertIn('提示词压缩', str(caught.exception))
                    self.assertEqual(client._primary.base_url, paid.url,
                                     'the rejected fallback must not rewrite the paid primary')
                self.assertEqual(ofm.requests, [], 'tokenSaver must stop the OFM request')
            finally:
                paid.close()
                ofm.close()


class OwnedPortProcTests(unittest.TestCase):
    """P2-16: a bare ``node`` listener is not a DSH owner."""

    def test_proc_identity_reads_the_real_process(self):
        if not sys.platform.startswith('linux'):
            self.skipTest('Linux /proc branch')
        identity = free_channels._proc_identity(os.getpid())
        self.assertIsNotNone(identity)
        self.assertTrue(identity['exe'])
        self.assertIn('python', Path(identity['exe']).name.casefold())
        self.assertTrue(identity['cmdline'])
        self.assertIsNone(free_channels._proc_identity('99999999'))
        self.assertIsNone(free_channels._proc_identity('not-a-pid'))

    def test_fake_node_listener_is_rejected_and_ofm_cmdline_is_kept(self):
        if not sys.platform.startswith('linux'):
            self.skipTest('Linux /proc branch')
        sample = '\n'.join([
            'p9001', 'cnode', 'n127.0.0.1:25600',
            'p9002', 'cnode', 'n127.0.0.1:25601',
            'p9003', 'cnode', 'n127.0.0.1:25602',
        ])
        identities = {
            '9001': {'exe': '/usr/bin/node', 'cmdline': 'node server.js'},
            '9002': {'exe': '/usr/bin/node',
                     'cmdline': 'node /opt/vendor/ofm_service.mjs --port 25601'},
            # 9003 has no readable identity -> conservative reject.
        }
        completed = mock.Mock(returncode=0, stdout=sample)
        with (
            mock.patch.object(free_channels.subprocess, 'run', return_value=completed),
            mock.patch.object(free_channels, '_proc_identity',
                              side_effect=lambda pid: identities.get(str(pid))),
        ):
            ports = free_channels.owned_ports()
        self.assertEqual(ports, [25601])

    def test_host_process_requires_path_evidence(self):
        self.assertFalse(free_channels._host_process('/usr/bin/node', '9001'))
        with mock.patch.object(free_channels, '_proc_identity',
                               return_value={'exe': '/opt/our-free-model/node',
                                             'cmdline': 'node /opt/our-free-model/ofm_service.mjs'}):
            self.assertTrue(free_channels._host_process('node', '9002'))

    @unittest.skipIf(os.name == 'nt', 'Unix lsof branch')
    def test_real_node_listener_needs_a_dsh_cmdline_marker(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        script = ("const s=require('http').createServer((q,r)=>r.end('ok'));"
                  "s.listen(0,'127.0.0.1',()=>console.log(s.address().port))")
        processes = []
        try:
            def start(*extra):
                proc = subprocess.Popen([node, '-e', script, *extra], stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
                processes.append(proc)
                port = int(proc.stdout.readline().strip())
                return port

            plain = start()
            marked = start('ofm_service.mjs')
            deadline = time.monotonic() + 5
            ports = []
            while time.monotonic() < deadline:
                ports = free_channels.owned_ports()
                if marked in ports:
                    break
                time.sleep(0.1)
            self.assertNotIn(plain, ports, 'a bare node listener must not be trusted')
            self.assertIn(marked, ports, 'a node cmdline naming ofm_service.mjs is a DSH host')
        finally:
            for proc in processes:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if proc.stdout:
                    proc.stdout.close()


class DshIdentityTests(unittest.TestCase):
    """P2-17: loopback self-reporting is not identity; owner check comes first."""

    def _config(self, url):
        return {'provider_schema': 1, 'providers': {'dsh': {
            'id': 'dsh', 'name': 'dsh', 'protocol': 'dsh_local', 'base_url': url,
            'api_key': 'DSH-SECRET', 'enabled': True, 'revision': 1,
            'allowed_projects': []}},
            'default_binding': {'provider_id': 'dsh', 'model_id': 'm'}}

    def test_fake_loopback_health_with_node_listener_is_rejected_before_key(self):
        with RecordingServer(health_ok) as server:
            config = self._config(server.url)
            # lsof says a process named node owns the port, but its real
            # /proc identity is this Python test process: no DSH path marker.
            completed = mock.Mock(returncode=0, stdout='\n'.join(
                [f'p{os.getpid()}', 'cnode', f'n127.0.0.1:{server.port}']))
            with (
                mock.patch.object(free_channels.subprocess, 'run', return_value=completed),
                mock.patch.object(free_channels, '_proc_identity',
                                  return_value={'exe': '/usr/bin/node',
                                                'cmdline': 'node server.js'}),
                mock.patch('manager.ai_tools.discover') as discover,
            ):
                with self.assertRaises(ValueError) as caught:
                    providers.discover(config, 'dsh')
                discover.assert_not_called()
            self.assertIn('尚未发送网关密钥', str(caught.exception))
            self.assertEqual(server.requests, [], 'verify must fail before GET /health')

    def test_owned_port_health_is_accepted_and_discover_runs(self):
        with RecordingServer(health_ok) as server:
            config = self._config(server.url)
            with (
                mock.patch.object(free_channels, 'owned_ports', return_value=[server.port]),
                mock.patch('manager.ai_tools.discover',
                           return_value={'models': ['m'], 'count': 1}) as discover,
            ):
                result = providers.discover(config, 'dsh')
                discover.assert_called_once()
            self.assertEqual(result['models'], ['m'])
            self.assertEqual([r['path'] for r in server.requests], ['/health'])

    def test_owned_port_with_wrong_health_service_is_rejected(self):
        with RecordingServer(health_wrong_service) as server:
            with mock.patch.object(free_channels, 'owned_ports', return_value=[server.port]):
                with self.assertRaises(ValueError):
                    providers.verify_dsh_gateway(server.url)


class ModelControlCharacterTests(unittest.TestCase):
    """P2-18: model IDs may not carry C0/DEL control bytes."""

    def _payload(self, **overrides):
        value = {'name': '中转', 'base_url': 'https://api.example.com/v1',
                 'api_key': 'fictional', 'protocol': 'openai_compatible'}
        value.update(overrides)
        return value

    def test_models_reject_control_characters(self):
        for bad in ('a\x01b', 'a\nb', 'a\tb', 'a\x7fb'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                providers.save({'provider_schema': 1, 'providers': {}}, None,
                               self._payload(models=[bad]))

    def test_free_models_reject_control_characters(self):
        for bad in ('free\x00model', 'free\r\nmodel', 'free\x7f'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                providers.save({'provider_schema': 1, 'providers': {}}, None,
                               self._payload(free_models=[bad]))

    def test_plain_models_still_save(self):
        doc, identity = providers.save({'provider_schema': 1, 'providers': {}}, None,
                                       self._payload(models=['a', 'b']))
        self.assertEqual(doc['providers'][identity]['models'], ['a', 'b'])


class NodeRuntimeEnvTests(unittest.TestCase):
    """P2-19: explicit runtime paths are authoritative; Electron is not Node."""

    def test_explicit_missing_node_does_not_fall_back_to_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            fallback = Path(tmp) / 'path-node'
            fallback.write_text('stub', encoding='utf-8')
            missing = Path(tmp) / 'missing-node'
            with (
                mock.patch.dict(os.environ, {'NOVEL_HELPER_NODE': str(missing)}, clear=False),
                mock.patch('shutil.which', return_value=str(fallback)) as which,
            ):
                with self.assertRaises(ValueError) as caught:
                    ofm_runtime._resolve_node_runtime()
            self.assertIn('NOVEL_HELPER_NODE', str(caught.exception))
            self.assertIn(str(missing), str(caught.exception))
            which.assert_not_called()

    def test_electron_probe_reads_process_versions_node(self):
        probe = mock.Mock(returncode=0, stdout='22.9.0', stderr='')
        with mock.patch.object(ofm_runtime.subprocess, 'run', return_value=probe) as run:
            version = ofm_runtime._node_version('/fake/electron',
                                                {'ELECTRON_RUN_AS_NODE': '1'})
        self.assertEqual(version, '22.9.0')
        args, kwargs = run.call_args
        self.assertNotIn('--version', args[0])
        self.assertEqual(args[0][1], '-e')
        self.assertIn('process.versions.node', args[0][2])
        self.assertEqual(kwargs['env']['ELECTRON_RUN_AS_NODE'], '1')

    def test_electron_without_node_version_is_an_error_even_without_proxy(self):
        with mock.patch.object(ofm_runtime, '_node_version', return_value=None):
            with self.assertRaises(ValueError) as caught:
                ofm_runtime._check_node_runtime('/fake/electron',
                                                {'ELECTRON_RUN_AS_NODE': '1'},
                                                proxy_configured=False)
        self.assertIn('Electron', str(caught.exception))

    def test_electron_resolution_marks_run_as_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            electron = Path(tmp) / 'electron'
            electron.write_text('stub', encoding='utf-8')
            with (
                mock.patch.dict(os.environ, {'NOVEL_HELPER_NODE': '',
                                             'NOVEL_HELPER_NODE_ELECTRON': str(electron)},
                                clear=False),
                mock.patch('shutil.which', return_value=None),
                mock.patch.object(Path, 'is_file', lambda self: str(self) == str(electron)),
            ):
                resolved, extra = ofm_runtime._resolve_node_runtime()
            self.assertEqual(Path(resolved), electron.resolve())
            self.assertEqual(extra, {'ELECTRON_RUN_AS_NODE': '1'})

    def test_missing_electron_path_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'missing-electron'
            with (
                mock.patch.dict(os.environ, {'NOVEL_HELPER_NODE': '',
                                             'NOVEL_HELPER_NODE_ELECTRON': str(missing)},
                                clear=False),
                mock.patch('shutil.which', return_value=None),
                mock.patch.object(Path, 'is_file', lambda self: False),
            ):
                with self.assertRaises(ValueError) as caught:
                    ofm_runtime._resolve_node_runtime()
            self.assertIn('NOVEL_HELPER_NODE_ELECTRON', str(caught.exception))


class PackageMetadataTests(unittest.TestCase):
    """P2-20 engines and P2-24 npm payload."""

    def test_engine_range_matches_runtime_floor(self):
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        self.assertEqual(package['engines']['node'], '>=22.21 <23 || >=24.5')
        self.assertIn('docs/*.md', package['files'])
        self.assertNotIn('docs/', package['files'])

    def test_node_pack_dry_run_excludes_docs_plan(self):
        npm = shutil.which('npm')
        if not npm:
            self.skipTest('npm is not installed')
        completed = subprocess.run(
            [npm, 'pack', '--dry-run', '--json', '--ignore-scripts'],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        document = next(iter(json.loads(completed.stdout).values()))
        paths = [row['path'] for row in document['files']]
        self.assertNotIn('docs/plan', paths)
        self.assertFalse([p for p in paths if p.startswith('docs/plan/')],
                         'docs/plan must not be packed')
        self.assertIn('docs/quickstart.md', paths)
        self.assertGreater(len(paths), 1000)


class EnginesRangeSemanticsTests(unittest.TestCase):
    """The engines expression must reject exactly what the runtime rejects."""

    @staticmethod
    def _allows(expression, major, minor):
        for clause in expression.split('||'):
            parts = clause.split()
            ok = True
            for part in parts:
                match = re.fullmatch(r'(>=|<=|>|<)?(\d+)(?:\.(\d+))?', part.strip())
                if not match:
                    ok = False
                    break
                operator, high_major, high_minor = match.groups()
                current = (major, minor)
                target = (int(high_major), int(high_minor or 0))
                if operator == '>=' and not current >= target:
                    ok = False
                elif operator == '<' and not current < target:
                    ok = False
                elif operator == '>' and not current > target:
                    ok = False
                elif operator == '<=' and not current <= target:
                    ok = False
            if ok:
                return True
        return False

    def test_range_and_runtime_agree(self):
        expression = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['engines']['node']
        cases = [(22, 20, False), (22, 21, True), (22, 22, True), (23, 11, False),
                 (24, 4, False), (24, 5, True), (24, 11, True), (25, 0, True), (26, 12, True)]
        for major, minor, expected in cases:
            self.assertEqual(self._allows(expression, major, minor), expected,
                             f'{major}.{minor}')
            self.assertEqual(ofm_runtime.node_version_supported(f'v{major}.{minor}.0'),
                             expected, f'{major}.{minor}')


if __name__ == '__main__':
    unittest.main()
