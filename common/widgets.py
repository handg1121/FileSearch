'여러 화면에서 같이 쓰는 스타일과 위젯 생성 함수'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from common.file_icons import FILE_TYPES, FileTypeIcon


TAG_COLORS = {
    "계약서": ("#fde2e1", "#c62828", "#ef4444"),
    "검토중": ("#fff1c2", "#8a6100", "#f5b800"),
    "거래처": ("#dbeafe", "#1d4ed8", "#3b82f6"),
    "완료": ("#d9f5e3", "#15803d", "#22c55e"),
    "중요": ("#ede4ff", "#6d28d9", "#a855f7"),
}

STYLE = """
QWidget { color: #1f2937; }
#central { background: #f5f7fa; }
#sidebar { background: #ffffff; border-right: 1px solid #e5e8ec; }
#navButton {
    text-align: left; border: none; border-radius: 8px; background: transparent;
    min-height: 40px;
}
#navButton:checked { background: #e8f0fe; }
#navButton:hover:!checked { background: #f1f3f5; }
#card { background: #ffffff; border: 1px solid #e5e8ec; border-radius: 10px; }
#pageTitle { font-size: 20pt; font-weight: bold; }
#dialogTitle { font-size: 18pt; font-weight: bold; }
#sectionTitle { font-size: 13pt; font-weight: bold; }
#muted { color: #6b7280; }
#selectedCount { color: #1a56db; font-weight: bold; font-size: 11pt; }
#primaryButton {
    background: #1a6ff0; color: white; border: none; border-radius: 6px;
    padding: 8px 22px; font-weight: bold;
}
#primaryButton:hover { background: #155fd0; }
#primaryButton:disabled { background: #a9c6f7; }
#secondaryButton {
    background: white; border: 1px solid #cfd6de; border-radius: 6px; padding: 7px 16px;
}
#secondaryButton:hover { background: #f5f7fa; }
#secondaryButton:disabled { color: #b0b7c0; border-color: #e5e8ec; }
#linkButton { border: none; background: transparent; color: #1a6ff0; }
#flatButton { border: none; background: transparent; text-align: left; padding: 6px 4px; color: #4b5563; }
#flatButton:hover { color: #1a6ff0; }
QLineEdit {
    border: 1px solid #cfd6de; border-radius: 6px; padding: 7px 10px; background: white;
}
QLineEdit:focus { border-color: #1a6ff0; }
QLineEdit:disabled { background: #f5f7fa; color: #9ca3af; }
QComboBox {
    border: 1px solid #cfd6de; border-radius: 6px; padding: 5px 10px; background: white;
    min-width: 120px;
}
#sortCombo { border: none; min-width: 110px; background: transparent; }
QTableWidget {
    border: 1px solid #e5e8ec; border-radius: 8px; background: white;
    gridline-color: transparent; selection-background-color: #e8f0fe; selection-color: #1f2937;
}
QTableWidget::item { border-bottom: 1px solid #eef0f3; }
QHeaderView::section {
    background: #f8f9fb; border: none; border-bottom: 1px solid #e5e8ec;
    padding: 8px; color: #4b5563;
}
#tagBar { background: #eaf2fe; border-radius: 10px; }
QTextBrowser { border: 1px solid #e5e8ec; border-radius: 6px; background: white; padding: 6px; }
#dupNote { background: #f8f9fb; border-radius: 8px; }
QStatusBar { background: white; border-top: 1px solid #e5e8ec; }
QSplitter::handle { background: transparent; }
#collectDialog { background: white; }
#typeTile { background: white; border: 2px solid transparent; border-radius: 10px; }
#typeTile:hover { background: #f5f7fa; }
#typeTile:checked { background: #eef5ff; border: 2px solid #1a6ff0; }
"""


def make_label(text, name=None):
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    return label


def make_button(text, name):
    button = QPushButton(text)
    button.setObjectName(name)
    button.setCursor(Qt.PointingHandCursor)
    return button


def make_chip(tag, removable=False):
    bg, fg, _ = TAG_COLORS[tag]
    text = f"{tag}  ×" if removable else tag
    chip = QLabel(text)
    chip.setStyleSheet(
        f"background: {bg}; color: {fg}; border-radius: 6px; padding: 3px 9px;"
    )
    return chip


def make_badge(text):
    badge = QLabel(text)
    badge.setStyleSheet(
        "background: #f1f5fb; color: #4b6b9a; border: 1px solid #d6e2f3; "
        "border-radius: 4px; padding: 0px 6px; font-size: 8pt;"
    )
    return badge


def make_type_icon(file_name, size=34):
    'Windows 연결 아이콘을 표시하고, 없으면 내장 문서 아이콘을 사용해요.'
    return FileTypeIcon(file_name, size)


def set_type_icon(icon, file_name):
    '파일이 바뀌면 같은 위젯의 아이콘을 갱신해요.'
    icon.set_file_name(file_name)


def make_dot(color, size=10):
    dot = QLabel()
    dot.setFixedSize(size, size)
    dot.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")
    return dot


def make_separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background: #e5e8ec;")
    return line


def transparent_widget():
    widget = QWidget()
    widget.setStyleSheet("background: transparent;")
    return widget


def format_size(size):
    '바이트 수를 1.2 MB 같은 읽기 쉬운 글자로'
    if size < 1024:
        return f"{size} B"
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size / 1024:.1f} TB"
