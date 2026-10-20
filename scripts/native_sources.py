#!/usr/bin/env python3
"""Restore ignored native source inputs from committed, checksum-locked archives.

The transformations below mirror pinned Core's html/fetch.py and
harfbuzz/make.py. No git clone or network request is made during preparation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"gumbo", "katana", "harfbuzz", "hyphen"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_lock(root: Path = ROOT) -> dict:
    lock = json.loads((root / "config/native-sources.lock.json").read_text(encoding="utf-8"))
    if lock.get("schemaVersion") != 1 or set(lock.get("sources", {})) != REQUIRED:
        raise ValueError("Native source lock must identify all four supplemental sources")
    for name, item in lock["sources"].items():
        if not re.fullmatch(r"[0-9a-f]{40}", item.get("commit", "")):
            raise ValueError(f"Invalid pinned commit: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")):
            raise ValueError(f"Invalid archive SHA256: {name}")
        for field, prefix in (("file", "vendor/archives/"), ("destination", "Common/3dParty/")):
            value = item.get(field, "")
            if not value.startswith(prefix) or ".." in Path(value).parts or "\\" in value:
                raise ValueError(f"Unsafe native source {field}: {name}")
    return lock


def verify_archives(root: Path = ROOT) -> dict:
    lock = load_lock(root)
    for name, item in lock["sources"].items():
        archive = root / item["file"]
        if not archive.is_file() or sha256(archive) != item["sha256"]:
            raise ValueError(f"Missing or corrupt locked {name} archive: {archive}")
    return lock


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise ValueError(f"Pinned native patch no longer applies: {path}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def harfbuzz_pri(directory: Path) -> str:
    files = sorted(path.relative_to(directory).as_posix()
                   for folder in (directory, directory / "graph")
                   for path in folder.iterdir() if path.is_file())
    headers = [name for name in files if Path(name).suffix in (".h", ".hh")]
    sources = [name for name in files if Path(name).suffix in (".c", ".cc")
               and Path(name).name not in ("main.cc", "failing-alloc.c")
               and not Path(name).name.startswith(("test", "harfbuzz"))]
    if not headers or "hb-ft.cc" not in sources:
        raise ValueError("Incomplete pinned HarfBuzz source tree")
    lines = ["SRC_DIR = $$PWD/harfbuzz/src", "DEFINES += HAVE_FREETYPE HB_NO_VISIBILITY",
             "INCLUDEPATH += $$SRC_DIR"]
    for variable, names in (("HEADERS", headers), ("SOURCES", sources)):
        lines.append(variable + " += " + (" " + chr(92) + "\n  ").join("$$SRC_DIR/" + name for name in names))
    return "\n".join(lines) + "\n"


def prepare(core: Path, root: Path = ROOT) -> None:
    lock = verify_archives(root)
    core = core.resolve()
    for item in lock["sources"].values():
        destination = (core / item["destination"]).resolve()
        if not destination.is_relative_to(core / "Common/3dParty") or destination.is_symlink():
            raise ValueError(f"Native source destination escapes Core: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="x2t-native-") as scratch:
            unpacked = Path(scratch)
            with tarfile.open(root / item["file"], "r:gz") as archive:
                archive.extractall(unpacked, filter="data")
            children = list(unpacked.iterdir())
            if len(children) != 1 or not children[0].is_dir():
                raise ValueError(f"Unexpected native archive layout: {item['file']}")
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(children[0]), str(destination))
    third_party = core / "Common/3dParty"
    replace(third_party / "html/gumbo-parser/src/tag.c", "isspace(*c)", "isspace((unsigned char)*c)")
    katana = third_party / "html/katana-parser/src"
    replace(katana / "tokenizer.c", "static inline bool katana_is_html_space(char c);",
            "static inline bool2 katana_is_html_space(char c);")
    replace(katana / "tokenizer.c", "inline bool katana_is_html_space(char c)",
            "static inline bool katana_is_html_space(char c)")
    replace(katana / "tokenizer.c", "static inline bool2 katana_is_html_space(char c);",
            "static inline bool katana_is_html_space(char c);")
    replace(katana / "parser.c", "katanaget_text(parser->scanner)", '/*katanaget_text(parser->scanner)*/"error"')
    replace(katana / "parser.c", "#define KATANA_PARSER_STRING(literal) (KatanaParserString){",
            "#define KATANA_PARSER_STRING(literal) {")
    replace(katana / "foundation.c", "size_t len = strlen(str);",
            "if (NULL == str)\n        return;\n    size_t len = strlen(str);")
    hb = third_party / "harfbuzz"
    patch = (hb / "patch/hb-ft.cc.patch").read_text(encoding="utf-8")
    old = patch.split("<<<<<<<", 1)[1].split("=======", 1)[0]
    new = patch.split("=======", 1)[1].split(">>>>>>>", 1)[0]
    replace(hb / "harfbuzz/src/hb-ft.cc", old, "\n#if 0" + old + "#else" + new + "#endif\n")
    (hb / "harfbuzz.pri").write_text(harfbuzz_pri(hb / "harfbuzz/src"), encoding="utf-8", newline="\n")
    (hb / "module.version").write_text("1", encoding="utf-8")
    verify(core, root)


def verify(core: Path, root: Path = ROOT) -> None:
    load_lock(root)
    required = (
        "html/katana-parser/src/katana.h", "html/katana-parser/src/parser.c",
        "html/gumbo-parser/src/gumbo.h", "hyphen/hyphen/hnjalloc.h",
        "hyphen/hyphen/hnjalloc.c", "hyphen/hyphen/hyphen.c", "hyphen/hyphen/hyphen.h",
        "harfbuzz/harfbuzz/src/hb-ft.cc", "harfbuzz/harfbuzz/src/hb.h",
    )
    third_party = core / "Common/3dParty"
    missing = [name for name in required if not (third_party / name).is_file()]
    if missing:
        raise ValueError("Missing native build inputs; run prepare.py: " + ", ".join(missing))
    hb = third_party / "harfbuzz"
    pri = hb / "harfbuzz.pri"
    if not pri.is_file() or pri.read_text(encoding="utf-8") != harfbuzz_pri(hb / "harfbuzz/src"):
        raise ValueError("Missing or stale generated HarfBuzz qmake input; run prepare.py")
    print("Locked native build inputs OK: Gumbo, Katana, HarfBuzz, Hyphen")


def verify_for_build(core: Path, target: str, root: Path = ROOT) -> None:
    """Check unpacked sources and restored dependency outputs before qmake/make."""
    verify(core, root)
    if target not in {"win_64", "linux_64", "linux_arm64"}:
        raise ValueError(f"Unsupported native build target: {target}")
    third = core / "Common/3dParty"
    required = [third / "brotli/brotli/c/include/brotli/decode.h",
                third / "brotli/brotli/c/dec/decode.c",
                third / "brotli/brotli/c/common/constants.c",
                third / f"boost/build/{target}/include/boost/version.hpp",
                third / "heif/libheif/libheif/api/libheif/heif.h"]
    icu = third / f"icu/{target}/build"
    heif = third / f"heif/libheif/build/{target}/release"
    x265 = third / f"heif/x265_git/build/{target}/release"
    de265 = third / f"heif/libde265/build/{target}/release/libde265"
    major = json.loads((root / "vendor/detected-deps.json").read_text(encoding="utf-8"))["icu"]["version"].split(".")[0]
    if target == "win_64":
        required += [icu / name for name in ("icuuc.lib", "icudt.lib", f"icuuc{major}.dll", f"icudt{major}.dll")]
        required += [heif / "libheif/Release/heif.lib", x265 / "Release/x265-static.lib", de265 / "Release/libde265.lib"]
    else:
        required += [icu / f"libicuuc.so.{major}", icu / f"libicudata.so.{major}", icu / "include/unicode/ucnv.h"]
        required += [heif / "libheif/libheif.a", x265 / "libx265.a", de265 / "libde265.a"]
    missing = [str(path.relative_to(core)) for path in required if not path.is_file() or path.stat().st_size == 0]
    for name in ("filesystem", "system", "regex", "date_time"):
        pattern = f"libboost_{name}-vc142-*.lib" if target == "win_64" else f"libboost_{name}.a"
        if not any(path.stat().st_size for path in (third / f"boost/build/{target}/lib").glob(pattern)):
            missing.append(f"Common/3dParty/boost/build/{target}/lib/{pattern}")
    if missing:
        raise ValueError("Incomplete prepared source/dependency handoff:\n" + "\n".join(missing))
    print(f"Prepared source and dependency outputs OK: {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--core-root", type=Path, default=ROOT / "core")
    args = parser.parse_args()
    (prepare if args.command == "prepare" else verify)(args.core_root)
