"""Release authenticity, interrupted downloads, safe extraction and startup rollback."""
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from updater import config, protocol
from updater.launcher import await_ready, run_session
from updater.storage import Layout, atomic_write, install_lock, json_bytes


class FakeProcess:
    def __init__(self, alive=False):
        self.alive = alive
        self.terminated = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False
        self.terminated = True

    def wait(self, timeout=None):
        self.alive = False
        return 0


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="filesearch-updates-", dir=os.environ.get("FILESEARCH_TEST_TEMP"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.layout = Layout(self.root)
        self.key = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.key.public_key().public_bytes_raw()).decode()
        self.addCleanup(patch.stopall)
        patch.object(config, "PUBLIC_KEY", self.public).start()
        old = self.layout.version_dir(config.VERSION)
        old.mkdir()
        (old / "FileSearchApp.exe").write_bytes(b"original")
        self.state = self.layout.read_state()
        self.version = "0.3.0"

    def signed(self, **changes):
        release = dict(schema=1, version=self.version, launcher_protocol=1, data_schema=1,
                       url=f"https://github.com/{config.REPOSITORY}/releases/download/v{self.version}/FileSearch-update-{self.version}-win64.zip",
                       size=3, sha256=hashlib.sha256(b"zip").hexdigest())
        release.update(changes)
        payload = json_bytes(release)
        raw = json_bytes({"payload": base64.b64encode(payload).decode(),
                          "signature": base64.b64encode(self.key.sign(payload)).decode()})
        return raw, release

    def package(self, entries=None):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            if entries is None:
                archive.writestr("FileSearchApp.exe", b"new executable")
                archive.writestr("_internal/lib.dll", b"library")
                archive.writestr("release.json", json_bytes({"version": self.version, "data_schema": 1, "launcher_protocol": 1}))
            else:
                for name, data in entries:
                    archive.writestr(name, data)
        data = content.getvalue()
        raw, release = self.signed(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        path = self.layout.archive_path(release)
        path.write_bytes(data)
        return raw, release, path

    def pending(self):
        raw, release, path = self.package()
        atomic_write(self.layout.pending_path, raw)
        return raw, release, path

    def test_signed_release_accepted(self):
        raw, release = self.signed()
        self.assertEqual(protocol.verify_manifest(raw), release)

    def test_payload_tamper_and_wrong_key_rejected(self):
        raw, _ = self.signed()
        envelope = json.loads(raw)
        payload = json.loads(base64.b64decode(envelope["payload"]))
        payload["version"] = "9.0.0"
        envelope["payload"] = base64.b64encode(json_bytes(payload)).decode()
        with self.assertRaises(protocol.UpdateError):
            protocol.verify_manifest(json_bytes(envelope))
        other = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()
        with self.assertRaises(protocol.UpdateError):
            protocol.verify_manifest(raw, other)

    def test_unsigned_malformed_or_oversize_manifest_rejected(self):
        for raw in (b'{}', b'invalid', b' ' * (protocol.MAX_MANIFEST + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(protocol.UpdateError):
                protocol.verify_manifest(raw)

    def test_signed_but_incompatible_release_rejected(self):
        for change in ({"data_schema": 2}, {"launcher_protocol": 2}, {"size": -1}, {"size": True},
                       {"url": "https://evil.example/update.zip"}, {"sha256": "abc"}, {"version": "../evil"}):
            with self.subTest(change=change), self.assertRaises(protocol.UpdateError):
                protocol.verify_manifest(self.signed(**change)[0])

    def test_versions_compare_numerically_and_reject_ambiguous_names(self):
        self.assertGreater(protocol.version_tuple("0.10.0"), protocol.version_tuple("0.9.9"))
        for version in ("01.2.3", "1.0", "1.0.0-beta", "../1.0.0", 1, "1.0.0\n"):
            with self.assertRaises(protocol.UpdateError):
                protocol.version_tuple(version)

    def test_http_and_untrusted_redirects_rejected(self):
        for url in ("http://github.com/x", "file:///a", "https://evil.example/x", "https://user@github.com/x"):
            with self.assertRaises(protocol.UpdateError):
                protocol.require_https(url)
        protocol.require_https("https://release-assets.githubusercontent.com/asset?signature=example")

    def test_download_is_verified_before_publication(self):
        raw, release = self.signed()
        path = self.layout.archive_path(release)
        reports = []
        with patch.object(protocol, "open_url", return_value=io.BytesIO(b"zip")):
            protocol.download(release, path, lambda *args: reports.append(args))
        self.assertEqual(path.read_bytes(), b"zip")
        self.assertEqual(reports, [(3, 3)])
        self.assertFalse(path.with_suffix(".part").exists())

    def test_truncated_corrupt_and_oversize_downloads_leave_no_final_file(self):
        _, release = self.signed()
        for data in (b"zi", b"bad", b"zip-more"):
            path = self.layout.archive_path(release)
            with patch.object(protocol, "open_url", return_value=io.BytesIO(data)), self.assertRaises(protocol.UpdateError):
                protocol.download(release, path)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix(".part").exists())

    def test_download_cancellation_preserves_existing_file(self):
        _, release = self.signed()
        path = self.layout.archive_path(release)
        path.write_bytes(b"existing")
        with self.assertRaises(protocol.Cancelled):
            protocol.download(release, path, stop=lambda: True)
        self.assertEqual(path.read_bytes(), b"existing")

    def test_cancellation_mid_download_removes_partial_file(self):
        data = b"a" * (protocol.CHUNK * 2)
        _, release = self.signed(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        path = self.layout.archive_path(release)
        stopped = []
        with patch.object(protocol, "open_url", return_value=io.BytesIO(data)), self.assertRaises(protocol.Cancelled):
            protocol.download(release, path, lambda *args: stopped.append(True), lambda: bool(stopped))
        self.assertFalse(path.exists())
        self.assertFalse(path.with_suffix(".part").exists())

    def test_safe_package_extracts_and_matches_version(self):
        _, release, path = self.package()
        destination = self.root / "extract"
        destination.mkdir()
        protocol.unpack(path, destination, release)
        self.assertEqual((destination / "FileSearchApp.exe").read_bytes(), b"new executable")

    def test_zip_traversal_windows_devices_and_case_collisions_rejected(self):
        bad_names = ("../escape", "/escape", "C:/escape", "a\\escape", "a:stream", "a/CON.txt", "a/trailing.", "a//b")
        for name in bad_names:
            _, release, path = self.package([(name, b"evil")])
            destination = self.root / "extract"
            destination.mkdir(exist_ok=True)
            with self.subTest(name=name), self.assertRaises(protocol.UpdateError):
                protocol.unpack(path, destination, release)
            self.assertFalse(any(destination.iterdir()))
        for entries in ((('A.txt', b'a'), ('a.txt', b'b')), (('a', b'a'), ('a/b', b'b'))):
            _, release, path = self.package(entries)
            with self.assertRaises(protocol.UpdateError):
                protocol.unpack(path, destination, release)

    def test_zip_symlinks_and_expansion_limit_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "../outside")
        with zipfile.ZipFile(data) as archive, self.assertRaises(protocol.UpdateError):
            protocol.safe_members(archive)
        _, _, path = self.package()
        with patch.object(protocol, "MAX_UNPACKED", 1), zipfile.ZipFile(path) as archive, self.assertRaises(protocol.UpdateError):
            protocol.safe_members(archive)

    def test_activation_preserves_previous_and_user_data(self):
        self.pending()
        user_data = self.root / "documents.txt"
        user_data.write_text("untouched")
        next_state = self.layout.activate_pending(self.state)
        self.assertEqual(next_state["active"], self.version)
        self.assertEqual(next_state["previous"], config.VERSION)
        self.assertFalse(next_state["attempting"])
        self.assertEqual((self.layout.version_dir(config.VERSION) / "FileSearchApp.exe").read_bytes(), b"original")
        self.assertEqual(user_data.read_text(), "untouched")

    def test_changed_download_rejected_at_activation(self):
        _, _, path = self.pending()
        path.write_bytes(b"tampered")
        with self.assertRaises(protocol.UpdateError):
            self.layout.activate_pending(self.state)
        self.assertEqual(self.layout.read_state(), self.state)

    def test_cancelled_extraction_leaves_previous_active(self):
        self.pending()
        with patch("updater.storage.unpack", side_effect=protocol.Cancelled()), self.assertRaises(protocol.Cancelled):
            self.layout.activate_pending(self.state)
        self.assertEqual(self.layout.read_state(), self.state)
        self.assertEqual(list(self.layout.staging.iterdir()), [])

    def test_state_write_failure_retries_already_extracted_version(self):
        self.pending()
        with patch.object(self.layout, "save_state", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.layout.activate_pending(self.state)
        self.assertEqual(self.layout.read_state(), self.state)
        self.assertTrue(self.layout.pending_path.exists())
        self.assertEqual(self.layout.activate_pending(self.state)["active"], self.version)

    def test_no_downgrade_or_retry_of_failed_version(self):
        self.pending()
        state = dict(self.state, active="9.0.0")
        self.assertEqual(self.layout.activate_pending(state), state)
        self.pending()
        state = dict(self.state, failed=[self.version])
        self.assertEqual(self.layout.activate_pending(state), state)

    def test_cleanup_retains_previous_and_unmanaged_folders(self):
        self.pending()
        state = self.layout.activate_pending(self.state)
        older = self.layout.version_dir("0.1.0")
        older.mkdir()
        (older / "FileSearchApp.exe").write_bytes(b"obsolete")
        unmanaged = self.layout.versions / "user-notes"
        unmanaged.mkdir()
        (unmanaged / "note.txt").write_text("keep")
        state = dict(state, trial=None, installed=["0.1.0", config.VERSION, self.version])
        result = self.layout.cleanup(state)
        self.assertFalse(older.exists())
        self.assertTrue(self.layout.version_dir(config.VERSION).exists())
        self.assertTrue(self.layout.version_dir(self.version).exists())
        self.assertTrue((unmanaged / "note.txt").exists())
        self.assertEqual(result["installed"], [config.VERSION, self.version])
    def test_first_launch_success_commits_trial(self):
        self.pending()
        seen = []
        def start(layout, state, ack, token, *args):
            seen.append(state["active"])
            atomic_write(ack, json_bytes({"version": state["active"], "token": token}))
            return FakeProcess()
        run_session(self.layout, start=start)
        self.assertEqual(seen, [self.version])
        self.assertIsNone(self.layout.read_state()["trial"])

    def test_download_applied_on_exit_is_tried_on_next_launch(self):
        def start(layout, state, ack, token, *args):
            self.pending()
            atomic_write(ack, json_bytes({"version": state["active"], "token": token}))
            return FakeProcess()
        run_session(self.layout, start=start)
        self.assertEqual(self.layout.read_state()["trial"], self.version)
        seen = []
        def next_start(layout, state, ack, token, *args):
            seen.append(state["active"])
            atomic_write(ack, json_bytes({"version": state["active"], "token": token}))
            return FakeProcess()
        run_session(self.layout, start=next_start)
        self.assertEqual(seen, [self.version])

    def test_failed_start_rolls_back_and_blocks_same_release(self):
        self.pending()
        seen = []
        def start(layout, state, ack, token, *args):
            seen.append(state["active"])
            if state["active"] == config.VERSION:
                atomic_write(ack, json_bytes({"version": state["active"], "token": token}))
            return FakeProcess()
        run_session(self.layout, start=start)
        self.assertEqual(seen, [self.version, config.VERSION])
        state = self.layout.read_state()
        self.assertEqual(state["active"], config.VERSION)
        self.assertIn(self.version, state["failed"])

    def test_restart_request_runs_new_version_after_old_app_exits(self):
        seen = []
        def start(layout, state, ack, token, *args):
            seen.append(state["active"])
            if len(seen) == 1:
                self.pending()
                atomic_write(layout.work / ("restart-" + token), b"restart")
            atomic_write(ack, json_bytes({"version": state["active"], "token": token}))
            return FakeProcess()
        run_session(self.layout, start=start)
        self.assertEqual(seen, [config.VERSION, self.version])
        self.assertIsNone(self.layout.read_state()["trial"])

    def test_unresponsive_trial_process_stopped_before_rollback(self):
        self.pending()
        processes = []
        def start(layout, state, ack, token, *args):
            process = FakeProcess(alive=state["active"] == self.version)
            processes.append(process)
            return process
        run_session(self.layout, start=start, ready=lambda process, *args: not process.alive)
        self.assertTrue(processes[0].terminated)
        self.assertEqual(self.layout.read_state()["active"], config.VERSION)

    def test_crashed_launcher_trial_is_rolled_back_next_time(self):
        self.pending()
        state = self.layout.activate_pending(self.state)
        self.layout.save_state(dict(state, attempting=True))
        seen = []
        def start(layout, state, ack, token, *args):
            seen.append(state["active"])
            atomic_write(ack, json_bytes({"version": state["active"], "token": token}))
            return FakeProcess()
        run_session(self.layout, start=start)
        self.assertEqual(seen, [config.VERSION])

    def test_ack_requires_current_nonce_and_version_and_times_out(self):
        path = self.layout.work / "ack.json"
        atomic_write(path, json_bytes({"token": "wrong", "version": config.VERSION}))
        self.assertFalse(await_ready(FakeProcess(), path, "right", config.VERSION))
        process = FakeProcess(alive=True)
        self.assertFalse(await_ready(process, path, "right", config.VERSION, timeout=0.01))

    @unittest.skipUnless(os.name == "nt", "Windows installation lock")
    def test_second_launcher_cannot_acquire_same_install_lock(self):
        with install_lock(self.layout):
            with self.assertRaises(protocol.UpdateError):
                with install_lock(self.layout):
                    self.fail("Concurrent launch allowed")
        with install_lock(self.layout):
            pass


if __name__ == "__main__":
    unittest.main()
