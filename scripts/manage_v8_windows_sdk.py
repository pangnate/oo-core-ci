#!/usr/bin/env python3
"""Publish a verified V8 SDK once, or restore it without building V8/Core."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/feature_deps"))
from common import InputError, safe_extract_archive, sha256_file, validate_sdk_manifest

SDK_DIR = "v8-windows-x64-sdk"
ARCHIVE = SDK_DIR + ".zip"
CHECKSUM = ARCHIVE + ".sha256"
RECEIPT = "sdk-release.json"
SOURCE = "sdk-source.json"
LIBRARY = "lib/win_64/release/obj/v8_monolith.lib"


def load_lock() -> dict:
    return json.loads((ROOT / "config/v8-windows.lock.json").read_text(encoding="utf-8"))


def identity(lock: dict) -> dict[str, str]:
    # Formatting and unrelated Core feature patches do not invalidate the SDK.
    canonical = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return {"sdk-key": digest, "release-tag": "v8-windows-x64-" + digest}


def emit(**values: object) -> None:
    for key, value in values.items():
        value = str(value).replace("\r", "").replace("\n", "")
        print(f"{key}={value}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"{key}={value}\n")


def gh(*arguments: str) -> str:
    result = subprocess.run(["gh", *arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=1800)
    if result.returncode:
        raise InputError(f"gh {arguments[0]} failed: {result.stderr.strip()}")
    return result.stdout


def api(path: str, *, missing_ok: bool = False) -> dict | None:
    try:
        return json.loads(gh("api", path))
    except InputError as exc:
        # Authentication, network, and rate-limit failures must not trigger builds.
        if missing_ok and "HTTP 404" in str(exc):
            return None
        raise


def validate_repo(repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise InputError("repository must have the form owner/name")
    return repo


def archive_hash(directory: Path) -> str:
    checksum = (directory / CHECKSUM).read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  " + re.escape(ARCHIVE), checksum)
    if not match or sha256_file(directory / ARCHIVE) != match[1]:
        raise InputError("SDK archive SHA256 mismatch or malformed checksum")
    return match[1]


def validate_sdk(sdk: Path, lock: dict) -> dict:
    sdk = sdk.resolve()
    manifest = json.loads((sdk / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((sdk / "provenance.json").read_text(encoding="utf-8"))
    if manifest.get("sdkId") != lock["sdkId"]:
        raise InputError("SDK identity mismatch")
    expected = {"schemaVersion": 1, "sdkId": lock["sdkId"], "coreRef": lock["coreRef"],
                "buildToolsRef": lock["buildToolsRef"], "v8Ref": lock["v8"]["ref"],
                "depotToolsRef": lock["depotTools"]["ref"], "gnArgs": lock["gnArgs"], "abi": lock["abi"],
                "probe": {"source": "1 + 2", "expected": 3, "status": "passed"}}
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise InputError("SDK provenance revision/GN/ABI/probe mismatch")
    if "sdkLockSha256" in provenance and provenance["sdkLockSha256"] != identity(lock)["sdk-key"]:
        raise InputError("SDK input lock fingerprint mismatch")
    normalized = copy.deepcopy(manifest)
    layouts = {"v8-headers": ("include", "include-headers.zip"), "v8-monolith": ("library", LIBRARY)}
    entries = normalized.get("entries", [])
    if not isinstance(entries, list) or len(entries) != 2:
        raise InputError("V8 SDK must contain exactly the headers and monolith entries")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") not in layouts:
            raise InputError("unexpected V8 SDK manifest entry")
        role, relative = layouts[entry["id"]]
        # Accept first-generation Actions packages without changing their bytes.
        if entry.get("path") not in {relative, f"dist/{SDK_DIR}/{relative}"} or entry.get("role") != role:
            raise InputError("unexpected V8 SDK layout")
        entry["path"] = relative
    validate_sdk_manifest(normalized, repo_root=sdk, platform=lock["platform"], kind="development",
                          abi=lock["abi"], required_roles={"include", "library"})
    files = {p.relative_to(sdk / "include").as_posix(): p
             for p in (sdk / "include").rglob("*") if p.is_file()}
    if not {"v8.h", "libplatform/libplatform.h"}.issubset(files):
        raise InputError("V8 public headers are incomplete")
    with zipfile.ZipFile(sdk / "include-headers.zip") as headers:
        names = [info.filename for info in headers.infolist() if not info.is_dir()]
        if len(set(names)) != len(names) or set(names) != set(files):
            raise InputError("extracted headers do not match the verified headers archive")
        for name in names:
            if files[name].is_symlink():
                raise InputError("SDK headers cannot be symlinks")
            with headers.open(name) as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != sha256_file(files[name]):
                    raise InputError(f"SDK header content mismatch: {name}")
    return {"sdkLockSha256": identity(lock)["sdk-key"],
            "librarySha256": sha256_file(sdk / LIBRARY), "manifestSha256": sha256_file(sdk / "manifest.json")}


def unpack(directory: Path, destination: Path, lock: dict) -> Path:
    archive_hash(directory)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to((ROOT / "core").resolve()):
        raise InputError("SDK destination already exists or points into official Core source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".v8-unpack-", dir=destination.parent) as temporary:
        scratch = Path(temporary)
        extracted = safe_extract_archive(directory / ARCHIVE, scratch / "unpacked", scratch_root=scratch,
                                         max_unpacked_bytes=4 * 1024**3)
        if {p.name for p in extracted.iterdir()} != {SDK_DIR}:
            raise InputError("unexpected SDK archive root layout")
        sdk = extracted / SDK_DIR
        validate_sdk(sdk, lock)
        shutil.move(str(sdk), str(destination))
    return destination


def validate_release_bundle(directory: Path, lock: dict, repo: str) -> dict:
    digest = archive_hash(directory)
    receipt = json.loads((directory / RECEIPT).read_text(encoding="utf-8"))
    expected = {"schemaVersion": 1, "repository": repo, "releaseTag": identity(lock)["release-tag"],
                "sdkLockSha256": identity(lock)["sdk-key"], "archive": ARCHIVE, "archiveSha256": digest}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise InputError("fixed SDK release receipt does not match repository/lock/archive")
    return receipt


def restore(repo: str, directory: Path, destination: Path, lock: dict, *, allow_missing: bool = False) -> bool:
    tag = identity(lock)["release-tag"]
    if not directory.exists():
        release = api(f"repos/{repo}/releases/tags/{tag}", missing_ok=True)
        if release is None:
            if allow_missing:
                emit(found="false")
                return False
            raise InputError("fixed V8 SDK is missing; run build-v8-windows with operation=build or promote once")
        if release.get("draft"):
            raise InputError("SDK release is still a draft; publication must be completed explicitly")
        directory.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".v8-download-", dir=directory.parent) as temporary:
            download = Path(temporary)
            gh("release", "download", tag, "--repo", repo, "--dir", str(download),
               "--pattern", ARCHIVE, "--pattern", CHECKSUM, "--pattern", RECEIPT)
            validate_release_bundle(download, lock, repo)
            shutil.move(str(download), str(directory))
    validate_release_bundle(directory, lock, repo)
    sdk = unpack(directory, destination, lock)
    shutil.copy2(directory / RECEIPT, sdk / RECEIPT)
    emit(found="true", **{"sdk-root": sdk, "include-root": sdk / "include", "library-path": sdk / LIBRARY,
                          "archive-sha256": archive_hash(directory)})
    return True


def import_run(repo: str, run_id: str, directory: Path, lock: dict) -> None:
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise InputError("source run ID must be a positive integer")
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    if (run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("head_repository", {}).get("full_name", "").lower() != repo.lower()
            or run.get("path") != ".github/workflows/build-v8-windows.yml"):
        raise InputError("source run must be a successful V8 SDK workflow in this repository")
    source_sha = run.get("head_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise InputError("source workflow did not report a commit SHA")
    source_lock = api(f"repos/{repo}/contents/config/v8-windows.lock.json?ref={source_sha}")
    if json.loads(base64.b64decode(source_lock["content"])) != lock:
        raise InputError("source run used a different V8 input lock")
    if directory.exists():
        raise InputError("source artifact destination already exists")
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".v8-import-", dir=directory.parent) as temporary:
        download = Path(temporary)
        gh("run", "download", run_id, "--repo", repo, "--name", SDK_DIR, "--dir", str(download))
        archive_hash(download)
        (download / SOURCE).write_text(json.dumps({"repository": repo, "runId": run_id, "commit": source_sha},
                                                 indent=2) + "\n", encoding="utf-8")
        shutil.move(str(download), str(directory))


def probe_sdk(sdk: Path, receipt: Path, lock: dict) -> None:
    if os.name != "nt" or not shutil.which("cl"):
        raise InputError("native SDK probe requires a Windows MSVC v142 developer shell")
    verified = validate_sdk(sdk, lock)
    from build_v8_windows_sdk import probe
    with tempfile.TemporaryDirectory(prefix="v8-sdk-probe-") as temporary:
        probe(sdk.resolve(), sdk.resolve() / LIBRARY, Path(temporary), os.environ.copy())
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({**verified, "status": "passed", "source": "1 + 2", "expected": 3},
                                  indent=2) + "\n", encoding="utf-8")


def install_into_staging(sdk: Path, staging: Path, lock: dict, *, repo_root: Path = ROOT) -> Path:
    """Fill qmake's existing dependency layout in an owned generated tree only."""
    verified = validate_sdk(sdk, lock)
    staging = staging.resolve()
    if (not staging.is_relative_to((repo_root / "vendor/work").resolve())
            or staging.is_relative_to((repo_root / "core").resolve())):
        raise InputError("SDK installation requires isolated staging under vendor/work")
    marker = staging / ".core-staging-owner"
    if not marker.is_file() or marker.read_text(encoding="utf-8") != "stage_core_source.py\n":
        raise InputError("SDK installation requires a stage_core_source.py owner marker")
    receipt_path = staging / "core-staging-receipt.json"
    source = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (source.get("coreRef") != lock["coreRef"]
            or source.get("stagedCorePath") != str(staging / "core")):
        raise InputError("staging Core identity/path mismatch")
    destination = staging / "core/Common/3dParty/v8_89/v8"
    if not destination.resolve().is_relative_to(staging) or destination.exists():
        raise InputError("staging V8 destination escapes staging or already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".v8-install-", dir=destination.parent) as temporary:
        prepared = Path(temporary) / "v8"
        shutil.copytree(sdk / "include", prepared / "include")
        library = prepared / "out.gn/win_64/release/obj/v8_monolith.lib"
        library.parent.mkdir(parents=True)
        shutil.copy2(sdk / LIBRARY, library)
        (prepared / ".v8-sdk-input.json").write_text(json.dumps({**verified,
            "coreStagingReceiptSha256": sha256_file(receipt_path), "sdkRoot": str(sdk.resolve())},
            indent=2) + "\n", encoding="utf-8")
        shutil.move(str(prepared), str(destination))
    emit(**{"core-v8-root": destination})
    return destination


def publish(repo: str, directory: Path, probe_receipt: Path, lock: dict) -> None:
    tag = identity(lock)["release-tag"]
    if api(f"repos/{repo}/releases/tags/{tag}", missing_ok=True) is not None:
        raise InputError("SDK release already exists; refusing to replace assets (use operation=reuse)")
    with tempfile.TemporaryDirectory(prefix="v8-sdk-publish-") as temporary:
        verified = validate_sdk(unpack(directory, Path(temporary) / "sdk", lock), lock)
    verified_probe = json.loads(probe_receipt.read_text(encoding="utf-8"))
    if verified_probe != {**verified, "status": "passed", "source": "1 + 2", "expected": 3}:
        raise InputError("SDK was not probed successfully after extraction")
    if (directory / SOURCE).is_file():
        source = json.loads((directory / SOURCE).read_text(encoding="utf-8"))
    else:
        source = {"repository": repo, "runId": os.environ.get("GITHUB_RUN_ID", ""),
                  "commit": os.environ.get("GITHUB_SHA", "")}
    if (source.get("repository") != repo or not re.fullmatch(r"[1-9][0-9]*", source.get("runId", ""))
            or not re.fullmatch(r"[0-9a-f]{40}", source.get("commit", ""))):
        raise InputError("publication requires the originating workflow run and commit")
    receipt = {"schemaVersion": 1, "repository": repo, "releaseTag": tag,
               "sdkLockSha256": identity(lock)["sdk-key"], "archive": ARCHIVE,
               "archiveSha256": archive_hash(directory), "source": source}
    (directory / RECEIPT).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    notes = directory / "sdk-release-notes.md"
    notes.write_text(f"Fixed Windows x64 V8 SDK.\n\nLock SHA256: {receipt['sdkLockSha256']}\n\n"
                     f"Archive SHA256: {receipt['archiveSha256']}\n\n"
                     f"Source: https://github.com/{repo}/actions/runs/{source['runId']}\n\n"
                     "Public headers and static monolith; MSVC v142 14.29 /MD. Native JS probe passed.\n"
                     "Do not replace assets under this tag; change the SDK lock for a new binary recipe.\n",
                     encoding="utf-8")
    # Draft first: consumers never observe a partially uploaded SDK. No --clobber.
    gh("release", "create", tag, str(directory / ARCHIVE), str(directory / CHECKSUM), str(directory / RECEIPT),
       "--repo", repo, "--draft", "--target", source["commit"], "--title", lock["sdkId"],
       "--notes-file", str(notes))
    gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest=false")
    with tempfile.TemporaryDirectory(prefix="v8-sdk-redownload-") as temporary:
        download = Path(temporary)
        gh("release", "download", tag, "--repo", repo, "--dir", str(download),
           "--pattern", ARCHIVE, "--pattern", CHECKSUM, "--pattern", RECEIPT)
        if validate_release_bundle(download, lock, repo) != receipt:
            raise InputError("published release did not round-trip unchanged")
    emit(**{"release-url": f"https://github.com/{repo}/releases/tag/{tag}"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("identity")
    for name in ("restore", "import-run", "publish"):
        command = commands.add_parser(name)
        command.add_argument("--repo", required=True)
        command.add_argument("--asset-dir", type=Path, required=True)
        if name == "restore":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--allow-missing", action="store_true")
        elif name == "import-run":
            command.add_argument("--run-id", required=True)
        else:
            command.add_argument("--probe-receipt", type=Path, required=True)
    command = commands.add_parser("unpack")
    command.add_argument("--asset-dir", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("probe")
    command.add_argument("--sdk-root", type=Path, required=True)
    command.add_argument("--receipt", type=Path, required=True)
    command = commands.add_parser("install")
    command.add_argument("--sdk-root", type=Path, required=True)
    command.add_argument("--staging-root", type=Path, required=True)
    args = parser.parse_args()
    lock = load_lock()
    if hasattr(args, "repo"):
        validate_repo(args.repo)
    if args.command == "identity":
        emit(**identity(lock))
    elif args.command == "restore":
        restore(args.repo, args.asset_dir, args.output, lock, allow_missing=args.allow_missing)
    elif args.command == "import-run":
        import_run(args.repo, args.run_id, args.asset_dir, lock)
    elif args.command == "unpack":
        emit(**{"sdk-root": unpack(args.asset_dir, args.output, lock)})
    elif args.command == "probe":
        probe_sdk(args.sdk_root, args.receipt, lock)
    elif args.command == "install":
        install_into_staging(args.sdk_root, args.staging_root, lock, repo_root=Path.cwd())
    else:
        publish(args.repo, args.asset_dir, args.probe_receipt, lock)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, OSError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print(f"V8 SDK error: {error}", file=sys.stderr)
        raise SystemExit(1)
