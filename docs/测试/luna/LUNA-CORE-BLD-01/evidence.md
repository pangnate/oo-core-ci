# LUNA-CORE-BLD-01 evidence — Windows dependency lock and gaps

Date: 2026-10-19
Status: PASS for source/input inventory and explicit gaps; no dependency compilation or hosted-runner guarantee.

## Findings

- Core and build_tools refs/tree hashes agree with `ci/baseline.json` and `vendor/checksums.json`.
- Windows Qt 5.15.2, Boost 1.72.0, ICU 74.2 and Brotli archives exist and match their lock hashes. In response to the follow-up instruction, Boost was upgraded from 1.58 to 1.72: `vendor/detected-deps.json`, `vendor/checksums.json`, the dependency lock and the archive now agree with the pinned build_tools Windows recipe and default `config/deps.json`. The obsolete 1.58 archive was removed. Hash-verified archives are not claimed as successfully compiled libraries.
- `build_tools/scripts/core_common/modules/v8_89.py` fetches V8 branch `remotes/branch-heads/8.9` and clones depot_tools without a pinned revision. The checked-in `core/Common/3dParty/v8_89` contains only `.gitignore`; no V8 headers/library/SDK, GN lock or probe exists.
- Core source anchors show FreeType 2.10.4, HarfBuzz, Brotli and OpenJPEG are part of the pinned source/qmake graph, but no new graphics/PdfFile/doctrenderer output has been built from this checkout.
- The current Windows PowerShell does not expose `cl.exe`, MSBuild, qmake or 7-Zip. The Qt archive is hash-verified only. The GitHub Windows job separately needs a toolchain and archive-extractor probe.
- Linux vendor assets are not accepted as inputs for the Windows POC; later Linux assets remain deferred to the user-designated source.

## Verification

- `python scripts/verify_vendor.py --platform windows` passed with the 1.72 archive.
- `python scripts/core_features.py --case build-deps-contract --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json --timeout 120` passed with 38 assertions after the Boost 1.72 update.
- `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` passed (10 tests).
- `git diff --check` passed. No Core files or feature patches changed.

## Boundary

This card defines the inputs and what is still unavailable. It does not prove the V8 or graphics/PDF DLL closure can compile. The next cards must validate reusable SDK inputs, isolate Core patch staging and obtain the required Windows dependencies before build acceptance.
