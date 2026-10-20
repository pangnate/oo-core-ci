#!/usr/bin/env python3
"""Apply hash-locked Core feature patches to the verified checkout."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from stage_core_source import file_sha256, validate_patch_series

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    series = json.loads((ROOT / "patches/core/series.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "vendor/checksums.json").read_text(encoding="utf-8"))["core-source"]
    baseline = json.loads((ROOT / "ci/baseline.json").read_text(encoding="utf-8"))
    validate_patch_series(series, lock)
    if baseline["corePatches"] != [entry["path"] for entry in series["patches"]]:
        raise RuntimeError("baseline and active patch series disagree")
    if not (ROOT / "vendor/work/x2t-core-source-verification.json").is_file():
        raise RuntimeError("verify_core_source.py must run before applying patches")

    applied = []
    for entry in series["patches"]:
        patch = ROOT / entry["path"]
        if not patch.is_file() or file_sha256(patch) != entry["sha256"]:
            raise RuntimeError(f"missing or hash-mismatched Core patch: {entry['path']}")
        for extra in (["--check"], []):
            # The pinned source includes CRLF files; git apply otherwise rejects
            # LF patch context on Windows even when the source content matches.
            command = ["git", "apply", "--ignore-space-change", *extra, str(patch)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            if result.returncode:
                raise RuntimeError(f"Core patch failed: {entry['path']}\n{result.stderr}")
        applied.append({"path": entry["path"], "sha256": entry["sha256"]})

    receipt_path = ROOT / "vendor/work/x2t-core-patch-receipt.json"
    if receipt_path.exists():
        raise RuntimeError(f"refusing to overwrite patch receipt: {receipt_path}")
    receipt_path.write_text(json.dumps({"coreRef": lock["ref"], "patches": applied}, indent=2) + "\n",
                            encoding="utf-8")
    print(f"Applied {len(applied)} locked Core patches to checkout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
