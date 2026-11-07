"""우클릭·체크 선택 삭제와 목록·태그·미리보기 갱신을 연결해요."""

from dataclasses import dataclass, field
import os
import sqlite3

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from collector.progress_dialog import ProgressDialog
from common.file_actions import delete_file
from common.settings import get_body_cache_path
from duplicates.workers import TaskThread
from tagger.storage import forget_deleted_file


@dataclass
class DeleteResult:
    deleted: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    metadata_errors: list = field(default_factory=list)
    cancelled: bool = False


def delete_files(paths, db_path, *, on_progress=lambda *args: None, should_stop=lambda: False):
    result = DeleteResult()
    paths = list({os.path.normcase(os.path.abspath(path)): path for path in paths}.values())
    for index, path in enumerate(paths):
        if should_stop():
            result.cancelled = True
            break
        on_progress("파일 삭제", index, len(paths), path)
        error = delete_file(path)
        if error:
            result.failed.append((path, error))
        else:
            result.deleted.append(path)
            try:
                forget_deleted_file(path, db_path)
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
                result.metadata_errors.append((path, str(error)))
        on_progress("파일 삭제", index + 1, len(paths), path)
    return result


class FileController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.db_path = get_body_cache_path()
        window.results.table.delete_requested.connect(lambda path: self.delete([path]))
        window.delete_button.clicked.connect(self.delete_selected)

    def delete_selected(self):
        # 행 선택과 체크박스 선택은 달라요. 체크한 파일만 대상으로 고정해요.
        self.delete([hit.path for hit in self.window.results.table.checked_hits()])

    def delete(self, paths):
        if not paths:
            return
        progress = ProgressDialog("파일 삭제", self.window)
        thread = TaskThread(lambda **callbacks: delete_files(paths, self.db_path, **callbacks), self.window)

        def show_progress(phase, done, total, path):
            progress.set_status(f"휴지통으로 보내는 중 · {done:,}/{total:,}")
            progress.set_progress(done, total)
            progress.set_detail(path)

        thread.progress.connect(show_progress)
        thread.finished.connect(progress.accept)
        progress.cancel_requested.connect(thread.requestInterruption)
        thread.start()
        progress.exec()
        thread.wait()
        result, error = thread.result, thread.error
        thread.deleteLater()
        progress.deleteLater()
        if error:
            QMessageBox.warning(self.window, "파일 삭제", error)
            return

        # 파일이 지워졌으면 DB 정리 실패와 관계없이 화면에서는 바로 빼요.
        if result.deleted:
            self.window.results.remove_paths(result.deleted)
            self.window.tags.refresh(reload_results=False)
        message = f"삭제 {len(result.deleted):,}개 · 실패 {len(result.failed):,}개 · {len(self.window.results.hits):,}개 남음"
        if result.cancelled:
            message += " · 삭제를 중단했어요."
        if result.metadata_errors:
            message += " · 태그·캐시 기록 정리 실패"
        details = [f"{path}\n{reason}" for path, reason in result.failed]
        details += [f"{path}\n파일은 삭제했지만 태그·캐시 기록을 정리하지 못했어요: {reason}"
                    for path, reason in result.metadata_errors]
        self.window.status_label.setText(message)
        self.window.status_label.setToolTip("\n\n".join(details))
        if details:
            box = QMessageBox(QMessageBox.Warning, "파일 삭제", message, QMessageBox.Ok, self.window)
            box.setDetailedText("\n\n".join(details))
            box.exec()
            box.deleteLater()
