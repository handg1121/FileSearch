"""파일 하나를 Windows 휴지통으로 보내요.

휴지통에 넣을 수 없는 경우(휴지통이 없는 USB·네트워크 드라이브, 휴지통 용량보다 큰 파일)
Windows가 확인 없이 영구 삭제하지 않도록 FOF_WANTNUKEWARNING을 켜요. 그러면 Windows가
영구 삭제할지 물어보고, 거절하면 파일은 그대로 남아 실패로 돌려줘요.
"""

import ctypes
from ctypes import wintypes
import os

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def send_to_trash(path):
    '성공하면 None, 실패하면 OSError. 파일이 실제로 사라졌는지까지 확인해요.'
    path = os.path.abspath(path)
    # pFrom은 여러 경로를 받는 형식이라 끝에 null이 두 번 있어야 해요.
    buffer = ctypes.create_unicode_buffer(path + "\0")
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = FO_DELETE
    operation.pFrom = ctypes.cast(buffer, ctypes.c_wchar_p)
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT | FOF_WANTNUKEWARNING
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if operation.fAnyOperationsAborted:
        raise OSError("영구 삭제를 취소해서 지우지 않았어요.")
    if code != 0:
        raise OSError(f"휴지통으로 보내지 못했어요. (코드 {code:#x})")
    if os.path.lexists(path):
        raise OSError("휴지통으로 보내지 못했어요. 파일이 그대로 있어요.")
