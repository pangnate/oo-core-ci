#!/usr/bin/env python3
"""Verify the checked-out Core tree against the pinned official source lock."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage_core_source import inventory_fingerprint, validate_patch_series  # noqa: E402


def main() -> int:
    baseline = json.loads((ROOT / "ci/baseline.json").read_text(encoding="utf-8"))
    checksums = json.loads((ROOT / "vendor/checksums.json").read_text(encoding="utf-8"))
    series = json.loads((ROOT / "patches/core/series.json").read_text(encoding="utf-8"))
    lock = checksums["core-source"]

    if baseline.get("coreRef") != lock.get("ref") or series.get("coreRef") != lock.get("ref"):
        raise SystemExit("Core refs in baseline, source lock and patch series disagree")
    validate_patch_series(series, lock)
    if series["patches"]:
        raise SystemExit("The direct checkout build cannot omit active Core feature patches")

    count, fingerprint = inventory_fingerprint(ROOT / "core")
    if count != lock.get("files") or fingerprint != lock.get("extractedTreeFingerprint"):
        raise SystemExit(
            "Checked-out Core source fingerprint mismatch: "
            f"files={count}, sha256={fingerprint}; expected files={lock.get('files')}, "
            f"sha256={lock.get('extractedTreeFingerprint')}"
        )

    work = ROOT / "vendor/work"
    work.mkdir(parents=True, exist_ok=True)
    receipt_path = work / "x2t-core-source-verification.json"
    if receipt_path.exists():
        raise SystemExit(f"Refusing to overwrite source verification receipt: {receipt_path}")
    receipt = {
        "schemaVersion": 1,
        "status": "verified",
        "coreRef": lock["ref"],
        "coreTreeSha256": lock["treeSha256"],
        "sourceFileCount": count,
        "sourceInventorySha256": fingerprint,
        "featurePatches": [],
        "buildCorrections": baseline.get("coreBuildPatches", []),
        "overlays": baseline.get("coreOverlays", []),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**receipt, "receipt": str(receipt_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
