#!/usr/bin/env python3
"""Run ordinary DOCX/PPTX -> editor BIN -> OOXML smoke conversions with a built X2T."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = (ROOT / "vendor" / "work").resolve()


class SmokeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def process_modules(pid: int) -> list[str]:
    """Capture loaded module paths from a running Windows process."""
    if os.name != "nt":
        return []
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p),
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                           wintypes.LPWSTR, wintypes.DWORD]
    psapi.GetModuleFileNameExW.restype = wintypes.DWORD
    process = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
    if not process:
        return []
    try:
        modules = (ctypes.c_void_p * 2048)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcessModulesEx(process, modules, ctypes.sizeof(modules),
                                          ctypes.byref(needed), 0x03):  # LIST_MODULES_ALL
            return []
        count = min(needed.value // ctypes.sizeof(ctypes.c_void_p), len(modules))
        paths: list[str] = []
        for module in modules[:count]:
            buffer = ctypes.create_unicode_buffer(32768)
            if psapi.GetModuleFileNameExW(process, module, buffer, len(buffer)):
                paths.append(buffer.value)
        return paths
    finally:
        kernel32.CloseHandle(process)


def run(label: str, command: list[str], *, timeout: int = 600) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=Path(command[0]).resolve().parent,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    modules: dict[str, str] = {}
    deadline = started + timeout
    while process.poll() is None:
        for module_path in process_modules(process.pid):
            modules[Path(module_path).name.lower()] = str(Path(module_path).resolve())
        if time.monotonic() >= deadline:
            process.kill()
            output, _ = process.communicate()
            raise SmokeError(f"{label} timed out after {timeout}s: {output[-3000:]}")
        time.sleep(0.025)
    output, _ = process.communicate()
    record = {"label": label, "command": command, "exitCode": process.returncode,
              "durationSeconds": round(time.monotonic() - started, 3),
              "output": output[-2000:], "loadedModules": modules}
    if process.returncode:
        raise SmokeError(f"{label} failed ({process.returncode}): {output[-3000:]}")
    return record


def validate_ooxml(path: Path, expected_part: str) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise SmokeError(f"X2T did not produce a non-empty file: {path}")
    try:
        with zipfile.ZipFile(path) as package:
            bad = package.testzip()
            if bad:
                raise SmokeError(f"OOXML archive CRC failure in {path.name}: {bad}")
            names = set(package.namelist())
            required = {"[Content_Types].xml", expected_part}
            if not required <= names:
                raise SmokeError(f"OOXML output is missing {sorted(required - names)}: {path}")
            for name in names:
                if name.endswith((".xml", ".rels")):
                    ET.fromstring(package.read(name))
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise SmokeError(f"invalid OOXML output {path}: {exc}") from exc
    return {"path": str(path), "size": path.stat().st_size, "sha256": sha256(path),
            "requiredPart": expected_part, "zipCrc": "passed", "xmlParts": "parsed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x2t", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, default=ROOT / "tests/core-features/fixtures")
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()

    if os.name != "nt":
        raise SmokeError("Windows X2T runtime smoke requires a Windows host")
    x2t = args.x2t.resolve()
    fixture_root = args.fixture_root.resolve()
    work_root = args.work_root.resolve()
    if not x2t.is_file():
        raise SmokeError(f"X2T executable is missing: {x2t}")
    if not fixture_root.is_dir():
        raise SmokeError(f"fixture directory is missing: {fixture_root}")
    if not inside(work_root, WORK_ROOT) or work_root == WORK_ROOT:
        raise SmokeError(f"smoke work root must be a new child of {WORK_ROOT}")
    if work_root.exists():
        raise SmokeError(f"smoke work root already exists; refusing to reuse it: {work_root}")
    work_root.mkdir(parents=True)

    font_root = work_root / "fonts"
    font_root.mkdir()
    font_record = run("generate-font-selection",
                      [str(x2t), "-create-allfonts", str(font_root), str(Path(os.environ["WINDIR"]) / "Fonts")],
                      timeout=900)
    font_selection = font_root / "font_selection.bin"
    if not font_selection.is_file() or font_selection.stat().st_size == 0:
        raise SmokeError(f"X2T did not generate font_selection.bin in {font_root}")

    conversions: list[dict[str, Any]] = [font_record]
    cases = [
        ("docx-bin-roundtrip", "source-blank.docx", "document.bin", "restored.docx", "word/document.xml"),
        ("pptx-bin-roundtrip", "source-blank.pptx", "presentation.bin", "restored.pptx", "ppt/presentation.xml"),
    ]
    outputs: list[dict[str, Any]] = []
    for case, fixture_name, bin_name, restored_name, expected_part in cases:
        case_root = work_root / case
        case_root.mkdir()
        source = fixture_root / fixture_name
        if not source.is_file():
            raise SmokeError(f"smoke fixture is missing: {source}")
        copied_source = case_root / fixture_name
        copied_source.write_bytes(source.read_bytes())
        binary = case_root / bin_name
        restored = case_root / restored_name
        conversions.append(run(f"{case}:ooxml-to-bin", [str(x2t), str(copied_source), str(binary), str(font_selection)]))
        if not conversions[-1]["loadedModules"]:
            raise SmokeError(f"could not capture loaded module paths while running {case}:ooxml-to-bin")
        if not binary.is_file() or binary.stat().st_size == 0:
            raise SmokeError(f"X2T did not produce editor BIN: {binary}")
        conversions.append(run(f"{case}:bin-to-ooxml", [str(x2t), str(binary), str(restored), str(font_selection)]))
        if not conversions[-1]["loadedModules"]:
            raise SmokeError(f"could not capture loaded module paths while running {case}:bin-to-ooxml")
        outputs.extend([
            {"path": str(binary), "size": binary.stat().st_size, "sha256": sha256(binary), "format": "editor-bin"},
            validate_ooxml(restored, expected_part),
        ])

    baseline = json.loads((ROOT / "ci/baseline.json").read_text(encoding="utf-8"))
    checksums = json.loads((ROOT / "vendor/checksums.json").read_text(encoding="utf-8"))
    source_receipt_path = WORK_ROOT / "x2t-core-source-verification.json"
    overlay_receipt_path = WORK_ROOT / "x2t-core-overlay-receipt.json"
    if not source_receipt_path.is_file() or not overlay_receipt_path.is_file():
        raise SmokeError("locked Core source or overlay receipt is missing")
    source_receipt = json.loads(source_receipt_path.read_text(encoding="utf-8"))
    overlay_receipt = json.loads(overlay_receipt_path.read_text(encoding="utf-8"))
    if (source_receipt.get("status") != "verified"
            or source_receipt.get("coreRef") != baseline["coreRef"]
            or source_receipt.get("sourceInventorySha256") != checksums["core-source"]["extractedTreeFingerprint"]
            or source_receipt.get("featurePatches") != []):
        raise SmokeError("X2T build must use the verified pinned Core checkout with no omitted feature patches")
    if (overlay_receipt.get("status") != "applied"
            or [entry.get("path") for entry in overlay_receipt.get("overlays", [])]
            != baseline.get("coreOverlays", [])):
        raise SmokeError("declared Core overlays were not applied to the build checkout")
    runtime_lock = checksums["runtime-windows-amd64"]
    runtime_archive = (ROOT / runtime_lock["file"].replace("\\", "/")).resolve()
    if sha256(runtime_archive) != runtime_lock["sha256"]:
        raise SmokeError("locked candidate Windows runtime archive hash changed")
    icu_lock = checksums["icu"]
    icu_archive = (ROOT / icu_lock["file"].replace("\\", "/")).resolve()
    if sha256(icu_archive) != icu_lock["sha256"]:
        raise SmokeError("locked ICU source archive hash changed")
    icu_build_root = ROOT / "core/Common/3dParty/icu/win_64/build"
    source_built_icu = {
        path.name.lower(): sha256(path) for path in icu_build_root.glob("*.dll") if path.is_file()
    }
    with zipfile.ZipFile(runtime_archive) as package:
        locked_runtime_dlls = {
            Path(name).name.lower(): hashlib.sha256(package.read(name)).hexdigest()
            for name in package.namelist() if name.lower().endswith(".dll")
        }
    dlls = []
    for path in sorted(x2t.parent.glob("*.dll"), key=lambda item: item.name.lower()):
        dlls.append({"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)})
    if not dlls:
        raise SmokeError("X2T runtime directory contains no app-local DLLs")
    dll_hashes = {entry["name"].lower(): entry["sha256"] for entry in dlls}
    loaded_runtime_dlls: dict[str, dict[str, str]] = {}
    for conversion in conversions:
        for name, path in conversion.get("loadedModules", {}).items():
            if name not in dll_hashes:
                continue
            resolved = Path(path).resolve()
            if resolved.parent != x2t.parent:
                raise SmokeError(f"runtime DLL loaded from outside the X2T directory: {path}")
            if name in source_built_icu:
                if source_built_icu[name] != dll_hashes[name]:
                    raise SmokeError(f"loaded ICU DLL differs from the locked-source build output: {name}")
                provenance = {"kind": "source-built-icu", "archive": icu_lock["file"],
                              "archiveSha256": icu_lock["sha256"]}
            else:
                if locked_runtime_dlls.get(name) != dll_hashes[name]:
                    raise SmokeError(f"loaded app-local DLL differs from the locked runtime archive: {name}")
                provenance = {"kind": "locked-runtime-archive", "archive": runtime_lock["file"],
                              "archiveSha256": runtime_lock["sha256"]}
            loaded_runtime_dlls[name] = {"path": str(resolved), "sha256": dll_hashes[name],
                                         "provenance": provenance}
    if not loaded_runtime_dlls:
        raise SmokeError("no app-local runtime DLL load path was observed during conversion")

    receipt = {
        "schemaVersion": 1,
        "status": "passed",
        "coreRef": baseline["coreRef"],
        "coreTreeSha256": checksums["core-source"]["treeSha256"],
        "buildToolsRef": baseline["buildToolsRef"],
        "sourceVerificationReceiptSha256": sha256(source_receipt_path),
        "coreSourceInventorySha256": source_receipt["sourceInventorySha256"],
        "overlayReceiptSha256": sha256(overlay_receipt_path),
        "runtimeArchive": runtime_lock["file"],
        "runtimeArchiveSha256": runtime_lock["sha256"],
        "runtimeSourceLabel": runtime_lock.get("source"),
        "runtimeProvenance": "operator-manual-upgrade; metadata-only-reconciliation",
        "icuSourceArchive": icu_lock["file"],
        "icuSourceArchiveSha256": icu_lock["sha256"],
        "x2t": {"path": str(x2t), "size": x2t.stat().st_size, "sha256": sha256(x2t)},
        "appLocalDlls": dlls,
        "observedLoadedAppLocalDlls": loaded_runtime_dlls,
        "fontSelection": {"size": font_selection.stat().st_size, "sha256": sha256(font_selection)},
        "conversions": conversions,
        "outputs": outputs,
        "acceptance": "DOCX -> editor BIN -> DOCX and PPTX -> editor BIN -> PPTX; output ZIP CRC and XML parsed",
    }
    report = WORK_ROOT / "x2t-baseline-smoke-receipt.json"
    report.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "coreRef": receipt["coreRef"],
                      "x2tSha256": receipt["x2t"]["sha256"], "dllCount": len(dlls),
                      "conversions": len(conversions), "outputs": len(outputs),
                      "receipt": str(report)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, json.JSONDecodeError, SmokeError, subprocess.TimeoutExpired) as exc:
        print(f"X2T runtime smoke error: {exc}", file=sys.stderr)
        raise SystemExit(1)
