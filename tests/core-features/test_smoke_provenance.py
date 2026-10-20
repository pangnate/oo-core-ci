"""The active patched build must be accepted without trusting arbitrary DLLs."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from smoke_x2t_runtime import SmokeError, validate_compiled_modules, validate_patch_receipts


class SmokeProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.expected = [{"path": "patches/core/feature.patch", "sha256": "patch-hash"}]
        self.source = {"status": "verified", "coreRef": "ref", "sourceInventorySha256": "tree",
                       "featurePatches": self.expected}
        self.applied = {"coreRef": "ref", "patches": self.expected}
        self.baseline = {"coreRef": "ref", "corePatches": [self.expected[0]["path"]]}
        self.lock = {"extractedTreeFingerprint": "tree"}

    def test_complete_active_feature_series_is_accepted(self):
        validate_patch_receipts(self.source, self.applied, self.baseline, self.lock, self.expected)

    def test_an_omitted_feature_patch_is_rejected(self):
        incomplete = copy.deepcopy(self.applied)
        incomplete["patches"] = []
        with self.assertRaises(SmokeError):
            validate_patch_receipts(self.source, incomplete, self.baseline, self.lock, self.expected)

    def test_rebuilt_modules_are_accepted_only_at_the_recorded_hashes(self):
        modules = {"x2t.exe": "exe", "graphics.dll": "graphics", "pdffile.dll": "pdf"}
        producer = {"compiledModules": modules}
        dlls = {"graphics.dll": "graphics", "pdffile.dll": "pdf", "kernel.dll": "locked"}
        self.assertEqual(validate_compiled_modules(producer, "exe", dlls), modules)
        with self.assertRaises(SmokeError):
            validate_compiled_modules(producer, "exe", {**dlls, "graphics.dll": "changed"})
        with self.assertRaises(SmokeError):
            validate_compiled_modules({"compiledModules": {**modules, "kernel.dll": "unchecked"}}, "exe", dlls)


if __name__ == "__main__":
    unittest.main()
