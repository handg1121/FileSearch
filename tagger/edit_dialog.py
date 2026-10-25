"""태그가 붙은 파일을 골라 이름을 수정하는 창이에요."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout

from common.file_actions import open_file
from common.widgets import make_button, make_label
from tagger import storage
from tagger.dialogs import STORAGE_ERRORS


class EditTagDialog(QDialog):
    def __init__(self, tag, paths, db_path, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.paths = list(paths)
        self.db_path = db_path
        self.edit_result = None
        self.existing = {item.name.casefold(): item for item in storage.show_tag(db_path)}
        self.setWindowTitle('태그 수정')
        self.resize(940, 580)
        layout = QVBoxLayout(self)
        title = make_label(f'수정할 태그: {tag.name}', 'sectionTitle')
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        note = make_label('아래에서 변경할 파일을 체크하고 새 태그 이름을 입력하세요.\n목록은 모든 폴더에 등록된 경로예요. 선택하지 않은 파일과 다른 태그는 그대로 유지돼요.')
        note.setWordWrap(True)
        layout.addWidget(note)
        name_row = QHBoxLayout()
        name_row.addWidget(make_label('새 태그 이름'))
        self.name_input = QLineEdit(tag.name)
        self.name_input.setMaxLength(64)
        self.name_input.setPlaceholderText('변경할 태그 이름을 입력하세요')
        name_row.addWidget(self.name_input, 1)
        layout.addLayout(name_row)
        selection_row = QHBoxLayout()
        self.select_all_button = make_button('전체 선택', 'secondaryButton')
        self.select_all_button.clicked.connect(lambda: self.set_all(Qt.Checked))
        selection_row.addWidget(self.select_all_button)
        self.clear_button = make_button('선택 해제', 'secondaryButton')
        self.clear_button.clicked.connect(lambda: self.set_all(Qt.Unchecked))
        selection_row.addWidget(self.clear_button)
        selection_row.addStretch()
        self.count_label = make_label('', 'muted')
        selection_row.addWidget(self.count_label)
        layout.addLayout(selection_row)
        self.table = QTableWidget(len(paths), 3)
        self.table.setHorizontalHeaderLabels(['선택', '파일명', '등록된 경로'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(1, 210)
        for row, path in enumerate(self.paths):
            self.table.setRowHeight(row, 38)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(os.path.basename(path)))
            item = QTableWidgetItem(path)
            item.setToolTip(path)
            self.table.setItem(row, 2, item)
        self.table.cellDoubleClicked.connect(self.open_document)
        layout.addWidget(self.table, 1)
        self.hint = make_label('', 'muted')
        self.hint.setTextFormat(Qt.PlainText)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.error_label = make_label('')
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setStyleSheet('color: #b42318;')
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = make_button('취소', 'secondaryButton')
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.save_button = make_button('선택한 파일의 태그 변경' if paths else '태그 이름 변경', 'primaryButton')
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        for button in (self.select_all_button, self.clear_button, self.cancel_button, self.save_button):
            button.setAutoDefault(False)
        self.name_input.returnPressed.connect(self.save)
        self.name_input.textChanged.connect(self.update_state)
        self.table.itemChanged.connect(self.update_state)
        self.select_all_button.setEnabled(bool(paths))
        self.clear_button.setEnabled(bool(paths))
        self.update_state()
        self.name_input.setFocus()
        self.name_input.selectAll()

    def selected_paths(self):
        return [path for row, path in enumerate(self.paths) if self.table.item(row, 0).checkState() == Qt.Checked]

    def set_all(self, state):
        previous = self.table.blockSignals(True)
        try:
            for row in range(len(self.paths)):
                self.table.item(row, 0).setCheckState(state)
        finally:
            self.table.blockSignals(previous)
        self.update_state()

    def update_state(self):
        count = len(self.selected_paths())
        self.count_label.setText(f'{count:,} / {len(self.paths):,}개 선택')
        self.error_label.hide()
        try:
            name = storage.normalize_name(self.name_input.text())
            valid = name != self.tag.name
        except ValueError:
            name, valid = '', False
        all_selected = count == len(self.paths)
        same_key = name.casefold() == self.tag.name.casefold()
        target = self.existing.get(name.casefold())
        if not valid:
            text = '새 태그 이름을 입력하세요. 이름은 64자까지이며 쉼표와 줄바꿈은 사용할 수 없어요.'
        elif same_key and not all_selected:
            text = '대소문자만 바꾸려면 전체 파일을 선택해 주세요.'
            valid = False
        elif target is not None and target.id != self.tag.id:
            text = f'이미 있는 “{target.name}” 태그로 변경해요. 그 태그의 색을 사용하고 중복으로 붙이지 않아요.'
        elif not self.paths:
            text = '이 태그가 붙은 파일이 없어요. 태그 이름만 변경하고 색은 유지해요.'
        elif all_selected:
            text = '모든 파일의 태그 이름을 변경해요. 태그 색은 그대로 유지돼요.'
        else:
            text = f'선택한 파일만 새 이름으로 바꿔요. 나머지는 “{self.tag.name}” 태그로 남아요.'
        self.hint.setText(text)
        self.save_button.setEnabled(valid and (count > 0 or not self.paths))

    def save(self):
        if not self.save_button.isEnabled():
            return
        try:
            self.edit_result = storage.edit_tag(self.tag.id, self.name_input.text(), self.selected_paths(),
                                                self.db_path, expected_name=self.tag.name)
        except STORAGE_ERRORS as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.accept()

    def open_document(self, row, column):
        if column != 0:
            error = open_file(self.paths[row])
            if error:
                QMessageBox.warning(self, '파일 열기', error)
