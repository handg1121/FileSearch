"""SQLite 태그 저장소. 본문 캐시와 연결을 공유하거나 캐시 행에 종속되지 않아요."""

from contextlib import contextmanager
from dataclasses import dataclass
import os
import sqlite3
import unicodedata

from common.settings import get_body_cache_path
from tagger.colors import DEFAULT_TAG_COLOR, normalize_color


@dataclass(frozen=True)
class Tag:
    id: int
    name: str
    file_count: int = 0
    color: str = DEFAULT_TAG_COLOR


def normalize_name(name):
    name = unicodedata.normalize("NFC", name).strip()
    if not name:
        raise ValueError("태그 이름을 입력해 주세요.")
    if len(name) > 64:
        raise ValueError("태그 이름은 64자까지 입력할 수 있어요.")
    if "," in name or any(unicodedata.category(char).startswith("C") for char in name):
        raise ValueError("태그 이름에는 쉼표나 제어 문자를 넣을 수 없어요.")
    return name


def _paths(paths):
    result = {}
    for path in paths:
        if not os.fspath(path).strip():
            raise ValueError("파일 경로가 비어 있어요.")
        absolute = os.path.abspath(path)
        result[os.path.normcase(absolute)] = absolute
    return result


def _chunks(values):
    values = list(values)
    for start in range(0, len(values), 300):
        yield values[start:start + 300]


def _marks(values):
    return ",".join("?" for _ in values)


@contextmanager
def _connect(db_path):
    path = os.path.abspath(db_path or get_body_cache_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE,
                    color TEXT NOT NULL DEFAULT '#ef4444'
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS file_tags (
                    path_key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (path_key, tag_id)
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS file_tags_tag_id ON file_tags(tag_id)")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tags)")}
        if "color" not in columns:
            with connection:
                connection.execute("ALTER TABLE tags ADD COLUMN color TEXT NOT NULL DEFAULT '#ef4444'")
        has_paths = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tracked_files'"
        ).fetchone()
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tracked_files (
                    path_key TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL
                )
            """)
            if not has_paths:
                old_paths = connection.execute("SELECT DISTINCT path FROM file_tags").fetchall()
                if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_cache'").fetchone():
                    old_paths += connection.execute("SELECT DISTINCT path FROM body_cache").fetchall()
                _remember_paths(connection, [row["path"] for row in old_paths])
        # user_version은 기존 본문 캐시가 관리해요. 태그 추가로 버전을 덮어쓰지 않아요.
        yield connection
    finally:
        connection.close()


def _remember_paths(connection, paths):
    connection.executemany("""
        INSERT INTO tracked_files(path_key, path, name) VALUES (?, ?, ?)
        ON CONFLICT(path_key) DO UPDATE SET path=excluded.path, name=excluded.name
    """, ((key, path, os.path.basename(path)) for key, path in _paths(paths).items()))


def _create(connection, name):
    key = name.casefold()
    connection.execute("INSERT INTO tags(name, name_key) VALUES (?, ?) ON CONFLICT(name_key) DO NOTHING",
                       (name, key))
    row = connection.execute("SELECT id, name, color FROM tags WHERE name_key = ?", (key,)).fetchone()
    return Tag(row["id"], row["name"], color=row["color"])


def create_tag(name, db_path=None):
    """태그를 만들고 반환해요. 공백·한글 표현·대소문자만 다른 이름은 재사용해요."""
    name = normalize_name(name)
    with _connect(db_path) as connection, connection:
        return _create(connection, name)


def delete_tag(tag_ids, db_path=None):
    """태그 정의와 모든 파일의 부착 관계를 삭제해요. 파일 자체는 건드리지 않아요."""
    ids = set(tag_ids)
    if not ids:
        return 0
    with _connect(db_path) as connection, connection:
        count = 0
        for chunk in _chunks(ids):
            count += connection.execute(f"DELETE FROM tags WHERE id IN ({_marks(chunk)})", chunk).rowcount
        return count


def show_tag(db_path=None, *, paths=None):
    """화면에 표시할 태그와 부착 파일 수를 반환해요. paths 지정 시 그 파일들의 태그만 읽어요."""
    keys = _paths(paths) if paths is not None else None
    if keys is not None and not keys:
        return []
    with _connect(db_path) as connection:
        if keys is None:
            rows = connection.execute("""
                SELECT t.id, t.name, t.color, COUNT(f.path_key) AS file_count FROM tags t
                LEFT JOIN file_tags f ON f.tag_id = t.id GROUP BY t.id
            """)
            tags = [Tag(row["id"], row["name"], row["file_count"], row["color"]) for row in rows]
        else:
            counts = {}
            for chunk in _chunks(keys):
                rows = connection.execute(f"""
                    SELECT t.id, t.name, t.color, COUNT(*) AS file_count FROM tags t
                    JOIN file_tags f ON f.tag_id = t.id
                    WHERE f.path_key IN ({_marks(chunk)}) GROUP BY t.id
                """, chunk)
                for row in rows:
                    old = counts.get(row["id"])
                    counts[row["id"]] = Tag(row["id"], row["name"],
                                               row["file_count"] + (old.file_count if old else 0), row["color"])
            tags = list(counts.values())
    return sorted(tags, key=lambda tag: (tag.name.casefold(), tag.id))


def read_file_tags(paths, db_path=None):
    """요청한 경로별 태그 이름을 한꺼번에 읽어요. 본문은 읽지 않아요."""
    paths = list(paths)
    keys = _paths(paths)
    names = {key: [] for key in keys}
    if keys:
        with _connect(db_path) as connection:
            for chunk in _chunks(keys):
                rows = connection.execute(f"""
                    SELECT f.path_key, t.name FROM file_tags f JOIN tags t ON t.id = f.tag_id
                    WHERE f.path_key IN ({_marks(chunk)}) ORDER BY t.name_key, t.id
                """, chunk)
                for row in rows:
                    names[row["path_key"]].append(row["name"])
    return {path: tuple(names[os.path.normcase(os.path.abspath(path))]) for path in paths}


def attach_tags(paths, names=(), tag_ids=(), db_path=None):
    """선택한 모든 파일에 태그를 부착하고 새 연결 수를 반환해요. 전체를 한 번에 저장해요."""
    files = _paths(paths)
    names = [normalize_name(name) for name in names]
    ids = set(tag_ids)
    if not files:
        raise ValueError("태그를 붙일 파일을 체크해 주세요.")
    if not names and not ids:
        raise ValueError("부착할 태그 이름을 입력해 주세요.")
    for path in files.values():
        if not os.path.isfile(path):
            raise ValueError(f"파일을 찾을 수 없어요. 다시 검색해 주세요: {path}")
    with _connect(db_path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        # 다른 창에서 삭제된 태그 ID를 조용히 무시하거나 다른 태그로 바꾸지 않아요.
        for chunk in _chunks(ids):
            found = connection.execute(f"SELECT COUNT(*) FROM tags WHERE id IN ({_marks(chunk)})", chunk).fetchone()[0]
            if found != len(chunk):
                raise ValueError("선택한 태그가 삭제됐어요. 태그 목록을 새로 확인해 주세요.")
        ids.update(_create(connection, name).id for name in names)
        _remember_paths(connection, files.values())
        count = 0
        for key, path in files.items():
            for tag_id in ids:
                count += connection.execute("""
                    INSERT INTO file_tags(path_key, path, tag_id) VALUES (?, ?, ?)
                    ON CONFLICT(path_key, tag_id) DO NOTHING
                """, (key, path, tag_id)).rowcount
        return count


def detach_tags(paths, tag_ids, db_path=None):
    """선택한 파일에서만 태그를 떼어요. 태그 정의와 다른 파일의 태그는 유지해요."""
    files, ids = _paths(paths), set(tag_ids)
    if not files or not ids:
        return 0
    with _connect(db_path) as connection, connection:
        count = 0
        for key in files:
            for chunk in _chunks(ids):
                count += connection.execute(
                    f"DELETE FROM file_tags WHERE path_key = ? AND tag_id IN ({_marks(chunk)})",
                    [key, *chunk],
                ).rowcount
        return count


def set_tag_color(tag_id, color, db_path=None):
    """태그 하나의 색만 저장해요. 연결된 파일과 태그 이름은 유지해요."""
    color = normalize_color(color)
    with _connect(db_path) as connection, connection:
        cursor = connection.execute("UPDATE tags SET color = ? WHERE id = ?", (color, tag_id))
        if cursor.rowcount != 1:
            raise ValueError("태그가 삭제됐어요. 목록을 다시 확인해 주세요.")


def read_tag_paths(tag_id, db_path=None):
    """태그 하나와 연결된 전체 파일 경로를 반환해요. 본문은 읽지 않아요."""
    with _connect(db_path) as connection:
        row = connection.execute("SELECT id, name, color FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row is None:
            raise ValueError("태그가 삭제됐어요. 목록을 다시 확인해 주세요.")
        paths = [item["path"] for item in connection.execute(
            "SELECT path FROM file_tags WHERE tag_id = ? ORDER BY path_key", (tag_id,))]
        return Tag(row["id"], row["name"], len(paths), row["color"]), paths


@dataclass(frozen=True)
class TagEditResult:
    tag: Tag
    changed_files: int
    source_retained: bool


def edit_tag(tag_id, new_name, paths, db_path=None, *, expected_name=None):
    """선택한 파일에서만 태그 이름을 바꿔요. 다른 태그와 파일 데이터는 유지해요.

    전부 선택하고 새 이름이면 기존 태그 ID와 색을 유지해 이름만 바꿔요.
    일부 선택이면 같은 색의 새 태그로 분리해요. 이미 있는 이름이면 그 태그로
    연결을 바꾸되 기존 색을 유지해요. 모든 변경은 한 트랜잭션으로 처리해요.
    """
    name = normalize_name(new_name)
    selected = set(_paths(paths))
    with _connect(db_path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        source = connection.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if source is None:
            raise ValueError("태그가 삭제됐어요. 창을 닫고 목록을 다시 확인해 주세요.")
        if expected_name is not None and source["name"] != expected_name:
            raise ValueError("태그 이름이 바뀌었어요. 창을 닫고 다시 수정해 주세요.")
        if source["name"] == name:
            raise ValueError("현재 태그와 다른 이름을 입력해 주세요.")
        links = {row["path_key"]: row["path"] for row in connection.execute(
            "SELECT path_key, path FROM file_tags WHERE tag_id = ?", (tag_id,))}
        if not selected <= links.keys():
            raise ValueError("선택한 파일의 태그가 바뀌었어요. 창을 닫고 목록을 다시 확인해 주세요.")
        if links and not selected:
            raise ValueError("변경할 파일을 하나 이상 선택해 주세요.")
        all_selected = selected == links.keys()
        target = connection.execute("SELECT * FROM tags WHERE name_key = ?", (name.casefold(),)).fetchone()
        if target is not None and target["id"] == tag_id and not all_selected:
            raise ValueError("대소문자만 바꾸려면 전체 파일을 선택해 주세요. 일부 파일은 다른 태그 이름을 사용해 주세요.")
        if all_selected and (target is None or target["id"] == tag_id):
            connection.execute("UPDATE tags SET name = ?, name_key = ? WHERE id = ?", (name, name.casefold(), tag_id))
            target_id = tag_id
        else:
            if target is None:
                cursor = connection.execute("INSERT INTO tags(name, name_key, color) VALUES (?, ?, ?)",
                                            (name, name.casefold(), source["color"]))
                target_id = cursor.lastrowid
            else:
                target_id = target["id"]
            connection.executemany("""
                INSERT INTO file_tags(path_key, path, tag_id) VALUES (?, ?, ?)
                ON CONFLICT(path_key, tag_id) DO NOTHING
            """, ((key, links[key], target_id) for key in sorted(selected)))
            connection.executemany("DELETE FROM file_tags WHERE path_key = ? AND tag_id = ?",
                                   ((key, tag_id) for key in sorted(selected)))
            if all_selected:
                connection.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        row = connection.execute("""
            SELECT t.id, t.name, t.color, COUNT(f.path_key) AS file_count
            FROM tags t LEFT JOIN file_tags f ON f.tag_id = t.id WHERE t.id = ? GROUP BY t.id
        """, (target_id,)).fetchone()
        retained = connection.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone() is not None
        return TagEditResult(Tag(row["id"], row["name"], row["file_count"], row["color"]), len(selected), retained)
