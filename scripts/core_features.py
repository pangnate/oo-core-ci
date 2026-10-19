#!/usr/bin/env python3
"""Source-profile runner for the Core feature POC.

Only the explicitly registered `fixtures` case is available at this stage.
Other cases fail closed until their owning cards implement them.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests" / "core-features"
REGISTRY = {
    "baseline": (TEST_ROOT / "test_baseline.py", "verify_baseline"),
    "fixtures": (TEST_ROOT / "test_fixtures.py", "verify_fixtures"),
    "contract": (TEST_ROOT / "test_contract.py", "verify_contract"),
}
SECRET_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|token|secret|authorization)(\s*[=:]\s*)([^\s,;]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer [REDACTED]"),
]


class RunnerError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def redact(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def require_assertions(count: int) -> None:
    if count <= 0:
        raise RunnerError("case completed with zero assertions")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunnerError(f"JSON root must be an object: {path}")
    return value


def validate_profile(profile_path: Path, case: str) -> tuple[dict[str, Any], Path]:
    profile_path = profile_path.resolve()
    profile = load_json(profile_path)
    if profile.get("schemaVersion") != 1:
        raise RunnerError("profile schemaVersion must be 1")
    if profile.get("level") != "source":
        raise RunnerError("this case requires a source-level profile")
    if profile.get("platform") not in {"windows-amd64", "linux-amd64", "linux-arm64"}:
        raise RunnerError("profile platform is missing or unsupported")
    baseline = load_json(ROOT / "ci" / "baseline.json")
    locks = load_json(ROOT / "vendor" / "checksums.json")
    core = profile.get("core")
    if not isinstance(core, dict):
        raise RunnerError("profile.core must be an object")
    if core.get("ref") != baseline.get("coreRef"):
        raise RunnerError("profile Core ref does not match ci/baseline.json")
    if core.get("treeSha256") != locks.get("core-source", {}).get("treeSha256"):
        raise RunnerError("profile Core tree hash does not match vendor/checksums.json")
    requirements = {
        "baseline": {"core-source", "baseline-evidence"},
        "fixtures": {"core-source", "fixture-manifest"},
        "contract": {"core-source", "feature-contract", "feature-profile-schema"},
    }.get(case)
    if requirements is None:
        raise RunnerError(f"case is not registered: {case}")
    inputs = profile.get("inputs")
    if not isinstance(inputs, dict):
        raise RunnerError("profile.inputs must be an object")
    for name in requirements:
        item = inputs.get(name)
        if not isinstance(item, dict):
            raise RunnerError(f"profile input missing: {name}")
        path = (ROOT / item.get("path", "")).resolve()
        if not path.is_file():
            raise RunnerError(f"profile input is missing: {name}")
        if sha256_file(path) != item.get("sha256"):
            raise RunnerError(f"profile input hash mismatch: {name}")
    fixture_dir = None
    if case == "fixtures":
        manifest_path = (ROOT / profile["inputs"]["fixture-manifest"]["path"]).resolve()
        if manifest_path.parent != TEST_ROOT / "fixtures":
            raise RunnerError("fixture manifest must be in the checked-in fixture directory")
        fixture_dir = manifest_path.parent
    return profile, fixture_dir


def _kill_owned_process(proc: subprocess.Popen[str]) -> None:
    """Stop only the process tree/group created for this runner child."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # /T scopes termination to this runner-created root process and its children.
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run_owned_process(command: list[str], timeout: float, *, env: dict[str, str] | None = None) -> tuple[int, str, bool, int]:
    kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                              "text": True, "encoding": "utf-8", "errors": "replace", "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, **kwargs)
    started_pid = proc.pid
    timed_out = False
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        partial = exc.output or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        _kill_owned_process(proc)
        try:
            tail, _ = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            tail = ""
        output = partial + (tail or "")
    return (proc.returncode if proc.returncode is not None else -9,
            redact(output), timed_out, started_pid)


def worker(case: str, profile_path: Path) -> int:
    module = REGISTRY.get(case)
    if module is None:
        print(f"ERROR: case is not registered: {case}")
        return 2
    try:
        profile, fixture_dir = validate_profile(profile_path, case)
    except RunnerError as exc:
        print(f"ERROR: {exc}")
        return 2
    module_path, function_name = REGISTRY[case]
    module_spec = importlib.util.spec_from_file_location(f"core_feature_{case}_case", module_path)
    if module_spec is None or module_spec.loader is None:
        raise RunnerError("fixture test module cannot be loaded")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    test_function = getattr(module, function_name, None)
    if test_function is None:
        print(f"ERROR: invalid registry handler for {case}")
        return 2
    if case == "fixtures":
        assertions = test_function(fixture_dir, profile)
    else:
        assertions = test_function(profile)
    try:
        require_assertions(assertions)
    except RunnerError as exc:
        print(f"ERROR: {exc}")
        return 3
    print(f"PASS: {case}; assertions={assertions}; profile={profile['name']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        print("ERROR: timeout must be positive", file=sys.stderr)
        return 2
    try:
        profile, _ = validate_profile(args.profile, args.case)
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if profile["platform"] != args.platform:
        print("ERROR: --platform does not match profile", file=sys.stderr)
        return 2
    if args.case not in REGISTRY:
        print(f"ERROR: case is not registered: {args.case}", file=sys.stderr)
        return 2
    if args.worker:
        return worker(args.case, args.profile)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--case", args.case,
               "--platform", args.platform, "--profile", str(args.profile.resolve())]
    started = time.time()
    code, output, timed_out, pid = run_owned_process(command, args.timeout, env=os.environ.copy())
    if args.log_dir:
        args.log_dir.mkdir(parents=True, exist_ok=True)
        record = {"case": args.case, "platform": args.platform, "profile": str(args.profile.resolve()),
                  "pid": pid, "timeoutSeconds": args.timeout, "timedOut": timed_out,
                  "exitCode": code, "durationSeconds": round(time.time() - started, 3), "output": output}
        (args.log_dir / f"{args.case}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(output)
    if timed_out:
        print(f"ERROR: case timed out after {args.timeout}s (owned pid {pid})", file=sys.stderr)
        return 124
    return code


if __name__ == "__main__":
    raise SystemExit(main())
