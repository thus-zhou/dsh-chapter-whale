"""P03 解释器契约：确定性选择 codec 解释器，失败时绝不改动旧凭据。

覆盖点：
- 三条解释器路径的优先级（sys.executable → 显式配置 → 托管 .venv → 中文错误）；
- 显式配置缺失时明确失败、不静默回退；
- 临时目录（含空格与中文）里加密→保存→新进程解密，输出只有相等布尔值与退出码；
- codec 缺失/注入失败时不写入、不清零，旧值仍能解出；
- 启动顺序：codec 预检失败发生在任何子进程（icacls / node）与凭据写入之前。
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 同级测试都以 `-t backend` 的顶层目录导入 `integration`；这里补一条绝对路径引导，
# 让 `python -m unittest backend.integration.test_ofm_runtime_interpreter` 也能直接跑。
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from integration import ofm_runtime

CODEC = Path(ofm_runtime.__file__).resolve().parent / 'credential_codec.py'
WINDOWS = os.name == 'nt'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

RESTART_CHECK = '''"""新进程校验密文可解；只输出相等布尔值。"""
import base64, hashlib, importlib.util, json, sys
from pathlib import Path
codec, store, digest = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location('codec_restart_check', codec)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
doc = json.loads(Path(store).read_text(encoding='utf-8'))
raw = module.transform(base64.b64decode(doc['protected'], validate=True), False)
print(hashlib.sha256(raw).hexdigest() == digest)
'''


def run(argv, data=b''):
    """跑一个子进程；只回传退出码与输出字节，测试断言不打印任何密文或明文。"""
    return subprocess.run(argv, input=data, capture_output=True, timeout=30, creationflags=NO_WINDOW)


def codec_call(mode, payload=b'', python=None, codec=CODEC):
    return run([str(python or sys.executable), '-B', '-X', 'utf8', str(codec), mode], payload)


def digest_of(raw):
    return hashlib.sha256(raw).hexdigest()


class Workdir:
    """含空格与中文的临时目录：路径必须原样工作，不能靠盘符或 PATH 偶然命中。"""

    def __enter__(self):
        self.base = Path(tempfile.mkdtemp(prefix='临时 目录 测试-'))
        self.path = self.base / '测试 目录'
        self.path.mkdir()
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.base, ignore_errors=True)
        return False


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ofm-interp-')
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_running_interpreter_wins_over_broken_explicit_config(self):
        chosen = ofm_runtime.resolve_helper_python(self_python=sys.executable,
            configured=str(self.root / '不存在的解释器.exe'), bundled=str(self.root / 'missing.exe'))
        self.assertEqual(chosen, Path(sys.executable).resolve())

    def test_explicit_config_used_when_running_interpreter_is_empty(self):
        chosen = ofm_runtime.resolve_helper_python(self_python='', configured=sys.executable,
            bundled=str(self.root / 'missing.exe'))
        self.assertEqual(chosen, Path(sys.executable).resolve())

    def test_managed_venv_used_when_nothing_else_is_available(self):
        chosen = ofm_runtime.resolve_helper_python(self_python='', configured='', bundled=sys.executable,
            root=self.root)
        self.assertEqual(chosen, Path(sys.executable).resolve())

    def test_missing_explicit_config_fails_loudly_without_fallback(self):
        missing = self.root / '缺失 的 python.exe'
        with self.assertRaises(ValueError) as caught:
            ofm_runtime.resolve_helper_python(self_python='', configured=str(missing), bundled=sys.executable)
        message = str(caught.exception)
        self.assertIn(str(missing), message)
        self.assertIn('不存在', message)
        self.assertIn(ofm_runtime.HELPER_PYTHON_ENV, message)

    def test_all_sources_missing_raise_actionable_error(self):
        with self.assertRaises(ValueError) as caught:
            ofm_runtime.resolve_helper_python(self_python='', configured='',
                bundled=str(self.root / 'missing.exe'), root=self.root)
        message = str(caught.exception)
        self.assertIn('未找到可用的 Python 解释器', message)
        self.assertIn('请重新安装完整发行包', message)
        self.assertIn('设置里指定 python 路径', message)
        self.assertIn('.venv', message)

    def test_managed_layout_is_derived_from_root_without_path_lookup(self):
        seen = {}

        def fake(value, source, timeout=15.0):
            seen[source] = str(value)
            raise ValueError('stop-here')

        with patch.object(ofm_runtime, '_validate_helper_python', side_effect=fake):
            with self.assertRaises(ValueError):
                ofm_runtime.resolve_helper_python(self_python='', configured='', root=self.root)
        self.assertEqual(seen['托管发行包解释器'],
            str(self.root / '.venv' / 'Scripts' / 'python.exe'))
        self.assertEqual(seen['运行进程自身（sys.executable）'], '')

    def test_environment_variable_is_used_when_running_interpreter_is_invalid(self):
        with patch.dict(os.environ, {ofm_runtime.HELPER_PYTHON_ENV: sys.executable}):
            chosen = ofm_runtime.resolve_helper_python(self_python='')
        self.assertEqual(chosen, Path(sys.executable).resolve())

    def test_bare_or_relative_python_is_rejected_instead_of_using_path(self):
        for value in ('python', 'python.exe', '.venv/Scripts/python.exe'):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                ofm_runtime._validate_helper_python(value, '显式配置')
            self.assertIn('不是绝对路径', str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            ofm_runtime._validate_helper_python('', '显式配置')
        self.assertIn('路径为空', str(caught.exception))


class CodecRuntimeTests(unittest.TestCase):
    def test_credential_runtime_pins_running_interpreter_and_neighbour_script(self):
        if not WINDOWS:
            self.skipTest('DPAPI 仅在 Windows 上可用')
        python, codec = ofm_runtime.credential_runtime()
        self.assertEqual(python, Path(sys.executable).resolve())
        self.assertEqual(codec, CODEC.resolve())
        self.assertEqual(codec_call('probe').stdout.strip(), b'ok')

    def test_explicit_non_default_interpreter_can_run_the_codec(self):
        if not WINDOWS:
            self.skipTest('DPAPI 仅在 Windows 上可用')
        chosen = ofm_runtime.resolve_helper_python(self_python='', configured=sys.executable)
        self.assertEqual(run([str(chosen), '-B', '-X', 'utf8', '-c', 'print(1)']).stdout.strip(), b'1')
        self.assertEqual(ofm_runtime.verify_credential_codec(chosen), CODEC.resolve())

    def test_missing_codec_script_is_reported_before_anything_runs(self):
        with Workdir() as work:
            with self.assertRaises(ValueError) as caught:
                ofm_runtime.verify_credential_codec(sys.executable, work / '不存在 codec.py')
            self.assertIn('凭据编解码组件不可用', str(caught.exception))
            self.assertIn('旧凭据未被改动', str(caught.exception))

    def test_non_windows_keeps_the_unsupported_boundary(self):
        if WINDOWS:
            self.skipTest('仅在非 Windows 上验证不支持边界')
        with self.assertRaises(ValueError):
            ofm_runtime.ensure_started()


class CredentialRoundTripTests(unittest.TestCase):
    def test_encrypt_save_restart_decrypt_with_spaces_and_chinese_path(self):
        if not WINDOWS:
            self.skipTest('DPAPI 仅在 Windows 上可用')
        with Workdir() as work:
            # 路径同时含空格与中文：任何环节拼接路径出错都会在这里暴露。
            self.assertIn(' ', str(work))
            self.assertIn('测试', str(work))
            secret = json.dumps({'forwardKey': '假密钥-仅用于测试', 'note': '临时 目录'}, ensure_ascii=False).encode('utf-8')
            encrypted = codec_call('encrypt', secret)
            self.assertEqual(encrypted.returncode, 0)
            self.assertNotIn(secret, encrypted.stdout)
            store = work / 'channel-credentials.json'
            store.write_text(json.dumps({'schema': 'novel-helper.dpapi.v1',
                'protected': encrypted.stdout.decode('ascii')}, ensure_ascii=False), encoding='utf-8')
            text = store.read_text(encoding='utf-8')
            self.assertNotIn('假密钥', text)
            check = work / '重启 校验.py'
            check.write_text(RESTART_CHECK, encoding='utf-8')
            restarted = run([sys.executable, '-B', '-X', 'utf8', str(check), str(CODEC), str(store), digest_of(secret)])
            self.assertEqual(restarted.returncode, 0)
            self.assertEqual(restarted.stdout.strip(), b'True')

    def test_codec_failure_keeps_the_old_credential_readable(self):
        if not WINDOWS:
            self.skipTest('DPAPI 仅在 Windows 上可用')
        with Workdir() as work:
            old = json.dumps({'forwardKey': '旧密钥-必须保留'}, ensure_ascii=False).encode('utf-8')
            encrypted = codec_call('encrypt', old)
            self.assertEqual(encrypted.returncode, 0)
            store = work / 'channel-credentials.json'
            store.write_text(json.dumps({'schema': 'novel-helper.dpapi.v1',
                'protected': encrypted.stdout.decode('ascii')}), encoding='utf-8')
            before = store.read_bytes()
            broken = work / '注入失败 codec.py'
            broken.write_text('raise SystemExit(1)\n', encoding='utf-8')
            with self.assertRaises(ValueError) as caught:
                ofm_runtime.verify_credential_codec(sys.executable, broken)
            self.assertIn('旧凭据未被改动', str(caught.exception))
            # Node 侧保存路径是“先加密成功，才落盘”：失败时没有密文产出，也就没有写入。
            attempt = codec_call('encrypt', '{"forwardKey":"新值"}'.encode('utf-8'), codec=broken)
            self.assertNotEqual(attempt.returncode, 0)
            self.assertEqual(attempt.stdout.strip(), b'')
            self.assertEqual(store.read_bytes(), before)
            check = work / '旧值 校验.py'
            check.write_text(RESTART_CHECK, encoding='utf-8')
            restarted = run([sys.executable, '-B', '-X', 'utf8', str(check), str(CODEC), str(store), digest_of(old)])
            self.assertEqual(restarted.returncode, 0)
            self.assertEqual(restarted.stdout.strip(), b'True')

    def test_plaintext_store_is_rejected_before_the_service_starts(self):
        with Workdir() as work:
            store = work / 'channel-credentials.json'
            store.write_text(json.dumps({'forwardKey': '明文-不得覆盖'}, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(ValueError) as caught:
                ofm_runtime.verify_credential_store(store)
            self.assertIn('不是 DPAPI 格式', str(caught.exception))
            self.assertEqual(json.loads(store.read_text(encoding='utf-8')), {'forwardKey': '明文-不得覆盖'})
            self.assertIsNone(ofm_runtime.verify_credential_store(work / 'missing.json'))
            good = work / 'good.json'
            good.write_text(json.dumps({'schema': 'novel-helper.dpapi.v1', 'protected': 'AAAA'}), encoding='utf-8')
            self.assertEqual(ofm_runtime.verify_credential_store(good), good)


class StartupOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ofm-start-')
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(ofm_runtime, 'DATA', self.root),
            patch.object(ofm_runtime, 'HOME', self.root / 'ofm-home'),
            patch.object(ofm_runtime, 'CONTROL', self.root / 'ofm-control.json'),
            patch.object(ofm_runtime, 'INFO', self.root / 'ofm-service.json')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    @unittest.skipUnless(WINDOWS, 'Windows DPAPI 凭据保护仅在 Windows 可用')
    def test_codec_preflight_fails_before_icacls_node_or_any_write(self):
        broken = self.root / '注入失败 codec.py'
        broken.write_text('raise SystemExit(1)\n', encoding='utf-8')
        real_run = subprocess.run
        spawned = []

        def spy(argv, *args, **kwargs):
            spawned.append([str(item) for item in argv])
            return real_run(argv, *args, **kwargs)

        with patch.object(ofm_runtime, 'CODEC_SCRIPT', broken), \
                patch.object(ofm_runtime.subprocess, 'run', side_effect=spy):
            with self.assertRaises(ValueError) as caught:
                ofm_runtime.ensure_started(start=True)
        message = str(caught.exception)
        self.assertIn('凭据编解码组件不可用', message)
        self.assertIn('旧凭据未被改动', message)
        # 只允许两次解释器探测（版本探测 + codec probe）；icacls 与 node 一次都没跑。
        flat = ' '.join(' '.join(item) for item in spawned)
        self.assertNotIn('icacls', flat)
        self.assertNotIn('node', flat.lower())
        self.assertTrue(spawned and spawned[-1][-1] == 'probe', spawned)
        self.assertFalse((self.root / 'ofm-control.json').exists())
        self.assertFalse((self.root / 'ofm-home' / 'channel-credentials.json').exists())


if __name__ == '__main__':
    unittest.main()
