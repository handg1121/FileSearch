"""사이드바 '중복 파일' 버튼의 실행 흐름(찾기 → 고르기 → 휴지통 → 화면 갱신)을 연결해요."""

import os

from PySide6.QtWidgets import QDialog, QMessageBox

from collector.progress_dialog import ProgressDialog
from common.settings import get_body_cache_path
from duplicates.dialog import DuplicateDialog
from duplicates.finder import find_duplicates
from duplicates.remover import remove_duplicates
from duplicates.trash import send_to_trash
from duplicates.workers import TaskThread


class DuplicateController:
    def __init__(self, window):
        self.window = window
        self.db_path = get_body_cache_path()
        window.nav_buttons["중복 파일"].clicked.connect(self.open)

    def run_task(self, title, task):
        progress = ProgressDialog(title, self.window)
        thread = TaskThread(task, self.window)

        def show_progress(phase, done, total, path):
            progress.set_status(f"{phase} · {done:,}/{total:,}" if total else f"{phase} · {done:,}개")
            progress.set_progress(done, total)
            progress.set_detail(path)

        thread.progress.connect(show_progress)
        thread.finished.connect(progress.accept)
        progress.cancel_requested.connect(thread.requestInterruption)
        thread.start()
        progress.exec()
        thread.wait()
        outcome = thread.result, thread.error, thread.cancelled
        thread.deleteLater()
        progress.deleteLater()
        return outcome

    def open(self):
        try:
            self.find_and_remove()
        finally:
            # 중복 파일은 별도 창으로 보여 주므로 사이드바 선택은 원래대로 돌려요.
            self.window.nav_buttons["전체 파일"].setChecked(True)

    def find_and_remove(self):
        root = self.window.root_dir
        if not os.path.isdir(root):
            self.window.status_label.setText(f"저장 위치({root})가 아직 없어요. 먼저 파일을 모아 주세요.")
            return
        result, error, cancelled = self.run_task(
            "중복 파일 찾기",
            lambda **progress: find_duplicates(root, cache_path=self.db_path, **progress),
        )
        if error:
            self.window.status_label.setText(f"중복 파일을 찾지 못했어요: {error}")
            return
        if cancelled:
            self.window.status_label.setText("중복 파일 찾기를 취소했어요.")
            return
        if not result.groups:
            message = f"파일 {result.scanned:,}개 중 내용이 같은 파일이 없어요."
            if result.errors:
                message += f" (확인하지 못한 파일 {len(result.errors):,}개)"
            self.window.status_label.setText(message)
            QMessageBox.information(self.window, "중복 파일", message)
            return
        self.window.status_label.setText(f"중복 묶음 {len(result.groups):,}개 · 내용 새로 읽음 {result.hashed:,}개 · "
                                         f"저장된 해시 사용 {result.reused:,}개")
        dialog = DuplicateDialog(result, self.window)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            choices = dialog.selected_choices()
        finally:
            dialog.deleteLater()
        removed, error, _ = self.run_task(
            "중복 파일 정리",
            lambda **progress: remove_duplicates(choices, trash=send_to_trash, db_path=self.db_path, **progress),
        )
        if error:
            QMessageBox.warning(self.window, "중복 파일 정리", f"정리하지 못했어요: {error}")
            return
        self.show_removed(removed)
        self.refresh_window(removed)

    def show_removed(self, removed):
        lines = [f"휴지통으로 보냄 {len(removed.trashed):,}개 · 실패 {len(removed.failed):,}개"]
        if removed.cancelled:
            lines.append("취소해서 남은 묶음은 처리하지 않았어요.")
        if removed.moved_tags:
            lines.append(f"태그 {removed.moved_tags:,}건을 남긴 파일로 옮겼어요.")
        if removed.tag_error:
            lines.append(f"파일은 휴지통으로 보냈지만 태그 기록을 정리하지 못했어요: {removed.tag_error}")
        box = QMessageBox(QMessageBox.Warning if removed.failed or removed.tag_error else QMessageBox.Information,
                          "중복 파일 정리", "\n".join(lines), QMessageBox.Ok, self.window)
        if removed.failed:
            box.setDetailedText("\n\n".join(f"{path}\n{reason}" for path, reason in removed.failed))
        box.exec()
        box.deleteLater()
        self.window.status_label.setText(" · ".join(lines))

    def refresh_window(self, removed):
        if not removed.trashed:
            return
        # 지운 파일이 결과 목록에 남지 않도록 태그와 검색 결과를 다시 읽어요.
        status = self.window.status_label.text()
        if self.window.active_tag_id is not None:
            self.window.tags.refresh()
        else:
            self.window.tags.refresh(reload_results=False)
            if self.window.results.table.hits:
                self.window.run_search()
        self.window.status_label.setText(status + " · 목록을 새로 고쳤어요.")
