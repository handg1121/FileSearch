"""Atomic update state and version folders; never changes the user's file collection."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from updater import config
from updater.protocol import MAX_MANIFEST, UpdateError, json_bytes, verify_manifest, verify_archive, unpack, version_tuple


def atomic_write(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_owned_tree(path, parent):
    """No traversal, junctions, or caller-supplied root directories may be removed."""
    path, parent = Path(path), Path(parent).resolve(strict=True)
    if path.is_symlink() or path.is_junction() or path.resolve().parent != parent:
        raise UpdateError("업데이트 정리 경로가 올바르지 않아요.")
    if path.exists():
        shutil.rmtree(path)


class Layout:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.versions = self.directory("versions")
        self.work = self.directory(".updates")
        self.downloads = self.directory(".updates", "downloads")
        self.staging = self.directory(".updates", "staging")
        self.state_path = self.work / "state.json"
        self.pending_path = self.work / "pending.json"

    def directory(self, *parts):
        path = self.root
        for part in parts:
            path = path / part
            if path.is_symlink() or path.is_junction():
                raise UpdateError("업데이트 폴더에 연결 경로를 사용할 수 없어요.")
            path.mkdir(exist_ok=True)
        return path

    def version_dir(self, version):
        version_tuple(version)
        path = self.versions / version
        if path.is_symlink() or path.is_junction() or path.resolve().parent != self.versions:
            raise UpdateError("프로그램 경로가 올바르지 않아요.")
        return path

    def read_state(self):
        if not self.state_path.exists():
            return {"active": config.VERSION, "previous": None, "trial": None, "attempting": False,
                    "failed": [], "installed": [config.VERSION]}
        if self.state_path.stat().st_size > 65536:
            raise UpdateError("업데이트 상태를 읽을 수 없어요.")
        state = json.loads(self.state_path.read_bytes())
        for name in ("active", "previous", "trial"):
            if state.get(name) is not None:
                version_tuple(state[name])
        version_tuple(state["active"])
        if not isinstance(state["failed"], list) or len(state["failed"]) > 100:
            raise UpdateError("업데이트 기록이 올바르지 않아요.")
        for version in state["failed"]:
            version_tuple(version)
        for version in state.get("installed", []):
            version_tuple(version)
        if state["trial"] and (state["trial"] != state["active"] or not state["previous"]):
            raise UpdateError("업데이트 복구 정보가 없어요.")
        return state

    def save_state(self, state):
        atomic_write(self.state_path, json_bytes(state))

    def archive_path(self, release):
        return self.downloads / (release["version"] + "-" + release["sha256"] + ".zip")

    def fail_trial(self, state):
        if not state["trial"]:
            return state
        failed = state["trial"]
        previous = self.version_dir(state["previous"])
        if not (previous / "FileSearchApp.exe").is_file():
            raise UpdateError("이전 버전 파일을 찾을 수 없어요.")
        state = dict(state, active=state["previous"], trial=None, previous=None, attempting=False,
                     failed=(state["failed"] + [failed])[-100:])
        self.save_state(state)
        return state

    def activate_pending(self, state, public_key=None):
        """Call only while the launcher owns its lock and the application has exited."""
        if not self.pending_path.exists():
            return state
        if self.pending_path.stat().st_size > MAX_MANIFEST:
            raise UpdateError("업데이트 정보가 너무 커요.")
        raw = self.pending_path.read_bytes()
        release = verify_manifest(raw, public_key)
        if (version_tuple(release["version"]) <= version_tuple(state["active"])
                or release["version"] in state["failed"]):
            self.pending_path.unlink()
            return state
        archive = self.archive_path(release)
        verify_archive(archive, release)
        destination = self.version_dir(release["version"])
        staging = Path(tempfile.mkdtemp(prefix="unpack-", dir=self.staging))
        try:
            unpack(archive, staging, release)
            # A power loss after extraction but before state commit may leave this version.
            # Recreate it from the signed archive; never touch the active/previous version.
            if destination.exists():
                if release["version"] in (state["active"], state["previous"]):
                    raise UpdateError("사용 중인 버전은 교체할 수 없어요.")
                remove_owned_tree(destination, self.versions)
            os.replace(staging, destination)
            installed = list(dict.fromkeys(state.get("installed", [state["active"]]) + [release["version"]]))
            new_state = dict(state, previous=state["active"], active=release["version"], trial=release["version"],
                             attempting=False, installed=installed)
            self.save_state(new_state)
            try:
                self.pending_path.unlink(missing_ok=True)
            except OSError:
                pass  # State is committed; obsolete pending metadata is harmless on the next run.
            return new_state
        finally:
            if staging.exists():
                remove_owned_tree(staging, self.staging)

    def cleanup(self, state):
        """Keep current + previous versions. Only remove versions recorded by this updater."""
        keep = {state["active"], state["previous"], state["trial"]}
        retained = []
        for version in state.get("installed", []):
            path = self.version_dir(version)
            if version in keep:
                retained.append(version)
                continue
            try:
                remove_owned_tree(path, self.versions)
            except OSError:
                retained.append(version)
        result = dict(state, installed=retained)
        self.save_state(result)
        # The installed executable is already verified and acknowledged. Reclaim its ZIP.
        for path in self.downloads.glob(state["active"] + "-*.zip"):
            if path.is_file() and not path.is_symlink() and path.resolve().parent == self.downloads:
                try:
                    path.unlink()
                except OSError:
                    pass
        return result


@contextmanager
def install_lock(layout, name="running.lock"):
    """Hold one OS file lock for the entire launcher + app session; auto-released on crash."""
    import msvcrt
    path = layout.work / name
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise UpdateError("파일 검색기가 이미 실행 중이에요.") from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
