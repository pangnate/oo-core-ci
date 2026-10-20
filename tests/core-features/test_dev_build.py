"""Contract checks for the isolated Windows development build entry."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_core_dev  # noqa: E402


class WindowsDevBuildTests(unittest.TestCase):
    def test_profile_is_bound_to_core_sdk_abi_and_probe_target(self) -> None:
        profile = json.loads((ROOT / "config/windows-dev-build.profile.json").read_text(encoding="utf-8"))
        sdk_lock = build_core_dev.validate_profile(profile)
        self.assertEqual(profile["platform"], "windows-amd64")
        self.assertEqual(profile["sdk"]["abi"], sdk_lock["abi"]["id"])
        self.assertIn("dependency-probe", profile["targets"])
        self.assertIn("USE_JPIP", (ROOT / "scripts/feature_deps/windows.py").read_text(encoding="utf-8"))
        self.assertNotIn("clean=1", (ROOT / "scripts/build_core_dev.py").read_text(encoding="utf-8"))

    def test_profile_rejects_an_unlocked_sdk_hash(self) -> None:
        profile = json.loads((ROOT / "config/windows-dev-build.profile.json").read_text(encoding="utf-8"))
        profile["sdk"]["lockSha256"] = "0" * 64
        with self.assertRaisesRegex(build_core_dev.BuildError, "SDK lock hash mismatch"):
            build_core_dev.validate_profile(profile)

    def test_output_reuse_requires_owned_profile_and_passed_receipt(self) -> None:
        identity = {"profileId": "fixture", "target": "dependency-probe"}
        with tempfile.TemporaryDirectory(dir=build_core_dev.WORK_ROOT) as temp:
            output = Path(temp) / "output"
            output.mkdir()
            (output / ".windows-dev-build.json").write_text(json.dumps(identity), encoding="utf-8")
            (output / "build-receipt.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            with self.assertRaisesRegex(build_core_dev.BuildError, "refusing to reuse"):
                build_core_dev.validate_output_root(output, identity)
            (output / "build-receipt.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            self.assertTrue(build_core_dev.validate_output_root(output, identity))

    def test_staged_source_must_carry_the_locked_official_receipt(self) -> None:
        checksums = json.loads((ROOT / "vendor/checksums.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="dev-build-stage-", dir=build_core_dev.WORK_ROOT) as temp:
            staging = Path(temp) / "staging"
            core = staging / "core"
            core.mkdir(parents=True)
            (staging / ".core-staging-owner").write_text("fixture\n", encoding="utf-8")
            receipt = {"coreRef": checksums["core-source"]["ref"],
                       "officialTreeSha256": checksums["core-source"]["treeSha256"],
                       "stagedCoreInventorySha256": "a" * 64}
            (staging / "core-staging-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            result = build_core_dev.validate_core_root(core)
            self.assertEqual(result["sourceKind"], "verified-staging")
            receipt["officialTreeSha256"] = "0" * 64
            (staging / "core-staging-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(build_core_dev.BuildError, "does not match"):
                build_core_dev.validate_core_root(core)


def verify_dev_build(profile: dict) -> int:
    if profile.get("level") != "source":
        raise AssertionError("dev-build uses a source profile")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WindowsDevBuildTests)
    result = unittest.TextTestRunner(stream=__import__("io").StringIO()).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Windows dev-build entry contract failed")
    return result.testsRun + 1


if __name__ == "__main__":
    unittest.main()
