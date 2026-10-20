#!/usr/bin/env python3
"""Run an isolated, profile-bound Windows Core development build target."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "feature_deps"))
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402
import windows as windows_sdk  # noqa: E402
from download import verify_official_core_source  # noqa: E402
from manage_v8_windows_sdk import load_lock as load_v8_lock, validate_sdk as validate_v8_sdk  # noqa: E402
from stage_core_source import StageError, stage_core_source  # noqa: E402

PROFILE_PATH = ROOT / "config" / "windows-dev-build.profile.json"
WORK_ROOT = ROOT / "vendor" / "work"


class BuildError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    return common.sha256_file(path)


def canonical_sha256(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def require_inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise BuildError(f"{label} must stay inside {root.resolve()}")
    return resolved


def validate_profile(profile: dict[str, Any], *, repo_root: Path = ROOT) -> dict[str, Any]:
    if set(profile) != {"schemaVersion", "profileId", "platform", "core", "sdk", "targets", "build"}:
        raise BuildError("Windows dev profile has missing or unsupported fields")
    if profile.get("schemaVersion") != 1 or profile.get("platform") != "windows-amd64":
        raise BuildError("unsupported Windows dev profile version or platform")
    baseline = read_json(repo_root / "ci/baseline.json")
    checksums = read_json(repo_root / "vendor/checksums.json")
    sdk_lock = read_json(repo_root / "config/windows-feature-sdk.lock.json")
    expected_core = {"ref": baseline.get("coreRef"),
                     "treeSha256": checksums.get("core-source", {}).get("treeSha256")}
    if profile["core"] != expected_core:
        raise BuildError("Windows dev profile Core identity differs from the pinned baseline")
    sdk = profile["sdk"]
    if not isinstance(sdk, dict) or set(sdk) != {"id", "lockPath", "lockSha256", "abi"}:
        raise BuildError("Windows dev profile SDK binding has an invalid shape")
    lock_path = (repo_root / sdk["lockPath"]).resolve()
    if not lock_path.is_relative_to(repo_root.resolve()) or not lock_path.is_file():
        raise BuildError("Windows dev profile SDK lock path is invalid")
    if sha256_file(lock_path) != sdk["lockSha256"]:
        raise BuildError("Windows dev profile SDK lock hash mismatch")
    if sdk["id"] != sdk_lock.get("sdkId") or sdk["abi"] != sdk_lock.get("abi", {}).get("id"):
        raise BuildError("Windows dev profile SDK identity/ABI mismatch")
    targets = profile.get("targets")
    if not isinstance(targets, dict) or not targets:
        raise BuildError("Windows dev profile must define at least one target")
    for target, spec in targets.items():
        if (target != "dependency-probe" or not isinstance(spec, dict)
                or set(spec) != {"kind", "projectSource"} or spec.get("kind") != "qmake-probe"):
            raise BuildError(f"unsupported Windows dev target: {target}")
        project_source = (repo_root / spec["projectSource"]).resolve()
        if not project_source.is_relative_to(repo_root.resolve()) or not project_source.is_file():
            raise BuildError(f"target source is missing or escapes the repository: {target}")
    build = profile.get("build")
    if (not isinstance(build, dict) or build.get("configuration") != "release"
            or build.get("generator") != "Qt qmake + nmake"
            or not isinstance(build.get("timeoutSeconds"), int) or build["timeoutSeconds"] <= 0):
        raise BuildError("Windows dev build configuration is invalid")
    return sdk_lock


def validate_core_root(core_root: Path, *, repo_root: Path = ROOT) -> dict[str, Any]:
    core_root = core_root.resolve()
    if not core_root.is_dir():
        raise BuildError(f"Core source root is missing: {core_root}; run scripts/download.py first")
    if core_root == (repo_root / "core").resolve():
        checksums = read_json(repo_root / "vendor/checksums.json")
        try:
            verify_official_core_source(core_root, checksums["core-source"])
        except (OSError, RuntimeError, ValueError) as exc:
            raise BuildError(f"official Core source validation failed: {exc}") from exc
        return {"coreRef": checksums["core-source"]["ref"],
                "officialTreeSha256": checksums["core-source"]["treeSha256"],
                "sourceInventorySha256": checksums["core-source"]["extractedTreeFingerprint"],
                "source": str(core_root), "sourceKind": "official-source"}
    require_inside(core_root, repo_root / "vendor/work", "staged Core source")
    receipt_path = core_root.parent / "core-staging-receipt.json"
    owner_marker = core_root.parent / ".core-staging-owner"
    receipt = read_json(receipt_path)
    checksums = read_json(repo_root / "vendor/checksums.json")
    if (not owner_marker.is_file() or receipt.get("coreRef") != checksums["core-source"]["ref"]
            or receipt.get("officialTreeSha256") != checksums["core-source"]["treeSha256"]):
        raise BuildError("staged Core receipt does not match the pinned official source")
    return {"coreRef": receipt["coreRef"], "officialTreeSha256": receipt["officialTreeSha256"],
            "sourceInventorySha256": receipt.get("sourceInventorySha256Before"),
            "source": str(core_root), "sourceKind": "verified-staging",
            "stagedCoreInventorySha256": receipt.get("stagedCoreInventorySha256")}


def validate_sdk(sdk_root: Path, *, profile: dict[str, Any], sdk_lock: dict[str, Any]) -> tuple[dict, dict[str, Path]]:
    sdk_root = sdk_root.resolve()
    manifest_path = sdk_root / "manifest.json"
    manifest = read_json(manifest_path)
    abi = profile["sdk"]["abi"]
    paths = common.validate_sdk_manifest(
        manifest, repo_root=sdk_root, platform="windows-amd64", kind="development", abi=abi,
        required_roles={"qt-package", "core-source-closure", "msvc-v142", "native-probes"})
    if manifest.get("sdkId") != profile["sdk"]["id"]:
        raise BuildError("development SDK id does not match the profile")
    provenance = read_json(sdk_root / "provenance.json")
    if (provenance.get("sdkKey") != canonical_sha256(sdk_lock)
            or provenance.get("lockSha256") != profile["sdk"]["lockSha256"]
            or provenance.get("coreRef") != profile["core"]["ref"]
            or provenance.get("coreTreeSha256") != profile["core"]["treeSha256"]
            or provenance.get("abi") != sdk_lock.get("abi")
            or provenance.get("probeStatus") != "passed"):
        raise BuildError("development SDK provenance does not match the profile or verified probe")
    return manifest, paths


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_output_root(output_root: Path, identity: dict[str, Any]) -> bool:
    """Return whether an owned successful build directory can be incrementally reused."""
    output_root = require_inside(output_root, WORK_ROOT, "build output root")
    if not output_root.exists():
        return False
    marker = output_root / ".windows-dev-build.json"
    if not marker.is_file() or read_json(marker) != identity:
        raise BuildError("existing output directory is not owned by this exact profile/target/SDK")
    receipt_path = output_root / "build-receipt.json"
    if not receipt_path.is_file() or read_json(receipt_path).get("status") != "passed":
        raise BuildError("previous build did not pass; refusing to reuse its output directory")
    return True


def make_identity(*, profile: dict[str, Any], sdk_lock: dict[str, Any], target: str,
                  core_identity: dict[str, Any]) -> dict[str, Any]:
    baseline = read_json(ROOT / "ci/baseline.json")
    series = read_json(ROOT / "patches/core/series.json")
    input_paths = {"baseline": ROOT / "ci/baseline.json",
                   "checksums": ROOT / "vendor/checksums.json",
                   "patchSeries": ROOT / "patches/core/series.json",
                   "driver": Path(__file__).resolve(),
                   "windowsRecipe": ROOT / "scripts/feature_deps/windows.py",
                   "probeSource": ROOT / profile["targets"][target]["projectSource"]}
    for relative in baseline.get("coreBuildPatches", []):
        input_paths[f"buildPatch:{relative}"] = ROOT / relative
    for relative in baseline.get("coreOverlays", []):
        input_paths[f"overlay:{relative}"] = ROOT / "overlays/core" / relative
    for item in series.get("patches", []):
        input_paths[f"patch:{item.get('path')}"] = ROOT / item.get("path", "")
    input_hashes = {name: sha256_file(path) for name, path in sorted(input_paths.items())}
    profile_hash = canonical_sha256(profile)
    return {"profileId": profile["profileId"], "profileSha256": profile_hash,
            "driverSha256": input_hashes["driver"], "inputsSha256": canonical_sha256(input_hashes),
            "target": target, "platform": profile["platform"],
            "coreRef": core_identity["coreRef"],
            "coreTreeSha256": core_identity["officialTreeSha256"],
            "coreSourceInventorySha256": core_identity["sourceInventorySha256"],
            "sdkId": profile["sdk"]["id"], "sdkKey": canonical_sha256(sdk_lock),
            "abi": profile["sdk"]["abi"]}


def _prepare_harfBuzz(staged_core: Path, sdk_lock: dict[str, Any], env: dict[str, str]) -> None:
    harfbuzz_dir = staged_core / "Common/3dParty/harfbuzz"
    expected_ref = next(item["version"] for item in sdk_lock["coreSources"] if item["id"] == "harfbuzz")
    generated_pri = harfbuzz_dir / "harfbuzz.pri"
    source_dir = harfbuzz_dir / "harfbuzz"
    if generated_pri.is_file() and (source_dir / "src/hb-ft.cc").is_file():
        git = common.run_recipe(["git", "rev-parse", "HEAD"], cwd=source_dir, timeout=30, env=env)
        if git["exitCode"] == 0 and git["output"].strip() == expected_ref:
            return
    recipe_env = env.copy()
    recipe_env["GIT_CONFIG_COUNT"] = "1"
    recipe_env["GIT_CONFIG_KEY_0"] = "core.longpaths"
    recipe_env["GIT_CONFIG_VALUE_0"] = "true"
    scripts_root = str((ROOT / "build_tools/scripts").resolve())
    current = recipe_env.get("PYTHONPATH")
    recipe_env["PYTHONPATH"] = scripts_root + (os.pathsep + current if current else "")
    result = common.run_recipe([sys.executable, str(harfbuzz_dir / "make.py")], cwd=harfbuzz_dir,
                               timeout=900, env=recipe_env)
    if result["exitCode"] or result["timedOut"]:
        raise BuildError(f"HarfBuzz source preparation failed: {result['output'][-4000:]}")


def run_target(*, target: str, profile: dict[str, Any], sdk_lock: dict[str, Any],
               sdk_paths: dict[str, Path], core_root: Path, output_root: Path,
               core_identity: dict[str, Any],
               vswhere: Path | None = None, sevenzip: Path | None = None) -> dict[str, Any]:
    if os.name != "nt":
        raise BuildError("Windows dev build execution requires a Windows host; use --plan-only for static validation")
    spec = profile["targets"][target]
    identity = make_identity(profile=profile, sdk_lock=sdk_lock, target=target, core_identity=core_identity)
    output_root = require_inside(output_root, WORK_ROOT, "build output root")
    marker = output_root / ".windows-dev-build.json"
    reusable = validate_output_root(output_root, identity)
    if not reusable:
        output_root.mkdir(parents=True)
        _write_json(marker, identity)
    receipt_path = output_root / "build-receipt.json"
    receipt: dict[str, Any] = {**identity, "status": "running"}
    _write_json(receipt_path, receipt)
    try:
        qt_entries = [entry for entry in manifest["entries"]
                      if entry.get("role") == "qt-package" and entry.get("status") == "verified"]
        if len(qt_entries) != 1 or qt_entries[0].get("id") not in sdk_paths:
            raise BuildError("development SDK must contain exactly one verified Qt package")
        qt_archive = sdk_paths[qt_entries[0]["id"]]
        qt_root = output_root / "qt"
        if not qt_root.exists():
            qt_root.mkdir()
            extractor = windows_sdk.find_7zip(sevenzip)
            result = common.run_recipe([str(extractor), "x", "-y", f"-o{qt_root}", str(qt_archive)],
                                       cwd=ROOT, timeout=900, env=os.environ.copy())
            if result["exitCode"] or result["timedOut"]:
                raise BuildError(f"Qt archive extraction failed: {result['output'][-4000:]}")
        qmake = qt_root / "msvc2019_64/bin/qmake.exe"
        if not qmake.is_file():
            raise BuildError("verified Qt archive is missing msvc2019_64/bin/qmake.exe")
        toolchain = common.probe_windows_toolchain(vswhere=vswhere, qmake=qmake)
        if not toolchain.get("available"):
            raise BuildError("Windows toolchain is incomplete: " + ", ".join(toolchain.get("missing", [])))
        env, nmake = windows_sdk.developer_environment(Path(toolchain["vcvarsall"]), output_root)

        if core_root == (ROOT / "core").resolve():
            stage_dir = output_root / "core-staging"
            if stage_dir.exists():
                staged_core = stage_dir / "core"
                receipt_stage = read_json(stage_dir / "core-staging-receipt.json")
                if receipt_stage.get("coreRef") != profile["core"]["ref"]:
                    raise BuildError("existing staged source is bound to a different Core baseline")
            else:
                stage_core_source(source_root=core_root, destination=stage_dir)
                staged_core = stage_dir / "core"
        else:
            staged_core = core_root

        brotli_root = staged_core / "Common/3dParty/brotli"
        if not (brotli_root / "module.version").is_file() or not (brotli_root / "brotli").is_dir():
            import tempfile
            with tempfile.TemporaryDirectory(prefix="brotli-", dir=output_root) as scratch_name:
                windows_sdk.install_brotli_archive(sdk_lock, staged_core, Path(scratch_name))
        _prepare_harfBuzz(staged_core, sdk_lock, env)

        result = windows_sdk.build_and_probe(sdk_lock, staged_core, qmake, nmake, env,
                                             windows_sdk.locate_font(None), output_root,
                                             probe_source=ROOT / spec["projectSource"])
        receipt = {**identity, "status": "passed", "coreSource": str(staged_core.resolve()),
                   "qmake": toolchain["qmake"], "toolchain": toolchain,
                   "projectSha256": result["projectSha256"],
                   "executableSha256": result["executableSha256"],
                   "compileDurationSeconds": result["compileDurationSeconds"],
                   "probeOutput": result["probeOutput"]}
        _write_json(receipt_path, receipt)
        return receipt
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["error"] = str(exc)
        _write_json(receipt_path, receipt)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--core-root", type=Path, default=ROOT / "core")
    parser.add_argument("--v8-root", type=Path, required=True)
    parser.add_argument("--target", default="dependency-probe")
    parser.add_argument("--output-root", type=Path,
                        default=WORK_ROOT / "build-core-dev/windows-amd64-msvc142/dependency-probe")
    parser.add_argument("--vswhere", type=Path)
    parser.add_argument("--sevenzip", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    profile = read_json(args.profile.resolve())
    sdk_lock = validate_profile(profile)
    if args.target not in profile["targets"]:
        raise BuildError(f"target is not declared by the active profile: {args.target}")
    core = validate_core_root(args.core_root)
    manifest, sdk_paths = validate_sdk(args.sdk_root, profile=profile, sdk_lock=sdk_lock)
    v8_lock = load_v8_lock()
    validate_v8_sdk(args.v8_root.resolve(), v8_lock)
    plan = {"profileId": profile["profileId"], "target": args.target, "platform": profile["platform"],
            "core": core, "sdkId": manifest["sdkId"], "abi": manifest["abi"],
            "sdkRoot": str(args.sdk_root.resolve()), "outputRoot": str(args.output_root.resolve()),
            "command": "Qt qmake + nmake; isolated under vendor/work; no reset/clean step"}
    if args.plan_only:
        output = require_inside(args.output_root, WORK_ROOT, "build output root")
        identity = make_identity(profile=profile, sdk_lock=sdk_lock, target=args.target,
                                 core_identity=core)
        if output.exists():
            validate_output_root(output, identity)
            plan["previousReceiptStatus"] = "passed"
        plan["mode"] = "plan-only"
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    result = run_target(target=args.target, profile=profile, sdk_lock=sdk_lock, sdk_paths=sdk_paths,
                        core_root=args.core_root.resolve(), output_root=args.output_root, core_identity=core,
                        vswhere=args.vswhere, sevenzip=args.sevenzip)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BuildError, common.InputError, StageError, OSError, ValueError, KeyError) as error:
        print(f"Windows Core dev build error: {error}", file=sys.stderr)
        raise SystemExit(1)
