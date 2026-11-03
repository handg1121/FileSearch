# A stable, windowless supervisor, independent of the replaceable Qt application.
from pathlib import Path
project_dir = Path(SPECPATH)
a = Analysis([str(project_dir / "launch.py")], pathex=[str(project_dir)],
             binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=["PySide6", "PIL"], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="FileSearch", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
