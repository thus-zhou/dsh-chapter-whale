"""0.9.2：macOS ARM64 部署文件与归档校验。

只读检查仓库里的 plist / run.command / README，外加用临时目录验证
platform_support.verify_archive 对 macos-arm64 归档的接受与拒绝路径。
"""
import gzip
import io
import json
import plistlib
import tarfile
import tempfile
import unittest
from pathlib import Path

from integration import platform_support as ps

ROOT = Path(__file__).resolve().parents[2]
MACOS = ROOT / 'deploy' / 'macos'


def _read(name):
    return (MACOS / name).read_bytes()


def _archive(path, members):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with path.open('wb') as handle:
        with gzip.GzipFile(fileobj=handle, mode='wb', mtime=0) as gz:
            gz.write(raw.getvalue())
    return path


def _manifest(platform='macos-arm64', arch='arm64'):
    return json.dumps({'schema': 1, 'platform': platform, 'arch': arch,
                       'version': '0.9.2', 'files': 1}).encode()


class PlistTest(unittest.TestCase):
    def setUp(self):
        self.plist = plistlib.loads(_read('com.chapterwhale.service.plist'))

    def test_label_and_entrypoint(self):
        self.assertEqual(self.plist['Label'], 'com.chapterwhale.service')
        args = self.plist['ProgramArguments']
        self.assertIn('integration.resident_service', args)
        self.assertEqual(args[args.index('start') - 1], 'integration.resident_service')
        self.assertIn('--root', args)
        self.assertEqual(args[args.index('--root') + 1], '/Users/Shared/chapter-whale')

    def test_environment_and_restart_policy(self):
        env = self.plist['EnvironmentVariables']
        self.assertEqual(env['PYTHONPATH'], '/opt/chapter-whale/backend')
        self.assertEqual(env['PYTHONUTF8'], '1')
        self.assertIs(self.plist['KeepAlive']['SuccessfulExit'], False)
        self.assertGreaterEqual(self.plist['ExitTimeOut'], 30)
        self.assertEqual(self.plist['RunAtLoad'], True)

    def test_logs_live_on_the_data_volume(self):
        self.assertTrue(self.plist['StandardOutPath'].startswith('/Users/Shared/chapter-whale/logs/'))
        self.assertTrue(self.plist['StandardErrorPath'].startswith('/Users/Shared/chapter-whale/logs/'))


class RunCommandTest(unittest.TestCase):
    def setUp(self):
        self.text = _read('run.command').decode('utf-8')

    def test_shell_is_strict_and_lf_only(self):
        self.assertTrue(self.text.startswith('#!/bin/sh'))
        self.assertIn('set -eu', self.text)
        self.assertNotIn('\r\n', self.text, 'run.command 必须使用 LF')

    def test_paths_are_quoted(self):
        self.assertIn('"$ROOT"', self.text)
        self.assertIn('"$CODE/backend/integration"', self.text)
        self.assertNotIn('$ROOT/正文', self.text)

    def test_refuses_missing_or_unwritable_volume(self):
        self.assertIn('exit 64', self.text)
        self.assertIn('exit 65', self.text)
        self.assertIn('exit 66', self.text)


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = _read('README.md').decode('utf-8')

    def test_install_uses_launchctl_bootstrap(self):
        self.assertIn('launchctl bootstrap gui/', self.text)
        self.assertIn('launchctl bootout', self.text)
        self.assertIn('/Users/Shared/chapter-whale', self.text)

    def test_says_pending_on_real_hardware(self):
        self.assertIn('待实机', self.text)
        self.assertIn('Apple Silicon', self.text)

    def test_browser_and_login_are_not_opened(self):
        self.assertIn('未开放', self.text)
        self.assertIn('浏览器', self.text)

    def test_warns_case_insensitive_and_network_volume(self):
        self.assertIn('大小写不敏感', self.text)
        self.assertIn('NAS', self.text)


class MacArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def build(self, name, platform='macos-arm64', arch='arm64', payload=None):
        payload = {'backend/integration/resident_service.py': b'x = 1\n',
                   'deploy/macos/run.command': b'#!/bin/sh\nset -eu\n'} if payload is None else payload
        files, digest = ps._payload_digest(payload)
        manifest = {'schema': 1, 'platform': platform, 'arch': arch, 'version': '0.9.3',
                    'files': len(files), 'sha256': digest}
        members = {'service-build.json': json.dumps(manifest).encode()}
        members.update(payload)
        return _archive(self.dir / name, members)

    def test_macos_archive_passes(self):
        path = self.build('dsh-chapter-whale-service-macos-arm64-0.9.2.tar.gz')
        result = ps.verify_archive(path)
        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['target'], 'macos-arm64')

    def test_elf_payload_is_refused(self):
        path = self.build('dsh-chapter-whale-service-macos-arm64-0.9.2.tar.gz',
                          payload={'backend/integration/fastpath.so': b'\x7fELF\x02\x01\x01'})
        result = ps.verify_archive(path)
        self.assertFalse(result['ok'])
        self.assertTrue(any(p.startswith(('elf_binary', 'linux_object')) for p in result['problems']),
                        result['problems'])

    def test_linux_archive_is_not_accepted_as_macos(self):
        path = self.build('dsh-chapter-whale-service-linux-arm64-0.9.2.tar.gz',
                          platform='linux-arm64', payload={})
        result = ps.verify_archive(path, expect_target='macos-arm64')
        self.assertFalse(result['ok'])
        self.assertTrue(any(p.startswith('platform_mismatch') for p in result['problems']))

    def test_intel_archive_passes_and_mismatch_is_refused(self):
        path = self.build('dsh-chapter-whale-service-macos-amd64-0.9.3.tar.gz',
                          platform='macos-amd64', arch='amd64',
                          payload={'deploy/macos/run.command': b'#!/bin/sh\nset -eu\n'})
        result = ps.verify_archive(path, expect_target='macos-amd64')
        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['target'], 'macos-amd64')
        wrong = ps.verify_archive(path, expect_target='macos-arm64')
        self.assertFalse(wrong['ok'])
        self.assertTrue(any(p.startswith('platform_mismatch') for p in wrong['problems']))

    def test_intel_archive_name_must_carry_arch(self):
        path = self.build('dsh-chapter-whale-service-macos-arm64-0.9.3.tar.gz',
                          platform='macos-amd64', arch='amd64', payload={})
        result = ps.verify_archive(path)
        self.assertFalse(result['ok'])
        self.assertTrue(any(p.startswith('archive_name_arch_mismatch') for p in result['problems']),
                        result['problems'])


if __name__ == '__main__':
    unittest.main()
