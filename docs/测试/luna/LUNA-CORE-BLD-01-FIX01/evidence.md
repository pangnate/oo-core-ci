# LUNA-CORE-BLD-01-FIX01 evidence — SDK input and recipe primitives

Date: 2026-10-19
Status: PASS for reusable manifest, archive, process and tool-probe primitives; no V8/Core build claim.

## Deliverables

- `config/sdk-manifest.schema.json` specifies development/build/runtime SDK manifests for the supported platform tuple and verified/unavailable/planned input states.
- `scripts/feature_deps/common.py` validates manifest identity and hashes, rejects unverified required roles and paths outside approved roots, safely extracts regular ZIP/TAR members into a new owned directory, runs argument-array recipes with timeout/process-tree cleanup, and probes Windows VS/v142/Qt paths and versions.
- `tests/core-features/test_build_deps_io.py` covers hash drift, wrong platform/ABI-kind, unverified inputs, path escape, ZIP traversal/symlink/size limits, destination reuse, timeout, schema expectations and reproducible missing-tool reporting.
- Source profile locks the SDK schema. No dependencies were downloaded or unpacked into Core by this card.

## Verification

- `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` passed (18 tests).
- `python scripts/core_features.py --case build-deps-io --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json --timeout 120` passed with 9 assertions.
- `python scripts/feature_deps/common.py --probe-windows --allow-missing` produced a structured report: local `vswhere.exe` and extracted Qt `qmake.exe` are not discoverable. This is the explicit local toolchain gap for the later GitHub runner probe.
- `git diff --check` passed. No Core source files or feature patches changed.

## Boundary

The archive test uses a tiny generated fixture; it does not compile any SDK. Local VS/Qt were unavailable, and the probe correctly returns unavailable instead of fabricating tool versions. Later SDK cards and the Windows Actions job must provide and exercise verified build inputs.
