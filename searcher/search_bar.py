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
        self.content_check = QCheckBox("파일 내용")
        self.content_check.setToolTip("이미지 글자 인식: PNG·JPG·JPEG·BMP·TIFF·WebP (한국어·영어)\n변경되지 않은 파일은 저장된 본문을 재사용해요.")
        option_row.addWidget(self.content_check)
        self.tag_check = QCheckBox("태그명")
        option_row.addWidget(self.tag_check)
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
        self.content_hint = make_label("", "muted")
        self.content_hint.setWordWrap(True)
        layout.addWidget(self.content_hint)
        self.name_check.toggled.connect(self.update_keyword_hint)
        self.content_check.toggled.connect(self.update_keyword_hint)
        self.tag_check.toggled.connect(self.update_keyword_hint)
        self.update_keyword_hint()

    def keyword_text(self):
        return self.keyword_input.text()

    def name_search_enabled(self):
        return self.name_check.isChecked()

    def content_search_enabled(self):
        return self.content_check.isChecked()

    def tag_search_enabled(self):
        return self.tag_check.isChecked()

    def update_keyword_hint(self):
        targets = [label for label, enabled in (
            ("파일명", self.name_search_enabled()),
            ("본문", self.content_search_enabled()),
            ("태그명", self.tag_search_enabled()),
        ) if enabled]
        if len(targets) > 1:
            placeholder = "·".join(targets) + " 중에서 찾을 검색어 입력"
        elif self.content_search_enabled():
            placeholder = "본문에서 찾을 문구 입력 (띄어쓰기 포함)"
        elif self.tag_search_enabled():
            placeholder = "태그명으로 검색 (일부 입력 가능, 비우면 태그가 붙은 파일)"
        elif self.name_search_enabled():
            placeholder = "파일명으로 검색 (띄어쓰기로 여러 단어, 비워 두면 전체)"
        else:
            placeholder = "검색할 항목을 선택하세요"
        self.keyword_input.setPlaceholderText(placeholder)
        hints = []
        if self.content_search_enabled():
            hints.append("본문은 띄어쓰기를 포함해 입력한 문구를 찾아요. 지원: HWP·HWPX·TXT·이미지 OCR. 처음 읽는 이미지는 시간이 걸릴 수 있어요.")
        if self.tag_search_enabled():
            hints.append("태그명은 입력한 문구가 포함된 태그를 찾아요. 예: 계약 → 계약서.")
        if len(targets) > 1:
            hints.append("선택한 항목 중 하나라도 일치하면 표시해요.")
        self.content_hint.setText(" ".join(hints))
        self.content_hint.setVisible(bool(hints))

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
