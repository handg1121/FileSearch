"""전체 경로·파일명만으로 이동 후보를 찾고, 사용자의 결정을 DB에 적용해요."""

from collections import defaultdict
from dataclasses import dataclass
import os
import stat

from searcher.metadata import check_cancelled, path_key
from tagger.storage import _connect, _remember_paths


@dataclass(frozen=True)
class MoveCandidate:
    old_path: str
    new_paths: tuple[str, ...]
    tag_ids: tuple[int, ...]
    tag_names: tuple[str, ...]


@dataclass(frozen=True)
class MoveChoice:
    candidate: MoveCandidate
    new_path: str


def _inside(path, root):
    try:
        return os.path.commonpath((path_key(path), path_key(root))) == path_key(root)
    except ValueError:
        return False


def _missing(path):
    # 접근 거부나 장치 오류는 FileNotFoundError와 구분해서 보류해요.
    try:
        os.stat(path, follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        return True
    return False


def _tag_rows(connection, key):
    return connection.execute("""
        SELECT t.id, t.name FROM file_tags f JOIN tags t ON t.id = f.tag_id
        WHERE f.path_key = ? ORDER BY t.id
    """, (key,)).fetchall()


def find_path_moves(snapshot, db_path=None, *, should_stop=lambda: False):
    """완료된 전체 탐색으로만 후보를 만들어요. 검색어·종류·날짜 필터는 적용하지 않아요.

    이미 등록된 다른 파일을 대상으로 삼지 않아요. 보류한 후보의 새 경로는 등록을
    미뤄서 다음 검색에도 다시 확인할 수 있어요. 원본 파일을 읽거나 수정하지 않아요.
    """
    check_cancelled(should_stop)
    if not snapshot.complete:
        return []
    with _connect(db_path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        known = {row["path_key"]: row["path"] for row in connection.execute("SELECT path_key, path FROM tracked_files")}
        tagged = {row["path_key"]: row["path"] for row in connection.execute("SELECT DISTINCT path_key, path FROM file_tags")}
        # 태그가 있는 경로는 기존 DB에서도 반드시 기존 파일로 취급해요.
        known.update(tagged)
        by_name = defaultdict(list)
        for key, item in snapshot.files.items():
            check_cancelled(should_stop)
            if key not in known:
                by_name[os.path.normcase(item.name)].append(item.path)
        moves, pending_keys = [], set()
        for key, old_path in tagged.items():
            check_cancelled(should_stop)
            if key in snapshot.files or not _inside(old_path, snapshot.root):
                continue
            paths = by_name.get(os.path.normcase(os.path.basename(old_path)), [])
            if not paths:
                continue
            try:
                if not _missing(old_path):
                    continue
            except OSError:
                pending_keys.update(path_key(path) for path in paths)
                continue
            rows = _tag_rows(connection, key)
            paths = tuple(sorted(paths, key=path_key))
            moves.append(MoveCandidate(old_path, paths, tuple(row["id"] for row in rows),
                                       tuple(row["name"] for row in rows)))
            pending_keys.update(path_key(path) for path in paths)
        for key, item in snapshot.files.items():
            check_cancelled(should_stop)
            if key not in pending_keys and known.get(key) != item.path:
                _remember_paths(connection, [item.path])
        return sorted(moves, key=lambda move: path_key(move.old_path))


def resolve_path_moves(choices, *, transfer, db_path=None):
    """승인한 태그 연결을 옮기거나 거절한 이전 경로의 DB 기록을 정리해요."""
    choices = list(choices)
    if not choices:
        return 0
    # 이동은 일대일로만 적용해요. 같은 기존 경로의 삭제 요청은 하나로 합쳐요.
    unique, destinations = {}, set()
    for choice in choices:
        old_key, new_key = path_key(choice.candidate.old_path), path_key(choice.new_path)
        if choice.new_path not in choice.candidate.new_paths or old_key == new_key:
            raise ValueError("이동 후보가 바뀌었어요. 다시 검색해 주세요.")
        if transfer and (old_key in unique or new_key in destinations):
            raise ValueError("기존 파일 하나당 새 경로 하나만 선택해 주세요. 같은 새 경로에 여러 파일의 태그를 옮길 수 없어요.")
        unique[old_key] = choice
        destinations.add(new_key)
    with _connect(db_path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        # 모든 항목을 재확인한 다음 한 번에 적용해요. 실패하면 전체를 되돌려요.
        for old_key, choice in unique.items():
            candidate = choice.candidate
            try:
                missing = _missing(candidate.old_path)
            except OSError as error:
                raise ValueError(f"기존 경로를 확인하지 못했어요: {candidate.old_path}") from error
            if not missing:
                raise ValueError(f"기존 경로에 파일이 다시 생겼어요. 다시 검색해 주세요: {candidate.old_path}")
            rows = _tag_rows(connection, old_key)
            if tuple(row["id"] for row in rows) != candidate.tag_ids:
                raise ValueError("확인 중 태그 정보가 변경됐어요. 다시 검색해 주세요.")
            # 대상이 사라지거나 접근할 수 없으면 거절 처리도 보류해요.
            try:
                info = os.stat(choice.new_path, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise OSError("일반 파일이 아니에요.")
            except OSError as error:
                raise ValueError(f"새 경로의 파일을 확인하지 못했어요: {choice.new_path}") from error
            if transfer:
                new_key = path_key(choice.new_path)
                if connection.execute("SELECT 1 FROM tracked_files WHERE path_key = ?", (new_key,)).fetchone():
                    raise ValueError("새 경로가 다른 파일로 등록됐어요. 다시 검색해 주세요.")
                if _tag_rows(connection, new_key):
                    raise ValueError("새 경로에 다른 태그 정보가 생겼어요. 다시 검색해 주세요.")
        has_body = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_cache'").fetchone()
        for old_key, choice in unique.items():
            if transfer:
                new_path = os.path.abspath(choice.new_path)
                new_key = path_key(new_path)
                connection.execute("UPDATE file_tags SET path_key = ?, path = ? WHERE path_key = ?",
                                   (new_key, new_path, old_key))
                _remember_paths(connection, [new_path])
            else:
                connection.execute("DELETE FROM file_tags WHERE path_key = ?", (old_key,))
            connection.execute("DELETE FROM tracked_files WHERE path_key = ?", (old_key,))
            if has_body:
                # 동명 파일의 내용은 다를 수 있으므로 이전 본문은 옮기지 않아요.
                connection.execute("DELETE FROM body_cache WHERE path_key = ?", (old_key,))
        return len(unique)


def transfer_tags_to_kept(pairs, db_path=None):
    """중복 정리로 휴지통에 보낸 파일의 태그를 남긴 파일로 옮기고, 새로 붙은 연결 수를 돌려줘요.

    resolve_path_moves와 달리 남긴 파일이 이미 등록돼 있거나 태그가 있어도 괜찮아요.
    같은 태그는 하나로 합쳐요. 지운 경로의 태그 연결·등록 정보·본문 캐시는 삭제해요.
    모든 변경은 한 트랜잭션으로 처리해요.
    """
    pairs = list(pairs)
    if not pairs:
        return 0
    with _connect(db_path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        has_body = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_cache'").fetchone()
        moved = 0
        for removed_path, kept_path in pairs:
            removed_key = path_key(removed_path)
            kept_path = os.path.abspath(kept_path)
            kept_key = path_key(kept_path)
            if removed_key == kept_key:
                raise ValueError(f"남길 파일과 지운 파일이 같아요: {kept_path}")
            moved += connection.execute("""
                INSERT INTO file_tags(path_key, path, tag_id)
                SELECT ?, ?, tag_id FROM file_tags WHERE path_key = ?
                ON CONFLICT(path_key, tag_id) DO NOTHING
            """, (kept_key, kept_path, removed_key)).rowcount
            _remember_paths(connection, [kept_path])
            connection.execute("DELETE FROM file_tags WHERE path_key = ?", (removed_key,))
            connection.execute("DELETE FROM tracked_files WHERE path_key = ?", (removed_key,))
            if has_body:
                connection.execute("DELETE FROM body_cache WHERE path_key = ?", (removed_key,))
        return moved
