"""Verify a signed release, download it over HTTPS and safely unpack its payload."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import urllib.request
from urllib.parse import urlsplit
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from updater import config

MAX_MANIFEST = 64 * 1024
MAX_DOWNLOAD = 1024 * 1024 * 1024
MAX_UNPACKED = 2 * MAX_DOWNLOAD
CHUNK = 1024 * 1024
VERSION_RE = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\Z")


class UpdateError(ValueError):
    pass


class Cancelled(UpdateError):
    pass


def check_cancel(stop):
    if stop():
        raise Cancelled("업데이트 준비를 중단했어요.")


def version_tuple(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise UpdateError("올바르지 않은 버전이에요.")
    return tuple(map(int, value.split(".")))


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest(raw, public_key=None):
    if len(raw) > MAX_MANIFEST:
        raise UpdateError("업데이트 정보가 너무 커요.")
    try:
        envelope = json.loads(raw)
        payload = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        key = base64.b64decode(config.PUBLIC_KEY if public_key is None else public_key, validate=True)
        Ed25519PublicKey.from_public_bytes(key).verify(signature, payload)
        release = json.loads(payload)
        version_tuple(release["version"])
        if release["schema"] != 1 or release["launcher_protocol"] != config.LAUNCHER_PROTOCOL:
            raise ValueError("launcher protocol")
        if release["data_schema"] != config.DATA_SCHEMA:
            raise ValueError("storage compatibility")
        if type(release["size"]) is not int or not 0 < release["size"] <= MAX_DOWNLOAD:
            raise ValueError("size")
        if not re.fullmatch(r"[0-9a-f]{64}", release["sha256"]):
            raise ValueError("hash")
        expected = (f"https://github.com/{config.REPOSITORY}/releases/download/v{release['version']}/"
                    f"FileSearch-update-{release['version']}-win64.zip")
        if release["url"] != expected:
            raise ValueError("release URL")
        return release
    except Exception as error:
        raise UpdateError("정식 업데이트인지 확인할 수 없어요.") from error


def require_https(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.hostname not in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}):
        raise UpdateError("허용되지 않은 업데이트 주소예요.")


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    require_https(url)
    opener = urllib.request.build_opener(HTTPSRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "FileSearch/" + config.VERSION,
                                                 "Accept-Encoding": "identity"})
    return opener.open(request, timeout=10)


def fetch_manifest():
    with open_url(config.MANIFEST_URL) as response:
        raw = response.read(MAX_MANIFEST + 1)
    verify_manifest(raw)
    return raw


def file_hash(path, stop=lambda: False):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(CHUNK):
            check_cancel(stop)
            result.update(chunk)
    return result.hexdigest()


def verify_archive(path, release, stop=lambda: False):
    if path.stat().st_size != release["size"] or file_hash(path, stop) != release["sha256"]:
        raise UpdateError("업데이트 파일 검증에 실패했어요.")


def download(release, destination, progress=lambda *args: None, stop=lambda: False):
    """Only the verified complete file receives the final name; .part is disposable."""
    destination = Path(destination)
    temporary = destination.with_suffix(".part")
    deadline = time.monotonic() + 3600
    try:
        check_cancel(stop)
        with open_url(release["url"]) as response, temporary.open("wb") as output:
            count = 0
            while True:
                check_cancel(stop)
                if time.monotonic() > deadline:
                    raise UpdateError("업데이트 다운로드 시간이 초과됐어요.")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                count += len(chunk)
                if count > release["size"]:
                    raise UpdateError("업데이트 파일 크기가 달라요.")
                output.write(chunk)
                progress(count, release["size"])
            output.flush()
            os.fsync(output.fileno())
        verify_archive(temporary, release, stop)
        check_cancel(stop)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def safe_members(archive):
    entries = archive.infolist()
    if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_UNPACKED:
        raise UpdateError("압축 파일의 허용 크기를 넘었어요.")
    seen, files = set(), set()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for entry in entries:
        name = entry.filename.rstrip("/")
        parts = name.split("/")
        if (not name or "\\" in name or any(not p or p in (".", "..") or p.endswith((".", " "))
                or re.search(r'[<>:"|?*\x00-\x1f]', p) or p.split(".")[0].upper() in reserved for p in parts)
                or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
            raise UpdateError("안전하지 않은 압축 경로예요.")
        key = name.casefold()
        if key in seen:
            raise UpdateError("중복된 압축 경로예요.")
        seen.add(key)
        if not entry.is_dir():
            files.add(key)
    for key in seen:
        if any(str(p) in files for p in PurePosixPath(key).parents if str(p) != "."):
            raise UpdateError("압축 경로가 충돌해요.")
    return entries


def unpack(archive_path, destination, release, stop=lambda: False):
    """Destination must be a newly created, empty directory owned by the updater."""
    destination = Path(destination)
    if destination.is_symlink() or destination.is_junction() or any(destination.iterdir()):
        raise UpdateError("빈 업데이트 폴더가 필요해요.")
    with zipfile.ZipFile(archive_path) as archive:
        entries = safe_members(archive)
        names = {e.filename for e in entries}
        if not {"FileSearchApp.exe", "release.json"} <= names or not any(n.startswith("_internal/") for n in names):
            raise UpdateError("필수 프로그램 파일이 없어요.")
        if archive.getinfo("release.json").file_size > MAX_MANIFEST:
            raise UpdateError("잘못된 배포 정보예요.")
        metadata = json.loads(archive.read("release.json"))
        if metadata != {"version": release["version"], "data_schema": config.DATA_SCHEMA,
                        "launcher_protocol": config.LAUNCHER_PROTOCOL}:
            raise UpdateError("프로그램 버전 정보가 일치하지 않아요.")
        for entry in entries:
            check_cancel(stop)
            output = destination.joinpath(*entry.filename.rstrip("/").split("/"))
            if entry.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, output.open("xb") as target:
                while chunk := source.read(CHUNK):
                    check_cancel(stop)
                    target.write(chunk)
