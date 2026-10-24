"""검색과 SQLite 연결을 UI 밖의 작업 스레드에서 실행해요."""

import time
from PySide6.QtCore import QThread, Signal

from searcher.search_pipeline import run


class SearchThread(QThread):
    progress = Signal(str, int, int, str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.result = None
        self.error = ""
        self._last_progress = 0
        self._last_phase = ""

    def report_progress(self, phase, done, total, path):
        now = time.monotonic()
        if phase != self._last_phase or now - self._last_progress >= 0.1 or done == total:
            self.progress.emit(phase, done, total, path)
            self._last_progress, self._last_phase = now, phase

    def run(self):
        try:
            self.result = run(self.request, on_progress=self.report_progress,
                              should_stop=self.isInterruptionRequested)
        except Exception as error:
            self.error = str(error) or type(error).__name__
