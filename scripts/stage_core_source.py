#!/usr/bin/env python3
"""Create an isolated Core build tree by replaying the frozen project inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class StageError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if path.suffix == ".patch":
                block = block.replace(b"\r\n", b"\n")
            h.update(block)
    return h.hexdigest()


def inventory_fingerprint(source: Path) -> tuple[int, str]:
    """Stable extraction fingerprint, distinct from the official archive tree hash."""
    source = source.resolve()
    entries = list(source.rglob("*"))
    for path in entries:
        if path.is_symlink():
            raise StageError(f"symlink is not allowed in official Core source: {path}")
    files = sorted((p for p in entries if p.is_file()),
                   key=lambda p: p.relative_to(source).as_posix().encode("utf-8"))
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(source).as_posix().encode("utf-8")
        digest.update(relative + b"\0" + str(path.stat().st_size).encode("ascii") + b"\0")
        digest.update(file_sha256(path).encode("ascii") + b"\n")
    return len(files), digest.hexdigest()


def _repo_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise StageError(f"path must remain within repository: {path}") from exc


def _safe_repo_path(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise StageError(f"unsafe repository-relative path: {relative}")
    target = (root / Path(*rel.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise StageError(f"path escapes repository: {relative}")
    return target


def validate_patch_series(series: dict[str, Any], core_lock: dict[str, Any]) -> None:
    if set(series) != {"schemaVersion", "coreRef", "coreTreeSha256", "patches"}:
        raise StageError("patch series has unknown or missing top-level fields")
    if series.get("schemaVersion") != 1 or not isinstance(series.get("patches"), list):
        raise StageError("unsupported patch series schema")
    seen: set[str] = set()
    previous: set[str] = set()
    previous_number = 0
    for entry in series["patches"]:
        if not isinstance(entry, dict) or set(entry) - {"path", "sha256", "purpose", "dependsOn"}:
            raise StageError("patch entry has an invalid shape")
        if not {"path", "sha256", "purpose"}.issubset(entry):
            raise StageError("patch entry is missing path, sha256 or purpose")
        path = entry["path"]
        if not isinstance(path, str) or not re.fullmatch(r"patches/core/[0-9]{3}-[a-z0-9-]+\.patch", path):
            raise StageError(f"invalid ordered patch path: {path!r}")
        number = int(path.rsplit("/", 1)[1][:3])
        if number <= previous_number:
            raise StageError("patches must be listed in strictly increasing numeric order")
        previous_number = number
        if path in seen:
            raise StageError(f"duplicate patch in series: {path}")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise StageError(f"invalid patch SHA256: {path}")
        if not isinstance(entry["purpose"], str) or not entry["purpose"].strip():
            raise StageError(f"patch purpose is empty: {path}")
        dependencies = entry.get("dependsOn", [])
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            raise StageError(f"invalid dependencies: {path}")
        seen.add(path)
        if len(set(dependencies)) != len(dependencies) or any(item not in previous for item in dependencies):
            raise StageError(f"patch dependencies must name earlier patches: {path}")
        previous.add(path)
    if series.get("coreRef") != core_lock.get("ref") or series.get("coreTreeSha256") != core_lock.get("treeSha256"):
        raise StageError("patch series official Core identity mismatch")


def _run_git_apply(root: Path, destination_rel: str, patch_path: Path, *, reverse: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["git", "apply", "--check"]
    if reverse:
        command.append("--reverse")
    command.extend(["--directory", destination_rel, str(patch_path)])
    return subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")


def stage_core_source(
    *,
    repo_root: Path = ROOT,
    source_root: Path | None = None,
    destination: Path,
    baseline: dict[str, Any] | None = None,
    checksums: dict[str, Any] | None = None,
    core_lock: dict[str, Any] | None = None,
    patch_series: dict[str, Any] | None = None,
    build_patches: list[str] | None = None,
    overlay_files: list[str] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    source_root = (source_root or (repo_root / "core")).resolve()
    baseline = baseline if baseline is not None else json.loads((repo_root / "ci" / "baseline.json").read_text(encoding="utf-8"))
    checksums = checksums if checksums is not None else json.loads((repo_root / "vendor" / "checksums.json").read_text(encoding="utf-8"))
    core_lock = core_lock if core_lock is not None else checksums["core-source"]
    patch_series = patch_series if patch_series is not None else json.loads((repo_root / "patches" / "core" / "series.json").read_text(encoding="utf-8"))
    build_patches = build_patches if build_patches is not None else baseline.get("coreBuildPatches", [])
    overlay_files = overlay_files if overlay_files is not None else baseline.get("coreOverlays", [])

    if baseline.get("coreRef") != core_lock.get("ref") or patch_series.get("coreRef") != core_lock.get("ref"):
        raise StageError("baseline, source lock and patch series Core refs disagree")
    if patch_series.get("coreTreeSha256") != core_lock.get("treeSha256"):
        raise StageError("patch series official Core tree hash mismatch")
    if baseline.get("coreRef") != checksums["core-source"].get("ref"):
        raise StageError("requested Core source does not match the repository baseline")
    validate_patch_series(patch_series, core_lock)
    if not source_root.is_dir():
        raise StageError(f"official Core source is missing: {source_root}")
    source_files, before_fingerprint = inventory_fingerprint(source_root)
    if source_files != core_lock.get("files"):
        raise StageError(f"official Core file count mismatch: {source_files} != {core_lock.get('files')}")
    expected_fingerprint = core_lock.get("extractedTreeFingerprint")
    expected_algorithm = "sha256(sorted UTF-8 relative path + NUL + decimal size + NUL + file SHA256 hex + LF)"
    if expected_fingerprint and core_lock.get("extractedTreeFingerprintAlgorithm") != expected_algorithm:
        raise StageError("unsupported extracted Core fingerprint algorithm")
    if expected_fingerprint and before_fingerprint != expected_fingerprint:
        raise StageError("official Core extracted source fingerprint mismatch")

    destination = destination.resolve()
    work_root = (repo_root / "vendor" / "work").resolve()
    if not destination.is_relative_to(work_root):
        raise StageError("staging destination must be under vendor/work")
    if destination.exists():
        raise StageError(f"staging destination already exists; refusing reuse or cleanup: {destination}")
    destination_rel = _repo_relative(repo_root, destination)
    destination.mkdir(parents=True)
    owned_marker = destination / ".core-staging-owner"
    owned_marker.write_text("stage_core_source.py\n", encoding="utf-8")
    staged_core = destination / "core"
    try:
        shutil.copytree(source_root, staged_core, symlinks=False)
        patch_receipts = []
        for relative in build_patches:
            script = _safe_repo_path(repo_root, relative)
            if not script.is_file():
                raise StageError(f"declared build correction is missing: {relative}")
            result = subprocess.run([sys.executable, str(script), "--core-root", str(staged_core)],
                                    cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode:
                raise StageError(f"build correction failed: {relative}\n{result.stdout}\n{result.stderr}")
            patch_receipts.append({"path": relative, "sha256": file_sha256(script), "output": result.stdout.strip()})

        for entry in patch_series["patches"]:
            patch_path = _safe_repo_path(repo_root, entry.get("path", ""))
            if not patch_path.is_file() or file_sha256(patch_path) != entry.get("sha256"):
                raise StageError(f"feature patch is missing or hash-mismatched: {entry.get('path')}")
            check = _run_git_apply(repo_root, destination_rel, patch_path)
            if check.returncode:
                raise StageError(f"feature patch does not apply: {entry['path']}\n{check.stderr.strip()}")
            apply = subprocess.run(["git", "apply", "--directory", destination_rel, str(patch_path)],
                                   cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if apply.returncode:
                raise StageError(f"feature patch apply failed: {entry['path']}\n{apply.stderr.strip()}")

        overlay_receipts = []
        overlay_root = repo_root / "overlays" / "core"
        for relative in overlay_files:
            rel = PurePosixPath(relative)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise StageError(f"unsafe overlay path: {relative}")
            overlay = (overlay_root / Path(*rel.parts)).resolve()
            if not overlay.is_relative_to(overlay_root.resolve()) or not overlay.is_file() or overlay.is_symlink():
                raise StageError(f"declared overlay is missing or unsafe: {relative}")
            target = staged_core / Path(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(overlay, target)
            overlay_receipts.append({"path": relative, "sha256": file_sha256(overlay)})

        staged_files, staged_fingerprint = inventory_fingerprint(staged_core)
        after_files, after_fingerprint = inventory_fingerprint(source_root)
        if (after_files, after_fingerprint) != (source_files, before_fingerprint):
            raise StageError("official Core source changed while staging")
        receipt = {
            "schemaVersion": 1,
            "coreRef": core_lock["ref"],
            "officialTreeSha256": core_lock["treeSha256"],
            "sourceFileCount": source_files,
            "sourceInventorySha256Before": before_fingerprint,
            "sourceInventorySha256After": after_fingerprint,
            "stagedCorePath": str(staged_core),
            "stagedCoreFiles": staged_files,
            "stagedCoreInventorySha256": staged_fingerprint,
            "featurePatches": [{"path": entry["path"], "sha256": entry["sha256"]} for entry in patch_series.get("patches", [])],
            "buildCorrections": patch_receipts,
            "overlays": overlay_receipts,
        }
        (destination / "core-staging-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt
    except Exception:
        # Destination was verified absent and marked as owned before any writes.
        shutil.rmtree(destination)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "core")
    parser.add_argument("--destination", type=Path, required=True,
                        help="new destination below vendor/work; existing paths are never reused or removed")
    args = parser.parse_args(argv)
    receipt = stage_core_source(source_root=args.source, destination=args.destination)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
