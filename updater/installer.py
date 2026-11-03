"""Register a bundled base version, used by the portable bootstrap and legacy installer."""
import json

from updater import config
from updater.protocol import UpdateError, version_tuple


def register_install(layout):
    """Caller owns both installation locks. Never read or change the user's data."""
    candidate = layout.version_dir(config.VERSION)
    expected = {'version': config.VERSION, 'data_schema': config.DATA_SCHEMA,
                'launcher_protocol': config.LAUNCHER_PROTOCOL}
    if (not (candidate / 'FileSearchApp.exe').is_file()
            or json.loads((candidate / 'release.json').read_bytes()) != expected):
        raise UpdateError('프로그램 파일이 완전하지 않아요. FileSearch.exe를 다시 받아 주세요.')
    if not layout.state_path.exists():
        # A new installation's bundled version is its explicit base version.
        state = layout.read_state()
    else:
        state = layout.read_state()
        current = state['active']
        if version_tuple(current) > version_tuple(config.VERSION):
            # Re-running an older installer must not undo a successful auto-update.
            if not (layout.version_dir(current) / 'FileSearchApp.exe').is_file():
                raise UpdateError('설치된 최신 버전 파일을 찾을 수 없어요.')
            layout.save_state(dict(state, installed=list(dict.fromkeys(
                state.get('installed', [current]) + [config.VERSION]))))
            return
        previous = current if current != config.VERSION else state.get('previous')
        if previous and not (layout.version_dir(previous) / 'FileSearchApp.exe').is_file():
            previous = None
        state = dict(state, active=config.VERSION, previous=previous,
                     trial=config.VERSION if previous else None, attempting=False,
                     failed=[version for version in state['failed'] if version != config.VERSION],
                     installed=list(dict.fromkeys(state.get('installed', [current]) + [config.VERSION])))
    layout.save_state(state)
