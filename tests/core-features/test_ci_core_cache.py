"""Protect reuse boundaries without starting a native Core build."""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import ci_core_cache as cache
import ci_handoff
import prepare
import build_metrics
import build_x2t
import ci_deps_key
import setup_build_acceleration


class CoreReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(cache, "ROOT", self.root))
        self.stack.enter_context(patch.object(ci_handoff, "ROOT", self.root))
        self.stack.enter_context(patch.dict(os.environ, {
            "ImageOS": "test", "ImageVersion": "image-1", "GITHUB_SHA": "producer-sha",
            "GITHUB_RUN_ID": "123", "X2T_DEPS_ID": "deps-1"}))

    def write(self, relative, value="data"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True, stderr=subprocess.DEVNULL)

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Cache test", "-c", "user.email=cache@example.invalid",
                 "commit", "-qm", "fixture")

    def cli(self, command, core_id="input-1", platform="win_64"):
        with patch.object(sys, "argv", ["ci_core_cache.py", command, "--platform", platform, "--core-id", core_id]):
            with contextlib.redirect_stdout(io.StringIO()):
                cache.main()

    def seed_outputs(self, platform="win_64"):
        for relative in cache.paths(platform):
            if relative in (f"core/build/bin/{platform}", f"core/Common/3dParty/icu/{platform}/build", f"core/build/lib/{platform}"):
                (self.root / relative).mkdir(parents=True)
            elif "core-producer" not in relative:
                self.write(relative, "{}")
        self.write(f"core/build/bin/{platform}/{'x2t.exe' if platform == 'win_64' else 'x2t'}", "compiled executable")
        if platform == "win_64":
            self.write("core/build/bin/win_64/graphics.dll", "compiled graphics")
            self.write("core/build/bin/win_64/PdfFile.dll", "compiled PDF")
        self.write(f"core/Common/3dParty/icu/{platform}/build/icu.dll", "compiled dependency")
        self.write(f"dist/core-inputs-{platform}.json", json.dumps({"coreId": "input-1", "inputs": {"platform": platform}}))
        self.cli("record", platform=platform)

    def test_key_ignores_docs_but_invalidates_compilation_inputs(self):
        self.write("config/build-acceleration.json", '{"parallelism":"cpu-count"}')
        self.write("config/branding.json", '{"version":"1.0.0.1"}')
        self.write("core/source.cpp", "old source")
        self.git("init", "-q")
        self.commit()
        with patch.object(cache, "INPUTS", ("core", "config")):
            original = cache.identity("win_64", "deps-1")["coreId"]
            self.write("docs/readme.md", "unrelated edit")
            self.commit()
            self.assertEqual(original, cache.identity("win_64", "deps-1")["coreId"])
            self.assertNotEqual(original, cache.identity("linux_64", "deps-1")["coreId"])
            self.assertNotEqual(original, cache.identity("win_64", "deps-2")["coreId"])
            with patch.dict(os.environ, ImageVersion="image-2"):
                self.assertNotEqual(original, cache.identity("win_64", "deps-1")["coreId"])
            with patch.dict(os.environ, CL="/DCHANGED_COMPILER_INPUT=1"):
                self.assertNotEqual(original, cache.identity("win_64", "deps-1")["coreId"])
            self.write("core/source.cpp", "changed source")
            self.commit()
            changed = cache.identity("win_64", "deps-1")["coreId"]
            self.assertNotEqual(original, changed)
            self.write("config/branding.json", '{"version":"1.0.0.2"}')
            self.commit()
            self.assertNotEqual(changed, cache.identity("win_64", "deps-1")["coreId"])

    def test_reuse_preserves_producer_and_rebinds_only_the_job_handoff(self):
        self.seed_outputs()
        self.cli("pack")
        binary = self.root / "core/build/bin/win_64/x2t.exe"
        binary.write_text("overwritten")
        with patch.dict(os.environ, GITHUB_SHA="consumer-sha", GITHUB_RUN_ID="456"):
            self.cli("restore")
            self.assertEqual(binary.read_text(), "compiled executable")
            producer = json.loads((self.root / "dist/core-producer-win_64.json").read_text())
            self.assertEqual(producer["sourceSha"], "producer-sha")
            args = argparse.Namespace(archive=str(self.root / "dist/build-win_64.tar"), stage="build",
                                      platform="win_64", source_sha="consumer-sha", path=cache.paths("win_64"), optional=[])
            with contextlib.redirect_stdout(io.StringIO()):
                ci_handoff.create(args)
                ci_handoff.restore(args)
            metadata = json.loads(Path(args.archive + ".json").read_text())
            self.assertEqual(metadata["sourceSha"], "consumer-sha")

    def test_wrong_key_and_corrupt_archive_are_rejected(self):
        self.seed_outputs()
        self.cli("pack")
        with self.assertRaisesRegex(ValueError, "sourceSha"):
            self.cli("restore", "wrong-input")
        archive = self.root / "dist/core-cache-win_64.tar"
        with archive.open("ab") as output:
            output.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.cli("restore")

    def test_changed_executable_is_rejected_before_caching(self):
        self.seed_outputs()
        self.write("core/build/bin/win_64/x2t.exe", "changed after compile")
        with self.assertRaisesRegex(ValueError, "producer receipt"):
            self.cli("pack")

    def test_changed_rebuilt_dll_is_rejected_before_caching(self):
        self.seed_outputs()
        self.write("core/build/bin/win_64/graphics.dll", "different DLL")
        with self.assertRaisesRegex(ValueError, "source-built module"):
            self.cli("pack")

    def test_linux_architectures_reuse_their_own_output_layout(self):
        for platform in ("linux_64", "linux_arm64"):
            with self.subTest(platform=platform):
                self.seed_outputs(platform)
                self.cli("pack", platform=platform)
                self.write(f"core/build/bin/{platform}/x2t", "corruption")
                self.cli("restore", platform=platform)
                self.assertEqual((self.root / f"core/build/bin/{platform}/x2t").read_text(), "compiled executable")


class ParallelismTests(unittest.TestCase):
    def test_default_parallelism_follows_private_and_public_runner_cpu_counts(self):
        with patch.dict(os.environ, {}, clear=True):
            for count in (2, 4, 16):
                with patch.object(build_metrics.os, "cpu_count", return_value=count):
                    self.assertEqual(build_metrics.build_jobs(), count)


class LinuxSysrootTests(unittest.TestCase):
    def test_linux_dependency_key_uses_locked_inputs_instead_of_runner_image(self):
        objects = {path: "a" * 40 for path in ci_deps_key.INPUTS + ci_deps_key.WINDOWS_INPUTS}
        def git_object(command, **kwargs):
            return SimpleNamespace(stdout=objects[command[-1].removeprefix("HEAD:")])
        with patch.object(ci_deps_key.subprocess, "run", side_effect=git_object):
            with patch.dict(os.environ, ImageOS="ubuntu24", ImageVersion="20261012", X2T_COMPILER_VERSION="host-a"):
                first = ci_deps_key.identity("linux_64")
                windows = ci_deps_key.identity("win_64")
            with patch.dict(os.environ, ImageOS="ubuntu24", ImageVersion="20261018", X2T_COMPILER_VERSION="host-b"):
                self.assertEqual(first, ci_deps_key.identity("linux_64"))
                self.assertNotEqual(windows, ci_deps_key.identity("win_64"))
                self.assertNotEqual(first, ci_deps_key.identity("linux_arm64"))
                objects["scripts/windows_build.cmd"] = "b" * 40
                self.assertEqual(first, ci_deps_key.identity("linux_64"))
                for path in ("vendor/checksums.json", "ci/toolchains", "build_tools", "scripts/make_minimal_deps.py"):
                    objects[path] = "b" * 40
                    self.assertNotEqual(first, ci_deps_key.identity("linux_64"))
                    objects[path] = "a" * 40

    def test_sccache_action_windows_extensionless_path(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "sccache.exe"
            binary.write_bytes(b"fixture")
            extensionless = str(binary.with_suffix(""))
            self.assertEqual(setup_build_acceleration.resolve_sccache(extensionless, windows=True), binary.resolve())
            self.assertEqual(setup_build_acceleration.resolve_sccache(str(binary), windows=True), binary.resolve())
            with self.assertRaisesRegex(RuntimeError, "executable is missing"):
                setup_build_acceleration.resolve_sccache(extensionless, windows=False)
            native = Path(extensionless)
            native.write_bytes(b"fixture")
            self.assertEqual(setup_build_acceleration.resolve_sccache(extensionless, windows=False), native.resolve())

    def test_linux_qmake_receives_prepared_relocation_config(self):
        with tempfile.TemporaryDirectory() as directory:
            qt = Path(directory)
            project = qt / "project.pro"
            with self.assertRaisesRegex(FileNotFoundError, "relocation config"):
                build_x2t.qmake_arguments(qt, project, ["CONFIG+=release"], windows=False, cache=True)
            conf = qt / "onlyoffice_qt.conf"
            conf.write_text("Prefix = " + qt.as_posix())
            args = build_x2t.qmake_arguments(qt, project, ["CONFIG+=release"], windows=False, cache=True)
            self.assertEqual(args[args.index("-qtconf") + 1], str(conf))
            self.assertIn("-r", args)
            self.assertIn("CONFIG+=x2t_cache", args)
            self.assertIn("CONFIG+=x2t_inputs", args)

    def test_dependency_identity_is_exported_from_producer_to_consumer(self):
        for target in ("linux", "windows"):
            text = (REPO / f".github/workflows/x2t-{target}.yml").read_text(encoding="utf-8")
            producer, consumer = text.split("\n  build:", 1)
            consumer = consumer.split("\n  verify:", 1)[0]
            self.assertIn("deps-id: ${{ env.X2T_DEPS_ID }}", producer)
            self.assertIn("X2T_DEPS_ID: ${{ needs.deps.outputs.deps-id }}", consumer)
            self.assertNotIn("scripts/ci_deps_key.py", consumer)
            if target == "windows":
                self.assertIn("needs.deps.outputs.compiler-version", consumer)

    def test_amd64_needs_no_arm_sysroot_and_missing_inputs_never_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "scripts/config.py"
            path.parent.mkdir(parents=True)
            path.write_text((REPO / "build_tools/scripts/config.py").read_text(encoding="utf-8"), encoding="utf-8")
            with patch.object(prepare, "BT", root):
                prepare.patch_linux_sysroot_check()
                first = path.read_text(encoding="utf-8")
                prepare.patch_linux_sysroot_check()
                self.assertEqual(first, path.read_text(encoding="utf-8"))
            tree = ast.parse(first)
            branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                          and ast.unparse(node.test) == "options['sysroot'] == '1'")
            code = compile(ast.Module(body=branch.body, type_ignores=[]), str(path), "exec")
            base = SimpleNamespace(get_script_dir=lambda *_: str(root), is_dir=lambda value: "amd64" in value)
            for platform in ("linux_64", "linux_arm64"):
                scope = {"__file__": str(path), "os": os, "base": base, "options": {},
                         "check_option": lambda name, value: value == platform}
                if platform == "linux_64":
                    exec(code, scope)
                    self.assertIn("sysroot_linux_64", scope["options"])
                else:
                    with self.assertRaisesRegex(RuntimeError, "Missing locked sysroot"):
                        exec(code, scope)


if __name__ == "__main__":
    unittest.main()
