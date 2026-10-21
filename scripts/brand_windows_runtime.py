#!/usr/bin/env python3
"""Set PE version resources on copied ONLYOFFICE Core DLLs in a Windows package.

This changes the package copies, not the locked vendor archives or Core sources.
ICU DLLs are third-party and remain untouched. Every other packaged PE must
carry the configured company, copyright holder and version after this step.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import struct
import sys
from ctypes import wintypes
from pathlib import Path
from branding import load_branding

UPSTREAM_COMPANY = "Ascensio System SIA"
RT_VERSION = 16
VS_VERSION_INFO = 1
LOAD_LIBRARY_AS_DATAFILE = 0x00000002


def align4(value: int) -> int:
    return (value + 3) & ~3


class VersionNode:
    def __init__(self, key: str, kind: int, value: bytes, children: list["VersionNode"]):
        self.key = key
        self.kind = kind
        self.value = value
        self.children = children


def parse_node(data: bytes, start: int, bound: int) -> VersionNode:
    if start + 6 > bound:
        raise ValueError("truncated VERSIONINFO node")
    size, value_length, kind = struct.unpack_from("<HHH", data, start)
    end = start + size
    if size < 6 or end > bound:
        raise ValueError("invalid VERSIONINFO node length")
    key_end = start + 6
    while key_end + 2 <= end and data[key_end:key_end + 2] != b"\0\0":
        key_end += 2
    if key_end + 2 > end:
        raise ValueError("unterminated VERSIONINFO key")
    key = data[start + 6:key_end].decode("utf-16le")
    value_start = align4(key_end + 2)
    value_size = value_length * (2 if kind == 1 else 1)
    value_end = value_start + value_size
    if value_end > end:
        raise ValueError(f"invalid VERSIONINFO value: {key}")
    children: list[VersionNode] = []
    cursor = align4(value_end)
    while cursor + 6 <= end:
        child_size = struct.unpack_from("<H", data, cursor)[0]
        if child_size == 0:
            break
        children.append(parse_node(data, cursor, end))
        cursor = align4(cursor + child_size)
    return VersionNode(key, kind, data[value_start:value_end], children)


def encode_node(node: VersionNode) -> bytes:
    out = bytearray(b"\0" * 6)
    out.extend((node.key + "\0").encode("utf-16le"))
    out.extend(b"\0" * (align4(len(out)) - len(out)))
    out.extend(node.value)
    if node.children:
        out.extend(b"\0" * (align4(len(out)) - len(out)))
        for child in node.children:
            out.extend(encode_node(child))
            out.extend(b"\0" * (align4(len(out)) - len(out)))
    value_length = len(node.value) // 2 if node.kind == 1 else len(node.value)
    if len(out) > 0xFFFF or value_length > 0xFFFF:
        raise ValueError("VERSIONINFO resource exceeds WORD length")
    struct.pack_into("<HHH", out, 0, len(out), value_length, node.kind)
    return bytes(out)


def string_value(node: VersionNode) -> str:
    return node.value.decode("utf-16le").rstrip("\0")


def update_version(data: bytes, company: str, version: str,
                   parts: tuple[int, int, int, int]) -> tuple[bytes, bool]:
    root = parse_node(data, 0, len(data))
    if root.key != "VS_VERSION_INFO" or len(root.value) < 52:
        raise ValueError("missing VS_VERSION_INFO fixed file info")
    fixed = list(struct.unpack_from("<13I", root.value))
    if fixed[0] != 0xFEEF04BD:
        raise ValueError("invalid VS_FIXEDFILEINFO signature")
    tables = [table for group in root.children if group.key == "StringFileInfo"
              for table in group.children]
    company_fields = [item for table in tables for item in table.children
                      if item.key == "CompanyName"]
    if not company_fields:
        raise ValueError("missing CompanyName in VERSIONINFO")
    previous_companies = {string_value(item) for item in company_fields}
    if not previous_companies.issubset({UPSTREAM_COMPANY, company}):
        raise ValueError(f"unexpected publisher in Core PE: {previous_companies}")
    replacements = {
        "CompanyName": company,
        "FileVersion": version,
        "ProductVersion": version,
    }
    for table in tables:
        copyrights = [item for item in table.children if item.key == "LegalCopyright"]
        if not copyrights:
            raise ValueError("missing LegalCopyright in VERSIONINFO")
        for item in copyrights:
            copyright_text = string_value(item)
            if UPSTREAM_COMPANY not in copyright_text and company not in copyright_text:
                raise ValueError(f"unexpected copyright holder in Core PE: {copyright_text}")
            item.value = (copyright_text.replace(UPSTREAM_COMPANY, company) + "\0").encode("utf-16le")
        for item in table.children:
            if item.key in replacements:
                item.value = (replacements[item.key] + "\0").encode("utf-16le")
    fixed_version = [(parts[0] << 16) | parts[1], (parts[2] << 16) | parts[3]]
    fixed[2:6] = fixed_version * 2
    root.value = struct.pack("<13I", *fixed) + root.value[52:]
    return encode_node(root), True


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None


def resource_languages(module: int) -> list[int]:
    assert kernel32 is not None
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p,
                                       ctypes.c_void_p, wintypes.WORD, ctypes.c_ssize_t)
    languages: list[int] = []

    @callback_type
    def collect(_module: int, _type: int, _name: int, language: int, _param: int) -> bool:
        languages.append(language)
        return True

    kernel32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                                 ctypes.c_void_p, callback_type, ctypes.c_ssize_t]
    kernel32.EnumResourceLanguagesW.restype = wintypes.BOOL
    if not kernel32.EnumResourceLanguagesW(module, RT_VERSION, VS_VERSION_INFO, collect, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return languages


def read_resources(path: Path) -> dict[int, bytes]:
    assert kernel32 is not None
    kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.FindResourceExW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                         ctypes.c_void_p, wintypes.WORD]
    kernel32.FindResourceExW.restype = wintypes.HRSRC
    kernel32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    kernel32.SizeofResource.restype = wintypes.DWORD
    kernel32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    kernel32.LoadResource.restype = wintypes.HGLOBAL
    kernel32.LockResource.argtypes = [wintypes.HGLOBAL]
    kernel32.LockResource.restype = ctypes.c_void_p
    kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel32.FreeLibrary.restype = wintypes.BOOL
    module = kernel32.LoadLibraryExW(str(path), None, LOAD_LIBRARY_AS_DATAFILE)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        resources = {}
        for language in resource_languages(module):
            resource = kernel32.FindResourceExW(module, RT_VERSION, VS_VERSION_INFO, language)
            if not resource:
                raise ctypes.WinError(ctypes.get_last_error())
            loaded = kernel32.LoadResource(module, resource)
            pointer = kernel32.LockResource(loaded) if loaded else None
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            resources[language] = ctypes.string_at(pointer, kernel32.SizeofResource(module, resource))
        return resources
    finally:
        kernel32.FreeLibrary(module)


def write_resources(path: Path, resources: dict[int, bytes]) -> None:
    assert kernel32 is not None
    kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                         ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p,
                                         wintypes.DWORD]
    kernel32.UpdateResourceW.restype = wintypes.BOOL
    kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    kernel32.EndUpdateResourceW.restype = wintypes.BOOL
    handle = kernel32.BeginUpdateResourceW(str(path), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for language, data in resources.items():
            buffer = ctypes.create_string_buffer(data)
            if not kernel32.UpdateResourceW(handle, RT_VERSION, VS_VERSION_INFO,
                                            language, buffer, len(data)):
                raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        kernel32.EndUpdateResourceW(handle, True)
        raise
    if not kernel32.EndUpdateResourceW(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-bin", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("PE resource updates require Windows")
    company, version, parts = load_branding()
    runtime_bin = args.runtime_bin.resolve(strict=True)
    records = []
    third_party = {"icudt74.dll", "icuuc74.dll", "icuin74.dll"}
    for dll in sorted([*runtime_bin.glob("*.dll"), *runtime_bin.glob("*.exe")]):
        if dll.name.lower() in third_party:
            continue
        resources = read_resources(dll)
        updates = {}
        for language, data in resources.items():
            changed_data, changed = update_version(data, company, version, parts)
            if changed:
                updates[language] = changed_data
        if not updates:
            raise RuntimeError(f"Core PE has no editable VERSIONINFO resource: {dll}")
        before = sha256(dll)
        write_resources(dll, updates)
        for data in read_resources(dll).values():
            parsed = parse_node(data, 0, len(data))
            fields = {item.key: string_value(item)
                      for group in parsed.children if group.key == "StringFileInfo"
                      for table in group.children for item in table.children}
            if any(fields.get(key) != value for key, value in
                   {"CompanyName": company, "FileVersion": version,
                    "ProductVersion": version}.items()):
                raise RuntimeError(f"VERSIONINFO verification failed: {dll}")
            copyright_text = fields.get("LegalCopyright", "")
            if company not in copyright_text or (UPSTREAM_COMPANY != company and
                                                 UPSTREAM_COMPANY in copyright_text):
                raise RuntimeError(f"copyright verification failed: {dll}")
        records.append({"file": dll.name, "beforeSha256": before, "afterSha256": sha256(dll)})
    if not records:
        raise RuntimeError(f"no Core PE files found in {runtime_bin}")
    receipt = {"company": company, "version": version,
               "coreFileCount": len(records), "thirdPartyDlls": sorted(third_party),
               "files": records}
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Branded and verified {len(records)} Core PE files in {runtime_bin}")


if __name__ == "__main__":
    main()
