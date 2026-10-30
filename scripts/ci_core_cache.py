#!/usr/bin/env python3
"""Reuse a verified Core build only for the same explicit compilation inputs.

The cache archive is bound to an input ID, while the normal job handoff is
recreated for GITHUB_SHA. A documentation-only commit can therefore reuse the
compiled bytes without pretending that they were compiled by the new commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import ci_handoff

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "core", "build_tools", "patches/core", "overlays/core", "ci/baseline.json",
    "ci/toolchains", "ci/vswrap", "config/branding.json", "config/deps.json",
    "config/build-acceleration.json", "vendor/checksums.json", "vendor/detected-deps.json",
    "scripts/prepare.py", "scripts/native_sources.py", "config/native-sources.lock.json",
    "scripts/configure_build.py", "scripts/patch_x2t_sln.py",
    "scripts/build_x2t.py", "scripts/audit_source_paths.py", "scripts/build_metrics.py", "scripts/branding.py", "scripts/windows_build.cmd",
    "scripts/generate_import_libs.ps1", "scripts/ci_vs_env.ps1", "scripts/qmake",
    "scripts/setup_build_acceleration.py", "scripts/ci_core_cache.py", "scripts/ci_handoff.py",
    "scripts/verify_vendor.py", "scripts/verify_core_source.py", "scripts/stage_core_source.py",
    "scripts/apply_core_patches.py", "scripts/apply_core_overlays.py", "scripts/report_windows_size.py",
)
SOURCE_RECEIPTS = (
    "vendor/work/x2t-core-source-verification.json",
    "vendor/work/x2t-core-patch-receipt.json",
    "vendor/work/x2t-core-overlay-receipt.json",
)


def paths(platform: str) -> list[str]:
    outputs = (["core/build/bin/win_64", "dist/windows-size-report.json"] if platform == "win_64"
               else [f"core/build/bin/{platform}/x2t", f"core/build/lib/{platform}", "config/branding.json"])
    return outputs + [f"core/Common/3dParty/icu/{platform}/build", *SOURCE_RECEIPTS,
                      f"dist/core-producer-{platform}.json", f"dist/build-metrics-{platform}.json"]


def identity(platform: str, deps_id: str) -> dict:
    if not deps_id:
        raise ValueError("X2T_DEPS_ID is required")
    objects = {}
    for relative in INPUTS:
        objects[relative] = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{relative}"], cwd=ROOT, text=True).strip()
    inputs = {"schemaVersion": 1, "platform": platform, "depsId": deps_id,
              "runner": {name: os.environ.get(name, "") for name in ("ImageOS", "ImageVersion")},
              "compilerVersion": os.environ.get("X2T_COMPILER_VERSION", "locked-linux-sysroot"),
              "compilerEnvironment": {name: os.environ.get(name, "") for name in (
                  "X2T_PCH_MODE", "CL", "_CL_", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "QMAKEFEATURES", "QT_QMAKE_ADDON")},
              "parallelism": json.loads((ROOT / "config/build-acceleration.json").read_text())["parallelism"],
              "gitObjects": objects}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"coreId": digest, "inputs": inputs}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check(platform: str, core_id: str) -> dict:
    producer = json.loads((ROOT / f"dist/core-producer-{platform}.json").read_text(encoding="utf-8"))
    if producer.get("coreId") != core_id or producer.get("inputs", {}).get("platform") != platform:
        raise ValueError("Core producer receipt does not match the requested compilation input ID/platform")
    for relative in paths(platform):
        if not (ROOT / relative).exists():
            raise FileNotFoundError(ROOT / relative)
    binary = ROOT / f"core/build/bin/{platform}/{'x2t.exe' if platform == 'win_64' else 'x2t'}"
    if binary.stat().st_size == 0 or ci_handoff.sha256(binary) != producer["binarySha256"]:
        raise ValueError("Core executable differs from the producer receipt")
    if platform == "win_64":
        expected = {"x2t.exe", "graphics.dll", "pdffile.dll"}
        if set(producer.get("compiledModules", {})) != expected:
            raise ValueError("Core producer must identify exactly the source-built Windows modules")
        for name, digest in producer["compiledModules"].items():
            path = next((item for item in binary.parent.iterdir() if item.name.lower() == name), None)
            if path is None or ci_handoff.sha256(path) != digest:
                raise ValueError(f"source-built module differs from producer receipt: {name}")
    return producer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("key", "record", "pack", "restore", "check"))
    parser.add_argument("--platform", required=True, choices=("win_64", "linux_64", "linux_arm64"))
    parser.add_argument("--core-id", default=os.environ.get("X2T_CORE_ID", ""))
    args = parser.parse_args()
    platform = args.platform
    if args.command == "key":
        data = identity(platform, os.environ.get("X2T_DEPS_ID", ""))
        write_json(ROOT / f"dist/core-inputs-{platform}.json", data)
        for variable, line in (("GITHUB_ENV", f"X2T_CORE_ID={data['coreId']}\n"),
                               ("GITHUB_OUTPUT", f"core-id={data['coreId']}\n")):
            if os.environ.get(variable):
                with Path(os.environ[variable]).open("a", encoding="utf-8") as output:
                    output.write(line)
        print(json.dumps(data, indent=2))
        return
    if not args.core_id:
        parser.error("--core-id or X2T_CORE_ID is required")
    archive = ROOT / f"dist/core-cache-{platform}.tar"
    if args.command == "record":
        producer = json.loads((ROOT / f"dist/core-inputs-{platform}.json").read_text(encoding="utf-8"))
        if producer["coreId"] != args.core_id:
            raise ValueError("current Core input receipt changed")
        binary = ROOT / f"core/build/bin/{platform}/{'x2t.exe' if platform == 'win_64' else 'x2t'}"
        producer.update({"sourceSha": os.environ.get("GITHUB_SHA", ""),
                         "runId": os.environ.get("GITHUB_RUN_ID", ""),
                         "binarySha256": ci_handoff.sha256(binary)})
        if platform == "win_64":
            modules = {item.name.lower(): item for item in binary.parent.iterdir() if item.is_file()}
            producer["compiledModules"] = {name: ci_handoff.sha256(modules[name])
                                           for name in ("x2t.exe", "graphics.dll", "pdffile.dll")}
        write_json(ROOT / f"dist/core-producer-{platform}.json", producer)
    elif args.command in ("pack", "restore"):
        handoff = argparse.Namespace(archive=str(archive), stage="build", platform=platform,
                                     source_sha=args.core_id, path=paths(platform), optional=[])
        if args.command == "pack":
            check(platform, args.core_id)
            ci_handoff.create(handoff)
        else:
            ci_handoff.restore(handoff)
    producer = check(platform, args.core_id)
    if args.command in ("record", "restore"):
        reuse = {"coreId": args.core_id, "platform": platform,
                 "reused": args.command == "restore", "sourceSha": os.environ.get("GITHUB_SHA", ""),
                 "producerSourceSha": producer["sourceSha"], "producerRunId": producer["runId"]}
        write_json(ROOT / f"dist/core-reuse-{platform}.json", reuse)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
                output.write(f"Core `{platform}`: {'reused verified build' if reuse['reused'] else 'compiled'}; "
                             f"input `{args.core_id}`; producer `{producer['sourceSha']}` / run `{producer['runId']}`.\n")
    print(f"Core input ID {args.core_id}; compiled by {producer['sourceSha']} / run {producer['runId']}")


if __name__ == "__main__":
    main()

