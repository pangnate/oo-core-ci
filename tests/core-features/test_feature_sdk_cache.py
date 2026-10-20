from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("feature_sdk_cache", ROOT / "scripts/ci_feature_sdk_cache.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)

class FeatureSdkCacheTests(unittest.TestCase):
    def test_only_dependency_patch_changes_key_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "patches/core"
            folder.mkdir(parents=True)
            (folder / "series.json").write_text(json.dumps({"patches": [{"path": "patches/core/a.patch"}, {"path": "patches/core/b.patch"}]}))
            (folder / "a.patch").write_text("+++ b/OOXML/DocxFormat/A.cpp\n")
            (folder / "b.patch").write_text("+++ b/Common/3dParty/harfbuzz/make.py\n")
            first = cache.patch_inputs(root)
            self.assertEqual(list(first), ["patches/core/b.patch"])
            (folder / "a.patch").write_text("+++ b/OOXML/DocxFormat/B.cpp\n")
            self.assertEqual(first, cache.patch_inputs(root))
            (folder / "b.patch").write_text("+++ b/Common/3dParty/harfbuzz/make.py\n+change\n")
            self.assertNotEqual(first, cache.patch_inputs(root))

    def test_cache_requires_compiler_identity(self):
        with patch.dict(cache.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "MSVC"):
                cache.identity()

    def test_receipt_rejects_input_and_file_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp)
            sdk = dist / "windows-feature-sdk"
            sdk.mkdir()
            for name in ("manifest.json", "provenance.json", "build-receipt.json", "staging-receipt.json", "core-feature-sources.zip"):
                (sdk / name).write_text("test")
            (sdk / "probe-receipt.json").write_text(json.dumps({"status": "passed"}))
            archive = dist / "windows-feature-sdk.zip"
            archive.write_bytes(b"archive")
            (dist / "windows-feature-sdk.zip.sha256").write_text(cache.sha(archive) + "  windows-feature-sdk.zip\n")
            cache.receipt(dist, "first", True)
            cache.receipt(dist, "first", False)
            # Current Core dev verification is separate from the cached SDK producer.
            (sdk / "dev-build-receipt.json").write_text("new consumer")
            cache.receipt(dist, "first", False)
            with self.assertRaisesRegex(ValueError, "mismatch"):
                cache.receipt(dist, "second", False)
            (sdk / "core-feature-sources.zip").write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                cache.receipt(dist, "first", False)

    def test_incomplete_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "incomplete"):
                cache.inventory(Path(temp))

if __name__ == "__main__":
    unittest.main()
