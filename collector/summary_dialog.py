'훑기 결과를 보여 주고 옮기기·복사 중 하나를 고르게 하는 창 (경고·공간 확인 포함)'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from collector import type_selector_script as core
from common.widgets import format_size, make_button, make_label


class SummaryDialog(QDialog):
    def __init__(self, items, target_dir, parent=None):
        super().__init__(parent)
        self.items = items
        self.target_dir = target_dir
        self.mode = None
        self.setObjectName("collectDialog")
        self.setWindowTitle("찾은 파일")
        self.setMinimumWidth(560)
        total_size = 0
        for item in items:
            total_size += item.size
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)
        layout.addWidget(make_label("찾은 파일", "dialogTitle"))
        count_label = make_label(f"{len(items):,}개 · {format_size(total_size)}", "sectionTitle")
        layout.addWidget(count_label)
        layout.addWidget(self.build_type_table())
        layout.addWidget(make_label(f"저장 위치: {target_dir}", "muted"))
        notice = make_label(
            "원래 폴더 구조대로 저장하고, 같은 이름이 있으면 이름 뒤에 _중복1, _중복2를 붙여요.",
            "muted",
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addLayout(self.build_buttons())

    def build_type_table(self):
        counts = {}
        sizes = {}
        for item in self.items:
            ext = item.src.rsplit(".", 1)[-1].lower()
            counts[ext] = counts.get(ext, 0) + 1
            sizes[ext] = sizes.get(ext, 0) + item.size
        table = QTableWidget(len(counts), 3)
        table.setHorizontalHeaderLabels(["유형", "개수", "크기"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, ext in enumerate(sorted(counts, key=counts.get, reverse=True)):
            table.setItem(row, 0, QTableWidgetItem(f".{ext}"))
            table.setItem(row, 1, QTableWidgetItem(f"{counts[ext]:,}개"))
            table.setItem(row, 2, QTableWidgetItem(format_size(sizes[ext])))
        table.setFixedHeight(min(260, 40 + 34 * len(counts)))
        return table

    def build_buttons(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        cancel_button = make_button("취소", "secondaryButton")
        cancel_button.setMinimumSize(100, 40)
        cancel_button.clicked.connect(self.reject)
        row.addWidget(cancel_button)
        copy_button = make_button("복사", "secondaryButton")
        copy_button.setMinimumSize(100, 40)
        copy_button.clicked.connect(self.choose_copy)
        row.addWidget(copy_button)
        move_button = make_button("옮기기", "primaryButton")
        move_button.setMinimumSize(100, 40)
        move_button.clicked.connect(self.choose_move)
        row.addWidget(move_button)
        return row

    def choose_copy(self):
        space = core.check_space(self.items, self.target_dir, core.MODE_COPY)
        if not space.enough:
            self.warn_no_space(space)
            return
        text = (
            f"필요한 공간: {format_size(space.needed)}\n"
            f"지금 남은 공간: {format_size(space.free)}\n"
            f"복사 후 남는 공간: {format_size(space.remaining)}\n\n"
            f"{len(self.items):,}개 파일을 복사할까요?"
        )
        if ask(self, QMessageBox.Question, "복사 확인", text, "복사"):
            self.mode = core.MODE_COPY
            self.accept()

    def choose_move(self):
        space = core.check_space(self.items, self.target_dir, core.MODE_MOVE)
        if not space.enough:
            self.warn_no_space(space)
            return
        text = (
            "옮긴 파일은 원래 위치에서 사라지며 되돌릴 수 없습니다.\n\n"
            f"{len(self.items):,}개 파일을 {self.target_dir} 로 옮길까요?"
        )
        if space.needed:
            text += (
                f"\n\n다른 드라이브에서 옮겨 오는 파일: {format_size(space.needed)}\n"
                f"옮긴 후 남는 공간: {format_size(space.remaining)}"
            )
        if ask(self, QMessageBox.Warning, "옮기기 경고", text, "옮기기"):
            self.mode = core.MODE_MOVE
            self.accept()

    def warn_no_space(self, space):
        text = (
            "디스크 공간이 부족합니다.\n\n"
            f"필요한 공간: {format_size(space.needed)}\n"
            f"지금 남은 공간: {format_size(space.free)}\n"
            f"(작업 후에도 {format_size(core.SAFETY_MARGIN)}는 남아 있어야 해요)"
        )
        box = QMessageBox(QMessageBox.Warning, "디스크 공간 부족", text, parent=self)
        box.addButton("확인", QMessageBox.AcceptRole)
        box.exec()


def ask(parent, icon, title, text, ok_text):
    '확인 버튼 글자를 바꿀 수 있는 예/아니오 창. 기본 선택은 취소'
    box = QMessageBox(icon, title, text, parent=parent)
    ok_button = box.addButton(ok_text, QMessageBox.AcceptRole)
    cancel_button = box.addButton("취소", QMessageBox.RejectRole)
    box.setDefaultButton(cancel_button)
    box.exec()
    return box.clickedButton() is ok_button
