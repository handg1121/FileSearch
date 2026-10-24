"""태그 버튼·체크박스·선택 범위·재실행 후 보존을 실제 Qt 화면에서 검사해요."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
from common import settings
from common.widgets import STYLE
from searcher.result_table import COL_CHECK, COL_TAGS
from tagger import storage
from tagger.dialogs import ManageTagsDialog, RemoveTagsDialog
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
source = fixture / "source"
source.mkdir(exist_ok=True)
settings.SETTINGS_PATH = str(fixture / "profile/settings.json")
settings.set_save_dir(str(source))
for name in ("계약서.txt", "도면.pdf", "회의록.txt"):
    (source / name).write_text("계약금 지급", encoding="utf-8")
app = QApplication([])
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: (print("GUI test timed out", flush=True), os._exit(2)))
watchdog.start(30000)
for name in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyleSheet(STYLE)
checks, errors = [], []
sys.excepthook = lambda typ, value, tb: errors.append(f"{typ.__name__}: {value}")


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def choose(widget, name):
    for row in range(widget.count()):
        item = widget.item(row)
        if item.text().split("  (")[0] == name:
            item.setCheckState(Qt.Checked)
            return
    raise AssertionError(f"Tag not found: {name}")


window = main.MainWindow()
window.show()
check("no_selection_disables_buttons", not window.tag_bar.attach_button.isEnabled() and not window.tag_bar.detach_button.isEnabled())
window.run_search()
table, bar = window.results.table, window.tag_bar
rows = {hit.name: row for row, hit in enumerate(table.hits)}
a = str(source / "계약서.txt")
b = str(source / "도면.pdf")
c = str(source / "회의록.txt")
for name in ("계약서.txt", "도면.pdf"):
    table.item(rows[name], COL_CHECK).setCheckState(Qt.Checked)
table.setCurrentCell(rows["계약서.txt"], 1)
bar.tag_input.setText("계약서, 중요")
bar.attach_button.click()
check("two_files_two_tags", storage.read_file_tags([a, b, c]) == {a: ("계약서", "중요"), b: ("계약서", "중요"), c: ()})
check("table_updated", table.item(rows["계약서.txt"], COL_TAGS).text() == "계약서, 중요")
check("preview_updated", window.preview.tags_label.text() == "계약서, 중요")
check("file_checks_preserved", len(table.checked_hits()) == 2 and window.selected_count_label.text() == "2개 선택")
check("sidebar_uses_real_counts", all("·  2" in window.tag_sidebar.tag_list.item(row).text() for row in range(2)))
bar.tag_input.setText("계약서, 검토중, 중요")
bar.attach_button.click()
check("new_and_existing_combined", set(storage.read_file_tags([a])[a]) == {"계약서", "중요", "검토중"})
check("duplicate_attachment_ignored", all(tag.file_count == 2 for tag in storage.show_tag()))

# Qt 이벤트 루프 안에서 실제 모달 창의 체크박스를 고르고 버튼을 눌러요.
def remove_in_dialog(cancel=False):
    dialog = app.activeModalWidget()
    check("removal_dialog", isinstance(dialog, RemoveTagsDialog))
    check("removal_starts_unchecked", not dialog.remove_button.isEnabled())
    choose(dialog.choices, "계약서")
    if cancel:
        dialog.reject()
    else:
        app.processEvents()
        check("capture_removal", dialog.grab().save(str(args.artifacts / "remove_tags.png")))
        dialog.remove_button.click()


table.item(rows["도면.pdf"], COL_CHECK).setCheckState(Qt.Unchecked)
QTimer.singleShot(0, lambda: remove_in_dialog(cancel=True))
bar.detach_button.click()
check("cancel_keeps_tags", "계약서" in storage.read_file_tags([a])[a])
QTimer.singleShot(0, remove_in_dialog)
bar.detach_button.click()
check("removes_only_checked_tag", set(storage.read_file_tags([a])[a]) == {"중요", "검토중"})
check("unselected_file_untouched", "계약서" in storage.read_file_tags([b])[b])
check("tag_definition_kept", "계약서" in [tag.name for tag in storage.show_tag()])
check("preview_reflects_removal", "계약서" not in window.preview.tags_label.text())

# 저장 실패 때 입력을 지우거나 성공으로 표시하면 안 돼요.
bar.tag_input.setText("보존할 입력")
with patch.object(storage, "attach_tags", side_effect=sqlite3.OperationalError("database is locked")), patch.object(QMessageBox, "warning") as warning:
    bar.attach_button.click()
check("db_error_reported", warning.called)
check("failed_input_preserved", bar.tag_input.text() == "보존할 입력")
bar.tag_input.clear()

# 관리 화면은 태그 자체를 삭제하므로 다른 파일에 붙은 관계도 명시적으로 제거해요.
def manage_in_dialog():
    dialog = app.activeModalWidget()
    check("manager_opens_from_sidebar", isinstance(dialog, ManageTagsDialog))
    dialog.name_input.setText("R&D <문자>")
    dialog.create_button.click()
    check("manager_create", "R&D <문자>" in [tag.name for tag in storage.show_tag()])
    choose(dialog.choices, "계약서")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        dialog.delete_button.click()
    check("global_delete_cancel", "계약서" in storage.read_file_tags([b])[b])
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        dialog.delete_button.click()
    check("global_delete_confirm", all("계약서" not in names for names in storage.read_file_tags([a, b]).values()))
    dialog.accept()


QTimer.singleShot(0, manage_in_dialog)
window.tag_sidebar.manage_button.click()
bar.tag_input.setText("R&D <문자>")
bar.attach_button.click()
check("tag_label_is_plain_text", "R&D <문자>" in window.preview.tags_label.text() and window.preview.tags_label.textFormat() == Qt.PlainText)
window.results.sort_combo.setCurrentText("이름순")
check("sorting_retains_tag_display", any("R&D <문자>" in table.item(row, COL_TAGS).text() for row in range(table.rowCount())))
check("sorting_clears_file_checks", not bar.attach_button.isEnabled())
row_a = next(row for row, hit in enumerate(table.hits) if hit.path == a)
table.setCurrentCell(row_a, 1)
app.processEvents()
check("capture_tagged_window", window.grab().save(str(args.artifacts / "tagged_window.png")))
expected = storage.read_file_tags([a, b, c])
window.close()
second = main.MainWindow()
second.run_search()
check("reopen_retains_tags", storage.read_file_tags([a, b, c]) == expected)
check("reopen_displays_tags", any("R&D <문자>" in second.results.table.item(row, COL_TAGS).text() for row in range(second.results.table.rowCount())))
second.search_bar.content_check.setChecked(True)
second.search_bar.keyword_input.setText("계약금")
second.run_search()
check("body_search_preserves_tags", storage.read_file_tags([a, b, c]) == expected)
check("body_results_show_tags", any("R&D <문자>" in second.results.table.item(row, COL_TAGS).text() for row in range(second.results.table.rowCount())))
with patch.object(storage, "read_file_tags", side_effect=sqlite3.DatabaseError("test read failure")):
    second.tags.refresh_file_tags()
check("read_error_stays_visible", not second.tag_bar.error_label.isHidden())
second.tags.refresh_file_tags()
check("read_error_clears_after_retry", second.tag_bar.error_label.isHidden())
check("no_qt_slot_errors", not errors)
second.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts / "tag_gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
