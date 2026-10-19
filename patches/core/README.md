# Project-owned Core patches

Keep code changes that must survive an official Core update as ordered `NNN-name.patch` files in this directory. Use the pinned official Core source as the input and replay project changes in an isolated staging tree as described below.

Project policy: keep the official `core/` input unchanged. Commit feature patches, tests, and build tooling; do not commit a patched Core source snapshot. Patch paths remain relative to the repository root with the `core/` prefix. Edit a project-owned staging copy, generate the narrow patch there, replay the complete on-disk patch set in a fresh staging tree, and test that tree. Do not run the old diff recipe against the authoritative input directory.

Keep patches narrow and ordered after the X2T CI build correction; apply intentional branding overlays only in staging. Record the official base, patch order/dependencies, and hashes. Upstream synchronization replaces only the official input; replay conflicts fail explicitly and require adapting the patch. Never skip a patch or silently renumber persisted protocols to make an upgrade pass.

The existing `download.py` applies patches/overlays to its source directory, and the current workflow builds that snapshot. This implementation must be changed by `LUNA-CORE-BLD-01-FIX02` before feature development uses it: stage sources separately, make build-root arguments explicit, and prove input fingerprints plus the pre-existing `git diff -- core` remain unchanged. Preserve current user changes; do not reset the input tree as part of this transition. See the [Core task cards](../../docs/Core三端功能改造_Luna开发任务卡_2026-10-19.md).
