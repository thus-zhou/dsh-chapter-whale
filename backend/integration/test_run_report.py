"""只读运行投影的契约测试：渲染不启动 worker、不写平台、不猜费用。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from integration import bridge, costs, run_report, scheduler, writer_runner


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


_UNSET = object()


class RunReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="run-report-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        for folder in ("正文", "大纲", ".webnovel"):
            (self.project / folder).mkdir(parents=True, exist_ok=True)
        (self.project / ".webnovel" / "state.json").write_text('{"title":"离线测试"}', encoding="utf-8")
        self.runs = self.root / "runs"
        self.ledger = self.root / "costs.sqlite3"
        self.receipts = {}
        self.patches = [
            patch.object(scheduler, "RUNS_ROOT", self.runs),
            patch.object(bridge, "COMBINED_ROOT", self.root),
            patch.object(bridge, "RUNTIME_ROOT", self.root / "runtime"),
            patch.dict(os.environ, {"NOVEL_HELPER_COST_DB": str(self.ledger)}),
            patch.object(scheduler, "_published_ids", return_value=[]),
            patch.object(scheduler, "_queue_ids", return_value=[]),
            patch.object(run_report.writer_runner, "reviewed_chapters",
                         side_effect=lambda project_root: dict(self.receipts)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.now = datetime.now(timezone.utc)
        self.today = datetime.now().date().isoformat()
        self.job = {"project": str(self.project), "book": "潮汐钟", "account": "acct",
                    "timezone": "Asia/Shanghai", "publication_mode": "draft_only"}

    def _write(self, run_id: str, record: dict) -> None:
        folder = self.runs / bridge.safe_dir_name("daily")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{run_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def _record(self, **overrides) -> dict:
        record = {
            "job_id": "daily",
            "project": str(self.project),
            "book": "潮汐钟",
            "account": "acct",
            "run_date": self.today,
            "slot": self.today + "@08:00",
            "status": "success",
            "started_at": _iso(self.now - timedelta(minutes=5)),
            "finished_at": _iso(self.now),
            "target_ids": [1, 2],
            "verification": "local_body_review_and_memory_only_no_remote_delivery",
            "cycle": {"run_date": self.today, "slot": "08:00", "target_ids": [1, 2],
                      "status": "success", "publication_mode": "draft_only", "draft_chapters": []},
        }
        record.update(overrides)
        return record

    def _body(self, chapter: int, text: str) -> Path:
        path = self.project / "正文" / f"第{chapter}章-测试.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def _pass(self, chapter: int, *, decision: str = "pass") -> None:
        self.receipts[chapter] = {"reviewed_at": _iso(self.now),
                                  "review": {"review_decision": decision},
                                  "destination": str((self.project / "正文").resolve())}

    def _event(self, unique: str, created_at: datetime, *, cost_cny="0.12", metering="reported",
               price=_UNSET) -> None:
        price_value = {"currency": "CNY"} if price is _UNSET else price
        payload = {"id": unique, "created_at": _iso(created_at), "project": str(self.project.resolve()),
                   "chapter": 1, "stage": "draft", "model": "m", "status": "success",
                   "metering": metering, "input_tokens": 100, "output_tokens": 50,
                   "cost_cny": cost_cny, "price": price_value}
        db = costs.connection(self.ledger)
        try:
            db.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?,?)",
                       (payload["id"], payload["created_at"], payload["project"], 1, "draft", "m",
                        json.dumps(payload, ensure_ascii=False)))
            db.commit()
        finally:
            db.close()

    # --- 投影内容 ---------------------------------------------------------
    def test_projection_reads_markdown_bodies_written_by_the_writer(self):
        # 真实写作器落盘为 .md；投影只认 .txt 时会把已存稿误报成未保存。
        for chapter in (1, 2):
            (self.project / "正文" / f"第{chapter}章-潮声.md").write_text(
                f"第{chapter}章正文，林禾听见怀表，沈砚不知情。", encoding="utf-8")
            self._pass(chapter)
        self._write("run-md", self._record())
        result = run_report.project_run("daily", self.job, "run-md")
        self.assertEqual(result["tally"]["saved"], 2)
        self.assertEqual(result["tally"]["reviewed"], 2)
        self.assertEqual(result["decision"], "complete")

    def test_draft_run_reports_saved_and_reviewed_without_remote_delivery(self):
        self._body(1, "第一章正文，林禾听见怀表。")
        self._body(2, "第二章正文，沈砚仍不知含义。")
        self._pass(1)
        self._pass(2)
        self._write("run-a", self._record())
        result = run_report.project_run("daily", self.job, "run-a")
        self.assertEqual(result["publication_mode"], "draft_only")
        self.assertEqual(result["remote_state"], "not_applicable")
        self.assertEqual(result["tally"]["target"], 2)
        self.assertEqual(result["tally"]["saved"], 2)
        self.assertEqual(result["tally"]["reviewed"], 2)
        self.assertEqual(result["tally"]["published"], 0)
        self.assertEqual(result["decision"], "complete")
        self.assertTrue(all(c["state"] == "reviewed" for c in result["chapters"]))

    def test_draft_run_with_unreviewed_chapter_is_manual_with_next_action(self):
        self._body(1, "第一章正文。")
        self._body(2, "第二章正文但审查未过。")
        self._pass(1)
        record = self._record(status="needs_revision", cycle={
            "run_date": self.today, "slot": "08:00", "target_ids": [1, 2],
            "status": "needs_revision", "publication_mode": "draft_only",
            "draft_chapters": [{"chapter_id": 2, "body_saved": True, "review_passed": False,
                                "review_decision": "needs_revision", "issue": "第二章信息量不足"}]})
        self._write("run-b", record)
        result = run_report.project_run("daily", self.job, "run-b")
        self.assertEqual(result["decision"], "manual")
        self.assertIn("修订", result["decision_reason"])
        self.assertEqual(result["chapters"][1]["review_passed"], False)
        self.assertEqual(result["chapters"][1]["issue"], "第二章信息量不足")
        self.assertIn("open_chapters", [a["id"] for a in result["available_actions"]])

    def test_publish_run_with_remote_intent_requires_read_only_verification(self):
        self._body(1, "第一章正文。")
        self._pass(1)
        job = dict(self.job, publication_mode="publish_now")
        record = self._record(status="publish_failed", queued_before_publish=[1], publish_exit_code=7,
                              verification="platform_receipt_and_body_hash")
        record["cycle"]["publication_mode"] = "publish_now"
        self._write("run-c", record)
        result = run_report.project_run("daily", job, "run-c")
        self.assertEqual(result["decision"], "verify_only")
        self.assertIn("不重复提交", result["decision_reason"])

    def test_publish_run_never_submitted_can_retry_once(self):
        self._body(1, "第一章正文。")
        self._pass(1)
        job = dict(self.job, publication_mode="publish_now")
        record = self._record(status="partial", verification="platform_receipt_and_body_hash")
        record["cycle"]["publication_mode"] = "publish_now"
        self._write("run-d", record)
        result = run_report.project_run("daily", job, "run-d")
        self.assertEqual(result["decision"], "retry")
        self.assertEqual(result["available_actions"][0]["id"], "retry")

    def test_publish_run_fully_verified_is_complete(self):
        self._body(1, "第一章正文。")
        self._pass(1)
        job = dict(self.job, publication_mode="publish_now")
        record = self._record(status="success", target_ids=[1], verification="platform_receipt_and_body_hash")
        record["cycle"] = {"run_date": self.today, "slot": "08:00", "target_ids": [1],
                           "status": "success", "publication_mode": "publish_now"}
        self._write("run-e", record)
        with patch.object(scheduler, "_published_ids", return_value=[1]):
            result = run_report.project_run("daily", job, "run-e")
        self.assertEqual(result["decision"], "complete")
        self.assertEqual(result["tally"]["published"], 1)

    def test_running_record_only_offers_refresh(self):
        self._write("run-f", self._record(status="running", finished_at=None))
        result = run_report.project_run("daily", self.job, "run-f")
        self.assertEqual(result["decision"], "wait")
        self.assertEqual([a["id"] for a in result["available_actions"]], ["refresh"])

    def test_slot_label_uses_job_timezone(self):
        job = dict(self.job, timezone="America/New_York")
        record = self._record(run_date="2026-03-08", slot="2026-03-08@07:30")
        self._write("run-g", record)
        result = run_report.project_run("daily", job, "run-g")
        self.assertEqual(result["slot"]["timezone"], "America/New_York")
        self.assertEqual(result["slot"]["label"], "2026-03-08 07:30（America/New_York）")

    # --- 费用三分 ---------------------------------------------------------
    def test_cost_state_distinguishes_known_zero_and_unknown(self):
        self._write("run-h", self._record())
        costs.connection(self.ledger).close()
        self.assertEqual(run_report.project_run("daily", self.job, "run-h")["costs"]["state"], "zero")
        self._event("e1", self.now - timedelta(minutes=2))
        known = run_report.project_run("daily", self.job, "run-h")["costs"]
        self.assertEqual(known["state"], "known")
        self.assertEqual(known["known_cost_cny"], "0.12")
        self._event("e2", self.now - timedelta(minutes=1), cost_cny=None, metering="unknown", price=None)
        partial = run_report.project_run("daily", self.job, "run-h")["costs"]
        self.assertEqual(partial["state"], "partial")
        self.assertEqual(partial["missing"], 2)
        self.ledger.unlink()
        missing = run_report.project_run("daily", self.job, "run-h")["costs"]
        self.assertEqual(missing["state"], "unknown")
        self.assertIsNone(missing["known_cost_cny"])

    # --- 只读与防御 -------------------------------------------------------
    def test_rendering_never_starts_worker_or_writes_platform(self):
        self._body(1, "第一章正文。")
        self._write("run-i", self._record())
        boom = AssertionError("只读投影不得执行任何写操作")
        with patch.object(scheduler, "run_once", side_effect=boom), \
             patch.object(writer_runner, "generate_chapter", side_effect=boom), \
             patch.object(bridge, "stage_project", side_effect=boom), \
             patch.object(bridge, "run_publish", side_effect=boom), \
             patch.object(bridge, "sync_manifest", side_effect=boom):
            result = run_report.project_run("daily", self.job, "run-i")
        self.assertEqual(result["run_id"], "run-i")

    def test_list_runs_skips_corrupt_files_and_load_rejects_traversal(self):
        self._write("run-2", self._record(started_at=_iso(self.now)))
        self._write("run-1", self._record(started_at=_iso(self.now - timedelta(days=1))))
        folder = self.runs / bridge.safe_dir_name("daily")
        (folder / "broken.json").write_text("{not json", encoding="utf-8")
        items = run_report.list_runs("daily")
        self.assertEqual([item["run_id"] for item in items], ["run-2", "run-1"])
        with self.assertRaises(ValueError):
            run_report.load_run("daily", "../../etc/passwd")
        with self.assertRaises(KeyError):
            run_report.load_run("daily", "nope")

    def test_unknown_mode_keeps_legacy_publish_semantics(self):
        self._write("run-j", {"target_ids": [1], "status": "partial", "started_at": _iso(self.now)})
        result = run_report.project_run("daily", self.job, "run-j")
        self.assertEqual(result["publication_mode"], "publish_now")


if __name__ == "__main__":
    unittest.main()
