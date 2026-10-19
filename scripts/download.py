#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "feature_deps"))
from common import safe_extract_archive
from stage_core_source import inventory_fingerprint, validate_patch_series

VENDOR = ROOT / "vendor"
ARCHIVES = VENDOR / "archives"
RUNTIME = VENDOR / "runtime"
DEPS_FILE = ROOT / "config" / "deps.json"
LOCK_FILE = VENDOR / "checksums.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_official_core_source(source: Path, lock: dict) -> tuple[int, str]:
    """Fail closed if an extracted source tree is not the pinned official input."""
    count, fingerprint = inventory_fingerprint(source)
    if count != lock.get("files") or fingerprint != lock.get("extractedTreeFingerprint"):
        raise RuntimeError(
            f"Core source fingerprint mismatch: files={count}, sha256={fingerprint}; "
            f"expected files={lock.get('files')}, sha256={lock.get('extractedTreeFingerprint')}"
        )
    return count, fingerprint


def download(url: str, dest: Path, expected_sha: str | None = None, retries: int = 5) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        digest = sha256(dest)
        if not expected_sha or digest.lower() == expected_sha.lower():
            print(f"[reuse] {dest.name}  sha256={digest}")
            return digest
        raise RuntimeError(f"Existing input has wrong SHA256 and was preserved: {dest}; expected {expected_sha}, got {digest}")

    tmp = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": "basemetas-onlyoffice-x2t-bootstrap/1.0"}
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            print(f"[download {attempt}/{retries}] {url}")
            with urllib.request.urlopen(req, timeout=60) as src, tmp.open("wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            os.replace(tmp, dest)
            digest = sha256(dest)
            if expected_sha and digest.lower() != expected_sha.lower():
                dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"SHA256 mismatch for {dest.name}: expected {expected_sha}, got {digest}"
                )
            print(f"[ok] {dest.name}  sha256={digest}")
            return digest
        except Exception as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"Failed to download {url}: {last_error}")


def extract_github_tar(archive: Path, target: Path) -> None:
    if target.exists():
        raise RuntimeError(f"Refusing to replace existing official source directory: {target}")
    temp_dir = Path(tempfile.mkdtemp(prefix="extract-", dir=str(ROOT)))
    try:
        unpacked = temp_dir / "unpacked"
        safe_extract_archive(archive, unpacked, scratch_root=temp_dir)
        roots = [p for p in unpacked.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(f"Unexpected archive layout in {archive}: {roots}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(roots[0]), str(target))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def pack_linux_runtime(source: Path, dest: Path) -> str:
    if not source.is_dir():
        raise FileNotFoundError(source)
    files = [p for p in source.rglob("*") if p.is_file() or p.is_symlink()]
    so_files = [p for p in files if ".so" in p.name]
    if not so_files:
        raise RuntimeError(f"No *.so* files found in {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz", dereference=False) as tf:
        for p in files:
            if ".so" in p.name:
                tf.add(p, arcname=p.relative_to(source).as_posix(), recursive=False)
    digest = sha256(dest)
    print(f"[runtime] {dest.name}: {len(so_files)} entries  sha256={digest}")
    return digest


def pack_windows_runtime(source: Path, dest: Path) -> str:
    if not source.is_dir():
        raise FileNotFoundError(source)
    dlls = [p for p in source.rglob("*.dll") if p.is_file()]
    if not dlls:
        raise RuntimeError(f"No DLL files found in {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(dlls):
            zf.write(p, arcname=p.relative_to(source).as_posix())
    digest = sha256(dest)
    print(f"[runtime] {dest.name}: {len(dlls)} DLLs  sha256={digest}")
    return digest


def write_baseline(core_ref: str, build_tools_ref: str) -> None:
    patches_dir = ROOT / "patches" / "core"
    # Only the default, explicitly enabled series belongs to the baseline.
    # Unbuilt candidate files may coexist here without entering a running POC.
    series = json.loads((patches_dir / "series.json").read_text(encoding="utf-8"))
    core_lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))["core-source"]
    validate_patch_series(series, core_lock)
    if series["coreRef"] != core_ref:
        raise RuntimeError("active Core patch series does not match requested baseline")
    patches = []
    for entry in series["patches"]:
        path = ROOT / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"active Core patch is missing or hash-mismatched: {entry['path']}")
        patches.append(entry["path"])
    overlay_root = ROOT / "overlays" / "core"
    overlays = sorted(path.relative_to(overlay_root).as_posix() for path in overlay_root.rglob("*") if path.is_file()) if overlay_root.exists() else []
    data = {
        "coreRef": core_ref,
        "buildToolsRef": build_tools_ref,
        "corePatches": patches,
        "coreOverlays": overlays,
        "coreBuildPatches": ["scripts/patch_x2t_sln.py"],
        "note": "Core source is fetched from the pinned ONLYOFFICE/core ref; project patches and overlays are maintained separately. Runtime libraries must match this baseline."
    }
    (ROOT / "ci").mkdir(exist_ok=True)
    (ROOT / "ci" / "baseline.json").write_text(json.dumps(data, indent=2), encoding="utf-8")



def detect_dependency_inputs(defaults: dict) -> dict:
    """Detect dependency versions/URLs from the downloaded baseline where practical."""
    out = json.loads(json.dumps(defaults))
    boost_py = ROOT / "build_tools/scripts/core_common/modules/boost.py"
    icu_py = ROOT / "build_tools/scripts/core_common/modules/icu.py"
    brotli_py = ROOT / "core/Common/3dParty/brotli/make.py"
    qt_py = ROOT / "build_tools/tools/linux/qt_binary_fetch.py"
    sysroot_py = ROOT / "build_tools/tools/linux/sysroot/fetch.py"

    if boost_py.exists():
        t = boost_py.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'boost_1_(\d+)_0', t)
        if m:
            minor = m.group(1)
            ver = f"1.{int(minor)}.0"
            out["boost"]["version"] = ver
            mv = re.search(r'common_check_version\(\s*["\']boost["\']\s*,\s*["\']([^"\']+)', t)
            if mv: out["boost"]["moduleVersion"] = mv.group(1)
            out["boost"]["url"] = f"https://archives.boost.io/release/{ver}/source/boost_1_{minor}_0.tar.bz2"
            if ver != "1.72.0":
                out["boost"]["sha256"] = None

    if icu_py.exists():
        t = icu_py.read_text(encoding="utf-8", errors="ignore")
        ma = re.search(r'icu_major\s*=\s*[\"\'](\d+)[\"\']', t)
        mi = re.search(r'icu_minor\s*=\s*[\"\'](\d+)[\"\']', t)
        if ma and mi:
            major, minor = ma.group(1), mi.group(1)
            out["icu"]["version"] = f"{major}.{minor}"
            mv = re.search(r'check_module_version\(\s*["\']([^"\']+)', t)
            if mv: out["icu"]["moduleVersion"] = mv.group(1)
            out["icu"]["url"] = f"https://github.com/unicode-org/icu/releases/download/release-{major}-{minor}/icu4c-{major}_{minor}-src.tgz"
            out["icu"]["sha256"] = None

    if brotli_py.exists():
        t = brotli_py.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'checkout[\"\']?\s*,\s*[\"\']([0-9a-f]{40})[\"\']', t)
        if not m:
            m = re.search(r'[\"\']checkout[\"\']\s*,\s*[\"\']([0-9a-f]{40})[\"\']', t)
        if m:
            commit = m.group(1)
            out["brotli"]["commit"] = commit
            mv = re.search(r'check_module_version\(\s*["\']([^"\']+)', t)
            if mv: out["brotli"]["moduleVersion"] = mv.group(1)
            out["brotli"]["url"] = f"https://github.com/google/brotli/archive/{commit}.tar.gz"
            out["brotli"]["sha256"] = None

    if qt_py.exists():
        t = qt_py.read_text(encoding="utf-8", errors="ignore")
        base_m = re.search(r'URL\s*=\s*[\"\']([^\"\']+)[\"\']', t)
        amd = re.search(r'[\"\']amd64[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', t)
        arm = re.search(r'[\"\']arm64[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', t)
        if base_m and amd and arm:
            out["qt_linux_amd64"]["url"] = base_m.group(1) + amd.group(1)
            out["qt_linux_arm64"]["url"] = base_m.group(1) + arm.group(1)
            out["qt_linux_amd64"]["filename"] = amd.group(1)
            out["qt_linux_arm64"]["filename"] = arm.group(1)
            qv = re.search(r'qt_binary_([^_]+)_gcc_64', amd.group(1))
            if qv:
                out["qt_linux_amd64"]["version"] = qv.group(1)
                out["qt_linux_arm64"]["version"] = qv.group(1)

    if sysroot_py.exists():
        t = sysroot_py.read_text(encoding="utf-8", errors="ignore")
        base_m = re.search(r'URL\s*=\s*[\"\']([^\"\']+)[\"\']', t)
        amd = re.search(r'[\"\']amd64[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', t)
        arm = re.search(r'[\"\']arm64[\"\']\s*:\s*[\"\']([^\"\']+)[\"\']', t)
        if base_m and amd and arm:
            out["sysroot_linux_amd64"]["url"] = base_m.group(1) + amd.group(1)
            out["sysroot_linux_arm64"]["url"] = base_m.group(1) + arm.group(1)
            out["sysroot_linux_amd64"]["filename"] = amd.group(1)
            out["sysroot_linux_arm64"]["filename"] = arm.group(1)

    return out

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download/pin ONLYOFFICE core build inputs for offline-ish GitHub Actions builds."
    )
    parser.add_argument("--core-ref", required=True, help="Exact ONLYOFFICE/core commit/tag/branch. Commit SHA is recommended.")
    parser.add_argument(
        "--build-tools-ref",
        default="a9f9895b172b09595abcafe85d56fab163f9ecb7",
        help="Exact ONLYOFFICE/build_tools commit (defaults to this repository's pinned baseline).",
    )
    parser.add_argument("--linux-amd64-libs", type=Path)
    parser.add_argument("--linux-arm64-libs", type=Path)
    parser.add_argument("--windows-amd64-dlls", type=Path)
    parser.add_argument(
        "--runtime-config",
        type=Path,
        help="Optional local JSON mapping for explicitly requested runtime packaging.",
    )
    parser.add_argument("--force-source", action="store_true")
    args = parser.parse_args()

    runtime_sources = {}
    if args.runtime_config:
        runtime_sources = json.loads(args.runtime_config.read_text(encoding="utf-8"))
        if not isinstance(runtime_sources, dict):
            raise SystemExit(f"Runtime config must be a JSON object: {args.runtime_config}")
        print(f"[runtime config] {args.runtime_config}")

    runtime_paths = {
        "linux-amd64": args.linux_amd64_libs or runtime_sources.get("linux-amd64"),
        "linux-arm64": args.linux_arm64_libs or runtime_sources.get("linux-arm64"),
        "windows-amd64": args.windows_amd64_dlls or runtime_sources.get("windows-amd64"),
    }
    requested_runtime = any(runtime_paths.values())
    for name, value in runtime_paths.items():
        if value:
            path = Path(value).expanduser().resolve()
            if not path.is_dir():
                raise SystemExit(f"Runtime bin directory for {name} does not exist: {path}")
            runtime_paths[name] = path
    runtime_source_labels = {
        "linux-amd64": "--linux-amd64-libs" if args.linux_amd64_libs else f"{args.runtime_config.name if args.runtime_config else 'runtime-config'}:linux-amd64",
        "linux-arm64": "--linux-arm64-libs" if args.linux_arm64_libs else f"{args.runtime_config.name if args.runtime_config else 'runtime-config'}:linux-arm64",
        "windows-amd64": "--windows-amd64-dlls" if args.windows_amd64_dlls else f"{args.runtime_config.name if args.runtime_config else 'runtime-config'}:windows-amd64",
    }

    ARCHIVES.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    deps_defaults = json.loads(DEPS_FILE.read_text(encoding="utf-8"))
    deps = deps_defaults
    lock: dict[str, dict[str, str]] = json.loads(LOCK_FILE.read_text(encoding="utf-8")) if LOCK_FILE.exists() else {}

    # Source trees: extracted and committed so CI does not fetch them.
    core_url = f"https://codeload.github.com/ONLYOFFICE/core/tar.gz/{urllib.parse.quote(args.core_ref, safe='')}"
    build_url = f"https://codeload.github.com/ONLYOFFICE/build_tools/tar.gz/{urllib.parse.quote(args.build_tools_ref, safe='')}"
    tmp_src = ROOT / ".download-tmp"
    tmp_src.mkdir(parents=True, exist_ok=True)
    core_tar = tmp_src / "onlyoffice-core-source.tar.gz"
    build_tar = tmp_src / "onlyoffice-build_tools-source.tar.gz"

    baseline_file = ROOT / "ci" / "baseline.json"
    existing_baseline = json.loads(baseline_file.read_text(encoding="utf-8")) if baseline_file.exists() else {}
    pinned = lock.get("core-source", {}).get("ref") == args.core_ref and lock.get("build-tools-source", {}).get("ref") == args.build_tools_ref
    if not pinned:
        raise SystemExit("Refusing to change official source refs in-place. Update the source lock in a fresh checkout.")
    core_exists = (ROOT / "core").exists()
    build_tools_exists = (ROOT / "build_tools").exists()
    same_source = (existing_baseline.get("coreRef") == args.core_ref
                   and existing_baseline.get("buildToolsRef") == args.build_tools_ref
                   and core_exists and build_tools_exists and not args.force_source)
    if same_source:
        expected = lock["core-source"].get("extractedTreeFingerprint")
        if expected:
            try:
                verify_official_core_source(ROOT / "core", lock["core-source"])
            except RuntimeError:
                raise SystemExit("Existing core/ does not match the pinned official source fingerprint; it was preserved. Use a fresh checkout to fetch pristine Core.")
        print("[reuse] core/ and build_tools/ match requested baseline and Core source fingerprint")
    else:
        if core_exists or build_tools_exists:
            raise SystemExit("Refusing to replace existing core/ or build_tools/ source input. --force-source does not overwrite source trees; use a fresh checkout.")
        core_sha = download(core_url, core_tar, lock.get("core-source", {}).get("archiveSha256"))
        build_sha = download(build_url, build_tar, lock.get("build-tools-source", {}).get("archiveSha256")
                             or lock.get("build-tools-source", {}).get("sha256"))
        lock.setdefault("core-source", {}).update({"archiveSha256": core_sha, "ref": args.core_ref, "url": core_url})
        lock.setdefault("build-tools-source", {}).update({"archiveSha256": build_sha, "ref": args.build_tools_ref, "url": build_url})
        extract_github_tar(core_tar, ROOT / "core")
        extract_github_tar(build_tar, ROOT / "build_tools")
        expected = lock.get("core-source", {}).get("extractedTreeFingerprint")
        if expected:
            try:
                verify_official_core_source(ROOT / "core", lock["core-source"])
            except RuntimeError:
                raise SystemExit("Downloaded Core extraction does not match the pinned source fingerprint; source was preserved for diagnosis.")

    deps = detect_dependency_inputs(deps_defaults)
    (VENDOR / "detected-deps.json").write_text(json.dumps(deps, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[detected dependencies]")
    for _k, _v in deps.items():
        print(f"  {_k}: {_v.get('version', _v.get('commit', ''))}  {_v.get('url', '')}")

    boost_minor = deps["boost"]["version"].split(".")[1]
    icu_major, icu_minor = deps["icu"]["version"].split(".")
    brotli_commit = deps["brotli"]["commit"]
    mapping = {
        "boost": f"boost_1_{boost_minor}_0.tar.bz2",
        "icu": f"icu4c-{icu_major}_{icu_minor}-src.tgz",
        "brotli": f"brotli-{brotli_commit}.tar.gz",
        "qt_linux_amd64": deps["qt_linux_amd64"].get("filename", "qt_binary_5.9.9_gcc_64.7z"),
        "qt_linux_arm64": deps["qt_linux_arm64"].get("filename", "qt_binary_5.9.9_gcc_arm64.7z"),
        "sysroot_linux_amd64": deps["sysroot_linux_amd64"].get("filename", "ubuntu16-amd64-sysroot.tar.gz"),
        "sysroot_linux_arm64": deps["sysroot_linux_arm64"].get("filename", "ubuntu16-arm64-sysroot.tar.gz"),
        "python3_linux": "python3.tar.gz",
    }
    for key, filename in mapping.items():
        item = deps[key]
        path = ARCHIVES / filename
        digest = download(item["url"], path, item.get("sha256"))
        lock[key] = {"sha256": digest, "url": item["url"], "file": path.relative_to(ROOT).as_posix()}

    if requested_runtime:
        RUNTIME.mkdir(parents=True, exist_ok=True)
    for platform, source, filename, pack in [
        ("linux-amd64", runtime_paths["linux-amd64"], "linux-amd64-runtime.tar.gz", pack_linux_runtime),
        ("linux-arm64", runtime_paths["linux-arm64"], "linux-arm64-runtime.tar.gz", pack_linux_runtime),
        ("windows-amd64", runtime_paths["windows-amd64"], "windows-amd64-runtime.zip", pack_windows_runtime),
    ]:
        if requested_runtime and source:
            archive = RUNTIME / filename
            digest = pack(source, archive)
            lock[f"runtime-{platform}"] = {
                "sha256": digest,
                "source": runtime_source_labels[platform],
                "file": archive.relative_to(ROOT).as_posix(),
            }

    LOCK_FILE.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
    write_baseline(args.core_ref, args.build_tools_ref)
    core_tar.unlink(missing_ok=True)
    build_tar.unlink(missing_ok=True)

    print("\nBootstrap download complete.")
    print(f"Core source: ONLYOFFICE/core@{args.core_ref}")
    print("Official Core source was not modified with project patches or overlays.")
    print("Next:")
    print("  1) On Windows, run scripts/download_windows_qt.ps1 if the Qt archive is missing")
    print("  2) Review vendor/checksums.json and ci/baseline.json")
    print("  3) git add . && git commit && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
