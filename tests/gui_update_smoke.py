"""Exercise update controls and a real Qt download worker without internet/user data."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog
from common import settings
from common.widgets import STYLE
from updater import config, protocol
from updater.storage import Layout, json_bytes
from updater.ui import UpdateController, UpdateWorker
import main

args.workspace.mkdir(parents=True)
args.artifacts.mkdir(parents=True)
settings.SETTINGS_PATH = str(args.workspace / "profile/settings.json")
source = args.workspace / "files"
source.mkdir()
settings.set_save_dir(str(source))
(source / "계약.txt").write_text("계약금", encoding="utf-8")
install = args.workspace / "install"
install.mkdir()
layout = Layout(install)
key = Ed25519PrivateKey.generate()
public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
release = dict(schema=1, version="0.3.0", launcher_protocol=1, data_schema=1, size=3,
               sha256=hashlib.sha256(b"zip").hexdigest(),
               url=f"https://github.com/{config.REPOSITORY}/releases/download/v0.3.0/FileSearch-update-0.3.0-win64.zip")
payload = json_bytes(release)
raw = json_bytes({"payload": base64.b64encode(payload).decode(), "signature": base64.b64encode(key.sign(payload)).decode()})
app = QApplication([])
for name in ("malgun.ttf", "malgunbd.ttf", "seguisym.ttf"):
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Malgun Gothic", 10))
app.setStyleSheet(STYLE)
checks, errors = [], []
sys.excepthook = lambda typ, value, tb: errors.append(str(value))


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def wait_until(predicate):
    end = time.monotonic() + 5
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    check("async_completed", predicate())


window = main.MainWindow()
window.updates = UpdateController(window, layout=layout, automatic=False)
window.show()
app.processEvents()
ui = window.updates
check("manual_check_label", ui.button.text() == "업데이트 확인")
with patch.object(config, "PUBLIC_KEY", public), patch("updater.ui.fetch_manifest", return_value=raw), \
     patch.object(protocol, "open_url", return_value=io.BytesIO(b"zip")):
    ui.button.click()
    check("download_disables_duplicate_check", not ui.button.isEnabled())
    wait_until(lambda: ui.worker is None)
check("update_prepared", ui.ready and layout.pending_path.is_file())
check("restart_label", ui.button.text() == "지금 다시 시작")
check("friendly_status", "다음 실행" in ui.label.text())
window.search_bar.keyword_input.setText("계약")
window.run_search()
check("search_works_with_pending_update", len(window.results.hits) == 1)
dialog = QDialog(window)
dialog.setModal(True)
dialog.show()
app.processEvents()
ui.clicked()
check("modal_work_prevents_restart", not ui.restart_requested)
check("modal_work_prevents_close", not ui.allow_close())
dialog.reject()
app.processEvents()
window.root_label.setText("저장 위치  " + source.name + "   ")
check("screenshot", window.grab().save(str(args.artifacts / "update_ready.png")))
check("normal_close_allowed", ui.allow_close())
with patch.dict(os.environ, {"FILESEARCH_UPDATE_TOKEN": "a" * 32}):
    ui.clicked()
check("restart_request_saved", (layout.work / ("restart-" + "a" * 32)).exists())
check("restart_closes_window", not window.isVisible())

window = main.MainWindow()
window.updates = UpdateController(window, layout=layout, automatic=False)
window.show()
ui = window.updates
with patch("updater.ui.fetch_manifest", side_effect=OSError("offline internal detail")):
    ui.check(manual=True)
    wait_until(lambda: ui.worker is None)
check("offline_message", "나중에" in ui.label.text())
check("no_internal_error_in_ui", "internal detail" not in ui.label.text())
check("offline_keeps_app_open", window.isVisible())

def slow_fetch():
    time.sleep(0.2)
    return raw

with patch("updater.ui.fetch_manifest", side_effect=slow_fetch):
    ui.check()
    window.close()
    check("shutdown_waits_for_worker", ui.closing and window.isVisible())
    wait_until(lambda: ui.worker is None and not window.isVisible())
check("no_qt_slot_errors", not errors)
(args.artifacts / "update_gui_results.json").write_text(json.dumps({"passed": len(checks), "checks": checks}, indent=2), encoding="utf-8")
