"""중복 찾기(크기 → 해시)와 정리(휴지통·태그 이전)를 실제 파일과 SQLite로 검사해요.

실제 휴지통 대신 파일을 지우는 가짜 함수를 넘겨서 사용자 휴지통을 건드리지 않아요.
"""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unicodedata
import unittest
from unittest.mock import patch

from duplicates import finder
from duplicates.finder import find_duplicates
from duplicates.remover import KeepChoice, is_copy_name, pick_original, remove_duplicates
from searcher.metadata import SearchCancelled, path_key
from searcher.search_pipeline import SearchRequest, run
from tagger.path_tracking import transfer_tags_to_kept
from tagger.storage import attach_tags, read_file_tags


def fake_trash(path):
    os.remove(path)


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-dup-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "files"
        self.source.mkdir()
        self.db = str(self.root / "profile" / "body_cache.sqlite3")

    def file(self, name, data):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return str(path)

    def find(self, **kwargs):
        return find_duplicates(str(self.source), cache_path=self.db, **kwargs)

    def paths(self, group):
        return [item.path for item in group.files]

    def test_same_content_grouped_regardless_of_name_and_folder(self):
        a = self.file("보고서.hwp", "같은 내용")
        b = self.file("하위/보고서_중복1.hwp", "같은 내용")
        c = self.file("다른폴더/완전히다른이름.txt", "같은 내용")
        self.file("단독.txt", "혼자만 있는 내용")
        result = self.find()
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(sorted(self.paths(result.groups[0])), sorted([a, b, c]))
        self.assertEqual(result.groups[0].wasted, len("같은 내용".encode("utf-8")) * 2)
        self.assertEqual(result.scanned, 4)

    def test_same_name_or_same_size_with_different_content_not_grouped(self):
        self.file("a/보고서.hwp", "내용 하나")
        self.file("b/보고서.hwp", "내용 둘!")
        self.file("크기같음1.txt", "abcd")
        self.file("크기같음2.txt", "wxyz")
        self.assertEqual(self.find().groups, [])

    def test_empty_files_excluded(self):
        self.file("빈1.txt", "")
        self.file("빈2.txt", "")
        self.assertEqual(self.find().groups, [])

    def test_only_same_size_files_are_read(self):
        a = self.file("a.txt", "12345")
        b = self.file("b.txt", "12345")
        self.file("c.txt", "123456")
        self.file("d.txt", "1234567")
        read = []
        original = finder.file_digest

        def counting(path, should_stop=lambda: False):
            read.append(path)
            return original(path, should_stop)

        with patch("duplicates.finder.file_digest", side_effect=counting):
            result = self.find()
        self.assertEqual(sorted(read), sorted([a, b]))
        self.assertEqual(result.hashed, 2)

    def test_large_file_hashed_in_chunks(self):
        data = os.urandom(finder.CHUNK_SIZE * 2 + 10)
        self.file("큰1.bin", data)
        self.file("큰2.bin", data)
        self.file("큰3.bin", data[:-1] + bytes([data[-1] ^ 1]))
        result = self.find()
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(len(result.groups[0].files), 2)

    def test_groups_sorted_by_wasted_space(self):
        self.file("작은1.txt", "ab")
        self.file("작은2.txt", "ab")
        self.file("큰1.txt", "abcdefgh")
        self.file("큰2.txt", "abcdefgh")
        self.file("큰3.txt", "abcdefgh")
        sizes = [group.size for group in self.find().groups]
        self.assertEqual(sizes, [8, 2])

    def test_unreadable_file_reported_not_grouped(self):
        a = self.file("a.txt", "같음")
        self.file("b.txt", "같음")
        original = finder.file_digest

        def failing(path, should_stop=lambda: False):
            if path == a:
                raise PermissionError("잠김")
            return original(path, should_stop)

        with patch("duplicates.finder.file_digest", side_effect=failing):
            result = self.find()
        self.assertEqual(result.groups, [])
        self.assertEqual([path for path, _ in result.errors], [a])

    def test_cancel_stops_finding(self):
        self.file("a.txt", "같음")
        self.file("b.txt", "같음")
        calls = []

        def stop():
            calls.append(1)
            return len(calls) > 3

        with self.assertRaises(SearchCancelled):
            self.find(should_stop=stop)

    def test_remove_keeps_choice_and_moves_tags(self):
        keep = self.file("남김/계약서.hwp", "같은 계약서")
        gone1 = self.file("계약서_중복1.hwp", "같은 계약서")
        gone2 = self.file("옛폴더/사본.hwp", "같은 계약서")
        attach_tags([keep], ["중요"], db_path=self.db)
        attach_tags([gone1], ["중요", "계약서"], db_path=self.db)
        attach_tags([gone2], ["거래처"], db_path=self.db)
        group = self.find().groups[0]
        keep_item = next(item for item in group.files if item.path == keep)
        removed = remove_duplicates([KeepChoice(group, keep_item)], trash=fake_trash, db_path=self.db)
        self.assertEqual(sorted(removed.trashed), sorted([gone1, gone2]))
        self.assertEqual(removed.failed, [])
        self.assertTrue(os.path.exists(keep))
        self.assertFalse(os.path.exists(gone1) or os.path.exists(gone2))
        # 같은 태그(중요)는 하나로 합치고, 새 태그 두 개만 옮겨요.
        self.assertEqual(removed.moved_tags, 2)
        tags = read_file_tags([keep, gone1, gone2], self.db)
        self.assertEqual(sorted(tags[keep]), ["거래처", "계약서", "중요"])
        self.assertEqual(tags[gone1], ())
        self.assertEqual(tags[gone2], ())

    def test_unselected_groups_untouched(self):
        a = self.file("a1.txt", "묶음A")
        b = self.file("a2.txt", "묶음A")
        c = self.file("b1.txt", "묶음BB")
        d = self.file("b2.txt", "묶음BB")
        groups = self.find().groups
        first = groups[0]
        removed = remove_duplicates([KeepChoice(first, first.files[0])], trash=fake_trash, db_path=self.db)
        self.assertEqual(removed.trashed, [first.files[1].path])
        other = [path for path in (a, b, c, d) if path not in self.paths(first)]
        self.assertTrue(all(os.path.exists(path) for path in other))

    def test_changed_file_skips_whole_group(self):
        keep = self.file("a.txt", "같음")
        gone = self.file("b.txt", "같음")
        attach_tags([gone], ["중요"], db_path=self.db)
        group = self.find().groups[0]
        Path(gone).write_text("바뀜!", encoding="utf-8")
        keep_item = next(item for item in group.files if item.path == keep)
        trashed = []
        removed = remove_duplicates([KeepChoice(group, keep_item)], trash=trashed.append, db_path=self.db)
        self.assertEqual(trashed, [])
        self.assertEqual([path for path, _ in removed.failed], [gone])
        self.assertIn("바뀌어", removed.failed[0][1])
        self.assertEqual(read_file_tags([gone], self.db)[gone], ("중요",))

    def test_kept_file_changed_also_skips_group(self):
        keep = self.file("a.txt", "같음")
        self.file("b.txt", "같음")
        group = self.find().groups[0]
        os.remove(keep)
        keep_item = next(item for item in group.files if item.path == keep)
        trashed = []
        removed = remove_duplicates([KeepChoice(group, keep_item)], trash=trashed.append, db_path=self.db)
        self.assertEqual(trashed, [])
        self.assertEqual(len(removed.failed), 1)

    def test_trash_failure_keeps_tags_on_failed_file(self):
        keep = self.file("a.txt", "같음")
        ok = self.file("b.txt", "같음")
        locked = self.file("c.txt", "같음")
        attach_tags([ok], ["완료"], db_path=self.db)
        attach_tags([locked], ["검토중"], db_path=self.db)
        group = self.find().groups[0]

        def trash(path):
            if path == locked:
                raise OSError("다른 프로그램이 사용 중")
            os.remove(path)

        keep_item = next(item for item in group.files if item.path == keep)
        removed = remove_duplicates([KeepChoice(group, keep_item)], trash=trash, db_path=self.db)
        self.assertEqual(removed.trashed, [ok])
        self.assertEqual(removed.failed, [(locked, "다른 프로그램이 사용 중")])
        tags = read_file_tags([keep, locked], self.db)
        self.assertEqual(tags[keep], ("완료",))
        self.assertEqual(tags[locked], ("검토중",))

    def test_cancel_between_groups(self):
        self.file("a1.txt", "묶음A")
        self.file("a2.txt", "묶음A")
        self.file("b1.txt", "묶음BB")
        self.file("b2.txt", "묶음BB")
        groups = self.find().groups
        choices = [KeepChoice(group, group.files[0]) for group in groups]
        trashed = []

        def trash(path):
            trashed.append(path)
            os.remove(path)

        # 첫 묶음을 보낸 뒤에 취소를 누른 경우예요.
        removed = remove_duplicates(choices, trash=trash, db_path=self.db, should_stop=lambda: bool(trashed))
        self.assertTrue(removed.cancelled)
        self.assertEqual(removed.trashed, [groups[0].files[1].path])

    def test_transfer_clears_records_of_removed_path(self):
        keep = self.file("a.txt", "본문 계약금")
        gone = self.file("b.txt", "본문 계약금")
        attach_tags([gone], ["중요"], db_path=self.db)
        run(SearchRequest(root=str(self.source), query="계약금", name_enabled=False,
                          body_enabled=True, cache_path=self.db))
        os.remove(gone)
        self.assertEqual(transfer_tags_to_kept([(gone, keep)], db_path=self.db), 1)
        with closing(sqlite3.connect(self.db)) as connection:
            for table in ("file_tags", "tracked_files", "body_cache"):
                self.assertIsNone(connection.execute(
                    f"SELECT 1 FROM {table} WHERE path_key = ?", (path_key(gone),)).fetchone(), table)
            self.assertIsNotNone(connection.execute(
                "SELECT 1 FROM tracked_files WHERE path_key = ?", (path_key(keep),)).fetchone())

    def test_transfer_rejects_same_path_and_rolls_back(self):
        keep = self.file("a.txt", "같음")
        gone = self.file("b.txt", "같음")
        attach_tags([gone], ["중요"], db_path=self.db)
        with self.assertRaises(ValueError):
            transfer_tags_to_kept([(gone, keep), (keep, keep)], db_path=self.db)
        self.assertEqual(read_file_tags([gone, keep], self.db), {gone: ("중요",), keep: ()})

    def test_copy_name_rule(self):
        for name in ("보고서_중복1.hwp", "보고서_중복12.hwp", "README_중복3",
                     "a.tar_중복1.gz", unicodedata.normalize("NFD", "보고서_중복2.hwp")):
            with self.subTest(name=name):
                self.assertTrue(is_copy_name(name))
        for name in ("보고서.hwp", "보고서_중복.hwp", "중복1.hwp", "보고서_중복1 수정.hwp", "_중복1이야기.txt"):
            with self.subTest(name=name):
                self.assertFalse(is_copy_name(name))

    def test_pick_original_only_when_single(self):
        original = self.file("보고서.hwp", "같음")
        self.file("하위/보고서_중복1.hwp", "같음")
        self.file("하위/보고서_중복2.hwp", "같음")
        group = self.find().groups[0]
        self.assertEqual(pick_original(group).path, original)

    def test_pick_original_none_when_ambiguous_or_missing(self):
        self.file("a/보고서.hwp", "둘 다 원본")
        self.file("b/보고서.hwp", "둘 다 원본")
        self.file("c/보고서_중복1.hwp", "둘 다 원본")
        self.file("x_중복1.txt", "원본 없음")
        self.file("x_중복2.txt", "원본 없음")
        groups = self.find().groups
        self.assertEqual(len(groups), 2)
        self.assertEqual([pick_original(group) for group in groups], [None, None])

    def read_paths_during(self, **kwargs):
        '찾는 동안 실제로 내용을 읽은 경로 목록과 결과를 돌려줘요.'
        read = []
        original = finder.file_digest

        def counting(path, should_stop=lambda: False):
            read.append(path)
            return original(path, should_stop)

        with patch("duplicates.finder.file_digest", side_effect=counting):
            result = self.find(**kwargs)
        return sorted(read), result

    def hash_rows(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return sorted(row[0] for row in connection.execute("SELECT path FROM file_hashes"))

    def test_second_find_reuses_saved_hashes(self):
        a = self.file("a.txt", "같음")
        b = self.file("b.txt", "같음")
        read, first = self.read_paths_during()
        self.assertEqual(read, sorted([a, b]))
        self.assertEqual((first.hashed, first.reused), (2, 0))
        read, second = self.read_paths_during()
        self.assertEqual(read, [])
        self.assertEqual((second.hashed, second.reused), (0, 2))
        self.assertEqual(self.paths(second.groups[0]), self.paths(first.groups[0]))

    def test_changed_mtime_or_size_rereads_only_that_file(self):
        a = self.file("a.txt", "같음")
        b = self.file("b.txt", "같음")
        c = self.file("c.txt", "같음")
        self.find()
        info = os.stat(b)
        os.utime(b, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        read, result = self.read_paths_during()
        self.assertEqual(read, [b])
        self.assertEqual(len(result.groups[0].files), 3)
        Path(c).write_text("크기가 다름", encoding="utf-8")
        read, result = self.read_paths_during()
        # c는 크기 상대가 없어 읽지 않고, a·b는 그대로라 저장된 해시를 써요.
        self.assertEqual(read, [])
        self.assertEqual(self.paths(result.groups[0]), sorted([a, b], key=path_key))

    def test_renamed_file_reread_and_old_record_forgotten(self):
        a = self.file("a.txt", "같음")
        b = self.file("b.txt", "같음")
        self.find()
        renamed = str(self.source / "b_새이름.txt")
        os.rename(b, renamed)
        read, result = self.read_paths_during()
        self.assertEqual(read, [renamed])
        self.assertEqual(self.hash_rows(), sorted([a, renamed]))

    def test_records_kept_when_scan_incomplete(self):
        a = self.file("a.txt", "같음")
        b = self.file("b.txt", "같음")
        self.find()
        os.remove(b)
        original = finder.read_file_metadata

        def failing_scan(*args, **kwargs):
            snapshot = original(*args, **kwargs)
            snapshot.errors.append(("다른폴더", "접근 거부"))
            return snapshot

        with patch("duplicates.finder.read_file_metadata", side_effect=failing_scan):
            self.find()
        self.assertEqual(self.hash_rows(), sorted([a, b]))
        self.find()
        self.assertEqual(self.hash_rows(), [a])

    def test_stale_hash_caught_before_trash(self):
        # 크기·수정 시각을 그대로 둔 채 내용만 바꾸면 찾기는 저장된 해시로 묶지만,
        # 지우기 직전에 다시 읽어 그 묶음을 건너뛰어요.
        keep = self.file("a.txt", "같음1")
        other = self.file("b.txt", "같음1")
        attach_tags([other], ["중요"], db_path=self.db)
        self.find()
        info = os.stat(other)
        Path(other).write_text("다름2", encoding="utf-8")
        os.utime(other, ns=(info.st_atime_ns, info.st_mtime_ns))
        group = self.find().groups[0]
        self.assertEqual(sorted(self.paths(group)), sorted([keep, other]))
        keep_item = next(item for item in group.files if item.path == keep)
        trashed = []
        removed = remove_duplicates([KeepChoice(group, keep_item)], trash=trashed.append, db_path=self.db)
        self.assertEqual(trashed, [])
        self.assertEqual([path for path, _ in removed.failed], [other])
        self.assertIn("내용이 달라", removed.failed[0][1])
        self.assertEqual(read_file_tags([other], self.db)[other], ("중요",))

    def test_kept_file_content_also_rechecked(self):
        keep = self.file("a.txt", "같음1")
        other = self.file("b.txt", "같음1")
        self.find()
        info = os.stat(keep)
        Path(keep).write_text("다름2", encoding="utf-8")
        os.utime(keep, ns=(info.st_atime_ns, info.st_mtime_ns))
        group = self.find().groups[0]
        keep_item = next(item for item in group.files if item.path == keep)
        trashed = []
        removed = remove_duplicates([KeepChoice(group, keep_item)], trash=trashed.append, db_path=self.db)
        self.assertEqual(trashed, [])
        self.assertTrue(os.path.exists(other))
        self.assertEqual(len(removed.failed), 1)

    def test_cancel_during_recheck_keeps_earlier_groups_done(self):
        a1 = self.file("a1.txt", "묶음BB")
        a2 = self.file("a2.txt", "묶음BB")
        self.file("b1.txt", "묶음A")
        self.file("b2.txt", "묶음A")
        attach_tags([a2], ["중요"], db_path=self.db)
        groups = self.find().groups
        choices = [KeepChoice(group, group.files[0]) for group in groups]
        calls = []

        def recheck(group, should_stop=lambda: False):
            calls.append(group)
            if len(calls) > 1:
                raise SearchCancelled()
            return ""

        with patch("duplicates.remover.content_reason", side_effect=recheck):
            removed = remove_duplicates(choices, trash=fake_trash, db_path=self.db)
        self.assertTrue(removed.cancelled)
        self.assertEqual(removed.trashed, [a2])
        self.assertEqual(read_file_tags([a1], self.db)[a1], ("중요",))


if __name__ == "__main__":
    unittest.main()
