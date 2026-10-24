"""본문 검색·캐시 갱신·실패 복구를 실제 임시 파일과 SQLite로 검사해요."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import struct
from tempfile import TemporaryDirectory
import unicodedata
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from searcher import body_cache, body_extractors, metadata
from searcher.body_extractors import ExtractionError, extract_file_body, extract_hwp_section
from searcher.search_pipeline import SearchRequest, run


class BodySearchTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-body-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.db = self.root / "cache.sqlite3"

    def file(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def search(self, query="계약금", **options):
        options.setdefault("name_enabled", False)
        options.setdefault("body_enabled", True)
        options.setdefault("cache_path", str(self.db))
        options.setdefault("root", str(self.source))
        return run(SearchRequest(query=query, **options))

    def rows(self):
        with closing(sqlite3.connect(self.db)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM body_cache")]

    def test_substring_same_names_and_cache_reuse(self):
        self.file("a/문서.txt", "선급계약금을 지불한다")
        self.file("b/문서.txt", "계약금 지급")
        first = self.search()
        self.assertEqual(len(first.hits), 2)
        self.assertEqual(first.refreshed, 2)
        with patch.object(body_cache, "extract_file_body", side_effect=AssertionError("캐시를 써야 해요")):
            second = self.search()
        self.assertEqual(len(second.hits), 2)
        self.assertEqual(second.reused, 2)
        self.assertFalse(second.errors)

    def test_phrase_spaces_and_literal_special_characters(self):
        self.file("a.txt", "계약금을 지불한다 100%_ * ' OR 1=1 --")
        self.file("b.txt", "계약금을 나중에 지불한다 100percent")
        self.assertEqual(len(self.search("계약금을 지불한다").hits), 1)
        for query in ("100%_", "*", "' OR 1=1 --", " 100%"):
            with self.subTest(query=query):
                self.assertEqual(len(self.search(query).hits), 1)
        self.assertFalse(self.search("계약금을  지불한다").hits)

    def test_unicode_normalization_casefold_and_excerpt(self):
        self.file("a.txt", unicodedata.normalize("NFD", "한글") + " " + "Straße " * 100 + "계약금")
        self.assertEqual(len(self.search("한글").hits), 1)
        self.assertEqual(len(self.search("STRASSE").hits), 1)
        self.assertIn("계약금", self.search().hits[0].body_excerpt)

    def test_name_only_body_only_and_or_merge(self):
        self.file("계약금_이름.txt", "관련 없음")
        self.file("본문.txt", "계약금 지급")
        self.file("계약금_양쪽.txt", "계약금 지급")
        self.file("계약금_지원외.pdf", "계약금")
        with patch("searcher.search_pipeline.open_body_cache", side_effect=AssertionError("이름 검색은 DB 불필요")):
            named = self.search(name_enabled=True, body_enabled=False)
        self.assertEqual(len(named.hits), 3)
        body = self.search()
        self.assertEqual(len(body.hits), 2)
        self.assertEqual(body.unsupported, 1)
        both = self.search(name_enabled=True)
        self.assertEqual(len(both.hits), 4)
        self.assertTrue(next(hit for hit in both.hits if "양쪽" in hit.name).body_excerpt)

    def test_empty_body_is_ready_and_empty_query_lists_supported(self):
        self.file("empty.txt", "")
        self.file("full.txt", "내용")
        self.assertEqual(len(self.search("").hits), 2)
        self.assertTrue(all(row["status"] == "ready" for row in self.rows()))
        self.assertEqual(self.search("").reused, 2)

    def test_modified_date_and_size_both_trigger_refresh(self):
        path = self.file("a.txt", "old")
        self.search("old")
        stamp = path.stat().st_mtime_ns
        path.write_text("new", encoding="utf-8")
        os.utime(path, ns=(stamp + 1_000_000, stamp + 1_000_000))
        self.assertEqual(self.search("new").refreshed, 1)
        self.assertFalse(self.search("old").hits)
        stamp = path.stat().st_mtime_ns
        path.write_text("longer", encoding="utf-8")
        os.utime(path, ns=(stamp, stamp))
        self.assertEqual(self.search("longer").refreshed, 1)

    def test_changed_file_failure_never_searches_stale_text_and_retries(self):
        path = self.file("a.txt", "계약금")
        self.search()
        path.write_text("계약금 수정됨", encoding="utf-8")
        with patch.object(body_cache, "extract_file_body", side_effect=PermissionError("읽기 거부")):
            failed = self.search()
        self.assertFalse(failed.hits)
        self.assertEqual(len(failed.errors), 1)
        self.assertEqual(self.rows()[0]["status"], "error")
        self.assertIsNone(self.rows()[0]["body"])
        retried = self.search()
        self.assertEqual(retried.refreshed, 1)
        self.assertEqual(len(retried.hits), 1)

    def test_change_during_extraction_does_not_publish_inconsistent_cache(self):
        path = self.file("a.txt", "계약금")
        def change_during_read(filename, **kwargs):
            path.write_text("더 긴 새로운 본문", encoding="utf-8")
            return "계약금"
        with patch.object(body_cache, "extract_file_body", side_effect=change_during_read):
            result = self.search()
        self.assertFalse(result.hits)
        self.assertEqual(len(result.errors), 1)
        self.assertIsNone(self.rows()[0]["body"])
        self.assertEqual(len(self.search("새로운").hits), 1)

    def test_filters_do_not_cause_cache_deletion(self):
        path = self.file("a.txt", "계약금")
        self.search()
        for options in ({"extensions": {"hwp"}}, {"since": path.stat().st_mtime + 10}):
            with self.subTest(options=options):
                result = self.search(**options)
                self.assertFalse(result.hits)
                self.assertEqual(result.deleted, 0)
                self.assertEqual(len(self.rows()), 1)
        path.unlink()
        self.assertEqual(self.search(extensions={"hwp"}).deleted, 1)
        self.assertEqual(self.rows(), [])

    def test_roots_are_isolated_and_only_missing_files_are_deleted(self):
        first = self.file("a.txt", "계약금")
        other = self.root / "other"
        other.mkdir()
        (other / "a.txt").write_text("계약금", encoding="utf-8")
        self.search()
        self.search(root=str(other))
        first.unlink()
        self.assertEqual(self.search().deleted, 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.search(root=str(other)).hits), 1)

    def test_partial_folder_scan_never_purges_unseen_cache(self):
        self.file("private/a.txt", "계약금")
        self.file("visible.txt", "계약금")
        self.search()
        original = os.scandir
        def restricted(path):
            if Path(path).name == "private":
                raise PermissionError("폴더 접근 거부")
            return original(path)
        with patch.object(metadata.os, "scandir", side_effect=restricted):
            result = self.search()
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(result.deleted, 0)

    def test_cancellation_keeps_completed_cache_without_partial_results(self):
        self.file("a.txt", "계약금")
        self.file("b.txt", "계약금")
        stopped = False
        def progress(phase, done, total, path):
            nonlocal stopped
            if phase == "본문 읽는 중" and done == 1:
                stopped = True
        request = SearchRequest(str(self.source), "계약금", False, True, cache_path=str(self.db))
        result = run(request, on_progress=progress, should_stop=lambda: stopped)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.hits, [])
        self.assertEqual(len(self.rows()), 1)
        next_result = self.search()
        self.assertEqual((next_result.refreshed, next_result.reused), (1, 1))
        self.assertEqual(len(next_result.hits), 2)

    def test_cancellation_during_read_retries_pending_file(self):
        self.file("a.txt", "계약금")
        with patch.object(body_cache, "extract_file_body", side_effect=metadata.SearchCancelled):
            result = self.search()
        self.assertTrue(result.cancelled)
        self.assertEqual(self.rows()[0]["status"], "pending")
        self.assertEqual(self.search().refreshed, 1)

    def test_database_inside_source_is_not_a_search_candidate(self):
        self.db = self.source / "cache.sqlite3"
        self.file("a.txt", "계약금")
        self.search()
        result = self.search()
        self.assertEqual(result.unsupported, 0)
        self.assertEqual(len(result.hits), 1)

    def test_extractor_version_change_rebuilds_cache(self):
        self.file("a.txt", "계약금")
        self.search()
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE body_cache SET extractor_version = 0")
        self.assertEqual(self.search().refreshed, 1)

    def test_newer_database_is_not_modified(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaises(RuntimeError):
            self.search()
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_compare_is_pure_and_separates_all_states(self):
        paths = [self.file(f"{name}.txt", "계약금") for name in ("same", "changed", "retry", "deleted")]
        self.search()
        with closing(body_cache.open_body_cache(str(self.db))) as connection:
            cached = body_cache.read_sqlite_metadata(connection, str(self.source))
        paths[1].write_text("수정한 계약금", encoding="utf-8")
        paths[3].unlink()
        new = self.file("new.txt", "계약금")
        old = cached[metadata.path_key(paths[2])]
        cached[old.file.key] = metadata.CachedMetadata(old.file, "error", old.extractor_version)
        before = self.rows()
        changes = metadata.compare_metadata(metadata.read_file_metadata(str(self.source)), cached)
        self.assertEqual([item.path for item in changes.added], [str(new)])
        self.assertEqual([len(getattr(changes, name)) for name in ("modified", "retry", "unchanged", "deleted")], [1, 1, 1, 1])
        self.assertEqual(self.rows(), before)

    def test_missing_root_and_no_selection(self):
        result = self.search(root=str(self.root / "missing"))
        self.assertTrue(result.errors)
        with self.assertRaises(ValueError):
            self.search(name_enabled=False, body_enabled=False)

    def test_text_encodings_and_line_endings(self):
        for encoding in ("utf-8-sig", "utf-16", "cp949"):
            with self.subTest(encoding=encoding):
                path = self.source / f"{encoding}.txt"
                path.write_bytes("계약금\r\n다음 문단".encode(encoding))
                self.assertEqual(extract_file_body(path), "계약금\n다음 문단")

    def test_hwp_records_controls_nested_levels_and_extended_size(self):
        def record(text, level=0, extended=False):
            data = text if isinstance(text, bytes) else text.encode("utf-16-le")
            header = struct.pack("<I", 67 | level << 10 | (0xFFF if extended else len(data)) << 20)
            return header + (struct.pack("<I", len(data)) if extended else b"") + data
        inline_tab = b"\x09\x00" + b"\x00" * 14
        section = record("계약금\r") + record("표 안의 본문", 4, True)
        section += record("앞".encode("utf-16-le") + inline_tab + "뒤😀".encode("utf-16-le"))
        self.assertEqual(extract_hwp_section(section), "계약금\n표 안의 본문\n앞\t뒤😀")
        for malformed in (b"\x00", struct.pack("<I", 67 | 20 << 20), record(b"\x09\x00")):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ExtractionError):
                    extract_hwp_section(malformed)

    def test_hwpx_runs_tabs_sections_and_nested_table_text(self):
        path = self.source / "a.hwpx"
        def section(content):
            return ('<hs:sec xmlns:hs="section" xmlns:hp="paragraph">' + content + '</hs:sec>')
        with ZipFile(path, "w") as archive:
            archive.writestr("Contents/section10.xml", section('<hp:p><hp:run><hp:t>마지막</hp:t></hp:run></hp:p>'))
            archive.writestr("Contents/section2.xml", section('<hp:p><hp:run><hp:t>계약</hp:t></hp:run><hp:run><hp:t>금 앞<hp:tab/>뒤<hp:lineBreak/>다음</hp:t></hp:run></hp:p><hp:tbl><hp:p><hp:run><hp:t>표 본문</hp:t></hp:run></hp:p></hp:tbl>'))
        self.assertEqual(extract_file_body(path), "계약금 앞\t뒤\n다음\n표 본문\n마지막\n")
        self.assertEqual(len(self.search().hits), 1)

    def test_broken_documents_report_failure_and_do_not_stop_other_files(self):
        self.file("broken.hwp", "not ole")
        self.file("broken.hwpx", "not zip")
        self.file("good.txt", "계약금")
        result = self.search()
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(sum(row["status"] == "error" for row in self.rows()), 2)

    def test_hwpx_dtd_and_oversized_input_are_rejected(self):
        path = self.source / "dtd.hwpx"
        with ZipFile(path, "w") as archive:
            archive.writestr("Contents/section0.xml", '<!DOCTYPE sec [<!ENTITY value "text">]><sec><t>&value;</t></sec>')
        with self.assertRaises(ExtractionError):
            extract_file_body(path)
        path = self.file("big.txt", "too long")
        with patch.object(body_extractors, "MAX_STREAM_BYTES", 2):
            with self.assertRaises(ExtractionError):
                extract_file_body(path)


if __name__ == "__main__":
    unittest.main()
