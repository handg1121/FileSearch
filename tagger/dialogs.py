"""파일에서 태그를 떼는 창과 태그 자체를 관리하는 창을 구분해요."""

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from common.widgets import make_button, make_label
from tagger import storage
from tagger.widgets import TagCheckList

STORAGE_ERRORS = (OSError, sqlite3.Error, ValueError, RuntimeError)


class RemoveTagsDialog(QDialog):
    def __init__(self, tags, file_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("선택한 파일에서 태그 제거")
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        note = make_label(f"선택한 파일 {file_count}개에서 제거할 태그를 체크하세요.\n다른 파일에 붙은 태그는 유지돼요.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.choices = TagCheckList()
        self.choices.set_tags(tags, counts=True)
        layout.addWidget(self.choices, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = make_button("취소", "secondaryButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.remove_button = make_button("선택한 태그 제거", "primaryButton")
        self.remove_button.setEnabled(False)
        self.choices.itemChanged.connect(lambda: self.remove_button.setEnabled(bool(self.choices.checked_ids())))
        self.remove_button.clicked.connect(self.accept)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)


class ManageTagsDialog(QDialog):
    changed = Signal()

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.setWindowTitle("태그 관리")
        self.resize(500, 440)
        layout = QVBoxLayout(self)
        note = make_label("태그를 만들거나 삭제해요.\n여기서 태그를 삭제하면 모든 파일에서 함께 제거돼요.")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("새 태그 이름 (하나씩 입력)")
        self.name_input.setMaxLength(64)
        self.create_button = make_button("태그 만들기", "primaryButton")
        self.create_button.clicked.connect(self.create)
        self.name_input.returnPressed.connect(self.create)
        row.addWidget(self.name_input, 1)
        row.addWidget(self.create_button)
        layout.addLayout(row)
        self.choices = TagCheckList()
        layout.addWidget(self.choices, 1)
        buttons = QHBoxLayout()
        self.delete_button = make_button("태그 자체 삭제", "secondaryButton")
        self.delete_button.setEnabled(False)
        self.choices.itemChanged.connect(lambda: self.delete_button.setEnabled(bool(self.choices.checked_ids())))
        self.delete_button.clicked.connect(self.delete)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        close = make_button("닫기", "secondaryButton")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.reload()
        self.name_input.setFocus()

    def reload(self):
        try:
            self.choices.set_tags(storage.show_tag(self.db_path), counts=True)
            self.delete_button.setEnabled(False)
        except STORAGE_ERRORS as error:
            QMessageBox.warning(self, "태그 조회", f"태그를 읽지 못했어요.\n{error}")

    def create(self):
        try:
            storage.create_tag(self.name_input.text(), self.db_path)
        except STORAGE_ERRORS as error:
            QMessageBox.warning(self, "태그 만들기", str(error))
            return
        self.name_input.clear()
        self.reload()
        self.changed.emit()

    def delete(self):
        ids = self.choices.checked_ids()
        if not ids:
            return
        answer = QMessageBox.question(
            self, "태그 자체 삭제",
            f"선택한 태그 {len(ids)}개를 삭제할까요?\n모든 파일에서 해당 태그가 제거되며 되돌릴 수 없어요.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            storage.delete_tag(ids, self.db_path)
        except STORAGE_ERRORS as error:
            QMessageBox.warning(self, "태그 삭제", str(error))
            return
        self.reload()
        self.changed.emit()


class TagColorDialog(QColorDialog):
    def __init__(self, tag, parent=None):
        super().__init__(QColor(tag.color), parent)
        self.setWindowTitle(f"태그 색 변경 · {tag.name}")
        self.setOption(QColorDialog.DontUseNativeDialog, True)
        self.setOption(QColorDialog.ShowAlphaChannel, False)
