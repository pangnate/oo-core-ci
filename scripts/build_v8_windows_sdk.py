#!/usr/bin/env python3
"""Build the pinned Core V8 8.9 Windows x64 SDK and execute a native smoke probe."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "feature_deps"))
from common import validate_sdk_manifest

LOCK_PATH = ROOT / "config" / "v8-windows.lock.json"
LOCK = json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 3600) -> str:
    print("+", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8",
                               errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=timeout)
    print(completed.stdout, end="", flush=True)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {command[0]}")
    return completed.stdout


def replace_once(path: Path, old: str, new: str, *, already_ok: str | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if already_ok and already_ok in text:
            return
        raise RuntimeError(f"expected patch anchor missing: {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")


def probe(v8: Path, library: Path, work: Path, env: dict[str, str]) -> None:
    source = work / "v8_probe.cc"
    executable = work / "v8_probe.exe"
    source.write_text(r'''#include <iostream>
#include "include/libplatform/libplatform.h"
#include "include/v8.h"

int main() {
  v8::V8::InitializeICUDefaultLocation(nullptr);
  v8::V8::InitializeExternalStartupData(nullptr);
  auto platform = v8::platform::NewDefaultPlatform();
  v8::V8::InitializePlatform(platform.get());
  if (!v8::V8::Initialize()) return 10;
  v8::Isolate::CreateParams params;
  params.array_buffer_allocator = v8::ArrayBuffer::Allocator::NewDefaultAllocator();
  auto isolate = v8::Isolate::New(params);
  int result = 0;
  {
    v8::Isolate::Scope isolate_scope(isolate);
    v8::HandleScope handle_scope(isolate);
    auto context = v8::Context::New(isolate);
    v8::Context::Scope context_scope(context);
    auto text = v8::String::NewFromUtf8(isolate, "1 + 2", v8::NewStringType::kNormal).ToLocalChecked();
    auto script = v8::Script::Compile(context, text).ToLocalChecked();
    auto value = script->Run(context).ToLocalChecked();
    result = value->Int32Value(context).FromMaybe(-1);
  }
  isolate->Dispose();
  delete params.array_buffer_allocator;
  v8::V8::Dispose();
  v8::V8::ShutdownPlatform();
  if (result != 3) return 11;
  std::cout << "V8_PROBE_RESULT=" << result << std::endl;
  return 0;
}
''', encoding="utf-8")
    libs = [str(library), "winmm.lib", "advapi32.lib", "Shell32.lib", "DbgHelp.lib", "Shlwapi.lib"]
    run(["cl", "/nologo", "/EHsc", "/MD", "/std:c++14", "/DV8_COMPRESS_POINTERS",
         f"/I{v8}", str(source), *libs, f"/Fe:{executable}"], cwd=work, env=env, timeout=600)
    output = run([str(executable)], cwd=work, env=env, timeout=120)
    if "V8_PROBE_RESULT=3" not in output:
        raise RuntimeError("V8 linked executable did not produce the expected JS result")


def prepare_depot_tools(depot: Path) -> None:
    """Apply the pinned ONLYOFFICE v8_89 Windows bootstrap compatibility recipe."""
    manifest = depot / "bootstrap/manifest.txt"
    bootstrap = depot / "bootstrap/bootstrap.py"
    if not manifest.is_file() or not bootstrap.is_file():
        raise RuntimeError("pinned depot_tools checkout lacks expected bootstrap files")
    original = manifest.read_text(encoding="utf-8")
    if "# changed by build_tools" not in original:
        backup = manifest.with_suffix(".txt.upstream")
        if backup.exists():
            raise RuntimeError("refusing to overwrite an existing depot_tools manifest backup")
        shutil.copyfile(manifest, backup)
        manifest.write_text(
            "# changed by build_tools\n\n"
            "$VerifiedPlatform windows-amd64 windows-arm64 linux-amd64 mac-amd64 mac-arm64\n\n"
            "@Subdir python\n"
            "infra/3pp/tools/cpython/${platform} version:2@2.7.18.chromium.39\n\n"
            "@Subdir python3\n"
            "infra/3pp/tools/cpython3/${platform} version:2@3.11.8.chromium.35\n\n"
            "@Subdir git\n"
            "infra/3pp/tools/git/${platform} version:2@2.41.0.chromium.11\n",
            encoding="utf-8", newline="",
        )
    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    failed_git_bootstrap = re.compile(
        r"(?m)^([ \t]*)raise subprocess\.CalledProcessError\(proc\.returncode, argv, None\)$"
    )
    matches = list(failed_git_bootstrap.finditer(bootstrap_text))
    if len(matches) == 1:
        bootstrap_text = failed_git_bootstrap.sub(
            lambda match: f"{match.group(1)}# changed by build_tools: skip failed Windows git bootstrap\n{match.group(1)}return",
            bootstrap_text, count=1,
        )
        bootstrap.write_text(bootstrap_text, encoding="utf-8", newline="")
    elif "# changed by build_tools: skip failed Windows git bootstrap" not in bootstrap_text:
        raise RuntimeError("unexpected depot_tools bootstrap error-handling context")
    replace_once(bootstrap, "    _win_git_bootstrap_config()", "    #_win_git_bootstrap_config()",
                 already_ok="    #_win_git_bootstrap_config()")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, default=ROOT / "vendor" / "work")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("the V8 SDK card is Windows-only")
    if not shutil.which("cl") or not shutil.which("git"):
        raise SystemExit("cl.exe and git must be available on PATH")

    args.work_root = args.work_root.resolve()
    args.dist = args.dist.resolve()

    args.work_root.mkdir(parents=True, exist_ok=True)
    build = args.work_root / "v8-sdk-windows-x64"
    if build.exists():
        raise SystemExit(f"refusing to reuse existing build directory: {build}")
    build.mkdir()
    (build / ".v8-build-owner").write_text("build_v8_windows_sdk.py\n", encoding="utf-8")

    depot = build / "depot_tools"
    run(["git", "clone", "--no-checkout", LOCK["depotTools"]["url"], str(depot)],
        cwd=build, env=os.environ.copy(), timeout=900)
    run(["git", "-C", str(depot), "checkout", "--detach", LOCK["depotTools"]["ref"]],
        cwd=build, env=os.environ.copy(), timeout=300)
    depot_head = run(["git", "-C", str(depot), "rev-parse", "HEAD"], cwd=build,
                     env=os.environ.copy()).strip()
    if depot_head != LOCK["depotTools"]["ref"]:
        raise RuntimeError("depot_tools checkout does not match lock")
    prepare_depot_tools(depot)

    env = os.environ.copy()
    env["PATH"] = str(depot) + os.pathsep + env.get("PATH", "")
    env["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
    env["DEPOT_TOOLS_UPDATE"] = "0"
    env["GYP_MSVS_VERSION"] = "2019"
    env["GCLIENT_SUPPRESS_GIT_VERSION_WARNING"] = "1"
    run(["cmd", "/c", str(depot / "fetch.bat"), "--nohooks", "v8"], cwd=build, env=env, timeout=1800)

    v8 = build / "v8"
    if not v8.is_dir():
        raise RuntimeError("depot_tools fetch did not create v8 checkout")
    run(["git", "-C", str(v8), "checkout", "--detach", LOCK["v8"]["ref"]], cwd=build, env=env)
    run(["cmd", "/c", str(depot / "gclient.bat"), "sync", "--force", f"--revision=v8@{LOCK['v8']['ref']}"],
        cwd=build, env=env, timeout=3600)
    head = run(["git", "-C", str(v8), "rev-parse", "HEAD"], cwd=build, env=env).strip()
    if head != LOCK["v8"]["ref"]:
        raise RuntimeError(f"V8 checkout mismatch: {head}")

    gn = v8 / "buildtools/win/gn.exe"
    ninja = v8 / "third_party/ninja/ninja.exe"
    if not gn.is_file() or not ninja.is_file():
        raise RuntimeError("pinned V8 checkout did not provide its GN and Ninja binaries")

    replace_once(v8 / "build/config/win/BUILD.gn", ":static_crt", ":dynamic_crt")
    replace_once(v8 / "build/vs_toolchain.py",
                 "  def to_int_if_int(x):\n    try:\n      return int(x)\n    except ValueError:\n      return x",
                 "  def to_int_if_int(x):\n    try:\n      return int(x)\n    except ValueError:\n      return 0")
    wrappers = v8 / "src/base/platform/wrappers.cc"
    if not wrappers.exists():
        wrappers.write_text('#include "src/base/platform/wrappers.h"\n', encoding="utf-8")
    jinja = v8 / "third_party/jinja2/tests.py"
    if jinja.exists():
        replace_once(jinja, "from collections import Mapping",
                     "try:\n    from collections.abc import Mapping\nexcept ImportError:\n    from collections import Mapping",
                     already_ok="from collections.abc import Mapping")
    tool_wrapper = v8 / "build/toolchain/win/tool_wrapper.py"
    wrapper_text = tool_wrapper.read_text(encoding="utf-8")
    if "line = line.decode('utf8')" not in wrapper_text:
        replace_once(tool_wrapper, "for line in link.stdout:\n",
                     "for line in link.stdout:\n      line = line.decode('utf8')\n")

    args_string = " ".join(f'{key} = {json.dumps(value)}' for key, value in LOCK["gnArgs"].items())
    out = "out.gn/win_64/release"
    run([str(gn), "gen", out, f"--args={args_string}"], cwd=v8, env=env, timeout=900)
    ninja_file = v8 / out / "obj/v8_wrappers.ninja"
    if not ninja_file.is_file():
        raise RuntimeError(f"GN did not produce expected wrapper target: {ninja_file}")
    original = ninja_file.read_text(encoding="utf-8")
    wrapper_object = "build obj/v8_wrappers.obj: cxx ../../../src/base/platform/wrappers.cc"
    if wrapper_object not in original:
        adjusted = original.replace("target_output_name = v8_wrappers", "target_output_name = v8_wrappers\n" + wrapper_object, 1)
        adjusted = adjusted.replace("build obj/v8_wrappers.lib: alink", "build obj/v8_wrappers.lib: alink obj/v8_wrappers.obj", 1)
        if adjusted == original or "build obj/v8_wrappers.lib: alink obj/v8_wrappers.obj" not in adjusted:
            raise RuntimeError("unrecognized generated v8_wrappers.ninja format")
        ninja_file.write_text(adjusted, encoding="utf-8", newline="")
    try:
        run([str(ninja), "-C", out, "-j", str(min(int(env.get("NUMBER_OF_PROCESSORS", "4")), 4)), "v8_wrappers"], cwd=v8, env=env, timeout=3600)
    finally:
        ninja_file.write_text(original, encoding="utf-8", newline="")
    run([str(ninja), "-C", out, "-j", str(min(int(env.get("NUMBER_OF_PROCESSORS", "4")), 4)), "v8_monolith"],
        cwd=v8, env=env, timeout=14400)

    library = v8 / out / "obj/v8_monolith.lib"
    include = v8 / "include"
    if not library.is_file() or not (include / "v8.h").is_file():
        raise RuntimeError("V8 library or public headers are missing")
    probe(v8, library, build, env)

    sdk = args.dist / "v8-windows-x64-sdk"
    if sdk.exists():
        raise SystemExit(f"refusing to overwrite SDK output directory: {sdk}")
    (sdk / "include").mkdir(parents=True)
    shutil.copytree(include, sdk / "include", dirs_exist_ok=True)
    headers_archive = sdk / "include-headers.zip"
    with zipfile.ZipFile(headers_archive, "w", compression=zipfile.ZIP_STORED) as headers:
        for header in sorted(p for p in (sdk / "include").rglob("*") if p.is_file()):
            headers.write(header, header.relative_to(sdk / "include").as_posix())
    (sdk / "lib/win_64/release/obj").mkdir(parents=True)
    shutil.copy2(library, sdk / "lib/win_64/release/obj/v8_monolith.lib")
    manifest = {
        "schemaVersion": 1,
        "sdkId": LOCK["sdkId"],
        "kind": "development",
        "platform": LOCK["platform"],
        "abi": LOCK["abi"],
        "entries": [
            {"id": "v8-headers", "role": "include", "status": "verified", "source": f"V8 {head} public headers", "path": "dist/v8-windows-x64-sdk/include-headers.zip", "sha256": sha256(headers_archive)},
            {"id": "v8-monolith", "role": "library", "status": "verified", "source": f"V8 {head} GN/Ninja build", "path": "dist/v8-windows-x64-sdk/lib/win_64/release/obj/v8_monolith.lib", "sha256": sha256(sdk / "lib/win_64/release/obj/v8_monolith.lib")}
        ]
    }
    (sdk / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_sdk_manifest(manifest, repo_root=ROOT, platform=LOCK["platform"], kind="development",
                          abi=LOCK["abi"], required_roles={"include", "library"})
    provenance = {"schemaVersion": 1, "sdkId": LOCK["sdkId"], "coreRef": LOCK["coreRef"],
                  "buildToolsRef": LOCK["buildToolsRef"], "v8Ref": head, "depotToolsRef": depot_head,
                  "gnArgs": LOCK["gnArgs"], "abi": LOCK["abi"],
                  "bootstrapRecipe": "ONLYOFFICE build_tools v8_89 Windows 8.9 bootstrap compatibility edits",
                  "probe": {"source": "1 + 2", "expected": 3, "status": "passed"}}
    (sdk / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    archive = args.dist / "v8-windows-x64-sdk.zip"
    args.dist.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        for path in sorted(p for p in sdk.rglob("*") if p.is_file()):
            package.write(path, path.relative_to(args.dist).as_posix())
    (args.dist / "v8-windows-x64-sdk.zip.sha256").write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii")
    print(f"SDK={sdk}\nARCHIVE={archive}\nSHA256={sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
