"""파일 열기·폴더 열기 (화면 코드와 분리). 실패하면 사유를 글자로 돌려주고, 성공하면 None"""

import os
import subprocess


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
