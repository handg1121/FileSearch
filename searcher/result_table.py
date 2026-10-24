'검색 결과 영역: 결과 수·정렬 선택(ResultPanel)과 결과 목록 표(ResultTable)'
import html
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from common.file_actions import open_file, open_folder
from common.widgets import format_size, make_label, make_type_icon, transparent_widget
from searcher.filename_search import SORT_ORDERS, sort_hits

MAX_ROWS = 500
COL_CHECK, COL_NAME, COL_TAGS, COL_MODIFIED, COL_SIZE = range(5)


class ResultPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hits = []
        self.keywords = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.addWidget(make_label("검색 결과", "sectionTitle"))
        self.count_label = make_label("", "muted")
        title_row.addWidget(self.count_label)
        title_row.addStretch()
        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("sortCombo")
        self.sort_combo.addItems(SORT_ORDERS)
        self.sort_combo.currentTextChanged.connect(self.refresh)
        title_row.addWidget(self.sort_combo)
        layout.addLayout(title_row)
        self.table = ResultTable()
        layout.addWidget(self.table, 1)
        layout.addWidget(make_label("더블클릭으로 파일 열기 · 우클릭으로 폴더 열기", "muted"))

    def show_hits(self, hits, keywords):
        self.hits = hits
        self.keywords = keywords
        self.refresh()

    def refresh(self):
        ordered = sort_hits(self.hits, self.sort_combo.currentText())
        self.table.show_hits(ordered[:MAX_ROWS], self.keywords)
        text = f"{len(ordered):,}개"
        if len(ordered) > MAX_ROWS:
            text += f" (처음 {MAX_ROWS}개만 표시, 검색어를 더 넣어 보세요)"
        self.count_label.setText(text)


class ResultTable(QTableWidget):
    current_hit_changed = Signal(object)
    checked_count_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.hits = []
        self.setHorizontalHeaderLabels(["", "파일명", "태그", "수정일", "크기"])
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setFocusPolicy(Qt.NoFocus)
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.setColumnWidth(COL_CHECK, 44)
        self.setColumnWidth(COL_TAGS, 150)
        self.setColumnWidth(COL_MODIFIED, 110)
        self.setColumnWidth(COL_SIZE, 90)
        self.itemSelectionChanged.connect(self.emit_current_hit)
        self.itemChanged.connect(self.on_item_changed)
        self.cellDoubleClicked.connect(self.on_double_click)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def show_hits(self, hits, keywords):
        self.blockSignals(True)
        self.clearContents()
        self.hits = hits
        self.setRowCount(len(hits))
        for row, hit in enumerate(hits):
            self.fill_row(row, hit, keywords)
        self.blockSignals(False)
        self.current_hit_changed.emit(None)
        self.checked_count_changed.emit(0)

    def fill_row(self, row, hit, keywords):
        self.setRowHeight(row, 56)
        check_item = QTableWidgetItem()
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check_item.setCheckState(Qt.Unchecked)
        self.setItem(row, COL_CHECK, check_item)
        self.setItem(row, COL_NAME, QTableWidgetItem())
        self.setCellWidget(row, COL_NAME, build_name_cell(hit, keywords))
        self.setItem(row, COL_TAGS, QTableWidgetItem())
        modified = datetime.fromtimestamp(hit.modified).strftime("%Y.%m.%d")
        self.setItem(row, COL_MODIFIED, QTableWidgetItem(modified))
        self.setItem(row, COL_SIZE, QTableWidgetItem(format_size(hit.size)))

    def checked_hits(self):
        checked = []
        for row, hit in enumerate(self.hits):
            if self.item(row, COL_CHECK).checkState() == Qt.Checked:
                checked.append(hit)
        return checked

    def emit_current_hit(self):
        row = self.currentRow()
        self.current_hit_changed.emit(self.hits[row] if 0 <= row < len(self.hits) else None)

    def on_item_changed(self, item):
        if item.column() == COL_CHECK:
            self.checked_count_changed.emit(len(self.checked_hits()))

    def on_double_click(self, row, column):
        if column != COL_CHECK:
            self.open_and_report(open_file, self.hits[row].path)

    def show_menu(self, pos):
        row = self.rowAt(pos.y())
        if row < 0:
            return
        path = self.hits[row].path
        menu = QMenu(self)
        menu.addAction("파일 열기", lambda: self.open_and_report(open_file, path))
        menu.addAction("폴더 열기", lambda: self.open_and_report(open_folder, path))
        menu.exec(self.viewport().mapToGlobal(pos))

    def open_and_report(self, action, path):
        error = action(path)
        if error:
            QMessageBox.warning(self, "열기", error)


def build_name_cell(hit, keywords):
    '유형 아이콘 + 파일명(검색어 굵게) + 그 아래 원래 폴더'
    cell = transparent_widget()
    row = QHBoxLayout(cell)
    row.setContentsMargins(8, 4, 8, 4)
    row.setSpacing(12)
    row.addWidget(make_type_icon(hit.name))
    text_column = QVBoxLayout()
    text_column.setSpacing(2)
    text_column.addStretch()
    name_label = QLabel(highlight(hit.name, keywords))
    name_label.setStyleSheet("font-size: 10.5pt;")
    text_column.addWidget(name_label)
    folder_label = make_label(hit.folder, "muted")
    folder_label.setStyleSheet("font-size: 8.5pt;")
    text_column.addWidget(folder_label)
    text_column.addStretch()
    row.addLayout(text_column, 1)
    return cell


def highlight(name, keywords):
    '파일명에서 검색어가 들어간 부분을 굵게 (대소문자 무시)'
    lowered = name.lower()
    if len(lowered) != len(name):
        return html.escape(name)
    marked = [False] * len(name)
    for keyword in keywords:
        start = lowered.find(keyword)
        while start != -1:
            for index in range(start, start + len(keyword)):
                marked[index] = True
            start = lowered.find(keyword, start + 1)
    parts = []
    start = 0
    while start < len(name):
        end = start
        while end < len(name) and marked[end] == marked[start]:
            end += 1
        chunk = html.escape(name[start:end])
        parts.append(f"<b>{chunk}</b>" if marked[start] else chunk)
        start = end
    return "".join(parts)
