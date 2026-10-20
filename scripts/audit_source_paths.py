#!/usr/bin/env python3
"""Check qmake input spelling even on a case-insensitive Windows filesystem."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


class CasePaths:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directories: dict[Path, dict[str, Path]] = {}

    def inspect(self, path: Path) -> tuple[Path | None, bool]:
        # abspath removes '..' without resolving the requested letter case.
        requested = Path(os.path.abspath(path))
        relative = requested.relative_to(self.root)
        current = self.root
        mismatch = False
        for part in relative.parts:
            if current not in self.directories:
                try:
                    self.directories[current] = {entry.name: entry for entry in current.iterdir()}
                except OSError:
                    return None, False
            entries = self.directories[current]
            if part in entries:
                current = entries[part]
                continue
            alternatives = [entry for name, entry in entries.items() if name.casefold() == part.casefold()]
            if len(alternatives) != 1:
                return None, False
            current = alternatives[0]
            mismatch = True
        return current, mismatch


def audit(core: Path, report: Path) -> dict:
    core = core.resolve()
    paths = CasePaths(core)
    manifests = sorted(core.rglob(".x2t-input-paths.txt"))
    if not manifests:
        raise ValueError("No qmake source manifests; generate the complete project with x2t_inputs first")
    errors = []
    stale_headers = []
    checked = set()
    for manifest in manifests:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            kind, value = line.split("|", 1)
            if kind not in ("SOURCE", "HEADER"):
                raise ValueError(f"Unknown qmake manifest record: {line}")
            entry = kind, value
            if entry in checked:
                continue
            checked.add(entry)
            actual, mismatch = paths.inspect(Path(value))
            item = {"kind": kind, "path": value, "manifest": str(manifest)}
            if actual is None or not actual.is_file():
                if kind == "HEADER":
                    stale_headers.append(item)
                else:
                    errors.append({**item, "reason": "missing source"})
            elif mismatch:
                errors.append({**item, "reason": "case mismatch", "actual": str(actual)})
    result = {"schemaVersion": 1, "projects": len(manifests), "checkedInputs": len(checked),
              "status": "failed" if errors else "passed", "errors": errors, "staleHeaders": stale_headers}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise ValueError("Invalid qmake input paths:\n" + "\n".join(
            f"{item['reason']}: {item['path']} -> {item.get('actual', '(missing)')}" for item in errors))
    print(f"Exact input path check OK: {len(manifests)} projects, {len(checked)} inputs; "
          f"{len(stale_headers)} obsolete header entries recorded")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    audit(args.core_root, args.report)
