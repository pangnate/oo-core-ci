from __future__ import annotations

import base64
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import manage_v8_windows_sdk as sdk

REPO = "owner/native-deps"


def package_fixture(directory: Path, *, legacy: bool = False) -> tuple[dict, Path]:
    """Small file fixtures validate packaging only; they are not a native SDK."""
    lock = sdk.load_lock()
    root = directory / sdk.SDK_DIR
    (root / "include/libplatform").mkdir(parents=True)
    (root / "include/v8.h").write_bytes(b"fixture V8 public header\n")
    (root / "include/libplatform/libplatform.h").write_bytes(b"fixture platform header\n")
    (root / sdk.LIBRARY).parent.mkdir(parents=True)
    (root / sdk.LIBRARY).write_bytes(b"fixture library; not executable\n")
    with zipfile.ZipFile(root / "include-headers.zip", "w") as headers:
        for path in sorted((root / "include").rglob("*.h")):
            headers.write(path, path.relative_to(root / "include").as_posix())
    entries = []
    for entry_id, role, relative in (("v8-headers", "include", "include-headers.zip"),
                                     ("v8-monolith", "library", sdk.LIBRARY)):
        entries.append({"id": entry_id, "role": role, "status": "verified", "source": "test fixture",
                        "path": f"dist/{sdk.SDK_DIR}/{relative}" if legacy else relative,
                        "sha256": sdk.sha256_file(root / relative)})
    manifest = {"schemaVersion": 1, "sdkId": lock["sdkId"], "kind": "development", "platform": lock["platform"],
                "abi": lock["abi"], "entries": entries}
    provenance = {"schemaVersion": 1, "sdkId": lock["sdkId"], "coreRef": lock["coreRef"],
                  "buildToolsRef": lock["buildToolsRef"], "v8Ref": lock["v8"]["ref"],
                  "depotToolsRef": lock["depotTools"]["ref"], "gnArgs": lock["gnArgs"], "abi": lock["abi"],
                  "probe": {"source": "1 + 2", "expected": 3, "status": "passed"}}
    if not legacy:
        provenance["sdkLockSha256"] = sdk.identity(lock)["sdk-key"]
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    with zipfile.ZipFile(directory / sdk.ARCHIVE, "w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory).as_posix())
    digest = sdk.sha256_file(directory / sdk.ARCHIVE)
    (directory / sdk.CHECKSUM).write_text(f"{digest}  {sdk.ARCHIVE}\n", encoding="utf-8")
    receipt = {"schemaVersion": 1, "repository": REPO, "releaseTag": sdk.identity(lock)["release-tag"],
               "sdkLockSha256": sdk.identity(lock)["sdk-key"], "archive": sdk.ARCHIVE, "archiveSha256": digest}
    (directory / sdk.RECEIPT).write_text(json.dumps(receipt), encoding="utf-8")
    return lock, root


class V8SdkReuseTests(unittest.TestCase):
    def test_identity_ignores_json_order_but_not_abi_or_recipe_identity(self):
        lock = sdk.load_lock()
        self.assertEqual(sdk.identity(lock), sdk.identity(dict(reversed(list(lock.items())))))
        for field in ("abi", "sdkId"):
            changed = copy.deepcopy(lock)
            changed[field] += "-changed"
            self.assertNotEqual(sdk.identity(lock), sdk.identity(changed))
        changed = copy.deepcopy(lock)
        changed["gnArgs"]["v8_enable_pointer_compression"] = False
        self.assertNotEqual(sdk.identity(lock), sdk.identity(changed))

    def test_first_run_archive_is_relocatable_without_rewriting_original_bytes(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                lock, _ = package_fixture(directory, legacy=legacy)
                before = sdk.archive_hash(directory)
                restored = sdk.unpack(directory, directory / "elsewhere/sdk", lock)
                self.assertTrue((restored / sdk.LIBRARY).is_file())
                self.assertEqual(sdk.archive_hash(directory), before)
                with self.assertRaisesRegex(sdk.InputError, "already exists"):
                    sdk.unpack(directory, restored, lock)

    def test_archive_hash_and_extracted_header_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, root = package_fixture(directory)
            (root / "include/v8.h").write_bytes(b"modified header")
            with self.assertRaisesRegex(sdk.InputError, "header content mismatch"):
                sdk.validate_sdk(root, lock)
            with (directory / sdk.ARCHIVE).open("ab") as archive:
                archive.write(b"corrupt archive")
            with self.assertRaisesRegex(sdk.InputError, "SHA256 mismatch"):
                sdk.unpack(directory, directory / "refused", lock)
            self.assertFalse((directory / "refused").exists())

    def test_gn_version_abi_and_probe_mismatches_are_rejected(self):
        for field, replacement in (("gnArgs", {}), ("abi", "wrong-crt"), ("v8Ref", "0" * 40),
                                   ("probe", {"status": "unavailable"})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                lock, root = package_fixture(Path(temporary))
                path = root / "provenance.json"
                provenance = json.loads(path.read_text())
                provenance[field] = replacement
                path.write_text(json.dumps(provenance), encoding="utf-8")
                with self.assertRaisesRegex(sdk.InputError, "provenance"):
                    sdk.validate_sdk(root, lock)

    def test_bad_bundle_receipt_or_cache_is_never_a_silent_cache_miss(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, _ = package_fixture(directory)
            receipt = json.loads((directory / sdk.RECEIPT).read_text())
            receipt["sdkLockSha256"] = "0" * 64
            (directory / sdk.RECEIPT).write_text(json.dumps(receipt))
            with patch.object(sdk, "api") as remote, self.assertRaises(sdk.InputError):
                sdk.restore(REPO, directory, directory / "sdk", lock)
            remote.assert_not_called()
            self.assertFalse((directory / "sdk").exists())

    def test_missing_release_only_returns_missing_for_explicit_bootstrap(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(sdk, "api", return_value=None):
            directory = Path(temporary)
            with self.assertRaisesRegex(sdk.InputError, "fixed V8 SDK is missing"):
                sdk.restore(REPO, directory / "cache", directory / "out", sdk.load_lock())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(sdk.restore(REPO, directory / "cache", directory / "out", sdk.load_lock(),
                                             allow_missing=True))
            self.assertFalse((directory / "cache").exists())
            self.assertFalse((directory / "out").exists())

    def test_repository_rename_requires_matching_immutable_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, _ = package_fixture(directory)
            renamed = "owner/renamed-native-deps"
            original_receipt = (directory / sdk.RECEIPT).read_bytes()
            with patch.object(sdk, "api", return_value={"id": 123, "full_name": renamed}) as remote:
                sdk.validate_release_bundle(directory, lock, renamed)
                self.assertEqual(remote.call_args_list[0].args, (f"repos/{REPO}",))
                self.assertEqual(remote.call_args_list[1].args, (f"repos/{renamed}",))
            self.assertEqual(original_receipt, (directory / sdk.RECEIPT).read_bytes())
            for responses in (({"id": 124}, {"id": 123}), ({}, {}), (None, {"id": 123})):
                with self.subTest(responses=responses), patch.object(sdk, "api", side_effect=responses):
                    with self.assertRaisesRegex(sdk.InputError, "different repository"):
                        sdk.validate_release_bundle(directory, lock, renamed)

    def test_rename_does_not_bypass_lock_or_archive_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, _ = package_fixture(directory)
            receipt = json.loads((directory / sdk.RECEIPT).read_text())
            receipt["sdkLockSha256"] = "0" * 64
            (directory / sdk.RECEIPT).write_text(json.dumps(receipt))
            with patch.object(sdk, "api") as remote, self.assertRaisesRegex(sdk.InputError, "lock/archive"):
                sdk.validate_release_bundle(directory, lock, "owner/renamed-native-deps")
            remote.assert_not_called()

    def test_network_or_auth_errors_are_not_reported_as_missing_sdk(self):
        for message in ("HTTP 403", "HTTP 500", "connection timed out"):
            with self.subTest(message=message), patch.object(sdk, "gh", side_effect=sdk.InputError(message)):
                with self.assertRaises(sdk.InputError):
                    sdk.api("repos/owner/repo/releases/tags/sdk", missing_ok=True)
        with patch.object(sdk, "gh", side_effect=sdk.InputError("HTTP 404")):
            self.assertIsNone(sdk.api("repos/owner/repo/releases/tags/sdk", missing_ok=True))

    def test_archive_traversal_with_matching_outer_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, _ = package_fixture(directory)
            with zipfile.ZipFile(directory / sdk.ARCHIVE, "a") as archive:
                archive.writestr("../outside.txt", "not allowed")
            digest = sdk.sha256_file(directory / sdk.ARCHIVE)
            (directory / sdk.CHECKSUM).write_text(f"{digest}  {sdk.ARCHIVE}\n")
            with self.assertRaisesRegex(sdk.InputError, "unsafe archive member"):
                sdk.unpack(directory, directory / "out", lock)
            self.assertFalse((directory / "out").exists())
            self.assertFalse((directory / "outside.txt").exists())

    def test_restoring_from_cache_does_not_call_network_or_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, _ = package_fixture(directory)
            with patch.object(sdk, "gh") as remote, patch("build_v8_windows_sdk.main") as build:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(sdk.restore(REPO, directory, directory / "restored", lock))
            remote.assert_not_called()
            build.assert_not_called()
            self.assertTrue((directory / "restored" / sdk.RECEIPT).is_file())

    def test_cache_miss_downloads_fixed_release_once_and_warm_restore_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = directory / "original"
            original.mkdir()
            lock, _ = package_fixture(original)

            def download(*arguments):
                self.assertEqual(arguments[:2], ("release", "download"))
                self.assertEqual(arguments[2], sdk.identity(lock)["release-tag"])
                target = Path(arguments[arguments.index("--dir") + 1])
                for name in (sdk.ARCHIVE, sdk.CHECKSUM, sdk.RECEIPT):
                    shutil.copy2(original / name, target / name)
                return ""

            with patch.object(sdk, "api", return_value={"draft": False}) as remote:
                with patch.object(sdk, "gh", side_effect=download) as transfer:
                    with patch("build_v8_windows_sdk.main") as build, contextlib.redirect_stdout(io.StringIO()):
                        sdk.restore(REPO, directory / "cache", directory / "cold", lock)
                        sdk.restore(REPO, directory / "cache", directory / "warm", lock)
                    build.assert_not_called()
                self.assertEqual(transfer.call_count, 1)
                self.assertEqual(remote.call_count, 1)
            self.assertEqual(sdk.validate_sdk(directory / "cold", lock), sdk.validate_sdk(directory / "warm", lock))

    def test_successful_source_run_can_be_imported_without_compiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = directory / "original"
            original.mkdir()
            lock, _ = package_fixture(original, legacy=True)
            run = {"status": "completed", "conclusion": "success", "head_repository": {"full_name": REPO},
                   "path": ".github/workflows/build-v8-windows.yml", "head_sha": "a" * 40}
            source_lock = {"content": base64.b64encode(json.dumps(lock).encode()).decode()}

            def download(*arguments):
                self.assertEqual(arguments[:3], ("run", "download", "42"))
                target = Path(arguments[arguments.index("--dir") + 1])
                for name in (sdk.ARCHIVE, sdk.CHECKSUM):
                    shutil.copy2(original / name, target / name)
                return ""

            with patch.object(sdk, "api", side_effect=[run, source_lock]), patch.object(sdk, "gh", side_effect=download):
                sdk.import_run(REPO, "42", directory / "imported", lock)
            self.assertEqual(sdk.archive_hash(original), sdk.archive_hash(directory / "imported"))
            source = json.loads((directory / "imported" / sdk.SOURCE).read_text())
            self.assertEqual(source["commit"], "a" * 40)
            sdk.unpack(directory / "imported", directory / "verified", lock)

    def test_failed_source_run_or_changed_lock_is_rejected_before_download(self):
        run = {"status": "completed", "conclusion": "failure", "head_repository": {"full_name": REPO},
               "path": ".github/workflows/build-v8-windows.yml", "head_sha": "a" * 40}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "imported"
            with patch.object(sdk, "api", return_value=run), patch.object(sdk, "gh") as download:
                with self.assertRaisesRegex(sdk.InputError, "successful V8 SDK workflow"):
                    sdk.import_run(REPO, "42", output, sdk.load_lock())
                download.assert_not_called()
            run["conclusion"] = "success"
            source_lock = {"content": base64.b64encode(b'{}').decode()}
            with patch.object(sdk, "api", side_effect=[run, source_lock]), patch.object(sdk, "gh") as download:
                with self.assertRaisesRegex(sdk.InputError, "different V8 input lock"):
                    sdk.import_run(REPO, "42", output, sdk.load_lock())
                download.assert_not_called()
            self.assertFalse(output.exists())

    def test_published_release_is_never_replaced(self):
        with patch.object(sdk, "api", return_value={"id": 123}), patch.object(sdk, "gh") as mutate:
            with self.assertRaisesRegex(sdk.InputError, "refusing to replace"):
                sdk.publish(REPO, Path("unused"), Path("unused"), sdk.load_lock())
            mutate.assert_not_called()

    def test_sdk_installs_into_owned_staging_using_existing_qmake_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            lock, root = package_fixture(repo)
            official = repo / "core"
            official.mkdir()
            (official / "untouched.txt").write_bytes(b"official input")
            staging = repo / "vendor/work/staged"
            staging.mkdir(parents=True)
            (staging / ".core-staging-owner").write_text("stage_core_source.py\n", encoding="utf-8")
            receipt = {"coreRef": lock["coreRef"], "stagedCorePath": str(staging.resolve() / "core")}
            (staging / "core-staging-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                target = sdk.install_into_staging(root, staging, lock, repo_root=repo)
            self.assertTrue((target / "include/v8.h").is_file())
            self.assertEqual(sdk.sha256_file(target / "out.gn/win_64/release/obj/v8_monolith.lib"),
                             sdk.sha256_file(root / sdk.LIBRARY))
            self.assertEqual((official / "untouched.txt").read_bytes(), b"official input")
            self.assertEqual(len(list(official.iterdir())), 1)
            with self.assertRaisesRegex(sdk.InputError, "already exists"):
                sdk.install_into_staging(root, staging, lock, repo_root=repo)
            with self.assertRaisesRegex(sdk.InputError, "isolated staging"):
                sdk.install_into_staging(root, official, lock, repo_root=repo)

    def test_staging_without_owner_marker_cannot_receive_sdk_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            lock, root = package_fixture(repo)
            staging = repo / "vendor/work/not-owned"
            staging.mkdir(parents=True)
            with self.assertRaisesRegex(sdk.InputError, "owner marker"):
                sdk.install_into_staging(root, staging, lock, repo_root=repo)
            self.assertEqual(list(staging.iterdir()), [])

    def test_publish_uploads_draft_then_publishes_and_verifies_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, root = package_fixture(directory)
            probe_receipt = directory / "sdk-probe.json"
            probe_receipt.write_text(json.dumps({**sdk.validate_sdk(root, lock), "status": "passed",
                                                  "source": "1 + 2", "expected": 3}))
            calls = []

            def mock_gh(*arguments):
                calls.append(arguments)
                if arguments[:2] == ("release", "download"):
                    target = Path(arguments[arguments.index("--dir") + 1])
                    for name in (sdk.ARCHIVE, sdk.CHECKSUM, sdk.RECEIPT):
                        shutil.copy2(directory / name, target / name)
                return ""

            with patch.object(sdk, "api", return_value=None), patch.object(sdk, "gh", side_effect=mock_gh):
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "42", "GITHUB_SHA": "a" * 40}):
                    with contextlib.redirect_stdout(io.StringIO()):
                        sdk.publish(REPO, directory, probe_receipt, lock)
            self.assertEqual([call[:2] for call in calls], [("release", "create"), ("release", "edit"),
                                                           ("release", "download")])
            self.assertIn("--draft", calls[0])
            self.assertIn("--draft=false", calls[1])
            self.assertTrue(all("--clobber" not in call for call in calls))
            sdk.validate_release_bundle(directory, lock, REPO)

    def test_publication_requires_a_probe_of_the_exact_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock, root = package_fixture(directory)
            probe_receipt = directory / "sdk-probe.json"
            probe_receipt.write_text(json.dumps({**sdk.validate_sdk(root, lock), "status": "failed"}))
            with patch.object(sdk, "api", return_value=None), patch.object(sdk, "gh") as mutate:
                with self.assertRaisesRegex(sdk.InputError, "not probed successfully"):
                    sdk.publish(REPO, directory, probe_receipt, lock)
                mutate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
