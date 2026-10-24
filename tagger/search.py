"""SQLite 태그명 검색과 태그 더블클릭 조회. 본문은 읽지 않아요."""

from contextlib import closing
from dataclasses import dataclass, field
import os
import sqlite3

from searcher.filename_search import SearchHit, normalize
from searcher.metadata import check_cancelled, metadata_for_path
from tagger.storage import _chunks, _connect, _marks, read_tag_paths


@dataclass
class TagSearchResult:
    name: str
    hits: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    missing: int = 0


def search_by_tag(tag_id, db_path=None, *, on_progress=lambda *args: None, should_stop=lambda: False):
    check_cancelled(should_stop)
    tag, paths = read_tag_paths(tag_id, db_path)
    result = TagSearchResult(tag.name)
    for index, path in enumerate(paths):
        check_cancelled(should_stop)
        on_progress("태그 파일 확인 중", index, len(paths), path)
        try:
            item = metadata_for_path(path)
        except (FileNotFoundError, NotADirectoryError):
            result.missing += 1
        except OSError as error:
            result.errors.append((path, str(error)))
        else:
            result.hits.append(SearchHit(item.path, normalize(item.name), os.path.dirname(item.path),
                                         item.size, item.mtime_ns / 1_000_000_000))
    check_cancelled(should_stop)
    on_progress("태그 파일 확인 중", len(paths), len(paths), "")
    return result


def search_keyword_tag(root, query, candidates, db_path=None, *,
                       on_progress=lambda *args: None, should_stop=lambda: False):
    """태그명에 입력 문구가 포함된 파일을 SQLite에서 찾아요.

    후보는 공통 폴더 탐색·종류·날짜 필터를 통과한 파일이에요. 태그가 여러 개
    일치해도 한 번만 반환해요. 빈 검색어는 태그가 붙은 파일 전체를 뜻해요.
    %, _, *와 따옴표는 와일드카드나 SQL 구문이 아닌 일반 문자예요.
    """
    check_cancelled(should_stop)
    if not candidates:
        return []
    needle = normalize(query.strip()).casefold()
    hits = []
    on_progress("저장된 태그명 검색 중", 0, len(candidates), "")
    with _connect(db_path) as connection:
        connection.set_progress_handler(lambda: int(should_stop()), 1000)
        done = 0
        try:
            for chunk in _chunks(candidates):
                check_cancelled(should_stop)
                with closing(connection.execute(f"""
                    SELECT DISTINCT f.path_key
                    FROM file_tags f JOIN tags t ON t.id = f.tag_id
                    WHERE f.path_key IN ({_marks(chunk)}) AND instr(t.name_key, ?) > 0
                """, [*chunk, needle])) as rows:
                    for row in rows:
                        check_cancelled(should_stop)
                        hits.append(candidates[row["path_key"]].to_hit(root))
                done += len(chunk)
                on_progress("저장된 태그명 검색 중", done, len(candidates), "")
        except sqlite3.OperationalError:
            check_cancelled(should_stop)
            raise
        finally:
            connection.set_progress_handler(None, 0)
    check_cancelled(should_stop)
    return hits
