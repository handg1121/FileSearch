"""SQLite 본문 캐시 읽기·동기화. 연결은 검색 작업 스레드에서 생성해요."""

from dataclasses import dataclass, field
import os
import sqlite3

from ocr import IMAGE_EXTENSIONS
from searcher.body_extractors import EXTRACTOR_VERSION, ExtractionError, extract_file_body
from searcher.metadata import (
    CachedMetadata, FileMetadata, SearchCancelled, check_cancelled, metadata_for_path,
    path_key, same_metadata,
)


def open_body_cache(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    connection = sqlite3.connect(path, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError("이 프로그램보다 새로운 버전의 본문 캐시예요.")
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS body_cache (
                    root_key TEXT NOT NULL,
                    path_key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    body TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'ready', 'error')),
                    extractor_version INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (root_key, path_key),
                    CHECK ((status = 'ready' AND body IS NOT NULL)
                        OR (status != 'ready' AND body IS NULL))
                )
            """)
            connection.execute("PRAGMA user_version = 1")
        return connection
    except Exception:
        connection.close()
        raise


def read_sqlite_metadata(connection, root):
    """현재 검색 폴더의 메타데이터만 읽어요. 큰 본문은 가져오지 않아요."""
    rows = connection.execute("""
        SELECT path_key, path, name, mtime_ns, size, status, extractor_version
        FROM body_cache WHERE root_key = ?
    """, (path_key(root),))
    return {row["path_key"]: CachedMetadata(
        FileMetadata(row["path"], row["name"], row["mtime_ns"], row["size"]),
        row["status"], row["extractor_version"],
    ) for row in rows}


def _store(connection, root, item, *, status, body=None, error=""):
    # 메타데이터와 본문을 한 트랜잭션으로 교체해 서로 다른 버전이 섞이지 않아요.
    with connection:
        connection.execute("""
            INSERT INTO body_cache
                (root_key, path_key, path, name, mtime_ns, size, body, status,
                 extractor_version, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_key, path_key) DO UPDATE SET
                path=excluded.path, name=excluded.name, mtime_ns=excluded.mtime_ns,
                size=excluded.size, body=excluded.body, status=excluded.status,
                extractor_version=excluded.extractor_version, error=excluded.error
        """, (path_key(root), item.key, item.path, item.name, item.mtime_ns,
              item.size, body, status, EXTRACTOR_VERSION, error))


@dataclass
class SyncResult:
    refreshed: int = 0
    reused: int = 0
    deleted: int = 0
    errors: list = field(default_factory=list)


def sync_body_cache(connection, root, changes, candidates, *,
                    on_progress=lambda *args: None, should_stop=lambda: False):
    """비교 결과를 적용해요. 실제 파일은 수정하거나 지우지 않아요.

    후보는 종류·날짜 조건을 통과한 지원 파일이에요. 삭제 판정은 전체 탐색 결과를 써요.
    취소 시 이미 완료한 캐시는 남고, pending/error 파일은 다음 검색에서 재시도해요.
    """
    result = SyncResult(reused=sum(item.key in candidates for item in changes.unchanged))
    check_cancelled(should_stop)
    with connection:
        for item in changes.deleted:
            check_cancelled(should_stop)
            connection.execute("DELETE FROM body_cache WHERE root_key = ? AND path_key = ?",
                               (path_key(root), item.key))
            result.deleted += 1
    pending = [item for item in changes.added + changes.modified + changes.retry
               if item.key in candidates]
    for index, item in enumerate(pending):
        check_cancelled(should_stop)
        phase = "이미지 글자 인식 중" if os.path.splitext(item.name)[1][1:].lower() in IMAGE_EXTENSIONS else "본문 읽는 중"
        on_progress(phase, index, len(pending), item.path)
        # 이전 본문을 먼저 무효화해 읽기 실패/중단 후 옛 내용이 검색되지 않게 해요.
        _store(connection, root, item, status="pending")
        try:
            before = metadata_for_path(item.path)
            if not same_metadata(item, before):
                raise ExtractionError("확인 중 파일이 변경됐어요. 다음 검색에서 다시 읽어요.")
            body = extract_file_body(item.path, should_stop=should_stop)
            after = metadata_for_path(item.path)
            if not same_metadata(before, after):
                raise ExtractionError("본문을 읽는 동안 파일이 변경됐어요. 다음 검색에서 다시 읽어요.")
            check_cancelled(should_stop)
        except SearchCancelled:
            raise
        except Exception as error:
            # 파일 하나의 오류는 나머지 검색을 막지 않아요. DB 쓰기 오류는 밖으로 전달해요.
            message = str(error) or type(error).__name__
            _store(connection, root, item, status="error", error=message)
            result.errors.append((item.path, message))
        else:
            _store(connection, root, after, status="ready", body=body)
            result.refreshed += 1
        on_progress(phase, index + 1, len(pending), item.path)
    return result
