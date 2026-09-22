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


def download(url: str, dest: Path, expected_sha: str | None = None, retries: int = 5) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        digest = sha256(dest)
        if not expected_sha or digest.lower() == expected_sha.lower():
            print(f"[reuse] {dest.name}  sha256={digest}")
            return digest
        print(f"[redownload] checksum mismatch: {dest}")
        dest.unlink()

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
    temp_dir = Path(tempfile.mkdtemp(prefix="extract-", dir=str(ROOT)))
    try:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(temp_dir)
        roots = [p for p in temp_dir.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(f"Unexpected archive layout in {archive}: {roots}")
        if target.exists():
            shutil.rmtree(target)
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


def patch_core() -> None:
    script = ROOT / "scripts" / "patch_x2t_sln.py"
    import subprocess
    subprocess.run([sys.executable, str(script)], check=True)


def write_baseline(core_ref: str, build_tools_ref: str) -> None:
    data = {
        "coreRef": core_ref,
        "buildToolsRef": build_tools_ref,
        "note": "Keep local runtime SO/DLL files from the same ONLYOFFICE core baseline as coreRef."
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
    parser.add_argument("--build-tools-ref", default="master", help="Exact ONLYOFFICE/build_tools commit/tag/branch. Commit SHA is recommended.")
    parser.add_argument("--linux-amd64-libs", type=Path)
    parser.add_argument("--linux-arm64-libs", type=Path)
    parser.add_argument("--windows-amd64-dlls", type=Path)
    parser.add_argument("--force-source", action="store_true")
    args = parser.parse_args()

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
    same_source = (
        existing_baseline.get("coreRef") == args.core_ref
        and existing_baseline.get("buildToolsRef") == args.build_tools_ref
        and (ROOT / "core").is_dir()
        and (ROOT / "build_tools").is_dir()
        and not args.force_source
    )
    if same_source:
        print("[reuse] core/ and build_tools/ match requested baseline")
    else:
        core_sha = download(core_url, core_tar)
        build_sha = download(build_url, build_tar)
        lock["core-source"] = {"sha256": core_sha, "ref": args.core_ref, "url": core_url}
        lock["build-tools-source"] = {"sha256": build_sha, "ref": args.build_tools_ref, "url": build_url}
        extract_github_tar(core_tar, ROOT / "core")
        extract_github_tar(build_tar, ROOT / "build_tools")

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

    if args.linux_amd64_libs:
        d = pack_linux_runtime(args.linux_amd64_libs.resolve(), RUNTIME / "linux-amd64-runtime.tar.gz")
        lock["runtime-linux-amd64"] = {"sha256": d, "source": str(args.linux_amd64_libs.resolve()), "file": "vendor/runtime/linux-amd64-runtime.tar.gz"}
    if args.linux_arm64_libs:
        d = pack_linux_runtime(args.linux_arm64_libs.resolve(), RUNTIME / "linux-arm64-runtime.tar.gz")
        lock["runtime-linux-arm64"] = {"sha256": d, "source": str(args.linux_arm64_libs.resolve()), "file": "vendor/runtime/linux-arm64-runtime.tar.gz"}
    if args.windows_amd64_dlls:
        d = pack_windows_runtime(args.windows_amd64_dlls.resolve(), RUNTIME / "windows-amd64-runtime.zip")
        lock["runtime-windows-amd64"] = {"sha256": d, "source": str(args.windows_amd64_dlls.resolve()), "file": "vendor/runtime/windows-amd64-runtime.zip"}

    LOCK_FILE.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
    write_baseline(args.core_ref, args.build_tools_ref)
    patch_core()
    core_tar.unlink(missing_ok=True)
    build_tar.unlink(missing_ok=True)

    print("\nBootstrap download complete.")
    print("Next:")
    print("  1) On Windows, run scripts/download_windows_qt.ps1")
    print("  2) git lfs install")
    print("  3) git add . && git commit && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
