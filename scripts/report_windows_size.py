#!/usr/bin/env python3
"""Record X2T PE sections and approximate linker-map object contributions."""
from __future__ import annotations

import argparse
import json
import re
import struct
from collections import defaultdict
from pathlib import Path

PREVIOUS_RUNTIME_EXE_BYTES = 39_928_816
PREVIOUS_CI_EXE_BYTES = 57_206_272
SYMBOL = re.compile(r"^\s*([0-9A-Fa-f]{4}):([0-9A-Fa-f]{8})\s+\S+\s+[0-9A-Fa-f]{8,16}\s+(?:f|i)\s+(.+?)\s*$")


def pe_sections(path: Path) -> list[dict[str, int | str]]:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"not a PE executable: {path}")
        stream.seek(0x3c)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError(f"invalid PE signature: {path}")
        coff = stream.read(20)
        count = struct.unpack_from("<H", coff, 2)[0]
        optional_size = struct.unpack_from("<H", coff, 16)[0]
        stream.seek(optional_size, 1)
        sections = []
        for _ in range(count):
            header = stream.read(40)
            name = header[:8].rstrip(b"\0").decode("ascii", errors="replace")
            virtual, rva, raw_size = struct.unpack_from("<III", header, 8)
            sections.append({"name": name, "rva": rva,
                             "virtualBytes": virtual, "rawBytes": raw_size})
        return sections


def map_contributors(path: Path) -> list[dict[str, int | str]]:
    # Public-symbol gaps are diagnostic estimates, not exact COMDAT ownership.
    by_section: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = SYMBOL.match(line)
        if match:
            by_section[match.group(1)].append((int(match.group(2), 16), match.group(3)))
    totals: dict[str, int] = defaultdict(int)
    for symbols in by_section.values():
        symbols.sort(key=lambda item: item[0])
        for current, following in zip(symbols, symbols[1:]):
            gap = following[0] - current[0]
            if 0 < gap < 1_000_000:
                totals[current[1]] += gap
    return [{"object": name, "estimatedSymbolGapBytes": size}
            for name, size in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:40]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if not args.map.is_file():
        raise SystemExit(f"linker map is missing: {args.map}")
    size = args.exe.stat().st_size
    report = {
        "exe": str(args.exe), "exeBytes": size,
        "previousRuntimeExeBytes": PREVIOUS_RUNTIME_EXE_BYTES,
        "previousCiExeBytes": PREVIOUS_CI_EXE_BYTES,
        "deltaFromPreviousRuntimeBytes": size - PREVIOUS_RUNTIME_EXE_BYTES,
        "deltaFromPreviousCiBytes": size - PREVIOUS_CI_EXE_BYTES,
        "sections": pe_sections(args.exe),
        "largestMapSymbolGapContributors": map_contributors(args.map),
        "mapBytes": args.map.stat().st_size,
        "mapEstimateNote": "Public symbol gaps approximate object contribution; use the uploaded map for exact investigation.",
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
