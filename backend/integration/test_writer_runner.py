import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

try:
    from . import writer_runner as writer
    from . import chapter_versions as versions
except ImportError:
    import writer_runner as writer
    import chapter_versions as versions

PASS = {"success": True, "review_decision": "pass", "needs_revision": False,
        "quality": {"format": "json", "verdict": "pass", "issues": [], "not_applicable": [],
                    "scores": {"setting": 90, "plot": 90, "character": 90,
                               "prose": 90, "dialogue": 90, "style": 90}}}
REVISE = {"success": True, "review_decision": "needs_revision", "needs_revision": True,
          "raw_review": "修正时间线"}


async def stream(events):
    for event in events:
        yield json.dumps(event, ensure_ascii=False) if not isinstance(event, str) else event


class WriterRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=writer.COMBINED_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.enterContext(patch.dict(os.environ, {"NOVEL_HELPER_AI_CONFIG": str(self.project / "offline-ai.json"),"AI_API_KEY":"","AI_MODEL":""}))
        (self.project / ".webnovel").mkdir()
        (self.project / "正文").mkdir()
        (self.project / "大纲").mkdir()
        self.state = self.project / ".webnovel" / "state.json"
        self.state.write_text(json.dumps({"project_info": {"title": "隔离作品"},
                                          "progress": {"current_chapter": 0}, "keep": "原字段"}),
                              encoding="utf-8")
        (self.project / "大纲" / "卷一.md").write_text(
            "\n".join(f"## 第{i}章 标题{i}\n故事梗概。" for i in range(1, 15)), encoding="utf-8")
        self.executor = Mock()
        from integration import memory_library, character_state
        self.enterContext(patch.object(memory_library,"sync_chapter",AsyncMock(return_value={"status":"synced"})))
        self.executor._extract_chapter_entities = AsyncMock(return_value={"extraction": {}})
        self.executor._apply_extraction_results = AsyncMock(return_value={"success": True, "created": 0})
        self.executor.sync_post_save_artifacts = AsyncMock(
            return_value={"rag_indexed": True, "continuity_written": True})
        self.loader = self.enterContext(patch.object(writer, "_load_webnovel_services",
            side_effect=AssertionError("禁止加载真实 AI")))
        self.generator_patch = patch.object(writer, "_generate_and_review",
                                            new_callable=AsyncMock)
        self.generator = self.generator_patch.start()
        self.addCleanup(self.generator_patch.stop)
        self.generator.side_effect = self.generated

    async def generated(self, project, chapter, words, revisions, scenes=0):
        return {"content": f"第{chapter}章的正文，因果与时间线完整。",
                "review": dict(PASS), "revision_rounds": 0, "executor": self.executor}

    def generate(self, **kwargs):
        return writer.generate_chapter(self.project, **kwargs)

    def pipeline(self, events, reviews=None, polished=None):
        self.generator_patch.stop()
        executor = Mock()
        executor.execute_write_stream.side_effect = lambda *a, **k: stream(events)
        executor.execute_polish = AsyncMock(return_value=polished or {"success": True, "content": "修正后正文"})
        executor.execute_review = AsyncMock(side_effect=reviews or [dict(PASS)])
        self.loader.side_effect = None
        self.loader.return_value = (Mock(return_value=executor), lambda: object())
        return executor

    def test_dry_run_never_initializes_ai_or_writes(self):
        result = self.generate(dry_run=True)
        self.assertEqual((result["status"], result["chapter_id"], result["title"]),
                         ("would_generate", 1, "标题1"))
        self.loader.assert_not_called()
        self.generator.assert_not_called()
        self.assertEqual(list((self.project / "正文").iterdir()), [])
        self.assertFalse((self.project / ".webnovel" / "writer.lock").exists())

    def test_nested_and_legacy_progress_and_saved_body(self):
        self.state.write_text(json.dumps({"current_chapter": 2, "progress": {"current_chapter": 5}}),
                              encoding="utf-8")
        self.assertEqual(writer.next_chapter_id(self.project), 6)
        (self.project / "正文" / "第8章-已有.md").write_text("既有正文", encoding="utf-8")
        self.assertEqual(writer.next_chapter_id(self.project), 9)

    def test_invalid_numbers_and_corrupt_state_block_before_ai(self):
        for kwargs in ({"chapter_id": 0}, {"chapter_id": -1}, {"word_count": True},
                       {"max_revisions": -1}, {"chapter_id": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.generate(**kwargs)
        self.state.write_text("{破损", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.generate()
        self.generator.assert_not_called()
        self.assertEqual(self.state.read_text(encoding="utf-8"), "{破损")

    def test_commit_records_review_hash_and_both_progress_fields(self):
        result = self.generate()
        self.assertEqual(result["status"], "generated")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual((state["current_chapter"], state["progress"]["current_chapter"]), (1, 1))
        self.assertEqual(state["keep"], "原字段")
        self.assertIn(1, writer.reviewed_chapters(self.project))
        self.assertEqual(result["post_save"]["entities"]["status"], "synced")
        self.assertEqual(list(self.project.rglob("*.tmp")), [])

    def test_generated_body_commits_through_chapter_versions(self):
        """生成正文必须同时生成版本索引、版本列表、当前版本和绑定回执。"""
        result = self.generate()
        body = Path(result["destination"])
        payload = body.read_bytes()
        digest = writer.hashlib.sha256(payload).hexdigest()
        meta = versions.current_version(self.project, 1)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["source"], "writer_runner")
        self.assertEqual(meta["sha256"], digest)
        self.assertEqual(meta["content_sha256"], digest)
        self.assertEqual(meta["version_id"], result["version_id"])
        self.assertEqual(meta["title"], "标题1")
        self.assertEqual(versions.chapter_path(self.project, 1), body)
        self.assertEqual(versions.file_sha256(body), digest)
        index_entry = versions.load_index(self.project)["chapters"]["1"]
        self.assertEqual(index_entry["current"], digest)
        self.assertEqual(index_entry["current_version_id"], meta["version_id"])
        self.assertEqual([item["version_id"] for item in versions.list_versions(self.project, 1)],
                         [meta["version_id"]])
        self.assertTrue(versions.compare_current(self.project, 1, digest)["version_matches_disk"])
        receipt = json.loads((self.project / ".webnovel" / "writer_receipts.json").read_text(encoding="utf-8"))["1"]
        self.assertEqual(receipt["sha256"], digest)
        self.assertEqual(receipt["version_id"], meta["version_id"])
        self.assertEqual(receipt["destination"], str(body.resolve()))
        from integration import chapter_editor
        state = chapter_editor.chapter_state(self.project, 1)
        self.assertEqual(state["version_id"], meta["version_id"])
        self.assertEqual(state["version_source"], "writer_runner")
        self.assertEqual(state["content_sha256"], digest)
        self.assertEqual(state["review_state"]["current_version_id"], meta["version_id"])
        self.assertFalse(state["review_state"]["stale"])

    def test_repeated_generation_reuses_the_committed_version(self):
        first = self.generate()
        before = Path(first["destination"]).read_bytes()
        second = self.generate(chapter_id=1)
        self.assertEqual(second["status"], "recovered")
        self.assertEqual(second["destination"], first["destination"])
        self.generator.assert_awaited_once()
        self.assertEqual(Path(second["destination"]).read_bytes(), before)
        self.assertEqual([item["version_id"] for item in versions.list_versions(self.project, 1)],
                         [first["version_id"]])
        self.assertEqual(versions.current_version(self.project, 1)["version_id"], first["version_id"])

    def test_changed_or_duplicate_body_invalidates_receipt(self):
        result = self.generate()
        Path(result["destination"]).write_text("改动正文", encoding="utf-8")
        self.assertNotIn(1, writer.reviewed_chapters(self.project))
        with self.assertRaises(FileExistsError):
            self.generate(chapter_id=1)
        self.generator.assert_awaited_once()
        (self.project / "正文" / "第1章-同章.md").write_text("第二文件", encoding="utf-8")
        self.assertEqual(writer.reviewed_chapters(self.project), {})

    def test_post_save_failure_is_committed_and_retry_does_not_generate(self):
        self.executor.sync_post_save_artifacts.side_effect = RuntimeError("模拟索引失败")
        result = self.generate()
        self.assertEqual(result["post_save"]["status"], "failed")
        recovered = self.generate(chapter_id=1)
        self.assertEqual(recovered["status"], "recovered")
        self.generator.assert_awaited_once()
        self.executor.sync_post_save_artifacts.assert_awaited_once()

    def test_review_same_body_reuses_completed_source_artifacts(self):
        self.generate()
        self.executor.execute_review=AsyncMock(return_value=PASS)
        self.loader.side_effect=None
        self.loader.return_value=(Mock(return_value=self.executor),lambda:object())
        result=writer.review_existing_chapter(self.project,1)
        self.assertEqual(result['review_decision'],'pass')
        self.executor._extract_chapter_entities.assert_awaited_once()
        self.executor.sync_post_save_artifacts.assert_awaited_once()
        self.assertTrue(result['post_save']['entities']['reused'])

    def test_missing_continuity_directory_is_created_on_same_body_repair(self):
        self.generate()
        path=self.project/'.webnovel'/'writer_receipts.json'
        receipts=writer.strict_json(path,{})
        receipts['1']['post_save']['continuity_written']=False
        writer.atomic_json(path,receipts)
        self.executor.execute_review=AsyncMock(return_value=PASS)
        self.executor._generate_continuity_summary=AsyncMock(return_value='本章状态：主角已确认来电。')
        self.loader.side_effect=None
        self.loader.return_value=(Mock(return_value=self.executor),lambda:object())
        result=writer.review_existing_chapter(self.project,1)
        self.assertTrue(result['post_save']['continuity_written'])
        self.assertEqual((self.project/'正文'/'.continuity'/'第1章_状态.md').read_text(encoding='utf-8'),'本章状态：主角已确认来电。')
        self.executor.sync_post_save_artifacts.assert_awaited_once()

    def test_continuity_cooldown_keeps_saved_artifacts_and_is_retryable(self):
        from integration import studio
        from integration.failure_info import PostSaveIncomplete
        from integration.retry_budget import RecoveryDeferred

        self.generate()
        path = self.project / '.webnovel' / 'writer_receipts.json'
        receipts = writer.strict_json(path, {})
        receipts['1']['post_save']['continuity_written'] = False
        writer.atomic_json(path, receipts)
        self.executor._generate_continuity_summary = AsyncMock(
            side_effect=RecoveryDeferred('2026-10-22T12:30:00+08:00'))
        self.loader.side_effect = None
        self.loader.return_value = (Mock(return_value=self.executor), lambda: object())

        with self.assertRaises(PostSaveIncomplete) as caught:
            studio.sync_existing_artifacts(self.project, 1)

        self.assertEqual(caught.exception.failure_kind, 'recovery_cooldown')
        self.assertEqual(caught.exception.next_retry_at, '2026-10-22T12:30:00+08:00')
        saved = writer.strict_json(path, {})['1']['post_save']
        self.assertTrue(saved['rag_indexed'])
        self.assertFalse(saved['continuity_written'])
        self.assertEqual(saved['entities']['status'], 'synced')

    def test_progress_write_failure_recovers_same_chapter(self):
        with patch.object(writer, "_save_progress", side_effect=OSError("模拟状态写入失败")):
            with self.assertRaises(OSError):
                self.generate()
        self.assertIn(1, writer.reviewed_chapters(self.project))
        self.assertEqual(self.generate(chapter_id=1)["status"], "recovered")
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["current_chapter"], 1)
        self.generator.assert_awaited_once()

    def test_receipt_failure_never_points_at_an_uncommitted_body(self):
        """版本提交成功后回执写入失败：不留回执，但正文与版本必须自洽。"""
        with patch.object(writer, "atomic_json", side_effect=OSError("模拟审查记录写入失败")):
            with self.assertRaises(OSError):
                self.generate()
        bodies = list((self.project / "正文").glob("*.md"))
        self.assertEqual(len(bodies), 1)
        meta = versions.current_version(self.project, 1)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["sha256"], versions.file_sha256(bodies[0]))
        self.assertEqual(versions.load_index(self.project)["chapters"]["1"]["current"], meta["sha256"])
        receipts_path = self.project / ".webnovel" / "writer_receipts.json"
        self.assertFalse(receipts_path.exists())
        self.assertEqual(writer.reviewed_chapters(self.project), {})

    def test_version_commit_failure_leaves_no_body_or_receipt(self):
        """版本层提交失败时，正文与回执都不得出现，回执不能指向临时稿。"""
        with patch.object(versions, "commit_raw_bytes",
                          side_effect=versions.VersionConflict("simulated_commit_failure")):
            with self.assertRaises(versions.VersionConflict):
                self.generate()
        self.assertEqual(list((self.project / "正文").glob("*.md")), [])
        self.assertEqual(versions.list_versions(self.project, 1), [])
        self.assertIsNone(versions.current_version(self.project, 1))
        receipts_path = self.project / ".webnovel" / "writer_receipts.json"
        self.assertFalse(receipts_path.exists())

    def test_body_created_during_generation_is_not_overwritten(self):
        async def concurrent_write(*args):
            versions.commit_raw_bytes(
                self.project, 1, "保留原文".encode("utf-8"), title="他人保存",
                source="chapter_editor", allow_new=True, expect_absent=True)
            return await self.generated(*args)
        self.generator.side_effect = concurrent_write
        with self.assertRaises(FileExistsError):
            self.generate()
        body = self.project / "正文" / "第1章-他人保存.md"
        self.assertEqual(body.read_text(encoding="utf-8"), "保留原文")
        committed = versions.list_versions(self.project, 1)
        self.assertEqual(len(committed), 1)
        self.assertEqual(committed[0]["source"], "chapter_editor")
        self.assertEqual(versions.current_version(self.project, 1)["sha256"],
                         versions.file_sha256(body))
        self.assertEqual(writer.reviewed_chapters(self.project), {})

    def test_chapter_created_at_commit_boundary_is_not_overwritten(self):
        """expect_absent：章锁外出现的同名章必须让生成失败，而不是覆盖它。"""
        real_commit = versions.commit_raw_bytes

        def racing_commit(*args, **kwargs):
            (self.project / "正文" / "第1章-并发保存.md").write_text("并发正文", encoding="utf-8")
            return real_commit(*args, **kwargs)

        with patch.object(versions, "commit_raw_bytes", side_effect=racing_commit):
            with self.assertRaises(versions.VersionConflict):
                self.generate()
        self.assertEqual((self.project / "正文" / "第1章-并发保存.md").read_text(encoding="utf-8"),
                         "并发正文")
        self.assertEqual([path.name for path in (self.project / "正文").glob("*.md")],
                         ["第1章-并发保存.md"])
        self.assertEqual(versions.list_versions(self.project, 1), [])
        self.assertFalse((self.project / ".webnovel" / "writer_receipts.json").exists())

    def test_chapter_editor_lock_blocks_generated_body_publication(self):
        """发布点必须与工作台共用 chapter_editor 的章锁，而不是只持有 writer.lock。"""
        from integration import chapter_editor
        acquired, release = threading.Event(), threading.Event()

        def hold():
            with chapter_editor._locked(self.project, 1):
                acquired.set()
                release.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            self.assertTrue(acquired.wait(5))
            with self.assertRaises(chapter_editor.ChapterError) as caught:
                self.generate()
            self.assertEqual(caught.exception.code, "file_in_use_retry")
            self.assertEqual(list((self.project / "正文").glob("*.md")), [])
            self.assertEqual(versions.list_versions(self.project, 1), [])
            self.assertFalse((self.project / ".webnovel" / "writer_receipts.json").exists())
        finally:
            release.set()
            holder.join(5)
        self.assertFalse(holder.is_alive())

    def test_unclear_or_contradictory_review_cannot_be_saved(self):
        for review in ({"success": "true", "review_decision": "pass"},
                       {**PASS, "needs_revision": True}, {"success": True, "review_decision": "unknown"}):
            with self.subTest(review=review):
                self.generator.return_value = {"content": "正文", "review": review}
                self.generator.side_effect = None
                with self.assertRaises(RuntimeError):
                    self.generate()
        self.assertEqual(list((self.project / "正文").glob("*.md")), [])

    def test_stream_requires_explicit_success_and_final_content_review(self):
        base = [{"type": "content", "chunk": "正文"},
                {"type": "review", "result": dict(PASS)}]
        bad_tails = [[], [{"type": "done"}], [{"type": "done", "success": "true"}],
                     [{"type": "done", "success": True, "content": "未经审查的变化"}],
                     [{"type": "done", "success": True, "content": ""}],
                     [{"type": "done", "success": True}, {"type": "content", "chunk": "晚到"}]]
        for tail in bad_tails:
            with self.subTest(tail=tail):
                result = asyncio.run(writer._read_stream_result(stream(base + tail)))
                self.assertTrue(not result["success"] or result["review"] is None or result["errors"])

    def test_malformed_and_warning_events_fail_closed(self):
        for bad in ("invalid", "[]", {"type": "error", "level": "warning", "message": "守卫失败"}):
            result = asyncio.run(writer._read_stream_result(stream([
                bad, {"type": "content", "chunk": "正文"},
                {"type": "review", "result": dict(PASS)}, {"type": "done", "success": True}])))
            self.assertTrue(result["errors"])

    def test_revision_rechecks_exact_polished_body(self):
        executor = self.pipeline([{"type": "content", "chunk": "初稿"},
            {"type": "review", "result": dict(REVISE)}, {"type": "done", "success": True}])
        result = asyncio.run(writer._generate_and_review(self.project, 1, 100, 2))
        self.assertEqual((result["content"], result["revision_rounds"]), ("修正后正文", 1))
        executor.execute_review.assert_awaited_once_with(chapter_id=1, content="修正后正文")

    def test_revision_limit_blocks_unpassed_body(self):
        executor = self.pipeline([{"type": "content", "chunk": "初稿"},
            {"type": "review", "result": dict(REVISE)}, {"type": "done", "success": True}],
            reviews=[dict(REVISE)])
        result = asyncio.run(writer._generate_and_review(self.project, 1, 100, 1))
        executor.execute_polish.assert_awaited_once()
        self.assertTrue(result["human_review_required"])
        self.assertEqual(result["review"]["review_decision"], "needs_human_review")
        self.assertEqual(result["review"]["auto_review_count"], writer.MAX_AUTO_REVIEWS)

    def test_editorial_recovery_reuses_latest_polished_body_and_history(self):
        executor=self.pipeline([{'type':'content','chunk':'初稿'},
            {'type':'review','result':dict(REVISE)},{'type':'done','success':True}],reviews=[dict(REVISE)])
        result=asyncio.run(writer._generate_and_review(self.project,1,100,2))
        self.assertEqual(executor.execute_write_stream.call_count,1)
        self.assertEqual(executor.execute_review.await_count,1)
        self.assertEqual(executor.execute_polish.await_count,1)
        call=executor.execute_polish.await_args
        self.assertEqual(call.args[1],'初稿')
        self.assertEqual(call.kwargs['mode'],'targeted_fix')
        self.assertIn('历轮防回归',call.args[2])
        self.assertEqual(result['content'],'修正后正文')
        self.assertEqual(result['review']['review_decision'],'needs_human_review')
        self.assertTrue(result['review']['human_review_required'])

    def test_C_failure_preserves_checkpoint_error_class_and_resumes_without_B(self):
        from .failure_info import PolishIncomplete,details
        executor=self.pipeline([{'type':'content','chunk':'完整初稿'},
            {'type':'review','result':dict(REVISE)},{'type':'done','success':True}])
        executor.execute_polish=AsyncMock(return_value={'success':False,'error':'输出 Token 上限',
            'failure_kind':'model_output','retryable':True})
        with self.assertRaises(PolishIncomplete) as caught:
            asyncio.run(writer._generate_and_review(self.project,1,100,2))
        self.assertEqual(details(caught.exception)['failure_kind'],'model_output')
        saved=list((self.project/'.webnovel'/'draft_checkpoints').glob('*.json'))[0]
        self.assertEqual(writer.strict_json(saved,{})['revision_attempts'],1)
        self.assertEqual(writer.strict_json(saved,{})['polished'],'完整初稿')
        executor.execute_review=AsyncMock(side_effect=[dict(REVISE),dict(PASS)])
        executor.execute_polish=AsyncMock(return_value={'success':True,'content':'合格修订正文'})
        result=asyncio.run(writer._generate_and_review(self.project,1,100,2))
        self.assertEqual(result['content'],'合格修订正文')
        self.assertEqual(executor.execute_write_stream.call_count,1)
        self.assertEqual(writer.strict_json(saved,{})['revision_attempts'],2)

    def test_editorial_budget_persists_across_process_style_restarts(self):
        executor=self.pipeline([{'type':'content','chunk':'初稿'},
            {'type':'review','result':dict(REVISE)},{'type':'done','success':True}])
        executor.execute_review=AsyncMock(return_value=dict(REVISE))
        executor.execute_polish=AsyncMock(side_effect=lambda *a,**k:{'success':True,'content':a[1]+'改'})
        first=asyncio.run(writer._generate_and_review(self.project,1,100,3))
        self.assertEqual(first['review']['review_decision'],'needs_human_review')
        self.assertEqual(executor.execute_polish.await_count,1)
        self.assertEqual(executor.execute_review.await_count,1)
        second=asyncio.run(writer._generate_and_review(self.project,1,100,3))
        self.assertEqual(second['review']['review_decision'],'needs_human_review')
        self.assertEqual(executor.execute_polish.await_count,1)
        self.assertEqual(executor.execute_review.await_count,1)

    def test_editorial_budget_persists_across_new_executor_instance(self):
        """A fresh executor (process restart) must reuse the checkpoint budget."""
        first_executor = self.pipeline([{'type':'content','chunk':'初稿'},
            {'type':'review','result':dict(REVISE)},{'type':'done','success':True}])
        first_executor.execute_review = AsyncMock(return_value=dict(REVISE))
        first_executor.execute_polish = AsyncMock(side_effect=lambda *a,**k:{'success':True,'content':a[1]+'改'})
        first = asyncio.run(writer._generate_and_review(self.project,1,100,3))
        self.assertEqual(first['review']['review_decision'], 'needs_human_review')

        second_executor = self.pipeline([{'type':'content','chunk':'不应再写'},
            {'type':'review','result':dict(REVISE)},{'type':'done','success':True}])
        second_executor.execute_review = AsyncMock(return_value=dict(REVISE))
        second_executor.execute_polish = AsyncMock(side_effect=lambda *a,**k:{'success':True,'content':a[1]+'改'})
        second = asyncio.run(writer._generate_and_review(self.project,1,100,3))
        self.assertEqual(second['review']['review_decision'], 'needs_human_review')
        self.assertEqual(second_executor.execute_write_stream.call_count, 0)
        self.assertEqual(second_executor.execute_polish.await_count, 0)
        self.assertEqual(second_executor.execute_review.await_count, 0)

    def test_untyped_or_changed_checkpoint_never_enables_editorial_retry(self):
        from . import editorial_recovery as editorial
        path=self.project/'.webnovel'/'draft_checkpoints'/'0001-fixture.json'
        writer.atomic_json(path,{'chapter':1,'polished':'现稿','revision_attempts':1})
        pending=editorial.EditorialReviewPending(1,1,path,writer.body_digest('现稿'))
        self.assertTrue(editorial.can_retry(pending,self.project,1))
        self.assertFalse(editorial.can_retry(RuntimeError(str(pending)),self.project,1))
        self.assertFalse(editorial.can_retry(pending,self.project,2))
        writer.atomic_json(path,{'chapter':1,'polished':'已改变','revision_attempts':1})
        self.assertFalse(editorial.can_retry(pending,self.project,1))
        writer.atomic_json(path,[])
        self.assertFalse(editorial.can_retry(pending,self.project,1))

    def test_project_lock_blocks_simultaneous_writer(self):
        started, release = threading.Event(), threading.Event()
        async def slow(*args):
            started.set()
            if not release.wait(5):
                raise AssertionError("测试超时")
            return await self.generated(*args)
        self.generator.side_effect = slow
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.generate)
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaisesRegex(RuntimeError, "已有任务"):
                    self.generate()
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5)["chapter_id"], 1)
        self.generator.assert_awaited_once()

    def configure_existing_review(self, review=None):
        self.loader.side_effect = None
        self.executor.execute_review = AsyncMock(return_value=review or dict(PASS))
        self.loader.return_value = (Mock(return_value=self.executor), lambda: object())
        body = self.project / "正文" / "第1章-手写正文.md"
        body.write_bytes("# 第1章 手写正文\r\n完整的原文。\r\n".encode("utf-8"))
        return body

    def test_review_existing_preserves_bytes_and_syncs_receipt_progress_entities(self):
        body = self.configure_existing_review()
        before = body.read_bytes()
        result = writer.review_existing_chapter(self.project, 1)
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual(body.read_bytes(), before)
        self.assertIn(1, writer.reviewed_chapters(self.project))
        self.generator.assert_not_awaited()
        self.executor._apply_extraction_results.assert_awaited_once()
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["progress"]["current_chapter"], 1)

    def test_failed_existing_review_revokes_previous_pass_without_body_changes(self):
        body = self.configure_existing_review()
        writer.review_existing_chapter(self.project, 1)
        before = body.read_bytes()
        self.executor.execute_review.return_value = dict(REVISE)
        result = writer.review_existing_chapter(self.project, 1)
        self.assertEqual(result["status"], "review_failed")
        self.assertNotIn(1, writer.reviewed_chapters(self.project))
        self.assertEqual(body.read_bytes(), before)
        self.assertEqual(self.executor._apply_extraction_results.await_count, 1)

    def test_existing_review_detects_edit_during_review(self):
        body = self.configure_existing_review()
        async def edited(**kwargs):
            body.write_text("审查期间改动正文", encoding="utf-8")
            return dict(PASS)
        self.executor.execute_review.side_effect = edited
        with self.assertRaisesRegex(RuntimeError, "正文已改变"):
            writer.review_existing_chapter(self.project, 1)
        self.assertEqual(writer.reviewed_chapters(self.project), {})
        self.executor.sync_post_save_artifacts.assert_not_awaited()

    def test_existing_review_cli_and_no_rewrite_contract(self):
        body = self.configure_existing_review()
        with self.assertRaises(ValueError):
            writer.review_existing_chapter(self.project, 1, max_revisions=1)
        with patch("builtins.print"):
            self.assertEqual(writer.main(["--project", str(self.project), "--review-existing", "--chapter", "1"]), 0)
            self.executor.execute_review.return_value = dict(REVISE)
            self.assertEqual(writer.main(["--project", str(self.project), "--review-existing", "--chapter", "1"]), 2)

    def test_entity_sync_failure_is_visible_without_regeneration(self):
        self.executor._extract_chapter_entities.return_value = None
        result = self.generate()
        self.assertEqual(result["post_save"]["entities"]["status"], "failed")
        self.assertIn(1, writer.reviewed_chapters(self.project))
        self.generate(chapter_id=1)
        self.generator.assert_awaited_once()

    def test_os_lock_is_cross_process_and_released_on_termination(self):
        path = self.project / "process.lock"
        code = ("import sys,time; from pathlib import Path; "
                f"sys.path.insert(0,{str(writer.COMBINED_ROOT)!r}); "
                "from integration.writer_runner import file_lock; "
                f"ctx=file_lock(Path({str(path)!r})); ctx.__enter__(); "
                "print('locked',flush=True); time.sleep(30)")
        process = subprocess.Popen([sys.executable, "-B", "-c", code],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaises(RuntimeError):
                with writer.file_lock(path):
                    pass
        finally:
            process.terminate()
            process.communicate(timeout=5)
        with writer.file_lock(path):
            pass

    def test_ai_config_path_is_set_before_get_and_cache_refreshed(self):
        services = types.ModuleType("services")
        ai = types.ModuleType("services.ai_service")
        skills = types.ModuleType("services.skill_executor")
        skills.SkillExecutor = Mock()
        services.ai_service = ai
        target = self.project / "ai_config.json"
        target.write_text("{}", encoding="utf-8")
        seen = []
        ai._ai_service = object()
        def get():
            seen.append(ai.CONFIG_FILE)
            if ai._ai_service is None:
                ai._ai_service = object()
            return ai._ai_service
        ai.get_ai_service = get
        # Exercise the original loader without importing upstream or credentials.
        with patch.dict(sys.modules, {"services": services, "services.ai_service": ai,
                                     "services.skill_executor": skills}), \
             patch.dict(os.environ, {"NOVEL_HELPER_AI_CONFIG": str(target)}):
            original = self.loader_pure
            _, getter = original()
            first = getter()
            target.write_text('{"model":"fake"}', encoding="utf-8")
            second = getter()
            self.assertIsNot(first, second)
            self.assertEqual(seen, [target.resolve(), target.resolve()])

    loader_pure = staticmethod(writer._load_webnovel_services)


    def test_generated_body_commits_candidates_without_extra_model_call(self):
        """主链路：正文落盘后立即提交 D 候选，并且不再额外调一次共享记忆抽取。"""
        from integration import memory_library

        body = "第1章的正文，因果与时间线完整。"
        from integration import character_state
        character_state.upsert_person(self.project, name="阿岚")
        scored = dict(PASS, quality={"scores": {name: 90 for name in
                                               ("setting", "plot", "character", "prose", "dialogue", "style")}},
                      fact_candidates=[{"title": "时间线完整", "content": "本章时间线完整",
                                        "quote": "因果与时间线完整"}],
                      character_candidates=[{"kind": "knowledge", "person": "阿岚", "info": "时间线完整",
                                             "event": "核对", "quote": "因果与时间线完整"}])

        async def generated(project, chapter, words, revisions, scenes=0):
            return {"content": body, "review": scored, "revision_rounds": 0, "executor": self.executor}

        self.generator.side_effect = generated
        with patch.object(memory_library, "sync_chapter", AsyncMock(return_value={"status": "synced"})) as sync:
            result = self.generate()
        self.assertEqual(result["status"], "generated")
        receipts = json.loads((self.project / ".webnovel" / "writer_receipts.json").read_text(encoding="utf-8"))
        candidates = receipts["1"]["candidates"]["memory_library"]
        self.assertEqual(candidates["committed"], "committed")
        self.assertGreaterEqual(candidates["added"], 1)
        titles = [item["title"] for item in memory_library.read(self.project)["items"]]
        self.assertIn("时间线完整", titles)
        self.assertEqual(receipts["1"]["candidates"]["character_state"]["added"]["knowledge"], 1)
        self.assertEqual(len(character_state.read(self.project)["knowledge"]), 1)
        self.assertEqual(sync.await_count, 0)

class ChapterTitleUniquenessTests(unittest.TestCase):
    """Fanqie rejects a repeated chapter title with -3011; generation must not emit one."""

    def test_duplicate_title_gets_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "正文").mkdir()
            (root / "正文" / "第1章-同名.md").write_text(
                "# 第1章 同名\n\n正文\n", encoding="utf-8"
            )
            self.assertEqual(writer._unique_chapter_title(root, 2, "同名"), "同名（续）")
            self.assertEqual(writer._unique_chapter_title(root, 1, "同名"), "同名")

    def test_suffix_escalates_when_suffixed_title_also_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "正文").mkdir()
            for name in ("第1章-同名.md", "第2章-同名（续）.md"):
                (root / "正文" / name).write_text(
                    f"# {name.split('-')[0]} 同名\n\n正文\n", encoding="utf-8"
                )
            self.assertEqual(writer._unique_chapter_title(root, 3, "同名"), "同名（续2）")

    def test_heading_is_rewritten_to_the_unique_title(self):
        content = "# 第31章 写名字的人\n\n正文第一段。\n"
        self.assertEqual(
            writer._retitle_chapter_heading(content, 31, "写名字的人（续）"),
            "# 第31章 写名字的人（续）\n\n正文第一段。",
        )


if __name__ == "__main__":
    unittest.main()
