# 복원 과정에서 새로 작성한 PyInstaller 설정이에요.
# 원래 배포본과 같은 onedir / windowed / _internal 형태로 빌드해요.
from pathlib import Path
import os
import sys

# 다른 프로그램의 PATH에 있는 동명 DLL(예: Poppler의 icuuc.dll)을 섞지 않아요.
# Qt는 Windows의 ICU API를 사용하므로 빌드 시 DLL 검색 경로도 한정해요.
# PyInstaller의 패키지 훅은 필요한 PySide6/shiboken6 경로를 따로 추가해요.
if sys.platform == "win32":
    windows_dir = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(str(path) for path in (
        Path(sys.prefix) / "Scripts", Path(sys.base_prefix),
        windows_dir / "System32", windows_dir,
    ))

project_dir = Path(SPECPATH)
a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileSearch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FileSearch")
