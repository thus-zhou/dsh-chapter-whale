"""凭据存储适配层：用可注入的假保护器验证迁移、降级与恢复（不依赖 Windows DPAPI）。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import secret_store


def fake_pair():
    key = b"novel"

    def flip(raw):
        return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(raw))

    return flip, flip


def broken_pair():
    def protect(raw):
        return b"x"

    def unprotect(raw):
        raise RuntimeError("cannot decrypt")

    return protect, unprotect


class SecretStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-secrets-")
        self.root = Path(self.temp.name)
        self.written = []

    def tearDown(self):
        self.temp.cleanup()

    def write(self, config):
        self.written.append(json.loads(json.dumps(config)))
        (self.root / "ai.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    def test_round_trip_moves_keys_out_of_the_config(self):
        config = {"base_url": "https://api.example.com/v1", "api_key": "sk-secret-one",
                  "roles": {"D": {"model": "d-model", "api_key": "sk-secret-two"}}}
        result = secret_store.save(self.root, config, self.write, codec_pair=fake_pair())
        self.assertTrue(result["migrated"])
        self.assertEqual(result["stored"], 2)
        stored = (self.root / "ai.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-secret-one", stored)
        self.assertNotIn("sk-secret-two", stored)
        blob = (self.root / secret_store.STORE_NAME).read_text(encoding="utf-8")
        self.assertNotIn("sk-secret-one", blob)
        loaded = secret_store.load(self.root, json.loads(stored), codec_pair=fake_pair())
        self.assertEqual(loaded["api_key"], "sk-secret-one")
        self.assertEqual(loaded["roles"]["D"]["api_key"], "sk-secret-two")

    def test_unavailable_protection_keeps_plaintext_and_says_so(self):
        config = {"api_key": "sk-keep-me"}
        result = secret_store.save(self.root, config, self.write, codec_pair=None)
        self.assertFalse(result["migrated"])
        self.assertEqual(result["mode"], "plaintext-acl")
        self.assertEqual(result["detail"], secret_store.status(self.root, None)["detail"])
        self.assertEqual(self.written[-1]["api_key"], "sk-keep-me")
        self.assertEqual(secret_store.load(self.root, config, codec_pair=None)["api_key"], "sk-keep-me")

    def test_failed_write_verification_keeps_the_old_plaintext(self):
        config = {"api_key": "sk-safe"}
        result = secret_store.save(self.root, config, self.write, codec_pair=broken_pair())
        self.assertFalse(result["migrated"])
        self.assertEqual(self.written[-1]["api_key"], "sk-safe")
        self.assertEqual(secret_store.load(self.root, config, codec_pair=fake_pair())["api_key"], "sk-safe")

    def test_corrupt_store_does_not_break_loading(self):
        (self.root / secret_store.STORE_NAME).write_text("{not json", encoding="utf-8")
        config = {"api_key": "sk-plain"}
        self.assertEqual(secret_store.load(self.root, config, codec_pair=fake_pair())["api_key"], "sk-plain")

    def test_backup_is_encrypted_and_restorable(self):
        config = {"api_key": "sk-backup"}
        secret_store.save(self.root, config, self.write, codec_pair=fake_pair())
        backup = secret_store.backup(self.root, fake_pair())
        self.assertIsNotNone(backup)
        text = Path(backup).read_text(encoding="utf-8")
        self.assertNotIn("sk-backup", text)
        (self.root / secret_store.STORE_NAME).unlink()
        outcome = secret_store.restore_backup(self.root, self.write, codec_pair=fake_pair())
        self.assertEqual(outcome["restored"], ["root"])
        self.assertEqual(secret_store.load(self.root, {}, codec_pair=fake_pair())["api_key"], "sk-backup")

    def test_status_reports_unavailable_without_protection(self):
        self.assertEqual(secret_store.status(self.root, None)["mode"], "plaintext-acl")
        self.assertFalse(secret_store.status(self.root, None)["available"])
        self.assertEqual(secret_store.status(self.root, fake_pair())["mode"], "dpapi")


if __name__ == "__main__":
    unittest.main()
