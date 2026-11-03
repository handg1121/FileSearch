"""Compile the single-file Windows installer with a pinned portable NSIS toolchain."""
import argparse
import hashlib
import html
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NSIS_VERSION = '3.13'
NSIS_SHA256 = 'ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8'
NSIS_URL = f'https://downloads.sourceforge.net/project/nsis/NSIS%203/{NSIS_VERSION}/nsis-{NSIS_VERSION}.zip'
NSIS_PAGE = f'https://sourceforge.net/projects/nsis/files/NSIS%203/{NSIS_VERSION}/nsis-{NSIS_VERSION}.zip/download'
MAX_DOWNLOAD = 8 * 1024 * 1024


def read_download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'FileSearch-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        if urllib.parse.urlparse(response.url).scheme != 'https':
            raise RuntimeError('The compiler download must use HTTPS')
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise RuntimeError('Compiler download exceeds the expected size')
    return data


def ensure_nsis():
    cache = ROOT / '.build-tools'
    cache.mkdir(exist_ok=True)
    archive = cache / f'nsis-{NSIS_VERSION}.zip'
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != NSIS_SHA256:
        data = read_download(NSIS_URL)
        if not data.startswith(b'PK'):
            # SourceForge may return its download page with a short-lived link.
            page = data.decode('utf-8', errors='replace')
            match = re.search(r'https://downloads\.sourceforge\.net/project/nsis/[^"\s]+nsis-3\.13\.zip\?ts=[^"\s]+', page)
            if match is None:
                page = read_download(NSIS_PAGE).decode('utf-8', errors='replace')
                match = re.search(r'https://downloads\.sourceforge\.net/project/nsis/[^"\s]+nsis-3\.13\.zip\?ts=[^"\s]+', page)
            if match:
                data = read_download(html.unescape(match.group()))
        if hashlib.sha256(data).hexdigest() != NSIS_SHA256:
            raise RuntimeError('NSIS download does not match the official SHA-256; nothing was executed')
        temporary = archive.with_suffix('.download')
        temporary.write_bytes(data)
        temporary.replace(archive)
    # Re-extract verified tool bytes; never run an unverified PATH compiler.
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            target = cache / info.filename
            if not target.resolve().is_relative_to(cache.resolve()) or '\\' in info.filename:
                raise RuntimeError('Unexpected path in the compiler archive')
        zipped.extractall(cache)
    compiler = cache / f'nsis-{NSIS_VERSION}' / 'makensis.exe'
    if not compiler.is_file():
        raise RuntimeError('NSIS compiler is missing')
    return compiler


def build_installer(bundle, output, version):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if not (bundle / 'FileSearch.exe').is_file():
        raise RuntimeError('Missing FileSearch launcher')
    for path in bundle.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError('Links are not permitted in the installer payload')
    compiler = ensure_nsis()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), '/NOCONFIG', '/V3', '/WX', '/INPUTCHARSET', 'UTF8',
                    f'/DAPP_VERSION={version}', f'/DBUNDLE={bundle}', f'/DOUTPUT_EXE={output}',
                    str(ROOT / 'installer/FileSearch.nsi')], cwd=ROOT, check=True)
    if not output.is_file() or output.stat().st_size < 1_000_000:
        raise RuntimeError('Installer output is missing or incomplete')
    print(f'Installer: {output}')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from updater.protocol import version_tuple
    version_tuple(args.version)
    build_installer(args.bundle, args.output, args.version)
