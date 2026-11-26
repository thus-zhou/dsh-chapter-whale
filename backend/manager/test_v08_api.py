"""v0.8 直写工作台 API：章节、草稿、定稿、大纲、资料、备份与导出。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from manager import app as module


class V08ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novel-v08-api-")
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "DATA", self.root),
                        patch.object(module, "AI_PATH", self.root / "ai.json")]
        for item in self.patches:
            item.start()
        self.client = TestClient(module.create_app(self.root / "manager.db", start_dispatcher=False))
        self.headers = {"X-Novel-Helper": "1"}
        self.project = self.root / "book"
        (self.project / "正文").mkdir(parents=True)
        (self.project / ".webnovel").mkdir()
        (self.project / ".webnovel" / "state.json").write_text(json.dumps({"title": "隔离测试"}), encoding="utf-8")
        response = self.client.post("/api/projects", json={"path": str(self.project)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.identity = response.json()["id"]

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def create(self, chapter=1, title="开端", content="第一段。\n\n第二段。\n"):
        response = self.client.post(f"/api/projects/{self.identity}/chapters",
                                    json={"chapter": chapter, "title": title, "content": content},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def state(self, chapter=1):
        response = self.client.get(f"/api/projects/{self.identity}/chapters/{chapter}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_read_save_and_conflict(self):
        created = self.create()
        self.assertTrue(created["chapter_uid"].startswith("chuid_"))
        state = self.state()
        self.assertEqual(state["content"], "第一段。\n\n第二段。\n")
        self.assertIn("draft", state)
        self.assertTrue(state["version_id"].startswith("ver_"))

        # 未带 expected 的覆盖必须 400
        missing = self.client.put(f"/api/projects/{self.identity}/chapters/1",
                                  json={"title": "开端", "content": "改稿", "op_id": "op-missing"},
                                  headers=self.headers)
        self.assertEqual(missing.status_code, 400)

        saved = self.client.put(f"/api/projects/{self.identity}/chapters/1",
                                json={"title": "开端", "content": "改稿。\n", "op_id": "op-save",
                                      "expected_version_id": state["version_id"],
                                      "expected_content_sha256": state["sha256"]},
                                headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["status"], "saved")
        self.assertNotEqual(saved.json()["content_sha256"], state["sha256"])

        stale = self.client.put(f"/api/projects/{self.identity}/chapters/1",
                                json={"title": "开端", "content": "旧页面", "op_id": "op-stale",
                                      "expected_version_id": state["version_id"],
                                      "expected_content_sha256": state["sha256"]},
                                headers=self.headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["code"], "concurrent_modification")

    def test_draft_endpoint_serializes_devices(self):
        self.create()
        first = self.client.put(f"/api/projects/{self.identity}/chapters/1/draft",
                                json={"title": "开端", "content": "草稿一", "expected_draft_id": None,
                                      "expected_draft_epoch": 0, "expected_draft_revision": 0},
                                headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        draft = first.json()["draft"]
        second = self.client.put(f"/api/projects/{self.identity}/chapters/1/draft",
                                 json={"title": "开端", "content": "草稿二",
                                       "expected_draft_id": draft["draft_id"],
                                       "expected_draft_epoch": draft["draft_epoch"],
                                       "expected_draft_revision": draft["draft_revision"]},
                                 headers=self.headers)
        self.assertEqual(second.status_code, 200)
        conflict = self.client.put(f"/api/projects/{self.identity}/chapters/1/draft",
                                   json={"title": "开端", "content": "平板旧稿",
                                         "expected_draft_id": draft["draft_id"],
                                         "expected_draft_epoch": draft["draft_epoch"],
                                         "expected_draft_revision": draft["draft_revision"]},
                                   headers=self.headers)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "draft_conflict")
        self.assertEqual(conflict.json()["current_draft"]["content"], "草稿二")

    def test_quick_check_author_confirm_and_revoke(self):
        self.create(content="他说：“走吧。。。”\n\n我突然笑了，突然又停了，不禁冷笑。\n")
        quick = self.client.post(f"/api/projects/{self.identity}/chapters/1/quick-check",
                                 json={}, headers=self.headers)
        self.assertEqual(quick.status_code, 200, quick.text)
        self.assertEqual(quick.json()["model_calls"], 0)
        self.assertTrue(quick.json()["issues"])
        state = self.state()
        confirm = self.client.post(f"/api/projects/{self.identity}/chapters/1/author-confirm",
                                   json={"expected_version_id": state["version_id"],
                                         "expected_content_sha256": state["sha256"],
                                         "op_id": "confirm-api-1"}, headers=self.headers)
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertEqual(confirm.json()["status"], "confirmed")
        self.assertTrue(self.state()["review_state"]["author_confirmed"])
        revoked = self.client.request("DELETE", f"/api/projects/{self.identity}/chapters/1/author-confirm",
                                      json={}, headers=self.headers)
        self.assertEqual(revoked.status_code, 200)
        self.assertFalse(self.state()["review_state"]["author_confirmed"])

    def test_outline_files_meta_and_lore(self):
        (self.project / "大纲").mkdir()
        (self.project / "大纲" / "总纲.md").write_text("总纲", encoding="utf-8", newline="\n")
        listing = self.client.get(f"/api/projects/{self.identity}/outline/files")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["files"][0]["name"], "总纲.md")
        self.assertTrue(listing.json()["files"][0]["editable"])
        revision = listing.json()["files"][0]["revision"]
        saved = self.client.put(f"/api/projects/{self.identity}/outline/files/总纲.md",
                                json={"content": "总纲改", "revision": revision}, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        meta = self.client.put(f"/api/projects/{self.identity}/outline/meta",
                               json={"master_outline": "权威总纲", "expected_meta_revision": 1},
                               headers=self.headers)
        self.assertEqual(meta.status_code, 200, meta.text)
        self.assertEqual(meta.json()["meta"]["meta_revision"], 2)
        lore = self.client.put(f"/api/projects/{self.identity}/lore/files/世界观.md",
                               json={"content": "境界表"}, headers=self.headers)
        self.assertEqual(lore.status_code, 200, lore.text)
        read = self.client.get(f"/api/projects/{self.identity}/lore/files/世界观.md")
        self.assertEqual(read.json()["content"], "境界表")

    def test_trash_and_delete_api(self):
        self.create(1, "第一章", "第一章正文\n")
        self.create(2, "第二章", "第二章正文\n")
        state = self.state(2)
        deleted = self.client.request("DELETE", f"/api/projects/{self.identity}/chapters/2",
                                      json={"expected_content_sha256": state["sha256"],
                                            "op_id": "delete-api-2"}, headers=self.headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        entry = deleted.json()["trash_entry"]
        restored = self.client.post(f"/api/projects/{self.identity}/trash/{entry}/restore",
                                    json={"op_id": "restore-api-2"}, headers=self.headers)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["chapter_id"], 2)

    def test_backup_and_export_legacy(self):
        self.create()
        backup_dir = self.root / "backup-target"
        backed = self.client.post(f"/api/projects/{self.identity}/backup",
                                  json={"destination": str(backup_dir)}, headers=self.headers)
        self.assertEqual(backed.status_code, 200, backed.text)
        self.assertTrue((backup_dir / "backup_manifest.json").is_file())
        exported = self.client.post(f"/api/projects/{self.identity}/rollback/export-legacy",
                                    json={"destination": str(self.root / "legacy")}, headers=self.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertTrue((self.root / "legacy" / "正文").is_dir())

    def test_search_is_local_and_finds_two_char_name(self):
        self.create(content="林溪拿着旧地图走进档案馆。\n")
        response = self.client.get(f"/api/projects/{self.identity}/search", params={"q": "林溪"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
