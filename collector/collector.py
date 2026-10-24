'파일 모으기 창: 찾을 위치·유형·저장 위치를 고르고, 찾기 → 확인 → 옮기기/복사 흐름을 이어 준다'
import os

from PySide6.QtCore import QDir, QStorageInfo
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QRadioButton, QVBoxLayout,
)

from collector import type_selector_script as core
from collector.progress_dialog import ProgressDialog
from collector.result_dialog import ResultDialog
from collector.summary_dialog import SummaryDialog
from collector.type_selector import TypeSelector
from collector.workers import CollectThread, ScanThread
from common.settings import get_save_dir, set_save_dir
from common.widgets import make_button, make_label, make_separator


class CollectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("collectDialog")
        self.setWindowTitle("파일 모으기")
        self.setMinimumWidth(860)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title_box.addWidget(make_label("파일 모으기", "dialogTitle"))
        title_box.addWidget(make_label("모을 파일의 위치와 유형을 선택하세요.", "muted"))
        layout.addLayout(title_box)
        layout.addWidget(make_separator())
        layout.addLayout(self.build_source_section())
        layout.addWidget(make_separator())
        self.type_selector = TypeSelector()
        self.type_selector.selection_changed.connect(self.update_footer)
        layout.addWidget(self.type_selector)
        layout.addWidget(make_separator())
        layout.addLayout(self.build_target_section())
        layout.addWidget(make_separator())
        layout.addLayout(self.build_footer())
        self.update_source_mode()
        self.update_footer(len(self.type_selector.selected_types()))

    def build_source_section(self):
        section = QVBoxLayout()
        section.setSpacing(10)
        section.addWidget(make_label("찾을 위치", "sectionTitle"))
        self.all_disks_radio = QRadioButton("모든 디스크")
        self.all_disks_radio.setChecked(True)
        self.all_disks_radio.toggled.connect(self.update_source_mode)
        section.addWidget(self.all_disks_radio)
        drive_row = QHBoxLayout()
        drive_row.setContentsMargins(26, 0, 0, 0)
        drive_row.setSpacing(20)
        self.drive_checks = []
        for volume in QStorageInfo.mountedVolumes():
            if not volume.isValid() or not volume.isReady():
                continue
            root = volume.rootPath().rstrip("/")
            text = f"{root}  {volume.name()}" if volume.name() else root
            check = QCheckBox(text)
            check.setChecked(True)
            drive_row.addWidget(check)
            self.drive_checks.append((root + "\\", check))
        drive_row.addStretch()
        section.addLayout(drive_row)
        self.folder_radio = QRadioButton("폴더 지정")
        section.addWidget(self.folder_radio)
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(26, 0, 0, 0)
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("찾을 폴더를 선택하세요")
        self.source_input.setMinimumHeight(36)
        folder_row.addWidget(self.source_input, 1)
        self.source_button = make_button("폴더 선택", "secondaryButton")
        self.source_button.clicked.connect(lambda: self.choose_folder(self.source_input))
        folder_row.addWidget(self.source_button)
        section.addLayout(folder_row)
        subfolder_row = QHBoxLayout()
        subfolder_row.setContentsMargins(26, 0, 0, 0)
        self.subfolder_check = QCheckBox("하위 폴더 포함")
        self.subfolder_check.setChecked(True)
        subfolder_row.addWidget(self.subfolder_check)
        section.addLayout(subfolder_row)
        return section

    def update_source_mode(self):
        all_disks = self.all_disks_radio.isChecked()
        for _, check in self.drive_checks:
            check.setEnabled(all_disks)
        for widget in (self.source_input, self.source_button, self.subfolder_check):
            widget.setEnabled(not all_disks)

    def build_target_section(self):
        section = QVBoxLayout()
        section.setSpacing(10)
        section.addWidget(make_label("저장 위치", "sectionTitle"))
        row = QHBoxLayout()
        self.target_input = QLineEdit(get_save_dir())
        self.target_input.setMinimumHeight(36)
        self.target_input.editingFinished.connect(self.save_target)
        row.addWidget(self.target_input, 1)
        change_button = make_button("변경", "secondaryButton")
        change_button.clicked.connect(self.change_target)
        row.addWidget(change_button)
        section.addLayout(row)
        section.addWidget(make_label(
            "원래 폴더 구조대로 한곳에 모아요. 저장 위치 폴더와 윈도우·프로그램 폴더는 찾지 않아요.",
            "muted",
        ))
        return section

    def choose_folder(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택", line_edit.text())
        if folder:
            line_edit.setText(QDir.toNativeSeparators(folder))

    def change_target(self):
        self.choose_folder(self.target_input)
        self.save_target()

    def save_target(self):
        '바꾼 저장 위치를 바로 설정에 기록 (다음에 켜도, 검색 대상도 이 위치)'
        target = self.target_input.text().strip()
        if target and os.path.abspath(target) != get_save_dir():
            set_save_dir(os.path.abspath(target))

    def build_footer(self):
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.footer_label = make_label("", "muted")
        footer.addWidget(self.footer_label)
        footer.addStretch()
        cancel_button = make_button("취소", "secondaryButton")
        cancel_button.setMinimumSize(110, 42)
        cancel_button.clicked.connect(self.reject)
        footer.addWidget(cancel_button)
        self.find_button = make_button("파일 찾기", "primaryButton")
        self.find_button.setMinimumSize(150, 42)
        self.find_button.clicked.connect(self.start)
        footer.addWidget(self.find_button)
        return footer

    def update_footer(self, count):
        self.footer_label.setText(f"{count}개 유형 선택")
        self.find_button.setEnabled(count > 0)

    def start(self):
        sources = self.selected_sources()
        if not sources:
            return
        target_dir = self.selected_target()
        if not target_dir:
            return
        items = self.scan(sources, target_dir)
        if items is None:
            return
        if not items:
            QMessageBox.information(self, "찾은 파일 없음", "선택한 위치에서 해당 유형의 파일을 찾지 못했어요.")
            return
        summary = SummaryDialog(items, target_dir, self)
        if summary.exec() != QDialog.Accepted:
            return
        result = self.collect(items, target_dir, summary.mode)
        if result is None:
            return
        ResultDialog(result, target_dir, self).exec()
        self.accept()

    def selected_sources(self):
        if self.all_disks_radio.isChecked():
            sources = []
            for root, check in self.drive_checks:
                if check.isChecked():
                    sources.append(root)
            if not sources:
                QMessageBox.information(self, "찾을 위치", "찾을 드라이브를 하나 이상 선택하세요.")
            return sources
        folder = self.source_input.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "찾을 위치", "찾을 폴더를 선택하세요.")
            return []
        return [folder]

    def selected_target(self):
        target = self.target_input.text().strip()
        if not target:
            QMessageBox.information(self, "저장 위치", "저장 위치를 선택하세요.")
            return ""
        target = os.path.abspath(target)
        drive = os.path.splitdrive(target)[0]
        if not os.path.exists(drive + "\\"):
            QMessageBox.information(self, "저장 위치", f"저장 위치의 드라이브({drive})를 찾을 수 없어요.")
            return ""
        return target

    def scan(self, sources, target_dir):
        '찾은 목록을 돌려줌. 취소하거나 오류가 나면 None'
        include_subfolders = self.all_disks_radio.isChecked() or self.subfolder_check.isChecked()
        thread = ScanThread(sources, self.type_selector.selected_types(), target_dir, include_subfolders)
        progress = ProgressDialog("파일 찾는 중", self)

        def show_progress(found, folder):
            progress.set_status(f"{found:,}개 찾음")
            progress.set_detail(folder)

        thread.progress.connect(show_progress)
        thread.finished.connect(progress.accept)
        progress.cancel_requested.connect(thread.requestInterruption)
        thread.start()
        progress.exec()
        thread.wait()
        if thread.error:
            self.show_error(thread.error)
            return None
        if thread.isInterruptionRequested():
            return None
        return thread.items

    def collect(self, items, target_dir, mode):
        '옮기기·복사 결과(CollectResult)를 돌려줌. 예상 못 한 오류가 나면 None'
        action = "옮기는" if mode == core.MODE_MOVE else "복사하는"
        thread = CollectThread(items, target_dir, mode)
        progress = ProgressDialog(f"파일 {action} 중", self)
        progress.set_progress(0, len(items))

        def show_progress(done, total, path):
            progress.set_progress(done, total)
            progress.set_status(f"{done:,} / {total:,}")
            progress.set_detail(path)

        thread.progress.connect(show_progress)
        thread.finished.connect(progress.accept)
        progress.cancel_requested.connect(thread.requestInterruption)
        thread.start()
        progress.exec()
        thread.wait()
        if thread.error:
            self.show_error(thread.error, core.journal_path(target_dir))
            return None
        return thread.result

    def show_error(self, detail, journal=""):
        text = "예상하지 못한 오류로 작업을 멈췄어요."
        if journal:
            text += f"\n어디까지 처리했는지는 작업 기록에서 확인할 수 있어요.\n{journal}"
        box = QMessageBox(QMessageBox.Critical, "오류", text, parent=self)
        box.setDetailedText(detail)
        box.exec()
