from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Checks:
    def __init__(self) -> None:
        self.count = 0

    def that(self, condition: bool, message: str) -> None:
        self.count += 1
        if not condition:
            raise AssertionError(message)


def verify_baseline(profile: dict) -> int:
    checks = Checks()
    baseline = json.loads((ROOT / "ci" / "baseline.json").read_text(encoding="utf-8"))
    locks = json.loads((ROOT / "vendor" / "checksums.json").read_text(encoding="utf-8"))
    core = locks["core-source"]
    checks.that(baseline["coreRef"] == profile["core"]["ref"] == core["ref"], "Core ref does not match source profile and vendor lock")
    checks.that(core["treeSha256"] == profile["core"]["treeSha256"], "official Core archive tree hash mismatch")
    checks.that(core["files"] == 21117, "official Core file count changed")
    checks.that(baseline.get("corePatches") == [], "unexpected functional Core patch declared in baseline")
    checks.that(baseline.get("coreBuildPatches") == ["scripts/patch_x2t_sln.py"], "Core build patch order/source changed")
    checks.that(baseline.get("coreOverlays") == ["Common/copyright.txt"], "Core overlay declaration changed")
    checks.that((ROOT / "scripts" / "patch_x2t_sln.py").is_file(), "declared X2T build patch is missing")
    checks.that((ROOT / "overlays" / "core" / "Common" / "copyright.txt").is_file(), "declared Core branding overlay is missing")
    series = json.loads((ROOT / "patches" / "core" / "series.json").read_text(encoding="utf-8"))
    checks.that(series["coreRef"] == core["ref"] and series["coreTreeSha256"] == core["treeSha256"],
                "active patch series source identity does not match baseline")
    feature_patches = series["patches"]
    checks.that(not feature_patches, f"CORE-00 baseline unexpectedly enables feature patches: {feature_patches}")
    core_status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "core"],
                                 cwd=ROOT, capture_output=True, text=True, check=True)
    checks.that(not core_status.stdout.strip(), "official Core worktree contains modified or untracked source")
    evidence = (ROOT / "docs" / "测试" / "luna" / "LUNA-CORE-00" / "evidence.md").read_text(encoding="utf-8")
    checks.that(core["treeSha256"] in evidence and core["ref"] in evidence, "CORE-00 evidence does not match locked source")
    checks.that("9.4.0.129" in evidence and "10.0.0.169" in evidence, "runtime source distinction is absent from CORE-00 evidence")
    checks.that("metadata-only-reconciliation" in evidence, "candidate runtime provenance caveat is absent")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_vendor.py"), "--platform", "windows"],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    checks.that(result.returncode == 0, "Windows vendor verification failed: " + (result.stdout + result.stderr)[-1200:])
    checks.that("Vendor inputs OK (windows)" in result.stdout, "Windows vendor verification returned no success marker")
    checks.that(profile.get("platform") == "windows-amd64", "baseline replay must use the Windows source profile")
    return checks.count
