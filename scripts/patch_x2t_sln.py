#!/usr/bin/env python3
"""Adapt the pinned Core qmake graph for CI."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--core-root", type=Path, default=ROOT / "core")
args = parser.parse_args()
core = args.core_root.resolve()
pri = core / "X2tConverter/build/Qt/X2tSLN.pri"
pro = core / "X2tConverter/build/Qt/X2tConverter.pro"
if not pri.exists() or not pro.exists():
    raise SystemExit("Missing X2T qmake project in Core source")

text = pri.read_text(encoding="utf-8")
# The static archives are independent; the executable and PdfFile declare
# their prerequisites below. Let make schedule within the CPU-count budget.
text = text.replace("CONFIG += ordered", "CONFIG -= ordered")
if "CryptoPPLib.file" not in text:
    text = text.replace("SUBDIRS = \\\n", "SUBDIRS = \\\n    CryptoPPLib \\\n", 1)
    marker = "XlsbFormatLib.file ="
    if marker not in text:
        raise SystemExit("Unexpected X2tSLN.pri: XlsbFormatLib.file missing")
    text = text.replace(marker,
                        "CryptoPPLib.file = ../../../Common/3dParty/cryptopp/project/cryptopp.pro\n" + marker,
                        1)
if "X2tConverter.depends = \\\n    CryptoPPLib \\\n" not in text:
    text = text.replace("X2tConverter.depends = \\\n",
                        "X2tConverter.depends = \\\n    CryptoPPLib \\\n", 1)
if "PdfFile.file" not in text:
    text += ("\n# Build patched Core libraries before linking X2T.\n"
             "graphics.file = ../../../DesktopEditor/graphics/pro/graphics.pro\n"
             "PdfFile.file = ../../../PdfFile/PdfFile.pro\n"
             "PdfFile.depends = graphics CryptoPPLib\n"
             "SUBDIRS -= X2tConverter\n"
             "SUBDIRS += graphics PdfFile X2tConverter\n"
             "X2tConverter.depends += PdfFile\n")
text = text.replace("PdfFile.depends = graphics\n", "PdfFile.depends = graphics CryptoPPLib\n")
pri.write_text(text, encoding="utf-8", newline="\n")

ptext = pro.read_text(encoding="utf-8")
block = ("\n# BASEMETAS_X2T_CI_BEGIN\n"
         "core_linux {\n"
         "    QMAKE_LFLAGS += -Wl,-rpath-link,$$CORE_BUILDS_LIBRARIES_PATH\n"
         "    QMAKE_LFLAGS += -Wl,-rpath-link,$$CORE_BUILDS_LIBRARIES_PATH/system\n"
         "}\n"
         "core_windows:core_release {\n"
         "    QMAKE_LFLAGS_RELEASE += /MAP:$$CORE_BUILDS_BINARY_PATH/x2t.map /MAPINFO:EXPORTS /OPT:REF /OPT:ICF /VERBOSE:LIB\n"
         "}\n"
         "# BASEMETAS_X2T_CI_END\n")
if "# BASEMETAS_X2T_CI_BEGIN" not in ptext:
    pro.write_text(ptext + block, encoding="utf-8", newline="\n")
print(f"Patched {pri}: CryptoPPLib, graphics and PdfFile in qmake graph")
print(f"Patched {pro}: Linux rpath-link and Windows size diagnostics")

# The pinned build_tools HEIF builder checks out x265 into x265_git, while the
# upstream qmake file still links against the old x265 directory.
heif_pri = core / "Common/3dParty/heif/heif.pri"
if not heif_pri.is_file():
    raise SystemExit(f"Missing HEIF qmake file: {heif_pri}")
heif_text = heif_pri.read_text(encoding="utf-8")
if "$$PWD/x265_git/build/" not in heif_text:
    if "$$PWD/x265/build/" not in heif_text:
        raise SystemExit("Unexpected heif.pri: x265 library path missing")
    heif_pri.write_text(
        heif_text.replace("$$PWD/x265/build/", "$$PWD/x265_git/build/"),
        encoding="utf-8", newline="\n",
    )
print(f"Patched {heif_pri}: use x265_git output from build_tools")

# The official tree stores these two files in lowercase. Windows hides the
# mismatch; a case-sensitive Linux checkout cannot compile the qmake paths.
metafile_pri = core / "DesktopEditor/graphics/pro/metafile.pri"
metafile_text = metafile_pri.read_text(encoding="utf-8")
for extension in ("cpp", "h"):
    old = f"/Wmf/WmfInterpretator/CWmfInterpretator.{extension}"
    new = f"/Wmf/WmfInterpretator/cwmfinterpretator.{extension}"
    if old not in metafile_text and new not in metafile_text:
        raise SystemExit(f"Unexpected metafile.pri: missing WMF {extension} input")
    metafile_text = metafile_text.replace(old, new)
metafile_pri.write_text(metafile_text, encoding="utf-8", newline="\n")
print(f"Patched {metafile_pri}: match case-sensitive WMF filenames")

# Make relative includes resolve from their own directory, rather than relying
# on unrelated include search directories (or a header never being compiled).
include_corrections = {
    "MsBinaryFile/Common/Base/Aggregat.h": [(b'"../../OOXML/Base/SmartPtr.h"', b'"../../../OOXML/Base/SmartPtr.h"')],
    "DesktopEditor/raster/heif/heif.h": [
        (b'"../../Common/3dParty/heif/', b'"../../../Common/3dParty/heif/'),
        (b'"../../UnicodeConverter/UnicodeConverter.h"', b'"../../../UnicodeConverter/UnicodeConverter.h"'),
    ],
}
for relative, replacements in include_corrections.items():
    header = core / relative
    content = header.read_bytes()
    for old, new in replacements:
        if old not in content and new not in content:
            raise SystemExit(f"Unexpected relative include in {header}: {old!r}")
        content = content.replace(old, new)
    header.write_bytes(content)
    print(f"Patched {header}: resolve includes relative to the header")
