from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_v8_windows_sdk import prepare_depot_tools


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
        self.assertIn("def prepare_depot_tools", script)
        self.assertIn("bootstrap/win_tools.bat", script)
        self.assertIn("manually managed python not supported by chrome operations", script)
        self.assertIn("# changed by build_tools", script)
        self.assertIn("args.work_root = args.work_root.resolve()", script)
        self.assertIn("args.dist = args.dist.resolve()", script)

    def test_depot_tools_bootstrap_recipe_is_narrow_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            depot = Path(temporary)
            (depot / "bootstrap").mkdir()
            (depot / "bootstrap/manifest.txt").write_text("upstream manifest\n", encoding="utf-8")
            (depot / "bootstrap/bootstrap.py").write_text(
                "            raise subprocess.CalledProcessError(proc.returncode, argv, None)\n"
                "    _win_git_bootstrap_config()\n",
                encoding="utf-8",
            )
            prepare_depot_tools(depot)
            manifest = (depot / "bootstrap/manifest.txt").read_text(encoding="utf-8")
            bootstrap = (depot / "bootstrap/bootstrap.py").read_text(encoding="utf-8")
            self.assertTrue((depot / "bootstrap/manifest.txt.upstream").is_file())
            self.assertIn("3.11.8.chromium.35", manifest)
            self.assertIn("# changed by build_tools: skip failed Windows git bootstrap", bootstrap)
            self.assertIn("#_win_git_bootstrap_config()", bootstrap)
            prepare_depot_tools(depot)
            self.assertEqual(bootstrap, (depot / "bootstrap/bootstrap.py").read_text(encoding="utf-8"))

    def test_depot_tools_revision_without_legacy_git_bootstrap_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            depot = Path(temporary)
            (depot / "bootstrap").mkdir()
            (depot / "bootstrap/manifest.txt").write_text("upstream manifest\n", encoding="utf-8")
            (depot / "bootstrap/bootstrap.py").write_text(
                "            raise subprocess.CalledProcessError(proc.returncode, argv, None)\n",
                encoding="utf-8",
            )
            prepare_depot_tools(depot)
            bootstrap = (depot / "bootstrap/bootstrap.py").read_text(encoding="utf-8")
            self.assertIn("# changed by build_tools: skip failed Windows git bootstrap", bootstrap)
            self.assertNotIn("_win_git_bootstrap_config", bootstrap)


if __name__ == "__main__":
    unittest.main()
