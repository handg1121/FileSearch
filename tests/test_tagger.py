"""태그의 저장 범위·원자성·본문 캐시와의 공존을 실제 SQLite로 검사해요."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unicodedata
import unittest

from searcher.search_pipeline import SearchRequest, run
from tagger.storage import attach_tags, create_tag, delete_tag, detach_tags, read_file_tags, show_tag


class TaggerTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-tags-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "files"
        self.source.mkdir()
        self.db = self.root / "profile" / "body_cache.sqlite3"
        self.a = self.file("a/동일.txt")
        self.b = self.file("b/동일.txt")
        self.c = self.file("본문미지원.pdf")

    def file(self, name, text="본문 계약금"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def tags(self, paths=None):
        return show_tag(self.db, paths=paths)

    def read(self, *paths):
        return read_file_tags(paths, self.db)

    def search(self):
        return run(SearchRequest(root=str(self.source), query="계약금", name_enabled=False,
                                 body_enabled=True, cache_path=str(self.db)))

    def test_create_reuses_normalized_names_and_persists(self):
        first = create_tag("  한글 Tag  ", self.db)
        second = create_tag(unicodedata.normalize("NFD", "한글 TAG"), self.db)
        self.assertEqual(first, second)
        self.assertEqual(self.tags(), [first])
        self.assertEqual(first.name, "한글 Tag")

    def test_invalid_batch_does_not_create_or_attach_any_tags(self):
        for invalid in ("", "   ", "a,b", "a\nb", "a\x00b", "x" * 65):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ValueError):
                    attach_tags([self.a], ["정상", invalid], db_path=self.db)
        self.assertEqual(self.tags(), [])
        self.assertEqual(self.read(self.a)[self.a], ())

    def test_attach_multiple_files_and_tags_is_idempotent(self):
        count = attach_tags([self.a, self.b, self.a, self.c], ["계약서", "중요"], db_path=self.db)
        self.assertEqual(count, 6)
        existing = self.tags()[0]
        self.assertEqual(attach_tags([self.a, self.b, self.c], ["중요"], [existing.id], self.db), 0)
        self.assertTrue(all(tag.file_count == 3 for tag in self.tags()))
        self.assertEqual(self.read(self.c)[self.c], ("계약서", "중요"))

    def test_detach_affects_only_selected_files_and_keeps_definition(self):
        attach_tags([self.a, self.b], ["계약서", "중요"], db_path=self.db)
        contract = next(tag for tag in self.tags() if tag.name == "계약서")
        self.assertEqual(detach_tags([self.a], [contract.id], self.db), 1)
        self.assertEqual(self.read(self.a)[self.a], ("중요",))
        self.assertEqual(self.read(self.b)[self.b], ("계약서", "중요"))
        detach_tags([self.b], [contract.id], self.db)
        self.assertEqual(next(tag.file_count for tag in self.tags() if tag.id == contract.id), 0)
        self.assertEqual(detach_tags([self.a], [contract.id], self.db), 0)

    def test_delete_cascades_only_requested_tag_and_never_reuses_id(self):
        attach_tags([self.a, self.b], ["계약서", "중요"], db_path=self.db)
        contract = next(tag for tag in self.tags() if tag.name == "계약서")
        self.assertEqual(delete_tag([contract.id], self.db), 1)
        self.assertEqual(self.read(self.a, self.b), {self.a: ("중요",), self.b: ("중요",)})
        new = create_tag("새 태그", self.db)
        self.assertNotEqual(new.id, contract.id)
        with self.assertRaises(ValueError):
            attach_tags([self.a], ["미저장"], [contract.id], self.db)
        self.assertNotIn("미저장", [tag.name for tag in self.tags()])
        self.assertTrue(Path(self.a).is_file())

    def test_same_names_in_different_directories_are_distinct(self):
        attach_tags([self.a], ["a폴더"], db_path=self.db)
        self.assertEqual(self.read(self.a, self.b)[self.b], ())
        if os.name == "nt":
            self.assertEqual(attach_tags([self.a.upper()], ["a폴더"], db_path=self.db), 0)
            self.assertEqual(self.read(self.a.upper())[self.a.upper()], ("a폴더",))

    def test_literal_names_are_not_sql(self):
        names = ["<b>중요</b>", "R&D", "' OR 1=1 --", "%_*"]
        attach_tags([self.a], names, db_path=self.db)
        self.assertEqual(set(self.read(self.a)[self.a]), set(names))
        self.assertEqual(self.read(self.b)[self.b], ())

    def test_missing_file_rejects_entire_attachment(self):
        Path(self.b).unlink()
        with self.assertRaises(ValueError):
            attach_tags([self.a, self.b], ["새 태그"], db_path=self.db)
        self.assertEqual(self.tags(), [])

    def test_database_failure_rolls_back_new_tags_and_all_links(self):
        create_tag("기존", self.db)
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("""CREATE TRIGGER reject_pdf BEFORE INSERT ON file_tags
                WHEN NEW.path LIKE '%.pdf' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            attach_tags([self.a, self.c], ["새 태그"], db_path=self.db)
        self.assertEqual([tag.name for tag in self.tags()], ["기존"])
        self.assertEqual(self.read(self.a)[self.a], ())

    def test_large_selection_returns_union_and_correct_counts(self):
        paths = [self.file(f"bulk/{index}.txt") for index in range(305)]
        attach_tags(paths, ["공통"], db_path=self.db)
        attach_tags([paths[0]], ["첫 파일"], db_path=self.db)
        selected = self.tags(paths + paths[:2])
        self.assertEqual({tag.name: tag.file_count for tag in selected}, {"공통": 305, "첫 파일": 1})
        self.assertEqual(len(read_file_tags(paths, self.db)), 305)
        common = next(tag for tag in selected if tag.name == "공통")
        self.assertEqual(detach_tags(paths, [common.id], self.db), 305)
        self.assertEqual(self.read(paths[0])[paths[0]], ("첫 파일",))

    def test_tag_first_then_body_cache_refresh_and_cleanup_preserve_tags(self):
        attach_tags([self.a, self.c], ["보존"], db_path=self.db)
        self.assertEqual(self.search().refreshed, 2)
        Path(self.a).write_text("계약금 변경된 문서입니다", encoding="utf-8")
        self.assertEqual(self.search().refreshed, 1)
        Path(self.a).unlink()
        self.search()
        self.assertEqual(self.read(self.a, self.c), {self.a: ("보존",), self.c: ("보존",)})
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM body_cache").fetchone()[0], 1)
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_existing_body_cache_is_preserved_when_tag_schema_is_added(self):
        self.assertEqual(self.search().refreshed, 2)
        attach_tags([self.a], ["보존"], db_path=self.db)
        delete_tag([self.tags()[0].id], self.db)
        result = self.search()
        self.assertEqual(result.reused, 2)
        self.assertEqual(len(result.hits), 2)


if __name__ == "__main__":
    unittest.main()
