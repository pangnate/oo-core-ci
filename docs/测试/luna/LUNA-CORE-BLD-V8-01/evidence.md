# LUNA-CORE-BLD-V8-01 evidence — Windows V8 SDK

Date: 2026-10-19
Status: IN_PROGRESS — lock, bootstrap script, static checks, and Actions workflow are ready; hosted build/probe is pending.

## Locked inputs

- Core: `ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`.
- build_tools: `a9f9895b172b09595abcafe85d56fab163f9ecb7`.
- V8 branch-heads/8.9 currently resolves to `a2d8eca22ad478a95ca67bb2421a9a2535113925`; this exact commit is pinned in `config/v8-windows.lock.json`.
- depot_tools: `82b992a1656d7d1cd0ee3cbea8ff609ffdfed380`.
- Target ABI: MSVC v142 14.29, x64, dynamic CRT; GN enables pointer compression and static monolithic V8 without external startup data.

## Implementation

- `scripts/build_v8_windows_sdk.py` clones the pinned depot_tools revision into a new owned directory under `vendor/work`, synchronizes V8 dependencies at the pinned V8 commit, applies checked Windows compatibility edits only to that disposable dependency source, builds `v8_monolith`, compiles and runs a standalone C++ probe that evaluates `1 + 2`, then packages public headers, library, manifest, provenance, and SHA256.
- `.github/workflows/build-v8-windows.yml` runs on relevant `main` pushes or manual dispatch, requires the v142 toolset, validates artifact metadata, and uploads the SDK.
- No Core source or `patches/core` files were modified.

## Local static checks

- `python -m py_compile scripts/build_v8_windows_sdk.py tests/core-features/test_v8_windows_sdk.py` — passed.
- `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` — 23 tests passed.
- `python scripts/verify_vendor.py --platform windows` — passed.
- `git diff --check` — passed.
- `git ls-remote https://chromium.googlesource.com/v8/v8.git refs/branch-heads/8.9` — branch resolved to the pinned V8 commit above.

## Pending hosted acceptance

The Windows build, native link/runtime probe, manifest validation, artifact upload/download, and final SDK hash verification have not run yet. The user does not compile locally; this card remains IN_PROGRESS until the GitHub Actions run succeeds and its artifact is verified.
