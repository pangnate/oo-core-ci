#!/usr/bin/env python3
"""Record the Linux binary accepted by the isolated verification job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("linux_64", "linux_arm64"))
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    source_sha = os.environ.get("GITHUB_SHA")
    if not source_sha:
        raise ValueError("GITHUB_SHA is required")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    receipt = {
        "status": "verified",
        "platform": args.target,
        "sourceSha": source_sha,
        "binarySha256": digest,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
