'훑기·옮기기·복사 중에 보여 주는 진행 창'
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QProgressBar, QVBoxLayout

from common.widgets import make_button, make_label


class ProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("collectDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(make_label(title, "sectionTitle"))
        self.status_label = make_label("준비하는 중...")
        layout.addWidget(self.status_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)
        self.detail_label = make_label("", "muted")
        layout.addWidget(self.detail_label)
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_button = make_button("취소", "secondaryButton")
        self.cancel_button.clicked.connect(self.request_cancel)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

    def set_status(self, text):
        self.status_label.setText(text)

    def set_detail(self, path):
        width = self.detail_label.width() or 500
        elided = self.detail_label.fontMetrics().elidedText(path, Qt.ElideMiddle, width)
        self.detail_label.setText(elided)

    def set_progress(self, done, total):
        self.bar.setRange(0, total)
        self.bar.setValue(done)

    def request_cancel(self):
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("멈추는 중...")
        self.cancel_requested.emit()

    def reject(self):
        if self.cancel_button.isEnabled():
            self.request_cancel()
