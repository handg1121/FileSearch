"""로컬 OCR 실행. 원본 파일과 시스템 설치/PATH를 변경하지 않아요."""

from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageOps

from searcher.metadata import check_cancelled

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PAGES = 100
MAX_TEXT_CHARS = 4 * 1024 * 1024
OCR_TIMEOUT_SECONDS = 120
POLL_SECONDS = 0.1


class OCRError(RuntimeError):
    pass


def runtime_directory():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ocr_runtime"
    return Path(__file__).resolve().parents[1] / "vendor" / "tesseract"


def _check_deadline(deadline, should_stop):
    check_cancelled(should_stop)
    if time.monotonic() >= deadline:
        raise OCRError("이미지 글자 인식 시간이 120초를 초과했어요. 이미지 크기나 페이지 수를 줄여 주세요.")


def _recognize(png, runtime, deadline, should_stop):
    _check_deadline(deadline, should_stop)
    # 상대 tessdata 경로와 표준 입력을 사용해 한글 경로도 처리해요.
    command = [str(runtime / "tesseract.exe"), "stdin", "stdout",
               "--tessdata-dir", "tessdata", "-l", "kor+eng", "--oem", "1", "--psm", "6"]
    env = os.environ.copy()
    env.pop("TESSDATA_PREFIX", None)
    env["OMP_THREAD_LIMIT"] = "1"
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(map(str, (runtime, windows / "System32", windows)))
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(command, cwd=runtime, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    try:
        data = png
        while True:
            _check_deadline(deadline, should_stop)
            try:
                output, error = process.communicate(input=data, timeout=POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                data = None
        _check_deadline(deadline, should_stop)
        if process.returncode:
            detail = error.decode("utf-8", errors="replace").strip()[-1500:]
            raise OCRError(f"이미지 글자 인식에 실패했어요: {detail or process.returncode}")
        text = output.decode("utf-8")
        if len(text) > MAX_TEXT_CHARS:
            raise OCRError("이미지에서 추출한 글자 수가 처리 한도를 초과했어요.")
        return text.strip()
    finally:
        # 취소/시간 초과에도 OCR 자식 프로세스를 남기지 않아요.
        if process.poll() is None:
            process.kill()
        process.communicate()


def _image_png(image):
    image = ImageOps.exif_transpose(image)
    if "A" in image.getbands() or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        image = white
    gray = ImageOps.grayscale(image)
    output = BytesIO()
    gray.save(output, format="PNG", dpi=(300, 300), compress_level=1)
    return output.getvalue()


def extract_image_body(path, *, should_stop=lambda: False):
    """한국어·영어 글자를 반환해요. TIFF는 모든 페이지를 순서대로 읽어요."""
    check_cancelled(should_stop)
    runtime = runtime_directory()
    required = ("tesseract.exe", "tessdata/kor.traineddata", "tessdata/eng.traineddata")
    if not all((runtime / name).is_file() for name in required):
        raise OCRError("프로그램에 포함된 OCR 파일이 없어요. FileSearch 배포 폴더 전체를 다시 복사해 주세요.")
    if Path(path).stat().st_size > MAX_FILE_BYTES:
        raise OCRError("이미지 파일이 처리 한도(64 MiB)를 초과했어요.")
    deadline = time.monotonic() + OCR_TIMEOUT_SECONDS
    pieces, length = [], 0
    try:
        with Image.open(path, formats=("PNG", "JPEG", "BMP", "TIFF", "WEBP")) as document:
            pages = getattr(document, "n_frames", 1)
            if pages > 1 and document.format != "TIFF":
                raise OCRError("움직이는 이미지는 아직 지원하지 않아요. 정지 이미지로 저장해 주세요.")
            if pages > MAX_PAGES:
                raise OCRError("TIFF가 처리 한도(100페이지)를 초과했어요.")
            for index in range(pages):
                _check_deadline(deadline, should_stop)
                document.seek(index)
                if document.width * document.height > MAX_PIXELS:
                    raise OCRError("이미지 한 페이지가 처리 한도(4,000만 화소)를 초과했어요.")
                png = _image_png(document)
                _check_deadline(deadline, should_stop)
                text = _recognize(png, runtime, deadline, should_stop)
                length += len(text) + 1
                if length > MAX_TEXT_CHARS:
                    raise OCRError("이미지에서 추출한 글자 수가 처리 한도를 초과했어요.")
                pieces.append(text)
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise OCRError(f"이미지를 읽을 수 없어요: {error}") from error
    return "\n".join(pieces)
