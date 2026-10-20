#!/usr/bin/env python3
"""Apply only the declared Core overlays to the checked-out source tree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    baseline = json.loads((ROOT / "ci/baseline.json").read_text(encoding="utf-8"))
    source_root = (ROOT / "overlays/core").resolve()
    core_root = (ROOT / "core").resolve()
    applied = []

    for relative in baseline.get("coreOverlays", []):
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise SystemExit(f"Unsafe Core overlay path: {relative!r}")
        source_candidate = source_root / Path(*rel.parts)
        target_candidate = core_root / Path(*rel.parts)
        if source_candidate.is_symlink():
            raise SystemExit(f"Declared Core overlay is a symlink: {relative}")
        source = source_candidate.resolve()
        target = target_candidate.resolve()
        if not source.is_relative_to(source_root) or not source.is_file():
            raise SystemExit(f"Declared Core overlay is missing or unsafe: {relative}")
        if not target.is_relative_to(core_root):
            raise SystemExit(f"Core overlay target escapes checkout: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        applied.append({"path": relative, "sha256": sha256(source)})

    work = ROOT / "vendor/work"
    work.mkdir(parents=True, exist_ok=True)
    receipt_path = work / "x2t-core-overlay-receipt.json"
    if receipt_path.exists():
        raise SystemExit(f"Refusing to overwrite Core overlay receipt: {receipt_path}")
    receipt = {"schemaVersion": 1, "status": "applied", "overlays": applied}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**receipt, "receipt": str(receipt_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
