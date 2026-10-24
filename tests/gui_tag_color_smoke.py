"""실제 태그 더블클릭·우클릭 메뉴·색 선택 창과 결과 갱신을 검사해요."""

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

from PySide6.QtCore import QLibraryInfo, Qt, QTimer, QTranslator
from PySide6.QtGui import QColor, QContextMenuEvent, QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QMenu
from common import settings
from common.widgets import STYLE
from searcher.result_table import COL_CHECK, COL_TAGS
from tagger import storage
from tagger.badges import BADGES_ROLE
from tagger.colors import DEFAULT_TAG_COLOR
from tagger.dialogs import RemoveTagsDialog, TagColorDialog
import main

fixture = args.workspace.resolve()
fixture.mkdir(parents=True, exist_ok=True)
args.artifacts.mkdir(parents=True, exist_ok=True)
source = fixture/'source'
source.mkdir(exist_ok=True)
outside = fixture/'other-folder'
outside.mkdir(exist_ok=True)
a, b, c = str(source/'계약서.txt'), str(source/'도면.pdf'), str(outside/'회의록.txt')
for path in (a, b, c):
    Path(path).write_text("본문 내용", encoding="utf-8")
settings.SETTINGS_PATH = str(fixture/'profile/settings.json')
settings.set_save_dir(str(source))
storage.attach_tags([a, c], ["중요"])
storage.attach_tags([a, b], ["검토중"])
empty_id = storage.create_tag("빈 태그").id
important_id = next(tag.id for tag in storage.show_tag() if tag.name == "중요")
app = QApplication([])
translator = QTranslator(app)
assert translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
app.installTranslator(translator)
watchdog = QTimer()
watchdog.setSingleShot(True)
watchdog.timeout.connect(lambda: (print("Color GUI test timed out", flush=True), os._exit(2)))
watchdog.start(30000)
for name in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font = Path(os.environ.get("WINDIR", "C:/Windows"))/'Fonts'/name
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


def sidebar_item(tag_id):
    items = window.tag_sidebar.tag_list
    return next(items.item(row) for row in range(items.count()) if items.item(row).data(Qt.UserRole) == tag_id)


def double_click_tag(tag_id):
    items = window.tag_sidebar.tag_list
    item = sidebar_item(tag_id)
    items.scrollToItem(item)
    app.processEvents()
    pos = items.visualItemRect(item).center()
    QTest.mouseClick(items.viewport(), Qt.LeftButton, pos=pos)
    QTest.mouseDClick(items.viewport(), Qt.LeftButton, pos=pos)
    app.processEvents()


def choose_color(tag_id, color, accept):
    items = window.tag_sidebar.tag_list
    item = sidebar_item(tag_id)
    items.scrollToItem(item)
    app.processEvents()
    pos = items.visualItemRect(item).center()
    def use_picker():
        dialog = app.activeModalWidget()
        check("color_picker_opened", isinstance(dialog, TagColorDialog))
        check("picker_uses_saved_color", dialog.currentColor().name() == next(tag.color for tag in storage.show_tag() if tag.id == tag_id))
        dialog.setCurrentColor(QColor(color))
        app.processEvents()
        if accept:
            check("capture_color_picker", dialog.grab().save(str(args.artifacts/'tag_color_dialog.png')))
            dialog.accept()
        else:
            dialog.reject()
    def use_menu():
        menu = app.activePopupWidget()
        if not isinstance(menu, QMenu):
            QTimer.singleShot(10, use_menu)
            return
        check("context_menu_color_action", [action.text() for action in menu.actions()] == ["색 변경"])
        action = menu.actions()[0]
        QTimer.singleShot(0, use_picker)
        QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())
    QTimer.singleShot(0, use_menu)
    event = QContextMenuEvent(QContextMenuEvent.Mouse, pos, items.viewport().mapToGlobal(pos))
    QApplication.sendEvent(items.viewport(), event)
    app.processEvents()


window = main.MainWindow()
window.show()
app.processEvents()
check("bottom_check_list_removed", not window.tag_bar.findChildren(QListWidget))
check("compact_tag_bar", window.tag_bar.height() < 100)
check("all_tags_start_red", all(tag.color == DEFAULT_TAG_COLOR for tag in storage.show_tag()))
window.search_bar.keyword_input.setText("해당하지 않는 검색어")
window.search_bar.name_check.setChecked(False)
window.search_bar.content_check.setChecked(False)
for combo, value in ((window.search_bar.type_combo, "한글"), (window.search_bar.date_combo, "오늘")):
    combo.blockSignals(True)
    combo.setCurrentText(value)
    combo.blockSignals(False)
with patch("searcher.search_pipeline.read_file_metadata", side_effect=AssertionError("Tag lookup should not scan folders")):
    double_click_tag(important_id)
check("double_click_direct_lookup", {hit.path for hit in window.results.hits} == {a, c})
check("tag_filter_title", window.results.title_label.text() == "검색 결과 · 중요")
check("active_tag_selected", window.active_tag_id == important_id and sidebar_item(important_id).isSelected())
check("search_input_not_needed", window.search_bar.keyword_input.text() == "해당하지 않는 검색어")
row_a = next(row for row, hit in enumerate(window.results.table.hits) if hit.path == a)
window.results.table.setCurrentCell(row_a, 1)
window.results.table.item(row_a, COL_CHECK).setCheckState(Qt.Checked)
choose_color(important_id, "#2563eb", True)
check("changed_color_persisted", next(tag.color for tag in storage.show_tag() if tag.id == important_id) == "#2563eb")
check("sidebar_color_updated", sidebar_item(important_id).data(BADGES_ROLE) == [["중요", "#2563eb"]] or sidebar_item(important_id).data(BADGES_ROLE) == [("중요", "#2563eb")])
check("result_badges_updated", ("중요", "#2563eb") in [tuple(pair) for pair in window.results.table.item(row_a, COL_TAGS).data(BADGES_ROLE)])
check("preview_badges_updated", window.preview.tags_label.colors["중요"] == "#2563eb")
check("color_change_preserves_file_selection", window.results.table.item(row_a, COL_CHECK).checkState() == Qt.Checked)
check("color_change_preserves_tag_filter", window.active_tag_id == important_id and len(window.results.hits) == 2)
choose_color(important_id, "#16a34a", False)
check("cancel_keeps_color", next(tag.color for tag in storage.show_tag() if tag.id == important_id) == "#2563eb")
app.processEvents()
check("capture_colored_main", window.grab().save(str(args.artifacts/'colored_tag_view.png')))
window.close()
window = main.MainWindow()
window.show()
app.processEvents()
check("color_survives_restart", window.tags.colors["중요"] == "#2563eb")
double_click_tag(important_id)
check("shortcut_works_before_search", {hit.path for hit in window.results.hits} == {a, c})
row_a = next(row for row, hit in enumerate(window.results.table.hits) if hit.path == a)
window.results.table.item(row_a, COL_CHECK).setCheckState(Qt.Checked)


def detach_active_tag():
    dialog = app.activeModalWidget()
    check("remove_dialog_preserved", isinstance(dialog, RemoveTagsDialog))
    for row in range(dialog.choices.count()):
        if dialog.choices.item(row).data(Qt.UserRole) == important_id:
            dialog.choices.item(row).setCheckState(Qt.Checked)
    dialog.remove_button.click()


QTimer.singleShot(0, detach_active_tag)
window.tag_bar.detach_button.click()
check("active_view_refreshes_after_detach", [hit.path for hit in window.results.hits] == [c])
check("other_tag_is_preserved", storage.read_file_tags([a])[a] == ("검토중",))
double_click_tag(empty_id)
check("empty_tag_shows_empty_results", window.active_tag_id == empty_id and window.results.hits == [])
double_click_tag(important_id)
storage.delete_tag([important_id])
window.tags.refresh()
check("deleted_active_tag_clears_view", window.active_tag_id is None and window.results.hits == [])
window.search_bar.keyword_input.clear()
window.search_bar.name_check.setChecked(True)
for combo in (window.search_bar.type_combo, window.search_bar.date_combo):
    combo.blockSignals(True)
    combo.setCurrentIndex(0)
    combo.blockSignals(False)
window.run_search()
check("normal_search_restored", {hit.path for hit in window.results.hits} == {a, b})
check("normal_search_title", window.results.title_label.text() == "검색 결과")
check("no_qt_slot_errors", not errors)
window.close()
app.processEvents()
report = {"passed": len(checks), "checks": checks, "qt_slot_errors": errors}
(args.artifacts/'tag_color_gui_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
