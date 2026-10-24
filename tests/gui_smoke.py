"""복원 후 추가한 GUI 통합 검사예요. 테스트 폴더만 탐색·복사해요."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
parser.add_argument("--source-root", type=Path)
args = parser.parse_args()
sys.path.insert(0, str((args.source_root or Path(__file__).resolve().parents[1]).resolve()))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog
from common import settings
from common.widgets import STYLE

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
settings.SETTINGS_PATH = str(fixture / "profile" / "settings.json")
source = fixture / "source"
target = fixture / "target"
source.mkdir(exist_ok=True)
target.mkdir(exist_ok=True)
for name, content in (("계약서_샘플.txt", b"contract"), ("계약_검토.txt", b"review"), ("메모.txt", b"memo")):
    (source / name).write_bytes(content)
settings.set_save_dir(str(source))

import main
from collector.collector import CollectDialog
from collector.summary_dialog import SummaryDialog
from collector.result_dialog import ResultDialog
from collector.progress_dialog import ProgressDialog
from collector import type_selector_script as core
from searcher.result_table import COL_CHECK, highlight

app = QApplication([])
for font_file in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font_file
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyleSheet(STYLE)
errors = []
sys.excepthook = lambda typ, value, tb: errors.append(f"{typ.__name__}: {value}")
checks = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

def capture(widget, name):
    widget.show()
    app.processEvents()
    check("capture:" + name, widget.grab().save(str(args.artifacts / name)))

window = main.MainWindow()
capture(window, "main_window.png")
window.search_bar.keyword_input.setText("계약")
with patch.object(main.time, "perf_counter", side_effect=[1.0, 1.125]):
    window.run_search()
check("search_two_hits", len(window.results.hits) == 2)
table = window.results.table
table.setCurrentCell(0, 1)
app.processEvents()
check("preview_selection", window.preview.hit == table.hits[0])
table.item(0, COL_CHECK).setCheckState(Qt.Checked)
check("checked_count", window.selected_count_label.text() == "1개 선택")
window.results.sort_combo.setCurrentText("이름순")
check("sort_resets_selection", window.selected_count_label.text() == "0개 선택")
table.setCurrentCell(0, 1)
capture(window, "search_results.png")
check("escaped_highlight", highlight("<ABC> & abc", ["abc"]) == "&lt;<b>ABC</b>&gt; &amp; <b>abc</b>")

dialog = CollectDialog(window)
dialog.folder_radio.setChecked(True)
dialog.source_input.setText(str(source))
dialog.target_input.setText(str(target))
dialog.save_target()
check("saved_target", settings.get_save_dir() == str(target))
dialog.type_selector.set_all(False)
check("no_types_disables_find", not dialog.find_button.isEnabled())
for tile in dialog.type_selector.tiles:
    if tile.ext == "txt": tile.setChecked(True)
check("one_type_enables_find", dialog.find_button.isEnabled())
check("selected_source", dialog.selected_sources() == [str(source)])
check("selected_target", dialog.selected_target() == str(target))
capture(dialog, "collect_dialog.png")
dialog.hide()

# 실제 스레드 및 모달 진행 창을 통과해요. 타임아웃은 실패로 기록해요.
timed_out = []
def abort_hung_dialog():
    timed_out.append(True)
    app.exit(1)
timer = QTimer()
timer.setSingleShot(True)
timer.timeout.connect(abort_hung_dialog)
timer.start(15000)
items = dialog.scan([str(source)], str(target))
check("scan_thread", items is not None and len(items) == 3)
summary = SummaryDialog(items, str(target), window)
capture(summary, "summary_dialog.png")
summary.hide()
result = dialog.collect(items, str(target), core.MODE_COPY)
timer.stop()
check("collect_thread", result is not None and result.done == 3 and not result.failed)
for item in items:
    check("copied_content:" + Path(item.src).name,
          Path(item.target).read_bytes() == Path(item.src).read_bytes())
finished = ResultDialog(result, str(target), window)
capture(finished, "result_dialog.png")
finished.close()

progress = ProgressDialog("취소 검사", window)
canceled = []
progress.cancel_requested.connect(lambda: canceled.append(True))
progress.reject()
check("progress_cancellation", canceled == [True] and not progress.cancel_button.isEnabled())
progress.accept()
check("no_timeout", not timed_out)
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts / "gui_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
