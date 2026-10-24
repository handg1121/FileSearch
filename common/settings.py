r"""사용자 설정 저장·불러오기 (%APPDATA%\FileSearch\settings.json)

exe 옆이 아니라 사용자 폴더에 두는 이유: 프로그램을 Program Files처럼
쓰기 권한이 없는 곳에 두어도 설정은 저장되게 하려고
"""

import json
import os


DEFAULT_SAVE_DIR = "D:\\모은파일"

SETTINGS_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FileSearch", "settings.json")


def load_settings():
    """설정 파일이 없거나 깨져 있으면 빈 설정(= 모두 기본값)"""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def write_settings(settings):
    """임시 파일에 다 쓴 뒤 바꿔치기 → 쓰는 도중 꺼져도 설정 파일이 반쯤 깨지지 않음"""
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    temp_path = SETTINGS_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, SETTINGS_PATH)


def get_save_dir():
    return load_settings().get("save_dir") or DEFAULT_SAVE_DIR


def get_body_cache_path():
    return os.path.join(os.path.dirname(SETTINGS_PATH), "body_cache.sqlite3")


def set_save_dir(path):
    settings = load_settings()
    settings["save_dir"] = path
    write_settings(settings)
