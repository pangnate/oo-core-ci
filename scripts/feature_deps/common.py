#!/usr/bin/env python3
"""Small fail-closed primitives shared by Core feature SDK preparation cards."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class InputError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_sdk_manifest(
    manifest: dict[str, Any],
    *,
    repo_root: Path,
    platform: str,
    kind: str,
    abi: str,
    required_roles: set[str] | None = None,
    allowed_roots: tuple[Path, ...] = (),
) -> dict[str, Path]:
    """Validate manifest shape, exact platform/ABI input identity and hashes.

    Only entries marked verified are eligible for build use. Unavailable/planned
    entries are valid inventory records but never satisfy a required role.
    """
    required_root_keys = {"schemaVersion", "sdkId", "kind", "platform", "abi", "entries"}
    if set(manifest) != required_root_keys:
        raise InputError("SDK manifest has missing or unsupported root fields")
    if manifest.get("schemaVersion") != 1:
        raise InputError("SDK manifest schemaVersion must be 1")
    if not isinstance(manifest.get("sdkId"), str) or not manifest["sdkId"].strip():
        raise InputError("SDK manifest sdkId is required")
    if manifest.get("platform") != platform:
        raise InputError("SDK manifest platform mismatch")
    if manifest.get("kind") != kind or kind not in {"development", "build", "runtime"}:
        raise InputError("SDK manifest kind mismatch")
    if not isinstance(manifest.get("abi"), str) or not manifest["abi"].strip():
        raise InputError("SDK manifest ABI is required")
    if manifest["abi"] != abi:
        raise InputError("SDK manifest ABI mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise InputError("SDK manifest entries must be a non-empty array")

    roots = (repo_root.resolve(), *(root.resolve() for root in allowed_roots))
    verified: dict[str, Path] = {}
    seen: set[str] = set()
    covered_roles: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise InputError("SDK manifest entries must be objects")
        allowed_entry_keys = {"id", "role", "status", "source", "path", "sha256", "reason"}
        if not {"id", "role", "status", "source"}.issubset(entry) or set(entry) - allowed_entry_keys:
            raise InputError("SDK manifest entry does not match its schema")
        entry_id, role, status = entry.get("id"), entry.get("role"), entry.get("status")
        if not all(isinstance(value, str) and value.strip() for value in (entry_id, role)):
            raise InputError("SDK manifest entry id and role are required")
        if entry_id in seen:
            raise InputError(f"duplicate SDK manifest entry: {entry_id}")
        seen.add(entry_id)
        if status not in {"verified", "unavailable", "planned"}:
            raise InputError(f"invalid input status for {entry_id}")
        if not isinstance(entry.get("source"), str) or not entry["source"].strip():
            raise InputError(f"source is required for {entry_id}")
        if status == "verified":
            rel = entry.get("path")
            expected = entry.get("sha256")
            if not isinstance(rel, str) or not rel or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise InputError(f"verified input requires path and SHA-256: {entry_id}")
            path = Path(rel)
            if not path.is_absolute():
                path = repo_root / path
            path = path.resolve()
            if not any(_inside(path, root) for root in roots):
                raise InputError(f"SDK input escapes approved roots: {entry_id}")
            if not path.is_file():
                raise InputError(f"verified SDK input is missing: {entry_id}")
            if sha256_file(path) != expected.lower():
                raise InputError(f"SDK input hash mismatch: {entry_id}")
            verified[entry_id] = path
            covered_roles.add(role)
        else:
            if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                raise InputError(f"unverified input requires a reason: {entry_id}")
            if "sha256" in entry or "path" in entry:
                raise InputError(f"unverified input cannot carry an artifact path/hash: {entry_id}")

    missing_roles = (required_roles or set()) - covered_roles
    if missing_roles:
        raise InputError("required SDK roles are not verified: " + ", ".join(sorted(missing_roles)))
    return verified


def _safe_member_path(raw_name: str) -> PurePosixPath:
    normalized = raw_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise InputError(f"unsafe archive member path: {raw_name!r}")
    if path.parts and ":" in path.parts[0]:
        raise InputError(f"drive/ADS archive member path is forbidden: {raw_name!r}")
    return path


def safe_extract_archive(
    archive: Path,
    destination: Path,
    *,
    scratch_root: Path,
    max_members: int = 100_000,
    max_unpacked_bytes: int = 2 * 1024**3,
) -> Path:
    """Extract regular files only to a new owned directory under scratch_root."""
    archive = archive.resolve()
    destination = destination.resolve()
    scratch_root = scratch_root.resolve()
    if not _inside(destination, scratch_root):
        raise InputError("extraction destination is outside the approved scratch root")
    if destination.exists():
        raise InputError("extraction destination already exists; refusing to clean or reuse it")
    if not archive.is_file():
        raise InputError(f"archive is missing: {archive}")

    destination.mkdir(parents=True)
    total_bytes = 0
    members = 0
    try:
        def output_path(name: str) -> Path:
            rel = _safe_member_path(name)
            target = (destination / Path(*rel.parts)).resolve()
            if not _inside(target, destination):
                raise InputError(f"archive member escapes extraction root: {name!r}")
            return target

        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as package:
                infos = package.infolist()
                if len(infos) > max_members:
                    raise InputError("archive contains too many members")
                for info in infos:
                    members += 1
                    target = output_path(info.filename)
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise InputError("symbolic links are forbidden in SDK archives")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    total_bytes += info.file_size
                    if total_bytes > max_unpacked_bytes:
                        raise InputError("archive expands beyond configured size limit")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        else:
            with tarfile.open(archive, "r:*") as package:
                infos = package.getmembers()
                if len(infos) > max_members:
                    raise InputError("archive contains too many members")
                for info in infos:
                    members += 1
                    target = output_path(info.name)
                    if info.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    if not info.isfile():
                        raise InputError("links and special files are forbidden in SDK archives")
                    total_bytes += info.size
                    if total_bytes > max_unpacked_bytes:
                        raise InputError("archive expands beyond configured size limit")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = package.extractfile(info)
                    if source is None:
                        raise InputError(f"cannot read archive member: {info.name}")
                    with source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        return destination
    except Exception:
        # This exact directory was proven absent and created by this invocation.
        shutil.rmtree(destination)
        raise


def run_recipe(command: list[str], *, cwd: Path, timeout: float, env: dict[str, str] | None = None) -> dict[str, Any]:
    if not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise InputError("recipe command must be a non-empty argument array")
    if timeout <= 0:
        raise InputError("recipe timeout must be positive")
    cwd = cwd.resolve()
    if not cwd.is_dir():
        raise InputError(f"recipe working directory does not exist: {cwd}")
    kwargs: dict[str, Any] = {"cwd": cwd, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                              "text": True, "encoding": "utf-8", "errors": "replace", "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise InputError(f"cannot start command {command[0]!r} in {cwd}: {exc}") from exc
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = exc.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            tail, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            tail, _ = process.communicate()
        output += tail or ""
    return {"command": command, "cwd": str(cwd), "pid": process.pid,
            "exitCode": process.returncode if process.returncode is not None else -9,
            "timedOut": timed_out, "durationSeconds": round(time.monotonic() - started, 3),
            "output": output}


def probe_windows_toolchain(*, vswhere: Path | None = None, qmake: Path | None = None) -> dict[str, Any]:
    if vswhere is None:
        program_files = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        vswhere = Path(program_files) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    missing: list[str] = []
    result: dict[str, Any] = {"platform": "windows-amd64", "vswhere": str(vswhere), "missing": missing}
    if not vswhere.is_file():
        missing.append("vswhere.exe")
        result["visualStudio"] = None
    else:
        found = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property",
                                "installationPath"], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        install = Path(found.stdout.strip()) if found.returncode == 0 and found.stdout.strip() else None
        result["visualStudio"] = str(install) if install else None
        vcvars = install / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat" if install else None
        msvc_root = install / "VC" / "Tools" / "MSVC" if install else None
        v142 = sorted((p for p in msvc_root.glob("14.29*") if p.is_dir()), reverse=True) if msvc_root and msvc_root.is_dir() else []
        result["vcvarsall"] = str(vcvars) if vcvars and vcvars.is_file() else None
        result["msvcV142"] = str(v142[0]) if v142 else None
        if not v142 or not vcvars or not vcvars.is_file():
            missing.append("MSVC v142 (14.29) and vcvarsall.bat")
    if qmake is None:
        qmake = Path("vendor/work/qt-win/Qt-5.15.2/msvc2019_64/bin/qmake.exe")
    result["qmake"] = str(qmake.resolve()) if qmake.is_file() else None
    result["qtVersion"] = None
    if qmake.is_file():
        run = subprocess.run([str(qmake), "-v"], check=False, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        output = (run.stdout + run.stderr).strip()
        result["qtProbeOutput"] = output
        if run.returncode == 0 and "5.15.2" in output and "msvc2019_64" in str(qmake).lower():
            result["qtVersion"] = "5.15.2-msvc2019_64"
        else:
            missing.append("Qt 5.15.2 msvc2019_64 qmake probe")
    else:
        missing.append("Qt 5.15.2 msvc2019_64 qmake.exe")
    result["available"] = not missing
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-windows", action="store_true")
    parser.add_argument("--vswhere", type=Path)
    parser.add_argument("--qmake", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)
    if not args.probe_windows:
        parser.error("select an operation")
    result = probe_windows_toolchain(vswhere=args.vswhere, qmake=args.qmake)
    content = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0 if result["available"] or args.allow_missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
