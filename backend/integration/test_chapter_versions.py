"""M01 正文版本契约的隔离检查（固定数据，无模型、无网络）。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integration import chapter_versions as cv


def make_project(folder):
    project = Path(folder) / '小说项目'
    (project / '正文').mkdir(parents=True)
    (project / '.webnovel').mkdir(parents=True)
    return project


class LegacyReadTest(unittest.TestCase):
    def test_legacy_project_reads_without_rewriting(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            source = project / '正文' / '第1章-旧稿.md'
            source.write_text('旧稿第一行\n旧稿第二行\n', encoding='utf-8', newline='\n')
            before = source.read_bytes()

            read = cv.read_version(project, 1)
            self.assertEqual(read['text'], '旧稿第一行\n旧稿第二行\n')
            self.assertEqual(read['source'], 'disk')
            self.assertEqual(cv.list_versions(project, 1), [])
            self.assertEqual(cv.report_ref(project, 1)['reason'], 'no_version_record')

            added = cv.adopt_legacy(project, 1)
            self.assertEqual(len(added), 1)
            self.assertEqual(source.read_bytes(), before, '兼容登记不得改写当前正文')
            self.assertEqual(cv.current_version(project, 1)['sha256'], cv.raw_sha256(before))
            self.assertFalse(cv.report_ref(project, 1)['stale'])
            # 幂等：再登记不增加版本
            self.assertEqual(cv.adopt_legacy(project, 1), [])


class CommitTest(unittest.TestCase):
    def test_save_then_read_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = '第一章正文\n\n第二段。\n'
            record = cv.write_chapter(project, 1, text, op_id='op-new', title='开端', allow_new=True)
            self.assertEqual(record['state'], 'committed')

            path = cv.chapter_path(project, 1)
            self.assertEqual(path.name, '第1章-开端.md')
            self.assertEqual(path.read_text(encoding='utf-8'), text)

            read = cv.read_version(project, 1)
            self.assertEqual(read['text'], text)
            self.assertEqual(read['sha256'], cv.raw_sha256(text.encode('utf-8')))
            self.assertEqual(read['meta']['body_digest'], cv.body_digest(text))
            self.assertEqual(len(cv.list_versions(project, 1)), 1)

    def test_concurrent_modification_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, '原稿\n', op_id='op-a', title='开端', allow_new=True)
            stale = cv.file_sha256(cv.chapter_path(project, 1))

            # 模拟另一个写入者改了当前稿
            (project / '正文' / '第1章-开端.md').write_text('别人改过的稿\n', encoding='utf-8', newline='\n')
            candidate = cv.save_candidate(project, 1, '我的候选\n', base_sha256=stale)

            with self.assertRaises(cv.VersionConflict) as caught:
                cv.commit_candidate(project, 1, candidate['candidate_id'], op_id='op-b', expected_sha256=stale)
            self.assertIn('concurrent_modification', str(caught.exception))
            self.assertEqual((project / '正文' / '第1章-开端.md').read_text(encoding='utf-8'), '别人改过的稿\n')
            self.assertEqual(cv.current_version(project, 1)['sha256'], stale)

    def test_repeated_operation_does_not_add_a_version(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            first = cv.write_chapter(project, 1, '正文\n', op_id='op-same', title='开端', allow_new=True)
            second = cv.write_chapter(project, 1, '正文\n', op_id='op-same', title='开端', allow_new=True)
            self.assertEqual(first['content_sha256'], second['content_sha256'])
            self.assertEqual(len(cv.list_versions(project, 1)), 1)
            self.assertEqual(second['state'], 'committed')

            with self.assertRaises(cv.VersionConflict):
                cv.write_chapter(project, 1, '换了内容\n', op_id='op-same', title='开端', allow_new=True)

    def test_failed_write_leaves_nothing_current_and_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            with patch.object(cv, '_write_chapter_bytes', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    cv.write_chapter(project, 1, '候选正文\n', op_id='op-crash', title='开端', allow_new=True)

            self.assertIsNone(cv.chapter_path(project, 1))
            self.assertEqual(cv.list_versions(project, 1), [])
            prepared = json.loads((cv.store_root(project) / 'commits' / 'op-crash.json').read_text(encoding='utf-8'))
            self.assertNotEqual(prepared['state'], 'committed')

            recovered = cv.recover_pending(project)
            self.assertEqual([item['state'] for item in recovered], ['committed'])
            self.assertEqual(cv.chapter_path(project, 1).read_text(encoding='utf-8'), '候选正文\n')
            self.assertEqual(cv.current_version(project, 1)['source'], 'writer')

    def test_corrupt_object_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, '正文\n', op_id='op-x', title='开端', allow_new=True)
            sha = cv.current_version(project, 1)['sha256']
            (cv.store_root(project) / 'objects' / f'{sha}.txt').write_bytes(b'tampered')
            with self.assertRaises(cv.VersionCorrupt):
                cv.read_version(project, 1, sha)


class AdoptionAndRestoreTest(unittest.TestCase):
    def test_adoption_rollback_and_remigrate(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            source = project / '正文' / '第2章-旧稿.md'
            source.write_text('旧稿\n', encoding='utf-8', newline='\n')
            before = source.read_bytes()

            cv.adopt_legacy(project, 2)
            sha = cv.current_version(project, 2)['sha256']
            self.assertTrue((cv.store_root(project) / 'objects' / f'{sha}.txt').is_file())

            result = cv.prune_adopted(project, 2)
            self.assertEqual(result['removed'], 1)
            self.assertEqual(cv.list_versions(project, 2), [])
            self.assertFalse((cv.store_root(project) / 'objects' / f'{sha}.txt').exists())
            self.assertEqual(source.read_bytes(), before, '回滚不得触碰用户正文')

            re_added = cv.adopt_legacy(project, 2)
            self.assertEqual(len(re_added), 1)
            self.assertEqual(re_added[0]['sha256'], sha)

    def test_originals_are_referenced_by_digest_only(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            originals = project / '.webnovel' / 'originals'
            originals.mkdir(parents=True)
            (originals / 'abc.md').write_text('更早的稿子\n', encoding='utf-8', newline='\n')

            added = cv.adopt_originals(project)
            self.assertEqual(len(added), 1)
            self.assertEqual(cv.adopt_originals(project), [])
            hits = cv.find_by_body_digest(project, cv.body_digest('更早的稿子\n'))
            self.assertEqual([hit['chapter_id'] for hit in hits], [None])
            # 未归属原稿不进入任何章节的当前版本
            self.assertIsNone(cv.current_version(project, 1))

    def test_review_attempt_links_to_version_by_normalized_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            text = '正文内容\n'
            cv.write_chapter(project, 3, text, op_id='op-r', title='试炼', allow_new=True)
            attempts = project / '.webnovel' / 'review_attempts'
            attempts.mkdir(parents=True)
            (attempts / '0003-demo.json').write_text(json.dumps({
                'chapter_id': 3, 'reviewed_at': '2026-11-14T00:00:00Z',
                'body_sha256': cv.body_digest(text), 'review': {'review_decision': 'pass'},
            }, ensure_ascii=False), encoding='utf-8')

            linked = cv.link_review_attempts(project, 3)
            self.assertEqual(len(linked), 1)
            self.assertTrue(linked[0]['current'])
            self.assertEqual(linked[0]['version_id'], cv.current_version(project, 3)['sha256'])

    def test_restore_is_a_new_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = make_project(folder)
            cv.write_chapter(project, 1, '第一版\n', op_id='op-1', title='开端', allow_new=True)
            first = cv.current_version(project, 1)['sha256']
            cv.write_chapter(project, 1, '第二版\n', op_id='op-2', title='开端')
            self.assertEqual(len(cv.list_versions(project, 1)), 2)

            cv.restore_version(project, 1, first, op_id='op-3')
            self.assertEqual(cv.chapter_path(project, 1).read_text(encoding='utf-8'), '第一版\n')
            versions = cv.list_versions(project, 1)
            self.assertEqual(len(versions), 3)
            self.assertEqual(versions[-1]['source'], 'restored')
            self.assertEqual(versions[-1]['parent'], cv.raw_sha256('第二版\n'.encode('utf-8')))


if __name__ == '__main__':
    unittest.main()
