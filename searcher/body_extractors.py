"""HWP 5.x / HWPX / TXT에서 검색할 글자를 추출해요. 외부 앱을 실행하지 않아요."""

from pathlib import Path
import re
import struct
import unicodedata
from xml.etree import ElementTree
from zipfile import ZipFile
import zlib

import olefile

from searcher.metadata import check_cancelled

SUPPORTED_EXTENSIONS = frozenset({"hwp", "hwpx", "txt"})
EXTRACTOR_VERSION = 1
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_BODY_CHARS = 32 * 1024 * 1024


class ExtractionError(Exception):
    pass


def _bounded_read(stream):
    data = stream.read(MAX_STREAM_BYTES + 1)
    if len(data) > MAX_STREAM_BYTES:
        raise ExtractionError("본문 데이터가 처리 한도(64 MiB)를 초과했어요.")
    return data


def _decode_hwp_text(data):
    """8 UTF-16 단위인 인라인/확장 제어 정보를 글자로 오인하지 않아요."""
    if len(data) % 2:
        raise ExtractionError("HWP 문단 텍스트가 손상됐어요.")
    output = bytearray()
    pos = 0
    while pos < len(data):
        char = struct.unpack_from("<H", data, pos)[0]
        if 1 <= char <= 23 and char not in (10, 13):
            if pos + 16 > len(data):
                raise ExtractionError("HWP 제어 정보가 잘렸어요.")
            if char == 9:
                output.extend(b"\t\x00")
            pos += 16
        else:
            if char >= 32:
                output.extend(data[pos:pos + 2])
            elif char in (10, 13):
                output.extend(b"\n\x00")
            elif char in (30, 31):
                output.extend(b" \x00")
            elif char == 24:
                output.extend(b"-\x00")
            pos += 2
    return output.decode("utf-16-le")


def extract_hwp_section(data, should_stop=lambda: False):
    """구역 내 모든 문단 텍스트 레코드를 읽어 표/글상자 안의 글자도 포함해요."""
    paragraphs = []
    pos = 0
    while pos < len(data):
        check_cancelled(should_stop)
        if pos + 4 > len(data):
            raise ExtractionError("HWP 레코드 헤더가 잘렸어요.")
        header = struct.unpack_from("<I", data, pos)[0]
        tag, length = header & 0x3FF, header >> 20
        pos += 4
        if length == 0xFFF:
            if pos + 4 > len(data):
                raise ExtractionError("HWP 확장 레코드 헤더가 잘렸어요.")
            length = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        if pos + length > len(data):
            raise ExtractionError("HWP 레코드 내용이 잘렸어요.")
        if tag == 67:  # HWPTAG_PARA_TEXT
            paragraphs.append(_decode_hwp_text(data[pos:pos + length]).rstrip("\n"))
        pos += length
    return "\n".join(paragraphs)


def _hwp(path, should_stop):
    with olefile.OleFileIO(path) as document:
        header = _bounded_read(document.openstream("FileHeader"))
        if len(header) < 40 or not header.startswith(b"HWP Document File\x00") or header[35] != 5:
            raise ExtractionError("HWP 5.x 형식만 지원해요.")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 2:
            raise ExtractionError("암호가 설정된 HWP는 본문을 읽을 수 없어요.")
        if flags & 4:
            raise ExtractionError("배포용 HWP 본문 추출은 아직 지원하지 않아요.")
        sections = [parts for parts in document.listdir() if len(parts) == 2
                    and parts[0] == "BodyText" and re.fullmatch(r"Section\d+", parts[1])]
        if not sections:
            raise ExtractionError("HWP 본문 구역을 찾을 수 없어요.")
        result = []
        length = 0
        for section in sorted(sections, key=lambda parts: int(parts[1][7:])):
            check_cancelled(should_stop)
            data = _bounded_read(document.openstream(section))
            if flags & 1:
                decompressor = zlib.decompressobj(-15)
                data = decompressor.decompress(data, MAX_STREAM_BYTES + 1)
                if len(data) > MAX_STREAM_BYTES or not decompressor.eof:
                    raise ExtractionError("HWP 압축 본문이 너무 크거나 손상됐어요.")
            text = extract_hwp_section(data, should_stop)
            length += len(text)
            if length > MAX_BODY_CHARS:
                raise ExtractionError("본문 글자 수가 처리 한도를 초과했어요.")
            result.append(text)
        return "\n".join(result)


class _HwpxTextTarget:
    """XML 이벤트 순서를 유지해 탭 앞뒤 글자도 순서대로 읽어요."""

    def __init__(self, should_stop):
        self.should_stop = should_stop
        self.pieces = []
        self.length = 0
        self.text_depth = 0

    def append(self, text):
        self.length += len(text)
        if self.length > MAX_BODY_CHARS:
            raise ExtractionError("본문 글자 수가 처리 한도를 초과했어요.")
        self.pieces.append(text)

    def start(self, tag, attributes):
        check_cancelled(self.should_stop)
        local = tag.rsplit("}", 1)[-1]
        if local == "t":
            self.text_depth += 1
        elif local in ("tab", "lineBreak"):
            self.append("\t" if local == "tab" else "\n")

    def end(self, tag):
        local = tag.rsplit("}", 1)[-1]
        if local == "t":
            self.text_depth -= 1
        elif local == "p":
            self.append("\n")

    def data(self, text):
        if self.text_depth:
            self.append(text)

    def doctype(self, name, pubid, system):
        raise ExtractionError("DTD가 포함된 XML은 처리하지 않아요.")

    def close(self):
        return "".join(self.pieces)


def _hwpx(path, should_stop):
    with ZipFile(path) as document:
        sections = [name for name in document.namelist()
                    if re.fullmatch(r"Contents/section\d+\.xml", name)]
        if not sections:
            raise ExtractionError("HWPX 본문 구역을 찾을 수 없어요.")
        pieces = []
        length = 0
        for section in sorted(sections, key=lambda name: int(re.search(r"\d+", name).group())):
            check_cancelled(should_stop)
            if document.getinfo(section).file_size > MAX_STREAM_BYTES:
                raise ExtractionError("HWPX 본문 구역이 처리 한도를 초과했어요.")
            parser = ElementTree.XMLParser(target=_HwpxTextTarget(should_stop))
            with document.open(section) as stream:
                while chunk := stream.read(64 * 1024):
                    check_cancelled(should_stop)
                    parser.feed(chunk)
            text = parser.close()
            length += len(text)
            if length > MAX_BODY_CHARS:
                raise ExtractionError("본문 글자 수가 처리 한도를 초과했어요.")
            pieces.append(text)
        return "".join(pieces)


def _txt(path, should_stop):
    check_cancelled(should_stop)
    with open(path, "rb") as stream:
        data = _bounded_read(stream)
    check_cancelled(should_stop)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("텍스트 인코딩을 확인할 수 없어요. UTF-8, UTF-16, CP949를 지원해요.")


def extract_file_body(path, *, should_stop=lambda: False):
    """전체 본문 텍스트를 반환해요. 실패/취소를 빈 본문으로 바꾸지 않아요."""
    check_cancelled(should_stop)
    extension = Path(path).suffix.lower().lstrip(".")
    readers = {"hwp": _hwp, "hwpx": _hwpx, "txt": _txt}
    if extension not in readers:
        raise ExtractionError(f".{extension} 본문 검색은 아직 지원하지 않아요.")
    text = readers[extension](path, should_stop)
    check_cancelled(should_stop)
    if len(text) > MAX_BODY_CHARS:
        raise ExtractionError("본문 글자 수가 처리 한도를 초과했어요.")
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
