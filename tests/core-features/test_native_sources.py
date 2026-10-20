from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import native_sources as native


class NativeSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = self.root / "core"
        lock = json.loads((ROOT / "config/native-sources.lock.json").read_text(encoding="utf-8"))
        fixtures = {
            "gumbo": {"src/tag.c": "isspace(*c)", "src/gumbo.h": "header"},
            "katana": {"src/katana.h": "header", "src/parser.c":
                       'katanaget_text(parser->scanner)\n#define KATANA_PARSER_STRING(literal) (KatanaParserString){',
                       "src/foundation.c": "size_t len = strlen(str);",
                       "src/tokenizer.c": "static inline bool katana_is_html_space(char c);\ninline bool katana_is_html_space(char c) {}"},
            "harfbuzz": {"src/hb-ft.cc": "\noriginal\n", "src/hb.h": "header", "src/graph/graph.hh": "header",
                         "src/test-something.cc": "test", "src/harfbuzz.cc": "amalgamation", "src/main.cc": "main"},
            "hyphen": {"hnjalloc.h": "header", "hnjalloc.c": "source", "hyphen.c": "source", "hyphen.h": "header"},
        }
        for name, item in lock["sources"].items():
            archive = self.root / item["file"]
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive, "w:gz") as package:
                for relative, content in fixtures[name].items():
                    data = content.encode()
                    info = tarfile.TarInfo("source/" + relative)
                    info.size = len(data)
                    package.addfile(info, io.BytesIO(data))
            item["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        config = self.root / "config/native-sources.lock.json"
        config.parent.mkdir()
        config.write_text(json.dumps(lock), encoding="utf-8")
        patch = self.core / "Common/3dParty/harfbuzz/patch/hb-ft.cc.patch"
        patch.parent.mkdir(parents=True)
        patch.write_text("<<<<<<<\noriginal\n=======\npatched\n>>>>>>>\n", encoding="utf-8")

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            native.prepare(self.core, self.root)

    def test_offline_restore_replays_patches_and_is_repeatable(self):
        self.prepare()
        katana = self.core / "Common/3dParty/html/katana-parser/src"
        self.assertIn("static inline bool katana_is_html_space(char c) {}", (katana / "tokenizer.c").read_text())
        self.assertNotIn("static static", (katana / "tokenizer.c").read_text())
        self.assertIn("if (NULL == str)", (katana / "foundation.c").read_text())
        self.assertIn('/*katanaget_text(parser->scanner)*/"error"', (katana / "parser.c").read_text())
        hb = self.core / "Common/3dParty/harfbuzz"
        first = (hb / "harfbuzz/src/hb-ft.cc").read_bytes()
        self.assertIn(b"#if 0", first)
        self.assertIn(b"patched", first)
        self.prepare()
        self.assertEqual(first, (hb / "harfbuzz/src/hb-ft.cc").read_bytes())
        pri = (hb / "harfbuzz.pri").read_text()
        self.assertIn("hb-ft.cc", pri)
        self.assertNotIn("test-something.cc", pri)
        self.assertNotIn("harfbuzz.cc", pri)
        self.assertNotIn("main.cc", pri)

    def test_missing_or_corrupt_archive_is_rejected(self):
        item = native.load_lock(self.root)["sources"]["katana"]
        archive = self.root / item["file"]
        archive.write_bytes(b"version https://git-lfs.github.com/spec/v1")
        with self.assertRaisesRegex(ValueError, "Missing or corrupt locked katana"):
            native.verify_archives(self.root)
        archive.unlink()
        with self.assertRaisesRegex(ValueError, "Missing or corrupt locked katana"):
            native.verify_archives(self.root)

    def test_missing_required_header_fails_before_build(self):
        self.prepare()
        (self.core / "Common/3dParty/html/katana-parser/src/katana.h").unlink()
        with self.assertRaisesRegex(ValueError, "katana.h"):
            native.verify(self.core, self.root)

    def test_missing_or_stale_harfbuzz_project_is_rejected(self):
        self.prepare()
        pri = self.core / "Common/3dParty/harfbuzz/harfbuzz.pri"
        pri.write_text("SOURCES =\n")
        with self.assertRaisesRegex(ValueError, "stale generated HarfBuzz"):
            native.verify(self.core, self.root)
        pri.unlink()
        with self.assertRaisesRegex(ValueError, "stale generated HarfBuzz"):
            native.verify(self.core, self.root)

    def test_incomplete_lock_is_rejected(self):
        config = self.root / "config/native-sources.lock.json"
        lock = json.loads(config.read_text())
        del lock["sources"]["hyphen"]
        config.write_text(json.dumps(lock))
        with self.assertRaisesRegex(ValueError, "all four"):
            native.load_lock(self.root)

    def test_dependency_output_preflight_for_three_targets(self):
        self.prepare()
        detected = self.root / "vendor/detected-deps.json"
        detected.parent.mkdir(exist_ok=True)
        detected.write_text('{"icu":{"version":"74.2"}}')
        third = self.core / "Common/3dParty"

        def seed(relative):
            path = third / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")

        for name in ("c/include/brotli/decode.h", "c/dec/decode.c", "c/common/constants.c"):
            seed("brotli/brotli/" + name)
        seed("heif/libheif/libheif/api/libheif/heif.h")
        for target in ("win_64", "linux_64", "linux_arm64"):
            seed(f"boost/build/{target}/include/boost/version.hpp")
            for name in ("filesystem", "system", "regex", "date_time"):
                filename = f"libboost_{name}-vc142-mt-x64-1_72.lib" if target == "win_64" else f"libboost_{name}.a"
                seed(f"boost/build/{target}/lib/{filename}")
            icu = ("icuuc.lib", "icudt.lib", "icuuc74.dll", "icudt74.dll") if target == "win_64" else (
                "libicuuc.so.74", "libicudata.so.74", "include/unicode/ucnv.h")
            for name in icu:
                seed(f"icu/{target}/build/{name}")
            if target == "win_64":
                libs = ("libheif/build/win_64/release/libheif/Release/heif.lib",
                        "x265_git/build/win_64/release/Release/x265-static.lib",
                        "libde265/build/win_64/release/libde265/Release/libde265.lib")
            else:
                libs = (f"libheif/build/{target}/release/libheif/libheif.a",
                        f"x265_git/build/{target}/release/libx265.a",
                        f"libde265/build/{target}/release/libde265/libde265.a")
            for name in libs:
                seed("heif/" + name)
            with contextlib.redirect_stdout(io.StringIO()):
                native.verify_for_build(self.core, target, self.root)
            broken = third / "heif" / libs[0]
            broken.unlink()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "Incomplete prepared"):
                native.verify_for_build(self.core, target, self.root)

    def test_parallel_graph_declares_pdf_crypto_dependency_and_is_idempotent(self):
        for relative in ("X2tConverter/build/Qt/X2tSLN.pri", "X2tConverter/build/Qt/X2tConverter.pro",
                         "Common/3dParty/heif/heif.pri"):
            target = self.core / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / "core" / relative).read_bytes())
        command = [sys.executable, str(ROOT / "scripts/patch_x2t_sln.py"), "--core-root", str(self.core)]
        subprocess.run(command, check=True, capture_output=True)
        pri = self.core / "X2tConverter/build/Qt/X2tSLN.pri"
        before = pri.read_bytes()
        subprocess.run(command, check=True, capture_output=True)
        self.assertEqual(pri.read_bytes(), before)
        self.assertIn(b"PdfFile.depends = graphics CryptoPPLib", before)
        self.assertIn(b"CONFIG -= ordered", before)
        self.assertNotIn(b"CONFIG += ordered", before)


if __name__ == "__main__":
    unittest.main()
