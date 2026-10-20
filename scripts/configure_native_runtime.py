#!/usr/bin/env python3
"""Connect a built X2T runtime to matching SDKJS Native scripts for PDF export."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def config_path(runtime: Path, target: Path) -> str:
    try:
        return Path(os.path.relpath(target, runtime)).as_posix()
    except ValueError:  # Windows paths on different drives
        return target.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-bin", type=Path, required=True)
    parser.add_argument("--sdkjs-root", type=Path, required=True)
    parser.add_argument("--dictionaries", type=Path,
                        help="Optional dictionary directory used for hyphenation")
    parser.add_argument("--replace", action="store_true",
                        help="Replace an existing DoctRenderer.config")
    args = parser.parse_args()

    runtime = args.runtime_bin.resolve(strict=True)
    sdkjs = args.sdkjs_root.resolve(strict=True)
    if not runtime.is_dir() or not sdkjs.is_dir():
        parser.error("runtime-bin and sdkjs-root must be directories")
    if not (runtime / ("x2t.exe" if os.name == "nt" else "x2t")).is_file():
        parser.error(f"X2T executable is missing from {runtime}")

    required = (
        "common/Native/native.js",
        "common/Native/jquery_native.js",
        "vendor/xregexp-all-min.js",
        "word/sdk-all.js",
        "word/sdk-all-min.js",
        "slide/sdk-all.js",
        "cell/sdk-all.js",
    )
    missing = [name for name in required if not (sdkjs / name).is_file()]
    if missing:
        parser.error("SDKJS Native build is incomplete: " + ", ".join(missing))

    shim_source = Path(__file__).resolve().parent.parent / "runtime/native-window-shim.js"
    if not shim_source.is_file():
        shim_source = Path(__file__).resolve().parent / "native-window-shim.js"
    if not shim_source.is_file():
        parser.error(f"Native shim is missing: {shim_source}")
    shim_target = runtime / "native-window-shim.js"
    config_target = runtime / "DoctRenderer.config"
    if config_target.exists() and not args.replace:
        parser.error(f"{config_target} already exists; use --replace to update it")

    files = [
        sdkjs / "common/Native/native.js",
        shim_target,
        sdkjs / "common/Native/jquery_native.js",
        sdkjs / "vendor/xregexp-all-min.js",
    ]
    lines = ["<Settings>"]
    for path in files[:3]:
        lines.append(f"<file>{escape(config_path(runtime, path))}</file>")
    lines.append("<allfonts>./AllFonts.js</allfonts>")
    lines.append(f"<file>{escape(config_path(runtime, files[3]))}</file>")
    lines.append(f"<sdkjs>{escape(config_path(runtime, sdkjs))}</sdkjs>")
    if args.dictionaries:
        dictionaries = args.dictionaries.resolve(strict=True)
        if not dictionaries.is_dir():
            parser.error(f"dictionaries must be a directory: {dictionaries}")
        lines.append(f"<dictionaries>{escape(config_path(runtime, dictionaries))}</dictionaries>")
    lines.append("</Settings>")

    if shim_source.resolve() != shim_target.resolve():
        shutil.copyfile(shim_source, shim_target)
    temporary = config_target.with_suffix(".config.tmp")
    try:
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(config_target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Configured {config_target} for SDKJS {sdkjs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
