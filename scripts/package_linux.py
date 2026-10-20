#!/usr/bin/env python3
"""Package one verified Linux X2T binary with versioned archive naming."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

from branding import load_branding

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    source = args.binary.resolve(strict=True)
    if source.stat().st_size == 0:
        raise ValueError(f"empty X2T binary: {source}")
    verification = json.loads(args.verification.read_text(encoding="utf-8"))
    expected_target = "linux_64" if args.arch == "amd64" else "linux_arm64"
    if verification.get("status") != "verified":
        raise ValueError("Linux binary has no passing verification receipt")
    if verification.get("platform") != expected_target:
        raise ValueError("verification platform does not match the package")
    if verification.get("sourceSha") != os.environ.get("GITHUB_SHA"):
        raise ValueError("verification source SHA does not match this run")
    if verification.get("binarySha256") != sha256(source):
        raise ValueError("verified binary hash does not match the package")
    _, _, parts = load_branding()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / f"x2t-linux-{args.arch}"
    branding = output / f"x2t-linux-{args.arch}-branding.json"
    shutil.copy2(source, binary)
    shutil.copy2(ROOT / "config/branding.json", branding)
    version = ".".join(str(part) for part in parts[:3])
    archive = output / f"core10-linux-{args.arch}-{version}-build-{parts[3]}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.write(binary, "x2t")
        package.write(branding, "branding.json")
        package.write(args.verification, "verification.json")
        package.write(ROOT / f"dist/core-producer-{expected_target}.json", "core-producer.json")
        package.write(ROOT / f"dist/core-reuse-{expected_target}.json", "core-reuse.json")
    sums = output / f"SHA256SUMS-linux-{args.arch}"
    sums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in (binary, branding, archive)),
        encoding="utf-8",
    )
    print(f"Packaged {archive}")


if __name__ == "__main__":
    main()
