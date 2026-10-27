"""중복 찾기와 휴지통 보내기를 UI 밖의 작업 스레드에서 실행해요."""

import time
from PySide6.QtCore import QThread, Signal

from searcher.metadata import SearchCancelled


class TaskThread(QThread):
    '작업 함수(on_progress, should_stop을 받는)를 실행하고 결과·오류·취소 여부를 남겨요.'
    progress = Signal(str, int, int, str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.result = None
        self.error = ""
        self.cancelled = False
        self._last_progress = 0
        self._last_phase = ""

    def report_progress(self, phase, done, total, path):
        now = time.monotonic()
        if phase != self._last_phase or now - self._last_progress >= 0.1 or done == total:
            self.progress.emit(phase, done, total, path)
            self._last_progress, self._last_phase = now, phase

    def run(self):
        try:
            self.result = self.task(on_progress=self.report_progress,
                                    should_stop=self.isInterruptionRequested)
        except SearchCancelled:
            self.cancelled = True
        except Exception as error:
            self.error = str(error) or type(error).__name__
