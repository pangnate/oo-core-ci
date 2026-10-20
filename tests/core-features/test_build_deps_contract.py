"""Static dependency inventory checks; verified does not mean build-tested."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "config" / "feature-runtime-deps.lock.json"
SCHEMA = ROOT / "config" / "feature-runtime-deps.schema.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_build_deps_contract(profile: dict[str, Any]) -> int:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schemaVersion"]["const"] == 1
    assert set(schema["$defs"]["items"]["items"]["properties"]["status"]["enum"]) == {
        "verified", "unavailable", "planned"
    }

    baseline = json.loads((ROOT / "ci" / "baseline.json").read_text(encoding="utf-8"))
    vendor = json.loads((ROOT / "vendor" / "checksums.json").read_text(encoding="utf-8"))
    assert lock["core"]["ref"] == baseline["coreRef"]
    assert lock["core"]["treeSha256"] == vendor["core-source"]["treeSha256"]
    assert lock["core"]["buildToolsRef"] == baseline["buildToolsRef"]
    assert lock["core"]["buildToolsTreeSha256"] == vendor["build-tools-source"]["sha256"]
    count = 4

    entries = lock["windowsAmd64"]["toolchain"] + lock["windowsAmd64"]["thirdParty"]
    ids = [item["id"] for item in entries]
    assert len(ids) == len(set(ids))
    for item in entries:
        assert item["status"] in {"verified", "unavailable", "planned"}
        if item["status"] == "verified":
            if "path" in item:
                path = (ROOT / item["path"]).resolve()
                assert path.is_relative_to(ROOT) and path.is_file(), item["id"]
                assert _sha256(path) == item["sha256"], item["id"]
            else:
                assert item.get("sourceRef") and item.get("evidence"), item["id"]
                if item["sourceRef"] == "core-source":
                    assert item["evidence"] and lock["core"]["treeSha256"] == vendor["core-source"]["treeSha256"]
        else:
            assert item.get("reason"), item["id"]
            assert "sha256" not in item, item["id"]
        count += 1

    for anchor in lock["anchors"]:
        source = (ROOT / anchor["path"]).read_text(encoding="utf-8", errors="replace")
        for expected in anchor["contains"]:
            assert expected in source, f"missing source anchor {anchor['path']} :: {expected}"
            count += 1

    third = {item["id"]: item for item in lock["windowsAmd64"]["thirdParty"]}
    detected = json.loads((ROOT / "vendor" / "detected-deps.json").read_text(encoding="utf-8"))
    assert detected["boost"]["version"] == third["boost-archive-1.72"]["version"] == "1.72.0"
    assert third["boost-archive-1.72"]["status"] == "verified"
    assert third["v8-windows-sdk"]["status"] == "verified"
    assert third["v8-windows-sdk"]["sourceRef"].startswith("fixed-release:")
    assert third["v8-windows-sdk"]["evidence"]
    v8_root = ROOT / "core" / "Common" / "3dParty" / "v8_89"
    assert sorted(path.name for path in v8_root.iterdir()) == [".gitignore"]
    assert lock["windowsAmd64"]["blockers"]
    assert profile["level"] == "source"
    return count + 6


class BuildDependencyContractTests(unittest.TestCase):
    def test_verified_inputs_and_explicit_gaps(self) -> None:
        self.assertGreater(verify_build_deps_contract({"level": "source"}), 0)
