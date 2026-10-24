"""검색 결과와 별도 경로 확인 창의 승인·거절·보류를 실제 Qt 흐름으로 검사해요."""

import argparse
from contextlib import closing
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
from searcher.metadata import path_key
from searcher.result_table import COL_TAGS
from tagger import storage
from tagger.move_dialog import PathMoveDialog
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
source = fixture / "source"
(source / "이전").mkdir(parents=True, exist_ok=True)
(source / "이동후").mkdir(exist_ok=True)
settings.SETTINGS_PATH = str(fixture / "profile/settings.json")
settings.set_save_dir(str(source))
a = str(source / "이전/계약서.txt")
b = str(source / "이전/회의록.txt")
for path in (a, b):
    Path(path).write_text("본문 내용", encoding="utf-8")
storage.attach_tags([a], ["중요"])
storage.attach_tags([b], ["검토중"])
app = QApplication([])
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: (print("Move GUI test timed out", flush=True), os._exit(2)))
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


def on_move_dialog(callback):
    # 검색 진행 창 다음에 열리는 경로 확인 창을 기다려요.
    def poll():
        dialog = app.activeModalWidget()
        if not isinstance(dialog, PathMoveDialog):
            QTimer.singleShot(10, poll)
            return
        try:
            callback(dialog)
        except BaseException:
            dialog.reject()
            raise
    QTimer.singleShot(0, poll)


window = main.MainWindow()
window.show()
window.search_bar.content_check.setChecked(True)
window.run_search()
new_a, new_b = str(source / "이동후/계약서.txt"), str(source / "이동후/회의록.txt")
Path(a).rename(new_a)
Path(b).rename(new_b)
window.search_bar.keyword_input.setText("검색결과에없는문구")


def approve_one(dialog):
    check("separate_confirmation_dialog", dialog.parent() is window)
    check("search_results_already_shown", not window.results.hits)
    check("two_missing_files_listed", len(dialog.rows) == 2)
    check("starts_without_preapproval", not dialog.transfer_button.isEnabled() and not dialog.discard_button.isEnabled())
    row = next(index for index, item in enumerate(dialog.rows) if item.candidate.old_path == a)
    check("old_and_new_paths_side_by_side", dialog.table.item(row, 1).text() == a and dialog.table.item(row, 2).text() == new_a)
    with patch("tagger.move_dialog.open_file", return_value=None) as opened:
        dialog.table.cellDoubleClicked.emit(row, 2)
    check("double_click_opens_new_file", opened.call_args.args == (new_a,))
    dialog.table.item(row, 0).setCheckState(Qt.Checked)
    app.processEvents()
    check("capture_confirmation", dialog.grab().save(str(args.artifacts / "path_move_confirmation.png")))
    dialog.transfer_button.click()


on_move_dialog(approve_one)
window.run_search()
check("approved_tag_moved", storage.read_file_tags([a, new_a]) == {a: (), new_a: ("중요",)})
check("unselected_tag_retained", storage.read_file_tags([b, new_b]) == {b: ("검토중",), new_b: ()})
check("approval_status", "태그를 옮겼어요" in window.status_label.text())


def defer(dialog):
    check("unresolved_file_appears_again", len(dialog.rows) == 1 and dialog.rows[0].candidate.old_path == b)
    dialog.close()


window.search_bar.keyword_input.clear()
on_move_dialog(defer)
window.run_search()
check("close_keeps_old_link", storage.read_file_tags([b])[b] == ("검토중",))
check("results_reflect_moved_tags", any(window.results.table.item(row, COL_TAGS).text() == "중요" for row in range(window.results.table.rowCount())))
window.close()
window = main.MainWindow()
window.show()
window.search_bar.content_check.setChecked(True)


def decline(dialog):
    check("deferred_after_restart", len(dialog.rows) == 1 and dialog.rows[0].candidate.old_path == b)
    dialog.select_all_button.click()
    dialog.discard_button.click()


on_move_dialog(decline)
window.run_search()
check("decline_removes_only_old_link", storage.read_file_tags([b, new_b, new_a]) == {b: (), new_b: (), new_a: ("중요",)})
with closing(sqlite3.connect(settings.get_body_cache_path())) as con:
    check("decline_clears_old_metadata", not con.execute("SELECT 1 FROM tracked_files WHERE path_key=?", (path_key(b),)).fetchone())
    check("decline_clears_old_body", not con.execute("SELECT 1 FROM body_cache WHERE path_key=?", (path_key(b),)).fetchone())
check("decline_preserves_file", Path(new_b).read_text(encoding="utf-8") == "본문 내용")
check("decline_preserves_tag_definition", "검토중" in [tag.name for tag in storage.show_tag()])
with patch("tagger.controller.PathMoveDialog", side_effect=AssertionError("Resolved candidates must not reappear")):
    window.run_search()
check("no_repeat_after_decision", True)

# 여러 동명 후보에서 하나를 선택하는 경우를 확인해요.
old = str(source / "이전/동명.txt")
Path(old).write_text("원본", encoding="utf-8")
storage.attach_tags([old], ["중요"])
window.run_search()
first = str(source / "이동후/동명.txt")
second = str(source / "다른폴더/동명.txt")
Path(first).parent.mkdir(exist_ok=True)
Path(second).parent.mkdir(exist_ok=True)
Path(old).rename(first)
Path(second).write_text("별개 파일", encoding="utf-8")


def choose_ambiguous(dialog):
    check("ambiguous_paths_listed", len(dialog.rows) == 2)
    dialog.select_all_button.click()
    with patch.object(QMessageBox, "warning") as warning:
        dialog.transfer_button.click()
    check("multiple_targets_blocked", warning.called and dialog.isVisible())
    dialog.set_all(Qt.Unchecked)
    row = next(i for i, item in enumerate(dialog.rows) if item.new_path == first)
    dialog.table.item(row, 0).setCheckState(Qt.Checked)
    dialog.transfer_button.click()


on_move_dialog(choose_ambiguous)
window.run_search()
check("only_chosen_destination_tagged", storage.read_file_tags([old, first, second]) == {old: (), first: ("중요",), second: ()})

# 확인 중 기존 경로에 파일이 다시 생기면 변경을 보류해요.
old_again = str(source / "이전/다시등장.txt")
Path(old_again).write_text("원본", encoding="utf-8")
storage.attach_tags([old_again], ["검토중"])
window.run_search()
new_again = str(source / "이동후/다시등장.txt")
Path(old_again).rename(new_again)


def reappear(dialog):
    Path(old_again).write_text("확인 중 돌아온 파일", encoding="utf-8")
    dialog.select_all_button.click()
    dialog.transfer_button.click()


on_move_dialog(reappear)
with patch.object(QMessageBox, "warning") as warning:
    window.run_search()
check("changed_state_reported", warning.called)
check("changed_state_keeps_data", storage.read_file_tags([old_again, new_again]) == {old_again: ("검토중",), new_again: ()})
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts / "move_gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
