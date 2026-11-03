"""Prepare the embedded app in a per-user cache, without an installer or registry writes."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from updater import config
from updater.installer import register_install
from updater.protocol import MAX_MANIFEST, UpdateError, unpack, verify_archive, version_tuple
from updater.storage import move_version_folder, remove_owned_tree


def bundled_release():
    bundle = Path(sys._MEIPASS) / 'payload'
    metadata = bundle / 'bundle.json'
    if metadata.stat().st_size > MAX_MANIFEST:
        raise UpdateError('실행 파일의 구성 정보가 올바르지 않아요. 다시 받아 주세요.')
    release = json.loads(metadata.read_bytes())
    if (release.get('version') != config.VERSION
            or release.get('data_schema') != config.DATA_SCHEMA
            or release.get('launcher_protocol') != config.LAUNCHER_PROTOCOL
            or type(release.get('development')) is not bool
            or type(release.get('size')) is not int or release['size'] <= 0
            or not isinstance(release.get('sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', release['sha256'])):
        raise UpdateError('실행 파일의 구성 정보가 올바르지 않아요. 다시 받아 주세요.')
    return bundle / 'app.zip', release


def runtime_root():
    _, release = bundled_release()
    local = os.environ.get('LOCALAPPDATA')
    if not local or not Path(local).is_absolute():
        raise UpdateError('Windows 사용자 캐시 폴더를 찾을 수 없어요.')
    path = Path(local).resolve(strict=True)
    # Developer builds must not silently reuse a different build of the same version.
    parts = ('FileSearch', 'Development', release['sha256']) if release['development'] else ('FileSearch', 'Runtime')
    for part in parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise UpdateError('프로그램 캐시 폴더에 연결 경로를 사용할 수 없어요.')
        path.mkdir(exist_ok=True)
    return path


def prepare_runtime(layout):
    """Caller owns both launcher/app locks; leave updated or rolled-back versions alone."""
    archive, release = bundled_release()
    state = layout.read_state() if layout.state_path.exists() else None
    if state:
        current = version_tuple(state['active'])
        bundled = version_tuple(release['version'])
        if current > bundled or release['version'] in state['failed']:
            return
        if current == bundled and (layout.version_dir(state['active']) / 'FileSearchApp.exe').is_file():
            return
    # The metadata and ZIP travel inside the same EXE. Network updates separately
    # require their Ed25519 signature, exactly as with the legacy folder launcher.
    verify_archive(archive, release)
    staging = Path(tempfile.mkdtemp(prefix='bootstrap-', dir=layout.staging))
    destination = layout.version_dir(release['version'])
    try:
        unpack(archive, staging, release)
        if destination.exists():
            remove_owned_tree(destination, layout.versions)
        move_version_folder(staging, destination)
        register_install(layout)
    finally:
        if staging.exists():
            remove_owned_tree(staging, layout.staging)
