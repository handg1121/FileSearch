"""파일 열기·폴더 열기·휴지통 이동. 실패하면 사유를 글자로 돌려주고, 성공하면 None"""

import os
import stat
import subprocess

from duplicates.trash import send_to_trash


def delete_file(path):
    """검색 결과의 파일 하나를 휴지통으로 보내요. 폴더로 바뀐 경로는 지우지 않아요."""
    try:
        if not stat.S_ISREG(os.stat(path, follow_symlinks=False).st_mode):
            return "일반 파일이 아니어서 삭제하지 않았어요. 다시 검색해 주세요."
        send_to_trash(path)
    except OSError as error:
        return f"파일을 삭제하지 못했어요. ({error})"
    return None


def open_file(path):
    """파일을 연결된 프로그램(한글, 엑셀 등)으로 연다"""
    if not os.path.exists(path):
        return "파일이 없어요. 옮겨졌거나 지워졌을 수 있어요."
    try:
        os.startfile(path)
    except OSError as error:
        return f"파일을 열 수 없어요. ({error})"
    return None


def open_folder(path):
    """파일이 있는 폴더를 탐색기로 열고 그 파일을 선택해 둔다"""
    if not os.path.exists(path):
        return "파일이 없어요. 옮겨졌거나 지워졌을 수 있어요."
    subprocess.Popen(f'explorer /select,"{path}"')
    return None
