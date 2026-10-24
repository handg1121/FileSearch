'파일 검색기 - 메인 화면 (파일명·본문 검색, 태그는 아직 화면만)'
import os
import sys
import time

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from collector.collector import CollectDialog
from collector.progress_dialog import ProgressDialog
from common.settings import get_save_dir
from common.widgets import (
    STYLE, TAG_COLORS, make_button, make_chip, make_dot, make_label, make_separator,
)
from searcher.filename_search import modified_since, parse_keywords
from searcher.preview_panel import PreviewPanel
from searcher.result_table import ResultPanel
from searcher.search_bar import SearchBar
from searcher.search_pipeline import SearchRequest
from searcher.workers import SearchThread

TAG_COUNTS = [("계약서", 86), ("검토중", 24), ("거래처", 48), ("완료", 132), ("중요", 16)]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("파일 검색기")
        self.resize(1500, 920)
        self.root_dir = get_save_dir()
        central = QWidget()
        central.setObjectName("central")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_sidebar())
        layout.addWidget(self.build_main_area(), 1)
        self.setCentralWidget(central)
        self.build_status_bar()

    def build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 12)
        layout.setSpacing(4)
        nav_group = QButtonGroup(self)
        for text in ("전체 파일", "최근 추가", "중복 파일"):
            button = QPushButton()
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            row = QHBoxLayout(button)
            row.setContentsMargins(12, 0, 12, 0)
            name_label = QLabel(text)
            name_label.setStyleSheet("background: transparent; font-size: 11pt;")
            name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(name_label)
            row.addStretch()
            nav_group.addButton(button)
            layout.addWidget(button)
        nav_group.buttons()[0].setChecked(True)
        layout.addSpacing(12)
        layout.addWidget(make_separator())
        layout.addSpacing(12)
        tag_header = QHBoxLayout()
        tag_header.setContentsMargins(8, 0, 0, 0)
        tag_header.addWidget(make_label("내 태그"))
        tag_header.addStretch()
        add_tag_button = make_button("+", "secondaryButton")
        add_tag_button.setFixedSize(30, 30)
        add_tag_button.setStyleSheet("padding: 0px;")
        tag_header.addWidget(add_tag_button)
        layout.addLayout(tag_header)
        layout.addSpacing(6)
        for tag, count in TAG_COUNTS:
            row = QHBoxLayout()
            row.setContentsMargins(12, 6, 8, 6)
            row.setSpacing(10)
            row.addWidget(make_dot(TAG_COLORS[tag][2]))
            row.addWidget(make_label(tag))
            row.addStretch()
            row.addWidget(make_label(str(count), "muted"))
            layout.addLayout(row)
        layout.addStretch()
        layout.addWidget(make_button("태그 관리", "flatButton"))
        return sidebar

    def build_main_area(self):
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)
        layout.addLayout(self.build_header())
        self.search_bar = SearchBar()
        self.search_bar.search_requested.connect(self.run_search)
        layout.addWidget(self.search_bar)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.results = ResultPanel()
        left_layout.addWidget(self.results, 1)
        left_layout.addWidget(self.build_tag_bar())
        self.preview = PreviewPanel()
        self.results.table.current_hit_changed.connect(self.preview.show_hit)
        self.results.table.checked_count_changed.connect(self.update_selected_count)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(16)
        splitter.addWidget(left)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 400])
        layout.addWidget(splitter, 1)
        return area

    def build_header(self):
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label("내 파일", "pageTitle"))
        titles.addWidget(make_label("모은 파일을 검색하고 태그로 정리하세요", "muted"))
        header.addLayout(titles)
        header.addStretch()
        collect_button = make_button("파일 모으기", "primaryButton")
        collect_button.setMinimumHeight(48)
        collect_button.setStyleSheet("font-size: 12pt; padding: 8px 28px;")
        collect_button.clicked.connect(self.open_collect_dialog)
        header.addWidget(collect_button, 0, Qt.AlignTop)
        return header

    def open_collect_dialog(self):
        dialog = CollectDialog(self)
        accepted = dialog.exec() == QDialog.Accepted
        self.root_dir = get_save_dir()
        self.root_label.setText(f"저장 위치  {self.root_dir}   ")
        if accepted:
            self.run_search()

    def build_tag_bar(self):
        bar = QFrame()
        bar.setObjectName("tagBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.selected_count_label = make_label("0개 선택", "selectedCount")
        input_row.addWidget(self.selected_count_label)
        tag_input = QLineEdit()
        tag_input.setPlaceholderText("추가할 태그 입력")
        tag_input.setMinimumHeight(36)
        input_row.addWidget(tag_input, 1)
        input_row.addWidget(make_button("태그 부착", "primaryButton"))
        input_row.addWidget(make_button("태그 제거", "secondaryButton"))
        layout.addLayout(input_row)
        existing_row = QHBoxLayout()
        existing_row.setSpacing(8)
        existing_row.addWidget(make_label("기존 태그", "muted"))
        for tag in ("계약서", "검토중", "중요"):
            existing_row.addWidget(make_chip(tag))
        existing_row.addStretch()
        layout.addLayout(existing_row)
        return bar

    def update_selected_count(self, count):
        self.selected_count_label.setText(f"{count}개 선택")

    def run_search(self):
        name_enabled = self.search_bar.name_search_enabled()
        body_enabled = self.search_bar.content_search_enabled()
        self.status_label.setToolTip("")
        if not name_enabled and not body_enabled:
            self.results.show_hits([], [])
            self.status_label.setText("검색할 항목을 하나 이상 선택하세요.")
            return
        if not os.path.isdir(self.root_dir):
            self.results.show_hits([], [])
            self.status_label.setText(f"저장 위치({self.root_dir})가 아직 없어요. 먼저 파일을 모아 주세요.")
            return
        query = self.search_bar.keyword_text()
        request = SearchRequest(
            self.root_dir, query, name_enabled, body_enabled,
            self.search_bar.extensions(), modified_since(self.search_bar.date_range()),
        )
        progress = ProgressDialog("파일 검색", self)
        thread = SearchThread(request, self)

        def show_progress(phase, done, total, path):
            progress.set_status(f"{phase} · {done:,}/{total:,}" if total else f"{phase} · {done:,}개")
            progress.set_progress(done, total)
            progress.set_detail(path)

        thread.progress.connect(show_progress)
        thread.finished.connect(progress.accept)
        progress.cancel_requested.connect(thread.requestInterruption)
        started = time.perf_counter()
        thread.start()
        progress.exec()
        thread.wait()
        elapsed = time.perf_counter() - started
        result, error = thread.result, thread.error
        thread.deleteLater()
        progress.deleteLater()
        if error:
            self.results.show_hits([], [])
            self.status_label.setText(f"검색하지 못했어요: {error}")
            self.status_label.setToolTip(error)
            return
        if result.cancelled:
            self.results.show_hits([], [])
            self.status_label.setText("검색을 취소했어요. 이미 읽은 본문은 다음 검색에서 재사용해요.")
            return
        self.results.show_hits(result.hits, parse_keywords(query) if name_enabled else [])
        details = [f"{len(result.hits):,}개 찾음", f"{elapsed:.2f}초"]
        if body_enabled:
            details.append(f"본문 갱신 {result.refreshed:,}개 · 재사용 {result.reused:,}개")
            if result.unsupported:
                details.append(f"본문 미지원 {result.unsupported:,}개")
        if result.errors:
            details.append(f"확인 실패 {len(result.errors):,}건 (마우스를 올려 상세 확인)")
            self.status_label.setToolTip("\n\n".join(f"{path}\n{message}" for path, message in result.errors))
        self.status_label.setText(" · ".join(details))

    def build_status_bar(self):
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self.status_label = make_label("검색어를 입력하고 검색을 누르세요. 비워 두고 누르면 전체 파일이 나와요.")
        self.status_label.setContentsMargins(12, 2, 0, 2)
        status.addWidget(self.status_label)
        self.root_label = make_label(f"저장 위치  {self.root_dir}   ", "muted")
        status.addPermanentWidget(self.root_label)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(STYLE)
    translator = QTranslator(app)
    if translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
