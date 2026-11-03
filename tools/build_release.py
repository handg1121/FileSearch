"""Build a complete first-install ZIP plus a signed update ZIP for GitHub Releases."""
import base64
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
from tools.release_key import load_key


def zip_tree(source, target):
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(source.rglob("*")):
            if file.is_symlink() or file.is_junction():
                raise ValueError("Links are not allowed in release bundles")
            if file.is_file():
                archive.write(file, file.relative_to(source).as_posix())


def build():
    version_tuple(config.VERSION)
    bootstrap = ROOT / "dist" / f"FileSearch-{config.VERSION}"
    if bootstrap.exists():
        raise RuntimeError(f"First-install output already exists: {bootstrap}. Move it aside before rebuilding.")
    key = load_key()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    if public != config.PUBLIC_KEY:
        raise RuntimeError("Release key does not match the pinned public key")
    for spec, output, work in (("FileSearch.spec", "_app", "release-app"),
                               ("Launcher.spec", "_launcher", "release-launcher")):
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--distpath", str(ROOT / "dist" / output), "--workpath", str(ROOT / "build" / work),
                        str(ROOT / spec)], cwd=ROOT, check=True)
    app = ROOT / "dist/_app/FileSearchApp"
    metadata = {"version": config.VERSION, "data_schema": config.DATA_SCHEMA, "launcher_protocol": config.LAUNCHER_PROTOCOL}
    (app / "release.json").write_bytes(json_bytes(metadata))
    output = ROOT / "dist/releases" / config.VERSION
    output.mkdir(parents=True, exist_ok=True)
    update = output / f"FileSearch-update-{config.VERSION}-win64.zip"
    zip_tree(app, update)
    payload = json_bytes(dict(metadata, schema=1, size=update.stat().st_size,
                             sha256=hashlib.sha256(update.read_bytes()).hexdigest(),
                             url=f"https://github.com/{config.REPOSITORY}/releases/download/v{config.VERSION}/{update.name}"))
    manifest = json_bytes({"payload": base64.b64encode(payload).decode("ascii"),
                           "signature": base64.b64encode(key.sign(payload)).decode("ascii")})
    verify_manifest(manifest)
    (output / "update.json").write_bytes(manifest)
    # Version-specific output avoids changing an existing/running portable installation.
    (bootstrap / "versions").mkdir(parents=True)
    shutil.copytree(app, bootstrap / "versions" / config.VERSION)
    shutil.copy2(ROOT / "dist/_launcher/FileSearch.exe", bootstrap / "FileSearch.exe")
    (bootstrap / "시작 안내.txt").write_text(
        "FileSearch.exe를 실행하세요. 이 폴더는 쓰기 가능한 위치에 보관하세요.\n"
        "업데이트는 자동으로 준비되고 프로그램 종료 후 적용돼요.\n"
        "기존 파일, 태그와 설정은 유지돼요.\n", encoding="utf-8")
    portable = output / f"FileSearch-{config.VERSION}-windows-x64.zip"
    zip_tree(bootstrap, portable)
    print(f"Ready: {bootstrap / 'FileSearch.exe'}")
    print(f"Release assets: {output}")


if __name__ == "__main__":
    build()
