"""0.7.3 audit regressions exercise production parsers and orchestration."""
import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from integration import writer_runner as writer, bridge, quality_gate, quality_score, platform_schedule


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.dict(os.environ, {
            'NOVEL_HELPER_COST_DB': str(self.root / 'costs.sqlite3'),
            'NOVEL_HELPER_AI_CONFIG': str(self.root / 'ai.json'),
        }))

    def test_real_extraction_apply_and_post_save_orchestration(self):
        Executor, _ = writer._load_webnovel_services()
        project = self.root / 'book'
        project.mkdir()
        executor = Executor(project, object())
        executor._chat_json_with_retry = AsyncMock(return_value={
            'new_locations': [{'name': '城门', 'description': '守夜人递信的地方'}]})
        executor.sync_post_save_artifacts = AsyncMock(return_value={
            'rag_indexed': True, 'continuity_written': True})
        path = project / '.webnovel/writer_receipts.json'
        receipt = {}
        with patch('integration.memory_library.sync_chapter', new=AsyncMock(return_value={'status': 'synced'})):
            result = asyncio.run(writer._sync_committed_artifacts(
                executor, 1, '守夜人在城门递来封蜡信。', receipt, {'1': receipt}, path))
        self.assertEqual(result['entities']['status'], 'synced')
        self.assertTrue((project / '设定集/地点库/城门.md').is_file())
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['1']['post_save']['entities']['status'], 'synced')

    def test_negative_chinese_review_cannot_become_a_quality_pass(self):
        Executor, _ = writer._load_webnovel_services()
        executor = Executor(self.root, object())
        for verdict in ('不通过，需修改', '未通过', '通过但需修改'):
            raw = json.dumps({'verdict': verdict, 'scores': {k: 90 for k in ('setting', 'plot', 'character', 'prose', 'dialogue', 'style')}, 'issues': []}, ensure_ascii=False)
            text, decision, needs = executor._normalize_review_output(raw)
            review = {'success': True, 'raw_review': text, 'review_decision': decision,
                      'needs_revision': needs, 'quality': quality_score.compute(text)}
            self.assertEqual(decision, 'needs_revision')
            self.assertFalse(quality_gate.judge(review, config={})['quality_pass'])
        self.assertEqual(quality_score.extract({'verdict': '无需修改'})['verdict'], 'pass')

    def test_real_entity_transport_failure_retains_retry_classification(self):
        Executor, _ = writer._load_webnovel_services()
        ai = MagicMock()
        ai.chat = AsyncMock(side_effect=ConnectionError('fixture connection lost'))
        executor = Executor(self.root, ai)
        executor.sync_post_save_artifacts = AsyncMock(return_value={'rag_indexed':True,'continuity_written':True})
        receipt = {}
        with patch('integration.memory_library.sync_chapter', new=AsyncMock(return_value={'status':'synced'})):
            result = asyncio.run(writer._sync_committed_artifacts(executor,1,'城门下收到封蜡信。',receipt,
                {'1':receipt},self.root/'.webnovel/writer_receipts.json'))
        self.assertEqual(result['entities']['failure_kind'], 'transport')
        self.assertTrue(result['entities']['retryable'])

    def test_non_iso_schedule_date_is_normalized(self):
        value = platform_schedule.normalize_row({'chapter_id': '1', 'book_id': 'b', 'account': 'a',
            'state': 'scheduled', 'planned_at': '2026/11/26 08:00', 'content_sha256': 'a' * 64},
            platform='fanqie', account='a', book_id='b')
        self.assertIn('2026-11-26', value['planned_at'])

    def test_login_uses_default_playwright_cache_when_override_absent(self):
        from manager import worker
        playwright = MagicMock()
        browser = playwright.chromium.launch.return_value
        context = browser.new_context.return_value
        context.new_page.return_value.url = 'https://fanqienovel.com/main/writer/book-manage'
        context.new_page.return_value.locator.return_value.inner_text.return_value = '我的作品'
        context.storage_state.return_value = {'cookies': [{'name': 'session', 'value': 'fixture'}]}
        with patch.object(bridge, 'account_dir', return_value=self.root / 'account'), \
                patch.object(bridge, 'child_environment', return_value={}), \
                patch.object(bridge, 'runtime_lock', return_value=__import__('contextlib').nullcontext()), \
                patch('playwright.sync_api.sync_playwright') as factory, patch('sys.stdin', io.StringIO('\n')):
            factory.return_value.__enter__.return_value = playwright
            self.assertEqual(worker.login('fixture')['status'], 'logged_in')
        playwright.chromium.launch.assert_called_once_with(headless=False)


class StreamCompletion(unittest.IsolatedAsyncioTestCase):
    async def test_eof_requires_done_or_finish_reason(self):
        from aiohttp import web
        writer._load_webnovel_services()
        from services.ai_service import AIService
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'NOVEL_HELPER_COST_DB': str(Path(folder) / 'costs.sqlite3')}):
            for ending in ('', '\ndata: [DONE]', '\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}'):
                async def handler(request):
                    return web.Response(text='data: {"choices":[{"delta":{"content":"半句正文"}}]}\n' + ending,
                                        content_type='text/event-stream')
                app = web.Application()
                app.router.add_post('/v1/chat/completions', handler)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, '127.0.0.1', 0)
                await site.start()
                try:
                    service = AIService(base_url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}', api_key='', model='fixture')
                    service.max_retries = 1
                    parts = [part async for part in service.chat_stream([{'role': 'user', 'content': 'fixture'}])]
                    self.assertEqual(parts[0], '半句正文')
                    self.assertEqual(any('[ERROR]' in part for part in parts), not bool(ending))
                finally:
                    await runner.cleanup()
