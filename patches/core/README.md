# Project-owned Core patches

Keep code changes that must survive an official Core update as ordered `NNN-name.patch` files in this directory. Use the pinned official Core source as the input and replay project changes in an isolated staging tree as described below.

Project policy: keep the official `core/` input unchanged. Commit feature patches, tests, and build tooling; do not commit a patched Core source snapshot. Patch paths remain relative to the repository root with the `core/` prefix. Edit a project-owned staging copy, generate the narrow patch there, replay the complete on-disk patch set in a fresh staging tree, and test that tree. Do not run the old diff recipe against the authoritative input directory.

Keep patches narrow and ordered after the X2T CI build correction; apply intentional branding overlays only in staging. Record the official base, patch order/dependencies, and hashes. Upstream synchronization replaces only the official input; replay conflicts fail explicitly and require adapting the patch. Never skip a patch or silently renumber persisted protocols to make an upgrade pass.

`download.py` now fetches only the pinned official input and refuses to replace or reuse a Core tree whose extraction fingerprint differs. `scripts/stage_core_source.py` makes a fresh build copy under `vendor/work`, applies the X2T build correction first, then the hash-locked ordered feature patch series and branding overlays, and writes a receipt with source/staging fingerprints. `patch-staging` verifies deterministic replay, order, conflicts, and source preservation. See the [Core task cards](../../docs/Core三端功能改造_Luna开发任务卡_2026-10-19.md).

## Unbuilt Word candidate series

`series-word-candidate.json` is an explicit opt-in, source-only candidate set for CORE-03/04/05/07. It does not change the default `series.json` or the running POC baseline. Pass its parsed JSON as `patch_series` to `stage_core_source` in a fresh owned destination. SOURCE-READY is not compilation or CODEC acceptance. The downloader and baseline test now read only the default `series.json`, rather than discovering patches from directory contents. The downloader validates the default series source/order/dependencies and file hashes before writing the baseline. Promotion requires explicit review and a new feature profile; never infer readiness from file presence.
