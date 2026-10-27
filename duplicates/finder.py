"""저장 위치 아래에서 내용이 같은 파일을 찾아요. 파일을 고치거나 지우지 않아요.

크기가 같은 파일끼리만 SHA-256을 계산해요. 크기가 다르면 내용도 다르므로 읽지 않아요.
이름·경로·수정일은 비교하지 않아요. 빈 파일은 내용과 상관없이 모두 같게 보이므로 제외해요.
경로·크기·수정 시각이 그대로인 파일은 저장된 해시를 다시 써요(hash_cache.py).
"""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
import hashlib

from common.settings import get_body_cache_path
from duplicates.hash_cache import cached_digest, forget_missing, open_hash_cache, read_hashes, store_hash
from searcher.metadata import check_cancelled, metadata_for_path, path_key, read_file_metadata, same_metadata

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class DuplicateGroup:
    size: int
    digest: str
    files: tuple  # FileMetadata, 경로 순

    @property
    def wasted(self):
        '하나만 남기면 확보되는 바이트 수'
        return self.size * (len(self.files) - 1)


@dataclass
class DuplicateResult:
    root: str
    groups: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    scanned: int = 0
    hashed: int = 0
    reused: int = 0

    @property
    def wasted(self):
        total = 0
        for group in self.groups:
            total += group.wasted
        return total


def file_digest(path, should_stop=lambda: False):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while True:
            check_cancelled(should_stop)
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_digest(item, should_stop=lambda: False):
    '읽기 전후로 크기·수정 시각을 확인해, 읽는 동안 바뀐 파일의 해시를 쓰지 않아요.'
    before = metadata_for_path(item.path)
    if not same_metadata(item, before):
        raise OSError("확인 중 파일이 변경됐어요. 다음에 다시 찾아 주세요.")
    digest = file_digest(item.path, should_stop)
    after = metadata_for_path(item.path)
    if not same_metadata(before, after):
        raise OSError("읽는 동안 파일이 변경됐어요. 다음에 다시 찾아 주세요.")
    return digest


def find_duplicates(root, *, cache_path=None, on_progress=lambda *args: None, should_stop=lambda: False):
    cache_path = cache_path or get_body_cache_path()
    snapshot = read_file_metadata(
        root, excluded_paths=[cache_path + suffix for suffix in ("", "-journal", "-wal", "-shm")],
        on_progress=on_progress, should_stop=should_stop,
    )
    result = DuplicateResult(snapshot.root, errors=list(snapshot.errors), scanned=len(snapshot.files))

    # 1단계: 크기별로 묶어요. 혼자인 크기는 비교할 상대가 없어요.
    by_size = defaultdict(list)
    for item in snapshot.files.values():
        if item.size > 0:
            by_size[item.size].append(item)
    candidates = []
    for items in by_size.values():
        if len(items) > 1:
            candidates.extend(items)

    # 2단계: 크기가 같은 파일만 해시를 비교해요. 바뀌지 않은 파일은 저장된 해시를 써요.
    by_digest = defaultdict(list)
    with closing(open_hash_cache(cache_path)) as connection:
        cached = read_hashes(connection, snapshot.root)
        # 탐색이 중간에 실패했으면 못 본 파일을 사라진 것으로 판단하지 않아요.
        if snapshot.complete:
            forget_missing(connection, snapshot.root, cached, snapshot.files.keys())
        for done, item in enumerate(candidates):
            on_progress("내용 비교 중", done, len(candidates), item.path)
            digest = cached_digest(cached, item)
            if digest is not None:
                result.reused += 1
            else:
                try:
                    digest = read_digest(item, should_stop)
                except OSError as error:
                    result.errors.append((item.path, str(error)))
                    continue
                store_hash(connection, snapshot.root, item, digest)
                result.hashed += 1
            by_digest[(item.size, digest)].append(item)
    on_progress("내용 비교 중", len(candidates), len(candidates), "")

    for (size, digest), items in by_digest.items():
        if len(items) > 1:
            items.sort(key=lambda item: path_key(item.path))
            result.groups.append(DuplicateGroup(size, digest, tuple(items)))
    # 확보할 공간이 큰 묶음부터 보여 줘요.
    result.groups.sort(key=lambda group: (-group.wasted, path_key(group.files[0].path)))
    return result
