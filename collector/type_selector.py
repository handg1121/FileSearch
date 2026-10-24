'파일 모으기 창의 파일 유형 선택 영역'
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from common.widgets import FILE_TYPES, make_button, make_label, make_type_icon

DEFAULT_TYPES = {"hwp", "hwpx", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf", "txt"}
COLUMNS = 6


class TypeTile(QPushButton):
    '눌러서 켜고 끄는 파일 유형 타일'
    def __init__(self, ext):
        super().__init__()
        self.ext = ext
        self.setObjectName("typeTile")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(124, 112)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 10)
        layout.setSpacing(8)
        icon = make_type_icon(ext, size=40)
        icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(icon, 0, Qt.AlignHCenter)
        name = QLabel(f".{ext}")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("background: transparent; font-size: 11pt;")
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(name)
        self.check_mark = QLabel("✓", self)
        self.check_mark.setAlignment(Qt.AlignCenter)
        self.check_mark.setFixedSize(22, 22)
        self.check_mark.move(self.width() - 30, 8)
        self.check_mark.setStyleSheet(
            "background: #1a6ff0; color: white; border-radius: 11px; "
            "font-family: 'Segoe UI Symbol'; font-weight: bold; font-size: 9pt;"
        )
        self.check_mark.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.check_mark.hide()
        self.toggled.connect(self.check_mark.setVisible)


class TypeSelector(QWidget):
    '유형 타일 묶음. 선택이 바뀔 때마다 선택 개수를 알린다'
    selection_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(make_label("파일 유형", "sectionTitle"))
        self.count_label = make_label("", "muted")
        header.addWidget(self.count_label)
        header.addStretch()
        select_all_button = make_button("전체 선택", "linkButton")
        select_all_button.clicked.connect(lambda: self.set_all(True))
        header.addWidget(select_all_button)
        header.addWidget(make_label("|", "muted"))
        clear_all_button = make_button("선택 해제", "linkButton")
        clear_all_button.clicked.connect(lambda: self.set_all(False))
        header.addWidget(clear_all_button)
        layout.addLayout(header)
        layout.addWidget(make_label("아이콘을 눌러 여러 유형을 선택할 수 있어요.", "muted"))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles = []
        for index, ext in enumerate(FILE_TYPES):
            tile = TypeTile(ext)
            tile.setChecked(ext in DEFAULT_TYPES)
            tile.toggled.connect(self.update_count)
            grid.addWidget(tile, index // COLUMNS, index % COLUMNS)
            self.tiles.append(tile)
        layout.addLayout(grid)
        self.update_count()

    def set_all(self, checked):
        for tile in self.tiles:
            tile.setChecked(checked)

    def selected_types(self):
        selected = []
        for tile in self.tiles:
            if tile.isChecked():
                selected.append(tile.ext)
        return selected

    def update_count(self):
        count = len(self.selected_types())
        self.count_label.setText(f"{count}개 선택")
        self.selection_changed.emit(count)
