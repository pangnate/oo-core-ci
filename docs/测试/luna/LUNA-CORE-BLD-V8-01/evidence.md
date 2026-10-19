# LUNA-CORE-BLD-V8-01 evidence — Windows V8 SDK

Date: 2026-10-19
Status: IN_PROGRESS — lock, bootstrap/publish/restore scripts and Actions workflow are ready; actual Release publication and hosted reuse probe are pending.

## Locked inputs

- Core: `ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`.
- build_tools: `a9f9895b172b09595abcafe85d56fab163f9ecb7`.
- V8 branch-heads/8.9 currently resolves to `a2d8eca22ad478a95ca67bb2421a9a2535113925`; this exact commit is pinned in `config/v8-windows.lock.json`.
- depot_tools: `82b992a1656d7d1cd0ee3cbea8ff609ffdfed380`.
- Target ABI: MSVC v142 14.29, x64, dynamic CRT; GN enables pointer compression and static monolithic V8 without external startup data.

## Implementation

- `scripts/build_v8_windows_sdk.py` clones the pinned depot_tools revision into a new owned directory under `vendor/work`, synchronizes V8 dependencies at the pinned V8 commit, applies checked Windows compatibility edits only to that disposable dependency source, builds `v8_monolith`, compiles and runs a standalone C++ probe that evaluates `1 + 2`, then packages public headers, library, manifest, provenance, and SHA256.
- `.github/workflows/build-v8-windows.yml` now runs only by manual dispatch, defaults to `reuse`, requires the v142 toolset for the native SDK probe, and publishes a fixed Release after build/import verification.
- No Core source or `patches/core` files were modified.

## Local static checks

- `python -m py_compile scripts/build_v8_windows_sdk.py tests/core-features/test_v8_windows_sdk.py` — passed.
- `python -B -m unittest discover -s tests/core-features -p 'test_*.py' -v` — 44 tests passed, including the probe include-path regression check and SDK reuse fixtures.
- `python scripts/verify_vendor.py --platform windows` — passed.
- `git diff --check` — passed.
- `git ls-remote https://chromium.googlesource.com/v8/v8.git refs/branch-heads/8.9` — branch resolved to the pinned V8 commit above.

## Pending hosted acceptance

### SDK publication and reuse adjustment

- The workflow separates explicit `build`, `promote` and default `reuse`. A first successful run artifact can be imported with no V8 compilation; import checks completed/success, repository, workflow path and the original commit's complete V8 lock. The legacy package layout is accepted without rewriting archive bytes.
- `scripts/manage_v8_windows_sdk.py` derives a release tag from canonical lock SHA256, validates the archive plus per-entry hashes and the extracted headers, checks exact revisions/GN/CRT/ABI, and restores without any fetch/GN/Ninja fallback. Release upload uses draft-first publication, refuses replacement, and redownloads to verify the published bytes. SDK lock/sdkId must change for a new binary recipe.
- `.github/actions/restore-v8-windows-sdk/action.yml` is the public consumer entrypoint. It uses an exact cache key with no restore-key fallback; a missing cache downloads the fixed Release. Cache and Release payloads receive the same verification. Optional installation only fills the existing qmake dependency layout inside owned Core staging and records SDK input hashes; official `core/` source remains unchanged.
- New build manifests use relocatable SDK-relative paths. V8 monolith compilation now streams Ninja output instead of buffering it until completion.
- Local unit fixtures cover old/new archive restore, header/archive tampering, GN/ABI/revision mismatch, failed/drifted source run rejection, missing-release behavior, auth/network errors, archive traversal, cache-only restore, staging ownership/source protection, publish/probe binding and refusing existing releases. These are Python fixtures/mocked GitHub responses, not native V8 build or hosted acceptance.
- Current working-tree checks: `python -B -m unittest discover -s tests/core-features -p 'test_*.py' -v` passed 44 tests, including fixed-Release cache miss followed by matching cache-hit restore; Python in-memory compile checks and `git diff --check` passed. Workflow actionlint v1.7.7 passed. `git diff --exit-code -- core build_tools patches/core overlays/core` was empty. Concurrent probe include-path edits in the shared checkout were preserved; this adjustment does not claim ownership of those edits.
- No local C++ compilation or Release publication was performed for this adjustment. Run `39254838375` failed after `v8_monolith.lib` completed, so it cannot be used as a `promote` source. Run `39265530451` on `3521e1c1` then built the monolith and linked `v8_probe.exe`, but the probe exited with Windows status `3221225477` (`0xC0000005`, access violation). The probe passed `nullptr` to `InitializeICUDefaultLocation` and `InitializeExternalStartupData`; Core's V8 embedder passes the executable path so V8 can locate ICU/startup data. The repair now passes `argv[0]` to both APIs. This is a source-level diagnosis that still requires a new hosted run to confirm. Run #11 produced no SDK artifact or Release and cannot be promoted. The card stays IN_PROGRESS until a new Actions build passes the probe and manifest checks, publishes the fixed Release, downloads it for verification, and a clean hosted reuse probe passes.

The first hosted run was `39247715707` on commit `c03593ae`; VS 2022 with MSVC v142 14.29 was found. Run `39247920954` on `fa9b84d4` confirmed absolute work paths were required. Runs `39248225394`/`39248482317` exposed the pinned depot_tools Python bootstrap requirement. The script now applies the build_tools V8 bootstrap manifest edits, invokes `bootstrap/win_tools.bat` explicitly with depot_tools auto-update disabled, and requires its generated Python pointer before V8 fetch. Run `39248827643` completed bootstrap but vpython's bundled `virtualenv 15.1` failed under Python 3.11 before V8 fetch (`TypeError` in `virtualenv.py` path handling); the documented vpython bypass sentinel now uses the already-pinned Python installation directly. Run `39249186345` progressed through bootstrap and V8 fetch, then Git could not create long paths in the nested `buildtools/third_party/libc++` checkout. Run `39254838375` on `550f0d77` successfully completed `v8_monolith.lib` at `[1700/1700]`, then probe compilation failed with C1083 for `libplatform/libplatform-export.h`. The probe had passed `/I<v8-root>` but lacked `/I<v8-root>/include`; the current script supplies both roots. Native link/runtime probe, manifest validation, artifact upload/download, Release publication and fixed SDK reuse remain unverified on Actions.
