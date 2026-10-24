"""검색 작업 스레드·본문 결과·취소를 실제 GUI 흐름으로 검사해요."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from zipfile import ZipFile

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from common import settings
from common.widgets import STYLE
from collector.progress_dialog import ProgressDialog
from searcher import body_cache
from searcher.metadata import check_cancelled
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
source = fixture / "source"
source.mkdir(exist_ok=True)
settings.SETTINGS_PATH = str(fixture / "profile/settings.json")
settings.set_save_dir(str(source))
for name, text in (("견적_안내.txt", "선급계약금을 지불한다. 잔금은 납품 후 지급한다."),
                   ("계약금_파일명.txt", "납품 안내"), ("메모.txt", "회의는 내일 진행한다.")):
    (source / name).write_text(text, encoding="utf-8")
with ZipFile(source / "공사_특약.hwpx", "w") as archive:
    archive.writestr("Contents/section0.xml", '<hs:sec xmlns:hs="section" xmlns:hp="paragraph"><hp:p><hp:run><hp:t>계약금 지급 후 작업을 시작한다.</hp:t></hp:run></hp:p></hs:sec>')
(source / "미지원.pdf").write_bytes(b"test fixture")

app = QApplication([])
for name in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyleSheet(STYLE)
errors, checks = [], []
sys.excepthook = lambda typ, value, tb: errors.append(f"{typ.__name__}: {value}")


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


window = main.MainWindow()
window.show()
window.search_bar.name_check.setChecked(False)
window.search_bar.content_check.setChecked(True)
window.search_bar.keyword_input.setText("계약금")
thread_checks = []
original_status = ProgressDialog.set_status


def check_status_thread(dialog, text):
    thread_checks.append(QThread.currentThread() == app.thread())
    original_status(dialog, text)


with patch.object(ProgressDialog, "set_status", check_status_thread):
    window.run_search()
check("body_only_two_hits", len(window.results.hits) == 2)
check("filename_only_match_excluded", all("파일명" not in hit.name for hit in window.results.hits))
check("unsupported_reported", "본문 미지원 1개" in window.status_label.text())
check("progress_updates_on_ui_thread", bool(thread_checks) and all(thread_checks))
window.results.table.setCurrentCell(0, 1)
app.processEvents()
check("body_preview", "계약금" in window.preview.body.toPlainText())
check("screen_capture", window.grab().save(str(args.artifacts / "body_search.png")))
window.run_search()
check("cache_reused", "재사용 4개" in window.status_label.text())
window.search_bar.keyword_input.setText("계약금을 지불한다")
window.run_search()
check("phrase_match", len(window.results.hits) == 1)
window.search_bar.keyword_input.setText("계약금")
window.search_bar.name_check.setChecked(True)
window.run_search()
check("or_search_three_hits", len(window.results.hits) == 3)
window.search_bar.content_check.setChecked(False)
window.run_search()
check("name_only_one_hit", len(window.results.hits) == 1)
window.results.table.setCurrentCell(0, 1)
check("name_only_clears_body_preview", not window.preview.body.toPlainText())
window.search_bar.name_check.setChecked(False)
window.run_search()
check("no_selection_message", "하나 이상" in window.status_label.text())
check("no_selection_clears_results", not window.results.hits)

# 느린 추출 중에도 UI 타이머가 실행되고 실제 취소 신호가 전달되는지 확인해요.
window.search_bar.content_check.setChecked(True)
(source / "느린파일.txt").write_text("계약금 새 문서", encoding="utf-8")
real_extract = body_cache.extract_file_body
ticks = []


def slow_extract(path, *, should_stop):
    for _ in range(1000):
        check_cancelled(should_stop)
        time.sleep(0.002)
    return real_extract(path, should_stop=should_stop)


def cancel_search():
    ticks.append(True)
    for widget in app.topLevelWidgets():
        if isinstance(widget, ProgressDialog) and widget.isVisible():
            widget.request_cancel()


QTimer.singleShot(80, cancel_search)
with patch.object(body_cache, "extract_file_body", slow_extract):
    window.run_search()
check("ui_remains_responsive", bool(ticks))
check("worker_cancelled", "취소했어요" in window.status_label.text())
check("cancel_does_not_show_partial_results", not window.results.hits)
window.run_search()
check("retry_after_cancel", len(window.results.hits) == 3)
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts / "body_gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
