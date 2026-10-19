from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "config" / "sdk-manifest.schema.json"
sys.path.insert(0, str(ROOT / "scripts" / "feature_deps"))
import common  # noqa: E402


def _manifest(path: Path, digest: str, status: str = "verified") -> dict:
    entry = {"id": "qt", "role": "qt", "status": status, "source": "locked fixture"}
    if status == "verified":
        entry.update({"path": str(path), "sha256": digest})
    else:
        entry["reason"] = "fixture input intentionally unavailable"
    return {"schemaVersion": 1, "sdkId": "unit-fixture", "kind": "build",
            "platform": "windows-amd64", "abi": "x64-msvc-v142", "entries": [entry]}


class BuildDependencyIOTests(unittest.TestCase):
    def test_sdk_manifest_schema_contract(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["kind"]["enum"], ["development", "build", "runtime"])
        self.assertEqual(schema["properties"]["platform"]["enum"],
                         ["windows-amd64", "linux-amd64", "linux-arm64"])
        self.assertEqual(schema["$defs"] if "$defs" in schema else schema["properties"]["entries"]["items"]["properties"]["status"]["enum"],
                         ["verified", "unavailable", "planned"])

    def test_manifest_hash_platform_abi_and_required_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / "qt.bin"
            payload.write_bytes(b"locked sdk")
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            verified = _manifest(payload, digest)
            paths = common.validate_sdk_manifest(verified, repo_root=root, platform="windows-amd64",
                                                  kind="build", abi="x64-msvc-v142", required_roles={"qt"})
            self.assertEqual(paths["qt"], payload.resolve())
            with self.assertRaises(common.InputError):
                common.validate_sdk_manifest(verified, repo_root=root, platform="linux-amd64", kind="build",
                                             abi="x64-msvc-v142")
            with self.assertRaises(common.InputError):
                common.validate_sdk_manifest(verified, repo_root=root, platform="windows-amd64",
                                             kind="runtime", abi="x64-msvc-v142", required_roles={"qt"})
            with self.assertRaisesRegex(common.InputError, "ABI mismatch"):
                common.validate_sdk_manifest(verified, repo_root=root, platform="windows-amd64", kind="build",
                                             abi="x86-msvc-v142")
            payload.write_bytes(b"changed")
            with self.assertRaisesRegex(common.InputError, "hash mismatch"):
                common.validate_sdk_manifest(verified, repo_root=root, platform="windows-amd64", kind="build",
                                             abi="x64-msvc-v142")

    def test_planned_and_unavailable_never_satisfy_dev_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for status in ("planned", "unavailable"):
                manifest = _manifest(root / "missing", "", status)
                with self.assertRaisesRegex(common.InputError, "not verified"):
                    common.validate_sdk_manifest(manifest, repo_root=root, platform="windows-amd64",
                                                 kind="build", abi="x64-msvc-v142", required_roles={"qt"})

    def test_manifest_rejects_external_paths_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            payload = Path(outside) / "qt.bin"
            payload.write_bytes(b"locked sdk")
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            with self.assertRaisesRegex(common.InputError, "escapes approved roots"):
                common.validate_sdk_manifest(_manifest(payload, digest), repo_root=root,
                                             platform="windows-amd64", kind="build", abi="x64-msvc-v142")
            invalid = _manifest(payload, digest)
            invalid["unexpected"] = True
            with self.assertRaisesRegex(common.InputError, "unsupported root fields"):
                common.validate_sdk_manifest(invalid, repo_root=Path(outside),
                                             platform="windows-amd64", kind="build", abi="x64-msvc-v142")

    def test_safe_zip_extract_and_refuse_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "ok.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("sdk/include/test.h", "header")
            out = common.safe_extract_archive(archive, root / "scratch" / "sdk", scratch_root=root / "scratch")
            self.assertEqual((out / "sdk" / "include" / "test.h").read_text(), "header")
            with self.assertRaisesRegex(common.InputError, "already exists"):
                common.safe_extract_archive(archive, out, scratch_root=root / "scratch")

    def test_safe_extract_rejects_traversal_and_cleans_its_owned_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("../escape.txt", "bad")
            dest = root / "scratch" / "owned"
            with self.assertRaisesRegex(common.InputError, "unsafe archive member"):
                common.safe_extract_archive(archive, dest, scratch_root=root / "scratch")
            self.assertFalse(dest.exists())
            self.assertFalse((root / "escape.txt").exists())

    def test_safe_extract_rejects_symlinks_and_size_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            symlink_archive = root / "symlink.zip"
            link = zipfile.ZipInfo("link")
            link.create_system = 3
            link.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(symlink_archive, "w") as package:
                package.writestr(link, "../../outside")
            with self.assertRaisesRegex(common.InputError, "symbolic links"):
                common.safe_extract_archive(symlink_archive, root / "scratch" / "link-out",
                                            scratch_root=root / "scratch")
            self.assertFalse((root / "scratch" / "link-out").exists())

            archive = root / "oversized.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("big.dat", b"0123456789")
            with self.assertRaisesRegex(common.InputError, "size limit"):
                common.safe_extract_archive(archive, root / "scratch" / "out", scratch_root=root / "scratch",
                                            max_unpacked_bytes=5)
            self.assertFalse((root / "scratch" / "out").exists())

    def test_recipe_timeout_and_probe_reports_reproducible_missing_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = common.run_recipe([sys.executable, "-c", "import time; time.sleep(10)"], cwd=root,
                                       timeout=0.1)
            self.assertTrue(result["timedOut"])
            self.assertNotEqual(result["exitCode"], 0)
            probe = common.probe_windows_toolchain(vswhere=root / "no-vswhere.exe", qmake=root / "no-qmake.exe")
            self.assertFalse(probe["available"])
            self.assertIn("vswhere.exe", probe["missing"])
            self.assertIn("Qt 5.15.2 msvc2019_64 qmake.exe", probe["missing"])


def verify_build_deps_io(profile: dict) -> int:
    if profile.get("level") != "source":
        raise AssertionError("build-deps-io uses a source profile")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BuildDependencyIOTests)
    result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("SDK input/recipe IO contract tests failed")
    return result.testsRun + 1


if __name__ == "__main__":
    unittest.main()
