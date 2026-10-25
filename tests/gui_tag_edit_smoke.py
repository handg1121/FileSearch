"""태그 수정 메뉴·파일 선택·전체 선택·저장·취소·결과 갱신을 검사해요."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import traceback
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from common import settings
from common.widgets import STYLE
from tagger import storage
from tagger.edit_dialog import EditTagDialog
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
source = fixture / "현재폴더"
outside = fixture / "다른폴더"
source.mkdir(exist_ok=True)
outside.mkdir(exist_ok=True)
a, b, c = str(source / "계약서.txt"), str(outside / "계약서.txt"), str(source / "참고자료.pdf")
for path in (a, b, c):
    Path(path).write_text("본문 계약금", encoding="utf-8")
settings.SETTINGS_PATH = str(fixture / "profile/settings.json")
settings.set_save_dir(str(source))
storage.attach_tags([a, b], ["검토중"])
storage.attach_tags([a, c], ["중요"])
source_id = next(t.id for t in storage.show_tag() if t.name == "검토중")
target_id = next(t.id for t in storage.show_tag() if t.name == "중요")
storage.set_tag_color(source_id, "#2563eb")
storage.set_tag_color(target_id, "#16a34a")
empty_id = storage.create_tag("빈 태그").id

app = QApplication([])
for name in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyleSheet(STYLE)
checks, errors = [], []
def exception_hook(typ, value, tb):
    errors.append(f"{typ.__name__}: {value}")
    traceback.print_exception(typ, value, tb)
sys.excepthook = exception_hook
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: (print("Tag edit GUI timed out", flush=True), os._exit(2)))
watchdog.start(30000)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def invoke_edit(tag_id, callback, via_menu=False):
    previous_errors = len(errors)
    def use_dialog():
        dialog = app.activeModalWidget()
        try:
            check("edit_dialog_opened", isinstance(dialog, EditTagDialog))
            callback(dialog)
        except Exception:
            exception_hook(*sys.exc_info())
            if dialog:
                dialog.reject()
    def use_menu():
        menu = app.activePopupWidget()
        if not isinstance(menu, QMenu):
            QTimer.singleShot(10, use_menu)
            return
        check("context_menu_has_edit_and_color", [action.text() for action in menu.actions()] == ["태그 수정", "색 변경"])
        action = next(action for action in menu.actions() if action.text() == "태그 수정")
        QTimer.singleShot(0, use_dialog)
        QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
    QTimer.singleShot(0, use_dialog if not via_menu else use_menu)
    if via_menu:
        items = window.tag_sidebar.tag_list
        item = next(items.item(row) for row in range(items.count()) if items.item(row).data(Qt.UserRole) == tag_id)
        items.scrollToItem(item)
        pos = items.visualItemRect(item).center()
        event = QContextMenuEvent(QContextMenuEvent.Mouse, pos, items.viewport().mapToGlobal(pos))
        QApplication.sendEvent(items.viewport(), event)
    else:
        window.tags.edit_tag(tag_id)
    app.processEvents()
    check("dialog_callback_succeeded", len(errors) == previous_errors)




window = main.MainWindow()
window.show()
app.processEvents()
window.run_search()
check("normal_results_before_edit", {h.path for h in window.results.hits} == {a, c})
before_cancel = storage.show_tag()


def cancel_via_menu(dialog):
    try:
        check("context_edit_dialog_opened", isinstance(dialog, EditTagDialog))
        check("all_registered_folders_included", set(dialog.paths) == {a, b})
        check("same_filename_different_full_paths", dialog.table.item(0, 1).text() == dialog.table.item(1, 1).text()
              and dialog.table.item(0, 2).text() != dialog.table.item(1, 2).text())
        check("initially_unchecked_and_save_disabled", dialog.selected_paths() == [] and not dialog.save_button.isEnabled())
        dialog.name_input.setText("수정된 계약")
        QTest.keyClick(dialog.name_input, Qt.Key_Return)
        check("enter_without_selection_does_not_change_or_select_files", dialog.selected_paths() == [] and dialog.isVisible())
        dialog.select_all_button.click()
        check("select_all_checks_all", set(dialog.selected_paths()) == {a, b} and dialog.save_button.isEnabled())
        dialog.clear_button.click()
        check("clear_all_unchecks_all", not dialog.selected_paths() and not dialog.save_button.isEnabled())
        dialog.cancel_button.click()
    except Exception:
        exception_hook(*sys.exc_info())
        if dialog:
            dialog.reject()


invoke_edit(source_id, cancel_via_menu, via_menu=True)
check("cancel_preserves_db", storage.show_tag() == before_cancel)
window.run_search(source_id)
check("active_source_view", {h.path for h in window.results.hits} == {a, b})


def edit_partial(dialog):
    dialog.name_input.setText("검토완료")
    row = dialog.paths.index(a)
    rect = dialog.table.visualItemRect(dialog.table.item(row, 0))
    QTest.mouseClick(dialog.table.viewport(), Qt.LeftButton, pos=rect.topLeft() + QPoint(12, rect.height() // 2))
    check("checkbox_click_selects_one_file", dialog.selected_paths() == [a])
    with patch("tagger.edit_dialog.open_file", return_value=None) as open_document:
        dialog.open_document(row, 1)
        check("document_open_uses_exact_registered_path", open_document.call_args.args == (a,))
    check("capture_partial_dialog", dialog.grab().save(str(args.artifacts / "tag_edit_dialog.png")))
    dialog.save_button.click()


invoke_edit(source_id, edit_partial)
new_tag = next(t for t in storage.show_tag() if t.name == "검토완료")
check("partial_edit_refreshes_source_results", window.active_tag_id == source_id and [h.path for h in window.results.hits] == [b])
check("unselected_keeps_old_tag", storage.read_file_tags([b])[b] == ("검토중",))
check("selected_keeps_other_tag", set(storage.read_file_tags([a])[a]) == {"검토완료", "중요"})
check("split_keeps_source_color", new_tag.color == "#2563eb" and window.tags.colors["검토완료"] == "#2563eb")
window.run_search(new_tag.id)


def rename_all(dialog):
    dialog.name_input.setText("최종계약서")
    dialog.select_all_button.click()
    QTest.keyClick(dialog.name_input, Qt.Key_Return)


invoke_edit(new_tag.id, rename_all)
check("all_rename_keeps_tag_identity_and_updates_title", window.active_tag_id == new_tag.id
      and window.results.title_label.text() == "검색 결과 · 최종계약서")
check("result_badge_renamed", set(window.results.table.tags_by_path[a]) == {"최종계약서", "중요"})
check("renamed_tag_color_preserved", window.tags.colors["최종계약서"] == "#2563eb")


def merge_all(dialog):
    dialog.name_input.setText("중요")
    dialog.select_all_button.click()
    check("merge_hint_explains_existing_target", "이미 있는" in dialog.hint.text() and "색" in dialog.hint.text())
    dialog.save_button.click()


invoke_edit(new_tag.id, merge_all)
check("merge_active_view_follows_target", window.active_tag_id == target_id and {h.path for h in window.results.hits} == {a, c})
check("merge_updates_title_and_removes_old_tag", window.results.title_label.text() == "검색 결과 · 중요"
      and new_tag.id not in window.tags.tags_by_id)
check("merge_deduplicates_and_uses_target_color", storage.read_file_tags([a])[a] == ("중요",) and window.tags.colors["중요"] == "#16a34a")


def rename_empty(dialog):
    dialog.name_input.setText("나중에 검토")
    check("empty_tag_can_rename_without_files", dialog.table.rowCount() == 0 and dialog.save_button.isEnabled())
    dialog.save_button.click()


invoke_edit(empty_id, rename_empty)
check("empty_tag_saved", next(t.name for t in storage.show_tag() if t.id == empty_id) == "나중에 검토")


def failed_edit(dialog):
    dialog.name_input.setText("실패 시 유지")
    dialog.select_all_button.click()
    with patch("tagger.edit_dialog.storage.edit_tag", side_effect=sqlite3.OperationalError("DB 쓰기 실패")):
        dialog.save_button.click()
    check("failed_edit_keeps_dialog_input_and_selection", dialog.isVisible() and dialog.name_input.text() == "실패 시 유지"
          and dialog.selected_paths() == [b] and dialog.error_label.isVisible())
    dialog.cancel_button.click()


invoke_edit(source_id, failed_edit)
check("failed_edit_does_not_change_storage", storage.read_file_tags([b])[b] == ("검토중",))
check("capture_updated_main", window.grab().save(str(args.artifacts / "tag_edit_result.png")))
window.close()
window = main.MainWindow()
window.show()
app.processEvents()
check("edits_survive_restart", "나중에 검토" in window.tags.colors and "최종계약서" not in window.tags.colors
      and window.tags.colors["중요"] == "#16a34a")
window.run_search(target_id)
check("lookup_after_restart", {h.path for h in window.results.hits} == {a, c})
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts / "tag_edit_gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
