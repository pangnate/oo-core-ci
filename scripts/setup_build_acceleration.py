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


def main() -> None:
    lock = json.loads((ROOT / "config/build-acceleration.json").read_text(encoding="utf-8"))
    cache = Path(os.environ.get("SCCACHE_PATH") or shutil.which("sccache") or "").resolve()
    if not cache.is_file():
        raise RuntimeError("the pinned sccache setup action must run first")
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
