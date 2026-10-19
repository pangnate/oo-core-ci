# LUNA-CORE-BLD-01-FIX02 evidence — isolated Core source staging

Date: 2026-10-19  
Status: PASS for pinned official-source validation and isolated staging on Windows; no Core build or GitHub Actions run.

## Official source identity

- Source: `ONLYOFFICE/core@ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`.
- Downloaded the pinned codeload archive into a task-owned temporary path without replacing the existing `core/` tree. Archive SHA-256: `9887c859b5a1f9e461895d985b5238bdb9818ba4599d85fa394f703f00a3f8a6`.
- Safe extraction yielded 21,117 files and inventory fingerprint `cc16fb1824a7788140aa76064c6714d803e51deb90205fe8d625664f508ab5f6`. Both archive and extraction hashes are now locked in `vendor/checksums.json`.
- The pre-existing local `core/` tree has a different fingerprint (`bd93e508a736b8c99948073354262fc883548c7ff4e34d8d395b54f64d739953`). It was preserved and is rejected as a pinned official source by the downloader/stager. This detects the old build/brand changes in that local snapshot instead of treating them as official source.

## Staging behavior

- A complete clean-source staging run applied, in order: `scripts/patch_x2t_sln.py`, the ordered feature patch series (currently empty), then `Common/copyright.txt` overlay.
- Receipt source fingerprint before and after staging matched exactly. The staged tree contains 21,117 files and fingerprints to `52c0c24ea72fade14c4e36e3bc1572873dc226906e1032e3aa216237c4afd4d7`; this is pinned in the Windows source profile.
- A synthetic two-patch series verified ordered replay and deterministic output. A separate fixture verified build corrections run before feature patches. Existing destination, bad source hash, wrong patch base, duplicate/invalid ordering, invalid dependency, missing or drifted patch, and non-official existing source are rejected. Failed owned staging output is removed; successful output retains an ownership marker for safe cleanup.
- `git diff -- core` remained empty. The existing ignored local `core/` inventory was unchanged by the full clean-source run.

## Validation

- `python scripts/core_features.py --case patch-staging --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json --timeout 120` — PASS, 16 assertions.
- `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` — PASS, 20 tests.
- `python scripts/verify_vendor.py --platform windows` — PASS.

This card did not compile Core or X2T and did not run GitHub Actions. The local Windows source tree is intentionally left untouched; future CI must fetch the pinned pristine source into a clean checkout, stage it, then build the staged tree.
