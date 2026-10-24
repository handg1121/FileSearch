'모으기 핵심 로직을 화면이 멈추지 않도록 별도 스레드에서 돌리는 부분'
import time
import traceback

from PySide6.QtCore import QThread, Signal

from collector import type_selector_script as core

PROGRESS_INTERVAL = 0.1


class ScanThread(QThread):
    progress = Signal(int, str)

    def __init__(self, sources, extensions, target_dir, include_subfolders):
        super().__init__()
        self.sources = sources
        self.extensions = extensions
        self.target_dir = target_dir
        self.include_subfolders = include_subfolders
        self.items = []
        self.error = None
        self.last_report = 0.0

    def run(self):
        try:
            self.items = core.scan_files(
                self.sources,
                self.extensions,
                self.target_dir,
                self.include_subfolders,
                on_folder=self.report,
                should_stop=self.isInterruptionRequested,
            )
        except Exception:
            self.error = traceback.format_exc()

    def report(self, folder, found):
        now = time.monotonic()
        if now - self.last_report >= PROGRESS_INTERVAL:
            self.last_report = now
            self.progress.emit(found, folder)


class CollectThread(QThread):
    progress = Signal(int, int, str)

    def __init__(self, items, target_dir, mode):
        super().__init__()
        self.items = items
        self.target_dir = target_dir
        self.mode = mode
        self.result = None
        self.error = None
        self.last_report = 0.0

    def run(self):
        try:
            self.result = core.run_collect(
                self.items,
                self.target_dir,
                self.mode,
                on_progress=self.report,
                should_stop=self.isInterruptionRequested,
            )
        except Exception:
            self.error = traceback.format_exc()

    def report(self, done, total, path):
        now = time.monotonic()
        if done == total or now - self.last_report >= PROGRESS_INTERVAL:
            self.last_report = now
            self.progress.emit(done, total, path)
