"""네이티브 아이콘·대체 아이콘·비동기 갱신과 실제 공통 화면을 검증해요."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

parser = argparse.ArgumentParser()
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--artifacts', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QWidget
from common import settings
from common.file_icons import FILE_TYPES, FileIconProvider, FileTypeIcon, file_extension, icon_provider, is_visible_icon, load_windows_icon
from common.widgets import STYLE
from searcher.result_table import COL_NAME
from collector.collector import CollectDialog
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
settings.SETTINGS_PATH = str(fixture / 'profile/settings.json')
folder = fixture / 'source'
folder.mkdir(exist_ok=True)
for name in ('계약서.pdf', '발표자료.pptx', '문서.docx', '정산.xlsx', '메모.txt', '보고서.hwp', '자료.filesearch_unknown_987a725c', 'README'):
    (folder/name).write_text('icon fixture', encoding='utf-8')
settings.set_save_dir(str(folder))
app = QApplication([])
for filename in ('malgun.ttf', 'malgunbd.ttf', 'seguisym.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/filename))
app.setFont(QFont('Malgun Gothic', 10))
app.setStyleSheet(STYLE)
checks, errors = [], []
def report_error(typ, value, tb):
    errors.append(f'{typ.__name__}: {value}')
    traceback.print_exception(typ, value, tb)

sys.excepthook = report_error


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def wait_for(condition):
    deadline = time.monotonic() + 15
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for icon loading')
        QTest.qWait(10)
    app.processEvents()


def capture(widget, name):
    widget.show()
    app.processEvents()
    check('capture:' + name, widget.grab().save(str(args.artifacts/name)))


check('extension_normalized', file_extension(r'C:\폴더.pdf\자료.PDF') == 'pdf')
check('explicit_extension', file_extension('.pptx') == 'pptx')
check('no_extension_is_generic', file_extension('README') == '' and file_extension('txt') == '')
check('parent_extension_ignored', file_extension(r'C:\folder.pdf\README') == '')

# 늦은 결과·실패·중복 요청을 실제 작업 스레드로 확인해요.
calls = Counter()
worker_threads = []
blank_cases = {
    'transparent': QColor(0, 0, 0, 0),
    'white': QColor(255, 255, 255, 255),
    'pale': QColor(250, 250, 250, 255),
    'faint': QColor(0, 0, 0, 4),
}
release = threading.Event()

def controlled_loader(ext):
    calls[ext] += 1
    worker_threads.append(QThread.currentThread() != app.thread())
    if ext == 'pdf':
        release.wait(5)
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(QColor('#2255dd'))
        return image
    if ext in blank_cases:
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(blank_cases[ext])
        return image
    if ext == 'pptx':
        raise OSError('Simulated Windows icon error')
    return QImage()

provider = FileIconProvider(app, loader=controlled_loader)
try:
    icon = FileTypeIcon('first.pdf', provider=provider)
    for _ in range(500):
        provider.icon_for('pdf')
    check('fallback_while_loading', not icon.pixmap().isNull() and icon.property('iconSource') == 'builtin')
    icon.set_file_name('now.txt')
    before = icon.pixmap().toImage()
    release.set()
    wait_for(lambda: not provider.pending)
    check('native_request_cached_for_500_files', calls['pdf'] == 1)
    check('native_load_off_ui_thread', all(worker_threads))
    check('late_result_does_not_replace_current_file', icon.extension == 'txt' and icon.pixmap().toImage() == before)
    check('missing_native_uses_builtin', provider.sources['txt'] == 'builtin')
    icon.set_file_name('again.PDF')
    check('cached_native_applied', icon.property('iconSource') == 'windows' and calls['pdf'] == 1)
    icon.set_file_name('slides.pptx')
    wait_for(lambda: not provider.pending)
    check('native_error_keeps_builtin', icon.property('iconSource') == 'builtin' and not icon.pixmap().isNull())
    icon.set_file_name('README')
    check('generic_needs_no_native_request', '' not in calls and not icon.pixmap().isNull())
    for ext in blank_cases:
        icon.set_file_name('invisible.' + ext)
        expected = icon.pixmap().toImage()
        wait_for(lambda: not provider.pending)
        check('invisible_native_falls_back:' + ext,
              icon.property('iconSource') == 'builtin' and icon.pixmap().toImage() == expected)
    icon.set_file_name('visible.pdf')
    check('visible_native_still_preserved', icon.property('iconSource') == 'windows')
finally:
    release.set()
    provider.pool.waitForDone(15000)

# 실제 Windows 연결 아이콘을 검색 결과·미리보기·수집 유형 화면에서 확인해요.
window = main.MainWindow()
window.show()
window.run_search()
shared = icon_provider()
wait_for(lambda: not shared.pending)
check('all_fixture_documents_found', len(window.results.hits) == 8)
row_icons = {}
for row, hit in enumerate(window.results.table.hits):
    cell = window.results.table.cellWidget(row, COL_NAME)
    label = cell.findChild(FileTypeIcon)
    check('row_icon:' + hit.name, label is not None and not label.pixmap().isNull())
    row_icons[hit.name] = label.property('iconSource')
    check('row_icon_visible:' + hit.name, is_visible_icon(label.pixmap().toImage()))
    if hit.name == '메모.txt':
        window.results.table.setCurrentCell(row, COL_NAME)
app.processEvents()
check('preview_uses_shared_icon', window.preview.icon.extension == 'txt' and
      window.preview.icon.pixmap().toImage() == shared.icon_for('txt').pixmap(
          window.preview.icon.size(), window.preview.icon.devicePixelRatioF()).toImage())
check('unknown_uses_builtin', row_icons['자료.filesearch_unknown_987a725c'] == 'builtin')
check('no_extension_uses_builtin', row_icons['README'] == 'builtin')
for name in ('발표자료.pptx', '문서.docx', '정산.xlsx'):
    native = load_windows_icon(file_extension(name))
    expected = 'windows' if is_visible_icon(native) else 'builtin'
    check('actual_office_icon_checked:' + name, row_icons[name] == expected)
capture(window, 'windows_file_icons.png')
collect = CollectDialog(window)
collect.show()
wait_for(lambda: not shared.pending)
check('collector_uses_shared_provider', all(tile.findChild(FileTypeIcon).provider is shared for tile in collect.type_selector.tiles))
capture(collect, 'windows_type_icons.png')
collect.close()

# 설치 프로그램이 없는 PC에서도 내장 아이콘만으로 모든 지원 유형을 표시해요.
fallback = FileIconProvider(app, loader=lambda ext: QImage())
gallery = QWidget()
gallery.setStyleSheet('background: white;')
layout = QGridLayout(gallery)
labels = []
for index, ext in enumerate([*FILE_TYPES, 'unknown']):
    label = FileTypeIcon('.' + ext, size=56, provider=fallback)
    labels.append(label)
    layout.addWidget(label, (index // 7) * 2, index % 7, Qt.AlignCenter)
    caption = QLabel(ext)
    caption.setAlignment(Qt.AlignCenter)
    layout.addWidget(caption, (index // 7) * 2 + 1, index % 7)
gallery.resize(650, 240)
gallery.show()
wait_for(lambda: not fallback.pending)
check('all_embedded_icons_available', all(not label.pixmap().isNull() and label.property('iconSource') == 'builtin' for label in labels))
capture(gallery, 'embedded_file_icons.png')
provider.shutdown()
provider.icon_for('after_shutdown')
check('shutdown_stops_new_native_requests', not provider.pending and 'after_shutdown' not in calls)
check('no_qt_slot_errors', not errors)
window.close()
gallery.close()
report = {'passed': len(checks), 'checks': checks, 'windows_sources': row_icons, 'errors': errors}
(args.artifacts/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
