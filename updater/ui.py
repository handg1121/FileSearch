"""User-facing update controls. Network and hashing work never runs on the Qt UI thread."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from updater import config
from updater.protocol import Cancelled, check_cancel, download, fetch_manifest, verify_archive, verify_manifest, version_tuple
from updater.storage import Layout, atomic_write, json_bytes


class UpdateWorker(QThread):
    progress = Signal(int)

    def __init__(self, layout, parent=None):
        super().__init__(parent)
        self.layout = layout
        self.result = ""
        self.error = ""
        self._last_percent = -1

    def report(self, done, total):
        percent = int(done * 100 / total)
        if percent != self._last_percent:
            self._last_percent = percent
            self.progress.emit(percent)

    def run(self):
        try:
            raw = fetch_manifest()
            check_cancel(self.isInterruptionRequested)
            release = verify_manifest(raw)
            if version_tuple(release["version"]) <= version_tuple(config.VERSION):
                self.result = "latest"
                return
            if release["version"] in self.layout.read_state()["failed"]:
                self.result = "deferred"
                return
            archive = self.layout.archive_path(release)
            if archive.exists():
                try:
                    verify_archive(archive, release, self.isInterruptionRequested)
                except Cancelled:
                    raise
                except Exception:
                    archive.unlink()
            if not archive.exists():
                download(release, archive, self.report, self.isInterruptionRequested)
            check_cancel(self.isInterruptionRequested)
            atomic_write(self.layout.pending_path, raw)
            self.result = "ready"
        except Cancelled:
            self.result = "cancelled"
        except Exception as error:
            self.error = str(error)
            self.result = "error"


class UpdateController(QObject):
    def __init__(self, window, *, layout=None, automatic=True):
        super().__init__(window)
        self.window = window
        self.layout = layout
        self.worker = None
        self.closing = False
        self.ready = False
        self.manual = False
        self.restart_requested = False
        if layout is None:
            root = os.environ.get("FILESEARCH_INSTALL_ROOT")
            if not getattr(sys, "frozen", False) or not root:
                return  # Source development and existing GUI tests do not use the network.
            self.layout = Layout(root)
        self.label = QLabel(os.environ.get("FILESEARCH_UPDATE_NOTICE", ""))
        self.button = QPushButton("업데이트 확인")
        self.button.setObjectName("linkButton")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setContentsMargins(8, 0, 12, 0)
        self.button.setToolTip("현재 버전 " + config.VERSION)
        self.button.clicked.connect(self.clicked)
        self.window.statusBar().addPermanentWidget(self.label)
        self.window.statusBar().addPermanentWidget(self.button)
        if automatic:
            QTimer.singleShot(2500, self.check)
            self.timer = QTimer(self)
            self.timer.setInterval(6 * 60 * 60 * 1000)
            self.timer.timeout.connect(self.check)
            self.timer.start()

    def check(self, manual=False):
        if self.layout is None or self.closing or self.ready or self.worker is not None:
            return
        self.manual = manual
        self.button.setEnabled(False)
        if manual:
            self.label.setText("업데이트 확인 중이에요.")
        worker = UpdateWorker(self.layout, self)
        self.worker = worker
        worker.progress.connect(lambda percent: self.label.setText(f"업데이트 다운로드 중 {percent}%"))
        worker.finished.connect(self.finished)
        worker.start()

    def finished(self):
        worker = self.worker
        self.worker = None
        self.button.setEnabled(True)
        if worker.result == "ready":
            self.ready = True
            self.label.setText("업데이트가 준비됐어요. 다음 실행부터 적용돼요.")
            self.button.setText("지금 다시 시작")
        elif worker.result == "latest" and self.manual:
            self.label.setText("최신 버전이에요.")
        elif worker.result == "deferred" and self.manual:
            self.label.setText("다음 업데이트를 기다리고 있어요. 현재 버전을 계속 사용해 주세요.")
        elif worker.result == "error":
            self.label.setText("업데이트를 확인하지 못했어요. 나중에 다시 시도해 주세요." if self.manual else "")
        worker.deleteLater()
        if self.closing:
            QTimer.singleShot(0, self.window.close)

    def clicked(self):
        if not self.ready:
            self.check(manual=True)
            return
        if QApplication.activeModalWidget() is not None:
            return
        if any(thread.isRunning() for thread in self.window.findChildren(QThread)):
            self.label.setText("진행 중인 작업을 마친 뒤 다시 시작해 주세요.")
            return
        self.restart_requested = True
        self.window.close()

    def allow_close(self):
        if self.layout is None:
            return True
        if QApplication.activeModalWidget() is not None:
            return False
        if self.worker is not None:
            self.closing = True
            self.worker.requestInterruption()
            self.label.setText("종료 준비 중이에요.")
            return False
        if self.restart_requested:
            token = os.environ.get("FILESEARCH_UPDATE_TOKEN", "")
            if len(token) == 32 and all(c in "0123456789abcdef" for c in token):
                atomic_write(self.layout.work / ("restart-" + token), b"restart")
        return True


def acknowledge_startup():
    """Acknowledge only after the actual application window and tag database initialize."""
    raw = os.environ.get("FILESEARCH_UPDATE_ACK")
    root = os.environ.get("FILESEARCH_INSTALL_ROOT")
    token = os.environ.get("FILESEARCH_UPDATE_TOKEN", "")
    if not raw or not root or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        return
    path = Path(raw)
    if path.resolve() != Path(root).resolve() / ".updates" / ("ready-" + token + ".json"):
        return
    atomic_write(path, json_bytes({"token": token, "version": config.VERSION}))
