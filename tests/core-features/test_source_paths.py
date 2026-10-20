from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_source_paths import audit


class SourcePathTests(unittest.TestCase):
    def test_wrong_letter_case_is_rejected_on_any_filesystem(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "Source"
            folder.mkdir()
            (folder / "Module.cpp").write_text("int value;")
            manifest = root / ".x2t-input-paths.txt"
            manifest.write_text("SOURCE|" + str(root / "source/module.cpp") + "\n")
            report = root / "report.json"
            with self.assertRaisesRegex(ValueError, "case mismatch"):
                audit(root, report)
            result = json.loads(report.read_text())
            self.assertEqual(result["errors"][0]["actual"], str(folder / "Module.cpp"))
            manifest.write_text("SOURCE|" + str(folder / "Module.cpp") + "\n")
            self.assertEqual(audit(root, report)["status"], "passed")

    def test_missing_source_fails_but_obsolete_ide_header_is_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / ".x2t-input-paths.txt"
            manifest.write_text("HEADER|" + str(root / "obsolete.h") + "\n")
            result = audit(root, root / "report.json")
            self.assertEqual(len(result["staleHeaders"]), 1)
            manifest.write_text("SOURCE|" + str(root / "missing.cpp") + "\n")
            with self.assertRaisesRegex(ValueError, "missing source"):
                audit(root, root / "report.json")

    def test_existing_header_wrong_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Exact.h").write_text("header")
            (root / ".x2t-input-paths.txt").write_text("HEADER|" + str(root / "exact.h") + "\n")
            with self.assertRaisesRegex(ValueError, "case mismatch"):
                audit(root, root / "report.json")

    def test_absent_manifests_are_not_a_passing_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "No qmake source manifests"):
                audit(root, root / "report.json")
