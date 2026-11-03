"""Stable launcher: a failed first startup switches back to the previous version."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from updater.protocol import UpdateError
from updater.storage import Layout, install_lock

STARTUP_TIMEOUT = 60


def start_application(layout, state, ack, token, notice="", extra_args=()):
    app_dir = layout.version_dir(state["active"])
    exe = app_dir / "FileSearchApp.exe"
    if not exe.is_file():
        raise UpdateError("프로그램 파일을 찾을 수 없어요. 설치 파일을 다시 받아 주세요.")
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("FILESEARCH_UPDATE_"):
            environment.pop(key)
    environment.update(FILESEARCH_INSTALL_ROOT=str(layout.root), FILESEARCH_UPDATE_ACK=str(ack),
                       FILESEARCH_UPDATE_TOKEN=token, FILESEARCH_UPDATE_NOTICE=notice,
                       PYINSTALLER_RESET_ENVIRONMENT="1")
    # The one-file launcher must not impose its temporary DLL search path on Qt.
    if os.name == "nt" and getattr(sys, "frozen", False):
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    return subprocess.Popen([str(exe), *extra_args], cwd=app_dir, env=environment,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def await_ready(process, ack, token, version, timeout=STARTUP_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ack.exists():
            try:
                if json.loads(ack.read_bytes()) == {"token": token, "version": version}:
                    return True
            except (ValueError, OSError):
                pass
        if process.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def run_session(layout, *, start=start_application, ready=await_ready, extra_args=()):
    state = layout.read_state()
    notice = ""
    if state["trial"] and state.get("attempting"):
        # A previous first start was interrupted before its health acknowledgement.
        state = layout.fail_trial(state)
        notice = "업데이트를 완료하지 못해 이전 버전으로 실행했어요."
    try:
        state = layout.activate_pending(state)
    except Exception as error:
        record_error(layout, error)
        notice = "업데이트를 적용하지 못했어요. 기존 버전으로 계속 사용할 수 있어요."
    while True:
        token = uuid.uuid4().hex
        ack = layout.work / ("ready-" + token + ".json")
        restart = layout.work / ("restart-" + token)
        process = None
        try:
            if state["trial"]:
                state = dict(state, attempting=True)
                layout.save_state(state)
            process = start(layout, state, ack, token, notice, extra_args)
            healthy = ready(process, ack, token, state["active"])
            if not healthy:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
                raise UpdateError("새 프로그램을 정상적으로 시작하지 못했어요.")
        except Exception as error:
            record_error(layout, error)
            if state["trial"]:
                state = layout.fail_trial(state)
                notice = "새 버전을 실행하지 못해 이전 버전으로 돌아왔어요."
                continue
            raise
        finally:
            ack.unlink(missing_ok=True)
        if state["trial"]:
            state = dict(state, trial=None, attempting=False)
            layout.save_state(state)
            try:
                state = layout.cleanup(state)
            except Exception as error:
                record_error(layout, error)
        process.wait()
        wants_restart = restart.exists()
        restart.unlink(missing_ok=True)
        notice = ""
        try:
            state = layout.activate_pending(state)
        except Exception as error:
            record_error(layout, error)
            notice = "업데이트를 적용하지 못했어요. 기존 버전으로 계속 사용할 수 있어요."
        if not wants_restart:
            return


def record_error(layout, error):
    try:
        (layout.work / "last-error.txt").write_text(f"{type(error).__name__}: {error}", encoding="utf-8")
    except OSError:
        pass


def main():
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(sys.argv[1])
    extra_args = ["--self-test"] if "--self-test" in sys.argv else []
    registering = "--register-install" in sys.argv
    try:
        layout = Layout(root)
        with install_lock(layout):
            # A launcher crash must not allow a second instance beside its orphaned app.
            with install_lock(layout, "app.lock"):
                if registering:
                    from updater.installer import register_install
                    register_install(layout)
                    return 0
            run_session(layout, extra_args=extra_args)
    except Exception as error:
        if "layout" in locals():
            record_error(layout, error)
        if "--self-test" not in sys.argv and not registering:
            message = str(error) if isinstance(error, UpdateError) else "프로그램을 시작하지 못했어요. 잠시 후 다시 실행해 주세요."
            ctypes.windll.user32.MessageBoxW(None, message, "파일 검색기", 0x10)
        return 1
    return 0
