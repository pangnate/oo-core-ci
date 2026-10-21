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
