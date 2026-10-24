'검색창 영역: 검색어, 검색 대상 체크박스, 파일 종류·수정일 필터'
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLineEdit, QVBoxLayout

from common.widgets import make_button, make_label
from searcher.filename_search import DATE_RANGES, TYPE_GROUPS


class SearchBar(QFrame):
    search_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        search_row = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("파일명으로 검색 (띄어쓰기로 여러 단어, 비워 두면 전체)")
        self.keyword_input.setClearButtonEnabled(True)
        self.keyword_input.setMinimumHeight(40)
        self.keyword_input.returnPressed.connect(self.search_requested)
        search_row.addWidget(self.keyword_input, 1)
        search_button = make_button("검색", "primaryButton")
        search_button.setMinimumHeight(40)
        search_button.clicked.connect(self.search_requested)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)
        option_row = QHBoxLayout()
        option_row.setSpacing(20)
        self.name_check = QCheckBox("파일명")
        self.name_check.setChecked(True)
        option_row.addWidget(self.name_check)
        for text in ("파일 내용", "태그"):
            check = QCheckBox(f"{text} (준비 중)")
            check.setEnabled(False)
            option_row.addWidget(check)
        option_row.addStretch()
        option_row.addWidget(make_label("파일 종류", "muted"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(list(TYPE_GROUPS))
        self.type_combo.currentTextChanged.connect(self.search_requested)
        option_row.addWidget(self.type_combo)
        option_row.addWidget(make_label("수정일", "muted"))
        self.date_combo = QComboBox()
        self.date_combo.addItems(DATE_RANGES)
        self.date_combo.currentTextChanged.connect(self.search_requested)
        option_row.addWidget(self.date_combo)
        reset_button = make_button("필터 초기화", "linkButton")
        reset_button.clicked.connect(self.reset_filters)
        option_row.addWidget(reset_button)
        layout.addLayout(option_row)

    def keyword_text(self):
        return self.keyword_input.text()

    def name_search_enabled(self):
        return self.name_check.isChecked()

    def extensions(self):
        return TYPE_GROUPS[self.type_combo.currentText()]

    def date_range(self):
        return self.date_combo.currentText()

    def reset_filters(self):
        for combo in (self.type_combo, self.date_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.search_requested.emit()
