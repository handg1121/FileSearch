"""End-to-end test of the actual frozen launcher/app using disposable installation copies."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater import config
from updater.protocol import json_bytes, verify_manifest
from updater.storage import Layout, atomic_write
from tools.release_key import load_key

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", type=Path, required=True)
args = parser.parse_args()
args.workspace.mkdir(parents=True)
install = args.workspace / "한글 설치 경로 & 공백"
shutil.copytree(ROOT / "dist" / f"FileSearch-{config.VERSION}", install)
layout = Layout(install)
profile = args.workspace / "profile"
(profile / "FileSearch").mkdir(parents=True)
sentinel = profile / "FileSearch/settings.json"
sentinel.write_text('{"save_dir":"D:\\\\never-scan-this"}')
before = sentinel.read_bytes()
environment = dict(os.environ, APPDATA=str(profile), QT_QPA_PLATFORM="offscreen")
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def launch():
    process = subprocess.run([str(install / "FileSearch.exe"), "--self-test"], cwd=install,
                             env=environment, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    check("frozen_process_exit", process.returncode == 0)
    check("user_profile_unchanged", sentinel.read_bytes() == before)


launch()
check("initial_launch", not layout.state_path.exists())
# Simulate an older managed installation, then install the real signed 0.2.0 payload.
old = "0.1.0"
os.replace(layout.version_dir(config.VERSION), layout.version_dir(old))
state = dict(layout.read_state(), active=old, installed=[old])
layout.save_state(state)
release_dir = ROOT / "dist/releases" / config.VERSION
raw = (release_dir / "update.json").read_bytes()
release = verify_manifest(raw)
shutil.copy2(release_dir / f"FileSearch-update-{config.VERSION}-win64.zip", layout.archive_path(release))
atomic_write(layout.pending_path, raw)
launch()
state = layout.read_state()
check("real_signed_update_activated", state["active"] == config.VERSION and state["trial"] is None)
check("previous_version_preserved", layout.version_dir(old).is_dir())

# A correctly signed release that cannot start must roll back without touching user data.
bad_version = "0.2.1"
bad_archive = args.workspace / "bad.zip"
with zipfile.ZipFile(bad_archive, "w") as archive:
    archive.writestr("FileSearchApp.exe", b"MZbroken executable")
    archive.writestr("_internal/lib.dll", b"placeholder")
    archive.writestr("release.json", json_bytes({"version": bad_version, "data_schema": 1, "launcher_protocol": 1}))
payload = json_bytes(dict(schema=1, version=bad_version, data_schema=1, launcher_protocol=1,
                         size=bad_archive.stat().st_size, sha256=hashlib.sha256(bad_archive.read_bytes()).hexdigest(),
                         url=f"https://github.com/{config.REPOSITORY}/releases/download/v{bad_version}/FileSearch-update-{bad_version}-win64.zip"))
bad_raw = json_bytes({"payload": base64.b64encode(payload).decode(),
                      "signature": base64.b64encode(load_key().sign(payload)).decode()})
bad_release = verify_manifest(bad_raw)
shutil.copy2(bad_archive, layout.archive_path(bad_release))
atomic_write(layout.pending_path, bad_raw)
launch()
state = layout.read_state()
check("bad_executable_rolled_back", state["active"] == config.VERSION and bad_version in state["failed"])

# Tampered signature is rejected by the frozen verifier, not just source tests.
envelope = json.loads(bad_raw)
envelope["signature"] = base64.b64encode(b"x" * 64).decode()
atomic_write(layout.pending_path, json_bytes(envelope))
launch()
check("tampered_manifest_keeps_working_version", layout.read_state()["active"] == config.VERSION)
check("verification_error_recorded", "UpdateError" in (layout.work / "last-error.txt").read_text(encoding="utf-8"))
layout.pending_path.unlink()

# Simulated power loss while a trial process was starting.
state = dict(layout.read_state(), active=bad_version, previous=config.VERSION, trial=bad_version, attempting=True)
layout.save_state(state)
launch()
check("interrupted_trial_recovers", layout.read_state()["active"] == config.VERSION)
(args.workspace / "frozen-results.json").write_text(json.dumps({"passed": len(checks), "checks": checks}, indent=2), encoding="utf-8")
print(json.dumps({"passed": len(checks), "workspace": str(args.workspace)}, ensure_ascii=False))
