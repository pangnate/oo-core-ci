#!/usr/bin/env python3
"""Identify and verify reusable Windows feature dependency SDK outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = (
    "DesktopEditor/freetype-2.10.4", "Common/3dParty/harfbuzz",
    "Common/3dParty/brotli", "DesktopEditor/cximage/png",
    "OfficeUtils/src/zlib-1.2.11", "DesktopEditor/raster/Jp2/openjpeg",
    "DesktopEditor/graphics/pro/freetype.pri", "DesktopEditor/graphics/pro/raster.pri",
)
INPUTS = (
    "config/windows-feature-sdk.lock.json", "config/v8-windows.lock.json",
    "config/feature-runtime-deps.lock.json", "vendor/checksums.json", "build_tools",
    "scripts/feature_deps", "scripts/stage_core_source.py", "scripts/download.py",
    "scripts/manage_v8_windows_sdk.py", "scripts/ci_feature_sdk_cache.py",
    "scripts/ci_vs_env.ps1", "tests/core-features/cpp/build_deps_windows_probe.cpp",
)

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def dependency_path(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in DEPENDENCIES)

def patch_inputs(root: Path) -> dict:
    series = json.loads((root / "patches/core/series.json").read_text(encoding="utf-8"))
    result = {}
    for item in series["patches"]:
        patch = root / item["path"]
        paths = [line[6:] for line in patch.read_text(encoding="utf-8").splitlines()
                 if line.startswith(("+++ b/", "--- a/"))]
        if any(dependency_path(path) for path in paths):
            result[item["path"]] = sha(patch)
    return result

def identity(root: Path = ROOT) -> str:
    compiler = os.environ.get("X2T_COMPILER_VERSION", "")
    if not compiler:
        raise ValueError("MSVC version must be identified before the feature SDK cache")
    baseline = json.loads((root / "ci/baseline.json").read_text(encoding="utf-8"))
    paths = (*INPUTS, *("core/" + path for path in DEPENDENCIES),
             *baseline.get("coreBuildPatches", []))
    objects = {}
    for path in paths:
        objects[path] = subprocess.run(["git", "rev-parse", "HEAD:" + path], cwd=root,
                                      text=True, capture_output=True, check=True).stdout.strip()
    overlays = {path: sha(root / "overlays/core" / path)
                for path in baseline.get("coreOverlays", []) if dependency_path(path)}
    value = {"schema": 1, "compiler": compiler, "imageOS": os.environ.get("ImageOS", ""),
             "imageVersion": os.environ.get("ImageVersion", ""),
             "objects": objects, "patches": patch_inputs(root), "overlays": overlays,
             "coreRef": baseline["coreRef"], "buildToolsRef": baseline["buildToolsRef"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def inventory(dist: Path) -> dict:
    sdk = dist / "windows-feature-sdk"
    required = [sdk / name for name in ("manifest.json", "provenance.json", "probe-receipt.json",
                "build-receipt.json", "staging-receipt.json", "core-feature-sources.zip")]
    required += [dist / "windows-feature-sdk.zip", dist / "windows-feature-sdk.zip.sha256"]
    if any(not path.is_file() for path in required):
        raise ValueError("incomplete feature SDK cache")
    paths = [p for p in sdk.rglob("*") if p.is_file() and p.name != "dev-build-receipt.json"]
    paths += required[-2:]
    return {p.relative_to(dist).as_posix(): sha(p) for p in sorted(set(paths))}

def receipt(dist: Path, key: str, record: bool) -> None:
    path = dist / "feature-sdk-cache-receipt.json"
    value = {"schemaVersion": 1, "inputId": key, "files": inventory(dist)}
    probe = json.loads((dist / "windows-feature-sdk/probe-receipt.json").read_text(encoding="utf-8"))
    if probe.get("status") != "passed":
        raise ValueError("feature SDK native probes did not pass")
    archive = dist / "windows-feature-sdk.zip"
    if (dist / "windows-feature-sdk.zip.sha256").read_text(encoding="ascii").split()[0] != sha(archive):
        raise ValueError("feature SDK archive checksum mismatch")
    if record:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    elif json.loads(path.read_text(encoding="utf-8")) != value:
        raise ValueError("feature SDK cache input or file checksums mismatch")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("key", "record", "verify"))
    args = parser.parse_args()
    key = identity()
    if args.mode == "key":
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write("input-id=" + key + "\n")
        print("Feature SDK input ID: " + key)
    else:
        receipt(ROOT / "dist", key, args.mode == "record")
        print("Feature SDK cache " + args.mode + " passed")

if __name__ == "__main__":
    main()
