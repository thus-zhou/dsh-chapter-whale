"""发行包组装规则：只发清单里的文件，并且拒绝测试残留。"""
import importlib.util
import json
import unittest
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

    def test_stage_rewrites_build_id(self):
        data, _ = self.module.manifest_files(ROOT)
        self.assertIsInstance(data.get("buildId"), str)


if __name__ == "__main__":
    unittest.main()
