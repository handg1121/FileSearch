"""선택 파일만 태그를 바꾸고 다른 데이터와 트랜잭션을 보존하는지 검사해요."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unicodedata
import unittest

from searcher.search_pipeline import SearchRequest, run
from tagger import storage


class TagEditTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-edit-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "cache.sqlite3"
        self.a = self.file("a/계약서.txt")
        self.b = self.file("b/계약서.txt")
        self.c = self.file("c/다른파일.txt")
        storage.attach_tags([self.a, self.b], ["검토중"], db_path=self.db)
        storage.attach_tags([self.a, self.c], ["중요"], db_path=self.db)
        self.source = next(tag for tag in storage.show_tag(self.db) if tag.name == "검토중")
        storage.set_tag_color(self.source.id, "#2563eb", self.db)

    def file(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("본문 계약금", encoding="utf-8")
        return str(path)

    def read(self):
        return {path: set(names) for path, names in storage.read_file_tags([self.a, self.b, self.c], self.db).items()}

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as con:
            return tuple(tuple(con.execute(f"SELECT * FROM {table} ORDER BY 1, 2")) for table in ("tags", "file_tags", "tracked_files"))

    def edit(self, name, paths, **kwargs):
        return storage.edit_tag(self.source.id, name, paths, self.db, **kwargs)

    def test_partial_edit_keeps_unselected_other_tags_and_source_color(self):
        result = self.edit("검토완료", [self.a, self.a])
        self.assertEqual(self.read(), {self.a: {"검토완료", "중요"}, self.b: {"검토중"}, self.c: {"중요"}})
        self.assertNotEqual(result.tag.id, self.source.id)
        self.assertEqual((result.changed_files, result.source_retained, result.tag.color), (1, True, "#2563eb"))
        self.assertEqual(storage.read_tag_paths(self.source.id, self.db)[1], [self.b])

    def test_all_selected_renames_same_tag_and_keeps_color(self):
        result = self.edit("완료", [self.a, self.b])
        self.assertEqual((result.tag.id, result.tag.file_count, result.tag.color), (self.source.id, 2, "#2563eb"))
        self.assertTrue(result.source_retained)
        self.assertEqual(self.read()[self.a], {"완료", "중요"})
        self.assertEqual(self.read()[self.b], {"완료"})
        self.assertNotIn("검토중", [tag.name for tag in storage.show_tag(self.db)])

    def test_partial_merge_existing_reuses_color_and_deduplicates(self):
        target = next(tag for tag in storage.show_tag(self.db) if tag.name == "중요")
        storage.set_tag_color(target.id, "#16a34a", self.db)
        result = self.edit("중요", [self.a])
        self.assertEqual((result.tag.id, result.tag.file_count, result.tag.color), (target.id, 2, "#16a34a"))
        self.assertEqual(self.read()[self.a], {"중요"})
        self.assertEqual(self.read()[self.b], {"검토중"})
        self.assertTrue(result.source_retained)

    def test_all_merge_removes_old_definition_preserves_target_links(self):
        result = self.edit("중요", [self.a, self.b])
        self.assertFalse(result.source_retained)
        self.assertEqual(result.tag.file_count, 3)
        self.assertEqual([tag.name for tag in storage.show_tag(self.db)], ["중요"])
        self.assertTrue(all(names == {"중요"} for names in self.read().values()))

    def test_empty_tag_rename_and_merge(self):
        empty = storage.create_tag("빈 태그", self.db)
        renamed = storage.edit_tag(empty.id, "빈 태그 수정", [], self.db)
        self.assertEqual(renamed.tag.id, empty.id)
        self.assertEqual(renamed.changed_files, 0)
        before = self.read()
        merged = storage.edit_tag(empty.id, "중요", [], self.db)
        self.assertFalse(merged.source_retained)
        self.assertEqual(self.read(), before)

    def test_invalid_unchanged_or_empty_selection_is_noop(self):
        before = self.snapshot()
        for name, paths in [("", [self.a]), ("a,b", [self.a]), ("x" * 65, [self.a]),
                            ("검토중", [self.a]), (" 검토중 ", [self.a]), ("완료", [])]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.edit(name, paths)
            self.assertEqual(self.snapshot(), before)

    def test_deleted_source_or_stale_name_is_rejected(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.edit("완료", [self.a], expected_name="변경된 이름")
        self.assertEqual(self.snapshot(), before)
        storage.delete_tag([self.source.id], self.db)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.edit("완료", [self.a])
        self.assertEqual(self.snapshot(), before)

    def test_removed_or_unrelated_selected_link_rejects_whole_edit(self):
        storage.detach_tags([self.b], [self.source.id], self.db)
        before = self.snapshot()
        for paths in ([self.a, self.b], [self.a, self.c]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.edit("완료", paths)
            self.assertEqual(self.snapshot(), before)

    def test_link_added_after_open_stays_unselected(self):
        old_selection = storage.read_tag_paths(self.source.id, self.db)[1]
        storage.attach_tags([self.c], [], [self.source.id], self.db)
        result = self.edit("완료", old_selection, expected_name="검토중")
        self.assertNotEqual(result.tag.id, self.source.id)
        self.assertEqual(self.read()[self.c], {"검토중", "중요"})

    def test_missing_physical_file_can_still_have_registered_tag_edited(self):
        Path(self.a).unlink()
        result = self.edit("보관", [self.a])
        self.assertEqual(result.changed_files, 1)
        self.assertEqual(self.read()[self.a], {"보관", "중요"})
        self.assertFalse(Path(self.a).exists())

    def test_case_only_requires_all_files(self):
        source = storage.create_tag("Draft", self.db)
        storage.attach_tags([self.a, self.b], [], [source.id], self.db)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            storage.edit_tag(source.id, "DRAFT", [self.a], self.db)
        self.assertEqual(self.snapshot(), before)
        result = storage.edit_tag(source.id, "DRAFT", [self.a, self.b], self.db)
        self.assertEqual((result.tag.id, result.tag.name), (source.id, "DRAFT"))

    def test_normalized_target_and_literal_sql_characters(self):
        target = storage.create_tag("완료 TAG", self.db)
        result = self.edit("  " + unicodedata.normalize("NFD", "완료 tag") + " ", [self.a])
        self.assertEqual(result.tag.id, target.id)
        literal = "완료'; DROP TABLE tags; --"
        result = self.edit(literal, [self.b])
        self.assertEqual(result.tag.name, literal)
        self.assertIn("중요", [tag.name for tag in storage.show_tag(self.db)])

    def test_db_error_rolls_back_new_definition_and_links(self):
        before = self.snapshot()
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute(f"""CREATE TRIGGER fail_edit BEFORE DELETE ON file_tags
                            WHEN OLD.tag_id = {self.source.id}
                            BEGIN SELECT RAISE(ABORT, 'test edit failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.edit("완료", [self.a])
        self.assertEqual(self.snapshot(), before)

    def test_file_body_and_metadata_unchanged_and_search_uses_new_tag(self):
        request = SearchRequest(str(self.root), "계약금", name_enabled=False, body_enabled=True, cache_path=str(self.db))
        self.assertEqual(len(run(request).hits), 3)
        def metadata():
            with closing(sqlite3.connect(self.db)) as con:
                return (list(con.execute("SELECT * FROM body_cache ORDER BY 1")),
                        list(con.execute("SELECT * FROM tracked_files ORDER BY 1")))
        before_db = metadata()
        before_files = [(Path(p).read_bytes(), Path(p).stat().st_mtime_ns) for p in (self.a, self.b, self.c)]
        self.edit("최종계약서", [self.a])
        self.assertEqual(metadata(), before_db)
        self.assertEqual([(Path(p).read_bytes(), Path(p).stat().st_mtime_ns) for p in (self.a, self.b, self.c)], before_files)
        result = run(SearchRequest(str(self.root), "최종", name_enabled=False, tag_enabled=True, cache_path=str(self.db)))
        self.assertEqual([hit.path for hit in result.hits], [self.a])

    def test_windows_path_case_is_same_file(self):
        if os.name != "nt":
            self.skipTest("Windows path normalization")
        result = self.edit("완료", [self.a.upper(), self.a])
        self.assertEqual(result.changed_files, 1)
        self.assertEqual(self.read()[self.b], {"검토중"})


if __name__ == "__main__":
    unittest.main()
