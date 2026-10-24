"""실제 경로 이동과 SQLite를 사용해 후보 탐지·확인·보류·정리를 검사해요."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from searcher.metadata import SearchCancelled, path_key, read_file_metadata
from searcher.search_pipeline import SearchRequest, run
from tagger import storage
from tagger import path_tracking as tracking
from tagger.path_tracking import MoveChoice, find_path_moves, resolve_path_moves


class PathTrackingTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-moves-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "files"
        self.source.mkdir()
        self.db = self.root / "data.sqlite3"
        self.old = self.file("old/계약서.txt", "이전 본문")
        storage.attach_tags([self.old], ["중요"], db_path=self.db)

    def file(self, name, text="본문"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def move(self, old=None, folder="new"):
        old = old or self.old
        new = self.source / folder / Path(old).name
        new.parent.mkdir(parents=True, exist_ok=True)
        Path(old).rename(new)
        return str(new)

    def find(self):
        return find_path_moves(read_file_metadata(str(self.source)), self.db)

    def read(self, *paths):
        return storage.read_file_tags(paths, self.db)

    def records(self, table):
        with closing(sqlite3.connect(self.db)) as con:
            return con.execute(f"SELECT * FROM {table} ORDER BY path_key").fetchall()

    def search(self, **options):
        options.setdefault("name_enabled", True)
        return run(SearchRequest(root=str(self.source), cache_path=str(self.db), **options))

    def choice(self):
        move = self.find()[0]
        return MoveChoice(move, move.new_paths[0])

    def test_defer_repeats_and_approval_transfers_only_links(self):
        new = self.move()
        first, second = self.find(), self.find()
        self.assertEqual(first, second)
        self.assertEqual(first[0].old_path, self.old)
        self.assertEqual(first[0].new_paths, (new,))
        self.assertEqual(self.read(self.old, new), {self.old: ("중요",), new: ()})
        self.assertEqual(resolve_path_moves([MoveChoice(first[0], new)], transfer=True, db_path=self.db), 1)
        self.assertEqual(self.read(self.old, new), {self.old: (), new: ("중요",)})
        self.assertEqual(self.find(), [])
        self.assertEqual(Path(new).read_text(encoding="utf-8"), "이전 본문")
        self.assertEqual([row[0] for row in self.records("tracked_files")], [path_key(new)])

    def test_decline_deletes_old_metadata_keeps_new_file_and_tag_definition(self):
        self.search(body_enabled=True)
        new = self.move()
        Path(new).write_text("완전히 다른 본문", encoding="utf-8")
        result = self.search(body_enabled=True)
        self.assertEqual(len(result.path_moves), 1)
        self.assertEqual(len(self.records("body_cache")), 2)
        resolve_path_moves([MoveChoice(result.path_moves[0], new)], transfer=False, db_path=self.db)
        self.assertEqual(self.read(self.old, new), {self.old: (), new: ()})
        self.assertEqual([tag.name for tag in storage.show_tag(self.db)], ["중요"])
        self.assertNotIn(path_key(self.old), [row[0] for row in self.records("tracked_files")])
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT path, body FROM body_cache").fetchall(), [(new, "완전히 다른 본문")])
        self.assertEqual(Path(new).read_text(encoding="utf-8"), "완전히 다른 본문")
        self.assertFalse(self.find())

    def test_transfer_does_not_copy_old_body_to_new_file(self):
        self.search(body_enabled=True)
        new = self.move()
        Path(new).write_text("새로운 내용", encoding="utf-8")
        result = self.search(body_enabled=True)
        resolve_path_moves([MoveChoice(result.path_moves[0], new)], transfer=True, db_path=self.db)
        with closing(sqlite3.connect(self.db)) as con:
            self.assertEqual(con.execute("SELECT path, body FROM body_cache").fetchall(), [(new, "새로운 내용")])

    def test_detection_ignores_query_extension_and_date_filters(self):
        new = self.move()
        result = self.search(query="매치되지 않는 이름", extensions={"pdf"}, since=9999999999)
        self.assertEqual(result.hits, [])
        self.assertEqual(result.path_moves[0].new_paths, (new,))

    def test_existing_same_name_file_is_not_a_candidate(self):
        known = self.file("other/계약서.txt")
        self.assertFalse(self.find())
        new = self.move()
        self.assertEqual(self.find()[0].new_paths, (new,))
        self.assertEqual(self.read(known)[known], ())

    def test_copy_does_not_get_original_tags_or_later_become_move_candidate(self):
        copy = self.file("copy/계약서.txt")
        self.assertFalse(self.find())
        Path(self.old).unlink()
        self.assertFalse(self.find())
        self.assertEqual(self.read(copy)[copy], ())

    def test_partial_scan_does_not_change_registry_or_propose_moves(self):
        self.move()
        snapshot = read_file_metadata(str(self.source))
        snapshot.errors.append((self.old, "읽기 거부"))
        before = self.records("tracked_files")
        self.assertFalse(find_path_moves(snapshot, self.db))
        self.assertEqual(self.records("tracked_files"), before)
        self.assertEqual(len(self.find()), 1)

    def test_permission_failure_preserves_candidate_for_retry(self):
        self.move()
        with patch.object(tracking, "_missing", side_effect=PermissionError("접근 거부")):
            self.assertFalse(self.find())
        self.assertEqual(len(self.find()), 1)

    def test_another_search_root_does_not_claim_old_file(self):
        new = self.move()
        snapshot = read_file_metadata(str(Path(new).parent))
        self.assertFalse(find_path_moves(snapshot, self.db))
        self.assertEqual(self.read(self.old)[self.old], ("중요",))

    def test_ambiguous_targets_require_one_selection(self):
        new = self.move()
        other = self.file("second/계약서.txt")
        candidate = self.find()[0]
        self.assertEqual(set(candidate.new_paths), {new, other})
        choices = [MoveChoice(candidate, path) for path in candidate.new_paths]
        with self.assertRaises(ValueError):
            resolve_path_moves(choices, transfer=True, db_path=self.db)
        self.assertEqual(self.read(self.old)[self.old], ("중요",))
        resolve_path_moves([MoveChoice(candidate, other)], transfer=True, db_path=self.db)
        self.assertEqual(self.read(new, other), {new: (), other: ("중요",)})

    def test_two_sources_cannot_merge_into_one_destination(self):
        second = self.file("second/계약서.txt")
        storage.attach_tags([second], ["별개"], db_path=self.db)
        new = self.move()
        Path(second).unlink()
        candidates = self.find()
        self.assertEqual(len(candidates), 2)
        with self.assertRaises(ValueError):
            resolve_path_moves([MoveChoice(item, new) for item in candidates], transfer=True, db_path=self.db)
        self.assertEqual(self.read(self.old, second, new), {self.old: ("중요",), second: ("별개",), new: ()})

    def test_reappeared_original_blocks_both_transfer_and_discard(self):
        new = self.move()
        choice = self.choice()
        Path(self.old).write_text("다시 생긴 파일", encoding="utf-8")
        for transfer in (True, False):
            with self.assertRaises(ValueError):
                resolve_path_moves([choice], transfer=transfer, db_path=self.db)
        self.assertEqual(self.read(self.old, new), {self.old: ("중요",), new: ()})

    def test_disappeared_target_and_concurrent_tag_change_are_rechecked(self):
        new = self.move()
        choice = self.choice()
        Path(new).unlink()
        for transfer in (True, False):
            with self.assertRaises(ValueError):
                resolve_path_moves([choice], transfer=transfer, db_path=self.db)
        Path(new).write_text("본문", encoding="utf-8")
        storage.delete_tag(choice.candidate.tag_ids, self.db)
        with self.assertRaises(ValueError):
            resolve_path_moves([choice], transfer=False, db_path=self.db)

    def test_database_failure_rolls_back_entire_move(self):
        new = self.move()
        choice = self.choice()
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("""CREATE TRIGGER fail_cleanup BEFORE DELETE ON tracked_files
                        BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            resolve_path_moves([choice], transfer=True, db_path=self.db)
        self.assertEqual(self.read(self.old, new), {self.old: ("중요",), new: ()})
        self.assertEqual(len(self.find()), 1)

    def test_legacy_registry_migration_preserves_links_and_known_body_paths(self):
        other = self.file("known/계약서.txt")
        self.search(body_enabled=True)
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("DROP TABLE tracked_files")
        new = self.move()
        self.assertEqual(self.find()[0].new_paths, (new,))
        self.assertEqual(self.read(self.old, other), {self.old: ("중요",), other: ()})

    def test_filename_change_and_content_change_do_not_guess_moves(self):
        Path(self.old).write_text("수정된 본문", encoding="utf-8")
        self.assertFalse(self.find())
        self.assertEqual(self.read(self.old)[self.old], ("중요",))
        Path(self.old).rename(Path(self.old).with_name("이름변경.txt"))
        self.assertFalse(self.find())

    def test_cancelled_scan_does_not_register_pending_candidates(self):
        self.move()
        snapshot = read_file_metadata(str(self.source))
        before = self.records("tracked_files")
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls > 2
        with self.assertRaises(SearchCancelled):
            find_path_moves(snapshot, self.db, should_stop=cancel)
        self.assertEqual(self.records("tracked_files"), before)
        self.assertEqual(len(self.find()), 1)


if __name__ == "__main__":
    unittest.main()
