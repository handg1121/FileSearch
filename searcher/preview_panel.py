'오른쪽 미리보기 영역: 선택한 파일의 정보와 열기 버튼'
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QTextBrowser, QVBoxLayout

from common.file_actions import open_file, open_folder
from common.widgets import (
    format_size, make_button, make_label, make_separator, make_type_icon, set_type_icon,
)

from tagger.badges import TagBadgeLabel

ZERO_WIDTH_SPACE = "\u200b"


class PreviewPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hit = None
        self.setObjectName("card")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(make_label("미리보기", "sectionTitle"))
        file_row = QHBoxLayout()
        file_row.setSpacing(12)
        self.icon = make_type_icon("", size=42)
        file_row.addWidget(self.icon, 0, Qt.AlignTop)
        file_info = QVBoxLayout()
        file_info.setSpacing(2)
        self.name_label = make_label("")
        self.name_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.name_label.setWordWrap(True)
        file_info.addWidget(self.name_label)
        self.path_label = make_label("", "muted")
        self.path_label.setWordWrap(True)
        file_info.addWidget(self.path_label)
        self.info_label = make_label("", "muted")
        file_info.addWidget(self.info_label)
        file_row.addLayout(file_info, 1)
        layout.addLayout(file_row)
        button_row = QHBoxLayout()
        self.open_button = make_button("파일 열기", "secondaryButton")
        self.open_button.clicked.connect(lambda: self.open_and_report(open_file))
        button_row.addWidget(self.open_button)
        self.folder_button = make_button("폴더 열기", "secondaryButton")
        self.folder_button.clicked.connect(lambda: self.open_and_report(open_folder))
        button_row.addWidget(self.folder_button)
        button_row.addStretch()
        layout.addLayout(button_row)
        layout.addSpacing(4)
        layout.addWidget(make_separator())
        layout.addSpacing(4)
        body_title = make_label("일치한 본문 일부")
        body_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(body_title)
        self.body = QTextBrowser()
        self.body.setPlaceholderText("본문 검색으로 찾은 파일을 선택하면 일치한 문구 주변을 보여 줘요.")
        self.body.setMinimumHeight(200)
        layout.addWidget(self.body, 1)
        layout.addSpacing(6)
        tags_title = make_label("부착된 태그")
        tags_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(tags_title)
        self.tags_label = TagBadgeLabel()
        self.tags_label.setTextFormat(Qt.PlainText)
        self.tags_label.setWordWrap(True)
        layout.addWidget(self.tags_label)
        self.show_hit(None)

    def show_hit(self, hit):
        self.hit = hit
        self.show_tags(())
        self.body.setPlainText(hit.body_excerpt if hit else "")
        set_type_icon(self.icon, hit.name if hit else "")
        if hit is None:
            self.name_label.setText("파일을 선택하세요")
            self.path_label.setText("")
            self.info_label.setText("")
        else:
            self.name_label.setText(hit.name)
            self.path_label.setText(os.path.dirname(hit.path).replace("\\", "\\" + ZERO_WIDTH_SPACE))
            modified = datetime.fromtimestamp(hit.modified).strftime("%Y.%m.%d %H:%M")
            self.info_label.setText(f"{format_size(hit.size)} · 수정 {modified}")
        self.open_button.setEnabled(hit is not None)
        self.folder_button.setEnabled(hit is not None)

    def show_tags(self, names, colors=None):
        self.tags_label.show_tags(names, colors,
                                 "부착된 태그가 없어요." if self.hit else "파일을 선택하세요.")

    def open_and_report(self, action):
        error = action(self.hit.path)
        if error:
            QMessageBox.warning(self, "열기", error)
