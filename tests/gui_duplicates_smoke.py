"""사이드바 '중복 파일' 버튼부터 정리·태그 이전·목록 갱신까지 실제 Qt 화면에서 검사해요.

실제 휴지통 대신 파일을 지우는 가짜 함수를 써서 사용자 휴지통을 건드리지 않아요.
"""

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from common import settings
from common.widgets import STYLE
from duplicates.dialog import COL_KEEP, DuplicateDialog
from duplicates.finder import DuplicateGroup, DuplicateResult
from searcher.metadata import FileMetadata
from tagger import storage
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
source = fixture / "source"
source.mkdir(exist_ok=True)
settings.SETTINGS_PATH = str(fixture / "profile/settings.json")
settings.set_save_dir(str(source))


def write(name, text):
    path = source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


keep = write("계약/계약서.hwp", "같은 계약서 내용")
copy1 = write("계약서_중복1.hwp", "같은 계약서 내용")
copy2 = write("옛자료/계약서_중복2.hwp", "같은 계약서 내용")
photo1 = write("사진/a.txt", "다른 묶음")
photo2 = write("사진/b.txt", "다른 묶음")
unique = write("단독.txt", "혼자")
storage.attach_tags([keep], ["중요"])
storage.attach_tags([copy1], ["중요", "거래처"])

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


def on_dialog(callback):
    # 찾기 진행 창 다음에 열리는 중복 파일 창을 기다려요.
    def poll():
        dialog = app.activeModalWidget()
        if not isinstance(dialog, DuplicateDialog):
            QTimer.singleShot(10, poll)
            return
        try:
            callback(dialog)
        except BaseException:
            dialog.reject()
            raise
    QTimer.singleShot(0, poll)


def row(dialog, group_index, file_index):
    return dialog.tree.topLevelItem(group_index).child(file_index)


def click(dialog, group_index, file_index):
    # 실제 마우스로 남길 파일 칸을 눌러요.
    item = row(dialog, group_index, file_index)
    dialog.tree.scrollToItem(item)
    rect = dialog.tree.visualItemRect(item)
    x = dialog.tree.header().sectionViewportPosition(COL_KEEP) + dialog.tree.columnWidth(COL_KEEP) // 2
    QTest.mouseClick(dialog.tree.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, rect.center().y()))


def checked(dialog, group_index, file_index):
    return row(dialog, group_index, file_index).data(COL_KEEP, Qt.CheckStateRole) == Qt.Checked


def fake_trash(path):
    os.remove(path)


window = main.MainWindow()
window.show()
window.run_search()
check("all_files_listed_before", len(window.results.hits) == 6)


def close_without_choice(dialog):
    check("two_groups_listed", len(dialog.result.groups) == 2)
    check("starts_without_choice", not dialog.remove_button.isEnabled() and not dialog.selected_choices())
    dialog.reject()


on_dialog(close_without_choice)
with patch("duplicates.controller.send_to_trash", side_effect=AssertionError("must not trash")):
    window.nav_buttons["중복 파일"].click()
check("close_deletes_nothing", all(os.path.exists(path) for path in (keep, copy1, copy2, photo1, photo2, unique)))
check("nav_returns_to_all_files", window.nav_buttons["전체 파일"].isChecked())


def choose_and_remove(dialog):
    group = dialog.result.groups[0]
    check("largest_group_first", len(group.files) == 3)
    paths = [item.path for item in group.files]
    check("no_row_widgets", dialog.tree.itemWidget(row(dialog, 0, 0), COL_KEEP) is None)
    click(dialog, 0, 0)
    check("choice_enables_button", dialog.remove_button.isEnabled() and checked(dialog, 0, 0))
    click(dialog, 0, 1)
    check("one_choice_per_group", not checked(dialog, 0, 0) and checked(dialog, 0, 1))
    click(dialog, 0, 1)
    check("click_again_clears", not checked(dialog, 0, 1) and not dialog.remove_button.isEnabled())
    QTest.mouseClick(dialog.tree.viewport(), Qt.LeftButton, Qt.NoModifier,
                     dialog.tree.visualItemRect(row(dialog, 0, 0)).center() + QPoint(200, 0))
    check("click_other_column_ignored", not dialog.selected_choices())
    click(dialog, 1, 0)
    dialog.clear_all()
    check("clear_all", not dialog.selected_choices())
    # 원본 한 번에 고르기: 직접 고른 묶음은 그대로 두고, 원본을 정할 수 없는 묶음은 비워 둬요.
    click(dialog, 0, paths.index(copy1))
    dialog.pick_button.click()
    check("pick_keeps_manual_choice", [choice.keep.path for choice in dialog.selected_choices()] == [copy1])
    check("pick_reports_undecided", "직접 골라야 할 묶음 1개" in dialog.pick_label.text())
    dialog.clear_all()
    dialog.pick_button.click()
    choices = dialog.selected_choices()
    check("pick_selects_original", [choice.keep.path for choice in choices] == [keep])
    check("pick_label", dialog.pick_label.text() == "원본으로 고른 묶음 1개 · 원본을 정할 수 없어 직접 골라야 할 묶음 1개")
    check("selected_keep", len(choices) == 1 and choices[0].keep.path == keep)
    check("summary_counts", "휴지통으로 보낼 파일 2개" in dialog.summary_label.text())
    with patch("duplicates.dialog.open_file", return_value=None) as opened:
        dialog.tree.itemDoubleClicked.emit(dialog.tree.topLevelItem(0).child(0), 1)
    check("double_click_opens_file", opened.call_args.args == (paths[0],))
    app.processEvents()
    check("capture_dialog", dialog.grab().save(str(args.artifacts / "duplicates_dialog.png")))
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        dialog.remove_button.click()
    check("confirm_no_keeps_dialog", dialog.isVisible())
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        dialog.remove_button.click()


on_dialog(choose_and_remove)
with patch("duplicates.controller.send_to_trash", side_effect=fake_trash), \
        patch.object(QMessageBox, "exec", return_value=QMessageBox.Ok) as shown:
    window.nav_buttons["중복 파일"].click()
check("result_message_shown", shown.called)
check("kept_file_remains", os.path.exists(keep))
check("copies_removed", not os.path.exists(copy1) and not os.path.exists(copy2))
check("unchosen_group_untouched", os.path.exists(photo1) and os.path.exists(photo2) and os.path.exists(unique))
check("tags_moved_to_kept", sorted(storage.read_file_tags([keep])[keep]) == ["거래처", "중요"])
check("removed_tags_cleared", storage.read_file_tags([copy1])[copy1] == ())
check("results_refreshed", sorted(hit.path for hit in window.results.hits) == sorted([keep, photo1, photo2, unique]))
check("status_reports", "휴지통으로 보냄 2개" in window.status_label.text())
check("sidebar_tag_count_updated", {tag.name: tag.file_count for tag in window.tags.tags_by_id.values()} == {"거래처": 1, "중요": 1})


def remove_second(dialog):
    check("only_remaining_group", len(dialog.result.groups) == 1)
    click(dialog, 0, 0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        dialog.remove_button.click()


def locked_trash(path):
    raise OSError("다른 프로그램이 사용 중")


on_dialog(remove_second)
with patch("duplicates.controller.send_to_trash", side_effect=locked_trash), \
        patch.object(QMessageBox, "exec", return_value=QMessageBox.Ok):
    window.nav_buttons["중복 파일"].click()
check("failed_trash_keeps_files", os.path.exists(photo1) and os.path.exists(photo2))
check("failure_reported", "실패 1개" in window.status_label.text())

os.remove(photo2)
with patch.object(QMessageBox, "information") as info:
    window.nav_buttons["중복 파일"].click()
check("no_duplicates_message", info.called and "내용이 같은 파일이 없어요" in window.status_label.text())
# 묶음이 많아도 창이 빨리 뜨는지 재요. 경로만 있는 가짜 결과라 파일은 만들지 않아요.
groups = []
for index in range(3000):
    files = tuple(FileMetadata(str(source / f"큰목록/{index}/{name}"), name, 0, 1000)
                  for name in ("파일.txt", "파일_중복1.txt", "파일_중복2.txt"))
    groups.append(DuplicateGroup(1000, f"{index:064x}", files))
big = DuplicateResult(str(source), groups)
started = time.perf_counter()
dialog = DuplicateDialog(big, window)
dialog.show()
app.processEvents()
opened_seconds = time.perf_counter() - started
started = time.perf_counter()
dialog.pick_button.click()
pick_seconds = time.perf_counter() - started
check("large_list_opens_fast", opened_seconds < 5)
check("large_list_pick", len(dialog.selected_choices()) == 3000)
dialog.reject()
dialog.deleteLater()
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors,
          "large_list": {"groups": 3000, "rows": 9000, "open_seconds": round(opened_seconds, 3),
                         "pick_seconds": round(pick_seconds, 3)}}
(args.artifacts / "duplicates_gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
