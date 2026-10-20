#!/usr/bin/env python3
"""Archive and verify files passed between isolated X2T Actions jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def member_path(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe handoff path: {value}")
    return path


def create(args: argparse.Namespace) -> None:
    paths: list[Path] = []
    for value in args.path:
        path = member_path(value)
        if not (ROOT / path).exists():
            raise FileNotFoundError(ROOT / path)
        paths.append(path)
    for value in args.optional:
        path = member_path(value)
        if (ROOT / path).exists():
            paths.append(path)
    if not paths:
        raise ValueError("handoff has no files")
    archive = Path(args.archive).resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w", dereference=True) as package:
        for path in sorted(set(paths)):
            package.add(ROOT / path, arcname=path.as_posix())
    metadata = {
        "schemaVersion": 1,
        "stage": args.stage,
        "platform": args.platform,
        "sourceSha": args.source_sha,
        "archiveSha256": sha256(archive),
        "paths": [path.as_posix() for path in sorted(set(paths))],
    }
    archive.with_suffix(archive.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


def restore(args: argparse.Namespace) -> None:
    archive = Path(args.archive).resolve(strict=True)
    metadata = json.loads(
        archive.with_suffix(archive.suffix + ".json").read_text(encoding="utf-8")
    )
    expected = {
        "schemaVersion": 1,
        "stage": args.stage,
        "platform": args.platform,
        "sourceSha": args.source_sha,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"handoff {key}: {metadata.get(key)!r} != {value!r}")
    if sha256(archive) != metadata.get("archiveSha256"):
        raise ValueError(f"handoff archive checksum mismatch: {archive}")
    with tarfile.open(archive, "r") as package:
        members = package.getmembers()
        for member in members:
            member_path(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsupported handoff member: {member.name}")
        package.extractall(ROOT, members=members)
    for value in metadata["paths"]:
        if not (ROOT / member_path(value)).exists():
            raise FileNotFoundError(ROOT / value)
    print(f"Restored {args.stage} for {args.platform} from {archive.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "restore"):
        command = subparsers.add_parser(name)
        command.add_argument("--archive", required=True)
        command.add_argument("--stage", required=True, choices=("deps", "build", "verify"))
        command.add_argument("--platform", required=True,
                             choices=("win_64", "linux_64", "linux_arm64"))
        command.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", ""))
        if name == "create":
            command.add_argument("--path", action="append", required=True)
            command.add_argument("--optional", action="append", default=[])
    args = parser.parse_args()
    if not args.source_sha:
        parser.error("--source-sha or GITHUB_SHA is required")
    if args.command == "create":
        create(args)
    else:
        restore(args)


if __name__ == "__main__":
    main()
