#!/usr/bin/env python3
"""Use the pinned compiler cache and a bounded make process pool in CI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def resolve_sccache(value: str | None = None, *, windows: bool | None = None) -> Path:
    value = value if value is not None else (os.environ.get("SCCACHE_PATH") or shutil.which("sccache"))
    if not value:
        raise RuntimeError("the pinned sccache setup action must run first")
    candidate = Path(value).resolve()
    if candidate.is_file():
        return candidate
    # sccache-action exports an extensionless SCCACHE_PATH on Windows, while
    # the release archive contains sccache.exe. Path.is_file does not use PATHEXT.
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        executable = Path(str(candidate) + ".exe")
        if executable.is_file():
            return executable
    raise RuntimeError(f"the pinned sccache executable is missing: {candidate}")


def main() -> None:
    lock = json.loads((ROOT / "config/build-acceleration.json").read_text(encoding="utf-8"))
    cache = resolve_sccache()
    version = subprocess.check_output([str(cache), "--version"], text=True).strip()
    if version != f"sccache {lock['sccacheVersion']}":
        raise RuntimeError(f"unexpected compiler cache: {version}")
    jobs = os.cpu_count() or 1
    values = {"X2T_SCCACHE": cache.as_posix(), "X2T_BUILD_JOBS": str(jobs)}
    if os.name == "nt":
        destination = ROOT / "vendor/work/build-acceleration/jom"
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / "jom.zip"
        urllib.request.urlretrieve(lock["jom"]["url"], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["jom"]["sha256"]:
            raise RuntimeError("pinned jom archive checksum mismatch")
        with zipfile.ZipFile(archive) as package:
            # Only the make executable is needed; do not extract archive paths.
            (destination / "jom.exe").write_bytes(package.read("jom.exe"))
        values["X2T_JOM"] = (destination / "jom.exe").as_posix()
        subprocess.run([values["X2T_JOM"], "/VERSION"], check=True)
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")
    print(f"Compiler cache: {version}; make jobs: {jobs}")


if __name__ == "__main__":
    main()
