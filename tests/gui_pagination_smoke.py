"""실제 검색·태그·미리보기를 연결해 페이지 이동과 500개 이후 결과를 검사해요."""

import argparse
import json
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--artifacts', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from common import settings
from common.widgets import STYLE
from searcher.result_table import COL_CHECK, COL_NAME, COL_TAGS
from tagger import storage
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
settings.SETTINGS_PATH = str(fixture / 'profile/settings.json')
root = fixture / 'source'
root.mkdir(exist_ok=True)
settings.set_save_dir(str(root))
files = []
for index in range(623):
    path = root / f'문서_{index:04d}.txt'
    path.write_text(f'페이지 검사 문서 {index}\n' + 'x' * index, encoding='utf-8')
    os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    files.append(str(path))
storage.attach_tags(files[50:113], ['검토'])
tag = next(tag for tag in storage.show_tag() if tag.name == '검토')
storage.set_tag_color(tag.id, '#2563eb')

app = QApplication([])
for name in ('malgun.ttf', 'malgunbd.ttf', 'seguisym.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
app.setFont(QFont('Malgun Gothic', 10))
app.setStyleSheet(STYLE)
checks, errors = [], []


def report_error(typ, value, tb):
    errors.append(str(value))
    traceback.print_exception(typ, value, tb)


sys.excepthook = report_error
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: os._exit(2))
watchdog.start(60000)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


window = main.MainWindow()
window.show()
app.processEvents()
panel = window.results
table = panel.table
bar = window.search_bar
bar.name_check.setChecked(True)
bar.content_check.setChecked(False)
bar.tag_check.setChecked(False)


def visible_paths():
    return [hit.path for hit in table.hits]


def capture(name):
    app.processEvents()
    check('capture:' + name, panel.grab().save(str(args.artifacts / name)))


check('default_50_and_exact_options', panel.page_size == 50 and
      [panel.page_size_combo.itemData(i) for i in range(panel.page_size_combo.count())] == [10, 30, 50, 100, 300, 500])
check('initial_empty_state', table.rowCount() == 0 and panel.page_input.value() == 0 and
      panel.page_count == 0 and not panel.next_button.isEnabled())
window.nav_buttons['전체 파일'].click()
check('all_files_default_page', len(panel.hits) == 623 and table.rowCount() == 50 and
      panel.page_count == 13 and panel.page_input.value() == 1)
check('range_and_total', panel.range_label.text() == '1–50 / 623개' and panel.count_label.text() == '623개')
check('first_boundary', not panel.first_button.isEnabled() and not panel.previous_button.isEnabled())
check('global_modified_sort', visible_paths() == list(reversed(files))[:50])
panel.last_button.click()
check('last_page_tail', visible_paths() == list(reversed(files))[600:] and panel.page_input.value() == 13)
check('last_boundary', not panel.next_button.isEnabled() and not panel.last_button.isEnabled())
panel.previous_button.click()
check('previous_page', panel.page_input.value() == 12 and table.rowCount() == 50)
panel.first_button.click()
panel.next_button.click()
check('first_and_next', panel.page_input.value() == 2 and visible_paths() == list(reversed(files))[50:100])

panel.sort_combo.setCurrentText('이름순')
check('sort_returns_to_first', panel.page_input.value() == 1 and visible_paths() == files[:50])
table.setCurrentCell(0, COL_NAME)
table.item(0, COL_CHECK).setCheckState(Qt.Checked)
table.scrollToBottom()
check('selected_before_navigation', window.preview.hit.path == files[0] and window.selected_count_label.text() == '1개 선택')
with patch('searcher.result_table.sort_hits', side_effect=AssertionError('Page turns must reuse the sorted results')):
    panel.next_button.click()
check('selection_and_preview_clear', not table.checked_hits() and window.preview.hit is None and
      table.currentRow() == -1 and window.selected_count_label.text() == '0개 선택')
check('page_starts_at_top', table.verticalScrollBar().value() == 0)
check('page_two_tag_badges', all(table.item(row, COL_TAGS).text() == '검토' for row in range(50)))
table.setCurrentCell(0, COL_NAME)
check('page_two_preview_and_color', window.preview.hit.path == files[50] and window.preview.tags_label.colors['검토'] == '#2563eb')
table.item(0, COL_CHECK).setCheckState(Qt.Checked)
window.tag_bar.tag_input.setText('두번째 페이지')
window.tags.attach_selected()
check('attach_only_visible_selected_file', '두번째 페이지' in storage.read_file_tags([files[50]])[files[50]] and
      '두번째 페이지' not in storage.read_file_tags([files[0]]).get(files[0], []))
check('tag_refresh_keeps_page', panel.page_input.value() == 2 and visible_paths() == files[50:100])
capture('pagination.png')

panel.page_input.setFocus()
panel.page_input.selectAll()
QTest.keyClicks(panel.page_input, '7')
check('typing_waits_for_commit', panel.page_input.value() == 2)
QTest.keyClick(panel.page_input, Qt.Key_Return)
check('jump_to_typed_page', panel.page_input.value() == 7 and visible_paths() == files[300:350])
seen = []
panel.first_button.click()
while True:
    seen.extend(visible_paths())
    if not panel.next_button.isEnabled():
        break
    panel.next_button.click()
check('every_result_reachable_once', seen == files and len(set(seen)) == 623)

for size in (10, 30, 50, 100, 300, 500):
    panel.page_size_combo.setCurrentIndex(panel.page_size_combo.findData(size))
    expected_pages = (623 + size - 1) // size
    check(f'page_size_{size}_first', panel.page_input.value() == 1 and visible_paths() == files[:size] and panel.page_count == expected_pages)
    panel.last_button.click()
    check(f'page_size_{size}_last', visible_paths() == files[(expected_pages - 1) * size:] and not panel.next_button.isEnabled())

bar.keyword_input.setText('문서_0001')
window.run_search()
check('new_search_resets_page_keeps_size', visible_paths() == [files[1]] and panel.page_input.value() == 1 and panel.page_size == 500)
bar.keyword_input.setText('없는파일')
window.run_search()
check('empty_search_resets_controls', panel.page_count == 0 and panel.page_input.value() == 0 and
      not panel.page_input.isEnabled() and panel.range_label.text() == '0개' and
      all(not button.isEnabled() for button in (panel.first_button, panel.previous_button, panel.next_button, panel.last_button)))
capture('pagination_empty.png')

panel.page_size_combo.setCurrentIndex(panel.page_size_combo.findData(50))
window.run_search(tag.id)
check('tag_filter_first_page', len(panel.hits) == 63 and panel.page_count == 2 and panel.tag_filter == '검토')
panel.next_button.click()
check('tag_filter_second_page', visible_paths() == files[100:113] and panel.tag_filter == '검토' and window.active_tag_id == tag.id)
window.nav_buttons['전체 파일'].click()
check('all_files_exits_tag_and_resets_page', panel.page_input.value() == 1 and len(panel.hits) == 623 and
      panel.tag_filter is None and window.active_tag_id is None and bar.keyword_input.text() == '')
panel.sort_combo.setCurrentText('크기순')
panel.next_button.click()
check('global_size_sort', visible_paths() == list(reversed(files))[50:100])
with patch('searcher.result_table.open_file', return_value=None) as opened:
    table.cellDoubleClicked.emit(0, COL_NAME)
    check('file_open_uses_current_page', opened.call_args.args == (files[-51],))
window.resize(1280, 800)
capture('pagination_narrow.png')
check('footer_controls_visible', panel.last_button.geometry().right() < panel.width() and
      panel.range_label.width() >= panel.range_label.fontMetrics().horizontalAdvance(panel.range_label.text()))
check('page_number_has_room_to_render', panel.page_input.lineEdit().width() >=
      panel.page_input.lineEdit().fontMetrics().horizontalAdvance(panel.page_input.text()) + 8)
check('no_qt_slot_errors', not errors)
window.close()
report = {'passed': len(checks), 'checks': checks, 'errors': errors}
(args.artifacts / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
