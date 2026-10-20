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
    "ci/toolchains",
    "scripts/prepare.py",
    "scripts/native_sources.py",
    "config/native-sources.lock.json",
    "scripts/configure_build.py",
    "scripts/make_minimal_deps.py",
    "scripts/ci_deps_key.py",
    "scripts/ci_handoff.py",
)
WINDOWS_INPUTS = ("ci/vswrap", "scripts/ci_vs_env.ps1", "scripts/windows_build.cmd")


def identity(platform: str) -> str:
    if platform not in ("win_64", "linux_64", "linux_arm64"):
        raise ValueError(f"Unsupported dependency target: {platform}")
    digest = hashlib.sha256()
    if platform == "win_64":
        environment = (os.environ.get("ImageOS", ""), os.environ.get("ImageVersion", ""),
                       os.environ.get("X2T_COMPILER_VERSION", ""))
        inputs = INPUTS + WINDOWS_INPUTS
    else:
        # Linux compilers/sysroots/Qt come from checksum-locked archives, not
        # the hosted image. Image rollouts must not invalidate those outputs.
        environment = ("locked-linux-sysroot-v2",)
        inputs = INPUTS
    for value in (platform, *environment):
        digest.update(value.encode("utf-8") + b"\0")
    for path in inputs:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT,
            check=True, text=True, capture_output=True,
        )
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(result.stdout.strip().encode("ascii") + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True,
                        choices=("win_64", "linux_64", "linux_arm64"))
    args = parser.parse_args()
    key = identity(args.platform)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with Path(github_env).open("a", encoding="utf-8") as output:
            output.write(f"X2T_DEPS_ID={key}\n")
    print(f"X2T_DEPS_ID={key}")


if __name__ == "__main__":
    main()
