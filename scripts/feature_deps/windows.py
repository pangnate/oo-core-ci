#!/usr/bin/env python3
"""Assemble and natively probe the locked Windows Core feature dependency SDK."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "feature_deps"))
from common import InputError, probe_windows_toolchain, run_recipe, safe_extract_archive, sha256_file, validate_sdk_manifest
from download import verify_official_core_source
from manage_v8_windows_sdk import identity as v8_identity, load_lock as load_v8_lock, validate_sdk as validate_v8_sdk
from stage_core_source import inventory_fingerprint, stage_core_source

SDK_LOCK_PATH = ROOT / "config" / "windows-feature-sdk.lock.json"
BASELINE_PATH = ROOT / "ci" / "baseline.json"
CHECKSUMS_PATH = ROOT / "vendor" / "checksums.json"
DEPS_LOCK_PATH = ROOT / "config" / "feature-runtime-deps.lock.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError(f"JSON root must be an object: {path}")
    return value


def canonical_sha256(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def require_inside(path: Path, root: Path, label: str) -> Path:
    path = path.resolve()
    root = root.resolve()
    if not path.is_relative_to(root):
        raise InputError(f"{label} must stay inside {root}")
    return path


def find_7zip(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit else []
    for name in ("7z.exe", "7za.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for value in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if value:
            candidates.append(Path(value) / "7-Zip" / "7z.exe")
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise InputError("7-Zip is required to extract the locked Qt archive")


def developer_environment(vcvarsall: Path, work: Path) -> dict[str, str]:
    if os.name != "nt":
        raise InputError("Windows dependency SDK assembly requires a Windows runner")
    batch_file = work / "capture-msvc-environment.cmd"
    batch_file.write_text(
        f'@echo off\r\ncall "{vcvarsall}" x64 -vcvars_ver=14.29\r\n'
        'if errorlevel 1 exit /b %errorlevel%\r\nset\r\n', encoding="ascii")
    try:
        result = subprocess.run(["cmd.exe", "/d", "/c", str(batch_file)], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
    finally:
        batch_file.unlink(missing_ok=True)
    if result.returncode:
        raise InputError(f"vcvarsall failed ({result.returncode}): {result.stderr.strip()}")
    env = os.environ.copy()
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key and not key.startswith("="):
                env[key] = value
    if not shutil.which("cl", path=env.get("PATH")) or not shutil.which("nmake", path=env.get("PATH")):
        raise InputError("MSVC v142 developer environment did not expose cl.exe and nmake.exe")
    return env


def verify_locked_inputs(core_root: Path, qt_archive: Path, v8_root: Path) -> tuple[dict, dict, dict, dict]:
    sdk_lock = read_json(SDK_LOCK_PATH)
    baseline = read_json(BASELINE_PATH)
    checksums = read_json(CHECKSUMS_PATH)
    deps_lock = read_json(DEPS_LOCK_PATH)
    core_lock = checksums.get("core-source", {})
    build_lock = checksums.get("build-tools-source", {})
    if (sdk_lock.get("schemaVersion") != 1 or sdk_lock.get("platform") != "windows-amd64"
            or sdk_lock.get("core", {}).get("ref") != baseline.get("coreRef")
            or sdk_lock.get("core", {}).get("treeSha256") != core_lock.get("treeSha256")
            or sdk_lock.get("buildTools", {}).get("ref") != baseline.get("buildToolsRef")
            or sdk_lock.get("buildTools", {}).get("treeSha256") != build_lock.get("sha256")):
        raise InputError("Windows feature SDK lock does not match the official Core/build_tools baseline")
    if (not core_root.is_dir() or not (ROOT / "build_tools").is_dir()):
        raise InputError("official core/ and build_tools/ sources must be present; run scripts/download.py first")
    verify_official_core_source(core_root, core_lock)
    qt_digest = sha256_file(qt_archive)
    if qt_digest != sdk_lock["qt"]["sha256"]:
        raise InputError(f"Qt archive hash mismatch: {qt_digest}")
    v8_lock = load_v8_lock()
    v8_info = v8_identity(v8_lock)
    if (v8_info["sdk-key"] != sdk_lock["v8"]["lockSha256"]
            or v8_info["release-tag"] != sdk_lock["v8"]["releaseTag"]):
        raise InputError("fixed V8 SDK lock does not match the Windows feature SDK lock")
    validate_v8_sdk(v8_root, v8_lock)
    release_receipt = read_json(v8_root / "sdk-release.json")
    if (release_receipt.get("releaseTag") != sdk_lock["v8"]["releaseTag"]
            or release_receipt.get("sdkLockSha256") != v8_info["sdk-key"]
            or release_receipt.get("archiveSha256") != sdk_lock["v8"]["archiveSha256"]):
        raise InputError("restored V8 release receipt does not match the feature SDK lock")
    entries = deps_lock.get("windowsAmd64", {}).get("thirdParty", [])
    v8_entry = next((entry for entry in entries if entry.get("id") == "v8-windows-sdk"), None)
    if not v8_entry or v8_entry.get("status") != "verified":
        raise InputError("feature dependency lock must record the fixed V8 SDK as verified")
    return sdk_lock, baseline, checksums, release_receipt


def install_brotli_archive(sdk_lock: dict[str, Any], staged_core: Path, scratch: Path) -> dict[str, str]:
    component = next(item for item in sdk_lock["coreSources"] if item["id"] == "brotli")
    archive = ROOT / component["archive"]
    if sha256_file(archive) != component["sha256"]:
        raise InputError("locked Brotli source archive hash mismatch")
    extracted = safe_extract_archive(archive, scratch / "brotli-unpacked", scratch_root=scratch,
                                     max_unpacked_bytes=256 * 1024**2)
    candidates = [path for path in extracted.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise InputError("Brotli archive must contain exactly one source directory")
    brotli_root = staged_core / "Common/3dParty/brotli"
    target = brotli_root / "brotli"
    if target.exists():
        raise InputError("staged Core already contains a Brotli source tree")
    brotli_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(candidates[0]), str(target))
    (brotli_root / "module.version").write_text("1\n", encoding="utf-8")
    return {"sourceRef": component["version"], "archiveSha256": component["sha256"],
            "tree": str(target.relative_to(staged_core).as_posix())}


def generate_probe_project(project: Path, staged_core: Path, probe_source: Path) -> None:
    core = staged_core.resolve().as_posix()
    source = probe_source.resolve().as_posix()
    content = f'''TEMPLATE = app
TARGET = build_deps_windows_probe
CONFIG += console release c++14
CONFIG -= debug qt app_bundle
DEFINES += OPJ_STATIC NOMINMAX
QMAKE_CFLAGS_RELEASE += /MD
QMAKE_CXXFLAGS_RELEASE += /MD
CORE_ROOT = {core}
SOURCES += {source}

INCLUDEPATH += \\
    $$CORE_ROOT/DesktopEditor/graphics/cximage/png \\
    $$CORE_ROOT/OfficeUtils/src \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11 \\
    $$CORE_ROOT/DesktopEditor/raster/Jp2/openjpeg \\
    $$CORE_ROOT/DesktopEditor/raster/Jp2/openjpeg/openjpeg-2.4.0/src/lib/openjp2

include($$CORE_ROOT/DesktopEditor/graphics/pro/freetype.pri)
include($$CORE_ROOT/Common/3dParty/brotli/brotli.pri)
include($$CORE_ROOT/Common/3dParty/harfbuzz/harfbuzz.pri)

SOURCES += $$files($$CORE_ROOT/DesktopEditor/graphics/cximage/png/*.c, false)
SOURCES += $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/crc32.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/adler32.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/deflate.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/inffast.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/inflate.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/inftrees.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/trees.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/zutil.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/uncompr.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib-1.2.11/compress.c \\
    $$CORE_ROOT/OfficeUtils/src/zlib_addon.c

OPENJPEG_ROOT = $$CORE_ROOT/DesktopEditor/raster/Jp2/openjpeg/openjpeg-2.4.0/src/lib/openjp2
SOURCES += $$files($$OPENJPEG_ROOT/*.c, false)
'''
    project.write_text(content, encoding="utf-8", newline="\n")


def source_manifest(sdk_lock: dict[str, Any], staged_core: Path, baseline: dict[str, Any],
                    checksums: dict[str, Any], brotli_receipt: dict[str, str]) -> dict[str, Any]:
    components = []
    for component in sdk_lock["coreSources"]:
        anchors = []
        for relative in component["anchors"]:
            path = ROOT / relative
            # Core files are checked against the official full-tree fingerprint;
            # matching anchors in staging ensure the probe used the isolated copy.
            staged = staged_core / Path(*Path(relative).parts[1:])
            if not path.is_file() or not staged.is_file():
                raise InputError(f"locked Core source anchor is missing: {relative}")
            source_hash = sha256_file(path)
            if source_hash != sha256_file(staged):
                raise InputError(f"staged source anchor differs from official Core: {relative}")
            anchors.append({"path": relative, "sha256": source_hash})
        components.append({"id": component["id"], "version": component["version"],
                           "recipe": component["recipe"], "anchors": anchors})
    return {
        "schemaVersion": 1,
        "coreRef": baseline["coreRef"],
        "coreTreeSha256": checksums["core-source"]["treeSha256"],
        "coreSourceInventorySha256": checksums["core-source"]["extractedTreeFingerprint"],
        "buildToolsRef": baseline["buildToolsRef"],
        "buildToolsTreeSha256": checksums["build-tools-source"]["sha256"],
        "components": components,
        "preparedBrotli": brotli_receipt,
    }


def build_and_probe(sdk_lock: dict[str, Any], staged_core: Path, qmake: Path, env: dict[str, str],
                    font: Path, work: Path) -> dict[str, Any]:
    harfbuzz_dir = staged_core / "Common/3dParty/harfbuzz"
    make_script = harfbuzz_dir / "make.py"
    if not make_script.is_file():
        raise InputError("pinned Core HarfBuzz recipe is missing")
    make_result = run_recipe([sys.executable, str(make_script)], cwd=harfbuzz_dir, timeout=900, env=env)
    if make_result["exitCode"] or make_result["timedOut"]:
        raise InputError(f"HarfBuzz source preparation failed: {make_result['output'][-4000:]}")
    generated_pri = harfbuzz_dir / "harfbuzz.pri"
    if not generated_pri.is_file() or not (harfbuzz_dir / "harfbuzz/src/hb-ft.cc").is_file():
        raise InputError("pinned HarfBuzz source generation did not produce its qmake inputs")
    expected_ref = next(item["version"] for item in sdk_lock["coreSources"] if item["id"] == "harfbuzz")
    if expected_ref not in (harfbuzz_dir / "harfbuzz/.git/HEAD").read_text(encoding="ascii", errors="replace"):
        git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=harfbuzz_dir / "harfbuzz",
                                  capture_output=True, text=True, encoding="utf-8", check=False)
        if git_head.returncode or git_head.stdout.strip() != expected_ref:
            raise InputError("HarfBuzz checkout is not the pinned source revision")

    project = work / "probe/build_deps_windows_probe.pro"
    project.parent.mkdir(parents=True)
    generate_probe_project(project, staged_core, ROOT / "tests/core-features/cpp/build_deps_windows_probe.cpp")
    qmake_probe = subprocess.run([str(qmake), "-v"], cwd=project.parent, env=env, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", check=False)
    qmake_text = (qmake_probe.stdout + qmake_probe.stderr).strip()
    if qmake_probe.returncode or "5.15.2" not in qmake_text:
        raise InputError(f"Qt qmake version probe failed: {qmake_text}")
    configure = run_recipe([str(qmake), project.name, "-spec", "win32-msvc"], cwd=project.parent,
                           timeout=300, env=env)
    if configure["exitCode"] or configure["timedOut"]:
        raise InputError(f"qmake failed: {configure['output'][-4000:]}")
    compile_result = run_recipe(["nmake", "/NOLOGO"], cwd=project.parent,
                                timeout=sdk_lock["build"]["timeoutSeconds"], env=env)
    if compile_result["exitCode"] or compile_result["timedOut"]:
        raise InputError(f"Windows dependency probe compilation/link failed: {compile_result['output'][-6000:]}")
    executable = project.parent / "release/build_deps_windows_probe.exe"
    if not executable.is_file():
        raise InputError("qmake/nmake succeeded without the expected probe executable")
    jp2 = project.parent / "probe-output.jp2"
    probe = run_recipe([str(executable), str(font.resolve()), str(jp2)], cwd=project.parent,
                       timeout=300, env=env)
    if probe["exitCode"] or probe["timedOut"] or not jp2.is_file() or jp2.stat().st_size < 12:
        raise InputError(f"native dependency probe failed: {probe['output'][-4000:]}")
    expected_outputs = set(sdk_lock["probes"])
    if not expected_outputs.issubset({line.replace("PASS ", "").split(" ", 1)[0]
                                      for line in probe["output"].splitlines()}):
        raise InputError("native probe did not report every locked capability")
    return {
        "qmake": qmake_text,
        "font": {"path": str(font.resolve()), "sha256": sha256_file(font)},
        "harfbuzzRef": expected_ref,
        "harfbuzzVersionHeaderSha256": sha256_file(harfbuzz_dir / "harfbuzz/src/hb-version.h"),
        "projectSha256": sha256_file(project),
        "executableSha256": sha256_file(executable),
        "jp2OutputSha256": sha256_file(jp2),
        "compileDurationSeconds": compile_result["durationSeconds"],
        "probeOutput": probe["output"].strip(),
        "status": "passed",
    }


def locate_font(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit else []
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates.extend([windows / "Fonts/arial.ttf", windows / "Fonts/Arial.ttf"])
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise InputError("a deterministic runner Arial font is required for the text shaping probe")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bundle_core_feature_sources(staged_core: Path, destination: Path) -> str:
    """Package only the verified source closure used by the native probe."""
    source_roots = [
        Path("DesktopEditor/freetype-2.10.4"),
        Path("Common/3dParty/harfbuzz/harfbuzz"),
        Path("Common/3dParty/brotli/brotli"),
        Path("DesktopEditor/graphics/cximage/png"),
        Path("OfficeUtils/src/zlib-1.2.11"),
        Path("DesktopEditor/raster/Jp2/openjpeg"),
    ]
    files: list[tuple[Path, str]] = []
    for relative in source_roots:
        root = staged_core / relative
        if not root.is_dir():
            raise InputError(f"verified dependency source directory is missing: {relative.as_posix()}")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise InputError(f"dependency source bundle cannot contain symlinks: {path}")
            if path.is_file():
                arcname = (Path("core") / relative / path.relative_to(root)).as_posix()
                files.append((path, arcname))
    if not files:
        raise InputError("dependency source closure is empty")
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=True) as package:
        for path, arcname in sorted(files, key=lambda item: item[1]):
            info = zipfile.ZipInfo(arcname, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            package.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return sha256_file(destination)


def assemble(args: argparse.Namespace) -> None:
    if os.name != "nt":
        raise InputError("Windows dependency SDK assembly must run on a Windows host")
    output = require_inside(args.output, ROOT, "output directory")
    work_root = require_inside(args.work_root, ROOT / "vendor/work", "work root")
    work = work_root / "windows-feature-sdk"
    archive = output.parent / "windows-feature-sdk.zip"
    if output.exists() or work.exists() or archive.exists() or archive.with_suffix(archive.suffix + ".sha256").exists():
        raise InputError("output/work destination already exists; refusing cleanup or reuse")
    sdk_lock = read_json(SDK_LOCK_PATH)
    qt_archive = ROOT / sdk_lock["qt"]["archive"]
    v8_root = args.v8_root.resolve()
    sdk_lock, baseline, checksums, v8_receipt = verify_locked_inputs(ROOT / "core", qt_archive, v8_root)
    font = locate_font(args.font)
    qt_archive = qt_archive.resolve()
    sevenzip = find_7zip(args.sevenzip)
    work_root.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True)
    qt_root = work / "qt"
    qt_root.mkdir()
    extract = run_recipe([str(sevenzip), "x", "-y", f"-o{qt_root}", str(qt_archive)], cwd=ROOT,
                         timeout=900, env=os.environ.copy())
    if extract["exitCode"] or extract["timedOut"]:
        raise InputError(f"Qt archive extraction failed: {extract['output'][-4000:]}")
    qmake = qt_root / "msvc2019_64/bin/qmake.exe"
    if not qmake.is_file():
        raise InputError("locked Qt archive has no msvc2019_64 qmake.exe")
    env_report = probe_windows_toolchain(qmake=qmake)
    if not env_report["available"]:
        raise InputError("required Windows toolchain is unavailable: " + ", ".join(env_report["missing"]))
    env = developer_environment(Path(env_report["vcvarsall"]), work)

    staging = work / "core-staging"
    stage_receipt = stage_core_source(source_root=ROOT / "core", destination=staging)
    with tempfile.TemporaryDirectory(prefix="brotli-", dir=work) as temp_name:
        brotli_info = install_brotli_archive(sdk_lock, staging / "core", Path(temp_name))
    source_info = source_manifest(sdk_lock, staging / "core", baseline, checksums, brotli_info)
    probe_info = build_and_probe(sdk_lock, staging / "core", qmake, env, font, work)

    sdk_key = canonical_sha256(sdk_lock)
    output.mkdir(parents=True)
    shutil.copy2(qt_archive, output / qt_archive.name)
    source_bundle_hash = bundle_core_feature_sources(staging / "core", output / "core-feature-sources.zip")
    write_json(output / "source-manifest.json", source_info)
    write_json(output / "toolchain-report.json", env_report)
    write_json(output / "v8-release.json", v8_receipt)
    write_json(output / "probe-receipt.json", probe_info)
    write_json(output / "staging-receipt.json", stage_receipt)
    shutil.copy2(SDK_LOCK_PATH, output / "windows-feature-sdk.lock.json")
    entries = [
        {"id": "qt-msvc2019", "role": "qt-package", "status": "verified", "source": sdk_lock["qt"]["archive"],
         "path": qt_archive.name, "sha256": sha256_file(output / qt_archive.name)},
        {"id": "v8-fixed-release", "role": "v8-release", "status": "verified", "source": sdk_lock["v8"]["releaseTag"],
         "path": "v8-release.json", "sha256": sha256_file(output / "v8-release.json")},
        {"id": "core-feature-sources", "role": "core-source-closure", "status": "verified", "source": sdk_lock["core"]["ref"],
         "path": "core-feature-sources.zip", "sha256": source_bundle_hash},
        {"id": "windows-v142-toolchain", "role": "msvc-v142", "status": "verified", "source": "windows-2022 runner",
         "path": "toolchain-report.json", "sha256": sha256_file(output / "toolchain-report.json")},
        {"id": "native-dependency-probes", "role": "native-probes", "status": "verified", "source": "Core qmake recipes",
         "path": "probe-receipt.json", "sha256": sha256_file(output / "probe-receipt.json")},
    ]
    manifest = {"schemaVersion": 1, "sdkId": sdk_lock["sdkId"], "kind": "development",
                "platform": sdk_lock["platform"], "abi": sdk_lock["abi"]["id"], "entries": entries}
    validate_sdk_manifest(manifest, repo_root=output, platform="windows-amd64", kind="development",
                          abi=sdk_lock["abi"]["id"], required_roles={"qt-package", "v8-release", "core-source-closure",
                                                                      "msvc-v142", "native-probes"})
    write_json(output / "manifest.json", manifest)
    provenance = {"schemaVersion": 1, "sdkKey": sdk_key, "lockSha256": sha256_file(SDK_LOCK_PATH),
                  "v8SdkKey": sdk_lock["v8"]["lockSha256"], "v8ArchiveSha256": v8_receipt["archiveSha256"],
                  "qtArchiveSha256": sha256_file(qt_archive), "coreRef": baseline["coreRef"],
                  "coreTreeSha256": checksums["core-source"]["treeSha256"], "buildToolsRef": baseline["buildToolsRef"],
                  "abi": sdk_lock["abi"], "probeStatus": probe_info["status"]}
    write_json(output / "provenance.json", provenance)
    artifact = archive
    with zipfile.ZipFile(artifact, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as package:
        for path in sorted(output.iterdir()):
            if path.is_file():
                package.write(path, arcname=f"{sdk_lock['sdkId']}/{path.name}")
    archive_hash = sha256_file(artifact)
    (artifact.with_suffix(artifact.suffix + ".sha256")).write_text(
        f"{archive_hash}  {artifact.name}\n", encoding="ascii")
    summary = {**provenance, "artifact": str(artifact.relative_to(ROOT).as_posix()),
               "archiveSha256": archive_hash, "artifactSize": artifact.stat().st_size}
    write_json(output / "build-receipt.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f"## Windows feature dependency SDK\n\n- SDK key: `{sdk_key}`\n"
                         f"- Archive SHA256: `{archive_hash}`\n- Core dependency probes: passed\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"sdk-key={sdk_key}\narchive-sha256={archive_hash}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v8-root", type=Path, required=True,
                        help="Verified directory output from restore-v8-windows-sdk")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/windows-feature-sdk")
    parser.add_argument("--work-root", type=Path, default=ROOT / "vendor/work")
    parser.add_argument("--sevenzip", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    assemble(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as error:
        print(f"Windows feature SDK error: {error}", file=sys.stderr)
        raise SystemExit(1)
