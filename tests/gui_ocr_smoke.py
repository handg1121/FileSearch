"""실제 검색 화면에서 OCR·본문 미리보기·캐시·필터·취소를 확인해요."""

import argparse
import json
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from collector.progress_dialog import ProgressDialog
from common import settings
from common.widgets import STYLE
from ocr import reader
from ocr_fixtures import save_image
from tagger import storage
import main

fixture = args.workspace.resolve()
source = fixture / "이미지 폴더"
source.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
settings.SETTINGS_PATH = str(fixture / "profile/settings.json")
settings.set_save_dir(str(source))
a = save_image(source / "스캔문서.png")
b = save_image(source / "납품사진.JPEG", "납품 완료\nDelivery complete")
(source / "메모.txt").write_text("계약금", encoding="utf-8")
(source / "미지원.pdf").write_bytes(b"test")
storage.attach_tags([str(a)], ["중요"])

app = QApplication([])
for name in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font = Path("C:/Windows/Fonts") / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyleSheet(STYLE)
checks, errors, phases = [], [], []
def exception_hook(typ, value, tb):
    errors.append(str(value))
    traceback.print_exception(typ, value, tb)
sys.excepthook = exception_hook
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: (print("OCR GUI timeout", flush=True), os._exit(2)))
watchdog.start(30000)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


window = main.MainWindow()
window.show()
window.search_bar.name_check.setChecked(False)
window.search_bar.content_check.setChecked(True)
window.search_bar.keyword_input.setText("계약금")
real_status = ProgressDialog.set_status


def track_progress(dialog, text):
    phases.append((text, QThread.currentThread() == app.thread()))
    real_status(dialog, text)


with patch.object(ProgressDialog, "set_status", track_progress):
    window.run_search()
check("ocr_and_text_results", {Path(hit.path).name for hit in window.results.hits} == {"스캔문서.png", "메모.txt"})
check("ocr_progress_visible_on_main_thread", any("이미지 글자 인식 중" in p[0] for p in phases) and all(p[1] for p in phases))
check("ocr_support_hint", "이미지 OCR" in window.search_bar.content_hint.text())
check("first_read_and_unsupported_counts", "본문 갱신 3개" in window.status_label.text() and "본문 미지원 1개" in window.status_label.text())
row = next(i for i, hit in enumerate(window.results.table.hits) if hit.path == str(a))
window.results.table.setCurrentCell(row, 1)
app.processEvents()
check("image_text_preview", "계약금" in window.preview.body.toPlainText() and "Invoice" in window.preview.body.toPlainText())
check("image_tag_preserved", window.results.table.tags_by_path[str(a)] == ("중요",))
check("ocr_search_screenshot", window.grab().save(str(args.artifacts / "ocr_search.png")))
with patch.object(reader, "_recognize", side_effect=AssertionError("Cached images must not run OCR")):
    window.run_search()
check("repeat_search_reuses_cache", "본문 갱신 0개" in window.status_label.text() and "재사용 3개" in window.status_label.text())
window.search_bar.type_combo.blockSignals(True)
window.search_bar.type_combo.setCurrentText("이미지")
window.search_bar.type_combo.blockSignals(False)
window.run_search()
check("image_filter_excludes_text_file", [hit.path for hit in window.results.hits] == [str(a)])
window.search_bar.keyword_input.setText("Delivery")
window.run_search()
check("uppercase_jpeg_and_english_body", [hit.path for hit in window.results.hits] == [str(b)])
save_image(a, "검수 완료\nInspection passed")
window.search_bar.keyword_input.setText("Inspection")
with patch.object(reader, "_recognize", wraps=reader._recognize) as recognize:
    window.run_search()
check("only_modified_image_runs_ocr", recognize.call_count == 1)
check("modified_search_uses_new_text", [hit.path for hit in window.results.hits] == [str(a)] and "재사용 1개" in window.status_label.text())
window.search_bar.keyword_input.setText("계약금")
window.run_search()
check("old_image_text_no_longer_matches", not window.results.hits)

save_image(source / "취소시험.png")
cancelled = []
def cancel_when_ocr_starts(dialog, text):
    real_status(dialog, text)
    if "이미지 글자 인식 중" in text and not cancelled:
        cancelled.append(True)
        QTimer.singleShot(0, dialog.request_cancel)


with patch.object(ProgressDialog, "set_status", cancel_when_ocr_starts):
    window.run_search()
check("ui_processed_cancel", bool(cancelled) and "취소했어요" in window.status_label.text())
check("cancel_does_not_show_partial_results", not window.results.hits)
window.run_search()
check("cancelled_image_can_retry", [Path(hit.path).name for hit in window.results.hits] == ["취소시험.png"])
(source / "깨진이미지.png").write_bytes(b"not an image")
window.run_search()
check("broken_image_reported_without_stopping_search", "확인 실패 1건" in window.status_label.text()
      and "깨진이미지.png" in window.status_label.toolTip() and len(window.results.hits) == 1)
(source / "깨진이미지.png").unlink()
window.close()
window = main.MainWindow()
window.show()
window.search_bar.name_check.setChecked(False)
window.search_bar.content_check.setChecked(True)
window.search_bar.keyword_input.setText("Inspection")
with patch.object(reader, "_recognize", side_effect=AssertionError("Cache must survive restart")):
    window.run_search()
check("ocr_cache_survives_restart", [hit.path for hit in window.results.hits] == [str(a)])
check("tags_survive_restart", window.results.table.tags_by_path[str(a)] == ("중요",))
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts / "ocr_gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
