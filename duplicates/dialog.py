"""내용이 같은 파일을 묶음별로 보여 주고, 묶음마다 남길 파일 하나를 고르는 창이에요.

파일이 수천 개여도 창이 빨리 뜨도록 줄마다 위젯을 만들지 않아요. 선택 상태는 표 항목에
저장하고, 동그라미는 RadioDelegate가 직접 그려요.
"""

import os
import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QMessageBox, QStyle, QStyledItemDelegate,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from common.file_actions import open_file
from common.widgets import format_size, make_button, make_label
from duplicates.remover import KeepChoice, pick_original

COL_KEEP, COL_NAME, COL_FOLDER, COL_MODIFIED = range(4)
# 파일 줄에 저장하는 값: 묶음 번호와 묶음 안 파일 번호
GROUP_ROLE = Qt.UserRole + 1
FILE_ROLE = Qt.UserRole + 2


class RadioDelegate(QStyledItemDelegate):
    '남길 파일 칸에 선택 동그라미를 그려요. 클릭 처리는 창에서 해요.'

    def paint(self, painter, option, index):
        if index.data(FILE_ROLE) is None:
            super().paint(painter, option, index)
            return
        widget = option.widget
        widget.style().drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter, widget)
        center = QPointF(option.rect.center())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if index.data(Qt.CheckStateRole) == Qt.Checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#1a6ff0"))
            painter.drawEllipse(center, 7, 7)
            painter.setBrush(QColor("white"))
            painter.drawEllipse(center, 3, 3)
        else:
            painter.setPen(QPen(QColor("#9ca3af"), 1))
            painter.setBrush(QColor("white"))
            painter.drawEllipse(center, 6.5, 6.5)
        painter.restore()


class DuplicateDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setObjectName("collectDialog")
        self.setWindowTitle("중복 파일")
        self.resize(1120, 640)
        self.result = result
        self.titles = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(make_label("중복 파일", "dialogTitle"))
        layout.addWidget(make_label(
            f"내용이 같은 묶음 {len(result.groups):,}개 · 정리하면 최대 {format_size(result.wasted)} 확보", "sectionTitle"))
        hint = make_label("묶음마다 남길 파일을 하나 고르세요. 고른 묶음만 정리하고, 나머지 파일은 휴지통으로 보내요. "
                          "지우는 파일의 태그는 남길 파일로 옮겨요. 고른 파일을 다시 누르면 선택이 풀려요. "
                          "파일을 더블클릭하면 열어 볼 수 있어요.", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        if result.errors:
            errors = make_label(f"확인하지 못한 파일 {len(result.errors):,}개는 비교에서 빠졌어요. (마우스를 올려 상세 확인)", "muted")
            errors.setToolTip("\n\n".join(f"{path}\n{message}" for path, message in result.errors[:50]))
            layout.addWidget(errors)
        pick_row = QHBoxLayout()
        self.pick_button = make_button("원본 한 번에 고르기", "secondaryButton")
        self.pick_button.setToolTip("이름 끝에 _중복1, _중복2 같은 꼬리표가 없는 파일이 하나뿐인 묶음은 그 파일을 남길 파일로 골라요.\n"
                                    "이미 직접 고른 묶음은 그대로 둬요.")
        self.pick_button.clicked.connect(self.pick_originals)
        pick_row.addWidget(self.pick_button)
        self.pick_label = make_label("", "muted")
        pick_row.addWidget(self.pick_label)
        pick_row.addStretch()
        layout.addLayout(pick_row)
        layout.addWidget(self.build_tree(), 1)
        self.summary_label = make_label("", "selectedCount")
        layout.addWidget(self.summary_label)
        buttons = QHBoxLayout()
        clear = make_button("선택 해제", "secondaryButton")
        clear.clicked.connect(self.clear_all)
        buttons.addWidget(clear)
        buttons.addStretch()
        close = make_button("닫기", "secondaryButton")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.remove_button = make_button("선택한 묶음 정리", "primaryButton")
        self.remove_button.clicked.connect(self.confirm)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)
        self.update_summary()

    def build_tree(self):
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["남길 파일", "파일명", "폴더", "수정일"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setItemDelegateForColumn(COL_KEEP, RadioDelegate(self.tree))
        header = self.tree.header()
        header.setSectionResizeMode(COL_KEEP, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_MODIFIED, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(COL_KEEP, 80)
        titles = []
        for group_index, group in enumerate(self.result.groups):
            title = QTreeWidgetItem([f"묶음 {group_index + 1} · {len(group.files)}개 · 각 {format_size(group.size)}"])
            title.setFlags(Qt.ItemIsEnabled)
            font = title.font(0)
            font.setBold(True)
            title.setFont(0, font)
            for file_index, item in enumerate(group.files):
                folder = os.path.relpath(os.path.dirname(item.path), self.result.root)
                modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.mtime_ns / 1_000_000_000))
                row = QTreeWidgetItem(["", item.name, "(맨 위 폴더)" if folder == "." else folder, modified])
                row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                row.setData(COL_KEEP, GROUP_ROLE, group_index)
                row.setData(COL_KEEP, FILE_ROLE, file_index)
                row.setData(COL_KEEP, Qt.CheckStateRole, Qt.Unchecked)
                row.setData(COL_NAME, Qt.UserRole, item.path)
                row.setToolTip(COL_NAME, item.path + "\n더블클릭으로 파일 열기")
                row.setToolTip(COL_FOLDER, os.path.dirname(item.path))
                title.addChild(row)
            titles.append(title)
        # 항목을 다 만든 뒤 한 번에 넣어야 줄이 많아도 빨라요.
        self.tree.addTopLevelItems(titles)
        for title in titles:
            title.setFirstColumnSpanned(True)
            title.setExpanded(True)
        self.titles = titles
        self.tree.itemClicked.connect(self.on_clicked)
        self.tree.itemDoubleClicked.connect(self.open_item)
        return self.tree

    def checked_index(self, group_index):
        title = self.titles[group_index]
        for file_index in range(title.childCount()):
            if title.child(file_index).data(COL_KEEP, Qt.CheckStateRole) == Qt.Checked:
                return file_index
        return -1

    def set_choice(self, group_index, file_index):
        'file_index 파일만 고른 상태로 만들어요. -1이면 그 묶음의 선택을 풀어요.'
        title = self.titles[group_index]
        for index in range(title.childCount()):
            state = Qt.Checked if index == file_index else Qt.Unchecked
            title.child(index).setData(COL_KEEP, Qt.CheckStateRole, state)

    def on_clicked(self, row, column):
        if column != COL_KEEP or row.data(COL_KEEP, FILE_ROLE) is None:
            return
        group_index = row.data(COL_KEEP, GROUP_ROLE)
        file_index = row.data(COL_KEEP, FILE_ROLE)
        # 이미 고른 파일을 다시 누르면 그 묶음은 정리하지 않도록 선택을 풀어요.
        if self.checked_index(group_index) == file_index:
            self.set_choice(group_index, -1)
        else:
            self.set_choice(group_index, file_index)
        self.update_summary()

    def pick_originals(self):
        picked, undecided = 0, 0
        for group_index, group in enumerate(self.result.groups):
            if self.checked_index(group_index) >= 0:
                continue
            original = pick_original(group)
            if original is None:
                undecided += 1
                continue
            self.set_choice(group_index, group.files.index(original))
            picked += 1
        if undecided:
            self.pick_label.setText(f"원본으로 고른 묶음 {picked:,}개 · 원본을 정할 수 없어 직접 골라야 할 묶음 {undecided:,}개")
        else:
            self.pick_label.setText(f"원본으로 고른 묶음 {picked:,}개")
        self.update_summary()

    def clear_all(self):
        for group_index in range(len(self.titles)):
            self.set_choice(group_index, -1)
        self.pick_label.setText("")
        self.update_summary()

    def selected_choices(self):
        choices = []
        for group_index, group in enumerate(self.result.groups):
            file_index = self.checked_index(group_index)
            if file_index >= 0:
                choices.append(KeepChoice(group, group.files[file_index]))
        return choices

    def update_summary(self):
        choices = self.selected_choices()
        count, size = 0, 0
        for choice in choices:
            count += len(choice.removes)
            size += choice.group.wasted
        if choices:
            self.summary_label.setText(f"남길 파일을 고른 묶음 {len(choices):,}개 · "
                                       f"휴지통으로 보낼 파일 {count:,}개 ({format_size(size)})")
        else:
            self.summary_label.setText("남길 파일을 고른 묶음이 없어요.")
        self.remove_button.setEnabled(bool(choices))

    def confirm(self):
        choices = self.selected_choices()
        if not choices:
            return
        count = 0
        for choice in choices:
            count += len(choice.removes)
        answer = QMessageBox.question(
            self, "중복 파일 정리",
            f"묶음 {len(choices):,}개에서 파일 {count:,}개를 휴지통으로 보내요.\n"
            "남길 파일은 그대로 두고, 지우는 파일의 태그는 남길 파일로 옮겨요.\n\n계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.accept()

    def open_item(self, item, column):
        path = item.data(COL_NAME, Qt.UserRole)
        if path:
            error = open_file(path)
            if error:
                QMessageBox.warning(self, "파일 열기", error)
