"""빌드 전에 OCR 번들의 누락·변조·언어 모델 누락을 검사해요."""

import hashlib
import json
from pathlib import Path


def verify_bundle(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["files"]
    required = {"tesseract.exe", "tessdata/kor.traineddata", "tessdata/eng.traineddata"}
    if not required <= entries.keys():
        raise RuntimeError("OCR 실행파일 또는 한국어·영어 모델이 manifest에 없어요.")
    for name, expected in entries.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            raise RuntimeError("OCR manifest에 잘못된 경로가 있어요.")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"OCR 배포 파일이 없거나 변경됐어요: {name}")
    return len(entries)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(f"OCR bundle verified: {verify_bundle(root / 'vendor/tesseract')} files")
