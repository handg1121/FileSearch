"""파일명 검색 핵심 로직 (화면 코드와 분리, PySide6를 쓰지 않음)

흐름
  1. 조건 정리   parse_keywords     검색어를 띄어쓰기로 나눔 (나눈 말이 모두 들어간 파일만 찾음)
                modified_since     수정일 조건(오늘, 최근 7일 ...)을 기준 시각으로 바꿈
  2. 훑기       search_by_name     저장 위치 전체를 훑으며 조건에 맞는 파일을 모음
                matches_name       파일명 하나가 검색어에 맞는지
  3. 정렬       sort_hits          수정일·이름·크기 순으로 정렬
"""
import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from collector.type_selector_script import JOURNAL_NAME, PART_SUFFIX


TYPE_GROUPS = {
    "전체": None,
    "한글": {"hwp", "hwpx"},
    "엑셀": {"xls", "xlsx"},
    "PowerPoint": {"ppt", "pptx"},
    "Word": {"doc", "docx"},
    "PDF": {"pdf"},
    "텍스트": {"txt"},
    "이미지": {"jpg", "png"},
}
DATE_RANGES = ["전체 기간", "오늘", "최근 7일", "최근 30일", "올해"]
SORT_ORDERS = ["수정일 최신순", "수정일 오래된순", "이름순", "크기순"]


@dataclass
class SearchHit:
    path: str
    name: str
    folder: str
    size: int
    modified: float
    body_excerpt: str = ""


def normalize(text):
    '맥에서 온 파일명은 한글 자모가 풀려 있어(NFD) 같은 글자인데도 검색이 안 됨 → 합쳐진 형태(NFC)로 통일'
    return unicodedata.normalize("NFC", text)


def parse_keywords(text):
    return normalize(text).lower().split()


def modified_since(date_range, now=None):
    '수정일 조건의 시작 시각(timestamp). 전체 기간이면 None'
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if date_range == "오늘":
        start = today
    elif date_range == "최근 7일":
        start = now - timedelta(days=7)
    elif date_range == "최근 30일":
        start = now - timedelta(days=30)
    elif date_range == "올해":
        start = today.replace(month=1, day=1)
    else:
        return None
    return start.timestamp()


def search_by_name(root, keywords, extensions=None, since=None):
    """root 아래 모든 폴더를 훑어 조건에 맞는 파일을 SearchHit 목록으로 돌려준다.
keywords가 비어 있으면 (다른 조건에 맞는) 모든 파일"""
    hits = []
    folders = [root]
    while folders:
        folder = folders.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    folders.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False) or is_work_file(entry.name):
                    continue
                if not matches_name(entry.name, keywords):
                    continue
                ext = os.path.splitext(entry.name)[1][1:].lower()
                if extensions and ext not in extensions:
                    continue
                info = entry.stat()
                if since and info.st_mtime < since:
                    continue
                relative = os.path.relpath(folder, root)
                hits.append(SearchHit(
                    path=entry.path,
                    name=normalize(entry.name),
                    folder="" if relative == "." else relative,
                    size=info.st_size,
                    modified=info.st_mtime,
                ))
            except OSError:
                continue
    return hits


def is_work_file(name):
    '파일 모으기가 쓰는 기록 파일과 복사 중인 임시 파일은 검색에서 뺌'
    return name == JOURNAL_NAME or name.endswith(PART_SUFFIX)


def matches_name(name, keywords):
    lowered = normalize(name).lower()
    for keyword in keywords:
        if keyword not in lowered:
            return False
    return True


def sort_hits(hits, order):
    if order == "수정일 오래된순":
        return sorted(hits, key=lambda hit: hit.modified)
    if order == "이름순":
        return sorted(hits, key=lambda hit: hit.name.lower())
    if order == "크기순":
        return sorted(hits, key=lambda hit: hit.size, reverse=True)
    return sorted(hits, key=lambda hit: hit.modified, reverse=True)
