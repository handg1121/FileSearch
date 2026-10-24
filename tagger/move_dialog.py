"""검색 결과와 별도로 경로 변경 후보를 확인하는 창이에요."""

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QMessageBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from common.file_actions import open_file
from common.widgets import make_button, make_label
from searcher.metadata import path_key
from tagger.path_tracking import MoveChoice


class PathMoveDialog(QDialog):
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("파일 경로 변경 확인")
        self.resize(1120, 520)
        self.action = None
        self.rows = [MoveChoice(candidate, path) for candidate in candidates for path in candidate.new_paths]
        layout = QVBoxLayout(self)
        note = make_label("파일이 저장된 경로에서 이동되었습니다.\n같은 이름의 파일이 다른 경로에서 발견되었습니다. 태그 정보를 옮기시겠습니까?")
        note.setWordWrap(True)
        layout.addWidget(note)
        hint = make_label("파일명이 같은 후보예요. 행을 더블클릭해 새 경로의 파일을 열어 본 뒤 처리할 행을 체크하세요.", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        select_row = QHBoxLayout()
        self.select_all_button = make_button("전체 선택", "secondaryButton")
        self.select_all_button.clicked.connect(lambda: self.set_all(Qt.Checked))
        select_row.addWidget(self.select_all_button)
        clear = make_button("선택 해제", "secondaryButton")
        clear.clicked.connect(lambda: self.set_all(Qt.Unchecked))
        select_row.addWidget(clear)
        select_row.addStretch()
        layout.addLayout(select_row)
        self.table = QTableWidget(len(self.rows), 3)
        self.table.setHorizontalHeaderLabels(["선택", "DB에 저장된 이전 경로", "새로 발견된 경로"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 52)
        for row, choice in enumerate(self.rows):
            self.table.setRowHeight(row, 46)
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, item)
            old = QTableWidgetItem(choice.candidate.old_path)
            old.setToolTip(choice.candidate.old_path + "\n태그: " + ", ".join(choice.candidate.tag_names))
            self.table.setItem(row, 1, old)
            new = QTableWidgetItem(choice.new_path)
            new.setToolTip(choice.new_path + "\n더블클릭으로 파일 열기")
            self.table.setItem(row, 2, new)
        self.table.cellDoubleClicked.connect(self.open_candidate)
        layout.addWidget(self.table, 1)
        warning = make_label("이전 기록 삭제: 선택한 기존 경로의 태그 연결과 메타데이터만 삭제해요. 실제 파일과 태그 이름은 유지해요.", "muted")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        buttons = QHBoxLayout()
        self.discard_button = make_button("선택한 이전 기록 삭제", "secondaryButton")
        self.discard_button.clicked.connect(lambda: self.finish("discard"))
        buttons.addWidget(self.discard_button)
        buttons.addStretch()
        later = make_button("나중에 확인", "secondaryButton")
        later.clicked.connect(self.reject)
        buttons.addWidget(later)
        self.transfer_button = make_button("선택한 태그 옮기기", "primaryButton")
        self.transfer_button.clicked.connect(lambda: self.finish("transfer"))
        buttons.addWidget(self.transfer_button)
        layout.addLayout(buttons)
        self.table.itemChanged.connect(self.update_buttons)
        self.update_buttons()

    def selected_choices(self):
        return [choice for row, choice in enumerate(self.rows)
                if self.table.item(row, 0).checkState() == Qt.Checked]

    def set_all(self, state):
        for row in range(len(self.rows)):
            self.table.item(row, 0).setCheckState(state)

    def update_buttons(self):
        selected = bool(self.selected_choices())
        self.transfer_button.setEnabled(selected)
        self.discard_button.setEnabled(selected)

    def finish(self, action):
        choices = self.selected_choices()
        if not choices:
            return
        if action == "transfer":
            old_counts = Counter(path_key(choice.candidate.old_path) for choice in choices)
            new_counts = Counter(path_key(choice.new_path) for choice in choices)
            if max(old_counts.values()) > 1 or max(new_counts.values()) > 1:
                QMessageBox.warning(self, "대상 선택", "기존 파일 하나당 새 경로 하나만 선택해 주세요. 같은 새 경로를 여러 번 선택할 수 없어요.")
                return
        self.action = action
        self.accept()

    def open_candidate(self, row, column):
        if column != 0:
            error = open_file(self.rows[row].new_path)
            if error:
                QMessageBox.warning(self, "파일 열기", error)
