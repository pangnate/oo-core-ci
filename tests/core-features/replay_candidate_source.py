"""Explicit candidate source replay only; does not compile or run Core."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from stage_core_source import stage_core_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=Path, required=True, help="explicit opt-in candidate manifest")
    parser.add_argument("--source", type=Path, required=True, help="pristine locked official Core directory")
    parser.add_argument("--destination", type=Path, required=True, help="new owned directory under vendor/work")
    args = parser.parse_args()
    series = json.loads(args.series.read_text(encoding="utf-8"))
    receipt = stage_core_source(source_root=args.source, destination=args.destination, patch_series=series)
    receipt["validationLevel"] = "SOURCE-REPLAY ONLY; C++/CODEC/Native NOT-RUN"
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
