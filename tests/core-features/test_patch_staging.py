from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGER_PATH = ROOT / "scripts" / "stage_core_source.py"
spec = importlib.util.spec_from_file_location("core_source_stager", STAGER_PATH)
assert spec and spec.loader
stager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stager)
download_spec = importlib.util.spec_from_file_location("core_source_downloader", ROOT / "scripts" / "download.py")
assert download_spec and download_spec.loader
downloader = importlib.util.module_from_spec(download_spec)
download_spec.loader.exec_module(downloader)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _patch(old: str, new: str) -> str:
    return ("diff --git a/core/demo.txt b/core/demo.txt\n"
            "index 0000000..1111111 100644\n"
            "--- a/core/demo.txt\n+++ b/core/demo.txt\n"
            f"@@ -1 +1 @@\n-{old}\n+{new}\n")


def _fixture_repo(parent: Path, *, wrong_base: bool = False) -> tuple[Path, Path, dict, dict, dict]:
    repo = parent / "repo"
    source = repo / "vendor" / "work" / "source"
    source.mkdir(parents=True)
    (source / "demo.txt").write_text("wrong\n" if wrong_base else "base\n", encoding="utf-8")
    (repo / "vendor" / "work").mkdir(exist_ok=True)
    patch_dir = repo / "patches" / "core"
    patch_dir.mkdir(parents=True)
    first = patch_dir / "001-first.patch"
    second = patch_dir / "002-second.patch"
    first.write_text(_patch("base", "middle"), encoding="utf-8", newline="\n")
    second.write_text(_patch("middle", "final"), encoding="utf-8", newline="\n")
    ref = "a" * 40
    tree = "b" * 64
    lock = {"ref": ref, "treeSha256": tree, "files": 1,
            "extractedTreeFingerprint": stager.inventory_fingerprint(source)[1],
            "extractedTreeFingerprintAlgorithm": "sha256(sorted UTF-8 relative path + NUL + decimal size + NUL + file SHA256 hex + LF)"}
    series = {"schemaVersion": 1, "coreRef": ref, "coreTreeSha256": tree,
              "patches": [
                  {"path": "patches/core/001-first.patch", "sha256": _sha(first), "purpose": "fixture first"},
                  {"path": "patches/core/002-second.patch", "sha256": _sha(second), "purpose": "fixture second",
                   "dependsOn": ["patches/core/001-first.patch"]},
              ]}
    baseline = {"coreRef": ref, "coreBuildPatches": [], "coreOverlays": []}
    checksums = {"core-source": lock}
    return repo, source, baseline, checksums, series


def _verify_build_correction_precedes_feature_patch(parent: Path) -> int:
    repo = parent / "ordered-repo"
    source = repo / "vendor" / "work" / "source"
    source.mkdir(parents=True)
    (source / "demo.txt").write_text("base\n", encoding="utf-8")
    correction = repo / "scripts" / "build-correction.py"
    correction.parent.mkdir()
    correction.write_text(
        "import argparse\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser(); p.add_argument('--core-root', type=Path); a=p.parse_args()\n"
        "(a.core_root / 'demo.txt').write_text('middle\\n', encoding='utf-8')\n",
        encoding="utf-8", newline="\n")
    patch_path = repo / "patches" / "core" / "001-after-correction.patch"
    patch_path.parent.mkdir(parents=True)
    patch_path.write_text(_patch("middle", "final"), encoding="utf-8", newline="\n")
    ref, tree = "c" * 40, "d" * 64
    lock = {"ref": ref, "treeSha256": tree, "files": 1,
            "extractedTreeFingerprint": stager.inventory_fingerprint(source)[1],
            "extractedTreeFingerprintAlgorithm": "sha256(sorted UTF-8 relative path + NUL + decimal size + NUL + file SHA256 hex + LF)"}
    series = {"schemaVersion": 1, "coreRef": ref, "coreTreeSha256": tree,
              "patches": [{"path": "patches/core/001-after-correction.patch", "sha256": _sha(patch_path),
                           "purpose": "must follow the build correction"}]}
    baseline = {"coreRef": ref, "coreBuildPatches": ["scripts/build-correction.py"], "coreOverlays": []}
    receipt = stager.stage_core_source(
        repo_root=repo, source_root=source, destination=repo / "vendor" / "work" / "ordered-stage",
        baseline=baseline, checksums={"core-source": lock}, patch_series=series)
    assert (repo / "vendor" / "work" / "ordered-stage" / "core" / "demo.txt").read_text(encoding="utf-8") == "final\n"
    assert receipt["buildCorrections"][0]["path"] == "scripts/build-correction.py"
    return 2


def verify_patch_staging(_profile: dict) -> int:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="patch-staging-") as temp:
        parent = Path(temp)
        repo, source, baseline, checksums, series = _fixture_repo(parent)
        before = stager.inventory_fingerprint(source)
        dest = repo / "vendor" / "work" / "stage-one"
        receipt = stager.stage_core_source(repo_root=repo, source_root=source, destination=dest,
                                           baseline=baseline, checksums=checksums, patch_series=series,
                                           build_patches=[], overlay_files=[])
        assertions += 1
        assert (dest / "core" / "demo.txt").read_text(encoding="utf-8") == "final\n"
        assertions += 1
        assert (dest / ".core-staging-owner").is_file()
        assertions += 1
        assert stager.inventory_fingerprint(source) == before
        assertions += 1
        assert receipt["sourceInventorySha256Before"] == receipt["sourceInventorySha256After"]
        assert receipt["featurePatches"] == [{"path": p["path"], "sha256": p["sha256"]} for p in series["patches"]]
        assertions += 1
        second_dest = repo / "vendor" / "work" / "stage-repeat"
        second_receipt = stager.stage_core_source(repo_root=repo, source_root=source, destination=second_dest,
                                                  baseline=baseline, checksums=checksums, patch_series=series,
                                                  build_patches=[], overlay_files=[])
        assert second_receipt["stagedCoreInventorySha256"] == receipt["stagedCoreInventorySha256"]
        assertions += 1
        try:
            stager.stage_core_source(repo_root=repo, source_root=source, destination=dest,
                                     baseline=baseline, checksums=checksums, patch_series=series,
                                     build_patches=[], overlay_files=[])
        except stager.StageError as exc:
            assert "already exists" in str(exc)
            assert (dest / "core" / "demo.txt").read_text(encoding="utf-8") == "final\n"
            assertions += 1
        else:
            raise AssertionError("staging must refuse to reuse an existing destination")

        conflict_repo, conflict_source, conflict_baseline, conflict_checksums, conflict_series = _fixture_repo(parent / "conflict", wrong_base=True)
        conflict_dest = conflict_repo / "vendor" / "work" / "stage-conflict"
        try:
            stager.stage_core_source(repo_root=conflict_repo, source_root=conflict_source, destination=conflict_dest,
                                     baseline=conflict_baseline, checksums=conflict_checksums,
                                     patch_series=conflict_series, build_patches=[], overlay_files=[])
        except stager.StageError as exc:
            assert "does not apply" in str(exc)
            assertions += 1
        else:
            raise AssertionError("patch against the wrong base must fail")
        assert not conflict_dest.exists()
        assertions += 1

        unordered = json.loads(json.dumps(series))
        unordered["patches"].reverse()
        unordered["patches"][0].pop("dependsOn", None)
        try:
            stager.stage_core_source(repo_root=repo, source_root=source,
                                     destination=repo / "vendor" / "work" / "unordered-series",
                                     baseline=baseline, checksums=checksums, patch_series=unordered,
                                     build_patches=[], overlay_files=[])
        except stager.StageError as exc:
            assert "increasing numeric order" in str(exc)
            assertions += 1
        else:
            raise AssertionError("unordered patches must be rejected")

        bad_series = json.loads(json.dumps(series))
        bad_series["patches"][1]["dependsOn"] = [bad_series["patches"][1]["path"]]
        try:
            stager.stage_core_source(repo_root=repo, source_root=source,
                                     destination=repo / "vendor" / "work" / "bad-series",
                                     baseline=baseline, checksums=checksums, patch_series=bad_series,
                                     build_patches=[], overlay_files=[])
        except stager.StageError as exc:
            assert "dependencies" in str(exc)
            assertions += 1
        else:
            raise AssertionError("forward/self dependency must fail before staging")

        for index, (patch_path, digest) in enumerate([("patches/core/003-missing.patch", "0" * 64),
                                                     (series["patches"][0]["path"], "0" * 64)]):
            drifted = json.loads(json.dumps(series))
            drifted["patches"] = [{"path": patch_path, "sha256": digest, "purpose": "negative case"}]
            try:
                stager.stage_core_source(repo_root=repo, source_root=source,
                                         destination=repo / "vendor" / "work" / f"bad-patch-{index}",
                                         baseline=baseline, checksums=checksums, patch_series=drifted,
                                         build_patches=[], overlay_files=[])
            except stager.StageError as exc:
                assert "missing or hash-mismatched" in str(exc)
                assertions += 1
            else:
                raise AssertionError(f"missing/hash-mismatched patch must fail: {patch_path}")

        wrong_checksum = dict(checksums)
        wrong_checksum["core-source"] = dict(checksums["core-source"], extractedTreeFingerprint="0" * 64)
        try:
            stager.stage_core_source(repo_root=repo, source_root=source,
                                     destination=repo / "vendor" / "work" / "wrong-source",
                                     baseline=baseline, checksums=wrong_checksum, patch_series=series,
                                     build_patches=[], overlay_files=[])
        except stager.StageError as exc:
            assert "fingerprint mismatch" in str(exc)
            assertions += 1
        else:
            raise AssertionError("source fingerprint drift must fail")
        assertions += _verify_build_correction_precedes_feature_patch(parent)
    return assertions


class PatchStagingTests(unittest.TestCase):
    def test_windows_autocrlf_and_patch_line_endings(self) -> None:
        for autocrlf in ("true", "false"):
            for source_eol in (b"\n", b"\r\n"):
                for patch_eol in (b"\n", b"\r\n"):
                    with self.subTest(autocrlf=autocrlf, source_eol=source_eol, patch_eol=patch_eol), tempfile.TemporaryDirectory() as temp:
                        repo, source, baseline, checksums, series = _fixture_repo(Path(temp))
                        subprocess.run(["git", "init", "-q", str(repo)], check=True)
                        subprocess.run(["git", "-C", str(repo), "config", "core.autocrlf", autocrlf], check=True)
                        (repo / ".gitattributes").write_text("* text=auto\ncore/** -text !eol\n", newline="\n")
                        (source / "demo.txt").write_bytes(b"base" + source_eol)
                        count, fingerprint = stager.inventory_fingerprint(source)
                        checksums["core-source"].update(files=count, extractedTreeFingerprint=fingerprint)
                        for entry in series["patches"]:
                            path = repo / entry["path"]
                            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", patch_eol))
                            entry["sha256"] = stager.file_sha256(path)
                        receipt = stager.stage_core_source(
                            repo_root=repo, source_root=source, destination=repo / "vendor/work/staged",
                            baseline=baseline, checksums=checksums, patch_series=series,
                            build_patches=[], overlay_files=[])
                        self.assertEqual((repo / "vendor/work/staged/core/demo.txt").read_text(), "final\n")
                        self.assertEqual(receipt["sourceInventorySha256Before"], receipt["sourceInventorySha256After"])

    def test_baseline_uses_active_series_and_never_discovers_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo, source, baseline, checksums, series = _fixture_repo(Path(temp))
            (repo / "vendor" / "checksums.json").write_text(json.dumps(checksums), encoding="utf-8")
            active = repo / "patches" / "core" / "series.json"
            candidate = repo / "patches" / "core" / "series-word-candidate.json"
            candidate.write_text(json.dumps(series), encoding="utf-8")
            active.write_text(json.dumps(dict(series, patches=[])), encoding="utf-8")
            with patch.object(downloader, "ROOT", repo), patch.object(downloader, "LOCK_FILE", repo / "vendor" / "checksums.json"):
                downloader.write_baseline(series["coreRef"], "c" * 40)
                output = repo / "ci" / "baseline.json"
                self.assertEqual(json.loads(output.read_text())["corePatches"], [])
                # Promotion is explicit and retains the hash-locked order.
                active.write_text(json.dumps(series), encoding="utf-8")
                downloader.write_baseline(series["coreRef"], "c" * 40)
                expected = [entry["path"] for entry in series["patches"]]
                self.assertEqual(json.loads(output.read_text())["corePatches"], expected)
                saved = output.read_bytes()
                (repo / expected[0]).write_text("tampered", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "hash-mismatched"):
                    downloader.write_baseline(series["coreRef"], "c" * 40)
                self.assertEqual(output.read_bytes(), saved)
                with self.assertRaisesRegex(RuntimeError, "requested baseline"):
                    downloader.write_baseline("d" * 40, "c" * 40)

    def test_fixture_staging_contract(self) -> None:
        self.assertGreater(verify_patch_staging({}), 0)

    def test_downloader_rejects_non_official_existing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "core"
            source.mkdir()
            file = source / "file.txt"
            file.write_text("official\n", encoding="utf-8")
            count, fingerprint = stager.inventory_fingerprint(source)
            lock = {"files": count, "extractedTreeFingerprint": fingerprint}
            self.assertEqual(downloader.verify_official_core_source(source, lock), (count, fingerprint))
            file.write_text("previously patched\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
                downloader.verify_official_core_source(source, lock)


if __name__ == "__main__":
    unittest.main()
