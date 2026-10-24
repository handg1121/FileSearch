"""태그명 SQLite 검색, 범위/필터, 본문 없는 검색과 OR 병합을 검증해요."""

from contextlib import closing
from itertools import product
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unicodedata
import unittest
from unittest.mock import patch

from searcher.metadata import SearchCancelled
from searcher.search_pipeline import SearchRequest, run
from tagger import storage
from tagger.search import search_keyword_tag


class TagKeywordSearchTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='filesearch-tag-query-', dir=os.environ.get('FILESEARCH_TEST_TEMP'))
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base/'source'
        self.root.mkdir()
        self.db = self.base/'cache.sqlite3'

    def file(self, name, body='관련 없는 본문', tags=()):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        if tags:
            storage.attach_tags([str(path)], tags, db_path=str(self.db))
        return path

    def search(self, query='계약', **options):
        options.setdefault('name_enabled', False)
        options.setdefault('tag_enabled', True)
        return run(SearchRequest(root=str(self.root), query=query, cache_path=str(self.db), **options))

    def paths(self, result):
        self.assertFalse(result.errors)
        return {Path(hit.path) for hit in result.hits}

    def test_partial_tag_search_never_reads_body_and_deduplicates(self):
        match = self.file('일반.pdf', tags=['계약서', '선급계약금'])
        self.file('계약_이름만.txt', body='계약 본문')
        with (patch('searcher.search_pipeline.open_body_cache', side_effect=AssertionError('No body cache')),
              patch('searcher.body_cache.extract_file_body', side_effect=AssertionError('No document reads'))):
            result = self.search()
        self.assertEqual(self.paths(result), {match})
        self.assertEqual(len(result.hits), 1)
        self.assertEqual((result.refreshed, result.reused, result.unsupported), (0, 0, 0))
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='body_cache'").fetchone())

    def test_all_checkbox_combinations_merge_without_losing_excerpt(self):
        name = self.file('계약_이름.txt')
        body = self.file('본문.txt', body='계약의 본문')
        tag = self.file('태그.pdf', tags=['계약서'])
        common = self.file('계약_공통.txt', body='계약 내용', tags=['계약'])
        self.file('무관.txt', tags=['중요'])
        for name_on, body_on, tag_on in product((False, True), repeat=3):
            if not any((name_on, body_on, tag_on)):
                continue
            with self.subTest(name=name_on, body=body_on, tag=tag_on):
                expected = {common}
                for enabled, path in ((name_on, name), (body_on, body), (tag_on, tag)):
                    if enabled:
                        expected.add(path)
                result = self.search(name_enabled=name_on, body_enabled=body_on, tag_enabled=tag_on)
                self.assertEqual(self.paths(result), expected)
                self.assertEqual(len(result.hits), len(expected))
                common_hit = next(hit for hit in result.hits if Path(hit.path) == common)
                self.assertEqual(bool(common_hit.body_excerpt), body_on)

    def test_scope_missing_paths_and_duplicate_file_names(self):
        first = self.file('a/같은이름.pdf', tags=['계약'])
        second = self.file('b/같은이름.pdf', tags=['계약'])
        gone = self.file('사라짐.pdf', tags=['계약'])
        gone.unlink()
        outside = self.base/'외부.pdf'
        outside.write_bytes(b'fixture')
        storage.attach_tags([str(outside)], ['계약'], db_path=str(self.db))
        self.assertEqual(self.paths(self.search()), {first, second})
        self.assertEqual(storage.show_tag(str(self.db))[0].file_count, 4)

    def test_type_and_date_filters_apply_to_tag_matches(self):
        recent = self.file('현재.pdf', tags=['계약'])
        old = self.file('예전.pdf', tags=['계약'])
        self.file('다른종류.txt', tags=['계약'])
        os.utime(old, (1000, 1000))
        self.assertEqual(self.paths(self.search(extensions={'pdf'}, since=2000)), {recent})

    def test_empty_query_lists_only_tagged_files(self):
        tagged = self.file('태그있음.txt', tags=['검토중'])
        self.file('태그없음.txt')
        for query in ('', '  '):
            self.assertEqual(self.paths(self.search(query)), {tagged})

    def test_unicode_casefold_and_phrase_matching(self):
        match = self.file('가.txt', tags=['한글 Straße 계약 검토'])
        self.file('나.txt', tags=['계약', '검토'])
        for query in ('STRASSE', unicodedata.normalize('NFD', '한글'), '계약 검토', '  계약 검토  '):
            self.assertEqual(self.paths(self.search(query)), {match})
        self.assertFalse(self.search('계약  검토').hits)

    def test_special_characters_are_literals(self):
        match = self.file('특수.pdf', tags=["100%_ * ' OR 1=1 --"])
        self.file('일반.pdf', tags=['일반 태그'])
        for query in ('%', '_', '*', "' OR 1=1 --"):
            self.assertEqual(self.paths(self.search(query)), {match})

    def test_large_candidate_list_is_chunked(self):
        paths = [self.file(f'{index:04d}.txt') for index in range(605)]
        storage.attach_tags([str(path) for path in paths], ['계약서'], db_path=str(self.db))
        self.assertEqual(self.paths(self.search()), set(paths))

    def test_cancel_during_tag_query_does_not_return_partial_hits(self):
        paths = [self.file(f'{index:04d}.txt') for index in range(305)]
        storage.attach_tags([str(path) for path in paths], ['계약'], db_path=str(self.db))
        stopped = False
        def progress(phase, done, total, path):
            nonlocal stopped
            if phase == '저장된 태그명 검색 중' and done >= 300:
                stopped = True
        result = run(SearchRequest(str(self.root), '계약', name_enabled=True, tag_enabled=True, cache_path=str(self.db)),
                     on_progress=progress, should_stop=lambda: stopped)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.hits)
        with self.assertRaises(SearchCancelled):
            search_keyword_tag(str(self.root), '계약', {}, str(self.db), should_stop=lambda: True)

    def test_disabled_branch_and_no_selection_validation(self):
        self.file('계약.txt')
        with patch('searcher.search_pipeline.search_keyword_tag', side_effect=AssertionError('Tag search disabled')):
            self.assertEqual(len(self.search(name_enabled=True, tag_enabled=False).hits), 1)
        with self.assertRaises(ValueError):
            self.search(name_enabled=False, body_enabled=False, tag_enabled=False)

    def test_query_database_error_is_reported(self):
        self.file('a.txt', tags=['계약'])
        with patch('tagger.search._connect', side_effect=sqlite3.OperationalError('database is locked')):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                self.search()

    def test_detach_and_deleted_tag_are_reflected_on_next_search(self):
        first = self.file('a.txt', tags=['계약'])
        second = self.file('b.txt', tags=['계약'])
        tag = storage.show_tag(str(self.db))[0]
        storage.detach_tags([str(first)], [tag.id], str(self.db))
        self.assertEqual(self.paths(self.search()), {second})
        storage.delete_tag([tag.id], str(self.db))
        self.assertFalse(self.search().hits)


if __name__ == '__main__':
    unittest.main()
