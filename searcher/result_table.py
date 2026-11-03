'검색 결과 영역: 결과 수·정렬 선택(ResultPanel)과 결과 목록 표(ResultTable)'
import html
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from common.file_actions import open_file, open_folder
from common.widgets import format_size, make_button, make_label, make_type_icon, transparent_widget
from searcher.filename_search import SORT_ORDERS, sort_hits
from tagger.badges import BADGES_ROLE, TagBadgeDelegate
from tagger.colors import DEFAULT_TAG_COLOR

PAGE_SIZES = (10, 30, 50, 100, 300, 500)
DEFAULT_PAGE_SIZE = 50
COL_CHECK, COL_NAME, COL_TAGS, COL_MODIFIED, COL_SIZE = range(5)


class ResultPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hits = []
        self.keywords = []
        self.tag_filter = None
        self.ordered_hits = []
        self.current_page = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title_row = QHBoxLayout()
        self.title_label = make_label("검색 결과", "sectionTitle")
        self.title_label.setTextFormat(Qt.PlainText)
        self.title_label.setMaximumWidth(360)
        title_row.addWidget(self.title_label)
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
        layout.addLayout(self.build_pagination())
        self.render_page()

    def build_pagination(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(make_label("페이지당", "muted"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.setAccessibleName("페이지당 표시 개수")
        self.page_size_combo.setStyleSheet("min-width: 70px; padding: 4px 8px;")
        for size in PAGE_SIZES:
            self.page_size_combo.addItem(f"{size}개", size)
        self.page_size_combo.setCurrentIndex(PAGE_SIZES.index(DEFAULT_PAGE_SIZE))
        self.page_size_combo.currentIndexChanged.connect(self.change_page_size)
        row.addWidget(self.page_size_combo)
        self.range_label = make_label("", "muted")
        row.addWidget(self.range_label)
        row.addStretch()

        def navigation_button(text, accessible_name, callback):
            button = make_button(text, "secondaryButton")
            button.setStyleSheet("padding: 4px 8px;")
            button.setAccessibleName(accessible_name)
            button.setToolTip(accessible_name)
            button.clicked.connect(callback)
            row.addWidget(button)
            return button

        self.first_button = navigation_button("처음", "첫 페이지", lambda: self.go_to_page(0))
        self.previous_button = navigation_button("이전", "이전 페이지", lambda: self.go_to_page(self.current_page - 1))
        self.page_input = QSpinBox()
        self.page_input.setAccessibleName("현재 페이지")
        self.page_input.setToolTip("페이지 번호를 입력하고 Enter를 누르세요.")
        self.page_input.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.page_input.setKeyboardTracking(False)
        self.page_input.setAlignment(Qt.AlignCenter)
        self.page_input.setFixedWidth(64)
        self.page_input.setMinimumHeight(30)
        self.page_input.lineEdit().setStyleSheet("border: none; padding: 0; background: transparent;")
        self.page_input.valueChanged.connect(lambda value: self.go_to_page(value - 1))
        row.addWidget(self.page_input)
        self.page_count_label = make_label("", "muted")
        row.addWidget(self.page_count_label)
        self.next_button = navigation_button("다음", "다음 페이지", lambda: self.go_to_page(self.current_page + 1))
        self.last_button = navigation_button("마지막", "마지막 페이지", lambda: self.go_to_page(self.page_count - 1))
        return row

    @property
    def page_size(self):
        return self.page_size_combo.currentData()

    @property
    def page_count(self):
        return (len(self.ordered_hits) + self.page_size - 1) // self.page_size

    def change_page_size(self):
        self.current_page = 0
        self.render_page()

    def go_to_page(self, page):
        page = max(0, min(page, self.page_count - 1))
        if page != self.current_page:
            self.current_page = page
            self.render_page()

    def set_tag_filter(self, name):
        self.tag_filter = name
        title = f"검색 결과 · {name}" if name else "검색 결과"
        self.title_label.setText(self.title_label.fontMetrics().elidedText(title, Qt.ElideRight, 360))
        self.title_label.setToolTip(f"태그: {name}\n모든 폴더의 파일이에요. 일반 검색을 하면 태그 보기가 해제돼요." if name else "")

    def show_hits(self, hits, keywords):
        self.hits = hits
        self.keywords = keywords
        self.refresh()

    def refresh(self):
        # Sort the complete result once. Page changes only slice this ordered list.
        self.ordered_hits = sort_hits(self.hits, self.sort_combo.currentText())
        self.current_page = 0
        self.render_page()

    def render_page(self):
        total = len(self.ordered_hits)
        pages = self.page_count
        self.current_page = max(0, min(self.current_page, pages - 1))
        start = self.current_page * self.page_size
        end = min(start + self.page_size, total)
        self.count_label.setText(f"{total:,}개")
        self.range_label.setText(f"{start + 1:,}–{end:,} / {total:,}개" if total else "0개")
        previous = self.page_input.blockSignals(True)
        self.page_input.setRange(1 if total else 0, pages)
        self.page_input.setValue(self.current_page + 1 if total else 0)
        self.page_input.blockSignals(previous)
        self.page_input.setEnabled(bool(total))
        self.page_count_label.setText(f"/ {pages:,}페이지")
        self.first_button.setEnabled(self.current_page > 0)
        self.previous_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(self.current_page + 1 < pages)
        self.last_button.setEnabled(self.current_page + 1 < pages)
        self.table.show_hits(self.ordered_hits[start:end], self.keywords)


class ResultTable(QTableWidget):
    current_hit_changed = Signal(object)
    checked_count_changed = Signal(int)
    hits_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.hits = []
        self.tags_by_path = {}
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
        self.setColumnWidth(COL_TAGS, 180)
        self.setItemDelegateForColumn(COL_TAGS, TagBadgeDelegate(self))
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
        self.clearSelection()
        self.setCurrentCell(-1, -1)
        self.tags_by_path = {}
        self.hits = hits
        self.setRowCount(len(hits))
        for row, hit in enumerate(hits):
            self.fill_row(row, hit, keywords)
        self.blockSignals(False)
        self.scrollToTop()
        self.current_hit_changed.emit(None)
        self.checked_count_changed.emit(0)
        self.hits_changed.emit()

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

    def show_tags(self, tags_by_path, colors=None):
        """선택·정렬 상태를 바꾸지 않고 태그 열만 갱신해요."""
        self.tags_by_path = tags_by_path
        previous = self.blockSignals(True)
        try:
            for row, hit in enumerate(self.hits):
                names = tags_by_path.get(hit.path, ())
                item = self.item(row, COL_TAGS)
                item.setText(", ".join(names))
                item.setData(BADGES_ROLE, [(name, (colors or {}).get(name, DEFAULT_TAG_COLOR)) for name in names])
                item.setToolTip("\n".join(names))
        finally:
            self.blockSignals(previous)

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
