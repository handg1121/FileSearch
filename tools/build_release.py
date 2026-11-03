"""Build a standalone EXE; --release additionally produces signed automatic-update files."""
import argparse
import base64
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater import config
from updater.protocol import json_bytes, verify_manifest, version_tuple


def zip_tree(source, target):
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(source.rglob('*')):
            if file.is_symlink() or file.is_junction():
                raise ValueError('Links are not allowed in release bundles')
            if file.is_file():
                archive.write(file, file.relative_to(source).as_posix())


def freeze(spec, destination, work, environment=None):
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(destination), '--workpath', str(ROOT / 'build' / work),
                    str(ROOT / spec)], cwd=ROOT, env=environment, check=True)


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
        bootstrap = output / 'folder-build'
    freeze('FileSearch.spec', ROOT / 'dist/_app', 'release-app')
    app = ROOT / 'dist/_app/FileSearchApp'
    metadata = {'version': config.VERSION, 'data_schema': config.DATA_SCHEMA, 'launcher_protocol': config.LAUNCHER_PROTOCOL}
    (app / 'release.json').write_bytes(json_bytes(metadata))
    output.mkdir(parents=True, exist_ok=True)

    # The same complete archive powers both first launch and signed online updates.
    payload_dir = output / 'embedded-payload'
    payload_dir.mkdir()
    payload_zip = payload_dir / 'app.zip'
    zip_tree(app, payload_zip)
    bundle = dict(metadata, size=payload_zip.stat().st_size,
                  sha256=hashlib.sha256(payload_zip.read_bytes()).hexdigest(), development=not release)
    (payload_dir / 'bundle.json').write_bytes(json_bytes(bundle))
    freeze('Portable.spec', output, 'release-portable',
           dict(os.environ, FILESEARCH_BUILD_PAYLOAD=str(payload_dir)))

    # Preserve a developer-only folder bundle for compatibility diagnostics.
    freeze('Launcher.spec', ROOT / 'dist/_launcher', 'release-launcher')
    (bootstrap / 'versions').mkdir(parents=True)
    shutil.copytree(app, bootstrap / 'versions' / config.VERSION)
    shutil.copy2(ROOT / 'dist/_launcher/FileSearch.exe', bootstrap / 'FileSearch.exe')
    (bootstrap / '시작 안내.txt').write_text(
        '이 폴더는 개발자용 폴더 빌드예요. 전체 폴더를 유지한 채 FileSearch.exe를 실행하세요.\n'
        '사용자 배포 파일은 releases/<버전>/FileSearch.exe 단일 파일이에요.\n', encoding='utf-8')
    if release:
        update = output / f'FileSearch-update-{config.VERSION}-win64.zip'
        shutil.copy2(payload_zip, update)
        payload = json_bytes(dict(metadata, schema=1, size=bundle['size'], sha256=bundle['sha256'],
                                 url=f'https://github.com/{config.REPOSITORY}/releases/download/v{config.VERSION}/{update.name}'))
        manifest = json_bytes({'payload': base64.b64encode(payload).decode('ascii'),
                               'signature': base64.b64encode(key.sign(payload)).decode('ascii')})
        verify_manifest(manifest)
        (output / 'update.json').write_bytes(manifest)
    record = {'version': config.VERSION, 'signed_update': release,
              'files': {path.name: {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                        for path in sorted(output.iterdir()) if path.is_file()}}
    (output / 'build-info.json').write_bytes(json_bytes(record))
    print(f'Ready: {output / "FileSearch.exe"}')
    print('Standalone EXE and app were built; no runtime tests, installation, or upload were run.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', action='store_true', help='Requires the private release key and creates signed update assets')
    build(parser.parse_args().release)
