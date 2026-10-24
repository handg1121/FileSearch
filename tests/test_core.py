"""복원 후 추가한 회귀 테스트. 모든 파일 작업은 임시 폴더에서 수행해요."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
import unittest
from unittest.mock import patch

from collector import type_selector_script as core
from common import settings
from searcher import filename_search as search


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="filesearch-recovery-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.source.mkdir()
        self.target.mkdir()

    def file(self, relative, data=b"sample data", base=None):
        path = (base or self.source) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def item(self, path, name=None):
        return core.FileItem(str(path), path.stat().st_size, str(self.target / (name or path.name)))

    def records(self):
        return [json.loads(line) for line in Path(core.journal_path(str(self.target))).read_text(encoding="utf-8").splitlines()]

    def test_unicode_keywords_and_dates(self):
        self.assertEqual(search.normalize("한글"), "한글")
        self.assertEqual(search.parse_keywords("  계약 ABC  "), ["계약", "abc"])
        self.assertTrue(search.matches_name("ABC_계약서.pdf", ["계약", "abc"]))
        self.assertFalse(search.matches_name("ABC.pdf", ["계약", "abc"]))
        now = datetime(2026, 10, 24, 15, 30)
        self.assertEqual(search.modified_since("오늘", now), datetime(2026, 10, 24).timestamp())
        self.assertEqual(search.modified_since("최근 7일", now), datetime(2026, 10, 17, 15, 30).timestamp())
        self.assertEqual(search.modified_since("올해", now), datetime(2026, 1, 1).timestamp())
        self.assertIsNone(search.modified_since("전체 기간", now))

    def test_search_filters_subfolders_and_work_files(self):
        a = self.file("sub/계약 ABC.PDF")
        self.file("계약 ABC.txt")
        old = self.file("오래된 계약 ABC.pdf")
        os.utime(old, (1, 1))
        self.file(core.JOURNAL_NAME)
        self.file("계약 ABC.pdf.part")
        hits = search.search_by_name(str(self.source), ["계약", "abc"], {"pdf"}, since=100)
        self.assertEqual([hit.path for hit in hits], [str(a)])
        self.assertEqual(hits[0].folder, "sub")
        self.assertEqual(len(search.search_by_name(str(self.source), [])), 3)

    def test_sort_orders(self):
        hits = [search.SearchHit("a", "z", "", 1, 10), search.SearchHit("b", "a", "", 3, 20)]
        self.assertEqual(search.sort_hits(hits, "이름순")[0].name, "a")
        self.assertEqual(search.sort_hits(hits, "수정일 오래된순")[0].modified, 10)
        self.assertEqual(search.sort_hits(hits, "수정일 최신순")[0].modified, 20)
        self.assertEqual(search.sort_hits(hits, "크기순")[0].size, 3)

    def test_scan_nested_excluded_and_overlapping_sources(self):
        self.file("top.txt")
        self.file("sub/nested.txt")
        self.file("~$office.txt")
        self.file("photo.png")
        excluded = self.source / "saved"
        self.file("previous.txt", base=excluded)
        reports = []
        items = core.scan_files([str(self.source), str(self.source / "sub")], ["TXT"], str(excluded),
                                on_folder=lambda folder, found: reports.append((folder, found)))
        self.assertEqual({Path(i.src).name for i in items}, {"top.txt", "nested.txt"})
        self.assertEqual(len(items), 2)
        self.assertTrue(reports)
        flat = core.scan_files([str(self.source)], ["txt"], str(excluded), include_subfolders=False)
        self.assertEqual([Path(i.src).name for i in flat], ["top.txt"])

    def test_scan_cancel_and_inaccessible_directory(self):
        self.file("a.txt")
        self.assertEqual(core.scan_files([str(self.source)], ["txt"], str(self.target), should_stop=lambda: True), [])
        with patch.object(core.os, "scandir", side_effect=PermissionError("denied")):
            self.assertEqual(core.scan_files([str(self.source)], ["txt"], str(self.target)), [])

    def test_windows_target_paths(self):
        with patch.object(core, "drive_folder_name", return_value="E_USB"):
            self.assertEqual(core.make_target_path(r"E:\자료\보고서.hwp", r"C:\모음"), r"C:\모음\E_USB\자료\보고서.hwp")
        self.assertEqual(core.drive_folder_name(r"\\server\share"), "server_share")
        self.assertTrue(core.is_inside_any(r"C:\Target\sub", [r"c:\target"]))
        self.assertFalse(core.is_inside_any(r"C:\Target2", [r"c:\target"]))

    def test_duplicate_names_reserve_part_files(self):
        path = self.file("보고서.txt", base=self.target)
        self.file("보고서_중복1.txt.part", base=self.target)
        self.assertEqual(core.resolve_duplicate(str(path)), str(self.target / "보고서_중복2.txt"))

    def test_copy_atomic_content_and_no_overwrite(self):
        src = self.file("binary.bin", bytes(range(256)) * 100)
        dst = self.target / "sub" / src.name
        core.copy_file_atomic(str(src), str(dst))
        self.assertEqual(hashlib.sha256(src.read_bytes()).digest(), hashlib.sha256(dst.read_bytes()).digest())
        self.assertFalse(Path(str(dst) + core.PART_SUFFIX).exists())
        with self.assertRaises(OSError):
            core.copy_file_atomic(str(src), str(dst))
        self.assertTrue(src.exists())
        self.assertEqual(dst.read_bytes(), src.read_bytes())

    def test_copy_failure_removes_partial_file(self):
        src = self.file("a.txt")
        dst = str(self.target / "a.txt")
        def fail_copy(source, destination):
            Path(destination).write_bytes(b"partial")
            raise OSError("simulated disk error")
        with patch.object(core.shutil, "copy2", side_effect=fail_copy):
            with self.assertRaises(OSError):
                core.copy_file_atomic(str(src), dst)
        self.assertTrue(src.exists())
        self.assertFalse(Path(dst).exists())
        self.assertFalse(Path(dst + core.PART_SUFFIX).exists())

    def test_same_drive_move(self):
        src = self.file("move.txt", b"move data")
        dst = self.target / "deep" / "move.txt"
        core.move_file(str(src), str(dst))
        self.assertFalse(src.exists())
        self.assertEqual(dst.read_bytes(), b"move data")

    def test_cross_drive_branch_and_source_delete_failure(self):
        # 두 드라이브가 없는 환경에서도 다른 드라이브 분기를 확인해요.
        src = self.file("cross.txt", b"cross data")
        dst = self.target / "cross.txt"
        with patch.object(core, "drive_of", side_effect=lambda p: "C:" if p == str(src) else "D:"):
            core.move_file(str(src), str(dst))
        self.assertFalse(src.exists())
        self.assertEqual(dst.read_bytes(), b"cross data")
        src = self.file("kept.txt", b"keep me")
        dst = self.target / "kept.txt"
        with patch.object(core, "drive_of", side_effect=lambda p: "C:" if p == str(src) else "D:"), \
             patch.object(core.os, "remove", side_effect=PermissionError("locked")):
            with self.assertRaises(core.SourceKeptError):
                core.move_file(str(src), str(dst))
        self.assertTrue(src.exists())
        self.assertEqual(dst.read_bytes(), src.read_bytes())

    def test_space_accounts_for_copy_and_move(self):
        items = [core.FileItem(r"C:\one", 10, ""), core.FileItem(r"D:\two", 20, "")]
        with patch.object(core.shutil, "disk_usage") as usage:
            usage.return_value.free = core.SAFETY_MARGIN + 25
            copy = core.check_space(items, r"C:\target", core.MODE_COPY)
            move = core.check_space(items, r"C:\target", core.MODE_MOVE)
        self.assertEqual(copy.needed, 30)
        self.assertFalse(copy.enough)
        self.assertEqual(move.needed, 20)
        self.assertTrue(move.enough)

    def test_collect_copy_duplicates_failure_and_journal(self):
        a = self.file("a.txt", b"a")
        b = self.file("b.txt", b"b")
        self.file("same.txt", b"keep original", base=self.target)
        items = [self.item(a, "same.txt"), self.item(b, "same.txt"),
                 core.FileItem(str(self.source / "missing.txt"), 0, str(self.target / "missing.txt"))]
        progress = []
        result = core.run_collect(items, str(self.target), core.MODE_COPY,
                                  on_progress=lambda *values: progress.append(values))
        self.assertEqual((result.total, result.done, len(result.failed)), (3, 2, 1))
        self.assertEqual([r["state"] for r in self.records()], ["start", "done", "start", "done", "start", "failed"])
        self.assertEqual(progress[-1][:2], (3, 3))
        self.assertEqual((self.target / "same.txt").read_bytes(), b"keep original")
        self.assertEqual((self.target / "same_중복1.txt").read_bytes(), b"a")
        self.assertEqual((self.target / "same_중복2.txt").read_bytes(), b"b")
        self.assertTrue(a.exists() and b.exists())

    def test_collect_cancellation_after_one_file(self):
        items = [self.item(self.file("a.txt")), self.item(self.file("b.txt"))]
        with patch.object(core, "recover_unfinished", return_value=0):
            result = core.run_collect(items, str(self.target), core.MODE_MOVE,
                                      should_stop=iter([False, True]).__next__)
        self.assertTrue(result.stopped)
        self.assertEqual(result.done, 1)
        self.assertTrue(Path(items[1].src).exists())
        self.assertFalse(Path(items[0].src).exists())

    def test_recover_incomplete_part_preserves_source(self):
        src = self.file("a.txt")
        dst = self.target / "a.txt"
        Path(str(dst) + core.PART_SUFFIX).write_bytes(b"partial")
        with open(core.journal_path(str(self.target)), "a", encoding="utf-8") as journal:
            core.write_journal(journal, core.MODE_MOVE, str(src), str(dst), "start")
            journal.write('{"incomplete":')
        self.assertEqual(core.recover_unfinished(str(self.target)), 1)
        self.assertTrue(src.exists())
        self.assertFalse(Path(str(dst) + core.PART_SUFFIX).exists())
        # 깨진 마지막 줄 뒤의 기록은 원본 구현상 같은 줄에 붙어요.
        self.assertIn('중단됨 (원본은 그대로 있음)', Path(core.journal_path(str(self.target))).read_text(encoding="utf-8"))

    def test_recover_completed_move_and_mismatched_copy(self):
        src = self.file("done.txt", b"same")
        dst = self.file("done.txt", b"same", base=self.target)
        state, reason = core.finish_interrupted(dict(src=str(src), dst=str(dst), mode=core.MODE_MOVE))
        self.assertEqual(state, "done")
        self.assertFalse(src.exists())
        src = self.file("different.txt", b"longer source")
        dst = self.file("different.txt", b"short", base=self.target)
        state, reason = core.finish_interrupted(dict(src=str(src), dst=str(dst), mode=core.MODE_MOVE))
        self.assertEqual(state, "failed")
        self.assertTrue(src.exists() and dst.exists())

    def test_settings_round_trip_and_corrupt_json(self):
        settings_path = self.root / "profile" / "settings.json"
        with patch.object(settings, "SETTINGS_PATH", str(settings_path)):
            self.assertEqual(settings.get_save_dir(), settings.DEFAULT_SAVE_DIR)
            settings.set_save_dir(str(self.target))
            self.assertEqual(settings.get_save_dir(), str(self.target))
            self.assertFalse(Path(str(settings_path) + ".tmp").exists())
            settings_path.write_text("{broken", encoding="utf-8")
            self.assertEqual(settings.load_settings(), {})
            settings_path.write_text("[]", encoding="utf-8")
            self.assertEqual(settings.load_settings(), {})


if __name__ == "__main__":
    unittest.main()
