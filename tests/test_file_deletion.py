"""임시 파일·DB와 실제 Qt 창으로 삭제 대상, 실패, 페이지 갱신을 검증해요."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from common import settings
from common.file_actions import delete_file
from common.widgets import STYLE
from duplicates.hash_cache import open_hash_cache, store_hash
from main import MainWindow
from searcher.file_controller import delete_files
from searcher.filename_search import search_by_name
from searcher.metadata import metadata_for_path, path_key
from searcher.result_table import COL_CHECK, COL_NAME
from searcher.search_pipeline import SearchRequest, run
from tagger import storage


class FileDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        temporary = TemporaryDirectory(prefix="filesearch-delete-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "files"
        self.source.mkdir()
        profile = patch.object(settings, "SETTINGS_PATH", str(self.root / "profile/settings.json"))
        profile.start()
        self.addCleanup(profile.stop)
        settings.set_save_dir(str(self.source))
        self.db = settings.get_body_cache_path()
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.window.show()
        self.panel = self.window.results
        self.table = self.panel.table
        self.panel.sort_combo.setCurrentText("이름순")
        self.panel.page_size_combo.setCurrentIndex(self.panel.page_size_combo.findData(10))
        self.app.processEvents()
        self.warnings = []
        self.dialog_timer = QTimer(self.window)
        self.dialog_timer.timeout.connect(self.close_warning)
        self.dialog_timer.start(5)
        self.addCleanup(self.dialog_timer.stop)
        trash = patch("common.file_actions.send_to_trash", side_effect=self.fake_trash)
        self.trash = trash.start()
        self.addCleanup(trash.stop)

    def fake_trash(self, path):
        # 자동 테스트에서는 사용자 휴지통을 건드리지 않고 이 테스트의 파일만 지워요.
        self.assertTrue(Path(path).resolve().is_relative_to(self.source.resolve()))
        os.remove(path)

    def close_warning(self):
        dialog = self.app.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            self.warnings.append((dialog.text(), dialog.detailedText()))
            dialog.accept()

    def files(self, count):
        paths = []
        for index in range(count):
            path = self.source / f"문서_{index:03d}.txt"
            path.write_text(f"검색 본문 {index}", encoding="utf-8")
            paths.append(str(path))
        self.panel.show_hits(search_by_name(str(self.source), []), ["문서"])
        return paths

    def check_rows(self, *rows):
        for row in rows:
            self.table.item(row, COL_CHECK).setCheckState(Qt.Checked)

    def visible(self):
        return [hit.path for hit in self.table.hits]

    def test_context_menu_deletes_clicked_file_not_checked_or_current_file(self):
        paths = self.files(3)
        self.table.setCurrentCell(0, COL_NAME)
        self.check_rows(0)
        actions = []

        def choose_delete():
            menu = self.app.activePopupWidget()
            actions.extend(action.text() for action in menu.actions() if not action.isSeparator())
            action = next(action for action in menu.actions() if action.text() == "삭제")
            menu.close()
            action.trigger()

        QTimer.singleShot(0, choose_delete)
        self.table.show_menu(self.table.visualItemRect(self.table.item(1, COL_NAME)).center())
        self.assertEqual(actions, ["파일 열기", "폴더 열기", "삭제"])
        self.trash.assert_called_once_with(paths[1])
        self.assertEqual(self.visible(), [paths[0], paths[2]])
        self.assertEqual([hit.path for hit in self.table.checked_hits()], [paths[0]])
        self.assertEqual(self.window.preview.hit.path, paths[0])
        self.assertEqual(self.panel.count_label.text(), "2개")

    def test_selected_delete_only_checks_and_keeps_failed_file_checked(self):
        paths = self.files(4)
        storage.attach_tags(paths, ["검토"], db_path=self.db)
        self.window.tags.refresh(reload_results=False)
        self.table.setCurrentCell(1, COL_NAME)
        self.check_rows(0, 2)

        def trash(path):
            if path == paths[2]:
                raise PermissionError("다른 프로그램이 사용 중이에요")
            self.fake_trash(path)

        self.trash.side_effect = trash
        self.window.delete_button.click()
        self.assertEqual([call.args[0] for call in self.trash.call_args_list], [paths[0], paths[2]])
        self.assertEqual(self.visible(), paths[1:])
        self.assertEqual([hit.path for hit in self.table.checked_hits()], [paths[2]])
        self.assertEqual(self.window.preview.hit.path, paths[1])
        self.assertEqual(self.window.selected_count_label.text(), "1개 선택")
        self.assertTrue(self.window.delete_button.isEnabled())
        self.assertIn("실패 1개", self.window.status_label.text())
        self.assertIn(paths[2], self.window.status_label.toolTip())
        self.assertEqual(storage.show_tag(self.db)[0].file_count, 3)
        self.assertEqual(len(self.warnings), 1)

    def test_empty_checks_do_not_delete_current_row_or_open_progress(self):
        paths = self.files(1)
        self.table.setCurrentCell(0, COL_NAME)
        self.assertFalse(self.window.delete_button.isEnabled())
        self.window.delete_button.click()
        self.window.files.delete_selected()
        self.trash.assert_not_called()
        self.assertTrue(Path(paths[0]).exists())
        with patch("searcher.result_table.QMenu") as menu:
            self.table.show_menu(QPoint(10, self.table.viewport().height() - 1))
            menu.assert_not_called()

    def test_last_page_deletion_moves_back_and_deleted_file_never_reappears(self):
        paths = self.files(21)
        self.panel.go_to_page(2)
        self.table.setCurrentCell(0, COL_NAME)
        self.check_rows(0)
        self.window.delete_button.click()
        self.assertEqual(self.panel.current_page, 1)
        self.assertEqual(self.panel.page_count, 2)
        self.assertEqual(self.visible(), paths[10:20])
        self.assertEqual(self.panel.range_label.text(), "11–20 / 20개")
        self.assertIsNone(self.window.preview.hit)
        self.assertFalse(self.window.delete_button.isEnabled())
        self.assertEqual(self.panel.keywords, ["문서"])
        self.panel.sort_combo.setCurrentText("크기순")
        self.assertNotIn(paths[-1], [hit.path for hit in self.panel.ordered_hits])
        self.assertFalse(Path(paths[-1]).exists())

    def test_middle_page_refills_and_keeps_sort_and_page(self):
        paths = self.files(23)
        self.panel.go_to_page(1)
        self.check_rows(0, 2)
        self.window.delete_button.click()
        remaining = [path for path in paths if path not in (paths[10], paths[12])]
        self.assertEqual(self.panel.current_page, 1)
        self.assertEqual(self.visible(), remaining[10:20])
        self.assertEqual(self.panel.count_label.text(), "21개")
        self.assertEqual(self.panel.sort_combo.currentText(), "이름순")

    def test_last_tagged_file_clears_preview_and_count_but_preserves_tag(self):
        paths = self.files(1)
        storage.attach_tags(paths, ["검토"], db_path=self.db)
        self.window.tags.refresh(reload_results=False)
        tag = storage.show_tag(self.db)[0]
        self.window.run_search(tag.id)
        self.table.setCurrentCell(0, COL_NAME)
        self.check_rows(0)
        self.window.delete_button.click()
        self.assertEqual(self.panel.hits, [])
        self.assertEqual(self.panel.count_label.text(), "0개")
        self.assertEqual(self.panel.page_input.value(), 0)
        self.assertFalse(self.panel.next_button.isEnabled())
        self.assertIsNone(self.window.preview.hit)
        self.assertFalse(self.window.preview.open_button.isEnabled())
        self.assertFalse(self.window.delete_button.isEnabled())
        self.assertEqual(self.window.active_tag_id, tag.id)
        self.assertEqual(self.panel.tag_filter, "검토")
        self.assertEqual(storage.show_tag(self.db)[0].file_count, 0)
        self.assertEqual(self.window.tags.tags_by_id[tag.id].file_count, 0)

    def test_failed_deletion_preserves_entire_ui_and_metadata(self):
        paths = self.files(1)
        storage.attach_tags(paths, ["검토"], db_path=self.db)
        self.table.setCurrentCell(0, COL_NAME)
        self.check_rows(0)
        self.trash.side_effect = PermissionError("locked")
        self.window.delete_button.click()
        self.assertTrue(Path(paths[0]).exists())
        self.assertEqual(self.visible(), paths)
        self.assertEqual(self.panel.count_label.text(), "1개")
        self.assertEqual(self.window.preview.hit.path, paths[0])
        self.assertEqual(len(self.table.checked_hits()), 1)
        self.assertEqual(storage.show_tag(self.db)[0].file_count, 1)

    def test_metadata_error_still_removes_deleted_file_from_ui(self):
        paths = self.files(1)
        self.table.setCurrentCell(0, COL_NAME)
        self.check_rows(0)
        with patch("searcher.file_controller.forget_deleted_file", side_effect=sqlite3.OperationalError("locked")):
            self.window.delete_button.click()
        self.assertFalse(Path(paths[0]).exists())
        self.assertEqual(self.panel.hits, [])
        self.assertIsNone(self.window.preview.hit)
        self.assertIn("태그·캐시 기록 정리 실패", self.window.status_label.text())
        self.assertEqual(len(self.warnings), 1)

    def test_folder_or_missing_path_never_reaches_trash(self):
        self.assertIsNotNone(delete_file(str(self.source)))
        self.assertIsNotNone(delete_file(str(self.source / "없는파일.txt")))
        self.trash.assert_not_called()
        self.assertTrue(self.source.is_dir())

    def test_cancel_keeps_unprocessed_files_and_returns_completed_deletions(self):
        paths = self.files(3)
        result = delete_files(paths, self.db, should_stop=lambda: not Path(paths[0]).exists())
        self.assertTrue(result.cancelled)
        self.assertEqual(result.deleted, paths[:1])
        self.assertTrue(all(Path(path).exists() for path in paths[1:]))

    def test_delete_clears_only_its_tags_tracking_body_and_hash_caches(self):
        paths = self.files(2)
        storage.attach_tags(paths, ["검토"], db_path=self.db)
        run(SearchRequest(str(self.source), "검색", body_enabled=True, cache_path=self.db))
        with closing(open_hash_cache(self.db)) as connection:
            for path in paths:
                store_hash(connection, str(self.source), metadata_for_path(path), "sample-digest")
        result = delete_files([paths[0], paths[0]], self.db)
        self.assertEqual(result.deleted, paths[:1])
        self.trash.assert_called_once_with(paths[0])
        with closing(sqlite3.connect(self.db)) as connection:
            for table in ("file_tags", "tracked_files", "body_cache", "file_hashes"):
                keys = {row[0] for row in connection.execute(f"SELECT path_key FROM {table}")}
                self.assertEqual(keys, {path_key(paths[1])}, table)
        self.assertEqual(storage.show_tag(self.db)[0].file_count, 1)


if __name__ == "__main__":
    unittest.main()
