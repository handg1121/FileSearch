"""묶음마다 고른 파일 하나만 남기고 나머지를 휴지통으로 보내요.

찾은 뒤 크기나 수정 시각이 바뀐 파일이 있으면 그 묶음은 건드리지 않아요.
찾기는 저장된 해시를 쓸 수 있으므로, 지우기 직전에 묶음의 모든 파일(남길 파일 포함)을
새로 읽어 해시가 같은지 다시 확인해요. 하나라도 다르면 그 묶음은 건너뛰어요.
휴지통으로 실제 보낸 파일의 태그만 남긴 파일로 옮겨요. 취소는 묶음 사이와 다시 읽는 중에 받아요.
"""

from dataclasses import dataclass, field
import os
import re
import sqlite3
import unicodedata

from collector.type_selector_script import DUPLICATE_MARK
from duplicates.finder import file_digest
from duplicates.trash import send_to_trash
from searcher.metadata import SearchCancelled, metadata_for_path
from tagger.path_tracking import transfer_tags_to_kept


@dataclass(frozen=True)
class KeepChoice:
    group: object  # DuplicateGroup
    keep: object   # 묶음 안의 FileMetadata

    @property
    def removes(self):
        result = []
        for item in self.group.files:
            if item.key != self.keep.key:
                result.append(item)
        return result


# 파일 모으기가 같은 이름을 피하려고 붙이는 꼬리표 (보고서_중복1.hwp)
COPY_NAME = re.compile(re.escape(DUPLICATE_MARK) + r"\d+$")


def is_copy_name(name):
    stem = os.path.splitext(unicodedata.normalize("NFC", name))[0]
    return COPY_NAME.search(stem) is not None


def pick_original(group):
    '이름 끝에 _중복N이 없는 파일이 딱 하나면 그 파일을, 없거나 여럿이면 None을 돌려줘요.'
    originals = []
    for item in group.files:
        if not is_copy_name(item.name):
            originals.append(item)
    if len(originals) == 1:
        return originals[0]
    return None


@dataclass
class RemoveResult:
    trashed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    moved_tags: int = 0
    tag_error: str = ""
    cancelled: bool = False


def changed_reason(group):
    '찾을 때와 달라진 파일이 있으면 사유를, 그대로면 빈 글자를 돌려줘요.'
    for item in group.files:
        try:
            now = metadata_for_path(item.path)
        except OSError:
            return f"파일을 확인하지 못해 이 묶음은 건너뛰었어요: {item.path}"
        if now.size != item.size or now.mtime_ns != item.mtime_ns:
            return f"찾은 뒤 파일이 바뀌어 이 묶음은 건너뛰었어요: {item.path}"
    return ""


def content_reason(group, should_stop=lambda: False):
    '저장된 해시 대신 파일을 새로 읽어, 내용이 찾을 때와 다르면 사유를 돌려줘요.'
    for item in group.files:
        try:
            digest = file_digest(item.path, should_stop)
        except OSError:
            return f"파일을 다시 읽지 못해 이 묶음은 건너뛰었어요: {item.path}"
        if digest != group.digest:
            return f"다시 읽어 보니 내용이 달라 이 묶음은 건너뛰었어요: {item.path}"
    return ""


def remove_duplicates(choices, *, trash=send_to_trash, db_path=None,
                      on_progress=lambda *args: None, should_stop=lambda: False):
    result = RemoveResult()
    total = 0
    for choice in choices:
        total += len(choice.removes)
    done = 0
    pairs = []
    for choice in choices:
        if should_stop():
            result.cancelled = True
            break
        reason = changed_reason(choice.group)
        if not reason:
            on_progress("내용 다시 확인 중", done, total, choice.keep.path)
            try:
                reason = content_reason(choice.group, should_stop)
            except SearchCancelled:
                # 앞 묶음에서 이미 보낸 파일의 태그는 아래에서 그대로 옮겨요.
                result.cancelled = True
                break
        for item in choice.removes:
            on_progress("휴지통으로 보내는 중", done, total, item.path)
            done += 1
            if reason:
                result.failed.append((item.path, reason))
                continue
            try:
                trash(item.path)
            except OSError as error:
                result.failed.append((item.path, str(error)))
                continue
            result.trashed.append(item.path)
            pairs.append((item.path, choice.keep.path))
    on_progress("휴지통으로 보내는 중", done, total, "")
    if pairs:
        # 파일은 이미 휴지통에 있으므로 DB 오류가 나도 결과는 그대로 알려 줘요.
        try:
            result.moved_tags = transfer_tags_to_kept(pairs, db_path=db_path)
        except (sqlite3.Error, OSError, ValueError) as error:
            result.tag_error = str(error) or type(error).__name__
    return result
