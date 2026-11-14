"""发行包组装规则：只发清单里的文件，并且拒绝测试残留。"""
import importlib.util
import json
import unittest
import hashlib
from tempfile import TemporaryDirectory
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pack-bundle.py"


def load_script():
    spec = importlib.util.spec_from_file_location("pack_bundle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BundleRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_script()

    def test_residue_is_rejected(self):
        bad = self.module.unwanted([
            "package/backend/integration/__pycache__/writer_runner.cpython-313.pyc",
            "package/backend/integration/test_secret_fixture.py",
            "package/backend/manager/app.py",
        ])
        self.assertEqual(len(bad), 2)
        self.assertTrue(any("__pycache__" in name for name in bad))
        self.assertTrue(any(name.endswith("test_secret_fixture.py") for name in bad))

    def test_manifest_files_all_exist(self):
        data, files = self.module.manifest_files(ROOT)
        self.assertTrue(data.get("buildId"))
        # runtime/ 是发行时才安装的产物（仓库里被 gitignore）；干净检出只核对源码部分。
        bundled = (ROOT / "runtime").is_dir()
        missing = [name for name in files
                   if (bundled or not str(name).startswith("runtime/")) and not (ROOT / name).is_file()]
        self.assertEqual(missing, [])

    def test_manifest_has_the_entry_points(self):
        _, files = self.module.manifest_files(ROOT)
        for name in ("backend/manager/app.py", "backend/integration/writer_runner.py",
                     "backend/fanqie_auto_publish/publication_safety.py"):
            self.assertIn(name, files)

    def test_actual_stage_copies_only_manifest_and_removes_self_download(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            stage_dir = Path(tmp) / "stage"
            package = stage_dir / "package"
            package.mkdir(parents=True)
            (root / "runtime").mkdir()
            (root / "runtime/real.txt").write_bytes(b"runtime")
            (root / "runtime/unlisted.txt").write_bytes(b"residue")
            manifest = {"buildId": "new", "files": {"runtime/real.txt": hashlib.sha256(b"runtime").hexdigest()}}
            (root / "runtime-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (package / "runtime-download.json").write_text('{"buildId":"old"}', encoding="utf-8")
            data, count = self.module.stage(root, stage_dir)
            self.assertEqual((data["buildId"], count), ("new", 1))
            self.assertEqual((package / "runtime/real.txt").read_bytes(), b"runtime")
            self.assertFalse((package / "runtime/unlisted.txt").exists())
            self.assertFalse((package / "runtime-download.json").exists())
            (root / "runtime/real.txt").write_bytes(b"changed")
            with self.assertRaises(SystemExit):
                self.module.stage(root, stage_dir)


if __name__ == "__main__":
    unittest.main()
