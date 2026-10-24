"""파일 상태 수집과 캐시 비교. 이 모듈은 본문을 읽거나 DB를 변경하지 않아요."""

from dataclasses import dataclass, field
import os
import stat

from searcher.filename_search import SearchHit, is_work_file, normalize


class SearchCancelled(Exception):
    """사용자가 검색 중단을 요청했어요."""


def check_cancelled(should_stop):
    if should_stop():
        raise SearchCancelled()


def path_key(path):
    """Windows의 경로 대소문자를 통일하되 원본 표시 경로는 별도로 보관해요."""
    return os.path.normcase(os.path.abspath(path))


@dataclass(frozen=True)
class FileMetadata:
    path: str
    name: str
    mtime_ns: int
    size: int

    @property
    def key(self):
        return path_key(self.path)

    def to_hit(self, root, excerpt=""):
        folder = os.path.relpath(os.path.dirname(self.path), root)
        return SearchHit(self.path, normalize(self.name), "" if folder == "." else folder,
                         self.size, self.mtime_ns / 1_000_000_000, excerpt)


def metadata_for_path(path):
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("일반 파일이 아니거나 확인 중 파일 종류가 바뀌었어요.")
    return FileMetadata(os.path.abspath(path), os.path.basename(path), info.st_mtime_ns, info.st_size)


@dataclass
class FileSnapshot:
    root: str
    files: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def complete(self):
        return not self.errors


@dataclass(frozen=True)
class CachedMetadata:
    file: FileMetadata
    status: str
    extractor_version: int


@dataclass
class MetadataChanges:
    added: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    retry: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    deleted: list = field(default_factory=list)


def same_metadata(a, b):
    return (a.mtime_ns, a.size) == (b.mtime_ns, b.size)


def read_file_metadata(root, *, excluded_paths=(), on_progress=lambda *args: None,
                       should_stop=lambda: False):
    """하위 폴더까지 메타데이터만 수집해요. 필터는 삭제 판정 뒤 별도로 적용해요.

    탐색/조회 실패를 숨기지 않아요. 하나라도 실패하면 이번 탐색으로 삭제를 확정하지 않아요.
    링크는 따라가지 않으며, 작업 중인 .part 및 Office 임시 파일은 제외해요.
    """
    root = os.path.abspath(root)
    snapshot = FileSnapshot(root)
    excluded = {path_key(path) for path in excluded_paths}
    folders = [root]
    while folders:
        check_cancelled(should_stop)
        folder = folders.pop()
        on_progress("파일 확인 중", len(snapshot.files), 0, folder)
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    check_cancelled(should_stop)
                    try:
                        if entry.is_symlink() or entry.is_junction():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            folders.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if (path_key(entry.path) in excluded or is_work_file(entry.name)
                                    or entry.name.startswith("~$")):
                                continue
                            stat = entry.stat(follow_symlinks=False)
                            item = FileMetadata(entry.path, entry.name, stat.st_mtime_ns, stat.st_size)
                            snapshot.files[item.key] = item
                    except OSError as error:
                        snapshot.errors.append((entry.path, str(error)))
        except OSError as error:
            snapshot.errors.append((folder, str(error)))
    return snapshot


def compare_metadata(snapshot, cached, *, extractor_version=1):
    """신규/수정/재시도/유지/삭제로 분류만 해요. 파일이나 DB에 쓰지 않아요."""
    changes = MetadataChanges()
    for key, item in snapshot.files.items():
        old = cached.get(key)
        if old is None:
            changes.added.append(item)
        elif not same_metadata(item, old.file):
            changes.modified.append(item)
        elif old.status != "ready" or old.extractor_version != extractor_version:
            changes.retry.append(item)
        else:
            changes.unchanged.append(item)
    if snapshot.complete:
        changes.deleted = [old.file for key, old in cached.items() if key not in snapshot.files]
    return changes
