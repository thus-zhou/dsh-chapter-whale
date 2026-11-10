import asyncio
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch
from integration import writer_runner, memory_library, free_pool


class ReleaseRegression(unittest.TestCase):
    def test_entity_names_reject_windows_escape(self):
        writer_runner._load_webnovel_services()
        from services.skill_executor import SkillExecutor
        executor = object.__new__(SkillExecutor)
        for name in ['C:outside', 'CON', 'LPT1.txt', '../outside', 'a\\b', 'name\x00']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                executor._normalize_entity_name(name)
        self.assertEqual(executor._normalize_entity_name('守灯人'), '守灯人')

    def test_failed_entity_write_never_becomes_synced(self):
        class Executor:
            ai_service = None
            _extract_chapter_entities = AsyncMock(return_value={'extraction': {}})
            _apply_extraction_results = AsyncMock(return_value={'success': False})
            sync_post_save_artifacts = AsyncMock(return_value={'rag_indexed': True})
        with tempfile.TemporaryDirectory() as folder, patch.object(memory_library, 'sync_chapter', AsyncMock(return_value={'status': 'synced'})):
            path = Path(folder)/'.webnovel'/'receipts.json'
            result = asyncio.run(writer_runner._sync_committed_artifacts(Executor(), 1, '验收正文', {}, {}, path))
            self.assertEqual(result['entities']['status'], 'failed')

    def test_free_pool_forwards_and_restores_thinking_scope(self):
        states=[]
        class Client:
            @contextmanager
            def without_thinking(self):
                states.append('enter')
                try: yield
                finally: states.append('exit')
            async def chat(self, messages, **kwargs):
                states.append('request')
                return 'test'
        pool = free_pool.FreePoolClient('E', {'providers': {'free-pool': {'base_url': 'http://127.0.0.1:1'}}}, lambda row: Client())
        with patch.object(pool, '_choices', return_value=('project', [{'model_id': 'test/model'}])), patch.object(pool, '_client', return_value=Client()), patch.object(free_pool, 'recovered'):
            with pool.without_thinking():
                self.assertEqual(asyncio.run(pool.chat([])), 'test')
            self.assertFalse(pool._thinking_disabled.get())
        self.assertEqual(states, ['enter', 'request', 'exit'])

    def test_legacy_confirmation_is_not_unattended(self):
        from integration import scheduler
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scheduler.json'
            path.write_text('{"jobs":{"old":{"approval_mode":"confirm_24h","enabled":true}}}',encoding='utf-8')
            with patch.object(scheduler, 'SCHEDULER_PATH', path):
                job = scheduler._read_scheduler()['jobs']['old']
                self.assertFalse(job['enabled'])
                self.assertEqual(job['approval_mode'], 'confirm_24h')
                self.assertIsNotNone(scheduler._check_approval(job, '2026-11-10'))


if __name__ == '__main__':
    unittest.main()
