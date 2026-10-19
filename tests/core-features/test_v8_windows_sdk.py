from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class V8WindowsSdkLockTests(unittest.TestCase):
    def test_lock_matches_core_and_build_tools_baseline(self):
        lock = json.loads((ROOT / "config/v8-windows.lock.json").read_text(encoding="utf-8"))
        baseline = json.loads((ROOT / "ci/baseline.json").read_text(encoding="utf-8"))
        checksums = json.loads((ROOT / "vendor/checksums.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["coreRef"], baseline["coreRef"])
        self.assertEqual(lock["buildToolsRef"], baseline["buildToolsRef"])
        self.assertEqual(lock["coreRef"], checksums["core-source"]["ref"])
        self.assertEqual(lock["buildToolsRef"], checksums["build-tools-source"]["ref"])

    def test_sdk_abi_and_gn_arguments_match_core_consumer(self):
        lock = json.loads((ROOT / "config/v8-windows.lock.json").read_text(encoding="utf-8"))
        core_pri = (ROOT / "core/Common/3dParty/v8/v8.pri").read_text(encoding="utf-8")
        self.assertEqual(lock["platform"], "windows-amd64")
        self.assertEqual(lock["abi"], "msvc-v142-14.29-dynamic-crt-x64")
        self.assertTrue(lock["gnArgs"]["v8_enable_pointer_compression"])
        self.assertTrue(lock["gnArgs"]["v8_monolithic"])
        self.assertIn("V8_COMPRESS_POINTERS", core_pri)
        self.assertIn("V8_VERSION_89_PLUS", core_pri)
        self.assertEqual(lock["v8"]["branch"], "branch-heads/8.9")
        self.assertRegex(lock["v8"]["ref"], r"^[0-9a-f]{40}$")
        self.assertRegex(lock["depotTools"]["ref"], r"^[0-9a-f]{40}$")

    def test_actions_workflow_builds_and_uploads_sdk(self):
        workflow = (ROOT / ".github/workflows/build-v8-windows.yml").read_text(encoding="utf-8")
        script = (ROOT / "scripts/build_v8_windows_sdk.py").read_text(encoding="utf-8")
        self.assertIn("windows-2022", workflow)
        self.assertIn("v8-windows-x64-sdk", workflow)
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("v8_monolith", script)
        self.assertIn("V8_PROBE_RESULT=3", script)
        self.assertIn("--revision=v8@", script)
        self.assertIn("args.work_root = args.work_root.resolve()", script)
        self.assertIn("args.dist = args.dist.resolve()", script)


if __name__ == "__main__":
    unittest.main()
