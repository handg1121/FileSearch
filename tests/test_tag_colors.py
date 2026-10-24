"""색상 마이그레이션·저장과 태그 바로 조회 범위를 검사해요."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from searcher.search_pipeline import SearchRequest, run
from tagger import storage
from tagger.colors import DEFAULT_TAG_COLOR
from tagger import search


class TagColorTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-color-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "cache.sqlite3"
        self.a = self.file("folder-a/문서.txt")
        self.b = self.file("folder-b/문서.pdf")
        self.c = self.file("folder-c/문서.txt")
        storage.attach_tags([self.a, self.b], ["중요"], db_path=self.db)
        storage.attach_tags([self.c], ["중요사항"], db_path=self.db)
        self.tag_id = next(tag.id for tag in storage.show_tag(self.db) if tag.name == "중요")

    def file(self, name):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("파일 본문", encoding="utf-8")
        return str(path)

    def lookup(self, **options):
        return run(SearchRequest(root=str(self.root/'없는폴더'), query="일치하지 않는 검색어",
                                 name_enabled=False, body_enabled=True, extensions={"hwp"},
                                 since=9999999999, tag_id=self.tag_id, cache_path=str(self.db)), **options)

    def test_default_red_and_color_change_preserve_identity_and_links(self):
        self.assertTrue(all(tag.color == DEFAULT_TAG_COLOR for tag in storage.show_tag(self.db)))
        before = storage.read_file_tags([self.a, self.b, self.c], self.db)
        storage.set_tag_color(self.tag_id, "#2563EB", self.db)
        again = storage.create_tag(" 중요 ", self.db)
        self.assertEqual((again.id, again.color), (self.tag_id, "#2563eb"))
        self.assertEqual(storage.read_file_tags([self.a, self.b, self.c], self.db), before)
        self.assertEqual(storage.show_tag(self.db, paths=[self.a])[0].color, "#2563eb")
        self.assertEqual(next(tag.color for tag in storage.show_tag(self.db) if tag.name == "중요사항"), DEFAULT_TAG_COLOR)

    def test_legacy_schema_migration_keeps_existing_tags_and_paths(self):
        before = storage.read_file_tags([self.a, self.b], self.db)
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("ALTER TABLE tags DROP COLUMN color")
            con.execute("PRAGMA user_version = 1")
        tags = storage.show_tag(self.db)
        self.assertTrue(all(tag.color == DEFAULT_TAG_COLOR for tag in tags))
        self.assertEqual(storage.read_file_tags([self.a, self.b], self.db), before)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_invalid_color_or_deleted_tag_does_not_change_other_tags(self):
        for color in ("red", "#fff", "#gg0000", "#11223344", "'; DROP TABLE tags; --"):
            with self.subTest(color=color), self.assertRaises(ValueError):
                storage.set_tag_color(self.tag_id, color, self.db)
        with self.assertRaises(ValueError):
            storage.set_tag_color(-1, "#112233", self.db)
        self.assertTrue(all(tag.color == DEFAULT_TAG_COLOR for tag in storage.show_tag(self.db)))

    def test_lookup_uses_exact_tag_id_and_ignores_search_conditions(self):
        with patch("searcher.search_pipeline.read_file_metadata", side_effect=AssertionError("No full scan")), \
             patch("searcher.search_pipeline.open_body_cache", side_effect=AssertionError("No body reads")):
            result = self.lookup()
        self.assertEqual({hit.path for hit in result.hits}, {self.a, self.b})
        self.assertEqual(result.tag_name, "중요")
        self.assertTrue(all(hit.folder == os.path.dirname(hit.path) for hit in result.hits))
        self.assertFalse(result.path_moves)
        self.assertFalse(result.errors)

    def test_missing_or_inaccessible_files_are_reported_without_deleting_tags(self):
        Path(self.b).unlink()
        real_metadata = search.metadata_for_path
        def denied(path):
            if path == self.a:
                raise PermissionError("접근 거부")
            return real_metadata(path)
        with patch.object(search, "metadata_for_path", side_effect=denied):
            result = self.lookup()
        self.assertEqual(result.missing, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.hits, [])
        self.assertEqual(storage.read_file_tags([self.a, self.b], self.db), {self.a: ("중요",), self.b: ("중요",)})

    def test_empty_tag_and_cancelled_lookup(self):
        empty = storage.create_tag("빈 태그", self.db)
        result = run(SearchRequest(str(self.root), tag_id=empty.id, cache_path=str(self.db)))
        self.assertEqual(result.tag_name, "빈 태그")
        self.assertEqual(result.hits, [])
        cancelled = self.lookup(should_stop=lambda: True)
        self.assertTrue(cancelled.cancelled)
        self.assertEqual(cancelled.hits, [])
        self.assertEqual(storage.read_tag_paths(self.tag_id, self.db)[0].file_count, 2)

    def test_deleted_tag_is_reported_as_error(self):
        storage.delete_tag([self.tag_id], self.db)
        with self.assertRaises(ValueError):
            self.lookup()


if __name__ == "__main__":
    unittest.main()
