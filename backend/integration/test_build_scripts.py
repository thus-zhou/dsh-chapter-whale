"""构建脚本的校验面：外部锚点、sidecar 必需、版本绑定。

这些用例直接调用 `scripts/build-linux-service.py` 与
`scripts/build-macos-service.py` 的 `main()`，只走 `--verify` 分支，
不收集仓库文件、不重打归档，所以是毫秒级。
"""

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from importlib import util as importlib_util
from pathlib import Path
from unittest.mock import patch

from integration import platform_support

ROOT = Path(__file__).resolve().parents[2]


def _load(script: str):
    path = ROOT / "scripts" / script
    spec = importlib_util.spec_from_file_location(script.replace("-", "_")[:-3], path)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ArchiveCase(unittest.TestCase):
    script = "build-linux-service.py"
    platform = "linux-amd64"
    arch = "amd64"
    external = "linux-service-manifest-amd64.json"

    def setUp(self):
        self.module = _load(self.script)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        payload = {"backend/integration/example.py": b"print('ok')\n",
                   "README.md": "说明\r\n".encode("utf-8")}
        files, digest = platform_support._payload_digest(payload)
        version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
        self.version = version
        self.manifest = {"schema": 1, "version": version, "platform": self.platform,
                         "arch": self.arch, "files": len(files), "sha256": digest}
        source = {}
        for name, data in payload.items():
            path = self.root / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            source[name] = path
        self.archive = self.root / "dsh-chapter-whale-service-{}-{}.tar.gz".format(
            self.platform.replace("-", "-", 1), self.version)
        self.archive = self.root / (
            f"dsh-chapter-whale-service-{self.platform.replace('linux-', 'linux-')}"
            f"-{self.version}.tar.gz")
        names = dict(source)
        self.module.build_archive(names, self.archive, {
            "service-build.json": (json.dumps(self.manifest, ensure_ascii=False, indent=2)
                                   + "\n").encode("utf-8")})
        self.sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def write_sidecar(self, value=None):
        (self.root / (self.archive.name + ".sha256")).write_text(
            f"{value or self.sha}  {self.archive.name}\n", encoding="utf-8", newline="\n")

    def write_external(self, **overrides):
        info = {"name": self.archive.name, "bytes": len(self.archive.read_bytes()),
                "sha256": self.sha}
        info.update(overrides)
        (self.root / self.external).write_text(
            json.dumps({"version": self.version, "archive": info}, ensure_ascii=False),
            encoding="utf-8", newline="\n")

    def verify(self, *extra):
        argv = [self.script, "--verify", str(self.archive), "--arch", self.arch, *extra]
        out = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                self.module.main()
        return caught.exception.code, out.getvalue()


class LinuxVerifyTest(_ArchiveCase):
    def test_ok_when_pin_and_sidecar_agree(self):
        self.write_sidecar()
        self.write_external()
        code, out = self.verify("--expect-sha256", self.sha)
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 0, report)
        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["expected_sha256"], self.sha)

    def test_forged_archive_is_caught_by_external_pin(self):
        self.write_sidecar()
        self.write_external()
        forged = "0" * 64
        code, out = self.verify("--expect-sha256", forged)
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("archive_pin_mismatch")
                            for item in report["problems"]), report)

    def test_missing_sidecar_is_refused_by_default(self):
        self.write_external()
        code, out = self.verify()
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("sidecar_missing") for item in report["problems"]))

    def test_missing_sidecar_allowed_only_when_asked(self):
        code, out = self.verify("--allow-missing-sidecar")
        self.assertEqual(code, 0, out)

    def test_sidecar_with_wrong_digest_is_refused(self):
        self.write_sidecar("f" * 64)
        code, out = self.verify()
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("sidecar_sha256_mismatch")
                            for item in report["problems"]))

    def test_unreadable_sidecar_reports_instead_of_crashing(self):
        (self.root / (self.archive.name + ".sha256")).write_text("   \n", encoding="utf-8")
        code, out = self.verify()
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("sidecar_unreadable") for item in report["problems"]))

    def test_external_manifest_non_numeric_bytes_reports_type_error(self):
        self.write_sidecar()
        payload = {"version": self.version, "archive": {
            "name": self.archive.name, "bytes": "很多", "sha256": self.sha}}
        (self.root / self.external).write_text(json.dumps(payload), encoding="utf-8")
        code, out = self.verify()
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("external_manifest_field_type")
                            for item in report["problems"]), report)

    def test_manifest_version_must_match_package(self):
        self.write_sidecar()
        payload_source = {"a.py": b"print(1)\n"}
        files, digest = platform_support._payload_digest(payload_source)
        stale = {"schema": 1, "version": "0.0.1", "platform": self.platform,
                 "arch": self.arch, "files": len(files), "sha256": digest}
        path = self.root / "src" / "a.py"
        path.write_bytes(payload_source["a.py"])
        self.module.build_archive({"a.py": path}, self.archive, {
            "service-build.json": (json.dumps(stale) + "\n").encode("utf-8")})
        self.sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.write_sidecar()
        code, out = self.verify()
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("archive_version_mismatch")
                            for item in report["problems"]), report)


class MacVerifyTest(_ArchiveCase):
    script = "build-macos-service.py"
    platform = "macos-arm64"
    arch = "arm64"
    external = "macos-service-manifest-arm64.json"

    def test_ok_with_pin(self):
        self.write_sidecar()
        self.write_external()
        code, out = self.verify("--expect-sha256", self.sha)
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 0, report)
        self.assertEqual(report["problems"], [])

    def test_pin_mismatch_is_refused(self):
        self.write_sidecar()
        code, out = self.verify("--expect-sha256", "1" * 64)
        report = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertTrue(any(item.startswith("archive_pin_mismatch")
                            for item in report["problems"]))


if __name__ == "__main__":
    unittest.main()
