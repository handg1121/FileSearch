"""파일 모으기 핵심 로직 (화면 코드와 분리, PySide6를 쓰지 않음)

흐름
  1. 훑기        scan_files           찾을 위치에서 선택한 유형의 파일 목록을 만든다
  2. 저장 경로    make_target_path     원래 폴더 구조를 살린 저장 경로를 정한다
                 resolve_duplicate    같은 이름이 있으면 _중복1, _중복2 ... 를 붙인다
  3. 공간 계산    check_space          옮기기·복사에 필요한 공간과 남는 공간을 계산한다
  4. 파일 하나    copy_file_atomic     임시 이름(.part)으로 복사한 뒤 진짜 이름으로 바꾼다
                 move_file            같은 드라이브면 이름 바꾸기, 아니면 복사 후 원본 삭제
  5. 기록·복구    write_journal        작업 직전·직후를 기록 파일에 남긴다
                 recover_unfinished   중간에 꺼졌던 작업을 정리한다
  6. 전체 실행    run_collect          위 단계를 묶어 목록 전체를 옮기거나 복사한다
"""
import ctypes
import functools
import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import datetime

MODE_MOVE = "move"
MODE_COPY = "copy"
PART_SUFFIX = ".part"
JOURNAL_NAME = "_모으기_기록.jsonl"
DUPLICATE_MARK = "_중복"
SAFETY_MARGIN = 1024 * 1024 * 1024
EXCLUDED_DIR_NAMES = {
    "program files", "program files (x86)",
    "$recycle.bin", "system volume information",
}
EXCLUDED_DIR_ENV_VARS = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")
HIDDEN_OR_SYSTEM = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM


@dataclass
class FileItem:
    src: str
    size: int
    target: str


@dataclass
class SpaceCheck:
    needed: int
    free: int
    remaining: int
    enough: bool


@dataclass
class CollectResult:
    mode: str
    total: int
    done: int = 0
    failed: list = field(default_factory=list)
    stopped: bool = False
    recovered: int = 0


def scan_files(sources, extensions, target_dir, include_subfolders=True,
               on_folder=None, should_stop=None):
    """찾을 위치들에서 선택한 확장자의 파일을 모두 찾아 FileItem 목록으로 돌려준다.

on_folder(폴더, 지금까지 찾은 개수): 폴더 하나를 볼 때마다 불림 (진행 표시용)
should_stop(): True를 돌려주면 그때까지 찾은 목록만 돌려주고 멈춤
"""
    wanted = set()
    for ext in extensions:
        wanted.add(ext.lower())
    excluded = build_excluded_dirs(target_dir)
    items = []
    seen = set()
    for source in sources:
        root = os.path.abspath(source)
        if is_inside_any(root, excluded):
            continue
        folders = [root]
        while folders:
            if should_stop and should_stop():
                return items
            folder = folders.pop()
            if on_folder:
                on_folder(folder, len(items))
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if include_subfolders and should_enter_dir(entry, excluded):
                            folders.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and is_wanted_file(entry, wanted):
                        key = os.path.normcase(entry.path)
                        if key in seen:
                            continue
                        seen.add(key)
                        size = entry.stat(follow_symlinks=False).st_size
                        items.append(FileItem(entry.path, size, make_target_path(entry.path, target_dir)))
                except OSError:
                    continue
    return items


def build_excluded_dirs(target_dir):
    '들어가지 않을 폴더의 전체 경로 목록 (저장 위치 + 윈도우·프로그램 폴더)'
    paths = [target_dir]
    for name in EXCLUDED_DIR_ENV_VARS:
        value = os.environ.get(name)
        if value:
            paths.append(value)
    excluded = []
    for path in paths:
        excluded.append(os.path.normcase(os.path.abspath(path)))
    return excluded


def is_inside_any(path, folders):
    path = os.path.normcase(path)
    for folder in folders:
        if path == folder or path.startswith(folder.rstrip("\\") + "\\"):
            return True
    return False


def should_enter_dir(entry, excluded):
    '숨김·시스템 폴더(AppData 등), 바로가기 폴더, 제외 폴더는 들어가지 않음'
    if entry.is_junction() or entry.is_symlink():
        return False
    if entry.name.lower() in EXCLUDED_DIR_NAMES:
        return False
    if entry.stat(follow_symlinks=False).st_file_attributes & HIDDEN_OR_SYSTEM:
        return False
    return not is_inside_any(entry.path, excluded)


def is_wanted_file(entry, wanted):
    '선택한 확장자이고, 오피스 임시파일(~$)이나 숨김·시스템 파일이 아닌 파일'
    if entry.name.startswith("~$"):
        return False
    ext = os.path.splitext(entry.name)[1][1:].lower()
    if ext not in wanted:
        return False
    return not entry.stat(follow_symlinks=False).st_file_attributes & HIDDEN_OR_SYSTEM


def make_target_path(src, target_dir):
    '원래 구조를 살린 저장 경로. E:\\자료\\보고서.hwp → 저장위치\\E_업무USB\\자료\\보고서.hwp'
    drive, rest = os.path.splitdrive(os.path.abspath(src))
    return os.path.join(target_dir, drive_folder_name(drive), rest.lstrip("\\"))


@functools.lru_cache(maxsize=None)
def drive_folder_name(drive):
    '드라이브 문자 + 볼륨 이름. USB는 꽂을 때마다 문자가 바뀔 수 있어 이름을 같이 씀'
    if drive.startswith("\\\\"):
        return drive.strip("\\").replace("\\", "_")
    letter = drive.rstrip(":")
    label = get_volume_label(drive)
    return f"{letter}_{label}" if label else letter


def get_volume_label(drive):
    buffer = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        drive + "\\", buffer, len(buffer), None, None, None, None, 0
    )
    return buffer.value if ok else ""


def resolve_duplicate(path):
    '같은 이름(또는 만들고 있는 임시 파일)이 있으면 보고서_중복1.hwp, 보고서_중복2.hwp ...'
    if not exists_or_in_progress(path):
        return path
    stem, ext = os.path.splitext(path)
    number = 1
    while True:
        candidate = f"{stem}{DUPLICATE_MARK}{number}{ext}"
        if not exists_or_in_progress(candidate):
            return candidate
        number += 1


def exists_or_in_progress(path):
    return os.path.exists(path) or os.path.exists(path + PART_SUFFIX)


def check_space(items, target_dir, mode):
    '복사는 전체 크기가, 옮기기는 다른 드라이브에서 오는 파일 크기만 새로 필요하다'
    target_drive = drive_of(target_dir)
    needed = 0
    for item in items:
        if mode == MODE_COPY or drive_of(item.src) != target_drive:
            needed += item.size
    free = shutil.disk_usage(target_drive + "\\").free
    remaining = free - needed
    return SpaceCheck(needed, free, remaining, remaining >= SAFETY_MARGIN)


def drive_of(path):
    return os.path.splitdrive(os.path.abspath(path))[0].upper()


class SourceKeptError(OSError):
    """사본은 저장했지만 원본을 지우지 못함"""


def copy_file_atomic(src, dst):
    """임시 이름으로 복사 → 디스크에 기록 확인 → 크기 확인 → 진짜 이름으로 바꾸기.
중간에 멈춰도 진짜 이름으로는 완성된 파일만 남는다."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + PART_SUFFIX
    try:
        shutil.copy2(src, part)
        with open(part, "rb+") as f:
            os.fsync(f.fileno())
        if os.path.getsize(part) != os.path.getsize(src):
            raise OSError("복사한 파일 크기가 원본과 다름")
        os.rename(part, dst)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise


def move_file(src, dst):
    if drive_of(src) == drive_of(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
        return
    copy_file_atomic(src, dst)
    try:
        os.remove(src)
    except OSError as error:
        raise SourceKeptError(f"사본은 저장했지만 원본을 지우지 못함 ({describe_error(error)})") from error


def describe_error(error):
    if isinstance(error, SourceKeptError):
        return str(error)
    if isinstance(error, PermissionError):
        return "권한이 없거나 다른 프로그램에서 열려 있음"
    if isinstance(error, FileNotFoundError):
        return "파일을 찾을 수 없음 (옮겨졌거나 지워짐)"
    return str(error)


def journal_path(target_dir):
    return os.path.join(target_dir, JOURNAL_NAME)


def write_journal(journal, mode, src, dst, state, reason=""):
    '한 줄씩 기록하고 바로 디스크에 내려씀. state: start / done / failed'
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "src": src,
        "dst": dst,
        "state": state,
    }
    if reason:
        record["reason"] = reason
    journal.write(json.dumps(record, ensure_ascii=False) + "\n")
    journal.flush()
    os.fsync(journal.fileno())


def recover_unfinished(target_dir):
    'start만 있고 done/failed가 없는 작업(중간에 꺼진 작업)을 정리하고 그 수를 돌려준다'
    path = journal_path(target_dir)
    if not os.path.exists(path):
        return 0
    last_records = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            last_records[record["dst"]] = record
    unfinished = []
    for record in last_records.values():
        if record["state"] == "start":
            unfinished.append(record)
    if not unfinished:
        return 0
    with open(path, "a", encoding="utf-8") as journal:
        for record in unfinished:
            state, reason = finish_interrupted(record)
            write_journal(journal, record["mode"], record["src"], record["dst"], state, reason)
    return len(unfinished)


def finish_interrupted(record):
    '중단된 작업 하나를 정리. 사본이 완성됐으면 마무리하고, 아니면 원본을 그대로 둔다'
    src, dst = record["src"], record["dst"]
    try:
        if os.path.exists(dst + PART_SUFFIX):
            os.remove(dst + PART_SUFFIX)
        if not os.path.exists(dst):
            return "failed", "중단됨 (원본은 그대로 있음)"
        if record["mode"] == MODE_MOVE and os.path.exists(src):
            if os.path.getsize(src) != os.path.getsize(dst):
                return "failed", "중단됨 (원본과 사본이 모두 남아 있음)"
            os.remove(src)
        return "done", "중단 후 마무리함"
    except OSError as error:
        return "failed", f"중단된 작업 정리 실패 ({describe_error(error)})"


def run_collect(items, target_dir, mode, on_progress=None, should_stop=None):
    """목록 전체를 옮기거나 복사한다.

on_progress(처리한 개수, 전체 개수, 지금 파일): 파일 하나를 끝낼 때마다 불림
should_stop(): True면 지금 파일까지만 끝내고 멈춤 (파일이 반쯤 남는 일은 없음)
"""
    os.makedirs(target_dir, exist_ok=True)
    result = CollectResult(mode=mode, total=len(items))
    result.recovered = recover_unfinished(target_dir)
    with open(journal_path(target_dir), "a", encoding="utf-8") as journal:
        for index, item in enumerate(items):
            if should_stop and should_stop():
                result.stopped = True
                break
            dst = resolve_duplicate(item.target)
            write_journal(journal, mode, item.src, dst, "start")
            try:
                if mode == MODE_MOVE:
                    move_file(item.src, dst)
                else:
                    copy_file_atomic(item.src, dst)
                write_journal(journal, mode, item.src, dst, "done")
                result.done += 1
            except OSError as error:
                reason = describe_error(error)
                write_journal(journal, mode, item.src, dst, "failed", reason)
                result.failed.append((item.src, reason))
            if on_progress:
                on_progress(index + 1, len(items), item.src)
    return result
