"""검색 버튼의 태그명 선택·혼합 검색·필터와 실제 화면 갱신을 검사해요."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
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
from PySide6.QtWidgets import QApplication, QPushButton
from common import settings
from common.widgets import STYLE
from searcher.result_table import COL_TAGS
from tagger import storage
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
settings.SETTINGS_PATH = str(fixture/'profile/settings.json')
root = fixture/'source'
root.mkdir(exist_ok=True)
settings.set_save_dir(str(root))
files = {}
for name, body in (('문서.pdf', 'fixture'), ('계약_이름.txt', '파일명 일치'),
                   ('본문.txt', '계약 내용을 읽어요'), ('계약_공통.txt', '계약 본문'), ('무관.txt', '내용')):
    path = root/name
    path.write_text(body, encoding='utf-8')
    files[name] = str(path)
a, b, c, both, none = (files[name] for name in ('문서.pdf', '계약_이름.txt', '본문.txt', '계약_공통.txt', '무관.txt'))
external = fixture/'외부.pdf'
external.write_bytes(b'fixture')
storage.attach_tags([a, str(external)], ['계약서'])
storage.attach_tags([a], ['계약 검토', '100% 완료'])
storage.attach_tags([both], ['선급계약금'])
storage.attach_tags([none], ['중요'])
contract = next(tag for tag in storage.show_tag() if tag.name == '계약서')
storage.set_tag_color(contract.id, '#2563eb')
os.utime(both, (1000, 1000))

app = QApplication([])
for filename in ('malgun.ttf', 'malgunbd.ttf', 'seguisym.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/filename))
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
watchdog.start(30000)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def paths():
    return {hit.path for hit in window.results.hits}


def choose(name=False, body=False, tag=True):
    window.search_bar.name_check.setChecked(name)
    window.search_bar.content_check.setChecked(body)
    window.search_bar.tag_check.setChecked(tag)


window = main.MainWindow()
window.show()
app.processEvents()
bar = window.search_bar
button = next(widget for widget in bar.findChildren(QPushButton) if widget.text() == '검색')
check('tag_checkbox_enabled', bar.tag_check.isEnabled() and bar.tag_check.text() == '태그명')
choose()
check('tag_placeholder_and_hint', '태그명' in bar.keyword_input.placeholderText() and bar.content_hint.isVisible())
bar.keyword_input.setText('계약')
with patch('searcher.search_pipeline.open_body_cache', side_effect=AssertionError('Tag only must not read body')):
    button.click()
check('tag_only_button_search', paths() == {a, both})
check('current_folder_only', str(external) not in paths())
check('tag_results_not_duplicated', len(window.results.hits) == 2)
row_a = next(row for row, hit in enumerate(window.results.table.hits) if hit.path == a)
window.results.table.setCurrentCell(row_a, 1)
app.processEvents()
check('tag_badges_in_results', '계약서' in window.results.table.item(row_a, COL_TAGS).text())
check('tag_color_in_preview', window.preview.tags_label.colors['계약서'] == '#2563eb')
check('no_body_work_status', '본문 갱신' not in window.status_label.text())
check('tag_query_capture', window.grab().save(str(args.artifacts/'tag_keyword_search.png')))

choose(name=True, body=True)
button.click()
check('three_way_or_search', paths() == {a, b, c, both} and len(window.results.hits) == 4)
row = next(row for row, hit in enumerate(window.results.table.hits) if hit.path == both)
window.results.table.setCurrentCell(row, 1)
check('body_excerpt_preserved', '계약' in window.preview.body.toPlainText())
check('mixed_search_hint', '하나라도' in bar.content_hint.text() and '태그명' in bar.keyword_input.placeholderText())
choose(name=True)
button.click()
check('name_plus_tag', paths() == {a, b, both})
choose(body=True)
button.click()
check('body_plus_tag', paths() == {a, c, both})
choose()
bar.type_combo.setCurrentText('PDF')
check('type_filter_triggers_tag_search', paths() == {a})
bar.type_combo.setCurrentText('전체')
bar.date_combo.setCurrentText('오늘')
check('date_filter_applies', paths() == {a})
bar.reset_filters()
check('reset_filters_keeps_tag_selection', bar.tag_check.isChecked() and paths() == {a, both})
bar.keyword_input.clear()
button.click()
check('empty_query_only_tagged', paths() == {a, both, none})
bar.keyword_input.setText('%')
button.click()
check('literal_percent', paths() == {a})
bar.keyword_input.setText('계약 검토')
button.click()
check('phrase_tag_search', paths() == {a})

window.run_search(contract.id)
check('sidebar_shortcut_ignores_search_options', paths() == {a, str(external)} and window.active_tag_id == contract.id)
bar.keyword_input.setText('계약')
button.click()
check('regular_tag_query_leaves_sidebar_mode', paths() == {a, both} and window.active_tag_id is None)
with patch('searcher.search_pipeline.search_keyword_tag', side_effect=sqlite3.OperationalError('테스트 DB 오류')):
    button.click()
check('database_error_visible', not paths() and '테스트 DB 오류' in window.status_label.text())
button.click()
check('retry_after_database_error', paths() == {a, both})
choose(tag=False)
button.click()
check('no_option_validation', not paths() and '하나 이상' in window.status_label.text())
choose(name=True, tag=False)
button.click()
check('normal_name_search_preserved', paths() == {b, both})
check('no_qt_slot_errors', not errors)
window.close()
report = {'passed': len(checks), 'checks': checks, 'errors': errors}
(args.artifacts/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
