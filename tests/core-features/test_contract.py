"""Static checks for the frozen file/runtime contract (not feature acceptance)."""
from __future__ import annotations

import itertools
import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "协议" / "core-feature-contract.json"
SCHEMA = ROOT / "docs" / "协议" / "feature-profile.schema.json"


def verify_contract(profile: dict[str, Any]) -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["schemaVersion"]["const"] == 1

    rows = contract["compatibilityMatrix"]
    expected = set(itertools.product(("old", "new"), repeat=3))
    actual = {(row["core"], row["browserJS"], row["nativeJS"]) for row in rows}
    assert len(rows) == 8 and actual == expected
    for row in rows:
        all_new = row["core"] == row["browserJS"] == row["nativeJS"] == "new"
        assert row["allowNewFeatureWrite"] is all_new
        assert row["allowFeaturePdfPrint"] is all_new

    word = contract["word"]
    tags = [item["binaryTag"] for item in word["paragraphBooleans"] + word["characterIndents"]]
    assert tags == list(range(200, 210))
    permission = word["permission"]
    assert permission["fields"] == {
        "id": 0, "displacedByCustomXml": 1, "colFirst": 2,
        "colLast": 3, "ed": 4, "edGrp": 5,
    }
    assert permission["markers"] == {"permStart": 28, "permEnd": 29, "scope": "paragraph content stream"}

    checked = 0
    for anchor in contract["sourceAnchors"]:
        source = (ROOT / anchor["path"]).read_text(encoding="utf-8", errors="replace")
        for symbol in anchor["symbols"]:
            assert symbol in source, f"source anchor missing: {anchor['path']} :: {symbol}"
            checked += 1

    assert contract["imageFailure"]["abi"]["additive"].startswith("fixed-width POD")
    assert contract["imageFailure"]["legacyDefault"].startswith("tolerant")
    assert "WASM is owned" in contract["runtimeInputs"]["consumer"]
    assert profile["level"] == "source"
    return checked + len(rows) + len(tags) + 8


class ContractTests(unittest.TestCase):
    def test_source_contract_and_anchors(self) -> None:
        self.assertGreater(verify_contract({"level": "source"}), 0)
