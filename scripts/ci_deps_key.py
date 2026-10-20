#!/usr/bin/env python3
"""Compute the immutable input ID for an X2T third-party dependency handoff."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "vendor/checksums.json",
    "vendor/detected-deps.json",
    "config/deps.json",
    "build_tools",
    "core/Common/3dParty",
    "patches/core",
    "overlays/core",
    "ci/toolchains",
    "ci/vswrap",
    "scripts/prepare.py",
    "scripts/configure_build.py",
    "scripts/make_minimal_deps.py",
    "scripts/patch_x2t_sln.py",
    "scripts/ci_deps_key.py",
    "scripts/ci_handoff.py",
    "scripts/windows_build.cmd",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True,
                        choices=("win_64", "linux_64", "linux_arm64"))
    args = parser.parse_args()
    digest = hashlib.sha256()
    for value in (args.platform, os.environ.get("ImageOS", ""),
                  os.environ.get("ImageVersion", "")):
        digest.update(value.encode("utf-8") + b"\0")
    for path in INPUTS:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT,
            check=True, text=True, capture_output=True,
        )
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(result.stdout.strip().encode("ascii") + b"\0")
    key = digest.hexdigest()
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with Path(github_env).open("a", encoding="utf-8") as output:
            output.write(f"X2T_DEPS_ID={key}\n")
    print(f"X2T_DEPS_ID={key}")


if __name__ == "__main__":
    main()
