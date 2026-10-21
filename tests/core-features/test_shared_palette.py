"""Guard the palette storage fix against altered XLS color values."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = Path("core/MsBinaryFile/XlsFile/Format/Logic")
PATCH = ROOT / "patches/core/019-xls-share-default-palette.patch"

class SharedPaletteTests(unittest.TestCase):
    def test_symbol_gap_estimates_do_not_multiply_aliases(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from report_windows_size import header_static_symbol_gaps
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "aliases.map"
            path.write_text(" 0001:00000010 ??__EmapEncodingsICU@NSUnicodeConverter@@YAXXZ 0000000140001010 f a.obj\n"
                            " 0001:00000010 ??__EmapEncodingsICU@NSUnicodeConverter@@YAXXZ 0000000140001010 f b.obj\n"
                            " 0001:00000010 ?otherAlias@@YAXXZ 0000000140001010 f c.obj\n"
                            " 0001:00000030 ?next@@YAXXZ 0000000140001030 f c.obj\n")
            self.assertEqual(header_static_symbol_gaps(path), [{"family": "mapEncodingsICU",
                             "estimatedSymbolGapBytesBySegment": {"0001": 32},
                             "estimatedZeroFillBytes": 0}])

    def test_header_static_limits_cover_removed_and_shared_initializers(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from report_windows_size import header_static_initializers
        actual = header_static_initializers([
            {"symbol": "??__EmapEncodingsICU@NSUnicodeConverter@@YAXXZ", "instances": 2153},
            {"symbol": "??__Eg_bstr_nodeclose@PPT@@YAXXZ", "instances": 477},
        ])
        failed = [entry for entry in actual if entry["instances"] > entry["maximum"]]
        self.assertEqual(len(failed), 2)
        self.assertTrue(all(entry["maximum"] == 0 for entry in failed))
        self.assertTrue(all(entry["instances"] <= entry["maximum"]
                            for entry in header_static_initializers([])))

    def test_map_initializer_count_uses_distinct_addresses(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from report_windows_size import repeated_initializers
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.map"
            path.write_text(" 0001:00000000 ??__EDefaultPalette@XLS@@YAXXZ 0000000140001000 f a.obj\n"
                            " 0001:00000000 ??__EDefaultPalette@XLS@@YAXXZ 0000000140001000 f a.obj\n"
                            " 0001:00001000 ??__EDefaultPalette@XLS@@YAXXZ 0000000140002000 f b.obj\n"
                            " 0002:00000000 ??__EDefaultPalette@XLS@@YAXXZ 0000000140003000 f c.obj\n")
            self.assertEqual(repeated_initializers(path), [{"symbol": "??__EDefaultPalette@XLS@@YAXXZ", "instances": 2}])

    def test_real_sources_apply_and_preserve_array_type_and_all_colors(self):
        original = (ROOT / RELATIVE / "GlobalWorkbookInfo.h").read_text(encoding="utf-8")
        palette = re.search(r"static const std::wstring DefaultPalette\[\] = \{.*?\n\};", original, re.S).group()
        colors = re.findall(r'L"[0-9A-F]{8}"', palette)
        self.assertEqual(len(colors), 64)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / RELATIVE
            target.mkdir(parents=True)
            for name in ("GlobalWorkbookInfo.h", "GlobalWorkbookInfo.cpp"):
                (target / name).write_bytes((ROOT / RELATIVE / name).read_bytes())
            subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--ignore-space-change", str(PATCH)], cwd=root, check=True, capture_output=True)
            header = (target / "GlobalWorkbookInfo.h").read_text(encoding="utf-8")
            source = (target / "GlobalWorkbookInfo.cpp").read_text(encoding="utf-8")
            self.assertIn("extern const std::wstring DefaultPalette[64];", header)
            self.assertNotIn("static const std::wstring DefaultPalette", header)
            self.assertNotIn(colors[0], header)
            definition = re.search(r"const std::wstring DefaultPalette\[64\] = \{.*?\n\};", source, re.S).group()
            self.assertEqual(re.findall(r'L"[0-9A-F]{8}"', definition), colors)
            self.assertEqual(source.count("const std::wstring DefaultPalette[64] ="), 1)

if __name__ == "__main__":
    unittest.main()
