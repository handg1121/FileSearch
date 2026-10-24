"""검색 오케스트레이터와 본문 부분 검색. Qt에 의존하지 않아요."""

from contextlib import closing
from dataclasses import dataclass, field
import os
import sqlite3

from common.settings import get_body_cache_path
from searcher.body_cache import open_body_cache, read_sqlite_metadata, sync_body_cache
from searcher.body_extractors import EXTRACTOR_VERSION, SUPPORTED_EXTENSIONS
from searcher.filename_search import matches_name, normalize, parse_keywords
from searcher.metadata import (
    SearchCancelled, check_cancelled, compare_metadata, path_key, read_file_metadata,
)

from tagger.path_tracking import find_path_moves
from tagger.search import search_by_tag, search_keyword_tag


@dataclass(frozen=True)
class SearchRequest:
    root: str
    query: str = ""
    name_enabled: bool = True
    body_enabled: bool = False
    extensions: set | None = None
    since: float | None = None
    cache_path: str | None = None
    tag_id: int | None = None
    tag_enabled: bool = False


@dataclass
class SearchResult:
    hits: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    unsupported: int = 0
    refreshed: int = 0
    reused: int = 0
    deleted: int = 0
    cancelled: bool = False
    path_moves: list = field(default_factory=list)
    tag_name: str = ""
    missing: int = 0


def _extension(item):
    return os.path.splitext(item.name)[1][1:].lower()


def _excerpt(body, folded, folded_index, folded_length, should_stop):
    """casefold로 글자 수가 달라지는 경우에도 원문 위치를 찾아요(예: ß → ss)."""
    start, end = folded_index, folded_index + folded_length
    if len(body) != len(folded):
        offset = 0
        found = False
        for index, char in enumerate(body):
            if index % 16384 == 0:
                check_cancelled(should_stop)
            next_offset = offset + len(char.casefold())
            if not found and next_offset > folded_index:
                start = index
                found = True
            if found and next_offset >= folded_index + folded_length:
                end = index + 1
                break
            offset = next_offset
    left = max(0, start - 80)
    right = min(len(body), max(end + 160, left + 300))
    # 매우 긴 검색어도 결과 목록 전체를 지나치게 크게 만들지 않아요.
    right = min(right, left + 1000)
    return ("…" if left else "") + body[left:right] + ("…" if right < len(body) else "")


def search_keyword_body(connection, root, query, candidates, *,
                        on_progress=lambda *args: None, should_stop=lambda: False):
    """SQLite의 최신 정상 본문에서 문구가 포함된 파일 목록을 돌려줘요.

    공백을 포함한 입력 전체를 찾아요. %, _, *도 평범한 글자로 처리해요.
    본문은 한 번에 하나씩 읽으며, 모든 파일의 본문을 메모리에 쌓지 않아요.
    """
    needle = normalize(query).casefold()
    hits = []
    rows = connection.execute("""
        SELECT path_key, mtime_ns, size, body FROM body_cache
        WHERE root_key = ? AND status = 'ready' AND extractor_version = ?
    """, (path_key(root), EXTRACTOR_VERSION))
    done = 0
    try:
        for row in rows:
            check_cancelled(should_stop)
            item = candidates.get(row["path_key"])
            if item is None or (item.mtime_ns, item.size) != (row["mtime_ns"], row["size"]):
                continue
            body = row["body"]
            folded = body.casefold()
            index = folded.find(needle)
            if index >= 0:
                excerpt = _excerpt(body, folded, index, len(needle), should_stop) if needle else body[:300]
                hits.append(item.to_hit(root, excerpt))
            done += 1
            on_progress("저장된 본문 검색 중", done, len(candidates), item.path)
    finally:
        rows.close()
    return hits


def run(request, *, on_progress=lambda *args: None, should_stop=lambda: False):
    """검색 버튼의 동작을 총괄해요. 선택한 이름·본문·태그 결과를 OR로 합쳐요."""
    if request.tag_id is None and not any((request.name_enabled, request.body_enabled, request.tag_enabled)):
        raise ValueError("검색할 항목을 하나 이상 선택하세요.")
    result = SearchResult()
    cache_path = request.cache_path or get_body_cache_path()
    try:
        if request.tag_id is not None:
            tagged = search_by_tag(request.tag_id, cache_path, on_progress=on_progress, should_stop=should_stop)
            result.hits, result.errors = tagged.hits, tagged.errors
            result.tag_name, result.missing = tagged.name, tagged.missing
            return result
        snapshot = read_file_metadata(
            request.root, excluded_paths=[cache_path + suffix for suffix in ("", "-journal", "-wal", "-shm")],
            on_progress=on_progress, should_stop=should_stop,
        )
        result.errors.extend(snapshot.errors)
        on_progress("태그 경로 확인 중", 0, 0, snapshot.root)
        try:
            result.path_moves = find_path_moves(snapshot, cache_path, should_stop=should_stop)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
            result.errors.append(("태그 경로 확인", str(error)))
        candidates = {
            key: item for key, item in snapshot.files.items()
            if (not request.extensions or _extension(item) in request.extensions)
            and (request.since is None or item.mtime_ns / 1_000_000_000 >= request.since)
        }
        hits = {}
        if request.name_enabled:
            keywords = parse_keywords(request.query)
            for key, item in candidates.items():
                check_cancelled(should_stop)
                if matches_name(item.name, keywords):
                    hits[key] = item.to_hit(snapshot.root)
        if request.tag_enabled:
            tag_hits = search_keyword_tag(snapshot.root, request.query, candidates, cache_path,
                                          on_progress=on_progress, should_stop=should_stop)
            for hit in tag_hits:
                hits[path_key(hit.path)] = hit
        if request.body_enabled:
            supported = {key: item for key, item in candidates.items()
                         if _extension(item) in SUPPORTED_EXTENSIONS}
            result.unsupported = len(candidates) - len(supported)
            with closing(open_body_cache(cache_path)) as connection:
                cached = read_sqlite_metadata(connection, snapshot.root)
                changes = compare_metadata(snapshot, cached, extractor_version=EXTRACTOR_VERSION)
                # 경로 변경 확인을 보류한 파일의 기존 메타데이터는 결정 전까지 남겨요.
                pending = {path_key(move.old_path) for move in result.path_moves}
                changes.deleted = [item for item in changes.deleted if item.key not in pending]
                sync = sync_body_cache(connection, snapshot.root, changes, supported,
                                       on_progress=on_progress, should_stop=should_stop)
                result.errors.extend(sync.errors)
                result.refreshed, result.reused, result.deleted = sync.refreshed, sync.reused, sync.deleted
                body_hits = search_keyword_body(connection, snapshot.root, request.query, supported,
                                                on_progress=on_progress, should_stop=should_stop)
                # 이름·태그에도 해당하면 본문 발췌가 있는 결과를 유지하며 중복을 없애요.
                for hit in body_hits:
                    hits[path_key(hit.path)] = hit
        check_cancelled(should_stop)
        result.hits = list(hits.values())
    except SearchCancelled:
        result.cancelled = True
    return result
