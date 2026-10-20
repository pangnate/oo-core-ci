"""Extract hash-bound source evidence; never compiles or executes Core."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def collect(staging: Path, plan: dict) -> dict:
    root = staging.resolve()
    entries = []
    for item in plan["entries"]:
        rel = PurePosixPath(item["path"])
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] != "core":
            raise ValueError("source evidence path must stay beneath staging/core")
        path = (root / Path(*rel.parts)).resolve()
        if not path.is_relative_to(root) or path.is_symlink():
            raise ValueError("source evidence path escapes staging")
        data = path.read_bytes()
        lines = data.decode("utf-8-sig").splitlines()
        matches = []
        for anchor in item["anchors"]:
            if not anchor:
                raise ValueError("empty source anchor")
            indexes = [index for index, line in enumerate(lines) if anchor in line]
            if not indexes:
                raise ValueError(f"source anchor missing: {item['path']}: {anchor}")
            matches.append({"anchor": anchor, "lines": [index + 1 for index in indexes],
                            "excerpts": [{"line": index + 1, "text": lines[index]} for index in indexes]})
        entries.append({"path": item["path"], "sha256": hashlib.sha256(data).hexdigest(), "anchors": matches})
    if not entries or not any(entry["anchors"] for entry in entries):
        raise ValueError("source audit cannot be empty")
    return {"taskId": plan["taskId"], "level": "SOURCE ANCHORS ONLY; semantics require manual review",
            "cppAssertionsExecuted": 0, "buildAcceptance": "NOT-RUN", "runtimeAcceptance": "NOT-RUN",
            "staging": str(root), "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.staging, json.loads(args.plan.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"source evidence extracted: {len(report['entries'])} files; C++ NOT-RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
