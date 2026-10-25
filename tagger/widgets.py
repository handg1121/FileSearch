"""태그 입력 영역과 목록 위젯. DB 접근은 저장소와 컨트롤러에서 담당해요."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget,
)

from common.widgets import make_button, make_label
from tagger.badges import BADGES_ROLE, COUNT_ROLE, TagBadgeDelegate


class TagCheckList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setItemDelegate(TagBadgeDelegate(self))
        self.setMinimumHeight(80)
        self.setStyleSheet("QListWidget { background: white; border: 1px solid #dce3ec; border-radius: 6px; } QListWidget::item { padding: 5px; }")

    def set_tags(self, tags, *, checked_ids=(), counts=False):
        self.blockSignals(True)
        self.clear()
        for tag in tags:
            text = f"{tag.name}  ({tag.file_count}개 파일)" if counts else tag.name
            item = QListWidgetItem(text)
            item.setToolTip(text)
            item.setData(Qt.UserRole, tag.id)
            item.setData(BADGES_ROLE, [(tag.name, tag.color)])
            item.setData(COUNT_ROLE, f"{tag.file_count}개 파일" if counts else None)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if tag.id in checked_ids else Qt.Unchecked)
            self.addItem(item)
        self.blockSignals(False)

    def checked_ids(self):
        return [self.item(row).data(Qt.UserRole) for row in range(self.count())
                if self.item(row).checkState() == Qt.Checked]

    def clear_checks(self):
        for row in range(self.count()):
            self.item(row).setCheckState(Qt.Unchecked)


class TagBar(QFrame):
    attach_requested = Signal()
    detach_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tagBar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        self.selected_count_label = make_label("0개 선택", "selectedCount")
        row.addWidget(self.selected_count_label)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("부착할 태그 입력 (여러 개는 쉼표로 구분)")
        self.tag_input.setMinimumWidth(170)
        row.addWidget(self.tag_input, 1)
        self.attach_button = make_button("태그 부착", "primaryButton")
        self.detach_button = make_button("태그 제거", "secondaryButton")
        self.attach_button.clicked.connect(self.attach_requested.emit)
        self.detach_button.clicked.connect(self.detach_requested.emit)
        self.tag_input.returnPressed.connect(self.attach_requested.emit)
        row.addWidget(self.attach_button)
        row.addWidget(self.detach_button)
        layout.addLayout(row)
        self.error_label = make_label("")
        self.error_label.setStyleSheet("color: #b42318;")
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.set_selected_count(0)

    def set_selected_count(self, count):
        self.selected_count_label.setText(f"{count}개 선택")
        self.attach_button.setEnabled(count > 0)
        self.detach_button.setEnabled(count > 0)

    def show_error(self, error):
        self.error_label.setText("태그를 읽지 못했어요. 태그 관리에서 다시 확인해 주세요." if error else "")
        self.error_label.setToolTip(str(error))
        self.error_label.setVisible(bool(error))


class TagSidebar(QWidget):
    manage_requested = Signal()
    tag_activated = Signal(int)
    color_requested = Signal(int)
    edit_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(make_label("내 태그"))
        row.addStretch()
        self.add_button = make_button("+", "secondaryButton")
        self.add_button.setFixedSize(30, 30)
        self.add_button.setStyleSheet("padding: 0px;")
        self.add_button.setToolTip("새 태그 만들기 / 태그 관리")
        self.add_button.clicked.connect(self.manage_requested.emit)
        row.addWidget(self.add_button)
        layout.addLayout(row)
        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(QListWidget.SingleSelection)
        self.tag_list.setItemDelegate(TagBadgeDelegate(self.tag_list))
        self.tag_list.itemDoubleClicked.connect(self.activate_tag)
        self.tag_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_list.customContextMenuRequested.connect(self.show_tag_menu)
        self.tag_list.setStyleSheet("QListWidget { border: none; background: transparent; } QListWidget::item { padding: 8px 2px; } QListWidget::item:selected { background: #e8f0fe; border-radius: 5px; }")
        self.tag_list.setToolTip("더블클릭: 태그 문서 보기 · 우클릭: 태그 수정·색 변경\n숫자는 모든 폴더에 등록된 파일 수예요.")
        layout.addWidget(self.tag_list, 1)
        self.manage_button = make_button("태그 관리", "flatButton")
        self.manage_button.clicked.connect(self.manage_requested.emit)
        layout.addWidget(self.manage_button)

    def show_tags(self, tags, active_id=None):
        self.tag_list.clear()
        if not tags:
            item = QListWidgetItem("등록된 태그가 없어요.")
            item.setFlags(Qt.NoItemFlags)
            self.tag_list.addItem(item)
        for tag in tags:
            item = QListWidgetItem(f"{tag.name}  ·  {tag.file_count}")
            item.setData(Qt.UserRole, tag.id)
            item.setData(BADGES_ROLE, [(tag.name, tag.color)])
            item.setData(COUNT_ROLE, tag.file_count)
            item.setToolTip(f"{tag.name} — 등록된 파일 {tag.file_count}개 (모든 폴더)\n더블클릭: 문서 보기 · 우클릭: 태그 수정·색 변경")
            self.tag_list.addItem(item)

        self.set_active_tag(active_id)

    def set_active_tag(self, tag_id):
        self.tag_list.clearSelection()
        for row in range(self.tag_list.count()):
            item = self.tag_list.item(row)
            if tag_id is not None and item.data(Qt.UserRole) == tag_id:
                self.tag_list.setCurrentItem(item)
                item.setSelected(True)
                break

    def activate_tag(self, item):
        tag_id = item.data(Qt.UserRole)
        if tag_id is not None:
            self.tag_activated.emit(tag_id)

    def show_tag_menu(self, pos):
        item = self.tag_list.itemAt(pos)
        if item is None or item.data(Qt.UserRole) is None:
            return
        tag_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        edit_action = menu.addAction("태그 수정")
        edit_action.triggered.connect(lambda: self.edit_requested.emit(tag_id))
        action = menu.addAction("색 변경")
        action.triggered.connect(lambda: self.color_requested.emit(tag_id))
        try:
            menu.exec(self.tag_list.viewport().mapToGlobal(pos))
        finally:
            menu.deleteLater()
