"""Windows 파일 연결 아이콘과 앱에 내장한 문서 아이콘을 제공해요."""

import atexit
import ctypes
from ctypes import wintypes
import ntpath
import os
import sys

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel


FILE_TYPES = {
    "hwp": ("한", "#1e88e5"), "hwpx": ("HWPX", "#1e88e5"),
    "doc": ("W", "#2b579a"), "docx": ("W", "#2b579a"),
    "xls": ("X", "#217346"), "xlsx": ("X", "#217346"),
    "ppt": ("P", "#d24726"), "pptx": ("P", "#d24726"),
    "pdf": ("PDF", "#e53935"), "txt": ("TXT", "#607d8b"),
    "jpg": ("JPG", "#26a69a"), "png": ("PNG", "#8e5bd8"),
}


def file_extension(file_name):
    """경로/파일명 또는 '.pdf' 형태의 명시적 확장자를 정규화해요."""
    name = ntpath.basename(os.fspath(file_name)).lower()
    ext = name[1:] if name.startswith('.') and name.count('.') == 1 else ntpath.splitext(name)[1][1:]
    return ext if len(ext) <= 100 and not any(ord(char) < 32 for char in ext) else ''


class _ShellFileInfo(ctypes.Structure):
    _fields_ = [
        ('hIcon', wintypes.HANDLE), ('iIcon', ctypes.c_int),
        ('dwAttributes', wintypes.DWORD), ('szDisplayName', wintypes.WCHAR * 260),
        ('szTypeName', wintypes.WCHAR * 80),
    ]


def load_windows_icon(extension):
    """작업 스레드에서 확장자만 조회해요. 실제 문서나 네트워크 경로는 열지 않아요.

    SHGFI_USEFILEATTRIBUTES로 연결 아이콘을 얻고, 미등록 파일과 같은 일반
    아이콘이면 빈 이미지를 반환해 내장 아이콘을 사용해요. HICON은 반드시 해제해요.
    https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shgetfileinfow
    """
    if sys.platform != 'win32' or not extension:
        return QImage()
    shell = ctypes.WinDLL('shell32')
    user = ctypes.WinDLL('user32')
    ole = ctypes.WinDLL('ole32')
    query = shell.SHGetFileInfoW
    query.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_ShellFileInfo),
                      wintypes.UINT, wintypes.UINT]
    query.restype = ctypes.c_size_t
    user.DestroyIcon.argtypes = [wintypes.HANDLE]
    user.DestroyIcon.restype = wintypes.BOOL
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if initialized < 0:
        return QImage()
    info = _ShellFileInfo()
    try:
        # 일반 파일 아이콘의 인덱스를 비교하며 특정 Windows 버전의 번호에 의존하지 않아요.
        generic = _ShellFileInfo()
        flags = 0x10 | 0x4000  # SHGFI_USEFILEATTRIBUTES | SHGFI_SYSICONINDEX
        has_generic = query('file.filesearch_unregistered_987a725c', 0x80,
                            ctypes.byref(generic), ctypes.sizeof(generic), flags)
        ok = query('file.' + extension, 0x80, ctypes.byref(info), ctypes.sizeof(info),
                   flags | 0x100)  # SHGFI_ICON (large)
        if not ok or not info.hIcon or (has_generic and info.iIcon == generic.iIcon):
            return QImage()
        return QImage.fromHICON(info.hIcon).copy()
    finally:
        if info.hIcon:
            user.DestroyIcon(info.hIcon)
        ole.CoUninitialize()


def is_visible_icon(image):
    """현재의 밝은 UI에서 실제로 식별되는 아이콘인지 확인해요.

    QImage.isNull()은 완전히 투명하거나 거의 흰색인 이미지도 유효하다고 해요.
    표시 크기로 줄인 뒤 흰 배경에 합성했을 때 차이가 충분한 픽셀이 최소 1%는
    있어야 해요. 알파를 반영하므로 희미한 검정색도 그대로 통과시키지 않아요.
    """
    if image.isNull():
        return False
    sample = image.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    required = max(4, (sample.width() * sample.height() + 99) // 100)
    visible = 0
    for y in range(sample.height()):
        for x in range(sample.width()):
            color = sample.pixelColor(x, y)
            difference = max(255 - color.red(), 255 - color.green(), 255 - color.blue())
            if difference * color.alpha() >= 48 * 255:
                visible += 1
                if visible >= required:
                    return True
    return False


def builtin_icon(extension):
    """외부 이미지 파일 없이 EXE에 포함되는 접힌 문서 모양의 대체 아이콘이에요."""
    text, color = FILE_TYPES.get(extension, ('', '#94a3b8'))
    pixmap = QPixmap(128, 144)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        page = QPainterPath()
        page.moveTo(28, 8)
        page.lineTo(81, 8)
        page.lineTo(109, 36)
        page.lineTo(109, 129)
        page.quadTo(109, 136, 102, 136)
        page.lineTo(28, 136)
        page.quadTo(21, 136, 21, 129)
        page.lineTo(21, 15)
        page.quadTo(21, 8, 28, 8)
        painter.setPen(QPen(QColor('#cbd5e1'), 3))
        painter.setBrush(QColor('#f8fafc'))
        painter.drawPath(page)
        fold = QPainterPath()
        fold.moveTo(81, 8)
        fold.lineTo(81, 36)
        fold.lineTo(109, 36)
        painter.setBrush(QColor('#e2e8f0'))
        painter.drawPath(fold)
        painter.setPen(QPen(QColor(color), 5, Qt.SolidLine, Qt.RoundCap))
        if extension in ('ppt', 'pptx'):
            painter.drawRoundedRect(QRectF(37, 49, 56, 34), 2, 2)
            painter.drawLine(65, 83, 65, 91)
        elif extension in ('xls', 'xlsx'):
            painter.drawRect(QRectF(37, 49, 56, 37))
            painter.drawLine(56, 49, 56, 86)
            painter.drawLine(37, 67, 93, 67)
        elif extension in ('jpg', 'png'):
            painter.drawEllipse(QRectF(74, 48, 12, 12))
            painter.drawLine(37, 82, 54, 63)
            painter.drawLine(54, 63, 69, 78)
            painter.drawLine(69, 78, 80, 68)
            painter.drawLine(80, 68, 94, 82)
        else:
            for y, end in ((53, 92), (67, 92), (81, 76)):
                painter.drawLine(37, y, end, y)
        if text:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(9, 94, 110, 35), 5, 5)
            font = QFont('Malgun Gothic')
            font.setPixelSize(22 if len(text) >= 4 else 25)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(Qt.white)
            painter.drawText(QRectF(9, 93, 110, 35), Qt.AlignCenter, text)
    finally:
        painter.end()
    return QIcon(pixmap)


class _LoadSignals(QObject):
    finished = Signal(str, QImage)


class _LoadIcon(QRunnable):
    def __init__(self, extension, loader):
        super().__init__()
        self.extension = extension
        self.loader = loader
        self.signals = _LoadSignals()

    def run(self):
        try:
            image = self.loader(self.extension)
        except Exception:
            # 아이콘 조회 실패가 파일 검색이나 화면 표시를 막지는 않아요.
            image = QImage()
        self.signals.finished.emit(self.extension, image)


class FileIconProvider(QObject):
    changed = Signal(str)

    def __init__(self, parent=None, *, loader=None):
        super().__init__(parent)
        self.loader = loader or load_windows_icon
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.icons = {}
        self.sources = {}
        self.pending = {}
        self.closing = False
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        # app.exec() 없이 끝나는 GUI 검사에서도 Python 종료 전에 작업을 정리해요.
        atexit.register(self.shutdown)

    def icon_for(self, extension):
        if extension not in self.icons:
            self.icons[extension] = builtin_icon(extension)
            self.sources[extension] = 'builtin'
            if extension and not self.closing:
                job = _LoadIcon(extension, self.loader)
                job.signals.finished.connect(self._loaded)
                self.pending[extension] = job
                self.pool.start(job)
        return self.icons[extension]

    @Slot()
    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.pool.clear()
        self.pool.waitForDone()
        self.pending.clear()

    @Slot(str, QImage)
    def _loaded(self, extension, image):
        if self.closing:
            return
        self.pending.pop(extension, None)
        if is_visible_icon(image):
            self.icons[extension] = QIcon(QPixmap.fromImage(image))
            self.sources[extension] = 'windows'
        self.changed.emit(extension)


def icon_provider():
    app = QApplication.instance()
    if not hasattr(app, '_filesearch_icon_provider'):
        app._filesearch_icon_provider = FileIconProvider(app)
    return app._filesearch_icon_provider


class FileTypeIcon(QLabel):
    def __init__(self, file_name, size=34, parent=None, *, provider=None):
        super().__init__(parent)
        self.setObjectName('fileTypeIcon')
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(size, int(size * 1.15))
        self.setStyleSheet('background: transparent; border: none; padding: 0;')
        self.provider = provider or icon_provider()
        self.provider.changed.connect(self._icon_changed)
        self.set_file_name(file_name)

    def set_file_name(self, file_name):
        self.extension = file_extension(file_name)
        self.setAccessibleName(f'{self.extension.upper()} 파일' if self.extension else '파일')
        self._refresh()

    @Slot(str)
    def _icon_changed(self, extension):
        if self.extension == extension:
            self._refresh()

    def _refresh(self):
        icon = self.provider.icon_for(self.extension)
        self.setPixmap(icon.pixmap(QSize(self.width(), self.height()), self.devicePixelRatioF()))
        self.setProperty('iconSource', self.provider.sources[self.extension])
