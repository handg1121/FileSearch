"""Build a user installer; --release additionally produces signed automatic-update files."""
import argparse
import base64
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater import config
from updater.protocol import json_bytes, verify_manifest, version_tuple
from tools.build_installer import build_installer, ensure_nsis


def zip_tree(source, target):
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(source.rglob('*')):
            if file.is_symlink() or file.is_junction():
                raise ValueError('Links are not allowed in release bundles')
            if file.is_file():
                archive.write(file, file.relative_to(source).as_posix())


def build(release=False):
    version_tuple(config.VERSION)
    key = None
    if release:
        from tools.release_key import load_key
        key = load_key()
        public = base64.b64encode(key.public_key().public_bytes_raw()).decode('ascii')
        if public != config.PUBLIC_KEY:
            raise RuntimeError('Release key does not match the pinned public key')
        bootstrap = ROOT / 'dist' / f'FileSearch-{config.VERSION}'
        output = ROOT / 'dist/releases' / config.VERSION
        if bootstrap.exists() or output.exists():
            raise RuntimeError('This release version already has output. Increase VERSION before a new release.')
    else:
        output = ROOT / 'dist/development' / (config.VERSION + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        bootstrap = output / 'FileSearch'
    compiler = ensure_nsis()  # Fail before the app build if the compiler cannot be obtained.
    for spec, destination, work in (('FileSearch.spec', '_app', 'release-app'),
                                     ('Launcher.spec', '_launcher', 'release-launcher')):
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--distpath', str(ROOT / 'dist' / destination), '--workpath', str(ROOT / 'build' / work),
                        str(ROOT / spec)], cwd=ROOT, check=True)
    app = ROOT / 'dist/_app/FileSearchApp'
    metadata = {'version': config.VERSION, 'data_schema': config.DATA_SCHEMA, 'launcher_protocol': config.LAUNCHER_PROTOCOL}
    (app / 'release.json').write_bytes(json_bytes(metadata))
    output.mkdir(parents=True, exist_ok=True)
    (bootstrap / 'versions').mkdir(parents=True)
    shutil.copytree(app, bootstrap / 'versions' / config.VERSION)
    shutil.copy2(ROOT / 'dist/_launcher/FileSearch.exe', bootstrap / 'FileSearch.exe')
    (bootstrap / 'licenses').mkdir()
    shutil.copy2(compiler.parent / 'COPYING', bootstrap / 'licenses/NSIS-LICENSE.txt')
    (bootstrap / 'THIRD_PARTY_NOTICES.txt').write_text(
        'Installer: NSIS 3.13 (https://nsis.sourceforge.io/), license: licenses/NSIS-LICENSE.txt\n'
        'NSIS source: https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/nsis-3.13-src.tar.bz2/download\n'
        'OCR notices and licenses: versions/<version>/_internal/ocr_runtime/THIRD_PARTY_NOTICES.txt\n', encoding='utf-8')
    (bootstrap / '시작 안내.txt').write_text(
        'FileSearch.exe를 실행하세요. 이 폴더는 쓰기 가능한 위치에 보관하세요.\n'
        '업데이트는 자동으로 준비되고 프로그램 종료 후 적용돼요.\n'
        '기존 파일, 태그와 설정은 유지돼요.\n', encoding='utf-8')
    installer = build_installer(bootstrap, output / f'FileSearch-Setup-{config.VERSION}.exe', config.VERSION)
    if release:
        update = output / f'FileSearch-update-{config.VERSION}-win64.zip'
        zip_tree(app, update)
        payload = json_bytes(dict(metadata, schema=1, size=update.stat().st_size,
                                 sha256=hashlib.sha256(update.read_bytes()).hexdigest(),
                                 url=f'https://github.com/{config.REPOSITORY}/releases/download/v{config.VERSION}/{update.name}'))
        manifest = json_bytes({'payload': base64.b64encode(payload).decode('ascii'),
                               'signature': base64.b64encode(key.sign(payload)).decode('ascii')})
        verify_manifest(manifest)
        (output / 'update.json').write_bytes(manifest)
    record = {'version': config.VERSION, 'signed_update': release,
              'files': {path.name: {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                        for path in sorted(output.iterdir()) if path.is_file()}}
    (output / 'build-info.json').write_bytes(json_bytes(record))
    print(f'Ready: {installer}')
    print('Application and installer were built; no runtime tests or installation were run.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', action='store_true', help='Requires the private release key and creates signed update assets')
    build(parser.parse_args().release)
