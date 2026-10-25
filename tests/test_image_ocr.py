"""실제 내장 OCR·캐시 재사용·수정/오류/취소 및 원본 보존을 검사해요."""

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from PIL import Image

from ocr import IMAGE_EXTENSIONS
from ocr import reader
from ocr.reader import OCRError, extract_image_body
from ocr_fixtures import save_image, text_image
from searcher.body_extractors import extract_file_body
from searcher.metadata import SearchCancelled
from searcher.search_pipeline import SearchRequest, run
from tagger import storage


@unittest.skipUnless(os.name == "nt", "Bundled Windows OCR")
class ImageOCRTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="filesearch-ocr-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "한글 경로 & 폴더"
        self.source.mkdir()
        self.db = self.root / "cache.sqlite3"

    def file(self, name="이미지.png", text=None):
        return save_image(self.source / name, text)

    def search(self, query="계약금", **options):
        settings = dict(root=str(self.source), query=query, name_enabled=False, body_enabled=True, cache_path=str(self.db))
        settings.update(options)
        return run(SearchRequest(**settings))

    def rows(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute("SELECT * FROM body_cache ORDER BY path")]

    def test_all_supported_formats_read_korean_english_and_reuse_cache(self):
        files = [self.file(f"문서.{ext}") for ext in sorted(IMAGE_EXTENSIONS)]
        before = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in files}
        first = self.search()
        self.assertEqual({hit.path for hit in first.hits}, {str(path) for path in files}, first.errors)
        self.assertEqual((first.refreshed, first.unsupported, first.errors), (len(files), 0, []))
        self.assertTrue(all("Invoice" in row["body"] and row["status"] == "ready" for row in self.rows()))
        with patch.object(reader, "_recognize", side_effect=AssertionError("Unchanged images must not run OCR")):
            second = self.search("Invoice")
        self.assertEqual((len(second.hits), second.refreshed, second.reused), (len(files), 0, len(files)))
        self.assertEqual(before, {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files})

    def test_only_changed_image_is_reread_by_date_or_size(self):
        a, b = self.file("a.png"), self.file("b.png")
        self.search()
        stamp = a.stat().st_mtime_ns
        self.file("a.png", "납품 완료\nDelivery complete")
        os.utime(a, ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
        with patch.object(reader, "_recognize", wraps=reader._recognize) as recognize:
            result = self.search("Delivery")
        self.assertEqual(recognize.call_count, 1)
        self.assertEqual((result.refreshed, result.reused), (1, 1))
        self.assertEqual([hit.path for hit in result.hits], [str(a)])
        stamp = a.stat().st_mtime_ns
        a.write_bytes(a.read_bytes() + b"metadata-size-change")
        os.utime(a, ns=(stamp, stamp))
        self.assertEqual(self.search("Delivery").refreshed, 1)
        self.assertEqual([hit.path for hit in self.search().hits], [str(b)])

    def test_corrupt_change_invalidates_old_text_and_retry_recovers(self):
        image = self.file()
        good = image.read_bytes()
        self.search()
        image.write_bytes(b"corrupt image")
        (self.source / "normal.txt").write_text("계약금", encoding="utf-8")
        result = self.search()
        self.assertEqual(len(result.errors), 1)
        self.assertEqual([Path(hit.path).suffix for hit in result.hits], [".txt"])
        row = next(row for row in self.rows() if row["path"] == str(image))
        self.assertEqual((row["status"], row["body"]), ("error", None))
        image.write_bytes(good)
        self.assertEqual(len(self.search().hits), 2)

    def test_transparent_png_uses_white_background(self):
        path = self.source / "transparent.png"
        text_image(transparent=True).save(path)
        self.assertIn("계약금", extract_file_body(path))

    def test_exif_rotation_and_multi_page_tiff(self):
        path = self.source / "rotated.jpg"
        image = text_image().rotate(90, expand=True)
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, quality=95, exif=exif)
        self.assertIn("계약금", extract_file_body(path))
        tiff = self.source / "pages.tiff"
        text_image().save(tiff, save_all=True, append_images=[text_image("납품 완료\nDelivery complete")])
        body = extract_file_body(tiff)
        self.assertIn("계약금", body)
        self.assertIn("Delivery", body)

    def test_blank_image_cached_as_ready_without_repeated_ocr(self):
        Image.new("RGB", (300, 300), "white").save(self.source / "blank.png")
        self.assertFalse(self.search().hits)
        self.assertEqual((self.rows()[0]["body"], self.rows()[0]["status"]), ("", "ready"))
        with patch.object(reader, "_recognize", side_effect=AssertionError("Blank ready cache must be reused")):
            self.assertEqual(self.search().reused, 1)

    def test_image_size_page_and_animation_limits_are_errors(self):
        path = self.file()
        with patch.object(reader, "MAX_PIXELS", 100), self.assertRaises(OCRError):
            extract_image_body(path)
        with patch.object(reader, "MAX_FILE_BYTES", 1), self.assertRaises(OCRError):
            extract_image_body(path)
        tiff = self.source / "pages.tif"
        text_image().save(tiff, save_all=True, append_images=[text_image("other")])
        with patch.object(reader, "MAX_PAGES", 1), self.assertRaises(OCRError):
            extract_image_body(tiff)
        webp = self.source / "animation.webp"
        text_image().save(webp, save_all=True, append_images=[text_image("other")], duration=100, loop=0)
        with self.assertRaisesRegex(OCRError, "움직이는"):
            extract_image_body(webp)

    def test_missing_runtime_reports_error_and_recovers_without_system_install(self):
        path = self.file()
        with patch.object(reader, "runtime_directory", return_value=self.root / "not-installed"):
            result = self.search()
        self.assertFalse(result.hits)
        self.assertIn("배포 폴더", result.errors[0][1])
        self.assertIsNone(self.rows()[0]["body"])
        self.assertEqual(self.search().refreshed, 1)
        with patch.object(reader, "runtime_directory", return_value=self.root / "not-installed"):
            self.assertEqual(len(self.search().hits), 1)

    def test_name_tag_and_type_filters_do_not_invoke_ocr(self):
        path = self.file("계약금.png")
        storage.attach_tags([str(path)], ["계약금"], db_path=self.db)
        with patch.object(reader, "_recognize", side_effect=AssertionError("OCR must not run")):
            self.assertEqual(len(self.search(body_enabled=False, name_enabled=True).hits), 1)
            self.assertEqual(len(self.search(body_enabled=False, tag_enabled=True).hits), 1)
            self.assertFalse(self.search(extensions={"txt"}).hits)

    def test_tags_and_existing_text_cache_survive_ocr(self):
        path = self.file()
        txt = self.source / "text.txt"
        txt.write_text("계약금", encoding="utf-8")
        self.search(extensions={"txt"})
        before = self.rows()[0]
        storage.attach_tags([str(path)], ["보관"], db_path=self.db)
        result = self.search()
        self.assertEqual((result.refreshed, result.reused), (1, 1))
        self.assertEqual(storage.read_file_tags([str(path)], self.db)[str(path)], ("보관",))
        self.assertEqual(next(row for row in self.rows() if row["path"] == str(txt)), before)

    def test_live_cancellation_kills_ocr_process_and_retries_pending_cache(self):
        self.file()
        processes = []
        real_popen = subprocess.Popen
        def start(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append((process, time.monotonic()))
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)
            return process
        def stop():
            return bool(processes) and time.monotonic() - processes[0][1] >= 0.03
        with patch.object(reader.subprocess, "Popen", start):
            result = run(SearchRequest(str(self.source), "계약금", False, True, cache_path=str(self.db)), should_stop=stop)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.hits, [])
        self.assertTrue(processes and all(p.poll() is not None for p, _ in processes))
        self.assertEqual(self.rows()[0]["status"], "pending")
        self.assertEqual(len(self.search().hits), 1)

    def test_timeout_kills_process_and_does_not_return_partial_text(self):
        png = reader._image_png(text_image())
        processes = []
        real_popen = subprocess.Popen
        def start(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(reader.subprocess, "Popen", start), self.assertRaises(OCRError):
            reader._recognize(png, reader.runtime_directory(), time.monotonic() + 0.02, lambda: False)
        self.assertTrue(processes and all(p.poll() is not None for p in processes))

    def test_failed_engine_does_not_report_empty_success(self):
        with self.assertRaises(OCRError):
            reader._recognize(b"invalid png", reader.runtime_directory(), time.monotonic() + 10, lambda: False)

    def test_cancel_before_read_never_launches_engine(self):
        with patch.object(reader.subprocess, "Popen") as popen, self.assertRaises(SearchCancelled):
            extract_image_body(self.source / "not-needed.png", should_stop=lambda: True)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
