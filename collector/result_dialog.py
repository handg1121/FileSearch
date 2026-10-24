'옮기기·복사가 끝난 뒤 결과와 실패 목록을 보여 주는 창'
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from collector import type_selector_script as core
from common.widgets import make_button, make_label


class ResultDialog(QDialog):
    def __init__(self, result, target_dir, parent=None):
        super().__init__(parent)
        self.setObjectName("collectDialog")
        action = "옮기기" if result.mode == core.MODE_MOVE else "복사"
        title = f"{action} 중단됨" if result.stopped else f"{action} 완료"
        self.setWindowTitle(title)
        self.setMinimumWidth(640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)
        layout.addWidget(make_label(title, "dialogTitle"))
        layout.addWidget(make_label(f"{action} 완료 {result.done:,}개 · 실패 {len(result.failed):,}개", "sectionTitle"))
        if result.stopped:
            untouched = result.total - result.done - len(result.failed)
            layout.addWidget(make_label(f"남은 {untouched:,}개는 처리하지 않았어요. 원래 위치에 그대로 있어요."))
        if result.recovered:
            layout.addWidget(make_label(f"시작 전에 지난번 중단된 작업 {result.recovered}건을 정리했어요."))
        if result.failed:
            layout.addWidget(make_label("처리하지 못한 파일 (원본은 원래 위치에 남아 있어요)", "muted"))
            layout.addWidget(self.build_failed_table(result.failed))
        layout.addWidget(make_label(f"작업 기록: {core.journal_path(target_dir)}", "muted"))
        button_row = QHBoxLayout()
        button_row.addStretch()
        ok_button = make_button("확인", "primaryButton")
        ok_button.setMinimumSize(100, 40)
        ok_button.clicked.connect(self.accept)
        button_row.addWidget(ok_button)
        layout.addLayout(button_row)

    def build_failed_table(self, failed):
        table = QTableWidget(len(failed), 2)
        table.setHorizontalHeaderLabels(["파일", "사유"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for row, (path, reason) in enumerate(failed):
            table.setItem(row, 0, QTableWidgetItem(path))
            table.setItem(row, 1, QTableWidgetItem(reason))
        table.setMinimumHeight(160)
        return table
