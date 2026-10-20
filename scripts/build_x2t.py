#!/usr/bin/env python3
"""Build one Core target with bounded concurrency, compiler caching and timings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from branding import load_branding
from build_metrics import ResourceMonitor, build_jobs
from native_sources import verify_for_build
from audit_source_paths import audit as audit_source_paths

ROOT = Path(__file__).resolve().parents[1]
BT = ROOT / "build_tools"
CORE = ROOT / "core"


def qmake_arguments(qt: Path, project: Path, configuration: list[str], *, windows: bool, cache: bool) -> list[str]:
    params = ["-r", "-nocache", str(project), *configuration, "CONFIG+=x2t_inputs"]
    if not windows:
        qtconf = qt / "onlyoffice_qt.conf"
        if not qtconf.is_file():
            raise FileNotFoundError(f"Missing prepared qmake relocation config: {qtconf}")
        params += ["-qtconf", str(qtconf)]
    if cache:
        params.append("CONFIG+=x2t_cache")
    return params


def main() -> None:
    organization, _, parts = load_branding()
    os.environ.update(PUBLISHER_NAME=organization, PRODUCT_VERSION=".".join(map(str, parts[:3])),
                      BUILD_NUMBER=str(parts[3]))
    sys.path.insert(0, str(BT / "scripts"))
    os.chdir(BT)
    import base
    import config
    import qmake

    config.parse()
    config.parse_defaults()
    target = config.option("platform").split()
    if len(target) != 1 or target[0] not in ("win_64", "linux_64", "linux_arm64"):
        raise ValueError("configure exactly one X2T target before building")
    target = target[0]
    verify_for_build(CORE, target, ROOT)
    base.set_env("BUILD_PLATFORM", target)
    base.set_env("OS_DEPLOY", target)
    cpu_count = os.cpu_count() or 1
    jobs = build_jobs()
    cache = os.environ.get("X2T_SCCACHE", "")
    if cache:
        if not Path(cache).is_file():
            raise FileNotFoundError(cache)
    features = str(ROOT / "scripts/qmake")
    if os.environ.get("QMAKEFEATURES"):
        features += os.pathsep + os.environ["QMAKEFEATURES"]
    os.environ["QMAKEFEATURES"] = features
    project = CORE / "X2tConverter/build/Qt/X2tSLN.pro"
    (project.parent / ".qmake.stash").unlink(missing_ok=True)
    makefile = "Makefile." + qmake.get_make_file_suffix(target)
    os.environ["DEST_MAKEFILE_NAME"] = "./" + makefile
    qt = Path(base.qt_setup(target))
    windows = target == "win_64"
    qmake_app = qt / "bin" / ("qmake.exe" if windows else "qmake")
    params = qmake_arguments(qt, project, base.qt_config_as_param(base.qt_config(target)), windows=windows, cache=bool(cache))
    if windows:
        jom = os.environ.get("X2T_JOM", "")
        if cache and not jom:
            raise RuntimeError("Windows object caching requires jom for no_batch compilation")
        make = [jom, f"-j{jobs}"] if jom else ["nmake", "/NOLOGO"]
        if cache:
            # jom owns concurrency; preserve other user compiler flags.
            for name in ("CL", "_CL_"):
                flags = os.environ.get(name, "").split()
                os.environ[name] = " ".join(flag for flag in flags if not flag.lower().startswith("/mp"))
    else:
        if config.option("sysroot"):
            os.environ["QMAKE_CUSTOM_SYSROOT"] = config.option("sysroot_" + target)
            os.environ["QMAKE_CUSTOM_SYSROOT_BIN"] = config.get_custom_sysroot_bin(target)
            os.environ["PKG_CONFIG_PATH"] = config.get_custom_sysroot_lib(target, True) + "/pkgconfig"
            os.environ["PKG_CONFIG_SYSROOT_DIR"] = config.option("sysroot_" + target)
        make = ["make", f"-j{jobs}", "--print-directory"]
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    started = time.monotonic()
    metrics = {"platform": target, "sourceSha": os.environ.get("GITHUB_SHA", ""),
               "coreId": os.environ.get("X2T_CORE_ID", ""), "cpuCount": cpu_count, "jobs": jobs,
               "compilerCache": bool(cache), "stages": [], "exitCode": 1}
    sysroot_active = False
    monitor = ResourceMonitor(ROOT)
    monitor.start()

    with (dist / f"build-{target}.log").open("w", encoding="utf-8") as log:
        def run(stage: str, command: list[str], required: bool = True) -> None:
            begin = time.monotonic()
            print(f"[{stage}] {' '.join(command)}", flush=True)
            process = subprocess.Popen(command, cwd=project.parent, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            for line in process.stdout:
                stamped = f"[{time.monotonic() - started:9.2f}s] {line}"
                log.write(stamped)
                print(stamped, end="", flush=True)
            code = process.wait()
            metrics["stages"].append({"name": stage, "seconds": round(time.monotonic() - begin, 3), "exitCode": code})
            if code and required:
                raise subprocess.CalledProcessError(code, command)

        try:
            run("qmake", [str(qmake_app), *params])
            if not windows:
                base.set_sysroot_env(target)
                sysroot_active = True
            if config.option("clean") == "1":
                run("clean", [*make, "-f", makefile, "clean"], required=False)
                run("distclean", [*make, "-f", makefile, "distclean"], required=False)
                if sysroot_active:
                    base.restore_sysroot_env()
                    sysroot_active = False
                run("qmake-after-clean", [str(qmake_app), *params])
                if not windows:
                    base.set_sysroot_env(target)
                    sysroot_active = True
            audit_source_paths(CORE, dist / f"source-path-audit-{target}.json")
            run("compile-and-link", [*make, "-f", makefile])
            metrics["exitCode"] = 0
        finally:
            monitor.stop()
            if sysroot_active:
                base.restore_sysroot_env()
            metrics["seconds"] = round(time.monotonic() - started, 3)
            metrics["resources"] = monitor.samples
            (dist / f"build-metrics-{target}.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
            if cache:
                stats = subprocess.run([cache, "--show-stats", "--stats-format", "json"],
                                       capture_output=True, text=True, encoding="utf-8", errors="replace")
                (dist / f"sccache-stats-{target}.json").write_text(stats.stdout or stats.stderr, encoding="utf-8")
    print(f"X2T build complete: {target}; {metrics['seconds']} seconds; jobs={jobs}")


if __name__ == "__main__":
    main()
