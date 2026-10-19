from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "core_features.py"
spec = importlib.util.spec_from_file_location("core_features_runner", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PROFILE = ROOT / "tests" / "core-features" / "profiles" / "source-windows.json"


class RunnerTests(unittest.TestCase):
    def test_baseline_replays_core00_evidence(self) -> None:
        result = subprocess.run([sys.executable, str(RUNNER_PATH), "--case", "baseline", "--platform", "windows-amd64",
                                 "--profile", str(PROFILE), "--timeout", "120"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"assertions=[1-9][0-9]*")

    def test_fixtures_case_is_nonempty_and_source_only(self) -> None:
        result = subprocess.run([sys.executable, str(RUNNER_PATH), "--case", "fixtures", "--platform", "windows-amd64",
                                 "--profile", str(PROFILE), "--timeout", "30"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"assertions=[1-9][0-9]*")

    def test_unknown_case_fails_closed(self) -> None:
        result = subprocess.run([sys.executable, str(RUNNER_PATH), "--case", "not-implemented", "--platform", "windows-amd64",
                                 "--profile", str(PROFILE)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_profile_platform_mismatch_fails_closed(self) -> None:
        result = subprocess.run([sys.executable, str(RUNNER_PATH), "--case", "fixtures", "--platform", "linux-amd64",
                                 "--profile", str(PROFILE)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match profile", result.stderr)

    def test_profile_hash_drift_is_rejected(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        profile["inputs"]["fixture-manifest"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "profile.json"
            candidate.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(runner.RunnerError, "hash mismatch"):
                runner.validate_profile(candidate, "fixtures")

    def test_zero_assertions_are_rejected(self) -> None:
        with self.assertRaisesRegex(runner.RunnerError, "zero assertions"):
            runner.require_assertions(0)
        runner.require_assertions(1)

    def test_timeout_stops_only_runner_owned_process_and_redacts_logs(self) -> None:
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
        try:
            code, output, timed_out, pid = runner.run_owned_process(
                [sys.executable, "-c", "import time; print('token=secret-value', flush=True); time.sleep(20)"], 0.25)
            self.assertTrue(timed_out)
            self.assertNotEqual(code, 0)
            self.assertGreater(pid, 0)
            self.assertIn("token=[REDACTED]", output)
            self.assertNotIn("secret-value", output)
            self.assertIsNone(unrelated.poll(), "timeout handling terminated a process it did not create")
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_runner_records_owned_pid_and_result_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp) / "logs"
            result = subprocess.run([sys.executable, str(RUNNER_PATH), "--case", "fixtures", "--platform", "windows-amd64",
                                     "--profile", str(PROFILE), "--timeout", "30", "--log-dir", str(log_dir)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads((log_dir / "fixtures.json").read_text(encoding="utf-8"))
            self.assertGreater(record["pid"], 0)
            self.assertEqual(record["exitCode"], 0)
            self.assertFalse(record["timedOut"])


if __name__ == "__main__":
    unittest.main()
