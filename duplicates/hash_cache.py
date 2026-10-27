"""SQLite에 파일 해시를 저장해 다음 중복 찾기에서 다시 써요.

경로(폴더+파일명)·크기·수정 시각이 저장할 때와 모두 같을 때만 저장된 해시를 써요.
이름이 바뀌면 다른 경로이므로 새로 읽어요. 본문 캐시와 같은 SQLite 파일에 표만 따로 둬요.
지우기 직전에는 이 캐시를 쓰지 않고 파일을 다시 읽어요(remover.py).
"""

import os
import sqlite3

from searcher.metadata import path_key


def open_hash_cache(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    connection = sqlite3.connect(path, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    root_key TEXT NOT NULL,
                    path_key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    digest TEXT NOT NULL,
                    PRIMARY KEY (root_key, path_key)
                )
            """)
        return connection
    except Exception:
        connection.close()
        raise


def read_hashes(connection, root):
    '저장 위치 하나의 기록을 {path_key: (크기, 수정 시각, 해시)}로 읽어요.'
    rows = connection.execute(
        "SELECT path_key, size, mtime_ns, digest FROM file_hashes WHERE root_key = ?", (path_key(root),))
    cached = {}
    for row in rows:
        cached[row["path_key"]] = (row["size"], row["mtime_ns"], row["digest"])
    return cached


def cached_digest(cached, item):
    '크기와 수정 시각이 저장할 때와 같으면 저장된 해시를, 아니면 None을 돌려줘요.'
    saved = cached.get(item.key)
    if saved is None:
        return None
    size, mtime_ns, digest = saved
    if size != item.size or mtime_ns != item.mtime_ns:
        return None
    return digest


def store_hash(connection, root, item, digest):
    with connection:
        connection.execute("""
            INSERT INTO file_hashes(root_key, path_key, path, size, mtime_ns, digest)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_key, path_key) DO UPDATE SET
                path=excluded.path, size=excluded.size, mtime_ns=excluded.mtime_ns, digest=excluded.digest
        """, (path_key(root), item.key, item.path, item.size, item.mtime_ns, digest))


def forget_missing(connection, root, cached, present_keys):
    """이번 탐색에 없는 경로의 기록을 지워요. 탐색이 끝까지 성공했을 때만 불러요.

    휴지통으로 보낸 파일의 기록도 다음 찾기에서 여기서 정리돼요. 휴지통에서 되살린 파일은
    크기·수정 시각·내용이 그대로라 그 전에 다시 찾아도 저장된 해시가 맞아요.
    """
    removed = 0
    with connection:
        for key in cached:
            if key not in present_keys:
                removed += connection.execute(
                    "DELETE FROM file_hashes WHERE root_key = ? AND path_key = ?", (path_key(root), key)).rowcount
    return removed
