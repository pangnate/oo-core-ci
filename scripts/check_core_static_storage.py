#!/usr/bin/env python3
"""Local g++ checks against real Core files; does not dispatch CI or build X2T."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    "UnicodeConverter/UnicodeConverter_Encodings.h", "RtfFile/Format/Utils.cpp",
    "MsBinaryFile/XlsFile/Format/Auxiliary/HelpFunc.cpp", "MsBinaryFile/Common/Vba/Records.cpp",
    "MsBinaryFile/Common/Base/FormatUtils.cpp", "OOXML/Binary/Presentation/XmlWriter.cpp",
    "OOXML/DocxFormat/ContentTypes.cpp", "OdfFile/Reader/Format/draw_shapes.cpp",
    "MsBinaryFile/XlsFile/Converter/xlsx_drawing_context.cpp",
    "OOXML/PPTXFormat/Namespaces.cpp", "OOXML/XlsxFormat/FileTypes_Spreadsheet.cpp",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-core", type=Path, default=ROOT / "core")
    parser.add_argument("--staged-core", type=Path, required=True)
    parser.add_argument("--boost-include", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which("g++"):
        parser.error("g++ required; on Windows run this script in WSL")
    args.receipt = args.receipt.resolve()
    results = []

    def run(command, core):
        completed = subprocess.run(command, cwd=core, capture_output=True, text=True)
        results.append({"command": command, "cwd": str(core), "exitCode": completed.returncode,
                        "stdoutSha256": hashlib.sha256(completed.stdout.encode()).hexdigest()})
        if completed.returncode:
            raise RuntimeError(completed.stderr[-6000:])
        return completed.stdout

    base_flags = ["g++", "-std=c++11", "-O1", "-w", "-DLINUX", "-D_LINUX",
                  "-DUNICODE", "-D_UNICODE", "-DDONT_WRITE_EMBEDDED_FONTS",
                  "-I" + str(args.boost_include.resolve())]
    try:
        after = args.staged_core.resolve()
        for source in SOURCES:
            run(base_flags + ["-IOdfFile/Common", "-fsyntax-only", source], after)
            print("syntax OK:", source, flush=True)
        with tempfile.TemporaryDirectory(prefix="core-static-native-") as temp:
            temp = Path(temp)
            comparisons = {"xml": [], "descriptors": []}
            for label, core in [("before", args.baseline_core.resolve()), ("after", after)]:
                flags = base_flags + ["-I" + str(core), "-ffunction-sections", "-fdata-sections"]
                xml = ROOT / "tests/core-features/cpp/core_xml_token_regression.cpp"
                exe = temp / ("xml-" + label)
                run(flags + ["-Wl,--gc-sections", str(xml), "OOXML/Binary/Presentation/XmlWriter.cpp",
                             "DesktopEditor/common/StringBuilder.cpp", "-o", str(exe)], core)
                comparisons["xml"].append(run([str(exe)], core))
                descriptor = ROOT / "tests/core-features/cpp/core_descriptor_storage_regression.cpp"
                obj = temp / ("other-" + label + ".o")
                run(flags + ["-DSTATIC_STORAGE_OTHER_TU", "-c", str(descriptor), "-o", str(obj)], core)
                exe = temp / ("descriptors-" + label)
                shared = ["-DCHECK_SHARED_STATIC_STORAGE"] if label == "after" else []
                run(flags + shared + ["-Wl,--gc-sections", str(descriptor), str(obj),
                    "OOXML/PPTXFormat/Namespaces.cpp", "OOXML/DocxFormat/FileType.cpp",
                    "OOXML/SystemUtility/SystemUtility.cpp", "OOXML/Base/Unit.cpp",
                    "OOXML/XlsxFormat/FileTypes_Spreadsheet.cpp",
                    "-o", str(exe)], core)
                comparisons["descriptors"].append(run([str(exe)], core))
            for name, outputs in comparisons.items():
                if outputs[0] != outputs[1]:
                    raise RuntimeError(name + " output changed")
                print("native before/after identical:", name, flush=True)
    finally:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps({"checks": results}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
