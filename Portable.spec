# A single downloadable EXE containing the launcher and the complete app/OCR ZIP.
from pathlib import Path
import os

project_dir = Path(SPECPATH)
payload = Path(os.environ['FILESEARCH_BUILD_PAYLOAD']).resolve(strict=True)
for name in ('app.zip', 'bundle.json'):
    if not (payload / name).is_file():
        raise ValueError('Missing embedded payload: ' + name)
a = Analysis([str(project_dir / 'portable_launch.py')], pathex=[str(project_dir)],
             binaries=[], datas=[(str(payload / 'app.zip'), 'payload'),
                                 (str(payload / 'bundle.json'), 'payload')],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6', 'PIL'], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='FileSearch', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
